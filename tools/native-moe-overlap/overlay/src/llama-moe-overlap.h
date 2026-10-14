#pragma once

#include <cstdint>
#include <memory>
#include <string>

// Experimental model-local configuration. Captured at model creation, never
// changed underneath a reusable graph. No planner/production Q8 contract.
struct llama_moe_overlap_config {
    int layer = -1;
    bool overlap = false;
    std::string capture_path; // optional bounded input/output comparison artifact
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
