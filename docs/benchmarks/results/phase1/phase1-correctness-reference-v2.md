# Phase-1 correctness reference v2 — capture result

```
Status: RESULT ARTIFACT (not a methodology change)
Methodology: docs/implementation/phase1-correctness-reference-methodology-correction-v2.md
FreeToken build: Zutfen-LLC/FreeToken branch poc/phase1-route-preserving-reduction,
commit 57f60048e1697297bfee004fe037c6552439e114
```

Two independent fresh-server sessions of `PHASE1_CORRECTNESS_REFERENCE_V2`
were captured under the frozen methodology, with no performance evidence
collected. The methodology, thresholds, and the session-A-canonical selection
rule were frozen and merged into the methodology PR before these captures were
observed.

## Artifacts

| Artifact | SHA-256 |
| --- | --- |
| session A (`c3-reference-v2-session-a.json`) | `113b5cd5335e244265cf543ef89f87708ad1d6e1f07b260c72ad0e57e72069a0` |
| session B (`c3-reference-v2-session-b.json`) | `113b5cd5335e244265cf543ef89f87708ad1d6e1f07b260c72ad0e57e72069a0` |

The two independently captured session artifacts are byte-identical: identical
token sequences, identical step-0 logits, identical metadata.

## Resolved runtime (both sessions)

- model `nvidia/Qwen3.6-35B-A3B-NVFP4`, revision
  `491c2f1ea524c639598bf8fa787a93fed5a6fbce`, GPU
  `GPU-d5c05739-96c1-7e49-89b6-bf54c2121c55`;
- expert quant `nvfp4`; MoE backend `offload`; decode target `gpu`; CPU MoE
  layers empty;
- NVFP4 backend requested `triton`, resolved `triton` (not inert);
- expert cache 3,774 slots; page size 1; attention backend `fi`; cache type
  `hybrid_radix`; prefill overlap resolved enabled;
- KV capacity 17,075 pages (exactly the W3 16,819-token prompt + 256-token
  output);
- CUDA graph max batch size 0; captured batch sizes empty — no decode CUDA
  graphs, matching the distributed candidate;
- memory ratio 0.85; max running requests 1; sampling defaults none (greedy
  request override);
- `--inferswarm-secondary-gpu` not supplied; resident bank not loaded; remote
  decode disabled — no InferSwarm treatment.

## Session A vs B self-consistency gate (predeclared)

| Class | complete sequence | step-0 argmax | step-0 top-5 | full logits (2e-3/2e-3) | max abs | max rel | NaN/Inf |
| --- | --- | --- | --- | --- | ---: | ---: | ---: |
| W1 | exact | exact | exact | pass | 0.0 | 0.0 | 0 |
| W2 | exact | exact | exact | pass | 0.0 | 0.0 | 0 |
| W3 | exact | exact | exact | pass | 0.0 | 0.0 | 0 |
| W4 | exact | exact | exact | pass | 0.0 | 0.0 | 0 |

Each session also independently passed the harness's within-session
self-consistency requirement (two measured captures per class, identical exact
token sequences), executed W1 → W2 → W3 → W4 in canonical order after two
warmups per class, without restarting the server or clearing the radix prefix
cache between classes.

## Canonical reference

By the predeclared selection rule, **session A** is the canonical
`PHASE1_CORRECTNESS_REFERENCE_V2` artifact:

`113b5cd5335e244265cf543ef89f87708ad1d6e1f07b260c72ad0e57e72069a0`

Session B is the corroborating artifact (identical checksum).

No candidate evaluation, performance measurement, or placement change is part
of this result document.
