#!/usr/bin/env python3
"""Issue #213 — campaign validation gate ordering and exact-head receipts.

Repository-owned orchestration semantics for physical/research campaign
handoff.  Four concerns live here:

1. **Gate ordering doctrine (machine-checked).**  ``CampaignFlow`` /
   ``plan_campaign_gates`` model a campaign as the pre-review phase (cheap,
   reviewer-trust-building gates) followed by the final-head phase (the one
   full-suite + one hosted-CI run on the final reviewed head).  The two
   expensive gates are MANDATORY final-head gates: a plan that omits either
   (or both) fails closed.  Adversarial review runs against the frozen
   pre-review head and MUST NOT request the expensive gates unless the
   campaign explicitly declares them review-critical.  Any unknown gate or
   workflow state fails closed to the existing broader behavior (fresh full
   validation).

2. **Duplicate-launch prevention (Phase 2) — on the canonical invocation
   path.**  ``run_single_head_suite`` is the single-launch seam wired into
   ``scripts/run_full_cpu_suite.py``'s canonical CLI entry: one logical
   ``(head, suite-config, environment-authority)`` request launches at most
   ONE real suite process on a host.  A concurrent identical request
   ATTACHES to the owner's live launch and consumes its mechanically
   validated completion receipt rather than starting another suite.  The
   launch identity key is derived mechanically (exact git SHA + canonical
   suite population digest from the runner's own plan + environment
   authority hashes); an arbitrary caller-supplied lock key is never
   accepted as authority.  Stale/malformed state fails closed; a stale
   holder is replaced only when mechanically proven dead.

3. **Exact-head suite receipts (Phase 3).**  ``SuiteReceipt`` binds a
   successful full-suite run to the exact repository SHA, the canonical
   suite identity (runner schema + canonical command + serial identity
   digest of the executed population + executed digest + test count), the
   environment authority identity, and start/end timestamps.  Receipt
   structure is validated field-by-field, fail-closed — never by arbitrary
   nested-dictionary equality alone.

4. **Independently bound final handoff.**  ``handoff_gate_status`` takes an
   independently derived ``FinalHeadRequest`` (current/final head identity,
   NEVER identity extracted from the receipt under validation) and requires
   BOTH the suite receipt and the hosted-CI status to bind to that exact
   SHA.  Hosted CI must present a structured status receipt (schema, exact
   SHA, ``SUCCESS`` result, run identity); a bare unbound boolean can never
   complete handoff.

This module is orchestration metadata tooling, NOT a hash-pinned evidence
producer and NOT a persistent result cache: the launch guard keeps at most
one bounded completion receipt per live identity on a host; receipts are
advisory deduplication records whose reuse the doctrine may permit; they
never replace the run itself when policy requires fresh validation.

Fail-closed posture throughout: every ambiguity (unknown gate name, missing
identity field, malformed lock or completion, non-success result, mismatched
digest) rejects rather than warns.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

SCHEMA = "campaign-gate-ordering/1"
RECEIPT_SCHEMA = "exact-head-suite-receipt/1"
CI_STATUS_SCHEMA = "hosted-ci-exact-head-status/1"
LAUNCH_IDENTITY_SCHEMA = "suite-launch-identity/1"
LAUNCH_LOCK_SCHEMA = "suite-launch-lock/2"
COMPLETION_SCHEMA = "suite-launch-completion/1"

# Structured normalized suite-configuration identity (Issue #213
# configuration correction).  MUST equal the runner's own
# SUITE_CONFIG_SCHEMA; a mismatch fails closed at derivation.
SUITE_CONFIG_SCHEMA = "suite-config/1"

# The canonical final-validation configuration values (current runner
# doctrine): default tests directory, default jobs schedule, default
# per-task timeout, no retained-artifact request.
CANONICAL_TIMEOUT_SECONDS = 1800.0

# The documented retained per-task artifact set (assignment + receipt +
# captured output streams) a `--retain-dir` request is entitled to.
RETAINED_TASK_SUFFIXES = ("-modules.json", "-expected.json", ".json",
                          "-stdout.txt", "-stderr.txt")

# Runner schema per current runner doctrine (scripts/run_full_cpu_suite.py
# SCHEMA constant).  Suite identities carrying any other runner schema are
# malformed and fail closed.
RUNNER_SCHEMA = "parallel-full-cpu-suite/1"

# The canonical suite command/config identity.  Any receipt whose suite
# command differs describes a different (non-canonical) invocation.
FULL_SUITE_COMMAND = (".venv/bin/python", "scripts/run_full_cpu_suite.py",
                      "--json")

# Environment authority: the single dependency authority file plus the two
# scripts that create/qualify the canonical environment.  A change to any of
# these changes the environment identity and invalidates receipt reuse.
ENV_AUTHORITY_FILES = (
    "requirements-test.txt",
    "scripts/bootstrap_test_env.py",
    "scripts/check_test_env.py",
)

# The runner whose invocation is guarded and whose results are receipted.
SUITE_RUNNER = "scripts/run_full_cpu_suite.py"

# Gates reviewers may need before reviewing the frozen head.  All are cheap,
# scoped, and already required by existing campaign doctrine; NONE of them is
# the full CPU suite or hosted CI.
PRE_REVIEW_GATES = frozenset({
    "focused-changed-surface-tests",
    "campaign-reducer-negative-controls",
    "predecessor-evidence-preservation-checks",
    "evidence-manifest-checks",
    "physical-authority-discovery-topology-validation",
    "prospective-correctness-authority-freeze-checks",
    "finalizer-status-pre-review-integrity-checks",
    "ci-planner-self-check",
})

# The expensive final-head gates.  Each runs EXACTLY ONCE on the final
# reviewed head, after review-driven mutation has stopped.
FINAL_HEAD_GATES = frozenset({
    "full-cpu-suite",
    "hosted-exact-head-ci",
    "finalizer-status-fixed-point-checks",
})

# The two expensive gates that are MANDATORY for every campaign handoff
# governed by this doctrine.  Issue #213 established no exemption: a plan
# that omits either gate fails closed, and no caller boolean can bypass
# this.
REQUIRED_FINAL_HEAD_GATES = frozenset({
    "full-cpu-suite",
    "hosted-exact-head-ci",
})

# A campaign may declare one of the expensive gates review-critical when a
# review lane genuinely depends on its result as an input.  The declaration
# is explicit per campaign; it never widens by default.
REVIEW_CRITICAL_EXCEPTIONS = frozenset({"full-cpu-suite", "hosted-exact-head-ci"})

# Gate classification for the Phase 0 audit vocabulary.
GATE_CLASSIFICATIONS = frozenset({
    "PRE_REVIEW_REQUIRED",
    "FINAL_HEAD_REQUIRED",
    "BOTH_WITH_JUSTIFICATION",
    "REDUNDANT_CURRENTLY",
    "NOT_APPLICABLE",
})

_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

# Hard wall for one full-suite launch used by the guard's wait/aging logic.
LAUNCH_GUARD_TIMEOUT_SECONDS = 4 * 60 * 60
# A completion receipt older than this is ignored (bounded liveness: no
# unbounded persistent result cache, just enough window for concurrent and
# immediately-following identical requests to consume the one real run).
COMPLETION_MAX_AGE_SECONDS = 24 * 60 * 60
# Grace window during which a just-created (possibly still-empty) lock file
# is re-read instead of being treated as malformed.
LOCK_WRITE_GRACE_SECONDS = 5.0


class GateOrderingError(RuntimeError):
    """A fail-closed gate-ordering or receipt validation failure."""


# ---------------------------------------------------------------------------
# Structural identity validation (fail closed on shape, not dict equality)
# ---------------------------------------------------------------------------

def _validate_git_sha(sha: object, what: str) -> str:
    if not isinstance(sha, str) or not _GIT_SHA_RE.fullmatch(sha):
        raise GateOrderingError(
            f"{what} is not an exact git SHA (fail closed): {sha!r}")
    return sha


def _validate_suite_config(config: object) -> None:
    """Structurally validate a normalized suite configuration (fail closed).

    The configuration is the authority for execution identity: known
    schema, a nonempty tests-directory identity, a valid requested-jobs
    value (None or a positive integer), a positive integer effective-jobs
    value, a 64-hex deterministic task-plan digest, a positive timeout,
    and a retain_dir that is None or a nonempty string.
    """
    if not isinstance(config, dict):
        raise GateOrderingError(
            "suite configuration is not an object (fail closed)")
    if config.get("schema") != SUITE_CONFIG_SCHEMA:
        raise GateOrderingError(
            "suite configuration schema is unknown (fail closed): "
            f"{config.get('schema')!r}")
    tests_dir = config.get("tests_dir")
    if not isinstance(tests_dir, str) or not tests_dir.strip():
        raise GateOrderingError(
            "suite configuration tests_dir is malformed (fail closed): "
            f"{tests_dir!r}")
    jobs = config.get("jobs")
    if not isinstance(jobs, int) or isinstance(jobs, bool) or jobs < 1:
        raise GateOrderingError(
            "suite configuration effective jobs is malformed (fail closed): "
            f"{jobs!r}")
    plan_digest = config.get("plan_digest")
    if not isinstance(plan_digest, str) or not _SHA256_RE.fullmatch(plan_digest):
        raise GateOrderingError(
            "suite configuration plan digest is malformed (fail closed): "
            f"{plan_digest!r}")
    timeout = config.get("timeout")
    if (not isinstance(timeout, (int, float)) or isinstance(timeout, bool)
            or timeout <= 0):
        raise GateOrderingError(
            "suite configuration timeout is malformed (fail closed): "
            f"{timeout!r}")
    retain = config.get("retain_dir")
    if retain is not None and (not isinstance(retain, str) or not retain.strip()):
        raise GateOrderingError(
            "suite configuration retain_dir is malformed (fail closed): "
            f"{retain!r}")


def validate_suite_identity_values(suite: object) -> None:
    """Validate the required suite identity structure and values.

    Required: known runner schema, the canonical suite command/config
    identity, a structurally valid normalized suite configuration, hex
    serial and executed digests that are EQUAL, and a positive integer
    test count.  Anything else (missing, unknown, malformed, forged)
    fails closed.
    """
    if not isinstance(suite, dict):
        raise GateOrderingError("suite identity is not an object (fail closed)")
    if suite.get("runner_schema") != RUNNER_SCHEMA:
        raise GateOrderingError(
            "suite identity runner schema is unknown (fail closed): "
            f"{suite.get('runner_schema')!r}")
    command = suite.get("suite_command")
    if not isinstance(command, list) or [str(part) for part in command] != \
            list(FULL_SUITE_COMMAND):
        raise GateOrderingError(
            "suite identity command is not the canonical suite "
            f"configuration (fail closed): {command!r}")
    if "suite_config" not in suite:
        raise GateOrderingError(
            "suite identity lacks the normalized suite configuration "
            "(fail closed)")
    _validate_suite_config(suite["suite_config"])
    serial = suite.get("serial_digest")
    executed = suite.get("executed_digest")
    for name, value in (("serial_digest", serial),
                        ("executed_digest", executed)):
        if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
            raise GateOrderingError(
                f"suite identity {name} is malformed (fail closed): {value!r}")
    if serial != executed:
        raise GateOrderingError(
            "suite identity serial/executed digests differ (fail closed)")
    count = suite.get("count")
    if not isinstance(count, int) or isinstance(count, bool) or count < 1:
        raise GateOrderingError(
            f"suite identity count is not a positive integer (fail closed): "
            f"{count!r}")


def validate_environment_authority(environment: object) -> None:
    """Require a complete environment-authority map, exactly, fail closed.

    The map must cover ALL required authority files — no missing file, no
    unknown extra file — and every value must be a hex sha256 digest.
    """
    if not isinstance(environment, dict):
        raise GateOrderingError(
            "environment authority identity is not an object (fail closed)")
    expected = set(ENV_AUTHORITY_FILES)
    actual = set(environment)
    if actual != expected:
        missing = sorted(expected - actual)
        unknown = sorted(actual - expected)
        raise GateOrderingError(
            "environment authority map incomplete or unknown (fail closed): "
            f"missing={missing} unknown={unknown}")
    for rel, digest in sorted(environment.items()):
        if not isinstance(digest, str) or not _SHA256_RE.fullmatch(digest):
            raise GateOrderingError(
                f"environment authority digest malformed for {rel} "
                f"(fail closed): {digest!r}")


def suite_identity(runner_result: dict) -> dict:
    """Canonical suite identity from a successful runner result payload.

    Binds the runner schema, the canonical command, the NORMALIZED SUITE
    CONFIGURATION the runner actually executed under (tests directory,
    jobs schedule, task-plan digest, timeout, retention), the serial
    identity digest of the discovered population, the executed identity
    digest, and the test count.  The runner must have proven
    serial/executed equality (``ok``); otherwise the identity is
    malformed (fail closed).
    """
    if not isinstance(runner_result, dict):
        raise GateOrderingError("suite result payload is not an object")
    if not runner_result.get("ok"):
        raise GateOrderingError(
            "suite identity requires a successful runner result")
    serial = runner_result.get("serial_digest")
    executed = runner_result.get("executed_digest")
    count = runner_result.get("count")
    if not (isinstance(serial, str) and isinstance(executed, str)
            and serial == executed):
        raise GateOrderingError(
            "runner result lacks serial/executed identity equality")
    if not isinstance(count, int) or isinstance(count, bool) or count < 1:
        raise GateOrderingError("runner result lacks a valid test count")
    identity = {
        "runner_schema": RUNNER_SCHEMA,
        "suite_command": list(FULL_SUITE_COMMAND),
        "suite_config": runner_result.get("suite_config"),
        "serial_digest": serial,
        "executed_digest": executed,
        "count": count,
    }
    validate_suite_identity_values(identity)
    return identity


# ---------------------------------------------------------------------------
# Phase 1 — canonical campaign gate ordering
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CampaignFlow:
    """One campaign's gate schedule under the canonical ordering.

    ``campaign_id``      — stable campaign identity (e.g. ``issue-210``).
    ``pre_review``       — gates run before adversarial review freezes.
    ``final_head``       — gates run once on the final reviewed head.
    ``review_critical``  — expensive gates a review lane explicitly needs
                            as an input (each requires justification).
    """

    campaign_id: str
    pre_review: tuple[str, ...] = ()
    final_head: tuple[str, ...] = ("full-cpu-suite", "hosted-exact-head-ci",
                                   "finalizer-status-fixed-point-checks")
    review_critical: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        unknown_pre = [g for g in self.pre_review if g not in PRE_REVIEW_GATES]
        if unknown_pre:
            raise GateOrderingError(
                f"unknown pre-review gates (fail closed): {unknown_pre}")
        unknown_final = [g for g in self.final_head if g not in FINAL_HEAD_GATES]
        if unknown_final:
            raise GateOrderingError(
                f"unknown final-head gates (fail closed): {unknown_final}")
        unknown_rc = [g for g in self.review_critical
                      if g not in REVIEW_CRITICAL_EXCEPTIONS]
        if unknown_rc:
            raise GateOrderingError(
                "review-critical declarations must name an expensive gate "
                f"(fail closed): {unknown_rc}")
        # MANDATORY final gates: a campaign-handoff plan governed by this
        # doctrine can never omit the full suite or hosted CI.  This
        # includes the empty-final-head case.
        missing = sorted(REQUIRED_FINAL_HEAD_GATES - set(self.final_head))
        if missing:
            raise GateOrderingError(
                "final-head plan omits a mandatory campaign gate "
                f"(fail closed): {missing}")
        overlap = set(self.pre_review) & set(self.final_head)
        if overlap:
            raise GateOrderingError(
                f"gates scheduled in both phases (fail closed): {sorted(overlap)}")
        overlap_rc = set(self.review_critical) & set(self.pre_review)
        if overlap_rc:
            raise GateOrderingError(
                "review-critical gates are scheduled before review anyway; "
                f"remove the declaration (fail closed): {sorted(overlap_rc)}")


def plan_campaign_gates(flow: CampaignFlow,
                        review_mutates_head: bool = True) -> dict:
    """Return the canonical ordered gate plan for one campaign handoff.

    Requirement vs execution accounting is explicit:

    * ``expensive_gate_executions`` counts PHYSICAL expensive-gate
      executions.  The normal plan executes full-suite once and hosted CI
      once on the final head.  A review-critical gate that ran pre-review
      and whose binding head was NOT mutated by review satisfies the final
      requirement through mechanically validated reuse (one execution, not
      two); a mutated head voids the exact-head binding and forces a second
      physical execution on the new final head.
    * ``final_validation_cycles`` counts complete final validation CYCLES:
      one normal cycle = one cycle containing the full suite AND hosted CI
      proven against one final head.  It is never a count of individual
      gate executions.
    """
    plan: dict = {
        "schema": SCHEMA,
        "campaign_id": flow.campaign_id,
        "phases": [
            {
                "phase": "pre-review",
                "gates": list(flow.pre_review),
                "note": ("cheap reviewer-trust gates only; expensive "
                         "validation is deferred to the final head"),
            },
            {
                "phase": "adversarial-review",
                "gates": [],
                "note": ("read-only against the frozen pre-review head; "
                         "reviewers must not require full-suite/hosted-CI "
                         "results unless declared review-critical"),
            },
            {
                "phase": "apply-accepted-review-fixes",
                "gates": [],
                "note": ("all accepted findings incorporated; focused "
                         "checks re-run as needed"),
            },
            {
                "phase": "final-head",
                "gates": [],
                "requirements": list(flow.final_head),
                "note": ("the mandatory full CPU suite + hosted exact-head "
                         "CI proven against one final head; a review-critical "
                         "pre-review result satisfies its requirement through "
                         "mechanically validated exact-head reuse when review "
                         "did not mutate the head"),
            },
        ],
        "review_critical": list(flow.review_critical),
        "review_mutates_head": review_mutates_head,
    }
    executions: dict[str, int] = {}
    for gate in sorted(set(flow.final_head) & REVIEW_CRITICAL_EXCEPTIONS):
        executions[gate] = 1
    reuse_satisfied: list[str] = []
    for gate in sorted(set(flow.review_critical) & set(flow.final_head)):
        if review_mutates_head:
            # The pre-review execution's exact-head binding is void; the
            # gate physically runs again on the new final head (counted,
            # never hidden).
            executions[gate] += 1
        else:
            # No mutation: the pre-review result remains bound to the exact
            # final head and satisfies the final requirement through
            # mechanically validated reuse — no second physical execution.
            reuse_satisfied.append(gate)
    # Physical final-head executions: every requirement NOT already
    # satisfied by a reuse-valid pre-review result.
    plan["phases"][3]["gates"] = [g for g in flow.final_head
                                  if g not in reuse_satisfied]
    if flow.review_critical:
        plan["phases"][0]["gates"] = sorted(
            set(flow.pre_review) | set(flow.review_critical))
        if review_mutates_head:
            plan["note_review_critical"] = (
                "review-critical gates ran pre-review by declaration and "
                "RE-RUN on the final head because review mutated it")
        else:
            plan["note_review_critical"] = (
                "review-critical gates ran pre-review by declaration; review "
                "did NOT mutate the head, so their exact-head results "
                "satisfy the final requirement through validated reuse")
    plan["reuse_satisfied_final"] = reuse_satisfied
    plan["expensive_gate_executions"] = executions
    plan["final_validation_cycles"] = 1  # one cycle = full suite + hosted CI
    # Exactness check: expensive-gate occurrences in the scheduled plan must
    # equal the physical execution count derived above (fail closed).
    scheduled = [g for phase in plan["phases"] for g in phase["gates"]]
    for gate, expected in executions.items():
        occurrences = scheduled.count(gate)
        if occurrences != expected:
            raise GateOrderingError(
                f"expensive gate {gate!r} scheduled {occurrences}x, "
                f"expected exactly {expected}")
    return plan


# ---------------------------------------------------------------------------
# Phase 3 — exact-head suite receipt
# ---------------------------------------------------------------------------

def _git_output(root: Path, *args: str) -> str:
    proc = subprocess.run(["git", "-C", str(root), *args],
                          capture_output=True, text=True)
    if proc.returncode != 0:
        raise GateOrderingError(
            f"git {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc.stdout.strip()


def git_commit_sha(root: Path) -> str:
    return _validate_git_sha(_git_output(root, "rev-parse", "HEAD"),
                             "git HEAD")


def environment_identity(root: Path) -> dict:
    """Fail-closed environment/dependency authority identity.

    Every declared authority file must exist and hash cleanly; the identity
    is the sorted file→sha256 map.  A missing authority file is an error,
    never a skip.
    """
    identity = {}
    for rel in ENV_AUTHORITY_FILES:
        path = root / rel
        if not path.is_file():
            raise GateOrderingError(
                f"environment authority file missing: {rel}")
        identity[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    return identity


@dataclass(frozen=True)
class SuiteReceipt:
    """The smallest internal record answering 'has the complete CPU suite
    already passed for this exact head and exact suite identity?'."""

    git_commit_sha: str
    suite: dict          # canonical suite command/config identity
    environment: dict    # environment authority identity
    result: str          # "PASS"
    count: int
    started_unix: float
    ended_unix: float

    def to_dict(self) -> dict:
        return {
            "schema": RECEIPT_SCHEMA,
            "git_commit_sha": self.git_commit_sha,
            "suite": self.suite,
            "environment": self.environment,
            "result": self.result,
            "count": self.count,
            "started_unix": self.started_unix,
            "ended_unix": self.ended_unix,
        }


