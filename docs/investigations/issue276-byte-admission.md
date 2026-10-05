# Issue #276 — Retained-Original Byte Admission (R8-I6A)

Parent: #273. Depends on #275's reconciled collector and original-byte
contract (accepted at PR #274 head `4504c99b7a98edabad4c3a0a27571382aa473107`).

## Outcome

One production path takes retained original capture bytes through staging
and the reader into admission. Acceptance derives from those bytes within
a reviewed collector/OS trust boundary — not from caller-supplied
dictionaries, authored labels, or any new seal assertion.

## Production path (scripts/issue276_reader.py)

```
#275 collector (reviewed code, contemporaneous OS/runtime probes)
  └─ retained originals: raw/*.bin probe bytes + row bytes + receipt.json
       └─ stage_capture_276()  — verbatim copy + digest binding (append-only,
                                 refuses incomplete/extra/contradictory bundles
                                 BEFORE any write)
            └─ staged unit: units/<case>/<tag>/{raw/*, rows/*, receipt.json,
                                 observation.json} + units/<case>/<tag>.json
                 └─ admit_staged_276() / admit_pair_276()  — the reader:
                      * recomputes every digest from the staged bytes
                      * re-derives ALL identity-bearing fields from bytes
                        (selector, ICD, backend, used Vulkan device, process
                        incarnation incl. closing re-observation, exe sha,
                        effective model, open members, residency counters)
                      * cross-checks authored labels (receipt claims, the
                        collector's own observation.json summary) AGAINST the
                        derivation — any contradiction fails closed
                      * enforces the per-arm law on the DERIVED values
                      * refuses invented authority fields on bindings
```

Staging cannot replace the observations because nothing staged is consumed
as an observation without being re-derived from the staged bytes: the
observation.json document is a cross-check input, never an authority.

## Trust boundary (finite and explicit)

* IN:  the reviewed collector code (`scripts/issue275_collector.py`, frozen
  at the accepted #275 head) and the contemporaneous OS/runtime
  observations it retained (procfs-style probe bytes, device census,
  residency counters, process environ, used-device observation).
* OUT: everything authored by callers or executors — receipt dictionaries,
  receipt labels, observation.json summaries, staged bindings, manifests.

SHA-256 digests prove BYTE INTEGRITY within that boundary; they do not by
themselves prove ORIGIN. There is deliberately no seal, signature, or
manifest assertion in this path that could move the unsupported
trust-by-itself claim elsewhere: a staged binding carries only plain
custody fields plus per-file byte digests, and an unknown authority-ish
field on a binding (e.g. an invented `CAPTURESEAL`) is rejected outright.
Origin rests solely on: bytes of the shape only the reviewed collector
path produces, validated by the same law the collector itself enforces at
capture time (arm law, incarnation binding, census/UUID/driver laws,
residency proof bounds).

## Negative controls (production-path, fixture-only)

Rejected by the same reader/admission entry point:
* cross-arm substitution (both directions; including self-consistent
  re-bound staged units),
* source-run reuse across arms (at staging by the arm law; at pair
  admission by byte integrity and receipt-digest equality),
* staged relabeling (binding arm label rewrite; observation label rewrite),
* byte changes in any retained file (including row bytes),
* fabricated self-consistent receipt/observation bundles with no accepted
  collector-origin basis (authored pairs, or reference labels pasted over
  authentic candidate bytes),
* invented seal/hash/manifest authority fields,
* incomplete bundles and unbound extra files.

## Independent review round 1 (gaps fixed and boundary pinned)

An empirical adversarial review returned FAIL with 7 gaps. Disposition:

FIXED (each pinned by a RED-first regression in this round):
1. Deleted receipt/observation bypassing derivation — metadata is now
   mandatory at admission; the derivation branch is no longer skippable.
2. Source missing row files — staging requires the complete decision set.
3. Receipt `server_pid`, observation exe PATH, observation cmdline, and
   closing-incarnation labels — all cross-checked against byte-derived
   values now.
4. Duplicate JSON keys in any probe document — fail closed, matching the
   collector's `object_pairs_hook` law.
5. Census top-level `boot_id` contradiction and pid-row uniqueness —
   enforced, matching the collector's census/boot law.
6. Binding `campaign`/`source_stem` custody labels — validated at
   admission; unknown arms fail closed in both staging and admission.
7. Repeat impersonation (one capture serving as its own repeat) — the
   pair law now refuses shared primary/repeat incarnation and
   byte-identical source bindings.
8. Row content law — rows must be full-vocabulary finite FP32 (the
   accepted comparator `validate_rows_finite` law); non-f32 payloads
   like `b"reference"` are rejected.

BOUNDARY (documented open observations, not papered over):
* A FULLY synthetic bundle whose bytes are byte-identical to a genuine
  collector output admits — because it IS collector-origin bytes. A
  byte-level reader cannot and should not distinguish a copy from an
  original; origin rests on the reviewed collector + OS boundary, per
  the acceptance text ("hashes prove byte integrity within that
  boundary, not origin by themselves").
* A BILATERAL swap of ALL row bytes across both arms (with every
  authored surface repaired) is not detectable at the
  integrity/derivation level: rows are payload observations with no
  upstream derivation source. All PARTIAL row attacks (aliasing,
  drift, unilateral copy) are rejected. Binding rows to arms by an
  invented seal is explicitly forbidden by the acceptance; in a
  physical campaign the arm-binding of rows comes from the capture
  window (contemporaneous incarnation/residency/census over raw
  probes), which a CPU fixture cannot represent. Reported to the
  maintainer as a concrete unresolved origin observation.

## First demonstration (fixture-only)

`tests.test_issue276_byte_admission.ByteAdmissionTests.test_demo_first_demonstration_fixture_only`
stages and admits one CPU-fixture bundle emitted through the #275 collector
path, then shows a substituted, digest-recomputed, relabeled counterpart is
rejected by the same admission entry point. FIXTURE-ONLY: no hardware,
model execution, holdout, or physical authority.

## Reconciliation record (pre-implementation, at `4504c99`)

The issue's "Start here" names "reported unpushed local reader/model-binding
corrections and their review". Verified read-only before editing:

* `git status --porcelain` in the authorized checkout (`~/code/is273-corrective`): clean.
* `git log origin/<branch>..HEAD`: empty — local head `4504c99` == remote
  branch head == PR #274 head; no unpushed commits exist anywhere
  (`git worktree list` checked every checkout; all other worktrees are on
  unrelated branches at older heads).
* Session recall of the #275 reconciliation found no reader/model-binding
  corrections beyond those already landed in `eaac7e2`/`4504c99`
  (observed-selection derivation and incarnation binding ARE the landed
  reader-side corrections; `_effective_model`/`_read_exe` derive the model
  binding from retained cmdline/exe bytes).
* Baseline: `tests.test_issue273_evidence tests.test_issue273_admission`
  green at `4504c99` (69 tests, 305s serial).

Disposition: nothing to preserve beyond the accepted head; implementation
continued additively from `4504c99` on the existing PR #274 branch.

## Exclusions honored

No new signing infrastructure, secret changes, hardware/model execution,
holdout access, historical-evidence edits, merge, or physical authority.
