#!/usr/bin/env python3
"""One-shot #301 overlay derivation from the authenticated pinned base.

Applies exact anchored text replacements to pinned source bytes and writes
transformed files, the unified patch, and the transformed-file manifest under
tests/fixtures/issue299/. Every anchor must occur exactly once at the pin;
results are retained fixtures recording the overlay, not silent build inputs.
"""
import difflib
import hashlib
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
BASE = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(
    '/home/zutfen/.hermes/cache/scratch/is299/llama-src')
FIX = REPO / 'tests/fixtures/issue299'
PIN = 'b29c606e28a01b1bc8c1351026a0fa6e616bf6c4'
TREE = '950999fe62b7fe55f44ab5b7394e3c8542f37f12'

# (path, unique anchor, replacement) — strictly observation-only guards.
SEAMS = [
    ('ggml/src/ggml-alloc.c',
     '    return ggml_backend_alloc_ctx_tensors_from_buft_impl(ctx, buft, &nbytes_total, /*no_alloc =*/ false);\n}',
     '    ggml_backend_buffer_t is301_buf = ggml_backend_alloc_ctx_tensors_from_buft_impl(ctx, buft, &nbytes_total, /*no_alloc =*/ false);\n'
     '    if (is301_buf != NULL && is301_is_enabled()) {\n'
     '        is301_record_event("alloc_ctx_tensors");\n'
     '        is301_fact_alloc((long long) ggml_backend_buffer_get_size(is301_buf), ggml_backend_buft_name(buft));\n'

     '    }\n'
     '    return is301_buf;\n}'),
    ('ggml/src/ggml-backend.cpp',
     'enum ggml_status ggml_backend_graph_compute(ggml_backend_t backend, struct ggml_cgraph * cgraph) {\n'
     '    enum ggml_status err = ggml_backend_graph_compute_async(backend, cgraph);\n'
     '    ggml_backend_synchronize(backend);\n'
     '    return err;\n}',
     'enum ggml_status ggml_backend_graph_compute(ggml_backend_t backend, struct ggml_cgraph * cgraph) {\n'
     '    enum ggml_status err = ggml_backend_graph_compute_async(backend, cgraph);\n'
     '    ggml_backend_synchronize(backend);\n'
     '    if (is301::enabled()) {\n'
     '        is301::stream().record("graph_compute");\n'
     '        is301::facts().append("graphs", std::string("{") +\n'
     '            is301::kv_num("graph_id", (long long) (uintptr_t) cgraph) + "," +\n'
     '            is301::kv_num("nodes",\n'
     '            (long long) (cgraph ? cgraph->n_nodes : 0)) + "," + is301::kv_num("status",\n'
     '            (long long) err) + "," +\n'
     '            is301::kv_str("ubatch_lineage", "unknown") + "}");\n'
     '    }\n'
     '    return err;\n}'),
    ('ggml/src/ggml-backend.cpp',
     '    buf->iface.set_tensor(buf, tensor, data, offset, size);\n}',
     '    buf->iface.set_tensor(buf, tensor, data, offset, size);\n'
     '    if (is301::enabled()) {\n'
     '        is301::stream().record("tensor_set");\n'
     '        is301::facts().append("transfers", std::string("{") +\n'
     '            is301::kv_num("bytes", (long long) size) + "," +\n'
     '            is301::kv_num("offset", (long long) offset) + "," +\n'
     '            is301::kv_str("op", "set") + "," +\n'
     '            is301::kv_shape("shape", tensor->ne) + "," +\n'
     '            is301::kv_str("tensor", tensor->name) + "," +\n'
     '            is301::kv_str("type", ggml_type_name(tensor->type)) + "," +\n'
     '            is301::kv_num("view_offset", (long long) tensor->view_offs) + "}");\n'
     '    }\n}'),
    ('ggml/src/ggml-backend.cpp',
     '    buf->iface.get_tensor(buf, tensor, data, offset, size);\n}',
     '    buf->iface.get_tensor(buf, tensor, data, offset, size);\n'
     '    if (is301::enabled()) {\n'
     '        is301::stream().record("tensor_get");\n'
     '        is301::facts().append("transfers", std::string("{") +\n'
     '            is301::kv_num("bytes", (long long) size) + "," +\n'
     '            is301::kv_num("offset", (long long) offset) + "," +\n'
     '            is301::kv_str("op", "get") + "," +\n'
     '            is301::kv_shape("shape", tensor->ne) + "," +\n'
     '            is301::kv_str("tensor", tensor->name) + "," +\n'
     '            is301::kv_str("type", ggml_type_name(tensor->type)) + "," +\n'
     '            is301::kv_num("view_offset", (long long) tensor->view_offs) + "}");\n'
     '    }\n}'),
    ('ggml/src/ggml-rpc/ggml-rpc.cpp',
     '    std::shared_ptr<uint8_t> input_ptr(input, std::default_delete<uint8_t[]>());\n'
     '    ctx->dispatcher->send(RPC_CMD_SET_TENSOR, input_ptr, input_size);\n}',
     '    std::shared_ptr<uint8_t> input_ptr(input, std::default_delete<uint8_t[]>());\n'
     '    ctx->dispatcher->send(RPC_CMD_SET_TENSOR, input_ptr, input_size);\n'
     '    if (is301::enabled()) {\n'
     '        is301::stream().record("rpc_set_tensor");\n'
     '        is301::facts().append("transfers", std::string("{") +\n'
     '            is301::kv_num("bytes", (long long) size) + "," +\n'
     '            is301::kv_num("offset", (long long) offset) + "," +\n'
     '            is301::kv_str("op", "rpc_set") + "," +\n'
     '            is301::kv_num("remote_ptr", (long long) ctx->remote_ptr) + "," +\n'
     '            is301::kv_shape("shape", tensor->ne) + "," +\n'
     '            is301::kv_str("tensor", tensor->name) + "," +\n'
     '            is301::kv_str("type", ggml_type_name(tensor->type)) + "," +\n'
     '            is301::kv_num("view_offset", (long long) tensor->view_offs) + "}");\n'
     '    }\n}'),
    ('ggml/src/ggml-rpc/ggml-rpc.cpp',
     '    ctx->dispatcher->send(RPC_CMD_GET_TENSOR, request, sizeof(*request), data, size);\n}',
     '    ctx->dispatcher->send(RPC_CMD_GET_TENSOR, request, sizeof(*request), data, size);\n'
     '    if (is301::enabled()) {\n'
     '        is301::stream().record("rpc_get_tensor");\n'
     '        is301::facts().append("transfers", std::string("{") +\n'
     '            is301::kv_num("bytes", (long long) size) + "," +\n'
     '            is301::kv_num("offset", (long long) offset) + "," +\n'
     '            is301::kv_str("op", "rpc_get") + "," +\n'
     '            is301::kv_num("remote_ptr", (long long) ctx->remote_ptr) + "," +\n'
     '            is301::kv_shape("shape", tensor->ne) + "," +\n'
     '            is301::kv_str("tensor", tensor->name) + "," +\n'
     '            is301::kv_str("type", ggml_type_name(tensor->type)) + "," +\n'
     '            is301::kv_num("view_offset", (long long) tensor->view_offs) + "}");\n'
     '    }\n}'),
    ('ggml/src/ggml-rpc/ggml-rpc.cpp',
     '        printf("Accepted client connection\\n");\n        fflush(stdout);\n',
     '        printf("Accepted client connection\\n");\n        fflush(stdout);\n'
     '        if (is301::enabled()) {\n'
     '            is301::stream().record("rpc_server_client");\n'
     '        }\n'),
    ('ggml/src/ggml-rpc/ggml-rpc.cpp',
     '        switch (cmd) {\n            case RPC_CMD_HELLO: {',
     '        if (is301::enabled()) {\n'
     '            is301::stream().record("rpc_server_command");\n'
     '        }\n'
     '        switch (cmd) {\n            case RPC_CMD_HELLO: {'),
    ('src/llama-model-loader.cpp',
     '    return true;\n}\n\nstd::string llama_model_loader::ftype_name() const {',
     '    if (is301::enabled()) {\n'
     '        is301::stream().record("model_load_all_data");\n'
     '        is301::facts().add("model_load", std::string("{") +\n'
     '            is301::kv_num("n_tensors", (long long) n_tensors) + "," +\n'
     '            is301::kv_num("n_tensors_moved", (long long) n_tensors_moved) + "," +\n'
     '            is301::kv_str("output_custody", "unknown") + "," +\n'
     '            is301::kv_num("size_data", (long long) size_data) + "," +\n'
     '            is301::kv_str("tensor_ranges", "unsupported") + "}");\n'
     '    }\n'
     '    return true;\n}\n\nstd::string llama_model_loader::ftype_name() const {'),
    ('src/llama-kv-cache.cpp',
     '    const char * LLAMA_KV_CACHE_DEBUG = getenv("LLAMA_KV_CACHE_DEBUG");\n'
     '    debug = LLAMA_KV_CACHE_DEBUG ? atoi(LLAMA_KV_CACHE_DEBUG) : 0;\n}',
     '    const char * LLAMA_KV_CACHE_DEBUG = getenv("LLAMA_KV_CACHE_DEBUG");\n'
     '    debug = LLAMA_KV_CACHE_DEBUG ? atoi(LLAMA_KV_CACHE_DEBUG) : 0;\n'
     '    if (is301::enabled()) {\n'
     '        is301::stream().record("kv_cache_constructed");\n'
     '        is301::facts().add("kv_cache", std::string("{") +\n'
     '            is301::kv_num("kv_size", (long long) get_size()) + "," +\n'
     '            is301::kv_num("n_stream", (long long) n_stream) + "," +\n'
     '            is301::kv_str("name", name_tag) + "}");\n'
     '    }\n}'),
    ('tools/server/server-queue.cpp',
     'int server_queue::get_new_id() {\n'
     '    std::unique_lock<std::mutex> lock(mutex_tasks);\n'
     '    int new_id = id++;\n'
     '    return new_id;\n}',
     'int server_queue::get_new_id() {\n'
     '    std::unique_lock<std::mutex> lock(mutex_tasks);\n'
     '    int new_id = id++;\n'
     '    if (is301::enabled()) {\n'
     '        is301::stream().record("server_task_new_id");\n'
     '        is301::facts().append("tasks", std::string("{") +\n'
     '            is301::kv_str("response_id", "unknown") + "," +\n'
     '            is301::kv_num("task_id", (long long) new_id) + "}");\n'
     '    }\n'
     '    return new_id;\n}'),
    ('tools/server/server-queue.cpp',
     '        QUE_DBG("processing task, id = %d\\n", task.id);\n',
     '        QUE_DBG("processing task, id = %d\\n", task.id);\n'
     '        if (is301::enabled()) {\n'
     '            is301::stream().record("server_task_processed");\n'
     '        }\n'),
    ('tools/server/server-queue.cpp',
     'void server_response::send(server_task_result_ptr && result) {\n'
     '    RES_DBG("sending result for task id = %d\\n", result->id);\n',
     'void server_response::send(server_task_result_ptr && result) {\n'
     '    RES_DBG("sending result for task id = %d\\n", result->id);\n'
     '    if (is301::enabled()) {\n'
     '        is301::stream().record("server_response_send");\n'
     '        is301::facts().append("responses", std::string("{") +\n'
     '            is301::kv_num("task_id", (long long) result->id) + "}");\n'
     '    }\n'),
    ('ggml/src/ggml-backend.cpp',
     'enum ggml_status ggml_backend_sched_graph_compute_async(ggml_backend_sched_t sched, struct ggml_cgraph * graph) {\n'
     '    GGML_ASSERT(sched);\n'
     '    if (!sched->is_reset && !sched->is_alloc) {\n'
     '        ggml_backend_sched_reset(sched);\n'
     '    }\n'
     '\n'
     '    if (!sched->is_alloc) {\n'
     '        if (!ggml_backend_sched_alloc_graph(sched, graph)) {\n'
     '            return GGML_STATUS_ALLOC_FAILED;\n'
     '        }\n'
     '    }\n'
     '\n'
     '    return ggml_backend_sched_compute_splits(sched);\n'
     '}',
     'enum ggml_status ggml_backend_sched_graph_compute_async(ggml_backend_sched_t sched, struct ggml_cgraph * graph) {\n'
     '    GGML_ASSERT(sched);\n'
     '    if (!sched->is_reset && !sched->is_alloc) {\n'
     '        ggml_backend_sched_reset(sched);\n'
     '    }\n'
     '\n'
     '    if (!sched->is_alloc) {\n'
     '        if (!ggml_backend_sched_alloc_graph(sched, graph)) {\n'
     '            return GGML_STATUS_ALLOC_FAILED;\n'
     '        }\n'
     '    }\n'
     '\n'
     '    enum ggml_status is301_err = ggml_backend_sched_compute_splits(sched);\n'
     '    if (is301::enabled()) {\n'
     '        is301::stream().record("sched_graph_compute");\n'
     '        is301::facts().append("graphs", std::string("{") +\n'
     '            is301::kv_num("graph_id", (long long) (uintptr_t) graph) + "," +\n'
     '            is301::kv_num("nodes", (long long) (graph ? graph->n_nodes : 0)) + "," +\n'
     '            is301::kv_num("splits", (long long) ggml_backend_sched_get_n_splits(sched)) + "," +\n'
     '            is301::kv_num("status", (long long) is301_err) + "," +\n'
     '            is301::kv_str("ubatch_lineage", "unknown") + "}");\n'
     '    }\n'
     '    return is301_err;\n'
     '}'),
    ('tools/server/server-queue.cpp',
     'void server_queue::terminate() {\n'
     '    std::unique_lock<std::mutex> lock(mutex_tasks);\n'
     '    running = false;\n'
     '    condition_tasks.notify_all();\n'
     '}',
     'void server_queue::terminate() {\n'
     '    {\n'
     '        std::unique_lock<std::mutex> lock(mutex_tasks);\n'
     '        running = false;\n'
     '        condition_tasks.notify_all();\n'
     '    }\n'
     '    is301::export_capture("dynamic", "whole", true, false, "llama-server");\n'
     '}'),
    ('ggml/src/ggml-rpc/ggml-rpc.cpp',
     '        rpc_serve_client(backends, cache_dir, client_socket);\n'
     '        printf("Client connection closed\\n");\n'
     '        fflush(stdout);\n',
     '        rpc_serve_client(backends, cache_dir, client_socket);\n'
     '        printf("Client connection closed\\n");\n'
     '        fflush(stdout);\n'
     '        is301::export_capture("dynamic", "whole", true, false, "ggml-rpc-server");\n'),
]

