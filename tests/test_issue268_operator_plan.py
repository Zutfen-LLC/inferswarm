import copy
import unittest
from dataclasses import FrozenInstanceError

from inferswarm.operator.config import parse_config, parse_config_json
from inferswarm.operator.plan import build_plan
from inferswarm.operator.strategy import llama_cpp_spec


def sample():
    model={"source_id":"arbitrary-source","revision":"release-1","representation":"opaque-format","members":[{"name":"member.gguf","sha256":"a"*64,"size_bytes":1000}]}
    def participant(role, node, cu, transport, address, endpoint, device, cache):
        return {"role":role,"node_id":node,"compute_id":cu,"transport":transport,"execution_address":address,"rpc_endpoint":endpoint,"device":device,"source_path":"/srv/model/member.gguf","runtime_executable":"/usr/bin/llama","runtime_sha256":"b"*64,"cache_path":cache,"port":8080 if role=="client" else 8081,"lifecycle_dir":"/run/operator/"+node,"source_id":"arbitrary-source","source_revision":"release-1","source_representation":"opaque-format","cache_ranges":[{"member":"member.gguf","offset":0,"length":100,"sha256":"c"*64,"cache_key":"key-"+cu+"-"+unit,"source_id":"arbitrary-source","revision":"release-1","representation":"opaque-format","unit_id":unit} for unit in (("unit-cpu","unit-compute-x") if role=="client" else ("unit-compute-y",))]}
    return {"schema":"operator-config/2","plan_id":"plan-arbitrary","model":model,"participants":[participant("client","node-x","compute-x","local","127.0.0.1",None,"device-x","/var/cache/client"),participant("remote","node-y","compute-y","rpc","ssh-y","worker.example:5000","device-y","/var/cache/remote")],"strategy_id":"llama.cpp","placement":[{"unit_id":"unit-cpu","compute_id":"compute-x","state_ids":["opaque-cpu-state"],"first_layer":0,"last_layer":40,"output":False},{"unit_id":"unit-compute-x","compute_id":"compute-x","state_ids":["opaque-state-x"],"first_layer":41,"last_layer":44,"output":False},{"unit_id":"unit-compute-y","compute_id":"compute-y","state_ids":["opaque-state-y"],"first_layer":45,"last_layer":47,"output":True}],"backend_options":{"hidden_layers":48,"offload_tail":8,"cpu_experts":True,"tensor_split":[1,1],"context":1024,"slots":1,"startup_timeout_seconds":90,"split_mode":"layer","verbosity":5},"request":{"prompt":"hello","max_tokens":8,"temperature":0.0,"seed":42}}

class OperatorPlanTests(unittest.TestCase):
    def test_parse_build_and_order_independent_digest(self):
        x=sample(); plan=build_plan(parse_config(x)); x["participants"].reverse()
        self.assertEqual(plan.digest,build_plan(parse_config(x)).digest)
        spec=llama_cpp_spec(plan)
        self.assertIn(("--rpc","worker.example:5000"),tuple(zip(spec.args,spec.args[1:])))
        self.assertEqual(spec.expected_placement[1].first_layer,41)
        self.assertEqual(dict(plan.request)["seed"],42)
    def test_strict_fields_hash_and_member_names(self):
        for mutate in (lambda x:x.update(extra=1),lambda x:x.pop("plan_id"),lambda x:x["model"]["members"][0].update(sha256="bad"),lambda x:x["model"]["members"][0].update(name="../escape.gguf"),lambda x:x["participants"][0].update(port=True)):
            x=sample(); mutate(x)
            with self.assertRaises(ValueError): parse_config(x)
    def test_duplicate_json_keys_and_nonfinite_rejected(self):
        with self.assertRaisesRegex(ValueError,"duplicate JSON key"):
            parse_config_json('{"schema":"operator-config/2","schema":"operator-config/2"}')
    def test_explicit_roles_transport_and_order(self):
        x=sample(); x["participants"][0]["transport"]="rpc"
        with self.assertRaisesRegex(ValueError,"transport"): parse_config(x)
        x=sample(); x["participants"][0],x["participants"][1]=x["participants"][1],x["participants"][0]
        plan=build_plan(parse_config(x)); self.assertEqual(llama_cpp_spec(plan).rpc_endpoint,"worker.example:5000")
    def test_typed_launch_has_no_user_native_args(self):
        x=sample(); x["placement"][0]["native_args"]=["--split-mode","row"]
        with self.assertRaises(ValueError): parse_config(x)
        args=llama_cpp_spec(build_plan(parse_config(sample()))).args
        self.assertEqual(args.count("--split-mode"),1)
        self.assertNotIn("--rpc",args[args.index("--device"):])
    def test_range_gaps_overlap_and_output_assignment_rejected(self):
        for first,last,output in ((40,47,True),(42,47,True),(45,47,False)):
            x=sample(); x["placement"][1].update(first_layer=first,last_layer=last,output=output)
            with self.assertRaises(ValueError): llama_cpp_spec(build_plan(parse_config(x)))
    def test_backing_descriptor_ranges_are_bounded_and_bound_to_source(self):
        for change in ({"offset":999},{"source_id":"wrong"},{"cache_key":""}):
            x=sample(); x["participants"][1]["cache_ranges"][0].update(change)
            with self.assertRaises(ValueError): parse_config(x)
    def test_deep_immutable_and_model_independent(self):
        p=build_plan(parse_config(sample()))
        with self.assertRaises((FrozenInstanceError,AttributeError,TypeError)): p.placement[0].state_ids += ("x",)
        self.assertEqual(p.model.source_id,"arbitrary-source")
        self.assertFalse(hasattr(p.participants[0],"backing_verified"))
    def test_request_and_float_validation(self):
        for key,value in (("seed",True),("temperature",float("nan"))):
            x=sample(); x["request"][key]=value
            with self.assertRaises(ValueError): parse_config(x)

if __name__ == "__main__": unittest.main()
