# Issue #264 Task 1 — exact output MMV selector (source only)

The #262 source tree `015c874f0cc0635fa1369650098c0137f9a492f0` is the required predecessor. `scripts/issue264_source_patch.py` replays the pinned predecessor through #260, #262, R8-E and comparator/2 via the frozen #262 builder, checks the complete working tree and Vulkan source digest before applying `patches/issue264-mmv-selector.patch`, then hashes the entire successor tree. The patch and full-tree hashes are frozen in `issue264-source-identity.json`. Build outputs must be **new directories**; the retained pilot sources are read-only.

CPU-only replay from a clean pinned llama.cpp checkout:

```sh
python3 scripts/issue264_source_patch.py --source /path/to/clean-b29c606e-checkout --output /path/to/new-i264-output
python3 -m unittest tests.test_issue264_h5 tests.test_issue264_source_patch -v
```

`GGML_VK_I264_MMV` is parsed at Vulkan backend initialization: absent or `base` selects the original SUBGROUP path; `large` selects the pre-existing LARGE q4_K/f32 DMMV pipeline. Every other value aborts before inference. The override is gated by `output.weight`, exact q4_K × f32 → f32 shape `2560x248320:2560x1->248320x1`, one vector column, unquantized Y and non-swapped mat-vec. No other dispatch, hardware capability, tensor type, request geometry, device placement or pipeline creation algorithm is changed. For the RTX 3060's subgroup size 32, BASE is SUBGROUP/local 32 and LARGE is HYBRID/local 128; unsupported or mismatched final compiled pipeline identities abort instead of reporting success.

The existing `ggml_vk_i262:v1|route` line is retained byte-for-byte. The new `ggml_vk_i264:v1|mmv` marker uses the *same event ID*, actual node/dimensions/types, requested state and the final compiled pipeline's creation-bound workgroup/reduction/local-size identity. It is emitted after descriptor-set request compiles the pipeline, just before dispatch. `scripts/issue264_h5.py` accepts exactly two ordered, individually i262-bound BASE→LARGE records and rejects malformed/missing/extra markers, wrong route/shape/type, wrong variant or wrong local size. IDs may reset across separately launched processes; each i264 event must match its immediately preceding i262 event.

This is a source freeze and CPU parser/transform check, **not** a Vulkan build or GPU/inference execution. Physical execution still requires the independent issue gate.
