from __future__ import annotations

import hashlib
import json
import math
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from issue74_methodology import CONTRACT_ID, canonical_json_bytes, sha256_bytes  # noqa: E402
from select_issue76_margin_stress_v2 import (  # noqa: E402
    MARGIN_DEFINITION,
    MIN_ELIGIBLE,
    select,
)

V1 = ROOT / "docs/qualification/gemma4-12b-it-v1/manifests"
V2 = ROOT / "docs/qualification/gemma4-12b-it-v2/manifests"

FROZEN_V2_POOL_SHA256 = "533b32857721b3f99243e5695bc18b24960cbd3c80692d626154907d6ecbd7c9"


def load(base: Path, name: str) -> dict:
    return json.loads((base / name).read_text())


def sha_canonical(value: dict) -> str:
    return sha256_bytes(canonical_json_bytes(value))


def make_commitment(pool: dict, **overrides) -> dict:
    commitment = load(V2, "margin-stress-selection-commitment.json")
    commitment = dict(commitment)
    commitment["candidate_pool_sha256"] = sha_canonical(pool)
    for key, value in overrides.items():
        commitment[key] = value
    return commitment


def make_margins(pool: dict, margin_by_id: dict[str, float]) -> dict:
    cases = []
    for case in pool["cases"]:
        margin = margin_by_id.get(case["case_id"], 1.0)
        cases.append({
            "case_id": case["case_id"],
            "case_sha256": case["case_sha256"],
            "top1_margin_hex": margin.hex(),
            "steps_nonpositive": 0 if margin > 0 else 1,
        })
    return {
        "schema": "inferswarm.issue76.reference-margin-summary/2",
        "contract_id": CONTRACT_ID,
        "margin_definition": MARGIN_DEFINITION,
        "stress_pool_sha256": sha_canonical(pool),
        "cases": cases,
    }


class TestV2StressPoolFrozen(unittest.TestCase):
    def test_pool_hash_is_frozen(self):
        raw = (V2 / "margin-stress-pool.json").read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), FROZEN_V2_POOL_SHA256)

    def test_pool_is_canonical_json(self):
        pool = load(V2, "margin-stress-pool.json")
        self.assertEqual(canonical_json_bytes(pool), (V2 / "margin-stress-pool.json").read_bytes())

    def test_pool_has_48_cases_2_per_cell(self):
        pool = load(V2, "margin-stress-pool.json")
        self.assertEqual(len(pool["cases"]), 48)
        cells = {(c["content_class"], tuple(c["length_regime"])) for c in pool["cases"]}
        self.assertEqual(len(cells), 24)
        counts: dict[tuple, int] = {}
        for c in pool["cases"]:
            key = (c["content_class"], tuple(c["length_regime"]))
            counts[key] = counts.get(key, 0) + 1
        self.assertEqual(set(counts.values()), {2})
        for c in pool["cases"]:
            self.assertTrue(c["case_id"].startswith("p76-"))

    def test_pool_is_disjoint_from_v1_pool_and_calibration(self):
        pool = load(V2, "margin-stress-pool.json")
        v1_pool = load(V1, "margin-stress-pool.json")
        calibration = load(V1, "calibration-corpus.json")
        v2_ids = {tuple(c["token_ids"]) for c in pool["cases"]}
        self.assertFalse(v2_ids & {tuple(c["token_ids"]) for c in v1_pool["cases"]})
        self.assertFalse(v2_ids & {tuple(c["token_ids"]) for c in calibration["cases"]})

    def test_margin_definition_is_unchanged_min_over_8(self):
        self.assertEqual(
            MARGIN_DEFINITION,
            "min over all 8 greedy steps of fp32(top1_logit - top2_logit)",
        )


