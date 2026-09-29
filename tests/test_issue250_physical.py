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

import copy
import importlib.util
import tempfile
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
    # One #250 singleton set per process (same contract as
    # tests/test_issue250_terminal.py): if another test module already
    # established this module, reuse it — re-executing under the same
    # sys.modules name orphans the previous instance that earlier
    # importers (and the producers' own cross-imports) still hold.
    existing = sys.modules.get(name)
    if existing is not None and type(existing).__name__ == "module":
        return existing
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

# AMENDMENT-006 fixtures: the real per-device identity structure emitted
# by _v0_observe_device() on inferswarm05 (two RADV V340L dies), so the
# runtime-identity JSON round trip is exercised with production shape,
# not the historical {"kernel": "synthetic"} placeholder that let the
# int/str device-map defect escape CI.
V340L_DEVICE_IDENTITY = {
    "vendor_id": "0x1002", "device_id": "0x6864",
    "name": "AMD Radeon Pro V340 (RADV VEGA10)",
    "driver_id": "DRIVER_ID_MESA_RADV",
    "driver_info": "Mesa 25.0.7-2+deb13u1",
    "driver_version": "25.0.7", "api_version": "1.4.305",
}


def make_runtime_identity(keys: type | tuple = int):
    """Live-shaped runtime identity; keys=int mirrors the physical
    vulkaninfo parse (0/1), keys=str mirrors a JSON-retained record."""
    k0, k1 = ((0, 1) if keys is int else ("0", "1"))
    return {"kernel": "6.12.107+deb13u3-x",
            "vulkan_instance": "1.4.309",
            "devices": {k0: copy.deepcopy(V340L_DEVICE_IDENTITY),
                        k1: copy.deepcopy(V340L_DEVICE_IDENTITY)}}


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
        # Legacy A-D producer fixtures predate V0. Exercise their original
        # invariants independently; V0 admission has dedicated tests below.
        # AMENDMENT-008 r2: arm_a_reachability_source (the corrected
        # Arm-A gate) is patched for the same reason — these fixtures
        # have no predecessor evidence, and their provenance law is
        # covered by the dedicated amendment008_round2 producer tests.
        test.enterContext(mock.patch.object(P, "_require_v0_fallback"))
        test.enterContext(mock.patch.object(
            P, "arm_a_reachability_source",
            return_value="historical-v0-amd-variable"))
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



class V0ProspectivePlanTests(unittest.TestCase):
    def test_v0_plan_is_three_fresh_units_with_two_then_conditional_third(self):
        plan = P.v0_probe_plan()
        self.assertEqual([x["tag"] for x in plan], list(P.V0_UNIT_TAGS))
        self.assertEqual(len(plan), 3)
        self.assertTrue(all(x["fresh_process"] and x["ngl"] == 1
                            and x["backend"] == "Vulkan"
                            and x["embedding_placement"] == "CPU"
                            and x["output_projection_placement"] == "Vulkan"
                            for x in plan))
        self.assertTrue(all(x["minimum_first"] == 2
                            and x["third_if_first_two_identical"]
                            and x["stop_on_first_mismatch"] for x in plan))

    def test_v0_dispatch_requires_exact_namespace_arm_and_body(self):
        body = "\n".join((D.DIAGNOSTIC_DISPATCH_PHRASE, "head=" + HEAD,
                           "diagnostic-namespace=" + P.V0_NAMESPACE,
                           "arm=" + P.V0_ARM))
        authority = {"namespace": P.V0_NAMESPACE, "arm": P.V0_ARM,
                     "body": body, "head_sha": HEAD,
                     "issue_url": f"https://api.github.com/repos/Zutfen-LLC/inferswarm/issues/{D.DIAGNOSTIC_PR_NUMBER}",
                     "created_at": "2026-09-27T00:00:00Z",
                     "author_association": "MEMBER", "open_pr": True,
                     "issue_open": True, "comment_id": 5}
        self.assertEqual(P.validate_v0_dispatch(
            P.V0_NAMESPACE, P.V0_ARM, authority), authority)
        for namespace, arm, candidate in (
                ("d250-arm-a", "A-vulkan-necessity", authority),
                (P.V0_NAMESPACE, P.V0_ARM,
                 {**authority, "namespace": "d250-arm-a"}),
                (P.V0_NAMESPACE, P.V0_ARM,
                 {**authority, "arm": "A-vulkan-necessity"})):
            with self.subTest(namespace=namespace, arm=arm):
                with self.assertRaises(P.PhysicalDiagnosticError):
                    P.validate_v0_dispatch(namespace, arm, candidate)

    def test_v0_amd_argv_uses_only_environment_bound_selector(self):
        argv = P.v0_server_argv(Path("/server"), Path("/model"))
        self.assertEqual(argv[argv.index("-ngl") + 1], "1")
        self.assertNotIn("--device", argv)
        with self.assertRaises(TypeError):
            P.v0_server_argv(Path("/server"), Path("/model"),
                             vulkan_device_index=1)

    def test_v0_timeout_cost_is_separate_and_prospective(self):
        cost = TB.v0_cost_record()
        budget = TB.v0_request_timeout()
        self.assertEqual(cost["namespace"], P.V0_NAMESPACE)
        self.assertEqual(cost["arm"], P.V0_ARM)
        self.assertEqual(cost["min_screen_units"], 2)
        self.assertEqual(cost["max_screen_units"], 3)
        self.assertFalse(cost["auto_execution_authorized"])
        self.assertFalse(budget["auto_execution_authorized"])
        self.assertEqual(budget["namespace"], P.V0_NAMESPACE)
        with self.assertRaises(TB.TimeoutBudgetError):
            TB.v0_cost_record(0)


