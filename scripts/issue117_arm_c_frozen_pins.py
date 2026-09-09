#!/usr/bin/env python3
"""Issue #117 Arm C — frozen FreeToken invocation-semantics derivation
(retention/derivation only; CPU-only; no physical execution).

Mechanically derives the ordinary-path invocation semantics from the
FROZEN FreeToken producer ``924cd22ea081f6d4ed471016faf01d427fc5b0d2``
bytes retained verbatim under
``evidence/arm-c/frozen-freetoken/924cd22e/`` (three files, each
sha256-pinned below; the pins were generated programmatically from the
retained bytes, never hand-typed):

- ``python/freetoken/research/r5b_epochs.py``
  (``EpochServingController.serve_tokens``): per committed position the
  controller derives ``replay_input`` from the transition strategy
  (prompt + committed tokens), invokes
  ``epoch.runtime.generate(..., prompt_token_ids=replay_input,
  max_new_tokens=2, on_token=capture)`` — with the comment "Commit only
  step zero; step one is explicitly speculative and discarded before
  replay" — commits only the step-0 token, records
  ``speculative_uncommitted_tokens_discarded: 1`` per commit, and loops
  ``while session.committed_position < max_new_tokens``. One runtime
  generate call per committed token, each with a full replay prefill.
- ``benchmarks/inferswarm_r6/coordinator.py`` (the ordinary-path HTTP
  Coordinator): imports ``EpochServingController`` and dispatches the
  ordinary request through ``self.controller.serve_tokens(...)`` —
  i.e. the ordinary arm's generation semantics ARE the controller's
  replay-prefix semantics, not a single-shot generate.
- ``benchmarks/inferswarm_r6/xc_strategy.py``
  (``GemmaTokenBoundaryStrategy.replay_input``): returns
  ``list(session.prompt_token_ids) + list(session.committed_token_ids)``
  — the replay-prefix derivation the controller feeds to every
  per-position generate call.

Every claim above is re-derived from the pinned bytes on each call
(``derive_invocation_semantics``); nothing is trusted from this
docstring. A mutated or missing frozen byte fails closed.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

#: test seam: mirrors the blocker reducer's ARM_C_BLOCKER_REPO override
#: so the mutation suite points BOTH git-identity checks and these
#: frozen-source pins at the scratch repository.
_REPO_OVERRIDE = os.environ.get("ARM_C_BLOCKER_REPO")
if _REPO_OVERRIDE:
    ROOT = Path(_REPO_OVERRIDE)

FROZEN_PRODUCER_SHA = "924cd22ea081f6d4ed471016faf01d427fc5b0d2"

#: relative paths, under evidence/arm-c/frozen-freetoken/924cd22e/
FROZEN_EPOCHS_REL = (
    "docs/implementation/r6-successor-dense-full-integration-117/evidence/arm-c/frozen-freetoken/924cd22e/python/freetoken/"
    "research/r5b_epochs.py")
FROZEN_COORDINATOR_REL = (
    "docs/implementation/r6-successor-dense-full-integration-117/evidence/arm-c/frozen-freetoken/924cd22e/benchmarks/"
    "inferswarm_r6/coordinator.py")
FROZEN_STRATEGY_REL = (
    "docs/implementation/r6-successor-dense-full-integration-117/evidence/arm-c/frozen-freetoken/924cd22e/benchmarks/"
    "inferswarm_r6/xc_strategy.py")

#: sha256 of the retained bytes (programmatic pins; verified per call)
FROZEN_SHA256 = {
    FROZEN_EPOCHS_REL:
        "388678971eb608741bd7dd4ad31a34e2"
        "e63c45fd2d0807e01065d077d9202805",
    FROZEN_COORDINATOR_REL:
        "189548dc4f87f5f40c05f7796a2be7af"
        "0446ea05f95a0cf7bafcd3b79bec5d77",
    FROZEN_STRATEGY_REL:
        "8d33b4b297a20511448ab78909d2f528"
        "eef62c2b7943acae167668ec9ff0f26f",
}

#: test seam: the mutation suite writes {rel: sha256} for the synthetic
#: frozen sources into a JSON file and points this env var at it.
_PINS_OVERRIDE_FILE = os.environ.get("ARM_C_BLOCKER_FROZEN_PINS")


def effective_pins() -> dict[str, str]:
    if _PINS_OVERRIDE_FILE:
        override = json.loads(Path(_PINS_OVERRIDE_FILE).read_text())
        return dict(override)
    return FROZEN_SHA256

#: exact source lines (verbatim) that establish each semantic fact
EPOCHS_LOOP = "while session.committed_position < max_new_tokens:"
EPOCHS_REPLAY_DERIVE = (
    "replay_input = list(self.transition_strategy.replay_input("
    "session=session))")
EPOCHS_REPLAY_ARG = "prompt_token_ids=replay_input,"
EPOCHS_MNT2 = "max_new_tokens=2,"
EPOCHS_STEP_ZERO = "if _step == 0:"
EPOCHS_SPECULATIVE = (
    "speculative_uncommitted_tokens_discarded\": 1,")
EPOCHS_MNT2_COMMENT = (
    "# decode interval. Commit only step zero; step one is")
COORD_IMPORT = (
    "from freetoken.research.r5b_epochs import EpochServingController")
COORD_CALL = "completed = self.controller.serve_tokens("
STRATEGY_REPLAY_INPUT = (
    "return list(session.prompt_token_ids) + list("
    "session.committed_token_ids)")

#: the ordinary per-position generate call must NOT be single-shot
EPOCHS_MNT8 = "max_new_tokens=8,"


class FrozenSourceError(RuntimeError):
    """Fail-closed frozen-source derivation error."""


def _read(rel: str) -> str:
    import hashlib
    path = ROOT / rel
    if not path.is_file():
        raise FrozenSourceError(f"missing frozen FreeToken source: {rel}")
    data = path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    pins = effective_pins()
    if digest != pins[rel]:
        raise FrozenSourceError(
            f"frozen FreeToken source digest drift: {rel} "
            f"{digest} != {pins[rel]}")
    return data.decode()


def derive_invocation_semantics() -> dict:
    """Re-derive both arms' frozen invocation semantics from the pinned
    FreeToken bytes. Raises FrozenSourceError on any drift."""
    epochs = _read(FROZEN_EPOCHS_REL)
    coordinator = _read(FROZEN_COORDINATOR_REL)
    strategy = _read(FROZEN_STRATEGY_REL)

    def line_no(text: str, needle: str, what: str) -> int:
        lines = text.splitlines()
        for index, line in enumerate(lines, 1):
            if needle in line:
                return index
        raise FrozenSourceError(
            f"frozen source does not contain {what}: {needle!r}")

    # ordinary semantics: replay-prefix loop, per-position generate
    facts = {
        "epochs_loop": (EPOCHS_LOOP,
                        line_no(epochs, EPOCHS_LOOP, "commit loop")),
        "epochs_replay_derive": (
            EPOCHS_REPLAY_DERIVE,
            line_no(epochs, EPOCHS_REPLAY_DERIVE, "replay derivation")),
        "epochs_replay_arg": (
            EPOCHS_REPLAY_ARG,
            line_no(epochs, EPOCHS_REPLAY_ARG, "replay generate arg")),
        "epochs_max_new_tokens_2": (
            EPOCHS_MNT2,
            line_no(epochs, EPOCHS_MNT2, "max_new_tokens=2 call")),
        "epochs_step_zero_only": (
            EPOCHS_STEP_ZERO,
            line_no(epochs, EPOCHS_STEP_ZERO, "step-zero capture")),
        "epochs_speculative_discard": (
            EPOCHS_SPECULATIVE,
            line_no(epochs, EPOCHS_SPECULATIVE, "speculative discard")),
        "coordinator_import": (
            COORD_IMPORT,
            line_no(coordinator, COORD_IMPORT, "controller import")),
        "coordinator_calls_serve_tokens": (
            COORD_CALL,
            line_no(coordinator, COORD_CALL, "serve_tokens dispatch")),
        "strategy_replay_input": (
            STRATEGY_REPLAY_INPUT,
            line_no(strategy, STRATEGY_REPLAY_INPUT,
                    "replay-input derivation")),
    }
    # fail-closed: the frozen controller must NOT single-shot generate
    # (the ordinary semantics are the replay loop; if the epochs source
    # ever carried max_new_tokens=8 the ordinary derivation would be a
    # post-hoc fiction)
    if EPOCHS_MNT8 in epochs:
        raise FrozenSourceError(
            "frozen EpochServingController unexpectedly contains a "
            "single-shot max_new_tokens=8 call; ordinary semantics "
            "derivation is inconsistent with the pinned bytes")
    # the speculative-discard comment and the mnt=2 call must be
    # adjacent in the same generate call (semantic coherence of the
    # pinned citation)
    mnt_line = facts["epochs_max_new_tokens_2"][1]
    comment_line = line_no(epochs, EPOCHS_MNT2_COMMENT,
                           "step-zero commit comment")
    if not 0 < mnt_line - comment_line <= 3:
        raise FrozenSourceError(
            "frozen max_new_tokens=2 call is not the commented "
            "commit-only-step-zero call; adjacency check failed")

    return {
        "schema": "inferswarm.issue117.arm-c.invocation-semantics/1",
        "frozen_producer": FROZEN_PRODUCER_SHA,
        "pinned_sources": {
            rel: {"sha256": v} for rel, v in effective_pins().items()
        },
        "direct": {
            "invocation": "single-shot",
            "runtime_generate_calls_per_case": 1,
            "max_new_tokens": 8,
            "prefill": "case prompt only, once per case",
            "derivation": (
                "METHODOLOGY-ARM-C §4 frozen at 5e2c83a and the frozen "
                "direct driver at 5e2c83a: one generate(session_id=i, "
                "prompt_token_ids=<rendered ids>, max_new_tokens=8) per "
                "case (pinned by the blocker reducer from git)"),
        },
        "ordinary": {
            "invocation": "replay-prefix per-token commit loop",
            "runtime_generate_calls_per_case": 8,
            "max_new_tokens": 2,
            "prefill": (
                "full replay prefix (prompt + committed tokens) "
                "re-fed on every per-position call"),
            "commit": "step/token zero only",
            "speculative_second_token": "discarded before replay",
            "citations": {k: {"line": v[1], "text": v[0]}
                          for k, v in facts.items()},
            "derivation": (
                "EpochServingController.serve_tokens (r5b_epochs.py @ "
                "924cd22e, sha256-pinned) loops per committed position: "
                "replay_input = strategy.replay_input(session) (= "
                "prompt + committed ids, xc_strategy.py @ 924cd22e), "
                "generate(prompt_token_ids=replay_input, "
                "max_new_tokens=2), commit step zero, discard the "
                "speculative second token; the ordinary HTTP "
                "Coordinator (inferswarm_r6/coordinator.py @ 924cd22e) "
                "dispatches /v1/chat/completions through exactly this "
                "controller.serve_tokens call"),
        },
        "semantics_equal": False,
        "objective_mismatch": (
            "the two arms differ in runtime invocation semantics, not "
            "only in control-plane routing: single-shot "
            "max_new_tokens=8 with one prefill per case vs a "
            "replay-prefix per-position loop of max_new_tokens=2 calls "
            "each committing only the first of two speculative tokens"),
    }
