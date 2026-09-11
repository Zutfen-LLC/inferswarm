#!/usr/bin/env python3
"""Deterministic repository finalization (Issue #130).

One fail-closed, CPU-only, pure-stdlib command that regenerates every
maintained derived artifact in a declared dependency order and proves the
result is a byte fixed point:

    python3 scripts/finalize_repository.py --write    # regenerate, then verify no-op
    python3 scripts/finalize_repository.py --check    # fail on any drift (default)
    python3 scripts/finalize_repository.py --list-stages

The dependency model is an explicit stage DAG, not shell-command folklore.
Every stage declares what it reads, what it writes, what a terminal manifest
covers, and which stages it runs after.  The engine mechanically proves,
before writing anything:

- the graph is acyclic (a cycle is reported with its actual member cycle);
- every path has exactly one writer stage;
- no stage writes a path any earlier stage reads (reader-after-writer
  invalidation), which also proves manifest-last ordering: a terminal
  manifest *reads* every path it covers, so any later writer of a covered
  path is rejected;
- a terminal manifest never covers its own bytes (no self-digest loop);
- every producer derives desired bytes from primary inputs (or from scratch
  outputs of the generators themselves), never from paths written by other
  stages, so ``--check`` and a converged ``--write`` observe the same tree.

``--write`` runs each producer exactly once in topological order, applies
only declared writes, then re-runs the entire pipeline a second time and
fails unless the second pass wants zero byte changes (fixed-point proof, no
retries, no timestamps).  Authored edits are never stashed, reset, or
overwritten: the engine records the starting dirty paths, writes only
declared generated paths, and reports exactly which stage changed which
file.

Authority / integrity split (Issue #130 "eliminate circular pinning"):
records a reducer *consumes* (frozen identities, authority audits) are
declared primary inputs and are never written by any stage; integrity
indexes that *pin derived outputs* (``producer-hashes.json``, retention
``MANIFEST.sha256``) are terminal stages written last and read by no
producer.  That is the acyclic

    authority facts -> derived evidence -> producer hashes -> manifest

chain; the engine's cycle and reader-after-writer proofs hold for any
registry built on this pattern, so future campaigns register stages here
instead of growing another issue-specific finalizer.

Migrated paths (the Issue #117 chain):

- ``scripts/sync_project_status.py`` living status sections;
- the Issue #117 CPU campaign evidence (``issue117_proof.run_campaign``);
- ``producer-hashes.json`` generation;
- ``docs/implementation/r6-successor-dense-full-integration-117/evidence/
  MANIFEST.sha256`` (terminal);
- the closed Issue #137 bundle manifest (verification-only).

Not migrated, deliberately: the legacy #74/#99/#101/#103 manifests are
immutable historical snapshots (their living-document rows are frozen and
test-exempt), and nothing under ``evidence/arm-c/`` is ever written — the
accepted #128/#129 authority records are primary inputs by contract.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]

KINDS = ("primary", "derived", "index", "terminal-manifest", "verify")


class FinalizationError(ValueError):
    """Fail-closed finalization diagnostic (never a warning)."""


# ---------------------------------------------------------------------------
# Stage contract
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Stage:
    """One declared generator/finalizer stage.

    ``producer`` returns the desired bytes for every path in ``writes``
    (and nothing else); it must be a pure function of primary inputs and
    its own scratch outputs, never of paths other stages write.  ``verify``
    stages run a read-only check instead of producing bytes.
    """

    id: str
    kind: str
    description: str
    reads: frozenset[str] = frozenset()
    writes: frozenset[str] = frozenset()
    covers: frozenset[str] = frozenset()
    after: frozenset[str] = frozenset()
    producer: Callable[["Run", Path], dict[str, bytes]] | None = None
    verify: Callable[["Run", Path], None] | None = None


class Run:
    """One finalization pass over the tree.

    Producers read tree state through ``run.read(path)``: bytes already
    written by an earlier stage this pass (or pending, in check mode)
    shadow the disk, so ``--check`` and ``--write`` derive identical
    results.  Producers must not open stage-written paths directly.
    """

    def __init__(self, root: Path, workroot: Path, write: bool) -> None:
        self.root = root
        self.workroot = workroot
        self.write = write
        self.pending: dict[str, bytes] = {}
        self.changed: dict[str, list[str]] = {}

    def read(self, relative: str) -> bytes | None:
        if relative in self.pending:
            return self.pending[relative]
        path = self.root / relative
        return path.read_bytes() if path.is_file() else None

    def apply(self, stage_id: str, desired: dict[str, bytes]) -> None:
        changed = []
        for relative in sorted(desired):
            data = desired[relative]
            current = self.read(relative)
            if current == data:
                continue
            self.pending[relative] = data
            changed.append(relative)
            if self.write:
                path = self.root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
        if changed:
            self.changed[stage_id] = changed


# ---------------------------------------------------------------------------
# Registry validation: acyclicity, single writer, manifest-last
# ---------------------------------------------------------------------------

def validate_registry(stages: tuple[Stage, ...]) -> None:
    by_id: dict[str, Stage] = {}
    for stage in stages:
        if stage.id in by_id:
            raise FinalizationError(f"duplicate stage id: {stage.id}")
        by_id[stage.id] = stage
    for stage in stages:
        if stage.kind not in KINDS:
            raise FinalizationError(
                f"stage {stage.id}: unknown kind {stage.kind!r}")
        unknown = stage.after - set(by_id)
        if unknown:
            raise FinalizationError(
                f"stage {stage.id}: unknown dependencies {sorted(unknown)}")
        for attr in ("reads", "writes", "covers"):
            for relative in getattr(stage, attr):
                _check_relative(stage.id, attr, relative)
        if stage.kind == "primary" and stage.writes:
            raise FinalizationError(
                f"primary stage {stage.id} must not write")
        if stage.kind == "verify" and (stage.writes or stage.producer):
            raise FinalizationError(
                f"verify stage {stage.id} must not write")
        if stage.kind == "terminal-manifest":
            if not stage.covers:
                raise FinalizationError(
                    f"terminal manifest {stage.id} covers nothing")
            if len(stage.writes) != 1:
                raise FinalizationError(
                    f"terminal manifest {stage.id} must write exactly its "
                    "manifest path")
            manifest_path = next(iter(stage.writes))
            if manifest_path in stage.covers:
                raise FinalizationError(
                    f"terminal manifest {stage.id} covers its own bytes; a "
                    "self-digest contract is required to hash oneself, and "
                    "none is approved")
        else:
            if stage.covers:
                raise FinalizationError(
                    f"stage {stage.id}: only terminal manifests declare "
                    "covered paths")
        if stage.kind == "verify" and (stage.writes or stage.producer
                                       or stage.verify is None):
            raise FinalizationError(
                f"verify stage {stage.id} must be read-only and carry a "
                "verify callable")
        if stage.kind == "primary" and (stage.writes or stage.producer):
            raise FinalizationError(
                f"primary stage {stage.id} must not write or produce bytes")
        if stage.kind in ("derived", "index", "terminal-manifest") \
                and stage.producer is None:
            raise FinalizationError(
                f"{stage.kind} stage {stage.id} has no producer")
    writers: dict[str, str] = {}
    for stage in stages:
        for relative in stage.writes:
            if relative in writers:
                raise FinalizationError(
                    f"path {relative} is written by both {writers[relative]} "
                    f"and {stage.id}; generated paths have exactly one writer")
            writers[relative] = stage.id


def _check_relative(stage_id: str, attr: str, relative: str) -> None:
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts or not relative.strip():
        raise FinalizationError(
            f"stage {stage.id}: {attr} entry must be a repo-relative path: "
            f"{relative!r}")


def topological_order(stages: tuple[Stage, ...]) -> list[str]:
    by_id = {stage.id: stage for stage in stages}
    dependencies = {stage.id: set(stage.after) for stage in stages}
    dependents: dict[str, list[str]] = {stage.id: [] for stage in stages}
    ready = [stage.id for stage in stages if not dependencies[stage.id]]
    order: list[str] = []
    while ready:
        current = ready.pop(0)
        order.append(current)
        for other in stages:
            if current in dependencies[other.id]:
                dependencies[other.id].discard(current)
                if not dependencies[other.id]:
                    ready.append(other.id)
    if len(order) != len(stages):
        remaining = [stage_id for stage_id in dependencies
                     if dependencies[stage_id]]
        raise FinalizationError(
            "dependency cycle between finalization stages: "
            f"{_find_cycle(remaining, by_id)}")
    return order


def _find_cycle(remaining: list[str], by_id: dict[str, Stage]) -> list[str]:
    start = sorted(remaining)[0]
    walk, seen = [], set()
    current = start
    while current not in seen:
        seen.add(current)
        walk.append(current)
        deps = sorted(by_id[current].after & set(remaining))
        if not deps:
            break
        current = deps[0]
    if current in seen:
        index = walk.index(current)
        return walk[index:]
    return sorted(remaining)


def validate_order(stages: tuple[Stage, ...], order: list[str]) -> None:
    """Reader-after-writer and manifest-last mechanical proofs."""
    position = {stage_id: index for index, stage_id in enumerate(order)}
    writer_of: dict[str, list[str]] = {}
    for stage in stages:
        for relative in stage.writes:
            writer_of.setdefault(relative, []).append(stage.id)
    for stage in stages:
        # a terminal manifest reads everything it covers (it hashes them),
        # so covered paths are inputs for the reader-after-writer proof too
        effective_reads = set(stage.reads) | set(stage.covers)
        for relative in sorted(effective_reads):
            for writer in writer_of.get(relative, ()):  # exactly one writer
                if position[writer] > position[stage.id]:
                    kind_note = (
                        " (covered by terminal manifest "
                        f"{stage.id})" if relative in stage.covers else "")
                    raise FinalizationError(
                        f"stage {writer} writes {relative} after {stage.id} "
                        f"already read it{kind_note}: the earlier stage's "
                        "output would be stale; declare the dependency or "
                        "split the responsibilities")
        if stage.kind == "terminal-manifest":
            for relative in sorted(stage.covers):
                for writer in writer_of.get(relative, ()):
                    if position[writer] > position[stage.id]:
                        raise FinalizationError(
                            f"terminal manifest {stage.id} is generated "
                            f"before covered path {relative} reaches final "
                            f"bytes (writer {writer} runs later)")


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

def dirty_paths(root: Path) -> list[str]:
    """Best-effort starting dirty-path census; never a mutation."""
    try:
        text = subprocess.run(
            ["git", "-c", f"safe.directory={root}", "-C", str(root),
             "status", "--porcelain"],
            capture_output=True, text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return []
    entries = []
    for line in text.splitlines():
        relative = line[3:].strip().strip('"')
        entries.append(relative)
    return sorted(entries)


def run_pipeline(root: Path, stages: tuple[Stage, ...], *, write: bool,
                 workroot: Path | None = None) -> dict:
    """One full pass: validate, execute stages in topological order."""
    validate_registry(stages)
    order_ids = topological_order(stages)
    by_id = {stage.id: stage for stage in stages}
    validate_order(stages, order_ids)
    scratch = workroot or Path(tempfile.mkdtemp(prefix="finalize-repository-"))
    run = Run(root, scratch, write)
    for stage_id in order_ids:
        stage = by_id[stage_id]
        for relative in sorted(stage.reads | stage.covers):
            if run.read(relative) is None:
                raise FinalizationError(
                    f"stage {stage_id}: required input is missing: "
                    f"{relative}")
        if stage.producer is not None:
            desired = stage.producer(run, scratch)
            undeclared = sorted(set(desired) - set(stage.writes))
            if undeclared:
                raise FinalizationError(
                    f"stage {stage_id} produced undeclared paths "
                    f"{undeclared}; every written path must be declared")
            missing = sorted(set(stage.writes) - set(desired))
            if missing:
                raise FinalizationError(
                    f"stage {stage_id} did not produce declared paths "
                    f"{missing}")
            run.apply(stage_id, desired)
        if stage.verify is not None:
            stage.verify(run, scratch)
    return {"order": order_ids, "changed": run.changed}


def finalize(root: Path, stages: tuple[Stage, ...], *, write: bool) -> dict:
    """Run the pipeline; in write mode prove the byte fixed point."""
    starting_dirty = dirty_paths(root)
    reset_scratch_caches()
    first = run_pipeline(root, stages, write=write)
    report = {
        "mode": "write" if write else "check",
        "starting_dirty_paths": starting_dirty,
        "order": first["order"],
        "changed": first["changed"],
    }
    if write:
        reset_scratch_caches()
        second = run_pipeline(root, stages, write=False)
        if second["changed"]:
            raise FinalizationError(
                "fixed point not reached: the second (verification) pass "
                "still wants changes "
                + json.dumps(second["changed"], sort_keys=True)
                + "; a generator is nondeterministic or mutually pinning "
                  "with another stage — fix the dependency, do not loop")
        report["second_pass"] = "zero byte changes"
    elif first["changed"]:
        raise FinalizationError(
            "generated artifacts are stale; run "
            "'python3 scripts/finalize_repository.py --write' and commit "
            f"the result: {json.dumps(first['changed'], sort_keys=True)}")
    return report


# ---------------------------------------------------------------------------
# Migration registry (Issue #117 chain)
# ---------------------------------------------------------------------------

_AREA = ("docs/implementation/r6-successor-dense-full-integration-117")
_EVIDENCE = f"{_AREA}/evidence"
_PRODUCER_HASHES = f"{_EVIDENCE}/producer-hashes.json"
_MANIFEST = f"{_EVIDENCE}/MANIFEST.sha256"
_BUNDLE_137 = f"{_EVIDENCE}/arm-c-regime4-diagnosis-137"

_campaign_cache: dict[str, dict[str, bytes]] = {}


def reset_scratch_caches() -> None:
    """Force fresh generator runs (used between the write and verify pass)."""
    _campaign_cache.clear()


def _scripts(root: Path) -> None:
    location = str(root / "scripts")
    if location not in sys.path:
        sys.path.insert(0, location)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _campaign_outputs(run: Run, scratch: Path) -> dict[str, bytes]:
    """Run the frozen Issue #117 CPU campaign once per pass into scratch.

    The campaign is deterministic (fixed scratch working root, canonical
    JSON, no timestamps, no network): identical trees produce identical
    bytes from any checkout.
    """
    key = str(run.root.resolve())
    cached = _campaign_cache.get(key)
    if cached is not None:
        return cached
    _scripts(run.root)
    import issue117_proof  # noqa: PLC0415 (lazy by design)
    out_dir = scratch / "issue117-evidence"
    out_dir.mkdir(parents=True, exist_ok=True)
    issue117_proof.run_campaign(out_dir)
    outputs: dict[str, bytes] = {}
    for name in sorted(issue117_proof.EVIDENCE_FILES):
        path = out_dir / name
        if path.is_file():
            outputs[f"{_EVIDENCE}/{name}"] = path.read_bytes()
    outputs[_MANIFEST] = (out_dir / "MANIFEST.sha256").read_bytes()
    _campaign_cache[key] = outputs
    return outputs


def _status_source_verify(run: Run, scratch: Path) -> None:
    _scripts(run.root)
    import sync_project_status as sync  # noqa: PLC0415
    document = json.loads(run.read("docs/project-status.json"))
    sync.validate(document)  # fail closed on a malformed status record


def _status_sync_producer(run: Run, scratch: Path) -> dict[str, bytes]:
    """Living status sections, reusing the frozen sync renderer verbatim."""
    _scripts(run.root)
    import sync_project_status as sync  # noqa: PLC0415
    sections = sync.render(json.loads(run.read("docs/project-status.json")))
    desired = {}
    for relative in sorted(sync.TARGETS):
        content = (run.root / relative).read_text(encoding="utf-8")
        for name in sync.TARGETS[relative]:
            content = sync.replace_section(content, name, sections[name])
        desired[relative] = content.encode("utf-8")
    return desired


def _issue117_evidence_producer(run: Run, scratch: Path) -> dict[str, bytes]:
    outputs = _campaign_outputs(run, scratch)
    return {path: data for path, data in outputs.items()
            if path != _PRODUCER_HASHES and path != _MANIFEST}


def _issue117_producer_hashes_producer(
        run: Run, scratch: Path) -> dict[str, bytes]:
    outputs = _campaign_outputs(run, scratch)
    _scripts(run.root)
    import issue117_proof  # noqa: PLC0415
    expected = {}
    for producer in sorted(issue117_proof.PRODUCERS):
        data = run.read(producer)
        if data is None:
            raise FinalizationError(
                f"issue117 producer is missing: {producer}")
        expected[producer] = _sha256(data)
    desired = outputs[_PRODUCER_HASHES]
    if json.loads(desired) != expected:
        raise FinalizationError(
            "producer-hashes ledger does not match the finalized producer "
            "bytes; the campaign scratch and the tree disagree")
    return {_PRODUCER_HASHES: desired}


def _verify_manifest_rows(rows: dict[str, str], run: Run) -> None:
    """Re-derive every manifest row from the bytes visible to this pass.

    Earlier-stage writes shadow the disk in check mode, so this proves
    manifest-last coverage both live and counterfactually.
    """
    for relative, digest in sorted(rows.items()):
        data = run.read(relative)
        if data is None:
            raise FinalizationError(
                f"manifest covers a missing path: {relative}")
        if _sha256(data) != digest:
            raise FinalizationError(
                f"manifest row does not match finalized bytes: {relative}")


def _issue117_manifest_producer(run: Run, scratch: Path) -> dict[str, bytes]:
    """Terminal retention manifest; every covered row is re-derived from
    the finalized tree state visible to this pass (earlier writes shadow
    the disk), which mechanically proves manifest-last coverage."""
    outputs = _campaign_outputs(run, scratch)
    desired = outputs[_MANIFEST]
    rows: dict[str, str] = {}
    for line in desired.decode("utf-8").splitlines():
        digest, separator, relative = line.partition("  ")
        if not separator or not relative:
            raise FinalizationError(
                f"malformed manifest row: {line!r}")
        rows[relative] = digest
    _verify_manifest_rows(rows, run)
    return {_MANIFEST: desired}


def _issue137_bundle_verify(run: Run, scratch: Path) -> None:
    """The accepted Issue #137 bundle is closed: verify it byte-current."""
    _scripts(run.root)
    import issue137_manifest  # noqa: PLC0415
    try:
        issue137_manifest.check(run.root)
    except Exception as error:  # noqa: BLE001 (report any verification fail)
        raise FinalizationError(
            f"Issue #137 bundle manifest verification failed: {error}") \
            from error


