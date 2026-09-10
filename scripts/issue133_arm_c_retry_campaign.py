#!/usr/bin/env python3
"""Issue #133 — physical Arm-C retry campaign core (coordination side).

This module is the CPU-only campaign support core for the physical Arm-C
retry authorized by issue #133. It contains NO model execution and NO
GPU access. It reuses, verbatim, the attempt/STOP state machine and the
accepted physical-campaign authority loader frozen by issue #129
(`scripts/issue129_arm_c_retry_core.py`); it never re-implements them.

Scope of this module:

1.  Bind and validate the fresh campaign authority document
    (`evidence/arm-c-retry/physical-campaign-authority.json`) against the
    #129-frozen strict schema (`_parse_accepted_campaign_authority_document`)
    and against the exact identities named by issue #133 (methodology head,
    accepted merge, model/checkpoint/producer/candidate/geometry/fixture,
    accepted Arm-B plan and participant identities).

2.  Define the retry's corrected invocation contract as data: the per-call
    `generate()` keyword set, `max_new_tokens=2` replay-prefill semantics,
    commit-step-zero/discard-step-one, and the runtime-session allocation
    identity extracted from the pinned r5b_epochs.py bytes (reused from
    the #129 core's own extractor — never re-derived here).

3.  Provide deployment-identity verification for the correctness-bearing
    retry drivers reusing the #129 contract (`verify_deployment_identity`).

4.  Emit canonical attempt facts for the campaign lineage, so every
    physical attempt (including pre-observation infrastructure failures)
    is reducible by the #129 public reducer against the accepted
    authority document in canonical Git history.

The authority document binds `execution_freeze_identity` = the sha256 of
the canonical execution-freeze record that pins every correctness-bearing
driver byte before the first launch. That record is authored in this
repository by the campaign, committed, and its sha256 written into the
authority document BEFORE the authority review/merge. A changed driver
byte after freeze invalidates the deployment identity of any attempt that
emitted correctness-bearing results (permanent campaign STOP under the
#129 state machine).

No GPU execution, no model execution, no tokenizer work, and no accepted
Arm-B participant-state mutation happens in this module.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import issue129_arm_c_retry_core as _frozen  # noqa: E402

AREA = ROOT / "docs/implementation/r6-successor-dense-full-integration-117"
RETRY_EVIDENCE = AREA / "evidence" / "arm-c-retry"
AUTHORITY_PATH = RETRY_EVIDENCE / "physical-campaign-authority.json"
EXECUTION_FREEZE_RECORD = RETRY_EVIDENCE / "execution-freeze.json"

#: exact identities named by issue #133 (authoritative; never edited here)
ISSUE133 = {
    "methodology_ready_head": "808b77c45f0b4e5d52a202c1a931f43447ff93a6",
    "accepted_main_merge": "781d6b688b29c149837f2ad217b4455dea269eeb",
    "methodology_terminal": "ISSUE117_ARM_C_RETRY_METHODOLOGY_READY",
    "physical_scope": "ISSUE117_ARM_C_RETRY",
    "issue_reference": "https://github.com/Zutfen-LLC/inferswarm/issues/133",
    "frozen_producer": "924cd22ea081f6d4ed471016faf01d427fc5b0d2",
    "model": "google/gemma-4-12B-it",
    "revision": "707f0a3b8a3c7ad586ed01e27eafbad8a27dd0f7",
    "checkpoint_sha256": ("5a84cb313260ac447237b890387116dfa8682e49"
                          "a6b44bc585ae8353abbff18d"),
    "qualification_subject": ("sha256:c6b9fe721103fb041be3a5b980e73ee"
                              "148f2304c8572bc50e971f7f1d7994ffd"),
    "candidate": "dense.6171f32b4413",
    "geometry": (
        "inferswarm01/gpu-0 [0,16)\ninferswarm01/gpu-1 [16,32)\n"
        "inferswarm03/gpu-0 [32,48)"),
    "execution_plan_digest": ("sha256:8646e00ce53e3aac4c163ca35231fa8"
                              "2471815386d71266a0d0962eea565bdad"),
    "participant_identity": ("sha256:ee845188d3328bdec29bf4b09d71f7ccda0"
                             "701ff5758cb1d8a70460a40fecfb1"),
    "fixture_digest": ("sha256:180185cd5c6a5dcd77b2c65979bd2c9aef4d1c7"
                       "ea9fb4850a64f4508b2ba36f2"),
    "case_count": 24,
    "coordinator_host": "inferswarm00",
    "participant_hosts": ("inferswarm01", "inferswarm03"),
}

#: the corrected comparator contract, as data (issue #133 mandatory section)
COMPARATOR_CONTRACT = {
    "replay_input": "frozen rendered prompt ids + already committed generated ids",
    "runtime_session_allocation": (
        "the exact frozen controller allocation derived and proven by "
        "issue #129 (verbatim AST extraction from the pinned r5b_epochs.py; "
        "multiplier 1000000; global call sequence from zero)"),
    "max_new_tokens": 2,
    "commit": "generated step zero only",
    "speculative": "step one discarded before replay",
    "single_shot_forbidden": "single-shot max_new_tokens=8 is forbidden",
    "generate_argument_names": tuple(
        _frozen.GENERATE_ARGUMENT_NAMES),
    "stopping": (
        "repeat until the frozen stopping condition is met (8 committed "
        "tokens per case unless the frozen stopping contract mechanically "
        "terminates earlier)"),
}

#: frozen tokenizer asset pins, loaded verbatim from the accepted #129
#: integrity record (never hand-copied)
_INTEGRITY = json.loads(
    (ROOT / "docs/implementation/r6-successor-dense-full-integration-117"
     / "evidence/arm-c-retry/integrity.json").read_text())
TOKENIZER_ASSET_PINS = dict(_INTEGRITY["tokenizer_asset_pins"])
TOKENIZER_SOFTWARE_IDENTITY = dict(_frozen.REQUIRED_TOKENIZER_SOFTWARE)
TOKENIZER_PYTHON = _frozen.TOKENIZER_PYTHON


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_canonical_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def load_authority_document(repo_root: Path | None = None) -> dict[str, Any]:
    """Load and strictly validate the physical-campaign authority document
    through the #129-frozen parser (fail-closed on any schema drift)."""
    root = repo_root or ROOT
    raw = (root / "docs/implementation/r6-successor-dense-full-integration-117"
           / "evidence/arm-c-retry/physical-campaign-authority.json"
           ).read_bytes()
    document = json.loads(raw)
    _frozen._parse_accepted_campaign_authority_document(document)
    return document


