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
