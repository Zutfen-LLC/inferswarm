"""Dispatch-capture custody contracts (CPU-only; never physical authority)."""
from __future__ import annotations
import unittest

from tests.test_issue252_physical import FixtureMixin, A, C, CAP


class CaptureTests(FixtureMixin, unittest.TestCase):
    def setUp(self):
        self.fixture()

    def test_build_and_verify_positive(self):
        cap = self.capture("A2")
        verified = CAP.verify_capture(cap, self.fetcher("A2"),
                                      repo_pr_number=C.CAMPAIGN_PR, _test_only=True)
        self.assertEqual(verified["arm"], "A2")
        self.assertEqual(verified["comment_id"], cap["comment_id"])

    def test_review_inline_comment_provenance_rejected(self):
        # A review comment payload shape: html_url under a review, not a
        # top-level PR conversation comment. Representable provenance must be
        # refused even when all other fields are internally consistent.
        c = self.comment("A2")
        forged = dict(c)
        forged["html_url"] = (
            "https://github.com/Zutfen-LLC/inferswarm/pull/253#pullrequestreview-1")
        forged["pull_request_review_id"] = 555
        with self.assertRaisesRegex(CAP.CaptureInvalid, "html_url"):
            CAP.build_capture(forged, pr=forged["pr"], issue=forged["issue"],
                              repo_pr_number=C.CAMPAIGN_PR)

    def test_issue252_timeline_comment_rejected_at_body_law(self):
        c = self.comment("A2")
        forged = dict(c)
        forged["issue_url"] = (
            "https://api.github.com/repos/Zutfen-LLC/inferswarm/issues/252")
        with self.assertRaisesRegex(CAP.CaptureInvalid, "top-level PR conversation"):
            CAP.build_capture(forged, pr=forged["pr"], issue=forged["issue"],
                              repo_pr_number=C.CAMPAIGN_PR)

    def test_wrong_repository_comment_rejected(self):
        c = self.comment("A2")
        forged = dict(c)
        forged["issue_url"] = "https://api.github.com/repos/evil/org/issues/253"
        forged["html_url"] = "https://github.com/evil/org/pull/253#issuecomment-9"
        with self.assertRaisesRegex(CAP.CaptureInvalid, "top-level PR conversation"):
            CAP.build_capture(forged, pr=forged["pr"], issue=forged["issue"],
                              repo_pr_number=C.CAMPAIGN_PR)

    def test_fabricated_association_rejected_at_body_law(self):
        c = self.comment("A2")
        forged = dict(c)
        forged["author_association"] = "FIRST_TIMER"
        with self.assertRaisesRegex(CAP.CaptureInvalid, "OWNER/MEMBER"):
            CAP.build_capture(forged, pr=forged["pr"], issue=forged["issue"],
                              repo_pr_number=C.CAMPAIGN_PR)

    def test_capture_pr_state_law(self):
        for field, value in (("merged", True), ("draft", True), ("state", "closed")):
            with self.subTest(field=field):
                c = self.comment("A2")
                c["pr"][field] = value
                with self.assertRaisesRegex(CAP.CaptureInvalid, "PR is not"):
                    CAP.build_capture(c, pr=c["pr"], issue=c["issue"],
                                      repo_pr_number=C.CAMPAIGN_PR)

    def test_capture_pr_head_must_equal_authorized_head(self):
        c = self.comment("A2")  # body head == self.head
        c["pr"]["head"]["sha"] = "e" * 40  # live PR head elsewhere
        with self.assertRaisesRegex(CAP.CaptureInvalid, "PR head"):
            CAP.build_capture(c, pr=c["pr"], issue=c["issue"],
                              repo_pr_number=C.CAMPAIGN_PR)

    def test_capture_issue_must_be_open_252(self):
        c = self.comment("A2")
        c["issue"]["state"] = "closed"
        with self.assertRaisesRegex(CAP.CaptureInvalid, "issue"):
            CAP.build_capture(c, pr=c["pr"], issue=c["issue"],
                              repo_pr_number=C.CAMPAIGN_PR)

    def test_verify_rejects_nonexistent_comment_id(self):
        cap = self.capture("A2")
        cap["comment_id"] = 424242  # no re-fetchable comment behind it
        with self.assertRaisesRegex(CAP.CaptureInvalid, "not found|differs"):
            CAP.verify_capture(cap, self.fetcher("A2"), repo_pr_number=C.CAMPAIGN_PR, _test_only=True)

    def test_verify_rejects_altered_retained_digest(self):
        cap = self.capture("A2")
        cap["raw_comment_sha256"] = "0" * 64
        with self.assertRaisesRegex(CAP.CaptureInvalid, "bytes differ from retained"):
            CAP.verify_capture(cap, self.fetcher("A2"), repo_pr_number=C.CAMPAIGN_PR, _test_only=True)

    def test_verify_rejects_wrong_pr_number_binding(self):
        cap = self.capture("A2")
        with self.assertRaisesRegex(CAP.CaptureInvalid, "PR number"):
            CAP.verify_capture(cap, self.fetcher("A2"), repo_pr_number=999, _test_only=True)

    def test_verify_rejects_exec_time_state_drift(self):
        cap = self.capture("A2")
        cap["execution_time_state"]["pr_head"] = "e" * 40
        with self.assertRaisesRegex(CAP.CaptureInvalid, "execution-time state"):
            CAP.verify_capture(cap, self.fetcher("A2"), repo_pr_number=C.CAMPAIGN_PR, _test_only=True)

    def test_structural_law_rejects_legacy_dict(self):
        legacy = {"head_sha": self.head, "arm": "A1",
                  "namespace": A.ARMS["A1"]["namespace"], "comment_id": 12,
                  "body": f"{C.DISPATCH_PHRASE_FORMAT}\nhead={self.head}\narm=A1",
                  "body_sha256": "0" * 64, "author_association": "OWNER"}
        with self.assertRaisesRegex(CAP.CaptureInvalid, "schema"):
            CAP.validate_capture_structure(legacy)

    def test_canonical_bytes_cover_all_auth_fields(self):
        c = self.comment("A2")
        raw = CAP.canonical_bytes(c)
        doc = eval(raw.decode())  # canonical JSON of scalars only
        self.assertEqual(set(doc), {"author_association", "body", "created_at",
                                    "html_url", "id", "issue_url", "user"})

    def test_moved_head_capture_rejected_by_verify(self):
        cap = self.capture("A2")
        cap["head_sha"] = "f" * 40
        cap["body"] = f"{C.DISPATCH_PHRASE_FORMAT}\nhead={'f' * 40}\narm=A2"
        cap["execution_time_state"]["pr_head"] = "f" * 40
        with self.assertRaisesRegex(CAP.CaptureInvalid, "differs"):
            CAP.verify_capture(cap, self.fetcher("A2"), repo_pr_number=C.CAMPAIGN_PR, _test_only=True)


if __name__ == "__main__":
    unittest.main()