def validate_authority_bindings(document: Mapping[str, Any]) -> dict[str, Any]:
    """Cross-bind the authority document against the exact identities
    issue #133 names. Any drift fails closed."""
    problems: list[str] = []
    acceptance = document["acceptance"]
    if acceptance["methodology_terminal"] != ISSUE133["methodology_terminal"]:
        problems.append("methodology terminal drift")
    reference = acceptance["methodology_acceptance_reference"]
    if not reference.endswith("/pull/132"):
        problems.append(
            "methodology acceptance reference is not accepted PR #132")
    execution = document["execution_authorization"]
    if execution["scope"] != ISSUE133["physical_scope"]:
        problems.append("physical scope drift")
    if execution["authorization_reference"] != ISSUE133["issue_reference"]:
        problems.append(
            "physical authorization reference is not issue #133")
    campaigns = document["campaigns"]
    if len(campaigns) != 1:
        problems.append(
            "the retry authorization covers exactly one fresh campaign")
    for campaign_id, record in campaigns.items():
        if record["methodology_ready_identity"] != \
                ISSUE133["methodology_ready_head"]:
            problems.append(
                f"campaign {campaign_id} methodology head drift")
        if not _frozen._is_sha256(record["execution_freeze_identity"]):
            problems.append(
                f"campaign {campaign_id} execution freeze identity is not "
                "a sha256")
        if record["execution_freeze_identity"] == "0" * 64:
            problems.append(
                f"campaign {campaign_id} execution freeze identity is the "
                "unbound placeholder")
    return {
        "schema": "inferswarm.issue133.authority-binding/1",
        "campaign_ids": sorted(campaigns),
        "problems": problems,
        "bound": not problems,
    }