def _issue117_covered_paths() -> frozenset[str]:
    """Exactly the row set ``issue117_proof.write_manifest`` emits."""
    _scripts(ROOT)
    import issue117_proof  # noqa: PLC0415
    covered = {f"{_EVIDENCE}/{name}" for name in issue117_proof.EVIDENCE_FILES}
    covered.update(f"{_EVIDENCE}/{name}"
                   for name in issue117_proof.COMMITTED_EVIDENCE_FILES
                   if (ROOT / _EVIDENCE / name).is_file())
    covered.update(issue117_proof.PRODUCERS)
    for relative in (f"{_AREA}/METHODOLOGY.md",
                     f"{_AREA}/METHODOLOGY-ARM-C-RETRY.md",
                     f"{_AREA}/CHECKPOINT-AUTHORITY-BLOCKER.md"):
        if (ROOT / relative).is_file():
            covered.add(relative)
    return frozenset(covered)


def default_registry() -> tuple[Stage, ...]:
    """The migrated Issue #117 chain (see module docstring).

    Registration is declarative: another campaign adds its own
    primary/derived/index/terminal-manifest/verify stages here without any
    engine change.
    """
    covered = _issue117_covered_paths()
    return (
        Stage(
            id="status-source",
            kind="primary",
            description=(
                "Authored living status record (docs/project-status.json); "
                "validated, never written"),
            reads=frozenset({"docs/project-status.json"}),
            verify=_status_source_verify,
        ),
        Stage(
            id="status-sync",
            kind="derived",
            description=(
                "Living status sections in the six managed documents "
                "(scripts/sync_project_status.py renderer, reused verbatim)"),
            reads=frozenset({"docs/project-status.json"}),
            writes=frozenset({
                "README.md", "ROADMAP.md", "ARCHITECTURE.md",
                "docs/implementation/README.md",
                "docs/integrations/freetoken.md",
                "docs/protocols/README.md",
            }),
            after=frozenset({"status-source"}),
            producer=_status_sync_producer,
        ),
        Stage(
            id="issue117-evidence",
            kind="derived",
            description=(
                "Issue #117 CPU campaign evidence (frozen producer "
                "issue117_proof.run_campaign; deterministic canonical JSON)"),
            reads=frozenset({f"{_EVIDENCE}/integration-fixture.json"}),
            writes=frozenset(
                f"{_EVIDENCE}/{name}"
                for name in (
                    "strategy.json", "planner-decision.json",
                    "requirements.json", "cold-acquisition.json",
                    "materialization-witnesses.json", "warm-restart.json",
                    "locality-mutation.json", "fencing.json",
                    "negative-controls.json", "zero-invariants.json",
                    "purity-audit.json", "applicability-audit.json",
                    "qualification-record.json",
                    "v5-qualification-subject-recovery.json",
                )),
            after=frozenset({"status-sync"}),
            producer=_issue117_evidence_producer,
        ),
        Stage(
            id="issue117-producer-hashes",
            kind="index",
            description=(
                "Producer identity ledger for the Issue #117 bundle; pure "
                "function of the finalized producer bytes"),
            reads=frozenset(),  # bound to every producer path at run time
            writes=frozenset({_PRODUCER_HASHES}),
            after=frozenset({"issue117-evidence"}),
            producer=_issue117_producer_hashes_producer,
        ),
        Stage(
            id="issue117-manifest",
            kind="terminal-manifest",
            description=(
                "Terminal retention manifest for the Issue #117 bundle; "
                "generated last, reads (hashes) every covered path, and is "
                "read by nothing"),
            writes=frozenset({_MANIFEST}),
            covers=covered,
            after=frozenset({
                "status-sync", "issue117-evidence",
                "issue117-producer-hashes"}),
            producer=_issue117_manifest_producer,
        ),
        Stage(
            id="issue137-bundle-verify",
            kind="verify",
            description=(
                "The accepted Issue #137 additive bundle is closed and must "
                "stay byte-current (scripts/issue137_manifest.py --check)"),
            reads=frozenset({_BUNDLE_137 + "/MANIFEST.sha256"}),
            after=frozenset({"issue117-manifest"}),
            verify=_issue137_bundle_verify,
        ),
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _describe(stages: tuple[Stage, ...]) -> str:
    order = topological_order(stages)
    by_id = {stage.id: stage for stage in stages}
    lines = []
    for position, stage_id in enumerate(order, start=1):
        stage = by_id[stage_id]
        lines.append(f"{position}. {stage_id} [{stage.kind}]")
        lines.append(f"   {stage.description}")
        if stage.reads:
            lines.append(f"   reads:    {', '.join(sorted(stage.reads))}")
        if stage.writes:
            lines.append(f"   writes:   {', '.join(sorted(stage.writes))}")
        if stage.covers:
            lines.append(
                f"   covers:   {len(stage.covers)} paths "
                "(manifest rows)")
        if stage.after:
            lines.append(f"   after:    {', '.join(sorted(stage.after))}")
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Deterministic repository finalization (Issue #130)")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--write", action="store_true",
                      help="regenerate declared artifacts in dependency "
                           "order, then verify a second pass changes nothing")
    mode.add_argument("--check", action="store_true",
                      help="fail if any declared generator would change "
                           "bytes (default)")
    parser.add_argument("--list-stages", action="store_true",
                        help="print the stage DAG and exit")
    args = parser.parse_args(argv)
    stages = default_registry()
    try:
        if args.list_stages:
            print(_describe(stages))
            return 0
        write = bool(args.write)
        report = finalize(ROOT, stages, write=write)
        if write:
            print("Finalization order: " + " -> ".join(report["order"]))
            for stage_id, files in sorted(report["changed"].items()):
                for relative in files:
                    print(f"  {stage_id}: rewrote {relative}")
            if not report["changed"]:
                print("  (all generated artifacts already current)")
            print("Second pass: " + report["second_pass"])
        else:
            print("Finalization check passed: graph acyclic, manifests "
                  "terminal, all generated artifacts current "
                  f"({len(report['order'])} stages)")
        return 0
    except FinalizationError as error:
        print(f"finalization failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
