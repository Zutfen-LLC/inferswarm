# Issue #299 implementation progress — incomplete

Status as of October 9, 2026: work in progress, not issue acceptance or execution authorization. The maintainer-requested provisional checkpoint `fe9b91032a8dfa4af56c1a80873f369468f5e649` preserved the runner before QUALITY review. The reviewed freshness correction and explicit observer-gap status are now retained in this progress snapshot. This is not the final draft-PR deliverable. Ordinary hosted CI and Final CPU Validation remain deferred under repository review ordering; progress-preservation commits use `[skip ci]`.

## Reviewed and committed foundations

| Slice | Commit | Status |
| --- | --- | --- |
| Bounded public Q8 metadata census and reproduction | `7054b9c` | Independent SPEC PASS and QUALITY APPROVED |
| Immutable profiles and strict operator-config/3 | `aa773399b51bf987b1091ba3608f1c8a0df6bc20` | Independent SPEC PASS and QUALITY APPROVED |
| Fixed Q8 ownership and resource admission | `cd330863e5e7ae3b275ea91bd4b6f1efbfc9f0d7` | Independent SPEC PASS and QUALITY APPROVED |
| Exact complete source/cache verification and serialization | `d9a14e0e9b7b147fa2c9bf99ec26247fc96b9424` | Independent SPEC PASS and QUALITY APPROVED |
| Owned physical bindings and complete materialization contracts | `aef2560922945f9c32c18b274fde71a52022f92a` | Independent SPEC PASS and QUALITY APPROVED after corrections |

The binding reviews reproduced and closed cumulative shared-buffer residence underreporting, missing identity rechecks after raised capture, and contradictory physical materialization-ID reuse across RAM and VRAM. These contracts reconcile a complete inventory; they do not provide native runtime telemetry or physical qualification.

## Historical runner checkpoint

The production `OperatorRunner` and `SSHSourceTransport` Q8 integration and `tests/test_issue299_runtime.py` entered checkpoint `fe9b910` after independent SPEC PASS. Initial QUALITY requested changes: plan or retained observation evidence could expire during blocking liveness work and still cross the request boundary. The following counts and hashes describe that historical pre-fix checkpoint, not the corrected bytes.

Verified before that checkpoint:

- Parent rerun: 273 tests passed, including 30 new runtime tests and 243 predecessor tests.
- Independent SPEC review: 73 fresh unittest methods passed (30 Q8 runtime and 43 legacy runtime), plus 49 asserted independent control records.
- CPU environment doctor, whitespace, CI planner self-check and retention checks passed.
- The 30 new runtime tests are registered on all four living CI surfaces.
- The initial RED was feature absence, not a behavioral defect reproduction; later coverage-first additions are not represented as pre-implementation RED.

Historical pre-fix runner/test bytes:

- `inferswarm/operator/runtime.py`: SHA-256 `60f80a59fd273b7abc9552c601cb695748dccc6f7906fffc1215b10722cee8c5`.
- `tests/test_issue299_runtime.py`: SHA-256 `b9d23467bbb9b48875c15c47f1f4b11f8908974a83609b2d28dfd42aa813266e`.

Offline tests exercise the actual runner and lease manager with recording transport boundaries, both explicit selections, complete 1,224-tensor/111-state reconciliation, independent owned identity, source joining, pre-request admission and owned cleanup. Mock source digests, resource budgets and observations are explicitly synthetic, not verified public weight bytes or live physical evidence. The accepted legacy path is retained.

## Reviewed request-boundary freshness correction

Final whole-plan admission and retained complete observation freshness now run after blocking owned-liveness/tunnel checks, immediately before the sole generation POST. No external transport or identity call intervenes. Expired/stale evidence refuses with its precise reason and zero POST, preserving owned cleanup and foreign ownership.