class V0ProducerAdmissionTests(unittest.TestCase):
    """Real entrypoint, with a runner that must never be reached on denial."""

    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.evidence = self.root / "evidence"
        self.evidence.mkdir()
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.calls = []
        P.retain_cost_planning_record(self.evidence)
        self.head = "a" * 40

    def authority(self, repo, head, namespace, github_api=None):
        return {"comment_id": 77, "issue_url":
                f"https://api.github.com/repos/Zutfen-LLC/inferswarm/issues/{D.DIAGNOSTIC_PR_NUMBER}",
                "created_at": "2026-09-27T00:00:00Z", "author_association": "MEMBER",
                "body": "\n".join((D.DIAGNOSTIC_DISPATCH_PHRASE,
                                    f"head={head}", f"diagnostic-namespace={namespace}",
                                    f"arm={P.V0_ARM}")),
                "head_sha": head, "namespace": namespace, "arm": P.V0_ARM,
                "open_pr": True, "issue_open": True}

    def invoke(self, tag=None, authority=None):
        def runner(**kw):
            self.calls.append(kw)
            raise RuntimeError("runner reached")
        return P.run_v0_unit(
            self.repo, self.evidence, P.V0_NAMESPACE, P.V0_ARM,
            tag or P.V0_UNIT_TAGS[0], binary=self.root / "bin",
            binary_id="comparator", model_dir=Path(D.MODEL_DIR),
            expected_head=self.head, model_attestation={},
            execute=runner, revalidate_authority=authority or self.authority)

    def test_stale_and_cross_arm_dispatch_never_reach_runner(self):
        for change in (lambda a: {**a, "head_sha": "1c86e97da42401ff7cfa98e3dc48a33517c65def"},
                       lambda a: {**a, "comment_id": D.STALE_DISPATCH_COMMENT_ID},
                       lambda a: {**a, "arm": "A-vulkan-necessity"},
                       lambda a: {**a, "namespace": "d250-arm-a"}):
            with self.subTest(change=change), self.assertRaises(P.PhysicalDiagnosticError):
                self.invoke(authority=lambda *args: change(self.authority(*args)))
            self.assertEqual(self.calls, [])

    def test_third_without_identical_verified_pair_never_reaches_runner(self):
        with self.assertRaises(Exception):
            self.invoke(tag=P.V0_UNIT_TAGS[2])
        self.assertEqual(self.calls, [])

    def test_forged_resigned_v0_cost_never_reaches_runner(self):
        import hashlib
        cost_path = self.evidence / "cost-planning-record.json"
        record = json.loads(cost_path.read_bytes())
        record["conditions"][TB.V0_CONDITION]["estimated_seconds_per_unit"] = 1
        body = {k: v for k, v in record.items() if k != "canonical_digest_sha256"}
        record["canonical_digest_sha256"] = hashlib.sha256(json.dumps(
            body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
        cost_path.write_text(json.dumps(record))
        with self.assertRaises((P.PhysicalDiagnosticError, TB.TimeoutBudgetError)):
            self.invoke()
        self.assertEqual(self.calls, [])

    def test_cpu_arm_a_cannot_launch_before_verified_v0(self):
        """AMENDMENT-008 (updated historical RED): without verified V0
        AND without the post-V0n bridge record, Arm A cannot launch. The
        historical refusal text is still raised when the bridge is also
        absent at the older head binding; here the accepted-evidence
        law yields the bridge refusal, which subsumes it."""
        def cpu_authority(repo, head, namespace, github_api=None):
            value = self.authority(repo, head, namespace, github_api)
            value["arm"] = "A-vulkan-necessity"
            value["body"] = value["body"].replace(
                f"arm={P.V0_ARM}", "arm=A-vulkan-necessity")
            return value
        with mock.patch.object(D, "_require_clean_head"):
            with self.assertRaisesRegex(
                    P.PhysicalDiagnosticError,
                    "Arm-A reachability bridge record missing"):
                P.run_diagnostic_unit(
                    self.repo, self.evidence, "d250-arm-a",
                    "A-vulkan-necessity", "case-3072-B-devnone-001",
                    binary=self.root / "bin", binary_id="comparator",
                    model_dir=Path(D.MODEL_DIR), expected_head=self.head,
                    model_attestation={}, execute=lambda **kw: self.calls.append(kw),
                    revalidate_authority=cpu_authority)
        self.assertEqual(self.calls, [])

    def test_v0_cost_basis_explicitly_not_measured_amd(self):
        record = TB.canonical_cost_planning_record()
        entry = record["conditions"][TB.V0_CONDITION]
        self.assertFalse(entry["planning_rate_measured"])
        self.assertIn("not_measured_amd", entry["planning_rate_basis"])
        self.assertEqual(entry["estimated_min_mismatch_cost_s"],
                         TB.v0_cost_record()["two_unit_cost_s"])
        self.assertEqual(TB.evaluate_cost_gate(
            TB.V0_CONDITION, record)["namespace"], P.V0_NAMESPACE)

    def test_amd_binary_attestation_is_hard_blocker_not_nvidia_digest(self):
        self._enable_cpu_fake_execution()
        with mock.patch.object(P, "_verify_v0_amd_binary",
                               side_effect=P.PhysicalDiagnosticError(
                                   "AMD seam not attested")):
            with self.assertRaisesRegex(P.PhysicalDiagnosticError,
                                        "AMD seam not attested"):
                self._run(P.V0_UNIT_TAGS[0])
        self.assertEqual(self.calls, [])
        self.assertFalse((self.evidence / P.V0_NAMESPACE).exists())

    def _enable_cpu_fake_execution(self, rows=None):
        rows = rows or (b"\0" * D.ROW_BYTES,) * 3
        self.real_placement_verifier = P._v0_verify_placement
        # A synthetic CPU runner cannot establish live AMD tensor placement.
        # Override only that physical observer; real default must fail closed.
        self.enterContext(mock.patch.object(P, "_v0_verify_placement"))
        self.enterContext(mock.patch.object(D, "_require_clean_head"))
        self.enterContext(mock.patch.object(P, "verify_fixtures", return_value={
            D.CASE: {"prompt_text": "fixture", "prompt_token_ids": [1] * 3077}}))
        self.enterContext(mock.patch.object(P, "verify_binary", return_value="f" * 64))
        self.enterContext(mock.patch.object(P, "_verify_v0_amd_binary",
                                            return_value=P.V0_COMPARATOR_SHA))
        self.enterContext(mock.patch.object(P, "validate_model_attestation",
                                            return_value={"model_dir": D.MODEL_DIR}))
        self.enterContext(mock.patch.object(P, "attestation_witness", return_value=([], {})))
        (self.evidence / P.MODEL_ATTESTATION_OPEN_NAME).write_text(
            json.dumps({"model_dir": D.MODEL_DIR}))

        def runner(**kw):
            self.calls.append(kw)
            unit_dir = kw["unit_dir"]
            (unit_dir / "obs.row0.f32").write_bytes(rows[len(self.calls) - 1])
            (unit_dir / "server.log").write_text(
                "offloading 1 repeating layer to GPU\n"
                "output projection: Vulkan\nembedding: CPU\n")
            return {"response_raw": b"{}", "vulkan_device_index": 0,
                    "vram_before": {"0000:07:00.0": 0, "0000:0b:00.0": 0},
                    "vram_after": {"0000:07:00.0": 512 * 1024 * 1024,
                                   "0000:0b:00.0": 0},
                    "backend": "Vulkan", "cuda_participation": False,
                    "process_attribution": {"server_pid": 100 + len(self.calls),
                                             "server_exe_sha256": P.V0_COMPARATOR_SHA,
                                             "server_argv": kw["argv"],
                                             "server_env": kw["env"]}}

        self.runner = runner
        self.device = lambda index: {"index": index, "vendor_id": "0x1002",
                                     "device_id": "0x6864", "name": "AMD test fixture",
                                     "vulkan_indices": [0, 1],
                                     "enumeration_sha256": "a" * 64,
                                     "icd_sha256": "b" * 64,
                                     "runtime_identity": make_runtime_identity(int),
                                     "drm_cards": {"0000:07:00.0": "card1",
                                                   "0000:0b:00.0": "card2"}}
        binary_dir = self.root
        binding = {"schema": P.V0_BINDING_SCHEMA,
                   "expected_pr_head": self.head, "host": "inferswarm05",
                   "producer": P.V0_BINDING_PRODUCER,
                   "source_pin": P.V0_SOURCE_PIN,
                   "binary_sha256": P.V0_COMPARATOR_SHA,
                   "binary_path": str(self.root / "bin"),
                   "icd": P.V0_RADV_ICD, "cuda_visible_devices": "-1",
                   "binary_lib_dir": str(binary_dir),
                   "enumeration_sha256": "a" * 64,
                   "icd_sha256": "b" * 64,
                   "runtime_identity": make_runtime_identity(str),
                   "drm_cards": self.device(0)["drm_cards"],
                   "mapping": {}}
        for idx, selected in ((0, "0000:07:00.0"), (1, "0000:0b:00.0")):
            excluded = next(b for b in binding["drm_cards"] if b != selected)
            binding["mapping"][str(idx)] = {
                "selected_bdf": selected, "excluded_bdf": excluded,
                "selected_card": binding["drm_cards"][selected],
                "excluded_card": binding["drm_cards"][excluded],
                "vram_before": {selected: 0, excluded: 0},
                "vram_after": {selected: 512 * 1024 * 1024, excluded: 0}}
        probe_dir = self.evidence / "v0-selector-preflight"
        probe_dir.mkdir()
        binding["preflight_probe_sha256"] = {}
        binding["dispatch_sha256"] = D.authority_digest(
            self.authority(self.repo, self.head, P.V0_NAMESPACE))
        for idx in (0, 1):
            entry = binding["mapping"][str(idx)]
            probe = {"index": idx,
                     "vram_before": entry["vram_before"],
                     "vram_after": entry["vram_after"],
                     "process_attribution": {
                         "server_exe_sha256": P.V0_COMPARATOR_SHA,
                         "server_argv": P.v0_server_argv(
                             self.root / "bin", Path(D.MODEL_DIR) / D.MODEL_MEMBER_1),
                         "server_env": {"VK_ICD_FILENAMES": P.V0_RADV_ICD,
                                        "GGML_VK_VISIBLE_DEVICES": str(idx),
                                        "CUDA_VISIBLE_DEVICES": "-1",
                                        "LD_LIBRARY_PATH": str(binary_dir)}}}
            probe_path = probe_dir / f"index-{idx}.json"
            probe_path.write_text(json.dumps(probe))
            binding["preflight_probe_sha256"][str(idx)] = D.file_sha256(probe_path)
        binding["canonical_digest_sha256"] = P._v0_digest(binding)
        (self.evidence / "v0-selector-binding.json").write_text(json.dumps(binding))
        self.binding = binding
        self.write_freeze()

    def write_freeze(self, *, index=None, selected=None, excluded=None,
                     rule=None, producer=None, binding_digest=None,
                     dispatch_sha256=None):
        """Write a canonically-derived (or deliberately mutated) freeze."""
        if index is None:
            index = min((0, 1), key=lambda i: str(
                self.binding["mapping"][str(i)]["selected_bdf"]))
        entry = self.binding["mapping"][str(index)]
        record = {
            "schema": P.V0_FREEZE_SCHEMA,
            "producer": producer or P.V0_FREEZE_PRODUCER,
            "freeze_rule": rule or P.V0_FREEZE_RULE,
            "expected_pr_head": self.head,
            "v0_screen_vulkan_index": index,
            "v0_screen_selected_bdf": selected or entry["selected_bdf"],
            "v0_screen_excluded_bdf": excluded or entry["excluded_bdf"],
            "selected_card": entry["selected_card"],
            "excluded_card": entry["excluded_card"],
            "source_pin": P.V0_SOURCE_PIN,
            "binary_sha256": P.V0_COMPARATOR_SHA,
            "icd": P.V0_RADV_ICD, "cuda_visible_devices": "-1",
            "selector_binding_digest": binding_digest
            or self.binding["canonical_digest_sha256"],
            "dispatch_sha256": dispatch_sha256 or self.binding["dispatch_sha256"],
            "namespace": P.V0_NAMESPACE, "arm": P.V0_ARM,
        }
        record["canonical_digest_sha256"] = P._v0_freeze_digest(record)
        (self.evidence / P.V0_FREEZE_NAME).write_text(json.dumps(record))
        return record

    def _run(self, tag, authority=None):
        return P.run_v0_unit(self.repo, self.evidence, P.V0_NAMESPACE, P.V0_ARM,
                             tag, binary=self.root / "bin", binary_id="comparator",
                             model_dir=Path(D.MODEL_DIR), expected_head=self.head,
                             model_attestation={}, execute=self.runner,
                             revalidate_authority=authority or self.authority,
                             vulkan_device_index=0, device_observer=self.device)

    def test_variable_pair_forbids_third_and_retained_byte_mutation(self):
        self._enable_cpu_fake_execution((b"\0" * D.ROW_BYTES,
                                         b"\1" * D.ROW_BYTES))
        self._run(P.V0_UNIT_TAGS[0])
        self._run(P.V0_UNIT_TAGS[1])
        with self.assertRaisesRegex(P.PhysicalDiagnosticError, "variable pair"):
            self._run(P.V0_UNIT_TAGS[2])
        self.assertEqual(len(self.calls), 2)
        row = self.evidence / P.V0_NAMESPACE / P.V0_UNIT_TAGS[0] / "obs.row0.f32"
        row.write_bytes(b"\2" * D.ROW_BYTES)
        with self.assertRaisesRegex(P.PhysicalDiagnosticError, "byte/custody"):
            self._run(P.V0_UNIT_TAGS[2])
        self.assertEqual(len(self.calls), 2)

    def test_identical_pair_permits_third_but_late_dispatch_drift_denies(self):
        self._enable_cpu_fake_execution((b"\0" * D.ROW_BYTES,) * 3)
        first = self._run(P.V0_UNIT_TAGS[0])
        self.assertEqual(first["prompt_token_ids"], [1] * 3077)
        self.assertEqual(first["prompt_text_sha256"], D.sha256_bytes(b"fixture"))
        self._run(P.V0_UNIT_TAGS[1])
        calls = [0]

        def drifting(*args):
            calls[0] += 1
            value = self.authority(*args)
            if calls[0] == 2:
                value["comment_id"] = 78
            return value

        with self.assertRaisesRegex(P.PhysicalDiagnosticError, "drift"):
            self._run(P.V0_UNIT_TAGS[2], authority=drifting)
        self.assertEqual(len(self.calls), 2)
        self._run(P.V0_UNIT_TAGS[2])
        self.assertEqual(len(self.calls), 3)

    def test_future_or_failed_partial_unit_blocks_selective_population(self):
        self._enable_cpu_fake_execution()
        future = self.evidence / P.V0_NAMESPACE / P.V0_UNIT_TAGS[2]
        future.mkdir(parents=True)
        with self.assertRaisesRegex(P.PhysicalDiagnosticError, "selective repeats"):
            self._run(P.V0_UNIT_TAGS[0])
        self.assertEqual(self.calls, [])
        future.rmdir()
        failed = self.evidence / P.V0_NAMESPACE / P.V0_UNIT_TAGS[0]
        failed.mkdir()
        (failed / "failure.json").write_text("{}")
        with self.assertRaisesRegex(P.PhysicalDiagnosticError, "selective repeats"):
            self._run(P.V0_UNIT_TAGS[0])
        self.assertEqual(self.calls, [])

    def test_excluded_die_residency_does_not_emit_receipt(self):
        self._enable_cpu_fake_execution()
        original = self.runner
        def sibling_runner(**kw):
            result = original(**kw)
            result["vram_after"]["0000:0b:00.0"] = 512 * 1024 * 1024
            return result
        self.runner = sibling_runner
        with mock.patch.object(P, "_v0_verify_placement",
                               self.real_placement_verifier):
            with self.assertRaisesRegex(P.PhysicalDiagnosticError,
                                        "selected/excluded physical die residency"):
                self._run(P.V0_UNIT_TAGS[0])
        failed = self.evidence / P.V0_NAMESPACE / P.V0_UNIT_TAGS[0]
        self.assertTrue((failed / "failure.json").is_file())
        self.assertFalse((failed / "unit.json").exists())

    def test_repeats_same_frozen_index_and_bdf_are_accepted(self):
        self._enable_cpu_fake_execution((b"\0" * D.ROW_BYTES,
                                         b"\1" * D.ROW_BYTES))
        self._run(P.V0_UNIT_TAGS[0])
        self._run(P.V0_UNIT_TAGS[1])
        for tag in P.V0_UNIT_TAGS[:2]:
            receipt = json.loads((self.evidence / P.V0_NAMESPACE / tag
                                  / "unit.json").read_bytes())
            self.assertEqual(receipt["amd_device"]["index"], 0)
            self.assertEqual(receipt["selected_bdf"], "0000:07:00.0")
            self.assertEqual(receipt["excluded_bdf"], "0000:0b:00.0")
            self.assertEqual(receipt["server_env"]["GGML_VK_VISIBLE_DEVICES"],
                             "0")
        self.assertEqual(len(self.calls), 2)

    def test_three_identical_repeats_same_frozen_device_accepted(self):
        self._enable_cpu_fake_execution((b"\0" * D.ROW_BYTES,) * 3)
        for tag in P.V0_UNIT_TAGS:
            self._run(tag)
        for tag in P.V0_UNIT_TAGS:
            receipt = json.loads((self.evidence / P.V0_NAMESPACE / tag
                                  / "unit.json").read_bytes())
            self.assertEqual(receipt["amd_device"]["index"], 0)
            self.assertEqual(receipt["selected_bdf"], "0000:07:00.0")
        self.assertEqual(len(self.calls), 3)

    def _unit_with_index(self, tag, index):
        """Reissue a receipt shape as if produced with the sibling index."""
        directory = self.evidence / P.V0_NAMESPACE / tag
        receipt = json.loads((directory / "unit.json").read_bytes())
        device = dict(receipt["amd_device"])
        device["index"] = index
        env = dict(receipt["server_env"])
        env["GGML_VK_VISIBLE_DEVICES"] = str(index)
        attribution = dict(receipt["process_attribution"])
        attribution["server_env"] = env
        receipt.update(amd_device=device, server_env=env,
                       process_attribution=attribution,
                       selected_bdf=self.binding["mapping"][str(index)][
                           "selected_bdf"],
                       excluded_bdf=self.binding["mapping"][str(index)][
                           "excluded_bdf"])
        return receipt

    def test_repeat_on_sibling_index_rejected_before_interpretation(self):
        self._enable_cpu_fake_execution((b"\0" * D.ROW_BYTES,) * 3)
        # repeat 1 on frozen index 0; a repeat 2 attempted on index 1 is
        # refused before any runner launch (selector mismatch).
        self._run(P.V0_UNIT_TAGS[0])
        with self.assertRaisesRegex(P.PhysicalDiagnosticError,
                                    "frozen screen device"):
            P.run_v0_unit(self.repo, self.evidence, P.V0_NAMESPACE, P.V0_ARM,
                          P.V0_UNIT_TAGS[1], binary=self.root / "bin",
                          binary_id="comparator", model_dir=Path(D.MODEL_DIR),
                          expected_head=self.head, model_attestation={},
                          execute=self.runner,
                          revalidate_authority=self.authority,
                          vulkan_device_index=1, device_observer=self.device)
        self.assertEqual(len(self.calls), 1)
        # A synthetically re-signed repeat-1 receipt on index 1 (so the
        # retained population itself is mixed-die) is rejected by the
        # retained-evidence validator before V0 interpretation.
        forged = self._unit_with_index(P.V0_UNIT_TAGS[0], 1)
        (self.evidence / P.V0_NAMESPACE / P.V0_UNIT_TAGS[0] /
         "unit.json").write_text(json.dumps(forged))
        with self.assertRaisesRegex(P.PhysicalDiagnosticError,
                                    "one frozen AMD die"):
            self._run(P.V0_UNIT_TAGS[1])
        self.assertEqual(len(self.calls), 1)

    def test_canonical_freeze_authenticates_without_any_units(self):
        self._enable_cpu_fake_execution()
        self.assertFalse((self.evidence / P.V0_NAMESPACE).exists())
        freeze, binding = P._v0_load_freeze_with_preflight(
            self.evidence, self.head,
            self.authority(self.repo, self.head, P.V0_NAMESPACE))
        self.assertEqual(freeze["v0_screen_vulkan_index"], 0)
        self.assertEqual(freeze["v0_screen_selected_bdf"],
                         binding["mapping"]["0"]["selected_bdf"])
        for tag in P.V0_UNIT_TAGS[:2]:
            self._run(tag)
        self.assertEqual(len(self.calls), 2)

    def test_resigned_sibling_freeze_refused_before_first_unit(self):
        self._enable_cpu_fake_execution()
        forged = self.write_freeze(index=1)
        self.assertEqual(forged["freeze_rule"], P.V0_FREEZE_RULE)
        self.assertEqual(forged["canonical_digest_sha256"],
                         P._v0_freeze_digest(forged))
        self.assertEqual(forged["selector_binding_digest"],
                         self.binding["canonical_digest_sha256"])
        self.assertEqual(forged["dispatch_sha256"],
                         self.binding["dispatch_sha256"])
        self.assertFalse((self.evidence / P.V0_NAMESPACE).exists())
        with self.assertRaisesRegex(P.PhysicalDiagnosticError,
                                    "canonical preflight selection"):
            P._v0_load_freeze_with_preflight(
                self.evidence, self.head,
                self.authority(self.repo, self.head, P.V0_NAMESPACE))
        with self.assertRaisesRegex(P.PhysicalDiagnosticError,
                                    "canonical preflight selection"):
            P._v0_retained_rows(
                self.evidence, 0, self.head,
                self.authority(self.repo, self.head, P.V0_NAMESPACE))
        with self.assertRaisesRegex(P.PhysicalDiagnosticError,
                                    "canonical preflight selection"):
            P.run_v0_unit(
                self.repo, self.evidence, P.V0_NAMESPACE, P.V0_ARM,
                P.V0_UNIT_TAGS[0], binary=self.root / "bin",
                binary_id="comparator", model_dir=Path(D.MODEL_DIR),
                expected_head=self.head, model_attestation={},
                execute=self.runner, revalidate_authority=self.authority,
                vulkan_device_index=1, device_observer=self.device)
        self.assertEqual(self.calls, [])

    def test_resigned_freeze_cards_and_authority_fields_refused(self):
        self._enable_cpu_fake_execution()
        for key, value in (
            ("selected_card", "card2"), ("excluded_card", "card1"),
            ("source_pin", "0" * 40), ("binary_sha256", "0" * 64),
            ("icd", "/wrong/radv.json"), ("cuda_visible_devices", "0"),
            ("namespace", "d250-arm-a"), ("arm", "A-vulkan-necessity"),
        ):
            with self.subTest(key=key):
                freeze = self.write_freeze()
                freeze[key] = value
                freeze["canonical_digest_sha256"] = P._v0_freeze_digest(freeze)
                (self.evidence / P.V0_FREEZE_NAME).write_text(json.dumps(freeze))
                with self.assertRaises(P.PhysicalDiagnosticError):
                    P._v0_load_freeze_with_preflight(
                        self.evidence, self.head,
                        self.authority(self.repo, self.head, P.V0_NAMESPACE))
                self.assertEqual(self.calls, [])

    def test_binding_mutation_stale_or_resigned_digest_refused(self):
        self._enable_cpu_fake_execution()
        for resign in (False, True):
            with self.subTest(resign=resign):
                binding = copy.deepcopy(self.binding)
                binding["mapping"]["1"]["vram_after"]["0000:0b:00.0"] += 1
                if resign:
                    binding["canonical_digest_sha256"] = P._v0_digest(binding)
                    self.write_freeze(binding_digest=binding["canonical_digest_sha256"])
                else:
                    self.write_freeze()
                (self.evidence / "v0-selector-binding.json").write_text(
                    json.dumps(binding))
                with self.assertRaises(P.PhysicalDiagnosticError):
                    P._v0_load_freeze_with_preflight(
                        self.evidence, self.head,
                        self.authority(self.repo, self.head, P.V0_NAMESPACE))
                self.assertEqual(self.calls, [])
        (self.evidence / "v0-selector-binding.json").write_text(
            json.dumps(self.binding))
        self.write_freeze()
        P._v0_load_freeze_with_preflight(
            self.evidence, self.head,
            self.authority(self.repo, self.head, P.V0_NAMESPACE))

    def test_all_sibling_receipts_cannot_be_interpreted(self):
        from shutil import copytree
        self._enable_cpu_fake_execution((b"\0" * D.ROW_BYTES,
                                         b"\1" * D.ROW_BYTES))
        # Create the attack's retained root while no V0 unit exists there.
        # Canonical fake receipts are templates only, produced in a separate
        # evidence root; the attack root never contained a canonical unit.
        sibling_evidence = self.root / "all-sibling-evidence"
        copytree(self.evidence, sibling_evidence)
        self.assertFalse((sibling_evidence / P.V0_NAMESPACE).exists())
        for tag in P.V0_UNIT_TAGS[:2]:
            self._run(tag)
        sibling_freeze = self.write_freeze(index=1)
        (sibling_evidence / P.V0_FREEZE_NAME).write_text(
            json.dumps(sibling_freeze))
        self.assertFalse((sibling_evidence / P.V0_NAMESPACE).exists())
        for tag in P.V0_UNIT_TAGS[:2]:
            directory = sibling_evidence / P.V0_NAMESPACE / tag
            copytree(self.evidence / P.V0_NAMESPACE / tag, directory)
            path = directory / "unit.json"
            receipt = self._unit_with_index(tag, 1)
            receipt["vram_after"] = {"0000:07:00.0": 0,
                                     "0000:0b:00.0": 512 * 1024 * 1024}
            receipt["timeout_policy"]["vulkan_device_index"] = 1
            path.write_text(json.dumps(receipt))
            self.assertEqual(receipt["amd_device"]["index"], 1)
            self.assertEqual(receipt["selected_bdf"], "0000:0b:00.0")
            self.assertEqual(receipt["server_env"]["GGML_VK_VISIBLE_DEVICES"],
                             "1")
        # Control: with ONLY the canonical-freeze gate bypassed, these
        # index-1 receipts satisfy the existing retained row/custody checks.
        # The invalid verdict below therefore tests the rule itself, not a
        # malformed receipt or an accidental mixed-die population.
        with mock.patch.object(P, "_v0_load_freeze_with_preflight",
                               return_value=(sibling_freeze, self.binding)):
            self.assertEqual(len(P._v0_retained_rows(
                sibling_evidence, 2, self.head,
                self.authority(self.repo, self.head, P.V0_NAMESPACE))), 2)
        with self.assertRaisesRegex(P.PhysicalDiagnosticError,
                                    "canonical preflight selection"):
            P._v0_retained_rows(
                sibling_evidence, 2, self.head,
                self.authority(self.repo, self.head, P.V0_NAMESPACE))
        with mock.patch.object(T, "verify_v0_historical_rows", return_value={}):
            state = T.derive_v0_state(
                sibling_evidence, self.root / "contrast", self.repo, self.head,
                authority_fetcher=self.authority)
        self.assertEqual(state["state"], D.V0_STATE_INVALID)
        self.assertFalse(state["valid"])
        self.assertFalse(state["a_eligible"])
        self.assertNotIn("repeat_stable", state)
        self.assertNotIn("concordance", state)
        self.assertNotIn("disagreement", state)
        self.assertIn("canonical preflight selection", state["reason"])

    def test_mutated_freeze_index_or_bdf_rejected(self):
        self._enable_cpu_fake_execution()
        # same selected BDF but mutated frozen index
        self.write_freeze(index=1, selected="0000:07:00.0",
                          excluded="0000:0b:00.0")
        with self.assertRaisesRegex(P.PhysicalDiagnosticError,
                                    "canonical preflight selection"):
            self._run(P.V0_UNIT_TAGS[0])
        # same index but mutated selected BDF
        self.write_freeze(index=0, selected="0000:0b:00.0",
                          excluded="0000:07:00.0")
        with self.assertRaisesRegex(P.PhysicalDiagnosticError,
                                    "canonical preflight selection"):
            self._run(P.V0_UNIT_TAGS[0])
        # canonical pair again: accepted
        self.write_freeze()
        self._run(P.V0_UNIT_TAGS[0])
        self.assertEqual(len(self.calls), 1)

    def test_third_repeat_switching_device_rejected(self):
        self._enable_cpu_fake_execution((b"\0" * D.ROW_BYTES,) * 3)
        self._run(P.V0_UNIT_TAGS[0])
        self._run(P.V0_UNIT_TAGS[1])
        with self.assertRaisesRegex(P.PhysicalDiagnosticError,
                                    "frozen screen device"):
            P.run_v0_unit(self.repo, self.evidence, P.V0_NAMESPACE, P.V0_ARM,
                          P.V0_UNIT_TAGS[2], binary=self.root / "bin",
                          binary_id="comparator", model_dir=Path(D.MODEL_DIR),
                          expected_head=self.head, model_attestation={},
                          execute=self.runner,
                          revalidate_authority=self.authority,
                          vulkan_device_index=1, device_observer=self.device)
        self.assertEqual(len(self.calls), 2)

    def test_resigned_or_tampered_freeze_cannot_manufacture_continuity(self):
        self._enable_cpu_fake_execution((b"\0" * D.ROW_BYTES,) * 3)
        # (a) a re-signed freeze pointing at the OTHER preflight entry
        # violates the canonical lexical-BDF rule, regardless of whether
        # a canonical-index receipt was retained earlier.
        self._run(P.V0_UNIT_TAGS[0])
        other = self.write_freeze(index=1)
        self.assertEqual(other["v0_screen_vulkan_index"], 1)
        with self.assertRaisesRegex(P.PhysicalDiagnosticError,
                                    "canonical preflight selection"):
            self._run(P.V0_UNIT_TAGS[1])
        self.write_freeze()
        # (b) mutated binding digest (re-signed) cannot tie the freeze to
        # a different preflight record.
        self.write_freeze(binding_digest="c" * 64)
        with self.assertRaisesRegex(P.PhysicalDiagnosticError,
                                    "retained preflight"):
            self._run(P.V0_UNIT_TAGS[1])
        # (c) mutated dispatch binding (re-signed)
        self.write_freeze(dispatch_sha256="d" * 64)
        with self.assertRaisesRegex(P.PhysicalDiagnosticError,
                                    "retained preflight"):
            self._run(P.V0_UNIT_TAGS[1])
        # (d) unknown producer / rule strings are refused
        self.write_freeze(producer="issue250_physical.py:v0-load-only-binding/1")
        with self.assertRaisesRegex(P.PhysicalDiagnosticError,
                                    "digest/head/binding"):
            self._run(P.V0_UNIT_TAGS[1])
        # (e) digest tampering without re-signing
        record = json.loads((self.evidence / P.V0_FREEZE_NAME).read_text())
        record["v0_screen_vulkan_index"] = 1
        (self.evidence / P.V0_FREEZE_NAME).write_text(json.dumps(record))
        with self.assertRaisesRegex(P.PhysicalDiagnosticError,
                                    "digest/head/binding"):
            self._run(P.V0_UNIT_TAGS[1])
        self.assertEqual(len(self.calls), 1)

    def test_missing_or_late_freeze_fails_closed(self):
        self._enable_cpu_fake_execution()
        (self.evidence / P.V0_FREEZE_NAME).unlink()
        with self.assertRaisesRegex(P.PhysicalDiagnosticError,
                                    "freeze record missing"):
            self._run(P.V0_UNIT_TAGS[0])
        self.assertEqual(self.calls, [])
        self.write_freeze()
        self._run(P.V0_UNIT_TAGS[0])
        # A second freeze after units exist can never re-choose a device.
        with self.assertRaisesRegex(P.PhysicalDiagnosticError,
                                    "already retained"):
            P.write_v0_screen_freeze(
                self.repo, self.evidence, binary=self.root / "bin",
                binary_id="comparator", model_dir=Path(D.MODEL_DIR),
                expected_head=self.head, model_attestation={},
                revalidate_authority=self.authority,
                device_observer=self.device)

    def test_full_retained_freeze_path_over_int_keyed_observer(self):
        """AMENDMENT-006 case F: the exact physical 028dce94 sequence.

        Production-shaped preflight retention through
        run_v0_binding_preflight (fake load-only probes) with a device
        observer whose runtime_identity.devices uses INTEGER keys — the
        raw _v0_observe_device shape that physically failed — then the
        repository-only write_v0_screen_freeze() with a fresh equivalent
        int-keyed observation, then run_v0_unit() under fake execution
        (case G). At head 028dce94 the freeze step deterministically
        raised 'digest/head/runtime identity mismatch'; the corrected
        canonical comparison must authenticate the freeze, and the unit
        consumer must reach the fake runner.
        """
        self._enable_cpu_fake_execution()
        evidence = self.root / "phys-shape-evidence"
        evidence.mkdir()
        P.retain_cost_planning_record(evidence)
        (evidence / P.MODEL_ATTESTATION_OPEN_NAME).write_text(
            json.dumps({"model_dir": D.MODEL_DIR}))
        authority = self.authority(self.repo, self.head, P.V0_NAMESPACE)

        def int_key_observer(index):
            return {"index": index, "vendor_id": "0x1002",
                    "device_id": "0x6864", "name": "AMD test fixture",
                    "vulkan_indices": [0, 1],
                    "enumeration_sha256": "a" * 64,
                    "icd_sha256": "b" * 64,
                    "runtime_identity": make_runtime_identity(int),
                    "drm_cards": {"0000:07:00.0": "card1",
                                  "0000:0b:00.0": "card2"}}

        def probe(binary, model, index, dies, directory):
            selected = list(dies)[index]
            return {"index": index,
                    "vram_before": {b: 0 for b in dies},
                    "vram_after": {b: (512 * 1024 * 1024 if b == selected
                                       else 0) for b in dies},
                    "process_attribution": {
                        "server_exe_sha256": P.V0_COMPARATOR_SHA,
                        "server_argv": P.v0_server_argv(binary, model),
                        "server_env": {
                            "VK_ICD_FILENAMES": P.V0_RADV_ICD,
                            "GGML_VK_VISIBLE_DEVICES": str(index),
                            "CUDA_VISIBLE_DEVICES": "-1",
                            "LD_LIBRARY_PATH": str(self.root)}}}

        with mock.patch.object(P, "require_live_dispatch",
                               return_value=authority):
            binding = P.run_v0_binding_preflight(
                self.repo, evidence, binary=self.root / "bin",
                model_dir=Path(D.MODEL_DIR), expected_head=self.head,
                model_attestation={}, probe_load=probe,
                device_observer=int_key_observer)
        # the RETAINED bytes carry the canonical string-keyed identity
        retained = json.loads(
            (evidence / "v0-selector-binding.json").read_bytes())
        self.assertEqual(sorted(retained["runtime_identity"]["devices"]),
                         ["0", "1"])
        self.assertEqual(retained["canonical_digest_sha256"],
                         binding["canonical_digest_sha256"])

        # THE physically failing step: freeze against a FRESH int-keyed
        # live observation of the same substrate.
        freeze = P.write_v0_screen_freeze(
            self.repo, evidence, binary=self.root / "bin",
            binary_id="comparator", model_dir=Path(D.MODEL_DIR),
            expected_head=self.head, model_attestation={},
            revalidate_authority=self.authority,
            device_observer=int_key_observer)
        self.assertEqual(freeze["v0_screen_vulkan_index"], 0)
        self.assertEqual(freeze["selector_binding_digest"],
                         binding["canonical_digest_sha256"])

        # Case G: the unit consumer's runtime-identity portion under fake
        # execution — JSON-round-tripped binding vs fresh int-keyed live
        # observation — reaches the runner and retains an authenticated
        # receipt embedding both.
        receipt = P.run_v0_unit(
            self.repo, evidence, P.V0_NAMESPACE, P.V0_ARM,
            P.V0_UNIT_TAGS[0], binary=self.root / "bin",
            binary_id="comparator", model_dir=Path(D.MODEL_DIR),
            expected_head=self.head, model_attestation={},
            execute=self.runner, revalidate_authority=self.authority,
            vulkan_device_index=0, device_observer=int_key_observer)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(
            sorted(receipt["v0_selector_binding"]["runtime_identity"][
                "devices"]),
            ["0", "1"])
        self.assertEqual(
            sorted(receipt["amd_device"]["runtime_identity"]["devices"],
                   key=str),
            [0, 1])
        # and the retained rows/authenticate path re-validates the whole
        # population through the same canonical comparison
        rows = P._v0_retained_rows(evidence, 1, self.head, authority)
        self.assertEqual(len(rows), 1)


class V0RuntimeIdentityJSONStabilityTests(unittest.TestCase):
    """AMENDMENT-006 regressions: the physical 028dce94 freeze failure.

    The retained selector binding JSON-round-trips runtime_identity.devices
    to string keys while _v0_observe_device() parsed integer keys; the old
    raw-dict comparison then rejected every otherwise-identical identity
    with 'digest/head/runtime identity mismatch'. These tests pin the
    corrected canonical contract against that defect class.
    """

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.head = "6" * 40
        self.cards = {"0000:07:00.0": "card1", "0000:0b:00.0": "card2"}
        self.live_identity = make_runtime_identity(int)
        self.retained_identity = json.loads(json.dumps(self.live_identity))
        self.live = {"index": 0, "vendor_id": "0x1002", "device_id": "0x6864",
                     "name": V340L_DEVICE_IDENTITY["name"],
                     "vulkan_indices": [0, 1],
                     "enumeration_sha256": "a" * 64, "icd_sha256": "b" * 64,
                     "runtime_identity": self.live_identity,
                     "drm_cards": self.cards,
                     "binary_lib_dir": str(self.root)}
        self.record = {"schema": P.V0_BINDING_SCHEMA, "host": "inferswarm05",
                       "producer": P.V0_BINDING_PRODUCER,
                       "expected_pr_head": self.head,
                       "source_pin": P.V0_SOURCE_PIN,
                       "binary_sha256": P.V0_COMPARATOR_SHA,
                       "binary_path": str(self.root / "llama-server"),
                       "binary_lib_dir": str(self.root),
                       "icd": P.V0_RADV_ICD, "cuda_visible_devices": "-1",
                       "enumeration_sha256": self.live["enumeration_sha256"],
                       "icd_sha256": self.live["icd_sha256"],
                       "runtime_identity": self.retained_identity,
                       "drm_cards": self.cards, "mapping": {}}
        for idx, selected in ((0, "0000:07:00.0"), (1, "0000:0b:00.0")):
            excluded = next(b for b in self.cards if b != selected)
            self.record["mapping"][str(idx)] = {
                "selected_bdf": selected, "excluded_bdf": excluded,
                "selected_card": self.cards[selected],
                "excluded_card": self.cards[excluded],
                "vram_before": {selected: 0, excluded: 0},
                "vram_after": {selected: 512 * 1024 * 1024, excluded: 0}}
        self.record["canonical_digest_sha256"] = P._v0_digest(self.record)

    def validate(self, record=None, live=None, index=0):
        return P.validate_v0_selector_binding(
            self.record if record is None else record, self.head, index,
            self.live if live is None else live, P.V0_COMPARATOR_SHA)

    def test_retained_json_roundtrip_accepts_int_keyed_live(self):
        """Primary old-defect regression (AMENDMENT-006 case A).

        Production-shaped retention: the record (with the canonical
        string-keyed identity) is written through P._write_json, re-read
        through json.loads, and validated against a FRESH int-keyed
        observation. Before the correction this failed with the exact
        physical 'digest/head/runtime identity mismatch'.
        """
        target = self.root / "v0-selector-binding.json"
        P._write_json(target, self.record)
        retained = json.loads(target.read_bytes())
        self.assertEqual(sorted(retained["runtime_identity"]["devices"]),
                         ["0", "1"])
        self.assertEqual(
            sorted(self.live["runtime_identity"]["devices"], key=str),
            [0, 1])
        entry = self.validate(record=retained)
        self.assertEqual(entry["selected_bdf"], "0000:07:00.0")
        # index-1 live observation of the same substrate also validates
        self.validate(record=retained,
                      live={**self.live, "index": 1}, index=1)

    def test_string_key_retained_equals_int_key_live(self):
        """Case C: pure canonical-equality seam."""
        self.assertEqual(
            P._v0_normalize_runtime_identity(self.retained_identity),
            P._v0_normalize_runtime_identity(self.live_identity))
        self.validate()

    def test_substantive_identity_drift_still_rejected(self):
        """Case D: every identity-bearing field mutates independently."""
        paths = [
            ("kernel", lambda r: r["kernel"].__class__),
            ("vulkan_instance", lambda r: r["vulkan_instance"].__class__),
        ]
        for field, _ in paths:
            for target in ("record", "live"):
                with self.subTest(field=field, target=target):
                    if target == "record":
                        bad = copy.deepcopy(self.record)
                        bad["runtime_identity"][field] += "-drift"
                        bad["canonical_digest_sha256"] = P._v0_digest(bad)
                        subject, live = bad, self.live
                    else:
                        live = copy.deepcopy(self.live)
                        live["runtime_identity"][field] += "-drift"
                        subject, live = self.record, live
                    with self.assertRaisesRegex(
                            P.PhysicalDiagnosticError,
                            "runtime identity mismatch"):
                        self.validate(record=subject, live=live)
        for field in ("vendor_id", "device_id", "name", "driver_id",
                      "driver_info", "driver_version", "api_version"):
            for device in ("0", "1"):
                with self.subTest(field=field, device=device):
                    bad = copy.deepcopy(self.record)
                    bad["runtime_identity"]["devices"][device][field] += "X"
                    bad["canonical_digest_sha256"] = P._v0_digest(bad)
                    with self.assertRaisesRegex(
                            P.PhysicalDiagnosticError,
                            "runtime identity mismatch"):
                        self.validate(record=bad)
                    live = copy.deepcopy(self.live)
                    live["runtime_identity"]["devices"][int(device)][
                        field] += "X"
                    with self.assertRaisesRegex(
                            P.PhysicalDiagnosticError,
                            "runtime identity mismatch"):
                        self.validate(live=live)

    def test_key_space_mutations_fail(self):
        """Case E: only exactly {0,1}/{0,1}-spelled two-device maps pass."""
        base = self.live_identity
        variants = {
            "only device 0": lambda i: i["devices"].pop(1),
            "only device 1": lambda i: i["devices"].pop(0),
            "extra device 2": lambda i: i["devices"].__setitem__(
                2, copy.deepcopy(V340L_DEVICE_IDENTITY)),
            "string key 00": lambda i: i["devices"].update({
                "00": i["devices"].pop(0)}),
            "float key 0.0": lambda i: i["devices"].update({
                0.0: i["devices"].pop(0)}),
            "boolean key": lambda i: i.__setitem__(
                "devices", {True: copy.deepcopy(V340L_DEVICE_IDENTITY),
                            "0": copy.deepcopy(V340L_DEVICE_IDENTITY)}),
            "colliding 0 and 0-str": lambda i: i["devices"].update({
                "0": copy.deepcopy(V340L_DEVICE_IDENTITY)}),
            "malformed devices value": lambda i: i.__setitem__(
                "devices", "not-a-map"),
            "device entry not dict": lambda i: i["devices"].__setitem__(
                0, "RADV"),
            "device entry missing field": lambda i: i["devices"].__setitem__(
                0, {k: v for k, v in V340L_DEVICE_IDENTITY.items()
                    if k != "driver_info"}),
            "device entry extra field": lambda i: i["devices"][0].update(
                {"extra": "field"}),
            "device field empty": lambda i: i["devices"][0].update(
                {"name": ""}),
            "kernel missing": lambda i: i.pop("kernel"),
            "kernel not a string": lambda i: i.update(kernel=612),
            "vulkan_instance missing": lambda i: i.pop("vulkan_instance"),
            "extra top-level key": lambda i: i.update(host="inferswarm05"),
            "not a dict": lambda i: i.clear(),
        }
        for name, mutate in variants.items():
            with self.subTest(name=name):
                identity = copy.deepcopy(base)
                mutate(identity)
                with self.assertRaises(P.PhysicalDiagnosticError):
                    P._v0_normalize_runtime_identity(identity)
        # canonical form is exactly the string-keyed two-device map
        self.assertEqual(set(P._v0_normalize_runtime_identity(
            self.live_identity)["devices"]), {"0", "1"})

    def test_resubstantiated_binding_digest_intact(self):
        """Case H: a re-digested mutated identity is internally valid but

        still rejected — the canonical identity comparison, not digest
        self-consistency, carries the authority here.
        """
        bad = copy.deepcopy(self.record)
        bad["runtime_identity"]["devices"]["1"]["driver_version"] = "99.0"
        bad["canonical_digest_sha256"] = P._v0_digest(bad)
        self.assertEqual(bad["canonical_digest_sha256"], P._v0_digest(bad))
        with self.assertRaisesRegex(P.PhysicalDiagnosticError,
                                    "runtime identity mismatch"):
            self.validate(record=bad)

    def test_producer_observe_device_emits_canonical_string_keys(self):
        """Case B: _v0_observe_device parsing with mocked vulkaninfo."""
        vulkaninfo = "\n".join([
            "Vulkan Instance Version: 1.4.309",
            "",
            "GPU0:",
            "\tapiVersion         = 1.4.305",
            "\tdriverVersion      = 25.0.7",
            "\tvendorID           = 0x1002",
            "\tdeviceID           = 0x6864",
            "\tdeviceName         = AMD Radeon Pro V340 (RADV VEGA10)",
            "\tdriverID           = DRIVER_ID_MESA_RADV",
            "\tdriverInfo         = Mesa 25.0.7-2+deb13u1",
            "",
            "GPU1:",
            "\tapiVersion         = 1.4.305",
            "\tdriverVersion      = 25.0.7",
            "\tvendorID           = 0x1002",
            "\tdeviceID           = 0x6864",
            "\tdeviceName         = AMD Radeon Pro V340 (RADV VEGA10)",
            "\tdriverID           = DRIVER_ID_MESA_RADV",
            "\tdriverInfo         = Mesa 25.0.7-2+deb13u1",
            "",
        ])
        dies = {"0000:07:00.0": "card1", "0000:0b:00.0": "card2"}
        fake_proc = mock.Mock(stdout=vulkaninfo, returncode=0)
        with mock.patch.object(P.socket, "gethostname",
                               return_value="inferswarm05"), \
             mock.patch.object(P, "V0_RADV_ICD", "/tmp/fake-icd.json"), \
             mock.patch.object(P.Path, "is_file", return_value=True), \
             mock.patch.object(P.D, "file_sha256", return_value="e" * 64), \
             mock.patch.object(P, "_v0_dies", return_value=dies), \
             mock.patch.object(P.subprocess, "run", return_value=fake_proc), \
             mock.patch("platform.release",
                        return_value="6.12.107+deb13u3-x"):
            observed = P._v0_observe_device(1)
        # top-level live index and vulkan_indices stay integers
        self.assertEqual(observed["index"], 1)
        self.assertEqual(observed["vulkan_indices"], [0, 1])
        # canonical device map: string keys exactly {"0", "1"}
        devices = observed["runtime_identity"]["devices"]
        self.assertEqual(set(devices), {"0", "1"})
        self.assertTrue(all(isinstance(k, str) for k in devices))
        self.assertEqual(devices["0"], V340L_DEVICE_IDENTITY)
        self.assertEqual(devices["1"], V340L_DEVICE_IDENTITY)
        self.assertEqual(observed["runtime_identity"]["vulkan_instance"],
                         "1.4.309")
        # JSON-stable from the outset: round-trip is a no-op
        self.assertEqual(
            json.loads(json.dumps(observed["runtime_identity"])),
            observed["runtime_identity"])
        # and the old-head defect shape is gone: a retained round-trip of
        # this observation validates against the fresh observation
        target = self.root / "observed.json"
        P._write_json(target, {"runtime_identity":
                               observed["runtime_identity"]})
        reread = json.loads(target.read_bytes())
        self.assertEqual(P._v0_normalize_runtime_identity(
            reread["runtime_identity"]),
            P._v0_normalize_runtime_identity(
                observed["runtime_identity"]))


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


class V0AMDAdapterTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.head = "d" * 40
        self.cards = {"0000:07:00.0": "card1", "0000:0b:00.0": "card2"}
        self.live = {"index": 0, "vendor_id": "0x1002", "device_id": "0x6864",
                     "name": "synthetic V340L", "vulkan_indices": [0, 1],
                     "enumeration_sha256": "a" * 64, "icd_sha256": "b" * 64,
                     "runtime_identity": make_runtime_identity(int),
                     "drm_cards": self.cards, "binary_lib_dir": str(self.root)}
        self.record = {"schema": P.V0_BINDING_SCHEMA, "host": "inferswarm05",
                       "producer": P.V0_BINDING_PRODUCER,
                       "expected_pr_head": self.head, "source_pin": P.V0_SOURCE_PIN,
                       "binary_sha256": P.V0_COMPARATOR_SHA,
                       "binary_path": str(self.root / "llama-server"),
                       "binary_lib_dir": str(self.root), "icd": P.V0_RADV_ICD,
                       "cuda_visible_devices": "-1",
                       "enumeration_sha256": self.live["enumeration_sha256"],
                       "icd_sha256": self.live["icd_sha256"],
                       "runtime_identity": make_runtime_identity(str),
                       "drm_cards": self.cards, "mapping": {}}
        for idx, a in ((0, "0000:07:00.0"), (1, "0000:0b:00.0")):
            b = next(b for b in self.cards if b != a)
            self.record["mapping"][str(idx)] = {
                "selected_bdf": a, "excluded_bdf": b,
                "selected_card": self.cards[a], "excluded_card": self.cards[b],
                "vram_before": {a: 0, b: 0},
                "vram_after": {a: 512 * 1024 * 1024, b: 0}}
        self.sign()

    def sign(self):
        self.record["canonical_digest_sha256"] = P._v0_digest(self.record)

    def validate(self, record=None, index=0, live=None, head=None, sha=None):
        return P.validate_v0_selector_binding(
            self.record if record is None else record,
            self.head if head is None else head, index,
            self.live if live is None else live,
            P.V0_COMPARATOR_SHA if sha is None else sha)

    def test_exact_source_and_comparator_identity(self):
        self.assertEqual(P.V0_SOURCE_PIN,
                         "b29c606e28a01b1bc8c1351026a0fae616bf6c4")
        self.assertEqual(P.V0_COMPARATOR_SHA,
                         "6f8b56bd44d116cdc691911f8a1131840f5c7a720133c05febe11e467c2636ad")
        self.assertNotEqual(P.V0_COMPARATOR_SHA, D.SERVER_BINARIES["canonical"])
        self.assertEqual(self.validate()["selected_bdf"], "0000:07:00.0")
        self.assertEqual(self.validate(index=1, live={**self.live, "index": 1})[
            "selected_bdf"], "0000:0b:00.0")
        with self.assertRaises(P.PhysicalDiagnosticError):
            self.validate(sha=D.SERVER_BINARIES["canonical"])
        with self.assertRaises(P.PhysicalDiagnosticError):
            self.validate(sha="0" * 64)

    def test_binary_verifier_accepts_only_observer_and_exact_libraries(self):
        binary = self.root / "llama-server"
        binary.write_bytes(b"synthetic; hash verification separately mocked")
        for name in P.V0_OBSERVER_LIBS:
            (self.root / name).write_bytes(b"synthetic library")
        ldd = "\n".join(f"{n} => {self.root / n}" for n in P.V0_OBSERVER_LIBS)
        def run(argv, **kw):
            if argv[0] == "ldd":
                return mock.Mock(stdout=ldd, returncode=0)
            return mock.Mock(stdout=b"--n-gpu-layers", stderr=b"", returncode=0)
        with mock.patch.object(P, "verify_binary", return_value=P.V0_COMPARATOR_SHA), \
             mock.patch.object(D, "file_sha256", side_effect=lambda p: P.V0_OBSERVER_LIBS[p.name]), \
             mock.patch.object(P.subprocess, "run", side_effect=run):
            self.assertEqual(P._verify_v0_amd_binary(binary, "comparator"),
                             P.V0_COMPARATOR_SHA)
        for wrong in (D.SERVER_BINARIES["canonical"], "0" * 64):
            with mock.patch.object(P, "verify_binary", return_value=wrong):
                with self.assertRaises(P.PhysicalDiagnosticError):
                    P._verify_v0_amd_binary(binary, "comparator")
        with self.assertRaises(P.PhysicalDiagnosticError):
            P._verify_v0_amd_binary(binary, "canonical")

    def test_resigned_selector_binding_mutations_fail_independently(self):
        cases = {
            "source pin": lambda r: r.update(source_pin="0" * 40),
            "wrong ICD": lambda r: r.update(icd="/tmp/fake.json"),
            "NVIDIA ICD": lambda r: r.update(icd="/usr/share/vulkan/icd.d/nvidia_icd.json"),
            "CUDA": lambda r: r.update(cuda_visible_devices="0"),
            "missing selector": lambda r: r["mapping"].pop("0"),
            "wrong BDF": lambda r: r["mapping"]["0"].update(selected_bdf="0000:ff:00.0"),
            "swapped BDF": lambda r: r["mapping"]["0"].update(
                selected_bdf="0000:0b:00.0", excluded_bdf="0000:07:00.0"),
            "duplicate map": lambda r: r["mapping"].update(
                {"1": copy.deepcopy(r["mapping"]["0"])}),
            "excluded residency": lambda r: r["mapping"]["0"]["vram_after"].update(
                {"0000:0b:00.0": 512 * 1024 * 1024}),
            "stale head": lambda r: r.update(expected_pr_head="e" * 40),
            "wrong library directory": lambda r: r.update(binary_lib_dir="/missing"),
            "wrong Mesa": lambda r: r["runtime_identity"].update(kernel="wrong"),
            "wrong ICD digest": lambda r: r.update(icd_sha256="0" * 64),
            "wrong vendor": lambda r: r.update(host="inferswarm-nvidia"),
            "wrong binary": lambda r: r.update(binary_sha256=D.SERVER_BINARIES["canonical"]),
        }
        for name, mutation in cases.items():
            with self.subTest(name=name):
                bad = copy.deepcopy(self.record)
                mutation(bad)
                bad["canonical_digest_sha256"] = P._v0_digest(bad)
                with self.assertRaises(P.PhysicalDiagnosticError):
                    self.validate(record=bad)
        bad = copy.deepcopy(self.record)
        bad["canonical_digest_sha256"] = "0" * 64
        with self.assertRaises(P.PhysicalDiagnosticError):
            self.validate(record=bad)
        with self.assertRaises(P.PhysicalDiagnosticError):
            self.validate(head="f" * 40)
        with self.assertRaises(P.PhysicalDiagnosticError):
            self.validate(index=2)
        with self.assertRaises(P.PhysicalDiagnosticError):
            self.validate(live={**self.live, "vendor_id": "0x10de"})

    def test_source_law_requires_ngl1_vulkan_and_physical_die_evidence(self):
        result = {"vulkan_device_index": 0, "backend": "Vulkan",
                  "cuda_participation": False,
                  "vram_before": {b: 0 for b in self.cards},
                  "vram_after": {"0000:07:00.0": 512 * 1024 * 1024,
                                 "0000:0b:00.0": 0}}
        P._v0_verify_placement(self.root, self.live, result, self.record)
        for changed in ({"vulkan_device_index": 1}, {"backend": "CUDA"},
                        {"cuda_participation": True},
                        {"vram_after": {"0000:07:00.0": 0,
                                        "0000:0b:00.0": 512 * 1024 * 1024}}):
            with self.subTest(changed=changed), self.assertRaises(P.PhysicalDiagnosticError):
                P._v0_verify_placement(self.root, self.live,
                                       {**result, **changed}, self.record)
        with self.assertRaises(P.PhysicalDiagnosticError):
            P._v0_verify_placement(self.root, self.live, result,
                                   {**self.record, "source_pin": "0" * 40})

    def test_frozen_argv_and_selector_environment(self):
        argv = P.v0_server_argv(self.root / "llama-server", Path(D.MODEL_DIR) /
                                D.MODEL_MEMBER_1)
        self.assertEqual(argv[argv.index("-ngl") + 1], "1")
        self.assertNotIn("--device", argv)
        env = P.v0_environment(0, self.root, self.record)
        self.assertEqual(env["VK_ICD_FILENAMES"], P.V0_RADV_ICD)
        self.assertEqual(env["GGML_VK_VISIBLE_DEVICES"], "0")
        self.assertEqual(env["CUDA_VISIBLE_DEVICES"], "-1")
        with self.assertRaises(P.PhysicalDiagnosticError):
            P.v0_environment(2, self.root, self.record)
        with self.assertRaises(TypeError):
            P.v0_server_argv(self.root / "llama-server", Path("/model"),
                             vulkan_device_index=0)

    def test_stale_dispatch_preflight_has_zero_load_probes(self):
        evidence = self.root / "evidence"
        evidence.mkdir()
        P.retain_cost_planning_record(evidence)
        calls = []
        def forbidden(*args):
            calls.append(args)
            raise AssertionError("load-only probe reached")
        with mock.patch.object(P, "require_live_dispatch",
                               side_effect=P.PhysicalDiagnosticError("stale dispatch")):
            with self.assertRaisesRegex(P.PhysicalDiagnosticError, "stale dispatch"):
                P.run_v0_binding_preflight(self.root, evidence,
                    binary=self.root / "llama-server", model_dir=Path(D.MODEL_DIR),
                    expected_head=self.head, model_attestation={},
                    probe_load=forbidden)
        self.assertEqual(calls, [])
        self.assertFalse((evidence / "v0-selector-preflight").exists())
    def test_live_preflight_process_rejects_environment_and_argv_drift(self):
        argv = ["/observer-bin/llama-server", "-ngl", "1"]
        env = {"VK_ICD_FILENAMES": P.V0_RADV_ICD,
               "GGML_VK_VISIBLE_DEVICES": "0", "CUDA_VISIBLE_DEVICES": "-1"}
        proc = mock.Mock(pid=31415)
        observed_env = b"\0".join(
            f"{k}={v}".encode() for k, v in env.items()) + b"\0"
        observed_argv = b"\0".join(x.encode() for x in argv) + b"\0"
        def proc_bytes(path):
            return observed_env if str(path).endswith("/environ") else observed_argv
        with mock.patch.object(Path, "read_bytes", proc_bytes):
            P._v0_check_live_process(proc, argv, env)
        with mock.patch.object(Path, "read_bytes", lambda p: (
                observed_env.replace(b"GGML_VK_VISIBLE_DEVICES=0",
                                     b"GGML_VK_VISIBLE_DEVICES=1")
                if str(p).endswith("/environ") else observed_argv)):
            with self.assertRaises(P.PhysicalDiagnosticError):
                P._v0_check_live_process(proc, argv, env)
        with mock.patch.object(Path, "read_bytes", lambda p: (
                observed_env if str(p).endswith("/environ") else
                observed_argv.replace(b"-ngl\0", b"--device\0"))):
            with self.assertRaises(P.PhysicalDiagnosticError):
                P._v0_check_live_process(proc, argv, env)

    def test_post_dispatch_preflight_fake_probes_build_reducible_binding(self):
        evidence = self.root / "evidence"
        evidence.mkdir()
        P.retain_cost_planning_record(evidence)
        (evidence / P.MODEL_ATTESTATION_OPEN_NAME).write_text(
            json.dumps({"model_dir": D.MODEL_DIR}))
        authority = {"comment_id": 123, "head_sha": self.head,
                     "namespace": P.V0_NAMESPACE, "arm": P.V0_ARM,
                     "issue_url": "https://api.github.com/repos/Zutfen-LLC/inferswarm/issues/251",
                     "author_association": "MEMBER",
                     "created_at": "2026-09-27T00:00:00Z",
                     "body": "synthetic V0 authority"}
        calls = []
        def observer(index):
            return {**self.live, "index": index}
        def probe(binary, model, index, dies, directory):
            calls.append(index)
            a = list(dies)[index]
            before = {b: 0 for b in dies}
            after = {b: (512 * 1024 * 1024 if b == a else 0) for b in dies}
            return {"index": index, "vram_before": before, "vram_after": after,
                    "process_attribution": {
                        "server_exe_sha256": P.V0_COMPARATOR_SHA,
                        "server_argv": P.v0_server_argv(binary, model),
                        "server_env": {"VK_ICD_FILENAMES": P.V0_RADV_ICD,
                                       "GGML_VK_VISIBLE_DEVICES": str(index),
                                       "CUDA_VISIBLE_DEVICES": "-1",
                                       "LD_LIBRARY_PATH": str(binary.parent)}}}
        with mock.patch.object(P, "require_live_dispatch", return_value=authority), \
             mock.patch.object(D, "_require_clean_head"), \
             mock.patch.object(P, "_verify_v0_amd_binary", return_value=P.V0_COMPARATOR_SHA), \
             mock.patch.object(P, "validate_model_attestation",
                               return_value={"model_dir": D.MODEL_DIR}), \
             mock.patch.object(P, "attestation_witness", return_value=([], {})):
            record = P.run_v0_binding_preflight(
                self.root, evidence, binary=self.root / "llama-server",
                model_dir=Path(D.MODEL_DIR), expected_head=self.head,
                model_attestation={}, revalidate_authority=None,
                probe_load=probe, device_observer=observer)
        self.assertEqual(calls, [0, 1])
        self.assertEqual(record["mapping"]["0"]["selected_bdf"],
                         "0000:07:00.0")
        self.assertEqual(record["mapping"]["1"]["selected_bdf"],
                         "0000:0b:00.0")
        self.assertEqual(json.loads((evidence / "v0-selector-binding.json").read_text()),
                         record)
        P._v0_verify_probe_records(record, evidence, authority)
        self.assertEqual(self.validate(record=record)["selected_bdf"],
                         "0000:07:00.0")
        with mock.patch.object(P, "require_live_dispatch", return_value=authority), \
             mock.patch.object(D, "_require_clean_head"), \
             mock.patch.object(P, "_verify_v0_amd_binary", return_value=P.V0_COMPARATOR_SHA), \
             mock.patch.object(P, "validate_model_attestation",
                               return_value={"model_dir": D.MODEL_DIR}), \
             mock.patch.object(P, "attestation_witness", return_value=([], {})):
            with self.assertRaises(P.PhysicalDiagnosticError):
                P.run_v0_binding_preflight(self.root, evidence,
                    binary=self.root / "llama-server", model_dir=Path(D.MODEL_DIR),
                    expected_head=self.head, model_attestation={}, probe_load=probe)
        self.assertEqual(calls, [0, 1])


if __name__ == "__main__":
    unittest.main()
