"""Arm-B node-side acquisition driver (runs on each participant node).

Consumes the frozen authorization tickets issued by the CPU-only
Coordinator (inferswarm00) and drives the ACCEPTED #99 acquisition engine
(acquire_artifact + NodeArtifactCache) against the authorized Source,
publishing verified objects into the canonical cold cache root.

Usage:
  armb_node_acquire.py --role source|participant
      --tickets <coordinator-issued tickets.json>
      --cache-root /srv/inferswarm/cache/issue117
      --transport local|http --http-endpoint http://10.0.0.141:18486

The transport adapters implement the accepted LocalFileSource read contract
(seek + exact-length read) against the authorized source descriptor
file:///srv/models/gemma-r6: local read on the SOURCE host, HTTP Range GET
elsewhere. All bytes move through acquire_artifact under Coordinator
authorization; verify-then-publish is the engine's own.
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, "/srv/inferswarm/state/arm-b/scripts")
sys.path.insert(0, str(Path(__file__).resolve().parent))

from issue99_artifact_core import (  # noqa: E402
    AcquisitionLedger, NodeArtifactCache, acquire_artifact,
)
import armb_plan_core as core  # noqa: E402

SOURCE_ROOT = "/srv/models/gemma-r6"


class LocalReadTransport:
    """Accepted LocalFileSource read contract, local filesystem."""

    source_id = "issue117-origin"
    kind = "local-file"

    def __init__(self):
        self.access_log = []

    def descriptor(self):
        return {"source_id": self.source_id,
                "endpoint": Path(SOURCE_ROOT).resolve().as_uri()}

    def read(self, origin, offset, length):
        import threading
        with open(f"{SOURCE_ROOT}/{origin['source_object']}", "rb") as h:
            h.seek(offset)
            data = h.read(length)
        if len(data) != length:
            raise RuntimeError("SOURCE_OBJECT_UNAVAILABLE short read")
        self.access_log.append({"source_object": origin["source_object"],
                                "offset": offset, "length": length})
        return data


class HttpRangeTransport:
    """Accepted source read contract over HTTP Range GET."""

    source_id = "issue117-origin"
    kind = "operator-local-http"

    def __init__(self, endpoint):
        self.endpoint = endpoint.rstrip("/")
        self.access_log = []

    def descriptor(self):
        return {"source_id": self.source_id,
                "endpoint": Path(SOURCE_ROOT).resolve().as_uri()}

    def read(self, origin, offset, length):
        url = f"{self.endpoint}/{origin['source_object']}"
        req = urllib.request.Request(
            url, headers={"Range": f"bytes={offset}-{offset + length - 1}"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = resp.read()
        if len(data) != length:
            raise RuntimeError(
                f"SOURCE_OBJECT_UNAVAILABLE short read {len(data)} != {length}")
        self.access_log.append({"source_object": origin["source_object"],
                                "offset": offset, "length": length})
        return data


class TicketAuthority:
    """Node-side guard implementing CoordinatorAuthority.check_acquisition.

    Validates the ticket self-identity, exact node binding, exact source
    descriptor, and artifact-record equality against the frozen requirement
    entry carried by the ticket — the same fail-closed checks the accepted
    in-process boundary performs, reconstructed from the issued ticket.
    """

    def __init__(self, ticket, requirements):
        core.validate_self_identity(ticket, identity_field="attempt_digest")
        self.ticket = ticket
        participant = next(
            p for p in requirements["participants"]
            if p["participant_id"] == ticket["participant_id"])
        if ticket["participant_requirements_digest"] != \
                participant["participant_requirements_digest"]:
            raise RuntimeError("RECONCILIATION_MISMATCH participant digest")
        records = {r["artifact_id"]: r for r in participant["required_artifacts"]}
        self.record = records[ticket["artifact_id"]]
        auth = ticket["authorization"]
        core.validate_self_identity(auth, identity_field="authorization_digest")

    def check_acquisition(self, *, participant_id, artifact_record, source_descriptor):
        t = self.ticket
        if participant_id != t["participant_id"]:
            raise RuntimeError("SOURCE_UNAUTHORIZED participant")
        if artifact_record.get("artifact_id") != t["artifact_id"]:
            raise RuntimeError("UNDECLARED_REQUIREMENT_ARTIFACT artifact")
        if artifact_record != self.record:
            raise RuntimeError("PROVENANCE_IDENTITY_MISMATCH record drift")
        if dict(source_descriptor) != t["source"]:
            raise RuntimeError("SOURCE_UNAUTHORIZED source descriptor")
        if dict(source_descriptor) not in t["authorization"]["eligible_sources"]:
            raise RuntimeError("SOURCE_UNAUTHORIZED eligible set")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tickets", required=True)
    ap.add_argument("--requirements", required=True)
    ap.add_argument("--cache-root", default="/srv/inferswarm/cache/issue117")
    ap.add_argument("--transport", choices=("local", "http"), required=True)
    ap.add_argument("--http-endpoint", default=None)
    ap.add_argument("--node-id", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--chunk-bytes", type=int, default=32 * 1024 * 1024)
    args = ap.parse_args()

    tickets = json.loads(Path(args.tickets).read_text())
    requirements = json.loads(Path(args.requirements).read_text())
    core.validate_self_identity(requirements, identity_field="requirements_digest")

    if args.transport == "local":
        transport = LocalReadTransport()
    else:
        transport = HttpRangeTransport(args.http_endpoint)

    cache = NodeArtifactCache(Path(args.cache_root))
    ledger = AcquisitionLedger()
    results = []
    for ticket in tickets:
        if ticket["node_id"] != args.node_id:
            continue  # this ticket belongs to the sibling stage on this node
        authority = TicketAuthority(ticket, requirements)
        result = acquire_artifact(
            cache=cache, source=transport, record=authority.record,
            authorization=authority, participant_id=ticket["participant_id"],
            ledger=ledger, chunk_bytes=args.chunk_bytes)
        results.append({
            "participant_id": ticket["participant_id"],
            "artifact_id": ticket["artifact_id"],
            "attempt_digest": ticket["attempt_digest"],
            "status": result["status"], "bytes": result.get("bytes", 0),
        })
        print(f"{ticket['participant_id']} {ticket['artifact_id'][:30]} "
              f"{result['status']} {result.get('bytes', 0)}", flush=True)

    # durable node record
    records_by_id = {}
    participants = {}
    for p in requirements["participants"]:
        participants[p["participant_id"]] = {
            "required_artifact_bytes": p["required_artifact_bytes"],
            "declared_state_ids": sorted(
                set(p["required_logical_state"]["assigned"])
                | set(p["required_logical_state"]["declared_shared"])
                | set(p["required_logical_state"]["required_metadata"])),
        }
        for r in p["required_artifacts"]:
            records_by_id[r["artifact_id"]] = r
    doc = ledger.document(records_by_artifact_id=records_by_id,
                          participants=participants)
    doc["node_id"] = args.node_id
    doc["acquisition_results"] = results
    doc["transport"] = {"kind": transport.kind,
                        "descriptor": transport.descriptor(),
                        "requests": len(transport.access_log),
                        "request_bytes": sum(r["length"] for r in transport.access_log)}
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_bytes(core.canonical_json_bytes(doc))
    print("ledger written:", args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