def build_receipt(root: Path, runner_result: dict,
                  started_unix: float, ended_unix: float) -> SuiteReceipt:
    """Build a receipt from a FRESH successful runner payload (fail closed)."""
    if not git_tree_clean(root):
        raise GateOrderingError(
            "refusing receipt on dirty worktree (fail closed)")
    return SuiteReceipt(
        git_commit_sha=git_commit_sha(root),
        suite=suite_identity(runner_result),
        environment=environment_identity(root),
        result="PASS",
        count=runner_result["count"],
        started_unix=started_unix,
        ended_unix=ended_unix,
    )


def request_identity(request_like: dict) -> dict:
    """Extract and STRUCTURALLY validate a request identity (fail closed).

    Callers pass either a prior receipt's dict or an independently derived
    ``FinalHeadRequest.to_dict()``; the suite/environment fields must be
    structurally valid — arbitrary nested dictionaries never compare equal
    their way into authority.
    """
    required = ("git_commit_sha", "suite", "environment")
    if not isinstance(request_like, dict):
        raise GateOrderingError("request identity is not an object")
    missing = [k for k in required if k not in request_like]
    if missing:
        raise GateOrderingError(
            f"request identity missing fields (fail closed): {missing}")
    _validate_git_sha(request_like["git_commit_sha"],
                      "request identity git_commit_sha")
    validate_suite_identity_values(request_like["suite"])
    validate_environment_authority(request_like["environment"])
    return {k: request_like[k] for k in required}


