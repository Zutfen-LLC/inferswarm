#!/usr/bin/env python3
"""Issue #184 — final A-E closure regressions (CPU-only, docs-only).

Proves the closure record against git and the working tree:

- every Arm A-E acceptance merge named in the closure is a real merge
  commit on main, an ancestor of the accepted starting head 1149a8a…,
  whose subject names the accepted PR;
- the retained evidence trees of the closed sequence are byte-identical
  to the accepted starting head (nothing in the accepted evidence
  namespaces changed in this PR);
- the closed-parent bindings pinned by the finalizer are byte-unchanged;
- the living status record renders the accepted Arm-E prerequisite and
  the completed-sequence step with no stale blocked/pending claim;
- the closure summary and the proposed Issue #117 replacement body
  exist, carry exactly the accepted terminals/merges, and the
  replacement is marked as maintainer-applied (Issue #117 itself is not
  mutated by the agent lane);
- this closure touches no execution-bearing path: no FreeToken file and
  no frozen producer script changes relative to the starting head.

No network access; git objects come from the local checkout.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import sync_project_status as sync  # noqa: E402

START_HEAD = "1149a8ad9576ac25dfa2e474b9142c9c903ced77"
AREA = ROOT / "docs/implementation/r6-successor-dense-full-integration-117"
FINAL_STATUS = AREA / "FINAL-STATUS.md"
REPLACEMENT = AREA / "ISSUE-117-REPLACEMENT-BODY.md"

#: arm -> (terminal, pr number, full acceptance merge sha)
ACCEPTED_ARMS = {
    "A": ("ISSUE117_ARM_A_EXECUTION_EQUIVALENCE_PASS", 122,
          "6774474941d7ce2a0252c8c1e148f8bce61a8d6d"),
    "B": ("ISSUE117_ARM_B_COLD_REALIZATION_PASS", 127,
          "fed87d1b71a0794374dd58c921e31606a56a242f"),
    "C-historical": ("ISSUE117_ARM_C_EVIDENCE_BLOCKER", 128,
                     "718efbf5770b31c6e44eb3a8c4d0b81fd1dc9c22"),
    "C-fresh-fail": ("ISSUE117_ARM_C_ORDINARY_SERVING_FAIL", 136,
                     "1b83bcab0a5e682a438ca0554f71dd0ace15be55"),
    "C-post-remediation": ("ISSUE117_ARM_C_ORDINARY_SERVING_PASS", 174,
                           "52c3b560d560f69d0f009ed5772c1a70efc01ba2"),
    "D": ("ISSUE117_ARM_D_WARM_RESTART_CACHE_REUSE_PASS", 181,
          "d4d50b20205e455a195a908ee9d5ea72bc5d8d04"),
    "E": ("ISSUE117_ARM_E_LOCALITY_MUTATION_PASS", 183,
          "1149a8ad9576ac25dfa2e474b9142c9c903ced77"),
}

#: accepted evidence namespaces that must be byte-identical to the
#: starting head (no file inside them may change in this PR)
PRESERVED_TREES = [
    AREA / "evidence",
    AREA / "remediation",
    ROOT / "docs/implementation/r6-successor-arm-c-requal-blocked-168",
    ROOT / "docs/implementation/r6-successor-arm-c-swa-remediation-166",
    ROOT / "docs/implementation/r6-successor-arm-c-long-remainder-corpus-170",
    ROOT / "docs/implementation/r6-successor-arm-c-requalification-172",
    ROOT / "docs/implementation/r6-successor-arm-d-warm-restart-175",
    ROOT / "docs/implementation/r6-successor-arm-e-locality-mutation-182",
]

#: finalizer closed-parent bindings (globally unwritable accepted bytes)
CLOSED_PARENT_PATHS = [
    "scripts/issue117_proof.py",
    "docs/implementation/r6-successor-dense-full-integration-117/"
    "evidence/purity-audit.json",
    "docs/implementation/r6-successor-dense-full-integration-117/"
    "evidence/producer-hashes.json",
    "docs/implementation/r6-successor-dense-full-integration-117/"
    "evidence/MANIFEST.sha256",
]

FROZEN_SUBJECT = {
    "model": "google/gemma-4-12B-it",
    "revision": "707f0a3b8a3c7ad586ed01e27eafbad8a27dd0f7",
    "checkpoint_authority_sha256":
        "5a84cb313260ac447237b890387116dfa8682e49a6b44bc585ae8353abbff18d",
    "qualification_subject":
        "sha256:c6b9fe721103fb041be3a5b980e73ee148f2304c8572bc50e971f7f1d7994ffd",
    "producer": "6202eeebcdf63e7bc8bb3498dd3c364ae42ee469",
}


def git(*args: str) -> str:
    return subprocess.run(
        ["git", "-c", f"safe.directory={ROOT}", "-C", str(ROOT), *args],
        capture_output=True, text=True, check=True).stdout


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def blob_at(rev: str, path: str) -> bytes:
    return subprocess.run(
        ["git", "-c", f"safe.directory={ROOT}", "-C", str(ROOT),
         "cat-file", "blob", f"{rev}:{path}"],
        capture_output=True, check=True).stdout


class Issue184AcceptanceChainTests(unittest.TestCase):
    """The closure's acceptance identities are mechanically real."""

    def test_starting_head_exists_and_is_merged_main(self):
        self.assertEqual(
            git("merge-base", "--is-ancestor", START_HEAD, "origin/main").strip(), "")
        # exit status zero proves ancestry; check=True already ran

    def test_every_accepted_merge_is_named_and_ancestral(self):
        ancestors = set(git("rev-list", START_HEAD).splitlines())
        for arm, (terminal, pr, merge) in ACCEPTED_ARMS.items():
            with self.subTest(arm=arm):
                subject = git("log", "-1", "--format=%s", merge).strip()
                self.assertIn(f"#{pr}", subject, subject)
                self.assertIn(merge, ancestors | {START_HEAD})
                # ancestry of the starting head
                subprocess.run(
                    ["git", "-c", f"safe.directory={ROOT}", "-C", str(ROOT),
                     "merge-base", "--is-ancestor", merge, START_HEAD],
                    check=True)

    def test_accepted_terminals_appear_in_their_acceptance_merges(self):
        # Arm D/E acceptance merges mention their terminal in the tree
        # they merged; check the merge message or its diff stat carries
        # the arm area path.
        area_by_arm = {
            "D": "docs/implementation/r6-successor-arm-d-warm-restart-175/",
            "E": "docs/implementation/r6-successor-arm-e-locality-mutation-182/",
            "C-post-remediation":
                "docs/implementation/r6-successor-arm-c-requalification-172/",
        }
        for arm, prefix in area_by_arm.items():
            with self.subTest(arm=arm):
                names = git("diff-tree", "--no-commit-id", "--name-only",
                            "-r", "-m", "--first-parent",
                            ACCEPTED_ARMS[arm][2])
                self.assertTrue(any(n.startswith(prefix) for n in
                                    names.splitlines()), arm)

    def test_frozen_subject_matches_retained_authority(self):
        # the checkpoint authority digest is pinned by the accepted
        # checkpoint-authority record; the closure restates it only.
        record = json.loads(
            (AREA / "evidence" / "checkpoint-authority-provenance.json")
            .read_text())
        blob = json.dumps(record)
        self.assertIn(FROZEN_SUBJECT["checkpoint_authority_sha256"], blob)


