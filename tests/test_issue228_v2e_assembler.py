#!/usr/bin/env python3
"""Issue #228 assembler state-machine tests — synthetic evidence trees.

Each test builds a COMPLETE synthetic evidence tree (preflight with
fresh mapping + capability census, ladder or refusal, baselines
refusal) exercising the REAL assembler through a sandboxed repo copy
(the closure binds a mini producer repo), then mutates one fact and
asserts the exact terminal flips.
"""
from __future__ import annotations

import json
import os
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
from test_issue228_v2e_peer_link import (synth_capability,
                                         synth_probe_stream)


def build_mini_repo(tmp: Path) -> Path:
    """A git repo containing exactly the closure sources plus a
    committed closure record, one producer commit + one record commit
    (mirrors the real two-commit freeze shape)."""
    repo = tmp / "repo"
    repo.mkdir()
    for rel in rc.CLOSURE_SOURCES:
        dst = repo / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO / rel, dst)
    subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email",
                    "t@t"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name",
                    "t"], check=True)
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "freeze"],
                   check=True)
    # write the closure record (pins the producer head) and commit it
    # without touching any closure source
    record = fz.write_closure(repo)
    subprocess.run(["git", "-C", str(repo), "add",
                    record.relative_to(repo).as_posix()], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "closure"],
                   check=True)
    return repo


def real_mechanism_for(cap: dict) -> dict:
    import issue228_ladder as ladder
    return ladder.classify_mechanism(cap)


def build_evidence_tree(repo: Path, tmp: Path, *,
                        capability: dict | None = None,
                        ladder_stream: str | None = None,
                        ladder_exit: int = 0,
                        with_refusal: bool = True) -> Path:
    """A complete synthetic V2-E evidence tree bound to the mini repo's
    closure. Default shape: unavailable mechanism -> refusal."""
    cap = capability if capability is not None else synth_capability()
    ev = tmp / "evidence"
    (ev / "preflight" / "raw").mkdir(parents=True)
    (ev / "preflight" / "mapping").mkdir(parents=True)

    cap_text = json.dumps({k: v for k, v in cap.items()
                           if k != "external_memory_matrix"},
                          indent=1)
    ext_text = json.dumps(cap.get("external_memory_matrix")
                          or {"schema": "x", "vega_count": 0, "dies": []},
                          indent=1)
    (ev / "preflight" / "raw" / "capability-probe.stdout").write_text(
        cap_text)
    (ev / "preflight" / "raw" / "ext-matrix.stdout").write_text(ext_text)
    (ev / "preflight" / "raw" / "capability-probe.exit-code").write_text("0\n")
    (ev / "preflight" / "raw" / "ext-matrix.exit-code").write_text("0\n")

    closure = fz.verify_closure(repo, sources=rc.CLOSURE_SOURCES)
    mapping = {
        "schema": "inferswarm.v2e.fresh-mapping/1",
        "campaign_id": rc.CAMPAIGN_ID,
        "attempt_id": "pf1-map",
        "authority_digest": "0" * 64,
        "participants": {
            "a": {"fresh_selector": "Vulkan1",
                  "fresh_pci_bdf": "06:00.0"},
            "b": {"fresh_selector": "Vulkan2",
                  "fresh_pci_bdf": "09:00.0"},
        },
    }
    import hashlib
    mapping["mapping_digest"] = hashlib.sha256(
        rc.canonical({k: v for k, v in mapping.items()
                      if k != "mapping_digest"})).hexdigest()
    (ev / "preflight" / "mapping" / "fresh-mapping.json").write_text(
        json.dumps(mapping, indent=1))

    preflight = {
        "schema": "inferswarm.v2e.preflight/1",
        "campaign_id": rc.CAMPAIGN_ID,
        "attempt_id": "pf1",
        "captured_utc": "2026-09-19T12:00:00+00:00",
        "boot_id": "synthetic",
        "authority_digest": "0" * 64,
        "mapping_digest": mapping["mapping_digest"],
        "closure_digest": closure["closure_digest"],
        "producer_head": closure["producer_head"],
        "probes": [],
        "capability": cap,
        "nonclaims": ["read-only census"],
    }
    (ev / "preflight" / "preflight.json").write_text(
        json.dumps(preflight, indent=1))

    if ladder_stream is not None:
        (ev / "ladder" / "raw").mkdir(parents=True)
        (ev / "ladder" / "raw" / "ladder-4096.stdout").write_text(
            ladder_stream)
        (ev / "ladder" / "raw" / "ladder-4096.exit-code").write_text(
            f"{ladder_exit}\n")
        ladder_doc = {
            "schema": "inferswarm.v2e.ladder/1",
            "campaign_id": rc.CAMPAIGN_ID,
            "attempt_id": "lad1",
            "captured_utc": "2026-09-19T12:30:00+00:00",
            "closure_digest": closure["closure_digest"],
            "producer_head": closure["producer_head"],
            "mechanism": real_mechanism_for(cap),
            "frozen_sizes": [4096],
            "rows": [{
                "size": 4096,
                "stdout_rel": "raw/ladder-4096.stdout",
                "stdout_sha256": hashlib.sha256(
                    ladder_stream.encode()).hexdigest(),
                "exit_code": ladder_exit,
            }],
            "stop_condition": None,
        }
        (ev / "ladder" / "ladder.json").write_text(
            json.dumps(ladder_doc, indent=1))
    elif with_refusal:
        refusal = {
            "schema": "inferswarm.v2e.ladder-refusal/1",
            "campaign_id": rc.CAMPAIGN_ID,
            "attempt_id": "lad1",
            "captured_utc": "2026-09-19T12:30:00+00:00",
            "closure_digest": closure["closure_digest"],
            "producer_head": closure["producer_head"],
            "mechanism": real_mechanism_for(cap),
            "refusal": "no mechanism",
            "executed_transfers": 0,
        }
        (ev / "ladder").mkdir(parents=True, exist_ok=True)
        (ev / "ladder" / "refusal.json").write_text(
            json.dumps(refusal, indent=1))
    return ev


