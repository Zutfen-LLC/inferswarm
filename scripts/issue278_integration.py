#!/usr/bin/env python3
"""Issue #278 (R8-I6A) — validate integrated tooling at the final PR head.

One production entry point composes the three accepted/reviewed child
capabilities into a single CPU-fixture chain:

  capture      the injected producer drives the REAL #275 collector
               (capture_execution_273) — retained originals land in
               collector custody under source/<case>/<tag>/;
  originals    a no-follow census of every retained original, with a
               canonical inventory digest binding the byte population;
  staging      the #276 production stager (stage_capture_276) copies the
               originals verbatim into append-only staged units;
  admission    the #276 production reader (admit_staged_276) recomputes
               every digest and re-derives identity from staged bytes,
               with mandatory custody binding to the retained originals;
  determinism  the #277 production orchestrator (orchestrate_277) admits
               every unit independently, recomputes primary/repeat
               determinism, and gates all candidate launches
               reference-first;
  reduction    the #273 public reducer is applied to the fixture record
               and fails closed, proving the integrated chain cannot
               mint physical terminal authority.

No caller boolean, verdict dictionary, or callback return is evidence.
Success is explicitly labeled tooling/fixture validation: it confers no
physical authority, merge authority, or #273 phase-3+ permission. The
executor/pair-comparison callbacks are recording fakes whose return
values are discarded by the orchestrator.

Fail-closed everywhere; CPU-fixture-only; no hardware, network,
holdout, or historical-evidence access.
"""
from __future__ import annotations

import hashlib
import json
import stat
from pathlib import Path
from typing import Any, Callable

import issue270_authority as C
import issue273_reducer as R
from issue276_reader import ReaderError, admit_staged_276, stage_capture_276
import issue277_orchestrator as O

SCHEMA = "inferswarm.issue278.integration/1"
INTEGRATION_COMPLETE = "integration complete (tooling/fixture validation only)"
EVIDENCE_CLASS = "tooling/fixture validation"
STAGES = ("capture", "originals", "staging", "admission",
          "determinism", "reduction")
_EVIDENCE_ERRORS = (ReaderError, OSError, ValueError, TypeError, KeyError, IndexError)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _unit_census(run: Path) -> dict[str, Any]:
    """No-follow census of ONE captured unit directory."""
    inventory: dict[str, str] = {}
    files = 0
    total = 0
    for path in sorted(run.rglob("*")):
        rel = path.relative_to(run).as_posix()
        if path.is_symlink() or path.is_dir():
            continue
        data = path.read_bytes()
        inventory[rel] = _sha(data)
        files += 1
        total += len(data)
    canonical = json.dumps(inventory, sort_keys=True, indent=2) + "\n"
    return {"files": files, "bytes": total,
            "inventory_sha256": _sha(canonical.encode())}


def _census(root: Path) -> tuple[dict[str, dict[str, Any]], list[str]]:
    """No-follow census of retained originals under a case/tag unit.

    Returns per-unit file/byte counts plus a canonical inventory digest
    over {relative path: sha256} so later stages (and the record itself)
    bind to the exact retained byte population.
    """
    problems: list[str] = []
    units: dict[str, dict[str, Any]] = {}
    if root.is_symlink() or not root.is_dir():
        return units, [f"retained custody root missing or unsafe: {root}"]
    inventory: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).as_posix()
        if path.is_symlink():
            problems.append(f"symlink in retained custody: {rel}")
            continue
        if path.is_dir():
            continue
        mode = path.stat().st_mode
        if not stat.S_ISREG(mode):
            problems.append(f"non-regular retained file: {rel}")
            continue
        data = path.read_bytes()
        inventory[rel] = _sha(data)
        parts = rel.split("/")
        if len(parts) >= 3:
            # rel is <case>/<tag>/<retained file...> under the source root
            key = "/".join(parts[:2])
            entry = units.setdefault(key, {"files": 0, "bytes": 0,
                                           "_digests": {}})
            entry["files"] += 1
            entry["bytes"] += len(data)
            entry["_digests"]["/".join(parts[2:])] = inventory[rel]
        else:
            problems.append(f"retained file outside <case>/<tag>/: {rel}")
    canonical = json.dumps(inventory, sort_keys=True, indent=2) + "\n"
    digest = _sha(canonical.encode())
    rebuilt: dict[str, dict[str, Any]] = {}
    for key, entry in units.items():
        unit_canonical = (json.dumps(entry["_digests"], sort_keys=True,
                                     indent=2) + "\n")
        rebuilt[key] = {"files": entry["files"], "bytes": entry["bytes"],
                        "inventory_sha256": _sha(unit_canonical.encode()),
                        "population_sha256": digest}
    return rebuilt, problems


