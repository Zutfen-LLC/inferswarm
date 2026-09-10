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

2.  PRE-EXECUTION ACCEPTED-HISTORY GATE (`accepted_authority_commit` /
    `verify_pre_execution_authority_gate`): the selected authority commit
    must be an ANCESTOR of `refs/remotes/origin/main`, verified
    fail-closed exactly like the frozen #129 reducer
    (`_reduce_attempts_from_accepted_git`). A branch-only authority commit,
    a missing remote ref, a malformed/nonexistent commit, or matching
    bytes at an unaccepted commit are all rejected BEFORE any physical
    launch. This is deliberately independent of the #129 terminal
    reducer: the reducer rejects at reduction time, which is too late to
    prevent a physical launch.

3.  MECHANICAL FREEZE BINDING (`verify_execution_freeze_binding`): the
    retained `execution-freeze.json` bytes are loaded, canonical
    encoding/schema-verified, SHA-256'd, and compared EXACTLY with the
    sole authorized campaign's `execution_freeze_identity`. An authored
    digest field inside the freeze is never trusted as proof of its own
    identity; any mismatch rejects before physical execution.

4.  Define the retry's corrected invocation contract as data: the per-call
    `generate()` keyword set, `max_new_tokens=2` replay-prefill semantics,
    commit-step-zero/discard-step-one, and the runtime-session allocation
    identity extracted from the pinned r5b_epochs.py bytes (reused from
    the #129 core's own extractor — never re-derived here).

5.  STATIC pre-execution freeze/deployment EXPECTATIONS
    (`build_execution_freeze_record`): the pre-execution freeze records
    the frozen repository/file identities, expected absolute path,
    read-only requirement, and the REQUIREMENTS that pre-launch and
    post-run deployment verification occur. It never claims that post-run
    verification has already succeeded — `post_run_verified` /
    `post_run_file_sha256` are OBSERVATIONAL evidence produced around a
    physical attempt and evaluated with the frozen #129
    `verify_deployment_identity()` semantics AFTER execution, never
    pre-authored into a pre-run record.

6.  Emit canonical attempt facts for the campaign lineage, so every
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
    "generate_argument_names": tuple(_frozen.GENERATE_ARGUMENT_NAMES),
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

#: static pre-execution freeze schema: fields a pre-run record may carry.
#: Deliberately EXCLUDES any post-run observational claim —
#: `post_run_verified` / `post_run_file_sha256` cannot exist before a
#: physical attempt and their presence in a pre-execution freeze fails
#: closed (a pre-run record may not masquerade as completed post-run
#: verification).
FREEZE_SCHEMA = "inferswarm.issue133.execution-freeze/3"
FREEZE_DRIVER_STATIC_FIELDS = (
    "repository_sha",
    "file_sha256",
    "expected_path",
    "read_only",
)
OBSERVATIONAL_DEPLOYMENT_FIELDS = frozenset({
    "pre_launch_verified", "post_run_verified", "post_run_file_sha256",
})
AUTHORIZED_REALIZATION_INPUTS = {
    "environment": {
        "canonical_sha256": (
            "182b950e844c078fd0a9d91c321cd67097c81d3d4fd704a86618407b6399b274"),
        "expected_path": "/srv/inferswarm/state/arm-c/environment.json",
        "source_evidence": (
            "docs/implementation/r6-successor-dense-full-integration-117/"
            "evidence/physical-preflight.json"),
        "derivation_authority": (
            "scripts/issue129_arm_c_retry_core.py:_frozen_environment at "
            "methodology head 808b77c45f0b4e5d52a202c1a931f43447ff93a6"),
    },
    "chain_plan": {
        "digest": (
            "sha256:a71a3129b8764d7108f51ed30fb230b42fcd69646a20bcd6806b6ee53b9bc51f"),
        "file_sha256": (
            "6d9a4859af5b686a321458fe50c86189244b7d0d41e2cbb0df28147552f709ab"),
        "expected_path": "/srv/inferswarm/state/arm-c/chain-plan.json",
        "source_evidence": (
            "docs/implementation/r6-successor-dense-full-integration-117/"
            "evidence/arm-c/chain-plan.json"),
    },
    "model_view_path": {
        "value": "/srv/inferswarm/state/arm-c/model-view",
        "source_evidence": (
            "docs/implementation/r6-successor-dense-full-integration-117/"
            "evidence/arm-c/chain-plan.json:model_path"),
    },
    "last_stage_host": {
        "value": "10.0.0.219",
        "source_evidence": (
            "docs/implementation/r6-successor-dense-full-integration-117/"
            "evidence/arm-a/run-device-bindings.json"),
    },
    "last_stage_port": {
        "value": 18485,
        "source_evidence": (
            "docs/implementation/r6-successor-dense-full-integration-117/"
            "evidence/arm-a/run-device-bindings.json"),
    },
    "prompt_fixture": {
        "file_sha256": (
            "e68dfaafe661f2f6cc5f5be3a51128c7e7abf0b5c81978cbdb45e9788fd88cd0"),
        "expected_path": (
            "/srv/inferswarm/state/arm-c-retry/prompt-fixture.json"),
        "source_evidence": (
            "docs/implementation/r6-successor-dense-full-integration-117/"
            "evidence/arm-c-retry/prompt-fixture.json"),
    },
    "integration_fixture": {
        "file_sha256": (
            "b9c2bb7f7416b10dcee284aaf9b6c591644292550e1dced70a315c08eba120a3"),
        "expected_path": (
            "/srv/inferswarm/state/arm-c-retry/integration-fixture.json"),
        "source_evidence": (
            "docs/implementation/r6-successor-dense-full-integration-117/"
            "evidence/integration-fixture.json"),
    },
    "tokenizer_path": {
        "value": "/srv/inferswarm/tokenizers/gemma-r6-frozen",
        "source_evidence": (
            "docs/implementation/r6-successor-dense-full-integration-117/"
            "evidence/arm-c-retry/methodology-run.json:tokenizer_source_contract"),
    },
}
FREEZE_TOP_FIELDS = frozenset({
    "schema", "issue", "physical_scope", "methodology_ready_head",
    "accepted_main_merge", "frozen_producer", "model", "revision",
    "checkpoint_sha256", "qualification_subject", "candidate", "geometry",
    "execution_plan_digest", "participant_identity", "fixture_digest",
    "case_count", "comparator_contract", "tokenizer_asset_pins",
    "tokenizer_software_identity", "tokenizer_python", "drivers",
    "dependencies", "authorized_realization_inputs",
    "deployment_verification_requirements",
})


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


# ---------------------------------------------------------------------------
# 1. PRE-EXECUTION ACCEPTED-HISTORY GATE (fail-closed, #129-equivalent)
# ---------------------------------------------------------------------------

ACCEPTED_REMOTE_REF = "refs/remotes/origin/main"


def _gate_git(repo_root: Path, *args: str,
              check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo_root), *args], stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True, check=check)


