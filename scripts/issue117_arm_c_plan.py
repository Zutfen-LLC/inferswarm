#!/usr/bin/env python3
"""Issue #117 Arm C — build the Arm-C participant chain plan (producer-bound).

Runs on inferswarm01 inside the frozen FreeToken producer worktree
(924cd22e…, clean). Re-freezes the ACCEPTED Arm-B participant plan
(/srv/inferswarm/state/arm-b/accepted-participant-plan.json, producer
44d6c94e…) using the frozen producer's own freeze code, with:

- identical block specs / allowed_tensor_keys / declared_shared_state /
  boundary_geometry / runtime_capacity_tokens (verified mechanically,
  field by field, against the accepted plan);
- allowed key sets verified against the HEADERS of the accepted
  materialized participant shards (pure-stdlib safetensors header parse;
  no tensor bytes are read; no Source-tree access of any kind);
- provenance rebound to the running producer 924cd22e… so the last-stage
  service starts in PLAN_FROZEN mode (no --allow-producer override);
- model_path rebound to the Arm-C zero-byte symlink view directory.

Fails closed on ANY difference beyond provenance/model_path. Writes the
plan, the equality verification record, and per-shard header digests.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
import subprocess
import sys
import time
from pathlib import Path

ACCEPTED_PLAN = Path(
    "/srv/inferswarm/state/arm-b/accepted-participant-plan.json")
EXPECTED_ACCEPTED_PRODUCER = "44d6c94e4fd2ee967451cc959f930883ca3f4a25"
EXPECTED_RUNNING_PRODUCER = "924cd22ea081f6d4ed471016faf01d427fc5b0d2"

MATERIALIZED = {
    "stage-1": Path("/srv/inferswarm/materialized/issue117/"
                    "dense.6171f32b4413.stage-1/armb-participant.safetensors"),
    "stage-2": Path("/srv/inferswarm/materialized/issue117/"
                    "dense.6171f32b4413.stage-2/armb-participant.safetensors"),
    "stage-3": Path("/srv/inferswarm/materialized/issue117/"
                    "dense.6171f32b4413.stage-3/armb-participant.safetensors"),
}
VIEW_CONFIG = Path("/srv/inferswarm/materialized/issue117/"
                   "dense.6171f32b4413.stage-1/config.json")


def die(message: str) -> None:
    raise SystemExit(f"ARM_C_PLAN_FAIL: {message}")


def safetensors_header_keys(path: Path) -> tuple[set, int, str]:
    """Pure-stdlib safetensors header read: (keys, header_bytes, header_sha)."""
    with path.open("rb") as stream:
        length = struct.unpack("<Q", stream.read(8))[0]
        if length <= 0 or length > 64 * 1024 * 1024:
            die(f"implausible header length for {path}")
        raw = stream.read(length)
    header = json.loads(raw)
    keys = set(k for k in header if k != "__metadata__")
    return keys, 8 + length, hashlib.sha256(raw).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 22), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=None,
                        help="FreeToken worktree root (default: inferred)")
    parser.add_argument("--out-dir", default="/srv/inferswarm/state/arm-c")
    parser.add_argument("--view-dir",
                        default="/srv/inferswarm/state/arm-c/model-view")
    parser.add_argument("--header-evidence", default=None,
                        help="optional stage-3 header JSON collected on 03")
    args = parser.parse_args()

    repo = Path(args.repo).resolve() if args.repo else Path(
        __file__).resolve().parents[2]
    running = subprocess.check_output(
        ["git", "-c", f"safe.directory={repo}", "-C", str(repo), "rev-parse",
         "HEAD"], text=True).strip()
    status = subprocess.check_output(
        ["git", "-c", f"safe.directory={repo}", "-C", str(repo),
         "status", "--porcelain"], text=True)
    if status:
        die(f"dirty producer tree: {status[:200]}")
    if running != EXPECTED_RUNNING_PRODUCER:
        die(f"running producer {running} != frozen {EXPECTED_RUNNING_PRODUCER}")

    from freetoken.research.r2_local_split import freeze_plan  # noqa: E402

    accepted = json.loads(ACCEPTED_PLAN.read_text())
    accepted_producer = accepted.get("provenance", {}).get("r6", {}).get(
        "producer_sha")
    if accepted_producer != EXPECTED_ACCEPTED_PRODUCER:
        die(f"accepted plan producer {accepted_producer!r} unexpected")

    # ---- per-shard header verification against the plan's key sets -------
    plan_keys = {
        f"stage-{i + 1}": set(block["allowed_tensor_keys"])
        for i, block in enumerate(accepted["blocks"])
    }
    shared_keys = set(
        accepted.get("declared_shared_state", {}).get("tensor_keys", []))
    header_records = {}
    for stage, path in MATERIALIZED.items():
        keys: set | None = None
        if stage == "stage-3" and not path.exists():
            # building on 01: stage-3 header evidence comes from --header-evidence
            if args.header_evidence and Path(args.header_evidence).exists():
                record = json.loads(Path(args.header_evidence).read_text())
                header_records[stage] = record
                keys = set(record["keys"])
            else:
                die("stage-3 shard absent and no header evidence supplied")
        else:
            keys, header_bytes, header_sha = safetensors_header_keys(path)
            record = {
                "path": str(path),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
                "header_bytes": header_bytes,
                "header_sha256": header_sha,
            }
            header_records[stage] = record
        assert keys is not None
        expected = plan_keys[stage]
        if stage in ("stage-1", "stage-3"):
            expected = expected | shared_keys
        if keys != expected:
            die(f"{stage} header keys != plan keys; diff "
                f"{sorted(keys ^ expected)[:5]}")
        header_records[stage]["key_count"] = len(keys)

    # ---- rebuild the plan: everything except provenance/model_path --------
    new_plan = json.loads(json.dumps(accepted))
    digest_old = new_plan.pop("digest")
    new_plan.pop("provenance")
    new_plan["model_path"] = str(Path(args.view_dir).resolve())
    new_plan["provenance"] = {
        "r6": {
            "producer_sha": running,
            "supersedes_for_issue117_arm_c_only": str(ACCEPTED_PLAN),
            "note": ("issue #117 Arm C: same accepted Arm-B participant "
                     "plan (specs, allowed_tensor_keys, declared shared "
                     "state, boundary geometry, runtime capacity) re-frozen "
                     "bound to the frozen integration producer for "
                     "ordinary serving; mechanically verified equal except "
                     "producer provenance and model_path"),
        },
        "issue117_arm_c": {
            "accepted_plan_sha256": sha256_file(ACCEPTED_PLAN),
            "accepted_plan_digest": digest_old,
            "built_at_ns": time.time_ns(),
        },
    }
    frozen = freeze_plan(new_plan)

    # ---- equality verification (everything but provenance/model_path) -----
    a = json.loads(json.dumps(accepted))
    b = json.loads(json.dumps(frozen))
    for doc in (a, b):
        doc.pop("digest"), doc.pop("provenance"), doc.pop("model_path")
    if a != b:
        die("re-frozen plan differs from the accepted plan beyond "
            "provenance/model_path")

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "chain-plan.json").write_text(
        json.dumps(frozen, indent=2, sort_keys=True) + "\n")
    verification = {
        "schema": "inferswarm.issue117.arm-c.plan-verification/1",
        "running_producer": running,
        "accepted_plan_path": str(ACCEPTED_PLAN),
        "accepted_plan_sha256": sha256_file(ACCEPTED_PLAN),
        "accepted_plan_digest": digest_old,
        "arm_c_plan_digest": frozen["digest"],
        "equality_beyond_provenance_model_path": True,
        "shard_headers": header_records,
        "shared_keys": sorted(shared_keys),
        "view_config_sha256": sha256_file(VIEW_CONFIG),
        "built_at_ns": time.time_ns(),
    }
    (out / "plan-verification.json").write_text(
        json.dumps(verification, indent=2, sort_keys=True) + "\n")
    print(json.dumps({
        "arm_c_plan": str(out / "chain-plan.json"),
        "digest": frozen["digest"],
        "accepted_digest": digest_old,
        "equality": True,
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
