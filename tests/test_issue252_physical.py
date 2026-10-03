"""CPU-only synthetic contracts; these fixtures are NEVER physical evidence."""
from __future__ import annotations
import copy
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import issue252_arms as A
import issue252_constants as C
import issue252_capture as CAP
import issue252_physical as P
import issue250_diagnostic as D


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args],
                          check=True, capture_output=True, text=True).stdout.strip()


class FixtureMixin:
    """Plain mixin. Builders act on the actual running TestCase instance."""
    def fixture(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        git(self.repo, "init", "-q")
        git(self.repo, "config", "user.name", "Fixture")
        git(self.repo, "config", "user.email", "fixture@example.invalid")
        (self.repo / "source.txt").write_text("fixture\n")
        git(self.repo, "add", "source.txt")
        git(self.repo, "commit", "-qm", "fixture")
        self.head = git(self.repo, "rev-parse", "HEAD")
        self.pr_number = 300
        self.arm = "A1"
        self.parent_patch = mock.patch.object(P.P0, "verify_terminalization", return_value={
            "terminal": C.PREDECESSOR_TERMINAL, "execution_head": C.ACCEPTED_EXECUTION_HEAD})
        self.pin_patch = mock.patch.object(P.P0, "verify_llama_pin", return_value={
            "head": C.LLAMA_PIN, "tree": C.LLAMA_PIN_TREE})
        self.parent_patch.start(); self.pin_patch.start()
        self.addCleanup(self.pin_patch.stop); self.addCleanup(self.parent_patch.stop)
        self.evidence = self.root / "synthetic-evidence-NOT-PHYSICAL"
        self.evidence.mkdir()
        # Each distinct (arm, head) dispatch is a DISTINCT synthetic comment
        # with its own GitHub comment id, so re-fetch-by-id can distinguish
        # arms and fix dispatches exactly like the live API would.
        self._comment_ids = {}

    def _comment_id(self, arm, head):
        key = (arm, head)
        if key not in self._comment_ids:
            self._comment_ids[key] = 1000 + len(self._comment_ids)
        return self._comment_ids[key]

    def comment(self, arm=None, head=None):
        arm = arm or self.arm
        head = head or self.head
        cid = self._comment_id(arm, head)
        return {"body": f"{C.DISPATCH_PHRASE_FORMAT}\nhead={head}\narm={arm}",
                "author_association": "OWNER", "id": cid,
                "created_at": "2026-09-30T12:00:00Z",
                "html_url": f"https://github.com/Zutfen-LLC/inferswarm/pull/{C.CAMPAIGN_PR}#issuecomment-{cid}",
                "user": {"login": "ezutfen"},
                "issue_url": f"https://api.github.com/repos/Zutfen-LLC/inferswarm/issues/{C.CAMPAIGN_PR}",
                "pr": {"state": "open", "merged": False, "draft": False,
                       "number": C.CAMPAIGN_PR, "base": {"ref": "main"},
                       "head": {"sha": head, "ref": git(self.repo, "branch", "--show-current")}},
                "issue": {"state": "open", "number": C.ISSUE}}

    def capture(self, arm=None, head=None, comment=None):
        """Retained capture built from the same factory the receipts use."""
        arm = arm or self.arm
        head = head or self.head
        c = comment or self.comment(arm, head)
        return CAP.build_capture(c, pr=c["pr"], issue=c["issue"],
                                 repo_pr_number=C.CAMPAIGN_PR)

    def fetcher(self, arm=None, head=None):
        """Offline re-fetch seam serving every registered synthetic comment."""
        if arm is not None:
            self.comment(arm, head)  # ensure the requested one is registered
        registry = {self._comment_ids[k]: self.comment(*k)
                    for k in list(self._comment_ids)}

        def fetch(url):
            prefix = ("https://api.github.com/repos/Zutfen-LLC/inferswarm/"
                      "issues/comments/")
            if not url.startswith(prefix):
                raise CAP.CaptureInvalid("comment not found: " + url)
            cid = int(url[len(prefix):])
            if cid not in registry:
                raise CAP.CaptureInvalid("comment not found: " + url)
            return registry[cid]
        return fetch

    def offline_authority_fetch(self, arm=None, head=None):
        """TEST-ONLY facility: patch the PRODUCTION fetch function object.

        This is the separated offline mechanism the round-4 review required:
        synthetic-fixture tests exercise reducer authority admission by
        patching issue252_physical.fetch_dispatch_comment with the offline
        registry — through the standard unittest seam, on the module the
        production code itself imports. It is NOT reachable through the
        shipped reducer/capture API (derive_terminal(evidence_root,
        arms_result) and verify_capture(retained, repo_pr_number=...) have
        no fetch parameter and no test flag), so no caller controlling
        reducer invocation can substitute an authority fetcher.
        """
        return mock.patch.object(P, "fetch_dispatch_comment",
                                 self.fetcher(arm, head))

    def authority(self, arm=None, head=None):
        return self.capture(arm, head)

    def write_json(self, path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, sort_keys=True))

    def receipt(self, arm="A1", index=1, row=None, authority=None,
                fix_commit=None, binary_sha256=C.COMPARATOR_SHA256,
                server_log=None):
        auth = authority or self.authority(arm)
        row = row if row is not None else bytes(D.ROW_BYTES)
        identity = dict(C.HOST_FACTS)
        # AMENDMENT-005 placement shape (frozen geometry facts; the enum
        # banner is no longer required by the producer law).
        placement = {"output_projection": "Vulkan", "embedding": "CPU",
                     "ngl": 1, "gpu_uuid": C.HOST_FACTS["gpu_uuid"],
                     "vulkan_family": "NV_coopmat2",
                     "vulkan_family_authority": "frozen-host-facts",
                     "cuda_participation": False}
        witness = {m: {k: 1 for k in ("bytes", "device", "inode", "mtime_ns", "ctime_ns")}
                   for m in C.MODEL_MEMBERS}
        raw = json.dumps({"tokens": list(range(D.DECISIONS))}).encode()
        meta = b"".join(json.dumps({"pos": i}).encode() + b"\n" for i in range(D.DECISIONS))
        log = server_log.encode("utf-8") if server_log is not None else b"synthetic fixture only\n"
        receipt = P.build_unit_receipt(
            authority=auth, unit_index=index, binary=Path("/fixture/llama-server"),
            model_member=Path("/srv/models/qwen38-ud-iq1-s") / next(iter(C.MODEL_MEMBERS)),
            observer_dir=Path("/fixture/observations"), identity_pre=identity,
            identity_post=identity, placement=placement, raw_response=raw,
            rows=[row] * D.DECISIONS, observer_meta=meta, server_log=log,
            server_pid=100 + index, model_stat_witness=witness,
            request=copy.deepcopy(D.REQUEST_CONTRACT), fix_commit=fix_commit,
            binary_sha256=binary_sha256)
        return receipt, raw, meta, log, row

    def retain(self, arm, index, row=None, authority=None, namespace=None,
               fix_commit=None, binary_sha256=C.COMPARATOR_SHA256,
               server_log=None):
        rec, raw, meta, log, row = self.receipt(arm, index, row, authority,
                                               fix_commit, binary_sha256,
                                               server_log)
        ns = namespace or A.ARMS[arm]["namespace"]
        unit = self.evidence / ns / rec["tag"]
        unit.mkdir(parents=True)
        self.write_json(unit / "unit.json", rec)
        (unit / "response.json.raw").write_bytes(raw)
        (unit / "obs.meta.json").write_bytes(meta)
        (unit / "server.log").write_bytes(log)
        for i in range(D.DECISIONS):
            (unit / f"obs.row{i}.f32").write_bytes(row)
        for phase in ("pre", "post"):
            self.write_json(unit / f"identity-{phase}.json", rec[f"identity_{phase}"])
        self.write_json(unit / "placement.json", rec["placement"])
        return unit


