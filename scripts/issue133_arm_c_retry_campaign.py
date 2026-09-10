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
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
# review 5166773760/5167622668: when this module executes from the
# ACCEPTED Git materialization (its canonical deployment for physical
# authorization), ROOT is the materialization root; keep scripts/ the
# FIRST entry so same-named working-tree modules can never shadow the
# accepted bytes, and seal the interpreter against environment
# module-search injections (the external bootstrap additionally
# scrubs PYTHONPATH et al. from the subprocess environment itself).
for _injected in ("PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP",
                  "PYTHONUSERBASE"):
    os.environ.pop(_injected, None)

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

#: ---------------------------------------------------------------------------
#: Corrected freeze identities (Phase-B pre-execution correction, per the
#: maintainer disposition issuecomment-5617122680). Three DISTINCT plan
#: identities are now maintained separately:
#:
#: 1. the accepted Arm-B participant execution-plan identity — schema
#:    ``inferswarm.issue117.execution-plan/2`` (ISSUE133 above,
#:    "execution_plan_digest"): preserved participant/substrate authority
#:    only, NEVER the r5a fence expectation;
#: 2. the accepted/re-frozen Arm-C chain-plan identity
#:    a71a3129b8764d7108f51ed30fb230b42fcd69646a20bcd6806b6ee53b9bc51f;
#: 3. the corrected Issue-133 r5a STATIC execution-plan identity (schema
#:    ``inferswarm.r5a.static-execution-plan/1``) below — mechanically
#:    derived by the REAL unmocked frozen producer builder over the
#:    corrected canonical physical environment (98c04387…) and the
#:    authorized chain plan; proven by the mandatory CPU-only
#:    real-builder dry run (scripts/issue133_real_builder_dry_run.py).
#:    Copied programmatically from the dry-run output at freeze time.
AUTHORIZED_R5A_STATIC_PLAN_DIGEST = (
    "sha256:a730405dab8bad2ee8c4eea9a4fb97b8ef53ea15415a4d904bf666d020cdc625")
AUTHORIZED_R5A_STATIC_PLAN_SCHEMA = (
    "inferswarm.r5a.static-execution-plan/1")
#: the accepted Arm-B PARTICIPANT execution-plan document family
#: (distinct from the r5a static family; asserted distinct at import
#: time above and re-asserted against the authority-bound freeze record
#: by the real-builder verdict cross-checks)
ARM_B_PARTICIPANT_PLAN_SCHEMA = "inferswarm.issue117.execution-plan/2"
#: the corrected canonical Issue-133 physical environment identity
#: (scripts/issue133_canonical_environment.py; identical to the #129
#: derivation except the three pci_bdf values are the freshly observed
#: physical BDFs and the narrative-only provenance_note is dropped)
AUTHORIZED_ENVIRONMENT_CANONICAL_SHA256 = (
    "98c04387215915acf54a9ff769492e3f7cb7b0266d36649631a531a9b5edbf67")
#: expected r5a plan semantics (asserted by the dry run against the
#: really-built plan)
ISSUE133_R5A_EXPECTED_CANDIDATE_ID = (
    "resident-two-node-three-slot[slot-stage-1=gpu.node-a.0,"
    "slot-stage-2=gpu.node-a.1,slot-stage-3=gpu.node-b.0]")
