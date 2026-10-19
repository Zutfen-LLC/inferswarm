// #314: private source-built expert graphs, existing RPC dispatcher, no fallback.
#include "llama-hot-experts.h"
#include "llama-moe-overlap.h"
#include "llama-graph.h"
#include "llama-model.h"
#include "llama-cparams.h"
#include "llama-context.h"
#include "ggml-alloc.h"
#include "ggml-cpu.h"
#include "ggml-rpc.h"
#include "ggml-impl.h"
#include "demand.h"
#include "../vendor/nlohmann/json.hpp"
extern "C" {
#include "../vendor/hash/sha256/sha256.h"
}
#include <algorithm>
#include <chrono>
#include <array>
#include <cstring>
#include <fstream>
#include <set>
#include <stdexcept>
#include <thread>
#include <unordered_map>

namespace {
void check(bool ok, const char * why) { if (!ok) throw std::runtime_error(std::string("IS314: ") + why); }
std::string sha(const void * data, size_t size) {
    uint8_t hash[32]; sha256_hash(hash, static_cast<const uint8_t *>(data), size);
    const char * hex = "0123456789abcdef"; std::string result;
    for (auto b : hash) { result += hex[b >> 4]; result += hex[b & 15]; }
    return result;
}
void compute(ggml_backend_t backend, ggml_cgraph * graph) {
    if (ggml_backend_graph_compute(backend, graph) != GGML_STATUS_SUCCESS) GGML_ABORT("IS314 CPU branch failed");
}
ggml_tensor * clone(ggml_context * ctx, ggml_tensor * t, std::unordered_map<ggml_tensor *, ggml_tensor *> & cuts) {
    auto found = cuts.find(t); if (found != cuts.end()) return found->second;
    if (t->op == GGML_OP_NONE) { check(t->buffer, "unallocated source leaf"); return t; }
    auto * copy = ggml_dup_tensor(ctx, t); cuts[t] = copy; copy->op = t->op;
    std::memcpy(copy->op_params, t->op_params, sizeof(t->op_params));
    std::memcpy(copy->nb, t->nb, sizeof(t->nb)); ggml_set_name(copy, t->name);
    for (int i = 0; i < GGML_MAX_SRC; ++i) if (t->src[i]) copy->src[i] = clone(ctx, t->src[i], cuts);
    if (t->view_src) { copy->view_src = clone(ctx, t->view_src, cuts); copy->view_offs = t->view_offs; }
    return copy;
}
}
void llama_hot_bind_routing(ggml_context * ctx, ggml_tensor * combined, int layer,
                            const llama_hot_routing & routing) {
    auto * weighted=ggml_get_tensor(ctx,("ffn_moe_weighted-"+std::to_string(layer)).c_str());
    check(weighted && weighted->src[0]->op==GGML_OP_MUL_MAT_ID,"benchmark source routing cut missing");
    auto * ids=weighted->src[0]->src[2];
    check(routing.ids && routing.weights && routing.ids->buffer && routing.weights->buffer,
          "benchmark routing leaves must be allocated");
    check(routing.ids->type==GGML_TYPE_I32 && routing.ids->ne[0]==10 && routing.ids->ne[1]==1 &&
          ggml_nelements(routing.ids)==10 && routing.weights->type==GGML_TYPE_F32 &&
          routing.weights->ne[0]==1 && routing.weights->ne[1]==10 && ggml_nelements(routing.weights)==10 &&
          ggml_is_contiguous(routing.ids) && ggml_is_contiguous(routing.weights),"benchmark ten routing slots required");
    // Every gate/up/down MUL_MAT_ID refers to the same original top-k view.
    // Cut all those references, not just the final down projection.
    std::set<ggml_tensor *> visited;
    std::vector<ggml_tensor *> pending={combined};
    while (!pending.empty()) {
        auto * t=pending.back(); pending.pop_back();
        if (!visited.insert(t).second) continue;
        for (auto & source:t->src) {
            if (source==ids) source=routing.ids;
            if (source) pending.push_back(source);
        }
    }
    weighted->src[1]=routing.weights;
}
void llama_hot_bind_routing_batch(ggml_context * ctx, ggml_tensor * combined, int layer,
                                  const llama_hot_routing_batch & routing) {
    // Same cut as llama_hot_bind_routing, extended to a [K,T] per-token
    // boundary. The source builder is token-generic: mul_mat_id consumes
    // ids [n_expert_used, T] and weights [1, n_expert_used, T], so only the
    // bind-time shape checks change.
    auto * weighted=ggml_get_tensor(ctx,("ffn_moe_weighted-"+std::to_string(layer)).c_str());
    check(weighted && weighted->src[0]->op==GGML_OP_MUL_MAT_ID,"batch benchmark source routing cut missing");
    auto * ids=weighted->src[0]->src[2];
    check(routing.ids && routing.weights && routing.ids->buffer && routing.weights->buffer,
          "batch benchmark routing leaves must be allocated");
    const int64_t T=routing.ids->ne[1];
    check(routing.ids->type==GGML_TYPE_I32 && routing.ids->ne[0]==10 && T>=1 &&
          routing.weights->type==GGML_TYPE_F32 && routing.weights->ne[0]==1 &&
          routing.weights->ne[1]==10 && routing.weights->ne[2]==T &&
          ggml_is_contiguous(routing.ids) && ggml_is_contiguous(routing.weights),
          "batch benchmark ten routing slots per token required");
    std::set<ggml_tensor *> visited;
    std::vector<ggml_tensor *> pending={combined};
    while (!pending.empty()) {
        auto * t=pending.back(); pending.pop_back();
        if (!visited.insert(t).second) continue;
        for (auto & source:t->src) {
            if (source==ids) source=routing.ids;
            if (source) pending.push_back(source);
        }
    }
    weighted->src[1]=routing.weights;
}
void llama_hot_set_phase(llama_context * ctx,int phase) { ctx->synchronize(); ctx->set_hot_phase(phase); }
struct llama_hot_spec { nlohmann::json document; };
llama_moe_overlap_config llama_hot_config(int n_layer) {
    check(!std::getenv("IS309_MOE"), "IS309_MOE and IS314_HOT_SPEC are exclusive");
    const char * path = std::getenv("IS314_HOT_SPEC");
    check(path && *path, "nonempty native spec path required");
    std::ifstream file(path, std::ios::binary); check(file.good(), "native spec open failed");
    std::string bytes((std::istreambuf_iterator<char>(file)), {});
    check(bytes.size() <= (1u << 20), "native spec too large");
    auto spec = std::make_shared<llama_hot_spec>();
    spec->document = nlohmann::json::parse(bytes);
    const auto & j = spec->document;
    check(j.at("schema") == "is314-hot-experts/1", "native spec schema");
    check(j.at("layer").is_number_integer(), "layer must be integer");
    const int layer = j.at("layer").get<int>(); check(layer >= 0 && layer < n_layer, "layer outside model");
    check(j.at("expert_ids").is_array() && j.at("expert_ids").size() <= 512, "expert list bound");
    std::set<int> seen;
    for (const auto & id : j.at("expert_ids")) {
        check(id.is_number_integer() && id.get<int>() >= 0 && seen.insert(id.get<int>()).second, "invalid/duplicate expert ID");
    }
    check(j.at("tensors").is_array() && j.at("tensors").size() == 3, "exactly three expert tensors required");
    llama_moe_overlap_config cfg; cfg.layer = layer; cfg.overlap = true; cfg.hot_spec = spec; return cfg;
}

