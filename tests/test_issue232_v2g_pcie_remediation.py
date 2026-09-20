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
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
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
                                          "0000:09:00.0"),
                 boot_id="boot-x", root_port="0000:00:1d.0",
                 upstream="0000:02:00.0"):
    return {
        "schema": "inferswarm.v2g.census/1",
        "campaign_id": rc.CAMPAIGN_ID,
        "census_id": "v2g-census-synth",
        "boot_id": boot_id,
        "derived_chain": {
            "root_port_bdf": root_port,
            "switch_upstream_bdf": upstream,
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


def synth_qualification_pass(*, root_port="0000:00:1d.0",
                             upstream="0000:02:00.0"):
    return {
        "schema": "inferswarm.v2g.qualification/1",
        "campaign_id": rc.CAMPAIGN_ID,
        "stop_condition": None,
        "same_die_operations": {
            "0000:06:00.0": {"ok": True},
            "0000:09:00.0": {"ok": True}},
        "upstream_rxerr_delta": 0,
        "boot_id": "boot-y",
        "chain": {
            "root_port_bdf": root_port,
            "switch_upstream_bdf": upstream,
        },
    }


ROOT_A = "0000:00:1d.0"
ROOT_B = "0000:00:1c.5"
UPSTREAM = "0000:02:00.0"


def synth_boot_proof(*, root_port=ROOT_A, upstream=UPSTREAM,
                     replay_boot_id="boot-y"):
    return {
        "schema": "inferswarm.v2g.boot-proof/1",
        "campaign_id": rc.CAMPAIGN_ID,
        "replay_boot_id": replay_boot_id,
        "topology": {
            "root_port": root_port,
            "switch_upstream": upstream,
            "negotiated_width": 1,
        },
        "continuity": {"anchor_census_boot_id": replay_boot_id},
    }


def write_synth_evidence(tmp: Path, *, gate_result="PASS",
                         replay_authorized: bool | None = True,
                         arms=(), halted=False, obs_rxerr=0,
                         quals_stop=None, order_entries=None,
                         qual_root=ROOT_A,
                         arm_root=ROOT_A, arm_upstream=UPSTREAM,
                         arm_roots=None,
                         gate_root=ROOT_A, gate_upstream=UPSTREAM,
                         cold_proof_root=ROOT_A,
                         boot_proof_root=ROOT_A,
                         write_boot_proof=True,
                         authz_binding_root=ROOT_A,
                         authz_decision_utc="2026-09-20T12:00:00+00:00",
                         order_entry_utc=None,
                         authz_gate_digest=None,
                         superseded_gate_digests=(),
                         arm_producer_head="0" * 40,
                         arm_closure_digest="0" * 64,
                         closure_producer_head="0" * 40,
                         closure_closure_digest="0" * 64,
                         amendments=None):
    """Synthetic evidence root shaped like the real V2-G evidence.

    Defaults model a VALID prospective replay: the authorization
    decision (12:00) mechanically precedes every arm (12:01+), the
    authorization pins the retained gate-result digest, and every arm
    carries the CURRENT closure identity. Every authority defect the
    2026-09-20 correction closes is expressed by overriding one
    parameter.
    """
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
    gate_doc.setdefault("detail", {})["chain"] = {
        "root_port": gate_root,
        "switch_upstream": gate_upstream,
        "census_boot_id": "boot-x",
        "observation_boot_id": "boot-x",
        "cold_confirmation_boot_ids": ["boot-y"],
        "cold_confirmation_root_ports": [cold_proof_root],
    }
    gate_bytes = json.dumps(gate_doc).encode()
    (ev / "gate-result.json").write_bytes(gate_bytes)
    if authz_gate_digest is None:
        authz_gate_digest = hashlib.sha256(gate_bytes).hexdigest()
    (ev / "qualification").mkdir(exist_ok=True)
    q = synth_qualification_pass(root_port=qual_root)
    q["stop_condition"] = quals_stop
    (ev / "qualification" / "qualification.json").write_text(
        json.dumps(q))
    if write_boot_proof:
        (ev / "boot-proof.json").write_text(json.dumps(
            synth_boot_proof(root_port=boot_proof_root)))
    if superseded_gate_digests:
        sup = ev / "superseded-20260920-topology-rebinding"
        sup.mkdir(parents=True, exist_ok=True)
        for d in superseded_gate_digests:
            (sup / "replay-authorization.json").write_text(json.dumps({
                "schema": "inferswarm.v2g.replay-authorization/1",
                "gate_result_digest": d,
                "decision_utc": "2026-09-20T11:00:00+00:00",
            }))
    if replay_authorized is not None:
        (ev / "replay-authorization.json").write_text(json.dumps({
            "schema": "inferswarm.v2g.replay-authorization/1",
            "campaign_id": rc.CAMPAIGN_ID,
            "authorized": replay_authorized,
            "decision": "REPLAY_AUTHORIZED" if replay_authorized
            else "REPLAY_REFUSED",
            "decision_utc": authz_decision_utc,
            "gate_result_digest": authz_gate_digest,
            "reasons": [],
            "replay_boot_id": "boot-y",
            "topology_binding": {
                "gate_root_port": authz_binding_root,
                "gate_switch_upstream": UPSTREAM,
                **({"boot_proof": {
                    "replay_boot_id": "boot-y",
                    "root_port": boot_proof_root,
                    "switch_upstream": UPSTREAM,
                    "negotiated_width": 1,
                }} if write_boot_proof else {}),
            },
            "replay_producer": {
                "producer_head": "0" * 40,
                "byte_identical_to_accepted": True},
        }))
    if order_entries is not None:
        if order_entry_utc is None:
            first = datetime.fromisoformat("2026-09-20T12:01:00+00:00")
            order_entry_utc = [
                (first + timedelta(minutes=i)).isoformat()
                for i in range(len(order_entries))]
        entries = []
        for e, utc in zip(order_entries, order_entry_utc):
            e = dict(e)
            e.setdefault("recorded_utc", utc)
            entries.append(e)
        order_doc = {
            "schema": "inferswarm.v2g.replay-order/1",
            "campaign_id": rc.CAMPAIGN_ID,
            "entries": entries,
        }
        order_doc["chain_digest"] = replay._chain(order_doc)
        (ev / "replay-order-state.json").write_text(json.dumps(order_doc))
    if arms:
        (ev / "raw").mkdir(exist_ok=True)
        for idx, (arm, stop, ok) in enumerate(arms):
            size = int(arm.split("-")[1])
            stdout = synth_replay_stdout(size, ok=ok)
            (ev / "raw" / f"{arm}.stdout").write_text(stdout)
            (ev / "arms").mkdir(exist_ok=True)
            if arm_roots is not None:
                a_root, a_up = arm_roots[idx]
            else:
                a_root, a_up = arm_root, arm_upstream
            (ev / "arms" / f"{arm}.json").write_text(json.dumps({
                "arm": arm, "size_bytes": size, "exit_code": 0,
                "boot_id": "boot-y",
                "stdout_rel": f"raw/{arm}.stdout",
                "validated": ok and stop is None,
                "stop_condition": stop,
                "root_port_bdf": a_root,
                "upstream_bdf": a_up,
                "negotiated_width": 1,
                "stdout_sha256": hashlib.sha256(
                    stdout.encode()).hexdigest(),
                "replay_producer_head": "0" * 40,
                "producer_head": arm_producer_head,
                "closure_digest": arm_closure_digest,
            }))
    if halted:
        entries = order_entries or []
        if not any(e.get("state") == "failed" for e in entries):
            order_doc = {
                "schema": "inferswarm.v2g.replay-order/1",
                "campaign_id": rc.CAMPAIGN_ID,
                "entries": entries + [
                    {"arm": (arms[-1][0] if arms else "replay-4096"),
                     "state": "failed",
                     "recorded_utc": "2026-09-20T12:05:00+00:00",
                     "detail": {"stop_condition":
                                (arms[-1][1] if arms else
                                 "ring_timeout_or_hang")}}],
            }
            order_doc["chain_digest"] = replay._chain(order_doc)
            (ev / "replay-order-state.json").write_text(json.dumps(order_doc))
    if amendments is not None:
        (tmp / "AMENDMENTS.json").write_text(json.dumps(amendments))
    # committed closure view next to the evidence root (the reducer's
    # standalone fallback reads exactly this path)
    (tmp / "PRODUCER-CLOSURE.json").write_text(json.dumps({
        "schema": "inferswarm.v2g.producer-closure/1",
        "campaign_id": rc.CAMPAIGN_ID,
        "producer_head": closure_producer_head,
        "closure_digest": closure_closure_digest,
        "sources": {},
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

def _write_closure_tmp(td, *, with_authority: bool = False) -> Path:
    """Mini repo whose closure source set matches CLOSURE_SOURCES
    byte-for-byte at its HEAD, so verify_closure passes there.
    With ``with_authority``, also builds the V2-G PHYSICAL-AUTHORITY
    (needs the V2-F predecessor bytes, resolved from the real repo
    via AREA overrides)."""
    repo = Path(td) / "minirepo"
    repo.mkdir(parents=True, exist_ok=True)
    def _g(*args: str) -> None:
        subprocess.run(["git", "-C", str(repo), *args], check=True,
                       capture_output=True)
    if not with_authority:
        _g("init", "-q")
        _g("config", "user.email", "t@example.com")
        _g("config", "user.name", "t")
    else:
        # graft: fetch the real history first, then branch from the
        # V2-F merge commit (the authority builder requires it to be
        # an ancestor of HEAD). DEPTH-1 fetch: only that commit's
        # tree is needed (the builder's ancestor check is satisfied
        # by the commit being HEAD's parent), and a full-history
        # fetch is ~1.3 GB per test class.
        _g("init", "-q", "--initial-branch", "work")
        _g("config", "user.email", "t@example.com")
        _g("config", "user.name", "t")
        _g("remote", "add", "real", str(REPO))
        # depth-2: the tree of the V2-F merge commit PLUS its parent
        # history enough for the builder's blob read of the pinned
        # replay producer commit 30cf6996 (a depth-1 graft cannot
        # serve unrelated pinned blobs); still far smaller than a
        # full-history fetch
        _g("fetch", "--depth=5", "-q", "real",
           "c21840e4a1e5b5c81c366dd23b18ff582f9670b1",
           "30cf699688aa3d718fb475f5390317ebb4ba7385")
        _g("fetch", "--depth=1", "-q", "real",
           "30cf699688aa3d718fb475f5390317ebb4ba7385")
        _g("checkout", "-q", "-B", "work",
           "c21840e4a1e5b5c81c366dd23b18ff582f9670b1")
    for rel in rc.CLOSURE_SOURCES:
        dst = repo / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO / rel, dst)
    if with_authority:
        # the authority builder reads V2-F (and earlier) predecessor
        # bytes via repo-relative paths — the checked-out predecessor
        # tree already contains ALL of those, so NO symlinking is
        # needed or allowed: a symlinked V2-G area would redirect the
        # closure/authority writes below INTO THE REAL REPO.
        pass
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "closure"],
                   check=True)
    # write the closure INTO THE MINI REPO explicitly — fz.write_
    # closure() defaults to rc.ROOT (the REAL repo) and would clobber
    # the live closure document mid-test
    doc = fz.closure_document(repo)
    closure_path = repo / rc.AREA_REL / rc.CLOSURE_NAME
    closure_path.parent.mkdir(parents=True, exist_ok=True)
    closure_path.write_bytes(json.dumps(doc, indent=1,
                                        sort_keys=True).encode()
                             + b"\n")
    if with_authority:
        doc = pa.build_authority(repo)
        out = repo / rc.AREA_REL / "PHYSICAL-AUTHORITY.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(json.dumps(doc, indent=1,
                                   sort_keys=True).encode()
                        + b"\n")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-qm", "closure2",
         "--allow-empty"], check=True)  # authority bytes are ignored
    return repo


