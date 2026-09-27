#!/usr/bin/env python3
"""Issue #250 (R8-I3B) — retained-byte terminal reducer tests.

Direct retained-byte tests for every reachable path of the frozen
sequential law (correction pass 2, blocker 4):
  * A localizes;
  * A→B localizes;
  * A→B→C localizes;
  * A→B→C→D localizes when a valid concrete transition predicate fires;
  * A→B→C→D complete but no causal mechanism => UNRESOLVED;
  * each missing required next arm => BLOCKED;
  * unreachable later-arm evidence cannot override an earlier
    localization;
  * contradictory evidence fails closed;
  * caller-supplied booleans cannot produce a terminal;
  * custody forgery / digest mutation fails closed;
  * campaign model-attestation mutations fail closed.

All fixtures are built through the REAL producer paths (fake runners)
so receipts are internally consistent; mutations tamper ONE field at
a time on a valid retained tree (never fixtures whose metadata all
derives from one generator).
"""
from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _load(name: str, rel: str):
    # The four #250 modules also run together in one unittest process.
    # Re-loading here after physical tests were imported creates two D/P
    # singleton sets: fixture binary patches then miss the producers'
    # module, and predecessor receipts fail identity checks.
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(
        name, REPO / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


for _dep in ("issue248_diagnostic", "issue248_health",
             "issue248_identity"):
    _load(_dep, f"scripts/{_dep}.py")
D = _load("issue250_diagnostic", "scripts/issue250_diagnostic.py")
TB = _load("issue250_timeout", "scripts/issue250_timeout.py")
P = _load("issue250_physical", "scripts/issue250_physical.py")
T = _load("issue250_terminal", "scripts/issue250_terminal.py")

HEAD = "d" * 40
TOKENS = [328, 760, 324, 55965, 51624, 29014, 34227, 18030]
PROMPT_TOKENS = 3077


def make_authority(namespace, arm, head=HEAD, comment_id=1,
                   extra_line=None):
    lines = [
        D.DIAGNOSTIC_DISPATCH_PHRASE,
        f"head={head}",
        f"diagnostic-namespace={namespace}",
        f"arm={arm}",
    ]
    if extra_line:
        lines.append(extra_line)
    body = "\n".join(lines)
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


def raw_identity():
    return {
        "schema": "inferswarm.issue248.subject-identity/1",
        "arm": "B",
        "raw": {
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
                    "    driverID          = "
                    "DRIVER_ID_NVIDIA_PROPRIETARY\n"
                    "    driverInfo        = 610.57.04\n"),
                "stderr": "", "rc": 0,
            },
        },
    }


def health_runner(argv, **kw):
    from collections import namedtuple
    Result = namedtuple("Result", "returncode stdout stderr")
    if argv[0] == "journalctl":
        return Result(0, b"", b"")
    if argv[0] == "nvidia-smi":
        return Result(0, (
            "GPU-d5c05739-96c1-7e49-89b6-bf54c2121c55, 42.0, 140.0, "
            "170.0, 0\n").encode(), b"")
    raise AssertionError(f"unexpected argv {argv}")


def utcnow():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


class FakeServerProc:
    """A fake attributed llama-server process (correction pass 4,
    blocker 2 tests): stands in for the Popen object with poll/return
    control so the production attribution/verification code paths run
    unchanged."""

    def __init__(self, exe_sha, pid=31337):
        self.pid = pid
        self.exe_sha = exe_sha
        self.argv: list = []
        self._terminated = False

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


