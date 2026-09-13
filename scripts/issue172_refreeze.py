#!/usr/bin/env python3
"""Issue #172 — chain-plan re-freeze + canonical environment rebuild.

Following the accepted #129 precedent (the accepted Arm-C chain plan was
itself a re-freeze of the accepted Arm-B participant plan under the then
producer), this campaign re-freezes the SAME chain-plan CONTENT under
the accepted #166-remediated producer 6202eee:

- every execution-bearing field (blocks, boundary_geometry,
  checkpoint_index_sha256, coverage_proof, declared_shared_state, model,
  model_path, number_of_layers, required_text_model_bytes,
  runtime_capacity_tokens, schema, status, total_checkpoint_bytes) is
  copied byte-identically from the accepted chain plan a71a3129;
- provenance.r6.producer_sha is bound to THIS campaign's producer
  6202eee, carrying the full chain of accepted identities
  (accepted_plan_digest ee845188…, accepted_arm_c_chain_plan a71a3129…);
- the result is digested (self-consistent freeze format) and deployed
  read-only to the campaign namespace on 01 and 03.

Also builds the canonical campaign environment (the accepted #133
environment with implementation_commit re-bound to 6202eee and the
freshly observed BDFs — verified against live hardware at deploy time
by the preflight), whose canonical sha256 feeds the real-builder dry
run that re-derives the r5a static-plan digest for THIS campaign.

CPU-only, stdlib. Fail-closed.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
import issue172_campaign_pins as P  # noqa: E402


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def chain_plan_digest(plan: dict) -> str:
    body = {k: v for k, v in plan.items() if k != "digest"}
    return "sha256:" + sha256_bytes(
        (json.dumps(body, sort_keys=True, separators=(",", ":")) + "\n"
         ).encode())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--accepted-plan", required=True,
                        help="path to the accepted chain plan a71a3129")
    parser.add_argument("--accepted-environment", required=True,
                        help="path to the accepted environment freeze")
    parser.add_argument("--out-plan", required=True)
    parser.add_argument("--out-environment", required=True)
    args = parser.parse_args()

    accepted = json.loads(Path(args.accepted_plan).read_text())
    if accepted.get("digest") != P.AUTHORIZED_CHAIN_PLAN_DIGEST:
        raise SystemExit("accepted chain plan digest drift")
    if chain_plan_digest(accepted) != P.AUTHORIZED_CHAIN_PLAN_DIGEST:
        raise SystemExit("accepted chain plan not self-consistent")

    # --- re-freeze content-identical, producer 6202eee -------------------
    fresh = copy.deepcopy(accepted)
    EXECUTION_FIELDS = [
        "blocks", "boundary_geometry", "checkpoint_index_sha256",
        "coverage_proof", "declared_shared_state", "model", "model_path",
        "number_of_layers", "required_text_model_bytes",
        "runtime_capacity_tokens", "schema", "status",
        "total_checkpoint_bytes",
    ]
    for field in EXECUTION_FIELDS:
        if fresh.get(field) != accepted.get(field):
            raise SystemExit(f"execution field {field} mutated")
    fresh["provenance"] = {
        "r6": {
            "note": (
                "issue #172 Arm-C requalification: the accepted #133 chain "
                "plan content re-frozen byte-identically (all "
                "execution-bearing fields equal) under the accepted #166 "
                "remediated producer for post-remediation ordinary "
                "serving; provenance chain ee845188 -> a71a3129 -> this "
                "freeze"),
            "producer_sha": P.FREETOKEN_RESEARCH_172,
            "supersedes_for_issue172_arm_c_requal_only": (
                "/srv/inferswarm/state/arm-c/chain-plan.json"),
        },
        "issue172_arm_c_requal": {
            "accepted_arm_c_chain_plan": P.AUTHORIZED_CHAIN_PLAN_DIGEST,
            "accepted_plan_digest": P.AUTHORIZED_PARTICIPANT_IDENTITY,
            "producer_sha": P.FREETOKEN_RESEARCH_172,
        },
    }
    fresh.pop("digest", None)
    fresh["digest"] = chain_plan_digest(fresh)
    out_plan = Path(args.out_plan)
    out_plan.parent.mkdir(parents=True, exist_ok=True)
    out_plan.write_text(json.dumps(fresh, indent=2, sort_keys=True) + "\n")

    # --- canonical environment: implementation_commit -> 6202eee --------
    environment = json.loads(Path(args.accepted_environment).read_text())
    accepted_canonical = sha256_bytes(
        (json.dumps(environment, indent=2, sort_keys=True) + "\n").encode())
    if accepted_canonical != P.AUTHORIZED_ENVIRONMENT_CANONICAL_SHA256:
        raise SystemExit("accepted environment bytes drift")
    environment["implementation_commit"] = P.FREETOKEN_RESEARCH_172
    environment["runtime_context"] = (
        f"r6-dense-producer:{P.FREETOKEN_RESEARCH_172}")
    out_env = Path(args.out_environment)
    out_env.parent.mkdir(parents=True, exist_ok=True)
    out_env.write_text(
        json.dumps(environment, indent=2, sort_keys=True) + "\n")

    env_canonical = sha256_bytes(
        (json.dumps(environment, indent=2, sort_keys=True) + "\n").encode())
    print(json.dumps({
        "chain_plan_172": str(out_plan),
        "chain_plan_172_digest": fresh["digest"],
        "content_equal_to_accepted": True,
        "environment_172": str(out_env),
        "environment_172_canonical_sha256": env_canonical,
        "implementation_commit": P.FREETOKEN_RESEARCH_172,
    }, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