- Six regression methods were added; final exact test bytes reproduce behavioral RED against authenticated pre-fix runtime: six methods, eleven failure entries, zero errors. Failure entries are six wrong-POST cases and five ordering failures, not eleven methods.
- Parent combined rerun: 279 tests passed (36 runtime and 243 predecessors); a fresh post-review parent runtime rerun also passed all 36 methods. Doctor, planner, retention and whitespace checks passed. Runtime retention counts are now 36 on the existing registered module.
- Independent SPEC delta PASS: 36 runtime methods plus 14 asserted controls (5 accepted / 9 refused). Independent QUALITY delta APPROVED: 36 runtime methods plus 13 asserted controls (5 accepted / 8 refused), no new Critical/Important/Minor delta findings. These bounded approvals close the freshness finding only.
- Corrected `runtime.py` SHA-256: `5977caa4fedbd3e578156b0aa0f8a6878ce82fed3970199fc321b82fbfbb5f5f`.
- Corrected `tests/test_issue299_runtime.py` SHA-256: `d35ea2d68c1650de0f86374170aad707dd0f08fc160c8b4bf867736a72bbe0b1`.

The earlier initial runner reviews remain evidence for unchanged seams; no broader issue, native observer, physical execution or final-handoff approval is inferred.

## Production observer implementation gap

The current checkpoint does **not** include a working native production observer or independent production process-identity reader wired into `run_config`. It includes an injectable contract and synthetic test proof of the production runner. `run_config` constructs the runner without those implementations, so normal Q8 execution refuses before launch.

This is an **implementation gap in a usable production Q8 path**, distinct from later physical qualification. Stock pinned diagnostics cannot supply the complete tensor/state/buffer/copy inventory required by the contract. It must not be described as an implemented production observer awaiting only hardware evidence. Issue #300's physical operations cannot implicitly supply this missing code. The maintainer explicitly requested resolution before final handoff. A bounded exact-source assessment, independently authenticated by the parent over 40 native files, confirmed native instrumentation is necessary. It also identified an unrealizable observation ordering: `--no-warmup` permits graph reservation but no same-request completed computation copies before the first POST, while the current contract requires those copies then.

The earlier fail-closed contract is retained as a safety invariant, not as proof that the production observer requirement is complete. The recommended linked scope decision is: an authenticated observation-only native overlay at the exact base pin; static pre-request admission separated from same-request dynamic acceptance before accepting output; bounded offline native compilation and tiny CPU fixtures. A real SSH collector/independent identity reader and automatic normal-runner wiring would then close the implementation gap. The B CPU → A staging → B CUDA route and no-fallback policy remain unchanged.

**The maintainer approved the bounded scope extension on October 9, 2026.** See [observer scope amendment](observer-scope.md). The narrow `/2` parser/build/request-identity foundation now passes 55 focused tests and independent SPEC and QUALITY review, including the early complete-canonical-byte guard and incremental digest correction. Both incomplete reconcilers still refuse: parser approval is not static admission or dynamic acceptance.

The direct existing-GCC stock CPU/RPC baseline compiled 29 native translation units and passed tiny CPU and loopback SET/GET/ADD fixtures. That historical proof belongs to builder SHA-256 `95857bb0044459d5a70390163351a89ab64030510cdc71fdab6ffe6738ed55de`. The corrected builder passes 34 canonical tests, including a genuine campaign-lock/absent-source/Git-forbidden run, and independent SPEC and QUALITY review of Q1–Q6. Test workspaces no longer charge the native campaign; dependency provenance preserves escaped whitespace; active server deadlines refuse before late success. Parent post-review combined verification passes 89 tests. No corrected-builder native compile or execution occurred; 142 retained stock files and the native campaign ledger remain unchanged.

Reviewed parser SHA-256: `003b79d90f3c0db151385e54e170d543cf7467972ce049bdbfdd1155c519c4e0`; corrected builder SHA-256: `5fcc744da70e0f333f08480b07c9f3ed70d78ebe4eef15122cb5950d15f8734b`. The two new test modules are registered on all four living CI surfaces (55 and 34 methods). The builder requires a fresh output child, uses audited non-detaching process groups and synchronous checked bodies, and does not automatically recreate externally captured link provenance. No arbitrary blocking-body watchdog or hostile-local filesystem guarantee is claimed.

Full static/dynamic reconciliation, observation-only native producer, full llama-server closure, independent collector/identity reader and normal wiring remain unfinished. The stock baseline is not observer-patched/full-server/CUDA/model/physical proof. Existing `/1` semantics are unchanged; planned placement and synthetic copies are not observed execution, and #300 does not own implementing this missing code.

## Reviewed calculated static-inventory foundation (4D0b1)

