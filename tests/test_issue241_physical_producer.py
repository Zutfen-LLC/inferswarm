"""CPU-only controls for the exact-head physical producer (no device access)."""
from __future__ import annotations

import hashlib
import inspect
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import issue241_constants as C
from scripts import issue241_placement as placement
from scripts import issue241_placement_producer as place_producer
from scripts import issue241_physical as physical
from scripts import issue241_dispatch as dispatch
from tests.test_issue241_placement_producer import (
    identity_observer, raw_identity_sources)

REPO = Path(__file__).resolve().parents[1]


def fake_identity(arm):
    """Identity observation satisfying the frozen predicate (test double)."""
    return identity_observer(arm)["identity"]


def telemetry_stub():
    return {"pid": 1234, "proc_status": ["VmRSS: 100 kB"],
            "proc_io": ["read_bytes: 1"],
            "request_timings": {"prompt_ms": 12.0, "decode_ms": 34.0},
            "process_measurements": {key: 1 for key in place_producer.MEASURED_FIELDS},
            "gpu_telemetry": {"source": "fake-runner", "samples": [{"raw": "sampled"}]},
            "excluded_device_residency_mib": {},
            "http_status": 200, "returncode": 0}


def valid_repeats(response_tokens=None, sha=None):
    tokens = response_tokens if response_tokens is not None else [11, 22, 33, 44, 55, 66, 77, 88]
    det_sha = placement.deterministic_output_sha256(tokens)
    return [{
        "index": i,
        "sane_completion": True,
        "response_tokens": list(tokens),
        "deterministic_output_sha256": det_sha,
        "response_raw": f"arm-ngl1{'' if i == 0 else f'.repeat{i}'}.response.json",
        "response_raw_sha256": sha or ("d" * 64),
        "raw_log": f"arm-ngl1{'' if i == 0 else f'.repeat{i}'}.server.log",
        "raw_log_sha256": "e" * 64,
        "raw_telemetry": f"arm-ngl1{'' if i == 0 else f'.repeat{i}'}.telemetry.json",
        "raw_telemetry_sha256": "f" * 64,
        "identity_pre": fake_identity("C"),
        "raw_identity_pre": f"arm-ngl1{'' if i == 0 else f'.repeat{i}'}.identity-pre.json",
        "raw_identity_pre_sha256": "1" * 64,
        "identity_post": fake_identity("C"),
        "raw_identity_post": f"arm-ngl1{'' if i == 0 else f'.repeat{i}'}.identity-post.json",
        "raw_identity_post_sha256": "2" * 64,
        "identity_post_health": place_producer._device_health("C", fake_identity("C")),
        "request_timings": {"prompt_ms": 1.0 + i, "decode_ms": 2.0 + i},
        "failure": None} for i in range(place_producer.RUNG_REPEATS)]


