"""Retention regressions for the Issue #117 physical-preflight PASS artifacts.

These tests pin the retained physical-preflight evidence inside the
repository's integrity boundary:

- ``physical-preflight.json`` (the frozen-validator-assembled record) and the
  compact/digested retention artifacts must exist, be byte-exact against the
  retained MANIFEST, and carry valid record digests;
- per-host FreeToken preflight-time identities must cover exactly the
  orchestrator + inferswarm01/03/04 host set, each mechanically digest-bound,
  each at the exact frozen producer with empty porcelain;
- the Coordinator zero invariants must carry mechanical derivation inputs
  (CUDA device/process/torch observations + per-root weight-byte accounting)
  whose derived totals equal the recorded zeroes;
- the accepted #118 canonical summary must remain byte-exact.
"""
import hashlib
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from issue99_artifact_core import self_digest  # noqa: E402
import issue117_proof as proof  # noqa: E402
import issue117_applicability as applicability  # noqa: E402

EVIDENCE = ROOT / "docs/implementation/r6-successor-dense-full-integration-117" / "evidence"
PHYSICAL_ARTIFACTS = (
    "physical-preflight.json",
    "physical-preflight-record.json",
    "physical-preflight-freetoken-identities.json",
    "physical-preflight-coordinator-accounting.json",
)
EXPECTED_HOSTS = {"orchestrator", "inferswarm01", "inferswarm03", "inferswarm04"}
PREFLIGHT_RECORD_SHA256 = (
    "e9711969a4443f9ea6f3287a06383b8e0d9ef2478f65059acce0e787f8fe0a06")
PREFLIGHT_DIGEST = (
    "sha256:bf7e0b312c8cb34ba5ced1c205039374dc018dbbbeba3cd9d2652a7b23a49e93")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def manifest_entries() -> dict[str, str]:
    entries = {}
    for line in (EVIDENCE / "MANIFEST.sha256").read_text().splitlines():
        digest, relative = line.split("  ", 1)
        entries[relative] = digest
    return entries


class PhysicalPreflightManifestTests(unittest.TestCase):
    def test_physical_artifacts_exist_and_are_manifest_exact(self):
        entries = manifest_entries()
        for name in PHYSICAL_ARTIFACTS:
            path = EVIDENCE / name
            self.assertTrue(path.is_file(), f"missing physical artifact {name}")
            relative = str(path.relative_to(ROOT))
            self.assertIn(relative, entries, f"{name} not in MANIFEST")
            self.assertEqual(entries[relative], sha256_file(path),
                             f"{name} bytes drift from MANIFEST")

    def test_frozen_preflight_file_and_digest_are_pinned(self):
        self.assertEqual(
            sha256_file(EVIDENCE / "physical-preflight.json"),
            PREFLIGHT_RECORD_SHA256)
        document = json.loads((EVIDENCE / "physical-preflight.json").read_text())
        self.assertEqual(document["preflight_digest"], PREFLIGHT_DIGEST)
        self.assertEqual(document["preflight_digest"],
                         self_digest(document, identity_field="preflight_digest"))

    def test_manifest_covers_exactly_the_expected_entry_set(self):
        # the regenerated manifest (proof.write_manifest convention) must
        # still match the checkout exactly, now including the physical rows
        entries = manifest_entries()
        expected = {
            *(str(proof.AREA / "evidence" / name) for name in proof.EVIDENCE_FILES),
            *(str(proof.AREA / "evidence" / name)
              for name in proof.COMMITTED_EVIDENCE_FILES),
            *proof.PRODUCERS,
            str(proof.AREA / "METHODOLOGY.md"),
            str(proof.AREA / "README.md"),
            str(proof.AREA / "METHODOLOGY-ARM-C-RETRY.md"),
            str(proof.AREA / "CHECKPOINT-AUTHORITY-BLOCKER.md"),
            ".github/workflows/ci.yml",
        }
        self.assertEqual(set(entries), expected)
        for relative, digest in entries.items():
            self.assertEqual(digest, sha256_file(ROOT / relative), relative)

    def test_accepted_118_canonical_summary_remains_byte_exact(self):
        self.assertEqual(
            sha256_file(EVIDENCE / "canonical-summary.json"),
            proof.ACCEPTED_118_CANONICAL_SUMMARY_SHA256)


