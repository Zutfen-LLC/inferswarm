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
    bool small=false; std::string endpoint,work,routing,control,comparison_mode="cpu-loopback";
};
int number(const std::string & text,int low,int high) {
    require(!text.empty() && text.size()<11 && text.find_first_not_of("0123456789")==std::string::npos,"invalid bounded integer");
    auto v=std::stoll(text); require(v>=low && v<=high,"integer outside benchmark budget"); return int(v);
}
options parse(int argc,char ** argv) {
    options o;
    for (int i=1;i<argc;++i) {
        std::string a=argv[i];
        if (a=="--small-test") { o.d=32;o.f=32;o.small=true;continue; }
        require(i+1<argc,"option needs value: "+a); const std::string v=argv[++i];
        if (a=="--endpoint") o.endpoint=v; else if (a=="--work-dir") o.work=v;
        else if (a=="--routing") o.routing=v; else if (a=="--threads") o.threads=number(v,1,128);
        else if (a=="--warmup") o.warmup=number(v,0,20); else if (a=="--pairs") o.pairs=number(v,1,100);
        else if (a=="--seed") o.seed=number(v,1,2147483647); else if (a=="--control") o.control=v;
        else if (a=="--comparison-mode") o.comparison_mode=v;
        else throw std::runtime_error("unknown option: "+a);
    }
    require(!o.endpoint.empty() && !o.work.empty(),"--endpoint and fresh --work-dir required");
    require(o.control.empty() || (o.small && (o.control=="missing-shared" || o.control=="missing-expert" || o.control=="bad-partition" || o.control=="native-routing" || o.control=="comparator-probe")),"negative controls require --small-test");
    require(o.comparison_mode=="cpu-loopback" || o.comparison_mode=="cpu-cuda","explicit comparison mode required: cpu-loopback|cpu-cuda");
    for (auto key:{"IS309_MOE","IS309_CAPTURE","IS314_HOT_SPEC","IS311_ASSIGNED"}) require(!std::getenv(key),std::string("refuse inherited ")+key);
    return o;
}
struct route {
    std::array<int32_t,K> ids; std::array<float,K> weights; std::string label;
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
    ~arm() { ggml_gallocr_free(alloc); }
};
struct bench {
    options o; llama_layer layer; ggml_tensor * omitted_shared_down=nullptr; ggml_context * ctx=nullptr; ggml_backend_buffer_t buffer=nullptr;
    ggml_backend_t cpu=nullptr,rpc=nullptr; ggml_backend_sched_t sched=nullptr;
    std::shared_ptr<llama_hot_experts> owner; int phase=2; arm a,b;
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
        build(a,false);build(b,true);
    }
    void build(arm & x,bool hot) {
        llama_adapter_loras loras;llm_graph_params p={};
        p.arch=LLM_ARCH_QWEN4EXP;p.hparams.n_layer_all=9;p.hparams.n_embd=o.d;p.hparams.n_expert=E;p.hparams.n_expert_used_arr.fill(K);
        p.hparams.n_head_arr.fill(1);p.hparams.n_head_kv_arr.fill(1);p.hparams.n_embd_head_k_full=o.d;p.hparams.n_embd_head_v_full=o.d;p.hparams.n_rot_full=o.d;
        p.hparams.expert_weights_scale=1;p.cparams.n_threads=o.threads;p.cparams.n_threads_batch=o.threads;p.ubatch.n_tokens=1;
        p.sched=sched;p.backend_cpu=cpu;p.loras=&loras;p.res=&x.result;p.hot_owner=&owner;p.hot_phase=&phase;
        p.cb=[](const llama_ubatch &,ggml_tensor * t,const char * name,int il){ggml_format_name(t,"%s-%d",name,il);};
        llm_graph_context builder(p);
        x.input=ggml_new_tensor_2d(x.result.get_ctx(),GGML_TYPE_F32,o.d,1);ggml_set_input(x.input);
        // A complete valid H5 graph with zero B-only shared down projection:
        // numerical omission sensitivity, not merely constructor refusal.
        auto selected=layer;if (hot && omitted_shared_down) selected.ffn_down_shexp=omitted_shared_down;
        if (hot) {
            auto cfg=llama_hot_config(9);
            if (o.control!="native-routing") cfg.benchmark_routing=&x.routing;
            x.output=builder.build_qwen4exp_ffn(x.input,selected,7,cfg);
        } else {
            x.output=builder.build_qwen4exp_ffn_native(x.input,selected,7);
            if (o.control!="native-routing") llama_hot_bind_routing(x.result.get_ctx(),x.output,7,x.routing);
            x.shared=x.output->src[1];ggml_set_output(x.shared);
            x.weighted=ggml_get_tensor(x.result.get_ctx(),"ffn_moe_weighted-7");ggml_set_output(x.weighted);
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
        const std::vector<float> & planes,const std::vector<float> & shared,bool cross_backend) {
    require(!a.empty() && a.size()==b.size() && planes.size()==K*a.size() && shared.size()==a.size(),"comparison shape mismatch");
    bool finite=true,equal=true,pass=true;double max_abs=0,max_ratio=0,squared=0,ref=0;
    for (size_t e=0;e<a.size();++e) {
        double l1=0;
        for (int i=0;i<K;++i) { double p=planes[e+i*a.size()];finite &= std::isfinite(p);l1+=std::fabs(p); }
        double tol=ASSOC*l1+(cross_backend?QUANT_HEADROOM:0.0)*l1;
        if (tol<=0.0) tol=ASSOC;
        finite &= std::isfinite(a[e]) && std::isfinite(b[e]) && std::isfinite(shared[e]);equal &= a[e]==b[e];
        double d=double(a[e])-b[e];max_abs=std::max(max_abs,std::abs(d));squared+=d*d;ref+=double(a[e])*a[e];
        max_ratio=std::max(max_ratio,std::abs(d)/tol);if (std::abs(d)>tol) pass=false;
    }
    return {{"pass",finite && pass},{"finite",finite},{"exact_equal",finite && equal},
        {"max_abs",finite?json(max_abs):json(nullptr)},{"max_ratio",finite?json(max_ratio):json(nullptr)},
        {"rms",finite?json(std::sqrt(squared/a.size())):json(nullptr)}, {"relative_l2",finite?json(std::sqrt(squared/std::max(ref,1e-300))):json(nullptr)}};
}
json comparator_probe(bool cross_backend) {
    std::vector<float> a={1},b={std::nextafter(1.0f,2.0f)},planes(K,0),shared={0.1f};planes[0]=1;
    json out;out["adjacent"]=diagnostic(a,b,planes,shared,cross_backend);
    b[0]=1.02f;out["excess"]=diagnostic(a,b,planes,shared,cross_backend);
    planes[0]=0;b[0]=std::nextafter(1.0f,2.0f);out["zero_planes"]=diagnostic(a,b,planes,shared,cross_backend);
    b[0]=INFINITY;out["nonfinite_output"]=diagnostic(a,b,planes,shared,cross_backend);b=a;
    planes[0]=NAN;out["nonfinite_plane"]=diagnostic(a,b,planes,shared,cross_backend);planes[0]=1;
    shared[0]=INFINITY;out["nonfinite_shared"]=diagnostic(a,b,planes,shared,cross_backend);return out;
}
}
int main(int argc,char ** argv) {
    try {
        const auto o=parse(argc,argv);const auto contract=comparison_contract(o.comparison_mode);
        if (o.control=="comparator-probe") { std::cout<<comparator_probe(o.comparison_mode=="cpu-cuda").dump()<<std::endl;return 0; }
        auto routing=routes(o);bench s(o);auto setup=clock_type::now();s.setup();
        std::ifstream spec_file(o.work+"/spec.json");const std::string spec_bytes((std::istreambuf_iterator<char>(spec_file)),{});
        std::ifstream weights_file(o.work+"/weights.json");const std::string weights_bytes((std::istreambuf_iterator<char>(weights_file)),{});
        std::cout<<json({{"type","setup"},{"schema","h5-layer7-matched/1"},{"setup_ms",ms(setup)},
            {"dimensions",{o.d,o.f,E,K}},{"small_test",o.small},{"seed",o.seed},{"threads",o.threads},
            {"representation","Q8_0"},{"routing_boundary_cut",o.control!="native-routing"},{"routing_scope","provided routing boundary; synthetic activations, not activation replay"},
            {"comparator",contract},{"comparison_mode",o.comparison_mode},{"weights_sha256",sha(weights_bytes.data(),weights_bytes.size())},{"weight_spec_sha256",sha(spec_bytes.data(),spec_bytes.size())}}).dump()<<std::endl;
        // The complete spec and assigned encoded-weight identities are retained in work-dir.
        json summaries=json::object();int measured=0;
        for (const std::string name:{"mixed","all-cold"}) {
            std::vector<double> ta,tb,delta;
            for (int n=0;n<o.warmup+o.pairs;++n) {
                bool warm=n<o.warmup;int pair=warm?n:n-o.warmup;
                auto r=routing[(size_t(pair)*routing.size()/o.pairs)%routing.size()];
                if (o.routing.empty()) {
                    std::rotate(r.ids.begin(),r.ids.begin()+pair%K,r.ids.end());
                    std::rotate(r.weights.begin(),r.weights.begin()+pair%K,r.weights.end());
                }
                if (name=="all-cold") for (auto & id:r.ids) if (std::find(HOT.begin(),HOT.end(),id)!=HOT.end()) {
                    int replacement=0;while (std::find(HOT.begin(),HOT.end(),replacement)!=HOT.end() || std::find(r.ids.begin(),r.ids.end(),replacement)!=r.ids.end()) ++replacement;id=replacement;
                }
                if (o.control=="bad-partition") r.ids[1]=r.ids[0];validate(r);
                unsigned hot=0;for (auto id:r.ids) hot+=std::find(HOT.begin(),HOT.end(),id)!=HOT.end();
                require(hot==(name=="mixed"?5:0),"invalid five-hot/ten-slot partition");
                uint32_t state=o.seed+uint32_t(pair+1)*7919;std::vector<float> input(o.d),a(o.d),b(o.d),shared(o.d),weighted(o.d*K);
                for (auto & v:input) v=sample(state)*0.8f+0.1f;
                if (o.control=="native-routing") input[0]=(name=="mixed"?1.0f:-1.0f)*(0.4f+pair/32.0f);
                for (auto * x:{&s.a,&s.b}) {
                    ggml_backend_tensor_set(x->input,input.data(),0,input.size()*4);
                    ggml_backend_tensor_set(x->routing.ids,r.ids.data(),0,K*4);
                    ggml_backend_tensor_set(x->routing.weights,r.weights.data(),0,K*4);
                }
                if (o.control=="missing-expert") { auto w=r.weights;w[0]=0;ggml_backend_tensor_set(s.b.routing.weights,w.data(),0,K*4); }
                bool ab=pair%2==0;double am,bm;
                if (ab) { am=s.execute(s.a,false,a);bm=s.execute(s.b,true,b); }
                else { bm=s.execute(s.b,true,b);am=s.execute(s.a,false,a); }
                if (o.control=="native-routing") {
                    ggml_backend_tensor_get(s.a.native_ids,r.ids.data(),0,K*4);
                    ggml_backend_tensor_get(s.a.native_weights,r.weights.data(),0,K*4);
                    r.label="native-router-regression";validate(r);
                }
                auto stats=llama_hot_get_stats(s.b.result.hot_experts.at(0));
                ggml_backend_tensor_get(s.a.shared,shared.data(),0,shared.size()*4);
                ggml_backend_tensor_get(s.a.weighted,weighted.data(),0,weighted.size()*4);
                bool shared_nonzero=std::any_of(shared.begin(),shared.end(),[](float x){return std::isfinite(x) && x!=0;});
                bool experts_nonzero=true;for (int i=0;i<K;++i) experts_nonzero &= std::any_of(weighted.begin()+i*o.d,weighted.begin()+(i+1)*o.d,[](float x){return std::isfinite(x) && x!=0;});
                auto metrics=diagnostic(a,b,weighted,shared,o.comparison_mode=="cpu-cuda");bool valid=metrics["pass"] && shared_nonzero && experts_nonzero && stats.hot==hot && stats.cold==K-hot;
                std::array<uint8_t,K*8> route_bytes;std::memcpy(route_bytes.data(),r.ids.data(),K*4);std::memcpy(route_bytes.data()+K*4,r.weights.data(),K*4);
                const auto input_hash=sha(input.data(),input.size()*4),route_hash=sha(route_bytes.data(),route_bytes.size());
                json row={{"type","pair"},{"case",name},{"pair",pair},{"warmup",warm},{"order",ab?"AB":"BA"},
                    {"routing_label",r.label},{"input_sha256",input_hash},{"routing_sha256",route_hash},
                    {"ids",r.ids},{"weight_bits",bits(r)},{"hot",stats.hot},{"cold",stats.cold},{"shared_nonzero",shared_nonzero},{"experts_nonzero",experts_nonzero},
                    {"correctness",metrics},{"valid",valid},{"A",{{"arm","A"},{"order",ab?0:1},{"total_layer_ms",am},{"output_sha256",sha(a.data(),a.size()*4)}}},
                    {"B",{{"arm","B"},{"order",ab?1:0},{"total_layer_ms",bm},{"output_sha256",sha(b.data(),b.size()*4)},
                        {"h5_layer_ms",stats.layer_ms},{"dispatch_ms",stats.dispatch_ms},{"cold_ms",stats.cold_ms},{"shared_ms",stats.shared_ms},{"join_ms",stats.join_ms},
                        {"input_bytes",stats.input_bytes},{"routing_bytes",stats.routing_bytes},{"result_bytes",stats.result_bytes},{"wire_bytes",nullptr},{"owner",stats.compact_owner},{"step",stats.steps}}},
                    {"B_minus_A_ms",bm-am}};
                for (const std::string arm_name:{"A","B"}) {
                    row[arm_name]["input_sha256"]=input_hash;row[arm_name]["routing_sha256"]=route_hash;
                    row[arm_name]["hot"]=arm_name=="A"?0:stats.hot;row[arm_name]["cold"]=arm_name=="A"?K:stats.cold;
                }
                std::cout<<row.dump()<<std::endl;require(valid,"invalid comparison: numerical/partition/shared/expert check failed");
                if (!warm) {ta.push_back(am);tb.push_back(bm);delta.push_back(bm-am);++measured;}
            }
            summaries[name]={{"A_ms",distribution(ta)},{"B_ms",distribution(tb)},{"B_minus_A_ms",distribution(delta)}};
        }
        std::cout<<json({{"type","summary"},{"valid",true},{"timing_comparison_valid",true},{"measured_pairs",measured},{"cases",summaries}}).dump()<<std::endl;
        return 0;
    } catch (const std::exception & e) {
        std::cout<<json({{"type","summary"},{"valid",false},{"timing_comparison_valid",false},{"error",e.what()},{"cases",nullptr}}).dump()<<std::endl;
        std::cerr<<"layer7 benchmark refused: "<<e.what()<<std::endl;return 2;
    }
}
