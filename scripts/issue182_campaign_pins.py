#!/usr/bin/env python3
"""Issue #182 — Arm-E locality-mutation campaign constants (stdlib, CPU-only).

Frozen BEFORE any correctness-bearing reduction. Everything the Arm-E
campaign pins lives here exactly once; scripts import, never restate.

Authority: InferSwarm issue #182 (AGENT-READY — ARM-E VERIFIED-INVENTORY
LOCALITY MUTATION / PLANNING-ONLY / NO MODEL OR GPU EXECUTION), final
planned Issue #117 integration arm, successor to the accepted #175 Arm-D
warm-restart cache-reuse PASS (PR #181, merge d4d50b20).

Planning-only: read-only physical inventory collection is authorized;
model execution, CUDA initialization for correctness-bearing work, GPU
realization, artifact acquisition/mutation, and new serving output are
prohibited. No h109-* material may be accessed, reconstructed,
generated, or used.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

#: ------------------------------------------------------------------
#: Campaign identity (fresh, bound to this issue)
#: ------------------------------------------------------------------
ISSUE = "https://github.com/Zutfen-LLC/inferswarm/issues/182"
CAMPAIGN_ID = "issue182-arm-e-locality-mutation-v1"
PHYSICAL_AUTHORIZATION_ID = (
    "physical-authorization-issue182-read-only-inventory")

#: terminal classifications mandated by issue #182
PASS_TERMINAL = "ISSUE117_ARM_E_LOCALITY_MUTATION_PASS"
FAIL_TERMINAL = "ISSUE117_ARM_E_LOCALITY_MUTATION_FAIL"
BLOCKED_TERMINAL = "ISSUE117_ARM_E_EVIDENCE_BLOCKED"

#: ------------------------------------------------------------------
#: Accepted starting heads (consume, never restate)
#: ------------------------------------------------------------------
#: current main = the accepted PR #181 Arm-D merge head (issue #182 names
#: it as the required starting point)
INFERSWARM_MAIN_182 = "d4d50b20205e455a195a908ee9d5ea72bc5d8d04"
#: accepted PR #181 merge that closed #175 with the Arm-D PASS terminal
INFERSWARM_MERGE_181 = "d4d50b20205e455a195a908ee9d5ea72bc5d8d04"
#: accepted FreeToken execution producer (retained predecessor identity;
#: NOT executed in this campaign)
FREETOKEN_RESEARCH_182 = "6202eeebcdf63e7bc8bb3498dd3c364ae42ee469"

#: ------------------------------------------------------------------
#: Frozen subject / candidate authority (issue #182 "Frozen subject /
#: candidate authority", consumed verbatim)
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
}

#: accepted Arm-B plan/requirements identities (re-derived from retained
#: bytes at authority build; never trusted from stored documents alone)
ARM_B_PLAN_DIGEST = (
    "sha256:8646e00ce53e3aac4c163ca35231fa82471815386d71266a0d0962eea565bdad")
ARM_B_REQUIREMENTS_DIGEST = (
    "sha256:68ef850a0a15b9aaabd64de0907e9936297ad4471669e5cb2607b7ddf020c817")

#: the accepted V5 qualification authority consumed through the accepted
#: machinery (issue117_accepted_subject / issue117_applicability); the
#: adjudication identity is the terminal file's own bare hex sha256,
#: exactly as the accepted record's authority field carries it
ACCEPTED_ADJUDICATION_SHA256 = (
    "f024f8b3394686ff098459b657ce6dba62d7f190972663e3929ef4a574ab7a70")

#: ------------------------------------------------------------------
#: Retained accepted evidence consumed read-only (byte-bound at
#: authority build; never edited)
#: ------------------------------------------------------------------
EVIDENCE_117 = ROOT / (
    "docs/implementation/r6-successor-dense-full-integration-117/evidence")
ARM_B = EVIDENCE_117 / "arm-b"
ARM_B_REQUIREMENTS = ARM_B / "requirements.json"
ARM_B_PLAN = ARM_B / "execution-plan.json"
#: sequence-1 pre-realization (cold) node inventory snapshots the Arm-B
#: coordinator consumed for planning (both empty of verified objects)
ARM_B_COLD_INVENTORY_01 = ARM_B / "raw/coordinator/inventory-inferswarm01.json"
ARM_B_COLD_INVENTORY_03 = ARM_B / "raw/coordinator/inventory-inferswarm03.json"
#: accepted #117 CPU analog documents loaded/bound by digest
LOCALITY_MUTATION_117 = EVIDENCE_117 / "locality-mutation.json"
LOCALITY_MUTATION_117_REQUIRED_KEYS = (
    "objective", "selected_candidate_id",
    "v5_transition_seconds_cold", "v5_transition_seconds_warm",
    "v5_missing_bytes_cold", "v5_missing_bytes_warm",
    "gate_ledger_unchanged", "all_gates_unchanged", "economics_changed")

EVIDENCE_ARM_D = ROOT / (
    "docs/implementation/r6-successor-arm-d-warm-restart-175/evidence")
ARM_D_AUTHORITY = EVIDENCE_ARM_D / "authority.json"
ARM_D_TERMINAL = EVIDENCE_ARM_D / "terminal-reduction.json"
ARM_D_MANIFEST = EVIDENCE_ARM_D / "MANIFEST.sha256"
#: terminal-window warm cache inventory (post-restart-2, services stopped)
ARM_D_WARM_INVENTORY_01 = EVIDENCE_ARM_D / (
    "physical-execution/inventories/inventory-01-postkill2.json")
ARM_D_WARM_INVENTORY_03 = EVIDENCE_ARM_D / (
    "physical-execution/inventories/inventory-03-postkill2.json")

#: ------------------------------------------------------------------
#: Physical substrate observed (read-only) during Arm E
#: ------------------------------------------------------------------
SUBSTRATE_ROOT = "/srv/inferswarm/materialized/issue117"
CACHE_ROOT = "/srv/inferswarm/cache/issue117"
#: byte-range verified cache inventory root per node (Arm-B layout)
CACHE_OBJECTS_ROOT = "/srv/inferswarm/cache/issue117/objects"
#: the accepted Source descriptor the Arm-B coordinator froze
SOURCE_DESCRIPTOR = {"source_id": "issue117-origin",
                     "endpoint": "file:///srv/models/gemma-r6"}
#: tokenizer deployment assets are not candidate requirements; they are
#: retained as observation-context only
TOKENIZER_DEPLOYMENT = "/srv/inferswarm/tokenizers/gemma-r6-frozen"
MODEL_VIEW_01 = "/srv/inferswarm/state/arm-c/model-view"

#: participant->node binding of the accepted candidate (retained #117
#: execution-plan participants; verified at authority build)
PARTICIPANT_NODES = {
    "dense.6171f32b4413.stage-1": "inferswarm01",
    "dense.6171f32b4413.stage-2": "inferswarm01",
    "dense.6171f32b4413.stage-3": "inferswarm03",
}
OBSERVATION_HOSTS = ("inferswarm01", "inferswarm03")

#: materialized shard pins (accepted Arm-D authority binding, re-verified
#: against live bytes during the fresh observation)
MATERIALIZED_PINS = {
    "inferswarm01": {
        "dense.6171f32b4413.stage-1/armb-participant.safetensors":
            "2e8cf1af3ff64f7d5f800dac72fea2d418ffa81b15c3a90da5fd42542eaa9ed5",
        "dense.6171f32b4413.stage-2/armb-participant.safetensors":
            "85b218060e0242af6fb27a2e988a24a66892511e8067c38ca90280efa3af038d",
    },
    "inferswarm03": {
        "dense.6171f32b4413.stage-3/armb-participant.safetensors":
            "120e9c29173e91419fe1cfd355651bede6bf195f331e9dac2fd682c4420e6036",
    },
}

#: frozen geometry UUIDs (accepted #175 authority). Correction round:
#: the previous hand-copied inferswarm03/gpu-0 UUID had dropped a hex
#: character (39 chars) — masked until now by the fail-open GPU check
#: (P1-1); the hardened OBS-GPU-SET-MISMATCH fence caught it live on
#: 2026-09-14. The builder now verifies these literals byte-for-byte
#: against the accepted Arm-D authority (bind_geometry_uuids), so
#: hand-copy drift fails closed at authority build.
FROZEN_GEOMETRY_UUIDS = {
    "inferswarm01": {
        "0": "GPU-1fc28f83-1d45-926e-54d0-ba1e835ef099",
        "1": "GPU-d5c05739-96c1-7e49-89b6-bf54c2121c55",
    },
    "inferswarm03": {
        "0": "GPU-e1f2f90c-49ab-2689-0cf1-e5d9da520176",
    },
}

#: inferswarm03 gpu-1 is not part of the accepted candidate geometry but
#: IS a frozen GPU of an observation host (accepted Arm-D retained
#: terminal-window observation, inventory-03-postkill2.json); the
#: fail-closed fence must observe it too (P1-1: every frozen GPU).
#: Also verified against the retained Arm-D records by the builder.
FROZEN_HOST_GPU_UUIDS = {
    "inferswarm01": {
        "0": "GPU-1fc28f83-1d45-926e-54d0-ba1e835ef099",
        "1": "GPU-d5c05739-96c1-7e49-89b6-bf54c2121c55",
    },
    "inferswarm03": {
        "0": "GPU-e1f2f90c-49ab-2689-0cf1-e5d9da520176",
        "1": "GPU-a57bd3fb-c072-67ed-166c-ce52cf504ac0",
    },
}

#: ------------------------------------------------------------------
#: Technical capacity planning input (frozen method, evaluated from
#: observation)
#: ------------------------------------------------------------------
#: usable_weight_bytes for each CU = observed total VRAM bytes, minus
#: the frozen reserve headroom the accepted campaigns retained (see
#: authority.json "capacity_reserve"): a 3072 MiB reserve per serving
#: GPU keeps runtime state out of the weight budget, mirroring how the
#: accepted campaigns kept the serving chain resident with ~10 GB
#: weights per 12 GB GPU. The reserve is declared BEFORE observation
#: (this constant); observation supplies only memory.total.
CAPACITY_RESERVE_BYTES = 3072 * 1024 * 1024

#: GPU totals are pinned from the accepted #175 authority inventory
#: (nvidia-smi --query-gpu memory.total) and re-observed live during
#: Phase 3; a drift between the pinned total and the live total is
#: observation drift -> EVIDENCE_BLOCKED (no repair).
PINNED_GPU_TOTAL_BYTES = {
    "inferswarm01/gpu-0": 12288 * 1024 * 1024,
    "inferswarm01/gpu-1": 12288 * 1024 * 1024,
    "inferswarm03/gpu-0": 12288 * 1024 * 1024,
    "inferswarm03/gpu-1": 12288 * 1024 * 1024,
    "inferswarm04/gpu-0": 24576 * 1024 * 1024,
}

#: ------------------------------------------------------------------
#: Path-bandwidth ranking evidence (frozen method)
#: ------------------------------------------------------------------
#: The accepted Arm-B campaign measured local-file Source reads; the
#: pinned per-request transport is retained in the acquisition ledger.
#: The Arm-E planning contract freezes ONE bandwidth figure for the
#: Source path per artifact, derived mechanically from the retained
#: Arm-B acquisition ledger: aggregate acquired bytes / aggregate wall
#: time over all ACQUIRED events per node (declared here as method;
#: evaluated by the authority builder from retained bytes only).
PATH_BANDWIDTH_METHOD = (
    "aggregate ACQUIRED bytes / aggregate wall_time_seconds over the "
    "retained Arm-B acquisition ledger events of the acquiring node")

#: evidence-contract freeze for #103 path evidence (fresh Arm-E
#: identity, distinct from the fixture contract)
PLANNING_EVIDENCE_CONTRACT = {
    "path": {
        "evidence_version": "issue182-evidence-v1",
        "evidence_identity": "arm-e-path-band-v1",
        "applicability_context": {
            "campaign": CAMPAIGN_ID,
            "arm": "locality-mutation-planning-only",
        },
    },
}

#: ------------------------------------------------------------------
#: Normalization convention for inventory comparison
#: ------------------------------------------------------------------
#: Inventories compare on the semantic projection ONLY:
#:   node_id, sequence, verified_objects[].content_digest,
#:   verified_objects[].length, verified_objects[].byte_digest_verified
#: Excluded as non-semantic collection telemetry: collected_utc,
#: source.endpoint path spelling, per-object host paths. A snapshot
#: whose projection changes between arms IS a semantic change.
NORMALIZATION_PROJECTION = (
    "node_id, sequence, sorted (content_digest, length, "
    "byte_digest_verified) triples")

#: stale-inventory rule: a warm snapshot sequence must be >= the cold
#: snapshot sequence for the same node (monotonic inventory epoch)
INVENTORY_SEQUENCE_MONOTONIC = True

#: ------------------------------------------------------------------
#: Observation epoch / freshness identity (review correction P1-2,
#: maintainer comment 5666244858)
#: ------------------------------------------------------------------
#: The fresh observation's inventory sequence is NOT manufactured by
#: the planner adapter. It is a frozen authority constant derived from
#: the retained accepted inventory lineage (Arm-B cold = sequence 1,
#: Arm-B post-acquisition = sequence 2), bound in authority.json
#: BEFORE the observation, embedded in the physical record by the
#: node-side collector only after verifying the staged authority
#: bytes (authority_digest), the frozen attempt id, and the campaign
#: id, and re-verified independently by the comparison and the
#: terminal reducer against the live authority + retained records.
OBSERVATION_SEQUENCE = 3
OBSERVATION_EPOCH_RULE = (
    "fresh observation epoch sequence = retained accepted Arm-B "
    "post-acquisition sequence (2) + 1, strictly later than both the "
    "cold (1) and retained accepted inventory identities; bound to "
    "authority_digest + attempt_id + campaign_id + host inside the "
    "physical record and re-derived at comparison and termination")

#: ------------------------------------------------------------------
#: Fail-closed host-probe contract (review correction P1-1)
#: ------------------------------------------------------------------
#: Every acceptance-bearing probe retains a structured receipt in the
#: observation record: exact command identity, return code,
#: stdout/stderr byte counts + sha256 digests + bounded raw text. A
#: failed probe is OBS-PROBE-FAILED — never an empty observation.
FENCE_PROBE_NAMES = ("ps", "ss", "nvidia-smi")
PROBE_STDOUT_CAP_BYTES = 65536

#: every frozen GPU of an observation host must be observed, its
#: telemetry parseable, and its memory.used within this bound, or the
#: campaign stops (OBS-GPU-SET-MISMATCH / OBS-GPU-TELEMETRY-\
#: UNPARSEABLE / OBS-GPU-NOT-IDLE). The bound derives from the
#: retained Arm-D terminal-window observation (0-1 MiB per idle GPU)
#: with headroom for driver bookkeeping; any CUDA initialization or
#: correctness-bearing GPU work by this campaign is prohibited and
#: would show as memory.used far above it.
GPU_MEMORY_USED_MAX_MIB = 16

#: ------------------------------------------------------------------
#: Accepted verified-cache provenance manifest (review correction P1-3)
#: ------------------------------------------------------------------
#: Sidecar written by the authority builder from the retained accepted
#: Arm-B post-acquisition inventories; the fresh observation's verified
#: object set must EQUAL it (no missing, no extra) and every object
#: must carry matching content-address identity (object name hex ==
#: recomputed bytes digest). Consumed by comparison + terminal with
#: the sidecar sha256 re-verified against the authority binding.
ACCEPTED_CACHE_OBJECTS_SCHEMA = (
    "inferswarm.issue182.arm-e.accepted-cache-objects/1")
ACCEPTED_CACHE_OBJECTS_PATH = ROOT / (
    "docs/implementation/r6-successor-arm-e-locality-mutation-182/"
    "evidence/authority/accepted-cache-objects.json")

#: ------------------------------------------------------------------
#: Attempt state machine / STOP rules (frozen before observation)
#: ------------------------------------------------------------------
#: ATTEMPT arme-182-2: single-pass read-only observation + reduction.
#:   Review correction round (maintainer comment 5666244858): the
#:   arme-182-physical-1 observation lacked mechanically retained
#:   successful-probe receipts and a real observation freshness
#:   identity, and is retained as SUPERSEDED evidence only.
#: STOP rules (any fires -> terminal BLOCKED, no retry, no repair):
#:   OBS-HOST-UNREACHABLE      observation host unreachable
#:   OBS-ROOT-MISSING          a bound cache/materialized root is absent
#:   OBS-CACHE-DIGEST-MISMATCH live byte digest != accepted Arm-D pin
#:   OBS-GPU-TOTAL-DRIFT       live GPU total != pinned authority total
#:   OBS-GPU-SET-MISMATCH      a frozen host GPU not observed (or extra)
#:   OBS-GPU-TELEMETRY-UNPARSEABLE  GPU row not parseable as pinned
#:   OBS-GPU-NOT-IDLE          GPU memory.used above the idle bound
#:   OBS-PROBE-FAILED          an acceptance-bearing host probe (ps /
#:                             ss / nvidia-smi) exited nonzero or is
#:                             missing its receipt (P1-1: a failed
#:                             probe is never an empty observation)
#:   OBS-CONTENT-ADDRESS-MISMATCH  sha256-<hex> object name != recomputed
#:                             content digest (P1-3)
#:   OBS-UNACCEPTED-CACHE-OBJECT   fresh object outside the accepted
#:                             verified-cache provenance manifest
#:   OBS-OBSERVATION-EPOCH-INVALID  freshness identity wrong/stale
#:                             (P1-2: bound epoch, sequence, attempt)
#:   OBS-FORBIDDEN-NAMESPACE-MATERIAL  forbidden-namespace material
#:                             referenced by a retained campaign record
#:   OBS-RECORD-DIGEST-MISMATCH  observation record self-digest does
#:                             not verify (post-hoc tamper; review
#:                             lane B)
#:   OBS-WARM-ARM-BINDING-MISMATCH  the comparison's warm arm is not
#:                             the snapshot bound to the retained
#:                             observation records (review lane A)
#:   OBS-FENCE-DERIVATION-MISMATCH  a derived fence field disagrees
#:                             with its retained receipt stdout
#:                             (review round 3 lane B P1-1)
#:   OBS-MANIFEST-MISMATCH     evidence manifest row does not verify
#:                             against the live evidence bytes
#:   OBS-MUTATION-DETECTED     before/after root digest differs
#:   OBS-PROCESSES-LIVE        execution-bearing process live at fence
ATTEMPT_ID = "arme-182-physical-2"
STOP_RULES = (
    "OBS-HOST-UNREACHABLE",
    "OBS-ROOT-MISSING",
    "OBS-CACHE-DIGEST-MISMATCH",
    "OBS-GPU-TOTAL-DRIFT",
    "OBS-GPU-SET-MISMATCH",
    "OBS-GPU-TELEMETRY-UNPARSEABLE",
    "OBS-GPU-NOT-IDLE",
    "OBS-PROBE-FAILED",
    "OBS-CONTENT-ADDRESS-MISMATCH",
    "OBS-UNACCEPTED-CACHE-OBJECT",
    "OBS-OBSERVATION-EPOCH-INVALID",
    "OBS-FORBIDDEN-NAMESPACE-MATERIAL",
    "OBS-RECORD-DIGEST-MISMATCH",
    "OBS-WARM-ARM-BINDING-MISMATCH",
    "OBS-FENCE-DERIVATION-MISMATCH",
    "OBS-MANIFEST-MISMATCH",
    "OBS-MUTATION-DETECTED",
    "OBS-PROCESSES-LIVE",
)

#: non-claims (issue #182 "Explicit non-claims", verbatim scope)
NON_CLAIMS = (
    "no new model correctness or numerical qualification",
    "no new throughput/performance numbers",
    "no physical transfer-time prediction accuracy",
    "no GPU scheduling quality",
    "no dynamic congestion/queueing behavior",
    "no production failover",
    "no node reboot/cache-loss recovery",
    "no mutable session-cache movement",
    "no public stable planner or locality schema",
)

EVIDENCE_DIR = ROOT / (
    "docs/implementation/r6-successor-arm-e-locality-mutation-182/evidence")

AUTHORITY_SCHEMA = "inferswarm.issue182.arm-e-authority/1"
INVENTORY_SCHEMA = "inferswarm.issue182.arm-e.warm-inventory/1"
FENCE_SCHEMA = "inferswarm.issue182.arm-e.observation-fence/1"
COLD_ARM_SCHEMA = "inferswarm.issue182.arm-e.cold-arm-binding/1"
WARM_ARM_SCHEMA = "inferswarm.issue182.arm-e.warm-arm-binding/1"
COMPARISON_SCHEMA = "inferswarm.issue182.arm-e.two-arm-comparison/1"
TERMINAL_SCHEMA = "inferswarm.issue182.arm-e.terminal-reduction/1"

#: forbidden namespace (never accessed)
FORBIDDEN_NAMESPACE = "h109-"
