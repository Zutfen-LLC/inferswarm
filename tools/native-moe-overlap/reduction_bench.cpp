// Isolated successor of layer7_bench.cpp: frozen fixture/math, explicit factorial scheduling.
// The historical producer remains unchanged. No model or worker implementation here.
#include "llama-graph.h"
#include "llama-model.h"
#include "llama-cparams.h"
#include "ggml-cpu.h"
#include "ggml-rpc.h"
#include "ggml-alloc.h"
#include "nlohmann/json.hpp"
extern "C" {
#include "hash/sha256/sha256.h"
}
#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <map>
#include <set>
#include <sstream>
#include <stdexcept>
#include <vector>
#include <sys/resource.h>
using nlohmann::json;
namespace {
using clock_type=std::chrono::steady_clock;
constexpr int E=512,K=10;
const std::array<int,5> HOT={54,74,136,290,394};
void require(bool ok,const std::string & why) { if (!ok) throw std::runtime_error(why); }
double ms(clock_type::time_point a) { return std::chrono::duration<double,std::milli>(clock_type::now()-a).count(); }
std::string sha(const void * p,size_t n) {
    uint8_t digest[32]; sha256_hash(digest,static_cast<const uint8_t *>(p),n);
    std::ostringstream s; for (auto b:digest) s<<std::hex<<std::setw(2)<<std::setfill('0')<<int(b); return s.str();
}
uint32_t next(uint32_t & state) { state^=state<<13; state^=state>>17; state^=state<<5; return state; }
float sample(uint32_t & state) { return (int(next(state)%2001)-1000)/1000.0f; }
struct options {
    int d=2560,f=640,threads=8,warmup=5,pairs=20; uint32_t seed=314159;
    bool small=false, failure_dump=false, diagnostic_pair13=false, capture_stages=false, operand_replay=false, warmed_operand_sweep=false; size_t dump_max_bytes=16*1024*1024; std::string endpoint,work,routing,control,comparison_mode="cpu-loopback";
    std::string tokens_list="1";
};
int number(const std::string & text,int low,int high) {
    require(!text.empty() && text.size()<11 && text.find_first_not_of("0123456789")==std::string::npos,"invalid bounded integer");
    auto v=std::stoll(text); require(v>=low && v<=high,"integer outside benchmark budget"); return int(v);
}
struct route {
    std::array<int32_t,K> ids; std::array<float,K> weights; std::string label;
};
// #346: one routing row per token of a batch. shared_set=true gives every
// token the same expert set (ideal expert reuse); false gives distinct
// per-token sets within the resident cold pool (general workload behavior).
struct batch_route {
    int tokens=1; bool shared_set=false; std::vector<route> rows; std::string label;
};
void validate(const route & r) {
    std::set<int32_t> ids;
    for (int i=0;i<K;++i) require(r.ids[i]>=0 && r.ids[i]<E && ids.insert(r.ids[i]).second && std::isfinite(r.weights[i]) && r.weights[i]>0,"invalid routing partition/weights");
}
std::vector<route> routes(const options & o) {
    std::vector<route> rows;
    if (!o.routing.empty()) {
        std::ifstream f(o.routing); json j; f>>j;
        require(j.at("schema")=="h5-layer7-routing/1" && j.at("rows").size()>0 && j.at("rows").size()<=200,"routing schema/budget");
        for (const auto & row:j.at("rows")) {
            route r; auto ids=row.at("ids").get<std::vector<int32_t>>(); auto bits=row.at("weight_bits").get<std::vector<std::string>>();
            require(ids.size()==K && bits.size()==K,"ten routing slots required");
            for (int i=0;i<K;++i) {
                r.ids[i]=ids[i]; require(bits[i].size()==8 && bits[i].find_first_not_of("0123456789abcdef")==std::string::npos,"invalid routing weight bits");
                uint32_t b=std::stoul(bits[i],nullptr,16); std::memcpy(&r.weights[i],&b,4);
            }
            r.label=row.at("label");validate(r);rows.push_back(r);
        }
    } else {
        route r; r.ids={136,17,394,231,54,3,290,411,74,277}; r.label="seeded-synthetic-routing";
        for (int i=0;i<K;++i) r.weights[i]=float(K-i)/55.0f;
        rows.push_back(r);
    }
    return rows;
}
struct arm {
    llm_graph_result result{8192}; ggml_gallocr_t alloc=nullptr;
    ggml_tensor * input=nullptr,* output=nullptr,* shared=nullptr,* weighted=nullptr,* native_ids=nullptr,* native_weights=nullptr;
    llama_hot_routing routing;
    llama_hot_stages stages{};
    ggml_backend_sched_t scheduler=nullptr;
    std::map<int,llama_hot_routing_batch> routing_batch;
    ~arm() { ggml_gallocr_free(alloc); }
};
struct bench {
    options o; llama_layer layer; ggml_tensor * omitted_shared_down=nullptr; ggml_context * ctx=nullptr; ggml_backend_buffer_t buffer=nullptr;
    ggml_backend_t cpu=nullptr,rpc=nullptr; ggml_backend_sched_t sched=nullptr;
    std::shared_ptr<llama_hot_experts> owner,owner5,owner10; int phase=2; arm a,b,b10;
    std::vector<int> resident;
    std::string root;
    json bank_evidence[2];
    size_t device_free_before=0,device_total=0;
    std::array<std::string,2> spec_paths;
    int max_tokens=1;
    std::vector<int> token_widths{1};
    bench(options opts):o(std::move(opts)) {}
    void retire(arm & x) {
        if(x.scheduler) {ggml_backend_sched_synchronize(x.scheduler);ggml_backend_sched_reset(x.scheduler);}
        x.result.reset();ggml_gallocr_free(x.alloc);x.alloc=nullptr;
        ggml_backend_sched_free(x.scheduler);x.scheduler=nullptr;
    }
    ~bench() {
        retire(b);retire(b10);retire(a);owner.reset();owner5.reset();owner10.reset();
        ggml_backend_sched_free(sched);ggml_backend_buffer_free(buffer);ggml_free(ctx);
        ggml_backend_free(rpc);ggml_backend_free(cpu);
    }
    void choose(bool ten) {
        resident=ten?std::vector<int>{0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,54,74,136,290,394}:std::vector<int>(HOT.begin(),HOT.end());
        setenv("IS314_HOT_SPEC",spec_paths[ten].c_str(),1);
        owner=ten?owner10:owner5;
    }
    void setup() {
        require(std::filesystem::create_directory(o.work),"work directory must be fresh");root=o.work;
        std::filesystem::create_directories(root+"/banks/p5");std::filesystem::create_directories(root+"/banks/p10");
        cpu=ggml_backend_cpu_init(); require(cpu,"CPU backend unavailable");ggml_backend_cpu_set_n_threads(cpu,o.threads);
        ctx=ggml_init({ggml_tensor_overhead()*32,nullptr,true});require(ctx,"weight metadata allocation failed");
        layer.ffn_gate_inp=ggml_new_tensor_2d(ctx,GGML_TYPE_F32,o.d,E);
        layer.ffn_gate_inp_shexp=ggml_new_tensor_2d(ctx,GGML_TYPE_F32,o.d,1);
        layer.ffn_gate_shexp=ggml_new_tensor_2d(ctx,GGML_TYPE_Q8_0,o.d,o.f);
        layer.ffn_up_shexp=ggml_new_tensor_2d(ctx,GGML_TYPE_Q8_0,o.d,o.f);
        layer.ffn_down_shexp=ggml_new_tensor_2d(ctx,GGML_TYPE_Q8_0,o.f,o.d);
        layer.ffn_gate_exps=ggml_new_tensor_3d(ctx,GGML_TYPE_Q8_0,o.d,o.f,E);
        layer.ffn_up_exps=ggml_new_tensor_3d(ctx,GGML_TYPE_Q8_0,o.d,o.f,E);
        layer.ffn_down_exps=ggml_new_tensor_3d(ctx,GGML_TYPE_Q8_0,o.f,o.d,E);
        const std::array<ggml_tensor *,3> banks={layer.ffn_gate_exps,layer.ffn_up_exps,layer.ffn_down_exps};
        const std::array<std::string,3> names={"gate","up","down"};
        for (int i=0;i<3;++i) ggml_format_name(banks[i],"blk.7.ffn_%s_exps.weight",names[i].c_str());
        ggml_set_name(layer.ffn_gate_inp,"blk.7.ffn_gate_inp.weight");
        ggml_set_name(layer.ffn_gate_inp_shexp,"blk.7.ffn_gate_inp_shexp.weight");
        ggml_set_name(layer.ffn_gate_shexp,"blk.7.ffn_gate_shexp.weight");
        ggml_set_name(layer.ffn_up_shexp,"blk.7.ffn_up_shexp.weight");
        ggml_set_name(layer.ffn_down_shexp,"blk.7.ffn_down_shexp.weight");
        for (auto * x:{&a,&b,&b10}) {
            x->routing.ids=ggml_new_tensor_2d(ctx,GGML_TYPE_I32,K,1);
            x->routing.weights=ggml_new_tensor_3d(ctx,GGML_TYPE_F32,1,K,1);
        }
        // #346: one routing-boundary leaf pair per swept width. The executor
        // and the bound graphs read the exact-width tensor, never a wider one.
        for (int t:token_widths) if (t>1) for (auto * x:{&a,&b,&b10}) {
            x->routing_batch[t].ids=ggml_new_tensor_2d(ctx,GGML_TYPE_I32,K,t);
            x->routing_batch[t].weights=ggml_new_tensor_3d(ctx,GGML_TYPE_F32,1,K,t);
        }
        if (o.control=="missing-shared") {
            omitted_shared_down=ggml_dup_tensor(ctx,layer.ffn_down_shexp);
            ggml_set_name(omitted_shared_down,"benchmark.omitted_shared.down.weight");
        }
        buffer=ggml_backend_alloc_ctx_tensors(ctx,cpu);require(buffer,"weight buffer allocation failed");
        ggml_backend_buffer_set_usage(buffer,GGML_BACKEND_BUFFER_USAGE_WEIGHTS);
        uint32_t state=o.seed;
        // Row-sized staging, deterministic signed dense nonzero weights; never download a model.
        for (auto t=ggml_get_first_tensor(ctx);t;t=ggml_get_next_tensor(ctx,t)) {
            if (t==omitted_shared_down || t->type==GGML_TYPE_I32 || ggml_nelements(t)==K) continue;
            std::vector<float> row(t->ne[0]); std::vector<uint8_t> encoded(ggml_row_size(t->type,t->ne[0]));
            const float scale=0.35f/std::sqrt(float(t->ne[0]));
            for (int64_t i=0;i<ggml_nelements(t)/t->ne[0];++i) {
                for (auto & v:row) v=sample(state)*scale;
                if (t->type==GGML_TYPE_Q8_0) {
                    ggml_quantize_chunk(t->type,row.data(),encoded.data(),0,1,t->ne[0],nullptr);
                    ggml_backend_tensor_set(t,encoded.data(),i*encoded.size(),encoded.size());
                } else ggml_backend_tensor_set(t,row.data(),i*row.size()*4,row.size()*4);
            }
        }
        if (omitted_shared_down) {
            std::vector<uint8_t> zero(ggml_nbytes(omitted_shared_down),0);
            ggml_backend_tensor_set(omitted_shared_down,zero.data(),0,zero.size());
        }
        if (o.control=="native-routing") {
            std::vector<float> router(o.d*E,0.0f);
            const int ids[K]={136,17,394,231,54,3,290,411,74,277};
            for (int i=0;i<K;++i) router[ids[i]*o.d]=float(K-i)/3;
            ggml_backend_tensor_set(layer.ffn_gate_inp,router.data(),0,router.size()*4);
        }
        // Observe every immutable weight exactly once, outside all timing pairs.
        json inventory={{"schema","h5-layer7-weights/1"},{"tensors",json::array()}};
        std::map<std::string,std::string> weight_hashes;
        for (auto * t:{layer.ffn_gate_exps,layer.ffn_up_exps,layer.ffn_down_exps,
                layer.ffn_gate_shexp,layer.ffn_up_shexp,layer.ffn_down_shexp,
                layer.ffn_gate_inp_shexp,layer.ffn_gate_inp,omitted_shared_down}) {
            if (!t) continue;
            std::vector<uint8_t> bytes(ggml_nbytes(t));ggml_backend_tensor_get(t,bytes.data(),0,bytes.size());
            auto hash=sha(bytes.data(),bytes.size());weight_hashes[t->name]=hash;
            inventory["tensors"].push_back({{"name",t->name},{"ggml_type",int(t->type)},
                {"shape",{t->ne[0],t->ne[1],t->ne[2],t->ne[3]}},{"byte_length",bytes.size()},{"sha256",hash}});
        }
        std::ofstream(o.work+"/weights.json")<<inventory.dump(2)<<"\n";
        std::ofstream assigned(root+"/assigned.txt");
        for(bool ten:{false,true}) {
            resident=ten?std::vector<int>{0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,54,74,136,290,394}:std::vector<int>(HOT.begin(),HOT.end());
            json spec={{"schema","is314-hot-experts/1"},{"layer",7},{"rpc_backend","RPC["+o.endpoint+"]"},{"expert_ids",resident},{"tensors",json::array()}};
            for(int i=0;i<3;++i) {
                auto * t=banks[i];size_t stride=t->nb[2];std::vector<uint8_t> compact(stride*resident.size());json ranges=json::array();
                for(size_t n=0;n<resident.size();++n) {
                    std::memcpy(compact.data()+n*stride,static_cast<uint8_t *>(t->data)+resident[n]*stride,stride);
                    ranges.push_back({{"expert_id",resident[n]},{"source_offset",resident[n]*stride},{"destination_offset",n*stride},{"length",stride}});
                }
                std::string name="is314.layer7.factorial.p"+std::string(ten?"10":"5")+"."+names[i],hash=sha(compact.data(),compact.size());
                spec["tensors"].push_back({{"source_name",t->name},{"compact_name",name},{"ggml_type",int(t->type)},
                    {"source_shape",{t->ne[0],t->ne[1],E,1}},{"compact_shape",{t->ne[0],t->ne[1],resident.size(),1}},
                    {"source_sha256",weight_hashes.at(t->name)},{"compact_sha256",hash},{"expert_bytes",stride},{"ranges",ranges}});
                assigned<<name<<" 8 "<<t->ne[0]<<" "<<t->ne[1]<<" "<<resident.size()<<" 1 "<<compact.size()<<" "<<hash<<"\n";
            }
            spec_paths[ten]=root+"/banks/p"+std::string(ten?"10":"5")+"/spec.json";
            std::ofstream(spec_paths[ten])<<spec.dump(2)<<"\n";
        }
        assigned.close();setenv("IS311_ASSIGNED",(root+"/assigned.txt").c_str(),1);
        for(bool ten:{false,true}) for(const auto name:{"weights.json","assigned.txt"})
            std::filesystem::copy_file(root+"/"+name,root+"/banks/p"+std::string(ten?"10":"5")+"/"+name);
        rpc=ggml_backend_rpc_init(o.endpoint.c_str(),0);require(rpc,"RPC backend unavailable");
        ggml_backend_dev_memory(ggml_backend_get_device(rpc),&device_free_before,&device_total);
        if(o.comparison_mode=="cpu-cuda") require(device_free_before>=1024ull*1024*1024,"GPU free memory below frozen 1 GiB setup floor");
        ggml_backend_t backends[]={rpc,cpu};sched=ggml_backend_sched_new(backends,nullptr,2,8192,false,false);require(sched,"scheduler unavailable");
        build(a,false,1);choose(false);build(b,true,1);owner5=owner;choose(true);build(b10,true,1);owner10=owner;
    }
    void build(arm & x,bool hot,int tokens) {
        llama_adapter_loras loras;llm_graph_params p={};
        p.arch=LLM_ARCH_QWEN4EXP;p.hparams.n_layer_all=9;p.hparams.n_embd=o.d;p.hparams.n_expert=E;p.hparams.n_expert_used_arr.fill(K);
        p.hparams.n_head_arr.fill(1);p.hparams.n_head_kv_arr.fill(1);p.hparams.n_embd_head_k_full=o.d;p.hparams.n_embd_head_v_full=o.d;p.hparams.n_rot_full=o.d;
        p.hparams.expert_weights_scale=1;p.cparams.n_threads=o.threads;p.cparams.n_threads_batch=o.threads;p.ubatch.n_tokens=tokens;
        if(hot) {ggml_backend_t backends[]={rpc,cpu};x.scheduler=ggml_backend_sched_new(backends,nullptr,2,8192,false,false);require(x.scheduler,"arm scheduler unavailable");}
        auto current_sched=hot?x.scheduler:sched;
        p.sched=current_sched;p.backend_cpu=cpu;p.loras=&loras;p.res=&x.result;p.hot_owner=&owner;p.hot_phase=&phase;
        p.cb=[](const llama_ubatch &,ggml_tensor * t,const char * name,int il){ggml_format_name(t,"%s-%d",name,il);};
        llm_graph_context builder(p);
        x.input=ggml_new_tensor_2d(x.result.get_ctx(),GGML_TYPE_F32,o.d,tokens);ggml_set_input(x.input);
        // A complete valid H5 graph with zero B-only shared down projection:
        // numerical omission sensitivity, not merely constructor refusal.
        auto selected=layer;if (hot && omitted_shared_down) selected.ffn_down_shexp=omitted_shared_down;
        if (hot) {
            auto cfg=llama_hot_config(9);
            cfg.benchmark_stages=o.capture_stages && (tokens==2 || o.operand_replay);
            if (o.control!="native-routing") {
                if (tokens>1) cfg.benchmark_routing_batch=&x.routing_batch.at(tokens);
                else cfg.benchmark_routing=&x.routing;
            }
            x.output=builder.build_qwen4exp_ffn(x.input,selected,7,cfg);
        } else {
            x.output=builder.build_qwen4exp_ffn_native(x.input,selected,7);
            if (o.control!="native-routing") {
                if (tokens>1) llama_hot_bind_routing_batch(x.result.get_ctx(),x.output,7,x.routing_batch.at(tokens));
                else llama_hot_bind_routing(x.result.get_ctx(),x.output,7,x.routing);
            }
            x.shared=x.output->src[1];ggml_set_output(x.shared);
            x.weighted=ggml_get_tensor(x.result.get_ctx(),"ffn_moe_weighted-7");ggml_set_output(x.weighted);
            if (o.capture_stages && (tokens==2 || o.operand_replay)) x.stages=llama_hot_retain_stages(x.weighted);
            if (o.control=="native-routing") {
                x.native_ids=ggml_cont(x.result.get_ctx(),x.weighted->src[0]->src[2]);ggml_set_output(x.native_ids);
                x.native_weights=x.weighted->src[1];ggml_set_output(x.native_weights);
            }
        }
        ggml_set_output(x.output);ggml_graph_clear(x.result.get_gf());ggml_build_forward_expand(x.result.get_gf(),x.output);
        if (x.native_ids) ggml_build_forward_expand(x.result.get_gf(),x.native_ids);
        if (hot) require(ggml_backend_sched_alloc_graph(current_sched,x.result.get_gf()),"H5 graph allocation failed");
        else {
            x.alloc=ggml_gallocr_new(ggml_backend_get_default_buffer_type(cpu));
            require(x.alloc && ggml_gallocr_alloc_graph(x.alloc,x.result.get_gf()),"CPU graph allocation failed");
        }
    }
    // Rebuild both arms at a new batch width. The owner, compact weights and
    // RPC connection persist; a new llama_hot_graph is built per width. The
    // previous arms' graphs are released before rebuilding, and the shared
    // scheduler is reset so the new graph's splits allocate cleanly.
    void rebuild(int tokens) {
        require(tokens==1 || tokens==4,"factorial width outside scope");
        retire(b);retire(b10);retire(a);
        build(a,false,tokens);choose(false);build(b,true,tokens);owner5=owner;choose(true);build(b10,true,tokens);owner10=owner;
    }
    double execute(arm & x,bool hot,std::vector<float> & out) {
        auto start=clock_type::now();
        auto status=hot?ggml_backend_sched_graph_compute(x.scheduler,x.result.get_gf()):ggml_backend_graph_compute(cpu,x.result.get_gf());
        if (hot) ggml_backend_sched_synchronize(x.scheduler);else ggml_backend_synchronize(cpu);
        double elapsed=ms(start);require(status==GGML_STATUS_SUCCESS,"graph execution failed");
        ggml_backend_tensor_get(x.output,out.data(),0,out.size()*4);return elapsed;
    }
};
json distribution(std::vector<double> v) {
    require(!v.empty(),"empty distribution");std::sort(v.begin(),v.end());double sum=0;for (auto x:v) sum+=x;
    return {{"n",v.size()},{"min",v.front()},{"median",v.size()%2?v[v.size()/2]:(v[v.size()/2-1]+v[v.size()/2])/2},
        {"p95",v[size_t(std::ceil(v.size()*0.95))-1]},{"max",v.back()},{"mean",sum/v.size()}};
}
json bits(const route & r) {
    json b=json::array();for (auto v:r.weights) { uint32_t n;std::memcpy(&n,&v,4);std::ostringstream s;s<<std::hex<<std::setw(8)<<std::setfill('0')<<n;b.push_back(s.str()); }return b;
}
// Unchanged legacy-cpu-unsplit/1 formula from moe_overlap_harness.cpp:590-620.
// This empirical screen is not independent operand/backend qualification.
constexpr double F32_ROUND=1.1920928955078125e-7;
constexpr double ASSOC=8.0*F32_ROUND, QUANT_HEADROOM=1.0/128.0;
json comparison_contract(const std::string & mode) {
    return {{"id","legacy-cpu-unsplit/1"},{"mode",mode},{"f32_round",F32_ROUND},
        {"association_multiplier",8},{"cross_backend_headroom",QUANT_HEADROOM},
        {"zero_plane_fallback",ASSOC},{"plane_source","A weighted slots"}};
}
json diagnostic(const std::vector<float> & a,const std::vector<float> & b,
        const std::vector<float> & planes,const std::vector<float> & shared,size_t d,bool cross_backend,bool locate=false) {
    require(d>0 && !a.empty() && a.size()%d==0 && a.size()==b.size() && planes.size()==K*a.size() && shared.size()==a.size(),"comparison shape mismatch");
    bool finite=true,equal=true,pass=true;double max_abs=0,max_ratio=0,squared=0,ref=0; json abs_at=nullptr,ratio_at=nullptr;
    for (size_t e=0;e<a.size();++e) {
        double l1=0;
        // weighted slots are [d,K,T], while outputs are [d,T].
        for (int i=0;i<K;++i) { double p=planes[((e/d)*K+i)*d+e%d];finite &= std::isfinite(p);l1+=std::fabs(p); }
        double tol=ASSOC*l1+(cross_backend?QUANT_HEADROOM:0.0)*l1;
        if (tol<=0.0) tol=ASSOC;
        finite &= std::isfinite(a[e]) && std::isfinite(b[e]) && std::isfinite(shared[e]);equal &= a[e]==b[e];
        const double error=std::abs(double(a[e])-b[e]);
        if (locate && (abs_at.is_null() || error>max_abs || ratio_at.is_null() || error/tol>max_ratio)) {
            json at={{"flat_index",e},{"token",e/d},{"coordinate",e%d},{"A",a[e]},{"B",b[e]},
                {"abs_error",error},{"scale_l1",l1},{"tolerance",tol},{"ratio",error/tol}};
            if (abs_at.is_null() || error>max_abs) abs_at=at;
            if (ratio_at.is_null() || error/tol>max_ratio) ratio_at=at;
        }
        double d=double(a[e])-b[e];max_abs=std::max(max_abs,std::abs(d));squared+=d*d;ref+=double(a[e])*a[e];
        max_ratio=std::max(max_ratio,std::abs(d)/tol);if (std::abs(d)>tol) pass=false;
    }
    json result={{"pass",finite && pass},{"finite",finite},{"exact_equal",finite && equal},
        {"max_abs",finite?json(max_abs):json(nullptr)},{"max_ratio",finite?json(max_ratio):json(nullptr)},
        {"rms",finite?json(std::sqrt(squared/a.size())):json(nullptr)}, {"relative_l2",finite?json(std::sqrt(squared/std::max(ref,1e-300))):json(nullptr)}};
    if (locate) {
        result["max_abs_at"]=finite?abs_at:json(nullptr);
        result["max_ratio_at"]=finite?ratio_at:json(nullptr);
    }
    return result;
}
bool used_replacement(const std::vector<route> & rows,int candidate) {
    for (auto & r:rows) for (auto id:r.ids) if (id==candidate) return true;
    return false;
}
struct fixture { std::vector<route> rows; std::vector<float> input; };
fixture make_fixture(const options & o,const std::vector<route> & routing,int tokens,
        const std::string & name,bool shared_set,int pair) {
    // Deterministic distinct routing row per token. Slot
    // order rotates per (pair,token). Varied sets replace
    // COLD slots with distinct unused globals per token —
    // the five hot experts are the fixed resident set, so
    // only non-resident slots can differ across tokens.
    std::vector<route> rows;
    for (int t=0;t<tokens;++t) {
        auto &src_row=routing[(size_t(pair)*routing.size()/o.pairs+size_t(t)*(shared_set?0:1))%routing.size()];
        route r=src_row; r.label=src_row.label;
        if (o.routing.empty()) {
            std::rotate(r.ids.begin(),r.ids.begin()+(pair+t*(shared_set?0:1))%K,r.ids.end());
            std::rotate(r.weights.begin(),r.weights.begin()+(pair+t*(shared_set?0:1))%K,r.weights.end());
        }
        for (auto & id:r.ids) {
            const bool is_hot=std::find(HOT.begin(),HOT.end(),id)!=HOT.end();
            // shared-set rows repeat token 0's replacements verbatim;
            // varied-set rows must not reuse an earlier token's experts.
            const bool block_reuse=!shared_set;
            if (name=="all-cold" && is_hot) {
                int replacement=0;while (std::find(HOT.begin(),HOT.end(),replacement)!=HOT.end() ||
                        std::find(r.ids.begin(),r.ids.end(),replacement)!=r.ids.end() ||
                        (block_reuse && used_replacement(rows,replacement))) ++replacement;
                id=replacement;
            } else if (name=="mixed" && !shared_set && !is_hot) {
                int replacement=0;while (std::find(HOT.begin(),HOT.end(),replacement)!=HOT.end() ||
                        std::find(r.ids.begin(),r.ids.end(),replacement)!=r.ids.end() ||
                        used_replacement(rows,replacement)) ++replacement;
                id=replacement;
            }
        }
        if (o.control=="bad-partition") r.ids[1]=r.ids[0];
        validate(r);rows.push_back(r);
    }
    uint32_t state=o.seed+uint32_t(pair+1)*7919+uint32_t(tokens)*104729;
    std::vector<float> input(o.d*tokens);
    for (auto & v:input) v=sample(state)*0.8f+0.1f;
    return {std::move(rows),std::move(input)};
}
std::vector<uint8_t> captured_weighted(const llama_hot_observation & observation,const std::vector<int> & resident) {
    const auto * shape=observation.weighted_shape;
    require(shape && observation.hot_weighted,"mixed capture branch outputs missing");
    const size_t d=shape->ne[0],tokens=shape->ne[2];
    std::vector<uint8_t> restored(ggml_nbytes(shape)),hot,cold;
    auto read=[&](ggml_tensor * t,std::vector<uint8_t> & bytes) {
        if (!t) return size_t(0);
        require(t->type==GGML_TYPE_F32 && ggml_is_contiguous(t) && size_t(t->ne[0])==d &&
            size_t(t->ne[2])==tokens && t->ne[3]==1,"capture branch layout mismatch");
        bytes.resize(ggml_nbytes(t));ggml_backend_tensor_get(t,bytes.data(),0,bytes.size());
        return size_t(t->ne[1]);
    };
    const auto nh=read(observation.hot_weighted,hot),nc=read(observation.cold_weighted,cold);
    require(shape->type==GGML_TYPE_F32 && shape->ne[1]==K && shape->ne[3]==1 && nh+nc==K,"capture slot layout mismatch");
    std::vector<int32_t> ids(K*tokens);ggml_backend_tensor_get(observation.ids,ids.data(),0,ids.size()*sizeof(int32_t));
    for (size_t t=0;t<tokens;++t) {
        size_t h=0,c=0;
        for (size_t slot=0;slot<K;++slot) {
            const bool is_hot=std::find(resident.begin(),resident.end(),ids[t*K+slot])!=resident.end();
            require(is_hot?h<nh:c<nc,"capture branch partition mismatch");
            const auto * src=is_hot?hot.data()+(t*nh+h++)*d*4:cold.data()+(t*nc+c++)*d*4;
            std::memcpy(restored.data()+(t*K+slot)*d*4,src,d*4);
        }
        require(h==nh && c==nc,"capture branch partition mismatch");
    }
    return restored;
}
// All reads occur after execute() synchronized both arms, outside the timers.
// One capture per run, at most 16 MiB payload plus 64 KiB metadata. A partial
// directory never has a successful manifest and never changes the comparator.
json capture(bench & s,arm & target,const json & row) {
    const uint32_t endian=1;
    require(*reinterpret_cast<const uint8_t *>(&endian)==1,"capture requires little endian host");
    auto observation=llama_hot_get_observation(target.result.hot_experts.at(0));
    const int tokens=row.at("tokens");
    auto * ai=tokens>1?s.a.routing_batch.at(tokens).ids:s.a.routing.ids;
    auto * aw=tokens>1?s.a.routing_batch.at(tokens).weights:s.a.routing.weights;
    if (s.a.native_ids) { ai=s.a.native_ids; aw=s.a.native_weights; }
    const std::vector<std::pair<std::string,ggml_tensor *>> tensors={
        {"A.input",s.a.input},{"B.input",observation.input},
        {"A.ids",ai},{"A.weights",aw},{"B.ids",observation.ids},{"B.weights",observation.weights},
        {"A.output",s.a.output},{"B.output",target.output},{"B.remote_sum",observation.remote_sum},
        {"A.weighted",s.a.weighted},{"A.shared",s.a.shared},
        {"B.weighted",observation.weighted_shape},{"B.shared",observation.shared},
        {"B.hot.input",observation.hot_input},{"B.hot.ids",observation.hot_ids},{"B.hot.weights",observation.hot_weights},
        {"B.cold.ids",observation.cold_ids},{"B.cold.weights",observation.cold_weights}};
    size_t total=0;
    for (const auto & entry:tensors) if (auto * t=entry.second) {
        require(ggml_is_contiguous(t),"capture requires contiguous tensor: "+entry.first);
        require(ggml_nbytes(t)<=s.o.dump_max_bytes-total,"capture payload budget exceeded");
        total+=ggml_nbytes(t);
    }
    const auto directory=std::filesystem::path(s.o.work)/"capture";
    require(std::filesystem::create_directory(directory),"capture path must be fresh");
    json manifest={{"schema","h5-layer7-capture/2"},{"byte_order","little"},{"payload_bytes",total},
        {"payload_limit_bytes",s.o.dump_max_bytes},{"pair_record",row},{"tensors",json::object()},
        {"weighted_layout","[coordinate,original_slot,token]; coordinate fastest"},
        {"B_weighted_source","retained-branch-outputs/1"},
        {"output_layout","[coordinate,token]; coordinate fastest"},
        {"B_unavailable",observation.weighted_shape?json::array():json({"weighted/shared: zero-hot fast graph intermediates not retained"})}};
    manifest["hot_count"]=row.at("hot");manifest["cold_count"]=row.at("cold");manifest["resident_expert_order"]=s.resident;
    manifest["absent_branches"]=row.at("cold")==0?json({"cold"}):json::array();
    std::map<std::string,std::vector<uint8_t>> bytes;
    for (const auto & entry:tensors) if (auto * t=entry.second) {
        auto & data=bytes[entry.first];data.resize(ggml_nbytes(t));
        if (entry.first=="B.weighted") data=captured_weighted(observation,s.resident);
        else ggml_backend_tensor_get(t,data.data(),0,data.size());
        const auto filename=entry.first+".bin";
        std::ofstream file(directory/filename,std::ios::binary);file.exceptions(std::ios::badbit|std::ios::failbit);
        file.write(reinterpret_cast<const char *>(data.data()),data.size());file.close();
        manifest["tensors"][entry.first]={{"file",filename},{"tensor_name",t->name},{"ggml_type",int(t->type)},
            {"type_name",ggml_type_name(t->type)},{"shape",{t->ne[0],t->ne[1],t->ne[2],t->ne[3]}},
            {"strides_bytes",{t->nb[0],t->nb[1],t->nb[2],t->nb[3]}},{"byte_length",data.size()},{"sha256",sha(data.data(),data.size())}};
    }
    bool identity=true;
    for (const std::string arm_name:{"A","B"}) {
        const auto & input=bytes.at(arm_name+".input");
        auto routing=bytes.at(arm_name+".ids");const auto & weights=bytes.at(arm_name+".weights");
        routing.insert(routing.end(),weights.begin(),weights.end());
        identity &= sha(input.data(),input.size())==row.at("input_sha256").get<std::string>() && sha(routing.data(),routing.size())==row.at("routing_sha256").get<std::string>();
    }
    manifest["consumed_identity_matches_pair"]=identity;
    const auto & ids=bytes.at("B.ids");
    manifest["slot_map"]=json::array();
    for (int token=0;token<tokens;++token) {
        int hot_slot=0,cold_slot=0;
        for (int slot=0;slot<K;++slot) {
            int32_t id;std::memcpy(&id,ids.data()+(token*K+slot)*4,4);
            auto dense=std::find(s.resident.begin(),s.resident.end(),id);bool hot=dense!=s.resident.end();
            manifest["slot_map"].push_back({{"token",token},{"original_slot",slot},{"global_expert",id},
                {"branch",hot?"hot":"cold"},{"branch_slot",hot?hot_slot++:cold_slot++},
                {"compact_expert",hot?json(dense-s.resident.begin()):json(nullptr)}});
        }
    }
    for (const std::string name:{"weights.json","spec.json","assigned.txt"}) {
        std::ifstream f(std::filesystem::path(s.o.work)/name,std::ios::binary);
        require(bool(f),"capture identity file missing");const std::string data((std::istreambuf_iterator<char>(f)),{});
        manifest["identities"][name]=sha(data.data(),data.size());
    }
    const auto text=manifest.dump(2)+"\n";require(text.size()<=65536,"capture metadata budget exceeded");
    std::ofstream file(directory/"manifest.json");file.exceptions(std::ios::badbit|std::ios::failbit);file<<text;file.close();
    return {{"status","complete"},{"manifest","capture/manifest.json"},{"payload_bytes",total},{"consumed_identity_matches_pair",identity}};
}
json tensor_metadata(ggml_tensor * t) {
    return {{"tensor_name",t->name},{"ggml_type",int(t->type)},{"type_name",ggml_type_name(t->type)},
        {"shape",{t->ne[0],t->ne[1],t->ne[2],t->ne[3]}},{"strides_bytes",{t->nb[0],t->nb[1],t->nb[2],t->nb[3]}},
        {"op",ggml_op_name(t->op)},{"flags",t->flags}};
}
std::string file_bytes(const std::filesystem::path & p) {
    std::ifstream f(p,std::ios::binary);require(bool(f),"missing evidence file: "+p.string());
    return std::string((std::istreambuf_iterator<char>(f)),{});
}
void save_json(const std::filesystem::path & path,const json & value) {
    std::ofstream f(path);f.exceptions(std::ios::badbit|std::ios::failbit);f<<value.dump(2)<<"\n";f.close();
}
void export_banks(bench & s,arm & target,bool ten) {
    s.choose(ten);const auto directory=std::filesystem::path(s.root)/"banks"/(ten?"p10":"p5");
    const auto remote=llama_hot_get_compact(target.result.hot_experts.at(0));
    const std::array<ggml_tensor *,3> source={s.layer.ffn_gate_exps,s.layer.ffn_up_exps,s.layer.ffn_down_exps};
    const std::array<std::string,3> names={"gate","up","down"};
    auto spec=json::parse(file_bytes(directory/"spec.json"));
    json manifest={{"schema","h5-layer7-factorial-banks/1"},{"byte_order","little"},
        {"hot_count",ten?10:5},{"cold_count",ten?0:5},{"resident_expert_order",s.resident},
        {"files",json::object()},{"identities",json::object()}};
    size_t total=0;
    for(size_t bank=0;bank<3;++bank) {
        auto * a=source[bank];auto * b=remote[bank];
        require(b->type==GGML_TYPE_Q8_0 && ggml_is_contiguous(b) && b->ne[0]==a->ne[0] &&
            b->ne[1]==a->ne[1] && size_t(b->ne[2])==s.resident.size() && b->ne[3]==1,"setup bank shape mismatch");
        std::vector<uint8_t> observed(ggml_nbytes(b)),selected(a->nb[2]*s.resident.size());
        for(size_t i=0;i<s.resident.size();++i)
            ggml_backend_tensor_get(a,selected.data()+i*a->nb[2],s.resident[i]*a->nb[2],a->nb[2]);
        ggml_backend_tensor_get(b,observed.data(),0,observed.size());
        require(selected==observed,"setup remote bank readback differs from frozen CPU slices");
        auto meta=tensor_metadata(b);meta["byte_length"]=observed.size();meta["sha256"]=sha(observed.data(),observed.size());
        require(spec["tensors"][bank]["compact_sha256"]==meta["sha256"],"setup spec compact hash mismatch");
        meta["B_actual_sha256"]=meta["sha256"];meta["source_tensor"]=a->name;
        meta["source_shape"]={a->ne[0],a->ne[1],a->ne[2],a->ne[3]};
        meta["source_sha256"]=spec["tensors"][bank]["source_sha256"];
        meta["block_elements"]=32;meta["block_bytes"]=34;
        meta["provenance"]="whole frozen CPU expert slices equal actual remote compact readback once at setup";
        const auto name=names[bank]+".q8_0.bin";
        std::ofstream f(directory/name,std::ios::binary);f.exceptions(std::ios::badbit|std::ios::failbit);
        f.write(reinterpret_cast<const char *>(observed.data()),observed.size());f.close();
        manifest["files"][name]=meta;total+=observed.size();
    }
    const size_t expected=3*size_t(s.o.d)*s.o.f/32*34*s.resident.size();
    require(total==expected,"resident bank payload calculation mismatch");manifest["payload_bytes"]=total;
    for(const auto name:{"weights.json","spec.json","assigned.txt"}) {const auto bytes=file_bytes(directory/name);manifest["identities"][name]=sha(bytes.data(),bytes.size());}
    save_json(directory/"manifest.json",manifest);s.bank_evidence[ten]=manifest;
}
json capture_stages(bench & s,arm & target,const json & row,bool ten) {
    constexpr size_t limit=32*1024*1024;const int tokens=row.at("tokens");const int count=ten?10:5;
    const auto directory=std::filesystem::path(s.o.work)/"stages";
    const auto b=llama_hot_get_stages(target.result.hot_experts.at(0));
    require(s.a.stages[0] && b[0],"factorial executed stages unavailable");
    require(std::filesystem::create_directory(directory),"fresh stages required");
    const std::array<std::string,5> names={"gate","up","swiglu","down","weighted"};
    const std::string relative="../../../banks/"+std::string(ten?"p10":"p5")+"/";
    const auto bank_bytes=file_bytes(directory/relative/"manifest.json");
    json manifest={{"schema","h5-layer7-factorial-stages/1"},{"byte_order","little"},{"threads",s.o.threads},
        {"pair_record",row},{"payload_limit_bytes",limit},{"files",json::object()},
        {"execution","existing executed graphs with OUTPUT retention; no recomputation"},
        {"perturbation","untimed A ten-slot and B selected remote stages retained; no timed retention"},
        {"performance_claim",false},{"hot_count",count},{"cold_count",10-count},{"resident_expert_order",s.resident},
        {"bank_manifest",relative+"manifest.json"},{"bank_manifest_sha256",sha(bank_bytes.data(),bank_bytes.size())}};
    size_t total=0;
    for(int which=0;which<2;++which) {
        const auto & stages=which?b:s.a.stages;
        for(size_t i=0;i<5;++i) {
            auto * t=stages[i];require(t && t->type==GGML_TYPE_F32 && ggml_is_contiguous(t) &&
                t->ne[0]==(i<3?s.o.f:s.o.d) && t->ne[1]==(which?count:10) && t->ne[2]==tokens &&
                t->ne[3]==1 && (t->flags&GGML_TENSOR_FLAG_OUTPUT),"factorial retained stage layout/lifetime");
            std::vector<uint8_t> bytes(ggml_nbytes(t));require(bytes.size()<=limit-total,"unchanged per-capture stage budget exceeded");
            ggml_backend_tensor_get(t,bytes.data(),0,bytes.size());const auto name=std::string(which?"B.":"A.")+names[i]+".bin";
            std::ofstream f(directory/name,std::ios::binary);f.exceptions(std::ios::badbit|std::ios::failbit);
            f.write(reinterpret_cast<const char *>(bytes.data()),bytes.size());f.close();
            auto meta=tensor_metadata(t);meta["byte_length"]=bytes.size();meta["sha256"]=sha(bytes.data(),bytes.size());
            manifest["files"][name]=meta;total+=bytes.size();
        }
    }
    for(const auto & item:s.bank_evidence[ten]["files"].items()) {auto meta=item.value();meta["file"]=relative+item.key();manifest["files"][item.key()]=meta;}
    const auto capture_bytes=file_bytes(std::filesystem::path(s.o.work)/"capture/manifest.json");const auto base=json::parse(capture_bytes);
    manifest["capture_manifest_sha256"]=sha(capture_bytes.data(),capture_bytes.size());manifest["slot_map"]=base.at("slot_map");
    manifest["input_sha256"]=row.at("input_sha256");manifest["routing_sha256"]=row.at("routing_sha256");manifest["payload_bytes"]=total;
    require(manifest.dump().size()<=65536,"stage metadata bound");save_json(directory/"manifest.json",manifest);return manifest;
}
json rpc_json(const is_factorial_rpc_stats & r) {
    json j=json::object();
#define RPC_FIELD(name) j[#name]=r.name
    RPC_FIELD(begin_ns);RPC_FIELD(end_ns);RPC_FIELD(group_enqueue_ns);RPC_FIELD(group_dequeue_ns);RPC_FIELD(group_end_ns);
    RPC_FIELD(graph_enqueue_ns);RPC_FIELD(graph_write_begin_ns);RPC_FIELD(graph_write_end_ns);RPC_FIELD(graph_uid);RPC_FIELD(graph_recompute);
    RPC_FIELD(get_enqueue_ns);RPC_FIELD(get_write_begin_ns);RPC_FIELD(get_write_end_ns);RPC_FIELD(get_first_byte_ns);RPC_FIELD(get_last_byte_ns);
    RPC_FIELD(tx_wire_bytes);RPC_FIELD(rx_wire_bytes);RPC_FIELD(tx_payload_bytes);RPC_FIELD(commands);RPC_FIELD(set_commands);RPC_FIELD(set_acks);
    RPC_FIELD(graph_commands);RPC_FIELD(get_commands);RPC_FIELD(pipeline);RPC_FIELD(timeout_ms);RPC_FIELD(failed);
#undef RPC_FIELD
    j["sets"]=json::array();for(const auto & a:r.sets) {json x;
#define SET_FIELD(name) x[#name]=a.name
        SET_FIELD(hash_begin_ns);SET_FIELD(hash_end_ns);SET_FIELD(enqueue_ns);SET_FIELD(write_begin_ns);SET_FIELD(write_end_ns);
        SET_FIELD(flush_ns);SET_FIELD(ack_first_ns);SET_FIELD(ack_end_ns);SET_FIELD(payload_bytes);SET_FIELD(wire_bytes);
#undef SET_FIELD
        j["sets"].push_back(x);
    }return j;
}
json stats_json(const llama_hot_stats & s) {
    json j={{"hot",s.hot},{"cold",s.cold},{"tokens",s.tokens},{"h5_layer_ms",s.layer_ms},
        {"dispatch_ms",s.dispatch_ms},{"cold_ms",s.cold_ms},{"shared_ms",s.shared_ms},{"join_ms",s.join_ms},
        {"input_bytes",s.input_bytes},{"routing_bytes",s.routing_bytes},{"result_bytes",s.result_bytes},
        {"owner",s.compact_owner},{"rpc",rpc_json(s.rpc)}};
#define LOCAL_FIELD(name) j[#name]=s.name
    LOCAL_FIELD(cold_begin_ns);LOCAL_FIELD(cold_end_ns);LOCAL_FIELD(shared_end_ns);LOCAL_FIELD(join_begin_ns);LOCAL_FIELD(join_end_ns);
    LOCAL_FIELD(reduced_output);LOCAL_FIELD(restore_end_ns);LOCAL_FIELD(reduce_end_ns);LOCAL_FIELD(compact_bytes);LOCAL_FIELD(staging_peak);
    LOCAL_FIELD(cpu_arena_bytes);LOCAL_FIELD(rpc_arena_bytes);LOCAL_FIELD(result_workspace_bytes);LOCAL_FIELD(metadata_bytes);
#undef LOCAL_FIELD
    return j;
}
const std::array<std::string,5> ARM_NAMES={"cpu","pipeline5","reduced5","pipeline10","reduced10"};
std::array<int,5> block_order(int pair) {
    std::array<int,5> order{};for(int i=0;i<5;++i) order[i]=(pair%5+i)%5;
    if(pair%10>=5) std::reverse(order.begin(),order.end());return order;
}
void bind(bench & s,arm & target,const fixture & f,int tokens) {
    std::vector<int32_t> ids;std::vector<float> weights;
    for(const auto & r:f.rows) for(int k=0;k<K;++k) {ids.push_back(r.ids[k]);weights.push_back(r.weights[k]);}
    ggml_backend_tensor_set(target.input,f.input.data(),0,f.input.size()*4);
    auto * ri=tokens>1?target.routing_batch.at(tokens).ids:target.routing.ids;
    auto * rw=tokens>1?target.routing_batch.at(tokens).weights:target.routing.weights;
    ggml_backend_tensor_set(ri,ids.data(),0,ids.size()*4);ggml_backend_tensor_set(rw,weights.data(),0,weights.size()*4);
}
options factorial_options(int argc,char ** argv) {
    options o;o.tokens_list="1,4";o.operand_replay=true;
    for(int i=1;i<argc;++i) {
        std::string a=argv[i];
        if(a=="--small-test") {o.small=true;o.d=32;o.f=32;continue;}
        if(a=="--quick") {o.warmup=1;o.pairs=2;continue;}
        require(i+1<argc,"option value required");const std::string v=argv[++i];
        if(a=="--endpoint") o.endpoint=v;else if(a=="--work-dir") o.work=v;
        else if(a=="--threads") o.threads=number(v,1,14);else if(a=="--comparison-mode") o.comparison_mode=v;
        else throw std::runtime_error("unknown factorial option "+a);
    }
    require(!o.endpoint.empty() && !o.work.empty(),"endpoint and fresh work directory required");
    require(o.comparison_mode=="cpu-loopback" || o.comparison_mode=="cpu-cuda","comparison mode");
    require(o.pairs==20 || o.small,"quick grid requires small-test");
    for(auto key:{"IS309_MOE","IS309_CAPTURE","IS314_HOT_SPEC","IS311_ASSIGNED","IS_FACTORIAL_TRANSPORT","IS_REDUCED_OUTPUT"})
        require(!std::getenv(key),std::string("refuse inherited ")+key);
    return o;
}
} // namespace
int main(int argc,char ** argv) {
    try {
        auto o=factorial_options(argc,argv);auto routing=routes(o);
        // Freeze and verify the full production fixture union even for quick local tests.
        options frozen=o;frozen.pairs=20;std::set<int> selected;
        for(int t:{1,4}) for(int p=0;p<20;++p) for(const auto & r:make_fixture(frozen,routing,t,"mixed",false,p).rows)
            selected.insert(r.ids.begin(),r.ids.end());
        std::set<int> expected={0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,54,74,136,290,394};
        require(selected==expected,"frozen fixture resident union changed");
        bench s(o);s.token_widths={1,4};s.max_tokens=4;
        auto setup=clock_type::now();s.setup();export_banks(s,s.b,false);export_banks(s,s.b10,true);
        const auto root=s.root;
        const auto memory=[&](){size_t free=0,total=0;ggml_backend_dev_memory(ggml_backend_get_device(s.rpc),&free,&total);
            require(total==s.device_total,"device total memory changed");
            const auto delta=s.device_free_before>free?s.device_free_before-free:0;
            if(o.comparison_mode=="cpu-cuda") require(delta<=512ull*1024*1024 && free>=512ull*1024*1024,"frozen GPU allocation envelope/free floor exceeded");
            return json{{"device_free_before",s.device_free_before},{"device_free_now",free},{"device_total",total},{"observed_allocated_delta",delta},{"allocation_cap_bytes",512ull*1024*1024}};};
        const auto setup_memory=memory();
        std::cout<<json({{"type","factorial-setup"},{"schema","h5-layer7-reduction/1"},{"setup_ms",ms(setup)},{"memory",setup_memory},
            {"placements",{{"five",stats_json(llama_hot_get_stats(s.b.result.hot_experts.at(0)))},{"ten",stats_json(llama_hot_get_stats(s.b10.result.hot_experts.at(0)))}}},
            {"dimensions",{o.d,o.f,E,K}},{"threads",o.threads},{"seed",o.seed},{"pairs",o.pairs},{"warmup",o.warmup},
            {"tokens_list",{1,4}},{"comparison_mode",o.comparison_mode},{"small_test",o.small},{"representation","Q8_0"},
            {"resident_union",selected},{"selected_per_token",10},{"five_remote_resident_count",5},{"ten_remote_resident_count",26},
            {"ten_remote_payload_bytes",3*size_t(o.d)*o.f/32*34*26},{"performance_claim",false},
            {"scope","controlled single-layer fixture; not a whole-model or full-VRAM placement policy"},
            {"order","five Latin rotations, their reverses, repeated twice"},{"priming","one same-fixture untimed invocation immediately before every arm"}}).dump()<<std::endl;
        struct replay {fixture f;json row;};std::vector<replay> replays;
        for(int t:{1,4}) {
            if(t!=1) {auto rebuild=clock_type::now();s.rebuild(t);std::cout<<json({{"type","factorial-rebuild"},{"tokens",t},{"rebuild_ms",ms(rebuild)},{"memory",memory()}}).dump()<<std::endl;}
            std::cout<<json({{"type","factorial-memory"},{"tokens",t},{"memory",memory()}}).dump()<<std::endl;
            for(int n=0;n<o.warmup+o.pairs;++n) {
                const bool warm=n<o.warmup;const int pair=warm?n:n-o.warmup;
                auto f=make_fixture(o,routing,t,"mixed",false,pair);const auto order=block_order(pair);
                std::vector<int32_t> ids;std::vector<float> weights;json ids_json=json::array(),weight_bits=json::array(),labels=json::array();
                for(const auto & r:f.rows) {ids_json.push_back(r.ids);weight_bits.push_back(bits(r));labels.push_back(r.label);
                    for(int k=0;k<K;++k) {ids.push_back(r.ids[k]);weights.push_back(r.weights[k]);}}
                std::vector<uint8_t> packed(ids.size()*8);std::memcpy(packed.data(),ids.data(),ids.size()*4);std::memcpy(packed.data()+ids.size()*4,weights.data(),weights.size()*4);
                const auto ih=sha(f.input.data(),f.input.size()*4),rh=sha(packed.data(),packed.size());
                std::array<std::vector<float>,5> outputs;std::array<json,5> arm_stats;json order_names=json::array();
                std::vector<float> shared(o.d*t),planes(o.d*K*t);
                for(int pos=0;pos<5;++pos) {
                    const int index=order[pos];const bool ten=index>=3;const bool reduced=index==2 || index==4;
                    auto & x=index==0?s.a:ten?s.b10:s.b;s.choose(ten);setenv("IS_FACTORIAL_TRANSPORT","pipeline",1);setenv("IS_REDUCED_OUTPUT",reduced?"1":"0",1);
                    bind(s,x,f,t);outputs[index].resize(o.d*t);std::vector<float> prime(o.d*t);
                    const double priming_ms=s.execute(x,index!=0,prime); // exactly one excluded priming invocation
                    const double elapsed=s.execute(x,index!=0,outputs[index]);
                    auto stats=index==0?json::object():stats_json(llama_hot_get_stats(x.result.hot_experts.at(0)));
                    if(index!=0) {const auto & r=stats.at("rpc");require(r["graph_recompute"]==1 && r["set_commands"]==3 && r["set_acks"]==3 &&
                        r["graph_commands"]==1 && r["get_commands"]==1 && r["failed"]==0,"timed RPC admission/recompute/count invariant");}
                    stats["arm"]=index==0?"A":"B";stats["order"]=pos;stats["total_layer_ms"]=elapsed;stats["priming_ms"]=priming_ms;
                    stats["output_sha256"]=sha(outputs[index].data(),outputs[index].size()*4);stats["input_sha256"]=ih;stats["routing_sha256"]=rh;
                    if(index==0) {stats["hot"]=0;stats["cold"]=10;stats["commands"]=0;
                        ggml_backend_tensor_get(s.a.shared,shared.data(),0,shared.size()*4);ggml_backend_tensor_get(s.a.weighted,planes.data(),0,planes.size()*4);}
                    arm_stats[index]=stats;order_names.push_back(ARM_NAMES[index]);
                }
                json block={{"type","factorial-block"},{"tokens",t},{"case",t==1?"mixed":"mixed-varied-set"},{"pair",pair},{"warmup",warm},
                    {"order",order_names},{"input_sha256",ih},{"routing_sha256",rh},{"arms",json::object()}};
                for(int i=0;i<5;++i) block["arms"][ARM_NAMES[i]]=arm_stats[i];
                if(n==0) block["post_prime_memory"]=memory();
                std::cout<<block.dump()<<std::endl;
                bool nonzero=true;for(int slot=0;slot<K*t;++slot) nonzero &= std::any_of(planes.begin()+slot*o.d,planes.begin()+(slot+1)*o.d,[](float v){return v!=0 && std::isfinite(v);});
                bool sn=std::any_of(shared.begin(),shared.end(),[](float v){return v!=0 && std::isfinite(v);});
                for(int i=1;i<5;++i) {
                    auto metrics=diagnostic(outputs[0],outputs[i],planes,shared,o.d,o.comparison_mode=="cpu-cuda");
                    bool structural=metrics["finite"] && nonzero && sn && std::all_of(planes.begin(),planes.end(),[](float v){return std::isfinite(v);}) &&
                        std::all_of(shared.begin(),shared.end(),[](float v){return std::isfinite(v);});
                    const int hot=i>=3?10:5;
                    require(arm_stats[i]["hot"]==hot && arm_stats[i]["cold"]==10-hot && arm_stats[i]["tokens"]==t,"active placement count mismatch");
                    json row={{"type","factorial-pair"},{"factorial_arm",ARM_NAMES[i]},{"tokens",t},{"case",block["case"]},{"pair",pair},{"warmup",warm},
                        {"order",arm_stats[0]["order"]<arm_stats[i]["order"]?"AB":"BA"},{"ids",t==1?json(f.rows[0].ids):ids_json},
                        {"weight_bits",t==1?bits(f.rows[0]):weight_bits},{"routing_labels",labels},{"input_sha256",ih},{"routing_sha256",rh},
                        {"hot",hot},{"cold",10-hot},{"shared_nonzero",sn},{"experts_nonzero",nonzero},{"correctness",metrics},
                        {"structural_valid",structural},{"valid",structural && metrics["pass"].get<bool>()},
                        {"A",arm_stats[0]},{"B",arm_stats[i]},{"B_minus_A_ms",arm_stats[i]["total_layer_ms"].get<double>()-arm_stats[0]["total_layer_ms"].get<double>()},
                        {"performance_claim",false}};
                    std::cout<<row.dump()<<std::endl;require(structural,"nonfinite or insensitive full-layer structure");
                    // Grouped output is checked exactly offline; legacy verdict stays visible.
                    if(!warm) replays.push_back({f,row});
                }
            }
        }
        s.o.capture_stages=true;std::filesystem::create_directory(root+"/replays");int replay_width=0;
        for(const auto & saved:replays) {
            const auto & row=saved.row;const int t=row.at("tokens");const bool ten=row.at("hot")==10;
            const auto name=row.at("factorial_arm").get<std::string>();const bool reduced=name.rfind("reduced",0)==0;
            s.choose(ten);const auto dir=root+"/replays/t"+std::to_string(t)+"-"+row.at("case").get<std::string>()+"-p"+std::to_string(row.at("pair").get<int>())+"-"+name;
            require(std::filesystem::create_directory(dir),"fresh replay directory required");
            const auto bank_dir=root+"/banks/"+std::string(ten?"p10":"p5");
            for(const auto file:{"spec.json","weights.json","assigned.txt"}) std::filesystem::copy_file(bank_dir+"/"+file,dir+"/"+file);
            s.o.work=dir;if(replay_width!=t) {s.rebuild(t);replay_width=t;
                std::cout<<json({{"type","factorial-replay-memory"},{"tokens",t},{"memory",memory()}}).dump()<<std::endl;}
            s.choose(ten);setenv("IS_FACTORIAL_TRANSPORT","pipeline",1);setenv("IS_REDUCED_OUTPUT",reduced?"1":"0",1);
            auto & x=ten?s.b10:s.b;bind(s,s.a,saved.f,t);bind(s,x,saved.f,t);
            std::vector<float> a(o.d*t),b(o.d*t);s.execute(s.a,false,a);s.execute(x,true,b);
            const bool equal=sha(a.data(),a.size()*4)==row["A"]["output_sha256"].get<std::string>() && sha(b.data(),b.size()*4)==row["B"]["output_sha256"].get<std::string>();
            save_json(std::filesystem::path(dir)/"replay-binding.json",{{"schema","h5-layer7-replay-binding/1"},{"timed_record",row},{"outputs_equal",equal},
                {"timed_graph_retention",false},{"replay_after_all_timed_work",true}});
            require(equal,"replay differs from exact timed arm output; stop without tolerance changes");
            auto result=capture(s,x,row);require(result["consumed_identity_matches_pair"],"capture consumed identity");capture_stages(s,x,row,ten);
            std::cout<<json({{"type","factorial-replay"},{"tokens",t},{"case",row["case"]},{"pair",row["pair"]},{"factorial_arm",name},{"outputs_equal",equal}}).dump()<<std::endl;
        }
        rusage usage{};require(getrusage(RUSAGE_SELF,&usage)==0,"peak RSS read failed");
        std::cout<<json({{"type","factorial-summary"},{"peak_host_rss_bytes",uint64_t(usage.ru_maxrss)*1024},{"memory",memory()},{"diagnostic_complete",true},{"replays",replays.size()},{"numerical_qualification",false},{"performance_claim",false}}).dump()<<std::endl;
        return 0;
    } catch(const std::exception & e) {std::cerr<<"FACTORIAL_STOP "<<e.what()<<std::endl;return 2;}
}
