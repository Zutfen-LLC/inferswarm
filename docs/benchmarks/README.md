# Benchmarks

This directory holds InferSwarm benchmark results and methodology artifacts.
The governing contract is [../../BENCHMARKING.md](../../BENCHMARKING.md): full
provenance, honest evidence labels, context-valid A/B baselines, end-to-end
claims backed by end-to-end evidence, and correctness checks.

Historical result records keep the schema/terminology that belonged to their
frozen experiment. New results should use current Fabric Doctrine concepts where
useful without inventing a prematurely stable database schema.

## Layout

Results are grouped by experiment/campaign according to the methodology that
created them. A simple recommended shape for new bounded experiments is:

```text
docs/benchmarks/
├── README.md
└── results/
    └── <experiment-or-campaign>/
        ├── result.json       ← machine-readable record where useful
        └── SUMMARY.md        ← human-readable summary
```

Do not create fake result placeholders. A result directory should correspond to
real retained evidence or an explicitly documented frozen methodology/artifact.

## Result format

A new machine-readable result should include the applicable provenance required
by the benchmark contract. Conceptually:

```json
{
  "label": "MEASURED",
  "date": "YYYY-MM-DD",
  "inferswarm_commit": "<sha>",
  "host_runtime_commit": "<sha>",
  "model": {
    "repository": "...",
    "revision": "...",
    "representation": "...",
    "strategy": "..."
  },
  "hardware": {
    "cpu": "...",
    "ram": "...",
    "compute_units": ["..."],
    "memory_resources": ["..."],
    "driver_runtime": "...",
    "local_topology": "...",
    "network": {"topology": "...", "rate": "..."}
  },
  "plan": {
    "frozen_description": "...",
    "state_residency": "...",
    "strategy_boundary": "...",
    "operator_constraints": "..."
  },
  "workload": {
    "fixture": "...",
    "batch_or_concurrency": "...",
    "context_or_input_length": 0,
    "output_length": 0
  },
  "results": {
    "ttft_ms": null,
    "prefill_tps": null,
    "decode_tps": null,
    "per_token_ms": null
  },
  "baseline": {"experiment": "...", "comparison": "..."},
  "correctness": {"reference": "...", "metric": "...", "deviation": "..."}
}
```

This is illustrative, not a frozen schema. A strategy-specific experiment may
need fields that do not belong in every result, and historical result schemas
must not be retroactively rewritten merely to match this example.

For residency/capacity claims, include component/materialization accounting when
needed to distinguish persistent required, persistent optional, transient peak,
and unexplained duplication. Process RSS alone may be supporting evidence but
is not sufficient for claims about whether a particular materialization
persists.

## Ground rules

- Every number carries a label: MEASURED, CALCULATED, ESTIMATED, or SPECULATIVE.
- ESTIMATED/SPECULATIVE reasoning belongs in investigations or clearly labeled
  methodology discussion rather than masquerading as retained measurements.
- Hardware benchmarks run on trusted, explicitly declared hardware — not public
  CI (see [../../SECURITY.md](../../SECURITY.md)).
- Results are immutable once committed; corrections are new records/annotations
  that preserve the earlier provenance rather than silently changing history.
- Demand observations are not performance results. A placement predicted from
  an Adaptive Demand Profile must still be measured before claiming a speedup.
- Strategy-specific fields such as expert placement may appear in the result for
  an expert experiment; they are not generic mandatory benchmark fields.
