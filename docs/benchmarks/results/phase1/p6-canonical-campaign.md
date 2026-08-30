# Phase 1 P6 canonical campaign

**Evidence class:** MEASURED

**Campaign status:** both sessions `COMPLETE` / `VALID`

**Mechanical verdict:** `NO-GO`

This report publishes the fresh P6 campaign run after the instrumentation-control
fix. The permanently incomplete campaign on `44b3ddfc…` was not reused,
spliced, compared, or included in any calculation.

## Provenance

| Identity | Exact value |
|---|---|
| FreeToken runtime | `f29013fda7f1dcda94c6e44957d8b503795928dd` (clean) |
| InferSwarm methodology | `14d0190eb76f39e11fcfd2e39d386ae05df78792` |
| Campaign runner | `0.4.0` |
| Campaign identity | `1a1dda536059c8d71f9179597c46d17c65a7763d9a8875414d7ce823b1c2ec13` |
| Model | `nvidia/Qwen3.6-35B-A3B-NVFP4` |
| Model revision | `491c2f1ea524c639598bf8fa787a93fed5a6fbce` |
| Workload manifest | `phase0-v1-2026-08-27`; SHA-256 `10f81e5418a71a68f387632de422c3337cc7ba0518111a8746ad856d0210b24a` |
| Placement | `coverage_constrained_complement_5442`; SHA-256 `2f62bb84df40d4cc5649e940a39cb53d2975eadecbc320fb97d2b037d4e005f4` |
| GPU 0 | RTX 3060 12 GB, `GPU-d5c05739-96c1-7e49-89b6-bf54c2121c55` |
| GPU 1 | RTX 3060 12 GB, `GPU-e1f2f90c-49ab-2689-0cf1-e5d9da520176` |
| Transport | stock-driver host-staged; peer access unavailable in both directions |

W1/W2/W3/W4 generated 512/512/256/128 tokens respectively, batch size 1,
greedy, `ignore_eos`. Each block retained two discarded warmups and all ten
measured repetitions. Actual uncached-prefill work from instrumentation, not
nominal prompt length, is used below.

## Exact-build prerequisites

| Artifact | Result | SHA-256 |
|---|---|---|
| Correctness reference Session A | canonical; all W1–W4 captures valid | `113b5cd5335e244265cf543ef89f87708ad1d6e1f07b260c72ad0e57e72069a0` |
| Correctness reference Session B | independent fresh server; exact match to A | `113b5cd5335e244265cf543ef89f87708ad1d6e1f07b260c72ad0e57e72069a0` |
| A/B self-consistency | complete sequences, first 64, argmax and top-5 exact; max absolute/relative deviation 0; zero NaN/Inf | `312db8623d6c0f6cd32cffbb1d1f2357cd524e3b7fa3580c5a790397f34461b2` |
| Candidate C1–C4 | all pass; C1/C3 max absolute/relative deviation 0; C2 exact; C4 zero NaN/Inf | `1904345b79531a91c261a94396e2dd71350b874f8a9a3ee5bc53a14fdfc84b7f` |
| P2/P3/P4 replay | all pass | `510ec3e90d733067da5be8d48f3ad17b8b31de27f3835ace36b227187f115efc` |
| Prerequisite manifest | independently rehashed by runner | `67e3cf67465687ec0ac1b99517110a31668d4638334cea58d25385e371c9fa91` |

P2 measured 5,442 GPU-1 resident slots and 9,662,902,272 resident expert
bytes, verified all source bytes/layout, separately recorded the same startup
weight H2D byte count, and measured zero steady-state expert-weight H2D. P3
passed local-only, remote-only, mixed, and 40-layer cases with exact ownership,
combine, dispatch, zero fallback/failure, and zero remote prefill. P4 passed
F1/F2/F3/F5/F6 independently for W1–W4 with overlap active and complete,
untruncated layer timing. F4 is established by C1/C2.

Part 4 software sanity was `PASS_WITH_PRE_EXISTING_EXCEPTIONS`: 179 Phase-1
campaign tests passed; 539 benchmark tests passed excluding the known
`test_phase0_profile_provenance.py` collection defect; engine/server/scheduler/
MoE tests were 996 passed and 6 skipped; `compileall` and `git diff --check`
passed. Ruff returned only the two reviewed pre-existing I001 findings. The
preserved original sanity artifact has SHA-256
`722cffc3e06ad9b00bf9ec0775d9ea99c775404ca24c2ecd45983ef96689999b`;
its separate disposition has SHA-256
`6240a103c4b1638f1b27d6f32fc4ca16c780f6046558cc978b72be66c3295048`.
FreeToken was not modified.