class TestClosureSourceCompleteness(unittest.TestCase):
    """The closure must pin every correctness-bearing producer —
    including bootproof/coldproof, whose outputs feed replay
    authorization and terminal reduction (authority correction
    2026-09-20)."""

    def test_bootproof_and_coldproof_in_closure_sources(self):
        self.assertIn("scripts/issue232_bootproof.py",
                      rc.CLOSURE_SOURCES)
        self.assertIn("scripts/issue232_coldproof.py",
                      rc.CLOSURE_SOURCES)

    def test_bootproof_and_coldproof_are_physical_producers(self):
        self.assertIn("scripts/issue232_bootproof.py",
                      fz.PHYSICAL_PRODUCERS)
        self.assertIn("scripts/issue232_coldproof.py",
                      fz.PHYSICAL_PRODUCERS)

    def test_closure_source_set_is_exactly_the_known_producers(self):
        expected = {
            "scripts/issue232_receipt.py",
            "scripts/issue232_freeze.py",
            "scripts/issue232_authority.py",
            "scripts/issue232_host.py",
            "scripts/issue232_baseline.py",
            "scripts/issue232_gate.py",
            "scripts/issue232_qualify.py",
            "scripts/issue232_replay.py",
            "scripts/issue232_reduce.py",
            "scripts/issue232_assemble.py",
            "scripts/issue232_manifest.py",
            "scripts/issue232_bootproof.py",
            "scripts/issue232_coldproof.py",
        }
        self.assertEqual(set(rc.CLOSURE_SOURCES), expected)

    def test_closure_rejects_missing_bootproof_from_set(self):
        # a committed closure whose source set OMITS bootproof must
        # fail verification (control: helper omitted from closure
        # authority => fail closed)
        with tempfile.TemporaryDirectory() as td:
            repo = _write_closure_tmp(td)
            committed = json.loads(
                (repo / "docs/investigations"
                 / "vulkan-v2-g-pcie-path-remediation"
                 / "PRODUCER-CLOSURE.json").read_text())
            dropped = dict(committed)
            dropped["sources"] = {
                k: v for k, v in committed["sources"].items()
                if k != "scripts/issue232_bootproof.py"}
            with self.assertRaises(fz.FreezeError):
                fz.verify_closure(repo, committed=dropped)