`q8_static_inventory(config, metadata, *, candidate=None)` now derives an immutable expected inventory from the typed config and authenticated public metadata. Both explicit selections retain all 1,224 weights, 109 persistent native cache expectations and two separately unresolved logical composites. Cache names, four-dimensional native shapes and byte lower bounds follow the pinned constructors and legal workload; they are not allocations, initialized tensors, observed residence or completed request work. Optional candidates must match every freshly derived field with exact nested types. The helper rejects non-integer workload dimensions before derivation without changing the qualified planner/cache law.

- Independent whole-slice SPEC PASS: 135 scoped methods (40 Q8 plan, 55 phased observation, 40 bindings), plus eight independent controls. Independent whole-slice QUALITY APPROVED: the same 135-method population, plus nine independent quality controls. Parent reran the scoped population, then the 13 inventory methods and both independent control sets at the frozen bytes. These are distinct runs, not additional unique canonical methods.
- Original feature-absence RED is a missing helper API at the genuine predecessor. The separate workload correction's final six methods replay 30 failing subtests, 11 erroring subtests and one positive coverage method against authenticated pre-correction source. Errors are counted separately; float microbatch already failed at later charge typing and is not claimed as an accepted input. Boolean slots/microbatch were independently reproduced as accepted descriptions before the fix, not as admitted execution.
- All 19 original production and five original test declarations, original seven inventory tests, candidate/plan digests, charges/capabilities, argv and native requested maps remain unchanged against genuine predecessor captures for both selections. Source inspection authenticated the pinned native constructors; no native program ran in this slice.
- Reviewed `qwen_q8.py` SHA-256: `6e185d73dc330c81d55bf6b20b15025c64b9bc02fc736d5292f6ab918ee9644d`; reviewed `test_issue299_q8_plan.py` SHA-256: `1f1303cbcdd779758c06e2c39daf21c13734526c39d1718feec06569179871e7`.
- The existing registered Q8-plan module now has 40 methods (27 unchanged predecessor methods plus 13 inventory methods). The retention audit records the current count while preserving its original 27-method baseline.

Returning this calculated description does not grant admission, source-weight verification, original-controller/process/build custody, resource fit, allocation/residency proof or output acceptance. Full static layout/component/reservation/allocator and identity/source/build/resource/freshness joins, dynamic request evidence, native producer, collector and normal wiring remain pending. Both public `/2` reconciliation entrypoints still unconditionally refuse, and `/1` is unchanged. Accepted project status, frontier and execution authorization are not advanced; explanatory impact is confined to this implementation guide and runtime contract.

## Reviewed original-plan expectation context (4D0b2)

`StaticPlanContext` and pure `derive_static_plan_context(plan, metadata, *, original_plan_digest)` retain a detached three-field description: the controller's independently retained original digest, typed config and calculated inventory. Closed nested record/scalar guards run before profile serialization, strategy or digest derivation. All 12 mirrored plan/config fields, normalized profile integrity, complete candidate/source law and original digest are checked. Deep detachment preserves internal aliases and object/array tags without retaining caller-owned dataclass nodes. A coherent new plan may describe its new identity but cannot replace the old controller identity or certify an old source/process/build lifecycle.

The private generic `_profiled_digest_from_metadata` is a mechanical extraction: existing digest bytes, canonical-options law, path exclusion and the old file-reading wrapper remain unchanged. Neither helper consumes observations, receipts, time or I/O; cached admission is typed description, not authority. Both actual `/2` reconcilers still unconditionally refuse.

