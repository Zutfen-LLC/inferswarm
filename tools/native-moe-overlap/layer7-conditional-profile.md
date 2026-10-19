# Conditional MMVQ correctness experiment

This prospective diagnostic completes the captured layer's arithmetic chain and
binds an untimed replay to timed output bytes. `conditional-profile-match` means
the **explicitly assumed vendor accuracy profile** holds for the checked case.
`numerical_qualification` and `performance_claim` remain false, always. This
neither qualifies numerical equivalence nor changes any legacy verdict.

The opt-in [warmed sweep preparation](layer7-warmed-sweep.md) preserves this
profile and adds complete measured-pair replay coverage before reporting
conditional timing observations. It does not change numerical qualification.

## Contract frozen before scoring

Profile: `b29c606e-q8_0-mmvq-vendor-accuracy-union/1`, native pin
`b29c606e28a01b1bc8c1351026a0fa6e616bf6c4`, Q8_0 weights, F32 inputs/outputs,
NVIDIA architecture 86, dedicated mixed five-hot/five-cold routing, d<=2560,
hidden<=640. T=1,2,4,8 are each tested by a different frozen deterministic seed
and expert order. Single-token and batched MMVQ share only a conservative
order-independent operation bound, not an asserted identical reduction tree.
**T=16/MMQ is unknown and refused by the replay option.**

Assumption: division obeys RN or CUDA's documented 2-ULP approximate-division
envelope. expf obeys the published ordinary/fast accuracy envelope. NVIDIA says
its math-function tables are based on extensive, non-exhaustive testing and are
not guarantees. This is therefore an **assumption-backed experimental profile**,
not a universal theorem or unconditional qualification. The accepted worker's
actual fastmath flag is not claimed observed. Compiler/architecture identities
must still be supplied by the existing build manifest and hardware supervisor.
References: [NVIDIA math accuracy](https://docs.nvidia.com/cuda/cuda-programming-guide/05-appendices/mathematical-functions.html),
[PTX division](https://docs.nvidia.com/cuda/parallel-thread-execution/index.html#floating-point-instructions-div).

Quantization uses only the captured operands, before any output residual:
amax is exact; surround RN amax/127 by four F32 neighbours on each side, and do
the same for x/d at both denominator endpoints. Four neighbours conservatively
cover a 2-ULP error even across a binade boundary. Apply monotone roundf to all
endpoints; keep every reachable integer and F16 scale. No chosen byte exception
or residual-fitted tolerance exists. Correlations are conservatively relaxed,
which may make a case inconclusive, never silently useful.

For each Q8 row, integer products/lane sums are exact and F16 scale products
are exactly representable in F32. The C++ helper encloses the ideal interval
with outward-rounded binary64 operations, then adds gamma_n * sum(abs(terms)),
u=2^-24 and n=8*(columns/32)+64. There are at most four floating partials per
Q8 block; this exceeds separate multiply/add counts plus warp/warp-group
reductions for each supported MMVQ path and also covers contracted FMA. It is
chosen from operation counts, independently of residuals. Finite F16 scales
and bounded activation scales prevent F32 overflow/underflow of dot partials.

SwiGLU uses captured, already checked gate/up. Decimal exp at 80 digits supplies
the reference; 4+ceil(2*abs(gate)) F32 neighbours cover ordinary expf plus both
published fast-exp coefficients (1.16 and 1.173), with conversion margin. Enclose
the F32 add, union division, and final multiply in source order. |gate|>16,
subnormal F32 arithmetic, activation scale underflow, nonfinite values and
unsupported dimensions are unknown/error rather than pass.

The conjunction checks B gate/up, B SwiGLU, B down, routing-weight multiplication,
restored expert planes, and final ten-expert-plus-shared reduction. Cold planes
and shared output must equal the same-input trusted CPU arm exactly. This is
reference-relative checking; it does not separately prove the CPU implementation.
All routing IDs/weight bits/slot mappings, payload hashes, selected bank hashes
and source identities remain exact invariants. The original comparator is
reported in `legacy_comparator` alongside the new result, without modification.

Each hot expert's output must reject zero at gate/up/down; each SwiGLU row must
also do so. Expert/shared omission and stale-token-output controls at composition
must reject. Zero mass or a bound too broad to reject required work produces
`inconclusive`. These signals do not claim detection of a coherent stale entire
capture; existing same-request worker/device attribution remains necessary.

## Untimed replay and bounded hardware test

`--operand-replay` requires one pair, zero warmups, supported widths, synthetic
routing and no other diagnostic. It executes one mixed case at T=1 and both
varied/shared-set cases at larger widths: seven timed pairs for 1/2/4/8.
Only **after all timed work finishes** does it rebuild graphs with OUTPUT stage
retention and replay those same seven inputs/routes. No timed graph receives
stage retention. Each arm's replay output hash must exactly equal that arm's
timed output hash. Failure is terminal/inconclusive, with raw evidence retained.
No tolerance adjustment or rerun follows it.

Replay capture schema 2 is opt-in; the historical T=2 schema loader remains
unchanged by default. A checker additionally reconciles the saved timed row
against the external retained stdout record, including input/route IDs and
weights and both output hashes. Maximum seven captures at <32 MiB each; no model
download or model execution is involved. Timings are diagnostic observations,
not a performance-qualified sweep (one pair/no warmup is intentionally small).
Legacy INVALID does not abort this explicitly labeled diagnostic; it remains
INVALID in both the row and legacy summary. Completion is a separate field.

After the existing CPU05/GPU03 launcher finishes and verifies cleanup:

```bash
c++ -O3 -std=c++17 -shared -fPIC -mf16c -ffp-contract=off \
  "$REPO/tools/native-moe-overlap/layer7_arithmetic.cpp" -o "$RESULT/operand-helper.so"
python3 "$REPO/tools/native-moe-overlap/layer7_operand_check.py" \
  --replays "$RESULT/benchmark" --helper "$RESULT/operand-helper.so" \
  --output "$RESULT/conditional-profile.json"
```

Exit 0 means all seven cases conform **conditionally**, 3 means inconclusive,
2 means a single-capture arithmetic/identity mismatch (aggregate inconclusive
retains each case's mismatch). Input/identity errors remain errors. A result
cannot be represented as unconditional numerical qualification. A later actual
performance sweep requires a separate decision based on this diagnostic and
its legacy results; this option does not start one automatically.

## Local verification

```bash
python3 -m unittest -v tests.test_layer7_arithmetic \
  tests.test_layer7_operand_check tests.test_layer7_mmvq_check
```

The new fixed inputs are in `tests/fixtures/layer7_mmvq_heldout.json`; they were
written before their first scoring. Tests check all four widths independently,
threshold ambiguity sets, every expert omission, SwiGLU omission, wrong banks,
IDs/slots, stale inputs, corruption beyond the bound, zero-mass sensitivity and
timed-output binding. Coherent downstream recomputation after a gate omission
passes later edges but fails the independently checked gate edge. Retained
pair13 conforms conditionally at every arithmetic edge while keeping its legacy
INVALID and unknown timed binding unless external timed records are supplied.

Documentation impact: this adds only prospective diagnostics. Accepted status,
historical comparators/evidence, execution authority and accepted worker bytes
are unchanged. No PR, hosted CI or Final Validation belongs to this development
task. The hardware test is a future Hermes action, not performed here.
