#!/usr/bin/env python3
"""Write the review manifest for every issue #74 artifact."""
from __future__ import annotations

import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "docs/qualification/gemma4-12b-it-v1"
OUT = BASE / "MANIFEST.sha256"
EXTRA = (
    ROOT / ".github/workflows/ci.yml",
    ROOT / "ARCHITECTURE.md",
    ROOT / "ROADMAP.md",
    ROOT / "docs/protocols/README.md",
    ROOT / "scripts/build_issue74_manifests.py",
    ROOT / "scripts/commit_issue74_holdout.py",
    ROOT / "scripts/generate_issue74_corpora.py",
    ROOT / "scripts/hash_issue74_artifacts.py",
    ROOT / "scripts/issue74_methodology.py",
    ROOT / "scripts/seal_issue74_holdout.py",
    ROOT / "scripts/select_issue74_margin_stress.py",
    ROOT / "tests/test_issue74_methodology.py",
)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    paths = [path for path in BASE.rglob("*") if path.is_file() and path != OUT]
    paths.extend(EXTRA)
    unique = sorted(set(paths), key=lambda path: path.relative_to(ROOT).as_posix())
    lines = [f"{digest(path)}  {path.relative_to(ROOT).as_posix()}" for path in unique]
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
