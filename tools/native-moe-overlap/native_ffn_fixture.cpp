// Small CPU/RPC fixture of the exact native FFN method called by qwen4exp.
// It uses native model layer tensors/allocations and the real outer scheduler.
// No checkpoint/model inference, CUDA qualification, or performance claim.
#include "llama-graph.h"
#include "llama-model.h"
#include "llama-cparams.h"
#include "ggml-cpu.h"
#include "ggml-rpc.h"
#include "ggml-alloc.h"
#include "ggml-impl.h"

#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <iostream>
#include <stdexcept>
#include <string>

static constexpr int D = 32, F = 32, S = 32, E = 8, K = 3;

struct fixture {
    ggml_backend_t cpu = nullptr;
    ggml_backend_t rpc = nullptr;
    ggml_backend_sched_t sched = nullptr;
    ggml_context * local = nullptr;
    ggml_context * remote = nullptr;
    ggml_backend_buffer_t local_weights = nullptr;
    ggml_backend_buffer_t remote_weights = nullptr;
    llama_layer layer;

    ~fixture() {
        ggml_backend_sched_free(sched);
        ggml_backend_buffer_free(remote_weights);
        ggml_backend_buffer_free(local_weights);
        ggml_free(remote);
        ggml_free(local);
        ggml_backend_free(rpc);
        ggml_backend_free(cpu);
    }

    void setup(const std::string & endpoint, bool merged, bool q8, bool wrong_placement) {
        cpu = ggml_backend_cpu_init();
        ggml_backend_cpu_set_n_threads(cpu, 2);
        rpc = ggml_backend_rpc_init(endpoint.c_str(), 0);
        if (!rpc) {
            throw std::runtime_error("RPC backend unavailable");
        }
        ggml_backend_t backends[] = {rpc, cpu};
        sched = ggml_backend_sched_new(backends, nullptr, 2, 8192, false, false);
        local = ggml_init({ggml_tensor_overhead() * 32, nullptr, true});
        remote = ggml_init({ggml_tensor_overhead() * 32, nullptr, true});
        layer.ffn_gate_inp = ggml_new_tensor_2d(local, GGML_TYPE_F32, D, E);
        layer.ffn_gate_inp_shexp = ggml_new_tensor_2d(local, GGML_TYPE_F32, D, 1);
        layer.ffn_gate_shexp = ggml_new_tensor_2d(local, GGML_TYPE_F32, D, S);
        layer.ffn_up_shexp = ggml_new_tensor_2d(local, GGML_TYPE_F32, D, S);
        layer.ffn_down_shexp = ggml_new_tensor_2d(local, GGML_TYPE_F32, S, D);
        auto * banks = wrong_placement ? local : remote;
        auto type = q8 ? GGML_TYPE_Q8_0 : GGML_TYPE_F32;
        if (merged) {
            layer.ffn_gate_up_exps = ggml_new_tensor_3d(banks, type, D, 2 * F, E);
        } else {
            layer.ffn_gate_exps = ggml_new_tensor_3d(banks, type, D, F, E);
            layer.ffn_up_exps = ggml_new_tensor_3d(banks, type, D, F, E);
        }
        layer.ffn_down_exps = ggml_new_tensor_3d(banks, type, F, D, E);
        local_weights = ggml_backend_alloc_ctx_tensors(local, cpu);
        if (!wrong_placement) {
            remote_weights = ggml_backend_alloc_ctx_tensors(remote, rpc);
        }
        ggml_backend_buffer_set_usage(local_weights, GGML_BACKEND_BUFFER_USAGE_WEIGHTS);
        if (remote_weights) {
            ggml_backend_buffer_set_usage(remote_weights, GGML_BACKEND_BUFFER_USAGE_WEIGHTS);
        }
        int salt = 0;
        for (auto * context : {local, remote}) {
            for (auto * t = ggml_get_first_tensor(context); t; t = ggml_get_next_tensor(context, t)) {
                std::vector<float> values(ggml_nelements(t));
                for (size_t i = 0; i < values.size(); ++i) {
                    values[i] = 0.12f * std::sin(float(i * 7 + (++salt)) * 0.013f);
                }
                if (t->type == GGML_TYPE_F32) {
                    ggml_backend_tensor_set(t, values.data(), 0, ggml_nbytes(t));
                } else {
                    std::vector<uint8_t> encoded(ggml_nbytes(t));
                    const auto bytes = ggml_quantize_chunk(t->type, values.data(), encoded.data(), 0,
                                                           ggml_nrows(t), t->ne[0], nullptr);
                    if (bytes != encoded.size()) {
                        throw std::runtime_error("fixture quantization size mismatch");
                    }
                    ggml_backend_tensor_set(t, encoded.data(), 0, encoded.size());
                }
            }
        }
    }