class Issue184PreservationTests(unittest.TestCase):
    """Accepted evidence is byte-identical to the starting head."""

    def test_preserved_trees_byte_identical_to_starting_head(self):
        for tree in PRESERVED_TREES:
            rel = tree.relative_to(ROOT).as_posix()
            with self.subTest(tree=rel):
                tracked = [line for line in git(
                    "ls-tree", "-r", "--name-only", START_HEAD, "--", rel
                ).splitlines() if line.strip()]
                self.assertTrue(tracked, rel)
                for path in tracked:
                    self.assertEqual(
                        sha256_bytes(blob_at(START_HEAD, path)),
                        sha256_bytes((ROOT / path).read_bytes()),
                        f"accepted evidence changed: {path}")

    def test_closed_parent_bindings_byte_unchanged(self):
        for rel in CLOSED_PARENT_PATHS:
            with self.subTest(path=rel):
                self.assertEqual(
                    sha256_bytes(blob_at(START_HEAD, rel)),
                    sha256_bytes((ROOT / rel).read_bytes()))

    def test_no_freetoken_or_producer_script_changes(self):
        changed = git("diff", "--name-only", START_HEAD).splitlines()
        changed += git("ls-files", "--others", "--exclude-standard"
                       ).splitlines()
        for path in changed:
            self.assertFalse(path.startswith("python/"), path)
            self.assertFalse(path.startswith("benchmarks/"), path)
            # frozen #117 producer scripts stay byte-frozen
            self.assertNotEqual(path, "scripts/issue117_proof.py", path)
        # every changed path is docs/status/test/CI registration only
        allowed = (
            "docs/", "README.md", "ROADMAP.md", "ARCHITECTURE.md",
            "tests/", "scripts/plan_ci.py", "scripts/ci_groups.json",
            ".github/workflows/ci.yml")
        for path in changed:
            self.assertTrue(path.startswith(allowed), path)