def find_authority_commits(repo_root: Path | None = None,
                           repo_path: Path | None = None) -> list[str]:
    """Commits (oldest first) whose blob at the fixed authority path
    equals the repo-root working-tree authority bytes.

    ``repo_path`` overrides the Git repository the history scan runs in
    (deterministic test fixtures); the authority BYTES always come from
    ``repo_root`` (default: this repository's retained evidence path).
    """
    bytes_root = Path(repo_root) if repo_root else ROOT
    git_root = Path(repo_path) if repo_path else bytes_root
    raw_path = Path(
        "docs/implementation/r6-successor-dense-full-integration-117/"
        "evidence/arm-c-retry/physical-campaign-authority.json")
    target = sha256_file(bytes_root / raw_path)
    completed = _gate_git(
        git_root, "log", "--all", "--format=%H", "--reverse", "--",
        str(raw_path), check=False)
    if completed.returncode != 0:
        stderr = completed.stderr or ""
        if "does not have any commits yet" in stderr:
            # an empty repository legitimately carries no authority
            # history: there is nothing to accept
            return []
        raise RuntimeError("authority history lookup failed")
    matches: list[str] = []
    for commit in completed.stdout.split():
        blob = _gate_git(
            git_root, "show", f"{commit}:{raw_path}", check=False)
        if blob.returncode == 0 and \
                sha256_bytes(blob.stdout.encode()) == target:
            matches.append(commit)
    return matches