class TestV2SelectionEligibility(unittest.TestCase):
    def setUp(self):
        self.pool = load(V2, "margin-stress-pool.json")
        self.commitment = make_commitment(self.pool)

    def test_zero_margin_case_is_ineligible_not_fatal(self):
        ids = [c["case_id"] for c in self.pool["cases"]]
        margins = {cid: 1.0 for cid in ids}
        margins[ids[0]] = 0.0  # exact tie — v1 selector aborted here
        margins[ids[1]] = -0.5  # nonpositive
        result = select(self.pool, make_margins(self.pool, margins), self.commitment)
        self.assertEqual(result["selected_count"], 8)
        self.assertEqual(result["ineligible_case_count"], 2)
        self.assertEqual(result["eligible_case_count"], 46)
        groups = [s["selection_group"] for s in result["selected"]]
        self.assertEqual(groups.count("four-smallest-positive"), 4)
        self.assertEqual(groups.count("four-largest-positive"), 4)
        chosen_ids = {s["case"]["case_id"] for s in result["selected"]}
        self.assertNotIn(ids[0], chosen_ids)
        self.assertNotIn(ids[1], chosen_ids)

    def test_five_zero_margin_cases_still_yield_valid_selection(self):
        # mirrors the observed v1 stop condition (5/48 exact-zero margins)
        ids = [c["case_id"] for c in self.pool["cases"]]
        margins = {cid: 0.5 + 0.01 * i for i, cid in enumerate(ids)}
        for cid in ids[:5]:
            margins[cid] = 0.0
        result = select(self.pool, make_margins(self.pool, margins), self.commitment)
        self.assertEqual(result["eligible_case_count"], 43)
        self.assertEqual(result["selected_count"], 8)
        self.assertEqual(len(result["ineligible_cases"]), 5)

    def test_fewer_than_8_eligible_fails_closed(self):
        ids = [c["case_id"] for c in self.pool["cases"]]
        margins = {cid: 1.0 for cid in ids}
        for cid in ids[:41]:
            margins[cid] = 0.0
        with self.assertRaises(ValueError):
            select(self.pool, make_margins(self.pool, margins), self.commitment)

    def test_selection_is_deterministic_and_margin_ordered(self):
        ids = sorted(c["case_id"] for c in self.pool["cases"])
        margins = {cid: 0.1 * (i % 10) + 0.05 for i, cid in enumerate(ids)}
        r1 = select(self.pool, make_margins(self.pool, margins), self.commitment)
        r2 = select(self.pool, make_margins(self.pool, margins), self.commitment)
        self.assertEqual(canonical_json_bytes(r1), canonical_json_bytes(r2))
        smallest = [s for s in r1["selected"] if s["selection_group"] == "four-smallest-positive"]
        largest = [s for s in r1["selected"] if s["selection_group"] == "four-largest-positive"]
        vals = [float.fromhex(s["reference_top1_margin_hex"]) for s in smallest]
        self.assertEqual(vals, sorted(vals))
        vals = [float.fromhex(s["reference_top1_margin_hex"]) for s in largest]
        self.assertEqual(vals, sorted(vals))
        eligible_sorted = sorted((margins[cid], cid) for cid in ids)
        self.assertEqual(
            {c for _, c in eligible_sorted[:4]} | {c for _, c in eligible_sorted[-4:]},
            {s["case"]["case_id"] for s in r1["selected"]},
        )

    def test_margin_definition_drift_is_rejected(self):
        ids = [c["case_id"] for c in self.pool["cases"]]
        margins = make_margins(self.pool, {cid: 1.0 for cid in ids})
        margins["margin_definition"] = "max over all 8 greedy steps"
        with self.assertRaises(ValueError):
            select(self.pool, margins, self.commitment)

    def test_v1_margin_definition_switch_attempts_rejected(self):
        for wrong in ("step 0", "mean over 8 steps", "median over 8 steps", "min over capture positions"):
            commitment = make_commitment(self.pool, margin_definition=wrong)
            ids = [c["case_id"] for c in self.pool["cases"]]
            with self.assertRaises(ValueError, msg=wrong):
                select(self.pool, make_margins(self.pool, {cid: 1.0 for cid in ids}), commitment)

    def test_commitment_must_bind_exact_pool(self):
        ids = [c["case_id"] for c in self.pool["cases"]]
        mutated = json.loads(json.dumps(self.pool))
        mutated["cases"][0]["prompt_text"] = "tampered"
        commitment = make_commitment(mutated)
        with self.assertRaises(ValueError):
            select(self.pool, make_margins(self.pool, {cid: 1.0 for cid in ids}), commitment)

    def test_commitment_must_bind_selector_program_hash(self):
        ids = [c["case_id"] for c in self.pool["cases"]]
        commitment = make_commitment(self.pool, selection_program_sha256="0" * 64)
        with self.assertRaises(ValueError):
            select(self.pool, make_margins(self.pool, {cid: 1.0 for cid in ids}), commitment)

    def test_v1_pool_schema_rejected(self):
        v1_pool = load(V1, "margin-stress-pool.json")
        ids = [c["case_id"] for c in self.pool["cases"]]
        with self.assertRaises(ValueError):
            select(v1_pool, make_margins(self.pool, {cid: 1.0 for cid in ids}), self.commitment)


class TestV1ArtifactsUntouched(unittest.TestCase):
    def test_v1_pool_and_commitment_hashes_unchanged(self):
        v1_pool_raw = (V1 / "margin-stress-pool.json").read_bytes()
        self.assertEqual(
            hashlib.sha256(v1_pool_raw).hexdigest(),
            "5958d50957628cf3c52fde5f1f1e59ad982bfa2a1010dd9ed25f2ba53d2a1d92",
        )
        commitment = json.loads((V1 / "margin-stress-selection-commitment.json").read_bytes())
        self.assertEqual(
            commitment["candidate_pool_sha256"],
            "5958d50957628cf3c52fde5f1f1e59ad982bfa2a1010dd9ed25f2ba53d2a1d92",
        )
        self.assertEqual(commitment["state"], "COMMITTED_BEFORE_MATCHED_REFERENCE_EXECUTION")

    def test_v1_holdout_ciphertext_unchanged(self):
        holdout = ROOT / "docs/qualification/gemma4-12b-it-v1/sealed/holdout.cms"
        self.assertEqual(
            hashlib.sha256(holdout.read_bytes()).hexdigest(),
            "23311c5514b2561c66a2ecd0c9cfa25c3f4f91b83b67353aada8355f48e25c59",
        )

    def test_v1_selector_rejects_zero_margin(self):
        # documents the v1 defect: any nonpositive margin is fatal in v1
        from select_issue74_margin_stress import select as select_v1
        v1_pool = load(V1, "margin-stress-pool.json")
        v1_commitment = load(V1, "margin-stress-selection-commitment.json")
        ids = [c["case_id"] for c in v1_pool["cases"]]
        cases = []
        for case in v1_pool["cases"]:
            margin = 0.0 if case["case_id"] == ids[0] else 1.0
            cases.append({
                "case_id": case["case_id"],
                "top1_margin_hex": margin.hex(),
            })
        margins = {
            "schema": "inferswarm.issue74.reference-margin-summary/1",
            "contract_id": CONTRACT_ID,
            "stress_pool_sha256": sha256_bytes(canonical_json_bytes(v1_pool)),
            "cases": cases,
        }
        with self.assertRaises(ValueError):
            select_v1(v1_pool, margins, v1_commitment)


if __name__ == "__main__":
    unittest.main()
