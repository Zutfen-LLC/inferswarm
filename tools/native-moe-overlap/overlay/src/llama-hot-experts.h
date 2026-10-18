#pragma once
#include <cstdint>
#include <memory>
struct llama_context;
// 0 unknown, 1 prefill, 2 decode, 3 mixed; setter fences previous execution.
void llama_hot_set_phase(llama_context * ctx, int phase);
struct llama_moe_overlap_config;
struct llama_hot_spec;
class llama_hot_experts;
class llama_hot_graph;
struct ggml_context;
struct ggml_tensor;
struct llama_hot_routing {
    ggml_tensor * ids = nullptr;
    ggml_tensor * weights = nullptr;
};
// Bind source routing cuts before allocation. Arithmetic and slot order stay native.
void llama_hot_bind_routing(ggml_context * ctx, ggml_tensor * combined, int layer,
                            const llama_hot_routing & routing);
llama_moe_overlap_config llama_hot_config(int n_layer);
struct llama_hot_stats {
    double dispatch_ms=0, cold_ms=0, shared_ms=0, join_ms=0, layer_ms=0, fast_ms=0;
    uint64_t input_bytes=0, routing_bytes=0, result_bytes=0;
    int phase = 0;
    uint64_t steps = 0;
    unsigned hot = 0, cold = 0;
    uintptr_t compact_owner = 0;
};
llama_hot_stats llama_hot_get_stats(const std::shared_ptr<llama_hot_graph> & graph);
