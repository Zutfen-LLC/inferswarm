# Issue #264 — corrected gen2 MMV source audit

**State:** source-only correction; prospective, not execution authorization. No build, inference, GPU dispatch, measurement, or physical evidence is claimed. Gen1 files are preserved byte-for-byte as historical snapshots.

## Scope and source pin

Issue #264 is OPEN; scope remains one experiment-only BASE/alternate selector at the actual DMMV workgroup selection site. The pinned #264 source identity is `issue264-source-identity-v2.json`, tree `23d38b96e371ad0634454d7bd6fe238da87eb1cb`, Vulkan source SHA-256 `551b6e7fd963fbf9cada48510df201cfa4bffa6a64bf4ea1d6d11d9e66999ebe`, parent tree `015c874f0cc0635fa1369650098c0137f9a492f0`, patch SHA-256 `f713767755cd40ee279aba6d4e72648c317e73a334d565a6cd0f176284e3226e`. Historical gen1 tree `2d7a5693a8bf86648ee564d389a32c7c1671c571` remains historical only.

Frozen operation: `output.weight`, `mat-vec`, `mul_mat_vec_q4_k_f32_f32`, `quant_y=0`, `split_k=0`, dimensions `2560x248320:2560x1->248320x1`, types `q4_K*f32->f32`. Sole live selector: `DMMV_WORKGROUP_SUBGROUP_TO_LARGE`, BASE SUBGROUP/SUBGROUP/local `{32,1,1}`, alternate LARGE/HYBRID/local `{128,1,1}`. Its priority is 3 (runtime/environment controls, CLI controls, then minimal source switch). Both use a shared pipeline name; exact dispatch marker must report resolved workgroup/reduction/local size.

## Candidate corrections

`candidates-v2.json` gives every candidate every required ledger field. There is exactly one `LIVE_CANDIDATE`. A1 `GGML_VK_SERIALIZE_SUBMISSIONS` is the existing `device->serialize_submissions` queue-submission synchronization branch in `ggml_vk_submit`; it does not select an MMV implementation and is `DEAD_FOR_FROZEN_PATH`. A4 `GGML_VK_PREFER_HOST_MEMORY` and A5 `GGML_VK_DISABLE_HOST_VISIBLE_VIDMEM` are memory allocation-placement branches, not MMV pipeline changes; each is `REJECTED_NOT_ONE_FACTOR`. `SUBGROUP_ARITHMETIC_REDUCTION` is an automatically selected capability with no independent exposed control; it is `REJECTED_NOT_ONE_FACTOR`, not an invented candidate. Existing MMVQ, integer-dot-product, coopmat2 and other controls retain their specific dead/not-one-factor dispositions.

## Workload and repeat law

Gen2 is bound to accepted Issue #250 `case-3072`, verified by `scripts/issue250_physical.py::verify_fixtures(repo_root)` against `docs/investigations/qwen38-flash-next-r8-b/evidence/reference/fixture-ladder.json`, SHA-256 `419bde668c7b3cedf823c98ca0a883560a9a501007f9a28bf8d826148ee822db`. The exact accepted request contract is in `scripts/issue250_diagnostic.py::REQUEST_CONTRACT`: `cache_prompt=false`, `n_predict=8`, `return_tokens=true`, `samplers=["top_k"]`, `seed=0`, `stream=false`, `temperature=0.0`, `top_k=1`. The verified prompt is 3077 tokens. The producer must freeze a canonical digest of accepted request plus exact fixture prompt before launch and revalidate it before launch; no caller prompt is accepted.

Each observer decision row is exactly 248,320 float32 values = 993,280 bytes; require exactly eight complete rows in indices 0..7, and have metadata and readers enforce count, index order/continuity, and per-row byte size. Compare units by SHA-256 of the bytewise concatenation of all eight full row byte strings in index order: `sha256(row[0] || row[1] || ... || row[7])`. Do not compare concatenated hex hashes, summaries, selected rows, metadata, or normalized floats. Run two fresh-process units first; if their digests differ, stop at two (`screening-variable`). Only if they match, run unit three. Any mismatch involving unit three is still `screening-variable`; three equal digests are screening-stable. Maximum three attempts, no retry/replacement.

## Limits

This audit adds no physical authorization and reports no living execution status. Gen2 methodology corrects only prospective documentation; prior committed gen1 bytes remain immutable and independently named. No sibling pilot files, accepted evidence, source implementation, CI, reducers, or status ledgers are changed.
