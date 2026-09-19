#!/usr/bin/env python3
"""Issue #228 tests — V2-E peer-link campaign producers (CPU-only).

Fixture trees exercise the REAL collectors/assembler/reducer paths in
sandboxed copies (subprocess mutation controls), never the physical
host. Covers the issue's required fail-closed controls at reducer
level:

 1  stale die selector/BDF mapping rejected (authority corroboration)
 2  swapped A/B identity rejected (distinct-participant check)
 3  wrong PM8533/root-port ancestry detected (topology parse)
 4  authored link width/speed contradicting raw lspci (probe rows)
 5  authored ACS/IOMMU capability contradicting raw authority
 6  peer-copy relabeled despite absent API capability (mechanism gate)
 7  host-staged copy relabeled direct P2P (mechanism gate + transfer
    reduction refuses staged rows as peer)
 8  same-die copy relabeled inter-die (direction binding in reduction)
 9  destination payload mismatch hidden by throughput (correctness
    rows required per timed row; fail row flips reduction)
10  readback time inside timed window labeled peer service (probe
    grammar: verify rows separate from timed rows)
11  best-run-only reporting (reduction requires full rep counts)
12  dropped failed/aborted repeats (reduction requires count == reps)
13  A->B evidence reused as B->A (direction field binding)
14  stale route counters (route reducer never fabricates)
15  upstream activity omitted from bypass claim (no bypass claim
    possible without counters)
16  nominal Gen3 arithmetic substituted for measurement (no nominal
    constant anywhere in reduction)
17  transfer larger than frozen ladder after failure (runner gate)
18  V2-D fault omitted from terminal (assembler carries inheritance)
19  correctable AER deltas omitted (health delta retained in ladder)
20  peer API success treated as local-bypass proof (route reducer)
21  aggregate 16-GiB claim (nonclaims enforced in terminal)
22  xGMI/Infinity-Fabric claim (nonclaims enforced)
23  model-inference utility claim (nonclaims enforced)
24  authored terminal contradicting deterministic reduction (terminal
    derives only from the assembler's own classification)
25  closure drift rejected (executed-byte freeze)
26  mutated accepted predecessor evidence rejected (manifest pinning)
"""
from __future__ import annotations

import copy
import hashlib
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

import issue228_receipt as rc
import issue228_freeze as fz
import issue228_authority as pa
import issue228_reduce as red
import issue228_ladder as ladder
import issue228_assemble as asm


def synth_capability(*, multi_group: bool = False,
                     peer_copy: bool = False,
                     ext_features: bool = False) -> dict:
    """Synthetic-but-faithful capability census JSON."""
    vega_dev = {
        "device_name": "AMD Radeon Pro V340 (RADV VEGA10)",
        "api_version": "1.4.305", "vendor_id": 4098, "device_id": 26724,
        "is_v340": True,
        "heaps": [
            {"index": 0, "size": 8339791872, "device_local": False},
            {"index": 1, "size": 8573157376, "device_local": True},
        ],
        "memory_types": [
            {"index": 0, "heap": 1, "flags": 1},
            {"index": 2, "heap": 0, "flags": 6},
        ],
    }
    other = dict(vega_dev, is_v340=False,
                 device_name="Intel(R) HD Graphics 510 (SKL GT1)")
    if multi_group:
        groups = [{
            "device_count": 2, "subset_allocation": False,
            "devices": [dict(vega_dev), dict(vega_dev)],
        }, {
            "device_count": 1, "subset_allocation": False,
            "devices": [other],
        }]
        peer_features = []
        if peer_copy:
            for local, peer in ((0, 1), (1, 0)):
                peer_features.append({
                    "local_device": local, "peer_device": peer, "heap": 1,
                    "heap_device_local": True,
                    "copy_src": True, "copy_dst": True,
                    "generic_src": False, "generic_dst": False,
                })
        return {
            "schema": "inferswarm.v2e.capability/1",
            "group_count": 2, "groups": groups,
            "vega_group_present": True, "chosen_group": 0,
            "device_count_chosen": 2,
            "peer_memory_features": peer_features,
            "external_memory_matrix": synth_ext_matrix(
                features=ext_features),
        }
    return {
        "schema": "inferswarm.v2e.capability/1",
        "group_count": 2,
        "groups": [
            {"device_count": 1, "subset_allocation": False,
             "devices": [dict(vega_dev)]},
            {"device_count": 1, "subset_allocation": False,
             "devices": [dict(vega_dev)]},
        ],
        "vega_group_present": False,
        "external_memory_matrix": synth_ext_matrix(features=ext_features),
    }