## Validation and session execution

Runner `plan` SHA-256 was
`78e0d01a400d0d86c9e614b6100bf4e456cc1999803daad7ccd34a52e4411229`.
Runner `validate` exited 0 and produced SHA-256
`34d031afd09f7f526c7e2e9ffd7a1668604d8e3615850e745970c3750cb595ea`:
`canonical = true`, `held_equal_all = true`, and
`undeclared_differences = []`.

| Session | Primary order | Supplementary disposition | Status | Baseline gate |
|---|---|---|---|---|
| 1 | B1 → candidate | B1 KV-matched required and completed | `COMPLETE` / `VALID` | campaign-build identity `PASS` |
| 2 | candidate → B1 | B1 KV-matched required and completed | `COMPLETE` / `VALID` | campaign identity and B1 revalidation `PASS`; no drift |

Each session completed 96 primary and 48 conditional supplementary
generations (144 total); the campaign completed 192 primary generations. In
Session 1 the boundary was GPU0 47 °C/GPU1 48 °C, both P8 at 210 MHz with
9/1 MiB used, no compute applications. Before Session 2 the explicit reset
attestation recorded GPU0/GPU1 at 46/46 °C, P8, 210 MHz SM/405 MHz memory,
9/1 MiB used, no compute applications, and host loads 0.60/0.91/1.10. GPU
memory and CPU package temperatures were unavailable. Runner observation at
the Session-2 boundary was 47/46 °C with the same idle memory and no apps.

## Statistical method

Sessions were analyzed independently and never pooled. Within each
session/class, each bootstrap replicate independently sampled the ten
candidate and ten baseline repetitions with replacement, took both medians,
then formed `R_c`; `R_agg` is the geometric mean of the four `R_c` values.
The recorded seed is 0, with 10,000 unpaired arm-major resamples and linear
percentile 95% intervals. Equal repetition indices were never paired. No
repetition was removed.

## M-warm decode result

All rates are median decode tokens/s. `Sig.` means the 95% interval excludes
1.000; here every interval is entirely below 1.000.

| Session | Class | Baseline | Candidate | `R_c` | 95% CI | Sig. |
|---|---|---:|---:|---:|---:|---|
| 1 | W1 | 57.285940 | 4.105904 | 0.071674 | [0.068661, 0.073756] | yes, slower |
| 1 | W2 | 55.000636 | 3.854352 | 0.070078 | [0.069527, 0.073324] | yes, slower |
| 1 | W3 | 52.300641 | 3.908679 | 0.074735 | [0.074112, 0.076995] | yes, slower |
| 1 | W4 | 55.243938 | 4.053848 | 0.073381 | [0.071863, 0.075101] | yes, slower |
| 2 | W1 | 57.299742 | 4.003418 | 0.069868 | [0.067628, 0.071681] | yes, slower |
| 2 | W2 | 54.998495 | 3.885417 | 0.070646 | [0.070019, 0.071135] | yes, slower |
| 2 | W3 | 52.339485 | 4.018068 | 0.076769 | [0.076167, 0.079015] | yes, slower |
| 2 | W4 | 55.270190 | 3.945253 | 0.071381 | [0.069835, 0.074889] | yes, slower |

| Session | `R_agg` | 95% CI | Independent verdict |
|---|---:|---:|---|
| 1 | 0.072446 | [0.071678, 0.073728] | `NO-GO` |
| 2 | 0.072116 | [0.071399, 0.073277] | `NO-GO` |

## Variance

