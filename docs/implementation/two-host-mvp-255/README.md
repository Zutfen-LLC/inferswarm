# Issue #255 Task 1: two-CUDA-host startup and coherent generation

**Outcome:** startup/placement proof, not the final MVP terminal. On October 3, 2026, one Qwen3.8-Flash-Next-UD-IQ1_S chat request generated a coherent sentence with local CUDA0 on `inferswarm01` and remote RPC0/CUDA0 on `inferswarm04`. A second ordinary request after an instrumented restart also completed, but the three-request repeatability and single-host baseline required by #255 are **not** claimed here; Task 2 owns those measurements. There is no performance or numerical equivalence claim.

## Frozen inputs and placement

- Base `origin/main`: `442e2a02ce89e7fb42bceff1f7a47c8789c17733`, including `ac9db62d15f21fdc7dd7a04253589f4b9e9ca489`. Fleet/model identities in `evidence/{01,04}/discovery.json` were fully SHA-256 verified by controller before this task. All three members match accepted split-rehash authority; no redundant 72.5 GB rehash was performed here. Model root on **both** hosts: `/srv/models/qwen38-ud-iq1-s/`; first member `Qwen3.8-Flash-Next-UD-IQ1_S-00001-of-00003.gguf`. Member hashes: `88a1420825a9304063e882ada29d438263617f51ac8923d438d927496693bafd`, `3a62e35bbf9add4733bd1438ebd3a67649d5edd6cb0e72bb78e33c913992b2b6`, `0e25ceaeb89b8a80aa973c6c0c7448943682f7408c2855b2ebd016b7643a861a` (members 1–3).
- Both hosts: `/home/hermes/llama.cpp` commit `b29c606e28a01b1bc8c1351026a0fa6e616bf6c4`, tree `950999fe62b7fe55f44ab5b7394e3c8542f37f12`; `build-v041/bin/llama-server` SHA-256 `de3a8a545e2f5995f80ff23f60776fedc30edca67f0e09f3bc47c845156e3411`; `ggml-rpc-server` SHA-256 `a897f908add3305658e6b4f996880033d07ede0800fff71dbc46e90230acdfe9`. Shared-library identities are in each discovery record. No runtime upgrades.
- `inferswarm01` RTX 3060 `GPU-d5c05739-96c1-7e49-89b6-bf54c2121c55`, 10.0.0.142: CPU layers 0–40, **CUDA0 layers 41–44**. CPU backs all MoE experts (`-cmoe`). `inferswarm04` RTX 3090 `GPU-ecda1aaa-0c66-857b-8218-3d511dc75c03`, 10.0.0.204: **RPC0/CUDA0 layers 45–47 and output layer 48**, with expert weights on client CPU. This is the pinned runtime's actual debug layer assignment (`evidence/01/server-layer.log`, `server-capture.log`), not a speculative split. Buffers: local CUDA0 248.45 MiB, remote RPC0 532.75 MiB. The explicit MVP/operator split is `--device CUDA0,RPC0 --split-mode layer --tensor-split 1,1 -ngl 8 -cmoe`; not a generic scheduling rule.

## Local source and transport

`tools/issue255_mvp/prestage.py` parses the pinned GGUF v3 index, streams exact tensor ranges from the **remote participant's own verified SSD members**, computes SHA-256 and calls the compiled `fnv64.c` to name the upstream RPC cache file (FNV is *not* the authority). `evidence/04/selected-layer.json` lists all 71 remotely assigned immutable tensors except `-cmoe` expert tensors. `staging-layer2.json` and `staging-layer3.json` retain name, member, absolute offset, length, SHA-256 and cache key. All **71** cache paths under `/home/hermes/issue255-mvp-retry/cache-layer/rpc/` were re-read by SHA-256 on the participant after publication: **558,627,584 bytes**, zero mismatches. This is a distinct SSD-backed namespace; original `/tmp/issue255-mvp*` attempts were preserved.

The pinned RPC hashes tensors **only above 10 MiB** (`ggml-rpc.cpp:87,700–708,930–935`). Thus the file-open trace `evidence/04/rpc-cache-open.strace` proves 9 exact `O_RDONLY` cache hits, totaling **473,497,600** immutable bytes (including `output.weight`), against the retained staged keys. The other 62 tensors total **85,129,984** bytes and are below this cache-lookup threshold; they travel from client to participant despite having been prestaged. The RPC log shows **zero** `set_tensor saved to` misses during the captured launch. The client TCP socket's cumulative `bytes_sent` was **86,359,771** after load; this includes small immutable payloads and protocol overhead and is not a pure immutable counter. During the captured request it rose to **142,256,308** (delta **55,896,537**, which includes dynamic execution traffic). `evidence/01/rpc-tcp-{before,after}.txt` retain these socket counters.

