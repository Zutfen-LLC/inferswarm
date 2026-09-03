# Issue #74 frozen methodology

Status: **FROZEN FOR MAINTAINER REVIEW. PHYSICAL EXECUTION IS NOT AUTHORIZED.**

## 1. Authority and scope

This methodology implements InferSwarm issue #74. ADR 0010 and
`docs/architecture/numerical-equivalence-contract.md` are authoritative. The
contract ID is `inferswarm.gemma4-heterogeneous-numerical-equivalence/1`.

The frozen subject is:

- model `google/gemma-4-12B-it`;
- revision `707f0a3b8a3c7ad586ed01e27eafbad8a27dd0f7`;
- checkpoint SHA-256
  `5a84cb313260ac447237b890387116dfa8682e49a6b44bc585ae8353abbff18d`;
- FreeToken producer derived from exact base
  `d4d16089165917704a87f4e2f0c4a09969646f95`;
- native BF16 text execution;
- Triton attention;
- deterministic greedy replay-prefill;
- one replay chunk within the frozen 64-row limit;
- a matched single-GPU FreeToken reference on the `inferswarm04` RTX 3090;
- the accepted three-stage RTX 3060 candidate chain.

The preflight must record the exact observed FreeToken build, torch, CUDA
runtime, driver, Triton, native extension, cuBLAS or other math-library,
device, role, mode, and geometry identities. It must match the applicability
key before a result is valid.

This campaign excludes incremental KV extend, multi-chunk execution, and a
Transformers-versus-FreeToken baseline gate. It does not derive a universal
tolerance. It does not use historical R6 or issue #71 values to set limits.

Historical R6 remains `R6_DENSE_ARCHITECTURE_FALSIFICATION_FAIL`.

## 2. Conjunctive correctness

Every valid result must pass all three layers:

1. exact integrity invariants;
2. all mandatory numerical envelopes;
3. exact deterministic greedy-token identity.

One layer cannot waive another layer. NaN or Inf at a declared finite
checkpoint is an unconditional failure.

The exact layer includes model and checkpoint identity, representation, plan
and role identity, Logical State Unit coverage, Materialization ownership,
sender and receiver bytes, session and position attribution, the observed
backend path, and the absence of fallback or substitution. Exact sender and
receiver boundary bytes never use a numerical tolerance.

## 3. Cases and independence

One deterministic prompt is one independent statistical case. A prompt
contributes one conservative case summary to each mandatory envelope.
Repeated processes or devices do not add statistical cases.

The calibration corpus uses six content classes:

1. ordinary prose;
2. source code and structured syntax;
3. mathematics and numerals;
4. multilingual text;
5. repetitive and low-entropy tokens;
6. punctuation, whitespace, rare-token, and high-entropy text.

It uses four prompt-token-length regimes: 4–8, 24–28, 36–40, and 52–56.
There are 24 content-by-length cells. Each cell contains 24 cases. The total is
576 independent calibration prompts.

`manifests/calibration-corpus.json` freezes the exact text, token IDs, lengths,
and hashes. It pins the tokenizer JSON and generation program hashes. The raw
text profile uses `encode(add_special_tokens=False)` with no chat template.
The execution harness must consume the frozen token IDs. It must not retokenize
the text during a physical run.

The corpus is deterministic. Its public seed and procedure are committed.
The generator uses a SHA-256-derived local pseudorandom stream for each case.
It truncates a generated content-class sequence to an exact token count. It
accepts the prompt only when decode and encode reproduce the same token IDs.

No calibration, stress-pool, or holdout prompt can equal the 26-token historical
R6 prompt. Prompt hashes and token-ID hashes are disjoint across the three
corpora.

## 4. Margin-stress cases

`manifests/margin-stress-pool.json` freezes 48 independent candidates. It has
two candidates in every content-by-length cell. These cases are not part of the
576 statistical samples.

The matched reference is the only input to selection. The selector rejects
zero, negative, NaN, Inf, missing, duplicate, and non-pool margins. It sorts by
`(positive_top1_margin, case_id)`. It selects the four smallest positive
margins and the four largest margins. The case ID is the deterministic tie
break.

`manifests/margin-stress-selection-commitment.json` freezes this rule, the pool
hash, and an output count of exactly eight. After the reference run, use
`scripts/select_issue74_margin_stress.py` to emit the selected manifest. Commit
that manifest before any heterogeneous candidate execution.

For each envelope, the final calibration limit is:

```text
max(maximum of 576 statistical case summaries,
    maximum of 8 selected stress case summaries)
```

The rule can only keep or increase the statistical maximum.

## 5. Replay and checkpoints

