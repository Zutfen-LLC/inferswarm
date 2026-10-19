# Partial operand-aware layer-7 check

This offline development check has **no end-to-end acceptance path**. A detected
error returns `mismatch`; otherwise the overall result is `unknown`. CLI exit 2
means mismatch, 3 means unknown; malformed/inconsistent data raises an error.
The frozen comparator is copied separately into `legacy_comparator`, unchanged.
Historical pair 13 remains INVALID under `legacy-cpu-unsplit/1`. There is no new
tolerance, numerical qualification, performance claim or hardware authorization.

## Smallest defensible scope

The retained operands support exact checks of:

- Selected pair identity, consumed inputs, ID and routing-weight bits, original
  slots, compact expert order, branch IDs/weights, shapes, strides and bank hashes.
- All hot gate/up CPU projections, from original F32 inputs and exact Q8_0 banks,
  under the explicit `b29c606e-q8_0-avx2-fma/1` arithmetic profile.
- F32 down-output times routing-weight, for every retained A plane and B hot plane.
- Retained weighted stage planes against the restored final-reduction planes.
- The final CPU reduction in both arms, from all ten retained weighted planes
  and the retained shared output, with rounding at every actual add.

The last three checks are conditional on their retained inputs. They do not
independently prove SwiGLU, down projections, the five cold experts or shared
branch arithmetic. Removing a plane from the final reduction while keeping the
captured plane detects missing work there. A computation that already produced
an incorrect zero plane and consistently used it downstream is **not** ruled out
by composition. A complete coherently stale capture cannot be distinguished
from a current execution using those same bytes. Existing same-request device
attribution remains necessary. A matching hash alone is not such attribution.

Each arm reports per-token controls omitting slots 0..9, omitting shared, and
substituting the other token's output. Zero-mass controls say
`insensitive-zero-mass`; work hidden by rounding says `insensitive-rounding`.
Neither is a demonstrated rejection. Unsupported subnormal controls say unknown.
No broad interval can make an omission pass: all implemented arithmetic checks
use zero error and exact F32 bit comparison, including signed zero.

## Arithmetic justification and applicability

Native pin: `b29c606e28a01b1bc8c1351026a0fa6e616bf6c4`. The CPU equations and
source references are in [layer7-arithmetic.md](layer7-arithmetic.md). The helper
uses RN-even F32 reciprocal multiplication, RN-even integer quantization, exact
F16 storage/conversion, integer dot lanes, explicit FMA and the pinned AVX2
reduction tree. Source identity/dispatch are premises from the authenticated
producer receipt and prior source trace, not inferred by this tool from shape.
The checker does not qualify a different CPU build by matching its outputs.

Local emulation requires x86 F16C, the documented compiler flags, round-to-nearest
and FTZ/DAZ disabled; a new read-only helper guard verifies the floating-point
environment. Projection dimensions are multiples of 32 with `32<=d<=2560`,
`1<=f<=640`. Each nonzero input block must have `2^-6<=amax<=1024`; zero blocks
are allowed. These conservative power-of-two restrictions are chosen from the
numeric formats, not observed residuals: reciprocal/scaling remain finite,
activation F16 scales are normal, and accumulation cannot overflow F32. All
finite bank F16 scales are supported: even F16 subnormals convert exactly into
normal F32, and their products here remain far above F32 underflow. No scale or
byte is adjusted to fit an output. Nonfinite tensors/scales/results are rejected.

Weighting is one RN F32 product. Two F32 significands have at most 48 product
bits, so Python binary64 evaluates that product exactly before the explicit
binary32 rounding. The native graph folds expert slots 0..9 in order using F32
`ggml_add`, then adds shared (`src/llama-graph.cpp:2336..2360` and
`src/models/qwen35moe.cpp:541` at the pin). The overlay preserves that downstream
graph. Each add is explicitly rounded to F32; binary64 suffices to round a sum
of two F32 operands correctly. Subnormal F32 operands/results in weighting or
composition report unknown because the accepted worker's FTZ contract is not
available. Zero and finite normal values are supported. No reassociation is
assumed. The executed-stage probe's allocation/fusion perturbation remains as
documented in [layer7-stages.md](layer7-stages.md).

Capture integration supports only the existing T=2, five-hot/five-cold schema,
with `d,f` multiples of 32 and bounded by 2560/640. The pure projection tests use
smaller `f` to exercise row mapping. **T=1/4/8 and T=16 return unknown**: no CUDA
MMVQ or MMQ profile is enabled, and nothing is generalized from T=2 dimensions.
An unsupported profile or dimension never passes. The checker retains the
existing stage loader and adds independent byte-level boundary reconciliation.

## Why CUDA and full-layer acceptance stay unknown

The accepted worker hash and source-default `-use_fast_math` do not establish
its actual compiler command, device instructions or quantized activation bytes.
The inferred token-1/index-1529 byte is **not** an acceptance exception. This
checker has no hypothesis option and does not use the old reconstruction's
`--hypothesis` mechanism. Host-RN CUDA quantization cannot stand in for the
executed CUDA operand. No operation-derived whole-layer interval can be asserted
from the retained facts alone, including for downstream nonlinear/quantization
boundaries. Testing an empirical residual envelope would not fill that gap.

The smallest next action is offline retrieval of the **existing** accepted
worker binary and its compiler command/cubin, if retained, to identify a
supported division/rounding contract. This task does not contact hardware.
Direct operand confirmation instead needs separately authorized capture of
actual temporary Q8_1 operands (especially token-1 block 47's 36 bytes), bound to
that exact execution. Neither item alone supplies the missing full-layer
SwiGLU/down/shared proof. A future online check would require those captures
outside timing plus an independently justified full composition profile before
being used to accept a batching sweep. No benchmark graph or timed work changes
are made here, and no online option is added prematurely.

## Local commands

```bash
c++ -O3 -std=c++17 -shared -fPIC -mf16c -ffp-contract=off \
  tools/native-moe-overlap/layer7_arithmetic.cpp -o /tmp/layer7-operand.so
python3 -m unittest -v tests.test_layer7_operand_check tests.test_layer7_arithmetic
python3 tools/native-moe-overlap/layer7_operand_check.py \
  --capture /authenticated/benchmark/native/stages \
  --helper /tmp/layer7-operand.so --output /fresh/operand-check.json
# Expected exit for the retained pair: 3 (unknown), with legacy pass=false.
```

Set `LAYER7_STAGE_CAPTURE` and `LAYER7_NATIVE_ORACLE` as in the arithmetic guide
to run all physical and actual pinned-function tests. The deterministic held-out
inputs are frozen in `tests/fixtures/layer7_operand_heldout.json` before their
first evaluation. They use a different seed, both tokens and different expert
orders. Small exact dyadic dots provide a separate scalar oracle; the optional
actual pinned CPU functions also evaluate those inputs. Threshold tests cover
both signs and the immediate F32 neighbours of half integers. Negative controls
exercise omitted hot/cold experts at reduction, omitted shared, wrong IDs,
routing weights, bank bytes and slot mappings, stale token inputs/output and
corruption. Their scope is the checked boundaries, not a full-layer proof.

Documentation impact: no accepted capability, status, integration branch,
qualification result or execution authority changes. Living project status,
frozen evidence and comparator remain unchanged. This is development before
PR qualification; no PR, hosted CI or Final Validation is required or run here.