- Independent whole-bounded SPEC PASS: 158 scoped methods (76 phased observation, 42 Q8 plan, 40 unchanged bindings), zero skips, plus seven independent controls. Independent whole-bounded QUALITY APPROVED: 118 fresh touched-module methods, zero skips/errors/failures, plus seven independent controls; binding40 and parent legacy16 results were authenticated reuse, not fresh QUALITY runs. Parent previously ran 158 scoped methods, 16 legacy methods and eight independent controls at these same bytes.
- Coverage qualification: SPEC's 275 named field probes comprised 265 encountered record fields plus ten optional CacheRange fields. Its heterogeneous-tuple census omitted ten NativeQ8Options fields. QUALITY freshly closed all ten named early-refusal cases without a product edit; combined coverage is 285 fields, not exhaustive scalar/opaque-JSON coverage. Historical SPEC evidence and the initial QUALITY census failure remain retained unchanged.
- Original 95 touched-module methods/goldens remain intact; 23 methods were added (21 context, two digest seam). Genuine four pre-write candidate/inventory/digest/admission captures and mechanical old-body parity are preserved. Feature-absence API errors, behavioral identity/shape failures, coverage-first additions and the corrected slicing/log-parser fixture issues are separately attributed, not inflated into unsafe-acceptance counts.
- Reviewed `plan.py` SHA-256: `ec44334b825ee2870d4f6506ac7841d00a331eb93b0a122cb84f41870976f1fa`; `phased_observation.py`: `123f62bb649eff9332e20410d5d9230efc012f1220a474c98a43ebb7b75ea1bf`; phased tests: `0980168659b0ee92643b2ef00d50eae4481267d87e19cd8d56fa14668371d34b`; Q8-plan tests: `fc151a33be5bc11bd7fe628708e76bb63fa1aefe2d20fcf4ee4a70dcf10a1a3b`.
- Existing registrations remain unchanged; current retention counts are 76 phased and 42 Q8-plan methods, preserving historical baselines of 55 and 27. Accepted project status/frontier and execution authorization are not advanced; explanatory impact is confined to this guide, the runtime contract and current-count bookkeeping.

Full static layout/component/reservation/allocator closure, actual source/mapping/cache continuity, independently read owned identity and versioned derived-build qualification, resource/freshness joins, same-request dynamic evidence, native producer, collector and normal wiring remain pending. This slice is not static admission, output acceptance, physical qualification or completion of #299.

## Reviewed finite startup expectation oracle (4D0b3)

`derive_q8_startup_oracle(plan, metadata, *, original_plan_digest, startup)` derives four frozen/slots expectation records (settings, dimensions, members, charges) from the original retained context FIRST, then the supplied startup description. The oracle is a pure finite prerequisite: it never allocates, launches, observes or authorizes anything, and both `/2` reconcilers still refuse unconditionally even when passed the oracle.

The first independent whole-bounded SPEC review failed with three findings (per-sequence embeddings UNKNOWN handling, five missing actual allocation/init/release citations, recurrent `rs_idx` native uint32 representation). All three were corrected (exact six production replacements, four appended regression methods, all 14 previous startup methods byte-unchanged) and independently reproduced by parent checks: final test bytes replay 3 methods / 26 assertion failures / 0 errors against the authenticated pre-fix producer `2187a9fc…`.

- Independent whole-bounded SPEC round-2 PASS: 176 scoped tests (60 Q8-plan, 76 phased, 40 bindings) in 233.185s, zero failures/errors/skips, loader/log exact multiset; 15 control groups, no findings; all ten matrix items PASS; 31-owner/218-field receiving census; 36 native families/61 source associations authenticated. Parent verified the packet (37 review artifacts, 142/145 path preservation).
- Independent whole-bounded QUALITY APPROVED: fresh 60 touched-module tests in 113.475s, zero failures/errors/skips; 10 newly authored control groups (corrected settings/source/uint32 seams, coverage, detachment, purity tripwires, cached-admission authority refusal); benign lock-in GREEN on authenticated pre-fix bytes; no Critical/Important/Minor findings. Retained same-byte 176-test runs and correction RED were authenticated and honestly reused, not re-executed.
- After session recovery the parent freshly reran doctor and the full 176-test population (227.257s, zero failures/errors/skips) at the identical frozen bytes with exact loader/log identity.
- Reviewed `qwen_q8.py` SHA-256: `3e09160738f205b2b77f49824995933e50a6a18a9a34894edd8784e6f0422a40`; `test_issue299_q8_plan.py`: `6a53d214cde935a357ea765a747e0de81de51bd5461366642620d74297f7f554`. Review/report hashes: SPEC-r2 `30a4e44e…`, QUALITY `cdaaabcf…`.

This oracle grants no admission, dispatch, output acceptance or execution authority. Effective argv/environment/server/cparams join, full static/dynamic reconciliation, native producer/full server, real collector/identity reader, normal-runner wiring, CLI, examples and final integration review remain pending.


## Issue #301 native producer and full-server build (child slice)

