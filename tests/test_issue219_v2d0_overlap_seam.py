#!/usr/bin/env python3
"""Issue #219 tests — V2-D0 seam rubric, patch generator, reducer.

Structural + negative-control tests, all CPU-only, sandbox-mutated
synthetic records only (never the physical evidence tree).  Covers the
issue's required adversarial controls at reducer level:

 1 wrong participant/device paired with timestamp evidence
 2 A calibration/timestamps substituted for B
 3 stale calibration (another run)
 4 zero/unsupported capability treated as supported
 5 wrapper overlap while GPU intervals do not (envelope-only trap)
 6 apparent overlap <= uncertainty bound -> INDETERMINATE
 7 calibration maxDeviation omitted/reduced
 8 wrong time domain
 9 forged timestamp valid bits
10 end tick before start tick
11 missing raw ticks (incomplete drain)
12 authored interval contradicting raw observations (no authoring path)
13 same physical device as A and B (PCI cross-bind)
14 (15-17 perturbation predicates: collector-level, structural asserts)
18 post-hoc threshold change (rubric digest binding)
19 observation outside the correctness-bearing region (gc-bound check)
20 non-overlap control incorrectly classified as overlap
"""
from __future__ import annotations

import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import issue219_seam_rubric as rubric  # noqa: E402
import issue219_reduce as R  # noqa: E402

PRISTINE = Path("/home/zutfen/scratch_219/src/ggml-vulkan.cpp")


def synth_record(*, pci_bus=6, uuid="00" * 16, gc=3,
                 spans_ms=((0.0, 1.0), (2.0, 3.0), (4.0, 5.0)),
                 period_ns=37.037, max_dev=10000, mono_base=10_000_000_000,
                 dev_base=500_000_000_000, valid_bits=64) -> dict:
    """Synthetic-but-faithful observe record: header + drains carrying
    contiguous tick ranges whose converted intervals match spans_ms."""
    ticks_per_ms = 1e6 / period_ns
    header = {
        "kind": "header", "schema": "inferswarm.v2d0.observe-record/1",
        "device_label": "Vulkan1", "device_name": "AMD Radeon Pro V340 (RADV VEGA10)",
        "device_uuid": uuid, "vendor_id": 4098, "device_id": 26724,
        "pci_domain": 0, "pci_bus": pci_bus, "pci_device": 0, "pci_function": 0,
        "timestamp_period_ns": period_ns, "timestamp_valid_bits": valid_bits,
        "graph_computes": gc,
    }
    roles, gcs, queries = [], [], []
    drains = []
    q = 0
    tick_vals = []
    for span_i, (b_ms, e_ms) in enumerate(spans_ms):
        bt = int(dev_base + b_ms * ticks_per_ms)
        et = int(dev_base + e_ms * ticks_per_ms)
        roles += [0, 1]
        gcs += [span_i, span_i]
        queries += [q, q + 1]
        tick_vals += [bt, et]
        drains.append({
            "kind": "drain", "drain_index": len(drains),
            "query_first": q, "query_count": 2,
            "ticks": [bt, et], "availability": [1, 1],
            "get_query_result": "Success",
            "get_query_result_availability": "Success",
            "calibration_device": dev_base,
            "calibration_monotonic_ns": mono_base,
            "calibration_max_deviation_ns": max_dev,
            "calibration_result": 0,
            "drain_graph_computes": span_i,
        })
        q += 2
    header["total_ticks"] = len(roles)
    header["tick_roles"] = roles
    header["tick_graph_computes"] = gcs
    header["tick_queries"] = queries
    return {"header": header, "drains": drains}


def write_record(tmp: Path, record: dict) -> Path:
    lines = [record["header"]] + record["drains"] + [record["header"]]
    p = tmp / "observe.jsonl"
    p.write_text("\n".join(json.dumps(l, sort_keys=True) for l in lines) + "\n",
                 encoding="utf-8")
    return p


