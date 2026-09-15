R8-C diagnosis authority freeze (Phase 0)
========================================

Frozen: 2026-09-15, BEFORE any new diagnostic model output (Issue #193 Phase 0).
Authority module: scripts/issue193_r8c_authority.py (this freeze's constant source).

Starting point
--------------
- origin/main = 3448cc7d63853079fff2520952c2b65d586ae3e4 (accepted R8-B merge,
  PR #192) — verified ancestral (it is the current main head at freeze time).
- Branch: issue-193-r8c-qwen38-rpc-divergence-diagnosis.

Accepted predecessor (consumed, never rewritten)
------------------------------------------------
- Issue #191 / PR #192, terminal R8B_QWEN38_NVIDIA_RPC_RUNTIME_QUALIFICATION_FAIL.
- R8-B bundle byte-preservation re-verified via its own MANIFEST.sha256
  (fail-closed; see tests and authority module). R8-B's missing raw host
  inventory is a scoped provenance limitation of the predecessor, retained
  as-is; R8-C does not repeat it.

Frozen runtime/model authority (identical to accepted R8-B)
-----------------------------------------------------------
- llama.cpp b29c606e28a01b1bc8c1351026a0fa6e616bf6c4 (v0.4.1); binaries at
  /home/hermes/llama.cpp/build-v041/bin on all three hosts re-hashed at
  R8-C freeze: llama-cli 3f6b0ed4..., llama-server de3a8a54...,
  ggml-rpc-server a897f908... — identical to the accepted R8-B pins.
- Model: /srv/models/qwen38-ud-iq1-s (inferswarm01), 3-member UD-IQ1_S split;
  member sha256 re-hashed against accepted R8-A pins at freeze (see
  evidence/split-identity-r8c/).
- Generation protocol (both arms, all wedges): HTTP /completion with
  prompt=<exact token ids>, n_predict=8, temperature=0.0, seed=0,
  samplers=["greedy"], cache_prompt=false, return_tokens=true, stream=false —
  identical to accepted R8-B.

Fresh raw host inventory (prospective; the R8-B retention gap closed)
----------------------------------------------------------------------
Retained verbatim under evidence/host-inventory/:
- inferswarm01-inventory-raw.txt + nvidia-smi-q.xml
- inferswarm03-inventory-raw.txt + nvidia-smi-q.xml
- inferswarm04-inventory-raw.txt + nvidia-smi-q.xml
Each contains: hostname, UTC date, uname, full ip addr, full nvidia-smi -q
(+ XML), per-GPU BDF/UUID/VRAM/driver, PCIe current/max link gen+width,
nvcc version, live llama/rpc process census (none at capture), and the three
pinned binary hashes re-measured on that host.

Notable inventory facts (raw evidence retained, not transcribed-only):
- inferswarm03 GPU1 (GPU-a57bd3fb) PCIe link currently 4x width (max 16x).
- inferswarm04 3090 max link gen 2 (current gen 1 at idle).
- All GPUs idle at capture; no stale llama/rpc processes on any host.

Experiment matrix
-----------------
Frozen prospectively in scripts/issue193_r8c_authority.py::EXPERIMENT_MATRIX
before the first new diagnostic model output. See that constant for the full
wedge definitions (Phase 1 reproduction arms R8C-R/R8C-C; wedge A direct vs
loopback RPC on one pinned tensor subset; wedge B local vs remote RPC on a
matched 3060; wedge C relation to the full accepted topology; Phase 3
teacher-forced logprob capture with pre-frozen descriptive margin buckets
near-tie < 0.10, moderate <= 1.0 logit).

Diagnostic boundaries (from Issue #193, restated)
------------------------------------------------
- No llama.cpp revision change, no repair, no requalification, no different
  runtime, no comparator weakening, no AMD/Vulkan, no Qwen serving
  integration. Diagnosis only; the accepted R8-B FAIL is immutable.
