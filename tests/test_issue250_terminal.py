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
P = _load("issue250_physical", "scripts/issue250_physical.py")
T = _load("issue250_terminal", "scripts/issue250_terminal.py")

HEAD = "d" * 40
TOKENS = [328, 760, 324, 55965, 51624, 29014, 34227, 18030]
PROMPT_TOKENS = 3077


def make_authority(namespace, arm, head=HEAD, comment_id=1):
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


class CampaignFixture:
    """Builds a COMPLETE valid #250 evidence tree through the REAL
    producer paths (fake runners), plus the accepted #248 contrast
    tree at its frozen shape."""

    def __init__(self, test, *, arm_a_rows="vary", arm_b_fresh="vary",
                 arm_b_same="deterministic", arm_c_default="vary",
                 arm_c_serial="deterministic", arm_d_rows=None,
                 arm_d_progress=None):
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

        self.authorities = {}
        self._build_arm_a(arm_a_rows)
        self._build_arm_b(arm_b_fresh, arm_b_same)
        self._build_arm_c(arm_c_default, arm_c_serial)
        self._build_arm_d(arm_d_rows, arm_d_progress)
        self._build_contrast()

    def _restore(self):
        D.SERVER_BINARIES.update(self.saved_binaries)
        D.MODEL_DIR = self.saved_model_dir

    # ---------------- authority ----------------
    def authority_fn(self, namespace, arm):
        base = make_authority(namespace, arm, head=self.head)

        def fetch(repo_root, expected_head, ns, github_api=None):
            if ns != namespace:
                raise D.DiagnosticError(
                    f"no dispatch authority for namespace {ns}")
            return dict(base)
        return fetch

    def fetch_all(self):
        """An authority fetcher map for every built namespace."""
        by_ns = {}

        def fetch(repo_root, expected_head, ns, github_api=None):
            if ns not in by_ns:
                raise D.DiagnosticError(
                    f"no dispatch authority for namespace {ns}")
            return dict(by_ns[ns])
        for ns, arm in (("d250-arm-a", "A-vulkan-necessity"),
                        ("d250-arm-b", "B-process-init"),
                        ("d250-arm-c", "C-cpu-threads"),
                        ("d250-arm-d", "D-context-transition")):
            base = make_authority(ns, arm, head=self.head)
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

    def fake_execute(self, seed_key, progress_lines=None):
        def execute(argv, env, request, prompt, port, unit_dir):
            self._write_rows(unit_dir, seed_key)
            if progress_lines is not None:
                (unit_dir / "server.log").write_text(
                    "\n".join(progress_lines) + "\n")
            else:
                (unit_dir / "server.log").write_text(
                    "slot print_timing: prompt eval time = 1.0 ms / "
                    f"{PROMPT_TOKENS} tokens\n")
            now = utcnow()
            return {
                "returncode": 0, "tokens": list(TOKENS),
                "response_raw": json.dumps(
                    {"tokens": TOKENS}).encode(),
                "process_attribution": {
                    "server_pid": 4000 + abs(hash(seed_key)) % 100,
                    "server_exe_sha256": D.SERVER_BINARIES["comparator"],
                    "server_argv": list(argv), "server_env": dict(env)},
                "device_samples": [
                    {"stage": s, "captured_at": now,
                     "nvidia_smi_raw":
                         "GPU-d5c05739-96c1-7e49-89b6-"
                         "bf54c2121c55, 42.0, 140.0, 170.0, 0\n"}
                    for s in ("before", "during", "after")],
            }
        return execute

    def _run_unit(self, namespace, arm, tag, seed_key,
                  progress_lines=None):
        P.run_diagnostic_unit(
            repo_root=self.repo, evidence_root=self.evidence,
            namespace=namespace, arm=arm, tag=tag,
            binary=self.bin, binary_id="comparator",
            model_dir=self.model_dir, expected_head=self.head,
            model_attestation=self.attestation,
            execute=self.fake_execute(seed_key, progress_lines),
            identity_observer=lambda: raw_identity(),
            revalidate_authority=self.authority_fn(namespace, arm),
            health_runner=health_runner)

    def _build_arm_a(self, mode):
        plan = D.probe_list_for("A-vulkan-necessity")
        for i, spec in enumerate(plan):
            seed = (f"{spec['tag']}" if mode == "vary"
                    else f"arm-a-fixed") if mode != "vary" else (
                f"{spec['tag']}-varying")
            self._run_unit("d250-arm-a", "A-vulkan-necessity",
                           spec["tag"],
                           f"armA-{mode}-{i}" if mode == "vary"
                           else "armA-fixed")

    def _build_arm_b(self, fresh_mode, same_mode):
        for i, spec in enumerate(
                u for u in D.probe_list_for("B-process-init")
                if not u.get("same_process")):
            self._run_unit(
                "d250-arm-b", "B-process-init", spec["tag"],
                f"armB-fresh-{fresh_mode}-{i}"
                if fresh_mode == "vary" else "armB-fresh-fixed")
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
            revalidate_authority=self.authority_fn(
                "d250-arm-b", "B-process-init"),
            health_runner=health_runner)

    def _fake_same_process(self, mode):
        def execute(argv, env, request, prompt, port, unit_dir,
                    repeats, expected_prompt_tokens):
            import hashlib
            records = []
            now = utcnow()
            pid = 777
            for index in range(repeats):
                key = ("same-fixed" if mode == "deterministic"
                       else f"same-varying-{index}")
                seed = hashlib.sha256(key.encode()).digest()
                row_files = {}
                meta_lines = []
                for d in range(D.DECISIONS):
                    row = (seed * (D.ROW_BYTES // len(seed) + 1)
                           )[:D.ROW_BYTES]
                    row_files[f"obs.row{d}.f32"] = row
                    meta_lines.append(json.dumps(
                        {"pos": d, "sampled_winner": TOKENS[d]}))
                log_slice = (
                    f"slot get_availabl: id  3 | task {index} | "
                    f"selected slot by id (3)\n"
                    f"slot print_timing: id  3 | task {index} | prompt "
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
            }
        return execute

    def _build_arm_c(self, default_mode, serial_mode):
        for i, spec in enumerate(
                u for u in D.probe_list_for("C-cpu-threads")):
            serial = "thr1" in spec["tag"]
            mode = serial_mode if serial else default_mode
            self._run_unit(
                "d250-arm-c", "C-cpu-threads", spec["tag"],
                f"armC-{'serial' if serial else 'default'}-{mode}-{i}"
                if mode == "vary" else
                f"armC-{'serial' if serial else 'default'}-fixed")

    def _build_arm_d(self, rows_mode, progress):
        """rows_mode: None (no arm D) | dict length->'det'/'var'."""
        if rows_mode is None:
            return
        for spec in D.probe_list_for("D-context-transition"):
            length = spec["ladder_length"]
            tag = spec["tag"]
            mode = rows_mode[length]
            idx = tag.rsplit("-", 1)[1]
            progress_lines = (progress or {}).get(length, [
                "slot print_timing: prompt processing, n_tokens = 512",
                "slot print_timing: prompt processing, n_tokens = 1024",
            ])
            self._run_unit(
                "d250-arm-d", "D-context-transition", tag,
                f"armD-{length}-{mode}-{idx}"
                if mode == "var" else f"armD-{length}-det",
                progress_lines=progress_lines)

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
        return T.derive_terminal(**kw)


class TerminalMatrixTests(unittest.TestCase):
    """Every reachable path of the frozen sequential law."""

    def _fixture(self, **kw):
        fixture = CampaignFixture(self, **kw)
        # the contrast constant patch must be restored AFTER the
        # normal cleanup chain unwinds D.SERVER_BINARIES
        self.addCleanup(fixture.restore_contrast_constant)
        return fixture

    def test_a_localizes(self):
        f = self._fixture(arm_a_rows="det", arm_b_fresh=None or "vary",
                          arm_b_same="vary", arm_c_default="vary",
                          arm_c_serial="vary", arm_d_rows=None)
        out = f.derive()
        self.assertEqual(out["terminal"], T.LOCALIZED, out.get("problems"))
        self.assertIn("backend-participation",
                      out["basis"]["localized_factor"])

    def test_a_to_b_localizes(self):
        f = self._fixture(arm_a_rows="vary", arm_b_fresh="vary",
                          arm_b_same="deterministic")
        out = f.derive()
        self.assertEqual(out["terminal"], T.LOCALIZED, out.get("problems"))
        self.assertIn("fresh-process/runtime-initialization",
                      out["basis"]["localized_factor"])

    def test_a_to_b_to_c_localizes(self):
        f = self._fixture(arm_a_rows="vary", arm_b_fresh="vary",
                          arm_b_same="vary", arm_c_default="vary",
                          arm_c_serial="deterministic")
        out = f.derive()
        self.assertEqual(out["terminal"], T.LOCALIZED, out.get("problems"))
        self.assertIn("CPU parallel execution/order",
                      out["basis"]["localized_factor"])

    def test_a_to_b_to_c_to_d_localizes_with_predicate(self):
        ladder = {1024: "det", 1536: "det", 2048: "det", 2304: "det",
                  2560: "det", 3072: "det"}
        # make only 3072 variable and give lengths >=2304 the
        # non-uniform split geometry (ubatch predicate)
        ladder[3072] = "var"
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
                          arm_c_serial="vary", arm_d_rows=ladder,
                          arm_d_progress=progress)
        out = f.derive()
        self.assertEqual(out["terminal"], T.LOCALIZED, out.get("problems"))
        self.assertEqual(out["basis"]["transition_predicate"],
                         "ubatch_geometry_split")

    def test_d_complete_without_mechanism_is_unresolved(self):
        ladder = {length: "var" for length in D.ARM_D_LADDER_LENGTHS}
        ladder[1024] = "det"
        # uniform progress everywhere -> no predicate fires
        progress = {length: [
            "prompt processing, n_tokens = 512",
            "prompt processing, n_tokens = 1024"] for length in ladder}
        f = self._fixture(arm_a_rows="vary", arm_b_fresh="vary",
                          arm_b_same="vary", arm_c_default="vary",
                          arm_c_serial="vary", arm_d_rows=ladder,
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
        # A localizes; B/C/D evidence EXISTS but is unreachable
        ladder = {length: "var" for length in D.ARM_D_LADDER_LENGTHS}
        f = self._fixture(arm_a_rows="det", arm_b_fresh="vary",
                          arm_b_same="vary", arm_c_default="vary",
                          arm_c_serial="vary", arm_d_rows=ladder)
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

    def test_non_uniform_progress_detection(self):
        self.assertTrue(T._non_uniform_progress(
            [512, 1024, 1536, 2048, 2560, 2565, 3073]))
        self.assertFalse(T._non_uniform_progress([512, 1024]))
        self.assertFalse(T._non_uniform_progress([100]))

    def test_predicates_are_frozen(self):
        self.assertEqual(
            sorted(T.TRANSITION_PREDICATES),
            ["checkpoint_resegmentation", "indexer_top_k_boundary",
             "ubatch_geometry_split"])
        for spec in T.TRANSITION_PREDICATES.values():
            self.assertTrue(spec["requires"])
            self.assertTrue(spec["binds"])

    def test_localized_factors_frozen(self):
        self.assertEqual(
            sorted(T.LOCALIZED_FACTORS),
            ["A-vulkan-necessity", "B-process-init", "C-cpu-threads",
             "D-context-transition"])


if __name__ == "__main__":
    unittest.main()
