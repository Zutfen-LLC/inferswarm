#!/usr/bin/env python3
"""Emit this additive compatibility bundle's terminal manifest (CPU-only).

Print deterministic repository-root-relative rows. Never read an existing
manifest or living status/CI. Redirect stdout to MANIFEST.sha256 after all
bundle/source/test bytes are final. Generic evidence lifecycle tests verify it.
"""
import hashlib
from pathlib import Path

BUNDLE = Path(__file__).resolve().parent
ROOT = BUNDLE.parents[3]
BOUND = (
    "scripts/issue280_observer.py", "scripts/issue280_runner.py",
    "scripts/issue280_compatibility.py", "scripts/issue280_source_compat.py",
    "scripts/issue280_source.py", "scripts/issue280_task_check.py",
    "tests/test_issue280_admission.py", "tests/test_issue280_observer.py",
    "tests/test_issue280_real_compat.py", "tests/test_issue280_source_compat.py",
    "tests/test_issue280_retention_fix.py", "tests/test_issue280_runner.py",
    "tests/test_issue280_source.py", "tests/test_issue280_task_check.py",
    "docs/investigations/vulkan-same-request-280/CORRECTION-REAL-R1.md",
)

if __name__ == "__main__":
    files = {ROOT / relative for relative in BOUND}
    files.update(p for p in BUNDLE.rglob("*") if p.is_file()
                 and p.name != "MANIFEST.sha256" and "__pycache__" not in p.parts
                 and p.suffix != ".pyc")
    for path in sorted(files, key=lambda p: p.relative_to(ROOT).as_posix()):
        print(hashlib.sha256(path.read_bytes()).hexdigest() + "  " + path.relative_to(ROOT).as_posix())
