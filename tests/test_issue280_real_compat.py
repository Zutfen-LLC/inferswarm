"""D1/D2/D3 regressions: actual bound capture and independent semantic attacks."""
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "docs/investigations/vulkan-same-request-280/compatibility"
CAPTURE_SHA256 = "b1fa13966a715d2009efdde4fa602a5a6f0b70d93c3884ceef0d14426bfcc796"

def load(name):
    path = ROOT / ("tests/test_issue280_admission.py" if name == "builder" else "scripts/issue280_" + name + ".py")
    spec = importlib.util.spec_from_file_location("i280_compat_" + name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m

def observer():
    return load("observer")

def rewrite(raw, event, change, predicate=lambda r: True, first=False):
    out, hits = [], 0
    for line in raw.splitlines():
        if "I280 " not in line:
            out.append(line)
            continue
        row = json.loads(line.split("I280 ", 1)[1])
        if row["event"] == event and predicate(row) and (not first or hits == 0):
            hits += 1
            row = change(row)
            if row is None:
                continue
        out.append("I280 " + json.dumps(row, separators=(",", ":")))
    assert hits, event
    return "\n".join(out) + "\n"

def update(**fields):
    return lambda r: {**r, **fields}

class RealCaptureCompatibilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        data = gzip.decompress((BUNDLE / "observer-R1-cold.i280.raw.gz").read_bytes())
        assert hashlib.sha256(data).hexdigest() == CAPTURE_SHA256
        cls.raw = data.decode()
        cls.m = observer()

    def verdict(self, raw):
        return self.m.validate_admission(raw, self.m.physical_280_contracts()["A"])

    def reject(self, raw, reason):
        v = self.verdict(raw)
        self.assertFalse(v["ok"], v)
        self.assertTrue(any(reason in p for p in v["problems"]), v["problems"])
        return v

    def test_exact_real_capture_is_compatible(self):
        v = self.verdict(self.raw)
        self.assertTrue(v["ok"], v["problems"])
        self.assertEqual(v["graph_count"], 40)
        self.assertEqual(v["per_die"]["0000:07:00.0"]["completed_compute_commands"], 457)

    def test_legacy_witness_cannot_transfer_to_changed_tokens_or_timestamps(self):
        for field, value in (("ts_ns", 1208002000000000), ("token_ids", [0] * 31)):
            raw = rewrite(self.raw, "batch_begin", update(**{field: value}), first=True)
            # A timestamp change may fail ordering first, never admit.
            self.assertFalse(self.verdict(raw)["ok"])

    def test_direct_conflicts_are_not_ignored_by_legacy_witness(self):
        for fields in ({"n_seqs_unq": 2, "seq_ids_unq": [0, 1], "n_seq_tokens": 1},
                       {"n_seqs_unq": 1, "seq_ids_unq": [1], "n_seq_tokens": 1}):
            self.reject(rewrite(self.raw, "graph_begin", update(**fields), first=True), "sequence")

    def test_request_mismatch_preserved(self):
        self.reject(rewrite(self.raw, "graph_begin", update(request=99), first=True), "cross-request")

    def test_explicit_terminal_sequence_conflict_rejected(self):
        self.reject(rewrite(self.raw, "request_end", update(seq=1)), "sequence")

    def test_host_lookalikes_and_unassigned_fail_closed(self):
        for name in ("CPU_Mapped_FAKE", "VulkanCPU_Mapped", "CPUfoo", "unknown_accelerator", "unassigned"):
            raw = rewrite(self.raw, "weight_inventory", update(bdf=name, backend=name),
                          lambda r: r["bdf"] == "CPU_Mapped")
            self.reject(raw, "placement")

    def test_explicit_backend_conflict_rejected(self):
        self.reject(rewrite(self.raw, "weight_inventory", update(backend="Vulkan0"),
                            lambda r: r["bdf"] == "CPU_Mapped"), "conflicting")

    def test_output_operand_required(self):
        self.reject(rewrite(self.raw, "weight", lambda r: None,
                            lambda r: r["tensor"] == "token_embd.weight"), "output role")

    def test_output_op_required(self):
        self.reject(rewrite(self.raw, "node", update(op="ADD"),
                            lambda r: r["tensor"] == "result_output"), "output role")

    def test_output_bytes_match_inventory(self):
        self.reject(rewrite(self.raw, "weight", update(bytes=128),
                            lambda r: r["tensor"] == "token_embd.weight"), "output role")

    def test_tied_cpu_backing_required(self):
        self.reject(rewrite(self.raw, "weight_inventory", lambda r: None,
                            lambda r: r["tensor"] == "token_embd.weight" and r["bdf"] == "CPU_Mapped"), "output role")

    def test_tied_cpu_backing_bytes_required(self):
        self.reject(rewrite(self.raw, "weight_inventory", update(bytes=128),
                            lambda r: r["tensor"] == "token_embd.weight" and r["bdf"] == "CPU_Mapped"), "output role")

    def test_ambiguous_gpu_alias_rejected(self):
        self.check_ambiguous_gpu_alias()

    def test_corrupted_matching_tied_sizes_still_fail_model_identity(self):
        raw = rewrite(self.raw, "weight_inventory", update(bytes=128),
                      lambda r: r["tensor"] == "token_embd.weight")
        raw = rewrite(raw, "weight", update(bytes=128), lambda r: r["tensor"] == "token_embd.weight")
        self.reject(raw, "output role")

    def test_explicit_model_identity_conflict(self):
        self.reject(rewrite(self.raw, "recording", update(model_sha256="wrong-model")), "output role")

    def test_distinct_inventory_prevents_silent_tied_fallback(self):
        raw = rewrite(self.raw, "weight_inventory", update(tensor="output.weight"),
                      lambda r: r["tensor"] == "output_norm.weight")
        self.reject(raw, "output role")

    def check_ambiguous_gpu_alias(self):
        lines = self.raw.splitlines()
        row = json.loads(lines[3].split("I280 ", 1)[1])
        self.assertEqual(row["tensor"], "token_embd.weight")
        row["buffer"] = "ambiguous-copy"
        lines.insert(4, "I280 " + json.dumps(row))
        self.reject("\n".join(lines) + "\n", "output role")

    def test_wrong_bdf(self):
        self.reject(rewrite(self.raw, "vk_graph_begin", update(bdf="0000:0b:00.0")), "BDF")

    def test_missing_upper_blocks(self):
        self.reject(rewrite(self.raw, "weight_inventory", lambda r: None,
                            lambda r: r["tensor"].startswith("blk.35.")), "inventory")

    def test_missing_kv(self):
        self.reject(rewrite(self.raw, "kv_inventory", lambda r: None), "kv_cache")

    def test_missing_completed_compute(self):
        self.reject(rewrite(self.raw, "complete", lambda r: None), "completed")

class LegacyAuthorityTransferRegressionTests(unittest.TestCase):
    """Round-2 trust-boundary regression (PR #286 review).

    The historical legacy sequence inference must not transfer to any
    stream that is not byte-identical to the exact retained historical R1
    capture — not even when its request/batch/graph projection matches the
    historical projection exactly and the stream is otherwise
    collector-valid. A production run_campaign() admission must likewise
    never consume legacy sequence authority for a stream lacking the
    successor direct sequence metadata.
    """

    @classmethod
    def setUpClass(cls):
        data = gzip.decompress((BUNDLE / "observer-R1-cold.i280.raw.gz").read_bytes())
        assert hashlib.sha256(data).hexdigest() == CAPTURE_SHA256
        cls.raw = data.decode()
        cls.m = observer()

    def attack_stream(self):
        """NOT byte-identical to the retained capture: exactly one legal,
        otherwise collector-valid cpu_state row. Same historical projection;
        still no successor direct sequence metadata."""
        lines = self.raw.splitlines()
        first_accept = next(i for i, line in enumerate(lines) if '"request_accept"' in line)
        ts = json.loads(lines[first_accept].split("I280 ", 1)[1])["ts_ns"]
        row = {"schema": "issue280-raw/1", "event": "cpu_state", "ts_ns": ts,
               "kind": "host_scratch", "bytes": 4096}
        lines.insert(first_accept, "I280 " + json.dumps(row, separators=(",", ":")))
        attack = "\n".join(lines) + "\n"
        assert hashlib.sha256(attack.encode()).hexdigest() != CAPTURE_SHA256
        return attack

    def test_non_identical_same_projection_stream_cannot_borrow_legacy_sequence_authority(self):
        attack = self.attack_stream()
        self.assertEqual(self.m._compat.sequence_projection(self.m.parse(attack)),
                         self.m._compat.sequence_projection(self.m.parse(self.raw)))
        v = self.m.validate_admission(attack, self.m.physical_280_contracts()["A"])
        self.assertFalse(v["ok"], v)
        self.assertTrue(any("sequence" in p for p in v["problems"]), v["problems"])
        self.assertNotEqual(v["sequence_evidence"], "AUTHENTICATED_R1_ONE_SLOT_SOURCE_INFERENCE")

    def test_production_runner_rejects_old_instrumentation_stream_without_direct_metadata(self):
        runner = load("runner")
        good = '{"service":"payments","severity":"high","status":"resolved"}'
        executed = []

        def launch(row):
            def request(kind):
                executed.append((row["label"], kind))
                return ({"launch": row["label"], "arm": row["arm"], "prompt": row["prompt"],
                         "kind": kind, "text": good, "transport_ok": True, "health_stop": None},
                        {"observer_raw": self.attack_stream(), "peak_rss_bytes": 1,
                         "observer_events": set()})
            return request

        summary = runner.run_campaign(runner.MINIMAL_RERUN_MATRIX, launch)
        self.assertEqual(len(executed), 1, "request 2 must never launch")
        self.assertEqual(summary["terminal"], "STOP")
        self.assertIn("observer admission failure", summary["stop_reason"])
        self.assertIn("sequence", summary["stop_reason"])


class DirectSequenceAndRoleTests(unittest.TestCase):
    def setUp(self):
        self.m = observer()
        self.raw = load("builder").build_stream(single_die=True)

    def v(self, raw):
        return self.m.validate_admission(raw, self.m.physical_280_contracts()["A"])

    def test_sequence_sets_are_not_unique_sequence_count(self):
        raw = rewrite(self.raw, "graph_begin", update(sequences=4, n_seq_tokens=1))
        self.assertTrue(self.v(raw)["ok"], self.v(raw)["problems"])

    def test_missing_unique_metadata_unrelated_stream_rejected(self):
        raw = rewrite(self.raw, "graph_begin", lambda r: {k: v for k, v in r.items()
                      if k not in ("n_seqs_unq", "seq_ids_unq", "n_seq_tokens")})
        self.assertFalse(self.v(raw)["ok"])

    def test_bad_direct_uniqueness_rejected(self):
        cases = ({"n_seqs_unq": 2, "seq_ids_unq": [0, 1]}, {"seq_ids_unq": [1]},
                 {"seq_ids_unq": [0, 0]}, {"n_seqs_unq": True}, {"n_seq_tokens": 1})
        for fields in cases:
            with self.subTest(fields=fields):
                self.assertFalse(self.v(rewrite(self.raw, "graph_begin", update(**fields)))["ok"])

    def test_accepted_sequence_must_match_batch(self):
        self.assertFalse(self.v(rewrite(self.raw, "request_accept", update(seq=1)))["ok"])

    def test_distinct_output_requires_output_compute(self):
        raw = rewrite(self.raw, "node", update(tensor="output_norm"), lambda r: r["tensor"] == "result_output")
        self.assertFalse(self.v(raw)["ok"])

    def test_wrong_output_die_remains_output_role_failure(self):
        raw = load("builder").build_stream(output_bdf="0000:07:00.0")
        v = self.m.validate_admission(raw, self.m.physical_280_contracts()["B"])
        self.assertFalse(v["ok"])
        self.assertTrue(any("output role" in p for p in v["problems"]), v["problems"])

    def test_uncompleted_output_is_not_compute_evidence(self):
        raw = rewrite(self.raw, "complete", lambda r: None)
        v = self.v(raw)
        self.assertFalse(v["ok"])
        self.assertTrue(any("output role" in p for p in v["problems"]), v["problems"])

    def test_new_direct_stream_tied_role_needs_no_new_d3_producer_fields(self):
        # Frozen model/source policy plus actual output operand and ownership:
        # the successor changes only graph metadata, not model-load rows.
        raw = rewrite(self.raw, "weight_inventory", update(tensor="token_embd.weight", bytes=255252480),
                      lambda r: r["tensor"] == "output.weight")
        raw = rewrite(raw, "weight", update(tensor="token_embd.weight", bytes=255252480,
                      buffer_bytes=255252480), lambda r: r["tensor"] == "output.weight")
        row = {"schema": "issue280-raw/1", "event": "weight_inventory", "ts_ns": 10,
               "tensor": "token_embd.weight", "layer": -1, "buffer": "host-input-copy",
               "bytes": 255252480, "bdf": "CPU_Mapped", "backend": "CPU_Mapped"}
        lines = raw.splitlines()
        lines.insert(1, "I280 " + json.dumps(row))
        v = self.v("\n".join(lines) + "\n")
        self.assertTrue(v["ok"], v["problems"])
        self.assertEqual(v["sequence_evidence"], "DIRECT_UNIQUE_IDS")

    def test_exact_host_names_count_only_in_denominator(self):
        for name in ("CPU", "CPU_Mapped", "Vulkan_Host"):
            row = {"schema": "issue280-raw/1", "event": "weight_inventory", "ts_ns": 10,
                   "tensor": "token_embd.weight", "layer": -1, "buffer": "host", "bytes": 100,
                   "bdf": name, "backend": name}
            lines = self.raw.splitlines()
            lines.insert(1, "I280 " + json.dumps(row))
            result = self.m.collect("\n".join(lines) + "\n", self.m.physical_280_contracts()["A"])
            self.assertTrue(result["ok"], result["problems"])
            self.assertEqual(result["placement"]["cpu_weight_bytes"], 100)
            self.assertEqual(result["placement_denominator_bytes"], 36 * 1024 + 512 + 100)
            self.assertEqual(result["placement"]["cpu_state"][0].get("backend"), name)

    def test_prelaunch_compatibility_failure_prevents_executor(self):
        runner = load("runner")
        runner._compatibility_gate = lambda: {"ok": False, "problems": ["injected compatibility failure"]}
        launches = []
        def launch(row):
            launches.append(row)
            return lambda kind: ({"transport_ok": False}, {})
        summary = runner.run_campaign(runner.MINIMAL_RERUN_MATRIX, launch)
        self.assertEqual(launches, [])
        self.assertEqual(summary["terminal"], "STOP")
        self.assertIn("compatibility", summary["stop_reason"])

if __name__ == "__main__":
    unittest.main()