class PhysicalProducerControls(unittest.TestCase):
    def test_no_ambient_dispatch_authority(self):
        self.assertFalse(hasattr(physical, "_pending_authority"))
        self.assertFalse(hasattr(physical, "_gate"))

    def test_every_low_level_operation_requires_explicit_authority(self):
        for name in physical.GATED_OPERATION_ATTRS:
            function = getattr(physical, name)
            self.assertIn("authority", inspect.signature(function).parameters, name)
            with self.assertRaises((TypeError, ValueError, RuntimeError), msg=name):
                function()

    def test_denied_dispatch_has_no_execution_or_fixture_load(self):
        calls = []
        with mock.patch.object(dispatch, "require_live_dispatch", side_effect=ValueError("denied")):
            with mock.patch.object(physical, "_load_fixture_content", side_effect=lambda *a, **k: calls.append("fixture")):
                for name in physical.physical_entrypoints():
                    with self.assertRaises(ValueError):
                        getattr(physical, name)(REPO)
        self.assertEqual(calls, [])

    def test_phase3_requires_selected_phase2_before_any_execution(self):
        calls = []
        with mock.patch.object(dispatch, "require_live_dispatch", return_value={"head_sha": "a" * 40}):
            with mock.patch.object(physical, "_load_fixture_content", side_effect=lambda *a, **k: calls.append("fixture")):
                with self.assertRaises((ValueError, RuntimeError, TypeError)):
                    physical.run_phase3(REPO)
        self.assertEqual(calls, [])

    def test_phase1_raw_outputs_live_beneath_campaign_root(self):
        authority = {
            "schema": dispatch.AUTHORITY_SCHEMA, "head_sha": "a" * 40,
            "review_commit_id": "a" * 40, "dispatch_phrase": dispatch.DISPATCH_PHRASE,
            "pr_number": 242, "issue_number": 241,
        }
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with mock.patch.object(physical, "require_dispatch_authority", return_value=authority), \
                 mock.patch.object(physical, "_revalidate", return_value=authority), \
                 mock.patch.object(physical.host, "collect_census",
                     return_value={"census": {}, "verdict": {"validated": True}}) as census_call:
                physical.run_phase1(REPO, evidence_root=root, runner=object())
            self.assertEqual(census_call.call_args.kwargs["out_dir"], root / "phase1" / "census")

    def test_phase2_requires_valid_phase1_census_before_build(self):
        authority = {
            "schema": dispatch.AUTHORITY_SCHEMA, "head_sha": "a" * 40,
            "review_commit_id": "a" * 40,
            "dispatch_phrase": dispatch.DISPATCH_PHRASE,
            "pr_number": 242, "issue_number": 241,
        }
        with tempfile.TemporaryDirectory() as temp:
            with mock.patch.object(physical, "require_dispatch_authority", return_value=authority), \
                 mock.patch.object(physical, "_revalidate", return_value=authority), \
                 mock.patch.object(physical, "_build_server", return_value={"binary": {"path": "none"}}) as build, \
                 mock.patch.object(physical, "_placement_probe", return_value={"selected": {}}):
                with self.assertRaises(ValueError):
                    physical.run_phase2(REPO, evidence_root=Path(temp),
                                        source_tree=Path(temp), build_runner=object())
            build.assert_not_called()

    def test_phase1_raw_command_digest_tamper_blocks_phase2(self):
        from tests.test_issue241_r8i3_rx580 import make_census
        authority = {"schema": dispatch.AUTHORITY_SCHEMA, "head_sha": "a" * 40,
                     "review_commit_id": "a" * 40,
                     "dispatch_phrase": dispatch.DISPATCH_PHRASE,
                     "pr_number": 242, "issue_number": 241}
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "phase1"
            raw = root / "census" / "raw"
            raw.mkdir(parents=True)
            command = {"argv": ["hostname"], "returncode": 0, "stdout": "inferswarm01"}
            artifact = raw / "hostname.json"
            artifact.write_text(json.dumps(command))
            document = make_census()
            document.update(raw={"hostname": command},
                            raw_artifact_sha256={"hostname": hashlib.sha256(artifact.read_bytes()).hexdigest()},
                            out_dir=str(root / "census"))
            observed = {"census": document, "verdict": physical.census.validate_census(document)}
            receipt = physical._receipt("phase1-census", authority, census=observed)
            path = root / "census-receipt.json"
            path.write_text(json.dumps(receipt))
            self.assertEqual(physical._phase1_receipt(path, authority), receipt)
            artifact.write_text("{}")
            with self.assertRaises(ValueError):
                physical._phase1_receipt(path, authority)

    def test_phase3_build_receipt_binds_actual_launched_executable(self):
        authority = {
            "schema": dispatch.AUTHORITY_SCHEMA, "head_sha": "a" * 40,
            "review_commit_id": "a" * 40, "dispatch_phrase": dispatch.DISPATCH_PHRASE,
            "pr_number": 242, "issue_number": 241,
        }
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            server = root / "llama-server"
            server.write_bytes(b"built comparator binary")
            package = root / "package.tar"
            package.write_bytes(b"package")
            source = root / "tools/server/server-context.cpp"
            source.parent.mkdir(parents=True)
            source.write_bytes(b"patched source")
            doc = {"schema": "inferswarm.issue241.comparator-v2-build/1",
                   "dispatch_authority": authority, "producer_head_sha": authority["head_sha"],
                   "source_pin": C.LLAMA_CPP_PIN, "source_head": C.LLAMA_CPP_PIN,
                   "patched_source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                   "cmake_flags": C.OBSERVER_BUILD_FLAGS, "worktree": str(root),
                   "binary": {"path": str(server),
                              "sha256": hashlib.sha256(server.read_bytes()).hexdigest()},
                   "package": {"path": str(package),
                               "sha256": hashlib.sha256(package.read_bytes()).hexdigest()}}
            receipt = root / "build-receipt.json"
            receipt.write_text(json.dumps(doc))
            with mock.patch.object(physical.C, "OBSERVER_PATCHED_SOURCE_SHA256", doc["patched_source_sha256"]):
                self.assertEqual(physical._build_receipt(receipt, authority, server), doc)
                server.write_bytes(b"substituted")
                with self.assertRaises(ValueError):
                    physical._build_receipt(receipt, authority, server)
                server.write_bytes(b"built comparator binary")
                forged = {**authority, "head_sha": "b" * 40, "review_commit_id": "b" * 40}
                with self.assertRaises(ValueError):
                    physical._build_receipt(receipt, forged, server)

    def test_phase3_passes_selected_receipt_and_revalidation_to_producer(self):
        authority = {
            "schema": dispatch.AUTHORITY_SCHEMA, "head_sha": "a" * 40,
            "review_commit_id": "a" * 40,
            "dispatch_phrase": dispatch.DISPATCH_PHRASE,
            "pr_number": 242, "issue_number": 241,
        }
        selected = {"selected": {"matched_ngl": 4}}
        with mock.patch.object(physical, "require_dispatch_authority", return_value=authority), \
             mock.patch.object(physical, "_revalidate", return_value=authority), \
             mock.patch.object(physical, "_build_receipt", return_value={"binary": {"sha256": "a" * 64}}), \
             mock.patch.object(physical, "_selected_receipt", return_value=selected), \
             mock.patch.object(physical.cmp_producer, "run_phase3_producer",
                               return_value={"measurements": {"B": {}, "C": {}}}) as collect:
            receipt = physical.run_phase3(
                REPO, evidence_root=REPO.parent / "synthetic-only",
                selected_path=REPO.parent / "synthetic-only" / "phase2" / "phase2-placement-receipt.json", server=Path("server"),
                canonical_server=Path("canonical"))
        self.assertEqual(receipt["matched_ngl"], 4)
        self.assertEqual(collect.call_args.args[3], selected)
        self.assertTrue(callable(collect.call_args.kwargs["revalidate_authority"]))
        self.assertEqual(collect.call_args.kwargs["canonical_server"], Path("canonical"))

    def test_operations_use_real_execution_seam(self):
        source = inspect.getsource(physical)
        for name in ("_probe_devices", "_build_server", "_run_inference",
                     "_placement_probe"):
            function = getattr(physical, name)
            body = inspect.getsource(function)
            self.assertTrue(any(s in body for s in ("host.collect_census(",
                "host.build_comparator(", "place_producer.run_phase2_producer(",
                "cmp_producer.run_phase3_producer(")),
                f"{name} has no executable producer seam")
        self.assertNotIn("_pending_authority", source)


