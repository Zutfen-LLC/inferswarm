# Factorial MMVQ source scope

This is source verification for the diagnostic candidate, not a hardware result
or numerical qualification. The unchanged native pin is
`b29c606e28a01b1bc8c1351026a0fa6e616bf6c4`. The checker retains
`b29c606e-q8_0-mmvq-vendor-accuracy-union/1` and its explicit vendor-accuracy
assumption. No tolerance or worker arithmetic changes are introduced.

At that pin, `ggml/src/ggml-cuda/ggml-cuda.cu:1910` dispatches
`GGML_OP_MUL_MAT_ID` with F32 input/output and quantized weights to
`ggml_cuda_mul_mat_vec_q` when output `ne[2]` is within the MMVQ limit.
`ggml/src/ggml-cuda/mmvq.cuh:3` sets that limit to eight.
`mmvq.cu:177` and `:285` make Q8_0's limit eight on the NVIDIA
Turing-and-newer path applicable to the approved RTX 3060. T1 and T4 therefore
return through MMVQ before the subsequent MMQ fallback test. Neither selected
expert count nor resident expert count participates in this limit.

The distinction is explicit in `mmvq.cu:1505`: with IDs, `ncols_dst=ne2`
is token width, `nchannels_dst=ne1` is selected expert count, and the source
expert dimension is `ne02` (resident count). At `mmvq.cu:1149`, ID-based
multi-token work uses the dedicated MoE MMVQ kernel. Its launch at `:1035`
uses selected count as grid channels, and `:891` obtains each compact resident
expert through `ids[channel_dst + token_idx * ids_stride]`. Increasing selected
count from five to ten changes the grid's useful expert work; increasing
residency from five to 26 changes the bank/index range. It does not turn T4
into a ten-column MMQ request. T1 uses the existing single-column MMVQ path at
`:1160`, with the same distinction between grid channels and resident IDs.

Gate/up operand width is 2560 and down operand width is 640. Both remain
complete Q8_0 blocks with the previously supported output dimensions. The
factorial checker changes only cardinality/indexing: ten selected stage planes
can address 26 resident slices. Its held-out tests separately cover T1/T4,
gate/down operand indexing, every selected expert omission, a wrongly truncated
ten-slice bank, duplicate output mappings and an out-of-range resident ID.

Timed graphs may use eligible existing fusion; untimed retained graphs can
inhibit it. Exact per-arm timed/replay output hashes remain mandatory before
retained stages support a timing interpretation. This source proof does not
claim to observe a particular device kernel, compiler instruction or GPU time.

The inspected files had these SHA-256 identities:

| Pinned source file | SHA-256 |
| --- | --- |
| `ggml-cuda.cu` | `523470d6604755b82d0208414ce40f1378941b10bc1349763bbdf02edaab9634` |
| `mmvq.cu` | `d4c70f68ab79d463fd6fd52cac66a62e915858397ba4b2b7f658a7fbf13121f3` |
| `mmvq.cuh` | `b37f8359f519ba90ddecd9cb3ca5f8c2ae05685bfae6813d435d75763c2bb006` |