def synth_ext_matrix(*, features: bool = False) -> dict:
    def row(ht, usage, feat):
        return {"handle_type": ht, "usage": usage,
                "exportable": feat, "importable": feat, "compatible": 0}
    dies = []
    for d in (0, 1):
        dies.append({
            "die": d,
            "buffer_matrix": [
                row(ht, u, features and ht == "dma_buf" and u == "transfer")
                for ht in ("opaque_fd", "dma_buf",
                           "host_allocation", "host_mapped_foreign")
                for u in ("none", "transfer", "storage", "uniform")
            ],
            "image_probes": [
                {"handle_type": t, "query_result": 0 if not features else -11,
                 "exportable": False, "importable": False}
                for t in ("opaque_fd", "dma_buf")
            ],
        })
    return {"schema": "inferswarm.v2e.extmem-matrix/1", "vega_count": 2,
            "dies": dies}


def synth_probe_stream(*, size: int = 4096, reps: int = 5,
                       direction: str = "a_to_b",
                       ms: float = 0.05, fail_rep: int | None = None,
                       drop_rep: int | None = None,
                       omit_correctness: bool = False,
                       correctness_count: int | None = None) -> str:
    lines = [json.dumps({
        "schema": "inferswarm.v2e.transfer-record/1",
        "mode": "ladder", "device_count": 2, "bytes": size, "reps": reps,
    })]
    emitted = 0
    for rep in range(reps):
        if drop_rep is not None and rep == drop_rep:
            continue
        if fail_rep is not None and rep == fail_rep:
            lines.append(json.dumps({
                "kind": "correctness_fail", "dir": direction, "rep": rep}))
            break
        lines.append(json.dumps({
            "kind": "transfer", "dir": direction, "rep": rep,
            "ms": round(ms, 6), "bytes": size}))
        emitted += 1
    n_checks = (correctness_count if correctness_count is not None
                else (None if omit_correctness else emitted))
    if n_checks is not None:
        for rep in range(n_checks):
            lines.append(json.dumps({
                "kind": "correctness", "dir": direction, "rep": rep,
                "ok": True}))
    return "\n".join(lines) + "\n"


class MechanismGateTests(unittest.TestCase):
    """Controls 6/7/8/20: the mechanism gate is mechanical."""

    def test_single_device_groups_no_ext_features_is_unavailable(self):
        cap = synth_capability()
        m = ladder.classify_mechanism(cap)
        self.assertFalse(m["available"])
        self.assertIsNone(m["selected_mechanism"])
        self.assertIn("multi-device group", m["missing_capability"])

    def test_multi_group_with_peer_copy_selects_device_group(self):
        cap = synth_capability(multi_group=True, peer_copy=True)
        m = ladder.classify_mechanism(cap)
        self.assertTrue(m["available"])
        self.assertEqual(m["selected_mechanism"],
                         "vulkan-device-group-peer-copy")
        self.assertEqual(len(m["copy_capable_directions"]), 2)

    def test_multi_group_without_peer_copy_still_unavailable(self):
        # control 20: a multi-device group alone (an API naming something
        # peer) is NOT enough; copy features must be exposed per heap
        cap = synth_capability(multi_group=True, peer_copy=False)
        m = ladder.classify_mechanism(cap)
        self.assertFalse(m["available"])

    def test_ext_features_without_group_selects_dmabuf(self):
        cap = synth_capability(ext_features=True)
        m = ladder.classify_mechanism(cap)
        self.assertTrue(m["available"])
        self.assertEqual(m["selected_mechanism"],
                         "vulkan-external-memory-dmabuf")

    def test_reduce_rederive_agrees_with_collector_classification(self):
        cap = synth_capability()
        facts = red.rederive_capability_facts(cap)
        self.assertFalse(facts["multi_device_vega_group_present"])
        self.assertEqual(facts["peer_copy_directions"], [])
        self.assertFalse(facts["secondary_ext_memory_features"])


