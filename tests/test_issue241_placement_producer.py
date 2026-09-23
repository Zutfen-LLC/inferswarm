"""CPU-only Phase-2 controls: no process, model, device or host commands."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import issue241_constants as C
from scripts import issue241_census as census
from scripts import issue241_dispatch as dispatch
from scripts import issue241_physical as physical
from scripts import issue241_placement_producer as producer

ROOT = Path(__file__).resolve().parents[1]

VULKAN_SUMMARY = {
    "B": ("GPU0:\n"
          "        apiVersion         = 1.4.341\n"
          "        deviceName         = NVIDIA GeForce RTX 3060\n"
          "        deviceUUID         = d5c05739-96c1-7e49-89b6-bf54c2121c55\n"),
    "C": ("GPU0:\n"
          "        apiVersion         = 1.4.305\n"
          "        deviceName         = AMD Radeon RX 580 Series (RADV POLARIS10)\n"
          "        deviceUUID         = 00000000-0200-0000-0000-000000000000\n"),
}


def raw_identity_sources(arm, **overrides):
    """RAW per-repeat identity source values (kernel spellings) for the
    frozen subject — the same shape _observe_arm_identity reads live."""
    cfg = C.REFERENCE_ARM if arm == "B" else C.CANDIDATE_ARM
    raw = {"sysfs_present": True, "sysfs": {
        "vendor": "0x" + cfg["vendor_id"],
        "device": "0x" + cfg["device_id"],
        "subsystem_vendor": "0x" + cfg["subsystem_vendor_id"],
        "subsystem_device": "0x" + cfg["subsystem_device_id"],
        "revision": "0x" + cfg["revision"],
        "current_link_width": cfg["link_width"][1:],
        "current_link_speed": "2.5 GT/s PCIe" if arm == "B" else "8.0 GT/s PCIe",
        "max_link_width": cfg["max_link_width"][1:],
        "max_link_speed": cfg["max_link_speed"] + " PCIe",
        "driver": cfg["kernel_driver"]},
        "nvidia_smi": (f"{cfg['gpu_uuid']}, {cfg['bdf']}\n" if arm == "B" else ""),
        "vulkaninfo_summary": VULKAN_SUMMARY[arm]}
    if arm == "C":
        raw["amd_vram_total_bytes"] = C.CANDIDATE_VRAM_CENSUS_MIB * 1024 * 1024
    raw["sysfs"].update(overrides)
    return raw


def identity_observer(arm):
    """Observer seam double returning {raw, identity} with the identity
    mechanically derived from the raw sources (satisfies the frozen
    predicate; same contract as the live _observe_arm_identity)."""
    raw = raw_identity_sources(arm)
    return {"raw": raw, "identity": producer.derive_identity_from_raw(arm, raw)}


def fake_identity(arm):
    """Derived identity observation satisfying the frozen predicate."""
    return identity_observer(arm)["identity"]


def authority():
    return {"schema": dispatch.AUTHORITY_SCHEMA, "head_sha": "a" * 40,
            "review_commit_id": "a" * 40, "review_id": 123,
            "pr_number": 242, "issue_number": 241,
            "dispatch_phrase": dispatch.DISPATCH_PHRASE}


class PlacementProducerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def measured(self, arm, ngl, repeat_index=0):
        bdf = next(iter(C.EXCLUDED_BY_ARM[arm]))
        tokens = [11, 22, 33, 44, 55, 66, 77, 88]
        # Timings DELIBERATELY DIFFER between repeats: they are measured
        # quantities and must not feed the determinism predicate.
        prompt_ms = 12.0 + repeat_index * 7.5
        decode_ms = 34.0 + repeat_index * 11.25
        return {"pid": 100 + ngl, "returncode": 0, "http_status": 200,
                "response_raw": json.dumps({"timings": {"prompt_ms": prompt_ms,
                                                        "predicted_ms": decode_ms},
                                            "tokens": tokens,
                                            "extra_incidental": {"served": repeat_index}}).encode(),
                "request_timings": {"prompt_ms": prompt_ms, "decode_ms": decode_ms},
                "proc_status": ["VmRSS: 400 kB\nRssFile: 150 kB\nRssAnon: 200 kB\nVmSwap: 3 kB"],
                "proc_io": ["read_bytes: 1024\nrchar: 2048"],
                "process_measurements": {"rss_file_kib": 150, "rss_anon_kib": 200,
                    "swap_kib": 3, "physical_read_bytes": 1024, "major_faults": 2},
                "gpu_telemetry": {"source": "injected-sample", "samples": [
                    {"proc": {"pid": 100 + ngl}, "device": {"nvidia": {}, "amd": {}}}]},
                "excluded_device_residency_mib": {bdf: 4}}

    def fake(self, events, *, excluded=4):
        state = {"repeat": 0}
        def runner(argv, *, arm, ngl, log_path, authority, **kwargs):
            events.append((arm, ngl, authority["head_sha"]))
            log_path.write_text(
                "load_tensors: layer 0 assigned to device Vulkan0\n"
                f"offloaded {ngl}/49 layers to GPU\n"
                f"Vulkan0 model buffer size = {300 if arm == 'C' else 200} MiB\n")
            result = self.measured(arm, ngl, repeat_index=state["repeat"])
            result["excluded_device_residency_mib"] = {
                next(iter(C.EXCLUDED_BY_ARM[arm])): excluded}
            state["repeat"] += 1
            return result
        return runner

    def test_both_arms_and_raw_log_telemetry_custody(self):
        events = []
        receipt = producer.run_phase2_producer(
            ROOT, self.root, Path("/srv/fake-server"), authority(),
            runner=self.fake(events), revalidate_authority=lambda a: a,
            identity_observer=identity_observer)
        self.assertEqual([(arm, ngl) for arm, ngl, _ in events],
                         [(arm, ngl) for ngl in C.LADDER_NGLS for arm in ("C", "B")
                          for _ in range(producer.RUNG_REPEATS)])
        self.assertEqual(receipt["selected"]["matched_ngl"], C.LADDER_NGLS[-1])
        for row in receipt["rung_receipts"]:
            self.assertEqual(set(receipt["rungs"][row["arm"]][C.LADDER_NGLS.index(row["ngl"])][
                "excluded_device_residency_mib"]), C.EXCLUDED_BY_ARM[row["arm"]])
            for name, sha in (("raw_log", "raw_log_sha256"),
                              ("raw_telemetry", "raw_telemetry_sha256")):
                self.assertEqual(hashlib.sha256((self.root / row[name]).read_bytes()).hexdigest(), row[sha])
            self.assertEqual(row["process"]["process_measurements"]["major_faults"], 2)
        self.assertEqual(json.loads((self.root / "phase2-placement-receipt.json").read_text()), receipt)
        with mock.patch.object(physical, "_head", return_value="a" * 40):
            self.assertEqual(physical._selected_receipt(
                self.root / "phase2-placement-receipt.json", authority())["selected"], receipt["selected"])

    def test_excluded_residency_over_noise_invalidates_rung(self):
        receipt = producer.run_phase2_producer(
            ROOT, self.root, Path("fake"), authority(), runner=self.fake([], excluded=9),
            revalidate_authority=lambda a: a, identity_observer=identity_observer)
        self.assertTrue(receipt["selected"]["placement_blocked"])
        self.assertIsNone(receipt["selected"]["matched_ngl"])

    def test_failed_startup_http_and_timeout_keep_diagnostics_and_continue(self):
        events = []
        failures = {("C", C.LADDER_NGLS[-1]): ("startup failure", -1, None),
                    ("B", C.LADDER_NGLS[-2]): ("HTTP 503", -15, 503),
                    ("C", C.LADDER_NGLS[1]): ("request timeout", -15, None)}
        def runner(argv, *, arm, ngl, log_path, **kwargs):
            result = self.fake(events)(argv, arm=arm, ngl=ngl, log_path=log_path, **kwargs)
            result["argv"] = argv
            if (arm, ngl) in failures:
                reason, rc, status = failures[arm, ngl]
                result.update(failure=reason, returncode=rc, http_status=status)
                log_path.write_text(f"server failure: {reason}\n")
            return result
        receipt = producer.run_phase2_producer(
            ROOT, self.root, Path("fake"), authority(), runner=runner,
            revalidate_authority=lambda a: a, identity_observer=identity_observer)
        self.assertEqual([(arm, ngl) for arm, ngl, _ in events],
                         [(arm, ngl) for ngl in C.LADDER_NGLS for arm in ("C", "B")
                          for _ in range(producer.RUNG_REPEATS)])
        self.assertEqual(receipt["selected"]["matched_ngl"], C.LADDER_NGLS[-3])
        for row in receipt["rung_receipts"]:
            if (row["arm"], row["ngl"]) in failures:
                self.assertFalse(receipt["rungs"][row["arm"]][C.LADDER_NGLS.index(row["ngl"])]["loaded"])
                self.assertIn("failure", row["process"])
                self.assertEqual(row["process"], json.loads((self.root / row["raw_telemetry"]).read_text()))
        with mock.patch.object(physical, "_head", return_value="a" * 40):
            self.assertEqual(physical._selected_receipt(
                self.root / "phase2-placement-receipt.json", authority())["selected"], receipt["selected"])

    def test_sparse_observed_failure_is_not_filled_with_synthetic_counters(self):
        events = []
        def runner(argv, *, arm, ngl, log_path, **kwargs):
            if (arm, ngl) == ("C", C.LADDER_NGLS[-1]):
                events.append((arm, ngl, kwargs["authority"]["head_sha"]))
                log_path.write_text("startup failed before first process sample\n")
                return {"pid": 901, "argv": argv, "returncode": 1,
                        "http_status": None, "failure": "server exited before health check",
                        "proc_status": [], "proc_io": [],
                        "gpu_telemetry": {"source": "live-device-samples", "samples": []},
                        "process_measurements": {}, "excluded_device_residency_mib": {}}
            return self.fake(events)(argv, arm=arm, ngl=ngl, log_path=log_path, **kwargs)
        receipt = producer.run_phase2_producer(
            ROOT, self.root, Path("fake"), authority(), runner=runner,
            revalidate_authority=lambda a: a, identity_observer=identity_observer)
        self.assertEqual(len(events), len(C.LADDER_NGLS) * 2 * producer.RUNG_REPEATS)
        self.assertEqual(receipt["selected"]["matched_ngl"], C.LADDER_NGLS[-2])
        row = next(r for r in receipt["rung_receipts"] if r["arm"] == "C" and r["ngl"] == C.LADDER_NGLS[-1])
        self.assertEqual(row["process"]["process_measurements"], {})
        self.assertEqual(row["process"]["excluded_device_residency_mib"], {})
        with mock.patch.object(physical, "_head", return_value="a" * 40):
            selected = physical._selected_receipt(self.root / "phase2-placement-receipt.json", authority())
            self.assertEqual(selected["selected"]["matched_ngl"], C.LADDER_NGLS[-2])

    def test_spawn_failure_has_no_fabricated_pid_and_still_completes_ladder(self):
        events = []
        def runner(argv, *, arm, ngl, log_path, **kwargs):
            if (arm, ngl) == ("C", C.LADDER_NGLS[-1]):
                events.append((arm, ngl, kwargs["authority"]["head_sha"]))
                log_path.write_bytes(b"")
                return {"pid": None, "argv": argv, "returncode": None,
                        "http_status": None, "spawn_failure": True,
                        "failure": "server spawn failed: FileNotFoundError",
                        "proc_status": [], "proc_io": [],
                        "gpu_telemetry": {"source": "live-device-samples", "samples": []},
                        "process_measurements": {}, "excluded_device_residency_mib": {}}
            return self.fake(events)(argv, arm=arm, ngl=ngl, log_path=log_path, **kwargs)
        receipt = producer.run_phase2_producer(
            ROOT, self.root, Path("fake"), authority(), runner=runner,
            revalidate_authority=lambda a: a, identity_observer=identity_observer)
        self.assertEqual(len(events), len(C.LADDER_NGLS) * 2 * producer.RUNG_REPEATS)
        self.assertEqual(receipt["selected"]["matched_ngl"], C.LADDER_NGLS[-2])
        self.assertIsNone(receipt["rung_receipts"][-2]["process"]["pid"])

    def test_success_cannot_be_claimed_from_http_failure_even_with_zero_returncode(self):
        events = []
        def runner(argv, *, arm, ngl, log_path, **kwargs):
            result = self.fake(events)(argv, arm=arm, ngl=ngl, log_path=log_path, **kwargs)
            if (arm, ngl) == ("B", C.LADDER_NGLS[-1]):
                result.update(http_status=503, failure="HTTP 503")
            return result
        receipt = producer.run_phase2_producer(
            ROOT, self.root, Path("fake"), authority(), runner=runner,
            revalidate_authority=lambda a: a, identity_observer=identity_observer)
        self.assertEqual(receipt["selected"]["matched_ngl"], C.LADDER_NGLS[-2])
        self.assertFalse(receipt["rungs"]["B"][-1]["loaded"])
        with mock.patch.object(physical, "_head", return_value="a" * 40):
            selected = physical._selected_receipt(self.root / "phase2-placement-receipt.json", authority())
            self.assertEqual(selected["selected"]["matched_ngl"], C.LADDER_NGLS[-2])

    def test_empty_failure_log_is_retained_but_unexpected_runner_error_stops(self):
        events = []
        def runner(argv, *, arm, ngl, log_path, **kwargs):
            result = self.fake(events)(argv, arm=arm, ngl=ngl, log_path=log_path, **kwargs)
            if (arm, ngl) == ("C", C.LADDER_NGLS[0]):
                log_path.write_bytes(b"")
                result.update(returncode=1, http_status=None, failure="startup exited")
            return result
        receipt = producer.run_phase2_producer(
            ROOT, self.root, Path("fake"), authority(), runner=runner,
            revalidate_authority=lambda a: a, identity_observer=identity_observer)
        self.assertFalse(receipt["rungs"]["C"][0]["loaded"])
        self.assertEqual(receipt["rung_receipts"][0]["raw_log_sha256"], hashlib.sha256(b"").hexdigest())
        with tempfile.TemporaryDirectory() as other:
            def broken(argv, *, log_path, **kwargs):
                log_path.write_text("partial observed log\n")
                raise KeyError("unexpected fake runner defect")
            with self.assertRaisesRegex(KeyError, "unexpected fake runner defect"):
                producer.run_phase2_producer(ROOT, Path(other), Path("fake"), authority(),
                    runner=broken, revalidate_authority=lambda a: a, identity_observer=identity_observer)
            self.assertFalse((Path(other) / "phase2-placement-receipt.json").exists())

    def test_missing_excluded_and_process_measurements_fail_closed(self):
        for mutation in (lambda r: r.pop("excluded_device_residency_mib"),
                         lambda r: r.__setitem__("excluded_device_residency_mib", {}),
                         lambda r: r.pop("process_measurements"),
                         lambda r: r["process_measurements"].pop("major_faults")):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as d:
                def runner(*args, **kwargs):
                    original = self.fake([])(*args, **kwargs)
                    mutation(original)
                    return original
                with self.assertRaisesRegex(ValueError, "excluded|measurement|fault"):
                    producer.run_phase2_producer(ROOT, Path(d), Path("fake"), authority(),
                        runner=runner, revalidate_authority=lambda a: a,
            identity_observer=identity_observer)

    def test_authority_revalidated_before_each_arm_and_drift_stops(self):
        events = []
        validations = []
        def revalidate(a):
            validations.append(a["head_sha"])
            if len(validations) == 3:
                return {**a, "head_sha": "b" * 40}
            return a
        with self.assertRaisesRegex((ValueError, RuntimeError), "authority|dispatch|head"):
            producer.run_phase2_producer(ROOT, self.root, Path("fake"), authority(),
                runner=self.fake(events), revalidate_authority=revalidate)
        self.assertEqual(len(events), 1)
        self.assertFalse((self.root / "phase2-placement-receipt.json").exists())

    def test_missing_revalidator_or_malformed_authority_never_runs(self):
        for auth, check in ((None, lambda a: a), ({"schema": "test"}, lambda a: a),
                            (authority(), None)):
            with self.subTest(auth=auth, check=check):
                called = []
                with self.assertRaisesRegex((ValueError, RuntimeError), "authority|dispatch"):
                    producer.run_phase2_producer(ROOT, self.root, Path("fake"), auth,
                        runner=self.fake(called), revalidate_authority=check,
                        identity_observer=identity_observer)
                self.assertEqual(called, [])

    def test_missing_raw_log_and_synthetic_measurement_rejected(self):
        def no_log(*args, **kwargs):
            return {**self.measured("C", 1), "synthetic": True}
        with self.assertRaisesRegex(ValueError, "synthetic|log"):
            producer.run_phase2_producer(ROOT, self.root, Path("fake"), authority(),
                runner=no_log, revalidate_authority=lambda a: a, identity_observer=identity_observer)

    def test_receipt_is_no_clobber_and_no_partial_summary(self):
        target = self.root / "phase2-placement-receipt.json"
        target.write_text("prior")
        with self.assertRaisesRegex(ValueError, "overwrite|exists|receipt"):
            producer.run_phase2_producer(ROOT, self.root, Path("fake"), authority(),
                runner=self.fake([]), revalidate_authority=lambda a: a, identity_observer=identity_observer)
        self.assertEqual(target.read_text(), "prior")

    def test_runner_receives_hash_verified_historical_prompt_not_generic_text(self):
        seen = []
        def runner(argv, *, arm, ngl, log_path, prompt_tokens, **kwargs):
            seen.append(prompt_tokens)
            return self.fake([])(argv, arm=arm, ngl=ngl, log_path=log_path, **kwargs)
        producer.run_phase2_producer(ROOT, self.root, Path("fake"), authority(),
            runner=runner, revalidate_authority=lambda a: a,
            identity_observer=identity_observer)
        fixture = C.load_fixtures(ROOT)["case-256"]["prompt_token_ids"]
        self.assertEqual(len(seen), len(C.LADDER_NGLS) * 2 * producer.RUNG_REPEATS)
        self.assertTrue(all(tokens == fixture for tokens in seen))

    def test_residency_uses_measured_device_bdf_and_fails_when_missing(self):
        sample = {"nvidia": {C.REFERENCE_ARM["bdf"]: {"uuid": C.REFERENCE_ARM["gpu_uuid"],
                       "used_mib": 11}},
                  "amd": {C.CANDIDATE_ARM["bdf"]: {"vram_used_bytes": 5 * 1024 * 1024}}}
        self.assertEqual(producer._residency(sample, C.REFERENCE_ARM["bdf"]), 11)
        self.assertEqual(producer._residency(sample, C.CANDIDATE_ARM["bdf"]), 5)
        with self.assertRaisesRegex(RuntimeError, "not observed"):
            producer._residency(sample, "00000000:04:00.0")

    def test_process_snapshot_parses_live_kernel_fields(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "status").write_text("VmRSS:\t500 kB\nRssFile:\t100 kB\nRssAnon:\t300 kB\nVmSwap:\t10 kB\n")
            (root / "io").write_text("read_bytes: 4096\nrchar: 9000\n")
            (root / "stat").write_text("123 (llama server) S " + " ".join(["0"] * 8 + ["7"] + ["0"] * 31))
            (root / "cmdline").write_bytes(b"llama\0--model\0")
            with mock.patch.object(producer, "_proc_root", return_value=root):
                sample = producer._proc_snapshot(123)
            self.assertEqual(sample["rss_file_kib"], 100)
            self.assertEqual(sample["rss_anon_kib"], 300)
            self.assertEqual(sample["swap_kib"], 10)
            self.assertEqual(sample["physical_read_bytes"], 4096)
            self.assertEqual(sample["major_faults"], 7)

if __name__ == "__main__":
    unittest.main()
