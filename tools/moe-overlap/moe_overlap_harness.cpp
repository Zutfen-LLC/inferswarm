// moe_overlap_harness.cpp — resident MoE block scheduling-overlap prototype.
//
// Purpose (prototype only; no engine, loader, protocol or kernel is added):
//   Measure whether overlapping CPU expert computation, GPU expert computation
//   and activation transfers reduces one representative qwen4exp MoE FFN
//   block's critical-path latency, compared with a strictly serialized
//   execution of the same math on the same resident weights.
//
// Reused execution path (llama.cpp pin b29c606e28a01b1bc8c1351026a0fa6e616bf6c4):
//   - gguf.h selective header parsing + targeted tensor reads (bounded read of
//     only the eight block tensors; no full-shard load);
//   - ggml CPU + (optional) CUDA backends and their existing kernels:
//     MUL_MAT (F32 router / shared expert / shared gate), MUL_MAT_ID (Q8_0
//     expert banks, including the CUDA fused up+gate+GLU MoE path), SOFT_MAX,
//     ARGSORT_TOP_K, GET_ROWS, SWIGLU_SPLIT, SIGMOID, SUM_ROWS, CLAMP, DIV;
//   - the exact op sequence of llm_graph_context::build_moe_ffn for the
//     qwen4exp configuration (softmax gating, top-10, normalized selected
//     weights applied after the down projection, plane-order expert sum) and
//     llama_model_qwen4exp::graph::build_layer_ffn's shared-expert branch.
//
// Both arms use identical weights, inputs, routing decisions (computed once per
// repetition by the same router graph and then shared), device ownership,
// kernels, precision and expert work. No expert skipping or approximation
// exists in this harness: every router-selected expert (normal cardinality
// 10 of 512) and the shared expert execute in both arms, and the per-repetition
// assertion routed_total == N_USED * n_tokens fails closed otherwise. Only the
// schedule differs:
//
//   serial    : every stage is fully synchronized before the next begins
//               (blocking input sets, compute, synchronize, blocking reads).
//   overlapped: activation H2D sets, the secondary-device expert graph and the
//               D2H read are enqueued on the secondary backend's stream via
//               ggml_backend_tensor_set_async / ggml_backend_graph_compute_async /
//               ggml_backend_tensor_get_async; the CPU-backend expert and
//               shared graphs run concurrently on the host threadpool; one
//               final ggml_backend_synchronize joins the streams. Submission is
//               only called "overlapped" because this ordering genuinely allows
//               concurrent execution; dependencies stay ordered because the
//               copies, kernels and read-back share one device stream.
//
// See tools/moe-overlap/README.md for the full contract, tolerances and limits.

#include "ggml.h"
#include "ggml-alloc.h"
#include "ggml-backend.h"
#include "ggml-cpu.h"
#include "gguf.h"

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cinttypes>
#include <iostream>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <limits>
#include <memory>
#include <random>
#include <string>
#include <thread>
#include <vector>
#include <sys/stat.h>

// ---------------------------------------------------------------------------
// Authentic qwen4exp Q8_0 block geometry (authenticated #299 census:
// tests/fixtures/issue299/q8-metadata.json; general.architecture = qwen4exp).
// ggml ne order at this pin is k-major: contraction over ne[0].
// ---------------------------------------------------------------------------
static const int64_t N_EMBD = 2560; // qwen4exp.embedding_length
static const int64_t N_FF   = 640;  // expert_feed_forward_length (== shared)
static const int64_t N_USED = 10;   // expert_used_count
static const int64_t N_EXPERT_AUTHENTIC = 512;
static const float WEIGHT_CLAMP_MIN = 6.103515625e-5f; // f16 smallest, as in llama.cpp norm_w path

static double now_ms() {
    return std::chrono::duration<double, std::milli>(
        std::chrono::steady_clock::now().time_since_epoch()).count();
}

static uint64_t mix64(uint64_t x) { // splitmix64 finalizer, for seed derivation
    x += 0x9e3779b97f4a7c15ULL;
    x = (x ^ (x >> 30)) * 0xbf58476d1ce4e5b9ULL;
    x = (x ^ (x >> 27)) * 0x94d049bb133111ebULL;
    return x ^ (x >> 31);
}

// Deterministic PRNG (std::mt19937_64 is fully specified by the standard;
// library distributions are not, so normals are Box-Muller on raw doubles).
struct PRNG {
    std::mt19937_64 eng;
    double spare = 0.0;
    bool has_spare = false;
    explicit PRNG(uint64_t seed) : eng(seed) {}
    double unit() { return (double)((eng() >> 11) * (1.0 / 9007199254740992.0)); }
    double normal() {
        if (has_spare) { has_spare = false; return spare; }
        double u1 = unit(), u2 = unit();
        if (u1 < 1e-300) u1 = 1e-300;
        double r = std::sqrt(-2.0 * std::log(u1));
        spare = r * std::sin(2.0 * M_PI * u2);
        has_spare = true;
        return r * std::cos(2.0 * M_PI * u2);
    }
};

// Minimal JSON emission (no dependencies). obj()/end() open an object at the
// current position (usable both as a named member and as an array element).
struct JsonOut {
    std::string s;
    std::vector<bool> stack;
    bool first = true;
    void sep() { if (!first) s += ","; first = false; }
    void key(const char * k) { sep(); s += "\""; s += k; s += "\":"; }
    void obj() { sep(); s += "{"; stack.push_back(first); first = true; }
    void begin(const char * k) { key(k); s += "{"; stack.push_back(false); first = true; }
    void begin_arr(const char * k) { key(k); s += "["; stack.push_back(false); first = true; }
    void end() { s += "}"; first = stack.back(); stack.pop_back(); }
    void end_arr() { s += "]"; first = stack.back(); stack.pop_back(); }
    void str(const char * k, const std::string & v) {
        key(k); s += "\"";
        for (char c : v) {
            if (c == '"' || c == '\\') { s += '\\'; s += c; }
            else if ((unsigned char)c < 0x20) { char b[8]; snprintf(b, sizeof b, "\\u%04x", c); s += b; }
            else s += c;
        }
        s += "\"";
    }
    void num(const char * k, double v) {
        key(k);
        if (std::isnan(v) || std::isinf(v)) { s += "null"; return; }
        char b[40];
        if (v == (double)(int64_t)v && std::fabs(v) < 9.0e15) snprintf(b, sizeof b, "%lld", (long long)v);
        else snprintf(b, sizeof b, "%.10g", v);
        s += b;
    }
    void boolean(const char * k, bool v) { key(k); s += v ? "true" : "false"; }
};

// ---------------------------------------------------------------------------
// Host-side weight store.
//   SYNTHETIC mode: deterministic F32 draws quantized through ggml's own Q8_0
//   quantizer (ggml_quantize_chunk). All outputs label this mode SYNTHETIC.
//   GGUF mode: header parsed with no_alloc (metadata only), then exactly the
//   eight block tensors are read from one shard (bounded selective read).
// ---------------------------------------------------------------------------
struct Weights {
    int64_t n_expert = N_EXPERT_AUTHENTIC;
    std::vector<uint8_t> store;
    ggml_context * ctx = nullptr;
    ggml_tensor * router = nullptr;    // F32 [N_EMBD, n_expert]
    ggml_tensor * sh_gate_w = nullptr; // F32 [N_EMBD]
    ggml_tensor * up = nullptr;        // Q8_0 [N_EMBD, N_FF, n_expert]
    ggml_tensor * gate = nullptr;      // Q8_0 [N_EMBD, N_FF, n_expert]
    ggml_tensor * down = nullptr;      // Q8_0 [N_FF, N_EMBD, n_expert]
    ggml_tensor * sh_up = nullptr;     // Q8_0 [N_EMBD, N_FF]
    ggml_tensor * sh_gate = nullptr;   // Q8_0 [N_EMBD, N_FF]
    ggml_tensor * sh_down = nullptr;   // Q8_0 [N_FF, N_EMBD]

    void create_tensors() {
        size_t meta = ggml_tensor_overhead() * 10 + 256;
        struct ggml_init_params ip = { meta, nullptr, /*no_alloc =*/ true };
        ctx = ggml_init(ip);
        auto q = [&](const char * n, int64_t ne0, int64_t ne1, int64_t ne2, uint8_t * p) {
            ggml_tensor * t = ne2
                ? ggml_new_tensor_3d(ctx, GGML_TYPE_Q8_0, ne0, ne1, ne2)
                : ggml_new_tensor_2d(ctx, GGML_TYPE_Q8_0, ne0, ne1);
            ggml_set_name(t, n);
            t->data = p;
            return t;
        };
        router    = ggml_new_tensor_2d(ctx, GGML_TYPE_F32, N_EMBD, n_expert);
        sh_gate_w = ggml_new_tensor_1d(ctx, GGML_TYPE_F32, N_EMBD);
        ggml_set_name(router,    "ffn_gate_inp.weight");
        ggml_set_name(sh_gate_w, "ffn_gate_inp_shexp.weight");
        size_t row_e = ggml_row_size(GGML_TYPE_Q8_0, (size_t)N_EMBD);
        size_t row_f = ggml_row_size(GGML_TYPE_Q8_0, (size_t)N_FF);
        uint8_t * p = store.data();
        up       = q("ffn_up_exps.weight",   N_EMBD, N_FF, n_expert, p); p += row_e * (size_t)(N_FF * n_expert);
        gate     = q("ffn_gate_exps.weight", N_EMBD, N_FF, n_expert, p); p += row_e * (size_t)(N_FF * n_expert);
        down     = q("ffn_down_exps.weight", N_FF, N_EMBD, n_expert, p); p += row_f * (size_t)(N_EMBD * n_expert);
        sh_up    = q("ffn_up_shexp.weight",   N_EMBD, N_FF, 0, p); p += row_e * (size_t)N_FF;
        sh_gate  = q("ffn_gate_shexp.weight", N_EMBD, N_FF, 0, p); p += row_e * (size_t)N_FF;
        sh_down  = q("ffn_down_shexp.weight", N_FF, N_EMBD, 0, p); p += row_f * (size_t)N_EMBD;
        router->data    = p;
        sh_gate_w->data = p + sizeof(float) * (size_t)(N_EMBD * n_expert);
    }

    bool fill_synthetic(int64_t n_exp, uint64_t seed) {
        n_expert = n_exp;
        size_t row_e = ggml_row_size(GGML_TYPE_Q8_0, (size_t)N_EMBD);
        size_t row_f = ggml_row_size(GGML_TYPE_Q8_0, (size_t)N_FF);
        size_t total = row_e * (size_t)(N_FF * n_expert) * 2
                     + row_f * (size_t)(N_EMBD * n_expert)
                     + row_e * (size_t)N_FF * 2
                     + row_f * (size_t)N_EMBD
                     + sizeof(float) * (size_t)(N_EMBD * n_expert + N_EMBD);
        store.assign(total, 0);
        create_tensors();

        ggml_quantize_init(GGML_TYPE_Q8_0);
        std::vector<float> buf;
        auto quant = [&](ggml_tensor * t, int64_t rows, int64_t per_row, uint64_t useed) {
            buf.assign((size_t)(rows * per_row), 0.0f);
            PRNG g(useed);
            double scale = 1.0 / std::sqrt((double)per_row);
            for (auto & v : buf) v = (float)(g.normal() * scale);
            ggml_quantize_chunk(GGML_TYPE_Q8_0, buf.data(), t->data, 0, rows, per_row, nullptr);
        };
        quant(up,     N_FF * n_expert, N_EMBD, mix64(seed ^ 0xA1));
        quant(gate,   N_FF * n_expert, N_EMBD, mix64(seed ^ 0xB2));
        quant(down,   N_EMBD * n_expert, N_FF, mix64(seed ^ 0xC3));
        quant(sh_up,   N_FF, N_EMBD, mix64(seed ^ 0xD4));
        quant(sh_gate, N_FF, N_EMBD, mix64(seed ^ 0xE5));
        quant(sh_down, N_EMBD, N_FF, mix64(seed ^ 0xF6));
        PRNG gr(mix64(seed ^ 0x07));
        for (int64_t i = 0; i < N_EMBD * n_expert; ++i)
            ((float *)router->data)[i] = (float)(gr.normal() / std::sqrt((double)N_EMBD));
        PRNG gs(mix64(seed ^ 0x18));
        for (int64_t i = 0; i < N_EMBD; ++i)
            ((float *)sh_gate_w->data)[i] = (float)(gs.normal() / std::sqrt((double)N_EMBD));
        ggml_quantize_free();
        return true;
    }

