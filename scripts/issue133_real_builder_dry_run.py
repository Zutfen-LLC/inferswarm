"""Issue #133 corrected freeze — CPU-only real-builder dry run.

Executes the ACTUAL frozen producer planning/build path with NO mocks of
build_execution_plan, no GPU, no model realization:

  exact producer 924cd22ea081f6d4ed471016faf01d427fc5b0d2
    (frozen-source/924cd22e bytes, sha256-pinned per file);
  exact corrected canonical Issue-133 physical environment
    (scripts/issue133_canonical_environment.py derivation);
  exact authorized chain plan
    (evidence/arm-c/chain-plan.json, digest a71a3129…);
  actual xc_strategy;
  actual Coordinator snapshot/objective helpers (coordinator.py);
  actual r3_planner;
  actual r5a_serving.freeze_execution_plan.

It then asserts:

  - schema is exactly inferswarm.r5a.static-execution-plan/1;
  - candidate/mapping/participant semantics are the expected Issue-133
    values;
  - digest exactly equals the newly frozen r5a static-plan digest
    (frozen by the campaign module; loaded from the campaign's frozen
    constant, never hand-copied in this module);
  - NEGATIVE CONTROL: the Arm-B participant-plan digest
    sha256:8646e00c… (a valid inferswarm.issue117.execution-plan/2
    identity) can NEVER satisfy the r5a static-plan authorization fence.

This module is the mandatory pre-freeze/pre-launch real-builder check
required by the maintainer disposition (issuecomment-5617122680).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import issue129_arm_c_retry_core as core  # noqa: E402
import issue133_arm_c_retry_campaign as camp  # noqa: E402
import issue133_canonical_environment as ice  # noqa: E402
import issue133_arm_c_retry_direct as drv  # noqa: E402

#: the accepted Arm-B participant execution-plan identity — a DIFFERENT
#: document family (inferswarm.issue117.execution-plan/2). Retained here
#: only as the wrong-family negative control and the preserved-substrate
#: authority check.
ARM_B_PARTICIPANT_PLAN_DIGEST = camp.ISSUE133["execution_plan_digest"]

R5A_STATIC_PLAN_SCHEMA = "inferswarm.r5a.static-execution-plan/1"


def run_real_builder_dry_run(freeze_bound: dict | None = None) -> dict:
    """Build the r5a static execution plan through the REAL frozen
    producer machinery from the final corrected inputs. No mocks. No
    realization. Returns the built plan document.

    ``freeze_bound`` (review 5166773760): the authoritative values taken
    DIRECTLY from the retained, authority-bound execution-freeze record.
    When supplied, the corrected canonical environment identity built
    here must equal the freeze record's own
    ``authorized_realization_inputs.environment.canonical_sha256``
    before the build result can be trusted."""
    environment = ice.issue133_physical_environment()
    ice.validate_environment_shape(environment)
    environment_sha = ice.environment_canonical_sha256(environment)
    if freeze_bound is not None:
        expected_environment = freeze_bound.get(
            "environment_canonical_sha256")
        if expected_environment is not None and \
                environment_sha != expected_environment:
            raise RuntimeError(
                "REAL-BUILDER DRY RUN FAILED: the corrected canonical "
                f"environment identity {environment_sha} != the "
                "authority-bound freeze record environment identity "
                f"{expected_environment}; the executing derivation has "
                "drifted from the authorized physical environment")
    plan = drv.build_execution_plan_from_environment(environment)
    return {"plan": plan, "environment": environment,
            "environment_canonical_sha256": environment_sha}


def verify_dry_run(plan: dict, freeze_bound: dict | None = None) -> dict:
    """Assert the full corrected acceptance contract on the really-built
    plan; return the verdict fields (never a bare True).

    ``freeze_bound`` (review 5166773760): authoritative values taken
    DIRECTLY from the retained, authority-bound execution-freeze
    record. When supplied, the verdict is bound to THOSE values; the
    module constants remain as ADDITIONAL internal assertions only —
    they may never substitute for the authority-bound record."""
    problems: list[str] = []
    if plan.get("schema") != R5A_STATIC_PLAN_SCHEMA:
        problems.append(
            f"schema {plan.get('schema')!r} != {R5A_STATIC_PLAN_SCHEMA!r}")
    expected_candidate = camp.ISSUE133_R5A_EXPECTED_CANDIDATE_ID
    if plan.get("candidate_id") != expected_candidate:
        problems.append(
            f"candidate {plan.get('candidate_id')!r} != {expected_candidate!r}")
    expected_mapping = camp.ISSUE133_R5A_EXPECTED_MAPPING
    if plan.get("mapping") != expected_mapping:
        problems.append(
            f"mapping {plan.get('mapping')!r} != {expected_mapping!r}")
    frozen_digest = camp.AUTHORIZED_R5A_STATIC_PLAN_DIGEST
    if plan.get("digest") != frozen_digest:
        problems.append(
            f"built r5a digest {plan.get('digest')!r} != newly frozen "
            f"{frozen_digest!r}")
    if freeze_bound is not None:
        # the AUTHORITY-BOUND freeze record values decide; module
        # constants above are additional internal assertions only
        if plan.get("schema") != freeze_bound.get("r5a_static_plan_schema"):
            problems.append(
                f"schema {plan.get('schema')!r} != authority-bound "
                f"freeze record {freeze_bound.get('r5a_static_plan_schema')!r}")
        if plan.get("digest") != freeze_bound.get("r5a_static_plan_digest"):
            problems.append(
                f"built r5a digest {plan.get('digest')!r} != authority-"
                f"bound freeze record "
                f"{freeze_bound.get('r5a_static_plan_digest')!r}")
        freeze_arm_b = freeze_bound.get("arm_b_participant_plan_digest")
        if freeze_arm_b is not None and \
                freeze_arm_b != ARM_B_PARTICIPANT_PLAN_DIGEST:
            problems.append(
                "authority-bound freeze record Arm-B participant digest "
                f"{freeze_arm_b!r} != preserved-substrate constant "
                f"{ARM_B_PARTICIPANT_PLAN_DIGEST!r}")
        freeze_chain = freeze_bound.get("chain_plan_digest")
        module_chain = camp.AUTHORIZED_REALIZATION_INPUTS["chain_plan"]["digest"]
        if freeze_chain is not None and freeze_chain != module_chain:
            problems.append(
                f"authority-bound freeze record chain-plan digest "
                f"{freeze_chain!r} != module constant {module_chain!r}")
    if problems:
        raise RuntimeError(
            "REAL-BUILDER CPU DRY RUN FAILED: " + "; ".join(problems))
    return {
        "schema": plan["schema"],
        "candidate_id": plan["candidate_id"],
        "mapping": dict(plan["mapping"]),
        "digest": plan["digest"],
        "frozen_digest": frozen_digest,
        "arm_b_participant_plan_digest": ARM_B_PARTICIPANT_PLAN_DIGEST,
    }


def verify_wrong_family_negative_control(plan: dict) -> None:
    """The Arm-B participant-plan digest (issue117.execution-plan/2) must
    NOT satisfy the r5a static-plan authorization fence — even though it
    is the valid accepted Arm-B identity."""
    if plan.get("schema") != R5A_STATIC_PLAN_SCHEMA:
        raise RuntimeError("negative control requires a real r5a plan")
    try:
        drv.verify_r5a_plan_authorization_fence(
            {"schema": "inferswarm.issue117.execution-plan/2",
             "digest": ARM_B_PARTICIPANT_PLAN_DIGEST})
    except SystemExit:
        return
    raise RuntimeError(
        "WRONG-FAMILY NEGATIVE CONTROL FAILED: the Arm-B participant-plan "
        "digest satisfied the r5a static-plan authorization fence")


def verify_arm_b_participant_authority() -> None:
    """The Arm-B participant-plan identity remains an independently
    checked preserved-substrate authority: recompute it from the
    retained accepted Arm-B execution-plan document."""
    import hashlib
    import json
    arm_b = json.loads(
        (ROOT / "docs/implementation"
         / "r6-successor-dense-full-integration-117"
         / "evidence/arm-b/execution-plan.json").read_text())
    body = {k: v for k, v in arm_b.items() if k != "plan_digest"}
    recomputed = "sha256:" + hashlib.sha256(
        (json.dumps(body, sort_keys=True, separators=(",", ":"))
         + "\n").encode()).hexdigest()
    if recomputed != ARM_B_PARTICIPANT_PLAN_DIGEST:
        raise RuntimeError(
            "Arm-B participant-plan identity drift against the retained "
            "accepted Arm-B execution-plan document")


def main() -> int:
    import json
    # review 5166773760: bind the verdict to the retained, authority-
    # bound execution-freeze record's OWN values (the campaign module
    # verifies its canonical bytes and freeze binding before returning
    # it; here we take the record as the authority source directly)
    record, _raw = camp.load_execution_freeze_record()
    camp.verify_freeze_static_shape(record)
    freeze_bound = {
        "r5a_static_plan_schema": record["r5a_static_plan_schema"],
        "r5a_static_plan_digest": record["r5a_static_plan_digest"],
        "arm_b_participant_plan_schema":
            record["arm_b_participant_plan_schema"],
        "arm_b_participant_plan_digest":
            record["arm_b_participant_plan_digest"],
        "chain_plan_digest": record["chain_plan_digest"],
        "environment_canonical_sha256":
            record["authorized_realization_inputs"]["environment"]
            ["canonical_sha256"],
    }
    result = run_real_builder_dry_run(freeze_bound=freeze_bound)
    plan = result["plan"]
    verdict = verify_dry_run(plan, freeze_bound=freeze_bound)
    verify_wrong_family_negative_control(plan)
    verify_arm_b_participant_authority()
    print(json.dumps({
        "gate": "ISSUE133_REAL_BUILDER_CPU_DRY_RUN_BOUND",
        **verdict,
        "environment_canonical_sha256":
            result["environment_canonical_sha256"],
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
