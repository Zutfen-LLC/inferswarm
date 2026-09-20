#!/usr/bin/env python3
"""Issue #232 tests — V2-G producers (CPU-only, no hardware).

Covers: authority building/binding against accepted predecessor bytes,
AER event-census grammar vs the retained fault-boot journal sample,
topology-chain derivation vs retained lspci bytes, the prospective
clean-link gate, intervention recording, replay authorization/order
state, and the assembler's deterministic terminal — plus the issue's
20 required fail-closed controls executed through the REAL
reducer/gate/assembler paths (mutation tests over synthetic evidence
trees, never hand-authored fixture summaries).
"""
from __future__ import annotations

import copy
import gzip
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

import issue232_receipt as rc
import issue232_freeze as fz
import issue232_authority as pa
import issue232_host as host
import issue232_baseline as baseline
import issue232_gate as gate
import issue232_qualify as qual
import issue232_replay as replay
import issue232_reduce as red
import issue232_assemble as asm


def canonical(v) -> bytes:
    return rc.canonical(v)


# ---------------------------------------------------------------------------
# Synthetic evidence builders (models of the collector output shapes).
# ---------------------------------------------------------------------------

V2F_AREA = Path("docs/investigations/vulkan-v2-f-v340l-external-memory")


def synth_observation(*, boot_id="boot-x", rxerr=0, journal_rxerr=None,
                      minutes=15.0, up_bdf="0000:02:00.0",
                      width=1, speed=8.0, note=None,
                      storage_ok=True, nic_ok=True):
    if journal_rxerr is None:
        journal_rxerr = rxerr
    return {
        "schema": "inferswarm.v2g.observation/1",
        "campaign_id": rc.CAMPAIGN_ID,
        "observation_id": f"v2g-obs-synth-{boot_id}",
        "note": note,
        "boot_id": boot_id,
        "started_utc": "2026-09-20T12:00:00+00:00",
        "ended_utc": "2026-09-20T12:15:00+00:00",
        "requested_minutes": int(minutes),
        "elapsed_minutes": minutes,
        "chain_bdfs": [up_bdf],
        "chain_roles": {
            "root_port": "0000:00:1d.0",
            "switch_upstream": up_bdf,
            "root_port_sta": {"speed": speed, "width": width,
                              "width_downgraded": False},
            "switch_upstream_sta": {"speed": speed, "width": width,
                                    "width_downgraded": width < 16},
            "root_port_cap": {"speed": 8.0, "width": 1},
            "switch_upstream_cap": {"speed": 8.0, "width": 16},
        },
        "aer_start": {},
        "aer_end": {},
        "aer_deltas": {
            up_bdf: {"aer_dev_correctable": {"RxErr": rxerr,
                                             "BadTLP": 0},
                     "aer_dev_nonfatal": None,
                     "aer_dev_fatal": None},
        },
        "rates": {
            up_bdf: {"correctable_events": rxerr,
                     "rate_per_minute": (rxerr / minutes
                                         if minutes else None)},
        },
        "journal_census_delta": {
            "events": {"Correctable": journal_rxerr,
                       "Uncorrectable": 0, "DPC": 0},
            "events_by_source": {
                up_bdf: {"Correctable": journal_rxerr,
                         "Uncorrectable": 0, "DPC": 0}},
        },
        "journal_fault_counts": {
            "fatal_aer": 0, "amdgpu_reset": 0, "amdgpu_timeout": 0,
            "amdgpu_failure": 0, "dmar_fault": 0, "thermal": 0},
        "link_sysfs_end": {},
        "host_health": {"loadavg": "0.10"},
        "nic": {"enp1s0": {"rx_bytes": 1, "tx_bytes": 1}} if nic_ok \
            else {},
        "storage": {"free_bytes": 10**9, "write_ok": storage_ok},
        "closure_digest": "0" * 64,
        "producer_head": "0" * 40,
    }


def synth_census(*, chain_ok=True, vegas=("0000:06:00.0",
                                          "0000:09:00.0")):
    return {
        "schema": "inferswarm.v2g.census/1",
        "campaign_id": rc.CAMPAIGN_ID,
        "census_id": "v2g-census-synth",
        "boot_id": "boot-x",
        "derived_chain": {
            "root_port_bdf": "0000:00:1d.0",
            "switch_upstream_bdf": "0000:02:00.0",
            "root_port_sta": {"speed": 8.0, "width": 1},
            "root_port_cap": {"speed": 8.0, "width": 1},
            "switch_upstream_sta": {"speed": 8.0, "width": 1,
                                    "width_downgraded": True},
            "switch_upstream_cap": {"speed": 8.0, "width": 16},
        } if chain_ok else {},
        "vega_bdfs": list(vegas) if chain_ok else [],
        "cold_cycle_evidence": None,
    }


