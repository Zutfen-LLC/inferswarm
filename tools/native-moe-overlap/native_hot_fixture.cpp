// Actual pinned llm_graph_context FFN through the real scheduler/RPC backend.
#include "llama-graph.h"
#include "llama-model.h"
#include "llama-cparams.h"
#include "ggml-cpu.h"
#include "ggml-rpc.h"
#include "ggml-alloc.h"
#include "ggml-impl.h"
#include "demand.h"
#include "nlohmann/json.hpp"
#include <cmath>
#include <cstring>
#include <fstream>
#include <iostream>
#include <stdexcept>
using nlohmann::json;
namespace {
constexpr int D=32,F=32,E=12,K=10;
struct fixture {
    ggml_backend_t cpu=nullptr,rpc=nullptr;
    ggml_backend_sched_t sched=nullptr;
    ggml_context * ctx=nullptr;
    ggml_backend_buffer_t buffer=nullptr;
    llama_layer layer;
    int phase_id=0;
    std::shared_ptr<llama_hot_experts> owner;
    llama_moe_overlap_config cfg;
    ~fixture() {
        owner.reset(); ggml_backend_sched_free(sched); ggml_backend_buffer_free(buffer);
        ggml_free(ctx); ggml_backend_free(rpc); ggml_backend_free(cpu);
    }
    void setup(const char * endpoint,const std::string & root,bool q8=false) {
        cfg=llama_moe_overlap_config::from_env(9);
        cpu=ggml_backend_cpu_init(); ggml_backend_cpu_set_n_threads(cpu,2);
        rpc=ggml_backend_rpc_init(endpoint,0); if (!rpc) throw std::runtime_error("fixture RPC unavailable");
        ggml_backend_t backends[]={rpc,cpu}; sched=ggml_backend_sched_new(backends,nullptr,2,8192,false,false);
        ctx=ggml_init({ggml_tensor_overhead()*20,nullptr,true});
        layer.ffn_gate_inp=ggml_new_tensor_2d(ctx,GGML_TYPE_F32,D,E);
        layer.ffn_gate_inp_shexp=ggml_new_tensor_2d(ctx,GGML_TYPE_F32,D,1);
        layer.ffn_gate_shexp=ggml_new_tensor_2d(ctx,GGML_TYPE_F32,D,F);
        layer.ffn_up_shexp=ggml_new_tensor_2d(ctx,GGML_TYPE_F32,D,F);
        layer.ffn_down_shexp=ggml_new_tensor_2d(ctx,GGML_TYPE_F32,F,D);
        const auto bank_type=q8?GGML_TYPE_Q8_0:GGML_TYPE_F32;
        layer.ffn_gate_exps=ggml_new_tensor_3d(ctx,bank_type,D,F,E);
        layer.ffn_up_exps=ggml_new_tensor_3d(ctx,bank_type,D,F,E);
        layer.ffn_down_exps=ggml_new_tensor_3d(ctx,bank_type,F,D,E);
        const std::pair<const char *,ggml_tensor *> banks[]={{"gate",layer.ffn_gate_exps},{"up",layer.ffn_up_exps},{"down",layer.ffn_down_exps}};
        for (auto item:banks) ggml_format_name(item.second,"blk.7.ffn_%s_exps.weight",item.first);
        buffer=ggml_backend_alloc_ctx_tensors(ctx,cpu); ggml_backend_buffer_set_usage(buffer,GGML_BACKEND_BUFFER_USAGE_WEIGHTS);
        for (auto t=ggml_get_first_tensor(ctx);t;t=ggml_get_next_tensor(ctx,t)) {
            std::vector<float> data(ggml_nelements(t));
            if (t==layer.ffn_gate_inp) {
                const int order[]={8,1,6,3,0,9,2,7,4,5,10,11};
                for (int i=0;i<E;++i) data[order[i]*D]=float(E-i)/3;
            } else if (t!=layer.ffn_gate_inp_shexp) {
                for (size_t i=0;i<data.size();++i) data[i]=(i%D==i/D%F)?0.125f:0.0f;
            }
            ggml_backend_tensor_set(t,data.data(),0,ggml_nbytes(t));
        }
        for (auto item:banks) {
            std::ifstream file(root+"/"+item.first+(q8?".q8.bin":".bin"),std::ios::binary);
            std::vector<char> data(ggml_nbytes(item.second));
            if (!file.read(data.data(),data.size())) throw std::runtime_error("fixture bank short read");
            ggml_backend_tensor_set(item.second,data.data(),0,data.size());
        }
    }
    void guard_probe(const std::string & control) {
        std::ifstream file(std::getenv("IS314_HOT_SPEC")); json spec; file>>spec;
        const auto & row=spec["tensors"][0]; const auto ids=spec["expert_ids"].get<std::vector<int>>();
        auto temporary=ggml_init({ggml_tensor_overhead()*8,nullptr,true});
        const auto shape=row["compact_shape"].get<std::vector<int64_t>>();
        auto first=ggml_new_tensor_4d(temporary,GGML_TYPE_F32,shape[0],shape[1],shape[2],shape[3]);
        ggml_set_name(first,row["compact_name"].get<std::string>().c_str());
        auto second=ggml_dup_tensor(temporary,first);ggml_set_name(second,first->name);
        auto view=ggml_view_4d(temporary,first,first->ne[0],first->ne[1],first->ne[2],first->ne[3],first->nb[1],first->nb[2],first->nb[3],0);
        ggml_set_name(view,first->name);
        auto buf=ggml_backend_alloc_ctx_tensors(temporary,rpc);ggml_backend_buffer_set_usage(buf,GGML_BACKEND_BUFFER_USAGE_WEIGHTS);
        std::vector<uint8_t> bytes(ggml_nbytes(first));
        for (size_t i=0;i<ids.size();++i) std::memcpy(bytes.data()+i*layer.ffn_gate_exps->nb[2],static_cast<uint8_t *>(layer.ffn_gate_exps->data)+ids[i]*layer.ffn_gate_exps->nb[2],layer.ffn_gate_exps->nb[2]);
        if (control=="guard-partial") ggml_backend_tensor_set(first,bytes.data(),0,bytes.size()/2);
        else if (control=="guard-view") ggml_backend_tensor_set(view,bytes.data(),0,bytes.size());
        else { ggml_backend_tensor_set(first,bytes.data(),0,bytes.size()); ggml_backend_tensor_set(second,bytes.data(),0,bytes.size()); }
        ggml_backend_synchronize(rpc);ggml_backend_buffer_free(buf);ggml_free(temporary);
        throw std::runtime_error("guard probe incorrectly accepted");
    }
    void run(int tokens,int il,int shape,const std::string & control,unsigned & sequence,is312::capture & cap) {
        llm_graph_result result(8192); llama_adapter_loras loras; llm_graph_params params={};
        params.arch=LLM_ARCH_QWEN4EXP; params.hparams.n_layer_all=9; params.hparams.n_embd=D;
        params.hparams.n_expert=E; params.hparams.n_expert_used_arr.fill(K);
        params.hparams.n_head_arr.fill(1); params.hparams.n_head_kv_arr.fill(1);
        params.hparams.n_embd_head_k_full=D; params.hparams.n_embd_head_v_full=D; params.hparams.n_rot_full=D;
        params.hparams.expert_weights_scale=1; params.cparams.n_threads=2;params.cparams.n_threads_batch=2;
        params.ubatch.n_tokens=tokens;params.sched=sched;params.backend_cpu=cpu;params.loras=&loras;params.res=&result;
        params.hot_owner=&owner;params.hot_phase=&phase_id;
        params.cb=[](const llama_ubatch &,ggml_tensor * t,const char * name,int il){ggml_format_name(t,"%s-%d",name,il);};
        llm_graph_context builder(params);
        auto selected=layer; if (control=="missing-shared") selected.ffn_up_shexp=nullptr;
        auto input=ggml_new_tensor_2d(result.get_ctx(),GGML_TYPE_F32,D,tokens); ggml_set_input(input);
        auto activation=ggml_scale(result.get_ctx(),input,0.75f);
        auto ffn=builder.build_qwen4exp_ffn(activation,selected,il,cfg);
        if (control=="reverse-reduction") {
            auto weighted=ggml_get_tensor(result.get_ctx(),("ffn_moe_weighted-"+std::to_string(il)).c_str());
            if (!weighted) throw std::runtime_error("fixture weighted source cut missing");
            auto reduced=ggml_view_2d(result.get_ctx(),weighted,D,tokens,weighted->nb[2],9*weighted->nb[1]);
            for (int i=8;i>=0;--i) reduced=ggml_add(result.get_ctx(),reduced,ggml_view_2d(result.get_ctx(),weighted,D,tokens,weighted->nb[2],i*weighted->nb[1]));
            ffn=ggml_add(result.get_ctx(),reduced,ffn->src[1]);
        }
        auto output=ggml_scale(result.get_ctx(),ffn,1.0f);ggml_set_output(output);ggml_build_forward_expand(result.get_gf(),output);
        if (!ggml_backend_sched_alloc_graph(sched,result.get_gf())) throw std::runtime_error("fixture outer allocation failed");
        for (int step=0;step<3;++step) {
            const std::string phase=sequence==0 || tokens>1?"prefill":"decode";
            phase_id=phase=="prefill"?1:2;
            if (tokens>1 || sequence>=3 || control=="prefill-no-collector") is312::set_active(nullptr);
            if (is312::active()) cap.begin(phase,sequence,tokens);
            ++sequence;
            std::vector<float> values(D*tokens),actual(D*tokens);
            for (size_t i=0;i<values.size();++i) values[i]=0.4f+step*0.125f+float(i%7)/32;
            // Router uses column zero: reverse its order/selection on step 1.
            if (step==1) values[0]=-values[0];
            ggml_backend_tensor_set(input,values.data(),0,values.size()*sizeof(float));
            if (ggml_backend_sched_graph_compute(sched,result.get_gf())!=GGML_STATUS_SUCCESS) throw std::runtime_error("fixture graph failed");
            ggml_backend_tensor_get(output,actual.data(),0,actual.size()*sizeof(float));
            json row={{"shape",shape},{"step",step},{"layer",il},{"tokens",tokens},{"output",actual},
                      {"owners",result.hot_experts.size()},{"hot",0},{"cold",0},{"compact_owner",0},{"phase",phase}};
            if (!result.hot_experts.empty()) {
                auto stats=llama_hot_get_stats(result.hot_experts[0]); row["hot"]=stats.hot;row["cold"]=stats.cold;row["compact_owner"]=stats.compact_owner;
                row["phase"]=stats.phase==1?"prefill":"decode";
                if (is312::active()) { auto capture=json::parse(cap.export_json());
                    if (capture["rows"].back()["phase"]!=row["phase"]) throw std::runtime_error("phase binding mismatch"); }
            }
            std::cout<<row.dump()<<std::endl;
        }
        ggml_backend_sched_synchronize(sched);ggml_backend_sched_reset(sched);result.reset();
        if (!result.hot_experts.empty()) throw std::runtime_error("graph owner survived reset");
    }
};
}
int main(int argc,char ** argv) {
    if (argc<3) return 2;
    try {
        const std::string control=argc>3?argv[3]:"";
        is312::identity id{"fixture","fixture",std::string(64,'a'),"F32",std::string(40,'a'),std::string(64,'b'),std::string(64,'c'),"test","fixture","cpu","fixture","fixture","0","qwen4exp"};
        is312::capture cap(id,9,E,K,128); is312::set_active(&cap);
        { fixture f; f.setup(argv[1],argv[2],control=="q8"); if (control.rfind("guard-",0)==0) f.guard_probe(control); unsigned sequence=0;
          f.run(1,7,0,control,sequence,cap); f.run(3,7,1,control,sequence,cap);
          f.run(1,6,2,control,sequence,cap); f.run(1,7,3,control,sequence,cap); }
        is312::set_active(nullptr); std::cout<<"{\"released\":true}"<<std::endl;
    } catch (const std::exception & e) { std::cerr<<"fixture refused: "<<e.what()<<std::endl; return 2; }
    return 0;
}