Child issue #301 ("Implement Q8 native telemetry and reproducible full-server
build") was implemented on this branch on October 10, 2026, continuing from
checkpoint `210f803`. Pre-work budget was recorded before any native build
(scratch `issue301-prework-budget.md`; ledger carried at 51.3s, never reset;
final cumulative 2654s of the 5400s ceiling; one build at a time, one compiler
job, 3GiB AS/256MiB file/4GiB tree RSS, no core dumps, disk floor held).

Delivered and verified:

- **Observation overlay** (`tests/fixtures/issue299/overlay/`): strictly
  observation-only hooks (guarded by `IS301_OBSERVE=1`) at documented seams —
  buffer allocation completion (ggml-alloc.c via C shim), graph compute and
  tensor set/get completions (ggml-backend.cpp), RPC client SET/GET
  completions plus server accept/command loop (ggml-rpc.cpp), model loader
  completion, KV-cache constructor completion, server task/response lifecycle
  (server-queue.cpp). No computation, kernel, placement, scheduling or
  transfer behavior changed. `is301_observer.h` emits complete
  `inferswarm-native-observation/2` envelopes: canonical JSON (sorted keys at
  every level, ASCII-safe) sealed with a self-contained SHA-256 over the
  envelope minus `terminal_digest` — cross-verified against the independent
  Python parser, which accepts every retained native-emitted capture.
- **Identity**: retained unified patch
  (`native-observer-overlay.patch`, sha256 `95e9d4361c44a43ade3433f6ab645bd44e327ceed4c161268d80d6f380ba4e25`)
  and transformed-file manifest (`native-observer-transformed.json`) derived
  once from the authenticated pin by `scripts/issue301_derive_overlay.py`
  (exact anchored replacements; every anchor unique at the pin).
- **Reproducible full-server build**
  (`inferswarm/operator/native_observer/full_build.py`): direct GCC recipe
  (no CMake in environment; no installs authorized) with the complete
  330-TU target/dependency closure authenticated from the pin's CMake target
  definitions — ggml-base/cpu/rpc, vendor hash, llama core + 154 model TUs,
  common (parsers/jinja/subprocess), mtmd + 50 clip model TUs, server-context/
  impl, cpp-httplib definitions, generated ggml-version.h/llama-version.h/
  build-info.cpp and the CMake priority-4 empty-asset ui.cpp/ui.h form.
  Per-target include resolution is mirrored (common before src so
  common/jinja resolves common/unicode.h).
- **Supervised execution**: 337 compiles + 3 links under the campaign
  Supervisor in one fresh output root. Both actual full targets built:
  `llama-server` (35,833,064 bytes, sha256 bc6d208a…, 335 objects) and
  `ggml-rpc-server` (4,085,360 bytes, sha256 766abb93…, 30 objects). Per-
  executable `q8-native-build-manifest/2` artifacts parse under
  `parse_build_manifest` and never claim the unmodified base.
- **Genuine native captures**: the patched tiny CPU fixture ran twice (CPU and
  RPC loopback against the patched `ggml-rpc-server` on an owned reaped
  listener). All four envelopes (static snapshot + dynamic whole, per run)
  parse with verified terminal digests; the RPC dynamic capture shows genuine
  `rpc_set`/`rpc_get` transfer facts with real remote pointers. Retained at
  `tests/fixtures/issue299/native-captures/`. Native IDs (pids, pointers,
  sizes, counters) come from execution; controller values stay distinct.
- **Offline tests** (`tests/test_issue299_native_producer.py`, 14 methods):
  replay the retained genuine captures and refuse mutated evidence
  (truncated, dropped-events, overflow, wrong generation, missing terminal
  fence). No test compiles, charges the campaign ledger or launches a server.
  Registered on all four living CI surfaces with a retention-audit record;
  focused parent rerun passes 377 tests across the ten #299 modules;
  doctor/planner/retention checks PASS in the canonical venv.


Independent review record for this child slice: SPEC round 1 returned FAIL
with three findings; all three were corrected and re-verified.

1. *Build manifests misidentified object bytes as backend libraries* —
   corrected: `full_build.py` and the retained run artifacts now emit real
   per-target static archives (`libllama-full.a` for the server link closure,
   `libggml-static.a` for the GGML closure + sink) built with `/usr/bin/ar`
   from the exact linked member objects.
