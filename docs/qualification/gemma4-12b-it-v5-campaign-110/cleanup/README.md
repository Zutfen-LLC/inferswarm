# Issue #115 — post-V5 raw-evidence retention & expungement

Status: Phase A complete (manifest committed); Phase B executed after all
deletion gates passed. See `RAW-EVIDENCE-RETENTION.json` (Phase A) and
`RAW-EVIDENCE-EXPUNGEMENT.json` (Phase B audit).

## What this is

A storage-cleanup-only operation on the maintainer-accepted, merged Issue
#110 campaign (`V5_QUALIFICATION_PASS`, immutable). It reclaims ~729 GiB of
node-local campaign scratch while preserving a small, hash-bound,
two-copy durable archive of every acceptance-bearing raw object.

No model execution, no CUDA, no evidence regeneration, no threshold,
verdict, or methodology change of any kind.

## Classification (five classes, exactly one per object)

- `RETAIN_COMPACT_DERIVATION` — all accepted committed evidence on `main`
  (`docs/qualification/gemma4-12b-it-v5-campaign-110/`, the frozen v5
  methodology area, `scripts/`, and the FreeToken producer trees). Never a
  deletion target.
- `RETAIN_DURABLE_RAW` — the content-addressed archive at
  `/srv/inferswarm/archive/issue110-v5/sha256/<digest>` on inferswarm01
  and inferswarm03 (two physically independent disks), 516 objects,
  460,854,709 bytes, containing:
  - all 24 consumed h109 cases × 8 decisions × 2 arms = **384
    full-vocabulary FP32 consumer-logit rows** with producer case records
    and assembled observations (every row verified against its producer
    `row_f32_sha256` pin);
  - the three threshold-provenance cases (`c109-04-02-024`,
    `c109-02-03-030`, `p109-03-03-01`), both arms × all 8 decisions;
  - run metadata byte-equal to the committed a2/b artifacts.
- `RETAIN_PRIVATE_DIAGNOSTIC` — exactly one restricted orchestrator-local
  copy of the consumed h109 plaintext + derived execution corpus
  (0700/0600, `CONSUMED_DIAGNOSTIC_ONLY`), outside Git.
- `SAFE_TO_EXPUNGE_AFTER_ACCEPTANCE` — the path-specific targets listed in
  the retention manifest (bulk capture bundles, duplicate
  materializations, duplicate derivations, duplicate plaintext-derived
  corpus copies, orchestration scratch, and custody secrets).
- `UNCLASSIFIED_STOP` — two fail-closed keeps (the in-place node copy of
  the committed adjudication outputs and the campaign manifests dir).

## Independent reverification from retained rows alone

Recomputation on inferswarm01 from archive rows only, using the frozen
scripts at accepted `main` (`546ff9d`), pure stdlib:

- max-abs `0x1.b48p+3`, RMS `0x1.44dcfa4242a7ap+1`,
  decision-local E_D `0x1.49p+3` — all three terminal maxima reproduced
  exactly;
- the 192/192 `SEMANTIC_PASS` accounting reconstructed decision-by-decision
  under the frozen domain/tie rules (192 unstable, zero failures of every
  class);
- all six frozen limit components (statistical + stress maxima for the
  three core families) reproduced from the three retained provenance
  cases' raw rows.

## Custody-secret lifecycle

The h109 holdout is permanently consumed. After the restricted diagnostic
plaintext and all public commitment/unseal records were verified durable,
all three private-key/secret-seed custodian copies (orchestrator,
inferswarm00, inferswarm01; identical SHA-256) were destroyed so the
consumed holdout can never be freshly decrypted or regenerated. The
sealed ciphertext, recipient certificate, and every public commitment
remain committed in the repository.

## Expected reclaim

| host | bytes |
|---|---|
| inferswarm01 | 405,023,971,156 |
| inferswarm03 | 241,564,907,761 |
| inferswarm04 | 135,696,473,216 |
| orchestrator | 63,950,602 |
| inferswarm00 | 2,553 |
| **total** | **782,349,305,288 (~728.6 GiB)** |

Deletion is path-specific and manifest-driven; campaign roots
(`/srv/models/issue110`, `/srv/inferswarm/state/issue110`) are never
deletion targets themselves.