    bool load_gguf(const std::string & path, int layer, std::string & err) {
        struct gguf_init_params ip = { /*no_alloc =*/ true, /*ctx =*/ nullptr };
        gguf_context * g = gguf_init_from_file(path.c_str(), ip);
        if (!g) { err = "gguf_init_from_file failed: " + path; return false; }
        struct Want { const char * suffix; ggml_type type; };
        std::vector<Want> want = {
            {"ffn_gate_inp.weight",       GGML_TYPE_F32},
            {"ffn_gate_inp_shexp.weight", GGML_TYPE_F32},
            {"ffn_up_exps.weight",        GGML_TYPE_Q8_0},
            {"ffn_gate_exps.weight",      GGML_TYPE_Q8_0},
            {"ffn_down_exps.weight",      GGML_TYPE_Q8_0},
            {"ffn_up_shexp.weight",       GGML_TYPE_Q8_0},
            {"ffn_gate_shexp.weight",     GGML_TYPE_Q8_0},
            {"ffn_down_shexp.weight",     GGML_TYPE_Q8_0},
        };
        std::vector<int64_t> ids((size_t)want.size(), -1);
        // first pass: presence, type, and the routed-expert count from the router
        for (size_t i = 0; i < want.size(); ++i) {
            char name[128];
            snprintf(name, sizeof name, "blk.%d.%s", layer, want[i].suffix);
            int64_t id = gguf_find_tensor(g, name);
            if (id < 0) { err = std::string("missing tensor in shard: ") + name; gguf_free(g); return false; }
            if (gguf_get_tensor_type(g, id) != want[i].type) {
                err = std::string("type mismatch for ") + name; gguf_free(g); return false;
            }
            if (i == 0) n_expert = gguf_get_tensor_ne(g, id)[1];
            ids[i] = id;
        }
        // second pass: exact shapes now that n_expert is known + file extents
        FILE * f = fopen(path.c_str(), "rb");
        if (!f) { err = "cannot reopen shard: " + path; gguf_free(g); return false; }
        struct Src { size_t file_off, bytes; };
        std::vector<Src> srcs((size_t)want.size());
        size_t data_off = gguf_get_data_offset(g);
        size_t total = 0;
        for (size_t i = 0; i < want.size(); ++i) {
            const int64_t * ne = gguf_get_tensor_ne(g, ids[i]);
            const char * sfx = want[i].suffix;
            bool is_router   = strcmp(sfx, "ffn_gate_inp.weight") == 0;
            bool is_shgate_w = strcmp(sfx, "ffn_gate_inp_shexp.weight") == 0;
            bool is_exps     = strstr(sfx, "_exps.weight") != nullptr;
            bool is_down     = strncmp(sfx, "ffn_down", 8) == 0; // down: [N_FF, N_EMBD, ...]
            int64_t e0 = is_down ? N_FF : N_EMBD;
            int64_t e1 = is_down ? N_EMBD : (is_router ? n_expert : N_FF);
            bool ok;
            if (is_shgate_w) {
                ok = (ne[0] == N_EMBD) && ne[1] <= 1; // 1D F32 vector
            } else {
                ok = (ne[0] == e0) && (ne[1] == e1);
                if (is_exps) ok = ok && (ne[2] == n_expert);
            }
            if (!ok) {
                char b[256];
                snprintf(b, sizeof b, "shape mismatch for blk.%d.%s: ne=[%lld,%lld,%lld] (expected [%lld,%lld,%lld])",
                         layer, sfx, (long long)ne[0], (long long)ne[1], (long long)ne[2],
                         (long long)e0, (long long)e1, (long long)(is_exps ? n_expert : 0));
                err = b; fclose(f); gguf_free(g); return false;
            }
            srcs[i].bytes = gguf_get_tensor_size(g, ids[i]);
            srcs[i].file_off = data_off + gguf_get_tensor_offset(g, ids[i]);
            total += srcs[i].bytes;
        }
        store.assign(total, 0);
        create_tensors();
        // Read each tensor's bytes directly into ITS tensor's storage. The
        // tensors' in-store layout (create_tensors) need not match the file
        // order; per-tensor reads make the byte-to-tensor assignment explicit.
        ggml_tensor * targets[8] = { router, sh_gate_w, up, gate, down, sh_up, sh_gate, sh_down };
        for (size_t i = 0; i < srcs.size(); ++i) {
            size_t expect = ggml_nbytes(targets[i]);
            if (srcs[i].bytes != expect) {
                char b[256];
                snprintf(b, sizeof b, "byte-size mismatch for blk.%d.%s: file %zu vs tensor %zu",
                         layer, want[i].suffix, srcs[i].bytes, expect);
                err = b; fclose(f); gguf_free(g); return false;
            }
            if (fseeko(f, (off_t)srcs[i].file_off, SEEK_SET) != 0) { err = "fseeko failed"; fclose(f); gguf_free(g); return false; }
            if (fread(targets[i]->data, 1, srcs[i].bytes, f) != srcs[i].bytes) {
                err = std::string("short read for blk.") + want[i].suffix; fclose(f); gguf_free(g); return false;
            }
        }
        fclose(f);
        gguf_free(g);
        return true;
    }
};

// ---------------------------------------------------------------------------
// Devices and resident expert-bank slices.
//   primary   : CPU backend; owns experts [0, split) plus the router and
//               shared-expert weights (host-resident views, no copy).
//   secondary : CPU (offline degenerate second backend) or CUDA backend; owns
//               experts [split, n_expert) as a resident device copy uploaded
//               once at load time.
// ---------------------------------------------------------------------------
struct DeviceSlice {
    ggml_backend_t bk = nullptr;
    ggml_context * wctx = nullptr;
    ggml_backend_buffer_t wbuf = nullptr; // secondary only
    ggml_tensor * up = nullptr;
    ggml_tensor * gate = nullptr;
    ggml_tensor * down = nullptr;
    int64_t e0 = 0, e1 = 0; // expert range [e0, e1)

    bool init_cpu_view(ggml_backend_t backend, Weights & w, int64_t s0, int64_t s1) {
        bk = backend; e0 = s0; e1 = s1;
        size_t meta = ggml_tensor_overhead() * 3 + 256;
        struct ggml_init_params ip = { meta, nullptr, /*no_alloc =*/ true };
        wctx = ggml_init(ip);
        // contiguous slice along ne[2]: views over the host-resident bank
        up   = ggml_view_3d(wctx, w.up,   N_EMBD, N_FF,   e1 - e0, w.up->nb[1],   w.up->nb[2],   (size_t)e0 * w.up->nb[2]);
        gate = ggml_view_3d(wctx, w.gate, N_EMBD, N_FF,   e1 - e0, w.gate->nb[1], w.gate->nb[2], (size_t)e0 * w.gate->nb[2]);
        down = ggml_view_3d(wctx, w.down, N_FF,   N_EMBD, e1 - e0, w.down->nb[1], w.down->nb[2], (size_t)e0 * w.down->nb[2]);
        ggml_set_name(up,   "up_slice");
        ggml_set_name(gate, "gate_slice");
        ggml_set_name(down, "down_slice");
        return up && gate && down;
    }

    bool init_device_copy(ggml_backend_t backend, Weights & w, int64_t s0, int64_t s1) {
        bk = backend; e0 = s0; e1 = s1;
        size_t meta = ggml_tensor_overhead() * 3 + 256;
        struct ggml_init_params ip = { meta, nullptr, /*no_alloc =*/ true };
        wctx = ggml_init(ip);
        size_t up_b   = ggml_row_size(GGML_TYPE_Q8_0, (size_t)(N_EMBD * N_FF)) * (size_t)(e1 - e0);
        size_t down_b = ggml_row_size(GGML_TYPE_Q8_0, (size_t)(N_FF * N_EMBD)) * (size_t)(e1 - e0);
        wbuf = ggml_backend_alloc_buffer(bk, up_b * 2 + down_b + 4096);
        if (!wbuf) return false;
        size_t align = ggml_backend_buffer_get_alignment(wbuf);
        uint8_t * base = (uint8_t *) ggml_backend_buffer_get_base(wbuf);
        size_t off = 0;
        auto place = [&](const char * n, int64_t ne0, int64_t ne1, const void * host, size_t bytes) {
            off = (off + align - 1) / align * align;
            ggml_tensor * t = ggml_new_tensor_3d(wctx, GGML_TYPE_Q8_0, ne0, ne1, e1 - e0);
            ggml_set_name(t, n);
            t->data = base + off;
            t->buffer = wbuf;
            ggml_backend_buffer_init_tensor(wbuf, t);
            ggml_backend_tensor_set(t, host, 0, bytes);
            off += bytes;
            return t;
        };
        up   = place("up_slice",   N_EMBD, N_FF,   (const uint8_t *)w.up->data   + (size_t)e0 * w.up->nb[2],   up_b);
        gate = place("gate_slice", N_EMBD, N_FF,   (const uint8_t *)w.gate->data + (size_t)e0 * w.gate->nb[2], up_b);
        down = place("down_slice", N_FF,   N_EMBD, (const uint8_t *)w.down->data + (size_t)e0 * w.down->nb[2], down_b);
        return true;
    }

    void free_slice() {
        if (wbuf) ggml_backend_buffer_free(wbuf);
        if (wctx) ggml_free(wctx);
        wbuf = nullptr; wctx = nullptr;
    }
};

// ---------------------------------------------------------------------------
// Graph plans (ggml ops only; allocated by a gallocr bound to the owning
// backend's default buffer type).
// ---------------------------------------------------------------------------
struct Plan {
    ggml_context * gctx = nullptr;
    ggml_cgraph * gf = nullptr;
    ggml_gallocr_t ga = nullptr;
    ggml_backend_t bk = nullptr;
    ggml_tensor * in_cur = nullptr;
    ggml_tensor * in_ids = nullptr; // I32 [k, T]
    ggml_tensor * in_w = nullptr;   // F32 [k, T]
    ggml_tensor * out = nullptr;    // F32 [N_EMBD, T]
    ggml_tensor * out_planes = nullptr; // F32 [N_EMBD, k, T] (reference only)
    bool ok() const { return ga != nullptr; }
    void free_plan() {
        if (ga) ggml_gallocr_free(ga);
        if (gctx) ggml_free(gctx);
        ga = nullptr; gctx = nullptr; gf = nullptr;
    }
};

