# Phase 1 go/no-go report

## Executive verdict

`NO-GO`

No startup caveat applies. Both independent valid sessions mechanically
produce `NO-GO`; the worse-valid-session rule therefore also produces
`NO-GO`.

## H1

The narrow Phase-1 hypothesis is that, for the fixed same-host two-RTX-3060
configuration, statically placing a complementary set of Qwen3.6 NVFP4 MoE
experts resident on GPU1 and dispatching selected batch-1 decode expert work
over the stock host-staged transport improves warm end-to-end decode versus
the canonical one-GPU offload baseline, while preserving correctness,
mechanism fidelity, TTFT, and actual prefill bounds.

The mechanism is real and correct, but the end-to-end performance hypothesis
is rejected on this build and hardware: Session 1 `R_agg = 0.072446`
([0.071678, 0.073728]) and Session 2 `R_agg = 0.072116`
([0.071399, 0.073277]). Every class is significantly slower and below the
0.95 ITERATE floor.

## Provenance

| Identity | Exact value |
|---|---|
| FreeToken | `f29013fda7f1dcda94c6e44957d8b503795928dd`; clean tree |
| InferSwarm methodology | `14d0190eb76f39e11fcfd2e39d386ae05df78792` |
| Runner | `0.4.0` |
| Campaign identity | `1a1dda536059c8d71f9179597c46d17c65a7763d9a8875414d7ce823b1c2ec13` |
| Model revision | `nvidia/Qwen3.6-35B-A3B-NVFP4@491c2f1ea524c639598bf8fa787a93fed5a6fbce` |
| Placement SHA-256 | `2f62bb84df40d4cc5649e940a39cb53d2975eadecbc320fb97d2b037d4e005f4` |
| Workload SHA-256 | `10f81e5418a71a68f387632de422c3337cc7ba0518111a8746ad856d0210b24a` |
| GPU0/GPU1 | `GPU-d5c05739-96c1-7e49-89b6-bf54c2121c55` / `GPU-e1f2f90c-49ab-2689-0cf1-e5d9da520176` |
| Transport | stock-driver host-staged; no patched P2P |
| Prerequisite manifest SHA-256 | `67e3cf67465687ec0ac1b99517110a31668d4638334cea58d25385e371c9fa91` |

The previous incomplete `44b3ddfc…` campaign remains historical control-plane
evidence only. No observation, baseline, thermal state, campaign identity, or
prerequisite from it enters this result.

## Qualification

The two fresh-server reference-v2 captures are byte-identical, both SHA-256
`113b5cd5335e244265cf543ef89f87708ad1d6e1f07b260c72ad0e57e72069a0`.
For W1–W4 their complete sequences, first 64 tokens, step-0 argmax, and
step-0 top-5 are exact; full logits pass `rtol=atol=2e-3` with observed max
absolute and relative deviation 0; NaN/Inf counts are zero. Session A is the
canonical reference.

The exact-build candidate C1–C4 artifact SHA-256 is
`1904345b79531a91c261a94396e2dd71350b874f8a9a3ee5bc53a14fdfc84b7f`:
C1 passes at `2e-3/2e-3` with max absolute/relative deviation 0; C2 ownership,
routing, and placement arithmetic are exact; C3 first 64, argmax, top-5, full
logits, and complete sequences are exact in every class; C4 has zero NaN/Inf.

P2/P3/P4 requalification SHA-256 is
`510ec3e90d733067da5be8d48f3ad17b8b31de27f3835ace36b227187f115efc`.
It passes the exact placement, 5,442 slots, 9,662,902,272 GPU1 expert bytes,
source/layout verification, native Triton NVFP4 shape, device restoration,
zero steady expert-weight H2D, local/remote/mixed execution, exact combine and
ownership, one dispatch boundary, zero remote prefill/fallback/failure, and
complete W1–W4 overlap/timing gates.

Software sanity passed with only the reviewed, pre-existing collection and
Ruff exceptions. FreeToken remained unmodified.

## Mechanism

| Gate | Campaign observation | Result |
|---|---|---|
| F1 | GPU1 owns 9,662,902,272 of 16,364,077,056 combined expert-cache bytes = 59.0495% in every block | PASS |
| F2 | GPU1 route fractions W1–W4 = 21.8045%, 36.3899%, 23.0657%, 21.0226% in each session | PASS |
| F3 | Actual/expected dispatches W1–W4 = 156,962/156,962; 187,195/187,195; 80,789/80,789; 38,498/38,498, zero mismatches | PASS |
| F4 | C1 combined output and C2 reconstruction/ownership exact | PASS |
| F5 | Steady host→GPU1 expert-weight bytes = 0; expert-weight streaming ratio = 0 (<1%) | PASS |
| F6 | Selected equals executed in every class; zero fallback and explicit failure | PASS |

