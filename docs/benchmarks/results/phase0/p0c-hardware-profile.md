# Phase-0 P0-C RTX 3060 hardware profile

```
Label: MEASURED
Status: P0-C complete
Captured: 2026-08-27T15:24:01+00:00
Source artifact SHA-256: fef830fea83f45b6b4b47e7aef30d4104c01c299307d587ef263dcf2403ca499
Repository JSON SHA-256: 806421cf5753cad7e2b52748ecb0bed54e8803eba20191a4829d141b7aea33fd
```

This is the accepted Phase-0 P0-C hardware-profile evidence for InferSwarm issue #2. It was captured only after the P0-C procedure and provenance gate were committed in InferSwarm and after FreeToken PR #2 fixed the same-GPU sequential diagnostic bind defect found by the exploratory runs.

The complete JSON data are committed as [`p0c-hardware-profile.json`](p0c-hardware-profile.json). That repository copy was reserialized with whitespace-only normalization; every JSON value and raw per-repetition observation is preserved. The source host artifact digest above remains the byte identity of the machine-produced file. The summary below is descriptive only; where it disagrees with the JSON data, the JSON wins.

## Provenance gate

- FreeToken commit: `715476811acdf281341d0f5f704bcc063bb18630`
- FreeToken checkout: clean (`dirty = false`, no dirty paths)
- InferSwarm methodology commit: `530bbc796039d7d3975439d0fbc2641b4ed0e5b9`
- Harness version: `0.3.0`
- Python: `3.13.5`, `/home/zutfen/FreeToken/.venv/bin/python`
- PyTorch: `2.11.0+cu130`; CUDA runtime reported by PyTorch: `13.0`; CUDA toolkit (`nvcc`): `13.1`

The selected physical GPU UUID agrees across the top-level profile, `ft bench bw`, device-memory bandwidth diagnostic, and expert microbenchmark:

`GPU-d5c05739-96c1-7e49-89b6-bf54c2121c55`

## Hardware identity

- GPU: NVIDIA GeForce RTX 3060
- VRAM: 12,288 MiB
- Compute capability: 8.6
- Driver: 610.57.04
- PCIe width: x16 current / x16 max
- PCIe generation recorded by idle `nvidia-smi`: Gen1 current / Gen3 max
- CPU: Intel Xeon E5-2683 v3 @ 2.00 GHz, 14 physical cores / 28 logical CPUs
- RAM: 134,985,097,216 bytes
- OS/kernel: Linux 6.12.105+deb13-amd64

The Gen1 `pcie.link.gen.current` value is retained exactly as observed rather than rewritten. The measured linear PCIe transfer rates below are far above a sustained Gen1 x16 ceiling, which is consistent with the link training up under workload while the static `nvidia-smi` provenance query captured the idle power state.

## `ft bench bw` host/PCIe calibration

The command completed successfully, named the same GPU UUID, and its generated profile matched that GPU.

| Measurement | Result |
|---|---:|
| CPU STREAM read | 32.0 GB/s |
| PCIe linear H2D | 11.58 GB/s |
| PCIe linear D2H | 12.11 GB/s |
| NVFP4 CPU-MoE | 19.4 GB/s |
| NVFP4 PCIe expert gather | 6.99 GB/s |
| Overlapped CPU-MoE | 18.15 GB/s |
| Overlapped PCIe gather | 6.77 GB/s |

NVFP4 calibration is **usable**. FreeToken recommended `hybrid`, with a recorded hybrid fetch fraction of `0.271669341894061` (about 27.17% of misses). The calibration profile itself is SHA-256 `2fdfc45f3daef87791bf6b38d4e539e2ea5e232453e00d5e5f0e487d6976c332`.

## Device/VRAM D2D bandwidth diagnostic

Method: CUDA-event timing around a 512 MiB device-to-device `torch.Tensor.copy_`; each repetition accounts for one read plus one write (1 GiB total movement). Five warmups were discarded and all 30 measured repetitions are retained in the JSON.

| Statistic | Read + write accounting |
|---|---:|
| Minimum | 326.589 GB/s |
| Median | 331.304 GB/s |
| Maximum | 331.618 GB/s |
| Mean | 330.506 GB/s |
| Standard deviation | 1.572 GB/s |
| CV | 0.476% |

The equivalent one-direction/read-only accounting is 165.253 GB/s mean. These are diagnostic hardware-profile measurements, not an inference-throughput estimate.

## Resident NVFP4 expert execution diagnostic

The expert diagnostic executed on the same proven RTX 3060 UUID using `freetoken.moe.fused_nvfp4.fused_experts_decode_nvfp4_marlin`. Expert weights were already resident on GPU; PCIe transfer is excluded from the timed interval.

- Geometry: hidden 2048, MoE intermediate 512, 32 cache slots, one token.
- Warmup: 20 calls; measured repetitions: 200.
- True `top_k=1` single-expert latency: **0.5215595 ms**.
- Single-expert diagnostic weight-read rate: 3.4044 GB/s.
- Grouped `top_k=8` routed-expert step latency: **0.5197432 ms**.
- Grouped diagnostic weight-read rate: 27.3307 GB/s.

The grouped step is intentionally **not divided by eight**. Experts inside that grouped call execute concurrently; `step_ms / top_k` would be an amortized throughput-like quantity, not single-expert latency. The separately measured `top_k=1` value is the single-expert latency required by P0-C.

## P0-C verdict

**PASS.** The accepted artifact contains every item required by [`docs/benchmarks/phase0-p0c-hardware-profile.md`](../../phase0-p0c-hardware-profile.md): exact repository provenance, clean FreeToken state, selected RTX 3060 12-GB identity and UUID, host/runtime/topology provenance, successful `ft bench bw`, usable NVFP4 calibration, per-repetition VRAM bandwidth evidence, true `top_k=1` expert latency, and the separately labelled grouped diagnostic.

This verdict says only that the Phase-0 hardware profile is complete. It does **not** establish an InferSwarm speedup and does not select `CANONICAL_PERFORMANCE_BASELINE`. Per `BENCHMARKING.md`, the microbenchmarks diagnose; only later end-to-end serving measurements can decide performance.