class TestProspectiveAuthorization(unittest.TestCase):
    """The replay authorization must mechanically PREDATE the first
    executed arm and bind the retained gate digest — a corrected
    authorization created after replay is retrospective and can never
    authorize the retained arms (authority correction 2026-09-20)."""

    ARMS4 = [("replay-4096", None, True),
             ("replay-1048576", None, True),
             ("replay-16777216", None, True),
             ("replay-67108864", None, True)]
    ORDER4 = [{"arm": f"replay-{s}", "state": "passed",
               "detail": {}} for s in (4096, 1048576, 16777216,
                                      67108864)]

    # --- literal regression: the exact retained #232 defect --------
    RETAINED_AUTHZ_UTC = "2026-09-20T16:57:20.265606+00:00"
    RETAINED_ARM_UTC = [
        "2026-09-20T15:14:05.182250+00:00",
        "2026-09-20T15:14:12.449888+00:00",
        "2026-09-20T15:14:14.749495+00:00",
        "2026-09-20T15:14:24.736884+00:00",
    ]
    RETAINED_SUPERSEDED_GATE_DIGEST = (
        "c90bc7f173d0ac5d154d4c98bd1ff0779dcf036f"
        "6a52761d472f784c125013e3")

    def _reduce(self, **kw):
        with tempfile.TemporaryDirectory() as td:
            ev = write_synth_evidence(Path(td),
                                      arms=self.ARMS4,
                                      order_entries=self.ORDER4,
                                      **kw)
            return red.derive_terminal(ev)

    def test_missing_authorization_with_arms_blocks(self):
        r = self._reduce(replay_authorized=None)
        self.assertEqual(r["terminal"], "V2G_EVIDENCE_BLOCKED")

    def test_missing_authorization_with_executed_order_blocks(self):
        with tempfile.TemporaryDirectory() as td:
            ev = write_synth_evidence(
                Path(td), replay_authorized=None,
                order_entries=self.ORDER4)
            r = red.derive_terminal(ev)
            self.assertEqual(r["terminal"], "V2G_EVIDENCE_BLOCKED")

    def test_refused_authorization_with_arms_blocks(self):
        r = self._reduce(replay_authorized=False)
        self.assertEqual(r["terminal"], "V2G_EVIDENCE_BLOCKED")

    def test_equal_authorization_timestamp_blocks(self):
        r = self._reduce(
            authz_decision_utc="2026-09-20T12:01:00+00:00")
        self.assertEqual(r["terminal"], "V2G_EVIDENCE_BLOCKED")

    def test_one_microsecond_before_first_arm_is_prospective(self):
        r = self._reduce(
            authz_decision_utc="2026-09-20T12:00:59.999999+00:00")
        self.assertEqual(r["terminal"],
                         "V2G_PCIE_PATH_REMEDIATED_REPLAY_PASS")

    def test_missing_authorization_without_execution_is_clean(self):
        with tempfile.TemporaryDirectory() as td:
            ev = write_synth_evidence(Path(td), replay_authorized=None)
            self.assertEqual(red.derive_terminal(ev)["terminal"],
                             "V2G_PCIE_PATH_CLEAN_NO_REPLAY")

    def test_refused_authorization_without_execution_is_clean(self):
        with tempfile.TemporaryDirectory() as td:
            ev = write_synth_evidence(Path(td), replay_authorized=False)
            self.assertEqual(red.derive_terminal(ev)["terminal"],
                             "V2G_PCIE_PATH_CLEAN_NO_REPLAY")

    def test_order_state_integrity_controls(self):
        mutations = (
            ("stale digest", lambda d: d["entries"][0].update(
                recorded_utc="2026-09-20T11:01:00+00:00"), False),
            ("missing digest", lambda d: d.pop("chain_digest"), False),
            ("bad schema", lambda d: d.update(schema="wrong"), True),
            ("bad campaign", lambda d: d.update(campaign_id="wrong"), True),
            ("reordered ladder", lambda d: d["entries"].reverse(), True),
            ("nonmonotonic time", lambda d: d["entries"][1].update(
                recorded_utc=d["entries"][0]["recorded_utc"]), True),
        )
        for name, mutate, rechain in mutations:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as td:
                ev = write_synth_evidence(
                    Path(td), arms=self.ARMS4, order_entries=self.ORDER4)
                path = ev / "replay-order-state.json"
                doc = json.loads(path.read_text())
                mutate(doc)
                if rechain:
                    doc["chain_digest"] = replay._chain(doc)
                path.write_text(json.dumps(doc))
                with self.assertRaises(red.ReductionError):
                    red.derive_terminal(ev)

    def test_control_authz_after_first_arm_blocks(self):
        r = self._reduce(
            authz_decision_utc="2026-09-20T12:02:30+00:00",
            order_entry_utc=[
                "2026-09-20T12:01:00+00:00",
                "2026-09-20T12:03:00+00:00",
                "2026-09-20T12:04:00+00:00",
                "2026-09-20T12:05:00+00:00"])
        self.assertEqual(r["terminal"], "V2G_EVIDENCE_BLOCKED")
        self.assertTrue(any("AFTER the first retained arm" in b
                            for b in r["basis"]))

    def test_control_authz_after_last_arm_blocks(self):
        r = self._reduce(
            authz_decision_utc="2026-09-20T12:09:00+00:00")
        self.assertEqual(r["terminal"], "V2G_EVIDENCE_BLOCKED")
        self.assertTrue(any("AFTER the last retained arm" in b
                            for b in r["basis"]))

    def test_control_retained_literal_timestamps_block(self):
        # the EXACT retained timestamps of the #232 defect: corrected
        # authorization 16:57:20 vs arms 15:14:05..15:14:24 — this
        # defect can never silently recur.
        r = self._reduce(
            authz_decision_utc=self.RETAINED_AUTHZ_UTC,
            order_entry_utc=self.RETAINED_ARM_UTC)
        self.assertEqual(r["terminal"], "V2G_EVIDENCE_BLOCKED")
        self.assertTrue(any(
            "16:57:20.265606" in b and "AFTER" in b
            for b in r["basis"]))

    def test_control_prospective_authz_stale_gate_digest_blocks(self):
        # prospective timestamp BUT pins the superseded root-A gate
        # digest while the retained gate/arms are root-B
        r = self._reduce(
            authz_decision_utc="2026-09-20T11:59:00+00:00",
            authz_gate_digest=self.RETAINED_SUPERSEDED_GATE_DIGEST,
            superseded_gate_digests=[
                self.RETAINED_SUPERSEDED_GATE_DIGEST])
        self.assertEqual(r["terminal"], "V2G_EVIDENCE_BLOCKED")
        self.assertTrue(any("SUPERSEDED gate" in b
                            for b in r["basis"]))

    def test_control_authz_unknown_gate_digest_blocks(self):
        r = self._reduce(
            authz_decision_utc="2026-09-20T11:59:00+00:00",
            authz_gate_digest="f" * 64)
        self.assertEqual(r["terminal"], "V2G_EVIDENCE_BLOCKED")
        self.assertTrue(any(
            "does not match the retained gate-result.json" in b
            for b in r["basis"]))

    def test_control_posthoc_bootproof_agreement_does_not_heal(self):
        # a boot proof that AGREES with the arms (default ROOT_A) is
        # post-campaign evidence: it cannot make a retrospective
        # authorization prospective (control 4).
        r = self._reduce(
            authz_decision_utc="2026-09-20T12:09:00+00:00",
            boot_proof_root=ROOT_A)
        self.assertEqual(r["terminal"], "V2G_EVIDENCE_BLOCKED")
        self.assertTrue(any("AFTER the last retained arm" in b
                            for b in r["basis"]))

    def test_control_missing_arm_timestamps_block(self):
        with tempfile.TemporaryDirectory() as td:
            ev = write_synth_evidence(
                Path(td), arms=self.ARMS4,
                order_entries=self.ORDER4)
            doc = json.loads(
                (ev / "replay-order-state.json").read_text())
            for e in doc["entries"]:
                e.pop("recorded_utc", None)
            doc["chain_digest"] = replay._chain(doc)
            (ev / "replay-order-state.json").write_text(
                json.dumps(doc))
            with self.assertRaisesRegex(red.ReductionError,
                                        "not a UTC timestamp"):
                red.derive_terminal(ev)

    def test_positive_prospective_authz_reaches_replay_pass(self):
        r = self._reduce()  # defaults: valid gate + authz precede arms
        self.assertEqual(r["terminal"],
                         "V2G_PCIE_PATH_REMEDIATED_REPLAY_PASS")


