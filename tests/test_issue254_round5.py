"""Round-5 RED/GREEN regressions: enum-free A3 placement/mechanism law +
pre-publication failure quarantine (METHODOLOGY-AMENDMENT-005, issue #254).

Physical defect class (second A3 attempt, dispatched head a090c41): the
retained server-log stream of this instrument carries NO ggml_vulkan
device-enumeration banner, so the exact enum-line requirement made every
physically real unit fail placement after successful inference, and the
scratch cleanup destroyed the only diagnostic server.log. The committed
RED anchors in this module reproduce both halves of that defect against
the a090c41 law (kept as one-time run RED probes at the pre-correction
head; at the corrected head they assert the GREEN law).
"""
from __future__ import annotations
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.test_issue254_producer import (
    ProducerFixtureMixin, ENUM_LINE, MECH_A3_LOG, NL)
from tests.test_issue252_physical import A, C as C252, D
import issue254_producer as PR
import issue252_mechanism as M
import issue252_physical as P252
import issue252_terminal as T252

# The physically plausible retained A3 stream: exact async-disabled marker
# and NO enumeration banner (the instrument's real behavior).
ASYNC_ONLY_LOG = ("ggml_vulkan: WARNING: Async execution disabled on certain "
                  "Intel devices." + NL)
# Second-GPU log: two banners must still block even without the
# one-banner requirement.
TWO_ENUM_LOG = (ASYNC_ONLY_LOG + ENUM_LINE + NL
                + ENUM_LINE.replace(" 0 = ", " 1 = ") + NL)

FAKE_COMPARATOR_NO_ENUM = (
    "#!/usr/bin/env python3\n"
    "import json, os\n"
    "from http.server import BaseHTTPRequestHandler, HTTPServer\n"
    f"OUT = os.environ['LLAMA_OBSERVE_OUT']\n"
    f"ROW_BYTES = {D.ROW_BYTES}\n"
    "class H(BaseHTTPRequestHandler):\n"
    "    def log_message(self, *a):\n"
    "        pass\n"
    "    def do_GET(self):\n"
    "        if self.path == '/health':\n"
    "            self.send_response(200)\n"
    "            self.end_headers()\n"
    "            self.wfile.write(b'ok')\n"
    "        else:\n"
    "            self.send_response(404)\n"
    "            self.end_headers()\n"
    "    def do_POST(self):\n"
    "        n = int(self.headers.get('Content-Length', 0))\n"
    "        self.rfile.read(n)\n"
    "        with open(OUT + '.meta.json', 'w') as f:\n"
    "            f.write(''.join(json.dumps(\n"
    "                {'pos': i, 'pid': os.getpid()}) + chr(10)\n"
    "                for i in range(8)))\n"
    "        for i in range(8):\n"
    "            with open(OUT + '.row%d.f32' % i, 'wb') as f:\n"
    "                f.write(bytes([i]) + bytes(ROW_BYTES - 1))\n"
    "        body = json.dumps({'tokens': [1, 2, 3, 4, 5, 6, 7, 8],\n"
    "                           'content': 'x' * 8,\n"
    "                           'timings': {'prompt_n': 3072}}\n"
    "                          ).encode()\n"
    "        self.send_response(200)\n"
    "        self.send_header('Content-Type', 'application/json')\n"
    "        self.send_header('Content-Length', str(len(body)))\n"
    "        self.end_headers()\n"
    "        self.wfile.write(body)\n"
    "print('ggml_vulkan: WARNING: Async execution disabled on certain "
    "Intel devices.', flush=True)\n"
    f"HTTPServer(('127.0.0.1', {PR.PORT}), H).serve_forever()\n")


def _geometry(arm="A3", binary=Path("/nonexistent/llama-server"),
              prefix=Path("/tmp/unit/obs")):
    return P252.launch_geometry(
        arm, binary, PR.MODEL_DIR / next(iter(C252.MODEL_MEMBERS)), prefix)


