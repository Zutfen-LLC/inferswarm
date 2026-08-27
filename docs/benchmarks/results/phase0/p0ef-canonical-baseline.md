# Phase-0 P0-E/P0-F canonical baseline result

```
Label: MEASURED
Verdict: CANONICAL_PERFORMANCE_BASELINE SELECTED
Date: 2026-08-27
```

This result combines the two completed canonical B1–B5 Phase-0 performance sessions. The selection rule is the predeclared rule in `docs/phase1-poc-success-criteria.md`: choose the valid FreeToken configuration with the highest aggregate warm decode throughput on the frozen W1–W4 workload set. No Phase-1 candidate measurement exists at the time of this selection.

## Verdict

**`CANONICAL_PERFORMANCE_BASELINE` = B1, with B4 an equivalent duplicate observation of the same resolved configuration on this host.**

Resolved baseline configuration:

- `--moe-backend offload`;
- B1's `--nvfp4-backend auto` resolved to **Triton**, so B1 and forced-Triton B4 collapse to the same runtime configuration;
- GPU decode target; no auto CPU layers fired;
- `--moe-cache-auto` resolved to 3,774 resident expert slots = 36.8555% of 10,240 total expert slots;
- `memory_ratio=0.85`, `kv_reserve_tokens=17075`;
- one RTX 3060 12 GB, UUID `GPU-d5c05739-96c1-7e49-89b6-bf54c2121c55`.

The two sessions independently pick the same **resolved configuration**: Session 1's numerically highest arm is B4; Session 2's is B1. Because B1 and B4 are the predeclared collapse pair and resolve identically, this is agreement rather than a conflicting winner. B4/B1 aggregate-decode ratio is 1.000425 in Session 1 (10,000-resample bootstrap 95% CI 0.984910–1.015949) and 0.999447 in Session 2 (95% CI 0.990777–1.008495); both intervals include 1.000. Across the eight session×class medians, B1's descriptive geometric mean is 55.671827 tok/s and B4's is 55.668250 tok/s. B1 is retained as the single representative arm identity; B4 is not treated as a distinct faster backend.

## Run identity

- FreeToken commit, both sessions: `2c3da952e47391bf392e0ece8ae4c67acbc91762` (clean checkout);
- InferSwarm Session 1 methodology: `70a0974d7efe9a57fed9e405250ee02a355e3899`;
- InferSwarm Session 2 methodology: `7e636ac6a72865af77cf7c63ac168808a55120df`; the only post-Session-1 methodology change replaced the arbitrary calendar-day proxy with an independently cooled thermal-reset requirement before Session 2;
- model: `nvidia/Qwen3.6-35B-A3B-NVFP4`;
- model revision: `491c2f1ea524c639598bf8fa787a93fed5a6fbce`;
- workload manifest SHA-256: `10f81e5418a71a68f387632de422c3337cc7ba0518111a8746ad856d0210b24a`;
- Session 1 raw archive SHA-256: `11bcbbcab49cdbf816e7940d185527c1f176703dcf8fabfd81cb4e8ff7d613ee`;
- Session 2 raw archive SHA-256: `b74fc411fbcee08ecdcfcda1bab06d74a4e2fd5b4f769793f300450119c2f3a5`.

## Canonical execution validity

Both session artifacts report `VALID CANONICAL CAMPAIGN`, `execution_status=COMPLETE`, zero failures, zero campaign invalidations, and 20/20 complete arm×workload blocks. Each session contains 40 warmups and 200 measured generations, for **400 canonical measured generations** across P0-E/P0-F.

All 480 total generations across the two sessions:

- reproduce serving prompt counts W1/W2/W3/W4 = 569 / 54 / 16,819 / 121 exactly;
- reproduce requested completion lengths = 512 / 512 / 256 / 128 exactly;
- have valid request-UID-attributed prefill measurements;
- retain nonempty output text whose recorded SHA-256 matches the stored text;
- use the same pinned model revision, physical GPU, FreeToken commit, harness version, memory ratio, KV reserve, warmup count, measured repetition count, and frozen manifest.

Session traversal is forward B1→B2→B3→B4→B5 in P0-E and reversed B5→B4→B3→B2→B1 in P0-F. All ten server logs are free of `ERROR`, traceback, OOM, and backend-worker-crash records. Python `resource_tracker` semaphore warnings remain post-shutdown cleanup noise.

## Aggregate warm decode result

Each entry is the geometric mean of the four per-class median warm decode throughputs within that session. The last column is the descriptive geometric mean across all eight session×class medians.