class TestRetainedArmProvenance(unittest.TestCase):
    """Retained arms carry their EXECUTING producer identity. Arms
    produced under a historical (different) closure cannot pass
    through the current closure without an explicit immutable
    historical-closure amendment (authority correction 2026-09-20)."""

    ARMS4 = TestProspectiveAuthorization.ARMS4
    ORDER4 = TestProspectiveAuthorization.ORDER4

    HIST_HEAD = "5" * 40
    HIST_DIGEST = "7" * 64

    def _reduce(self, **kw):
        with tempfile.TemporaryDirectory() as td:
            ev = write_synth_evidence(
                Path(td), arms=self.ARMS4,
                order_entries=self.ORDER4, **kw)
            return red.derive_terminal(ev)

    def test_control_historical_closure_digest_blocks(self):
        r = self._reduce(arm_producer_head=self.HIST_HEAD,
                         arm_closure_digest=self.HIST_DIGEST)
        self.assertEqual(r["terminal"], "V2G_EVIDENCE_BLOCKED")
        self.assertTrue(any(
            "no admissible immutable historical-closure amendment"
            in b for b in r["basis"]))

    def test_control_historical_producer_head_blocks(self):
        r = self._reduce(arm_producer_head=self.HIST_HEAD)
        self.assertEqual(r["terminal"], "V2G_EVIDENCE_BLOCKED")
        self.assertTrue(any(
            "no admissible immutable historical-closure amendment"
            in b for b in r["basis"]))

    def test_control_unpinned_arm_identity_blocks(self):
        with tempfile.TemporaryDirectory() as td:
            ev = write_synth_evidence(
                Path(td), arms=self.ARMS4,
                order_entries=self.ORDER4)
            for p in sorted((ev / "arms").glob("replay-*.json")):
                doc = json.loads(p.read_text())
                doc["producer_head"] = None
                p.write_text(json.dumps(doc))
            r = red.derive_terminal(ev)
            self.assertEqual(r["terminal"], "V2G_EVIDENCE_BLOCKED")
            self.assertTrue(any(
                "retains no producer_head" in b for b in r["basis"]))

    def test_control_changed_physical_producer_not_reduction_only(
            self):
        # issue232_replay.py is classified PHYSICAL_PRODUCER: a
        # reduction-only amendment across a changed replay producer
        # is structurally refused by accepted_amended_digests (its
        # physical-producer diff check raises), and the reducer
        # treats ANY refusal as no-admission.
        from issue232_freeze import PHYSICAL_PRODUCERS
        self.assertIn("scripts/issue232_replay.py",
                      PHYSICAL_PRODUCERS)
        # even a WELL-FORMED amendment cannot admit arms whose
        # historical pin is not the amendment's pin: the pin-match
        # rejection fires even when the admission map is populated
        problems = red._historical_provenance_problems(
            [{"arm": "replay-4096", "producer_head": self.HIST_HEAD,
              "closure_digest": self.HIST_DIGEST}],
            {"producer_head": "0" * 40,
             "closure_digest": "0" * 64},
            {self.HIST_DIGEST: {"evidence_producer_head":
                                "9" * 40,
                                "closure_producer_head": "9" * 40}})
        self.assertTrue(any("historical pin" in p for p in problems))

    def test_positive_current_identity_reaches_replay_pass(self):
        r = self._reduce()  # arms carry the current closure identity
        self.assertEqual(r["terminal"],
                         "V2G_PCIE_PATH_REMEDIATED_REPLAY_PASS")


