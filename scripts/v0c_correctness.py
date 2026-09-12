#!/usr/bin/env python3
"""Reduce the frozen V0-C CLI transcript to its byte-exact assistant reply."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


class CorrectnessError(RuntimeError):
    """The frozen terminal grammar cannot uniquely isolate the response."""


def _once(haystack: bytes, needle: bytes, name: str) -> int:
    positions: list[int] = []
    offset = 0
    while True:
        found = haystack.find(needle, offset)
        if found < 0:
            break
        positions.append(found)
        offset = found + 1
    if len(positions) != 1:
        raise CorrectnessError(f"missing or ambiguous {name} marker")
    return positions[0]


def extract_visible_response(transcript: bytes, prompt: bytes) -> bytes:
    """Extract only the reply delimited by the frozen prompt/timing grammar."""
    if not isinstance(transcript, bytes) or not isinstance(prompt, bytes) or not prompt:
        raise CorrectnessError("transcript and frozen prompt bytes are required")
    prompt_line = b"> " + prompt + b"\n"
    prompt_index = _once(transcript, prompt_line, "prompt")
    response_start = prompt_index + len(prompt_line)
    timing_index = _once(transcript[response_start:], b"\n[ Prompt:", "timing") + response_start
    response_with_delimiter = transcript[response_start:timing_index]
    if not response_with_delimiter.endswith(b"\n"):
        raise CorrectnessError("missing response/timing delimiter newline")
    response = response_with_delimiter[:-1]
    if response.endswith(b"\n"):
        response = response[:-1]
    if not response:
        raise CorrectnessError("empty visible response")
    return response


def reduce(transcript: bytes, prompt: bytes, reference: bytes) -> dict[str, Any]:
    visible = extract_visible_response(transcript, prompt)
    return {
        "schema": "inferswarm.v0c.correctness-result/2",
        "visible_response_bytes": visible,
        "visible_response_sha256": hashlib.sha256(visible).hexdigest(),
        "reference_sha256": hashlib.sha256(reference).hexdigest(),
        "byte_exact_visible_output": visible == reference,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stdout", type=Path, required=True)
    parser.add_argument("--prompt", type=Path, required=True)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = reduce(args.stdout.read_bytes(), args.prompt.read_bytes(), args.reference.read_bytes())
        result["visible_response_utf8"] = result.pop("visible_response_bytes").decode("utf-8")
        args.out.write_bytes(json.dumps(result, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8") + b"\n")
    except (OSError, UnicodeDecodeError, CorrectnessError) as error:
        raise SystemExit(f"V0-C correctness error: {error}") from error
    return 0 if result["byte_exact_visible_output"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
