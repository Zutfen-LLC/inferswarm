# Implementation plans

These documents turn InferSwarm's research roadmap into ordered engineering and
experiment sequences. They are subordinate to `ROADMAP.md`, `BENCHMARKING.md`,
accepted ADRs, canonical GitHub issues, and precommitted success criteria.

## Current sequence

| Phase | Plan | Current state |
|---|---|---|
| **Phase 0 — baseline and instrumentation** | [phase0-baseline.md](phase0-baseline.md) | **Active.** The FreeToken harness/runtime instrumentation is implemented and merged; canonical measurements, correctness reference, and routing/residency evidence are still outstanding. |
| **Phase 1 — two-GPU local POC** | [phase1-two-gpu-poc.md](phase1-two-gpu-poc.md) | **Planned / may begin implementation opportunistically.** Canonical Phase-1 measurement is blocked on the Phase-0 exit gates. |

The important distinction is between **tooling implemented** and **phase
complete**. Phase 0 is not complete merely because its benchmark harness has
landed; it completes only when its canonical evidence exists and the Phase-0
issues' acceptance criteria are satisfied.

Later phases should receive their own implementation plans only when prior
evidence makes their concrete sequence knowable. Do not pre-design Phase 5's
generic worker abstraction before the POCs have established the seam it must
represent.