static Plan build_router_plan(ggml_backend_t bk, Weights & w, int64_t T) {
    Plan p;
    p.bk = bk;
    size_t meta = ggml_tensor_overhead() * 32 + ggml_graph_overhead() + 8192;
    struct ggml_init_params ip = { meta, nullptr, /*no_alloc =*/ true };
    p.gctx = ggml_init(ip);
    p.gf = ggml_new_graph(p.gctx);
    p.in_cur = ggml_new_tensor_2d(p.gctx, GGML_TYPE_F32, N_EMBD, T);
    ggml_set_input(p.in_cur);
    ggml_set_name(p.in_cur, "cur");
    // logits = mm(router, cur) -> [n_expert, T]; probs = softmax
    ggml_tensor * logits = ggml_mul_mat(p.gctx, w.router, p.in_cur);
    ggml_tensor * probs  = ggml_soft_max(p.gctx, logits);
    // selected_experts = argsort_top_k(probs, N_USED) -> I32 [N_USED, T]
    ggml_tensor * ids = ggml_argsort_top_k(p.gctx, probs, (int)N_USED);
    // weights = get_rows(probs3, ids) -> [1, N_USED, T], then the norm_w pipeline
    ggml_tensor * probs3 = ggml_reshape_3d(p.gctx, probs, 1, w.n_expert, T);
    ggml_tensor * wsel   = ggml_get_rows(p.gctx, probs3, ids);
    ggml_tensor * w2     = ggml_reshape_2d(p.gctx, wsel, N_USED, T);
    ggml_tensor * wsum   = ggml_sum_rows(p.gctx, w2);
    wsum = ggml_clamp(p.gctx, wsum, WEIGHT_CLAMP_MIN, INFINITY);
    ggml_tensor * wn = ggml_div(p.gctx, w2, wsum);
    ggml_build_forward_expand(p.gf, wn);
    // Materialize the selected-expert ids as a graph output: the ids view
    // feeds only get_rows, so the gallocr may reuse its buffer for later
    // nodes during compute. The cpy target has no consumers, and
    // ggml_set_output keeps its block live until the graph completes.
    ggml_tensor * ids_out = ggml_cpy(p.gctx, ids, ggml_new_tensor_2d(p.gctx, GGML_TYPE_I32, N_USED, T));
    ggml_set_name(ids_out, "selected_experts");
    ggml_set_output(ids_out);
    ggml_build_forward_expand(p.gf, ids_out);
    ggml_set_output(wn);
    p.out = wn;
    p.in_ids = ids_out;
    p.ga = ggml_gallocr_new(ggml_backend_get_default_buffer_type(bk));
    if (!ggml_gallocr_alloc_graph(p.ga, p.gf)) { p.free_plan(); return p; }
    return p;
}

// Expert-subset plan on one device slice: the exact build_moe_ffn op sequence
// for the qwen4exp configuration, restricted to this slice's expert range.
static Plan build_expert_plan(ggml_backend_t bk, DeviceSlice & ds, int64_t k, int64_t T,
                              bool emit_planes) {
    Plan p;
    p.bk = bk;
    size_t meta = ggml_tensor_overhead() * 64 + ggml_graph_overhead() * 4 + 8192;
    struct ggml_init_params ip = { meta, nullptr, /*no_alloc =*/ true };
    p.gctx = ggml_init(ip);
    p.gf = ggml_new_graph(p.gctx);
    p.in_cur = ggml_new_tensor_2d(p.gctx, GGML_TYPE_F32, N_EMBD, T);
    p.in_ids = ggml_new_tensor_2d(p.gctx, GGML_TYPE_I32, k, T);
    p.in_w   = ggml_new_tensor_2d(p.gctx, GGML_TYPE_F32, k, T);
    ggml_set_input(p.in_cur);
    ggml_set_input(p.in_ids);
    ggml_set_input(p.in_w);
    ggml_set_name(p.in_cur, "cur");
    ggml_set_name(p.in_ids, "ids");
    ggml_set_name(p.in_w, "w");

    ggml_tensor * cur3 = ggml_reshape_3d(p.gctx, p.in_cur, N_EMBD, 1, T);
    ggml_tensor * up   = ggml_mul_mat_id(p.gctx, ds.up,   cur3, p.in_ids);  // [N_FF, k, T]
    ggml_tensor * gat  = ggml_mul_mat_id(p.gctx, ds.gate, cur3, p.in_ids);  // [N_FF, k, T]
    ggml_tensor * act  = ggml_swiglu_split(p.gctx, gat, up);                // [N_FF, k, T]
    ggml_tensor * down = ggml_mul_mat_id(p.gctx, ds.down, act, p.in_ids);   // [N_EMBD, k, T]
    ggml_tensor * w3   = ggml_reshape_3d(p.gctx, p.in_w, 1, k, T);
    ggml_tensor * weighted = ggml_mul(p.gctx, down, w3);                    // [N_EMBD, k, T]
    if (emit_planes) {
        // Materialize the weighted planes as an output for host-side
        // tolerance magnitudes (the in-graph plane sum consumes and may
        // reuse the weighted buffer during compute).
        p.out_planes = ggml_cpy(p.gctx, weighted,
                                ggml_new_tensor_3d(p.gctx, GGML_TYPE_F32, N_EMBD, k, T));
        ggml_set_name(p.out_planes, "weighted_planes");
        ggml_set_output(p.out_planes);
    }
    // plane-order sum within this subset, as llama.cpp orders the views/adds
    ggml_tensor * acc = ggml_view_2d(p.gctx, weighted, N_EMBD, T, weighted->nb[2], 0);
    ggml_build_forward_expand(p.gf, acc);
    for (int64_t i = 1; i < k; ++i) {
        ggml_tensor * v = ggml_view_2d(p.gctx, weighted, N_EMBD, T, weighted->nb[2], (size_t)i * weighted->nb[1]);
        ggml_build_forward_expand(p.gf, v);
        acc = ggml_add(p.gctx, acc, v);
    }
    ggml_build_forward_expand(p.gf, acc);
    if (emit_planes) ggml_build_forward_expand(p.gf, p.out_planes);
    p.out = acc;
    p.ga = ggml_gallocr_new(ggml_backend_get_default_buffer_type(bk));
    if (!ggml_gallocr_alloc_graph(p.ga, p.gf)) { p.free_plan(); return p; }
    return p;
}

// Shared expert branch (build_ffn LLM_FFN_SILU / LLM_FFN_PAR + sigmoid gate).
static Plan build_shared_plan(ggml_backend_t bk, Weights & w, int64_t T) {
    Plan p;
    p.bk = bk;
    size_t meta = ggml_tensor_overhead() * 32 + ggml_graph_overhead() + 8192;
    struct ggml_init_params ip = { meta, nullptr, /*no_alloc =*/ true };
    p.gctx = ggml_init(ip);
    p.gf = ggml_new_graph(p.gctx);
    p.in_cur = ggml_new_tensor_2d(p.gctx, GGML_TYPE_F32, N_EMBD, T);
    ggml_set_input(p.in_cur);
    ggml_set_name(p.in_cur, "cur");
    ggml_tensor * u   = ggml_mul_mat(p.gctx, w.sh_up,   p.in_cur); // [N_FF, T]
    ggml_tensor * gat = ggml_mul_mat(p.gctx, w.sh_gate, p.in_cur); // [N_FF, T]
    ggml_tensor * act = ggml_swiglu_split(p.gctx, gat, u);
    ggml_tensor * d   = ggml_mul_mat(p.gctx, w.sh_down, act);      // [N_EMBD, T]
    ggml_tensor * sg  = ggml_sigmoid(p.gctx, ggml_mul_mat(p.gctx, w.sh_gate_w, p.in_cur)); // [1, T]
    p.out = ggml_mul(p.gctx, d, sg);
    ggml_build_forward_expand(p.gf, p.out);
    p.ga = ggml_gallocr_new(ggml_backend_get_default_buffer_type(bk));
    if (!ggml_gallocr_alloc_graph(p.ga, p.gf)) { p.free_plan(); return p; }
    return p;
}

// ---------------------------------------------------------------------------
// Input activations per repetition. Default: SYNTHETIC seeded gaussians
// (labeled as synthetic everywhere). --inputs-file loads a captured F32
// [N_EMBD * T] little-endian tensor for the later hardware capture step.
// ---------------------------------------------------------------------------
static void gen_input(std::vector<float> & cur, int64_t T, uint64_t seed) {
    cur.assign((size_t)(N_EMBD * T), 0.0f);
    PRNG g(seed);
    for (auto & v : cur) v = (float)g.normal();
}

static bool read_inputs_file(const std::string & path, std::vector<float> & cur, int64_t T, std::string & err) {
    FILE * f = fopen(path.c_str(), "rb");
    if (!f) { err = "cannot open --inputs-file: " + path; return false; }
    cur.assign((size_t)(N_EMBD * T), 0.0f);
    size_t want = sizeof(float) * (size_t)(N_EMBD * T);
    if (fread(cur.data(), 1, want, f) != want) { err = "inputs-file too small"; fclose(f); return false; }
    fclose(f);
    return true;
}

// ---------------------------------------------------------------------------
// Legacy CPU-unsplit comparison: retain the original criterion and failures.
// CPU and CUDA do NOT use identical activation operands: CUDA MMQ D4 stores
// fp32 scales whereas CPU Q8_0 and CUDA MMVQ store fp16 scales. Code rounding
// also depends on the kernel path. The historical plane-L1 allowance below
// is not a bound on quantization error through the nonlinear block, nor an
// independent backend operand reference. See numerical-reference.md. The
// overlapped arm must additionally match the serial arm bit-for-bit (same
// kernels, same order, deterministic per fixed shapes/thread counts).
// ---------------------------------------------------------------------------
struct CheckResult {
    bool pass = true;
    double max_abs = 0.0;
    double max_ratio = 0.0; // max |diff| / tolerance
    bool bitwise_equal = true;
    long long n = 0;
};

static CheckResult validate_vs_reference(const std::vector<float> & got,
                                         const std::vector<float> & ref,
                                         const std::vector<float> & planes, // [N_EMBD, k_ref, T]
                                         int64_t k_ref, int64_t T,
                                         bool cross_backend) {
    CheckResult r;
    const double f32_round = (double)1.1920928955078125e-7f; // 2^-23 rounding unit
    const double assoc = 8.0 * f32_round;
    const double quant_headroom = cross_backend ? (1.0 / 128.0) : 0.0;
    int64_t numel = N_EMBD * T;
    for (int64_t t = 0; t < T; ++t) {
        for (int64_t e = 0; e < N_EMBD; ++e) {
            double l1 = 0.0;
            for (int64_t i = 0; i < k_ref; ++i)
                l1 += std::fabs((double)planes[(size_t)(e + i * N_EMBD + t * N_EMBD * k_ref)]);
            double tol = assoc * l1 + quant_headroom * l1;
            if (tol <= 0.0) tol = assoc; // all-zero planes: pure rounding scale
            double g = (double)got[(size_t)(e + t * N_EMBD)];
            double q = (double)ref[(size_t)(e + t * N_EMBD)];
            // non-finite outputs can never satisfy a tolerance comparison
            // (NaN comparisons are false); refuse them explicitly
            if (!std::isfinite(g) || !std::isfinite(q)) { r.pass = false; g = q = 0.0; }
            double d = std::fabs(g - q);
            r.n++;
            if (d > r.max_abs) r.max_abs = d;
            double ratio = d / tol;
            if (ratio > r.max_ratio) r.max_ratio = ratio;
            if (d > tol) r.pass = false;
        }
    }
    return r;
}

static CheckResult validate_bitwise(const std::vector<float> & a, const std::vector<float> & b) {
    CheckResult r;
    r.bitwise_equal = a.size() == b.size();
    r.pass = r.bitwise_equal;
    if (!r.bitwise_equal) return r;
    for (size_t i = 0; i < a.size(); ++i) {
        if (a[i] != b[i]) {
            r.bitwise_equal = false;
            double d = std::fabs((double)a[i] - (double)b[i]);
            if (d > r.max_abs) r.max_abs = d;
        }
        r.n++;
    }
    r.pass = r.bitwise_equal;
    return r;
}