ISSUE133_R5A_EXPECTED_MAPPING = {
    "slot-stage-1": "gpu.node-a.0",
    "slot-stage-2": "gpu.node-a.1",
    "slot-stage-3": "gpu.node-b.0",
}
if ISSUE133["execution_plan_digest"] == AUTHORIZED_R5A_STATIC_PLAN_DIGEST:
    raise SystemExit(
        "plan-family conflation: the Arm-B participant-plan digest and "
        "the r5a static-plan digest must never be the same value")

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
#: freeze schema /6 (review 5167622668): the pre-execution trust
#: bootstrap is now EXTERNAL to the working tree —
#: scripts/issue133_physical_prelaunch_gate.py (stdlib/Git-only)
#: resolves the accepted authority-bearing commit from
#: refs/remotes/origin/main, materializes that commit's complete tree
#: via git archive, byte-binds the complete physical-prelaunch
#: closure (gate tooling + the bootstrap itself) against the accepted
#: blobs, and executes the gate from that materialization only, in a
#: scrubbed-environment subprocess. Working-tree Python never
#: establishes its own authority. Schema /5 (review 5166773760)
#: fields retained; this /6 record adds the bootstrap provenance and
#: verdict-field contract. Schema /7 (review 5169777338) re-binds the
#: bootstrap to the CANONICAL GIT-ROOTED LAUNCHER: the first Python
#: executed for the physical prelaunch decision is the bootstrap blob
#: extracted from the accepted authority-bearing commit by shell+Git
#: alone (no working-tree loader), working-tree invocation fails
#: closed, and the verdict schema advances to /2.
FREEZE_SCHEMA = "inferswarm.issue133.execution-freeze/7"
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
            "98c04387215915acf54a9ff769492e3f7cb7b0266d36649631a531a9b5edbf67"),
        "expected_path": "/srv/inferswarm/state/arm-c/environment.json",
        "derivation": (
            "scripts/issue133_canonical_environment.py — the #129 "
            "derivation with the three pci_bdf values re-observed live "
            "(gpu-identity-observation.json) per maintainer decision "
            "issuecomment-5617122680, and the narrative-only "
            "provenance_note excluded from physical authorization"),
        "source_evidence": (
            "docs/implementation/r6-successor-dense-full-integration-117/"
            "evidence/physical-preflight.json + "
            "evidence/arm-c-retry/gpu-identity-observation.json"),
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
    "arm_b_participant_plan_digest", "arm_b_participant_plan_schema",
    "chain_plan_digest", "r5a_static_plan_digest",
    "r5a_static_plan_schema", "participant_identity", "fixture_digest",
    "case_count", "comparator_contract", "tokenizer_asset_pins",
    "tokenizer_software_identity", "tokenizer_python", "drivers",
    "dependencies", "authorized_realization_inputs",
    "real_builder_dry_run", "superseded_freeze_lineage",
    "deployment_verification_requirements",
    "gate_tooling_closure",
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


#: ---------------------------------------------------------------------------
#: PRE-EXECUTION GATE-TOOLING CLOSURE (maintainer review 5166773760).
#:
#: The exhaustive fixed set of repository-side Python files whose bytes
#: can affect the pre-execution authorization decision. Derived by
#: auditing the ACTUAL import graph of the gate:
#:
#: - scripts/issue133_arm_c_retry_campaign.py  (this module - the gate
#:   itself: authority loading, accepted-history resolution, freeze
#:   binding, dry-run invocation);
#: - scripts/issue133_real_builder_dry_run.py   (dynamically executed by
#:   verify_real_builder_dry_run);
#: - scripts/issue133_canonical_environment.py  (imported by the dry run;
#:   derives the corrected canonical physical environment);
#: - scripts/issue133_arm_c_retry_direct.py     (imported by the dry run;
#:   the corrected direct driver whose r5a fence and vendored
#:   byte-pinned producer closure build the plan);
#: - scripts/issue129_arm_c_retry_core.py       (imported by every module
#:   above; the frozen #129 authority/state-machine core -
#:   load_authority_document, accepted-authority semantics, campaign
#:   state classification, frozen control-plane loading);
#: - scripts/issue117_arm_c_frozen_pins.py      (loaded by the #129 core
#:   at authority/parse time - derive_invocation_semantics and the
#:   frozen tokenizer-asset pin table the authority parser consults).
#:
#: The frozen producer closure (frozen-source/924cd22e/*) is NOT
#: working-tree code: the dry run byte-pins every vendored file through
#: the #129 core's frozen loader and the direct driver's vendored-file
#: pin table before import, so it needs no accepted-commit binding here.
GATE_TOOLING_CLOSURE = (
    "scripts/issue133_arm_c_retry_campaign.py",
    "scripts/issue133_real_builder_dry_run.py",
    "scripts/issue133_canonical_environment.py",
    "scripts/issue133_arm_c_retry_direct.py",
    "scripts/issue129_arm_c_retry_core.py",
    "scripts/issue117_arm_c_frozen_pins.py",
)
#: the external Git-rooted bootstrap (maintainer review 5167622668)
#: binds this closure PLUS itself to the accepted authority commit
#: and executes this module from a ``git archive`` materialization of
#: that commit — current-working-tree Python never establishes its
#: own authority. The bootstrap's PHYSICAL_PRELAUNCH_CLOSURE must
#: equal this closure plus the bootstrap path; asserted by
#: tests/test_issue133_prelaunch_bootstrap.py.
EXTERNAL_BOOTSTRAP_REL_PATH = (
    "scripts/issue133_physical_prelaunch_gate.py")