def validate_receipt(receipt: dict, request: dict) -> bool:
    """Authorize reuse ONLY on validated structure plus full identity match.

    Fail-closed on: wrong/unknown schema, non-PASS or missing result,
    missing or malformed identity fields (SHA shape, suite identity
    structure, environment authority completeness), top-level count
    inconsistency, tampered timestamps, or a non-positive duration.
    Returns False (legitimate invalidation, not an error) only for exact
    identity drift against a structurally valid request.
    """
    if not isinstance(receipt, dict):
        raise GateOrderingError("receipt is not an object")
    if receipt.get("schema") != RECEIPT_SCHEMA:
        raise GateOrderingError(
            f"unknown receipt schema (fail closed): {receipt.get('schema')!r}")
    if receipt.get("result") != "PASS":
        raise GateOrderingError(
            f"receipt result is not PASS (fail closed): {receipt.get('result')!r}")
    missing = [k for k in ("git_commit_sha", "suite", "environment")
               if k not in receipt]
    if missing:
        raise GateOrderingError(
            f"receipt missing identity fields (fail closed): {missing}")
    _validate_git_sha(receipt["git_commit_sha"], "receipt git_commit_sha")
    validate_suite_identity_values(receipt["suite"])
    validate_environment_authority(receipt["environment"])
    count = receipt.get("count")
    if not isinstance(count, int) or isinstance(count, bool) or count < 1:
        raise GateOrderingError(
            f"receipt count is not a positive integer (fail closed): {count!r}")
    if count != receipt["suite"]["count"]:
        raise GateOrderingError(
            "receipt top-level count disagrees with suite count (fail closed)")
    request = request_identity(request)
    started: object = receipt.get("started_unix")
    ended: object = receipt.get("ended_unix")
    for name, value in (("started_unix", started), ("ended_unix", ended)):
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise GateOrderingError(
                f"receipt {name} is malformed (fail closed): {value!r}")
    assert isinstance(started, (int, float)) and not isinstance(started, bool)
    assert isinstance(ended, (int, float)) and not isinstance(ended, bool)
    if ended < started or ended - started <= 0:
        raise GateOrderingError(
            "receipt duration is not positive (fail closed)")
    if receipt["git_commit_sha"] != request["git_commit_sha"]:
        return False  # head drift: legitimately invalidated, not an error
    if receipt["suite"] != request["suite"]:
        return False  # suite configuration drift
    if receipt["environment"] != request["environment"]:
        return False  # dependency/environment authority drift
    return True


