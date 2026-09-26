#!/usr/bin/env python3
"""Issue #250 (R8-I3B) — physical producer tests (correction pass 2).

CPU-only FAKE-RUNNER tests: no physical execution, no GPU, no model
reads, no network. Every producer gate is exercised through injected
fakes (runner, identity observer, authority fetcher, health runner)
with mutation controls asserting the probe list is EMPTY when a gate
denies and zero runner calls on remote drift.

The same-process lifecycle tests cover the maintainer's mutation
list: PID changes mid-arm, wrong id_slot, cache reuse (missing
full-recompute proof), missing prompt-eval proof, request-history
drift, server restart, wrong request contract.
"""
from __future__ import annotations

import importlib.util
import json
import struct
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(
        name, REPO / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# dependency order (issue250_physical imports 248 helpers)
for _dep in ("issue248_diagnostic", "issue248_health",
             "issue248_identity"):
    _load(_dep, f"scripts/{_dep}.py")
D = _load("issue250_diagnostic", "scripts/issue250_diagnostic.py")
P = _load("issue250_physical", "scripts/issue250_physical.py")

HEAD = "c" * 40
TOKENS = [328, 760, 324, 55965, 51624, 29014, 34227, 18030]


def make_authority(namespace="d250-arm-a", arm="A-vulkan-necessity",
                   head=HEAD, comment_id=1):
    body = "\n".join([
        D.DIAGNOSTIC_DISPATCH_PHRASE,
        f"head={head}",
        f"diagnostic-namespace={namespace}",
        f"arm={arm}",
    ])
    return {
        "comment_id": comment_id,
        "issue_url": f"https://api.github.com/repos/Zutfen-LLC/"
                     f"inferswarm/issues/{D.DIAGNOSTIC_PR_NUMBER}",
        "author_association": "MEMBER",
        "created_at": "2026-09-26T00:00:00Z",
        "body": body,
        "head_sha": head,
        "open_pr": True,
        "issue_open": True,
        "namespace": namespace,
        "arm": arm,
    }


class Recorder:
    """Callable recorder for injectable seams."""

    def __init__(self, fn=None, value=None):
        self.calls = []
        self.fn = fn
        self.value = value

    def __call__(self, *a, **kw):
        self.calls.append((a, kw))
        if self.fn is not None:
            return self.fn(*a, **kw)
        return self.value


def fake_identity():
    """A raw identity observation satisfying the accepted predicate."""
    return {
        "schema": "inferswarm.issue248.subject-identity/1",
        "arm": "B",
        "raw": _RAW_IDENTITY,
    }


def _build_raw_identity():
    # Build a raw identity observation whose DERIVED fields equal the
    # frozen reference constants (independent values, not copies).
    return {
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
        "nvidia-smi": (
            "0, GPU-d5c05739-96c1-7e49-89b6-bf54c2121c55, "
            "00000000:03:00.0, NVIDIA GeForce RTX 3060, 610.57.04"),
        "icd_inventory": {
            "nvidia_icd.json": json.dumps(
                {"file_format_version": "1.0.0",
                 "ICD": {"library_path":
                         "libGLX_nvidia.so.0"}})},
        "vulkaninfo": {
            "icd_path": "/usr/share/vulkan/icd.d/nvidia_icd.json",
            "stdout": (
                "VULKANINFO\nVulkan Instance Version: 1.4.341\n\n"
                "GPU0:\n    apiVersion        = 1.4.341\n"
                "    deviceName        = NVIDIA GeForce RTX 3060\n"
                "    deviceUUID        = "
                "d5c05739-96c1-7e49-89b6-bf54c2121c55\n"
                "    driverID          = DRIVER_ID_NVIDIA_PROPRIETARY\n"
                "    driverInfo        = 610.57.04\n"),
            "stderr": "", "rc": 0,
        },
    }


_RAW_IDENTITY = _build_raw_identity()


def fake_health_runner(argv, **kw):
    """Read-only health runner satisfying the accepted verifier."""
    from collections import namedtuple
    Result = namedtuple("Result", "returncode stdout stderr")
    if argv[0] == "journalctl":
        return Result(0, b"", b"")
    if argv[0] == "nvidia-smi":
        return Result(0, (
            "GPU-d5c05739-96c1-7e49-89b6-bf54c2121c55, 42.0, 140.0, "
            "170.0, 0\n").encode(), b"")
    raise AssertionError(f"unexpected health argv: {argv}")


def fake_execute(argv, env, request, prompt, port, unit_dir):
    """A fake server launch writing observer outputs + a response."""
    import hashlib
    import time
    tokens = TOKENS
    response = {"tokens": tokens}
    raw = json.dumps(response).encode()
    # observer rows: deterministic bytes derived from the prompt
    seed = hashlib.sha256(prompt.encode()).digest()
    meta_lines = []
    for i in range(D.DECISIONS):
        row = (seed * (D.ROW_BYTES // len(seed) + 1))[:D.ROW_BYTES]
        (unit_dir / f"obs.row{i}.f32").write_bytes(row)
        meta_lines.append(json.dumps(
            {"pos": i, "sampled_winner": tokens[i]}))
    (unit_dir / "obs.meta.json").write_text(
        "\n".join(meta_lines) + "\n")
    now = datetime_now()
    return {
        "returncode": 0,
        "tokens": tokens,
        "response_raw": raw,
        "process_attribution": {
            "server_pid": 4242,
            "server_exe_sha256": D.SERVER_BINARIES["comparator"],
            "server_argv": list(argv),
            "server_env": dict(env),
        },
        "device_samples": [
            {"stage": "before", "captured_at": now,
             "nvidia_smi_raw": "GPU-d5c05739-96c1-7e49-89b6-bf54c2121c55, "
                               "42.0, 140.0, 170.0, 0\n"},
            {"stage": "during", "captured_at": now,
             "nvidia_smi_raw": "GPU-d5c05739-96c1-7e49-89b6-bf54c2121c55, "
                               "43.0, 145.0, 170.0, 0\n"},
            {"stage": "after", "captured_at": now,
             "nvidia_smi_raw": "GPU-d5c05739-96c1-7e49-89b6-bf54c2121c55, "
                               "41.0, 138.0, 170.0, 0\n"},
        ],
    }


def datetime_now():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def fake_same_process_execute(argv, env, request, prompt, port,
                              unit_dir, repeats, expected_prompt_tokens):
    """Fake ONE-process lifecycle: shared PID, per-request proofs."""
    import hashlib
    records = []
    now = datetime_now()
    shared_pid = 5252
    for index in range(repeats):
        seed = hashlib.sha256(f"{prompt}:{index}".encode()).digest()
        row_files = {}
        meta_lines = []
        for d in range(D.DECISIONS):
            row = (seed * (D.ROW_BYTES // len(seed) + 1))[:D.ROW_BYTES]
            row_files[f"obs.row{d}.f32"] = row
            meta_lines.append(json.dumps(
                {"pos": d, "sampled_winner": TOKENS[d]}))
        meta_file = ("\n".join(meta_lines) + "\n").encode()
        log_slice = (
            f"srv    load_model: initializing, n_slots = 4\n"
            f"slot get_availabl: id  3 | task {index} | "
            f"selected slot by id (3)\n"
            f"slot print_timing: id  3 | task {index} | prompt eval "
            f"time = 42905.50 ms / {expected_prompt_tokens} tokens\n"
        ).encode()
        records.append({
            "server_pid": shared_pid,
            "tokens": list(TOKENS),
            "response_raw": json.dumps({"tokens": TOKENS}).encode(),
            "log_slice": log_slice,
            "row_files": row_files,
            "meta_file": meta_file,
            "reset_proof": P._parse_slot_log(
                log_slice.decode(), index, expected_prompt_tokens),
            "request_contract": dict(request),
        })
    return {
        "server_pid": shared_pid,
        "process_attribution": {
            "server_pid": shared_pid,
            "server_exe_sha256": D.SERVER_BINARIES["comparator"],
            "server_argv": list(argv),
            "server_env": dict(env),
        },
        "requests": records,
        "device_samples": [
            {"stage": "before", "captured_at": now,
             "nvidia_smi_raw": "GPU-d5c05739-96c1-7e49-89b6-bf54c2121c55, "
                               "42.0, 140.0, 170.0, 0\n"},
            {"stage": "during", "captured_at": now,
             "nvidia_smi_raw": "GPU-d5c05739-96c1-7e49-89b6-bf54c2121c55, "
                               "43.0, 145.0, 170.0, 0\n"},
            {"stage": "after", "captured_at": now,
             "nvidia_smi_raw": "GPU-d5c05739-96c1-7e49-89b6-bf54c2121c55, "
                               "41.0, 138.0, 170.0, 0\n"},
        ],
    }


class Env:
    """Common fixture: clean git repo, attestation, authority fetcher."""

    def __init__(self, test, namespace="d250-arm-a",
                 arm="A-vulkan-necessity"):
        import tempfile
        self.test = test
        self.tmp = tempfile.TemporaryDirectory()
        test.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.repo = self.root / "repo"
        self.evidence = self.root / "evidence"
        self.repo.mkdir()
        # minimal git repo at the expected clean head
        import subprocess
        def git(*args):
            subprocess.run(["git", *args], cwd=self.repo, check=True,
                           capture_output=True)
        git("init", "-q")
        git("config", "user.email", "t@t")
        git("config", "user.name", "t")
        (self.repo / "marker.txt").write_text("x")
        # the real fixture ladder at its frozen relative path so the
        # REAL verify_fixtures gate runs against the fake repo
        ladder_dst = self.repo / D.FIXTURE_LADDER_REL
        ladder_dst.parent.mkdir(parents=True, exist_ok=True)
        ladder_dst.write_bytes((REPO / D.FIXTURE_LADDER_REL).read_bytes())
        git("add", "-A")
        git("commit", "-qm", "init")
        git("commit", "--allow-empty", "-qm", "head")
        head = subprocess.run(["git", "rev-parse", "HEAD"],
                              cwd=self.repo, capture_output=True,
                              text=True, check=True).stdout.strip()
        self.head = head
        # fixture ladder verify reads the real repo tree
        self.real_repo = REPO
        self.namespace = namespace
        self.arm = arm
        # fake model dir with stat-stable members (accepted #248 test
        # pattern: MODEL_DIR is patched to the fixture path and
        # restored on cleanup)
        self.model_dir = self.root / "srvmodel"
        self.model_dir.mkdir()
        self.model_files = {}
        for member in D.MODEL_MEMBERS:
            pth = self.model_dir / member
            pth.write_bytes(b"model-bytes-" + member.encode())
            self.model_files[member] = pth
        self.attestation = None
        # accepted #248 test pattern: deterministic binary sha by
        # patching the SERVER_BINARIES lookup (restored on cleanup)
        self.bin = self.root / "llama-server"
        self.bin.write_bytes(b"#!/bin/sh\n# fake accepted comparator build\n")
        self._saved_binaries = dict(D.SERVER_BINARIES)
        D.SERVER_BINARIES["comparator"] = D.file_sha256(self.bin)
        self._saved_model_dir = D.MODEL_DIR
        D.MODEL_DIR = str(self.model_dir)
        test = self.test
        test.addCleanup(lambda: (D.SERVER_BINARIES.update(self._saved_binaries),
                                  setattr(D, "MODEL_DIR", self._saved_model_dir)))

    def open_attestation(self):
        def fake_hasher(path):
            return D.MODEL_MEMBER_SHA256[path.name]
        self.attestation = P.build_model_attestation(
            self.model_dir, self.head, hasher=fake_hasher)
        self.evidence.mkdir(exist_ok=True)
        P._write_json(self.evidence
                      / P.MODEL_ATTESTATION_OPEN_NAME, self.attestation)
        return self.attestation

    def authority_fn(self, mutations=None):
        base = make_authority(namespace=self.namespace, arm=self.arm,
                              head=self.head)
        state = {"base": base, "mutations": mutations or []}

        def fetch(repo_root, expected_head, namespace, github_api=None):
            payload = dict(state["base"])
            for mutate in state["mutations"]:
                mutate(payload)
            return payload
        fetch.state = state
        return fetch


class ProducerGatingTests(unittest.TestCase):
    """Fresh-process producer: gate order + zero-runner-on-denial."""

    def setUp(self):
        self.env = Env(self)
        self.env.open_attestation()

    def _run(self, tag="case-3072-B-devnone-001", **over):
        runner = Recorder(fn=fake_execute)
        identity = Recorder(value=fake_identity())
        fetcher = self.env.authority_fn(
            over.pop("authority_mutations", None))
        authority = Recorder(fn=fetcher)
        kw = dict(
            repo_root=self.env.repo, evidence_root=self.env.evidence,
            namespace=self.env.namespace, arm=self.env.arm, tag=tag,
            binary=self.env.bin, binary_id="comparator",
            model_dir=self.env.model_dir, expected_head=self.env.head,
            model_attestation=self.env.attestation,
            execute=runner, identity_observer=identity,
            revalidate_authority=authority,
            health_runner=fake_health_runner,
        )
        # fixture ladder must resolve: point at the real repo for it
        kw.update(over)
        receipt = P.run_diagnostic_unit(**kw)
        return receipt, runner, identity, authority

    def test_happy_path_produces_receipt(self):
        receipt, runner, _, _ = self._run()
        self.assertEqual(receipt["schema"], P.UNIT_SCHEMA)
        self.assertEqual(receipt["tag"], "case-3072-B-devnone-001")
        self.assertEqual(receipt["argv_delta"], ["-dev", "none"])
        self.assertEqual(receipt["authority"]["arm"],
                         "A-vulkan-necessity")
        self.assertTrue((self.env.evidence / self.env.namespace /
                         "case-3072-B-devnone-001" / "unit.json").is_file())

    def test_namespace_arm_mismatch_denies_before_any_launch(self):
        runner = Recorder(fn=fake_execute)
        with self.assertRaises(D.DiagnosticError):
            P.run_diagnostic_unit(
                repo_root=self.env.repo, evidence_root=self.env.evidence,
                namespace="d250-arm-a", arm="C-cpu-threads",
                tag="case-3072-B-devnone-001",
                binary=self.env.bin, binary_id="comparator",
                model_dir=self.env.model_dir,
                expected_head=self.env.head,
                model_attestation=self.env.attestation,
                execute=runner)
        self.assertEqual(runner.calls, [])

    def test_unknown_tag_denies_with_zero_runner_calls(self):
        runner = Recorder(fn=fake_execute)
        identity = Recorder(value=fake_identity())
        authority = self.env.authority_fn()
        with self.assertRaises(P.PhysicalDiagnosticError):
            P.run_diagnostic_unit(
                repo_root=self.env.repo, evidence_root=self.env.evidence,
                namespace=self.env.namespace, arm=self.env.arm,
                tag="case-3072-B-devnone-099",
                binary=self.env.bin, binary_id="comparator",
                model_dir=self.env.model_dir,
                expected_head=self.env.head,
                model_attestation=self.env.attestation,
                execute=runner, identity_observer=identity,
                revalidate_authority=authority,
                health_runner=fake_health_runner)
        self.assertEqual(runner.calls, [])

    def test_remote_drift_between_preflight_and_launch_denies(self):
        # late fetch returns a DIFFERENT body: zero runner calls
        runner = Recorder(fn=fake_execute)
        identity = Recorder(value=fake_identity())
        authority = self.env.authority_fn()
        calls = {"n": 0}

        def drifting(repo_root, expected_head, namespace, github_api=None):
            calls["n"] += 1
            payload = dict(authority.state["base"])
            if calls["n"] >= 2:
                payload["body"] += "\nextra remote line"
            return payload
        with self.assertRaises(D.DiagnosticError):
            P.run_diagnostic_unit(
                repo_root=self.env.repo, evidence_root=self.env.evidence,
                namespace=self.env.namespace, arm=self.env.arm,
                tag="case-3072-B-devnone-001",
                binary=self.env.bin, binary_id="comparator",
                model_dir=self.env.model_dir,
                expected_head=self.env.head,
                model_attestation=self.env.attestation,
                execute=runner, identity_observer=identity,
                revalidate_authority=drifting,
                health_runner=fake_health_runner)
        self.assertEqual(runner.calls, [])
        self.assertGreaterEqual(calls["n"], 2)

    def test_closed_pr_denies_before_launch(self):
        runner = Recorder(fn=fake_execute)
        identity = Recorder(value=fake_identity())
        authority = self.env.authority_fn(
            [lambda p: p.update({"open_pr": False})])
        with self.assertRaises(D.DiagnosticError):
            P.run_diagnostic_unit(
                repo_root=self.env.repo, evidence_root=self.env.evidence,
                namespace=self.env.namespace, arm=self.env.arm,
                tag="case-3072-B-devnone-001",
                binary=self.env.bin, binary_id="comparator",
                model_dir=self.env.model_dir,
                expected_head=self.env.head,
                model_attestation=self.env.attestation,
                execute=runner, identity_observer=identity,
                revalidate_authority=authority,
                health_runner=fake_health_runner)
        self.assertEqual(runner.calls, [])

    def test_arm_mismatch_in_dispatch_denies(self):
        runner = Recorder(fn=fake_execute)
        identity = Recorder(value=fake_identity())
        # comment authorizes arm A but caller asks arm B execution
        authority = self.env.authority_fn()
        with self.assertRaises(P.PhysicalDiagnosticError):
            P.run_diagnostic_unit(
                repo_root=self.env.repo, evidence_root=self.env.evidence,
                namespace="d250-arm-b", arm="B-process-init",
                tag="case-3072-B-cpu-fresh-001",
                binary=self.env.bin, binary_id="comparator",
                model_dir=self.env.model_dir,
                expected_head=self.env.head,
                model_attestation=self.env.attestation,
                execute=runner, identity_observer=identity,
                revalidate_authority=authority,
                health_runner=fake_health_runner)
        self.assertEqual(runner.calls, [])

    def test_missing_attestation_denies(self):
        (self.env.evidence / P.MODEL_ATTESTATION_OPEN_NAME).unlink()
        runner = Recorder(fn=fake_execute)
        identity = Recorder(value=fake_identity())
        authority = self.env.authority_fn()
        with self.assertRaises(P.PhysicalDiagnosticError):
            P.run_diagnostic_unit(
                repo_root=self.env.repo, evidence_root=self.env.evidence,
                namespace=self.env.namespace, arm=self.env.arm,
                tag="case-3072-B-devnone-001",
                binary=self.env.bin, binary_id="comparator",
                model_dir=self.env.model_dir,
                expected_head=self.env.head,
                model_attestation=self.env.attestation,
                execute=runner, identity_observer=identity,
                revalidate_authority=authority,
                health_runner=fake_health_runner)
        self.assertEqual(runner.calls, [])

    def test_identity_drift_denies_before_launch(self):
        runner = Recorder(fn=fake_execute)
        bad = {"schema": "x", "arm": "B", "raw": {}}
        identity = Recorder(value=bad)
        authority = self.env.authority_fn()
        with self.assertRaises(P.PhysicalDiagnosticError):
            P.run_diagnostic_unit(
                repo_root=self.env.repo, evidence_root=self.env.evidence,
                namespace=self.env.namespace, arm=self.env.arm,
                tag="case-3072-B-devnone-001",
                binary=self.env.bin, binary_id="comparator",
                model_dir=self.env.model_dir,
                expected_head=self.env.head,
                model_attestation=self.env.attestation,
                execute=runner, identity_observer=identity,
                revalidate_authority=authority,
                health_runner=fake_health_runner)
        self.assertEqual(runner.calls, [])

    def test_binary_mismatch_denies(self):
        runner = Recorder(fn=fake_execute)
        identity = Recorder(value=fake_identity())
        authority = self.env.authority_fn()
        with self.assertRaises(P.PhysicalDiagnosticError):
            P.run_diagnostic_unit(
                repo_root=self.env.repo, evidence_root=self.env.evidence,
                namespace=self.env.namespace, arm=self.env.arm,
                tag="case-3072-B-devnone-001",
                binary=Path("/bin/true"), binary_id="canonical",
                model_dir=self.env.model_dir,
                expected_head=self.env.head,
                model_attestation=self.env.attestation,
                execute=runner, identity_observer=identity,
                revalidate_authority=authority,
                health_runner=fake_health_runner)
        self.assertEqual(runner.calls, [])

    def test_contract_override_must_equal_frozen(self):
        receipt, _, _, _ = self._run(
            request_contract=dict(D.REQUEST_CONTRACT))
        self.assertEqual(receipt["request_contract"],
                         D.REQUEST_CONTRACT)
        with self.assertRaises(D.DiagnosticError):
            self._run(request_contract={
                **D.REQUEST_CONTRACT, "top_k": 2})

    def test_model_witness_drift_denies(self):
        # mutate one member's mtime -> stat witness mismatch
        member = self.env.model_files[D.MODEL_MEMBERS[1]]
        import os
        os.utime(member, ns=(1, 1))
        runner = Recorder(fn=fake_execute)
        identity = Recorder(value=fake_identity())
        authority = self.env.authority_fn()
        with self.assertRaises(P.PhysicalDiagnosticError):
            P.run_diagnostic_unit(
                repo_root=self.env.repo, evidence_root=self.env.evidence,
                namespace=self.env.namespace, arm=self.env.arm,
                tag="case-3072-B-devnone-001",
                binary=self.env.bin, binary_id="comparator",
                model_dir=self.env.model_dir,
                expected_head=self.env.head,
                model_attestation=self.env.attestation,
                execute=runner, identity_observer=identity,
                revalidate_authority=authority,
                health_runner=fake_health_runner)
        self.assertEqual(runner.calls, [])

    def test_append_only_unit_dirs(self):
        self._run()
        with self.assertRaises(D.DiagnosticError):
            self._run()  # same tag cannot be replaced
        # quarantine then re-run is the sanctioned path
        P.quarantine_unit(self.env.evidence, self.env.namespace,
                          "case-3072-B-devnone-001")
        receipt, _, _, _ = self._run()
        self.assertEqual(receipt["tag"], "case-3072-B-devnone-001")

    def test_two_pass_authority_binding_recorded(self):
        receipt, _, _, authority = self._run()
        # both fetches observed the identical payload (the recorder
        # wraps the env's fetcher)
        self.assertEqual(len(authority.calls), 2)
        self.assertIn("dispatch_sha256", receipt["authority"])

    def test_server_argv_carries_only_declared_factor(self):
        receipt, _, _, _ = self._run()
        argv = receipt["server_argv"]
        self.assertEqual(argv[-2:], ["-dev", "none"])
        self.assertIn("--ctx-size", argv)
        self.assertIn("--batch-size", argv)
        self.assertEqual(argv[argv.index("-ngl") + 1], "0")

    def test_same_process_tag_cannot_use_fresh_path(self):
        runner = Recorder(fn=fake_execute)
        identity = Recorder(value=fake_identity())
        authority = self.env.authority_fn()
        with self.assertRaises(P.PhysicalDiagnosticError):
            P.run_diagnostic_unit(
                repo_root=self.env.repo, evidence_root=self.env.evidence,
                namespace="d250-arm-b", arm="B-process-init",
                tag="case-3072-B-cpu-sameproc-001",
                binary=self.env.bin, binary_id="comparator",
                model_dir=self.env.model_dir,
                expected_head=self.env.head,
                model_attestation=self.env.attestation,
                execute=runner, identity_observer=identity,
                revalidate_authority=authority,
                health_runner=fake_health_runner)
        self.assertEqual(runner.calls, [])


class SameProcessLifecycleTests(unittest.TestCase):
    """The Arm-B one-process population + the maintainer mutations."""

    def setUp(self):
        self.env = Env(self, namespace="d250-arm-b",
                       arm="B-process-init")
        self.env.open_attestation()

    def _run(self, execute=None, **over):
        runner = Recorder(fn=execute or fake_same_process_execute)
        identity = Recorder(value=fake_identity())
        authority = self.env.authority_fn()
        kw = dict(
            repo_root=self.env.repo, evidence_root=self.env.evidence,
            namespace=self.env.namespace, arm=self.env.arm,
            tag_prefix="case-3072-B-cpu-sameproc",
            binary=self.env.bin, binary_id="comparator",
            model_dir=self.env.model_dir, expected_head=self.env.head,
            model_attestation=self.env.attestation,
            execute=runner, identity_observer=identity,
            revalidate_authority=authority,
            health_runner=fake_health_runner,
        )
        kw.update(over)
        return P.run_same_process_lifecycle(**kw), runner

    def test_one_shared_pid_five_requests(self):
        out, _ = self._run()
        lifecycle = out["lifecycle"]
        self.assertEqual(lifecycle["shared_server_pid"], 5252)
        self.assertEqual(lifecycle["request_count"], 5)
        self.assertEqual(len(out["receipts"]), 5)
        pids = {r["same_process"]["shared_server_pid"]
                for r in out["receipts"]}
        self.assertEqual(pids, {5252})
        indexes = sorted(r["same_process"]["request_index"]
                         for r in out["receipts"])
        self.assertEqual(indexes, [0, 1, 2, 3, 4])
        # every receipt binds the ARM-B contract (id_slot=3)
        for r in out["receipts"]:
            self.assertEqual(r["request_contract"], D.ARM_B_CONTRACT)
            self.assertTrue(r["same_process"]["reset_proof"][
                "slot_selected_by_id"])
            self.assertTrue(r["same_process"]["reset_proof"][
                "full_recompute_proven"])

    def test_pid_change_mid_arm_is_fatal(self):
        def mutating(argv, env, request, prompt, port, unit_dir,
                     repeats, expected_prompt_tokens):
            result = fake_same_process_execute(
                argv, env, request, prompt, port, unit_dir, repeats,
                expected_prompt_tokens)
            result["requests"][2]["server_pid"] = 9999
            return result
        with self.assertRaises(P.PhysicalDiagnosticError):
            self._run(execute=mutating)

    def test_wrong_id_slot_is_fatal(self):
        def wrong_slot(argv, env, request, prompt, port, unit_dir,
                       repeats, expected_prompt_tokens):
            result = fake_same_process_execute(
                argv, env, request, prompt, port, unit_dir, repeats,
                expected_prompt_tokens)
            # contract drifts to id_slot 0 on request 3
            result["requests"][3]["request_contract"] = {
                **D.ARM_B_CONTRACT, "id_slot": 0}
            return result
        with self.assertRaises(P.PhysicalDiagnosticError):
            self._run(execute=wrong_slot)

    def test_missing_full_recompute_proof_is_fatal(self):
        def cache_reuse(argv, env, request, prompt, port, unit_dir,
                        repeats, expected_prompt_tokens):
            result = fake_same_process_execute(
                argv, env, request, prompt, port, unit_dir, repeats,
                expected_prompt_tokens)
            # request 4 reuses cache: prompt eval reports only 100
            # tokens (no full recompute)
            rec = result["requests"][4]
            rec["log_slice"] = (
                "slot get_availabl: id  3 | task 4 | "
                "selected slot by id (3)\n"
                "slot print_timing: id  3 | task 4 | prompt eval "
                "time = 100.00 ms / 100 tokens\n").encode()
            rec["reset_proof"] = P._parse_slot_log(
                rec["log_slice"].decode(), 4, expected_prompt_tokens)
            return result
        with self.assertRaises(P.PhysicalDiagnosticError):
            self._run(execute=cache_reuse)

    def test_missing_prompt_eval_evidence_is_fatal(self):
        def no_eval(argv, env, request, prompt, port, unit_dir,
                    repeats, expected_prompt_tokens):
            result = fake_same_process_execute(
                argv, env, request, prompt, port, unit_dir, repeats,
                expected_prompt_tokens)
            rec = result["requests"][1]
            rec["log_slice"] = (
                "slot get_availabl: id  3 | task 1 | "
                "selected slot by id (3)\n").encode()
            rec["reset_proof"] = P._parse_slot_log(
                rec["log_slice"].decode(), 1, expected_prompt_tokens)
            return result
        with self.assertRaises(P.PhysicalDiagnosticError):
            self._run(execute=no_eval)

    def test_lru_slot_selection_not_by_id_is_fatal(self):
        def lru(argv, env, request, prompt, port, unit_dir,
                repeats, expected_prompt_tokens):
            result = fake_same_process_execute(
                argv, env, request, prompt, port, unit_dir, repeats,
                expected_prompt_tokens)
            rec = result["requests"][0]
            rec["log_slice"] = (
                "slot get_availabl: id  3 | task 0 | selected slot by "
                f"LRU, t_last = -1\nslot print_timing: id  3 | task 0 | "
                f"prompt eval time = 1.00 ms / "
                f"{expected_prompt_tokens} tokens\n").encode()
            rec["reset_proof"] = P._parse_slot_log(
                rec["log_slice"].decode(), 0, expected_prompt_tokens)
            return result
        with self.assertRaises(P.PhysicalDiagnosticError):
            self._run(execute=lru)

    def test_request_count_drift_is_fatal(self):
        def four(argv, env, request, prompt, port, unit_dir,
                 repeats, expected_prompt_tokens):
            result = fake_same_process_execute(
                argv, env, request, prompt, port, unit_dir, repeats,
                expected_prompt_tokens)
            result["requests"] = result["requests"][:4]
            return result
        with self.assertRaises(P.PhysicalDiagnosticError):
            self._run(execute=four)

    def test_lifecycle_dir_is_append_only(self):
        self._run()
        with self.assertRaises(D.DiagnosticError):
            self._run()

    def test_lifecycle_requires_arm_b(self):
        with self.assertRaises(P.PhysicalDiagnosticError):
            P.run_same_process_lifecycle(
                repo_root=self.env.repo, evidence_root=self.env.evidence,
                namespace="d250-arm-a", arm="A-vulkan-necessity",
                tag_prefix="case-3072-B-cpu-sameproc",
                binary=self.env.bin, binary_id="comparator",
                model_dir=self.env.model_dir,
                expected_head=self.env.head,
                model_attestation=self.env.attestation)

    def test_remote_drift_denies_with_zero_launches(self):
        authority = self.env.authority_fn()
        calls = {"n": 0}

        def drifting(repo_root, expected_head, namespace, github_api=None):
            calls["n"] += 1
            payload = dict(authority.state["base"])
            if calls["n"] >= 2:
                payload["comment_id"] = 2
            return payload
        runner = Recorder(fn=fake_same_process_execute)
        identity = Recorder(value=fake_identity())
        with self.assertRaises(D.DiagnosticError):
            P.run_same_process_lifecycle(
                repo_root=self.env.repo, evidence_root=self.env.evidence,
                namespace=self.env.namespace, arm=self.env.arm,
                tag_prefix="case-3072-B-cpu-sameproc",
                binary=self.env.bin, binary_id="comparator",
                model_dir=self.env.model_dir,
                expected_head=self.env.head,
                model_attestation=self.env.attestation,
                execute=runner, identity_observer=identity,
                revalidate_authority=drifting,
                health_runner=fake_health_runner)
        self.assertEqual(runner.calls, [])


class CampaignAttestationTests(unittest.TestCase):
    def setUp(self):
        self.env = Env(self)

    def _hasher(self, path):
        return D.MODEL_MEMBER_SHA256[path.name]

    def test_open_close_lifecycle(self):
        att = P.open_campaign_attestation(
            self.env.evidence, self.env.model_dir, self.env.head,
            hasher=self._hasher)
        closing = P.close_campaign_attestation(
            self.env.evidence, self.env.model_dir, self.env.head,
            hasher=self._hasher)
        self.assertEqual(
            closing["opening_attestation_sha256"],
            att["attestation_sha256"])
        self.assertTrue((self.env.evidence
                         / P.MODEL_ATTESTATION_CLOSE_NAME).is_file())

    def test_open_is_append_only(self):
        P.open_campaign_attestation(
            self.env.evidence, self.env.model_dir, self.env.head,
            hasher=self._hasher)
        with self.assertRaises(P.PhysicalDiagnosticError):
            P.open_campaign_attestation(
                self.env.evidence, self.env.model_dir, self.env.head,
                hasher=self._hasher)

    def test_close_detects_member_mutation(self):
        P.open_campaign_attestation(
            self.env.evidence, self.env.model_dir, self.env.head,
            hasher=self._hasher)
        # mutate member bytes -> closing re-hash changes digest
        member = self.env.model_files[D.MODEL_MEMBERS[2]]

        def bad_hasher(path):
            if path.name == D.MODEL_MEMBERS[2]:
                return "0" * 64
            return D.MODEL_MEMBER_SHA256[path.name]
        with self.assertRaises(D.DiagnosticError):
            P.close_campaign_attestation(
                self.env.evidence, self.env.model_dir, self.env.head,
                hasher=bad_hasher)

    def test_close_requires_opening(self):
        with self.assertRaises(P.PhysicalDiagnosticError):
            P.close_campaign_attestation(
                self.env.evidence, self.env.model_dir, self.env.head,
                hasher=self._hasher)

    def test_witness_detects_topology_change(self):
        att = P.open_campaign_attestation(
            self.env.evidence, self.env.model_dir, self.env.head,
            hasher=self._hasher)
        # add an unexpected .gguf member
        (self.env.model_dir / "extra.gguf").write_bytes(b"x")
        problems, witness = P.attestation_witness(
            self.env.model_dir, att)
        self.assertTrue(problems)
        self.assertIsNone(witness)


class LadderDerivationTests(unittest.TestCase):
    def test_ladder_lengths_predeclared(self):
        ladder = json.loads(
            (REPO / D.FIXTURE_LADDER_REL).read_bytes())
        base = {c["case_id"]: c for c in ladder["cases"]}[D.CASE]
        for length, repeats in D.ARM_D_LADDER_SENTENCE_REPEATS.items():
            prompt = P.derive_ladder_prompt(
                base["prompt_text"], length,
                base["sentence_repeats"],
                len(base["prompt_token_ids"]))
            block = ("The lighthouse keeper counted forty-one waves "
                     "before the foghorn answered twice. ")
            head = base["prompt_text"][:base["prompt_text"].index(block)]
            tail = base["prompt_text"][
                base["prompt_text"].rindex(block) + len(block):]
            self.assertEqual(prompt, head + block * repeats + tail)

    def test_undeclared_length_refused(self):
        ladder = json.loads(
            (REPO / D.FIXTURE_LADDER_REL).read_bytes())
        base = {c["case_id"]: c for c in ladder["cases"]}[D.CASE]
        with self.assertRaises(P.PhysicalDiagnosticError):
            P.derive_ladder_prompt(base["prompt_text"], 4096,
                                   base["sentence_repeats"],
                                   len(base["prompt_token_ids"]))

    def test_ladder_unit_argv_has_no_delta(self):
        plan = D.probe_list_for("D-context-transition")
        argv = P.server_argv(Path("/bin/llama-server"),
                             Path("/model/member1.gguf"), plan[0])
        self.assertNotIn("-dev", argv)
        self.assertEqual(argv[argv.index("-ngl") + 1], "8")


class NoPhysicalExecutionTests(unittest.TestCase):
    """Zero-physical-execution proof (correction pass 2): the producer
    modules never import or spawn GPU/model machinery at import time,
    and no test in this file performs physical work."""

    def test_no_gpu_model_subprocess_modules(self):
        for rel in ("scripts/issue250_physical.py",
                    "scripts/issue250_terminal.py"):
            src = (REPO / rel).read_text()
            self.assertNotIn("import torch", src)
            self.assertNotIn("import requests", src)
        # the real execute seams exist but tests only inject fakes
        self.assertTrue(callable(P._real_execute))
        self.assertTrue(callable(P._real_same_process_execute))


if __name__ == "__main__":
    unittest.main()