2. *Fact catalog did not supply transfer shapes/endpoints or graph lineage* —
   corrected: transfer facts now carry type, native 4-dimension shape and
   view offset (plus remote_ptr on RPC legs); graph facts carry a real
   graph_id and an explicit `ubatch_lineage: "unknown"` marker; model-load
   facts carry explicit `output_custody: "unknown"` and
   `tensor_ranges: "unsupported"` markers per the issue's explicit
   unsupported/unknown-field requirement. Patch sha256 now
   `14a3870a4392605fc606382c3af9bebe96c308f63c70c549356f0341e54ccc89`.
   The full supervised build was re-executed within budget with the enriched
   overlay: llama-server 35,845,408 bytes (sha256 4ff549e0…), ggml-rpc-server
   4,089,512 bytes (90f4ca76…); all four re-retained captures parse with
   verified digests and enriched facts.
3. *Wrong-generation control only tested digest binding* — corrected: the
   mutation controls now RECOMPUTE valid terminal digests over mutated
   envelopes, so refusal exercises the semantic fences (drop/overflow with
   consistent counters, whole-stream mislabeled as prefix via terminal=false
   or nonzero sequence_start, and a middle-row sequence gap) rather than mere
   tampering detection; unsealed-tampering refusals are retained alongside.

After corrections, SPEC continuation verdict: PASS. The full independent
QUALITY review returned NOT APPROVED with five findings; all five were then
corrected and re-verified: (1) the RPC server child now also receives
IS301_RPC_ENDPOINT; (2) the native facts builder refuses scalar/array fact
mixing and bounds the first appended element (no malformed-JSON or lost-fact
path); (3) the retention audit records the true 16-method count; (4) retained
capture bytes are pinned by expected SHA-256 in the tests, so re-authored
self-consistent fixtures are detected; (5) a focused test asserts archive
membership equals the exact link-command inputs (index drift guarded).
Focused reruns pass 126 tests across the touched modules; retention and
doctor checks PASS. An independent QUALITY re-review of the corrected head
read the corrected files and re-ran the focused suites (all OK); verdict
APPROVED with no new findings. Campaign ledger after the final re-run:
4070s of the 5400s cumulative ceiling.

Honest limits: this is CPU-only native proof — the tiny fixture does not
observe Q8 tensors, model-specific hooks or any CUDA path; the B CPU→A
staging→B CUDA route is unchanged with no fallback; both `/2` reconcilers
remain fail-closed; no model download/inference/GPU/deployment/merge occurred.
A derived observer build is never the unmodified pin. Physical preparation
stays #300. Independent SPEC/QUALITY review records for this slice are
retained in scratch alongside prior review artifacts.

## PR #304 maintainer-review correction round (2026-10-10)

Maintainer review 5479625739 (CHANGES REQUIRED at `bedf44a`) identified three
P1 findings. All three were corrected on this branch; correction commits
preserve `bedf44a` in ancestry (no rebase/amend/force-push).

- **P1-A (scheduler observation + collector export)**: the overlay now
  instruments `ggml_backend_sched_graph_compute_async` — the entry
  `llama-context.cpp:2513` actually uses — recording completion AFTER
  `ggml_backend_sched_compute_splits` returns, with no added synchronization
  or behavior change. Facts carry graph identity (graph_id, nodes, splits,
  status) with explicit `ubatch_lineage: "unknown"`. A bounded producer-owned
  export seam (`is301::export_capture`, IS301_EXPORT_DIR, 64-export cap,
  fresh generation + reset per capture, atomic .tmp+rename publication) is
  wired at `server_queue::terminate()` (llama-server) and the RPC server's
  per-connection site (ggml-rpc.cpp). The tiny fixture now executes the TRUE
  scheduler path (CPU-last backend ordering per the pin's own
  `ggml_backend_sched_new` assertion) and exercises the export.
- **P1-B (valid, non-overwritten, fail-closed facts)**: server lifecycle
  facts are array elements (`tasks` [{response_id, task_id}] with the honest
  "unknown" response marker; `responses` [{task_id}] join key) instead of
  invalid scalar-overwriting JSON. Allocation records are preserved per
  allocation (`allocations` [{backend, buffer_bytes}] via a new
  `is301_fact_alloc` C shim), replacing last-value-only scalars. EVERY
  fact-capacity refusal in the facts builder increments dropped/overflow
  counters folded into the fixed `/2` fences (`dropped_events`/`overflow`),
  so a truncated stream can no longer report zero drops. The adversarial
  native-fact-bounds fixture proves both directions natively: the overbound
  capture is REFUSED by the parser for dropped_events>0 (valid-digest
  semantic refusal), and the clean capture preserves all 3 tasks + 2
  responses + 2 allocations.
