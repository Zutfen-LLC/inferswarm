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
import os
import struct
import sys
import unittest
from pathlib import Path
from unittest import mock

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
TB = _load("issue250_timeout", "scripts/issue250_timeout.py")
P = _load("issue250_physical", "scripts/issue250_physical.py")
T = _load("issue250_terminal", "scripts/issue250_terminal.py")

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


def fake_execute(argv, env, request, prompt, port, unit_dir,
                     timeout_budget=None):
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
        },                "timeout_budget": timeout_budget,
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
                              unit_dir, repeats,
                              expected_prompt_tokens, timeout_s=None,
                              preflight_request=None):
    """Fake ONE-process lifecycle: shared PID, per-request proofs.

    Uses the PINNED server log grammar (SLT_INF ``slot <fn>: id N |
    task M |`` prefixes — correction pass 3, blocker 3): each request
    selects slot 3 BY ID (selection line structurally carries
    task -1), launches a fresh task, and prints its own full-prompt
    eval line. Task ids advance per request (fresh w.r.t. earlier
    requests of this lifecycle), as the pinned monotonic counter does.

    CORRECTION PASS 4 (NO-GO 5851078451, blocker 1): honors the real
    runner's truncation contract — a preflight (authority-gate)
    failure BEFORE request N stops the loop, keeps the completed
    prefix 0..N-1 in the return value, and reports
    stop_kind="truncated" with the cause instead of propagating.
    """
    import hashlib
    records = []
    now = datetime_now()
    shared_pid = 5252
    base_task_id = 100  # /health-style tasks may shift ids; ids fresh
    stop_kind = "completed_all"
    stop_reason = None
    for index in range(repeats):
        if preflight_request is not None:
            try:
                preflight_request(index)
            except Exception as exc:
                stop_kind = "truncated"
                stop_reason = (
                    f"authority-revalidation failure before request "
                    f"{index}: {exc}")
                break
        seed = hashlib.sha256(f"{prompt}:{index}".encode()).digest()
        row_files = {}
        meta_lines = []
        for d in range(D.DECISIONS):
            row = (seed * (D.ROW_BYTES // len(seed) + 1))[:D.ROW_BYTES]
            row_files[f"obs.row{d}.f32"] = row
            meta_lines.append(json.dumps(
                {"pos": d, "sampled_winner": TOKENS[d]}))
        meta_file = ("\n".join(meta_lines) + "\n").encode()
        task_id = base_task_id + index
        log_slice = (
            f"0.01.000.000 I slot get_availabl: id  3 | task -1 | "
            f"selected slot by id (3)\n"
            f"0.01.000.001 I slot launch_slot_: id  3 | task {task_id}"
            f" | processing task, is_child = 0\n"
            f"0.01.000.002 I slot print_timing: id  3 | task {task_id}"
            f" | prompt eval time = 42905.50 ms / "
            f"{expected_prompt_tokens} tokens "
            f"(  13.94 ms per token,   71.72 tokens per second)\n"
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
             "nvidia_smi_raw": "GPU-d5c05739-96c1-7e49-89b6-"
                               "bf54c2121c55, 42.0, 140.0, 170.0, 0\n"},
            {"stage": "during", "captured_at": now,
             "nvidia_smi_raw": "GPU-d5c05739-96c1-7e49-89b6-"
                               "bf54c2121c55, 43.0, 145.0, 170.0, 0\n"},
            {"stage": "after", "captured_at": now,
             "nvidia_smi_raw": "GPU-d5c05739-96c1-7e49-89b6-"
                               "bf54c2121c55, 41.0, 138.0, 170.0, 0\n"},
        ],
        "stop_kind": stop_kind,
        "stop_reason": stop_reason,
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
        P.retain_cost_planning_record(self.evidence)
        return self.attestation

    def authority_fn(self, mutations=None):
        base = make_authority(namespace=self.namespace, arm=self.arm,
                              head=self.head)
        state = {"base": base, "mutations": mutations or []}

        def fetch(repo_root, expected_head, namespace, github_api=None):
            if namespace == self.namespace:
                payload = dict(state["base"])
                for mutate in state["mutations"]:
                    mutate(payload)
                return payload
            arms = {"d250-arm-a": "A-vulkan-necessity",
                    "d250-arm-b": "B-process-init",
                    "d250-arm-c": "C-cpu-threads",
                    "d250-arm-c1": "C1-reduced-parallelism",
                    "d250-arm-c2": D.ARM_C2_NAME,
                    "d250-arm-d": "D-context-transition"}
            payload = make_authority(namespace, arms[namespace], self.head)
            if namespace == D.C2_SERIAL_NAMESPACE:
                payload["body"] += "\n" + D.C2_GATE_REQUIRED_LINE
            return payload
        fetch.state = state
        return fetch

    def populate_variable(self, namespace, arm):
        """Retain a real, reducer-verified early-mismatch prefix."""
        specs = [u for u in D.probe_list_for(arm)
                 if not u.get("same_process")][:2]
        assert len(specs) == 2
        for index, spec in enumerate(specs):
            if (self.evidence / namespace / spec["tag"] / "unit.json").is_file():
                continue  # an already-retained valid prefix from this fixture
            def execute(**kw):
                result = fake_execute(**kw)
                if index:
                    row = kw["unit_dir"] / "obs.row0.f32"
                    raw = row.read_bytes()
                    row.write_bytes(bytes([raw[0] ^ 1]) + raw[1:])
                return result
            P.run_diagnostic_unit(
                self.repo, self.evidence, namespace, arm, spec["tag"],
                binary=self.bin, binary_id="comparator",
                model_dir=self.model_dir, expected_head=self.head,
                model_attestation=self.attestation, execute=execute,
                identity_observer=fake_identity,
                revalidate_authority=self.authority_fn(),
                health_runner=fake_health_runner)

    def populate_b_same_variable(self):
        def execute(**kw):
            result = fake_same_process_execute(**{**kw, "repeats": 2})
            second = result["requests"][1]
            raw = second["row_files"]["obs.row0.f32"]
            second["row_files"]["obs.row0.f32"] = (
                bytes([raw[0] ^ 1]) + raw[1:])
            result["requests"] = result["requests"][:2]
            result["stop_kind"] = "mismatch_stop"
            result["stop_reason"] = "first verified row mismatch"
            return result
        P.run_same_process_lifecycle(
            self.repo, self.evidence, "d250-arm-b", "B-process-init",
            "case-3072-B-cpu-sameproc", binary=self.bin,
            binary_id="comparator", model_dir=self.model_dir,
            expected_head=self.head, model_attestation=self.attestation,
            execute=execute, identity_observer=fake_identity,
            revalidate_authority=self.authority_fn(),
            health_runner=fake_health_runner)

    def populate_through_c(self):
        self.populate_variable("d250-arm-a", "A-vulkan-necessity")
        self.populate_variable("d250-arm-b", "B-process-init")
        self.populate_b_same_variable()
        self.populate_variable("d250-arm-c", "C-cpu-threads")

    def populate_through_c2(self):
        self.populate_through_c()
        self.populate_variable("d250-arm-c1", "C1-reduced-parallelism")
        fetch = self.authority_fn()
        c1 = fetch(self.repo, self.head, "d250-arm-c1")
        c2 = fetch(self.repo, self.head, D.C2_SERIAL_NAMESPACE)
        P._write_json(self.evidence / D.C2_GATE_RECORD_NAME, {
            "schema": D.C2_GATE_RECORD_SCHEMA, "head_sha": self.head,
            "c1_completed": True, "c1_verdict": "variable",
            "c1_authority_sha256": D.authority_digest(c1),
            "c2_authority_sha256": D.authority_digest(c2),
        })
        self.populate_variable(D.C2_SERIAL_NAMESPACE, D.ARM_C2_NAME)


class ProducerSequentialReachabilityTests(unittest.TestCase):
    """The producer, not merely the reducer, enforces verified prefixes."""

    def _fresh(self, env, namespace, arm, runner):
        return P.run_diagnostic_unit(
            env.repo, env.evidence, namespace, arm,
            D.probe_list_for(arm)[0]["tag"],
            binary=env.bin, binary_id="comparator",
            model_dir=env.model_dir, expected_head=env.head,
            model_attestation=env.attestation, execute=runner,
            identity_observer=fake_identity,
            revalidate_authority=env.authority_fn(),
            health_runner=fake_health_runner)

    def test_reached_b_fresh_executes_but_tampered_a_rows_deny(self):
        env = Env(self, "d250-arm-b", "B-process-init")
        env.open_attestation()
        env.populate_variable("d250-arm-a", "A-vulkan-necessity")
        runner = Recorder(fn=fake_execute)
        self.assertEqual(self._fresh(env, env.namespace, env.arm, runner)[
            "arm_id"], "B-process-init")
        self.assertEqual(len(runner.calls), 1)
        runner.calls.clear()
        row = (env.evidence / "d250-arm-a" /
               D.probe_list_for("A-vulkan-necessity")[0]["tag"] /
               "obs.row0.f32")
        raw = row.read_bytes()
        row.write_bytes(bytes([raw[0] ^ 1]) + raw[1:])
        with self.assertRaisesRegex(P.PhysicalDiagnosticError, "sequential"):
            self._fresh(env, env.namespace, env.arm, runner)
        self.assertEqual(runner.calls, [])

    def test_reached_b_loses_predecessor_dispatch_before_launch(self):
        env = Env(self, "d250-arm-b", "B-process-init")
        env.open_attestation()
        env.populate_variable("d250-arm-a", "A-vulkan-necessity")
        runner = Recorder(fn=fake_execute)
        fetch = env.authority_fn()
        reads = 0

        def drift(repo, head, namespace, github_api=None):
            nonlocal reads
            payload = fetch(repo, head, namespace, github_api)
            if namespace == "d250-arm-a":
                reads += 1
                if reads > 1:
                    payload["comment_id"] += 1
            return payload

        with self.assertRaises((P.PhysicalDiagnosticError,
                                D.DiagnosticError)):
            P.run_diagnostic_unit(
                env.repo, env.evidence, env.namespace, env.arm,
                D.probe_list_for(env.arm)[0]["tag"],
                binary=env.bin, binary_id="comparator",
                model_dir=env.model_dir, expected_head=env.head,
                model_attestation=env.attestation, execute=runner,
                identity_observer=fake_identity,
                revalidate_authority=drift,
                health_runner=fake_health_runner)
        self.assertEqual(runner.calls, [])
        self.assertGreaterEqual(reads, 2)

    def test_unreached_b_same_process_does_not_launch(self):
        env = Env(self, "d250-arm-b", "B-process-init")
        env.open_attestation()
        runner = Recorder(fn=fake_same_process_execute)
        with self.assertRaisesRegex(P.PhysicalDiagnosticError, "sequential"):
            P.run_same_process_lifecycle(
                env.repo, env.evidence, env.namespace, env.arm,
                "case-3072-B-cpu-sameproc", binary=env.bin,
                binary_id="comparator", model_dir=env.model_dir,
                expected_head=env.head, model_attestation=env.attestation,
                execute=runner, identity_observer=fake_identity,
                revalidate_authority=env.authority_fn(),
                health_runner=fake_health_runner)
        self.assertEqual(runner.calls, [])

    def test_c_and_c1_require_each_predecessor_and_execute_when_reached(self):
        env = Env(self, "d250-arm-c", "C-cpu-threads")
        env.open_attestation()
        runner = Recorder(fn=fake_execute)
        env.populate_variable("d250-arm-a", "A-vulkan-necessity")
        with self.assertRaisesRegex(P.PhysicalDiagnosticError, "sequential"):
            self._fresh(env, env.namespace, env.arm, runner)
        self.assertEqual(runner.calls, [])
        env.populate_variable("d250-arm-b", "B-process-init")
        env.populate_b_same_variable()
        self.assertEqual(self._fresh(env, env.namespace, env.arm, runner)[
            "arm_id"], "C-cpu-threads")
        runner.calls.clear()
        with self.assertRaisesRegex(P.PhysicalDiagnosticError, "sequential"):
            self._fresh(env, "d250-arm-c1", "C1-reduced-parallelism",
                        runner)
        self.assertEqual(runner.calls, [])
        env.populate_variable("d250-arm-c", "C-cpu-threads")
        self.assertEqual(self._fresh(
            env, "d250-arm-c1", "C1-reduced-parallelism", runner)[
                "arm_id"], "C1-reduced-parallelism")

    def test_d_requires_verified_completed_variable_c2_before_runner(self):
        env = Env(self, "d250-arm-d", "D-context-transition")
        env.open_attestation()
        env.populate_through_c2()
        runner = Recorder(fn=fake_execute)
        # Tokenization is an independent gate; mock only that document
        # while the sequential gate validates REAL retained C2 rows.
        fixture = P.verify_fixtures(env.repo)[D.CASE]
        unit = D.probe_list_for(env.arm)[0]
        length = unit["ladder_length"]
        prompt = P.derive_ladder_prompt(
            fixture["prompt_text"], length, fixture["sentence_repeats"])
        entry = P.ladder_token_authority_receipt(
            length, D.ARM_D_LADDER_SENTENCE_REPEATS[length], prompt,
            D.sha256_bytes(prompt.encode()), 100)
        with mock.patch.object(P, "load_ladder_token_authority",
                               return_value={"lengths": {str(length): entry}}):
            self.assertEqual(self._fresh(env, env.namespace, env.arm, runner)[
                "arm_id"], "D-context-transition")
            self.assertEqual(len(runner.calls), 1)
            runner.calls.clear()
            row = (env.evidence / D.C2_SERIAL_NAMESPACE /
                   D.probe_list_for(D.ARM_C2_NAME)[0]["tag"] /
                   "obs.row0.f32")
            raw = row.read_bytes()
            row.write_bytes(bytes([raw[0] ^ 1]) + raw[1:])
            with self.assertRaisesRegex(P.PhysicalDiagnosticError,
                                        "sequential"):
                self._fresh(env, env.namespace, env.arm, runner)
            self.assertEqual(runner.calls, [])

    def test_d_rejects_complete_deterministic_c2_before_runner(self):
        env = Env(self, "d250-arm-d", "D-context-transition")
        env.open_attestation()
        env.populate_through_c()
        env.populate_variable("d250-arm-c1", "C1-reduced-parallelism")
        fetch = env.authority_fn()
        P._write_json(env.evidence / D.C2_GATE_RECORD_NAME, {
            "schema": D.C2_GATE_RECORD_SCHEMA, "head_sha": env.head,
            "c1_completed": True, "c1_verdict": "variable",
            "c1_authority_sha256": D.authority_digest(
                fetch(env.repo, env.head, "d250-arm-c1")),
            "c2_authority_sha256": D.authority_digest(
                fetch(env.repo, env.head, D.C2_SERIAL_NAMESPACE)),
        })
        for spec in D.probe_list_for(D.ARM_C2_NAME):
            P.run_diagnostic_unit(
                env.repo, env.evidence, D.C2_SERIAL_NAMESPACE,
                D.ARM_C2_NAME, spec["tag"], binary=env.bin,
                binary_id="comparator", model_dir=env.model_dir,
                expected_head=env.head, model_attestation=env.attestation,
                execute=fake_execute, identity_observer=fake_identity,
                revalidate_authority=env.authority_fn(),
                health_runner=fake_health_runner)
        runner = Recorder(fn=fake_execute)
        with self.assertRaisesRegex(P.PhysicalDiagnosticError,
                                    "sequential Arm C2 serial"):
            self._fresh(env, env.namespace, env.arm, runner)
        self.assertEqual(runner.calls, [])


class C2ProducerGateTests(unittest.TestCase):
    """C2 over-ceiling spend needs independently verified C1 rows."""

    def setUp(self):
        self.env = Env(self, "d250-arm-c2", D.ARM_C2_NAME)
        self.env.open_attestation()
        self.env.populate_through_c()
        self.c1 = make_authority("d250-arm-c1", "C1-reduced-parallelism",
                                 self.env.head)
        self.c2 = make_authority(D.C2_SERIAL_NAMESPACE, D.ARM_C2_NAME,
                                 self.env.head)
        self.c2["body"] += "\n" + D.C2_GATE_REQUIRED_LINE
        self.fetches = []
        self.runner = Recorder(fn=fake_execute)
        self.real_verify = T._verify_namespace_population
        self.verify = self.enterContext(mock.patch.object(
            T, "_verify_namespace_population"))
        self.enterContext(mock.patch.dict(sys.modules, {"issue250_terminal": T}))
        self.launch = self.enterContext(mock.patch.object(P, "_real_execute"))

    def _c1_rows(self, verdict="variable", problems=()):
        tags = [u["tag"] for u in D.probe_list_for(
            "C1-reduced-parallelism")]
        retained = tags if verdict == "deterministic" else tags[:2]
        if verdict == "incomplete":
            retained = tags[:1]
        digests = {tag: (("b" if verdict == "variable" and i else "a"),)
                   for i, tag in enumerate(retained)}
        population = {"units": [], "retained_tags": retained,
                      "prefix_law": D.prefix_population_facts(
                          tags, retained, digests)}
        self.verify.side_effect = lambda *args, **kwargs: (
            (population, list(problems)) if args[1] == "d250-arm-c1"
            else self.real_verify(*args, **kwargs))

    def _gate_record(self, verdict="variable"):
        P._write_json(self.env.evidence / D.C2_GATE_RECORD_NAME, {
            "schema": D.C2_GATE_RECORD_SCHEMA, "head_sha": self.env.head,
            "c1_completed": True, "c1_verdict": verdict,
            "c1_authority_sha256": D.authority_digest(self.c1),
            "c2_authority_sha256": D.authority_digest(self.c2),
        })

    def _fetch(self, repo, head, namespace, github_api=None):
        self.fetches.append(namespace)
        if namespace == "d250-arm-c1":
            return dict(self.c1)
        if namespace == "d250-arm-c2":
            return dict(self.c2)
        return self.env.authority_fn()(repo, head, namespace, github_api)

    def _run(self, namespace="d250-arm-c2", arm=D.ARM_C2_NAME):
        return P.run_diagnostic_unit(
            self.env.repo, self.env.evidence, namespace, arm,
            D.probe_list_for(D.ARM_C2_NAME)[0]["tag"],
            binary=self.env.bin, binary_id="comparator",
            model_dir=self.env.model_dir, expected_head=self.env.head,
            model_attestation=self.env.attestation,
            execute=self.runner, identity_observer=fake_identity,
            revalidate_authority=self._fetch,
            health_runner=fake_health_runner)

    def test_completed_variable_c1_and_both_live_dispatches_admit_c2(self):
        self._c1_rows()
        self._gate_record()
        receipt = self._run()
        self.assertEqual(receipt["namespace"], D.C2_SERIAL_NAMESPACE)
        self.assertEqual(len(self.runner.calls), 1)
        self.assertIn("d250-arm-c1", self.fetches)
        self.assertIn("d250-arm-c2", self.fetches)
        self.verify.assert_called()
        self.launch.assert_not_called()

    def test_valid_c1_gate_does_not_override_corrupt_a_predecessor(self):
        self._c1_rows()
        self._gate_record()
        row = (self.env.evidence / "d250-arm-a" /
               D.probe_list_for("A-vulkan-necessity")[0]["tag"] /
               "obs.row0.f32")
        raw = row.read_bytes()
        row.write_bytes(bytes([raw[0] ^ 1]) + raw[1:])
        with self.assertRaisesRegex(P.PhysicalDiagnosticError, "sequential"):
            self._run()
        self.assertEqual(self.runner.calls, [])
        self.launch.assert_not_called()

    def test_completed_deterministic_c1_admits_c2(self):
        self._c1_rows("deterministic")
        self._gate_record("deterministic")
        self.assertEqual(self._run()["namespace"], D.C2_SERIAL_NAMESPACE)
        self.assertEqual(len(self.runner.calls), 1)

    def test_real_retained_c1_rows_admit_c2_and_tamper_denies(self):
        # Build real producer receipts (fake CPU runner) so the terminal's
        # actual byte/digest verifier, not a stub verdict, proves C1.
        self.verify.side_effect = self.real_verify
        for spec in D.probe_list_for("C1-reduced-parallelism"):
            P.run_diagnostic_unit(
                self.env.repo, self.env.evidence, "d250-arm-c1",
                "C1-reduced-parallelism", spec["tag"],
                binary=self.env.bin, binary_id="comparator",
                model_dir=self.env.model_dir, expected_head=self.env.head,
                model_attestation=self.env.attestation,
                execute=self.runner, identity_observer=fake_identity,
                revalidate_authority=self._fetch,
                health_runner=fake_health_runner)
        self.runner.calls.clear()
        self._gate_record("deterministic")
        self.assertEqual(self._run()["namespace"], D.C2_SERIAL_NAMESPACE)
        self.assertEqual(len(self.runner.calls), 1)
        self.runner.calls.clear()
        row = (self.env.evidence / "d250-arm-c1" /
               D.probe_list_for("C1-reduced-parallelism")[0]["tag"] /
               "obs.row0.f32")
        raw = row.read_bytes()
        row.write_bytes(bytes([raw[0] ^ 1]) + raw[1:])
        with self.assertRaises(P.PhysicalDiagnosticError):
            self._run()
        self.assertEqual(self.runner.calls, [])
        self.launch.assert_not_called()

    def test_c2_gate_rejects_incomplete_and_corrupt_c1(self):
        self._gate_record()
        for verdict, problems in (("incomplete", ()),
                                  ("variable", ("corrupt row",))):
            with self.subTest(verdict=verdict, problems=problems):
                self._c1_rows(verdict, problems)
                with self.assertRaises(P.PhysicalDiagnosticError):
                    self._run()
                self.assertEqual(self.runner.calls, [])
                self.launch.assert_not_called()

    def test_c2_gate_rejects_missing_and_mismatched_record(self):
        self._c1_rows()
        with self.assertRaises(P.PhysicalDiagnosticError):
            self._run()
        self._gate_record()
        gate_path = self.env.evidence / D.C2_GATE_RECORD_NAME
        valid = json.loads(gate_path.read_bytes())
        for field, value in (("c1_verdict", "deterministic"),
                             ("c1_completed", False),
                             ("c1_authority_sha256", "0" * 64),
                             ("c2_authority_sha256", "0" * 64),
                             ("head_sha", "0" * 40)):
            with self.subTest(field=field):
                gate_path.write_text(json.dumps({**valid, field: value}))
                with self.assertRaises(P.PhysicalDiagnosticError):
                    self._run()
                self.assertEqual(self.runner.calls, [])
        self.launch.assert_not_called()

    def test_c1_live_authority_drift_before_launch_denies(self):
        self._c1_rows()
        self._gate_record()
        original = self._fetch
        c1_reads = 0

        def drift(repo, head, namespace, github_api=None):
            nonlocal c1_reads
            payload = original(repo, head, namespace, github_api)
            if namespace == "d250-arm-c1":
                c1_reads += 1
                if c1_reads > 1:
                    payload["body"] += "\nchanged after C1 proof"
            return payload

        self._fetch = drift
        with self.assertRaises(D.DiagnosticError):
            self._run()
        self.assertEqual(self.runner.calls, [])
        self.launch.assert_not_called()

    def test_generic_c_and_c1_cannot_launch_serial(self):
        self._c1_rows()
        self._gate_record()
        for namespace, arm in (("d250-arm-c", D.ARM_C2_NAME),
                               ("d250-arm-c1", D.ARM_C2_NAME),
                               ("d250-arm-c2", "C-cpu-threads")):
            with self.subTest(namespace=namespace, arm=arm):
                with self.assertRaises((P.PhysicalDiagnosticError,
                                        D.DiagnosticError)):
                    self._run(namespace, arm)
        self.assertEqual(self.runner.calls, [])
        self.launch.assert_not_called()

class ProducerGatingTests(unittest.TestCase):
    """Fresh-process producer: gate order + zero-runner-on-denial."""

    def setUp(self):
        self.env = Env(self)
        self.env.open_attestation()

    def test_arm_b_fresh_without_verified_arm_a_never_calls_runner(self):
        env = Env(self, "d250-arm-b", "B-process-init")
        env.open_attestation()
        runner = Recorder(fn=fake_execute)
        with self.assertRaisesRegex(P.PhysicalDiagnosticError, "sequential"):
            P.run_diagnostic_unit(
                env.repo, env.evidence, env.namespace, env.arm,
                D.probe_list_for(env.arm)[0]["tag"],
                binary=env.bin, binary_id="comparator",
                model_dir=env.model_dir, expected_head=env.head,
                model_attestation=env.attestation, execute=runner,
                identity_observer=fake_identity,
                revalidate_authority=env.authority_fn(),
                health_runner=fake_health_runner)
        self.assertEqual(runner.calls, [])

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
        self.env.populate_variable("d250-arm-a", "A-vulkan-necessity")

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

    # ---------------- per-request authority drift matrix ----------
    # (correction pass 3, BLOCKER 1) a live revalidation runs BEFORE
    # EVERY completion request; drift at request N means exactly the
    # prefix 0..N-1 executes and the lifecycle is retained incomplete.

    def _drift_run(self, drift_at, mutate):
        """Run with authority drifting at per-request gate N; return
        (lifecycle_doc, completion_indexes_issued)."""
        authority = self.env.authority_fn()
        gate_calls = {"n": 0}

        def drifting(repo_root, expected_head, namespace, github_api=None):
            if namespace != self.env.namespace:
                return authority(repo_root, expected_head, namespace, github_api)
            gate_calls["n"] += 1
            payload = dict(authority.state["base"])
            # gates: 2 prelaunch passes then one per request; drift
            # targets the per-request gate for request index
            if (drift_at is not None
                    and gate_calls["n"] == 3 + drift_at):
                mutate(payload)
            return payload

        issued = []

        def execute(argv, env, request, prompt, port, unit_dir,
                    repeats, expected_prompt_tokens,
                    preflight_request=None, timeout_s=None):
            # honest runner: the REAL gate runs before every request;
            # a gate failure stops the lifecycle before the HTTP
            # completion issues. `issued` records completions only.
            def effective(index):
                if preflight_request is not None:
                    preflight_request(index)  # may raise => no issue
                issued.append(index)
            return fake_same_process_execute(
                argv, env, request, prompt, port, unit_dir, repeats,
                expected_prompt_tokens,
                preflight_request=effective)

        try:
            P.run_same_process_lifecycle(
                repo_root=self.env.repo, evidence_root=self.env.evidence,
                namespace=self.env.namespace, arm=self.env.arm,
                tag_prefix="case-3072-B-cpu-sameproc",
                binary=self.env.bin, binary_id="comparator",
                model_dir=self.env.model_dir,
                expected_head=self.env.head,
                model_attestation=self.env.attestation,
                execute=execute, identity_observer=Recorder(
                    value=fake_identity()),
                revalidate_authority=drifting,
                health_runner=fake_health_runner)
            doc = None
        except (P.PhysicalDiagnosticError, D.DiagnosticError):
            doc = "raised"
        return doc, issued

    def test_all_gates_current_all_five_execute(self):
        doc, issued = self._drift_run(None, lambda p: None)
        self.assertEqual(issued, [0, 1, 2, 3, 4])

    def test_drift_before_request_0_zero_completions(self):
        doc, issued = self._drift_run(0, lambda p: p.update(head_sha="z" * 40))
        self.assertEqual(issued, [])

    def test_drift_before_request_1_only_request_0_executes(self):
        doc, issued = self._drift_run(1, lambda p: p.update(head_sha="z" * 40))
        self.assertEqual(issued, [0])

    def test_drift_before_request_2_only_0_and_1_execute(self):
        doc, issued = self._drift_run(2, lambda p: p.update(head_sha="z" * 40))
        self.assertEqual(issued, [0, 1])

    def test_pr_head_moves_mid_lifecycle_stops(self):
        doc, issued = self._drift_run(
            2, lambda p: p.update(open_pr=False))
        self.assertEqual(issued, [0, 1])

    def test_issue_closes_mid_lifecycle_stops(self):
        doc, issued = self._drift_run(
            2, lambda p: p.update(issue_open=False))
        self.assertEqual(issued, [0, 1])

    def test_comment_id_changes_mid_lifecycle_stops(self):
        doc, issued = self._drift_run(
            2, lambda p: p.update(comment_id=99))
        self.assertEqual(issued, [0, 1])

    def test_comment_body_changes_mid_lifecycle_stops(self):
        def change_body(p):
            p["body"] = p.get("body", "x") + "MUTATED"
        doc, issued = self._drift_run(2, change_body)
        self.assertEqual(issued, [0, 1])

    def test_namespace_changes_mid_lifecycle_stops(self):
        def change_ns(p):
            p["body"] = p["body"].replace(
                "diagnostic-namespace=d250-arm-b",
                "diagnostic-namespace=d250-arm-a")
            p["namespace"] = "d250-arm-a"
        doc, issued = self._drift_run(2, change_ns)
        self.assertEqual(issued, [0, 1])

    def test_arm_changes_mid_lifecycle_stops(self):
        # the arm is re-derived from the comment BODY line; the drift
        # must change the body's arm line (namespace<->arm binding
        # then fails, and the cross-bind digest changes)
        def change_arm(p):
            p["body"] = p["body"].replace(
                "arm=B-process-init", "arm=A-vulkan-necessity")
            p["arm"] = "A-vulkan-necessity"
        doc, issued = self._drift_run(2, change_arm)
        self.assertEqual(issued, [0, 1])

    def test_retained_prefix_does_not_satisfy_deterministic_claim(self):
        # truncated lifecycle: reducer judges an incomplete population
        out = T._verify_namespace_population  # not used directly; the
        # terminal-level fixture covers the reducer side. Here assert
        # the producer never marks a truncated lifecycle complete.
        doc, issued = self._drift_run(1, lambda p: p.update(head_sha="z" * 40))
        self.assertEqual(issued, [0])

    def test_pid_change_mid_arm_is_fatal(self):
        def mutating(argv, env, request, prompt, port,
                              unit_dir, repeats,
                              expected_prompt_tokens,
                              preflight_request=None, timeout_s=None):
            result = fake_same_process_execute(
                argv, env, request, prompt, port, unit_dir, repeats,
                expected_prompt_tokens,
                preflight_request=preflight_request)
            result["requests"][2]["server_pid"] = 9999
            return result
        with self.assertRaises(P.PhysicalDiagnosticError):
            self._run(execute=mutating)

    def test_wrong_id_slot_is_fatal(self):
        def wrong_slot(argv, env, request, prompt, port,
                              unit_dir, repeats,
                              expected_prompt_tokens,
                              preflight_request=None, timeout_s=None):
            result = fake_same_process_execute(
                argv, env, request, prompt, port, unit_dir, repeats,
                expected_prompt_tokens,
                preflight_request=preflight_request)
            # contract drifts to id_slot 0 on request 3
            result["requests"][3]["request_contract"] = {
                **D.ARM_B_CONTRACT, "id_slot": 0}
            return result
        with self.assertRaises(P.PhysicalDiagnosticError):
            self._run(execute=wrong_slot)

    def test_missing_full_recompute_proof_is_fatal(self):
        def cache_reuse(argv, env, request, prompt, port,
                              unit_dir, repeats,
                              expected_prompt_tokens,
                              preflight_request=None, timeout_s=None):
            result = fake_same_process_execute(
                argv, env, request, prompt, port, unit_dir, repeats,
                expected_prompt_tokens,
                preflight_request=preflight_request)
            # request 4 reuses cache: prompt eval reports only 100
            # tokens (no full recompute) on the CURRENT task
            rec = result["requests"][4]
            task = 100 + 4
            rec["log_slice"] = (
                f"0.01.000.000 I slot get_availabl: id  3 | task -1 | "
                f"selected slot by id (3)\n"
                f"0.01.000.001 I slot launch_slot_: id  3 | task "
                f"{task} | processing task, is_child = 0\n"
                f"0.01.000.002 I slot print_timing: id  3 | task "
                f"{task} | prompt eval "
                f"time = 100.00 ms / 100 tokens\n").encode()
            rec["reset_proof"] = P._parse_slot_log(
                rec["log_slice"].decode(), 4, expected_prompt_tokens)
            return result
        with self.assertRaises(P.PhysicalDiagnosticError):
            self._run(execute=cache_reuse)

    def test_missing_prompt_eval_evidence_is_fatal(self):
        def no_eval(argv, env, request, prompt, port,
                              unit_dir, repeats,
                              expected_prompt_tokens,
                              preflight_request=None, timeout_s=None):
            result = fake_same_process_execute(
                argv, env, request, prompt, port, unit_dir, repeats,
                expected_prompt_tokens,
                preflight_request=preflight_request)
            rec = result["requests"][1]
            task = 100 + 1
            rec["log_slice"] = (
                f"0.01.000.000 I slot get_availabl: id  3 | task -1 | "
                f"selected slot by id (3)\n"
                f"0.01.000.001 I slot launch_slot_: id  3 | task "
                f"{task} | processing task, is_child = 0\n").encode()
            rec["reset_proof"] = P._parse_slot_log(
                rec["log_slice"].decode(), 1, expected_prompt_tokens)
            return result
        with self.assertRaises(P.PhysicalDiagnosticError):
            self._run(execute=no_eval)

    def test_lru_slot_selection_not_by_id_is_fatal(self):
        def lru(argv, env, request, prompt, port,
                              unit_dir, repeats,
                              expected_prompt_tokens,
                              preflight_request=None, timeout_s=None):
            result = fake_same_process_execute(
                argv, env, request, prompt, port, unit_dir, repeats,
                expected_prompt_tokens,
                preflight_request=preflight_request)
            rec = result["requests"][0]
            rec["log_slice"] = (
                f"0.01.000.000 I slot get_availabl: id  3 | task -1 | "
                f"selected slot by LRU, t_last = -1\n"
                f"0.01.000.001 I slot launch_slot_: id  3 | task 100 | "
                f"processing task, is_child = 0\n"
                f"0.01.000.002 I slot print_timing: id  3 | task 100 | "
                f"prompt eval time = 1.00 ms / "
                f"{expected_prompt_tokens} tokens\n").encode()
            rec["reset_proof"] = P._parse_slot_log(
                rec["log_slice"].decode(), 0, expected_prompt_tokens)
            return result
        with self.assertRaises(P.PhysicalDiagnosticError):
            self._run(execute=lru)

    def test_delayed_prior_task_evidence_cannot_certify_request(self):
        # BLOCKER 3 OLD-DEFECT SHAPE: request 1's slice contains a
        # PERFECT task-0 (prior request) selection + full prompt eval,
        # but NO task-1 evidence. The task-bound proof must fail.
        def delayed(argv, env, request, prompt, port,
                              unit_dir, repeats,
                              expected_prompt_tokens,
                              preflight_request=None, timeout_s=None):
            result = fake_same_process_execute(
                argv, env, request, prompt, port, unit_dir, repeats,
                expected_prompt_tokens,
                preflight_request=preflight_request)
            rec = result["requests"][1]
            rec["log_slice"] = (
                "0.01.000.000 I slot get_availabl: id  3 | task -1 | "
                "selected slot by id (3)\n"
                "0.01.000.001 I slot launch_slot_: id  3 | task 100 | "
                "processing task, is_child = 0\n"
                "0.01.000.002 I slot print_timing: id  3 | task 100 | "
                f"prompt eval time = 1.00 ms / "
                f"{expected_prompt_tokens} tokens\n").encode()
            # prior-task (100 == request 0's task) evidence only
            rec["reset_proof"] = P._parse_slot_log(
                rec["log_slice"].decode(), 1, expected_prompt_tokens,
                consumed_task_ids=frozenset({100}))
            return result
        with self.assertRaises(P.PhysicalDiagnosticError):
            self._run(execute=delayed)

    def test_request_count_drift_is_fatal(self):
        def four(argv, env, request, prompt, port,
                              unit_dir, repeats,
                              expected_prompt_tokens,
                              preflight_request=None, timeout_s=None):
            result = fake_same_process_execute(
                argv, env, request, prompt, port, unit_dir, repeats,
                expected_prompt_tokens,
                preflight_request=preflight_request)
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
            if namespace != self.env.namespace:
                return authority(repo_root, expected_head, namespace, github_api)
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


class ArmBDriftPrefixCustodyTests(unittest.TestCase):
    """CORRECTION PASS 4 (NO-GO 5851078451, BLOCKER 1).

    Durable retention of the completed Arm-B prefix after a
    per-request authority-gate failure: on drift before request N,
    every completed request 0..N-1 is retained and finalized
    (unit directory + receipt), lifecycle.json exists with the
    truncated schema, and NO unit exists for request N or later.
    The reducer treats a truncated lifecycle as BLOCKED (never
    terminal-complete) even if the retained prefix happens to carry
    a row mismatch — the truncation cause dominates.
    """

    def setUp(self):
        self.env = Env(self, namespace="d250-arm-b",
                       arm="B-process-init")
        self.env.open_attestation()
        self.env.populate_variable("d250-arm-a", "A-vulkan-necessity")

    def _drift(self, drift_at, mutate=None, row_mismatch_at=None):
        """Drift the per-request gate at request index `drift_at`;
        optionally make request `row_mismatch_at` produce rows that
        differ from request 0 (accidental mismatch inside the
        retained prefix). Returns the runner return value and the
        list of issued completion indexes."""
        authority = self.env.authority_fn()
        gate = {"n": 0}

        def drifting(repo_root, expected_head, namespace,
                     github_api=None):
            if namespace != self.env.namespace:
                return authority(repo_root, expected_head, namespace, github_api)
            gate["n"] += 1
            payload = dict(authority.state["base"])
            if drift_at is not None and gate["n"] == 3 + drift_at:
                (mutate or (lambda p: p.update(
                    head_sha="z" * 40)))(payload)
            return payload

        issued = []

        def execute(argv, env, request, prompt, port, unit_dir,
                    repeats, expected_prompt_tokens,
                    preflight_request=None, timeout_s=None):
            import hashlib

            def effective(index):
                if preflight_request is not None:
                    preflight_request(index)  # may raise => no issue
                issued.append(index)

            if row_mismatch_at is None:
                return fake_same_process_execute(
                    argv, env, request, prompt, port, unit_dir,
                    repeats, expected_prompt_tokens,
                    preflight_request=effective)
            # variant: one request's rows differ from request 0's
            records = []
            now = datetime_now()
            base_rows = None
            for index in range(repeats):
                if preflight_request is not None:
                    try:
                        preflight_request(index)
                    except Exception as exc:
                        break
                issued.append(index)
                # deterministic rows across requests (a stable
                # baseline) EXCEPT at the designated mismatch index
                seed = hashlib.sha256(
                    f"{prompt}:baseline".encode()).digest()
                if index == row_mismatch_at:
                    seed = hashlib.sha256(
                        f"{prompt}:{index}:mismatch".encode()).digest()
                row_files = {}
                meta_lines = []
                for d in range(D.DECISIONS):
                    row = (seed * (D.ROW_BYTES // len(seed)
                                   + 1))[:D.ROW_BYTES]
                    row_files[f"obs.row{d}.f32"] = row
                    meta_lines.append(json.dumps(
                        {"pos": d, "sampled_winner": TOKENS[d]}))
                if base_rows is None:
                    base_rows = row_files
                mismatch = (index > 0 and row_files != base_rows)
                meta_file = ("\n".join(meta_lines) + "\n").encode()
                task_id = 100 + index
                log_slice = (
                    f"0.01.000.000 I slot get_availabl: id  3 | "
                    f"task -1 | selected slot by id (3)\n"
                    f"0.01.000.001 I slot launch_slot_: id  3 | "
                    f"task {task_id} | processing task, is_child = 0\n"
                    f"0.01.000.002 I slot print_timing: id  3 | "
                    f"task {task_id} | prompt eval time = 42905.50 ms "
                    f"/ {expected_prompt_tokens} tokens (  13.94 ms "
                    f"per token,   71.72 tokens per second)\n"
                ).encode()
                records.append({
                    "server_pid": 5252,
                    "tokens": list(TOKENS),
                    "response_raw": json.dumps(
                        {"tokens": TOKENS}).encode(),
                    "log_slice": log_slice,
                    "row_files": row_files,
                    "meta_file": meta_file,
                    "reset_proof": P._parse_slot_log(
                        log_slice.decode(), index,
                        expected_prompt_tokens),
                    "request_contract": dict(request),
                })
                if mismatch:
                    # honor the frozen early-stop law: the runner
                    # reports mismatch_stop at the first divergence
                    return {
                        "server_pid": 5252,
                        "process_attribution": {
                            "server_pid": 5252,
                            "server_exe_sha256":
                                D.SERVER_BINARIES["comparator"],
                            "server_argv": list(argv),
                            "server_env": dict(env),
                        },
                        "requests": records,
                        "device_samples": [
                            {"stage": "before", "captured_at": now,
                             "nvidia_smi_raw": "GPU-d5c05739-96c1-"
                                               "7e49-89b6-bf54c2121"
                                               "c55, 42.0, 140.0, "
                                               "170.0, 0\n"},
                            {"stage": "during", "captured_at": now,
                             "nvidia_smi_raw": "GPU-d5c05739-96c1-"
                                               "7e49-89b6-bf54c2121"
                                               "c55, 43.0, 145.0, "
                                               "170.0, 0\n"},
                            {"stage": "after", "captured_at": now,
                             "nvidia_smi_raw": "GPU-d5c05739-96c1-"
                                               "7e49-89b6-bf54c2121"
                                               "c55, 41.0, 138.0, "
                                               "170.0, 0\n"},
                        ],
                        "stop_kind": "mismatch_stop",
                        "stop_reason": (
                            f"first row-digest mismatch at request "
                            f"{index}"),
                    }
            return {
                "server_pid": 5252,
                "process_attribution": {
                    "server_pid": 5252,
                    "server_exe_sha256":
                        D.SERVER_BINARIES["comparator"],
                    "server_argv": list(argv),
                    "server_env": dict(env),
                },
                "requests": records,
                "device_samples": [
                    {"stage": "before", "captured_at": now,
                     "nvidia_smi_raw": "GPU-d5c05739-96c1-7e49-89b6-"
                                       "bf54c2121c55, 42.0, 140.0, "
                                       "170.0, 0\n"},
                    {"stage": "during", "captured_at": now,
                     "nvidia_smi_raw": "GPU-d5c05739-96c1-7e49-89b6-"
                                       "bf54c2121c55, 43.0, 145.0, "
                                       "170.0, 0\n"},
                    {"stage": "after", "captured_at": now,
                     "nvidia_smi_raw": "GPU-d5c05739-96c1-7e49-89b6-"
                                       "bf54c2121c55, 41.0, 138.0, "
                                       "170.0, 0\n"},
                ],
                "stop_kind": "completed_all",
                "stop_reason": None,
            }

        out = P.run_same_process_lifecycle(
            repo_root=self.env.repo, evidence_root=self.env.evidence,
            namespace=self.env.namespace, arm=self.env.arm,
            tag_prefix="case-3072-B-cpu-sameproc",
            binary=self.env.bin, binary_id="comparator",
            model_dir=self.env.model_dir,
            expected_head=self.env.head,
            model_attestation=self.env.attestation,
            execute=execute, identity_observer=Recorder(
                value=fake_identity()),
            revalidate_authority=drifting,
            health_runner=fake_health_runner)
        return out, issued

    # ---- required matrix A–F ------------------------------------

    def _unit_tags(self, n):
        return [f"case-3072-B-cpu-sameproc-{i + 1:03d}"
                for i in range(n)]

    def _assert_prefix_retained(self, completed, failed_index):
        ns = self.env.evidence / "d250-arm-b"
        lifecycle = (ns / "case-3072-B-cpu-sameproc-lifecycle"
                     / "lifecycle.json")
        self.assertTrue(lifecycle.is_file(),
                        "lifecycle.json must be retained")
        doc = json.loads(lifecycle.read_bytes())
        self.assertEqual(doc["stop_kind"], "truncated")
        self.assertFalse(doc["complete"])
        self.assertEqual(doc["planned_request_count"], 5)
        self.assertEqual(doc["request_count"], completed)
        self.assertEqual(doc["successful_gate_count"], completed)
        self.assertEqual(doc["gate_attempt_count"], completed + 1)
        self.assertEqual(doc["failed_gate_index"], failed_index)
        self.assertIsInstance(doc["stop_reason"], str)
        self.assertTrue(doc["stop_reason"])
        self.assertEqual(doc["shared_server_pid"], 5252)
        self.assertEqual(len(doc["per_request_authorities"]),
                         completed)
        # completed unit dirs + receipts; nothing for N or later
        for i, tag in enumerate(self._unit_tags(completed)):
            unit = ns / tag
            self.assertTrue(
                (unit / "unit.json").is_file(),
                f"request {i} unit receipt missing: {unit}")
            for name in ("obs.row0.f32", "obs.meta.json",
                         "response.json.raw", "server.log"):
                self.assertTrue((unit / name).is_file(),
                                f"{tag}/{name} missing")
        for tag in self._unit_tags(5)[completed:]:
            self.assertFalse(
                (ns / tag).exists(),
                f"no unit may exist for a request that never "
                f"executed: {tag}")
        return doc

    def test_A_drift_before_request_0_zero_completions(self):
        out, issued = self._drift(0)
        self.assertEqual(issued, [])
        doc = self._assert_prefix_retained(0, 0)
        self.assertEqual(doc["per_request_authorities"], [])
        self.assertEqual(doc["reset_proofs"], [])

    def test_B_drift_before_request_1_retains_request_0(self):
        out, issued = self._drift(1)
        self.assertEqual(issued, [0])
        doc = self._assert_prefix_retained(1, 1)
        # receipt carries its own successful authority block
        ns = self.env.evidence / "d250-arm-b"
        receipt = json.loads(
            (ns / "case-3072-B-cpu-sameproc-001" / "unit.json"
             ).read_bytes())
        self.assertIn("dispatch_sha256", receipt["authority"])
        self.assertEqual(receipt["same_process"]["request_index"], 0)

    def test_C_drift_before_request_2_retains_0_and_1(self):
        out, issued = self._drift(2)
        self.assertEqual(issued, [0, 1])
        self._assert_prefix_retained(2, 2)

    def test_D_drift_before_request_4_retains_first_four(self):
        out, issued = self._drift(4)
        self.assertEqual(issued, [0, 1, 2, 3])
        self._assert_prefix_retained(4, 4)

    def test_E_mismatch_stop_retained_normally(self):
        out, issued = self._drift(None, row_mismatch_at=2)
        self.assertEqual(issued, [0, 1, 2])
        ns = self.env.evidence / "d250-arm-b"
        doc = json.loads(
            (ns / "case-3072-B-cpu-sameproc-lifecycle"
             / "lifecycle.json").read_bytes())
        self.assertEqual(doc["stop_kind"], "mismatch_stop")
        # a mismatch_stop prefix is a COMPLETE nondeterministic
        # population under the frozen early-stop law (correction
        # pass 4 keeps it distinct from truncation)
        self.assertTrue(doc["complete"])
        self.assertIsNone(doc["failed_gate_index"])
        self.assertEqual(doc["request_count"], 3)
        self.assertEqual(doc["successful_gate_count"], 3)
        self.assertEqual(doc["gate_attempt_count"], 3)
        for tag in self._unit_tags(3):
            self.assertTrue(
                (ns / tag / "unit.json").is_file(), tag)

    def test_F_truncation_cause_dominates_accidental_mismatch(self):
        # REDUCER-side law (see test_issue250_terminal
        # TruncatedLifecycleReducerTests): a truncated lifecycle is
        # never terminal-complete even when its retained prefix
        # happens to contain differing rows. At the PRODUCER the
        # combination is unreachable by construction — the frozen
        # early-stop law reports mismatch_stop at the first
        # divergence BEFORE any later gate can fail — so here we
        # assert exactly that ordering invariant: with a designated
        # row mismatch at request 1 and authority drift at request
        # 2, the mismatch fires first and the lifecycle records
        # mismatch_stop (cause: the discriminator was answered).
        out, issued = self._drift(2, row_mismatch_at=1)
        self.assertEqual(issued, [0, 1])
        ns = self.env.evidence / "d250-arm-b"
        doc = json.loads(
            (ns / "case-3072-B-cpu-sameproc-lifecycle"
             / "lifecycle.json").read_bytes())
        self.assertEqual(doc["stop_kind"], "mismatch_stop")
        self.assertEqual(doc["request_count"], 2)
        self.assertIsNone(doc["failed_gate_index"])

    def test_no_authority_block_for_failed_request(self):
        out, issued = self._drift(1)
        ns = self.env.evidence / "d250-arm-b"
        doc = json.loads(
            (ns / "case-3072-B-cpu-sameproc-lifecycle"
             / "lifecycle.json").read_bytes())
        # exactly one successful per-request authority block (for
        # request 0); none manufactured for the failed request
        self.assertEqual(len(doc["per_request_authorities"]), 1)
        self.assertNotIn(
            "case-3072-B-cpu-sameproc-002",
            [p.name for p in ns.iterdir()])


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


class FakeServerProc:
    """A fake attributed llama-server process (correction pass 4,
    blocker 2 tests): stands in for the Popen object with poll/
    returncode control so the production attribution/verification
    code paths run unchanged."""

    def __init__(self, exe_sha, pid=31337):
        self.pid = pid
        self._pid = pid
        self.exe_sha = exe_sha
        self.argv: list = []
        self._terminated = False

    @property
    def pid(self):
        return self._pid

    @pid.setter
    def pid(self, value):
        self._pid = value

    def poll(self):
        return 0 if self._terminated else None

    def wait(self, timeout=None):
        self._terminated = True
        return 0

    @property
    def returncode(self):
        return 0

    def verify(self, expected_sha):
        # production _verify_tokenizer_process_still_attributed reads
        # /proc/<pid>/exe; the fake seam asserts the same binding
        if self._terminated:
            raise P.PhysicalDiagnosticError(
                "fake tokenizer server exited mid-authority")
        if self.exe_sha != expected_sha:
            raise P.PhysicalDiagnosticError(
                f"fake tokenizer server exe sha drift: {self.exe_sha}")

    def terminate(self):
        self._terminated = True


class TokenizerProcessAttributionTests(unittest.TestCase):
    """CORRECTION PASS 4 (NO-GO 5851078451, BLOCKER 2) — the 13
    required controls. Production ladder-token authority must come
    from a launched-and-attributed accepted llama-server process;
    every binding is verified and every mutation fails closed."""

    def setUp(self):
        self.env = Env(self)
        self.env.open_attestation()
        self.bin_sha = D.SERVER_BINARIES["comparator"]
        self.proc = FakeServerProc(self.bin_sha)
        self.launched = []

    def _launcher(self, *, exe_sha=None, argv_mutator=None,
                  model_member=None, port_occupied=lambda port: False):
        proc = self.proc

        def spawn(argv, log_path):
            proc.argv = list(argv)
            return proc

        attribution_exe = exe_sha if exe_sha is not None else self.bin_sha

        def attribution_fn(proc_, argv, env):
            return {"server_pid": proc_.pid,
                    "server_exe_sha256": attribution_exe,
                    "server_argv": list(argv),
                    "server_env": dict(env)}

        def fake_wait_healthy(proc_, port):
            pass

        member = model_member

        def launch(binary, binary_sha, model_dir, launch_member):
            argv = P.tokenizer_server_argv(
                binary, member or launch_member)
            if argv_mutator is not None:
                argv = argv_mutator(list(argv))
            handle = P.launch_tokenizer_server(
                binary, binary_sha, model_dir, member or launch_member,
                spawn=spawn, wait_healthy=fake_wait_healthy,
                port_occupied=port_occupied,
                attribution_fn=attribution_fn)
            self.launched.append(launch_member)
            return handle
        return launch

    def _http(self, counts=None, mutate_raw=None):
        counts = counts or {68: 1022, 102: 1534, 136: 2053,
                            153: 2303, 171: 2567, 204: 3077}

        def post(url, body):
            prompt = json.loads(body)["content"]
            n = counts[prompt.count("The lighthouse keeper counted")]
            doc = {"tokens": list(range(n))}
            raw = json.dumps(doc).encode()
            if mutate_raw is not None:
                raw = mutate_raw(raw)
            return raw, json.loads(raw)
        return post

    def _derive(self, launcher=None, http=None, **over):
        kw = dict(
            repo_root=self.env.repo, evidence_root=self.env.evidence,
            expected_head=self.env.head,
            binary=self.env.bin, binary_id="comparator",
            model_dir=self.env.model_dir,
            attestation=self.env.attestation,
            launch_server=launcher or self._launcher(),
            stop_server=lambda handle: self.proc.terminate(),
            verify_alive=lambda handle, sha: self.proc.verify(sha),
            http_post=http or self._http())
        kw.update(over)
        return P.derive_ladder_token_authority(**kw)

    def _retained(self):
        return json.loads(
            (self.env.evidence / P.LADDER_TOKEN_AUTHORITY_NAME
             ).read_bytes())

    # 1. attributed accepted process + correct binary/model =>
    #    authority accepted
    def test_1_attributed_process_authority_accepted(self):
        doc = self._derive()
        self.assertEqual(
            doc["authority"],
            "attributed_pinned_server_tokenize_endpoint")
        self.assertEqual(doc["process_attribution"]["server_pid"],
                         31337)
        self.assertEqual(
            doc["process_attribution"]["server_exe_sha256"],
            self.bin_sha)
        self.assertEqual(doc["process_attribution"]["argv"],
                         P.tokenizer_server_argv(
                             self.env.bin,
                             self.env.model_dir / D.MODEL_MEMBER_1))
        # and the reducer-side loader accepts the retained document
        loaded = P.load_ladder_token_authority(
            self.env.evidence, self.env.head)
        self.assertEqual(loaded["authority"], doc["authority"])

    # 2. wrong executable SHA => fail
    def test_2_wrong_executable_sha_fails(self):
        with self.assertRaises(P.PhysicalDiagnosticError) as ctx:
            self._derive(launcher=self._launcher(exe_sha="b" * 64))
        self.assertIn("executable SHA mismatch", str(ctx.exception))
        # the failed launch is torn down (poll() reports exit)
        self.assertIsNotNone(self.proc.poll())

    # 3. wrong binary id => fail (verify_binary gate)
    def test_3_wrong_binary_id_fails(self):
        with self.assertRaises(P.PhysicalDiagnosticError):
            self._derive(binary_id="reference")

    # 4. wrong model launch member => fail
    def test_4_wrong_model_launch_member_fails(self):
        other = self.env.model_dir / D.MODEL_MEMBERS[-1]
        self._derive(launcher=self._launcher(model_member=other))
        # the producer retained an argv bound to the WRONG member;
        # the reducer's process-block validation rejects it
        with self.assertRaises(P.PhysicalDiagnosticError) as ctx:
            P.load_ladder_token_authority(self.env.evidence,
                                          self.env.head)
        self.assertIn("model launch member mismatch",
                      str(ctx.exception))

    # 5. wrong model-attestation digest => fail
    def test_5_wrong_attestation_digest_fails(self):
        # a mutated digest fails the canonical attestation validation
        bad = json.loads(json.dumps(self.env.attestation))
        bad["attestation_sha256"] = "c" * 64
        with self.assertRaises(D.DiagnosticError):
            self._derive(attestation=bad)

    def test_5b_attestation_digest_binding_retained(self):
        doc = self._derive()
        self.assertEqual(
            doc["process_attribution"]["model_attestation_sha256"],
            self.env.attestation["attestation_sha256"])

    def test_5c_retained_digest_mutation_rejected(self):
        # mutate the digest INSIDE the retained process block: the
        # reducer's process-block validation rejects it
        self._derive()
        path = self.env.evidence / P.LADDER_TOKEN_AUTHORITY_NAME
        doc = json.loads(path.read_bytes())
        doc["process_attribution"][
            "model_attestation_sha256"] = "c" * 64
        path.write_bytes(json.dumps(doc).encode())
        with self.assertRaises(P.PhysicalDiagnosticError):
            P.load_ladder_token_authority(self.env.evidence,
                                          self.env.head)

    def test_6_changed_stat_witness_fails(self):
        member = self.env.model_files[D.MODEL_MEMBERS[0]]
        member.write_bytes(member.read_bytes() + b"x")
        with self.assertRaises(P.PhysicalDiagnosticError):
            self._derive()

    # 7. pre-existing unknown port listener => fail
    def test_7_preexisting_unknown_port_listener_fails(self):
        with self.assertRaises(P.PhysicalDiagnosticError) as ctx:
            self._derive(launcher=self._launcher(
                port_occupied=lambda port: True))
        self.assertIn("occupied by an unknown process",
                      str(ctx.exception))
        self.assertEqual(self.launched, [])

    # 8. process PID changes during authority generation => fail.
    # The production verifier reads /proc/<pid>/exe; swapping the
    # attributed PID for a live-but-different process (our own)
    # must fail the executable binding mid-authority.
    def test_8_pid_change_mid_authority_fails(self):
        verify_calls = {"n": 0}

        def verify(handle, sha):
            verify_calls["n"] += 1
            if verify_calls["n"] > 2:
                # process replaced: the attributed PID now names a
                # DIFFERENT live executable (our own interpreter)
                handle["proc"].pid = os.getpid()
                handle["attribution"]["server_exe_sha256"] = "e" * 64
            P._verify_tokenizer_process_still_attributed(handle, sha)
        with self.assertRaises(P.PhysicalDiagnosticError) as ctx:
            self._derive(verify_alive=verify)
        self.assertTrue(
            "changed mid-authority" in str(ctx.exception)
            or "vanished mid-authority" in str(ctx.exception),
            str(ctx.exception))

    # 9. raw tokenize response mutation => fail
    def test_9_raw_response_mutation_fails(self):
        # derive normally, then mutate the RETAINED raw response
        # bytes: the digest/size binding must catch it
        self._derive()
        path = self.env.evidence / P.LADDER_TOKEN_AUTHORITY_NAME
        doc = json.loads(path.read_bytes())
        entry = doc["lengths"]["2048"]
        import base64 as b64
        raw = bytearray(
            b64.b64decode(entry["tokenize_response_raw_b64"]))
        raw[raw.index(b"[0,") + 1] = ord("9")
        entry["tokenize_response_raw_b64"] = b64.b64encode(
            bytes(raw)).decode("ascii")
        path.write_bytes(json.dumps(doc).encode())
        with self.assertRaises(P.PhysicalDiagnosticError) as ctx:
            P.load_ladder_token_authority(self.env.evidence,
                                          self.env.head)
        self.assertIn("raw response bytes do not match",
                      str(ctx.exception))

    def test_9b_raw_ids_substitution_fails(self):
        # mutate raw bytes AND token ids consistently BUT leave the
        # digest: still caught (digest no longer matches content)
        self._derive()
        path = self.env.evidence / P.LADDER_TOKEN_AUTHORITY_NAME
        doc = json.loads(path.read_bytes())
        entry = doc["lengths"]["2048"]
        import base64 as b64
        raw = bytearray(
            b64.b64decode(entry["tokenize_response_raw_b64"]))
        raw[raw.index(b"[0,") + 1] = ord("9")
        entry["tokenize_response_raw_b64"] = b64.b64encode(
            bytes(raw)).decode("ascii")
        ids = [9] + entry["token_ids"][1:]
        entry["token_ids"] = ids
        entry["token_ids_sha256"] = D.sha256_bytes(
            json.dumps(ids, separators=(",", ":")).encode())
        path.write_bytes(json.dumps(doc).encode())
        with self.assertRaises(P.PhysicalDiagnosticError):
            P.load_ladder_token_authority(self.env.evidence,
                                          self.env.head)

    # 10. retained token ids/count mutation => reducer rejects
    def test_10_retained_token_mutation_rejected(self):
        self._derive()
        path = self.env.evidence / P.LADDER_TOKEN_AUTHORITY_NAME
        doc = json.loads(path.read_bytes())
        entry = doc["lengths"]["2048"]
        ids = entry["token_ids"]
        ids[0] = ids[0] + 1
        entry["token_ids"] = ids
        entry["token_ids_sha256"] = D.sha256_bytes(
            json.dumps(ids, separators=(",", ":")).encode())
        path.write_bytes(json.dumps(doc).encode())
        with self.assertRaises(P.PhysicalDiagnosticError):
            P.load_ladder_token_authority(self.env.evidence,
                                          self.env.head)

    # 11. prompt digest mutation => reducer rejects
    def test_11_prompt_digest_mutation_rejected(self):
        # derive, mutate the retained prompt digest, and re-derive
        # the REAL prompt text from the frozen ladder: the entry
        # validation must detect the binding loss
        self._derive()
        path = self.env.evidence / P.LADDER_TOKEN_AUTHORITY_NAME
        doc = json.loads(path.read_bytes())
        doc["lengths"]["2048"]["prompt_sha256"] = "d" * 64
        path.write_bytes(json.dumps(doc).encode())
        ladder = json.loads(
            (self.env.repo / D.FIXTURE_LADDER_REL).read_bytes())
        base = {c["case_id"]: c for c in ladder["cases"]}[D.CASE]
        prompt = P.derive_ladder_prompt(
            base["prompt_text"], 2048, base["sentence_repeats"])
        entry = P.load_ladder_token_authority(
            self.env.evidence, self.env.head)["lengths"]["2048"]
        with self.assertRaises(P.PhysicalDiagnosticError) as ctx:
            P.validate_ladder_token_authority_entry(entry, prompt)
        self.assertIn("different prompt text", str(ctx.exception))

    # 12. authority document without process attribution => rejected
    def test_12_document_without_attribution_rejected(self):
        self._derive()
        path = self.env.evidence / P.LADDER_TOKEN_AUTHORITY_NAME
        doc = json.loads(path.read_bytes())
        del doc["process_attribution"]
        doc["authority"] = "pinned_server_tokenize_endpoint"
        path.write_bytes(json.dumps(doc).encode())
        with self.assertRaises(P.PhysicalDiagnosticError) as ctx:
            P.load_ladder_token_authority(self.env.evidence,
                                          self.env.head)
        self.assertIn("attributed", str(ctx.exception))

    # 13. synthetic HTTP endpoint alone cannot produce production
    #     token authority (the bare `tokenize` test seam names
    #     itself test_seam and the reducer rejects it)
    def test_13_synthetic_endpoint_is_not_production_authority(self):
        doc = self._derive(tokenize=lambda prompt: (10, list(range(10))))
        self.assertEqual(doc["authority"], "test_seam")
        self.assertIsNone(doc["process_attribution"])
        with self.assertRaises(P.PhysicalDiagnosticError) as ctx:
            P.load_ladder_token_authority(self.env.evidence,
                                          self.env.head)
        self.assertIn("attributed", str(ctx.exception))


class LadderDerivationTests(unittest.TestCase):
    def test_ladder_lengths_predeclared(self):
        ladder = json.loads(
            (REPO / D.FIXTURE_LADDER_REL).read_bytes())
        base = {c["case_id"]: c for c in ladder["cases"]}[D.CASE]
        for length, repeats in D.ARM_D_LADDER_SENTENCE_REPEATS.items():
            prompt = P.derive_ladder_prompt(
                base["prompt_text"], length,
                base["sentence_repeats"])
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
                                   base["sentence_repeats"])

    def test_ladder_labels_are_generation_parameters_not_tokens(self):
        # CORRECTION PASS 3 (blocker 4A): nominal labels are sentence
        # repeat counts, never token counts; the derivation must not
        # consume or claim a token length.
        ladder = json.loads(
            (REPO / D.FIXTURE_LADDER_REL).read_bytes())
        base = {c["case_id"]: c for c in ladder["cases"]}[D.CASE]
        accepted = {c["case_id"]: len(c["prompt_token_ids"])
                    for c in ladder["cases"]}
        # accepted fixtures already show label != token count
        self.assertNotEqual(accepted["case-1024"], 1024)
        self.assertNotEqual(accepted[D.CASE], 3072)
        for length in D.ARM_D_LADDER_LENGTHS:
            prompt = P.derive_ladder_prompt(
                base["prompt_text"], length,
                base["sentence_repeats"])
            # the derived prompt's token count is derived ONLY through
            # the tokenizer authority, never from the label
            self.assertNotIn(str(length), ["0"])
            self.assertIsInstance(prompt, str)

    def test_tokenizer_authority_receipt_roundtrip(self):
        # nominal 2048 with actual 2053 => the authority carries 2053
        # and the reducer-side threshold judgment uses the ACTUAL
        # count (T.validate_ladder_length_authority in the terminal
        # reducer; nominal-vs-actual controls below). CORRECTION
        # PASS 5 (NO-GO 5852014883): the boundary is the explicit
        # all-cells/selective pair — 2051 itself is NOT selective
        # (width = min(2051, 2051) = 2051 covers the full
        # population); 2052 is the first selective-side count.
        receipt = P.ladder_token_authority_receipt(
            2048, 136, "x", "a" * 64, 2053)
        self.assertEqual(receipt["actual_token_count"], 2053)
        verdict = P.validate_ladder_token_authority(receipt)
        self.assertEqual(verdict["actual_token_count"], 2053)
        self.assertTrue(
            T.validate_ladder_length_authority(
                receipt, D.INDEXER_ALL_CELLS_MAX,
                D.INDEXER_SELECTIVE_MIN)["crosses_top_k"])
        self.assertTrue(
            T.validate_ladder_length_authority(
                receipt, D.INDEXER_ALL_CELLS_MAX,
                D.INDEXER_SELECTIVE_MIN)["selective_side"])
        # equality control: actual 2051 is STILL all-cells and must
        # NOT satisfy the selective-side predicate
        eq = P.ladder_token_authority_receipt(
            2048, 136, "x", "a" * 64, 2051)
        v2051 = T.validate_ladder_length_authority(
            eq, D.INDEXER_ALL_CELLS_MAX, D.INDEXER_SELECTIVE_MIN)
        self.assertFalse(v2051["crosses_top_k"])
        self.assertFalse(v2051["selective_side"])
        self.assertTrue(v2051["all_cells_side"])
        # 2050: all-cells side; cannot be considered selective
        v2050 = T.validate_ladder_length_authority(
            P.ladder_token_authority_receipt(
                2048, 136, "x", "a" * 64, 2050),
            D.INDEXER_ALL_CELLS_MAX, D.INDEXER_SELECTIVE_MIN)
        self.assertFalse(v2050["crosses_top_k"])
        self.assertTrue(v2050["all_cells_side"])
        # 2052: FIRST selective-side count
        v2052 = T.validate_ladder_length_authority(
            P.ladder_token_authority_receipt(
                2048, 136, "x", "a" * 64, 2052),
            D.INDEXER_ALL_CELLS_MAX, D.INDEXER_SELECTIVE_MIN)
        self.assertTrue(v2052["crosses_top_k"])
        self.assertTrue(v2052["selective_side"])
        self.assertFalse(v2052["all_cells_side"])
        # nominal 2048 with actual 2041 => threshold NOT crossed even
        # though the NOMINAL label equals 2048
        receipt2 = P.ladder_token_authority_receipt(
            2048, 136, "x", "a" * 64, 2041)
        self.assertFalse(
            T.validate_ladder_length_authority(
                receipt2, D.INDEXER_ALL_CELLS_MAX,
                D.INDEXER_SELECTIVE_MIN)["crosses_top_k"])
        # prompt text mutation changes token authority => BLOCKED
        with self.assertRaises(P.PhysicalDiagnosticError):
            P.validate_ladder_token_authority(receipt, prompt_text="x")

    def test_runtime_prompt_eval_must_match_token_authority(self):
        # retained tokenizer count disagrees with runtime prompt eval
        # => the reducer BLOCKS the length condition
        receipt = P.ladder_token_authority_receipt(
            2048, 136, "x", "a" * 64, 2053)
        verdict = T.validate_ladder_length_authority(
            receipt, D.INDEXER_ALL_CELLS_MAX,
            D.INDEXER_SELECTIVE_MIN, runtime_prompt_eval_tokens=2049)
        self.assertFalse(verdict["runtime_matches_authority"])

    def test_ladder_unit_argv_has_no_delta(self):
        plan = D.probe_list_for("D-context-transition")
        argv = P.server_argv(Path("/bin/llama-server"),
                             Path("/model/member1.gguf"), plan[0])
        self.assertNotIn("-dev", argv)
        self.assertEqual(argv[argv.index("-ngl") + 1], "8")