| Arm | Resolved decode backend | Session 1 tok/s | Session 2 tok/s | 8-cell descriptive GM tok/s |
| --- | --- | ---: | ---: | ---: |
| B1 | offload | 55.875 | 55.470 | 55.672 |
| B4 | offload | 55.898 | 55.439 | 55.668 |
| B3 | hybrid (auto→hybrid) | 48.797 | 46.096 | 47.427 |
| B2 | hybrid | 44.057 | 45.649 | 44.846 |
| B5 | cpu | 18.133 | 18.052 | 18.092 |

B1/B4 dominate both sessions. B3/B2 are valid hybrid observations but are materially slower than the offload+Triton baseline; B5 CPU decode is much slower. B2 and B3 both resolve to hybrid within each session. Their session-level fresh `ft bench bw` calibration changed the allowed hybrid fetch fraction from 25.2904% in Session 1 to 26.2850% in Session 2, as intended by the protocol.

## Per-block measured statistics

Decode variance is reported as required: min, median, max, IQR, and coefficient of variation over the 10 measured repetitions in each arm×class×session block. TTFT and CUDA-event prefill medians are included as secondary measurements; baseline selection is decode-only.

| Session | Arm | Class | Decode min | Decode median | Decode max | Decode IQR | Decode CV | TTFT median ms | Prefill median tok/s |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | B1 | W1 | 56.130 | 58.373 | 60.361 | 3.065 | 2.86% | 1754.0 | 32.79 |
| 1 | B1 | W2 | 53.869 | 55.898 | 56.865 | 0.713 | 1.47% | 1750.4 | 31.05 |
| 1 | B1 | W3 | 51.456 | 53.169 | 54.529 | 1.619 | 2.05% | 1845.1 | 29.34 |
| 1 | B1 | W4 | 54.624 | 56.181 | 57.750 | 2.076 | 2.11% | 1750.5 | 32.79 |
| 1 | B2 | W1 | 43.871 | 45.741 | 47.025 | 1.431 | 2.36% | 1753.4 | 32.80 |
| 1 | B2 | W2 | 40.680 | 42.852 | 44.636 | 1.865 | 2.94% | 1749.1 | 31.07 |
| 1 | B2 | W3 | 40.827 | 41.321 | 41.762 | 0.490 | 0.76% | 1844.4 | 29.34 |
| 1 | B2 | W4 | 44.921 | 46.519 | 48.418 | 1.787 | 2.47% | 1750.2 | 32.80 |
| 1 | B3 | W1 | 48.654 | 49.960 | 52.202 | 1.539 | 2.34% | 1761.0 | 32.66 |
| 1 | B3 | W2 | 46.426 | 48.268 | 49.727 | 2.089 | 2.44% | 1757.5 | 30.92 |
| 1 | B3 | W3 | 45.230 | 45.503 | 46.035 | 0.507 | 0.69% | 1854.8 | 29.21 |
| 1 | B3 | W4 | 47.974 | 51.674 | 55.047 | 3.056 | 4.12% | 1759.1 | 32.64 |
| 1 | B4 | W1 | 56.174 | 58.414 | 60.381 | 3.053 | 2.84% | 1753.7 | 32.78 |
| 1 | B4 | W2 | 53.868 | 55.926 | 56.865 | 0.716 | 1.47% | 1750.6 | 31.03 |
| 1 | B4 | W3 | 51.463 | 53.185 | 54.527 | 1.615 | 2.05% | 1845.4 | 29.32 |
| 1 | B4 | W4 | 54.649 | 56.191 | 57.750 | 2.100 | 2.10% | 1750.6 | 32.78 |
| 1 | B5 | W1 | 18.228 | 18.264 | 18.366 | 0.040 | 0.22% | 1758.6 | 32.70 |
| 1 | B5 | W2 | 18.211 | 18.304 | 18.689 | 0.028 | 0.72% | 1755.8 | 30.95 |
| 1 | B5 | W3 | 17.658 | 17.736 | 17.883 | 0.033 | 0.33% | 1851.3 | 29.26 |
| 1 | B5 | W4 | 18.136 | 18.232 | 18.322 | 0.013 | 0.30% | 1754.3 | 32.71 |
| 2 | B1 | W1 | 55.934 | 58.309 | 59.756 | 1.127 | 2.03% | 1760.5 | 32.67 |
| 2 | B1 | W2 | 54.370 | 55.964 | 57.688 | 0.834 | 1.76% | 1756.2 | 30.93 |
| 2 | B1 | W3 | 51.688 | 52.311 | 54.383 | 1.152 | 1.65% | 1851.8 | 29.23 |
| 2 | B1 | W4 | 53.530 | 55.462 | 55.965 | 0.888 | 1.44% | 1755.1 | 32.69 |
| 2 | B2 | W1 | 45.284 | 46.820 | 48.129 | 1.401 | 2.01% | 1759.0 | 32.69 |
| 2 | B2 | W2 | 42.809 | 45.005 | 47.582 | 1.579 | 3.19% | 1756.7 | 30.93 |
| 2 | B2 | W3 | 42.284 | 43.197 | 43.970 | 0.909 | 1.38% | 1850.1 | 29.24 |
| 2 | B2 | W4 | 45.864 | 47.708 | 48.901 | 1.499 | 2.08% | 1756.8 | 32.67 |
| 2 | B3 | W1 | 45.197 | 46.927 | 48.046 | 1.365 | 2.01% | 1760.3 | 32.70 |
| 2 | B3 | W2 | 43.096 | 45.179 | 47.518 | 1.571 | 2.96% | 1756.8 | 30.94 |
| 2 | B3 | W3 | 41.991 | 44.446 | 45.059 | 1.759 | 2.49% | 1851.3 | 29.24 |
| 2 | B3 | W4 | 46.160 | 47.912 | 49.109 | 0.711 | 1.83% | 1755.4 | 32.69 |
| 2 | B4 | W1 | 55.940 | 58.316 | 59.758 | 1.116 | 2.03% | 1761.2 | 32.65 |
| 2 | B4 | W2 | 54.325 | 55.942 | 57.691 | 0.795 | 1.77% | 1758.4 | 30.90 |
| 2 | B4 | W3 | 51.662 | 52.275 | 54.338 | 1.139 | 1.64% | 1855.0 | 29.20 |
| 2 | B4 | W4 | 53.512 | 55.393 | 55.949 | 0.875 | 1.45% | 1757.3 | 32.64 |
| 2 | B5 | W1 | 18.256 | 18.335 | 18.698 | 0.080 | 0.69% | 1763.0 | 32.62 |
| 2 | B5 | W2 | 18.243 | 18.311 | 18.445 | 0.077 | 0.36% | 1760.1 | 30.88 |
| 2 | B5 | W3 | 17.362 | 17.421 | 17.462 | 0.041 | 0.20% | 1855.1 | 29.19 |
| 2 | B5 | W4 | 17.839 | 18.157 | 18.310 | 0.189 | 0.83% | 1760.9 | 32.61 |

