#!/usr/bin/env python3
"""Fail closed on immutable Issue #109 prerequisite source identities."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from issue74_methodology import MethodologyError, sha256_file

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "docs/qualification/gemma4-12b-it-v5/manifests/prerequisite-bindings.json"
ACCEPTED_108_MERGE = "ee394c68a86428576b78299b90902904a196e786"
HISTORICAL_107_MERGE = "2b5873798623c320027b6a2f69c058f45cd0e2a3"


def _is_ancestor(commit: str) -> bool:
    return subprocess.run(
        ["git", "merge-base", "--is-ancestor", commit, "HEAD"], cwd=ROOT,
        check=False, capture_output=True,
    ).returncode == 0


def validate_prerequisites(document: dict[str, Any] | None = None) -> dict[str, Any]:
    """Validate every pinned prerequisite byte and accepted merge ancestry."""
    if document is None:
        document = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if document.get("schema") != "inferswarm.issue109.v5-prerequisite-bindings/1":
        raise MethodologyError("Issue109 prerequisite schema mismatch")
    if document.get("accepted_issue108_merge") != ACCEPTED_108_MERGE:
        raise MethodologyError("wrong accepted #108 merge identity")
    if document.get("historical_issue107_merge") != HISTORICAL_107_MERGE:
        raise MethodologyError("wrong historical #107 merge identity")
    if not _is_ancestor(ACCEPTED_108_MERGE) or not _is_ancestor(HISTORICAL_107_MERGE):
        raise MethodologyError("accepted prerequisite merge is not an ancestor of HEAD")
    bindings = document.get("bindings")
    if not isinstance(bindings, list) or not bindings:
        raise MethodologyError("Issue109 prerequisite bindings are missing")
    names: set[str] = set()
    for row in bindings:
        if not isinstance(row, dict) or set(row) != {"name", "path", "sha256"}:
            raise MethodologyError("Issue109 prerequisite binding shape mismatch")
        name, relative, expected = row["name"], row["path"], row["sha256"]
        path = ROOT / relative
        if not isinstance(name, str) or name in names or not isinstance(relative, str) or not path.is_file():
            raise MethodologyError("Issue109 prerequisite binding path mismatch")
        names.add(name)
        if sha256_file(path) != expected:
            raise MethodologyError(f"Issue109 immutable prerequisite drift: {name}")
    required = {"issue83_semantic_contract", "issue93_adr0011", "issue95_historical_methodology", "issue97_terminal", "issue105_diagnosis", "issue105_retention", "issue105_expungement", "issue108_statistical_contract", "issue108_metric_classification", "issue108_decision", "adr0012"}
    if not required <= names:
        raise MethodologyError("Issue109 prerequisite bindings are incomplete")
    return document


if __name__ == "__main__":
    validate_prerequisites()
