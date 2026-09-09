"""Arm-B COORDINATOR driver (inferswarm00, CPU-only, metadata-only).

Reconstructs the accepted Coordinator control role over the physical
boundary: freezes the plan/requirements (validating self-identity and the
byte-pinned digests), ingests node inventory snapshots, derives per-
participant deltas, and issues exact acquisition tickets.

Every document crossing this boundary is walked for raw bytes payloads —
coordinator_bulk_artifact_bytes_observed derives from that counter, never
from architecture. No torch import; stdlib only.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, "/srv/inferswarm/state/arm-b/scripts")
sys.path.insert(0, str(Path(__file__).resolve().parent))

import armb_plan_core as core  # noqa: E402

ACCEPTED_MAIN = "5179c41232051e7455b778ddb8876a6539f4cb04"
CHECKPOINT_SHA256 = "5a84cb313260ac447237b890387116dfa8682e49a6b44bc585ae8353abbff18d"
SOURCE_DESCRIPTOR = {"source_id": "issue117-origin",
                     "endpoint": "file:///srv/models/gemma-r6"}
AUTHORIZATION_SCHEMA = "inferswarm.issue99.realization-authorization/1"


def _walk_for_bytes(value, sink):
    if isinstance(value, (bytes, bytearray)):
        sink.append(len(value))
    elif isinstance(value, dict):
        for k, v in value.items():
            _walk_for_bytes(k, sink)
            _walk_for_bytes(v, sink)
    elif isinstance(value, (list, tuple, set)):
        for v in value:
            _walk_for_bytes(v, sink)


class BytesGuard:
    def __init__(self):
        self.bytes_observed = 0

    def guard(self, *values):
        sink = []
        for v in values:
            _walk_for_bytes(v, sink)
        if sink:
            self.bytes_observed += sum(sink)
            raise RuntimeError("SOURCE_UNAUTHORIZED bulk bytes at coordinator")


def issue_tickets(plan_path, requirements_path, inventory_paths, out_dir):
    coordinator = BytesGuard()
    plan = json.loads(Path(plan_path).read_text())
    requirements = json.loads(Path(requirements_path).read_text())
    coordinator.guard(plan, requirements)
    core.validate_self_identity(plan, identity_field="plan_digest")
    core.validate_self_identity(requirements, identity_field="requirements_digest")
    if requirements["plan_digest"] != plan["plan_digest"]:
        raise RuntimeError("RECONCILIATION_MISMATCH requirements/plan")
    if plan["model"]["checkpoint_authority_sha256"] != CHECKPOINT_SHA256:
        raise RuntimeError("checkpoint authority drift")

    # ingest verified node inventory snapshots (metadata only)
    snapshots = {}
    generation = 1
    for path in inventory_paths:
        snap = json.loads(Path(path).read_text())
        coordinator.guard(snap)
        node_id = snap["node_id"]
        for obj in snap["verified_objects"]:
            if not obj["byte_digest_verified"]:
                raise RuntimeError(
                    f"UNVERIFIED_OBJECT_PUBLICATION_REFUSED {node_id}")
        snapshots[node_id] = {"snapshot": snap, "sequence": snap["sequence"]}

    tickets_out = []
    deltas_out = []
    for participant in requirements["participants"]:
        node_id = participant["node_id"]
        snap = snapshots[node_id]["snapshot"]
        local = {(o["content_digest"], o["length"])
                 for o in snap["verified_objects"]}
        required = participant["required_artifacts"]
        delta = {
            "epoch": plan["epoch"], "generation": generation,
            "plan_digest": plan["plan_digest"],
            "participant_id": participant["participant_id"],
            "node_id": node_id,
            "participant_requirements_digest":
                participant["participant_requirements_digest"],
            "inventory_sequence": snap["sequence"],
            "required_artifact_ids": sorted(r["artifact_id"] for r in required),
            "local_artifact_ids": sorted(
                r["artifact_id"] for r in required
                if (r["content_digest"], r["length"]) in local),
            "missing_artifact_ids": sorted(
                r["artifact_id"] for r in required
                if (r["content_digest"], r["length"]) not in local),
        }
        delta["delta_digest"] = core.self_digest(delta, identity_field="delta_digest")
        deltas_out.append(delta)
        records = {r["artifact_id"]: r for r in required}
        for artifact_id in delta["missing_artifact_ids"]:
            record = records[artifact_id]
            authorization = {
                "schema": AUTHORIZATION_SCHEMA,
                "plan_digest": plan["plan_digest"],
                "requirements_digest": requirements["requirements_digest"],
                "eligible_sources": [dict(SOURCE_DESCRIPTOR)],
                "participants": {
                    p["participant_id"]: {
                        "required_artifact_ids": sorted(
                            r["artifact_id"] for r in p["required_artifacts"]),
                        "eligible_source_ids": [SOURCE_DESCRIPTOR["source_id"]],
                    } for p in requirements["participants"]},
            }
            authorization["authorization_digest"] = core.self_digest(
                authorization, identity_field="authorization_digest")
            coordinator.guard(authorization)
            ticket = {
                "epoch": plan["epoch"], "plan_digest": plan["plan_digest"],
                "generation": generation,
                "participant_id": participant["participant_id"],
                "node_id": node_id,
                "participant_requirements_digest":
                    participant["participant_requirements_digest"],
                "delta_digest": delta["delta_digest"],
                "artifact_id": artifact_id,
                "source": dict(SOURCE_DESCRIPTOR), "mode": "ORIGIN",
                "candidates": [],
                "attempt_number": len(tickets_out) + 1,
                "authorization": authorization,
                "artifact_record": record,
            }
            ticket["attempt_digest"] = core.self_digest(
                ticket, identity_field="attempt_digest")
            coordinator.guard(ticket)
            tickets_out.append(ticket)

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "coordinator-deltas.json").write_bytes(
        core.canonical_json_bytes({"deltas": deltas_out}))
    by_node = {}
    for t in tickets_out:
        by_node.setdefault(t["node_id"], []).append(t)
    for node_id, ts in by_node.items():
        (out / f"tickets-{node_id}.json").write_bytes(core.canonical_json_bytes(ts))
    record = {
        "schema": "inferswarm.issue117.arm-b.coordinator-record/1",
        "coordinator_host": "inferswarm00",
        "plan_digest": plan["plan_digest"],
        "tickets_issued": len(tickets_out),
        "deltas": len(deltas_out),
        "coordinator_bulk_artifact_bytes_observed": coordinator.bytes_observed,
        "cuda_initialized": 0,
        "torch_imported": False,
    }
    (out / "coordinator-record.json").write_bytes(core.canonical_json_bytes(record))
    print(json.dumps(record, indent=1))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", required=True)
    ap.add_argument("--requirements", required=True)
    ap.add_argument("--inventories", nargs="+", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    return issue_tickets(args.plan, args.requirements, args.inventories, args.out)


if __name__ == "__main__":
    raise SystemExit(main())
