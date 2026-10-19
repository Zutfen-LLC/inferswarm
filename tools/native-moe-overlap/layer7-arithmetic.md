# Offline layer-7 gate/up arithmetic

This small offline diagnostic uses the executed-stage capture and exact selected
Q8_0 banks. It changes no benchmark, runtime, frozen comparator, tolerance or
verdict. It needs no GPU, sockets or production model. Run it on x86 with F16C
and the default round-to-nearest floating-point environment.

```bash
c++ -O3 -std=c++17 -shared -fPIC -mf16c -ffp-contract=off \
  tools/native-moe-overlap/layer7_arithmetic.cpp -o /tmp/layer7-arithmetic.so
python3 tools/native-moe-overlap/layer7_arithmetic.py \
  --capture /retained/benchmark/native/stages \
  --helper /tmp/layer7-arithmetic.so --output /fresh/arithmetic.json
```

The stage validator checks all base/stage tensor identities and layouts first.
Gate/up reconstruction is bounded to two tokens, five hot experts, `d<=2560`,
`f<=640`. The report preserves original and compact expert-slot mappings. It
compares every selected row, including token 0 controls, and reports bit-exact
counts, maximum residuals, RMS, and each expert's worst observed A/B point.
It makes no performance or acceptance claim.

`--hypothesis TOKEN:INPUT_INDEX:SIGNED_BYTE` explicitly changes a modeled CUDA
activation byte. It is never labeled a captured observation. The tool reports
both the unchanged host-RN quantizer model and the changed-byte model, plus a
no-FMA ablation. Hypotheses must come from a separately documented mechanism;
this tool neither fits tolerances nor searches arbitrary activation bytes.

The equations follow authenticated llama.cpp
`b29c606e28a01b1bc8c1351026a0fa6e616bf6c4`:

- CPU `ggml-cpu.c:1542` converts F32 activations to the type-trait dot operand;
  Q8_0 uses Q8_0 (`:272`). The IQ panel path requires Q8_K and does not apply
  (`iqp.cpp:1053`). In `arch/x86/quants.c:302`, AVX quantization uses a F32
  `127/amax` multiplier and nearest-even integer rounding, storing scale as F16.
  The AVX2 dot (`:1308`) has eight four-product integer lanes, F32 scale products,
  FMA accumulation, and the horizontal reduction at `:43`.
- CUDA `ggml-cuda.cu:1911` first dispatches quantized F32-input/F32-output
  MUL_MAT_ID with T=2 to MMVQ when the device's Q8_0 batch limit allows it.
  Q8_0 limits are at least four for NVIDIA (`mmvq.cu:150,177,285`). With IDs and
  multiple tokens, `mmvq.cu:1149` chooses the dedicated MoE kernel (`:836`),
  not the ordinary single-token kernel. The launcher has 32 lanes per NVIDIA
  warp, one warp per token and two output rows per CUDA block (`:1027`).
  This conclusion also requires the retained type, backend, IDs and shapes;
  dimensions alone do not identify dispatch.
- `quantize.cu:54` uses F32 `d=amax/127`, `roundf(x/d)`, and F16 scale storage
  in Q8_1. Q8_0's dot uses only that scale and integer bytes, not the sum half
  (`vecdotq.cuh:246,851`). Four threads cover each 32-value block; thread-local
  sums advance by eight blocks, then XOR warp reduction uses offsets
  16,8,4,2,1 (`mmvq.cu:907`, `common.cuh:472`). The helper models FMA explicitly.

The helper packs relevant activation scale/bytes as Q8_0 for both models. It
does not claim this is the device's actual Q8_1 buffer: Q8_1 also contains an
unused sum half. CUDA quantization uses host correctly rounded division in this
model. Pinned CUDA CMake sets `-use_fast_math` (`CMakeLists.txt:186`), which
[NVCC documents](https://docs.nvidia.com/cuda/cuda-compiler-driver-nvcc/index.html#use-fast-math-use-fast-math)
as enabling approximate division and FMA. The accepted worker's actual
quantization bytes, per-element quotient and device instructions must not be
invented from that build default. Exact output agreement under a byte hypothesis
is exact reconstruction of the outputs, with the byte and instruction mechanism
still identified as inference.

Focused tests:

```bash
python3 -m unittest -v tests.test_layer7_arithmetic
```

Four primitive tests run normally. Two optional tests need an authenticated
physical capture and an actual pinned CPU function wrapper. Build that wrapper
from the authenticated pin (not a different checkout):

```bash
PIN=/authenticated/llama.cpp-b29c606e28a01b1bc8c1351026a0fa6e616bf6c4
gcc -O3 -shared -fPIC -mavx2 -mfma -mf16c -fvisibility=hidden \
  -ffunction-sections -fdata-sections -Wl,--gc-sections \
  -I"$PIN/ggml/include" -I"$PIN/ggml/src" -I"$PIN/ggml/src/ggml-cpu" \
  tests/layer7_native_oracle.c "$PIN/ggml/src/ggml-cpu/arch/x86/quants.c" \
  -lm -o /tmp/layer7-native-oracle.so
LAYER7_STAGE_CAPTURE=/retained/benchmark/native/stages \
LAYER7_NATIVE_ORACLE=/tmp/layer7-native-oracle.so \
  python3 -m unittest -v tests.test_layer7_arithmetic
```

The adapter initializes the pinned CPU code's F16 lookup table with F16C, then
calls its actual quantizer and dot functions. It runs no graph or serving code.
The optional physical test is specific to frozen pair 13; it verifies all
selected gate/up rows, both tokens, and a wrong-byte counterexample. It is a
local diagnostic test, not qualification or hosted CI.

Documentation impact: no accepted capability, project status, execution
authorization or historical result changes. Keep physical bundles and detailed
local numerical reports outside Git unless separately approved for publication.
