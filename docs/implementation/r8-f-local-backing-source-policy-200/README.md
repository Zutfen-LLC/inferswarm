# R8-F — Verified Node-Local Model Backing and Explicit Artifact Source Policy — Issue #200

Status: **Complete: `R8F_LOCAL_VERIFIED_BACKING_PASS`** (Phase 5 executed
2026-09-16; mechanically derived, see Phase 5 below).

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
(never re-executed, never requalified), it retains the corrected Phase-4
finding: the pinned runtime exposes a `-c` / `RPC_CMD_SET_TENSOR_HASH` cache
seam, but the bounded non-Qwen experiment does not establish the actual Qwen
payload/chunk boundary. Phase 5 therefore remains required.

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

## Correction notice (this revision)

An earlier revision of this record inferred, from the single fact that the
accepted R8-D v2 launch (`scripts/issue195_v2_launch.py`) never passes a
model path to any `ggml-rpc-server` backend invocation, that **no
participant-local-backing seam exists at all** in the pinned runtime, and
emitted `R8F_RUNTIME_LOCAL_BACKING_PREREQUISITE` on that basis. That
inference was incomplete: it never inspected the pinned
`ggml-rpc-server`'s own local-cache implementation. It is **retracted** and
replaced by the corrected Phase 4 treatment below, which mechanically tested
that cache seam against the actual pinned binary. The generic Phase 1–3
source-policy/local-backing seam (below) is unaffected and unchanged.

## Phase 4 — the real Qwen/runtime seam, corrected

### 4a. The narrow, still-true launch-configuration fact

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

Only the client process was given a model path in *this specific launch*,
and no RPC backend received `-c`/`--cache` either. This fact is scoped to
this one launch configuration and, by itself, proves only that R8-D v2 never
exercised any backend-local materialization path — it does **not** prove the
pinned runtime lacks one.

### 4b. The pinned RPC local-cache seam, mechanically tested

The pinned build separately implements a local file cache for large
tensors, entirely independent of the model-path question above. Immutable
identity of the exact pinned files inspected (fetched read-only from
`https://github.com/ggml-org/llama.cpp` at the pinned commit; never vendored,
never modified — see `evidence/rpc-cache-mechanism.json` for full sha256s):

| File | sha256 |
|---|---|
| `tools/rpc/rpc-server.cpp` | `14f69793a377a79f2476a190da1f80bac079cfeb4a83df13ffd378d3435d974a` |
| `tools/rpc/README.md` | `f3ca2fcfadf926ec60115da8102cedf08f0701f60f62c16ff42f56f87dd819da` |
| `ggml/src/ggml-rpc/ggml-rpc.cpp` | `07ca713158d222959b4415e74e0bee83119212aad85750ff6240773365c0b2d9` |
| `ggml/include/ggml-rpc.h` | `505c01e4575c06a3b01cdbbb5688368baaabf6223a36eeafd918057251da6e43` |
| `ggml/src/ggml-rpc/transport.h` | `fec7abf4e6cebec0d20e3350c01f2f47d495f90a79c6d829870e09d8a7ef2219` |

Mechanics read directly from those files:

- `-c`/`--cache` (`rpc-server.cpp`) enables a local file cache under
  `$LLAMA_CACHE/rpc/` (default `$HOME/.cache/llama.cpp/rpc/`).
- For any `set_tensor` payload larger than `HASH_THRESHOLD` (10 MiB,
  `ggml-rpc.cpp`), the client first sends `RPC_CMD_SET_TENSOR_HASH` — an
  FNV-1a hash (`fnv_hash`) of the exact bytes it is about to send — instead
  of the payload. If the server finds a file at
  `<cache_dir>/<16-hex-fnv1a-hash>`, it loads that file into the tensor's
  backend memory and reports a hit; the client then **skips the full
  `SET_TENSOR` transfer entirely**. On a miss, the client falls back to the
  full transfer, and the server writes what it received to that same path.
- `rpc_server::get_cached_file` trusts whatever bytes are stored at that
  filename and **never re-hashes the file's own content** before serving
  it — the FNV-1a name is upstream's internal dedup key, not a
  content-integrity check.

### 4c. Bounded non-Qwen experiment (this correction)

