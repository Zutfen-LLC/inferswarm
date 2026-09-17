#!/usr/bin/env python3
"""Apply the R8-G observation-only hooks to llama.cpp server-context.cpp
(Issue #207). Idempotent: refuses to apply twice.

Two hooks, both INERT unless their env vars are set:

1. r8g_observe_logits — IDENTICAL semantics to the accepted R8-E hook
   (reads the logits row the sampler just consumed at the sampling seam;
   no llama/ggml state writes). Retained for the non-perturbation and
   seam-anchor byte cross-checks against the accepted R8-E rows.

2. r8g_boundary_observer — registers the NATIVE scheduler eval callback
   (params_base.cb_eval; the seam wired common_context_params_to_llama ->
   llama_context (src/llama-context.cpp:1365) -> ggml_backend_sched_set_
   eval_callback). Observation only:
     - ask phase: returns true only for nodes whose runtime name is in
       the frozen name set parsed from LLAMA_OBSERVE_BOUNDARIES (format
       "name:tokdim;name:tokdim;..." — tokdim is the tensor dimension
       index holding the token axis, used only for the frozen column
       extraction rule below). The scheduler therefore syncs only at
       observation points; every other node is computed in the same
       grouped contiguous ranges as an uninstrumented run.
     - tell phase (post ggml_backend_synchronize): reads the node bytes
       via ggml_backend_tensor_get (documented read path; no writes, no
       placement/split input), extracts the LAST-TOKEN COLUMN along
       tokdim (the frozen bounded representation: for decode graphs
       (ne[tokdim]==1) this is the whole tensor; for prefill graphs it
       is the final prompt position's state — exactly the state that
       flows into the first generated token), and appends one JSONL row
       to $LLAMA_OBSERVE_BOUNDARY_JSONL:
         {name, seq (per-process occurrence counter for this name),
          type, ne, nbytes, tokdim, ntok (ne[tokdim]), col_nbytes,
          sha256 (over the column bytes), n_nonfinite (column floats),
          noncontig}
       plus a raw f32 sidecar $LLAMA_OBSERVE_BOUNDARY_OUT/<safe>__<seq>.f32
       (temp+rename) holding the column bytes.
   Graph-execution binding (which occurrence is prefill vs decode step k)
   is done by the Python capture producer from the retained rows +
   response tokens, NOT by the hook: the hook only counts occurrences.

The column-extraction rule and the name set are frozen prospectively in
the campaign authority BEFORE any physical observation.
"""
import sys

p = "tools/server/server-context.cpp"
src = open(p).read()
if "r8g_boundary_observer" in src:
    print("already patched")
    sys.exit(1)