class llama_hot_experts {
public:
    std::shared_ptr<llama_hot_spec> spec;
    ggml_backend_t rpc = nullptr;
    ggml_context * ctx = nullptr;
    ggml_backend_buffer_t buffer = nullptr;
    std::array<ggml_tensor *, 3> original = {}, compact = {};
    std::vector<int32_t> dense;
    std::shared_ptr<llama_hot_graph> graph;
    size_t resident = 0, staging_peak = 0;
    ~llama_hot_experts() { graph.reset(); ggml_backend_buffer_free(buffer); ggml_free(ctx); }

    void setup(const llama_moe_overlap_config & cfg, const llama_layer & layer, ggml_backend_sched_t sched) {
        spec = cfg.hot_spec; const auto & j = spec->document;
        const auto ids = j.at("expert_ids").get<std::vector<int32_t>>();
        original = {layer.ffn_gate_exps, layer.ffn_up_exps, layer.ffn_down_exps};
        check(!layer.ffn_gate_up_exps && !layer.ffn_up_exps_s && !layer.ffn_gate_exps_s && !layer.ffn_down_exps_s,
              "only separate unscaled gate/up/down banks supported");
        check(original[0] && original[1] && original[2], "missing source banks");
        dense.assign(original[0]->ne[2], -1);
        for (size_t i = 0; i < ids.size(); ++i) { check(ids[i] < (int)dense.size(), "expert outside source bank"); dense[ids[i]] = i; }
        const auto registry_name = j.at("rpc_backend").get<std::string>();
        check(registry_name.rfind("RPC[",0)==0 && registry_name.back()==']', "GPU0 RPC registry name required");
        const auto backend_name = std::string("RPC0") + registry_name.substr(3);
        for (int i = 0; i < ggml_backend_sched_get_n_backends(sched); ++i) {
            auto b = ggml_backend_sched_get_backend(sched, i);
            if (ggml_backend_is_rpc(b) && backend_name == ggml_backend_name(b)) {
                check(!rpc, "ambiguous existing RPC backend"); rpc = b;
            }
        }
        check(rpc, "named existing context RPC backend missing");
        ctx = ggml_init({ggml_tensor_overhead()*4, nullptr, true}); check(ctx, "compact metadata allocation");
        std::set<std::string> names;
        // Validate ALL metadata and hashes before remote allocation/upload.
        std::array<const nlohmann::json *, 3> rows = {};
        for (const auto & row : j.at("tensors")) {
            const auto source = row.at("source_name").get<std::string>();
            size_t index = 0; while (index < 3 && source != original[index]->name) ++index;
            check(index < 3 && !rows[index], "source name missing/duplicate"); rows[index] = &row;
            auto * t = original[index];
            check(t->buffer && ggml_backend_buffer_is_host(t->buffer) && ggml_is_contiguous(t) && !t->view_src,
                  "source must be whole contiguous CPU bank");
            check(t->type == GGML_TYPE_Q8_0 || t->type == GGML_TYPE_F32, "source encoding unsupported");
            check(row.at("ggml_type").get<int>() == (int)t->type, "source type mismatch");
            auto shape = row.at("source_shape").get<std::vector<int64_t>>();
            auto small = row.at("compact_shape").get<std::vector<int64_t>>();
            check(shape.size()==4 && small.size()==4, "four-dimensional shapes required");
            for (int d=0; d<4; ++d) check(shape[d]==t->ne[d] && small[d]==(d==2 ? (int64_t)ids.size() : shape[d]), "source/compact shape mismatch");
            check(t->ne[2] == (int64_t)dense.size() && t->ne[3]==1, "expert count mismatch");
            const size_t stride = t->nb[2];
            check(row.at("expert_bytes").get<size_t>()==stride && ggml_nbytes(t)==stride*dense.size(), "encoded expert stride mismatch");
            check(row.at("source_sha256").get<std::string>() == sha(t->data,ggml_nbytes(t)), "source bytes identity mismatch");
            const auto name = row.at("compact_name").get<std::string>();
            check(!name.empty() && name.size()<GGML_MAX_NAME && name.rfind("is314.",0)==0 && names.insert(name).second,
                  "derived destination name invalid/duplicate");
            for (unsigned char c : name) check(c>32 && c<127, "derived name must be ASCII without whitespace");
            for (auto * source_tensor : original) check(name != source_tensor->name, "derived name aliases source");
            const auto & ranges = row.at("ranges"); check(ranges.is_array() && ranges.size()==ids.size(), "whole slice ranges required");
            // Streaming compact digest uses at most ONE compact staging tensor.
            std::vector<uint8_t> staging(stride*ids.size()); staging_peak=std::max(staging_peak,staging.size());
            for (size_t k=0; k<ids.size(); ++k) {
                const auto & r=ranges[k];
                check(r.at("expert_id").get<int>()==ids[k] && r.at("source_offset").get<size_t>()==size_t(ids[k])*stride &&
                    r.at("destination_offset").get<size_t>()==k*stride && r.at("length").get<size_t>()==stride,
                    "partial/view/reordered slice refused");
                std::memcpy(staging.data()+k*stride, static_cast<const uint8_t *>(t->data)+size_t(ids[k])*stride,stride);
            }
            check(row.at("compact_sha256").get<std::string>()==sha(staging.data(),staging.size()), "compact identity mismatch");
            if (!ids.empty()) {
                compact[index]=ggml_new_tensor_4d(ctx,t->type,t->ne[0],t->ne[1],ids.size(),1);
                ggml_set_name(compact[index],name.c_str()); resident+=staging.size();
            }
        }
        if (!ids.empty()) {
            buffer=ggml_backend_alloc_ctx_tensors(ctx,rpc); check(buffer,"compact backend allocation");
            ggml_backend_buffer_set_usage(buffer,GGML_BACKEND_BUFFER_USAGE_WEIGHTS);
            for (size_t i=0; i<3; ++i) {
                auto * t=original[i]; std::vector<uint8_t> staging(ggml_nbytes(compact[i]));
                for (size_t k=0; k<ids.size(); ++k) std::memcpy(staging.data()+k*t->nb[2],static_cast<const uint8_t *>(t->data)+size_t(ids[k])*t->nb[2],t->nb[2]);
                ggml_backend_tensor_set(compact[i],staging.data(),0,staging.size());
            }
        }
        ggml_backend_synchronize(rpc);
    }
};

