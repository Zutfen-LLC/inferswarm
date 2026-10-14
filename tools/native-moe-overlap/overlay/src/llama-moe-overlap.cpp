#include "llama-moe-overlap.h"
#include "llama-graph.h"
#include "llama-model.h"
#include "llama-cparams.h"
#include "ggml-alloc.h"
#include "ggml-cpu.h"
#include "ggml-rpc.h"
#include "ggml-impl.h"

#include <algorithm>
#include <chrono>
#include <cstdio>
#include <cstring>
#include <stdexcept>
#include <string>
#include <unordered_map>

llama_moe_overlap_config llama_moe_overlap_config::from_env(int n_layer) {
    llama_moe_overlap_config cfg;
    const char * value = std::getenv("IS309_MOE");
    if (!value) {
        return cfg;
    }
    const std::string text(value);
    const auto colon = text.find(':');
    if (colon == std::string::npos || colon == 0 ||
        text.find_first_not_of("0123456789", 0) != colon) {
        throw std::runtime_error("IS309_MOE requires <layer>:serial or <layer>:overlap");
    }
    const auto mode = text.substr(colon + 1);
    if (mode != "serial" && mode != "overlap") {
        throw std::runtime_error("unsupported IS309_MOE schedule");
    }
    const auto layer = std::stoul(text.substr(0, colon));
    if (layer >= (unsigned) n_layer) {
        throw std::runtime_error("IS309_MOE layer is outside the model");
    }
    cfg.layer = (int) layer;
    cfg.overlap = mode == "overlap";
    const char * capture = std::getenv("IS309_CAPTURE");
    if (capture) {
        if (!*capture) {
            throw std::runtime_error("IS309_CAPTURE requires a nonempty artifact path");
        }
        cfg.capture_path = capture;
    }
    return cfg;
}

namespace {
using clock_type = std::chrono::steady_clock;
double ms(clock_type::time_point start, clock_type::time_point end) {
    return std::chrono::duration<double, std::milli>(end - start).count();
}
void require(bool ok, const char * message) {
    if (!ok) {
        throw std::runtime_error(std::string("IS309_MOE: ") + message);
    }
}
void compute(ggml_backend_t backend, ggml_cgraph * graph) {
    if (ggml_backend_graph_compute(backend, graph) != GGML_STATUS_SUCCESS) {
        // The custom CPU op cannot return a backend error. Fail the entire
        // process, as the pinned RPC dispatcher does on transport failure.
        GGML_ABORT("IS309_MOE native branch failed");
    }
}
}

// One owner per reusable graph shape, retained by llm_graph_result. None of
// these arenas belongs to the outer scheduler's gallocr. Its waits remain
// unchanged. Weight leaves borrow the already-loaded model buffers.
class llama_moe_overlap {
public:
    llama_moe_overlap_config cfg;
    ggml_context * ctx = nullptr;
    ggml_backend_t cpu = nullptr; // separate CPU executor: no recursive pool use
    ggml_backend_t rpc = nullptr; // borrowed context backend/dispatcher
    ggml_gallocr_t router_alloc = nullptr;
    ggml_gallocr_t shared_alloc = nullptr;
    ggml_gallocr_t routed_alloc = nullptr;
    ggml_cgraph * router = nullptr;
    ggml_cgraph * shared = nullptr;
    ggml_cgraph * routed = nullptr;
    ggml_tensor * input = nullptr;
    ggml_tensor * remote_input = nullptr;
    ggml_tensor * ids = nullptr;
    ggml_tensor * remote_ids = nullptr;
    ggml_tensor * weights = nullptr;
    ggml_tensor * remote_weights = nullptr;
    ggml_tensor * shared_out = nullptr;
    ggml_tensor * routed_out = nullptr;
    std::vector<float> result;
    llama_moe_overlap_stats stats = {};

    ~llama_moe_overlap() {
        // Every successful custom-op call joins before returning. There is
        // no outstanding branch on reset, shape change, or context teardown.
        ggml_gallocr_free(routed_alloc);
        ggml_gallocr_free(shared_alloc);
        ggml_gallocr_free(router_alloc);
        ggml_backend_free(cpu);
        ggml_free(ctx);
    }

