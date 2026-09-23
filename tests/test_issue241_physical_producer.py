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

REPO = Path(__file__).resolve().parents[1]


def fake_identity(arm):
    """Identity observation satisfying the frozen predicate (test double)."""
    cfg = C.REFERENCE_ARM if arm == "B" else C.CANDIDATE_ARM
    ident = {k: cfg[k] for k in (
        "bdf", "vendor_id", "device_id", "pci_id", "subsystem_vendor_id",
        "subsystem_device_id", "revision", "link_width", "max_link_width",
        "max_link_speed", "vulkan_device_name", "vulkan_device_uuid")}
    ident["vulkan_icd"] = cfg["icd"]
    ident["driver_in_use"] = cfg["kernel_driver"]
    ident["link_speed"] = "2.5 GT/s" if arm == "B" else "8.0 GT/s"
    ident["selected_device_present"] = True
    if arm == "B":
        ident["gpu_uuid"] = cfg["gpu_uuid"]
    else:
        ident["vram_mib"] = C.CANDIDATE_VRAM_CENSUS_MIB
    return ident


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
    return [{
        "index": i,
        "sane_completion": True,
        "response_tokens": list(tokens),
        "response_raw": f"arm-ngl1{'' if i == 0 else f'.repeat{i}'}.response.json",
        "response_raw_sha256": sha or ("d" * 64),
        "raw_log": f"arm-ngl1{'' if i == 0 else f'.repeat{i}'}.server.log",
        "raw_log_sha256": "e" * 64,
        "raw_telemetry": f"arm-ngl1{'' if i == 0 else f'.repeat{i}'}.telemetry.json",
        "raw_telemetry_sha256": "f" * 64,
        "request_timings": {"prompt_ms": 1.0, "decode_ms": 2.0},
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
                health = {"fatal_states": [], "observed": dict(identity)}
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
                response_name = f"{arm}-ngl{ngl}.response.json"
                response_raw = json.dumps({"timings": {"prompt_ms": 12.0,
                                                      "predicted_ms": 34.0},
                                           "tokens": [11, 22, 33, 44, 55, 66, 77, 88]}).encode()
                (self.root / response_name).write_bytes(response_raw)
                repeats = []
                for repeat_index in range(place_producer.RUNG_REPEATS):
                    suffix = "" if repeat_index == 0 else f".repeat{repeat_index}"
                    if suffix:
                        rep_log_name = f"{arm}-ngl{ngl}{suffix}.server.log"
                        rep_tel_name = f"{arm}-ngl{ngl}{suffix}.telemetry.json"
                        (self.root / rep_log_name).write_bytes(raw)
                        (self.root / rep_tel_name).write_bytes(
                            (json.dumps(telemetry_stub(), sort_keys=True) + "\n").encode())
                        rep_log_sha = hashlib.sha256(raw).hexdigest()
                        rep_tel_sha = hashlib.sha256(
                            (self.root / rep_tel_name).read_bytes()).hexdigest()
                    else:
                        rep_log_name = name
                        rep_tel_name = telemetry_name
                        rep_log_sha = hashlib.sha256(raw).hexdigest()
                        rep_tel_sha = hashlib.sha256(telemetry_raw).hexdigest()
                    repeats.append({
                        "index": repeat_index,
                        "sane_completion": True,
                        "response_tokens": [11, 22, 33, 44, 55, 66, 77, 88],
                        "response_raw": response_name if not suffix else f"{arm}-ngl{ngl}{suffix}.response.json",
                        "response_raw_sha256": hashlib.sha256(response_raw).hexdigest(),
                        "raw_log": rep_log_name,
                        "raw_log_sha256": rep_log_sha,
                        "raw_telemetry": rep_tel_name,
                        "raw_telemetry_sha256": rep_tel_sha,
                        "request_timings": {"prompt_ms": 12.0, "decode_ms": 34.0},
                        "failure": None})
                    if suffix:
                        rep_resp_name = f"{arm}-ngl{ngl}{suffix}.response.json"
                        (self.root / rep_resp_name).write_bytes(response_raw)
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
                                  "raw_response": response_name,
                                  "raw_response_sha256": hashlib.sha256(response_raw).hexdigest(),
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
                "device_health": {"fatal_states": [], "observed": fake_identity("C")},
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


if __name__ == "__main__":
    unittest.main()