    void run(int tokens, bool missing_shared, bool missing_selected, int shape_index) {
        llm_graph_result result(8192);
        llama_adapter_loras loras;
        llm_graph_params params = {};
        params.arch = LLM_ARCH_QWEN4EXP;
        params.hparams.n_layer_all = 2;
        params.hparams.n_embd = D;
        params.hparams.n_expert = E;
        params.hparams.n_expert_used_arr.fill(K);
        params.hparams.n_head_arr.fill(1);
        params.hparams.n_head_kv_arr.fill(1);
        params.hparams.n_embd_head_k_full = D;
        params.hparams.n_embd_head_v_full = D;
        params.hparams.n_rot_full = D;
        params.hparams.expert_weights_scale = 1.0f;
        params.cparams.n_threads = 2;
        params.cparams.n_threads_batch = 2;
        params.ubatch.n_tokens = tokens;
        params.sched = sched;
        params.backend_cpu = cpu;
        params.loras = &loras;
        params.res = &result;
        params.cb = [](const llama_ubatch &, ggml_tensor * tensor, const char * name, int il) {
            ggml_format_name(tensor, "%s-%d", name, il);
        };
        llm_graph_context builder(params);
        auto config = llama_moe_overlap_config::from_env(2);
        auto selected_layer = layer;
        if (missing_shared || missing_selected) {
            selected_layer.ffn_up_shexp = nullptr;
        }
        auto * input = ggml_new_tensor_2d(result.get_ctx(), GGML_TYPE_F32, D, tokens);
        ggml_set_input(input);
        // Exercise activation/intermediate memory owned by the outer allocator
        // before and after the fork/join. The selected input is not a user leaf.
        auto * activation = ggml_scale(result.get_ctx(), input, 0.75f);
        auto * ffn = builder.build_qwen4exp_ffn(activation, selected_layer, 0, config);
        auto * output = ggml_add(result.get_ctx(), ffn, activation);
        ggml_set_output(output);
        ggml_build_forward_expand(result.get_gf(), output);
        if (!ggml_backend_sched_alloc_graph(sched, result.get_gf())) {
            throw std::runtime_error("outer allocation failed");
        }
        for (int step = 0; step < 6; ++step) {
            std::vector<float> values(D * tokens), output_values(D * tokens);
            for (size_t i = 0; i < values.size(); ++i) {
                values[i] = std::sin(float(i + 31 * step) * 0.07f) * (0.3f + step * 0.1f);
            }
            ggml_backend_tensor_set(input, values.data(), 0, values.size() * sizeof(float));
            if (ggml_backend_sched_graph_compute(sched, result.get_gf()) != GGML_STATUS_SUCCESS) {
                throw std::runtime_error("outer computation failed");
            }
            ggml_backend_tensor_get(output, output_values.data(), 0, output_values.size() * sizeof(float));
            std::cout << "{\"shape\":" << shape_index << ",\"tokens\":" << tokens << ",\"step\":" << step
                      << ",\"owners\":" << result.moe_overlap.size();
            if (!result.moe_overlap.empty()) {
                const auto stats = llama_moe_overlap_get_stats(result.moe_overlap[0]);
                std::cout << ",\"native_steps\":" << stats.steps << ",\"rpc_backend\":" << stats.rpc_backend
                          << ",\"routed_buffer\":" << stats.routed_buffer << ",\"shared_buffer\":" << stats.shared_buffer
                          << ",\"input_bytes\":" << stats.input_bytes << ",\"routing_bytes\":" << stats.routing_bytes
                          << ",\"result_bytes\":" << stats.result_bytes;
            }
            std::cout << ",\"output\":[";
            for (size_t i = 0; i < output_values.size(); ++i) {
                if (i) std::cout << ',';
                std::cout.precision(9);
                std::cout << output_values[i];
            }
            std::cout << "]}" << std::endl;
        }
        ggml_backend_sched_synchronize(sched);
        ggml_backend_sched_reset(sched);
        // reset releases the owner before metadata is reused. A shape change
        // constructs new arenas, while the model weights and connection stay.
        result.reset();
        if (!result.moe_overlap.empty()) {
            throw std::runtime_error("owner survived graph reset");
        }
    }
};

int main(int argc, char ** argv) {
    if (argc < 2) {
        std::fprintf(stderr, "native-ffn-fixture ENDPOINT [merged|q8|wrong-placement|missing-shared|missing-selected]\n");
        return 2;
    }
    const std::string control = argc > 2 ? argv[2] : "";
    try {
        fixture f;
        f.setup(argv[1], control == "merged", control == "q8", control == "wrong-placement");
        for (int i = 0; i < 3; ++i) {
            f.run(i == 1 ? 7 : 1, control == "missing-shared", control == "missing-selected", i);
        }
        std::cout << "{\"released\":true}" << std::endl;
    } catch (const std::exception & e) {
        std::fprintf(stderr, "fixture refused: %s\n", e.what());
        return 2;
    }
    return 0;
}