class PhaseLinkageControls(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.authority = {
            "schema": dispatch.AUTHORITY_SCHEMA, "head_sha": "a" * 40,
            "review_commit_id": "a" * 40,
            "dispatch_phrase": dispatch.DISPATCH_PHRASE,
            "pr_number": 242, "issue_number": 241,
        }
        self.rows = []
        by_arm = {"B": [], "C": []}
        for ngl in C.LADDER_NGLS:
            for arm in ("C", "B"):
                raw = (f"load_tensors: layer 0 assigned to device Vulkan0\n"
                       f"offloaded {ngl}/49 layers to GPU\n"
                       "Vulkan0 model buffer size = 393.43 MiB\n").encode()
                name = f"{arm}-ngl{ngl}.server.log"
                (self.root / name).write_bytes(raw)
                identity = fake_identity(arm)
                health = place_producer._device_health(arm, identity)
                telemetry = {"pid": 1234, "proc_status": ["VmRSS: 100 kB"],
                             "proc_io": ["read_bytes: 1"],
                             "request_timings": {"prompt_ms": 12.0, "decode_ms": 34.0},
                             "process_measurements": {key: 1 for key in place_producer.MEASURED_FIELDS},
                             "gpu_telemetry": {"source": "fake-runner", "samples": [{"raw": "sampled"}]},
                             "excluded_device_residency_mib": {
                                 bdf: 0 for bdf in C.EXCLUDED_BY_ARM[arm]},
                             "http_status": 200, "returncode": 0}
                telemetry_name = f"{arm}-ngl{ngl}.telemetry.json"
                telemetry_raw = (json.dumps(telemetry, sort_keys=True) + "\n").encode()
                (self.root / telemetry_name).write_bytes(telemetry_raw)
                repeats = []
                for repeat_index in range(place_producer.RUNG_REPEATS):
                    suffix = "" if repeat_index == 0 else f".repeat{repeat_index}"
                    # Timings deliberately differ per repeat: measurements
                    # must not feed the determinism predicate.
                    prompt_ms = 12.0 + repeat_index * 3.5
                    decode_ms = 34.0 + repeat_index * 5.25
                    tokens = [11, 22, 33, 44, 55, 66, 77, 88]
                    response_raw = json.dumps(
                        {"timings": {"prompt_ms": prompt_ms,
                                     "predicted_ms": decode_ms},
                         "tokens": tokens,
                         "incidental": {"served": repeat_index}}).encode()
                    if suffix:
                        rep_log_name = f"{arm}-ngl{ngl}{suffix}.server.log"
                        rep_tel_name = f"{arm}-ngl{ngl}{suffix}.telemetry.json"
                        (self.root / rep_log_name).write_bytes(raw)
                        stub = telemetry_stub()
                        stub["request_timings"] = {"prompt_ms": prompt_ms,
                                                   "decode_ms": decode_ms}
                        (self.root / rep_tel_name).write_bytes(
                            (json.dumps(stub, sort_keys=True) + "\n").encode())
                        rep_log_sha = hashlib.sha256(raw).hexdigest()
                        rep_tel_sha = hashlib.sha256(
                            (self.root / rep_tel_name).read_bytes()).hexdigest()
                        rep_resp_name = f"{arm}-ngl{ngl}{suffix}.response.json"
                        (self.root / rep_resp_name).write_bytes(response_raw)
                        rep_response_name = rep_resp_name
                    else:
                        rep_log_name = name
                        rep_tel_name = telemetry_name
                        rep_log_sha = hashlib.sha256(raw).hexdigest()
                        rep_tel_sha = hashlib.sha256(telemetry_raw).hexdigest()
                        rep_response_name = f"{arm}-ngl{ngl}.response.json"
                        (self.root / rep_response_name).write_bytes(response_raw)
                    # per-repeat RAW identity artifacts (pre and post)
                    rep_identity = {"index": repeat_index,
                                    "sane_completion": True,
                                    "response_tokens": tokens,
                                    "deterministic_output_sha256": placement.deterministic_output_sha256(tokens),
                                    "response_raw": rep_response_name,
                                    "response_raw_sha256": hashlib.sha256(response_raw).hexdigest(),
                                    "raw_log": rep_log_name,
                                    "raw_log_sha256": rep_log_sha,
                                    "raw_telemetry": rep_tel_name,
                                    "raw_telemetry_sha256": rep_tel_sha}
                    for stage, stage_label, stage_health in (
                            ("pre", "pre-execution", None),
                            ("post", "post-execution", health)):
                        obs_name = f"{arm}-ngl{ngl}{suffix}.identity-{stage}.json"
                        observation = {
                            "schema": place_producer.IDENTITY_OBSERVATION_SCHEMA,
                            "campaign": C.CAMPAIGN_ID, "arm": arm, "ngl": ngl,
                            "repeat_index": repeat_index,
                            "capture_stage": stage_label,
                            "raw": raw_identity_sources(arm),
                            "derived_identity": identity}
                        if stage_health is not None:
                            observation["derived_health"] = stage_health
                        (self.root / obs_name).write_bytes(
                            (json.dumps(observation, sort_keys=True) + "\n").encode())
                        obs_sha = hashlib.sha256(
                            (self.root / obs_name).read_bytes()).hexdigest()
                        rep_identity[f"raw_identity_{stage}"] = obs_name
                        rep_identity[f"raw_identity_{stage}_sha256"] = obs_sha
                        rep_identity[f"identity_{stage}"] = identity
                    rep_identity["identity_post_health"] = health
                    rep_identity["request_timings"] = {"prompt_ms": prompt_ms,
                                                       "decode_ms": decode_ms}
                    rep_identity["failure"] = None
                    repeats.append(rep_identity)
                rung = {"schema": placement.RUNG_SCHEMA, "arm": arm,
                        "ngl": ngl, "loaded": True,
                        "placement": placement.parse_placement(raw.decode()),
                        "excluded_device_residency_mib": {
                            bdf: 0 for bdf in C.EXCLUDED_BY_ARM[arm]},
                        "process_measurements": {key: 1 for key in place_producer.MEASURED_FIELDS},
                        "request_timings": {"prompt_ms": 12.0, "decode_ms": 34.0},
                        "device_identity": identity,
                        "post_execution_device_identity": fake_identity(arm),
                        "device_health": health,
                        "repeats": repeats}
                by_arm[arm].append(rung)
                self.rows.append({"arm": arm, "ngl": ngl, "raw_log": name,
                                  "raw_log_sha256": hashlib.sha256(raw).hexdigest(),
                                  "raw_telemetry": telemetry_name,
                                  "raw_telemetry_sha256": hashlib.sha256(telemetry_raw).hexdigest(),
                                  "raw_response": f"{arm}-ngl{ngl}.response.json",
                                  "raw_response_sha256": hashlib.sha256(
                                      (self.root / f"{arm}-ngl{ngl}.response.json").read_bytes()).hexdigest(),
                                  "process": telemetry,
                                  "repeats": repeats,
                                  "device_identity": identity,
                                  "post_execution_device_identity": rung["post_execution_device_identity"],
                                  "device_health": health,
                                  "verdict": placement.judge_rung(rung)})
        self.doc = {"schema": place_producer.SCHEMA,
                    "campaign": C.CAMPAIGN_ID, "authority": self.authority,
                    "rungs": by_arm, "rung_receipts": self.rows,
                    "selected": placement.select_matched_rung(by_arm)}
        self.path = self.root / "phase2-placement-receipt.json"

    def check(self):
        self.path.write_text(json.dumps(self.doc))
        return physical._selected_receipt(self.path, self.authority)

    def test_live_log_parses_to_judgeable_rung(self):
        parsed = placement.parse_placement(
            "offloaded 4/49 layers to GPU\nVulkan0 model buffer size = 393.43 MiB\n")
        rung = {"schema": placement.RUNG_SCHEMA, "arm": "C", "ngl": 4,
                "loaded": True, "placement": parsed,
                "excluded_device_residency_mib": {
                    bdf: 0 for bdf in C.EXCLUDED_BY_ARM["C"]},
                "process_measurements": {key: 1 for key in place_producer.MEASURED_FIELDS},
                "request_timings": {"prompt_ms": 12.0, "decode_ms": 34.0},
                "device_identity": fake_identity("C"),
                "post_execution_device_identity": fake_identity("C"),
                "device_health": place_producer._device_health("C", fake_identity("C")),
                "repeats": valid_repeats()}
        self.assertTrue(placement.judge_rung(rung)["valid"])

    def test_largest_common_rung_derived_from_measured_both_arms(self):
        self.assertEqual(self.check()["selected"]["matched_ngl"], C.LADDER_NGLS[-1])

    def test_one_arm_missing_is_rejected(self):
        self.doc["rung_receipts"].pop()
        with self.assertRaises(ValueError):
            self.check()

    def test_different_reference_rung_rejected(self):
        self.doc["rung_receipts"][1]["ngl"] = 2
        with self.assertRaises(ValueError):
            self.check()

    def test_unmeasured_synthetic_process_rejected(self):
        self.doc["rung_receipts"][0]["process"] = {"synthetic": True}
        with self.assertRaises(ValueError):
            self.check()

    def test_missing_raw_server_log_rejected(self):
        (self.root / self.rows[0]["raw_log"]).unlink()
        with self.assertRaises(ValueError):
            self.check()

    def test_tampered_raw_telemetry_rejected(self):
        (self.root / self.rows[0]["raw_telemetry"]).write_text("{}")
        with self.assertRaises(ValueError):
            self.check()

    def test_missing_or_tampered_raw_response_rejected(self):
        response = self.root / self.rows[0]["raw_response"]
        response.unlink()
        with self.assertRaises(ValueError):
            self.check()
        response.write_bytes(b"{}")
        with self.assertRaises(ValueError):
            self.check()

    def test_telemetry_summary_cross_binding_rejected(self):
        self.doc["rung_receipts"][0]["process"]["pid"] = 98765
        with self.assertRaises(ValueError):
            self.check()

    def test_forged_selected_ngl_rejected(self):
        self.doc["selected"]["matched_ngl"] = 1
        with self.assertRaises(ValueError):
            self.check()

    def test_wrong_dispatch_head_rejected(self):
        self.doc["authority"]["head_sha"] = "b" * 40
        with self.assertRaises((ValueError, RuntimeError)):
            self.check()

    # --- correction pass 5: per-repeat raw identity custody mutations ---

    def _repeat_paths(self, row_index=0):
        row = self.rows[row_index]
        return row, row["repeats"]

    def _refresh_verdict(self, row_index=0):
        """Competent forgers refresh every derivable summary: the rung
        verdict is recomputed from the (mutated) rung record too."""
        arm = self.doc["rung_receipts"][row_index]["arm"]
        rung = self.doc["rungs"][arm][row_index // 2]
        rung["repeats"] = self.doc["rung_receipts"][row_index]["repeats"]
        self.doc["rung_receipts"][row_index]["verdict"] = placement.judge_rung(rung)

    def test_missing_per_repeat_identity_artifact_rejected(self):
        row, _ = self._repeat_paths()
        target = self.root / row["repeats"][0]["raw_identity_pre"]
        target.unlink()
        with self.assertRaisesRegex(ValueError, "identity evidence missing"):
            self.check()

    def test_missing_first_repeat_identity_second_exists_rejected(self):
        row, _ = self._repeat_paths()
        (self.root / row["repeats"][0]["raw_identity_pre"]).unlink()
        # repeat 1 still has its own artifact; the FIRST repeat's missing
        # evidence must be what fails the receipt
        self.assertTrue((self.root / row["repeats"][1]["raw_identity_pre"]).is_file())
        with self.assertRaisesRegex(ValueError, "identity evidence missing"):
            self.check()

    def test_tampered_raw_identity_artifact_rejected(self):
        row, _ = self._repeat_paths()
        target = self.root / row["repeats"][1]["raw_identity_post"]
        doc = json.loads(target.read_text())
        doc["raw"]["sysfs"]["revision"] = "0xef"
        target.write_text(json.dumps(doc, sort_keys=True) + "\n")
        with self.assertRaisesRegex(ValueError, "identity artifact digest"):
            self.check()

    def test_forged_raw_identity_sha_rejected(self):
        row, _ = self._repeat_paths()
        self.doc["rung_receipts"][0]["repeats"][1]["raw_identity_pre_sha256"] = "a" * 64
        with self.assertRaisesRegex(ValueError, "identity artifact digest"):
            self.check()

    def test_coherent_raw_tamper_with_refreshed_sha_rejected(self):
        # competent forgery: change the raw subsystem value AND refresh the
        # artifact sha — the re-derivation/predicate boundary must fire
        row, _ = self._repeat_paths()
        target = self.root / row["repeats"][1]["raw_identity_pre"]
        doc = json.loads(target.read_text())
        doc["raw"]["sysfs"]["subsystem_device"] = "0xe387"
        target.write_text(json.dumps(doc, sort_keys=True) + "\n")
        self.doc["rung_receipts"][0]["repeats"][1]["raw_identity_pre_sha256"] = (
            hashlib.sha256(target.read_bytes()).hexdigest())
        with self.assertRaisesRegex(
                ValueError, "frozen-subject drift|derived identity differs"):
            self.check()

    def test_forged_derived_identity_inconsistent_with_raw_rejected(self):
        # coherent at the artifact level (raw unchanged) but the repeat
        # SUMMARY claims an identity the raw values do not support
        row, _ = self._repeat_paths()
        forged = json.loads(json.dumps(row["repeats"][1]["identity_pre"]))
        forged["revision"] = "ef"
        self.doc["rung_receipts"][0]["repeats"][1]["identity_pre"] = forged
        self._refresh_verdict()
        with self.assertRaisesRegex(
                ValueError, "identity summary differs|frozen-subject drift"):
            self.check()

    def test_identity_drift_first_repeat_correct_second_rejected(self):
        row, _ = self._repeat_paths()
        # rewrite repeat 0's pre artifact to a drifted-but-coherent board
        for rep_index in (0,):
            for stage in ("pre", "post"):
                target = self.root / row["repeats"][rep_index][f"raw_identity_{stage}"]
                doc = json.loads(target.read_text())
                doc["raw"]["sysfs"]["subsystem_device"] = "0xe387"
                doc["derived_identity"] = place_producer.derive_identity_from_raw(
                    "C", doc["raw"])
                if "derived_health" in doc:
                    doc["derived_health"] = place_producer._device_health(
                        "C", doc["derived_identity"])
                target.write_text(json.dumps(doc, sort_keys=True) + "\n")
                sha = hashlib.sha256(target.read_bytes()).hexdigest()
                rep = self.doc["rung_receipts"][0]["repeats"][rep_index]
                rep[f"raw_identity_{stage}_sha256"] = sha
                rep[f"identity_{stage}"] = doc["derived_identity"]
                if "derived_health" in doc:
                    rep["identity_post_health"] = doc["derived_health"]
        # rung aggregates follow repeat 0 pre / last post
        self.doc["rung_receipts"][0]["device_identity"] = (
            self.doc["rung_receipts"][0]["repeats"][0]["identity_pre"])
        for records in (self.doc["rungs"]["C"], self.doc["rung_receipts"]):
            records[0]["device_identity"] = (
                self.doc["rung_receipts"][0]["repeats"][0]["identity_pre"])
        self._refresh_verdict()
        with self.assertRaisesRegex(ValueError, "frozen-subject drift"):
            self.check()

    def test_forged_healthy_summary_inconsistent_with_raw_rejected(self):
        row, _ = self._repeat_paths()
        # raw post artifact says the device vanished; summaries claim healthy
        target = self.root / row["repeats"][1]["raw_identity_post"]
        doc = json.loads(target.read_text())
        doc["raw"] = {"sysfs_present": False}
        doc["derived_identity"] = place_producer.derive_identity_from_raw("C", doc["raw"])
        doc["derived_health"] = place_producer._device_health("C", doc["derived_identity"])
        target.write_text(json.dumps(doc, sort_keys=True) + "\n")
        sha = hashlib.sha256(target.read_bytes()).hexdigest()
        rep = self.doc["rung_receipts"][0]["repeats"][1]
        rep["raw_identity_post_sha256"] = sha
        with self.assertRaisesRegex(
                ValueError, "identity summary differs|frozen-subject drift|"
                            "health summary differs|health disposition"):
            self.check()

    def test_wrong_identity_artifact_binding_rejected(self):
        row, _ = self._repeat_paths()
        target = self.root / row["repeats"][1]["raw_identity_pre"]
        doc = json.loads(target.read_text())
        doc["repeat_index"] = 0  # claims to be repeat 0's observation
        target.write_text(json.dumps(doc, sort_keys=True) + "\n")
        self.doc["rung_receipts"][0]["repeats"][1]["raw_identity_pre_sha256"] = (
            hashlib.sha256(target.read_bytes()).hexdigest())
        with self.assertRaisesRegex(ValueError, "binding invalid"):
            self.check()

    def test_traversal_identity_path_rejected(self):
        for bad in ("../escape.json", "/abs/path.json", "."):
            with self.subTest(bad=bad):
                self.doc["rung_receipts"][0]["repeats"][0]["raw_identity_pre"] = bad
                with self.assertRaises(ValueError):
                    self.check()

    def test_symlink_identity_artifact_rejected(self):
        row, _ = self._repeat_paths()
        target = self.root / row["repeats"][0]["raw_identity_pre"]
        real = target.read_bytes()
        payload = json.loads(real)
        outside = self.root.parent / "outside-identity.json"
        outside.write_bytes(real)
        target.unlink()
        target.symlink_to(outside)
        with self.assertRaisesRegex(ValueError, "missing/aliased|symlink"):
            self.check()
        target.unlink()
        target.write_bytes(real)
        payload = None  # silence linter

    def test_variable_timings_same_tokens_pass_determinism(self):
        # staged fixture carries DIFFERENT timings/metadata per repeat with
        # identical tokens: the receipt must validate the determinism
        first = self.rows[0]["repeats"][0]
        second = self.rows[0]["repeats"][1]
        self.assertNotEqual(first["request_timings"], second["request_timings"])
        self.assertNotEqual(first["response_raw_sha256"], second["response_raw_sha256"])
        self.assertEqual(first["deterministic_output_sha256"],
                         second["deterministic_output_sha256"])
        selected = self.check()
        self.assertEqual(selected["selected"]["matched_ngl"], C.LADDER_NGLS[-1])

    def test_one_changed_token_fails_selected_receipt(self):
        # competent token forgery: mutate repeat 1's tokens, refresh the
        # claimed digest AND the retained response bytes
        row, _ = self._repeat_paths()
        rep = self.doc["rung_receipts"][0]["repeats"][1]
        tokens = [99] + list(rep["response_tokens"])[1:]
        rep["response_tokens"] = tokens
        rep["deterministic_output_sha256"] = placement.deterministic_output_sha256(tokens)
        response_path = self.root / rep["response_raw"]
        doc = json.loads(response_path.read_text())
        doc["tokens"] = tokens
        raw = json.dumps(doc).encode()
        response_path.write_bytes(raw)
        rep["response_raw_sha256"] = hashlib.sha256(raw).hexdigest()
        self._refresh_verdict()
        with self.assertRaisesRegex(
                ValueError, "determinism does not hold|canonical token"):
            self.check()

    def test_forged_deterministic_output_claim_rejected(self):
        rep = self.doc["rung_receipts"][0]["repeats"][1]
        rep["deterministic_output_sha256"] = "a" * 64
        self._refresh_verdict()
        with self.assertRaisesRegex(
                ValueError, "deterministic-output digest claim"):
            self.check()

    def test_forged_token_summary_differs_from_raw_response_rejected(self):
        rep = self.doc["rung_receipts"][0]["repeats"][1]
        tokens = list(rep["response_tokens"])
        tokens[0] += 1
        rep["response_tokens"] = tokens
        # claimed digest follows the forged summary; the RAW response bytes
        # still carry the original tokens — summary-vs-raw must fire
        rep["deterministic_output_sha256"] = placement.deterministic_output_sha256(tokens)
        self._refresh_verdict()
        with self.assertRaisesRegex(
                ValueError, "summary differs|sane-completion"):
            self.check()


if __name__ == "__main__":
    unittest.main()