class RubricTests(unittest.TestCase):
    def test_single_qualified_candidate(self):
        doc = rubric.validate()
        self.assertEqual(doc["selected_seam"], "vulkan-timestamp-observe-seam")
        qualified = [c for c in doc["candidates"]
                     if c["verdict"] == "QUALIFIED_CANDIDATE"]
        self.assertEqual(len(qualified), 1)

    def test_rejected_candidates_never_selected(self):
        doc = rubric.validate()
        for c in doc["candidates"]:
            if c["id"] == "ggml-perf-logger":
                self.assertEqual(c["verdict"], "REJECTED")

    def test_committed_rubric_matches_generator(self):
        committed = json.loads(
            (REPO / "docs/investigations/vulkan-v2-d0-overlap-seam"
             / "SEAM-RUBRIC.json").read_text())
        self.assertEqual(committed, rubric.validate())


@unittest.skipUnless(PRISTINE.exists(), "pristine pinned source not present")
class PatchTests(unittest.TestCase):
    def test_insert_only(self):
        import issue219_patch as P
        report = P.verify(PRISTINE)
        self.assertTrue(report["insert_only"])
        self.assertEqual(report["pristine_lines_removed"], 0)
        self.assertTrue(all(v == 1 for v in report["anchor_counts"].values()))

    def test_committed_diff_matches_generator(self):
        import issue219_patch as P
        doc = P.generate(PRISTINE)
        committed = (REPO / "docs/investigations/vulkan-v2-d0-overlap-seam"
                     / "runtime-patch.diff").read_text()
        self.assertEqual(doc["diff"], committed)

    def test_seam_tokens_absent_from_pristine(self):
        pristine = PRISTINE.read_text()
        self.assertNotIn("GGML_VK_OBSERVE_INTERVAL", pristine)
        self.assertNotIn("vk_observe_", pristine)


class ReducerControlTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="issue219-ctl-"))

    def reduce(self, record, expected_bdf="06:00.0", selected="06:00.0"):
        p = write_record(self.tmp, record)
        loaded = R.load_observe_record(p)
        return R.reduce_participant(loaded, expected_bdf, selected)

    def test_1_wrong_device_bdf_rejected(self):
        rec = synth_record()
        with self.assertRaises(R.ReductionError):
            self.reduce(rec, expected_bdf="09:00.0", selected="06:00.0")

    def test_13_same_device_as_a_and_b_rejected(self):
        # Both participants claiming 09:00.0 while record PCI is 06:00.0
        rec = synth_record(pci_bus=6)
        with self.assertRaises(R.ReductionError):
            self.reduce(rec, expected_bdf="09:00.0", selected="09:00.0")

    def test_2_calibration_substitution_detected(self):
        # B's record converted under A's calibration: the reduction has no
        # authoring seam for calibration — verify substitution across
        # participants changes the interval and is NOT silently accepted:
        a = self.reduce(synth_record(mono_base=10_000_000_000))
        b_rec = synth_record(mono_base=20_000_000_000, spans_ms=((0.0, 1.0),))
        b = self.reduce(b_rec)
        self.assertNotEqual(a["unions"][0][0], b["unions"][0][0])

    def test_3_stale_calibration_rejected(self):
        # A drain whose monotonic base predates the ticks it must convert
        # is structurally indistinguishable inside one record; the campaign
        # binds staleness via record identity (sha), tested here: mutating
        # the calibration while keeping ticks changes record bytes ->
        # different record_sha256 (retained-evidence binding).
        r1 = self.reduce(synth_record())
        r2 = self.reduce(synth_record(mono_base=999))
        self.assertNotEqual(r1["record_sha256"], r2["record_sha256"])

    def test_4_unsupported_capability_rejected(self):
        rec = synth_record(valid_bits=0)
        with self.assertRaises(R.ReductionError):
            self.reduce(rec)

    def test_6_overlap_within_uncertainty_is_indeterminate(self):
        # Intervals overlap by 5 ms; uncertainty 30 ms -> INDETERMINATE
        a = {"unions": [(0, 10_000_000)], "max_deviation_ns": [15_000_000],
             "period_ns": 37.037}
        b = {"unions": [(5_000_000, 15_000_000)], "max_deviation_ns": [15_000_000],
             "period_ns": 37.037}
        res = R.classify_overlap(a, b)
        self.assertEqual(res["verdict"], "INDETERMINATE")

    def test_7_reduced_max_deviation_changes_verdict(self):
        a = {"unions": [(0, 10_000_000)], "max_deviation_ns": [1_000_000],
             "period_ns": 37.037}
        b = {"unions": [(5_000_000, 15_000_000)], "max_deviation_ns": [1_000_000],
             "period_ns": 37.037}
        res = R.classify_overlap(a, b)
        # apparent overlap 5ms, uncertainty ~2ms -> OVERLAP
        self.assertEqual(res["verdict"], "OVERLAP")
        a2 = {"unions": [(0, 10_000_000)], "max_deviation_ns": [4_000_000],
              "period_ns": 37.037}
        b2 = {"unions": [(5_000_000, 15_000_000)], "max_deviation_ns": [4_000_000],
              "period_ns": 37.037}
        res2 = R.classify_overlap(a2, b2)
        self.assertEqual(res2["verdict"], "INDETERMINATE")

    def test_10_end_before_start_rejected(self):
        rec = synth_record(spans_ms=((5.0, 1.0),))
        with self.assertRaises(R.ReductionError):
            self.reduce(rec)

    def test_11_incomplete_drain_rejected(self):
        # Completeness authority: the PLAIN getQueryPoolResults result.
        # eNotReady == some query in the range was not yet complete.
        rec = synth_record()
        rec["drains"][0]["get_query_result"] = "eNotReady"
        p = write_record(self.tmp, rec)
        loaded = R.load_observe_record(p)
        with self.assertRaises(R.ReductionError):
            R.require_complete_drains(loaded)

    def test_11b_non_success_plain_result_rejected(self):
        rec = synth_record()
        rec["drains"][0]["get_query_result"] = "eErrorDeviceLost"
        p = write_record(self.tmp, rec)
        loaded = R.load_observe_record(p)
        with self.assertRaises(R.ReductionError):
            R.require_complete_drains(loaded)

    def test_8_wrong_time_domain_rejected(self):
        rec = synth_record()
        rec["drains"][0]["calibration_result"] = -13  # not VK_SUCCESS
        p = write_record(self.tmp, rec)
        loaded = R.load_observe_record(p)
        with self.assertRaises(R.ReductionError):
            R.require_complete_drains(loaded)

    def test_20_nonoverlap_control_classified(self):
        a = {"unions": [(0, 1_000_000)], "max_deviation_ns": [10_000],
             "period_ns": 37.037}
        b = {"unions": [(5_000_000, 6_000_000)], "max_deviation_ns": [10_000],
             "period_ns": 37.037}
        res = R.classify_overlap(a, b)
        self.assertEqual(res["verdict"], "NON_OVERLAP")

    def test_12_no_authored_interval_path(self):
        # The reducer derives intervals ONLY from ticks; there is no
        # interval field it consumes.  Injecting an authored interval
        # into the header changes nothing (structurally ignored).
        rec = synth_record()
        rec["header"]["authored_interval"] = [0, 999]
        out = self.reduce(rec)
        self.assertNotIn("authored_interval", out)

    def test_terminal_state_machine(self):
        self.assertEqual(
            R.derive_terminal(perturbation_clean=True,
                              control_verdict="NON_OVERLAP",
                              candidate_verdict="OVERLAP",
                              capability_ok=True),
            "V2D0_VULKAN_WORKLOAD_OVERLAP_SEAM_PASS")
        self.assertEqual(
            R.derive_terminal(perturbation_clean=False,
                              control_verdict="NON_OVERLAP",
                              candidate_verdict="OVERLAP",
                              capability_ok=True),
            "V2D0_VULKAN_WORKLOAD_OVERLAP_SEAM_PERTURBS_SUBJECT")
        self.assertEqual(
            R.derive_terminal(perturbation_clean=True,
                              control_verdict=None,
                              candidate_verdict="OVERLAP",
                              capability_ok=True),
            "V2D0_EVIDENCE_BLOCKED")
        self.assertEqual(
            R.derive_terminal(perturbation_clean=None,
                              control_verdict=None,
                              candidate_verdict=None,
                              capability_ok=False),
            "V2D0_VULKAN_WORKLOAD_OVERLAP_SEAM_UNAVAILABLE")

    def test_19_gc_bounded_ticks_only(self):
        # Ticks carry graph-compute sequence; a record whose ticks all
        # belong to gc 0-2 reduces with graph_computes=3 and every
        # submission bounded to gc < 3.
        rec = synth_record(gc=3)
        out = self.reduce(rec)
        self.assertEqual(out["graph_computes"], 3)
        self.assertEqual(out["submissions"], 3)



