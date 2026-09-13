#!/usr/bin/env python3
"""Issue #172 — ordinary controller loop (CPU preflight variant).

The accepted #129 ordinary arm, factored for reuse over the 40-case
campaign fixture: the REAL EpochServingController.serve_tokens loop
(frozen producer bytes) with the recording runtime as realizer, serving
the fixture's rendered ids (the CPU preflight serves the same ids both
arms derive; the physical ordinary arm derives them through the real
HTTP ingress, proven equal by the accepted ingress proof).
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))
import issue172_campaign_pins as P  # noqa: E402

ROOT = P.ROOT
sys.path.insert(0, str(ROOT / "scripts"))
import issue129_arm_c_retry_core as core  # noqa: E402


class _RecordingRealizer172:
    """Same contract as the accepted #129 _RecordingRealizer."""

    def __init__(self, runtime, serving) -> None:
        self.runtime = runtime
        self.serving = serving

    def __call__(self, execution_plan, realization_authorization=None):
        observation = {
            "plan_digest": execution_plan["digest"],
            "participants": execution_plan["participants"],
            "compute_units": execution_plan["compute_units"],
            "representations": execution_plan["representations"],
            "backend_choices": execution_plan["backend_choices"],
            "state_placement": execution_plan["state_placement"],
            "state_authority": execution_plan["state_authority"],
            "semantic_boundaries": execution_plan["semantic_boundaries"],
        }
        self.serving.reconcile_realization(execution_plan, observation)
        self.runtime.plan_digest_value = execution_plan["digest"]
        return self.serving.RealizedStaticPlan(
            runtime=self.runtime, observation=observation)


def run_ordinary_loop(*, planner, serving, epochs, xc_strategy, runtime,
                      fixture: dict[str, Any], repo_root: Path) -> dict:
    environment = core._frozen_environment(repo_root)
    chain_plan = core._load_chain_plan(repo_root)
    transcript = runtime.sink

    def compiler(evaluation):
        return xc_strategy.compile_candidate(
            dict(evaluation), chain_plan=dict(chain_plan))

    controller = epochs.EpochServingController(
        problem=xc_strategy.planning_problem(core.FROZEN_PRODUCER_SHA),
        initial_snapshot=core.build_resource_snapshot(planner, environment),
        policy=xc_strategy.operator_policy(core.FROZEN_PRODUCER_SHA),
        objective=core._objective(planner),
        evidence_catalog=core._evidence_catalog(planner, repo_root),
        compiler=compiler,
        realizer=_RecordingRealizer172(runtime, serving),
        transition_strategy=xc_strategy.GemmaTokenBoundaryStrategy(),
        transition_policy=core._transition_policy(planner),
    )
    per_case: dict[str, Any] = {}
    for case in sorted(fixture["cases"], key=lambda c: c["session_index"]):
        case_id = case["case_id"]
        prompt_ids = list(case["rendered_prompt_token_ids"])
        mark = len(transcript)
        completed = controller.serve_tokens(
            session_id=case["session_index"],
            prompt_token_ids=prompt_ids,
            max_new_tokens=core.COMMIT_TOKENS,
            sampling_inputs=dict(core.SAMPLING_INPUTS))
        per_case[case_id] = {
            "case_id": case_id,
            "logical_session_id": case["session_index"],
            "prompt_ids_source": "frozen fixture (ingress equality proven separately)",
            "completed_token_ids": list(completed["generated_token_ids"]),
            "committed_count": len(completed["generated_token_ids"]),
            "committed_epoch_ids": list(completed["committed_epoch_ids"]),
            "committed_plan_digests": list(
                completed["committed_plan_digests"]),
            "calls": core._public_calls(transcript[mark:], case_id),
        }
    plan = controller._epochs[0].execution_plan
    per_case["__selection_authorization__"] = {
        "mode": "AUTOMATIC_PLANNER_SELECTION",
        "plan_digest": plan.get("digest"),
        "candidate_id": plan.get("candidate_id"),
    }
    controller.close()
    return per_case
