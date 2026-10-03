# METHODOLOGY-AMENDMENT-004 — R8-I3C Phase 1 live producer (#254)

Additive to the frozen #252 METHODOLOGY (merged PR #253). Nothing in this
amendment edits frozen #252/#253 text, arms, geometry, mechanism contracts,
or the comparator/2 methodology. It records the Phase-1 producer law the
issue #254 Phase-A review covers.

## A. Dispatch-law succession (#252 phrase → #254 phrase)

The frozen #252 capture law (schema `/2`) binds dispatch authority to the
exact phrase `R8I3C PHYSICAL DISPATCH #252` on campaign PR #253, and
requires that PR to be OPEN/unmerged/non-draft. PR #253 merged as
`ac9db62d15f21fdc7dd7a04253589f4b9e9ca489`; the `/2` law is therefore
structurally undispatchable (fail-closed by design, not weakened).

Live physical authority for issue #254 is the phrase mandated verbatim by
the issue, `R8I3C PHYSICAL DISPATCH #254`, posted as a top-level
conversation comment on the still-open producer PR created from branch
`issue-254-*`. The producer PR number is resolved at runtime through the
production GitHub HTTPS seam (unique open PR from that branch against
`main`), never a hand-guessed constant; `ISSUE254_PR` may pin the
expectation on the executing host and a mismatch fails closed. The retained
authority record is the additive live capture schema
`inferswarm.issue254.dispatch-capture/3`, which binds the same
authentication-bearing immutable comment fields plus the execution-time
PR/issue state and the #254 phrase. Schema `/2` records and their verifier
remain byte-identical for all accepted Phase-0 evidence.

One dispatch authorizes exactly one arm and one exact head, re-fetched
immediately before every unit.

## B. Producer attestation (new custody layer)

Every physical unit is retained with a machine-readable
`producer-attestation.json` (`inferswarm.issue254.producer-attestation/1`)
binding: producer source head; dispatch capture comment ID + body digest;
unit index/tag; server PID; start/end timestamps; comparator SHA-256;
model stat witness; argv/env (byte-equal to the frozen one-factor
geometry); request digest; response raw digest/length; observer meta and
row digests/lengths; server-log digest; identity pre/post; placement
evidence; process exit/cleanup verification; health snapshot.

The reducer consumes the attestation mechanically: a unit retained under a
`/3` live capture is admitted ONLY when the attestation re-derives from
retained bytes and re-binds every digest the receipt carries
(`verify_unit_producer_binding`). A hand-built, internally consistent
unit/receipt tree without producer execution is refused as physical
authority (adversarial case 17).

## C. Atomic unit publication and stop law

Units are assembled in a hidden staging directory, fsynced, validated
(receipt + attestation + retained-byte hashes), and published by atomic
rename. A crash leaves only the staging directory, which the producer
refuses to continue through (ambiguous-continuation refusal); a
machine-readable producer status record is retained at the evidence root
on abort (never inside a policed namespace directory).

The stop law derives from retained bytes via the accepted #250 prefix law:
only the next legal prefix unit executes; first mismatch stops the arm;
three identical is screening stability only (continue); five identical is
deterministic (arm complete); completed mismatch populations refuse any
restart continuation; no retry or cherry-pick of a completed unit.

## D. No synthetic authority path

No public API accepts caller-supplied response bytes, observer rows,
identity/placement dictionaries, server-log bytes, or a preconstructed
receipt and marks them physical. The only physical path is
`execute_unit`, which launches the pinned comparator process itself,
reads back the live `/proc/<pid>/cmdline`+`environ`, issues the byte-exact
accepted request itself, and derives placement evidence from the retained
complete server log plus the no-CUDA environment law.

Round-2 correction (maintainer review of d668f628): the production
orchestration entrypoints `run_unit` and `run_arm` expose NO injectable
seams of any kind — no `fetch`, `execute`, `identity_observer`,
`health_runner` parameter and no generic `**kwargs` escape.
`run_unit` unconditionally calls `fetch_live_dispatch`, `execute_unit`,
and the production identity/health paths; `run_arm` calls only the
production `run_unit` path. Offline tests exercise the production
orchestration logic solely by patching the internal production function
objects (`PR.fetch_live_dispatch`, `PR.execute_unit`) from test code
with `unittest.mock` — the same doctrine as the schema-/2 suite's
`offline_authority_fetch`. The /3 capture verifier additionally binds
comment provenance to the exact producer PR conversation (see the
round-2 provenance law in `scripts/issue254_producer.py`:
`validate_live_comment_provenance`), mirroring the hardened schema-/2
doctrine: `issue_url == API_ROOT/issues/<pr_number>` and the exact
canonical `html_url` `.../pull/<pr_number>#issuecomment-<comment_id>`
are retained in the /3 capture, its canonical projection, and
re-derived from the independently re-fetched live comment at
reduction time; the retained `commenter_login` must equal the live
commenter login.

## E. Zero physical authority in Phase A

Phase A (this PR) performs NO model inference and NO physical
discriminator execution. `execute_unit` cannot start: it requires a fresh
live `#254` dispatch, and no dispatch comment may exist for this PR before
maintainer review. All 44 tests run against offline fixtures and patched
internal production objects. Phase B (A3 first) requires the separate
exact-head OWNER/MEMBER dispatch defined in issue #254.