def reuse_or_rerun(receipt: dict | None, request: dict) -> dict:
    """The reuse decision (advisory dedup, never a bypass)."""
    if receipt is None:
        return {"action": "run", "reason": "no receipt available"}
    try:
        if validate_receipt(receipt, request):
            return {"action": "reuse", "reason": "exact identity match"}
    except GateOrderingError as error:
        return {"action": "run", "reason": f"receipt unusable: {error}"}
    return {"action": "run",
            "reason": "identity drift (head, suite config, or environment)"}


# ---------------------------------------------------------------------------
# Phase 4 — hosted-CI exact-head status and independently bound handoff
# ---------------------------------------------------------------------------

def build_hosted_ci_status(git_commit_sha: str, run_id: str,
                           result: str = "SUCCESS",
                           run_url: str | None = None) -> dict:
    """Build a structured hosted-CI status bound to one exact head."""
    status: dict = {
        "schema": CI_STATUS_SCHEMA,
        "git_commit_sha": _validate_git_sha(git_commit_sha,
                                            "hosted-CI git_commit_sha"),
        "run_id": run_id,
        "result": result,
    }
    if run_url is not None:
        status["run_url"] = run_url
    validate_hosted_ci_status(status, git_commit_sha)
    return status


def validate_hosted_ci_status(status: dict, expected_sha: str) -> bool:
    """Mechanically bind a hosted-CI success to one exact head (fail closed).

    A bare boolean can never satisfy this: the status must carry the
    ``hosted-ci-exact-head-status`` schema, an exact git SHA, a nonempty run
    identity, and a ``SUCCESS`` result.  Malformed/missing/unknown fields
    raise; a well-formed status for a DIFFERENT SHA returns False (stale,
    not this head).
    """
    if not isinstance(status, dict):
        raise GateOrderingError("hosted-CI status is not an object")
    if status.get("schema") != CI_STATUS_SCHEMA:
        raise GateOrderingError(
            "unknown hosted-CI status schema (fail closed): "
            f"{status.get('schema')!r}")
    sha = _validate_git_sha(status.get("git_commit_sha"),
                            "hosted-CI status git_commit_sha")
    if status.get("result") != "SUCCESS":
        raise GateOrderingError(
            "hosted-CI result is not SUCCESS (fail closed): "
            f"{status.get('result')!r}")
    run_id = status.get("run_id")
    if not isinstance(run_id, str) or not run_id.strip():
        raise GateOrderingError(
            f"hosted-CI run identity is malformed (fail closed): {run_id!r}")
    if "run_url" in status:
        url = status["run_url"]
        if not isinstance(url, str) or not url.strip():
            raise GateOrderingError(
                f"hosted-CI run_url is malformed (fail closed): {url!r}")
    return sha == expected_sha


@dataclass(frozen=True)
class FinalHeadRequest:
    """An independently derived current/final-head request identity.

    NEVER constructed from the receipt under validation: the caller derives
    it from the repository (``current_final_head_request``) or from its own
    canonical request state.  Handoff compares every final gate against
    this one identity.
    """

    git_commit_sha: str
    suite: dict
    environment: dict

    def __post_init__(self) -> None:
        _validate_git_sha(self.git_commit_sha, "final-head git_commit_sha")
        validate_suite_identity_values(self.suite)
        validate_environment_authority(self.environment)

    def to_dict(self) -> dict:
        return {"git_commit_sha": self.git_commit_sha,
                "suite": self.suite, "environment": self.environment}


def _load_runner_module():
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import run_full_cpu_suite as runner  # noqa: PLC0415 (deferred, no cycle)
    return runner


def _runner_plan_and_config(root: Path, tests_dir: Path, jobs: int | None,
                            timeout: float,
                            retain_dir: Path | None) -> tuple[dict, dict]:
    """The runner's own deterministic plan + normalized suite config.

    Discovery imports must not dirty the tree being identified (no
    ``__pycache__``), so bytecode writing is suppressed for the duration.
    The runner's suite-config schema must agree with this module's
    doctrine constant or derivation fails closed.
    """
    runner = _load_runner_module()
    if getattr(runner, "SUITE_CONFIG_SCHEMA", None) != SUITE_CONFIG_SCHEMA:
        raise GateOrderingError(
            "runner suite-config schema disagrees with orchestration "
            f"doctrine (fail closed): {runner.SUITE_CONFIG_SCHEMA!r}")
    previous = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        payload = runner.plan(Path(root), Path(tests_dir), jobs)
        config = runner.suite_config_for(Path(root), Path(tests_dir), jobs,
                                         payload["jobs"], payload["tasks"],
                                         timeout, retain_dir)
    finally:
        sys.dont_write_bytecode = previous
    return payload, config


def _head_tracked_files(root: Path, rel_dir: str) -> frozenset[str]:
    """Every file under ``rel_dir`` tracked at the EXACT HEAD (fail closed).

    ``git ls-tree -r --name-only HEAD`` enumerates the committed tree —
    not the index and not the worktree — so an untracked or ignored file
    can never appear in this census.  A git failure fails closed.
    """
    proc = subprocess.run(
        ["git", "-C", str(root), "ls-tree", "-r", "--name-only", "-z",
         "HEAD", "--", rel_dir],
        capture_output=True, text=True)
    if proc.returncode != 0:
        raise GateOrderingError(
            f"git ls-tree HEAD census failed (fail closed): "
            f"{proc.stderr.strip()}")
    return frozenset(entry for entry in proc.stdout.split("\0") if entry)


def _git_path_ignored(root: Path, rel_path: str) -> bool:
    """Whether ``rel_path`` matches a Git ignore rule (fail closed on error).

    ``git check-ignore`` reports ignore RULES, independent of tracked
    status; exit 0 means ignored, exit 1 means not ignored, anything else
    is a git failure that must never be read as "not ignored".
    """
    proc = subprocess.run(
        ["git", "-C", str(root), "check-ignore", "-q", "--", rel_path],
        capture_output=True, text=True)
    if proc.returncode not in (0, 1):
        raise GateOrderingError(
            f"git check-ignore failed (fail closed): {proc.stderr.strip()}")
    return proc.returncode == 0