Each case generates eight deterministic greedy tokens. Exact token identity is
mandatory at positions 0 through 7. Tensor capture positions are 0, 1, 3, and
7. Record selected-token margin, rank, and top-k diagnostics. These diagnostics
cannot replace an exact token gate or a numerical envelope.

`manifests/checkpoint-family-map.json` assigns every frozen numerical checkpoint
to one checkpoint family. It includes:

- embedding output as an exact reference sanity checkpoint;
- layer-0 `o_proj` input and output;
- one representative global-attention output projection;
- residual outputs after global layers 15, 31, and 47;
- the final normalized hidden state;
- the full final-row BF16 logits;
- the full final-row FP32 logits consumed by greedy selection.

The five families are local BF16 backend-operation output, hidden or residual
stream, final normalized hidden state, BF16 logits, and FP32 consumer logits.
Each family has maximum absolute difference, RMS difference, and p99 absolute
error. This makes exactly 15 mandatory envelopes.

## 6. Statistical design

For every envelope:

- population content `p = 0.99`;
- familywise confidence for all 15 marginal coverage statements `= 0.95`;
- familywise alpha `= 0.05`;
- Bonferroni per-envelope alpha `alpha_i = 0.05 / 15`;
- distribution-free upper tolerance limit `= X_(n)`, the sample maximum.

The requirement is:

```text
P(F(X_(n)) >= p) = 1 - p^n >= 1 - alpha_i
n >= ceil(log(alpha_i) / log(p)) = 568
```

The selected count is 576 because `24 cells * 24 cases = 576`. The mechanical
record is `manifests/sample-size-derivation.json`. A method change is required
if the program does not return 568 and 576.

This design gives simultaneous confidence about the marginal population
coverage of each envelope. It does not claim that 99 percent of requests pass
all 15 envelopes together. The holdout is a separate falsification gate.

## 7. Physical arms and order

The maintainer must accept this methodology before Arm A starts.

### Arm A: same-device repeatability

Use the 12 frozen sentinel cases. Run at least three fresh processes on each
participating device. The expected result is exact equality. If nondeterminism
occurs, stop before heterogeneous calibration. Retain
`SAME_DEVICE_NONDETERMINISM_BLOCKED`.

### Arm B: same-device-class cross-card repeatability

Run the same sentinel set on at least two physical RTX 3060 cards. Match the
stage role, weights, input, and geometry. RTX 3060 class qualification is not
valid without successful cross-card evidence.

### Arm C: heterogeneous same-input stage execution

Replay byte-identical captured input and state for representative stage
geometry on the RTX 3090 and every participating RTX 3060.

### Arm D: full calibration

Run all 576 prompts and the eight selected stress prompts through the matched
single-GPU reference and the frozen three-stage candidate. Preserve exact
boundary proofs. Collect all 15 conservative case summaries and semantic
outputs.

## 8. Threshold freeze

`scripts/issue74_methodology.py derive-thresholds` accepts only the frozen
methodology manifest and retained calibration summaries. It fails closed on a
holdout field, a holdout case ID, an exact or semantic failure, non-finite data,
missing cases, missing envelopes, or missing evidence hashes.

The program verifies evidence completeness. It computes each 576-case maximum
and each eight-case stress maximum. It writes their maximum as an exact
hexadecimal IEEE-754 value. It records the methodology, corpus, calibration
evidence, and derivation-program hashes. Manual editing and rounding are
prohibited.

Commit and verify the threshold manifest before any holdout custodian releases
the private key or secret seed. A changed reducer, corpus, sample count, risk
target, or threshold rule requires a new contract version and a new holdout.

## 9. Sealed holdout

The holdout contains one prompt in every content-by-length cell. It contains 24
cases. It is disjoint from calibration, the stress pool, and historical R6.

The repository stores only the CMS-encrypted package, recipient certificate,
and public commitment. The public commitment contains cell labels, lengths,
and content hashes. It does not contain prompt text or token IDs. The private
key and deterministic secret seed remain in custodian storage outside the
repository.

Do not run the `unseal` command until the threshold manifest is committed and
independently verified. The unseal tool requires that exact threshold manifest
and its expected SHA-256.

The holdout rule is zero exceedances. A valid case passes only when it matches
the applicability key, passes all exact invariants, stays finite, satisfies all
15 limits, has exact greedy tokens at all eight positions, and covers the
required devices, roles, and geometry. Any valid exceedance is `FAIL`. Do not
retune. Use `INSUFFICIENT_EVIDENCE` only for incomplete or invalid evidence.

## 10. Stop condition

This methodology PR must remain unmerged until maintainer review completes.
Issue #74 completion does not authorize calibration. After explicit acceptance,
open a separate execution issue for calibration, threshold freeze, and sealed
holdout qualification. A later R6 successor remains a separate full integration
attempt.