struct hot_branch {
    ggml_cgraph * graph = nullptr;
    ggml_gallocr_t alloc = nullptr;
    ggml_tensor * input = nullptr, * ids = nullptr, * weights = nullptr, * output = nullptr;
};
llama_hot_stages llama_hot_retain_stages(ggml_tensor * weighted) {
    if (weighted->op==GGML_OP_CONT) weighted=weighted->src[0];
    check(weighted->op==GGML_OP_MUL,"benchmark weighted stage mismatch");
    auto * down=weighted->src[0];
    check(down->op==GGML_OP_MUL_MAT_ID,"benchmark down stage mismatch");
    auto * swiglu=down->src[1];
    check(swiglu->op==GGML_OP_GLU && ggml_get_glu_op(swiglu)==GGML_GLU_OP_SWIGLU,"benchmark SwiGLU stage mismatch");
    llama_hot_stages stages={swiglu->src[0],swiglu->src[1],swiglu,down,weighted};
    check(stages[0]->op==GGML_OP_MUL_MAT_ID && stages[1]->op==GGML_OP_MUL_MAT_ID,"benchmark projection stage mismatch");
    for (auto * tensor:stages) ggml_set_output(tensor);
    return stages;
}
class llama_hot_graph {
public:
    llama_hot_experts * owner = nullptr;
    ggml_context * ctx = nullptr;
    ggml_backend_t cpu = nullptr;
    hot_branch router, shared, reduce, fast;
    std::array<hot_branch,11> hot = {}, cold = {};
    ggml_tensor * input = nullptr, * ids = nullptr, * weights = nullptr, * slots = nullptr;
    ggml_tensor * bound_ids = nullptr;
    std::vector<float> remote_result;
    llama_hot_stats stats;
    llama_hot_stages stages{};
    const int * phase = nullptr;
    int layer = -1;
    size_t last_remote_uid = 0;
    // #346: one prebuilt graph set per token-batch width. Batch width is fixed
    // per llama_hot_graph; a sweep across widths builds one graph set per
    // width through the owner's shared compact experts and RPC connection.
    unsigned built_tokens = 1;
    ~llama_hot_graph() {
        for (auto * b : {&router,&shared,&reduce,&fast}) ggml_gallocr_free(b->alloc);
        for (auto & b : hot) ggml_gallocr_free(b.alloc);
        for (auto & b : cold) ggml_gallocr_free(b.alloc);
        ggml_backend_free(cpu); ggml_free(ctx);
    }
    void allocate(hot_branch & b, ggml_backend_t backend) {
        for (int i=0;i<b.graph->n_nodes;++i) check(ggml_backend_supports_op(backend,b.graph->nodes[i]),"unsupported source branch operation");
        for (int i=0;i<b.graph->n_leafs;++i) {
            auto t=b.graph->leafs[i]; if (t->buffer) check(ggml_backend_supports_buft(backend,ggml_backend_buffer_get_type(t->buffer)),"branch source placement mismatch");
        }
        b.alloc=ggml_gallocr_new(ggml_backend_get_default_buffer_type(backend));
        check(b.alloc && ggml_gallocr_alloc_graph(b.alloc,b.graph),"private arena allocation");
    }
    static void execute(ggml_tensor * dst,const ggml_tensor * src,int ith,int nth,void * data) {
        GGML_UNUSED(nth); if (ith) return;
        auto & s=*static_cast<llama_hot_graph *>(data);
        using clock=std::chrono::steady_clock;
        const auto start=clock::now();
        const auto elapsed=[](clock::time_point a,clock::time_point b){return std::chrono::duration<double,std::milli>(b-a).count();};
        s.stats.phase=s.phase?*s.phase:0;
        if (s.stats.phase!=1 && s.stats.phase!=2) GGML_ABORT("IS314 real request phase missing/mixed");
        ggml_backend_tensor_set(s.input,src->data,0,ggml_nbytes(s.input));
        // Benchmark routing is bound to already-stable caller tensors: read the
        // boundary directly instead of dispatching an empty router graph whose
        // only work is copying those bytes. Native routing still computes the
        // real router graph below. #346: T>1 reads the [10,T] batch boundary.
        if (!s.bound_ids) compute(s.cpu,s.router.graph);
        const auto * ids=static_cast<const int32_t *>(s.bound_ids?s.bound_ids->data:s.ids->data);
        const auto * weights=static_cast<const float *>(s.weights->data);
        // Bound routing is [10,T]; the native-router path packs [10,T] too.
        // The bound benchmark tensor is allocated once at the sweep's maximum
        // width; the active step's width is the caller graph's built width.
        const unsigned tokens = unsigned(s.bound_ids ? s.built_tokens : s.ids->ne[1]);
        if (tokens<1 || tokens>256) GGML_ABORT("IS314 unsupported token batch");
        std::vector<int32_t> hi{},ci{},hs{},cs{}; std::vector<float> hw{},cw{};
        unsigned nh=0,nc=0;
        for (unsigned t=0;t<tokens;++t) {
            unsigned th=0,tc=0;
            for (int slot=0;slot<10;++slot) {
                const int32_t id=ids[t*10+slot];
                if (id<0 || id>=(int)s.owner->dense.size()) GGML_ABORT("IS314 invalid source routing");
                const int dense=s.owner->dense[id];
                if (dense>=0) ++th; else ++tc;
            }
            if (t==0) { nh=th; nc=tc; }
            // One prebuilt branch graph (one mul_mat_id) executes the whole
            // batch, so every token must carry the same hot count. The bound
            // caller enforces this before the step; abort otherwise.
            else if (th!=nh) GGML_ABORT("IS314 mixed hot counts within one batch unsupported");
        }
        hi.resize(nh*tokens);ci.resize(nc*tokens);hs.resize(nh*tokens);cs.resize(nc*tokens);hw.resize(nh*tokens);cw.resize(nc*tokens);
        for (unsigned t=0;t<tokens;++t) {
            // Fill offsets are batch-strided: token t's hot entries occupy
            // hi[t*nh .. t*nh+nh-1] (the [C,T] ids/weights layout mul_mat_id
            // and the branch tensors expect), likewise cold at t*nc.
            unsigned h=t*nh,c=t*nc;
            for (int slot=0;slot<10;++slot) {
                const int32_t id=ids[t*10+slot];
                // Uniqueness is per token: the same expert may legitimately
                // serve several tokens of one batch (that reuse is the point
                // of batching). Only duplicates WITHIN one token's ten slots
                // are invalid routing.
                for (int seen=0;seen<slot;++seen)
                    if (ids[t*10+seen]==id) GGML_ABORT("IS314 invalid source routing");
                const int dense=s.owner->dense[id];
                if (dense>=0) { hs[h]=t*10+slot; hi[h]=dense; std::memcpy(&hw[h++],&weights[t*10+slot],sizeof(float)); }
                else { cs[c]=t*10+slot; ci[c]=id; std::memcpy(&cw[c++],&weights[t*10+slot],sizeof(float)); }
            }
        }
        if (auto demand=is312::active()) demand->record(s.layer,ids,10,tokens,0.0);
        if (!nh) {
            // Zero-hot step: the reusable ordinary CPU graph is exactly the
            // source FFN for this routing (same banks, slot order, weighting,
            // shared contribution and reduction/add order). One private
            // compute replaces the cold/shared/restore/reduce split; no RPC
            // dispatch, allocation or upload occurs. Mixed steps below keep
            // the heterogeneous hot-RPC/cold-CPU path and its overlap.
            if (!s.fast.graph) GGML_ABORT("IS314 zero-hot fast graph missing");
            ggml_backend_tensor_set(s.fast.ids,ids,0,10*tokens*sizeof(int32_t));
            ggml_backend_tensor_set(s.fast.weights,weights,0,10*tokens*sizeof(float));
            const auto fast_start=clock::now();
            compute(s.cpu,s.fast.graph);
            const auto fast_done=clock::now();
            std::memcpy(dst->data,s.fast.output->data,ggml_nbytes(dst));
            ++s.stats.steps; s.stats.hot=nh; s.stats.cold=nc; s.stats.compact_owner=reinterpret_cast<uintptr_t>(s.owner);
            s.stats.tokens=tokens;
            s.stats.dispatch_ms=0; s.stats.cold_ms=0; s.stats.shared_ms=0; s.stats.join_ms=0;
            s.stats.fast_ms=elapsed(fast_start,fast_done); s.stats.layer_ms=elapsed(start,clock::now());
            s.stats.input_bytes=0; s.stats.routing_bytes=0; s.stats.result_bytes=0;
            std::fprintf(stderr,"IS314_STEP layer=%d phase=%s step=%llu hot=%u cold=%u dispatch_ms=%.6f cold_ms=%.6f shared_ms=%.6f join_ms=%.6f layer_ms=%.6f input_bytes=%llu routing_bytes=%llu result_bytes=%llu ids=",
                s.layer,s.stats.phase==1?"prefill":"decode",(unsigned long long)s.stats.steps,nh,nc,s.stats.dispatch_ms,s.stats.cold_ms,s.stats.shared_ms,s.stats.join_ms,s.stats.layer_ms,
                (unsigned long long)s.stats.input_bytes,(unsigned long long)s.stats.routing_bytes,(unsigned long long)s.stats.result_bytes);
            for (int i=0;i<10;++i) std::fprintf(stderr,"%s%d",i?",":"",ids[i]);
            std::fprintf(stderr," weight_bits=");
            for (int i=0;i<10;++i) { uint32_t bits; std::memcpy(&bits,&weights[i],sizeof(bits)); std::fprintf(stderr,"%s%08x",i?",":"",bits); }
            std::fprintf(stderr,"\n");
            return;
        }
        auto & h=s.hot[nh]; auto & c=s.cold[nc];
        // Routing partitions travel by value into the dispatch thread: their
        // buffers must outlive the synchronous acknowledged transfers. #346:
        // [C,T] ids and weights for every token of the batch.
        const std::vector<int32_t> hot_ids=hi; const std::vector<float> hot_weights=hw;
        double dispatch_span=0;
        // Submit the remote branch concurrently with the CPU cold/shared
        // branches. Each composed-RPC-v7 setter is an acknowledged round trip
        // (bounded staging, caller-owned buffers), so a serial submission
        // merely idles the main thread for three network round trips before
        // any local work starts. The dispatch thread only touches the RPC
        // backend; the CPU branches never use it, so the dispatcher's ordered
        // queue keeps the wire sequence SET,SET,SET,GRAPH intact.
        // The join MUST precede the result GET: the dispatcher queue is
        // ordered, but only after the dispatch thread has actually queued the
        // GRAPH_COMPUTE. Joining first keeps SET,SET,SET,GRAPH strictly ahead
        // of the response-bearing GET on the wire on every path.
        double cold_ms=0, shared_ms=0;
        clock::time_point shared_done_outer{};
        {
            std::thread dispatch_thread([&](){
                const auto submit=clock::now();
                ggml_backend_tensor_set_async(s.owner->rpc,h.input,s.input->data,0,ggml_nbytes(h.input));
                ggml_backend_tensor_set_async(s.owner->rpc,h.ids,hot_ids.data(),0,nh*tokens*sizeof(int32_t));
                ggml_backend_tensor_set_async(s.owner->rpc,h.weights,hot_weights.data(),0,nh*tokens*sizeof(float));
                if (ggml_backend_graph_compute_async(s.owner->rpc,h.graph)!=GGML_STATUS_SUCCESS) GGML_ABORT("IS314 remote dispatch failed");
                dispatch_span=elapsed(submit,clock::now());
            });
            // Join on every path inside this scope: a joinable std::thread
            // destroyed mid-flight would call std::terminate.
            struct dispatch_joiner { std::thread & t; ~dispatch_joiner() { t.join(); } } join_on_exit{dispatch_thread};
            const auto submitted=clock::now();
            if (nc) {
                ggml_backend_tensor_set(c.ids,ci.data(),0,nc*tokens*sizeof(int32_t));
                ggml_backend_tensor_set(c.weights,cw.data(),0,nc*tokens*sizeof(float)); compute(s.cpu,c.graph);
            }
            const auto cold_done=clock::now();
            compute(s.cpu,s.shared.graph);
            const auto shared_done=clock::now();
            cold_ms=elapsed(submitted,cold_done); shared_ms=elapsed(cold_done,shared_done);
            shared_done_outer=shared_done;
        }
        if (nh) {
            // GET is the response-bearing join (the dispatch thread has already
            // been joined above). Synchronize alone only drains the client queue.
            ggml_backend_tensor_get(h.output,s.remote_result.data(),0,ggml_nbytes(h.output));
            ggml_backend_synchronize(s.owner->rpc);
        }
        const auto joined=clock::now();
        const size_t width=src->ne[0]; auto * slots=static_cast<float *>(s.slots->data);
        // #346: slot rows scale with the batch: expert i of token t writes
        // slots[t, i] (row t*10+i of the [width,10,T] slot staging).
        for (unsigned i=0;i<nh*tokens;++i) std::memcpy(slots+hs[i]*width,s.remote_result.data()+i*width,width*sizeof(float));
        if (nc) for (unsigned i=0;i<nc*tokens;++i) std::memcpy(slots+cs[i]*width,static_cast<float *>(c.output->data)+i*width,width*sizeof(float));
        // Execute the cloned SOURCE reduction, including its view/add order and shared add.
        compute(s.cpu,s.reduce.graph); std::memcpy(dst->data,s.reduce.output->data,ggml_nbytes(dst));
        ++s.stats.steps; s.stats.hot=nh; s.stats.cold=nc; s.stats.compact_owner=reinterpret_cast<uintptr_t>(s.owner);
        s.stats.tokens=tokens; ++s.stats.graph_dispatches;
        if (h.graph->uid && s.last_remote_uid==h.graph->uid) ++s.stats.graph_recompute_reuse;
        s.last_remote_uid=h.graph->uid;
        // dispatch_ms is the submission span measured inside the dispatch
        // thread (acknowledged transfers + graph dispatch). With the concurrent
        // submit it is no longer main-thread serial time; layer_ms carries the
        // wall-clock effect. cold/shared/join remain main-thread intervals.
        s.stats.dispatch_ms=dispatch_span; s.stats.cold_ms=cold_ms;
        s.stats.shared_ms=shared_ms; s.stats.join_ms=elapsed(shared_done_outer,joined); s.stats.fast_ms=0; s.stats.layer_ms=elapsed(start,clock::now());
        s.stats.input_bytes=nh?ggml_nbytes(h.input):0; s.stats.routing_bytes=nh*tokens*(sizeof(int32_t)+sizeof(float)); s.stats.result_bytes=nh?ggml_nbytes(h.output):0;
        std::fprintf(stderr,"IS314_STEP layer=%d phase=%s step=%llu hot=%u cold=%u tokens=%u dispatch_ms=%.6f cold_ms=%.6f shared_ms=%.6f join_ms=%.6f layer_ms=%.6f input_bytes=%llu routing_bytes=%llu result_bytes=%llu ids=",
            s.layer,s.stats.phase==1?"prefill":"decode",(unsigned long long)s.stats.steps,nh,nc,tokens,s.stats.dispatch_ms,s.stats.cold_ms,s.stats.shared_ms,s.stats.join_ms,s.stats.layer_ms,
            (unsigned long long)s.stats.input_bytes,(unsigned long long)s.stats.routing_bytes,(unsigned long long)s.stats.result_bytes);
        for (unsigned i=0;i<10*tokens;++i) std::fprintf(stderr,"%s%d",i?",":"",ids[i]);
        std::fprintf(stderr," weight_bits=");
        for (unsigned i=0;i<10*tokens;++i) { uint32_t bits; std::memcpy(&bits,&weights[i],sizeof(bits)); std::fprintf(stderr,"%s%08x",i?",":"",bits); }
        std::fprintf(stderr,"\n");
    }
};
llama_hot_stats llama_hot_get_stats(const std::shared_ptr<llama_hot_graph> & graph) { return graph->stats; }
llama_hot_stages llama_hot_get_stages(const std::shared_ptr<llama_hot_graph> & graph) {
    return graph && graph->stats.hot==5 ? graph->stages : llama_hot_stages{};
}

