#!/usr/bin/env python3
"""Issue #117 Arm C — frozen-evidence blocker mutation suite,
correction /2 (CPU-only).

Baseline + 30 mandatory controls. Each control mutates one fact in a
synthetic fakeroot (scratch git repo + evidence dir + synthetic frozen
FreeToken sources) and requires the REAL blocker reducer to fail
closed (ReductionError) or refuse the mutation. The baseline must
mechanically derive the blocker terminal from the frozen
comparator-methodology defect, with both history branches converging.

The suite never runs physical execution; it exercises
scripts/issue117_arm_c_blocker_reducer.py through reduce_all().
"""
from __future__ import annotations

import hashlib
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
FT_AREA = ("docs/implementation/r6-successor-dense-full-integration-"
           "117/evidence/arm-c/frozen-freetoken/924cd22e")
EPOCHS_REL = f"{FT_AREA}/python/freetoken/research/r5b_epochs.py"


def load_reducer():
    spec = importlib.util.spec_from_file_location(
        "issue117_arm_c_blocker_reducer", BLOCKER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class BlockerCase(unittest.TestCase):
    """Scratch git repo (freeze commit + post-freeze commit) carrying
    the frozen methodology/driver bytes, a fakeroot evidence dir with
    synthetic frozen FreeToken sources, and the reducer pointed at
    both via env + seam."""

    FROZEN_METHODOLOGY = (
        "# frozen methodology (synthetic)\n\none `generate(session_id=i,"
        "\nprompt_token_ids=<rendered ids>, max_new_tokens=8)` per case\n"
        "The ONLY intended difference is the control-plane path.\n")
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
        self.git_env = {**os.environ, "GIT_AUTHOR_NAME": "t",
                        "GIT_AUTHOR_EMAIL": "t@t",
                        "GIT_COMMITTER_NAME": "t",
                        "GIT_COMMITTER_EMAIL": "t@t"}
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        subprocess.run(["git", "-C", str(self.repo), "add", "-A"],
                       check=True)
        subprocess.run(
            ["git", "-C", str(self.repo), "commit", "-q", "-m", "freeze",
             "--allow-empty"], check=True, env=self.git_env)
        # second commit: driver+reducer modified after the freeze
        (self.repo / DRIVER_REL).write_text(
            self.FROZEN_DRIVER.replace("max_new_tokens=8",
                                       "max_new_tokens=2  # replay"))
        (self.repo / REDUCER_REL).write_text(
            "# post-freeze reducer revision (synthetic)\n")
        subprocess.run(["git", "-C", str(self.repo), "add", "-A"],
                       check=True)
        subprocess.run(
            ["git", "-C", str(self.repo), "commit", "-q", "-m", "post"],
            check=True, env=self.git_env)
        self.audited_head = subprocess.check_output(
            ["git", "-C", str(self.repo), "rev-parse", "HEAD"],
            text=True).strip()
        self.freeze_sha = subprocess.check_output(
            ["git", "-C", str(self.repo), "rev-parse", "HEAD~1"],
            text=True).strip()
        os.environ["ARM_C_BLOCKER_FREEZE_SHA"] = self.freeze_sha
        os.environ["ARM_C_BLOCKER_REPO"] = str(self.repo)
        # fakeroot builds evidence INSIDE the scratch repo so the
        # frozen FreeToken sources resolve under the same root
        evidence_dir = self.repo / (
            "docs/implementation/r6-successor-dense-full-integration"
            "-117/evidence/arm-c")
        pins = build_fakeroot(evidence_dir)
        self.pins_file = self.root / "pins.json"
        self.pins_file.write_text(json.dumps(pins))
        os.environ["ARM_C_BLOCKER_FROZEN_PINS"] = str(self.pins_file)
        # bind the fakeroot audit to the scratch repo
        audit_path = evidence_dir / "pre-execution-authority-audit.json"
        audit = json.loads(audit_path.read_text())
        audit["claimed_pre_execution_inferswarm_sha"] = self.freeze_sha
        audit["head_classified"] = self.audited_head
        rr = json.loads(
            (evidence_dir / "run-record.json").read_text())
        rr["pre_execution_inferwarm_sha"] = self.freeze_sha
        for rel in (METHODOLOGY_REL, DRIVER_REL, REDUCER_REL):
            blob = subprocess.check_output(
                ["git", "-C", str(self.repo), "rev-parse",
                 f"{self.freeze_sha}:{rel}"], text=True).strip()
            content = subprocess.check_output(
                ["git", "-C", str(self.repo), "cat-file", "blob",
                 f"{self.freeze_sha}:{rel}"])
            entry = audit["frozen_correctness_bearing_files"][rel]
            entry["git_blob_sha_at_freeze"] = blob
            entry["sha256_at_freeze"] = hashlib.sha256(
                content).hexdigest()
            entry["sha256_at_campaign_commit"] = entry["sha256_at_freeze"]
            if entry["status_at_head"] == "unchanged_since_freeze":
                entry["sha256_current_head"] = entry["sha256_at_freeze"]
        audit_path.write_text(json.dumps(audit, indent=2, sort_keys=True)
                              + "\n")
        (evidence_dir / "run-record.json").write_text(
            json.dumps(rr, indent=2, sort_keys=True) + "\n")
        self.evidence = evidence_dir
        self.br = load_reducer()
        self.br.set_evidence_dir(evidence_dir)

    def tearDown(self) -> None:
        os.environ.pop("ARM_C_BLOCKER_REPO", None)
        os.environ.pop("ARM_C_BLOCKER_FREEZE_SHA", None)
        os.environ.pop("ARM_C_BLOCKER_FROZEN_PINS", None)
        self.tmp.cleanup()

    # ---- helpers -------------------------------------------------------
    def load(self, name: str) -> dict:
        return json.loads((self.evidence / name).read_text())

    def save(self, name: str, doc: dict) -> None:
        (self.evidence / name).write_text(
            json.dumps(doc, indent=2, sort_keys=True) + "\n")

    def mutate_frozen_source(self, rel: str, old: str, new: str) -> None:
        path = self.repo / rel
        text = path.read_text()
        self.assertIn(old, text, f"frozen-source mutation precondition")
        path.write_text(text.replace(old, new, 1))
        # re-pin the synthetic source so the digest check passes and
        # the SEMANTIC derivation must catch the mutation
        pins = json.loads(self.pins_file.read_text())
        pins[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
        self.pins_file.write_text(json.dumps(pins))
        # the pins module is imported by path per call: env re-read
        os.environ["ARM_C_BLOCKER_FROZEN_PINS"] = str(self.pins_file)

    def add_head_commit(self, changes: dict[str, str]) -> str:
        """Commit additional file changes on top of the audited head
        (simulating a later head); returns the new head sha."""
        for rel, content in changes.items():
            path = self.repo / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
        subprocess.run(["git", "-C", str(self.repo), "add", "-A"],
                       check=True)
        subprocess.run(
            ["git", "-C", str(self.repo), "commit", "-q", "-m", "later"],
            check=True, env=self.git_env)
        return subprocess.check_output(
            ["git", "-C", str(self.repo), "rev-parse", "HEAD"],
            text=True).strip()

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
        self.assertEqual(
            result["comparator_defect"]["authority_statement"][:43],
            "The frozen Arm-C methodology failed its own")

    def require_fails_closed(self, label: str) -> None:
        result = self.reduce()
        self.assertIn(
            "failed_closed", result,
            f"mutation {label!r} was NOT caught: {result}")


class TestBaseline(BlockerCase):
    def test_baseline_derives_blocker(self) -> None:
        self.require_baseline()
        result = self.reduce()
        sem = result["frozen_invocation_semantics"]
        self.assertEqual(sem["direct"]["max_new_tokens"], 8)
        self.assertEqual(sem["direct"]["invocation"], "single-shot")
        self.assertEqual(sem["ordinary"]["max_new_tokens"], 2)
        self.assertIn("replay-prefix", sem["ordinary"]["invocation"])
        branches = result["branch_analysis"]["branches"]
        self.assertTrue(all(b["terminal"] == self.br.BLOCKED
                            for b in branches))
        chron = result["observations"]["chronology_utc"]
        self.assertLess(chron["armc-direct-6"], chron["armc-ordinary-1"])
        self.assertLess(chron["armc-ordinary-1"],
                        chron["armc-direct-7"])
        self.assertEqual(
            result["observations"]["direct6"]
            ["exact_staged_driver_bytes"], "unknown / not retained")


class TestMandatoryControls(BlockerCase):
    def setUp(self) -> None:
        super().setUp()
        self.require_baseline()

    # --- frozen invocation semantics ---------------------------------
    # 2. changing the frozen ordinary controller call from 2 to 8
    def test_c2_frozen_ordinary_2_to_8(self) -> None:
        self.mutate_frozen_source(
            EPOCHS_REL, "max_new_tokens=2,", "max_new_tokens=8,")
        self.require_fails_closed("c2-frozen-ordinary-2-to-8")

    # 3. removing replay-prefix semantics from the pinned ordinary
    #    source fails
    def test_c3_remove_replay_prefix(self) -> None:
        self.mutate_frozen_source(
            EPOCHS_REL,
            "replay_input = list(self.transition_strategy."
            "replay_input(session=session))",
            "replay_input = list(prompt_token_ids)")
        self.require_fails_closed("c3-remove-replay-prefix")

    # 4. forging the two invocation modes as equivalent fails
    def test_c4_forge_equivalence(self) -> None:
        # make the ordinary source a single-shot clone of the direct
        # arm: the comparator defect must vanish-protect
        self.mutate_frozen_source(
            EPOCHS_REL, "max_new_tokens=2,", "max_new_tokens=8,")
        # direct mnt is pinned from git at 8; if both are 8 the
        # reducer MUST fail (defect fabricated away)
        self.require_fails_closed("c4-forged-equivalence")

    # --- direct-6 identity + observations ------------------------------
    # 5. asserting exact direct-6 driver identity fails
    def test_c5_forged_direct6_driver_identity(self) -> None:
        doc = self.load("attempt-lineage.json")
        for a in doc["attempts"]:
            if a["attempt_id"] == "armc-direct-6":
                a["code_identity"]["driver_bytes"] = (
                    "sha256:c0f03ef5d5b7aaba1e36cdee3ca310d29ce9d1bd"
                    "70b9b1bfa4f947ddeefa204a")
        self.save("attempt-lineage.json", doc)
        self.require_fails_closed("c5-forged-direct6-identity")

    # 6. erasing direct-6 fails
    def test_c6_erase_direct6(self) -> None:
        doc = self.load("attempt-lineage.json")
        doc["attempts"] = [a for a in doc["attempts"]
                           if a["attempt_id"] != "armc-direct-6"]
        self.save("attempt-lineage.json", doc)
        self.require_fails_closed("c6-erase-direct6")

    # 7. erasing ordinary-1 fails
    def test_c7_erase_ordinary1(self) -> None:
        doc = self.load("attempt-lineage.json")
        doc["attempts"] = [a for a in doc["attempts"]
                           if a["attempt_id"] != "armc-ordinary-1"]
        self.save("attempt-lineage.json", doc)
        self.require_fails_closed("c7-erase-ordinary1")

    # 8. changing the direct-6/ordinary timestamp ordering fails
    def test_c8_timestamp_reorder(self) -> None:
        doc = self.load("attempt-lineage.json")
        for a in doc["attempts"]:
            if a["attempt_id"] == "armc-direct-6":
                a["observed_timestamps"]["completion_evidence_utc"] = (
                    "2026-09-09T10:48:00.000000+00:00")
        self.save("attempt-lineage.json", doc)
        self.require_fails_closed("c8-timestamp-reorder")

    # 8b. a claimed chronology (logical order) contradicting the
    #     retained timestamps fails
    def test_c8b_logical_order_contradiction(self) -> None:
        doc = self.load("attempt-lineage.json")
        for a in doc["attempts"]:
            if a["attempt_id"] == "armc-ordinary-1":
                a["order"] = 1  # timestamps: after direct-6
        self.save("attempt-lineage.json", doc)
        self.require_fails_closed("c8b-order-contradiction")

    # 9. treating replay direct-9 as the terminal comparator fails
    def test_c9_direct9_terminal(self) -> None:
        doc = self.load("attempt-lineage.json")
        for a in doc["attempts"]:
            if a["attempt_id"] == "armc-direct-9":
                a["campaign_classification"] = (
                    "admissible terminal comparator")
        self.save("attempt-lineage.json", doc)
        self.require_fails_closed("c9-direct9-terminal")

    # 10. restoring semantic FAIL (stored string) changes nothing
    def test_c10_forge_semantic_fail(self) -> None:
        self.evidence.joinpath("blocker-reduction.json").write_text(
            json.dumps({"terminal":
                        "ISSUE117_ARM_C_ORDINARY_SERVING_FAIL"}) + "\n")
        result = self.reduce()
        self.assertNotIn("failed_closed", result)
        self.assertNotEqual(result.get("terminal"),
                            "ISSUE117_ARM_C_ORDINARY_SERVING_FAIL")
        self.assertEqual(result.get("terminal"), self.br.BLOCKED)

    # 11. restoring PASS (stored string) changes nothing
    def test_c11_forge_pass(self) -> None:
        self.evidence.joinpath("blocker-reduction.json").write_text(
            json.dumps({"terminal":
                        "ISSUE117_ARM_C_ORDINARY_SERVING_PASS"}) + "\n")
        result = self.reduce()
        self.assertNotEqual(result.get("terminal"),
                            "ISSUE117_ARM_C_ORDINARY_SERVING_PASS")
        self.assertEqual(result.get("terminal"), self.br.BLOCKED)

    # --- frozen-rule Source reads --------------------------------------
    # 12. silently exempting tokenizer metadata (zeroing) fails
    def test_c12_zero_tokenizer_reads(self) -> None:
        audit = self.load("pre-execution-authority-audit.json")
        acct = audit["source_read_accounting_frozen_rule"]
        acct["tokenizer_metadata_file_reads"] = 0
        acct["observed_paths"]["tokenizer_metadata_files"] = []
        self.save("pre-execution-authority-audit.json", audit)
        self.require_fails_closed("c12-zero-tokenizer-reads")

    # 13. changing the four-read count fails
    def test_c13_change_read_count(self) -> None:
        audit = self.load("pre-execution-authority-audit.json")
        audit["source_read_accounting_frozen_rule"][
            "tokenizer_metadata_file_reads"] = 3
        self.save("pre-execution-authority-audit.json", audit)
        self.require_fails_closed("c13-read-count")

    # --- authority + frozen identities ---------------------------------
    # 14. changing the frozen pre-execution SHA fails
    def test_c14_change_freeze_sha(self) -> None:
        doc = self.load("run-record.json")
        doc["pre_execution_inferwarm_sha"] = "9" * 40
        self.save("run-record.json", doc)
        self.require_fails_closed("c14-freeze-sha")

    # 15. changing the frozen methodology digest fails
    def test_c15_change_methodology_digest(self) -> None:
        audit = self.load("pre-execution-authority-audit.json")
        audit["frozen_correctness_bearing_files"][METHODOLOGY_REL][
            "sha256_at_freeze"] = "f" * 64
        self.save("pre-execution-authority-audit.json", audit)
        self.require_fails_closed("c15-methodology-digest")

    # 16. changing the frozen direct-driver digest fails
    def test_c16_change_driver_digest(self) -> None:
        audit = self.load("pre-execution-authority-audit.json")
        audit["frozen_correctness_bearing_files"][DRIVER_REL][
            "sha256_at_freeze"] = "e" * 64
        self.save("pre-execution-authority-audit.json", audit)
        self.require_fails_closed("c16-driver-digest")

    # 17. removing the correctness-bearing flag from direct-6 fails
    def test_c17_remove_cb_flag(self) -> None:
        doc = self.load("attempt-lineage.json")
        for a in doc["attempts"]:
            if a["attempt_id"] == "armc-direct-6":
                a["correctness_bearing_result_emitted"] = False
        self.save("attempt-lineage.json", doc)
        self.require_fails_closed("c17-remove-cb-flag")

    # 18. replay marker injected into direct-6 rows fails
    def test_c18_replay_masquerade(self) -> None:
        doc = self.load("invalid-attempt-6/direct-run.json")
        for row in doc["results"]:
            row["invocation"] = "per-token-replay-prefill/1"
        self.save("invalid-attempt-6/direct-run.json", doc)
        self.require_fails_closed("c18-replay-masquerade")

    # 19. both history branches removed (ambiguous flag + broken
    #     chronology) fails — the terminal may not hang on an
    #     unresolvable history
    def test_c19_history_unresolvable(self) -> None:
        doc = self.load("attempt-lineage.json")
        for a in doc["attempts"]:
            if a["attempt_id"] == "armc-direct-6":
                a["retained_validity_flag"] = None
        self.save("attempt-lineage.json", doc)
        self.require_fails_closed("c19-history-unresolvable")

    # 20. comparator-modification forensics violation (staged-driver
    #     overwrite placed BEFORE direct-6 completed) fails
    def test_c20_forensics_order(self) -> None:
        audit = self.load("pre-execution-authority-audit.json")
        audit["comparator_modification_forensics"][
            "staged_driver_mtime_utc"] = "2026-09-09T10:00:00Z"
        self.save("pre-execution-authority-audit.json", audit)
        self.require_fails_closed("c20-forensics-order")

    # 21. ordinary planner provenance no longer citing direct-6 fails
    def test_c21_provenance_severed(self) -> None:
        doc = self.load("coordinator-report.json")
        doc["epochs"][0]["execution_plan"]["evidence_audit"][0][
            "provenance"]["attempt_id"] = "someone-else"
        self.save("coordinator-report.json", doc)
        self.require_fails_closed("c21-provenance-severed")

    # --- exact-head audit loophole (fail-closed allowlist) --------------
    def _later_change(self, changes: dict[str, str], label: str) -> None:
        self.add_head_commit(changes)
        self.require_fails_closed(label)

    # 22. later methodology change alone fails
    def test_c22_later_methodology(self) -> None:
        self._later_change(
            {METHODOLOGY_REL: self.FROZEN_METHODOLOGY + "# tuned\n"},
            "c22-later-methodology")

    # 23. later driver change alone fails
    def test_c23_later_driver(self) -> None:
        self._later_change(
            {DRIVER_REL: self.FROZEN_DRIVER + "# tuned\n"},
            "c23-later-driver")

    # 24. later methodology + legacy-reducer change fails (the exact
    #     loophole: old logic passed whenever the reducer changed too)
    def test_c24_later_methodology_plus_reducer(self) -> None:
        self._later_change(
            {METHODOLOGY_REL: self.FROZEN_METHODOLOGY + "# tuned\n",
             REDUCER_REL: "# legacy reducer also changed\n"},
            "c24-later-methodology+reducer")

    # 25. later driver + legacy-reducer change fails
    def test_c25_later_driver_plus_reducer(self) -> None:
        self._later_change(
            {DRIVER_REL: self.FROZEN_DRIVER + "# tuned\n",
             REDUCER_REL: "# legacy reducer also changed\n"},
            "c25-later-driver+reducer")

    # 26. later methodology + driver + legacy-reducer change fails
    def test_c26_later_all_three(self) -> None:
        self._later_change(
            {METHODOLOGY_REL: self.FROZEN_METHODOLOGY + "# tuned\n",
             DRIVER_REL: self.FROZEN_DRIVER + "# tuned\n",
             REDUCER_REL: "# legacy reducer also changed\n"},
            "c26-later-all-three")

    # 27. an unexpected correctness-bearing file change after the
    #     audited head fails (no allowlist entry)
    def test_c27_unexpected_later_file(self) -> None:
        self._later_change(
            {"scripts/issue117_arm_c_client.py": "# changed late\n"},
            "c27-unexpected-later-file")

    # 28. an allowlisted file whose final bytes do not match the
    #     allowlisted digest fails
    def test_c28_allowlist_digest_mismatch(self) -> None:
        audit = self.load("pre-execution-authority-audit.json")
        audit["post_audit_correction_allowlist"][
            "scripts/issue117_arm_c_blocker_reducer.py"][
            "sha256"] = "a" * 64
        self.save("pre-execution-authority-audit.json", audit)
        self._later_change(
            {"scripts/issue117_arm_c_blocker_reducer.py":
             "# changed with wrong pin\n"},
            "c28-allowlist-digest-mismatch")

    # 29. missing allowlist entirely fails
    def test_c29_missing_allowlist(self) -> None:
        audit = self.load("pre-execution-authority-audit.json")
        del audit["post_audit_correction_allowlist"]
        self.save("pre-execution-authority-audit.json", audit)
        self.require_fails_closed("c29-missing-allowlist")

    # 30. direct-6 retained validity relabeled true (Branch A) still
    #     derives the blocker — the terminal does not depend on the
    #     post-hoc validity judgment either way
    def test_c30_relabel_valid_still_blocked(self) -> None:
        doc = self.load("attempt-lineage.json")
        for a in doc["attempts"]:
            if a["attempt_id"] == "armc-direct-6":
                a["retained_validity_flag"] = True
                a["campaign_classification"] = "valid comparator"
        self.save("attempt-lineage.json", doc)
        # must NOT fail closed — Branch A is derivable — and must
        # still be the blocker
        result = self.reduce()
        self.assertNotIn("failed_closed", result)
        self.assertEqual(result.get("terminal"), self.br.BLOCKED)
        self.assertTrue(all(
            b["terminal"] == self.br.BLOCKED
            for b in result["branch_analysis"]["branches"]
            if b["derivable"]))


    # 31. rewriting the freeze commit itself so the FROZEN direct
    #     invocation is 2 (not 8) fails: the git-pinned methodology
    #     comparator text would no longer exist at the freeze
    def test_c31_frozen_freeze_direct_8_to_2(self) -> None:
        # rebuild the scratch history with a mutated freeze commit:
        # methodology+driver both carry max_new_tokens=2 at the freeze
        (self.repo / METHODOLOGY_REL).write_text(
            self.FROZEN_METHODOLOGY.replace(
                "max_new_tokens=8", "max_new_tokens=2"))
        (self.repo / DRIVER_REL).write_text(
            self.FROZEN_DRIVER.replace(
                "max_new_tokens=8", "max_new_tokens=2"))
        subprocess.run(["git", "-C", str(self.repo), "add", "-A"],
                       check=True)
        subprocess.run(
            ["git", "-C", str(self.repo), "commit", "-q", "-m",
             "rewrite freeze"], check=True, env=self.git_env)
        new_freeze = subprocess.check_output(
            ["git", "-C", str(self.repo), "rev-parse", "HEAD"],
            text=True).strip()
        os.environ["ARM_C_BLOCKER_FREEZE_SHA"] = new_freeze
        rr = self.load("run-record.json")
        rr["pre_execution_inferwarm_sha"] = new_freeze
        self.save("run-record.json", rr)
        audit = self.load("pre-execution-authority-audit.json")
        audit["claimed_pre_execution_inferswarm_sha"] = new_freeze
        for rel in (METHODOLOGY_REL, DRIVER_REL, REDUCER_REL):
            blob = subprocess.check_output(
                ["git", "-C", str(self.repo), "rev-parse",
                 f"{new_freeze}:{rel}"], text=True).strip()
            content = subprocess.check_output(
                ["git", "-C", str(self.repo), "cat-file", "blob",
                 f"{new_freeze}:{rel}"])
            entry = audit["frozen_correctness_bearing_files"][rel]
            entry["git_blob_sha_at_freeze"] = blob
            entry["sha256_at_freeze"] = hashlib.sha256(
                content).hexdigest()
        self.save("pre-execution-authority-audit.json", audit)
        self.require_fails_closed("c31-frozen-direct-8-to-2")

    # 32. a high-similarity RENAME of the frozen methodology after
    #     the audited head must fail even though plain `git diff
    #     --name-only` would list only the new path (review P1:
    #     rename-detection loophole; the reducer diffs with
    #     --no-renames so the deleted frozen path is enumerated)
    def test_c32_rename_frozen_methodology(self) -> None:
        moved = METHODOLOGY_REL + "-renamed.md"
        source = subprocess.check_output(
            ["git", "-C", str(self.repo), "cat-file", "blob",
             f"{self.audited_head}:{METHODOLOGY_REL}"], text=True)
        # near-identical content + a tuned line: rename detection
        # would classify this as R100/R09x against the deletion
        (self.repo / moved).write_text(source + "\n# tuned late\n")
        (self.repo / METHODOLOGY_REL).unlink()
        subprocess.run(["git", "-C", str(self.repo), "add", "-A"],
                       check=True)
        subprocess.run(
            ["git", "-C", str(self.repo), "commit", "-q", "-m",
             "rename frozen methodology"], check=True, env=self.git_env)
        # prove the attack premise: WITH rename detection the frozen
        # path disappears from the diff (only the new path shows)
        with_renames = subprocess.check_output(
            ["git", "-C", str(self.repo), "diff", "--name-only",
             f"{self.audited_head}..HEAD"], text=True).strip().splitlines()
        self.assertNotIn(METHODOLOGY_REL, with_renames)
        self.assertIn(moved, with_renames)
        # the reducer must still fail closed (deleted frozen path)
        self.require_fails_closed("c32-rename-frozen-methodology")


class TestRealEvidence(unittest.TestCase):
    """The retained physical evidence must derive the blocker through
    the REAL reducer against the REAL repository (no fakeroot)."""

    def test_retained_campaign_derives_blocker(self) -> None:
        os.environ.pop("ARM_C_BLOCKER_REPO", None)
        os.environ.pop("ARM_C_BLOCKER_FREEZE_SHA", None)
        os.environ.pop("ARM_C_BLOCKER_FROZEN_PINS", None)
        br = load_reducer()
        result = br.reduce_all()
        self.assertEqual(result["terminal"], br.BLOCKED)
        sem = result["frozen_invocation_semantics"]
        self.assertEqual(sem["direct"]["max_new_tokens"], 8)
        self.assertEqual(sem["direct"]["invocation"], "single-shot")
        self.assertEqual(sem["ordinary"]["max_new_tokens"], 2)
        self.assertIn("replay-prefix", sem["ordinary"]["invocation"])
        self.assertTrue(result["comparator_defect"]["defect"])
        self.assertEqual(result["branch_analysis"]["convergence"],
                         br.BLOCKED)
        self.assertEqual(
            result["observations"]["direct6"]
            ["exact_staged_driver_bytes"], "unknown / not retained")
        self.assertEqual(
            result["source_reads_frozen_rule"][
                "tokenizer_metadata_file_reads"], 4)
        self.assertFalse(result["observations"][
            "direct9_is_frozen_comparator"])


class TestFrozenPinsRealBytes(unittest.TestCase):
    """The sha256-pinned retained FreeToken bytes derive the ordinary
    semantics and fail closed on any mutation (no fakeroot)."""

    def setUp(self) -> None:
        os.environ.pop("ARM_C_BLOCKER_REPO", None)
        os.environ.pop("ARM_C_BLOCKER_FROZEN_PINS", None)
        spec = importlib.util.spec_from_file_location(
            "issue117_arm_c_frozen_pins",
            REPO / "scripts/issue117_arm_c_frozen_pins.py")
        self.pins = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.pins)

    def test_real_bytes_derive_replay_semantics(self) -> None:
        sem = self.pins.derive_invocation_semantics()
        self.assertEqual(sem["ordinary"]["max_new_tokens"], 2)
        self.assertEqual(
            sem["ordinary"]["runtime_generate_calls_per_case"], 8)
        self.assertIn("replay-prefix", sem["ordinary"]["invocation"])
        self.assertEqual(len(sem["pinned_sources"]), 3)

    def test_mnt2_mutation_fails_closed(self) -> None:
        path = REPO / self.pins.FROZEN_EPOCHS_REL
        original = path.read_bytes()
        self.addCleanup(path.write_bytes, original)
        path.write_bytes(original.replace(
            b"max_new_tokens=2,", b"max_new_tokens=9,", 1))
        with self.assertRaises(self.pins.FrozenSourceError):
            self.pins.derive_invocation_semantics()

    def test_replay_removal_mutation_fails_closed(self) -> None:
        path = REPO / self.pins.FROZEN_STRATEGY_REL
        original = path.read_bytes()
        self.addCleanup(path.write_bytes, original)
        path.write_bytes(original.replace(
            b"list(session.prompt_token_ids) + list("
            b"session.committed_token_ids)",
            b"list(session.prompt_token_ids)", 1))
        with self.assertRaises(self.pins.FrozenSourceError):
            self.pins.derive_invocation_semantics()



if __name__ == "__main__":
    unittest.main()