def accepted_authority_commit(repo_root: Path | None = None,
                              repo_path: Path | None = None) -> str:
    """The commit carrying the authority bytes that is an ANCESTOR of
    ``refs/remotes/origin/main`` (accepted history).

    Fail-closed semantics (equivalent to the frozen #129 reducer's
    authority lookup):
    - no commit carrying matching authority bytes at all => rejected;
    - matching bytes exist ONLY on a working/PR branch (not an ancestor
      of ``origin/main``) => REJECTED — presence of matching bytes on an
      unaccepted branch is never acceptance;
    - the remote ref ``refs/remotes/origin/main`` is missing => fail
      closed;
    - a candidate commit is malformed or does not exist as a commit
      object => fail closed;
    - the first candidate that is an accepted ancestor is returned.
    """
    bytes_root = Path(repo_root) if repo_root else ROOT
    git_root = Path(repo_path) if repo_path else bytes_root
    candidates = find_authority_commits(bytes_root, git_root)
    if not candidates:
        raise RuntimeError(
            "accepted-history pre-execution gate: no commit carries the "
            "authority document bytes; the authority document must be "
            "reviewed and merged into accepted InferSwarm history "
            "before any correctness-bearing physical attempt")
    # the accepted remote ref must EXIST (a missing ref fails closed —
    # ancestry is undecidable, never assumed)
    ref_check = _gate_git(
        git_root, "rev-parse", "--verify", "--quiet",
        ACCEPTED_REMOTE_REF, check=False)
    if ref_check.returncode != 0 or not ref_check.stdout.strip():
        raise RuntimeError(
            "accepted-history pre-execution gate: "
            f"{ACCEPTED_REMOTE_REF} is missing; accepted ancestry cannot "
            "be verified, failing closed before any physical launch")
    for commit in candidates:
        if not _frozen._is_git_sha(commit):
            raise RuntimeError(
                "accepted-history pre-execution gate: malformed candidate "
                f"commit {commit!r}; failing closed")
        exists = _gate_git(
            git_root, "cat-file", "-e", f"{commit}^{{commit}}", check=False)
        if exists.returncode != 0:
            raise RuntimeError(
                "accepted-history pre-execution gate: candidate commit "
                f"{commit} does not exist as a commit object; failing "
                "closed")
        ancestry = _gate_git(
            git_root, "merge-base", "--is-ancestor", commit,
            ACCEPTED_REMOTE_REF, check=False)
        if ancestry.returncode == 0:
            return commit
    raise RuntimeError(
        "accepted-history pre-execution gate: the authority document "
        "bytes exist only at commit(s) not accepted into "
        f"{ACCEPTED_REMOTE_REF}; a branch-only authority commit is not "
        "accepted history — the PR must be reviewed and merged before "
        "any correctness-bearing physical attempt")


def verify_pre_execution_authority_gate(
        repo_root: Path | None = None,
        repo_path: Path | None = None) -> dict[str, Any]:
    """Full pre-execution gate verdict for Phase B to invoke MECHANICALLY
    before any physical launch:

    - authority document loads + passes the #129-frozen strict schema;
    - the authority document is bound to the exact issue #133 identities;
    - the selected authority commit is an ancestor of
      ``refs/remotes/origin/main`` (accepted history);
    - the retained execution-freeze bytes hash EXACTLY to the sole
      authorized campaign's ``execution_freeze_identity``.

    Any failure raises (fail closed). A passing verdict is a precondition,
    never physical-execution authority by itself.
    """
    root = Path(repo_root) if repo_root else ROOT
    git_root = Path(repo_path) if repo_path else root
    document = load_authority_document(root)
    binding = validate_authority_bindings(document)
    if not binding["bound"]:
        raise RuntimeError(
            "pre-execution gate: authority bindings failed: "
            + "; ".join(binding["problems"]))
    commit = accepted_authority_commit(root, git_root)
    freeze = verify_execution_freeze_binding(document, root)
    return {
        "schema": "inferswarm.issue133.pre-execution-gate/1",
        "gate": "ACCEPTED_HISTORY_AND_FREEZE_BOUND",
        "accepted_authority_commit": commit,
        "accepted_ref": ACCEPTED_REMOTE_REF,
        "campaign_ids": binding["campaign_ids"],
        "execution_freeze_binding": freeze,
    }


# ---------------------------------------------------------------------------
# 2. MECHANICAL FREEZE BINDING (retained bytes == authorized identity)
# ---------------------------------------------------------------------------

