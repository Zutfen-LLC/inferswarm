#!/usr/bin/env python3
"""Run the full CPU unittest population in bounded, isolated processes.

Issue #173.  Discovery is the authority: this runner performs the same
``unittest discover -s tests -p 'test_*.py'`` population discovery once, then
partitions complete module suites across a bounded number of subprocesses.
Each worker returns the test IDs it actually started; the parent fails closed
unless their union is exactly the discovered serial identity set.

Use ``.venv/bin/python scripts/run_full_cpu_suite.py`` for the preferred local
full CPU-suite command.  ``unittest discover`` remains useful for direct
single-process debugging and equivalence checks.
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
SCHEMA = "parallel-full-cpu-suite/1"
DEFAULT_MAX_JOBS = 4
# Kept in one interpreter because the historical Issue #133 fixture deliberately
# couples these real script modules through sys.modules.
COOLOCATED_MODULES = frozenset({
    "test_issue133_arm_c_retry_campaign",
    "test_issue133_arm_c_retry_direct",
    "test_issue133_corrected_freeze",
})
# These modules need an exclusive worker under parallel execution. Arm-B copies
# multi-GB retained evidence; Issue #103 asserts its serial /tmp-shaped volatile
# paths. Keeping each isolated preserves both contracts.
ISOLATED_MODULES = frozenset({
    "test_issue117_arm_b_retention",
    "test_issue103_planner",
    "test_issue117_preflight",
})
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


def partition_units(units: list[Unit], jobs: int) -> list[list[Unit]]:
    """Deterministic least-test-count partition, preserving required bundle."""
    jobs = worker_count(jobs, len(units))
    unit_by_name = {unit.name: unit for unit in units}
    required = [unit_by_name[name] for name in unit_by_name if name in COOLOCATED_MODULES]
    if required and {unit.name for unit in required} != COOLOCATED_MODULES:
        raise SuiteError("required Issue #133 co-location bundle is incomplete")
    isolated = [unit_by_name[name] for name in unit_by_name if name in ISOLATED_MODULES]
    if jobs > len(isolated) and isolated:
        remaining = [unit for unit in units if unit.name not in ISOLATED_MODULES]
        buckets = partition_units(remaining, jobs - len(isolated))
        return [[unit] for unit in isolated] + buckets
    grouped: list[list[Unit]] = []
    if required:
        grouped.append(required)
    grouped.extend([[unit] for unit in units if unit.name not in COOLOCATED_MODULES])
    buckets: list[list[Unit]] = [[] for _ in range(jobs)]
    loads = [0] * jobs
    for group in grouped:
        index = min(range(jobs), key=lambda item: (loads[item], item))
        buckets[index].extend(group)
        loads[index] += sum(len(unit.ids) for unit in group)
    return [bucket for bucket in buckets if bucket]


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
    status = subprocess.run(["git", "-C", str(root), "status", "--porcelain"],
                            capture_output=True, text=True)
    if status.returncode == 0 and status.stdout:
        raise SuiteError("refusing dirty Git worktree: commit or stash before the isolated full suite")


def stop_workers(workers: list[tuple]) -> None:
    """Terminate, reap, then force-kill every started worker before cleanup."""
    for worker in workers:
        process = worker[0]
        if process.poll() is None:
            process.terminate()
    for worker in workers:
        process = worker[0]
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


def run_suite(root: Path = ROOT, tests_dir: Path | None = None, *, jobs: int | None = None,
              timeout: float = 1800.0) -> dict:
    root, tests_dir = Path(root).resolve(), Path(tests_dir or Path(root) / "tests").resolve()
    ensure_clean_git_worktree(root)
    units = discover_units(root, tests_dir)
    serial_ids = ids_for_units(units)
    selected_jobs = default_jobs(len(units)) if jobs is None else worker_count(jobs, len(units))
    buckets = partition_units(units, selected_jobs)
    diagnostics: list[str] = []
    receipts: list[dict] = []
    workspace_parent = Path(os.environ.get(
        "INFER_SWARM_SUITE_TMPDIR", str(Path.home() / ".cache"))).resolve()
    workspace_parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="parallel-full-cpu-suite-", dir=workspace_parent) as temporary:
        temp = Path(temporary)
        workers: list[tuple[subprocess.Popen, Path, Path]] = []
        try:
            for index, bucket in enumerate(buckets):
                worker_root = prepare_worker_root(root, temp, index)
                receipt = temp / f"worker-{index}.json"
                assigned = ids_for_units(bucket)
                worker_script = worker_root / "scripts" / Path(__file__).name
                if not worker_script.is_file():
                    worker_script = Path(__file__).resolve()
                modules_path = temp / f"worker-{index}-modules.json"
                expected_path = temp / f"worker-{index}-expected.json"
                modules_path.write_text(json.dumps([unit.name for unit in bucket]), encoding="utf-8")
                expected_path.write_text(json.dumps(assigned), encoding="utf-8")
                command = [sys.executable, str(worker_script), "--worker",
                           "--root", str(worker_root), "--tests-dir", str(worker_root / "tests"),
                           "--modules-file", str(modules_path),
                           "--expected-ids-file", str(expected_path), "--receipt", str(receipt)]
                worker_tmp = temp / f"worker-{index}-tmp"
                worker_tmp.mkdir()
                environment = os.environ.copy()
                # All ordinary parallel workers get a private home-filesystem
                # scratch directory. The one path-sensitive module retains the
                # serial command's /tmp behavior; jobs=1 remains fully serial.
                if len(buckets) > 1 and {unit.name for unit in bucket} != TMPDIR_SENSITIVE_MODULES:
                    environment["TMPDIR"] = str(worker_tmp)
                workers.append((subprocess.Popen(command, cwd=worker_root, text=True,
                                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                                  env=environment),
                                receipt, worker_root))
            for index, (process, receipt, _) in enumerate(workers):
                try:
                    stdout, stderr = process.communicate(timeout=timeout)
                except subprocess.TimeoutExpired:
                    process.terminate()
                    stdout, stderr = process.communicate(timeout=10)
                    raise SuiteError(f"worker {index} timed out after {timeout} seconds")
                if process.returncode:
                    diagnostics.append(f"worker {index} exit={process.returncode}\n{stdout}\n{stderr}")
                if not receipt.is_file():
                    raise SuiteError(f"worker {index} exited without a receipt")
                try:
                    receipts.append(json.loads(receipt.read_text(encoding="utf-8")))
                except (OSError, json.JSONDecodeError) as error:
                    raise SuiteError(f"worker {index} receipt is malformed: {error}") from error
        except BaseException as error:
            stop_workers(workers)
            if isinstance(error, KeyboardInterrupt):
                raise SuiteError("interrupted: all worker processes terminated") from error
            raise
        finally:
            for _, _, worker_root in workers:
                remove_worker_root(root, worker_root)
    try:
        executed_ids, executed_digest = validate_receipts(receipts, serial_ids)
    except SuiteError as error:
        diagnostics.append(str(error))
        return {"ok": False, "serial_ids": serial_ids, "executed_ids": [],
                "serial_digest": identity_digest(sorted(serial_ids)), "executed_digest": None,
                "count": len(serial_ids), "diagnostics": "\n".join(diagnostics)}
    return {"ok": not diagnostics, "serial_ids": serial_ids, "executed_ids": executed_ids,
            "serial_digest": identity_digest(sorted(serial_ids)), "executed_digest": executed_digest,
            "count": len(serial_ids), "jobs": len(buckets), "diagnostics": "\n".join(diagnostics)}


def plan(root: Path, tests_dir: Path, jobs: int | None) -> dict:
    units = discover_units(root, tests_dir)
    selected_jobs = default_jobs(len(units)) if jobs is None else worker_count(jobs, len(units))
    buckets = partition_units(units, selected_jobs)
    ids = ids_for_units(units)
    return {"schema": SCHEMA, "count": len(ids), "identity_digest": identity_digest(sorted(ids)),
            "module_count": len(units), "jobs": len(buckets),
            "co_located_modules": sorted(COOLOCATED_MODULES),
            "workers": [[unit.name for unit in bucket] for bucket in buckets]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jobs", type=int)
    parser.add_argument("--timeout", type=float, default=1800.0)
    parser.add_argument("--list", "--plan", action="store_true", dest="list_only")
    parser.add_argument("--json", action="store_true")
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
            payload = run_suite(args.root, tests_dir, jobs=args.jobs, timeout=args.timeout)
    except (SuiteError, ValueError) as error:
        print(f"parallel-full-cpu-suite: FAIL {error}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(payload, sort_keys=True))
    elif args.list_only:
        print(f"discovered {payload['count']} tests in {payload['module_count']} modules; "
              f"identity digest {payload['identity_digest']}; {payload['jobs']} workers")
    elif payload["ok"]:
        print(f"parallel-full-cpu-suite: PASS {payload['count']} tests; "
              f"identity digest {payload['serial_digest']}; {payload['jobs']} workers")
    else:
        print("parallel-full-cpu-suite: FAIL\n" + payload["diagnostics"], file=sys.stderr)
    if args.list_only:
        return 0
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