class TestHistoricalAmendmentAssembler(unittest.TestCase):
    @staticmethod
    def _mark_final_arm_failed(ev: Path):
        name = "replay-67108864"
        arm_path = ev / "arms" / f"{name}.json"
        arm = json.loads(arm_path.read_text())
        arm["stop_condition"] = "ring_timeout_or_hang"
        arm["validated"] = False
        arm_path.write_text(json.dumps(arm))
        order_path = ev / "replay-order-state.json"
        order = json.loads(order_path.read_text())
        order["entries"][-1]["state"] = "failed"
        order["entries"][-1]["detail"]["stop_condition"] = \
            "ring_timeout_or_hang"
        order["chain_digest"] = replay._chain(order)
        order_path.write_text(json.dumps(order))

    def _fixture(self, tmp: Path) -> tuple[Path, Path, str]:
        repo = _write_closure_tmp(tmp)
        area = repo / rc.AREA_REL
        historical = json.loads((area / rc.CLOSURE_NAME).read_text())
        historical_pin = subprocess.check_output(
            ["git", "-C", str(repo), "rev-parse", "HEAD"], text=True
        ).strip()
        current = fz.closure_document(repo)
        (area / rc.CLOSURE_NAME).write_text(json.dumps(current))
        subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-qm",
                        "new closure"], check=True)
        (area / "AMENDMENTS.json").write_text(json.dumps({
            "schema": fz.AMENDMENT_SCHEMA,
            "amendments": [{
                "evidence_producer_head": historical_pin,
                "evidence_closure_digest": historical["closure_digest"],
                "evidence_producer_closure_pins": historical["producer_head"],
            }],
        }))
        ev = write_synth_evidence(
            tmp / "synthetic", arms=TestProspectiveAuthorization.ARMS4,
            order_entries=TestProspectiveAuthorization.ORDER4,
            arm_producer_head=historical["producer_head"],
            arm_closure_digest=historical["closure_digest"])
        target = area / "evidence"
        shutil.copytree(ev, target)
        return repo, target, historical_pin

    def test_admitted_historical_closure_reaches_real_assembler(self):
        with tempfile.TemporaryDirectory() as td:
            repo, ev, _ = self._fixture(Path(td))
            result = asm.assemble(repo=repo, evidence_root=ev)
            self.assertEqual(result["reduction"]["terminal"],
                             "V2G_PCIE_PATH_REMEDIATED_REPLAY_PASS")

    def test_admitted_historical_failure_reaches_real_assembler(self):
        with tempfile.TemporaryDirectory() as td:
            repo, ev, _ = self._fixture(Path(td))
            self._mark_final_arm_failed(ev)
            result = asm.assemble(repo=repo, evidence_root=ev)
            self.assertEqual(
                result["reduction"]["terminal"],
                "V2G_PCIE_PATH_REMEDIATED_FAULT_REPRODUCED")

    def test_historical_failure_without_amendment_blocks_real_assembler(self):
        with tempfile.TemporaryDirectory() as td:
            repo, ev, _ = self._fixture(Path(td))
            self._mark_final_arm_failed(ev)
            (repo / rc.AREA_REL / "AMENDMENTS.json").unlink()
            result = asm.assemble(repo=repo, evidence_root=ev)
            self.assertEqual(result["reduction"]["terminal"],
                             "V2G_EVIDENCE_BLOCKED")

    def test_changed_physical_producer_rejected_by_real_assembler(self):
        with tempfile.TemporaryDirectory() as td:
            repo, ev, _ = self._fixture(Path(td))
            producer = repo / "scripts/issue232_replay.py"
            producer.write_bytes(producer.read_bytes() + b"\n# changed\n")
            subprocess.run(["git", "-C", str(repo), "add", "-A"],
                           check=True)
            subprocess.run(["git", "-C", str(repo), "commit", "-qm",
                            "changed physical producer"], check=True)
            current = fz.closure_document(repo)
            (repo / rc.AREA_REL / rc.CLOSURE_NAME).write_text(
                json.dumps(current))
            subprocess.run(["git", "-C", str(repo), "add", "-A"],
                           check=True)
            subprocess.run(["git", "-C", str(repo), "commit", "-qm",
                            "new changed closure"], check=True)
            with self.assertRaisesRegex(fz.FreezeError,
                                        "physical producers changed"):
                asm.assemble(repo=repo, evidence_root=ev)

    def test_malformed_amendment_rejected_by_real_assembler(self):
        with tempfile.TemporaryDirectory() as td:
            repo, ev, _ = self._fixture(Path(td))
            amendment = repo / rc.AREA_REL / "AMENDMENTS.json"
            doc = json.loads(amendment.read_text())
            doc["schema"] = "wrong"
            amendment.write_text(json.dumps(doc))
            with self.assertRaisesRegex(fz.FreezeError,
                                        "amendment record schema mismatch"):
                asm.assemble(repo=repo, evidence_root=ev)


