#!/usr/bin/env python3
"""Issue #172 — real-builder CPU dry run for the campaign r5a static plan.

Builds the r5a STATIC execution plan through the REAL frozen producer
control plane (vendored sha256-pinned bytes — identical between the
accepted producer 924cd22e and this campaign's 6202eee, mechanically
verified by the authority audit) over the #172 canonical environment
(implementation_commit 6202eee) and the #172 re-frozen chain plan.

No GPU, no model execution. Outputs the plan digest to pin as this
campaign's r5a authorization fence (must equal the digest the physical
direct driver builds locally at launch).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))
import issue172_campaign_pins as P  # noqa: E402

ROOT = P.ROOT
sys.path.insert(0, str(ROOT / "scripts"))
import issue129_arm_c_retry_core as core  # noqa: E402
import issue133_arm_c_retry_direct as d133  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--environment", required=True)
    parser.add_argument("--chain-plan", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    environment = json.loads(Path(args.environment).read_text())
    chain_plan = json.loads(Path(args.chain_plan).read_text())
    if environment.get("implementation_commit") != P.FREETOKEN_RESEARCH_172:
        raise SystemExit("environment not bound to the #172 producer")

    # verify the re-frozen chain plan derives from the accepted lineage
    if chain_plan.get("digest") != d133_chain_digest(chain_plan):
        raise SystemExit("chain plan digest not self-consistent")

    repo = ROOT
    frozen = d133._load_vendored_producer_control_plane(repo)
    plan = d133._compile_r5a_static_plan(
        strategy=frozen["xc_strategy"], coordinator=frozen["coordinator"],
        planner=frozen["r3_planner"], serving=frozen["r5a_serving"],
        env=environment, chain_plan=chain_plan)
    if plan.get("schema") != d133.AUTHORIZED_R5A_STATIC_PLAN_SCHEMA:
        raise SystemExit(f"wrong plan family {plan.get('schema')!r}")

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(
        plan, indent=2, sort_keys=True) + "\n")
    canonical_env = "sha256:" + hashlib.sha256(
        (json.dumps(environment, indent=2, sort_keys=True) + "\n")
        .encode()).hexdigest()
    print(json.dumps({
        "r5a_static_plan_digest": plan["digest"],
        "schema": plan["schema"],
        "candidate_id": plan.get("candidate_id"),
        "environment_canonical_sha256": canonical_env,
        "chain_plan_digest": chain_plan.get("digest"),
        "note": "built by the real frozen producer control plane on CPU; "
                "pin this digest as the #172 r5a authorization fence",
    }, indent=1))
    return 0


def d133_chain_digest(plan: dict) -> str:
    body = {k: v for k, v in plan.items() if k != "digest"}
    return "sha256:" + hashlib.sha256(
        (json.dumps(body, sort_keys=True, separators=(",", ":")) + "\n")
        .encode()).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
