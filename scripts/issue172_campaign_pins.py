#!/usr/bin/env python3
"""Issue #172 — Arm-C physical requalification campaign constants (stdlib).

Frozen BEFORE any correctness-bearing execution. Everything the campaign
pins lives here exactly once; scripts import, never restate.

Authority: InferSwarm issue #172 (AGENT-READY physical successor to the
accepted #166 SWA remediation and #170 long-remainder corpus freeze).

No GPU, no model execution, no h109-* material. This module never
imports transformers or torch.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

#: ------------------------------------------------------------------
#: Campaign identity (fresh, bound to this issue)
#: ------------------------------------------------------------------
ISSUE = "https://github.com/Zutfen-LLC/inferswarm/issues/172"
CAMPAIGN_ID = "issue172-arm-c-requalification-v1"
PHYSICAL_AUTHORIZATION_ID = (
    "physical-authorization-issue172-inferswarm-bce7fb3d-freetoken-6202eeeb")

#: terminal classifications mandated by issue #172
PASS_TERMINAL = "ISSUE117_ARM_C_ORDINARY_SERVING_PASS"
FAIL_TERMINAL = "ISSUE117_ARM_C_ORDINARY_SERVING_FAIL"
BLOCKED_TERMINAL = "ISSUE117_ARM_C_REQUALIFICATION_EVIDENCE_BLOCKED"

#: ------------------------------------------------------------------
#: Accepted starting heads named by issue #172 (consume, never restate)
#: ------------------------------------------------------------------
INFERSWARM_MAIN_172 = "bce7fb3d8e54429972472933be66433b81ebcf8f"
FREETOKEN_RESEARCH_172 = (
    "6202eeebcdf63e7bc8bb3498dd3c364ae42ee469")
FREETOKEN_166_IMPLEMENTATION = (
    "64a37a1f1a2797a190610c5adcdcb4157bce63b9")

#: the accepted #168 execution-delta audit bound stage_runtime.py at the
#: #166 implementation head; the accepted research merge 6202eeeb carries
#: the identical bytes (verified by the authority builder)
STAGE_RUNTIME_SHA256_AT_166 = (
    "afe9ceb09208174d0da2905d4097009460d05bbe5050b0d15eaa2baa4e40ac73")
STAGE_RUNTIME_REL = "benchmarks/inferswarm_r6/stage_runtime.py"

#: ------------------------------------------------------------------
#: Frozen subject / topology (issue #172 "Frozen subject / topology")
#: ------------------------------------------------------------------
SUBJECT = {
    "model": "google/gemma-4-12B-it",
    "revision": "707f0a3b8a3c7ad586ed01e27eafbad8a27dd0f7",
    "checkpoint_sha256": (
        "5a84cb313260ac447237b890387116dfa8682e49a6b44bc585ae8353abbff18d"),
    "qualification_subject": (
        "sha256:c6b9fe721103fb041be3a5b980e73ee148f2304c8572bc50e971f"
        "1d7994ffd"),
    "candidate": "dense.6171f32b4413",
    "geometry": (
        "inferswarm01/gpu-0 [0,16)\ninferswarm01/gpu-1 [16,32)\n"
        "inferswarm03/gpu-0 [32,48)"),
    "prefill_boundary_rows": 64,
}

#: accepted plan/participant identities (same literals the accepted
#: #133 driver pins; plan-digest families deliberately distinct)
ARM_B_PARTICIPANT_PLAN_DIGEST = (
    "sha256:8646e00ce53e3aac4c163ca35231fa82471815386d71266a0d0962eea565bdad")
AUTHORIZED_CHAIN_PLAN_DIGEST = (
    "sha256:a71a3129b8764d7108f51ed30fb230b42fcd69646a20bcd6806b6ee53b9bc51f")
AUTHORIZED_PARTICIPANT_IDENTITY = (
    "sha256:ee845188d3328bdec29bf4b09d71f7ccda0701ff5758cb1d8a70460a40fecfb1")
AUTHORIZED_R5A_STATIC_PLAN_DIGEST = (
    "sha256:a730405dab8bad2ee8c4eea9a4fb97b8ef53ea15415a4d904bf666d020cdc625")
#: the fence THIS campaign's physical run actually used, re-derived by the
#: real-builder CPU dry run under producer 6202eee (retained in
#: evidence/r5a-static-plan.json and recorded as plan_digest in every run)
REQUALIFIED_R5A_STATIC_PLAN_DIGEST = (
    "sha256:208be7956474a559756355c85142eb6716585f4c0320a27fe73d2f4196972c3e")
#: accepted Issue #168 authority record, consumed for the delta comparison
ISSUE168_AUTHORITY_RECORD = (
    "docs/implementation/r6-successor-arm-c-requal-blocked-168/evidence/"
    "authority-record.json")
AUTHORIZED_ENVIRONMENT_CANONICAL_SHA256 = (
    "98c04387215915acf54a9ff769492e3f7cb7b0266d36649631a531a9b5edbf67")

#: frozen deployed input bytes (accepted #133 deployment, re-consumed)
AUTHORIZED_INPUT_FILE_SHA256 = {
    "chain_plan": "6d9a4859af5b686a321458fe50c86189244b7d0d41e2cbb0df28147552f709ab",
    "prompt_fixture": "e68dfaafe661f2f6cc5f5be3a51128c7e7abf0b5c81978cbdb45e9788fd88cd0",
    "integration_fixture": "b9c2bb7f7416b10dcee284aaf9b6c591644292550e1dced70a315c08eba120a3",
    "r5b_epochs": "388678971eb608741bd7dd4ad31a34e2e63c45fd2d0807e01065d077d9202805",
}

#: ------------------------------------------------------------------
#: Immutable 40-case corpus (issue #172 Phase 1)
#: ------------------------------------------------------------------
REGRESSION_ARM_CASE_COUNT = 24
GENERALIZATION_ARM_CASE_COUNT = 16
TOTAL_CASE_COUNT = 40

#: the accepted #133 public Arm-C fixture, consumed by digest (the
#: accepted integration-fixture identity, imported-not-restated via
#: scripts.issue129_arm_c_retry_core.FIXTURE_DIGEST_24)
REGRESSION_FIXTURE_DIGEST_24 = (
    "sha256:180185cd5c6a5dcd77b2c65979bd2c9aef4d1c7ea9fb4850a64f4508b2ba36f2")
REGRESSION_FIXTURE_PATH = (
    "docs/implementation/r6-successor-dense-full-integration-117"
    "/evidence/arm-c-retry/prompt-fixture.json")
INTEGRATION_FIXTURE_PATH = (
    "docs/implementation/r6-successor-dense-full-integration-117"
    "/evidence/integration-fixture.json")

#: the accepted #170 long-remainder corpus, consumed without regeneration
CORPUS_170_PATH = (
    "docs/implementation/r6-successor-arm-c-long-remainder-corpus-170"
    "/evidence/corpus.json")
CORPUS_170_DIGEST = (
    "sha256:8a382df1ae5e7d7330966e65acba58bc02ff5af958f3ef63484cc52747a31c34")

FORBIDDEN_NAMESPACE = "h109-"

#: ------------------------------------------------------------------
#: Phase 5 sentinels (issue #172: exact seven identities)
#: ------------------------------------------------------------------
SENTINEL_HISTORICAL = (
    "c109-04-02-047",   # Anchor A
    "c109-04-06-074",   # Anchor B
    "c109-03-04-003",   # stable control
)
SENTINEL_170 = (
    ("g170-01", "1-8", 1),
    ("g170-05", "9-24", 9),
    ("g170-09", "25-48", 25),
    ("g170-13", "49-64", 49),
)
SENTINEL_REPEATS = 6

#: ------------------------------------------------------------------
#: Comparator contract (#129/#133 corrected semantics, unchanged)
#: ------------------------------------------------------------------
COMMIT_TOKENS = 8
GENERATE_MAX_NEW_TOKENS = 2
SAMPLING_INPUTS = {"temperature": 0.0, "top_k": -1, "top_p": 1.0}
STOPPING_POLICY = {"kind": "length", "committed_tokens": COMMIT_TOKENS}
GENERATE_ARGUMENT_NAMES = (
    "max_new_tokens", "on_token", "prompt_token_ids", "session_id")

#: ------------------------------------------------------------------
#: Deployment layout (fresh additive namespace for this issue)
#: ------------------------------------------------------------------
STATE_ROOT = "/srv/inferswarm/state/arm-c-requal-172"
ATTEMPT_ID = "armc-requal172-physical-1"

#: evidence bundle in this repository
EVIDENCE_DIR = ROOT / (
    "docs/implementation/r6-successor-arm-c-requalification-172/evidence")

AUTHORITY_SCHEMA = "inferswarm.issue172.arm-c-requal-authority/1"
CORPUS_BINDING_SCHEMA = "inferswarm.issue172.arm-c-requal-corpus/1"
