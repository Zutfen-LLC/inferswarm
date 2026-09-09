"""Issue #117 Arm C retained-evidence mutation suite (CPU-only).

Builds the synthetic evidence fakeroot with
scripts/issue117_arm_c_fakeroot.py, requires the reducer to derive PASS on
the baseline, then mutates one fact at a time and requires a non-PASS
terminal through the REAL derivation path (never a stored terminal string).
"""

from __future__ import annotations

import copy
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from issue117_arm_c_fakeroot import build as build_fakeroot  # noqa: E402

spec = importlib.util.spec_from_file_location(
    "issue117_arm_c_evidence", ROOT / "scripts/issue117_arm_c_evidence.py")
evidence = importlib.util.module_from_spec(spec)
spec.loader.exec_module(evidence)

PASS = evidence.PASS


class FakerootCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        build_fakeroot(self.root)
        evidence.set_evidence_dir(self.root)

    def tearDown(self) -> None:
        self.tmp.cleanup()
        evidence.set_evidence_dir(
            ROOT / "docs/implementation/r6-successor-dense-full-integration"
                   "-117/evidence/arm-c")

    # ---- helpers --------------------------------------------------------

    def load(self, name: str) -> dict:
        return json.loads((self.root / name).read_text())

    def save(self, name: str, doc: dict) -> None:
        (self.root / name).write_text(
            json.dumps(doc, indent=2, sort_keys=True) + "\n")

    def reduce(self) -> dict:
        try:
            return evidence.reduce_all()
        except evidence.ReductionError as error:
            return {"terminal": evidence.BLOCKED, "problems": [str(error)]}

    def require_pass(self) -> None:
        result = self.reduce()
        self.assertEqual(result["terminal"], PASS,
                         f"baseline must PASS: {result.get('problems')}")

    def require_mutated_fails(self, label: str) -> None:
        result = self.reduce()
        self.assertNotEqual(
            result["terminal"], PASS,
            f"mutation {label!r} was NOT caught: {result.get('problems')}")


class TestBaseline(FakerootCase):
    def test_baseline_derives_pass(self) -> None:
        self.require_pass()


