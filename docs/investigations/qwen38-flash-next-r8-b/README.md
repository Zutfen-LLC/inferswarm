# R8-B — Qwen3.8-Flash-Next UD-IQ1_S pinned llama.cpp NVIDIA cross-host RPC qualification

Status: physical runtime qualification for [issue #191](https://github.com/Zutfen-LLC/inferswarm/issues/191), executed 2026-09-14/15 under the accepted R8-A authority (issue #189 / PR #190, merge `938af774878f562314e920007846f9f2bb611ec2`, terminal `R8A_QWEN38_RUNTIME_PREREQUISITE`).

**Terminal: `R8B_QWEN38_NVIDIA_RPC_RUNTIME_QUALIFICATION_FAIL`** — mechanically re-derived by `scripts/issue191_terminal_reduction.py` from the retained evidence (this directory + `terminal-reduction.json`).

## What was proved (all machine-checked)

1. **Exact representation integrity.** The complete three-member UD-IQ1_S split set was downloaded to inferswarm01; every member's full sha256 equals the accepted R8-A LFS pin (`88a14208…`, `3a62e35b…`, `0e25ceae…`); every member's header extent byte-reproduces the retained R8-A raw headers.
2. **One pinned runtime, three identical builds.** llama.cpp `b29c606e…` (tag v0.4.1, released 2026-09-14) selected per Phase 1: contains the #27960/#27993 repair (merge `73f56d10…` verified ancestor), full `qwen4exp` support (5 support commits ancestral), CUDA + cross-host RPC. Built from clean clones on inferswarm01/03/04 with pinned flags (CUDA 13.1, gcc 14.2.0, cmake 3.31.6, arch 86); `llama-cli`, `llama-server`, `ggml-rpc-server` byte-identical across hosts.
3. **PLE host residency is the runtime default and was demonstrated.** At this revision `TENSOR_READ_LAZY` + auto-lazy (>4 GiB, mmap) puts `per_layer_token_embd.weight` (27465.95 MiB, reported as 27466 MiB elsewhere) in a client-side CPU mmap; `-ot` cannot move it (lazy return precedes the override block — matches R8-A's source audit). Both arms' load logs retain the lazy-read line; accounting shows the client's PLE is file-backed (`RssFile`), with NO anonymous host mirror.
4. **Intended topology executed.** Frozen rung-0: client inferswarm01 (2× RTX 3060) + RPC inferswarm03 (2× RTX 3060, one rpc-server per GPU) + RPC inferswarm04 (RTX 3090) over 1 GbE. Load logs retain the exact per-device model buffers: 6796.90 + 6518.70 (local) + 7761.99 + 6796.90 (03) + 13493.79 MiB (04) = 41368 MiB backbone on devices, PLE 27466 MiB host-side, 49/49 layers offloaded, 3/3 RPC endpoints used. No silent CPU-only or wrong-device fallback (device-buffer arithmetic reconciles with the accepted census; GPU compute apps observed on exactly the intended UUIDs).
5. **Both arms are internally deterministic and restart-stable.** Reference (single-host non-RPC, same build + bytes): 3/3 identical runs. Candidate: 3/3 identical runs; full process restart (all client+RPC processes killed, proven gone, GPUs idle, relaunched identical config) reproduces byte-identical outputs.
6. **The fixture ladder pressed the >2K class.** Exact frozen token IDs (256/1022/3077/4097 rendered tokens, derived via the pinned build's own `/tokenize`), 8 committed greedy tokens, `return_tokens` exact IDs, stop semantics retained per case.

## The FAIL basis

The distributed candidate's generated token IDs differ from the frozen same-build single-host reference on **all four** cases, with a shared-prefix divergence pattern (positions 3/3/4/0 for 256/1024/3072/4096). The candidate is deterministic and restart-stable, so this is a reproducible cross-host-RPC divergence, not noise. Per the issue contract: comparator untouched, topology/runtime unchanged after observation, no re-tuning — retained as FAIL.

Divergence detail (reference → candidate):
- case-256: prefix `561, 40554, 32039` then `28056, 3486, 271, 248068, 198` vs `25082, 271, 248068, 271, 248069`
- case-1024: prefix `561, 51624, 13332` then `4558, …` vs `2423, …`
- case-3072: prefix `561, 29262, 49172, 33172` then `248046` (EOS) vs `10598, 321, 279, 324`
- case-4096: reference `561, 29262, …` (8 tokens) vs candidate immediate `248046` (EOS at position 0)

## Evidence map

- `TOPOLOGY-FREEZE.md` — Phase 1/3 freeze: runtime selection, build/binary identity, topology, ladder, pre-output failed-load attempts, PLE contract
- `evidence/split-identity/split-verification.json` — Phase 2 receipts
- `evidence/runtime-authority/runtime-authority.json` + `binary-hashes.json` — selection, ancestry proofs, build flags, hashes, option contract
- `evidence/reference/` — fixture-ladder.json, reference-run-{1,2,3}.json, reference-server.log
- `evidence/candidate/` — candidate-run-{1,2,3}.json, candidate-restart.json, candidate-server.log
- `evidence/accounting/residency-accounting.json` — per-process RSS/PSS/mappings/GPU for all 5 processes
- `evidence/negative-controls/negative-controls.json` — 10 reducer-level controls, all fail closed
- `evidence/topology-ladder/smoke-singlehost-2x3060.log` — pre-output failed load (zero tokens), motivating rung-0
- `evidence/raw-observations/` — rpc-server logs from 03/04
- `terminal-reduction.json` — machine-derived terminal + checks

## Non-claims

- No AMD/Vulkan execution; no mixed-vendor claim. The 3060 Ti (x1 riser path) was not used.
- FAIL qualifies nothing about llama.cpp generally — it records that THIS pinned runtime/representation/topology did not reproduce the same-build single-host reference over cross-host RPC.
- The reference arm itself (single-host, CUDA0+CUDA1+CPU spill, lazy PLE) is deterministic but is not hereby claimed as a production serving configuration.
- Performance observations (load ~6 min over 1 GbE; per-case wall times in the run records) are descriptive only.
- No InferSwarm planner/serving integration, no production-readiness, no fleet-topology inference.
- inferswarm02, valinor, and all non-selected hardware untouched; model bytes stored outside Git under `/srv/models/qwen38-ud-iq1-s/` on inferswarm01 only.

## Successor note

The failure signature (deterministic, prefix-divergent, worst on >2K) is consistent with the cross-host RPC defect class of #27993 but on a different backend/quant/topology; any repair attempt requires a fresh issue — this terminal may not be re-labeled or re-run under the same authority.