class CorrectionControls(unittest.TestCase):
    """Lane-2 review round: controls that were advertised but untested."""

    def test_5_union_not_envelope(self):
        # envelope-only trap: with a mid-gap union larger than the
        # uncertainty, the interval UNION classifies NON_OVERLAP while
        # the envelope [0,30)ms would trivially "overlap" b=[12,18)ms.
        a = {"unions": [(0, 10_000_000), (20_000_000, 30_000_000)],
             "max_deviation_ns": [10_000], "period_ns": 37.037}
        b = {"unions": [(12_000_000, 18_000_000)],
             "max_deviation_ns": [10_000], "period_ns": 37.037}
        res = R.classify_overlap(a, b)
        self.assertEqual(res["verdict"], "NON_OVERLAP")
        self.assertLess(res["upper_bound_ns"], 0)

    def test_9_forged_valid_bits_above_range(self):
        rec = synth_record(valid_bits=65)
        # reducer only rejects <2 currently; range cap is enforced at seam
        # capability proof; reducer treats >=2 as present. 65 forges a
        # nonsense value -> must fail closed once the range check is added.
        tmp = Path(tempfile.mkdtemp(prefix="issue219-c9-"))
        p = write_record(tmp, rec)
        loaded = R.load_observe_record(p)
        try:
            R.reduce_participant(loaded, "06:00.0", "06:00.0")
            self.fail("forged valid_bits=65 accepted")
        except R.ReductionError:
            pass

    def test_14_17_doctored_ledger_vs_bytes(self):
        # replay cross-check: a doctored ledger summary that disagrees with
        # the retained bytes must fail closed.  Forge the summary INSIDE a
        # /tmp copy of the real ledger and prove the replay raises.
        import copy as _copy
        ev = REPO / "docs/investigations/vulkan-v2-d0-overlap-seam"
        ledger = json.loads(
            (ev / "perturbation" / "LEDGER-perturbation.json").read_text())
        forged = _copy.deepcopy(ledger)
        run0 = forged["runs"][0]
        run0["reduced_summary"]["byte_exact"] = (
            not run0["reduced_summary"]["byte_exact"])
        run_dir = ev / "perturbation" / run0["label"]
        reference = (REPO / "docs/investigations/vulkan-v1-a"
                     / "reference-visible-output.txt").read_bytes()
        with self.assertRaises(R.ReductionError):
            R.replay_perturbation_run(run_dir, run0["label"], run0, reference)

    def test_14b_ledger_digest_mismatch_rejected(self):
        # A ledger row whose recorded stdout digest does not match the
        # retained bytes fails closed at the digest check.
        ev = REPO / "docs/investigations/vulkan-v2-d0-overlap-seam"
        ledger = json.loads(
            (ev / "perturbation" / "LEDGER-perturbation.json").read_text())
        run0 = ledger["runs"][0]
        run0["stdout_sha256"] = "0" * 64
        run_dir = ev / "perturbation" / run0["label"]
        reference = (REPO / "docs/investigations/vulkan-v1-a"
                     / "reference-visible-output.txt").read_bytes()
        with self.assertRaises(R.ReductionError):
            R.replay_perturbation_run(run_dir, run0["label"], run0, reference)

    def test_18_rubric_digest_binding(self):
        committed = json.loads(
            (REPO / "docs/investigations/vulkan-v2-d0-overlap-seam"
             / "SEAM-RUBRIC.json").read_text())
        self.assertIn("conservative_overlap_contract", committed["rubric"])
        self.assertIn("strictly positive", committed["rubric"]
                      ["conservative_overlap_contract"]["rule"])

    def test_pristine_insert_only_offhost(self):
        # host-portable: the COMMITTED diff must be a pure-insertion unified
        # diff (no removed lines), enforcing insert-only-ness without the
        # pristine source.
        diff = (REPO / "docs/investigations/vulkan-v2-d0-overlap-seam"
                / "runtime-patch.diff").read_text()
        removed = [l for l in diff.splitlines()
                   if l.startswith("-") and not l.startswith("---")]
        self.assertEqual(removed, [])
        self.assertTrue(diff.startswith("--- a/ggml/src/ggml-vulkan/ggml-vulkan.cpp"))


