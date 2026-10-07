// R8-A2 producer-occurrence CPU harness TEMPLATE. Synthetic CPU recording,
// NEVER a physical GPU observation.
//
// TEMPLATE, NOT STANDALONE: the five occurrence-counter expressions are
// placeholders ({RESET}, {ASSIGN}, {BEGIN}, {PATH}, {END}). At test time,
// tests/test_issue280_source.py extracts the ACTUAL expressions inserted
// into the production sources by scripts/issue280_source.py and substitutes
// them before compiling, so executing this harness executes the real
// generated counter logic (semantic binding: a mutated transform produces a
// mutated harness, and the real collector rejects its stream).
//
// Lifecycle order mirrors the pinned source:
//   ggml_backend_sched_graph_compute_async entry  -> reset()      (per graph;
//     1:1 with the observer's graph_begin on the process_ubatch path:
//     llama_context::graph_compute performs exactly one async sched call
//     per emitted graph)
//   compute_splits manifest loop, per planned input
//                                                -> assign(input, copy)
//   per-split input copy                         -> begin(input, copy) at
//     boundary_begin; current(input, copy) at boundary_end
//   ggml-vulkan copy_path (scheduler-initiated cross-die input copy)
//                                                -> current(src, dst)
#include <cstdlib>
#include <iostream>
#include <sstream>
#include <string>
#include <vector>

static long long clock_ns = 0;
static long long recording_clock() { return clock_ns; }
#define I280_CLOCK recording_clock
#define I280_LOG(s) (std::cout << "I280 " << s << '\n')
#include "issue280_observer.h"
#include "issue280_occurrence.h"

// Stand-in tensor identities: distinct stable addresses model distinct
// ggml_tensor objects (including one ggml_cgraph reused across invocations,
// which keeps identical tensor addresses — the case-1 graph-object reuse).
static const void * T_IN = (const void *) 0x1000;
static const void * T_C1 = (const void *) 0x2000;
static const void * T_C2 = (const void *) 0x3000;

struct PlannedPair { const void * input; const void * copy; };

// Inserted at ggml_backend_sched_graph_compute_async entry (production
// anchor in scripts/issue280_source.py INSERTIONS for ggml-backend.cpp).
// {RESET} is replaced by the transform's verbatim inserted line.
static void sched_graph_compute_async_entry() {
    {RESET}
}

// copy_manifest site (compute_splits pre-execution loop): the authoritative
// occurrence assignment. {ASSIGN} is the transform's verbatim inserted line
// (it declares observed_occ).
static void emit_manifest_site(int tokens, const PlannedPair & pair) {
    const void * input = pair.input;
    const void * copy = pair.copy;
    {ASSIGN}
    issue280::event("copy_manifest").s("tensor", "ffn_out-0").s("src", "Vulkan0")
        .s("dst", "Vulkan1").p("input", input).p("copy", copy).n("occ", observed_occ)
        .n("bytes", tokens * 16).s("type", "f32").n("ne0", 4)
        .n("ne1", tokens).n("ne2", 1).n("ne3", 1).n("nb0", 4)
        .n("nb1", 16).n("nb2", tokens * 16).n("nb3", tokens * 16)
        .n("view_offset", 0).n("buffer_bytes", 65536).emit();
}

// boundary_begin site (per-split input copy): begins the next copy event
// for this (input, copy) — a repeated pair advances 0, then 1. {BEGIN} is
// the transform's verbatim inserted line (it completes this chain).
static void emit_boundary_begin_site(int tokens, const PlannedPair & pair) {
    const void * input = pair.input;
    const void * input_cpy = pair.copy;
    issue280::event("boundary_begin").s("tensor", "ffn_out-0")
        .s("src", "Vulkan0").s("dst", "Vulkan1").p("input", input).p("copy", input_cpy)
        .n("bytes", tokens * 16)
        {BEGIN}
}

// copy_path site (ggml-vulkan.cpp, scheduler-initiated cross-die input
// copy): (src, dst) ARE the planned input and its selected copy. {PATH} is
// the transform's verbatim inserted line (a chain continuation).
static void emit_copy_path_site(const PlannedPair & pair,
                                const std::string & src_buffer,
                                const std::string & dst_buffer) {
    const void * src = pair.input;
    const void * dst = pair.copy;
    issue280::event("copy_path").p("input", src).p("copy", dst)
        {PATH}
        .s("src_buffer", src_buffer).s("dst_buffer", dst_buffer).emit();
}

// boundary_end site: the occurrence of the copy event opened by begin.
// {END} is the transform's verbatim inserted line (a complete statement).
static void emit_boundary_end_site(const PlannedPair & pair) {
    const void * input = pair.input;
    const void * input_cpy = pair.copy;
    {END}
}

