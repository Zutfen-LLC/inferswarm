# Documentation map

InferSwarm is a research repository. Most of it is retained evidence, and the
rules for reading it matter as much as the content.

Repository precedence is:

> **[ADRs](adr/README.md) decide; the
> [Fabric Doctrine](architecture/fabric-doctrine.md) specifies;
> [ARCHITECTURE.md](../ARCHITECTURE.md) explains;
> [ROADMAP.md](../ROADMAP.md) sequences.**

A lower layer never silently overrides a higher one. An implementation note or
roadmap paragraph cannot change normative doctrine; that requires an ADR.

## Where to start

| If you want to | Read |
|---|---|
| understand what the project is | [README.md](../README.md) |
| understand the architecture | [ARCHITECTURE.md](../ARCHITECTURE.md), then the [Fabric Doctrine](architecture/fabric-doctrine.md) |
| know why something was decided | [ADRs](adr/README.md) |
| know what happens next | [ROADMAP.md](../ROADMAP.md) |
| publish a number | [BENCHMARKING.md](../BENCHMARKING.md) |
| contribute | [CONTRIBUTING.md](../CONTRIBUTING.md) |
| run the checks | [`tests/README.md`](../tests/README.md) |
| understand a script | [`scripts/README.md`](../scripts/README.md) |
| understand which CI checks run for a change | [CI impact planning](ci-impact-planning.md) |

## Directories

### [`adr/`](adr/README.md) — architecture decision records

Twelve accepted decisions, numbered and immutable once accepted. ADR 0008
adopts the Fabric Doctrine as the canonical resource/residency/planning model;
ADRs 0009-0012 adopt the normative supplements.

### [`architecture/`](architecture/README.md) — normative doctrine

The Fabric Doctrine and its two adopted supplements. This is the only layer
that *specifies* semantics.

### [`benchmarks/`](benchmarks/README.md) — methodology and measured results

Phase-0 and Phase-1 campaign records, the frozen Phase-0 workload fixtures,
and raw per-workload data. Results are immutable once committed; corrections
are new records that preserve the earlier provenance.

### [`implementation/`](implementation/README.md) — experiment plans and retained proofs

One directory or document per bounded research question, spanning Phase 0
through the current issue #117 integration gate. Completed plans stay because
their methodology is provenance, not because they are still guidance.

### [`investigations/`](investigations/README.md) — research inputs

Feasibility studies and hardware analyses that *inform* direction without
being contracts. Every quantitative claim carries a `MEASURED` /
`CALCULATED` / `ESTIMATED` / `SPECULATIVE` label.

### [`protocols/`](protocols/README.md) — semantic-boundary and transport notes

Constraints a future wire protocol must satisfy, extracted from real
experiments. Deliberately not a frozen schema.

### [`qualification/`](qualification/README.md) — the correctness-qualification lane

The v1 through v5 heterogeneous numerical-equivalence methodologies, their
physical campaigns, the diagnoses of each failure, and the doctrine decisions
those diagnoses produced. This lane terminated `V5_QUALIFICATION_PASS`.

### [`phase1-poc-success-criteria.md`](phase1-poc-success-criteria.md)

The frozen Phase-1 acceptance criteria, retained as historical provenance for
the canonical `NO-GO` verdict.

## Living project status

[Status maintenance](status-maintenance.md) describes the shared
[status record](project-status.json), generated sections, CI drift check, and
the documentation-impact review required for changes to project capabilities
or execution scope. The record summarizes linked authority; it does not issue
execution permission.

## Reading rules

These apply to every directory above.

- **Historical evidence is immutable.** Accepted records are not rewritten
  because the architecture vocabulary improved, because a later experiment
  disagreed, or because a result was disappointing. A correction is a new
  record that links back.
- **Old vocabulary stays.** Terms such as `primary`, `secondary`, `worker`,
  L0/L1/L2/L3, or expert-specific placement may appear in preserved records.
  They describe that experiment accurately; they are not current doctrine
  unless ADR 0008 and the Fabric Doctrine reaffirm them.
- **A frozen methodology area describes itself at freeze time.** It does not
  get updated with the outcome. The matching `*-campaign-*` directory carries
  the verdict.
- **Negative results are preserved.** `NO-GO`,
  `R6_DENSE_ARCHITECTURE_FALSIFICATION_FAIL`, `V3_HOLDOUT_FAIL`, and
  `V4_HOLDOUT_CORE_FAIL` are part of the record, not embarrassments to edit
  away.
- **If a historical planning document could be mistaken for active
  guidance**, add a forward scope/supersession note rather than changing its
  measured facts.
<!-- validation-only docs note for Issue #148 targeted-mode proof -->