def load_execution_freeze_record(
        repo_root: Path | None = None) -> tuple[dict[str, Any], bytes]:
    """Load the retained execution-freeze record; fail closed unless it
    is valid JSON in EXACT canonical form (indent=2, sort_keys, trailing
    newline — the representation the freeze identity is defined over)."""
    root = Path(repo_root) if repo_root else ROOT
    raw = (root / "docs/implementation/r6-successor-dense-full-integration-117"
           / "evidence/arm-c-retry/execution-freeze.json").read_bytes()
    try:
        document = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RuntimeError(
            "execution-freeze record is not valid JSON") from error
    canonical = (json.dumps(document, indent=2, sort_keys=True)
                 + "\n").encode()
    if raw != canonical:
        raise RuntimeError(
            "execution-freeze record is not canonical JSON "
            "(indent=2, sort_keys=True, trailing newline); the retained "
            "bytes cannot be bound to a canonical freeze identity")
    return document, raw


def verify_freeze_static_shape(record: Mapping[str, Any]) -> None:
    """Verify the STATIC pre-execution freeze shape: exact top-level field
    set, exact schema id, and — critically — NO post-run observational
    claim. A pre-run record carrying `post_run_verified` or a
    `post_run_file_sha256` (or a driver entry carrying them) fails
    closed: those facts cannot exist before a physical attempt."""
    if not isinstance(record, Mapping):
        raise RuntimeError("execution-freeze record is not an object")
    def observational_fields(value: Any) -> set[str]:
        if isinstance(value, Mapping):
            found = set(value).intersection(OBSERVATIONAL_DEPLOYMENT_FIELDS)
            for nested in value.values():
                found.update(observational_fields(nested))
            return found
        if isinstance(value, (list, tuple)):
            found: set[str] = set()
            for nested in value:
                found.update(observational_fields(nested))
            return found
        return set()

    observed = sorted(observational_fields(record))
    if observed:
        raise RuntimeError(
            "static pre-execution freeze carries observational deployment "
            f"fields {observed}; these facts can exist only in per-attempt "
            "evidence")
    if record.get("schema") != FREEZE_SCHEMA:
        raise RuntimeError(
            f"execution-freeze schema drift: expected {FREEZE_SCHEMA}, "
            f"got {record.get('schema')!r}")
    if set(record) != set(FREEZE_TOP_FIELDS):
        missing = sorted(set(FREEZE_TOP_FIELDS) - set(record))
        extra = sorted(set(record) - set(FREEZE_TOP_FIELDS))
        raise RuntimeError(
            "execution-freeze record has non-exhaustive fields "
            f"(missing={missing}, extra={extra})")
    requirements = record["deployment_verification_requirements"]
    if not isinstance(requirements, Mapping) or \
            not requirements.get("pre_launch_verification_required") or \
            not requirements.get("post_run_verification_required"):
        raise RuntimeError(
            "execution-freeze record must REQUIRE pre-launch and post-run "
            "deployment verification")
    for category in ("drivers", "dependencies"):
        entries = record[category]
        if not isinstance(entries, Mapping) or not entries:
            raise RuntimeError(
                f"execution-freeze record carries no {category}")
        for name, entry in entries.items():
            if not isinstance(entry, Mapping):
                raise RuntimeError(
                    f"{category} entry {name} is not an object")
            verdict = verify_static_deployment_identity(entry)
            if not verdict["ok"]:
                raise RuntimeError(
                    f"{category} entry {name} fails the static identity "
                    f"contract: {verdict['reason']}")