class A3EnumFreePlacementTests(ProducerFixtureMixin, unittest.TestCase):
    """GREEN 4: corrected placement law accepts the frozen producer-attested
    Vulkan identity/env facts WITHOUT the enum banner (RED at a090c41)."""

    def setUp(self):
        self.fixture()

    def test_enum_free_physically_plausible_log_accepted(self):
        placement = PR._placement_from_log(
            ASYNC_ONLY_LOG.encode(), _geometry()["env"],
            _geometry()["argv"])
        self.assertEqual(placement["output_projection"], "Vulkan")
        self.assertEqual(placement["embedding"], "CPU")
        self.assertEqual(placement["ngl"], 1)
        self.assertEqual(placement["gpu_uuid"], C252.HOST_FACTS["gpu_uuid"])
        self.assertFalse(placement["cuda_participation"])
        # identity authority, not a per-unit log observation
        self.assertEqual(placement["vulkan_family"], "NV_coopmat2")
        self.assertEqual(placement["vulkan_family_authority"],
                         "frozen-host-facts")
        self.assertNotIn("enumeration_line", placement)

    def test_second_enumeration_banner_still_blocks(self):
        with self.assertRaisesRegex(PR.ProducerError,
                                    "more than one Vulkan device"):
            PR._placement_from_log(TWO_ENUM_LOG.encode(),
                                   _geometry()["env"], _geometry()["argv"])

    def test_cuda_visible_path_still_blocks(self):
        env = dict(_geometry()["env"])
        env["CUDA_VISIBLE_DEVICES"] = "0"
        with self.assertRaisesRegex(PR.ProducerError, "CUDA"):
            PR._placement_from_log(ASYNC_ONLY_LOG.encode(), env)

    def test_wrong_icd_still_blocks(self):
        env = dict(_geometry()["env"])
        env["VK_ICD_FILENAMES"] = "/usr/share/vulkan/icd.d/radeon_icd.json"
        with self.assertRaisesRegex(PR.ProducerError, "ICD"):
            PR._placement_from_log(ASYNC_ONLY_LOG.encode(), env)

    def test_wrong_vk_visible_devices_still_blocks(self):
        env = dict(_geometry()["env"])
        env["GGML_VK_VISIBLE_DEVICES"] = "1"
        with self.assertRaisesRegex(PR.ProducerError, "visible devices"):
            PR._placement_from_log(ASYNC_ONLY_LOG.encode(), env)

    def test_non_frozen_ngl_geometry_still_blocks(self):
        argv = list(_geometry()["argv"])
        i = argv.index("-ngl")
        argv[i + 1] = "99"
        with self.assertRaisesRegex(PR.ProducerError, "ngl"):
            PR._placement_from_log(ASYNC_ONLY_LOG.encode(),
                                   _geometry()["env"], argv)

    def test_banner_when_present_must_match_frozen_capability(self):
        bad = ASYNC_ONLY_LOG + ENUM_LINE.replace(
            "NV_coopmat2", "AMD_radial") + NL
        with self.assertRaisesRegex(PR.ProducerError,
                                    "frozen subject capability"):
            PR._placement_from_log(bad.encode(), _geometry()["env"],
                                   _geometry()["argv"])

    def test_enum_carrying_log_still_accepted_with_enumeration_line(self):
        placement = PR._placement_from_log(
            MECH_A3_LOG.encode(), _geometry()["env"], _geometry()["argv"])
        self.assertEqual(placement["enumeration_line"], ENUM_LINE)