SHIM_H = '''// C-compatible observation shim for the #301 overlay (C translation units).
// The linked is301_sink.cpp owns the real state and implements these as
// no-ops unless IS301_OBSERVE=1. Observation-only; never changes behavior.
#ifndef IS301_C_SHIM_H
#define IS301_C_SHIM_H
#ifdef __cplusplus
extern "C" {
#endif
int is301_is_enabled(void);
void is301_record_event(const char * name);
void is301_fact_num(const char * key, long long value);
void is301_fact_str(const char * key, const char * value);
void is301_fact_alloc(long long buffer_bytes, const char * backend);
#ifdef __cplusplus
}
#endif
#endif
'''

SINK_CPP = '''// Single owner of the #301 observation state for each executable.
// Implements the C shim over the shared is301 recorder. Observation-only.
#include "is301_observer.h"
#include "is301_c_shim.h"

extern "C" int is301_is_enabled(void) { return is301::enabled() ? 1 : 0; }
extern "C" void is301_record_event(const char * name) {
    if (is301::enabled()) is301::stream().record(name);
}
extern "C" void is301_fact_num(const char * key, long long value) {
    if (is301::enabled()) is301::facts().add(key, std::to_string(value));
}
extern "C" void is301_fact_str(const char * key, const char * value) {
    if (is301::enabled()) is301::facts().add(key, is301::quote(value));
}
extern "C" void is301_fact_alloc(long long buffer_bytes, const char * backend) {
    if (is301::enabled()) is301::facts().append("allocations", std::string("{") +
        is301::kv_str("backend", backend ? backend : "unknown") + "," +
        is301::kv_num("buffer_bytes", buffer_bytes) + "}");
}
'''

