// CPU loopback proof using the real patched dispatcher and unchanged v7 worker.
#include "factorial-rpc.h"
#include "ggml-rpc.h"
#include "ggml-alloc.h"
#include "ggml-impl.h"
#include <algorithm>
#include <array>
#include <cstring>
#include <iostream>
#include <stdexcept>
#include <vector>

static void require(bool ok, const char * why) {
    if (!ok) throw std::runtime_error(why);
}

int main(int argc, char ** argv) {
    try {
        require(argc == 3, "usage: factorial-rpc-fixture HOST:PORT serial|pipeline");
        const bool pipeline = std::strcmp(argv[2], "pipeline") == 0;
        require(pipeline || std::strcmp(argv[2], "serial") == 0, "unknown mode");
        auto backend = ggml_backend_rpc_init(argv[1], 0);
        require(backend, "RPC init failed");
        auto context = ggml_init({ggml_tensor_overhead()*16 + ggml_graph_overhead_custom(16, false), nullptr, true});
        require(context, "context allocation failed");
        constexpr size_t N = 16384;
        ggml_tensor * inputs[3];
        for (int i = 0; i < 3; ++i) {
            inputs[i] = ggml_new_tensor_1d(context, GGML_TYPE_F32, N);
            ggml_format_name(inputs[i], "factorial.mutable.%d", i);
            ggml_set_input(inputs[i]);
        }
        auto output = ggml_add(context, ggml_add(context, inputs[0], inputs[1]), inputs[2]);
        ggml_set_output(output);
        auto graph = ggml_new_graph_custom(context, 16, false);
        ggml_build_forward_expand(graph, output);
        graph->uid = 884466;
        auto buffer = ggml_backend_alloc_ctx_tensors(context, backend);
        require(buffer, "RPC allocation failed");
        std::array<std::vector<float>, 3> source;
        std::vector<float> result(N), expected(N);
        is_factorial_rpc_tensor descriptors[3];
        std::cout << "{\"schema\":\"factorial-rpc-fixture/1\",\"mode\":\"" << argv[2] << "\",\"steps\":[";
        for (int step = 0; step < 2; ++step) {
            for (int i = 0; i < 3; ++i) {
                source[i].resize(N);
                for (size_t j = 0; j < N; ++j) source[i][j] = float((i+1)*32 + (j%128) + step) / 8;
                descriptors[i] = {inputs[i], source[i].data(), 0, N*sizeof(float)};
            }
            for (size_t j = 0; j < N; ++j) expected[j] = (source[0][j]+source[1][j])+source[2][j];
            // Earlier queued work must be fully drained before observation.
            ggml_backend_tensor_memset(inputs[0], 0, 0, N*sizeof(float));
            is_factorial_rpc_stats stats;
            require(is_factorial_rpc_begin(backend, &stats), "observation begin failed");
            require(!is_factorial_rpc_begin(backend, &stats), "nested observation accepted");
            if (step == 0) {
                ggml_backend_buffer_set_usage(buffer, GGML_BACKEND_BUFFER_USAGE_WEIGHTS);
                require(!is_factorial_rpc_set3(backend, descriptors, pipeline, 5000), "immutable group accepted");
                ggml_backend_buffer_set_usage(buffer, GGML_BACKEND_BUFFER_USAGE_ANY);
                auto old = descriptors[1].tensor;
                descriptors[1].tensor = inputs[0];
                require(!is_factorial_rpc_set3(backend, descriptors, pipeline, 5000), "duplicate tensor accepted");
                descriptors[1].tensor = old;
            }
            require(is_factorial_rpc_set3(backend, descriptors, pipeline, 5000), "SET3 validation failed");
            // Borrowed mutable data and headers are no longer needed after all
            // admissions. Changing caller storage must not change remote values.
            for (auto & values : source) std::fill(values.begin(), values.end(), -1024.f);
            require(ggml_backend_graph_compute(backend, graph) == GGML_STATUS_SUCCESS, "graph failed");
            ggml_backend_synchronize(backend); // Same join-before-GET ordering.
            ggml_backend_tensor_get(output, result.data(), 0, N*sizeof(float));
            require(is_factorial_rpc_end(backend), "observation end failed");
            require(result == expected, "remote values/lifetimes/output differ");
            require(stats.set_commands == 3 && stats.set_acks == 3 && stats.graph_commands == 1 &&
                    stats.get_commands == 1 && stats.commands == 5 && stats.failed == 0,
                    "command/ACK counters differ");
            require(stats.tx_payload_bytes == 3*N*sizeof(float), "payload counter differs");
            require(stats.graph_uid == graph->uid && stats.graph_recompute == (uint64_t)step,
                    "actual graph UID/recompute differs");
            require(stats.rx_wire_bytes == 27+8+N*sizeof(float), "response byte counter differs");
            if (!pipeline) for (int i = 1; i < 3; ++i)
                require(stats.sets[i-1].ack_end_ns <= stats.sets[i].write_begin_ns, "serial ACK order differs");
            for (int i = 0; i < 3; ++i)
                require(stats.sets[i].hash_end_ns <= stats.sets[i].write_begin_ns &&
                        stats.sets[i].write_end_ns <= stats.sets[i].ack_end_ns, "SET timeline differs");
            if (step) std::cout << ',';
            std::cout << "{\"commands\":" << stats.commands << ",\"acks\":" << stats.set_acks
                << ",\"tx_wire_bytes\":" << stats.tx_wire_bytes << ",\"rx_wire_bytes\":" << stats.rx_wire_bytes
                << ",\"recompute\":" << stats.graph_recompute << ",\"passed\":true}";
        }
        std::cout << "],\"passed\":true}" << std::endl;
        ggml_backend_buffer_free(buffer);
        ggml_free(context);
        ggml_backend_free(backend);
        return 0;
    } catch (const std::exception & error) {
        std::cerr << error.what() << std::endl;
        return 1;
    }
}
