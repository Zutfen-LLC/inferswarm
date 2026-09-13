#!/usr/bin/env python3
"""Issue #157 — accepted-authority binding module (chunk-2 diagnosis).

Immutable pins of the accepted #157 diagnostic authority, plus a
fail-closed verifier the diagnostic drivers run BEFORE any GPU
execution and the conclusions reducer re-runs over retained records.

Authority model (inherited from #137's correction C5): hashes recorded
at run time are OBSERVATIONS, not pins.  A value is a PIN only when
compared against an immutable accepted authority source.  For #157 the
authority sources are:

  * InferSwarm main @ e63209c0a3fd7256f527e7d2a009a688cdd66ca6 (issue
    #157 start; PR #155 merge carrying the accepted #153 terminal
    ISSUE117_ARM_C_REMEDIATION_BLOCKED / BACKEND_REQUIRES_MULTI_CHUNK);
  * FreeToken inferswarm-research @ 55e8baaebabe67aeb967d4bd407ef26696933104
    (accepted research head at authorization; contains the accepted
    #153 candidate source f6133b88d40e4d43d3ac82fa732f21e540b7273d);
  * accepted #137 baseline input digests (frozen in
    scripts/issue137_binding.py from the reviewed PR #138 records and
    re-verified byte-identical on the live nodes at #157 freeze time);
  * the frozen subject (model revision / checkpoint sha256 /
    qualification subject digest) as named by issue #157.

The verifier proves, mechanically, BEFORE any GPU work:

  1. producer checkout: exact commit 55e8baa, clean tree, and the
     on-disk sha256 of every imported execution-path module equals the
     git-blob-derived pin below (misbinding fails before GPU);
  2. interpreter: executing python == the recorded frozen venv python;
  3. torch/CUDA numerical-mode flags == the accepted #137 baseline
     snapshot (a silently changed numerical mode fails closed);
  4. accepted baseline inputs (fixture / environment / chain-plan /
     accepted direct-run) byte-identical to accepted digests;
  5. GPU geometry: inferswarm01 gpu-0/gpu-1 and inferswarm03 gpu-0
     UUIDs match the accepted frozen topology.

CPU-only, stdlib-only.  Every check emits a named condition; failures
raise BindError BEFORE any execution path can proceed.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

BINDER_SCHEMA = "inferswarm.issue157.binding/1"

# -- accepted identities (issue #157 authorization) ---------------------
INFERSWARM_MAIN = "e63209c0a3fd7256f527e7d2a009a688cdd66ca6"
FREETOKEN_RESEARCH_HEAD = "55e8baaebabe67aeb967d4bd407ef26696933104"
ACCEPTED_153_CANDIDATE = "f6133b88d40e4d43d3ac82fa732f21e540b7273d"
PR136_MERGE = "1b83bcab0a5e682a438ca0554f71dd0ace15be55"      # #133 terminal
PR138_MERGE = "cdc23d0e8fa9d3b1b27bab5749939a5ad69b9610"      # #137 terminal
PR155_MERGE = "e63209c0a3fd7256f527e7d2a009a688cdd66ca6"      # #153 terminal

# -- frozen subject (issue #157 text; no substitution) ------------------
SUBJECT = {
    "model": "google/gemma-4-12B-it",
    "revision": "707f0a3b8a3c7ad586ed01e27eafbad8a27dd0f7",
    "checkpoint_sha256": (
        "5a84cb313260ac447237b890387116dfa8682e49a6b44bc585ae8353abbff18d"
    ),
    "qualification_subject": (
        "sha256:c6b9fe721103fb041be3a5b980e73ee148f2304c8572bc50e971f7f1d7994ffd"
    ),
}

GEOMETRY = {
    "inferswarm01": [
        "GPU-1fc28f83-1d45-926e-54d0-ba1e835ef099",   # gpu-0, stage 1 [0,16)
        "GPU-d5c05739-96c1-7e49-89b6-bf54c2121c55",   # gpu-1, stage 2 [16,32)
    ],
    "inferswarm03": [
        "GPU-e1f2f90c-49ab-2689-0cf1-e5d9da520176",   # gpu-0, stage 3 [32,48)
    ],
}

# -- accepted #137 baseline input bytes (re-verified at #157 freeze) ----
BASELINE_INPUT_SHA256 = {
    "prompt-fixture.json": (
        "e68dfaafe661f2f6cc5f5be3a51128c7e7abf0b5c81978cbdb45e9788fd88cd0"
    ),
    "environment.json": (
        "98c04387215915acf54a9ff769492e3f7cb7b0266d36649631a531a9b5edbf67"
    ),
    "chain-plan.json": (
        "6d9a4859af5b686a321458fe50c86189244b7d0d41e2cbb0df28147552f709ab"
    ),
    "direct-run.json": (
        "08807407784be47e40b5051e4de152a42c8248b81e6ee70ae253c7a3ca623ebf"
    ),
}

# -- frozen diagnostic producer modules ---------------------------------
# On-disk sha256 of every execution-path module the #157 diagnostic
# imports, derived from git blobs at 55e8baa (never from a mutable
# working tree).  The producer is the ACCEPTED research head VERBATIM —
# the #157 diagnostic adds ZERO FreeToken source changes; all
# instrumentation is external (driver-side monkeypatching at explicit
# diagnostic entrypoints only).
PRODUCER_MODULE_SHA256 = {
    "benchmarks/inferswarm_r6/stage_chain.py": (
        "42950431177783699bb6f677155925784970b08d7ddf6c8ea6486952477e8983"
    ),
    "benchmarks/inferswarm_r6/wire_client.py": (
        "84390972b0ad109e334516d4d772518afc3de1c8e1df3bf70136a99a2155f3ed"
    ),
    "benchmarks/inferswarm_r6/stage_runtime.py": (
        "1cca03969a14d5b3d9b150a7972fa9bb2bee5a693073d603fb46e9af897f8737"
    ),
    "benchmarks/inferswarm_r6/chain_runtime.py": (
        "9652ebb376b3737d559e6f764b47dfe154e31d1804e9eac62825badb4b3d9980"
    ),
    "benchmarks/inferswarm_r6/last_stage_service.py": (
        "273c22187734ef674de25144fb9484fa965e5423e78de5d660dfb7481f3ff6b2"
    ),
    "benchmarks/inferswarm_r6_localization/capture.py": (
        "369fe8e61c2c37bd3e5b0376e2569befce6eb212960bf3e8a37515b3438d1051"
    ),
    "python/freetoken/research/r4_wire.py": (
        "491f710efc07119441a98642f8569d18a47bc3b4e785fbe7111cea258ab05e2c"
    ),
    # execution-path modules exercised by chunk-2 (route split + kernels)
    "python/freetoken/attention/triton.py": (
        "9d394c50d274ac9ae2e852b6558db8b668c4a00ac5f5627f7558676716998740"
    ),
    "python/freetoken/kernel/triton/attention.py": (
        "d5f49f3fe0218b43bd5244c48047f2196dccd282fdf33ef32c209a1b66467ae5"
    ),
    "python/freetoken/models/gemma4/attention.py": (
        "80609719d11f721595045858fb5827bc98aee415f056bd008f57978b2e1cece2"
    ),
    "python/freetoken/models/gemma4/model.py": (
        "c5f0ad68d32338e215ca3e9ca5d0d1675c8e3a6e1c10c12646765a43ec1da69b"
    ),
    "python/freetoken/core.py": (
        "ec25770fa6c74d0198e8e6ce3b94391074f94b51a410a28edd1ecf8f0dd0578f"
    ),
    "benchmarks/inferswarm_r6/strategy.py": (
        "ca31f0999cb4fcf46d73c83f8b3ee7bbe2636792bcfc1824b15946aaac53906b"
    ),
    "python/freetoken/research/prefill_partition.py": (
        "841635bd42e2bf25954e3fbe6ec902fb79f3d33cca1a4f5b1e8a51383ab73c86"
    ),
}

# -- accepted execution-environment snapshot (unchanged from #137) ------
BASELINE_SOFTWARE = {
    "python": "3.12.13",
    "torch": "2.11.0+cu130",
    "cuda_runtime": "13.0",
    "driver": "610.57.04",
    "multiprocessing_start_method_default": "fork",
}

# -- frozen diagnostic corpus (bound before physical execution) ---------
# Anchor A: mandated by issue #157 (in-session-variable family; the only
# case with retained #137 D/D2 layer evidence: first chunk stable,
# embedding stable, earliest captured variance after layer 0 / at or
# before global layer 1).
ANCHOR_A = "c109-04-02-047"
# Anchor B: bound from accepted #137 per-case causal families —
# session-stable-within-session but cross-session-different family
# (in_session_values all 107; matches no accepted value; cross-campaign
# all-four-distinct).  Position-0 divergence (the chunk-2 prefill call
# itself), same as Anchor A, distinct remainder (66 = 64+2 vs 67 = 64+3).
ANCHOR_B = "c109-04-06-074"
# Stable control: the exact stable control identity from accepted #137
# probe C2 (bound from the retained i137-diag-C2 record's case field and
# its deterministic single-chunk arm), never re-selected.
STABLE_CONTROL = "c109-03-04-003"

# First-divergent positions and prompt lengths from the accepted #137
# phase-1 inventory (sha 369b2c81…; never re-typed by hand from prose).
ACCEPTED_FIRST_DIVERGENT = {
    "c109-04-01-026": 4,
    "c109-04-02-047": 0,
    "c109-04-03-040": 2,
    "c109-04-04-024": 3,
    "c109-04-05-047": 0,   # guard: typo detector — real key is -043
    "c109-04-05-043": 0,
    "c109-04-06-074": 0,
}

# Chunk-2 partition facts under the remediated 64-row policy
# (accepted #153: 65-67-row units REQUIRED to partition 64 + remainder).
PREFILL_CHUNK = 64
ANCHOR_PARTITION = {
    ANCHOR_A: {"prompt_len": 67, "chunks": [64, 3]},
    ANCHOR_B: {"prompt_len": 66, "chunks": [64, 2]},
    STABLE_CONTROL: {"prompt_len": 53, "chunks": [53]},
}


class BindError(RuntimeError):
    """Raised when a pinned identity fails closed before GPU work."""


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def verify_producer_checkout(repo: Path) -> dict:
    """Exact commit + clean tree + per-module on-disk sha256 pins."""
    repo = Path(repo).resolve()
    conditions = {}

    def git(*args: str) -> str:
        return subprocess.check_output(
            ["git", "-c", f"safe.directory={repo}", "-C", str(repo), *args],
            text=True,
        ).strip()

    head = git("rev-parse", "HEAD")
    if head != FREETOKEN_RESEARCH_HEAD:
        raise BindError(
            f"producer HEAD {head!r} != frozen {FREETOKEN_RESEARCH_HEAD!r}"
        )
    conditions["producer_commit"] = head

    status = git("status", "--porcelain")
    if status:
        raise BindError(f"producer tree not clean:\n{status}")
    conditions["producer_tree_clean"] = True

    modules = {}
    for rel, pin in sorted(PRODUCER_MODULE_SHA256.items()):
        path = repo / rel
        if not path.is_file():
            raise BindError(f"pinned module missing: {rel}")
        observed = sha256_file(path)
        if observed != pin:
            raise BindError(
                f"module drift {rel}: on-disk {observed} != pin {pin}"
            )
        modules[rel] = observed
    conditions["producer_modules_pinned"] = len(modules)
    return {"producer": head, "modules": modules, "conditions": conditions}


def verify_baseline_inputs(mapping: dict[str, Path]) -> dict[str, str]:
    observed = {}
    for name, pin in sorted(BASELINE_INPUT_SHA256.items()):
        path = mapping.get(name)
        if path is None:
            raise BindError(f"baseline input not provided: {name}")
        path = Path(path)
        if not path.is_file():
            raise BindError(f"baseline input missing: {path}")
        digest = sha256_file(path)
        if digest != pin:
            raise BindError(
                f"baseline input drift {name}: {digest} != pin {pin}"
            )
        observed[name] = digest
    return observed


def verify_software(snapshot: dict, *, interpreter_path: str) -> None:
    if Path(interpreter_path).resolve() != Path(
        "/srv/inferswarm/repos/FreeToken/.venv/bin/python"
    ):
        raise BindError(
            f"interpreter {interpreter_path!r} is not the frozen venv python"
        )
    for key, expected in BASELINE_SOFTWARE.items():
        flag_key = key.replace("multiprocessing_start_method_default",
                               "mp_start_method")
        observed = snapshot.get(flag_key, snapshot.get(key))
        if observed != expected:
            raise BindError(
                f"software drift {key}: {observed!r} != {expected!r}"
            )


def verify_geometry(observed: dict[str, list[str]]) -> None:
    for host, expected in GEOMETRY.items():
        got = [u.strip() for u in observed.get(host, [])]
        if got != expected:
            raise BindError(f"geometry drift {host}: {got} != {expected}")


def verify_checkpoint(path: Path) -> str:
    digest = sha256_file(path)
    if digest != SUBJECT["checkpoint_sha256"]:
        raise BindError(
            f"checkpoint drift: {digest} != frozen subject sha256"
        )
    return digest


# Self-check: the typo-guard key must never be consumed as a real case.
assert "c109-04-05-047" not in {
    ANCHOR_A, ANCHOR_B, STABLE_CONTROL,
}, "typo-guard key collides with a bound identity"


def load_json_pinned(path: Path) -> tuple[dict, str]:
    digest = sha256_file(path)
    return json.loads(path.read_text()), digest