FACT_BOUNDS_CPP = '''// Adversarial bounded-facts proof; the real allocation seam exercises the C shim.
#include "is301_observer.h"
#include <cstdio>
#include <cstring>
#include <string>

static void write_capture(const std::string & path, const std::string & body) {
    std::FILE * out = std::fopen(path.c_str(), "wb");
    if (!out) std::abort();
    if (std::fwrite(body.data(), 1, body.size(), out) != body.size()) std::abort();
    if (std::fclose(out) != 0) std::abort();
}

static void add_clean_facts() {
    for (int id = 1; id <= 3; ++id) {
        is301::facts().append("tasks", std::string("{") +
            is301::kv_str("response_id", "unknown") + "," +
            is301::kv_num("task_id", id) + "}");
    }
    for (int id = 1; id <= 2; ++id) {
        is301::facts().append("responses", std::string("{") +
            is301::kv_num("task_id", id) + "}");
    }
    // This mirrors is301_fact_alloc; the C shim path is exercised by the real alloc seam.
    for (int i = 0; i < 2; ++i) {
        is301::facts().append("allocations", std::string("{") +
            is301::kv_str("backend", "CPU") + "," +
            is301::kv_num("buffer_bytes", 4096) + "}");
    }
}

static std::string capture(const char * generation) {
    return is301::envelope("dynamic", "native-fact-bounds", std::string(64, '0'),
        "export", generation, "whole", true, false);
}

int main(int argc, char ** argv) {
    if (argc != 2) return 2;
    const std::string dir(argv[1]);
    is301::stream().record("fixture_fact_bounds");
    add_clean_facts();
    is301::facts().append("oversized", std::string(4097, 'x'));
    write_capture(dir + "/fact-bounds-capture.json", capture("fact-bounds-bad"));
    is301::reset();
    is301::stream().record("fixture_fact_bounds");
    add_clean_facts();
    write_capture(dir + "/fact-bounds-clean.json", capture("fact-bounds-clean"));
    std::puts("IS301 fact-bounds fixture PASS");
    return 0;
}
'''

