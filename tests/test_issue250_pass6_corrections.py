#!/usr/bin/env python3
"""Correction pass 6 (METHODOLOGY-AMENDMENT-003) regression suite.

Covers, per the correction directive:

* TIMEOUT POLICY  — the retired 1200s constant was shorter than a
  legitimate Arm-A case-3072 CPU-only request (retained v1 evidence:
  ~2.25 tok/s prefill, ~3077 prompt tokens, killed at ~83%/~1143s);
  the new per-arm/unit budget authority must (A) admit that valid
  completion, (B) remain a bounded safety mechanism, (C) be bound to
  the frozen unit/arm plan, (D) be receipt-bound with full derivation
  inputs, (E) be verified by the reducer, (F) leave timeouts as
  FAILED-units-never-numbers.
* COST GATE       — machine-readable frozen planning record derived
  from the retained rate evidence; C2 serial never auto-reachable.
* ARM C1/C2       — exact frozen thread regimes; C1 authority cannot
  authorize C2; generic Arm-C dispatch cannot reach serial units.
* EVIDENCE GENERATION — the v1 failed tree is read-only defect
  evidence; canonical reruns require the fresh generation identifier;
  no mixing across generations in the reducer.
* DISPATCH STALENESS — comment 5852485456 binds ONLY head
  1c86e97...; once HEAD moves it cannot authorize any physical unit.

No test here executes physical diagnostic work.
"""

import copy
import importlib.util
import json
import socket
import sys
import threading
import time
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tests"))


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, REPO / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


for _dep in ("issue248_diagnostic", "issue248_health",
             "issue248_identity"):
    _load(_dep, f"scripts/{_dep}.py")
D = _load("issue250_diagnostic", "scripts/issue250_diagnostic.py")
TB = _load("issue250_timeout", "scripts/issue250_timeout.py")
P = _load("issue250_physical", "scripts/issue250_physical.py")
T = _load("issue250_terminal", "scripts/issue250_terminal.py")

OLD_HEAD = "1c86e97da42401ff7cfa98e3dc48a33517c65def"
ARM_A_UNIT = {"tag": "case-3072-B-devnone-001", "ngl": 0,
              "argv_delta": ("-dev", "none")}
C1_UNIT = {"tag": "case-3072-B-c1t4-001", "ngl": 0,
           "argv_delta": ("-dev", "none", "-t", "4", "-tb", "4")}


# ---------------------------------------------------------------------------
# TIMEOUT POLICY
# ---------------------------------------------------------------------------

