#!/usr/bin/env python3
"""Run the full CPU unittest population in bounded, isolated processes.

Issue #173.  Discovery is the authority: this runner performs the same
``unittest discover -s tests -p 'test_*.py'`` population discovery once, then
schedules complete module suites across a bounded number of subprocesses.
Each worker returns the test IDs it actually started; the parent fails closed
unless their union is exactly the discovered serial identity set.

Scheduling contract (corrected per maintainer review of the first revision):

* ``ISOLATED_MODULES`` tasks are always single-module process tasks.  They are
  scheduled first and never share a worker process with another module, at any
  supported ``--jobs`` value.  They do not permanently consume a worker slot:
  execution uses a bounded rolling window of at most ``--jobs`` live worker
  processes, and a slot is released as soon as its task terminates.
* The remaining population (with the Issue #133 co-location bundle kept in one
  task) is deterministically least-loaded partitioned across the requested
  worker count, so the default ``--jobs 4`` spreads the population instead of
  collapsing it onto one worker.
* ``jobs=1`` retains ordinary serial semantics: one process, discovery order,
  and the inherited environment.

TMPDIR contract: a task whose modules intersect
``TMPDIR_SENSITIVE_MODULES`` must observe the serial-compatible temporary
directory environment, so it inherits the parent environment verbatim (no
``TMPDIR`` override), exactly like raw ``unittest discover``.  ``jobs=1``
inherits for every module.  Every other parallel task receives a private
scratch ``TMPDIR`` so ordinary modules cannot collide on volatile paths.

Use ``.venv/bin/python scripts/run_full_cpu_suite.py`` for the preferred local
full CPU-suite command.  ``unittest discover`` remains useful for direct
single-process debugging and equivalence checks.

Single-launch deduplication (Issue #213): the canonical invocation path
(delegating to :func:`run_single_head_suite`) guarantees at most ONE real
suite process per ``(exact head, suite configuration, environment
authority)`` request on a host.  Concurrent identical requests attach
behind the live launch and consume its mechanically validated completion
receipt; distinct identities never share results.  The launch identity is
derived mechanically from the repository, never from a caller-supplied key.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
import unittest
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
SCHEMA = "parallel-full-cpu-suite/1"
# Structured normalized suite configuration (Issue #213 configuration
# identity).  The execution-relevant public runner inputs live in ONE
# authoritative object; the completion/receipt identity binds it instead
# of a command string alone.
SUITE_CONFIG_SCHEMA = "suite-config/1"
DEFAULT_MAX_JOBS = 4
# Kept in one interpreter because the historical Issue #133 fixture deliberately
# couples these real script modules through sys.modules.
COOLOCATED_MODULES = frozenset({
    "test_issue133_arm_c_retry_campaign",
    "test_issue133_arm_c_retry_direct",
    "test_issue133_corrected_freeze",
})
# These modules need an exclusive worker process under parallel execution.
# Arm-B copies multi-GB retained evidence; Issue #103 and the Issue #117
# preflight assert serial /tmp-shaped volatile paths.  Keeping each in its own
# single-module process preserves both contracts without starving the
# remaining population of worker slots.
ISOLATED_MODULES = frozenset({
    "test_issue117_arm_b_retention",
    "test_issue103_planner",
    "test_issue117_preflight",
})
# Modules whose deterministic records encode /tmp-shaped volatile paths.  A
# task containing any of them must run with the serial-compatible inherited
# environment (no TMPDIR override), never with private scratch.
TMPDIR_SENSITIVE_MODULES = frozenset({
    "test_issue103_planner",
    "test_issue117_preflight",
})


class SuiteError(RuntimeError):
    """A fail-closed runner or receipt validation failure."""


@dataclass(frozen=True)
class Unit:
    name: str
    ids: tuple[str, ...]


@dataclass(frozen=True)
class Task:
    """One worker-process assignment in the phased schedule."""

    index: int
    phase: str  # "serial" | "isolated" | "population"
    units: tuple[Unit, ...]
    tmpdir_mode: str  # "serial" | "inherited" | "private"


def flatten(suite: unittest.TestSuite | unittest.TestCase) -> list[unittest.TestCase]:
    if isinstance(suite, unittest.TestCase):
        return [suite]
    tests: list[unittest.TestCase] = []
    for child in suite:
        tests.extend(flatten(child))
    return tests


def identity_digest(ids: Iterable[str]) -> str:
    return hashlib.sha256(("\n".join(ids) + "\n").encode("utf-8")).hexdigest()


def ids_for_units(units: Iterable[Unit]) -> list[str]:
    return [test_id for unit in units for test_id in unit.ids]


def discover_units(root: Path = ROOT, tests_dir: Path | None = None) -> list[Unit]:
    """Discover exactly like raw unittest discovery and group leaves by module."""
    root, tests_dir = Path(root).resolve(), Path(tests_dir or root / "tests").resolve()
    if not tests_dir.is_dir():
        raise SuiteError(f"test directory is missing: {tests_dir}")
    old_path = list(sys.path)
    try:
        # Raw CLI discovery starts with the repository cwd importable.  A script
        # entrypoint instead starts at scripts/, so restore that same root seam
        # without pre-inserting the discovery directory itself.
        sys.path.insert(0, str(root))
        suite = unittest.TestLoader().discover(str(tests_dir), pattern="test_*.py")
        leaves = flatten(suite)
    finally:
        sys.path[:] = old_path
    by_module: dict[str, list[str]] = {}
    order: list[str] = []
    for test in leaves:
        test_id = test.id()
        module = test_id.split(".", 1)[0]
        if module == "unittest":
            error = getattr(test, "_exception", None)
            raise SuiteError(f"serial discovery import failure: {error}")
        if not module.startswith("test_"):
            raise SuiteError(f"discovery returned non-test module identity: {test_id}")
        if module not in by_module:
            order.append(module)
            by_module[module] = []
        by_module[module].append(test_id)
    ids = [test_id for name in order for test_id in by_module[name]]
    if not ids:
        raise SuiteError("discovery returned no test identities")
    if len(ids) != len(set(ids)):
        raise SuiteError("serial discovery returned duplicate test identities")
    return [Unit(name, tuple(by_module[name])) for name in order]


def worker_count(requested: int, unit_count: int) -> int:
    if requested < 1:
        raise ValueError("--jobs must be a positive integer")
    if unit_count < 1:
        raise ValueError("no module units to execute")
    return min(requested, unit_count)


def default_jobs(unit_count: int) -> int:
    return worker_count(min(DEFAULT_MAX_JOBS, os.cpu_count() or 1), unit_count)


def tmpdir_mode_for(module_names: Iterable[str]) -> str:
    """Inherited (serial-compatible) environment for path-sensitive modules."""
    return ("inherited" if TMPDIR_SENSITIVE_MODULES.intersection(module_names)
            else "private")


def co_location_groups(units: list[Unit]) -> list[list[Unit]]:
    """Group population units, keeping the Issue #133 bundle in one group."""
    bundle = [unit for unit in units if unit.name in COOLOCATED_MODULES]
    if bundle and {unit.name for unit in bundle} != COOLOCATED_MODULES:
        raise SuiteError("required Issue #133 co-location bundle is incomplete")
    groups: list[list[Unit]] = []
    for unit in units:
        if unit.name in COOLOCATED_MODULES:
            if unit is bundle[0]:
                groups.append(bundle)
            continue
        groups.append([unit])
    return groups


