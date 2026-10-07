"""Issue #284 corrected campaign runner: synchronous acceptance-aware STOP gates.

The recovered #280 runner treated HTTP completion as "OK" and never evaluated
frozen acceptance between requests. These tests pin the corrected law: every
frozen per-request acceptance/STOP condition is evaluated BEFORE any subsequent
launch or request; a failing first baseline request yields exactly one executed
request and zero later launches/requests; missing observer evidence fails
closed; peak RSS is retained or its absence blocks admission.
"""
from pathlib import Path
import importlib.util
import json
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/issue280_runner.py"
ADMISSION = Path(__file__).resolve().parents[1] / "tests/test_issue280_admission.py"


def load_admission_builder():
    spec = importlib.util.spec_from_file_location("i280_admission_builder", ADMISSION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_admission = load_admission_builder()


def events_of(raw):
    names = set()
    for line in raw.splitlines():
        if "I280 " in line:
            names.add(json.loads(line.split("I280 ", 1)[1])["event"])
    return names


def load():
    spec = importlib.util.spec_from_file_location("issue280_runner", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RunnerHarness(unittest.TestCase):
    def setUp(self):
        self.m = load()
        self.launches = []
        self.requests = []

    def fake_executor(self, outcomes):
        """outcomes: list (one per planned request) of dicts:
        {text, observer_raw (retained bytes; default: a valid stream for the
         request's arm), observer_events (diagnostic names), peak_rss_bytes,
         launch_error}"""
        m = self.m

        def launch(matrix_row):
            self.launches.append(matrix_row)
            launch_state = {"peak_rss_bytes": None, "observer_events": set()}

            def request(kind):
                self.requests.append((matrix_row["label"], kind))
                if len(self.requests) > len(outcomes):
                    raise AssertionError("executor asked for a request beyond planned budget")
                outcome = outcomes[len(self.requests) - 1]
                raw = outcome.get("observer_raw")
                if raw is None and "observer_events" not in outcome:
                    # default: a mechanically valid retained stream for the arm
                    raw = _admission.build_stream(
                        single_die=matrix_row["arm"] == "A")
                launch_state["observer_raw"] = raw
                launch_state["observer_events"] = set(outcome.get(
                    "observer_events", events_of(raw) if raw else ()))
                launch_state["peak_rss_bytes"] = outcome.get("peak_rss_bytes")
                record = {
                    "launch": matrix_row["label"], "arm": matrix_row["arm"],
                    "prompt": matrix_row["prompt"], "kind": kind,
                    "text": outcome.get("text", ""),
                    "transport_ok": True,  # HTTP completion — NOT acceptance
                    "health_stop": outcome.get("health_stop"),
                }
                return record, launch_state

            return request

        return launch

    def full_evidence(self):
        return {"weight_inventory", "kv_inventory", "recording", "graph_begin",
                "graph_end", "dispatch", "submit", "complete", "vk_graph_begin"}

    def candidate_evidence(self):
        return self.full_evidence() | {"boundary_begin", "boundary_end",
                                       "copy_manifest", "host_leg", "copy_path"}


class ImmediateStopTests(RunnerHarness):
    def test_first_baseline_semantic_failure_stops_after_exactly_one_request(self):
        m = self.m
        outcomes = [
            {"text": "prose with no JSON", "observer_events": self.full_evidence(), "peak_rss_bytes": 1},
        ] * 4
        summary = m.run_campaign(m.MINIMAL_RERUN_MATRIX, self.fake_executor(outcomes))
        self.assertEqual(len(self.requests), 1, "request 2 must never launch")
        self.assertEqual(len(self.launches), 1)
        self.assertEqual(summary["terminal"], "STOP")
        self.assertIn("task", summary["stop_reason"])
        r = summary["requests"]
        self.assertEqual(r[0]["disposition"], "rejected")
        self.assertEqual([x["disposition"] for x in r[1:]], ["not_attempted"] * 3)

    def test_transport_ok_is_not_acceptance(self):
        """A request that completed HTTP 200 with wrong content must STOP."""
        m = self.m
        wrong_value = ('```json\n{"service":"service=search","severity":"low","status":"open"}\n```')
        outcomes = [{"text": wrong_value, "observer_events": self.candidate_evidence(), "peak_rss_bytes": 1}] * 4
        summary = m.run_campaign(m.MINIMAL_RERUN_MATRIX, self.fake_executor(outcomes))
        self.assertEqual(summary["terminal"], "STOP")
        self.assertEqual(len(self.requests), 1)
        self.assertIn("field service", summary["stop_reason"])

    def test_correct_semantics_but_missing_inventory_stops_closed(self):
        m = self.m
        good = '{"service":"payments","severity":"high","status":"resolved"}'
        # name-diagnostics can no longer carry authority: a stream whose
        # event-name set merely lacks inventory names fails mechanically.
        valid = _admission.build_stream(single_die=True)
        stripped = "\n".join(l for l in valid.splitlines()
                             if '"weight_inventory"' not in l
                             and '"kv_inventory"' not in l) + "\n"
        outcomes = [{"text": good, "observer_raw": stripped, "peak_rss_bytes": 1}] * 4
        summary = m.run_campaign(m.MINIMAL_RERUN_MATRIX, self.fake_executor(outcomes))
        self.assertEqual(summary["terminal"], "STOP")
        self.assertIn("observer admission failure", summary["stop_reason"])
        self.assertEqual(len(self.requests), 1)

    def test_missing_compute_events_stop_closed(self):
        m = self.m
        good = '{"service":"payments","severity":"high","status":"resolved"}'
        # streams with no completed compute on the only die fail mechanically
        no_compute = "\n".join(l for l in _admission.build_stream(single_die=True)
                               .splitlines()
                               if '"dispatch"' not in l) + "\n"
        outcomes = [{"text": good, "observer_raw": no_compute, "peak_rss_bytes": 1}] * 4
        summary = m.run_campaign(m.MINIMAL_RERUN_MATRIX, self.fake_executor(outcomes))
        self.assertEqual(summary["terminal"], "STOP")
        self.assertIn("observer admission failure", summary["stop_reason"])

    def test_missing_peak_rss_blocks_admission(self):
        m = self.m
        good = '{"service":"payments","severity":"high","status":"resolved"}'
        outcomes = [{"text": good, "peak_rss_bytes": None}] * 4
        summary = m.run_campaign(m.MINIMAL_RERUN_MATRIX, self.fake_executor(outcomes))
        self.assertEqual(summary["terminal"], "STOP")
        self.assertIn("peak_rss", summary["stop_reason"])
        self.assertEqual(len(self.requests), 1)

    def test_missing_boundary_events_on_candidate_stop_remaining_matrix(self):
        m = self.m
        good = '{"service":"payments","severity":"high","status":"resolved"}'
        # mechanically: no completed cross-die boundary in any candidate graph
        candidate_no_boundary = _admission.build_stream(omit_boundary=True)
        outcomes = [{"text": good, "peak_rss_bytes": 1},
                    {"text": good, "peak_rss_bytes": 1},
                    {"text": good, "observer_raw": candidate_no_boundary,
                     "peak_rss_bytes": 1},
                    {"text": good, "peak_rss_bytes": 1}]
        summary = m.run_campaign(m.MINIMAL_RERUN_MATRIX, self.fake_executor(outcomes))
        self.assertEqual(summary["terminal"], "STOP")
        self.assertIn("boundary", summary["stop_reason"])
        # both baseline requests admitted, candidate cold executed, warm never launched
        self.assertEqual(len(self.requests), 3)
        self.assertEqual([x["disposition"] for x in summary["requests"]],
                         ["accepted", "accepted", "rejected", "not_attempted"])


class PassThroughTests(RunnerHarness):
    def test_fully_successful_minimal_rerun_admits_all_four(self):
        m = self.m
        good = '{"service":"payments","severity":"high","status":"resolved"}'
        # default retained bytes: a mechanically valid stream per arm
        outcomes = [{"text": good, "peak_rss_bytes": 1}] * 4
        summary = m.run_campaign(m.MINIMAL_RERUN_MATRIX, self.fake_executor(outcomes))
        self.assertEqual(summary["terminal"], "COMPLETE")
        self.assertIsNone(summary["stop_reason"])
        self.assertEqual(len(self.launches), 2)
        self.assertEqual(len(self.requests), 4)
        self.assertEqual([x["disposition"] for x in summary["requests"]], ["accepted"] * 4)
        self.assertEqual(summary["matrix_shape"], {"launches": 2, "requests": 4})

    def test_aborted_request_consumes_its_slot_no_replacement(self):
        m = self.m
        good = '{"service":"payments","severity":"high","status":"resolved"}'
        def launch(row):
            seen = []
            def request(kind):
                seen.append(kind)
                if len(seen) == 1:
                    return ({"launch": row["label"], "arm": row["arm"],
                             "prompt": row["prompt"], "kind": kind,
                             "text": "", "transport_ok": False},
                            {"observer_events": set(), "peak_rss_bytes": None})
                return ({"launch": row["label"], "arm": row["arm"],
                         "prompt": row["prompt"], "kind": kind,
                         "text": good, "transport_ok": True},
                        {"observer_events": self.full_evidence(), "peak_rss_bytes": 1})
            return request
        summary = m.run_campaign(m.MINIMAL_RERUN_MATRIX, launch)
        self.assertEqual(summary["terminal"], "STOP")
        self.assertEqual(len(self.requests), 0)  # harness requests list unused here
        self.assertEqual(summary["requests"][0]["disposition"], "aborted")
        # aborted slot is consumed: ordinal 2 (same launch warm) never retried as cold
        kinds = [r["kind"] for r in summary["requests"] if r["launch"] == summary["requests"][0]["launch"]]
        self.assertEqual(summary["requests"][1]["disposition"], "not_attempted")

    def test_matrix_is_exactly_the_minimal_rerun_contract(self):
        m = self.m
        self.assertEqual(len(m.MINIMAL_RERUN_MATRIX), 2)
        self.assertEqual([(row["label"], row["prompt"], row["arm"]) for row in m.MINIMAL_RERUN_MATRIX],
                         [("R1", "P1", "A"), ("R2", "P1", "B")])
        for row in m.MINIMAL_RERUN_MATRIX:
            self.assertEqual(row["requests"], ("cold", "warm"))


class HealthGateTests(RunnerHarness):
    def test_available_health_stop_input_evaluated_before_next_launch(self):
        m = self.m
        good = '{"service":"payments","severity":"high","status":"resolved"}'
        outcomes = [{"text": good, "peak_rss_bytes": 1},
                    {"text": good, "peak_rss_bytes": 1},
                    {"text": good, "peak_rss_bytes": 1,
                     "health_stop": "edge_temp_over_limit"},
                    {"text": good, "peak_rss_bytes": 1}]
        summary = m.run_campaign(m.MINIMAL_RERUN_MATRIX, self.fake_executor(outcomes))
        # health stop arrives with request 3's completion: request 4 must not launch
        self.assertEqual(len(self.requests), 3)
        self.assertEqual(summary["terminal"], "STOP")
        self.assertIn("health", summary["stop_reason"])


if __name__ == "__main__":
    unittest.main()
