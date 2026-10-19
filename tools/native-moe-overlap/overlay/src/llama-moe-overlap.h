#pragma once

#include <cstdint>
#include <memory>
#include <string>
#include "llama-hot-experts.h"

// Experimental model-local configuration. Captured at model creation, never
// changed underneath a reusable graph. No planner/production Q8 contract.
struct llama_moe_overlap_config {
    std::shared_ptr<llama_hot_spec> hot_spec;
    int layer = -1;
    bool overlap = false;
    std::string capture_path; // optional bounded input/output comparison artifact
    // Constructor-only layer microbenchmark cut. No environment/serving toggle.
    // Both arms bind identical captured/synthetic routing, never activations.
    const llama_hot_routing * benchmark_routing = nullptr;
    // #346 batched break-even sweep: same constructor-only contract, T tokens.
    // Batches apply to tokens available together (prefill or independent
    // requests); dependent decode steps of one sequence stay one token each.
    const llama_hot_routing_batch * benchmark_routing_batch = nullptr;
    bool benchmark_stages = false; // retain executed T=2 hot-stage outputs only
    static llama_moe_overlap_config from_env(int n_layer);
};

class llama_moe_overlap;

struct llama_moe_overlap_stats {
    uint64_t steps;
    uintptr_t rpc_backend;
    uintptr_t routed_buffer;
    uintptr_t shared_buffer;
    uint64_t input_bytes;
    uint64_t routing_bytes;
    uint64_t result_bytes;
    double dispatch_ms;
    double shared_ms;
    double join_ms;
};

llama_moe_overlap_stats llama_moe_overlap_get_stats(const std::shared_ptr<llama_moe_overlap> & state);
