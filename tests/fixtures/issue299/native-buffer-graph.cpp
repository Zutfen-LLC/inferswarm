// Tiny stock GGML CPU/RPC proof. No observer, model, or kernel modifications.
#include "ggml.h"
#include "ggml-cpu.h"
#include "ggml-rpc.h"
#include "ggml-backend.h"
#include "ggml-alloc.h"
#include <cassert>
#include <cstdio>
#include <cstring>

int main(int argc, char ** argv) {
    assert(argc == 1 || argc == 2);
    constexpr size_t buffer_cap = 1 << 20;
    // Metadata arena and one backend allocation are each <=1 MiB; total <16 MiB.
    const size_t arena = 8 * ggml_tensor_overhead() + ggml_graph_overhead_custom(8, false);
    assert(arena <= buffer_cap);
    ggml_init_params params = {arena, nullptr, true};
    ggml_context * ctx = ggml_init(params);
    assert(ctx);
    ggml_backend_t backend = argc == 2 ? ggml_backend_rpc_init(argv[1], 0) : ggml_backend_cpu_init();
    assert(backend);
    if (argc == 1) {
        assert(ggml_backend_is_cpu(backend));
        ggml_backend_cpu_set_n_threads(backend, 1);
    } else {
        assert(ggml_backend_is_rpc(backend));
    }
    ggml_tensor * a = ggml_new_tensor_1d(ctx, GGML_TYPE_F32, 4);
    ggml_tensor * b = ggml_new_tensor_1d(ctx, GGML_TYPE_F32, 4);
    ggml_tensor * sum = ggml_add(ctx, a, b);
    ggml_set_name(a, "tiny-a");
    ggml_set_name(b, "tiny-b");
    ggml_set_name(sum, "tiny-add");
    ggml_cgraph * graph = ggml_new_graph_custom(ctx, 8, false);
    ggml_build_forward_expand(graph, sum);
    const size_t needed = ggml_backend_alloc_ctx_tensors_from_buft_size(ctx, ggml_backend_get_default_buffer_type(backend));
    assert(needed > 0 && needed <= buffer_cap);
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
    ggml_backend_tensor_get(a, readback, 0, sizeof(readback));
    assert(std::memcmp(readback, left, sizeof(left)) == 0);
    assert(ggml_backend_graph_compute(backend, graph) == GGML_STATUS_SUCCESS);
    // Real GET/readback observes executed output; client GRAPH send alone isn't proof.
    ggml_backend_tensor_get(sum, readback, 0, sizeof(readback));
    assert(std::memcmp(readback, expected, sizeof(expected)) == 0);
    std::printf("%s stock SET/GET/ADD PASS buffer=%zu arena=%zu values=[%.1f,%.1f,%.1f,%.1f]\n",
                argc == 2 ? "RPC-loopback" : "CPU", allocated, arena,
                readback[0], readback[1], readback[2], readback[3]);
    ggml_backend_buffer_free(buffer);
    ggml_free(ctx);
    ggml_backend_free(backend);
    return 0;
}