def _require_head_bound_tests_dir(root: Path, tests_dir: Path) -> None:
    """Fail-closed binding of a custom tests tree to the exact head.

    A clean ``git status --porcelain`` census does NOT prove that an
    arbitrary in-repo directory contains only HEAD-authorized content:
    ignored in-repo trees (``scratch/``, ``tmp/``, ``.cache/``, ...) are
    invisible to that census.  The mechanical HEAD-binding proof is:

    1. the effective tests directory lives inside the repository root
       (never under ``.git``) and is a real directory;
    2. the directory itself is not an ignored tree with no committed
       content (``git check-ignore`` + the HEAD census below) — an
       ignored in-repo tree can never claim exact-head authority;
    3. every test source module the runner's own discovery imports from
       that tree (``discover_units``, bytecode writing suppressed so the
       proof does not dirty the tree) must appear in the
       ``git ls-tree -r --name-only HEAD -- <tests-dir>`` census —
       untracked or ignored execution-relevant content cannot be
       authorized by the exact committed head;
    4. the ordinary clean-worktree prerequisite remains: every TRACKED
       file is byte-identical to ``HEAD`` (staged, unstaged, and
       untracked dirtiness all refuse).

    Together: everything the suite can execute from that tree is tracked
    at the exact HEAD and unmodified, so the exact committed head
    authorizes the executed contents.  An external or unprovable tests
    tree is REFUSED — never cached as though HEAD authorized it — before
    identity derivation, completion lookup, attach, or launch.
    """
    root, tests_dir = Path(root).resolve(), Path(tests_dir).resolve()
    try:
        relative = tests_dir.relative_to(root)
    except ValueError:
        raise GateOrderingError(
            "guarded tests directory must live inside the repository root "
            f"(fail closed): {tests_dir}") from None
    if relative.parts and relative.parts[0] == ".git":
        raise GateOrderingError(
            "guarded tests directory may not live under .git (fail closed)")
    if not tests_dir.is_dir():
        raise GateOrderingError(
            f"guarded tests directory is missing (fail closed): {tests_dir}")
    rel_dir = relative.as_posix()
    tracked = _head_tracked_files(root, rel_dir)
    if _git_path_ignored(root, rel_dir) and not tracked:
        raise GateOrderingError(
            f"guarded tests directory is ignored by Git and untracked at "
            f"HEAD (fail closed): {rel_dir} — an ignored in-repo tree is "
            "invisible to the clean-worktree census and can never prove "
            "exact-head authority")
    runner = _load_runner_module()
    previous = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        try:
            units = runner.discover_units(root, tests_dir)
        except Exception as error:  # runner SuiteError -> fail closed
            raise GateOrderingError(
                f"guarded tests-tree discovery failed (fail closed): "
                f"{error}") from error
    finally:
        sys.dont_write_bytecode = previous
    for unit in units:
        module_rel = (relative / f"{unit.name}.py").as_posix()
        if module_rel not in tracked:
            raise GateOrderingError(
                f"discovered guarded tests module is not tracked at HEAD — "
                "untracked or ignored execution-relevant content can never "
                f"be authorized by the exact committed head (fail closed): "
                f"{module_rel}")


def canonical_suite_config(root: Path, tests_dir: Path | None = None, *,
                           jobs: int | None = None,
                           timeout: float = CANONICAL_TIMEOUT_SECONDS,
                           retain_dir: Path | None = None) -> dict:
    """The normalized execution configuration for one request (fail closed).

    Requires a clean committed worktree, binds a custom tests directory
    to the exact head, and derives the configuration (effective tests
    directory, requested/effective jobs, deterministic task-plan digest,
    timeout, retention) from the runner's own plan of that exact tree.
    """
    root = Path(root).resolve()
    _require_clean_committed_worktree(root)
    effective = Path(tests_dir or root / "tests").resolve()
    if _inside_git_work_tree(root):
        _require_head_bound_tests_dir(root, effective)
    _, config = _runner_plan_and_config(root, effective, jobs, timeout,
                                        retain_dir)
    _validate_suite_config(config)
    return config


def current_final_head_request(root: Path, *, tests_dir: Path | None = None,
                               jobs: int | None = None,
                               timeout: float = CANONICAL_TIMEOUT_SECONDS,
                               retain_dir: Path | None = None) -> FinalHeadRequest:
    """Independently derive the CURRENT final-head request identity.

    Requires a clean git worktree (the head must be a real committed head),
    takes the exact SHA from git, the suite identity from the runner's own
    canonical plan of that worktree under the CANONICAL final-validation
    configuration (default tests directory ``root/tests``, default jobs
    schedule, default per-task timeout, no retained-artifact request —
    callers deriving the canonical final head pass no overrides), and the
    environment authority hashes.  The normalized suite configuration is
    part of the identity: a suite run under a different jobs/tests/
    timeout/retention configuration can never satisfy this request even
    when it discovers the same test IDs.
    """
    root = Path(root).resolve()
    if not git_tree_clean(root):
        raise GateOrderingError(
            "refusing final-head request identity on dirty worktree "
            "(fail closed)")
    effective = Path(tests_dir or root / "tests").resolve()
    if _inside_git_work_tree(root):
        _require_head_bound_tests_dir(root, effective)
    payload, config = _runner_plan_and_config(root, effective, jobs, timeout,
                                              retain_dir)
    suite = {
        "runner_schema": RUNNER_SCHEMA,
        "suite_command": list(FULL_SUITE_COMMAND),
        "suite_config": config,
        "serial_digest": payload["identity_digest"],
        # Plan-time identity: serial discovery is the population authority.
        # A COMPLETED receipt must additionally carry the runner-proven
        # executed digest, which the runner proves equal to serial.
        "executed_digest": payload["identity_digest"],
        "count": payload["count"],
    }
    return FinalHeadRequest(
        git_commit_sha=git_commit_sha(root),
        suite=suite,
        environment=environment_identity(root),
    )


def handoff_gate_status(final_head: FinalHeadRequest,
                        suite_receipt: dict | None,
                        hosted_ci_status: dict | None,
                        finalizer_ok: bool) -> dict:
    """Final handoff decision (fail closed).

    Every required final gate is proven against the ONE independently
    supplied final-head identity.  The suite receipt is validated against
    ``final_head`` — never against identity extracted from the receipt —
    and hosted-CI success must be mechanically bound to the same exact SHA
    through a structured status.  Adversarial review alone can never mark
    handoff complete.
    """
    if not isinstance(final_head, FinalHeadRequest):
        raise GateOrderingError(
            "handoff requires an independently derived FinalHeadRequest "
            "(fail closed)")
    suite_ok = False
    if suite_receipt is not None:
        # Malformed receipts RAISE (visible fail-closed rejection), never
        # silently degrade to a quiet False.
        suite_ok = validate_receipt(suite_receipt, final_head.to_dict())
    ci_ok = False
    if hosted_ci_status is not None:
        # A bare boolean cannot satisfy this: the structured status must
        # carry schema + exact SHA + SUCCESS + run identity, and a
        # malformed one raises instead of degrading.
        ci_ok = validate_hosted_ci_status(hosted_ci_status,
                                          final_head.git_commit_sha)
    ok = bool(suite_ok and ci_ok and finalizer_ok)
    return {
        "schema": SCHEMA,
        "handoff_complete": ok,
        "final_head_sha": final_head.git_commit_sha,
        "full_suite_receipt_valid": suite_ok,
        "hosted_ci_success": ci_ok,
        "finalizer_status_ok": finalizer_ok,
        "note": ("all final gates must bind to the one independently "
                 "supplied final-head identity; review GO verdicts are "
                 "necessary but never sufficient"),
    }


# ---------------------------------------------------------------------------
# Phase 2 — duplicate-launch prevention on the canonical invocation path
# ---------------------------------------------------------------------------

def _inside_git_work_tree(root: Path) -> bool:
    probe = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--is-inside-work-tree"],
        capture_output=True, text=True)
    return probe.returncode == 0 and probe.stdout.strip() == "true"


def git_tree_clean(root: Path) -> bool:
    return _git_output(root, "status", "--porcelain") == ""


def _require_clean_committed_worktree(root: Path) -> None:
    """The guard's clean-worktree doctrine (Issue #213 correction pass).

    Mirrors the runner's ``ensure_clean_git_worktree`` exactly — same
    ``git rev-parse --is-inside-work-tree`` probe, same ``git status
    --porcelain`` census (staged, unstaged, and untracked dirtiness all
    count), same fail-closed behavior when ``git status`` fails inside a
    real work tree — so the guard cannot diverge from the runner's own
    semantics.  A plain non-Git fixture root keeps the runner's existing
    unguarded behavior.
    """
    if not _inside_git_work_tree(root):
        return
    status = subprocess.run(
        ["git", "-C", str(root), "status", "--porcelain"],
        capture_output=True, text=True)
    if status.returncode != 0:
        # Fail closed exactly as the runner does: a git failure inside a
        # real work tree must never be treated as a clean tree.
        raise GateOrderingError(
            f"git status failed inside a work tree (fail closed): "
            f"{status.stderr.strip()}")
    if status.stdout:
        raise GateOrderingError(
            "refusing guarded full-suite request on dirty Git worktree "
            "(fail closed): commit or stash before deriving the launch "
            "identity, consulting a completion, attaching, or launching")


