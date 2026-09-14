#!/usr/bin/env python3
"""Issue #175 — Arm-D warm-restart campaign constants (stdlib, CPU-only).

Frozen BEFORE any correctness-bearing execution. Everything the Arm-D
campaign pins lives here exactly once; scripts import, never restate.

Authority: InferSwarm issue #175 (AGENT-READY physical Arm D — warm
restart / verified artifact-cache reuse / zero model-weight
reacquisition), successor to the accepted #172 Arm-C ordinary-serving
PASS (PR #174, merge 52c3b560).

No GPU, no model execution, no h109-* material. This module never
imports transformers or torch.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

#: ------------------------------------------------------------------
#: Campaign identity (fresh, bound to this issue)
#: ------------------------------------------------------------------
ISSUE = "https://github.com/Zutfen-LLC/inferswarm/issues/175"
CAMPAIGN_ID = "issue175-arm-d-warm-restart-v1"
PHYSICAL_AUTHORIZATION_ID = (
    "physical-authorization-issue175-inferswarm-246dcca8-freetoken-6202eeeb")

#: terminal classifications mandated by issue #175
PASS_TERMINAL = "ISSUE117_ARM_D_WARM_RESTART_CACHE_REUSE_PASS"
FAIL_TERMINAL = "ISSUE117_ARM_D_WARM_RESTART_CACHE_REUSE_FAIL"
BLOCKED_TERMINAL = "ISSUE117_ARM_D_EVIDENCE_BLOCKED"

#: ------------------------------------------------------------------
#: Accepted starting heads (consume, never restate)
#: ------------------------------------------------------------------
#: the maintainer handoff names current main = the accepted #173 head
INFERSWARM_MAIN_175 = "246dcca809d8af22b3f3e4ae11ec9fd412fbd8dc"
#: accepted PR #174 merge that closed #172 with the Arm-C PASS terminal
INFERSWARM_MERGE_174 = "52c3b560d560f69d0f009ed5772c1a70efc01ba2"
FREETOKEN_RESEARCH_175 = (
    "6202eeebcdf63e7bc8bb3498dd3c364ae42ee469")
FREETOKEN_166_IMPLEMENTATION = (
    "64a37a1f1a2797a190610c5adcdcb4157bce63b9")

#: ------------------------------------------------------------------
#: Frozen subject / topology (issue #175 "Frozen subject / topology")
#: ------------------------------------------------------------------
SUBJECT = {
    "model": "google/gemma-4-12B-it",
    "revision": "707f0a3b8a3c7ad586ed01e27eafbad8a27dd0f7",
    "checkpoint_sha256":
        "5a84cb313260ac447237b890387116dfa8682e49a6b44bc585ae8353abbff18d",
    "qualification_subject":
        "sha256:c6b9fe721103fb041be3a5b980e73ee148f2304c8572bc50e971f"
        "1d7994ffd",
    "candidate": "dense.6171f32b4413",
    "geometry": (
        "inferswarm01/gpu-0 [0,16)\ninferswarm01/gpu-1 [16,32)\n"
        "inferswarm03/gpu-0 [32,48)"),
    "prefill_boundary_rows": 64,
}

FROZEN_GEOMETRY_UUIDS = {
    "inferswarm01": {
        "0": "GPU-1fc28f83-1d45-926e-54d0-ba1e835ef099",
        "1": "GPU-d5c05739-96c1-7e49-89b6-bf54c2121c55",
    },
    "inferswarm03": {
        "0": "GPU-e1f2f90c-49ab-2689-0cf1-e5d9da520176",
    },
}

#: accepted plan identities (all re-derived from retained bytes at
#: authority build; identical semantics to the accepted #172 freeze)
CHAIN_PLAN_172_DIGEST = (
    "sha256:b24c3ca06b3ea79b62fdea8058afe9f71e0c69187b5cd77740cc5855f9796529")
ENVIRONMENT_172_CANONICAL_SHA256 = (
    "sha256:cd0909bb96fc637a921218c973aaa1640579af7093681714cd3216a0dfa5f279")
R5A_STATIC_PLAN_172_DIGEST = (
    "sha256:208be7956474a559756355c85142eb6716585f4c0320a27fe73d2f4196972c3e")
PARTICIPANT_IDENTITY = (
    "sha256:ee845188d3328bdec29bf4b09d71f7ccda0701ff5758cb1d8a70460a40fecfb1")
#: the plan digest a fresh Coordinator must reproduce from the frozen
#: environment + chain plan + accepted serving evidence (both accepted
#: #172 coordinator instances produced exactly this)
COORDINATOR_PLAN_DIGEST_172 = (
    "sha256:14344025ed0d86d8db91664dc19aa03f321e8d8586919f9d6776ad6c76f58bb7")

#: ------------------------------------------------------------------
#: Accepted #172 retained comparison material (Phase 4 authority)
#: ------------------------------------------------------------------
EVIDENCE_172 = ROOT / (
    "docs/implementation/r6-successor-arm-c-requalification-172/evidence")
CORPUS_172_PATH = EVIDENCE_172 / "campaign-corpus.json"
CORPUS_172_FILE_SHA256 = (
    "e49b9c19232c10ec5c06408b890c21c48fbef0a48af68ad6ebf529b6d719e9c7")
SERVING_REPORT_172_CANONICAL = (
    EVIDENCE_172 / "physical-execution/serving-report-canonical.json")
SERVING_REPORT_172_SENTINELS = (
    EVIDENCE_172 / "physical-execution/serving-report-sentinels.json")
ORDINARY_172_CANONICAL = (
    EVIDENCE_172 / "physical-execution/ordinary-canonical/ordinary-campaign.json")
ORDINARY_172_SENTINELS = (
    EVIDENCE_172 / "physical-execution/ordinary-sentinels/ordinary-campaign.json")
DIRECT_172_RUN = EVIDENCE_172 / "physical-execution/direct-run.json"
WARM_RESTART_117 = ROOT / (
    "docs/implementation/r6-successor-dense-full-integration-117/evidence"
    "/warm-restart.json")

#: accepted #117 CPU warm-restart fixture semantics that this campaign
#: turns into a physical proof (loaded/bound by digest, never edited)
WARM_RESTART_117_REQUIRED_KEYS = (
    "per_participant", "warm_restart_model_weight_transfer_bytes",
    "coordinator_bytes_observed", "plan_digest", "witnesses")

#: ------------------------------------------------------------------
#: Node-local verified immutable artifact cache (Phase 0 binding)
#: ------------------------------------------------------------------
SUBSTRATE_ROOT = "/srv/inferswarm/materialized/issue117"
CACHE_ARTIFACTS = {
    "inferswarm01": {
        "dense.6171f32b4413.stage-1/armb-participant.safetensors":
            "2e8cf1af3ff64f7d5f800dac72fea2d418ffa81b15c3a90da5fd42542eaa9ed5",
        "dense.6171f32b4413.stage-2/armb-participant.safetensors":
            "85b218060e0242af6fb27a2e988a24a66862511e8067c38ca90280efa3af038d",
    },
    "inferswarm03": {
        "dense.6171f32b4413.stage-3/armb-participant.safetensors":
            "120e9c29173e91419fe1cfd355651bede6bf195f331e9dac2fd682c4420e6036",
    },
}
#: the 01-side model view the node agent passes to stages 1-2 (config +
#: per-stage symlinked participant shards; symlinks resolve into the
#: cache roots above and are re-verified at inventory time)
MODEL_VIEW_01 = "/srv/inferswarm/state/arm-c/model-view"
MODEL_VIEW_03 = SUBSTRATE_ROOT + "/dense.6171f32b4413.stage-3"
TOKENIZER_DEPLOYMENT = "/srv/inferswarm/tokenizers/gemma-r6-frozen"
TOKENIZER_ASSET_PINS = {
    "chat_template.jinja":
        "ae53464bf3be25802b3a5b37def7fd89667067d7577049b3b2d74c4d8de4c6d4",
    "config.json":
        "478c46e8d2c52d5c2d85bf67e3b3e8c90e7c9d91086cee27e3c267907e936bd9",
    "generation_config.json":
        "a8349d9bd64cc5841297fcb5002f0fdc4749c473c8f1b10ea337f9ce4ee7014e",
    "tokenizer.json":
        "cc8d3a0ce36466ccc1278bf987df5f71db1719b9ca6b4118264f45cb627bfe0f",
    "tokenizer_config.json":
        "a62f4e85a47c0c136edaaa3a4f591fd6783717299a9def47e5ad03a49f6a5eb9",
}
FORBIDDEN_SOURCE_ROOT = "/srv/models/"
FORBIDDEN_NAMESPACE = "h109-"

#: ------------------------------------------------------------------
#: Frozen deployment / restart command authority
#: ------------------------------------------------------------------
#: inputs consumed read-only exactly as retained by the accepted #172
#: campaign (chain plan + environment + serving evidence are the
#: accepted freeze bytes; only NEW Arm-D outputs land under STATE_ROOT)
CHAIN_PLAN_INPUT = "/srv/inferswarm/state/arm-c-requal-172/chain-plan.json"
ENVIRONMENT_INPUT = "/srv/inferswarm/state/arm-c-requal-172/environment.json"
SERVING_EVIDENCE_INPUT = (
    "/srv/inferswarm/state/arm-c-requal-172/serving-evidence.json")
COORDINATOR_REPO = "/srv/inferswarm/repos/FreeToken"
COORDINATOR_PYTHON = "/srv/inferswarm/venv/bin/python"
NODE_REPO = "/home/zutfen/FreeToken"
NODE_PYTHON = "/home/zutfen/FreeToken/.venv/bin/python"
LAST_STAGE_HOST = "10.0.0.219"
LAST_STAGE_PORT = 18485
NODE_AGENT_HOST = "10.0.0.141"
NODE_AGENT_PORT = 18486
COORDINATOR_ORIGIN = "http://10.0.0.206:18080"
SCOPE_ID = "issue117-arm-c"

#: the exact restart commands (run as the owning service user under
#: nohup, detached, with strace -f -e trace=openat,connect bound to the
#: restart window observation; full text frozen in the authority record)
STRACE_PREFIX = ["strace", "-f", "-qq", "-e", "trace=openat,connect"]

STATE_ROOT = "/srv/inferswarm/state/arm-d-175"
ATTEMPT_ID = "armd-175-physical-1"

EVIDENCE_DIR = ROOT / (
    "docs/implementation/r6-successor-arm-d-warm-restart-175/evidence")

#: ------------------------------------------------------------------
#: Prospectively frozen observation plan (declared BEFORE restart #1)
#: ------------------------------------------------------------------
#: pre-restart health sentinel screen (accepted #172 public cases only)
SCREEN_CASES = ("c109-03-04-003", "c109-04-02-047", "g170-01")
#: restart #1: the exact accepted 40-case canonical corpus through the
#: ordinary external-Coordinator path (includes one trailing controlled
#: fencing-arm request, the accepted #172 negative control)
#: restart #2: the exact accepted seven sentinel identities x 6 repeats
#: (the accepted #172 repeatability protocol, verbatim tooling)
SENTINEL_IDS = (
    "c109-04-02-047", "c109-04-06-074", "c109-03-04-003",
    "g170-01", "g170-05", "g170-09", "g170-13",
)
SENTINEL_REPEATS = 6
RESTART_COUNT = 2

#: per-boundary peer-transfer bound: the R4 wire may carry activation
#: (hidden-state) frames only; the accepted #172 canonical run retained
#: activation_bytes_rx/boundaries ratio; any model-weight transfer is
#: ~4 orders of magnitude above this. Formula frozen here, evaluated
#: from retained bytes only.
ACTIVATION_BOUND_FACTOR = 2

#: comparator contract (accepted #129/#133/#172 semantics, unchanged)
COMMIT_TOKENS = 8
SAMPLING_INPUTS = {"temperature": 0.0, "top_k": -1, "top_p": 1.0}

AUTHORITY_SCHEMA = "inferswarm.issue175.arm-d-authority/1"
INVENTORY_SCHEMA = "inferswarm.issue175.arm-d.cache-inventory/1"
FENCE_SCHEMA = "inferswarm.issue175.arm-d.process-fence/1"
ZERO_INVARIANTS_SCHEMA = "inferswarm.issue175.arm-d.zero-invariants/1"
EQUALITY_SCHEMA = "inferswarm.issue175.arm-d.equality-reduction/1"
TERMINAL_SCHEMA = "inferswarm.issue175.arm-d.terminal-reduction/1"