    void allocate(ggml_cgraph * graph, ggml_backend_t backend, ggml_gallocr_t & alloc) {
        for (int i = 0; i < graph->n_leafs; ++i) {
            auto * leaf = graph->leafs[i];
            if (leaf->buffer) {
                require(ggml_backend_supports_buft(backend, ggml_backend_buffer_get_type(leaf->buffer)),
                        "branch weight placement does not match its backend; use native tensor overrides");
            }
        }
        for (int i = 0; i < graph->n_nodes; ++i) {
            require(ggml_backend_supports_op(backend, graph->nodes[i]), "unsupported native branch operation");
        }
        alloc = ggml_gallocr_new(ggml_backend_get_default_buffer_type(backend));
        require(alloc && ggml_gallocr_alloc_graph(alloc, graph), "branch allocation failed");
    }

    static void execute(ggml_tensor * dst, const ggml_tensor * src, int ith, int nth, void * opaque) {
        GGML_UNUSED(nth);
        // The pin passes the pool's nth and invokes every worker, even for a
        // one-task custom op. Other workers wait at the graph's node barrier.
        if (ith != 0) {
            return;
        }
        auto & s = *static_cast<llama_moe_overlap *>(opaque);
        const auto start = clock_type::now();
        // This input snapshot remains owned until the response-bearing join.
        // The outer scheduler may reuse src only after this op returns.
        ggml_backend_tensor_set(s.input, src->data, 0, ggml_nbytes(s.input));
        compute(s.cpu, s.router);
        ggml_backend_tensor_set_async(s.rpc, s.remote_input, s.input->data, 0, ggml_nbytes(s.input));
        ggml_backend_tensor_set_async(s.rpc, s.remote_ids, s.ids->data, 0, ggml_nbytes(s.ids));
        ggml_backend_tensor_set_async(s.rpc, s.remote_weights, s.weights->data, 0, ggml_nbytes(s.weights));
        if (ggml_backend_graph_compute_async(s.rpc, s.routed) != GGML_STATUS_SUCCESS) {
            GGML_ABORT("IS309_MOE routed dispatch failed");
        }
        const auto dispatched = clock_type::now();
        double join_ms = 0;
        const auto join = [&] {
            const auto before = clock_type::now();
            // synchronize alone only drains the RPC client queue. GET_TENSOR
            // waits for the remote GRAPH_COMPUTE and owns result until copied.
            ggml_backend_tensor_get(s.routed_out, s.result.data(), 0, ggml_nbytes(s.routed_out));
            ggml_backend_synchronize(s.rpc);
            join_ms += ms(before, clock_type::now());
        };
        if (!s.cfg.overlap) {
            join();
        }
        const auto shared_start = clock_type::now();
        compute(s.cpu, s.shared);
        const auto shared_done = clock_type::now();
        if (s.cfg.overlap) {
            join();
        }
        // Same F32 add and operand order in both schedules. No expert or
        // shared work is skipped. The shared gate is part of shared_out.
        const auto * local = static_cast<const float *>(s.shared_out->data);
        auto * output = static_cast<float *>(dst->data);
        for (size_t i = 0; i < s.result.size(); ++i) {
            output[i] = s.result[i] + local[i];
        }
        ++s.stats.steps;
        s.stats.rpc_backend = reinterpret_cast<uintptr_t>(s.rpc);
        s.stats.routed_buffer = reinterpret_cast<uintptr_t>(s.routed_out->buffer);
        s.stats.shared_buffer = reinterpret_cast<uintptr_t>(s.shared_out->buffer);
        s.stats.input_bytes = ggml_nbytes(s.input);
        s.stats.routing_bytes = ggml_nbytes(s.ids) + ggml_nbytes(s.weights);
        s.stats.result_bytes = ggml_nbytes(s.routed_out);
        s.stats.dispatch_ms = ms(start, dispatched);
        s.stats.shared_ms = ms(shared_start, shared_done);
        s.stats.join_ms = join_ms;
        if (!s.cfg.capture_path.empty()) {
            // I309/1, little-endian x86 fixture/Hermes scope: four uint32s,
            // uint64 step, followed by input and result F32 arrays. The
            // separately supervised run bounds total file size and duration.
            const uint32_t header[] = {0x39303349, (uint32_t)s.cfg.layer,
                                       (uint32_t)s.input->ne[0], (uint32_t)s.input->ne[1]};
            FILE * file = std::fopen(s.cfg.capture_path.c_str(), "ab");
            if (!file) {
                GGML_ABORT("IS309_MOE capture open failed");
            }
            const bool ok = std::fwrite(header, sizeof(header), 1, file) == 1 &&
                            std::fwrite(&s.stats.steps, sizeof(s.stats.steps), 1, file) == 1 &&
                            std::fwrite(s.input->data, ggml_nbytes(s.input), 1, file) == 1 &&
                            std::fwrite(output, ggml_nbytes(dst), 1, file) == 1;
            const int closed = std::fclose(file);
            if (!ok || closed != 0) {
                GGML_ABORT("IS309_MOE capture write failed");
            }
        }
        std::fprintf(stderr, "IS309_MOE layer=%d schedule=%s step=%llu dispatch_ms=%.6f shared_ms=%.6f join_ms=%.6f input_bytes=%llu routing_bytes=%llu result_bytes=%llu\n",
                     s.cfg.layer, s.cfg.overlap ? "overlap" : "serial",
                     (unsigned long long) s.stats.steps, s.stats.dispatch_ms, s.stats.shared_ms, s.stats.join_ms,
                     (unsigned long long) s.stats.input_bytes, (unsigned long long) s.stats.routing_bytes,
                     (unsigned long long) s.stats.result_bytes);
    }
};