| Session | Arm | Class | n | Min | Median | Max | IQR | CV |
|---|---|---|---:|---:|---:|---:|---:|---:|
| 1 | B1 | W1 | 10 | 55.1435 | 57.2859 | 59.2546 | 2.9303 | 2.8199% |
| 1 | B1 | W2 | 10 | 52.9937 | 55.0006 | 55.9039 | 0.6821 | 1.4485% |
| 1 | B1 | W3 | 10 | 50.6077 | 52.3006 | 53.7123 | 1.5917 | 2.0549% |
| 1 | B1 | W4 | 10 | 53.7243 | 55.2439 | 56.7435 | 2.1131 | 2.0919% |
| 1 | candidate | W1 | 10 | 3.9158 | 4.1059 | 4.2226 | 0.1065 | 2.4260% |
| 1 | candidate | W2 | 10 | 3.8270 | 3.8544 | 4.0430 | 0.1718 | 2.4047% |
| 1 | candidate | W3 | 10 | 3.8875 | 3.9087 | 3.9432 | 0.0345 | 0.5364% |
| 1 | candidate | W4 | 10 | 4.0346 | 4.0538 | 4.0902 | 0.0264 | 0.4331% |
| 2 | B1 | W1 | 10 | 55.1437 | 57.2997 | 59.2695 | 2.9505 | 2.8283% |
| 2 | B1 | W2 | 10 | 52.9976 | 54.9985 | 55.9432 | 0.6934 | 1.4695% |
| 2 | B1 | W3 | 10 | 50.6126 | 52.3395 | 53.7011 | 1.5662 | 2.0420% |
| 2 | B1 | W4 | 10 | 53.7664 | 55.2702 | 56.7847 | 1.9944 | 2.0638% |
| 2 | candidate | W1 | 10 | 3.8928 | 4.0034 | 4.0319 | 0.0413 | 1.0155% |
| 2 | candidate | W2 | 10 | 3.8605 | 3.8854 | 3.9020 | 0.0169 | 0.3467% |
| 2 | candidate | W3 | 10 | 3.9941 | 4.0181 | 4.0426 | 0.0296 | 0.4360% |
| 2 | candidate | W4 | 10 | 3.8795 | 3.9453 | 4.0969 | 0.1644 | 2.2642% |

Every B1 CV is below the frozen 5% ceiling.

## Warm TTFT and actual prefill

| Session | Class | B1 TTFT ms | Candidate TTFT ms | TTFT ratio | B1 prefill tok/s | Candidate prefill tok/s | Prefill ratio |
|---|---|---:|---:|---:|---:|---:|---:|
| 1 | W1 | 1758.809 | 2009.504 | 1.142537 | 32.6841 | 32.6819 | 0.999934 |
| 1 | W2 | 1755.726 | 2013.417 | 1.146771 | 30.9435 | 30.9356 | 0.999746 |
| 1 | W3 | 1850.363 | 2118.368 | 1.144839 | 29.2384 | 29.2240 | 0.999508 |
| 1 | W4 | 1756.064 | 2013.332 | 1.146503 | 32.6738 | 32.6639 | 0.999700 |
| 2 | W1 | 1760.029 | 2010.263 | 1.142176 | 32.6572 | 32.7865 | 1.003959 |
| 2 | W2 | 1756.695 | 2004.944 | 1.141316 | 30.9232 | 31.0421 | 1.003846 |
| 2 | W3 | 1851.038 | 2104.741 | 1.137059 | 29.2200 | 29.3323 | 1.003841 |
| 2 | W4 | 1756.730 | 2016.646 | 1.147955 | 32.6593 | 32.7749 | 1.003539 |

Every class in both sessions passes the frozen 1.25x TTFT and 0.80x prefill
bounds.

## Token latency

Values are the median repetition p50, median repetition p95, and maximum
observed repetition maximum, in ms.

| Session | Class | B1 p50 / p95 / max | Candidate p50 / p95 / max |
|---|---|---:|---:|
| 1 | W1 | 16.304 / 25.558 / 47.848 | 244.961 / 258.589 / 1153.036 |
| 1 | W2 | 17.251 / 26.320 / 46.240 | 261.992 / 267.297 / 1311.151 |
| 1 | W3 | 18.523 / 26.150 / 50.538 | 256.940 / 270.891 / 839.551 |
| 1 | W4 | 17.097 / 27.368 / 43.620 | 248.652 / 262.361 / 655.215 |
| 2 | W1 | 16.336 / 25.611 / 48.120 | 250.527 / 265.533 / 1184.578 |
| 2 | W2 | 17.265 / 26.358 / 46.223 | 259.657 / 264.752 / 1326.718 |
| 2 | W3 | 18.496 / 26.148 / 50.520 | 249.677 / 263.275 / 822.616 |
| 2 | W4 | 17.077 / 27.378 / 43.426 | 256.103 / 269.364 / 680.280 |

## Startup, cold behavior, capacities, and supplementary arm

