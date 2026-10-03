#!/usr/bin/env python3
"""#262 H5 instrumentation editor: applies the output-projection route marker
edits to ggml-vulkan.cpp on top of the #260 instrumented tree.

Fail-closed: every anchor must match exactly once (or an explicit expected
count); any drift aborts without writing.
"""
import sys

PATH = "ggml/src/ggml-vulkan/ggml-vulkan.cpp"

def edit(src: str) -> str:
    def sub1(old: str, new: str, what: str, count: int = 1):
        nonlocal src
        n = src.count(old)
        if n != count:
            sys.exit(f"anchor drift ({what}): expected {count} occurrence(s), found {n}")
        src = src.replace(old, new, count)

    # A. device struct: per-name creation-family registry
    sub1(
        "    bool coopmat2;\n    bool coopmat2_bf16_support {};\n    bool coopmat2_decode_vector;\n",
        "    bool coopmat2;\n    bool coopmat2_bf16_support {};\n    bool coopmat2_decode_vector;\n"
        "    // #262 H5 diagnostic: matmul pipeline name -> creating configuration branch.\n"
        "    std::map<std::string, std::string> i262_mm_family;\n",
        "device struct family map")

    # B. creation function: family variable before the shared lambda
    sub1(
        "    using spec_fn_t = std::function<std::vector<uint32_t>(const std::vector<uint32_t>&, bool)>;\n"
        "    auto const &create_mm_pipelines = [&](",
        "    // #262 H5: record which configuration branch created each matmul pipeline.\n"
        "    std::string i262_creation_family = \"unclassified\";\n"
        "    using spec_fn_t = std::function<std::vector<uint32_t>(const std::vector<uint32_t>&, bool)>;\n"
        "    auto const &create_mm_pipelines = [&](",
        "creation family var")

    # C. record families inside the shared lambda (after aligned creation)
    sub1(
        "            if (vec[i].aligned) {\n"
        "                ggml_vk_create_pipeline(device, vec[i].aligned,\n"
        "                    vec[i].aligned->name.empty() ? (shader_name + \"_aligned_\" + std::to_string(i)).c_str() : vec[i].aligned->name.c_str(),\n"
        "                    spv_len, spv_data, \"main\", param_count, push_constant_size,\n"
        "                    tc.wg_denoms, spec_fn(tc.warptile, true), tc.align,\n"
        "                    disable_robustness, rfs, rsgs);\n"
        "            }\n"
        "        }\n"
        "    };\n",
        "            if (vec[i].aligned) {\n"
        "                ggml_vk_create_pipeline(device, vec[i].aligned,\n"
        "                    vec[i].aligned->name.empty() ? (shader_name + \"_aligned_\" + std::to_string(i)).c_str() : vec[i].aligned->name.c_str(),\n"
        "                    spv_len, spv_data, \"main\", param_count, push_constant_size,\n"
        "                    tc.wg_denoms, spec_fn(tc.warptile, true), tc.align,\n"
        "                    disable_robustness, rfs, rsgs);\n"
        "            }\n"
        "            // #262 H5: bind created pipeline names to the active branch.\n"
        "            device->i262_mm_family[vec[i].unaligned->name] = i262_creation_family;\n"
        "            if (vec[i].aligned) {\n"
        "                device->i262_mm_family[vec[i].aligned->name] = i262_creation_family;\n"
        "            }\n"
        "        }\n"
        "    };\n",
        "lambda family recording")

    # D1. coopmat2 pipeline-creation branch head (NOT the earlier warptile
    # block: anchor on the cm2_spec lambda that only exists there).
    sub1(
        "    if (device->coopmat2) {\n"
        "        auto const &ggml_vk_mul_mm_cm2_spec = [&]",
        "    if (device->coopmat2) {\n"
        "        i262_creation_family = \"coopmat2\";\n"
        "        auto const &ggml_vk_mul_mm_cm2_spec = [&]",
        "coopmat2 branch head")

    # D2. coopmat1 branch head
    sub1(
        "    if (device->coopmat_support) {\n"
        "        spec_fn_t cm1_spec = [&](const std::vector<uint32_t>& wt, bool a) { return ggml_vk_mul_mm_spec(wt, a); };",
        "    if (device->coopmat_support) {\n"
        "        i262_creation_family = \"coopmat1\";\n"
        "        spec_fn_t cm1_spec = [&](const std::vector<uint32_t>& wt, bool a) { return ggml_vk_mul_mm_spec(wt, a); };",
        "coopmat1 branch head")

    # D3. BF16 fallback (outside both branches)
    sub1(
        "        const uint32_t s_warptile_wm_bf16 = device->subgroup_size == 8 ? 8 : 32;\n"
        "        std::vector<vk_tile_config> tc_bf16_fb = {",
        "        i262_creation_family = \"scalar-bf16-fallback\";\n"
        "        const uint32_t s_warptile_wm_bf16 = device->subgroup_size == 8 ? 8 : 32;\n"
        "        std::vector<vk_tile_config> tc_bf16_fb = {",
        "bf16 fallback family")

    # E. emission helper before ggml_vk_mul_mat_vec_q_f16
    helper = '''
// ---------------------------------------------------------------------------
// #262 H5 diagnostic: emit the ACTUAL selected route/pipeline for the frozen
// output projection (the tensor named "output.weight"). Observation only;
// originates at the real dispatch/selection sites, never at capability
// enumeration.
// ---------------------------------------------------------------------------
static std::atomic<uint64_t> ggml_vk_i262_next_route_id { 1 };

static void ggml_vk_i262_emit_output_route(ggml_backend_vk_context * ctx,
                                           const ggml_tensor * dst,
                                           const ggml_tensor * src0,
                                           const ggml_tensor * src1,
                                           const char * route,
                                           const vk_pipeline & pipe,
                                           bool quantize_y,
                                           uint32_t split_k) {
    const ggml_tensor * w = nullptr;
    int side = -1;
    if (src0 && strcmp(src0->name, "output.weight") == 0) { w = src0; side = 0; }
    else if (src1 && strcmp(src1->name, "output.weight") == 0) { w = src1; side = 1; }
    if (w == nullptr) { return; }
    std::string family;
    if (strcmp(route, "mat-vec") == 0) {
        family = quantize_y ? "mmvq-idp" : "mmv";
    } else {
        const auto it = ctx->device->i262_mm_family.find(pipe ? pipe->name : "");
        family = it != ctx->device->i262_mm_family.end() ? it->second : std::string("unclassified");
    }
#if defined(VK_EXT_shader_64bit_indexing)
    const int i262_64b = pipe && pipe->is_64b_indexing ? 1 : 0;
#else
    const int i262_64b = 0;
#endif
    const uint64_t rid = ggml_vk_i262_next_route_id.fetch_add(1, std::memory_order_relaxed);
    GGML_LOG_INFO("ggml_vk_i262:v1|route|id=%llu|graph=%llu|weight=output.weight|node=%s|side=%d|route=%s|pipe=%s|family=%s|quant_y=%d|split_k=%u|64b=%d|dims=%llux%llu:%llux%llu->%llux%llu|types=%s*%s->%s\\n",
        (unsigned long long) rid, (unsigned long long) ctx->i260_graph_id,
        (dst && dst->name[0]) ? dst->name : "-", side, route,
        pipe ? pipe->name.c_str() : "-", family.c_str(),
        quantize_y ? 1 : 0, split_k, i262_64b,
        (unsigned long long) (src0 ? src0->ne[0] : 0), (unsigned long long) (src0 ? src0->ne[1] : 0),
        (unsigned long long) (src1 ? src1->ne[0] : 0), (unsigned long long) (src1 ? src1->ne[1] : 0),
        (unsigned long long) (dst ? dst->ne[0] : 0), (unsigned long long) (dst ? dst->ne[1] : 0),
        src0 ? ggml_type_name(src0->type) : "-", src1 ? ggml_type_name(src1->type) : "-",
        dst ? ggml_type_name(dst->type) : "-");
}

'''
    sub1(
        "static void ggml_vk_mul_mat_q_f16(ggml_backend_vk_context * ctx, vk_context& subctx, const ggml_tensor * src0, const ggml_tensor * src1, ggml_tensor * dst, bool disable_split_k) {",
        helper +
        "static void ggml_vk_mul_mat_q_f16(ggml_backend_vk_context * ctx, vk_context& subctx, const ggml_tensor * src0, const ggml_tensor * src1, ggml_tensor * dst, bool disable_split_k) {",
        "helper insertion")

    # F. mat-vec emission after the final dmmv resolution. The anchor is the
    # mul_mat_vec_q_f16 copy: it is preceded by the y-noncontig assert that
    # exists only in the vector path (mul_mat_id_q_f16 lacks it).
    sub1(
        "    GGML_ASSERT(y_non_contig || !qy_needs_dequant);  // NOLINT\n"
        "\n"
        "    GGML_ASSERT(!qx_needs_dequant || to_fp16_vk_0 != nullptr);  // NOLINT\n"
        "    GGML_ASSERT(!qy_needs_dequant || to_fp16_vk_1 != nullptr);  // NOLINT\n"
        "    GGML_ASSERT(dmmv != nullptr);\n",
        "    GGML_ASSERT(y_non_contig || !qy_needs_dequant);  // NOLINT\n"
        "\n"
        "    GGML_ASSERT(!qx_needs_dequant || to_fp16_vk_0 != nullptr);  // NOLINT\n"
        "    GGML_ASSERT(!qy_needs_dequant || to_fp16_vk_1 != nullptr);  // NOLINT\n"
        "    GGML_ASSERT(dmmv != nullptr);\n"
        "    // #262 H5: the vector-path selection (incl. 64b variant) is final here.\n"
        "    ggml_vk_i262_emit_output_route(ctx, cgraph->nodes[node_idx], src0, src1, \"mat-vec\", dmmv, quantize_y, 0);\n",
        "mat-vec emission")

    # G. mat-mat emission after pipeline + split_k are final
    sub1(
        "    const uint32_t split_k = ggml_vk_guess_split_k(ctx, ne01, ne11, ne10, disable_split_k, pipeline);\n",
        "    const uint32_t split_k = ggml_vk_guess_split_k(ctx, ne01, ne11, ne10, disable_split_k, pipeline);\n"
        "    // #262 H5: the matrix-path pipeline selection and split-K decision are final here.\n"
        "    ggml_vk_i262_emit_output_route(ctx, dst, src0, src1, \"mat-mat\", pipeline, quantize_y, split_k);\n",
        "mat-mat emission", count=1)
    return src

def main() -> int:
    if len(sys.argv) != 3:
        sys.exit("usage: issue262_h5_edit.py <in.cpp> <out.cpp>")
    src = open(sys.argv[1], encoding="utf-8").read()
    if "ggml_vk_i262_next_route_id" in src:
        sys.exit("H5 edits already present (double apply)")
    out = edit(src)
    open(sys.argv[2], "w", encoding="utf-8").write(out)
    import hashlib
    print("h5 source sha256:", hashlib.sha256(out.encode()).hexdigest())
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
