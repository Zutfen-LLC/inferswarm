// Matched routing-boundary microbenchmark; actual native CPU and H5 graphs.
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
    bool small=false, failure_dump=false, diagnostic_pair13=false, capture_stages=false; size_t dump_max_bytes=16*1024*1024; std::string endpoint,work,routing,control,comparison_mode="cpu-loopback";
    std::string tokens_list="1";
};
int number(const std::string & text,int low,int high) {
    require(!text.empty() && text.size()<11 && text.find_first_not_of("0123456789")==std::string::npos,"invalid bounded integer");
    auto v=std::stoll(text); require(v>=low && v<=high,"integer outside benchmark budget"); return int(v);
}
std::vector<int> parse_tokens(const std::string & text) {
    // Bounded ascending batch widths for the #346 break-even sweep.
    require(text.size()<=63,"token list too long");
    std::vector<int> widths; std::set<int> seen;
    size_t begin=0;
    while (begin<=text.size()) {
        const size_t end=text.find(',',begin);
        const std::string item=text.substr(begin,end==std::string::npos?text.size()-begin:end-begin);
        const int v=number(item,1,256);
        require(seen.insert(v).second,"duplicate token batch width");
        widths.push_back(v);
        if (end==std::string::npos) break;
        begin=end+1;
    }
    require(!widths.empty(),"empty token list");
    std::sort(widths.begin(),widths.end());
    return widths;
}
options parse(int argc,char ** argv) {
    options o;
    for (int i=1;i<argc;++i) {
        std::string a=argv[i];
        if (a=="--capture-stages") { o.capture_stages=true;continue; }
        if (a=="--failure-dump") { o.failure_dump=true;continue; }
        if (a=="--diagnostic-pair13") { o.diagnostic_pair13=true;continue; }
        if (a=="--small-test") { o.d=32;o.f=32;o.small=true;continue; }
        require(i+1<argc,"option needs value: "+a); const std::string v=argv[++i];
        if (a=="--endpoint") o.endpoint=v; else if (a=="--work-dir") o.work=v;
        else if (a=="--routing") o.routing=v; else if (a=="--threads") o.threads=number(v,1,128);
        else if (a=="--warmup") o.warmup=number(v,0,20); else if (a=="--pairs") o.pairs=number(v,1,100);
        else if (a=="--seed") o.seed=number(v,1,2147483647); else if (a=="--control") o.control=v;
        else if (a=="--dump-max-bytes") o.dump_max_bytes=number(v,1,16*1024*1024);
        else if (a=="--tokens") o.tokens_list=v;
        else if (a=="--comparison-mode") o.comparison_mode=v;
        else throw std::runtime_error("unknown option: "+a);
    }
    require(!o.endpoint.empty() && !o.work.empty(),"--endpoint and fresh --work-dir required");
    require(o.control.empty() || o.control=="fixture-probe" || (o.small && (o.control=="missing-shared" || o.control=="missing-expert" || o.control=="bad-partition" || o.control=="native-routing" || o.control=="comparator-probe" || o.control=="fixture-probe" || o.control=="stage-probe")),"negative controls require --small-test");
    require(o.comparison_mode=="cpu-loopback" || o.comparison_mode=="cpu-cuda","explicit comparison mode required: cpu-loopback|cpu-cuda");
    if (o.diagnostic_pair13) {
        require(o.seed==314159 && o.warmup==5 && o.pairs==20 && o.routing.empty() && o.control.empty(),"pair13 diagnostic requires frozen seed/warmup/pairs/synthetic routing");
        require(o.tokens_list=="1" || o.tokens_list=="1,2,4,8,16","pair13 diagnostic requires original width allocation");
        o.tokens_list="1,2,4,8,16";
    }
    require(!o.capture_stages || o.diagnostic_pair13 || (o.small && o.control=="stage-probe"),"stage capture requires frozen diagnostic or small stage-probe");
    if (o.control=="stage-probe") require(o.tokens_list=="2" && o.warmup==0 && o.pairs<=2,"stage-probe requires T=2, no warmup, one or two pairs");
    for (auto key:{"IS309_MOE","IS309_CAPTURE","IS314_HOT_SPEC","IS311_ASSIGNED"}) require(!std::getenv(key),std::string("refuse inherited ")+key);
    return o;
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
    std::map<int,llama_hot_routing_batch> routing_batch;
    ~arm() { ggml_gallocr_free(alloc); }
};
struct bench {
    options o; llama_layer layer; ggml_tensor * omitted_shared_down=nullptr; ggml_context * ctx=nullptr; ggml_backend_buffer_t buffer=nullptr;
    ggml_backend_t cpu=nullptr,rpc=nullptr; ggml_backend_sched_t sched=nullptr;
    std::shared_ptr<llama_hot_experts> owner; int phase=2; arm a,b;
    int max_tokens=1;
    std::vector<int> token_widths{1};
    bench(options opts):o(std::move(opts)) {}
    ~bench() {
        if (sched) { ggml_backend_sched_synchronize(sched);ggml_backend_sched_reset(sched); }
        b.result.reset();a.result.reset();owner.reset();
        ggml_gallocr_free(a.alloc);a.alloc=nullptr;
        ggml_backend_sched_free(sched);ggml_backend_buffer_free(buffer);ggml_free(ctx);
        ggml_backend_free(rpc);ggml_backend_free(cpu);
    }
    void setup() {
        require(std::filesystem::create_directory(o.work),"work directory must be fresh");
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
        for (auto * x:{&a,&b}) {
            x->routing.ids=ggml_new_tensor_2d(ctx,GGML_TYPE_I32,K,1);
            x->routing.weights=ggml_new_tensor_3d(ctx,GGML_TYPE_F32,1,K,1);
        }
        // #346: one routing-boundary leaf pair per swept width. The executor
        // and the bound graphs read the exact-width tensor, never a wider one.
        for (int t:token_widths) if (t>1) for (auto * x:{&a,&b}) {
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
        json spec={{"schema","is314-hot-experts/1"},{"layer",7},{"rpc_backend","RPC["+o.endpoint+"]"},{"expert_ids",HOT},{"tensors",json::array()}};
        std::ofstream assigned(o.work+"/assigned.txt");
        for (int i=0;i<3;++i) {
            auto * t=banks[i]; const size_t stride=t->nb[2]; std::vector<uint8_t> compact(stride*HOT.size());
            json ranges=json::array();
            for (size_t n=0;n<HOT.size();++n) {
                std::memcpy(compact.data()+n*stride,static_cast<uint8_t *>(t->data)+HOT[n]*stride,stride);
                ranges.push_back({{"expert_id",HOT[n]},{"source_offset",HOT[n]*stride},{"destination_offset",n*stride},{"length",stride}});
            }
            std::string name="is314.layer7.bench."+names[i],hash=sha(compact.data(),compact.size());
            spec["tensors"].push_back({{"source_name",t->name},{"compact_name",name},{"ggml_type",int(t->type)},
                {"source_shape",{t->ne[0],t->ne[1],E,1}},{"compact_shape",{t->ne[0],t->ne[1],HOT.size(),1}},
                {"source_sha256",weight_hashes.at(t->name)},{"compact_sha256",hash},{"expert_bytes",stride},{"ranges",ranges}});
            assigned<<name<<" 8 "<<t->ne[0]<<" "<<t->ne[1]<<" 5 1 "<<compact.size()<<" "<<hash<<"\n";
        }
        assigned.close();std::ofstream(o.work+"/spec.json")<<spec.dump(2)<<"\n";
        setenv("IS314_HOT_SPEC",(o.work+"/spec.json").c_str(),1);setenv("IS311_ASSIGNED",(o.work+"/assigned.txt").c_str(),1);
        rpc=ggml_backend_rpc_init(o.endpoint.c_str(),0);require(rpc,"RPC backend unavailable");
        ggml_backend_t backends[]={rpc,cpu};sched=ggml_backend_sched_new(backends,nullptr,2,8192,false,false);require(sched,"scheduler unavailable");
        build(a,false,1);build(b,true,1);
    }
    void build(arm & x,bool hot,int tokens) {
        llama_adapter_loras loras;llm_graph_params p={};
        p.arch=LLM_ARCH_QWEN4EXP;p.hparams.n_layer_all=9;p.hparams.n_embd=o.d;p.hparams.n_expert=E;p.hparams.n_expert_used_arr.fill(K);
        p.hparams.n_head_arr.fill(1);p.hparams.n_head_kv_arr.fill(1);p.hparams.n_embd_head_k_full=o.d;p.hparams.n_embd_head_v_full=o.d;p.hparams.n_rot_full=o.d;
        p.hparams.expert_weights_scale=1;p.cparams.n_threads=o.threads;p.cparams.n_threads_batch=o.threads;p.ubatch.n_tokens=tokens;
        p.sched=sched;p.backend_cpu=cpu;p.loras=&loras;p.res=&x.result;p.hot_owner=&owner;p.hot_phase=&phase;
        p.cb=[](const llama_ubatch &,ggml_tensor * t,const char * name,int il){ggml_format_name(t,"%s-%d",name,il);};
        llm_graph_context builder(p);
        x.input=ggml_new_tensor_2d(x.result.get_ctx(),GGML_TYPE_F32,o.d,tokens);ggml_set_input(x.input);
        // A complete valid H5 graph with zero B-only shared down projection:
        // numerical omission sensitivity, not merely constructor refusal.
        auto selected=layer;if (hot && omitted_shared_down) selected.ffn_down_shexp=omitted_shared_down;
        if (hot) {
            auto cfg=llama_hot_config(9);
            cfg.benchmark_stages=o.capture_stages && tokens==2;
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
            if (o.capture_stages && tokens==2) x.stages=llama_hot_retain_stages(x.weighted);
            if (o.control=="native-routing") {
                x.native_ids=ggml_cont(x.result.get_ctx(),x.weighted->src[0]->src[2]);ggml_set_output(x.native_ids);
                x.native_weights=x.weighted->src[1];ggml_set_output(x.native_weights);
            }
        }
        ggml_set_output(x.output);ggml_graph_clear(x.result.get_gf());ggml_build_forward_expand(x.result.get_gf(),x.output);
        if (x.native_ids) ggml_build_forward_expand(x.result.get_gf(),x.native_ids);
        if (hot) require(ggml_backend_sched_alloc_graph(sched,x.result.get_gf()),"H5 graph allocation failed");
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
        require(tokens>=1 && tokens<=max_tokens,"token width outside sweep");
        ggml_backend_sched_synchronize(sched);
        b.result.reset();a.result.reset();
        ggml_backend_sched_reset(sched);
        ggml_gallocr_free(a.alloc);a.alloc=nullptr;
        build(a,false,tokens);build(b,true,tokens);
    }
    double execute(arm & x,bool hot,std::vector<float> & out) {
        auto start=clock_type::now();
        auto status=hot?ggml_backend_sched_graph_compute(sched,x.result.get_gf()):ggml_backend_graph_compute(cpu,x.result.get_gf());
        if (hot) ggml_backend_sched_synchronize(sched);else ggml_backend_synchronize(cpu);
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
json comparator_probe(bool cross_backend) {
    std::vector<float> a={1},b={std::nextafter(1.0f,2.0f)},planes(K,0),shared={0.1f};planes[0]=1;
    json out;out["adjacent"]=diagnostic(a,b,planes,shared,1,cross_backend,true);
    b[0]=1.02f;out["excess"]=diagnostic(a,b,planes,shared,1,cross_backend,true);
    planes[0]=0;b[0]=std::nextafter(1.0f,2.0f);out["zero_planes"]=diagnostic(a,b,planes,shared,1,cross_backend,true);
    b[0]=INFINITY;out["nonfinite_output"]=diagnostic(a,b,planes,shared,1,cross_backend,true);b=a;
    planes[0]=NAN;out["nonfinite_plane"]=diagnostic(a,b,planes,shared,1,cross_backend,true);planes[0]=1;
    shared[0]=INFINITY;out["nonfinite_shared"]=diagnostic(a,b,planes,shared,1,cross_backend,true);
    // Asymmetric [d,K,T] planes: each coordinate must use its own token's
    // scale, including small coordinates beside large ones in either token.
    constexpr size_t d=3,tokens=2;
    const float scales[tokens][d]={{0.125f,128.0f,0.25f},{256.0f,0.5f,512.0f}};
    a.assign(d*tokens,1.0f);shared.assign(d*tokens,0.1f);planes.resize(d*K*tokens);
    for (size_t t=0;t<tokens;++t) for (int slot=0;slot<K;++slot)
        for (size_t c=0;c<d;++c) planes[(t*K+slot)*d+c]=scales[t][c];
    out["batch_coordinates"]=json::array();
    for (size_t e=0;e<a.size();++e) {
        double tol=(ASSOC+(cross_backend?QUANT_HEADROOM:0.0))*K*scales[e/d][e%d];
        b=a;b[e]+=float(tol/2);
        auto within=diagnostic(a,b,planes,shared,d,cross_backend,true);
        b=a;b[e]+=float(2*tol);
        out["batch_coordinates"].push_back({{"token",e/d},{"coordinate",e%d},
            {"within",within},{"excess",diagnostic(a,b,planes,shared,d,cross_backend,true)}});
    }
    b=a;b[0]+=0.25f;b[3]+=0.5f;
    out["different_maxima"]=diagnostic(a,b,planes,shared,d,cross_backend,true);
    return out;
}
// The reduction allocator can reuse slot staging once its final view dies.
// Restore a capture from the retained branch outputs, without reading that
// expired staging or changing the executor's graph/liveness/timed work.
std::vector<uint8_t> captured_weighted(const llama_hot_observation & observation) {
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
            const bool is_hot=std::find(HOT.begin(),HOT.end(),ids[t*K+slot])!=HOT.end();
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
json capture(bench & s,const json & row) {
    const uint32_t endian=1;
    require(*reinterpret_cast<const uint8_t *>(&endian)==1,"capture requires little endian host");
    auto observation=llama_hot_get_observation(s.b.result.hot_experts.at(0));
    const int tokens=row.at("tokens");
    auto * ai=tokens>1?s.a.routing_batch.at(tokens).ids:s.a.routing.ids;
    auto * aw=tokens>1?s.a.routing_batch.at(tokens).weights:s.a.routing.weights;
    if (s.a.native_ids) { ai=s.a.native_ids; aw=s.a.native_weights; }
    const std::vector<std::pair<std::string,ggml_tensor *>> tensors={
        {"A.input",s.a.input},{"B.input",observation.input},
        {"A.ids",ai},{"A.weights",aw},{"B.ids",observation.ids},{"B.weights",observation.weights},
        {"A.output",s.a.output},{"B.output",s.b.output},
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
    std::map<std::string,std::vector<uint8_t>> bytes;
    for (const auto & entry:tensors) if (auto * t=entry.second) {
        auto & data=bytes[entry.first];data.resize(ggml_nbytes(t));
        if (entry.first=="B.weighted") data=captured_weighted(observation);
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
            auto dense=std::find(HOT.begin(),HOT.end(),id);bool hot=dense!=HOT.end();
            manifest["slot_map"].push_back({{"token",token},{"original_slot",slot},{"global_expert",id},
                {"branch",hot?"hot":"cold"},{"branch_slot",hot?hot_slot++:cold_slot++},
                {"compact_expert",hot?json(dense-HOT.begin()):json(nullptr)}});
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
// Separate stage budget includes exact selected Q8_0 banks (~26 MiB at the
// frozen geometry). Default capture keeps its existing 16 MiB payload limit.
json capture_stages(bench & s,const json & row) {
    constexpr size_t limit=32*1024*1024;
    const auto directory=std::filesystem::path(s.o.work)/"stages";
    const auto b=llama_hot_get_stages(s.b.result.hot_experts.at(0));
    require(s.a.stages[0] && b[0] && row.at("tokens")==2,"executed stages unavailable");
    require(std::filesystem::create_directory(directory),"stage directory must be fresh");
    const std::array<std::string,5> names={"gate","up","swiglu","down","weighted"};
    json manifest={{"schema","h5-layer7-stages/1"},{"byte_order","little"},{"threads",s.o.threads},
        {"pair_record",row},{"payload_limit_bytes",limit},{"files",json::object()},
        {"execution","existing executed graphs with OUTPUT retention; no recomputation"},
        {"perturbation","T=2 A stages and B five-hot stages retained; allocator reuse and eligible fusion may change"},
        {"performance_claim",false},{"compact_expert_order",HOT}};
    size_t total=0;
    auto save=[&](const std::string & name,const std::vector<uint8_t> & bytes,json metadata) {
        require(bytes.size()<=limit-total,"stage payload budget exceeded");total+=bytes.size();
        std::ofstream file(directory/name,std::ios::binary);file.exceptions(std::ios::badbit|std::ios::failbit);
        file.write(reinterpret_cast<const char *>(bytes.data()),bytes.size());file.close();
        metadata["byte_length"]=bytes.size();metadata["sha256"]=sha(bytes.data(),bytes.size());manifest["files"][name]=metadata;
    };
    auto metadata=[](ggml_tensor * t) { return json{{"tensor_name",t->name},{"ggml_type",int(t->type)},
        {"type_name",ggml_type_name(t->type)},{"shape",{t->ne[0],t->ne[1],t->ne[2],t->ne[3]}},
        {"strides_bytes",{t->nb[0],t->nb[1],t->nb[2],t->nb[3]}},{"op",ggml_op_name(t->op)},{"flags",t->flags}}; };
    for (int arm=0;arm<2;++arm) {
        const auto & stages=arm?b:s.a.stages;
        for (size_t i=0;i<stages.size();++i) {
            auto * t=stages[i];
            require(t && t->type==GGML_TYPE_F32 && ggml_is_contiguous(t) &&
                t->ne[0]==(i<3?s.o.f:s.o.d) && t->ne[1]==(arm?5:10) && t->ne[2]==2 &&
                t->ne[3]==1 && (t->flags&GGML_TENSOR_FLAG_OUTPUT),"retained stage shape/lifetime mismatch");
            std::vector<uint8_t> bytes(ggml_nbytes(t));ggml_backend_tensor_get(t,bytes.data(),0,bytes.size());
            save(std::string(arm?"B.":"A.")+names[i]+".bin",bytes,metadata(t));
        }
    }
    std::ifstream spec_file(s.o.work+"/spec.json");json spec;spec_file>>spec;
    const std::array<ggml_tensor *,3> source={s.layer.ffn_gate_exps,s.layer.ffn_up_exps,s.layer.ffn_down_exps};
    const std::array<ggml_tensor *,3> actual={b[0]->src[0],b[1]->src[0],b[3]->src[0]};
    for (size_t bank=0;bank<3;++bank) {
        auto * a=source[bank];auto * remote=actual[bank];
        require(a->type==GGML_TYPE_Q8_0 && remote->type==a->type && ggml_is_contiguous(a) &&
            ggml_is_contiguous(remote) && remote->ne[0]==a->ne[0] && remote->ne[1]==a->ne[1] &&
            remote->ne[2]==5 && remote->ne[3]==1 && remote->nb[2]==a->nb[2],"stage bank layout mismatch");
        std::vector<uint8_t> selected(a->nb[2]*HOT.size()),observed(ggml_nbytes(remote));
        for (size_t i=0;i<HOT.size();++i) ggml_backend_tensor_get(a,selected.data()+i*a->nb[2],HOT[i]*a->nb[2],a->nb[2]);
        ggml_backend_tensor_get(remote,observed.data(),0,observed.size());
        require(selected==observed,"stage CPU/CUDA encoded weight mismatch");
        auto meta=metadata(remote);meta["source_tensor"]=a->name;
        meta["source_shape"]={a->ne[0],a->ne[1],a->ne[2],a->ne[3]};
        meta["B_actual_sha256"]=sha(observed.data(),observed.size());
        meta["block_elements"]=32;meta["block_bytes"]=34;
        meta["provenance"]="A encoded whole expert slices; byte-equal B actual compact bank readback";
        bool matched=false;
        for (const auto & tensor:spec.at("tensors")) if (tensor.at("source_name")==std::string(a->name)) {
            require(tensor.at("compact_sha256").get<std::string>()==meta["B_actual_sha256"].get<std::string>(),"stage spec bank identity mismatch");
            meta["source_sha256"]=tensor.at("source_sha256");matched=true;
        }
        require(matched,"stage source bank identity missing");
        save(names[bank==2?3:bank]+".q8_0.bin",selected,meta);
    }
    std::ifstream captured_file(s.o.work+"/capture/manifest.json");json captured;captured_file>>captured;
    std::ifstream raw_capture(s.o.work+"/capture/manifest.json");const std::string capture_bytes((std::istreambuf_iterator<char>(raw_capture)),{});
    manifest["capture_manifest_sha256"]=sha(capture_bytes.data(),capture_bytes.size());
    manifest["slot_map"]=captured.at("slot_map");manifest["input_sha256"]=row.at("input_sha256");
    manifest["routing_sha256"]=row.at("routing_sha256");manifest["payload_bytes"]=total;
    manifest["reference_scope"]="dequantized mathematical matmuls are not backend activation quantization/rounding";
    const auto text=manifest.dump(2)+"\n";require(text.size()<=65536,"stage metadata budget exceeded");
    std::ofstream file(directory/"manifest.json");file.exceptions(std::ios::badbit|std::ios::failbit);file<<text;file.close();
    return {{"status","complete"},{"manifest","stages/manifest.json"},{"payload_bytes",total}};
}
// #346 per-token/throughput derived distributions: plain per-sample transforms
// of the SAME retained pair times, never separately re-measured quantities.
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
std::vector<double> divided(const std::vector<double> & v,int tokens) {
    std::vector<double> out;out.reserve(v.size());
    for (auto x:v) out.push_back(x/tokens);
    return out;
}
std::vector<double> rate(const std::vector<double> & v,int tokens) {
    std::vector<double> out;out.reserve(v.size());
    for (auto x:v) out.push_back(tokens/(x/1000.0));
    return out;
}
std::vector<double> ratio(const std::vector<double> & a,const std::vector<double> & b) {
    require(a.size()==b.size(),"paired ratio shape mismatch");
    std::vector<double> out;out.reserve(a.size());
    for (size_t i=0;i<a.size();++i) out.push_back(a[i]/b[i]);
    return out;
}
}
int main(int argc,char ** argv) {
    try {
        const auto o=parse(argc,argv);const auto contract=comparison_contract(o.comparison_mode);
        if (o.control=="comparator-probe") { std::cout<<comparator_probe(o.comparison_mode=="cpu-cuda").dump()<<std::endl;return 0; }
        const auto widths=parse_tokens(o.tokens_list);
        auto routing=routes(o);
        if (o.control=="fixture-probe") {
            auto f=make_fixture(o,routing,2,"mixed",false,13);
            json rows=json::array();std::vector<uint8_t> packed(2*K*8);
            for (int t=0;t<2;++t) {
                rows.push_back({{"ids",f.rows[t].ids},{"weight_bits",bits(f.rows[t])}});
                std::memcpy(packed.data()+t*K*4,f.rows[t].ids.data(),K*4);
                std::memcpy(packed.data()+2*K*4+t*K*4,f.rows[t].weights.data(),K*4);
            }
            std::cout<<json({{"case","mixed-varied-set"},{"tokens",2},{"pair",13},{"warmup",false},
                {"input_sha256",sha(f.input.data(),f.input.size()*4)},{"routing_sha256",sha(packed.data(),packed.size())},{"rows",rows}}).dump()<<std::endl;
            return 0;
        }
        bench s(o);s.token_widths=widths;s.max_tokens=widths.back();auto setup=clock_type::now();s.setup();
        std::ifstream spec_file(o.work+"/spec.json");const std::string spec_bytes((std::istreambuf_iterator<char>(spec_file)),{});
        std::ifstream weights_file(o.work+"/weights.json");const std::string weights_bytes((std::istreambuf_iterator<char>(weights_file)),{});
        std::cout<<json({{"type","setup"},{"schema","h5-layer7-matched/1"},{"setup_ms",ms(setup)},
            {"dimensions",{o.d,o.f,E,K}},{"small_test",o.small},{"seed",o.seed},{"threads",o.threads},
            {"tokens_list",widths},
            {"representation","Q8_0"},{"routing_boundary_cut",o.control!="native-routing"},{"routing_scope","provided routing boundary; synthetic activations, not activation replay"},
            {"comparator",contract},{"comparison_mode",o.comparison_mode},{"weights_sha256",sha(weights_bytes.data(),weights_bytes.size())},{"weight_spec_sha256",sha(spec_bytes.data(),spec_bytes.size())}}).dump()<<std::endl;
        if (o.diagnostic_pair13) std::cout<<json({{"type","diagnostic_selector"},{"id","pr346-t2-pair13-prefix/1"},
            {"performance_claim",false},{"priming_pairs",68},{"target_case","mixed-varied-set"},{"target_tokens",2},{"target_pair",13}}).dump()<<std::endl;
        // The complete spec and assigned encoded-weight identities are retained in work-dir.
        json summaries=json::object();int measured=0,primed=0;
        for (int tokens:widths) {
            if (tokens!=1) { const auto rebuild_start=clock_type::now();s.rebuild(tokens);
                std::cout<<json({{"type","rebuild"},{"tokens",tokens},{"rebuild_ms",ms(rebuild_start)}}).dump()<<std::endl; }
            for (const std::string name:{"mixed","all-cold"}) {
                // Batched widths run two labeled variants: distinct per-token
                // expert sets (general workload behavior) and the same set for
                // every token (ideal expert reuse). The single-token
                // compatibility case runs once with the historical name.
                const int variants=tokens>1?2:1;
                for (int variant=0;variant<variants;++variant) {
                    const bool shared_set=variant==1;
                    const std::string case_name=name+(tokens>1?(shared_set?"-shared-set":"-varied-set"):"");
                    std::vector<double> ta,tb,delta;
                    for (int n=0;n<o.warmup+o.pairs;++n) {
                        bool warm=n<o.warmup;int pair=warm?n:n-o.warmup;
                        auto fixture=make_fixture(o,routing,tokens,name,shared_set,pair);
                        auto & rows=fixture.rows; auto & input=fixture.input;
                        unsigned hot=0;
                        for (auto & r:rows) for (auto id:r.ids) hot+=std::find(HOT.begin(),HOT.end(),id)!=HOT.end();
                        require(hot==size_t(name=="mixed"?5:0)*size_t(tokens),"invalid five-hot/ten-slot partition");
                        std::vector<float> a(o.d*tokens),b(o.d*tokens),shared(o.d*tokens),weighted(o.d*K*tokens);
                        if (o.control=="native-routing") input[0]=(name=="mixed"?1.0f:-1.0f)*(0.4f+pair/32.0f);
                        std::vector<int32_t> ids_flat;std::vector<float> weights_flat;
                        for (auto & r:rows) for (int i=0;i<K;++i) { ids_flat.push_back(r.ids[i]);weights_flat.push_back(r.weights[i]); }
                        for (auto * x:{&s.a,&s.b}) {
                            ggml_backend_tensor_set(x->input,input.data(),0,input.size()*4);
                            if (tokens>1) {
                                auto & rb=x->routing_batch.at(tokens);
                                ggml_backend_tensor_set(rb.ids,ids_flat.data(),0,K*tokens*4);
                                ggml_backend_tensor_set(rb.weights,weights_flat.data(),0,K*tokens*4);
                            } else {
                                ggml_backend_tensor_set(x->routing.ids,rows[0].ids.data(),0,K*4);
                                ggml_backend_tensor_set(x->routing.weights,rows[0].weights.data(),0,K*4);
                            }
                        }
                        if (o.control=="missing-expert") {
                            auto w=weights_flat;for (int t=0;t<tokens;++t) w[t*K]=0;
                            auto target=tokens>1?s.b.routing_batch.at(tokens).weights:s.b.routing.weights;
                            ggml_backend_tensor_set(target,w.data(),0,w.size()*4);
                        }
                        bool ab=pair%2==0;double am,bm;
                        if (ab) { am=s.execute(s.a,false,a);bm=s.execute(s.b,true,b); }
                        else { bm=s.execute(s.b,true,b);am=s.execute(s.a,false,a); }
                        if (o.control=="native-routing") {
                            // Regression readback after compute: the native router's own
                            // top-k must produce a valid partition; relabel on success.
                            ggml_backend_tensor_get(s.a.native_ids,ids_flat.data(),0,K*tokens*4);
                            ggml_backend_tensor_get(s.a.native_weights,weights_flat.data(),0,K*tokens*4);
                            for (int t=0;t<tokens;++t) {
                                for (int i=0;i<K;++i) {
                                    rows[t].ids[i]=ids_flat[t*K+i];rows[t].weights[i]=weights_flat[t*K+i];
                                }
                                rows[t].label="native-router-regression";validate(rows[t]);
                            }
                        }
                        auto stats=llama_hot_get_stats(s.b.result.hot_experts.at(0));
                        ggml_backend_tensor_get(s.a.shared,shared.data(),0,shared.size()*4);
                        ggml_backend_tensor_get(s.a.weighted,weighted.data(),0,weighted.size()*4);
                        bool shared_nonzero=std::any_of(shared.begin(),shared.end(),[](float x){return std::isfinite(x) && x!=0;});
                        bool experts_nonzero=true;for (size_t i=0;i<size_t(K)*tokens;++i) experts_nonzero &= std::any_of(weighted.begin()+i*o.d,weighted.begin()+(i+1)*o.d,[](float x){return std::isfinite(x) && x!=0;});
                        auto metrics=diagnostic(a,b,weighted,shared,o.d,o.comparison_mode=="cpu-cuda",o.failure_dump || o.diagnostic_pair13);
                        bool valid=metrics["pass"] && shared_nonzero && experts_nonzero && stats.hot==(name=="mixed"?5:0) && stats.cold==K-(name=="mixed"?5:0) && stats.tokens==unsigned(tokens);
                        std::vector<uint8_t> route_bytes(K*tokens*8);
                        std::memcpy(route_bytes.data(),ids_flat.data(),K*tokens*4);
                        std::memcpy(route_bytes.data()+K*tokens*4,weights_flat.data(),K*tokens*4);
                        const auto input_hash=sha(input.data(),input.size()*4),route_hash=sha(route_bytes.data(),route_bytes.size());
                        json ids_json=json::array();json weight_bits=json::array();json labels=json::array();
                        for (auto & r:rows) { ids_json.push_back(r.ids);weight_bits.push_back(bits(r));labels.push_back(r.label); }
                        // tokens==1 keeps the historical flat fields for compatibility.
                        json row={{"type","pair"},{"case",case_name},{"tokens",tokens},{"pair",pair},{"warmup",warm},{"order",ab?"AB":"BA"},
                            {"routing_labels",labels},{"input_sha256",input_hash},{"routing_sha256",route_hash},
                            {"ids",ids_json},{"weight_bits",weight_bits},{"hot",stats.hot},{"cold",stats.cold},{"shared_nonzero",shared_nonzero},{"experts_nonzero",experts_nonzero},
                            {"correctness",metrics},{"valid",valid},{"A",{{"arm","A"},{"order",ab?0:1},{"total_layer_ms",am},{"output_sha256",sha(a.data(),a.size()*4)}}},
                            {"B",{{"arm","B"},{"order",ab?1:0},{"total_layer_ms",bm},{"output_sha256",sha(b.data(),b.size()*4)},
                                {"h5_layer_ms",stats.layer_ms},{"dispatch_ms",stats.dispatch_ms},{"cold_ms",stats.cold_ms},{"shared_ms",stats.shared_ms},{"join_ms",stats.join_ms},{"fast_ms",stats.fast_ms},
                                {"input_bytes",stats.input_bytes},{"routing_bytes",stats.routing_bytes},{"result_bytes",stats.result_bytes},{"wire_bytes",nullptr},{"owner",stats.compact_owner},{"step",stats.steps},
                                {"graph_dispatches",stats.graph_dispatches},{"graph_recompute_reuse",stats.graph_recompute_reuse},{"tokens",stats.tokens}}},
                            {"B_minus_A_ms",bm-am}};
                        if (tokens==1) {
                            row["routing_label"]=rows[0].label;
                            row["ids"]=rows[0].ids;
                            row["weight_bits"]=bits(rows[0]);
                        }
                        for (const std::string arm_name:{"A","B"}) {
                            row[arm_name]["input_sha256"]=input_hash;row[arm_name]["routing_sha256"]=route_hash;
                            row[arm_name]["hot"]=arm_name=="A"?0:stats.hot;row[arm_name]["cold"]=arm_name=="A"?K:stats.cold;
                        }
                        const bool target=tokens==2 && name=="mixed" && variant==0 && !warm &&
                            ((o.diagnostic_pair13 && pair==13) || (o.control=="stage-probe" && pair==o.pairs-1));
                        if (o.diagnostic_pair13 || o.control=="stage-probe") { row["type"]=target?"pair":"diagnostic-prime";row["performance_claim"]=false; }
                        bool capture_ok=true;
                        if (target || (o.failure_dump && !valid)) {
                            try {
                                row["capture"]=capture(s,row);capture_ok=row["capture"]["consumed_identity_matches_pair"];
                            }
                            catch (const std::exception & error) { capture_ok=false;row["capture"]={{"status","failed"},{"error",error.what()}}; }
                            if (capture_ok && o.capture_stages && tokens==2) {
                                try { row["stages"]=capture_stages(s,row); }
                                catch (const std::exception & error) { capture_ok=false;row["stages"]={{"status","failed"},{"error",error.what()}}; }
                            }
                        }
                        std::cout<<row.dump()<<std::endl;
                        require(valid,"invalid comparison: numerical/partition/shared/expert check failed");
                        require(capture_ok,"diagnostic capture failed or consumed identity mismatch");
                        if (target) {
                            require(o.control=="stage-probe" || primed==68,"diagnostic prefix count mismatch");
                            std::cout<<json({{"type","summary"},{"valid",true},{"timing_comparison_valid",false},
                                {"diagnostic_complete",true},{"performance_claim",false},{"priming_pairs",primed},
                                {"target_pairs",1},{"measured_pairs",0},{"cases",nullptr}}).dump()<<std::endl;
                            return 0;
                        }
                        if (o.diagnostic_pair13 || o.control=="stage-probe") { ++primed;continue; }
                        if (!warm) {ta.push_back(am);tb.push_back(bm);delta.push_back(bm-am);++measured;}
                    }
                    if (!o.diagnostic_pair13 && o.control!="stage-probe") summaries[case_name+"@t"+std::to_string(tokens)]={{"tokens",tokens},{"expert_set",tokens>1?(shared_set?"shared":"varied"):"single"},
                        {"A_ms",distribution(ta)},{"B_ms",distribution(tb)},{"B_minus_A_ms",distribution(delta)},
                        {"A_ms_per_token",distribution(divided(ta,tokens))},{"B_ms_per_token",distribution(divided(tb,tokens))},
                        {"A_tokens_per_s",distribution(rate(ta,tokens))},{"B_tokens_per_s",distribution(rate(tb,tokens))},
                        {"speedup_B_over_A",distribution(ratio(ta,tb))}};
                }
            }
        }
        std::cout<<json({{"type","summary"},{"valid",true},{"timing_comparison_valid",true},{"measured_pairs",measured},{"cases",summaries}}).dump()<<std::endl;
        return 0;
    } catch (const std::exception & e) {
        std::cout<<json({{"type","summary"},{"valid",false},{"timing_comparison_valid",false},{"error",e.what()},{"cases",nullptr}}).dump()<<std::endl;
        std::cerr<<"layer7 benchmark refused: "<<e.what()<<std::endl;return 2;
    }
}