Because the code alone doesn't settle *retransmission is actually
suppressed* or *pre-staged content is actually consumed*, this correction
built the pinned `ggml-rpc-server` binary from the pinned commit (CPU-only,
`-DGGML_RPC=ON`, no llama.cpp source modified) and drove it with an external
driver (`evidence/rpc-cache-experiment-raw/driver.cpp`) that calls only the
pinned public backend API (`ggml_backend_rpc_buffer_type`,
`ggml_backend_alloc_ctx_tensors_from_buft`, `ggml_backend_tensor_set/get`).
A deterministic 12 MiB fixture (`gen_fixture.py`, just over `HASH_THRESHOLD`)
stands in for a tiny slice of the real release. Network bytes were measured
independently via `strace` on the client's own `send`/`recv` syscalls, not
by trusting either side's self-reporting. Full results:
`evidence/rpc-cache-experiment.json`; raw per-phase strace/server logs:
`evidence/rpc-cache-experiment-raw/raw-logs/`.

| Phase | Setup | `SET` phase bytes sent | Result |
|---|---|---:|---|
| A — cold | fresh empty cache, first-ever contact | 12,583,546 | full payload sent (cache miss, as expected) |
| B — warm, restarted | **new server process**, same on-disk cache from A | 321 | hash-probe only — payload retransmission suppressed after a restart (durable, not in-memory) |
| C — pre-staged | brand-new server, bytes written to the predicted cache path **before any client ever connected** | 321 | hash-probe hit on first-ever contact — pre-staged verified backing consumed with **zero** prior network pass |
| D — wrong content | predicted cache path holds different bytes | 321 (hit) | server served the wrong bytes; client-side `get` detected the mismatch (upstream itself did not) |
| E — truncated | predicted cache path holds a half-length prefix | 321 (hit) | server served truncated data with a silently unwritten tail; client-side `get` detected the mismatch |

Mechanical conclusions (`evidence/rpc-cache-mechanism.json`,
`mechanical_cache_finding`):

1. **Can participant-local durable state avoid retransmission of identical
   assigned tensor bytes? Yes** — phase B, across a full server-process
   restart, using only the on-disk cache.
2. **Can that mechanism consume an InferSwarm-verified operator-prestaged
   immutable release directly, with no prior network pass? Yes** — phase C.
3. **Case classification: C** — *"existing cache can consume pre-staged
   backing with a bounded external adapter, no llama.cpp modification."* The
   adapter's job is narrow: verify InferSwarm provenance for a participant's
   assigned tensor, then write those exact bytes to
   `<cache_dir>/<fnv1a-hex>` before the client connects. This is a
   staging/materialization step; it changes no Logical State Unit
   requirement, no placement decision, and no planner semantics.
4. **Is a correctness-bearing llama.cpp/runtime modification required? No**,
   for whole-tensor (single-chunk, offset-0) assignments — proven above. An
   explicit, honest boundary: this experiment does not prove (and does not
   assume) the same result for a tensor fragmented into multiple
   `(offset, size)` sub-ranges by llama.cpp's own runtime tensor-split
   logic; reproducing those exact chunk boundaries ahead of time is left
   open, not claimed.
5. **Is the upstream FNV-1a filename InferSwarm trust authority? No** —
   phases D and E mechanically prove the pinned server is fail-open: it
   trusts whatever bytes sit at the predicted filename with no
   re-verification. Any adapter populating this cache **must** perform
   InferSwarm's own SHA-256/provenance verification before writing to the
   cache path; the FNV-1a name is never sufficient by itself, and this
   record never claims the upstream cache meets Issue #200's verification
   bar on its own.

Client-local `mmap` of a checkpoint (client-local materialization staging)
is still not confused with RPC-host-local backing consumption anywhere in
this record.

## Phase 5 — not run in this session (legal seam established; physical proof outstanding)

Two independent facts, both recorded in `evidence/terminal-reduction.json`
so neither is mistaken for the other:

1. **No substrate blocker** — Phase 4 above mechanically establishes a
   legal, non-runtime-modifying seam (Case C). This alone does **not**
   satisfy Issue #200: it shows the architecture question has a positive
   answer, not that the bounded physical Qwen proof happened.
2. **Execution-environment constraint of this session** — this remote
   execution session can resolve the fleet hostnames but has no usable SSH
   credential (a BatchMode probe was rejected). This is a property of *this
   session*, not of the architecture or runtime.

No physical arm ran. No model was downloaded, staged, or claimed staged. No
network/local byte accounting for a physical arm exists because none was
produced; `evidence/terminal-reduction.json.physical_phase5_ran` is `false`
and carries no `staged_bytes`/`network_bytes` fields (NC-12,
`test_terminal_reduction_never_claims_physical_arm_ran`).