def build_execution_freeze_record(
        drivers: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """Build the canonical execution-freeze record binding every
    correctness-bearing driver byte (repository SHA + file sha256 +
    expected absolute deployed path + read-only deployment), plus the
    issue-133 identity block. The record's own sha256 (canonical JSON)
    becomes the campaign's `execution_freeze_identity`."""
    for name, driver in drivers.items():
        verdict = _frozen.verify_deployment_identity(driver)
        if not verdict["ok"]:
            raise ValueError(
                f"driver {name} fails the deployment-identity contract: "
                f"{verdict['reason']}")
    record = {
        "schema": "inferswarm.issue133.execution-freeze/1",
        "issue": ISSUE133["issue_reference"],
        "physical_scope": ISSUE133["physical_scope"],
        "methodology_ready_head": ISSUE133["methodology_ready_head"],
        "accepted_main_merge": ISSUE133["accepted_main_merge"],
        "frozen_producer": ISSUE133["frozen_producer"],
        "model": ISSUE133["model"],
        "revision": ISSUE133["revision"],
        "checkpoint_sha256": ISSUE133["checkpoint_sha256"],
        "qualification_subject": ISSUE133["qualification_subject"],
        "candidate": ISSUE133["candidate"],
        "geometry": ISSUE133["geometry"],
        "execution_plan_digest": ISSUE133["execution_plan_digest"],
        "participant_identity": ISSUE133["participant_identity"],
        "fixture_digest": ISSUE133["fixture_digest"],
        "case_count": ISSUE133["case_count"],
        "comparator_contract": dict(COMPARATOR_CONTRACT),
        "tokenizer_asset_pins": dict(TOKENIZER_ASSET_PINS),
        "tokenizer_software_identity": dict(TOKENIZER_SOFTWARE_IDENTITY),
        "tokenizer_python": TOKENIZER_PYTHON,
        "drivers": {name: dict(driver) for name, driver in drivers.items()},
    }
    return record


def execution_freeze_identity(record: Mapping[str, Any]) -> str:
    """Canonical-JSON sha256 of the execution-freeze record — the value
    bound into the authority document's campaign record."""
    return sha256_bytes(
        (json.dumps(record, indent=2, sort_keys=True) + "\n").encode())


def emit_attempt_facts(
        *, campaign_id: str, attempt_id: str, observed_at: str,
        authority: Mapping[str, Any],
        gpu_execution_occurred: bool,
        model_execution_occurred: bool,
        correctness_bearing_result_emitted: bool,
        result_reached_coordinator: bool,
        coordinator_commit_occurred: bool,
        frozen_identity_verified_pre_launch: bool,
        frozen_identity_verified_post_run: bool,
        methodology_gate_passed: bool = True,
        terminal_observation: bool = False,
        diagnostic_only_disclosure: bool = False) -> dict[str, Any]:
    """Emit one attempt's facts bound to the accepted authority record."""
    record = authority["campaigns"][campaign_id]
    facts = {
        "campaign_id": campaign_id,
        "physical_authorization_id": record["physical_authorization_id"],
        "methodology_ready_identity": record["methodology_ready_identity"],
        "execution_freeze_identity": record["execution_freeze_identity"],
        "attempt_id": attempt_id,
        "observed_at": observed_at,
        "campaign_lineage_root": record["campaign_lineage_root"],
        "physical_authorization_issued_at": record[
            "physical_authorization_issued_at"],
        "prior_stopped_campaign_id": record.get("prior_stopped_campaign_id"),
        "prior_stop_attempt_id": record.get("prior_stop_attempt_id"),
        "prior_stop_review_id": record.get("prior_stop_review_id"),
        "prior_stop_reviewed_at": record.get("prior_stop_reviewed_at"),
        "gpu_execution_occurred": gpu_execution_occurred,
        "model_execution_occurred": model_execution_occurred,
        "correctness_bearing_result_emitted": correctness_bearing_result_emitted,
        "result_reached_coordinator": result_reached_coordinator,
        "coordinator_commit_occurred": coordinator_commit_occurred,
        "frozen_identity_verified_pre_launch": frozen_identity_verified_pre_launch,
        "frozen_identity_verified_post_run": frozen_identity_verified_post_run,
        "methodology_gate_passed": methodology_gate_passed,
        "physical_retry_authorized": True,
        "terminal_observation": terminal_observation,
        "diagnostic_only_disclosure": diagnostic_only_disclosure,
        "stop_occurred": False,
    }
    # fail-closed: the emitted facts must be classifiable RIGHT NOW
    _frozen.classify_attempt(facts)
    return facts


def reduce_campaign_attempts(
        attempts: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Reduce the campaign's attempts against this repository's accepted
    Git history via the #129 public reducer (authority loaded from the
    fixed path at the accepted authority commit)."""
    commit = accepted_authority_commit()
    return _frozen.reduce_attempts(attempts, accepted_authority_commit=commit)


def accepted_authority_commit() -> str:
    """The commit of this repository's main history that first carries the
    authority document; fails closed if the working tree's authority bytes
    are not yet in accepted history (pre-review state)."""
    raw_path = Path(
        "docs/implementation/r6-successor-dense-full-integration-117/"
        "evidence/arm-c-retry/physical-campaign-authority.json")
    target = sha256_file(ROOT / raw_path)
    completed = subprocess.run(
        ["git", "log", "--format=%H", "--reverse",
         "--", str(raw_path)],
        cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, check=False)
    if completed.returncode != 0:
        raise RuntimeError("authority history lookup failed")
    for commit in completed.stdout.split():
        blob = subprocess.run(
            ["git", "show", f"{commit}:{raw_path}"],
            cwd=ROOT, stdout=subprocess.PIPE, text=True, check=False)
        if blob.returncode == 0 and sha256_bytes(blob.stdout.encode()) == target:
            return commit
    raise RuntimeError(
        "the authority document in the working tree is not yet committed "
        "to accepted history; it must be reviewed and merged before any "
        "correctness-bearing physical attempt")


def main(argv: list[str] | None = None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--validate-authority", action="store_true",
        help="validate the authority document against issue #133 bindings")
    args = parser.parse_args(argv)
    if args.validate_authority:
        document = load_authority_document()
        verdict = validate_authority_bindings(document)
        print(json.dumps(verdict, indent=2, sort_keys=True))
        return 0 if verdict["bound"] else 1
    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
