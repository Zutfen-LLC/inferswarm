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
class llama_hot_graph {
public:
    llama_hot_experts * owner = nullptr;
    ggml_context * ctx = nullptr;
    ggml_backend_t cpu = nullptr;
    hot_branch router, shared, reduce;
    std::array<hot_branch,11> hot = {}, cold = {};
    ggml_tensor * input = nullptr, * ids = nullptr, * weights = nullptr, * slots = nullptr;
    std::vector<float> remote_result;
    llama_hot_stats stats;
    const int * phase = nullptr;
    int layer = -1;
    ~llama_hot_graph() {
        for (auto * b : {&router,&shared,&reduce}) ggml_gallocr_free(b->alloc);
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
        ggml_backend_tensor_set(s.input,src->data,0,ggml_nbytes(s.input)); compute(s.cpu,s.router.graph);
        const auto * ids=static_cast<const int32_t *>(s.ids->data);
        const auto * weights=static_cast<const float *>(s.weights->data);
        std::array<int32_t,10> hi={},ci={},hs={},cs={}; std::array<float,10> hw={},cw={};
        unsigned nh=0,nc=0; std::set<int32_t> selected;
        for (int slot=0;slot<10;++slot) {
            if (ids[slot]<0 || ids[slot]>=(int)s.owner->dense.size() || !selected.insert(ids[slot]).second) GGML_ABORT("IS314 invalid source routing");
            const int dense=s.owner->dense[ids[slot]];
            if (dense>=0) { hi[nh]=dense; hs[nh]=slot; std::memcpy(&hw[nh++],&weights[slot],sizeof(float)); }
            else { ci[nc]=ids[slot]; cs[nc]=slot; std::memcpy(&cw[nc++],&weights[slot],sizeof(float)); }
        }
        if (auto demand=is312::active()) demand->record(s.layer,ids,10,1,0.0);
        auto & h=s.hot[nh]; auto & c=s.cold[nc];
        const auto dispatch_start=clock::now();
        if (nh) {
            ggml_backend_tensor_set_async(s.owner->rpc,h.input,s.input->data,0,ggml_nbytes(h.input));
            ggml_backend_tensor_set_async(s.owner->rpc,h.ids,hi.data(),0,nh*sizeof(int32_t));
            ggml_backend_tensor_set_async(s.owner->rpc,h.weights,hw.data(),0,nh*sizeof(float));
            if (ggml_backend_graph_compute_async(s.owner->rpc,h.graph)!=GGML_STATUS_SUCCESS) GGML_ABORT("IS314 remote dispatch failed");
        }
        const auto dispatched=clock::now();
        if (nc) {
            ggml_backend_tensor_set(c.ids,ci.data(),0,nc*sizeof(int32_t));
            ggml_backend_tensor_set(c.weights,cw.data(),0,nc*sizeof(float)); compute(s.cpu,c.graph);
        }
        const auto cold_done=clock::now();
        compute(s.cpu,s.shared.graph);
        const auto shared_done=clock::now();
        if (nh) {
            // GET is the response-bearing join. Synchronize alone only drains the client queue.
            ggml_backend_tensor_get(h.output,s.remote_result.data(),0,ggml_nbytes(h.output));
            ggml_backend_synchronize(s.owner->rpc);
        }
        const auto joined=clock::now();
        const size_t width=src->ne[0]; auto * slots=static_cast<float *>(s.slots->data);
        for (unsigned i=0;i<nh;++i) std::memcpy(slots+hs[i]*width,s.remote_result.data()+i*width,width*sizeof(float));
        if (nc) for (unsigned i=0;i<nc;++i) std::memcpy(slots+cs[i]*width,static_cast<float *>(c.output->data)+i*width,width*sizeof(float));
        // Execute the cloned SOURCE reduction, including its view/add order and shared add.
        compute(s.cpu,s.reduce.graph); std::memcpy(dst->data,s.reduce.output->data,ggml_nbytes(dst));
        ++s.stats.steps; s.stats.hot=nh; s.stats.cold=nc; s.stats.compact_owner=reinterpret_cast<uintptr_t>(s.owner);
        s.stats.dispatch_ms=elapsed(dispatch_start,dispatched); s.stats.cold_ms=elapsed(dispatched,cold_done);
        s.stats.shared_ms=elapsed(cold_done,shared_done); s.stats.join_ms=elapsed(shared_done,joined); s.stats.layer_ms=elapsed(start,clock::now());
        s.stats.input_bytes=nh?ggml_nbytes(h.input):0; s.stats.routing_bytes=nh*(sizeof(int32_t)+sizeof(float)); s.stats.result_bytes=nh?ggml_nbytes(h.output):0;
        std::fprintf(stderr,"IS314_STEP layer=%d phase=%s step=%llu hot=%u cold=%u dispatch_ms=%.6f cold_ms=%.6f shared_ms=%.6f join_ms=%.6f layer_ms=%.6f input_bytes=%llu routing_bytes=%llu result_bytes=%llu ids=",
            s.layer,s.stats.phase==1?"prefill":"decode",(unsigned long long)s.stats.steps,nh,nc,s.stats.dispatch_ms,s.stats.cold_ms,s.stats.shared_ms,s.stats.join_ms,s.stats.layer_ms,
            (unsigned long long)s.stats.input_bytes,(unsigned long long)s.stats.routing_bytes,(unsigned long long)s.stats.result_bytes);
        for (int i=0;i<10;++i) std::fprintf(stderr,"%s%d",i?",":"",ids[i]);
        std::fprintf(stderr," weight_bits=");
        for (int i=0;i<10;++i) { uint32_t bits; std::memcpy(&bits,&weights[i],sizeof(bits)); std::fprintf(stderr,"%s%08x",i?",":"",bits); }
        std::fprintf(stderr,"\n");
    }
};
llama_hot_stats llama_hot_get_stats(const std::shared_ptr<llama_hot_graph> & graph) { return graph->stats; }

