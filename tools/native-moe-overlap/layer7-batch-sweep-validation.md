# Layer-7 token-batch break-even sweep — local implementation validation

Base: `0c0f8022859601a784d94d7afe15387c54823a93` (origin/main, PR #345 merged).
This record concerns local synthetic CPU-loopback development only. It does not
change the completed H5 experiments, accepted native identities, project status,
or hardware authorization.

## What was built

The batched sweep extends the existing matched layer-7 benchmark along the
narrowest shape/plumbing seam the pinned H5 path allows:

- The H5 API's real batch support was inspected first. `build_qwen4exp_ffn`
  fell back to the ordinary CPU graph for any `n_tokens != 1`;
  `build_qwen4exp_ffn_hot` required one token; the executor partitioned a
  single token's ten slots. The pinned `mul_mat_id`, the source FFN builder and
  the reduction are token-generic, so batching needed shape/plumbing changes
  only: a `[10,T]` routing-boundary bind (`llama_hot_bind_routing_batch`), a
  constructor-only `benchmark_routing_batch` config field that admits multi-
  token batches at the same routing cut, `[C,T]` branch ids/weights tensors,
  `[d,10,T]` slot staging, a per-width prebuilt graph set, and batch-strided
  hot/cold partition fill. No protocol, worker, placement or residency change.
- Concrete boundary reported rather than papered over: one `mul_mat_id` per
  prebuilt branch forces a uniform hot count across a batch's tokens, so the
  sweep keeps the five hot globals fixed per batch (the resident set) and
  varies only cold-expert sets per token. Per-token *varying hot experts*
  would need grouped multi-graph dispatch per step — a runtime redesign, out
  of scope, not silently approximated.
- `--tokens 1,2,4,8,16` (bounded 1..256, ≤63-char list). Width 1 preserves the
  historical case and unsuffixed names/fields byte-compatibly. Widths >1 run
  two labeled variants: `*-varied-set` (distinct per-token cold sets — general
  behavior) and `*-shared-set` (same set per token — ideal expert reuse),
  never aggregated. Each batch is ONE H5 step over batched tensors
  (`[10,T]` routing, `[C,T]` branch payloads, `[d,10,T]` slots) — not a loop of
  single-token RPC calls.
- Timers, comparator (`legacy-cpu-unsplit/1`, mode frozen before execution),
  AB/BA alternation, warmup separation, raw per-pair records, immutable weight
  uploads, persistent connection and graph reuse are unchanged. Summaries add
  per-token latency, throughput and paired speedup as transforms of the same
  retained pair times, plus B's cumulative graph-dispatch/recompute-reuse
  counters (observable wire reuse), reset per width.

## Focused validation (canonical venv, `python -E -m unittest`)

- 21 focused tests + 3 cross-cutting smoke: **all pass** (`Layer7BenchContracts`,
  `Layer7BatchSweepContracts`, the six `test_matched_*`, batch-sweep execution
  and negative-control tests, `test_hot_candidate_builder_is_additive`).
- Full registered module `tests.test_native_moe_overlap`: **60 tests pass**
  (includes the unchanged fixture/overlay behavior suite — single-token decode,
  hot-count reuse, zero-hot transitions, wire contracts — proving no
  regression in the existing H5 path).
- Batch-sweep execution test exercises: T ∈ {1,2,4} through the real CPU/RPC-v7
  graphs, per-width rebuild (`IS314_SETUP tokens=T` per width), per-token
  routing rows (distinct-within-token, varied vs shared sets), B token binding,
  output validity under the frozen cpu-cuda gate, single setup-only compact
  upload, and non-increasing dispatch counters across all-cold steps.
- Negative controls (missing-expert, bad-partition) refuse at batched widths.
- Production-scale loopback sweep (portable build, small-test geometry guard
  bypassed by dimension budget retained): widths 1,2,4,8,16 × 10 measured
  pairs, all 18 cases valid, every output element checked, loopback worker
  reaped. Retained at `/home/zutfen/data/is346-batch-sweep/`.

## Local loopback result (NOT a performance claim)

On this development host (QEMU 8-vCPU, portable no-AVX build, 2 threads) the
sweep shows **no crossover within T ≤ 16**: B−A remains positive at every
width, shrinking per token from +0.852 ms (mixed, T=1) to +1.59 ms absolute at
T=16 (+0.100 ms/token, speedup 0.17×) — batching amortizes the fixed dispatch
cost across tokens but the loopback dispatch overhead (~0.9 ms/step) dominates
the tiny per-token expert work at these dimensions. All-cold stays ≈+0.12–0.16
ms/step. The 05→03 hardware run carries ~2.2 ms/step dispatch against real GPU
expert compute and is where a break-even could appear; distributions and
contradictory samples are retained in the run records. Batching applies to
tokens available together (prefill/independent requests); dependent decode
steps of one sequence cannot be batched, and this layer benchmark cannot
establish whole-model latency or throughput.

## Single scoped review

One scoped independent review of the diff was run; it returned **NO-GO** with a
single material finding (P2): for batched rows the supervisor validated only
the outer row count of `ids`/`weight_bits`, accepting malformed inner rows,
missing per-token routing labels, and routing hashes not re-derived from the
displayed partition — leaving batch routing attribution unverifiable. The
original verdict is preserved, not relabeled. Accepted correction (in-commit):
`validate_result` now checks ten in-range distinct IDs and finite positive
weight bits per token, requires per-token `routing_labels`, and re-derives the
row routing hash from the displayed partition using the native packing (all
ids then all weights, little-endian), refusing any drift. Two regression tests
pin the mutated-row refusals and the hash re-derivation; the historical
single-token contract fixture was updated to the same packing. No unrelated
hardening or broad refactors were added. Full transcript retained at
`/home/zutfen/data/is346-batch-sweep/reviews/scoped-review-transcript.log`.

## Remaining limitations

No SSH/GPU execution, model download, full-model hashing, worker/protocol
change, placement-policy change, installation, identity promotion or hosted
validation was performed. The portable-fixture loopback numbers are not CPU05
or GPU03 performance evidence. The three acknowledged SET round trips per step
(#345) remain per-step costs at every width; batching amortizes them per token
but does not remove them. Per-token varying hot experts, width interleaving
and captured-routing batch extraction remain out of scope.