llama_moe_overlap_stats llama_moe_overlap_get_stats(const std::shared_ptr<llama_moe_overlap> & state) {
    return state->stats;
}

// Clone only routed descendants. The three activation/routing cuts become
// private remote inputs. Already-resident weight leaves are shared by pointer;
// they are never copied by this allocator or uploaded during a step.
static ggml_tensor * clone_routed(ggml_context * ctx, ggml_tensor * tensor,
                                 std::unordered_map<ggml_tensor *, ggml_tensor *> & copies) {
    const auto found = copies.find(tensor);
    if (found != copies.end()) {
        return found->second;
    }
    if (tensor->op == GGML_OP_NONE) {
        require(tensor->buffer != nullptr, "unallocated routed weight");
        return tensor;
    }
    auto * copy = ggml_dup_tensor(ctx, tensor);
    copies[tensor] = copy;
    copy->op = tensor->op;
    std::memcpy(copy->op_params, tensor->op_params, sizeof(copy->op_params));
    std::memcpy(copy->nb, tensor->nb, sizeof(copy->nb));
    ggml_set_name(copy, tensor->name);
    for (int i = 0; i < GGML_MAX_SRC; ++i) {
        if (tensor->src[i]) {
            copy->src[i] = clone_routed(ctx, tensor->src[i], copies);
        }
    }
    if (tensor->view_src) {
        copy->view_src = clone_routed(ctx, tensor->view_src, copies);
        copy->view_offs = tensor->view_offs;
    }
    return copy;
}