| Session | B1 M-start s | Candidate M-start s | KV-matched B1 M-start s |
|---|---:|---:|---:|
| 1 | 79.280 | 158.504 | 79.245 |
| 2 | 79.252 | 158.553 | 79.254 |

The candidate was about 2.00x at startup and about 79.3 seconds slower, so
neither frozen startup-caveat trigger (>3x or >180 seconds absolute) fired.
The first W1 generation after launch measured B1/candidate at
55.8339/3.9680 tok/s and 2116.54/7505.02 ms TTFT in Session 1, and
55.8552/3.8849 tok/s and 2124.27/7498.39 ms TTFT in Session 2. These are
supporting M-cold observations; M-warm above is gating.

B1 resolved 17,091 KV tokens; the candidate resolved 17,075. The predeclared
supplementary B1 arm therefore ran at 17,075 in both sessions. Its W1–W4
decode medians were 57.3188, 55.0046, 52.3483, 55.2840 tok/s in Session 1
and 57.3064, 55.0032, 52.3555, 55.2236 tok/s in Session 2. It confirms that
the 16-token capacity difference does not explain the candidate result; the
supplementary arm is not substituted for the canonical B1 verdict baseline.

B1 and the supplementary arm resolved 3,774 GPU0 expert-cache slots with
CUDA graph capture active (`max_bs=1`). The candidate resolved 3,774 GPU0
slots plus 5,442 static GPU1 slots, CUDA graphs disabled (`max_bs=0`),
host-staged transport, and overlapping local/remote execution. No
graph-disabled baseline diagnostic was measured, so graph cost cannot support
ITERATE remediation arithmetic.

## Canonical mechanism gates

The following values are identical across the two deterministic sessions.

| Class | F1 GPU1 byte share | F2 routes on GPU1 | F3 dispatch actual/expected | F5 expert-weight H2D | F6 selected/executed; fallback/failure |
|---|---:|---:|---:|---:|---:|
| W1 | 59.0495% | 356,547/1,635,200 = 21.8045% | 156,962/156,962 | 0 bytes; ratio 0 | 356,547/356,547; 0/0 |
| W2 | 59.0495% | 595,047/1,635,200 = 36.3899% | 187,195/187,195 | 0 bytes; ratio 0 | 595,047/595,047; 0/0 |
| W3 | 59.0495% | 188,216/816,000 = 23.0657% | 80,789/80,789 | 0 bytes; ratio 0 | 188,216/188,216; 0/0 |
| W4 | 59.0495% | 85,436/406,400 = 21.0226% | 38,498/38,498 | 0 bytes; ratio 0 | 85,436/85,436; 0/0 |

F1, F2, F3, F5, and F6 pass every class/session; F4 passes via C1/C2. Remote
prefill dispatches were zero. The reported total host→GPU1 transport ratios,
which include activation/payload traffic rather than expert weights, were
0.1031%, 0.0737%, 0.1006%, and 0.1056% of hypothetical streamed expert
weights for W1–W4, themselves below 1%; the F5 expert-weight numerator is
strictly zero.

## Instrumentation control and raw evidence

Every plan and provenance record froze a 300.0-second server operation budget
and 305.0-second HTTP-client wait. Timing capacity was 5,120 steps; all
populations were complete, valid, overlapping, and untruncated. There were no
control-plane failures. The largest conservative runner-side snapshot elapsed
upper bound was 155.666 seconds (Session 1 candidate W2), measured from the
last generation completion timestamp to the resulting block artifact mtime;
it is an upper bound, not a fabricated request-duration field.

The deterministic [analysis artifact](data/p6-analysis.json) has SHA-256
`aed7b7849f0083efe9fc43bd84325330bdeab168626fb84cb80d41156bc09703`.
Exact [generation observations](data/raw/) and the
[SHA manifest](data/p6-evidence-sha256.json), itself SHA-256
`fb5e5120b97525036f736167b157afa3cada797fb5c7fcf2fe0d1441f756cfd5`,
are published with the analysis implementation. The SHA manifest references
the externally preserved multi-gigabyte mechanism snapshots by absolute path
and exact runner-indexed hash. The complete-layer interpretation is in
[p6-complete-layer-breakdown.md](p6-complete-layer-breakdown.md); the formal
decision is in [phase1-go-no-go-report.md](phase1-go-no-go-report.md).