class A3EnumFreeMechanismTests(ProducerFixtureMixin, unittest.TestCase):
    """GREEN 5/6: A3 mechanism accepts the exact async-disabled marker +
    corrected retained placement/identity WITHOUT the enum banner; missing
    marker still BLOCKS (RED at a090c41: same population rejected)."""

    def setUp(self):
        self.fixture()
        self.ns = A.ARMS["A3"]["namespace"]

    def _write_unit(self, name, log, *, placement=None, identity=None,
                    missing_placement=False, missing_identity=False):
        unit = self.evidence / self.ns / name
        unit.mkdir(parents=True)
        (unit / "server.log").write_text(log, encoding="utf-8")
        if not missing_placement:
            (unit / "placement.json").write_text(json.dumps(
                placement if placement is not None else {
                    "output_projection": "Vulkan", "embedding": "CPU",
                    "ngl": 1, "gpu_uuid": C252.HOST_FACTS["gpu_uuid"],
                    "vulkan_family": "NV_coopmat2",
                    "vulkan_family_authority": "frozen-host-facts",
                    "cuda_participation": False}))
        if not missing_identity:
            ident = identity if identity is not None else dict(
                C252.HOST_FACTS)
            (unit / "identity-pre.json").write_text(json.dumps(ident))
            (unit / "identity-post.json").write_text(json.dumps(ident))

    def test_enum_free_async_marker_population_accepted(self):
        self._write_unit("case-3072-B-a3-001", ASYNC_ONLY_LOG)
        self._write_unit("case-3072-B-a3-002", ASYNC_ONLY_LOG)
        status = M.mechanism_status(self.evidence, "A3", self.ns)
        self.assertTrue(status["capable"])

    def test_missing_async_marker_still_blocks(self):
        self._write_unit("case-3072-B-a3-001", "no markers at all" + NL)
        with self.assertRaisesRegex(M.MechanismInvalid,
                                    "async-disabled"):
            M.mechanism_status(self.evidence, "A3", self.ns)

    def test_wrong_gpu_uuid_placement_still_blocks(self):
        self._write_unit("case-3072-B-a3-001", ASYNC_ONLY_LOG,
                         placement={"output_projection": "Vulkan",
                                    "embedding": "CPU", "ngl": 1,
                                    "gpu_uuid": "GPU-deadbeef",
                                    "cuda_participation": False})
        with self.assertRaisesRegex(M.MechanismInvalid, "GPU UUID"):
            M.mechanism_status(self.evidence, "A3", self.ns)

    def test_cuda_participating_placement_still_blocks(self):
        self._write_unit("case-3072-B-a3-001", ASYNC_ONLY_LOG,
                         placement={"output_projection": "Vulkan",
                                    "embedding": "CPU", "ngl": 1,
                                    "gpu_uuid": C252.HOST_FACTS["gpu_uuid"],
                                    "cuda_participation": True})
        with self.assertRaisesRegex(M.MechanismInvalid, "placement"):
            M.mechanism_status(self.evidence, "A3", self.ns)

    def test_drifted_identity_still_blocks(self):
        drifted = {**C252.HOST_FACTS, "driver": "999.99.99"}
        self._write_unit("case-3072-B-a3-001", ASYNC_ONLY_LOG,
                         identity=drifted)
        with self.assertRaisesRegex(M.MechanismInvalid, "identity"):
            M.mechanism_status(self.evidence, "A3", self.ns)

    def test_missing_placement_evidence_fails_closed(self):
        self._write_unit("case-3072-B-a3-001", ASYNC_ONLY_LOG,
                         missing_placement=True)
        with self.assertRaisesRegex(M.MechanismInvalid,
                                    "placement/identity evidence"):
            M.mechanism_status(self.evidence, "A3", self.ns)

    def test_wrong_vulkan_family_authority_value_blocks(self):
        self._write_unit("case-3072-B-a3-001", ASYNC_ONLY_LOG,
                         placement={"output_projection": "Vulkan",
                                    "embedding": "CPU", "ngl": 1,
                                    "gpu_uuid": C252.HOST_FACTS["gpu_uuid"],
                                    "vulkan_family": "AMD_radial",
                                    "cuda_participation": False})
        with self.assertRaisesRegex(M.MechanismInvalid, "vulkan_family"):
            M.mechanism_status(self.evidence, "A3", self.ns)

    def test_a2_and_a5_enum_laws_unchanged(self):
        # GREEN 9: A2/A5 still hard-require their enum observables.
        enum_free = "ggml_vulkan memory: NVIDIA GeForce RTX 3060: +4.00 MiB " \
                    "device at 0x1. Total device: 4.00 MiB, total host: 0 B" + NL
        ns2 = A.ARMS["A2"]["namespace"]
        (self.evidence / ns2 / "u1").mkdir(parents=True)
        (self.evidence / ns2 / "u1" / "server.log").write_text(
            enum_free, encoding="utf-8")
        with self.assertRaisesRegex(M.MechanismInvalid, "enumeration"):
            M.mechanism_status(self.evidence, "A2", ns2)
        ns5 = A.ARMS["A5"]["namespace"]
        (self.evidence / ns5 / "u1").mkdir(parents=True)
        (self.evidence / ns5 / "u1" / "server.log").write_text(
            ASYNC_ONLY_LOG + enum_free, encoding="utf-8")
        with self.assertRaisesRegex(M.MechanismInvalid, "enumeration"):
            # #258: retained custody law invoked directly (A5 nonterminal).
            M._mechanism_a5(self.evidence, ns5)
        # A5 keeps the frozen-family enum requirement even with a valid
        # staging ledger (fresh root so the enum-free u1 above is not the
        # unit that raises first).
        staging_log = (ASYNC_ONLY_LOG + ENUM_LINE.replace(
            "NV_coopmat2", "KHR_coopmat") + NL
            + "ggml_vulkan memory: ggml_vk_ensure_sync_staging_buffer(4194304)"
            + NL
            + "ggml_vulkan memory: NVIDIA GeForce RTX 3060: +4.00 MiB host "
              "at 0x1. Total device: 0 B, total host: 4.00 MiB" + NL
            + "ggml_vulkan memory: NVIDIA GeForce RTX 3060: +4.00 MiB "
              "device at 0x2. Total device: 4.00 MiB, total host: "
              "4.00 MiB" + NL)
        alt = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, alt, ignore_errors=True)
        (alt / ns5 / "u1").mkdir(parents=True)
        (alt / ns5 / "u1" / "server.log").write_text(
            staging_log, encoding="utf-8")
        # #258 (AMENDMENT-006): A5 is withdrawn from the localization
        # registry (mechanism_status short-circuits nonterminal), so the
        # retained custody law is exercised directly — its frozen enum
        # requirement is unchanged.
        with self.assertRaisesRegex(M.MechanismInvalid, "differs from"):
            M._mechanism_a5(alt, ns5)