ggml_tensor * llm_graph_context::build_qwen4exp_ffn(ggml_tensor * cur, const llama_layer & layer, int il,
                                                 const llama_moe_overlap_config & cfg) {
    if (cfg.layer != il) {
        return build_qwen4exp_ffn_native(cur, layer, il);
    }
    require(arch == LLM_ARCH_QWEN4EXP, "only qwen4exp is supported");
    require(cur->type == GGML_TYPE_F32 && ggml_is_contiguous(cur) && ggml_n_dims(cur) <= 2,
            "selected activation must be contiguous F32 [embedding,tokens]");
    require(loras && loras->empty(), "LoRA is not supported by this experiment");
    require(cparams.cb_eval == nullptr, "intermediate eval callbacks are not supported by this experiment");
    require(layer.ffn_up_shexp && layer.ffn_gate_shexp && layer.ffn_down_shexp && layer.ffn_gate_inp_shexp,
            "selected layer lacks the gated shared branch");
    auto state = std::make_shared<llama_moe_overlap>();
    state->cfg = cfg;
    for (int i = 0; i < ggml_backend_sched_get_n_backends(sched); ++i) {
        auto * backend = ggml_backend_sched_get_backend(sched, i);
        if (!ggml_backend_is_rpc(backend)) {
            continue;
        }
        auto * bank = layer.ffn_gate_up_exps ? layer.ffn_gate_up_exps : layer.ffn_up_exps;
        if (bank && bank->buffer && ggml_backend_supports_buft(backend, ggml_backend_buffer_get_type(bank->buffer))) {
            require(state->rpc == nullptr, "ambiguous resident RPC backend");
            state->rpc = backend;
        }
    }
    require(state->rpc, "selected expert banks must already be resident on one context RPC backend");
    state->cpu = ggml_backend_cpu_init();
    require(state->cpu, "CPU executor initialization failed");
    ggml_backend_cpu_set_n_threads(state->cpu, std::max(1, n_tokens == 1 ? cparams.n_threads : cparams.n_threads_batch));
    const size_t max_nodes = 1024 + 4 * n_expert;
    state->ctx = ggml_init({ggml_tensor_overhead() * max_nodes * 3 + ggml_graph_overhead_custom(max_nodes, false) * 4,
                            nullptr, true});
    require(state->ctx, "metadata allocation failed");
    state->input = ggml_dup_tensor(state->ctx, cur);
    ggml_set_input(state->input);
    // INPUT alone only reserves an early allocation. Router gallocr can reuse
    // it after its last local read, but shared and RPC still need this snapshot.
    ggml_set_output(state->input);

    // Use the existing model builders, including routing normalization, expert
    // scales, native SwiGLU, shared projection and sigmoid gate. Redirect only
    // this build's metadata and callbacks; restore even on construction failure.
    auto * outer_ctx = ctx0;
    auto * outer_graph = gf;
    ggml_tensor * combined;
    ctx0 = state->ctx;
    gf = ggml_new_graph_custom(ctx0, max_nodes, false);
    moe_overlap_building = true;
    try {
        combined = build_qwen4exp_ffn_native(state->input, layer, il);
    } catch (...) {
        ctx0 = outer_ctx;
        gf = outer_graph;
        moe_overlap_building = false;
        throw;
    }
    ctx0 = outer_ctx;
    gf = outer_graph;
    moe_overlap_building = false;
    state->shared_out = combined->src[1];
    auto * original_moe = combined->src[0];
    auto * weighted = ggml_get_tensor(state->ctx, ("ffn_moe_weighted-" + std::to_string(il)).c_str());
    require(weighted, "pinned routing cut is missing");
    state->weights = weighted->src[1];
    auto * down = weighted->src[0];
    // With per-expert output scales the down matmul is inside a multiply.
    if (down->op == GGML_OP_MUL) {
        down = down->src[0];
    }
    require(down->op == GGML_OP_MUL_MAT_ID, "pinned expert cut is missing");
    auto * original_ids = down->src[2];
    // Native top-k is a strided view of argsort (stride E, width K).
    // Pack the routing boundary before sending its K-by-T private copy.
    state->ids = ggml_cont(state->ctx, original_ids);
    ggml_set_output(state->weights);
    ggml_set_output(state->ids);
    ggml_set_output(state->shared_out);
    state->router = ggml_new_graph_custom(state->ctx, max_nodes, false);
    ggml_build_forward_expand(state->router, state->weights);
    ggml_build_forward_expand(state->router, state->ids);
    state->shared = ggml_new_graph_custom(state->ctx, max_nodes, false);
    ggml_build_forward_expand(state->shared, state->shared_out);
    state->remote_input = ggml_dup_tensor(state->ctx, state->input);
    state->remote_ids = ggml_dup_tensor(state->ctx, state->ids);
    state->remote_weights = ggml_dup_tensor(state->ctx, state->weights);
    ggml_set_input(state->remote_input);
    ggml_set_input(state->remote_ids);
    ggml_set_input(state->remote_weights);
    std::unordered_map<ggml_tensor *, ggml_tensor *> copies = {
        {state->input, state->remote_input}, {original_ids, state->remote_ids}, {state->weights, state->remote_weights}
    };
    state->routed_out = clone_routed(state->ctx, original_moe, copies);
    // The native aggregate can be a strided view when K>1; make the readback
    // contiguous without changing accumulation order or precision.
    state->routed_out = ggml_cont(state->ctx, state->routed_out);
    ggml_set_output(state->routed_out);
    state->routed = ggml_new_graph_custom(state->ctx, max_nodes, false);
    ggml_build_forward_expand(state->routed, state->routed_out);
    state->allocate(state->router, state->cpu, state->router_alloc);
    state->allocate(state->shared, state->cpu, state->shared_alloc);
    state->allocate(state->routed, state->rpc, state->routed_alloc);
    require(ggml_is_contiguous(state->shared_out), "shared output is not contiguous");
    std::fprintf(stderr, "IS309_SETUP layer=%d tokens=%lld rpc=%s router_bytes=%zu shared_bytes=%zu routed_bytes=%zu weights=borrowed-resident\n",
                 il, (long long)cur->ne[1], ggml_backend_name(state->rpc),
                 ggml_gallocr_get_buffer_size(state->router_alloc, 0),
                 ggml_gallocr_get_buffer_size(state->shared_alloc, 0),
                 ggml_gallocr_get_buffer_size(state->routed_alloc, 0));
    state->result.resize(ggml_nelements(cur));
    auto * output = ggml_map_custom1(ctx0, cur, llama_moe_overlap::execute, 1, state.get());
    res->moe_overlap.push_back(std::move(state));
    cb(output, "ffn_out", il);
    ggml_backend_sched_set_tensor_backend(sched, output, backend_cpu);
    return output;
}