#: freeze record fields the real-builder verdict is cross-checked against
#: (taken from the authority-bound execution-freeze record itself, never
#: from a mutable module constant alone).
FREEZE_BOUND_VERDICT_FIELDS = (
    "r5a_static_plan_schema",
    "r5a_static_plan_digest",
    "arm_b_participant_plan_schema",
    "arm_b_participant_plan_digest",
    "chain_plan_digest",
)


def _accepted_commit_blob(repo_path: Path, commit: str,
                          relative: str) -> bytes | None:
    """Exact blob bytes at ``commit:relative`` (raw bytes, never text
    transcoding); None when the path does not exist at that commit."""
    import subprocess
    completed = subprocess.run(
        ["git", "-C", str(repo_path), "show", f"{commit}:{relative}"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if completed.returncode != 0:
        return None
    return completed.stdout


def verify_gate_tooling_closure(
        accepted_commit: str,
        repo_root: Path | None = None,
        repo_path: Path | None = None) -> dict[str, Any]:
    """Fail-closed byte binding of the COMPLETE pre-execution
    gate-tooling closure against the accepted authority commit
    (maintainer review 5166773760): before any gate module is
    imported/executed, every file in ``GATE_TOOLING_CLOSURE`` must be a
    regular non-symlink working-tree file whose EXACT bytes equal the
    blob at the accepted authority commit.

    This closes the dependency hole where a working-tree edit or a
    later-main change could alter the launch gate while the
    authority-bound execution-freeze bytes still verify: gate tooling
    drift now rejects BEFORE the dry run executes.

    A later-main commit that leaves every gate byte identical to the
    accepted authority commit remains compatible (allowed); any gate
    byte change requires review/re-freeze (rejected here)."""
    bytes_root = Path(repo_root) if repo_root else ROOT
    git_root = Path(repo_path) if repo_path else bytes_root
    if not _frozen._is_git_sha(accepted_commit):
        raise RuntimeError(
            "gate-tooling closure: malformed accepted authority commit "
            f"{accepted_commit!r}; failing closed")
    verified: dict[str, str] = {}
    problems: list[str] = []
    for relative in GATE_TOOLING_CLOSURE:
        local = bytes_root / relative
        if local.is_symlink() or not local.is_file():
            problems.append(
                f"{relative} is not a regular non-symlink working-tree "
                "file")
            continue
        accepted_bytes = _accepted_commit_blob(
            git_root, accepted_commit, relative)
        if accepted_bytes is None:
            problems.append(
                f"no blob at {relative} in accepted authority commit "
                f"{accepted_commit}")
            continue
        local_sha = sha256_bytes(local.read_bytes())
        accepted_sha = sha256_bytes(accepted_bytes)
        if local_sha != accepted_sha:
            problems.append(
                f"gate tooling byte drift for {relative}: working tree "
                f"{local_sha} != accepted {accepted_sha}")
        else:
            verified[relative] = local_sha
    if problems:
        raise RuntimeError(
            "gate-tooling closure FAILED against accepted authority "
            f"commit {accepted_commit}: " + "; ".join(problems))
    return {
        "schema": "inferswarm.issue133.gate-tooling-closure/1",
        "accepted_authority_commit": accepted_commit,
        "bound_paths": sorted(GATE_TOOLING_CLOSURE),
        "verified": verified,
    }


def verify_pre_execution_authority_gate(
        repo_root: Path | None = None,
        repo_path: Path | None = None) -> dict[str, Any]:
    """Full pre-execution gate verdict for Phase B to invoke MECHANICALLY
    before any physical launch:

    - authority document loads + passes the #129-frozen strict schema;
    - the authority document is bound to the exact issue #133 identities;
    - the selected authority commit is an ancestor of
      ``refs/remotes/origin/main`` (accepted history);
    - the COMPLETE pre-execution gate-tooling closure (every
      repository-side Python file able to affect this decision) is
      byte-identical to the accepted authority commit - verified
      BEFORE any gate module is imported/executed (fail closed on any
      working-tree drift, symlink, missing path, or later-main gate
      byte change);
    - the retained execution-freeze bytes hash EXACTLY to the sole
      authorized campaign's ``execution_freeze_identity``;
    - MANDATORY REAL-BUILDER CPU DRY RUN, bound to the authority-loaded
      freeze record's OWN identities (never a mutable module constant
      alone): the actual unmocked frozen producer build path (no
      GPU/model work) reproduces exactly the freeze record's r5a
      static-plan digest, the freeze record, the campaign module
      constant, and the direct-driver constant all agree exactly, and
      the Arm-B participant-plan digest cannot satisfy that fence.

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
    # ---- review 5166773760: bind the executing gate-tooling bytes to
    # ---- the accepted authority commit BEFORE importing/executing any
    # ---- gate module.
    tooling = verify_gate_tooling_closure(commit, root, git_root)
    freeze = verify_execution_freeze_binding(document, root)
    dry_run = verify_real_builder_dry_run(
        root, freeze_record=freeze["record"])
    return {
        "schema": "inferswarm.issue133.pre-execution-gate/3",
        "gate": "ACCEPTED_HISTORY_TOOLING_FREEZE_AND_REAL_BUILDER_BOUND",
        "accepted_authority_commit": commit,
        "accepted_ref": ACCEPTED_REMOTE_REF,
        "campaign_ids": binding["campaign_ids"],
        "gate_tooling_closure": tooling,
        "execution_freeze_binding": freeze,
        "real_builder_dry_run": dry_run,
    }


def verify_real_builder_dry_run(
        repo_root: Path | None = None,
        freeze_record: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """MANDATORY pre-launch check (maintainer disposition
    issuecomment-5617122680 + review 5166773760): from the exact
    repository bytes, the ACTUAL unmocked frozen producer build path
    must produce an r5a static execution plan whose digest equals the
    digest authorized by the RETAINED, authority-bound
    execution-freeze record itself (``freeze_record``; loaded and
    byte-verified here when not supplied). No GPU, no model
    realization — pure CPU build path. The freeze record's r5a
    schema/digest, the Arm-B participant identity, the chain-plan
    digest, and the authorized environment canonical sha256 are
    cross-checked against the executing module constants and the
    really-built plan; ANY disagreement fails closed before physical
    execution. The wrong-family negative control must also hold."""
    root = Path(repo_root) if repo_root else ROOT
    import importlib
    import importlib.util
    # ---- review 5166773760: the dry run is bound to the AUTHORITY-
    # ---- LOADED, byte-verified execution-freeze record's own
    # ---- identities, never to a mutable module constant alone.
    if freeze_record is None:
        record, _raw = load_execution_freeze_record(root)
        verify_freeze_static_shape(record)
    else:
        record = freeze_record
    for field in FREEZE_BOUND_VERDICT_FIELDS:
        if field not in record:
            raise RuntimeError(
                f"authority-bound freeze record lacks field {field!r}; "
                "the real-builder verdict cannot be bound to authority")
    bound = {field: record[field] for field in FREEZE_BOUND_VERDICT_FIELDS}
    bound_environment_sha = record["authorized_realization_inputs"][
        "environment"]["canonical_sha256"]
    script = root / "scripts" / "issue133_real_builder_dry_run.py"
    spec = importlib.util.spec_from_file_location(
        "_issue133_real_builder_dry_run", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    result = module.run_real_builder_dry_run(freeze_bound=bound)
    plan = result["plan"]
    verdict = module.verify_dry_run(plan, freeze_bound=bound)
    module.verify_wrong_family_negative_control(plan)
    module.verify_arm_b_participant_authority()
    problems: list[str] = []
    # 1. the really-built plan equals the AUTHORITY-BOUND freeze values
    if plan.get("schema") != bound["r5a_static_plan_schema"]:
        problems.append(
            f"built plan schema {plan.get('schema')!r} != freeze record "
            f"{bound['r5a_static_plan_schema']!r}")
    if plan.get("digest") != bound["r5a_static_plan_digest"]:
        problems.append(
            f"built r5a digest {plan.get('digest')!r} != freeze record "
            f"{bound['r5a_static_plan_digest']!r}")
    # 2. the freeze record, the campaign constant, and the direct-driver
    #    constant must agree EXACTLY (any disagreement fails before
    #    physical execution)
    if bound["r5a_static_plan_digest"] != AUTHORIZED_R5A_STATIC_PLAN_DIGEST:
        problems.append(
            "freeze record r5a digest != campaign constant "
            f"{AUTHORIZED_R5A_STATIC_PLAN_DIGEST!r}")
    if bound["r5a_static_plan_schema"] != AUTHORIZED_R5A_STATIC_PLAN_SCHEMA:
        problems.append("freeze record r5a schema != campaign constant")
    if bound["arm_b_participant_plan_digest"] != \
            ISSUE133["execution_plan_digest"]:
        problems.append(
            "freeze record Arm-B participant digest != campaign constant")
    if bound["arm_b_participant_plan_schema"] != \
            ARM_B_PARTICIPANT_PLAN_SCHEMA:
        problems.append(
            "freeze record Arm-B participant schema != campaign constant")
    if bound["chain_plan_digest"] != \
            AUTHORIZED_REALIZATION_INPUTS["chain_plan"]["digest"]:
        problems.append(
            "freeze record chain-plan digest != campaign constant")
    if verdict["digest"] != bound["r5a_static_plan_digest"]:
        problems.append("dry-run verdict digest != freeze record digest")
    # 3. the corrected environment identity is the freeze record's own
    built_environment_sha = result.get("environment_canonical_sha256")
    if built_environment_sha != bound_environment_sha:
        problems.append(
            "built environment canonical sha256 "
            f"{built_environment_sha!r} != freeze record "
            f"{bound_environment_sha!r}")
    # 4. the direct-driver module constant agrees too (imported lazily
    #    so, inside the pre-execution gate, the gate's own byte binding
    #    has already been verified before this import)
    import issue133_arm_c_retry_direct as _driver
    if _driver.AUTHORIZED_R5A_STATIC_PLAN_DIGEST != \
            bound["r5a_static_plan_digest"]:
        problems.append(
            "direct-driver r5a digest constant != freeze record digest")
    if _driver.AUTHORIZED_R5A_STATIC_PLAN_SCHEMA != \
            bound["r5a_static_plan_schema"]:
        problems.append(
            "direct-driver r5a schema constant != freeze record schema")
    if _driver.AUTHORIZED_ENVIRONMENT_CANONICAL_SHA256 != \
            bound_environment_sha:
        problems.append(
            "direct-driver environment constant != freeze record "
            "environment identity")
    if problems:
        raise RuntimeError(
            "REAL-BUILDER DRY RUN authority binding FAILED: "
            + "; ".join(problems)
            + "; physical launch is rejected")
    verdict = dict(verdict)
    verdict["freeze_bound_verdict_fields"] = dict(bound)
    verdict["environment_canonical_sha256"] = built_environment_sha
    return verdict


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
    # plan-family separation (corrected Phase-B): the Arm-B participant
    # plan (issue117.execution-plan/2) and the r5a static plan
    # (r5a.static-execution-plan/1) are DISTINCT document families with
    # DISTINCT digests; conflation fails closed
    if record["arm_b_participant_plan_schema"] != (
            "inferswarm.issue117.execution-plan/2"):
        raise RuntimeError(
            "Arm-B participant plan schema drift: expected "
            "inferswarm.issue117.execution-plan/2")
    if record["r5a_static_plan_schema"] != (
            "inferswarm.r5a.static-execution-plan/1"):
        raise RuntimeError(
            "r5a static plan schema drift: expected "
            "inferswarm.r5a.static-execution-plan/1")
    if record["arm_b_participant_plan_digest"] == record[
            "r5a_static_plan_digest"]:
        raise RuntimeError(
            "plan-family conflation in the execution freeze: the Arm-B "
            "participant-plan digest and the r5a static-plan digest are "
            "different document families and must never be equal")
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
        # the LOADED, byte-verified freeze record itself: the
        # authority-bound source of every identity the real-builder
        # verdict is cross-checked against (review 5166773760)
        "record": record,
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
        "arm_b_participant_plan_digest": ISSUE133["execution_plan_digest"],
        "arm_b_participant_plan_schema": (
            "inferswarm.issue117.execution-plan/2"),
        "chain_plan_digest": (
            "sha256:a71a3129b8764d7108f51ed30fb230b42fcd69646"
            "a20bcd6806b6ee53b9bc51f"),
        "r5a_static_plan_digest": AUTHORIZED_R5A_STATIC_PLAN_DIGEST,
        "r5a_static_plan_schema": AUTHORIZED_R5A_STATIC_PLAN_SCHEMA,
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
        "real_builder_dry_run": {
            "required": True,
            "gate": "ISSUE133_REAL_BUILDER_CPU_DRY_RUN_BOUND",
            "script": "scripts/issue133_real_builder_dry_run.py",
            "semantics": (
                "before any physical launch, the ACTUAL unmocked frozen "
                "producer build path must produce an r5a static plan "
                "(inferswarm.r5a.static-execution-plan/1) whose digest "
                "equals r5a_static_plan_digest; the Arm-B "
                "participant-plan digest (issue117.execution-plan/2) "
                "must fail the same fence (wrong-family negative "
                "control)"),
            "authority_binding": (
                "review 5166773760: the verdict is bound to THIS "
                "authority-bound freeze record's own values — "
                "r5a_static_plan_schema, r5a_static_plan_digest, "
                "arm_b_participant_plan_schema, "
                "arm_b_participant_plan_digest, chain_plan_digest, and "
                "authorized_realization_inputs.environment."
                "canonical_sha256 are taken from the loaded, "
                "byte-verified record and cross-checked against the "
                "executing module constants and the really-built plan; "
                "ANY disagreement fails closed before physical "
                "execution"),
            "bound_verdict_fields": list(FREEZE_BOUND_VERDICT_FIELDS),
        },
        "gate_tooling_closure": {
            "required": True,
            "binding": (
                "review 5169777338: the canonical physical prelaunch "
                "launch is SHELL + GIT ONLY before Python (codified "
                "in METHODOLOGY-ARM-C-RETRY.md, 'Canonical "
                "physical-prelaunch launch contract'): the operator "
                "recipe resolves refs/remotes/origin/main, selects "
                "the newest accepted commit carrying the current "
                "physical-campaign authority document with Git "
                "plumbing, extracts scripts/issue133_physical_"
                "prelaunch_gate.py from THAT commit with git show "
                "into a fresh temporary directory, verifies the "
                "extracted bytes equal the selected Git blob, and "
                "executes `python3 -I -S <extracted-bootstrap> "
                "--accepted-bootstrap --repo <repository>`. NO "
                "Python file read from the mutable working tree "
                "executes before the accepted bootstrap; the "
                "working-tree invocation of the bootstrap FAILS "
                "CLOSED (non-authorizing). The accepted bootstrap "
                "verifies its own bytes equal the accepted blob, "
                "materializes that commit's complete tree via git "
                "archive into an isolated temporary directory, "
                "byte-binds the COMPLETE physical-prelaunch closure "
                "(the gate-tooling closure below PLUS the bootstrap "
                "itself) against the accepted blobs, and executes "
                "the pre-execution gate from that accepted "
                "materialization only — in a subprocess with "
                "PYTHONPATH/PYTHONHOME/PYTHONSTARTUP/PYTHONUSERBASE "
                "scrubbed so materialized modules cannot resolve "
                "same-named working-tree modules. Current-working-"
                "tree Python never establishes its own authority; "
                "working-tree copies are compared with the accepted "
                "bytes only as a secondary defense-in-depth "
                "integrity report. A later-main commit leaving every "
                "closure byte identical remains compatible; any "
                "closure byte change requires review/re-freeze."),
            "paths": list(GATE_TOOLING_CLOSURE),
            "external_bootstrap": EXTERNAL_BOOTSTRAP_REL_PATH,
            "bootstrap_closure": list(GATE_TOOLING_CLOSURE) + [
                EXTERNAL_BOOTSTRAP_REL_PATH],
            "bootstrap_verdict_schema": (
                "inferswarm.issue133.physical-prelaunch-bootstrap/2"),
        },
        "superseded_freeze_lineage": [
            {
                "execution_freeze_identity": (
                    "5af9aee314fdd742cdb75d903d47e2f3c43296ee887e50"
                    "7ef335b8f614e7a19e"),
                "status": "INVALIDATED_BEFORE_PHYSICAL_EXECUTION",
                "reason": (
                    "Phase-B preflight STOP issuecomment-5613617497: "
                    "Blocker A (unsatisfiable plan-family conflation in "
                    "the authorization fence) and Blocker B (frozen "
                    "environment embedded non-physical node_a BDF "
                    "literals); maintainer disposition "
                    "issuecomment-5617122680 authorized this corrected "
                    "freeze. Zero physical attempts occurred under the "
                    "superseded freeze."),
            },
        ],
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
    parser.add_argument(
        "--git-repo", type=Path, default=None,
        help="the Git repository whose refs/remotes/origin/main and "
             "object database prove accepted history when this module "
             "executes from an accepted Git materialization (the "
             "canonical physical-prelaunch deployment, review "
             "5167622668); defaults to the repository containing this "
             "file. The working tree of that repository is consulted "
             "for Git metadata only, never for executable code")
    parser.add_argument(
        "--print-gate-tooling-closure", action="store_true",
        help="print the gate-tooling closure paths (used by the "
             "external bootstrap and its closure-agreement tests; "
             "performs no verification)")
    args = parser.parse_args(argv)
    if args.print_gate_tooling_closure:
        print(json.dumps(
            {"gate_tooling_closure": list(GATE_TOOLING_CLOSURE),
             "external_bootstrap": EXTERNAL_BOOTSTRAP_REL_PATH}))
        return 0
    if args.validate_authority:
        document = load_authority_document()
        verdict = validate_authority_bindings(document)
        print(json.dumps(verdict, indent=2, sort_keys=True))
        return 0 if verdict["bound"] else 1
    if args.verify_pre_execution_gate:
        repo_path = args.git_repo
        verdict = verify_pre_execution_authority_gate(
            repo_path=repo_path) if repo_path is not None else \
            verify_pre_execution_authority_gate()
        print(json.dumps(verdict, indent=2, sort_keys=True))
        return 0
    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
