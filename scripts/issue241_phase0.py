#!/usr/bin/env python3
"""CPU-only Issue #241 Phase 0 preservation audit.

Verifies, before anything else and without any device access:
  - the working tree descends from the exact accepted merge
    3aa59aed74df7f00302a6a2eb84640623b7cc14b (git ancestry, not just
    tree equality);
  - every accepted R8-I evidence file (all 28 MANIFEST.sha256 rows) is
    byte-preserved;
  - the sealed holdout ciphertext and certificate hashes are unchanged;
  - zero predictive-namespace evidence exists in the new campaign area;
  - the superseded #240 exploration area is untouched by this branch.

Fails closed on every axis. Emits a parseable JSON audit report.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import issue241_constants as C

SCHEMA = "inferswarm.issue241.phase0-preservation-audit/1"


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args], check=True,
        capture_output=True, text=True)
    return result.stdout.strip()


def audit_phase0(repo: Path | None = None) -> dict[str, Any]:
    repo = (repo or C.ROOT).resolve()
    problems: list[str] = []

    head = _git(repo, "rev-parse", "HEAD")
    ancestry = _git(repo, "merge-base", "--is-ancestor", C.ACCEPTED_MAIN, "HEAD")
    if ancestry != "" or subprocess.run(
            ["git", "-C", str(repo), "merge-base", "--is-ancestor",
             C.ACCEPTED_MAIN, "HEAD"]).returncode != 0:
        problems.append(
            f"HEAD {head} does not descend from accepted {C.ACCEPTED_MAIN}")

    # Byte-preservation of all accepted R8-I evidence rows
    preserved = 0
    drifted: dict[str, str] = {}
    import hashlib
    for rel, expected in C.accepted_r8i_file_digest(repo).items():
        path = repo / rel
        if not path.is_file():
            drifted[rel] = "missing"
            continue
        got = hashlib.sha256(path.read_bytes()).hexdigest()
        if got != expected:
            drifted[rel] = f"{got} != {expected}"
        else:
            preserved += 1
    if drifted:
        problems.append(f"accepted R8-I evidence drift: {drifted}")

    holdout = hashlib.sha256(
        (repo / C.R8I_HOLDOUT_REL).read_bytes()).hexdigest()
    expected_holdout = C.accepted_r8i_file_digest(repo)[C.R8I_HOLDOUT_REL]
    if holdout != expected_holdout:
        problems.append("sealed holdout ciphertext hash changed")

    # Zero predictive-namespace CASE EVIDENCE in the campaign area.
    # Real predictive case ids are namespace + digits (c237-01-01-001);
    # the bare prefixes appear legitimately in prohibition prose.
    area = repo / C.AREA_REL
    predictive_hits: list[str] = []
    predictive_re = [re.compile(pref + r"\d") for pref in C.PROHIBITED_CASE_PREFIXES]
    if area.exists():
        for p in area.rglob("*"):
            if p.is_file():
                try:
                    text = p.read_text(errors="replace")
                except OSError:
                    continue
                for rx in predictive_re:
                    if rx.search(text):
                        predictive_hits.append(
                            f"{p.relative_to(repo)}:{rx.pattern}")
    if predictive_hits:
        problems.append(f"predictive-namespace evidence present: {predictive_hits}")

    # The superseded #240 exploration must not be continued here
    is240_area = repo / "docs/investigations/qwen38-flash-next-r8-i2"
    if is240_area.exists():
        changed = _git(repo, "diff", "--name-only", C.ACCEPTED_MAIN, "--",
                       "docs/investigations/qwen38-flash-next-r8-i2")
        if changed:
            problems.append(
                "superseded #240 exploration area modified by this branch")

    report: dict[str, Any] = {
        "schema": SCHEMA,
        "campaign": C.CAMPAIGN_ID,
        "head": head,
        "accepted_main": C.ACCEPTED_MAIN,
        "accepted_ancestry_ok": not any(
            "does not descend" in p for p in problems),
        "r8i_files_preserved": preserved,
        "r8i_files_total": len(C.accepted_r8i_file_digest(repo)),
        "holdout_ciphertext_sha256": holdout,
        "predictive_evidence_hits": predictive_hits,
        "problems": problems,
        "clean": not problems,
    }
    return report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--out", type=Path, default=None,
                    help="optional report output path")
    args = ap.parse_args(argv)
    report = audit_phase0()
    text = json.dumps(report, indent=2, sort_keys=True)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n")
    print(text)
    return 0 if report["clean"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
