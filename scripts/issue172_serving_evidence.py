#!/usr/bin/env python3
"""Issue #172 — ordinary-arm serving evidence builder (run on inferswarm00).

One EXACT_CONTEXT ranking-evidence record measured by THIS campaign's
direct-control arm at the exact running producer/context (per the
accepted #117/#133 methodology): the planner still evaluates every
legal shape and selects automatically.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

PRODUCER = "6202eeebcdf63e7bc8bb3498dd3c364ae42ee469"
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
    if len(walls) != 40:
        raise SystemExit("direct-run must carry 40 measured cases")
    walls_sorted = sorted(walls)
    median_ms = (walls_sorted[19] + walls_sorted[20]) / 2 / 1e6

    record = {
        "schema": "inferswarm.r6.serving-evidence/1",
        "records": [
            {
                "confidence": "EXACT_CONTEXT",
                "evidence_class":
                    "MEASURED_ISSUE172_ARM_C_REQUAL_DIRECT_CHAIN",
                "evidence_identity":
                    "issue172-arm-c-requal-direct-chain-validation",
                "freshness": "CURRENT",
                "id": "armc-requal172-direct-measured-chain-ttft",
                "mapping": {
                    "slot-stage-1": "gpu.node-a.0",
                    "slot-stage-2": "gpu.node-a.1",
                    "slot-stage-3": "gpu.node-b.0",
                },
                "measurement_status": "MEASURED",
                "metric": {
                    "name": "ttft_ms",
                    "statistic": "single-run",
                    "unit": "ms",
                    "value": median_ms,
                },
                "producer_identity": PRODUCER,
                "provenance": {
                    "attempt_id": direct["attempt_id"],
                    "case_count": 40,
                    "chain_plan_digest": (
                        "sha256:b24c3ca06b3ea79b62fdea8058afe9f71e0c6"
                        "9187b5cd77740cc5855f9796529"),
                    "source": "issue #172 direct-control comparator run",
                    "wall_ns_sha256": hashlib.sha256(
                        json.dumps(walls).encode()).hexdigest(),
                },
                "required_context": {
                    "model_revision": MODEL_REVISION,
                    "network_context":
                        "1GbE-LAN-MTU1500-node-a-to-node-b",
                    "runtime_context":
                        f"r6-dense-producer:{PRODUCER}",
                    "workload_geometry": "r6-dense-3stage-chain",
                },
                "role": "RANKING_OBJECTIVE",
                "shape_id": "resident-two-node-three-slot",
            }
        ],
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(record, indent=2, sort_keys=True) + "\n").encode()
    out.write_bytes(data)
    out.with_suffix(out.suffix + ".sha256").write_text(
        f"{hashlib.sha256(data).hexdigest()}  {out.name}\n")
    print(json.dumps({"serving_evidence": str(out),
                      "median_ms": median_ms}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