// ---------------------------------------------------------------------------
// Repetition state (fresh per repetition: no shared activation/output buffers;
// warm weights never imply reused answers).
// ---------------------------------------------------------------------------
struct ArmContext {
    std::vector<float> cur;                // [N_EMBD * T]
    std::vector<int32_t> ids;              // [N_USED * T]
    std::vector<float> rweights;           // [N_USED * T]
    std::vector<int32_t> ids_cpu, ids_sec; // padded per-device ids [k * T]
    std::vector<float> w_cpu, w_sec;
    int64_t k_cpu = 0, k_sec = 0;           // padded subset sizes
    int64_t k_cpu_real = 0, k_sec_real = 0; // real selected counts (sum over tokens)
    std::vector<float> partial_cpu, partial_sec, shared_out;
};

// Padding for uniform-k windows (T > 1): MUL_MAT_ID ids are top-k output —
// UNIQUE per token — and the CUDA backend's id-mapping kernel (mm_ids_helper
// in ggml-cuda/mmid.cu at this pin) relies on that: it compacts each
// (token, expert) pair exactly once. Padding a token's window with a
// REPEATED local expert id therefore write-write races inside the kernel and
// leaves duplicate output slots reading stale pool memory (the T=128
// nondeterminism diagnosed on 2026-10-12; the CPU backend tolerates
// duplicates, which is why offline runs never caught it). Padding ids must be
// DISTINCT within the token and distinct from the token's genuine
// selections, with weight exactly +0.0f so the extra expert planes are
// numerically discarded. If the requested padded width cannot be represented
// that way (fewer unselected local experts than padding slots), that is an
// unrepresentable input: rejected explicitly here, never silently filled
// with repeated ids.
struct PaddingFail {
    int64_t token = 0;
    int64_t slots_needed = 0, unselected = 0;
    bool primary = true;
    bool duplicate_genuine = false; // same expert selected twice in one token
};

static void fill_padding_distinct(std::vector<int32_t> & ids_dev,
                                  std::vector<float> & w_dev,
                                  const std::vector<uint8_t> & used,
                                  int64_t k_dev, int64_t n_local, int64_t t,
                                  int64_t & fill, bool primary, PaddingFail & fail) {
    for (int64_t cand = 0; cand < n_local && fill < k_dev; ++cand) {
        if (used[(size_t)(cand + t * n_local)]) continue;
        ids_dev[(size_t)(fill + t * k_dev)] = (int32_t)cand; // weight stays +0.0f
        ++fill;
    }
    if (fill < k_dev) { fail = PaddingFail{t, k_dev - fill, n_local - (k_dev - fill), primary, false}; }
}

// Split routing into per-device padded subsets. For T == 1 the subsets are
// exact (single token). For T > 1, mul_mat_id needs one uniform k per device,
// so each subset is padded to its per-repetition maximum with DISTINCT local
// expert ids unused by that token and weight exactly +0.0f (see
// fill_padding_distinct); the padding work is identical in both arms and is
// reported (k vs k_real). Sets structural_fail when the split routing
// cannot be represented safely.
static void partition_routing(ArmContext & A, int64_t T, int64_t split, int64_t n_expert,
                              PaddingFail & structural_fail) {
    int64_t maxc = 0, maxs = 0;
    for (int64_t t = 0; t < T; ++t) {
        int64_t c = 0, s = 0;
        for (int64_t i = 0; i < N_USED; ++i) {
            int32_t id = A.ids[(size_t)(i + t * N_USED)];
            if (id < split) ++c; else ++s;
        }
        A.k_cpu_real += c;
        A.k_sec_real += s;
        maxc = std::max(maxc, c);
        maxs = std::max(maxs, s);
    }
    A.k_cpu = (T == 1) ? A.k_cpu_real : maxc;
    A.k_sec = (T == 1) ? A.k_sec_real : maxs;
    A.ids_cpu.assign((size_t)(A.k_cpu * T), 0);
    A.w_cpu.assign((size_t)(A.k_cpu * T), 0.0f);
    A.ids_sec.assign((size_t)(A.k_sec * T), 0);
    A.w_sec.assign((size_t)(A.k_sec * T), 0.0f);
    // per-token local-id occupancy, so padding can pick distinct unselected ids
    std::vector<uint8_t> used_cpu, used_sec;
    if (split > 0) used_cpu.assign((size_t)(split * T), 0);
    if (n_expert - split > 0) used_sec.assign((size_t)((n_expert - split) * T), 0);
    for (int64_t t = 0; t < T; ++t) {
        int64_t ci = 0, si = 0;
        for (int64_t i = 0; i < N_USED; ++i) {
            int64_t slot = i + t * N_USED;
            int32_t id = A.ids[(size_t)slot];
            float wv = A.rweights[(size_t)slot];
            if (id < split) {
                uint8_t & u = used_cpu[(size_t)(id + t * split)];
                if (u) { structural_fail = PaddingFail{t, 0, 0, true, true}; return; }
                u = 1;
                if (ci < A.k_cpu) {
                    A.ids_cpu[(size_t)(ci + t * A.k_cpu)] = id;
                    A.w_cpu[(size_t)(ci + t * A.k_cpu)] = wv;
                    ++ci;
                }
            } else {
                uint8_t & u = used_sec[(size_t)((id - split) + t * (n_expert - split))];
                if (u) { structural_fail = PaddingFail{t, 0, 0, false, true}; return; }
                u = 1;
                if (si < A.k_sec) {
                    A.ids_sec[(size_t)(si + t * A.k_sec)] = id - (int32_t)split;
                    A.w_sec[(size_t)(si + t * A.k_sec)] = wv;
                    ++si;
                }
            }
        }
        // remaining padded columns carry weight exactly +0.0f and DISTINCT
        // unselected local expert ids (never a repeated id: see above)
        if (A.k_cpu > 0) fill_padding_distinct(A.ids_cpu, A.w_cpu, used_cpu, A.k_cpu, split, t, ci, true, structural_fail);
        if (A.k_sec > 0) fill_padding_distinct(A.ids_sec, A.w_sec, used_sec, A.k_sec, n_expert - split, t, si, false, structural_fail);
    }
}

// Offline unit seam for partition_routing: when MOE_OVERLAP_UNIT_ROUTING is
// set, run the split/pad logic over caller-supplied routing (no backends, no
// weights, no graphs) and print the resulting padded matrices as JSON on
// stdout, then exit 0 — or exit 5 with a reason on stderr when the padded
// width is unrepresentable (fewer unselected local ids than padding slots).
// This exists so the offline test suite can structurally verify the padding
// invariant and the explicit rejection on a CPU-only machine (duplicate-id
// padding raced only inside the CUDA kernel, which CPU runs never observe).
// Expected input JSON on stdin (all fields required):
//   {"n_expert": E, "split": S, "tokens": T, "n_used": U,
//    "ids":   [U*T global expert ids, id + t*U layout],
//    "weights": [U*T F32-as-uint32 bit patterns, same layout]}
// Cardinality contract: partition_routing consumes routing with the FIXED
// top-10 stride N_USED (this harness models the qwen4exp router's
// argsort_top_k(probs, 10); it is not a general top-k partitioner). The seam
// therefore requires n_used == N_USED exactly and rejects any other
// cardinality as an explicit input error BEFORE partitioning: a shorter
// array would make the fixed-stride counting loop read past the caller's
// input (demonstrated: AddressSanitizer heap-buffer-overflow at the
// partition_routing first counting loop with n_used=4), and a longer one
// would silently mis-stride tokens.
static int unit_routing_run() {
    // Minimal JSON object parser for this fixed schema (numbers + flat int
    // arrays). Not a general parser: any deviation from the schema is an
    // error, never a guess.
    std::string all, line;
    while (std::getline(std::cin, line)) all += line;
    auto fail = [](const char * why) { fprintf(stderr, "unit-routing input error: %s\n", why); return 5; };
    auto parse_uint_array = [&](const std::string & key, std::vector<uint32_t> & out) -> bool {
        size_t k = all.find("\"" + key + "\"");
        if (k == std::string::npos) return false;
        size_t lb = all.find('[', k), rb = all.find(']', k);
        if (lb == std::string::npos || rb == std::string::npos) return false;
        out.clear();
        size_t i = lb + 1;
        while (i < rb) {
            if (all[i] == ',' || all[i] == ' ') { ++i; continue; }
            size_t j = i;
            while (j < rb && all[j] != ',') ++j;
            out.push_back((uint32_t)std::strtoul(all.substr(i, j - i).c_str(), nullptr, 10));
            i = j;
        }
        return true;
    };
    auto parse_num = [&](const std::string & key, int64_t & v) -> bool {
        size_t k = all.find("\"" + key + "\"");
        if (k == std::string::npos) return false;
        size_t c = all.find(':', k);
        if (c == std::string::npos) return false;
        v = (int64_t)std::strtoll(all.substr(c + 1).c_str(), nullptr, 10);
        return true;
    };
    int64_t n_expert = 0, split = 0, T = 0, n_used = 0;
    std::vector<uint32_t> ids_in, w_in;
    if (!parse_num("n_expert", n_expert) || !parse_num("split", split) ||
        !parse_num("tokens", T) || !parse_num("n_used", n_used) ||
        !parse_uint_array("ids", ids_in) || !parse_uint_array("weights", w_in))
        return fail("missing field");
    if (n_expert < 1 || n_expert > 4096 || split < 0 || split > n_expert ||
        T < 1 || T > 4096)
        return fail("geometry out of range");
    // Fixed-cardinality contract: partition_routing reads exactly N_USED ids
    // per token (see above); anything else is rejected before partitioning.
    if (n_used != N_USED)
        return fail("n_used must equal the harness's fixed top-10 routing "
                    "cardinality (N_USED=10); other cardinalities are not "
                    "supported by this seam");
    if ((int64_t)ids_in.size() != n_used * T || (int64_t)w_in.size() != n_used * T)
        return fail("array size mismatch");
    for (uint32_t id : ids_in) if (id >= (uint32_t)n_expert) return fail("id out of range");

    // Build the same ArmContext the production path builds from the router.
    ArmContext A;
    A.ids.assign(ids_in.begin(), ids_in.end());
    A.rweights.resize((size_t)(n_used * T));
    for (size_t i = 0; i < A.rweights.size(); ++i)
        std::memcpy(&A.rweights[i], &w_in[i], 4);

    PaddingFail pfail;
    partition_routing(A, T, split, n_expert, pfail);
    if (pfail.duplicate_genuine) {
        fprintf(stderr, "duplicate genuine expert id within token %lld (%s subset): "
                "router output violates the top-k uniqueness contract\n",
                (long long)pfail.token, pfail.primary ? "primary" : "secondary");
        return 5;
    }
    if (pfail.slots_needed > 0) {
        fprintf(stderr, "unrepresentable padding: token %lld %s subset needs %lld padding "
                "slots but only %lld unselected local expert ids exist\n",
                (long long)pfail.token, pfail.primary ? "primary" : "secondary",
                (long long)pfail.slots_needed, (long long)pfail.unselected);
        return 5;
    }

    JsonOut D;
    D.begin("routing");
    D.num("tokens", (double)T);
    D.num("n_expert", (double)n_expert);
    D.num("split", (double)split);
    D.num("k_cpu", (double)A.k_cpu);
    D.num("k_sec", (double)A.k_sec);
    D.num("k_cpu_real", (double)A.k_cpu_real);
    D.num("k_sec_real", (double)A.k_sec_real);
    auto arr = [&](const char * name, const std::vector<int32_t> & v) {
        D.begin_arr(name);
        for (size_t i = 0; i < v.size(); ++i) {
            char b[24];
            snprintf(b, sizeof b, "%s%lld", i ? "," : "", (long long)v[i]);
            D.s += b;
        }
        D.end_arr();
    };
    arr("ids_cpu", A.ids_cpu);
    arr("ids_sec", A.ids_sec);
    auto wbits = [&](const char * name, const std::vector<float> & w) {
        D.begin_arr(name);
        for (size_t i = 0; i < w.size(); ++i) {
            uint32_t bits; std::memcpy(&bits, &w[i], 4);
            char b[32];
            snprintf(b, sizeof b, "%" PRIu32 "%s", bits, i + 1 < w.size() ? "," : "");
            D.s += b;
        }
        D.end_arr();
    };
    wbits("w_cpu", A.w_cpu);
    wbits("w_sec", A.w_sec);
    D.end();
    printf("{\n%s\n}\n", D.s.c_str());
    return 0;
}

