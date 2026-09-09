"""Issue #117 Arm C — frozen-evidence blocker mutation suite (CPU-only).

16 mandatory controls + baseline. Each control mutates one fact in a
synthetic fakeroot (scratch git repo + evidence dir) and requires the
REAL blocker reducer to fail closed (ReductionError) or refuse the
mutation. The baseline must derive the blocker terminal mechanically.

The suite never runs physical execution; it exercises
scripts/issue117_arm_c_blocker_reducer.py through reduce_all().
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

from issue117_arm_c_blocker_fakeroot import build as build_fakeroot  # noqa: E402

BLOCKER_PATH = REPO / "scripts/issue117_arm_c_blocker_reducer.py"
FREEZE_SHA = "5e2c83a09031d68784c3098fc9dad319b684f0da"

METHODOLOGY_REL = ("docs/implementation/r6-successor-dense-full-"
                   "integration-117/METHODOLOGY-ARM-C.md")
DRIVER_REL = "scripts/issue117_arm_c_direct.py"
REDUCER_REL = "scripts/issue117_arm_c_evidence.py"


def load_reducer():
    spec = importlib.util.spec_from_file_location(
        "issue117_arm_c_blocker_reducer", BLOCKER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class BlockerCase(unittest.TestCase):
    """Builds a scratch git repo whose HEAD content carries the frozen
    methodology/driver/reducer bytes the reducer verifies, plus a
    fakeroot evidence dir; points the reducer at both via env + seam."""

    FROZEN_METHODOLOGY = (
        "# frozen methodology (synthetic)\n\none `generate(session_id=i,\n"
        "prompt_token_ids=<rendered ids>, max_new_tokens=8)` per case\n")
    FROZEN_DRIVER = (
        "# frozen driver (synthetic)\nresult = runtime.generate(\n"
        "    session_id=index,\n    prompt_token_ids=rendered[case_id],\n"
        "    max_new_tokens=8,\n)\n")

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.repo = self.root / "repo"
        self.evidence = self.root / "evidence"
        (self.repo / "scripts").mkdir(parents=True)
        (self.repo / METHODOLOGY_REL).parent.mkdir(parents=True)
        (self.repo / METHODOLOGY_REL).write_text(self.FROZEN_METHODOLOGY)
        (self.repo / DRIVER_REL).write_text(self.FROZEN_DRIVER)
        (self.repo / REDUCER_REL).write_text("# frozen reducer (synthetic)\n")
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        subprocess.run(["git", "-C", str(self.repo), "add", "-A"],
                       check=True)
        subprocess.run(
            ["git", "-C", str(self.repo), "commit", "-q", "-m", "freeze",
             "--allow-empty"],
            check=True,
            env={**os.environ, "GIT_AUTHOR_NAME": "t",
                 "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
                 "GIT_COMMITTER_EMAIL": "t@t"})
        # second commit: modify the driver+reducer after the freeze so
        # the head classification (disclosed post-freeze changes)
        # matches the synthetic audit's disclosure set
        (self.repo / DRIVER_REL).write_text(
            self.FROZEN_DRIVER.replace("max_new_tokens=8",
                                       "max_new_tokens=2  # replay"))
        (self.repo / REDUCER_REL).write_text(
            "# post-freeze reducer revision (synthetic)\n")
        subprocess.run(["git", "-C", str(self.repo), "add", "-A"],
                       check=True)
        subprocess.run(
            ["git", "-C", str(self.repo), "commit", "-q", "-m", "post"],
            check=True,
            env={**os.environ, "GIT_AUTHOR_NAME": "t",
                 "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
                 "GIT_COMMITTER_EMAIL": "t@t"})
        self.freeze_sha = subprocess.check_output(
            ["git", "-C", str(self.repo), "rev-parse", "HEAD~1"],
            text=True).strip()
        os.environ["ARM_C_BLOCKER_FREEZE_SHA"] = self.freeze_sha
        build_fakeroot(self.evidence)
        # bind the fakeroot audit to the scratch repo's freeze SHA
        audit_path = self.evidence / "pre-execution-authority-audit.json"
        audit = json.loads(audit_path.read_text())
        audit["claimed_pre_execution_inferswarm_sha"] = self.freeze_sha
        audit["head_classified"] = subprocess.check_output(
            ["git", "-C", str(self.repo), "rev-parse", "HEAD"],
            text=True).strip()
        rr = json.loads((self.evidence / "run-record.json").read_text())
        rr["pre_execution_inferwarm_sha"] = self.freeze_sha
        # pin the frozen file digests to the scratch repo blobs
        for rel in (METHODOLOGY_REL, DRIVER_REL, REDUCER_REL):
            blob = subprocess.check_output(
                ["git", "-C", str(self.repo), "rev-parse",
                 f"{self.freeze_sha}:{rel}"], text=True).strip()
            content = subprocess.check_output(
                ["git", "-C", str(self.repo), "cat-file", "blob",
                 f"{self.freeze_sha}:{rel}"])
            import hashlib
            entry = audit["frozen_correctness_bearing_files"][rel]
            entry["git_blob_sha_at_freeze"] = blob
            entry["sha256_at_freeze"] = hashlib.sha256(content).hexdigest()
            entry["sha256_at_campaign_commit"] = entry["sha256_at_freeze"]
            if entry["status_at_head"] == "unchanged_since_freeze":
                entry["sha256_current_head"] = entry["sha256_at_freeze"]
        audit_path.write_text(json.dumps(audit, indent=2, sort_keys=True)
                              + "\n")
        (self.evidence / "run-record.json").write_text(
            json.dumps(rr, indent=2, sort_keys=True) + "\n")
        os.environ["ARM_C_BLOCKER_REPO"] = str(self.repo)
        self.br = load_reducer()
        self.br.set_evidence_dir(self.evidence)

    def tearDown(self) -> None:
        os.environ.pop("ARM_C_BLOCKER_REPO", None)
        os.environ.pop("ARM_C_BLOCKER_FREEZE_SHA", None)
        self.tmp.cleanup()

    # ---- helpers -------------------------------------------------------
    def load(self, name: str) -> dict:
        return json.loads((self.evidence / name).read_text())

    def save(self, name: str, doc: dict) -> None:
        (self.evidence / name).write_text(
            json.dumps(doc, indent=2, sort_keys=True) + "\n")

    def reduce(self):
        try:
            return self.br.reduce_all()
        except self.br.ReductionError as error:
            return {"failed_closed": str(error)}

    def require_baseline(self) -> None:
        result = self.reduce()
        self.assertEqual(result.get("terminal"), self.br.BLOCKED,
                         f"baseline must derive the blocker: {result}")
        self.assertNotIn("failed_closed", result)

    def require_fails_closed(self, label: str) -> None:
        result = self.reduce()
        self.assertIn(
            "failed_closed", result,
            f"mutation {label!r} was NOT caught: {result}")


class TestBaseline(BlockerCase):
    def test_baseline_derives_blocker(self) -> None:
        self.require_baseline()
        result = self.reduce()
        stop = result["stop_boundary"]
        self.assertTrue(stop["correctness_bearing_stop_trigger"])
        self.assertEqual(stop["stop_trigger_attempt"], "armc-direct-6")
        self.assertEqual(
            result["terminal_qualification"],
            "post-correctness-bearing methodology / evidence-"
            "admissibility failure")


class TestMandatoryControls(BlockerCase):
    def setUp(self) -> None:
        super().setUp()
        self.require_baseline()

    # 1. removing the direct-6 correctness-bearing flag fails
    def test_c1_remove_stop_trigger_flag(self) -> None:
        doc = self.load("attempt-lineage.json")
        for a in doc["attempts"]:
            if a["attempt_id"] == "armc-direct-6":
                a["correctness_bearing_result_emitted"] = False
        self.save("attempt-lineage.json", doc)
        self.require_fails_closed("c1-remove-cb-flag")

    # 2. relabeling direct-6 valid does not bypass the frozen rules
    def test_c2_relabel_direct6_valid(self) -> None:
        doc = self.load("attempt-lineage.json")
        for a in doc["attempts"]:
            if a["attempt_id"] == "armc-direct-6":
                a["retained_validity_flag"] = True
                a["campaign_classification"] = "valid comparator"
        self.save("attempt-lineage.json", doc)
        self.require_fails_closed("c2-relabel-valid")

    # 3. admitting direct-9 as terminal comparator after the stop fails
    def test_c3_admit_direct9_terminal(self) -> None:
        doc = self.load("attempt-lineage.json")
        for a in doc["attempts"]:
            if a["attempt_id"] == "armc-direct-9":
                a["campaign_classification"] = (
                    "admissible terminal comparator")
        self.save("attempt-lineage.json", doc)
        self.require_fails_closed("c3-admit-direct9")

    # 4. admitting ordinary-1 as terminal evidence after the stop fails
    def test_c4_admit_ordinary1_terminal(self) -> None:
        doc = self.load("attempt-lineage.json")
        for a in doc["attempts"]:
            if a["attempt_id"] == "armc-ordinary-1":
                a["campaign_classification"] = (
                    "admissible terminal evidence")
        self.save("attempt-lineage.json", doc)
        self.require_fails_closed("c4-admit-ordinary1")

    # 5. changing the frozen pre-execution SHA fails
    def test_c5_change_freeze_sha(self) -> None:
        doc = self.load("run-record.json")
        doc["pre_execution_inferwarm_sha"] = "9" * 40
        self.save("run-record.json", doc)
        self.require_fails_closed("c5-freeze-sha")

    # 6. changing the frozen methodology digest fails
    def test_c6_change_methodology_digest(self) -> None:
        audit = self.load("pre-execution-authority-audit.json")
        audit["frozen_correctness_bearing_files"][METHODOLOGY_REL][
            "sha256_at_freeze"] = "f" * 64
        self.save("pre-execution-authority-audit.json", audit)
        self.require_fails_closed("c6-methodology-digest")

    # 7. changing the frozen direct-driver digest fails
    def test_c7_change_driver_digest(self) -> None:
        audit = self.load("pre-execution-authority-audit.json")
        audit["frozen_correctness_bearing_files"][DRIVER_REL][
            "sha256_at_freeze"] = "e" * 64
        self.save("pre-execution-authority-audit.json", audit)
        self.require_fails_closed("c7-driver-digest")

    # 8. post-freeze driver modification without disclosure fails
    def test_c8_undisclosed_driver_change(self) -> None:
        audit = self.load("pre-execution-authority-audit.json")
        audit["frozen_correctness_bearing_files"][DRIVER_REL][
            "status_at_head"] = "unchanged_since_freeze"
        self.save("pre-execution-authority-audit.json", audit)
        self.require_fails_closed("c8-undisclosed-driver-change")

    # 9. post-freeze reducer modification without disclosure fails
    def test_c9_undisclosed_reducer_change(self) -> None:
        audit = self.load("pre-execution-authority-audit.json")
        audit["frozen_correctness_bearing_files"][REDUCER_REL][
            "status_at_head"] = "unchanged_since_freeze"
        self.save("pre-execution-authority-audit.json", audit)
        self.require_fails_closed("c9-undisclosed-reducer-change")

    # 10. replay-prefill cannot masquerade as the frozen single-shot
    #     comparator (marker injected into the direct-6 rows)
    def test_c10_replay_masquerade(self) -> None:
        doc = self.load("invalid-attempt-6/direct-run.json")
        for row in doc["results"]:
            row["invocation"] = "per-token-replay-prefill/1"
        self.save("invalid-attempt-6/direct-run.json", doc)
        self.require_fails_closed("c10-replay-masquerade")

    # 11. tokenizer metadata Source reads cannot be silently zeroed
    def test_c11_zero_tokenizer_reads(self) -> None:
        audit = self.load("pre-execution-authority-audit.json")
        acct = audit["source_read_accounting_frozen_rule"]
        acct["tokenizer_metadata_file_reads"] = 0
        acct["observed_paths"]["tokenizer_metadata_files"] = []
        self.save("pre-execution-authority-audit.json", audit)
        self.require_fails_closed("c11-zero-tokenizer-reads")

    # 12. changing the four-read count fails
    def test_c12_change_read_count(self) -> None:
        audit = self.load("pre-execution-authority-audit.json")
        audit["source_read_accounting_frozen_rule"][
            "tokenizer_metadata_file_reads"] = 3
        self.save("pre-execution-authority-audit.json", audit)
        self.require_fails_closed("c12-read-count")

    # 13. erasing direct-6 from lineage fails
    def test_c13_erase_direct6(self) -> None:
        doc = self.load("attempt-lineage.json")
        doc["attempts"] = [a for a in doc["attempts"]
                           if a["attempt_id"] != "armc-direct-6"]
        self.save("attempt-lineage.json", doc)
        self.require_fails_closed("c13-erase-direct6")

    # 14. erasing a later diagnostic attempt fails
    def test_c14_erase_later_attempt(self) -> None:
        doc = self.load("attempt-lineage.json")
        doc["attempts"] = [a for a in doc["attempts"]
                           if a["attempt_id"] != "armc-ordinary-1"]
        self.save("attempt-lineage.json", doc)
        self.require_fails_closed("c14-erase-ordinary1")

    # 15. converting the campaign to semantic FAIL despite the stop
    #     boundary fails (a forged blocker-reduction.json terminal is
    #     not authority; and the derivation cannot produce FAIL)
    def test_c15_forge_semantic_fail(self) -> None:
        self.evidence.joinpath("blocker-reduction.json").write_text(
            json.dumps({"terminal": "ISSUE117_ARM_C_ORDINARY_SERVING_FAIL"})
            + "\n")
        result = self.reduce()
        self.assertNotIn("failed_closed", result)
        self.assertNotEqual(result.get("terminal"),
                            "ISSUE117_ARM_C_ORDINARY_SERVING_FAIL",
                            "stored FAIL string must not become authority")
        self.assertEqual(result.get("terminal"), self.br.BLOCKED)

    # 16. converting the campaign to PASS fails
    def test_c16_forge_pass(self) -> None:
        self.evidence.joinpath("blocker-reduction.json").write_text(
            json.dumps({"terminal": "ISSUE117_ARM_C_ORDINARY_SERVING_PASS"})
            + "\n")
        result = self.reduce()
        self.assertNotEqual(result.get("terminal"),
                            "ISSUE117_ARM_C_ORDINARY_SERVING_PASS",
                            "stored PASS string must not become authority")
        self.assertEqual(result.get("terminal"), self.br.BLOCKED)

    # extra: ordering violation (a post-stop attempt reordered before
    # the trigger) fails
    def test_c17_post_stop_reordered_before_trigger(self) -> None:
        doc = self.load("attempt-lineage.json")
        for a in doc["attempts"]:
            if a["attempt_id"] == "armc-ordinary-1":
                a["order"] = 1
        self.save("attempt-lineage.json", doc)
        self.require_fails_closed("c17-reorder")


class TestRealEvidence(unittest.TestCase):
    """The retained physical evidence must derive the blocker through
    the REAL reducer against the REAL repository (no fakeroot)."""

    def test_retained_campaign_derives_blocker(self) -> None:
        os.environ.pop("ARM_C_BLOCKER_REPO", None)
        os.environ.pop("ARM_C_BLOCKER_FREEZE_SHA", None)
        br = load_reducer()
        result = br.reduce_all()
        self.assertEqual(result["terminal"], br.BLOCKED)
        self.assertEqual(result["stop_boundary"]["stop_trigger_attempt"],
                         "armc-direct-6")
        self.assertEqual(
            result["source_reads_frozen_rule"][
                "tokenizer_metadata_file_reads"], 4)
        self.assertFalse(result["stop_boundary"]["direct9_is_frozen_"
                                                "comparator"])


if __name__ == "__main__":
    unittest.main()
