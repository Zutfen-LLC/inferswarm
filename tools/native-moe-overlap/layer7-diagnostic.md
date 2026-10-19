# Layer-7 pair 13 diagnostic

This is opt-in diagnostic support for the PR #346 producer at
`5a28198f7f514b22e01e8204dc5499a173b0f569`. It makes no performance claim.
The original mixed-varied-set T=2 measured pair 13 verdict remains **INVALID**.
The supplied failure report gives ratio 1.136 and max_abs 2.31e-6. The 2.89e-6
value belongs to passing pair 3. These are historical reported values, not
new observations from this change. No implementation defect or CUDA
accumulation cause has been established.

## Options and capture

`layer7_bench.py --failure-dump` captures the first pair that fails a numerical,
partition, shared, or expert check. The default creates no capture and keeps the
existing result fields and comparison behavior. `--diagnostic-pair13` selects
the fixed original prefix and captures its target even if the target passes.
Both options pass through to `native-layer7-bench`. Use the bounded supervisor
for execution because the pinned RPC transport has no socket deadline.

The one fresh `native/capture/` directory contains raw little-endian tensors and
`manifest.json`. Each tensor entry has its GGML type and name, four dimensions,
byte strides, length and SHA-256. Float files preserve all F32 bits, including
nonfinite values. The payload limit is 16 MiB; metadata is limited to 64 KiB.
`--dump-max-bytes` can lower the payload limit. A refused or incomplete capture
is explicit in the pair row. It cannot turn a failed comparator into PASS.
An enabled diagnostic whose capture fails also exits nonzero.

Capture reads run after both arms synchronize and outside the total timers.
There is no extra graph computation, allocation flag, arithmetic, scheduling,
or synchronization change in the executor. A read-only accessor exposes the
existing mixed-path tensors before the next step or graph rebuild. Remote
hot-input/routing reads add untimed GETs only when a capture is selected.

The capture contains:

- A input and B's internal consumed input snapshot; B's remote hot input.
- A and B consumed IDs and F32 routing weights. Raw files retain weight bits.
- B hot compact IDs/weights and cold global IDs/weights.
- A and B output vectors, A's ten weighted planes, B's ten weighted planes
  after the existing slot restoration, and A/B shared outputs.
- Original token/slot to global expert, hot/cold branch slot and compact hot
  expert mapping. Weighted tensors use `[d,10,T,1]`, coordinate fastest.
- Separate `max_abs_at` and `max_ratio_at` records from the actual comparator:
  token, coordinate, flat output index, A, B, error, L1 scale, tolerance and ratio.
  Ties select the first flat index. Nonfinite comparisons have null locations.
- The original pair row and hashes of `weights.json`, `spec.json` and
  `assigned.txt`. The supervisor retains those files and candidate provenance.

B weighted planes are the exact host staging slots consumed by the native
reduction. The original slot mapping distinguishes hot and cold planes. This
supports an offline per-expert/shared/reduction decomposition. It does not
capture CUDA operands before matmul or independently qualify the arithmetic.
B's all-cold fast graph does not retain weighted/shared intermediates. Those
observations are explicitly unavailable for an all-cold capture; stale mixed
buffers are never substituted. No production instrumentation framework is added.

The empirical `legacy-cpu-unsplit/1` gate, `2^-7` cross-backend L1 headroom,
near-zero fallback, and INVALID exit remain unchanged. Repeated output hashes
show reproducibility; they do not exclude deterministic stale buffers.
All-cold equality alone does not localize mixed residuals.

## Exact selection and history

The selector fixes seed 314159, 5 warm pairs, 20 original measured indexes,
synthetic routing, and the original width allocation list `1,2,4,8,16`.
Conflicting selection arguments are refused. It keeps the frozen generator's
F32 expression and the xorshift state mutation by reference. The same generator
serves execution and the tensor-free `--control fixture-probe` boundary check.
The probe builds no graphs and contacts no endpoint.

The bounded diagnostic executes this prefix, in order:

1. T=1 mixed: warm indexes 0..4, then original measured indexes 0..19.
2. T=1 all-cold: warm indexes 0..4, then original measured indexes 0..19.
3. Rebuild at T=2 with the same owner, weights and RPC connection.
4. T=2 mixed-varied-set: warm indexes 0..4, then original measured indexes 0..12.
5. Capture original measured pair 13 in BA order, then stop.

There are 68 priming pairs and one selected target. Priming records have type
`diagnostic-prime`; they retain original indexes and warmup labels. Only the
selected target has type `pair`. B has step/dispatch count 19 and reuse count
18 at the target after the T=2 rebuild. The selector runs no T=2 shared-set or
all-cold cases and builds no graphs at T=4/8/16. It allocates the original
routing leaves at setup to preserve the original generator/allocation context.
All diagnostic summaries set `timing_comparison_valid=false`, with no
performance distributions. A failing priming pair stops the run immediately.