class FreeTokenIdentityEvidenceTests(unittest.TestCase):
    def load(self):
        return json.loads(
            (EVIDENCE / "physical-preflight-freetoken-identities.json").read_text())

    def test_exactly_the_expected_host_set(self):
        checkouts = self.load()["freetoken_checkouts"]
        self.assertEqual(set(checkouts), EXPECTED_HOSTS)

    def test_every_record_is_digest_bound_and_untampered(self):
        document = self.load()
        self.assertEqual(
            document["record_digest"],
            self_digest(document, identity_field="record_digest"))

    def test_every_host_is_exact_frozen_producer_and_clean(self):
        checkouts = self.load()["freetoken_checkouts"]
        for host, record in checkouts.items():
            self.assertEqual(
                record["observed_head"],
                applicability.FROZEN_INTEGRATION_PRODUCER,
                f"{host}: HEAD is not the frozen integration producer")
            self.assertEqual(record["status_porcelain"], "",
                             f"{host}: porcelain is not empty")
            self.assertTrue(record["clean"], f"{host}: not clean")
            for field in ("host", "checkout_path", "collected_utc",
                          "collector_command_identity", "evidence_source"):
                self.assertTrue(record.get(field), f"{host}: missing {field}")

    def test_preflight_window_bracketing(self):
        document = self.load()
        start = document["preflight_window"]["start"]
        end = document["preflight_window"]["end"]
        for host, record in document["freetoken_checkouts"].items():
            if host == "orchestrator":
                # the orchestrator checkout was verified BEFORE preparation
                # began (it is not modified by node preparation) and was
                # never touched during the window; its observation may
                # legitimately precede the window start.
                self.assertLessEqual(record["collected_utc"], end,
                                     f"{host}: observation follows the window")
                self.assertIn("never modified during the preflight",
                              record["collector_command_identity"],
                              "pre-window observation must document "
                              "unchanged-through-window status")
            else:
                self.assertLessEqual(start, record["collected_utc"],
                                     f"{host}: observation precedes the window")
                self.assertLessEqual(record["collected_utc"], end,
                                     f"{host}: observation follows the window")

    def test_missing_duplicate_or_wrong_hosts_fail(self):
        document = self.load()
        checkouts = document["freetoken_checkouts"]
        # duplicate-host shape (a repeated host key collapses in JSON; the
        # equivalent failure is an unexpected extra/missing host)
        self.assertEqual(len(checkouts), 4)
        wrong = json.loads(json.dumps(document))
        wrong["freetoken_checkouts"]["inferswarm05"] = dict(
            wrong["freetoken_checkouts"]["inferswarm03"], host="inferswarm05")
        self.assertNotEqual(set(wrong["freetoken_checkouts"]), EXPECTED_HOSTS)
        drifted = json.loads(json.dumps(document))
        drifted["freetoken_checkouts"]["inferswarm03"]["observed_head"] = "0" * 40
        self.assertNotEqual(
            drifted["freetoken_checkouts"]["inferswarm03"]["observed_head"],
            applicability.FROZEN_INTEGRATION_PRODUCER)
        self.assertNotEqual(
            self_digest(drifted, identity_field="record_digest"),
            document["record_digest"],
            "a drifted record must not re-derive the retained digest")

    def test_frozen_record_embeds_the_01_mechanical_identity(self):
        frozen = json.loads((EVIDENCE / "physical-preflight.json").read_text())
        embedded = frozen["implementation"]["freetoken_identity"]
        self.assertEqual(embedded["head"],
                         applicability.FROZEN_INTEGRATION_PRODUCER)
        self.assertEqual(embedded["porcelain"], "")
        self.assertEqual(embedded["repo_root"], "/home/zutfen/FreeToken")
        identities = self.load()["freetoken_checkouts"]["inferswarm01"]
        self.assertEqual(identities["mechanical_digest"],
                         embedded["repository_identity_digest"])