class FailureQuarantineTests(ProducerFixtureMixin, unittest.TestCase):
    """GREEN 10: a placement-stage exception preserves server.log in a
    non-reducer quarantine namespace instead of deleting it (RED at
    a090c41: scratch deleted, zero server.log anywhere)."""

    def setUp(self):
        self.fixture()
        self.arm = "A3"
        self.ns = A.ARMS[self.arm]["namespace"]

    def _run_real_scratch_failure(self, comparator_text):
        with tempfile.TemporaryDirectory() as tmp:
            binary = Path(tmp) / "llama-server"
            binary.write_text(comparator_text)
            binary.chmod(0o755)
            witness = {m: {"bytes": 1, "device": 1, "inode": 1,
                           "mtime_ns": 1, "ctime_ns": 1}
                       for m in C252.MODEL_MEMBERS}
            expected_argv = _geometry(
                binary=binary, prefix=Path(tmp) / "unit" / "obs")["argv"]
            with self.patched_orchestration(self.arm,
                                            execute=PR.execute_unit), \
                    mock.patch.object(PR, "verify_comparator",
                                      lambda b: "0" * 64), \
                    mock.patch.object(PR, "observe_model_stats",
                                      lambda md: witness), \
                    mock.patch.object(PR, "_default_identity_observer",
                                      lambda: dict(C252.HOST_FACTS)), \
                    mock.patch.object(PR, "_default_health_runner",
                                      lambda: {"rc": 0,
                                               "nvidia_smi_raw": ""}), \
                    mock.patch.object(PR, "_proc_readback",
                                      lambda pid: {
                                          "argv": list(expected_argv),
                                          "env_raw_sha256": "0" * 64}):
                try:
                    PR.run_unit(repo_root=self.repo,
                                evidence_root=self.evidence,
                                arm=self.arm, binary=binary, timeout_s=60)
                    raise AssertionError("run_unit unexpectedly succeeded")
                except PR.ProducerError:
                    pass

    def test_placement_failure_preserves_server_log_in_quarantine(self):
        # The physical instrument's stream (no enum banner) reaches a
        # placement-stage failure under the OLD law; under the corrected
        # law this comparator runs to publication — so force the failure
        # deterministically with a log that violates placement (two enum
        # banners = second participating device).
        two_banner = FAKE_COMPARATOR_NO_ENUM.replace(
            "print('ggml_vulkan: WARNING: Async execution disabled on "
            "certain Intel devices.', flush=True)",
            "print(" + repr(ENUM_LINE) + ", flush=True)\n"
            "print(" + repr(ENUM_LINE.replace(" 0 = ", " 1 = ")) +
            ", flush=True)")
        self._run_real_scratch_failure(two_banner)
        quarantine = self.evidence / "producer-failure-quarantine" / self.ns
        self.assertTrue(quarantine.is_dir())
        failures = sorted(quarantine.iterdir())
        self.assertEqual(len(failures), 1)
        preserved = failures[0]
        self.assertTrue((preserved / "server.log").is_file(),
                        "diagnostic server.log destroyed by cleanup")
        self.assertIn("0 = NVIDIA", (preserved / "server.log").read_text())
        self.assertIn("1 = NVIDIA",
                      (preserved / "server.log").read_text())
        status = json.loads((preserved / "failure-status.json").read_bytes())
        self.assertEqual(status["status"], "unit_failed")
        # the raw response bytes were collected before failure: preserved
        self.assertTrue((preserved / "obs.meta.json").is_file()
                        or (preserved / "obs.row0.f32").is_file(),
                        "observer artifacts not preserved")
        # root status record retained
        rec = json.loads(
            (self.evidence / f"producer-status-{self.ns}.json").read_bytes())
        self.assertEqual(rec["status"], "unit_failed")

    def test_quarantine_directory_is_not_reducer_admissible(self):
        # A quarantine entry inside the evidence root must BLOCK reduction
        # of that root (unplanned namespace), never contribute evidence.
        cap = self.live_capture(self.arm)
        for i in range(1, 6):
            self.write_unit_tree(self.arm, i, cap)
        (self.evidence / "authority.json").write_text(json.dumps({
            "repo_root": str(self.repo), "dispatch_capture": cap},
            sort_keys=True))
        quarantine = (self.evidence / "producer-failure-quarantine"
                      / self.ns / "exec-case-3072-B-a3-001.tmp-20261001")
        quarantine.mkdir(parents=True)
        (quarantine / "server.log").write_text("diagnostic only" + NL)
        (quarantine / "failure-status.json").write_text(json.dumps({
            "schema": "inferswarm.issue254.failure-quarantine/1",
            "status": "unit_failed"}))
        with mock.patch.object(P252, "fetch_dispatch_comment",
                               self.offline_comment_refetch()):
            self.assertEqual(T252.derive_terminal(self.evidence, {}),
                             T252.BLOCKED)
        # and the quarantine holds no unit.json / producer attestation
        self.assertFalse((quarantine / "unit.json").exists())
        self.assertFalse((quarantine / "producer-attestation.json").exists())

    def test_continuation_fail_closed_after_failure(self):
        # The retained failure status record refuses any next unit on the
        # same evidence root (fresh root required).
        (self.evidence / f"producer-status-{self.ns}.json").write_text(
            json.dumps({"schema": "inferswarm.issue254.producer-status/1",
                        "namespace": self.ns, "status": "unit_failed"}))
        with self.assertRaisesRegex(PR.ProducerError, "fail-closed"):
            PR.next_legal_unit(self.evidence, self.arm)
        # a FRESH root with no failure record continues normally
        fresh = self.root / "fresh-evidence"
        fresh.mkdir()
        self.assertEqual(PR.next_legal_unit(fresh, self.arm), 1)

    def test_empty_scratch_failure_leaves_no_quarantine(self):
        # A failure before execute_unit created any artifact (nothing to
        # destroy) is not quarantined: ordinary cleanup still applies.
        def failing_execute(**kwargs):
            raise PR.ProducerError("synthetic launch failure")
        with self.patched_orchestration(self.arm, execute=failing_execute):
            with self.assertRaises(PR.ProducerError):
                PR.run_unit(repo_root=self.repo,
                            evidence_root=self.evidence,
                            arm=self.arm,
                            binary=Path("/nonexistent/llama-server"),
                            timeout_s=60)
        self.assertFalse(
            (self.evidence / "producer-failure-quarantine").exists())
        self.assertFalse(list(
            (self.evidence / self.ns).glob(".exec-*"))
            if (self.evidence / self.ns).is_dir() else [])


