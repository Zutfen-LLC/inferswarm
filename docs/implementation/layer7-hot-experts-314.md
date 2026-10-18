# Bounded layer-7 hot experts (#314)

## Scope and authority

Started from freshly fetched main
`02288987ca4ca50bc3800f1c70039502a08909af` in isolated worktree
`/home/zutfen/worktrees/is314-hot-experts`, branch
`feat/314-layer7-hot-experts`. Other worktrees were left intact.
Inspected #309 native overlap, #311 assigned RPC-v7 preparation/cache, #313
41/45 guarded two-CUDA lowering and #314 dedicated demand integration first.
This is a local implementation, not acceptance, execution permission, identity
promotion, deployment, issue closure, or a performance result.

The experiment is default off. Only single-token layer-7 FFNs use H5, ordered
`[54,74,136,290,394]`, on the already-owned GPU0 RPC backend on inferswarm03.
Other layers and multi-token prefill retain original CPU execution. Single-token
prefill retains its actual server phase. Surrounding 41/45 whole-layer
ownership, eight offload slots and tensor split 4,4 are unchanged. The generic
manifest supports an explicit immutable expert list, not automatic selection.
The guarded comparison deliberately accepts only this frozen H5 subject.

## Reuse and smallest added seams

- `hot_experts.py`: canonical immutable INTENT, external manifest digest pin,
  bounded authenticated encoded-slice preparation, exact derived shapes/ranges,
  content hashes and dense mapping. Original CPU banks are never rewritten.
- `llama-hot-experts.cpp`: context-owned compact tensors, independent private
  source-built router/shared/hot/cold/reduction graphs, existing dispatcher and
  response-bearing join. Graph reset/re-reservation shares the context owner.
- Partition every one of ten global IDs once, preserving slot positions and
  routing-weight bits. Hot IDs become compact indices; cold IDs retain original
  bank indices. Zero-hot avoids remote expert dispatch; zero-cold omits CPU
  expert dispatch, not shared work. Scatter weighted per-expert outputs into
  original slots, then run the source reduction graph and add shared once.
  CPU/GPU subtotals are never independently reduced and added.
- `hot_experiment.py`: finite optional session block, prepared/source-receipt
  join, bounded exclusive staging in existing owned invocation directories,
  additive exact assigned guards for client and GPU0 only. GPU1 is unchanged.
  Existing leases, resource controls, source-digest cache, failure supervision,
  deadlines, retention and cleanup remain the execution path.
- Actual `/tokenize` on the admitted, already-loaded owned server precedes every
  arm's first inference. It uses explicit add_special/parse_special true and
  with_pieces false, retains token IDs and refuses any input over 128 tokens.
  It does not load another model or issue a generation request.
- The existing guarded CLI accepts one shared `--outer-start-monotonic`; hot
  sessions require it. Both arms use the same controller/boot start frozen
  before preparation. The existing absolute deadline and RuntimeMax controls
  clamp to execution STOP at T0+160 minutes; total 180 minutes, 20 for cleanup.

Ordinary ownership validators and RPC-v7 exact upload guards are not relaxed.
Every derived tensor has a distinct immutable name and a complete offset-zero
upload. No partial upload uses an original bank name. The >10 MiB hash-hit
threshold is unchanged. H5 is CALCULATED 26,112,000 encoded bytes total,
8,704,000 per component, before runtime allocations. Setup uploads are expected;
these sizes do not prove VRAM fit or persistent hash hits.

## Provenance and immutable example

`tools/native-hot-experts/capture-provenance.json` binds the private bundle,
report, raw profile, retained reducer source/output and original requests.
Local authentication and the unchanged production reducer reproduce 1,584 rows,
zero drops and the retained summary. H5 occupies 160 of 320 decode slots; layer
7 uses 14 decode experts versus 92 prefill experts. Repetitive ABCD is only
development evidence, not representative coverage.

Bundle SHA-256:
`5d52bf5badee1cdbf450d9c5ba59a1089c85ac45f0c386574cf0a7500b3bf42f`.
Capture-provenance raw SHA-256:
`95dc5513eafea811e1c67f6259ce46a0b6dfc79b7660afc7c43efb2cf24196cf`.
Example INTENT manifest payload digest:
`ae733f217a6f9dff7e7a40cf1b4e8c7c601d9e71fe0e078f0231c518a030994c`.

The example intentionally has no invented compact hash; actual source-tensor
and compact hashes are emitted only by authenticated preparation. Global expert
394 maps to compact index 4. The whole source member remains independently
bound to checked-in model metadata and its recorded SHA-256.

## Build/identity handoff, not promotion

`tools/native-moe-overlap/hot-build-composed.py` composes the authenticated native
pin, complete RPC-v7 assigned-cache and observer patches, native overlap and H5.
Its default full-server build uses the accepted optimized CPU options including
Debug `-O3 -g0` and assertions. It records actual source closure, compiler bytes
and version, executable and library hashes, effective flags, commands and
producer-format per-target manifests. No accepted ordinary/CUDA identity file
or executable is overwritten.

Future build-only command, after separate authorization on 05:

```bash
python3 tools/native-moe-overlap/hot-build-composed.py \
  --archive "$AUTHENTICATED_PIN_ARCHIVE" \
  --output "$FRESH_CANDIDATE_OUTPUT" --server
```

