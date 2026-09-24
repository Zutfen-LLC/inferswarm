#!/usr/bin/env python3
"""Issue #241 — R8-I3 dormant campaign orchestrator.

Single entrypoint for the CPU-only slice. Every physical phase (census
capture on inferswarm01, matched-placement ladder, comparator/2
historical-fixture validation, practicality measurement) is DORMANT:
its producer refuses to run without the exact-head maintainer dispatch
(issue241_dispatch), and this orchestrator only emits status/plan
records. It never launches llama-server, never touches a GPU, and never
reads holdout plaintext (no decrypt path exists in this module graph).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import issue241_constants as C
import issue241_phase0
import issue241_supersession

SCHEMA = "inferswarm.issue241.campaign-status/1"

PHASES = (
    ("phase0", "preservation audit", "CPU-only", "RUNNABLE now"),
    ("phase1", "fresh same-host AMD/NVIDIA Vulkan precheck (census + "
               "historical-fixture bounded runs)", "physical",
     "DORMANT — maintainer dispatch required"),
    ("phase2", "prospective matched-placement ngl ladder freeze", "physical",
     "DORMANT — maintainer dispatch required"),
    ("phase3", "comparator/2 historical-only validation", "physical",
     "DORMANT — maintainer dispatch required"),
    ("phase4", "practicality projection + one disposition", "reducer",
     "DORMANT — consumes measured receipts only"),
    ("phase5", "additive v2 methodology supersession (NO authority "
               "before the measured phase-4 disposition and maintainer GO)",
     "builder",
     "DORMANT — requires a passing phase-4 terminal AND maintainer GO"),
)

PHYSICAL_PHASES = ("phase1", "phase2", "phase3")

# The committed bounded physical execution path (scripts/issue241_physical.py):
# each entrypoint gates on require_live_dispatch BEFORE any fixture load,
# device probe/init, server build, model-byte read, telemetry, or inference.
PHYSICAL_ENTRYPOINTS = ("run_phase1", "run_phase2", "run_phase3")


def campaign_status(repo: Path | None = None) -> dict[str, Any]:
    repo = repo or C.ROOT
    audit = issue241_phase0.audit_phase0(repo)
    return {
        "schema": SCHEMA,
        "campaign": C.CAMPAIGN_ID,
        "issue": C.ISSUE,
        "head": audit["head"],
        "subject_generation": C.SUBJECT_GENERATION,
        "historical_terminal": C.HISTORICAL_TERMINAL,
        "historical_dispatch_head": C.HISTORICAL_DISPATCH_HEAD,
        "phase0": audit,
        "phases": [
            {"phase": p, "description": d, "kind": k, "state": s}
            for p, d, k, s in PHASES
        ],
        "physical_execution_performed": False,
        "dispatch_phrase": "R8I3 PHYSICAL DISPATCH #241",
        "holdout_access_performed": False,
        "predictive_execution_performed": False,
    }


def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args(argv)
    status = campaign_status()
    text = json.dumps(status, indent=2, sort_keys=True)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
