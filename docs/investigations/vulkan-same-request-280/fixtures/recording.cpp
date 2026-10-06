// Synthetic CPU recording, NEVER a physical GPU observation.
// Calls the identical raw emitter used by the pinned-source hooks; the parser
// consumes the resulting log, not preassembled proof/reducer dictionaries.
#include <iostream>
#include <string>
static long long clock_ns = 0;
static long long recording_clock() { return clock_ns; }
#define I280_CLOCK recording_clock
#define I280_LOG(s) (std::cout << "I280 " << s << '\n')
#include "issue280_observer.h"

int main(int argc, char ** argv) {
    if (argc != 2) return 2;
    setenv("ISSUE280_OBSERVE", "1", 1);
    const std::string mode(argv[1]);
    if (mode == "disabled") unsetenv("ISSUE280_OBSERVE");
    const bool native = mode == "native-path" || mode == "timeline-stale";
    const bool micro = mode == "microbatch";
    I280_EVENT("recording").s("kind", mode == "source-identity" ? "SOURCE_OBSERVER" : "CPU_FIXTURE").s("source_pin", "b29c606e28a01b1bc8c1351026a0fa6e616bf6c4").emit();
    const int graphs = mode == "eos-first" ? 1 : micro ? 4 : 3;
    for (int g = 0; g < graphs; ++g) {
        clock_ns = 100 + g * 100;
        const bool prefill = g < (micro ? 2 : 1);
        const int ntok = prefill ? (micro ? 2 : 4) : 1;
        if (!(micro && g == 1)) {
            I280_EVENT("batch_begin").n("request", 7).n("seq", 0).n("tokens", micro && g == 0 ? 4 : ntok)
                .s("phase", prefill ? "prefill" : "decode").n("speculative", 0).emit();
        }
        I280_EVENT("graph_begin").s("graph", "g").n("tokens", ntok).n("seq", 0).n("sequences", 1).emit();
        if (mode != "missing-manifest") {
            I280_EVENT("copy_manifest").s("tensor", "ffn_out-0").s("src", "Vulkan0").s("dst", "Vulkan1")
                .s("input", "in").s("copy", "out").n("bytes", ntok*16).s("type", "f32")
                .n("ne0", 4).n("ne1", ntok).n("ne2", 1).n("ne3", 1)
                .n("nb0", 4).n("nb1", 16).n("nb2", ntok*16).n("nb3", ntok*16).n("view_offset", 0).emit();
        }
        for (int d = 0; d < 2; ++d) {
            clock_ns += 1;
            const std::string ctx = "ctx" + std::to_string(d);
            const std::string cmd = "cmd" + std::to_string(d);
            const std::string bdf = d == 0 ? "0000:01:00.0" : "0000:02:00.0";
            if (d == 1) {
                I280_EVENT("boundary_begin").s("tensor", "ffn_out-0").s("src", "Vulkan0").s("dst", "Vulkan1")
                    .s("input", "in").s("copy", "out").n("bytes", mode == "wrong-bytes" ? ntok*16-1 : ntok*16).emit();
                if (native) {
                    I280_EVENT("copy_path").s("input", "in").s("copy", "out")
                        .s("src_buffer", "sb").s("dst_buffer", "db").emit();
                    I280_EVENT("ctx_create").s("subctx", "temp").s("ctx", "temp").emit();
                    I280_EVENT("submit").s("subctx", "temp").s("cmd", "temp-cmd").n("use", g+1).emit();
                    I280_EVENT("fence_marker").s("subctx", "temp").emit();
                    I280_EVENT("complete").s("ctx", "temp").s("wait", "transfer_fence").emit();
                }
                clock_ns += 10;
                if (native) {
                    I280_EVENT("host_leg").s("src_buffer", "sb").s("dst_buffer", "db").s("direction", "device_to_host").n("bytes", ntok*16).emit();
                } else {
                    I280_EVENT("host_leg").s("input", "in").s("copy", "out").s("direction", "device_to_host").n("bytes", ntok*16).emit();
                }
                clock_ns += 10;
                if (native) {
                    I280_EVENT("host_leg").s("src_buffer", "sb").s("dst_buffer", "db").s("direction", "host_to_device").n("bytes", ntok*16).emit();
                } else if (mode != "missing-host-leg") {
                    I280_EVENT("host_leg").s("input", "in").s("copy", "out").s("direction", "host_to_device").n("bytes", ntok*16).emit();
                }
                clock_ns += 10;
                I280_EVENT("boundary_end").s("input", "in").s("copy", "out").emit();
            }
            I280_EVENT("vk_graph_begin").s("ctx", ctx).s("backend", "Vulkan" + std::to_string(d)).s("bdf", bdf).emit();
            I280_EVENT("ctx_create").s("subctx", "sub" + std::to_string(d)).s("ctx", ctx).emit();
            I280_EVENT("node").s("ctx", ctx).s("cmd", cmd).n("use", g+1)
                .s("tensor", "ffn_out-" + std::to_string(d)).s("op", "MUL_MAT").emit();
            I280_EVENT("weight").s("ctx", ctx).s("cmd", cmd).n("use", g+1)
                .s("tensor", "blk." + std::to_string(d) + ".ffn_gate.weight")
                .s("buffer", "weights" + std::to_string(d)).n("offset", 16).n("bytes", 128).n("buffer_bytes", 4096).emit();
            if (mode != "empty-submit" || d != 1) {
                I280_EVENT("dispatch").s("ctx", ctx).s("cmd", cmd).n("use", g+1)
                    .s("pipeline", "mul_mat_f32").n("x", 1).n("y", 1).n("z", 1).emit();
            }
            if (mode == "early-completion") I280_EVENT("complete").s("ctx", ctx).s("wait", "fence").emit();
            I280_EVENT("submit").s("subctx", "sub" + std::to_string(d)).s("cmd", cmd).n("use", g+1).emit();
            if (mode == "abort") return 0; // raw partial recording, not success
            if (native) {
                I280_EVENT("event_record").s("ctx", ctx).s("sync_event", "ev" + std::to_string(d)).n("value", g+1).emit();
                I280_EVENT("event_complete").s("sync_event", "ev" + std::to_string(d)).n("value", mode == "timeline-stale" ? g+2 : g+1).emit();
            } else if (mode != "missing-completion") I280_EVENT("complete").s("ctx", ctx).s("wait", "fence").emit();
            I280_EVENT("vk_graph_end").s("ctx", ctx).emit();
        }
        I280_EVENT("graph_end").s("graph", "g").n("status", 0).emit();
        if (!(micro && g == 0)) {
            I280_EVENT("batch_end").n("status", 0).emit();
            I280_EVENT("sample").n("request", mode == "wrong-request" ? 8 : 7).n("position", micro ? g-1 : g)
                .n("eos", g == graphs-1 && mode != "limit" ? 1 : 0).emit();
        }
    }
    I280_EVENT("response").n("request", 7).n("sampled", mode == "wrong-output" ? graphs+1 : micro ? graphs-1 : graphs)
        .n("prompt_processed", 4).n("prompt_cached", 0).n("eos", mode == "limit" ? 0 : 1).emit();
}