def launch_request_identity(root: Path, tests_dir: Path | None = None, *,
                            jobs: int | None = None,
                            timeout: float = CANONICAL_TIMEOUT_SECONDS,
                            retain_dir: Path | None = None) -> dict:
    """Mechanically derived (head, suite-config, environment) launch identity.

    The key authority is the exact repository SHA, the canonical suite
    population identity (runner plan digest + count + canonical command +
    the NORMALIZED SUITE CONFIGURATION: effective tests directory,
    requested/effective jobs, deterministic task-plan digest, timeout,
    retention request), and the required environment authority hashes.
    An arbitrary caller-supplied lock key is never accepted anywhere in
    this module.

    A Git worktree MUST be clean and committed BEFORE the identity is
    derived: the guard's clean-worktree doctrine is the runner's own
    (``ensure_clean_git_worktree`` — same ``git status --porcelain``
    census, same fail-closed behavior on git failure inside a real work
    tree), applied here so that a dirty tree is REFUSED before any
    completion lookup, attach, or launch can occur.  A dirty worktree is
    never merely another cache-key component: the runner contract
    requires a committed exact head.  For a Git-backed guarded request a
    custom tests directory must additionally be provably bound to that
    exact head (``_require_head_bound_tests_dir``: inside the repository
    root, not under ``.git``, not an ignored untracked tree, and every
    discovered test module tracked at HEAD) — an external or unprovable
    tests tree fails closed.
    """
    root = Path(root).resolve()
    _require_clean_committed_worktree(root)
    effective = Path(tests_dir or root / "tests").resolve()
    if _inside_git_work_tree(root):
        _require_head_bound_tests_dir(root, effective)
    payload, config = _runner_plan_and_config(root, effective, jobs, timeout,
                                              retain_dir)
    identity = {
        "schema": LAUNCH_IDENTITY_SCHEMA,
        "git_commit_sha": git_commit_sha(root),
        "suite": {
            "runner_schema": RUNNER_SCHEMA,
            "suite_command": list(FULL_SUITE_COMMAND),
            "suite_config": config,
            "serial_digest": payload["identity_digest"],
            "executed_digest": payload["identity_digest"],
            "count": payload["count"],
        },
        "environment": environment_identity(root),
    }
    launch_request_key(identity)  # structural self-check (fail closed)
    return identity