class AssemblerTerminalTests(unittest.TestCase):
    def _assemble(self, repo: Path, ev: Path) -> dict:
        import issue228_assemble as asm
        # bind the assembler's REPO to the mini repo via env override
        old = asm.REPO
        asm.REPO = repo
        try:
            # rc.ROOT also needs rebinding for verify_closure default
            old_root = rc.ROOT
            rc.ROOT = repo
            try:
                return asm.assemble(ev)
            finally:
                rc.ROOT = old_root
        finally:
            asm.REPO = old

    def test_unavailable_mechanism_yields_api_prerequisite(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            repo = build_mini_repo(tmp)
            ev = build_evidence_tree(repo, tmp)
            out = self._assemble(repo, ev)
            self.assertEqual(out["terminal"],
                             "V2E_V340L_P2P_API_PREREQUISITE")

    def test_ext_features_mechanism_yields_route_unresolved(self):
        cap = synth_capability(ext_features=True)
        stream = (synth_probe_stream(reps=5)
                  + synth_probe_stream(reps=5, direction="b_to_a",
                                       ms=0.06))
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            repo = build_mini_repo(tmp)
            ev = build_evidence_tree(repo, tmp, capability=cap,
                                     ladder_stream=stream)
            out = self._assemble(repo, ev)
            # mechanism available; transfers clean; no route counters
            self.assertEqual(out["terminal"],
                             "V2E_V340L_P2P_FUNCTIONAL_ROUTE_UNRESOLVED")

    def test_correctness_fail_blocks_pass(self):
        cap = synth_capability(multi_group=True, peer_copy=True)
        stream = synth_probe_stream(reps=5, fail_rep=3)
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            repo = build_mini_repo(tmp)
            ev = build_evidence_tree(repo, tmp, capability=cap,
                                     ladder_stream=stream)
            out = self._assemble(repo, ev)
            self.assertEqual(out["terminal"],
                             "V2E_V340L_P2P_FUNCTIONAL_ROUTE_UNRESOLVED")
            self.assertTrue(out.get("correctness_fail_retained"))

    def test_probe_nonzero_exit_blocks_pass(self):
        # a crashed probe arm is retained, never reduced to a pass
        cap = synth_capability(multi_group=True, peer_copy=True)
        stream = synth_probe_stream(reps=5)
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            repo = build_mini_repo(tmp)
            ev = build_evidence_tree(repo, tmp, capability=cap,
                                     ladder_stream=stream,
                                     ladder_exit=2)
            with self.assertRaises(Exception):
                self._assemble(repo, ev)

    def test_capability_tamper_flips_to_blocked(self):
        # control 6: relabeling capability (claiming a peer API exists)
        # diverges from the retained raw census bytes -> BLOCKED
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            repo = build_mini_repo(tmp)
            ev = build_evidence_tree(repo, tmp)
            # tamper the preflight summary but NOT the raw census
            pf = json.loads(
                (ev / "preflight" / "preflight.json").read_text())
            pf["capability"] = synth_capability(multi_group=True,
                                                peer_copy=True)
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
        # control 18: the terminal record carries the V2-D inheritance
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            repo = build_mini_repo(tmp)
            ev = build_evidence_tree(repo, tmp)
            out = self._assemble(repo, ev)
            self.assertEqual(
                out["v2d_inherited_fault"]["terminal"],
                "V2D_V340L_PLATFORM_STRESS_FAIL")

    def test_refusal_mechanism_divergence_rejected(self):
        # a refusal artifact whose mechanism classification disagrees
        # with the assembler's own re-derivation is rejected
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            repo = build_mini_repo(tmp)
            ev = build_evidence_tree(repo, tmp)
            rf = json.loads(
                (ev / "ladder" / "refusal.json").read_text())
            rf["mechanism"]["available"] = True
            (ev / "ladder" / "refusal.json").write_text(
                json.dumps(rf, indent=1))
            with self.assertRaises(Exception):
                self._assemble(repo, ev)


if __name__ == "__main__":
    unittest.main()