Archive identity remains authenticated by the existing composer. The candidate
receipt is not authority. The finite pair
`hot-experts-candidate-cpu05-cuda03` intentionally refuses while
`tools/native-hot-experts/reviewed-cpu05-llama-server.build-manifest.json` is
absent. A later reviewed identity promotion must bind the real 05 server and
library/source/compiler closure; the remote remains the accepted Step-A CUDA03
worker. No such file is created here. Local fixture-only portable options are
explicitly barred from server builds and cannot satisfy this pair.

## Comparison and correctness boundary

The executable preparation/analysis recipe is
[`../../tools/native-hot-experts/comparison-recipe.md`](../../tools/native-hot-experts/comparison-recipe.md).
It recovers the original warmup/ABCD bytes and freezes factual extraction and
structured transformation before any candidate execution. Five requests per
arm: original warmup, original workload, new factual, new transform, original
workload repeated. A then B, one load each, same candidate, only H5 disabled vs
enabled; no retries or rescue arms. No comparison has been executed.

Structural/scheduling equality under identical CPU arithmetic is distinct from
CPU/CUDA Q8 numerical qualification. Frozen semantic checks and same-input
numerical diagnostics are executable; heterogeneous numerical diagnostics do
not invent a tolerance or grant acceptance. The existing independent
`moe-operand-reference/2` comparator remains unchanged and is applicable only
when its independent operands are available; otherwise numerical qualification
is explicitly NOT-EVALUATED. No bitwise CPU/CUDA claim is made. Observer
saturation/refusal remains separate from demand completeness and experiment
measurements. A correct no-gain screening result is useful, not a statistically
established speedup.

## Local validation (not physical qualification)

- 107 focused Python tests passed in `tests.test_issue313_two_gpu` and
  `tests.test_issue314_demand_integration` (17.517 s, zero skips).
- Nine real RPC-v7 CPU-loopback tests passed in
  `tests.test_native_moe_overlap.NativeHotExperts`, independently rerun by the
  controller against the final portable fixture build. They cover all hot
  counts 0–10 with changing routing order and nonuniform weights; exact encoded
  Q8 slices; original CPU output equality; shared/reduction sensitivity; graph
  reset/reuse/default-off/other-layer/multi-token invariance; true prefill phase;
  setup-only weight uploads; exact partial/view/duplicate guard refusal; and
  disconnect/stalled-join bounded cleanup.
- A fresh complete optimized-option composed CPU server build passed. This VM
  lacks AVX, so that server is compile-only here. Separate portable-fixture
  builds passed the execution tests; those options are forbidden for servers.
- Controller readback verified every one of 3,606 source inputs in each build,
  compiler executable hashes, all executable hashes, producer manifests and
  libraries (13 for the full build, five for portable fixtures).
- Authenticated retained-bundle/reducer reproduction and actual offline
  preparation CLI were exercised. The latter returned PREPARATION-ONLY and
  `execution_authorized:false`; no real-model preparation or comparison ran.

Actual build/identity handoff is
[`../../tools/native-hot-experts/local-build-handoff.json`](../../tools/native-hot-experts/local-build-handoff.json).
Durable local sources, executables, libraries, original receipts and validation
logs are retained at `/home/zutfen/data/is314-local-development/` (not merely in
24-hour scratch). The handoff maps original build paths to durable copies.
These are local development artifacts, not the future 05 candidate or accepted
runtime identities.

### Scoped independent review and blocker disposition

One independent correctness/resource review examined exact implementation head
`236d3d7186ff819a03512f3bd9919c9e01fe5767`. Its original verdict is preserved
as NO-GO, with one demonstrated P2 blocker: the tokenizer integration called
`request_timeout()` although the real `SystemdSessionGuard` exposes the existing
deadline-clamped `request_timeout_seconds()`. The original namespace-based test
masked that nonexistent API. Both arms would safely stop after load and before
the first tokenizer POST. Cleanup contained the failure, but the comparison
would not function. No other material blocker was reported.

The correction changes that single production call to the real API, replaces
the masking stub with a real guard, and adds a real
`OperatorRunner._execute_diagnostic_session` / `SystemdSessionGuard` regression
for both A and B. The new regression reproduced the AttributeError before the
fix (RED), then verified exactly five tokenizer POSTs, real deadline-clamped
integer timeouts and no inference before the request boundary (GREEN).
Oversized-token refusal remains covered. Eighteen comparison tests and the
complete affected Python population (108 tests, 16.065 s, zero skips) passed
after correction. Native source/fixtures/build inputs did not change, so the
nine loopback results and authenticated build receipts remain applicable;
there was no redundant native rebuild or broad validation campaign.

Original review/probe/logs and correction RED/GREEN logs are retained under
`/home/zutfen/data/is314-local-development/validation/`. The independent
NO-GO report is not relabeled GO: the demonstrated blocker is recorded as
controller-corrected and regression-verified. Final maintainer review of the
local corrected head remains pending. No optional-hardening work was added.

## Validation policy and documentation impact

Focused development tests and one scoped independent correctness/resource review
are the local gates. No hosted CI, Final CPU Validation or full repository suite
was launched. The risk planner selects full regression for the native/build
interface change at later merge assessment; this does not dispatch that gate.
The new tool directory is mapped to existing registered groups; tests extend
already registered modules.

No living accepted-capability/frontier or execution-authorization record is
advanced: this work adds unqualified default-off diagnostic software only.
Existing historical evidence, failure verdicts, identity tables and accepted
binary pairs remain intact. This implementation record and the recipe are the
affected explanatory documentation; no doctrine/ADR change is introduced.
