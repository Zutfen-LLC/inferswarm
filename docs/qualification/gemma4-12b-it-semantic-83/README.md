# Issue #83 — Heterogeneous greedy semantic-output contract

Design/research adjudication defining the prospective strategy semantic
contract for deterministic greedy generation under qualified heterogeneous
floating-point variation, after #81's `CALIBRATION_SEMANTIC_FAIL`.

Read [`SEMANTIC-CONTRACT.md`](SEMANTIC-CONTRACT.md).

Contents:

- `SEMANTIC-CONTRACT.md` — the contract: what #81 falsified, the
  first-divergence diagnostic summary, the mandatory full-vocabulary
  numerical bound `E_full` vs the supplemental decision-local bound
  `E_D` separation, the proved decision-stability theorems
  (`m_D > 2E_D`, ambiguity set, tightness incl. tie behavior), fail-closed
  `DECISION_DOMAIN_ESCAPE` containment, frozen argmax/tie-break semantics,
  the A+B(+C-reserved) autoregressive trajectory design, the strict vs
  decision-stability profile taxonomy, the prospective
  calibration/holdout chronology, and the successor gate outline.
- `evidence/first-divergence-{statistical,stress}.json` — per-case
  first-divergence records extracted read-only from the retained #81
  Phase-D artifacts (reference index + per-case chain JSONs), with
  source sha256 sidecars.
- `evidence/same-prefix-error-metrics.json` — per-(case, step) full-vocab
  FP32 consumer-logit error metrics for the 752 retained captured rows on
  both arms (max/RMS/p99, top-8 overlap, candidate-argmax rank), per-row
  sha256 for both arms' rows.
- `evidence/decision-local-errors.json` — per-row decision-local errors
  (reference top1/top2 and candidate-argmax tokens), reference margin,
  admissibility gap, and the theorem-consistency checks.

Re-derive all aggregates:

```sh
python3 scripts/issue83_first_divergence.py
```

(pure stdlib, CPU-only; a hard reproduction gate re-derives the historical
#81 counts — 236/576 statistical, 4/8 stress — and aborts on mismatch.)

Raw row binaries live outside the repo on the evidence nodes:
`/srv/inferswarm/state/i83-analysis/{ref-rows,chain-rows}/` on
inferswarm01 (reference, extracted from `refphaseD/`) and inferswarm03
(chain last-stage, extracted from `phaseD-*-laststage/`), with
`ref-row-meta.json` / `chain-row-meta.json` recording per-row sha256
(verified against capture-internal record hashes). The underlying #81
artifacts under `/srv/inferswarm/state/i81/` were read read-only.

Historical preservation: #81 remains `CALIBRATION_SEMANTIC_FAIL`; R6
remains `R6_DENSE_ARCHITECTURE_FALSIFICATION_FAIL`; the #74 holdout
remains sealed (sha256 `23311c55…` unchanged). No threshold in this
directory derives from observed #81 values.