class RealExecuteEnumFreeTests(ProducerFixtureMixin, unittest.TestCase):
    """GREEN end-to-end: the REAL execute_unit + REAL run_unit publish a
    unit whose retained stream is the instrument's (async marker, no enum
    banner) — the exact physical A3 unit-001 shape now survives."""

    def setUp(self):
        self.fixture()

    def test_real_execute_unit_publishes_enum_free_unit(self):
        with tempfile.TemporaryDirectory() as tmp:
            binary = Path(tmp) / "llama-server"
            binary.write_text(FAKE_COMPARATOR_NO_ENUM)
            binary.chmod(0o755)
            work = Path(tmp) / "unit"
            work.mkdir()
            dispatch = {"comment_id": 1, "body_sha256": "0" * 64,
                        "head_sha": "1" * 40, "arm": "A3"}
            witness = {m: {"bytes": 1, "device": 1, "inode": 1,
                           "mtime_ns": 1, "ctime_ns": 1}
                       for m in C252.MODEL_MEMBERS}
            expected_argv = _geometry(binary=binary, prefix=work / "obs")["argv"]
            with mock.patch.object(PR, "verify_comparator",
                                   lambda b: C252.COMPARATOR_SHA256), \
                    mock.patch.object(PR, "observe_model_stats",
                                      lambda md: witness), \
                    mock.patch.object(PR, "_default_identity_observer",
                                      lambda: dict(C252.HOST_FACTS)), \
                    mock.patch.object(PR, "_default_health_runner",
                                      lambda: {"rc": 0,
                                               "nvidia_smi_raw": ""}), \
                    mock.patch.object(PR, "_proc_readback",
                                      lambda pid: {
                                          "argv": list(expected_argv),
                                          "env_raw_sha256": "0" * 64}):
                unit = PR.execute_unit(
                    dispatch=dispatch, arm="A3", unit_index=1,
                    binary=binary, unit_dir=work,
                    prompt="p", timeout_s=30)
            placement = unit["placement"]
            self.assertEqual(placement["output_projection"], "Vulkan")
            self.assertNotIn("enumeration_line", placement)
            self.assertEqual(placement["vulkan_family_authority"],
                             "frozen-host-facts")
            # full producer attestation validates over the enum-free unit
            att = PR.build_producer_attestation(unit)
            PR.validate_producer_attestation(att)