def verify_execution_freeze_binding(
        document: Mapping[str, Any] | None = None,
        repo_root: Path | None = None) -> dict[str, Any]:
    """Mechanically bind the retained execution-freeze BYTES to the sole
    authorized campaign's `execution_freeze_identity`:

    1. load the exact retained `execution-freeze.json`;
    2. verify canonical encoding (fail-closed) and the static
       pre-execution shape (schema; no post-run claims);
    3. compute SHA-256 over the retained bytes (the canonical
       representation the contract defines the identity over);
    4. compare EXACTLY with the sole authorized campaign's
       `execution_freeze_identity`;
    5. reject any mismatch (or malformed/zero identity) before physical
       execution.

    An authored digest field inside the freeze document is never
    consulted as proof of its own identity.
    """
    root = Path(repo_root) if repo_root else ROOT
    if document is None:
        document = load_authority_document(root)
    campaigns = document["campaigns"]
    if len(campaigns) != 1:
        raise RuntimeError(
            "freeze binding requires exactly one authorized campaign "
            f"(got {sorted(campaigns)})")
    campaign_id = next(iter(campaigns))
    authorized = campaigns[campaign_id]["execution_freeze_identity"]
    if not _frozen._is_sha256(authorized) or authorized == "0" * 64:
        raise RuntimeError(
            f"campaign {campaign_id} carries a malformed or unbound "
            "execution_freeze_identity; failing closed")
    record, raw = load_execution_freeze_record(root)
    verify_freeze_static_shape(record)
    actual = sha256_bytes(raw)
    if actual != authorized:
        raise RuntimeError(
            f"execution-freeze binding mismatch for campaign {campaign_id}: "
            f"retained bytes sha256 {actual} != authorized "
            f"execution_freeze_identity {authorized}; physical execution "
            "is rejected before launch")
    return {
        "campaign_id": campaign_id,
        "authorized_execution_freeze_identity": authorized,
        "retained_bytes_sha256": actual,
        "bound": True,
    }


# ---------------------------------------------------------------------------
# 3. STATIC pre-execution freeze construction (no post-run claims)
# ---------------------------------------------------------------------------