class TestRetainedEvidenceRegression(unittest.TestCase):
    """The REAL retained #232 evidence must reduce to
    V2G_EVIDENCE_BLOCKED under the corrected invariants (the arms ran
    15:14, the corrected authorization is 16:57, and the arms carry
    the historical 52a65b19/7a5505af identity)."""

    def test_retained_evidence_reduces_to_evidence_blocked(self):
        r = red.derive_terminal(
            REPO / "docs/investigations"
            / "vulkan-v2-g-pcie-path-remediation" / "evidence")
        self.assertEqual(r["terminal"], "V2G_EVIDENCE_BLOCKED")
        joined = " | ".join(r["basis"])
        self.assertIn("0000:00:1d.0", joined)
        self.assertIn("16:57:20.265606", joined)
        self.assertIn("6176s AFTER the last retained arm", joined)
        self.assertIn("52a65b19e736", joined)
        self.assertIn("7a5505af200c", joined)


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
    @classmethod
    def setUpClass(cls):
        # producers must verify their closure before emitting; this
        # round edits producers, so the closure is pinned at a
        # throwaway head committed with exactly CLOSURE_SOURCES (the
        # committed closure in this worktree is mid-correction and
        # legitimately refuses until re-frozen)
        cls.repo = _write_closure_tmp(
            Path(tempfile.mkdtemp()))

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.ev = self.tmp / "evidence"
        pre = self.ev / "censuses" / "x" / "census.json"
        pre.parent.mkdir(parents=True, exist_ok=True)
        pre.write_text("{}")

    def test_control_6_single_component_only(self):
        doc = baseline.record_intervention(
            repo=TestInterventions.repo,
            out=self.ev / "interventions",
            component="pm8533_upstream_reseat",
            description="reseated the switch card in slot 3",
            pre_census_rel="censuses/x/census.json")
        self.assertFalse(doc["declared_bundle"])
        self.assertIn("single variable", doc["attribution_policy"])

    def test_control_6_bundle_must_declare_itself(self):
        with self.assertRaises(baseline.BaselineError):
            baseline.record_intervention(
                repo=TestInterventions.repo,
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
    @classmethod
    def setUpClass(cls):
        # authorize() verifies the closure + re-verifies the physical
        # authority before deciding; pin both at a throwaway
        # committed head (this round edits producers, so the live
        # committed closure mid-correction correctly refuses)
        cls.repo = _write_closure_tmp(
            Path(tempfile.mkdtemp()), with_authority=True)

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
        decision = replay.authorize(
            repo=TestReplayAuthorization.repo,
            evidence_root=self.ev)
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


# ---------------------------------------------------------------------------
# Replay execution authority and arm/order cross-binding
# ---------------------------------------------------------------------------

class TestReplayExecutionBinding(unittest.TestCase):
    """Each replay terminal requires one ordered arm and valid authority."""

    PASS_ARMS = TestProspectiveAuthorization.ARMS4
    PASS_ORDER = TestProspectiveAuthorization.ORDER4
    FAIL_ARMS = [("replay-4096", None, True),
                 ("replay-1048576", "ring_timeout_or_hang", False)]
    FAIL_ORDER = [
        {"arm": "replay-4096", "state": "passed", "detail": {}},
        {"arm": "replay-1048576", "state": "failed",
         "detail": {"stop_condition": "ring_timeout_or_hang"}},
    ]

    def _check(self, arms, order, *, expected="V2G_EVIDENCE_BLOCKED",
               mutate=None, **kwargs):
        with tempfile.TemporaryDirectory() as td:
            ev = write_synth_evidence(Path(td), arms=arms,
                                      order_entries=order, **kwargs)
            if mutate:
                mutate(ev)
            result = red.derive_terminal(ev)
            self.assertEqual(result["terminal"], expected)
            return result

    @staticmethod
    def _change_arm(ev, name, change):
        path = ev / "arms" / f"{name}.json"
        doc = json.loads(path.read_text())
        change(doc)
        path.write_text(json.dumps(doc))

    def test_failed_historical_arm_without_amendment_blocks(self):
        result = self._check(
            self.FAIL_ARMS, self.FAIL_ORDER,
            arm_producer_head="5" * 40,
            arm_closure_digest="7" * 64)
        self.assertTrue(any("historical-closure amendment" in b
                            for b in result["basis"]))
        self.assertTrue(any("observed a failure" in b
                            for b in result["basis"]))

    def test_failed_arm_on_other_topology_blocks(self):
        result = self._check(self.FAIL_ARMS, self.FAIL_ORDER,
                             arm_roots=[(ROOT_A, UPSTREAM),
                                        (ROOT_B, UPSTREAM)])
        self.assertTrue(any("gate bound" in b for b in result["basis"]))

    def test_failed_arm_missing_or_contradictory_boot_proof_blocks(self):
        for kwargs in ({"write_boot_proof": False},
                       {"boot_proof_root": ROOT_B}):
            with self.subTest(kwargs=kwargs):
                result = self._check(self.FAIL_ARMS, self.FAIL_ORDER,
                                     **kwargs)
                self.assertTrue(any("boot-proof" in b
                                    for b in result["basis"]))

    def test_full_arm_directory_with_partial_order_blocks(self):
        self._check(self.PASS_ARMS, self.PASS_ORDER[:1])

    def test_order_entry_without_arm_artifact_blocks(self):
        self._check(self.PASS_ARMS[:1], self.PASS_ORDER[:2])

    def test_extra_arm_artifact_blocks(self):
        self._check(self.PASS_ARMS[:2], self.PASS_ORDER[:1])

    def test_failed_order_arm_differs_from_stopped_arm_blocks(self):
        arms = [("replay-4096", "ring_timeout_or_hang", False),
                ("replay-1048576", None, True)]
        self._check(arms, self.FAIL_ORDER)

    def test_passed_order_entry_with_stop_blocks(self):
        self._check([(self.FAIL_ARMS[0]),
                     ("replay-1048576", "ring_timeout_or_hang", False)],
                    self.PASS_ORDER[:2])

    def test_failed_order_entry_without_stop_blocks(self):
        self._check(self.PASS_ARMS[:2], self.FAIL_ORDER)

    def test_arm_name_size_and_order_detail_mismatch_block(self):
        changes = (
            lambda d: d.update(arm="replay-67108864"),
            lambda d: d.update(size_bytes=8192),
        )
        for change in changes:
            with self.subTest(change=change):
                self._check(self.PASS_ARMS[:1], self.PASS_ORDER[:1],
                            mutate=lambda ev: self._change_arm(
                                ev, "replay-4096", change))
        order = [{"arm": "replay-4096", "state": "passed",
                  "detail": {"size": 8192}}]
        self._check(self.PASS_ARMS[:1], order)

    def test_positive_authorized_failure_terminals_and_pass(self):
        self._check(self.FAIL_ARMS, self.FAIL_ORDER,
                    expected="V2G_PCIE_PATH_REMEDIATED_FAULT_REPRODUCED")
        different = [("replay-4096", "correctness_mismatch", False)]
        order = [{"arm": "replay-4096", "state": "failed",
                  "detail": {"stop_condition": "correctness_mismatch"}}]
        self._check(different, order,
                    expected="V2G_PCIE_PATH_REMEDIATED_DIFFERENT_FAILURE")
        self._check(self.PASS_ARMS, self.PASS_ORDER,
                    expected="V2G_PCIE_PATH_REMEDIATED_REPLAY_PASS")


# ---------------------------------------------------------------------------
# Topology-identity continuity (2026-09-20 correction controls)
# ---------------------------------------------------------------------------

class TestTopologyIdentityContinuity(unittest.TestCase):
    """The 1c.5-vs-1d.0 defect class: a gate bound to one root port
    must never authorize/credit evidence executed on another. Each
    control builds a full synthetic evidence tree where EXACTLY ONE
    identity axis crosses (root A vs root B) and asserts the gate /
    authorization / terminal fail closed."""

    COLD_PROOF = {"cycles": [
        {"prev_boot_ended_without_reboot_target": True,
         "shutdown_record_present": True}]}

    def _gate(self, *, census, obs, confs, interventions=None):
        return gate.evaluate_gate(
            observation=obs, census=census,
            interventions=interventions or [synth_intervention()],
            cold_confirmation_observations=confs,
            cold_proof=self.COLD_PROOF)

    def test_control_cold_confirmation_on_root_b_fails(self):
        # clean candidate on root A + cold confirmation on root B
        r = self._gate(
            census=synth_census(),
            obs=synth_observation(),
            confs=[synth_observation(boot_id="b2", )])
        # tamper ONLY the confirmation's root port to root B
        confs = [synth_observation(boot_id="b2")]
        confs[0]["chain_roles"]["root_port"] = ROOT_B
        r2 = self._gate(
            census=synth_census(), obs=synth_observation(),
            confs=confs)
        self.assertTrue(
            r["checks"]["topology_identity_continuity"])
        self.assertFalse(
            r2["checks"]["topology_identity_continuity"])
        self.assertEqual(r2["result"], "FAIL")
        self.assertIn("topology_identity_continuity",
                      r2["failed_checks"])

    def test_control_stale_census_boot_fails(self):
        # the census is from a DIFFERENT boot than the candidate
        # observation (the literal 2026-09-20 defect: the gate was fed
        # intervention-3's pre-census from the motherboard-slot boot)
        r = self._gate(
            census=synth_census(boot_id="boot-OTHER",
                                root_port=ROOT_B),
            obs=synth_observation(),
            confs=[synth_observation(boot_id="b2")])
        self.assertFalse(
            r["checks"]["topology_identity_continuity"])
        self.assertEqual(r["result"], "FAIL")

    def test_control_census_chain_vs_observation_roles(self):
        # census boot matches but its derived chain names root B while
        # the observation's live-derived roles name root A
        r = self._gate(
            census=synth_census(root_port=ROOT_B),
            obs=synth_observation(),
            confs=[synth_observation(boot_id="b2")])
        self.assertFalse(
            r["checks"]["topology_identity_continuity"])

    def test_control_gate_root_a_qualification_root_b(self):
        # gate bound to root A; qualification chain on root B
        with tempfile.TemporaryDirectory() as td:
            ev = write_synth_evidence(
                Path(td), qual_root=ROOT_B,
                arms=[("replay-4096", None, True)],
                order_entries=[{"arm": "replay-4096",
                                "state": "passed", "detail": {}}])
            # authorization re-check must refuse the disagreement
            # (synth evidence writes an authz with a matching binding;
            # flip ONLY the qualification chain to root B)
            qpath = ev / "qualification" / "qualification.json"
            q = json.loads(qpath.read_text())
            q["chain"]["root_port_bdf"] = ROOT_B
            qpath.write_text(json.dumps(q))
            # the reducer terminal path must not reach REPLAY_PASS on
            # crossed identities: re-derive with the authz binding
            # naming root A while qualification names root B
            r = red.derive_terminal(ev)
            self.assertEqual(r["terminal"],
                             "V2G_EVIDENCE_BLOCKED")

    def test_control_gate_root_a_replay_arm_root_b(self):
        # gate bound to root A; one arm executed on root B
        LADDER = ("replay-4096", "replay-1048576",
                  "replay-16777216", "replay-67108864")
        with tempfile.TemporaryDirectory() as td:
            ev = write_synth_evidence(
                Path(td),
                arms=[(n, None, True) for n in LADDER],
                order_entries=[
                    {"arm": n, "state": "passed", "detail": {}}
                    for n in LADDER],
                arm_roots=[(ROOT_A, UPSTREAM), (ROOT_B, UPSTREAM),
                           (ROOT_A, UPSTREAM), (ROOT_A, UPSTREAM)])
            r = red.derive_terminal(ev)
            self.assertEqual(r["terminal"], "V2G_EVIDENCE_BLOCKED")
            self.assertTrue(any(ROOT_B in b for b in r["basis"]))

    def test_control_arms_crossing_topologies(self):
        # both arms pass but on DIFFERENT roots from each other
        with tempfile.TemporaryDirectory() as td:
            ev = write_synth_evidence(
                Path(td),
                arms=[("replay-4096", None, True),
                      ("replay-1048576", None, True)],
                order_entries=[
                    {"arm": "replay-4096", "state": "passed",
                     "detail": {}},
                    {"arm": "replay-1048576", "state": "passed",
                     "detail": {}}],
                arm_roots=[(ROOT_A, UPSTREAM),
                           (ROOT_B, UPSTREAM)])
            r = red.derive_terminal(ev)
            self.assertEqual(r["terminal"], "V2G_EVIDENCE_BLOCKED")

    def test_control_no_boot_proof_no_replay_pass(self):
        # fail closed: without a retained boot proof the pass cannot
        # be attributed to any topology
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
                write_boot_proof=False)
            r = red.derive_terminal(ev)
            self.assertEqual(r["terminal"], "V2G_EVIDENCE_BLOCKED")
            self.assertTrue(any("boot-proof" in b for b in r["basis"]))

    def test_control_authz_binding_disagrees_with_boot_proof(self):
        # the authorization document claims a topology the retained
        # boot-proof does not establish
        LADDER = ("replay-4096", "replay-1048576",
                  "replay-16777216", "replay-67108864")
        with tempfile.TemporaryDirectory() as td:
            ev = write_synth_evidence(
                Path(td),
                arms=[(n, None, True) for n in LADDER],
                order_entries=[
                    {"arm": n, "state": "passed", "detail": {}}
                    for n in LADDER],
                boot_proof_root=ROOT_A,
                authz_binding_root=ROOT_B)
            r = red.derive_terminal(ev)
            self.assertEqual(r["terminal"], "V2G_EVIDENCE_BLOCKED")
            self.assertTrue(any("disagrees" in b or "different" in b
                                for b in r["basis"]))

    def test_positive_continuity_reaches_replay_pass(self):
        # positive control: all identities agree -> REPLAY_PASS still
        # reachable through the REAL reducer (proves the new checks
        # are not simply always-fail)
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
                              "replay-16777216", "replay-67108864")])
            r = red.derive_terminal(ev)
            self.assertEqual(
                r["terminal"], "V2G_PCIE_PATH_REMEDIATED_REPLAY_PASS")

    def test_control_authored_terminal_claiming_wrong_topology(self):
        # authored final report claiming a topology different from
        # the retained replay authority: the TERMINAL.json agreement
        # check fires only on the terminal token, so the REPORT-level
        # guard lives in the reducer basis + assembler; here assert
        # the assembled basis names the bound topology and a TERMINAL
        # contradicting the reduction is refused (control 20 path)
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
                              "replay-16777216", "replay-67108864")])
            r = red.derive_terminal(ev)
            # the basis must name the EXACT bound topology
            self.assertTrue(any(ROOT_A in b and UPSTREAM in b
                                for b in r["basis"]))
            # a hand-authored terminal doc contradicting the
            # deterministic reduction is still refused
            (ev / "TERMINAL.json").write_text(json.dumps(
                {"terminal": "V2G_PCIE_PATH_CLEAN_NO_REPLAY"}))
            with self.assertRaises(red.ReductionError):
                red.derive_terminal(ev)


