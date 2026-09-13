#!/usr/bin/env python3
"""Issue #161 V1-C successor campaign orchestration (local proving node only).

This is the narrowest V1-C orchestration path: it REUSES the accepted
V1-A campaign components unchanged — preflight, qualification through
the adapter seam, generic planning through the participant, frozen
plan semantics, the accepted byte-exact correctness comparator, the
adapter-sealed canonical proof, the generic canonical observation, and
the execution receipt — and supersedes ONLY the canonical accounting
stage with the selector-aware successor reducer
(``scripts/v1c_accounting.py``).

``scripts/v1a_runner.py`` is imported and used as a module: its
preflight, qualify, build_snapshot, plan_and_freeze, and _execute are
the accepted execution stages. The single superseded stage is the
accepted runner's call to the first-subject-pinned V0-C accounting
reducer inside ``execute_canonical``; the equivalent V1-C canonical
stage is implemented here, calling the SAME accepted components in the
SAME order with the successor accounting reducer substituted. No
planner or proof semantics are forked or reimplemented.

No SSH. Every subject fact comes from the frozen V1-C authority.
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
import v1c_accounting as successor_accounting  # noqa: E402


class RunnerError(RuntimeError):
    """A V1-C campaign invariant was not satisfied."""


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def digest_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------------------
# Retained-transcript regression (Phase 2): prove the successor reducer
# against accepted retained raw bytes BEFORE any new physical output.
# ---------------------------------------------------------------------------

def reduce_retained_transcript(stderr: str, *, selector: str, predecessor_label: str) -> dict[str, Any]:
    """Reduce an accepted retained transcript under the successor reducer."""
    accounting = successor_accounting.parse_accounting(stderr, selector=selector)
    for key in ("unexplained_persistent_host_mirror_bytes", "source_fetches_after_ready",
                "unplanned_state_movements"):
        if accounting[key] != 0:
            raise RunnerError(f"retained {predecessor_label} accounting disposition not clean: {key}")
    return accounting


def v1a_regression_proof() -> dict[str, Any]:
    """Field-by-field mechanical equivalence with the accepted V1-A artifact."""
    frozen_v1a_selector = "Vulkan1"
    stderr_path = ROOT / "docs/investigations/vulkan-v1-a/raw/v1a-amd-a-canonical-01/stderr.txt"
    artifact_path = ROOT / "docs/investigations/vulkan-v1-a/evidence/v1a-amd-a-canonical-01/accounting.json"
    stderr = stderr_path.read_text(encoding="utf-8")
    accepted = json.loads(artifact_path.read_text(encoding="utf-8"))
    reproduced = successor_accounting.parse_accounting(stderr, selector=frozen_v1a_selector)
    # Every accepted /1 fact and raw line must be reproduced IDENTICALLY.
    inherited_fields = sorted(set(accepted) - {"schema"})
    field_results = {field: {"accepted": accepted[field], "reproduced": reproduced.get(field),
                             "identical": accepted[field] == reproduced.get(field)}
                     for field in inherited_fields}
    differing = [field for field, result in field_results.items() if not result["identical"]]
    if differing:
        raise RunnerError(f"successor accounting differs from accepted V1-A facts: {differing}")
    # Byte-identical canonical JSON over the shared fact fields.
    accepted_facts = {key: value for key, value in accepted.items() if key != "schema"}
    reproduced_facts = {key: value for key, value in reproduced.items()
                        if key not in ("schema", "selected_resource", "predecessor")}
    facts_byte_identical = canonical(accepted_facts) == canonical(reproduced_facts)
    if not facts_byte_identical:
        raise RunnerError("shared accounting facts are not byte-identical canonical JSON")
    for key in ("unexplained_persistent_host_mirror_bytes", "source_fetches_after_ready",
                "unplanned_state_movements"):
        if reproduced[key] != 0:
            raise RunnerError(f"regression accounting disposition not clean: {key}")
    return {
        "schema": "inferswarm.v1c.retained-transcript-regression/1",
        "subject": "V1-A (accepted first subject)",
        "retained_stderr": str(stderr_path.relative_to(ROOT)),
        "retained_stderr_sha256": digest_bytes(stderr_path.read_bytes()),
        "accepted_artifact": str(artifact_path.relative_to(ROOT)),
        "accepted_artifact_sha256": digest_bytes(artifact_path.read_bytes()),
        "selector_source": "accepted V1-A authority frozen.selector",
        "selector": frozen_v1a_selector,
        "inherited_fields": inherited_fields,
        "field_by_field_identical": True,
        "shared_facts_byte_identical": True,
        "three_tuple_zero": True,
        "result": "PASS",
    }


def v1b_retained_reduction(v1b_authority_path: Path) -> dict[str, Any]:
    """Reduce the accepted retained V1-B second-subject transcript."""
    authority = json.loads(v1b_authority_path.read_text(encoding="utf-8"))
    frozen = authority["frozen"]
    stderr_path = ROOT / "docs/investigations/vulkan-v1-b/raw/v1b-nv-a-canonical-01/stderr.txt"
    stderr = stderr_path.read_text(encoding="utf-8")
    accounting = successor_accounting.parse_accounting(stderr, selector=frozen["selector"])
    three_tuple = [accounting["unexplained_persistent_host_mirror_bytes"],
                   accounting["source_fetches_after_ready"],
                   accounting["unplanned_state_movements"]]
    if any(value != 0 for value in three_tuple):
        raise RunnerError("retained V1-B accounting disposition not clean")
    return {
        "schema": "inferswarm.v1c.retained-transcript-regression/1",
        "subject": "V1-B (accepted second subject, retrospective reduction only)",
        "retained_stderr": str(stderr_path.relative_to(ROOT)),
        "retained_stderr_sha256": digest_bytes(stderr_path.read_bytes()),
        "selector_source": "accepted V1-B authority frozen.selector",
        "selector": frozen["selector"],
        "accounting": accounting,
        "three_tuple": three_tuple,
        "role": "retrospective direct-evidence reduction; NOT the prospective V1-C physical PASS",
        "result": "PASS",
    }


# ---------------------------------------------------------------------------
# Phase 3 canonical stage: the accepted V1-A canonical orchestration with
# the successor accounting reducer substituted. Every other accepted
# component is imported and reused unchanged, in the accepted order.
# ---------------------------------------------------------------------------

def execute_canonical(authority: Mapping[str, Any], plan: Mapping[str, Any], measured: Mapping[str, Any],
                      out: Path) -> dict[str, Any]:
    frozen = authority["frozen"]
    participant.validate_frozen_plan(plan)
    if "plan_digest" in frozen and plan["plan_digest"] != frozen["plan_digest"]:
        raise RunnerError("frozen plan digest differs from authority")
    candidate = plan["candidate"]
    for field in ("node_id", "compute_unit_id", "memory_resource_id", "execution_unit_id",
                  "execution_contract_id", "implementation_id", "physical_device_bdf"):
        if candidate.get(field) != frozen[field]:
            raise RunnerError(f"frozen candidate {field} mismatch")
    if "candidate_id" in frozen and candidate.get("candidate_id") != frozen["candidate_id"]:
        raise RunnerError("frozen candidate_id mismatch")
    run = accepted_runner._execute(frozen, out)
    if run["exit_code"] != 0:
        raise RunnerError(f"canonical exit was not clean: {run['exit_code']}")
    observation = adapter.parse_backend_observation(
        stderr=run["stderr"], selector=frozen["selector"], expected_bdf=frozen["physical_device_bdf"],
        node_id=candidate["node_id"], compute_unit_id=candidate["compute_unit_id"],
        memory_resource_id=candidate["memory_resource_id"], execution_unit_id=candidate["execution_unit_id"],
        execution_contract_id=candidate["execution_contract_id"],
        implementation_id=candidate["implementation_id"], evidence_id=candidate["evidence_id"],
        runtime_identity=candidate["runtime_identity"])
    # Selector-aware successor accounting reducer: the ONLY superseded
    # stage. The selector is consumed from the frozen authority.
    accounting = successor_accounting.parse_accounting(run["stderr"], selector=frozen["selector"])
    for key in ("unexplained_persistent_host_mirror_bytes", "source_fetches_after_ready",
                "unplanned_state_movements"):
        if accounting[key] != 0:
            raise RunnerError(f"accounting disposition not clean: {key}")
    # Accepted V0-C byte-exact correctness comparator, unchanged.
    correctness = v0c_correctness.reduce(run["stdout"], frozen["prompt"].encode(),
                                         Path(frozen["reference_output"]).read_bytes())
    if not correctness["byte_exact_visible_output"]:
        raise RunnerError("byte-exact correctness comparison failed")
    proof = adapter.seal_canonical_execution_proof(
        observation=observation, plan_digest=plan["plan_digest"], candidate_id=candidate["candidate_id"],
        execution_contract_id=candidate["execution_contract_id"],
        execution_evidence_id=frozen["canonical_execution_evidence_id"], stdout=run["stdout"],
        stderr=run["stderr"], exit_code=run["exit_code"])
    observation_record = participant.canonical_observation(plan=plan, canonical_proof=proof)
    # V0-C receipt semantics: attribution covers the canonical visible
    # response bytes, not the raw spinner-laden transcript.
    receipt = participant.execution_receipt(plan=plan, output=correctness["visible_response_bytes"],
                                            canonical_proof=proof)
    return {"run": run, "accounting": accounting, "correctness": correctness, "proof": proof,
            "canonical_observation": observation_record, "receipt": receipt}


# ---------------------------------------------------------------------------
# Cross-subject accounting/generalization audit (Phase 8).
# ---------------------------------------------------------------------------

GENERIC_SOURCES = (
    "scripts/v1a_execution_participant.py",
    "scripts/v1a_vulkan_adapter.py",
    "scripts/v1a_runner.py",
    "scripts/v0c_correctness.py",
)


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_cross_subject_audit(v1a_authority: Mapping[str, Any], v1b_authority: Mapping[str, Any],
                              v1c_authority: Mapping[str, Any], regression: Mapping[str, Any],
                              retained_v1b: Mapping[str, Any], qualification: Mapping[str, Any],
                              candidate_set: Mapping[str, Any],
                              canonical: Mapping[str, Any]) -> dict[str, Any]:
    v1c_frozen = v1c_authority["frozen"]
    current_generic = {path: _sha256_file(ROOT / path) for path in GENERIC_SOURCES}
    accepted_pins = v1c_authority["accepted_source_pins"]
    generic_reused = all(current_generic[path] == accepted_pins[path] for path in GENERIC_SOURCES)
    successor_path = "scripts/v1c_accounting.py"
    successor_current = _sha256_file(ROOT / successor_path)
    selector_authority_only = (
        v1c_frozen["selector"] == v1b_authority["frozen"]["selector"]
        and canonical.get("accounting", {}).get("selected_resource") == v1c_frozen["selector"])
    subject_specific_code_remaining: list[str] = []
    if not generic_reused:
        subject_specific_code_remaining.append("generic source drift vs accepted pins")
    if successor_current != v1c_authority["source_freeze"]["successor_accounting_reducer_sha256"]:
        subject_specific_code_remaining.append("successor accounting reducer drift vs authority pin")
    classifications = [
        {"aspect": "accepted generic participant/adapter/runner/comparator bytes reused unchanged",
         "evidence": {"pins_match_current": generic_reused},
         "classification": "ACCEPTED_GENERIC_SEMANTICS_REUSED" if generic_reused else "SUBJECT_SPECIFIC_CODE_REMAINS"},
        {"aspect": "selected Vulkan resource label origin",
         "evidence": {"selector": v1c_frozen["selector"],
                      "origin": "frozen V1-C physical authority (re-measured from the current host), consumed as data",
                      "observed_selected_resource": canonical.get("accounting", {}).get("selected_resource")},
         "classification": "SELECTOR_AUTHORITY_DATA_ONLY" if selector_authority_only else "SUBJECT_SPECIFIC_CODE_REMAINS"},
        {"aspect": "selector-aware successor accounting reducer replacing the first-subject-pinned /1 reducer",
         "evidence": {"module": successor_path,
                      "authority_pin": v1c_authority["source_freeze"]["successor_accounting_reducer_sha256"],
                      "current": successor_current,
                      "v1a_regression_field_identical": regression.get("field_by_field_identical"),
                      "v1a_regression_byte_identical": regression.get("shared_facts_byte_identical"),
                      "v1b_retained_reduced": retained_v1b.get("result") == "PASS",
                      "v1b_retained_three_tuple": retained_v1b.get("three_tuple")},
         "classification": "GENERIC_ACCOUNTING_REFACTOR_ACCEPTED"
         if (regression.get("field_by_field_identical") and retained_v1b.get("result") == "PASS"
             and successor_current == v1c_authority["source_freeze"]["successor_accounting_reducer_sha256"])
         else "SUBJECT_SPECIFIC_CODE_REMAINS"},
        {"aspect": "V1-B historical finding",
         "evidence": {"terminal": "V1B_SECOND_SUBJECT_REFACTOR_REQUIRED",
                      "note": "historical terminal retained verbatim; not rewritten or promoted"},
         "classification": "ACCEPTED_GENERIC_SEMANTICS_REUSED"},
        {"aspect": "foundational invariants (byte-exact comparator, contract binding, receipt attribution)",
         "evidence": {"byte_exact": canonical.get("correctness", {}).get("byte_exact_visible_output"),
                      "planner_explanations": candidate_set.get("explanations")},
         "classification": "FOUNDATIONAL_INVARIANT_FALSIFIED"
         if not canonical.get("correctness", {}).get("byte_exact_visible_output")
         else "ACCEPTED_GENERIC_SEMANTICS_REUSED"},
    ]
    passed = (generic_reused and selector_authority_only
              and regression.get("field_by_field_identical") and regression.get("shared_facts_byte_identical")
              and retained_v1b.get("result") == "PASS"
              and not subject_specific_code_remaining
              and not any(row["classification"] == "FOUNDATIONAL_INVARIANT_FALSIFIED"
                          for row in classifications))
    return {
        "schema": "inferswarm.v1c.cross-subject-audit/1",
        "compared": {
            "v1a": {"issue": v1a_authority["issue"], "terminal": "V1A_REUSABLE_VULKAN_PARTICIPANT_PASS",
                    "subject": {"compute_unit_id": v1a_authority["frozen"]["compute_unit_id"],
                                "selector": v1a_authority["frozen"]["selector"],
                                "accounting_schema": "inferswarm.v0c.materialization-accounting/1"}},
            "v1b": {"issue": v1b_authority["issue"], "terminal": "V1B_SECOND_SUBJECT_REFACTOR_REQUIRED",
                    "subject": {"compute_unit_id": v1b_authority["frozen"]["compute_unit_id"],
                                "selector": v1b_authority["frozen"]["selector"],
                                "accounting_disposition": "FAIL_CLOSED, retained verbatim"}},
            "v1c": {"issue": v1c_authority["issue"],
                    "subject": {"compute_unit_id": v1c_frozen["compute_unit_id"],
                                "selector": v1c_frozen["selector"],
                                "accounting_schema": successor_accounting.SCHEMA},
                    "qualification": qualification.get("qualification_evidence_id"),
                    "canonical": canonical.get("canonical_execution_evidence_id")},
        },
        "accounting_reducer_identities": {
            "accepted_v0c": {"module": "scripts/v0c_canonical_run.py::parse_accounting",
                             "sha256": accepted_pins["scripts/v0c_canonical_run.py"],
                             "schema": "inferswarm.v0c.materialization-accounting/1",
                             "disposition": "unchanged historical bytes; superseded on the V1-C path only"},
            "successor_v1c": {"module": "scripts/v1c_accounting.py::parse_accounting",
                              "sha256": successor_current,
                              "schema": "inferswarm.v0c.materialization-accounting/2"},
        },
        "classifications": classifications,
        "subject_specific_code_remaining": subject_specific_code_remaining,
        "foundational_invariant_falsified": any(
            row["classification"] == "FOUNDATIONAL_INVARIANT_FALSIFIED" for row in classifications),
        "audit_conclusion": ("selector is authority data on the V1-C canonical path; accepted generic "
                            "semantics reused unchanged; the accounting refactor is generic (no subject, "
                            "vendor, or selector literal in reusable logic)")
                            if passed else
                            ("cross-subject portability is not yet provable generically: "
                             + "; ".join(subject_specific_code_remaining or ["see classifications"])),
        "result": "PASS" if passed else "FAIL",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--authority", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--mode", choices=("preflight", "qualify", "plan", "canonical",
                                           "regression", "audit"), required=True)
    parser.add_argument("--capability")
    parser.add_argument("--plan")
    parser.add_argument("--v1a-authority")
    parser.add_argument("--v1b-authority")
    parser.add_argument("--regression")
    parser.add_argument("--retained-v1b")
    parser.add_argument("--qualification")
    parser.add_argument("--candidate-set")
    parser.add_argument("--canonical-record")
    args = parser.parse_args(argv)
    authority = json.loads(Path(args.authority).read_text(encoding="utf-8"))
    out = Path(args.out)
    frozen = authority["frozen"]

    if args.mode == "preflight":
        measured = accepted_runner.preflight(authority)
        print(canonical({"result": "PASS", "measured": measured}).decode())
        return 0

    if args.mode == "qualify":
        measured = accepted_runner.preflight(authority)
        result = accepted_runner.qualify(authority, measured, out)
        record = result["record"]
        record["schema"] = "inferswarm.v1c.qualification/1"
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
        snapshot = accepted_runner.build_snapshot(authority, capability)
        decision, plan = accepted_runner.plan_and_freeze(authority, snapshot)
        out.mkdir(parents=True, exist_ok=False)
        (out / "resource-snapshot.json").write_bytes(canonical(snapshot) + b"\n")
        (out / "candidate-set.json").write_bytes(canonical(decision) + b"\n")
        (out / "frozen-plan.json").write_bytes(canonical(plan) + b"\n")
        print(plan["plan_digest"])
        return 0

    if args.mode == "canonical":
        plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
        measured = accepted_runner.preflight(authority)
        result = execute_canonical(authority, plan, measured, out)
        record = {
            "schema": "inferswarm.v1c.canonical-execution/1",
            "canonical_execution_evidence_id": frozen["canonical_execution_evidence_id"],
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
        # Adapter-sealed evidence records, retained separately.
        evidence = out.parent.parent / "evidence" / frozen["canonical_execution_evidence_id"]
        evidence.mkdir(parents=True, exist_ok=True)
        (evidence / "accounting.json").write_bytes(canonical(result["accounting"]) + b"\n")
        (evidence / "correctness-result.json").write_bytes(canonical(
            {k: (v.decode("utf-8") if isinstance(v, bytes) else v)
             for k, v in result["correctness"].items()}) + b"\n")
        (evidence / "canonical-observation.json").write_bytes(canonical(result["canonical_observation"]) + b"\n")
        (evidence / "execution-receipt.json").write_bytes(canonical(result["receipt"]) + b"\n")
        print(record["record_digest"])
        return 0

    if args.mode == "regression":
        v1a_proof = v1a_regression_proof()
        v1b_proof = v1b_retained_reduction(Path(args.v1b_authority))
        record = {
            "schema": "inferswarm.v1c.retained-transcript-regressions/1",
            "v1a_regression": v1a_proof,
            "v1b_retained_reduction": v1b_proof,
            "negative_controls": "executed in tests/test_v1c_accounting.py (fail-closed contract)",
            "result": "PASS" if v1a_proof["result"] == "PASS" and v1b_proof["result"] == "PASS" else "FAIL",
        }
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(canonical(record) + b"\n")
        print(record["result"])
        return 0

    # audit
    v1a_authority = json.loads(Path(args.v1a_authority).read_text(encoding="utf-8"))
    v1b_authority = json.loads(Path(args.v1b_authority).read_text(encoding="utf-8"))
    regression = json.loads(Path(args.regression).read_text(encoding="utf-8"))
    retained_v1b = json.loads(Path(args.retained_v1b).read_text(encoding="utf-8")) \
        if args.retained_v1b else regression["v1b_retained_reduction"]
    qualification = json.loads(Path(args.qualification).read_text(encoding="utf-8"))
    candidate_set = json.loads(Path(args.candidate_set).read_text(encoding="utf-8"))
    canonical_record = json.loads(Path(args.canonical_record).read_text(encoding="utf-8"))
    audit = build_cross_subject_audit(v1a_authority, v1b_authority, authority, regression,
                                      retained_v1b, qualification, candidate_set, canonical_record)
    out.write_bytes(canonical(audit) + b"\n")
    print(audit["result"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