class CampaignFixture:
    """Builds sequentially reachable #250 evidence through real producers
    (fake runners), plus the accepted #248 contrast tree."""

    def __init__(self, test, *, arm_a_rows="vary", arm_b_fresh="vary",
                 arm_b_same="deterministic", arm_c_default="vary",
                 arm_c_serial="deterministic", arm_c2_gate=False,
                 arm_c2_mode="vary",
                 arm_d_rows=None,
                 arm_d_progress=None, arm_d_confirm_lengths=None,
                 arm_d_confirm_mismatch_at=None,
                 arm_d_token_counts=None):
        import subprocess
        import tempfile
        self.test = test
        self.tmp = tempfile.TemporaryDirectory()
        test.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.repo = self.root / "repo"
        self.evidence = self.root / "evidence"
        self.repo.mkdir()
        self.evidence.mkdir()
        # CORRECTION PASS 5 (NO-GO 5852014883): optional override of
        # the ladder's ACTUAL token counts, keyed by nominal ladder
        # length, for the 2050/2051/2052 execution-boundary equality
        # controls (translated to sentence-repeat keys below).
        self.arm_d_token_counts = arm_d_token_counts

        def git(*args):
            subprocess.run(["git", *args], cwd=self.repo, check=True,
                           capture_output=True)
        git("init", "-q")
        git("config", "user.email", "t@t")
        git("config", "user.name", "t")
        ladder = self.repo / D.FIXTURE_LADDER_REL
        ladder.parent.mkdir(parents=True)
        ladder.write_bytes((REPO / D.FIXTURE_LADDER_REL).read_bytes())
        (self.repo / "m.txt").write_text("x")
        git("add", "-A")
        git("commit", "-qm", "init")
        git("commit", "--allow-empty", "-qm", "h")
        self.head = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=self.repo,
            capture_output=True, text=True, check=True).stdout.strip()

        self.bin = self.root / "llama-server"
        self.bin.write_bytes(b"fake-accepted-build")
        self.saved_binaries = dict(D.SERVER_BINARIES)
        D.SERVER_BINARIES["comparator"] = D.file_sha256(self.bin)
        self.model_dir = self.root / "srvmodel"
        self.model_dir.mkdir()
        self.model_files = {}
        for member in D.MODEL_MEMBERS:
            pth = self.model_dir / member
            pth.write_bytes(b"m:" + member.encode())
            self.model_files[member] = pth
        self.saved_model_dir = D.MODEL_DIR
        D.MODEL_DIR = str(self.model_dir)
        test.addCleanup(self._restore)

        def hasher(path):
            return D.MODEL_MEMBER_SHA256[path.name]
        self.attestation = P.open_campaign_attestation(
            self.evidence, self.model_dir, self.head, hasher=hasher)
        P.close_campaign_attestation(
            self.evidence, self.model_dir, self.head, hasher=hasher)
        P.write_generation_marker(self.evidence)
        P.retain_cost_planning_record(self.evidence)

        self.authorities = {}
        self._build_v0()
        from unittest.mock import patch
        self.v0_historical_patch = patch.object(
            T, "verify_v0_historical_rows", return_value=dict(self.v0_history))
        self.v0_historical_patch.start()
        test.addCleanup(self.v0_historical_patch.stop)
        # A preceding diagnostic old-defect proof may reload the named
        # terminal module while this test file retains its first instance.
        active_terminal = sys.modules.get("issue250_terminal")
        if active_terminal is not T:
            active_patch = patch.object(
                active_terminal, "verify_v0_historical_rows",
                return_value=dict(self.v0_history))
            active_patch.start()
            test.addCleanup(active_patch.stop)
        self._build_arm_a(arm_a_rows)
        self.arm_d_confirm_lengths = (
            arm_d_confirm_lengths if arm_d_confirm_lengths is not None
            else None)  # None => default boundary-adjacent rule
        self.arm_d_confirm_mismatch_at = arm_d_confirm_mismatch_at
        # A deterministic => B unreachable; B fresh deterministic or B
        # same-process deterministic => C unreachable; C2 deterministic
        # => D unreachable. No fake producer bypasses these real gates.
        if arm_a_rows != "det":
            self._build_arm_b(arm_b_fresh, arm_b_same)
            if arm_b_fresh == "vary" and arm_b_same != "deterministic":
                self._build_arm_c(arm_c_default, arm_c_serial)
                if arm_c2_gate:
                    self._write_c2_gate_record(arm_c_serial)
                    self._build_arm_c2(arm_c2_mode)
                if (arm_d_rows is not None and arm_c2_gate
                        and arm_c2_mode != "deterministic"):
                    # retained tokenizer authority precedes Arm-D execution
                    # (correction pass 3, blocker 4A)
                    self._derive_ladder_authority()
                    self._build_arm_d(arm_d_rows, arm_d_progress)
        self._build_contrast()

    def _build_v0(self):
        """Retain a real full-row AMD prefix under the V0 receipt contract.

        Historical #248 is injected only in legacy A-D fixture tests; a
        separate test exercises its original committed/external bytes.
        """
        import hashlib
        self.v0_authority = make_authority(
            D.V0_NAMESPACE, D.V0_ARM, self.head, comment_id=248001)
        v0_case = next(
            case for case in json.loads(
                (REPO / D.FIXTURE_LADDER_REL).read_text())["cases"]
            if case["case_id"] == D.CONTRAST_CASE)
        self.v0_prompt_tokens = v0_case["prompt_token_ids"]
        self.v0_history = {
            "row_sha256": D.V0_NVIDIA_ROW0_SHA256,
            "prompt_len": PROMPT_TOKENS,
            "prompt_token_ids": self.v0_prompt_tokens,
            "prompt_text_sha256": hashlib.sha256(
                v0_case["prompt_text"].encode()).hexdigest(),
            "prompt_sha256": hashlib.sha256(json.dumps(
                self.v0_prompt_tokens, separators=(",", ":")).encode()).hexdigest(),
            "manifest_self_digest": D.ACCEPTED_248_MANIFEST_SELF_DIGEST,
            "result_head": D.ACCEPTED_248_RESULT_HEAD,
        }
        base = self.evidence / D.V0_NAMESPACE
        for index, tag in enumerate(D.V0_UNIT_TAGS[:2], 1):
            unit = base / tag
            unit.mkdir(parents=True)
            row = bytes([index]) * D.ROW_BYTES
            (unit / "obs.row0.f32").write_bytes(row)
            receipt = {
                "schema": D.V0_SCHEMA, "tag": tag,
                "namespace": D.V0_NAMESPACE, "arm": D.V0_ARM,
                "head_sha": self.head,
                "evidence_generation": P.EVIDENCE_GENERATION,
                "authority_sha256": D.authority_digest(self.v0_authority),
                "placement_verified": True,
                "amd_device": {"index": 0, "vendor_id": "0x1002"},
                "decision0_row_sha256": hashlib.sha256(row).hexdigest(),
                "row_bytes": D.ROW_BYTES, "case_id": D.CONTRAST_CASE,
                "ngl": 1, "backend": "Vulkan",
                "embedding_placement": "CPU",
                "output_projection_placement": "Vulkan",
                "model_dir": D.MODEL_DIR,
                "model_launch_member": str(Path(D.MODEL_DIR) / D.MODEL_MEMBER_1),
                "model_member_sha256": D.MODEL_MEMBER_SHA256[D.MODEL_MEMBER_1],
                "prompt_sha256": self.v0_history["prompt_sha256"],
                "prompt_token_ids": self.v0_prompt_tokens,
                "prompt_text_sha256": self.v0_history["prompt_text_sha256"],
                "prompt_len": PROMPT_TOKENS,
                "request_contract": D.REQUEST_CONTRACT,
                "request_contract_sha256": D.canonical_request_digest(D.REQUEST_CONTRACT),
                "fresh_process": True, "server_pid": index + 40000,
                "binary_sha256": D.SERVER_BINARIES["comparator"],
                "server_argv": [str(self.bin), "--model",
                                str(Path(D.MODEL_DIR) / D.MODEL_MEMBER_1),
                                "-ngl", "1", "--device", "0"],
            }
            (unit / "unit.json").write_text(json.dumps(receipt))

    def _derive_ladder_authority(self):
        """Retain the token authority through an ATTRIBUTED (fake)
        tokenizer server launch — the production document shape
        (correction pass 4, NO-GO 5851078451, blocker 2): the fixture
        exercises the real launch/attribute/verify/teardown path with
        fake process seams, so the retained document carries the
        process-attribution block the reducer demands."""
        counts = {68: 1022, 102: 1534, 136: 2053, 153: 2303,
                  171: 2567, 204: 3077}
        if self.arm_d_token_counts:
            # pass-5 equality controls: remap nominal ladder length
            # -> actual token count through the sentence-repeat key
            for length, count in self.arm_d_token_counts.items():
                repeats = D.ARM_D_LADDER_SENTENCE_REPEATS[length]
                counts[repeats] = count

        def prompt_count(prompt: str) -> int:
            return counts.get(
                prompt.count("The lighthouse keeper counted"),
                len(prompt.split()))

        bin_sha = D.SERVER_BINARIES["comparator"]
        fake_proc = FakeServerProc(bin_sha)

        def fake_spawn(argv, log_path):
            fake_proc.argv = list(argv)
            return fake_proc

        def fake_attribution(proc, argv, env):
            return {"server_pid": proc.pid,
                    "server_exe_sha256": bin_sha,
                    "server_argv": list(argv),
                    "server_env": dict(env)}

        def fake_wait_healthy(proc, port):
            pass

        def fake_post(url, body):
            prompt = json.loads(body)["content"]
            n = prompt_count(prompt)
            doc = {"tokens": list(range(n))}
            raw = json.dumps(doc).encode()
            return raw, doc

        P.derive_ladder_token_authority(
            self.repo, self.evidence, self.head,
            binary=self.bin, binary_id="comparator",
            model_dir=self.model_dir,
            attestation=self.attestation,
            launch_server=lambda binary, binary_sha, model_dir,
                member: P.launch_tokenizer_server(
                binary, binary_sha, model_dir, member,
                spawn=fake_spawn, wait_healthy=fake_wait_healthy,
                port_occupied=lambda port: False,
                attribution_fn=fake_attribution),
            stop_server=lambda handle: fake_proc.terminate(),
            verify_alive=lambda handle, sha: fake_proc.verify(sha),
            http_post=fake_post)

    def _restore(self):
        D.SERVER_BINARIES.update(self.saved_binaries)
        D.MODEL_DIR = self.saved_model_dir

    # ---------------- authority ----------------
    def fetch_all(self):
        """One stable fake live dispatch for all campaign namespaces.

        Predecessor checks fetch earlier arms with this SAME fetcher; C2's
        gate digests must bind the exact bytes later returned by it.
        """
        by_ns = {}

        def fetch(repo_root, expected_head, ns, github_api=None):
            if ns not in by_ns:
                raise D.DiagnosticError(
                    f"no dispatch authority for namespace {ns}")
            if ns == D.V0_NAMESPACE:
                return dict(self.v0_authority)
            return dict(by_ns[ns])
        for ns, arm in ((D.V0_NAMESPACE, D.V0_ARM),
                        ("d250-arm-a", "A-vulkan-necessity"),
                        ("d250-arm-b", "B-process-init"),
                        ("d250-arm-c", "C-cpu-threads"),
                        ("d250-arm-c1", "C1-reduced-parallelism"),
                        (D.C2_SERIAL_NAMESPACE, D.ARM_C2_NAME),
                        ("d250-arm-d", "D-context-transition")):
            base = make_authority(
                ns, arm, head=self.head,
                extra_line=(D.C2_GATE_REQUIRED_LINE
                            if ns == D.C2_SERIAL_NAMESPACE else None))
            if ns in self.authorities:
                base = self.authorities[ns]
            by_ns[ns] = base
        return fetch

    # ---------------- unit builders ----------------
    def _write_rows(self, unit_dir, seed_key):
        import hashlib
        seed = hashlib.sha256(seed_key.encode()).digest()
        meta_lines = []
        for i in range(D.DECISIONS):
            row = (seed * (D.ROW_BYTES // len(seed) + 1))[:D.ROW_BYTES]
            (unit_dir / f"obs.row{i}.f32").write_bytes(row)
            meta_lines.append(json.dumps(
                {"pos": i, "sampled_winner": TOKENS[i]}))
        (unit_dir / "obs.meta.json").write_text(
            "\n".join(meta_lines) + "\n")

    def fake_execute(self, seed_key, progress_lines=None,
                     prompt_tokens=None):
        def execute(argv, env, request, prompt, port, unit_dir,
                timeout_budget=None):
            self._write_rows(unit_dir, seed_key)
            # the retained log must carry the ACTUAL token count from
            # the retained tokenizer authority (blocker 4A) plus the
            # progress rungs
            tokens = (prompt_tokens
                      if prompt_tokens is not None else PROMPT_TOKENS)
            if progress_lines is not None:
                body = "\n".join(progress_lines) + "\n"
                body += (f"slot print_timing: prompt eval time = "
                         f"1.0 ms / {tokens} tokens\n")
                (unit_dir / "server.log").write_text(body)
            else:
                (unit_dir / "server.log").write_text(
                    "slot print_timing: prompt eval time = 1.0 ms / "
                    f"{tokens} tokens\n")
            now = utcnow()
            return {
                "returncode": 0, "tokens": list(TOKENS),
                "response_raw": json.dumps(
                    {"tokens": TOKENS}).encode(),
                "process_attribution": {
                    "server_pid": 4000 + abs(hash(seed_key)) % 100,
                    "server_exe_sha256": D.SERVER_BINARIES["comparator"],
                    "server_argv": list(argv), "server_env": dict(env)},                "timeout_budget": timeout_budget,
                "device_samples": [
                    {"stage": s, "captured_at": now,
                     "nvidia_smi_raw":
                         "GPU-d5c05739-96c1-7e49-89b6-"
                         "bf54c2121c55, 42.0, 140.0, 170.0, 0\n"}
                    for s in ("before", "during", "after")],
            }
        return execute

    def _run_unit(self, namespace, arm, tag, seed_key,
                  progress_lines=None, prompt_tokens=None):
        P.run_diagnostic_unit(
            repo_root=self.repo, evidence_root=self.evidence,
            namespace=namespace, arm=arm, tag=tag,
            binary=self.bin, binary_id="comparator",
            model_dir=self.model_dir, expected_head=self.head,
            model_attestation=self.attestation,
            execute=self.fake_execute(seed_key, progress_lines,
                                      prompt_tokens),
            identity_observer=lambda: raw_identity(),
            revalidate_authority=self.fetch_all(),
            health_runner=health_runner)

    def _build_arm_a(self, mode):
        plan = D.probe_list_for("A-vulkan-necessity")
        # HONEST PRODUCER SHAPE (correction pass 3, blocker 2): in
        # "vary" mode the first row mismatch answers the discriminator
        # at unit 002 — execution stops there (frozen early-stop law);
        # units 003..005 are never run. In "det" mode all five planned
        # units run with identical rows (frozen deterministic count).
        for i, spec in enumerate(plan):
            if mode == "vary" and i >= 2:
                break
            seed_key = (f"{spec['tag']}-varying" if mode == "vary"
                        else "arm-a-fixed")
            if mode == "vary" and i == 0:
                seed_key = "armA-vary-baseline"
            self._run_unit("d250-arm-a", "A-vulkan-necessity",
                           spec["tag"], seed_key)

    def _build_arm_b(self, fresh_mode, same_mode):
        plan = [u for u in D.probe_list_for("B-process-init")
                if not u.get("same_process")]
        for i, spec in enumerate(plan):
            if fresh_mode == "vary" and i >= 2:
                break
            seed_key = (f"armB-fresh-varying-{i}"
                        if fresh_mode == "vary" else "armB-fresh-fixed")
            if fresh_mode == "vary" and i == 0:
                seed_key = "armB-fresh-baseline"
            self._run_unit(
                "d250-arm-b", "B-process-init", spec["tag"], seed_key)
        # same-process lifecycle via the real producer
        P.run_same_process_lifecycle(
            repo_root=self.repo, evidence_root=self.evidence,
            namespace="d250-arm-b", arm="B-process-init",
            tag_prefix="case-3072-B-cpu-sameproc",
            binary=self.bin, binary_id="comparator",
            model_dir=self.model_dir, expected_head=self.head,
            model_attestation=self.attestation,
            execute=self._fake_same_process(same_mode),
            identity_observer=lambda: raw_identity(),
            revalidate_authority=self.fetch_all(),
            health_runner=health_runner)

    def _fake_same_process(self, mode):
        def execute(argv, env, request, prompt, port, unit_dir,
                    repeats, expected_prompt_tokens,
                    preflight_request=None, timeout_s=None):
            import hashlib
            records = []
            now = utcnow()
            pid = 777
            base_task_id = 50
            # HONEST PRODUCER SHAPE (blocker 2): nondeterministic
            # lifecycles stop at the FIRST row mismatch (request 002)
            # — the frozen early-stop law — and report
            # stop_kind=mismatch_stop. Deterministic lifecycles run
            # all five planned requests.
            stop_kind = "completed_all"
            stop_reason = None
            baseline = None
            for index in range(repeats):
                if preflight_request is not None:
                    preflight_request(index)
                key = ("same-fixed" if mode == "deterministic"
                       else ("same-vary-baseline" if index == 0
                             else f"same-varying-{index}"))
                seed = hashlib.sha256(key.encode()).digest()
                row_files = {}
                meta_lines = []
                for d in range(D.DECISIONS):
                    row = (seed * (D.ROW_BYTES // len(seed) + 1)
                           )[:D.ROW_BYTES]
                    row_files[f"obs.row{d}.f32"] = row
                    meta_lines.append(json.dumps(
                        {"pos": d, "sampled_winner": TOKENS[d]}))
                task_id = base_task_id + index
                log_slice = (
                    f"0.01.000.000 I slot get_availabl: id  3 | "
                    f"task -1 | selected slot by id (3)\n"
                    f"0.01.000.001 I slot launch_slot_: id  3 | "
                    f"task {task_id} | processing task, is_child = 0\n"
                    f"0.01.000.002 I slot print_timing: id  3 | "
                    f"task {task_id} | prompt "
                    f"eval time = 1.0 ms / {expected_prompt_tokens} "
                    f"tokens\n").encode()
                records.append({
                    "server_pid": pid,
                    "tokens": list(TOKENS),
                    "response_raw": json.dumps(
                        {"tokens": TOKENS}).encode(),
                    "log_slice": log_slice,
                    "row_files": row_files,
                    "meta_file": ("\n".join(meta_lines) + "\n").encode(),
                    "reset_proof": P._parse_slot_log(
                        log_slice.decode(), index,
                        expected_prompt_tokens),
                    "request_contract": dict(request),
                })
                if mode != "deterministic":
                    digests = tuple(hashlib.sha256(
                        row_files[f"obs.row{d}.f32"]).hexdigest()
                        for d in range(D.DECISIONS))
                    if baseline is None:
                        baseline = digests
                    elif digests != baseline:
                        stop_kind = "mismatch_stop"
                        stop_reason = (
                            f"first row-digest mismatch at request "
                            f"{index}")
                        break
            return {
                "server_pid": pid,
                "process_attribution": {
                    "server_pid": pid,
                    "server_exe_sha256": D.SERVER_BINARIES["comparator"],
                    "server_argv": list(argv),
                    "server_env": dict(env)},
                "requests": records,
                "device_samples": [
                    {"stage": s, "captured_at": now,
                     "nvidia_smi_raw":
                         "GPU-d5c05739-96c1-7e49-89b6-"
                         "bf54c2121c55, 42.0, 140.0, 170.0, 0\n"}
                    for s in ("before", "during", "after")],
                "stop_kind": stop_kind,
                "stop_reason": stop_reason,
            }
        return execute

    def _build_arm_c(self, default_mode, c1_mode):
        """AMENDMENT-003 shape: d250-arm-c default reproduction pair
        (2 units) + the d250-arm-c1 bounded reduced-parallelism probe
        (5 units, early stop). ``serial_mode`` now drives C1; the
        gated serial C2 population is NOT built by this fixture."""
        default_vary_count = 0
        c1_vary_count = 0
        for i, spec in enumerate(D.probe_list_for("C-cpu-threads")):
            mode = default_mode
            if mode == "vary":
                default_vary_count += 1
                if default_vary_count > 2:
                    break
            seed_key = (f"armC-default-varying-{i}"
                        if mode == "vary" else "armC-default-fixed")
            if mode == "vary" and i == 0:
                seed_key = "armC-default-baseline"
            self._run_unit(
                "d250-arm-c", "C-cpu-threads", spec["tag"], seed_key)
        c1_plan = D.probe_list_for("C1-reduced-parallelism")
        for i, spec in enumerate(c1_plan):
            mode = c1_mode
            if mode == "vary":
                c1_vary_count += 1
                if c1_vary_count > 2:
                    break  # early-stop after the mismatch unit
            seed_key = (f"armC1-varying-{i}"
                        if mode == "vary" else "armC1-fixed")
            if mode == "vary" and i == 0:
                seed_key = "armC1-baseline"
            self._run_unit(
                "d250-arm-c1", "C1-reduced-parallelism",
                spec["tag"], seed_key)

    def _c1_c2_authorities(self):
        by_ns = {}
        for ns, arm in (("d250-arm-c1", "C1-reduced-parallelism"),
                        (D.C2_SERIAL_NAMESPACE, D.ARM_C2_NAME)):
            base = make_authority(
                ns, arm, head=self.head,
                extra_line=(D.C2_GATE_REQUIRED_LINE
                            if ns == D.C2_SERIAL_NAMESPACE else None))
            if ns in self.authorities:
                base = self.authorities[ns]
            by_ns[ns] = base
        return by_ns

    def _write_c2_gate_record(self, c1_mode):
        """Frozen C1-completed gate record binding BOTH the C1 and C2
        authority digests (written BEFORE the C2 units execute — the
        dispatch authority itself demands the closed gate)."""
        by_ns = self._c1_c2_authorities()
        gate = {
            "schema": D.C2_GATE_RECORD_SCHEMA,
            "head_sha": self.head,
            "c1_completed": True,
            "c1_verdict": ("variable" if c1_mode == "vary"
                           else "deterministic"),
            "c1_authority_sha256": D.authority_digest(
                by_ns["d250-arm-c1"]),
            "c2_authority_sha256": D.authority_digest(
                by_ns[D.C2_SERIAL_NAMESPACE]),
        }
        (self.evidence / D.C2_GATE_RECORD_NAME).write_text(
            json.dumps(gate, indent=2, sort_keys=True) + "\n")

    def _build_arm_c2(self, c2_mode):
        """Gated serial C2 population after either completed C1 verdict."""
        for i, spec in enumerate(D.probe_list_for(D.ARM_C2_NAME)):
            # HONEST PRODUCER SHAPE (frozen early-stop law): in "vary"
            # mode the first mismatch answers at unit 002 — units
            # 003..005 are never run.
            if c2_mode == "vary" and i >= 2:
                break
            seed_key = (f"armC2-varying-{i}" if c2_mode == "vary"
                        else "armC2-fixed")
            if c2_mode == "vary" and i == 0:
                seed_key = "armC2-baseline"
            self._run_unit(D.C2_SERIAL_NAMESPACE, D.ARM_C2_NAME,
                           spec["tag"], seed_key)

    def _build_arm_d(self, rows_mode, progress):
        """rows_mode: None (no arm D) | dict length->'det'/'var'.

        HONEST PRODUCER SHAPE (correction pass 3, blocker 4C): the
        2-repeat screening pair runs at every length; a 'det' length
        whose LOCALIZED claim would depend on it (the last
        deterministic length before the boundary) is extended through
        its predeclared confirm units 003-005 to reach the frozen
        deterministic-confirmation count of 5. Unrelated ladder
        points are NOT extended. A 'var' length stops at the first
        mismatch within its screening pair.
        """
        if rows_mode is None:
            return
        # actual token counts from the retained tokenizer authority
        # (the fixture's fake tokenizer map; blocker 4A)
        authority = json.loads(
            (self.evidence / P.LADDER_TOKEN_AUTHORITY_NAME).read_bytes())
        actual = {int(k): v["actual_token_count"]
                  for k, v in authority["lengths"].items()}
        det_lengths = sorted(n for n, m in rows_mode.items() if m == "det")
        last_det = det_lengths[-1] if det_lengths else None
        # confirm-extension policy: None => default frozen adaptive
        # rule (boundary-adjacent deterministic length only); a set
        # => exactly those lengths extended (empty => none extended)
        if self.arm_d_confirm_lengths is None:
            confirm_lengths = ({last_det} if last_det is not None
                               else set())
        else:
            confirm_lengths = set(self.arm_d_confirm_lengths)
        mismatch_length = self.arm_d_confirm_mismatch_at
        for spec in D.probe_list_for("D-context-transition"):
            length = spec["ladder_length"]
            tag = spec["tag"]
            mode = rows_mode[length]
            confirm = bool(spec.get("confirm_extension"))
            idx = tag.rsplit("-", 1)[1]
            # adaptive confirmation: only the predeclared boundary
            # condition executes its confirm units
            if confirm and length not in confirm_lengths:
                continue
            if mode == "var" and idx not in ("001", "002"):
                continue
            progress_lines = (progress or {}).get(length, [
                "slot print_timing: prompt processing, n_tokens = 512",
                "slot print_timing: prompt processing, n_tokens = 1024",
            ])
            seed = (f"armD-{length}-det" if mode == "det"
                    else f"armD-{length}-var-{idx}")
            # a mismatch injected inside the confirm extension of a
            # "det" length makes that length variable — the first
            # mismatch establishes variability immediately
            if (mismatch_length == length and confirm
                    and mode == "det" and tag.endswith("-003-confirm")):
                seed = f"armD-{length}-confirm-mismatch"
            self._run_unit(
                "d250-arm-d", "D-context-transition", tag, seed,
                progress_lines=progress_lines,
                prompt_tokens=actual[length])

    # ---------------- contrast tree ----------------
    def _build_contrast(self):
        import hashlib
        root = self.root / "contrast"
        ns_dir = root / D.CONTRAST_NAMESPACE
        rows_by_unit = {}
        manifest_rows = []
        for tag in D.CONTRAST_UNITS:
            unit_dir = ns_dir / tag
            unit_dir.mkdir(parents=True)
            seed = hashlib.sha256(tag.encode()).digest()
            row_sha = []
            for i in range(D.DECISIONS):
                row = (seed * (D.ROW_BYTES // len(seed) + 1)
                       )[:D.ROW_BYTES]
                (unit_dir / f"obs.row{i}.f32").write_bytes(row)
                digest = hashlib.sha256(row).hexdigest()
                row_sha.append(digest)
                manifest_rows.append(
                    (f"{digest}  {D.CONTRAST_NAMESPACE}/{tag}/"
                     f"obs.row{i}.f32"))
            meta_lines = [json.dumps({"pos": i,
                                      "sampled_winner": TOKENS[i]})
                          for i in range(D.DECISIONS)]
            meta_bytes = ("\n".join(meta_lines) + "\n").encode()
            (unit_dir / "obs.meta.json").write_bytes(meta_bytes)
            manifest_rows.append(
                (f"{hashlib.sha256(meta_bytes).hexdigest()}  "
                 f"{D.CONTRAST_NAMESPACE}/{tag}/obs.meta.json"))
            tokens = list(TOKENS)
            raw = json.dumps({"tokens": tokens}).encode()
            (unit_dir / "response.json.raw").write_bytes(raw)
            manifest_rows.append(
                (f"{hashlib.sha256(raw).hexdigest()}  "
                 f"{D.CONTRAST_NAMESPACE}/{tag}/response.json.raw"))
            receipt = {
                "schema": "inferswarm.issue248.diagnostic-unit/1",
                "namespace": D.CONTRAST_NAMESPACE,
                "tag": tag,
                "case_id": D.CONTRAST_CASE,
                "arm": "B",
                "ngl": D.CONTRAST_NGL,
                "observer_rows": row_sha,
                "deterministic_output_sha256": D.canonical_token_digest(
                    tokens),
                "tokens": tokens,
                "authority": {
                    "comment_id": 5835805496,
                    "head_sha": T.CONTRAST_AUTHORITY_HEAD,
                    "namespace": D.CONTRAST_NAMESPACE,
                    "created_at": "2026-09-25T00:00:00Z",
                    "author_association": "MEMBER",
                    "pr_number": 249,
                    "issue_number": 248,
                    "dispatch_sha256": "0" * 64,
                },
            }
            receipt_bytes = (json.dumps(receipt, indent=2,
                                        sort_keys=True) + "\n").encode()
            (unit_dir / "unit.json").write_bytes(receipt_bytes)
            manifest_rows.append(
                (f"{hashlib.sha256(receipt_bytes).hexdigest()}  "
                 f"{D.CONTRAST_NAMESPACE}/{tag}/unit.json"))
            rows_by_unit[tag] = row_sha
        # manifest self-digest must equal the accepted constant: build
        # then pad? No: the verifier hashes the manifest bytes and
        # compares to the frozen constant, so a synthetic tree cannot
        # pass the real verifier. Tests instead patch the constant to
        # the synthetic manifest digest (restored on cleanup).
        manifest_text = "\n".join(sorted(manifest_rows)) + "\n"
        (root / "SHA256SUMS").write_text(manifest_text)
        self.contrast_root = root
        self.saved_manifest_digest = D.ACCEPTED_248_MANIFEST_SELF_DIGEST
        D.ACCEPTED_248_MANIFEST_SELF_DIGEST = hashlib.sha256(
            manifest_text.encode()).hexdigest()

    def restore_contrast_constant(self):
        D.ACCEPTED_248_MANIFEST_SELF_DIGEST = (
            self.saved_manifest_digest)

    # ---------------- helpers for tests ----------------
    def derive(self, **over):
        kw = dict(
            evidence_root=self.evidence, expected_head=self.head,
            repo_root=self.repo,
            authority_fetcher=self.fetch_all(),
            contrast_root=self.contrast_root,
        )
        kw.update(over)
        from unittest.mock import patch
        # Existing A-D fixture matrix supplies synthetic #248 contrast rows;
        # patch ONLY historical materialization, never the AMD byte reducer.
        with patch.object(T, "verify_v0_historical_rows",
                          return_value=dict(self.v0_history)):
            return T.derive_terminal(**kw)


class V0EvidenceBridgeTests(unittest.TestCase):
    """The evidence gate checks retained full bytes before Arm A."""

    def _fixture(self):
        fixture = CampaignFixture(self, arm_a_rows="det")
        self.addCleanup(fixture.restore_contrast_constant)
        return fixture

    def test_v0_variable_then_independent_a_dispatch(self):
        f = self._fixture()
        out = f.derive()
        self.assertEqual(out["terminal"], T.LOCALIZED)
        self.assertEqual(out["v0"]["state"], D.V0_STATE_AMD_VARIABLE)
        fetch = f.fetch_all()
        def no_a(repo, head, ns, api):
            if ns == "d250-arm-a":
                raise D.DiagnosticError("A dispatch absent")
            return fetch(repo, head, ns, api)
        out = f.derive(authority_fetcher=no_a)
        self.assertEqual(out["blocked"], T.BLOCKED)
        self.assertEqual(out["v0"]["state"], D.V0_STATE_AMD_VARIABLE)

    def test_v0_mutation_and_selective_omission_block_terminal(self):
        f = self._fixture()
        unit = f.evidence / D.V0_NAMESPACE / D.V0_UNIT_TAGS[1]
        receipt_path = unit / "unit.json"
        row_path = unit / "obs.row0.f32"
        original = json.loads(receipt_path.read_text())
        for key, wrong in (("model_member_sha256", "0" * 64),
                           ("prompt_sha256", "0" * 64),
                           ("prompt_token_ids", [0] * PROMPT_TOKENS),
                           ("prompt_text_sha256", "0" * 64),
                           ("request_contract", {**D.REQUEST_CONTRACT, "seed": 9}),
                           ("ngl", 8), ("backend", "CPU"),
                           ("embedding_placement", "Vulkan"),
                           ("output_projection_placement", "CPU"),
                           ("placement_verified", False),
                           ("head_sha", "a" * 40),
                           ("authority_sha256", "0" * 64)):
            receipt_path.write_text(json.dumps({**original, key: wrong}))
            out = f.derive()
            self.assertEqual(out["blocked"], T.BLOCKED, key)
            self.assertEqual(out["v0"]["state"], D.V0_STATE_INVALID, key)
        receipt_path.write_text(json.dumps(original))
        raw = row_path.read_bytes()
        for bad in (raw[:-1], raw[:-1] + bytes([raw[-1] ^ 1])):
            row_path.write_bytes(bad)
            self.assertEqual(f.derive()["v0"]["state"], D.V0_STATE_INVALID)
        row_path.write_bytes(raw)
        receipt_path.rename(unit / "unit.json-quarantined")
        self.assertEqual(f.derive()["v0"]["state"], D.V0_STATE_INVALID)
        receipt_path.write_text(json.dumps(original))
        extra = f.evidence / D.V0_NAMESPACE / D.V0_UNIT_TAGS[2]
        extra.mkdir()
        self.assertEqual(f.derive()["v0"]["state"], D.V0_STATE_INVALID)

    def test_identical_pair_needs_third_not_a(self):
        f = self._fixture()
        first = f.evidence / D.V0_NAMESPACE / D.V0_UNIT_TAGS[0] / "obs.row0.f32"
        second = f.evidence / D.V0_NAMESPACE / D.V0_UNIT_TAGS[1]
        raw = first.read_bytes()
        (second / "obs.row0.f32").write_bytes(raw)
        receipt = json.loads((second / "unit.json").read_text())
        import hashlib
        receipt["decision0_row_sha256"] = hashlib.sha256(raw).hexdigest()
        (second / "unit.json").write_text(json.dumps(receipt))
        self.assertEqual(f.derive()["v0"]["state"],
                         D.V0_STATE_IDENTICAL_PAIR_NEEDS_THIRD)
        third = f.evidence / D.V0_NAMESPACE / D.V0_UNIT_TAGS[2]
        third.mkdir()
        (third / "obs.row0.f32").write_bytes(raw)
        receipt.update(tag=D.V0_UNIT_TAGS[2], server_pid=40003)
        (third / "unit.json").write_text(json.dumps(receipt))
        self.assertEqual(f.derive()["v0"]["state"], D.V0_STATE_DISAGREEMENT_STOP)

    def test_external_248_actual_rows_when_available(self):
        import os
        import tempfile
        import shutil
        source = os.environ.get("ISSUE250_TEST_248_EVIDENCE_ROOT")
        if not source:
            self.skipTest("set ISSUE250_TEST_248_EVIDENCE_ROOT to retained #248 copy")
        source = Path(source)
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / D.CONTRAST_NAMESPACE).mkdir()
            shutil.copy2(source / "SHA256SUMS", root / "SHA256SUMS")
            for tag in D.CONTRAST_UNITS:
                dst = root / D.CONTRAST_NAMESPACE / tag
                dst.mkdir()
                for name in ("unit.json", "obs.row0.f32"):
                    shutil.copy2(source / D.CONTRAST_NAMESPACE / tag / name,
                                 dst / name)
            out = T.verify_v0_historical_rows(root, REPO)
            self.assertEqual(out["row_sha256"], D.V0_NVIDIA_ROW0_SHA256)
            row = root / D.CONTRAST_NAMESPACE / D.CONTRAST_UNITS[0] / "obs.row0.f32"
            raw = row.read_bytes()
            for bad in (raw[:-1], bytes([raw[0] ^ 1]) + raw[1:]):
                row.write_bytes(bad)
                with self.assertRaises(ValueError):
                    T.verify_v0_historical_rows(root, REPO)
            row.write_bytes(raw)
            receipt = root / D.CONTRAST_NAMESPACE / D.CONTRAST_UNITS[0] / "unit.json"
            original = receipt.read_bytes()
            obj = json.loads(original)
            obj["authority"]["issue_number"] = 247
            receipt.write_text(json.dumps(obj))
            with self.assertRaises(ValueError):
                T.verify_v0_historical_rows(root, REPO)


class TerminalMatrixTests(unittest.TestCase):
    """Every reachable path of the frozen sequential law."""

    def _fixture(self, **kw):
        fixture = CampaignFixture(self, **kw)
        # the contrast constant patch must be restored AFTER the
        # normal cleanup chain unwinds D.SERVER_BINARIES
        self.addCleanup(fixture.restore_contrast_constant)
        return fixture

    def test_a_localizes(self):
        f = self._fixture(arm_a_rows="det", arm_b_fresh="vary",
                          arm_b_same="vary", arm_c_default="vary",
                          arm_c_serial="vary",
                          arm_c2_gate=True, arm_d_rows=None)
        self.assertFalse((f.evidence / "d250-arm-b").exists())
        self.assertFalse((f.evidence / "d250-arm-c").exists())
        out = f.derive()
        self.assertEqual(out["terminal"], T.LOCALIZED, out.get("problems"))
        self.assertIn("backend-participation",
                      out["basis"]["localized_factor"])

    def test_pair_identical_without_confirmation_is_unresolved(self):
        # blocker 4C: 2 identical screening rows are NOT a
        # deterministic condition; without the confirm extension the
        # D claim cannot localize
        # det side actual tokens (1022, 1534) all <= 2051
        # (all-cells side); var side (2053, 2303, 2567, 3077) all
        # >= 2052 (selective side) — the
        # indexer_top_k_boundary fires at (1536, 2048)
        ladder = {1024: "det", 1536: "det", 2048: "var", 2304: "var",
                  2560: "var", 3072: "var"}
        progress = {
            1024: ["prompt processing, n_tokens = 512",
                   "prompt processing, n_tokens = 1024"],
            1536: ["prompt processing, n_tokens = 512",
                   "prompt processing, n_tokens = 1024",
                   "prompt processing, n_tokens = 1536"],
            2048: ["prompt processing, n_tokens = 512",
                   "prompt processing, n_tokens = 1024",
                   "prompt processing, n_tokens = 1536",
                   "prompt processing, n_tokens = 2048"],
            2304: ["prompt processing, n_tokens = 768",
                   "prompt processing, n_tokens = 1536",
                   "prompt processing, n_tokens = 2304"],
            2560: ["prompt processing, n_tokens = 512",
                   "prompt processing, n_tokens = 1024",
                   "prompt processing, n_tokens = 1536",
                   "prompt processing, n_tokens = 2048",
                   "prompt processing, n_tokens = 2560"],
            3072: ["prompt processing, n_tokens = 512",
                   "prompt processing, n_tokens = 1024",
                   "prompt processing, n_tokens = 1536",
                   "prompt processing, n_tokens = 2048",
                   "prompt processing, n_tokens = 2560",
                   "prompt processing, n_tokens = 2565",
                   "prompt processing, n_tokens = 3073"],
        }
        f = self._fixture(arm_a_rows="vary", arm_b_fresh="vary",
                          arm_b_same="vary", arm_c_default="vary",
                          arm_c_serial="vary",
                          arm_c2_gate=True, arm_d_rows=ladder,
                          arm_d_progress=progress,
                          arm_d_confirm_lengths=set())
        out = f.derive()
        self.assertEqual(out["terminal"], T.UNRESOLVED, out.get("problems"))
        self.assertIn("pair-identical", out["basis"]["reason"])

    def test_confirmed_boundary_localizes(self):
        # det side actual tokens (1022, 1534) all <= 2051
        # (all-cells side); var side (2053, 2303, 2567, 3077) all
        # >= 2052 (selective side) — the
        # indexer_top_k_boundary fires at (1536, 2048)
        ladder = {1024: "det", 1536: "det", 2048: "var", 2304: "var",
                  2560: "var", 3072: "var"}
        progress = {length: [
            "prompt processing, n_tokens = 512",
            "prompt processing, n_tokens = 1024"] for length in ladder}
        f = self._fixture(arm_a_rows="vary", arm_b_fresh="vary",
                          arm_b_same="vary", arm_c_default="vary",
                          arm_c_serial="vary",
                          arm_c2_gate=True, arm_d_rows=ladder,
                          arm_d_progress=progress)
        out = f.derive()
        self.assertEqual(out["terminal"], T.LOCALIZED, out.get("problems"))
        self.assertEqual(out["basis"]["transition_predicate"],
                         "indexer_top_k_boundary")

    def test_unconfirmed_length_cannot_localize(self):
        # same ladder but NO confirm extension executed anywhere
        # det side actual tokens (1022, 1534) all <= 2051
        # (all-cells side); var side (2053, 2303, 2567, 3077) all
        # >= 2052 (selective side) — the
        # indexer_top_k_boundary fires at (1536, 2048)
        ladder = {1024: "det", 1536: "det", 2048: "var", 2304: "var",
                  2560: "var", 3072: "var"}
        progress = {length: [
            "prompt processing, n_tokens = 512",
            "prompt processing, n_tokens = 1024"] for length in ladder}
        f = self._fixture(arm_a_rows="vary", arm_b_fresh="vary",
                          arm_b_same="vary", arm_c_default="vary",
                          arm_c_serial="vary",
                          arm_c2_gate=True, arm_d_rows=ladder,
                          arm_d_progress=progress,
                          arm_d_confirm_lengths=set())
        out = f.derive()
        self.assertEqual(out["terminal"], T.UNRESOLVED, out.get("problems"))
        self.assertIn("pair-identical", out["basis"]["reason"])

    def test_mismatch_within_confirm_extension_establishes_variability(self):
        # first mismatch at ANY point (including inside the confirm
        # extension) immediately establishes variability — the
        # deterministic side then fails confirmation => UNRESOLVED
        # det side actual tokens (1022, 1534) all <= 2051
        # (all-cells side); var side (2053, 2303, 2567, 3077) all
        # >= 2052 (selective side) — the
        # indexer_top_k_boundary fires at (1536, 2048)
        ladder = {1024: "det", 1536: "det", 2048: "var", 2304: "var",
                  2560: "var", 3072: "var"}
        progress = {length: [
            "prompt processing, n_tokens = 512",
            "prompt processing, n_tokens = 1024"] for length in ladder}
        f = self._fixture(arm_a_rows="vary", arm_b_fresh="vary",
                          arm_b_same="vary", arm_c_default="vary",
                          arm_c_serial="vary",
                          arm_c2_gate=True, arm_d_rows=ladder,
                          arm_d_progress=progress,
                          arm_d_confirm_mismatch_at=1536)
        out = f.derive()
        self.assertEqual(out["terminal"], T.UNRESOLVED, out.get("problems"))

    def test_a_to_b_localizes(self):
        f = self._fixture(arm_a_rows="vary", arm_b_fresh="vary",
                          arm_b_same="deterministic")
        self.assertFalse((f.evidence / "d250-arm-c").exists())
        out = f.derive()
        self.assertEqual(out["terminal"], T.LOCALIZED, out.get("problems"))
        self.assertIn("fresh-process/runtime-initialization",
                      out["basis"]["localized_factor"])

    def test_c1_deterministic_requires_single_thread_followup_before_localization(self):
        f = self._fixture(arm_a_rows="vary", arm_b_fresh="vary",
                          arm_b_same="vary", arm_c_default="vary",
                          arm_c_serial="deterministic")
        out = f.derive()
        self.assertIsNone(out["terminal"])
        self.assertEqual(out["blocked"], T.BLOCKED)
        self.assertFalse(out["arm_c_gate_status"]["c2_serial_gate_closed"])
        self.assertEqual(out["arm_c_gate_status"]["c1_verdict"],
                         "deterministic")

    def test_c1_varied_without_c2_is_blocked(self):
        f = self._fixture(arm_a_rows="vary", arm_b_fresh="vary",
                          arm_b_same="vary", arm_c_default="vary",
                          arm_c_serial="vary")
        out = f.derive()
        self.assertIsNone(out["terminal"])
        self.assertEqual(out["blocked"], T.BLOCKED)
        self.assertEqual(out["arm_c_gate_status"]["c1_verdict"],
                         "variable")

    def test_c2_gate_cannot_launder_the_opposite_c1_verdict(self):
        f = self._fixture(arm_a_rows="vary", arm_b_fresh="vary",
                          arm_b_same="vary", arm_c_default="vary",
                          arm_c_serial="deterministic")
        f._write_c2_gate_record("vary")  # forged C1 claim vs five real rows
        out = f.derive()
        self.assertIsNone(out["terminal"])
        self.assertEqual(out["blocked"], T.BLOCKED)
        self.assertIn("completed retained C1 verdict", " ".join(out["problems"]))

    def test_c2_gate_record_without_live_c2_dispatch_is_blocked(self):
        f = self._fixture(arm_a_rows="vary", arm_b_fresh="vary",
                          arm_b_same="vary", arm_c_default="vary",
                          arm_c_serial="deterministic")
        f._write_c2_gate_record("deterministic")
        normal_fetch = f.fetch_all()
        def without_c2(repo_root, expected_head, namespace, github_api=None):
            if namespace == D.C2_SERIAL_NAMESPACE:
                raise D.DiagnosticError("no C2 dispatch")
            return normal_fetch(repo_root, expected_head, namespace,
                                github_api=github_api)
        out = f.derive(authority_fetcher=without_c2)
        self.assertIsNone(out["terminal"])
        self.assertEqual(out["blocked"], T.BLOCKED)
        self.assertIn(D.C2_SERIAL_NAMESPACE, " ".join(out["problems"]))

    def test_c1_deterministic_with_c2_deterministic_localizes(self):
        f = self._fixture(arm_a_rows="vary", arm_b_fresh="vary",
                          arm_b_same="vary", arm_c_default="vary",
                          arm_c_serial="deterministic", arm_c2_gate=True,
                          arm_c2_mode="deterministic")
        self.assertFalse((f.evidence / "d250-arm-d").exists())
        out = f.derive()
        self.assertEqual(out["terminal"], T.LOCALIZED, out.get("problems"))
        self.assertEqual(out["basis"]["arm"], D.ARM_C2_NAME)
        self.assertIn("-t 1 -tb 1", out["basis"]["localized_factor"])

    def test_c1_varied_with_c2_deterministic_localizes(self):
        f = self._fixture(arm_a_rows="vary", arm_b_fresh="vary",
                          arm_b_same="vary", arm_c_default="vary",
                          arm_c_serial="vary", arm_c2_gate=True,
                          arm_c2_mode="deterministic")
        out = f.derive()
        self.assertEqual(out["terminal"], T.LOCALIZED, out.get("problems"))
        self.assertEqual(out["basis"]["arm"], D.ARM_C2_NAME)

    def test_c1_deterministic_with_c2_varied_reaches_d(self):
        ladder = {length: "var" for length in D.ARM_D_LADDER_LENGTHS}
        ladder[1024] = "det"
        f = self._fixture(arm_a_rows="vary", arm_b_fresh="vary",
                          arm_b_same="vary", arm_c_default="vary",
                          arm_c_serial="deterministic", arm_c2_gate=True,
                          arm_c2_mode="vary", arm_d_rows=ladder)
        out = f.derive()
        self.assertEqual(out["terminal"], T.UNRESOLVED, out.get("problems"))
        self.assertTrue(out["arm_c_gate_status"]["c2_serial_executed"])
        self.assertIn("D-context-transition", out["arms"])


    def test_a_to_b_to_c_to_d_old_midstream_shape_cannot_localize(self):
        # CORRECTION PASS 4 (NO-GO 5851078451, blocker 3) FLIPPED
        # ASSERTION: this exact ladder/progress shape LOCALIZED at D
        # via midstream_ubatch_split at the pass-3 head; the predicate
        # is retired (wall-clock-sampled progress counts are not
        # ubatch boundaries), so the same retained evidence now
        # yields UNRESOLVED — progress counts alone can never select
        # LOCALIZED.
        ladder = {1024: "det", 1536: "det", 2048: "det", 2304: "det",
                  2560: "det", 3072: "var"}
        progress = {
            1024: ["prompt processing, n_tokens = 512",
                   "prompt processing, n_tokens = 1024"],
            1536: ["prompt processing, n_tokens = 512",
                   "prompt processing, n_tokens = 1024",
                   "prompt processing, n_tokens = 1536"],
            2048: ["prompt processing, n_tokens = 512",
                   "prompt processing, n_tokens = 1024",
                   "prompt processing, n_tokens = 1536",
                   "prompt processing, n_tokens = 2048"],
            2304: ["prompt processing, n_tokens = 768",
                   "prompt processing, n_tokens = 1536",
                   "prompt processing, n_tokens = 2304"],
            2560: ["prompt processing, n_tokens = 512",
                   "prompt processing, n_tokens = 1024",
                   "prompt processing, n_tokens = 1536",
                   "prompt processing, n_tokens = 2048",
                   "prompt processing, n_tokens = 2560"],
            3072: ["prompt processing, n_tokens = 512",
                   "prompt processing, n_tokens = 1024",
                   "prompt processing, n_tokens = 1536",
                   "prompt processing, n_tokens = 2048",
                   "prompt processing, n_tokens = 2560",
                   "prompt processing, n_tokens = 2565",
                   "prompt processing, n_tokens = 3073"],
        }
        f = self._fixture(arm_a_rows="vary", arm_b_fresh="vary",
                          arm_b_same="vary", arm_c_default="vary",
                          arm_c_serial="vary",
                          arm_c2_gate=True, arm_d_rows=ladder,
                          arm_d_progress=progress)
        out = f.derive()
        self.assertEqual(out["terminal"], T.UNRESOLVED, out.get("problems"))
        self.assertIn("no smallest runtime/execution boundary",
                      out["basis"]["reason"])

    def test_d_complete_without_mechanism_is_unresolved(self):
        ladder = {length: "var" for length in D.ARM_D_LADDER_LENGTHS}
        ladder[1024] = "det"
        # plain final-remainder progress everywhere -> no predicate
        # fires (wall-clock-sampled rungs are not geometry evidence)
        progress = {length: [
            "prompt processing, n_tokens = 512",
            "prompt processing, n_tokens = 1024"] for length in ladder}
        f = self._fixture(arm_a_rows="vary", arm_b_fresh="vary",
                          arm_b_same="vary", arm_c_default="vary",
                          arm_c_serial="vary",
                          arm_c2_gate=True, arm_d_rows=ladder,
                          arm_d_progress=progress)
        out = f.derive()
        self.assertEqual(out["terminal"], T.UNRESOLVED, out.get("problems"))
        self.assertIn("no smallest runtime/execution boundary",
                      out["basis"]["reason"])

    def test_missing_required_arm_b_is_blocked(self):
        # A varies but NO arm B evidence exists at all
        import shutil
        f = self._fixture(arm_a_rows="vary")
        shutil.rmtree(f.evidence / "d250-arm-b")
        out = f.derive()
        self.assertIsNone(out["terminal"])
        self.assertEqual(out["blocked"], T.BLOCKED)

    def test_missing_required_arm_c_is_blocked(self):
        import shutil
        f = self._fixture(arm_a_rows="vary", arm_b_fresh="vary",
                          arm_b_same="vary")
        shutil.rmtree(f.evidence / "d250-arm-c")
        out = f.derive()
        self.assertIsNone(out["terminal"])
        self.assertEqual(out["blocked"], T.BLOCKED)

    def test_missing_required_arm_d_is_blocked(self):
        import shutil
        f = self._fixture(arm_a_rows="vary", arm_b_fresh="vary",
                          arm_b_same="vary", arm_c_default="vary",
                          arm_c_serial="vary")
        arm_d = f.evidence / "d250-arm-d"
        if arm_d.is_dir():
            shutil.rmtree(arm_d)
        out = f.derive()
        self.assertIsNone(out["terminal"])
        self.assertEqual(out["blocked"], T.BLOCKED)

    def test_incomplete_arm_a_below_claim_threshold_is_blocked(self):
        # 5 units but two share a seed and three differ is "vary"...
        # construct BELOW-threshold: delete units so n < 5 with
        # identical rows (cannot claim deterministic with 3)
        import shutil
        f = self._fixture(arm_a_rows="det")
        base = f.evidence / "d250-arm-a"
        for tag in ("case-3072-B-devnone-004",
                    "case-3072-B-devnone-005"):
            shutil.rmtree(base / tag)
        out = f.derive()
        self.assertIsNone(out["terminal"])
        self.assertEqual(out["blocked"], T.BLOCKED)

    def test_cpu_only_variation_requires_b_not_unresolved(self):
        # OLD DEFECT: CPU-only varying prematurely returned UNRESOLVED.
        f = self._fixture(arm_a_rows="vary", arm_b_fresh="vary",
                          arm_b_same="deterministic")
        out = f.derive()
        # with B evidence present the walk localizes at B — the
        # premature-UNRESOLVED path is gone
        self.assertEqual(out["terminal"], T.LOCALIZED)
        # and with B evidence REMOVED the result is BLOCKED, never
        # UNRESOLVED
        import shutil
        shutil.rmtree(f.evidence / "d250-arm-b")
        out2 = f.derive()
        self.assertNotEqual(out2["terminal"], T.UNRESOLVED)
        self.assertEqual(out2["blocked"], T.BLOCKED)

    def test_unreachable_later_arm_cannot_override_earlier(self):
        # A localizes. Synthesize adversarial later-arm records rather
        # than invoking a producer whose sequential gate correctly
        # refuses unreachable B/C/D. If the reducer scans them, their
        # deliberately contradictory claims must fail closed; otherwise
        # they cannot override verified A.
        f = self._fixture(arm_a_rows="det", arm_b_fresh="vary",
                          arm_b_same="vary", arm_c_default="vary",
                          arm_c_serial="vary",
                          arm_c2_gate=True)
        for namespace, arm in (
                ("d250-arm-b", "B-process-init"),
                ("d250-arm-c", "C-cpu-threads"),
                ("d250-arm-c1", "C1-reduced-parallelism"),
                (D.C2_SERIAL_NAMESPACE, D.ARM_C2_NAME),
                ("d250-arm-d", "D-context-transition")):
            claimed = f.evidence / namespace / "unreachable-adversarial"
            claimed.mkdir(parents=True)
            (claimed / "unit.json").write_text(json.dumps({
                "namespace": namespace, "arm": arm,
                "terminal": T.UNRESOLVED,
                "authority": make_authority(namespace, arm, head=f.head),
            }))
            self.assertTrue((claimed / "unit.json").is_file())
        out = f.derive()
        self.assertEqual(out["terminal"], T.LOCALIZED)
        self.assertIn("backend-participation",
                      out["basis"]["localized_factor"])
        # the unreachable arms were never consumed
        self.assertNotIn("B-process-init", out["arms"])

    def test_contradictory_b_fresh_deterministic_fails_closed(self):
        # A varied; B fresh is deterministic — contradiction
        f = self._fixture(arm_a_rows="vary", arm_b_fresh="det",
                          arm_b_same="det")
        out = f.derive()
        self.assertIsNone(out["terminal"])
        self.assertEqual(out["blocked"], T.BLOCKED)
        self.assertTrue(any("contradictory" in p for p in out["problems"]))

    def test_caller_supplied_terminal_is_not_an_input(self):
        f = self._fixture(arm_a_rows="vary")
        import inspect
        params = inspect.signature(T.derive_terminal).parameters
        for banned in ("reduction", "terminal", "deterministic",
                       "localized_factor", "condition_summary"):
            self.assertNotIn(banned, params)

    def test_no_terminal_without_authority(self):
        f = self._fixture(arm_a_rows="det")

        def no_authority(repo_root, expected_head, ns, github_api=None):
            raise D.DiagnosticError("fetch refused")
        out = f.derive(authority_fetcher=no_authority)
        self.assertIsNone(out["terminal"])
        self.assertEqual(out["blocked"], T.BLOCKED)

    def test_wrong_namespace_authority_fails_closed(self):
        f = self._fixture(arm_a_rows="det")

        def wrong(repo_root, expected_head, ns, github_api=None):
            # arm-C authority presented for the arm-A namespace
            return make_authority("d250-arm-c", "C-cpu-threads",
                                  head=expected_head)
        out = f.derive(authority_fetcher=wrong)
        self.assertIsNone(out["terminal"])
        self.assertEqual(out["blocked"], T.BLOCKED)


class CustodyMutationTests(unittest.TestCase):
    """One-field tampering on a valid retained tree fails closed."""

    def _fixture(self, **kw):
        fixture = CampaignFixture(self, **kw)
        self.addCleanup(fixture.restore_contrast_constant)
        return fixture

    def _receipt_path(self, f, tag):
        return f.evidence / "d250-arm-a" / tag / "unit.json"

    def _mutate_receipt(self, f, tag, mutate):
        path = self._receipt_path(f, tag)
        receipt = json.loads(path.read_bytes())
        mutate(receipt)
        # keep internal digest fields consistent where the mutation
        # targets semantics rather than digests
        path.write_bytes(
            (json.dumps(receipt, indent=2, sort_keys=True) + "\n")
            .encode())

    def test_row_bytes_mutation_detected(self):
        f = self._fixture(arm_a_rows="det")
        row = (f.evidence / "d250-arm-a" /
               "case-3072-B-devnone-001" / "obs.row3.f32")
        data = bytearray(row.read_bytes())
        data[0] ^= 0xFF
        row.write_bytes(bytes(data))
        out = f.derive()
        self.assertEqual(out["blocked"], T.BLOCKED)

    def test_authority_comment_substitution_detected(self):
        f = self._fixture(arm_a_rows="det")
        self._mutate_receipt(f, "case-3072-B-devnone-001", lambda r: r[
            "authority"].__setitem__("comment_id", 999999))
        out = f.derive()
        self.assertEqual(out["blocked"], T.BLOCKED)

    def test_head_substitution_detected(self):
        f = self._fixture(arm_a_rows="det")
        self._mutate_receipt(f, "case-3072-B-devnone-001", lambda r: r[
            "authority"].__setitem__("head_sha", "e" * 40))
        out = f.derive()
        self.assertEqual(out["blocked"], T.BLOCKED)

    def test_token_digest_forgery_detected(self):
        f = self._fixture(arm_a_rows="det")
        self._mutate_receipt(
            f, "case-3072-B-devnone-001",
            lambda r: r.__setitem__("deterministic_output_sha256",
                                    "f" * 64))
        out = f.derive()
        self.assertEqual(out["blocked"], T.BLOCKED)

    def test_argv_substitution_detected(self):
        f = self._fixture(arm_a_rows="det")
        self._mutate_receipt(
            f, "case-3072-B-devnone-001",
            lambda r: (r.__setitem__("argv_delta", ["-t", "1"]),
                       r["unit"].__setitem__("argv_delta", ["-t", "1"])))
        out = f.derive()
        self.assertEqual(out["blocked"], T.BLOCKED)

    def test_contract_substitution_detected(self):
        f = self._fixture(arm_a_rows="det")
        self._mutate_receipt(
            f, "case-3072-B-devnone-001",
            lambda r: r.__setitem__(
                "request_contract", {**D.REQUEST_CONTRACT, "seed": 7}))
        out = f.derive()
        self.assertEqual(out["blocked"], T.BLOCKED)

    def test_unplanned_unit_detected(self):
        import shutil
        f = self._fixture(arm_a_rows="det")
        src = f.evidence / "d250-arm-a" / "case-3072-B-devnone-001"
        dst = f.evidence / "d250-arm-a" / "case-3072-B-devnone-006"
        shutil.copytree(src, dst)
        out = f.derive()
        self.assertEqual(out["blocked"], T.BLOCKED)
        self.assertTrue(any("unplanned" in p for p in out["problems"]))

    def test_missing_unit_detected(self):
        import shutil
        f = self._fixture(arm_a_rows="det")
        shutil.rmtree(f.evidence / "d250-arm-a" /
                      "case-3072-B-devnone-003")
        out = f.derive()
        self.assertEqual(out["blocked"], T.BLOCKED)

    def test_attestation_closing_mutation_detected(self):
        f = self._fixture(arm_a_rows="det")
        # remove the closing attestation entirely
        (f.evidence / P.MODEL_ATTESTATION_CLOSE_NAME).unlink()
        out = f.derive()
        self.assertEqual(out["blocked"], T.BLOCKED)

    def test_attestation_opening_digest_mutation_detected(self):
        f = self._fixture(arm_a_rows="det")
        path = f.evidence / P.MODEL_ATTESTATION_OPEN_NAME
        doc = json.loads(path.read_bytes())
        doc["members"][0]["sha256"] = "0" * 64
        path.write_bytes(
            (json.dumps(doc, indent=2, sort_keys=True) + "\n").encode())
        out = f.derive()
        self.assertEqual(out["blocked"], T.BLOCKED)


class ContrastMutationTests(unittest.TestCase):

    def _fixture(self, **kw):
        fixture = CampaignFixture(self, **kw)
        self.addCleanup(fixture.restore_contrast_constant)
        return fixture

    def test_valid_contrast_verifies(self):
        f = self._fixture(arm_a_rows="det")
        out = T.verify_historical_contrast(f.contrast_root)
        self.assertFalse(out["row_deterministic"])
        self.assertEqual(out["provenance"],
                         D.CONTRAST_PROVENANCE)

    def test_manifest_digest_mutation_detected(self):
        f = self._fixture(arm_a_rows="det")
        D.ACCEPTED_248_MANIFEST_SELF_DIGEST = "0" * 64
        try:
            with self.assertRaises(ValueError):
                T.verify_historical_contrast(f.contrast_root)
        finally:
            f.restore_contrast_constant()

    def test_contrast_row_mutation_detected(self):
        f = self._fixture(arm_a_rows="det")
        row = (f.contrast_root / D.CONTRAST_NAMESPACE /
               D.CONTRAST_UNITS[0] / "obs.row0.f32")
        data = bytearray(row.read_bytes())
        data[-1] ^= 0x01
        row.write_bytes(bytes(data))
        with self.assertRaises(ValueError):
            T.verify_historical_contrast(f.contrast_root)

    def test_contrast_head_substitution_detected(self):
        f = self._fixture(arm_a_rows="det")
        receipt_path = (f.contrast_root / D.CONTRAST_NAMESPACE /
                        D.CONTRAST_UNITS[0] / "unit.json")
        doc = json.loads(receipt_path.read_bytes())
        doc["authority"]["head_sha"] = "9" * 40
        receipt_path.write_bytes(
            (json.dumps(doc, indent=2, sort_keys=True) + "\n").encode())
        with self.assertRaises(ValueError):
            T.verify_historical_contrast(f.contrast_root)

    def test_contrast_deterministic_rows_destroy_comparison(self):
        # both contrast units carry identical rows: the retained
        # bytes contradict the accepted nondeterminism -> fail closed
        f = self._fixture(arm_a_rows="det")
        import hashlib
        seed = hashlib.sha256(b"identical").digest()
        for tag in D.CONTRAST_UNITS:
            for i in range(D.DECISIONS):
                row = (seed * (D.ROW_BYTES // len(seed) + 1)
                       )[:D.ROW_BYTES]
                (f.contrast_root / D.CONTRAST_NAMESPACE / tag /
                 f"obs.row{i}.f32").write_bytes(row)
        # rebuild the manifest to match mutated rows
        manifest_rows = []
        for tag in D.CONTRAST_UNITS:
            for i in range(D.DECISIONS):
                p = (f.contrast_root / D.CONTRAST_NAMESPACE / tag /
                     f"obs.row{i}.f32")
                manifest_rows.append(
                    f"{hashlib.sha256(p.read_bytes()).hexdigest()}  "
                    f"{D.CONTRAST_NAMESPACE}/{tag}/obs.row{i}.f32")
        # also fix the receipts' row digests so ONLY the derived
        # nondeterminism contradiction remains
        for tag in D.CONTRAST_UNITS:
            rp = (f.contrast_root / D.CONTRAST_NAMESPACE / tag /
                  "unit.json")
            doc = json.loads(rp.read_bytes())
            doc["observer_rows"] = [
                hashlib.sha256(
                    (f.contrast_root / D.CONTRAST_NAMESPACE / tag /
                     f"obs.row{i}.f32").read_bytes()).hexdigest()
                for i in range(D.DECISIONS)]
            rp.write_bytes(
                (json.dumps(doc, indent=2, sort_keys=True) + "\n")
                .encode())
            manifest_rows.append(
                f"{hashlib.sha256(rp.read_bytes()).hexdigest()}  "
                f"{D.CONTRAST_NAMESPACE}/{tag}/unit.json")
        manifest_text = "\n".join(sorted(set(manifest_rows))) + "\n"
        (f.contrast_root / "SHA256SUMS").write_text(manifest_text)
        D.ACCEPTED_248_MANIFEST_SELF_DIGEST = hashlib.sha256(
            manifest_text.encode()).hexdigest()
        try:
            with self.assertRaises(ValueError):
                T.verify_historical_contrast(f.contrast_root)
        finally:
            f.restore_contrast_constant()


class TransitionPredicateTests(unittest.TestCase):
    # CORRECTION PASS 4 (NO-GO 5851078451, blocker 3): the retired
    # _non_uniform_progress predicate (pass 2) AND the pass-3
    # midstream_ubatch_split signature are both UNSOUND — pinned
    # print_timings_pp gates progress lines on a 3s WALL-CLOCK
    # sample, so step sequences are timing artifacts with no
    # ubatch-boundary semantics. Both old-defect behaviors are
    # asserted as REMOVED; wall-clock progress can never select
    # LOCALIZED.

    def _fixture(self, **kw):
        fixture = CampaignFixture(self, **kw)
        self.addCleanup(fixture.restore_contrast_constant)
        return fixture

    def test_retired_non_uniform_progress_is_removed(self):
        self.assertFalse(hasattr(T, "_non_uniform_progress"))

    def test_midstream_split_signature_retired(self):
        # CORRECTION PASS 4 (NO-GO 5851078451, blocker 3) FLIPPED
        # ASSERTION: _midstream_split_signature previously returned
        # True for the retained #248 case-3072 shape (midstream
        # 5-token step 2560->2565 with continuation). The predicate is
        # RETIRED — wall-clock-sampled progress counts cannot identify
        # ubatch boundaries — so the function is a fail-closed stub
        # returning False for EVERY input, including the old
        # signature-bearing shapes.
        self.assertFalse(T._midstream_split_signature(
            [512, 1024, 1536, 2048, 2560, 2565, 3073]))
        # ordinary final remainder shape: also False (no causal claim)
        self.assertFalse(T._midstream_split_signature(
            [512, 1024, 1536, 2048, 2560, 3068]))
        self.assertFalse(T._midstream_split_signature([512, 1024]))
        self.assertFalse(T._midstream_split_signature([100]))
        self.assertFalse(T._midstream_split_signature([]))
        # noisy/sparse arbitrary wall-clock samples: no causal claim
        self.assertFalse(T._midstream_split_signature(
            [512, 700, 715, 1536, 1537, 3073]))
        self.assertFalse(T._midstream_split_signature(
            [5, 480, 491, 1003, 1004, 2049, 2050, 3073]))
        self.assertFalse(T._midstream_split_signature(
            [512, 517, 1024, 1029, 1536]))

    def test_arbitrary_wall_clock_progress_cannot_localize(self):
        # REQUIRED CONTROL (NO-GO 5851078451, blocker 3): arbitrary
        # wall-clock progress sequences with sub-512 MIDSTREAM
        # sampled deltas can never select LOCALIZED. Drive the full
        # reducer with a ladder whose only distinguishing evidence is
        # progress shape (no token-count crossing) — the terminal is
        # UNRESOLVED, not LOCALIZED.
        ladder = {1024: "det", 1536: "det", 2048: "det", 2304: "det",
                  2560: "det", 3072: "var"}
        # every length carries a midstream sub-512 sampled delta —
        # under the retired predicate this shape was "signature"
        # evidence; it must carry no causal weight now.
        progress = {length: [
            "prompt processing, n_tokens = 512",
            "prompt processing, n_tokens = 517",
            "prompt processing, n_tokens = 1024",
            "prompt processing, n_tokens = 1029",
            "prompt processing, n_tokens = 1536",
            "prompt processing, n_tokens = 1541",
        ] for length in ladder}
        f = self._fixture(arm_a_rows="vary", arm_b_fresh="vary",
                          arm_b_same="vary", arm_c_default="vary",
                          arm_c_serial="vary",
                          arm_c2_gate=True, arm_d_rows=ladder,
                          arm_d_progress=progress)
        out = f.derive()
        self.assertEqual(out["terminal"], T.UNRESOLVED, out.get("problems"))

    def test_predicates_are_frozen(self):
        # CORRECTION PASS 4 (blocker 3): midstream_ubatch_split is
        # REMOVED from the frozen predicate vocabulary.
        self.assertEqual(
            sorted(T.TRANSITION_PREDICATES),
            ["indexer_top_k_boundary"])
        for spec in T.TRANSITION_PREDICATES.values():
            self.assertTrue(spec["requires"])
            self.assertTrue(spec["binds"])
        # retired predicate names must not silently return
        self.assertNotIn("checkpoint_resegmentation",
                         T.TRANSITION_PREDICATES)
        self.assertNotIn("ubatch_geometry_split",
                         T.TRANSITION_PREDICATES)
        self.assertNotIn("midstream_ubatch_split",
                         T.TRANSITION_PREDICATES)

    def test_localized_factors_frozen(self):
        self.assertEqual(
            sorted(T.LOCALIZED_FACTORS),
            ["A-vulkan-necessity", "B-process-init", "C-cpu-threads",
             "C1-reduced-parallelism", "C2-serial",
             "D-context-transition"])


class IndexerBoundaryEqualityTests(unittest.TestCase):
    """CORRECTION PASS 5 (NO-GO 5852014883): the exact source
    arithmetic of the indexer top-k selection-width execution
    boundary, at and around equality.

    Pinned runtime law (src/models/qwen4exp.cpp build_qsa_top_k):
    width = min(n_kv, indexer_top_k + r - 1) = min(n_kv, 2051) for
    top_k=2048, r=4. At n_kv = 2051 the width EQUALS the population
    (every cell still selected — all-cells/dense-equivalent side);
    the first population where selection can exclude a cell is
    n_kv = 2052. The old predicate encoded the selective transition
    as ">= 2051" — wrong at equality — and is retained here as an
    explicit old-defect regression (test E).
    """

    def _fixture(self, **kw):
        fixture = CampaignFixture(self, **kw)
        self.addCleanup(fixture.restore_contrast_constant)
        return fixture

    def _ladder_progress(self):
        return {length: [
            "prompt processing, n_tokens = 512",
            "prompt processing, n_tokens = 1024",
        ] for length in D.ARM_D_LADDER_LENGTHS}

    # --- exact source arithmetic (cases A/B/C + law) ---

    def test_source_arithmetic_constants(self):
        self.assertEqual(D.INDEXER_TOP_K, 2048)
        self.assertEqual(D.INDEXER_COMPRESS_RATIO, 4)
        self.assertEqual(D.INDEXER_TOPK_WIDTH,
                         D.INDEXER_TOP_K + D.INDEXER_COMPRESS_RATIO - 1)
        self.assertEqual(D.INDEXER_ALL_CELLS_MAX, 2051)
        self.assertEqual(D.INDEXER_SELECTIVE_MIN, 2052)
        self.assertEqual(D.INDEXER_SELECTIVE_MIN,
                         D.INDEXER_ALL_CELLS_MAX + 1)
        # the law itself, at the three decisive populations
        width = lambda n_kv: min(n_kv, D.INDEXER_TOPK_WIDTH)  # noqa: E731
        self.assertEqual(width(2050), 2050)   # all-cells
        self.assertEqual(width(2051), 2051)   # STILL all-cells (== n_kv)
        self.assertEqual(width(2052), 2051)   # first width < population
        self.assertLess(width(2052), 2052)

    def test_evaluate_predicate_direct_2050_2051_2052(self):
        # Direct unit-level exercise of the reducer predicate on
        # ladder-fact dictionaries (the same shape derive_terminal
        # builds): cases A (2050), B (2051), C (2052).
        def facts(det_count, var_count):
            return {
                1024: {"row_deterministic": True, "unit_count": 5,
                       "prompt_progress_counts": [], "pair_identical":
                       True, "deterministic_confirmed": True,
                       "actual_token_count": det_count},
                2048: {"row_deterministic": False, "unit_count": 2,
                       "prompt_progress_counts": [], "pair_identical":
                       False, "deterministic_confirmed": False,
                       "actual_token_count": var_count},
            }

        # B: variable side at exactly 2051 — STILL all-cells; the
        # selective-side predicate MUST NOT be satisfied
        out = T._evaluate_transition_predicates(facts(1534, 2051))
        self.assertIsNone(out)
        # E (incorrect equality case): deterministic < 2051 and
        # variable exactly 2051 — MUST NOT fire
        out = T._evaluate_transition_predicates(facts(1534, 2051))
        self.assertIsNone(out)
        # A: 2050 on the variable side is all-cells; no localization
        out = T._evaluate_transition_predicates(facts(1534, 2050))
        self.assertIsNone(out)
        # C: 2052 is the first selective-side count — predicate fires
        out = T._evaluate_transition_predicates(facts(1534, 2052))
        self.assertIsNotNone(out)
        self.assertEqual(out["predicate"], "indexer_top_k_boundary")
        self.assertEqual(out["all_cells_max"], 2051)
        self.assertEqual(out["selective_min"], 2052)
        # D: boundary det=2051 / var=2052 — det 2051 is on the
        # all-cells side, so the predicate MAY fire
        out = T._evaluate_transition_predicates(facts(2051, 2052))
        self.assertIsNotNone(out)
        self.assertEqual(out["boundary_actual_tokens"], (2051, 2052))

    def test_det_side_2052_is_not_all_cells(self):
        # deterministic side at 2052 (selective side) cannot satisfy
        # the all-cells-side requirement — no fire
        def facts(det_count, var_count):
            return {
                1024: {"row_deterministic": True, "unit_count": 5,
                       "prompt_progress_counts": [], "pair_identical":
                       True, "deterministic_confirmed": True,
                       "actual_token_count": det_count},
                2048: {"row_deterministic": False, "unit_count": 2,
                       "prompt_progress_counts": [], "pair_identical":
                       False, "deterministic_confirmed": False,
                       "actual_token_count": var_count},
            }
        self.assertIsNone(T._evaluate_transition_predicates(
            facts(2052, 2053)))

    # --- full-reducer equality regressions (retained-byte path) ---

    def test_variable_side_exactly_2051_cannot_localize(self):
        # OLD-DEFECT REGRESSION (equality at 2051): the pass-4
        # reducer accepted a variable-side actual count of exactly
        # 2051 as being on the selective side (>= 2051) and emitted
        # LOCALIZED. At equality width = min(2051, 2051) = 2051
        # covers the FULL population, so 2051 is all-cells and the
        # corrected head MUST end UNRESOLVED for this evidence.
        ladder = {1024: "det", 1536: "det", 2048: "var", 2304: "var",
                  2560: "var", 3072: "var"}
        counts = {2048: 2051}  # only the first variable length moves
        f = self._fixture(arm_a_rows="vary", arm_b_fresh="vary",
                          arm_b_same="vary", arm_c_default="vary",
                          arm_c_serial="vary",
                          arm_c2_gate=True, arm_d_rows=ladder,
                          arm_d_progress=self._ladder_progress(),
                          arm_d_token_counts=counts)
        out = f.derive()
        self.assertEqual(out["terminal"], T.UNRESOLVED, out.get("problems"))
        self.assertIn("no smallest runtime/execution boundary",
                      out["basis"]["reason"])

    def test_det_boundary_side_at_exactly_2051_can_localize(self):
        # D: deterministic actual 2051 / variable actual 2052+ — the
        # deterministic side sits ON the all-cells maximum, all other
        # frozen D gates satisfied, so the predicate MAY fire.
        ladder = {1024: "det", 1536: "det", 2048: "det", 2304: "var",
                  2560: "var", 3072: "var"}
        counts = {2048: 2051}  # last deterministic length at the max
        f = self._fixture(arm_a_rows="vary", arm_b_fresh="vary",
                          arm_b_same="vary", arm_c_default="vary",
                          arm_c_serial="vary",
                          arm_c2_gate=True, arm_d_rows=ladder,
                          arm_d_progress=self._ladder_progress(),
                          arm_d_token_counts=counts)
        out = f.derive()
        self.assertEqual(out["terminal"], T.LOCALIZED, out.get("problems"))
        self.assertEqual(out["basis"]["transition_predicate"],
                         "indexer_top_k_boundary")
        self.assertEqual(out["basis"]["mechanism"]["binds"].count(
            "2051"), 2)

    def test_real_ladder_1534_to_2053_still_fires(self):
        # F: real prospective ladder example — deterministic side
        # actual count 1534, variable side actual count 2053; the
        # predicate still fires when all confirmation/gating
        # conditions are satisfied (the default fixture counts).
        ladder = {1024: "det", 1536: "det", 2048: "var", 2304: "var",
                  2560: "var", 3072: "var"}
        f = self._fixture(arm_a_rows="vary", arm_b_fresh="vary",
                          arm_b_same="vary", arm_c_default="vary",
                          arm_c_serial="vary",
                          arm_c2_gate=True, arm_d_rows=ladder,
                          arm_d_progress=self._ladder_progress())
        out = f.derive()
        self.assertEqual(out["terminal"], T.LOCALIZED, out.get("problems"))
        self.assertEqual(out["basis"]["transition_predicate"],
                         "indexer_top_k_boundary")
        self.assertEqual(out["basis"]["boundary"], (1536, 2048))
        # boundary actuals under the default fixture counts
        self.assertEqual(out["basis"]["boundary_actual_tokens"],
                         (1534, 2053))

    def test_all_counts_below_or_equal_2051_no_localization(self):
        # G: every ladder count on the all-cells side (<= 2051) —
        # the ladder varies, but no deterministic->selective
        # crossing exists, so no localization.
        ladder = {1024: "det", 1536: "det", 2048: "var", 2304: "var",
                  2560: "var", 3072: "var"}
        counts = {2048: 2051, 2304: 2049, 2560: 2050, 3072: 2051}
        f = self._fixture(arm_a_rows="vary", arm_b_fresh="vary",
                          arm_b_same="vary", arm_c_default="vary",
                          arm_c_serial="vary",
                          arm_c2_gate=True, arm_d_rows=ladder,
                          arm_d_progress=self._ladder_progress(),
                          arm_d_token_counts=counts)
        out = f.derive()
        self.assertEqual(out["terminal"], T.UNRESOLVED, out.get("problems"))
        self.assertIn("no smallest runtime/execution boundary",
                      out["basis"]["reason"])

    def test_all_counts_selective_no_crossing(self):
        # H: every count >= 2052 (all selective side) — no
        # deterministic->selective crossing; no localization.
        ladder = {1024: "det", 1536: "det", 2048: "var", 2304: "var",
                  2560: "var", 3072: "var"}
        counts = {1024: 2052, 1536: 2054, 2048: 2053, 2304: 2060,
                  2560: 2070, 3072: 3077}
        f = self._fixture(arm_a_rows="vary", arm_b_fresh="vary",
                          arm_b_same="vary", arm_c_default="vary",
                          arm_c_serial="vary",
                          arm_c2_gate=True, arm_d_rows=ladder,
                          arm_d_progress=self._ladder_progress(),
                          arm_d_token_counts=counts)
        out = f.derive()
        self.assertEqual(out["terminal"], T.UNRESOLVED, out.get("problems"))
        self.assertIn("no smallest runtime/execution boundary",
                      out["basis"]["reason"])

    def test_non_monotone_boundary_no_localization(self):
        # I: interleaved/non-monotone determinism (a variable length
        # below a deterministic one in ladder order) — the monotone
        # deterministic->variable boundary does not exist; no
        # localization regardless of counts.
        ladder = {1024: "det", 1536: "var", 2048: "det", 2304: "var",
                  2560: "var", 3072: "var"}
        f = self._fixture(arm_a_rows="vary", arm_b_fresh="vary",
                          arm_b_same="vary", arm_c_default="vary",
                          arm_c_serial="vary",
                          arm_c2_gate=True, arm_d_rows=ladder,
                          arm_d_progress=self._ladder_progress())
        out = f.derive()
        self.assertEqual(out["terminal"], T.UNRESOLVED, out.get("problems"))
        self.assertIn("no smallest runtime/execution boundary",
                      out["basis"]["reason"])

    def test_nominal_label_irrelevant_against_actual_count(self):
        # J: the nominal label 2048 is irrelevant when the ACTUAL
        # token count sits on the other side of the boundary. A
        # length NOMINALLY labeled 2048 whose actual count is 2051
        # is all-cells (not selective) — and one whose actual count
        # is 2052 IS selective despite the same nominal label.
        # (Covers both label!=count directions at the boundary.)
        ladder = {1024: "det", 1536: "det", 2048: "var", 2304: "var",
                  2560: "var", 3072: "var"}
        counts = {2048: 2052}  # nominal 2048, ACTUAL 2052: selective
        f = self._fixture(arm_a_rows="vary", arm_b_fresh="vary",
                          arm_b_same="vary", arm_c_default="vary",
                          arm_c_serial="vary",
                          arm_c2_gate=True, arm_d_rows=ladder,
                          arm_d_progress=self._ladder_progress(),
                          arm_d_token_counts=counts)
        out = f.derive()
        self.assertEqual(out["terminal"], T.LOCALIZED, out.get("problems"))
        self.assertEqual(out["basis"]["transition_predicate"],
                         "indexer_top_k_boundary")
        # boundary actuals: nominal-2048 length judged by its ACTUAL
        # 2052, not its label
        self.assertEqual(out["basis"]["boundary_actual_tokens"],
                         (1534, 2052))

    def test_localized_wording_names_execution_boundary(self):
        # the terminal interpretation stays narrow: the localized
        # factor names the QSA all-cells -> selective-mask execution
        # boundary, not an ultimate numerical root cause
        ladder = {1024: "det", 1536: "det", 2048: "var", 2304: "var",
                  2560: "var", 3072: "var"}
        f = self._fixture(arm_a_rows="vary", arm_b_fresh="vary",
                          arm_b_same="vary", arm_c_default="vary",
                          arm_c_serial="vary",
                          arm_c2_gate=True, arm_d_rows=ladder,
                          arm_d_progress=self._ladder_progress())
        out = f.derive()
        self.assertEqual(out["terminal"], T.LOCALIZED, out.get("problems"))
        self.assertEqual(out["basis"]["arm"], "D-context-transition")
        self.assertIn("execution-path transition",
                      out["basis"]["localized_factor"])
        self.assertIn("frozen transition predicate",
                      out["basis"]["localized_factor"])


if __name__ == "__main__":
    unittest.main()
