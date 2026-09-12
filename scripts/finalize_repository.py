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
- a terminal manifest never covers its own bytes (no self-digest loop);
- declared reads are *enforced*: a stage's callable may only read inputs
  it declared (mediated through ``Run.read`` AND directly through the
  stage's own restricted filesystem projection), and paths registered
  as primary/frozen authority inputs are globally write-forbidden —
  a writer scheduled before OR after the protected reader is rejected;
- every real-tree write is symlink-safe: the destination and every
  ancestor component are validated with no-follow semantics before
  any byte is written, so an output symlink or a symlinked parent
  can never redirect an engine-authorized write outside the checkout.

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

Migrated paths:

- ``scripts/sync_project_status.py`` living status sections;
- the additive Issue #130 successor bundle
  (``.../evidence/issue-130-finalization``): parent-binding authority
  record, producer-hashes ledger, terminal retention manifest;
- the closed Issue #117 parent and Issue #137 bundle: verification-only.

Closed-parent contract (Issue #130 correction round 3).  The Issue
#117 bundle is a *closed accepted parent*: its ``MANIFEST.sha256``,
``producer-hashes.json``, ``purity-audit.json``, and the historical
producer ``scripts/issue117_proof.py`` are exact accepted bytes, no
stage writes them, and no Issue #130 source is registered in the
historical producer inventory.  The parent is bound immutably through
the successor bundle's ``commit:path`` authority record (git blob
identity + expected SHA-256, the accepted Issue #137 lifecycle model),
and a dedicated verify stage fails closed if any parent path drifts
from its accepted bytes.  Current-finalization integrity (producer
hashes + retention manifest for the Issue #130 sources) lives in its
own additive successor bundle under ``evidence/issue-130-finalization``
with its own terminal manifest; it never edits the parent bundle.

``Run.read`` is the mediated read channel: each stage is bound (as
``run.stage``) while its callable executes, and reads of paths the
stage did not declare fail closed.  The sandbox ``run.root`` a callable
sees is a per-stage *restricted projection*: it contains byte copies of
only the paths that stage declared, so a direct filesystem read of an
undeclared sibling input is impossible, not merely discouraged.

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
import stat
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
    protected: bool = False
    producer: Callable[["Run", Path], dict[str, bytes]] | None = None
    verify: Callable[["Run", Path], None] | None = None


class Run:
    """One finalization pass, executed against per-stage projections.

    ``root`` is the stage's restricted projection (byte copies of only
    the paths that stage declared), never the real working tree.
    Producers read tree state through ``run.read(path)``: bytes already
    written by an earlier stage this pass shadow the projection bytes,
    so ``--check`` and ``--write`` derive identical results.  While a
    stage's callable executes, ``run.stage`` is bound to that stage's
    declared read set and ``Run.read`` rejects any undeclared path;
    reading a path the stage also writes requires declaring it in BOTH
    ``reads`` and ``writes`` (the explicit self-input contract).
    ``Run.apply`` records desired bytes; the engine — and only the
    engine — writes them to the real tree during the apply step of a
    ``--write`` run.
    """

    def __init__(self, workroot: Path) -> None:
        self.root = workroot  # rebound per stage to its projection
        self.workroot = workroot
        self.stage: frozenset[str] = frozenset({"*"})  # unbound sentinel
        self.pending: dict[str, bytes] = {}
        self.mutations: dict[str, bytes] = {}
        self.changed: dict[str, list[str]] = {}

    def read_input(self, relative: str) -> bytes | None:
        """Engine-internal input check (pre-stage); bypasses no guard."""
        if relative in self.pending:
            return self.pending[relative]
        path = self.root / relative
        return path.read_bytes() if path.is_file() else None

    def read(self, relative: str) -> bytes | None:
        declared = "*" in self.stage or relative in self.stage
        if not declared:
            raise FinalizationError(
                f"undeclared read: the active stage did not declare "
                f"{relative!r} in its reads; add it to the stage contract "
                "or read through the declared dependency")
        if relative in self.pending:
            return self.pending[relative]
        path = self.root / relative
        return path.read_bytes() if path.is_file() else None

    def apply(self, stage_id: str, desired: dict[str, bytes]) -> None:
        """Record desired bytes and update the shadow state.

        Nothing here touches the real working tree; the engine's apply
        step does that, once, for declared paths only.
        """
        changed = []
        for relative in sorted(desired):
            data = desired[relative]
            current = self.read_input(relative)
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
    # primary/frozen authority inputs are globally write-forbidden: any
    # stage writing such a path is rejected REGARDLESS of topological
    # ordering — a writer scheduled before the protected reader is just
    # as invalid as one scheduled after it (Issue #130 correction F3).
    protected_by: dict[str, str] = {}
    for stage in stages:
        if not stage.protected:
            continue
        for relative in stage.reads | stage.covers:
            writer = writers.get(relative)
            if writer is not None:
                raise FinalizationError(
                    f"stage {writer} writes {relative}, a primary/frozen "
                    f"authority input protected by {stage.id}; protected "
                    "inputs are never writable, in any order")
            if relative in protected_by:
                raise FinalizationError(
                    f"protected input {relative} is claimed by both "
                    f"{protected_by[relative]} and {stage.id}")
            protected_by[relative] = stage.id


def _check_relative(stage_id: str, attr: str, relative: str) -> None:
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts or not relative.strip():
        raise FinalizationError(
            f"stage {stage_id}: {attr} entry must be a repo-relative path: "
            f"{relative!r}")
    if path.as_posix() != relative:
        # alias spellings ("./x", "a//b.txt", trailing slashes) would
        # create a second identity for the same destination and bypass
        # single-writer/protected-path/manifest-coverage rules
        raise FinalizationError(
            f"stage {stage_id}: {attr} entry must be a canonical "
            f"repo-relative spelling (no './', '//', or trailing '/'): "
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


def dirty_paths(root: Path) -> list[str]:
    """Fail-closed census of dirty paths (tracked + untracked).

    Kept for callers that only need the dirty PATH LIST; the engine
    itself uses the full path-state ``worktree_census``.  Deletion of a
    tracked path counts as dirty here (the worktree differs from HEAD).
    """
    census = worktree_census(root)
    return sorted(
        relative for relative, state in census.items()
        if state.state != "clean-tracked")


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


# ---------------------------------------------------------------------------
# Path-state census (F2): every relevant path's STATE, not just bytes
# ---------------------------------------------------------------------------

_STATUS_CHARS = frozenset(b"MADRCU?! ")

# path states:
#   clean-tracked   tracked, present, bytes == HEAD (restorable from git)
#   dirty-tracked   tracked, present, bytes != HEAD (authored; copy backed up)
#   deleted-tracked tracked, ABSENT by author intent (must stay deleted)
#   untracked       present, not tracked (authored; copy backed up)
#   absent          neither tracked nor present at census time
_MISSING = object()  # sentinel: path has no bytes (deleted/absent)


def _status_records(root: Path) -> list[tuple[str, str]]:
    """Parsed ``status --porcelain=v1 -z`` records: (XY, path) pairs.

    Rename/copy records contribute their new path plus the old path
    (marked as deleted-in-effect).  Unparseable output fails closed.
    """
    raw = _git(root, "status", "--porcelain=v1", "-z",
               "--untracked-files=all")
    records: list[tuple[str, str]] = []
    expect_old_path = False
    for token in raw.split(b"\0"):
        if not token:
            continue  # trailing terminator
        if expect_old_path:
            records.append(("D ", token.decode("utf-8", "surrogateescape")))
            expect_old_path = False
            continue
        if (len(token) < 4 or token[2:3] != b" "
                or any(byte not in _STATUS_CHARS for byte in token[:2])):
            raise FinalizationError(
                f"unparseable git status record: {token!r}; refusing to "
                "guess the starting worktree state")
        status = token[:2].decode("ascii")
        records.append(
            (status, token[3:].decode("utf-8", "surrogateescape")))
        if "R" in status or "C" in status:
            expect_old_path = True
    if expect_old_path:
        raise FinalizationError(
            "truncated git status record (rename/copy without its old "
            "path); refusing to guess the starting worktree state")
    return records


@dataclass(frozen=True)
class PathState:
    """The complete starting state of one repository path."""

    state: str            # clean-tracked|dirty-tracked|deleted-tracked|
                          # untracked|absent
    digest: str | None    # sha256 of present bytes, None if absent
    mode: int | None      # st_mode of the present file, None if absent

    def present(self) -> bool:
        return self.state in ("clean-tracked", "dirty-tracked", "untracked")


def worktree_census(root: Path) -> dict[str, PathState]:
    """Map every relevant path to its starting state (F2).

    Relevant = tracked paths (present or deleted) + untracked files.
    Distinguishes clean-tracked, dirty-tracked, deleted-tracked
    (authored deletion — must remain deleted), and untracked, with
    content digest and file mode so restoration is unambiguous.
    """
    tracked = _tracked_paths(root)
    records = _status_records(root)
    present: dict[str, PathState] = {}
    deleted_tracked: set[str] = set()
    for status, relative in records:
        if relative in tracked and ("D" in status or "A" not in status
                                    and status[1] == "D"):
            pass  # handled below via set logic
        if "D" in status:
            # worktree deletion of a tracked path (XY=D. or .D);
            # staged additions that are later deleted vanish instead
            if relative in tracked:
                deleted_tracked.add(relative)
            continue
        path = root / relative
        if not path.is_file():
            continue  # e.g. an untracked directory record; files follow
        info = path.lstat()
        present[relative] = PathState(
            state=("untracked" if relative not in tracked
                   else "dirty-tracked"),
            digest=_digest_file(path), mode=stat.S_IMODE(info.st_mode))
    census: dict[str, PathState] = dict(present)
    for relative in sorted(tracked):
        if relative in census or relative in deleted_tracked:
            continue
        # tracked, not in status output => clean and present
        path = root / relative
        info = path.lstat()
        census[relative] = PathState(
            state="clean-tracked",
            digest=_digest_file(path), mode=stat.S_IMODE(info.st_mode))
    for relative in deleted_tracked:
        census[relative] = PathState(
            state="deleted-tracked", digest=None, mode=None)
    return census


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


# ---------------------------------------------------------------------------
# Per-stage restricted projections (F3): a callable cannot even SEE an
# input it did not declare, so direct filesystem reads cannot silently
# expand the dependency graph any more than Run.read can.
# ---------------------------------------------------------------------------

def _stage_projection(stage: Stage, root: Path, run: Run,
                      workroot: Path) -> Path:
    """Materialize the stage's restricted projection and bind run.root.

    Contains byte copies of exactly the paths the stage declared
    (reads + writes + covers), plus the pass's pending outputs for its
    declared inputs (earlier-stage writes it declared as reads).  The
    projection root is what the callable receives as ``run.root``.
    """
    projection = workroot / "projections" / stage.id
    if projection.exists():
        shutil.rmtree(projection, ignore_errors=True)
    projection.mkdir(parents=True, exist_ok=True)
    declared = stage.reads | stage.writes | stage.covers
    for relative in sorted(declared):
        if relative in run.pending:
            data = run.pending[relative]
            target = projection / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            continue
        source = root / relative
        if not source.is_file():
            continue  # missing inputs fail later with a precise stage error
        target = projection / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    return projection


def _sandbox_digests(sandbox: Path) -> dict[str, str]:
    """Content digests of every file in a projection/sandbox tree.

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


# ---------------------------------------------------------------------------
# Starting-state snapshot and restoration (F2)
# ---------------------------------------------------------------------------

def _snapshot_starting_state(root: Path, workroot: Path
                             ) -> dict[str, PathState]:
    """Census every relevant path and back up authored bytes.

    Dirty-tracked and untracked bytes are copied into
    ``workroot/starting-bytes`` (they exist nowhere else); clean-tracked
    bytes are restorable read-only from the git object store;
    deleted-tracked paths need no bytes — restoration must keep them
    deleted.  Clean-tracked paths are copied too, so restoration never
    depends on git succeeding AFTER a mutation: if a post-mutation
    census or restore fails, the engine still holds byte-level copies.
    """
    census = worktree_census(root)
    backup = workroot / "starting-bytes"
    for relative, state in sorted(census.items()):
        if not state.present():
            continue
        source = root / relative
        target = backup / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    return census


def _restore_worktree(root: Path, starting: dict[str, PathState],
                      backup: Path, *, preserve: set[str]) -> list[str]:
    """Restore the worktree to its exact starting state (F2).

    Handles all six transitions:

    - clean/dirty/untracked present at start -> restore bytes + mode
      (authored bytes from the engine copy, which for clean-tracked
      paths is byte-identical to HEAD);
    - deleted-tracked at start -> a path a callable recreated is
      DELETED again (an authored deletion stays deleted; HEAD bytes are
      never resurrected merely because the baseline lacked file bytes);
    - created during execution (not in the census) -> engine debris,
      removed.
    """
    restored: list[str] = []
    current = worktree_census(root)
    # git-status acquisition already failed closed inside the census if
    # untrustworthy; a failure here aborts restoration loudly, never
    # silently skips it (F2 requirement).
    for relative in sorted(set(starting) | set(current)):
        if relative in preserve:
            continue
        was, now = starting.get(relative), current.get(relative)
        if was == now:
            continue
        target = root / relative
        if was is None:
            # created during the run, never authored, never tracked:
            # engine debris — remove it (directories pruned below)
            if now is not None and now.present():
                target.unlink(missing_ok=True)
            elif target.is_symlink() or target.exists():
                target.unlink(missing_ok=True)
            restored.append(relative)
        elif was.present():
            # authored or clean content: restore the exact starting
            # bytes and mode from the engine-made copy
            source = backup / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            os.chmod(target, was.mode or 0o644)
            restored.append(relative)
        else:
            # deleted-tracked at start: keep it deleted
            if now is not None and now.present():
                target.unlink(missing_ok=True)
            elif target.exists() or target.is_symlink():
                target.unlink(missing_ok=True)
            restored.append(relative)
    # prune empty directories the removals may have left behind
    for parent in sorted({(root / r).parent for r in restored},
                         key=lambda p: len(p.parts), reverse=True):
        try:
            parent.rmdir()
        except OSError:
            pass
    return restored


def _census_delta(before: dict[str, PathState],
                  after: dict[str, PathState]) -> list[str]:
    """Paths whose state changed between two censuses."""
    changed = []
    for relative in sorted(set(before) | set(after)):
        if before.get(relative) != after.get(relative):
            changed.append(relative)
    return changed


@contextlib.contextmanager
def _callable_guard(root: Path, projection: Path, stage_id: str, role: str,
                    starting: dict[str, PathState], backup: Path,
                    ) -> Iterator[None]:
    """Detect any direct filesystem side effect of one stage callable.

    Compares full content digests of the stage's restricted projection
    and a complete path-state census of the REAL worktree before and
    after the callable.  On any difference — create, overwrite, delete,
    rename (a rename is a delete plus an undeclared create) — the
    worktree is restored to its exact starting state and the engine
    fails closed.  If the post-callable census itself fails, that
    failure propagates: preservation is never silently skipped.  Nothing
    here relies on the callable reporting its writes honestly.
    """
    projection_before = _sandbox_digests(projection)
    census_before = worktree_census(root)
    previous_cwd = Path(os.getcwd())
    os.chdir(projection)
    try:
        yield
    finally:
        os.chdir(previous_cwd)
        damage: list[str] = []
        try:
            projection_after = _sandbox_digests(projection)
        except OSError as error:
            raise FinalizationError(
                f"stage {stage_id} {role} left the projection "
                f"unreadable ({error}); the finalizer fails closed "
                "without applying any declared write") from error
        if projection_after != projection_before:
            touched = sorted(
                path for path in set(projection_after) | set(projection_before)
                if projection_after.get(path) != projection_before.get(path))
            damage.append(
                "directly mutated the stage sandbox (undeclared "
                f"filesystem writes): {touched}")
        census_after = worktree_census(root)
        if census_after != census_before:
            touched = _census_delta(census_before, census_after)
            damage.append(
                f"directly mutated the repository worktree: {touched}")
            _restore_worktree(root, starting, backup, preserve=set())
        if damage:
            raise FinalizationError(
                f"stage {stage_id} {role} escaped the engine contract: "
                + "; ".join(damage)
                + "; the repository was restored to its starting state "
                "and no declared writes from this pass were applied")


def _is_scripts_module(module: object) -> bool:
    file = getattr(module, "__file__", None)
    if not file:
        return False
    try:
        path = Path(file).resolve()
    except OSError:
        return False
    return path != Path(__file__).resolve() and path.parent.name == "scripts"


def _purge_script_modules(sandbox: Path | None) -> None:
    """Drop imported ``scripts/`` modules so imports bind to the sandbox.

    Producer modules (issue117_proof, sync_project_status, ...) derive
    their repository ROOT from their import location.  Before a pass any
    module the ENGINE imported (bound to the sandbox or to another
    checkout) is purged so the campaign and its authority verification
    read the sandbox copies; after a pass the engine-imported copies are
    purged so later imports rebind to a real checkout.

    Modules that were ALREADY imported before the first engine call are
    never purged: other suites in the same process hold references to
    their classes, and a purge would re-import a second class object and
    silently break isinstance/assertIs identity for code that did
    nothing wrong.  Those pre-existing bindings read the real tree, whose
    declared-input bytes are identical to the sandbox copies; any write
    attempt is still caught by the callable guard.
    """
    sandbox_scripts = (sandbox / "scripts").resolve() if sandbox else None
    for name, module in list(sys.modules.items()):
        if name in _import_baseline or not _is_scripts_module(module):
            continue
        file = getattr(module, "__file__", None)
        assert file is not None
        path = Path(file).resolve()
        if sandbox_scripts is not None and path.parent == sandbox_scripts:
            continue
        del sys.modules[name]
    importlib.invalidate_caches()


_import_baseline: frozenset[str] = frozenset()


def _mark_import_baseline() -> None:
    """Record (once per process) which scripts modules predate the engine."""
    global _import_baseline
    if not _import_baseline:
        _import_baseline = frozenset(
            name for name, module in sys.modules.items()
            if _is_scripts_module(module))


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
    starting = _snapshot_starting_state(root, managed)
    try:
        report = _execute_pass(root, stages, managed, starting)
        if write and report["mutations"]:
            _apply_mutations(root, report["mutations"])
        return report
    finally:
        if workroot is None:
            shutil.rmtree(managed, ignore_errors=True)


def _execute_pass(root: Path, stages: tuple[Stage, ...], workroot: Path,
                  starting: dict[str, PathState]) -> dict:
    """Execute one pass of per-stage projections; the real tree is
    never written here."""
    validate_registry(stages)
    order_ids = topological_order(stages)
    by_id = {stage.id: stage for stage in stages}
    validate_order(stages, order_ids)
    backup = workroot / "starting-bytes"
    run = Run(workroot)
    _mark_import_baseline()
    for stage_id in order_ids:
        stage = by_id[stage_id]
        if stage.producer is None and stage.verify is None:
            continue  # purely declarative stage
        run.root = _stage_projection(stage, root, run, workroot)
        # enforced read set: declared reads; covers count as reads for
        # terminal manifests (they hash every covered path); a path the
        # stage writes is readable ONLY if also declared in reads (the
        # explicit self-input contract)
        run.stage = frozenset(stage.reads | stage.covers)
        _purge_script_modules(run.root)
        for relative in sorted(stage.reads | stage.covers):
            if run.read_input(relative) is None:
                raise FinalizationError(
                    f"stage {stage_id}: required input is missing: "
                    f"{relative}")
        try:
            if stage.producer is not None:
                with _callable_guard(root, run.root, stage_id, "producer",
                                     starting, backup):
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
                with _callable_guard(root, run.root, stage_id, "verify",
                                     starting, backup):
                    stage.verify(run, workroot)
        finally:
            run.stage = frozenset({"*"})
    return {"order": order_ids, "changed": run.changed,
            "mutations": run.mutations}


def _validate_output_path(root: Path, relative: str) -> Path:
    """Symlink-safe validation of one real-tree write target (F4).

    The destination itself must not be a symlink, and no ancestor
    component beneath the repository root may be a symlink; the
    resulting canonical path must remain beneath ``root``.  Validation
    uses no-follow ``lstat`` semantics on each component — a ``resolve``
    check followed by an unsafe follow-write would reintroduce the
    escape.  Aliases that would bypass registry identity (``..``,
    absolute paths, repeated separators) are rejected upstream by
    ``_check_relative``; this proves the *filesystem* agrees.
    """
    target = root / relative
    # lstat the destination: an existing symlink destination is refused
    try:
        info = target.lstat()
    except FileNotFoundError:
        info = None
    if info is not None and stat.S_ISLNK(info.st_mode):
        raise FinalizationError(
            f"output path {relative!r} is a symlink; engine writes must "
            "land on a real file inside the repository, never follow a "
            "symlinked destination")
    # walk every ancestor component beneath the root with lstat
    current = root
    parts = Path(relative).parts
    for component in parts[:-1]:
        if component in ("", ".", ".."):
            raise FinalizationError(
                f"malformed output path {relative!r}")
        current = current / component
        try:
            entry = current.lstat()
        except FileNotFoundError:
            break  # missing parents are created by the engine, no-follow
        if stat.S_ISLNK(entry.st_mode):
            raise FinalizationError(
                f"output path {relative!r} has a symlinked ancestor "
                f"({component!r}); engine writes must stay inside the "
                "repository without following symlinks")
        if not stat.S_ISDIR(entry.st_mode):
            raise FinalizationError(
                f"output path {relative!r} traverses non-directory "
                f"component {component!r}")
    # final containment check (root itself already resolved+compared)
    if os.path.commonpath([str(root), str(target)]) != str(root):
        raise FinalizationError(
            f"output path {relative!r} escapes the repository root")
    return target


def _apply_mutations(root: Path, mutations: dict[str, bytes]) -> None:
    """The ONLY code that writes the real working tree (F4-hardened).

    Declared paths, engine bytes, one pass, after every stage has run.
    Every destination is validated symlink-safely immediately before
    its write; writes open the final component with ``O_NOFOLLOW`` so a
    race between validation and write cannot redirect the byte landing.
    """
    for relative in sorted(mutations):
        target = _validate_output_path(root, relative)
        data = mutations[relative]
        parent = target.parent
        parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(target, os.O_WRONLY | os.O_CREAT
                             | os.O_TRUNC | os.O_NOFOLLOW, 0o644)
        try:
            os.write(descriptor, data)
        finally:
            os.close(descriptor)


def finalize(root: Path, stages: tuple[Stage, ...], *, write: bool) -> dict:
    """Run the pipeline; in write mode prove the byte fixed point."""
    starting_census = worktree_census(root)  # fail closed if untrustworthy
    starting_dirty = sorted(
        relative for relative, state in starting_census.items()
        if state.state in ("dirty-tracked", "deleted-tracked", "untracked"))
    workroot = Path(tempfile.mkdtemp(prefix="finalize-repository-"))
    try:
        starting = _snapshot_starting_state(root, workroot)
        reset_scratch_caches()
        first = _execute_pass(root, stages, workroot, starting)
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
            after = worktree_census(root)
            allowed = set(first["mutations"])
            unexpected = [
                relative for relative in set(starting) | set(after)
                if relative not in allowed
                and starting.get(relative) != after.get(relative)]
            if unexpected:
                _restore_worktree(root, starting,
                                  workroot / "starting-bytes",
                                  preserve=allowed)
                raise FinalizationError(
                    "the worktree changed outside the declared writes "
                    f"during the apply step: {sorted(unexpected)}; the "
                    "repository was restored to its starting state")
            reset_scratch_caches()
            second = _execute_pass(root, stages, workroot, starting)
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
_BUNDLE_137 = f"{_EVIDENCE}/arm-c-regime4-diagnosis-137"
# The additive Issue #130 successor bundle: current-finalization
# integrity for the Issue #130 sources, never a rewrite of the closed
# Issue #117 parent bundle (accepted at commit d1afad6, unchanged).
_BUNDLE_130 = f"{_EVIDENCE}/issue-130-finalization"
_PARENT_COMMIT = "d1afad64ca8bdd05634d3d0e1e09b8077da525d5"

# The closed Issue #117 parent artifacts (F1): path -> accepted SHA-256
# at the accepted parent commit.  Identity derived from the accepted
# git tree (d1afad6 = origin/main at review), the same authority the
# accepted #137 lifecycle binds its parent with (commit:path identity
# plus expected digest).  These paths are read-only: no stage writes
# them, and the parent-bind verify stage fails closed on any drift.
PARENT_BINDINGS: dict[str, str] = {
    "scripts/issue117_proof.py":
        "a000f674cd62f96e50c5e8e555c46b4ec7f7a0aaf0237d19651deb02f8c11395",
    f"{_EVIDENCE}/purity-audit.json":
        "54e6cb8fe831df57de30899e020f08376c855ff2c22d559cf3b3d9edd322fc7f",
    f"{_EVIDENCE}/producer-hashes.json":
        "d63bbafa010461d9ff4a0dc23a948abf8ff9157faf00c486ab3c45bd45e40d9b",
    f"{_EVIDENCE}/MANIFEST.sha256":
        "473ad14a01d293c39d45293222ad42d61cd2e8046ff3c5433dbf5683d7824946",
}

# Issue #130 finalizer sources and contracts (the successor bundle's
# own producer inventory; additive, disjoint from the parent's).
FINALIZATION_PRODUCERS: tuple[str, ...] = (
    "scripts/finalize_repository.py",
    "tests/test_finalize_repository.py",
    "tests/test_evidence_manifest_lifecycle.py",
)

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


def _parent_binding_document() -> dict[str, object]:
    """Immutable commit:path authority record binding the closed parent.

    Follows the accepted Issue #137 lifecycle model: an ancestor bundle
    is addressed through immutable Git ``commit:path`` identity plus the
    expected SHA-256 of each bound path, never through its live
    working-tree copy.
    """
    return {
        "parent_issue": 117,
        "parent_commit": _PARENT_COMMIT,
        "authority_model": "commit:path + expected sha256 "
                           "(docs/evidence-manifests.md lifecycle)",
        "bindings": {
            path: {
                "commit": _PARENT_COMMIT,
                "path": path,
                "sha256": digest,
            }
            for path, digest in sorted(PARENT_BINDINGS.items())
        },
    }


def _parent_bind_verify(run: Run, scratch: Path) -> None:
    """Fail closed unless every closed-parent artifact is byte-current.

    Mechanical verification of the immutable parent binding: the live
    bytes must equal the accepted SHA-256 recorded in the successor
    bundle's authority record AND the git blob identity at the accepted
    parent commit must still match.  Verification-only: this stage
    never writes anything, and the parent artifacts are registered as
    protected (globally unwritable) inputs.
    """
    document = _parent_binding_document()
    authority = run.root / _BUNDLE_130 / "parent-binding.json"
    if authority.is_file():
        committed = json.loads(authority.read_text(encoding="utf-8"))
        if committed != document:
            raise FinalizationError(
                "Issue #130 successor bundle parent-binding record "
                "disagrees with the engine's canonical binding document")
    for path, digest in sorted(PARENT_BINDINGS.items()):
        data = run.read(path)
        if data is None:
            raise FinalizationError(
                f"closed parent artifact is missing: {path}")
        if _sha256(data) != digest:
            raise FinalizationError(
                f"closed parent artifact drifted from its accepted "
                f"bytes: {path} (expected sha256 {digest})")


def _successor_producer_hashes_producer(
        run: Run, scratch: Path) -> dict[str, bytes]:
    """Producer-hash ledger for the Issue #130 successor bundle."""
    expected = {}
    for producer in sorted(FINALIZATION_PRODUCERS):
        data = run.read(producer)
        if data is None:
            raise FinalizationError(
                f"finalization producer is missing: {producer}")
        expected[producer] = _sha256(data)
    body = json.dumps(expected, sort_keys=True,
                      separators=(",", ":")).encode("utf-8") + b"\n"
    return {f"{_BUNDLE_130}/producer-hashes.json": body}


def _successor_manifest_rows(run: Run) -> dict[str, str]:
    rows: dict[str, str] = {}
    for producer in sorted(FINALIZATION_PRODUCERS):
        data = run.read(producer)
        if data is None:
            raise FinalizationError(
                f"finalization producer is missing: {producer}")
        rows[producer] = _sha256(data)
    for path, digest in sorted(PARENT_BINDINGS.items()):
        rows[path] = digest
    binding = run.read(f"{_BUNDLE_130}/parent-binding.json")
    if binding is None:
        raise FinalizationError(
            "successor bundle parent-binding record is missing")
    rows[f"{_BUNDLE_130}/parent-binding.json"] = _sha256(binding)
    return rows


def _successor_manifest_producer(run: Run, scratch: Path
                                 ) -> dict[str, bytes]:
    """Terminal manifest of the additive Issue #130 successor bundle.

    Covers the Issue #130 producer sources plus the closed parent
    bindings (the parent paths are recorded with their ACCEPTED
    digests — the successor manifest pins the parent, it never
    regenerates it).
    """
    rows = _successor_manifest_rows(run)
    body = "".join(f"{digest}  {path}\n"
                   for path, digest in sorted(rows.items()))
    return {f"{_BUNDLE_130}/MANIFEST.sha256": body.encode("utf-8")}


def _status_source_verify(run: Run, scratch: Path) -> None:
    _scripts(run.root)
    import sync_project_status as sync  # noqa: PLC0415
    document = json.loads(run.read("docs/project-status.json"))
    sync.validate(document)  # fail closed on a malformed status record


def _status_sync_producer(run: Run, scratch: Path) -> dict[str, bytes]:
    """Living status sections, reusing the frozen sync renderer verbatim.

    Reads each managed document's existing bytes through the projection
    and replaces only the generated sections; the authored bytes outside
    the markers are inputs to the desired bytes (declared as self-inputs
    in the stage contract).
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


def _issue137_bundle_reads() -> frozenset[str]:
    """The closed #137 bundle's real read set, from its own constants."""
    _scripts(ROOT)
    import issue137_manifest as bundle  # noqa: PLC0415
    reads = {f"{_BUNDLE_137}/{name}" for name in bundle.EVIDENCE_FILES}
    reads.add(f"{_BUNDLE_137}/MANIFEST.sha256")
    reads |= set(bundle.PRODUCERS)
    return frozenset(reads)


def _successor_bundle_files() -> list[str]:
    return [f"{_BUNDLE_130}/parent-binding.json",
            f"{_BUNDLE_130}/producer-hashes.json",
            f"{_BUNDLE_130}/MANIFEST.sha256"]


def default_registry() -> tuple[Stage, ...]:
    """The finalization DAG (see module docstring).

    Registration is declarative and derived from canonical constants:
    another campaign adds its own primary/derived/index/terminal-manifest/
    verify stages here without any engine change.
    """
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
            id="issue117-parent-bind",
            kind="verify",
            description=(
                "The closed Issue #117 parent bundle is bound immutably "
                "through commit:path identity plus expected SHA-256 "
                "(accepted #137 lifecycle model). Verification-only: the "
                "parent artifacts are exact accepted bytes, protected "
                "against any writer, and no Issue #130 source is in the "
                "historical producer inventory"),
            reads=frozenset(PARENT_BINDINGS)
                  | {f"{_BUNDLE_130}/parent-binding.json"},
            protected=True,
            after=frozenset({"status-sync"}),
            verify=_parent_bind_verify,
        ),
        Stage(
            id="issue117-successor-hashes",
            kind="index",
            description=(
                "Producer identity ledger for the additive Issue #130 "
                "successor bundle (scripts/finalize_repository.py + its "
                "test suites); disjoint from the closed parent's "
                "inventory"),
            reads=frozenset(FINALIZATION_PRODUCERS),
            writes=frozenset({f"{_BUNDLE_130}/producer-hashes.json"}),
            after=frozenset({"issue117-parent-bind"}),
            producer=_successor_producer_hashes_producer,
        ),
        Stage(
            id="issue117-successor-manifest",
            kind="terminal-manifest",
            description=(
                "Terminal retention manifest of the additive Issue #130 "
                "successor bundle; pins the Issue #130 producers and the "
                "closed parent bindings (parent rows carry their ACCEPTED "
                "digests; the parent is never regenerated)"),
            writes=frozenset({f"{_BUNDLE_130}/MANIFEST.sha256"}),
            covers=(frozenset(FINALIZATION_PRODUCERS)
                    | frozenset(PARENT_BINDINGS)
                    | {f"{_BUNDLE_130}/parent-binding.json"}),
            after=frozenset({"issue117-successor-hashes"}),
            producer=_successor_manifest_producer,
        ),
        Stage(
            id="issue137-bundle-verify",
            kind="verify",
            description=(
                "The accepted Issue #137 additive bundle is closed and must "
                "stay byte-current (scripts/issue137_manifest.py --check). "
                "Reads derived from the bundle's own evidence/producer "
                "constants; the #137 bundle inputs are protected"),
            reads=_issue137_bundle_reads(),
            protected=True,
            after=frozenset({"issue117-successor-manifest"}),
            verify=_issue137_bundle_verify,
        ),
    )


def _parent_binding_bytes() -> bytes:
    return (json.dumps(_parent_binding_document(), indent=2,
                       sort_keys=True) + "\n").encode("utf-8")


def materialize_successor_bundle() -> None:
    """Write the static parent-binding authority record (authored-once).

    The binding document is deterministic engine output pinned by the
    successor manifest; it is written through the engine's own apply
    path during ``--write`` runs of the finalizer bootstrap.  It exists
    so the immutable parent binding is a committed, reviewable artifact
    rather than engine-internal state.
    """
    authority = ROOT / _BUNDLE_130 / "parent-binding.json"
    authority.parent.mkdir(parents=True, exist_ok=True)
    authority.write_bytes(_parent_binding_bytes())


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
