#!/usr/bin/env python3
"""Issue #215 — final-boot full canonical check assembler (Phase 4 final step).

Assembles the retained harness outputs (fresh V2-C discovery, authorities,
per-die qualification/plan/conical records produced by the ACCEPTED
V2-A harness, byte-unchanged) into final-canonical.json. The assembler
derives every predicate from retained bytes; it executes nothing.

Inputs (under <out-root>/final-canonical/):
  discovery/DISCOVERY-INVENTORY-R3.json, DISCOVERY-BINDINGS-R3.json (+ raw)
  authorities/AUTHORITY-V2C-FINAL-{A,B}.json
  die-{a,b}/qualification/qualification.json
  die-{a,b}/canonical/canonical-execution.json (+ raw stdout/stderr)
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

CAMPAIGN_ID = "issue215-v2c-v340l-platform-stability-v1"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-root", required=True)
    parser.add_argument("--boot-id", required=True)
    parser.add_argument("--repo-head", required=True)
    args = parser.parse_args()

    fc = Path(args.out_root) / "final-canonical"
    dies = {}
    for die in ("a", "b"):
        q = json.loads((fc / f"die-{die}/qualification/qualification.json").read_text())
        c = json.loads((fc / f"die-{die}/canonical/canonical-execution.json").read_text())
        # re-hash retained raw bytes against the recorded digests
        raw_dir = fc / f"die-{die}/canonical"
        stdout_sha = sha256_file(raw_dir / "stdout.txt")
        stderr_sha = sha256_file(raw_dir / "stderr.txt")
        dies[die] = {
            "qualification_result": q["result"],
            "offloaded_layers": q["offloaded_layers"],
            "canonical_result": c["result"],
            "plan_digest": c["plan_digest"],
            "byte_exact_visible_output": c["correctness"]["byte_exact_visible_output"],
            "accounting_three_tuple": {k: c["accounting"][k] for k in (
                "unexplained_persistent_host_mirror_bytes", "source_fetches_after_ready",
                "unplanned_state_movements")},
            "canonical_proof_digest": c["canonical_proof_digest"],
            "raw_stdout_sha256_rerashed": stdout_sha,
            "raw_stderr_sha256_rehashed": stderr_sha,
            "recorded_stdout_sha256": c["attempt"]["stdout_sha256"],
            "recorded_stderr_sha256": c["attempt"]["stderr_sha256"],
            "raw_bytes_match_record": (stdout_sha == c["attempt"]["stdout_sha256"]
                                       and stderr_sha == c["attempt"]["stderr_sha256"]),
        }
    inv = json.loads((fc / "discovery/DISCOVERY-INVENTORY-R3.json").read_text())
    bind = json.loads((fc / "discovery/DISCOVERY-BINDINGS-R3.json").read_text())
    record = {
        "schema": "inferswarm.v2c.final-canonical/1",
        "campaign_id": CAMPAIGN_ID,
        "boot_id": args.boot_id,
        "repo_head": args.repo_head,
        "discovery": {
            "inventory_sha256": sha256_file(fc / "discovery/DISCOVERY-INVENTORY-R3.json"),
            "bindings_sha256": sha256_file(fc / "discovery/DISCOVERY-BINDINGS-R3.json"),
            "measured_utc": inv.get("measured_utc"),
            "bindings": [{"selector": b["selector"], "pci_bdf": b.get("pci_bdf"),
                          "binding_status": b["binding_status"]} for b in bind["bindings"]],
        },
        "dies": dies,
        "result": ("PASS" if all(
            d["qualification_result"] == "PASS" and d["canonical_result"] == "PASS"
            and d["byte_exact_visible_output"]
            and all(v == 0 for v in d["accounting_three_tuple"].values())
            and d["raw_bytes_match_record"] for d in dies.values()) else "FAIL"),
        "captured_utc": datetime.now(timezone.utc).isoformat(),
    }
    (fc / "final-canonical.json").write_bytes(json.dumps(record, indent=1).encode() + b"\n")
    print(json.dumps({"boot_id": args.boot_id, "result": record["result"],
                      "dies": {k: v["canonical_result"] for k, v in dies.items()}}))
    return 0 if record["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
