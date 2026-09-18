#!/usr/bin/env python3
"""Issue #216 — V2-D fail-closed producer freeze (corrected closure).

Supersedes the index-based closure (PRODUCER-CLOSURE.json schema /2,
which hashed `git show :<path>` while Python executed working-tree
bytes). The corrected mechanism proves the EXACT BYTES BEING EXECUTED:

  * an exact producer/review HEAD is pinned in the committed closure
    record (`producer_head`);
  * for every CLOSURE_SOURCES file the closure hashes the ACTUAL
    working-tree bytes AND independently compares them against
    `HEAD:<path>` (via `git cat-file blob`, never the index);
  * staged drift fails closed (index bytes must equal HEAD bytes for
    every source);
  * unstaged drift fails closed (worktree bytes must equal index bytes);
  * missing / untracked / substituted closure sources fail closed
    (every source must be TRACKED at the pinned HEAD and present in the
    worktree with identical bytes);
  * the whole worktree must be clean of ANY unstaged modification to a
    closure source, and the index must hold no staged difference for a
    closure source, before any producer may emit or the assembler may
    reduce.

The Git index is never used as a substitute for executed-byte identity:
it is only one of two independent channels (worktree bytes, HEAD blob)
that must AGREE, plus a third (index blob) whose disagreement is itself
rejection evidence.

Phase→producer binding: every emitted phase record must carry the
closure digest, and `assemble()` verifies that binding FIRST — before
reducing any phase — so evidence produced under any other producer
identity fails closed. (Producers embed it via
`issue216_receipt.require_frozen()`; the assembler re-verifies.)
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

import issue216_receipt as rc


class FreezeError(RuntimeError):
    """The producer freeze failed; no correctness-bearing output may be
    produced or accepted."""


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, check=check)


def _git_bytes(repo: Path, *args: str) -> bytes | None:
    proc = _git(repo, *args, check=False)
    return proc.stdout if proc.returncode == 0 else None


def worktree_source_sha256(repo: Path, rel: str) -> str:
    """Hash the ACTUAL working-tree bytes of one closure source."""
    path = repo / rel
    if not path.is_file():
        raise FreezeError(f"closure source missing from worktree: {rel}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def head_source_sha256(repo: Path, rel: str, head: str) -> str | None:
    """Hash the HEAD blob of one closure source (never the index)."""
    data = _git_bytes(repo, "cat-file", "blob", f"{head}:{rel}")
    return None if data is None else hashlib.sha256(data).hexdigest()


def index_source_sha256(repo: Path, rel: str) -> str | None:
    """Hash the INDEX blob of one closure source (staged bytes)."""
    data = _git_bytes(repo, "show", f":{rel}")
    return None if data is None else hashlib.sha256(data).hexdigest()


def is_tracked_at_head(repo: Path, rel: str, head: str) -> bool:
    proc = _git(repo, "cat-file", "-e", f"{head}:{rel}", check=False)
    return proc.returncode == 0


def current_head(repo: Path) -> str:
    proc = _git(repo, "rev-parse", "HEAD")
    return proc.stdout.decode().strip()


def closure_document(repo: Path = rc.ROOT,
                      sources: tuple[str, ...] | None = None
                      ) -> dict[str, Any]:
    """Build the corrected closure over the CURRENT tree + HEAD.

    Fails closed (FreezeError) unless, for every closure source:
      worktree bytes == index bytes == HEAD blob bytes,
    i.e. no staged drift, no unstaged drift, no missing/untracked/
    substituted source. Returns the closure document whose
    `closure_digest` binds {producer_head, sources} — this digest is
    what every phase record must carry and what the assembler verifies.

    `sources` overrides the closure source set for CPU tests that build
    a mini producer repo (the default is the campaign's
    rc.CLOSURE_SOURCES).
    """
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
        if hd is None:  # defensive; tracked check above should cover
            raise FreezeError(f"closure source missing at HEAD: {rel}")
        if wt != idx:
            raise FreezeError(
                f"unstaged producer drift (worktree != index): {rel}")
        if idx != hd:
            raise FreezeError(
                f"staged producer drift (index != HEAD): {rel}")
        out_sources[rel] = wt
    doc = {
        "schema": "inferswarm.v2d.producer-closure/3",
        "campaign_id": rc.CAMPAIGN_ID,
        "producer_head": head,
        "sources": out_sources,
    }
    doc["closure_digest"] = hashlib.sha256(
        rc.canonical({k: v for k, v in doc.items()
                      if k != "closure_digest"})).hexdigest()
    return doc


def verify_closure(repo: Path = rc.ROOT,
                   committed: dict[str, Any] | None = None,
                   sources: tuple[str, ...] | None = None,
                   record_rel: str | None = None
                   ) -> dict[str, Any]:
    """Verify the committed closure record against the LIVE tree.

    The closure record pins the PRODUCER-SOURCE head (the commit whose
    blobs are the reviewed, executed bytes). A commit containing a
    closure pinning its own SHA is unsatisfiable (self-reference), so
    the record itself lands in a FOLLOWING commit; HEAD may therefore
    advance past the pin, but only via commits that touch NO closure
    source. Fail-closed checks:

      1. schema /3, campaign id, pinned 40-hex producer_head, and the
         source SET equals CLOSURE_SOURCES exactly (no missing/
         untracked/substituted closure source);
      2. every source's PINNED-HEAD blob hash equals the record's
         digest (the record cannot carry a bogus pin);
      3. every source's INDEX blob equals the pinned blob (no staged
         drift) and its WORKTREE bytes equal the pinned blob (no
         unstaged drift — the bytes Python executes are the reviewed
         bytes);
      4. `git diff --name-only <pin> HEAD -- <sources>` is empty (no
         intervening commit replaced a producer between freeze and now).
    """
    record_path = repo / (record_rel
                          if record_rel is not None
                          else f"{rc.AREA_REL}/{rc.CLOSURE_NAME}")
    if committed is None:
        if not record_path.is_file():
            raise FreezeError(f"committed closure missing: {record_path}")
        committed = json.loads(record_path.read_text(encoding="utf-8"))
    assert committed is not None
    if committed.get("schema") != "inferswarm.v2d.producer-closure/3":
        raise FreezeError(
            f"closure schema mismatch (expected /3, got "
            f"{committed.get('schema')!r}); the index-based /2 closure "
            "cannot prove executed-byte identity and is retired")
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
    # (2)+(3) every recorded digest must equal the pinned blob, the
    # index blob, and the actual worktree bytes
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
            raise FreezeError(
                f"unstaged producer drift (worktree != pin): {rel}")
    # (4) HEAD may advance past the pin only without touching sources.
    # A reduction-only AMENDMENT (see accepted_amended_digests) is the
    # one legal exception: physical collectors unchanged, reducer
    # hardened, authority NOT regenerated. The amendment must pin the
    # OLD producer head whose closure the retained evidence binds and
    # carry its self-bound closure digest.
    diff = _git_bytes(repo, "diff", "--name-only", pinned,
                      current_head(repo), "--", *closure_sources)
    if diff is None or diff.strip():
        amended = accepted_amended_digests(repo)
        pin_diff = _git_bytes(repo, "diff", "--name-only", pinned,
                              current_head(repo), "--",
                              *PHYSICAL_PRODUCERS)
        # The live pin must itself be an amendment entry (the evidence
        # binds THIS record's digest) — otherwise the closure moved and
        # the retained evidence belongs to another producer identity.
        entry = amended.get(committed.get("closure_digest"))
        if entry is None or pin_diff is None or pin_diff.strip():
            raise FreezeError(
                "producer sources changed between the pinned head and "
                "HEAD — re-freeze (regenerate the closure) before any "
                "producer emits or the assembler reduces")
    # digest binding: record digest must equal the canonical digest of
    # its own content
    body = {k: v for k, v in committed.items() if k != "closure_digest"}
    recomputed = hashlib.sha256(rc.canonical(body)).hexdigest()
    if committed.get("closure_digest") != recomputed:
        raise FreezeError("closure record digest does not bind its content")
    return committed


def write_closure(repo: Path = rc.ROOT) -> Path:
    """Regenerate the committed closure record pinning the CURRENT head
    as the producer-source head.

    Only legal while the tree is frozen for every closure source
    (closure_document() enforces that). The record pins the head BEFORE
    the record's own commit; verify_closure() then admits only later
    commits that touch no closure source.
    """
    record_path = repo / rc.AREA_REL / rc.CLOSURE_NAME
    record_path.parent.mkdir(parents=True, exist_ok=True)
    doc = closure_document(repo)
    record_path.write_bytes(json.dumps(doc, indent=1, sort_keys=True)
                            .encode("utf-8") + b"\n")
    return record_path


def require_frozen(repo: Path = rc.ROOT) -> dict[str, Any]:
    """Producer-side gate: verify the freeze immediately before any
    correctness-bearing emission. Returns the verified closure so the
    caller can embed closure_digest + producer_head in the record."""
    return verify_closure(repo)


def assert_execution_provenance(repo: Path = rc.ROOT,
                                  sources: tuple[str, ...] | None = None,
                                  record_rel: str | None = None
                                  ) -> dict[str, Any]:
    """Fail-closed proof that the bytes about to execute ARE the frozen
    bytes: for every closure source, the working-tree file's bytes hash
    to the committed closure's source digest (executed-byte identity),
    and independently equal HEAD's blob (reviewed identity)."""
    closure = verify_closure(repo, sources=sources,
                             record_rel=record_rel)
    head = closure["producer_head"]
    for rel, expected in closure["sources"].items():
        wt = worktree_source_sha256(repo, rel)
        if wt != expected:
            raise FreezeError(
                f"executed-byte identity failure: worktree {rel} hash "
                f"{wt} != closure {expected}")
        hd = head_source_sha256(repo, rel, head)
        if hd != expected:
            raise FreezeError(
                f"reviewed-identity failure: HEAD blob {rel} hash {hd} "
                f"!= closure {expected}")
    return closure