def launch_request_key(identity: dict) -> str:
    """Deterministic identity key, valid ONLY for derived identities."""
    if not isinstance(identity, dict):
        raise GateOrderingError(
            "launch identity must be an object (fail closed)")
    if identity.get("schema") != LAUNCH_IDENTITY_SCHEMA:
        raise GateOrderingError(
            "launch identity must come from launch_request_identity(); "
            "arbitrary caller-supplied keys are not authority (fail closed)")
    _validate_git_sha(identity.get("git_commit_sha"),
                      "launch identity git_commit_sha")
    validate_suite_identity_values(identity.get("suite"))
    validate_environment_authority(identity.get("environment"))
    canonical = json.dumps(
        {"git_commit_sha": identity["git_commit_sha"],
         "suite": identity["suite"], "environment": identity["environment"]},
        sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _default_guard_dir() -> Path:
    # Outside any worktree on purpose: guard state must never dirty the
    # tree the runner is about to validate (same workspace parent contract
    # as the runner itself).
    parent = Path(os.environ.get(
        "INFER_SWARM_SUITE_TMPDIR", str(Path.home() / ".cache")))
    return parent.resolve() / "suite-launch-guard"


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists, owned by another user
    return True


class LaunchGuard:
    """One live suite process per launch identity on this host.

    Synchronization is an atomically-created (``O_CREAT | O_EXCL``) lock
    file recording the PID and command of the single live launch, plus a
    bounded per-identity completion receipt written by the owner when the
    underlying suite returns.  Races between concurrent starters are
    handled explicitly: losers of the atomic create re-read and ATTACH.
    A malformed lock fails closed; a holder is replaced only when
    mechanically proven dead (``os.kill(pid, 0)`` -> ESRCH).  The recorded
    PID is the process that actually invokes the suite — never a parent
    that could exit while an untracked suite child remains.
    """

    def __init__(self, identity: dict, lock_dir: Path | None = None,
                 poll_seconds: float = 0.05):
        self.identity = identity
        self.key = launch_request_key(identity)
        self.root = Path(lock_dir) if lock_dir is not None else _default_guard_dir()
        self.poll_seconds = poll_seconds

    def lock_path(self) -> Path:
        return self.root / f"launch-{self.key}.lock"

    def completion_path(self) -> Path:
        return self.root / f"completion-{self.key}.json"

    def _read_lock(self) -> dict | None:
        """Read and shape-validate the lock payload; None if unreadable."""
        try:
            raw = self.lock_path().read_text(encoding="utf-8")
        except OSError:
            return None
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return None
        if (not isinstance(payload, dict)
                or payload.get("schema") != LAUNCH_LOCK_SCHEMA
                or not isinstance(payload.get("pid"), int)
                or isinstance(payload.get("pid"), bool)
                or not isinstance(payload.get("command"), list)
                or not isinstance(payload.get("acquired_unix"), (int, float))
                or isinstance(payload.get("acquired_unix"), bool)):
            return None
        return payload

    def find_valid_completion(self, *, allow_fail: bool = False) -> dict | None:
        """Return a mechanically valid completion for THIS identity.

        Malformed completion content fails closed; an expired completion is
        ignored (bounded liveness, will be overwritten by the next owner).
        By default only a PASS completion (a validated canonical runner
        result proven against this launch identity) is returned: a
        completed FAIL is never a reusable PASS.  ``allow_fail=True`` is
        the concurrent-attacher path — the bounded completed failure is
        delivered to a request that already attached to the live launch,
        never to a later independent invocation.
        """
        path = self.completion_path()
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        self._validate_completion(record)
        if not allow_fail and not record["ok"]:
            return None
        try:
            age = time.time() - path.stat().st_mtime
        except OSError:
            return None
        if age > COMPLETION_MAX_AGE_SECONDS:
            return None
        return record

    def _validate_completion(self, record: object) -> None:
        """Structural completion contract (fail closed on every field).

        A completion suppresses an actual full-suite launch, so a matched
        key, a matched SHA, ``result`` being any dict, and ``ok`` being
        any boolean never authorize reuse on their own.  The embedded
        runner result must be a canonical full-suite runner payload whose
        outcome agrees with the record's ``ok`` flag; a PASS additionally
        binds its count, serial/executed digests, AND ITS NORMALIZED SUITE
        CONFIGURATION to THIS launch identity's suite (a result produced
        under a different jobs/tests/timeout/retention configuration can
        never satisfy this request).
        """
        if not isinstance(record, dict) or record.get("schema") != COMPLETION_SCHEMA:
            raise GateOrderingError(
                f"malformed suite completion receipt (fail closed): "
                f"{self.completion_path()}")
        if record.get("key") != self.key:
            raise GateOrderingError(
                "completion receipt bound to a different launch identity "
                f"(fail closed): {self.completion_path()}")
        if record.get("git_commit_sha") != self.identity["git_commit_sha"]:
            raise GateOrderingError(
                "completion receipt head mismatch (fail closed)")
        ok = record.get("ok")
        if not isinstance(ok, bool):
            raise GateOrderingError(
                "completion receipt outcome malformed (fail closed)")
        result = record.get("result")
        # A canonical runner result is required — any dict is not enough.
        result = self._validated_runner_result(result, require_pass=ok)
        if result["ok"] is not ok:
            raise GateOrderingError(
                "completion receipt ok flag disagrees with the embedded "
                "runner result (fail closed)")
        if ok:
            # A reusable PASS binds the runner-proven population AND the
            # executed suite configuration to THIS launch identity's
            # suite: exact count, exact digest, exact configuration.
            if result["count"] != self.identity["suite"]["count"]:
                raise GateOrderingError(
                    "completion receipt runner count differs from the "
                    "launch identity suite count (fail closed)")
            if (result["serial_digest"] != self.identity["suite"]["serial_digest"]
                    or result["executed_digest"]
                    != self.identity["suite"]["executed_digest"]):
                raise GateOrderingError(
                    "completion receipt runner digests differ from the "
                    "launch identity suite population digest (fail closed)")
            if result.get("suite_config") != \
                    self.identity["suite"]["suite_config"]:
                raise GateOrderingError(
                    "completion receipt suite configuration differs from "
                    "the launch identity configuration (fail closed)")
        started: object = record.get("started_unix")
        ended: object = record.get("ended_unix")
        for name, value in (("started_unix", started), ("ended_unix", ended)):
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise GateOrderingError(
                    f"completion receipt {name} malformed (fail closed)")
        assert isinstance(started, (int, float)) and not isinstance(started, bool)
        assert isinstance(ended, (int, float)) and not isinstance(ended, bool)
        if ended < started:
            raise GateOrderingError(
                "completion receipt timestamps inverted (fail closed)")

    def _validated_runner_result(self, result: object,
                                 *, require_pass: bool) -> dict:
        """Require a canonical full-suite runner result payload (fail closed).

        Known runner schema, ``ok`` a real boolean, positive integer
        count, and 64-hex serial/executed digests.  For a PASS
        (``require_pass=True`` — the only outcome that may authorize
        reuse) the serial and executed digests must additionally be EQUAL:
        that equality is the runner's own pass-closed proof that the
        executed population matched the serial discovery, and the runner
        emits it only on success.  Malformed, missing, or forged fields
        reject.
        """
        if not isinstance(result, dict):
            raise GateOrderingError(
                "completion receipt result payload malformed (fail closed)")
        if result.get("schema") != RUNNER_SCHEMA:
            raise GateOrderingError(
                "completion receipt result is not a canonical runner "
                f"result (fail closed): {result.get('schema')!r}")
        ok = result.get("ok")
        if not isinstance(ok, bool) or ok is not require_pass:
            raise GateOrderingError(
                "completion receipt runner result ok is malformed or "
                f"disagrees with the declared outcome (fail closed): {ok!r}")
        count = result.get("count")
        if not isinstance(count, int) or isinstance(count, bool) or count < 1:
            raise GateOrderingError(
                "completion receipt runner result count is not a positive "
                f"integer (fail closed): {count!r}")
        serial = result.get("serial_digest")
        executed = result.get("executed_digest")
        if not isinstance(serial, str) or not _SHA256_RE.fullmatch(serial):
            raise GateOrderingError(
                "completion receipt runner result serial_digest is malformed "
                f"(fail closed): {serial!r}")
        if ok:
            if not isinstance(executed, str) or not _SHA256_RE.fullmatch(executed):
                raise GateOrderingError(
                    "completion receipt runner result executed_digest is "
                    f"malformed (fail closed): {executed!r}")
            if serial != executed:
                raise GateOrderingError(
                    "completion receipt runner result serial/executed "
                    "digests differ on a PASS (fail closed)")
        elif executed is not None and (not isinstance(executed, str)
                                        or not _SHA256_RE.fullmatch(executed)):
            # A runner FAIL carries either the serial digest of the
            # discovered population or no executed digest at all (the
            # executed-ID proof failed); anything else is malformed.
            raise GateOrderingError(
                "completion receipt runner result executed_digest is "
                f"malformed (fail closed): {executed!r}")
        return result

    def acquire_or_attach(self, *, accept_completion: bool = True) -> dict:
        """Return ``{"attached": bool, ...}`` for one logical launch request.

        ``attached=False`` — the caller OWNS the single live launch for
        this identity on this host.  ``attached=True`` — a live owner
        process is already running this exact identity; the caller must
        wait on its completion, never start a second suite.  Malformed or
        unprovably-stale state fails closed with ``GateOrderingError``.
        ``accept_completion=False`` skips the sequential completion-reuse
        path (used by the retention policy: a completion whose requested
        retained artifacts are not mechanically present must be rerun).
        """
        self.root.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + LAUNCH_GUARD_TIMEOUT_SECONDS
        while True:
            completed = (self.find_valid_completion()
                         if accept_completion else None)
            if completed is not None:
                return {"attached": True, "completed": True,
                        "pid": None, "result": completed["result"],
                        "key": self.key}
            if self.lock_path().exists():
                meta = self._read_lock()
                if meta is not None:
                    try:
                        age = time.time() - self.lock_path().stat().st_mtime
                    except OSError:
                        age = float("inf")
                    if age < LOCK_WRITE_GRACE_SECONDS and not _alive(meta["pid"]):
                        # Just-created lock whose payload may still be
                        # landing, or the owner died within the grace
                        # window; re-read before deciding.
                        time.sleep(self.poll_seconds)
                        continue
                    if not _alive(meta["pid"]):
                        # Mechanically proven stale: the holder is gone.
                        try:
                            self.lock_path().unlink()
                        except OSError as error:
                            raise GateOrderingError(
                                f"cannot prune proven-stale launch lock "
                                f"(fail closed): {error}") from error
                        continue
                    if meta["key"] != self.key:
                        raise GateOrderingError(
                            "launch lock key mismatch (fail closed)")
                    acquired_age = time.time() - meta["acquired_unix"]
                    if acquired_age > LAUNCH_GUARD_TIMEOUT_SECONDS:
                        # Alive but beyond any legitimate suite wall: the
                        # holder may be an unrelated PID-reuse victim.
                        # Cannot prove stale => fail closed.
                        raise GateOrderingError(
                            "launch lock held past the suite wall without "
                            "completing; cannot prove staleness (fail "
                            f"closed): {self.lock_path()}")
                    return {"attached": True, "completed": False,
                            "pid": meta["pid"], "key": self.key}
                # Unreadable/malformed lock.
                try:
                    age = time.time() - self.lock_path().stat().st_mtime
                except OSError:
                    age = float("inf")
                if age < LOCK_WRITE_GRACE_SECONDS:
                    time.sleep(self.poll_seconds)
                    continue
                raise GateOrderingError(
                    f"malformed launch lock (fail closed): {self.lock_path()}")
            if time.monotonic() > deadline:
                raise GateOrderingError(
                    "launch guard exceeded its wait wall (fail closed)")
            # Atomic create: exactly one concurrent starter wins.
            payload = {
                "schema": LAUNCH_LOCK_SCHEMA,
                "key": self.key,
                "pid": os.getpid(),
                "command": [sys.executable, SUITE_RUNNER, "--json"],
                "acquired_unix": time.time(),
            }
            try:
                fd = os.open(str(self.lock_path()),
                             os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
            except FileExistsError:
                continue  # lost the create race; re-read and attach
            try:
                os.write(fd, json.dumps(payload, sort_keys=True).encode())
            finally:
                os.close(fd)
            return {"attached": False, "completed": False,
                    "pid": os.getpid(), "key": self.key}

    def release(self) -> None:
        try:
            self.lock_path().unlink()
        except FileNotFoundError:
            pass

    def write_completion(self, result: dict, started_unix: float) -> None:
        record = {
            "schema": COMPLETION_SCHEMA,
            "key": self.key,
            "git_commit_sha": self.identity["git_commit_sha"],
            "ok": bool(result.get("ok")),
            "result": result,
            "started_unix": started_unix,
            "ended_unix": time.time(),
        }
        self._validate_completion(record)
        temporary = self.completion_path().with_suffix(".json.tmp")
        temporary.write_text(json.dumps(record, sort_keys=True),
                             encoding="utf-8")
        temporary.replace(self.completion_path())


def _retained_artifacts_present(retain_dir: Path,
                                task_count: int) -> bool:
    """Mechanically prove the documented retained artifact set is present.

    A cached run can satisfy a ``--retain-dir`` request ONLY when the
    requested directory already contains every documented per-task
    artifact (assignment, expected-IDs, receipt, captured stdout/stderr)
    for every task of the completed run plus ``summary.json``.  This is a
    presence check against the exact retained set — never a generalized
    artifact cache.
    """
    retain_dir = Path(retain_dir)
    if not (retain_dir / "summary.json").is_file():
        return False
    for index in range(task_count):
        for suffix in ("-modules.json", "-expected.json", ".json",
                       "-stdout.txt", "-stderr.txt"):
            if not (retain_dir / f"task-{index}{suffix}").is_file():
                return False
    return True


def run_single_head_suite(root: Path, *, tests_dir: Path | None = None,
                          timeout: float = CANONICAL_TIMEOUT_SECONDS,
                          jobs: int | None = None,
                          retain_dir: Path | None = None,
                          suite_command=None,
                          lock_dir: Path | None = None) -> dict:
    """The canonical single-launch seam (wired into the runner CLI).

    Exactly ONE real suite process runs per logical
    ``(head, suite-config, environment-authority)`` request on a host:

    * the first request acquires the guard and invokes the suite;
    * a concurrent identical request ATTACHES, waits for the owner's
      bounded completion receipt, and consumes the mechanically validated
      result instead of launching;
    * an identical request arriving right after completion consumes the
      bounded completion receipt (capped liveness, not a persistent
      cache);
    * distinct head/config/environment identities never share results
      (distinct deterministic keys) — the normalized suite configuration
      (effective tests directory, requested/effective jobs, task-plan
      digest, timeout, retention request) is part of the key, so a
      request under a different configuration can never consume another
      configuration's completion;
    * non-git roots have no exact-head identity and run unguarded, exactly
      like the runner's own git doctrine.

    ``tests_dir`` restores the pre-#213 execution contract
    (``run_suite(root, tests_dir, ...)``): the guarded path executes the
    requested tests tree, and the launch identity is derived from the
    SAME effective tests directory.  A custom tests directory is never
    silently normalized back to ``root/tests``.  For a Git-backed guarded
    request the tests tree must be provably bound to the exact committed
    head (``_require_head_bound_tests_dir``: inside the repository root,
    not under ``.git``, not an ignored untracked tree, and every
    discovered test module tracked at HEAD): an unsafe or unprovable
    external tree fails closed rather than being cached as though HEAD
    authorized its contents.

    Retention policy (smallest safe policy, no generalized artifact
    cache): a non-retained completion can never silently satisfy a
    ``--retain-dir`` request.  Sequential cached-PASS reuse is disabled
    when satisfying the request would omit the requested retained
    per-task artifacts; the request performs a fresh underlying suite run
    unless the exact documented artifact set is mechanically proven
    present and compatible.  Concurrent identical requests that share the
    same retention request may deduplicate normally.

    If the underlying suite raises, no completion is written: waiters fail
    closed and the next identical request launches fresh.

    A guarded request (Git checkout) REFUSES a dirty worktree up front —
    before the launch identity is derived, before any completion is
    consulted, before attaching, before launching (the runner's own
    ``ensure_clean_git_worktree`` doctrine; a dirty tree is never just
    another cache-key component).  Completion policy: a validated PASS
    completion is consumed by identical requests within the bounded
    window; a completed FAIL is delivered ONLY to requests that already
    attached to the live launch — a later independent invocation reruns
    the suite (a FAIL never suppresses a fresh launch).
    """
    root = Path(root).resolve()
    effective_tests = Path(tests_dir or root / "tests").resolve()

    def _invoke() -> dict:
        if suite_command is not None:
            return suite_command()
        runner = _load_runner_module()
        return runner.run_suite(root, effective_tests, jobs=jobs,
                                timeout=timeout, retain_dir=retain_dir)

    if not _inside_git_work_tree(root):
        return _invoke()
    # Clean committed worktree BEFORE identity derivation, completion
    # lookup, attach, or launch (fail closed exactly like the runner);
    # a Git-backed custom tests tree must be head-bound (fail closed).
    _require_clean_committed_worktree(root)
    _require_head_bound_tests_dir(root, effective_tests)
    identity = launch_request_identity(root, effective_tests, jobs=jobs,
                                       timeout=timeout,
                                       retain_dir=retain_dir)
    guard = LaunchGuard(identity, lock_dir=lock_dir,
                        poll_seconds=0.02 if suite_command is not None else 0.05)
    accept_completion = True
    if retain_dir is not None:
        # Retention request: sequential reuse of a possibly non-retained
        # PASS is allowed ONLY when the requested directory mechanically
        # proves the full documented per-task artifact set (plus the
        # summary); otherwise a fresh underlying run produces them.
        completed = guard.find_valid_completion()
        if completed is not None:
            task_count = len(completed["result"].get("tasks") or [])
            accept_completion = _retained_artifacts_present(
                Path(retain_dir), task_count)
    outcome = guard.acquire_or_attach(accept_completion=accept_completion)
    if outcome["attached"]:
        if outcome["completed"]:
            return outcome["result"]
        return _await_completion(guard, outcome["pid"])
    started = time.time()
    try:
        result = _invoke()
    except BaseException:
        # No completion receipt: concurrent waiters fail closed, and the
        # next identical request legitimately launches fresh.
        guard.release()
        raise
    guard.write_completion(result, started)
    guard.release()
    return result


def _await_completion(guard: LaunchGuard, owner_pid: int) -> dict:
    """Wait behind the live owner; fail closed if it dies without receipt.

    This request already ATTACHED to the live launch, so the bounded
    completed outcome — PASS or FAIL — is delivered as the one real
    result of the single underlying launch.  A FAIL is never a reusable
    PASS: only ``find_valid_completion()`` (the pre-attach reuse path)
    filters to PASS-only.
    """
    deadline = time.monotonic() + LAUNCH_GUARD_TIMEOUT_SECONDS
    while True:
        completed = guard.find_valid_completion(allow_fail=True)
        if completed is not None:
            return completed["result"]
        if not _alive(owner_pid):
            raise GateOrderingError(
                "launch owner exited without a completion receipt "
                "(fail closed)")
        if time.monotonic() > deadline:
            raise GateOrderingError(
                "timed out waiting behind the live suite launch "
                "(fail closed)")
        time.sleep(guard.poll_seconds)


# ---------------------------------------------------------------------------
# Phase 6 — old-vs-new trace comparison
# ---------------------------------------------------------------------------

def trace_campaign(old_order: bool, review_mutates_head: bool = True,
                   review_critical: tuple[str, ...] = ()) -> dict:
    """Synthetic trace of expensive-gate EXECUTIONS under one ordering.

    ``old_order=True``  models the #210/PR-#212 sequence: full suite +
      hosted CI BEFORE review; review mutates the head; both run AGAIN.
    ``old_order=False`` is the canonical ordering.  A review-critical gate
      that ran pre-review contributes a second physical execution only
      when review mutated the head; without mutation the exact-head result
      is reused and counted once.
    """
    gates = ("full-cpu-suite", "hosted-exact-head-ci")
    if old_order:
        executions = {g: (2 if review_mutates_head else 1) for g in gates}
    else:
        critical = set(review_critical)
        executions = {
            g: 1 + (1 if g in critical and review_mutates_head else 0)
            for g in gates}
    return {
        "schema": SCHEMA,
        "old_order": old_order,
        "review_mutates_head": review_mutates_head,
        "review_critical": sorted(review_critical),
        "expensive_gate_executions": executions,
        "total_expensive_executions": sum(executions.values()),
        "final_validation_cycles": 1,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--trace", action="store_true",
                        help="print the old-vs-new ordering trace")
    args = parser.parse_args(argv)
    if args.trace:
        old = trace_campaign(True)
        new = trace_campaign(False)
        rc_mutation = trace_campaign(False, True, ("full-cpu-suite",))
        rc_reuse = trace_campaign(False, False, ("full-cpu-suite",))
        print(json.dumps({"old": old, "new": new,
                          "new_review_critical_mutation": rc_mutation,
                          "new_review_critical_reuse": rc_reuse},
                         indent=2, sort_keys=True))
        return 0
    print(json.dumps({"schema": SCHEMA, "ok": True}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