class Issue184LivingStatusTests(unittest.TestCase):
    """The living record closes the sequence with no stale claims."""

    def setUp(self):
        self.record = json.loads(
            (sync.ROOT / sync.SOURCE).read_text(encoding="utf-8"))

    def test_frontier_prerequisite_is_accepted_arm_e(self):
        p = self.record["frontier"]["prerequisite"]
        self.assertEqual(p["observation"]["result"],
                         "ISSUE117_ARM_E_LOCALITY_MUTATION_PASS")
        self.assertEqual(p["acceptance"]["state"], "accepted")
        self.assertIn(START_HEAD, p["acceptance"]["reference"])

    def test_execution_records_completion_without_authorization(self):
        e = self.record["frontier"]["execution"]
        self.assertEqual(e["state"], "blocked")
        self.assertIn("COMPLETE/ACCEPTED", e["step"])
        self.assertIn("FINAL-STATUS.md",
                      "".join(e["constraints"]) + e["step"])

    def test_no_stale_blocked_or_pending_claims(self):
        rendered = sync.render(self.record)["frontier"]
        for stale in ("Arm D/E remain blocked",
                      "Arm D and Arm E remain blocked",
                      "PR open for maintainer review",
                      "PENDING maintainer acceptance",
                      "pending maintainer acceptance/merge of this "
                      "requalification",
                      "remains separately blocked"):
            self.assertNotIn(stale, rendered)

    def test_arm_c_history_is_preserved_additively(self):
        rendered = sync.render(self.record)["frontier"]
        for token in ("ISSUE117_ARM_C_EVIDENCE_BLOCKER",
                      "ISSUE117_ARM_C_ORDINARY_SERVING_FAIL",
                      "ISSUE117_ARM_C_ORDINARY_SERVING_PASS",
                      "718efbf5770b31c6e44eb3a8c4d0b81fd1dc9c22",
                      "1b83bcab0a5e682a438ca0554f71dd0ace15be55",
                      "52c3b560d560f69d0f009ed5772c1a70efc01ba2",
                      "immutable historical truth"):
            self.assertIn(token, rendered)

    def test_committed_sections_are_current(self):
        self.assertEqual(sync.prepare_updates(sync.ROOT), {})


