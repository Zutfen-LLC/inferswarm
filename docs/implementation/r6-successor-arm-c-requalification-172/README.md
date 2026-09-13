# Issue #172 — Arm-C physical requalification after SWA remediation and long-remainder corpus

Status: **`ISSUE117_ARM_C_ORDINARY_SERVING_PASS`** (PR OPEN, unmerged,
for maintainer review). Arm D and Arm E were NOT started; both require
maintainer acceptance/merge of this requalification first.

Campaign `issue172-arm-c-requalification-v1`, physical authorization
`physical-authorization-issue172-inferswarm-bce7fb3d-freetoken-6202eeeb`,
attempt `armc-requal172-physical-1`.

## What this is

The first physical authority to answer the post-#166 Arm-C PASS/FAIL
question: whether the accepted #166 SWA-lifecycle correction restores
exact ordinary external-Coordinator serving equivalence for the frozen
Issue #117 dense-Gemma subject, and whether it holds across the
accepted #170 long-remainder two-chunk range.

Starting from the exact accepted heads (InferSwarm `main@bce7fb3d`
[PR #171 merge accepting the #170 corpus freeze]; FreeToken
`inferswarm-research@6202eeeb` [PR #34 merge containing the accepted
#166 remediation, implementation head `64a37a1` in ancestry]) with the
execution-delta audit re-derived (only the accepted #153 single-chunk
policy + #166 SWA lifecycle differ from the accepted Arm-C producer;
`stage_runtime.py` sha256 `afe9ceb0…` == the accepted #166 hash), the
campaign ran on the frozen geometry (inferswarm01/gpu-0+gpu-1,
inferswarm03/gpu-0; frozen GPU UUIDs verified live at the frozen
indices), producer `6202eee` deployed clean on every
execution-bearing node.

## Result (mechanically re-derived from retained bytes)

- **Phase 0/1** — authority frozen (`evidence/authority.json`); the
  immutable 40-case corpus bound (`evidence/corpus-binding.json`,
  `evidence/campaign-corpus.json`): 24 accepted #133 regression cases
  (fixture digest `6046d479…`, integration identity `180185cd…`)
  + 16 accepted #170 generalization cases consumed without
  regeneration (canonical digest `8a382df1…`); every g170 case
  re-rendered under the pinned frozen tokenizer through the extracted
  Coordinator ingress seam with rendered lengths exactly the frozen
  65..128.
- **Phase 2** — CPU transcript preflight (`cpu-transcript-preflight.json`):
  40/40 exact model-execution transcript equivalence between direct and
  ordinary invocations (the accepted #129 recording-runtime machinery;
  replay prefixes, frozen-allocator session ids, argument sets,
  commit/discard semantics call-by-call identical; control-plane-only
  differences outside the runtime-invocation argument set).
- **Phase 3** — physical preflight (`preflight/host-preflight-{00,01,03}.json`):
  producer clean at `6202eee` on all three hosts with every
  correctness-bearing file digest equal to its pinned git blob;
  frozen-geometry devices verified at the frozen indices (BDFs
  re-observed; the additional physical GPU on inferswarm03 is recorded
  inventory, not geometry); Arm-B substrate byte-reconciled
  (participant safetensors sha256 equal to the accepted #133
  reconciliation); #157 instrumentation proven OFF (no env gates, no
  injected sitecustomize); tokenizer deployment exactly the five
  pinned assets, non-Source. The chain plan re-frozen
  content-identically under the #172 producer
  (`chain-plan.json` digest `b24c3ca0…`, provenance chain
  `ee845188` → `a71a3129` → this freeze — the accepted #129
  re-freeze precedent), and the r5a static-plan authorization fence
  re-derived by the real-builder CPU dry run (`r5a-static-plan.json`
  digest `208be795…`; authorized == locally built == runtime-returned).
- **Phase 4** — canonical 40-case physical campaign
  (`physical-execution/`): direct arm 40/40 (per-token replay prefill,
  frozen allocator, `max_new_tokens=2`, step-0 commit / step-1
  discard); ordinary arm 40/40 HTTP 200 over the full external path
  (client → CPU-only Coordinator on inferswarm00 → frozen Gemma
  strategy → generic planner with THIS campaign's measured
  EXACT_CONTEXT ranking evidence → frozen serving plan → node agent →
  3-stage chain → remote last stage → fenced commits) plus the
  controlled fencing-arm request. Equality reduction
  (`equality-reduction.json`): **40/40 exact** — committed token ids
  step-by-step, counts, stopping semantics, decoded bytes, per-call
  runtime session ids, replay prefixes. All six historical #133
  divergent identities (including both #157 anchors) now match exactly.
- **Phase 5** — repeatability sentinels (`sentinel-reduction.json`):
  the seven frozen identities (`c109-04-02-047`, `c109-04-06-074`,
  `c109-03-04-003`, `g170-01`, `g170-05`, `g170-09`, `g170-13`) × six
  repeats per arm from fresh qualified session state: 6/6
  within-direct determinism, 6/6 within-ordinary determinism, exact
  cross-arm equality on every repeat; complete distributions retained.
- **Invariants** (`zero-invariants.json`): every mandatory zero holds —
  attribution counters all zero, both controlled fencing injections
  (duplicate position; stale epoch) rejected without ledger mutation,
  Coordinator zero CUDA/weight/bulk participation (torch-free host,
  no forbidden nouns in the serving scope), no plan substitution, no
  Source fallback, instrumentation off. SWA ownership observed through
  the accepted #166 pure-read seam (`swa-ownership.json`): pristine
  reset state, incremental frontier 64→65→decode+1, no live position
  resolving to sentinel slot 0, wholesale release on reset, valid
  reuse, ownership conserved.
- **Terminal** (`terminal-reduction.json`): `ISSUE117_ARM_C_
  ORDINARY_SERVING_PASS`, all twelve conditions re-derived from the
  retained phase records.

## Attempt lineage

Every launch retained (`terminal-reduction.json` → `attempt_ledger`).
One pre-observation infrastructure failure is honestly recorded: the
first Phase-5 direct launch hit the last-stage service's
single-connection lifetime (the canonical-phase service had exited
with its connection); it emitted zero correctness-bearing results,
produced zero case outputs, and the frozen substrate was preserved
(all preflights re-passed before the successful relaunch). No STOP
condition fired; the campaign was never restarted after any observed
correctness result.

## Non-claims

- This PASS does not rewrite the historical #133 FAIL; it is a new
  post-remediation physical result.
- Arm D and Arm E are not started.
- No diagnosis/remediation beyond the accepted #166 correction is
  made or implied.
- No `h109-*` material was opened, generated, copied, inferred,
  reconstructed, decrypted, or used.

## Evidence layout

- `authority.json` — Phase 0 freeze (heads, ancestry, execution-delta
  audit, subject/plan identities, attempt state machine, non-claims)
- `corpus-binding.json` / `campaign-corpus.json` — the 40-case corpus
- `cpu-transcript-preflight.json` (+ transcripts) — Phase 2
- `chain-plan.json` / `environment.json` / `r5a-static-plan.json` /
  `coordinator-config.json` / `serving-evidence.json` — the frozen
  campaign deployment inputs
- `preflight/` — per-host physical preflights
- `physical-execution/` — direct run + per-case records, ordinary
  client records + fencing arm, serving reports, last-stage final
  reports, sentinel runs
- `equality-reduction.json` / `sentinel-reduction.json` /
  `zero-invariants.json` / `swa-ownership.json` — fail-closed reducers
- `terminal-reduction.json` — the terminal, re-derived

Scripts: `scripts/issue172_*.py` (all CPU-side tooling; the physical
drivers are byte-deployed read-only on the nodes and hash-retained in
the preflight records).
