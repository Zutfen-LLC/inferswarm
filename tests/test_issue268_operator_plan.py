import unittest
from dataclasses import FrozenInstanceError

from inferswarm.operator.config import parse_config
from inferswarm.operator.plan import build_plan
from inferswarm.operator.strategy import llama_cpp_spec


def sample():
    return {"schema":"operator-config/1","plan_id":"p1","model":{"source_id":"arbitrary-model","revision":"rev-1","representation":"gguf","members":[{"name":"part.gguf","sha256":"a"*64}]},"participants":[{"node_id":"node-a","compute_id":"cu-a","transport":"local","address":"127.0.0.1","device":"CUDA0","source_id":"arbitrary-model","source_revision":"rev-1","source_representation":"gguf","source_path":"/models/part.gguf","runtime_executable":"/bin/llama","runtime_sha256":"b"*64,"cache_path":"/cache/a","port":8080,"lifecycle_dir":"/run/a"},{"node_id":"node-b","compute_id":"cu-b","transport":"rpc","address":"host:5000","device":"RPC0","source_id":"arbitrary-model","source_revision":"rev-1","source_representation":"gguf","source_path":"/models/part.gguf","runtime_executable":"/bin/llama","runtime_sha256":"b"*64,"cache_path":"/cache/b","port":8081,"lifecycle_dir":"/run/b"}],"strategy_id":"llama.cpp","placement":[{"unit_id":"layers-0-40","compute_id":"cu-a","native_args":["--tensor-split","1,1"]},{"unit_id":"layers-41-48","compute_id":"cu-b","native_args":["-ngl","8"]}],"request":{"prompt":"hello","max_tokens":8,"temperature":0}}

class OperatorPlanTests(unittest.TestCase):
    def test_parse_build_and_deterministic_digest(self):
        c=parse_config(sample()); p=build_plan(c)
        self.assertEqual(p.digest,build_plan(parse_config(sample())).digest)
        self.assertEqual(p.placement[0].compute_id,"cu-a")
        self.assertEqual(llama_cpp_spec(p).expected_placement,p.placement)
    def test_unknown_missing_and_bad_digest_rejected(self):
        for mutate in (lambda x:x.update(extra=1), lambda x:x.pop("plan_id"), lambda x:x["model"]["members"][0].update(sha256="bad")):
            x=sample(); mutate(x)
            with self.assertRaises(ValueError): parse_config(x)
    def test_unknown_compute_and_incomplete_duplicate_placement_rejected(self):
        x=sample(); x["placement"][0]["compute_id"]="missing"
        with self.assertRaises(ValueError): build_plan(parse_config(x))
    def test_deep_immutable_and_identity_is_opaque(self):
        p=build_plan(parse_config(sample()))
        with self.assertRaises((FrozenInstanceError, AttributeError, TypeError)):
            p.placement[0].native_args += ("x",)
        self.assertEqual(p.model.source_id,"arbitrary-model")
    def test_cache_descriptor_is_not_claimed_as_verified_bytes(self):
        p=build_plan(parse_config(sample()))
        self.assertFalse(p.participants[1].backing_verified)

if __name__ == "__main__": unittest.main()
