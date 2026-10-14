// Compact real pinned loader route, without model construction or inference.
#include "llama-model-loader.h"
#include "ggml-alloc.h"
#include "ggml-rpc.h"
#include <fstream>
#include <sstream>
#include <cstdio>

int main(int argc, char ** argv) {
    if (argc < 5) { return 1; }
    std::vector<std::string> splits;
    for (int i = 3; i < argc; ++i) { splits.emplace_back(argv[i]); }
    llama_model_loader loader(nullptr, nullptr, nullptr, argv[2], splits, nullptr,
        LLAMA_LOAD_MODE_NONE, false, false, false, nullptr, nullptr);
    ggml_context_ptr ctx{ggml_init({1048576, nullptr, true})};
    std::ifstream assigned(getenv("IS311_ASSIGNED"));
    std::string line;
    while (std::getline(assigned, line)) {
        std::istringstream row(line);
        std::string name; row >> name;
        const auto * meta = loader.require_tensor_meta(name);
        auto * tensor = ggml_dup_tensor(ctx.get(), meta);
        ggml_set_name(tensor, name.c_str());
        if (getenv("IS311_FIXTURE_DUPLICATE")) {
            auto * duplicate = ggml_dup_tensor(ctx.get(), meta);
            ggml_set_name(duplicate, name.c_str());
        }
    }
    ggml_backend_buffer_ptr buffer{ggml_backend_alloc_ctx_tensors_from_buft(ctx.get(), ggml_backend_rpc_buffer_type(argv[1], 0))};
    if (!buffer) { return 2; }
    ggml_backend_buffer_set_usage(buffer.get(), GGML_BACKEND_BUFFER_USAGE_WEIGHTS);
    loader.init_mappings(false);
    llama_buf_map buffers{{0, buffer.get()}};
    if (!loader.load_all_data(ctx.get(), buffers, nullptr, nullptr, nullptr)) { return 3; }
    if (getenv("IS311_FIXTURE_PARTIAL")) {
        auto * tensor = ggml_get_first_tensor(ctx.get());
        std::vector<uint8_t> data(ggml_nbytes(tensor));
        ggml_backend_tensor_set(tensor, data.data(), 1, data.size()-1);
    }
    for (auto * t = ggml_get_first_tensor(ctx.get()); t; t = ggml_get_next_tensor(ctx.get(), t)) {
        const auto & weight = loader.require_weight(t->name);
        const auto bytes = ggml_nbytes(t);
        std::vector<uint8_t> expected(bytes), actual(bytes);
        const void * data = loader.load_data_range(weight, 0, bytes, expected.data());
        ggml_backend_tensor_get(t, actual.data(), 0, bytes);
        if (memcmp(data, actual.data(), bytes) != 0) { return 4; }
        printf("{\"tensor\":\"%s\",\"offset\":0,\"bytes\":%zu,\"readback\":true}\n", t->name, bytes);
    }
    return 0;
}