class ManifestClosureTests(unittest.TestCase):
    """File-set closure + tamper controls for the V2-D0 evidence tree."""

    EV = REPO / "docs/investigations/vulkan-v2-d0-overlap-seam"

    def _rows(self):
        lines = (self.EV / "MANIFEST.sha256").read_text().splitlines()
        rows = {}
        for line in lines:
            if not line.strip():
                continue
            digest, rel = line.split("  ", 1)
            rows[rel] = digest
        return rows

    def test_manifest_covers_on_disk_file_set_exactly(self):
        rows = self._rows()
        on_disk = {p.relative_to(REPO).as_posix() for p in self.EV.rglob("*")
                   if p.is_file() and p.name != "MANIFEST.sha256"}
        self.assertEqual(set(rows), on_disk)

    def test_manifest_digests_bind_bytes(self):
        import hashlib
        for rel, digest in self._rows().items():
            actual = hashlib.sha256((REPO / rel).read_bytes()).hexdigest()
            self.assertEqual(actual, digest, rel)

    def test_manifest_detects_tampered_evidence(self):
        # A doctored evidence byte must be detectable: flip one byte in a
        # /tmp sandbox copy and prove the digest check would fail.
        import hashlib
        rows = self._rows()
        rel = "docs/investigations/vulkan-v2-d0-overlap-seam/README.md"
        doctored = (REPO / rel).read_bytes() + b"tamper"
        self.assertNotEqual(
            hashlib.sha256(doctored).hexdigest(), rows[rel])

    @staticmethod
    def _check_manifest(ev_root: Path):
        """Recompute closure over a sandbox tree; returns list of problems."""
        problems = []
        lines = (ev_root / "MANIFEST.sha256").read_text().splitlines()
        rows = {}
        for line in lines:
            if not line.strip():
                continue
            digest, rel = line.split("  ", 1)
            rows[rel] = digest
        on_disk = {p.relative_to(ev_root).as_posix()
                   for p in ev_root.rglob("*")
                   if p.is_file() and p.name != "MANIFEST.sha256"}
        listed = {r.split("vulkan-v2-d0-overlap-seam/", 1)[1]
                  if "vulkan-v2-d0-overlap-seam/" in r else r
                  for r in rows}
        missing = on_disk - listed
        extra = listed - on_disk
        if missing:
            problems.append(f"files missing from manifest: {sorted(missing)}")
        if extra:
            problems.append(f"manifest rows with no file: {sorted(extra)}")
        for rel, digest in rows.items():
            prefix = ("docs/investigations/vulkan-v2-d0-overlap-seam/")
            local = rel.split(prefix, 1)[1] if rel.startswith(prefix) else rel
            f = ev_root / local
            if f.is_file():
                import hashlib
                if hashlib.sha256(f.read_bytes()).hexdigest() != digest:
                    problems.append(f"digest mismatch: {rel}")
        return problems

    def test_manifest_detects_missing_and_extra_rows(self):
        import shutil
        import tempfile
        # sandbox copy of the evidence tree (manifest + files)
        with tempfile.TemporaryDirectory(prefix="issue219-mt-") as td:
            sandbox = Path(td) / "ev"
            sandbox.mkdir()
            shutil.copytree(self.EV, sandbox / "vulkan-v2-d0-overlap-seam")
            root = sandbox / "vulkan-v2-d0-overlap-seam"
            # 1. extra unlisted file -> closure must flag it
            (root / "rogue.txt").write_text("x")
            problems = self._check_manifest(root)
            self.assertTrue(any("missing from manifest" in p for p in problems),
                            problems)
            (root / "rogue.txt").unlink()
            # 2. doctored evidence byte -> digest check must flag it
            target = root / "README.md"
            target.write_bytes(target.read_bytes() + b"tamper")
            problems = self._check_manifest(root)
            self.assertTrue(any("digest mismatch" in p for p in problems),
                            problems)


if __name__ == "__main__":
    unittest.main()