// Buffer-scope host legs (pinned vk hook shape: concrete buffer identities
// only; no logical occ can be soundly derived from buffer-global counters).
static void emit_host_leg_site(const std::string & direction, int bytes,
                               const std::string & src_buffer,
                               const std::string & dst_buffer) {
    I280_EVENT("host_leg").s("src_buffer", src_buffer).s("dst_buffer", dst_buffer)
        .s("direction", direction).n("bytes", bytes).emit();
}

static void emit_inventory() {
    for (int d = 0; d < 2; ++d) {
        const std::string bdf = d == 0 ? "0000:01:00.0" : "0000:02:00.0";
        I280_EVENT("weight_inventory").s("tensor", "blk." + std::to_string(d) + ".weight")
            .s("bdf", bdf).n("bytes", 1024).n("layer", d)
            .s("buffer", "weight-inventory-" + std::to_string(d)).emit();
        I280_EVENT("kv_inventory").s("tensor", "kv.k." + std::to_string(d))
            .s("bdf", bdf).n("bytes", 128).s("kind", "k").n("layer", d)
            .s("buffer", "kv-" + std::to_string(d)).emit();
        I280_EVENT("kv_inventory").s("tensor", "kv.v." + std::to_string(d))
            .s("bdf", bdf).n("bytes", 128).s("kind", "v").n("layer", d)
            .s("buffer", "kv-" + std::to_string(d)).emit();
        I280_EVENT("buffer_decl").s("buffer", "staging-" + std::to_string(d))
            .s("bdf", bdf).n("bytes", 256).s("purpose", "staging").emit();
        I280_EVENT("buffer_decl").s("buffer", "compute-" + std::to_string(d))
            .s("bdf", bdf).n("bytes", 512).s("purpose", "compute").emit();
    }
    I280_EVENT("cpu_state").s("kind", "runtime").n("bytes", 64).emit();
}

// One producer graph lifecycle: sched entry (reset) -> manifests (assign)
// -> per-die execution with boundary begin/copy_path/legs/end (begin/current).
static void emit_graph(int request, int graph_index, const std::string & phase,
                       int tokens, const std::vector<int> & token_ids,
                       const std::vector<int> & positions,
                       const std::vector<PlannedPair> & pairs) {
    std::ostringstream row;
    row << "{\"schema\":\"issue280-raw/1\",\"event\":\"batch_begin\",\"ts_ns\":"
        << recording_clock() << ",\"request\":" << request << ",\"seq\":0"
        << ",\"tokens\":" << tokens << ",\"phase\":\"" << phase
        << "\",\"speculative\":0,\"token_ids\":[";
    for (size_t i = 0; i < token_ids.size(); ++i) {
        if (i) row << ',';
        row << token_ids[i];
    }
    row << "],\"positions\":[";
    for (size_t i = 0; i < positions.size(); ++i) {
        if (i) row << ',';
        row << positions[i];
    }
    row << "]}";
    I280_LOG(row.str());
    clock_ns += 100;
    I280_EVENT("graph_begin").n("request", request)
        .s("graph", "g" + std::to_string(graph_index))
        .n("tokens", tokens).n("seq", 0).n("sequences", 1).emit();
    // Production order: the async sched entry (and with it the occurrence
    // reset) precedes the compute_splits manifest loop.
    sched_graph_compute_async_entry();
    for (const PlannedPair & pair : pairs) { emit_manifest_site(tokens, pair); }
    for (int d = 0; d < 2; ++d) {
        clock_ns += 1;
        const std::string ctx = "ctx" + std::to_string(d);
        const std::string cmd = "cmd" + std::to_string(d);
        const std::string subctx = "sub" + std::to_string(d);
        const std::string bdf = d == 0 ? "0000:01:00.0" : "0000:02:00.0";
        if (d == 1) {
            for (size_t pi = 0; pi < pairs.size(); ++pi) {
                const std::string sb = "sb" + std::to_string(pi);
                const std::string db = "db" + std::to_string(pi);
                emit_boundary_begin_site(tokens, pairs[pi]);
                emit_copy_path_site(pairs[pi], sb, db);
                clock_ns += 10;
                emit_host_leg_site("device_to_host", tokens * 16, sb, db);
                clock_ns += 10;
                emit_host_leg_site("host_to_device", tokens * 16, sb, db);
                clock_ns += 10;
                emit_boundary_end_site(pairs[pi]);
            }
        }
        I280_EVENT("vk_graph_begin").n("request", request).s("ctx", ctx)
            .s("backend", "Vulkan" + std::to_string(d)).s("bdf", bdf).emit();
        I280_EVENT("ctx_create").n("request", request).s("subctx", subctx)
            .s("ctx", ctx).emit();
        I280_EVENT("node").n("request", request).s("ctx", ctx).s("cmd", cmd)
            .n("use", graph_index + 1).s("tensor", "ffn_out-" + std::to_string(d))
            .s("op", "MUL_MAT").emit();
        I280_EVENT("weight").n("request", request).s("ctx", ctx).s("cmd", cmd)
            .n("use", graph_index + 1).s("tensor", "blk." + std::to_string(d) + ".ffn_gate.weight")
            .s("buffer", "weights" + std::to_string(d)).n("offset", 16)
            .n("bytes", 128).n("buffer_bytes", 4096).emit();
        I280_EVENT("dispatch").n("request", request).s("ctx", ctx).s("cmd", cmd)
            .n("use", graph_index + 1).s("pipeline", "mul_mat_f32").n("x", 1)
            .n("y", 1).n("z", 1).emit();
        I280_EVENT("submit").n("request", request).s("subctx", subctx)
            .s("cmd", cmd).n("use", graph_index + 1).emit();
        I280_EVENT("complete").n("request", request).s("ctx", ctx)
            .s("wait", "fence").emit();
        I280_EVENT("vk_graph_end").n("request", request).s("ctx", ctx).emit();
    }
    I280_EVENT("graph_end").n("request", request)
        .s("graph", "g" + std::to_string(graph_index)).n("status", 0).emit();
    I280_EVENT("batch_end").n("request", request).n("status", 0).emit();
}

