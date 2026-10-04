"""Issue #270 (R8-I6) — accepted-authority consumption and campaign
boundary tests (CPU-only, offline; zero physical execution).

Covers:
  * #243 retained-bytes candidate identity derivation == transcribed
    expectation (both directions fail closed);
  * accepted main-constant cross-bindings (pin/binaries/model/fixtures);
  * reference identity consumed from the accepted #248 module;
  * namespace/case discipline (predictive, threshold, holdout, case-4096
    all refused);
  * comparator/2 semantics re-declaration self-containment (no import
    of unmerged #242 modules) and pair/determinism/inertness validation
    on synthetic retained-byte fixtures;
  * Phase-0 reconciliation;
  * Phase-2 fresh-identity derivation and drift fail-closed;
  * dispatch authority (phrase/head/namespace/association) fail-closed.
"""
from __future__ import annotations

import ast
import copy
import hashlib
import json
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import issue270_authority as C  # noqa: E402
import issue270_comparator as comparator  # noqa: E402
import issue270_physical as P  # noqa: E402
import issue270_terminal as P_T  # noqa: E402


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def row_bytes(seed: bytes, *, finite: bool = True) -> bytes:
    """Deterministic full-vocab FP32 row with a fixed pattern."""
    n = C.N_VOCAB
    out = bytearray()
    for i in range(n):
        v = ((seed[i % len(seed)] + seed[(i // 7) % len(seed)]
              + i * 7) % 251 - 125) / 8.0
        out += struct.pack("<f", v)
    if not finite:
        out[:4] = struct.pack("<f", float("nan"))
    return bytes(out)


V340_VULKANINFO = """VULKANINFO
==========

Vulkan Instance Version: 1.4.309

Devices:
========
GPU0:
	apiVersion         = 1.4.305
	deviceName         = AMD Radeon Pro V340 (RADV VEGA10)
	driverID           = DRIVER_ID_MESA_RADV
	driverInfo         = Mesa 25.0.7-2+deb13u1
	deviceUUID         = 00000000-0700-0000-0000-000000000000
GPU1:
	apiVersion         = 1.4.305
	deviceName         = AMD Radeon Pro V340 (RADV VEGA10)
	driverID           = DRIVER_ID_MESA_RADV
	driverInfo         = Mesa 25.0.7-2+deb13u1
	deviceUUID         = 00000000-0b00-0000-0000-000000000000
GPU2:
	apiVersion         = 1.4.305
	deviceType         = PHYSICAL_DEVICE_TYPE_CPU
	deviceName         = llvmpipe (LLVM 19.1.7, 256 bits)
	driverID           = DRIVER_ID_MESA_LLVMPIPE
	driverInfo         = Mesa 25.0.7-2+deb13u1 (LLVM 19.1.7)
	deviceUUID         = 6d657361-3235-2e30-2e37-2d322b646500
"""


def synthetic_raw(observed_at: str = "2026-10-04T00:00:00Z") -> dict:
    return {
        "host": "inferswarm05",
        "uname": "6.12.107+deb13-amd64",
        "icd": {"path": C.RADV_ICD, "sha256": "a" * 64},
        "dies": {
            "0000:07:00.0": {
                "vendor": "1002", "device": "6864",
                "subsystem_vendor": "1002", "subsystem_device": "0c00",
                "revision": "0x05",
                "current_link_speed": "8.0 GT/s PCIe",
                "current_link_width": "16",
                "max_link_speed": "8.0 GT/s PCIe",
                "max_link_width": "16",
                "driver": "amdgpu", "drm_card": "card1",
                "mem_info_vram_total": "8573157376",
                "mem_info_vram_used": "8339456"},
            "0000:0b:00.0": {
                "vendor": "1002", "device": "6864",
                "subsystem_vendor": "1002", "subsystem_device": "0c00",
                "revision": "0x05",
                "current_link_speed": "8.0 GT/s PCIe",
                "current_link_width": "16",
                "max_link_speed": "8.0 GT/s PCIe",
                "max_link_width": "16",
                "driver": "amdgpu", "drm_card": "card2",
                "mem_info_vram_total": "8573157376",
                "mem_info_vram_used": "8339456"},
        },
        "vulkaninfo": {"rc": 0, "stdout": V340_VULKANINFO, "stderr": ""},
    }


class CandidateAuthorityTests(unittest.TestCase):
    def test_retained_census_derives_expected_identity(self):
        derived = C.validate_candidate_authority()
        self.assertEqual(derived["host"], "inferswarm05")
        self.assertEqual(derived["vendor_id"], "0x1002")
        self.assertEqual(derived["device_id"], "0x6864")
        self.assertEqual(derived["vram_total_bytes"], 8_573_157_376)
        self.assertEqual(sorted(derived["dies"]), sorted(C.DIE_BDFS))

    def test_tampered_census_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "census.json"
            doc = json.loads((REPO / C.R8I4_CENSUS_REL).read_bytes())
            doc["dies"]["card1"]["device"] = "9999"
            path.write_text(json.dumps(doc))
            with self.assertRaises(C.AuthorityError):
                C.validate_candidate_authority(path)

    def test_truncated_dram_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "census.json"
            doc = json.loads((REPO / C.R8I4_CENSUS_REL).read_bytes())
            doc["host"]["meminfo"] = "MemTotal:  1000 kB"
            path.write_text(json.dumps(doc))
            with self.assertRaises(C.AuthorityError):
                C.validate_candidate_authority(path)


class AcceptedMainBindingTests(unittest.TestCase):
    def test_runtime_and_model_authority_matches_accepted_main(self):
        self.assertEqual(C.LLAMA_SOURCE_PIN,
                         "b29c606e28a01b1bc8c1351026a0fa6e616bf6c4")
        self.assertEqual(C.COMPARATOR_SHA256,
                         "6f8b56bd44d116cdc691911f8a1131840f5c7a720133c05febe11e467c2636ad")
        self.assertEqual(C.CANONICAL_SHA256,
                         "21707f2568d80fb781b445cd472588e83501e1cc66dcf10885b286e34c02573e")
        self.assertEqual(len(C.OBSERVER_LIBS), 8)
        for digest in C.OBSERVER_LIBS.values():
            self.assertRegex(digest, r"^[0-9a-f]{64}$")
        self.assertEqual(C.MODEL_DIR, "/srv/models/qwen38-ud-iq1-s")
        self.assertEqual(len(C.MODEL_MEMBER_SHA256), 3)

    def test_request_contract_is_byte_exact_accepted(self):
        self.assertEqual(C.REQUEST_CONTRACT, {
            "cache_prompt": False, "n_predict": 8, "return_tokens": True,
            "samplers": ["top_k"], "seed": 0, "stream": False,
            "temperature": 0.0, "top_k": 1})

    def test_fixture_ladder_binding_matches_accepted_bytes(self):
        data = (REPO / C.FIXTURE_LADDER_REL).read_bytes()
        self.assertEqual(sha256(data), C.FIXTURE_LADDER_SHA256)
        fixtures = C.load_fixtures()
        self.assertEqual(sorted(fixtures),
                         ["case-1024", "case-256", "case-3072"])
        for case, fx in fixtures.items():
            self.assertEqual(len(fx["prompt_token_ids"]),
                             fx["rendered_length"])

    def test_case4096_never_authorizable(self):
        self.assertNotIn("case-4096", C.FIXTURE_CASES)
        self.assertIn("case-4096", C.PROHIBITED_CASES)
        with self.assertRaises(C.AuthorityError):
            C.validate_case("case-4096")


class ReferenceConsumptionTests(unittest.TestCase):
    def test_reference_identity_consumed_not_refrozen(self):
        ref = C.reference_identity()
        import issue248_identity as I
        frozen = I.frozen_identity("B")
        for field in C.REFERENCE_IDENTITY_FIELDS:
            self.assertEqual(ref[field], frozen[field], field)
        self.assertEqual(ref["host"], "inferswarm01")
        self.assertEqual(ref["gpu_uuid"],
                         "GPU-d5c05739-96c1-7e49-89b6-bf54c2121c55")


class DisciplineTests(unittest.TestCase):
    def test_valid_namespace_accepted(self):
        self.assertEqual(C.validate_namespace("c270-v340-comparator2"),
                         "c270-v340-comparator2")

    def test_forbidden_namespaces_rejected(self):
        for bad in ("c237-x", "d248-x", "c270-c237-x", "c270-threshold",
                    "c270-holdout", "c270-calibration", "c270-",
                    "c270-UPPER", "issue270", ""):
            with self.assertRaises(C.AuthorityError, msg=bad):
                C.validate_namespace(bad)

    def test_predictive_cases_rejected(self):
        for bad in ("c237-x", "h237-x", "p237-x", "case-4096", "case-999",
                    "case-2560", "", None):
            with self.assertRaises(C.AuthorityError, msg=str(bad)):
                C.validate_case(bad)


class SelfContainmentTests(unittest.TestCase):
    def test_no_import_of_unmerged_242_modules(self):
        """PR #242 was closed unmerged: importing issue241_* is illegal."""
        for module in ("issue270_authority.py", "issue270_comparator.py",
                       "issue270_physical.py"):
            source = (REPO / "scripts" / module).read_text()
            tree = ast.parse(source)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        self.assertFalse(alias.name.startswith("issue241"),
                                         f"{module} imports {alias.name}")
                elif isinstance(node, ast.ImportFrom):
                    self.assertFalse(
                        (node.module or "").startswith("issue241"),
                        f"{module} imports from {node.module}")

    def test_accepted_241_constants_are_historical_only(self):
        self.assertEqual(C.ACCEPTED_241_TERMINAL,
                         "R8I3_COMPARATOR_V2_BLOCKED")
        self.assertTrue(C.ACCEPTED_241_EVIDENCE_ROOT.startswith("inferswarm01"))


def make_arm_receipt(*, evidence: Path, root: Path, arm: str, case: str,
                     rows_seed: bytes, selected_bdf: str, host: str,
                     icd: str, selector: dict, excluded_bdfs: tuple,
                     pid: int, head: str, authority: dict,
                     argv_env: dict | None = None,
                     row_override: bytes | None = None,
                     claimed_digest: str | None = None,
                     declared_bytes: int | None = None,
                     winners: list[int] | None = None,
                     forced: list[int] | None = None,
                     meta_rows: list[dict] | None = None,
                     ) -> tuple[dict, dict]:
    """Build a synthetic-but-custody-real arm receipt.

    Rows are written as real files under the evidence root; the receipt
    paths are relative to it, digests computed from actual bytes. All
    mutations (digest flips, byte truncation, NaN rows) go through the
    file/field layers so the validator's custody path is exercised.
    """
    fixtures = C.load_fixtures(root)
    fx = fixtures[case]
    rows = {}
    case_dir = evidence / "rows" / case / arm
    case_dir.mkdir(parents=True, exist_ok=True)
    if winners is None:
        winners = [11 * (d + 1) for d in range(8)]
    if forced is None:
        forced = list(winners) if arm == "candidate" else [-1] * 8
    if meta_rows is None:
        meta_rows = [
            {"pos": d, "n_vocab": C.N_VOCAB,
             "sampled_winner": winners[d],
             "forced_token": (-1 if arm == "reference" else forced[d])}
            for d in range(8)]
    for d in range(8):
        data = row_override if row_override is not None else row_bytes(
            rows_seed + str(d).encode())
        rel = f"rows/{case}/{arm}/row{d}.f32"
        (evidence / rel).write_bytes(data)
        rows[str(d)] = {"path": rel, "bytes": declared_bytes or len(data),
                        "sha256": claimed_digest or sha256(data)}
    ngl = C.SELECTED_PLACEMENT_NGL
    model_member = C.MODEL_MEMBERS[0]
    argv = ["/srv/bin/llama-server", "--model",
            f"{C.MODEL_DIR}/{model_member}", "-ngl", str(ngl),
            "--ctx-size", "8192", "--batch-size", "512"]
    env = {"VK_ICD_FILENAMES": icd, **selector,
           "LLAMA_OBSERVE_CAPTURE": "8", "LLAMA_OBSERVE_OUT": "/tmp/obs",
           "LLAMA_OBSERVE_LOG": "/tmp/obs.log",
           **(argv_env or {})}
    subject = dict(C.reference_identity())
    subject.update({"bdf": selected_bdf, "host": host})
    receipt = {
        "schema": comparator.RUN_SCHEMA, "campaign": C.CAMPAIGN_ID,
        "comparator_id": C.COMPARATOR_V2_ID, "case_id": case,
        "host": host, "arm": arm, "selector": selector, "icd": icd,
        "cuda_visible_devices": "-1", "bdf": selected_bdf, "ngl": ngl,
        "subject_identity": subject,
        "fixture_ladder_sha256": C.FIXTURE_LADDER_SHA256,
        "prompt_token_ids": fx["prompt_token_ids"],
        "prompt_len": fx["rendered_length"],
        "prompt_text_sha256": sha256(fx["prompt_text"].encode()),
        "model_members": C.MODEL_MEMBER_SHA256,
        "llama_source_pin": C.LLAMA_SOURCE_PIN,
        "server_sha256": C.COMPARATOR_SHA256,
        "build_flags": ["-DGGML_VULKAN=ON", "-DGGML_CUDA=OFF"],
        "request_contract": C.REQUEST_CONTRACT,
        "excluded_device_residency_bytes": {bdf: 12288
                                            for bdf in excluded_bdfs},
        "process_attribution": {"server_pid": pid, "server_argv": argv,
                                "server_env": env},
        "dispatch_authority": authority,
        "sampled_winners": winners, "forced_tokens": forced,
        "meta_rows": meta_rows, "rows": rows,
        "_arm_const": {"selector": selector, "icd": icd, "bdf": selected_bdf,
                       "build_flags": ["-DGGML_VULKAN=ON",
                                       "-DGGML_CUDA=OFF"],
                       "excluded_bdfs": excluded_bdfs},
    }
    return receipt, rows


REFERENCE_SELECTOR = {"GGML_VK_VISIBLE_DEVICES": "0",
                      "CUDA_VISIBLE_DEVICES": "-1"}
CANDIDATE_SELECTOR = {"GGML_VK_VISIBLE_DEVICES": "0",
                      "CUDA_VISIBLE_DEVICES": "-1"}
SELECTED = "0000:07:00.0"
EXCLUDED = ("0000:0b:00.0",)


def make_authority(head: str, comment_id: int = 99001) -> dict:
    return {"schema": "inferswarm.issue270.dispatch-authority/1",
            "issue": 270, "pr_number": None, "comment_id": comment_id,
            "commenter": "ezutfen", "commenter_association": "MEMBER",
            "created_at": "2026-10-04T00:00:00Z", "head_sha": head,
            "namespace": "c270-v340-comparator2",
            "dispatch_phrase": C.DISPATCH_PHRASE}


class ComparatorValidationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "repo"
        self.evidence = Path(self.tmp.name) / "evidence"
        self.root.mkdir()
        (self.root / C.FIXTURE_LADDER_REL).parent.mkdir(parents=True)
        (self.root / C.FIXTURE_LADDER_REL).write_bytes(
            (REPO / C.FIXTURE_LADDER_REL).read_bytes())
        subprocess.run(["git", "init", "-q"], cwd=self.root, check=True)
        subprocess.run(["git", "config", "user.email", "t@t"], cwd=self.root,
                       check=True)
        subprocess.run(["git", "config", "user.name", "t"], cwd=self.root,
                       check=True)
        subprocess.run(["git", "add", "-A"], cwd=self.root, check=True)
        subprocess.run(["git", "commit", "-qm", "init"], cwd=self.root,
                       check=True)
        self.head = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=self.root, capture_output=True,
            text=True, check=True).stdout.strip()
        self.authority = make_authority(self.head)
        self.ref, self.ref_rows = make_arm_receipt(
            evidence=self.evidence, root=self.root, arm="reference",
            case="case-256", rows_seed=b"ref-a",
            selected_bdf="00000000:03:00.0", host="inferswarm01",
            icd=C.NVIDIA_ICD, selector=REFERENCE_SELECTOR,
            excluded_bdfs=(), pid=1001, head=self.head,
            authority=self.authority)
        self.cand, self.cand_rows = make_arm_receipt(
            evidence=self.evidence, root=self.root, arm="candidate",
            case="case-256", rows_seed=b"cand-a",
            selected_bdf=SELECTED, host="inferswarm05",
            icd=C.RADV_ICD, selector=CANDIDATE_SELECTOR,
            excluded_bdfs=EXCLUDED, pid=2001, head=self.head,
            authority=self.authority)
        self.reader = comparator.custody_row_reader(self.evidence)

    def mutate(self, receipt: dict, rows: dict, mutation: str) -> dict:
        r = copy.deepcopy(receipt)
        if mutation == "claim-digest-flip":
            r["rows"]["0"]["sha256"] = "0" * 64
        elif mutation == "declare-wrong-bytes":
            r["rows"]["0"]["bytes"] = C.ROW_BYTES - 4
        elif mutation == "row-path-traversal":
            r["rows"]["0"]["path"] = "../../etc/passwd"
        elif mutation == "row-path-absolute":
            r["rows"]["0"]["path"] = "/etc/passwd"
        elif mutation == "duplicate-decision":
            r["rows"]["1"] = dict(r["rows"]["0"])
            r["meta_rows"][1]["pos"] = 0
        elif mutation == "missing-decision":
            del r["rows"]["7"]
        elif mutation == "candidate-winner-contamination":
            r["sampled_winners"] = [424242] * 8
            r["forced_tokens"] = [424242] * 8
            for m in r["meta_rows"]:
                m["forced_token"] = 424242
        elif mutation == "wrong-ngl":
            r["ngl"] = 8
        elif mutation == "wrong-case":
            r["case_id"] = "case-4096"
            r["prompt_token_ids"] = [1, 2, 3]
            r["prompt_len"] = 3
        elif mutation == "cuda-participation":
            r["cuda_visible_devices"] = "0"
        elif mutation == "wrong-selector":
            r["selector"] = {"GGML_VK_VISIBLE_DEVICES": "1",
                             "CUDA_VISIBLE_DEVICES": "-1"}
        elif mutation == "wrong-model":
            r["model_members"] = dict(
                list(r["model_members"].items())[:2])
        elif mutation == "wrong-server-binary":
            r["server_sha256"] = "a" * 64
        elif mutation == "wrong-request-contract":
            r["request_contract"] = dict(r["request_contract"], top_k=2)
        elif mutation == "excluded-die-participation":
            r["excluded_device_residency_bytes"] = {EXCLUDED[0]: 1 << 30}
            r["_arm_const"]["excluded_bdfs"] = (EXCLUDED[0],)
        elif mutation == "wrong-dispatch":
            r["dispatch_authority"] = make_authority(
                self.head, comment_id=1)
            r["dispatch_authority"]["commenter_association"] = "CONTRIBUTOR"
        elif mutation == "stale-dispatch-head":
            r["dispatch_authority"] = make_authority("b" * 40)
        elif mutation == "wrong-host":
            r["host"] = "inferswarm99"
        elif mutation == "wrong-icd":
            r["icd"] = "/usr/share/vulkan/icd.d/other_icd.json"
        elif mutation == "pid-missing":
            del r["process_attribution"]["server_pid"]
        elif mutation == "argv-wrong-ngl":
            r["process_attribution"]["server_argv"] = [
                a for a in r["process_attribution"]["server_argv"]]
            r["process_attribution"]["server_argv"][
                r["process_attribution"]["server_argv"].index("-ngl") + 1] = "8"
        elif mutation == "nan-row":
            path = self.evidence / rows["3"]["path"]
            data = bytearray(path.read_bytes())
            data[:4] = struct.pack("<f", float("nan"))
            path.write_bytes(bytes(data))
            r["rows"]["3"]["sha256"] = sha256(bytes(data))
        elif mutation == "inf-row":
            path = self.evidence / rows["4"]["path"]
            data = bytearray(path.read_bytes())
            data[:4] = struct.pack("<f", float("inf"))
            path.write_bytes(bytes(data))
            r["rows"]["4"]["sha256"] = sha256(bytes(data))
        elif mutation == "row-bytes-mutation":
            path = self.evidence / rows["5"]["path"]
            data = bytearray(path.read_bytes())
            data[0:4] = b"\x01\x02\x03\x04"
            path.write_bytes(bytes(data))
        elif mutation == "force-before-capture-order":
            for m in r["meta_rows"]:
                m["sampled_winner"] = None
        elif mutation == "reference-forces-token":
            r["forced_tokens"] = list(r["sampled_winners"])
            for m in r["meta_rows"]:
                m["forced_token"] = m["sampled_winner"]
        elif mutation == "seven-rows":
            del r["rows"]["6"]
        elif mutation == "wrong-comparator-id":
            r["comparator_id"] = "inferswarm.qwen38-vulkan-comparator/1"
        elif mutation == "wrong-campaign":
            r["campaign"] = "issue241-r8i3-rx580-comparator-v2"
        else:
            raise AssertionError(f"unknown mutation {mutation}")
        return r

    def expect_pair_problem(self, mutation: str, fragment: str):
        ref = self.mutate(self.ref, self.ref_rows, mutation)
        cand = self.cand
        result = comparator.validate_pair(ref, cand, self.reader,
                                          C.reference_identity())
        self.assertFalse(result["validated"], mutation)
        joined = json.dumps(result["problems"])
        self.assertIn(fragment, joined, (mutation, joined))

    def test_complete_pair_validates(self):
        result = comparator.validate_pair(self.ref, self.cand, self.reader,
                                          C.reference_identity())
        self.assertTrue(result["validated"], result["problems"])

    def test_mutation_matrix(self):
        cases = (
            ("claim-digest-flip", "row 0 digest mismatch"),
            ("declare-wrong-bytes", "row 0 bytes"),
            ("row-path-traversal", "traversal rejected"),
            ("row-path-absolute", "absolute row path rejected"),
            ("duplicate-decision", "meta rows are not exactly positions"),
            ("missing-decision", "row decisions != 8"),
            ("candidate-winner-contamination",
             "candidate meta row 0 forced_token != reference winner"),
            ("wrong-ngl", "ngl"),
            ("wrong-case", "not an authorized historical-excluded"),
            ("cuda-participation", "CUDA not fenced off"),
            ("wrong-selector", "selector drift"),
            ("wrong-model", "model member hashes"),
            ("wrong-server-binary", "accepted comparator binary"),
            ("wrong-request-contract", "request contract drift"),
            ("excluded-die-participation",
             "over the residency noise bound"),
            ("wrong-dispatch", "OWNER/MEMBER"),
            ("stale-dispatch-head",
             "must cross-bind to the same historical"),
            ("wrong-host", "arm host must be"),
            ("wrong-icd", "ICD drift"),
            ("pid-missing", "live server pid"),
            ("argv-wrong-ngl", "-ngl"),
            ("nan-row", "non-finite"),
            ("inf-row", "non-finite"),
            ("row-bytes-mutation", "digest mismatch"),
            ("reference-forces-token", "reference arm must not force"),
            ("wrong-comparator-id", "comparator id mismatch"),
            ("wrong-campaign", "campaign mismatch"),
        )
        for mutation, fragment in cases:
            with self.subTest(mutation=mutation):
                self.expect_pair_problem(mutation, fragment)

    def test_cross_binding_case_mismatch(self):
        ref = copy.deepcopy(self.ref)
        cand = copy.deepcopy(self.cand)
        cand["case_id"] = "case-1024"
        cand["prompt_token_ids"] = C.load_fixtures(
            self.root)["case-1024"]["prompt_token_ids"]
        cand["prompt_len"] = C.load_fixtures(
            self.root)["case-1024"]["rendered_length"]
        cand_rows, _ = make_arm_receipt(
            evidence=self.evidence, root=self.root, arm="candidate",
            case="case-1024", rows_seed=b"cand-b",
            selected_bdf=SELECTED, host="inferswarm05",
            icd=C.RADV_ICD, selector=CANDIDATE_SELECTOR,
            excluded_bdfs=EXCLUDED, pid=2002, head=self.head,
            authority=self.authority)
        cand["rows"] = cand_rows["rows"]
        result = comparator.validate_pair(ref, cand, self.reader,
                                          C.reference_identity())
        self.assertFalse(result["validated"])
        self.assertTrue(any("case mismatch" in p
                            for p in result["problems"]))

    def test_determinism_repeat_mismatch_detected_from_bytes(self):
        evidence2 = self.evidence.parent / "evidence-repeat-a"
        ref2, ref2_rows = make_arm_receipt(
            evidence=evidence2, root=self.root, arm="reference",
            case="case-256", rows_seed=b"ref-DIFFERENT",
            selected_bdf="00000000:03:00.0", host="inferswarm01",
            icd=C.NVIDIA_ICD, selector=REFERENCE_SELECTOR,
            excluded_bdfs=(), pid=1002, head=self.head,
            authority=self.authority)
        result = comparator.validate_determinism(
            self.ref, ref2, self.reader,
            comparator.custody_row_reader(evidence2))
        self.assertFalse(result["deterministic"])
        self.assertTrue(any("repeat rows differ" in p
                            for p in result["problems"]))

    def test_determinism_pass_on_identical_bytes(self):
        evidence3 = self.evidence.parent / "evidence-repeat-b"
        ref2, _ = make_arm_receipt(
            evidence=evidence3, root=self.root, arm="reference",
            case="case-256", rows_seed=b"ref-a",
            selected_bdf="00000000:03:00.0", host="inferswarm01",
            icd=C.NVIDIA_ICD, selector=REFERENCE_SELECTOR,
            excluded_bdfs=(), pid=1002, head=self.head,
            authority=self.authority)
        result = comparator.validate_determinism(
            self.ref, ref2, self.reader,
            comparator.custody_row_reader(evidence3))
        self.assertTrue(result["deterministic"], result["problems"])

    def test_inertness_requires_no_observer_output(self):
        ok = comparator.validate_inertness([1] * 8, [1] * 8,
                                           disabled_emitted_observer_output=False,
                                           canonical_emitted_observer_output=False)
        self.assertTrue(ok["inert"])
        bad = comparator.validate_inertness([1] * 8, [1] * 8,
                                            disabled_emitted_observer_output=True)
        self.assertFalse(bad["inert"])
        self.assertIn("emitted observer output", " ".join(bad["problems"]))

    def test_nan_row_rejected(self):
        bad = self.mutate(self.ref, self.ref_rows, "nan-row")
        result = comparator.validate_arm_receipt(
            bad, "reference", self.reader, C.reference_identity())
        self.assertFalse(result["valid"])
        self.assertTrue(any("non-finite" in p for p in result["problems"]))


class Phase0Tests(unittest.TestCase):
    def test_reconciliation_clean_at_starting_main(self):
        record = P.phase0_reconciliation(REPO, C.STARTING_MAIN)
        self.assertTrue(record["reconciled"], record["problems"])

    def test_reconciliation_records_main_drift_without_fatal(self):
        record = P.phase0_reconciliation(REPO, "f" * 40)
        self.assertFalse(record["reconciled"])
        self.assertTrue(any(p.startswith("origin/main advanced")
                            for p in record["problems"]))

    def test_reconciliation_fails_on_missing_holdout(self):
        # The sealed-holdout presence check must fail closed on a repo
        # root lacking the ciphertext (synthetic root).
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            root.mkdir()
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            with self.assertRaises(P.PhysicalError):
                P.phase0_reconciliation(root, C.STARTING_MAIN)


class Phase2IdentityTests(unittest.TestCase):
    def test_fresh_observation_matches_frozen(self):
        obs = {"schema": "x", "host": "inferswarm05",
               "raw": synthetic_raw(), "derived": None}
        derived = P.derive_v340_identity(obs["raw"])
        self.assertEqual(P.identity_problems_vs_frozen(derived), [])

    def test_wrong_host_rejected(self):
        with self.assertRaises(P.PhysicalError):
            P.observe_v340_host(
                sysfs_reader=lambda bdf, rel: "0",
                command_runner=lambda argv: "inferswarm99\n" if
                argv[0] == "hostname" else (_ for _ in ()).throw(
                    AssertionError(argv)),
                hostname="inferswarm99")

    def test_missing_second_die_rejected(self):
        raw = synthetic_raw()
        raw["vulkaninfo"]["stdout"] = V340_VULKANINFO.replace(
            "GPU1:", "GPUX:").split("GPUX:")[0]
        with self.assertRaises(P.PhysicalError):
            P.derive_v340_identity(raw)
        with self.assertRaises(P.PhysicalError):
            P.derive_v340_identity({"vulkaninfo": {"stdout": "junk"}})

    def test_uuid_drift_rejected(self):
        raw = synthetic_raw()
        raw["vulkaninfo"]["stdout"] = V340_VULKANINFO.replace(
            "00000000-0b00", "00000000-0c00")
        with self.assertRaises(P.PhysicalError):
            P.derive_v340_identity(raw)

    def test_kernel_drift_detected(self):
        raw = synthetic_raw()
        raw["uname"] = "6.1.0-999"
        derived = P.derive_v340_identity(raw)
        problems = P.identity_problems_vs_frozen(derived)
        self.assertTrue(any("kernel drift" in p for p in problems))

    def test_llvmpipe_never_counts_as_die(self):
        raw = synthetic_raw()
        derived = P.derive_v340_identity(raw)
        self.assertEqual(set(derived["dies"]), set(C.DIE_BDFS))

    def test_radv_uuid_decodes_bdf(self):
        self.assertEqual(C._bdf_from_radv_uuid(
            "00000000-0700-0000-0000-000000000000"), "0000:07:00.0")
        self.assertEqual(C._bdf_from_radv_uuid(
            "00000000-0b00-0000-0000-000000000000"), "0000:0b:00.0")
        self.assertIsNone(C._bdf_from_radv_uuid(
            "6d657361-3235-2e30-2e37-2d322b646500"))


class DispatchAuthorityTests(unittest.TestCase):
    def test_valid_dispatch_selected(self):
        comment = {"id": 99123, "user": {"login": "ezutfen"},
                   "author_association": "MEMBER",
                   "created_at": "2026-10-04T01:00:00Z",
                   "body": (f"{C.DISPATCH_PHRASE}\n"
                            f"head={'a' * 40}\n"
                            "namespace=c270-v340-comparator2\n")}
        doc = P._select_dispatch([comment], "a" * 40,
                                 "c270-v340-comparator2")
        self.assertEqual(doc["comment_id"], 99123)

    def test_stale_head_dispatch_refused(self):
        comment = {"id": 99123, "user": {"login": "ezutfen"},
                   "author_association": "MEMBER",
                   "created_at": "2026-10-04T01:00:00Z",
                   "body": (f"{C.DISPATCH_PHRASE}\n"
                            f"head={'b' * 40}\n"
                            "namespace=c270-v340-comparator2\n")}
        with self.assertRaises(P.PhysicalError):
            P._select_dispatch([comment], "a" * 40,
                               "c270-v340-comparator2")

    def test_wrong_namespace_dispatch_refused(self):
        comment = {"id": 99123, "user": {"login": "ezutfen"},
                   "author_association": "MEMBER",
                   "created_at": "2026-10-04T01:00:00Z",
                   "body": (f"{C.DISPATCH_PHRASE}\n"
                            f"head={'a' * 40}\nnamespace=c237-x\n")}
        with self.assertRaises(P.PhysicalError):
            P._select_dispatch([comment], "a" * 40,
                               "c270-v340-comparator2")

    def test_contributor_dispatch_refused(self):
        comment = {"id": 99123, "user": {"login": "someone"},
                   "author_association": "CONTRIBUTOR",
                   "created_at": "2026-10-04T01:00:00Z",
                   "body": (f"{C.DISPATCH_PHRASE}\n"
                            f"head={'a' * 40}\n"
                            "namespace=c270-v340-comparator2\n")}
        with self.assertRaises(P.PhysicalError):
            P._select_dispatch([comment], "a" * 40,
                               "c270-v340-comparator2")

    def test_authority_validator_shape(self):
        doc = make_authority("a" * 40)
        self.assertEqual(P._validate_authority(
            doc, "a" * 40, "c270-v340-comparator2"), doc)
        for mutation, key in (("issue", "issue"), ("head", "head_sha"),
                              ("namespace", "namespace"),
                              ("phrase", "dispatch_phrase")):
            bad = dict(doc)
            if mutation == "issue":
                bad[key] = 999
            elif mutation == "head":
                bad[key] = "b" * 40
            elif mutation == "namespace":
                bad[key] = "c270-other"
            else:
                bad[key] = "OTHER PHRASE"
            with self.assertRaises(P.PhysicalError):
                P._validate_authority(bad, "a" * 40,
                                      "c270-v340-comparator2")


class BinaryModelTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_binary_identity_verified(self):
        bindir = self.root / "bin"
        bindir.mkdir()
        binary = bindir / "llama-server"
        binary.write_bytes(b"comparator-bytes")
        libs = {name: b"lib-" + name.encode()
                for name in C.OBSERVER_LIBS}
        for name, data in libs.items():
            (bindir / name).write_bytes(data)
        self.saved = (C.COMPARATOR_SHA256, C.CANONICAL_SHA256, dict(C.OBSERVER_LIBS))
        C.COMPARATOR_SHA256 = sha256(b"comparator-bytes")
        C.OBSERVER_LIBS.update(
            {name: sha256(data) for name, data in libs.items()})
        self.addCleanup(self._restore)
        got = P.verify_comparator_binary(binary, bindir)
        self.assertEqual(got, C.COMPARATOR_SHA256)
        # drift: flip one library byte
        (bindir / next(iter(libs))).write_bytes(b"tampered")
        with self.assertRaises(P.PhysicalError):
            P.verify_comparator_binary(binary, bindir)

    def _restore(self):
        C.COMPARATOR_SHA256, C.CANONICAL_SHA256, libs = self.saved
        C.OBSERVER_LIBS.clear()
        C.OBSERVER_LIBS.update(libs)

    def test_canonical_must_be_distinct(self):
        comp = self.root / "comp"
        comp.write_bytes(b"comparator-bytes")
        canon = self.root / "canon"
        canon.write_bytes(b"canonical-bytes")
        saved = (C.COMPARATOR_SHA256, C.CANONICAL_SHA256)
        C.COMPARATOR_SHA256 = sha256(b"comparator-bytes")
        C.CANONICAL_SHA256 = sha256(b"canonical-bytes")
        try:
            self.assertEqual(P.verify_canonical_distinct(
                C.COMPARATOR_SHA256, canon), C.CANONICAL_SHA256)
            same = self.root / "same"
            same.write_bytes(b"comparator-bytes")
            C.CANONICAL_SHA256 = sha256(b"comparator-bytes")
            with self.assertRaises(P.PhysicalError):
                P.verify_canonical_distinct(C.COMPARATOR_SHA256, same)
        finally:
            C.COMPARATOR_SHA256, C.CANONICAL_SHA256 = saved

    def test_model_member_drift_fails_closed(self):
        model = self.root / "model"
        model.mkdir()
        for i, member in enumerate(C.MODEL_MEMBERS):
            (model / member).write_bytes(b"m:%d" % i)
        saved = dict(C.MODEL_MEMBER_SHA256)
        C.MODEL_MEMBER_SHA256.update(
            {member: sha256(b"m:%d" % i)
             for i, member in enumerate(C.MODEL_MEMBERS)})
        try:
            P.model_member_hashes(model)  # clean path
            (model / C.MODEL_MEMBERS[1]).write_bytes(b"drifted")
            with self.assertRaises(P.PhysicalError):
                P.model_member_hashes(model)
        finally:
            C.MODEL_MEMBER_SHA256.clear()
            C.MODEL_MEMBER_SHA256.update(saved)


def build_binding_record(expected_head: str, *,
                         selected_first: str = "0000:07:00.0",
                         excluded_first: str = "0000:0b:00.0",
                         load_delta: int = 128 * 1024 * 1024,
                         schema: str | None = None) -> dict:
    """Two-index binding: index0 selects 07 (or swapped), index1 the other."""
    swap = selected_first == "0000:0b:00.0"
    mapping = {
        "0": {"selected_bdf": selected_first,
              "excluded_bdf": excluded_first,
              "vram_before": {"0000:07:00.0": 1_000_000,
                              "0000:0b:00.0": 1_000_000},
              "vram_after": {"0000:07:00.0": 1_000_000,
                             "0000:0b:00.0": 1_000_000}},
        "1": {"selected_bdf": excluded_first,
              "excluded_bdf": selected_first,
              "vram_before": {"0000:07:00.0": 1_000_000,
                              "0000:0b:00.0": 1_000_000},
              "vram_after": {"0000:07:00.0": 1_000_000,
                             "0000:0b:00.0": 1_000_000}},
    }
    for key, entry in mapping.items():
        sel, exc = entry["selected_bdf"], entry["excluded_bdf"]
        entry["vram_after"][sel] = entry["vram_before"][sel] + load_delta
        # excluded stays at +0 (below noise bound)
    if swap:
        mapping["0"], mapping["1"] = mapping["1"], mapping["0"]
    return {"schema": schema or C.BINDING_SCHEMA,
            "expected_pr_head": expected_head, "host": C.CANDIDATE_HOST,
            "binary_sha256": C.COMPARATOR_SHA256, "icd": C.RADV_ICD,
            "cuda_visible_devices": "-1", "mapping": mapping}


class FreezeAndSelectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "repo"
        self.evidence = Path(self.tmp.name) / "evidence"
        self.root.mkdir()
        (self.root / C.FIXTURE_LADDER_REL).parent.mkdir(parents=True)
        (self.root / C.FIXTURE_LADDER_REL).write_bytes(
            (REPO / C.FIXTURE_LADDER_REL).read_bytes())
        self.head = "a" * 40
        self.dispatch = make_authority(self.head)

    def _observation(self):
        return {"schema": "x", "host": C.CANDIDATE_HOST,
                "raw": synthetic_raw(),
                "observed_at": "2026-10-04T00:00:00Z"}

    def test_frozen_selection_rule(self):
        sel = P_T.derive_frozen_selection(
            build_binding_record(self.head))
        self.assertEqual(sel["selected_bdf"], "0000:07:00.0")
        self.assertEqual(sel["excluded_bdfs"], ("0000:0b:00.0",))
        # Enumeration-order independence: index0 selects 0b, index1 07 ->
        # the rule still freezes 07 (lexicographically smallest selected).
        sel2 = P_T.derive_frozen_selection(
            build_binding_record(self.head,
                                 selected_first="0000:0b:00.0",
                                 excluded_first="0000:07:00.0"))
        self.assertEqual(sel2["selected_bdf"], "0000:07:00.0")

    def test_selection_rejects_non_die_bdf(self):
        record = build_binding_record(self.head)
        record["mapping"]["0"]["selected_bdf"] = "0000:0c:00.0"
        with self.assertRaises(P_T.ReducerError):
            P_T.derive_frozen_selection(record)

    def test_freeze_write_load_roundtrip(self):
        binding = build_binding_record(self.head)
        freeze = P_T.write_subject_freeze(
            self.evidence, self.root, self._observation(), binding,
            self.dispatch)
        loaded = P_T.load_subject_freeze(self.evidence)
        self.assertEqual(loaded, freeze)
        self.assertEqual(loaded["frozen_selection"]["selected_bdf"],
                         "0000:07:00.0")
        self.assertEqual(loaded["subject"]["comparator_sha256"],
                         C.COMPARATOR_SHA256)
        # Tampering invalidates the self-digest.
        freeze["subject"]["ngl"] = 8
        (self.evidence / P.FREEZE_NAME).write_text(json.dumps(freeze))
        with self.assertRaises(P_T.ReducerError):
            P_T.load_subject_freeze(self.evidence)

    def test_freeze_refuses_identity_drift(self):
        raw = synthetic_raw()
        raw["uname"] = "6.1.0-999"
        with self.assertRaises(P.PhysicalError):
            P_T.write_subject_freeze(
                self.evidence, self.root,
                {"schema": "x", "host": C.CANDIDATE_HOST, "raw": raw,
                 "observed_at": "2026-10-04T00:00:00Z"},
                build_binding_record(self.head), self.dispatch)


class SelectorBindingTests(unittest.TestCase):
    def setUp(self):
        self.head = "a" * 40

    def test_valid_binding_validates(self):
        sel = P_T.validate_selector_binding(
            build_binding_record(self.head), self.head,
            C.COMPARATOR_SHA256)
        self.assertEqual(sel["selected_bdf"], "0000:07:00.0")

    def test_wrong_head_refused(self):
        with self.assertRaises(P.PhysicalError):
            P_T.validate_selector_binding(
                build_binding_record("b" * 40), self.head,
                C.COMPARATOR_SHA256)

    def test_wrong_binary_refused(self):
        with self.assertRaises(P.PhysicalError):
            P_T.validate_selector_binding(
                build_binding_record(self.head), self.head, "c" * 64)

    def test_cuda_not_excluded_refused(self):
        record = build_binding_record(self.head)
        record["cuda_visible_devices"] = "0"
        with self.assertRaises(P.PhysicalError):
            P_T.validate_selector_binding(record, self.head,
                                          C.COMPARATOR_SHA256)

    def test_excluded_die_load_rejected(self):
        record = build_binding_record(self.head)
        entry = record["mapping"]["0"]
        entry["vram_after"][entry["excluded_bdf"]] += C.EXCLUDED_NOISE_BYTES
        with self.assertRaises(P.PhysicalError):
            P_T.validate_selector_binding(record, self.head,
                                          C.COMPARATOR_SHA256)

    def test_selected_die_load_required(self):
        record = build_binding_record(self.head, load_delta=1024)
        with self.assertRaises(P.PhysicalError):
            P_T.validate_selector_binding(record, self.head,
                                          C.COMPARATOR_SHA256)


class TerminalReducerTests(unittest.TestCase):
    """Full offline Phase-1+2+4 pipeline over synthetic-but-custody-real
    evidence."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.repo = self.base / "repo"
        self.evidence = self.base / "evidence"
        self.repo.mkdir()
        (self.repo / C.FIXTURE_LADDER_REL).parent.mkdir(parents=True)
        (self.repo / C.FIXTURE_LADDER_REL).write_bytes(
            (REPO / C.FIXTURE_LADDER_REL).read_bytes())
        subprocess.run(["git", "init", "-q"], cwd=self.repo, check=True)
        subprocess.run(["git", "add", "-A"], cwd=self.repo, check=True)
        subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                        "commit", "-qm", "i"], cwd=self.repo, check=True)
        self.head = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=self.repo,
            capture_output=True, text=True, check=True).stdout.strip()
        self.dispatch = make_authority(self.head)
        binding = build_binding_record(self.head)
        P_T.write_subject_freeze(
            self.evidence, self.repo,
            {"schema": "x", "host": C.CANDIDATE_HOST,
             "raw": synthetic_raw(),
             "observed_at": "2026-10-04T00:00:00Z"},
            binding, self.dispatch)
        P._write_json(self.evidence / P.PREFLIGHT_NAME, {
            "schema": P.PREFLIGHT_SCHEMA,
            "selector_binding": binding})
        self.frozen_ref = C.reference_identity()

    def _write_units(self, *, candidate_agrees: bool = True,
                     inert: bool = True, drop_case: str | None = None):
        for case in C.FIXTURE_CASES:
            if case == drop_case:
                continue
            unit_dir = self.evidence / "units" / case
            unit_dir.mkdir(parents=True, exist_ok=True)
            winners = [11 * (d + 1) for d in range(8)]
            cand_winners = (list(winners) if candidate_agrees
                            else [424242] * 8)
            arms = {
                "reference": ("ref", "00000000:03:00.0", "inferswarm01",
                              C.NVIDIA_ICD, REFERENCE_SELECTOR, ()),
                "candidate": ("cand", "0000:07:00.0", C.CANDIDATE_HOST,
                              C.RADV_ICD, CANDIDATE_SELECTOR, EXCLUDED),
            }
            inert_tokens = [7] * 8 if inert else [8] * 8
            for arm, (seed, bdf, host, icd, selector, excluded) in arms.items():
                receipt, _ = make_arm_receipt(
                    evidence=self.evidence, root=self.repo, arm=arm,
                    case=case, rows_seed=seed.encode() + case.encode(),
                    selected_bdf=bdf, host=host, icd=icd,
                    selector=selector, excluded_bdfs=excluded,
                    pid=1000, head=self.head, authority=self.dispatch,
                    winners=winners if arm == "reference" else cand_winners,
                    forced=([-1] * 8 if arm == "reference"
                            else list(winners)))
                if arm == "reference":
                    receipt["disabled_observer_tokens"] = inert_tokens
                    receipt["canonical_tokens"] = [7] * 8
                    receipt["disabled_observer_emitted"] = not inert
                    receipt["canonical_emitted"] = False
                P._write_json(unit_dir / f"{arm}.json", receipt)
                # Repeat receipt: same bytes, own files.
                r2, _ = make_arm_receipt(
                    evidence=self.evidence, root=self.repo, arm=arm,
                    case=case,
                    rows_seed=seed.encode() + case.encode(),
                    selected_bdf=bdf, host=host, icd=icd,
                    selector=selector, excluded_bdfs=excluded,
                    pid=1001, head=self.head, authority=self.dispatch,
                    winners=winners if arm == "reference" else cand_winners,
                    forced=([-1] * 8 if arm == "reference"
                            else list(winners)))
                r2["repeat_of"] = arm
                P._write_json(unit_dir / f"{arm}-repeat.json", r2)

    def test_pass_terminal_on_clean_evidence(self):
        self._write_units()
        result = P_T.derive_terminal(self.evidence, self.repo, self.head)
        self.assertEqual(result["terminal"], C.TERMINAL_PASS,
                         result.get("problems"))

    def test_missing_case_runtime_blocked(self):
        self._write_units(drop_case="case-3072")
        result = P_T.derive_terminal(self.evidence, self.repo, self.head)
        self.assertEqual(result["terminal"], C.TERMINAL_RUNTIME_BLOCKED)

    def test_candidate_disagreement_is_still_pass(self):
        """comparator/2 records the delta as diagnostics; candidate
        winners may differ WITHOUT failing the gate — the campaign's
        product is the authority record, not numerical agreement."""
        self._write_units(candidate_agrees=False)
        result = P_T.derive_terminal(self.evidence, self.repo, self.head)
        self.assertEqual(result["terminal"], C.TERMINAL_PASS,
                         result.get("problems"))
        self.assertEqual(
            result["diagnostics"]["case-256"]["pair"][
                "first_divergent_decision"], 0)

    def test_observer_not_inert_runtime_blocked(self):
        self._write_units(inert=False)
        result = P_T.derive_terminal(self.evidence, self.repo, self.head)
        self.assertEqual(result["terminal"], C.TERMINAL_RUNTIME_BLOCKED)

    def test_wrong_head_authority_blocked(self):
        self._write_units()
        result = P_T.derive_terminal(self.evidence, self.repo, "b" * 40)
        self.assertEqual(result["terminal"], C.TERMINAL_AUTHORITY_BLOCKED)

    def test_missing_freeze_authority_blocked(self):
        (self.evidence / P.FREEZE_NAME).unlink()
        result = P_T.derive_terminal(self.evidence, self.repo, self.head)
        self.assertEqual(result["terminal"], C.TERMINAL_AUTHORITY_BLOCKED)

    def test_missing_preflight_infrastructure_blocked(self):
        (self.evidence / P.PREFLIGHT_NAME).unlink()
        result = P_T.derive_terminal(self.evidence, self.repo, self.head)
        self.assertEqual(result["terminal"],
                         C.TERMINAL_INFRASTRUCTURE_BLOCKED)


if __name__ == "__main__":
    unittest.main()
