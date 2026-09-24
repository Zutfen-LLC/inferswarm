"""CPU-only comparator/2 execution-seam and evidence tests (unittest)."""
from __future__ import annotations
import inspect
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from scripts import issue241_comparator_producer as producer
from scripts import issue241_constants as C
from scripts import issue241_placement as placement
from scripts import issue241_placement_producer as p2
from scripts import issue241_dispatch as dispatch
from scripts import issue241_practicality as practicality
from tests.test_issue241_placement_producer import identity_observer

AUTH = {"schema": dispatch.AUTHORITY_SCHEMA, "head_sha": "a" * 40,
        "dispatch_phrase": dispatch.DISPATCH_PHRASE,
        "comment_id": 55, "commenter": "maintainer",
        "commenter_association": "OWNER",
        "created_at": "2026-09-23T00:00:00Z"}


def phase2():
    arms = {arm: [{"schema": placement.RUNG_SCHEMA, "arm": arm, "ngl": n,
        "loaded": True, "placement": {"offloaded_layers": [str(n), "99"],
        "alloc_failures": 0, "fallback_markers": 0, "buffer_records": []},
        "excluded_device_residency_mib": {},
        "process_measurements": {key: 1 for key in p2.MEASURED_FIELDS},
        "request_timings": {"prompt_ms": 1.0, "decode_ms": 2.0},
        "device_identity": identity(arm),
        "post_execution_device_identity": identity(arm),
        "device_health": p2._device_health(arm, identity(arm)),
        "repeats": repeats(arm)} for n in C.LADDER_NGLS] for arm in ("B", "C")}
    selected = placement.select_matched_rung(arms)
    receipts = [{"ngl": n, "arm": arm, "raw_log": f"{arm}-{n}.log",
                 "raw_log_sha256": "b" * 64} for n in C.LADDER_NGLS for arm in ("C", "B")]
    return {"schema": p2.SCHEMA, "campaign": C.CAMPAIGN_ID, "authority": AUTH,
            "rungs": arms, "rung_receipts": receipts,
            "selected": selected, "digest": "c" * 64}


def identity(arm):
    return identity_observer(arm)["identity"]


def repeats(arm=None, tokens=None, sha=None):
    arm = arm or "C"
    toks = tokens if tokens is not None else [11, 22, 33, 44, 55, 66, 77, 88]
    det_sha = placement.deterministic_output_sha256(toks)
    ident = identity(arm)
    health = p2._device_health(arm, ident)
    return [{
        "index": i,
        "sane_completion": True,
        "response_tokens": list(toks),
        "deterministic_output_sha256": det_sha,
        "response_raw": f"arm-ngl1{'' if i == 0 else f'.repeat{i}'}.response.json",
        "response_raw_sha256": sha or ("d" * 64),
        "raw_log": f"stub{'' if i == 0 else f'.repeat{i}'}.server.log",
        "raw_log_sha256": "e" * 64,
        "raw_telemetry": f"stub{'' if i == 0 else f'.repeat{i}'}.telemetry.json",
        "raw_telemetry_sha256": "f" * 64,
        "identity_pre": ident,
        "raw_identity_pre": f"stub{'' if i == 0 else f'.repeat{i}'}.identity-pre.json",
        "raw_identity_pre_sha256": "1" * 64,
        "identity_post": ident,
        "raw_identity_post": f"stub{'' if i == 0 else f'.repeat{i}'}.identity-post.json",
        "raw_identity_post_sha256": "2" * 64,
        "identity_post_health": health,
        "request_timings": {"prompt_ms": 1.0 + i, "decode_ms": 2.0 + i},
        "failure": None} for i in range(placement.RUNG_REPEATS)]


class FakeRunner:
    def __init__(self, bad=False):
        self.calls = []
        self.bad = bad
    def __call__(self, *, argv, env, arm, mode, request, prompt, output_dir, timeout_s):
        self.calls.append((arm, mode, request, prompt, timeout_s))
        winners = list(range(8))
        forced = [int(x) for x in env.get("LLAMA_OBSERVE_FORCE", "").split(",") if x]
        tokens = forced if arm == "C" and mode in ("candidate", "repeat") else winners
        observe = mode in ("baseline", "candidate", "repeat")
        rows = {str(d): bytes(C.ROW_BYTES) for d in range(8)} if observe and not self.bad else None
        meta = [{"pos": d, "sampled_winner": winners[d],
                 "forced_token": -1 if arm == "B" else (forced[d] if forced else -1)}
                for d in range(8)] if observe and not self.bad else []
        if observe and not self.bad:
            Path(env["LLAMA_OBSERVE_OUT"] + ".meta.json").write_text(
                "".join(json.dumps(row) + "\n" for row in meta))
        return {"returncode": 0, "response": {"tokens": tokens},
                "response_raw": json.dumps({"tokens": tokens}).encode(),
                "tokens": tokens, "rows": rows,
                "meta_rows": meta, "sampled_winners": winners,
                "forced_tokens": forced if arm == "C" else [],
                "pid": 1000 + len(self.calls), "log": f"raw log {arm} {mode}\n",
                "process_attribution": {"server_pid": 1000 + len(self.calls),
                    "server_argv": argv, "server_env": {**env},
                    "server_exe_sha256": hashlib.sha256(Path(argv[0]).read_bytes()).hexdigest()},
                "device_identity": identity(arm),
                "device_samples": [{"stage": stage, "residency_mib": {
                    bdf: (1 if stage == "during" else 0) for bdf in C.EXCLUDED_BY_ARM[arm]}}
                    for stage in ("before", "during", "after")],
                "excluded_device_residency_mib": {
                    bdf: 1 for bdf in C.EXCLUDED_BY_ARM[arm]}}


class ComparatorProducerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.server = self.root / "server"
        self.server.write_bytes(b"fake binary")
        self.canonical = self.root / "canonical"
        self.canonical.write_bytes(b"no-hook binary")

    def call(self, doc=None, runner=None, revalidate=None, accepted_canonical=None):
        for member in C.MODEL_MEMBERS:
            (self.root / member).write_bytes(b"fake model " + member.encode())
        hashes = {name: hashlib.sha256((self.root / name).read_bytes()).hexdigest()
                  for name in C.MODEL_MEMBERS}
        with patch.object(producer.C, "MODEL_DIR", self.root), patch.object(producer.C, "MODEL_MEMBER_SHA256", hashes), \
             patch.object(producer.C, "ACCEPTED_CANONICAL_VK_SERVER_SHA256", accepted_canonical or hashlib.sha256(self.canonical.read_bytes()).hexdigest()):
            return producer.run_phase3_producer(Path(__file__).resolve().parents[1],
                self.root / "out", self.server, phase2() if doc is None else doc,
                AUTH, FakeRunner() if runner is None else runner,
                revalidate_authority=(lambda a: a) if revalidate is None else revalidate,
                canonical_server=self.canonical)

    def test_requires_full_phase2_artifact_before_side_effects(self):
        runner = FakeRunner()
        with self.assertRaisesRegex(ValueError, "full Phase-2"):
            self.call(doc={"matched_ngl": 1}, runner=runner)
        self.assertFalse(runner.calls)
        self.assertFalse((self.root / "out").exists())

    def test_phase2_ladder_tamper_rejected_before_runner(self):
        doc = phase2()
        doc["rung_receipts"].pop()
        runner = FakeRunner()
        with self.assertRaisesRegex(ValueError, "raw rung receipts"):
            self.call(doc=doc, runner=runner)
        self.assertFalse(runner.calls)

    def test_all_cases_repeats_rows_logs_inertness_and_measured_times(self):
        runner = FakeRunner()
        result = self.call(runner=runner)
        self.assertEqual(result["cases"], list(C.FIXTURE_CASES))
        self.assertEqual(len(runner.calls), len(C.FIXTURE_CASES) * 8)
        for arm in ("B", "C"):
            self.assertEqual(set(result["measurements"][arm]), set(C.FIXTURE_CASES))
            self.assertTrue(all(x["wall_s"] >= 0 for x in result["measurements"][arm].values()))
        self.assertTrue(all(x["validated"] for x in result["pairs"]))
        self.assertTrue(all(x["deterministic"] for x in result["determinism"]))
        self.assertTrue(all(x["inert"] for x in result["inertness"]))
        self.assertEqual(result["inertness"][0]["canonical_server_sha256"],
                         hashlib.sha256(self.canonical.read_bytes()).hexdigest())
        self.assertEqual(result["inertness"][0]["disabled_tokens"], result["inertness"][0]["canonical_tokens"])
        self.assertTrue((self.root / "out" / result["inertness"][0]["canonical_response_path"]).is_file())
        for case in C.FIXTURE_CASES:
            self.assertEqual(len(list((self.root / "out" / case).glob("*.f32"))), 32)
            self.assertEqual(len(list((self.root / "out" / case).glob("*.server.log"))), 8)
            for arm, label in (("B", "baseline"), ("C", "candidate")):
                receipt = self.root / "out" / case / f"{arm}-{label}.run.json"
                self.assertTrue(receipt.is_file(), f"missing RUN_SCHEMA receipt {receipt}")
        measured = self.root / "out" / "measured-wall-times.json"
        self.assertTrue(measured.is_file())
        projection = practicality.project_from_measurements(measured)
        self.assertEqual(projection["matched_ngl"], C.LADDER_NGLS[-1])
        self.assertGreater(projection["sequential_total_s"], 0)

    def test_missing_rows_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "observer"):
            self.call(runner=FakeRunner(bad=True))

    def test_fake_process_or_device_evidence_cannot_be_substituted(self):
        class Bad(FakeRunner):
            def __call__(self, **kwargs):
                result = super().__call__(**kwargs)
                result.pop("process_attribution")
                return result
        with self.assertRaisesRegex(ValueError, "process attribution"):
            self.call(runner=Bad())
        class WrongDevice(FakeRunner):
            def __call__(self, **kwargs):
                result = super().__call__(**kwargs)
                result["device_identity"]["bdf"] = "00000000:09:00.0"
                return result
        with self.assertRaisesRegex(ValueError, "device identity"):
            self.call(runner=WrongDevice())
        class WrongExecutable(FakeRunner):
            def __call__(self, **kwargs):
                result = super().__call__(**kwargs)
                result["process_attribution"]["server_exe_sha256"] = "f" * 64
                return result
        with self.assertRaisesRegex(ValueError, "executed server"):
            self.call(runner=WrongExecutable())

    def test_missing_or_over_noise_excluded_samples_fail(self):
        class Missing(FakeRunner):
            def __call__(self, **kwargs):
                result = super().__call__(**kwargs)
                result["device_samples"] = []
                return result
        with self.assertRaisesRegex(ValueError, "device samples"):
            self.call(runner=Missing())
        class Noisy(FakeRunner):
            def __call__(self, **kwargs):
                result = super().__call__(**kwargs)
                bdf = next(iter(C.EXCLUDED_BY_ARM[kwargs["arm"]]))
                result["device_samples"][1]["residency_mib"][bdf] = 12
                return result
        with self.assertRaisesRegex(ValueError, "excluded"):
            self.call(runner=Noisy())

    def test_excluded_residency_is_delta_from_observed_idle_not_absolute(self):
        class Idle(FakeRunner):
            def __call__(self, **kwargs):
                result = super().__call__(**kwargs)
                bdf = next(iter(C.EXCLUDED_BY_ARM[kwargs["arm"]]))
                for sample, used in zip(result["device_samples"], (64, 65, 64)):
                    sample["residency_mib"][bdf] = used
                result.pop("excluded_device_residency_mib")
                return result
        self.call(runner=Idle())
        receipt = json.loads((self.root / "out" / C.FIXTURE_CASES[0] / "B-baseline.run.json").read_text())
        self.assertEqual(receipt["excluded_device_residency_mib"], {next(iter(C.EXCLUDED_BY_ARM["B"])): 1})

    def test_canonical_inertness_requires_exact_tokens_and_distinct_binary(self):
        class Drift(FakeRunner):
            def __call__(self, **kwargs):
                result = super().__call__(**kwargs)
                if kwargs["mode"] == "canonical":
                    result["tokens"][0] = 9
                    result["response_raw"] = json.dumps({"tokens": result["tokens"]}).encode()
                return result
        with self.assertRaisesRegex(ValueError, "inertness|comparator failed"):
            self.call(runner=Drift())
        self.assertFalse((self.root / "out" / "phase3.json").exists())

    def test_unaccepted_canonical_binary_rejected_before_runner(self):
        runner = FakeRunner()
        self.canonical.write_bytes(b"substituted no-hook binary")
        with self.assertRaisesRegex(ValueError, "accepted canonical"):
            self.call(runner=runner, accepted_canonical=hashlib.sha256(b"no-hook binary").hexdigest())
        self.assertFalse(runner.calls)

    def test_retained_rows_and_receipt_use_distinct_paths_and_actual_hashes(self):
        self.call(runner=FakeRunner())
        case = C.FIXTURE_CASES[0]
        base = self.root / "out" / case
        b = json.loads((base / "B-baseline.run.json").read_text())
        repeat = json.loads((base / "B-repeat.run.json").read_text())
        self.assertNotEqual(b["rows"]["0"]["path"], repeat["rows"]["0"]["path"])
        self.assertEqual(b["server_sha256"], hashlib.sha256(self.server.read_bytes()).hexdigest())
        self.assertEqual(b["model_members"], {name: hashlib.sha256((self.root / name).read_bytes()).hexdigest() for name in C.MODEL_MEMBERS})
        self.assertEqual(b["process_attribution"]["server_pid"], 1001)
        self.assertEqual(b["excluded_device_residency_mib"], {next(iter(C.EXCLUDED_BY_ARM["B"])): 1})
        self.assertTrue((self.root / "out" / b["rows"]["0"]["path"]).is_file())
        raw_meta = (self.root / "out" / b["observer_meta"]).read_bytes()
        self.assertEqual(hashlib.sha256(raw_meta).hexdigest(), b["observer_meta_sha256"])
        self.assertEqual(len(raw_meta.splitlines()), 8)
        self.assertEqual(json.loads((self.root / "out" / b["response_path"]).read_bytes())["tokens"], list(range(8)))

    def test_missing_hook_metadata_file_is_not_recreated_from_claims(self):
        class MissingMeta(FakeRunner):
            def __call__(self, **kwargs):
                result = super().__call__(**kwargs)
                Path(kwargs["env"]["LLAMA_OBSERVE_OUT"] + ".meta.json").unlink(missing_ok=True)
                return result
        with self.assertRaisesRegex(ValueError, "raw observer metadata"):
            self.call(runner=MissingMeta())

    def test_authority_revalidation_refusal_stops_before_runner(self):
        runner = FakeRunner()
        with self.assertRaisesRegex(ValueError, "authority"):
            self.call(runner=runner, revalidate=lambda a: {})
        self.assertFalse(runner.calls)

    def test_default_real_runner_and_timeout_contract(self):
        self.assertTrue(callable(producer._real_runner))
        self.assertIsNone(inspect.signature(producer.run_phase3_producer).parameters["runner"].default)
        self.assertIn("timeout_s", inspect.signature(producer.run_phase3_producer).parameters)

    def test_real_runner_fake_process_reads_live_attribution_samples_and_kills_group(self):
        class Process:
            pid = 4321
            returncode = None
            def poll(self): return self.returncode
            def wait(self, timeout): self.returncode = -15
        class HTTP:
            status = 200
            def __init__(self, payload): self.payload = payload
            def __enter__(self): return self
            def __exit__(self, *_): pass
            def read(self, *_): return self.payload
        process = Process(); killed = []
        def http(req, timeout):
            if isinstance(req, str): return HTTP(b"")
            return HTTP(json.dumps({"tokens": list(range(8))}).encode())
        argv = [str(self.server), "--port", "19000"]
        env = {"LLAMA_OBSERVE_LOG": str(self.root / "run.log")}
        with patch.object(producer, "_device_identity", return_value={"bdf": C.REFERENCE_ARM["bdf"]}), \
             patch.object(producer, "_device_sample", side_effect=lambda arm, stage: {"stage": stage}), \
             patch.object(producer, "_process_attribution", return_value={"server_pid": 4321, "server_argv": argv, "server_env": env, "server_exe_sha256": hashlib.sha256(self.server.read_bytes()).hexdigest()}), \
             patch.object(producer.subprocess, "Popen", return_value=process), \
             patch.object(producer.urllib.request, "urlopen", side_effect=http), \
             patch.object(producer.os, "killpg", side_effect=lambda pid, sig: killed.append((pid, sig))):
            row = producer._real_runner(argv=argv, env=env, arm="B", mode="baseline",
                request=C.REQUEST_CONTRACT, prompt="fixture", output_dir=self.root,
                timeout_s=10)
        self.assertEqual(row["process_attribution"]["server_pid"], 4321)
        self.assertEqual([s["stage"] for s in row["device_samples"]], ["before", "during", "after"])
        self.assertEqual(killed, [(4321, producer.signal.SIGTERM)])

    def test_real_runner_escalates_stuck_process_group_on_failure(self):
        class Stuck:
            pid = 2345
            returncode = None
            def poll(self): return None
            def wait(self, timeout):
                if timeout == 10: raise producer.subprocess.TimeoutExpired("server", timeout)
                self.returncode = -9
        class HTTP:
            status = 200
            def __enter__(self): return self
            def __exit__(self, *_): pass
        process = Stuck(); killed = []
        argv = [str(self.server), "--port", "19000"]
        env = {"LLAMA_OBSERVE_LOG": str(self.root / "run.log")}
        with patch.object(producer, "_device_identity", return_value={"bdf": C.REFERENCE_ARM["bdf"]}), \
             patch.object(producer, "_device_sample", return_value={"stage": "before"}), \
             patch.object(producer, "_process_attribution", side_effect=ValueError("proc unavailable")), \
             patch.object(producer.subprocess, "Popen", return_value=process), \
             patch.object(producer.urllib.request, "urlopen", return_value=HTTP()), \
             patch.object(producer.os, "killpg", side_effect=lambda pid, sig: killed.append((pid, sig))):
            with self.assertRaisesRegex(ValueError, "proc unavailable"):
                producer._real_runner(argv=argv, env=env, arm="B", mode="baseline",
                    request=C.REQUEST_CONTRACT, prompt="fixture", output_dir=self.root,
                    timeout_s=10)
        self.assertEqual(killed, [(2345, producer.signal.SIGTERM), (2345, producer.signal.SIGKILL)])

if __name__ == "__main__":
    unittest.main()