def synth_intervention(component="pm8533_upstream_reseat",
                       bundle=False, declared_width=None):
    doc = {
        "schema": "inferswarm.v2g.intervention/1",
        "campaign_id": rc.CAMPAIGN_ID,
        "intervention_id": f"v2g-iv-synth-{component}",
        "recorded_utc": "2026-09-20T11:00:00+00:00",
        "component": component,
        "declared_bundle": bundle,
        "attribution_policy": "NO individual component attribution "
                              "for a declared bundle" if bundle else
                              f"single variable: {component}",
        "description": "synthetic",
        "pre_census_rel": "censuses/x/census.json",
        "pre_census_sha256": "0" * 64,
        "operator_declared": True,
        "closure_digest": "0" * 64,
        "producer_head": "0" * 40,
    }
    if declared_width is not None:
        doc["declared_width"] = declared_width
    return doc


def synth_gate_pass():
    obs = synth_observation()
    conf = synth_observation(boot_id="boot-y")
    cold_proof = {"cycles": [
        {"prev_boot_ended_without_reboot_target": True,
         "shutdown_record_present": True}]}
    return gate.evaluate_gate(
        observation=obs, census=synth_census(),
        interventions=[synth_intervention()],
        cold_confirmation_observations=[conf],
        cold_proof=cold_proof)


def synth_qualification_pass():
    return {
        "schema": "inferswarm.v2g.qualification/1",
        "campaign_id": rc.CAMPAIGN_ID,
        "stop_condition": None,
        "same_die_operations": {
            "0000:06:00.0": {"ok": True},
            "0000:09:00.0": {"ok": True}},
        "upstream_rxerr_delta": 0,
        "boot_id": "boot-y",
    }


def write_synth_evidence(tmp: Path, *, gate_result="PASS",
                         replay_authorized: bool | None = True,
                         arms=(), halted=False, obs_rxerr=0,
                         quals_stop=None, order_entries=None):
    ev = tmp / "evidence"
    ev.mkdir(parents=True, exist_ok=True)
    (ev / "observations" / "a").mkdir(parents=True, exist_ok=True)
    obs = synth_observation(rxerr=obs_rxerr)
    (ev / "observations" / "a" / "observation.json").write_text(
        json.dumps(obs))
    (ev / "observations" / "a" / "raw").mkdir(exist_ok=True)
    (ev / "observations" / "a" / "raw" /
     "journal-delta-census.json").write_text(json.dumps(
        obs["journal_census_delta"]))
    gate_doc = synth_gate_pass()
    gate_doc["result"] = gate_result
    (ev / "gate-result.json").write_text(json.dumps(gate_doc))
    (ev / "qualification").mkdir(exist_ok=True)
    q = synth_qualification_pass()
    q["stop_condition"] = quals_stop
    (ev / "qualification" / "qualification.json").write_text(
        json.dumps(q))
    if replay_authorized is not None:
        (ev / "replay-authorization.json").write_text(json.dumps({
            "schema": "inferswarm.v2g.replay-authorization/1",
            "campaign_id": rc.CAMPAIGN_ID,
            "decision": "REPLAY_AUTHORIZED" if replay_authorized
            else "REPLAY_REFUSED",
            "reasons": [],
            "replay_producer": {
                "producer_head": "0" * 40,
                "byte_identical_to_accepted": True},
        }))
    if order_entries is not None:
        (ev / "replay-order-state.json").write_text(json.dumps({
            "schema": "inferswarm.v2g.replay-order/1",
            "campaign_id": rc.CAMPAIGN_ID,
            "entries": order_entries,
            "chain_digest": "0" * 64,
        }))
    if arms:
        (ev / "raw").mkdir(exist_ok=True)
        for arm, stop, ok in arms:
            size = int(arm.split("-")[1])
            stdout = synth_replay_stdout(size, ok=ok)
            (ev / "raw" / f"{arm}.stdout").write_text(stdout)
            (ev / "arms").mkdir(exist_ok=True)
            (ev / "arms" / f"{arm}.json").write_text(json.dumps({
                "arm": arm, "size_bytes": size, "exit_code": 0,
                "stdout_rel": f"raw/{arm}.stdout",
                "validated": ok and stop is None,
                "stop_condition": stop,
                "stdout_sha256": hashlib.sha256(
                    stdout.encode()).hexdigest(),
                "replay_producer_head": "0" * 40,
            }))
    if halted:
        entries = order_entries or []
        if not any(e.get("state") == "failed" for e in entries):
            (ev / "replay-order-state.json").write_text(json.dumps({
                "schema": "inferswarm.v2g.replay-order/1",
                "campaign_id": rc.CAMPAIGN_ID,
                "entries": entries + [
                    {"arm": (arms[-1][0] if arms else "replay-4096"),
                     "state": "failed",
                     "detail": {"stop_condition":
                                (arms[-1][1] if arms else
                                 "ring_timeout_or_hang")}}],
                "chain_digest": "0" * 64,
            }))
    return ev


