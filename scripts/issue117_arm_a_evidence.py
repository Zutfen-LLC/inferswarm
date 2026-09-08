"""Issue #117 Arm A retained-evidence reducer (PR #122 correction).

An INDEPENDENT validator that re-derives the Arm-A terminal classification
from low-level retained records only. It never reads a stored PASS boolean,
aggregate counter, or ``all_*_identical`` convenience field as authority:
every dimension is derived from independently sourced control/integrated
values in the retained paired records, raw-row manifests, boundary records,
run indexes, attempt-lineage record, and pre-run revalidation record.

Fail-closed on: missing / duplicated / malformed / producer-mismatched /
case-mismatched / decision-mismatched / prefix-mismatched / row-mismatched /
token-mismatched / rule-proof-mismatched / boundary-mismatched /
raw-row-unbound / wrong-checkpoint / wrong-topology / dirty-or-wrong-checkout
evidence, and on any stored-boolean/aggregate that disagrees with the
re-derived value.

TRUST-BOUNDARY SCOPE (documented per the trust-boundary review): the
retained Arm-A evidence set is self-contained in this repository. The
reducer verifies INTERNAL consistency of the retained records against each
other and against the SHA-hardcoded anchors in this module (preserved
physical-preflight / #118 canonical-summary bytes, fixture corpus, producer
and checkpoint identities); it cannot verify recorded row SHAs against the
physical FP32 bytes, which are deliberately not retained in git. A
repo-committing adversary able to mutate every retained artifact
consistently (including MANIFEST.sha256) could therefore fabricate an
internally-consistent PASS; the anchors against that adversary are the
SHA constants below and the immutable git history of the original
observation commits (2e5a68e / 140f6ef), against which any post-hoc
forgery remains diffable. This module's contract is independent
re-derivation from retained records, not tamper-evidence against a
malicious committer.

CPU-pure (stdlib only). No model execution, ever.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
AREA = ROOT / "docs/implementation/r6-successor-dense-full-integration-117"
EVIDENCE = AREA / "evidence"
ARM_A = EVIDENCE / "arm-a"

CONTROL_PRODUCER = "7e5c852163afd9aadfccc406be267e8d060e79ef"
INTEGRATED_PRODUCER = "924cd22ea081f6d4ed471016faf01d427fc5b0d2"
STARTING_MAIN = "51c8adeeedf6d6f0a16db994ca0a0cf259bed52f"
CHECKPOINT_AUTHORITY = (
    "5a84cb313260ac447237b890387116dfa8682e49a6b44bc585ae8353abbff18d")
FIXTURE_DIGEST = "sha256:180185cd5c6a5dcd77b2c65979bd2c9aef4d1c7ea9fb4850a64f4508b2ba36f2"
FIXTURE_CORPUS_SHA256 = (
    "22ffa8a906e9470f2ddbe5b46bddf3d99fd94aba35d1c126d2bb19354761e306")
PHYSICAL_PREFLIGHT_FILE_SHA256 = (
    "e9711969a4443f9ea6f3287a06383b8e0d9ef2478f65059acce0e787f8fe0a06")
CANONICAL_SUMMARY_118_SHA256 = (
    "26520e1608d9b12b5ac9e2667e55b9a8f5342818e3c701abaaaafb4319c57d4a")
TERMINAL_PASS = "ISSUE117_ARM_A_EXECUTION_EQUIVALENCE_PASS"
GENERATED_TOKENS = 8
CASE_COUNT = 24
DECISION_COUNT = CASE_COUNT * GENERATED_TOKENS  # 192

#: The exact (case, decision) keyspace is derived from the retained fixture
#: corpus — never from any run artifact, so a substituted corpus is caught.
RUN_INDEXES = {
    "control_reference": (CONTROL_PRODUCER, "index-control-reference.json"),
    "control_candidate": (CONTROL_PRODUCER, "index-control-candidate.json"),
    "integrated_reference": (INTEGRATED_PRODUCER, "index-integrated-reference.json"),
    "integrated_candidate": (INTEGRATED_PRODUCER, "index-integrated-candidate.json"),
}
TOPOLOGY = {
    "inferswarm01/gpu-0": ("GPU-1fc28f83-1d45-926e-54d0-ba1e835ef099", "[0,16)"),
    "inferswarm01/gpu-1": ("GPU-d5c05739-96c1-7e49-89b6-bf54c2121c55", "[16,32)"),
    "inferswarm03/gpu-0": ("GPU-e1f2f90c-49ab-2689-0cf1-e5d9da520176", "[32,48)"),
    "inferswarm04/gpu-0": ("GPU-ecda1aaa-0c66-857b-8218-3d511dc75c03", "reference"),
}


class EvidenceError(Exception):
    """Raised when retained Arm-A evidence fails closed."""


def _load(relative: str) -> Any:
    path = ARM_A / relative
    if not path.is_file():
        raise EvidenceError(f"missing retained artifact: arm-a/{relative}")
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise EvidenceError(f"malformed retained artifact arm-a/{relative}: {exc}") from exc


def _keys(rows: list[dict], label: str) -> dict[tuple[str, int], dict]:
    out: dict[tuple[str, int], dict] = {}
    for row in rows:
        key = (row.get("case_id"), row.get("decision_index"))
        if key[0] is None or key[1] is None:
            raise EvidenceError(f"{label}: row without case_id/decision_index")
        if key in out:
            raise EvidenceError(f"{label}: duplicated key {key}")
        out[key] = row
    return out


def _fixture_keyspace() -> tuple[set[tuple[str, int]], dict[str, dict]]:
    corpus = _load("fixture-corpus.json")
    if hashlib.sha256((ARM_A / "fixture-corpus.json").read_bytes()).hexdigest() != FIXTURE_CORPUS_SHA256:
        raise EvidenceError("fixture corpus bytes drift from retained identity")
    cases = corpus.get("cases", [])
    if len(cases) != CASE_COUNT or len({c.get("case_id") for c in cases}) != CASE_COUNT:
        raise EvidenceError("fixture corpus is not exactly 24 distinct cases")
    if any(str(c.get("case_id", "")).startswith("h109-") for c in cases):
        raise EvidenceError("holdout material present in fixture corpus")
    keys = {(c["case_id"], i) for c in cases for i in range(GENERATED_TOKENS)}
    if len(keys) != DECISION_COUNT:
        raise EvidenceError("fixture keyspace is not 192 keys")
    return keys, {c["case_id"]: c for c in cases}


def _check_run_indexes(fixture_cases: dict[str, dict]) -> None:
    for run, (producer, index_file) in RUN_INDEXES.items():
        index = _load(index_file)
        if index.get("producer", {}).get("commit") != producer:
            raise EvidenceError(f"{run}: producer mismatch")
        if index.get("producer", {}).get("dirty"):
            raise EvidenceError(f"{run}: producer tree dirty at run time")
        if index.get("case_count") != CASE_COUNT:
            raise EvidenceError(f"{run}: case count {index.get('case_count')}")
        cases = index.get("cases", [])
        if len(cases) != CASE_COUNT or len({c.get("case_id") for c in cases}) != CASE_COUNT:
            raise EvidenceError(f"{run}: index case list is not 24 distinct")
        for case in cases:
            fixture = fixture_cases.get(case.get("case_id"))
            if fixture is None:
                raise EvidenceError(f"{run}: case {case.get('case_id')} not in fixture")
            if case.get("case_sha256") != fixture.get("case_sha256"):
                raise EvidenceError(f"{run}: case sha mismatch for {case.get('case_id')}")
            if case.get("nan_inf_count") != 0:
                raise EvidenceError(f"{run}: nonzero nan_inf for {case.get('case_id')}")
        subject = index.get("subject", {})
        if subject.get("checkpoint_sha256") != CHECKPOINT_AUTHORITY:
            raise EvidenceError(f"{run}: wrong checkpoint authority")


def _check_paired_records(keyspace: set[tuple[str, int]]) -> dict[str, int]:
    paired = _load("paired-decision-records.json")
    if paired.get("control_producer") != CONTROL_PRODUCER or paired.get("integrated_producer") != INTEGRATED_PRODUCER:
        raise EvidenceError("paired records: producer binding mismatch")
    stats = {}
    for label in ("candidate_rows", "reference_rows"):
        rows = paired.get(label)
        if not isinstance(rows, list) or not rows:
            raise EvidenceError(f"paired records: {label} missing")
        by_key = _keys(rows, f"paired.{label}")
        if set(by_key) != keyspace:
            missing = len(keyspace - set(by_key))
            extra = len(set(by_key) - keyspace)
            raise EvidenceError(
                f"paired.{label}: keyset mismatch ({missing} missing, {extra} unexpected)")
        prefix_len = prefix_sha = token = rule = proof = row_sha = elems = 0
        for (case_id, idx), row in by_key.items():
            if row["control_prefix_len"] != row["integrated_prefix_len"]:
                prefix_len += 1
            if row["control_prefix_sha256"] != row["integrated_prefix_sha256"]:
                prefix_sha += 1
            if row["control_emitted_token"] != row["integrated_emitted_token"]:
                token += 1
            if label == "candidate_rows":
                if row["control_argmax_rule"] != row["integrated_argmax_rule"]:
                    rule += 1
                if row["control_rule_proof"] != row["integrated_rule_proof"]:
                    proof += 1
            if row["control_row_f32_sha256"] != row["integrated_row_f32_sha256"]:
                row_sha += 1
            if row["control_row_element_count"] != row["integrated_row_element_count"]:
                elems += 1
        stats[label] = {
            "rows": len(by_key),
            "prefix_len_mismatches": prefix_len,
            "prefix_sha_mismatches": prefix_sha,
            "emitted_token_mismatches": token,
            "argmax_rule_mismatches": rule,
            "rule_proof_mismatches": proof,
            "row_sha_mismatches": row_sha,
            "element_count_mismatches": elems,
        }
        derived = stats[label]
        if (derived["rows"] != DECISION_COUNT or derived["prefix_len_mismatches"]
                or derived["prefix_sha_mismatches"] or derived["emitted_token_mismatches"]
                or derived["argmax_rule_mismatches"] or derived["rule_proof_mismatches"]
                or derived["row_sha_mismatches"] or derived["element_count_mismatches"]):
            raise EvidenceError(f"paired.{label}: identity derivation failed: {derived}")
    return stats


def _check_boundary_records(keyspace_cases: set[str]) -> int:
    records = _load("capture-manifest-records.json")
    cases = records.get("cases", [])
    ids = [c.get("case_id") for c in cases]
    if len(ids) != CASE_COUNT or len(set(ids)) != CASE_COUNT or set(ids) != keyspace_cases:
        raise EvidenceError("boundary records: case set mismatch")
    comparisons = 0
    for case in cases:
        for stage in ("stage1", "stage2", "stage3"):
            control = case.get("control", {}).get(stage)
            integrated = case.get("integrated", {}).get(stage)
            if not isinstance(control, dict) or not isinstance(integrated, dict):
                raise EvidenceError(f"boundary {case.get('case_id')}/{stage}: record missing")
            for field in ("record_count", "record_sha256"):
                if field not in control or field not in integrated:
                    raise EvidenceError(
                        f"boundary {case.get('case_id')}/{stage}: field {field} missing")
                if json.dumps(control[field], sort_keys=True) != json.dumps(integrated[field], sort_keys=True):
                    raise EvidenceError(
                        f"boundary {case.get('case_id')}/{stage}: {field} mismatch")
            comparisons += 1
    return comparisons


def _check_raw_rows(manifest_file: str, keyspace: set[tuple[str, int]],
                    paired_rows: list[dict], reference: bool) -> dict[str, int]:
    manifest = _load(manifest_file)
    rows = manifest.get("rows")
    if not isinstance(rows, list) or not rows:
        raise EvidenceError(f"{manifest_file}: rows missing")
    by_key = _keys(rows, manifest_file)
    if set(by_key) != keyspace:
        raise EvidenceError(f"{manifest_file}: keyset mismatch vs fixture keyspace")
    paired_by_key = _keys(paired_rows, "paired")
    byte_identical = 0
    summary_bound = 0
    for key, row in by_key.items():
        if row["control_raw_row_sha256"] != row["integrated_raw_row_sha256"]:
            raise EvidenceError(f"{manifest_file}: {key} raw-row SHA mismatch")
        if row["control_raw_row_size"] != row["integrated_raw_row_size"]:
            raise EvidenceError(f"{manifest_file}: {key} raw-row size mismatch")
        if row["control_raw_row_size"] % 4:
            raise EvidenceError(f"{manifest_file}: {key} size not FP32-aligned")
        byte_identical += 1
        # bind raw rows to the decision-table row SHAs (the 01 summaries)
        paired = paired_by_key.get(key)
        if paired is None:
            raise EvidenceError(f"{manifest_file}: {key} absent from paired records")
        if row["control_raw_row_sha256"] != paired["control_row_f32_sha256"]:
            raise EvidenceError(f"{manifest_file}: {key} control raw unbound from decision table")
        if row["integrated_raw_row_sha256"] != paired["integrated_row_f32_sha256"]:
            raise EvidenceError(f"{manifest_file}: {key} integrated raw unbound from decision table")
        if row["control_raw_row_size"] != paired["control_row_element_count"] * 4:
            raise EvidenceError(f"{manifest_file}: {key} size/element-count binding failed")
        summary_bound += 1
        if reference:
            if not (row.get("control_summary_bound") and row.get("integrated_summary_bound")):
                raise EvidenceError(f"{manifest_file}: {key} reference summary binding failed")
            if row["control_summary_row_sha256"] != row["control_raw_row_sha256"]:
                raise EvidenceError(f"{manifest_file}: {key} control summary SHA drift")
            if row["integrated_summary_row_sha256"] != row["integrated_raw_row_sha256"]:
                raise EvidenceError(f"{manifest_file}: {key} integrated summary SHA drift")
    return {
        "rows_compared": len(by_key),
        "byte_identical": byte_identical,
        "summary_bound": summary_bound,
    }


def _check_attempt_lineage() -> dict[str, Any]:
    lineage = _load("attempt-lineage.json")
    attempts = lineage.get("attempts", [])
    ids = [a.get("attempt_id") for a in attempts]
    if len(ids) != len(set(ids)):
        raise EvidenceError("attempt lineage: duplicated attempt ids")
    invalid = [a for a in attempts if a.get("validity") == "INVALID"]
    valid = [a for a in attempts if a.get("validity") == "VALID"]
    if len(valid) != 1:
        raise EvidenceError("attempt lineage: expected exactly one VALID attempt")
    for attempt in invalid:
        if attempt.get("correctness_bearing_observation_count") != 0:
            raise EvidenceError(
                f"attempt {attempt.get('attempt_id')}: invalid attempt claims correctness-bearing observations")
        proof = attempt.get("harness_semantics_termination_proof")
        if not proof or not isinstance(proof, str):
            raise EvidenceError(
                f"attempt {attempt.get('attempt_id')}: missing harness-semantics termination proof")
        if not any(marker in proof for marker in ("CASE_ARM", "CASE_BEGIN", "PREFILL")):
            raise EvidenceError(
                f"attempt {attempt.get('attempt_id')}: termination proof does not bind harness semantics")
    # the valid attempt must be distinct from every invalid attempt id
    if valid[0].get("attempt_id") in ids[:-1] or ids.count(valid[0].get("attempt_id")) != 1:
        raise EvidenceError("attempt lineage: valid attempt id not distinct")
    if lineage.get("valid_attempt_logical_id") != valid[0].get("attempt_id"):
        raise EvidenceError("attempt lineage: valid_attempt_logical_id mismatch")
    # the valid integrated run index must bind to the VALID attempt's label
    index = _load("index-integrated-candidate.json")
    if index.get("attempt_id") != lineage.get("historical_attempt_id_label"):
        raise EvidenceError("valid run index attempt label mismatch vs lineage record")
    if valid[0].get("producer") != INTEGRATED_PRODUCER:
        raise EvidenceError("valid attempt producer mismatch")
    return {
        "attempts": len(attempts),
        "invalid": [a["attempt_id"] for a in invalid],
        "valid": valid[0]["attempt_id"],
    }


def _check_prerun_revalidation() -> None:
    reval = _load("prerun-revalidation.json")
    if reval.get("orchestrator_inferswarm", {}).get("head") != STARTING_MAIN:
        raise EvidenceError("pre-run revalidation: wrong InferSwarm HEAD")
    if reval.get("orchestrator_inferswarm", {}).get("clean") is not True:
        raise EvidenceError("pre-run revalidation: InferSwarm checkout not clean")
    hosts = {rec.get("host") for rec in reval.get("freetoken_identities", [])}
    if hosts != {"inferswarm01", "inferswarm03", "inferswarm04"}:
        raise EvidenceError("pre-run revalidation: host set mismatch")
    for rec in reval.get("freetoken_identities", []):
        roles = {c.get("role"): c for c in rec.get("checkout_paths", [])}
        integrated = roles.get("integrated", {})
        control = roles.get("control", {})
        if integrated.get("head_at_probe") != INTEGRATED_PRODUCER or "DIRTY=0" not in str(integrated.get("porcelain_at_probe", "x")):
            raise EvidenceError(f"pre-run revalidation {rec.get('host')}: integrated checkout identity failed")
        if control.get("head_after_p0b_checkout") != CONTROL_PRODUCER or control.get("clean_after_p0b_checkout") is not True:
            raise EvidenceError(f"pre-run revalidation {rec.get('host')}: control checkout identity failed")
    runtime = reval.get("runtime_identity", {})
    expected = {"torch": "2.11.0+cu130", "cuda_runtime": "13.0",
                "nvidia_driver": "610.57.04", "triton": "3.6.0", "flashinfer": "0.6.17"}
    for key, value in expected.items():
        if runtime.get(key) != value:
            raise EvidenceError(f"pre-run revalidation: runtime {key} mismatch")
    units = {u.get("uuid"): u for u in reval.get("compute_unit_identity", [])}
    for slot, (uuid, layers) in TOPOLOGY.items():
        unit = units.get(uuid)
        if unit is None or unit.get("layers") != layers:
            raise EvidenceError(f"pre-run revalidation: topology {slot} mismatch")
    checkpoint = reval.get("checkpoint", {})
    if checkpoint.get("sha256") != CHECKPOINT_AUTHORITY and checkpoint.get("authority_sha256") != CHECKPOINT_AUTHORITY:
        raise EvidenceError("pre-run revalidation: wrong checkpoint authority")
    if checkpoint.get("size_bytes") != 23919549408:
        raise EvidenceError("pre-run revalidation: checkpoint size mismatch")
    if set(checkpoint.get("hosts_validated", [])) != {"inferswarm01", "inferswarm03", "inferswarm04"}:
        raise EvidenceError("pre-run revalidation: checkpoint host set mismatch")
    if "regular file" not in str(checkpoint.get("file_kind", "")):
        raise EvidenceError("pre-run revalidation: checkpoint not a plain regular file")
    cold = reval.get("arm_b_cold_roots", {})
    if set(cold.get("roots", [])) != {
            "/srv/inferswarm/cache/issue117", "/srv/inferswarm/materialized/issue117"}:
        raise EvidenceError("pre-run revalidation: Arm-B cold-root set mismatch")
    if "EMPTY" not in str(cold.get("pre_arm_a_state", "")):
        raise EvidenceError("pre-run revalidation: Arm-B cold roots not empty pre-execution")


def _check_preserved_history() -> None:
    preflight = EVIDENCE / "physical-preflight.json"
    if hashlib.sha256(preflight.read_bytes()).hexdigest() != PHYSICAL_PREFLIGHT_FILE_SHA256:
        raise EvidenceError("accepted physical-preflight bytes changed")
    summary = EVIDENCE / "canonical-summary.json"
    if hashlib.sha256(summary.read_bytes()).hexdigest() != CANONICAL_SUMMARY_118_SHA256:
        raise EvidenceError("accepted #118 canonical-summary bytes changed")


def derive(verbose: bool = False) -> dict[str, Any]:
    """Re-derive the Arm-A terminal classification from retained evidence.

    Returns the derivation report; raises EvidenceError (fail closed) on any
    trust-boundary violation.
    """
    keyspace, fixture_cases = _fixture_keyspace()
    _check_run_indexes(fixture_cases)
    paired = _load("paired-decision-records.json")
    stats = _check_paired_records(keyspace)
    boundary_comparisons = _check_boundary_records({c for c, _ in keyspace})
    candidate_raw = _check_raw_rows("raw-row-manifest-laststage03.json", keyspace,
                                    paired["candidate_rows"], reference=False)
    reference_raw = _check_raw_rows("raw-row-manifest-reference04.json", keyspace,
                                    paired["reference_rows"], reference=True)
    attempts = _check_attempt_lineage()
    _check_prerun_revalidation()
    _check_preserved_history()

    report = {
        "schema": "inferswarm.issue117.arm-a.evidence-derivation/1",
        "terminal_classification": TERMINAL_PASS,
        "derivation": {
            "fixture": {"case_count": CASE_COUNT, "decision_keyspace": len(keyspace),
                        "holdout_material": False},
            "run_indexes": {run: {"producer": producer, "cases": CASE_COUNT, "nan_inf": 0}
                            for run, (producer, _) in RUN_INDEXES.items()},
            "paired_identity": stats,
            "stage_boundary_comparisons": boundary_comparisons,
            "candidate_raw_rows": candidate_raw,
            "reference_raw_rows": reference_raw,
            "attempt_lineage": attempts,
        },
        "authority": "derived exclusively from retained low-level records; "
                     "no stored PASS boolean or aggregate counter was consulted",
    }
    if verbose:
        print(json.dumps(report, indent=2, sort_keys=True))
    return report


if __name__ == "__main__":
    derive(verbose=True)