class PhysicalTests(FixtureMixin, unittest.TestCase):
    def setUp(self):
        self.fixture()

    def test_dispatch_positive_synthetic_clean_repo(self):
        self.assertEqual(P.verify_dispatch(self.comment(), self.repo, self.head)["arm"], "A1")

    def test_head_moved(self):
        with self.assertRaisesRegex(P.DispatchRefused, "head moved"):
            P.verify_dispatch(self.comment(head="f" * 40), self.repo, self.head)

    def test_live_pr_head_moved(self):
        c = self.comment(); c["pr"]["head"]["sha"] = "e" * 40
        with self.assertRaisesRegex(P.DispatchRefused, "PR head moved"):
            P.verify_dispatch(c, self.repo, self.head)

    def test_branch_drift(self):
        c = self.comment(); c["pr"]["head"]["ref"] = "another-branch"
        with self.assertRaisesRegex(P.DispatchRefused, "branch differs"):
            P.verify_dispatch(c, self.repo, self.head)

    def test_dirty_tree(self):
        (self.repo / "untracked").write_text("dirty")
        with self.assertRaisesRegex(P.DispatchRefused, "dirty"):
            P.verify_dispatch(self.comment(), self.repo, self.head)

    def test_wrong_phrase(self):
        c = self.comment(); c["body"] = c["body"].replace("PHYSICAL", "UNAUTHORIZED")
        with self.assertRaisesRegex(P.DispatchRefused, "phrase"):
            P.verify_dispatch(c, self.repo, self.head)

    def test_capture_namespace_arm_mismatch_rejected(self):
        # The namespace key no longer travels in the comment; namespace/arm
        # consistency is enforced at the capture layer.
        cap = self.capture("A2")
        cap["namespace"] = A.ARMS["A1"]["namespace"]
        with self.assertRaisesRegex(CAP.CaptureInvalid, "namespace/arm"):
            CAP.validate_capture_structure(cap)

    def test_emit_capture_positive(self):
        c = self.comment()
        cap = P.emit_capture(c)
        self.assertEqual(cap["arm"], "A1")
        self.assertEqual(cap["namespace"], A.ARMS["A1"]["namespace"])
        self.assertGreater(cap["comment_id"], 0)
        self.assertEqual(cap["execution_time_state"]["pr_head"], self.head)

    def test_non_owner(self):
        c = self.comment(); c["author_association"] = "CONTRIBUTOR"
        with self.assertRaisesRegex(P.DispatchRefused, "OWNER/MEMBER"):
            P.verify_dispatch(c, self.repo, self.head)

    def test_issue_closed(self):
        c = self.comment(); c["issue"]["state"] = "closed"
        with self.assertRaisesRegex(P.DispatchRefused, "not open"):
            P.verify_dispatch(c, self.repo, self.head)

    def test_pr_merged_draft_closed(self):
        for field, value in (("merged", True), ("draft", True), ("state", "closed")):
            with self.subTest(field=field):
                c = self.comment(); c["pr"][field] = value
                with self.assertRaisesRegex(P.DispatchRefused, "PR is not"):
                    P.verify_dispatch(c, self.repo, self.head)

    def test_parent_tampered(self):
        with mock.patch.object(P.P0, "verify_terminalization", side_effect=ValueError("tampered")):
            with self.assertRaisesRegex(P.DispatchRefused, "parent authority"):
                P.verify_dispatch(self.comment(), self.repo, self.head)

    def test_pin_tampered(self):
        with mock.patch.object(P.P0, "verify_llama_pin", return_value={}):
            with self.assertRaisesRegex(P.DispatchRefused, "parent authority"):
                P.verify_dispatch(self.comment(), self.repo, self.head)

    def test_no_top_level_pr_comment(self):
        c = self.comment(); c["issue_url"] = "https://api.github.com/repos/Zutfen-LLC/inferswarm/issues/252"
        with self.assertRaisesRegex(P.DispatchRefused, "top-level"):
            P.verify_dispatch(c, self.repo, self.head)

    def test_receipt_mutations(self):
        rec = self.receipt()[0]
        mutations = {
            "missing custody": lambda r: r.pop("response_raw_sha256"),
            "wrong argv": lambda r: r["server_argv"].__setitem__(4, "0"),
            "wrong model member": lambda r: r["model_members"].__setitem__(next(iter(C.MODEL_MEMBERS)), "0" * 64),
            "missing identity post": lambda r: r.pop("identity_post"),
            "wrong request": lambda r: r.__setitem__("request", {}),
            "wrong control": lambda r: r["server_env"].__setitem__("GGML_VK_SERIALIZE_SUBMISSIONS", "0"),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                changed = copy.deepcopy(rec); mutate(changed)
                with self.assertRaises(ValueError):
                    P.validate_unit_receipt(changed)


if __name__ == "__main__":
    unittest.main()
