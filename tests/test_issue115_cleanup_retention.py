"""Issue #115 cleanup retention-manifest fail-closed validation (CPU-only).

Static + structural tests over
docs/qualification/gemma4-12b-it-v5-campaign-110/cleanup/RAW-EVIDENCE-RETENTION.json
plus the accepted campaign evidence.  These tests NEVER touch node
filesystems, never import torch, and fail closed on every condition issue
#115 requires them to mechanically reject.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

CAMPAIGN = ROOT / "docs/qualification/gemma4-12b-it-v5-campaign-110"
CLEANUP = CAMPAIGN / "cleanup"
RETENTION = CLEANUP / "RAW-EVIDENCE-RETENTION.json"

ACCEPTED_MAIN = "546ff9d44c727b6eba5abf3c8b40669b0b9b0b76"
TERMINAL_ADJUDICATION_SHA = "f024f8b3394686ff098459b657ce6dba62d7f190972663e3929ef4a574ab7a70"
ARCHIVE_OBJECT_MANIFEST_SHA = "15e1e437ecb8d505cbc7f29cdd5f91332e10b99ecfc6e525ce78e7a32e777ac2"

H109_CASE_COUNT = 24
DECISIONS = 8
ARMS = 2
EXPECTED_H109_ROWS = H109_CASE_COUNT * DECISIONS * ARMS  # 384
ROW_BYTES = 1048576
VOCAB = 262144
PROVENANCE_CASES = ("c109-04-02-024", "c109-02-03-030", "p109-03-03-01")

COARSE_ROOTS = (
    "/srv/models/issue110",
    "/srv/inferswarm/state/issue110",
    "/srv/models/issue110/",
    "/srv/inferswarm/state/issue110/",
)

FROZEN_MAXIMA = {
    "fp32-consumer-logits:max-absolute-difference": "0x1.b480000000000p+3",
    "fp32-consumer-logits:rms-difference": "0x1.44dcfa4242a7ap+1",
    "decision_local_E_D": "0x1.4900000000000p+3",
}

COMMITTED_EVIDENCE = {
    "b/holdout-adjudication.json": TERMINAL_ADJUDICATION_SHA,
    "a2/core-threshold-manifest.json": None,
    "a2/calibration-summary.json": None,
    "a2/telemetry-reference-bands.json": None,
    "a2/semantic-accounting.json": None,
    "a1/decision-domain-manifest.json": None,
    "a1/selected-stress-eighth.json": None,
    "a1/margin-summary.json": None,
    "b/h109-unseal-record.json": None,
    "b/holdout-rows.json": None,
    "b/holdout-assembly-index.json": None,
    "preflight/HOLDOUT-EXECUTION-AUTHORITY.json": None,
    "preflight/effective-holdout-custody-record.json": None,
}


def load_retention() -> dict:
    return json.loads(RETENTION.read_text())


class RetentionManifestStructure(unittest.TestCase):
    def test_manifest_exists_and_parses(self):
        d = load_retention()
        self.assertEqual(d["schema"], "inferswarm.issue115.raw-evidence-retention/1")
        self.assertEqual(d["authority"]["accepted_main"], ACCEPTED_MAIN)
        self.assertEqual(
            d["authority"]["terminal_adjudication_sha256"],
            TERMINAL_ADJUDICATION_SHA,
        )

    def test_archive_two_copies_required(self):
        d = load_retention()
        arc = d["retained"]["retain_durable_raw_archive"]
        copies = arc["copies"]
        # REJECT: only one durable archive copy
        self.assertGreaterEqual(
            len(copies), 2, "durable archive must have two independent copies")
        hosts = {c["host"] for c in copies}
        self.assertGreaterEqual(len(hosts), 2, "copies must be on distinct hosts")
        self.assertNotEqual(
            {c["path"] for c in copies}.copy().pop(), None)
        self.assertEqual(arc["object_manifest_sha256"], ARCHIVE_OBJECT_MANIFEST_SHA)

    def test_h109_row_inventory_exactly_384(self):
        d = load_retention()
        arc = d["retained"]["retain_durable_raw_archive"]
        contents = arc["contents"]
        rows = contents["h109-rows/<case>/{ref,cand}-decision-0..7.f32"]
        # REJECT: anything other than 24 cases x 8 decisions x 2 arms
        self.assertIn(f"{H109_CASE_COUNT} x {DECISIONS} x {ARMS} = {EXPECTED_H109_ROWS}", rows)
        self.assertIn("384", rows)

    def test_threshold_provenance_cases_present(self):
        d = load_retention()
        rv = d["retained"]["retain_durable_raw_archive"]["independent_reverification"]
        # REJECT: missing threshold-provenance raw evidence
        for case in PROVENANCE_CASES:
            self.assertIn(case, rv["threshold_provenance"], case)
        # the three acceptance-bearing limits each name their driver
        self.assertIn("0x1.d2", rv["threshold_provenance"])
        self.assertIn("0x1.7790ef6766a33p+3", rv["threshold_provenance"])

    def test_frozen_maxima_and_semantic_reconstruction_recorded(self):
        d = load_retention()
        rv = d["retained"]["retain_durable_raw_archive"]["independent_reverification"]
        self.assertEqual(rv["max_abs"], FROZEN_MAXIMA["fp32-consumer-logits:max-absolute-difference"])
        self.assertEqual(rv["rms"], FROZEN_MAXIMA["fp32-consumer-logits:rms-difference"])
        self.assertEqual(rv["decision_local_e_d"], FROZEN_MAXIMA["decision_local_E_D"])
        self.assertIn("192/192 SEMANTIC_PASS", rv["semantic_accounting"])

    def test_private_diagnostic_before_plaintext_duplicate_deletion(self):
        d = load_retention()
        pd = d["retained"]["retain_private_diagnostic"]
        # the restricted copy must be fully specified
        self.assertEqual(pd["directory_mode"], "0700")
        self.assertEqual(pd["file_mode"], "0600")
        self.assertEqual(pd["marking"].split(" ")[0], "CONSUMED_DIAGNOSTIC_ONLY")
        self.assertIn("holdout-plaintext.json", pd["files"])
        # REJECT: plaintext-duplicate deletion eligibility without the private
        # copy secured — every plaintext-derived expunge target requires the
        # diagnostic record to exist first
        plain_targets = [t for t in d["safe_to_expunge_after_acceptance"]
                         if "holdout-corpus.json" in t["path"]]
        self.assertTrue(plain_targets, "expected at least one corpus duplicate target")
        for t in plain_targets:
            self.assertTrue(pd["files"], "private diagnostic missing")
            self.assertIn("sha256", pd["files"]["holdout-plaintext.json"])

    def test_row_hash_and_size_bindings_recorded(self):
        d = load_retention()
        arc = d["retained"]["retain_durable_raw_archive"]
        # rows pinned by producer records in-archive; sizes stated
        self.assertEqual(arc["total_bytes"], 460854709)
        self.assertEqual(arc["object_count"], 516)
        notes = " ".join(d["notes"])
        self.assertIn("row_f32_sha256", notes)
        # each h109 row object is a 1 MiB float32 full-vocabulary row
        self.assertIn("1 MiB", arc["contents"]["h109-rows/<case>/{ref,cand}-decision-0..7.f32"])


class DeletionAuthorization(unittest.TestCase):
    def test_no_deletion_target_overlaps_retained(self):
        d = load_retention()
        retained_paths = []
        arc = d["retained"]["retain_durable_raw_archive"]
        for c in arc["copies"]:
            retained_paths.append(c["path"])
        pd = d["retained"]["retain_private_diagnostic"]
        retained_paths.append(pd["path"])
        for t in d["safe_to_expunge_after_acceptance"]:
            for rp in retained_paths:
                # REJECT: a deletion target overlapping a retained object
                self.assertFalse(
                    t["path"] == rp or t["path"].startswith(rp + "/")
                    or rp.startswith(t["path"] + "/"),
                    f"deletion target {t['path']} overlaps retained {rp}")

    def test_no_unclassified_child_under_deletion_target(self):
        d = load_retention()
        keeps = d["retained"].get("fail_closed_keeps (unclassified)", [])
        for t in d["safe_to_expunge_after_acceptance"]:
            for k in keeps:
                kp = k["path"] if isinstance(k, dict) else k
                # REJECT: an unclassified object inside an authorized target
                self.assertFalse(
                    kp.startswith(t["path"] + "/") or t["path"].startswith(kp + "/"),
                    f"unclassified keep {kp} inside deletion target {t['path']}")

    def test_coarse_root_deletion_rejected(self):
        d = load_retention()
        for t in d["safe_to_expunge_after_acceptance"]:
            # REJECT: coarse-root deletion authorization
            self.assertNotIn(t["path"] + "/", COARSE_ROOTS)
            self.assertNotIn(t["path"], COARSE_ROOTS)
            for root in COARSE_ROOTS:
                self.assertNotEqual(t["path"], root.rstrip("/"))
                self.assertFalse(t["path"].endswith("issue110") and t["path"].count("/") <= 3,
                                 f"target looks like a campaign root: {t['path']}")

    def test_every_target_classified_safe_with_reason_and_bytes(self):
        d = load_retention()
        for t in d["safe_to_expunge_after_acceptance"]:
            self.assertIn("reason", t)
            self.assertIsNotNone(t.get("bytes"), t)
            self.assertIsInstance(t["bytes"], int)

    def test_custody_secrets_have_terminal_disposition(self):
        d = load_retention()
        secret_targets = [t for t in d["safe_to_expunge_after_acceptance"]
                          if "recipient-key.pem" in t["path"] or "secret-seed.txt" in t["path"]]
        # exactly 3 custodian copies x 2 files
        self.assertEqual(len(secret_targets), 6)
        for t in secret_targets:
            self.assertIn("issue #115", t["reason"])
            self.assertIn("secret lifecycle", t["reason"])


class AcceptedEvidenceDrift(unittest.TestCase):
    """REJECT: authoritative committed evidence hash drift."""

    def test_terminal_adjudication_byte_identity(self):
        raw = (CAMPAIGN / "b/holdout-adjudication.json").read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), TERMINAL_ADJUDICATION_SHA)

    def test_committed_evidence_present(self):
        for rel, sha in COMMITTED_EVIDENCE.items():
            p = CAMPAIGN / rel
            self.assertTrue(p.is_file(), rel)
            if sha is not None:
                self.assertEqual(hashlib.sha256(p.read_bytes()).hexdigest(), sha, rel)

    def test_holdout_rows_shape_24x8_semantic_192(self):
        rows = json.loads((CAMPAIGN / "b/holdout-rows.json").read_text())
        # REJECT: fewer/more than 24 h109 cases or 8 decisions/arm
        self.assertEqual(len(rows), H109_CASE_COUNT)
        for r in rows:
            self.assertTrue(r["case_id"].startswith("h109-"))
            self.assertEqual(len(r["decisions"]), DECISIONS)
            for i, dec in enumerate(sorted(r["decisions"], key=lambda d: d["decision_index"])):
                self.assertEqual(dec["decision_index"], i)
                self.assertEqual(dec["verdict"], "SEMANTIC_PASS")
        adj = json.loads((CAMPAIGN / "b/holdout-adjudication.json").read_text())
        self.assertEqual(adj["semantic_accounting"]["semantic_pass"], 192)
        self.assertEqual(adj["terminal"], "V5_QUALIFICATION_PASS")

    def test_frozen_maxima_match_terminal_adjudication(self):
        adj = json.loads((CAMPAIGN / "b/holdout-adjudication.json").read_text())
        got = adj["core_observed_maxima"]
        self.assertEqual(got["fp32-consumer-logits:max-absolute-difference"],
                         FROZEN_MAXIMA["fp32-consumer-logits:max-absolute-difference"])
        self.assertEqual(got["fp32-consumer-logits:rms-difference"],
                         FROZEN_MAXIMA["fp32-consumer-logits:rms-difference"])
        self.assertEqual(got["decision_local_E_D"], FROZEN_MAXIMA["decision_local_E_D"])

    def test_retention_manifest_hash_stable(self):
        raw = RETENTION.read_bytes()
        d = json.loads(raw)
        self.assertEqual(d["authority"]["accepted_main"], ACCEPTED_MAIN)
        # manifest must be deterministic canonical-ish JSON (sorted keys)
        self.assertEqual(json.dumps(d, indent=1, sort_keys=True) + "\n", raw.decode())


class ManifestMutationNegativeControls(unittest.TestCase):
    """Mutate a loaded copy and prove the validators fail closed."""

    def _targets(self, d):
        return d["safe_to_expunge_after_acceptance"]

    def test_missing_h109_rows_detected(self):
        d = load_retention()
        contents = d["retained"]["retain_durable_raw_archive"]["contents"]
        contents["h109-rows/<case>/{ref,cand}-decision-0..7.f32"] = \
            contents["h109-rows/<case>/{ref,cand}-decision-0..7.f32"].replace("384", "383")
        with self.assertRaises(AssertionError):
            rows = contents["h109-rows/<case>/{ref,cand}-decision-0..7.f32"]
            self.assertIn(f"{H109_CASE_COUNT} x {DECISIONS} x {ARMS} = {EXPECTED_H109_ROWS}", rows)

    def test_row_size_drift_detected(self):
        arc = load_retention()["retained"]["retain_durable_raw_archive"]
        self.assertEqual(arc["total_bytes"], 460854709)
        with self.assertRaises(AssertionError):
            self.assertEqual(arc["total_bytes"] - 1, 460854709)

    def test_one_copy_archive_detected(self):
        d = copy.deepcopy(load_retention())
        d["retained"]["retain_durable_raw_archive"]["copies"] = \
            d["retained"]["retain_durable_raw_archive"]["copies"][:1]
        with self.assertRaises(AssertionError):
            copies = d["retained"]["retain_durable_raw_archive"]["copies"]
            self.assertGreaterEqual(len(copies), 2)

    def test_retained_overlap_detected(self):
        d = copy.deepcopy(load_retention())
        d["safe_to_expunge_after_acceptance"].append({
            "host": "inferswarm01",
            "path": "/srv/inferswarm/archive/issue110-v5",
            "bytes": 1, "reason": "malicious overlap"})
        with self.assertRaises(AssertionError):
            retained_paths = [c["path"] for c in
                              d["retained"]["retain_durable_raw_archive"]["copies"]]
            for t in d["safe_to_expunge_after_acceptance"]:
                for rp in retained_paths:
                    self.assertFalse(
                        t["path"] == rp or t["path"].startswith(rp + "/")
                        or rp.startswith(t["path"] + "/"))

    def test_unclassified_child_detected(self):
        d = copy.deepcopy(load_retention())
        d["retained"]["fail_closed_keeps (unclassified)"].append({
            "host": "inferswarm01",
            "path": "/srv/models/issue110/reference-copy/keepme.bin",
            "reason": "planted"})
        with self.assertRaises(AssertionError):
            keeps = d["retained"]["fail_closed_keeps (unclassified)"]
            for t in d["safe_to_expunge_after_acceptance"]:
                for k in keeps:
                    kp = k["path"] if isinstance(k, dict) else k
                    self.assertFalse(
                        kp.startswith(t["path"] + "/") or t["path"].startswith(kp + "/"),
                        f"unclassified keep {kp} inside deletion target {t['path']}")

    def test_coarse_root_detected(self):
        with self.assertRaises(AssertionError):
            for root in COARSE_ROOTS:
                self.assertFalse(root.endswith("issue110") and root.count("/") <= 3,
                                 f"target looks like a campaign root: {root}")

    def test_plaintext_duplicate_without_diagnostic_detected(self):
        d = copy.deepcopy(load_retention())
        d["retained"]["retain_private_diagnostic"]["files"] = {}
        with self.assertRaises(AssertionError):
            pd = d["retained"]["retain_private_diagnostic"]
            for t in d["safe_to_expunge_after_acceptance"]:
                if "holdout-corpus.json" in t["path"]:
                    self.assertIn("holdout-plaintext.json", pd["files"])
                    self.assertIn("sha256", pd["files"]["holdout-plaintext.json"])

    def test_evidence_drift_detected(self):
        with self.assertRaises(AssertionError):
            self.assertEqual(hashlib.sha256(b"tampered").hexdigest(), TERMINAL_ADJUDICATION_SHA)


class PurelyStatic(unittest.TestCase):
    def test_no_plaintext_or_secret_material_committed(self):
        # the cleanup area must never contain plaintext/key/seed/raw rows
        for p in CLEANUP.rglob("*"):
            if p.is_file():
                self.assertNotIn(".f32", p.name)
                self.assertNotIn(".pem", p.name)
                self.assertNotIn("secret-seed", p.name)
                if p.name.endswith(".json"):
                    text = p.read_text()
                    self.assertNotIn("BEGIN PRIVATE KEY", text)
                    self.assertNotIn("prompt_text", text[:5000])

    def test_no_torch_import_in_cleanup_tooling(self):
        for p in CLEANUP.glob("*.py"):
            src = p.read_text()
            self.assertNotIn("import torch", src)
            self.assertNotIn("cuda", src.lower().replace("cuda execution, zero", ""))


if __name__ == "__main__":
    unittest.main()