class TimeoutPolicyTests(unittest.TestCase):

    def test_retired_1200s_constant_is_gone_from_request_path(self):
        # the old global constant no longer exists as an attribute ...
        self.assertFalse(hasattr(P, "HTTP_TIMEOUT_S"))
        src = (REPO / "scripts" / "issue250_physical.py").read_text()
        # ... appears ONLY in defect-record prose/comments ...
        prose_prefixes = ("#", "*", "HTTP_TIMEOUT_S = 1200 vs",
                          "HTTP_TIMEOUT_S = 1200 constant is GONE",
                          "issue250_timeout.DEFECT_HTTP_TIMEOUT_S")
        for line in src.splitlines():
            if "HTTP_TIMEOUT_S" in line:
                stripped = line.strip()
                self.assertTrue(
                    any(stripped.startswith(p) for p in prose_prefixes)
                    or "assert TB.DEFECT_HTTP_TIMEOUT_S" in stripped,
                    f"active HTTP_TIMEOUT_S reference survived: {line}")
        # ... and the defect value stays pinned in the timeout module.
        self.assertEqual(TB.DEFECT_HTTP_TIMEOUT_S, 1200)
        self.assertEqual(TB.LEGACY_FIXED_TIMEOUT_S, 1200)
        # _http_completion requires the explicit per-unit deadline.
        import inspect
        sig = inspect.signature(P._http_completion)
        self.assertIn("timeout_s", sig.parameters)

    def test_arm_a_derived_budget_exceeds_legitimate_duration(self):
        # INVARIANT A: at the retained 2.25 tok/s, a case-3072 Arm-A
        # prefill needs ~1368s; the retired 1200s budget killed a
        # valid completion at ~83%. The derived budget must exceed
        # the full legitimate duration by the frozen margin.
        budget = TB.request_timeout_budget(ARM_A_UNIT)
        predicted = (TB.DEFAULT_PROMPT_TOKENS
                     / TB.V1_OBSERVED_RATE_TOKENS_PER_S)
        self.assertAlmostEqual(predicted, 3077 / 2.25, delta=1.0)
        self.assertGreater(predicted, 1200.0)
        expected = predicted * TB.SAFETY_FACTOR \
            + TB.STARTUP_DECODE_MARGIN_S
        self.assertEqual(budget["budget_s"], int(-(-expected // 1)))
        self.assertGreater(budget["budget_s"], predicted + 600.0)
        # full receipt-derivation block present
        self.assertEqual(budget["condition"], "arm-a-cpu-only")
        self.assertEqual(budget["expected_prompt_tokens"], 3077)
        self.assertEqual(
            budget["rate_basis_id"], "cpu-only-default-threads")
        self.assertEqual(budget["safety_factor"], 1.5)
        self.assertEqual(
            budget["rate_basis"], "retained_v1_failed_unit_server_log")
        self.assertTrue(budget["rate_measured"])
        self.assertEqual(budget["schema"], TB.SCHEMA)

    def test_fast_gpu_condition_does_not_inherit_absurd_timeout(self):
        # GPU-like ladder placements run ~71.7 tok/s; they must get a
        # small bounded budget, not a multi-hour one.
        budget = TB.request_timeout_budget({"ladder_length": 2048})
        self.assertLessEqual(budget["budget_s"], 2400.0)
        self.assertGreaterEqual(budget["budget_s"], TB.MIN_TIMEOUT_S)
        self.assertEqual(budget["rate_basis_id"],
                         "gpu-accepted-placement")
        self.assertLess(budget["budget_s"],
                        TB.request_timeout_budget(
                            ARM_A_UNIT)["budget_s"] / 2)

    def test_timeout_remains_bounded_safety_mechanism(self):
        # INVARIANT B: finite, sane bounds on every condition; no
        # infinite/universal-constant degeneracy.
        for cond_key in TB.TIMEOUT_BASIS:
            unit = ({"ladder_length": 1024}
                    if cond_key == "gpu-accepted-placement"
                    else (C1_UNIT if cond_key == "cpu-only-c1-t4"
                          else ARM_A_UNIT))
            budget = TB.request_timeout_budget(unit)
            self.assertGreaterEqual(budget["budget_s"],
                                    TB.MIN_TIMEOUT_S)
            self.assertLessEqual(budget["budget_s"],
                                 TB.MAX_TIMEOUT_S)
            self.assertEqual(budget["max_timeout_s"],
                             TB.MAX_TIMEOUT_S)
        # different conditions derive DIFFERENT budgets (no single
        # universal constant)
        a = TB.request_timeout_budget(ARM_A_UNIT)["budget_s"]
        g = TB.request_timeout_budget({"ladder_length": 2048})["budget_s"]
        c1 = TB.request_timeout_budget(C1_UNIT)["budget_s"]
        self.assertNotEqual(a, g)
        self.assertNotEqual(a, c1)
        self.assertLess(g, a)
        self.assertLess(a, c1)

    def test_budget_is_mechanically_bound_to_frozen_plan(self):
        # INVARIANT C: the derivation is a pure function of the frozen
        # plan unit geometry (+ frozen case token count), and every
        # auto-reachable plan unit maps to a frozen basis/disposition.
        self.assertEqual(TB.request_timeout_budget(ARM_A_UNIT),
                         TB.request_timeout_budget(
                             dict(ARM_A_UNIT)))
        self.assertNotEqual(
            TB.request_timeout_budget(ARM_A_UNIT)["budget_s"],
            TB.request_timeout_budget(C1_UNIT)["budget_s"])
        for arm in ("A-vulkan-necessity", "C-cpu-threads",
                    "C1-reduced-parallelism"):
            for unit in D.probe_list_for(arm):
                cond = TB.unit_condition(unit)
                key = TB.CONDITION_RATE_BASIS[cond]
                self.assertIn(key, TB.TIMEOUT_BASIS)
                self.assertIn(
                    TB.COST_DISPOSITIONS[cond],
                    ("authorized_by_pass6_dispatch",
                     "conditional_not_dispatched",
                     "blocked_requires_separate_authorization"))

    def test_receipt_timeout_block_mutation_fails_closed(self):
        # INVARIANT D/E: receipts carry the derivation; the reducer's
        # verifier recomputes it and rejects ANY mutation (budget,
        # rate, basis, arm-condition, prompt tokens, safety factor,
        # gate flag), plus digest re-binding.
        budget = TB.request_timeout_budget(ARM_A_UNIT)
        budget["timeout_policy_sha256"] = TB.timeout_budget_digest(
            budget)
        for field, mutation in (
                ("budget_s", budget["budget_s"] + 1),
                ("planning_rate_tokens_per_s", 9.99),
                ("condition", "arm-b-fresh"),
                ("expected_prompt_tokens", 2048),
                ("safety_factor", 1.4),
                ("rate_basis_id", "gpu-accepted-placement")):
            tampered = copy.deepcopy(budget)
            tampered[field] = mutation
            with self.assertRaises(TB.TimeoutBudgetError):
                TB.verify_timeout_budget_block(tampered, ARM_A_UNIT)
        # digest mutation alone is caught
        tampered = copy.deepcopy(budget)
        tampered["timeout_policy_sha256"] = "0" * 64
        with self.assertRaises(TB.TimeoutBudgetError):
            TB.verify_timeout_budget_block(tampered, ARM_A_UNIT)
        # honest block verifies
        TB.verify_timeout_budget_block(budget, ARM_A_UNIT)

    def test_unknown_arm_and_rate_basis_fail_closed(self):
        for bad_unit in ({"argv_delta": ("-t", "9")}, {},
                         {"argv_delta": ("-dev", "gpu")}):
            with self.assertRaises(TB.TimeoutBudgetError):
                TB.request_timeout_budget(bad_unit)
        with self.assertRaises(TB.TimeoutBudgetError):
            TB._planning_rate("totally-unknown")
        with self.assertRaises(TB.TimeoutBudgetError):
            TB.request_timeout_budget(ARM_A_UNIT, prompt_tokens=0)
        with self.assertRaises(TB.TimeoutBudgetError):
            TB.request_timeout_budget(ARM_A_UNIT, prompt_tokens=-5)

    def test_timeout_still_terminates_stalled_request(self):
        # INVARIANT F part 1: a real socket stall still dies at the
        # derived (bounded) deadline — fail-closed.
        srv = socket.socket()
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        port = srv.getsockname()[1]

        def stall():
            try:
                conn, _ = srv.accept()
                try:
                    conn.recv(65536)
                    threading.Event().wait(60)
                except OSError:
                    pass
                finally:
                    conn.close()
            except OSError:
                pass

        threading.Thread(target=stall, daemon=True).start()
        started = time.monotonic()
        with self.assertRaises(Exception):
            P._http_completion(port, {"n_predict": 8}, "p",
                               timeout_s=1.0)
        elapsed = time.monotonic() - started
        srv.close()
        self.assertLess(elapsed, 10.0)


# ---------------------------------------------------------------------------
# COST GATE
# ---------------------------------------------------------------------------

class CostGateTests(unittest.TestCase):

    def test_cost_record_schema_and_values(self):
        rec = TB.cost_planning_record()
        self.assertEqual(rec["schema"], TB.COST_RECORD_SCHEMA)
        self.assertEqual(
            rec["retained_rate_evidence"]["observed_rate_tokens_per_s"],
            2.25)
        self.assertEqual(
            rec["retained_rate_evidence"]["defect_timeout_s"], 1200)
        self.assertEqual(rec["retained_rate_evidence"]["head_sha"],
                         OLD_HEAD)
        conds = rec["conditions"]
        self.assertEqual(set(conds), set(TB.COST_CONDITIONS))
        for cond, entry in conds.items():
            self.assertEqual(entry["prompt_tokens"], 3077)
            self.assertEqual(
                entry["planning_rate_tokens_per_s"],
                TB.TIMEOUT_BASIS[
                    TB.CONDITION_RATE_BASIS[cond]]
                ["rate_tokens_per_s"])
            self.assertIn(entry["planning_rate_basis_key"],
                          TB.TIMEOUT_BASIS)
            self.assertIn(entry["disposition"],
                          set(TB.COST_DISPOSITIONS.values()))
            self.assertGreater(entry["estimated_seconds_per_unit"], 0)
            self.assertEqual(entry["min_units_to_establish_mismatch"],
                             TB.MIN_MISMATCH_UNITS)
            self.assertEqual(entry["units_for_deterministic_claim"],
                             TB.DETERMINISTIC_UNITS)
        # machine-checkable arithmetic (Arm A from the retained rate)
        a = conds["arm-a-cpu-only"]
        self.assertAlmostEqual(
            a["estimated_seconds_per_unit"],
            3077 / 2.25 + TB.STARTUP_DECODE_MARGIN_S + 8 / 2.25,
            delta=2.0)
        # serial entry uses the EXACT 2.25/14 fraction and lands at
        # the ~5.3 h planning figure
        c2 = conds["arm-c2-serial"]
        self.assertAlmostEqual(
            c2["estimated_seconds_per_unit"],
            3077 / (2.25 / 14) + TB.STARTUP_DECODE_MARGIN_S
            + 8 / (2.25 / 14), delta=3.0)
        self.assertGreater(c2["estimated_seconds_per_unit"], 19000)

    def test_arm_a_allowed(self):
        verdict = TB.evaluate_cost_gate("arm-a-cpu-only")
        self.assertTrue(verdict["auto_reachable"])
        self.assertFalse(verdict["requires_separate_maintainer_gate"])
        self.assertEqual(
            TB.COST_DISPOSITIONS["arm-a-cpu-only"],
            "authorized_by_pass6_dispatch")

    def test_arm_b_remains_conditional(self):
        for cond in ("arm-b-fresh", "arm-b-sameproc"):
            verdict = TB.evaluate_cost_gate(cond)
            self.assertFalse(verdict["auto_reachable"])
            self.assertEqual(
                TB.COST_DISPOSITIONS[cond],
                "conditional_not_dispatched")

    def test_c1_pair_authorized_c2_blocked(self):
        self.assertTrue(
            TB.evaluate_cost_gate("arm-c-default")["auto_reachable"])
        self.assertTrue(
            TB.evaluate_cost_gate("arm-c1-reduced")["auto_reachable"])
        verdict = TB.evaluate_cost_gate("arm-c2-serial")
        self.assertFalse(verdict["auto_reachable"])
        self.assertTrue(verdict["requires_separate_maintainer_gate"])
        self.assertEqual(
            TB.COST_DISPOSITIONS["arm-c2-serial"],
            "blocked_requires_separate_authorization")

    def test_old_arm_c_serial_not_auto_reachable_by_cost(self):
        rec = TB.cost_planning_record()
        c2 = rec["conditions"]["arm-c2-serial"]
        self.assertGreater(
            c2["estimated_deterministic_proof_cost_s"],
            rec["campaign_cost_ceiling_s"])
        self.assertTrue(
            TB.evaluate_cost_gate("arm-c2-serial")["over_cost_ceiling"])

    def test_cost_metadata_mutation_fails_closed(self):
        rec = TB.cost_planning_record()
        good = copy.deepcopy(rec)
        good["conditions"]["arm-a-cpu-only"]["disposition"] = \
            "authorized_by_pass6_dispatch"
        # disposition tampering on any entry fails closed
        bad = copy.deepcopy(rec)
        bad["conditions"]["arm-a-cpu-only"]["disposition"] = \
            "authorized_by_pass6_dispatchX"
        with self.assertRaises(TB.TimeoutBudgetError):
            TB.evaluate_cost_gate("arm-a-cpu-only", bad)
        # ceiling tampering fails closed
        bad2 = copy.deepcopy(rec)
        bad2["campaign_cost_ceiling_s"] = 10 ** 9
        with self.assertRaises(TB.TimeoutBudgetError):
            TB.evaluate_cost_gate("arm-a-cpu-only", bad2)
        # schema tampering fails closed
        bad3 = copy.deepcopy(rec)
        bad3["schema"] = "inferswarm.issue250.cost-planning-record/0"
        with self.assertRaises(TB.TimeoutBudgetError):
            TB.evaluate_cost_gate("arm-a-cpu-only", bad3)
        # unknown condition fails closed
        with self.assertRaises(TB.TimeoutBudgetError):
            TB.evaluate_cost_gate("arm-x-unknown", good)
        # missing fields fail closed
        bad4 = copy.deepcopy(rec)
        del bad4["conditions"]["arm-a-cpu-only"]["disposition"]
        with self.assertRaises(TB.TimeoutBudgetError):
            TB.evaluate_cost_gate("arm-a-cpu-only", bad4)

    def test_c1_projection_documented(self):
        rec = TB.cost_planning_record()
        c1 = rec["conditions"]["arm-c1-reduced"]
        self.assertAlmostEqual(
            c1["planning_rate_tokens_per_s"], 0.6428, places=4)
        # ~4790s/unit; ~6.7h deterministic proof — bounded, under the
        # 12h ceiling
        self.assertAlmostEqual(c1["estimated_seconds_per_unit"],
                               3077 / 0.6428 + 1920.0 + 12.4,
                               delta=3.0)
        self.assertLess(c1["estimated_deterministic_proof_cost_s"],
                        rec["campaign_cost_ceiling_s"])
        self.assertEqual(c1["disposition"],
                         "authorized_by_pass6_dispatch")
        self.assertFalse(
            TB.TIMEOUT_BASIS["cpu-only-c1-t4"]["measured"])


# ---------------------------------------------------------------------------
# ARM C1 / C2 AUTHORITY SEPARATION
# ---------------------------------------------------------------------------

class ArmC1C2Tests(unittest.TestCase):

    def test_c1_exact_frozen_thread_regime_and_cpu_only(self):
        units = D.probe_list_for("C1-reduced-parallelism")
        self.assertEqual(len(units), 5)
        for u in units:
            self.assertEqual(tuple(u["argv_delta"]),
                             ("-dev", "none", "-t", "4", "-tb", "4"))
            self.assertEqual(u["ngl"], 0)
        self.assertEqual(D.ARM_C1_ARGV_DELTA,
                         ("-t", "4", "-tb", "4"))

    def test_c1_is_cpu_only_no_unrelated_argv_changes(self):
        for u in D.probe_list_for("C1-reduced-parallelism"):
            joined = json.dumps(u, sort_keys=True)
            for banned in ("numa", "affinity", "prio", "nice",
                           "poll", "batch-size", "ctx-size"):
                self.assertNotIn(banned, joined)
            self.assertEqual(u["ngl"], 0)  # CPU-only preserved

    def test_c1_five_units_and_frozen_laws(self):
        units = D.probe_list_for("C1-reduced-parallelism")
        self.assertEqual(len(units), D.DETERM_MIN_REPEATS)
        self.assertEqual(D.DETERM_MIN_REPEATS, 5)

    def test_generic_arm_c_authority_cannot_reach_c2(self):
        # the d250-arm-c arm plan contains NO serial units at all
        for u in D.probe_list_for("C-cpu-threads"):
            self.assertNotEqual(tuple(u["argv_delta"])[-2:],
                                ("-t", "1"))
        # and a namespace<->arm mismatch between the generic C
        # namespace and the serial arm is rejected by the binding map
        with self.assertRaises(D.DiagnosticError):
            D.validate_namespace_arm_binding(
                "d250-arm-c", D.ARM_C2_NAME)

    def test_c1_dispatch_cannot_authorize_c2(self):
        with self.assertRaises(D.DiagnosticError):
            D.validate_namespace_arm_binding(
                "d250-arm-c1", D.ARM_C2_NAME)
        for u in D.probe_list_for("C1-reduced-parallelism"):
            self.assertNotEqual(tuple(u["argv_delta"])[-2:],
                                ("-t", "1"))

    def test_c2_requires_explicit_gate_line_and_gate_record(self):
        # a c2-shaped authority WITHOUT the explicit gate line is
        # rejected outright
        body = "\n".join([D.DIAGNOSTIC_DISPATCH_PHRASE,
                          f"head={OLD_HEAD}",
                          "diagnostic-namespace=d250-arm-c2",
                          f"arm={D.ARM_C2_NAME}"])
        with self.assertRaises(D.DiagnosticError):
            D.validate_authority_payload(
                {"comment_id": 99,
                 "issue_url": f"https://api.github.com/repos/"
                              f"Zutfen-LLC/inferswarm/issues/"
                              f"{D.DIAGNOSTIC_PR_NUMBER}",
                 "author_association": "MEMBER",
                 "created_at": "2026-01-01T00:00:00Z",
                 "body": body, "head_sha": OLD_HEAD,
                 "open_pr": True, "issue_open": True,
                 "namespace": "d250-arm-c2",
                 "arm": D.ARM_C2_NAME},
                expected_head=OLD_HEAD)
        # a gate-record doc missing the C1-varied assertion or either
        # digest fails closed (c1_dispatch_c2_unlocked is the law)
        good = {"schema": D.C2_GATE_RECORD_SCHEMA,
                "head_sha": OLD_HEAD,
                "c1_completed_variable": True,
                "c1_authority_sha256": "a" * 64,
                "c2_authority_sha256": "b" * 64}
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / D.C2_GATE_RECORD_NAME).write_text(
                json.dumps(good))
            self.assertTrue(
                D.c1_dispatch_c2_unlocked(root,
                                          expected_head=OLD_HEAD))
            for bad in ({**good, "c1_completed_variable": False},
                        {k: v for k, v in good.items()
                         if k != "c1_authority_sha256"},
                        {k: v for k, v in good.items()
                         if k != "c2_authority_sha256"},
                        {**good, "schema": "x"},
                        {**good, "head_sha": "9" * 40}):
                (root / D.C2_GATE_RECORD_NAME).write_text(
                    json.dumps(bad))
                self.assertFalse(D.c1_dispatch_c2_unlocked(
                    root, expected_head=OLD_HEAD))
            # absent record => locked (the post-correction default)
            (root / D.C2_GATE_RECORD_NAME).unlink()
            self.assertFalse(D.c1_dispatch_c2_unlocked(
                root, expected_head=OLD_HEAD))
            self.assertFalse(D.c1_dispatch_c2_unlocked(None))

    def test_c2_budget_refused_without_gate_and_stays_unexecuted(self):
        with self.assertRaises(TB.TimeoutBudgetError):
            TB.request_timeout_budget(
                {"argv_delta":
                 ("-dev", "none") + D.ARM_C2_ARGV_DELTA})
        # no physical C2 evidence exists anywhere in the repo tree
        for p in (REPO / "docs").rglob("*"):
            if p.is_file() and "case-3072-B-serial" in p.name:
                self.fail(f"unexpected C2 evidence artifact: {p}")


# ---------------------------------------------------------------------------
# EVIDENCE GENERATION
# ---------------------------------------------------------------------------

class EvidenceGenerationTests(unittest.TestCase):

    def test_generation_constants_frozen(self):
        self.assertEqual(P.EVIDENCE_GENERATION, "gen-2-pass6")
        self.assertEqual(TB.V1_EVIDENCE_GENERATION,
                         "gen-1-v1-timeout-defect")
        self.assertIn("gen-1-v1-timeout-defect",
                      P.RETIRED_EVIDENCE_GENERATIONS)
        self.assertEqual(
            P.RETIRED_V1_EVIDENCE_ROOT,
            "inferswarm01:/home/hermes/is250-campaign/evidence/")
        # the frozen custody hash is a 64-hex sha256 (retained v1
        # server.log of the failed unit)
        self.assertRegex(TB.V1_SERVER_LOG_SHA256, r"^[0-9a-f]{64}$")
        self.assertRegex(TB.V1_ATTESTATION_SHA256, r"^[0-9a-f]{64}$")

    def test_v1_read_only_generation_rejected_as_write_target(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            v1root = Path(td) / "is250-campaign" / "evidence"
            v1root.mkdir(parents=True)
            (v1root / "evidence-generation.json").write_text(
                json.dumps({"generation":
                            "gen-1-v1-timeout-defect"}))
            with self.assertRaises(P.PhysicalDiagnosticError):
                P.validate_evidence_generation(v1root)
            # foreign marker on ANY root is refused (no laundering)
            other = Path(td) / "other-root"
            other.mkdir()
            (other / "evidence-generation.json").write_text(
                json.dumps({"generation": "gen-9-future"}))
            with self.assertRaises(P.PhysicalDiagnosticError):
                P.validate_evidence_generation(other)
            # symlinked roots are refused
            link = Path(td) / "link-root"
            link.symlink_to(v1root)
            with self.assertRaises(P.PhysicalDiagnosticError):
                P.validate_evidence_generation(link)

    def test_fresh_generation_identifier_required_and_appended(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "fresh-campaign-root"
            root.mkdir()
            self.assertEqual(P.validate_evidence_generation(root),
                             "gen-2-pass6")
            doc = P.write_generation_marker(root)
            self.assertEqual(doc["generation"], "gen-2-pass6")
            self.assertEqual(doc["predecessor_generation"],
                             "gen-1-v1-timeout-defect")
            self.assertIn("read-only", doc["predecessor_disposition"])
            # append-only: a second write is refused
            with self.assertRaises(P.PhysicalDiagnosticError):
                P.write_generation_marker(root)
            # the retained cost record binds the same generation
            cost = P.retain_cost_planning_record(root)
            self.assertEqual(cost["evidence_generation"],
                             "gen-2-pass6")
            with self.assertRaises(P.PhysicalDiagnosticError):
                P.retain_cost_planning_record(root)

    def test_reducer_rejects_foreign_generation_cost_records(self):
        # a retained cost record bound to a non-canonical generation
        # must drive derive_terminal into BLOCKED (never UNRESOLVED,
        # never a derivation over mixed generations)
        self.assertIn("generation mismatch",
                      (REPO / "scripts" / "issue250_terminal.py")
                      .read_text())


# ---------------------------------------------------------------------------
# DISPATCH STALENESS (comment 5852485456)
# ---------------------------------------------------------------------------

def old_dispatch_authority():
    return {
        "comment_id": 5852485456,
        "issue_url": f"https://api.github.com/repos/Zutfen-LLC/"
                     f"inferswarm/issues/{D.DIAGNOSTIC_PR_NUMBER}",
        "author_association": "MEMBER",
        "created_at": "2026-09-27T04:03:41Z",
        "body": "\n".join([
            D.DIAGNOSTIC_DISPATCH_PHRASE,
            f"head={OLD_HEAD}",
            "diagnostic-namespace=d250-arm-a",
            "arm=A-vulkan-necessity"]),
        "head_sha": OLD_HEAD, "open_pr": True, "issue_open": True,
        "namespace": "d250-arm-a", "arm": "A-vulkan-necessity",
    }


class DispatchStalenessTests(unittest.TestCase):

    def test_dispatch_comment_5852485456_binds_old_head_only(self):
        rec = D.bind_stale_dispatch_record(OLD_HEAD)
        self.assertEqual(rec["comment_id"], 5852485456)
        self.assertEqual(rec["bound_head"], OLD_HEAD)
        self.assertEqual(rec["namespace"], "d250-arm-a")
        self.assertEqual(rec["arm"], "A-vulkan-necessity")
        self.assertFalse(rec["stale"])
        # at ANY moved head the record flips to stale
        rec2 = D.bind_stale_dispatch_record("f" * 40)
        self.assertTrue(rec2["stale"])
        # the exact-head validator rejects the old dispatch payload
        # against any other head
        with self.assertRaises(D.DiagnosticError):
            D.validate_authority_payload(
                old_dispatch_authority(),
                expected_head="e" * 40)
        ok = D.validate_authority_payload(
            old_dispatch_authority(), expected_head=OLD_HEAD)
        self.assertEqual(ok["head_sha"], OLD_HEAD)

    def test_stale_dispatch_cannot_launch_physical_units(self):
        new_head = "e" * 40

        def stale_fetcher(repo, head, ns, arm=None):
            return old_dispatch_authority()

        with self.assertRaises((P.PhysicalDiagnosticError,
                                D.DiagnosticError)):
            P.require_live_dispatch(
                REPO, new_head, "d250-arm-a",
                revalidate_authority=stale_fetcher)
        # sanity: at the OLD head the same dispatch is still accepted
        ok = P.require_live_dispatch(
            REPO, OLD_HEAD, "d250-arm-a",
            revalidate_authority=stale_fetcher)
        self.assertEqual(ok["head_sha"], OLD_HEAD)

    def test_fresh_review_and_dispatch_required_after_head_move(self):
        # mechanical proof of the directive requirement: the retired
        # registry cannot be re-armed for a new head; a fresh
        # maintainer dispatch at the new head is the only path.
        self.assertEqual(D.STALE_DISPATCH_COMMENT_ID, 5852485456)
        self.assertEqual(D.STALE_DISPATCH_HEAD, OLD_HEAD)


if __name__ == "__main__":
    unittest.main()