Remote prefill is zero, overlap is active, and all 5,120-step-capacity timing
populations are valid and untruncated. Mechanism gates establish that this is
a valid test of H1; they do not compensate for the slow result.

## Session 1

Session 1 ran B1 → candidate → required KV-matched B1 and finished
`COMPLETE` / `VALID`. The campaign-build baseline identity gate passed.
All baseline CVs pass: W1 2.8199%, W2 1.4485%, W3 2.0549%, W4 2.0919%.

| Class | B1 tok/s | Candidate tok/s | `R_c` | 95% CI | TTFT ratio | Prefill ratio |
|---|---:|---:|---:|---:|---:|---:|
| W1 | 57.285940 | 4.105904 | 0.071674 | [0.068661, 0.073756] | 1.142537 | 0.999934 |
| W2 | 55.000636 | 3.854352 | 0.070078 | [0.069527, 0.073324] | 1.146771 | 0.999746 |
| W3 | 52.300641 | 3.908679 | 0.074735 | [0.074112, 0.076995] | 1.144839 | 0.999508 |
| W4 | 55.243938 | 4.053848 | 0.073381 | [0.071863, 0.075101] | 1.146503 | 0.999700 |

`R_agg = 0.072446`, 95% CI `[0.071678, 0.073728]`. Each `R_c`
interval excludes 1.000 on the slower side. TTFT and actual-prefill bounds
pass every class. Independent Session-1 verdict: `NO-GO`.

## Session 2

After an independently observed thermal reset, Session 2 ran candidate → B1
→ required KV-matched B1 and finished `COMPLETE` / `VALID`. The runner
verified the Session-1 artifact SHA index and required set, exact campaign
identity, campaign-build baseline gate, and later B1 revalidation. No B1 drift
was found. Baseline CVs pass: W1 2.8283%, W2 1.4695%, W3 2.0420%, W4
2.0638%.

| Class | B1 tok/s | Candidate tok/s | `R_c` | 95% CI | TTFT ratio | Prefill ratio |
|---|---:|---:|---:|---:|---:|---:|
| W1 | 57.299742 | 4.003418 | 0.069868 | [0.067628, 0.071681] | 1.142176 | 1.003959 |
| W2 | 54.998495 | 3.885417 | 0.070646 | [0.070019, 0.071135] | 1.141316 | 1.003846 |
| W3 | 52.339485 | 4.018068 | 0.076769 | [0.076167, 0.079015] | 1.137059 | 1.003841 |
| W4 | 55.270190 | 3.945253 | 0.071381 | [0.069835, 0.074889] | 1.147955 | 1.003539 |

`R_agg = 0.072116`, 95% CI `[0.071399, 0.073277]`. Each `R_c`
interval excludes 1.000 on the slower side. TTFT and actual-prefill bounds
pass every class. Independent Session-2 verdict: `NO-GO`.

## End-to-end result

The two sessions were analyzed independently with 10,000 unpaired bootstrap
resamples, RNG seed 0, and no repetition deletion. Both are valid and
significantly slower. Since both independent verdicts are `NO-GO`, the frozen
worse-valid-session rule yields `NO-GO`.

The required KV-matched supplementary arms completed because B1 resolved
17,091 KV tokens and the candidate 17,075. Pinning B1 to 17,075 retained
52.35–57.32 tok/s across sessions/classes, so it does not change the primary
decision and is not substituted into the canonical ratio.

Candidate startup was 158.50/158.55 seconds versus B1 79.28/79.25 seconds.
It triggers neither >3x nor >180-second startup bound, so the verdict has no
startup caveat.

## Issue #5

The full measured breakdown is published in
[p6-complete-layer-breakdown.md](p6-complete-layer-breakdown.md). The
independent median complete-layer wall is 0.233472 ms for B1 and
3.611648–3.786752 ms for the candidate. Candidate component evidence includes
classification/control, GPU0→host activation/routing staging, host submission,
payload H2D, GPU1 route-contribution execution, result D2H, join, returned
contribution H2D, reconstruction, final reduction, and the GPU0 local branch.