struct StageTimes {
    double h2d_ms = 0, cpu_ms = 0, sec_ms = 0, d2h_ms = 0, combine_ms = 0, total_ms = 0;
};

// Compute-status failure propagation: a non-success graph compute must abort
// the run before any output is compared or reused (no stale outputs).
static bool g_compute_failed = false;
static std::string g_compute_fail_stage;
struct ComputeFailure {};

static void check_compute(enum ggml_status st, const char * stage) {
    if (st != GGML_STATUS_SUCCESS && !g_compute_failed) {
        g_compute_failed = true;
        g_compute_fail_stage = std::string(stage) + " (ggml_status=" + std::to_string((int)st) + ")";
        fprintf(stderr, "error: graph compute failed at %s\n", g_compute_fail_stage.c_str());
    }
    // Unwind to the owning repetition/control before any tensor read, combine
    // or comparison. That owner joins both backends while its buffers live.
    if (g_compute_failed) throw ComputeFailure{};
}

struct Harness {
    std::string mode = "synthetic";
    std::string gguf_path;
    int layer = 2;
    int64_t n_expert = N_EXPERT_AUTHENTIC;
    int64_t T = 1;
    int64_t split = 256;
    std::string secondary_kind = "cpu"; // "cpu" | "cuda"
    int threads = 0, secondary_threads = 2;
    int warmup = 1, reps = 5;
    uint64_t seed = 0x4953573030303033ULL; // "ISW0003"
    std::string inputs_file;
    std::string json_path;
    bool negative_control = false;
    bool status_negative = false;
    std::string dump_serial, dump_overlap; // last-rep arm outputs (F32)
    std::string dump_routing;              // last-rep split routing evidence
    std::string reference_case;             // untimed export for independent checker
    std::string reference_cpu_mode, reference_secondary_mode;
    // last-rep routing capture for --dump-routing
    std::vector<int32_t> last_ids_cpu, last_ids_sec, last_ids_all;
    std::vector<float> last_w_cpu, last_w_sec, last_w_all;
    int64_t last_k_cpu = 0, last_k_sec = 0, last_kr_cpu = 0, last_kr_sec = 0;

    ggml_backend_t cpu_bk = nullptr, sec_bk = nullptr;
    Weights W;
    DeviceSlice prim, sec, full;
    Plan router_plan, shared_plan, ref_plan;
    JsonOut J;
};

