# Phase-1 route-preserving candidate — C3 and requalification result

```
Status: RESULT ARTIFACT
FreeToken build: Zutfen-LLC/FreeToken poc/phase1-route-preserving-reduction,
commit 57f60048e1697297bfee004fe037c6552439e114
Placement: phase1-qwen36-placement-v2 / coverage_constrained_complement_5442,
SHA-256 2f62bb84df40d4cc5649e940a39cb53d2975eadecbc320fb97d2b037d4e005f4
Comparator: PHASE1_CORRECTNESS_REFERENCE_V2 (session A, canonical)
```

All evidence below was collected after the correctness-reference v2
methodology and the reference artifact were frozen. No performance field was
collected anywhere in this result.

## C3 — candidate vs reference v2 (canonical, exact recorder)

`c3-candidate-reference-v2.json`
SHA-256 `a1549814996c91dd6cc91d7087e1886a8ac16269dbf49657c17ae765a277dd0e`

| Class | first 64 tokens | step-0 argmax | step-0 top-5 | full logits 2e-3/2e-3 | max abs | max rel | NaN/Inf | verdict |
| --- | --- | --- | --- | --- | ---: | ---: | ---: | --- |
| W1 | exact | exact | exact | pass | 0.0 | 0.0 | 0 | PASS |
| W2 | exact | exact | exact | pass | 0.0 | 0.0 | 0 | PASS |
| W3 | exact | exact | exact | pass | 0.0 | 0.0 | 0 | PASS |
| W4 | exact | exact | exact | pass | 0.0 | 0.0 | 0 | PASS |

The complete fixed-length greedy sequences are identical (no divergence index
exists); the full step-0 logit vectors are bitwise equal. Under the matched
cache-history reference, the route-preserving distributed candidate is exact.

## P2 — resident secondary bank (fixture)

`p3-correctness-route-preserving.json` (clean copy
SHA-256 `b27f744b00dab31397e70ecf837f0f60e6dc0afdc2d772b0a5911cac1ed44f44`)

- placement SHA-256 exactly
  `2f62bb84df40d4cc5649e940a39cb53d2975eadecbc320fb97d2b037d4e005f4`;
- 5,442 GPU-1 resident slots; 9,662,902,272 resident expert bytes;
- source-byte verification passed: 32,652 rows, 9,662,902,272 bytes;
- startup expert-weight H2D 9,662,902,272 bytes; steady-state expert-weight
  H2D **0 bytes**;
- quant `nvfp4`, Triton backend, `native_modelopt_nvfp4` bank layout,
  host-staged transport, no decode CUDA graphs;
- primary device current restored after the fixture.

## P3 — route ownership / C1 / C2 / C4 (fixture)

- mixed case: 4 GPU0 + 4 GPU1 executed, 1 remote dispatch, C1 within
  2e-3/2e-3 with max abs = max rel = 0.0, zero NaN/Inf;
- local-only case: 8 + 0, zero remote dispatches, exact;
- remote-only case: 0 + 8, 1 dispatch, no GPU0 residency/copy entries, exact;
- remote router identities never entered GPU0 residency or copy plan
  (asserted in all cases); raw route tensor preserved;
- 40-layer smoke: 320 selections = 160 GPU0 + 160 GPU1 executed, 40 remote
  dispatches, 40 route reconstructions, 40 final sum reductions, zero
  fallback, zero explicit failure, zero NaN/Inf, zero remote prefill.

## P4 — W1-W4 mechanism gates (serving smoke, reset-delimited per class)

`p4-workloads-route-preserving-v2.json`
SHA-256 `9600eebf9535d053ccc599a1e16dda8eade261db035761b71bdd92f2ff27dffc`

| Class | F1 | F2 (≥20%) | F3 | F5 | F6 | remote prefill | steady expert H2D | overlap |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| W1 | pass | 21.0164% | pass | pass | exact | 0 | 0 B | active |
| W2 | pass | 36.3020% | pass | pass | exact | 0 | 0 B | active |
| W3 | pass | 24.1422% | pass | pass | exact | 0 | 0 B | active |
| W4 | pass | 21.5527% | pass | pass | exact | 0 | 0 B | active |

F6: `selected_for_gpu1 == executed_on_gpu1` in every class; zero fallback,
zero explicit failure. Complete-layer timing validity true; no CUDA graph
replay, as frozen for the candidate. The smoke's own `C3` sub-field is
`evaluated: false` by design (exact token IDs and step-0 logits are collected
only by the canonical recorder) and its text re-encoding diagnostic shows
first-64 equality for all classes against the retained reference text.

### Route-preserving return traffic, reported honestly

Preserving per-route contributions enlarges the GPU1 return path by the
top-k factor (8) compared with returning an already-reduced partial. Per
reset-delimited class window:

| Class | returned D2H GPU1→host | returned H2D host→GPU0 | prior partial-return D2H (pre-correction build) |
| --- | ---: | ---: | ---: |
| W1 | 508,624,896 B | 508,624,896 B | 63,373,312 B |
| W2 | 612,696,064 B | 612,696,064 B | 76,808,192 B |
| W3 | 268,271,616 B | 268,271,616 B | 33,464,320 B |
| W4 | 127,893,504 B | 127,893,504 B | 16,080,896 B |

F5 is unchanged and still passes: these bytes are activation-class route
contributions, not expert-weight traffic; steady-state expert-weight H2D
remains zero.

## Boundary

This result contains no throughput, TTFT, prefill-speed, aggregate-speedup,
patched-P2P, or GO/ITERATE performance field. P5/P6 were not started.
