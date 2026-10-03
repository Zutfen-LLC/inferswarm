# Issue #264 — pinned MMV source audit

**Status:** one source-supported minimal candidate; no physical execution. This audit is limited to source identity, existing artifact and subject-limit review. It does not claim a fresh build, Vulkan pipeline creation, dispatch, inference, numerical result, or execution authority.

## Authority and pin

Issue #264 is OPEN. Its complete body was retrieved and reviewed through the public GitHub API; the controller separately authenticated the issue and PR. The issue allows one minimal experiment-only BASE/alternate selector at the actual DMMV workgroup selection point, with exactly two states, preserving frozen operation/request/quantization/placement and an exact marker that distinguishes the selected implementation. It does not authorize a production/general selector, broader capability enumeration, or an unconditional physical run. Any physical work remains subject to the separate current pre-execution gate.

The pinned source identity is `issue264-source-identity-v2.json`: parent tree `015c874f0cc0635fa1369650098c0137f9a492f0`, issue #264 tree `23d38b96e371ad0634454d7bd6fe238da87eb1cb`, Vulkan source SHA-256 `551b6e7fd963fbf9cada48510df201cfa4bffa6a64bf4ea1d6d11d9e66999ebe`, and patch SHA-256 `f713767755cd40ee279aba6d4e72648c317e73a334d565a6cd0f176284e3226e`. Historical gen1 identity/tree `2d7a5693a8bf86648ee564d389a32c7c1671c571` remains preserved as historical source material; it is not the current selector source and neither generation is physical evidence.

The frozen operation is `output.weight`, route `mat-vec`, pipeline `mul_mat_vec_q4_k_f32_f32`, `quant_y=0`, `split_k=0`, dimensions `2560x248320:2560x1->248320x1`, types `q4_K*f32->f32`. Subject is RTX 3060 UUID `GPU-d5c05739-96c1-7e49-89b6-bf54c2121c55`, BDF `00000000:03:00.0`, Vulkan subgroup size 32, maximum workgroup invocation count 1024.

## Candidate ledger

The machine-readable ledger `candidates.json` contains every evaluated candidate with required fields: `id`, `site`, `exact_pipelines`, `frozen_eligibility`, `one_factor`, `subject_capability`, `disposition`, and `reason`.

Exactly one candidate is live: `DMMV_WORKGROUP_SUBGROUP_TO_LARGE`, at the existing `dmmv_wg` selection in `ggml_vk_get_dequantize_mul_mat_vec`:

| State | Workgroup | Reduction | Local size |
|---|---|---|---|
| BASE | `SUBGROUP` | `SUBGROUP` | `{32,1,1}` |
| Alternate | `LARGE` | `HYBRID` | `{128,1,1}` |

Both use the shared pipeline name `mul_mat_vec_q4_k_f32_f32`; the dispatch marker must therefore identify the *actual resolved* workgroup and reduction variant, not just the shared name. Source indicates the NVIDIA post-Turing baseline uses LARGE only for `M<=8192 && K>=1024`; frozen `M=248320`, so BASE is SUBGROUP. Existing retained Q4_K/f32 SPIR-V forms for SHMEM/default, HYBRID, and SUBGROUP passed `spirv-val --target-env vulkan1.2`. This is inspection/validation of retained artifacts, not a fresh build or device pipeline creation. Both local sizes are within the reported device limit.

This is ranked **3**, not rank 1: the recorded priority order is runtime/environment controls, CLI controls, then minimal source switch. No earlier environment control is live for this exact frozen route. The other evaluated candidates—`GGML_VK_DISABLE_MMVQ`, `GGML_VK_FORCE_MMVQ`, `GGML_VK_DISABLE_INTEGER_DOT_PRODUCT`, `GGML_VK_DISABLE_COOPMAT2`, and `GGML_VK_SERIALIZE_SUBMISSIONS`—are fully dispositioned in the ledger. They are dead for the frozen path or, for forced MMVQ, violate one-factor identity by changing RHS quantization/type.

## Source-audit limits

No selector implementation, build, inference, GPU dispatch, or physical measurement was performed for this documentation task. Source-level eligibility and reported device limits do not establish runtime success or numerical behavior. Do not infer a physical result, zero-candidate terminal, or theorem conclusion from this audit.
