#!/usr/bin/env python3
"""Issue #172 — direct comparator loop (CPU preflight variant).

The accepted #129 corrected direct loop, factored for reuse over the
40-case campaign fixture: per committed position, replay input =
rendered prompt ids + already committed ids; runtime session id from
the frozen AST-extracted allocator; max_new_tokens=2; commit step zero;
discard step one; stop at 8 committed tokens.

This module is shared by the CPU preflight (RecordingRuntime) and is
semantics-pinned by tests; the physical driver embeds the same loop
against the real integrated substrate.
"""
from __future__ import annotations

from typing import Any

import issue172_campaign_pins as P  # noqa: F401

import sys as _sys
_sys.path.insert(0, str(P.ROOT / "scripts"))
import issue129_arm_c_retry_core as _core

_public_calls = _core._public_calls


def run_direct_loop(*, allocator, runtime, fixture: dict[str, Any]) -> dict:
    per_case: dict[str, Any] = {}
    sink = runtime.sink

    def _direct_on_token(step: int, token: int, boundary) -> None:
        # commit only step zero; the speculative step-1 token is discarded
        # (the ordinary controller's capture contract, independently coded)
        del step, token, boundary

    for case in sorted(fixture["cases"], key=lambda c: c["session_index"]):
        case_id = case["case_id"]
        rendered = list(case["rendered_prompt_token_ids"])
        committed: list[int] = []
        mark = len(sink)
        while len(committed) < 8:
            replay = list(rendered) + committed
            result = runtime.generate(
                session_id=allocator.allocate(case["session_index"]),
                prompt_token_ids=replay,
                max_new_tokens=2,
                on_token=_direct_on_token)
            tokens = list(result["generated_token_ids"])
            if not tokens:
                break  # unresolvable stream: reducer fails closed
            committed.append(tokens[0])
        per_case[case_id] = {
            "case_id": case_id,
            "logical_session_id": case["session_index"],
            "completed_token_ids": committed,
            "committed_count": len(committed),
            "committed_epoch_ids": None,
            "committed_plan_digests": None,
            "calls": _public_calls(sink[mark:], case_id),
        }
    return per_case