llama_hot_observation llama_hot_get_observation(const std::shared_ptr<llama_hot_graph> & graph) {
    if (!graph || !graph->stats.steps) return {};
    auto & s=*graph;
    llama_hot_observation out;
    out.input=s.input; out.ids=s.bound_ids?s.bound_ids:s.ids; out.weights=s.weights;
    // Fast-path intermediates are not retained. Never expose the last mixed
    // step's slots/shared as observations of an all-cold step.
    if (!s.stats.hot) return out;
    out.weighted_shape=s.slots; out.shared=s.shared.output;
    auto & h=s.hot[s.stats.hot];
    out.hot_weighted=h.output;
    out.hot_input=h.input; out.hot_ids=h.ids; out.hot_weights=h.weights;
    if (s.stats.cold) {
        out.cold_weighted=s.cold[s.stats.cold].output;
        out.cold_ids=s.cold[s.stats.cold].ids;
        out.cold_weights=s.cold[s.stats.cold].weights;
    }
    return out;
}


ggml_tensor * llm_graph_context::build_qwen4exp_ffn_hot(ggml_tensor * cur,const llama_layer & layer,int il,const llama_moe_overlap_config & cfg) {
    check(n_expert_used==10 && n_tokens>=1,"requires ten slots and at least one token");
    check(cur->type==GGML_TYPE_F32 && ggml_is_contiguous(cur),"contiguous F32 activation required");
    check(loras && loras->empty(),"LoRA unsupported");
    check(cparams.cb_eval==nullptr || is312::dedicated_callback(cparams.cb_eval),"unsupported eval callback");
    check(hot_owner,"context lifetime owner missing");
    if (!*hot_owner) { auto owner=std::make_shared<llama_hot_experts>(); owner->setup(cfg,layer,sched); *hot_owner=std::move(owner); }
    auto & owner=**hot_owner;
    // The owner's spec document is identity across rebuilds: each build parses
    // the same frozen spec.json file, so compare the retained document rather
    // than the shared_ptr produced by this build's parse.
    check(owner.spec->document==cfg.hot_spec->document,"immutable hot configuration changed");
    check(owner.original[0]==layer.ffn_gate_exps && owner.original[1]==layer.ffn_up_exps && owner.original[2]==layer.ffn_down_exps,"source bank identity changed");
    // #346: the cached graph is fixed-width. A batch-width change retires it
    // (the caller has already reset the graph results that referenced it) and
    // builds a fresh graph over the same owner, compact weights and RPC link.
    if (owner.graph && owner.graph->built_tokens!=unsigned(n_tokens)) owner.graph.reset();
    if (!owner.graph) {
        auto s=std::make_shared<llama_hot_graph>(); s->owner=&owner; s->layer=il; s->phase=hot_phase;
        constexpr size_t nodes=1024;
        s->ctx=ggml_init({ggml_tensor_overhead()*8192+ggml_graph_overhead_custom(nodes,false)*24,nullptr,true}); check(s->ctx,"private metadata allocation");
        s->cpu=ggml_backend_cpu_init(); check(s->cpu,"private CPU backend"); ggml_backend_cpu_set_n_threads(s->cpu,std::max(1,cparams.n_threads));
        s->input=ggml_dup_tensor(s->ctx,cur); ggml_set_input(s->input); ggml_set_output(s->input);
        s->built_tokens=unsigned(n_tokens);
        auto * outer_ctx=ctx0; auto * outer_gf=gf;
        ctx0=s->ctx; gf=ggml_new_graph_custom(ctx0,nodes,false); moe_overlap_building=true;
        ggml_tensor * combined=nullptr;
        try { combined=build_qwen4exp_ffn_native(s->input,layer,il); }
        catch (...) { ctx0=outer_ctx; gf=outer_gf; moe_overlap_building=false; throw; }
        ctx0=outer_ctx; gf=outer_gf; moe_overlap_building=false;
        check(combined->op==GGML_OP_ADD && layer.ffn_up_shexp,"gated shared branch required");
        if (cfg.benchmark_routing_batch) { llama_hot_bind_routing_batch(s->ctx,combined,il,*cfg.benchmark_routing_batch); s->bound_ids=cfg.benchmark_routing_batch->ids; }
        else if (cfg.benchmark_routing) { llama_hot_bind_routing(s->ctx,combined,il,*cfg.benchmark_routing); s->bound_ids=cfg.benchmark_routing->ids; }
        auto * weighted=ggml_get_tensor(s->ctx,("ffn_moe_weighted-"+std::to_string(il)).c_str()); check(weighted,"source weighted cut missing");
        auto * down=weighted->src[0]; check(down->op==GGML_OP_MUL_MAT_ID,"source expert cut mismatch");
        s->ids=ggml_cont(s->ctx,down->src[2]); s->weights=weighted->src[1];
        ggml_set_output(s->ids); ggml_set_output(s->weights);
        s->router.graph=ggml_new_graph_custom(s->ctx,nodes,false);
        ggml_build_forward_expand(s->router.graph,s->ids); ggml_build_forward_expand(s->router.graph,s->weights);
        s->allocate(s->router,s->cpu);
        s->shared.output=combined->src[1]; ggml_set_output(s->shared.output);
        s->shared.graph=ggml_new_graph_custom(s->ctx,nodes,false); ggml_build_forward_expand(s->shared.graph,s->shared.output); s->allocate(s->shared,s->cpu);
        s->slots=ggml_dup_tensor(s->ctx,weighted); ggml_set_input(s->slots);
        std::unordered_map<ggml_tensor *,ggml_tensor *> cuts={{weighted,s->slots},{s->shared.output,s->shared.output}};
        s->reduce.output=ggml_cont(s->ctx,clone(s->ctx,combined,cuts)); ggml_set_output(s->reduce.output);
        s->reduce.graph=ggml_new_graph_custom(s->ctx,nodes,false); ggml_build_forward_expand(s->reduce.graph,s->reduce.output);
        // Shared is a precomputed leaf in this graph, not repeated shared work.
        // clone's identity cut still has an op: temporarily hide it while expanding.
        auto op=s->shared.output->op; auto sources=std::array<ggml_tensor *,GGML_MAX_SRC>{};
        std::copy(std::begin(s->shared.output->src),std::end(s->shared.output->src),sources.begin());
        s->shared.output->op=GGML_OP_NONE; std::fill(std::begin(s->shared.output->src),std::end(s->shared.output->src),nullptr);
        ggml_graph_clear(s->reduce.graph); ggml_build_forward_expand(s->reduce.graph,s->reduce.output);
        s->shared.output->op=op; std::copy(sources.begin(),sources.end(),std::begin(s->shared.output->src));
        s->allocate(s->reduce,s->cpu);
        // Zero-hot reusable ordinary CPU graph: the complete source FFN clone
        // with only the routing boundary as private leaf inputs. Identical
        // banks, slot association, weighting, shared branch and view/add
        // reduction order to the ordinary CPU arm; ONE private compute per
        // all-cold step, with no RPC dispatch, allocation or upload. Mixed
        // steps never touch it, so the heterogeneous path and its overlap
        // are unchanged.
        s->fast.ids=ggml_new_tensor_2d(s->ctx,GGML_TYPE_I32,10,s->built_tokens);
        s->fast.weights=ggml_new_tensor_3d(s->ctx,GGML_TYPE_F32,1,10,s->built_tokens);
        ggml_set_input(s->fast.ids); ggml_set_input(s->fast.weights);
        std::unordered_map<ggml_tensor *,ggml_tensor *> fast_cuts={{s->input,s->input},{down->src[2],s->fast.ids},{weighted->src[1],s->fast.weights}};
        s->fast.output=ggml_cont(s->ctx,clone(s->ctx,combined,fast_cuts)); ggml_set_output(s->fast.output);
        s->fast.graph=ggml_new_graph_custom(s->ctx,nodes,false); ggml_build_forward_expand(s->fast.graph,s->fast.output);
        s->allocate(s->fast,s->cpu);
        for (int count=1;count<=10;++count) for (bool remote : {false,true}) {
            if (remote && owner.dense.end()==std::find_if(owner.dense.begin(),owner.dense.end(),[](int v){return v>=0;})) continue;
            if (remote && count>(int)cfg.hot_spec->document.at("expert_ids").size()) continue;
            // cold[10] only serves zero-hot steps, which the fast graph now owns.
            if (!remote && count==10) continue;
            llm_graph_params p={}; p.arch=arch; p.hparams=hparams; p.hparams.n_expert_used_arr.fill(count); p.cparams=cparams;
            p.ubatch=ubatch; p.sched=sched; p.backend_cpu=backend_cpu; p.loras=loras; p.res=res;
            p.cb=[](const llama_ubatch &,ggml_tensor * t,const char * name,int layer){ggml_format_name(t,"%s-%d",name,layer);};
            llm_graph_context builder(p); builder.ctx0=s->ctx; builder.gf=ggml_new_graph_custom(s->ctx,nodes,false); builder.moe_overlap_building=true;
            builder.build_moe_ffn(s->input,layer.ffn_gate_inp,layer.ffn_up_exps,layer.ffn_gate_exps,layer.ffn_down_exps,nullptr,n_expert,count,LLM_FFN_SILU,true,hparams.expert_weights_scale,LLAMA_EXPERT_GATING_FUNC_TYPE_SOFTMAX,il);
            // Names can repeat across templates: obtain the last weighted node from this template graph.
            ggml_tensor * w=nullptr;
            for (int i=0;i<builder.gf->n_nodes;++i) if (std::string(builder.gf->nodes[i]->name)=="ffn_moe_weighted-"+std::to_string(il)) w=builder.gf->nodes[i];
            check(w && w->src[0]->op==GGML_OP_MUL_MAT_ID,"source branch weighted cut");
            auto & b=remote?s->hot[count]:s->cold[count];
            b.input=remote?ggml_dup_tensor(s->ctx,s->input):s->input;
            b.ids=ggml_new_tensor_2d(s->ctx,GGML_TYPE_I32,count,s->built_tokens);
            b.weights=ggml_new_tensor_3d(s->ctx,GGML_TYPE_F32,1,count,s->built_tokens);
            ggml_set_input(b.input); ggml_set_input(b.ids); ggml_set_input(b.weights);
            std::unordered_map<ggml_tensor *,ggml_tensor *> branch_cuts={{s->input,b.input},{w->src[0]->src[2],b.ids},{w->src[1],b.weights}};
            if (remote) for (size_t i=0;i<3;++i) branch_cuts[owner.original[i]]=owner.compact[i];
            b.output=ggml_cont(s->ctx,clone(s->ctx,w,branch_cuts)); ggml_set_output(b.output);
            if (cfg.benchmark_stages && remote && count==5) {
                check(cfg.benchmark_routing_batch && s->built_tokens==2,"stage retention requires bound T=2 benchmark");
                s->stages=llama_hot_retain_stages(b.output);
            }
            b.graph=ggml_new_graph_custom(s->ctx,nodes,false); ggml_build_forward_expand(b.graph,b.output);
            s->allocate(b,remote?owner.rpc:s->cpu);
            if (remote) {
                // A prebuilt remote branch is structurally immutable across steps:
                // per-step routing and activations reach it through in-place
                // SET_TENSOR writes into the same allocated input tensors. Give
                // each distinct remote graph a nonzero uid so the pinned RPC
                // client's existing GRAPH_RECOMPUTE path (uid match against the
                // device's last dispatched graph) can skip per-step client
                // serialization and server-side graph reconstruction. A uid
                // mismatch — any other graph dispatched in between, including
                // scheduler splits in a full model — falls back to the ordinary
                // full GRAPH_COMPUTE, so correctness never depends on reuse.
                b.graph->uid=ggml_graph_next_uid();
            }
        }
        s->remote_result.resize(cur->ne[0]*10*s->built_tokens);
        size_t local_bytes=0,remote_bytes=0;
        for (auto * b : {&s->router,&s->shared,&s->reduce,&s->fast}) local_bytes+=ggml_gallocr_get_buffer_size(b->alloc,0);
        for (auto & b:s->cold) if (b.alloc) local_bytes+=ggml_gallocr_get_buffer_size(b.alloc,0);
        for (auto & b:s->hot) if (b.alloc) remote_bytes+=ggml_gallocr_get_buffer_size(b.alloc,0);
        std::fprintf(stderr,"IS314_SETUP layer=%d tokens=%u compact_bytes=%zu staging_peak=%zu retained_staging=0 cpu_arena_bytes=%zu rpc_arena_bytes=%zu result_workspace_bytes=%zu metadata_bytes=%zu\n",il,s->built_tokens,owner.resident,owner.staging_peak,local_bytes,remote_bytes,s->remote_result.size()*sizeof(float),ggml_used_mem(s->ctx));
        owner.graph=std::move(s);
    }
    auto * output=ggml_map_custom1(ctx0,cur,llama_hot_graph::execute,1,owner.graph.get());
    res->hot_experts.push_back(owner.graph); cb(output,"ffn_out",il); ggml_backend_sched_set_tensor_backend(sched,output,backend_cpu); return output;
}
