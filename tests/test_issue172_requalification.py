"""Issue #172 — Arm-C physical requalification retention tests.

Fail-closed retention checks over the frozen evidence bundle: authority
identities, corpus bindings, terminal derivation inputs, manifest
coverage, and the reduction chain consistency. No physical execution.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

REPO = Path(__file__).resolve().parents[1]
EVIDENCE = (
    REPO / "docs/implementation"
    / "r6-successor-arm-c-requalification-172" / "evidence")


def load(name: str) -> dict:
    return json.loads((EVIDENCE / name).read_text())


def test_pins_import_and_identity():
    import issue172_campaign_pins as pins  # noqa: F401
    assert pins.CAMPAIGN_ID == "issue172-arm-c-requalification-v1"
    assert pins.TOTAL_CASE_COUNT == 40
    assert pins.SENTINEL_REPEATS == 6
    assert len(pins.SENTINEL_HISTORICAL) == 3
    assert len(pins.SENTINEL_170) == 4
    assert pins.PASS_TERMINAL == "ISSUE117_ARM_C_ORDINARY_SERVING_PASS"
    assert pins.FREETOKEN_RESEARCH_172 == (
        "6202eeebcdf63e7bc8bb3498dd3c364ae42ee469")
    assert pins.INFERSWARM_MAIN_172 == (
        "bce7fb3d8e54429972472933be66433b81ebcf8f")


def test_authority_record_bindings():
    authority = load("authority.json")
    assert authority["starting_heads"]["verified"] is True
    assert authority["execution_delta_audit"][
        "stage_runtime_matches_166_remediation"] is True
    assert authority["subject"]["candidate"] == "dense.6171f32b4413"
    assert authority["corpus_bindings"]["combined_identity"][
        "case_count"] == 40
    assert authority["pre_observation_state"][
        "physical_execution_performed"] is False


def test_corpus_binding_and_digests():
    binding = load("corpus-binding.json")
    assert binding["case_count"] == 40
    assert binding["regression_count"] == 24
    assert binding["generalization_count"] == 16
    assert binding["corpus_170_canonical_digest"] == (
        "sha256:8a382df1ae5e7d7330966e65acba58bc02ff5af958f3ef63"
        "484cc52747a31c34")
    assert all(binding["checks"].values())
    corpus = load("campaign-corpus.json")
    cases = corpus["cases"]
    assert len(cases) == 40
    canonical = "sha256:" + hashlib.sha256(json.dumps(
        cases, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    assert canonical == corpus["combined_canonical_digest"]
    session_indexes = sorted(c["session_index"] for c in cases)
    assert session_indexes == list(range(1, 41))
    assert "h109-" not in json.dumps(cases)


def test_cpu_preflight_pass():
    preflight = load("cpu-transcript-preflight.json")
    assert preflight["terminal"] == "PREFLIGHT_PASS"
    assert preflight["per_case_equal_count"] == 40
    assert preflight["cpu_only"]["gpu_execution_occurred"] is False
    lengths = [preflight["g170_rendered_lengths"][f"g170-{i:02d}"]
               for i in range(1, 17)]
    assert lengths == [
        65, 67, 69, 72, 73, 78, 83, 88, 89, 96, 104, 112, 113, 118,
        123, 128]


def test_equality_reduction_pass():
    equality = load("equality-reduction.json")
    assert equality["equal_count"] == 40
    assert equality["terminal"] == "ISSUE117_ARM_C_ORDINARY_SERVING_PASS"
    assert not equality["global_problems"]


def test_sentinel_reduction_pass():
    sentinels = load("sentinel-reduction.json")
    assert len(sentinels["rows"]) == 7
    assert sentinels["within_direct_deterministic"] is True
    assert sentinels["within_ordinary_deterministic"] is True
    assert sentinels["cross_arm_exact"] is True
    assert sentinels["terminal"] == "ISSUE117_ARM_C_ORDINARY_SERVING_PASS"
    for row in sentinels["rows"]:
        assert len(row["direct_distribution"]) == 6
        assert len(row["ordinary_distribution"]) == 6
        assert not row["problems"]


def test_zero_invariants_pass():
    zeros = load("zero-invariants.json")
    assert zeros["passed"] is True
    assert not zeros["zero_failures"]
    for injection in zeros["fencing"]["injections"]:
        assert injection["accepted"] is False
    assert zeros["counters"]["fencing_injections_rejected"] == 2
    assert zeros["counters"]["fencing_ledger_unmutated"] is True
    for mandatory in zeros["mandatory_zeros"]:
        assert zeros["counters"].get(mandatory, 0) == 0


def test_swa_ownership_observation():
    swa = load("swa-ownership.json")
    assert swa["passed"] is True
    assert swa["producer"] == "6202eeebcdf63e7bc8bb3498dd3c364ae42ee469"
    assert all(swa["verdicts"].values())
    assert swa["seam"] == (
        "swa_session_ownership_report (accepted #166 pure-read)")


def test_terminal_reduction_chain():
    terminal = load("terminal-reduction.json")
    assert terminal["terminal"] == "ISSUE117_ARM_C_ORDINARY_SERVING_PASS"
    assert not terminal["failed_conditions"]
    assert all(terminal["conditions"].values())
    ledger = terminal["attempt_ledger"]
    assert any(entry.get("classification") ==
               "correctable-pre-observation-infrastructure"
               for entry in ledger)
    for entry in ledger:
        if entry.get("classification") != (
                "correctable-pre-observation-infrastructure"):
            assert entry["correctness_bearing_results"] > 0


def test_physical_execution_artifacts_retained():
    direct = json.loads(
        (EVIDENCE / "physical-execution/direct-run.json").read_text())
    assert direct["producer"] == "6202eeebcdf63e7bc8bb3498dd3c364ae42ee469"
    assert direct["case_count"] == 40
    assert direct["plan_digest"] == (
        "sha256:208be7956474a559756355c85142eb6716585f4c0320a27fe73d2f"
        "4196972c3e")
    report = json.loads(
        (EVIDENCE / "physical-execution/serving-report-canonical.json")
        .read_text())
    requests = [r for r in report["coordinator_scope"]["requests"]
                if not r.get("fencing_arm_injections")]
    assert len(requests) == 40
    ordinary = json.loads(
        (EVIDENCE / "physical-execution/ordinary-canonical/"
         "ordinary-campaign.json").read_text())
    assert ordinary["ok_count"] == 40
    direct_sentinels = json.loads(
        (EVIDENCE / "physical-execution/direct-sentinels/direct-run.json")
        .read_text())
    assert direct_sentinels["case_count"] == 42


def test_chain_plan_172_lineage():
    plan = json.loads((EVIDENCE / "chain-plan.json").read_text())
    assert plan["digest"] == (
        "sha256:b24c3ca06b3ea79b62fdea8058afe9f71e0c69187b5cd77740cc"
        "5855f9796529")
    assert plan["provenance"]["r6"]["producer_sha"] == (
        "6202eeebcdf63e7bc8bb3498dd3c364ae42ee469")
    assert plan["provenance"]["issue172_arm_c_requal"][
        "accepted_arm_c_chain_plan"] == (
        "sha256:a71a3129b8764d7108f51ed30fb230b42fcd69646a20bcd6806b6"
        "ee53b9bc51f")
    assert plan["provenance"]["issue172_arm_c_requal"][
        "accepted_plan_digest"] == (
        "sha256:ee845188d3328bdec29bf4b09d71f7ccda0701ff5758cb1d8a7046"
        "0a40fecfb1")


def test_manifest_covers_evidence_tree():
    manifest = (EVIDENCE / "MANIFEST.sha256").read_text().splitlines()
    listed = {line.split("  ", 1)[1] for line in manifest if "  " in line}
    actual = {
        str(p.relative_to(EVIDENCE)) for p in EVIDENCE.rglob("*")
        if p.is_file() and p.name != "MANIFEST.sha256"}
    assert listed == actual
    for line in manifest:
        digest, rel = line.split("  ", 1)
        assert hashlib.sha256(
            (EVIDENCE / rel).read_bytes()).hexdigest() == digest


def test_arm_d_and_e_not_started():
    readme = (EVIDENCE.parent / "README.md").read_text()
    assert "Arm D and Arm E were NOT started" in readme
    assert "Arm D and Arm E are not started" in readme
    assert "h109-" in readme  # explicit forbidden-material statement


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__]))
