# Phase 1 P6 complete-layer breakdown

**Evidence class:** MEASURED

**Issue:** #5

**Campaign identity:** `1a1dda536059c8d71f9179597c46d17c65a7763d9a8875414d7ce823b1c2ec13`

This is the complete MoE-layer evidence for both primary arms of the valid
P6 campaign. All durations are measured at the authoritative schema boundary.
The two candidate branches overlap; component durations are therefore never
summed or presented as layer wall time. The independently measured
`complete_layer` field is the only full-layer wall measure. Absolute clocks
from GPU0 and GPU1 are not compared.

## Population validity

| Session | Class | Steps observed/retained | Layer records retained | Capacity | Truncated | Complete/component valid | Overlap |
|---|---|---:|---:|---:|---|---|---|
| 1 | W1 | 5,110/5,110 | 204,400 | 5,120 | no | yes/yes | active |
| 1 | W2 | 5,110/5,110 | 204,400 | 5,120 | no | yes/yes | active |
| 1 | W3 | 2,550/2,550 | 102,000 | 5,120 | no | yes/yes | active |
| 1 | W4 | 1,270/1,270 | 50,800 | 5,120 | no | yes/yes | active |
| 2 | W1 | 5,110/5,110 | 204,400 | 5,120 | no | yes/yes | active |
| 2 | W2 | 5,110/5,110 | 204,400 | 5,120 | no | yes/yes | active |
| 2 | W3 | 2,550/2,550 | 102,000 | 5,120 | no | yes/yes | active |
| 2 | W4 | 1,270/1,270 | 50,800 | 5,120 | no | yes/yes | active |

The full populations, not sampled or truncated subsets, produce every
summary below.

## Independently measured complete-layer wall

All values are milliseconds. The median is the primary description; p95 and
max expose the full-population tail. Maxima are observations, not values
summed from components.

| Session | Class | Arm | n | Min | Median | p95 | Max |
|---|---|---|---:|---:|---:|---:|---:|
| 1 | W1 | B1 | 204,400 | 0.082944 | 0.233472 | 0.538624 | 1.571840 |
| 1 | W1 | candidate | 204,400 | 1.717248 | 3.611648 | 3.822592 | 596.742144 |
| 1 | W2 | B1 | 204,400 | 0.082944 | 0.233472 | 0.690176 | 1.569792 |
| 1 | W2 | candidate | 204,400 | 1.715200 | 3.708928 | 3.762176 | 1075.530752 |
| 1 | W3 | B1 | 102,000 | 0.082944 | 0.233472 | 0.676915 | 1.547264 |
| 1 | W3 | candidate | 102,000 | 1.724416 | 3.786752 | 3.870720 | 463.472640 |
| 1 | W4 | B1 | 50,800 | 0.082944 | 0.233472 | 0.688179 | 1.571840 |
| 1 | W4 | candidate | 50,800 | 1.794048 | 3.698688 | 3.795968 | 423.368704 |
| 2 | W1 | B1 | 204,400 | 0.082944 | 0.233472 | 0.538624 | 1.585152 |
| 2 | W1 | candidate | 204,400 | 1.801216 | 3.721216 | 3.840000 | 597.279744 |
| 2 | W2 | B1 | 204,400 | 0.082944 | 0.233472 | 0.690176 | 1.579008 |
| 2 | W2 | candidate | 204,400 | 1.789952 | 3.688448 | 3.759104 | 1082.278912 |
| 2 | W3 | B1 | 102,000 | 0.082944 | 0.233472 | 0.677888 | 1.556480 |
| 2 | W3 | candidate | 102,000 | 1.785856 | 3.679232 | 3.763200 | 455.643136 |
| 2 | W4 | B1 | 50,800 | 0.082944 | 0.233472 | 0.688128 | 1.545216 |
| 2 | W4 | candidate | 50,800 | 1.785856 | 3.757056 | 3.932160 | 438.501376 |

The candidate median full-layer wall is 15.47–16.22 times the B1 median,
consistent in direction with the measured end-to-end decode result. This is
a descriptive wall-time comparison, not a replacement for `R_c` or `R_agg`.

## Baseline components

Median ms are shown. Baseline GPU1/remote, join, reconstruction, and final
candidate reduction fields are schema-authoritatively `not_applicable`, not
zero. GPU0 expert fetch is the measured host→GPU0 expert-weight service where
applicable.

| Session | Class | Route/cache service | Host→GPU0 expert fetch | GPU0 expert execution | Complete local branch | Complete layer wall |
|---|---|---:|---:|---:|---:|---:|
| 1 | W1 | 0.006144 | 0.148480 | 0.075776 | 0.231424 | 0.233472 |
| 1 | W2 | 0.006144 | 0.148480 | 0.075776 | 0.232448 | 0.233472 |
| 1 | W3 | 0.006144 | 0.149504 | 0.075776 | 0.232448 | 0.233472 |
| 1 | W4 | 0.006144 | 0.148480 | 0.075776 | 0.231424 | 0.233472 |
| 2 | W1 | 0.006144 | 0.148480 | 0.075776 | 0.231424 | 0.233472 |
| 2 | W2 | 0.006144 | 0.148480 | 0.075776 | 0.231424 | 0.233472 |
| 2 | W3 | 0.006144 | 0.149504 | 0.075776 | 0.231424 | 0.233472 |
| 2 | W4 | 0.006144 | 0.148480 | 0.075776 | 0.231424 | 0.233472 |

## Candidate components — Session 1

Median ms are shown. `GPU0→host act/routing` is the activation/routing
staging copy. `Staging wait` and `host submission` are separately measured
host-control intervals. `GPU1 complete` independently brackets payload H2D,
remote route-contribution execution, and result D2H on GPU1; it is not the
sum used for layer wall.

