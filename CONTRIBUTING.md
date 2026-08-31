# Contributing to InferSwarm

InferSwarm is a Zutfen LLC open-source project. Contributions are welcome and
appreciated. This document explains what we expect and what you can expect from
us. (InferSwarm has its own policy; it is not copied from FreeToken or any other
project.)

## Start with the canonical docs

Before architecture/runtime work, read the documentation in this order:

1. [ADRs](docs/adr/README.md) — decisions and supersession;
2. [Fabric Doctrine](docs/architecture/fabric-doctrine.md) — normative detailed
   resource/residency/planning semantics;
3. [ARCHITECTURE.md](ARCHITECTURE.md) — derived overview;
4. [ROADMAP.md](ROADMAP.md) — current evidence-gated sequence;
5. [BENCHMARKING.md](BENCHMARKING.md) — evidence/benchmark contract.

The project is currently **doctrine-shaped, API-unfrozen**. Do not assume that a
conceptual term in the doctrine must become a public Python/Rust/C++ type with
the same name, and do not freeze a broad interface merely because a POC needs a
temporary internal structure.

## Ways to contribute

- Reproduce or refute benchmark results on your hardware — a hardware report
  (use the *Hardware report* issue template) with real numbers is a first-class
  contribution.
- Improve documentation and architecture reasoning.
- Investigate an open question (see [ROADMAP.md](ROADMAP.md)).
- Contribute code where the roadmap actually calls for it.

## Workflow

1. Fork the repository.
2. Create a branch for your change.
3. Make **one logical change per pull request**. A PR that mixes a refactor, a
   feature, and an unrelated typo sweep is hard to review and hard to revert.
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
- **No fabricated benchmark results.** Ever. If you don't have hardware to run
  a benchmark, say so — an honest "untested" is more useful than an invented
  number.
- **Fast but wrong is failure.** Performance evidence never overrides the
  declared correctness contract.

## AI-assisted contributions

AI-assisted contributions are allowed. The contributor remains responsible for
understanding and validating submitted code — if you submit it, you own it,
including its correctness, claims, and review responses. An AI-generated PR you
cannot explain does not meet the bar.

## Resource and backend work

Do not encode hardware/vendor behavior into a universal physical `Worker`
class or sprinkle vendor checks throughout generic placement logic.

The current doctrine separates:

- Nodes, Compute Units, Memory Resources, and Links/topology;
- Logical State Units and physical Materializations;
- Model Execution Strategy legality/economics;
- generic planning and operator policy;
- backend-native implementation details.

Vendor-specific code is expected inside a backend/strategy implementation when
that is what the experiment requires. The important requirement is that generic
resource/planner semantics do not become `if NVIDIA`, `if expert`, or `if CUDA
Graph` logic.

A backend may fuse multiple resources into one fast runtime executor when that
is the best correct implementation; that does not turn the fused executor into
the physical resource ontology.

## Model integrations

Keep model semantics behind the Model Execution Strategy boundary.

A model integration/strategy should establish things such as:

- logical state/execution units;
- legal split/grouping/dependency boundaries;
- state authority/reconstructibility semantics;
- legal representations/backends;
- correctness/equivalence rules;
- relevant structural demand and strategy-specific costs.

The generic planner chooses among legal arrangements using the Swarm resource
graph, evidence, workload/profile information, and operator policy. PRs that
teach the generic planner model-family nouns such as `expert`, router, Qwen, KV
cache, or SSM as universal concepts will be asked to move that logic behind the
strategy seam.

## Residency and memory accounting

For changes that materialize state across RAM/accelerator memory, distinguish:

- persistent required state;
- persistent optional cache/replica state;
- transient staging/conversion/transfer peak;
- unexplained duplication.

Do not rely on process RSS alone when a claim concerns whether a specific host
materialization persists. Accelerator residency must not inherently require an
equivalent persistent host mirror; intentional RAM copies are still valid when
they have an explicit role and are accounted.

## Historical versus current docs

Completed benchmark/investigation/implementation records may retain terms such
as `primary`, `secondary`, L0/L1/L2/L3, or `worker` where those terms accurately
describe the experiment at the time. Do not mechanically rewrite historical
evidence into current doctrine vocabulary.

If a historical planning document could be mistaken for active guidance, add a
clear forward scope/supersession note rather than changing its measured facts.

## Repository conventions

- **[ADRs](docs/adr/README.md)** record consequential architecture decisions. If
  your change establishes one, propose an ADR with your PR.
- **[Fabric Doctrine](docs/architecture/fabric-doctrine.md)** is the normative
  detailed architecture synthesis. A material doctrine change requires an ADR;
  it must not arrive silently through `ROADMAP.md` or implementation prose.
- **[Investigations](docs/investigations/README.md)** document research inputs,
  with every number labeled MEASURED / CALCULATED / ESTIMATED / SPECULATIVE per
  the [benchmark contract](BENCHMARKING.md).
- **Commit messages** follow Conventional Commits (`feat:`, `fix:`, `docs:`,
  `chore:`, ...).

## Licensing

By contributing, you agree your contribution is licensed under the Apache
License 2.0 (the project's license, see [LICENSE](LICENSE)). You retain
copyright; if you want credit in the file header, add it.

## Questions

Open an issue and ask. Research-stage projects have fewer dumb questions than
shipping ones — uncertainty is part of the job.
