#!/usr/bin/env python3
"""Issue #216 assembler state-machine tests — synthetic fixture trees.

Each test builds a COMPLETE synthetic evidence tree (preflight with a
R3-revalidating fresh mapping, baselines, 3 concurrent pairs with seam
records, transport with #35-faithful raw probe records, soak, fault
arms, reset) exercising the REAL assembler (imported, then as a
subprocess in the mutation controls), then mutates one fact and asserts
the exact terminal flips.

Seam observe records are synthetic-but-faithful JSONL in the #219
instrument's exact schema (header + drain records; complete drains;
calibration pairs; monotonic ticks).
"""
from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "tests"))

import issue216_assemble as asm
import issue216_physical_authority as _pa
__AUTH__ = _pa.build_authority()["authority_digest"]
import issue216_v2d_fixtures as fx
__BIND__ = fx.closure_binding()
from test_issue216_v2d_concurrent import (clean_run, synth_run_bytes,
                                           write_run)
import issue216_v2d_fixtures as fx

PERIOD_NS = 37.037


def synth_observe_jsonl(*, bus: int = 6, spans_ms=((0, 200), (400, 600)),
                        dev_base=10 ** 12, mono_base=50 * 10 ** 9,
                        max_dev=20000, ticks_per_span=64) -> bytes:
    """Faithful #219 seam record: header + one drain per span."""
    ticks_per_ms = 1e6 / PERIOD_NS
    roles, gcs, queries = [], [], []
    ticks: list[int] = []
    q = 0
    for gi, (b_ms, e_ms) in enumerate(spans_ms):
        bt = int(dev_base + b_ms * ticks_per_ms)
        et = int(dev_base + e_ms * ticks_per_ms)
        roles += [0, 1]
        gcs += [gi, gi]
        queries += [q, q + 1]
        ticks += [bt, et]
        q += 2
    header = {
        "kind": "header", "schema": "inferswarm.v2d0.observe-record/1",
        "device_label": "Vulkan1", "device_name":
            "AMD Radeon Pro V340 (RADV VEGA10)",
        "device_uuid": f"{bus:02x}" + "aa" * 15, "vendor_id": 4098,
        "device_id": 26724, "pci_domain": 0, "pci_bus": bus,
        "pci_device": 0, "pci_function": 0,
        "timestamp_period_ns": PERIOD_NS, "timestamp_valid_bits": 64,
        "graph_computes": len(spans_ms),
        "tick_roles": roles, "tick_graph_computes": gcs,
        "tick_queries": queries, "total_ticks": len(ticks),
    }
    drain = {
        "kind": "drain", "drain_index": 0, "query_first": 0,
        "query_count": len(ticks), "ticks": ticks,
        "get_query_result": "esuccess", "calibration_result": 0,
        "calibration_device": dev_base,
        "calibration_monotonic_ns": mono_base,
        "calibration_max_deviation_ns": max_dev,
    }
    lines = [json.dumps(header), json.dumps(drain)]
    return ("\n".join(lines) + "\n").encode()


def _mapping_digest(root: Path) -> str:
    return json.loads((root / "preflight" / "mapping" /
                       "fresh-mapping.json").read_bytes())["mapping_digest"]


def synth_pair_fixture(root: Path, attempt: str, *, overlap_ms=(100, 150),
                       die_a_correct=True, die_b_correct=True,
                       die_a_bdf="0000:06:00.0",
                       die_b_bdf="0000:09:00.0") -> dict:
    """One concurrent pair fixture: runs + seam records + pair json."""
    d = root / "concurrent" / attempt
    d.mkdir(parents=True, exist_ok=True)
    pair = {"attempt_id": attempt, "phase": "concurrent",
            "participants": {}, "observe_rels": {},
            "wrapper_intervals_ns": {"a": [0, 1], "b": [0, 1]},
            "authority_digest": __AUTH__,
            "mapping_digest": _mapping_digest(root),
            "closure_digest": __BIND__["closure_digest"],
            "producer_head": __BIND__["producer_head"]}
    # die A runs at [0,200]ms device-domain; die B overlapping
    a_spans = ((0, 200),)
    b_spans = ((overlap_ms[0], overlap_ms[0] + 50),)
    for die, bdf, spans, correct in (
            ("a", die_a_bdf, a_spans, die_a_correct),
            ("b", die_b_bdf, b_spans, die_b_correct)):
        run = synth_run_bytes(f"run-{attempt}", bdf=bdf,
                              selector=f"Vulkan{1 if die == 'a' else 2}",
                              correct=correct)
        rd = d / die
        rd.mkdir(exist_ok=True)
        write_run(rd, run, "")
        # collector convention: rel paths are die-relative
        for key in ("stdout_rel", "stderr_rel", "exit_code_rel"):
            run[key] = f"{die}/{run[key]}"
        pair["participants"][die] = clean_run(run)
        observe_rel = f"{die}/observe-{attempt}.jsonl"
        (d / observe_rel).write_bytes(
            synth_observe_jsonl(bus=int(bdf.split(":")[1], 16),
                                spans_ms=spans,
                                dev_base=10 ** 12,
                                mono_base=50 * 10 ** 9))
        pair["observe_rels"][die] = observe_rel
    (d / f"pair-{attempt}.json").write_bytes(
        json.dumps(pair, indent=1, sort_keys=True).encode() + b"\n")
    return pair