### Prefill interpretation

The canonical protocol intentionally measures a **warm** repeated-workload serving state and does not force prefix-cache misses. After the two warmups, the measured baseline B1 repetitions consistently prefill only the uncached suffix: W1 = 57 new + 512 cached tokens; W2 = 54 + 0; W3 = 51 + 16,768; W4 = 57 + 64. Accordingly, the reported prefill tok/s values are CUDA-event rates for the actual uncached prefill work performed in that warm state; they must not be misread as cold full-prompt throughput. TTFT remains end-to-end client-observed first-token latency.

## Baseline reproducibility gate

For representative baseline arm B1, decode CV is below the required 5% in every class in both sessions:

| Class | Session 1 CV | Session 2 CV |
| --- | ---: | ---: |
| W1 | 2.86% | 2.03% |
| W2 | 1.47% | 1.76% |
| W3 | 2.05% | 1.65% |
| W4 | 2.11% | 1.44% |

Both sessions completed with no early stopping and no repetition discarded. The Phase-1 reproducibility prerequisite for the performance baseline is therefore satisfied.

## Baseline class medians for downstream comparison

Phase-1 comparisons must preserve the two-session discipline and use the matching B1 baseline session/class medians rather than collapsing the sessions into one synthetic denominator:

| Class | Session 1 decode tok/s | Session 2 decode tok/s | Session 1 TTFT ms | Session 2 TTFT ms | Session 1 prefill tok/s | Session 2 prefill tok/s |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| W1 | 58.373 | 58.309 | 1754.0 | 1760.5 | 32.79 | 32.67 |
| W2 | 55.898 | 55.964 | 1750.4 | 1756.2 | 31.05 | 30.93 |
| W3 | 53.169 | 52.311 | 1845.1 | 1851.8 | 29.34 | 29.23 |
| W4 | 56.181 | 55.462 | 1750.5 | 1755.1 | 32.79 | 32.69 |

These values are the canonical single-RTX-3060+host-RAM performance reference for the pinned checkpoint and workload. They do not establish correctness; the separate fixed `CORRECTNESS_REFERENCE` campaign remains required before Phase 0 is complete.

## P0-E/P0-F verdict

**PASS.** Both canonical performance sessions are valid and complete, their order reversal succeeds, the baseline reproducibility gate passes, and both select the same resolved offload+Triton configuration. `CANONICAL_PERFORMANCE_BASELINE` is therefore fixed as **B1 (B4-equivalent resolved offload+Triton)**. No later Phase-1 candidate may be compared against a slower B2/B3/B5 arm and described as a speedup.
