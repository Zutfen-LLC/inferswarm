#include "demand.h"
#include <algorithm>
#include <atomic>
#include <chrono>
#include <cmath>
#include <iomanip>
#include <sstream>
#include <stdexcept>

namespace is312 {
namespace {
// Single-request CLI only; the private CPU op may execute on a pool thread.
std::atomic<capture *> current{nullptr};
std::atomic<eval_callback> dedicated{nullptr};
std::string quote(const std::string & s) {
    std::ostringstream out;
    out << '"';
    for (unsigned char c : s) {
        if (c == '"' || c == '\\') out << '\\' << c;
        else if (c < 32) out << "\\u" << std::hex << std::setw(4) << std::setfill('0') << int(c) << std::dec;
        else out << c;
    }
    out << '"';
    return out.str();
}
} // namespace
capture * active() { return current.load(std::memory_order_acquire); }
void set_active(capture * cap) { current.store(cap, std::memory_order_release); }
void set_dedicated_callback(eval_callback cb) { dedicated.store(cb, std::memory_order_release); }
bool dedicated_callback(eval_callback cb) {
    return active() && cb && cb == dedicated.load(std::memory_order_acquire);
}
bool observe_argsort(capture * cap, const char * name, bool ask, bool i32,
                     size_t experts, size_t tokens, size_t element_stride, size_t token_stride,
                     read_ids read, void * source) {
    if (!cap || !name || std::string(name).compare(0, 16, "ffn_moe_argsort-") != 0) return !ask;
    if (ask) return true;
    try {
        const std::string suffix = std::string(name).substr(16);
        if (suffix.empty() || suffix.find_first_not_of("0123456789") != std::string::npos)
            throw std::runtime_error("invalid router layer name");
        const unsigned long layer = std::stoul(suffix);
        if (layer >= cap->layer_count() || !i32 || experts != cap->expert_count() ||
            tokens != cap->expected_tokens((unsigned)layer) || element_stride != sizeof(int32_t) ||
            token_stride != experts * sizeof(int32_t) || !read || !source ||
            tokens * cap->top_k() * sizeof(int32_t) > 8 * 1024 * 1024)
            throw std::runtime_error("router argsort shape mismatch");
        std::vector<int32_t> selected(tokens * cap->top_k());
        const auto start = std::chrono::steady_clock::now();
        for (size_t t = 0; t < tokens; ++t)
            read(source, selected.data() + t * cap->top_k(), t * token_stride,
                 cap->top_k() * sizeof(int32_t));
        const double ms = std::chrono::duration<double, std::milli>(
            std::chrono::steady_clock::now() - start).count();
        cap->record((unsigned)layer, selected.data(), cap->top_k(), (unsigned)tokens, ms);
    } catch (const std::exception & e) {
        cap->fail(e.what());
        return false;
    }
    return true;
}

capture::capture(identity id, unsigned layers, unsigned experts, unsigned top_k, unsigned capacity, size_t max_bytes)
    : id_(std::move(id)), layers_(layers), experts_(experts), top_k_(top_k), capacity_(capacity),
      max_bytes_(max_bytes), seen_(layers) {
    if (!layers || layers > 256 || !experts || experts > 4096 || !top_k || top_k > experts ||
        !capacity || capacity > 100000 || !max_bytes || max_bytes > 8 * 1024 * 1024)
        throw std::invalid_argument("invalid capture bounds");
}
void capture::begin(const std::string & phase, unsigned step, unsigned tokens) {
    if ((phase != "prefill" && phase != "decode") || tokens == 0 || tokens > 4096 ||
        steps_ >= 257 || (!steps_ && phase != "prefill") || (steps_ && phase != "decode") ||
        (steps_ && step != step_ + 1) || (!steps_ && step != 0) || (phase == "decode" && tokens != 1)) {
        throw std::invalid_argument("invalid explicit phase/step/token count");
    }
    phase_ = phase;
    step_ = step;
    token_start_ += tokens_;
    tokens_ = tokens;
    ++steps_;
    step_meta_.push_back({phase, step, tokens, token_start_});
    std::fill(seen_.begin(), seen_.end(), false);
}
void capture::record(unsigned layer, const int32_t * ids, unsigned stride, unsigned tokens, double readback_ms) {
    const auto start = std::chrono::steady_clock::now();
    if (!steps_ || layer >= layers_ || seen_[layer] || tokens != expected_tokens(layer) || !ids || stride < top_k_ ||
        stride > experts_ || !std::isfinite(readback_ms) || readback_ms < 0) {
        throw std::invalid_argument("invalid router observation");
    }
    seen_[layer] = true;
    ++observed_;
    // Charge vector/row overhead as well as ID bytes, before allocating any
    // token vectors. Drops are whole observations, never partial token groups.
    const size_t charge = 256 + size_t(tokens) * (32 + sizeof(unsigned) + size_t(top_k_) * sizeof(int32_t));
    if (rows_.size() >= capacity_ || charge > max_bytes_ - retained_bytes_) { ++dropped_; return; }
    row r{phase_, step_, layer, readback_ms, {}, {}};
    for (unsigned t = 0; t < tokens; ++t) {
        std::vector<int32_t> selected;
        for (unsigned k = 0; k < top_k_; ++k) {
            const int32_t expert = ids[t * stride + k];
            if (expert < 0 || unsigned(expert) >= experts_ ||
                std::find(selected.begin(), selected.end(), expert) != selected.end()) {
                throw std::invalid_argument("invalid selected expert ID");
            }
            selected.push_back(expert);
        }
        r.tokens.push_back(std::move(selected));
        r.token_positions.push_back(token_start_ + (layer + 1 == layers_ ? tokens_ - 1 : t));
    }
    rows_.push_back(std::move(r));
    retained_bytes_ += charge;
    rows_.back().readback_ms += std::chrono::duration<double, std::milli>(
        std::chrono::steady_clock::now() - start).count();
}
void capture::record_cost(unsigned layer, overlap_cost cost) {
    if (!steps_ || layer >= layers_ || !seen_[layer] ||
        !std::isfinite(cost.dispatch_ms) || cost.dispatch_ms < 0 ||
        !std::isfinite(cost.shared_ms) || cost.shared_ms < 0 ||
        !std::isfinite(cost.join_ms) || cost.join_ms < 0)
        throw std::invalid_argument("invalid overlap cost observation");
    auto it = std::find_if(rows_.begin(), rows_.end(), [&](const row & r) {
        return r.step == step_ && r.layer == layer;
    });
    if (it == rows_.end()) return; // ID row already dropped; no orphan cost.
    if (it->has_cost) throw std::invalid_argument("duplicate overlap cost");
    constexpr size_t cost_charge = 1024; // six bounded metric envelopes
    if (cost_charge > max_bytes_ - retained_bytes_) {
        retained_bytes_ -= 256 + it->tokens.size() * (32 + sizeof(unsigned) + size_t(top_k_) * sizeof(int32_t));
        rows_.erase(it);
        ++dropped_;
        return;
    }
    it->has_cost = true;
    it->cost = cost;
    retained_bytes_ += cost_charge;
}
std::string capture::export_json() const {
    std::ostringstream out;
    out << "{\"schema\":\"native-demand/1\",\"identity\":{";
    const std::pair<const char *, const std::string *> fields[] = {
        {"model_source", &id_.model_source}, {"model_revision", &id_.model_revision},
        {"model_sha256", &id_.model_sha256}, {"representation", &id_.representation},
        {"native_source", &id_.native_source}, {"native_build_sha256", &id_.native_build_sha256},
        {"workload_sha256", &id_.workload_sha256}, {"cohort", &id_.cohort},
        {"workload_label", &id_.workload_label}, {"backend", &id_.backend},
        {"shape_label", &id_.shape_label},
    };
    for (size_t i = 0; i < sizeof(fields)/sizeof(fields[0]); ++i) {
        if (i) out << ',';
        out << quote(fields[i].first) << ':' << quote(*fields[i].second);
    }
    out << "},\"identity_provenance\":{\"model_source\":\"operator_attested\","
           "\"model_revision\":\"operator_attested\",\"model_sha256\":\"operator_attested\","
           "\"representation\":\"operator_attested\",\"native_source\":\"source_pinned\","
           "\"native_build_sha256\":\"operator_attested\",\"workload_sha256\":\"operator_attested\"},"
           "\"observed_gguf\":{\"name\":" << quote(id_.gguf_name)
        << ",\"file_type\":" << quote(id_.gguf_file_type)
        << ",\"architecture\":" << quote(id_.gguf_architecture)
        << "},\"layers\":" << layers_ << ",\"expert_count\":" << experts_
        << ",\"top_k\":" << top_k_ << ",\"capacity_rows\":" << capacity_
        << ",\"token_coverage\":\"qwen4exp-last-output\""
        << ",\"steps\":" << steps_ << ",\"observed_rows\":" << observed_
        << ",\"dropped_rows\":" << dropped_ << ",\"step_meta\":[";
    for (size_t i = 0; i < step_meta_.size(); ++i) {
        if (i) out << ',';
        const auto & s = step_meta_[i];
        out << "{\"phase\":" << quote(s.phase) << ",\"step\":" << s.step
            << ",\"tokens\":" << s.tokens << ",\"token_start\":" << s.token_start << '}';
    }
    out << "],\"rows\":[";
    for (size_t i = 0; i < rows_.size(); ++i) {
        if (i) out << ',';
        const auto & r = rows_[i];
        out << "{\"phase\":" << quote(r.phase) << ",\"step\":" << r.step
            << ",\"layer\":" << r.layer << ",\"readback_ms\":" << std::setprecision(9)
            << r.readback_ms << ",\"tokens\":[";
        for (size_t t = 0; t < r.tokens.size(); ++t) {
            if (t) out << ',';
            out << '[';
            for (size_t k = 0; k < r.tokens[t].size(); ++k) {
                if (k) out << ',';
                out << r.tokens[t][k];
            }
            out << ']';
        }
        out << "],\"token_positions\":[";
        for (size_t t = 0; t < r.token_positions.size(); ++t) {
            if (t) out << ',';
            out << r.token_positions[t];
        }
        out << ']';
        if (r.has_cost) {
            out << ",\"cost_observations\":[";
            const auto metric = [&](const char * name, double value, const char * unit, const char * meaning, bool first) {
                if (!first) out << ',';
                out << "{\"evidence_class\":\"measured\",\"metric\":{\"name\":" << quote(name)
                    << ",\"value\":" << std::setprecision(9) << value << ",\"unit\":" << quote(unit)
                    << ",\"statistic\":\"observation\"},\"scope\":" << quote(meaning) << '}';
            };
            metric("dispatch_ms", r.cost.dispatch_ms, "ms", "client dispatch incl router and enqueue; overlaps later stages", true);
            metric("shared_ms", r.cost.shared_ms, "ms", "client CPU shared stage; overlaps remote work", false);
            metric("join_ms", r.cost.join_ms, "ms", "RPC client result wait/copy; not device kernel time", false);
            metric("input_bytes", double(r.cost.input_bytes), "byte", "logical input payload; not wire bytes", false);
            metric("routing_bytes", double(r.cost.routing_bytes), "byte", "logical routing payload; not wire bytes", false);
            metric("result_bytes", double(r.cost.result_bytes), "byte", "logical result payload; not wire bytes", false);
            out << ']';
        }
        out << '}';
    }
    out << "]}";
    return out.str();
}
} // namespace is312