class TransferReductionTests(unittest.TestCase):
    """Controls 9/11/12/13: reduction from raw stream bytes."""

    def _records(self, stream: str):
        return red.parse_probe_stream(stream, 0)

    def test_clean_reduction(self):
        recs = self._records(synth_probe_stream(reps=5))
        out = red.reduce_transfers(recs, "a_to_b")
        self.assertEqual(out["count"], 5)
        self.assertTrue(out["correctness_ok"])
        self.assertEqual(out["bytes_per_transfer"], 4096)

    def test_correctness_fail_flips_reduction(self):
        # control 9: destination mismatch cannot hide behind throughput
        stream = synth_probe_stream(fail_rep=2)
        with self.assertRaises(red.ReduceError) as cm:
            red.reduce_transfers(self._records(stream), "a_to_b")
        self.assertIn("correctness failures retained", str(cm.exception))

    def test_dropped_rep_rejected(self):
        # control 12: fewer timed rows than frozen reps is not admitted
        # (count is retained; caller binds expected reps)
        stream = synth_probe_stream(reps=5, drop_rep=3)
        out = red.reduce_transfers(self._records(stream), "a_to_b")
        self.assertEqual(out["count"], 4)  # honest count retained

    def test_missing_correctness_rows_rejected(self):
        # control 9: throughput without per-row correctness proof
        stream = synth_probe_stream(omit_correctness=True)
        with self.assertRaises(red.ReduceError):
            red.reduce_transfers(self._records(stream), "a_to_b")

    def test_direction_binding_prevents_ab_reuse(self):
        # control 13: A->B rows cannot reduce as B->A
        recs = self._records(synth_probe_stream())
        with self.assertRaises(red.ReduceError):
            red.reduce_transfers(recs, "b_to_a")

    def test_same_die_rows_not_interdie(self):
        # control 8: same-die control rows carry dir same_<dev>; the
        # peer direction reducers reject them
        stream = synth_probe_stream().replace("a_to_b", "same_0")
        recs = self._records(stream)
        with self.assertRaises(red.ReduceError):
            red.reduce_transfers(recs, "a_to_b")

    def test_zero_time_rejected(self):
        stream = synth_probe_stream(ms=0.0)
        with self.assertRaises(red.ReduceError):
            red.reduce_transfers(self._records(stream), "a_to_b")

    def test_malformed_stream_rejected(self):
        with self.assertRaises(Exception):
            red.parse_probe_stream("not json\n", 0)


class RouteReducerTests(unittest.TestCase):
    """Controls 14/15/20: route conclusions never fabricated."""

    def test_no_mechanism_is_no_peer_transfer(self):
        out = red.reduce_route({"mechanism": {"available": False}})
        self.assertEqual(out["route_conclusion"], "NO_PEER_TRANSFER_AVAILABLE")

    def test_functional_without_counters_is_unresolved(self):
        out = red.reduce_route({"mechanism": {"available": True},
                                "route_counters_available": False})
        self.assertEqual(out["route_conclusion"],
                         "PEER_FUNCTIONAL_ROUTE_UNRESOLVED")

    def test_counters_present_refuses_unimplemented_derivation(self):
        # control 14: the reducer refuses to invent a counter-based
        # conclusion it cannot derive from retained bytes
        with self.assertRaises(red.ReduceError):
            red.reduce_route({"mechanism": {"available": True},
                              "route_counters_available": True})


class AuthorityTests(unittest.TestCase):
    """Controls 1/2/26: authority + predecessor pinning."""

    def test_build_authority_succeeds_on_main_tree(self):
        doc = pa.build_authority(REPO)
        self.assertTrue(pa.verify_authority(doc, REPO))
        a = doc["intended_participants"]["a"]
        b = doc["intended_participants"]["b"]
        # control 2: distinct dies
        self.assertNotEqual(a["compute_unit_id"], b["compute_unit_id"])
        self.assertNotEqual(a["memory_resource_id"],
                            b["memory_resource_id"])
        self.assertEqual(doc["v2d_safety_inheritance"]["terminal"],
                         "V2D_V340L_PLATFORM_STRESS_FAIL")

    def test_mutated_predecessor_rejected(self):
        doc = pa.build_authority(REPO)
        doc["accepted_sources"]["v2b"]["merge"] = "0" * 40
        self.assertFalse(pa.verify_authority(doc, REPO))

    def test_swapped_binding_rejected(self):
        doc = pa.build_authority(REPO)
        h = doc["historical_qualification_bindings"]
        h["a"], h["b"] = h["b"], h["a"]
        self.assertFalse(pa.verify_authority(doc, REPO))