- **P1-C (complete compiled-source authentication)**: `overlay.apply()`
  materializes every unmodified file from pinned Git blobs (cat-file at the
  pin, mode-preserving, .git excluded, symlink-aware) instead of `cp -a` of
  the mutable worktree; `verify_tree_inputs()` authenticates ALL 3,594 tree
  files against pin/retained manifests before ANY compile and again after
  compilation; reused overlay trees get the same complete check. Build
  provenance now separates pinned base, retained patch, transformed sources,
  untransformed-input aggregate (3,582 files), generated inputs, compiler
  identity, per-executable ordered link inputs and executable hashes. A
  dirty worktree copy is refused (offline negative control with a fake pin
  repo, including the dirty-untransformed-TU refusal before command
  assembly).

### Native validation within the remaining authorized envelope

The cumulative native ledger stood at 4070.3s of 5400s before this round.
One supervised full rebuild attempt spent 771s but failed on the last link
(fact-bounds executable initially linked without its own TU); the corrected
GGML-closure phases then completed within budget. Final ledger:
**5164.5s of 5400s (235.5s remaining)**. All phases ran under the campaign
Supervisor (one compiler job, 3GiB AS, 4GiB owned-tree RSS abort, 256MiB
file cap, 16GiB disk floor, 60s fixture timeouts, no core dumps).

Genuine native evidence retained (all byte-pinned in
`tests/test_issue299_native_producer.py`):

- `native-captures/{static,dynamic}-capture.json` and `rpc/` — regenerated
  CPU/RPC-loopback captures now containing `sched_graph_compute` events and
  scheduler graph facts (parse-verified, digests valid).
- `native-captures/exports/` — real collector-exported sealed streams from
  the fixture process and the patched `ggml-rpc-server` (per-connection
  export seam; 12 and 17 events).
- `native-captures/fact-bounds/clean.json` — the adversarial fact-bounds
  clean capture (3 tasks / 2 responses / 2 allocations, zero drops).
- Build artifacts (issue301-correction-ggml scratch root):
  `ggml-rpc-server` sha256 58dc9c746670a036809b8de89c496fb7f99cd44b9181b0a5d50e5df4641aadcc;
  `native-buffer-graph-observed` 1f9c24bfb08dc3ce88de0d497746e6517299e2a7d75ff55f8226942f05a163ea;
  `native-fact-bounds` 559b8cfaff34f4f8d6aefdb99bc642f1f3c353e2e657e677c25b44c0b8099ca0;
  per-executable `q8-native-build-manifest/2` (parse_build_manifest OK,
  never the unmodified base) and separated provenance.
  Retained patch sha256 d471abb83e3c911ed5bcc812c04bb8bb36a062183cea1e2f79b4f80fe482d2ef;
  transformed manifest sha256 6244b3eebba5f426add5c154c3a25f419c5554b73773c37969b677e7997471c0.

**STOP item — llama-server corrected-executable rebuild**: the corrected
overlay changes 8 server-closure-relevant TUs (ggml-alloc.c,
ggml-backend.cpp, ggml-rpc.cpp, server-queue.cpp, model-loader, kv-cache,
sink, fixtures). The GGML closure + both server-adjacent fixtures were
rebuilt and validated within budget; the ~300-TU llama-server relink did
NOT fit the remaining 235.5s. **Exact additional build budget required:
approximately 700-750 seconds of supervised native compilation** (one
compiler job, ~300 llama/common/server TUs at the measured ~2.1s/TU rate
plus the server link). No previous manifest is claimed as proof of the
corrected llama-server executable.

### Independent review of the correction round

- **SPEC review**: PASS, no findings (12/12 matrix; report
  `pr304-correction/spec-review.md`, sha256 d0a982f3…). Verified the
  scheduler hook, export seam, fixture truth, lifecycle/allocation facts,
  fail-closed fences, canonical ordering, P1-C materialization and
  authentication, no regression of reviewed enrichments (derive script
  idempotent, byte-stable), native evidence honesty, and the RED->GREEN
  test evidence. 64 focused tests, zero failures/skips; repo left clean.
