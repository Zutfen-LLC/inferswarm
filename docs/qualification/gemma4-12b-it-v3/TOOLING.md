# v3 tooling inventory and build/freeze audit (issue #86)

All tools are CPU-only pure Python (stdlib + jsonschema in tests/verifier).
Purity is unit-tested: no torch/triton/transformers/numpy/CUDA imports, no
subprocess, no NVIDIA device queries, no model runtime. The corpus
generator imports only the pinned `tokenizers` JSON file (tokenizer-pure;
no model weights).

## Scripts

| Script | Role |
|---|---|
| `scripts/issue86_v3_methodology.py` | frozen identities, D(r) construction (`reference-top-1024-with-cutoff-ties/1`), frozen argmax/tie-break, decision_local_error / case_E_D / E_D, 16-family design, `evaluate_decision` semantic gate (exact §9 order) |
| `scripts/generate_issue86_corpora.py` | deterministic c86-*/p86-*/h86-* generation (v1 machinery, new seeds/prefixes/schemas) |
| `scripts/build_issue86_disjointness.py` | mechanical disjointness proof + frozen identity printout |
| `scripts/commit_issue86_stress_selection.py` | public stress-selection commitment (pre-reference) |
| `scripts/select_issue86_margin_stress_v3.py` | frozen v3 selector (zero-eligible; negative/nonfinite fatal) |
| `scripts/commit_issue86_holdout.py` | holdout commitment + custody-record builders (historical-reuse guards) |
| `scripts/build_issue86_schemas.py` | deterministic emission of all 9 v3 JSON Schemas |
| `scripts/issue86_v3_thresholds.py` | deterministic 15-limit + E_D threshold derivation; `statistical-design` subcommand. The complete 48-case reference-margin summary is a REQUIRED input (`--reference-margins`): the frozen selector is replayed over it and the committed selected-eight must equal the replay exactly (`SELECTED_EIGHT_NOT_SELECTOR_DERIVED` otherwise); the summary SHA is bound into the manifest (`reference_margin_summary_sha256`) |
| `scripts/verify_issue86_v3_unseal.py` | v3 unseal preflight — never decrypts, stops before decrypt. The CLI REQUIRES `--holdout-ciphertext` and `--recipient-certificate` file paths and hashes the ACTUAL bytes of the supplied files; missing files fail unreadable, corrupt/wrong/historical material fails the identity checks (no frozen-hash substitution anywhere in the CLI path) |

## Build/freeze chronology (2026-09-04, orchestrator host)

1. tokenizer purity: pinned `tokenizer.json` sha256 `cc8d3a0c…` verified
   before generation (`tokenizers` 0.23.1 venv, `/tmp/i74gen`);
2. c86 corpus + p86 pool generated, canonical JSON, committed manifests;
3. disjointness proven mechanically (prompt + token-id hash set
   intersections, all empty vs c74/p74/p76/h74 and v3-internal);
4. selector written, commitment generated binding the exact pool +
   selector SHA (state `COMMITTED_BEFORE_MATCHED_REFERENCE_EXECUTION`);
5. fresh RSA-3072 keypair + secret seed (`openssl genrsa`, CSPRNG);
   h86 holdout generated, sealed (CMS AES-256-CBC DER), plaintext
   destroyed; commitment + custody record built; key/seed distributed to
   two custodians (orchestrator + inferswarm00), permissions 0700/0600,
   public-key match verified non-decrypting; staging wiped;
6. schemas emitted deterministically; tooling + 89-test suite written;
7. no model/GPU execution occurred at any step; no decrypt performed.

## Frozen SHA-256 identities (committed v3 artifacts)

```
09731f1b2e66a6892b886c01bd2ec058be147b73885213844f2863caa10b41b6  manifests/calibration-corpus.json (canonical)
4975e0bba93c39a7e1eb9eac79435675da26ce5f29f25936997e4c79be6faa5f  c86 case-id set
71299a2b827c102667457fb076acece563e3e0150f330962b0f694c6682f2191  c86 case identities
4e4735c19f10bdcff4bf4173d9e96d2330df5c98de40f2701e1e3c309d29f015  manifests/stress-pool.json (canonical)
b04bae2fe5ab3d166417c20cad52241aac24770c12b82a7f23c42a81a3875ef1  p86 case-id set
91119013a6c097e636c2cc6619d8b8635760e22c70e592bed462e8ae6a5797fe  p86 case identities
4ec7233c0344ff98e9c914606904e6ccb74b29e5d001ffe20579d051fce74740  manifests/stress-selection-commitment.json
ff0ac30b5ce147c9e446b7765263551a5d7226c83c92308a4e5b2f9c81044e91  scripts/select_issue86_margin_stress_v3.py
7dc3af038ac1e6a71bfb4b7088a1a43f4366dfe991e212c3cbd2794e58e4dac8  sealed/holdout.cms
680a01b722b28e6e147ace0bb6ade3f3dfc1915afdda480498f97de3042d1542  sealed/recipient-certificate.pem
fc56175d275b24344354828957dfef84efc1ff3bfd02d996efe7a4d78f14cf9b  recipient public key (DER)
e6daaf451dc823464d80b3f3a04ad26f4b3a74698f1f225212c00b863016899b  custodian private-key identity (never committed)
0d55476a07bc981f93b3a3c01c7bfc4bdab35eada2042b726658ad91b6d842b8  secret seed (sha; never committed)
```

(File-hashes of the remaining artifacts are pinned by this repository's
commit itself; the tooling constants pin the canonical-JSON hashes above.)

## Explicit non-claims

- no physical execution of any kind occurred during this freeze;
- the selected-eight, reference-margin summary, decision-domain manifest,
  calibration summary, and real threshold manifest DO NOT EXIST yet —
  they are future physical artifacts of the successor campaign issue;
- the v3 holdout is `SEALED_NOT_CONSUMED`; the historical #74 holdout is
  untouched and permanently excluded from the v3 path;
- passing this gate authorizes nothing physical; only maintainer
  acceptance of this PR plus a NEW issue may authorize the v3 physical
  campaign.