int run_harness(Harness & H) {
    std::string err;
    JsonOut & J = H.J;
    bool all_pass = true;
    std::string fail_reason;
    if (!H.reference_case.empty()) {
        if (H.T != 1 && H.T != 128) {
            fprintf(stderr, "error: operand reference supports only T=1 and T=128\n"); return 4;
        }
#if defined(__x86_64__) || defined(__i386__)
        // Query the linked CPU closure, not the harness TU's compiler flags.
        H.reference_cpu_mode = (ggml_cpu_has_avx() || ggml_cpu_has_avx2())
            ? "cpu-avx-q8_0" : "cpu-scalar-q8_0";
#else
        fprintf(stderr, "error: unsupported CPU reference quantizer architecture\n"); return 4;
#endif
        H.reference_secondary_mode = H.secondary_kind == "cpu" ? H.reference_cpu_mode
            : (H.T == 1 ? "cuda-mmvq-q8_1" : "cuda-mmq-d4");
        if (mkdir(H.reference_case.c_str(), 0700) != 0) {
            fprintf(stderr, "error: reference-case directory must be new and creatable\n"); return 4;
        }
    }

    // ---- backends ----------------------------------------------------------
    ggml_backend_dev_t cpu_dev = ggml_backend_dev_by_type(GGML_BACKEND_DEVICE_TYPE_CPU);
    if (!cpu_dev) { fprintf(stderr, "error: no CPU backend device\n"); return 4; }
    H.cpu_bk = ggml_backend_dev_init(cpu_dev, nullptr);
    if (!H.cpu_bk) { fprintf(stderr, "error: cpu backend init failed\n"); return 4; }
    if (H.threads <= 0) {
        unsigned hc = std::thread::hardware_concurrency();
        H.threads = hc > 1 ? (int)(hc / 2) : 1;
    }
    ggml_backend_cpu_set_n_threads(H.cpu_bk, H.threads);
    if (H.secondary_kind == "cuda") {
        ggml_backend_dev_t gpu = ggml_backend_dev_by_type(GGML_BACKEND_DEVICE_TYPE_GPU);
        if (!gpu) {
            fprintf(stderr, "error: no CUDA/GPU backend device available (fail-closed; no CPU fallback)\n");
            return 4;
        }
        if (!H.reference_case.empty() && (std::string(ggml_backend_dev_description(gpu)) != "NVIDIA GeForce RTX 3060"
                || std::string(ggml_backend_dev_name(gpu)) != "CUDA0")) {
            fprintf(stderr, "error: unsupported CUDA reference subject (requires RTX 3060)\n"); return 4;
        }
        H.sec_bk = ggml_backend_dev_init(gpu, nullptr);
        if (!H.sec_bk) { fprintf(stderr, "error: gpu backend init failed\n"); return 4; }
    } else {
        H.sec_bk = ggml_backend_dev_init(cpu_dev, nullptr);
        if (!H.sec_bk) { fprintf(stderr, "error: secondary cpu backend init failed\n"); return 4; }
        ggml_backend_cpu_set_n_threads(H.sec_bk, H.secondary_threads);
    }

    // ---- weights (loaded once; both arms and all repetitions reuse) --------
    double t0 = now_ms();
    if (H.mode == "gguf") {
        if (!H.W.load_gguf(H.gguf_path, H.layer, err)) { fprintf(stderr, "error: %s\n", err.c_str()); return 4; }
        H.n_expert = H.W.n_expert;
    } else if (!H.W.fill_synthetic(H.n_expert, H.seed)) {
        fprintf(stderr, "error: synthetic weight generation failed\n");
        return 4;
    }
    double load_ms = now_ms() - t0;

    // ---- resident slices ----------------------------------------------------
    double sec_load_ms = 0.0;
    if (!H.prim.init_cpu_view(H.cpu_bk, H.W, 0, H.split)) { fprintf(stderr, "error: primary slice\n"); return 4; }
    if (!H.full.init_cpu_view(H.cpu_bk, H.W, 0, H.n_expert)) { fprintf(stderr, "error: reference slice\n"); return 4; }
    if (H.split < H.n_expert) {
        double s0 = now_ms();
        if (!H.sec.init_device_copy(H.sec_bk, H.W, H.split, H.n_expert)) {
            fprintf(stderr, "error: secondary slice\n"); return 4;
        }
        sec_load_ms = now_ms() - s0;
    }

    // ---- fixed plans ---------------------------------------------------------
    H.router_plan = build_router_plan(H.cpu_bk, H.W, H.T);
    H.shared_plan = build_shared_plan(H.cpu_bk, H.W, H.T);
    H.ref_plan    = build_expert_plan(H.cpu_bk, H.full, N_USED, H.T, /*emit_planes=*/true);
    if (!H.router_plan.ok() || !H.shared_plan.ok() || !H.ref_plan.ok()) {
        fprintf(stderr, "error: fixed plan allocation failed\n");
        return 4;
    }

    J.begin("config");
    J.str("harness", "moe_overlap_harness/1");
    J.str("native_pin", "llama.cpp b29c606e28a01b1bc8c1351026a0fa6e616bf6c4");
    J.str("weights_mode", H.mode == "gguf" ? "GGUF" : "SYNTHETIC");
    if (H.mode == "gguf") { J.str("gguf", H.gguf_path); J.num("layer", H.layer); }
    else { J.num("synthetic_seed", (double)H.seed); }
    J.str("inputs_mode", H.inputs_file.empty() ? "SYNTHETIC-GAUSSIAN" : "CAPTURED-FILE");
    if (!H.inputs_file.empty()) J.str("inputs_file", H.inputs_file);
    J.num("n_embd", (double)N_EMBD);
    J.num("n_ff", (double)N_FF);
    J.num("n_expert", (double)H.n_expert);
    J.num("n_used", (double)N_USED);
    J.num("tokens", (double)H.T);
    J.num("split", (double)H.split);
    J.str("primary_backend", ggml_backend_name(H.cpu_bk));
    J.str("secondary_kind", H.secondary_kind);
    J.str("secondary_backend", H.sec_bk ? ggml_backend_name(H.sec_bk) : "(none)");
    J.str("reference_comparison", "legacy-cpu-unsplit/1");
    J.str("backend_operand_reference_contract", "moe-operand-reference/2");
    J.str("backend_operand_reference_status", H.reference_case.empty() ? "NOT_REQUESTED" : "EXTERNAL_CHECK_PENDING");
    if (!H.reference_case.empty()) {
        J.str("reference_cpu_mode", H.reference_cpu_mode);
        J.str("reference_secondary_mode", H.reference_secondary_mode);
        J.str("reference_case", H.reference_case);
    }
    J.num("primary_threads", H.threads);
    J.num("secondary_threads", H.secondary_kind == "cpu" ? H.secondary_threads : 0);
    J.num("warmup", H.warmup);
    J.num("reps", H.reps);
    J.end();

    J.begin("load");
    J.num("weights_ms", load_ms);
    J.num("secondary_slice_ms", sec_load_ms);
    J.num("weight_bytes", (double)H.W.store.size());
    J.end();

    // ---- execution helpers ---------------------------------------------------
    auto record_compute_failure = [&]() {
        // A CPU failure can occur while secondary copies/kernels are pending;
        // even a failed async submission may have enqueued some work. Join both
        // before freeing plans or letting their host input/output vectors die.
        ggml_backend_synchronize(H.cpu_bk);
        ggml_backend_synchronize(H.sec_bk);
        all_pass = false;
        fail_reason = "graph compute failed: " + g_compute_fail_stage;
    };

    auto run_router = [&](ArmContext & A) {
        double s = now_ms();
        ggml_backend_tensor_set(H.router_plan.in_cur, A.cur.data(), 0, sizeof(float) * A.cur.size());
        check_compute(ggml_backend_graph_compute(H.cpu_bk, H.router_plan.gf), "router");
        ggml_backend_synchronize(H.cpu_bk);
        A.ids.resize((size_t)(N_USED * H.T));
        A.rweights.resize((size_t)(N_USED * H.T));
        ggml_backend_tensor_get(H.router_plan.in_ids, A.ids.data(), 0, sizeof(int32_t) * A.ids.size());
        ggml_backend_tensor_get(H.router_plan.out, A.rweights.data(), 0, sizeof(float) * A.rweights.size());
        return now_ms() - s;
    };

    auto compute_shared_blocking = [&](ArmContext & A, std::vector<float> & sh) {
        ggml_backend_tensor_set(H.shared_plan.in_cur, A.cur.data(), 0, sizeof(float) * A.cur.size());
        check_compute(ggml_backend_graph_compute(H.cpu_bk, H.shared_plan.gf), "shared");
        ggml_backend_synchronize(H.cpu_bk);
        sh.resize((size_t)(N_EMBD * H.T));
        ggml_backend_tensor_get(H.shared_plan.out, sh.data(), 0, sizeof(float) * sh.size());
    };

    // Reference: unsplit llama.cpp-order block on the primary device; the
    // complete block output is add(moe_out, shared), one F32 add per element.
    auto run_reference = [&](ArmContext & A, std::vector<float> & ref_out, std::vector<float> & ref_planes) {
        ggml_backend_tensor_set(H.ref_plan.in_cur, A.cur.data(), 0, sizeof(float) * A.cur.size());
        ggml_backend_tensor_set(H.ref_plan.in_ids, A.ids.data(), 0, sizeof(int32_t) * A.ids.size());
        ggml_backend_tensor_set(H.ref_plan.in_w, A.rweights.data(), 0, sizeof(float) * A.rweights.size());
        check_compute(ggml_backend_graph_compute(H.cpu_bk, H.ref_plan.gf), "reference");
        ggml_backend_synchronize(H.cpu_bk);
        ref_out.resize((size_t)(N_EMBD * H.T));
        ref_planes.resize((size_t)(N_EMBD * N_USED * H.T));
        ggml_backend_tensor_get(H.ref_plan.out, ref_out.data(), 0, sizeof(float) * ref_out.size());
        ggml_backend_tensor_get(H.ref_plan.out_planes, ref_planes.data(), 0, sizeof(float) * ref_planes.size());
        std::vector<float> sh;
        compute_shared_blocking(A, sh);
        for (size_t i = 0; i < ref_out.size(); ++i) ref_out[i] = ref_out[i] + sh[i];
    };

    auto set_plan_inputs_blocking = [&](Plan & p, ArmContext & A, const std::vector<int32_t> & idsv, const std::vector<float> & wv) {
        ggml_backend_tensor_set(p.in_cur, A.cur.data(), 0, sizeof(float) * A.cur.size());
        ggml_backend_tensor_set(p.in_ids, idsv.data(), 0, sizeof(int32_t) * idsv.size());
        ggml_backend_tensor_set(p.in_w, wv.data(), 0, sizeof(float) * wv.size());
    };

    auto combine = [&](ArmContext & A, std::vector<float> & out) {
        out.assign((size_t)(N_EMBD * H.T), 0.0f);
        for (size_t i = 0; i < out.size(); ++i)
            out[i] = (A.partial_cpu[i] + A.partial_sec[i]) + A.shared_out[i];
    };

    // serial arm: every stage fully synchronized before the next
    auto run_serial = [&](ArmContext & A, Plan & pcpu, Plan & psec, std::vector<float> & out, StageTimes & st) {
        double s = now_ms();
        double c0 = now_ms();
        if (pcpu.ok()) {
            set_plan_inputs_blocking(pcpu, A, A.ids_cpu, A.w_cpu);
            check_compute(ggml_backend_graph_compute(H.cpu_bk, pcpu.gf), "primary experts");
            ggml_backend_synchronize(H.cpu_bk);
            A.partial_cpu.resize((size_t)(N_EMBD * H.T));
            ggml_backend_tensor_get(pcpu.out, A.partial_cpu.data(), 0, sizeof(float) * A.partial_cpu.size());
        } else {
            A.partial_cpu.assign((size_t)(N_EMBD * H.T), 0.0f);
        }
        compute_shared_blocking(A, A.shared_out);
        st.cpu_ms = now_ms() - c0;
        if (psec.ok()) {
            double h0 = now_ms();
            set_plan_inputs_blocking(psec, A, A.ids_sec, A.w_sec);
            ggml_backend_synchronize(H.sec_bk);
            st.h2d_ms = now_ms() - h0;
            double g0 = now_ms();
            check_compute(ggml_backend_graph_compute(H.sec_bk, psec.gf), "secondary experts");
            ggml_backend_synchronize(H.sec_bk);
            st.sec_ms = now_ms() - g0;
            double d0 = now_ms();
            A.partial_sec.resize((size_t)(N_EMBD * H.T));
            ggml_backend_tensor_get(psec.out, A.partial_sec.data(), 0, sizeof(float) * A.partial_sec.size());
            st.d2h_ms = now_ms() - d0;
        } else {
            A.partial_sec.assign((size_t)(N_EMBD * H.T), 0.0f);
        }
        double k0 = now_ms();
        combine(A, out);
        st.combine_ms = now_ms() - k0;
        st.total_ms = now_ms() - s;
    };

    // overlapped arm: secondary stream work enqueued, CPU runs concurrently.
    // The D2H read-back is deliberately issued only AFTER the CPU-side work:
    // the destination is ordinary pageable host memory, and CUDA documents
    // that an async copy with a pageable destination may block the host until
    // the copy completes. Enqueueing it before the CPU branch could silently
    // serialize the whole arm and masquerade as a negative overlap result.
    // Stream ordering still guarantees the read happens after the kernels.
    auto run_overlap = [&](ArmContext & A, Plan & pcpu, Plan & psec, std::vector<float> & out, StageTimes & st) {
        double s = now_ms();
        if (psec.ok()) {
            double h0 = now_ms();
            ggml_backend_tensor_set_async(H.sec_bk, psec.in_cur, A.cur.data(), 0, sizeof(float) * A.cur.size());
            ggml_backend_tensor_set_async(H.sec_bk, psec.in_ids, A.ids_sec.data(), 0, sizeof(int32_t) * A.ids_sec.size());
            ggml_backend_tensor_set_async(H.sec_bk, psec.in_w, A.w_sec.data(), 0, sizeof(float) * A.w_sec.size());
            st.h2d_ms = now_ms() - h0; // submission time only (async)
            A.partial_sec.resize((size_t)(N_EMBD * H.T));
            check_compute(ggml_backend_graph_compute_async(H.sec_bk, psec.gf), "secondary experts (async)");
        } else {
            A.partial_sec.assign((size_t)(N_EMBD * H.T), 0.0f);
        }
        // CPU expert subset + shared branch run while the secondary stream works
        double c0 = now_ms();
        if (pcpu.ok()) {
            set_plan_inputs_blocking(pcpu, A, A.ids_cpu, A.w_cpu);
            check_compute(ggml_backend_graph_compute(H.cpu_bk, pcpu.gf), "primary experts");
            ggml_backend_synchronize(H.cpu_bk);
            A.partial_cpu.resize((size_t)(N_EMBD * H.T));
            ggml_backend_tensor_get(pcpu.out, A.partial_cpu.data(), 0, sizeof(float) * A.partial_cpu.size());
        } else {
            A.partial_cpu.assign((size_t)(N_EMBD * H.T), 0.0f);
        }
        compute_shared_blocking(A, A.shared_out);
        st.cpu_ms = now_ms() - c0;
        // join: D2H read-back (pageable host destination) issued here, after
        // the CPU-side work, then wait for the secondary stream to complete
        if (psec.ok()) {
            double d0 = now_ms();
            ggml_backend_tensor_get_async(H.sec_bk, psec.out, A.partial_sec.data(), 0, sizeof(float) * A.partial_sec.size());
            ggml_backend_synchronize(H.sec_bk);
            st.d2h_ms = now_ms() - d0;
        }
        double k0 = now_ms();
        combine(A, out);
        st.combine_ms = now_ms() - k0;
        st.total_ms = now_ms() - s;
    };

    struct RepResult {
        double serial_ms = 0, overlap_ms = 0, router_ms = 0, build_ms = 0;
        StageTimes st_serial, st_overlap;
        int64_t k_cpu = 0, k_sec = 0, k_cpu_real = 0, k_sec_real = 0;
        CheckResult serial_vs_ref, overlap_vs_serial;
        std::vector<float> serial_out, overlap_out, ref_out, ref_planes;
        bool counts_ok = false, single_device = false;
    };

    // Untimed host exports only; graph structure, kernels and schedule are
    // unchanged. Even a legacy numerical FAIL can be independently checked.
    auto export_arm = [&](ArmContext & A, const std::vector<float> & out, int rep, const char * arm) {
        if (H.reference_case.empty() || rep < 0 || g_compute_failed) return;
        auto write = [&](const std::string & suffix, const void * data, size_t bytes) {
            std::string path = H.reference_case + "/rep-" + std::to_string(rep) + "-" + suffix;
            FILE * f = fopen(path.c_str(), "wb");
            if (!f) { all_pass = false; fail_reason = "reference-case export failed"; return; }
            bool ok = fwrite(data, 1, bytes, f) == bytes;
            if (fclose(f) != 0) ok = false;
            if (!ok) { all_pass = false; fail_reason = "reference-case export failed"; }
        };
        if (std::string(arm) == "serial") {
            write("cur.f32", A.cur.data(), A.cur.size() * sizeof(float));
            write("ids.i32", A.ids.data(), A.ids.size() * sizeof(int32_t));
            write("weights.f32", A.rweights.data(), A.rweights.size() * sizeof(float));
            write("cpu.f32", A.partial_cpu.data(), A.partial_cpu.size() * sizeof(float));
            write("sec.f32", A.partial_sec.data(), A.partial_sec.size() * sizeof(float));
            write("shared.f32", A.shared_out.data(), A.shared_out.size() * sizeof(float));
        }
        write(std::string(arm) + ".f32", out.data(), out.size() * sizeof(float));
    };

    // one repetition: router once, reference once, both arms (order alternates)
    auto run_rep = [&](ArmContext & A, RepResult & R, bool serial_first, bool validate, int capture_rep = -1) {
        Plan pcpu, psec;
        try {
            if (g_compute_failed) throw ComputeFailure{};
            R.router_ms = run_router(A);
            PaddingFail pfail;
            partition_routing(A, H.T, H.split, H.n_expert, pfail);
            if (pfail.duplicate_genuine || pfail.slots_needed > 0) {
                // fail closed: never present duplicate or unrepresentable ids
                // to the native MUL_MAT_ID operation
                all_pass = false;
                fail_reason = pfail.duplicate_genuine
                    ? "duplicate genuine expert id within token " + std::to_string(pfail.token) +
                      " (router output violates the top-k uniqueness contract)"
                    : "unrepresentable padding: token " + std::to_string(pfail.token) +
                      (pfail.primary ? " primary" : " secondary") + " subset needs " +
                      std::to_string(pfail.slots_needed) + " padding slots but only " +
                      std::to_string(pfail.unselected) + " unselected local expert ids exist";
                pcpu.free_plan();
                psec.free_plan();
                return false;
            }
            // fail-closed routed-work assertion: every token routes exactly N_USED
            // experts across the two devices; nothing may skip or duplicate work.
            R.counts_ok = (A.k_cpu_real + A.k_sec_real) == N_USED * H.T;
            R.k_cpu = A.k_cpu; R.k_sec = A.k_sec;
            R.k_cpu_real = A.k_cpu_real; R.k_sec_real = A.k_sec_real;
            R.single_device = (A.k_sec == 0);
            if (!H.dump_routing.empty()) {
                H.last_ids_cpu = A.ids_cpu; H.last_w_cpu = A.w_cpu;
                H.last_ids_sec = A.ids_sec; H.last_w_sec = A.w_sec;
                H.last_ids_all = A.ids;    H.last_w_all = A.rweights;
                H.last_k_cpu = A.k_cpu; H.last_k_sec = A.k_sec;
                H.last_kr_cpu = A.k_cpu_real; H.last_kr_sec = A.k_sec_real;
            }

            double b0 = now_ms();
            if (A.k_cpu > 0) pcpu = build_expert_plan(H.cpu_bk, H.prim, A.k_cpu, H.T, false);
            if (A.k_sec > 0) psec = build_expert_plan(H.sec_bk, H.sec, A.k_sec, H.T, false);
            R.build_ms = now_ms() - b0;
            if ((A.k_cpu > 0 && !pcpu.ok()) || (A.k_sec > 0 && !psec.ok())) {
                all_pass = false;
                fail_reason = "arm plan allocation failed";
                pcpu.free_plan();
                psec.free_plan();
                return false;
            }

            bool cross = (A.k_sec > 0) && (H.secondary_kind != "cpu");
            run_reference(A, R.ref_out, R.ref_planes);
            if (serial_first) {
                run_serial(A, pcpu, psec, R.serial_out, R.st_serial);
                export_arm(A, R.serial_out, capture_rep, "serial");
                run_overlap(A, pcpu, psec, R.overlap_out, R.st_overlap);
                export_arm(A, R.overlap_out, capture_rep, "overlap");
            } else {
                run_overlap(A, pcpu, psec, R.overlap_out, R.st_overlap);
                export_arm(A, R.overlap_out, capture_rep, "overlap");
                run_serial(A, pcpu, psec, R.serial_out, R.st_serial);
                export_arm(A, R.serial_out, capture_rep, "serial");
            }
            R.serial_ms = R.st_serial.total_ms;
            R.overlap_ms = R.st_overlap.total_ms;

            if (validate) {
                R.serial_vs_ref = validate_vs_reference(R.serial_out, R.ref_out, R.ref_planes, N_USED, H.T, cross);
                R.overlap_vs_serial = validate_bitwise(R.overlap_out, R.serial_out);
                bool ok = R.counts_ok && R.serial_vs_ref.pass && R.overlap_vs_serial.pass;
                if (R.single_device) {
                    // strict identity: single-device serial must match the
                    // reference bit-for-bit (same kernels, order and backend)
                    bool bw = (R.serial_out.size() == R.ref_out.size());
                    for (size_t i = 0; bw && i < R.serial_out.size(); ++i)
                        if (R.serial_out[i] != R.ref_out[i]) bw = false;
                    if (!bw) { ok = false; if (fail_reason.empty()) fail_reason = "single-device serial not bitwise-identical to reference"; }
                }
                if (!ok) {
                    all_pass = false;
                    if (fail_reason.empty()) fail_reason = "validation failed";
                }
            }
        } catch (const ComputeFailure &) {
            record_compute_failure();
            pcpu.free_plan();
            psec.free_plan();
            return false;
        }
        pcpu.free_plan();
        psec.free_plan();
        return true;
    };

    auto make_input = [&](ArmContext & A, int rep, bool & ok) {
        ok = true;
        if (!H.inputs_file.empty()) {
            if (!read_inputs_file(H.inputs_file, A.cur, H.T, err)) { fprintf(stderr, "error: %s\n", err.c_str()); ok = false; }
        } else {
            gen_input(A.cur, H.T, mix64(H.seed ^ (uint64_t)(0x1000 + rep)));
        }
    };

    // ---- warmup (discarded; warms allocator, code paths and device graphs) --
    int warmup_runs = 0;
    for (int w = 0; w < H.warmup; ++w) {
        ++warmup_runs;
        ArmContext A;
        RepResult R;
        bool ok = false;
        make_input(A, -1, ok);
        if (!ok) return 4;
        run_rep(A, R, true, /*validate=*/false);
        if (g_compute_failed) {
            fprintf(stderr, "error: warmup compute failed: %s\n", g_compute_fail_stage.c_str());
            break;
        }
    }

    // optional status-failure injection control: prove that a failed compute
    // refuses to reach any comparison (the run must terminate non-passing
    // with the stage recorded; no stale-output use)
    bool status_negative = H.status_negative;
    if (status_negative) {
        g_compute_failed = true;
        g_compute_fail_stage = "injected failure (self-check-status-negative)";
    }

    // ---- timed repetitions ----------------------------------------------------
    std::vector<RepResult> results;
    J.begin_arr("reps");
    for (int r = 0; r < H.reps && !g_compute_failed; ++r) {
        ArmContext A;
        RepResult R;
        bool ok = false;
        make_input(A, r, ok);
        if (!ok) return 4;
        if (!run_rep(A, R, /*serial_first=*/ (r % 2) == 0, /*validate=*/true, r)) break;
        // isolation: distinct generated inputs must produce distinct reference
        // outputs. With --inputs-file every repetition replays the same
        // captured activations by definition, so distinctness is not a valid
        // demand there (the determinism recheck below still applies).
        if (r > 0 && H.inputs_file.empty()) {
            bool differ = false;
            for (size_t i = 0; i < R.ref_out.size(); ++i)
                if (R.ref_out[i] != results.back().ref_out[i]) { differ = true; break; }
            if (!differ) { all_pass = false; if (fail_reason.empty()) fail_reason = "isolation failure: distinct inputs produced identical outputs"; }
        }
        results.push_back(R);
        J.obj();
        J.num("rep", r);
        J.boolean("serial_first", (r % 2) == 0);
        J.num("router_ms", R.router_ms);
        J.num("build_ms", R.build_ms);
        J.num("serial_ms", R.serial_ms);
        J.num("overlap_ms", R.overlap_ms);
        J.begin("serial_stages");
        J.num("h2d_ms", R.st_serial.h2d_ms);
        J.num("cpu_ms", R.st_serial.cpu_ms);
        J.num("sec_ms", R.st_serial.sec_ms);
        J.num("d2h_ms", R.st_serial.d2h_ms);
        J.num("combine_ms", R.st_serial.combine_ms);
        J.end();
        J.begin("overlap_stages");
        J.num("h2d_submit_ms", R.st_overlap.h2d_ms);
        J.num("cpu_ms", R.st_overlap.cpu_ms);
        J.num("d2h_ms", R.st_overlap.d2h_ms);
        J.num("combine_ms", R.st_overlap.combine_ms);
        J.end();
        J.num("k_cpu", (double)R.k_cpu);
        J.num("k_sec", (double)R.k_sec);
        J.num("k_cpu_real", (double)R.k_cpu_real);
        J.num("k_sec_real", (double)R.k_sec_real);
        J.begin("checks");
        J.boolean("routed_counts_ok", R.counts_ok);
        J.boolean("serial_vs_ref_pass", R.serial_vs_ref.pass);
        J.num("serial_vs_ref_max_abs", R.serial_vs_ref.max_abs);
        J.num("serial_vs_ref_max_ratio", R.serial_vs_ref.max_ratio);
        // Explicit name for new consumers; old fields/gates remain unchanged.
        J.begin("legacy_cpu_unsplit_diagnostic");
        J.boolean("pass", R.serial_vs_ref.pass);
        J.num("max_abs", R.serial_vs_ref.max_abs);
        J.num("max_ratio", R.serial_vs_ref.max_ratio);
        J.end();
        J.boolean("overlap_vs_serial_bitwise", R.overlap_vs_serial.bitwise_equal);
        J.boolean("overlap_vs_serial_pass", R.overlap_vs_serial.pass);
        if (R.overlap_vs_serial.max_abs > 0) J.num("overlap_vs_serial_max_abs", R.overlap_vs_serial.max_abs);
        J.end();
        J.end();
    }
    J.end_arr();

    // determinism/reuse recheck: rep 0's inputs must reproduce rep 0 exactly
    if (!g_compute_failed && !results.empty()) {
        ArmContext A;
        RepResult R;
        bool ok = false;
        make_input(A, 0, ok);
        if (!ok) return 4;
        if (run_rep(A, R, true, /*validate=*/false)) {
            bool bw = (R.ref_out.size() == results[0].ref_out.size());
            for (size_t i = 0; bw && i < R.ref_out.size(); ++i) if (R.ref_out[i] != results[0].ref_out[i]) bw = false;
            bool bw_serial = (R.serial_out.size() == results[0].serial_out.size());
            for (size_t i = 0; bw_serial && i < R.serial_out.size(); ++i) if (R.serial_out[i] != results[0].serial_out[i]) bw_serial = false;
            J.begin("determinism_recheck");
            J.boolean("reference_bitwise", bw);
            J.boolean("serial_bitwise", bw_serial);
            J.end();
            if (!bw || !bw_serial) { all_pass = false; if (fail_reason.empty()) fail_reason = "determinism recheck failed (stale buffer reuse suspected)"; }
        }
    }

    // ---- negative control (comparator sensitivity) -----------------------------
    if (H.negative_control && !g_compute_failed) {
        // Recompute the serial output with the shared branch omitted from the
        // combine; the validator must reject it. Proves a missing branch
        // cannot silently pass.
        ArmContext A;
        bool ok = false;
        make_input(A, 0, ok);
        if (!ok) return 4;
        Plan pcpu, psec;
        auto run_negative = [&]() {
            run_router(A);
            PaddingFail pfail;
            partition_routing(A, H.T, H.split, H.n_expert, pfail);
            if (pfail.duplicate_genuine || pfail.slots_needed > 0) {
                all_pass = false;
                fail_reason = "negative control: invalid routing structure (token " +
                    std::to_string(pfail.token) + ")";
                return;
            }
            if (A.k_cpu > 0) pcpu = build_expert_plan(H.cpu_bk, H.prim, A.k_cpu, H.T, false);
            if (A.k_sec > 0) psec = build_expert_plan(H.sec_bk, H.sec, A.k_sec, H.T, false);
            if ((A.k_cpu > 0 && !pcpu.ok()) || (A.k_sec > 0 && !psec.ok())) {
                all_pass = false;
                fail_reason = "negative-control plan allocation failed";
                return;
            }
            std::vector<float> ref_out, ref_planes;
            run_reference(A, ref_out, ref_planes);
            std::vector<float> partial_cpu((size_t)(N_EMBD * H.T), 0.0f), partial_sec((size_t)(N_EMBD * H.T), 0.0f);
            if (pcpu.ok()) {
                set_plan_inputs_blocking(pcpu, A, A.ids_cpu, A.w_cpu);
                check_compute(ggml_backend_graph_compute(H.cpu_bk, pcpu.gf), "primary experts");
                ggml_backend_synchronize(H.cpu_bk);
                ggml_backend_tensor_get(pcpu.out, partial_cpu.data(), 0, sizeof(float) * partial_cpu.size());
            }
            if (psec.ok()) {
                set_plan_inputs_blocking(psec, A, A.ids_sec, A.w_sec);
                check_compute(ggml_backend_graph_compute(H.sec_bk, psec.gf), "secondary experts");
                ggml_backend_synchronize(H.sec_bk);
                ggml_backend_tensor_get(psec.out, partial_sec.data(), 0, sizeof(float) * partial_sec.size());
            }
            std::vector<float> no_shared((size_t)(N_EMBD * H.T), 0.0f);
            for (size_t i = 0; i < no_shared.size(); ++i) no_shared[i] = partial_cpu[i] + partial_sec[i];
            bool cross = (A.k_sec > 0) && (H.secondary_kind != "cpu");
            CheckResult neg = validate_vs_reference(no_shared, ref_out, ref_planes, N_USED, H.T, cross);
            J.begin("negative_control");
            J.str("perturbation", "shared branch omitted from combine");
            J.boolean("comparator_rejected", !neg.pass);
            J.num("max_ratio", neg.max_ratio);
            J.end();
            if (neg.pass) { all_pass = false; if (fail_reason.empty()) fail_reason = "negative control NOT rejected (comparator insensitive)"; }
        };
        try {
            run_negative();
        } catch (const ComputeFailure &) {
            record_compute_failure();
        }
        pcpu.free_plan();
        psec.free_plan();
    }

    // optional last-rep arm-output dumps for external validation (F32,
    // little-endian, [N_EMBD * T]); only valid when the run is not failed
    if ((!H.dump_serial.empty() || !H.dump_overlap.empty()) && all_pass && !g_compute_failed && !results.empty()) {
        auto dump = [](const std::string & path, const std::vector<float> & v, bool & ok) {
            if (path.empty()) return;
            FILE * f = fopen(path.c_str(), "wb");
            if (!f) { ok = false; return; }
            fwrite(v.data(), sizeof(float), v.size(), f);
            fclose(f);
        };
        bool dump_ok = !g_compute_failed;
        dump(H.dump_serial, results.back().serial_out, dump_ok);
        dump(H.dump_overlap, results.back().overlap_out, dump_ok);
        J.begin("output_dumps");
        J.boolean("ok", dump_ok);
        if (!H.dump_serial.empty()) J.str("serial", H.dump_serial);
        if (!H.dump_overlap.empty()) J.str("overlap", H.dump_overlap);
        J.num("elements", (double)(N_EMBD * H.T));
        J.end();
        if (!dump_ok) { all_pass = false; if (fail_reason.empty()) fail_reason = "output dump failed"; }
    }

    // optional last-rep split-routing dump for external structural validation
    // (JSON: per-device padded id/weight matrices exactly as presented to the
    // native MUL_MAT_ID operation); only valid when the run is not failed
    if (!H.dump_routing.empty() && all_pass && !g_compute_failed && !results.empty()) {
        FILE * f = fopen(H.dump_routing.c_str(), "w");
        if (!f) {
            all_pass = false;
            if (fail_reason.empty()) fail_reason = "routing dump failed";
        } else {
            JsonOut D;
            D.begin("routing");
            D.num("tokens", (double)H.T);
            D.num("n_expert", (double)H.n_expert);
            D.num("split", (double)H.split);
            D.num("k_cpu", (double)H.last_k_cpu);
            D.num("k_sec", (double)H.last_k_sec);
            D.num("k_cpu_real", (double)H.last_kr_cpu);
            D.num("k_sec_real", (double)H.last_kr_sec);
            auto arr = [&](const char * name, const std::vector<int32_t> & v) {
                D.begin_arr(name);
                for (size_t i = 0; i < v.size(); ++i) {
                    char b[24];
                    snprintf(b, sizeof b, "%s%lld", i ? "," : "", (long long)v[i]);
                    D.s += b;
                }
                D.end_arr();
            };
            arr("ids_all", H.last_ids_all);
            arr("ids_cpu", H.last_ids_cpu);
            arr("ids_sec", H.last_ids_sec);
            D.begin_arr("w_cpu");
            for (size_t i = 0; i < H.last_w_cpu.size(); ++i) {
                // exact bit pattern of the float weight (distinguishes +0.0)
                uint32_t bits; std::memcpy(&bits, &H.last_w_cpu[i], 4);
                char b[32];
                snprintf(b, sizeof b, "%" PRIu32 "%s", bits,
                         i + 1 < H.last_w_cpu.size() ? "," : "");
                D.s += b;
            }
            D.end_arr();
            auto wbits = [&](const char * name, const std::vector<float> & w) {
                D.begin_arr(name);
                for (size_t i = 0; i < w.size(); ++i) {
                    // exact bit pattern of the float weight (distinguishes +0.0)
                    uint32_t bits; std::memcpy(&bits, &w[i], 4);
                    char b[32];
                    snprintf(b, sizeof b, "%" PRIu32 "%s", bits,
                             i + 1 < w.size() ? "," : "");
                    D.s += b;
                }
                D.end_arr();
            };
            wbits("w_all", H.last_w_all);
            wbits("w_cpu", H.last_w_cpu);
            wbits("w_sec", H.last_w_sec);
            D.end();
            fprintf(f, "{\n%s\n}\n", D.s.c_str());
            fclose(f);
            J.begin("routing_dump");
            J.str("path", H.dump_routing);
            J.end();
        }
    }

    // ---- summary ----------------------------------------------------------------
    {
        auto med = [](std::vector<double> v) {
            if (v.empty()) return 0.0;
            std::sort(v.begin(), v.end());
            return v[v.size() / 2];
        };
        std::vector<double> sv, ov;
        for (auto & r : results) { sv.push_back(r.serial_ms); ov.push_back(r.overlap_ms); }
        double sm = med(sv), om = med(ov);
        J.begin("summary");
        J.num("serial_median_ms", sm);
        J.num("overlap_median_ms", om);
        J.num("serial_min_ms", sv.empty() ? 0 : *std::min_element(sv.begin(), sv.end()));
        J.num("overlap_min_ms", ov.empty() ? 0 : *std::min_element(ov.begin(), ov.end()));
        J.num("overlap_to_serial_ratio", sm > 0 ? om / sm : 0.0);
        J.num("serial_minus_overlap_ms", sm - om);
        J.end();
    }

    if (g_compute_failed) {
        all_pass = false;
        fail_reason = "graph compute failed: " + g_compute_fail_stage;
    }
    J.begin("verdict");
    J.boolean("pass", all_pass);
    J.num("warmup_runs", (double)warmup_runs);
    if (H.status_negative) {
        // expected outcome of the injection: the run refuses to pass and the
        // reason names the injected failed stage (never a comparison result)
        J.boolean("status_negative_control_refused", !all_pass && fail_reason.find("injected failure") != std::string::npos);
    }
    J.str("reason", all_pass ? "all correctness gates passed" : fail_reason);
    J.str("timing_claim",
          !H.reference_case.empty() ? "untimed numerical-reference exports present: timing is NOT performance evidence"
          : H.secondary_kind == "cuda"
              ? "single-node CPU/GPU overlap measurement (hardware run)"
              : "secondary is a CPU backend: scheduling/dependency correctness only; overlap timing is NOT meaningful offline (thread pools contend on one host)");
    J.end();

    // ---- release -----------------------------------------------------------------
    H.router_plan.free_plan();
    H.shared_plan.free_plan();
    H.ref_plan.free_plan();
    H.full.free_slice();
    H.prim.free_slice();
    H.sec.free_slice();
    if (H.W.ctx) ggml_free(H.W.ctx);
    if (H.sec_bk) ggml_backend_free(H.sec_bk);
    if (H.cpu_bk) ggml_backend_free(H.cpu_bk);
    J.boolean("resources_released", true);

    std::string json = "{\n" + J.s + "\n}\n";
    if (!H.reference_case.empty()) {
        std::string path = H.reference_case + "/run.json";
        FILE * f = fopen(path.c_str(), "wb");
        if (!f) { fprintf(stderr, "error: cannot write reference-case run.json\n"); return 4; }
        bool ok = fwrite(json.data(), 1, json.size(), f) == json.size();
        if (fclose(f) != 0) ok = false;
        if (!ok) { fprintf(stderr, "error: incomplete reference-case run.json\n"); return 4; }
    }
    if (!H.json_path.empty()) {
        FILE * f = fopen(H.json_path.c_str(), "w");
        if (!f) { fprintf(stderr, "error: cannot write %s\n", H.json_path.c_str()); return 4; }
        fwrite(json.data(), 1, json.size(), f);
        fclose(f);
    }
    printf("%s", json.c_str());
    return all_pass ? 0 : 3;
}

