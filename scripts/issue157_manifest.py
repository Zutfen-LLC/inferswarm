#!/usr/bin/env python3
"""Issue #157 bundle manifest builder (fail-closed).

Enumerates the #157 evidence bundle directory, requires EXACTLY the
expected entry set (no missing, no unexpected), and writes
MANIFEST.sha256.  Fails closed on any drift.  Never touches parent
(#117/#133/#137/#153) manifests.
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

BUNDLE = Path(__file__).resolve().parents[1] / (
    "docs/implementation/r6-successor-dense-full-integration-117/"
    "evidence/arm-c-chunk2-diagnosis-157"
)

EXPECTED = sorted([
    "MANIFEST.sha256",
    "METHODOLOGY.md",
    "README.md",
    "baseline-reproduction.json",
    "diagnostic-conclusions.json",
    "exact-state-replay.json",
    "instrumentation-manifest.json",
    "interventions.json",
    "launch-ledger.json",
    "physical-diagnostic-authority.json",
])


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def main(argv=None) -> int:
    check_only = "--check" in (argv or [])
    present = sorted(p.name for p in BUNDLE.iterdir() if p.is_file())
    if present != EXPECTED:
        missing = sorted(set(EXPECTED) - set(present))
        unexpected = sorted(set(present) - set(EXPECTED))
        print(f"FAIL: bundle entry drift: missing={missing} "
              f"unexpected={unexpected}")
        return 1
    prefix = (
        "docs/implementation/r6-successor-dense-full-integration-117/"
        "evidence/arm-c-chunk2-diagnosis-157/"
    )
    rows = []
    for name in EXPECTED:
        if name == "MANIFEST.sha256":
            continue
        rows.append(f"{sha256_file(BUNDLE / name)}  {prefix}{name}")
    manifest = "\n".join(rows) + "\n"
    manifest_path = BUNDLE / "MANIFEST.sha256"
    if check_only:
        if manifest_path.read_text() != manifest:
            print("FAIL: manifest drift")
            return 1
        print("OK: manifest current")
        return 0
    manifest_path.write_text(manifest)
    print(f"wrote {manifest_path} ({len(rows)} entries)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