def least_loaded_buckets(groups: list[list[Unit]], jobs: int) -> list[list[Unit]]:
    """Deterministic least-test-count partition of groups onto jobs buckets."""
    buckets: list[list[Unit]] = [[] for _ in range(jobs)]
    loads = [0] * jobs
    for group in groups:
        index = min(range(jobs), key=lambda item: (loads[item], item))
        buckets[index].extend(group)
        loads[index] += sum(len(unit.ids) for unit in group)
    return [bucket for bucket in buckets if bucket]


def build_tasks(units: list[Unit], jobs: int) -> tuple[int, list[Task]]:
    """Build the deterministic phased schedule for a requested worker count.

    jobs=1 is the explicit serial contract: one task, discovery order,
    inherited environment.  For jobs >= 2 every ISOLATED_MODULES unit becomes
    a single-module task scheduled first (never sharing a process with another
    module), and the remaining population is balanced across all requested
    workers.  Task order is deterministic; the runtime rolling window reuses
    worker slots as tasks terminate, so isolated tasks do not permanently
    consume a slot.
    """
    if ISOLATED_MODULES & COOLOCATED_MODULES:
        raise SuiteError("module declared both isolated and co-located")
    jobs = worker_count(jobs, len(units))
    if jobs == 1:
        return 1, [Task(0, "serial", tuple(units), "serial")]
    tasks: list[Task] = []
    for unit in units:
        if unit.name in ISOLATED_MODULES:
            tasks.append(Task(len(tasks), "isolated", (unit,),
                              tmpdir_mode_for((unit.name,))))
    population = [unit for unit in units if unit.name not in ISOLATED_MODULES]
    groups = co_location_groups(population)
    if groups:
        for bucket in least_loaded_buckets(groups, min(jobs, len(groups))):
            tasks.append(Task(len(tasks), "population", tuple(bucket),
                              tmpdir_mode_for(unit.name for unit in bucket)))
    return jobs, tasks


class RecordingResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.started_ids: list[str] = []

    def startTest(self, test):  # noqa: N802
        self.started_ids.append(test.id())
        super().startTest(test)


def _atomic_json(path: Path, payload: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    temporary.replace(path)


def worker_main(root: Path, tests_dir: Path, module_names: list[str], expected_ids: list[str], receipt: Path) -> int:
    """Execute complete module suites and write an atomic receipt in all cases."""
    started = time.monotonic()
    payload: dict = {"schema": SCHEMA, "ok": False, "expected_ids": expected_ids}
    try:
        sys.path.insert(0, str(root))
        sys.path.insert(0, str(tests_dir))
        suites = [unittest.defaultTestLoader.loadTestsFromName(name) for name in module_names]
        loaded_ids = [test.id() for suite in suites for test in flatten(suite)]
        if loaded_ids != expected_ids:
            raise SuiteError("worker module loading differs from parent discovery: "
                             f"expected {expected_ids!r}, got {loaded_ids!r}")
        runner = unittest.TextTestRunner(verbosity=2, resultclass=RecordingResult)
        result: RecordingResult = runner.run(unittest.TestSuite(suites))
        payload.update({
            "started_ids": result.started_ids,
            "tests_run": result.testsRun,
            "failures": len(result.failures),
            "errors": len(result.errors),
            "skipped": len(result.skipped),
            "ok": result.wasSuccessful() and result.started_ids == expected_ids,
        })
    except BaseException as error:
        payload.update({"error": f"{type(error).__name__}: {error}",
                        "traceback": traceback.format_exc(), "started_ids": payload.get("started_ids", [])})
    finally:
        payload["elapsed_seconds"] = time.monotonic() - started
        _atomic_json(receipt, payload)
    return 0 if payload["ok"] else 1


def validate_receipts(receipts: list[dict], serial_ids: list[str]) -> tuple[list[str], str]:
    if not receipts:
        raise SuiteError("no worker receipts were produced")
    executed: list[str] = []
    for index, receipt in enumerate(receipts):
        if not isinstance(receipt, dict) or receipt.get("schema") != SCHEMA:
            raise SuiteError(f"worker {index} receipt is malformed")
        if not receipt.get("ok"):
            raise SuiteError(f"worker {index} reported failure: {receipt.get('error', 'test failure/error')}")
        ids = receipt.get("started_ids")
        if not isinstance(ids, list) or ids != receipt.get("expected_ids"):
            raise SuiteError(f"worker {index} execution IDs differ from its assignment")
        executed.extend(ids)
    if len(executed) != len(set(executed)):
        raise SuiteError("parallel workers executed duplicate test identities")
    if sorted(executed) != sorted(serial_ids):
        raise SuiteError("parallel workers omitted or added test identities")
    return executed, identity_digest(sorted(executed))


def ensure_clean_git_worktree(root: Path) -> None:
    """Reject dirty Git roots so discovery and isolated workers share one SHA."""
    probe = subprocess.run(["git", "-C", str(root), "rev-parse", "--is-inside-work-tree"],
                           capture_output=True, text=True)
    inside = probe.returncode == 0 and probe.stdout.strip() == "true"
    status = subprocess.run(["git", "-C", str(root), "status", "--porcelain"],
                            capture_output=True, text=True)
    if status.returncode != 0:
        if inside:
            # Fail closed: a git failure inside a real work tree must never be
            # treated as a clean tree (review P2: guard was silently skipped).
            raise SuiteError(f"git status failed inside a work tree: {status.stderr.strip()}")
        return  # not a Git checkout (plain fixture root); no guard applies
    if status.stdout:
        raise SuiteError("refusing dirty Git worktree: commit or stash before the isolated full suite")


def stop_workers(processes: list[subprocess.Popen]) -> None:
    """Terminate, reap, then force-kill every live worker before cleanup."""
    for process in processes:
        if process.poll() is None:
            process.terminate()
    for process in processes:
        try:
            process.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate()


def prepare_worker_root(root: Path, temporary: Path, index: int) -> Path:
    """Create a detached worker worktree when ``root`` is a Git checkout."""
    probe = subprocess.run(["git", "-C", str(root), "rev-parse", "--is-inside-work-tree"],
                           capture_output=True, text=True)
    if probe.returncode != 0 or probe.stdout.strip() != "true":
        return root
    worker_root = temporary / f"worktree-{index}"
    created = subprocess.run(["git", "-C", str(root), "worktree", "add", "--detach",
                              str(worker_root), "HEAD"], capture_output=True, text=True)
    if created.returncode != 0:
        raise SuiteError(f"cannot create isolated worker worktree: {created.stderr.strip()}")
    return worker_root


def remove_worker_root(root: Path, worker_root: Path) -> None:
    """Remove a detached worker worktree; no-op for non-Git fixture roots."""
    if worker_root == root:
        return
    removed = subprocess.run(["git", "-C", str(root), "worktree", "remove", "--force",
                              str(worker_root)], capture_output=True, text=True)
    if removed.returncode != 0:
        raise SuiteError(f"cannot remove isolated worker worktree: {removed.stderr.strip()}")


def _task_environment(task: Task, temporary: Path) -> dict[str, str]:
    """Build the worker environment honoring the TMPDIR contract.

    "serial" (jobs=1) and "inherited" (TMPDIR-sensitive) tasks receive the
    parent environment verbatim, which is exactly what raw serial
    ``unittest discover`` observes.  Only "private" parallel tasks get a
    per-task scratch TMPDIR.
    """
    environment = dict(os.environ)
    if task.tmpdir_mode == "private":
        worker_tmp = temporary / f"task-{task.index}-tmp"
        worker_tmp.mkdir(parents=True, exist_ok=True)
        environment["TMPDIR"] = str(worker_tmp)
    return environment


def run_suite(root: Path = ROOT, tests_dir: Path | None = None, *, jobs: int | None = None,
              timeout: float = 1800.0, retain_dir: Path | None = None) -> dict:
    """Execute the phased schedule through a rolling window of bounded workers."""
    root, tests_dir = Path(root).resolve(), Path(tests_dir or Path(root) / "tests").resolve()
    ensure_clean_git_worktree(root)
    units = discover_units(root, tests_dir)
    serial_ids = ids_for_units(units)
    requested = default_jobs(len(units)) if jobs is None else jobs
    selected_jobs, tasks = build_tasks(units, requested)
    config = suite_config_for(root, tests_dir, jobs, selected_jobs,
                              _task_dicts(tasks), timeout, retain_dir)
    diagnostics: list[str] = []
    receipts: list[dict] = []
    timings: list[dict] = []
    workspace_parent = Path(os.environ.get(
        "INFER_SWARM_SUITE_TMPDIR", str(Path.home() / ".cache"))).resolve()
    workspace_parent.mkdir(parents=True, exist_ok=True)
    if retain_dir is not None:
        retain_dir = Path(retain_dir).resolve()
        if retain_dir.exists() and any(retain_dir.iterdir()):
            raise SuiteError(f"retain directory is not empty: {retain_dir}")
        retain_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="parallel-full-cpu-suite-", dir=workspace_parent) as temporary_name:
        temporary = Path(temporary_name)
        artifacts = retain_dir if retain_dir is not None else temporary
        pending = list(tasks)
        running: list[tuple[Task, subprocess.Popen, Path, Path, float]] = []
        outstanding_roots: list[Path] = []
        try:
            while pending or running:
                # Fill the rolling window: at most selected_jobs live workers,
                # isolated tasks first, then population buckets in order.
                while pending and len(running) < selected_jobs:
                    task = pending.pop(0)
                    worker_root = prepare_worker_root(root, temporary, task.index)
                    outstanding_roots.append(worker_root)
                    modules_path = artifacts / f"task-{task.index}-modules.json"
                    expected_path = artifacts / f"task-{task.index}-expected.json"
                    receipt = artifacts / f"task-{task.index}.json"
                    modules_path.write_text(
                        json.dumps([unit.name for unit in task.units]), encoding="utf-8")
                    expected_path.write_text(
                        json.dumps(ids_for_units(task.units)), encoding="utf-8")
                    worker_script = worker_root / "scripts" / Path(__file__).name
                    if not worker_script.is_file():
                        worker_script = Path(__file__).resolve()
                    # The worker executes the SAME effective tests tree:
                    # map it into the detached worktree when the root is a
                    # Git checkout (custom tests directories included);
                    # non-Git fixture roots execute the tree in place.
                    try:
                        worker_tests = worker_root / tests_dir.relative_to(root)
                    except ValueError:
                        worker_tests = tests_dir
                    # Worker output goes to per-task files, never OS pipes: the
                    # poll-based reaper does not drain pipes while waiting, and
                    # a full 64KB pipe buffer would freeze the worker forever.
                    stdout_path = artifacts / f"task-{task.index}-stdout.txt"
                    stderr_path = artifacts / f"task-{task.index}-stderr.txt"
                    with stdout_path.open("wb") as out, stderr_path.open("wb") as err:
                        command = [sys.executable, str(worker_script), "--worker",
                                   "--root", str(worker_root), "--tests-dir", str(worker_tests),
                                   "--modules-file", str(modules_path),
                                   "--expected-ids-file", str(expected_path), "--receipt", str(receipt)]
                        process = subprocess.Popen(command, cwd=worker_root, text=True,
                                                   stdout=out, stderr=err,
                                                   env=_task_environment(task, temporary))
                    running.append((task, process, receipt, worker_root, time.monotonic()))
                # Reap whichever live worker finishes first: a crashing task is
                # detected promptly regardless of phase order, and its slot
                # returns to the window for the next pending task.
                finished = None
                while finished is None and running:
                    now = time.monotonic()
                    for slot, entry in enumerate(running):
                        if entry[1].poll() is not None:
                            finished = slot
                            break
                        if now - entry[4] > timeout:
                            entry[1].terminate()
                            try:
                                entry[1].communicate(timeout=10)
                            except subprocess.TimeoutExpired:
                                entry[1].kill()
                                entry[1].communicate()
                            raise SuiteError(
                                f"task {entry[0].index} ({entry[0].phase}) timed out "
                                f"after {timeout} seconds")
                    time.sleep(0.05)
                if finished is None:
                    continue
                task, process, receipt, worker_root, started_at = running.pop(finished)
                process.wait()
                ended_at = time.monotonic()
                remove_worker_root(root, worker_root)
                outstanding_roots.remove(worker_root)
                if process.returncode:
                    stdout = (artifacts / f"task-{task.index}-stdout.txt").read_text(
                        encoding="utf-8", errors="replace")
                    stderr = (artifacts / f"task-{task.index}-stderr.txt").read_text(
                        encoding="utf-8", errors="replace")
                    diagnostics.append(
                        f"task {task.index} ({task.phase}) exit={process.returncode}\n{stdout}\n{stderr}")
                if not receipt.is_file():
                    raise SuiteError(f"task {task.index} ({task.phase}) exited without a receipt")
                try:
                    receipts.append(json.loads(receipt.read_text(encoding="utf-8")))
                except (OSError, json.JSONDecodeError) as error:
                    raise SuiteError(f"task {task.index} receipt is malformed: {error}") from error
                timings.append({
                    "task": task.index, "phase": task.phase,
                    "modules": [unit.name for unit in task.units],
                    "tmpdir_mode": task.tmpdir_mode,
                    "started_at": started_at, "ended_at": ended_at,
                    "elapsed_seconds": receipts[-1].get("elapsed_seconds"),
                    "tests_run": receipts[-1].get("tests_run"),
                })
        except BaseException as error:
            stop_workers([entry[1] for entry in running])
            cleanup_error = None
            for worker_root in list(outstanding_roots):
                try:
                    remove_worker_root(root, worker_root)
                except SuiteError as cleanup_failure:
                    # Never mask the original failure with a cleanup failure.
                    cleanup_error = cleanup_failure
            if isinstance(error, KeyboardInterrupt):
                raise SuiteError("interrupted: all worker processes terminated") from error
            if cleanup_error is not None:
                error.add_note(f"worktree cleanup also failed: {cleanup_error}")
            raise
    try:
        executed_ids, executed_digest = validate_receipts(receipts, serial_ids)
    except SuiteError as error:
        diagnostics.append(str(error))
        return _result(False, serial_ids, [], selected_jobs, tasks, timings,
                       diagnostics, config=config)
    return _result(not diagnostics, serial_ids, executed_ids, selected_jobs, tasks,
                   timings, diagnostics, executed_digest, config=config)


