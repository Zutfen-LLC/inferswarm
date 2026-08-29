# Phase-1 placement methodology correction — v2

```
Status: FROZEN BEFORE PHASE-1 PERFORMANCE
Supersedes for the canonical candidate: phase1-qwen36-placement-v1
Canonical policy: phase1-qwen36-placement-v2
Canonical placement: coverage_constrained_complement_5442
Artifact SHA-256: 2f62bb84df40d4cc5649e940a39cb53d2975eadecbc320fb97d2b037d4e005f4
Related issues: #4 and #5
```

This amendment corrects a pre-performance methodology defect in the first
Phase-1 placement. It does not optimize a measured candidate and changes no
mechanism, correctness, performance, or workload gate. The historical v1
policy, artifact, checksum, validation, and physical PR #9 evidence remain
part of the experiment record.

## What went wrong

V1 required GPU 1's 5,442 identities to be completely disjoint from the
3,774-slot static GPU-0 primary proxy. The already-frozen P0-I routing evidence
showed that the whole universe outside that proxy contained only 17.3827% of
W1 route mass, 18.1327% of W3, and 16.3194% of W4. A completely disjoint bank
therefore could not satisfy the predeclared F2 requirement of at least 20% in
each workload class.

The v1 artifact faithfully implemented its policy. Its calculated aggregate
coverage and PR #9's later noncanonical physical mechanism observations made
the contradiction visible:

| Class | [CALCULATED] v1 P0-I coverage | [MEASURED] PR #9 v1 F2 |
| --- | ---: | ---: |
| W1 | 17.2736% | 16.2965% |
| W2 | 30.5138% | 30.4250% |
| W3 | 18.0912% | 19.0184% |
| W4 | 16.2886% | 16.8135% |

The P4 smoke exposed the contradiction; none of its observations was used to
choose v2.

The statement in
[`phase1-placement-validation.md`](phase1-placement-validation.md) that v1
provided "ample selected-route geometry for the Phase-1 mechanism gates" is
explicitly corrected: v1 did not provide viable F2 geometry for W1, W3, or W4.

## Pre-performance firewall

At the time v2 was derived and frozen, none of the following existed for a
canonical Phase-1 candidate:

- canonical candidate throughput or tokens/s;
- canonical candidate TTFT;
- a candidate prefill-speed ratio;
- aggregate candidate speedup;
- a removable graph-cost estimate;
- a patched-P2P result;
- a GO, ITERATE, or NO-GO performance verdict.

The only inputs to v2 were the already-frozen canonical P0-I source artifacts.
No Phase-1 output, timing, F2 observation, or other runtime evidence entered
the derivation.

## Immutable source and geometry

V2 verifies and pins the same P0-I provenance as v1:

| Source | SHA-256 |
| --- | --- |
| workload manifest | `10f81e5418a71a68f387632de422c3337cc7ba0518111a8746ad856d0210b24a` |
| `run.json` | `1ecd14c8c157eb6cde62f8514b8f2af82a36dfe69e3a7241f5be6c9908e539dc` |
| `exact-routing.jsonl` | `4071e2bfd3c18f39e5c5a0b5ff8913ca0fb99b843cf7abca0ecc1f4ebd0a252f` |
| `cache-pressure.jsonl` | `f02d96a079a6af94b3fec9d2c571322a1274cd408a3a9ff2ef162f538babab3a` |

The model remains `nvidia/Qwen3.6-35B-A3B-NVFP4` at revision
`491c2f1ea524c639598bf8fa787a93fed5a6fbce`. The fixed geometry remains:

- 40 MoE layers and 256 experts per layer;
- 10,240 expert identities;
- a 3,774-slot static GPU-0 primary proxy;
- exactly 5,442 GPU-1 slots;
- 1,775,616 bytes per slot;
- a 9,663,676,416-byte remote budget;
- exactly 9,662,902,272 resident expert bytes.

F2 remains at least 20% independently for W1, W2, W3, and W4. Workloads,
ranking, tie-breaks, all correctness tolerances, and every performance
criterion are unchanged.