The named measured source-grounded cost is the
`inferswarm_remote_decode.py` host submission path
(`host_remote_submit_control`, median 0.677–0.698 ms). It is real, but neither
it nor another single measured removable cost has bounded arithmetic capable
of moving an approximately 0.07 aggregate ratio above 1.20. The local and
remote branches overlap, so no component sum is used as wall time. A
graph-disabled B1 diagnostic was not measured, so disabled graphs cannot be
used as an ITERATE explanation.

## Section 8

`INCONCLUSIVE`

The canonical schema lacks per-touch expert identity joined to baseline
pre-touch local-hit/non-local state. `MATCHED_NONLOCAL_TOUCH_SET`, the required
census, `REMOTE_INTRINSIC`, and `BASE_NONLOCAL_SERVICE` therefore cannot be
proven without forbidden aggregate apportionment. No touch-level resampling
or substitute comparison was performed. Rule B/N5 does not fire; this
diagnostic neither rescues nor replaces the end-to-end result.

## Mechanical criteria table

`PASS` means the named predicate is satisfied. For N-rules, `PASS` means that
the NO-GO condition fires.

| Rule | Session 1 | Session 2 | Mechanical finding |
|---|---|---|---|
| G1 | PASS | PASS | F1–F6 pass |
| G2 | PASS | PASS | C1–C4 pass |
| G3 | PASS | PASS | both sessions complete, no early stop, all B1 CV ≤5% |
| G4 | FAIL | FAIL | `R_agg` and CI floor are far below 1.20/1.10 |
| G5 | FAIL | FAIL | no class reaches 1.05; all are significantly slower |
| G6 | PASS | PASS | every TTFT/prefill ratio is in bounds |
| G7 | PASS | PASS | complete-layer evidence exists for both arms |
| I1 | PASS | PASS | required mechanism/correctness gates pass |
| I2 | PASS | PASS | G3 reproducibility passes |
| I3 | PASS | PASS | Issue #5 evidence exists |
| I4 | PASS | PASS | named measured host-submission path identified |
| I5 | FAIL | FAIL | no bounded removal moves `R_agg > 1.20` |
| I6 | FAIL | FAIL | no qualifying single next experiment follows from I5 |
| I7 | FAIL | FAIL | every class is below 0.95 |
| ITERATE A | FAIL | FAIL | aggregate is below 1.05, not in [1.05, 1.20) |
| ITERATE B | FAIL | FAIL | §8 is inconclusive; Rule A is not established |
| ITERATE C | FAIL | FAIL | no class has a significant ≥1.20 benefit |
| ITERATE D | FAIL | FAIL | decode fails G4/G5; TTFT/prefill pass |
| ITERATE E | FAIL | FAIL | I5 remediation arithmetic is absent |
| N1 | FAIL | FAIL | correctness is maintained |
| N2 | FAIL | FAIL | intervals exclude 1.000, on the slower side |
| N3 | PASS | PASS | `R_agg < 1.05` and no ITERATE case |
| N4 | PASS | PASS | candidate is below 1.00 beyond noise |
| N5 | FAIL | FAIL | §8 Rule-B preconditions cannot be proven |
| N6 | PASS | PASS | all four classes show no significant gain |
| N7 | FAIL | FAIL | no artificial user-inaccessible gain is claimed |
| N8 | FAIL | FAIL | there is no apparent microbenchmark gain claimed as end-to-end gain |
| N9 | PASS | PASS | every class regresses below 0.95 and I7 fails |
| §8 diagnostic | INCONCLUSIVE | INCONCLUSIVE | matched non-local touch set cannot be constructed |

N3, N4, N6, and N9 independently fire in both valid sessions. GO fails G4
and G5. ITERATE fails I5, I6, I7, and every defined case. The mechanical
result is therefore `NO-GO`.

## Claims boundary

This result addresses only the tested mechanism: same-host, two RTX 3060s,
NVFP4, static placement, stock host-staged transport, remote decode experts,
batch 1, and Qwen3.6-35B-A3B. It does not prove or disprove network execution,
1 GbE viability, scaling beyond two GPUs, heterogeneous vendors, other
quantizations, dense-model execution, or a generalized InferSwarm runtime
architecture.

Raw generation observations, exact external mechanism-snapshot paths and
hashes, deterministic analysis output, and reproduction metadata are in
[data/](data/). The raw external campaign remains byte-for-byte preserved.
