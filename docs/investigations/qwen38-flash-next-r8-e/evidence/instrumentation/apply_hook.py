#!/usr/bin/env python3
"""Apply the R8-E observation-only hook to llama.cpp server-context.cpp
(Issue #199). Idempotent: refuses to apply twice."""
import sys

p = "tools/server/server-context.cpp"
src = open(p).read()
if "r8e_observe_logits" in src:
    print("already patched")
    sys.exit(1)

hook = """
#include <cstdlib>
#include <cmath>
#include <sstream>
#include <iomanip>

// R8-E observation-only hook (Issue #199). Inert unless
// LLAMA_OBSERVE_LOGITS is set. Reads the logits row the sampler just
// consumed; performs no llama/ggml state writes.
static void r8e_observe_logits(struct llama_context * ctx, const int idx,
                               const int gen_pos, const llama_token tok) {
    const char * out_path = std::getenv("LLAMA_OBSERVE_LOGITS");
    if (!out_path || !out_path[0]) { return; }
    const float * logits;
    try {
        logits = llama_get_logits_ith(ctx, idx);
    } catch (...) { return; }
    if (!logits) { return; }
    const int n_vocab = llama_vocab_n_tokens(llama_model_get_vocab(llama_get_model(ctx)));

    std::vector<int> order(n_vocab);
    for (int i = 0; i < n_vocab; i++) { order[i] = i; }
    std::stable_sort(order.begin(), order.end(), [&](int a, int b) {
        const float la = logits[a], lb = logits[b];
        if (!std::isfinite(la) || !std::isfinite(lb)) { return a < b; }
        if (la != lb) { return la > lb; }
        return a < b;
    });

    std::vector<int> focus;
    if (const char * f = std::getenv("LLAMA_OBSERVE_FOCUS")) {
        std::istringstream is(f);
        std::string item;
        while (std::getline(is, item, ',')) {
            try { focus.push_back(std::stoi(item)); } catch (...) {}
        }
    }

    std::ostringstream o;
    o << std::setprecision(9);
    o << "{\\"pos\\": " << gen_pos << ", \\"tok\\": " << tok
      << ", \\"n_vocab\\": " << n_vocab << ", \\"top\\": [";
    for (int k = 0; k < 16 && k < n_vocab; k++) {
        if (k) { o << ", "; }
        o << "[" << order[k] << ", " << logits[order[k]] << "]";
    }
    o << "], \\"focus\\": [";
    bool first = true;
    for (int t : focus) {
        if (t < 0 || t >= n_vocab) { continue; }
        int rank = -1;
        for (int k = 0; k < n_vocab; k++) {
            if (order[k] == t) { rank = k + 1; break; }
        }
        if (!first) { o << ", "; }
        first = false;
        o << "[" << t << ", " << rank << ", " << logits[t] << "]";
    }
    long n_nf = 0;
    for (int i = 0; i < n_vocab; i++) {
        if (!std::isfinite((double) logits[i])) { n_nf++; }
    }
    o << "], \\"n_nonfinite\\": " << n_nf << "}\\n";
    { std::ofstream f(out_path, std::ios::app); f << o.str(); }

    // retain the exact float32 logits row bytes at the requested position
    if (const char * p = std::getenv("LLAMA_OBSERVE_POS")) {
        try {
            if (std::stoi(p) == gen_pos) {
                std::string tmp = std::string(out_path) + ".pos" +
                                  std::to_string(gen_pos) + ".f32.tmp";
                std::string dst = std::string(out_path) + ".pos" +
                                  std::to_string(gen_pos) + ".f32";
                { std::ofstream f(tmp, std::ios::binary);
                  f.write((const char *) logits,
                          (std::streamsize) n_vocab * sizeof(float)); }
                std::filesystem::rename(tmp, dst);
            }
        } catch (...) {}
    }
}
"""

anchor = "#include <fstream>\n"
assert src.count(anchor) == 1
src = src.replace(anchor, anchor + hook, 1)

anchor2 = "                id = common_sampler_sample(slot.smpl.get(), slot.ctx_tgt, tok_idx);\n"
assert src.count(anchor2) == 1
src = src.replace(anchor2, anchor2 + """                // R8-E observation-only (Issue #199): reads the same
                // logits row the sampler consumed; no state writes.
                r8e_observe_logits(slot.ctx_tgt, tok_idx,
                                   (int) slot.stats.n_gen, id);
""", 1)

open(p, "w").write(src)
print("patched OK")
