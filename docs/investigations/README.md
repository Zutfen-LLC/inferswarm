# Investigations

Research inputs: feasibility studies, hardware analyses, literature notes, and
other artifacts that *inform* InferSwarm's direction without being architecture
contracts.

Repository precedence is:

> **[ADRs](../adr/README.md) decide; the
> [Fabric Doctrine](../architecture/fabric-doctrine.md) specifies;
> `ARCHITECTURE.md` explains; `ROADMAP.md` sequences.**

An investigation is evidence in, not a decision or doctrine update out.

## Conventions

- One Markdown file per investigation: `short_name.md`.
- Every quantitative claim carries one of the evidence labels from
  [../../BENCHMARKING.md](../../BENCHMARKING.md): MEASURED, CALCULATED,
  ESTIMATED, SPECULATIVE.
- Investigations are preserved as written, with a provenance header when they
  originated outside this repository. Findings are not silently rewritten;
  corrections/refutations are new evidence that links back.
- Historical investigations may retain first-strategy terminology such as
  `primary`, `secondary`, `worker`, or expert-specific placement. Those terms
  do not become current generic doctrine merely because they appear in a
  preserved research artifact.

## Index

- [multi_gpu_moe_feasibility.md](multi_gpu_moe_feasibility.md) — the original
  secondary-GPU MoE feasibility investigation that preceded the standalone
  InferSwarm repository. Historical research input; not the architecture
  contract.

## Where new research artifacts go

New investigations land here with the conventions above. If an investigation
produces a consequential architecture decision, propose an ADR and synchronize
the Fabric Doctrine if the decision changes normative semantics. A roadmap or
implementation note must not silently override the ADR/doctrine layer.
