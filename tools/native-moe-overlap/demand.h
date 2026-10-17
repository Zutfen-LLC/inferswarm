#pragma once
// #312 single-request, opt-in, bounded structural router capture. No token IDs/text.
#include <cstddef>
#include <cstdint>
#include <string>
#include <vector>

struct ggml_tensor;
namespace is312 {
using eval_callback = bool (*)(ggml_tensor *, bool, void *);
void set_dedicated_callback(eval_callback callback);
bool dedicated_callback(eval_callback callback);
using read_ids = void (*)(void *, void *, size_t, size_t);
// Callback's computed E-by-T argsort (not its non-computed top-k view).
bool observe_argsort(class capture * cap, const char * name, bool ask, bool i32,
                     size_t experts, size_t tokens, size_t element_stride, size_t token_stride,
                     read_ids read, void * source);
struct identity {
    std::string model_source, model_revision, model_sha256, representation;
    std::string native_source, native_build_sha256, workload_sha256;
    std::string cohort, workload_label, backend, shape_label;
    std::string gguf_name, gguf_file_type, gguf_architecture;
};
struct overlap_cost {
    double dispatch_ms, shared_ms, join_ms;
    uint64_t input_bytes, routing_bytes, result_bytes;
};
struct row {
    std::string phase;
    unsigned step, layer;
    double readback_ms;
    std::vector<std::vector<int32_t>> tokens;
    std::vector<unsigned> token_positions;
    bool has_cost = false;
    overlap_cost cost = {};
};
struct step_info { std::string phase; unsigned step, tokens, token_start; };
class capture {
public:
    capture(identity id, unsigned layers, unsigned experts, unsigned top_k, unsigned capacity,
            size_t max_bytes = 8 * 1024 * 1024);
    void begin(const std::string & phase, unsigned step, unsigned tokens);
    void record(unsigned layer, const int32_t * ids, unsigned stride, unsigned tokens, double readback_ms);
    void record_cost(unsigned layer, overlap_cost cost);
    std::string export_json() const;
    unsigned expert_count() const { return experts_; }
    unsigned top_k() const { return top_k_; }
    unsigned layer_count() const { return layers_; }
    // Supported CLI only: one contiguous sequence, logits=null, embeddings=false.
    // Pinned qwen4exp prunes to the last output row before its final FFN.
    unsigned expected_tokens(unsigned layer) const { return layer + 1 == layers_ ? 1 : tokens_; }
    void fail(std::string message) { error_ = std::move(message); }
    const std::string & error() const { return error_; }
private:
    identity id_;
    unsigned layers_, experts_, top_k_, capacity_, tokens_ = 0, token_start_ = 0;
    size_t max_bytes_, retained_bytes_ = 0;
    unsigned step_ = 0, steps_ = 0, observed_ = 0, dropped_ = 0;
    std::string phase_, error_;
    std::vector<bool> seen_;
    std::vector<step_info> step_meta_;
    std::vector<row> rows_;
};
capture * active();
void set_active(capture * cap);
} // namespace is312