Source inspection establishes that T=2 uses a fresh graph and that its first
mixed step dispatches a full graph before recompute reuse. It does not prove
that prior T=1 owner/remote allocator history is irrelevant. This is the shortest
unchanged original execution prefix that reaches pair 13 without omitting
possibly relevant history. It is a conservative prefix, not a proven minimum
necessary hardware priming sequence. Standalone pair equivalence is untested.
The CPU fixture checks the exact prefix and counters. No GPU equivalence claim
is made. Do not replace this with `--tokens 2 --pairs 1`: that selects pair 0.

Production-geometry boundary hashes from the local generator probe are:

```text
input   20b7d9a7d7e4e23ac7cc3f1038481aae242fb98978a974fa22e2906f1889de7e
routing 8010b05f2f320ac067d2f4fd696f84d5358f7ffe97b5319003976cd02cbe73a8
```

The historical archive and `is346-t2-diag/REPORT.md` were absent on this computer.
These hashes have not been compared with those retained artifacts here.
`--retained-run ARCHIVE` authenticates SHA-256
`89c148c31c222580375ff768b35124be2cbbf267eb739000fd830b4c0a7e1331`,
selects the one original pair 13 row, then compares input/routing hashes,
IDs and weight bits before the supervisor launches native execution. It refuses
missing, ambiguous or different identities. Without an archive, `run.json`
explicitly reports the retained identity check as unavailable.

## One later Hermes session

This recipe is prepared, not executed. Use the established long-lived
`ssh -A hermes@100.107.250.44` CPU05 controller and the existing health/STOP
supervision. Stage this reviewed repository and the authenticated source archive
there through the established path. Keep every historical result unchanged.
Do not rebuild or replace the accepted CUDA worker.

Run once on CPU05, with fresh build and result paths:

```bash
bash /reviewed/repo/tools/native-moe-overlap/layer7-cpu05.sh \
  /reviewed/repo /authenticated/source.tar.gz \
  /fresh/pair13-candidate /fresh/pair13-diagnostic \
  --diagnostic-pair13 /retained/h5-layer7-pr346-cuda-run.tar.gz
```

If the retained archive is unavailable on the controller, omit only its final
argument. The run then carries an explicit missing historical identity check.
When the archive is available, supply it; do not bypass an identity mismatch.
The launcher composes only the diagnostic candidate benchmark and CPU fixture
worker. It retains the existing one `-L` SSH tunnel to GPU03, ownership token,
accepted worker executable hash and GPU UUID checks, 300-second supervisor cap,
360-second worker backstop, and acknowledged cleanup on every exit path.
The accepted GPU03 worker remains
`/home/hermes/is327-owned/ggml-rpc-server.cuda03`, SHA-256
`46345f6c4df4f229aa11e76514c6c6eff9c9a148257f9232a505c8173d2ebf73`.
GPU03 remains `hermes@100.77.187.38`, GPU0 UUID
`GPU-e1f2f90c-49ab-2689-0cf1-e5d9da520176`. No second attempt follows a refusal.

Retain the complete fresh build and result trees. Inspect
`benchmark/native/capture/manifest.json`, `benchmark/stdout.jsonl`,
`benchmark/run.json` and launcher `cleanup.json`. A target comparator failure
returns 2 with its raw capture retained. Missing/failed cleanup remains failed
or unknown. Neither diagnostic PASS nor INVALID replaces the historical
PR #346 verdict or grants performance acceptance.

Documentation impact: this adds benchmark diagnostics and a future recipe. It
changes no accepted capability, integration branch, gate result, acceptance,
or hardware authorization. The living project status and frozen evidence stay
unchanged.

## Local validation

The optimized portable CPU candidate was rebuilt from the authenticated cached
source archive with `hot-build-composed.py --benchmark-only --portable-fixtures`.
The focused layer-7 contracts, new diagnostic tests, existing matched graph,
batch, native-router, omission, provenance and timeout tests passed: 27 tests.
One additional supervisor regression passed. It proves that a capture-budget
failure remains INVALID when the target comparator passes. No full CPU suite
or hosted CI ran in this task.

One small CPU loopback supervisor diagnostic completed with 68 priming pairs,
one target, 17 captured tensors, `timing_comparison_valid=false`, and its owned
worker reaped. The scoped independent code/documentation review was GO with no
material findings. These results are local development checks. No hardware
host was contacted, and no GPU workload, performance qualification, push, PR,
or merge occurred.
