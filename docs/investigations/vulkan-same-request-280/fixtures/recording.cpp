// Synthetic CPU recording, NEVER a physical GPU observation.
// Emits the same I280 raw JSON row stream consumed by the source-log collector.
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

static void emit_batch(int request, int seq, int tokens, const std::string & phase,
                       const std::vector<int> & token_ids,
                       const std::vector<int> & positions,
                       const std::string & extra = "") {
    if (!issue280::enabled()) return;
    std::ostringstream row;
    row << "{\"schema\":\"issue280-raw/1\",\"event\":\"batch_begin\",\"ts_ns\":"
        << recording_clock() << ",\"request\":" << request << ",\"seq\":" << seq
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
    row << ']';
    if (!extra.empty()) row << ',' << extra;
    row << '}';
    I280_LOG(row.str());
}

static std::vector<int> sequence(int count, int start) {
    std::vector<int> values;
    for (int i = 0; i < count; ++i) values.push_back(start + i);
    return values;
}

static void emit_inventory(bool one_die, bool omit) {
    if (omit) return;
    if (std::getenv("I280_CPU_ONLY_INVENTORY")) {
        // Emitter-alignment control: mixed placement — both dies carry their
        // own weight/KV inventory AND the CPU backend reports additional
        // named state via the backend-name fallback (no BDF). This is the
        // real llama.cpp mixed shape (e.g. output embeddings kept on CPU).
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
        }
        I280_EVENT("weight_inventory").s("tensor", "output.weight")
            .s("bdf", "CPU").n("bytes", 300).n("layer", -1)
            .s("buffer", "cpu-weights").emit();
        I280_EVENT("kv_inventory").s("tensor", "kv.scratch")
            .s("bdf", "CPU").n("bytes", 96).s("kind", "kv").n("layer", -1)
            .s("buffer", "cpu-kv").emit();
        I280_EVENT("cpu_state").s("kind", "runtime").n("bytes", 64).emit();
        return;
    }
    const int count = one_die ? 1 : 2;
    for (int d = 0; d < count; ++d) {
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

static void emit_manifest(int request, int tokens, int occ, const std::string & mode,
                          const std::string & input, const std::string & copy) {
    std::string tensor_type = "f32";
    int ne0 = 4;
    int view_offset = 0;
    bool bounded = false;
    if (mode == "inconsistent-shape-bytes" || mode == "shape-law-violation") ne0 = 5;
    if (mode == "unsupported-type") tensor_type = "q4_0";
    if (mode == "range-overflow") { view_offset = 1; bounded = true; }
    // The pinned ggml hook reads the containing buffers' contexts, so real
    // source streams always carry bounds; the fixture declares them too.
    // range-overflow keeps a bound SMALLER than the payload to prove the
    // overflow check; missing-bounds omits the field entirely (unprovable).
    bounded = true;
    const int buffer_bound = mode == "range-overflow" ? 32 : 65536;
    if (issue280::enabled()) {
        issue280::event event("copy_manifest");
        event.n("request", request).s("tensor", "ffn_out-0").s("src", "Vulkan0")
            .s("dst", "Vulkan1").s("input", input).s("copy", copy).n("occ", occ)
            .n("bytes", tokens * 16).s("type", tensor_type).n("ne0", ne0)
            .n("ne1", tokens).n("ne2", 1).n("ne3", 1).n("nb0", 4)
            .n("nb1", 16).n("nb2", tokens * 16).n("nb3", tokens * 16)
            .n("view_offset", view_offset);
        if (bounded && mode != "missing-bounds") { event.n("buffer_bytes", buffer_bound); }
        event.emit();
    }
}

static void emit_source_shaped_leg(const std::string & direction, int occ,
                                   int bytes, const std::string & src_buffer,
                                   const std::string & dst_buffer) {
    // Pinned-source shape: ggml-vulkan host legs carry NO request and NO
    // logical (input,copy) identity — only concrete buffer identities, the leg
    // direction, and the byte count. `occ` >= 0 models the CURRENT (defective)
    // emitter behavior: a buffer-GLOBAL counter keyed by the vk_buffer, not
    // the logical input/copy occurrence of the enclosing boundary. occ < 0
    // omits the field entirely (the corrected emitter shape).
    if (issue280::enabled()) {
        issue280::event host("host_leg");
        if (occ >= 0) host.n("occ", occ);
        host.s("direction", direction).n("bytes", bytes)
            .s("src_buffer", src_buffer).s("dst_buffer", dst_buffer);
        host.emit();
    }
}

static void emit_shared_buffer_copy(int request, int tokens, int occ,
                                    const std::string & input,
                                    const std::string & copy,
                                    const std::string & src_buffer,
                                    const std::string & dst_buffer,
                                    int d2h_occ, int h2d_occ,
                                    bool skip_copy_path = false,
                                    const std::string & leg_src = "",
                                    const std::string & leg_dst = "") {
    // Two logical inputs can legitimately share one underlying vk_buffer pair:
    // at the pinned llama.cpp source multiple tensors occupy offsets in one
    // ggml_backend_vk_buffer_context::dev_buffer, so logical input B (occ=0)
    // reuses the same concrete buffers as logical input A (occ=0).
    I280_EVENT("boundary_begin").n("request", request).s("tensor", "ffn_out-0")
        .s("src", "Vulkan0").s("dst", "Vulkan1").s("input", input)
        .s("copy", copy).n("occ", occ).n("bytes", tokens * 16).emit();
    if (!skip_copy_path) {
        I280_EVENT("copy_path").n("request", request).s("input", input).s("copy", copy)
            .n("occ", occ).s("src_buffer", src_buffer).s("dst_buffer", dst_buffer).emit();
    }
    clock_ns += 10;
    emit_source_shaped_leg("device_to_host", d2h_occ, tokens * 16,
                           leg_src.empty() ? src_buffer : leg_src,
                           leg_dst.empty() ? dst_buffer : leg_dst);
    clock_ns += 10;
    emit_source_shaped_leg("host_to_device", h2d_occ, tokens * 16,
                           src_buffer, dst_buffer);
    clock_ns += 10;
    I280_EVENT("boundary_end").n("request", request).s("input", input)
        .s("copy", copy).n("occ", occ).n("bytes", tokens * 16).emit();
}

static void emit_copy(int request, int tokens, int occ, const std::string & mode,
                      const std::string & input, const std::string & copy, bool native) {
    const int bytes = mode == "wrong-bytes" ? tokens * 16 - 1 : tokens * 16;
    I280_EVENT("boundary_begin").n("request", request).s("tensor", "ffn_out-0")
        .s("src", "Vulkan0").s("dst", "Vulkan1").s("input", input)
        .s("copy", copy).n("occ", occ).n("bytes", bytes).emit();
    if (mode == "abort-incomplete-copy") return;
    I280_EVENT("copy_path").n("request", request).s("input", input).s("copy", copy)
        .n("occ", occ).s("src_buffer", "sb").s("dst_buffer", "db").emit();
    if (native) {
        I280_EVENT("ctx_create").n("request", request).s("subctx", "temp")
            .s("ctx", "temp").emit();
        I280_EVENT("submit").n("request", request).s("subctx", "temp")
            .s("cmd", "temp-cmd").n("use", static_cast<int>(clock_ns)).emit();
        I280_EVENT("fence_marker").n("request", request).s("subctx", "temp").emit();
        I280_EVENT("complete").n("request", request).s("ctx", "temp")
            .s("wait", "transfer_fence").emit();
    }
    clock_ns += 10;
    if (issue280::enabled()) {
        issue280::event host("host_leg");
        host.n("request", request).s("input", input).s("copy", copy).n("occ", occ)
            .s("direction", "device_to_host").n("bytes", tokens * 16);
        host.s("src_buffer", "sb").s("dst_buffer", "db");
        host.emit();
    }
    clock_ns += 10;
    if (mode != "missing-host-leg" && issue280::enabled()) {
        issue280::event host("host_leg");
        host.n("request", request).s("input", input).s("copy", copy).n("occ", occ)
            .s("direction", "host_to_device").n("bytes", tokens * 16);
        host.s("src_buffer", "sb").s("dst_buffer", "db");
        host.emit();
    }
    clock_ns += 10;
    I280_EVENT("boundary_end").n("request", request).s("input", input)
        .s("copy", copy).n("occ", occ).n("bytes", tokens * 16).emit();
}

static void request_accept(int request, int ordinal) {
    I280_EVENT("request_accept").n("request", request).n("ordinal", ordinal).emit();
}

static void request_end(int request, const std::string & stop_reason, int prompt_tokens) {
    I280_EVENT("request_end").n("request", request).s("stop_reason", stop_reason)
        .n("prompt_processed", prompt_tokens).n("prompt_cached", 0).emit();
}

static void emit_request(int request, int ordinal, const std::string & mode,
                         bool one_die, bool micro, bool first_request) {
    request_accept(request, ordinal);
    // leg-outside mode: emit the rogue buffer-scope leg BEFORE any boundary
    // opens (at request scope, after request_accept, no active boundary).
    if (mode == "shared-buffer-leg-outside") {
        clock_ns += 10;
        emit_source_shaped_leg("device_to_host", -1, 64, "sb", "db");
    }
    const bool native = mode == "native-path" || mode == "timeline-stale"
        || mode == "repeated-successful-timeline-wait" || mode == "repeat-wait"
        || mode == "native-zero-first-use" || mode == "conflicting-wait"
        || mode == "two-requests" || mode == "two-sequential-requests";
    const bool repeat_copy = mode == "repeat-copy";
    const int graph_count = mode == "eos-first" ? 1 : micro ? 4 : 3;
    const int die_count = one_die ? 1 : 2;
    const int prompt_tokens = mode == "abort-preserves-work" ? 1 : micro ? 4 : 4;
    const int request_token_base = request == 8 ? 80 : 40;
    const int stop_after = (mode == "abort-preserves-work" || mode == "abort-second-not-attempted") ? 0
        : mode == "abort-unsubmitted-accounting" ? 1 : -1;

    for (int g = 0; g < graph_count; ++g) {
        clock_ns += 100;
        const bool prefill = micro ? g < 2 : g == 0;
        const int graph_tokens = prefill ? (micro ? 2 : prompt_tokens) : 1;
        int ntok = graph_tokens;
        if (!(micro && g == 1)) {
            std::vector<int> token_ids, positions;
            std::string phase = prefill ? "prefill" : "decode";
            if (prefill) {
                token_ids = sequence(micro ? 4 : ntok, 1);
                positions = sequence(micro ? 4 : ntok, 0);
                ntok = micro ? 4 : ntok;
            } else {
                const int sample_index = micro ? g - 2 : g - 1;
                int token = request_token_base + sample_index;
                if ((mode == "decode-token-mismatch" || mode == "decode-wrong-token")
                        && first_request && g == 1) token = 999;
                token_ids = {token};
                // Pinned-source law: sample fires at prompt.tokens.pos_next()=N
                // and the sampled token is consumed by the next decode AT
                // position N (handle_last_sampled_token adds it at pos_next).
                int position = prompt_tokens + sample_index;
                if ((mode == "wrong-absolute-decode-position" || mode == "decode-wrong-position")
                        && first_request && g == 1) position = 17;
                positions = {position};
            }
            std::string extra;
            if (mode == "warm-request-no-inheritance" && g == 1)
                extra = "\"frame_request\":8";
            emit_batch(request, 0, ntok, phase, token_ids, positions, extra);
        }

        const std::string graph_id = request == 8 ? "g8-" + std::to_string(g) : "g";
        I280_EVENT("graph_begin").n("request", request).s("graph", graph_id)
            .n("tokens", graph_tokens).n("seq", 0).n("sequences", 1).emit();

        const bool no_manifest = mode == "missing-manifest";
        const int copies = repeat_copy ? 2 : 1;
        const std::string input = request == 8 ? "in8" : "in";
        const std::string copy = request == 8 ? "out8" : "out";
        // Shared-buffer modes: two DISTINCT logical (input, copy) identities,
        // each legitimately occ=0, sharing ONE concrete src/dst vk_buffer pair
        // (multiple tensors occupy offsets in one dev_buffer at the pin).
        const bool shared_buffer = mode.rfind("shared-buffer-", 0) == 0;
        const std::string input_b = "in-b", copy_b = "out-b";
        if (!one_die && !no_manifest) {
            if (shared_buffer) {
                emit_manifest(request, graph_tokens, 0, mode, input, copy);
                emit_manifest(request, graph_tokens, 0, mode, input_b, copy_b);
            } else {
                for (int occ = 0; occ < copies; ++occ)
                    emit_manifest(request, graph_tokens, occ, mode, input, copy);
            }
        }

        for (int d = 0; d < die_count; ++d) {
            clock_ns += 1;
            const std::string ctx = (request == 8 ? "ctx8" : "ctx") + std::to_string(d);
            const std::string cmd = (request == 8 ? "cmd8" : "cmd") + std::to_string(d);
            const std::string subctx = (request == 8 ? "sub8" : "sub") + std::to_string(d);
            const int use = mode == "native-zero-first-use" && g == 0 && d == 0 ? 0 : g + 1;
            const std::string bdf = d == 0 ? "0000:01:00.0" : "0000:02:00.0";

            if (d == 1 && !one_die) {
                if (shared_buffer) {
                    // Current-emitter shape: buffer-global leg counters. Logical
                    // A is legs 0/0; logical B reuses the same buffers so its
                    // d2h counter reads 1 and h2d counter reads 1 while its
                    // LOGICAL occurrence is 0.
                    const bool corrected = mode != "shared-buffer-current-emitter";
                    const std::string leg_src = mode == "shared-buffer-wrong-buffers" ? "other-sb" : "";
                    const std::string leg_dst = mode == "shared-buffer-wrong-buffers" ? "other-db" : "";
                    emit_shared_buffer_copy(request, graph_tokens, 0, input, copy,
                                            "sb", "db", corrected ? -1 : 0, corrected ? -1 : 0);
                    emit_shared_buffer_copy(request, graph_tokens, 0, input_b, copy_b,
                                            "sb", "db", corrected ? -1 : 1, corrected ? -1 : 1,
                                            mode == "shared-buffer-no-copy-path",
                                            leg_src, leg_dst);
                } else {
                    for (int occ = 0; occ < copies; ++occ) {
                        emit_copy(request, graph_tokens, occ, mode, input, copy, native);
                        if (mode == "abort-incomplete-copy") {
                            request_end(request, "abort", 0);
                            return;
                        }
                    }
                }
            }
            I280_EVENT("vk_graph_begin").n("request", request).s("ctx", ctx)
                .s("backend", "Vulkan" + std::to_string(d)).s("bdf", bdf).emit();
            I280_EVENT("ctx_create").n("request", request).s("subctx", subctx)
                .s("ctx", ctx).emit();
            I280_EVENT("node").n("request", request).s("ctx", ctx).s("cmd", cmd)
                .n("use", use).s("tensor", "ffn_out-" + std::to_string(d))
                .s("op", "MUL_MAT").emit();
            I280_EVENT("weight").n("request", request).s("ctx", ctx).s("cmd", cmd)
                .n("use", use).s("tensor", "blk." + std::to_string(d) + ".ffn_gate.weight")
                .s("buffer", "weights" + std::to_string(d)).n("offset", 16)
                .n("bytes", 128).n("buffer_bytes", 4096).emit();
            if (mode != "empty-submit" || d != 1) {
                I280_EVENT("dispatch").n("request", request).s("ctx", ctx).s("cmd", cmd)
                    .n("use", use).s("pipeline", "mul_mat_f32").n("x", 1)
                    .n("y", 1).n("z", 1).emit();
            }
            const bool orphan = (mode == "unsubmitted-compute-recording" || mode == "unsubmitted-compute")
                    ? (g == 0 && d == 0)
                    : mode == "abort-unsubmitted-accounting" && g == 1 && d == 0;
            if (orphan) {
                I280_EVENT("node").n("request", request).s("ctx", ctx)
                    .s("cmd", "orphan-cmd").n("use", 91).s("tensor", "orphan.compute")
                    .s("op", "MUL_MAT").emit();
                I280_EVENT("dispatch").n("request", request).s("ctx", ctx)
                    .s("cmd", "orphan-cmd").n("use", 91).s("pipeline", "mul_mat_f32")
                    .n("x", 1).n("y", 1).n("z", 1).emit();
            }
            if (mode == "early-completion")
                I280_EVENT("complete").n("request", request).s("ctx", ctx)
                    .s("wait", "fence").emit();
            I280_EVENT("submit").n("request", request).s("subctx", subctx)
                .s("cmd", cmd).n("use", use).emit();
            if (mode == "abort" && g == 0 && d == 0) {
                request_end(request, "abort", 0);
                return;
            }
            if (native) {
                const int value = g + 1;
                I280_EVENT("event_record").n("request", request).s("ctx", ctx)
                    .s("sync_event", "ev" + std::to_string(d)).n("value", value).emit();
                if (mode == "conflicting-wait" && g == 0 && d == 0) {
                    I280_EVENT("event_record").n("request", request).s("ctx", ctx)
                        .s("sync_event", "ev" + std::to_string(d)).n("value", value).emit();
                }
                I280_EVENT("event_complete").n("request", request)
                    .s("sync_event", "ev" + std::to_string(d))
                    .n("value", mode == "timeline-stale" && g == 0 ? value + 1 : value).emit();
                if (mode == "repeated-successful-timeline-wait" || mode == "repeat-wait")
                    I280_EVENT("event_complete").n("request", request)
                        .s("sync_event", "ev" + std::to_string(d)).n("value", value).emit();
            } else if (mode != "missing-completion") {
                I280_EVENT("complete").n("request", request).s("ctx", ctx)
                    .s("wait", "fence").emit();
            }
            I280_EVENT("vk_graph_end").n("request", request).s("ctx", ctx).emit();
        }
        I280_EVENT("graph_end").n("request", request).s("graph", graph_id).n("status", 0).emit();
        if (!(micro && g == 0)) {
            I280_EVENT("batch_end").n("request", request).n("status", 0).emit();
            const int sample_index = micro ? g - 1 : g;
            int sample_request = mode == "wrong-request" && first_request ? request + 1 : request;
            const bool terminal = g == graph_count - 1 && mode != "limit";
            int sample_position = micro ? g - 1 : g;
            const int absolute_position = prompt_tokens + sample_index;
            I280_EVENT("sample").n("request", sample_request).n("position", sample_position)
                .n("token_id", request_token_base + sample_index)
                .n("absolute_position", absolute_position).n("eos", terminal ? 1 : 0).emit();
        }
        if (g == stop_after) {
            request_end(request, "abort", prompt_tokens);
            return;
        }
    }

    const int sampled = micro ? graph_count - 1 : graph_count;
    I280_EVENT("response").n("request", request)
        .n("sampled", mode == "wrong-output" && first_request ? sampled + 1 : sampled)
        .n("prompt_processed", prompt_tokens).n("prompt_cached", 0)
        .n("eos", mode == "limit" ? 0 : 1).emit();
    request_end(request, mode == "word-stop-full-request" ? "word"
                : mode == "none-stop-after-response" ? "none"
                : mode == "limit" ? "limit" : "eos", prompt_tokens);
}

int main(int argc, char ** argv) {
    if (argc != 2) return 2;
    setenv("ISSUE280_OBSERVE", "1", 1);
    const std::string mode(argv[1]);
    if (mode == "disabled") unsetenv("ISSUE280_OBSERVE");
    const bool one_die = mode == "single-die-baseline" || mode == "single-die";
    const bool micro = mode == "microbatch";
    const bool omit_placement = mode == "placement-missing"
        || mode == "placement-ownership-unexplained";
    const bool two_requests = mode == "two-sequential-requests" || mode == "two-requests";
    const bool planned_two = two_requests || mode == "abort-second-not-attempted"
        || mode == "cross-request-alias";
    I280_EVENT("recording").s("kind", mode == "source-identity" ? "SOURCE_OBSERVER" : "CPU_FIXTURE")
        .s("source_pin", "b29c606e28a01b1bc8c1351026a0fa6e616bf6c4")
        .n("requests_planned", planned_two ? 2 : 1).emit();
    // Adversarial placement modes must NOT inherit the honest inventory: emit
    // their tailored rows as the ONLY inventory so each claim is isolated.
    const bool adversarial_placement = omit_placement || mode == "placement-swapped-layers"
        || mode == "staging-as-weights";
    emit_inventory(one_die, adversarial_placement);
    if (mode == "placement-swapped-layers") {
        // E2 adversarial: inventory rows claim the OPPOSITE die owns each
        // layer; dispatch evidence remains die0=blk.0, die1=blk.1.
        for (int d = 0; d < 2; ++d) {
            const std::string bdf = d == 0 ? "0000:01:00.0" : "0000:02:00.0";
            const int other = 1 - d;
            I280_EVENT("weight_inventory").s("tensor", "blk." + std::to_string(other) + ".weight")
                .s("bdf", bdf).n("bytes", 1024).n("layer", other)
                .s("buffer", "swapped-weight-" + std::to_string(d)).emit();
        }
        I280_EVENT("cpu_state").s("kind", "runtime").n("bytes", 64).emit();
        emit_request(7, 1, "positive", false, false, true);
        return 0;
    }
    if (mode == "staging-as-weights") {
        // E3 adversarial: one buffer identity declared as staging AND weights.
        I280_EVENT("buffer_decl").s("buffer", "staging-0")
            .s("bdf", "0000:01:00.0").n("bytes", 256).s("purpose", "staging").emit();
        I280_EVENT("weight_inventory").s("tensor", "blk.0.staging")
            .s("bdf", "0000:01:00.0").n("bytes", 999999).n("layer", 0)
            .s("buffer", "staging-0").emit();
        I280_EVENT("weight_inventory").s("tensor", "blk.1.weight")
            .s("bdf", "0000:02:00.0").n("bytes", 1024).n("layer", 1)
            .s("buffer", "weight-inventory-1").emit();
        I280_EVENT("cpu_state").s("kind", "runtime").n("bytes", 64).emit();
        emit_request(7, 1, "positive", false, false, true);
        return 0;
    }
    if (mode == "warm-request-no-inheritance") {
        request_accept(7, 1);
        emit_batch(7, 0, 1, "decode", {999}, {0}, "\"frame_request\":8");
        return 0;
    }
    emit_request(7, 1, mode, one_die, micro, true);
    if (two_requests) {
        clock_ns += 100;
        emit_request(8, 2, mode, false, false, false);
    } else if (mode == "cross-request-alias") {
        request_accept(8, 2);
        emit_batch(8, 0, 4, "prefill", {1, 2, 3, 4}, {0, 1, 2, 3});
        I280_EVENT("graph_begin").n("request", 8).s("graph", "g8")
            .n("tokens", 4).n("seq", 0).n("sequences", 1).emit();
        I280_EVENT("vk_graph_begin").n("request", 7).s("ctx", "ctx0")
            .s("backend", "Vulkan0").s("bdf", "0000:01:00.0").emit();
    }
    return 0;
}