FIXTURE_CPP = '''// Tiny #301 observed fixture: same stock CPU/RPC proof as native-buffer-graph,
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
    std::printf("IS301 %s fixture PASS pid=%lld\\n", rpc ? "RPC-loopback" : "CPU", is301::pid());
    return 0;
}
'''


def main():
    identity = subprocess.check_output(
        ['git', '-C', str(BASE), 'rev-parse', 'HEAD', 'HEAD^{tree}']).decode().split()
    if identity != [PIN, TREE]:
        raise SystemExit('base identity mismatch: ' + repr(identity))

    outputs = {}
    for path, anchor, replacement in SEAMS:
        text = outputs.get(path) or (BASE / path).read_text()
        if text.count(anchor) != 1:
            raise SystemExit(f'anchor not unique ({text.count(anchor)}x): {path}: {anchor[:60]!r}')
        print(f'anchor unique: {path}: 1')
        outputs[path] = text.replace(anchor, replacement)

    # Include the hook header at the top include of every transformed file.
    # If that first include sits inside an unclosed conditional block (e.g.
    # ggml-backend.cpp's #ifdef _WIN32 guard), insert after the block closes
    # instead, so the observer header is compiled on every platform.
    import re as _re
    for path, text in list(outputs.items()):
        lines = text.split('\n')
        depth = 0
        insert_at = None
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith(('#ifdef', '#ifndef')) or (
                    stripped.startswith('#if ') and not stripped.startswith('#if defined')):
                depth += 1
            elif stripped.startswith('#endif'):
                depth -= 1
            elif stripped.startswith('#include') and depth == 0:
                insert_at = i
                break
        if insert_at is None:
            raise SystemExit('no unconditional include found: ' + path)
        header = 'is301_c_shim.h' if path.endswith('.c') else 'is301_observer.h'
        lines.insert(insert_at, '#include "' + header + '"')
        outputs[path] = '\n'.join(lines)

    extras = {
        'is301_c_shim.h': SHIM_H,
        'is301_sink.cpp': SINK_CPP,
        'tests/native-buffer-graph-observed.cpp': FIXTURE_CPP,
        'tests/native-fact-bounds.cpp': FACT_BOUNDS_CPP,
    }

    manifest_files = []
    diffs = []
    for path, text in sorted({**outputs, **extras}.items()):
        target = FIX / 'overlay' / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
        manifest_files.append({'path': path,
                               'sha256': hashlib.sha256(text.encode()).hexdigest()})
        if path in outputs:
            original = (BASE / path).read_text()
            diffs.append(''.join(difflib.unified_diff(
                original.splitlines(True), text.splitlines(True),
                fromfile='a/' + path, tofile='b/' + path)))
    header = (FIX / 'overlay/is301_observer.h').read_bytes()
    manifest_files.append({'path': 'is301_observer.h',
                           'sha256': hashlib.sha256(header).hexdigest()})

    patch_text = ''.join(diffs)
    (FIX / 'native-observer-overlay.patch').write_text(patch_text)
    manifest = {
        'schema': 'native-observer-transformed/1',
        'base_revision': PIN,
        'base_tree': TREE,
        'patch_sha256': hashlib.sha256(patch_text.encode()).hexdigest(),
        'files': manifest_files,
    }
    (FIX / 'native-observer-transformed.json').write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + '\n')
    print('transformed files:', len(manifest_files))
    print('patch sha256:', manifest['patch_sha256'])


if __name__ == '__main__':
    main()
