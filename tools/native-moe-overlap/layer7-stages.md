# Executed layer-7 hot-expert stages

`layer7_bench.py --diagnostic-pair13 --capture-stages` extends the
[bounded pair-13 diagnostic](layer7-diagnostic.md). It is default off and makes
no performance claim. It preserves the original INVALID verdict, comparator,
tolerances, routing, backend options, thread count and 68-prime + one-target
selection. It stops at the first failed priming pair. A failure before T=2 has
only the base capture; a T=2 priming failure captures that actual pair and stops
without claiming that pair 13 was reached. No larger widths are executed.

## What is observed

Before T=2 graph allocation, the benchmark marks five existing executed nodes
as OUTPUT: gate projection, up projection, SwiGLU, unweighted down projection,
and weighted expert output. A retains all ten slots; B retains only the existing
five-hot-expert remote branch. The constructor-only `benchmark_stages` setting
has no serving environment flag. T=1 graphs are unchanged. There is no extra
graph execution or separately recomputed operand graph. Existing worker tensor
flags carry retention through RPC; the worker and wire protocol are unchanged.

The flags retain bytes until synchronized capture, including both tokens and
token 0 as a control. They change allocator reuse and prohibit eligible fusion
that would elide these outputs, including CUDA gate/up/SwiGLU fusion. The stage
graphs therefore can execute different kernels. Even matching final hashes do
not establish that the original fused graph materialized identical intermediate
values. No capture from this extension should be presented as an observation of
an unretained original intermediate. Retention is applied to all T=2 primes and
the target so the selected graph retains its original dispatch/reuse sequence.

Untimed reads occur after both arms synchronize. `native/stages/manifest.json`
records these perturbations and links the exact schema-2 base capture manifest.
The primary capture retains actual inputs, route IDs and weight bits, shared
output, final outputs, and original slot mappings. The stage directory contains:

- Ten F32 files: A/B gate, up, SwiGLU, down and weighted output. Shapes are
  `[f,10,2,1]` / `[f,5,2,1]` for the first three and
  `[d,10,2,1]` / `[d,5,2,1]` for the last two. Coordinate is fastest.
- Three exact Q8_0 banks in compact expert order `54,74,136,290,394`, each with
  GGML type, four dimensions, byte strides and hashes. Selected slices of A's
  synthetic banks must equal actual B remote bank bytes and the existing compact
  bank identity. Only one identical copy is saved. Q8_0 blocks retain the F16
  scale and 32 signed quantized bytes. These are the weights actually consumed.
- Both-token original slot, branch slot, compact expert and global expert
  mappings; executed node names/operations/OUTPUT flags; source full-bank
  identities; input/routing hashes; original pair index, warmup and AB/BA order.

At production geometry `d=2560,f=640`, the ten F32 files total 844800 bytes and
the three selected banks total 26112000 bytes (26956800 combined). The separate
stage cap is 32 MiB and metadata cap 64 KiB; base capture remains capped at
16 MiB. Required fresh capture directories prevent overwrites.
Short writes, layout/identity errors or budget failures remain explicit failed
diagnostics and cannot convert a failed comparison into PASS. Extra remote GETs
and host staging run outside total timers. OUTPUT retention can change timed
execution; diagnostic timings carry no performance claim.

## Offline interpretation

`layer7_stages.py` validates identities, dimensions and strides before comparing
the mapped hot experts. It reports each token/expert's exact-coordinate count,
maximum absolute difference, RMS and relative L2 difference at each stage. Gate
and up are parallel inputs, so both can be first differing boundaries. This
locates the first observed discrepancy; it does not establish a specific kernel
cause or add another acceptance tolerance.
The separate [offline arithmetic helper](layer7-arithmetic.md) can reconstruct
the pinned gate/up quantized dot paths and test explicitly labeled activation
byte hypotheses using the same captured inputs and banks.

Always compare the final A/B output hashes with the supplied uninstrumented
pair-13 capture. The tool accepts that older schema only for final output and
boundary identities, never for its invalid B weighted planes. If either final
hash differs, its report explicitly prohibits attributing the instrumented
stages to the original failure. If the target was not reached, report that and
do not compare another pair to the pair-13 baseline.

`--reference` computes six selected individual row dots: the worst mapped
gate/up/down point for each token, for both arms, using 100-digit Decimal and
the exact Q8_0 bytes. These are mathematical dequantized-weight dots, not CPU or
CUDA backend emulation. They do not model dynamic activation quantization,
accumulation order, fused arithmetic or rounding. A near-reference result is
not a replacement comparator or proof that a backend operation is defective.

## One controller-only replay

