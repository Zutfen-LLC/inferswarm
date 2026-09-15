# R8-F — Verified Node-Local Model Backing and Explicit Artifact Source Policy — Issue #200

Status: **Complete: `R8F_RUNTIME_LOCAL_BACKING_PREREQUISITE`**

Parent: [#188](https://github.com/Zutfen-LLC/inferswarm/issues/188) — R8
Qwen3.8-Flash-Next heterogeneous residency/execution program.

Starting `origin/main`: `f142a0d9b693f999685960c641b2a8fe362c4e1e` (PR #197
merge, exactly the SHA the issue names). No later `main` commit existed at
the time this record was produced, so no reconciliation was required.

## What this is

Implements and proves a **model-independent internal Source-policy seam**
over the accepted [ADR 0009](../../adr/0009-plan-driven-model-artifact-distribution.md)
/ [model-artifact-distribution.md](../../architecture/model-artifact-distribution.md)
architecture that Issue #99 and Issue #101 already established: given a
frozen Execution Plan's already-derived required artifact set, choose
between (a) an eligible verified Node-local backing/cache and (b) an
authorized non-local Source, without ever changing which Logical State Units
are required or treating whole-model local possession as a participant
feasibility prerequisite.

Then, using only already-committed, previously-accepted R8-D v2 evidence
(never re-executed, never requalified), mechanically determines whether the
pinned physical runtime (llama.cpp / `ggml-rpc-server`) can actually honor
that seam for a remote participant's assigned state without the client
retransmitting the same bytes — and reports honestly that it cannot, so the
bounded physical Qwen proof (Phase 5) correctly does not run.

## Authority consumed

- ADR 0009 (`docs/adr/0009-plan-driven-model-artifact-distribution.md`) —
  accepted;
- `docs/architecture/model-artifact-distribution.md` — accepted normative
  supplement;
- Issue #99 (`PLAN_DRIVEN_ARTIFACT_ACQUISITION_PASS`) —
  `scripts/issue99_artifact_core.py`, `scripts/issue99_proof.py`;
- Issue #101 (`PLAN_DRIVEN_ARTIFACT_ORCHESTRATION_PASS`) —
  `scripts/issue101_orchestration.py`, `scripts/issue101_fixture.py`,
  `scripts/issue101_proof.py`;
- R8-D v2 evidence from Issue #195 / PR #197 —
  `docs/investigations/qwen38-flash-next-r8-d-v2/`, in particular the exact
  committed launch-orchestration producer `scripts/issue195_v2_launch.py`
  (read-only; never re-executed; never requalified).

## Generic extension points changed

**None of the hash-pinned #99/#101 producers were modified.**
`scripts/issue99_artifact_core.py` and `scripts/issue101_orchestration.py`
remain byte-identical to the accepted evidence pinned in
`docs/implementation/plan-driven-artifact-acquisition-99/evidence/MANIFEST.sha256`
and `docs/implementation/plan-driven-artifact-orchestration-101/evidence/MANIFEST.sha256`
(verified by `tests/test_issue200_r8f_source_policy.py::StaticDisciplineTests::test_no_frozen_producer_bytes_changed`
and by the unchanged `test_issue99_*`/`test_issue101_*` suites).

R8-F is purely additive, composing the accepted classes' **public** surface
(`Coordinator.freeze/ingest/delta/source_index/validate_attempt/reconcile`,
`Node.cache/ledger/failures/lifecycle/source/inventory`,
`NodeArtifactCache.publish/inventory`) plus one narrow, legitimate OOP
extension:

- `scripts/issue200_r8f_source_policy.py`
  - `PolicyCoordinator(Coordinator)` — subclasses the accepted #101
    `Coordinator` and adds exactly one new method,
    `authorize_under_policy(delta, artifact_id, policy)`, that reuses the
    same frozen plan/requirements/inventory/exclusion state as the inherited
    `authorize` and differs only in *which* eligible Source it selects for
    the exact same already-required artifact. `authorize` itself (inherited,
    unmodified) keeps its exact accepted behavior for every existing #99/#101
    caller.
  - `acquire_under_policy(node, coordinator, ticket, source)` — for every
    ticket whose mode is `LOCAL_CACHE`, or whose Node does not already
    verify the artifact locally, this is byte-for-byte `Node.acquire`
    (inherited, unmodified). Only when the *policy itself* deliberately
    selected a non-local Source despite the Node already holding the exact
    verified bytes locally (the R1 controlled-comparison arm) does it bypass
    the ordinary already-verified shortcut, using only the same public
    cache/ledger primitives `acquire_artifact` itself uses
    (`begin_partial`/`append_partial`/`finish_partial`, `ledger.record`), so
    the authorized Source is genuinely read and the transferred bytes are
    honestly attributed. `coordinator.validate_attempt` (public, unmodified)
    remains the sole authorization gate either way.
  - `local_backing_accounting(node, participant_requirements)` — Phase 2:
    mechanically distinguishes required-bytes-satisfied-from-local-backing
    from retained-optional-backing-bytes, from the Node's own re-verified
    cache inventory.
  - `ledger_network_accounting(ledger_events)` — mechanically re-derives
    cache-hit/acquired/forced-transfer byte totals from ledger events,
    rather than trusting an authored claim (NC-11).
- `scripts/issue200_r8f_fixture.py` — a deterministic CPU release fixture
  (mirrors `issue101_fixture.py`) whose release (8 members) is larger than
  any one frozen plan's required subset, so a Node can hold a full release
  as optional local backing while a plan requires only part of it.
- `scripts/issue200_r8f_proof.py` / `scripts/issue200_r8f_terminal_reduction.py`
  — the compact campaign and terminal reducer.

## Internal Source-policy modes (Phase 1)

| Mode | Semantics | Fails closed when |
|---|---|---|
| `PREFER_LOCAL_VERIFIED` (default) | Use an eligible exact local verified Source first; otherwise fall back to an authorized non-local Source. Byte-identical ordering to accepted #101 `authorize`. | No local and no remote Source is eligible. |
| `REQUIRE_LOCAL_VERIFIED` | Only a local verified backing may satisfy the requirement. | No eligible local verified backing — **before any remote bytes move**. |
| `PREFER_REMOTE_AUTHORIZED` | Select an eligible non-local Source even when a local verified copy exists (controlled comparison). | No remote candidate and no local fallback. |
| `REQUIRE_REMOTE_AUTHORIZED` | Only a non-local authorized Source may satisfy the requirement. | No eligible non-local Source — **before a local cache hit is silently substituted**. |

Policy operates on Source *selection* for an already-frozen, unchanged
required artifact set. NC-5 mechanically proves the
`participant_requirements_digest` is identical across all four policies for
the same delta.

## Optional full-release local backing (Phase 2)

No new mutation primitive was needed: the accepted #101
`NodeArtifactCache.publish()` (verify-then-publish, content-addressed,
idempotent) already is the correct "ingest/register local durable objects
only after exact identity/provenance verification" operation the issue asks
for. `ReleaseFixture.stage_full_release(node)` calls it for every release
member without advertising them as a peer Source, demonstrating that a
Node's own `local_artifact_ids` eligibility already depends only on its own
re-verified cache contents (`NodeArtifactCache.inventory()`), never on
publication/advertisement.

`local_backing_accounting` then reports, purely from that re-verified
inventory and the frozen requirements document:

- `required_bytes_satisfied_from_local_backing` — bytes of the *exact*
  required artifact set already verified in this Node's own cache;
- `total_verified_local_backing_bytes` — every verified byte in the cache;
- `retained_optional_backing_bytes` — the surplus that satisfies no
  currently declared requirement.

A full 8-member release staged as backing while a plan requires only 1
member reports `required_bytes_satisfied_from_local_backing == 4`,
`retained_optional_backing_bytes == 28` — the surplus is visible and
accounted, never required, never promoted to residency (NC-6), and evicting
it does not disturb the one required member's realization
(`test_evicting_optional_backing_does_not_corrupt_required_realization`).

## Compact CPU proof (Phase 3)

All five canonical arms and both cross-arm invariants pass on the isolated
CPU release fixture (`scripts/issue200_r8f_proof.py::run_arms`, retained at
`evidence/arms.json`):

| Arm | Precondition | Policy | Result |
|---|---|---|---|
| L1 | local present | `PREFER_LOCAL_VERIFIED` | `LOCAL_CACHE` selected; `CACHE_HIT`; 0 newly-acquired bytes |
| L2 | local absent | `PREFER_LOCAL_VERIFIED` | `ORIGIN` selected; `ACQUIRED`; exact missing bytes |
| R1 | local present | `PREFER_REMOTE_AUTHORIZED` | `ORIGIN` selected despite local possession; `ACQUIRED` with `policy_forced_transfer: true`; real bytes attributed to the remote source |
| LREQ | local incomplete | `REQUIRE_LOCAL_VERIFIED` | `SOURCE_UNAUTHORIZED` before any ticket issued or remote byte read |
| RREQ | remote unavailable | `REQUIRE_REMOTE_AUTHORIZED` | `SOURCE_UNAUTHORIZED`; local Node's ledger stays empty (no silent substitution) |

`test_r8f_peer_variant_also_forces_real_transfer` additionally proves R1
against a `PEER_CACHE` Source, not only `ORIGIN`.

## Required negative controls

All 12 controls the issue lists are covered — 11 as runnable compact-CPU
controls (`evidence/negative-controls.json`), 1 (NC-12, physical-arm-only) as
a documented disposition citing the Phase 4 finding below:

1. wrong digest/model/revision identity never satisfies a requirement
   (`nc1`, `PROVENANCE_IDENTITY_MISMATCH`);
2. a corrupt member inside an otherwise-complete release is excluded from
   `local_artifact_ids` (`nc2`);
3. `REQUIRE_LOCAL_VERIFIED` never contacts the origin (`nc3`, request-count
   delta proof);
4. `REQUIRE_REMOTE_AUTHORIZED` never leaves a ledger event when it fails
   (`nc4`);
5. policy never changes the required-state digest (`nc5`);
6. a full local release cache never enlarges the required artifact set
   (`nc6`);
7. zero local backing remains fully feasible via remote acquisition (`nc7`);
8. a stale inventory (object removed after ingest) fails closed at
   acquisition rather than silently satisfying (`nc8`);
9. a content/name-mismatched file on disk never counts as verified backing
   (`nc9`);
10. the Coordinator mechanically rejects bulk bytes through the new seam too,
    incrementing `bytes_observed` (`nc10`);
11. a false authored "zero network bytes" claim is mechanically contradicted
    by `ledger_network_accounting` (`nc11`);
12. not runnable on a compact CPU fixture; see Phase 4/5 below (`nc12`).

## Phase 4 — the real Qwen/runtime seam

Traced mechanically from the exact committed R8-D v2 physical launch
orchestration (`scripts/issue195_v2_launch.py`, the producer that actually
launched the accepted R8-D v2 candidate arm on `inferswarm01/03/04`, pinned
llama.cpp commit `b29c606e28a01b1bc8c1351026a0fa6e616bf6c4`), reproduced by
`scripts/issue200_r8f_terminal_reduction.py::phase4_mechanical_finding`
(re-derived from the file's live text, not authored):

```text
CAND_SH  (client, inferswarm01):  llama-server -m {MODEL} ... --rpc {RPC_EP}
RPC03_G0 (backend, inferswarm03): ggml-rpc-server -H 0.0.0.0 -p 50052 -d CUDA0
RPC03_G1 (backend, inferswarm03): ggml-rpc-server -H 0.0.0.0 -p 50053 -d CUDA1
RPC04    (backend, inferswarm04): ggml-rpc-server -H 0.0.0.0 -p 50052 -d CUDA0
```

Only the client process is ever given a model path. Every `ggml-rpc-server`
backend process is launched with only `-H`/`-p`/`-d` — no model artifact of
any kind. The `ggml-rpc` wire protocol this pinned build implements
(`alloc_buffer`/`set_tensor`/`get_tensor`/`copy_tensor`/`graph_compute`) is a
generic remote compute/memory protocol driven entirely by client-originated
pushes.

Mechanical answers:

1. **Can a remote participant's assigned model state be materialized from
   that participant's own verified local backing without the client
   retransmitting the same bytes? No.** The RPC backend process has no
   model-loading capability of its own and no seam to open a
   participant-local verified artifact by content identity.
2. **Exact seam permitting it:** none exists in the pinned build.
3. **Where client-originated bytes are forced:** every RPC backend launch
   invocation omits a model path entirely, so every tensor byte an RPC
   backend process ever holds must originate from the client's `set_tensor`
   calls.

Client-local `mmap` of the checkpoint (client-local materialization staging)
is not confused with RPC-host-local backing consumption anywhere in this
finding or its evidence.

Per the issue's own hard constraint ("Do not change llama.cpp merely to
force this experiment to work... retain that as a substrate prerequisite"),
this stops the physical phase here rather than staging 72.5 GB for
appearance. The smallest narrow successor scope is recorded in
`evidence/terminal-reduction.json` and is explicitly out of scope for this
issue/session.

## Phase 5 — not run

Two independent reasons, both recorded in `evidence/terminal-reduction.json`
so neither is mistaken for the other:

1. **Substrate blocker (Phase 4, above)** — the pinned `ggml-rpc-server`
   cannot consume participant-local backing for its assigned tensors; this
   alone is sufficient under the issue's own hard constraint to stop the
   physical phase.
2. **Execution-environment constraint of this session** — this remote
   execution session has no SSH credentials, no `known_hosts` entries, and
   no DNS resolution for the R8-D physical fleet hostnames
   (`inferswarm01`/`03`/`04`); verified directly (`ssh -o BatchMode=yes`
   resolution failure, empty `~/.ssh`). This is reported separately because
   it is a property of *this session*, not of the architecture or runtime —
   a session with fleet access would still hit the Phase 4 blocker above.

No physical arm ran. No model was downloaded, staged, or claimed staged. No
network/local byte accounting for a physical arm exists because none was
produced; `evidence/terminal-reduction.json.physical_phase5_ran` is `false`
and carries no `staged_bytes`/`network_bytes` fields (NC-12,
`test_terminal_reduction_never_claims_physical_arm_ran`).

## Terminal

```
R8F_RUNTIME_LOCAL_BACKING_PREREQUISITE
```

The generic source-policy/local-cache capability is sound (compact seam
`PASS`, all negative controls fail closed), but the current pinned execution
substrate cannot consume participant-local immutable backing for
remote-assigned state without a runtime/backend change. This is a
successful architectural finding, not permission to patch the runtime in
this issue/session. No Qwen-specific generic planner branch was introduced.
No R8-D correctness adjudication was rerun or requalified — R8-D v2 evidence
was read, never re-executed.

## Validation

- `.venv/bin/python scripts/check_test_env.py` — doctor green;
- `.venv/bin/python -m unittest tests.test_issue99_artifact_core tests.test_issue99_proof tests.test_issue101_orchestration tests.test_issue101_proof` — unchanged, green (100 tests);
- `.venv/bin/python -m unittest tests.test_issue200_r8f_source_policy tests.test_issue200_r8f_proof` — green;
- `.venv/bin/python scripts/run_full_cpu_suite.py` — full CPU suite green;
- `.venv/bin/python scripts/finalize_repository.py --check` — green;
- `.venv/bin/python scripts/sync_project_status.py --check` — green (frontier untouched, following the same R8-B/C/D precedent of not advancing the roadmap frontier pointer for an R8 sub-investigation).

## Evidence layout

```
evidence/arms.json                    five canonical arms + cross-arm invariant
evidence/negative-controls.json       all 12 required negative controls
evidence/local-backing-accounting.json Phase 2 required-vs-optional accounting
evidence/producer-hashes.json         sha256 of every producer this record depends on
evidence/canonical-summary.json       pass/fail roll-up
evidence/isolation.json               mechanical network/process/path isolation record
evidence/terminal-reduction.json      Phase 4 finding + environment note + terminal
evidence/MANIFEST.sha256              integrity anchor over every retained/producer path
```