ggml_tensor * llm_graph_context::build_qwen4exp_ffn_hot(ggml_tensor * cur,const llama_layer & layer,int il,const llama_moe_overlap_config & cfg) {
    check(n_expert_used==10 && n_tokens==1,"requires ten slots and single token");
    check(cur->type==GGML_TYPE_F32 && ggml_is_contiguous(cur),"contiguous F32 activation required");
    check(loras && loras->empty(),"LoRA unsupported");
    check(cparams.cb_eval==nullptr || is312::dedicated_callback(cparams.cb_eval),"unsupported eval callback");
    check(hot_owner,"context lifetime owner missing");
    if (!*hot_owner) { auto owner=std::make_shared<llama_hot_experts>(); owner->setup(cfg,layer,sched); *hot_owner=std::move(owner); }
    auto & owner=**hot_owner;
    check(owner.spec==cfg.hot_spec,"immutable hot configuration changed");
    check(owner.original[0]==layer.ffn_gate_exps && owner.original[1]==layer.ffn_up_exps && owner.original[2]==layer.ffn_down_exps,"source bank identity changed");
    if (!owner.graph) {
        auto s=std::make_shared<llama_hot_graph>(); s->owner=&owner; s->layer=il; s->phase=hot_phase;
        constexpr size_t nodes=1024;
        s->ctx=ggml_init({ggml_tensor_overhead()*8192+ggml_graph_overhead_custom(nodes,false)*24,nullptr,true}); check(s->ctx,"private metadata allocation");
        s->cpu=ggml_backend_cpu_init(); check(s->cpu,"private CPU backend"); ggml_backend_cpu_set_n_threads(s->cpu,std::max(1,cparams.n_threads));
        s->input=ggml_dup_tensor(s->ctx,cur); ggml_set_input(s->input); ggml_set_output(s->input);
        auto * outer_ctx=ctx0; auto * outer_gf=gf;
        ctx0=s->ctx; gf=ggml_new_graph_custom(ctx0,nodes,false); moe_overlap_building=true;
        ggml_tensor * combined=nullptr;
        try { combined=build_qwen4exp_ffn_native(s->input,layer,il); }
        catch (...) { ctx0=outer_ctx; gf=outer_gf; moe_overlap_building=false; throw; }
        ctx0=outer_ctx; gf=outer_gf; moe_overlap_building=false;
        check(combined->op==GGML_OP_ADD && layer.ffn_up_shexp,"gated shared branch required");
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
        for (int count=1;count<=10;++count) for (bool remote : {false,true}) {
            if (remote && owner.dense.end()==std::find_if(owner.dense.begin(),owner.dense.end(),[](int v){return v>=0;})) continue;
            if (remote && count>(int)cfg.hot_spec->document.at("expert_ids").size()) continue;
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
            b.ids=ggml_new_tensor_2d(s->ctx,GGML_TYPE_I32,count,1); b.weights=ggml_new_tensor_3d(s->ctx,GGML_TYPE_F32,1,count,1);
            ggml_set_input(b.input); ggml_set_input(b.ids); ggml_set_input(b.weights);
            std::unordered_map<ggml_tensor *,ggml_tensor *> branch_cuts={{s->input,b.input},{w->src[0]->src[2],b.ids},{w->src[1],b.weights}};
            if (remote) for (size_t i=0;i<3;++i) branch_cuts[owner.original[i]]=owner.compact[i];
            b.output=ggml_cont(s->ctx,clone(s->ctx,w,branch_cuts)); ggml_set_output(b.output);
            b.graph=ggml_new_graph_custom(s->ctx,nodes,false); ggml_build_forward_expand(b.graph,b.output);
            s->allocate(b,remote?owner.rpc:s->cpu);
        }
        s->remote_result.resize(cur->ne[0]*10);
        size_t local_bytes=0,remote_bytes=0;
        for (auto * b : {&s->router,&s->shared,&s->reduce}) local_bytes+=ggml_gallocr_get_buffer_size(b->alloc,0);
        for (auto & b:s->cold) if (b.alloc) local_bytes+=ggml_gallocr_get_buffer_size(b.alloc,0);
        for (auto & b:s->hot) if (b.alloc) remote_bytes+=ggml_gallocr_get_buffer_size(b.alloc,0);
        std::fprintf(stderr,"IS314_SETUP layer=%d compact_bytes=%zu staging_peak=%zu retained_staging=0 cpu_arena_bytes=%zu rpc_arena_bytes=%zu result_workspace_bytes=%zu metadata_bytes=%zu\n",il,owner.resident,owner.staging_peak,local_bytes,remote_bytes,s->remote_result.size()*sizeof(float),ggml_used_mem(s->ctx));
        owner.graph=std::move(s);
    }
    auto * output=ggml_map_custom1(ctx0,cur,llama_hot_graph::execute,1,owner.graph.get());
    res->hot_experts.push_back(owner.graph); cb(output,"ffn_out",il); ggml_backend_sched_set_tensor_backend(sched,output,backend_cpu); return output;
}
