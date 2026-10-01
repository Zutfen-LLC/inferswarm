#!/usr/bin/env python3
"""Issue #252 Phase 0: offline baseline and accepted-evidence authentication.

Repository-only deterministic reconciliation. This module performs no physical
execution, GPU access, model reads, or network requests. Accepted evidence is
read-only; all Git source authority hashes are derived from pinned commits.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

import issue252_constants as C


class ReconciliationError(RuntimeError):
    """An expected immutable authority or repository binding failed."""


def _git(root: Path, *args: str, input: bytes | None = None) -> bytes:
    p = subprocess.run(["git", "-C", str(root), *args], input=input,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if p.returncode:
        raise ReconciliationError(f"git {' '.join(args)} failed: {p.stderr.decode(errors='replace').strip()}")
    return p.stdout


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _show(root: Path, head: str, rel: str) -> bytes:
    return _git(root, "show", f"{head}:{rel}")


def _fail(message: str) -> None:
    raise ReconciliationError(message)


def _parse_manifest(root: Path, manifest: Path) -> list[dict[str, str]]:
    rows = []
    for number, line in enumerate(manifest.read_text().splitlines(), 1):
        if not line.strip():
            continue
        try:
            digest, rel = line.split("  ", 1)
        except ValueError:
            _fail(f"manifest malformed row {number}")
        path = root / rel
        if not path.is_file():
            _fail(f"manifest artifact missing: {rel}")
        actual = _sha(path.read_bytes())
        if actual != digest:
            _fail(f"manifest digest mismatch: {rel}")
        rows.append({"path": rel, "sha256": actual})
    return rows


def verify_terminalization(repo_root: Path,
                           terminalization_head: str = C.ACCEPTED_TERMINALIZATION_HEAD) -> dict[str, Any]:
    root = Path(repo_root)
    area = root / C.TERMINALIZATION_REL
    manifest = area / "MANIFEST.sha256"
    if not manifest.is_file():
        _fail("accepted terminalization MANIFEST.sha256 missing")
    rows = _parse_manifest(root, manifest)
    terminal_path = area / "TERMINAL.json"
    if not terminal_path.is_file():
        _fail("accepted terminalization TERMINAL.json missing")
    doc = json.loads(terminal_path.read_bytes())
    if doc.get("terminal") != C.PREDECESSOR_TERMINAL:
        _fail("accepted predecessor terminal name mismatch")
    # TERMINAL.json records the llama.cpp source pin (not the execution head).
    source_head = doc.get("source_build", {}).get("source_head")
    if source_head != C.LLAMA_PIN:
        _fail("terminalization source head does not match llama.cpp pin")
    # The accepted physical execution head is authenticated by the retained
    # dispatch-authority record (head_sha + dispatch body binding).
    dispatch_path = area / "dispatch-authority.json"
    if not dispatch_path.is_file():
        _fail("accepted terminalization dispatch-authority.json missing")
    dispatch = json.loads(dispatch_path.read_bytes())
    if dispatch.get("head_sha") != C.ACCEPTED_EXECUTION_HEAD:
        _fail("accepted predecessor execution head mismatch")
    body = dispatch.get("body", "")
    if f"head={C.ACCEPTED_EXECUTION_HEAD}" not in body:
        _fail("dispatch authority head binding missing")
    if "R8I3B PHYSICAL DISPATCH #250" not in body:
        _fail("dispatch authority phrase missing")
    # Terminalization commit identity is authenticated by exact pinned object
    # existence and by the unchanged terminalization bytes at that commit.
    _git(root, "cat-file", "-e", f"{terminalization_head}^{{commit}}")
    pinned_terminal = _show(root, terminalization_head,
                            C.TERMINALIZATION_REL + "/TERMINAL.json")
    if pinned_terminal != terminal_path.read_bytes():
        _fail("accepted terminalization head artifact differs from working tree")
    return {"manifest_rows": rows, "manifest_row_count": len(rows),
            "terminal": doc.get("terminal"),
            "terminalization_head": terminalization_head,
            "execution_head": C.ACCEPTED_EXECUTION_HEAD}


def verify_contrast_authority(repo_root: Path) -> list[dict[str, Any]]:
    rows = []
    for rel in C.REFERENCE_PATHS:
        try:
            data = _show(Path(repo_root), C.ACCEPTED_TERMINALIZATION_HEAD, rel)
        except ReconciliationError:
            # The reviewed rederivation is a retained source under the evidence
            # tree, not necessarily a source-code path. Resolve at accepted merge.
            data = _show(Path(repo_root), C.ACCEPTED_MERGE_HEAD, rel)
        if C.ACCEPTED_248_MANIFEST_SELF_DIGEST.encode() not in data:
            _fail("accepted #248 manifest digest constant occurrence missing")
        rows.append({"identity": f"{C.ACCEPTED_TERMINALIZATION_HEAD}:{rel}",
                     "sha256": _sha(data), "full_pin_occurs": True})
    return rows


def verify_llama_pin(llama_root: Path) -> dict[str, str]:
    root = Path(llama_root)
    if not root.is_dir():
        _fail(f"llama.cpp fixture/repository missing: {root}")
    head = _git(root, "rev-parse", "HEAD").decode().strip()
    tree = _git(root, "rev-parse", "HEAD^{tree}").decode().strip()
    if head != C.LLAMA_PIN:
        _fail(f"llama.cpp HEAD mismatch: {head}")
    if tree != C.LLAMA_PIN_TREE:
        _fail(f"llama.cpp tree mismatch: {tree}")
    return {"path": str(root), "head": head, "tree": tree, "verified": "true"}


def derive_reconciliation(repo_root: Path, llama_root: Path,
                          expected_base: str = C.EXPECTED_BASE_HEAD) -> dict[str, Any]:
    root = Path(repo_root)
    # The accepted merge must be an ancestor of the working HEAD (the Phase-0
    # branch adds commits on top of it). The live HEAD is deliberately NOT
    # embedded in the artifact so re-runs stay byte-identical as HEAD moves.
    _git(root, "merge-base", "--is-ancestor", expected_base, "HEAD")
    _git(root, "merge-base", "--is-ancestor", C.ACCEPTED_MERGE_HEAD, "HEAD")
    accepted = verify_terminalization(root)
    authorities = verify_contrast_authority(root)
    llama = verify_llama_pin(Path(llama_root))
    return {
        "schema": "inferswarm.issue252.phase0.reconciliation/1",
        "issue": C.ISSUE,
        "kind": C.KIND,
        "status": "RECONCILED",
        "physical_execution": False,
        "repository": {"expected_base": expected_base,
                       "expected_base_is_ancestor": True,
                       "accepted_merge_is_ancestor": True},
        "predecessor": {"issue": C.PREDECESSOR_ISSUE,
                         "accepted_pr": C.ACCEPTED_PR, **accepted},
        "accepted_248_contrast_authority": {
            "manifest_self_digest": C.ACCEPTED_248_MANIFEST_SELF_DIGEST,
            "references": authorities},
        "llama_cpp_pin": llama,
        "comparator_sha256": C.COMPARATOR_SHA256,
        "model": C.MODEL,
        "model_members": C.MODEL_MEMBERS,
        "localized_factor": C.LOCALIZED_FACTOR,
        "host_facts": C.HOST_FACTS,
        "terminal_vocabulary": [C.ACCEPTED_TERMINAL, C.NOT_VALIDATED_TERMINAL,
                                 C.UNRESOLVED_TERMINAL],
        "dispatch_phrase_format": C.DISPATCH_PHRASE_FORMAT,
    }


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo-root", default=".")
    ap.add_argument("--llama-root", default="/home/zutfen/llama.cpp-252")
    ap.add_argument("--expected-base", default=C.EXPECTED_BASE_HEAD)
    ap.add_argument("--output", required=True)
    args = ap.parse_args()
    doc = derive_reconciliation(Path(args.repo_root), Path(args.llama_root), args.expected_base)
    payload = json.dumps(doc, indent=1, sort_keys=True).encode() + b"\n"
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(payload)
    print(f"reconciliation written: {out} (sha256 {_sha(payload)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
