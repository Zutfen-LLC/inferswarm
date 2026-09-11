"""Issue #137 CORRECTION tests (CPU-only, fail-closed) — PR #138
correction pass: corrected causal intervention (C2 probe family),
reducer v2 requirements/binding, honest per-case partition, history
narrowing, manifest binding, authority pins, and pre-execution
misbinding controls.

Every mutation control mutates exactly ONE thing in a scratch copy of
the evidence dir (or a forged record built from INDEPENDENT values)
and asserts the reducer's derived outcome changes or fails closed.
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
EVIDENCE = (
    REPO / "docs" / "implementation" /
    "r6-successor-dense-full-integration-117" / "evidence" /
    "arm-c-regime4-diagnosis-137"
)
CONCLUSIONS = REPO / "scripts" / "issue137_conclusions.py"
PHASE1 = REPO / "scripts" / "issue137_phase1_inventory.py"
DRIVER = REPO / "scripts" / "issue137_probe_driver.py"
BINDING = REPO / "scripts" / "issue137_binding.py"

sys.path.insert(0, str(REPO / "scripts"))
import issue137_binding  # noqa: E402

DIAGNOSTIC_ONLY = "DIAGNOSTIC_ONLY"
PRODUCER = "924cd22ea081f6d4ed471016faf01d427fc5b0d2"
TERMINAL_LOCALIZED = "ISSUE117_ARM_C_REGIME4_DIAGNOSIS_LOCALIZED"
TERMINAL_PARTIAL = "ISSUE117_ARM_C_REGIME4_DIAGNOSIS_PARTIAL"
TERMINAL_INSUFFICIENT = (
    "ISSUE117_ARM_C_REGIME4_DIAGNOSIS_INSUFFICIENT_EVIDENCE"
)


def run_tool(script: Path, *args: str) -> dict:
    proc = subprocess.run(
        [sys.executable, str(script), *args],
        capture_output=True, text=True, timeout=300, cwd=REPO,
    )
    if proc.returncode != 0:
        raise AssertionError(
            f"{script.name} failed: {proc.stderr[-2000:]}")
    return json.loads(proc.stdout)


def run_reducer(ev: Path, out: Path) -> dict:
    return run_tool(CONCLUSIONS, "--evidence-dir", str(ev),
                    "--out", str(out))


def make_c2_record(*, trials=6, single_value=1509,
                   two_values=None, orders=None, fresh=True,
                   run_id="i137-diag-C2-1799999999") -> dict:
    """Build a valid-looking C2 record from INDEPENDENT values (never
    derived from the real fixture generator)."""
    two_values = two_values or [238631, 1509, 9259, 236777, 111, 222]
    orders = orders or [["single", "two"], ["two", "single"]] * (
        trials // 2)
    observations = []
    for t in range(trials):
        arms = {}
        for arm, value in (
            ("single", single_value),
            ("two", two_values[t % len(two_values)]),
        ):
            arms[arm] = {
                "committed_step0": value,
                "speculative_step1": value,
                "realization_identity": {
                    "stage_pids": [100000 + t * 17 + (0 if arm == "single" else 8),
                                   100001 + t * 17 + (0 if arm == "single" else 8)],
                    "stage_pids_distinct_within": True,
                    "stage_ready_pids": [],
                    "remote_last_stage": {
                        "pid": 200000 + t * 3 + (0 if arm == "single" else 1),
                        "launch_counter": 400 + t * 2 + (0 if arm == "single" else 1),
                        "host": "inferswarm03",
                        "gpu_uuid": issue137_binding.BASELINE_GEOMETRY[
                            "inferswarm03"][0],
                    },
                    "build_chain_pid": 999 + t,
                } if fresh else {
                    "stage_pids": [1, 2],
                    "stage_pids_distinct_within": True,
                    "stage_ready_pids": [],
                    "remote_last_stage": {
                        "pid": 7, "launch_counter": 7,
                        "host": "inferswarm03",
                        "gpu_uuid": issue137_binding.BASELINE_GEOMETRY[
                            "inferswarm03"][0],
                    },
                    "build_chain_pid": 1,
                },
            }
        observations.append({
            "trial": t,
            "launch_order": orders[t % len(orders)],
            "arms": arms,
        })
    return {
        "schema": "inferswarm.issue137.diagnostic-probe/2",
        "classification": DIAGNOSTIC_ONLY,
        "run_id": run_id,
        "probe": "C2",
        "producer": PRODUCER,
        "hostname": "inferswarm01",
        "started_at_ns": 1799999999_000000000,
        "completed_at_ns": 1799999999_900000000,
        "driver": {"sha256": "0" * 64, "invocation": ["x"],
                   "binding_module_sha256": "0" * 64},
        "authority": {
            "baseline_inputs": dict(
                issue137_binding.BASELINE_INPUT_SHA256),
            "producer_modules": dict(
                issue137_binding.PRODUCER_MODULE_SHA256),
            "software": {
                **issue137_binding.BASELINE_SOFTWARE,
                **issue137_binding.BASELINE_TORCH_FLAGS,
            },
            "venv_python": issue137_binding.BASELINE_VENV_PYTHON,
            "geometry": {"inferswarm01": issue137_binding.BASELINE_GEOMETRY[
                "inferswarm01"]},
        },
        "inputs": {
            "fixture_sha256": issue137_binding.BASELINE_INPUT_SHA256[
                "prompt-fixture.json"],
            "chain_plan_sha256": issue137_binding.BASELINE_INPUT_SHA256[
                "chain-plan.json"],
            "environment_sha256": issue137_binding.BASELINE_INPUT_SHA256[
                "environment.json"],
            "accepted_direct_run_sha256": issue137_binding.
            BASELINE_INPUT_SHA256["direct-run.json"],
        },
        "target_call": {
            "case_id": "c109-03-04-003",
            "prompt_len": 53,
            "replay_sha256": "0" * 64,
        },
        "design": {
            "arms": ["single_chunk_64", "two_chunk_32_21"],
            "substrate": "fresh per arm per trial",
            "target_call_position": "first correctness-bearing call",
            "order": "counterbalanced by trial parity",
            "one_variable": "chunk partition",
            "trials": trials,
        },
        "observations": observations,
        "remote_last_stage_launches": [],
    }


class TestBindingModule(unittest.TestCase):
    def test_pins_match_frozen_deployment_baseline(self):
        # self-consistency: stage_chain pin == accepted #133 pin
        self.assertEqual(
            issue137_binding.PRODUCER_MODULE_SHA256[
                "benchmarks/inferswarm_r6/stage_chain.py"],
            issue137_binding.ACCEPTED_133_STAGE_CHAIN_PIN,
        )

    def test_vendored_frozen_stage_chain_matches_pin(self):
        vendored = (
            REPO / "docs" / "implementation" /
            "r6-successor-dense-full-integration-117" / "evidence" /
            "arm-c-retry" / "frozen-source" / "924cd22e" /
            "benchmarks" / "inferswarm_r6" / "stage_chain.py"
        )
        import hashlib
        self.assertEqual(
            hashlib.sha256(vendored.read_bytes()).hexdigest(),
            issue137_binding.ACCEPTED_133_STAGE_CHAIN_PIN,
        )

    def test_verify_producer_checkout_rejects_dirty_tree(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            (repo / "benchmarks").mkdir(parents=True)
            for rel, pin in issue137_binding.PRODUCER_MODULE_SHA256.items():
                f = repo / rel
                f.parent.mkdir(parents=True, exist_ok=True)
                f.write_bytes(b"")
            with self.assertRaises(issue137_binding.BindError):
                issue137_binding.verify_producer_checkout(
                    repo,
                    git_rev_parse=lambda *a: (
                        issue137_binding.PRODUCER if a[0] == "rev-parse"
                        else " M dirty"),
                )

    def test_verify_producer_checkout_rejects_module_hash_drift(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            for rel, pin in issue137_binding.PRODUCER_MODULE_SHA256.items():
                f = repo / rel
                f.parent.mkdir(parents=True, exist_ok=True)
                f.write_bytes(pin.encode())  # wrong bytes
            with self.assertRaises(issue137_binding.BindError):
                issue137_binding.verify_producer_checkout(
                    repo,
                    git_rev_parse=lambda *a: (
                        issue137_binding.PRODUCER if a[0] == "rev-parse"
                        else ""),
                )

    def test_verify_software_rejects_flag_change(self):
        snapshot = {
            **issue137_binding.BASELINE_SOFTWARE,
            **issue137_binding.BASELINE_TORCH_FLAGS,
        }
        snapshot["tf32_matmul"] = not snapshot["tf32_matmul"]
        with self.assertRaises(issue137_binding.BindError):
            issue137_binding.verify_software(
                snapshot, interpreter_path=issue137_binding.
                BASELINE_VENV_PYTHON)

    def test_verify_software_rejects_wrong_interpreter(self):
        snapshot = {
            **issue137_binding.BASELINE_SOFTWARE,
            **issue137_binding.BASELINE_TORCH_FLAGS,
        }
        with self.assertRaises(issue137_binding.BindError):
            issue137_binding.verify_software(
                snapshot, interpreter_path="/usr/bin/python3")

    def test_verify_record_binding_catches_unbound_authority(self):
        record = make_c2_record()
        self.assertEqual(
            issue137_binding.verify_record_binding(record), [])
        record["authority"]["producer_modules"][
            "benchmarks/inferswarm_r6/wire_client.py"] = "f" * 64
        problems = issue137_binding.verify_record_binding(record)
        self.assertTrue(any("wire_client" in p for p in problems))

    def test_verify_realization_freshness_rejects_missing_pids(self):
        obs = make_c2_record()["observations"][0]["arms"]["single"]
        self.assertEqual(
            issue137_binding.verify_realization_freshness(obs), [])
        bad = {"realization_identity": {"stage_pids": [1]}}
        self.assertTrue(
            issue137_binding.verify_realization_freshness(bad))


class TestPhase1InventoryV2(unittest.TestCase):
    def test_authority_pinned_and_categories_complete(self):
        with tempfile.TemporaryDirectory() as td:
            out = run_tool(PHASE1, "--repo", str(REPO),
                           "--out", str(Path(td) / "inv.json"))
            self.assertEqual(out["divergent_cases"], 6)
            record = json.loads((Path(td) / "inv.json").read_text())
            self.assertEqual(
                record["schema"],
                "inferswarm.issue137.phase1-causal-inventory/2")
            inv = record["runtime_lifecycle_inventory"]
            required = [
                "process_creation_runtime_realization_path",
                "process_lifetime_request_history",
                "case_order",
                "runtime_object_reuse",
                "session_reset_lifecycle",
                "speculative_generation_cleanup",
                "kv_state_allocation_reset",
                "realization_epoch_lifecycle",
                "stage_startup_order",
                "cuda_device_runtime_configuration",
                "deterministic_nondeterministic_backend_flags",
                "planner_realizer_side_effects",
                "local_remote_stage_connection_lifecycle",
                "mutable_module_global_class_state",
                "pre_call_state_not_in_comparator",
            ]
            for cat in required:
                self.assertIn(cat, inv)
                row = inv[cat]
                self.assertIn(row["status"],
                              ("derived", "unavailable", "not_retained",
                               "partially_retained"))
                if row["status"] != "derived":
                    self.assertIn("consequence", row)
            self.assertIn("1b83bca", record["authority"]["source"])

    def test_tampered_accepted_input_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            ev_root = ("docs/implementation/"
                       "r6-successor-dense-full-integration-117/evidence")
            # minimal copy: only the files the inventory reads + manifest
            needed = [
                f"{ev_root}/MANIFEST.sha256",
                f"{ev_root}/arm-c-retry/physical-execution/"
                f"equality-reduction.json",
            ]
            for rel in needed:
                dst = repo / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(REPO / rel, dst)
            doc = json.loads(
                (repo / needed[1]).read_text())
            doc["rows"][0]["direct_committed_token_ids"][0] += 1
            (repo / needed[1]).write_text(json.dumps(doc))
            with self.assertRaises(AssertionError):
                run_tool(PHASE1, "--repo", str(repo),
                         "--out", str(Path(td) / "inv.json"))


class TestConclusionsV2(unittest.TestCase):
    """Against the CURRENT (pre-correction-execution) evidence dir the
    reducer must derive PARTIAL — never LOCALIZED without C2, never
    LOCALIZED with unbound records.  With a valid C2 record added and
    the inventory regenerated, LOCALIZED requires every requirement."""

    def _scratch(self, td: str, *, with_c2: bool = False,
                 c2_kwargs=None, keep_real_c2: bool = True) -> Path:
        scratch = Path(td) / "ev"
        shutil.copytree(EVIDENCE, scratch)
        # regenerate inventory v2 into the scratch
        run_tool(PHASE1, "--repo", str(REPO),
                 "--out", str(scratch / "phase1-inventory.json"))
        if not keep_real_c2:
            for c2f in scratch.glob("i137-diag-C2-*.json"):
                c2f.unlink()
        if with_c2:
            rec = make_c2_record(**(c2_kwargs or {}))
            (scratch / f"{rec['run_id']}.json").write_text(
                json.dumps(rec, indent=2, sort_keys=True) + "\n")
        return scratch

    def test_current_evidence_derives_partial_not_localized(self):
        """With the corrected C2 executed and retained, the honest
        derived terminal is PARTIAL: every requirement holds except
        per-case instability (three cases session-stable)."""
        with tempfile.TemporaryDirectory() as td:
            ev = self._scratch(td)
            out = run_reducer(ev, Path(td) / "c.json")
            self.assertEqual(out["terminal"], TERMINAL_PARTIAL)
            self.assertEqual(out["problems"], [])
            self.assertFalse(out["requirements"][
                "every_divergent_case_shows_instability"])
            self.assertTrue(out["requirements"][
                "corrected_chunk_intervention_causal"])
        with tempfile.TemporaryDirectory() as td:
            ev = self._scratch(td, keep_real_c2=False)
            out = run_reducer(ev, Path(td) / "c.json")
            self.assertEqual(out["terminal"], TERMINAL_PARTIAL)
            self.assertIn("missing probe family C2", out["problems"])

    def test_byte_identical_regeneration_no_field_loss(self):
        with tempfile.TemporaryDirectory() as td:
            ev = self._scratch(td)
            out1 = Path(td) / "c1.json"
            out2 = Path(td) / "c2r.json"
            run_reducer(ev, out1)
            run_reducer(ev, out2)
            self.assertEqual(out1.read_bytes(), out2.read_bytes())
            doc = json.loads(out1.read_text())
            for field in ("terminal", "terminal_requirements",
                          "problems", "per_case_causal_families",
                          "history_sensitivity", "causal_factor",
                          "earliest_divergence", "inputs",
                          "informational_observations"):
                self.assertIn(field, doc)

    def test_output_self_reference_impossible(self):
        with tempfile.TemporaryDirectory() as td:
            ev = self._scratch(td)
            out = Path(td) / "c.json"
            run_reducer(ev, out)
            doc = json.loads(out.read_text())
            # inputs map excludes the output file by name
            self.assertNotIn("diagnostic-conclusions.json",
                             doc["inputs"])
            # and a stale output file inside the evidence dir is
            # excluded too
            shutil.copy2(out, ev / "diagnostic-conclusions.json")
            out2 = Path(td) / "c2r.json"
            run_reducer(ev, out2)
            doc2 = json.loads(out2.read_text())
            self.assertNotIn("diagnostic-conclusions.json",
                             doc2["inputs"])

    def test_valid_c2_with_all_varying_evidence_reaches_localized(self):
        """The ladder must reach LOCALIZED when (and only when) every
        requirement holds: valid C2 + every divergent case varying
        in-session.  The three session-stable cases' A records are
        supplemented with forged within-realization variance (values
        from an independent generator), proving LOCALIZED is derived,
        not encoded."""
        with tempfile.TemporaryDirectory() as td:
            ev = self._scratch(td, with_c2=True)
            for case in ("c109-04-03-040", "c109-04-04-024",
                         "c109-04-06-074"):
                matches = sorted(ev.glob("i137-diag-A-*.json"))
                for mp in matches:
                    rec = json.loads(mp.read_text())
                    if rec["target_call"]["case_id"] != case:
                        continue
                    obs = rec["observations"]
                    obs[-1]["committed_step0"] = 777000 + obs[-1][
                        "realization"]
                    mp.write_text(json.dumps(rec))
            out = run_reducer(ev, Path(td) / "c.json")
            self.assertEqual(out["terminal"], TERMINAL_LOCALIZED,
                             out["problems"])
            self.assertEqual(out["problems"], [])
            self.assertTrue(all(out["requirements"].values()))

    def test_each_requirement_independently_controls(self):
        # 1: C2 with deterministic two-arm -> not causal
        with tempfile.TemporaryDirectory() as td:
            ev = self._scratch(td, with_c2=True, keep_real_c2=False,
                               c2_kwargs=dict(two_values=[42] * 6))
            out = run_reducer(ev, Path(td) / "c.json")
            self.assertFalse(out["requirements"][
                "corrected_chunk_intervention_causal"])
            self.assertNotEqual(out["terminal"], TERMINAL_LOCALIZED)
        # 2: fixed (non-counterbalanced) arm order -> problem + downgrade
        with tempfile.TemporaryDirectory() as td:
            ev = self._scratch(td, with_c2=True, keep_real_c2=False,
                               c2_kwargs=dict(
                                   orders=[["single", "two"]] * 6))
            out = run_reducer(ev, Path(td) / "c.json")
            self.assertTrue(any("counterbalanced" in p
                                for p in out["problems"]))
            self.assertNotEqual(out["terminal"], TERMINAL_LOCALIZED)
        # 3: shared substrate between arms (freshness broken)
        with tempfile.TemporaryDirectory() as td:
            ev = self._scratch(td, with_c2=True, keep_real_c2=False,
                               c2_kwargs=dict(fresh=False))
            out = run_reducer(ev, Path(td) / "c.json")
            self.assertTrue(any("freshness" in p for p in out["problems"]))
            self.assertNotEqual(out["terminal"], TERMINAL_LOCALIZED)
        # 4: too few trials
        with tempfile.TemporaryDirectory() as td:
            ev = self._scratch(td, with_c2=True, keep_real_c2=False,
                               c2_kwargs=dict(trials=3))
            out = run_reducer(ev, Path(td) / "c.json")
            self.assertTrue(any("trials" in p for p in out["problems"]))
            self.assertNotEqual(out["terminal"], TERMINAL_LOCALIZED)
        # 5: missing probe family D
        with tempfile.TemporaryDirectory() as td:
            ev = self._scratch(td, with_c2=True, keep_real_c2=False)
            (ev / "i137-diag-D-1789128772.json").unlink()
            out = run_reducer(ev, Path(td) / "c.json")
            self.assertIn("missing probe family D", out["problems"])
            self.assertNotEqual(out["terminal"], TERMINAL_LOCALIZED)

    def test_retired_c_cannot_cause_localized(self):
        """Even with the retired C bytes showing a flip, no C2 means
        no causal claim (C's cumulative fixed-order design)."""
        with tempfile.TemporaryDirectory() as td:
            ev = self._scratch(td, keep_real_c2=False)  # C only, no C2
            out = run_reducer(ev, Path(td) / "c.json")
            self.assertNotEqual(out["terminal"], TERMINAL_LOCALIZED)
            doc = json.loads((Path(td) / "c.json").read_text())
            self.assertIn("no causal claim derivable",
                          doc["causal_factor"]
                          ["corrected_intervention_c2"]["verdict"])
            self.assertIsNotNone(
                doc["informational_observations"]["probe_c_retired"])

    def test_history_mismatch_not_ignored(self):
        with tempfile.TemporaryDirectory() as td:
            ev = self._scratch(td, with_c2=True)
            out = Path(td) / "c.json"
            run_reducer(ev, out)
            doc = json.loads(out.read_text())
            mism = doc["informational_observations"][
                "probe_b_after_divergent_history_mismatches"]
            self.assertTrue(mism, "after_divergent_history mismatch "
                                  "must be retained")
            self.assertIn("NOT NECESSARY", doc["history_sensitivity"]
                          ["conclusion"])
            self.assertNotIn("history not causal",
                             doc["history_sensitivity"]["conclusion"])
            # mutating the mismatch away must not upgrade anything:
            # it is informational, and LOCALIZED already required the
            # narrowed conclusion — verify the narrowed form is
            # load-bearing by breaking probe B entirely
            (ev / "i137-diag-B-1789130217.json").unlink()
            out2 = run_reducer(ev, Path(td) / "c2r.json")
            self.assertNotEqual(out2["terminal"], TERMINAL_LOCALIZED)

    def test_false_layer_ordering_rejected(self):
        """Numeric layer ordering: with after_layer_0 stabilized and
        after_layer_1 varying, the global earliest must be
        after_layer_1 — lexicographic ordering would have picked
        after_layer_0's stale value or after_layer_12/15 first."""
        with tempfile.TemporaryDirectory() as td:
            ev = self._scratch(td, with_c2=True)
            for name in ("manifest-first-stage1-d2b.json",):
                p = ev / name
                man = json.loads(p.read_text())
                stable_value = next(
                    r["sha256"] for r in man["records"]
                    if r["checkpoint"] == "after_layer_0")
                for r in man["records"]:
                    cp = r["checkpoint"]
                    if cp == "after_layer_0":
                        r["sha256"] = stable_value
                    elif cp == "after_layer_1":
                        # vary across steps (uniform would be stable)
                        r["sha256"] = ("deadbeef" if r["step"] % 2 == 0
                                       else "cafebabe") + "0" * 56
                p.write_text(json.dumps(man, indent=2, sort_keys=True)
                             + "\n")
            out = run_reducer(ev, Path(td) / "c.json")
            doc = json.loads((Path(td) / "c.json").read_text())
            self.assertEqual(
                doc["earliest_divergence"]["earliest_varying_checkpoint"],
                "after_layer_1",
                "earliest varying checkpoint must be derived "
                "numerically, globally, deterministically")

    def test_last_manifest_overwrite_impossible(self):
        """Global earliest selection: manifest processing order must
        not let the LAST manifest's varying checkpoint win."""
        with tempfile.TemporaryDirectory() as td:
            ev = self._scratch(td, with_c2=True)
            p = ev / "manifest-middle-stage2-d2b.json"
            man = json.loads(p.read_text())
            for r in man["records"]:
                if r["checkpoint"] == "boundary_recv_hidden":
                    r["sha256"] = "cafebabe" * 8
            p.write_text(json.dumps(man, indent=2, sort_keys=True)
                         + "\n")
            doc = json.loads(
                (Path(td) / "c.json").read_text()) if False else None
            out = run_reducer(ev, Path(td) / "c.json")
            doc = json.loads((Path(td) / "c.json").read_text())
            # earliest must remain after_layer_0 (stage-1), not the
            # middle stage's boundary checkpoint
            self.assertEqual(
                doc["earliest_divergence"]["earliest_varying_checkpoint"],
                "after_layer_0")

    def _mutate_manifest(self, td, mutator):
        ev = self._scratch(td, with_c2=True)
        p = ev / "manifest-first-stage1-d2b.json"
        man = json.loads(p.read_text())
        mutator(man)
        p.write_text(json.dumps(man, indent=2, sort_keys=True) + "\n")
        return ev

    def test_manifest_fail_closed_matrix(self):
        cases = {
            "missing": lambda man: man.update({"records": []}),
            "stale-producer": lambda man: man.update(
                {"producer_sha": "0" * 40}),
            "wrong-schema": lambda man: man.update(
                {"schema": "wrong/1"}),
            "count-inconsistent": lambda man: man.update(
                {"record_count": 999}),
            "wrong-stage-role": lambda man: man.update({"role": "last"}),
        }
        for name, mut in cases.items():
            with tempfile.TemporaryDirectory() as td:
                ev = self._mutate_manifest(td, mut)
                out = run_reducer(ev, Path(td) / "c.json")
                self.assertNotEqual(
                    out["terminal"], TERMINAL_LOCALIZED, name)
                self.assertTrue(out["problems"], name)

    def test_manifest_outside_run_window_rejected(self):
        """A manifest whose captures are entirely OUTSIDE every D2
        run window and not in any capture dir is unbound evidence."""
        with tempfile.TemporaryDirectory() as td:
            ev = self._scratch(td, with_c2=True)
            # strip inline binding AND move timestamps out of window
            for name in ("manifest-first-stage1-d2b.json",
                         "manifest-middle-stage2-d2b.json"):
                p = ev / name
                man = json.loads(p.read_text())
                for r in man["records"]:
                    r["captured_at_unix_ns"] = 1_000_000_000_000000000
                p.write_text(json.dumps(man, indent=2, sort_keys=True)
                             + "\n")
            out = run_reducer(ev, Path(td) / "c.json")
            self.assertTrue(any("not bound to any diagnostic run"
                                in p for p in out["problems"]))
            self.assertNotEqual(out["terminal"], TERMINAL_LOCALIZED)

    def test_altered_accepted_input_hash_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            ev = self._scratch(td, with_c2=True)
            p = ev / "i137-diag-A-1789127822.json"
            rec = json.loads(p.read_text())
            rec["inputs"]["fixture_sha256"] = "f" * 64
            p.write_text(json.dumps(rec))
            out = run_reducer(ev, Path(td) / "c.json")
            self.assertTrue(any("unbound-or-drifted" in p
                                for p in out["problems"]))
            self.assertNotEqual(out["terminal"], TERMINAL_LOCALIZED)

    def test_producer_module_misbinding_in_record_fails(self):
        with tempfile.TemporaryDirectory() as td:
            ev = self._scratch(td, with_c2=True)
            rec = make_c2_record()
            rec["authority"]["producer_modules"][
                "benchmarks/inferswarm_r6/stage_runtime.py"] = "e" * 64
            (ev / f"{rec['run_id']}.json").write_text(
                json.dumps(rec, indent=2, sort_keys=True) + "\n")
            out = run_reducer(ev, Path(td) / "c.json")
            self.assertTrue(any("stage_runtime" in p
                                for p in out["problems"]))
            self.assertNotEqual(out["terminal"], TERMINAL_LOCALIZED)

    def test_empty_or_wildcard_evidence_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            empty = Path(td) / "empty"
            empty.mkdir()
            with self.assertRaises(AssertionError):
                run_reducer(empty, Path(td) / "c.json")
            # unrelated files in the evidence dir are rejected
            ev = self._scratch(td, with_c2=True)
            (ev / " stray-notes.json").write_text("{}")
            with self.assertRaises(AssertionError):
                run_reducer(ev, Path(td) / "c.json")

    def test_per_case_partition_blocks_single_mechanism(self):
        """Three cases do not vary in-session: LOCALIZED requires
        every divergent case to show instability; the partition must
        record them separately and the single-mechanism claim must be
        absent."""
        with tempfile.TemporaryDirectory() as td:
            ev = self._scratch(td, with_c2=True)
            out = run_reducer(ev, Path(td) / "c.json")
            # current evidence: 3/6 vary -> not all -> PARTIAL
            self.assertNotEqual(out["terminal"], TERMINAL_LOCALIZED)
            doc = json.loads((Path(td) / "c.json").read_text())
            part = doc["single_mechanism_or_families"]
            self.assertEqual(
                len(part["session_stable_but_matches_no_accepted_value"]),
                3)
            self.assertIn("NOT established", part["claim"])

    def test_terminal_values_derived_not_encoded(self):
        source = CONCLUSIONS.read_text()
        # ladder is conditional on requirements
        self.assertIn("if all(requirements.values())", source)
        self.assertIn("elif", source)
        # terminal strings are compared, never returned as constants
        self.assertNotIn("return TERMINAL_LOCALIZED", source.replace(
            'terminal = TERMINAL_LOCALIZED', ""))


class TestDriverStaticControls(unittest.TestCase):
    """CPU-only static proofs on the corrected driver (no GPU)."""

    def test_driver_fails_closed_before_execution_on_binding(self):
        source = DRIVER.read_text()
        self.assertIn("verify_producer_checkout", source)
        self.assertIn("verify_baseline_inputs", source)
        self.assertIn("verify_software", source)
        self.assertIn("verify_geometry", source)
        # binding happens before probe dispatch (index order)
        binding_pos = source.index("verify_producer_checkout")
        first_probe_pos = source.index('args.probe == "A"')
        self.assertLess(binding_pos, first_probe_pos)

    def test_c2_design_counterbalanced_fresh_first(self):
        source = DRIVER.read_text()
        self.assertIn('args.probe == "C2"', source)
        self.assertIn("counterbalanced", source)
        # each arm realizes its own fresh substrate
        self.assertIn('for arm in order:', source)
        # C2 exists as a probe choice
        self.assertIn('"C2"', source)

    def test_driver_retains_realization_identity(self):
        source = DRIVER.read_text()
        self.assertIn("realization_identity", source)
        self.assertIn("stage_pids", source)
        self.assertIn("remote_last_stage_launches", source)

    def test_driver_binds_manifests_to_run(self):
        source = DRIVER.read_text()
        self.assertIn("diagnostic_run_binding", source)
        self.assertIn("save_and_bind_captures", source)


if __name__ == "__main__":
    unittest.main()