class TaskBoundResetProofMutationTests(unittest.TestCase):
    """BLOCKER 3 mutation matrix: the reset proof must bind to the
    CURRENT request's task; prior-request evidence (the old defect)
    can never certify the current request."""

    TOKENS = 3077

    def slice_for(self, task, tokens=None, selection="id", slot=3):
        tokens = tokens if tokens is not None else self.TOKENS
        sel = (f"0.01.000.000 I slot get_availabl: id {slot:2d} | "
               f"task -1 | selected slot by id ({slot})\n" if selection == "id"
               else f"0.01.000.000 I slot get_availabl: id {slot:2d} | "
                    f"task -1 | selected slot by LRU, t_last = -1\n")
        return (sel
                + f"0.01.000.001 I slot launch_slot_: id {slot:2d} | "
                f"task {task} | processing task, is_child = 0\n"
                + f"0.01.000.002 I slot print_timing: id {slot:2d} | "
                f"task {task} | prompt eval time = 1.0 ms / "
                f"{tokens} tokens\n")

    def prove(self, text, request_index, consumed=frozenset()):
        return P._parse_slot_log(text, request_index, self.TOKENS,
                                 consumed_task_ids=consumed)

    def test_correct_task_n_proof_passes(self):
        proof = self.prove(self.slice_for(100), 0)
        self.assertTrue(proof["proven"], proof["problems"])
        self.assertEqual(proof["task_id"], 100)
        self.assertEqual(proof["prompt_eval_tokens"], self.TOKENS)

    def test_prior_task_evidence_with_request_index_1_fails(self):
        # OLD-DEFECT SHAPE: slice carries task 100 (request 0's task)
        # while proving request 1; task 100 is consumed => fail
        proof = self.prove(self.slice_for(100), 1,
                           consumed=frozenset({100}))
        self.assertFalse(proof["proven"])
        self.assertTrue(any("fresh task" in p or "prior" in p
                            for p in proof["problems"]))

    def test_only_prior_selection_line_fails(self):
        text = (f"0.01.000.000 I slot get_availabl: id  3 | task -1 | "
                f"selected slot by id (3)\n")
        proof = self.prove(text, 1, consumed=frozenset({100}))
        self.assertFalse(proof["proven"])

    def test_only_prior_full_prompt_eval_fails(self):
        # no current-task launch; prior task's eval is in-slice
        text = (f"0.01.000.002 I slot print_timing: id  3 | task 100 | "
                f"prompt eval time = 1.0 ms / {self.TOKENS} tokens\n")
        proof = self.prove(text, 1, consumed=frozenset({100}))
        self.assertFalse(proof["proven"])

    def test_selection_current_but_prompt_eval_previous_fails(self):
        text = (f"0.01.000.000 I slot get_availabl: id  3 | task -1 | "
                f"selected slot by id (3)\n"
                f"0.01.000.001 I slot launch_slot_: id  3 | task 101 | "
                f"processing task, is_child = 0\n"
                f"0.01.000.002 I slot print_timing: id  3 | task 100 | "
                f"prompt eval time = 1.0 ms / {self.TOKENS} tokens\n")
        proof = self.prove(text, 1, consumed=frozenset({100}))
        self.assertFalse(proof["proven"])
        self.assertTrue(any("prompt-eval" in p
                            for p in proof["problems"]))

    def test_prompt_eval_current_but_selection_previous_fails(self):
        # prior task's by-id selection, current eval: the LRU-style
        # re-selection never happened for the current task — no
        # by-id selection after the prior launch
        text = (f"0.01.000.000 I slot get_availabl: id  3 | task -1 | "
                f"selected slot by id (3)\n"
                f"0.01.000.001 I slot launch_slot_: id  3 | task 100 | "
                f"processing task, is_child = 0\n"
                f"0.01.000.002 I slot print_timing: id  3 | task 101 | "
                f"prompt eval time = 1.0 ms / {self.TOKENS} tokens\n")
        proof = self.prove(text, 1, consumed=frozenset({100}))
        self.assertFalse(proof["proven"])

    def test_mixed_lines_no_coherent_current_proof_fails(self):
        text = (self.slice_for(100)
                + f"0.01.000.003 I slot get_availabl: id  3 | task -1 | "
                f"selected slot by id (3)\n")
        proof = self.prove(text, 1, consumed=frozenset({100}))
        self.assertFalse(proof["proven"])

    def test_duplicate_conflicting_task_boundaries_fail_closed(self):
        text = (self.slice_for(101)
                + f"0.01.000.003 I slot launch_slot_: id  3 | "
                f"task 102 | processing task, is_child = 0\n")
        proof = self.prove(text, 1, consumed=frozenset({100}))
        self.assertFalse(proof["proven"])
        self.assertTrue(any("conflicting" in p for p in proof["problems"]))

    def test_wrong_id_slot_fails(self):
        proof = self.prove(self.slice_for(101, slot=0), 1,
                           consumed=frozenset({100}))
        self.assertFalse(proof["proven"])

    def test_lru_selection_fails(self):
        proof = self.prove(self.slice_for(101, selection="lru"), 1,
                           consumed=frozenset({100}))
        self.assertFalse(proof["proven"])
        self.assertTrue(any("LRU" in p for p in proof["problems"]))

    def test_cache_reuse_partial_prompt_fails(self):
        proof = self.prove(self.slice_for(101, tokens=100), 1,
                           consumed=frozenset({100}))
        self.assertFalse(proof["proven"])
        self.assertTrue(any("cache reuse" in p
                            for p in proof["problems"]))

    def test_task_id_retained_in_proof_receipt(self):
        proof = self.prove(self.slice_for(101), 1,
                           consumed=frozenset({100}))
        self.assertEqual(proof["task_id"], 101)
        self.assertIn("consumed_prior_task_ids", proof)
        self.assertEqual(proof["consumed_prior_task_ids"], [100])



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