## Deterministic correction

For identity `s` and workload class `c`, v2 retains v1's exact score:

```
p_c(s) = measured selections of s in c / total measured selections in c
score(s) = mean(p_W1(s), p_W2(s), p_W3(s), p_W4(s))
```

It retains the exact sort: score descending, total raw measured selections
descending, then flat ID ascending. If `ordered` is that 10,240-identity rank,
`A = 3774`, `R = 5442`, and `o` is an integer overlap, then:

```
candidate(o) = ordered[A - o : A - o + R]
```

V2 selects the smallest `o` for which every one of the ten measured exact
routing repetitions in every W1-W4 class has static remote coverage at least
0.20. This is a one-dimensional rank-window correction. It uses no optimizer,
stochastic search, new score, manual substitution, P4 observation, or
candidate timing.

The selected result is:

- [CALCULATED] `o* = 528` primary-proxy tail identities;
- [CALCULATED] rank window `[3246, 8688)`;
- [CALCULATED] 4,914 v1 complement identities retained;
- [CALCULATED] 528 lowest-ranked v1 complement identities displaced;
- [CALCULATED] 528 lowest-ranked primary-proxy identities admitted;
- [CALCULATED] 528 / 5,442 = 9.7023% of the remote bank overlaps the proxy;
- [CALCULATED] 528 / 3,774 = 13.9905% of the proxy tail is admitted.

Minimality is witnessed by `o = 527`: W4 repetition 9 covers only
8,120 / 40,640 = 19.980315%, so it does not qualify. At `o = 528`, that same
repetition covers exactly 8,128 / 40,640 = 20.000000%.

## Frozen P0-I coverage evidence

All values in this section are **[CALCULATED]** from the frozen measured P0-I
count histograms. They are placement geometry, not physical runtime evidence
or a performance prediction.

| Class | Selected routes | Total routes | Aggregate coverage | Minimum repetition | Maximum repetition |
| --- | ---: | ---: | ---: | ---: | ---: |
| W1 | 356,547 | 1,635,200 | 21.804489% | 21.039628% | 22.630259% |
| W2 | 595,047 | 1,635,200 | 36.389861% | 34.808586% | 38.151908% |
| W3 | 188,216 | 816,000 | 23.065686% | 22.386029% | 24.488971% |
| W4 | 85,436 | 406,400 | 21.022638% | 20.000000% | 22.064469% |
| **Global** | **1,225,246** | **4,492,800** | **27.271323%** | — | — |

The sanitized artifact contains the numerator, denominator, and coverage for
all 40 individual repetitions as well as aggregate comparisons against v1,
the primary proxy, and the global-hot diagnostic placement.

## Runtime meaning of overlap

Primary-proxy overlap is not proof that runtime expert weights are duplicated,
and it never means an expert executes twice. The primary proxy is a static
placement model; GPU 0 remains FreeToken's dynamic LRU. A weight copy may be on
both devices if that dynamic cache happens to contain an identity resident in
the static GPU-1 bank.

P3/P4 route ownership remains exclusive: every selected route executes exactly
once, on GPU 0 or GPU 1. GPU1-owned route positions are excluded from GPU0
service, one remote dispatch is made per selected mixed layer call, one combine
is performed, and silent fallback remains forbidden.

## Historical v1 record and supersession

`phase1-qwen36-placement-v1` remains byte-identical at SHA-256
`255dce5d335c5017de06eff54cfd1c8a0599d2dbd6c84c7fb0fb856701596a2c`.
Its policy, artifact, validation note, rationale, and PR #9 physical result are
retained as historical evidence.

V1 is superseded only as the canonical pre-performance Phase-1 candidate.
The canonical candidate now uses `phase1-qwen36-placement-v2`, placement
`coverage_constrained_complement_5442`, SHA-256
`2f62bb84df40d4cc5649e940a39cb53d2975eadecbc320fb97d2b037d4e005f4`.

The v2 artifact has no self-referential checksum. Its checksum is published in
`docs/investigations/data/phase1-placement-v2.sha256.txt`.