`evidence/terminal-reduction.json.physical_phase5_handoff` records the exact
scope for whoever runs Phase 5 next: the accepted Qwen3.8-Flash-Next
UD-IQ1_S release and hashes, the bounded provenance-verifying adapter
described above, a remote/cold arm, a local-verified arm (identical required
state and placement, pre-staged, zero prior network pass), the local-verified
arm repeated once, and the exact network/timing/identity evidence to retain.
`scripts/issue200_r8f_physical.py` derives every acceptance predicate from
checksum-bound raw receipts, the accepted R8-D member authority, and observed
SET_TENSOR boundaries. For each staged range, the CPU-only
`scripts/issue200_r8f_range_receipt.py` opens the node-local accepted member,
checks its complete size/SHA-256, reads the exact range, retains its bytes,
and emits the bound measurement receipt. Network totals are not a JSON event
claim: `scripts/issue200_r8f_network_reduce.py` re-parses a retained,
process-wide PID/TID/endpoint-bound `strace -xx` capture and maps exact raw
sends to those observed payload bytes. It rejects authored summary booleans
and classifications. The Phase-5 capture contract is one exact argv, bound to
the recorded root client PID:

```text
strace -f --always-show-pid -ttt -xx -s 0 -e trace=network,write,writev -p <client-pid>
```

`-f`, `--always-show-pid`, `-s 0`, and `-xx` are mandatory. `-f -p` follows
the root client's threads and later descendants; every PID-prefixed syscall
in the retained stream is accounted as a captured tracee, never filtered back
to only the root PID. The reducer rejects a relevant `sendto` whose argument
is abbreviated (`...`), malformed, short, or whose result does not bind the
exact retained bytes. It accepts target traffic only after the retained trace
contains a successful target `connect()` for its FD; authored capture boundary
strings cannot substitute for that connection provenance. It also rejects a
bound-peer `send`/`sendmsg`/`sendmmsg`/`write`/`writev` (including a write on
a connected FD whose earlier `socket()` predates attachment) rather than
silently excluding it. Unrelated stdout/stderr writes remain distinguishable.
This makes an absent, incomplete, or root-PID-only raw capture incapable of
proving zero reacquisition. Every accepted range measurement and
participant-local cache-staging receipt is additionally bound to the same
`SET_TENSOR` payload participant, so one node's backing cannot prove another
node's assignment. No such Phase-5 evidence exists here, so `PASS` is not
reachable here.

## Phase 5 — bounded physical Qwen proof (executed 2026-09-16)

The bounded physical comparison the issue requires was executed on the fleet
against the real accepted release, the pinned R8-D binaries, and the exact
process-wide capture contract. Everything below is mechanically derived from
retained raw receipts; the committed validator
(`scripts/issue200_r8f_physical.py`, schema `inferswarm.issue200.physical-phase5/3`)
independently re-derives every acceptance predicate and the terminal reducer
consumes only its verdict.

### Frozen subject (identical across all three arms)

- Client: `inferswarm01`, pinned `llama-server`
  (`de3a8a545e2f5995f80ff23f60776fedc30edca67f0e09f3bc47c845156e3411`).
- One remote RPC participant: `inferswarm04` `RPC0[10.0.0.204:50052]`
  (RTX 3090, `GPU-ecda1aaa-0c66-857b-8218-3d511dc75c03`, BDF `01:00.0`),
  pinned `ggml-rpc-server`
  (`a897f908add3305658e6b4f996880033d07ede0800fff71dbc46e90230acdfe9`, matching
  the accepted R8-D host inventory). `inferswarm04` was selected because it is
  the simplest and highest-capacity accepted R8-D RPC participant (single GPU,
  24 GiB, holds no other role), and its assignment carries a cache-eligible
  tensor payload (10,813,440 bytes) larger than the pinned RPC
  `HASH_THRESHOLD` (10 MiB).
- Required state: one Logical State Unit — tensor `blk.24.attn_gate.weight`
  (Q5_K, `[2560, 6144]`, 10,813,440 bytes, the smallest cache-eligible tensor
  of the accepted release) of member
  `Qwen3.8-Flash-Next-UD-IQ1_S-00003-of-00003.gguf`, file range
  `[848968992, 848968992+10813440)`, placed on the participant via
  `-ot 'blk\.24\.attn_gate\.weight=RPC0[10.0.0.204:50052]'`; every other
  tensor stays exactly where the accepted R8-D placement put it
  (client-local; `-ngl 0 -c 8192`, `--no-warmup`, load subject = model
  initialization to `listening on http://`).
