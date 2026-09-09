#!/usr/bin/env python3
"""Build the Arm-C ordinary-arm serving evidence record (run on inferswarm00).

One EXACT_CONTEXT ranking-evidence record measured by the direct-control
arm at the exact running producer/context (per METHODOLOGY-ARM-C §3): the
planner still evaluates every legal shape and selects automatically.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

PRODUCER = "924cd22ea081f6d4ed471016faf01d427fc5b0d2"
MODEL_REVISION = "707f0a3b8a3c7ad586ed01e27eafbad8a27dd0f7"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--direct-run", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    direct = json.loads(Path(args.direct_run).read_text())
    if direct["producer"] != PRODUCER:
        raise SystemExit("direct-run producer drift")
    walls = [r["wall_ns"] for r in direct["results"]]
    if len(walls) != 24:
        raise SystemExit("direct-run must carry 24 measured cases")
    walls_sorted = sorted(walls)
    median_ms = (walls_sorted[11] + walls_sorted[12]) / 2 / 1e6

    record = {
        "schema": "inferswarm.issue117.arm-c.serving-evidence/1",
        "record": {
            "id": "armc-direct-measured-chain-ttft",
            "evidence_class": "MEASURED_ISSUE117_ARM_C_DIRECT_CHAIN",
            "evidence_identity": "issue117-arm-c-direct-chain-validation",
            "measurement_status": "MEASURED",
            "confidence": "EXACT_CONTEXT",
            "freshness": "CURRENT",
            "role": "RANKING_OBJECTIVE",
            "shape_id": "resident-two-node-three-slot",
            "mapping": {
                "slot-stage-1": "gpu.node-a.0",
                "slot-stage-2": "gpu.node-a.1",
                "slot-stage-3": "gpu.node-b.0",
            },
            "metric": {
                "name": "ttft_ms",
                "unit": "ms",
                "statistic": "single-run",
                "value": median_ms,
            },
            "producer_identity": PRODUCER,
            "required_context": {
                "model_revision": MODEL_REVISION,
                "network_context":
                    "1GbE-LAN-MTU1500-node-a-to-node-b",
                "runtime_context": f"r6-dense-producer:{PRODUCER}",
                "workload_geometry": "r6-dense-3stage-chain",
            },
            "provenance": {
                "source": "issue117-arm-c direct-control comparator run",
                "attempt_id": direct["attempt_id"],
                "case_count": 24,
                "wall_ns_sha256": hashlib.sha256(json.dumps(
                    walls, separators=(",", ":")).encode()).hexdigest(),
                "chain_plan_digest": direct.get("chain_plan_digest"),
            },
        },
        "built_at_ns": time.time_ns(),
    }
    out = Path(args.out)
    out.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"out": str(out), "ttft_ms": median_ms}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