This recipe is prepared for Hermes, not executed during development. Set
`EXPECTED_SHA` to the reviewed remote commit in the handoff. Use the existing
long-lived `ssh -A hermes@100.107.250.44` controller, health/STOP rules and
unchanged accepted CUDA worker. Do not retry a refused or failed session.

```bash
set -eu
EXPECTED_SHA=REPLACE_WITH_REVIEWED_REMOTE_COMMIT
SOURCE=/home/hermes/diag346-wt
ROOT=$(mktemp -d /home/hermes/l7st.XXXXXX)
git -C "$SOURCE" fetch origin diag/layer7-pair13
test "$(git -C "$SOURCE" rev-parse FETCH_HEAD)" = "$EXPECTED_SHA"
git -C "$SOURCE" worktree add --detach "$ROOT/repo" "$EXPECTED_SHA"
export PATH=/home/hermes/h5-layer7-pr346/fresh/ninja_dir:$PATH
set +e
bash "$ROOT/repo/tools/native-moe-overlap/layer7-cpu05.sh" \
  "$ROOT/repo" /home/hermes/is319-stepa/pin.tar.gz \
  "$ROOT/candidate" "$ROOT/result" --diagnostic-stages \
  /home/hermes/is346-diag/retained/h5-layer7-pr346-cuda-run.tar.gz \
  >"$ROOT/launcher.log" 2>&1
RUN_STATUS=$?
set -e
printf '%s\n' "$RUN_STATUS" >"$ROOT/launcher.exit"
cat "$ROOT/result/cleanup.json"
```

Do not continue hardware execution if anything fails. Exit 2 may be the expected
numerical INVALID with a complete capture. Check `benchmark/run.json`, selected
pair records, capture status and `cleanup.json` before interpreting evidence.
Cleanup must confirm the owned remote worker is absent. Preserve unknown or
failed cleanup status honestly; follow established cleanup supervision.

The launcher rebuilds only the diagnostic candidate benchmark and CPU fixture.
It uses one `-L 127.0.0.1:50060:127.0.0.1:50060` tunnel to
`hermes@100.77.187.38`, the existing accepted worker
`/home/hermes/is327-owned/ggml-rpc-server.cuda03` with SHA-256
`46345f6c4df4f229aa11e76514c6c6eff9c9a148257f9232a505c8173d2ebf73`,
and GPU0 UUID `GPU-e1f2f90c-49ab-2689-0cf1-e5d9da520176`.
The source archive SHA-256 is
`03fb04316eb32a7b7347004a79a8dd60531c02f5a064d853fed3b53828951723`.
It verifies the historical run archive SHA-256
`89c148c31c222580375ff768b35124be2cbbf267eb739000fd830b4c0a7e1331`.
Keep the 300-second supervisor cap, 360-second worker backstop and cleanup on
every terminal path. No CUDA worker rebuild, new SSH identity or second attempt.

If the selected record is non-warmup T=2 mixed-varied-set pair 13 and all stage
files are complete, analyze offline after cleanup:

```bash
(ulimit -v 1048576
 timeout --signal=TERM --kill-after=2 60 python3 \
  "$ROOT/repo/tools/native-moe-overlap/layer7_stages.py" \
  --capture "$ROOT/result/benchmark/native/stages" \
  --baseline /home/hermes/is346-diag/pair13-diagnostic/benchmark \
  --reference --output "$ROOT/stage-analysis.json")
```

For a captured earlier T=2 failure, omit `--baseline` and report that the target
was not reached. Do not rerun. Retain the whole fresh root, receipts, native
bytes, analysis and logs. Historical verdicts and artifacts remain unchanged;
neither PASS nor INVALID here grants performance acceptance.

## Development scope

Focused portable CPU tests cover both tokens and all hot slots, AB/BA execution,
retained-node lifetime, raw-bank identity/layout, base-plane reconstruction,
corruption refusal, baseline attribution refusal, and enabled/disabled final
output equality. The small `stage-probe` seam selects pair 0 or 1 solely for
local tests and carries no performance claim. It is not the hardware selector.

Documentation impact: this adds benchmark observations and an operations recipe,
without changing accepted capability, project status, gate results or historical
evidence. Hardware execution remains a separate Hermes action.

The final source-bound portable CPU build passed 23 focused tests. One supervised
small CPU replay reached original pair 13 in BA order after 68 primes, retained
all 13 stage/bank files, set `timing_comparison_valid=false`, and reaped its owned
worker. Its A/B final hashes matched the earlier uninstrumented CPU capture;
both tokens' hot stages were exact across the CPU arms. This does not establish
CUDA output invariance. Scoped independent review was GO after correcting the
timer wording above. No hardware workload or hosted CI ran during development.
