#!/usr/bin/env python3
"""Issue #213 — campaign validation gate ordering and exact-head receipts.

Repository-owned orchestration semantics for physical/research campaign
handoff.  Two concerns live here:

1. **Gate ordering doctrine (machine-checked).**  ``CampaignFlow`` /
   ``plan_campaign_gates`` model a campaign as the pre-review phase (cheap,
   reviewer-trust-building gates) followed by the final-head phase (the one
   full-suite + one hosted-CI run on the final reviewed head).  Adversarial
   review runs against the frozen pre-review head and MUST NOT request the
   expensive gates unless the campaign explicitly declares them
   review-critical.  Any unknown gate or workflow state fails closed to the
   existing broader behavior (fresh full validation).

2. **Exact-head suite receipts (Phase 3).**  ``SuiteReceipt`` binds a
   successful full-suite run to the exact repository SHA, the canonical
   suite identity (runner schema + serial identity digest of the executed
   population + test count), the environment authority identity, and
   start/end timestamps.  ``validate_receipt`` fails closed: a failed,
   cancelled, incomplete, drifted, or tampered receipt can never satisfy
   the final-head gate, and reuse is authorized only when every identity
   field matches the request exactly.

The duplicate-launch guard (Phase 2) is a cooperative single-launch lock
(``LaunchLock``): one logical final-head suite request launches at most one
suite process per head/config; a second concurrent request ATTACHES to the
running process (or fails closed when the lock is stale/broken) rather than
starting a second suite.  The lock deliberately does not survive host
reboots (tmpfs) — a vanished lock means a vanished process, which correctly
requires a fresh launch decision, never silent reuse.

This module is orchestration metadata tooling, NOT a hash-pinned evidence
producer and NOT a persistent result cache: receipts are advisory
deduplication records whose reuse the doctrine may permit; they never
replace the run itself when policy requires fresh validation.

Fail-closed posture throughout: every ambiguity (unknown gate name, missing
identity field, malformed lock, non-success result, mismatched digest)
rejects rather than warns.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

SCHEMA = "campaign-gate-ordering/1"
RECEIPT_SCHEMA = "exact-head-suite-receipt/1"

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


class GateOrderingError(RuntimeError):
    """A fail-closed gate-ordering or receipt validation failure."""


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

    The plan schedules each expensive gate exactly once on the final head,
    regardless of whether review mutated the head.  Review-critical
    exceptions are the only gates that may run pre-review, and they still
    re-run on the final head when review mutates it (an exact-head gate
    bound to a superseded SHA is void).
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
                "gates": list(flow.final_head),
                "note": ("one full CPU suite + one hosted exact-head CI on "
                         "the final reviewed head"),
            },
        ],
        "review_critical": list(flow.review_critical),
        "review_mutates_head": review_mutates_head,
    }
    expensive_cycles = len(set(flow.final_head) & REVIEW_CRITICAL_EXCEPTIONS)
    if flow.review_critical:
        # A review-critical gate runs pre-review by explicit declaration;
        # head mutation voids its exact-head binding, so it runs again on
        # the final head (counted, never hidden).
        plan["phases"][0]["gates"] = sorted(
            set(flow.pre_review) | set(flow.review_critical))
        if review_mutates_head:
            plan["note_review_critical"] = (
                "review-critical gates ran pre-review by declaration and "
                "RE-RUN on the final head because review mutated it")
    plan["expensive_validation_cycles"] = (
        expensive_cycles + len(flow.review_critical) if review_mutates_head
        else expensive_cycles)
    # Exactness check: the expensive final-head gates must appear exactly
    # once each in the scheduled plan (fail closed on duplication).
    scheduled = [g for phase in plan["phases"] for g in phase["gates"]]
    for gate in flow.final_head:
        occurrences = scheduled.count(gate)
        min_expected = 1 + (1 if gate in flow.review_critical and
                            review_mutates_head else 0)
        if occurrences != min_expected:
            raise GateOrderingError(
                f"expensive gate {gate!r} scheduled {occurrences}x, "
                f"expected exactly {min_expected}")
    return plan


def handoff_gate_status(receipt: dict | None, hosted_ci_success: bool,
                        finalizer_ok: bool) -> dict:
    """Final handoff decision (fail closed).

    Adversarial review alone can never mark handoff complete: the final-head
    full-suite receipt and hosted-CI success are mandatory wherever policy
    requires them (this doctrine preserves that requirement).
    """
    suite_ok = False
    if receipt is not None:
        try:
            suite_ok = validate_receipt(receipt, request_identity(receipt))
        except GateOrderingError:
            suite_ok = False
    ok = bool(suite_ok and hosted_ci_success and finalizer_ok)
    return {
        "schema": SCHEMA,
        "handoff_complete": ok,
        "full_suite_receipt_valid": suite_ok,
        "hosted_ci_success": hosted_ci_success,
        "finalizer_status_ok": finalizer_ok,
        "note": ("review GO verdicts are necessary but never sufficient; "
                 "expensive final-head gates remain mandatory"),
    }


# ---------------------------------------------------------------------------
# Phase 2 — duplicate-launch prevention (cooperative single-launch lock)
# ---------------------------------------------------------------------------

@dataclass
class LaunchLock:
    """One live suite process per (head, suite identity) on this host.

    The lock directory lives under the suite workspace parent (tmpfs-class
    scratch by default) and records the PID and command of the single live
    launch.  A vanished process releases the lock (stale locks are pruned
    after verifying with ``os.kill(pid, 0)``); a broken/malformed lock file
    fails closed — the caller must NOT launch a second suite process.
    """

    root: Path
    key: str
    poll_seconds: float = 0.05
    _meta: dict = field(default_factory=dict, init=False, repr=False)

    def path(self) -> Path:
        return self.root / f"suite-launch-{self.key}.lock"

    def _read_meta(self) -> dict | None:
        try:
            payload = json.loads(self.path().read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if (not isinstance(payload, dict)
                or not isinstance(payload.get("pid"), int)
                or not isinstance(payload.get("command"), list)):
            return None
        return payload

    @staticmethod
    def _alive(pid: int) -> bool:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True  # exists, owned by another user
        return True

    def acquire_or_attach(self, command: list[str]) -> dict:
        """Return ``{"attached": bool, ...}`` for one logical launch request.

        ``attached=False`` means the caller OWNS the launch (lock created);
        ``attached=True`` means an existing live process is already running
        this head/config and the caller must wait on it, not launch again.
        A malformed/unreadable-but-present lock fails closed with
        ``GateOrderingError``.
        """
        self.root.mkdir(parents=True, exist_ok=True)
        lock_path = self.path()
        if lock_path.exists():
            meta = self._read_meta()
            if meta is None:
                raise GateOrderingError(
                    f"malformed launch lock (fail closed): {lock_path}")
            if self._alive(meta["pid"]):
                if meta["command"] != command:
                    raise GateOrderingError(
                        "live lock held by a different suite configuration "
                        f"(fail closed): {lock_path}")
                return {"attached": True, "pid": meta["pid"],
                        "lock": str(lock_path)}
            # Stale holder: process gone, prune and retake.
            lock_path.unlink(missing_ok=True)
        payload = {"schema": "suite-launch-lock/1", "pid": os.getpid(),
                   "command": list(command), "acquired_unix": time.time()}
        # Atomic create: fail if another request created it concurrently.
        fd = os.open(str(lock_path),
                     os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        try:
            os.write(fd, json.dumps(payload, sort_keys=True).encode())
        finally:
            os.close(fd)
        self._meta = payload
        return {"attached": False, "pid": os.getpid(), "lock": str(lock_path)}

    def release(self) -> None:
        self.path().unlink(missing_ok=True)


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
    return _git_output(root, "rev-parse", "HEAD")


def git_tree_clean(root: Path) -> bool:
    return _git_output(root, "status", "--porcelain") == ""


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


def suite_identity(runner_result: dict, root: Path) -> dict:
    """Canonical suite identity from a successful runner result payload.

    Binds the runner schema, the serial identity digest of the discovered
    population, the executed identity digest, and the test count.  The two
    digests must both be present and the runner must have proven them equal
    (``ok``), otherwise the identity is malformed (fail closed).
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
    if not isinstance(count, int) or count < 1:
        raise GateOrderingError("runner result lacks a valid test count")
    return {
        "runner_schema": runner_result.get("schema"),
        "suite_command": [".venv/bin/python", SUITE_RUNNER, "--json"],
        "serial_digest": serial,
        "executed_digest": executed,
        "count": count,
    }


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
        suite=suite_identity(runner_result, root),
        environment=environment_identity(root),
        result="PASS",
        count=runner_result["count"],
        started_unix=started_unix,
        ended_unix=ended_unix,
    )


