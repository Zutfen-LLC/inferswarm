// #312 opt-in, single-request native capture. No prompt or token IDs exported.
#include "demand.h"
#include "llama.h"
#include "ggml.h"
#include "ggml-backend.h"
#include "ggml-rpc.h"
#include <algorithm>
#include <chrono>
#include <cctype>
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <map>
#include <memory>
#include <stdexcept>
#include <string>
#include <vector>

namespace {
using clock_type = std::chrono::steady_clock;
unsigned number(const std::string & text, unsigned limit) {
    if (text.empty() || text.find_first_not_of("0123456789") != std::string::npos) throw std::invalid_argument("invalid positive integer");
    unsigned long long n = std::stoull(text);
    if (!n || n > limit) throw std::invalid_argument("number outside capture bound");
    return unsigned(n);
}
std::string metadata(llama_model * model, const std::string & key) {
    char buffer[128] = {};
    if (llama_model_meta_val_str(model, key.c_str(), buffer, sizeof(buffer)) <= 0 || !buffer[0])
        throw std::runtime_error("missing model metadata: " + key);
    return buffer;
}
std::string optional_metadata(llama_model * model, const std::string & key) {
    char buffer[128] = {};
    return llama_model_meta_val_str(model, key.c_str(), buffer, sizeof(buffer)) > 0 ? buffer : "";
}
std::string required(const std::map<std::string, std::string> & args, const std::string & key) {
    const auto it = args.find(key);
    if (it == args.end() || it->second.empty()) throw std::invalid_argument("missing " + key);
    return it->second;
}
void digest(const std::string & s) {
    if (s.size() != 64 || !std::all_of(s.begin(), s.end(), [](char c) {
        return (c >= '0' && c <= '9') || (c >= 'a' && c <= 'f'); }))
        throw std::invalid_argument("digest must be lowercase SHA-256");
}
struct observer {
    is312::capture & cap;
    static bool callback(ggml_tensor * t, bool ask, void * opaque) {
        auto & self = *static_cast<observer *>(opaque);
        // This is the computed argsort, not ffn_moe_topk's non-compute view.
        return is312::observe_argsort(&self.cap, t->name, ask, t->type == GGML_TYPE_I32,
            t->ne[0] < 0 ? 0 : (size_t)t->ne[0], t->ne[1] < 0 ? 0 : (size_t)t->ne[1],
            t->nb[0], t->nb[1],
            [](void * source, void * dst, size_t offset, size_t bytes) {
                ggml_backend_tensor_get(static_cast<ggml_tensor *>(source), dst, offset, bytes);
            }, t);
    }
};
} // namespace