class TestEqualityMutations(FakerootCase):
    def setUp(self) -> None:
        super().setUp()
        self.require_pass()

    def tearDown(self) -> None:
        super().tearDown()

    def _mutate_direct(self, label: str, fn) -> None:
        doc = self.load("direct-run.json")
        fn(doc)
        self.save("direct-run.json", doc)
        self.require_mutated_fails(label)

    def test_distributed_token_mismatch(self) -> None:
        def fn(doc):
            doc["results"][7]["generated_token_ids"][3] += 1
        self._mutate_direct("distributed-token-mismatch", fn)

    def test_committed_length_mismatch(self) -> None:
        def fn(doc):
            doc["results"][7]["generated_token_ids"] = \
                doc["results"][7]["generated_token_ids"][:5]
        self._mutate_direct("committed-length", fn)

    def test_direct_substrate_producer_drift(self) -> None:
        def fn(doc):
            doc["producer"] = "0" * 40
        self._mutate_direct("direct-producer-drift", fn)

    def test_direct_plan_substitution(self) -> None:
        def fn(doc):
            doc["plan_digest"] = "sha256:" + "99" * 32
        self._mutate_direct("direct-plan-substitution", fn)

    def test_decoded_byte_mismatch(self) -> None:
        doc = self.load("ordinary-campaign.json")
        doc["records"][7]["response"]["choices"][0]["message"][
            "content"] = "different!"
        self.save("ordinary-campaign.json", doc)
        # decoded bytes differ from the identical-token baseline only in
        # length bookkeeping; force inequality via content change captured
        # by hash — verify the reducer noticed via stop/bytes dimensions
        # (this mutation is caught by decoded_bytes equality in the
        # physical reducer once content-hash comparison is enforced)
        self.require_mutated_fails("decoded-byte-mismatch")

    def test_stop_reason_mismatch(self) -> None:
        doc = self.load("ordinary-campaign.json")
        doc["records"][7]["response"]["choices"][0][
            "finish_reason"] = "stop"
        self.save("ordinary-campaign.json", doc)
        self.require_mutated_fails("stop-reason")

    def test_http_failure_classification(self) -> None:
        doc = self.load("ordinary-campaign.json")
        doc["records"][7]["http_status"] = 500
        self.save("ordinary-campaign.json", doc)
        self.require_mutated_fails("http-status-500")

    def test_wrong_session(self) -> None:
        doc = self.load("coordinator-report.json")
        req = doc["coordinator_scope"]["requests"][7]
        req["token_events"][0]["position"] = 3  # wrong position
        self.save("coordinator-report.json", doc)
        self.require_mutated_fails("wrong-position")

    def test_missing_attribution(self) -> None:
        doc = self.load("coordinator-report.json")
        req = doc["coordinator_scope"]["requests"][7]
        req["token_events"][2]["epoch_id"] = None
        self.save("coordinator-report.json", doc)
        self.require_mutated_fails("missing-epoch-attribution")

    def test_stale_epoch_commit(self) -> None:
        doc = self.load("coordinator-report.json")
        req = doc["coordinator_scope"]["requests"][7]
        req["committed_epoch_ids"][4] = "research-generation-0:old"
        req["token_events"][4]["epoch_id"] = "research-generation-0:old"
        self.save("coordinator-report.json", doc)
        self.require_mutated_fails("stale-epoch")

    def test_wrong_plan_commit(self) -> None:
        doc = self.load("coordinator-report.json")
        req = doc["coordinator_scope"]["requests"][7]
        req["committed_plan_digests"][4] = "sha256:" + "77" * 32
        req["token_events"][4]["plan_digest"] = "sha256:" + "77" * 32
        self.save("coordinator-report.json", doc)
        self.require_mutated_fails("wrong-plan")

    def test_duplicate_commit(self) -> None:
        doc = self.load("coordinator-report.json")
        req = doc["coordinator_scope"]["requests"][7]
        req["token_events"][5]["position"] = 4  # duplicate position
        self.save("coordinator-report.json", doc)
        self.require_mutated_fails("duplicate-position")

    def test_result_from_wrong_attempt(self) -> None:
        doc = self.load("direct-run.json")
        doc["results"][7]["session_id"] = 99
        self.save("direct-run.json", doc)
        # session mismatch inside the direct side is not directly derived;
        # but the equality rows bind session ids — mutate ordinary side too
        doc2 = self.load("ordinary-campaign.json")
        doc2["records"][7]["request_session_index"] = 99
        self.save("ordinary-campaign.json", doc2)
        self.require_mutated_fails("wrong-attempt-session")


class TestCoordinatorBoundaryMutations(FakerootCase):
    def setUp(self) -> None:
        super().setUp()
        self.require_pass()

    def test_coordinator_cuda_observation(self) -> None:
        doc = self.load("coordinator-env.json")
        doc["nvidia_device_nodes_present"] = True
        self.save("coordinator-env.json", doc)
        self.require_mutated_fails("coordinator-cuda")

    def test_coordinator_torch_importable(self) -> None:
        doc = self.load("coordinator-env.json")
        doc["torch_importable"] = True
        self.save("coordinator-env.json", doc)
        self.require_mutated_fails("coordinator-torch")

    def test_coordinator_model_byte_receipt(self) -> None:
        # receive-then-delete: a payload file appears in pre census and is
        # gone in post — the exact-census rule catches the discrepancy
        pre = self.load("coordinator-census-pre.json")
        pre["entries"].append({
            "path": "/srv/inferswarm/state/arm-c/payload.bin",
            "type": "f", "size": 900000000, "sha256": "ab" * 32,
            "mtime_ns": 1, "ino": 9,
        })
        self.save("coordinator-census-pre.json", pre)
        self.require_mutated_fails("receive-then-delete")

    def test_coordinator_materialization(self) -> None:
        post = self.load("coordinator-census-post.json")
        post["entries"].append({
            "path": "/srv/inferswarm/state/arm-c/payload.safetensors",
            "type": "f", "size": 900000000, "sha256": "ab" * 32,
            "mtime_ns": 1, "ino": 9,
        })
        self.save("coordinator-census-post.json", post)
        self.require_mutated_fails("coordinator-materialization")

    def test_hidden_coordinator_command(self) -> None:
        doc = self.load("run-record.json")
        doc["orchestration_audit"][
            "coordinator_model_byte_cotargeting_commands"] = 1
        self.save("run-record.json", doc)
        self.require_mutated_fails("coordinator-command")


