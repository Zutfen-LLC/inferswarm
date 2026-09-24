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
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import issue248_diagnostic as D  # noqa: E402
import issue248_physical as P  # noqa: E402
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
                   ) -> dict:
    lines = [
        f"{D.DIAGNOSTIC_DISPATCH_PHRASE}",
        f"head={head}",
        f"diagnostic-namespace={namespace}",
    ]
    if body_extra:
        lines.extend(body_extra)
    return {
        "comment_id": 123456,
        "issue_url": f"https://api.github.com/repos/Zutfen-LLC/inferswarm/issues/{D.DIAGNOSTIC_PR_NUMBER}",
        "author_association": "MEMBER",
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
            return {"tokens": list(tokens), "response_raw": raw,
                    "process_attribution": {"server_pid": 42,
                                            "server_argv": argv,
                                            "server_env": env},
                    "device_samples": [{"stage": "before"},
                                       {"stage": "after"}]}
        return execute

    def _run_kwargs(self, **overrides):
        kw = dict(
            arm="B", case="case-3072", ngl=8, binary_id="comparator",
            binary=self.bin, model_dir=self.model_dir, expected_head=HEAD,
            index=1, execute=self._fake_execute(),
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
        # determinism digest derives from raw bytes, not receipt claims
        rr = json.loads((unit / "response.json.raw").read_bytes())
        self.assertEqual(
            receipt["deterministic_output_sha256"],
            D.canonical_token_digest(rr["tokens"]))

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


if __name__ == "__main__":
    unittest.main()