| Component | W1 | W2 | W3 | W4 |
|---|---:|---:|---:|---:|
| Classification/control | 0.048262 | 0.049904 | 0.051162 | 0.050058 |
| GPU0→host act/routing | 0.084992 | 0.087360 | 0.090528 | 0.087936 |
| Staging wait | 0.005387 | 0.005463 | 0.005733 | 0.005557 |
| Host submission | 0.677352 | 0.681181 | 0.695194 | 0.680115 |
| Host→GPU1 payload H2D | 0.084032 | 0.086048 | 0.088608 | 0.086656 |
| GPU1 route-contribution execution | 0.469312 | 0.472768 | 0.480640 | 0.472064 |
| GPU1→host D2H | 0.051200 | 0.052576 | 0.054496 | 0.052736 |
| GPU1 complete branch | 0.605568 | 0.612288 | 0.624288 | 0.611328 |
| Join/wait | 0.006791 | 0.006916 | 0.007159 | 0.006990 |
| Host→GPU0 returned contribution H2D | 0.115712 | 0.117760 | 0.120832 | 0.118784 |
| Reconstruction | 0.128000 | 0.130048 | 0.134144 | 0.131072 |
| Final MoE reduction | 0.154624 | 0.156672 | 0.160768 | 0.157696 |
| GPU0 route/cache service | 0.323584 | 0.333824 | 0.342016 | 0.332800 |
| Host→GPU0 expert fetch | 0.167936 | 0.169984 | 0.174080 | 0.169984 |
| GPU0 local expert execution | 0.588800 | 0.594944 | 0.608256 | 0.594944 |
| GPU0 complete local branch | 1.125376 | 1.146880 | 1.173504 | 1.146880 |
| **Independent complete-layer wall** | **3.611648** | **3.708928** | **3.786752** | **3.698688** |

## Candidate components — Session 2

| Component | W1 | W2 | W3 | W4 |
|---|---:|---:|---:|---:|
| Classification/control | 0.049992 | 0.049471 | 0.049467 | 0.051468 |
| GPU0→host act/routing | 0.088992 | 0.088224 | 0.088448 | 0.091328 |
| Staging wait | 0.005745 | 0.005601 | 0.005663 | 0.005930 |
| Host submission | 0.685761 | 0.677050 | 0.677115 | 0.698403 |
| Host→GPU1 payload H2D | 0.086912 | 0.086144 | 0.086304 | 0.089248 |
| GPU1 route-contribution execution | 0.476480 | 0.471360 | 0.470848 | 0.485536 |
| GPU1→host D2H | 0.052096 | 0.051360 | 0.051360 | 0.053504 |
| GPU1 complete branch | 0.616288 | 0.609504 | 0.609120 | 0.629344 |
| Join/wait | 0.007079 | 0.006919 | 0.006914 | 0.007218 |
| Host→GPU0 returned contribution H2D | 0.118784 | 0.117760 | 0.117760 | 0.121856 |
| Reconstruction | 0.130048 | 0.128000 | 0.129024 | 0.134144 |
| Final MoE reduction | 0.157696 | 0.156672 | 0.156672 | 0.161792 |
| GPU0 route/cache service | 0.336896 | 0.334848 | 0.334848 | 0.339968 |
| Host→GPU0 expert fetch | 0.172032 | 0.171008 | 0.171008 | 0.177152 |
| GPU0 local expert execution | 0.600064 | 0.591872 | 0.592896 | 0.612352 |
| GPU0 complete local branch | 1.157120 | 1.147904 | 1.147904 | 1.177600 |
| **Independent complete-layer wall** | **3.721216** | **3.688448** | **3.679232** | **3.757056** |

The machine-readable [analysis artifact](data/p6-analysis.json) retains n,
min, median, max, IQR, CV, and p95 for every valid component in every
arm/class/session. It also preserves schema `not_applicable`/unavailable
status rather than fabricating zeroes.

## Bottleneck interpretation

The source-grounded named cost is the candidate remote submission path in
`python/freetoken/moe/inferswarm_remote_decode.py`: its measured
`host_remote_submit_control` median is 0.677–0.698 ms per participating
layer/step. It enqueues payload H2D, GPU1 route-contribution execution, and
the D2H result; the separate GPU1 branch median is 0.606–0.629 ms. The
candidate GPU0 local branch is also 1.125–1.178 ms versus 0.231–0.232 ms for
B1, while the authoritative complete-layer wall is 3.612–3.787 ms versus
0.233 ms.

These observations identify real candidate costs but do not satisfy frozen
ITERATE arithmetic. Even removing the entire measured host-submission median
does not bridge a candidate end-to-end ratio near 0.07 to `R_agg > 1.20`;
components cannot be additively removed from the overlapping wall; and no
graph-disabled B1 diagnostic exists to bound the candidate's graph-disabled
cost. Consequently there is no defensible single remediation calculation or
specific qualifying next experiment under I5/I6. This is a valid slow result,
not an instrumentation or mechanism failure.

## Section 8 diagnostic

`§8 diagnostic = INCONCLUSIVE`. Canonical blocks do not expose a per-touch
expert identity joined to the baseline pre-touch `LOCAL_HIT`, `OFFLOAD_MISS`,
`CPU_SERVICE`, or `HYBRID_NONLOCAL` state. Therefore
`MATCHED_NONLOCAL_TOUCH_SET`, its census, `REMOTE_INTRINSIC`, and
`BASE_NONLOCAL_SERVICE` cannot be constructed without prohibited aggregate
apportionment. No individual expert touches were resampled, Rule B/N5 does
not fire, and §7's real end-to-end result controls the verdict.
