#!/usr/bin/env python3
"""Issue #228 assembler state-machine tests — corrected round.

Each test builds a COMPLETE synthetic evidence tree (pf2 preflight
with validated census verdict + fresh mapping + refusals) bound to a
mini producer repo (closure), reduces it through the REAL assembler,
then mutates exactly one fact and asserts the terminal flips or the
assembly fails closed.

Correction-round regressions (each names its blocker):

* attempt-1 (superseded) evidence can never be reduced — the corrected
  assembler rejects it as BLOCKED/raise, never as capability absence;
* missing/empty/failed census => EVIDENCE_BLOCKED, never
  API_PREREQUISITE;
* api-1.0 census => BLOCKED;
* swapped/stale mapping join => BLOCKED;
* no transfer evidence can produce a functional terminal: advertised
  capability + disabled execution => EVIDENCE_BLOCKED;
* a transfer ladder artifact under the disabled campaign => raise;
* capability absence with a complete valid census => API_PREREQUISITE
  (the only path to that terminal);
* fault lines outside the window/authority cannot be silently dropped;
* reduction errors never become functional terminals.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "tests"))

import issue228_receipt as rc
import issue228_freeze as fz
import issue228_assemble as asm
import issue228_probe as probe
from test_issue228_v2e_peer_link import (synth_capability_v2,
                                         synth_ext_matrix_v2,
                                         synth_probe_stream)


def build_mini_repo(tmp: Path) -> Path:
    """A git repo containing exactly the closure sources plus the
    committed physical authority and closure record (two-commit freeze
    shape)."""
    repo = tmp / "repo"
    repo.mkdir()
    for rel in rc.CLOSURE_SOURCES:
        dst = repo / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO / rel, dst)
    authority_dst = repo / rc.AREA_REL / "PHYSICAL-AUTHORITY.json"
    authority_dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(REPO / rc.AREA_REL / "PHYSICAL-AUTHORITY.json",
                 authority_dst)
    subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email",
                    "t@t"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name",
                    "t"], check=True)
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "freeze"],
                   check=True)
    record = fz.write_closure(repo)
    subprocess.run(["git", "-C", str(repo), "add",
                    record.relative_to(repo).as_posix()], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "closure"],
                   check=True)
    return repo


def _mapping_doc(closure: dict, attempt: str = "pf2-map",
                 swap: bool = False) -> tuple[dict, dict]:
    participants = {
        "a": {"fresh_selector": "Vulkan1",
              "fresh_pci_bdf": "09:00.0" if swap else "06:00.0"},
        "b": {"fresh_selector": "Vulkan2",
              "fresh_pci_bdf": "06:00.0" if swap else "09:00.0"},
    }
    import hashlib
    doc = {
        "schema": "inferswarm.v2e.fresh-mapping/1",
        "campaign_id": rc.CAMPAIGN_ID,
        "attempt_id": attempt,
        "authority_digest": "0" * 64,
        "participants": participants,
    }
    doc["mapping_digest"] = hashlib.sha256(
        rc.canonical({k: v for k, v in doc.items()
                      if k != "mapping_digest"})).hexdigest()
    return doc, participants


def build_evidence_tree(repo: Path, tmp: Path, *,
                        capability: dict | None = None,
                        ext_matrix: dict | None = None,
                        mapping_swap: bool = False,
                        census_stdout: str | None = None,
                        census_exit: int | None = 0,
                        drop_census: bool = False,
                        empty_census: bool = False,
                        drop_exit_code: bool = False,
                        preflight_attempt: str = "pf2",
                        refusal_attempt: str = "lad2",
                        with_ladder: str | None = None,
                        with_refusal: bool = True) -> Path:
    """A complete synthetic V2-E pf2 evidence tree bound to the mini
    repo's closure. Default shape: valid single-group census, no
    capable mechanism, refusals present."""
    cap = capability if capability is not None else synth_capability_v2()
    ext = ext_matrix if ext_matrix is not None else synth_ext_matrix_v2()
    ev = tmp / "evidence"
    (ev / "preflight" / "raw").mkdir(parents=True)
    (ev / "preflight" / "mapping").mkdir(parents=True)

    if census_stdout is not None:
        cap_text = census_stdout
    else:
        cap_text = json.dumps(cap, indent=1)
    if empty_census:
        cap_text = ""
    if not drop_census:
        (ev / "preflight" / "raw" / "capability-probe.stdout").write_text(
            cap_text)
        (ev / "preflight" / "raw" / "ext-matrix.stdout").write_text(
            json.dumps(ext, indent=1))
        if not drop_exit_code:
            (ev / "preflight" / "raw" /
             "capability-probe.exit-code").write_text(
                f"{census_exit if census_exit is not None else 0}\n")
            (ev / "preflight" / "raw" /
             "ext-matrix.exit-code").write_text("0\n")

    closure = fz.verify_closure(repo, sources=rc.CLOSURE_SOURCES)
    authority = json.loads(
        (repo / rc.AREA_REL / "PHYSICAL-AUTHORITY.json").read_text())
    mapping, participants = _mapping_doc(closure,
                                         swap=mapping_swap)
    (ev / "preflight" / "mapping" / "fresh-mapping.json").write_text(
        json.dumps(mapping, indent=1))

    verdict = None
    if not drop_census and not empty_census and census_exit == 0:
        try:
            expected = {d: ("0000:" + p["fresh_pci_bdf"])
                        for d, p in participants.items()}
            verdict = probe.validate_capability_census(
                json.loads(cap_text), ext, expected)
        except (json.JSONDecodeError, probe.CensusInvalid):
            verdict = None

    preflight = {
        "schema": "inferswarm.v2e.preflight/2",
        "campaign_id": rc.CAMPAIGN_ID,
        "attempt_id": preflight_attempt,
        "captured_utc": "2026-09-19T12:00:00+00:00",
        "boot_id": "synthetic-boot",
        "authority_digest": authority["authority_digest"],
        "mapping_digest": mapping["mapping_digest"],
        "closure_digest": closure["closure_digest"],
        "producer_head": closure["producer_head"],
        "probes": [],
        "capability": "REMOVED-BY-CORRECTION",
        "nonclaims": ["read-only census"],
    }
    if verdict is not None:
        preflight["capability_verdict"] = verdict
    (ev / "preflight" / "preflight.json").write_text(
        json.dumps(preflight, indent=1))

    import issue228_ladder as ladder
    (ev / "ladder").mkdir(parents=True, exist_ok=True)
    if with_ladder is not None:
        # a transfer ladder artifact under the disabled campaign
        (ev / "ladder" / "raw").mkdir(parents=True, exist_ok=True)
        (ev / "ladder" / "raw" / "ladder-4096.stdout").write_text(
            with_ladder)
        (ev / "ladder" / "raw" / "ladder-4096.exit-code").write_text("0\n")
        ladder_doc = {
            "schema": "inferswarm.v2e.ladder/1",
            "campaign_id": rc.CAMPAIGN_ID,
            "attempt_id": refusal_attempt,
            "captured_utc": "2026-09-19T12:30:00+00:00",
            "closure_digest": closure["closure_digest"],
            "producer_head": closure["producer_head"],
            "executed_transfers": 3,
        }
        (ev / "ladder" / "ladder.json").write_text(
            json.dumps(ladder_doc, indent=1))
    elif with_refusal:
        refusal = {
            "schema": "inferswarm.v2e.ladder-refusal/2",
            "campaign_id": rc.CAMPAIGN_ID,
            "attempt_id": refusal_attempt,
            "captured_utc": "2026-09-19T12:30:00+00:00",
            "closure_digest": closure["closure_digest"],
            "producer_head": closure["producer_head"],
            "mechanism": (ladder.classify_mechanism(verdict)
                          if verdict is not None
                          else ladder.classify_mechanism(
                              {"census_valid": False,
                               "failure_reasons": ["x"]})),
            "executed_transfers": 0,
        }
        (ev / "ladder" / "refusal.json").write_text(
            json.dumps(refusal, indent=1))
    baselines = {
        "schema": "inferswarm.v2e.baselines-refusal/2",
        "campaign_id": rc.CAMPAIGN_ID,
        "attempt_id": "base2",
        "captured_utc": "2026-09-19T12:40:00+00:00",
        "closure_digest": closure["closure_digest"],
        "producer_head": closure["producer_head"],
        "executed": False,
        "executed_transfers": 0,
    }
    (ev / "baselines").mkdir(parents=True, exist_ok=True)
    (ev / "baselines" / "refusal.json").write_text(
        json.dumps(baselines, indent=1))
    return ev


class AssemblerTerminalTests(unittest.TestCase):

    def _assemble(self, repo: Path, ev: Path) -> dict:
        import issue228_assemble as asm_mod
        old = asm_mod.REPO
        asm_mod.REPO = repo
        try:
            old_root = rc.ROOT
            rc.ROOT = repo
            try:
                return asm_mod.assemble(ev)
            finally:
                rc.ROOT = old_root
        finally:
            asm_mod.REPO = old

    def test_valid_census_capability_absence_is_api_prerequisite(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            repo = build_mini_repo(tmp)
            ev = build_evidence_tree(repo, tmp)
            out = self._assemble(repo, ev)
            self.assertEqual(out["terminal"],
                             "V2E_V340L_P2P_API_PREREQUISITE")
            self.assertEqual(
                len(out["capability_absence_reasons"]), 2)

    def test_advertised_capability_without_transfers_is_blocked(self):
        cap = synth_capability_v2(multi_group=True, peer_copy=True)
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            repo = build_mini_repo(tmp)
            ev = build_evidence_tree(repo, tmp, capability=cap)
            out = self._assemble(repo, ev)
            self.assertEqual(out["terminal"], "V2E_EVIDENCE_BLOCKED")
            self.assertIn("no measured transfers",
                          out["blocked_reason"])

    def test_superseded_attempt1_tree_not_reduced(self):
        # attempt-1 evidence (pf1) must never reduce to a terminal
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            repo = build_mini_repo(tmp)
            ev = build_evidence_tree(repo, tmp, preflight_attempt="pf1")
            out = self._assemble(repo, ev)
            self.assertEqual(out["terminal"], "V2E_EVIDENCE_BLOCKED")
            self.assertIn("superseded", out["blocked_reason"])

    def test_missing_census_blocked_not_prerequisite(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            repo = build_mini_repo(tmp)
            ev = build_evidence_tree(repo, tmp, drop_census=True)
            out = self._assemble(repo, ev)
            self.assertEqual(out["terminal"], "V2E_EVIDENCE_BLOCKED")
            self.assertIn("capability-probe.stdout",
                          out["blocked_reason"])

    def test_empty_census_blocked_not_prerequisite(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            repo = build_mini_repo(tmp)
            ev = build_evidence_tree(repo, tmp, empty_census=True)
            out = self._assemble(repo, ev)
            self.assertEqual(out["terminal"], "V2E_EVIDENCE_BLOCKED")

    def test_nonzero_census_exit_is_evidence_failure(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            repo = build_mini_repo(tmp)
            ev = build_evidence_tree(repo, tmp, census_exit=2)
            out = self._assemble(repo, ev)
            self.assertEqual(out["terminal"], "V2E_EVIDENCE_BLOCKED")
            self.assertIn("evidence failure", out["blocked_reason"])

    def test_missing_exit_code_retention_blocked(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            repo = build_mini_repo(tmp)
            ev = build_evidence_tree(repo, tmp, drop_exit_code=True)
            out = self._assemble(repo, ev)
            self.assertEqual(out["terminal"], "V2E_EVIDENCE_BLOCKED")
            self.assertIn("exit-code", out["blocked_reason"])

    def test_api10_census_blocked_not_prerequisite(self):
        cap = synth_capability_v2(requested_api="0.0.0",
                                  effective_api="1.0.0")
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            repo = build_mini_repo(tmp)
            ev = build_evidence_tree(repo, tmp, capability=cap)
            out = self._assemble(repo, ev)
            self.assertEqual(out["terminal"], "V2E_EVIDENCE_BLOCKED")
            self.assertIn("1.1", out["blocked_reason"])

    def test_swapped_mapping_join_blocked(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            repo = build_mini_repo(tmp)
            # census says a=06:00.0; swapped mapping says a=09:00.0 —
            # the UUID join must fail closed
            ev = build_evidence_tree(repo, tmp, mapping_swap=True)
            out = self._assemble(repo, ev)
            self.assertEqual(out["terminal"], "V2E_EVIDENCE_BLOCKED")

    def test_ladder_artifact_under_disabled_campaign_rejected(self):
        stream = synth_probe_stream(reps=5) + synth_probe_stream(
            reps=5, direction="b_to_a", ms=0.06)
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            repo = build_mini_repo(tmp)
            ev = build_evidence_tree(repo, tmp, with_ladder=stream)
            out = self._assemble(repo, ev)
            self.assertEqual(out["terminal"], "V2E_EVIDENCE_BLOCKED")
            self.assertIn("disabled", out["blocked_reason"])
            self.assertIn("transfer evidence cannot be reduced",
                          out["blocked_reason"])

    def test_refusal_claiming_executed_transfers_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            repo = build_mini_repo(tmp)
            ev = build_evidence_tree(repo, tmp)
            rf = json.loads(
                (ev / "ladder" / "refusal.json").read_text())
            rf["executed_transfers"] = 1
            (ev / "ladder" / "refusal.json").write_text(
                json.dumps(rf, indent=1))
            out = self._assemble(repo, ev)
            self.assertEqual(out["terminal"], "V2E_EVIDENCE_BLOCKED")
            self.assertIn("executed transfers", out["blocked_reason"])

    def test_attempt1_refusal_not_reduced(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            repo = build_mini_repo(tmp)
            ev = build_evidence_tree(repo, tmp, refusal_attempt="lad1")
            out = self._assemble(repo, ev)
            self.assertEqual(out["terminal"], "V2E_EVIDENCE_BLOCKED")

    def test_no_refusal_blocked(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            repo = build_mini_repo(tmp)
            ev = build_evidence_tree(repo, tmp, with_refusal=False)
            out = self._assemble(repo, ev)
            self.assertEqual(out["terminal"], "V2E_EVIDENCE_BLOCKED")

    def test_capability_tamper_flips_to_blocked(self):
        # preflight's authored verdict diverging from raw census bytes
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            repo = build_mini_repo(tmp)
            ev = build_evidence_tree(repo, tmp)
            pf = json.loads(
                (ev / "preflight" / "preflight.json").read_text())
            pf["capability_verdict"] = synth_verdict_tampered()
            (ev / "preflight" / "preflight.json").write_text(
                json.dumps(pf, indent=1))
            out = self._assemble(repo, ev)
            self.assertEqual(out["terminal"], "V2E_EVIDENCE_BLOCKED")

    def test_missing_preflight_blocked(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            repo = build_mini_repo(tmp)
            ev = build_evidence_tree(repo, tmp)
            (ev / "preflight" / "preflight.json").unlink()
            out = self._assemble(repo, ev)
            self.assertEqual(out["terminal"], "V2E_EVIDENCE_BLOCKED")

    def test_inherited_v2d_fault_recorded_not_recounted(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            repo = build_mini_repo(tmp)
            ev = build_evidence_tree(repo, tmp)
            out = self._assemble(repo, ev)
            self.assertEqual(
                out["v2d_inherited_fault"]["terminal"],
                "V2D_V340L_PLATFORM_STRESS_FAIL")

    def test_refusal_mechanism_divergence_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            repo = build_mini_repo(tmp)
            ev = build_evidence_tree(repo, tmp)
            rf = json.loads(
                (ev / "ladder" / "refusal.json").read_text())
            rf["mechanism"]["available"] = True
            (ev / "ladder" / "refusal.json").write_text(
                json.dumps(rf, indent=1))
            out = self._assemble(repo, ev)
            self.assertEqual(out["terminal"], "V2E_EVIDENCE_BLOCKED")
            self.assertIn("diverges", out["blocked_reason"])


def synth_verdict_tampered() -> dict:
    """A verdict that LOOKS valid but disagrees with retained raw
    census bytes (claims a capable device-group mechanism)."""
    return {
        "census_valid": True, "failure_reasons": [],
        "api": {"requested": "1.1.0", "effective": "1.4.309",
                "ext_matrix_effective": "1.4.309"},
        "identity": {"join_ok": True, "participants": {}},
        "group": {"both_dies_in_one_group": True, "note": "forged"},
        "peer_features": {
            "directions": {"a_to_b": {"present": True},
                           "b_to_a": {"present": True}},
            "both_directions_device_local_copy": True},
        "external_memory": {"usable_handle_types": [],
                            "directions": {}},
        "scoped_observations": {},
        "capable_mechanisms": ["vulkan-device-group-peer-copy"],
    }


if __name__ == "__main__":
    unittest.main()