def run_single_head_suite(root: Path = ROOT, *, tests_dir: Path | None = None,
                          jobs: int | None = None,
                          timeout: float = 1800.0,
                          retain_dir: Path | None = None) -> dict:
    """Canonical single-launch entry (Issue #213 duplicate-launch guard).

    Thin delegation to ``issue213_gate_orchestration.run_single_head_suite``
    so the guard lives at the canonical invocation seam with exactly one
    dependency edge.  ``tests_dir`` is honored exactly like the runner's
    own ``run_suite`` contract (default ``root/tests``); the launch
    identity binds the SAME effective tests directory.  Non-git roots run
    unguarded, mirroring the runner's own git doctrine; a dirty Git
    worktree is refused BEFORE identity derivation/completion reuse (the
    guard enforces the runner's own ``ensure_clean_git_worktree``
    doctrine), surfacing here as the runner's own ``SuiteError`` so the
    CLI keeps its FAIL/exit-1 contract.  Import is local: tests import
    THIS module first, and the orchestration module loads THIS module only
    lazily for ``plan()``.
    """
    sys.path.insert(0, str(SCRIPTS))
    try:
        import issue213_gate_orchestration as gate
    finally:
        try:
            sys.path.remove(str(SCRIPTS))
        except ValueError:  # pragma: no cover (defensive)
            pass
    try:
        return gate.run_single_head_suite(
            Path(root), tests_dir=tests_dir, jobs=jobs, timeout=timeout,
            retain_dir=retain_dir)
    except gate.GateOrderingError as error:
        raise SuiteError(str(error)) from error


