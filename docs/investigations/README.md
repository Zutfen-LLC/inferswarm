# Investigations

Research inputs: feasibility studies, hardware analyses, literature notes,
and other artifacts that *inform* InferSwarm's direction without being
architecture contracts. An investigation is evidence in, not a decision out —
decisions live in [ADRs](../adr/README.md).

## Conventions

- One Markdown file per investigation: `short_name.md`.
- Every quantitative claim carries one of the evidence labels from
  [../../BENCHMARKING.md](../../BENCHMARKING.md): MEASURED, CALCULATED,
  ESTIMATED, SPECULATIVE.
- Investigations are preserved as written, with a provenance header when they
  originated outside this repository. Findings are not silently rewritten;
  corrections or refutations are new documents that link back.

## Index

- [multi_gpu_moe_feasibility.md](multi_gpu_moe_feasibility.md) — the original
  secondary-GPU MoE feasibility investigation that preceded the standalone
  InferSwarm repository. Historical research input; not the architecture
  contract.

## Where new research artifacts go

New investigations land here with the conventions above. If an investigation
produces a consequential decision, it graduates into an ADR (proposed via PR)
and the investigation links to it.
