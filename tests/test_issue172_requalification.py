"""Issue #172 — Arm-C physical requalification retention tests.

Fail-closed retention checks over the frozen evidence bundle: authority
identities, corpus bindings, terminal derivation inputs, manifest
coverage, and the reduction chain consistency. No physical execution.
"""
from __future__ import annotations

import hashlib
import json
import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

REPO = Path(__file__).resolve().parents[1]
EVIDENCE = (
    REPO / "docs/implementation"
    / "r6-successor-arm-c-requalification-172" / "evidence")


def load(name):
    return json.loads((EVIDENCE / name).read_text())


class Issue172RequalTests(unittest.TestCase):

    def test_pins_import_and_identity(self):
        import issue172_campaign_pins as pins  # noqa: F401
        self.assertEqual(pins.CAMPAIGN_ID, "issue172-arm-c-requalification-v1")
        self.assertEqual(pins.TOTAL_CASE_COUNT, 40)
        self.assertEqual(pins.SENTINEL_REPEATS, 6)
        self.assertEqual(len(pins.SENTINEL_HISTORICAL), 3)
        self.assertEqual(len(pins.SENTINEL_170), 4)
        self.assertEqual(
            pins.PASS_TERMINAL, "ISSUE117_ARM_C_ORDINARY_SERVING_PASS")
        self.assertEqual(pins.FREETOKEN_RESEARCH_172,
                         "6202eeebcdf63e7bc8bb3498dd3c364ae42ee469")
        self.assertEqual(pins.INFERSWARM_MAIN_172,
                         "bce7fb3d8e54429972472933be66433b81ebcf8f")

    def test_authority_record_bindings(self):
        authority = load("authority.json")
        self.assertTrue(authority["starting_heads"]["verified"])
        self.assertTrue(authority["execution_delta_audit"][
            "stage_runtime_matches_166_remediation"])
        self.assertEqual(authority["subject"]["candidate"],
                         "dense.6171f32b4413")
        self.assertEqual(authority["corpus_bindings"][
            "combined_identity"]["case_count"], 40)
        self.assertFalse(authority["pre_observation_state"][
            "physical_execution_performed"])

    def test_corpus_binding_and_digests(self):
        binding = load("corpus-binding.json")
        self.assertEqual(binding["case_count"], 40)
        self.assertEqual(binding["regression_count"], 24)
        self.assertEqual(binding["generalization_count"], 16)
        self.assertEqual(binding["corpus_170_canonical_digest"],
                         "sha256:8a382df1ae5e7d7330966e65acba58bc02ff"
                         "5af958f3ef63484cc52747a31c34")
        self.assertTrue(all(binding["checks"].values()))
        corpus = load("campaign-corpus.json")
        cases = corpus["cases"]
        self.assertEqual(len(cases), 40)
        canonical = "sha256:" + hashlib.sha256(json.dumps(
            cases, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        self.assertEqual(canonical, corpus["combined_canonical_digest"])
        indexes = sorted(c["session_index"] for c in cases)
        self.assertEqual(indexes, list(range(1, 41)))
        self.assertNotIn("h109-", json.dumps(cases))

    def test_cpu_preflight_pass(self):
        preflight = load("cpu-transcript-preflight.json")
        self.assertEqual(preflight["terminal"], "PREFLIGHT_PASS")
        self.assertEqual(preflight["per_case_equal_count"], 40)
        self.assertFalse(preflight["cpu_only"]["gpu_execution_occurred"])
        lengths = [preflight["g170_rendered_lengths"][f"g170-{i:02d}"]
                   for i in range(1, 17)]
        self.assertEqual(lengths, [
            65, 67, 69, 72, 73, 78, 83, 88, 89, 96, 104, 112, 113, 118,
            123, 128])

    def test_equality_reduction_pass(self):
        equality = load("equality-reduction.json")
        self.assertEqual(equality["equal_count"], 40)
        self.assertEqual(equality["terminal"],
                         "ISSUE117_ARM_C_ORDINARY_SERVING_PASS")
        self.assertEqual(equality["global_problems"], [])

    def test_sentinel_reduction_pass(self):
        sentinels = load("sentinel-reduction.json")
        self.assertEqual(len(sentinels["rows"]), 7)
        self.assertTrue(sentinels["within_direct_deterministic"])
        self.assertTrue(sentinels["within_ordinary_deterministic"])
        self.assertTrue(sentinels["cross_arm_exact"])
        self.assertEqual(sentinels["terminal"],
                         "ISSUE117_ARM_C_ORDINARY_SERVING_PASS")
        for row in sentinels["rows"]:
            self.assertEqual(len(row["direct_distribution"]), 6)
            self.assertEqual(len(row["ordinary_distribution"]), 6)
            self.assertEqual(row["problems"], [])

    def test_zero_invariants_pass(self):
        zeros = load("zero-invariants.json")
        self.assertTrue(zeros["passed"])
        self.assertEqual(zeros["zero_failures"], [])
        for injection in zeros["fencing"]["injections"]:
            self.assertFalse(injection["accepted"])
        self.assertEqual(zeros["counters"]["fencing_injections_rejected"], 2)
        self.assertTrue(zeros["counters"]["fencing_ledger_unmutated"])
        for mandatory in zeros["mandatory_zeros"]:
            self.assertEqual(zeros["counters"].get(mandatory, 0), 0)

    def test_swa_ownership_observation(self):
        swa = load("swa-ownership.json")
        self.assertTrue(swa["passed"])
        self.assertEqual(swa["producer"],
                         "6202eeebcdf63e7bc8bb3498dd3c364ae42ee469")
        self.assertTrue(all(swa["verdicts"].values()))
        self.assertEqual(
            swa["seam"],
            "swa_session_ownership_report (accepted #166 pure-read)")

    def test_terminal_reduction_chain(self):
        terminal = load("terminal-reduction.json")
        self.assertEqual(terminal["terminal"],
                         "ISSUE117_ARM_C_ORDINARY_SERVING_PASS")
        self.assertEqual(terminal["failed_conditions"], [])
        self.assertTrue(all(terminal["conditions"].values()))
        ledger = terminal["attempt_ledger"]
        self.assertTrue(any(
            entry.get("classification") ==
            "correctable-pre-observation-infrastructure"
            for entry in ledger))
        for entry in ledger:
            if entry.get("classification") != (
                    "correctable-pre-observation-infrastructure"):
                self.assertGreater(entry["correctness_bearing_results"], 0)

    def test_physical_execution_artifacts_retained(self):
        direct = json.loads((EVIDENCE / "physical-execution" /
                             "direct-run.json").read_text())
        self.assertEqual(direct["producer"],
                         "6202eeebcdf63e7bc8bb3498dd3c364ae42ee469")
        self.assertEqual(direct["case_count"], 40)
        self.assertEqual(direct["plan_digest"],
                         "sha256:208be7956474a559756355c85142eb6716"
                         "585f4c0320a27fe73d2f4196972c3e")
        report = json.loads(
            (EVIDENCE / "physical-execution" /
             "serving-report-canonical.json").read_text())
        requests = [r for r in report["coordinator_scope"]["requests"]
                    if not r.get("fencing_arm_injections")]
        self.assertEqual(len(requests), 40)
        ordinary = json.loads(
            (EVIDENCE / "physical-execution/ordinary-canonical" /
             "ordinary-campaign.json").read_text())
        self.assertEqual(ordinary["ok_count"], 40)
        direct_sentinels = json.loads(
            (EVIDENCE / "physical-execution/direct-sentinels" /
             "direct-run.json").read_text())
        self.assertEqual(direct_sentinels["case_count"], 42)

    def test_chain_plan_172_lineage(self):
        plan = json.loads((EVIDENCE / "chain-plan.json").read_text())
        self.assertEqual(plan["digest"],
                         "sha256:b24c3ca06b3ea79b62fdea8058afe9f71e0c6"
                         "9187b5cd77740cc5855f9796529")
        self.assertEqual(plan["provenance"]["r6"]["producer_sha"],
                         "6202eeebcdf63e7bc8bb3498dd3c364ae42ee469")
        self.assertEqual(
            plan["provenance"]["issue172_arm_c_requal"][
                "accepted_arm_c_chain_plan"],
            "sha256:a71a3129b8764d7108f51ed30fb230b42fcd69646a20bcd"
            "6806b6ee53b9bc51f")
        self.assertEqual(
            plan["provenance"]["issue172_arm_c_requal"][
                "accepted_plan_digest"],
            "sha256:ee845188d3328bdec29bf4b09d71f7ccda0701ff5758cb1d"
            "8a70460a40fecfb1")

    def test_manifest_covers_evidence_tree(self):
        manifest = (EVIDENCE / "MANIFEST.sha256").read_text().splitlines()
        listed = {line.split("  ", 1)[1]
                  for line in manifest if "  " in line}
        actual = {
            p.relative_to(REPO).as_posix() for p in EVIDENCE.rglob("*")
            if p.is_file() and p.name != "MANIFEST.sha256"}
        self.assertEqual(listed, actual)
        for line in manifest:
            digest, rel = line.split("  ", 1)
            self.assertEqual(
                hashlib.sha256((REPO / rel).read_bytes()).hexdigest(),
                digest)

    def test_arm_d_and_e_not_started(self):
        readme = (EVIDENCE.parent / "README.md").read_text()
        self.assertIn("Arm D and Arm E were NOT started", readme)
        self.assertIn("Arm D and Arm E are not started", readme)
        self.assertIn("h109-", readme)


if __name__ == "__main__":
    unittest.main()