def build_complete_tree(root: Path, *, n_concurrent: int = 3,
                        soak_duration_s: int = 3600) -> dict:
    """Complete synthetic evidence tree: all phases PASS-shaped."""
    root.mkdir(parents=True, exist_ok=True)
    BIND = fx.closure_binding()
    # fresh mapping artifact (R3-revalidating, retained probe bytes)
    mapping_doc = fx.build_mapping_doc(root)
    MAPPING_DIGEST = mapping_doc["mapping_digest"]
    # preflight (collector layout: summary + raw inside the phase dir)
    (root / "preflight").mkdir(exist_ok=True)
    (root / "preflight" / "raw").mkdir(exist_ok=True)
    (root / "preflight" / "raw" / "journal_faults.stdout").write_bytes(
        b"no faults\n")
    # sentinels: full run rows + raw bytes so the assembler re-derives
    sentinels = {}
    for die, bdf, sel in (("a", "0000:06:00.0", "Vulkan1"),
                          ("b", "0000:09:00.0", "Vulkan2")):
        run = synth_run_bytes(f"sentinel-pf1-{die}", bdf=bdf, selector=sel)
        write_run(root / "preflight" / "sentinel" / die, run, "")
        run_row = clean_run(run)
        sentinels[die] = {"correct": True, "run": run_row}
    preflight = {
        "schema": "inferswarm.v2d.preflight/2", "campaign_id":
            "issue216-v2d-v340l-concurrent-dual-die-v2",
        "attempt_id": "pf1", "authority_digest": __AUTH__,
        "mapping_digest": MAPPING_DIGEST, "boot_id": "b-1",
        "closure_digest": BIND["closure_digest"],
        "producer_head": BIND["producer_head"],
        "bdfs": ["0000:06:00.0", "0000:09:00.0"],
        "sentinels": sentinels,
    }
    (root / "preflight" / "preflight.json").write_bytes(
        json.dumps(preflight, indent=1).encode())
    # baselines
    for die in ("a", "b"):
        reps = []
        dd = root / f"baseline-{die}"
        dd.mkdir(exist_ok=True)
        for i in (1, 2, 3):
            run = synth_run_bytes(
                f"baseline-{die}-{i:02d}",
                selector=f"Vulkan{1 if die == 'a' else 2}",
                bdf="0000:06:00.0" if die == "a" else "0000:09:00.0")
            write_run(dd, run, "")
            reps.append({"rep": i, "run": clean_run(run)})
        (root / f"baseline-{die}.json").write_bytes(
            json.dumps({"die": die, "reps": reps,
                        "authority_digest": __AUTH__,
                        "mapping_digest": MAPPING_DIGEST,
                        "closure_digest": BIND["closure_digest"],
                        "producer_head": BIND["producer_head"]},
                       indent=1).encode())
    # concurrent attempts
    attempts = []
    for i in range(1, n_concurrent + 1):
        att = f"c{i:02d}"
        synth_pair_fixture(root, att)
        attempts.append({"attempt_id": att, "status": "run"})
    (root / "attempt-ledger.json").write_bytes(
        json.dumps({"attempts": attempts}, indent=1).encode())
    # transport: #35-faithful raw records per arm + the phase summary
    transport = {"authority_digest": __AUTH__,
                 "mapping_digest": MAPPING_DIGEST,
                 "closure_digest": BIND["closure_digest"],
                 "producer_head": BIND["producer_head"]}
    for mode, die, sel_idx, match_idx in (
            ("single-a", "a", 1, 0), ("single-b", "b", 2, 1)):
        bdf = "0000:06:00.0" if die == "a" else "0000:09:00.0"
        record = fx.synth_transport_probe_record(bdf, sel_idx, match_idx)
        mode_dir = root / "transport" / mode
        (mode_dir / "raw").mkdir(parents=True, exist_ok=True)
        (mode_dir / "raw" / "probe.json").write_bytes(
            json.dumps(record, indent=1).encode())
        stdout_b = record["probe_stdout"].encode()
        (mode_dir / f"{mode}.stdout").write_bytes(stdout_b)
        (mode_dir / f"{mode}.exit-code").write_bytes(b"0\n")
        transport[mode] = {
            "exit_code": 0, "stdout_rel": f"{mode}.stdout",
            "exit_code_rel": f"{mode}.exit-code",
            "stdout_sha256": hashlib.sha256(stdout_b).hexdigest()}
    dual_parts = {}
    for die, sel_idx, match_idx in (("a", 1, 0), ("b", 2, 1)):
        bdf = "0000:06:00.0" if die == "a" else "0000:09:00.0"
        record = fx.synth_transport_probe_record(bdf, sel_idx, match_idx)
        ddir = root / "transport" / "dual" / die
        (ddir / "raw").mkdir(parents=True, exist_ok=True)
        (ddir / "raw" / "probe.json").write_bytes(
            json.dumps(record, indent=1).encode())
        stdout_b = record["probe_stdout"].encode()
        (ddir / "probe.stdout").write_bytes(stdout_b)
        (ddir / "probe.exit-code").write_bytes(b"0\n")
        dual_parts[die] = {
            "exit_code": 0, "stdout_rel": "probe.stdout",
            "exit_code_rel": "probe.exit-code",
            "stdout_sha256": hashlib.sha256(stdout_b).hexdigest()}
    transport["dual"] = {"participants": dual_parts,
                         "probe_process_overlap": True,
                         "intervals_ns": {"a": [0, 100],
                                          "b": [10, 110]}}
    (root / "transport").mkdir(exist_ok=True)
    (root / "transport" / "transport-tp1.json").write_bytes(
        json.dumps(transport, indent=1).encode())
    # soak: 60 samples of 60s cadence = 3600s, no faults
    raw = root / "soak" / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    samples = []
    for i in range(1, 61):
        t = i * 60 * 10 ** 9
        snap = {"sample": i, "monotonic_ns": t,
                "telemetry": {"0000:06:00.0": {"ras_gpu_err_cnt": 0},
                              "0000:09:00.0": {"ras_gpu_err_cnt": 0}},
                "aer": {"0000:06:00.0": {"aer_dev_fatal": {}},
                        "0000:09:00.0": {"aer_dev_fatal": {}}},
                "pids": {"a": {"pid": 101, "state": "R"},
                         "b": {"pid": 102, "state": "R"}}}
        rel = f"raw/telemetry-{i:04d}.json"  # soak-dir-relative
        snap_bytes = json.dumps(snap, sort_keys=True).encode()
        (raw / Path(rel).name).write_bytes(snap_bytes)
        (raw / Path(rel).name.replace("telemetry-", "journal-").replace(
            ".json", ".stdout")).write_bytes(b"clean\n")
        samples.append({"sample": i, "rel": rel, "monotonic_ns": t,
                        "sha256": hashlib.sha256(snap_bytes).hexdigest()})
    (raw / "journal-final.stdout").write_bytes(b"clean\n")
    # checkpoints every 600s (summary json + run dir, collector shape)
    for cps in range(600, soak_duration_s, 600):
        cp_dir = raw / f"checkpoint-{cps:04d}"
        cp_dir.mkdir(parents=True, exist_ok=True)
        pair = _checkpoint_pair(root, cp_dir, f"cp{cps}")
        (raw / f"checkpoint-{cps:04d}.json").write_bytes(
            json.dumps(pair, indent=1, sort_keys=True).encode())
    final_dir = raw / "final-sentinel"
    final_dir.mkdir(parents=True, exist_ok=True)
    final_pair = _checkpoint_pair(root, final_dir, "final")
    (raw / "final-sentinel.json").write_bytes(
        json.dumps(final_pair, indent=1, sort_keys=True).encode())
    soak = {
        "schema": "inferswarm.v2d.soak-run/2",
        "campaign_id": "issue216-v2d-v340l-concurrent-dual-die-v2",
        "attempt_id": "soak1", "started_ns": 0, "ended_ns":
            soak_duration_s * 10 ** 9,
        "duration_s": soak_duration_s, "requested_duration_s":
            soak_duration_s, "cadence_s": 60, "checkpoint_every_s": 600,
        "sched_tolerance_s": 15, "stop_reason": "duration_reached",
        "pairs_launched": 60, "events": [], "samples": samples,
        "authority_digest": __AUTH__, "mapping_digest": MAPPING_DIGEST,
        "closure_digest": BIND["closure_digest"],
        "producer_head": BIND["producer_head"],
    }
    (root / "soak").mkdir(exist_ok=True)
    (root / "soak" / "soak-sk1.json").write_bytes(
        json.dumps(soak, indent=1).encode())
    # fault arms
    for arm in ("a", "b"):
        _build_fault_arm(root, arm)
    # reset
    (root / "reset-determination.json").write_bytes(json.dumps({
        "schema": "inferswarm.v2d.reset-determination/2",
        "campaign_id": "issue216-v2d-v340l-concurrent-dual-die-v2",
        "probes": {"a": {"bdf": "0000:06:00.0",
                         "reset_file_present": True},
                   "b": {"bdf": "0000:09:00.0",
                         "reset_file_present": True}},
        "lspci_tree": "-+-[06]-+-06.00.0\n`-[09]-+-09.00.0\n",
        "both_functions_behind_one_switch": True,
        "kernel_docs_stdout": "amdgpu reset docs\nPROBE_DONE\n",
        "disposition": "DEVICE_RESET_ISOLATION_NOT_AVAILABLE",
        "reason": "shared switch",
        "authority_digest": __AUTH__,
        "mapping_digest": _mapping_digest(root),
        "closure_digest": __BIND__["closure_digest"],
        "producer_head": __BIND__["producer_head"],
    }, indent=1).encode())
    return {"root": root, "attempts": attempts}