def build_execution_freeze_record(
        drivers: Mapping[str, Mapping[str, Any]],
        dependencies: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """Build the canonical STATIC execution-freeze record binding every
    correctness-bearing driver's frozen identity (repository SHA + file
    sha256 + expected absolute deployed path + read-only requirement), plus
    the issue-133 identity block and the REQUIREMENT that pre-launch and
    post-run deployment verification occur. The record's own sha256 becomes
    the campaign's `execution_freeze_identity`.

    Deliberately does NOT contain `post_run_verified` or
    `post_run_file_sha256`: no physical execution has occurred, so those
    observational facts cannot exist yet. After an actual attempt,
    Phase B/C evidence separately retains the truthful pre/post
    verification observations and is evaluated with the frozen #129
    `verify_deployment_identity()` semantics. Static drivers here pass
    the STATIC subset of that contract only.
    """
    for category, entries in (("driver", drivers),
                              ("dependency", dependencies)):
        if not entries:
            raise ValueError(f"execution freeze has no {category} entries")
        for name, entry in entries.items():
            verdict = verify_static_deployment_identity(entry)
            if not verdict["ok"]:
                raise ValueError(
                    f"{category} {name} fails the static deployment-identity "
                    f"contract: {verdict['reason']}")
    record = {
        "schema": FREEZE_SCHEMA,
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
        "authorized_realization_inputs": dict(AUTHORIZED_REALIZATION_INPUTS),
        "deployment_verification_requirements": {
            "pre_launch_verification_required": True,
            "post_run_verification_required": True,
            "semantics": (
                "pre_launch_verified / post_run_verified / "
                "post_run_file_sha256 are OBSERVATIONAL evidence produced "
                "around a physical attempt and evaluated with the frozen "
                "issue-#129 verify_deployment_identity() semantics after "
                "execution; this static pre-execution freeze only pins "
                "expected identities and may never claim a future "
                "post-run observation as an accomplished fact"),
        },
        "drivers": {name: dict(driver) for name, driver in drivers.items()},
        "dependencies": {
            name: dict(dependency)
            for name, dependency in dependencies.items()
        },
    }
    return record


def verify_static_deployment_identity(
        record: Mapping[str, Any]) -> dict[str, Any]:
    """The STATIC subset of the frozen #129 deployment-identity contract
    (everything provable before any physical attempt). The full frozen
    contract — including `post_run_verified` and byte-level post-run
    equality — is applied by Phase B/C to actual observations after an
    attempt, through `_frozen.verify_deployment_identity` verbatim."""
    missing = sorted(set(FREEZE_DRIVER_STATIC_FIELDS) - set(record))
    extra = sorted(set(record) - set(FREEZE_DRIVER_STATIC_FIELDS))
    if missing or extra:
        return {"ok": False,
                "reason": f"field mismatch missing={missing}, extra={extra}"}

    def _hex(value, length):
        return (isinstance(value, str) and len(value) == length
                and all(c in "0123456789abcdef" for c in value))

    if not _hex(record["repository_sha"], 40):
        return {"ok": False, "reason": "repository_sha is not a commit sha1"}
    if not _hex(record["file_sha256"], 64):
        return {"ok": False, "reason": "file_sha256 is not a sha256"}
    if not isinstance(record["expected_path"], str) or not record[
            "expected_path"].startswith("/"):
        return {"ok": False, "reason": "expected_path is not absolute"}
    if record["read_only"] is not True:
        return {"ok": False, "reason": "deployment is mutable (not read-only)"}
    return {"ok": True}


def execution_freeze_identity(record: Mapping[str, Any]) -> str:
    """Canonical-JSON sha256 of the execution-freeze record — the value
    bound into the authority document's campaign record."""
    return sha256_bytes(
        (json.dumps(record, indent=2, sort_keys=True) + "\n").encode())


def verify_campaign_retention_legality(
        repo_root: Path | None = None) -> dict[str, Any]:
    """Prove that the fresh campaign has no attempt, terminal, or STOP.

    The proof scans the complete retry evidence area. It does not trust the
    authored zero counters in ``phase-a-correction.json``.
    """
    root = Path(repo_root) if repo_root else ROOT
    area = (root / "docs/implementation/r6-successor-dense-full-integration-117"
            / "evidence/arm-c-retry")
    authority = load_authority_document(root)
    campaigns = authority["campaigns"]
    if len(campaigns) != 1:
        raise RuntimeError("campaign-retention proof requires one campaign")
    campaign_id = next(iter(campaigns))
    campaign = campaigns[campaign_id]
    prior_stop_fields = (
        "prior_stopped_campaign_id", "prior_stop_attempt_id",
        "prior_stop_review_id", "prior_stop_reviewed_at",
    )
    if any(campaign.get(field) is not None for field in prior_stop_fields):
        raise RuntimeError(
            "campaign-retention proof found a prior STOP binding")

    attempt_records: list[str] = []
    terminal_records: list[str] = []
    stop_records: list[str] = []
    for path in sorted(area.rglob("*.json")):
        relative = str(path.relative_to(area))
        if relative in {
                "physical-campaign-authority.json",
                "phase-a-correction.json"}:
            continue
        try:
            value = json.loads(path.read_text())
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise RuntimeError(
                f"campaign-retention proof cannot parse {relative}") from error

        def walk(node: Any) -> None:
            if isinstance(node, Mapping):
                if node.get("campaign_id") == campaign_id:
                    if "attempt_id" in node:
                        attempt_records.append(relative)
                    if node.get("terminal_observation") is True or \
                            "terminal_classification" in node:
                        terminal_records.append(relative)
                    if node.get("stop_occurred") is True or \
                            "stop_attempt_id" in node:
                        stop_records.append(relative)
                for nested in node.values():
                    walk(nested)
            elif isinstance(node, list):
                for nested in node:
                    walk(nested)

        walk(value)
    if attempt_records or terminal_records or stop_records:
        raise RuntimeError(
            "campaign-retention proof found physical campaign records: "
            f"attempts={sorted(set(attempt_records))}, "
            f"terminals={sorted(set(terminal_records))}, "
            f"stops={sorted(set(stop_records))}")
    return {
        "campaign_id": campaign_id,
        "attempt_count": 0,
        "terminal_count": 0,
        "stop_count": 0,
        "prior_stop_fields_all_null": True,
        "same_campaign_rebinding_legal": True,
    }


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


def main(argv: list[str] | None = None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--validate-authority", action="store_true",
        help="validate the authority document against issue #133 bindings")
    parser.add_argument(
        "--verify-pre-execution-gate", action="store_true",
        help="mechanically verify the full pre-execution gate "
             "(accepted-history ancestry + freeze binding); Phase B must "
             "invoke this before any physical launch")
    args = parser.parse_args(argv)
    if args.validate_authority:
        document = load_authority_document()
        verdict = validate_authority_bindings(document)
        print(json.dumps(verdict, indent=2, sort_keys=True))
        return 0 if verdict["bound"] else 1
    if args.verify_pre_execution_gate:
        verdict = verify_pre_execution_authority_gate()
        print(json.dumps(verdict, indent=2, sort_keys=True))
        return 0
    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