class CoordinatorAccountingEvidenceTests(unittest.TestCase):
    def load(self):
        return json.loads(
            (EVIDENCE / "physical-preflight-coordinator-accounting.json").read_text())

    def test_record_is_digest_bound(self):
        document = self.load()
        self.assertEqual(
            document["record_digest"],
            self_digest(document, identity_field="record_digest"))

    def test_cuda_derivation_inputs_are_retained_and_derive_zero(self):
        document = self.load()
        cuda = document["cuda_initialization_evidence"]
        self.assertIn("dev_nvidia_nodes", cuda)
        self.assertIn("processes_with_cuda_device_fds", cuda)
        self.assertIn("coordinator_venv_torch_importable", cuda)
        derived = int(bool(cuda["dev_nvidia_nodes"])
                      or bool(cuda["processes_with_cuda_device_fds"])
                      or bool(cuda["coordinator_venv_torch_importable"]))
        self.assertEqual(derived, document["derived_coordinator_cuda_initialized"])
        self.assertEqual(document["derived_coordinator_cuda_initialized"], 0)

    def test_weight_byte_accounting_roots_and_zero_totals(self):
        document = self.load()
        accounting = document["weight_byte_accounting"]
        roots = accounting["roots_scanned"]
        self.assertEqual(roots, [
            "/srv/inferswarm/cache/issue117",
            "/srv/inferswarm/materialized/issue117"])
        received = sum(root["weight_object_bytes"]
                       for root in accounting["per_root"].values())
        self.assertEqual(received, accounting["total_received_bytes"])
        self.assertEqual(accounting["total_received_bytes"], 0)
        self.assertEqual(accounting["total_materialized_bytes"], 0)

    def test_nonzero_or_tampered_accounting_fails(self):
        document = self.load()
        tampered = json.loads(json.dumps(document))
        tampered["weight_byte_accounting"]["total_received_bytes"] = 1
        self.assertNotEqual(
            self_digest(tampered, identity_field="record_digest"),
            document["record_digest"])
        with self.assertRaises(AssertionError):
            bad = json.loads(json.dumps(document))
            bad["weight_byte_accounting"]["per_root"][
                "/srv/inferswarm/cache/issue117"]["weight_object_bytes"] = 1024
            received = sum(r["weight_object_bytes"] for r in
                           bad["weight_byte_accounting"]["per_root"].values())
            self.assertEqual(received,
                             bad["weight_byte_accounting"]["total_received_bytes"])


class CompactRecordBindingTests(unittest.TestCase):
    def test_compact_record_binds_recovered_evidence_digests(self):
        document = json.loads(
            (EVIDENCE / "physical-preflight-record.json").read_text())
        self.assertEqual(
            document["retention_record_digest"],
            self_digest(document, identity_field="retention_record_digest"))
        for key, name in (
                ("freetoken_identity_evidence",
                 "physical-preflight-freetoken-identities.json"),
                ("coordinator_accounting_evidence",
                 "physical-preflight-coordinator-accounting.json")):
            bound = document[key]["record_digest"]
            referenced = json.loads((EVIDENCE / name).read_text())["record_digest"]
            self.assertEqual(bound, referenced)
        self.assertTrue(document["physical_preflight_executed"])
        self.assertEqual(document["physical_preflight_result"],
                         "ISSUE117_PHYSICAL_PREFLIGHT_PASS")
        self.assertFalse(document["physical_arms_executed"])


if __name__ == "__main__":
    unittest.main()
