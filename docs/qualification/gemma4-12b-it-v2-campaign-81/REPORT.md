# Issue #81 v2 physical qualification campaign — terminal stop report

Campaign: Execute Gemma numerical qualification v2 (reference selection →
calibration → threshold freeze → retained holdout)
Result: STOPPED at Phase D — CALIBRATION_SEMANTIC_FAIL

## Identity chain
- InferSwarm accepted head: d8a98b5614123c7408aa60b0137220c252fd50b9 (verified)
- FreeToken clean base: d4d16089165917704a87f4e2f0c4a09969646f95 (verified)
- #71 localization anchor: 9586695e6ef35943b1cc4e78becd792892080e15 (verified)
- Physical producer: 9f06d81c6e9519d7ddf68b302c1c2aa14993387d
  (fresh branch inferswarm-81-gemma-numerical-qualification-v2; PR-#28
  harness cherry-picked verbatim, 0-line tree diff vs 29e04d0 harness)
- Model/revision/checkpoint: google/gemma-4-12B-it @ 707f0a3b / 5a84cb31…ff18d
  (identical on 01/03/04)
- Frozen v2 artifacts verified: pool 533b3285…, commitment 04421a6f…,
  selector e32e8672…, corpus e147ce0a…, holdout 23311c55…

## Completed gates
- Phase P / preflight: producer frozen, pushed, clean trees on 01/03/04,
  stacks identical (torch 2.11.0+cu130, CUDA 13.0, driver 610.57.04,
  triton 3.6.0, transformers 5.16.1, Py 3.13.5); native-ext .so hashes
  recorded per node (01==03; 04 differs by build-path metadata — recorded
  honestly, no byte equality claimed). CPU/static tests pass (1 pre-existing
  base failure verified at d4d1608 itself).
- Phase 0 (3090 reference, 48 p76): ALL_48_FINITE, 0 NaN/Inf,
  37 finite-positive / 11 finite-nonpositive / 0 nonfinite margins.
- Selected-eight barrier: frozen selector ran clean; 4 smallest
  (p76-01-02-02, p76-01-04-02, p76-02-02-02, p76-02-06-01; margin 0.125
  each) + 4 largest (p76-04-03-02, p76-04-04-02, p76-03-04-01, p76-03-04-02);
  manifest sha 4a97262c…; committed+pushed BEFORE any candidate execution at
  c0b80b14718ab153c24565c709d5ecf2a38af04d (re-fetched byte-identical;
  no-candidate-execution check recorded).
- Phase A: SAME_DEVICE_REPEATABLE — 3090 3x and chain 3x realizations all
  token+margins exact; 0 NaN/Inf.
- Phase B: RTX_3060_DEVICE_CLASS evidence — matched stage-role replays
  (frozen #71 run_stage1_diag) byte-identical across all three physical
  3060s (12/12 records each pair). One bundle gpu_uuid label recorded
  incorrectly by a known nvidia-smi quirk; physical execution GPU proven
  via torch device identity; noted honestly in the verdict.
- Phase C: diagnostic heterogeneous replay retained; 3090 single arm valid
  (12/12); single-full-model arm on 12 GiB 3060s physically impossible —
  two deterministic pre-execution OOMs classified infrastructure-invalid
  and retained.

## Terminal stop — Phase D
Both arms completed all cases (producer 9f06d81, clean, 0 NaN/Inf):
- reference 576/576 + stress 8/8 on inferswarm04; chain 576/576 + stress
  8/8 on 01+03.
- Exact integrity PASS (all case identities equal across arms).
- Semantic output FAIL: 236/576 statistical cases and 4/8 stress cases
  flipped ≥1 greedy token vs the matched reference.
- The four failing stress cases are exactly the four SMALLEST-margin
  selections (all 0.125); the four largest-margin selections matched.
- Mismatch strongly margin-correlated (80% flip rate at reference margin
  <0.01; median mismatch margin 0.125 vs 0.5 for matches).
- Classification: deterministic device-class bf16 GEMM accumulation
  divergence (#71 BACKEND_EXECUTION_LOCAL) flipping near-tie greedy argmax.
  NOT nondeterminism (Phase A exact-repeatable on both arms), NOT integrity
  failure, NOT nonfinite.

Consequences applied per frozen methodology:
- threshold derivation STOPPED (never started);
- holdout REMAINS SEALED (23311c55… unchanged); Phases E–J not entered;
- no valid failing case rerun; no threshold modified (none derived);
- infrastructure-invalid attempts (3: refstress missing-input; chainstress
  connection-refused; 2x pre-execution 3060 single-arm OOM) retained with
  logs under invalid/.

## Verdict
NOT QUALIFIED. Final state:
CALIBRATION_SEMANTIC_FAIL (stop condition; evidence retained for
maintainer adjudication). This is NOT QUALIFIED_NUMERICAL and NOT
QUALIFIED_BIT_EXACT. Incremental KV-extend, multi-chunk, and all other
configurations remain unqualified. Historical R6 remains failed.