# --- reduction-only amendment protocol -------------------------------
# Reduction-layer hardening AFTER retained physical output does not
# invalidate the evidence: the collectors' executed bytes are unchanged.
# An AMENDMENTS.json entry records each such transition and the verifier
# re-proves, mechanically, that no PHYSICAL producer changed between
# the head the evidence binds and the current HEAD.

PHYSICAL_PRODUCERS: tuple[str, ...] = (
    "scripts/issue216_physical_authority.py",
    "scripts/issue216_host.py",
    "scripts/issue216_execution.py",
    "scripts/issue216_preflight.py",
    "scripts/issue216_concurrent.py",
    "scripts/issue216_transport.py",
    "scripts/issue216_soak.py",
    "scripts/issue216_fault.py",
    "scripts/issue216_reset.py",
)

AMENDMENT_SCHEMA = "inferswarm.v2d.producer-amendments/1"


def _closure_digest_at(repo: Path, pin: str) -> str | None:
    """Recompute the committed closure record's self-bound digest at an
    arbitrary historical pin (fails closed on any tampering)."""
    raw = _git_bytes(repo, "show",
                     f"{pin}:{rc.AREA_REL}/{rc.CLOSURE_NAME}")
    if not raw:
        return None
    try:
        doc = json.loads(raw.decode("utf-8"))
        body = {k: v for k, v in doc.items() if k != "closure_digest"}
        import hashlib as _h
        recomputed = _h.sha256(rc.canonical(body)).hexdigest()
    except Exception:
        return None
    return recomputed if recomputed == doc.get("closure_digest") \
        else None


