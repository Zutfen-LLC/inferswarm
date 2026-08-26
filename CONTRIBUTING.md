# Contributing to InferSwarm

InferSwarm is a Zutfen LLC open-source project. Contributions are welcome and
appreciated. This document explains what we expect and what you can expect
from us. (InferSwarm has its own policy; it is not copied from FreeToken or
any other project.)

## Ways to contribute

- Reproduce or refute benchmark results on your hardware — a
  hardware report (use the *Hardware report* issue template) with real
  numbers is a first-class contribution.
- Improve documentation and architecture reasoning.
- Investigate an open question (see [ROADMAP.md](ROADMAP.md)).
- Contribute code where the roadmap actually calls for it.

## Workflow

1. Fork the repository.
2. Create a branch for your change.
3. Make **one logical change per pull request**. A PR that mixes a refactor,
   a feature, and a typo sweep is hard to review and hard to revert.
4. Open a pull request against `main` using the
   [pull request template](.github/pull_request_template.md).
5. Respond to review feedback.

## Tests and benchmarks

- **Tests are required where applicable.** Documentation-only changes don't
  need tests; anything executable does.
- **Benchmarks are required for performance claims.** Any PR that claims a
  performance change must include a before/after A/B comparison per
  [BENCHMARKING.md](BENCHMARKING.md), with full provenance.
- **Exact hardware disclosure is required for hardware-dependent results** —
  GPU model, VRAM, driver, CPU, RAM, network link, topology.
- **Exact model disclosure is required for model-dependent results** — model
  repository, checkpoint revision, quantization/weight format.
- **No fabricated benchmark results.** Ever. Fabricating results is grounds
  for rejection of the contribution and, for repeat cases, of the
  contributor. If you don't have hardware to run a benchmark, say so — an
  honest "untested" is more useful than an invented number.

## AI-assisted contributions

AI-assisted contributions are allowed. The contributor remains responsible
for understanding and validating submitted code — if you submit it, you own
it, including its correctness, its claims, and its review responses. An
AI-generated PR you cannot explain does not meet the bar.

## Hardware backends

Prefer implementing a capability backend against a stable worker interface
rather than adding vendor-specific conditions throughout the scheduler.
Vendor-specific branches sprinkled through placement logic are how
heterogeneity stops being first-class. (Current backend state:
[ARCHITECTURE.md](ARCHITECTURE.md#heterogeneous-hardware-future-direction).)

## Model integrations

Keep model semantics separate from resource-placement policy. A model's code
should describe what the model computes; where inputs live and where
execution happens belongs to the fabric. PRs that entangle the two will be
asked to separate them.

## Repository conventions

- **[ADRs](docs/adr/README.md)** record consequential architecture
  decisions. If your change establishes one, propose an ADR with your PR.
- **[Investigations](docs/investigations/README.md)** document research
  inputs, with every number labeled MEASURED / CALCULATED / ESTIMATED /
  SPECULATIVE per the [benchmark contract](BENCHMARKING.md).
- **Commit messages** follow Conventional Commits
  (`feat:`, `fix:`, `docs:`, `chore:`, ...).

## Licensing

By contributing, you agree your contribution is licensed under the Apache
License 2.0 (the project's license, see [LICENSE](LICENSE)). You retain
copyright; if you want credit in the file header, add it.

## Questions

Open an issue and ask. Research-stage projects have fewer dumb questions
than shipping ones — uncertainty is part of the job.