def _result(ok: bool, serial_ids: list[str], executed_ids: list[str], jobs: int,
            tasks: list[Task], timings: list[dict], diagnostics: list[str],
            executed_digest: str | None = None,
            config: dict | None = None) -> dict:
    payload = {"schema": SCHEMA, "ok": ok, "serial_ids": serial_ids, "executed_ids": executed_ids,
               "serial_digest": identity_digest(sorted(serial_ids)),
               "executed_digest": executed_digest, "count": len(serial_ids), "jobs": jobs,
               "tasks": _task_dicts(tasks),
               "task_timings": timings, "diagnostics": "\n".join(diagnostics)}
    if config is not None:
        payload["suite_config"] = config
    return payload


def _task_dicts(tasks: list[Task]) -> list[dict]:
    return [{"index": task.index, "phase": task.phase,
             "tmpdir_mode": task.tmpdir_mode,
             "modules": [unit.name for unit in task.units]} for task in tasks]


def task_plan_digest(task_dicts: list[dict]) -> str:
    """Deterministic digest of the effective schedule (Identity #213).

    Binds the phased task plan — task order, phase, TMPDIR mode, and module
    assignment — so two requests with different effective schedules can
    never share one completion identity.
    """
    return hashlib.sha256(json.dumps(
        task_dicts, sort_keys=True, separators=(",", ":")).encode(
            "utf-8")).hexdigest()


