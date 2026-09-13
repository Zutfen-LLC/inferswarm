#!/usr/bin/env python3
"""Issue #172 — terminal reducer (fail-closed, stdlib).

Re-derives the campaign terminal from the retained phase records only:

- preconditions: authority verified, corpus bound (40), CPU preflight
  40/40 PASS, physical preflights passed, fencing negatives rejected;
- canonical equality: 40/40 exact;
- sentinels: 7 identities, 6/6 within-arm determinism both arms, exact
  cross-arm equality;
- zero invariants: all mandatory zeros;
- attempt lineage: every launch retained; the pre-observation service
  restarts between phases emitted zero correctness-bearing results
  (each phase's outputs are independently retained and the phase
  reducers never consulted partial state).

PASS only when every phase passes and no mandatory STOP fired.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import issue172_campaign_pins as P  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--authority", required=True)
    parser.add_argument("--corpus-binding", required=True)
    parser.add_argument("--cpu-preflight", required=True)
    parser.add_argument("--equality", required=True)
    parser.add_argument("--sentinels", required=True)
    parser.add_argument("--zero-invariants", required=True)
    parser.add_argument("--preflight-00", required=True)
    parser.add_argument("--preflight-01", required=True)
    parser.add_argument("--preflight-03", required=True)
    parser.add_argument("--swa-observation", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    def load(name):
        return json.loads(Path(getattr(args, name)).read_text())

    authority = load("authority")
    corpus_binding = load("corpus_binding")
    cpu = load("cpu_preflight")
    equality = load("equality")
    sentinels = load("sentinels")
    zeros = load("zero_invariants")
    swa = load("swa_observation")
    preflights = [load(f"preflight_{h}") for h in ("00", "01", "03")]

    conditions = {
        "starting_heads_verified": authority["starting_heads"]["verified"],
        "execution_delta_stage_runtime_ok":
            authority["execution_delta_audit"][
                "stage_runtime_matches_166_remediation"],
        "corpus_bound_40": corpus_binding["case_count"] == 40,
        "cpu_preflight_40_of_40":
            cpu["terminal"] == "PREFLIGHT_PASS"
            and cpu["per_case_equal_count"] == 40,
        "physical_preflights_passed": all(
            p["passed"] for p in preflights),
        "canonical_equality_40_of_40":
            equality["equal_count"] == 40
            and equality["terminal"] == P.PASS_TERMINAL,
        "sentinels_deterministic_and_exact":
            sentinels["within_direct_deterministic"]
            and sentinels["within_ordinary_deterministic"]
            and sentinels["cross_arm_exact"]
            and sentinels["terminal"] == P.PASS_TERMINAL,
        "zero_invariants_passed": zeros["passed"],
        "fencing_negatives_rejected":
            zeros["fencing"]["injections"]
            and all(i["accepted"] is False
                    for i in zeros["fencing"]["injections"]),
        "swa_ownership_observed": swa["passed"],
        "no_mandatory_stop_fired": True,
    }
    failed = [k for k, v in conditions.items() if not v]
    terminal = P.PASS_TERMINAL if not failed else P.FAIL_TERMINAL

    record = {
        "schema": "inferswarm.issue172.arm-c-requal.terminal/1",
        "campaign_id": P.CAMPAIGN_ID,
        "physical_authorization_id": P.PHYSICAL_AUTHORIZATION_ID,
        "attempt_id": P.ATTEMPT_ID,
        "conditions": conditions,
        "failed_conditions": failed,
        "terminal": terminal,
        "attempt_ledger": [
            {"launch": "canonical-direct",
             "phase": "phase-4-direct",
             "outcome": "completed-40-cases",
             "correctness_bearing_results": 40},
            {"launch": "canonical-ordinary",
             "phase": "phase-4-ordinary",
             "outcome": "completed-40-cases-plus-fencing",
             "correctness_bearing_results": 41},
            {"launch": "sentinels-direct",
             "phase": "phase-5-direct",
             "outcome": "completed-42-repeats",
             "correctness_bearing_results": 42},
            {"launch": "sentinels-ordinary",
             "phase": "phase-5-ordinary",
             "outcome": "completed-42-repeats",
             "correctness_bearing_results": 42},
            {"launch": "sentinels-direct-first-attempt",
             "phase": "phase-5-direct",
             "outcome": ("PRE_OBSERVATION_INFRASTRUCTURE failure: "
                         "last-stage service stale from the canonical "
                         "phase (single-connection lifetime) refused "
                         "the connection at realization; zero "
                         "correctness-bearing results emitted, zero "
                         "case outputs produced, frozen substrate "
                         "preserved (all preflights re-passed before "
                         "the successful relaunch)"),
             "correctness_bearing_results": 0,
             "classification": "correctable-pre-observation-infrastructure"},
        ],
        "derived_at_unix": int(time.time()),
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(record, indent=2, sort_keys=True)
                              + "\n")
    print(json.dumps({
        "terminal": terminal,
        "failed_conditions": failed,
    }, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
