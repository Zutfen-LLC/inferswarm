#!/usr/bin/env python3
"""Frozen semantic task checker for the Issue #280 mechanism experiment.

Issue #284 correction: the #280 rubric was formatting-sensitive (exact JSON
only, no prose/fences). This checker verifies semantic CONTENT — the intended
three fields with exactly the expected values per prompt — while accepting
Markdown fences and brief introductory prose. Deterministic and frozen before
any rerun; never tuned from candidate observations.

Values are frozen from the #280 execution freeze (task_rubric):
  P1: service=payments, severity=high,  status=resolved
  P2: service=search,  severity=low,   status=open
"""
from __future__ import annotations

import json
import re

FIELDS = ("service", "severity", "status")
EXPECTED = {
    "P1": {"service": "payments", "severity": "high", "status": "resolved"},
    "P2": {"service": "search", "severity": "low", "status": "open"},
}
# A JSON object: first '{' to its matching '}' (no nested objects expected in a
# task response; brace balance still guards against truncated output).
_OBJECT_RE = re.compile(r"\{[^{}]*\}")


def _objects(text: str):
    return _OBJECT_RE.findall(text)


def check(prompt: str, text: str):
    """Return (ok, reason). ok=True iff exactly one three-field object with the
    frozen expected values is present. Never raises on malformed text."""
    expected = EXPECTED[prompt]  # unknown prompt is a caller defect: KeyError
    if not isinstance(text, str) or not text.strip():
        return False, "empty response"
    found = _objects(text)
    if not found:
        return False, "no JSON object found in response"
    if len(found) > 1:
        return False, f"ambiguous: {len(found)} JSON objects found"
    try:
        obj = json.loads(found[0])
    except ValueError as exc:
        return False, f"malformed JSON object: {exc}"
    if not isinstance(obj, dict):
        return False, "JSON value is not an object"
    extra = sorted(set(obj) - set(FIELDS))
    if extra:
        return False, f"unexpected extra keys: {extra}"
    missing = sorted(set(FIELDS) - set(obj))
    if missing:
        return False, f"missing fields: {missing}"
    for field in FIELDS:
        value = obj[field]
        if not isinstance(value, str):
            return False, f"field {field} is not a string: {value!r}"
        if value != expected[field]:
            return False, (
                f"field {field} has value {value!r}, expected {expected[field]!r}")
    return True, "semantic values match the frozen rubric"


def main():  # pragma: no cover - manual CLI
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("prompt", choices=sorted(EXPECTED))
    parser.add_argument("response_file")
    args = parser.parse_args()
    ok, reason = check(args.prompt, Path_text(args.response_file))
    print(f"{'ACCEPT' if ok else 'REJECT'}: {reason}")
    return 0 if ok else 1


def Path_text(path):  # pragma: no cover
    from pathlib import Path
    return Path(path).read_text()


if __name__ == "__main__":
    raise SystemExit(main())