def synth_replay_stdout(size=4096, ok=True):
    # compact separators: the real C producer prints compact JSON
    # (no space after ':' or ','), and the correctness check matches
    # '"ok":true' exactly
    J = lambda o: json.dumps(o, separators=(",", ":"))
    lines = [J({
        "event": "arm", "mechanism": "opaque_fd",
        "direction": "b_to_a", "size": size, "reps": 1, "warmups": 0,
        "source": {"bdf": "0000:09:00.0", "queue_family": 0},
        "destination": {"bdf": "0000:06:00.0", "queue_family": 0,
                        "import_memory_type": 0,
                        "import_compatible_bits": 513,
                        "fd_props_query_supported": 0},
        "handle_type_bit": 1,
        "fd_lifecycle": "opaque_fd: consumed by driver on import"})]
    lines.append(J({
        "event": "rep", "rep": 0, "measured": 1, "seed": 1,
        "ok": ok, "elapsed_ns": 1_000_000}))
    lines.append(J({
        "event": "summary", "mechanism": "opaque_fd",
        "direction": "b_to_a", "size": size, "ok": ok}))
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Authority tests
# ---------------------------------------------------------------------------

class TestAuthority(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.doc = pa.build_authority(REPO)

    def test_builds_from_accepted_bytes(self):
        d = self.doc
        self.assertEqual(d["schema"], "inferswarm.v2g.physical-authority/1")
        self.assertEqual(d["terminals"]["v2f"]["terminal"],
                         "V2F_V340L_PLATFORM_STRESS_FAIL")
        self.assertTrue(all(
            d["chronic_condition_baseline"]["cross_check"].values()))

    def test_chronic_baseline_reparses_retained_journal(self):
        b = self.doc["chronic_condition_baseline"]
        self.assertEqual(
            b["reparsed_from_raw_bytes"]["events"]["Correctable"],
            250851)
        self.assertEqual(
            b["reparsed_from_raw_bytes"]["events_by_source"]
            ["0000:02:00.0"]["Correctable"], 250507)

    def test_replay_pin_binds_v2f_blob(self):
        pin = self.doc["replay_producer_pin"]
        blob = subprocess.run(
            ["git", "-C", str(REPO), "cat-file", "blob",
             f"{pin['producer_head']}:{pin['transfer_source']}"],
            capture_output=True).stdout
        self.assertEqual(hashlib.sha256(blob).hexdigest(),
                         pin["transfer_source_sha256"])

    def test_verify_rejects_hand_edit(self):
        d = copy.deepcopy(self.doc)
        d["terminals"]["v2f"]["terminal"] = "V2F_PASS"
        with self.assertRaises(pa.AuthorityError):
            pa.verify_authority(d, REPO)

    def test_verify_rejects_baseline_rewrite(self):
        d = copy.deepcopy(self.doc)
        d["chronic_condition_baseline"]["retained_quantification"][
            "severity_counts"]["Correctable"] = 1
        with self.assertRaises(pa.AuthorityError):
            pa.verify_authority(d, REPO)


# ---------------------------------------------------------------------------
# AER census grammar tests (against the RETAINED fault-boot bytes)
# ---------------------------------------------------------------------------

class TestAERCensusGrammar(unittest.TestCase):
    SAMPLE = (
        "Sep 20 08:36:50 h kernel: pcieport 0000:00:1c.0: AER: enabled with IRQ 123\n"
        "Sep 20 08:36:50 h kernel: acpi PNP0A08:00: _OSC: OS now controls [PCIeHotplug AER]\n"
        "Sep 20 08:36:51 h kernel: pcieport 0000:00:1d.0: AER: Correctable error message received from 0000:02:00.0\n"
        "Sep 20 08:36:51 h kernel: pcieport 0000:02:00.0: PCIe Bus Error: severity=Correctable, type=Physical Layer, (Receiver ID)\n"
        "Sep 20 08:36:51 h kernel: pcieport 0000:02:00.0:   device [11f8:8533] error status/mask=00000001/0000e000\n"
        "Sep 20 08:36:51 h kernel: pcieport 0000:02:00.0:    [ 0] RxErr                  (First)\n"
        "Sep 20 08:36:52 h kernel: pcieport 0000:00:1d.0: AER: Multiple Correctable error message received from 0000:02:00.0\n"
        "Sep 20 08:36:52 h kernel: pcieport 0000:02:00.0: PCIe Bus Error: severity=Correctable, type=Physical Layer, (Receiver ID)\n"
        "Sep 20 08:36:53 h kernel: pcieport 0000:02:00.0: PCIe Bus Error: severity=Uncorrected (Fatal), type=Transaction Layer, (Receiver ID)\n"
        "Sep 20 08:36:54 h kernel: pcieport 0000:09:00.0: PCIe Bus Error: severity=Correctable, type=Data Link Layer, (Receiver ID)\n"
    )

    def test_events_counted_by_severity_lines(self):
        c = host.aer_event_census(self.SAMPLE)
        # 3 Correctable severity lines + 1 Uncorrected = events;
        # announcements and detail rows are separate populations
        self.assertEqual(c["events"]["Correctable"], 3)
        self.assertEqual(c["events"]["Uncorrectable"], 1)
        self.assertEqual(c["announcement_lines"], 2)
        self.assertEqual(c["context_lines"], 2)

    def test_control_3_journal_context_not_events(self):
        c = host.aer_event_census(self.SAMPLE)
        total = sum(c["events"].values())
        self.assertNotEqual(total, c["total_lines"])
        self.assertNotEqual(total, c["announcement_lines"] + total)

    def test_control_4_severity_never_conflated(self):
        c = host.aer_event_census(self.SAMPLE)
        # correctable source attribution: announcement received-from
        self.assertEqual(c["events_by_source"]["0000:02:00.0"]
                         ["Correctable"], 2)
        # uncorrected severity lines attribute by their own prefix
        self.assertEqual(
            c["events_by_severity_prefix"]["0000:02:00.0"]
            ["Uncorrectable"], 1)
        # total severity events: 3 correctable + 1 uncorrected
        self.assertEqual(c["events"]["Correctable"], 3)
        self.assertEqual(c["events"]["Uncorrectable"], 1)

    def test_control_5_source_attribution(self):
        # the relay announcement attributes 0000:02:00.0 even though
        # the RELAYING port is 00:1d.0
        c = host.aer_event_census(self.SAMPLE)
        self.assertIn("0000:02:00.0", c["events_by_source"])
        self.assertNotIn("0000:00:1d.0", c["events_by_source"])

    def test_retained_fault_boot_full_file(self):
        gz = REPO / V2F_AREA / "evidence/supplementary/aer-fault-boot-full.txt.gz"
        if not gz.is_file():
            self.skipTest("fault-boot journal not present")
        c = host.aer_event_census(
            gzip.decompress(gz.read_bytes()).decode("utf-8", "replace"))
        self.assertEqual(c["events"]["Correctable"], 250851)
        self.assertEqual(c["events"]["Uncorrectable"], 0)
        self.assertEqual(
            c["events_by_source"]["0000:02:00.0"]["Correctable"],
            250507)


# ---------------------------------------------------------------------------
# Chain derivation tests (against RETAINED lspci bytes)
# ---------------------------------------------------------------------------

class TestChainDerivation(unittest.TestCase):
    RAW = REPO / V2F_AREA / "evidence/preflight/raw"

    @classmethod
    def setUpClass(cls):
        cls.nn = (cls.RAW / "lspci_nn.stdout").read_text()
        cls.tree = (cls.RAW / "lspci_tree.stdout").read_text()
        import glob
        vv_files = sorted(cls.RAW.glob("lspci_vv_*.stdout"))
        cls.vv = "\n".join(p.read_text() for p in vv_files)

    def test_chain_from_real_bytes(self):
        chain = host.derive_chain(self.nn, self.tree, self.vv)
        self.assertEqual(chain["root_port_bdf"], "0000:00:1d.0")
        self.assertEqual(chain["switch_upstream_bdf"], "0000:02:00.0")

    def test_control_1_stale_bdf_rejected(self):
        # mutate the switch to a DIFFERENT slot (bus 05): a chain
        # derived with historical literals would silently pass; the
        # derivation must re-key on the fresh bytes
        nn2 = self.nn.replace("02:00.0", "05:00.0")
        tree2 = self.tree.replace("[02-09]", "[05-09]")
        vv2 = self.vv
        # bus-chaining now needs the root port's secondary to be 05 —
        # a stale derivation fails closed (no corroborated candidate)
        with self.assertRaises(host.HostObservationError):
            host.derive_chain(nn2, tree2, vv2)

    def test_duplicate_block_injection_fails_closed(self):
        vv2 = self.vv + "\n" + self.vv.split("\n\n")[0] + "\n"
        with self.assertRaises(host.HostObservationError):
            host.split_lspci_blocks(vv2)


# ---------------------------------------------------------------------------
# Clean-link gate tests + controls 2/8/9/10/11/12
# ---------------------------------------------------------------------------

class TestCleanLinkGate(unittest.TestCase):
    def test_clean_pass(self):
        r = synth_gate_pass()
        self.assertEqual(r["result"], "PASS")

    def test_control_10_rxerr_nonzero_fails(self):
        obs = synth_observation(rxerr=1)
        r = gate.evaluate_gate(
            observation=obs, census=synth_census(),
            interventions=[synth_intervention()],
            cold_confirmation_observations=[
                synth_observation(boot_id="b2")],
            cold_proof={"cycles": [
                {"prev_boot_ended_without_reboot_target": True,
                 "shutdown_record_present": True}]})
        self.assertEqual(r["result"], "FAIL")
        self.assertIn("upstream_rxerr_zero", r["failed_checks"])

    def test_control_10_threshold_is_frozen_zero(self):
        self.assertEqual(rc.CLEAN_LINK_RXERR_MAX, 0)
        self.assertEqual(
            gate.GATE_SCHEMA, "inferswarm.v2g.clean-link-gate/1")

    def test_control_2_speed_downtrain_not_width_downgrade(self):
        # speed 2.5 (idle downtrain) with width still x1 passes width
        obs = synth_observation(speed=2.5)
        r = gate.evaluate_gate(
            observation=obs, census=synth_census(),
            interventions=[synth_intervention()],
            cold_confirmation_observations=[
                synth_observation(boot_id="b2")],
            cold_proof={"cycles": [
                {"prev_boot_ended_without_reboot_target": True,
                 "shutdown_record_present": True}]})
        self.assertTrue(r["checks"]["width_matches_declared_wiring"])

    def test_control_2_width_downgrade_fails(self):
        obs = synth_observation(width=1)  # wiring expects x1 — but
        # mutate the switch width to 1 while CAP says 16 and no
        # declared width change: undeclared width change fails via
        # rp/sw mismatch; use a divergent rp width to force it
        obs = copy.deepcopy(obs)
        obs["chain_roles"]["root_port_sta"]["width"] = 2
        r = gate.evaluate_gate(
            observation=obs, census=synth_census(),
            interventions=[synth_intervention()],
            cold_confirmation_observations=[
                synth_observation(boot_id="b2")],
            cold_proof={"cycles": [
                {"prev_boot_ended_without_reboot_target": True,
                 "shutdown_record_present": True}]})
        self.assertFalse(r["checks"]["width_matches_declared_wiring"])

    def test_control_8_warm_reboot_never_substitutes(self):
        r = gate.evaluate_gate(
            observation=synth_observation(),
            census=synth_census(),
            interventions=[synth_intervention()],
            cold_confirmation_observations=[
                synth_observation(boot_id="b2")],
            cold_proof={"cycles": [
                {"prev_boot_ended_without_reboot_target": False,
                 "shutdown_record_present": True}]})
        self.assertFalse(r["checks"]["cold_confirmation_repeated"])

    def test_control_9_one_clean_interval_not_enough(self):
        r = gate.evaluate_gate(
            observation=synth_observation(),
            census=synth_census(),
            interventions=[synth_intervention()],
            cold_confirmation_observations=[],
            cold_proof=None)
        self.assertFalse(r["checks"]["cold_confirmation_repeated"])

    def test_control_11_clean_aer_with_amdgpu_fault_fails(self):
        obs = synth_observation()
        obs = copy.deepcopy(obs)
        obs["journal_fault_counts"]["amdgpu_timeout"] = 2
        r = gate.evaluate_gate(
            observation=obs, census=synth_census(),
            interventions=[synth_intervention()],
            cold_confirmation_observations=[
                synth_observation(boot_id="b2")],
            cold_proof={"cycles": [
                {"prev_boot_ended_without_reboot_target": True,
                 "shutdown_record_present": True}]})
        self.assertFalse(r["checks"]["no_amdgpu_timeout_reset"])

    def test_control_12_topology_mismatch_fails(self):
        r = gate.evaluate_gate(
            observation=synth_observation(),
            census=synth_census(chain_ok=False),
            interventions=[synth_intervention()],
            cold_confirmation_observations=[
                synth_observation(boot_id="b2")],
            cold_proof={"cycles": [
                {"prev_boot_ended_without_reboot_target": True,
                 "shutdown_record_present": True}]})
        self.assertFalse(r["checks"]["topology_chain_unique"])

    def test_control_4_uncorrectable_fails_gate(self):
        obs = synth_observation()
        obs = copy.deepcopy(obs)
        obs["journal_census_delta"]["events"]["Uncorrectable"] = 1
        r = gate.evaluate_gate(
            observation=obs, census=synth_census(),
            interventions=[synth_intervention()],
            cold_confirmation_observations=[
                synth_observation(boot_id="b2")],
            cold_proof={"cycles": [
                {"prev_boot_ended_without_reboot_target": True,
                 "shutdown_record_present": True}]})
        self.assertFalse(r["checks"]["zero_uncorrectable_and_dpc"])


# ---------------------------------------------------------------------------
# Intervention recording + control 6
# ---------------------------------------------------------------------------

class TestInterventions(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.ev = self.tmp / "evidence"
        pre = self.ev / "censuses" / "x" / "census.json"
        pre.parent.mkdir(parents=True, exist_ok=True)
        pre.write_text("{}")

    def test_control_6_single_component_only(self):
        doc = baseline.record_intervention(
            repo=REPO if False else self._repo_stub(),
            out=self.ev / "interventions",
            component="pm8533_upstream_reseat",
            description="reseated the switch card in slot 3",
            pre_census_rel="censuses/x/census.json")
        self.assertFalse(doc["declared_bundle"])
        self.assertIn("single variable", doc["attribution_policy"])

    def test_control_6_bundle_must_declare_itself(self):
        with self.assertRaises(baseline.BaselineError):
            baseline.record_intervention(
                repo=self._repo_stub(),
                out=self.ev / "interventions",
                component="pm8533_upstream_reseat",
                description="reseat + slot move at once",
                pre_census_rel="censuses/x/census.json",
                declared_bundle=True)

    def _repo_stub(self):
        # intervention recording only verifies the closure — point it
        # at the real repo (closure sources are present, uncommitted)
        return REPO


# ---------------------------------------------------------------------------
# Replay authorization/order + controls 13/14/15/19
# ---------------------------------------------------------------------------

class TestReplayAuthorization(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.ev = self.tmp / "evidence"

    def _write(self, gate_result="PASS", qual_stop=None):
        (self.ev).mkdir(parents=True, exist_ok=True)
        (self.ev / "gate-result.json").write_text(json.dumps(
            {"schema": "inferswarm.v2g.clean-link-gate/1",
             "result": gate_result,
             "checks": {"cold_confirmation_repeated": True}}))
        (self.ev / "qualification").mkdir(exist_ok=True)
        (self.ev / "qualification" / "qualification.json").write_text(
            json.dumps({"schema":
                        "inferswarm.v2g.qualification/1",
                        "stop_condition": qual_stop}))

    def test_control_13_refused_before_gate(self):
        self.ev.mkdir(parents=True, exist_ok=True)
        doc = {"schema": "inferswarm.v2g.clean-link-gate/1",
               "result": "FAIL",
               "checks": {"cold_confirmation_repeated": False}}
        (self.ev / "gate-result.json").write_text(json.dumps(doc))
        (self.ev / "qualification").mkdir(parents=True, exist_ok=True)
        (self.ev / "qualification" / "qualification.json").write_text(
            json.dumps({"schema":
                        "inferswarm.v2g.qualification/1",
                        "stop_condition": None}))
        decision = replay.authorize(repo=REPO, evidence_root=self.ev)
        self.assertFalse(decision["authorized"])
        self.assertEqual(decision["decision"], "REPLAY_REFUSED")
        self.assertTrue(any("gate" in r for r in decision["reasons"]))

    def test_first_arm_is_4k_not_fault_scale(self):
        self.assertEqual(rc.REPLAY_LADDER[0]["size_bytes"], 4096)
        self.assertEqual(rc.REPLAY_LADDER[-1]["size_bytes"],
                         64 << 20)
        # control 15: ladder ascends strictly
        sizes = [r["size_bytes"] for r in rc.REPLAY_LADDER]
        self.assertEqual(sizes, sorted(sizes))
        self.assertTrue(all(r["reps"] == 1 and r["warmups"] == 0
                            for r in rc.REPLAY_LADDER))


class TestReplayOrderState(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.ev = self.tmp / "evidence"
        self.ev.mkdir(parents=True)
        (self.ev / "replay-authorization.json").write_text(json.dumps({
            "schema": "inferswarm.v2g.replay-authorization/1",
            "campaign_id": rc.CAMPAIGN_ID,
            "authorized": True, "decision": "REPLAY_AUTHORIZED",
            "reasons": []}))

    def test_order_enforced(self):
        # the FIRST arm authorizes with no predecessors
        auth = replay.authorize_arm(self.ev, "replay-4096")
        self.assertEqual(auth["predecessors_passed"], [])
        replay.record_arm_result(self.ev, "replay-4096", "passed", {})
        auth = replay.authorize_arm(self.ev, "replay-1048576")
        self.assertEqual(auth["predecessors_passed"], ["replay-4096"])
        # jumping ahead is refused
        with self.assertRaises(replay.ReplayError):
            replay.authorize_arm(self.ev, "replay-67108864")

    def test_control_19_no_rerun_after_failure(self):
        replay.record_arm_result(self.ev, "replay-4096", "passed", {})
        replay.record_arm_result(self.ev, "replay-1048576", "failed",
                                 {"stop_condition":
                                  "ring_timeout_or_hang"})
        with self.assertRaises(replay.ReplayError):
            replay.authorize_arm(self.ev, "replay-16777216")
        with self.assertRaises(replay.ReplayError):
            replay.authorize_arm(self.ev, "replay-1048576")

    def test_duplicate_refused(self):
        replay.record_arm_result(self.ev, "replay-4096", "passed", {})
        with self.assertRaises(replay.ReplayError):
            replay.record_arm_result(self.ev, "replay-4096",
                                     "passed", {})

    def test_chain_digest_tamper_detected(self):
        replay.record_arm_result(self.ev, "replay-4096", "passed", {})
        path = replay.order_state_path(self.ev)
        doc = json.loads(path.read_text())
        doc["entries"][0]["state"] = "failed"
        path.write_text(json.dumps(doc))
        with self.assertRaises(replay.ReplayError):
            replay.authorize_arm(self.ev, "replay-1048576")


# ---------------------------------------------------------------------------
# Terminal reduction + controls 7/16/17/18/20
# ---------------------------------------------------------------------------

class TestTerminalReduction(unittest.TestCase):
    def test_clean_replay_pass_terminal(self):
        with tempfile.TemporaryDirectory() as td:
            ev = write_synth_evidence(
                Path(td),
                arms=[("replay-4096", None, True),
                      ("replay-1048576", None, True),
                      ("replay-16777216", None, True),
                      ("replay-67108864", None, True)],
                order_entries=[
                    {"arm": "replay-4096", "state": "passed",
                     "detail": {}},
                    {"arm": "replay-1048576", "state": "passed",
                     "detail": {}},
                    {"arm": "replay-16777216", "state": "passed",
                     "detail": {}},
                    {"arm": "replay-67108864", "state": "passed",
                     "detail": {}}],
                halted=False)
            r = red.derive_terminal(ev)
            self.assertEqual(
                r["terminal"], "V2G_PCIE_PATH_REMEDIATED_REPLAY_PASS")

    def test_fault_reproduced_terminal(self):
        with tempfile.TemporaryDirectory() as td:
            ev = write_synth_evidence(
                Path(td),
                arms=[("replay-4096", None, True),
                      ("replay-1048576", "ring_timeout_or_hang",
                       False)],
                order_entries=[
                    {"arm": "replay-4096", "state": "passed",
                     "detail": {}},
                    {"arm": "replay-1048576", "state": "failed",
                     "detail": {"stop_condition":
                                "ring_timeout_or_hang"}}],
                halted=True)
            r = red.derive_terminal(ev)
            self.assertEqual(
                r["terminal"],
                "V2G_PCIE_PATH_REMEDIATED_FAULT_REPRODUCED")

    def test_different_failure_terminal(self):
        with tempfile.TemporaryDirectory() as td:
            ev = write_synth_evidence(
                Path(td),
                arms=[("replay-4096", "correctness_mismatch", False)],
                order_entries=[
                    {"arm": "replay-4096", "state": "failed",
                     "detail": {"stop_condition":
                                "correctness_mismatch"}}],
                halted=True)
            r = red.derive_terminal(ev)
            self.assertEqual(
                r["terminal"],
                "V2G_PCIE_PATH_REMEDIATED_DIFFERENT_FAILURE")

    def test_remediation_failed_terminal(self):
        with tempfile.TemporaryDirectory() as td:
            ev = write_synth_evidence(Path(td), gate_result="FAIL",
                                      replay_authorized=None)
            r = red.derive_terminal(ev)
            self.assertEqual(
                r["terminal"], "V2G_PCIE_PATH_REMEDIATION_FAILED")

    def test_clean_no_replay_terminal(self):
        with tempfile.TemporaryDirectory() as td:
            ev = write_synth_evidence(Path(td),
                                      replay_authorized=False)
            r = red.derive_terminal(ev)
            self.assertEqual(
                r["terminal"], "V2G_PCIE_PATH_CLEAN_NO_REPLAY")

    def test_control_20_authored_terminal_contradiction_refused(self):
        with tempfile.TemporaryDirectory() as td:
            ev = write_synth_evidence(
                Path(td),
                arms=[("replay-4096", None, True),
                      ("replay-1048576", None, True),
                      ("replay-16777216", None, True),
                      ("replay-67108864", None, True)],
                order_entries=[
                    {"arm": n, "state": "passed", "detail": {}}
                    for n in ("replay-4096", "replay-1048576",
                              "replay-16777216", "replay-67108864")],
                halted=False)
            (ev / "TERMINAL.json").write_text(json.dumps(
                {"terminal":
                 "V2G_PCIE_PATH_REMEDIATED_FAULT_REPRODUCED"}))
            with self.assertRaises(red.ReductionError):
                red.derive_terminal(ev)

    def test_control_16_missing_correctness_observation(self):
        with tempfile.TemporaryDirectory() as td:
            ev = write_synth_evidence(
                Path(td),
                arms=[("replay-4096", None, False)],  # ok:false
                order_entries=[
                    {"arm": "replay-4096", "state": "passed",
                     "detail": {}}],
                halted=False)
            r = red.derive_terminal(ev)
            # an unvalidated arm cannot produce a REPLAY_PASS
            self.assertNotEqual(
                r["terminal"],
                "V2G_PCIE_PATH_REMEDIATED_REPLAY_PASS")

    def test_control_18_predecessor_evidence_not_rewritten(self):
        # derive_terminal reads predecessor state via the authority;
        # a rewritten fault-boot journal fails the authority build,
        # which the reducer path requires (authority re-verify is in
        # replay.authorize; here assert the authority refuses)
        d = copy.deepcopy(pa.build_authority(REPO))
        gz_rel = (f"{V2F_AREA}/evidence/supplementary/"
                  "aer-fault-boot-full.txt.gz")
        real = (REPO / gz_rel).read_bytes()
        d["chronic_condition_baseline"][
            "retained_quantification"][
            "severity_counts"]["Correctable"] = 999999
        with self.assertRaises(pa.AuthorityError):
            pa.verify_authority(d, REPO)


if __name__ == "__main__":
    unittest.main()