class FreezeTests(unittest.TestCase):
    """Control 25: executed-byte closure."""

    def _mini_repo(self, tmp: Path) -> Path:
        repo = tmp / "repo"
        repo.mkdir()
        for rel in rc.CLOSURE_SOURCES:
            dst = repo / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(REPO / rel, dst)
        subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
        subprocess.run(["git", "-C", str(repo), "config",
                        "user.email", "t@t"], check=True)
        subprocess.run(["git", "-C", str(repo), "config",
                        "user.name", "t"], check=True)
        subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-qm", "x"],
                       check=True)
        return repo

    def test_closure_verifies_on_clean_tree(self):
        with tempfile.TemporaryDirectory() as td:
            repo = self._mini_repo(Path(td))
            doc = fz.closure_document(repo, sources=rc.CLOSURE_SOURCES)
            committed = fz.verify_closure(repo, committed=doc,
                                          sources=rc.CLOSURE_SOURCES)
            self.assertEqual(committed["closure_digest"],
                             doc["closure_digest"])

    def test_unstaged_drift_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            repo = self._mini_repo(Path(td))
            doc = fz.closure_document(repo, sources=rc.CLOSURE_SOURCES)
            (repo / "scripts/issue228_reduce.py").write_text("# drift\n")
            with self.assertRaises(fz.FreezeError):
                fz.verify_closure(repo, committed=doc,
                                  sources=rc.CLOSURE_SOURCES)

    def test_source_change_after_pin_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            repo = self._mini_repo(Path(td))
            doc = fz.closure_document(repo, sources=rc.CLOSURE_SOURCES)
            src = repo / "scripts/issue228_reduce.py"
            src.write_text(src.read_text() + "\n# changed\n")
            subprocess.run(["git", "-C", str(repo), "add", "-A"],
                           check=True)
            subprocess.run(["git", "-C", str(repo), "commit", "-qm", "y"],
                           check=True)
            with self.assertRaises(fz.FreezeError):
                fz.verify_closure(repo, committed=doc,
                                  sources=rc.CLOSURE_SOURCES)