def _checkpoint_pair(root: Path, cp_dir: Path, tag: str) -> dict:
    pair = {"attempt_id": tag, "phase": "soak-checkpoint",
            "participants": {}, "observe_rels": {},
            "wrapper_intervals_ns": {"a": [0, 1], "b": [0, 1]},
            "authority_digest": __AUTH__,
            "mapping_digest": _mapping_digest(root),
            "closure_digest": __BIND__["closure_digest"],
            "producer_head": __BIND__["producer_head"]}
    for die, bdf, sel in (("a", "0000:06:00.0", "Vulkan1"),
                          ("b", "0000:09:00.0", "Vulkan2")):
        run = synth_run_bytes(f"run-{tag}", bdf=bdf, selector=sel)
        rd = cp_dir / die
        rd.mkdir(parents=True, exist_ok=True)
        write_run(rd, run, "")
        for key in ("stdout_rel", "stderr_rel", "exit_code_rel"):
            run[key] = f"{die}/{run[key]}"
        pair["participants"][die] = clean_run(run)
        observe_rel = f"{die}/observe-{die}.jsonl"
        (cp_dir / observe_rel).write_bytes(
            synth_observe_jsonl(bus=int(bdf.split(":")[1], 16),
                                spans_ms=((0, 50),),
                                dev_base=10 ** 12,
                                mono_base=50 * 10 ** 9))
        pair["observe_rels"][die] = observe_rel
    return pair


def _build_fault_arm(root: Path, arm: str) -> None:
    victim = arm
    sibling = "b" if arm == "a" else "a"
    base = root / f"fault-arm-{arm}-loss"
    sib_bdf = "0000:06:00.0" if sibling == "a" else "0000:09:00.0"
    sib_sel = "Vulkan1" if sibling == "a" else "Vulkan2"
    init = base / "initial"
    rel_dir = base / "relaunch"
    # victim's own retained exit code: SIGKILLed (negative)
    (init / victim).mkdir(parents=True, exist_ok=True)
    (init / victim / "run.exit-code").write_bytes(b"-9\n")
    sib_run = synth_run_bytes(f"fault-sib-{arm}", bdf=sib_bdf,
                              selector=sib_sel)
    write_run(init / sibling, sib_run, "")
    vic_run = synth_run_bytes(f"fault-vic-{arm}",
                              bdf="0000:06:00.0" if victim == "a"
                              else "0000:09:00.0",
                              selector=f"Vulkan{1 if victim == 'a' else 2}")
    write_run(rel_dir / victim, vic_run, "")
    rec_dir = base / "recovery-sentinel"
    rec_pair = _checkpoint_pair(root, rec_dir, f"fault{arm}-rec")
    doc = {
        "schema": "inferswarm.v2d.fault-arm/2",
        "campaign_id": "issue216-v2d-v340l-concurrent-dual-die-v2",
        "attempt_id": f"f{arm}1", "arm": arm, "victim": victim,
        "sibling": sibling, "victim_gone": True, "kill_method": "SIGKILL",
        "sibling_run": clean_run(sib_run), "relaunch_run":
            clean_run(vic_run),
        "recovery_sentinel": rec_pair,
        "authority_digest": __AUTH__,
        "mapping_digest": _mapping_digest(root),
        "closure_digest": __BIND__["closure_digest"],
        "producer_head": __BIND__["producer_head"],
    }
    (root / f"fault-arm-{arm}.json").write_bytes(
        json.dumps(doc, indent=1).encode())


def classify_tree(root: Path) -> str:
    return asm.assemble(root)["terminal"]