static int list_devices() {
    size_t n = ggml_backend_dev_count();
    printf("devices: %zu\n", n);
    for (size_t d = 0; d < n; ++d) {
        ggml_backend_dev_t dev = ggml_backend_dev_get(d);
        const char * kind = "?";
        switch (ggml_backend_dev_type(dev)) {
            case GGML_BACKEND_DEVICE_TYPE_CPU: kind = "CPU"; break;
            case GGML_BACKEND_DEVICE_TYPE_GPU: kind = "GPU"; break;
            default: break;
        }
        printf("  %zu: %s [%s] %s\n", d, ggml_backend_dev_name(dev), kind, ggml_backend_dev_description(dev));
    }
    return 0;
}

int main(int argc, char ** argv) {
    if (std::getenv("MOE_OVERLAP_UNIT_ROUTING")) return unit_routing_run();
    Harness H;
    for (int i = 1; i < argc; ++i) {
        std::string a = argv[i];
        auto next = [&](const char * what) -> std::string {
            if (i + 1 >= argc) { fprintf(stderr, "error: %s needs a value\n", what); exit(2); }
            return argv[++i];
        };
        if (a == "--gguf") { H.mode = "gguf"; H.gguf_path = next("--gguf"); }
        else if (a == "--layer") H.layer = atoi(next("--layer").c_str());
        else if (a == "--synthetic") H.mode = "synthetic";
        else if (a == "--experts") H.n_expert = atoll(next("--experts").c_str());
        else if (a == "--seed") H.seed = strtoull(next("--seed").c_str(), nullptr, 0);
        else if (a == "--tokens") H.T = atoll(next("--tokens").c_str());
        else if (a == "--split") H.split = atoll(next("--split").c_str());
        else if (a == "--secondary") H.secondary_kind = next("--secondary");
        else if (a == "--threads") H.threads = atoi(next("--threads").c_str());
        else if (a == "--secondary-threads") H.secondary_threads = atoi(next("--secondary-threads").c_str());
        else if (a == "--warmup") H.warmup = atoi(next("--warmup").c_str());
        else if (a == "--reps") H.reps = atoi(next("--reps").c_str());
        else if (a == "--inputs-file") H.inputs_file = next("--inputs-file");
        else if (a == "--json") H.json_path = next("--json");
        else if (a == "--self-check-negative") H.negative_control = true;
        else if (a == "--self-check-status-negative") H.status_negative = true;
        else if (a == "--dump-serial") H.dump_serial = next("--dump-serial");
        else if (a == "--dump-overlap") H.dump_overlap = next("--dump-overlap");
        else if (a == "--dump-routing") H.dump_routing = next("--dump-routing");
        else if (a == "--dump-reference-case") H.reference_case = next("--dump-reference-case");
        else if (a == "--list-devices") return list_devices();
        else if (a == "--help" || a == "-h") {
            printf("usage: %s [--gguf <shard> --layer N | --synthetic [--experts N] [--seed S]]\n"
                   "  --tokens T (1 = decode, 128 = prefill) [--split S] [--secondary cpu|cuda]\n"
                   "  [--threads N] [--secondary-threads N] [--warmup W] [--reps R]\n"
                   "  [--inputs-file <f32 block activations>] [--json out.json]\n"
                   "  [--self-check-negative] [--self-check-status-negative]\n"
                   "  [--dump-serial PATH] [--dump-overlap PATH] [--dump-routing PATH]\n"
                   "  [--dump-reference-case NEW_DIR] (independent offline numerical check)\n"
                   "  [--list-devices]\n", argv[0]);
            return 0;
        }
        else { fprintf(stderr, "error: unknown arg %s\n", a.c_str()); return 2; }
    }
    if (H.T < 1) { fprintf(stderr, "error: --tokens must be >= 1\n"); return 2; }
    if (H.mode == "gguf" && H.gguf_path.empty()) { fprintf(stderr, "error: --gguf needs a path\n"); return 2; }
    if (H.mode == "synthetic" && H.n_expert < N_USED) { fprintf(stderr, "error: --experts must be >= %lld\n", (long long)N_USED); return 2; }
    if (H.split < 0 || H.split > H.n_expert) { fprintf(stderr, "error: --split out of range\n"); return 2; }
    if (H.secondary_kind != "cpu" && H.secondary_kind != "cuda") { fprintf(stderr, "error: --secondary must be cpu or cuda\n"); return 2; }
    return run_harness(H);
}
