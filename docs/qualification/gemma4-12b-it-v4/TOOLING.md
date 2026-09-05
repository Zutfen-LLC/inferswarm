# v4 CPU/static tooling

- `scripts/generate_issue95_corpora.py` deterministically produces the fresh c95 1896-case corpus and p95 48-case pool from the pinned tokenizer; it never initializes a model.
- `scripts/issue95_v4_contract.py` dynamically binds #93's fifteen identities, derives 79/1896/1/80/4/80, and keeps core limits separate from telemetry bands.
- `scripts/issue95_v4_thresholds.py` is future-calibration-only and rejects a count other than 1896 statistical cases or eight selected stress cases.
- `scripts/verify_issue95_v4_unseal.py` hashes actual supplied core-threshold/ciphertext/certificate bytes, validates external two-custodian metadata, and stops before decrypt.
- `scripts/commit_issue95_holdout.py` creates public commitment/custody records from a transient plaintext on the sealing host. Plaintext, secret seed, and key are never repository artifacts.

All static tooling is prohibited from importing or initializing torch, transformers, Triton, CUDA, FreeToken runtime, or NVIDIA queries.