int main(int argc, char ** argv) {
    try {
        // Every argument is a flag/value pair; there is no implicit profile.
        std::map<std::string, std::string> args;
        for (int i = 1; i < argc; i += 2) {
            if (i + 1 >= argc || std::string(argv[i]).compare(0, 2, "--") != 0 ||
                !args.emplace(argv[i], argv[i + 1]).second) throw std::invalid_argument("invalid flag/value pair");
        }
        const std::string model_path = required(args, "--model");
        const std::string output = required(args, "--output");
        const unsigned max_rows = number(required(args, "--max-rows"), 100000);
        const unsigned decode_steps = number(required(args, "--decode-steps"), 256);
        for (const auto * key : {"--model-sha256", "--native-build-sha256", "--workload-sha256"}) digest(required(args, key));
        if (required(args, "--cohort") != "profiling") throw std::invalid_argument("cohort must be profiling, not evaluation");
        if (std::getenv("IS309_CAPTURE")) throw std::invalid_argument("IS309_CAPTURE retains unrelated tensors: refuse");
        const bool rpc = args.count("--rpc-endpoint") != 0;
        if (rpc != (args.count("--rpc-tensors-regex") != 0))
            throw std::invalid_argument("RPC endpoint and bank override regex must be paired");
        if (std::getenv("IS309_MOE") && !rpc)
            throw std::invalid_argument("selected overlap requires explicit existing RPC bank overrides");
        const std::string prompt_file = required(args, "--prompt-file");
        std::ifstream input(prompt_file, std::ios::binary);
        if (!input) throw std::runtime_error("prompt file unreadable");
        std::string prompt(65537, '\0');
        input.read(&prompt[0], prompt.size());
        const auto prompt_bytes = input.gcount();
        if (prompt_bytes == 0 || prompt_bytes > 65536) throw std::runtime_error("prompt byte bound exceeded");
        prompt.resize((size_t)prompt_bytes);
        auto params = llama_model_default_params();
        if (args.count("--gpu-layers")) params.n_gpu_layers = (int)number(args.at("--gpu-layers"), 512);
        ggml_backend_dev_t rpc_devices[2] = {nullptr, nullptr};
        llama_model_tensor_buft_override overrides[2] = {};
        std::string regex;
        if (rpc) {
            const std::string endpoint = required(args, "--rpc-endpoint");
            regex = required(args, "--rpc-tensors-regex");
            auto * reg = ggml_backend_rpc_add_server(endpoint.c_str());
            if (!reg || !(rpc_devices[0] = ggml_backend_reg_dev_get(reg, 0)))
                throw std::runtime_error("native RPC device unavailable");
            params.devices = rpc_devices;
            overrides[0] = {regex.c_str(), ggml_backend_rpc_buffer_type(endpoint.c_str(), 0)};
            params.tensor_buft_overrides = overrides;
        }
        auto model = std::unique_ptr<llama_model, decltype(&llama_model_free)>(
            llama_model_load_from_file(model_path.c_str(), params), llama_model_free);
        if (!model) throw std::runtime_error("model load failed");
        const auto architecture = metadata(model.get(), "general.architecture");
        if (architecture != "qwen4exp")
            throw std::runtime_error("only qwen4exp native routing is supported");
        const auto file_type = metadata(model.get(), "general.file_type");
        if (file_type != required(args, "--file-type")) throw std::runtime_error("model file_type mismatch");
        const unsigned experts = number(metadata(model.get(), "qwen4exp.expert_count"), 4096);
        const unsigned top_k = number(metadata(model.get(), "qwen4exp.expert_used_count"), experts);
        const unsigned layers = (unsigned)llama_model_n_layer(model.get());
        is312::identity id{required(args, "--model-source"), required(args, "--model-revision"),
            required(args, "--model-sha256"), required(args, "--representation"),
            "b29c606e28a01b1bc8c1351026a0fa6e616bf6c4", required(args, "--native-build-sha256"),
            required(args, "--workload-sha256"), "profiling", required(args, "--workload-label"),
            required(args, "--backend"), "single-request;file_type=" + file_type,
            optional_metadata(model.get(), "general.name"), file_type, architecture};
        is312::capture cap(id, layers, experts, top_k, max_rows);
        observer obs{cap};
        const auto * vocab = llama_model_get_vocab(model.get());
        std::vector<llama_token> tokens(4096);
        const int n = llama_tokenize(vocab, prompt.data(), (int)prompt.size(), tokens.data(), (int)tokens.size(), true, false);
        if (n <= 0 || n > 4096) throw std::runtime_error("prompt token bound exceeded");
        tokens.resize(n);
        auto cp = llama_context_default_params();
        // Capture maps exactly this single-sequence, last-output-only batch
        // contract; do not request extra logits/routed work for profiling.
        cp.embeddings = false;
        cp.n_ctx = (uint32_t)(n + decode_steps + 16);
        cp.n_batch = cp.n_ubatch = (uint32_t)n;
        cp.cb_eval = observer::callback;
        cp.cb_eval_user_data = &obs;
        is312::set_dedicated_callback(observer::callback);
        // Context construction reserves graphs, including the private overlap
        // FFN. Admit this dedicated callback before those builds, but do not
        // label any token step until the real prefill below.
        is312::set_active(&cap);
        auto ctx = std::unique_ptr<llama_context, decltype(&llama_free)>(llama_init_from_model(model.get(), cp), llama_free);
        if (!ctx) throw std::runtime_error("context init failed");
        cap.begin("prefill", 0, (unsigned)n);
        if (llama_decode(ctx.get(), llama_batch_get_one(tokens.data(), n)) != 0 || !cap.error().empty())
            throw std::runtime_error("prefill failed: " + cap.error());
        for (unsigned step = 1; step <= decode_steps; ++step) {
            const float * logits = llama_get_logits_ith(ctx.get(), -1);
            if (!logits) throw std::runtime_error("missing logits");
            const int vocab_size = llama_vocab_n_tokens(vocab);
            const llama_token next = (llama_token)(std::max_element(logits, logits + vocab_size) - logits);
            cap.begin("decode", step, 1);
            llama_token token = next;
            if (llama_decode(ctx.get(), llama_batch_get_one(&token, 1)) != 0 || !cap.error().empty())
                throw std::runtime_error("decode failed: " + cap.error());
        }
        is312::set_active(nullptr);
        // Only publish a complete, bounded single-request export; no overwrite.
        const std::string exported = cap.export_json();
        if (exported.size() > 16 * 1024 * 1024) throw std::runtime_error("export byte bound exceeded");
        FILE * file = std::fopen(output.c_str(), "wx");
        if (!file) throw std::runtime_error("output must be a fresh path");
        const bool ok = std::fwrite(exported.data(), exported.size(), 1, file) == 1;
        if (std::fclose(file) != 0 || !ok) throw std::runtime_error("export write failed");
    } catch (const std::exception & e) {
        is312::set_active(nullptr);
        std::fprintf(stderr, "native demand: %s\n", e.what());
        return 2;
    }
    return 0;
}
