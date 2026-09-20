#!/usr/bin/env python3
"""Issue #234 — R8-H fail-closed producer freeze (schema /1).

For every CLOSURE_SOURCES file the closure proves the EXACT BYTES BEING
EXECUTED — worktree bytes == index bytes == HEAD blob bytes, pinned
producer head, no missing/untracked/substituted source. The physical
collectors deployed to inferswarm02 must hash-verify against this
closure BEFORE any model execution; any drift blocks the campaign.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import issue234_receipt as rc


class FreezeError(RuntimeError):
    """The producer freeze failed; no correctness-bearing output may be
    produced or accepted."""


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True)


def verify_producer_freeze(repo: Path, expected_head: str) -> dict:
    """Fail closed unless every closure source is exactly HEAD-clean."""
    repo = repo.resolve()
    head = _git(repo, "rev-parse", "HEAD")
    if head.returncode != 0 or head.stdout.strip() != expected_head:
        raise FreezeError(
            f"worktree head {head.stdout.strip()!r} != expected "
            f"{expected_head}")
    status = _git(repo, "status", "--porcelain")
    for line in status.stdout.splitlines():
        if not line.strip():
            continue
        # untracked non-closure files are allowed (e.g. .venv) but any
        # MODIFIED/STAGED closure source is fatal; untracked closure
        # sources are also fatal (substituted producer).
        code, path = line[:2], line[3:].strip()
        rel = path.split(" -> ")[-1]
        if rel in rc.CLOSURE_SOURCES:
            raise FreezeError(f"closure source not HEAD-clean: {line!r}")
    closure = rc.verify_closure(repo, expected_head=expected_head)
    return closure


def deploy_check(local_repo: Path, deployed_hashes: dict[str, str]) -> None:
    """Verify the producers deployed on inferswarm02 hash-match the
    frozen closure (substituted collector = fatal)."""
    closure = rc.closure_document(local_repo)
    for rel, want in deployed_hashes.items():
        if rel not in closure["sources"]:
            raise FreezeError(f"not a closure source: {rel}")
        got = deployed_hashes[rel]
        if got != closure["sources"][rel]["sha256"]:
            raise FreezeError(
                f"deployed producer hash mismatch for {rel}: {got} != "
                f"{closure['sources'][rel]['sha256']}")
