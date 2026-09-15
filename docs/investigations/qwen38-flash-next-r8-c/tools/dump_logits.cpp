// R8-C Phase 4 diagnostic-only logits dumper (Issue #193).
// Compiled against the EXACT pinned llama.cpp b29c606e build's shared
// libraries (libllama.so, libllama-common.so, libggml*). Observation only:
// identical load path (common_init_from_params incl. fit), identical decode;
// we only READ llama_get_logits_ith after llama_decode and perform argmax
// locally. Non-perturbation proof: the tool's greedy token stream must
// reproduce the accepted R8-B arm outputs byte-exactly.
//
// Usage:
//   dump_logits --mode generate|teacher -m MODEL -c CTX -ngl N
//     [--rpc host:port,...] [-ot pat=BUFT,...] --prompt-ids id,id,...
//     [--prefix-ids id,id,...] -n N --out PREFIX
// "generate": decode prompt then N greedy steps, dump full-vocab fp32 row
//             per step to PREFIX.bin, meta to PREFIX.json (tokens + top-20).
// "teacher":  decode prompt+prefix once, dump the single next-token row.
#include "llama.h"
#include "common.h"
#include "ggml-rpc.h"
#include "log.h"
#include <atomic>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <list>
#include <map>
#include <random>
#include <algorithm>
#include <string>
#include <vector>

static std::vector<llama_token> parse_ids(const std::string & s) {
    std::vector<llama_token> v; size_t p0 = 0;
    while (true) { size_t c = s.find(',', p0); if (c == std::string::npos) { v.push_back((llama_token)atoi(s.substr(p0).c_str())); break; } v.push_back((llama_token)atoi(s.substr(p0, c - p0).c_str())); p0 = c + 1; }
    return v;
}

static void add_rpc_devices(const std::string & servers) {
    ggml_backend_load_all();
    auto fn = &ggml_backend_rpc_add_server;
    size_t p0 = 0;
    while (true) {
        size_t c = servers.find(',', p0);
        std::string ep = (c == std::string::npos) ? servers.substr(p0) : servers.substr(p0, c - p0);
        ggml_backend_reg_t reg = fn(ep.c_str());
        if (reg) ggml_backend_register(reg);
        if (c == std::string::npos) break;
        p0 = c + 1;
    }
}

static void parse_ot(const std::string & value, std::vector<llama_model_tensor_buft_override> & ov) {
    std::map<std::string, ggml_backend_buffer_type_t> buft_list;
    for (size_t i = 0; i < ggml_backend_dev_count(); ++i) {
        auto * dev = ggml_backend_dev_get(i);
        auto * buft = ggml_backend_dev_buffer_type(dev);
        if (buft) buft_list[ggml_backend_buft_name(buft)] = buft;
    }
    static std::list<std::string> keep;
    size_t p0 = 0;
    while (true) {
        size_t c = value.find(',', p0);
        std::string o = (c == std::string::npos) ? value.substr(p0) : value.substr(p0, c - p0);
        size_t e = o.find('=');
        if (e == std::string::npos) { fprintf(stderr, "bad -ot\n"); exit(2); }
        std::string pat = o.substr(0, e), bt = o.substr(e + 1);
        if (!buft_list.count(bt)) {
            fprintf(stderr, "unknown buffer type '%s'; available:\n", bt.c_str());
            for (auto & kv : buft_list) fprintf(stderr, "  %s\n", kv.first.c_str());
            exit(2);
        }
        keep.push_back(pat);
        ov.push_back({keep.back().c_str(), buft_list.at(bt)});
        if (c == std::string::npos) break;
        p0 = c + 1;
    }
}