hook = r"""
#include <cstdlib>
#include <cmath>
#include <cstring>
#include <sstream>
#include <iomanip>
#include <cstdint>
#include <map>
#include <filesystem>

// R8-E-compatible sampling-seam hook (Issue #199 semantics, retained for
// the R8-G non-perturbation/seam-anchor cross-checks). Inert unless
// LLAMA_OBSERVE_LOGITS is set. Reads the logits row the sampler just
// consumed; performs no llama/ggml state writes.
static void r8g_observe_logits(struct llama_context * ctx, const int idx,
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
    o << "{\"pos\": " << gen_pos << ", \"tok\": " << tok
      << ", \"n_vocab\": " << n_vocab << ", \"top\": [";
    for (int k = 0; k < 16 && k < n_vocab; k++) {
        if (k) { o << ", "; }
        o << "[" << order[k] << ", " << logits[order[k]] << "]";
    }
    o << "], \"focus\": [";
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
    o << "], \"n_nonfinite\": " << n_nf << "}\n";
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

// R8-G boundary observer (Issue #207): native scheduler eval-callback
// seam; observation only. ask=true -> membership in the frozen name set;
// ask=false (post-compute, post-synchronize) -> read the node bytes,
// extract the frozen last-token column, emit a JSONL row + raw f32
// sidecar. No writes to any ggml/llama state, no placement input.
static bool r8g_boundary_observer(struct ggml_tensor * t, bool ask,
                                  void * user_data) {
    const char * spec = std::getenv("LLAMA_OBSERVE_BOUNDARIES");
    const char * out_dir = std::getenv("LLAMA_OBSERVE_BOUNDARY_OUT");
    const char * jsonl = std::getenv("LLAMA_OBSERVE_BOUNDARY_JSONL");
    if (!spec || !spec[0] || !out_dir || !out_dir[0] || !jsonl || !jsonl[0]) {
        return false;  // observe nothing, continue execution
    }
    static std::map<std::string, int> frozen_dims;
    static std::map<std::string, int> seen_counts;
    static bool frozen_parsed = false;
    if (!frozen_parsed) {
        std::istringstream is(spec);
        std::string item;
        while (std::getline(is, item, ';')) {
            const auto colon = item.rfind(':');
            if (colon == std::string::npos || colon == 0 ||
                colon + 1 >= item.size()) {
                continue;
            }
            try {
                frozen_dims[item.substr(0, colon)] =
                    std::stoi(item.substr(colon + 1));
            } catch (...) {}
        }
        std::filesystem::create_directories(out_dir);
        frozen_parsed = true;
    }
    const std::string name(t->name);
    const auto fd = frozen_dims.find(name);
    if (fd == frozen_dims.end()) {
        return ask ? false : true;
    }
    const int d = fd->second < 0 || fd->second > 3 ? 0 : fd->second;
    // occurrence ordinal, 0-based: the scheduler invokes ask=true exactly
    // once per node; ask=false only follows an ask=true that returned
    // true, for the SAME node — count only at ask=true.
    if (ask) {
        const int seq = seen_counts[name]++;
        (void) seq;
        return true;   // scheduler syncs at every occurrence of a wanted name
    }
    const int seq = seen_counts[name] - 1;

    // tell phase: read the node's bytes (post-synchronize)
    const size_t nbytes = ggml_nbytes(t);
    const size_t es = ggml_type_size(t->type);
    const int64_t ntok_i = t->ne[d];
    const size_t nelem = (size_t) t->ne[0] * t->ne[1] * t->ne[2] * t->ne[3];
    const bool noncontig = (nelem * es != nbytes) || (ntok_i <= 0);
    const int64_t ntok = ntok_i > 0 ? ntok_i : 0;
    std::vector<uint8_t> buf(nbytes);
    if (nbytes > 0) {
        ggml_backend_tensor_get(t, buf.data(), 0, nbytes);
    }

    std::vector<uint8_t> col;
    bool col_ok = !noncontig;
    if (col_ok) {
        // last-token column: iterate every coordinate with dim d fixed at
        // ntok-1, free dims in element order (dim0 fastest)
        const int64_t n_[4] = {t->ne[0], t->ne[1], t->ne[2], t->ne[3]};
        int64_t idx[4] = {0, 0, 0, 0};
        idx[d] = n_[d] - 1;
        const int64_t col_elems = nelem / n_[d];
        col.resize(col_elems * es);
        int order3[3];
        int m = 0;
        for (int k = 0; k < 4; ++k) { if (k != d) { order3[m++] = k; } }
        int64_t out = 0;
        for (;;) {
            const int64_t off = idx[0] + n_[0] * (idx[1] + n_[1] * (idx[2] + n_[2] * idx[3]));
            memcpy(&col[out * es], &buf[off * es], es);
            ++out;
            int k;
            for (k = 2; k >= 0; --k) {
                const int cd = order3[k];
                if (++idx[cd] < n_[cd]) { break; }
                idx[cd] = 0;
            }
            if (k < 0) { break; }
        }
        if ((size_t) out != (size_t) col_elems) { col_ok = false; }
    }

    // sha256 (self-contained, public-domain style)
    std::string digest = "NA";
    long n_nf = -1;
    if (col_ok) {
        static const uint32_t K[64] = {
            0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,
            0x923f82a4,0xab1c5ed5,0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,
            0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,0xe49b69c1,0xefbe4786,
            0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,
            0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,
            0x06ca6351,0x14292967,0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,
            0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,0xa2bfe8a1,0xa81a664b,
            0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,
            0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,
            0x5b9cca4f,0x682e6ff3,0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,
            0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2};
        uint32_t h[8] = {0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,
                         0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19};
        auto rotr = [](uint32_t x, int n) { return (x >> n) | (x << (32 - n)); };
        const size_t total = col.size();
        std::vector<uint8_t> msg(col);
        msg.push_back(0x80);
        while (msg.size() % 64 != 56) { msg.push_back(0); }
        uint64_t bits = (uint64_t) total * 8;
        for (int i = 7; i >= 0; --i) { msg.push_back((uint8_t)(bits >> (i * 8))); }
        for (size_t off = 0; off < msg.size(); off += 64) {
            uint32_t w[64];
            for (int i = 0; i < 16; ++i) {
                w[i] = ((uint32_t) msg[off + i * 4] << 24) |
                       ((uint32_t) msg[off + i * 4 + 1] << 16) |
                       ((uint32_t) msg[off + i * 4 + 2] << 8) |
                       ((uint32_t) msg[off + i * 4 + 3]);
            }
            for (int i = 16; i < 64; ++i) {
                const uint32_t s0 = rotr(w[i-15],7) ^ rotr(w[i-15],18) ^ (w[i-15] >> 3);
                const uint32_t s1 = rotr(w[i-2],17) ^ rotr(w[i-2],19) ^ (w[i-2] >> 10);
                w[i] = w[i-16] + s0 + w[i-7] + s1;
            }
            uint32_t a=h[0],b=h[1],c=h[2],dd=h[3],e=h[4],f=h[5],g=h[6],hh=h[7];
            for (int i = 0; i < 64; ++i) {
                const uint32_t S1 = rotr(e,6) ^ rotr(e,11) ^ rotr(e,25);
                const uint32_t ch = (e & f) ^ (~e & g);
                const uint32_t t1 = hh + S1 + ch + K[i] + w[i];
                const uint32_t S0 = rotr(a,2) ^ rotr(a,13) ^ rotr(a,22);
                const uint32_t maj = (a & b) ^ (a & c) ^ (b & c);
                const uint32_t t2 = S0 + maj;
                hh=g; g=f; f=e; e=dd+t1; dd=c; c=b; b=a; a=t1+t2;
            }
            h[0]+=a; h[1]+=b; h[2]+=c; h[3]+=dd; h[4]+=e; h[5]+=f; h[6]+=g; h[7]+=hh;
        }
        std::ostringstream hs;
        for (int i = 0; i < 8; ++i) { hs << std::hex << std::setw(8) << std::setfill('0') << h[i]; }
        digest = hs.str();

        n_nf = 0;
        const size_t nf = col.size() / sizeof(float);
        const float * fv = (const float *) col.data();
        for (size_t i = 0; i < nf; ++i) {
            if (!std::isfinite((double) fv[i])) { n_nf++; }
        }

        std::string safe = name;
        for (auto & c : safe) {
            if (!std::isalnum((unsigned char) c) && c != '.' && c != '-' &&
                c != '_') { c = '_'; }
        }
        const std::string base = std::string(out_dir) + "/" + safe + "__" +
                                 std::to_string(seq);
        std::string tmp = base + ".f32.tmp";
        { std::ofstream f(tmp, std::ios::binary);
          f.write((const char *) col.data(), (std::streamsize) col.size()); }
        std::filesystem::rename(tmp, base + ".f32");
    }

    {
        std::ostringstream o;
        o << "{\"name\": \"" << name << "\", \"seq\": " << seq
          << ", \"type\": \"" << ggml_type_name(t->type)
          << "\", \"ne\": [" << t->ne[0] << ", " << t->ne[1] << ", "
          << t->ne[2] << ", " << t->ne[3] << "]"
          << ", \"nbytes\": " << nbytes
          << ", \"tokdim\": " << d
          << ", \"ntok\": " << ntok
          << ", \"col_nbytes\": " << (col_ok ? col.size() : 0)
          << ", \"sha256\": \"" << digest << "\""
          << ", \"n_nonfinite\": " << n_nf
          << ", \"noncontig\": " << (noncontig ? "true" : "false")
          << "}\n";
        { std::ofstream f(jsonl, std::ios::app); f << o.str(); }
    }
    return true;
}
"""

anchor = "#include <fstream>\n"
assert src.count(anchor) == 1
src = src.replace(anchor, anchor + hook, 1)

anchor2 = "        llama_init = common_init_from_params(params_base);\n"
assert src.count(anchor2) == 1
src = src.replace(anchor2, """        // R8-G observation-only (Issue #207): register the NATIVE
        // scheduler eval callback when boundary observation is enabled.
        // Inert unless LLAMA_OBSERVE_BOUNDARIES is set (the observer
        // returns false at ask for every node when its env is absent).
        if (std::getenv("LLAMA_OBSERVE_BOUNDARIES") != nullptr) {
            params_base.cb_eval = r8g_boundary_observer;
        }
""" + anchor2, 1)

anchor3 = "                id = common_sampler_sample(slot.smpl.get(), slot.ctx_tgt, tok_idx);\n"
assert src.count(anchor3) == 1
src = src.replace(anchor3, anchor3 + """                // R8-E-compatible sampling-seam observation (Issue #207
                // retains the accepted hook semantics; reads the same
                // logits row the sampler consumed; no state writes).
                r8g_observe_logits(slot.ctx_tgt, tok_idx,
                                   (int) slot.stats.n_gen, id);
""", 1)

open(p, "w").write(src)
print("patched OK")
