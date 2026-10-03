#!/usr/bin/env python3
"""#262 H5 instrumentation source transform and identity freeze.

Builds the #262 instrumented comparator source from the pinned predecessor
through the EXACT accepted chain, in one fail-closed script:

  1. pinned clean llama.cpp b29c606e (predecessor commit/tree verified);
  2. the frozen #260 Vulkan instrumentation patch (H2/H3 markers);
  3. the #262 H5 route-marker edits (fail-closed anchor script);
  4. the accepted R8-E observation patch (sha-verified);
  5. the accepted comparator/2 observer seam (patched source sha-verified).

The resulting FULL instrumented tree identity is frozen in
issue262-source-identity.json. The ggml-vulkan.cpp intermediate identity
(after steps 2+3) is frozen alongside it so the H5 patch alone is
reproducible: patching ggml-vulkan.cpp of the #260 instrumented tree with
patches/issue262-h5-route.patch must yield exactly h5_vk_source_sha256.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
AREA = REPO / "docs/investigations/qwen38-flash-next-r8-i3c-vulkan-mechanism"
IDENTITY_REL = "issue262-source-identity.json"
IDENTITY_PATH = AREA / IDENTITY_REL
H5_PATCH_REL = "patches/issue262-h5-route.patch"
H5_EDITOR_REL = "patches/issue262_h5_edit.py"

PREDECESSOR_COMMIT = "b29c606e28a01b1bc8c1351026a0fa6e616bf6c4"
PREDECESSOR_TREE = "950999fe62b7fe55f44ab5b7394e3c8542f37f12"
I260_PATCH_REL = "patches/issue260-vulkan-instrumentation.patch"
R8E_PATCH_REL = "../qwen38-flash-next-r8-e/evidence/instrumentation/applied-source.patch"
R8E_PATCH_SHA256 = "058674419daa1189b25b80e99278001e437827a97c9a2d68ed7e24f03df0d659"
OBSERVER_PATCHED_SOURCE_SHA256 = (
    "2f1f3d5461c39b94d4dc92c74e03da5fb0b1af069f1aeda1df587a25c3ffe89f")

VK_SOURCE = "ggml/src/ggml-vulkan/ggml-vulkan.cpp"
SERVER_SOURCE = "tools/server/server-context.cpp"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(root), *args],
                          text=True, capture_output=True)


def _fail(message: str) -> "NoReturn":  # type: ignore[valid-type]
    sys.exit(message)


def build(source: Path, output: Path) -> dict:
    source, output = Path(source), Path(output)
    if not source.is_dir():
        _fail(f"pinned source missing: {source}")
    head = _git(source, "rev-parse", "HEAD")
    tree = _git(source, "rev-parse", "HEAD^{tree}")
    status = _git(source, "status", "--porcelain", "--untracked-files=all")
    if (head.returncode or head.stdout.strip() != PREDECESSOR_COMMIT
            or tree.returncode or tree.stdout.strip() != PREDECESSOR_TREE):
        _fail("source is not the exact pinned clean checkout")
    if status.returncode or status.stdout.strip():
        _fail("pinned source must be clean")
    i260_patch = AREA / I260_PATCH_REL
    r8e_patch = (AREA / R8E_PATCH_REL).resolve()
    h5_editor = AREA / H5_EDITOR_REL
    for path in (i260_patch, r8e_patch, h5_editor):
        if not path.is_file():
            _fail(f"required patch artifact missing: {path}")
    if _sha(r8e_patch.read_bytes()) != R8E_PATCH_SHA256:
        _fail("accepted R8-E patch digest drift")
    if output.exists():
        _fail("output directory already exists")
    output.parent.mkdir(parents=True, exist_ok=True)
    clone = subprocess.run(
        ["git", "clone", "--shared", "--no-checkout", str(source), str(output)],
        text=True, capture_output=True)
    if clone.returncode:
        _fail(clone.stderr.strip())
    checkout = _git(output, "checkout", "--detach", PREDECESSOR_COMMIT)
    if checkout.returncode:
        _fail(checkout.stderr.strip())

    def apply(patch: Path, what: str) -> None:
        check = _git(output, "apply", "--check", str(patch))
        if check.returncode:
            _fail(f"{what} context check failed: {check.stderr.strip()}")
        applied = _git(output, "apply", str(patch))
        if applied.returncode:
            _fail(f"{what} failed: {applied.stderr.strip()}")

    apply(i260_patch, "#260 instrumentation patch")
    h5_patch = AREA / H5_PATCH_REL
    check = _git(output, "apply", "--check", str(h5_patch))
    if check.returncode == 0:
        applied = _git(output, "apply", str(h5_patch))
        if applied.returncode:
            _fail(f"H5 patch failed: {applied.stderr.strip()}")
    else:
        # Anchor-editor fallback: identical edits, fail-closed anchors.
        edit = subprocess.run(
            [sys.executable, str(h5_editor),
             str(output / VK_SOURCE), str(output / VK_SOURCE)],
            text=True, capture_output=True)
        if edit.returncode:
            _fail(f"H5 edits failed: {edit.stderr.strip()}")
    h5_vk_sha = _sha((output / VK_SOURCE).read_bytes())
    apply(r8e_patch, "accepted R8-E observation patch")
    # comparator/2 seam: reuse the accepted #241 module frozen in git history
    # of this repository (accepted head 4e8b4fc) via git show, never a copy.
    show = _git(REPO, "show", "4e8b4fc369defe409f68da46e26d152eade4df47:"
                 "scripts/issue241_observer_patch.py")
    if show.returncode:
        _fail("accepted comparator/2 seam module not found in history")
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as handle:
        handle.write(show.stdout)
        seam_path = Path(handle.name)
    try:
        seam = subprocess.run(
            [sys.executable, str(seam_path), "--source",
             str(output / SERVER_SOURCE), "--out", str(output / SERVER_SOURCE)],
            text=True, capture_output=True)
    finally:
        seam_path.unlink(missing_ok=True)
    if seam.returncode:
        _fail(f"comparator/2 seam failed: {seam.stderr.strip()}")
    server_sha = _sha((output / SERVER_SOURCE).read_bytes())
    if server_sha != OBSERVER_PATCHED_SOURCE_SHA256:
        _fail("comparator/2 patched server source digest mismatch")
    staged = _git(output, "add", "-A")
    tree_result = _git(output, "write-tree") if staged.returncode == 0 else staged
    if tree_result.returncode:
        _fail("cannot determine transformed tree: " + tree_result.stderr.strip())
    return {
        "predecessor_commit": PREDECESSOR_COMMIT,
        "predecessor_tree": PREDECESSOR_TREE,
        "i260_patch_sha256": _sha(i260_patch.read_bytes()),
        "h5_editor_sha256": _sha(h5_editor.read_bytes()),
        "h5_patch_sha256": _sha((AREA / H5_PATCH_REL).read_bytes())
                           if (AREA / H5_PATCH_REL).is_file() else None,
        "h5_vk_source_sha256": h5_vk_sha,
        "r8e_patch_sha256": R8E_PATCH_SHA256,
        "server_source_sha256": server_sha,
        "instrumented262_tree": tree_result.stdout.strip(),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True, type=Path)
    ap.add_argument("--output", required=True, type=Path)
    ap.add_argument("--freeze", action="store_true",
                    help="Create the identity once; otherwise verify it")
    args = ap.parse_args()
    identity = build(args.source, args.output)
    if IDENTITY_PATH.exists():
        frozen = json.loads(IDENTITY_PATH.read_text(encoding="utf-8"))
        if args.freeze:
            _fail("identity is already frozen")
        for key, value in identity.items():
            if value is not None and frozen.get(key) != value:
                _fail(f"instrumented source identity drift: {key}")
        print(json.dumps({k: v for k, v in identity.items()}, sort_keys=True))
    elif args.freeze:
        IDENTITY_PATH.open("x", encoding="utf-8").write(
            json.dumps(identity, sort_keys=True, indent=1) + "\n")
        print(json.dumps(identity, sort_keys=True))
    else:
        _fail("source identity is not frozen; use --freeze exactly once")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