- Backing authority: the participant's own copy of member 3, full
  SHA-256-verified (`0e25ceaeb89b8a80aa973c6c0c7448943682f7408c2855b2ebd016b7643a861a`)
  against the accepted R8-D split-rehash authority before any staging.

### Actual observed Qwen SET_TENSOR payload boundary

The pinned client transfers the whole tensor as ONE framed RPC message
emitted by a single `send()` syscall of a worker TID:
`cmd(1) + size(8) + rpc_tensor + offset(8) + payload` — observed wire length
10,813,744 bytes for the 10,813,440-byte payload (304-byte framing
overhead), preceded by a `RPC_CMD_SET_TENSOR_HASH` probe because the payload
exceeds `HASH_THRESHOLD`. There is no sub-tensor fragmentation at this
boundary, and the earlier synthetic experiment's assumption of bare-payload
syscalls was wrong in exactly one respect: the payload is the suffix of a
framed record. The Phase-5 network reducer
(`scripts/issue200_r8f_network_reduce.py`, schema
`inferswarm.issue200.network-reduction/3`) was corrected accordingly (see
"Phase-5 reducer correction" below) before the canonical arms ran.

### Arms and mechanically derived network accounting

| Arm | Policy / Source | immutable payload bytes | control/hash-probe bytes | total client-to-server | init wall |
|---|---|---:|---:|---:|---:|
| A cold_remote | `PREFER_REMOTE_AUTHORIZED` / `REMOTE_AUTHORIZED` | 10,813,440 | 80,335 | 10,893,775 | 2.643 s |
| B local_verified | `REQUIRE_LOCAL_VERIFIED` / `LOCAL_VERIFIED` | **0** | 80,022 | 80,022 | 2.626 s |
| C repeat_local_verified | `REQUIRE_LOCAL_VERIFIED` / `LOCAL_VERIFIED` | **0** | 80,022 | 80,022 | 2.621 s |

All three arms carry identical required-state, participant-requirements,
placement, and materialization identities (validator-enforced), identical
SET_TENSOR payload boundaries, and the exact capture contract
`strace -f --always-show-pid -ttt -xx -s 0 -e trace=network,write,writev -p <client-pid>`
with the full traced PID/TID sets retained in each reduction output
(4 tracees per arm: the client root plus its RPC worker threads).

Arm B staged the participant-local verified backing BEFORE any client
contact: the controlled range helper verified the complete member and read
the exact range (`scripts/issue200_r8f_range_receipt.py`, retained stdout/
stderr/range bytes per arm), the staging adapter verified SHA-256
before-and-after and published atomically to
`<private cache>/rpc/bbc9ae6a1038b6a6` (the FNV-1a cache key of the exact
payload bytes — a filename computation, never trust authority). Arm C
repeated the same fresh-prestaged procedure against a second fresh private
cache. A supplementary observation
(`evidence/physical-phase5-raw/restart_reuse/`) additionally proves restart
durability: a fresh `ggml-rpc-server` process against arm B's
already-populated on-disk cache (no re-staging, no network rebuild) again
moved 0 immutable bytes.

### Phase-5 reducer correction (producer identity changed legitimately)

Executing the mandated capture contract for the first time against the real
pinned client discovered two facts the never-executed Phase-4-era reducer
assumptions contradicted:

1. On the fleet's strace 6.13, `-s 0` is the zero-length string limit: every
   nonempty send payload renders as `""...`. A retained capture under the
   exact mandated argv is therefore length-complete (declared length +
   syscall result per record) but not byte-complete. The corrected reducer
   accepts an abbreviated record only when it is structurally
   self-consistent (decoded prefix shorter than declared length, ellipsis
   marker present, result == declared length); truncated-without-marker,
   partial-result, and over-long records still fail closed.
2. The immutable payload is the suffix of a framed record (304 bytes
   observed overhead; the acceptance window is bounded at 4096 bytes
   independently of that observation), never a bare-payload record.

Attribution is rung-ordered and fragmentation-proof: exact retained bytes
when available; otherwise exactly one target-bound record within
`[payload_length, payload_length + 4096]`; a zero claim for a local arm is
accepted only when the arm's TOTAL target-bound bytes are strictly below
every frozen payload length (so a payload fragmented into sub-window records
can never produce a zero), and any target-bound record larger than every
frozen payload plus the window rejects as unexplained payload-class traffic.