class FailureCrashRestartTests(ProducerFixtureMixin, unittest.TestCase):
    """CPU-only real run_unit exception/finally and orphan restart controls."""

    def setUp(self):
        self.fixture()
        self.arm = "A3"
        self.ns = A.ARMS[self.arm]["namespace"]
        self.work = (self.evidence / self.ns
                     / ".exec-case-3072-B-a3-001.tmp")
        self.artifacts = {"server.log": b"diagnostic server log\n",
                          "obs.meta.json": b'{"pid":123}\n',
                          "obs.row0.f32": b"\x00\x01\x02",
                          "response.json.raw": b'{"tokens":[1]}'}
        self.failure = PR.ProducerError("original execution failure")

    def failing_execute(self, **kwargs):
        work = kwargs["unit_dir"]
        for name, raw in self.artifacts.items():
            (work / name).write_bytes(raw)
        raise self.failure

    def run_failure(self):
        with self.patched_orchestration(self.arm, execute=self.failing_execute):
            with self.assertRaises(PR.ProducerError) as caught:
                PR.run_unit(repo_root=self.repo, evidence_root=self.evidence,
                            arm=self.arm, binary=Path("/nonexistent"),
                            timeout_s=60)
        self.assertIs(caught.exception, self.failure)

    def assert_preserved(self, work):
        self.assertEqual({p.name: p.read_bytes() for p in work.iterdir()},
                         self.artifacts)

    def test_pre_rename_quarantine_failure_preserves_scratch(self):
        quarantine = mock.Mock(side_effect=OSError("forced pre-rename failure"))
        with mock.patch.object(PR, "quarantine_unit_failure", quarantine):
            self.run_failure()
        quarantine.assert_called_once()
        self.assertTrue(self.work.is_dir(),
                        "finally destroyed non-empty failed execution scratch")
        self.assert_preserved(self.work)
        self.assertIn("forced pre-rename failure",
                      " ".join(getattr(self.failure, "__notes__", [])))

    def test_quarantine_destination_collision_preserves_scratch(self):
        with mock.patch.object(PR.time, "strftime", return_value="fixed"):
            dest = (self.evidence / "producer-failure-quarantine" / self.ns
                    / (self.work.name.lstrip(".") + "-fixed"))
            dest.mkdir(parents=True)
            (dest / "sentinel").write_bytes(b"prior failure")
            self.run_failure()
        self.assertTrue(self.work.is_dir(), "collision deleted evidence")
        self.assert_preserved(self.work)
        self.assertEqual((dest / "sentinel").read_bytes(), b"prior failure")

    def test_orphan_exec_without_status_refuses_restart(self):
        self.work.mkdir(parents=True)
        for name, raw in self.artifacts.items():
            (self.work / name).write_bytes(raw)
        self.assertFalse((self.evidence /
                          f"producer-status-{self.ns}.json").exists())
        self.assertEqual(PR.retained_tags(self.evidence, self.ns), [])
        with self.assertRaisesRegex(PR.ProducerError, "incomplete"):
            PR.next_legal_unit(self.evidence, self.arm)
        self.assert_preserved(self.work)

    def test_orphan_unit_publication_staging_refuses_restart(self):
        work = self.work.with_name(".unit-case-3072-B-a3-001.tmp")
        work.mkdir(parents=True)
        (work / "server.log").write_bytes(b"partial publication")
        with self.assertRaisesRegex(PR.ProducerError, "incomplete"):
            PR.next_legal_unit(self.evidence, self.arm)
        self.assertEqual((work / "server.log").read_bytes(), b"partial publication")

    def test_scratch_symlinks_and_unexpected_paths_refuse_restart(self):
        base = self.work.parent
        base.mkdir(parents=True)
        for name in (self.work.name, ".unit-case-3072-B-a3-001.tmp",
                     "case-3072-B-a3-001", ".unexpected"):
            for kind in ("file", "dangling", "directory-link"):
                with self.subTest(name=name, kind=kind):
                    path = base / name
                    if kind == "file":
                        path.write_bytes(b"unexpected")
                    else:
                        path.symlink_to(self.root / "missing" if kind == "dangling"
                                        else self.repo, target_is_directory=True)
                    try:
                        with self.assertRaises(PR.ProducerError):
                            PR.next_legal_unit(self.evidence, self.arm)
                    finally:
                        path.unlink()

    def test_namespace_symlink_and_file_refuse_restart(self):
        base = self.work.parent
        for kind in ("file", "dangling", "directory-link"):
            with self.subTest(kind=kind):
                if kind == "file":
                    base.write_bytes(b"unexpected")
                else:
                    base.symlink_to(self.root / "missing" if kind == "dangling"
                                    else self.repo, target_is_directory=True)
                try:
                    with self.assertRaises(PR.ProducerError):
                        PR.next_legal_unit(self.evidence, self.arm)
                finally:
                    base.unlink()

    def test_status_unexpected_path_refuses_restart(self):
        status = self.evidence / f"producer-status-{self.ns}.json"
        status.symlink_to(self.root / "missing")
        with self.assertRaises(PR.ProducerError):
            PR.next_legal_unit(self.evidence, self.arm)

    def test_status_write_failure_does_not_mask_original_or_delete_scratch(self):
        with mock.patch.object(PR, "retain_status_record",
                               side_effect=OSError("status write failed")), \
             mock.patch.object(PR, "quarantine_unit_failure",
                               side_effect=OSError("quarantine failed")):
            self.run_failure()
        self.assert_preserved(self.work)
        notes = " ".join(self.failure.__notes__)
        self.assertIn("status write failed", notes)
        self.assertIn("quarantine failed", notes)

    def test_failed_nested_scratch_preserved_byte_for_byte(self):
        def fail(**kwargs):
            self.failing_execute(**kwargs)
        def nested_fail(**kwargs):
            nested = kwargs["unit_dir"] / "nested"
            nested.mkdir()
            (nested / "observer").write_bytes(b"nested artifact")
            fail(**kwargs)
        with self.patched_orchestration(self.arm, execute=nested_fail), \
             mock.patch.object(PR, "quarantine_unit_failure",
                               side_effect=OSError("quarantine failed")):
            with self.assertRaises(PR.ProducerError) as caught:
                PR.run_unit(repo_root=self.repo, evidence_root=self.evidence,
                            arm=self.arm, binary=Path("/nonexistent"), timeout_s=60)
        self.assertIs(caught.exception, self.failure)
        self.assertEqual((self.work / "nested" / "observer").read_bytes(),
                         b"nested artifact")
        for name, raw in self.artifacts.items():
            self.assertEqual((self.work / name).read_bytes(), raw)

    def test_successful_quarantine_preserves_all_execution_artifacts(self):
        self.run_failure()
        self.assertFalse(self.work.exists())
        base = self.evidence / "producer-failure-quarantine" / self.ns
        retained = list(base.iterdir())
        self.assertEqual(len(retained), 1)
        for name, raw in self.artifacts.items():
            self.assertEqual((retained[0] / name).read_bytes(), raw)
        self.assertEqual(json.loads((retained[0] / "failure-status.json")
                                   .read_bytes())["error"],
                         "ProducerError: original execution failure")


    def test_quarantine_symlink_refused_without_evidence_loss(self):
        target = self.root / "elsewhere"
        target.mkdir()
        base = self.evidence / "producer-failure-quarantine"
        base.symlink_to(target, target_is_directory=True)
        self.run_failure()
        self.assert_preserved(self.work)
        self.assertEqual(list(target.iterdir()), [])
        self.assertIn("unexpected quarantine directory path",
                      " ".join(self.failure.__notes__))

    def test_post_rename_status_failure_preserves_quarantined_bytes(self):
        write = PR._write_json_fsynced
        def fail_quarantine_metadata(path, doc):
            if path.name == "failure-status.json":
                raise OSError("quarantine metadata failed")
            return write(path, doc)
        with mock.patch.object(PR, "_write_json_fsynced", fail_quarantine_metadata):
            self.run_failure()
        self.assertFalse(self.work.exists())
        base = self.evidence / "producer-failure-quarantine" / self.ns
        retained = list(base.iterdir())
        self.assertEqual(len(retained), 1)
        self.assert_preserved(retained[0])
        self.assertIn("quarantine metadata failed", " ".join(self.failure.__notes__))

    def test_successful_publication_cleans_duplicate_execution_scratch(self):
        execute = self.fake_execute_unit()
        def with_scratch(**kwargs):
            unit = execute(**kwargs)
            (kwargs["unit_dir"] / "server.log").write_bytes(unit["server_log"])
            return unit
        with self.patched_orchestration(self.arm, execute=with_scratch):
            outcome = PR.run_unit(repo_root=self.repo, evidence_root=self.evidence,
                                  arm=self.arm, binary=Path("/nonexistent"),
                                  timeout_s=60)
        self.assertFalse(self.work.exists())
        self.assertTrue((Path(outcome["unit_dir"]) / "server.log").is_file())
        self.assertEqual(PR.next_legal_unit(self.evidence, self.arm), 2)

    def test_empty_orphan_exec_still_requires_explicit_recovery(self):
        # Only the current run's pre-artifact scratch may be cleaned. An
        # orphan's emptiness alone cannot authorize resuming a crashed run.
        self.work.mkdir(parents=True)
        with self.assertRaisesRegex(PR.ProducerError, "incomplete"):
            PR.next_legal_unit(self.evidence, self.arm)

    def test_discovery_covers_all_current_unpublished_directory_forms(self):
        self.work.parent.mkdir(parents=True)
        names = [".exec-case-3072-B-a3-001.tmp", ".unit-case-3072-B-a3-002.tmp"]
        for name in names:
            (self.work.parent / name).mkdir()
        self.assertEqual(PR.incomplete_producer_scratch(self.evidence, self.ns),
                         sorted(names))

    def test_orphan_scratch_cannot_supply_mechanism_or_terminal_evidence(self):
        # An otherwise fully admissible population must be BLOCKED by an
        # orphan, not promoted or counted. Reducer policing is unchanged.
        cap = self.live_capture(self.arm)
        for i in range(1, 6):
            self.write_unit_tree(self.arm, i, cap)
        (self.evidence / "authority.json").write_text(json.dumps({
            "repo_root": str(self.repo), "dispatch_capture": cap}))
        with mock.patch.object(P252, "fetch_dispatch_comment",
                               self.offline_comment_refetch()):
            self.assertNotEqual(T252.derive_terminal(self.evidence, {}),
                                T252.BLOCKED)
            for prefix in (".exec-", ".unit-"):
                work = self.work.with_name(prefix + "case-3072-B-a3-001.tmp")
                work.mkdir()
                (work / "server.log").write_bytes(b"diagnostic only")
                try:
                    self.assertEqual(T252.derive_terminal(self.evidence, {}),
                                     T252.BLOCKED)
                    with self.assertRaises(M.MechanismInvalid):
                        M.mechanism_status(self.evidence, self.arm, self.ns)
                    self.assertFalse((work / "unit.json").exists())
                finally:
                    shutil.rmtree(work)


if __name__ == "__main__":
    unittest.main()
