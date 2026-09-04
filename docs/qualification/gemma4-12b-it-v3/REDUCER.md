# v3 reducer binding (issue #86)

The numerical reducer is REUSED, not redefined: the frozen v1 identity

```
host-float64/full-domain/nearest-rank-higher-p99/per-case-family-max/1
```

implemented byte-identically in `scripts/issue74_methodology.py`
(`tensor_metrics`, `conservative_case_family`, `nearest_rank_higher`; the
living v1 `MANIFEST.sha256` test proves byte-identity), governs all 15
envelope families: host float64 arithmetic, full checkpoint domain,
nearest-rank-higher p99, per-case family maximum, finite-only,
inclusive `observed <= frozen_limit`, and
`limit[e] = max(statistical_max[e], stress_max[e])` over the exact 576
statistical + 8 selected stress cases.

New v3-only reductions (frozen in `scripts/issue86_v3_methodology.py`):

```
decision_local_error(row) = max_{i in D(r)} |candidate_i - reference_i|
case_E_D(case)            = max over all 8 canonical-prefix decisions
statistical_E_D           = max case_E_D over the exact 576 c86-* cases
stress_E_D                = max case_E_D over the exact 8 selected p86-* cases
E_D                       = max(statistical_E_D, stress_E_D)
```

E_D reducer identity string (carried in the v3 threshold manifest):

```
case_E_D=max over 8 decisions of decision_local_error; statistical_E_D=max
over 576 statistical cases; stress_E_D=max over 8 selected stress cases;
E_D=max(statistical_E_D,stress_E_D)
```

Exact hexadecimal binary64 serialization everywhere; no rounding, no
manual editing, no empirical safety factor. Threshold derivation verifies
per-case that the stated `case_e_d` equals the max over the case's own 8
decision rows (exact binding, machine-checked).

The independent sampling unit is the case, not the token row:
within-case decision/checkpoint values are reduced conservatively (max)
before the across-case maximum.
