# Benchmarks

This directory holds InferSwarm benchmark results and methodology artifacts.
The rules that govern them are the contract in
[../../BENCHMARKING.md](../../BENCHMARKING.md): full provenance, honest
labels, A/B baselines, end-to-end evidence, correctness checks.

## Layout

Results live under a per-experiment directory, one directory per experiment
run:

```
docs/benchmarks/
├── README.md          ← this file
└── results/
    └── YYYY-MM-DD-short-name/
        ├── result.json       ← machine-readable record
        └── SUMMARY.md        ← human-readable summary
```

Do not create result directories or files until real results exist — no
placeholders, no fake data. (At the time of this writing there are none;
Phase 0 of the [roadmap](../../ROADMAP.md) produces the first.)

## Result format

The recommended record is JSON with, at minimum, the provenance fields the
contract requires:

```json
{
  "label": "MEASURED",
  "date": "YYYY-MM-DD",
  "inferswarm_commit": "<sha>",
  "freetoken_commit": "<sha>",
  "model": {"repository": "...", "revision": "...", "format": "..."},
  "hardware": {
    "cpu": "...", "ram": "...", "gpus": ["..."], "driver": "...",
    "runtime": "CUDA 12.x",
    "pcie_topology": "...", "network": {"topology": "...", "rate": "1 GbE"}
  },
  "config": {
    "vram_policy": "...", "ram_policy": "...", "expert_placement": "..."
  },
  "workload": {"prompt": "...", "batch_size": 1, "context_length": 0, "output_length": 0},
  "results": {
    "ttft_ms": null, "prefill_tps": null, "decode_tps": null,
    "per_token_ms": null
  },
  "baseline": {"experiment": "...", "comparison": "..."},
  "correctness": {"reference": "...", "metric": "...", "deviation": "..."}
}
```

Treat the schema above as a starting convention, not a frozen contract — it
will be refined by the first real experiments. A deliberate non-goal for now:
no elaborate database schema, no aggregation tooling. Structured JSON plus a
human summary is enough until real result volume says otherwise.

## Ground rules

- Every number carries a label: MEASURED, CALCULATED, ESTIMATED, or
  SPECULATIVE.
- ESTIMATED/SPECULATIVE numbers belong in
  [investigations](../investigations/README.md), not in results/.
- Hardware benchmarks run on trusted, explicitly-declared hardware — not
  public CI (see [../../SECURITY.md](../../SECURITY.md)).
- Results are immutable once committed; corrections are new entries that
  supersede, with a note.