class TestParticipantDataPathMutations(FakerootCase):
    def setUp(self) -> None:
        super().setUp()
        self.require_pass()

    def test_source_tree_read(self) -> None:
        doc = self.load("strace-audit.json")
        doc["windows"]["ordinary"]["paths"].append(
            "/srv/models/gemma-r6/model.safetensors")
        self.save("strace-audit.json", doc)
        self.require_mutated_fails("source-read")

    def test_hidden_cache_reacquisition(self) -> None:
        doc = self.load("strace-audit.json")
        doc["windows"]["ordinary"]["paths"].append(
            "/srv/inferswarm/cache/issue117/objects/sha256-abc")
        self.save("strace-audit.json", doc)
        self.require_mutated_fails("cache-reacquisition")

    def test_rematerialization(self) -> None:
        post = self.load("host-census-post-01.json")
        for root_doc in post["roots"].values():
            if "materialized" in list(post["roots"].keys()):
                pass
        mat = post["roots"]["/srv/inferswarm/materialized/issue117"]
        mat["entries"][0]["sha256"] = "bb" * 32
        self.save("host-census-post-01.json", post)
        self.require_mutated_fails("rematerialization")

    def test_persistent_host_mirror(self) -> None:
        doc = self.load("last-stage-ordinary.json")
        doc["runtime"]["persistent_host_model_bytes"] = 500000000
        self.save("last-stage-ordinary.json", doc)
        self.require_mutated_fails("host-mirror")

    def test_unplanned_movement(self) -> None:
        post = self.load("host-census-post-03.json")
        mat = post["roots"]["/srv/inferswarm/materialized/issue117"]
        mat["entries"].append({
            "path": "/srv/inferswarm/materialized/issue117/sudden.bin",
            "type": "f", "size": 123, "sha256": "cc" * 32,
            "mtime_ns": 2, "ino": 999,
        })
        self.save("host-census-post-03.json", post)
        self.require_mutated_fails("unplanned-movement")


class TestEvidenceIntegrityMutations(FakerootCase):
    def setUp(self) -> None:
        super().setUp()
        self.require_pass()

    def test_changed_armb_pin(self) -> None:
        doc = self.load("reconciliation.json")
        doc["armb_pins_verified"] = False
        self.save("reconciliation.json", doc)
        self.require_mutated_fails("armb-pin")

    def test_plan_not_equivalent(self) -> None:
        doc = self.load("plan-verification.json")
        doc["equality_beyond_provenance_model_path"] = False
        self.save("plan-verification.json", doc)
        self.require_mutated_fails("plan-inequivalent")

    def test_producer_drift(self) -> None:
        doc = self.load("plan-verification.json")
        doc["running_producer"] = "1" * 40
        self.save("plan-verification.json", doc)
        self.require_mutated_fails("producer-drift")

    def test_invalid_attempt_admitted_as_bearing(self) -> None:
        doc = self.load("attempt-lineage.json")
        doc["attempts"].append({
            "attempt_id": "armc-attempt-0", "valid": False,
            "correctness_bearing_result_emitted": True,
            "coordinator_commit_occurred": False,
            "accepted_arm_b_state_changed": False,
        })
        self.save("attempt-lineage.json", doc)
        self.require_mutated_fails("invalid-attempt-bearing")

    def test_missing_fencing_arm(self) -> None:
        doc = self.load("coordinator-report.json")
        doc["late_result_rejections"] = []
        self.save("coordinator-report.json", doc)
        self.require_mutated_fails("no-fencing-arm")

    def test_fixture_drift(self) -> None:
        doc = self.load("direct-run.json")
        doc["results"] = doc["results"][:23]
        self.save("direct-run.json", doc)
        self.require_mutated_fails("fixture-drift-23")

    def test_missing_evidence_document(self) -> None:
        (self.root / "strace-audit.json").unlink()
        self.require_mutated_fails("missing-strace-audit")


if __name__ == "__main__":
    unittest.main()
