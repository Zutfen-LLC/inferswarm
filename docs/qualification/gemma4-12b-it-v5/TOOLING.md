# v5 CPU/static tooling

- `scripts/generate_issue109_corpora.py` deterministically produces the fresh c109 1416-case IID mixture-population calibration corpus and p109 48-case pool from the pinned tokenizer; it never initializes a model.
- `scripts/issue109_v5_methodology.py` derives the mixture-population statistical design (1416/24/24 components/alpha=0.05) and re-exports the unchanged v4 semantic gate.
- `scripts/issue109_v5_contract.py` mechanically merges the accepted #108 fp32-consumer-logits/E_D reclassification with the twelve unchanged telemetry identities.
- `scripts/build_issue109_schemas.py` and `scripts/build_issue109_disjointness.py` emit the versioned JSON Schemas and the historical-exclusion proof. Predictive prompt/token collisions are audit-only retained IID draws.
- `scripts/build_issue109_historical_exclusion.py` emits the fixed hash-bound historical identity inventory. The predictive generator applies case-local rejection sampling when an identity is in this inventory.
- `scripts/issue109_v5_methodology_freeze.py` validates the complete v5 freeze against the accepted #108 doctrine and emits the terminal record; run it to reproduce `GEMMA_V5_CORRECTED_QUALIFICATION_METHODOLOGY_FROZEN`.
- `scripts/issue109_v5_thresholds.py` is future-calibration-only and rejects a count other than 1416 statistical cases, eight selected stress cases, or an incomplete holdout custody record.
- `scripts/verify_issue109_v5_unseal.py` hashes actual supplied core-threshold/ciphertext/certificate bytes, validates external two-custodian metadata, and stops before decrypt.
- `scripts/commit_issue109_holdout.py` creates public commitment/custody records from a transient plaintext on the sealing host. It derives the recipient public-key DER hash from the committed certificate. Plaintext, secret seed, and key are never repository artifacts.
- `scripts/select_issue109_margin_stress_v5.py` / `scripts/commit_issue109_stress_selection.py` freeze the (unchanged from v4) stress-selection rule and replay selection from already-computed reference margins; neither executes a model.

All static tooling is prohibited from importing or initializing torch, transformers, Triton, CUDA, FreeToken runtime, or NVIDIA queries.

Reproduce the corpora (requires the pinned `tokenizer.json`, SHA-256 `cc8d3a0ce36466ccc1278bf987df5f71db1719b9ca6b4118264f45cb627bfe0f`, and the `tokenizers` package):

```sh
python3 scripts/generate_issue109_corpora.py --tokenizer-json tokenizer.json \
  --calibration-out docs/qualification/gemma4-12b-it-v5/manifests/calibration-corpus.json \
  --stress-pool-out docs/qualification/gemma4-12b-it-v5/manifests/stress-pool.json
```

The source input is `google/gemma-4-12B-it`, revision `707f0a3b8a3c7ad586ed01e27eafbad8a27dd0f7`, file `tokenizer.json`. Verify its SHA-256 before generation. Do not commit the tokenizer input.

Reproduce and verify the freeze record (pure stdlib, no tokenizer required):

```sh
python3 scripts/issue109_v5_methodology_freeze.py
python3 -m unittest tests.test_issue109_v5_methodology tests.test_issue109_v5_thresholds tests.test_issue109_v5_methodology_freeze -v
```