## Actual generation and physical participation

Prompt and settings in `evidence/01/request.json`: `In one sentence, explain why local backups are useful.`, temperature 0, seed 42, maximum 64 completion tokens, nonstreaming. `generation.json` and `generation-capture.json` both have stop reason `stop` and 53 completion tokens. First completion: “Local backups are useful because they provide quick, reliable access to your data without depending on internet connectivity or cloud services.” The captured restart's server log reports load ~6.84 s; first-request prompt eval 5,194.907 ms, generation 12,950.395 ms at 4.015 tokens/s. This is **not TTFT**; streaming TTFT belongs to Task 2.

`evidence/01/gpu01.csv` samples (250 ms) show 1,055→1,479 MiB and peak 67% utilization. `evidence/04/gpu04.csv` samples show 952→980 MiB and peak 1% utilization. Sampling misses short kernels, so utilization alone is not a threshold/proof. Crucially, the same request's runtime has actual CUDA0/RPC0 layer and weight buffers, 55.9 MB client↔RPC traffic during generation, and `evidence/04/rpc-capture.log` records **four remote `ggml_backend_cuda_graph_compute: CUDA graph warmup complete`** events after server load and request. `evidence/startup-observation.json` binds the derived counts to raw paths. Both server processes stayed healthy through both ordinary completions.

## Commands and bounded lifecycle

Launch on 04 (after compiling helper `cc -O2 -std=c11 -o /home/hermes/issue255-mvp-retry/fnv64 /home/hermes/issue255-mvp-retry/fnv64.c` and staging exact names with `python3 /home/hermes/issue255-mvp-retry/prestage.py --member <member> --member-sha256 <discovery-sha> --names <member-names-json> --cache /home/hermes/issue255-mvp-retry/cache-layer --fnv-binary /home/hermes/issue255-mvp-retry/fnv64 --previously-verified-member`):

```sh
LLAMA_CACHE=/home/hermes/issue255-mvp-retry/cache-layer /home/hermes/llama.cpp/build-v041/bin/ggml-rpc-server -H 10.0.0.204 -p 50055 -d CUDA0 -c
```

Launch on 01, after RPC listens:

```sh
/home/hermes/llama.cpp/build-v041/bin/llama-server -m /srv/models/qwen38-ud-iq1-s/Qwen3.8-Flash-Next-UD-IQ1_S-00001-of-00003.gguf --rpc 10.0.0.204:50055 --device CUDA0,RPC0 --split-mode layer --tensor-split 1,1 -ngl 8 -cmoe --host 127.0.0.1 --port 8343 -c 1024 -np 1 --no-warmup -lv 5
```

HTTP is loopback; RPC is bound only to the selected LAN IP, **not** `0.0.0.0`. This RPC endpoint has no authentication; restrict to the trusted private interface/firewall when repeating. For cache-read proof RPC was launched under `strace -f -ttt -e trace=openat,read -s 80 -o /home/hermes/issue255-mvp-retry/run/rpc-cache-open.strace`, with the same argv/environment. All exact Task-1-owned PIDs were shut down: client `186007` (failed first attempt), `187950`, `190045`; RPC `484133`, `484399`, `484654`, tracer `484650`. Ports 8343 and 50055 were confirmed closed; no live topology is handed off. Preserved remote evidence and SSD cache are under `/home/hermes/issue255-mvp-retry/` on the relevant hosts.

## Failed probe retained / next scope

The first tensor-only override put `blk.24–27.attn_*` weights on RPC while the associated layers stayed on CPU and crashed with `pre-allocated tensor (blk.24.attn_qkv.weight) ... cannot run the operation (NONE)` (`evidence/01/server.log`). Correcting the **whole-layer split** resolved the concrete scheduler incompatibility without modifying pinned runtime. The earlier speculative 12-tensor cache remains separate in `/home/hermes/issue255-mvp-retry/cache/`; no prior attempt data was removed. Stage-2/3 measured repeatability, TTFT, exact request-window network and practical single-host baseline are still required; Task 3 should register the focused `tests/test_issue255_mvp.py` in appropriate CPU-only CI after review. No general qualification or final `MVP_DISTRIBUTED_INFERENCE_PASS` is claimed.
