# R7-B — DeepSeek V4.1 Flash runtime substrate correction

Status: CPU/static source audit for [issue #209](https://github.com/Zutfen-LLC/inferswarm/issues/209). This additive correction preserves the accepted R7-A bundle byte-for-byte and supersedes the insufficient one-file vLLM disposition at `69e07e5`; its historical result and reason remain in `superseded-69e07e5.json`.

## Runtime decision

`runtime-authority.json` rejects vLLM `0eae9acd4d01574e12d4ecf6a0229813f7fdb799` only on p8 (`observable_cache_authority`), which is `UNPROVEN`. p1–p7, p9, and p10 are `PASS`. `external-source-evidence.json` pins its Apache-2.0 license, build configuration, full-file SHA-256 identities, paths, and decisive excerpts for the DeepSeek V4.1 model, PP utilities, standard safetensors loader, and attention/cache implementation.

The loader handles standard Hugging Face `model.safetensors.index.json` plus safetensor shards. The PP helper creates real layers only in the local interval and uses `PPMissingLayer` elsewhere; the DeepSeek loader skips parameters belonging to missing stages. A broad backing iterator therefore is not proof of broad active materialization. The model transfers explicit `IntermediateTensors` across PP stages. The V4.1 attention source identifies KV/index-source owners, shared-cache dependencies, prefill/decode token accounting, and rejects PP cuts inside a KV-sharing group.

## Blocking seam

The retained attention source does not establish request/session cache lifetime, invalidation, or a legal reconstruction boundary. Therefore it cannot establish p8 or authorize a strategy adapter, a selected shape, or a compact execution fixture. The smallest next evidence is an exact pinned vLLM request/session KV-cache lifecycle source, including invalidation/reconstruction, bound to the V4.1 cache-source mapping; it may then re-adjudicate p8 without downloading a checkpoint or executing a model.

The machine-derived terminal is `R7B_RUNTIME_SUBSTRATE_PREREQUISITE`, mechanically because p8 is not `PASS`. It grants no execution authorization.

## Scope and reproduction

No strategy adapter or compact fixture was implemented. No full checkpoint was downloaded. No model code was executed or imported. No GPU/CUDA/Vulkan qualification, serving, conversion, hybrid stage+expert work, vision, or MTP activity occurred.

```bash
python3 scripts/finalize_repository.py --write
python3 -m unittest tests.test_issue209_r7b -v
python3 scripts/finalize_repository.py --check
```