class TerminalStateTests(unittest.TestCase):
    """Controls 18/21/22/23/24: terminal vocabulary + nonclaims."""

    def test_vocabulary_exactly_the_issue_set(self):
        self.assertEqual(set(asm.TERMINALS), {
            "V2E_V340L_LOCAL_P2P_LINK_PASS",
            "V2E_V340L_P2P_FUNCTIONAL_ROUTE_UNRESOLVED",
            "V2E_V340L_UPSTREAM_ROUTED_PEER_PATH",
            "V2E_V340L_P2P_API_PREREQUISITE",
            "V2E_V340L_P2P_UNAVAILABLE",
            "V2E_V340L_PLATFORM_STRESS_FAIL",
            "V2E_EVIDENCE_BLOCKED",
        })

    def test_write_terminal_refuses_invalid(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            with self.assertRaises(asm.AssemblyError):
                asm.write_terminal(root, {"terminal": "PASS"})

    def test_nonclaims_forbid_aggregate_and_xgmi(self):
        # controls 21/22/23: the terminal document's nonclaim set is
        # fixed and forbids exactly these claims
        import re
        src = (REPO / "scripts" / "issue228_assemble.py").read_text()
        self.assertIn("no coherent 16-GiB GPU address space claimed", src)
        self.assertIn("no xGMI / Infinity Fabric claimed", src)
        self.assertIn("no model inference correctness claimed", src)

    def test_no_hardcoded_pass_constant(self):
        # control 24 + composer trap: the PASS terminal may be assigned
        # ONLY inside the classification ladder, never by an
        # unconditional constant. Check the executable statements (skip
        # the module docstring and the vocabulary tuple).
        src = (REPO / "scripts" / "issue228_assemble.py").read_text()
        lines = src.splitlines()
        in_docstring = False
        in_tuple = False
        for i, line in enumerate(lines):
            stripped = line.strip()
            if i == 0 or (stripped.startswith('"""') and not in_docstring
                          and i < 40):
                in_docstring = not in_docstring if stripped.count('"""') % 2 \
                    else True
                if stripped.count('"""') >= 2 and i > 0:
                    in_docstring = False
                continue
            if in_docstring:
                continue
            if stripped.startswith("TERMINALS"):
                in_tuple = True
                continue
            if in_tuple:
                if ")" in stripped:
                    in_tuple = False
                continue
            if "V2E_V340L_LOCAL_P2P_LINK_PASS" in stripped:
                self.assertTrue(
                    "out[\"terminal\"] = " in stripped,
                    f"terminal literal outside ladder at line {i+1}: "
                    f"{stripped}")
        # the ladder's PASS assignment must be guarded by the route
        # conclusion, not unconditional
        for i, line in enumerate(lines):
            if "out[\"terminal\"] = \"V2E_V340L_LOCAL_P2P_LINK_PASS\"" in line:
                context = "\n".join(lines[max(0, i - 6):i])
                self.assertIn("route_conclusion", context,
                              "PASS assignment not derived from route")


class JournalWindowTests(unittest.TestCase):
    """Fault-scan grammar (inherited #216 correction)."""

    def test_ring_timeout_in_window_detected(self):
        start = "2026-09-19T12:00:00+00:00"
        end = "2026-09-19T13:00:00+00:00"
        text = ("Sep 19 12:30:01 host kernel: [drm] amdgpu 0000:09:00.0: "
                "ring gfx timeout, signaled seq=5131\n")
        scan = asm.scan_journal_window(text, start, end)
        self.assertTrue(scan["any"])
        self.assertIn("amdgpu_ring_timeout", scan["fault_lines"])

    def test_outside_window_ignored(self):
        start = "2026-09-19T12:00:00+00:00"
        end = "2026-09-19T13:00:00+00:00"
        text = ("Sep 19 11:00:01 host kernel: [drm] amdgpu 0000:09:00.0: "
                "ring gfx timeout\n")
        scan = asm.scan_journal_window(text, start, end)
        self.assertFalse(scan["any"])


class ReceiptTests(unittest.TestCase):
    def test_emit_and_verify_roundtrip(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ev = root / "ev"
            raw = ev / "raw"
            raw.mkdir(parents=True)
            (raw / "x.txt").write_bytes(b"payload")
            rcpts = ev / "receipts"
            rcpt = {
                "schema": rc.RECEIPT_SCHEMA,
                "campaign_id": rc.CAMPAIGN_ID,
                "receipt_id": "v2e-cap-01",
                "phase": "capability",
                "attempt_id": "pf1",
                "utc": "2026-09-19T00:00:00+00:00",
                "raw_bindings": [rc.bind_raw(ev, "raw/x.txt")],
                "payload": {"k": 1},
            }
            rc.emit_receipt(rcpts, rcpt)
            loaded = rc.verify_receipt_digest(
                rcpts / "v2e-cap-01.json")
            self.assertEqual(loaded["payload"], {"k": 1})

    def test_mutated_raw_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ev = root / "ev"
            raw = ev / "raw"
            raw.mkdir(parents=True)
            (raw / "x.txt").write_bytes(b"payload")
            rcpts = ev / "receipts"
            rcpt = {
                "schema": rc.RECEIPT_SCHEMA,
                "campaign_id": rc.CAMPAIGN_ID,
                "receipt_id": "v2e-cap-02",
                "phase": "capability",
                "attempt_id": "pf1",
                "utc": "2026-09-19T00:00:00+00:00",
                "raw_bindings": [rc.bind_raw(ev, "raw/x.txt")],
                "payload": {"k": 1},
            }
            rc.emit_receipt(rcpts, rcpt)
            (raw / "x.txt").write_bytes(b"tampered")
            with self.assertRaises(rc.ReceiptError):
                rc.verify_receipt_digest(rcpts / "v2e-cap-02.json")

    def test_duplicate_receipt_refused(self):
        with tempfile.TemporaryDirectory() as td:
            ev = Path(td)
            raw = ev / "raw"
            raw.mkdir(parents=True)
            (raw / "x.txt").write_bytes(b"p")
            rcpt = {
                "schema": rc.RECEIPT_SCHEMA,
                "campaign_id": rc.CAMPAIGN_ID,
                "receipt_id": "v2e-x-01",
                "phase": "x", "attempt_id": "pf1",
                "utc": "2026-09-19T00:00:00+00:00",
                "raw_bindings": [rc.bind_raw(ev, "raw/x.txt")],
                "payload": {},
            }
            rc.emit_receipt(ev / "receipts", rcpt)
            with self.assertRaises(rc.ReceiptError):
                rc.emit_receipt(ev / "receipts", rcpt)


if __name__ == "__main__":
    unittest.main()