class TestBootProof(unittest.TestCase):
    """Boot-continuity proof builder: parse/compute/fail-closed."""

    def _probe_raw(self, *, boot_id="boot-y", uptime=100.0,
                   probed_utc="2026-09-20T16:00:00+00:00",
                   root_short="1d.0"):
        return (
            "=== boot_id\n"
            f"{boot_id}\n"
            "=== uptime_seconds\n"
            f"{uptime}\n"
            "=== probed_utc\n"
            f"{probed_utc}\n"
            "=== kernel\n7.1.8+deb13-amd64\n"
            "=== lspci_nn\n"
            "02:00.0 PCI bridge [0604]: Microchip Technology PM8533 "
            "PFX 48xG3 PCIe Fanout Switch [11f8:8533]\n"
            "06:00.0 Display controller [0380]: AMD Vega 10 "
            "[1002:6864]\n"
            "09:00.0 Display controller [0380]: AMD Vega 10 "
            "[1002:6864]\n"
            "=== lspci_tree\n"
            f"-[0000:00]-+-1d.0-[02-09]----00.0-[03-09]--+-00.0-"
            f"[04-06]----00.0-[05-06]----00.0-[06]----00.0  Advanced "
            "Micro Devices, Inc. [AMD/ATI] Vega 10 [Radeon Pro "
            "V340/Instinct MI25x2]\n"
            "            |                               "
            "\\-01.0-[07-09]----00.0-[08-09]----00.0-[09]----00.0  "
            "Advanced Micro Devices, Inc. [AMD/ATI] Vega 10 [Radeon "
            "Pro V340/Instinct MI25x2]\n")

    def _ev(self, tmp: Path, *, probe=None, census_boot="boot-y",
            census_mono_s=50.0,
            census_utc="2026-09-20T15:59:10+00:00",
            census_root=ROOT_A, qual_root=ROOT_A,
            order_utc=("2026-09-20T15:59:40+00:00",
                       "2026-09-20T15:59:50+00:00")):
        import issue232_bootproof as bp
        ev = tmp / "evidence"
        (ev / "censuses" / "anchor").mkdir(parents=True, exist_ok=True)
        (ev / "censuses" / "anchor" / "census.json").write_text(
            json.dumps({
                "schema": "inferswarm.v2g.census/1",
                "boot_id": census_boot,
                "collected_utc": census_utc,
                "host_health": {"monotonic_ns": int(census_mono_s
                                                    * 1e9)},
                "derived_chain": {
                    "root_port_bdf": census_root,
                    "switch_upstream_bdf": UPSTREAM,
                    "root_port_sta": {"width": 1},
                    "switch_upstream_sta": {"width": 1}},
                "vega_bdfs": ["0000:06:00.0", "0000:09:00.0"],
            }))
        (ev / "qualification").mkdir(parents=True, exist_ok=True)
        (ev / "qualification" / "qualification.json").write_text(
            json.dumps({
                "schema": "inferswarm.v2g.qualification/1",
                "boot_id": census_boot,
                "collected_utc": census_utc,
                "chain": {"root_port_bdf": qual_root,
                          "switch_upstream_bdf": UPSTREAM},
            }))
        entries = []
        for i, arm in enumerate(("replay-4096", "replay-1048576")):
            entries.append({"arm": arm, "state": "passed",
                            "recorded_utc": order_utc[i],
                            "detail": {}})
        doc = {"schema": "inferswarm.v2g.replay-order/1",
               "campaign_id": rc.CAMPAIGN_ID,
               "entries": entries}
        import issue232_replay as replay_mod
        doc["chain_digest"] = replay_mod._chain(doc)
        (ev / "replay-order-state.json").write_text(json.dumps(doc))
        (ev / "arms").mkdir(parents=True, exist_ok=True)
        for arm in ("replay-4096", "replay-1048576"):
            (ev / "arms" / f"{arm}.json").write_text(json.dumps(
                {"arm": arm}))
            (ev / "raw").mkdir(parents=True, exist_ok=True)
            (ev / "raw" / f"{arm}-identity.stdout").write_text(
                json.dumps({"devices": [
                    {"bdf": "0000:06:00.0",
                     "uuid": "u-a"},
                    {"bdf": "0000:09:00.0",
                     "uuid": "u-b"}]}))
        probe_rel = "raw/bootproof-probe.stdout"
        (ev / "raw").mkdir(parents=True, exist_ok=True)
        (ev / probe_rel).write_text(probe if probe is not None
                                    else self._probe_raw())
        return ev, probe_rel

    def test_boot_proof_binds_replay_boot(self):
        import issue232_bootproof as bp
        with tempfile.TemporaryDirectory() as td:
            ev, probe_rel = self._ev(Path(td))
            doc = bp.build_boot_proof(
                evidence_root=ev, probe_raw_rel=probe_rel,
                anchor_census_rel="censuses/anchor")
            self.assertEqual(doc["replay_boot_id"], "boot-y")
            self.assertEqual(doc["topology"]["root_port"], ROOT_A)
            self.assertEqual(doc["topology"]["switch_upstream"],
                             UPSTREAM)
            self.assertLessEqual(doc["continuity"]["drift_s"], 5.0)

    def test_boot_proof_reboot_fails_closed(self):
        import issue232_bootproof as bp
        with tempfile.TemporaryDirectory() as td:
            ev, probe_rel = self._ev(
                Path(td),
                probe=self._probe_raw(boot_id="boot-REBOOTED"))
            with self.assertRaises(bp.BootProofError):
                bp.build_boot_proof(
                    evidence_root=ev, probe_raw_rel=probe_rel,
                    anchor_census_rel="censuses/anchor")

    def test_boot_proof_uptime_drift_fails_closed(self):
        import issue232_bootproof as bp
        with tempfile.TemporaryDirectory() as td:
            # uptime inconsistent with census monotonic + wall clock
            ev, probe_rel = self._ev(
                Path(td), probe=self._probe_raw(uptime=13.0))
            with self.assertRaises(bp.BootProofError):
                bp.build_boot_proof(
                    evidence_root=ev, probe_raw_rel=probe_rel,
                    anchor_census_rel="censuses/anchor")

    def test_boot_proof_arm_window_outside_interval_fails(self):
        import issue232_bootproof as bp
        with tempfile.TemporaryDirectory() as td:
            ev, probe_rel = self._ev(
                Path(td),
                order_utc=("2026-09-20T17:30:00+00:00",
                           "2026-09-20T17:30:10+00:00"))
            with self.assertRaises(bp.BootProofError):
                bp.build_boot_proof(
                    evidence_root=ev, probe_raw_rel=probe_rel,
                    anchor_census_rel="censuses/anchor")

    def test_boot_proof_topology_move_fails_closed(self):
        import issue232_bootproof as bp
        with tempfile.TemporaryDirectory() as td:
            # the present-day tree shows the card on root B while the
            # anchor census derived root A
            raw = self._probe_raw().replace(
                "1d.0-[02-09]", "1c.5-[02-09]")
            ev, probe_rel = self._ev(Path(td), probe=raw)
            with self.assertRaises(bp.BootProofError):
                bp.build_boot_proof(
                    evidence_root=ev, probe_raw_rel=probe_rel,
                    anchor_census_rel="censuses/anchor")


if __name__ == "__main__":
    unittest.main()
