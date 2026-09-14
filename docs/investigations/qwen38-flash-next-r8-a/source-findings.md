# R8-A source-authority and representation findings

Status: Phase 0--2 static research input for [issue #189](https://github.com/Zutfen-LLC/inferswarm/issues/189), not an architecture decision, execution authorization, runtime qualification, or performance/correctness result.

Retrieved: 2026-09-14T16:12:41-04:00.  Retrieval used the Hugging Face
revision/tree APIs and small, pinned source files only; no GGUF weight artifact
or physical workload was downloaded or run.  `main` names are mutable: every
reference below uses a commit SHA.

## Separate authorities

| role | pinned repository and revision | primary evidence |
| --- | --- | --- |
| Official upstream checkpoint | [`Qwen/Qwen3.8-Flash-Next@de4b8e4d43b917e7706784d8bb445c9af86a3540`](https://huggingface.co/Qwen/Qwen3.8-Flash-Next/tree/de4b8e4d43b917e7706784d8bb445c9af86a3540) | [revision API](https://huggingface.co/api/models/Qwen/Qwen3.8-Flash-Next/revision/de4b8e4d43b917e7706784d8bb445c9af86a3540?blobs=true), [complete tree API (page 1)](https://huggingface.co/api/models/Qwen/Qwen3.8-Flash-Next/tree/de4b8e4d43b917e7706784d8bb445c9af86a3540?recursive=true&expand=true&limit=100) |
| Practical, third-party conversion | [`unsloth/Qwen3.8-Flash-Next-GGUF@38bb39ee97821de2c9009abb7e93950eec396e66`](https://huggingface.co/unsloth/Qwen3.8-Flash-Next-GGUF/tree/38bb39ee97821de2c9009abb7e93950eec396e66) | [revision API](https://huggingface.co/api/models/unsloth/Qwen3.8-Flash-Next-GGUF/revision/38bb39ee97821de2c9009abb7e93950eec396e66?blobs=true), [complete tree API](https://huggingface.co/api/models/unsloth/Qwen3.8-Flash-Next-GGUF/tree/38bb39ee97821de2c9009abb7e93950eec396e66?recursive=true&expand=true&limit=100) |

The latter card declares `base_model: Qwen/Qwen3.8-Flash-Next`; it is still a
separate Unsloth-produced GGUF representation, **not** the official
checkpoint.  Both revisions were public and ungated at retrieval.  The
InferSwarm research starting head was
`f349cbdfbb20ac933447c483f855b1f501aa7a1c`; that exact #117 closure merge is
the checked head and therefore ancestral to this record.

## Official source and model semantics

The official pinned `config.json` identifies a multimodal
`Qwen4ExpForConditionalGeneration` / `qwen4_exp` model, with a 48-layer text
configuration (`hidden_size=2560`), 512 experts and 10 selected experts per
token, `max_position_embeddings=262144`, one MTP layer, `use_cache=true`, and
a 27-depth vision configuration.  These are configuration declarations, not
an execution result.  [Pinned config](https://huggingface.co/Qwen/Qwen3.8-Flash-Next/raw/de4b8e4d43b917e7706784d8bb445c9af86a3540/config.json).

The Qwen Team's source README at commit
[`69885871a64393807d988b27b1b5e380e8f28526`](https://github.com/QwenLM/Qwen3.8-Flash-Next/commit/69885871a64393807d988b27b1b5e380e8f28526)
describes a GDN+QSA hybrid, 125B main parameters, 51B N-gram embeddings and
6B activated parameters per token.  It says the N-gram table may be offloaded
to host memory with asynchronous prefetch overlap, and that llama.cpp supports
the text and vision model.  These are upstream semantic/runtime-support claims,
not validation of a particular conversion or placement:
[architecture and N-gram passage](https://github.com/QwenLM/Qwen3.8-Flash-Next/blob/69885871a64393807d988b27b1b5e380e8f28526/README.md#L28-L33),
[llama.cpp passage](https://github.com/QwenLM/Qwen3.8-Flash-Next/blob/69885871a64393807d988b27b1b5e380e8f28526/README.md#L87-L91).

The official checkpoint tree has **144 files**, including **131 safetensors
shards** named `model-00001-of-00131.safetensors` through
`model-00131-of-00131.safetensors`.  Its reported aggregate is
**360,023,351,514 bytes**; the shard subtotal is **360,000,192,888 bytes**
(CALCULATED by summing the tree API's per-object `size` fields).  Supporting
metadata includes the safetensors index, tokenizer files, chat template,
processor configurations, and license.  The tree API supplies each weight
object's LFS SHA-256 identity; a later census must bind state classes to those
object/tensor identities rather than infer them from aggregate parameter
claims alone.

## Unsloth GGUF inventory

The pinned conversion tree contains 60 files: 56 GGUF files, 3 small text
files, and `imatrix_unsloth.gguf_file` (580,038,720 bytes).  The following
totals are **CALCULATED** from the authoritative per-object API sizes; they
describe complete split-file sets, not accelerator-resident requirements.

| main representation | split GGUF files | bytes | GiB |
| --- | ---: | ---: | ---: |
| BF16 | 8 | 354,029,930,496 | 329.72 |
| Q8_0 | 6 | 188,225,033,248 | 175.30 |
| UD-IQ1_M | 3 | 74,538,755,776 | 69.42 |
| UD-IQ1_S | 3 | 72,546,461,344 | 67.56 |
| UD-Q2_K_XL | 3 | 78,869,128,864 | 73.45 |
| UD-IQ3_XXS | 3 | 81,961,823,936 | 76.33 |
| UD-Q3_K_XL | 3 | 89,986,353,824 | 83.81 |
| UD-IQ4_XS | 3 | 93,682,584,224 | 87.25 |
| UD-Q4_K_XL | 4 | 111,334,654,784 | 103.69 |
| UD-Q5_K_XL | 6 | 158,286,406,650 | 147.42 |
| UD-Q6_K_XL | 6 | 169,165,382,688 | 157.55 |

The tree also provides MTP sidecars: main and `shared` BF16, Q4_K_M, and Q8_0
files (six total, 24,616,077,888 bytes), plus `mmproj-BF16.gguf`
(907,542,944 bytes) and `mmproj-F16.gguf` (904,004,000 bytes).  The conversion
card describes the subject as a causal language model with vision encoder and
states the same 125B / 6B-active / 51B-N-gram / 4B-MTP model overview:
[pinned card](https://huggingface.co/unsloth/Qwen3.8-Flash-Next-GGUF/blob/38bb39ee97821de2c9009abb7e93950eec396e66/README.md#L57-L86).

Static inventory alone does **not** establish GGUF architecture metadata,
per-tensor quantization, an independently addressable N-gram table, or a safe
offload mode.  Those require a subsequent bounded pinned-GGUF header/range
census.  Nor do the aggregate bytes establish per-resource fit, runtime
support, correctness qualification, or useful performance.

## Retained retrieval identities

These SHA-256 values identify the exact small responses fetched during this
research; they are audit aids, not upstream artifact identities.

| retrieved pinned content | SHA-256 |
| --- | --- |
| official `config.json` | `889658f2508e8c61d409b02e70e0d78d8d4452ec65aaafbe129805d213d2e74b` |
| official model card `README.md` | `35ca37ccc366f1ba478dab33841a2c0c18ce53fd62f291ca05341f7728b225b2` |
| official Qwen GitHub README at `69885871…` | `34d45d3486c29dcc23dade1472b5cbf1347ffe0a1adc3334aec83b3dc4e08c50` |
| Unsloth model card `README.md` | `9538227ff778ba7d8ba61b42cde3927487bf4c9c647ce18ac31d08a0b42998e6` |
| official revision API response | `9212971add20d6aea4d577c020efd1c5b2a68bd28c319c10317f71277d60a787` |
| Unsloth revision API response | `df9b512a3061533226a0376e1fbd5b9eb082f3aa050ce3ddcd979c6d5f631310` |

## Non-claims

This note makes no Qwen3.8 correctness, performance, runtime-defect,
decomposition-legality, capacity-fit, n-gram-residency, or R8-B authorization
claim.  It records the reproducible source authorities and the Phase 0--2
repository/representation facts needed before those questions can be tested.