int main(int argc, char ** argv) {
    if (argc != 2) return 2;
    setenv("ISSUE280_OBSERVE", "1", 1);
    const std::string mode(argv[1]);
    const int prompt_tokens = 4;
    std::vector<int> prompt_ids, prompt_pos;
    for (int i = 0; i < prompt_tokens; ++i) { prompt_ids.push_back(i + 1); prompt_pos.push_back(i); }
    const PlannedPair in_c1 = { T_IN, T_C1 };
    const PlannedPair in_c2 = { T_IN, T_C2 };

    I280_EVENT("recording").s("kind", "CPU_FIXTURE")
        .s("source_pin", "b29c606e28a01b1bc8c1351026a0fa6e616bf6c4")
        .n("requests_planned", 1).emit();
    emit_inventory();
    I280_EVENT("request_accept").n("request", 7).n("ordinal", 1).emit();

    if (mode == "two-graphs-same-pair") {
        // Case 1: the SAME (input, copy) across two graph invocations in one
        // process (the graph object and its tensors are reused: identical
        // addresses) must emit occurrence 0, then 0 — the registry resets at
        // each sched entry, matching the collector's per-graph derivation.
        emit_graph(7, 0, "prefill", prompt_tokens, prompt_ids, prompt_pos, { in_c1 });
        I280_EVENT("sample").n("request", 7).n("position", 0).n("token_id", 40)
            .n("absolute_position", prompt_tokens + 0).n("eos", 0).emit();
        emit_graph(7, 1, "decode", 1, { 40 }, { prompt_tokens }, { in_c1 });
        I280_EVENT("sample").n("request", 7).n("position", 1).n("token_id", 41)
            .n("absolute_position", prompt_tokens + 1).n("eos", 1).emit();
    } else if (mode == "one-input-two-copies") {
        // Case 2: one input with two distinct copies in a graph emits
        // occurrence 0 for each (input, copy) pair.
        emit_graph(7, 0, "prefill", prompt_tokens, prompt_ids, prompt_pos, { in_c1, in_c2 });
        I280_EVENT("sample").n("request", 7).n("position", 0).n("token_id", 40)
            .n("absolute_position", prompt_tokens + 0).n("eos", 1).emit();
    } else if (mode == "repeat-pair") {
        // Case 3: repeated occurrences of the same pair within a graph emit
        // 0, then 1.
        emit_graph(7, 0, "prefill", prompt_tokens, prompt_ids, prompt_pos, { in_c1, in_c1 });
        I280_EVENT("sample").n("request", 7).n("position", 0).n("token_id", 40)
            .n("absolute_position", prompt_tokens + 0).n("eos", 1).emit();
    } else if (mode == "agree") {
        // Case 4 (agreement): manifest, begin, copy_path and end all carry
        // the one assigned occurrence.
        emit_graph(7, 0, "prefill", prompt_tokens, prompt_ids, prompt_pos, { in_c1 });
        I280_EVENT("sample").n("request", 7).n("position", 0).n("token_id", 40)
            .n("absolute_position", prompt_tokens + 0).n("eos", 1).emit();
    } else {
        return 2;
    }
    I280_EVENT("response").n("request", 7)
        .n("sampled", mode == "two-graphs-same-pair" ? 2 : 1)
        .n("prompt_processed", prompt_tokens).n("prompt_cached", 0).n("eos", 1).emit();
    I280_EVENT("request_end").n("request", 7).s("stop_reason", "eos")
        .n("prompt_processed", prompt_tokens).n("prompt_cached", 0).emit();
    return 0;
}