def _blocked(stages: dict[str, Any], problems: list[str],
             orchestration: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"schema": SCHEMA, "status": "blocked", "stages": stages,
            "problems": problems, "candidate_launches": 0,
            "orchestration": orchestration}


def run_integration_278(source_root: Path, staged_root: Path,
                         producer: Callable[[str, str, bool], Any],
                         executor: Callable[[str], Any],
                         pair_comparison: Callable[[str, dict, dict], Any],
                         cases: tuple[str, ...] | None = None) -> dict[str, Any]:
    """Run the complete integrated chain once. Fail-closed at every stage.

    producer(case, arm, repeat) must drive the production #275 collector
    so the retained originals land under source_root/source/<case>/<tag>/.
    The returned path is cross-checked against the custody layout: a
    capture that did not land in collector custody fails closed BEFORE
    any staging write.
    """
    source_root, staged_root = Path(source_root), Path(staged_root)
    cases = tuple(C.FIXTURE_CASES) if cases is None else tuple(cases)
    stages: dict[str, Any] = {}
    problems: list[str] = []
    # ---- capture ----------------------------------------------------------
    capture_units: dict[str, dict[str, Any]] = {}
    for case in cases:
        for arm in ("reference", "candidate"):
            for repeat in (False, True):
                tag = arm + ("-repeat" if repeat else "")
                key = f"{case}/{tag}"
                try:
                    run_path = Path(producer(case, arm, repeat))
                except _EVIDENCE_ERRORS as exc:
                    problems.append(f"{key}: capture producer failed: {exc}")
                    continue
                expected = source_root / "source" / case / tag
                if run_path != expected or not expected.is_dir():
                    problems.append(
                        f"{key}: capture did not land in collector custody "
                        f"(expected {expected}, producer reported {run_path})")
                    continue
                capture_units[key] = {"path": expected.as_posix(),
                                      **_unit_census(expected)}
    stages["capture"] = {"units": capture_units}
    if problems or len(capture_units) != len(cases) * 4:
        problems.append("capture stage incomplete — refusing to stage")
        return _blocked(stages, problems)
    # ---- originals --------------------------------------------------------
    originals, census_problems = _census(source_root / "source")
    stages["originals"] = {"units": originals}
    problems.extend(census_problems)
    for key, captured in capture_units.items():
        observed = originals.get(key, {})
        if (observed.get("inventory_sha256") != captured.get("inventory_sha256")
                or observed.get("files") != captured.get("files")
                or observed.get("bytes") != captured.get("bytes")):
            problems.append(
                f"{key}: retained originals drifted from the bytes the "
                f"capture stage censused (custody integrity failure)")
    if problems or set(originals) != set(capture_units):
        problems.append("retained-original census does not match the captured units")
        return _blocked(stages, problems)
    # ---- staging + admission ----------------------------------------------
    staged_units: dict[str, dict[str, Any]] = {}
    admitted_units: dict[str, dict[str, Any]] = {}
    for key in sorted(capture_units):
        case, tag = key.split("/")
        arm = tag[:-7] if tag.endswith("-repeat") else tag
        repeat = tag.endswith("-repeat")
        try:
            stage_capture_276(source_root, staged_root, case, arm, repeat)
            verdict = admit_staged_276(staged_root, case, arm, repeat,
                                       custody_root=source_root)
        except _EVIDENCE_ERRORS as exc:
            problems.append(f"{key}: staging/admission failed: {exc}")
            continue
        staged_units[key] = {"binding": f"units/{case}/{tag}.json"}
        admitted = {k: v for k, v in verdict.items() if k != "derived"}
        derived = verdict.get("derived") or {}
        admitted["source_stem"] = f"source/{case}/{tag}"
        admitted["derived"] = {"backend": derived.get("backend"),
                               "used_bdf": derived.get("used_bdf"),
                               "icd": derived.get("icd"),
                               "row_sha256": derived.get("row_sha256")}
        admitted_units[key] = admitted
        if verdict.get("admitted") is not True:
            problems.extend(f"{key}: {p}" for p in verdict.get("problems", []))
    stages["staging"] = {"units": staged_units}
    stages["admission"] = {"units": admitted_units}
    if problems:
        return _blocked(stages, problems)
    # ---- determinism + reference-first orchestration ------------------------
    launch_probe = _LaunchProbe()
    orchestration = O.orchestrate_277(
        staged_root, source_root,
        lambda case: (launch_probe.record(case), executor(case))[1],
        pair_comparison)
    launch_probe.attach(orchestration)
    stages["determinism"] = {
        "status": orchestration.get("status"),
        "terminal": orchestration.get("terminal"),
        "cases": {case: {arm: {"deterministic": item.get("deterministic"),
                                "primary_admitted": item.get("primary_admitted"),
                                "repeat_admitted": item.get("repeat_admitted")}
                         for arm, item in arms.items()}
                  for case, arms in orchestration.get("cases", {}).items()}}
    if orchestration.get("status") != "candidate gate reached":
        problems.extend(orchestration.get("problems", []))
        return _blocked(stages, problems, orchestration)
    # ---- reduction: the fixture chain cannot mint physical authority -------
    reduction = R.derive_terminal_273(orchestration, orchestration)
    stages["reduction"] = {"terminal": reduction.get("terminal"),
                           "problems": reduction.get("problems", []),
                           "note": "in-memory fixture records are not "
                                   "retained-byte evidence authority"}
    if reduction.get("terminal") != R.TERMINAL_RUNTIME_BLOCKED_273:
        problems.append("integrated fixture record unexpectedly carried "
                        "physical terminal authority")
        return _blocked(stages, problems, orchestration)
    return {"schema": SCHEMA, "status": INTEGRATION_COMPLETE,
            "evidence_class": EVIDENCE_CLASS, "stages": stages,
            "problems": [], "candidate_launches": orchestration["candidate_launches"],
            "orchestration": orchestration}