### Phase-5 physical negative controls

All 22 issue-listed physical controls are mechanically exercised: 19 via the
committed mutation/unit controls over the validator and reducer (including
the new fragmentation, partial-result, truncated-without-marker,
unexplained-payload-class, wrong-member-SHA, and wrong-FNV-key controls),
and the process-wide/PID/argv/connect-provenance/unsupported-syscall family
via `tests/test_issue200_r8f_proof.py` (26 tests, green).

### Terminal

`evidence/terminal-reduction.json` now carries
`terminal: R8F_LOCAL_VERIFIED_BACKING_PASS`, `status: TERMINAL_RESOLVED`,
`physical_phase5_ran: true`, with the evidence-status block retaining the
validator's full derived accounting. Non-claims: this proves the generic
source-policy seam plus participant-local verified backing consumption for
the frozen bounded subject on the pinned substrate; it does not rerun or
reinterpret any R8-D qualification/correctness adjudication, does not rank
sources by bandwidth or economics, and does not modify llama.cpp anywhere.


## Historical nonterminal status (pre-Phase-5)

`terminal-reduction.json` has `terminal: null`, `status: "PHASE5_REQUIRED"`,
and `incomplete: true`. Issue #200 defines exactly these terminals:
`R8F_LOCAL_VERIFIED_BACKING_PASS`,
`R8F_RUNTIME_LOCAL_BACKING_PREREQUISITE`, and
`R8F_GENERIC_SOURCE_POLICY_BLOCKED`.

The generic source-policy/local-cache capability is sound (compact seam
`PASS`, all negative controls fail closed). The pinned execution substrate
**does** have a legal, non-runtime-modifying seam for participant-local
verified backing (Case C, Phase 4c above) — no llama.cpp/runtime
modification is required. What remains outstanding is the bounded physical
Qwen proof Issue #200 itself requires before a `PASS`/`PREREQUISITE`
terminal can honestly be claimed; this session cannot execute it (no usable
fleet credential). This is neither a pass nor a permission to patch the
runtime: it is an honest incomplete/handoff status. No Qwen-specific generic
planner branch was introduced. No R8-D correctness adjudication was rerun or
requalified — R8-D v2 evidence was read, never re-executed. No llama.cpp
source was modified anywhere in this correction, including to produce the
bounded RPC cache experiment evidence.

## Validation

- `.venv/bin/python scripts/check_test_env.py` — doctor green;
- `.venv/bin/python -m unittest tests.test_issue99_artifact_core tests.test_issue99_proof tests.test_issue101_orchestration tests.test_issue101_proof` — unchanged, green (100 tests);
- `.venv/bin/python -m unittest tests.test_issue200_r8f_source_policy tests.test_issue200_r8f_proof` — green;
- `.venv/bin/python scripts/run_full_cpu_suite.py` — full CPU suite green;
- `.venv/bin/python scripts/finalize_repository.py --check` — green;
- `.venv/bin/python scripts/sync_project_status.py --check` — green (frontier untouched, following the same R8-B/C/D precedent of not advancing the roadmap frontier pointer for an R8 sub-investigation).

## Evidence layout

```
evidence/arms.json                          five canonical Source-policy arms
evidence/negative-controls.json             all 12 required negative controls
evidence/local-backing-accounting.json      Phase 2 required-vs-optional accounting
evidence/materialization-invariance.json    same frozen plan/requirements, local vs remote materialization proof
evidence/producer-hashes.json               sha256 of every producer this record depends on
evidence/canonical-summary.json             pass/fail roll-up
evidence/isolation.json                     mechanical network/process/path isolation record
evidence/rpc-cache-mechanism.json           pinned upstream source identity + mechanical cache-seam finding
evidence/rpc-cache-experiment.json          bounded non-Qwen cold/warm/prestaged/adversarial experiment results
evidence/rpc-cache-experiment-raw/          driver source, fixture generator, orchestration script, raw strace/server logs
evidence/terminal-reduction.json            Phase 4 finding + cache-mechanism finding + terminal Phase-5 status
evidence/physical-phase5.json               Phase-5 physical evidence document (validator-conformant)
evidence/physical-phase5-raw/               per-arm raw captures, range/staging receipts, retained range bytes
evidence/MANIFEST.sha256                    integrity anchor over every retained/producer path
```
