#!/usr/bin/env python3
"""Issue #232 — helper: build the gate's cold-proof JSON from retained
census cold-cycle evidence rows (Phase 3 input assembly; reads only
retained bytes, writes the bound document)."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import issue232_host as host


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--evidence-root", required=True)
    ap.add_argument("--census-rel", required=True, action="append",
                    help="census dir rel (repeatable, confirmation "
                         "censuses only — each must carry "
                         "cold_cycle_evidence with both proofs true)")
    args = ap.parse_args()
    ev = Path(args.evidence_root)
    cycles = []
    for rel in args.census_rel:
        doc = json.loads((ev / rel / "census.json").read_text())
        cce = doc.get("cold_cycle_evidence")
        if not cce:
            raise SystemExit(
                f"census {rel} lacks cold_cycle_evidence")
        if not (cce.get("prev_boot_ended_without_reboot_target")
                and cce.get("shutdown_record_present")):
            raise SystemExit(
                f"census {rel} does not prove a COLD transition "
                "(warm reboot evidence present — control 8)")
        cycles.append({
            "census_rel": rel,
            "boot_id": doc["boot_id"],
            "prev_boot_ended_without_reboot_target":
                cce["prev_boot_ended_without_reboot_target"],
            "shutdown_record_present":
                cce["shutdown_record_present"],
            "prev_tail_sha256": cce["prev_tail_sha256"],
            "last_x_sha256": cce["last_x_sha256"],
        })
    doc = {
        "schema": "inferswarm.v2g.cold-proof/1",
        "cycles": cycles,
    }
    out = ev / "cold-proof.json"
    host.durable_write(out, json.dumps(doc, indent=1,
                                       sort_keys=True).encode()
                       + b"\n")
    print(json.dumps({"cold_proof": str(out),
                      "cycles": len(cycles)}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
