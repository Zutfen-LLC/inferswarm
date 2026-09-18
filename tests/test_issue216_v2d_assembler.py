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
            "authority_digest": __AUTH__, "mapping_digest": "M",
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
    for cps in range(600, soak_duration_s + 1, 600):
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
        "authority_digest": __AUTH__, "mapping_digest": "M",
        "closure_digest": __BIND__["closure_digest"],
        "producer_head": __BIND__["producer_head"],
    }, indent=1).encode())
    return {"root": root, "attempts": attempts}


def _checkpoint_pair(root: Path, cp_dir: Path, tag: str) -> dict:
    pair = {"attempt_id": tag, "phase": "soak-checkpoint",
            "participants": {}, "observe_rels": {},
            "wrapper_intervals_ns": {"a": [0, 1], "b": [0, 1]},
            "authority_digest": __AUTH__, "mapping_digest": "M",
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
        "authority_digest": __AUTH__, "mapping_digest": "M",
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


if __name__ == "__main__":
    unittest.main()
