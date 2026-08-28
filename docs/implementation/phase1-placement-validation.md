# Phase-1 placement validation — `phase1-qwen36-placement-v1`

```
Status: VALIDATED BEFORE PHASE-1 PERFORMANCE
Policy: phase1-qwen36-placement-v1
Source: canonical P0-I routing evidence
Canonical remote placement: complement_5442
```

> **Correction / historical status (2026-08-28).** This v1 validation remains
> intact as historical evidence, including its artifact SHA and calculated
> coverage. Its final claim of "ample selected-route geometry" was wrong:
> W1, W3, and W4 are below the independently predeclared 20% F2 floor. V1 is
> superseded for the canonical pre-performance candidate by
> [`phase1-qwen36-placement-v2`](phase1-placement-methodology-correction-v2.md).
> No canonical Phase-1 candidate performance had been observed before that
> correction was frozen.

This note records the mechanical validation of the generated Phase-1 placement artifact before any Phase-1 candidate throughput exists. It is subordinate to `phase1-placement-policy.md` and does not change the predeclared placement rule.

## Publication integrity

The host-generated sanitized artifacts have these SHA-256 values:

- `p0i-routing-histogram.json`: `f9363f786dac48d99ebf02600618d3f5294855a0aeb09690d16af61b16a96e18`
- `phase1-qwen36-placement-v1.json`: `255dce5d335c5017de06eff54cfd1c8a0599d2dbd6c84c7fb0fb856701596a2c`

The histogram source pins the canonical P0-I raw evidence:

- `run.json`: `1ecd14c8c157eb6cde62f8514b8f2af82a36dfe69e3a7241f5be6c9908e539dc`
- `exact-routing.jsonl`: `4071e2bfd3c18f39e5c5a0b5ff8913ca0fb99b843cf7abca0ecc1f4ebd0a252f`
- `cache-pressure.jsonl`: `f02d96a079a6af94b3fec9d2c571322a1274cd408a3a9ff2ef162f538babab3a`

## Mechanical invariants

Validation of the generated histogram and placement confirms:

- exactly 10,240 histogram identities, one for every flat id `0..10239`;
- class route totals reproduce W1 = 1,635,200, W2 = 1,635,200, W3 = 816,000, W4 = 406,400;
- `gpu0_primary_proxy_3774` contains exactly 3,774 unique identities;
- `global_hot_5442` contains exactly 5,442 unique identities;
- canonical `complement_5442` contains exactly 5,442 unique identities;
- the primary proxy and canonical complement have intersection size zero;
- the primary proxy plus canonical complement contain exactly 9,216 identities = 90.00% of the 10,240-slot expert pool;
- every stored identity satisfies `flat_id = layer * 256 + expert_id`, with layer `0..39` and expert `0..255`;
- the emitted rank order exactly reproduces the policy ordering: workload-balanced score descending, then total raw count descending, then flat id ascending;
- the canonical complement exactly equals the first 5,442 ranked identities after removing the first 3,774 primary-proxy identities;
- `5,442 * 1,775,616 = 9,662,902,272` expert-bank bytes, within the frozen 9-GiB remote budget of 9,663,676,416 bytes.

## Calculated trace coverage

These values are **[CALCULATED]** directly from the **[MEASURED]** W1-W4 exact-routing counts. They are static trace coverage, not a prediction of runtime cache hit rate or two-GPU throughput.

| Placement | Slots | Global trace coverage | W1 | W2 | W3 | W4 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| GPU-0 primary proxy | 3,774 | 77.7002% | 82.6173% | 69.2173% | 81.8673% | 83.6806% |
| Global-hot diagnostic | 5,442 | 90.1315% | 92.7874% | 85.2209% | 92.7537% | 93.9387% |
| Canonical GPU-1 complement | 5,442 | 22.1519% | 17.2736% | 30.5138% | 18.0912% | 16.2886% |
| **Primary proxy + canonical complement** | **9,216** | **99.8521%** | **99.8909%** | **99.7311%** | **99.9585%** | **99.9692%** |

Only 6,645 of 4,492,800 measured routed selections fall on the 1,024 expert identities outside the combined static geometry. By class the uncovered selections are W1 = 1,784, W2 = 4,397, W3 = 339, W4 = 125.

This is a strong mechanism-geometry result: the two fixed capacity sets cover 90% of expert identities but 99.8521% of the measured route demand. It does **not** mean the Phase-1 runtime will achieve a 99.8521% hit rate, because GPU 0 remains FreeToken's dynamic LRU rather than being replaced by the static primary proxy.

## Why the canonical placement uses a primary proxy

P0-I v1 records exact selected expert identities and exact aggregate/per-layer hit/miss counters, plus the expert identities resident at observation boundaries. It does not record per-expert miss identity or the complete LRU timestamp ordering at the start of each measured repetition. Therefore the existing artifact cannot mechanically rank experts by observed GPU-0 miss frequency without inventing state that was not recorded.

The frozen policy consequently uses the best reproducible evidence available without another experiment: an equal-workload-class static primary-capacity proxy, followed by a non-overlapping secondary complement. This satisfies the Phase-1 plan's intent to avoid deliberately duplicating likely-cheap GPU-0 service while keeping the placement deterministic and pre-performance.

A later placement experiment may add per-expert miss telemetry and compare a miss-weighted policy, but it cannot replace `phase1-qwen36-placement-v1` inside the first canonical Phase-1 campaign after candidate throughput is observed.

## Verdict

**HISTORICAL VALIDATION, SUPERSEDED FOR THE CANONICAL CANDIDATE.** The generated
artifact is a deterministic implementation of the v1 policy, but it does not
provide viable F2 geometry for W1, W3, or W4. Its rationale, bytes, SHA, and
physical PR #9 result remain part of the record. Whether any placement can
improve end-to-end inference remains **[SPEC]** until an authorized canonical
performance campaign; no such candidate performance informed v2.
