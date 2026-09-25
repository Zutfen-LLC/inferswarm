"""Issue #248 (R8-I3A) diagnostic tooling tests (CPU-only, fake runners).

Round-1 correction suite (maintainer NO-GO comment 5820126410): adds
old-defect proofs and mutation controls for the six corrected boundaries
— exact three-member model authority, frozen request contract, mandatory
live dispatch authority, comment-bound case-4096 authorization,
mechanical terminal derivation, and exact runtime/device subject
identity. Still CPU-only: every physical seam (git, GitHub, identity
observer, model hashing, server launch) is injected.
"""
from __future__ import annotations

import hashlib
import json
import os
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import issue248_diagnostic as D  # noqa: E402
import issue248_health as H  # noqa: E402
import issue248_physical as P  # noqa: E402
import issue248_terminal as T  # noqa: E402
import issue248_identity as I  # noqa: E402

HEAD = "0" * 40  # synthetic authorized head for authority tests

# Retained-census-shaped raw identity evidence (arm B), provenance-bound
# to the accepted #241 replacement census (2026-09-24). Mutations of
# THIS structure drive the identity negative controls.
CENSUS_RAW_B = {
    "host": "inferswarm01",
    "bdf": "00000000:03:00.0",
    "sysfs.vendor": "0x10de",
    "sysfs.device": "0x2504",
    "sysfs.subsystem_vendor": "0x1458",
    "sysfs.subsystem_device": "0x4074",
    "sysfs.revision": "0xa1",
    "sysfs.current_link_width": "16",
    "sysfs.max_link_width": "16",
    "sysfs.max_link_speed": "16.0 GT/s PCIe",
    "sysfs.driver": "nvidia",
    "nvidia-smi": ("0, GPU-d5c05739-96c1-7e49-89b6-bf54c2121c55, "
                   "00000000:03:00.0, NVIDIA GeForce RTX 3060, 610.57.04, "
                   "12288 MiB, 38, 14.28 W, 170.00 W"),
    "icd_inventory": {
        "nvidia_icd.json": json.dumps(
            {"ICD": {"library_path": "libGLX_nvidia.so.0"},
             "api_version": "1.4.341"}),
        "radeon_icd.json": json.dumps(
            {"ICD": {"library_path": "/usr/lib/x86_64-linux-gnu/"
                     "libradeon_vulkan.so.1"},
             "api_version": "1.4.305"}),
    },
    "vulkaninfo": {
        "icd_path": "/usr/share/vulkan/icd.d/nvidia_icd.json",
        "stdout": (
            "==========\nVULKANINFO\n==========\n\n"
            "Vulkan Instance Version: 1.4.309\n\nDevices:\n========\n"
            "GPU0:\n\tapiVersion         = 1.4.341\n"
            "\tdriverVersion      = 610.57.4.0\n"
            "\tvendorID           = 0x10de\n"
            "\tdeviceID           = 0x2504\n"
            "\tdeviceName         = NVIDIA GeForce RTX 3060\n"
            "\tdriverID           = DRIVER_ID_NVIDIA_PROPRIETARY\n"
            "\tdriverName         = NVIDIA\n"
            "\tdriverInfo         = 610.57.04\n"
            "\tdeviceUUID         = d5c05739-96c1-7e49-89b6-bf54c2121c55\n"),
        "rc": 0,
    },
}


def census_observation(arm: str = "B", **overrides) -> dict:
    raw = json.loads(json.dumps(CENSUS_RAW_B))
    raw.update(overrides)
    return {"arm": arm, "raw": raw}


def identity_ok(arm: str) -> dict:
    """Valid arm-B observation (arm C is not identity-exercised here)."""
    return census_observation(arm)


def make_authority(head: str = HEAD, namespace: str = "d248-test-ns",
                   body_extra: list[str] | None = None,
                   open_pr: bool = True, issue_open: bool = True,
                   comment_id: int = 123456,
                   author_association: str = "MEMBER",
                   ) -> dict:
    lines = [
        f"{D.DIAGNOSTIC_DISPATCH_PHRASE}",
        f"head={head}",
        f"diagnostic-namespace={namespace}",
    ]
    if body_extra:
        lines.extend(body_extra)
    return {
        "comment_id": comment_id,
        "issue_url": f"https://api.github.com/repos/Zutfen-LLC/inferswarm/issues/{D.DIAGNOSTIC_PR_NUMBER}",
        "author_association": author_association,
        "created_at": "2026-09-25T00:00:00Z",
        "body": "\n".join(lines),
        "head_sha": head,
        "namespace": namespace,
        "open_pr": open_pr,
        "issue_open": issue_open,
    }


class FakeGit:
    """Patch git invocations to a synthetic clean head."""

    def __init__(self, head: str = HEAD, dirty: bool = False):
        self.head = head
        self.dirty = dirty

    def __call__(self, argv, cwd=None, capture_output=True, text=True,
                 check=True, timeout=None):
        class R:
            pass
        r = R()
        if argv[1] == "rev-parse":
            r.stdout = self.head + "\n"
        elif argv[1] == "status":
            r.stdout = " M dirty\n" if self.dirty else ""
        r.returncode = 0
        return r


class NamespaceTests(unittest.TestCase):
    def test_valid_namespaces(self):
        for ns in ("d248-ref-repeats", "d248-observer-ladder",
                   "d248-placement-ngl-sweep"):
            self.assertEqual(D.validate_namespace(ns), ns)

    def test_forbidden_namespaces(self):
        for ns in ("d248-c237-x", "issue241-campaign", "d248-qualification",
                   "d248-campaign", "d248-phase3", "x", "d248-", "d248-A",
                   "d248--x", "", None, 5):
            with self.assertRaises(D.DiagnosticError):
                D.validate_namespace(ns)

    def test_qualification_shadow_guard(self):
        # 'phase'/'campaign'/'c237-' substrings rejected by
        # validate_namespace (the primary boundary)
        for ns in ("d248-phase9", "d248-campaign", "d248-c237-x"):
            with self.assertRaises(D.DiagnosticError):
                D.validate_namespace(ns)


class AuthorityTests(unittest.TestCase):
    def test_valid_payload_authorizes(self):
        a = make_authority()
        out = D.validate_authority_payload(a, HEAD)
        self.assertEqual(out["namespace"], "d248-test-ns")

    def test_rejects_non_member(self):
        a = make_authority()
        a["author_association"] = "CONTRIBUTOR"
        with self.assertRaises(D.DiagnosticError):
            D.validate_authority_payload(a, HEAD)

    def test_rejects_head_drift(self):
        a = make_authority()
        with self.assertRaises(D.DiagnosticError):
            D.validate_authority_payload(a, "f" * 40)

    def test_rejects_wrong_issue_binding(self):
        a = make_authority()
        a["issue_url"] = (
            "https://api.github.com/repos/Zutfen-LLC/inferswarm/issues/242")
        with self.assertRaises(D.DiagnosticError):
            D.validate_authority_payload(a, HEAD)

    def test_rejects_missing_phrase(self):
        a = make_authority()
        a["body"] = f"head={HEAD}\ndiagnostic-namespace=d248-test-ns"
        with self.assertRaises(D.DiagnosticError):
            D.validate_authority_payload(a, HEAD)

    def test_rejects_phrase_embedded_in_prose(self):
        # phrase mid-sentence (not an exact stripped line) must NOT match
        a = make_authority()
        a["body"] = (f"we said {D.DIAGNOSTIC_DISPATCH_PHRASE} today\n"
                     f"head={HEAD}\ndiagnostic-namespace=d248-test-ns")
        with self.assertRaises(D.DiagnosticError):
            D.validate_authority_payload(a, HEAD)

    def test_rejects_scope_mismatch(self):
        a = make_authority()
        a["namespace"] = "d248-other-ns"
        with self.assertRaises(D.DiagnosticError):
            D.validate_authority_payload(a, HEAD)

    def test_rejects_missing_scope_line(self):
        a = make_authority()
        a["body"] = f"{D.DIAGNOSTIC_DISPATCH_PHRASE}\nhead={HEAD}"
        a["namespace"] = "d248-test-ns"
        with self.assertRaises(D.DiagnosticError):
            D.validate_authority_payload(a, HEAD)

    def test_rejects_pr_closed(self):
        a = make_authority(open_pr=False)
        with self.assertRaises(D.DiagnosticError) as ctx:
            D.validate_authority_payload(a, HEAD)
        self.assertIn("closed or merged", str(ctx.exception))

    def test_rejects_issue_closed(self):
        a = make_authority(issue_open=False)
        with self.assertRaises(D.DiagnosticError) as ctx:
            D.validate_authority_payload(a, HEAD)
        self.assertIn("Issue #248 is closed", str(ctx.exception))

    def test_cached_payload_without_live_state_fails(self):
        # Correction 3 old-defect proof: a syntactically valid CACHED
        # authority dict (no live PR/issue state) can no longer pass.
        a = make_authority()
        del a["open_pr"]
        del a["issue_open"]
        with self.assertRaises(D.DiagnosticError) as ctx:
            D.validate_authority_payload(a, HEAD)
        self.assertIn("live authority state missing", str(ctx.exception))

    def test_multiple_scope_lines_rejected(self):
        a = make_authority(body_extra=["diagnostic-namespace=d248-test-ns"])
        with self.assertRaises(D.DiagnosticError) as ctx:
            D.validate_authority_payload(a, HEAD)
        self.assertIn("exactly one diagnostic-namespace", str(ctx.exception))


class RequireLiveDispatchTests(unittest.TestCase):
    """Correction 3: the live fetch is MANDATORY on the production path."""

    def test_default_path_runs_the_real_fetcher(self):
        calls = []

        def failing_fetch(repo_root, expected_head, namespace, github_api):
            calls.append((str(repo_root), expected_head, namespace,
                          github_api))
            raise D.DiagnosticError("live fetch attempted (no network in "
                                    "unit tests)")

        import inspect
        # The production default wires revalidate_authority=None to the
        # real live fetcher: prove require_live_dispatch dispatches to
        # the fetcher (here: a probe that records and fails), and that
        # a VALID injected fetch result is re-validated and returned.
        try:
            D.require_live_dispatch(Path("/tmp"), HEAD, "d248-test-ns",
                                    revalidate_authority=failing_fetch,
                                    github_api="https://example.invalid")
        except D.DiagnosticError as exc:
            self.assertIn("live fetch attempted", str(exc))
        self.assertEqual(len(calls), 1)

        payload = make_authority()
        result = D.require_live_dispatch(
            Path("/tmp"), HEAD, "d248-test-ns",
            revalidate_authority=lambda *a, **k: payload)
        self.assertEqual(result["namespace"], "d248-test-ns")
        self.assertTrue(result["open_pr"])
        self.assertTrue(result["issue_open"])
        # the structural default is the REAL fetcher (source-level)
        src = inspect.getsource(D.require_live_dispatch)
        self.assertIn("revalidate_authority = fetch_dispatch_authority",
                      src)

    def test_injected_fetcher_rejects_stale_head(self):
        def fetch(repo_root, expected_head, namespace, github_api):
            return make_authority(head="f" * 40)
        with self.assertRaises(D.DiagnosticError):
            D.require_live_dispatch(Path("/tmp"), HEAD, "d248-test-ns",
                                    revalidate_authority=fetch)

    def test_injected_fetcher_rejects_closed_pr(self):
        def fetch(repo_root, expected_head, namespace, github_api):
            return make_authority(open_pr=False)
        with self.assertRaises(D.DiagnosticError):
            D.require_live_dispatch(Path("/tmp"), HEAD, "d248-test-ns",
                                    revalidate_authority=fetch)