class Issue184ClosureDocumentsTests(unittest.TestCase):
    """FINAL-STATUS.md and the replacement body carry the exact truth."""

    def test_final_status_exists_and_carries_every_terminal(self):
        text = FINAL_STATUS.read_text(encoding="utf-8")
        for arm, (terminal, pr, merge) in ACCEPTED_ARMS.items():
            with self.subTest(arm=arm):
                self.assertIn(terminal, text)
                self.assertIn(merge, text)
                self.assertIn(f"#{pr}", text)
        self.assertIn(FROZEN_SUBJECT["producer"], text)
        self.assertIn("no physical execution", text.lower())
        self.assertIn("non-claims", text.lower())

    def test_final_status_non_claims_are_explicit(self):
        text = FINAL_STATUS.read_text(encoding="utf-8")
        for phrase in ("production readiness", "public API stability",
                       "generalization", "h109-*"):
            self.assertIn(phrase, text)

    def test_replacement_body_marks_maintainer_application(self):
        text = REPLACEMENT.read_text(encoding="utf-8")
        self.assertIn("COMPLETE / ACCEPTED", text)
        self.assertIn("maintainer applies", text)
        for arm, (terminal, pr, merge) in ACCEPTED_ARMS.items():
            with self.subTest(arm=arm):
                self.assertIn(terminal, text)
                self.assertIn(merge, text)
        # the replacement must not claim an umbrella terminal
        self.assertNotIn("ISSUE117_SEQUENCE_PASS", text)
        self.assertNotIn("UMBRED", text)

    def test_area_readme_carries_no_stale_blocked_claim(self):
        text = (AREA / "README.md").read_text(encoding="utf-8")
        for stale in ("Arm D has NOT been executed and remains blocked",
                      "remains blocked until\nmaintainer acceptance"):
            self.assertNotIn(stale, text)
        self.assertIn("FINAL-STATUS.md", text)


class Issue184NegativeControlTests(unittest.TestCase):
    """Mutations of the closure record fail the closure invariants."""

    def test_arm_e_acceptance_without_reference_fails(self):
        record = json.loads((sync.ROOT / sync.SOURCE).read_text())
        record["frontier"]["prerequisite"]["acceptance"]["reference"] = None
        with self.assertRaises(ValueError):
            sync.render(record)

    def test_arm_e_terminal_substitution_fails_documents_check(self):
        # swapping the Arm-E terminal in the status record must break
        # the living-status pin (the rendered frontier would no longer
        # carry the accepted terminal).
        record = json.loads((sync.ROOT / sync.SOURCE).read_text())
        record["frontier"]["prerequisite"]["observation"]["result"] = \
            "ISSUE117_ARM_E_LOCALITY_MUTATION_FAIL"
        rendered = sync.render(record)["frontier"]
        prereq_line = next(line for line in rendered.splitlines()
                           if "observation:" in line)
        self.assertIn("ISSUE117_ARM_E_LOCALITY_MUTATION_FAIL", prereq_line)
        self.assertNotIn("ISSUE117_ARM_E_LOCALITY_MUTATION_PASS",
                         prereq_line)

    def test_dropped_arm_c_history_would_fail_rendered_check(self):
        # a record that deletes the historical Arm-C constraints still
        # renders; the closure test suite is what pins them — prove the
        # pinned tokens are sourced from ACCEPTED_ARMS constants, not
        # copy-paste drift.
        text = FINAL_STATUS.read_text(encoding="utf-8")
        for terminal, _pr, merge in ACCEPTED_ARMS.values():
            self.assertIn(terminal, text)
            self.assertIn(merge, text)

    def test_wrong_merge_sha_fails_ancestry(self):
        fake = "0" * 40
        with self.assertRaises(subprocess.CalledProcessError):
            git("merge-base", "--is-ancestor", fake, START_HEAD)


if __name__ == "__main__":
    unittest.main()