int main(int argc, char ** argv) {
    std::string mode = "generate", model, out, rpc, ot, sampler = "greedy";
    int n_predict = 8, ctx = 8192; int64_t ngl = -1;
    std::vector<llama_token> prompt, prefix;
    for (int i = 1; i < argc; ++i) {
        std::string a = argv[i];
        auto next = [&]() -> std::string { return (i + 1 < argc) ? argv[++i] : ""; };
        if (a == "--mode") mode = next();
        else if (a == "-m") model = next();
        else if (a == "--out") out = next();
        else if (a == "-n") n_predict = atoi(next().c_str());
        else if (a == "-c") ctx = atoi(next().c_str());
        else if (a == "-ngl") ngl = atoll(next().c_str());
        else if (a == "--rpc") rpc = next();
        else if (a == "-ot") ot = next();
        else if (a == "--prompt-ids") prompt = parse_ids(next());
        else if (a == "--prefix-ids") prefix = parse_ids(next());
        else if (a == "--sampler") sampler = next();
        else { fprintf(stderr, "unknown arg %s\n", a.c_str()); return 2; }
    }
    if (model.empty() || out.empty() || prompt.empty()) { fprintf(stderr, "need -m --out --prompt-ids\n"); return 2; }

    if (!rpc.empty()) add_rpc_devices(rpc);

    common_params p;
    p.model.path = model;
    p.n_ctx = ctx;
    p.n_gpu_layers = ngl;
    if (!ot.empty()) parse_ot(ot, p.tensor_buft_overrides);
    p.tensor_buft_overrides.push_back({nullptr, nullptr});  // terminator: fit requires the buffer even when empty
    p.cpuparams.n_threads = 14;        // bypassing common_params_parse skips postprocess_cpu_params;
    p.cpuparams_batch.n_threads = 14;  // -1 would reach the threadpool as (uint)-1 -> 16TiB alloc
    p.no_perf = true;
    p.warmup = false;
    p.verbosity = (int) LOG_LEVEL_WARN;

    auto init = common_init_from_params(p);
    llama_model * ml = init->model();
    llama_context * ctxl = init->context();
    if (!ml || !ctxl) { fprintf(stderr, "init failed\n"); return 1; }
    const llama_vocab * vocab = llama_model_get_vocab(ml);
    const int n_vocab = llama_vocab_n_tokens(vocab);

    std::vector<llama_token> batch = prompt;
    if (mode == "teacher") { if (prefix.empty()) { fprintf(stderr, "teacher needs --prefix-ids\n"); return 2; } batch.insert(batch.end(), prefix.begin(), prefix.end()); }

    const int total_rows = (mode == "teacher") ? 1 : n_predict;
    std::vector<float> rows;
    rows.reserve((size_t)total_rows * n_vocab);
    std::vector<llama_token> toks;

    // dist replay implemented locally (std::mt19937 seed 0, one uniform draw per step,
    // cumulative-sum crossing over UNsorted vocab logits) — matches llama_sampler_init_dist(0)+apply semantics
    // without touching sampler-chain internals.
    std::mt19937 dist_rng(0);
    std::uniform_real_distribution<double> dist_uni(0.0, 1.0);

    auto decode_and_step = [&](std::vector<llama_token> & toks_in) -> llama_token {
        llama_batch b = llama_batch_get_one(toks_in.data(), (int)toks_in.size());
        if (llama_decode(ctxl, b)) { fprintf(stderr, "decode failed\n"); exit(1); }
        const float * lg = llama_get_logits_ith(ctxl, -1);
        rows.insert(rows.end(), lg, lg + n_vocab);
        if (sampler == "dist") {
            float max_l = lg[0];
            for (int i = 1; i < n_vocab; ++i) if (lg[i] > max_l) max_l = lg[i];
            double sum_cum = 0.0;
            std::vector<double> pr(n_vocab);
            for (int i = 0; i < n_vocab; ++i) { float p = expf(lg[i] - max_l); pr[i] = p; sum_cum += p; }
            const double rnd = dist_uni(dist_rng);
            const double sum_tgt = sum_cum * rnd;
            double sum_run = 0.0;
            for (int i = 0; i < n_vocab; ++i) { sum_run += pr[i]; if (sum_run >= sum_tgt) return (llama_token) i; }
            return (llama_token)(n_vocab - 1);
        }
        int best = 0;
        for (int i = 1; i < n_vocab; ++i) if (lg[i] > lg[best]) best = i;
        return (llama_token) best;
    };

    llama_token t = decode_and_step(batch);
    toks.push_back(t);
    int steps = (mode == "teacher") ? 0 : (n_predict - 1);
    for (int s = 0; s < steps; ++s) {
        std::vector<llama_token> one = {toks.back()};
        t = decode_and_step(one);
        toks.push_back(t);
    }

    // write binary rows
    std::ofstream bin(out + ".bin", std::ios::binary);
    bin.write((const char *) rows.data(), rows.size() * sizeof(float));
    // meta json (manual, minimal)
    FILE * j = fopen((out + ".json").c_str(), "w");
    fprintf(j, "{\"mode\":\"%s\",\"sampler\":\"%s\",\"n_vocab\":%d,\"n_rows\":%zu,\"tokens\":[", mode.c_str(), sampler.c_str(), n_vocab, rows.size() / n_vocab);
    for (size_t i = 0; i < toks.size(); ++i) fprintf(j, "%s%d", i ? "," : "", toks[i]);
    fprintf(j, "],\"prompt_len\":%zu}\n", batch.size());
    fclose(j);
    // stdout summary: tokens + per-row top-5
    printf("tokens=[");
    for (size_t i = 0; i < toks.size(); ++i) printf("%s%d", i ? "," : "", toks[i]);
    printf("]\n");
    for (size_t r = 0; r < rows.size() / n_vocab && r < 8; ++r) {
        const float * lg = rows.data() + r * n_vocab;
        std::vector<int> idx(n_vocab); for (int i = 0; i < n_vocab; ++i) idx[i] = i;
        std::partial_sort(idx.begin(), idx.begin() + 5, idx.end(), [&](int a, int b){ return lg[a] > lg[b]; });
        printf("row%zu top5: ", r);
        for (int k = 0; k < 5; ++k) printf("%d:%.4f ", idx[k], lg[idx[k]]);
        float mx = lg[idx[0]];
        printf("| margin12=%.4f\n", mx - lg[idx[1]]);
    }
    return 0;
}
