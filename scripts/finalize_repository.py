#!/usr/bin/env python3
"""Deterministic repository finalization (Issue #130).

One fail-closed, CPU-only, pure-stdlib command that regenerates every
maintained derived artifact in a declared dependency order and proves the
result is a byte fixed point:

    python3 scripts/finalize_repository.py --write    # regenerate, then verify no-op
    python3 scripts/finalize_repository.py --check    # fail on any drift (default)
    python3 scripts/finalize_repository.py --list-stages

Three mechanical contracts, all proven by the engine itself:

Dependency contract (explicit stage DAG).  Every stage declares what it
reads, what it writes, what a terminal manifest covers, and which stages
it runs after.  Declarations are derived from the canonical constants of
the producers themselves (``sync_project_status.TARGETS``,
``issue117_proof.PRODUCERS``, the pinned authority dictionaries in
``issue117_applicability`` and ``issue117_accepted_subject``, and
``issue137_manifest``'s bundle constants) — never hand-maintained
duplicates.  Before writing anything the engine mechanically proves:

- the graph is acyclic (a cycle is reported with its member cycle);
- every generated path has exactly one writer stage;
- no stage writes a path any earlier stage reads (reader-after-writer
  invalidation), which also proves manifest-last ordering: a terminal
  manifest *reads* every path it covers, so any later writer of a
  covered path is rejected;
- a terminal manifest never covers its own bytes (no self-digest loop).

A stage that consumes the existing bytes of a path it also writes — the
status-sync managed documents carry authored content outside their
generated sections, and those bytes are inputs to the desired bytes —
declares the path in BOTH ``reads`` and ``writes`` (a self-input).  The
reader-after-writer proof treats the stage as its own reader, so the
declaration is represented mechanically while no other stage may
interleave a write between the read and the write.

Isolation contract (callables cannot silently mutate the repository).
Stage producers and verifiers never execute against the real working
tree.  Each pass materializes a sandbox containing byte copies of every
declared input and declared write path; ``run.root`` IS the sandbox,
callables run with the sandbox as their working directory, and
``Run.read`` mediates reads (pending stage outputs shadow the sandbox
bytes, so ``--check`` and a converged ``--write`` derive identical
results).  Around every producer and verify callable the engine compares
full content digests of the sandbox tree and of the real worktree
dirty/untracked census (tracked AND untracked paths).  Any direct write,
modification, deletion, or rename — against the sandbox, or against the
real tree via an absolute path — fails closed BEFORE any declared write
is applied, and the worktree is restored from a starting byte snapshot:
authored dirty/untracked bytes from engine-made copies, and clean
tracked bytes re-read read-only from the git object store.
``git reset``/``checkout``/``clean``/``stash`` are never used as
recovery.  ``--check`` is mechanically no-write: the engine's apply step
is the only code that ever writes the real tree, and it does not run in
check mode.

Transaction contract.  ``--write`` records the starting dirty paths
(NUL-delimited porcelain so spaces, quoting, renames, copies, and
untracked paths are unambiguous; failure to obtain trustworthy status is
a hard error, never an empty census), runs each producer exactly once in
topological order, applies only declared writes, then re-runs the entire
pipeline and fails unless the second pass wants zero byte changes
(fixed-point proof, no retries, no timestamps).

Authority / integrity split (Issue #130 "eliminate circular pinning"):
records a reducer *consumes* — frozen identities, the pinned V5
authority files, the physical-identity evidence, the accepted-subject
evidence package, the frozen producer-delta audit, and the immutable
accepted Arm-C records under ``evidence/arm-c/`` — are registered as the
``issue117-authority`` primary stage's declared reads: part of the actual
registry, not prose, and never written by any stage.  Integrity indexes
that *pin derived outputs* (``producer-hashes.json``, retention
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
import contextlib
import hashlib
import importlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator

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
    (and nothing else); it must be a pure function of declared inputs and
    its own scratch outputs.  ``verify`` stages run a read-only check
    instead of producing bytes.  Producers and verifiers execute inside
    the engine sandbox (``run.root`` is the sandbox, not the repository)
    and must perform all tree reads through ``run.read``; direct
    filesystem mutation beneath the sandbox or the real repository is
    detected and fails closed.
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
    """One finalization pass, executed against the sandbox.

    ``root`` is the per-pass sandbox (byte copies of every declared
    input), never the real working tree.  Producers read tree state
    through ``run.read(path)``: bytes already written by an earlier stage
    this pass shadow the sandbox copies, so ``--check`` and ``--write``
    derive identical results.  ``Run.apply`` records desired bytes; the
    engine — and only the engine — writes them to the real tree during
    the apply step of a ``--write`` run.
    """

    def __init__(self, sandbox: Path, workroot: Path) -> None:
        self.root = sandbox
        self.workroot = workroot
        self.pending: dict[str, bytes] = {}
        self.mutations: dict[str, bytes] = {}
        self.changed: dict[str, list[str]] = {}

    def read(self, relative: str) -> bytes | None:
        if relative in self.pending:
            return self.pending[relative]
        path = self.root / relative
        return path.read_bytes() if path.is_file() else None

    def apply(self, stage_id: str, desired: dict[str, bytes]) -> None:
        """Record desired bytes and update the sandbox shadow state.

        Nothing here touches the real working tree; the engine's apply
        step does that, once, for declared paths only.
        """
        changed = []
        for relative in sorted(desired):
            data = desired[relative]
            current = self.read(relative)
            if current == data:
                continue
            self.pending[relative] = data
            self.mutations[relative] = data
            sandbox_path = self.root / relative
            sandbox_path.parent.mkdir(parents=True, exist_ok=True)
            sandbox_path.write_bytes(data)
            changed.append(relative)
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
        if stage.kind == "primary" and stage.producer is not None:
            raise FinalizationError(
                f"primary stage {stage.id} must not produce bytes")
        if stage.kind == "verify" and (stage.writes or stage.producer
                                       or stage.verify is None):
            raise FinalizationError(
                f"verify stage {stage.id} must be read-only and carry a "
                "verify callable")
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
        elif stage.covers:
            raise FinalizationError(
                f"stage {stage.id}: only terminal manifests declare "
                "covered paths")
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
    """Reader-after-writer and manifest-last mechanical proofs.

    A stage that both reads and writes the same path (a self-input, e.g.
    status-sync's managed documents) is its own reader: the proof only
    rejects OTHER stages whose write would interleave after the read.
    """
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
                            "bytes (writer {writer} runs later)")


# ---------------------------------------------------------------------------
# Fail-closed worktree census (NUL-delimited porcelain)
# ---------------------------------------------------------------------------

_STATUS_CHARS = frozenset(b"MADRCU?! ")


def _git(root: Path, *args: str) -> bytes:
    """Run git read-only plumbing beneath ``root``; fail closed."""
    try:
        finished = subprocess.run(
            ["git", "-c", f"safe.directory={root}", "-C", str(root), *args],
            capture_output=True, check=True)
    except (OSError, subprocess.CalledProcessError) as error:
        detail = ""
        if isinstance(error, subprocess.CalledProcessError):
            detail = (error.stderr or b"").decode("utf-8", "replace").strip()
        raise FinalizationError(
            f"unable to obtain trustworthy git state for {root} "
            f"(git {' '.join(args[:2])} failed"
            + (f": {detail}" if detail else "")
            + "); the finalizer fails closed rather than guess the "
            "starting worktree state") from error
    return finished.stdout


def _parse_porcelain_z(raw: bytes) -> list[str]:
    """Parse ``status --porcelain=v1 -z`` records into repo-relative paths.

    With ``-z`` every record is ``XY <path>`` NUL-delimited with no
    quoting; rename/copy records carry the old path as a following bare
    NUL token.  Anything unparseable fails closed.
    """
    paths: list[str] = []
    expect_old_path = False
    for token in raw.split(b"\0"):
        if not token:
            continue  # the trailing terminator
        if expect_old_path:
            paths.append(token.decode("utf-8", "surrogateescape"))
            expect_old_path = False
            continue
        if (len(token) < 4 or token[2:3] != b" "
                or any(byte not in _STATUS_CHARS for byte in token[:2])):
            raise FinalizationError(
                f"unparseable git status record: {token!r}; refusing to "
                "guess the starting worktree state")
        status = token[:2].decode("ascii")
        paths.append(token[3:].decode("utf-8", "surrogateescape"))
        if "R" in status or "C" in status:
            expect_old_path = True
    if expect_old_path:
        raise FinalizationError(
            "truncated git status record (rename/copy without its old "
            "path); refusing to guess the starting worktree state")
    return paths


def dirty_paths(root: Path) -> list[str]:
    """Fail-closed census of dirty paths (tracked + untracked).

    Returns a sorted, de-duplicated list of repo-relative paths that are
    modified, staged, deleted, renamed, copied, or untracked.  Any
    failure to obtain or parse trustworthy git status raises
    ``FinalizationError`` — a fail-closed command never proceeds with an
    invented empty census.
    """
    raw = _git(root, "status", "--porcelain=v1", "-z",
               "--untracked-files=all")
    return sorted(set(_parse_porcelain_z(raw)))


def _tracked_paths(root: Path) -> set[str]:
    raw = _git(root, "ls-files", "-z")
    return {token.decode("utf-8", "surrogateescape")
            for token in raw.split(b"\0") if token}


def _digest_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _worktree_census(root: Path) -> dict[str, str]:
    """Map every dirty/untracked path to its current content digest."""
    return {relative: _digest_file(root / relative)
            for relative in dirty_paths(root)
            if (root / relative).is_file()}


def _head_blob(root: Path, relative: str) -> tuple[bytes, int]:
    """Read a clean tracked file's committed bytes (read-only plumbing).

    Used ONLY to restore a file that was provably clean at the start of
    the run (its bytes were by definition identical to HEAD); git's
    reset/checkout/clean/stash machinery is never invoked.
    """
    try:
        blob = _git(root, "cat-file", "-p", f"HEAD:{relative}")
        tree_line = _git(root, "ls-tree", "HEAD", "--", relative)
    except FinalizationError:
        raise FinalizationError(
            f"cannot restore clean tracked path {relative} from HEAD; "
            "its bytes were never recorded in a commit") from None
    fields = tree_line.decode("utf-8", "replace").split()
    mode = int(fields[0], 8) & 0o777 if fields else 0o644
    return blob, mode


# ---------------------------------------------------------------------------
# Sandbox isolation and callable guards
# ---------------------------------------------------------------------------

def _sandbox_inputs(stages: tuple[Stage, ...]) -> frozenset[str]:
    inputs: set[str] = set()
    for stage in stages:
        inputs |= stage.reads | stage.writes | stage.covers
    return frozenset(inputs)


def _prepare_sandbox(root: Path, inputs: frozenset[str],
                     workroot: Path) -> Path:
    """Byte-copy every declared input into a fresh sandbox directory.

    The sandbox is what stage callables see as ``run.root``; the real
    working tree is never exposed to callable execution.
    """
    sandbox = workroot / "sandbox"
    for relative in sorted(inputs):
        source = root / relative
        if not source.is_file():
            continue  # missing inputs fail later with a precise stage error
        target = sandbox / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    return sandbox


def _sandbox_digests(sandbox: Path) -> dict[str, str]:
    """Content digests of every file in the sandbox tree.

    Any file the engine did not put there, or any byte change to one it
    did, is a direct filesystem side effect by a callable.  Interpreter
    bytecode caches (``__pycache__``) are excluded, mirroring the
    repository's own ``.gitignore``: they are deterministic artifacts of
    importing the declared producer sources, not callable-authored
    content — a callable can only influence a ``.pyc`` by first writing
    or modifying the ``.py`` beside it, which this digest catches.
    """
    digests: dict[str, str] = {}
    for path in sorted(sandbox.rglob("*")):
        if path.is_file() and path.parent.name != "__pycache__":
            digests[path.relative_to(sandbox).as_posix()] = \
                _digest_file(path)
    return digests


def _snapshot_starting_bytes(root: Path, workroot: Path
                             ) -> tuple[dict[str, str], Path, set[str]]:
    """Snapshot the authored starting state for fail-closed restoration.

    Copies every dirty/untracked file (authored bytes that exist nowhere
    else) into ``workroot/starting-bytes`` and records the tracked path
    set.  Restoration after a detected mutation rewrites dirty/untracked
    paths from these copies and clean tracked paths from their provably
    identical HEAD bytes.  Authored content can therefore never be
    destroyed by a failing callable — the very bytes that existed at the
    start are the ones restored.
    """
    census = _worktree_census(root)
    backup = workroot / "starting-bytes"
    for relative in sorted(census):
        source = root / relative
        target = backup / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    tracked = _tracked_paths(root)
    return census, backup, tracked


def _restore_worktree(root: Path, baseline: dict[str, str], backup: Path,
                      tracked: set[str], *, preserve: set[str]) -> list[str]:
    """Restore the worktree to its starting bytes after a mutation.

    ``preserve`` names declared engine writes that must survive (used
    after the apply step).  Returns the restored/deleted paths.
    """
    restored: list[str] = []
    current = _worktree_census(root)
    for relative in sorted(set(baseline) | set(current)):
        if relative in preserve:
            continue
        if baseline.get(relative) == current.get(relative):
            continue
        target = root / relative
        if relative in baseline:
            # authored content (dirty or untracked at start): restore the
            # exact starting bytes from the engine-made copy
            source = backup / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        elif relative in tracked:
            # clean and tracked at start: bytes provably identical to HEAD
            blob, mode = _head_blob(root, relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(blob)
            os.chmod(target, mode)
        else:
            # created during the run, never authored, never tracked:
            # engine debris — remove it
            target.unlink(missing_ok=True)
        restored.append(relative)
    return restored


@contextlib.contextmanager
def _callable_guard(root: Path, sandbox: Path, stage_id: str, role: str,
                    baseline: dict[str, str], backup: Path,
                    tracked: set[str]) -> Iterator[None]:
    """Detect any direct filesystem side effect of one stage callable.

    Compares full content digests of the sandbox and a dirty/untracked
    census of the REAL worktree before and after the callable.  On any
    difference: restore the worktree to its starting bytes and fail
    closed.  Nothing here relies on the callable reporting its writes
    honestly.
    """
    sandbox_before = _sandbox_digests(sandbox)
    census_before = _worktree_census(root)
    previous_cwd = Path(os.getcwd())
    os.chdir(sandbox)
    try:
        yield
    finally:
        os.chdir(previous_cwd)
        damage: list[str] = []
        sandbox_after = _sandbox_digests(sandbox)
        if sandbox_after != sandbox_before:
            touched = sorted(
                path for path in set(sandbox_after) | set(sandbox_before)
                if sandbox_after.get(path) != sandbox_before.get(path))
            damage.append(
                "directly mutated the stage sandbox (undeclared "
                f"filesystem writes): {touched}")
        census_after = _worktree_census(root)
        if census_after != census_before:
            touched = sorted(
                path for path in set(census_after) | set(census_before)
                if census_after.get(path) != census_before.get(path))
            damage.append(
                f"directly mutated the repository worktree: {touched}")
            _restore_worktree(root, baseline, backup, tracked,
                              preserve=set())
        if damage:
            raise FinalizationError(
                f"stage {stage_id} {role} escaped the engine contract: "
                + "; ".join(damage)
                + "; the repository was restored to its starting bytes "
                "and no declared writes from this pass were applied")


def _purge_script_modules(sandbox: Path | None) -> None:
    """Drop imported ``scripts/`` modules so imports bind to the sandbox.

    Producer modules (issue117_proof, sync_project_status, ...) derive
    their repository ROOT from their import location.  Before a pass they
    are purged unless already bound to this sandbox, so the campaign and
    its authority verification read the sandbox copies; after a pass the
    sandbox-bound copies are purged so later imports (tests, other
    tooling) rebind to a real checkout.  This module itself is never
    purged.
    """
    self_path = Path(__file__).resolve()
    sandbox_scripts = (sandbox / "scripts").resolve() if sandbox else None
    for name, module in list(sys.modules.items()):
        file = getattr(module, "__file__", None)
        if not file:
            continue
        try:
            path = Path(file).resolve()
        except OSError:
            continue
        if path == self_path or path.parent.name != "scripts":
            continue
        if sandbox_scripts is not None and path.parent == sandbox_scripts:
            continue
        del sys.modules[name]
    importlib.invalidate_caches()


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

def run_pipeline(root: Path, stages: tuple[Stage, ...], *, write: bool,
                 workroot: Path | None = None) -> dict:
    """One full pass: validate, execute stages in topological order.

    With ``write=True`` the engine applies the pass's declared mutations
    to the real tree after the pass completes; with ``write=False``
    nothing is applied (the mechanically read-only check mode).
    """
    managed = workroot or Path(tempfile.mkdtemp(prefix="finalize-repository-"))
    baseline, backup, tracked = _snapshot_starting_bytes(root, managed)
    try:
        report = _execute_pass(root, stages, managed,
                               baseline, backup, tracked)
        if write and report["mutations"]:
            _apply_mutations(root, report["mutations"])
        return report
    finally:
        if workroot is None:
            shutil.rmtree(managed, ignore_errors=True)


def _execute_pass(root: Path, stages: tuple[Stage, ...], workroot: Path,
                  baseline: dict[str, str], backup: Path,
                  tracked: set[str]) -> dict:
    """Execute one sandboxed pass; the real tree is never written here."""
    validate_registry(stages)
    order_ids = topological_order(stages)
    by_id = {stage.id: stage for stage in stages}
    validate_order(stages, order_ids)
    sandbox = _prepare_sandbox(root, _sandbox_inputs(stages), workroot)
    _purge_script_modules(sandbox)
    run = Run(sandbox, workroot)
    for stage_id in order_ids:
        stage = by_id[stage_id]
        for relative in sorted(stage.reads | stage.covers):
            if run.read(relative) is None:
                raise FinalizationError(
                    f"stage {stage_id}: required input is missing: "
                    f"{relative}")
        if stage.producer is not None:
            with _callable_guard(root, sandbox, stage_id, "producer",
                                 baseline, backup, tracked):
                desired = stage.producer(run, workroot)
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
            with _callable_guard(root, sandbox, stage_id, "verify",
                                 baseline, backup, tracked):
                stage.verify(run, workroot)
    return {"order": order_ids, "changed": run.changed,
            "mutations": run.mutations}


def _apply_mutations(root: Path, mutations: dict[str, bytes]) -> None:
    """The ONLY code that writes the real working tree.

    Declared paths, engine bytes, one pass, after every stage has run.
    """
    for relative in sorted(mutations):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(mutations[relative])


def finalize(root: Path, stages: tuple[Stage, ...], *, write: bool) -> dict:
    """Run the pipeline; in write mode prove the byte fixed point."""
    starting_dirty = dirty_paths(root)  # fail closed on untrustworthy state
    workroot = Path(tempfile.mkdtemp(prefix="finalize-repository-"))
    try:
        baseline, backup, tracked = \
            _snapshot_starting_bytes(root, workroot)
        reset_scratch_caches()
        first = _execute_pass(root, stages, workroot,
                              baseline, backup, tracked)
        report = {
            "mode": "write" if write else "check",
            "starting_dirty_paths": starting_dirty,
            "order": first["order"],
            "changed": first["changed"],
        }
        if write:
            _apply_mutations(root, first["mutations"])
            # post-apply audit: nothing outside the declared writes may
            # have changed; restore anything that did
            after = _worktree_census(root)
            allowed = set(first["mutations"])
            unexpected = {
                relative for relative in set(baseline) | set(after)
                if relative not in allowed
                and baseline.get(relative) != after.get(relative)}
            if unexpected:
                _restore_worktree(root, baseline, backup, tracked,
                                  preserve=allowed)
                raise FinalizationError(
                    "the worktree changed outside the declared writes "
                    f"during the apply step: {sorted(unexpected)}; the "
                    "repository was restored to its starting bytes")
            reset_scratch_caches()
            second = _execute_pass(root, stages, workroot,
                                   baseline, backup, tracked)
            if second["mutations"]:
                raise FinalizationError(
                    "fixed point not reached: the second (verification) "
                    "pass still wants changes "
                    + json.dumps(second["changed"], sort_keys=True)
                    + "; a generator is nondeterministic or mutually pinning "
                      "with another stage — fix the dependency, do not loop")
            report["second_pass"] = "zero byte changes"
        elif first["mutations"]:
            raise FinalizationError(
                "generated artifacts are stale; run "
                "'python3 scripts/finalize_repository.py --write' and commit "
                f"the result: {json.dumps(first['changed'], sort_keys=True)}")
        return report
    finally:
        _purge_script_modules(None)
        shutil.rmtree(workroot, ignore_errors=True)


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
    bytes from any checkout.  It executes against the pass sandbox
    (``run.root``), so its repository reads — the integration fixture,
    the pinned authority files, the producer sources — are byte copies
    of the real tree's declared inputs, and any attempt by the campaign
    to write repository paths lands in the sandbox and fails the guard.
    """
    key = str(run.root.resolve())
    cached = _campaign_cache.get(key)
    if cached is not None:
        return cached
    _scripts(run.root)
    import issue117_proof  # noqa: PLC0415 (lazy, sandbox-bound by design)
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
    """Living status sections, reusing the frozen sync renderer verbatim.

    Reads each managed document's existing bytes through the sandbox and
    replaces only the generated sections; the authored bytes outside the
    markers are inputs to the desired bytes (declared as self-inputs in
    the stage contract).
    """
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

    Earlier-stage writes shadow the sandbox copies, so this proves
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
    the sandbox), which mechanically proves manifest-last coverage."""
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


def _status_sync_reads() -> frozenset[str]:
    """The status DAG's real read set, derived from the renderer itself.

    ``docs/project-status.json`` supplies the rendered sections; every
    managed target document's existing bytes are consumed to preserve
    authored content outside the generated sections — a self-input
    (declared in both reads and writes).
    """
    _scripts(ROOT)
    import sync_project_status as sync  # noqa: PLC0415
    return frozenset({"docs/project-status.json", *sync.TARGETS})


def _issue117_authority_reads() -> frozenset[str]:
    """Every repository authority byte the campaign's outputs depend on.

    Derived from the canonical pinned-file dictionaries the campaign
    actually verifies against — never a hand-maintained duplicate:
    the V5 authority files, the accepted physical-identity evidence,
    the accepted-subject evidence package, the frozen producer-delta
    audit, and the immutable accepted #118 canonical summary.
    """
    _scripts(ROOT)
    import issue117_applicability as applicability  # noqa: PLC0415
    import issue117_accepted_subject as accepted_subject  # noqa: PLC0415
    reads = set(applicability.V5_AUTHORITY_FILES)
    reads |= set(applicability.ACCEPTED_PHYSICAL_IDENTITY_FILES)
    reads |= set(accepted_subject.ACCEPTED_SUBJECT_EVIDENCE_FILES)
    reads.add(applicability.PRODUCER_DELTA_RELATIVE_PATH)
    reads.add(f"{_EVIDENCE}/canonical-summary.json")
    return frozenset(reads)


def _issue137_bundle_reads() -> frozenset[str]:
    """The closed #137 bundle's real read set, from its own constants."""
    _scripts(ROOT)
    import issue137_manifest as bundle  # noqa: PLC0415
    reads = {f"{_BUNDLE_137}/{name}" for name in bundle.EVIDENCE_FILES}
    reads.add(f"{_BUNDLE_137}/MANIFEST.sha256")
    reads |= set(bundle.PRODUCERS)
    return frozenset(reads)