def request_identity(receipt_like: dict) -> dict:
    """Extract the request identity a receipt must match for reuse.

    Callers pass either a prior receipt or a dict carrying the same
    ``git_commit_sha`` / ``suite`` / ``environment`` fields; every field
    must be present (fail closed).
    """
    required = ("git_commit_sha", "suite", "environment")
    missing = [k for k in required if k not in receipt_like]
    if missing:
        raise GateOrderingError(
            f"request identity missing fields (fail closed): {missing}")
    return {k: receipt_like[k] for k in required}


def validate_receipt(receipt: dict, request: dict) -> bool:
    """Authorize reuse ONLY on full identity match and a PASS result.

    Fail-closed on: wrong/unknown schema, non-PASS or missing result,
    missing identity fields, head drift, suite-config drift, environment
    drift, or tampering (an end before start, a zero/negative duration).
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
    try:
        request = request_identity(request)
    except GateOrderingError:
        raise
    if receipt.get("git_commit_sha") != request["git_commit_sha"]:
        return False  # head drift: legitimately invalidated, not an error
    if receipt.get("suite") != request["suite"]:
        return False  # suite configuration drift
    if receipt.get("environment") != request["environment"]:
        return False  # dependency/environment authority drift
    started, ended = receipt.get("started_unix"), receipt.get("ended_unix")
    if not isinstance(started, (int, float)) or not isinstance(ended, (int, float)):
        raise GateOrderingError("receipt timestamps malformed (fail closed)")
    if ended < started or ended - started <= 0:
        raise GateOrderingError(
            "receipt duration is not positive (fail closed)")
    return True


def reuse_or_rerun(receipt: dict | None, request: dict) -> dict:
    """The Phase 2/3 reuse decision (advisory dedup, never a bypass)."""
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
# Phase 6 — old-vs-new trace comparison
# ---------------------------------------------------------------------------

def trace_campaign(old_order: bool, review_mutates_head: bool = True) -> dict:
    """Synthetic trace of expensive-gate executions under one ordering.

    ``old_order=True``  models the #210/PR-#212 sequence: full suite +
    hosted CI BEFORE review, review mutates the head, both run AGAIN after.
    ``old_order=False`` is the canonical ordering this issue establishes.
    Returns the count of full-suite and hosted-CI executions.
    """
    if old_order:
        executions = {"full-cpu-suite": 2 if review_mutates_head else 1,
                      "hosted-exact-head-ci": 2 if review_mutates_head else 1}
    else:
        executions = {"full-cpu-suite": 1, "hosted-exact-head-ci": 1}
    return {
        "schema": SCHEMA,
        "old_order": old_order,
        "review_mutates_head": review_mutates_head,
        "expensive_executions": executions,
        "total": sum(executions.values()),
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
        print(json.dumps({"old": old, "new": new}, indent=2, sort_keys=True))
        return 0
    print(json.dumps({"schema": SCHEMA, "ok": True}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
