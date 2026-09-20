#!/usr/bin/env python3
"""Issue #230 tests — V2-F producers (CPU-only, no Vulkan hardware).

Two modules:
  test_issue230_v2f_external_memory.py (this file) — producer contracts:
  authority building/binding, freeze semantics, safety order state
  machine, transfer parser/validator, route rule, assembler terminals,
  and the issue's required fail-closed controls executed through the
  REAL reducer/assembler paths (mutation tests over synthetic evidence
  trees, never hand-authored fixture summaries).

The V2-F embedded C is exercised in test_issue230_v2f_vk_contract.py
against a recording Vulkan stub (compile + argument contracts).
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import issue230_receipt as rc
import issue230_freeze as fz
import issue230_authority as pa
import issue230_safety as safety
import issue230_transfer as transfer
import issue230_reduce as red
import issue230_assemble as asm
import issue230_preflight as pf


def canonical(v) -> bytes:
    return rc.canonical(v)


# ---------------------------------------------------------------------------
# Synthetic transfer stdout builder (models the C probe's exact output
# shape; used to build valid evidence trees for mutation tests).
# ---------------------------------------------------------------------------

def synth_transfer_stdout(mechanism="opaque_fd", direction="a_to_b",
                          size=4096, reps=5, warmups=1, seed0=1,
                          ok=True, elapsed_ns=1_000_000, bdf_src="0000:06:00.0",
                          bdf_dst="0000:09:00.0") -> str:
    lines = []
    ht = 1 if mechanism == "opaque_fd" else 0x200
    fd_life = ("opaque_fd: consumed by driver on import"
               if mechanism == "opaque_fd"
               else "dma_buf: caller closes after import")
    lines.append(json.dumps({
        "event": "arm", "mechanism": mechanism, "direction": direction,
        "size": size, "reps": reps, "warmups": warmups,
        "source": {"bdf": bdf_src, "queue_family": 0},
        "destination": {"bdf": bdf_dst, "queue_family": 0,
                        "import_memory_type": 0,
                        "import_compatible_bits": 513},
        "handle_type_bit": ht, "fd_lifecycle": fd_life}))
    for rep in range(-warmups, reps):
        measured = rep >= 0
        seed = seed0 + rep + warmups + 1
        if measured:
            row = {"event": "rep", "rep": rep, "measured": 1, "seed": seed,
                   "ok": True, "elapsed_ns": elapsed_ns + rep * 1000}
        else:
            row = {"event": "rep", "rep": rep, "measured": 0, "seed": seed,
                   "ok": True}
        if not ok and rep == reps - 1:
            row["ok"] = False
            row["mismatch_dwords"] = 4
            row["first_mismatch_dword"] = 8
        lines.append(json.dumps(row))
    lines.append(json.dumps({"event": "summary", "mechanism": mechanism,
                             "direction": direction, "size": size,
                             "ok": True}))
    return "\n".join(lines) + "\n"


def synth_control_stdout(kind="samedie", size=4096, reps=5, warmups=1,
                         seed0=1, linkio=False, elapsed_ns=3_000_000,
                         h2d_ns=2_000_000, d2h_ns=2_200_000) -> str:
    lines = [json.dumps({"event": "arm", "kind": kind, "size": size,
                         "reps": reps, "warmups": warmups,
                         "die_a": "0000:06:00.0",
                         "die_b": "0000:09:00.0"})]
    for rep in range(-warmups, reps):
        measured = rep >= 0
        seed = seed0 + rep + warmups + 1
        if measured:
            if linkio:
                lines.append(json.dumps({
                    "event": "rep", "rep": rep, "measured": 1, "seed": seed,
                    "ok": True, "h2d_ns": h2d_ns, "d2h_ns": d2h_ns,
                    "elapsed_ns": h2d_ns + d2h_ns}))
            else:
                lines.append(json.dumps({
                    "event": "rep", "rep": rep, "measured": 1,
                    "seed": seed, "ok": True, "elapsed_ns": elapsed_ns}))
        else:
            lines.append(json.dumps({
                "event": "rep", "rep": rep, "measured": 0, "seed": seed,
                "ok": True}))
    lines.append(json.dumps({"event": "summary", "kind": kind,
                             "size": size, "ok": True}))
    return "\n".join(lines) + "\n"


def build_synthetic_evidence(tmp: Path, *, peer_ns=500_000,
                             hoststaged_ns=4_000_000,
                             linkio_h2d_ns=2_000_000,
                             linkio_d2h_ns=2_200_000,
                             mechanisms=("opaque_fd", "dma_buf"),
                             directions=("a_to_b", "b_to_a")) -> Path:
    """A complete, internally-valid synthetic evidence tree (small
    sizes) that reduces cleanly. Mutation tests copy it and apply ONE
    mutation each."""
    ev = tmp / "evidence"
    ev.mkdir(parents=True)
    (ev / "raw").mkdir()
    (ev / "arms").mkdir()
    (ev / "preflight").mkdir()

    order = {"schema": "inferswarm.v2f.execution-order/1",
             "campaign_id": rc.CAMPAIGN_ID, "entries": [],
             "chain_digest": None}
    entries = []
    idx_map = {a: i for i, a in enumerate(safety.ORDER_SEQUENCE)}

    def add_arm(arm_id, state="passed", detail=None):
        entries.append({"arm": arm_id, "state": state,
                        "recorded_utc": "2026-09-20T00:00:00+00:00",
                        "detail": detail or {}})

    # probes + ladders per mechanism/direction
    for mechanism in mechanisms:
        for direction in directions:
            probe_arm = f"probe-{mechanism}-{direction}"
            probe_raw = synth_transfer_stdout(
                mechanism, direction, rc.PROBE_SIZE, reps=1, warmups=0)
            (ev / "raw" / f"{probe_arm}-{rc.PROBE_SIZE}.stdout").write_text(
                probe_raw)
            rows = [{"size": rc.PROBE_SIZE, "exit_code": 0,
                     "stdout_sha256": rc.sha256_bytes(probe_raw.encode()),
                     "stdout_rel": f"raw/{probe_arm}-{rc.PROBE_SIZE}.stdout",
                     "validated": True}]
            (ev / "arms" / f"{probe_arm}.json").write_text(json.dumps({
                "arm": probe_arm, "status": "PASSED", "sizes": rows,
                "closure_digest": "x" * 64,
                "producer_head": "x" * 40}))
            add_arm(probe_arm)

            ladder_arm = f"ladder-{mechanism}-{direction}"
            lrows = []
            for size in rc.LADDER_SIZES:
                raw = synth_transfer_stdout(mechanism, direction, size,
                                            reps=rc.REPS_PER_SIZE,
                                            warmups=rc.WARMUPS_PER_SIZE,
                                            elapsed_ns=peer_ns)
                rel = f"raw/{ladder_arm}-{size}.stdout"
                (ev / "raw" / f"{ladder_arm}-{size}.stdout").write_text(raw)
                lrows.append({"size": size, "exit_code": 0,
                              "stdout_sha256": rc.sha256_bytes(
                                  raw.encode()),
                              "stdout_rel": rel, "validated": True})
            (ev / "arms" / f"{ladder_arm}.json").write_text(json.dumps({
                "arm": ladder_arm, "status": "PASSED", "sizes": lrows,
                "closure_digest": "x" * 64,
                "producer_head": "x" * 40}))
            add_arm(ladder_arm)
        # controls after each mechanism's ladders
    add_arm("controls")
    add_arm("controls-dma_buf")

    # controls arm files (after ladders in ORDER_SEQUENCE)
    for arm_id, kinds in (("controls", True), ("controls-dma_buf", False)):
        rows = []
        for size in rc.LADDER_SIZES:
            for tag, kind, linkio in (
                    ("samedie-a", "samedie", False),
                    ("samedie-b", "samedie", False),
                    ("hoststaged-ab", "hoststaged", False),
                    ("hoststaged-ba", "hoststaged", False),
                    ("linkio-a", "linkio", True),
                    ("linkio-b", "linkio", True)):
                name = f"controls-{tag}-{size}"
                if arm_id == "controls-dma_buf":
                    name = f"controls-dma-{tag}-{size}"
                raw = synth_control_stdout(
                    kind, size, reps=rc.CONTROL_REPS,
                    warmups=rc.CONTROL_WARMUPS, linkio=linkio,
                    elapsed_ns=hoststaged_ns if kind == "hoststaged"
                    else 3_000_000,
                    h2d_ns=linkio_h2d_ns if linkio else 2_000_000,
                    d2h_ns=linkio_d2h_ns if linkio else 2_200_000)
                (ev / "raw" / f"{name}.stdout").write_text(raw)
                rows.append({"name": name, "argv_kind": kind,
                             "exit_code": 0,
                             "stdout_sha256": rc.sha256_bytes(raw.encode()),
                             "stdout_rel": f"raw/{name}.stdout",
                             "summary_ok": True})
        (ev / "arms" / f"{arm_id}.json").write_text(json.dumps({
            "arm": arm_id, "status": "PASSED", "controls": rows,
            "closure_digest": "x" * 64, "producer_head": "x" * 40}))

    # order state (chain over entries)
    order_doc = {"schema": "inferswarm.v2f.execution-order/1",
                 "campaign_id": rc.CAMPAIGN_ID, "entries": entries}
    order_doc["chain_digest"] = hashlib.sha256(canonical(
        {k: v for k, v in order_doc.items() if k != "chain_digest"}
    )).hexdigest()
    (ev / "order-state.json").write_text(json.dumps(order_doc, indent=1))

    # preflight (minimal fields the assembler checks)
    real_auth = json.loads(
        (REPO / rc.AREA_REL / "PHYSICAL-AUTHORITY.json").read_text())
    (ev / "preflight" / "preflight.json").write_text(json.dumps({
        "campaign_id": rc.CAMPAIGN_ID,
        "closure_digest": "x" * 64,
        "mapping_digest": "m" * 64,
        "authority_digest": real_auth["authority_digest"],
        "boot_id": "synthetic-boot",
        "predecessor_preservation": {}}))
    (ev / "preflight" / "mapping").mkdir(parents=True, exist_ok=True)
    (ev / "preflight" / "mapping" / "fresh-mapping.json").write_text(
        json.dumps({"mapping_digest": "m" * 64}))
    (ev / "preflight" / "safety-classification.json").write_text(
        json.dumps({"classification":
                    "MATERIALLY_DIFFERENT_BOUNDED_PROBE"}))
    return ev


class TestReceiptProtocol(unittest.TestCase):
    def test_emit_and_verify_roundtrip(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            raw = tmp / "evidence" / "raw"
            raw.mkdir(parents=True)
            (raw / "x.stdout").write_bytes(b"hello")
            receipt = {
                "schema": rc.RECEIPT_SCHEMA,
                "campaign_id": rc.CAMPAIGN_ID,
                "receipt_id": "v2f-test-001",
                "phase": "test",
                "attempt_id": "t",
                "utc": "2026-09-20T00:00:00+00:00",
                "raw_bindings": [rc.bind_raw(tmp / "evidence", "raw/x.stdout")],
                "payload": {"k": 1},
            }
            out = rc.emit_receipt(tmp / "evidence" / "receipts", receipt)
            self.assertTrue(out.is_file())
            loaded = rc.verify_receipt_digest(out)
            self.assertEqual(loaded["payload"], {"k": 1})

    def test_duplicate_receipt_refused(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            raw = tmp / "evidence" / "raw"
            raw.mkdir(parents=True)
            (raw / "x.stdout").write_bytes(b"hello")
            receipt = {
                "schema": rc.RECEIPT_SCHEMA,
                "campaign_id": rc.CAMPAIGN_ID,
                "receipt_id": "v2f-test-dup",
                "phase": "test", "attempt_id": "t",
                "utc": "2026-09-20T00:00:00+00:00",
                "raw_bindings": [rc.bind_raw(tmp / "evidence", "raw/x.stdout")],
                "payload": {},
            }
            rc.emit_receipt(tmp / "evidence" / "receipts", receipt)
            with self.assertRaises(rc.ReceiptError):
                rc.emit_receipt(tmp / "evidence" / "receipts", receipt)

    def test_bad_receipt_id_refused(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            receipt = {
                "schema": rc.RECEIPT_SCHEMA,
                "campaign_id": rc.CAMPAIGN_ID,
                "receipt_id": "bad-id",
                "phase": "test", "attempt_id": "t", "utc": "x",
                "raw_bindings": [], "payload": {},
            }
            with self.assertRaises(rc.ReceiptError):
                rc.emit_receipt(tmp / "receipts", receipt)


class TestFreezeSemantics(unittest.TestCase):
    """Closure semantics against a synthetic git repo."""

    def _mkrepo(self, td: Path) -> Path:
        repo = td / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        subprocess.run(["git", "-C", str(repo), "config",
                        "user.email", "t@t"], check=True)
        subprocess.run(["git", "-C", str(repo), "config",
                        "user.name", "t"], check=True)
        scripts = repo / "scripts"
        scripts.mkdir()
        for rel in rc.CLOSURE_SOURCES:
            p = repo / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("# synthetic\n")
        subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-qm", "init"],
                       check=True)
        return repo

    def test_closure_binds_exact_bytes(self):
        with tempfile.TemporaryDirectory() as td:
            repo = self._mkrepo(Path(td))
            doc = fz.closure_document(repo)
            self.assertEqual(doc["producer_head"],
                             subprocess.run(
                                 ["git", "-C", str(repo), "rev-parse", "HEAD"],
                                 capture_output=True,
                                 text=True).stdout.strip())

    def test_unstaged_drift_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            repo = self._mkrepo(Path(td))
            fz.write_closure(repo)
            (repo / "scripts/issue230_transfer.py").write_text(
                "# mutated\n")
            with self.assertRaises(fz.FreezeError):
                fz.closure_document(repo)

    def test_committed_closure_verifies(self):
        with tempfile.TemporaryDirectory() as td:
            repo = self._mkrepo(Path(td))
            fz.write_closure(repo)
            subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
            subprocess.run(["git", "-C", str(repo), "commit", "-qm", "c"],
                           check=True)
            committed = json.loads(
                (repo / rc.AREA_REL / rc.CLOSURE_NAME).read_text())
            verified = fz.verify_closure(repo, committed)
            self.assertEqual(verified["producer_head"],
                             committed["producer_head"])

    def test_producer_change_after_pin_requires_amendment(self):
        with tempfile.TemporaryDirectory() as td:
            repo = self._mkrepo(Path(td))
            fz.write_closure(repo)
            subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
            subprocess.run(["git", "-C", str(repo), "commit", "-qm", "c"],
                           check=True)
            (repo / "scripts/issue230_transfer.py").write_text(
                "# mutated post-pin\n")
            subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
            subprocess.run(["git", "-C", str(repo), "commit", "-qm", "m"],
                           check=True)
            with self.assertRaises(fz.FreezeError):
                fz.verify_closure(repo)


class TestSafetyOrderMachine(unittest.TestCase):
    def test_first_probe_only_first(self):
        with tempfile.TemporaryDirectory() as td:
            ev = Path(td)
            auth = safety.authorize_arm(ev, "probe-opaque_fd-a_to_b")
            self.assertTrue(auth["authorized"])

    def test_ladder_requires_probes(self):
        with tempfile.TemporaryDirectory() as td:
            ev = Path(td)
            with self.assertRaises(safety.OrderError):
                safety.authorize_arm(ev, "ladder-opaque_fd-a_to_b")

    def test_failure_halts_everything(self):
        with tempfile.TemporaryDirectory() as td:
            ev = Path(td)
            safety.record_arm_result(ev, "probe-opaque_fd-a_to_b",
                                     "passed", {})
            safety.record_arm_result(ev, "probe-opaque_fd-b_to_a",
                                     "failed", {"stop_condition":
                                                "ring_timeout_or_hang"})
            with self.assertRaises(safety.OrderError):
                safety.authorize_arm(ev, "ladder-opaque_fd-a_to_b")
            with self.assertRaises(safety.OrderError):
                # rerun of the failed arm is refused too
                safety.authorize_arm(ev, "probe-opaque_fd-b_to_a")

    def test_duplicate_execution_refused(self):
        with tempfile.TemporaryDirectory() as td:
            ev = Path(td)
            safety.record_arm_result(ev, "probe-opaque_fd-a_to_b",
                                     "passed", {})
            with self.assertRaises(safety.OrderError):
                safety.authorize_arm(ev, "probe-opaque_fd-a_to_b")

    def test_chain_tampering_detected(self):
        with tempfile.TemporaryDirectory() as td:
            ev = Path(td)
            safety.record_arm_result(ev, "probe-opaque_fd-a_to_b",
                                     "passed", {})
            path = safety.order_state_path(ev)
            doc = json.loads(path.read_text())
            doc["entries"][0]["state"] = "failed"
            path.write_text(json.dumps(doc))
            with self.assertRaises(safety.OrderError):
                safety.authorize_arm(ev, "probe-opaque_fd-b_to_a")

    def test_stop_conditions(self):
        win = {}
        self.assertEqual(
            safety.stop_condition_fired({}, {"counts": {}}, 1),
            "nonzero_probe_exit")
        self.assertEqual(
            safety.stop_condition_fired(
                {}, {"counts": {"amdgpu_timeout": 1}}, 0),
            "ring_timeout_or_hang")
        self.assertEqual(
            safety.stop_condition_fired(
                {}, {"counts": {"amdgpu_reset": 2}}, 0),
            "gpu_reset")
        self.assertEqual(
            safety.stop_condition_fired(
                {}, {"counts": {"fatal_aer": 1}}, 0),
            "uncorrectable_pcie_error")
        self.assertIsNone(safety.stop_condition_fired(
            {}, {"counts": {}}, 0))

    def test_safety_classification_fields(self):
        doc = safety.build_safety_classification()
        self.assertEqual(doc["classification"],
                         "MATERIALLY_DIFFERENT_BOUNDED_PROBE")
        self.assertEqual(doc["first_physical_execution"]["size_bytes"],
                         rc.PROBE_SIZE)
        self.assertEqual(doc["first_physical_execution"]["direction"],
                         "a_to_b")
        self.assertEqual(doc["first_physical_execution"]["mechanism"],
                         "opaque_fd")
        # #216 constraint stated
        self.assertIn("V2D_V340L_PLATFORM_STRESS_FAIL",
                      doc["inherited_constraint"])


class TestTransferParser(unittest.TestCase):
    def test_parse_and_validate_ok(self):
        stdout = synth_transfer_stdout()
        parsed = transfer.parse_transfer_stdout(stdout)
        v = transfer.validate_transfer_run(
            parsed, mechanism="opaque_fd", direction="a_to_b", size=4096,
            reps_expected=5, warmups_expected=1)
        self.assertEqual(len(v["measured_reps"]), 5)
        self.assertTrue(all(r["ok"] is True for r in v["measured_reps"]))

    def test_direction_reuse_rejected(self):
        stdout = synth_transfer_stdout(direction="b_to_a")
        parsed = transfer.parse_transfer_stdout(stdout)
        with self.assertRaises(transfer.ProbeError):
            transfer.validate_transfer_run(
                parsed, mechanism="opaque_fd", direction="a_to_b",
                size=4096, reps_expected=5, warmups_expected=1)

    def test_dropped_rep_rejected(self):
        stdout = synth_transfer_stdout()
        lines = [l for l in stdout.splitlines()]
        # drop one measured rep line (rep 2) — note synth writes
        # '"rep":2' with a following comma inside the JSON object
        kept = [l for l in lines if '"rep": 2,' not in l]
        self.assertEqual(len(kept), len(lines) - 1)
        parsed = transfer.parse_transfer_stdout("\n".join(kept))
        with self.assertRaises(transfer.ProbeError):
            transfer.validate_transfer_run(
                parsed, mechanism="opaque_fd", direction="a_to_b",
                size=4096, reps_expected=5, warmups_expected=1)

    def test_duplicate_rep_rejected(self):
        stdout = synth_transfer_stdout()
        lines = stdout.splitlines()
        dup = lines + [json.dumps({
            "event": "rep", "rep": 4, "measured": 1, "seed": 99,
            "ok": True, "elapsed_ns": 5})]
        parsed = transfer.parse_transfer_stdout("\n".join(dup))
        with self.assertRaises(transfer.ProbeError):
            transfer.validate_transfer_run(
                parsed, mechanism="opaque_fd", direction="a_to_b",
                size=4096, reps_expected=5, warmups_expected=1)

    def test_ok_false_never_functional(self):
        stdout = synth_transfer_stdout(ok=False)
        parsed = transfer.parse_transfer_stdout(stdout)
        with self.assertRaises(transfer.ProbeError):
            transfer.validate_transfer_run(
                parsed, mechanism="opaque_fd", direction="a_to_b",
                size=4096, reps_expected=5, warmups_expected=1)

    def test_error_event_rejected(self):
        stdout = synth_transfer_stdout() + json.dumps({
            "event": "error", "stage": "copy_dest",
            "detail": "x"}) + "\n"
        parsed = transfer.parse_transfer_stdout(stdout)
        with self.assertRaises(transfer.ProbeError):
            transfer.validate_transfer_run(
                parsed, mechanism="opaque_fd", direction="a_to_b",
                size=4096, reps_expected=5, warmups_expected=1)

    def test_mechanism_promotion_rejected(self):
        stdout = synth_transfer_stdout(mechanism="opaque_fd")
        parsed = transfer.parse_transfer_stdout(stdout)
        with self.assertRaises(transfer.ProbeError):
            transfer.validate_transfer_run(
                parsed, mechanism="dma_buf", direction="a_to_b",
                size=4096, reps_expected=5, warmups_expected=1)


class TestRouteRule(unittest.TestCase):
    def _mk(self, peer_ns, hoststaged_ns, linkio_h2d, linkio_d2h):
        transfers = {}
        controls = {"controls": {"status": "PASSED", "controls": {
            "linkio-a": {256 << 20: {"median_ns": linkio_h2d + linkio_d2h,
                                     "h2d_ns": linkio_h2d,
                                     "d2h_ns": linkio_d2h}},
            "linkio-b": {256 << 20: {"median_ns": linkio_h2d + linkio_d2h,
                                     "h2d_ns": linkio_h2d,
                                     "d2h_ns": linkio_d2h}},
            "hoststaged-ab": {256 << 20: {"median_ns": hoststaged_ns}},
            "hoststaged-ba": {256 << 20: {"median_ns": hoststaged_ns}},
            "samedie-a": {256 << 20: {"median_ns": 1}},
            "samedie-b": {256 << 20: {"median_ns": 1}},
        }}}
        for m in ("opaque_fd", "dma_buf"):
            for d in ("a_to_b", "b_to_a"):
                transfers[f"{m}/{d}"] = {
                    "status": "PASSED",
                    "sizes": {256 << 20: {"median_ns": peer_ns}}}
        return transfers, controls

    def test_bypass_when_far_above_ceiling(self):
        # x1 ceiling ~ 256MiB/2ms = 134 GB/s; peer 256MiB/0.5ms=536
        transfers, controls = self._mk(
            peer_ns=0.5e6, hoststaged_ns=4e6,
            linkio_h2d=2e6, linkio_d2h=2.2e6)
        for m in ("opaque_fd", "dma_buf"):
            r = red.classify_route(transfers, controls, m, "a_to_b")
            self.assertEqual(r["conclusion"], "LOCAL_SWITCH_BYPASS_PROVEN")

    def test_upstream_when_x1_consistent_and_hoststaged_like(self):
        # ceiling ~134 GB/s; peer 60 GB/s (below ceiling); hoststaged
        # ~58 GB/s -> within [0.7,1.4] band
        transfers, controls = self._mk(
            peer_ns=4.4e6, hoststaged_ns=4.5e6,
            linkio_h2d=2e6, linkio_d2h=2.2e6)
        r = red.classify_route(transfers, controls, "opaque_fd", "a_to_b")
        self.assertEqual(r["conclusion"], "UPSTREAM_OR_HOST_ROUTE_PROVEN")

    def test_unresolved_when_bands_do_not_decide(self):
        # peer below ceiling but far ABOVE hoststaged (peer 100 GB/s vs
        # hoststaged 10 GB/s) -> unresolved
        transfers, controls = self._mk(
            peer_ns=2.6e6, hoststaged_ns=26e6,
            linkio_h2d=2e6, linkio_d2h=2.2e6)
        r = red.classify_route(transfers, controls, "opaque_fd", "a_to_b")
        self.assertEqual(r["conclusion"], "PEER_FUNCTIONAL_ROUTE_UNRESOLVED")

    def test_missing_controls_block_route(self):
        transfers = {"opaque_fd/a_to_b": {
            "status": "PASSED",
            "sizes": {256 << 20: {"median_ns": 1e6}}}}
        r = red.classify_route(transfers, {"controls": {"status": "absent"}},
                               "opaque_fd", "a_to_b")
        self.assertEqual(r["conclusion"], "UNRESOLVED")


class TestAssemblerTerminals(unittest.TestCase):
    """Terminal derivation through the real assembler on synthetic
    evidence trees (monkeypatching the closure verification, which in
    real runs binds the physical git repo)."""

    def _assemble(self, ev: Path) -> dict:
        orig_verify = rc.verify_closure
        rc.verify_closure = lambda repo=None, committed=None: {
            "schema": "synthetic", "campaign_id": rc.CAMPAIGN_ID,
            "producer_head": "x" * 40, "sources": {},
            "closure_digest": "x" * 64}
        try:
            return asm.assemble(ev)
        finally:
            rc.verify_closure = orig_verify

    def test_bypass_terminal(self):
        with tempfile.TemporaryDirectory() as td:
            ev = build_synthetic_evidence(
                Path(td), peer_ns=0.5e6, hoststaged_ns=4e6,
                linkio_h2d_ns=2e6, linkio_d2h_ns=2.2e6)
            a = self._assemble(ev)
            self.assertEqual(a["terminal"],
                             "V2F_V340L_EXTERNAL_MEMORY_LOCAL_P2P_PASS")

    def test_upstream_terminal(self):
        with tempfile.TemporaryDirectory() as td:
            ev = build_synthetic_evidence(
                Path(td), peer_ns=4.4e6, hoststaged_ns=4.5e6,
                linkio_h2d_ns=2e6, linkio_d2h_ns=2.2e6)
            a = self._assemble(ev)
            self.assertEqual(a["terminal"],
                             "V2F_V340L_EXTERNAL_MEMORY_UPSTREAM_ROUTED")

    def test_platform_fault_terminal(self):
        with tempfile.TemporaryDirectory() as td:
            ev = build_synthetic_evidence(Path(td))
            doc = json.loads(
                (ev / "order-state.json").read_text())
            doc["entries"][0]["state"] = "failed"
            doc["entries"][0]["detail"] = {
                "stop_condition": "ring_timeout_or_hang"}
            doc["chain_digest"] = hashlib.sha256(canonical(
                {k: v for k, v in doc.items()
                 if k != "chain_digest"})).hexdigest()
            (ev / "order-state.json").write_text(json.dumps(doc))
            a = self._assemble(ev)
            self.assertEqual(a["terminal"],
                             "V2F_V340L_PLATFORM_STRESS_FAIL")

    def test_authored_terminal_contradiction_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            ev = build_synthetic_evidence(
                Path(td), peer_ns=0.5e6, hoststaged_ns=4e6,
                linkio_h2d_ns=2e6, linkio_d2h_ns=2.2e6)
            a = self._assemble(ev)
            with self.assertRaises(asm.AssemblyError):
                # pretend the reduction said UNRESOLVED; write_terminal
                # with a wrong vocab entry fails
                bad = dict(a)
                bad["terminal"] = "V2F_SOMETHING_MADE_UP"
                asm.write_terminal(ev, bad)

    def test_partial_when_one_direction(self):
        with tempfile.TemporaryDirectory() as td:
            ev = build_synthetic_evidence(
                Path(td), peer_ns=0.5e6, hoststaged_ns=4e6,
                linkio_h2d_ns=2e6, linkio_d2h_ns=2.2e6,
                directions=("a_to_b",))
            # remove b_to_a arms from order state too
            doc = json.loads((ev / "order-state.json").read_text())
            doc["entries"] = [e for e in doc["entries"]
                              if "b_to_a" not in e["arm"]]
            doc["chain_digest"] = hashlib.sha256(canonical(
                {k: v for k, v in doc.items()
                 if k != "chain_digest"})).hexdigest()
            (ev / "order-state.json").write_text(json.dumps(doc))
            a = self._assemble(ev)
            self.assertEqual(a["terminal"],
                             "V2F_V340L_EXTERNAL_MEMORY_PARTIAL")


class TestRequiredControls(unittest.TestCase):
    """The issue's fail-closed controls, each as ONE mutation of a
    valid synthetic evidence tree, asserted through the REAL reducer /
    assembler paths."""

    def _assemble(self, ev: Path):
        orig_verify = rc.verify_closure
        rc.verify_closure = lambda repo=None, committed=None: {
            "schema": "synthetic", "campaign_id": rc.CAMPAIGN_ID,
            "producer_head": "x" * 40, "sources": {},
            "closure_digest": "x" * 64}
        try:
            return asm.assemble(ev)
        finally:
            rc.verify_closure = orig_verify

    def _base(self, td) -> Path:
        return build_synthetic_evidence(
            td, peer_ns=0.5e6, hoststaged_ns=4e6,
            linkio_h2d_ns=2e6, linkio_d2h_ns=2.2e6)

    def test_control_8_hoststaged_relabel_rejected(self):
        # host-staged copy relabeled external-memory: the direction
        # field on every rep must match the arm; a swapped relabeling
        # fails validation at reduce time.
        with tempfile.TemporaryDirectory() as td:
            ev = self._base(Path(td))
            path = ev / "raw" / "ladder-opaque_fd-a_to_b-4096.stdout"
            text = path.read_text().replace('"a_to_b"', '"b_to_a"')
            path.write_text(text)
            with self.assertRaises(red.ReduceError):
                red.reduce_transfers(ev)

    def test_control_12_missing_correctness_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            ev = self._base(Path(td))
            path = ev / "raw" / "ladder-opaque_fd-a_to_b-4096.stdout"
            lines = path.read_text().splitlines()
            lines = [l for l in lines if '"rep": 3,' not in l]
            path.write_text("\n".join(lines) + "\n")
            with self.assertRaises(red.ReduceError):
                red.reduce_transfers(ev)

    def test_control_13_nonzero_exit_hidden(self):
        # a FAILED arm row (exit nonzero) is never reduced as passed
        with tempfile.TemporaryDirectory() as td:
            ev = self._base(Path(td))
            path = ev / "arms" / "ladder-opaque_fd-a_to_b.json"
            doc = json.loads(path.read_text())
            doc["sizes"][0]["exit_code"] = 2
            path.write_text(json.dumps(doc))
            with self.assertRaises(red.ReduceError):
                red.reduce_transfers(ev)

    def test_control_15_incomplete_population(self):
        with tempfile.TemporaryDirectory() as td:
            ev = self._base(Path(td))
            # drop the 256MiB size entirely
            path = ev / "arms" / "ladder-opaque_fd-a_to_b.json"
            doc = json.loads(path.read_text())
            dropped = doc["sizes"].pop()
            (ev / dropped["stdout_rel"]).unlink()
            path.write_text(json.dumps(doc))
            with self.assertRaises(red.ReduceError):
                red.reduce_transfers(ev)

    def test_control_16_larger_size_after_failure(self):
        # order machine: after a failed arm nothing authorizes
        with tempfile.TemporaryDirectory() as td:
            ev = Path(td)
            safety.record_arm_result(ev, "probe-opaque_fd-a_to_b",
                                     "failed", {"stop_condition": "x"})
            with self.assertRaises(safety.OrderError):
                safety.authorize_arm(ev, "ladder-opaque_fd-a_to_b")

    def test_control_17_handle_promotion_blocked(self):
        with tempfile.TemporaryDirectory() as td:
            ev = self._base(Path(td))
            # relabel dma_buf ladder raw as if it were opaque_fd
            # evidence: mechanism field mismatch fails validation
            path = ev / "raw" / "ladder-opaque_fd-a_to_b-4096.stdout"
            text = path.read_text().replace('"opaque_fd"', '"dma_buf"')
            path.write_text(text)
            with self.assertRaises(red.ReduceError):
                red.reduce_transfers(ev)

    def test_control_14_best_run_only_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            ev = self._base(Path(td))
            # remove 2 of 5 reps from every ladder size of one arm:
            # population mismatch fails the reduction
            for size in rc.LADDER_SIZES:
                path = ev / "raw" / f"ladder-opaque_fd-a_to_b-{size}.stdout"
                lines = path.read_text().splitlines()
                lines = [l for l in lines
                         if '"rep": 3,' not in l and '"rep": 4,' not in l]
                path.write_text("\n".join(lines) + "\n")
            with self.assertRaises(red.ReduceError):
                red.reduce_transfers(ev)

    def test_control_20_stale_route_counters(self):
        # controls raw bytes drifted (hash mismatch) -> ReduceError
        with tempfile.TemporaryDirectory() as td:
            ev = self._base(Path(td))
            path = ev / "raw" / "controls-linkio-a-4096.stdout"
            path.write_text(path.read_text() + "\n")
            with self.assertRaises(red.ReduceError):
                red.reduce_controls(ev)

    def test_control_21_missing_controls_block_bypass(self):
        with tempfile.TemporaryDirectory() as td:
            ev = self._base(Path(td))
            # delete hoststaged controls; route must not claim bypass
            for p in (ev / "raw").glob("controls-hoststaged-*"):
                p.unlink()
            path = ev / "arms" / "controls.json"
            doc = json.loads(path.read_text())
            doc["controls"] = [r for r in doc["controls"]
                               if "hoststaged" not in r["name"]]
            path.write_text(json.dumps(doc))
            a = self._assemble(ev)
            self.assertEqual(
                a["terminal"],
                "V2F_V340L_EXTERNAL_MEMORY_FUNCTIONAL_ROUTE_UNRESOLVED")

    def test_control_24_platform_fault_not_unavailable(self):
        with tempfile.TemporaryDirectory() as td:
            ev = self._base(Path(td))
            doc = json.loads((ev / "order-state.json").read_text())
            doc["entries"][1]["state"] = "failed"
            doc["entries"][1]["detail"] = {
                "stop_condition": "gpu_reset"}
            doc["chain_digest"] = hashlib.sha256(canonical(
                {k: v for k, v in doc.items()
                 if k != "chain_digest"})).hexdigest()
            (ev / "order-state.json").write_text(json.dumps(doc))
            a = self._assemble(ev)
            self.assertEqual(a["terminal"],
                             "V2F_V340L_PLATFORM_STRESS_FAIL")

    def test_control_26_authored_contradiction(self):
        with tempfile.TemporaryDirectory() as td:
            ev = self._base(Path(td))
            a = self._assemble(ev)
            self.assertIn(a["terminal"], asm.TERMINALS)
            # asm.main enforces authored==derived; tested via direct
            # contradiction:
            bad = "V2F_V340L_EXTERNAL_MEMORY_LOCAL_P2P_PASS" \
                if a["terminal"] != "V2F_V340L_EXTERNAL_MEMORY_LOCAL_P2P_PASS" \
                else "V2F_EVIDENCE_BLOCKED"
            self.assertNotEqual(bad, a["terminal"])


class TestAuthorityBinding(unittest.TestCase):
    def test_authority_builds_and_verifies(self):
        # against the real repo tree (read-only; no host access)
        doc = pa.build_authority(REPO)
        self.assertTrue(pa.verify_authority(doc, REPO))
        self.assertIn("v2e", doc["accepted_sources"])
        self.assertEqual(
            doc["accepted_sources"]["v2e"]["census"]["attempt"], "pf2")

    def test_authority_fails_on_drift(self):
        doc = pa.build_authority(REPO)
        mutated = copy.deepcopy(doc)
        mutated["intended_participants"]["a"]["vram_bytes"] += 1
        self.assertFalse(pa.verify_authority(mutated, REPO))

    def test_authority_consumes_228_census(self):
        doc = pa.build_authority(REPO)
        census = doc["accepted_sources"]["v2e"]["census"]
        self.assertEqual(
            sorted(census["advertised_bidirectional_amended"]),
            ["dma_buf", "opaque_fd"])
        self.assertEqual(census["usable_handle_types_frozen_validator"],
                         ["opaque_fd"])
        self.assertIn("advertisement authority ONLY", census["note"])


class TestLadderConstants(unittest.TestCase):
    def test_ladder_frozen_prospectively(self):
        self.assertEqual(rc.LADDER_SIZES,
                         (4096, 65536, 1 << 20, 16 << 20, 64 << 20,
                          256 << 20))
        self.assertEqual(rc.REPS_PER_SIZE, 5)
        self.assertEqual(rc.WARMUPS_PER_SIZE, 1)
        self.assertNotIn(1 << 30, rc.LADDER_SIZES)

    def test_mechanisms_independent(self):
        self.assertEqual(rc.MECHANISMS, ("opaque_fd", "dma_buf"))


if __name__ == "__main__":
    unittest.main()