def default_registry() -> tuple[Stage, ...]:
    """The migrated Issue #117 chain (see module docstring).

    Registration is declarative and derived from canonical constants:
    another campaign adds its own primary/derived/index/terminal-manifest/
    verify stages here without any engine change.
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
                "(scripts/sync_project_status.py renderer, reused "
                "verbatim). Each managed document is a self-input: its "
                "authored bytes outside the generated sections are "
                "consumed to construct the desired bytes"),
            reads=_status_sync_reads(),
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
            id="issue117-authority",
            kind="primary",
            description=(
                "Authority inputs consumed by the Issue #117 campaign: "
                "the pinned V5 authority files, the accepted physical-"
                "identity evidence, the accepted-subject evidence "
                "package, the frozen producer-delta audit, and the "
                "immutable accepted #118 canonical summary. Derived from "
                "the pinned-file dictionaries in issue117_applicability "
                "and issue117_accepted_subject; never written by any "
                "stage (the authority/integrity split, registered)"),
            reads=_issue117_authority_reads(),
            after=frozenset({"status-sync"}),
        ),
        Stage(
            id="issue117-evidence",
            kind="derived",
            description=(
                "Issue #117 CPU campaign evidence (frozen producer "
                "issue117_proof.run_campaign; deterministic canonical "
                "JSON). Reads the integration fixture, the purity-audited "
                "planner source, and every declared authority input"),
            reads=(frozenset({
                       f"{_EVIDENCE}/integration-fixture.json",
                       "scripts/issue117_planner.py",
                   })
                   | _issue117_authority_reads()),
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
            after=frozenset({"status-sync", "issue117-authority"}),
            producer=_issue117_evidence_producer,
        ),
        Stage(
            id="issue117-producer-hashes",
            kind="index",
            description=(
                "Producer identity ledger for the Issue #117 bundle; pure "
                "function of every producer path it hashes (declared "
                "reads derived from issue117_proof.PRODUCERS)"),
            reads=frozenset(_producer_paths()),
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
                "stay byte-current (scripts/issue137_manifest.py --check). "
                "Reads derived from the bundle's own evidence/producer "
                "constants"),
            reads=_issue137_bundle_reads(),
            after=frozenset({"issue117-manifest"}),
            verify=_issue137_bundle_verify,
        ),
    )


def _producer_paths() -> frozenset[str]:
    """Every producer path the index stage hashes (canonical constant)."""
    _scripts(ROOT)
    import issue117_proof  # noqa: PLC0415
    return frozenset(issue117_proof.PRODUCERS)


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
            lines.append(f"   reads:    {len(stage.reads)} paths")
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
