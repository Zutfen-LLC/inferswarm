# Issue #262 — Rapid Physical Pilot (H5) — Final Report

Schema: `inferswarm.issue262.pilot-report/1` (see `pilot-report.json`).

## Execution authority

- Issue #262 OPEN; PR #263 the unique open PR against `issue-254-r8i3c-producer`.
- Frozen execution head: `76aaaf69a3920879c1db17c47219f375207fdaf2`
  (branch `issue-262-r8i3c-physical-pilot`, clean tree, verified per unit).
- Subject: inferswarm01, RTX 3060, BDF `00000000:03:00.0`,
  UUID `GPU-d5c05739-96c1-7e49-89b6-bf54c2121c55`, driver 610.57.04
  (historical A3/A5 subject reused; verified live per unit).
- Instrumented comparator `llama-server` SHA-256
  `1981bd5d0f2832482cde079f57fbf82f6b21040387b61b5fff59911a776e0988`,
  rebuilt from the frozen chain (pinned `b29c606e` + #260 patch + H5 route
  patch + accepted R8-E patch + comparator/2 seam; tree
  `015c874f0cc0635fa1369650098c0137f9a492f0`). Build recipe
  authenticated by reproducing the frozen baseline comparator
  (`6f8b56bd...`, 77-byte build-path-only diff).

## Arms (screening, 2 units each, per issue bounds)

| Arm | Env factor | Units | H2/H3 submission | Graphs/unit |
|-----|------------|-------|------------------|-------------|
| BASE | (none) | 2 | normal | 7907 |
| A1 | `GGML_VK_SERIALIZE_SUBMISSIONS=1` | 2 | serialized | 7907 |
| A5 | `GGML_VK_DISABLE_HOST_VISIBLE_VIDMEM=1` | 2 | normal | 7907 |

All units: clean process exit, observer rows retained (8 rows + digest),
response retained, atomic publication (`unit.json`, `markers.json`,
`identity-pre/post.json`, `server.log`, `obs.row*.f32`).

## H5 result (the pilot's question)

The Qwen3.8-Flash-Next output projection (case 3072) dispatches on the
**vector path** in every unit:

```
route=mat-vec  pipe=mul_mat_vec_q4_k_f32_f32  family=mmv
quant_y=0  split_k=0  64b=0
dims=2560x248320:2560x1->248320x1  types=q4_K*f32->f32
```

10 route markers per unit (one per generated token, single-token decode
of this hybrid-SSM model), all agreeing. Weight `output.weight` is
`[2560, 248320]` q4_K (K x N convention; n_embd=2560).

**H5_CANDIDATE is ineligible**: `GGML_VK_DISABLE_COOPMAT2` selects only
the matrix-matrix pipeline family; the output projection never dispatches
mat-mat in this workload, so the one-factor control cannot bind. Per the
issue's iff-eligible clause, no H5_CANDIDATE arm was run. A4 was not
needed (screening classification consistent across all units; no mismatch
ever observed).

## Producer defects found and fixed during the pilot

Three parser defects, all producer-side, each quarantined with the full
unit retained on the subject host
(`evidence/producer-defect-quarantine/{base-parse-defect-001,
base-run2-parser-defect-001, base-run3-prefix-law-001}`):

1. Real-stream markers carry the GGML common-log prefix; synthetic-only
   `startswith` law never survived it. Fixed: bare-or-anchor law.
2. Frozen geometry constants were wrong (assumed `248320x2048` `IQ1_S`;
   observed `2560x248320` `q4_K`). Fixed to observed truth.
3. Concurrent GGML log sites interleave text mid-line before markers
   (three distinct shapes observed). Whitelisting shapes cannot hold;
   anchor law adopted: the text before a marker must end with a valid
   `<ts> <level> ` common-log prefix, and all integrity lives in the
   strict whole-line marker fullmatch.

Inference completed correctly in every quarantined unit; only parsing
failed. No evidence was discarded (logs retained under quarantine).

## Retained log exemplars

`logs/d262-base-001.server.log.gz` (sha256 of uncompressed
`406f845a7f17602c8cd726f0f5aec7ceca7b181b4fa6b2e5d0b655162cb06894`) and
`logs/d262-a1-001.server.log.gz` (uncompressed
`4d760a909d1e7b115ef5e247533fb940cf68d37548e125d822373654d0c5f344`).
All six unit server logs retained on inferswarm01
(`/home/hermes/is262-evidence/d262-*/`).