def suite_config_for(root: Path, tests_dir: Path, requested_jobs: int | None,
                     selected_jobs: int, task_dicts: list[dict],
                     timeout: float, retain_dir: Path | None) -> dict:
    """The ONE normalized execution configuration (Issue #213).

    Captures every execution-relevant public runner input — effective tests
    directory, EFFECTIVE/selected jobs, the deterministic task-plan
    digest, timeout, and retention request — as a structured object.
    Identity binds the EFFECTIVE schedule (the runner's deterministic
    plan), not the requested label: default jobs and explicit ``--jobs 1``
    are distinguishable exactly when their effective schedules differ.
    Never a bare test-count/digest proxy: two runs that discover the same
    population under different jobs/timeout/retention/tests-dir
    configurations carry different ``suite_config`` objects.
    """
    if (not isinstance(timeout, (int, float)) or isinstance(timeout, bool)
            or timeout <= 0):
        raise SuiteError(f"timeout must be a positive number: {timeout!r}")
    if requested_jobs is not None and (not isinstance(requested_jobs, int)
                                       or isinstance(requested_jobs, bool)
                                       or requested_jobs < 1):
        raise SuiteError(f"jobs must be a positive integer: {requested_jobs!r}")
    root, tests_dir = Path(root).resolve(), Path(tests_dir).resolve()
    try:
        tests_identity = tests_dir.relative_to(root).as_posix()
    except ValueError:
        # Outside the root: only representable (and only legal) for plain
        # non-Git fixture roots; guarded Git-backed requests fail closed on
        # this shape before identity derivation (orchestration doctrine).
        tests_identity = str(tests_dir)
    return {
        "schema": SUITE_CONFIG_SCHEMA,
        "tests_dir": tests_identity,
        "jobs": selected_jobs,
        "plan_digest": task_plan_digest(task_dicts),
        "timeout": float(timeout),
        "retain_dir": (str(Path(retain_dir).resolve())
                       if retain_dir is not None else None),
    }