def accepted_amended_digests(repo: Path = rc.ROOT) -> dict[str, dict]:
    """Return {closure_digest: amendment_entry} for every reduction-only
    amendment whose collector-unchanged proof holds against the LIVE
    tree. Fails closed: any malformed/unprovable entry raises."""
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
        # (a) the pin must be real history reachable from HEAD
        reach = subprocess.run(
            ["git", "-C", str(repo), "merge-base", "--is-ancestor",
             pin, head], capture_output=True)
        if reach.returncode != 0:
            raise FreezeError(
                f"amendment pin {pin[:12]} is not an ancestor of HEAD")
        # (b) the recorded digest must equal the closure record's own
        # self-bound digest as committed at the pin
        at_pin = _closure_digest_at(repo, pin)
        if at_pin is None or at_pin != digest:
            raise FreezeError(
                f"amendment digest for pin {pin[:12]} does not match "
                "the closure record committed at that pin")
        # (c) collector-unchanged proof: no PHYSICAL producer byte may
        # differ between the evidence pin and the live HEAD
        changed = _git_bytes(repo, "diff", "--name-only", pin, head,
                             "--", *PHYSICAL_PRODUCERS)
        if changed is None or changed.strip():
            raise FreezeError(
                f"amendment for pin {pin[:12]} is invalid: physical "
                f"producers changed ({changed.decode()[:200]})")
        if entry.get("authority_regenerated"):
            raise FreezeError(
                f"amendment for pin {pin[:12]} regenerated the "
                "authority — not a reduction-only fix; evidence is "
                "superseded and a new campaign is required")
        accepted[digest] = entry
    return accepted