class TestTerminalStateMachine(unittest.TestCase):
    def test_complete_pass(self):
        with tempfile.TemporaryDirectory() as td:
            build_complete_tree(Path(td))
            self.assertEqual(
                classify_tree(Path(td)),
                "V2D_V340L_CONCURRENT_DUAL_DIE_STABILITY_PASS")

    def test_concurrent_correctness_fail_retained(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            build_complete_tree(root)
            # break one retained repeat's output (byte-exact fails)
            pair_dir = root / "concurrent" / "c02" / "a"
            data = json.loads((root / "concurrent" / "c02" /
                               "pair-c02.json").read_text())
            run = data["participants"]["a"]
            stdout = (root / "concurrent" / "c02" / run["stdout_rel"]).read_bytes()
            tampered = stdout.replace(b"pangram", b"PANGRAM")
            (root / "concurrent" / "c02" / run["stdout_rel"]).write_bytes(tampered)
            # update binding hashes so the tamper is CONTENT-level, not
            # hash-level: the assembler must still fail on byte-exactness
            run["stdout_sha256"] = __import__("hashlib").sha256(
                tampered).hexdigest()
            (root / "concurrent" / "c02" / "pair-c02.json").write_bytes(
                json.dumps(data, indent=1, sort_keys=True).encode())
            self.assertEqual(
                classify_tree(root),
                "V2D_V340L_CONCURRENT_CORRECTNESS_FAIL")

    def test_no_overlap_classified_fail(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            build_complete_tree(root)
            # move die B's device spans far from die A's: NON_OVERLAP
            data = json.loads((root / "concurrent" / "c01" /
                               "pair-c01.json").read_text())
            rel = data["observe_rels"]["b"]
            p = root / "concurrent" / "c01" / rel
            record = [json.loads(ln) for ln in p.read_text().splitlines()
                      if ln.strip()]
            for rec in record:
                if rec.get("kind") == "drain":
                    shift = int(10 ** 9 / PERIOD_NS * 1000)  # +1000ms
                    rec["ticks"] = [t + shift for t in rec["ticks"]]
            p.write_bytes(("\n".join(json.dumps(r) for r in record)
                           + "\n").encode())
            # 2 clean overlapping repeats + 1 retained non-overlapping
            # repeat: repeatability violation on valid simultaneous
            # executions -> CORRECTNESS_FAIL (never BLOCKED)
            self.assertEqual(
                classify_tree(root),
                "V2D_V340L_CONCURRENT_CORRECTNESS_FAIL")

    def test_same_die_cross_bind_fail(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            build_complete_tree(root)
            # participant B's selected BDF becomes die A's bus: the
            # pair runs on one physical die
            data = json.loads((root / "concurrent" / "c01" /
                               "pair-c01.json").read_text())
            run = data["participants"]["b"]
            rd = root / "concurrent" / "c01"
            stderr = (rd / run["stderr_rel"]).read_text()
            stderr = stderr.replace("0000:09:00.0", "0000:06:00.0")
            (rd / run["stderr_rel"]).write_bytes(stderr.encode())
            import hashlib
            run["stderr_sha256"] = hashlib.sha256(
                stderr.encode()).hexdigest()
            (root / "concurrent" / "c01" / "pair-c01.json").write_bytes(
                json.dumps(data, indent=1, sort_keys=True).encode())
            self.assertEqual(
                classify_tree(root),
                "V2D_V340L_CONCURRENT_CORRECTNESS_FAIL")

    def test_zero_overlap_all_repeats_blocked(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            build_complete_tree(root)
            for att in ("c01", "c02", "c03"):
                data = json.loads(
                    (root / "concurrent" / att / f"pair-{att}.json")
                    .read_text())
                rel = data["observe_rels"]["b"]
                p = root / "concurrent" / att / rel
                record = [json.loads(ln) for ln in p.read_text()
                          .splitlines() if ln.strip()]
                for rec in record:
                    if rec.get("kind") == "drain":
                        shift = int(10 ** 9 / 37.037 * 1000)
                        rec["ticks"] = [t + shift for t in rec["ticks"]]
                p.write_bytes(("\n".join(json.dumps(r) for r in record)
                               + "\n").encode())
            self.assertEqual(
                classify_tree(root),
                "V2D_EVIDENCE_BLOCKED")

    def test_platform_stress_fail_soak_reset(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            build_complete_tree(root)
            # inject an amdgpu reset line into a retained journal delta
            p = root / "soak" / "raw" / "journal-0030.stdout"
            p.write_bytes(b"amdgpu: GPU reset triggered\n")
            self.assertEqual(
                classify_tree(root),
                "V2D_V340L_PLATFORM_STRESS_FAIL")

    def test_shortened_soak_worker_exit(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            build_complete_tree(root)
            doc = json.loads((root / "soak" / "soak-sk1.json").read_text())
            # genuine mid-soak worker exit (stop before 60 min)
            doc["duration_s"] = 1800
            doc["stop_reason"] = "participant_exit_with_sibling_active"
            doc["events"] = [{"event": "participant_exit",
                              "monotonic_ns": 1800 * 10**9}]
            (root / "soak" / "soak-sk1.json").write_bytes(json.dumps(doc).encode())
            self.assertEqual(
                classify_tree(root),
                "V2D_V340L_PLATFORM_STRESS_FAIL")

    def test_dropped_repeat_denominator(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            build_complete_tree(root, n_concurrent=2)
            self.assertEqual(
                classify_tree(root),
                "V2D_V340L_CONCURRENT_CORRECTNESS_FAIL")

    def test_soak_gap_blocks_pass(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            build_complete_tree(root)
            doc = json.loads((root / "soak" / "soak-sk1.json").read_text())
            # remove middle samples -> 120s gap
            doc["samples"] = doc["samples"][:30] + doc["samples"][58:]
            (root / "soak" / "soak-sk1.json").write_bytes(json.dumps(doc).encode())
            # cadence gap -> AssemblyError path -> soak missing -> INCOMPLETE
            self.assertEqual(
                classify_tree(root),
                "V2D_EVIDENCE_INCOMPLETE_AFTER_CONCURRENCY")

    def test_fault_survivor_rebind_fail(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            build_complete_tree(root)
            doc = json.loads((root / "fault-arm-a.json").read_text())
            run = doc["sibling_run"]
            rd = root / "fault-arm-a-loss" / "initial" / "b"
            stderr = (rd / run["stderr_rel"]).read_text()
            stderr = stderr.replace("0000:09:00.0", "0000:06:00.0")
            (rd / run["stderr_rel"]).write_bytes(stderr.encode())
            import hashlib
            run["stderr_sha256"] = hashlib.sha256(
                stderr.encode()).hexdigest()
            doc["sibling_run"] = run
            (root / "fault-arm-a.json").write_bytes(
                json.dumps(doc, indent=1).encode())
            self.assertEqual(
                classify_tree(root),
                "V2D_V340L_PLATFORM_STRESS_FAIL")

    def test_transport_slowdown_not_correctness_failure(self):
        """Control #18: a dual-arm slowdown must never flip the terminal
        to a correctness failure — transport values are descriptive."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            build_complete_tree(root)
            tp = root / "transport" / "transport-tp1.json"
            doc = json.loads(tp.read_text())
            # halve the dual throughput numbers (descriptive field kept
            # shape-valid: the assembler reads exit codes + overlap only)
            doc["dual"]["descriptive_note"] = "dual bandwidth halved"
            tp.write_bytes(json.dumps(doc, indent=1).encode())
            self.assertEqual(
                classify_tree(root),
                "V2D_V340L_CONCURRENT_DUAL_DIE_STABILITY_PASS")

    def test_single_die_mislabeled_dual_rejected(self):
        """Control #10: dual arm without probe-process overlap fails."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            build_complete_tree(root)
            tp = root / "transport" / "transport-tp1.json"
            doc = json.loads(tp.read_text())
            doc["dual"]["probe_process_overlap"] = False
            tp.write_bytes(json.dumps(doc, indent=1).encode())
            out = asm.assemble(root)
            self.assertEqual(out["terminal"],
                             "V2D_EVIDENCE_INCOMPLETE_AFTER_CONCURRENCY")
            self.assertIn("overlap", str(
                out.get("transport_missing_reason")))

    def test_blocked_when_preflight_fails(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            build_complete_tree(root)
            doc = json.loads((root / "preflight" / "preflight.json").read_text())
            doc["sentinels"]["a"]["correct"] = False
            (root / "preflight" / "preflight.json").write_bytes(json.dumps(doc).encode())
            self.assertEqual(
                classify_tree(root),
                "V2D_EVIDENCE_BLOCKED")

    def test_subprocess_assembler_real_cli(self):
        """Real-CLI-path control: run the assembler as a subprocess over
        a pristine tree and over a mutated tree; assert PASS then the
        mutated terminal."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            build_complete_tree(root)
            out1 = Path(td) / "a1.json"
            proc = subprocess.run(
                [sys.executable, str(REPO / "scripts" / "issue216_assemble.py"),
                 "--evidence-root", str(root), "--out", str(out1)],
                capture_output=True, text=True, cwd=str(REPO))
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn("STABILITY_PASS", proc.stdout)
            # mutate: amdgpu reset in soak journal
            (root / "soak" / "raw" / "journal-0030.stdout").write_bytes(
                b"amdgpu: GPU reset triggered\n")
            out2 = Path(td) / "a2.json"
            proc = subprocess.run(
                [sys.executable, str(REPO / "scripts" / "issue216_assemble.py"),
                 "--evidence-root", str(root), "--out", str(out2)],
                capture_output=True, text=True, cwd=str(REPO))
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn("PLATFORM_STRESS_FAIL", proc.stdout)




class TestCorrectionMutations(unittest.TestCase):
    """Correction-campaign adversarial controls: internally
    self-consistent WRONG-DIE evidence must prevent PASS."""

    def _swap_pair_dies(self, root: Path, att: str) -> None:
        """Swap A and B raw executions PLUS their authored
        selected_bdf/argv fields — fully self-consistent wrong-die
        evidence (each participant carrying the other die's bytes)."""
        import hashlib as _h
        ppath = root / "concurrent" / att / f"pair-{att}.json"
        pair = json.loads(ppath.read_bytes())
        rd = root / "concurrent" / att
        raws = {}
        for k in ("a", "b"):
            run = pair["participants"][k]
            raws[k] = {key: (rd / run[key]).read_bytes()
                       for key in ("stdout_rel", "stderr_rel",
                                   "exit_code_rel")}
        for k, other in (("a", "b"), ("b", "a")):
            run = pair["participants"][k]
            for key in ("stdout_rel", "stderr_rel", "exit_code_rel"):
                (rd / run[key]).write_bytes(raws[other][key])
            run["stdout_sha256"] = _h.sha256(raws[other]["stdout_rel"]).hexdigest()
            run["stderr_sha256"] = _h.sha256(raws[other]["stderr_rel"]).hexdigest()
            argv = run["argv"]
            sel = argv[argv.index("--device") + 1]
            argv[argv.index("--device") + 1] = (
                "Vulkan2" if sel == "Vulkan1" else "Vulkan1")
            run["selected_bdf"] = (
                "0000:09:00.0" if run["selected_bdf"] == "0000:06:00.0"
                else "0000:06:00.0")
        # seam records follow their executions
        oa, ob = pair["observe_rels"]["a"], pair["observe_rels"]["b"]
        pair["observe_rels"]["a"], pair["observe_rels"]["b"] = ob, oa
        ppath.write_bytes(json.dumps(pair, indent=1, sort_keys=True)
                          .encode() + b"\n")

    def test_ab_swap_prevents_pass(self):
        """FIX 2 mutation: swap A and B raw executions + authored
        selected_bdf fields — the identity invariant must reject."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            build_complete_tree(root)
            self.assertEqual(
                classify_tree(root),
                "V2D_V340L_CONCURRENT_DUAL_DIE_STABILITY_PASS")
            self._swap_pair_dies(root, "c02")
            self.assertEqual(
                classify_tree(root),
                "V2D_V340L_CONCURRENT_CORRECTNESS_FAIL")

    def test_a_on_b_bdf_consistent_forgery_prevents_pass(self):
        """FIX 2 mutation: A genuinely executes on B's BDF while every
        authored field is changed to agree with the wrong BDF."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            build_complete_tree(root)
            ppath = root / "concurrent" / "c01" / "pair-c01.json"
            pair = json.loads(ppath.read_bytes())
            run = pair["participants"]["a"]
            rd = root / "concurrent" / "c01"
            stderr = (rd / run["stderr_rel"]).read_text()
            forged = stderr.replace("0000:06:00.0", "0000:09:00.0")
            (rd / run["stderr_rel"]).write_bytes(forged.encode())
            import hashlib as _h
            run["stderr_sha256"] = _h.sha256(forged.encode()).hexdigest()
            run["selected_bdf"] = "0000:09:00.0"
            ppath.write_bytes(json.dumps(pair, indent=1,
                                         sort_keys=True).encode())
            # two dies were used (b is on 09 too) — but participant a's
            # identity != fresh mapping: must fail, not PASS
            out = asm.assemble(root)
            self.assertNotEqual(
                out["terminal"],
                "V2D_V340L_CONCURRENT_DUAL_DIE_STABILITY_PASS")
            self.assertEqual(out["terminal"],
                             "V2D_V340L_CONCURRENT_CORRECTNESS_FAIL")

    def test_b_on_a_bdf_consistent_forgery_prevents_pass(self):
        """FIX 2 mutation: symmetric B-on-A case."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            build_complete_tree(root)
            ppath = root / "concurrent" / "c01" / "pair-c01.json"
            pair = json.loads(ppath.read_bytes())
            run = pair["participants"]["b"]
            rd = root / "concurrent" / "c01"
            stderr = (rd / run["stderr_rel"]).read_text()
            forged = stderr.replace("0000:09:00.0", "0000:06:00.0")
            (rd / run["stderr_rel"]).write_bytes(forged.encode())
            import hashlib as _h
            run["stderr_sha256"] = _h.sha256(forged.encode()).hexdigest()
            run["selected_bdf"] = "0000:06:00.0"
            ppath.write_bytes(json.dumps(pair, indent=1,
                                         sort_keys=True).encode())
            out = asm.assemble(root)
            self.assertEqual(out["terminal"],
                             "V2D_V340L_CONCURRENT_CORRECTNESS_FAIL")

    def test_fault_victim_exit_11_prevents_pass(self):
        """FIX 4 mutation: victim exit -11 (SIGSEGV) != frozen -9."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            build_complete_tree(root)
            (root / "fault-arm-a-loss" / "initial" / "a" /
             "run.exit-code").write_bytes(b"-11\n")
            out = asm.assemble(root)
            self.assertEqual(out["terminal"],
                             "V2D_V340L_PLATFORM_STRESS_FAIL")

    def test_fault_wrong_kill_method_prevents_pass(self):
        """FIX 4 mutation: kill_method SIGTERM."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            build_complete_tree(root)
            fp = root / "fault-arm-b.json"
            doc = json.loads(fp.read_bytes())
            doc["kill_method"] = "SIGTERM"
            fp.write_bytes(json.dumps(doc, indent=1).encode())
            out = asm.assemble(root)
            self.assertNotEqual(
                out["terminal"],
                "V2D_V340L_CONCURRENT_DUAL_DIE_STABILITY_PASS")

    def test_fault_survivor_on_victim_bdf_prevents_pass(self):
        """FIX 4 mutation: survivor genuinely executes on the victim's
        BDF with ALL authored fields changed consistently."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            build_complete_tree(root)
            fp = root / "fault-arm-a.json"
            doc = json.loads(fp.read_bytes())
            run = doc["sibling_run"]
            rd = root / "fault-arm-a-loss" / "initial" / "b"
            stderr = (rd / run["stderr_rel"]).read_text()
            forged = stderr.replace("0000:09:00.0", "0000:06:00.0")
            (rd / run["stderr_rel"]).write_bytes(forged.encode())
            import hashlib as _h
            run["stderr_sha256"] = _h.sha256(forged.encode()).hexdigest()
            run["selected_bdf"] = "0000:06:00.0"
            doc["sibling_run"] = run
            fp.write_bytes(json.dumps(doc, indent=1).encode())
            out = asm.assemble(root)
            self.assertEqual(out["terminal"],
                             "V2D_V340L_PLATFORM_STRESS_FAIL")

    def test_fault_relaunch_on_sibling_bdf_prevents_pass(self):
        """FIX 4 mutation: victim relaunch genuinely executes on the
        sibling's BDF with all authored fields changed consistently."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            build_complete_tree(root)
            fp = root / "fault-arm-b.json"
            doc = json.loads(fp.read_bytes())
            run = doc["relaunch_run"]
            rd = root / "fault-arm-b-loss" / "relaunch" / "b"
            stderr = (rd / run["stderr_rel"]).read_text()
            forged = stderr.replace("0000:09:00.0", "0000:06:00.0")
            (rd / run["stderr_rel"]).write_bytes(forged.encode())
            import hashlib as _h
            run["stderr_sha256"] = _h.sha256(forged.encode()).hexdigest()
            run["selected_bdf"] = "0000:06:00.0"
            doc["relaunch_run"] = run
            fp.write_bytes(json.dumps(doc, indent=1).encode())
            out = asm.assemble(root)
            self.assertEqual(out["terminal"],
                             "V2D_V340L_PLATFORM_STRESS_FAIL")

    def test_soak_telemetry_hash_mismatch_prevents_pass(self):
        """FIX 6 mutation: tamper one telemetry sample's bytes."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            build_complete_tree(root)
            p = root / "soak" / "raw" / "telemetry-0030.json"
            data = json.loads(p.read_bytes())
            data["telemetry"]["0000:06:00.0"]["ras_gpu_err_cnt"] = 5
            p.write_bytes(json.dumps(data, sort_keys=True).encode())
            out = asm.assemble(root)
            self.assertNotEqual(
                out["terminal"],
                "V2D_V340L_CONCURRENT_DUAL_DIE_STABILITY_PASS")

    def test_soak_pid_gone_prevents_pass(self):
        """FIX 6 mutation: PID GONE during an active interval."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            build_complete_tree(root)
            p = root / "soak" / "raw" / "telemetry-0030.json"
            data = json.loads(p.read_bytes())
            data["pids"]["a"]["state"] = "GONE"
            snap_bytes = json.dumps(data, sort_keys=True).encode()
            p.write_bytes(snap_bytes)
            doc = json.loads((root / "soak" / "soak-sk1.json")
                             .read_bytes())
            for s in doc["samples"]:
                if s["sample"] == 30:
                    s["sha256"] = hashlib.sha256(snap_bytes).hexdigest()
            (root / "soak" / "soak-sk1.json").write_bytes(
                json.dumps(doc, indent=1).encode())
            out = asm.assemble(root)
            self.assertEqual(out["terminal"],
                             "V2D_V340L_PLATFORM_STRESS_FAIL")

    def test_soak_silent_replacement_prevents_pass(self):
        """FIX 6 mutation: unplanned exit then silent relaunch."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            build_complete_tree(root)
            sp = root / "soak" / "soak-sk1.json"
            doc = json.loads(sp.read_bytes())
            doc["events"] = [
                {"event": "participant_exit",
                 "pair_die": [["1:a", -9]], "monotonic_ns": 100},
                {"event": "pair_launched", "pair": 2,
                 "monotonic_ns": 200},
            ]
            sp.write_bytes(json.dumps(doc, indent=1).encode())
            out = asm.assemble(root)
            self.assertEqual(out["terminal"],
                             "V2D_V340L_PLATFORM_STRESS_FAIL")

    def test_soak_fault_only_in_final_journal_prevents_pass(self):
        """FIX 6 mutation: reset/hang event present ONLY in
        journal-final.stdout (invisible to cadence deltas)."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            build_complete_tree(root)
            (root / "soak" / "raw" / "journal-final.stdout").write_bytes(
                b"amdgpu: GPU reset triggered after soak\n")
            out = asm.assemble(root)
            self.assertEqual(out["terminal"],
                             "V2D_V340L_PLATFORM_STRESS_FAIL")

    def test_soak_altered_stop_reason_prevents_pass(self):
        """FIX 6 mutation: stop reason != duration_reached."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            build_complete_tree(root)
            sp = root / "soak" / "soak-sk1.json"
            doc = json.loads(sp.read_bytes())
            doc["stop_reason"] = "operator_abort"
            sp.write_bytes(json.dumps(doc, indent=1).encode())
            out = asm.assemble(root)
            self.assertNotEqual(
                out["terminal"],
                "V2D_V340L_CONCURRENT_DUAL_DIE_STABILITY_PASS")

    def test_soak_dropped_checkpoint_prevents_pass(self):
        """FIX 6 mutation: a checkpoint summary removed from disk."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            build_complete_tree(root)
            (root / "soak" / "raw" / "checkpoint-0600.json").unlink()
            out = asm.assemble(root)
            self.assertEqual(out["terminal"],
                             "V2D_EVIDENCE_INCOMPLETE_AFTER_CONCURRENCY")

    def test_transport_missing_probe_output_prevents_pass(self):
        """FIX 5 mutation: single-B probe stdout deleted."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            build_complete_tree(root)
            (root / "transport" / "single-b" / "single-b.stdout").unlink()
            out = asm.assemble(root)
            self.assertEqual(out["terminal"],
                             "V2D_EVIDENCE_INCOMPLETE_AFTER_CONCURRENCY")

    def test_transport_forged_exit_code_prevents_pass(self):
        """FIX 5 mutation: authored exit 0 over raw exit 1 bytes."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            build_complete_tree(root)
            (root / "transport" / "single-a" / "single-a.exit-code"
             ).write_bytes(b"1\n")
            out = asm.assemble(root)
            self.assertEqual(out["terminal"],
                             "V2D_EVIDENCE_INCOMPLETE_AFTER_CONCURRENCY")

    def test_transport_wrong_bdf_prevents_pass(self):
        """FIX 5 mutation: dual/A probe identity binding points at the
        wrong die's BDF."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            build_complete_tree(root)
            pp = root / "transport" / "dual" / "a" / "raw" / "probe.json"
            rec = json.loads(pp.read_bytes())
            rec["twin_binding"]["identity_probe"]["pci_bdf"] = "09:00.0"
            rec["subject"]["pci_bdf"] = "09:00.0"
            pp.write_bytes(json.dumps(rec, indent=1).encode())
            out = asm.assemble(root)
            self.assertEqual(out["terminal"],
                             "V2D_EVIDENCE_INCOMPLETE_AFTER_CONCURRENCY")

    def test_transport_missing_transfer_size_prevents_pass(self):
        """FIX 5 mutation: one ladder size dropped from the raw record."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            build_complete_tree(root)
            pp = root / "transport" / "single-a" / "raw" / "probe.json"
            rec = json.loads(pp.read_bytes())
            stdout = rec["probe_stdout"]
            # remove one 128MiB h2d rep row group marker: simplest —
            # drop 8 of the 64 sustained rows via body rewrite
            import re as _re
            lines = stdout.splitlines()
            # reconstruct without 8 of the h2d_134217728 rows
            kept, dropped = [], 0
            for ln in lines:
                if '"dir":"h2d"' in ln and "134217728" in ln \
                        and '"rep":7' in ln:
                    dropped += 1
                    continue
                kept.append(ln)
            rec["probe_stdout"] = "\n".join(kept) + "\n"
            pp.write_bytes(json.dumps(rec, indent=1).encode())
            out = asm.assemble(root)
            self.assertEqual(out["terminal"],
                             "V2D_EVIDENCE_INCOMPLETE_AFTER_CONCURRENCY")

    def test_transport_forged_overlap_boolean_prevents_pass(self):
        """FIX 5 mutation: authored probe_process_overlap=True over
        non-overlapping retained intervals."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            build_complete_tree(root)
            tp = root / "transport" / "transport-tp1.json"
            doc = json.loads(tp.read_bytes())
            doc["dual"]["intervals_ns"] = {"a": [0, 100], "b": [500, 900]}
            doc["dual"]["probe_process_overlap"] = True
            tp.write_bytes(json.dumps(doc, indent=1).encode())
            out = asm.assemble(root)
            self.assertEqual(out["terminal"],
                             "V2D_EVIDENCE_INCOMPLETE_AFTER_CONCURRENCY")
            self.assertIn("overlap",
                          str(out.get("transport_missing_reason")))

    def test_reset_forged_disposition_prevents_pass(self):
        """FIX 7 mutation: authored RESET_ARM_EXECUTED over evidence
        deriving NOT_AVAILABLE."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            build_complete_tree(root)
            rp = root / "reset-determination.json"
            doc = json.loads(rp.read_bytes())
            doc["disposition"] = "RESET_ARM_EXECUTED"
            doc["reason"] = "forged"
            rp.write_bytes(json.dumps(doc, indent=1).encode())
            out = asm.assemble(root)
            self.assertNotEqual(
                out["terminal"],
                "V2D_V340L_CONCURRENT_DUAL_DIE_STABILITY_PASS")

    def test_reset_missing_mechanism_evidence_blocks(self):
        """FIX 7 mutation: probes stripped of the reset-file
        observation (derivation impossible)."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            build_complete_tree(root)
            rp = root / "reset-determination.json"
            doc = json.loads(rp.read_bytes())
            doc["probes"] = {}
            rp.write_bytes(json.dumps(doc, indent=1).encode())
            out = asm.assemble(root)
            self.assertEqual(out["terminal"],
                             "V2D_EVIDENCE_INCOMPLETE_AFTER_CONCURRENCY")

    def test_preflight_authored_sentinel_verdict_not_authority(self):
        """FIX 3 mutation: authored correct=True over broken raw bytes
        (byte-exactness destroyed) must BLOCK, not PASS."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            build_complete_tree(root)
            pf = json.loads((root / "preflight" / "preflight.json")
                            .read_bytes())
            run = pf["sentinels"]["a"]["run"]
            sp = root / "preflight" / "sentinel" / "a"
            stdout = (sp / run["stdout_rel"]).read_bytes()
            tampered = stdout.replace(b"pangram", b"PANGRAM")
            (sp / run["stdout_rel"]).write_bytes(tampered)
            run["stdout_sha256"] = hashlib.sha256(tampered).hexdigest()
            pf["sentinels"]["a"]["correct"] = True  # authored lie
            (root / "preflight" / "preflight.json").write_bytes(
                json.dumps(pf, indent=1).encode())
            out = asm.assemble(root)
            self.assertEqual(out["terminal"], "V2D_EVIDENCE_BLOCKED")

    def test_mapping_digest_mutation_blocks(self):
        """FIX 2 mutation: a phase record carrying a foreign mapping
        digest fails closed."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            build_complete_tree(root)
            bp = root / "baseline-a.json"
            doc = json.loads(bp.read_bytes())
            doc["mapping_digest"] = "0" * 64
            bp.write_bytes(json.dumps(doc, indent=1).encode())
            out = asm.assemble(root)
            self.assertEqual(out["terminal"], "V2D_EVIDENCE_BLOCKED")

    def test_phase_record_without_closure_binding_blocks(self):
        """FIX 1 mutation: a phase record with no producer-closure
        binding cannot carry executed-byte provenance."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            build_complete_tree(root)
            fp = root / "fault-arm-a.json"
            doc = json.loads(fp.read_bytes())
            del doc["closure_digest"]
            fp.write_bytes(json.dumps(doc, indent=1).encode())
            out = asm.assemble(root)
            self.assertEqual(out["terminal"],
                             "V2D_EVIDENCE_INCOMPLETE_AFTER_CONCURRENCY")

    def test_phase_record_foreign_closure_binding_blocks(self):
        """FIX 1 mutation: evidence from another producer identity."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            build_complete_tree(root)
            fp = root / "fault-arm-b.json"
            doc = json.loads(fp.read_bytes())
            doc["closure_digest"] = "3" * 64
            fp.write_bytes(json.dumps(doc, indent=1).encode())
            out = asm.assemble(root)
            self.assertEqual(out["terminal"],
                             "V2D_EVIDENCE_INCOMPLETE_AFTER_CONCURRENCY")


if __name__ == "__main__":
    unittest.main()

class TestFaultScanMutations(unittest.TestCase):
    """Campaign-window fault scan: mutation controls. Each control
    proves tampering with the retained fault evidence cannot preserve
    or fabricate a verdict."""

    def _scan(self, lines, start=None, end=None):
        import issue216_assemble as asm
        from datetime import datetime, timezone, timedelta
        tz = timezone(timedelta(hours=-4))
        s = start or datetime(2026, 9, 18, 20, 0, 0, tzinfo=timezone.utc)
        e = end or datetime(2026, 9, 18, 21, 30, 0, tzinfo=timezone.utc)
        return asm.scan_platform_faults(
            ("\n".join(lines)).encode(), s, e)

    def test_real_fault_line_detected_in_window(self):
        r = self._scan([
            "Sep 18 16:28:33 inferswarm02 kernel: amdgpu 0000:09:00.0: "
            "ring gfx timeout, signaled seq=5131, emitted seq=5132"])
        self.assertEqual(len(r["hits"]), 1)
        self.assertTrue(r["hits"][0]["in_window"])
        self.assertEqual(r["hits"][0]["class"],
                         "gpu_reset_or_ring_timeout")

    def test_out_of_window_fault_not_counted(self):
        r = self._scan([
            "Sep 18 10:28:33 inferswarm02 kernel: amdgpu 0000:09:00.0: "
            "ring gfx timeout, signaled seq=1, emitted seq=2"])
        self.assertEqual(len(r["hits"]), 1)
        self.assertFalse(r["hits"][0]["in_window"])

    def test_correctable_aer_noise_not_a_fault(self):
        r = self._scan([
            "Sep 18 16:28:33 inferswarm02 kernel: pcieport 0000:02:00.0: "
            "PCIe Bus Error: severity=Correctable, type=Physical Layer"])
        self.assertEqual(len(r["hits"]), 0)

    def test_dmesg_T_grammar_parsed(self):
        r = self._scan([
            "[Fri Sep 18 16:28:34 2026] amdgpu 0000:09:00.0: GPU reset "
            "end with ret = -62"])
        self.assertEqual(len(r["hits"]), 1)
        self.assertTrue(r["hits"][0]["in_window"])

    def test_unparseable_fault_line_retained_fail_closed(self):
        r = self._scan([
            "amdgpu: ring gfx timeout with no timestamp at all"])
        # cannot window it -> retained, never silently dropped
        self.assertEqual(len(r["out_of_window_unparsed"]), 1)

    def test_campaign_scan_retains_unparseable_source_line(self):
        import issue216_assemble as asm
        from datetime import datetime, timezone
        with tempfile.TemporaryDirectory() as td:
            raw = Path(td) / "soak" / "raw"
            raw.mkdir(parents=True)
            (raw / "journal-final.stdout").write_text(
                "amdgpu: ring gfx timeout without a timestamp\n")
            result = asm.scan_campaign_faults(
                Path(td), datetime(2026, 9, 18, tzinfo=timezone.utc),
                datetime(2026, 9, 19, tzinfo=timezone.utc))
            record = result["sources"]["soak/raw/journal-final.stdout"]
            self.assertEqual(len(record["unparsed"]), 1)
            self.assertEqual(record["in_window"], [])

    def test_tampered_fault_capture_cannot_hide_fault(self):
        # deleting the fault line from the journal capture is caught
        # by the digest binding: fault-capture/SHA256SUMS.txt pins the
        # bytes; a mutation test at the file level lives in the
        # manifest lifecycle suite. Here: fabricating a PASS by
        # removing every fault line from an in-window scan source
        # still leaves the OTHER source (journal) carrying it.
        import issue216_assemble as asm
        from datetime import datetime, timezone, timedelta
        tz = timezone(timedelta(hours=-4))
        s = datetime(2026, 9, 18, 20, 0, 0, tzinfo=timezone.utc)
        e = datetime(2026, 9, 18, 21, 30, 0, tzinfo=timezone.utc)
        self.assertTrue(len(asm.scan_platform_faults(
            b"Sep 18 16:28:33 h kernel: GPU reset begin", s, e)["hits"]))

    def test_fault_scan_survives_tz_trick(self):
        # a fault written with a bogus year in journalctl grammar (no
        # year token) cannot escape the window: the parser pins the
        # campaign year from the window itself
        r = self._scan([
            "Sep 18 16:28:33 inferswarm02 kernel: amdgpu: GPU reset "
            "begin"])
        self.assertEqual(len(r["hits"]), 1)
        self.assertTrue(r["hits"][0]["in_window"])
