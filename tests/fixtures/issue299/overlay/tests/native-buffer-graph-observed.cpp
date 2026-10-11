// Tiny #301 observed fixture: same stock CPU/RPC proof as native-buffer-graph,
// with the observation overlay enabled. Emits genuine static and dynamic
// inferswarm-native-observation/2 envelopes from real execution.
#include "is301_observer.h"
#include "ggml.h"
#include "ggml-cpu.h"
#include "ggml-rpc.h"
#include "ggml-backend.h"
#include "ggml-alloc.h"
#include <cassert>
#include <cstdio>
#include <cstring>

static void emit(const char * phase, const char * kind, bool terminal,
                 bool fence, const char * out_path) {
    std::string envelope = is301::envelope(
        phase, "fixture-tiny", std::string(64, '0'), "inv-fixture",
        std::string("gen-") + std::to_string(is301::now_ns()), kind, terminal, fence);
    std::FILE * out = std::fopen(out_path, "w");
    assert(out);
    std::fwrite(envelope.data(), 1, envelope.size(), out);
    std::fclose(out);
}

int main(int argc, char ** argv) {
    assert(argc == 3); // argv[1]: cpu|rpc  argv[2]: output directory
    const bool rpc = std::strcmp(argv[1], "rpc") == 0;
    is301::facts().add("process", std::string("{") +
        is301::kv_str("argv0", argv[0]) + "," +
        is301::kv_num("pid", is301::pid()) + "}");
    is301::facts().add("build", std::string("{") +
        is301::kv_str("protocol", "inferswarm-native-observation/2") + "}");
    // static snapshot BEFORE the instrumented allocation: empty zero interval.
    emit("static", "snapshot", true, true,
         (std::string(argv[2]) + "/static-capture.json").c_str());
    is301::reset();
    is301::facts().add("process", std::string("{") +
        is301::kv_str("argv0", argv[0]) + "," +
        is301::kv_num("pid", is301::pid()) + "}");
    is301::facts().add("build", std::string("{") +
        is301::kv_str("protocol", "inferswarm-native-observation/2") + "}");
    constexpr size_t buffer_cap = 1 << 20;
    const size_t arena = 8 * ggml_tensor_overhead() + ggml_graph_overhead_custom(8, false);
    assert(arena <= buffer_cap);
    ggml_init_params params = {arena, nullptr, true};
    ggml_context * ctx = ggml_init(params);
    assert(ctx);
    const char * endpoint = std::getenv("IS301_RPC_ENDPOINT");
    ggml_backend_t backend = rpc && endpoint
        ? ggml_backend_rpc_init(endpoint, 0) : ggml_backend_cpu_init();
    assert(backend);
    if (!rpc || !endpoint) { assert(ggml_backend_is_cpu(backend));
        ggml_backend_cpu_set_n_threads(backend, 1); }
    else { assert(ggml_backend_is_rpc(backend)); }
    is301::stream().record(rpc ? "fixture_rpc_loopback" : "fixture_cpu_init");
    ggml_tensor * a = ggml_new_tensor_1d(ctx, GGML_TYPE_F32, 4);
    ggml_tensor * b = ggml_new_tensor_1d(ctx, GGML_TYPE_F32, 4);
    ggml_tensor * sum = ggml_add(ctx, a, b);
    ggml_set_name(a, "tiny-a"); ggml_set_name(b, "tiny-b"); ggml_set_name(sum, "tiny-add");
    ggml_cgraph * graph = ggml_new_graph_custom(ctx, 8, false);
    ggml_build_forward_expand(graph, sum);
    const size_t needed = ggml_backend_alloc_ctx_tensors_from_buft_size(
        ctx, ggml_backend_get_default_buffer_type(backend));
    assert(needed > 0 && needed <= buffer_cap);
    is301::stream().record("fixture_alloc");
    ggml_backend_buffer_t buffer = ggml_backend_alloc_ctx_tensors(ctx, backend);
    assert(buffer);
    const size_t allocated = ggml_backend_buffer_get_size(buffer);
    assert(allocated <= buffer_cap && allocated + arena <= (16 << 20));
    const float left[4] = {1, 2, -3, 4};
    const float right[4] = {5, -2, 7, 0.5f};
    const float expected[4] = {6, 0, 4, 4.5f};
    float readback[4] = {};
    ggml_backend_tensor_set(a, left, 0, sizeof(left));
    ggml_backend_tensor_set(b, right, 0, sizeof(right));
    is301::stream().record("fixture_set");
    ggml_backend_tensor_get(a, readback, 0, sizeof(readback));
    assert(std::memcmp(readback, left, sizeof(left)) == 0);
    is301::stream().record("fixture_get");
    // Mirror llama-server's real ordering: acceleration backend(s) first, the
    // CPU backend LAST (ggml_backend_sched_new asserts a CPU final backend).
    ggml_backend_t cpu_backend = ggml_backend_cpu_init();
    assert(cpu_backend);
    ggml_backend_cpu_set_n_threads(cpu_backend, 1);
    ggml_backend_t backends[2];
    int n_backends = 1;
    if (rpc) { backends[0] = backend; backends[1] = cpu_backend; n_backends = 2; }
    else { backends[0] = cpu_backend; ggml_backend_free(backend); backend = cpu_backend; }
    ggml_backend_sched_t sched = ggml_backend_sched_new(backends, nullptr, n_backends, 8, false, false);
    assert(sched);
    // Mirror llama-server startup: reserve the scheduler's graph allocation
    // before async compute (multi-backend graphs cannot auto-reallocate).
    assert(ggml_backend_sched_reserve(sched, graph));
    assert(ggml_backend_sched_graph_compute_async(sched, graph) == GGML_STATUS_SUCCESS);
    ggml_backend_sched_synchronize(sched);
    is301::stream().record("fixture_graph");
    ggml_backend_tensor_get(sum, readback, 0, sizeof(readback));
    assert(std::memcmp(readback, expected, sizeof(expected)) == 0);
    is301::stream().record("fixture_output_readback");
    ggml_backend_sched_free(sched);
    if (rpc) { ggml_backend_free(cpu_backend); }
    ggml_backend_buffer_free(buffer);
    ggml_free(ctx);
    ggml_backend_free(backend);
    emit("dynamic", "whole", true, false,
         (std::string(argv[2]) + "/dynamic-capture.json").c_str());
    is301::export_capture("dynamic", "whole", true, false,
                          rpc ? "fixture-rpc" : "fixture-cpu");
    std::printf("IS301 %s fixture PASS pid=%lld\n", rpc ? "RPC-loopback" : "CPU", is301::pid());
    return 0;
}
