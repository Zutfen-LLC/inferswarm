#!/usr/bin/env python3
"""Replay authenticated #262 source then apply only #264 output MMV dispatch edits."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

import issue262_source_patch as parent

AREA = parent.AREA
VK = parent.VK_SOURCE
PARENT_TREE = I262_TREE = "015c874f0cc0635fa1369650098c0137f9a492f0"
PARENT_VK_SHA256 = "abb1031f1b35a669cb5a18b776fc6587cfb7927384729128048dd697b8160dbb"
PATCH = AREA / "patches/issue264-mmv-selector.patch"
IDENTITY = AREA / "issue264-source-identity.json"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def git(root: Path, *args: str, env=None) -> str:
    result = subprocess.run(["git", "-C", str(root), *args], text=True,
                            capture_output=True, env=env)
    if result.returncode:
        raise ValueError(f"git {args}: {result.stderr.strip()}")
    return result.stdout.strip()


def authenticate(root: Path) -> str:
    """Hash the complete working source in an isolated Git index, not HEAD."""
    with tempfile.TemporaryDirectory(prefix="i264-index-") as tmp:
        env = dict(os.environ, GIT_INDEX_FILE=str(Path(tmp) / "index"))
        git(root, "read-tree", "HEAD", env=env)
        git(root, "add", "-u", env=env)
        if git(root, "ls-files", "--others", "--exclude-standard"):
            raise ValueError("untracked source files")
        return git(root, "write-tree", env=env)


def build(source: Path, output: Path) -> dict:
    """Create a new destination; refuse parent drift before applying the frozen patch."""
    if not PATCH.is_file():
        raise ValueError("frozen #264 patch absent")
    record = parent.build(source, output)
    if record["instrumented262_tree"] != PARENT_TREE or sha((output / VK).read_bytes()) != PARENT_VK_SHA256:
        raise ValueError("#262 complete-tree or Vulkan source drift")
    if authenticate(output) != PARENT_TREE:
        raise ValueError("#262 full working tree drift")
    git(output, "apply", "--check", str(PATCH))
    git(output, "apply", str(PATCH))
    return {"parent_tree": PARENT_TREE, "parent_vk_sha256": PARENT_VK_SHA256,
            "patch_sha256": sha(PATCH.read_bytes()),
            "issue264_vk_sha256": sha((output / VK).read_bytes()),
            "issue264_tree": authenticate(output)}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source", required=True, type=Path)
    ap.add_argument("--output", required=True, type=Path)
    ap.add_argument("--freeze", action="store_true")
    args = ap.parse_args()
    if args.freeze and IDENTITY.exists():
        ap.error("identity already frozen")
    result = build(args.source, args.output)
    if args.freeze:
        IDENTITY.open("x").write(json.dumps(result, sort_keys=True, indent=2) + "\n")
    elif not IDENTITY.exists() or json.loads(IDENTITY.read_text()) != result:
        ap.error("identity absent or drifted")
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
