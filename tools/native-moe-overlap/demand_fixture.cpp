// Small synthetic router fixture: exercises the exact capture/export used by the CLI.
#include "demand.h"
#include <cstring>
#include <iostream>
#include <string>

namespace {
struct source { const int32_t * ids; size_t bytes; size_t read_bytes = 0; };
void read(void * opaque, void * dst, size_t offset, size_t bytes) {
    auto & s = *static_cast<source *>(opaque);
    if (offset + bytes > s.bytes) throw std::runtime_error("fixture read outside argsort");
    std::memcpy(dst, reinterpret_cast<const char *>(s.ids) + offset, bytes);
    s.read_bytes += bytes;
}
bool registered(ggml_tensor *, bool, void *) { return true; }
bool unrelated(ggml_tensor *, bool, void *) { return true; }
}

int main(int argc, char ** argv) {
    if (argc != 2) return 2;
    const std::string mode = argv[1];
    if (mode == "off") {
        const int32_t ids[] = {0, 1, 2, 3};
        source s{ids, sizeof(ids)};
        const bool ask = is312::observe_argsort(is312::active(), "ffn_moe_argsort-0", true,
                                               true, 4, 1, 4, 16, read, &s);
        const bool after = is312::observe_argsort(is312::active(), "ffn_moe_argsort-0", false,
                                                 true, 4, 1, 4, 16, read, &s);
        std::cout << "{\"active\":" << (ask || s.read_bytes ? "true" : "false")
                  << ",\"rows\":" << s.read_bytes / (2 * sizeof(int32_t)) << "}\n";
        return 0;
    }
    is312::identity id{"qwen3.8", "r38", std::string(64, 'a'), "Q8",
        "b29c606e28a01b1bc8c1351026a0fa6e616bf6c4", std::string(64, 'b'),
        std::string(64, 'c'), "profiling", "synthetic", "cpu", "fixture",
        "Synthetic GGUF", "15", "qwen4exp"};
    if (mode == "callback-identity") {
        is312::capture guard(id, 1, 4, 2, 2);
        is312::set_dedicated_callback(registered);
        const bool off_refused = !is312::dedicated_callback(registered);
        is312::set_active(&guard);
        const bool other_refused = !is312::dedicated_callback(unrelated);
        const bool dedicated_accepted = is312::dedicated_callback(registered);
        is312::set_active(nullptr);
        std::cout << "{\"off_refused\":" << (off_refused ? "true" : "false")
                  << ",\"other_refused\":" << (other_refused ? "true" : "false")
                  << ",\"dedicated_accepted\":" << (dedicated_accepted ? "true" : "false") << "}\n";
        return 0;
    }
    if (mode == "large") {
        is312::capture big(id, 48, 4, 2, 700);
        const int32_t ids[] = {1, 3, 0, 2};
        source s{ids, sizeof(ids)};
        for (unsigned step = 0; step < 13; ++step) {
            big.begin(step == 0 ? "prefill" : "decode", step, 1);
            for (unsigned layer = 0; layer < 48; ++layer)
                if (!is312::observe_argsort(&big, ("ffn_moe_argsort-" + std::to_string(layer)).c_str(),
                                            false, true, 4, 1, 4, 16, read, &s)) return 3;
        }
        std::cout << big.export_json() << '\n';
        return 0;
    }
    if (mode == "adapter") {
        is312::capture adapter(id, 1, 4, 2, 4);
        const int32_t argsort[] = {1,3,0,2, 0,2,3,1, 2,1,0,3};
        const int32_t decode[] = {3,0,2,1};
        source s{argsort, sizeof(argsort)};
        adapter.begin("prefill", 0, 3);
        const bool ignored = !is312::observe_argsort(&adapter, "ffn_moe_topk-0", true, true, 4, 3, 4, 16, read, &s)
            && is312::observe_argsort(&adapter, "unrelated", false, true, 4, 3, 4, 16, read, &s);
        const bool first = is312::observe_argsort(&adapter, "ffn_moe_argsort-0", true, true, 4, 3, 4, 16, read, &s)
            && is312::observe_argsort(&adapter, "ffn_moe_argsort-0", false, true, 4, 3, 4, 16, read, &s);
        adapter.begin("decode", 1, 1);
        source d{decode, sizeof(decode)};
        const bool second = is312::observe_argsort(&adapter, "ffn_moe_argsort-0", false, true, 4, 1, 4, 16, read, &d);
        is312::capture invalid(id, 1, 4, 2, 4);
        invalid.begin("prefill", 0, 1);
        const bool shape_failed = !is312::observe_argsort(&invalid, "ffn_moe_argsort-0", false, true, 4, 1, 4, 8, read, &d)
            && !invalid.error().empty();
        is312::capture bad_type(id, 1, 4, 2, 4);
        bad_type.begin("prefill", 0, 1);
        const bool type_failed = !is312::observe_argsort(&bad_type, "ffn_moe_argsort-0", false,
                                                         false, 4, 1, 4, 16, read, &d) && !bad_type.error().empty();
        is312::capture bad_layer(id, 1, 4, 2, 4);
        bad_layer.begin("prefill", 0, 1);
        const bool layer_failed = !is312::observe_argsort(&bad_layer, "ffn_moe_argsort-1", false,
                                                          true, 4, 1, 4, 16, read, &d) && !bad_layer.error().empty();
        const bool unchanged = argsort[0] == 1 && argsort[1] == 3 && decode[0] == 3;
        const bool output_equal = (argsort[0] * 2 + argsort[1] * 3) == 11;
        std::string result = adapter.export_json();
        result.pop_back();
        std::cout << result << ",\"read_bytes\":" << s.read_bytes + d.read_bytes
                  << ",\"nonmatching_ignored\":" << (ignored ? "true" : "false")
                  << ",\"ids_unchanged\":" << (unchanged ? "true" : "false")
                  << ",\"output_equal\":" << (first && second && output_equal ? "true" : "false")
                  << ",\"shape_failed\":" << (shape_failed ? "true" : "false")
                  << ",\"type_failed\":" << (type_failed ? "true" : "false")
                  << ",\"layer_failed\":" << (layer_failed ? "true" : "false") << "}\n";
        return 0;
    }
    if (mode == "cost-budget") {
        is312::capture limited(id, 2, 4, 2, 2, 620);
        limited.begin("prefill", 0, 1);
        const int32_t ids[] = {1, 3};
        limited.record(0, ids, 2, 1, 0.125);
        limited.record_cost(0, {0.25, 0.5, 0.75, 64, 32, 64});
        std::cout << limited.export_json() << '\n';
        return 0;
    }
    is312::capture cap(id, 2, 4, 2, mode == "bounded" ? 1 : 16,
                       mode == "byte-budget" ? 620 : 8 * 1024 * 1024);
    is312::set_active(&cap);
    cap.begin("prefill", 0, 1); // phase is explicit; one-token prefill is not decode
    const int32_t first[] = {1, 3};
    cap.record(0, first, 2, 1, 0.125);
    if (mode == "costs") {
        cap.record_cost(0, {0.25, 0.5, 0.75, 64, 32, 64});
        is312::set_active(nullptr);
        std::cout << cap.export_json() << '\n';
        return 0;
    }
    if (mode == "integrity") {
        // The caller's selected-ID buffer and its scalar downstream result
        // are read-only across the actual collector call.
        const int32_t expected_ids[] = {1, 3};
        const float reference = float(expected_ids[0] * 2 + expected_ids[1] * 3) + 0.25f;
        const float after = float(first[0] * 2 + first[1] * 3) + 0.25f;
        is312::set_active(nullptr);
        std::cout << "{\"ids_unchanged\":" << (first[0] == 1 && first[1] == 3 ? "true" : "false")
                  << ",\"output_equal\":" << (reference == after ? "true" : "false") << "}\n";
        return 0;
    }
    if (mode != "bounded") {
        const int32_t second[] = {2, 3};
        cap.record(1, second, 2, 1, 0.25);
    }
    cap.begin("decode", 1, 1);
    const int32_t third[] = {2, 1};
    cap.record(0, third, 2, 1, 0.5);
    if (mode == "bounded") {
        const int32_t fourth[] = {1, 2};
        cap.record(1, fourth, 2, 1, 0.5);
    } else {
        const int32_t fourth[] = {0, 3};
        cap.record(1, fourth, 2, 1, 0.5);
    }
    if (mode == "repeated-steps") {
        cap.begin("decode", 2, 1);
        cap.record(0, third, 2, 1, 0.5);
        const int32_t repeat_other[] = {0, 3};
        cap.record(1, repeat_other, 2, 1, 0.5);
    }
    is312::set_active(nullptr);
    if (mode == "repeat") {
        std::cout << "{\"identical\":" << (cap.export_json() == cap.export_json() ? "true" : "false") << "}\n";
    } else {
        std::cout << cap.export_json() << '\n';
    }
}
