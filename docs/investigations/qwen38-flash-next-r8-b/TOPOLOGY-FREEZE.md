R8-B topology and residency freeze (Phase 3)
============================================

Frozen: 2026-09-15, BEFORE any distributed candidate correctness output.
Producer: issue-191-r8b-qwen38-rpc-qualification branch; authority module
scripts/issue191_r8b_authority.py.

Runtime (Phase 1 freeze)
------------------------
- llama.cpp b29c606e28a01b1bc8c1351026a0fa6e616bf6c4 (tag v0.4.1), built
  from clean clones on each host at that exact commit.
- Build: cmake -DCMAKE_BUILD_TYPE=Release -DGGML_CUDA=ON
  -DCMAKE_CUDA_ARCHITECTURES=86 -DLLAMA_CURL=OFF -DGGML_RPC=ON,
  CUDA 13.1 (nvcc release 13.1), gcc 14.2.0 (Debian), cmake 3.31.6.
- Binaries (sha256 identical on all three hosts):
  llama-cli    3f6b0ed46f42e5c614e4fb4d36b91c56061dfff96096bbb1e4bc0044bd95e77f
  llama-server de3a8a545e2f5995f80ff23f60776fedc30edca67f0e09f3bc47c845156e3411
  ggml-rpc-server a897f908add3305658e6b4f996880033d07ede0800fff71dbc46e90230acdfe9
- #27960 repair merge 73f56d105bb6b5aeb37d0c7dcc6a7d58c2f7974a verified
  ancestor of the selection (GitHub compare, 2026-09-15); qwen4exp support
  commits 6c84c7d, 36b1015, 09412af, 0eadefe, 6fe7498 all ancestral.
- TENSOR_READ_LAZY treatment at this revision (source-verified):
  qwen4exp.cpp creates per_layer_token_embd.weight with TENSOR_READ_LAZY;
  lazy_read::add() auto-lazy-reads tensors > 4 GiB when mmap is available;
  lazy_read::buft() returns the CPU device buffer type, and buft_for_tensor
  returns the lazy buft BEFORE the -ot override block, so -ot cannot move
  the PLE table off the host. Intended placement (PLE host-side, mmap
  backed, on the model-loading client) is therefore the runtime DEFAULT
  at this revision and is machine-observable in load logs
  ("lazy read enabled ... 27466 MiB" for per_layer_token_embd.weight).

Physical topology (rung 0 — canonical candidate)
------------------------------------------------
Client host: inferswarm01 (10.0.0.141, eno1)
  - CUDA0 0000:02:00.0 GPU-1fc28f83-1d45-926e-54d0-ba1e835ef099 (RTX 3060 12GB)
  - CUDA1 0000:03:00.0 GPU-d5c05739-96c1-7e49-89b6-bf54c2121c55 (RTX 3060 12GB)
  - host RAM 125 GiB; PLE table (26.82 GiB) host-resident here (lazy, mmap)
  - model files at /srv/models/qwen38-ud-iq1-s/ (local SSD sda2)
RPC host 1: inferswarm03 (10.0.0.219, enp5s0)
  - 0000:01:00.0 GPU-e1f2f90c-49ab-2689-0cf1-e5d9da520176 (RTX 3060 12GB)
  - 0000:03:00.0 GPU-a57bd3fb-c072-67ed-166c-ce52cf504ac0 (RTX 3060 12GB)
RPC host 2: inferswarm04 (10.0.0.204, enp3s0)
  - 0000:01:00.0 GPU-ecda1aaa-0c66-857b-8218-3d511dc75c03 (RTX 3090 24GB)
NVIDIA driver 610.57.04 on all three hosts. Network: 1 GbE switched LAN
(10.0.0.0/24), RPC over TCP ports 50052/50053.

Process roles (candidate):
  inferswarm03: 2x ggml-rpc-server --host 0.0.0.0 --port 50052/50053
                (one per GPU; device pinned per server)
  inferswarm04: 1x ggml-rpc-server --host 0.0.0.0 --port 50052
  inferswarm01: llama-server (client) --rpc 10.0.0.219:50052,...  with local
                CUDA0/CUDA1 also in the device pool, PLE lazy host-side.

Split: backbone (~40.74 GiB non-PLE) distributed by the runtime's weighted
layer assignment across all 5 CUDA devices (aggregate 71.6 GiB free-class
capacity); exact observed per-device placement retained from load logs as
evidence. KV/GDN/QSA session state follows its owning layer's device;
single slot, context 4608 tokens per case.

Predeclared capacity-only topology ladder
-----------------------------------------
Advancing is permitted ONLY on a load/initialization failure with ZERO
generated candidate tokens and ONLY for demonstrated static memory
insufficiency. Once any candidate token is generated, topology is frozen.

  rung 0: as above (5 CUDA devices across 3 hosts).
  rung 1: if a single 3060-class RPC endpoint proves insufficient for its
          assigned range, split inferswarm03 into two rpc-server endpoints
          (one per GPU) — same hosts, same devices.
  rung 2: if aggregate is insufficient, reduce per-device load by moving the
          tokenizer/output head to client CPU via -ot (non-PLE tensors only)
          — no host/device change.

Pre-output failed load attempts (retained):
  2026-09-15 smoke on inferswarm01, 2x3060 local only, forced -ngl 99:
  "failed to allocate CUDA0 buffer of size 22183447808" — single-host 2x3060
  capacity insufficient for the backbone; expected; motivated rung 0 as the
  smallest sufficient topology. Zero tokens generated.

Reference arm (Phase 4 freeze)
------------------------------
Same binaries, same model bytes, single-host non-RPC on inferswarm01:
llama-server with auto device fit (n_gpu_layers auto), local CUDA0+CUDA1
plus CPU spill for the remainder; PLE lazy host-side (same as candidate).
The RPC path is the changed variable; identical HTTP JSON protocol
(/tokenize, /completion with return_tokens, greedy sampling, temperature 0)
is used by BOTH arms so the wrapper is common.

Frozen deterministic protocol (both arms):
  - /tokenize {content, add_special:true} to derive exact prompt token IDs;
  - /completion {prompt: <exact token-id prompt>, n_predict: 8,
    temperature: 0 (greedy), seed 0, cache_prompt false, return_tokens true,
    samplers: ["greedy"] or equivalent greedy-only chain};
  - stop policy: no stop strings; generation ends at n_predict=8 committed
    tokens; exact stop_type and stopping_word retained per case;
  - fixture ladder: 4 cases with rendered lengths ~256 / ~1024 / ~3072 /
    ~4096 tokens (exact IDs frozen after tokenizer derivation, before any
    candidate output); 8 committed tokens per case.

Sentinels (Phase 6): case-256 (short) and case-4096 (>2K); 3 clean repeats
per sentinel per arm; plus one clean process-restart rerun of both
sentinels requiring exact equality.

PLE placement contract
----------------------
per_layer_token_embd.weight MUST be host-resident on the client
(inferswarm01), mmap-backed, NOT transferred to any RPC/CUDA buffer.
Machine-checked from: load log lazy-read line; absence of a corresponding
RPC buffer allocation; client RSS/PSS accounting vs file-backed mapping.
