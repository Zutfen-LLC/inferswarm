# R8-I3A physical diagnostic result — Issue #248

Terminal (machine-derived by `scripts/issue248_terminal.py::derive_terminal`
from retained bytes, live dispatch authority re-fetched at reduction time):

    R8I3_REF_NONDETERMINISM_UNRESOLVED

- Reduction record: `evidence/physical/terminal-reduction.json`
  (sha256 `0b12c5f8da0b24eaba4ec4a9d2d3043245eb1841938ea520c83031307d515894`, complete=true,
  problems=[]).
- Campaign executed 2026-09-25 under maintainer dispatch comments
  `5835804759` / `5835805496` / `5835806243` / `5835806907` (GO
  `5835802760`) at PR #249 head `3f36ef1a518065bdc848cb66f6f26d94b34319f4`,
  hosted CI run `36156959482` SUCCESS, on inferswarm01 (RTX 3060 reference
  arm B) under the campaign-level model attestation
  (opening `fc76fa30…`, closing `9b6f9150…`, METHODOLOGY-AMENDMENT-003).
- 31 units, 4 namespaces, 200 fresh-process request rows; all identity
  pre/post and platform-health checks clean on every unit.
- External evidence root: `inferswarm01:/home/hermes/is248-campaign/`
  (534-row `evidence/SHA256SUMS`, self-digest
  `af9dfd0f08e9d3c4cbeb8fe164f781bc64b488ad4aba23954f5893ac980ab3bc`;
  every row verifies; quarantined pre-correction unit retained but
  non-terminal-bearing).

## What the retained bytes establish

1. REPRODUCED: full-vocabulary FP32 row bytes differ across fresh
   processes at case-3072 on the RTX 3060 reference arm in EVERY pair
   of the 5 fresh repeats (5/5 distinct row sets; ~248,320/248,320
   entries differ per decision; RMS 0.16–0.34; max |Δ| 0.87–1.9
   except cascaded decisions after a winner flip, see 3).
2. REGIME-SPECIFIC: case-256 and case-1024 are byte-deterministic
   under identical observer/binaries/host/process semantics (rows
   byte-identical across fresh processes). Only the 3072-token regime
   varies.
3. WINNER INSTABILITY IS REAL BUT RARE: 4/5 fresh repeats produced the
   accepted winner sequence; unit baseline-001 produced a different
   winner at decisions 0, 1, and 7 (top-1 flip at d0; downstream
   decisions then cascade: pairwise max |Δ| jumps to ~15–18 on
   d1–d7 vs ~1–2 elsewhere — consistent with committed-token context
   divergence, not independent per-decision noise). The accepted #241
   warning that argmax stability was "luck-adjacent" is confirmed: a
   fresh process DID flip d0.
4. OBSERVER EXCLUDED: dual-capture rows are byte-equal within every
   process (comparator hook vs independently-coded R8-E hook, same
   process: `obs.row0.f32` == `obs.r8e.jsonl.pos0.f32` in both dual
   units) while rows still vary across processes — capture is faithful;
   the comparator observer is not the perturbation. Additionally the
   hook-free canonical binary (`21707f25…`) produced DIFFERENT tokens
   across its two fresh processes at case-3072, while obs-off
   (inert-observer binary) tokens were stable in its pair. The
   unobserved path itself varies.
5. PLACEMENT DOES NOT LOCALIZE: rows differ at every ngl rung 1/2/4/6/8
   (2/2 distinct row sets per rung) — variation survives placement
   changes including near-all-CPU ngl=1.
6. HEALTH/IDENTITY CLEAN: all 31 units identity pre/post clean, no
   fatal platform findings; no kernel/AER evidence of device fault.
7. EARLIEST DIVERGENCE BOUNDARY: the decision-0 full-vocabulary row of
   the first generation step already differs broadly across fresh
   processes (max |Δ| ~1.4–1.9 at d0 in every pair, ~all entries) —
   divergence arises at or before the first generation step's row
   computation, upstream of any committed-token cascade.

## Why UNRESOLVED is the honest terminal

The frozen methodology requires a mechanically localized mechanism for
`*_LOCALIZED` terminals. Here: observer perturbation is excluded (4),
placement is excluded as the discriminator (5), platform instability is
not evidenced (6), and regime specificity is established (2) — but the
frozen tooling has no validated one-factor Vulkan runtime control, so
"Vulkan nondeterminism" cannot be causally separated from runtime/
process-initialization state with the executed probe set. Per the
frozen reducer contract, Vulkan localization is intentionally
unreachable without such a control; the reducer therefore derives
UNRESOLVED (repeatable variation confirmed, causal boundary not
honestly localizable) rather than an unsupported LOCALIZED claim.

## Prohibitions compliance

Zero predictive `c237-*` execution, zero holdout access, zero threshold
derivation, zero case-4096 execution (never authorized), no #241
evidence modification (consumed read-only under its own manifest
custody), `R8I3_COMPARATOR_V2_BLOCKED` untouched, no comparator/2
methodology change, no candidate-tolerance relaxation, no R8-J work.
