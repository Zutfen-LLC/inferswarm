# Issue #299 provisional implementation checkpoint

Status as of October 9, 2026: work in progress, not issue acceptance or execution authorization. This checkpoint was requested by the maintainer to preserve current code and status on GitHub before the remaining SDD gates. It is not the final draft-PR deliverable. Ordinary hosted CI and Final CPU Validation remain deferred under the repository's review ordering; this provisional commit uses `[skip ci]`.

## Reviewed and committed foundations

| Slice | Commit | Status |
| --- | --- | --- |
| Bounded public Q8 metadata census and reproduction | `7054b9c` | Independent SPEC PASS and QUALITY APPROVED |
| Immutable profiles and strict operator-config/3 | `aa773399b51bf987b1091ba3608f1c8a0df6bc20` | Independent SPEC PASS and QUALITY APPROVED |
| Fixed Q8 ownership and resource admission | `cd330863e5e7ae3b275ea91bd4b6f1efbfc9f0d7` | Independent SPEC PASS and QUALITY APPROVED |
| Exact complete source/cache verification and serialization | `d9a14e0e9b7b147fa2c9bf99ec26247fc96b9424` | Independent SPEC PASS and QUALITY APPROVED |
| Owned physical bindings and complete materialization contracts | `aef2560922945f9c32c18b274fde71a52022f92a` | Independent SPEC PASS and QUALITY APPROVED after corrections |

The binding reviews reproduced and closed cumulative shared-buffer residence underreporting, missing identity rechecks after raised capture, and contradictory physical materialization-ID reuse across RAM and VRAM. These contracts reconcile a complete inventory; they do not provide native runtime telemetry or physical qualification.

## Provisionally checkpointed runner integration

The production `OperatorRunner` and `SSHSourceTransport` Q8 integration and `tests/test_issue299_runtime.py` are included in this checkpoint. Their independent SPEC review passed; separate QUALITY review is pending. Do not treat their provisional commit as QUALITY approval.

Verified before checkpoint:

- Parent rerun: 273 tests passed, including 30 new runtime tests and 243 predecessor tests.
- Independent SPEC review: 73 fresh unittest methods passed (30 Q8 runtime and 43 legacy runtime), plus 49 asserted independent control records.
- CPU environment doctor, whitespace, CI planner self-check and retention checks passed.
- The 30 new runtime tests are registered on all four living CI surfaces.
- The initial RED was feature absence, not a behavioral defect reproduction; later coverage-first additions are not represented as pre-implementation RED.

Exact runner/test bytes undergoing QUALITY review:

- `inferswarm/operator/runtime.py`: SHA-256 `60f80a59fd273b7abc9552c601cb695748dccc6f7906fffc1215b10722cee8c5`.
- `tests/test_issue299_runtime.py`: SHA-256 `b9d23467bbb9b48875c15c47f1f4b11f8908974a83609b2d28dfd42aa813266e`.

Offline tests exercise the actual runner and lease manager with recording transport boundaries, both explicit selections, complete 1,224-tensor/111-state reconciliation, independent owned identity, source joining, pre-request admission and owned cleanup. Mock source digests, resource budgets and observations are explicitly synthetic, not verified public weight bytes or live physical evidence. The accepted legacy path is retained.

## Remaining work

1. Finish independent QUALITY review of the runner; resolve and re-review any material findings.
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
