#!/usr/bin/env python3
"""V2-A ONE reusable campaign engine (issue #163).

Consumes a prospectively frozen ``inferswarm.v2a.campaign-authority/1``
document and drives the accepted campaign semantics end to end:

  1. mechanical preflight; 2. fresh physical qualification;
  3. adapter-sealed observation; 4. capability creation;
  5. generic resource snapshot; 6. production generic planner;
  7. candidate + plan freeze; 8. canonical physical execution;
  9. selector-aware accounting (accepted V1-C reducer);
  10. accepted byte-exact comparator against the authority's
  prospectively authorized reference; 11. adapter-sealed canonical
  proof; 12. generic canonical observation; 13. execution receipt;
  14. deterministic evidence reduction.

Accepted components are IMPORTED, never forked: the V1-A runner's
preflight/qualify/snapshot/planning/_execute stages, the V1-A
participant and adapter, the V0-C correctness comparator, and the V1-C
selector-aware accounting reducer. Every subject fact (selector, BDF,
node/CU/MR IDs, hashes, evidence IDs, reference bytes) is consumed from
the frozen authority as data. The engine bytes contain no selector,
vendor, device, BDF, model, or accepted evidence literal.

The engine never self-authorizes: the correctness reference is loaded
and hash-pinned by ``v2a_authority`` at load time, before any stage
runs, and cannot be replaced afterwards (the loaded authority document
is treated as read-only data by every stage).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import v1a_runner as accepted_runner  # noqa: E402
import v1a_execution_participant as participant  # noqa: E402
import v1a_vulkan_adapter as adapter  # noqa: E402
import v0c_correctness as v0c_correctness  # noqa: E402
import v1c_accounting as accepted_accounting  # noqa: E402
import v2a_authority as authority_contract  # noqa: E402
import v2a_authority_v3 as authority_contract_v3  # noqa: E402
import v2a_discovery_v3 as discovery_v3  # noqa: E402


class HarnessError(RuntimeError):
    """A V2-A campaign invariant was not satisfied."""


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def digest_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------------------
# Authority -> accepted V1-A authority-shape adaptation (pure data mapping).
# The accepted runner consumes the V1-A authority mapping; the V2-A contract
# is a strict superset. No fact is invented: every value is copied from the
# frozen authority, and the reference bytes come from the correctness block.
# ---------------------------------------------------------------------------

def _v1a_view(v2a: Mapping[str, Any]) -> dict[str, Any]:
    frozen = dict(v2a["frozen"])
    frozen["reference_output"] = v2a["correctness"]["reference_path"]
    return {"frozen": frozen,
            "capability_completion": v2a.get("capability_completion", {
                "representations": [frozen["required_representation"]],
                "required_features": list(frozen["required_features"]),
                "integrity_status": frozen["required_integrity_status"]}),
            "physical_identity": v2a.get("physical_identity", {})}


# ---------------------------------------------------------------------------
# Stage 9/10 supersessions of the accepted canonical stage: identical order
# and components to the accepted V1-C canonical stage, with the selector and
# the reference bytes consumed from the frozen V2-A authority only.
# ---------------------------------------------------------------------------

def execute_canonical(v2a: Mapping[str, Any], plan: Mapping[str, Any], measured: Mapping[str, Any],
                      out: Path) -> dict[str, Any]:
    frozen = v2a["frozen"]
    v1a_view = _v1a_view(v2a)
    participant.validate_frozen_plan(plan)
    if "plan_digest" in frozen and plan["plan_digest"] != frozen["plan_digest"]:
        raise HarnessError("frozen plan digest differs from authority")
    candidate = plan["candidate"]
    for field in ("node_id", "compute_unit_id", "memory_resource_id", "execution_unit_id",
                  "execution_contract_id", "implementation_id", "physical_device_bdf"):
        if candidate.get(field) != frozen[field]:
            raise HarnessError(f"frozen candidate {field} mismatch")
    if "candidate_id" in frozen and candidate.get("candidate_id") != frozen["candidate_id"]:
        raise HarnessError("frozen candidate_id mismatch")
    run = accepted_runner._execute(frozen, out)
    if run["exit_code"] != 0:
        raise HarnessError(f"canonical exit was not clean: {run['exit_code']}")
    observation = adapter.parse_backend_observation(
        stderr=run["stderr"], selector=frozen["selector"], expected_bdf=frozen["physical_device_bdf"],
        node_id=candidate["node_id"], compute_unit_id=candidate["compute_unit_id"],
        memory_resource_id=candidate["memory_resource_id"], execution_unit_id=candidate["execution_unit_id"],
        execution_contract_id=candidate["execution_contract_id"],
        implementation_id=candidate["implementation_id"], evidence_id=candidate["evidence_id"],
        runtime_identity=candidate["runtime_identity"])
    # Selector-aware accounting: the selector comes from the frozen
    # authority ONLY (never from the transcript, never from the caller).
    accounting = accepted_accounting.parse_accounting(run["stderr"], selector=frozen["selector"])
    for key in ("unexplained_persistent_host_mirror_bytes", "source_fetches_after_ready",
                "unplanned_state_movements"):
        if accounting[key] != 0:
            raise HarnessError(f"accounting disposition not clean: {key}")
    # Accepted byte-exact comparator against the authority-declared
    # reference (hash-pinned at authority load time).
    reference = authority_contract.reference_bytes(v2a, reference_root=ROOT)
    correctness = v0c_correctness.reduce(run["stdout"], frozen["prompt"].encode(), reference)
    if not correctness["byte_exact_visible_output"]:
        raise HarnessError("byte-exact correctness comparison failed")
    proof = adapter.seal_canonical_execution_proof(
        observation=observation, plan_digest=plan["plan_digest"], candidate_id=candidate["candidate_id"],
        execution_contract_id=candidate["execution_contract_id"],
        execution_evidence_id=frozen["canonical_execution_evidence_id"], stdout=run["stdout"],
        stderr=run["stderr"], exit_code=run["exit_code"])
    observation_record = participant.canonical_observation(plan=plan, canonical_proof=proof)
    receipt = participant.execution_receipt(plan=plan, output=correctness["visible_response_bytes"],
                                            canonical_proof=proof)
    return {"run": run, "accounting": accounting, "correctness": correctness, "proof": proof,
            "canonical_observation": observation_record, "receipt": receipt}


# ---------------------------------------------------------------------------
# Retained-evidence replay (Phase 6 of the issue): reduce ACCEPTED raw bytes
# from both proven subjects under the SAME harness reduction path, without
# subject-specific code. Retrospective only.
# ---------------------------------------------------------------------------

def replay_retained(retained_stderr: str, *, selector: str, expected_bdf: str,
                    expected_prompt: str, reference: bytes, stdout: bytes) -> dict[str, Any]:
    """Replay one accepted retained physical transcript through the harness.

    All inputs are accepted retained evidence bytes/facts. The adapter
    observation is rebuilt from the retained transcript with neutral
    replay identity, accounting is reduced under the authority selector,
    and the byte-exact comparator runs against the accepted reference.
    """
    observation = adapter.parse_backend_observation(
        stderr=retained_stderr, selector=selector, expected_bdf=expected_bdf,
        node_id="replay-node", compute_unit_id="replay-cu",
        memory_resource_id="replay-mr", execution_unit_id="replay-unit",
        execution_contract_id="replay-contract", implementation_id="replay-impl",
        evidence_id="replay-evidence", runtime_identity={"replay": True})
    accounting = accepted_accounting.parse_accounting(retained_stderr, selector=selector)
    for key in ("unexplained_persistent_host_mirror_bytes", "source_fetches_after_ready",
                "unplanned_state_movements"):
        if accounting[key] != 0:
            raise HarnessError(f"replayed accounting disposition not clean: {key}")
    correctness = v0c_correctness.reduce(stdout, expected_prompt.encode(), reference)
    if not correctness["byte_exact_visible_output"]:
        raise HarnessError("replayed byte-exact correctness comparison failed")
    return {"full_offload": list(observation.offloaded_layers),
            "accounting_three_tuple": [accounting["unexplained_persistent_host_mirror_bytes"],
                                       accounting["source_fetches_after_ready"],
                                       accounting["unplanned_state_movements"]],
            "byte_exact_visible_output": correctness["byte_exact_visible_output"],
            "role": "retrospective retained-evidence replay; NOT a fresh physical PASS",
            "result": "PASS"}


# ---------------------------------------------------------------------------
# Portability audit (Phase 10): machine-readable comparison of the two
# campaigns produced by the SAME source freeze.
# ---------------------------------------------------------------------------

HARNESS_SOURCES = (
    "scripts/v2a_harness.py", "scripts/v2a_discovery.py", "scripts/v2a_discovery_v2.py",
    "scripts/v2a_discovery_v3.py", "scripts/v2a_authority.py", "scripts/v2a_authority_v2.py",
    "scripts/v2a_authority_v3.py", "scripts/v2a_manifest.py",
)


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_portability_audit(campaigns: list[Mapping[str, Any]]) -> dict[str, Any]:
    """Classify every difference between campaigns run by this harness.

    Each campaign entry carries: authority, qualification, plan, canonical
    record, and the source-freeze commit it ran under. PASS requires the
    exact same harness/source hashes for both campaigns, differences
    limited to authority/runtime/evidence data, no subject-specific code,
    and no falsified foundational invariant.
    """
    if len(campaigns) != 2:
        raise HarnessError("portability audit compares exactly two campaigns")
    first, second = campaigns
    harness_hashes = {path: _sha256_file(ROOT / path) for path in HARNESS_SOURCES}
    same_harness = all(c.get("harness_source_hashes") == harness_hashes for c in campaigns)
    subject_data_aspects = []
    for label, campaign in (("first", first), ("second", second)):
        frozen = campaign["authority"]["frozen"]
        subject_data_aspects.append({
            "campaign": label,
            "subject": {key: frozen[key] for key in (
                "node_id", "compute_unit_id", "memory_resource_id", "physical_device_bdf",
                "selector", "implementation_id")},
            "evidence_ids": {key: frozen[key] for key in (
                "qualification_evidence_id", "canonical_execution_evidence_id")},
        })
    runtime_differences = [
        {key: {"first": first["authority"]["frozen"].get(key),
               "second": second["authority"]["frozen"].get(key)}}
        for key in ("executable_sha256", "model_sha256", "runtime_source_commit",
                    "runtime_identity", "memory_bytes")
        if first["authority"]["frozen"].get(key) != second["authority"]["frozen"].get(key)
    ]
    # R2 discovery->authority layer: both campaigns must run the exact
    # same discovery implementation, reference manifest-retained reviewed
    # discovery, and carry prospectively BOUND selector/BDF bindings.
    discovery_impl_same = all(
        c.get("discovery_implementation_sha256") == campaigns[0].get(
            "discovery_implementation_sha256") for c in campaigns)
    bindings_all_bound = all(
        c.get("authority", {}).get("verified_binding", {}).get("binding_status") == "BOUND"
        for c in campaigns)
    discovery_retained = all(
        c.get("discovery_binding", {}).get("bindings_sha256")
        and c.get("discovery_binding", {}).get("inventory_sha256") for c in campaigns)
    same_artifacts = (first.get("discovery_binding", {}).get("inventory_sha256")
                      == second.get("discovery_binding", {}).get("inventory_sha256")
                      and first.get("discovery_binding", {}).get("bindings_sha256")
                      == second.get("discovery_binding", {}).get("bindings_sha256"))
    both_passed = all(c.get("canonical", {}).get("result") == "PASS" and
                      c.get("qualification", {}).get("result") == "PASS" for c in campaigns)
    accounting_clean = all(
        c.get("canonical", {}).get("accounting", {}).get(
            "unexplained_persistent_host_mirror_bytes") == 0 and
        c.get("canonical", {}).get("accounting", {}).get("source_fetches_after_ready") == 0 and
        c.get("canonical", {}).get("accounting", {}).get("unplanned_state_movements") == 0
        for c in campaigns)
    byte_exact = all(c.get("canonical", {}).get("correctness", {}).get(
        "byte_exact_visible_output") for c in campaigns)
    classifications = [
        {"aspect": "reusable harness source bytes identical across campaigns",
         "evidence": {"same_harness_hashes": same_harness},
         "classification": "REUSABLE_HARNESS_SEMANTICS_SHARED" if same_harness
         else "SUBJECT_SPECIFIC_CODE_REQUIRED"},
        {"aspect": "subject/resource identity, selector, and evidence IDs",
         "evidence": {"subjects": subject_data_aspects},
         "classification": "AUTHORITY_DATA_ONLY"},
        {"aspect": "runtime/state facts (executable, model, driver/runtime identity)",
         "evidence": {"differences": runtime_differences},
         "classification": "BACKEND_RUNTIME_DATA_ONLY"},
        {"aspect": "qualification and canonical results (offload, exit, accounting, correctness)",
         "evidence": {"both_campaigns_passed": both_passed, "accounting_clean": accounting_clean,
                      "byte_exact": byte_exact},
         "classification": "REUSABLE_HARNESS_SEMANTICS_SHARED"
         if (both_passed and accounting_clean and byte_exact)
         else "FOUNDATIONAL_INVARIANT_FALSIFIED"},
        {"aspect": "reviewed discovery implementation and artifacts (discovery->authority layer)",
         "evidence": {"same_discovery_implementation": discovery_impl_same,
                      "bindings_prospectively_bound": bindings_all_bound,
                      "discovery_artifacts_retained": discovery_retained,
                      "same_reviewed_artifacts": same_artifacts},
         "classification": "REUSABLE_HARNESS_SEMANTICS_SHARED"
         if (discovery_impl_same and bindings_all_bound and discovery_retained)
         else "SUBJECT_SPECIFIC_CODE_REQUIRED"},
    ]
    passed = (same_harness and both_passed and accounting_clean and byte_exact
              and discovery_impl_same and bindings_all_bound and discovery_retained
              and not any(row["classification"] == "SUBJECT_SPECIFIC_CODE_REQUIRED"
                          or row["classification"] == "FOUNDATIONAL_INVARIANT_FALSIFIED"
                          for row in classifications))
    return {
        "schema": "inferswarm.v2a.portability-audit/1",
        "harness_source_hashes": harness_hashes,
        "campaign_subjects": subject_data_aspects,
        "runtime_data_differences": runtime_differences,
        "classifications": classifications,
        "subject_specific_code_required": any(
            row["classification"] == "SUBJECT_SPECIFIC_CODE_REQUIRED" for row in classifications),
        "foundational_invariant_falsified": any(
            row["classification"] == "FOUNDATIONAL_INVARIANT_FALSIFIED" for row in classifications),
        "result": "PASS" if passed else "FAIL",
    }


# ---------------------------------------------------------------------------
# CLI: the single reusable entry point. Every mode takes --authority; no
# subject-specific flag exists.
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--authority", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--mode", choices=("preflight", "qualify", "plan", "canonical"), required=True)
    parser.add_argument("--capability")
    parser.add_argument("--plan")
    args = parser.parse_args(argv)
    # Correctness-bearing campaign stages require the v3 reviewed-discovery
    # contract: the authority's selector/BDF pair must be mechanically BOUND
    # to a digest-verified reviewed discovery artifact whose PHYSICAL
    # INVENTORY measurement (not merely its review event) is fresh, and
    # whose retained raw identity-probe bytes re-verify against the
    # structured proof, before any stage runs. R2 authorities
    # (campaign-authority/2) no longer authorize correctness-bearing runs.
    v2a = authority_contract_v3.load_authority_file(Path(args.authority), reference_root=ROOT,
                                                    discovery_root=ROOT, raw_root=ROOT)
    v1a_view = _v1a_view(v2a)
    out = Path(args.out)
    frozen = v2a["frozen"]

    if args.mode == "preflight":
        measured = accepted_runner.preflight(v1a_view)
        print(canonical({"result": "PASS", "measured": measured}).decode())
        return 0

    if args.mode == "qualify":
        measured = accepted_runner.preflight(v1a_view)
        result = accepted_runner.qualify(v1a_view, measured, out)
        record = result["record"]
        record["schema"] = "inferswarm.v2a.qualification/1"
        record["raw"] = {"stdout": "stdout.txt", "stderr": "stderr.txt", "exit_code": "exit-code.txt"}
        record.pop("attempt", None)
        record["attempt"] = {k: v for k, v in result["run"].items() if k in accepted_runner.REDUCED_RUN_KEYS}
        record["record_digest"] = digest_bytes(canonical(record))
        (out / "qualification.json").write_bytes(canonical(record) + b"\n")
        print(record["record_digest"])
        return 0

    if args.mode == "plan":
        loaded = json.loads(Path(args.capability).read_text(encoding="utf-8"))
        capability = loaded.get("capability_record", loaded)
        snapshot = accepted_runner.build_snapshot(v1a_view, capability)
        decision, plan = accepted_runner.plan_and_freeze(v1a_view, snapshot)
        out.mkdir(parents=True, exist_ok=False)
        (out / "resource-snapshot.json").write_bytes(canonical(snapshot) + b"\n")
        (out / "candidate-set.json").write_bytes(canonical(decision) + b"\n")
        (out / "frozen-plan.json").write_bytes(canonical(plan) + b"\n")
        print(plan["plan_digest"])
        return 0

    # canonical
    plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
    measured = accepted_runner.preflight(v1a_view)
    result = execute_canonical(v2a, plan, measured, out)
    evidence_id = frozen["canonical_execution_evidence_id"]
    record = {
        "schema": "inferswarm.v2a.canonical-execution/1",
        "canonical_execution_evidence_id": evidence_id,
        "preflight": measured,
        "attempt": {k: v for k, v in result["run"].items() if k in accepted_runner.REDUCED_RUN_KEYS},
        "plan_digest": plan["plan_digest"], "candidate_id": plan["candidate"]["candidate_id"],
        "accounting": result["accounting"],
        "correctness": {k: (v.decode("utf-8") if isinstance(v, bytes) else v)
                        for k, v in result["correctness"].items()},
        "canonical_proof_digest": result["proof"].proof_digest,
        "canonical_observation": result["canonical_observation"],
        "execution_receipt": result["receipt"], "result": "PASS",
        "raw": {"stdout": "stdout.txt", "stderr": "stderr.txt", "exit_code": "exit-code.txt"},
    }
    record["record_digest"] = digest_bytes(canonical(record))
    (out / "canonical-execution.json").write_bytes(canonical(record) + b"\n")
    namespace = v2a["evidence"]["evidence_namespace"]
    evidence = ROOT / "docs/investigations" / namespace / "evidence" / evidence_id
    evidence.mkdir(parents=True, exist_ok=True)
    (evidence / "accounting.json").write_bytes(canonical(result["accounting"]) + b"\n")
    (evidence / "correctness-result.json").write_bytes(canonical(
        {k: (v.decode("utf-8") if isinstance(v, bytes) else v)
         for k, v in result["correctness"].items()}) + b"\n")
    (evidence / "canonical-observation.json").write_bytes(canonical(result["canonical_observation"]) + b"\n")
    (evidence / "execution-receipt.json").write_bytes(canonical(result["receipt"]) + b"\n")
    print(record["record_digest"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
