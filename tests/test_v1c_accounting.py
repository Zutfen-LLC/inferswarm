"""Issue #161 CPU-only selector-aware successor accounting reducer tests.

Phase 2 contract: before any new physical output, the successor reducer
must (a) reproduce the accepted V1-A accounting semantics field-for-
field from the ACCEPTED retained V1-A raw transcript, (b) reduce the
ACCEPTED retained V1-B Vulkan3 transcript without ambiguity and derive
the three PASS invariants from direct runtime evidence, and (c) fail
closed on every negative control required by Issue #161.

Observed selector literals (Vulkan1/Vulkan3) appear here only as
fixture facts bound to accepted retained evidence, which the issue
explicitly permits; the reducer itself consumes them as authority data.
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import v1c_accounting as v1c  # noqa: E402

V1A_STDERR = ROOT / "docs/investigations/vulkan-v1-a/raw/v1a-amd-a-canonical-01/stderr.txt"
V1A_ACCEPTED = ROOT / "docs/investigations/vulkan-v1-a/evidence/v1a-amd-a-canonical-01/accounting.json"
V1B_STDERR = ROOT / "docs/investigations/vulkan-v1-b/raw/v1b-nv-a-canonical-01/stderr.txt"
V1B_AUTHORITY = json.loads(
    (ROOT / "docs/investigations/vulkan-v1-b/PHYSICAL-AUTHORITY.json").read_text(encoding="utf-8"))

THREE_TUPLE = ("unexplained_persistent_host_mirror_bytes",
               "source_fetches_after_ready", "unplanned_state_movements")


def synthetic_transcript(selector: str, *, extra_device: str | None = None) -> str:
    """Minimal transcript in the runtime's printed accounting grammar.

    Structure mirrors the accepted retained transcripts: pre-ready
    breakdown rows, named buffer lines, ready-state line, post-ready
    final breakdown rows.
    """
    lines = [
        "0.01 I cmn  common_param: device_info:",
        f"0.01 I cmn  common_param:   - {selector} : SomeDevice (8438 MiB, 8122 MiB free)",
    ]
    if extra_device:
        lines.append(f"0.01 I cmn  common_param:   - {extra_device} : OtherDevice (8192 MiB, 8186 MiB free)")
    lines += [
        "0.01 I common_memory_breakdown_print: | memory breakdown [MiB]    | total   free    self   model   context   compute    unaccounted |",
        f"0.01 I common_memory_breakdown_print: |   - {selector} (Dev) |  8438 = 8099 + (3091 =  1834 +    1152 +     104) +       -2752 |",
    ]
    if extra_device:
        lines.append(f"0.01 I common_memory_breakdown_print: |   - {extra_device} (Dev) |  8192 = 8186 + (0 =  0 +  0 +  0) +  0 |")
    lines += [
        "0.01 I common_memory_breakdown_print: |   - Host                  |                  283 =   243 +       0 +      40                |",
        "0.02 I load_tensors:   CPU_Mapped model buffer size =   243.43 MiB",
        f"0.02 I load_tensors:      {selector} model buffer size =  1834.82 MiB",
        "0.12 I llama_context: Vulkan_Host  output buffer size =     0.58 MiB",
        f"0.12 I llama_kv_cache:    {selector} KV buffer size =  1152.00 MiB",
        f"0.12 I sched_reserve:    {selector} compute buffer size =   104.51 MiB",
        "0.12 I sched_reserve: Vulkan_Host compute buffer size =    40.02 MiB",
        "0.12 I slot   operator(): id  0 | task 0 | cached n_tokens = 0, memory_seq_rm [0, end)",
        "0.13 I common_memory_breakdown_print: | memory breakdown [MiB]    | total   free    self   model   context   compute    unaccounted |",
        f"0.13 I common_memory_breakdown_print: |   - {selector} (Dev) |  8438 = 4532 + (3091 =  1834 +    1152 +     104) +         814 |",
        "0.13 I common_memory_breakdown_print: |   - Host                  |                  283 =   243 +       0 +      40                |",
    ]
    return "\n".join(lines) + "\n"


class SelectorValidationTests(unittest.TestCase):
    def test_missing_selector_fails_closed(self):  # negative control 2
        with self.assertRaises(v1c.AccountingError):
            v1c.parse_accounting(synthetic_transcript("Vulkan3"), selector=None)

    def test_malformed_selector_fails_closed(self):  # negative control 3
        for bad in ("", "vulkan3", "Vulkan", "Vulkan 3", "Vulkan-3", "04:00.0",
                    "NVIDIA", "GA104", "  Vulkan3  ", "Vulkan01x", 37):
            with self.assertRaises(v1c.AccountingError, msg=repr(bad)):
                v1c.validate_selector(bad)

    def test_valid_selectors_accepted(self):
        for good in ("Vulkan0", "Vulkan1", "Vulkan3", "Vulkan12"):
            self.assertEqual(v1c.validate_selector(good), good)


class RetainedTranscriptTests(unittest.TestCase):
    def test_v1a_regression_field_by_field_equivalence(self):
        accepted = json.loads(V1A_ACCEPTED.read_text(encoding="utf-8"))
        reproduced = v1c.parse_accounting(V1A_STDERR.read_text(encoding="utf-8"),
                                          selector="Vulkan1")
        for field in set(accepted) - {"schema"}:
            self.assertEqual(reproduced[field], accepted[field], field)
        self.assertEqual(reproduced["schema"], "inferswarm.v0c.materialization-accounting/2")
        self.assertEqual(reproduced["selected_resource"], "Vulkan1")
        self.assertEqual(reproduced["predecessor"]["reducer_sha256"],
                         "db3eff0587204c5ea6aebde34380611dc34a58ba7f772293df425f61f3c546bb")

    def test_v1a_regression_byte_identical_shared_facts(self):
        accepted = json.loads(V1A_ACCEPTED.read_text(encoding="utf-8"))
        reproduced = v1c.parse_accounting(V1A_STDERR.read_text(encoding="utf-8"),
                                          selector="Vulkan1")
        shared = {k: v for k, v in accepted.items() if k != "schema"}
        mine = {k: v for k, v in reproduced.items()
                if k not in ("schema", "selected_resource", "predecessor")}
        self.assertEqual(json.dumps(shared, sort_keys=True, separators=(",", ":")),
                         json.dumps(mine, sort_keys=True, separators=(",", ":")))

    def test_v1b_retained_vulkan3_transcript_reduces_cleanly(self):
        selector = V1B_AUTHORITY["frozen"]["selector"]
        result = v1c.parse_accounting(V1B_STDERR.read_text(encoding="utf-8"),
                                      selector=selector)
        self.assertEqual(selector, "Vulkan3")
        self.assertEqual(result["selected_resource"], "Vulkan3")
        for key in THREE_TUPLE:
            self.assertEqual(result[key], 0, key)
        # facts derived from the retained direct evidence, not asserted
        self.assertEqual(result["device_resident_model_bytes"], 1923948216)
        self.assertEqual(result["device_context_bytes"], 1207959552)
        self.assertEqual(result["device_compute_bytes"], 109586678)

    def test_cross_device_transcript_selects_exactly_the_frozen_selector(self):  # negative control 11
        # A transcript enumerating two Vulkan resources reduces under the
        # frozen selector only, with no cross-device rows mixed in.
        transcript = synthetic_transcript("Vulkan3", extra_device="Vulkan1")
        result = v1c.parse_accounting(transcript, selector="Vulkan3")
        self.assertEqual(result["selected_resource"], "Vulkan3")
        for line in result["raw_lines"]["device_memory_before_after"]:
            self.assertNotIn("Vulkan1", line)
        # the wrong frozen selector on the same transcript fails closed
        with self.assertRaises(v1c.AccountingError):
            v1c.parse_accounting(transcript, selector="Vulkan1")


class NegativeControlTests(unittest.TestCase):
    def test_wrong_selector_on_valid_transcript(self):  # negative control 1
        transcript = synthetic_transcript("Vulkan3")
        with self.assertRaises(v1c.AccountingError):
            v1c.parse_accounting(transcript, selector="Vulkan1")

    def test_duplicate_named_buffer_rows_fail_closed(self):  # negative control 4
        transcript = synthetic_transcript("Vulkan3")
        duplicated = transcript.replace(
            "0.12 I sched_reserve:    Vulkan3 compute buffer size =   104.51 MiB",
            "0.12 I sched_reserve:    Vulkan3 compute buffer size =   104.51 MiB\n"
            "0.12 I sched_reserve:    Vulkan3 compute buffer size =   104.51 MiB")
        with self.assertRaises(v1c.AccountingError):
            v1c.parse_accounting(duplicated, selector="Vulkan3")

    def test_ambiguous_post_ready_selected_device_rows(self):  # negative control 5
        transcript = synthetic_transcript("Vulkan3")
        final = "0.13 I common_memory_breakdown_print: |   - Vulkan3 (Dev) |  8438 = 4532 + (3091 =  1834 +    1152 +     104) +         814 |"
        ambiguous = transcript.replace(final, final + "\n" + final)
        with self.assertRaises(v1c.AccountingError):
            v1c.parse_accounting(ambiguous, selector="Vulkan3")

    def test_missing_final_selected_device_row(self):  # negative control 6
        transcript = synthetic_transcript("Vulkan3")
        final = "0.13 I common_memory_breakdown_print: |   - Vulkan3 (Dev) |  8438 = 4532 + (3091 =  1834 +    1152 +     104) +         814 |"
        # keep the final Host row (so the failure is specifically the
        # missing selected-device row) but drop the final device row
        missing = transcript.replace(final + "\n", "")
        with self.assertRaises(v1c.AccountingError):
            v1c.parse_accounting(missing, selector="Vulkan3")

    def test_contradictory_device_component_totals(self):  # negative control 7
        transcript = synthetic_transcript("Vulkan3")
        final = "0.13 I common_memory_breakdown_print: |   - Vulkan3 (Dev) |  8438 = 4532 + (3091 =  1834 +    1152 +     104) +         814 |"
        bad = "0.13 I common_memory_breakdown_print: |   - Vulkan3 (Dev) |  8438 = 4532 + (3999 =  1834 +    1152 +     104) +         814 |"
        with self.assertRaises(v1c.AccountingError):
            v1c.parse_accounting(transcript.replace(final, bad), selector="Vulkan3")

    def test_contradictory_host_totals(self):  # negative control 8
        transcript = synthetic_transcript("Vulkan3")
        final_host = "0.13 I common_memory_breakdown_print: |   - Host                  |                  283 =   243 +       0 +      40                |"
        bad_host = "0.13 I common_memory_breakdown_print: |   - Host                  |                  999 =   243 +       0 +      40                |"
        with self.assertRaises(v1c.AccountingError):
            v1c.parse_accounting(transcript.replace(final_host, bad_host), selector="Vulkan3")

    def test_unexplained_host_model_mirror_bytes(self):  # negative control 9
        transcript = synthetic_transcript("Vulkan3")
        # raise the Host model component far above the CPU_Mapped label
        final_host = "0.13 I common_memory_breakdown_print: |   - Host                  |                  283 =   243 +       0 +      40                |"
        bad_host = "0.13 I common_memory_breakdown_print: |   - Host                  |                 1283 =  1243 +       0 +      40                |"
        result = v1c.parse_accounting(transcript.replace(final_host, bad_host), selector="Vulkan3")
        self.assertGreater(result["unexplained_persistent_host_mirror_bytes"], 0)

    def test_source_fetch_after_ready_counted(self):  # negative control 10 (a)
        transcript = synthetic_transcript("Vulkan3") + "0.20 I load: fetch remote source layer 5\n"
        result = v1c.parse_accounting(transcript, selector="Vulkan3")
        self.assertEqual(result["source_fetches_after_ready"], 1)

    def test_state_movement_after_ready_counted(self):  # negative control 10 (b)
        transcript = synthetic_transcript("Vulkan3") + "0.20 I sched: copying state to remote resource\n"
        result = v1c.parse_accounting(transcript, selector="Vulkan3")
        self.assertEqual(result["unplanned_state_movements"], 1)

    def test_empty_or_nonstring_stderr_fails_closed(self):
        with self.assertRaises(v1c.AccountingError):
            v1c.parse_accounting("", selector="Vulkan3")
        with self.assertRaises(v1c.AccountingError):
            v1c.parse_accounting(None, selector="Vulkan3")


class GenericSourceAuditTests(unittest.TestCase):
    def test_no_subject_specific_literals_in_reusable_logic(self):
        text = (ROOT / "scripts/v1c_accounting.py").read_text(encoding="utf-8")
        # The reducer module must not encode any observed subject value
        # as selection policy. (The schema-documentation mention of the
        # grammar token class below is not a subject value.)
        for token in ("Vulkan1", "Vulkan3", "AMD", "NVIDIA", "Radeon", "GA104",
                      "04:00.0", "02:00.0", "RTX"):
            self.assertNotIn(token, text, token)
        # The runner is plumbing around accepted components; the same
        # ban applies except it legitimately cites the retained V1-A
        # artifact paths and the accepted first-subject selector label
        # as *authority-data fixtures bound to accepted evidence*.
        runner = (ROOT / "scripts/v1c_runner.py").read_text(encoding="utf-8")
        for token in ("AMD", "NVIDIA", "Radeon", "GA104", "RTX"):
            self.assertNotIn(token, runner, token)

    def test_schema_version_increment_documented(self):
        self.assertEqual(v1c.SCHEMA, "inferswarm.v0c.materialization-accounting/2")
        self.assertEqual(v1c.PREDECESSOR["schema"], "inferswarm.v0c.materialization-accounting/1")


if __name__ == "__main__":
    unittest.main()