def suite_config(root: Path = ROOT, tests_dir: Path | None = None, *,
                 jobs: int | None = None, timeout: float = 1800.0,
                 retain_dir: Path | None = None) -> dict:
    """Derive the normalized configuration from the runner's own plan.

    Same authority as execution: the deterministic ``plan()`` of the exact
    ``(root, tests_dir, jobs)`` triple determines the effective selected
    jobs and the task-plan digest recorded in the configuration.
    """
    root = Path(root).resolve()
    tests_dir = Path(tests_dir or root / "tests").resolve()
    payload = plan(root, tests_dir, jobs)
    return suite_config_for(root, tests_dir, jobs, payload["jobs"],
                            payload["tasks"], timeout, retain_dir)


def plan(root: Path, tests_dir: Path, jobs: int | None) -> dict:
    units = discover_units(root, tests_dir)
    selected_jobs, tasks = build_tasks(units, default_jobs(len(units)) if jobs is None else jobs)
    ids = ids_for_units(units)
    task_dicts = _task_dicts(tasks)
    return {"schema": SCHEMA, "count": len(ids), "identity_digest": identity_digest(sorted(ids)),
            "module_count": len(units), "jobs": selected_jobs,
            "co_located_modules": sorted(COOLOCATED_MODULES),
            "isolated_modules": sorted(ISOLATED_MODULES),
            "tmpdir_sensitive_modules": sorted(TMPDIR_SENSITIVE_MODULES),
            "tasks": task_dicts}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jobs", type=int)
    parser.add_argument("--timeout", type=float, default=1800.0)
    parser.add_argument("--list", "--plan", action="store_true", dest="list_only")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--retain-dir", type=Path,
                        help="keep per-task assignment/receipt files and summary.json here")
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--tests-dir", type=Path)
    parser.add_argument("--modules-file", type=Path)
    parser.add_argument("--expected-ids-file", type=Path)
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args(argv)
    tests_dir = args.tests_dir or args.root / "tests"
    if args.worker:
        if not (args.modules_file and args.expected_ids_file and args.receipt):
            parser.error("--worker requires module, identity, and receipt files")
        try:
            modules = json.loads(args.modules_file.read_text(encoding="utf-8"))
            expected_ids = json.loads(args.expected_ids_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            parser.error(f"cannot read worker assignment: {error}")
        return worker_main(args.root, tests_dir, modules, expected_ids, args.receipt)
    try:
        if args.list_only:
            payload = plan(args.root, tests_dir, args.jobs)
        else:
            payload = run_single_head_suite(args.root, tests_dir=tests_dir,
                                            jobs=args.jobs,
                                            timeout=args.timeout,
                                            retain_dir=args.retain_dir)
    except (SuiteError, ValueError) as error:
        print(f"parallel-full-cpu-suite: FAIL {error}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(payload, sort_keys=True))
    elif args.list_only:
        print(f"discovered {payload['count']} tests in {payload['module_count']} modules; "
              f"identity digest {payload['identity_digest']}; {payload['jobs']} workers; "
              f"{len(payload['tasks'])} tasks")
    elif payload["ok"]:
        print(f"parallel-full-cpu-suite: PASS {payload['count']} tests; "
              f"identity digest {payload['serial_digest']}; {payload['jobs']} workers; "
              f"{len(payload['tasks'])} tasks")
    else:
        print("parallel-full-cpu-suite: FAIL\n" + payload["diagnostics"], file=sys.stderr)
    if args.list_only:
        return 0
    if args.retain_dir is not None:
        summary = Path(args.retain_dir).resolve() / "summary.json"
        _atomic_json(summary, payload)
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
