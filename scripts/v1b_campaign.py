#!/usr/bin/env python3
"""Issue #158 V1-B second-subject campaign plumbing (local proving node only).

This module is DATA PLUMBING around the ACCEPTED, BYTE-UNCHANGED V1-A
campaign path. ``scripts/v1a_runner.py`` remains the only
correctness-bearing orchestrator (preflight, qualification, generic
planning, canonical execution); ``scripts/v1a_execution_participant.py``
remains the generic seam; ``scripts/v1a_vulkan_adapter.py`` remains the
backend boundary; ``scripts/v0c_correctness.py`` and the accounting
reducer in ``scripts/v0c_canonical_run.py`` remain the accepted
reducers. This wrapper only:

  * executes the prospectively frozen V1-B stability sample through the
    same accepted preflight and runtime argv, reducing each execution
    with the accepted adapter observation parser and the accepted
    byte-exact comparator;
  * invokes the accepted runner for the canonical attempt and reduces
    the retained raw bytes with the same accepted reducers, recording
    the accepted accounting reducer's disposition VERBATIM — including a
    fail-closed accounting error, which is retained as the finding, never
    bypassed or repaired here;
  * emits the machine-readable cross-subject reuse audit from the
    accepted V1-A authority/evidence and the V1-B bundle.

No accepted source is modified, reimplemented, or bypassed. No
selector, BDF, vendor, or device name is special-cased here: every
subject fact comes from the frozen V1-B authority.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import v1a_runner as accepted_runner  # noqa: E402
import v1a_vulkan_adapter as adapter  # noqa: E402
import v0c_correctness as correctness_reducer  # noqa: E402
import v0c_canonical_run as accounting_reducer  # noqa: E402


class CampaignError(RuntimeError):
    """A V1-B campaign invariant was not satisfied."""


def canonical_json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def digest_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def reduced_run(run: Mapping[str, Any]) -> dict[str, Any]:
    return {key: run[key] for key in accepted_runner.REDUCED_RUN_KEYS}


# ---------------------------------------------------------------------------
# Stability sample: prospectively judged executions under the frozen V1-B
# authority, through the accepted preflight/argv, reduced by the accepted
# adapter parser and byte-exact comparator only.
# ---------------------------------------------------------------------------

def run_stability_sample(authority: Mapping[str, Any], out_root: Path) -> list[str]:
    frozen = authority["frozen"]
    contract = authority["stability_contract"]
    prefix = contract["evidence_id_prefix"]
    size = int(contract["sample_size"])
    if size < 3:
        raise CampaignError("prospective stability sample must include at least three executions")
    digests = []
    out_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as scratch_root:
        for index in range(1, size + 1):
            evidence_id = f"{prefix}-stability-{index:02d}"
            # Every execution is judged under the accepted preflight, which
            # requires a clean repository tree: all raw bytes are written to
            # a scratch directory OUTSIDE the repository and moved into the
            # retained evidence location only after every execution in the
            # sample has completed.
            measured = accepted_runner.preflight(authority)
            scratch = Path(scratch_root) / f"stability-{index:02d}"
            run = accepted_runner._execute(frozen, scratch)
            record = reduce_stability_execution(authority, evidence_id, measured, run)
            (scratch / "stability.json").write_bytes(canonical_json(record) + b"\n")
            digests.append(record["record_digest"])
        for index in range(1, size + 1):
            source = Path(scratch_root) / f"stability-{index:02d}"
            destination = out_root / f"{prefix}-stability-{index:02d}"
            destination.mkdir(parents=True, exist_ok=False)
            for name in ("stdout.txt", "stderr.txt", "exit-code.txt", "stability.json"):
                (destination / name).write_bytes((source / name).read_bytes())
    return digests


def reduce_stability_execution(authority: Mapping[str, Any], evidence_id: str,
                               measured: Mapping[str, Any], run: Mapping[str, Any]) -> dict[str, Any]:
    frozen = authority["frozen"]
    result: dict[str, Any] = {
        "schema": "inferswarm.v1b.stability/1",
        "stability_evidence_id": evidence_id,
        "preflight": dict(measured),
        "attempt": reduced_run(run),
    }
    failures: list[str] = []
    if run["exit_code"] != 0:
        failures.append(f"exit was not clean: {run['exit_code']}")
    if not failures:
        observation = adapter.parse_backend_observation(
            stderr=run["stderr"], selector=frozen["selector"], expected_bdf=frozen["physical_device_bdf"],
            node_id=frozen["node_id"], compute_unit_id=frozen["compute_unit_id"],
            memory_resource_id=frozen["memory_resource_id"], execution_unit_id=frozen["execution_unit_id"],
            execution_contract_id=frozen["execution_contract_id"],
            implementation_id=frozen["implementation_id"], evidence_id=evidence_id,
            runtime_identity=frozen["runtime_identity"])
        result["offloaded_layers"] = list(observation.offloaded_layers)
        result["observation_digest"] = observation.proof_digest
        correctness = correctness_reducer.reduce(
            run["stdout"], frozen["prompt"].encode(),
            Path(frozen["reference_output"]).read_bytes())
        result["correctness"] = {key: (value.decode("utf-8") if isinstance(value, bytes) else value)
                                 for key, value in correctness.items()}
        if not correctness["byte_exact_visible_output"]:
            failures.append("visible output is not byte-exact against the frozen reference")
    result["result"] = "PASS" if not failures else "FAIL"
    if failures:
        result["failures"] = failures
    result["raw"] = {"stdout": "stdout.txt", "stderr": "stderr.txt", "exit_code": "exit-code.txt"}
    result["record_digest"] = digest_bytes(canonical_json(result))
    return result


# ---------------------------------------------------------------------------
# Canonical attempt: invoke the ACCEPTED runner unchanged, retain its raw
# output and its own exit disposition, then reduce the retained bytes with
# the accepted reducers. A fail-closed accounting error from the accepted
# reducer is recorded verbatim as the campaign finding.
# ---------------------------------------------------------------------------

def invoke_accepted_canonical_runner(authority_path: Path, plan_path: Path, out: Path) -> int:
    # The accepted runner's _execute creates the output directory itself
    # (exist_ok=False); this wrapper must not pre-create it.
    process = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "v1a_runner.py"), "--authority", str(authority_path),
         "--mode", "canonical", "--plan", str(plan_path), "--out", str(out)],
        capture_output=True, text=True, cwd=str(ROOT))
    out.mkdir(parents=True, exist_ok=True)
    (out / "runner-stdout.txt").write_text(process.stdout, encoding="utf-8")
    (out / "runner-stderr.txt").write_text(process.stderr, encoding="utf-8")
    (out / "runner-exit-code.txt").write_text(f"{process.returncode}\n", encoding="utf-8")
    return process.returncode


def reduce_canonical_attempt(authority: Mapping[str, Any], plan: Mapping[str, Any], raw: Path,
                             runner_exit: int) -> dict[str, Any]:
    frozen = authority["frozen"]
    candidate = plan["candidate"]
    record: dict[str, Any] = {
        "schema": "inferswarm.v1b.canonical-attempt/1",
        "canonical_execution_evidence_id": frozen["canonical_execution_evidence_id"],
        "plan_digest": plan["plan_digest"], "candidate_id": candidate["candidate_id"],
        "accepted_runner_exit_code": runner_exit,
    }
    failures: list[str] = []
    have_raw = all((raw / name).is_file() for name in ("stdout.txt", "stderr.txt", "exit-code.txt"))
    if not have_raw:
        failures.append("accepted runner produced no retained raw runtime execution "
                        "(failed before runtime execution)")
        record["result"] = "FAIL"
        record["failures"] = failures
        record["raw"] = {"accepted_runner_stdout": "runner-stdout.txt",
                         "accepted_runner_stderr": "runner-stderr.txt",
                         "accepted_runner_exit_code": "runner-exit-code.txt"}
        return record
    stdout = (raw / "stdout.txt").read_bytes()
    stderr_bytes = (raw / "stderr.txt").read_bytes()
    stderr = stderr_bytes.decode("utf-8")
    exit_code = int((raw / "exit-code.txt").read_text().strip())
    record["attempt"] = {"exit_code": exit_code, "stdout_sha256": digest_bytes(stdout),
                         "stderr_sha256": digest_bytes(stderr_bytes)}
    if exit_code == 0:
        observation = adapter.parse_backend_observation(
            stderr=stderr, selector=frozen["selector"], expected_bdf=frozen["physical_device_bdf"],
            node_id=candidate["node_id"], compute_unit_id=candidate["compute_unit_id"],
            memory_resource_id=candidate["memory_resource_id"], execution_unit_id=candidate["execution_unit_id"],
            execution_contract_id=candidate["execution_contract_id"],
            implementation_id=candidate["implementation_id"], evidence_id=candidate["evidence_id"],
            runtime_identity=candidate["runtime_identity"])
        record["offloaded_layers"] = list(observation.offloaded_layers)
        record["observation_digest"] = observation.proof_digest
    else:
        failures.append(f"canonical runtime exit was not clean: {exit_code}")
    # Accepted byte-exact comparator, unchanged: recorded regardless of the
    # accounting outcome.
    correctness = correctness_reducer.reduce(stdout, frozen["prompt"].encode(),
                                             Path(frozen["reference_output"]).read_bytes())
    record["correctness"] = {key: (value.decode("utf-8") if isinstance(value, bytes) else value)
                             for key, value in correctness.items()}
    if not correctness["byte_exact_visible_output"]:
        failures.append("visible output is not byte-exact against the frozen reference")
    # Accepted V0-C accounting reducer, unchanged. Its disposition —
    # including a fail-closed error on the second subject's transcript —
    # is the authoritative outcome and is never bypassed here.
    accounting = None
    accounting_error = None
    try:
        accounting = accounting_reducer.parse_accounting(stderr)
    except accounting_reducer.AccountingError as error:
        accounting_error = str(error)
    if accounting_error is not None:
        record["accounting"] = {"disposition": "FAIL_CLOSED",
                                "error": accounting_error,
                                "finding": "accepted V0-C accounting reducer cannot reduce the second-subject "
                                           "transcript; retained verbatim, not repaired in V1-B"}
        record["accounting_classification"] = "GENERIC_SEAM_CHANGE_REQUIRED"
        failures.append(f"accepted accounting reducer failed closed: {accounting_error}")
    else:
        record["accounting"] = accounting
        for key in ("unexplained_persistent_host_mirror_bytes", "source_fetches_after_ready",
                    "unplanned_state_movements"):
            if accounting[key] != 0:
                failures.append(f"accounting disposition not clean: {key}")
    record["result"] = "PASS" if not failures else "FAIL"
    if failures:
        record["failures"] = failures
    record["raw"] = {"stdout": "stdout.txt", "stderr": "stderr.txt", "exit_code": "exit-code.txt",
                     "accepted_runner_stdout": "runner-stdout.txt",
                     "accepted_runner_stderr": "runner-stderr.txt",
                     "accepted_runner_exit_code": "runner-exit-code.txt"}
    return record


# ---------------------------------------------------------------------------
# Cross-subject reuse audit: machine-readable comparison of the accepted
# V1-A first-subject campaign and the V1-B second-subject campaign.
# ---------------------------------------------------------------------------

ACCEPTED_SEAM_SOURCES = (
    "scripts/v1a_execution_participant.py",
    "scripts/v1a_vulkan_adapter.py",
    "scripts/v1a_runner.py",
    "scripts/v0c_canonical_run.py",
    "scripts/v0c_correctness.py",
)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def build_cross_subject_audit(v1a_authority: Mapping[str, Any], v1b_authority: Mapping[str, Any],
                              qualification: Mapping[str, Any], candidate_set: Mapping[str, Any],
                              canonical_attempt: Mapping[str, Any]) -> dict[str, Any]:
    v1a_frozen, v1b_frozen = v1a_authority["frozen"], v1b_authority["frozen"]
    current = {path: _sha256_file(ROOT / path) for path in ACCEPTED_SEAM_SOURCES}
    identical_sources = {
        path: {"v1a_pin": v1a_frozen["v1a_sources"][path],
               "v1b_pin": v1b_authority["accepted_source_pins"][path],
               "current": current[path],
               "identical": v1a_frozen["v1a_sources"][path] == v1b_authority["accepted_source_pins"][path] == current[path]}
        for path in ACCEPTED_SEAM_SOURCES}
    generic_identifiers = ["execution_contract_id", "execution_unit_id", "logical_state_id",
                           "required_representation", "required_features", "required_memory_bytes",
                           "required_headroom_bytes", "required_integrity_status", "correctness_policy", "objective"]
    shared_generic_identity = {key: {"v1a": v1a_frozen[key], "v1b": v1b_frozen[key],
                                     "identical": v1a_frozen[key] == v1b_frozen[key]}
                               for key in generic_identifiers}
    per_subject = {key: {"v1a": v1a_frozen[key], "v1b": v1b_frozen[key]}
                   for key in ("node_id", "compute_unit_id", "memory_resource_id", "physical_device_bdf",
                               "selector", "runtime_identity", "implementation_id")}
    accounting_requires_change = canonical_attempt.get("accounting_classification") == "GENERIC_SEAM_CHANGE_REQUIRED"
    classifications = [
        {"aspect": "generic participant (eligibility/ranking/plan validation/proof/observation/receipt semantics)",
         "evidence": identical_sources["scripts/v1a_execution_participant.py"],
         "classification": "AUTHORITY_DATA_ONLY"},
        {"aspect": "backend adapter (runtime parsing, offload/fallback validation, sealed capsules)",
         "evidence": identical_sources["scripts/v1a_vulkan_adapter.py"],
         "classification": "BACKEND_ADAPTER_DATA_ONLY"},
        {"aspect": "campaign runner (preflight, qualification, planning, canonical orchestration)",
         "evidence": identical_sources["scripts/v1a_runner.py"],
         "classification": "AUTHORITY_DATA_ONLY"},
        {"aspect": "byte-exact correctness comparator",
         "evidence": identical_sources["scripts/v0c_correctness.py"],
         "classification": "AUTHORITY_DATA_ONLY"},
        {"aspect": "accepted V0-C materialization/residency accounting reducer",
         "evidence": identical_sources["scripts/v0c_canonical_run.py"],
         "classification": "GENERIC_SEAM_CHANGE_REQUIRED" if accounting_requires_change else "AUTHORITY_DATA_ONLY",
         "basis": canonical_attempt.get("accounting", {}).get("error",
                                                              "accounting reduced the transcript cleanly")},
    ]
    return {
        "schema": "inferswarm.v1b.cross-subject-audit/1",
        "compared_campaigns": {
            "first_subject": {"issue": v1a_authority["issue"], "terminal": "V1A_REUSABLE_VULKAN_PARTICIPANT_PASS"},
            "second_subject": {"issue": v1b_authority["issue"]}},
        "identical_reusable_semantics": {
            "accepted_source_hashes": identical_sources,
            "generic_execution_identity": shared_generic_identity,
            "candidate_schema": {"v1a": "inferswarm.v1a.internal-plan/1", "v1b": "inferswarm.v1a.internal-plan/1"},
            "frozen_plan_schema": {"v1a": "inferswarm.v1a.internal-frozen-plan/1",
                                   "v1b": "inferswarm.v1a.internal-frozen-plan/1"},
            "planner_eligibility_and_ranking": "same accepted participant bytes on both subjects",
            "qualification_schema": {"v1a": "inferswarm.v1a.qualification/1",
                                     "v1b": qualification.get("schema")},
            "accounting_reducer_schema": "inferswarm.v0c.materialization-accounting/1",
            "correctness_reducer_schema": "inferswarm.v0c.correctness-result/2",
        },
        "legitimate_per_subject_authority_data": {
            "resource_and_physical_identity": per_subject,
            "evidence_ids": {"v1a": v1a_authority.get("evidence_ids"), "v1b": v1b_authority.get("evidence_ids")},
            "measured_economics": {
                "v1a_qualification_wall_seconds": v1a_frozen.get("v1a_qualification_wall_seconds"),
                "v1b_qualification_wall_seconds": qualification.get("attempt", {}).get("wall_seconds")},
            "subject_local_reference": {
                "v1a": v1a_frozen["reference_output"], "v1b": v1b_frozen["reference_output"],
                "note": "each reference was frozen prospectively from accepted pre-campaign subject evidence"},
            "planner_dispositions": candidate_set.get("explanations"),
        },
        "classifications": classifications,
        "foundational_invariant_falsified": False,
        "generic_seam_change_required": accounting_requires_change,
        "audit_conclusion": "only authority/adapter data varies between subjects in the retained campaigns, EXCEPT "
                            "the accepted V0-C accounting reducer, whose first-subject selector label must be "
                            "parameterized (a correctness-bearing change to a hash-pinned accepted source) before "
                            "the second subject's canonical accounting can be reduced",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--authority", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--mode", choices=("stability", "canonical-run", "reduce-canonical", "audit"), required=True)
    parser.add_argument("--plan")
    parser.add_argument("--raw")
    parser.add_argument("--runner-exit", type=int)
    parser.add_argument("--v1a-authority")
    parser.add_argument("--qualification")
    parser.add_argument("--candidate-set")
    parser.add_argument("--canonical-attempt")
    args = parser.parse_args(argv)
    authority = json.loads(Path(args.authority).read_text(encoding="utf-8"))
    out = Path(args.out)

    if args.mode == "stability":
        contract = authority["stability_contract"]
        digests = run_stability_sample(authority, out)
        for index, record_digest in enumerate(digests, start=1):
            print(f"{contract['evidence_id_prefix']}-stability-{index:02d} {record_digest}")
        return 0

    if args.mode == "canonical-run":
        exit_code = invoke_accepted_canonical_runner(Path(args.authority), Path(args.plan), out)
        print(f"accepted-runner-exit {exit_code}")
        return 0

    if args.mode == "reduce-canonical":
        plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
        record = reduce_canonical_attempt(authority, plan, Path(args.raw), args.runner_exit)
        out.write_bytes(canonical_json(record) + b"\n")
        print(record["result"], record.get("accounting_classification", "ACCOUNTING_CLEAN"))
        return 0

    # audit
    v1a_authority = json.loads(Path(args.v1a_authority).read_text(encoding="utf-8"))
    qualification = json.loads(Path(args.qualification).read_text(encoding="utf-8"))
    candidate_set = json.loads(Path(args.candidate_set).read_text(encoding="utf-8"))
    canonical_attempt = json.loads(Path(args.canonical_attempt).read_text(encoding="utf-8"))
    audit = build_cross_subject_audit(v1a_authority, authority, qualification, candidate_set, canonical_attempt)
    out.write_bytes(canonical_json(audit) + b"\n")
    print("GENERIC_SEAM_CHANGE_REQUIRED" if audit["generic_seam_change_required"] else "AUTHORITY_DATA_ONLY")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
