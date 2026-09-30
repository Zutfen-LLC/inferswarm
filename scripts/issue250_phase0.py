#!/usr/bin/env python3
"""Issue #250 (R8-I3B) — Phase-0 OFFLINE source/runtime reconstruction.

Option-1 follow-up to the accepted Issue #248 terminal
R8I3_REF_NONDETERMINISM_UNRESOLVED (result head a2cf9f33d1a056f2eef062b4186c078262e66f63
on merged PR #249; main authority bc71774dc68e7d7fddaf97bd794bbbc297e66ca5).

Nothing in this module reinterprets #241/#248 accepted evidence, changes
comparator/2 methodology, or executes any physical probe. Every fact
below is derived from (a) the pinned llama.cpp source tree
b29c606e28a01b1bc8c1351026a0fae616bf6c4 (verified == inferswarm01:~/llama.cpp
HEAD, full clone), (b) the three accepted binary builds, (c) the accepted
#248 retained evidence root, and (d) live read-only host observations
(identity/topology only; no GPU compute, no model reads beyond metadata).

Machine-derived outputs (committed):
  docs/investigations/qwen38-flash-next-r8-i3b-ref-runtime-boundary/
      evidence/phase0/phase0-analysis.json      (deterministic re-run)

Phase-0 question set (Issue #250 §Phase 0 items 3–7):
  R1  prompt ingestion path (server slotting, cache_prompt=false reset
      semantics, batch/ubatch geometry);
  R2  first generation step (decision-0 row provenance: last prompt
      ubatch vs first eval decode);
  R3  threadpool / batch-thread selection (OpenMP build, 14-thread
      default, per-op work distribution, SSM-scan head partitioning);
  R4  CPU kernels used when layers are not offloaded (IQ1_S panel GEMM
      via iqp.cpp, quantized activation conversion, barrier/chunk
      claiming semantics);
  R5  Vulkan participation at ngl=1 (i_gpu_start arithmetic: the single
      offloaded layer IS the output layer at every tested rung);
  R6  process-initialization state relevant to fresh-process
      reproducibility (backend registry enumeration, warmup decode,
      sampler RNG reset, threadpool creation order).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

# --- accepted authority bindings (read-only constants) --------------------
ACCEPTED_MAIN_HEAD = "bc71774dc68e7d7fddaf97bd794bbbc297e66ca5"
ACCEPTED_248_RESULT_HEAD = (
    "a2cf9f33d1a056f2eef062b4186c078262e66f63")
ACCEPTED_248_TERMINAL = "R8I3_REF_NONDETERMINISM_UNRESOLVED"
ACCEPTED_248_EVIDENCE_ROOT = "inferswarm01:/home/hermes/is248-campaign/evidence/"
ACCEPTED_248_MANIFEST_SELF_DIGEST = (
    "af9dfd0f08e9d3c4cbeb8fe164f781bc64b488ad4aba23954f5893ac980ab3bc")
ADJUDICATION_COMMENT_ID = "5838156612"
ISSUE = 250
KIND = "R8-I3B"

# llama.cpp pin (Issue #250 §Phase 0 item 3).
LLAMA_PIN = "b29c606e28a01b1bc8c1351026a0fae616bf6c4"
LLAMA_PIN_TREE = "950999fe62b7fe55f44ab5b7394e3c8542f37f12"
# The three accepted builds of that pin (binary sha256, frozen in
# scripts/issue248_diagnostic.py at the accepted #248 result head).
ACCEPTED_BINARIES = {
    "canonical": "21707f2568d80fb781b445cd472588e83501e1cc66dcf10885b286e34c02573e",
    "r8e-obs": "dcee5bcf8d80a7c99f2d71b753afd4c678d51a43154ed83bc2e208cced1b3ab0",
    "comparator": "6f8b56bd44d116cdc691911f8a1131840f5c7a720133c05febe11e467c2636ad",
}

# Frozen facts re-declared from the accepted campaign line (identical
# bytes exist at the accepted heads; cross-verified by tests, never
# imported from unmerged branches).
MODEL_DIR = "/srv/models/qwen38-ud-iq1-s"
FIXTURE_LADDER_REL = (
    "docs/investigations/qwen38-flash-next-r8-b/evidence/reference/"
    "fixture-ladder.json")
FIXTURE_LADDER_SHA256 = (
    "419bde668c7b3cedf823c98ca0a883560a9a501007f9a28bf8d826148ee822db")
N_VOCAB = 248320
DECISIONS = 8

# Model architecture facts (GGUF metadata read at phase 0; read-only,
# first 64 KiB of member 1 — no tensor bytes touched).
MODEL_ARCH_FACTS = {
    "general.architecture": "qwen4exp",
    "qwen4exp.block_count": 48,          # == llama n_layer_all
    "qwen4exp.full_attention_interval": 4,
    "qwen4exp.expert_count": 512,
    "qwen4exp.expert_used_count": 10,
    "qwen4exp.attention.head_count": 24,
    "qwen4exp.attention.head_count_kv": 2,
    "qwen4exp.attention.key_length": 256,
    "qwen4exp.attention.value_length": 256,
    "qwen4exp.attention.indexer.head_count": 4,
    "qwen4exp.attention.indexer.key_length": 128,
    "qwen4exp.attention.indexer.top_k": 2048,
}

# Host facts observed at phase 0 (read-only).
HOST_FACTS = {
    "cpu_model": "Intel(R) Xeon(R) CPU E5-2683 v3 @ 2.00GHz",
    "cpu_logical": 28,
    "cpu_physical_cores": 14,
    "threads_per_core": 2,
    "numa_nodes": 1,
    "default_thread_count": 14,  # std::thread::hardware_concurrency()/2
    "observed_threadpool_init": "n_threads = 14 (retained server logs, all arms/rungs)",
}

class Phase0Error(RuntimeError):
    """Raised when a phase-0 binding is violated."""


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(Path(path).read_bytes())


# ---------------------------------------------------------------------------
# Binding verification (authority first)
# ---------------------------------------------------------------------------

def verify_bindings(repo_root: Path, evidence_root: Path | None = None
                    ) -> dict[str, Any]:
    """Verify the accepted #248/#241 authority is intact at phase 0.

    Runs from committed artifacts only: the retained terminal-reduction
    (committed at the #248 result head and now on main through PR #249)
    must still name the accepted terminal, and the frozen constants here
    must match the committed #248 tooling constants byte-for-byte
    (cross-checked against the merged main tree, not a branch).
    """
    root = Path(repo_root)
    problems: list[str] = []
    facts: dict[str, Any] = {}

    # 1. committed #248 result artifacts on THIS tree (main lineage).
    red = root / ("docs/investigations/qwen38-flash-next-r8-i3a-ref-"
                  "nondeterminism/evidence/physical/terminal-reduction.json")
    if not red.is_file():
        problems.append("committed #248 terminal reduction absent")
    else:
        d = read_json(red)
        if d.get("terminal") != ACCEPTED_248_TERMINAL:
            problems.append(
                f"committed #248 terminal drift: {d.get('terminal')!r}")
        facts["committed_terminal"] = d.get("terminal")
        facts["committed_reduction_complete"] = bool(d.get("complete"))

    # 2. cross-verify frozen binary/ladder constants against the merged
    #    #248 tooling on THIS tree (self-containment rule: no imports).
    diag = root / "scripts/issue248_diagnostic.py"
    if not diag.is_file():
        problems.append("issue248_diagnostic.py absent from main tree")
    else:
        src = diag.read_text()
        for label, digest in ACCEPTED_BINARIES.items():
            if digest not in src:
                problems.append(
                    f"binary digest {label} absent from merged #248 tooling")
        if FIXTURE_LADDER_SHA256 not in src:
            problems.append(
                "fixture ladder digest absent from merged #248 tooling")
    facts["binary_constant_crosscheck"] = "ok" if not problems else "drift"

    # 3. fixture ladder bytes verify against the frozen digest.
    ladder = root / FIXTURE_LADDER_REL
    if not ladder.is_file():
        problems.append("fixture ladder file absent")
    else:
        digest = sha256_bytes(ladder.read_bytes())
        if digest != FIXTURE_LADDER_SHA256:
            problems.append(f"fixture ladder digest drift: {digest}")
        facts["fixture_ladder_sha256"] = digest
        cases = read_json(ladder).get("cases", [])
        facts["ladder_case_lengths"] = {
            c["case_id"]: len(c["prompt_token_ids"]) for c in cases}

    # 4. retained external evidence binding is stated, not re-fetched here
    #    (phase-0 keeps GPU/model work at zero; the campaign driver
    #    re-verifies the external root live before any dispatch).
    facts["accepted_248_evidence_root"] = ACCEPTED_248_EVIDENCE_ROOT
    facts["accepted_248_manifest_self_digest"] = (
        ACCEPTED_248_MANIFEST_SELF_DIGEST)

    return {"ok": not problems, "problems": problems, "facts": facts}


# ---------------------------------------------------------------------------
# Pinned-source reconstruction facts (R1–R6)
# ---------------------------------------------------------------------------
# Each entry: file/line evidence inside the pin tree b29c606e. The
# reconstruction is the committed derivation; the physical driver
# re-verifies the pin head on the node before any unit launches.

RECONSTRUCTION = {
    "R1_prompt_ingestion": {
        "summary": (
            "One llama-server process per unit; n_slots=4 (n_parallel "
            "default), slot chosen by LRU (t_last_used == -1 for every "
            "fresh process, so slot 3 — the last id — wins the <= "
            "comparison). cache_prompt=false forces n_past=0 "
            "(server-context.cpp:3288), keep_first(0), and a full "
            "memory_seq_rm(id, pos_next=0, -1) wipe before decode; the "
            "prompt is re-processed from position 0 every request. "
            "Prefill decode splits at n_batch=512 "
            "(--batch-size), then memory-driven ubatches "
            "(llama-memory-hybrid.cpp init_batch -> split_equal with "
            "unified KV and rollback-tail constraints); retained logs "
            "show non-uniform splits (510/512, 512x5+5+508...) — "
            "geometry is length- AND position-dependent, not fixed."),
        "evidence": [
            "tools/server/server-context.cpp:3288 (n_past=0 when "
            "cache_prompt false)",
            "tools/server/server-context.cpp:3444 (seq_rm id, p0, -1 "
            "truncate beyond pos_next)",
            "tools/server/server-context.cpp:3524-3560 (batch fill loop "
            "bounded by n_batch)",
            "src/llama-memory-hybrid.cpp:67-99 (init_batch split_equal, "
            "unified-KV non-sequential split, rollback-tail grouping)",
            "src/llama-context.cpp:247 (n_ubatch = min(n_batch, "
            "n_ubatch or n_batch))",
        ],
    },
    "R2_first_generation_step": {
        "summary": (
            "Decision-0's full-vocabulary row is produced by the LAST "
            "PROMPT U BATCH, not by a separate first decode: the "
            "comparator hook reads llama_get_logits_ith at the sampled "
            "index after the final prefill decode, i.e. the row the "
            "sampler consumed for token 1. The generation steps d1..d7 "
            "are single-token eval decodes reusing the same graph "
            "(graphs reused = 7 in every retained log). Therefore the "
            "first-row divergence lives in PREFILL-side computation of "
            "the 3077-token prompt at case-3072."),
        "evidence": [
            "node dirty-patch (comparator build) r8g_observe_logits: "
            "reads logits row at sampled index post common_sampler_sample",
            "retained server.log (all case-3072 units): prompt eval "
            "3077 tokens, eval 8 tokens, graphs reused = 7",
        ],
    },
    "R3_threadpool_threads": {
        "summary": (
            "Build uses OpenMP (libggml-cpu links libgomp; GGML_USE_OPENMP "
            "paths). Default threads = hardware_concurrency()/2 = 14 on "
            "the 28-LPU E5-2683 v3 (common.cpp:145 fallback + arg.cpp "
            "--threads default). graph_compute passes n_threads_batch "
            "for batched (prefill) graphs and n_threads for "
            "single-token generation; both default to 14. Per-op work "
            "distribution: MUL_MAT/IQP GEMM threads claim atomic chunks "
            "(completion-order-varying) but write disjoint output rows; "
            "SSM_SCAN partitions heads across threads "
            "(ops.cpp:9771+, ih0=dh*ith), no cross-thread reduction; "
            "barrier per node (OpenMP omp barrier). No thread writes "
            "another thread's output row; the only order-sensitive "
            "shared structure is the per-thread scratch/panel buffers."),
        "evidence": [
            "common/common.cpp:145 (hardware_concurrency()/2 default)",
            "common/arg.cpp:1514-1534 (-t/--threads, -tb/--threads-batch)",
            "src/llama-context.cpp:2497-2510 (batched vs gen thread "
            "selection; set_n_threads fanout to all backends)",
            "ggml/src/ggml-cpu/ggml-cpu.c:1255+ (MUL_MAT chunk claiming, "
            "disjoint row writes)",
            "ggml/src/ggml-cpu/iqp.cpp:1193+ (IQP panel GEMM: per-thread "
            "panels, atomic chunk claim, disjoint groups)",
            "ggml/src/ggml-cpu/ops.cpp:9771+ (SSM_SCAN head partition)",
            "retained logs: 'llama threadpool init, n_threads = 14' in "
            "every unit",
        ],
    },
    "R4_cpu_kernels": {
        "summary": (
            "IQ1_S weights (file_type 24) on CPU go through the IQP "
            "panel-GEMM path (iqp.cpp): per-thread decode panels + "
            "iqp_gemm_8x8_q8_K on q8_K-quantized activations. The "
            "activation quantization splits the K dimension on fixed "
            "block boundaries per thread (ggml-cpu.c:1346-1361), so "
            "each element is converted exactly once; output rows are "
            "disjoint. llamafile sgemm does not apply (quantized "
            "src0). Attention for non-offloaded layers is CPU "
            "flash-attn OFF by default (flash_attn_type AUTO -> off "
            "for this build config), i.e. KQ_matmul + softmax + KQV "
            "on CPU."),
        "evidence": [
            "ggml/src/ggml-cpu/ggml-cpu.c:1327-1370 (src1 -> vec_dot "
            "type conversion, K-block thread partition; IQP dispatch)",
            "ggml/src/ggml-cpu/iqp.cpp:1141-1160, 1193-1252 (panel "
            "build per thread; gemm/gemv over q8_K rows)",
            "GGUF metadata: general.file_type = 24 (IQ1_S family), "
            "quantize imatrix present",
        ],
    },
    "R5_vulkan_at_ngl1": {
        "summary": (
            "Layer arithmetic (llama-model.cpp:1496-1521): n_layer_all "
            "= 48, i_gpu_start = max(48 + 1 - ngl, 0). At ngl=1: "
            "i_gpu_start=48 -> repeating layers 0..47 stay on CPU, and "
            "the OUTPUT layer (dev_output = get_layer_buft_list(48)) is "
            "the ONLY Vulkan-resident compute: the full-vocabulary "
            "projection feeding every decision row runs on the GPU at "
            "EVERY tested rung (ngl 1/2/4/6/8 all offload the output "
            "layer). The input embedding layer is ALWAYS CPU. At ngl=2 "
            "the last repeating block joins the output layer on GPU. "
            "Conclusion: #248's placement-invariance result is "
            "consistent with an output-layer (or its downstream "
            "normalization) origin, and ALSO with CPU-side prefill "
            "divergence upstream of the projection — the GPU is "
            "nevertheless STRUCTURALLY a participant in every row at "
            "every rung, so 'zero-Vulkan' controls are the "
            "discriminating step (Arm A)."),
        "evidence": [
            "src/llama-model.cpp:1496-1497 (i_gpu_start, "
            "act_gpu_layers)",
            "src/llama-model.cpp:1520-1521 (dev_output = "
            "get_layer_buft_list(n_layer_all))",
            "src/llama-model.cpp:1809 (n_gpu = min(n_gpu_layers, "
            "n_layer_all))",
            "GGUF: qwen4exp.block_count = 48",
        ],
    },
    "R6_process_init": {
        "summary": (
            "Per fresh process: backend registry enumerates (dynamic "
            "backend .so scan at first use; VK_ICD_FILENAMES + "
            "GGML_VK_VISIBLE_DEVICES pin the device), threadpools are "
            "constructed (14 threads), a WARMUP decode of BOS/EOS runs "
            "BEFORE any request (params.warmup default true) followed "
            "by memory_clear + sampler RNG reset, and the graph cache "
            "is empty (first graph built per shape). Same-process "
            "repeats with cache_prompt=false reuse the SAME threadpool, "
            "graph cache, and memory buffers; the request-reset seam "
            "(seq_rm all + keep_first(0) + fresh sampler per task) is "
            "the only reset between same-process requests. The warmup "
            "decode writes no logits to the observation seam (hook "
            "reads only at generation positions)."),
        "evidence": [
            "common/common.cpp:1511-1548 (warmup decode + memory clear "
            "+ sampler reset)",
            "ggml/src/ggml-backend-reg.cpp:574+ (dynamic backend load)",
            "tools/server/server-context.cpp:544-560 (release/reset "
            "between tasks)",
            "retained env: VK_ICD_FILENAMES=nvidia_icd.json, "
            "GGML_VK_VISIBLE_DEVICES=0, CUDA_VISIBLE_DEVICES=-1",
        ],
    },
}

# Pinned-build CLI/runtime controls PROVEN from source + binary --help
# (Issue #250 §Phase 0 item 5; nothing imported from current upstream
# docs). Each control cites its provenance.
PINNED_CONTROLS = {
    "cpu_only_zero_layers": {
        "flag": "-ngl 0",
        "provenance": (
            "arg.cpp:2785+ (-ngl N parses numeric); llama-model.cpp:1496 "
            "i_gpu_start = max(48+1-0,0)=49 > 48 -> act_gpu_layers=0; "
            "all layers incl. output on CPU. Vulkan backend STILL "
            "initialized and present in scheduler (device backends "
            "built from model.devices — arg.cpp:2740 -dev list; "
            "llama.cpp:158-301 default GPU enumeration) so op_offload "
            "and KV offload MAY still route host-side ops to GPU."),
        "caveat": (
            "NOT a pure CPU control: with no -dev override, the "
            "Vulkan device remains in model.devices, backend list, and "
            "scheduler; op_offload (default true) can move "
            "WEIGHT-BACKED host ops to GPU even at ngl=0."),
    },
    "cpu_only_no_device": {
        "flag": "-dev none",
        "provenance": (
            "arg.cpp:1122-1124 ('none' -> devices=[nullptr] terminator "
            "only); llama.cpp:160-184 (params.devices list copied, "
            "empty GPU list) -> model.devices empty -> no GPU backend "
            "in context (llama-context.cpp:330-337), scheduler is "
            "CPU-only, op_offload inert (no GPU backend to offload "
            "to), KV stays host-side. TRUE CPU-ONLY execution with "
            "the same binary."),
        "caveat": (
            "Changes process init: Vulkan backend registry still "
            "loads (binary links libggml-vulkan), but no device "
            "backend instance is created."),
    },
    "generation_threads": {
        "flag": "-t N",
        "provenance": "arg.cpp:1514-1520; cparams.n_threads.",
    },
    "batch_threads": {
        "flag": "-tb N",
        "provenance": (
            "arg.cpp:1524-1530; cparams.n_threads_batch (prefill). "
            "Unset -> same as -t."),
    },
    "cpu_affinity_mask": {
        "flag": "-C M / --cpu-mask M (-Cr range; batch variants -Cb/-Crb)",
        "provenance": "arg.cpp:1534-1540, 1578+.",
    },
    "thread_priority_poll": {
        "flag": "--prio N / --poll <0..100> (batch: --prio-batch/--poll-batch)",
        "provenance": "arg.cpp:1571-1576 (poll default 50).",
    },
    "numa": {
        "flag": "--numa isolate|distribute|numactl",
        "provenance": "arg.cpp:2719-2731.",
    },
    "op_offload": {
        "flag": "--no-op-offload",
        "provenance": "arg.cpp:2945-2947; ggml-backend.cpp:970.",
    },
    "kv_offload": {
        "flag": "--no-kv-offload",
        "provenance": "llama-context.cpp:3649 (offload_kqv default true).",
    },
    "warmup": {
        "flag": "--no-warmup",
        "provenance": "common.h:579 (warmup default true).",
    },
    "batch_size": {
        "flag": "-b N / --batch-size N",
        "provenance": "accepted argv: --batch-size 512; n_batch=512.",
    },
    "ubatch_size": {
        "flag": "-u N / --ubatch-size N",
        "provenance": (
            "llama-context.cpp:247: n_ubatch = min(n_batch, n_ubatch "
            "or n_batch). DEFAULT: n_ubatch==0 -> n_batch, i.e. 512 "
            "here. Single-factor thread probes keep -b/-u unchanged."),
    },
    "kv_unified_per_slot": {
        "flag": "--kv-unified-per-slot N",
        "provenance": (
            "server-context.cpp:1215+; retained log kv_unified='true' "
            "(n_parallel>1 default)."),
    },
    "ctx_checkpoints": {
        "flag": "-ctxcp N",
        "provenance": (
            "arg.cpp:1694+; default 32; hybrid memory forces "
            "checkpointing (do_checkpoint true when "
            "COMMON_CONTEXT_SEQ_RM_TYPE_FULL/RS or n_swa>0; qwen4exp "
            "hybrid SSM layers cannot seq_rm partially)."),
    },
    "slot_pinning": {
        "flag": "request field \"id_slot\": 3",
        "provenance": (
            "server-context.cpp:4323 (task.id_slot = json_value "
            "\"id_slot\", -1); get_available_slot honors id_slot "
            "(server-context.cpp:1553). NOT a server CLI flag — a "
            "per-request field. The accepted contract has no id_slot "
            "key, so B-arm same-process repeats must use a SANCTIONED "
            "extension discussed with the maintainer, not a silent "
            "addition (request-contract equality gate rejects extra "
            "keys)."),
    },
    "slot_count": {
        "flag": "-np N / --parallel N",
        "provenance": (
            "arg.cpp (server -np); default 4 in retained logs; slot "
            "geometry identical across fresh processes."),
    },
}

# Hypothesis matrix: mechanisms that could produce fresh-process
# first-row nondeterminism at case-3072 with byte-deterministic
# 256/1024, ranked by consistency with #248 retained evidence, each
# with the SMALLEST discriminating probe (predeclared).
HYPOTHESES = [
    {
        "id": "H1",
        "mechanism": (
            "Vulkan output-layer GEMM nondeterminism (the only GPU "
            "compute at ngl=1; present at every rung) — e.g. driver "
            "scheduling/queue-timing-dependent reduction order in the "
            "full-vocab projection."),
        "consistent_with": [
            "rows differ at every rung (output layer on GPU at all)",
            "case-256/1024 deterministic (same GPU op — argues "
            "AGAINST unless length-dependent)",
            "broad row-wide deltas (projection output scale)",
        ],
        "against": [
            "case-256/1024 byte-deterministic WITH the same output "
            "layer on GPU — H1 requires an additional length "
            "dependence to survive",
        ],
        "smallest_probe": (
            "Arm A2 '-dev none' (CPU-only, zero GPU participation): "
            "if deterministic while ngl>=1 varies, GPU participation "
            "is a necessary boundary (not yet 'Vulkan is the cause'); "
            "if A2 varies, H1 is excluded in favor of CPU-side "
            "mechanisms."),
    },
    {
        "id": "H2",
        "memo": "cpu_prefill_reduction",
        "mechanism": (
            "CPU-side prefill compute nondeterminism: 14-thread "
            "OpenMP execution of the 3077-token prefill produces "
            "different results per process (e.g. via chunk-claim "
            "order interacting with per-thread panel/scratch state, "
            "memory layout, or SSM state layout), despite disjoint "
            "output writes."),
        "consistent_with": [
            "divergence already present in decision-0 row (prefill "
            "product) — R2",
            "length dependence: 3077-token prefill vs 1022/256 — "
            "more chunks, more barrier crossings, longer SSM scans",
            "fresh-process variation (per-process allocator/layout "
            "state) with in-process graph reuse determinism",
        ],
        "against": [
            "disjoint-write thread model gives no obvious "
            "cross-thread float nondeterminism (R3/R4) — a concrete "
            "order-sensitive seam must be identified to keep H2",
        ],
        "smallest_probe": (
            "Arm C '-t 1 -tb 1' single-thread CPU regime at "
            "case-3072: serial CPU execution deterministic => "
            "parallel-order CPU mechanism localized (boundary); "
            "still varies => CPU threading excluded."),
    },
    {
        "id": "H3",
        "mechanism": (
            "Fresh-process initialization variance: per-process "
            "differences (ASLR/mmap layout, thread-stack addresses, "
            "backend registry order, warmup side effects) that alter "
            "numerics of the first real request only at long prompts."),
        "mechanism_short": "fresh_process_init",
        "consistent_with": [
            "every fresh process differs (5/5 pairs at case-3072)",
            "same binary, same argv/env, byte-deterministic short "
            "cases",
        ],
        "against": [
            "why would layout variance matter only above ~3k tokens? "
            "needs a mechanism (e.g. buffer boundary crossing)",
        ],
        "smallest_probe": (
            "Arm B: equivalent same-process repeats (id_slot pinned, "
            "cache_prompt=false proven full reset) vs fresh "
            "processes. Same-process deterministic + fresh varying "
            "=> init is a necessary boundary."),
    },
    {
        "id": "H4",
        "mechanism": (
            "Long-context execution-path transition: some pinned-build "
            "path switches at longer contexts (hybrid-memory ubatch "
            "geometry, checkpoint splitting, indexer top-k selection "
            "over 2048, graph shape/fragmentation) that is "
            "nondeterministic per process."),
        "consistent_with": [
            "256/1024 deterministic, 3072 variable — a threshold "
            "between 1022 and 3077 tokens",
            "log-visible geometry differences (5-token ubatch at "
            "2560; 510/508 splits at case-1024)",
        ],
        "against": [
            "no specific transition yet mapped to a nondeterministic "
            "mechanism; threshold existence not yet demonstrated — "
            "only bracketed",
        ],
        "smallest_probe": (
            "Arm D length ladder (predeclared: 1024, 1536, 2048, "
            "2560, 3072; and 2304=3*768 as a 512-residue variant) "
            "between deterministic case-1024 and variable case-3072, "
            "same fixture derivation rule; locate the earliest "
            "repeatable transition, then map to source path."),
    },
    {
        "id": "H5",
        "mechanism": (
            "Memory-subsystem timing effects on the host (DDR4 "
            "read-timing-dependent quantization via ECC or refresh "
            "interference) — not detected in platform health, purely "
            "speculative."),
        "consistent_with": [],
        "against": [
            "platform identity/health/AER evidence clean (#248 fact "
            "7); byte-deterministic controls on the SAME host CPU "
            "and memory",
        ],
        "smallest_probe": (
            "Excluded by accepted evidence unless A–D all fail; then "
            "report unresolved rather than claim H5."),
    },
]


def derive_phase0(repo_root: Path) -> dict[str, Any]:
    """Produce the committed phase-0 analysis document (deterministic)."""
    bindings = verify_bindings(repo_root)
    ladder = read_json(Path(repo_root) / FIXTURE_LADDER_REL)
    case_lengths = {c["case_id"]: len(c["prompt_token_ids"])
                    for c in ladder["cases"]}

    doc: dict[str, Any] = {
        "schema": "inferswarm.issue250.phase0/1",
        "kind": KIND,
        "issue": ISSUE,
        "authority": {
            "main_head": ACCEPTED_MAIN_HEAD,
            "accepted_248_result_head": ACCEPTED_248_RESULT_HEAD,
            "accepted_248_terminal": ACCEPTED_248_TERMINAL,
            "accepted_248_evidence_root": ACCEPTED_248_EVIDENCE_ROOT,
            "accepted_248_manifest_self_digest":
                ACCEPTED_248_MANIFEST_SELF_DIGEST,
            "adjudication_comment_id": ADJUDICATION_COMMENT_ID,
        },
        "llama_pin": {
            "commit": LLAMA_PIN,
            "tree": LLAMA_PIN_TREE,
            "binaries": dict(ACCEPTED_BINARIES),
            "verify_rule": (
                "physical driver must verify inferswarm01:~/llama.cpp "
                "HEAD == pin and binary sha256 == accepted digests "
                "before any unit"),
        },
        "model_arch": MODEL_ARCH_FACTS,
        "host_facts": HOST_FACTS,
        "bindings": bindings,
        "reconstruction": RECONSTRUCTION,
        "pinned_controls": PINNED_CONTROLS,
        "case_lengths": case_lengths,
        "hypotheses": HYPOTHESES,
        "prohibited": (
            "no comparator/2 methodology change; no tolerance/noise "
            "model; no physical execution before maintainer exact-head "
            "dispatch; no case-4096; no backend substitution as "
            "accepted reference authority"),
    }
    return doc


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo-root", default=".")
    ap.add_argument("--output", required=True)
    args = ap.parse_args()

    doc = derive_phase0(Path(args.repo_root))
    payload = json.dumps(doc, indent=1, sort_keys=True).encode() + b"\n"
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(payload)
    print(f"phase0 analysis written: {out} "
          f"(sha256 {sha256_bytes(payload)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