class FixtureAndIdentityTests(unittest.TestCase):
    def test_fixture_ladder_verifies(self):
        fixtures = D.verify_fixtures(REPO)
        for case in ("case-256", "case-1024", "case-3072", "case-4096"):
            self.assertIn(case, fixtures)
        self.assertEqual(fixtures["case-3072"]["rendered_length"], 3077)

    def test_ladder_sha_is_the_accepted_binding(self):
        # Must equal the #241 frozen constant (same bytes on main).
        self.assertEqual(
            D.FIXTURE_LADDER_SHA256,
            "419bde668c7b3cedf823c98ca0a883560a9a501007f9a28bf8d826148ee822db")

    def test_binary_ids_are_the_three_accepted_builds(self):
        self.assertEqual(D.SERVER_BINARIES["canonical"],
                         "21707f2568d80fb781b445cd472588e83501e1cc66dcf10885b286e34c02573e")
        self.assertEqual(D.SERVER_BINARIES["r8e-obs"],
                         "dcee5bcf8d80a7c99f2d71b753afd4c678d51a43154ed83bc2e208cced1b3ab0")
        self.assertEqual(D.SERVER_BINARIES["comparator"],
                         "6f8b56bd44d116cdc691911f8a1131840f5c7a720133c05febe11e467c2636ad")

    def test_verify_binary_rejects_mismatch(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "srv"
            p.write_bytes(b"not a real binary")
            with self.assertRaises(D.DiagnosticError):
                D.verify_binary(p, "comparator")
            with self.assertRaises(D.DiagnosticError):
                D.verify_binary(p, "unknown-id")

    def test_canonical_token_digest(self):
        digest = D.canonical_token_digest(
            [328, 760, 324, 55965, 51624, 29014, 34227, 18030])
        expected = hashlib.sha256(
            struct.pack("<8I", 328, 760, 324, 55965, 51624, 29014, 34227,
                        18030)).hexdigest()
        self.assertEqual(digest, expected)
        with self.assertRaises(D.DiagnosticError):
            D.canonical_token_digest([1] * 7)
        with self.assertRaises(D.DiagnosticError):
            D.canonical_token_digest([True] + [1] * 7)


class UnitTagTests(unittest.TestCase):
    def test_tags(self):
        self.assertEqual(D.unit_tag("case-3072", "B", "baseline", 1),
                         "case-3072-B-baseline-001")
        self.assertEqual(D.unit_tag("case-3072", "B", "ngl4", 12),
                         "case-3072-B-ngl4-012")

    def test_rejects_bad_shapes(self):
        for args in (("case-8192", "B", "x", 1), ("case-3072", "X", "x", 1),
                     ("case-3072", "B", "Bad", 1),
                     ("case-4096", "B", "baseline", 1)):
            with self.assertRaises(D.DiagnosticError):
                D.unit_tag(*args)


class CustodyTests(unittest.TestCase):
    def test_prepare_and_quarantine(self):
        with tempfile.TemporaryDirectory() as td:
            root, ns = Path(td), "d248-custody"
            u = D.prepare_unit_dir(root, ns, "case-3072-B-baseline-001")
            self.assertTrue(u.is_dir())
            with self.assertRaises(D.DiagnosticError):
                D.prepare_unit_dir(root, ns, "case-3072-B-baseline-001")
            q = D.quarantine_unit(root, ns, "case-3072-B-baseline-001")
            self.assertTrue(q.name.endswith("-quarantined"))
            self.assertFalse((root / ns / "case-3072-B-baseline-001").exists())
            with self.assertRaises(D.DiagnosticError):
                D.quarantine_unit(root, ns, "case-3072-B-baseline-001")

    def test_launch_env_observer_modes(self):
        base = dict(selector={"GGML_VK_VISIBLE_DEVICES": "0"},
                    icd="/icd.json", force=None, out_prefix=Path("/tmp/o"))
        env = D.launch_env("B", observer="comparator", **base)
        self.assertEqual(env["LLAMA_OBSERVE_CAPTURE"], "8")
        self.assertEqual(env["LLAMA_OBSERVE_FORCE"], "")
        env = D.launch_env("B", observer="r8e-only", **base)
        self.assertNotIn("LLAMA_OBSERVE_CAPTURE", env)
        self.assertTrue(env["LLAMA_OBSERVE_LOGITS"].endswith(".r8e.jsonl"))
        env = D.launch_env("B", observer="comparator", r8e_capture=True,
                           **base)
        # dual capture: comparator rows AND r8e row in ONE process
        self.assertEqual(env["LLAMA_OBSERVE_CAPTURE"], "8")
        self.assertTrue(env["LLAMA_OBSERVE_LOGITS"].endswith(".r8e.jsonl"))
        env = D.launch_env("B", observer="off", **base)
        self.assertNotIn("LLAMA_OBSERVE_CAPTURE", env)
        self.assertNotIn("LLAMA_OBSERVE_LOGITS", env)

    def test_server_argv_frozen_shape(self):
        argv = D.server_argv(Path("/b"), Path("/m"), 8, 19000)
        self.assertEqual(
            argv,
            ["/b", "--model", "/m", "-ngl", "8", "--ctx-size", "8192",
             "--batch-size", "512", "--host", "127.0.0.1",
             "--port", "19000"])
        with self.assertRaises(D.DiagnosticError):
            D.server_argv(Path("/b"), Path("/m"), 3, 19000)


class FakeRunnerPhysicalTests(unittest.TestCase):
    """Drive run_diagnostic_unit with a fake execute seam."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.repo = self.root / "repo"
        (self.repo / "docs/investigations/qwen38-flash-next-r8-b/"
         "evidence/reference").mkdir(parents=True)
        source = (REPO / D.FIXTURE_LADDER_REL).read_bytes()
        (self.repo / D.FIXTURE_LADDER_REL).write_bytes(source)
        self.bin = self.root / "bin"
        self.bin.write_bytes(b"x" * 32)
        # Correction 1: the FULL accepted three-member set under the
        # accepted MODEL_DIR layout; deterministic digests via the
        # injected model_hasher seam (real 50-GiB members never needed).
        self.model_dir = self.root / D.MODEL_DIR.lstrip("/")
        self.model_dir.mkdir(parents=True)
        self.member_digests = {}
        for member in D.MODEL_MEMBERS:
            p = self.model_dir / member
            p.write_bytes(b"m" * 64)
        for i, member in enumerate(D.MODEL_MEMBERS):
            # The injected hasher stands in for hashing the real
            # 50-GiB bytes: by default it reports the ACCEPTED digests
            # (i.e. the members hold exactly the accepted content).
            # Negative controls override individual members.
            self.member_digests[member] = D.MODEL_MEMBER_SHA256[member]
        self.model_hasher = (
            lambda path: self.member_digests[path.name])
        # deterministic binary sha by patching SERVER_BINARIES lookup
        self._orig = dict(D.SERVER_BINARIES)
        D.SERVER_BINARIES["comparator"] = D.file_sha256(self.bin)
        # fake git
        import issue248_diagnostic
        self._orig_run = issue248_diagnostic.subprocess.run
        issue248_diagnostic.subprocess.run = FakeGit(HEAD)

    def tearDown(self):
        D.SERVER_BINARIES.clear()
        D.SERVER_BINARIES.update(self._orig)
        import issue248_diagnostic
        issue248_diagnostic.subprocess.run = self._orig_run
        self._tmp.cleanup()

    def _live_fetch(self):
        """Injected live-dispatch fetcher returning a VALID payload."""
        def fetch(repo_root, expected_head, namespace, github_api):
            return make_authority(head=expected_head, namespace=namespace)
        return fetch

    def _identity_ok_seam(self, arm):
        return identity_ok(arm)

    def _identity_drift(self, arm):
        return census_observation(
            arm, **{"nvidia-smi": "some other gpu"})

    def _fake_execute(self, tokens=(328, 760, 324, 55965, 51624, 29014,
                                    34227, 18030)):
        def execute(argv, env, arm, request, prompt, port, unit_dir):
            raw = json.dumps({"tokens": list(tokens)}).encode()
            # observer files as the real server would write them
            (unit_dir / "obs.meta.json").write_text("".join(
                json.dumps({"pos": d, "sampled_winner": t,
                            "forced_token": -1, "n_vocab": D.N_VOCAB}) + "\n"
                for d, t in enumerate(tokens)))
            for d in range(D.DECISIONS):
                (unit_dir / f"obs.row{d}.f32").write_bytes(
                    struct.pack("<1f", 0.5) * D.N_VOCAB)
            stamp = datetime.now(timezone.utc).isoformat()
            return {"tokens": list(tokens), "response_raw": raw,
                    "process_attribution": {"server_pid": 42,
                                            "server_exe_sha256": D.SERVER_BINARIES["comparator"],
                                            "server_argv": argv,
                                            "server_env": env},
                    "device_samples": [{"stage": stage, "captured_at": stamp,
                                        "nvidia_smi_raw": (
                                            f"{I.REFERENCE_IDENTITY['gpu_uuid']}, "
                                            "40, 20, 170, 0\n")}
                                       for stage in ("before", "during", "after")]}
        return execute

    @staticmethod
    def _fake_health_command(argv, **kwargs):
        import issue248_health as H
        if argv[0] == "journalctl":
            # The test command's row is bound to the requested window.
            stamp = argv[argv.index("--until") + 1]
            return H.CommandResult(0, f"{stamp} host kernel: normal\n".encode())
        if argv[0] == "nvidia-smi":
            return H.CommandResult(0, (
                "GPU-d5c05739-96c1-7e49-89b6-bf54c2121c55, "
                "41, 75.0, 170.0, 0x0\n").encode())
        raise AssertionError(argv)

    def _run_kwargs(self, **overrides):
        kw = dict(
            arm="B", case="case-3072", ngl=8, binary_id="comparator",
            binary=self.bin, model_dir=self.model_dir, expected_head=HEAD,
            index=1, execute=self._fake_execute(),
            health_runner=self._fake_health_command,
            identity_observer=self._identity_ok_seam,
            revalidate_authority=self._live_fetch(),
            model_hasher=self.model_hasher)
        kw.update(overrides)
        return kw

    def _run(self, **overrides):
        return P.run_diagnostic_unit(self.repo, self.root / "ev",
                                     "d248-fake", "repeat", **overrides
                                     ) if False else P.run_diagnostic_unit(
            self.repo, self.root / "ev", "d248-fake", "repeat",
            **self._run_kwargs(**overrides))

    def test_positive_path_writes_custody(self):
        receipt = self._run()
        self.assertEqual(receipt["tokens"],
                         [328, 760, 324, 55965, 51624, 29014, 34227, 18030])
        # Correction 1: the COMPLETE verified member map is bound.
        self.assertEqual(receipt["model_members_sha256"],
                         self.member_digests)
        self.assertEqual(set(receipt["model_members_sha256"]),
                         set(D.MODEL_MEMBERS))
        # the launch path is DERIVED member 1 under the frozen dir
        self.assertEqual(
            Path(receipt["model_launch_member"]),
            self.model_dir / D.MODEL_MEMBER_1)
        # Correction 2: the receipt binds the frozen contract + digest.
        self.assertEqual(receipt["request_contract"], D.REQUEST_CONTRACT)
        self.assertEqual(
            receipt["request_contract_sha256"],
            D.canonical_request_digest(D.REQUEST_CONTRACT))
        unit = self.root / "ev" / "d248-fake" / receipt["tag"]
        for name in ("unit.json", "response.json.raw", "identity-pre.json",
                     "identity-post.json", "obs.meta.json"):
            self.assertTrue((unit / name).exists(), name)
        # The execution seam returns samples; production custody must retain
        # those exact raw observations rather than dropping them on return.
        samples = json.loads((unit / "device-samples.json").read_bytes())
        self.assertEqual([s["stage"] for s in samples],
                         ["before", "during", "after"])
        self.assertIn("platform_health", receipt)
        self.assertEqual(len(receipt["platform_health"]["artifacts"]), 3)
        self.assertEqual(receipt["response_raw_sha256"], hashlib.sha256(
            (unit / "response.json.raw").read_bytes()).hexdigest())
        self.assertEqual(len(receipt["observer_rows"]), D.DECISIONS)
        for i, digest in enumerate(receipt["observer_rows"]):
            self.assertEqual(digest, hashlib.sha256(
                (unit / f"obs.row{i}.f32").read_bytes()).hexdigest())
        # determinism digest derives from raw bytes, not receipt claims
        rr = json.loads((unit / "response.json.raw").read_bytes())
        self.assertEqual(
            receipt["deterministic_output_sha256"],
            D.canonical_token_digest(rr["tokens"]))

    def test_producer_receipt_is_consumable_by_strict_terminal_population(self):
        import issue248_terminal as T
        receipt = self._run()
        unit = self.root / "ev" / "d248-fake" / receipt["tag"]
        payload = make_authority(head=HEAD, namespace="d248-fake")
        population, problems = T._population(unit.parent, [receipt["tag"]],
                                              "repeat", "d248-fake",
                                              expected_authority=payload)
        self.assertEqual(problems, [])
        self.assertEqual(len(population["units"]), 1)

    def test_default_execution_path_persists_real_execute_returned_samples(self):
        # Replace only the physical process-launch leaf: run_diagnostic_unit
        # still selects its production _real_execute symbol by default.
        original = P._real_execute
        called = []
        def returning_samples(**kwargs):
            called.append(kwargs["unit_dir"])
            return self._fake_execute()(**kwargs)
        P._real_execute = returning_samples
        try:
            receipt = self._run(execute=None)
        finally:
            P._real_execute = original
        unit = self.root / "ev/d248-fake" / receipt["tag"]
        self.assertEqual(called, [unit])
        self.assertEqual([sample["stage"] for sample in json.loads(
            (unit / "device-samples.json").read_bytes())],
            ["before", "during", "after"])
        self.assertEqual(next(a for a in receipt["platform_health"]["artifacts"]
                              if a["kind"] == "producer_samples")["path"],
                         "device-samples.json")

    def test_reducer_health_requires_all_retained_raw_artifacts(self):
        for missing in ("device-samples.json", "kernel-journal.raw",
                        "nvidia-smi.csv.raw", "platform-health-receipt.json"):
            with self.subTest(missing=missing):
                receipt = self._run(index=len(list((self.root / "ev/d248-fake").glob("*"))) + 1)
                unit = self.root / "ev/d248-fake" / receipt["tag"]
                self.assertEqual(P._platform_health(unit.parent, [receipt["tag"]])[
                    "fatal_states"], [])
                (unit / missing).unlink()
                self.assertIsNone(P._platform_health(unit.parent, [receipt["tag"]]))

    def test_reducer_health_rejects_raw_digest_forgery(self):
        receipt = self._run()
        unit = self.root / "ev/d248-fake" / receipt["tag"]
        raw = unit / "kernel-journal.raw"
        raw.write_bytes(b"forged clean\n")
        self.assertIsNone(P._platform_health(unit.parent, [receipt["tag"]]))

    def test_reducer_health_fatal_raw_overrides_clean_summary(self):
        receipt = self._run()
        unit = self.root / "ev/d248-fake" / receipt["tag"]
        raw = unit / "kernel-journal.raw"
        window = receipt["platform_health"]["window"]
        raw.write_bytes((f'{window["start"]} host kernel: NVRM: Xid (PCI:0000:03:00): 79\n').encode())
        health_receipt = receipt["platform_health"]
        entry = next(a for a in health_receipt["artifacts"]
                     if a["kind"] == "kernel_journal")
        entry["bytes"] = len(raw.read_bytes())
        entry["sha256"] = hashlib.sha256(raw.read_bytes()).hexdigest()
        health_bytes = (json.dumps(health_receipt, sort_keys=True,
                                   indent=2) + "\n").encode()
        (unit / "platform-health-receipt.json").write_bytes(health_bytes)
        receipt["platform_health_receipt"]["bytes"] = len(health_bytes)
        receipt["platform_health_receipt"]["sha256"] = hashlib.sha256(
            health_bytes).hexdigest()
        receipt["platform_health_clean"] = True  # adversarial prose/summary
        (unit / "unit.json").write_text(json.dumps(receipt))
        result = P._platform_health(unit.parent, [receipt["tag"]])
        self.assertIsNotNone(result)
        self.assertTrue(result["fatal_states"])

    # --- Correction 1 negative controls: exact model authority ---------

    def test_model_member1_wrong_bytes_no_launch(self):
        called = []
        def execute(**kw):
            called.append(kw)
            return self._fake_execute()(**kw)
        digests = dict(self.member_digests)
        digests[D.MODEL_MEMBERS[0]] = "b" * 64
        with self.assertRaises(D.DiagnosticError) as ctx:
            self._run(execute=execute,
                      model_hasher=lambda p: digests[p.name])
        self.assertIn(D.MODEL_MEMBERS[0], str(ctx.exception))
        self.assertEqual(called, [])

    def test_model_member2_wrong_bytes_no_launch(self):
        called = []
        def execute(**kw):
            called.append(kw)
            return self._fake_execute()(**kw)
        digests = dict(self.member_digests)
        digests[D.MODEL_MEMBERS[1]] = "c" * 64
        with self.assertRaises(D.DiagnosticError) as ctx:
            self._run(execute=execute,
                      model_hasher=lambda p: digests[p.name])
        self.assertIn(D.MODEL_MEMBERS[1], str(ctx.exception))
        self.assertEqual(called, [])

    def test_model_member3_wrong_bytes_no_launch(self):
        called = []
        def execute(**kw):
            called.append(kw)
            return self._fake_execute()(**kw)
        digests = dict(self.member_digests)
        digests[D.MODEL_MEMBERS[2]] = "d" * 64
        with self.assertRaises(D.DiagnosticError) as ctx:
            self._run(execute=execute,
                      model_hasher=lambda p: digests[p.name])
        self.assertIn(D.MODEL_MEMBERS[2], str(ctx.exception))
        self.assertEqual(called, [])

    def test_model_member_missing_no_launch(self):
        called = []
        def execute(**kw):
            called.append(kw)
            return self._fake_execute()(**kw)
        import shutil
        shutil.rmtree(self.model_dir)
        self.model_dir.mkdir(parents=True)
        for member in D.MODEL_MEMBERS[1:]:  # member 1 absent
            (self.model_dir / member).write_bytes(b"m" * 64)
        with self.assertRaises(D.DiagnosticError) as ctx:
            self._run(execute=execute, model_hasher=self.model_hasher)
        self.assertIn("missing", str(ctx.exception))
        self.assertEqual(called, [])

    def test_arbitrary_replacement_model_no_launch(self):
        # A competent caller points model_dir at a directory holding a
        # DIFFERENT gguf (with correct member-1 digest even): the split
        # topology check rejects it before launch.
        called = []
        def execute(**kw):
            called.append(kw)
            return self._fake_execute()(**kw)
        import shutil
        other = self.root / "other-model"
        other.mkdir()
        (other / "MysteryModel-Q4_K_M-00001-of-00001.gguf").write_bytes(
            b"z" * 64)
        with self.assertRaises(D.DiagnosticError) as ctx:
            self._run(execute=execute, model_dir=other,
                      model_hasher=lambda p: self.member_digests.get(
                          p.name, "a" * 64))
        self.assertIn("unexpected split topology", str(ctx.exception))
        self.assertEqual(called, [])

    def test_competent_caller_mutates_members2_3_no_launch(self):
        # member 1 hash is CORRECT, members 2/3 mutated: still no launch.
        called = []
        def execute(**kw):
            called.append(kw)
            return self._fake_execute()(**kw)
        digests = dict(self.member_digests)
        digests[D.MODEL_MEMBERS[1]] = "e" * 64
        digests[D.MODEL_MEMBERS[2]] = "f" * 64
        with self.assertRaises(D.DiagnosticError) as ctx:
            self._run(execute=execute,
                      model_hasher=lambda p: digests[p.name])
        self.assertIn(D.MODEL_MEMBERS[1], str(ctx.exception))
        self.assertEqual(called, [])

    def test_real_model_hasher_rejects_fake_bytes(self):
        # The production hasher path (file bytes) must reject a dir of
        # fake members whose digests cannot match the accepted values.
        with self.assertRaises(D.DiagnosticError):
            D.verify_model_members(self.model_dir)

    # --- Correction 6 negative controls: subject identity --------------

    def _identity_case(self, label, **overrides):
        called = []
        def execute(**kw):
            called.append(kw)
            return self._fake_execute()(**kw)
        with self.assertRaises(P.PhysicalDiagnosticError) as ctx:
            self._run(execute=execute,
                      identity_observer=lambda arm: census_observation(
                          arm, **overrides))
        self.assertEqual(called, [])
        return ctx.exception

    def test_identity_driver_drift_no_launch(self):
        exc = self._identity_case(
            "driver", **{"nvidia-smi": CENSUS_RAW_B["nvidia-smi"].replace(
                "610.57.04", "615.00.01")})
        self.assertIn("nvidia_driver", str(exc))

    def test_identity_wrong_icd_no_launch(self):
        raw = json.loads(json.dumps(CENSUS_RAW_B))
        del raw["icd_inventory"]["nvidia_icd.json"]
        exc = self._identity_case("icd", **{"icd_inventory":
                                            raw["icd_inventory"]})
        self.assertIn("nvidia_icd", str(exc))

    def test_identity_wrong_vulkan_uuid_no_launch(self):
        raw = json.loads(json.dumps(CENSUS_RAW_B))
        raw["vulkaninfo"]["stdout"] = raw["vulkaninfo"]["stdout"].replace(
            "d5c05739-96c1-7e49-89b6-bf54c2121c55",
            "deadbeef-96c1-7e49-89b6-bf54c2121c55")
        exc = self._identity_case("vulkan-uuid", **{"vulkaninfo":
                                                    raw["vulkaninfo"]})
        # either the Vulkan UUID field or the cross-binding must fire
        self.assertTrue("vulkan_device_uuid" in str(exc)
                        or "cross-bind" in str(exc))

    def test_identity_wrong_vulkan_device_no_launch(self):
        raw = json.loads(json.dumps(CENSUS_RAW_B))
        raw["vulkaninfo"]["stdout"] = raw["vulkaninfo"]["stdout"].replace(
            "NVIDIA GeForce RTX 3060", "NVIDIA GeForce RTX 3050")
        exc = self._identity_case("vulkan-device", **{"vulkaninfo":
                                                      raw["vulkaninfo"]})
        self.assertIn("vulkan_device_name", str(exc))

    def test_identity_subsystem_drift_no_launch(self):
        exc = self._identity_case("subsystem",
                                  **{"sysfs.subsystem_vendor": "0x8086"})
        self.assertIn("subsystem_vendor_id", str(exc))

    def test_identity_revision_drift_no_launch(self):
        exc = self._identity_case("revision", **{"sysfs.revision": "0xb1"})
        self.assertIn("revision", str(exc))

    def test_identity_width_drift_no_launch(self):
        exc = self._identity_case("width", **{"sysfs.current_link_width":
                                              "8"})
        self.assertIn("negotiated_width", str(exc))

    def test_identity_speed_capability_drift_no_launch(self):
        exc = self._identity_case("speed", **{"sysfs.max_link_speed":
                                              "8.0 GT/s PCIe"})
        self.assertIn("max_link_speed_capability", str(exc))

    def test_identity_wrong_bdf_no_launch(self):
        # The observed BDF differs from the frozen address: fail closed.
        raw = json.loads(json.dumps(CENSUS_RAW_B))
        raw["bdf"] = "00000000:c1:00.0"
        called = []
        def execute(**kw):
            called.append(kw)
            return self._fake_execute()(**kw)
        with self.assertRaises(P.PhysicalDiagnosticError) as ctx:
            self._run(execute=execute,
                      identity_observer=lambda arm: {"arm": arm,
                                                     "raw": raw})
        self.assertEqual(called, [])
        self.assertIn("device address disagreement", str(ctx.exception))

    def test_identity_wrong_gpu_uuid_no_launch(self):
        exc = self._identity_case(
            "gpu-uuid", **{"nvidia-smi": CENSUS_RAW_B["nvidia-smi"].replace(
                "GPU-d5c05739-96c1-7e49-89b6-bf54c2121c55",
                "GPU-11111111-2222-3333-4444-555555555555")})
        self.assertTrue("gpu_uuid" in str(exc) or "cross-bind" in str(exc))

    def test_identity_missing_raw_source_no_launch(self):
        called = []
        def execute(**kw):
            called.append(kw)
            return self._fake_execute()(**kw)
        raw2 = json.loads(json.dumps(CENSUS_RAW_B))
        del raw2["sysfs.revision"]
        with self.assertRaises(P.PhysicalDiagnosticError) as ctx:
            self._run(execute=execute,
                      identity_observer=lambda arm: {"arm": arm,
                                                     "raw": raw2})
        self.assertEqual(called, [])
        self.assertIn("derivation failed", str(ctx.exception))

    def test_identity_vulkan_receipt_wrong_icd_source_no_launch(self):
        # The vulkaninfo receipt must come from the DERIVED ICD.
        raw = json.loads(json.dumps(CENSUS_RAW_B))
        raw["vulkaninfo"]["icd_path"] = (
            "/usr/share/vulkan/icd.d/radeon_icd.json")
        exc = self._identity_case("receipt-icd", **{"vulkaninfo":
                                                    raw["vulkaninfo"]})
        self.assertIn("derived ICD", str(exc))

    def test_single_factor_intervention_runs_and_labels(self):
        iv = {"field": "negotiated_width", "expected_value": "x8"}
        receipt = self._run(
            identity_observer=lambda arm: census_observation(
                arm, **{"sysfs.current_link_width": "8"}),
            intervention=iv)
        self.assertEqual(receipt["intervention_mode"], True)
        self.assertEqual(receipt["intervention"], iv)
        self.assertEqual(receipt["identity_problems_pre"], [])
        self.assertEqual(receipt["identity_problems_post"], [])

    def test_two_factor_intervention_rejected(self):
        called = []
        def execute(**kw):
            called.append(kw)
            return self._fake_execute()(**kw)
        iv = {"field": "negotiated_width", "expected_value": "x8"}
        with self.assertRaises(P.PhysicalDiagnosticError) as ctx:
            self._run(execute=execute,
                      identity_observer=lambda arm: census_observation(
                          arm, **{"sysfs.current_link_width": "8",
                                  "sysfs.max_link_width": "8"}),
                      intervention=iv)
        self.assertEqual(called, [])
        # the ONLY drift is the undeclared second factor
        self.assertIn("max_width", str(ctx.exception))
        self.assertNotIn("negotiated_width: observed", str(ctx.exception))

    def test_intervention_target_must_differ(self):
        called = []
        def execute(**kw):
            called.append(kw)
            return self._fake_execute()(**kw)
        iv = {"field": "negotiated_width",
              "expected_value": I.frozen_identity("B")["negotiated_width"]}
        with self.assertRaises(P.PhysicalDiagnosticError) as ctx:
            self._run(execute=execute, intervention=iv)
        self.assertEqual(called, [])
        self.assertIn("DIFFERS", str(ctx.exception))

    def test_identity_drift_fails_closed_before_launch(self):
        called = []
        def execute(**kw):
            called.append(kw)
            return self._fake_execute()(**kw)
        with self.assertRaises(P.PhysicalDiagnosticError) as ctx:
            self._run(execute=execute,
                      identity_observer=self._identity_drift)
        self.assertIn("identity drift", str(ctx.exception))
        self.assertEqual(called, [])  # probe list EMPTY when gate denied

    def test_case4096_requires_preauthorization(self):
        # Valid authority comment WITHOUT a case-4096 line: the regime
        # run of case-4096 must fail before launch.
        with self.assertRaises(P.PhysicalDiagnosticError) as ctx:
            P.run_diagnostic_unit(
                self.repo, self.root / "ev", "d248-fake", "regime",
                **self._run_kwargs(case="case-4096"))
        self.assertIn("case-4096", str(ctx.exception))

    def test_case4096_authorized_by_comment_line_runs(self):
        # Correction 4 POSITIVE: the authorization comes from the exact
        # stripped comment line parsed out of the live-fetched payload.
        def fetch(repo_root, expected_head, namespace, github_api):
            return make_authority(
                head=expected_head, namespace=namespace,
                body_extra=["case-4096:regime bracket extension"])
        receipt = P.run_diagnostic_unit(
            self.repo, self.root / "ev", "d248-fake", "regime",
            **self._run_kwargs(case="case-4096", revalidate_authority=fetch))
        self.assertIn("case4096", receipt["tag"])
        self.assertEqual(receipt["authority"]["case4096"]["reason"],
                         "regime bracket extension")
        self.assertEqual(receipt["authority"]["case4096"]["comment_id"],
                         123456)

    def test_case4096_dict_metadata_cannot_authorize(self):
        # Correction 4 OLD-DEFECT PROOF: an otherwise valid dispatch
        # comment WITHOUT a case-4096 line, plus an arbitrary
        # preauthorized_case4096 field injected into the in-memory
        # authority dict, must STILL fail before launch.
        def fetch(repo_root, expected_head, namespace, github_api):
            a = make_authority(head=expected_head, namespace=namespace)
            a["preauthorized_case4096"] = "case-4096:caller-manufactured"
            return a
        with self.assertRaises(P.PhysicalDiagnosticError) as ctx:
            P.run_diagnostic_unit(
                self.repo, self.root / "ev", "d248-fake", "regime",
                **self._run_kwargs(case="case-4096",
                                   revalidate_authority=fetch))
        self.assertIn("exact 'case-4096:<reason>' line", str(ctx.exception))

    def test_case4096_empty_reason_fails(self):
        with self.assertRaises(D.DiagnosticError) as ctx:
            D.validate_authority_payload(make_authority(
                body_extra=["case-4096:"]), HEAD)
        self.assertIn("empty reason", str(ctx.exception))

    def test_case4096_prose_mention_is_not_authorization(self):
        a = make_authority(body_extra=[
            "we discussed case-4096: maybe later"])
        out = D.validate_authority_payload(a, HEAD)
        self.assertIsNone(out["case4096"])  # not an exact stripped line

    def test_case4096_malformed_prefix_fails(self):
        for bad in ("case-4096 <reason>", "case4096:x", "case-4096",
                    "Case-4096:x"):
            a = make_authority(body_extra=[bad])
            out = D.validate_authority_payload(a, HEAD)
            self.assertIsNone(out["case4096"], bad)

    def test_case4096_duplicate_lines_fail(self):
        a = make_authority(body_extra=["case-4096:reason one",
                                       "case-4096:reason two"])
        with self.assertRaises(D.DiagnosticError) as ctx:
            D.validate_authority_payload(a, HEAD)
        self.assertIn("multiple conflicting case-4096", str(ctx.exception))

    def test_bad_authority_rejected_before_launch(self):
        called = []
        def execute(**kw):
            called.append(kw)
            return self._fake_execute()(**kw)
        def fetch(repo_root, expected_head, namespace, github_api):
            a = make_authority(head=expected_head, namespace=namespace)
            a["author_association"] = "CONTRIBUTOR"
            return a
        with self.assertRaises(D.DiagnosticError):
            self._run(execute=execute, revalidate_authority=fetch)
        self.assertEqual(called, [])

    def test_canonical_kind_requires_canonical_binary(self):
        with self.assertRaises(P.PhysicalDiagnosticError):
            P.run_diagnostic_unit(
                self.repo, self.root / "ev", "d248-fake", "canonical",
                **self._run_kwargs())

    def test_dirty_head_rejected(self):
        import issue248_diagnostic
        issue248_diagnostic.subprocess.run = FakeGit(HEAD, dirty=True)
        try:
            with self.assertRaises(D.DiagnosticError):
                self._run()
        finally:
            issue248_diagnostic.subprocess.run = FakeGit(HEAD)

    def test_no_overwrite_of_existing_unit(self):
        kw = self._run_kwargs()
        P.run_diagnostic_unit(self.repo, self.root / "ev", "d248-fake",
                              "repeat", **kw)
        with self.assertRaises(D.DiagnosticError):
            P.run_diagnostic_unit(self.repo, self.root / "ev", "d248-fake",
                                  "repeat", **kw)

    # --- Correction 2 negative controls: frozen request contract -------

    def _contract_case(self, contract):
        called = []
        def execute(**kw):
            called.append(kw)
            return self._fake_execute()(**kw)
        with self.assertRaises(D.DiagnosticError) as ctx:
            self._run(execute=execute, request_contract=contract)
        self.assertEqual(called, [])
        return ctx.exception

    def test_request_seed_change_no_launch(self):
        c = dict(D.REQUEST_CONTRACT, seed=42)
        self.assertIn("seed", str(self._contract_case(c)))

    def test_request_top_k_change_no_launch(self):
        c = dict(D.REQUEST_CONTRACT, top_k=20)
        self.assertIn("top_k", str(self._contract_case(c)))

    def test_request_sampler_list_change_no_launch(self):
        c = dict(D.REQUEST_CONTRACT, samplers=["top_k", "temp"])
        self.assertIn("samplers", str(self._contract_case(c)))

    def test_request_temperature_change_no_launch(self):
        c = dict(D.REQUEST_CONTRACT, temperature=0.7)
        self.assertIn("temperature", str(self._contract_case(c)))

    def test_request_n_predict_change_no_launch(self):
        c = dict(D.REQUEST_CONTRACT, n_predict=16)
        self.assertIn("n_predict", str(self._contract_case(c)))

    def test_request_cache_prompt_change_no_launch(self):
        c = dict(D.REQUEST_CONTRACT, cache_prompt=True)
        self.assertIn("cache_prompt", str(self._contract_case(c)))

    def test_request_stream_change_no_launch(self):
        c = dict(D.REQUEST_CONTRACT, stream=True)
        self.assertIn("stream", str(self._contract_case(c)))

    def test_request_return_tokens_change_no_launch(self):
        c = dict(D.REQUEST_CONTRACT, return_tokens=False)
        self.assertIn("return_tokens", str(self._contract_case(c)))

    def test_request_extra_semantic_key_no_launch(self):
        c = dict(D.REQUEST_CONTRACT, min_p=0.05)
        exc = str(self._contract_case(c))
        self.assertIn("extra semantic keys", exc)
        self.assertIn("min_p", exc)

    def test_request_equal_override_accepted(self):
        # An override EQUAL to the canonical contract is accepted and
        # the executed request is byte-identical to the frozen one.
        receipt = self._run(request_contract=dict(D.REQUEST_CONTRACT))
        self.assertEqual(receipt["request_contract"], D.REQUEST_CONTRACT)


class ReducerTests(unittest.TestCase):
    def _make_units(self, root: Path, ns: str, tags_tokens_rows):
        for tag, tokens, row_fill in tags_tokens_rows:
            unit = D.prepare_unit_dir(root, ns, tag)
            (unit / "response.json.raw").write_text(
                json.dumps({"tokens": list(tokens)}))
            (unit / "obs.meta.json").write_text("".join(
                json.dumps({"pos": d, "sampled_winner": t,
                            "forced_token": -1, "n_vocab": D.N_VOCB
                            if hasattr(D, "N_VOCB") else D.N_VOCAB}) + "\n"
                for d, t in enumerate(tokens)))
            for d in range(D.DECISIONS):
                (unit / f"obs.row{d}.f32").write_bytes(
                    struct.pack("<1f", row_fill[d]) * D.N_VOCAB)
            (unit / "unit.json").write_text(json.dumps({
                "schema": P.UNIT_SCHEMA, "tag": tag, "tokens": list(tokens)}))

    def test_derives_determinism_from_bytes(self):
        with tempfile.TemporaryDirectory() as td:
            root, ns = Path(td), "d248-reduce"
            toks = [328, 760, 324, 55965, 51624, 29014, 34227, 18030]
            self._make_units(root, ns, [
                ("case-3072-B-baseline-001", toks, [0.5] * 8),
                ("case-3072-B-baseline-002", toks, [0.5] * 8),
                ("case-3072-B-baseline-003", toks, [0.25] * 8),
            ])
            plan = {"probes": {"repeat": {"units": [
                "case-3072-B-baseline-001",
                "case-3072-B-baseline-002",
                "case-3072-B-baseline-003"]}}}
            r = P.derive_reduction(root, ns, plan)
            self.assertTrue(r["complete"])
            probe = r["probes"]["repeat"]
            self.assertTrue(probe["token_determinism"]["deterministic"])
            self.assertFalse(probe["row_determinism"]["deterministic"])

    def test_missing_unit_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root, ns = Path(td), "d248-reduce2"
            plan = {"probes": {"repeat": {"units": ["missing-unit"]}}}
            r = P.derive_reduction(root, ns, plan)
            self.assertFalse(r["complete"])
            self.assertTrue(any("missing" in p for p in r["problems"]))

    def test_receipt_token_forgery_caught(self):
        with tempfile.TemporaryDirectory() as td:
            root, ns = Path(td), "d248-reduce3"
            toks = [328, 760, 324, 55965, 51624, 29014, 34227, 18030]
            self._make_units(root, ns, [
                ("case-3072-B-baseline-001", toks, [0.5] * 8)])
            # forge the receipt tokens (raw bytes disagree)
            u = root / ns / "case-3072-B-baseline-001"
            doc = json.loads((u / "unit.json").read_text())
            doc["tokens"] = [1] * 8
            (u / "unit.json").write_text(json.dumps(doc))
            plan = {"probes": {"repeat": {"units": [
                "case-3072-B-baseline-001"]}}}
            r = P.derive_reduction(root, ns, plan)
            self.assertFalse(r["complete"])
            self.assertTrue(any("differ from raw" in p for p in r["problems"]))


class ProhibitionTests(unittest.TestCase):
    def test_no_predictive_or_holdout_capability(self):
        """The tooling must be structurally unable to reach c237/holdout."""
        src = (REPO / "scripts/issue248_diagnostic.py").read_text()
        src += (REPO / "scripts/issue248_physical.py").read_text()
        # c237 appears only as the namespace guard
        self.assertEqual(src.count("c237"), 1)
        self.assertIn('"c237-"', src)
        self.assertNotIn("decrypt", src)
        self.assertNotIn("holdout_plaintext", src)
        # no predictive namespace can pass the validator
        for ns in ("d248-c237-5", "d248-c237-x9"):
            with self.assertRaises(D.DiagnosticError):
                D.validate_namespace(ns)
        # no threshold machinery: the module has no numeric epsilon
        # constants to tune (determinism is digest equality only)
        self.assertNotIn("epsilon", src)
        self.assertNotIn("tolerance", src)
        # no imports from the unmerged qualification branch's producers:
        # the diagnostic tooling is self-contained on main
        for forbidden_import in ("import issue241_dispatch",
                                 "from issue241_dispatch",
                                 "import issue241_constants",
                                 "from issue241_constants",
                                 "import issue241_comparator",
                                 "from issue241_comparator"):
            self.assertNotIn(forbidden_import, src)

    def test_terminals_exact_vocabulary(self):
        self.assertEqual(D.TERMINALS, (
            "R8I3_REF_VULKAN_NONDETERMINISM_LOCALIZED",
            "R8I3_REF_OBSERVER_PERTURBATION_LOCALIZED",
            "R8I3_REF_PLATFORM_INSTABILITY_LOCALIZED",
            "R8I3_REF_NONDETERMINISM_UNRESOLVED",
            "R8I3_REF_NONDETERMINISM_NOT_REPRODUCED"))

    def test_analyzer_constants_bind_accepted_campaign(self):
        import issue248_analysis as A
        self.assertEqual(A.ACCEPTED_CAMPAIGN_HEAD,
                         "4e8b4fc369defe409f68da46e26d152eade4df47")
        self.assertEqual(A.REPORTED_LIVE_MANIFEST_SELF_DIGEST,
                         "78400bcfe9de5464fdbceca9c05c9eb1938ccd3487d7d053043d5be50a52a0eb")
        self.assertEqual(A.ISSUE_QUOTED_MANIFEST_SELF_DIGEST,
                         "a5d7f02d44c694034738f5cb55c22c257b0b0f488a3e50ba8a71924f8df62e32")


class AnalyzerMutationTests(unittest.TestCase):
    """Negative controls for the Phase-0 analyzer against sandbox copies.

    Builds a COMPLETE synthetic evidence root (all four analyzed pairs)
    with a small patched vocabulary so tests run in milliseconds; the
    production vocabulary is pinned by
    ProhibitionTests.test_analyzer_constants_bind_accepted_campaign and
    by the real-root run retained in the evidence area.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        # shrink the vocabulary for test speed
        import issue248_analysis as A
        self._A = A
        self._orig_vocab = (A.N_VOCAB, A.ROW_BYTES)
        A.N_VOCAB = 4
        A.ROW_BYTES = 16
        self.root = Path(self._tmp.name) / "root"
        self.root.mkdir()
        toks = [328, 760, 324, 55965, 51624, 29014, 34227, 18030]
        for case in ("case-256", "case-1024", "case-3072"):
            cdir = self.root / "phase3" / case
            cdir.mkdir(parents=True)
            for arm, modes in (("B", ("baseline", "repeat")),
                               ("C", ("candidate", "repeat"))):
                for mode in modes:
                    tag = f"{case}-{arm}-{mode}"
                    (cdir / f"{tag}.meta.json").write_text("".join(
                        json.dumps({"pos": d, "sampled_winner": t,
                                    "forced_token": -1, "n_vocab": 4})
                        + "\n" for d, t in enumerate(toks)))
                    (cdir / f"{tag}.response.json").write_text(
                        json.dumps({"tokens": toks}))
                    for d in range(8):
                        fill = 0.5
                        if case == "case-3072" and arm == "B":
                            fill = 0.5 if mode == "baseline" else 0.5 + d * 0.01
                        (cdir / f"{tag}.row{d}.f32").write_bytes(
                            struct.pack("<4f", fill, fill, fill, fill))
        (self.root / "phase0-pre.json").write_text(json.dumps({
            "schema": "inferswarm.issue241.phase0-preservation-audit/1",
            "head": "4e8b4fc369defe409f68da46e26d152eade4df47",
            "problems": [], "subject_generation": 2}))
        self._regen_manifest()

    def _regen_manifest(self):
        rows = []
        for p in sorted(self.root.rglob("*")):
            if p.is_file() and p.name != "SHA256SUMS":
                rel = ("phase0-pre.json" if p.name == "phase0-pre.json"
                       else f"phase3/{p.parent.name}/{p.name}")
                rows.append(
                    f"{hashlib.sha256(p.read_bytes()).hexdigest()}  ./{rel}")
        (self.root / "SHA256SUMS").write_text("\n".join(rows) + "\n")

    def tearDown(self):
        self._A.N_VOCAB, self._A.ROW_BYTES = self._orig_vocab
        self._tmp.cleanup()

    def _run(self):
        return self._A.run_analysis(self.root)

    def test_positive_analysis_passes(self):
        result = self._run()
        self.assertTrue(result["accepted_head_binding"]["clean"])
        self.assertTrue(
            result["pairs"]["case-256-B"]["all_decisions_byte_identical"])
        self.assertTrue(
            result["pairs"]["case-1024-B"]["all_decisions_byte_identical"])
        self.assertTrue(
            result["pairs"]["case-3072-C"]["all_decisions_byte_identical"])
        pair = result["pairs"]["case-3072-B"]
        self.assertFalse(pair["all_decisions_byte_identical"])
        self.assertTrue(pair["observer_winners"]["equal"])
        self.assertTrue(pair["response_tokens"]["equal"])

    def test_manifest_mutation_fails_closed(self):
        p = (self.root / "phase3/case-3072/"
             "case-3072-B-baseline.row0.f32")
        p.write_bytes(struct.pack("<4f", 9.9, 9.9, 9.9, 9.9))
        with self.assertRaises(self._A.CustodyError):
            self._run()

    def test_head_binding_mutation_fails_closed(self):
        doc = json.loads((self.root / "phase0-pre.json").read_text())
        doc["head"] = "f" * 40
        (self.root / "phase0-pre.json").write_text(json.dumps(doc))
        self._regen_manifest()  # competent forgery: custody re-consistent
        with self.assertRaises(self._A.CustodyError):
            self._run()

    def test_row_length_mutation_fails_closed(self):
        p = (self.root / "phase3/case-3072/"
             "case-3072-B-baseline.row0.f32")
        p.write_bytes(b"\x00" * 8)
        self._regen_manifest()
        with self.assertRaises(Exception):
            self._run()


A_HEAD = "4e8b4fc369defe409f68da46e26d152eade4df47"


class FakeCommand:
    def __init__(self, journal="2026-09-24T12:00:30-04:00 host kernel: normal\n", smi="GPU-TEST, 41, 75.0, 250.0, 0x0\n",
                 journal_rc=0, smi_rc=0):
        self.journal = journal.encode()
        self.smi = smi.encode()
        self.journal_rc = journal_rc
        self.smi_rc = smi_rc
        self.calls = []

    def __call__(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        if argv[0] == "journalctl":
            return H.CommandResult(self.journal_rc, self.journal, b"")
        if argv[0] == "nvidia-smi":
            return H.CommandResult(self.smi_rc, self.smi, b"")
        raise AssertionError(argv)


class Issue248HealthTests(unittest.TestCase):
    START = "2026-09-24T12:00:00-04:00"
    END = "2026-09-24T12:01:00-04:00"

    def capture(self, tmp, command, samples=None):
        return H.capture_platform_health(
            Path(tmp), self.START, self.END, runner=command,
            samples=samples if samples is not None else [
                {"stage": stage, "captured_at": "2026-09-24T12:00:30-04:00"}
                for stage in ("before", "during", "after")])

    def test_capture_uses_bounded_read_only_commands_and_retains_raw(self):
        journal = "2026-09-24T12:00:30-04:00 host kernel: normal\n"
        command = FakeCommand(journal)
        with tempfile.TemporaryDirectory() as tmp:
            receipt = self.capture(tmp, command)
            self.assertEqual(receipt["window"], {"start": self.START, "end": self.END})
            self.assertEqual(len(receipt["artifacts"]), 3)
            for artifact in receipt["artifacts"]:
                raw = (Path(tmp) / artifact["path"]).read_bytes()
                self.assertEqual(artifact["bytes"], len(raw))
                self.assertEqual(artifact["sha256"], hashlib.sha256(raw).hexdigest())
            self.assertEqual([c[0][0] for c in command.calls], ["journalctl", "nvidia-smi"])
            self.assertIn("--since", command.calls[0][0])
            self.assertIn("--until", command.calls[0][0])
            self.assertIn("-k", command.calls[0][0])
            self.assertIn("--no-pager", command.calls[0][0])

    def test_successful_empty_kernel_window_is_retained_negative_proof(self):
        with tempfile.TemporaryDirectory() as tmp:
            receipt = self.capture(tmp, FakeCommand(journal=""))
            self.assertEqual((Path(tmp) / "kernel-journal.raw").read_bytes(), b"")
            result = H.verify_platform_health(Path(tmp), receipt)
            self.assertTrue(result["valid"])
            self.assertEqual(result["fatal_findings"], [])

    def test_nonzero_collection_fails_closed_without_fallback(self):
        command = FakeCommand(journal_rc=1)
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(H.PlatformHealthError):
                self.capture(tmp, command)
            self.assertEqual(len(command.calls), 1)

    def test_journal_outside_or_unparseable_window_is_rejected(self):
        for row in (
            "2026-09-24T12:01:01-04:00 host kernel: late\n",
            "host kernel: timestamp missing\n",
        ):
            with self.subTest(row=row), tempfile.TemporaryDirectory() as tmp:
                with self.assertRaises(H.PlatformHealthError):
                    self.capture(tmp, FakeCommand(row))

    def test_sample_population_must_cover_all_execution_stages(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(H.PlatformHealthError):
                self.capture(tmp, FakeCommand(), [{"stage": "before"}, {"stage": "after"}])

    def test_sample_stage_order_and_monotonic_time_are_required(self):
        stamps = ("2026-09-24T12:00:10-04:00",
                  "2026-09-24T12:00:20-04:00",
                  "2026-09-24T12:00:30-04:00")
        for stages, times in (
                (("after", "during", "before"), stamps),
                (("before", "during", "after"), tuple(reversed(stamps)))):
            with self.subTest(stages=stages, times=times), tempfile.TemporaryDirectory() as tmp:
                bad = [{"stage": stage, "captured_at": when}
                       for stage, when in zip(stages, times)]
                with self.assertRaises(H.PlatformHealthError):
                    self.capture(tmp, FakeCommand(), bad)

    def test_verifier_rehashes_raw_bytes_not_receipt_or_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            receipt = self.capture(tmp, FakeCommand())
            receipt["fatal_states"] = ["forged clean/fatal summary"]
            self.assertTrue(H.verify_platform_health(Path(tmp), receipt)["valid"])
            artifact = receipt["artifacts"][0]
            (Path(tmp) / artifact["path"]).write_bytes(b"x" * artifact["bytes"])
            verified = H.verify_platform_health(Path(tmp), receipt)
            self.assertFalse(verified["valid"])
            self.assertIn("sha256 mismatch", " ".join(verified["problems"]))

    def test_receipt_path_traversal_and_receipt_window_tampering_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            receipt = self.capture(tmp, FakeCommand())
            changed = json.loads(json.dumps(receipt))
            changed["artifacts"][0]["path"] = "../escape"
            self.assertFalse(H.verify_platform_health(Path(tmp), changed)["valid"])
            changed = json.loads(json.dumps(receipt))
            changed["window"]["end"] = self.START
            self.assertFalse(H.verify_platform_health(Path(tmp), changed)["valid"])

    def test_fatal_predicates_come_from_raw_causal_evidence(self):
        journal = ("2026-09-24T12:00:30-04:00 host kernel: NVRM: Xid (PCI:0000:03:00): 79, GPU has fallen off the bus\n"
                   "2026-09-24T12:00:31-04:00 host kernel: pcieport 0000:00:01.0: AER: Uncorrected (Fatal)\n")
        with tempfile.TemporaryDirectory() as tmp:
            receipt = self.capture(tmp, FakeCommand(journal))
            verified = H.verify_platform_health(Path(tmp), receipt)
            self.assertTrue(verified["valid"])
            self.assertEqual({f["kind"] for f in verified["fatal_findings"]}, {"NVIDIA_XID", "PCIe_AER_FATAL", "GPU_DEVICE_LOST"})

    def test_unrelated_gpu_xid_does_not_identify_subject_instability(self):
        journal = ("2026-09-24T12:00:30-04:00 host kernel: "
                   "NVRM: Xid (PCI:0000:04:00): 79\n")
        with tempfile.TemporaryDirectory() as tmp:
            receipt = self.capture(tmp, FakeCommand(journal))
            verified = H.verify_platform_health(
                Path(tmp), receipt, expected_gpu_uuid="GPU-TEST",
                expected_bdf="00000000:03:00.0")
            self.assertTrue(verified["valid"])
            self.assertEqual(verified["fatal_findings"], [])

    def test_unrelated_telemetry_uuid_blocks_subject_proof(self):
        with tempfile.TemporaryDirectory() as tmp:
            receipt = self.capture(tmp, FakeCommand())
            verified = H.verify_platform_health(
                Path(tmp), receipt, expected_gpu_uuid="GPU-OTHER",
                expected_bdf="00000000:03:00.0")
            self.assertFalse(verified["valid"])

    def test_numeric_temperature_and_power_are_observations_not_thresholds(self):
        command = FakeCommand(smi="GPU-TEST, 99, 249.0, 250.0, 0x0\n")
        with tempfile.TemporaryDirectory() as tmp:
            receipt = self.capture(tmp, command)
            verified = H.verify_platform_health(Path(tmp), receipt)
            self.assertTrue(verified["valid"])
            self.assertEqual(verified["fatal_findings"], [])
            self.assertEqual(verified["telemetry"][0]["temperature.gpu"], 99.0)
            self.assertEqual(verified["telemetry"][0]["power.draw"], 249.0)

    def test_nvidia_driver_active_thermal_limit_is_raw_driver_evidence(self):
        samples = [{"stage": stage, "captured_at": "2026-09-24T12:00:30-04:00",
                    "nvidia_smi_raw": "GPU-TEST, 70, 100.0, 250.0, "
                    + ("0x20" if stage == "during" else "0x0") + "\n"}
                   for stage in ("before", "during", "after")]
        with tempfile.TemporaryDirectory() as tmp:
            receipt = self.capture(tmp, FakeCommand(), samples)
            verified = H.verify_platform_health(Path(tmp), receipt,
                                                expected_gpu_uuid="GPU-TEST",
                                                expected_arm="B")
            self.assertEqual([f["kind"] for f in verified["fatal_findings"]],
                             ["NVIDIA_THERMAL_LIMIT_ACTIVE"])

    def test_amd_hwmon_retains_available_driver_sensor_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            hwmon = Path(tmp) / "hwmon0"
            hwmon.mkdir()
            for name, value in (("temp1_input", "65000\n"),
                                ("temp1_crit", "95000\n"),
                                ("power1_average", "75000000\n"),
                                ("power1_cap", "150000000\n")):
                (hwmon / name).write_text(value)
            observation = H.read_amd_hwmon(Path(tmp))
            self.assertEqual(observation["temp1_input"], "65000\n")
            self.assertEqual(observation["power1_average"], "75000000\n")
            self.assertEqual(observation["temp1_crit"], "95000\n")
            self.assertEqual(observation["power1_cap"], "150000000\n")

    def test_amd_driver_critical_sensor_threshold_is_a_raw_violation(self):
        samples = [{"stage": stage,
                    "captured_at": "2026-09-24T12:00:30-04:00",
                    "amd_hwmon_raw": {
                        "temp1_input": "100000\n", "temp1_crit": "95000\n",
                        "power1_average": "160000000\n",
                        "power1_crit": "150000000\n"}}
                   for stage in ("before", "during", "after")]
        with tempfile.TemporaryDirectory() as tmp:
            receipt = self.capture(tmp, FakeCommand(), samples)
            observed = H.verify_platform_health(Path(tmp), receipt,
                                                 expected_arm="C")
            self.assertTrue(observed["valid"])
            self.assertEqual({f["kind"] for f in observed["fatal_findings"]},
                             {"AMD_THERMAL_CRITICAL", "AMD_POWER_CRITICAL"})

    def test_missing_amd_driver_sensors_block_arm_c(self):
        with tempfile.TemporaryDirectory() as tmp:
            receipt = self.capture(tmp, FakeCommand())
            self.assertFalse(H.verify_platform_health(
                Path(tmp), receipt, expected_arm="C")["valid"])

    def test_reference_arm_requires_in_window_driver_samples(self):
        with tempfile.TemporaryDirectory() as tmp:
            receipt = self.capture(tmp, FakeCommand())
            verified = H.verify_platform_health(Path(tmp), receipt,
                                                expected_gpu_uuid="GPU-TEST",
                                                expected_arm="B")
            self.assertFalse(verified["valid"])

    def test_post_window_driver_throttle_is_not_causal(self):
        command = FakeCommand(smi="GPU-TEST, 70, 100.0, 250.0, 0x80\n")
        with tempfile.TemporaryDirectory() as tmp:
            receipt = self.capture(tmp, command)
            observed = H.verify_platform_health(Path(tmp), receipt)
            self.assertTrue(observed["valid"])
            self.assertFalse(observed["fatal_findings"])

    def test_in_window_driver_throttle_is_causal_from_sample_bytes(self):
        command = FakeCommand()
        samples = [{"stage": stage, "captured_at": "2026-09-24T12:00:30-04:00",
                    "nvidia_smi_raw": "GPU-TEST, 41, 75.0, 250.0, "
                    + ("0x80" if stage == "during" else "0x0") + "\n"}
                   for stage in ("before", "during", "after")]
        with tempfile.TemporaryDirectory() as tmp:
            receipt = self.capture(tmp, command, samples)
            observed = H.verify_platform_health(Path(tmp), receipt,
                                                 expected_gpu_uuid="GPU-TEST",
                                                 expected_arm="B")
            self.assertTrue(observed["valid"])
            self.assertIn("NVIDIA_POWER_BRAKE_ACTIVE",
                          {x["kind"] for x in observed["fatal_findings"]})

    def test_nvidia_driver_thermal_limit_is_raw_in_window_evidence(self):
        samples = [{"stage": stage, "captured_at": "2026-09-24T12:00:30-04:00",
                    "nvidia_smi_raw": "GPU-TEST, 70, 100.0, 250.0, "
                    + ("0x40" if stage == "during" else "0x0") + "\n"}
                   for stage in ("before", "during", "after")]
        with tempfile.TemporaryDirectory() as tmp:
            receipt = self.capture(tmp, FakeCommand(), samples)
            verified = H.verify_platform_health(Path(tmp), receipt,
                                                expected_gpu_uuid="GPU-TEST",
                                                expected_arm="B")
            self.assertEqual([f["kind"] for f in verified["fatal_findings"]],
                             ["NVIDIA_THERMAL_LIMIT_ACTIVE"])

    def test_explicit_fatal_sample_fields_are_derived_from_retained_raw(self):
        samples = [
            {"stage": stage, "captured_at": "2026-09-24T12:00:30-04:00",
             "telemetry": {"ecc_uncorrected": 1} if stage == "during" else {}}
            for stage in ("before", "during", "after")]
        with tempfile.TemporaryDirectory() as tmp:
            receipt = self.capture(tmp, FakeCommand(), samples)
            verified = H.verify_platform_health(Path(tmp), receipt)
            self.assertEqual([f["kind"] for f in verified["fatal_findings"]],
                             ["ECC_UNCORRECTED"])

    def test_forged_journal_command_window_binding_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            receipt = self.capture(tmp, FakeCommand())
            receipt["collection"]["kernel_journal"]["argv"][2] = "2026-09-23T12:00:00-04:00"
            (Path(tmp) / "platform-health-receipt.json").write_text(
                json.dumps(receipt, indent=2, sort_keys=True) + "\n")
            result = H.verify_platform_health(Path(tmp), receipt)
            self.assertFalse(result["valid"])
            self.assertIn("journal collection", " ".join(result["problems"]))

    def test_missing_samples_and_kernel_artifacts_block(self):
        for kind in ("producer_samples", "kernel_journal"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as tmp:
                receipt = self.capture(tmp, FakeCommand())
                artifact = next(a for a in receipt["artifacts"]
                                if a["kind"] == kind)
                (Path(tmp) / artifact["path"]).unlink()
                result = H.verify_platform_health(Path(tmp), receipt)
                self.assertFalse(result["valid"])
                self.assertIn("missing", " ".join(result["problems"]))

    def test_malformed_samples_block_even_if_digest_is_forged(self):
        with tempfile.TemporaryDirectory() as tmp:
            receipt = self.capture(tmp, FakeCommand())
            path = Path(tmp) / "device-samples.json"
            path.write_bytes(b"{not-json}")
            self._forge_receipt(tmp, receipt, "producer_samples")
            result = H.verify_platform_health(Path(tmp), receipt)
            self.assertFalse(result["valid"])

    def test_competent_window_forgery_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            receipt = self.capture(tmp, FakeCommand())
            path = Path(tmp) / "device-samples.json"
            samples = json.loads(path.read_bytes())
            samples[0]["captured_at"] = "2026-09-23T12:00:30-04:00"
            path.write_text(json.dumps(samples))
            self._forge_receipt(tmp, receipt, "producer_samples")
            result = H.verify_platform_health(Path(tmp), receipt)
            self.assertFalse(result["valid"])
            self.assertIn("outside requested window", " ".join(result["problems"]))

    @staticmethod
    def _forge_receipt(tmp, receipt, kind):
        entry = next(a for a in receipt["artifacts"] if a["kind"] == kind)
        raw = (Path(tmp) / entry["path"]).read_bytes()
        entry["bytes"] = len(raw)
        entry["sha256"] = hashlib.sha256(raw).hexdigest()
        (Path(tmp) / "platform-health-receipt.json").write_text(
            json.dumps(receipt, indent=2, sort_keys=True) + "\n")

    def test_missing_or_forged_artifact_receipt_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            receipt = self.capture(tmp, FakeCommand())
            receipt["artifacts"][1]["bytes"] += 1
            result = H.verify_platform_health(Path(tmp), receipt)
            self.assertFalse(result["valid"])
            self.assertTrue(any("receipt artifacts differs" in p for p in result["problems"]))



NS = "d248-terminal-fixture"
ROW_BYTES = T.ROW_BYTES
TOKENS = [1, 2, 3, 4, 5, 6, 7, 8]
STAMP0 = "2026-09-24T12:00:00+00:00"
STAMP1 = "2026-09-24T12:01:00+00:00"
# Round-3 dispatch provenance: one authoritative live dispatch payload
# per frozen probe namespace (each phase is separately authorized by an
# exact diagnostic-namespace scope line in its own OWNER/MEMBER comment).
DISPATCH_HEAD = "a" * 40
DISPATCH_COMMENT_ID = 5821999901


def dispatch_payload(namespace: str, *, head: str = DISPATCH_HEAD,
                     comment_id: int = DISPATCH_COMMENT_ID,
                     body_extra: list[str] | None = None,
                     author_association: str = "MEMBER",
                     open_pr: bool = True, issue_open: bool = True) -> dict:
    return make_authority(head=head, namespace=namespace,
                          comment_id=comment_id,
                          author_association=author_association,
                          open_pr=open_pr, issue_open=issue_open,
                          body_extra=body_extra)


def dispatch_map(**overrides) -> dict:
    """The namespace-keyed LIVE dispatch authority map for the fixture."""
    out = {}
    for namespace in set(T.FROZEN_PROBE_NAMESPACE.values()):
        out[namespace] = dispatch_payload(namespace, **overrides)
    return out


def tag(variant: str, index: int) -> str:
    return f"case-3072-B-{variant}-{index:03d}"


def token_digest(tokens):
    try:
        packed = struct.pack("<8I", *tokens)
    except struct.error:
        packed = json.dumps(tokens, separators=(",", ":")).encode()
    return hashlib.sha256(packed).hexdigest()


def plan():
    repeat = [tag("baseline", i) for i in range(1, 6)]
    observer = [tag("obs-comparator", i) for i in (1, 2)]
    placement = [tag(f"ngl{rung}", i) for rung in (1, 2, 4, 6, 8)
                 for i in (1, 2)]
    regime = [f"case-{case}-B-regime-{case}-{i:03d}"
              for case in (256, 1024, 3072) for i in (1, 2)]
    canonical = [tag("canonical", i) for i in (1, 2)]
    return {"probes": {"repeat": {"units": repeat,
                                  "namespace": T.FROZEN_PROBE_NAMESPACE["repeat"]},
                        "observer": {"units": observer,
                                     "namespace": T.FROZEN_PROBE_NAMESPACE["observer"]},
                        "canonical": {"units": canonical,
                                      "namespace": T.FROZEN_PROBE_NAMESPACE["canonical"]},
                        "placement": {"units": placement,
                                      "namespace": T.FROZEN_PROBE_NAMESPACE["placement"]},
                        "regime": {"units": regime,
                                   "namespace": T.FROZEN_PROBE_NAMESPACE["regime"]}}}


def health_runner(argv, **_kwargs):
    if argv[0] == "journalctl":
        return H.CommandResult(0, b"")
    return H.CommandResult(0, (
        "GPU-d5c05739-96c1-7e49-89b6-bf54c2121c55, "
        "40, 20, 170, 0\n").encode())


def fake_execute_seam(tokens=(328, 760, 324, 55965, 51624, 29014,
                              34227, 18030)):
    """Module-level fake execute seam (shared by the TOCTOU controls)."""
    def execute(argv, env, arm, request, prompt, port, unit_dir):
        raw = json.dumps({"tokens": list(tokens)}).encode()
        (unit_dir / "obs.meta.json").write_text("".join(
            json.dumps({"pos": d, "sampled_winner": t,
                        "forced_token": -1, "n_vocab": D.N_VOCAB}) + "\n"
            for d, t in enumerate(tokens)))
        for d in range(D.DECISIONS):
            (unit_dir / f"obs.row{d}.f32").write_bytes(
                struct.pack("<1f", 0.5) * D.N_VOCAB)
        stamp = datetime.now(timezone.utc).isoformat()
        return {"tokens": list(tokens), "response_raw": raw,
                "process_attribution": {"server_pid": 42,
                                        "server_exe_sha256": D.SERVER_BINARIES["comparator"],
                                        "server_argv": argv,
                                        "server_env": env},
                "device_samples": [{"stage": stage, "captured_at": stamp,
                                    "nvidia_smi_raw": (
                                        f"{I.REFERENCE_IDENTITY['gpu_uuid']}, "
                                        "40, 20, 170, 0\n")}
                                   for stage in ("before", "during", "after")]}
    return execute


class RetainedTerminalMatrix(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        for namespace in set(T.FROZEN_PROBE_NAMESPACE.values()):
            (self.root / namespace).mkdir()
        self.base = self.root / T.FROZEN_PROBE_NAMESPACE["repeat"]
        self.p = plan()
        self.dispatch = dispatch_map()
        tags = set()
        for probe in self.p["probes"].values():
            tags.update(probe["units"])
        for variant in T.VARIANTS:
            tags.update(tag(variant, i) for i in (1, 2))
        self.tags = sorted(tags)
        for unit in self.tags:
            self.write_unit(unit)

    def tearDown(self):
        self.tmp.cleanup()

    def unit_dir(self, unit):
        family = ("placement" if "-ngl" in unit else
                  "regime" if "-regime-" in unit or "-case4096-" in unit else
                  "observer" if "-obs-" in unit or "-canonical-" in unit else
                  "repeat")
        return self.root / T.FROZEN_PROBE_NAMESPACE[family] / unit

    def write_unit(self, unit, *, row_seed=b"a", tokens=None, fatal=False,
                   case_id=None, arm="B", kind=None, raw_mutate=False,
                   rowless=None, authority=None):
        d = self.unit_dir(unit)
        d.mkdir(parents=True, exist_ok=True)
        tokens = list(TOKENS if tokens is None else tokens)
        if case_id is None:
            import re
            m = re.search(r"case-(\d+)", unit)
            case_id = f"case-{m.group(1)}" if m else "case-3072"
        if kind is None:
            kind = ("repeat" if "baseline" in unit else
                    "rung" if "ngl" in unit else
                    "regime" if "regime" in unit or "case4096" in unit else
                    "canonical" if "canonical" in unit else "observer")
        # Round 3: every unit receipt carries the canonical dispatch
        # authority block derived from this namespace's live payload.
        if authority is None:
            authority = D.unit_authority_block(
                self.dispatch[d.parent.name])
        raw = (json.dumps({"tokens": tokens}, separators=(",", ":")) + "\n").encode()
        (d / "response.json.raw").write_bytes(raw)
        receipt = {"schema": "inferswarm.issue248.diagnostic-unit/1",
                   "kind": kind, "namespace": d.parent.name, "tag": unit,
                   "case_id": case_id, "arm": arm, "ngl": 8,
                   "binary_id": ("canonical" if kind == "canonical" else
                                 "r8e-obs" if "obs-r8e" in unit else "comparator"),
                   "binary_sha256": D.SERVER_BINARIES[(
                       "canonical" if kind == "canonical" else
                       "r8e-obs" if "obs-r8e" in unit else "comparator")],
                   "tokens": tokens, "deterministic_output_sha256": token_digest(tokens),
                   "response_raw_sha256": hashlib.sha256(raw).hexdigest(),
                   "server_argv": D.server_argv(
                       Path("/accepted/llama-server"),
                       Path(D.MODEL_DIR) / D.MODEL_MEMBER_1,
                       (int(unit.split("ngl", 1)[1].split("-", 1)[0])
                        if "-ngl" in unit else 8), 19000),
                   "model_dir": D.MODEL_DIR,
                   "model_launch_member": str(Path(D.MODEL_DIR) / D.MODEL_MEMBER_1),
                   "request_contract": dict(D.REQUEST_CONTRACT),
                   "request_contract_sha256": D.canonical_request_digest(D.REQUEST_CONTRACT),
                   "model_members_sha256": dict(D.MODEL_MEMBER_SHA256),
                   "server_env": {"CUDA_VISIBLE_DEVICES": "-1"},
                   "observer_mode": ("comparator-off" if "obs-off" in unit else
                                     "comparator-dual" if "obs-dual" in unit else
                                     "r8e-only" if "obs-r8e" in unit else "comparator"),
                   "identity_problems_pre": [], "identity_problems_post": [],
                   "intervention": None,
                   "authority": authority}
        if "ngl" in unit:
            receipt["ngl"] = int(unit.split("ngl", 1)[1].split("-", 1)[0])
        if "regime" in unit:
            receipt["kind"] = "regime"
        mode = receipt["observer_mode"]
        env = D.launch_env(
            "B", icd=I.frozen_identity("B")["icd"],
            selector=dict(I.frozen_identity("B")["selector"]),
            observer=("comparator" if mode.startswith("comparator") else "r8e-only"),
            out_prefix=d / "obs", force=None,
            r8e_capture=(mode == "comparator-dual"))
        if mode == "comparator-off":
            env = {key: value for key, value in env.items()
                   if not key.startswith("LLAMA_OBSERVE")}
        receipt["server_env"] = {key: value for key, value in env.items()
                                 if key.startswith(("LLAMA_", "VK_", "CUDA_"))}
        receipt["process_attribution"] = {
            "server_pid": 42,
            "server_exe_sha256": receipt["binary_sha256"],
            "server_argv": receipt["server_argv"],
            "server_env": env,
        }
        (d / "unit.json").write_text(json.dumps(receipt, sort_keys=True))
        identity = identity_ok("B")
        (d / "identity-pre.json").write_text(json.dumps(identity))
        (d / "identity-post.json").write_text(json.dumps(identity))
        if rowless is None:
            rowless = ("canonical" in unit or "obs-off" in unit
                       or "obs-r8e" in unit)
        if not rowless:
            rows = []
            for decision in range(8):
                row = (row_seed[:1] + bytes([decision])
                       + b"\0" * (T.ROW_BYTES - 2))
                rows.append(row)
                (d / f"obs.row{decision}.f32").write_bytes(row)
            (d / "obs.meta.json").write_text("".join(
                json.dumps({"pos": i, "sampled_winner": tokens[i] if i < len(tokens) else -1,
                            "forced_token": -1, "n_vocab": 248320}) + "\n"
                for i in range(8)))
            receipt["observer_rows"] = [hashlib.sha256(r).hexdigest() for r in rows]
            receipt["observer_meta_sha256"] = hashlib.sha256(
                (d / "obs.meta.json").read_bytes()).hexdigest()
            (d / "unit.json").write_text(json.dumps(receipt, sort_keys=True))
        if "obs-dual" in unit:
            row = row_seed[:1] + bytes([0]) + b"\0" * (T.ROW_BYTES - 2)
            (d / "capture.r8e.pos0.f32").write_bytes(row)
            receipt["r8e_row0_sha256"] = hashlib.sha256(row).hexdigest()
        if "obs-r8e" in unit:
            row = row_seed[:1] + bytes([0]) + b"\0" * (T.ROW_BYTES - 2)
            (d / "capture.r8e.pos0.f32").write_bytes(row)
            receipt["r8e_row0_sha256"] = hashlib.sha256(row).hexdigest()
        samples = [{"stage": stage, "captured_at": stamp,
                    "nvidia_smi_raw": (
                        "GPU-d5c05739-96c1-7e49-89b6-bf54c2121c55, "
                        "40, 20, 170, 0\n")}
                   for stage, stamp in (("before", STAMP0), ("during", STAMP0), ("after", STAMP1))]
        if fatal:
            samples[1]["xid_code"] = 79
        if not (d / "platform-health-receipt.json").exists():
            H.capture_platform_health(d, STAMP0, STAMP1, samples=samples,
                                      runner=health_runner)
        health_raw = (d / "platform-health-receipt.json").read_bytes()
        health = json.loads(health_raw)
        receipt["platform_health"] = health
        receipt["platform_health_receipt"] = {
            "path": "platform-health-receipt.json", "bytes": len(health_raw),
            "sha256": hashlib.sha256(health_raw).hexdigest(),
            "window": health["window"]}
        (d / "unit.json").write_text(json.dumps(receipt, sort_keys=True))

    def derive(self, p=None, dispatch=None, case4096_authority=None,
               health_verifier=None):
        return T.derive_terminal(self.root, NS, p or self.p,
                                 dispatch_authority=(
                                     self.dispatch if dispatch is None
                                     else dispatch),
                                 case4096_authority=case4096_authority,
                                 health_verifier=health_verifier)

    def test_population_requires_exactly_eight_integer_tokens(self):
        unit = self.p["probes"]["repeat"]["units"][0]
        self.write_unit(unit, tokens=[1, 2])
        out = self.derive()
        self.assertIsNone(out["terminal"])
        self.assertEqual(out["blocked"], T.BLOCKED)
        self.assertTrue(any("eight" in problem.lower() or "8" in problem
                            for problem in out["problems"]))

    def test_raw_response_receipt_digest_binding_is_required(self):
        unit = self.p["probes"]["repeat"]["units"][0]
        p = self.unit_dir(unit) / "response.json.raw"
        p.write_bytes(p.read_bytes() + b" ")
        out = self.derive()
        self.assertIsNone(out["terminal"])
        self.assertEqual(out["blocked"], T.BLOCKED)

    def test_row_digest_must_match_receipt_binding(self):
        unit = self.p["probes"]["repeat"]["units"][0]
        (self.unit_dir(unit) / "obs.row0.f32").write_bytes(b"zz")
        out = self.derive()
        self.assertIsNone(out["terminal"])
        self.assertEqual(out["blocked"], T.BLOCKED)

    def test_five_repeat_units_and_two_per_phase_two_level_required(self):
        for probes, short in (("repeat", 4), ("placement", 9), ("regime", 5)):
            p = json.loads(json.dumps(self.p))
            p["probes"][probes]["units"] = p["probes"][probes]["units"][:short]
            out = self.derive(p)
            self.assertIsNone(out["terminal"], probes)
            self.assertEqual(out["blocked"], T.BLOCKED, probes)

    def test_case4096_is_blocked_without_comment_bound_authorization(self):
        p = json.loads(json.dumps(self.p))
        optional = ["case-4096-B-case4096-001", "case-4096-B-case4096-002"]
        p["probes"]["regime"]["units"].extend(optional)
        for unit in optional:
            self.write_unit(unit)
        out = self.derive(p)
        self.assertIsNone(out["terminal"])
        self.assertEqual(out["blocked"], T.BLOCKED)
        self.assertTrue(any("case-4096" in x for x in out["problems"]))

    def _plan_with_case4096(self, *, reason="extend the regime ladder"):
        p = json.loads(json.dumps(self.p))
        optional = ["case-4096-B-case4096-001", "case-4096-B-case4096-002"]
        p["probes"]["regime"]["units"].extend(optional)
        for unit in optional:
            self.write_unit(unit)
        return p

    def _case4096_units(self, p):
        return [u for u in p["probes"]["regime"]["units"]
                if u.startswith("case-4096")]

    def _stamp_case4096_authority(self, p, *, comment_id, head_sha, line,
                                  reason, live=None):
        block = D.unit_authority_block(live or self.dispatch[
            T.FROZEN_PROBE_NAMESPACE["regime"]])
        block["comment_id"] = comment_id
        block["head_sha"] = head_sha
        block["case4096"] = {"comment_id": comment_id, "line": line,
                             "reason": reason}
        # Re-stamp EVERY unit of the regime namespace in this plan so
        # the whole namespace binds to the same coherent authorizing
        # comment (tests that swap the live payload must not leave the
        # six ordinary regime units bound to a different body digest).
        for unit in p["probes"]["regime"]["units"]:
            path = self.unit_dir(unit) / "unit.json"
            receipt = json.loads(path.read_bytes())
            receipt["authority"] = block
            path.write_text(json.dumps(receipt))

    def _live_authority(self, *, comment_id=DISPATCH_COMMENT_ID,
                        head_sha=DISPATCH_HEAD,
                        reason="extend the regime ladder"):
        line = f"case-4096:{reason}"
        # Positive payloads use the REAL frozen dispatch phrase constant,
        # never a hand-typed weaker spelling (round-3 blocker 3).
        return {
            "comment_id": comment_id, "head_sha": head_sha,
            "issue_url": (f"https://api.github.com/repos/Zutfen-LLC/inferswarm/"
                          f"issues/{D.DIAGNOSTIC_PR_NUMBER}"),
            "author_association": "MEMBER",
            "created_at": "2026-09-25T00:00:00Z",
            "body": "\n".join([
                D.DIAGNOSTIC_DISPATCH_PHRASE,
                f"head={head_sha}",
                f"diagnostic-namespace={T.FROZEN_PROBE_NAMESPACE['regime']}",
                line,
            ]),
            "namespace": T.FROZEN_PROBE_NAMESPACE["regime"],
            "open_pr": True, "issue_open": True,
            "case4096": {"comment_id": comment_id, "line": line,
                         "reason": "FORGED: different reason"},
        }

    def test_case4096_forged_receipt_authority_cannot_authorize(self):
        # P1 regression: an internally consistent fabricated receipt
        # (authority block matches itself) must NOT authorize case-4096
        # when no LIVE dispatch authority is supplied.
        p = self._plan_with_case4096()
        self._stamp_case4096_authority(
            p, comment_id=1234, head_sha="a" * 40,
            line="case-4096:extend the regime ladder",
            reason="extend the regime ladder")
        out = self.derive(p)
        self.assertIsNone(out["terminal"])
        self.assertEqual(out["blocked"], T.BLOCKED)
        self.assertTrue(any("case-4096" in x for x in out["problems"]))

    def test_case4096_live_authority_authorizes_only_exact_binding(self):
        p = self._plan_with_case4096()
        live = self._live_authority()
        # ONE coherent comment: the live payload (with its case-4096
        # line) is also the regime namespace's dispatch authority here.
        self.dispatch[T.FROZEN_PROBE_NAMESPACE["regime"]] = live
        self._stamp_case4096_authority(
            p, comment_id=live["comment_id"], head_sha=live["head_sha"],
            line="case-4096:extend the regime ladder",
            reason="extend the regime ladder", live=live)
        out = self.derive(p, case4096_authority=live)
        # A live authority whose precomputed case4096 block disagrees is
        # still fine (that block is ignored); the comment body's exact
        # line binds the retained receipts.
        self.assertEqual(out["terminal"],
                         T.TERMINALS[4])  # NOT_REPRODUCED on clean set

    def test_case4096_live_authority_rejects_head_or_line_mismatch(self):
        p = self._plan_with_case4096()
        live = self._live_authority()
        self._stamp_case4096_authority(
            p, comment_id=live["comment_id"], head_sha="b" * 40,
            line="case-4096:extend the regime ladder",
            reason="extend the regime ladder", live=live)
        out = self.derive(p, case4096_authority=live)
        self.assertIsNone(out["terminal"])
        self.assertEqual(out["blocked"], T.BLOCKED)
        self.assertTrue(any("case-4096" in x for x in out["problems"]))

    def test_case4096_live_authority_wrong_comment_line_rejected(self):
        p = self._plan_with_case4096()
        live = self._live_authority()
        # receipt claims the authorization line, but the LIVE comment
        # body authorizes a different (comment_id, line) pair.
        self._stamp_case4096_authority(
            p, comment_id=live["comment_id"] + 1, head_sha=live["head_sha"],
            line="case-4096:extend the regime ladder",
            reason="extend the regime ladder", live=live)
        out = self.derive(p, case4096_authority=live)
        self.assertIsNone(out["terminal"])
        self.assertEqual(out["blocked"], T.BLOCKED)
        self.assertTrue(any("case-4096" in x for x in out["problems"]))

    def test_case4096_live_authority_missing_namespace_scope_rejected(self):
        p = self._plan_with_case4096()
        live = self._live_authority()
        live["body"] = "\n".join([
            D.DIAGNOSTIC_DISPATCH_PHRASE,
            f"head={live['head_sha']}",
            "case-4096:extend the regime ladder",
        ])  # no diagnostic-namespace line
        self._stamp_case4096_authority(
            p, comment_id=live["comment_id"], head_sha=live["head_sha"],
            line="case-4096:extend the regime ladder",
            reason="extend the regime ladder", live=live)
        out = self.derive(p, case4096_authority=live)
        self.assertIsNone(out["terminal"])
        self.assertEqual(out["blocked"], T.BLOCKED)

    def test_non_object_response_json_blocks_not_crashes(self):
        # P2 regression: a top-level JSON array response must fail closed
        # as a malformed unit, not raise AttributeError.
        unit = self.p["probes"]["repeat"]["units"][0]
        ud = self.unit_dir(unit)
        (ud / "response.json.raw").write_bytes(b"[1,2,3]")
        out = self.derive()
        self.assertIsNone(out["terminal"])
        self.assertEqual(out["blocked"], T.BLOCKED)
        self.assertTrue(any(unit in x for x in out["problems"]))


    def test_complete_clean_raw_evidence_is_not_reproduced(self):
        out = self.derive()
        self.assertEqual(out["terminal"], T.TERMINALS[4])

    def test_execution_contract_mutations_block_frozen_probe(self):
        unit = self.p["probes"]["placement"]["units"][0]
        path = self.unit_dir(unit) / "unit.json"
        original = json.loads(path.read_bytes())
        for field, mutate in (
            ("argv_ngl", lambda r: r["server_argv"].__setitem__(
                r["server_argv"].index("-ngl") + 1, "8")),
            ("binary", lambda r: r.__setitem__("binary_sha256", "f" * 64)),
            ("model", lambda r: r["model_members_sha256"].__setitem__(
                D.MODEL_MEMBER_1, "f" * 64)),
            ("request", lambda r: r["request_contract"].__setitem__("seed", 99)),
            ("executed_binary", lambda r: r["process_attribution"].__setitem__(
                "server_exe_sha256", "f" * 64)),
        ):
            with self.subTest(field=field):
                changed = json.loads(json.dumps(original))
                mutate(changed)
                path.write_text(json.dumps(changed))
                out = self.derive()
                self.assertIsNone(out["terminal"], field)
                self.assertEqual(out["blocked"], T.BLOCKED, field)
        path.write_text(json.dumps(original))

    def test_missing_phase2_unit_list_returns_blocked_not_exception(self):
        p = json.loads(json.dumps(self.p))
        p["probes"]["placement"].pop("units")
        out = self.derive(p)
        self.assertIsNone(out["terminal"])
        self.assertEqual(out["blocked"], T.BLOCKED)

    def test_unplanned_retained_phase2_unit_cannot_be_cherry_picked_away(self):
        self.write_unit("case-3072-B-ngl1-003")
        out = self.derive()
        self.assertIsNone(out["terminal"])
        self.assertEqual(out["blocked"], T.BLOCKED)

    def test_phase2_requires_exact_two_index_population_per_condition(self):
        p = json.loads(json.dumps(self.p))
        extra = "case-3072-B-ngl1-003"
        p["probes"]["placement"]["units"].append(extra)
        self.write_unit(extra)
        out = self.derive(p)
        self.assertIsNone(out["terminal"])
        self.assertEqual(out["blocked"], T.BLOCKED)

    def test_cross_case_placement_unit_cannot_satisfy_frozen_ladder(self):
        p = json.loads(json.dumps(self.p))
        wrong = "case-1024-B-ngl1-001"
        p["probes"]["placement"]["units"][0] = wrong
        self.write_unit(wrong)
        out = self.derive(p)
        self.assertIsNone(out["terminal"])
        self.assertEqual(out["blocked"], T.BLOCKED)

    def test_wrong_regime_variant_cannot_satisfy_frozen_ladder(self):
        p = json.loads(json.dumps(self.p))
        wrong = "case-1024-B-regime-256-001"
        p["probes"]["regime"]["units"][2] = wrong
        self.write_unit(wrong)
        out = self.derive(p)
        self.assertIsNone(out["terminal"])
        self.assertEqual(out["blocked"], T.BLOCKED)

    def test_unit_receipt_health_binding_is_required(self):
        unit = self.p["probes"]["repeat"]["units"][0]
        path = self.unit_dir(unit) / "unit.json"
        receipt = json.loads(path.read_bytes())
        receipt["platform_health_receipt"]["sha256"] = "f" * 64
        path.write_text(json.dumps(receipt))
        out = self.derive()
        self.assertIsNone(out["terminal"])
        self.assertEqual(out["blocked"], T.BLOCKED)

    def test_dual_capture_missing_or_disagreeing_row_blocks(self):
        unit = tag("obs-dual", 1)
        d = self.unit_dir(unit)
        path = d / "capture.r8e.pos0.f32"
        raw = path.read_bytes()
        path.unlink()
        out = self.derive()
        self.assertIsNone(out["terminal"])
        self.assertEqual(out["blocked"], T.BLOCKED)
        mutated = b"z" + raw[1:]
        path.write_bytes(mutated)
        receipt_path = d / "unit.json"
        receipt = json.loads(receipt_path.read_bytes())
        receipt["r8e_row0_sha256"] = hashlib.sha256(mutated).hexdigest()
        receipt_path.write_text(json.dumps(receipt))
        out = self.derive()
        self.assertIsNone(out["terminal"])
        self.assertEqual(out["blocked"], T.BLOCKED)

    def test_r8e_only_instability_after_stable_repeat_is_not_ignored(self):
        self.write_unit(tag("obs-r8e", 2), row_seed=b"z")
        out = self.derive()
        self.assertEqual(out["terminal"],
                         "R8I3_REF_NONDETERMINISM_UNRESOLVED")

    def test_canonical_token_instability_after_stable_repeat_is_not_ignored(self):
        self.write_unit(tag("canonical", 2), tokens=TOKENS[:-1] + [9])
        out = self.derive()
        self.assertEqual(out["terminal"],
                         "R8I3_REF_NONDETERMINISM_UNRESOLVED")

    def test_observer_population_instability_after_stable_repeat_is_not_ignored(self):
        self.write_unit(tag("obs-comparator", 2), row_seed=b"z")
        out = self.derive()
        self.assertEqual(out["terminal"],
                         "R8I3_REF_NONDETERMINISM_UNRESOLVED")

    def test_missing_or_tampered_direct_health_custody_blocks(self):
        unit = self.p["probes"]["repeat"]["units"][0]
        (self.unit_dir(unit) / "platform-health-receipt.json").unlink()
        out = self.derive()
        self.assertIsNone(out["terminal"])
        self.assertEqual(out["blocked"], T.BLOCKED)

    def test_health_is_verified_for_all_units_before_not_reproduced(self):
        unit = self.p["probes"]["canonical"]["units"][1]
        (self.unit_dir(unit) / "kernel-journal.raw").write_bytes(b"tampered")
        out = self.derive()
        self.assertIsNone(out["terminal"])
        self.assertEqual(out["blocked"], T.BLOCKED)

    def test_real_fatal_sample_localizes_platform_only_after_full_health(self):
        unit = self.p["probes"]["repeat"]["units"][0]
        d = self.unit_dir(unit)
        for name in ("kernel-journal.raw", "nvidia-smi.csv.raw",
                     "device-samples.json", "platform-health-receipt.json"):
            (d / name).unlink()
        self.write_unit(unit, fatal=True)
        out = self.derive()
        self.assertEqual(out["terminal"], "R8I3_REF_PLATFORM_INSTABILITY_LOCALIZED")

    def test_runtime_initialization_contrast_does_not_localize_vulkan(self):
        # A changed initialization setting changes another factor, not a Vulkan cause probe.
        out = self.derive()
        self.assertNotEqual(out["terminal"], "R8I3_REF_VULKAN_NONDETERMINISM_LOCALIZED")

    def test_deterministic_complete_evidence_derives_not_reproduced(self):
        out = self.derive()
        self.assertEqual(out["terminal"], "R8I3_REF_NONDETERMINISM_NOT_REPRODUCED")

    def test_repeatability_terminal_rejects_later_same_level_contradiction(self):
        pair = [u for u in self.p["probes"]["placement"]["units"]
                if "ngl1-" in u]
        self.write_unit(pair[0], row_seed=b"A")
        self.write_unit(pair[1], row_seed=b"B")
        out = self.derive()
        self.assertEqual(out["terminal"], "R8I3_REF_NONDETERMINISM_UNRESOLVED")

    def test_unresolved_basis_retains_placement_regime_and_capture_facts(self):
        for i, unit in enumerate(self.p["probes"]["repeat"]["units"]):
            self.write_unit(unit, row_seed=bytes([65 + (i % 2)]))
        pair = [u for u in self.p["probes"]["placement"]["units"]
                if "-ngl1-" in u]
        self.write_unit(pair[0], row_seed=b"A")
        self.write_unit(pair[1], row_seed=b"B")
        out = self.derive()
        self.assertEqual(out["terminal"], "R8I3_REF_NONDETERMINISM_UNRESOLVED")
        basis = out["basis"]
        self.assertTrue(basis["placement_row_variation_by_ngl"]["1"])
        self.assertFalse(basis["placement_row_variation_by_ngl"]["8"])
        self.assertFalse(basis["regime_row_variation_by_case"]["256"])
        self.assertTrue(basis["dual_capture_position0_agrees"])
        self.assertFalse(basis["observer_independent_r8e_position0_varies"])
        self.assertTrue(basis["platform_health_complete_clean"])

    def test_repeat_row_variation_derives_unresolved(self):
        for i, unit in enumerate(self.p["probes"]["repeat"]["units"]):
            self.write_unit(unit, row_seed=bytes([65 + (i % 2)]))
        out = self.derive()
        self.assertEqual(out["terminal"], "R8I3_REF_NONDETERMINISM_UNRESOLVED")

    def test_rowless_observer_off_cannot_establish_row_causality(self):
        for i, unit in enumerate(self.p["probes"]["repeat"]["units"]):
            self.write_unit(unit, row_seed=bytes([65 + (i % 2)]))
        for variant in T.VARIANTS:
            for i in (1, 2):
                seed = (bytes([64 + i]) if variant in ("obs-comparator", "obs-dual")
                        else b"A")
                self.write_unit(tag(variant, i), row_seed=seed)
        out = self.derive()
        self.assertEqual(out["terminal"], "R8I3_REF_NONDETERMINISM_UNRESOLVED")

    def test_observer_localization_rejects_on_off_token_confound(self):
        for i, unit in enumerate(self.p["probes"]["repeat"]["units"]):
            self.write_unit(unit, row_seed=bytes([65 + (i % 2)]))
        for variant in T.VARIANTS:
            for i in (1, 2):
                seed = bytes([64 + i]) if variant in ("obs-comparator", "obs-dual") else b"A"
                tokens = list(TOKENS)
                if variant == "obs-off" and i == 2:
                    tokens[-1] += 1
                self.write_unit(tag(variant, i), row_seed=seed, tokens=tokens)
        out = self.derive()
        self.assertNotEqual(out["terminal"], "R8I3_REF_OBSERVER_PERTURBATION_LOCALIZED")

    def test_textual_health_callback_cannot_override_retained_evidence(self):
        out = self.derive(
            health_verifier=lambda *_: {"fatal_states": [], "evidence": ["invented"]})
        self.assertEqual(out["terminal"], "R8I3_REF_NONDETERMINISM_NOT_REPRODUCED")

    def test_forged_success_receipt_with_raw_identity_drift_blocks(self):
        unit = self.p["probes"]["repeat"]["units"][0]
        path = self.unit_dir(unit) / "identity-post.json"
        observation = json.loads(path.read_text())
        observation["raw"]["sysfs.device"] = "0xffff"
        path.write_text(json.dumps(observation))
        out = self.derive()
        self.assertIsNone(out["terminal"])
        self.assertEqual(out["blocked"], T.BLOCKED)

    def test_observer_off_rowless_population_is_required_and_health_custodied(self):
        expected = {tag(v, i) for v in T.VARIANTS for i in (1, 2)}
        missing = expected - set(self.tags)
        self.assertFalse(missing)
        for unit in expected:
            health = H.verify_platform_health(self.unit_dir(unit))
            self.assertTrue(health["valid"], unit)

    def test_deterministic_repeat_does_not_skip_phase2_or_health(self):
        p = json.loads(json.dumps(self.p))
        p["probes"].pop("placement")
        out = self.derive(p)
        self.assertIsNone(out["terminal"])
        self.assertEqual(out["blocked"], T.BLOCKED)

    def test_namespace_units_are_bound_to_plan(self):
        p = json.loads(json.dumps(self.p))
        p["probes"]["repeat"]["units"][0] = "case-3072-B-baseline-006"
        out = self.derive(p)
        self.assertIsNone(out["terminal"])
        self.assertEqual(out["blocked"], T.BLOCKED)



class DispatchProvenanceMatrix(RetainedTerminalMatrix):
    """Round-3 blocker 2: competent-forgery controls for unit dispatch
    provenance. Every fixture here is numerically/runtime/health VALID
    (inherited from the parent fixtures); ONLY the dispatch provenance
    varies, proving valid evidence cannot overcome invalid provenance.
    """

    def _rewrite(self, unit, mutate):
        path = self.unit_dir(unit) / "unit.json"
        receipt = json.loads(path.read_bytes())
        mutate(receipt)
        path.write_text(json.dumps(receipt, sort_keys=True))

    def test_valid_evidence_authority_absent_blocks(self):
        for unit in self.tags:
            self._rewrite(unit, lambda r: r.pop("authority", None))
        out = self.derive()
        self.assertIsNone(out["terminal"])
        self.assertEqual(out["blocked"], T.BLOCKED)
        self.assertTrue(any("dispatch authority" in x for x in out["problems"]))

    def test_valid_evidence_wrong_head_blocks(self):
        def mutate(r):
            r["authority"]["head_sha"] = "e" * 40
        for unit in self.tags:
            self._rewrite(unit, mutate)
        out = self.derive()
        self.assertIsNone(out["terminal"])
        self.assertEqual(out["blocked"], T.BLOCKED)

    def test_valid_evidence_wrong_comment_id_blocks(self):
        def mutate(r):
            r["authority"]["comment_id"] = DISPATCH_COMMENT_ID + 99
        for unit in self.tags:
            self._rewrite(unit, mutate)
        out = self.derive()
        self.assertIsNone(out["terminal"])
        self.assertEqual(out["blocked"], T.BLOCKED)

    def test_valid_evidence_wrong_dispatch_digest_blocks(self):
        def mutate(r):
            r["authority"]["dispatch_sha256"] = "f" * 64
        for unit in self.tags:
            self._rewrite(unit, mutate)
        out = self.derive()
        self.assertIsNone(out["terminal"])
        self.assertEqual(out["blocked"], T.BLOCKED)

    def test_correct_head_wrong_namespace_in_unit_blocks(self):
        # A unit whose authority block names a different namespace than
        # the probe namespace containing it (the transplanted-unit shape).
        def mutate(r):
            r["authority"]["namespace"] = "d248-other-namespace"
        for unit in self.tags:
            self._rewrite(unit, mutate)
        out = self.derive()
        self.assertIsNone(out["terminal"])
        self.assertEqual(out["blocked"], T.BLOCKED)
        self.assertTrue(any("namespace" in x for x in out["problems"]))

    def test_copied_valid_unit_moved_into_different_probe_namespace_blocks(self):
        # Copy one fully valid repeat unit's bytes into the placement
        # namespace under a placement tag shape: the receipt itself is
        # internally re-bound (tag/namespace/kind), but its authority
        # digest still names the REPEAT namespace's dispatch — only the
        # probe-namespace equality check catches it.
        source = self.unit_dir(self.p["probes"]["repeat"]["units"][0])
        target_tag = "case-3072-B-ngl1-001"
        target = self.unit_dir(target_tag)
        receipt = json.loads((source / "unit.json").read_bytes())
        receipt["tag"] = target_tag
        receipt["namespace"] = target.parent.name
        receipt["kind"] = "rung"
        receipt["ngl"] = 1
        receipt["server_argv"] = D.server_argv(
            Path("/accepted/llama-server"),
            Path(D.MODEL_DIR) / D.MODEL_MEMBER_1, 1, 19000)
        target.mkdir(parents=True, exist_ok=True)
        for name in ("response.json.raw", "identity-pre.json",
                     "identity-post.json", "obs.meta.json",
                     "platform-health-receipt.json", "kernel-journal.raw",
                     "nvidia-smi.csv.raw", "device-samples.json"):
            if (source / name).is_file():
                (target / name).write_bytes((source / name).read_bytes())
        for i in range(8):
            (target / f"obs.row{i}.f32").write_bytes(
                (source / f"obs.row{i}.f32").read_bytes())
        (target / "unit.json").write_text(json.dumps(receipt, sort_keys=True))
        # The authority block still equals the REPEAT dispatch — the
        # placement population must reject it via namespace mismatch.
        out = self.derive()
        self.assertIsNone(out["terminal"])
        self.assertEqual(out["blocked"], T.BLOCKED)
        self.assertTrue(any("namespace" in x for x in out["problems"]))

    def test_two_units_same_namespace_different_comments_blocks(self):
        # Both units stay in the repeat namespace but one claims a
        # different (unauthorized) authorizing comment.
        other = dispatch_payload(T.FROZEN_PROBE_NAMESPACE["repeat"],
                                 comment_id=DISPATCH_COMMENT_ID + 7)
        self._rewrite(self.p["probes"]["repeat"]["units"][1],
                      lambda r: r.__setitem__(
                          "authority", D.unit_authority_block(other)))
        out = self.derive()
        self.assertIsNone(out["terminal"])
        self.assertEqual(out["blocked"], T.BLOCKED)
        self.assertTrue(any("authority binding mismatch" in x
                            for x in out["problems"]))

    def test_no_dispatch_authority_map_blocks(self):
        # Fully valid evidence, but the reduction was given no live
        # dispatch authority at all.
        out = self.derive(dispatch={})
        self.assertIsNone(out["terminal"])
        self.assertEqual(out["blocked"], T.BLOCKED)
        self.assertTrue(any("no validated live dispatch authority"
                            in x for x in out["problems"]))

    def test_non_member_dispatch_payload_blocks(self):
        out = self.derive(dispatch=dispatch_map(author_association="CONTRIBUTOR"))
        self.assertIsNone(out["terminal"])
        self.assertEqual(out["blocked"], T.BLOCKED)

    def test_closed_pr_or_issue_dispatch_payload_blocks(self):
        out = self.derive(dispatch=dispatch_map(open_pr=False))
        self.assertIsNone(out["terminal"])
        self.assertEqual(out["blocked"], T.BLOCKED)
        out = self.derive(dispatch=dispatch_map(issue_open=False))
        self.assertIsNone(out["terminal"])
        self.assertEqual(out["blocked"], T.BLOCKED)

    def test_wrong_pr_binding_dispatch_payload_blocks(self):
        bad = dispatch_map()
        for payload in bad.values():
            payload["issue_url"] = (
                "https://api.github.com/repos/Zutfen-LLC/inferswarm/issues/242")
        out = self.derive(dispatch=bad)
        self.assertIsNone(out["terminal"])
        self.assertEqual(out["blocked"], T.BLOCKED)

    def test_wrong_phrase_dispatch_payload_blocks(self):
        bad = dispatch_map()
        for payload in bad.values():
            payload["body"] = payload["body"].replace(
                D.DIAGNOSTIC_DISPATCH_PHRASE, "R8I3 PHYSICAL DISPATCH #248")
        out = self.derive(dispatch=bad)
        self.assertIsNone(out["terminal"])
        self.assertEqual(out["blocked"], T.BLOCKED)

    def test_missing_head_line_dispatch_payload_blocks(self):
        bad = dispatch_map()
        for payload in bad.values():
            payload["body"] = payload["body"].replace(
                f"head={DISPATCH_HEAD}\n", "")
        out = self.derive(dispatch=bad)
        self.assertIsNone(out["terminal"])
        self.assertEqual(out["blocked"], T.BLOCKED)

    def test_stale_head_dispatch_payload_blocks(self):
        bad = dispatch_map(head="b" * 40)
        out = self.derive(dispatch=bad)
        self.assertIsNone(out["terminal"])
        self.assertEqual(out["blocked"], T.BLOCKED)

    def test_duplicate_namespace_lines_dispatch_payload_blocks(self):
        bad = dispatch_map()
        for payload in bad.values():
            payload["body"] += f"\ndiagnostic-namespace={payload['namespace']}"
        out = self.derive(dispatch=bad)
        self.assertIsNone(out["terminal"])
        self.assertEqual(out["blocked"], T.BLOCKED)

    def test_map_key_mismatch_dispatch_payload_blocks(self):
        # A payload registered under the WRONG map key (its validated
        # namespace differs from the key it is filed under).
        good = dispatch_map()
        payload = good[T.FROZEN_PROBE_NAMESPACE["repeat"]]
        del good[T.FROZEN_PROBE_NAMESPACE["repeat"]]
        good["d248-wrong-key"] = payload
        out = self.derive(dispatch=good)
        self.assertIsNone(out["terminal"])
        self.assertEqual(out["blocked"], T.BLOCKED)

    def test_valid_evidence_with_exact_namespace_authority_accepted(self):
        out = self.derive()
        self.assertEqual(out["terminal"], T.TERMINALS[4])
        self.assertIsNone(out["blocked"])


class Case4096FullAuthorityMatrix(RetainedTerminalMatrix):
    """Round-3 blocker 3: the case-4096 permission must clear the SAME
    full diagnostic-dispatch validator as ordinary units; the old weaker
    parser (integer id + 40-hex head + namespace line + case line, no
    phrase/association/PR-state/issue-state/head-line checks) accepted
    payloads the real dispatch contract rejects.
    """

    def _derive_with_4096(self, live, p=None):
        p = p or self._plan_with_case4096()
        # ONE coherent authorizing comment: the live payload (which
        # carries the case-4096 line) is also the regime namespace's
        # dispatch authority for this reduction.
        self.dispatch[T.FROZEN_PROBE_NAMESPACE["regime"]] = live
        self._stamp_case4096_authority(
            p, comment_id=live["comment_id"], head_sha=live["head_sha"],
            line="case-4096:extend the regime ladder",
            reason="extend the regime ladder", live=live)
        return self.derive(p, case4096_authority=live)

    def test_weaker_r8i3_phrase_rejected(self):
        # OLD-DEFECT PROOF: the exact wrong phrase the round-2 fixture
        # used ("R8I3 PHYSICAL DISPATCH #248", missing the A) must now
        # be rejected by the full validator.
        live = self._live_authority()
        live["body"] = live["body"].replace(
            D.DIAGNOSTIC_DISPATCH_PHRASE, "R8I3 PHYSICAL DISPATCH #248")
        out = self._derive_with_4096(live)
        self.assertIsNone(out["terminal"])
        self.assertEqual(out["blocked"], T.BLOCKED)
        self.assertTrue(any("phrase" in x for x in out["problems"]))

    def test_missing_dispatch_phrase_rejected(self):
        live = self._live_authority()
        live["body"] = "\n".join(live["body"].splitlines()[1:])
        out = self._derive_with_4096(live)
        self.assertIsNone(out["terminal"])
        self.assertEqual(out["blocked"], T.BLOCKED)

    def test_missing_exact_head_line_rejected(self):
        live = self._live_authority()
        live["body"] = live["body"].replace(f"head={live['head_sha']}\n", "")
        out = self._derive_with_4096(live)
        self.assertIsNone(out["terminal"])
        self.assertEqual(out["blocked"], T.BLOCKED)

    def test_stale_head_line_rejected(self):
        live = self._live_authority(head_sha="c" * 40)
        out = self._derive_with_4096(live)
        self.assertIsNone(out["terminal"])
        self.assertEqual(out["blocked"], T.BLOCKED)

    def test_non_member_author_rejected(self):
        live = self._live_authority()
        live["author_association"] = "CONTRIBUTOR"
        out = self._derive_with_4096(live)
        self.assertIsNone(out["terminal"])
        self.assertEqual(out["blocked"], T.BLOCKED)

    def test_wrong_pr_binding_rejected(self):
        live = self._live_authority()
        live["issue_url"] = (
            "https://api.github.com/repos/Zutfen-LLC/inferswarm/issues/242")
        out = self._derive_with_4096(live)
        self.assertIsNone(out["terminal"])
        self.assertEqual(out["blocked"], T.BLOCKED)

    def test_closed_pr_state_rejected(self):
        live = self._live_authority()
        live["open_pr"] = False
        out = self._derive_with_4096(live)
        self.assertIsNone(out["terminal"])
        self.assertEqual(out["blocked"], T.BLOCKED)

    def test_closed_issue_state_rejected(self):
        live = self._live_authority()
        live["issue_open"] = False
        out = self._derive_with_4096(live)
        self.assertIsNone(out["terminal"])
        self.assertEqual(out["blocked"], T.BLOCKED)

    def test_wrong_namespace_scope_rejected(self):
        live = self._live_authority()
        live["body"] = live["body"].replace(
            f"diagnostic-namespace={T.FROZEN_PROBE_NAMESPACE['regime']}",
            "diagnostic-namespace=d248-wrong-scope")
        out = self._derive_with_4096(live)
        self.assertIsNone(out["terminal"])
        self.assertEqual(out["blocked"], T.BLOCKED)

    def test_duplicate_namespace_lines_rejected(self):
        live = self._live_authority()
        live["body"] += (
            f"\ndiagnostic-namespace={T.FROZEN_PROBE_NAMESPACE['regime']}")
        out = self._derive_with_4096(live)
        self.assertIsNone(out["terminal"])
        self.assertEqual(out["blocked"], T.BLOCKED)

    def test_absent_case4096_line_rejects_case4096_units_only(self):
        # A dispatch valid for the regime namespace WITHOUT the
        # case-4096 line: only the case-4096 population may fail.
        p = self._plan_with_case4096()
        live = self._live_authority()
        live["body"] = "\n".join(
            line for line in live["body"].splitlines()
            if not line.startswith("case-4096:"))
        regime_ns = T.FROZEN_PROBE_NAMESPACE["regime"]
        self.dispatch[regime_ns] = live
        self._stamp_case4096_authority(
            p, comment_id=live["comment_id"], head_sha=live["head_sha"],
            line="case-4096:extend the regime ladder",
            reason="extend the regime ladder", live=live)
        out = self.derive(p, case4096_authority=live)
        self.assertIsNone(out["terminal"])
        self.assertEqual(out["blocked"], T.BLOCKED)
        self.assertTrue(any("case-4096" in x for x in out["problems"]))

    def test_duplicate_conflicting_case4096_lines_rejected(self):
        live = self._live_authority()
        live["body"] += "\ncase-4096:a conflicting second reason"
        out = self._derive_with_4096(live)
        self.assertIsNone(out["terminal"])
        self.assertEqual(out["blocked"], T.BLOCKED)

    def test_fabricated_internally_consistent_receipt_rejected(self):
        # OLD-DEFECT PROOF (round-2 P1, re-proven through the full
        # validator): a receipt whose authority block matches itself but
        # has NO live dispatch payload cannot authorize case-4096.
        p = self._plan_with_case4096()
        self._stamp_case4096_authority(
            p, comment_id=4242, head_sha="d" * 40,
            line="case-4096:extend the regime ladder",
            reason="extend the regime ladder")
        out = self.derive(p)
        self.assertIsNone(out["terminal"])
        self.assertEqual(out["blocked"], T.BLOCKED)
        self.assertTrue(any("case-4096" in x for x in out["problems"]))

    def test_precomputed_case4096_summary_cannot_override_comment_bytes(self):
        # The payload's own case4096 dict claims a DIFFERENT reason than
        # the comment body's exact line: the body wins; the receipts are
        # stamped with the body's line, so this must still authorize.
        live = self._live_authority()
        live["case4096"] = {"comment_id": live["comment_id"],
                            "line": "case-4096:some other reason",
                            "reason": "some other reason"}
        out = self._derive_with_4096(live)
        self.assertEqual(out["terminal"], T.TERMINALS[4])

    def test_fully_valid_dispatch_with_exact_case4096_line_accepted(self):
        live = self._live_authority()
        out = self._derive_with_4096(live)
        self.assertEqual(out["terminal"], T.TERMINALS[4])
        self.assertIsNone(out["blocked"])


class TwoPassAuthorityLaunchControls(unittest.TestCase):
    """Round-3 blocker 1: TOCTOU controls on the two-pass live authority.

    The first fetch is VALID; remote state drifts before the final gate;
    the runner call list must be EMPTY in every drift case (recorded-call
    ordering, not eventual rejection).
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.repo = self.root / "repo"
        (self.repo / "docs/investigations/qwen38-flash-next-r8-b/"
         "evidence/reference").mkdir(parents=True)
        source = (REPO / D.FIXTURE_LADDER_REL).read_bytes()
        (self.repo / D.FIXTURE_LADDER_REL).write_bytes(source)
        self.bin = self.root / "bin"
        self.bin.write_bytes(b"x" * 32)
        self.model_dir = self.root / D.MODEL_DIR.lstrip("/")
        self.model_dir.mkdir(parents=True)
        for member in D.MODEL_MEMBERS:
            (self.model_dir / member).write_bytes(b"m" * 64)
        self.member_digests = {m: D.MODEL_MEMBER_SHA256[m]
                               for m in D.MODEL_MEMBERS}
        self.model_hasher = lambda path: self.member_digests[path.name]
        self._orig = dict(D.SERVER_BINARIES)
        D.SERVER_BINARIES["comparator"] = D.file_sha256(self.bin)
        import issue248_diagnostic
        self._orig_run = issue248_diagnostic.subprocess.run
        issue248_diagnostic.subprocess.run = FakeGit(HEAD)

    def tearDown(self):
        D.SERVER_BINARIES.clear()
        D.SERVER_BINARIES.update(self._orig)
        import issue248_diagnostic
        issue248_diagnostic.subprocess.run = self._orig_run
        self._tmp.cleanup()

    def _fetch_pair(self, first, second):
        """A revalidate_authority seam that drifts after the first call."""
        state = {"calls": 0}

        def fetch(repo_root, expected_head, namespace, github_api):
            state["calls"] += 1
            payload = first if state["calls"] == 1 else second
            if isinstance(payload, Exception):
                raise payload
            return payload(head=expected_head, namespace=namespace)
        return fetch

    def _attempt(self, first, second):
        calls = []

        def execute(**kw):
            calls.append(kw)
            raise AssertionError("runner must not be reached")

        with self.assertRaises((P.PhysicalDiagnosticError, D.DiagnosticError)):
            P.run_diagnostic_unit(
                self.repo, self.root / "ev", "d248-toctou", "repeat",
                arm="B", case="case-3072", ngl=8, binary_id="comparator",
                binary=self.bin, model_dir=self.model_dir,
                expected_head=HEAD, index=1, execute=execute,
                health_runner=FakeRunnerPhysicalTests._fake_health_command,
                identity_observer=lambda arm: census_observation(arm),
                revalidate_authority=self._fetch_pair(first, second),
                model_hasher=self.model_hasher)
        return calls

    def test_first_valid_second_pr_head_moved_zero_runner_calls(self):
        def drifted(**kw):
            payload = make_authority(**kw)
            payload["open_pr"] = False
            payload["head_sha"] = "f" * 40
            return payload
        calls = self._attempt(make_authority, drifted)
        self.assertEqual(calls, [])

    def test_first_valid_second_pr_closed_zero_runner_calls(self):
        calls = self._attempt(
            make_authority,
            lambda **kw: make_authority(**{**kw, "open_pr": False}))
        self.assertEqual(calls, [])

    def test_first_valid_second_issue_closed_zero_runner_calls(self):
        calls = self._attempt(
            make_authority,
            lambda **kw: make_authority(**{**kw, "issue_open": False}))
        self.assertEqual(calls, [])

    def test_first_valid_second_comment_absent_zero_runner_calls(self):
        calls = self._attempt(
            make_authority,
            D.DiagnosticError("no valid dispatch authority"))
        self.assertEqual(calls, [])

    def test_first_valid_second_namespace_changed_zero_runner_calls(self):
        def drifted(**kw):
            kw = dict(kw)
            kw["namespace"] = kw["namespace"] + "-drifted"
            return make_authority(**kw)
        calls = self._attempt(make_authority, drifted)
        self.assertEqual(calls, [])

    def test_first_valid_second_comment_id_differs_fails_closed(self):
        def drifted(**kw):
            kw = dict(kw)
            kw["comment_id"] = 987654321
            return make_authority(**kw)
        calls = self._attempt(make_authority, drifted)
        self.assertEqual(calls, [])

    def test_first_valid_second_body_edited_fails_closed(self):
        def drifted(**kw):
            payload = make_authority(**kw)
            payload["body"] = payload["body"] + "\nedited later"
            return payload
        calls = self._attempt(make_authority, drifted)
        self.assertEqual(calls, [])

    def test_both_checks_identical_current_allows_launch(self):
        receipt = P.run_diagnostic_unit(
            self.repo, self.root / "ev", "d248-toctou-ok", "repeat",
            arm="B", case="case-3072", ngl=8, binary_id="comparator",
            binary=self.bin, model_dir=self.model_dir, expected_head=HEAD,
            index=1, execute=fake_execute_seam(),
            health_runner=FakeRunnerPhysicalTests._fake_health_command,
            identity_observer=lambda arm: census_observation(arm),
            revalidate_authority=self._fetch_pair(make_authority,
                                                  make_authority),
            model_hasher=self.model_hasher)
        self.assertEqual(receipt["authority"]["comment_id"], 123456)
        self.assertEqual(receipt["authority"]["head_sha"], HEAD)
        self.assertIn("dispatch_sha256", receipt["authority"])

    def test_final_gate_is_last_governance_before_runner(self):
        # Source-order proof: within run_diagnostic_unit, the runner
        # invocation comes after the final authority gate + binding +
        # clean-head recheck, which come after the early gate.
        import inspect
        src = inspect.getsource(P.run_diagnostic_unit)
        final = src.index("FINAL GOVERNANCE GATE")
        bind = src.index("D.bind_authority_observations")
        runner = src.index("runner = execute or _real_execute")
        early = src.index("authority_early = D.require_live_dispatch")
        self.assertLess(early, final)
        self.assertLess(final, bind)
        self.assertLess(bind, runner)


if __name__ == "__main__":
    unittest.main()