def evaluate_278(staged_root: Path, custody_root: Path,
                 executor: Callable[[str], Any],
                 pair_comparison: Callable[[str, dict, dict], Any]) -> dict[str, Any]:
    """Re-run admission→determinism over an ALREADY staged population.

    Used by tamper regressions: staged-side or custody-side byte edits
    after a completed integrated run must fail closed here.
    """
    launch_probe = _LaunchProbe()
    orchestration = O.orchestrate_277(
        Path(staged_root), Path(custody_root),
        lambda case: (launch_probe.record(case), executor(case))[1],
        pair_comparison)
    launch_probe.attach(orchestration)
    if orchestration.get("status") != "candidate gate reached":
        return _blocked({}, orchestration.get("problems", []), orchestration)
    reduction = R.derive_terminal_273(orchestration, orchestration)
    return {"schema": SCHEMA,
            "status": INTEGRATION_COMPLETE if not orchestration.get("problems") else "blocked",
            "evidence_class": EVIDENCE_CLASS,
            "stages": {"reduction": {"terminal": reduction.get("terminal")}},
            "problems": orchestration.get("problems", []),
            "candidate_launches": orchestration["candidate_launches"],
            "orchestration": orchestration}


class _LaunchProbe:
    """Observes executor invocations without being evidence."""

    def __init__(self) -> None:
        self.launches: list[str] = []
        self._host: dict[str, Any] | None = None

    def record(self, case: str) -> None:
        self.launches.append(case)
        if self._host is not None:
            observed = list(self.launches)
            actual = list(self._host.get("_executor_launches", []))
            if observed != actual:
                self._host["_executor_launches"] = observed

    def attach(self, orchestration: dict[str, Any]) -> None:
        self._host = orchestration
        orchestration["_executor_launches"] = list(self.launches)


def compact_stage(stage: dict[str, Any]) -> str:
    """One-line summary used by the first demonstration."""
    units = stage.get("units")
    if isinstance(units, dict) and units:
        key = sorted(units)[0]
        return (f"{len(units)} units; e.g. {key}: "
                + json.dumps({k: v for k, v in units[key].items()
                              if k != "derived"}, sort_keys=True)[:160])
    return json.dumps({k: v for k, v in stage.items()
                       if k not in ("units", "cases")}, sort_keys=True)[:160]


if __name__ == "__main__":  # pragma: no cover — manual entry point
    import sys
    sys.exit("The #278 first demonstration is owned by "
             "tests.test_issue278_integration (registered CI suite); "
             "this module is a library, not a runnable demonstration.")
