#!/usr/bin/env python3
"""Issue #232 — V2-G fail-closed producer freeze.

Identical corrected semantics to the accepted #230 closure (schema /1):
for every CLOSURE_SOURCES file the closure proves the EXACT BYTES BEING
EXECUTED — worktree bytes == index bytes == HEAD blob bytes, pinned
producer head, no missing/untracked/substituted source. HEAD may advance
past the pin only via commits touching no closure source.

Every emitted phase record must carry the closure digest; the assembler
verifies that binding FIRST, before reducing any phase.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

import issue232_receipt as rc


class FreezeError(RuntimeError):
    """The producer freeze failed; no correctness-bearing output may be
    produced or accepted."""


SCHEMA_CLOSURE = "inferswarm.v2g.producer-closure/1"

#: Collector (physical observation) producers. A reduction-only
#: amendment must prove these byte-unchanged between the evidence pin
#: and HEAD; they are the bytes whose executed identity the retained
#: raw evidence binds. bootproof/coldproof are included (2026-09-20
#: authority correction): they emit correctness/authority-bearing
#: artifacts consumed by replay authorization and terminal reduction,
#: so an amendment across a changed bootproof/coldproof is a producer
#: change, not a reduction-only edit.
PHYSICAL_PRODUCERS: tuple[str, ...] = (
    "scripts/issue232_receipt.py",
    "scripts/issue232_authority.py",
    "scripts/issue232_host.py",
    "scripts/issue232_baseline.py",
    "scripts/issue232_gate.py",
    "scripts/issue232_qualify.py",
    "scripts/issue232_replay.py",
    "scripts/issue232_bootproof.py",
    "scripts/issue232_coldproof.py",
)


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, check=check)


def _git_bytes(repo: Path, *args: str) -> bytes | None:
    proc = _git(repo, *args, check=False)
    return proc.stdout if proc.returncode == 0 else None


def worktree_source_sha256(repo: Path, rel: str) -> str:
    path = repo / rel
    if not path.is_file():
        raise FreezeError(f"closure source missing from worktree: {rel}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def head_source_sha256(repo: Path, rel: str, head: str) -> str | None:
    data = _git_bytes(repo, "cat-file", "blob", f"{head}:{rel}")
    return None if data is None else hashlib.sha256(data).hexdigest()


def index_source_sha256(repo: Path, rel: str) -> str | None:
    data = _git_bytes(repo, "show", f":{rel}")
    return None if data is None else hashlib.sha256(data).hexdigest()


def is_tracked_at_head(repo: Path, rel: str, head: str) -> bool:
    proc = _git(repo, "cat-file", "-e", f"{head}:{rel}", check=False)
    return proc.returncode == 0


def current_head(repo: Path) -> str:
    proc = _git(repo, "rev-parse", "HEAD")
    return proc.stdout.decode().strip()


def closure_document(repo: Path | None = None,
                     sources: tuple[str, ...] | None = None
                     ) -> dict[str, Any]:
    repo = Path(repo) if repo is not None else rc.ROOT
    head = current_head(repo)
    closure_sources = sources if sources is not None else rc.CLOSURE_SOURCES
    out_sources: dict[str, str] = {}
    for rel in closure_sources:
        if not is_tracked_at_head(repo, rel, head):
            raise FreezeError(
                f"closure source not tracked at producer HEAD {head}: {rel}")
        wt = worktree_source_sha256(repo, rel)
        idx = index_source_sha256(repo, rel)
        hd = head_source_sha256(repo, rel, head)
        if idx is None:
            raise FreezeError(f"closure source missing from index: {rel}")
        if hd is None:
            raise FreezeError(f"closure source missing at HEAD: {rel}")
        if wt != idx:
            raise FreezeError(
                f"unstaged producer drift (worktree != index): {rel}")
        if idx != hd:
            raise FreezeError(
                f"staged producer drift (index != HEAD): {rel}")
        out_sources[rel] = wt
    doc = {
        "schema": SCHEMA_CLOSURE,
        "campaign_id": rc.CAMPAIGN_ID,
        "producer_head": head,
        "sources": out_sources,
    }
    doc["closure_digest"] = hashlib.sha256(
        rc.canonical({k: v for k, v in doc.items()
                      if k != "closure_digest"})).hexdigest()
    return doc


def verify_closure(repo: Path | None = None,
                   committed: dict[str, Any] | None = None,
                   sources: tuple[str, ...] | None = None,
                   record_rel: str | None = None
                   ) -> dict[str, Any]:
    repo = Path(repo) if repo is not None else rc.ROOT
    record_path = repo / (record_rel
                          if record_rel is not None
                          else f"{rc.AREA_REL}/{rc.CLOSURE_NAME}")
    if committed is None:
        if not record_path.is_file():
            raise FreezeError(f"committed closure missing: {record_path}")
        committed = json.loads(record_path.read_text(encoding="utf-8"))
    assert committed is not None
    if committed.get("schema") != SCHEMA_CLOSURE:
        raise FreezeError(f"closure schema mismatch: {committed.get('schema')!r}")
    if committed.get("campaign_id") != rc.CAMPAIGN_ID:
        raise FreezeError("closure campaign mismatch")
    pinned = committed.get("producer_head")
    if not isinstance(pinned, str) or len(pinned) != 40 \
            or any(c not in "0123456789abcdef" for c in pinned):
        raise FreezeError("closure record does not pin a producer HEAD")
    closure_sources = sources if sources is not None else rc.CLOSURE_SOURCES
    if set(committed.get("sources") or {}) != set(closure_sources):
        raise FreezeError(
            "closure source set mismatch (missing/untracked/substituted "
            "closure source)")
    for rel, expected in committed["sources"].items():
        hd = head_source_sha256(repo, rel, pinned)
        if hd is None:
            raise FreezeError(
                f"closure source not present at pinned producer head: {rel}")
        if hd != expected:
            raise FreezeError(
                f"closure record pin does not match pinned HEAD blob: {rel}")
        idx = index_source_sha256(repo, rel)
        if idx is None or idx != expected:
            raise FreezeError(f"staged producer drift (index != pin): {rel}")
        wt = worktree_source_sha256(repo, rel)
        if wt != expected:
            raise FreezeError(f"unstaged producer drift (worktree != pin): {rel}")
    diff = _git_bytes(repo, "diff", "--name-only", pinned,
                      current_head(repo), "--", *closure_sources)
    if diff is None or diff.strip():
        amended = accepted_amended_digests(repo)
        pin_diff = _git_bytes(repo, "diff", "--name-only", pinned,
                              current_head(repo), "--",
                              *PHYSICAL_PRODUCERS)
        entry = amended.get(str(committed.get("closure_digest")))
        if entry is None or pin_diff is None or pin_diff.strip():
            raise FreezeError(
                "producer sources changed between the pinned head and "
                "HEAD — re-freeze (regenerate the closure) before any "
                "producer emits or the assembler reduces")
    body = {k: v for k, v in committed.items() if k != "closure_digest"}
    recomputed = hashlib.sha256(rc.canonical(body)).hexdigest()
    if committed.get("closure_digest") != recomputed:
        raise FreezeError("closure record digest does not bind its content")
    return committed


def write_closure(repo: Path | None = None) -> Path:
    repo = Path(repo) if repo is not None else rc.ROOT
    record_path = repo / rc.AREA_REL / rc.CLOSURE_NAME
    record_path.parent.mkdir(parents=True, exist_ok=True)
    doc = closure_document(repo)
    record_path.write_bytes(json.dumps(doc, indent=1, sort_keys=True)
                            .encode("utf-8") + b"\n")
    return record_path


# --- reduction-only amendment protocol ---------------------------------
# Same semantics as the accepted #230/#228/#216 protocol: a
# reduction-layer correction AFTER retained physical output does not
# invalidate the evidence; an AMENDMENTS.json entry proves the
# collectors' executed bytes are unchanged, mechanically per entry,
# fail-closed.

AMENDMENT_SCHEMA = "inferswarm.v2g.producer-amendments/1"


def _closure_digest_at(repo: Path, pin: str) -> str | None:
    raw = _git_bytes(repo, "show",
                     f"{pin}:{rc.AREA_REL}/{rc.CLOSURE_NAME}")
    if not raw:
        return None
    try:
        doc = json.loads(raw.decode("utf-8"))
        if doc.get("schema") != SCHEMA_CLOSURE:
            return None
        if doc.get("campaign_id") != rc.CAMPAIGN_ID:
            return None
        if set(doc.get("sources") or {}) != set(rc.CLOSURE_SOURCES):
            return None
        body = {k: v for k, v in doc.items() if k != "closure_digest"}
        recomputed = hashlib.sha256(rc.canonical(body)).hexdigest()
    except Exception:
        return None
    return recomputed if recomputed == doc.get("closure_digest") \
        else None


def accepted_amended_digests(repo: Path | None = None) -> dict[str, dict]:
    """Return {closure_digest: amendment_entry} for every reduction-only
    amendment whose collector-unchanged proof holds against the LIVE
    tree. Fails closed: any malformed/unprovable entry raises."""
    repo = Path(repo) if repo is not None else rc.ROOT
    path = repo / rc.AREA_REL / "AMENDMENTS.json"
    if not path.is_file():
        return {}
    doc = json.loads(path.read_text(encoding="utf-8"))
    if doc.get("schema") != AMENDMENT_SCHEMA:
        raise FreezeError(f"amendment record schema mismatch "
                          f"(expected {AMENDMENT_SCHEMA})")
    accepted: dict[str, dict] = {}
    head = current_head(repo)
    for entry in doc.get("amendments", []):
        pin = entry.get("evidence_producer_head")
        digest = entry.get("evidence_closure_digest")
        if not isinstance(pin, str) or len(pin) != 40 \
                or not isinstance(digest, str) or len(digest) != 64:
            raise FreezeError("amendment entry malformed "
                              "(pin/digest shape)")
        reach = subprocess.run(
            ["git", "-C", str(repo), "merge-base", "--is-ancestor",
             pin, head], capture_output=True)
        if reach.returncode != 0:
            raise FreezeError(
                f"amendment pin {pin[:12]} is not an ancestor of HEAD")
        at_pin = _closure_digest_at(repo, pin)
        if at_pin is None or at_pin != digest:
            raise FreezeError(
                f"amendment digest for pin {pin[:12]} does not match "
                "the closure record committed at that pin")
        changed = _git_bytes(repo, "diff", "--name-only", pin, head,
                             "--", *PHYSICAL_PRODUCERS)
        if changed is None or changed.strip():
            changed_names = (changed.decode()[:200]
                             if changed is not None else "<git failed>")
            raise FreezeError(
                f"amendment for pin {pin[:12]} is invalid: physical "
                f"producers changed ({changed_names})")
        accepted[digest] = entry
    return accepted


def require_frozen(repo: Path | None = None) -> dict[str, Any]:
    """Producer-side gate: verify the freeze immediately before any
    correctness-bearing emission."""
    return verify_closure(Path(repo) if repo is not None else rc.ROOT)