- **QUALITY review**: one Important + one Minor finding, both corrected and
  re-verified. (1) `verify_tree_inputs()` now enforces the exact pinned
  mode class (added/lost executable bits refused), rejects any
  regular-file<->symlink substitution (symlinks can be retargeted after
  verification), rejects dangling/foreign filesystem entries via complete
  no-follow enumeration, and requires every tree entry to be a regular
  non-symlink file. Three new offline negative controls (0755 flip,
  symlink substitution, dangling entry) RED-verified the bypasses and now
  pass. (2) `export_capture` refuses a shared export directory already
  used by another process, bounding one directory to one process's
  64-export cap. The RPC fixture now also reserves the scheduler graph
  (mirroring llama-server startup) before async compute; a genuine
  fixture-rpc export stream is additionally retained. Final focused
  suites: 67 producer+build methods OK (26+41); retention audit OK.

Post-QUALITY native re-run (fixture-tail phase, incremental): all nine
native evidence checks pass — CPU/RPC static+dynamic captures, three
export streams (fixture-cpu, fixture-rpc, ggml-rpc-server), the refused
adversarial capture, and the clean fact-bounds capture (3 tasks, 2
responses, 2 allocations). Final campaign ledger: **5244.2s of 5400s
(155.8s remaining)**. Updated executable identities (issue301-correction-ggml scratch root):
`ggml-rpc-server` f6bd79694cdcb13e30a95a5edf19512ed041d6b7f03eb5133748ae6ce887232b;
`native-buffer-graph-observed` d4f6ecdb25d2dd1fd3eaf2fb5deab542155a80fb9b327eb84b06d2ba38e388a4;
`native-fact-bounds` 1b36ce9408957587d9c5c28c17494e753943aec36d42a1bc71634393a53e42a2
(per-executable /2 manifests + separated provenance re-emitted); no llama-server rebuild is claimed and the STOP item stands
(~700-750s additional supervised budget required).


### Tests

- `tests/test_issue299_native_producer.py`: 26 methods (16 prior + 10
  correction: 6 source-realistic pre-build controls RED->GREEN + 4 genuine
  native-evidence controls). All prior mutation controls keep passing
  against the regenerated byte-pinned captures.
- `tests/test_issue299_native_build.py`: 38 methods (34 prior + 4 P1-C
  authentication controls RED->GREEN).
- Full #299 population rerun: 393 methods across ten modules, zero
  failures/skips; CI retention audit and planner self-check PASS. The
  derive script is verified idempotent (byte-stable regeneration).


## Remaining work

1. Implement and review the approved successor observation contract, native producer, real collector, independent identity reader and normal-runner wiring. Verify actual CPU-native fixtures within recorded limits; report CUDA/physical qualification separately. No production-complete handoff while implementation gaps remain.
2. Add and review the no-effects plan-only CLI.
3. Add and review reproducible illustrative one-GPU/CPU-only examples, receipts and documentation.
4. Complete documentation/status impact checks and independent original-acceptance integration review.
5. Deliver a verified draft PR and stop for maintainer exact-head review before applicable final hosted validation. No merge is authorized by this coding task.

## Explicit limitations and authority boundaries

- Header authentication proves metadata descriptors, not full weight-bearing object integrity. The original acquisition's intermediate redirect-body byte count was not recorded; no historical all-response-body budget claim is made.
- Pinned llama.cpp source support is separate from binary/build, Q8 kernel, numerical, route, allocation-residence, memory-fit and performance qualification.
- At the pin, B CPU-to-CUDA copying is not server-local. The explicitly selected candidate uses B -> A client staging -> B GET/SET with its route and staging budget requirements; there is no silent route substitution or CPU fallback.
- Stock telemetry is insufficient for complete independent physical observations. The default live Q8 runner fails closed before lifecycle effects without a capable observer and independent identity reader. The constructor-only synthetic test seam is not exposed as run/CLI authority.
- No full weights were acquired for this implementation, no physical host/device operation or inference was performed, and no full final suite, hosted CI dispatch, Final CPU Validation or merge was performed.
- Issue #300's physical preparation/comparison remains separately gated after acceptance and merge with scoped execution authorization. Cross-vendor work under #188 is neither qualified nor retired by this checkpoint.
- Living accepted status/frontier records are not advanced by this provisional implementation checkpoint.