ggml_tensor * llm_graph_context::build_qwen4exp_ffn_native(ggml_tensor * cur, const llama_layer & layer, const int il) {
    GGML_ASSERT(layer.ffn_gate_inp != nullptr);

    ggml_tensor * moe_out =
        build_moe_ffn(cur,
            layer.ffn_gate_inp,
            layer.ffn_up_exps,
            layer.ffn_gate_exps,
            layer.ffn_down_exps,
            nullptr,
            n_expert, n_expert_used,
            LLM_FFN_SILU, true,
            hparams.expert_weights_scale,
            LLAMA_EXPERT_GATING_FUNC_TYPE_SOFTMAX, il,
            nullptr, layer.ffn_gate_up_exps,
            layer.ffn_up_exps_s,
            layer.ffn_gate_exps_s,
            layer.ffn_down_exps_s);
    cb(moe_out, "ffn_moe_out", il);

    // shared experts, as in the Qwen3Next reference
    if (layer.ffn_up_shexp != nullptr) {
        ggml_tensor * ffn_shexp =
            build_ffn(cur,
                layer.ffn_up_shexp, NULL, layer.ffn_up_shexp_s,
                layer.ffn_gate_shexp, NULL, layer.ffn_gate_shexp_s,
                layer.ffn_down_shexp, NULL, layer.ffn_down_shexp_s,
                NULL,
                LLM_FFN_SILU, LLM_FFN_PAR, il);
        cb(ffn_shexp, "ffn_shexp", il);

        // shared expert has its own sigmoided gate (ffn_gate_inp_shexp, one value per token)
        ggml_tensor * shared_gate = build_lora_mm(layer.ffn_gate_inp_shexp, cur);
        cb(shared_gate, "shared_expert_gate", il);

        shared_gate = ggml_sigmoid(ctx0, shared_gate);
        cb(shared_gate, "shared_expert_gate_sigmoid", il);

        ffn_shexp = ggml_mul(ctx0, ffn_shexp, shared_gate);
        cb(ffn_shexp, "ffn_shexp_gated", il);

        cur = ggml_add(ctx0, moe_out, ffn_shexp);
        cb(cur, "ffn_out", il);
    } else {
        cur = moe_out;
    }

    return cur;
}
