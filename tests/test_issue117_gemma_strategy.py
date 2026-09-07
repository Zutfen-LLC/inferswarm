"""Focused tests for the issue #117 Gemma dense strategy seam."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import issue117_gemma_strategy as strategy  # noqa: E402
from issue99_artifact_core import derive_participant_requirements  # noqa: E402


def build_strategy(temp: Path):
    repo = temp / "checkpoint"
    config, objects = strategy.build_synthetic_gemma_repository(repo)
    catalog = strategy.catalog_from_repository(repo, config=config)
    source_bytes = {name: data for name, data in objects.items()}

    def provider(name: str) -> bytes:
        return source_bytes[name]

    return strategy.GemmaDenseStrategy(catalog=catalog, source_bytes=provider), catalog, config


def capacity_model_for(catalog):
    """Synthetic capacity model with the real topology's feasibility shape.

    Declared per-CU usable weight bytes as a fraction of the synthetic
    checkpoint: a 16-layer stage fits a 3060-class CU, a 24-layer stage does
    not, and the whole checkpoint fits only the reference 3090-class CU.
    """
    total = strategy.checkpoint_weight_bytes(catalog)
    usable = {}
    for cu in strategy.RESOURCE_SNAPSHOT["compute_units"]:
        fraction = 1.06 if "3090" in cu["product"] else 0.36
        usable[cu["cu_id"]] = int(total * fraction)
    return usable


class CatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="issue117-strategy-")
        cls.strategy, cls.catalog, cls.config = build_strategy(Path(cls.temp.name))

    def test_catalog_covers_all_weight_state_units(self):
        units = strategy.weight_unit_ids(self.catalog)
        self.assertIn("state.embedding", units)
        self.assertIn("state.final_norm", units)
        self.assertIn("state.output_head", units)
        for layer in range(48):
            self.assertIn(f"state.layer.{layer}", units)

    def test_shard_boundary_crosses_the_accepted_stage_boundary(self):
        tensors = self.catalog["tensors"]
        shard_of = {name: spec["object"] for name, spec in tensors.items()}
        self.assertEqual(
            shard_of["model.layers.15.self_attn.q_proj.weight"],
            shard_of["model.embed_tokens.weight"])
        self.assertEqual(
            shard_of["model.layers.24.self_attn.q_proj.weight"],
            shard_of["model.norm.weight"])
        self.assertNotEqual(
            shard_of["model.layers.23.mlp.down_proj.weight"],
            shard_of["model.layers.24.mlp.down_proj.weight"])

    def test_tied_head_has_no_lm_head_tensor(self):
        self.assertNotIn("model.lm_head.weight", self.catalog["tensors"])

    def test_catalog_is_deterministic(self):
        again = strategy.catalog_from_repository(
            Path(self.temp.name) / "checkpoint", config=self.config)
        self.assertEqual(self.catalog, again)


class CandidateEnumerationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="issue117-strategy-")
        cls.strategy, cls.catalog, _ = build_strategy(Path(cls.temp.name))
        cls.capacity = capacity_model_for(cls.catalog)
        cls.candidates = cls.strategy.legal_candidates(capacity_model=cls.capacity)

    def test_enumerates_balanced_dense_candidates_only(self):
        by_stages = {}
        for candidate in self.candidates:
            by_stages.setdefault(candidate["stage_count"], []).append(candidate)
        self.assertEqual(sorted(by_stages), [1, 2, 3])
        sizes = {
            count: [ [s["layer_end"] - s["layer_start"] for s in c["stages"]]
                     for c in sorted(candidates, key=lambda c: c["candidate_id"]) ]
            for count, candidates in by_stages.items()
        }
        # one balanced stage per CU; balanced windows over the chain for
        # multi-stage candidates (contiguous chain windows, no holes)
        self.assertEqual(sizes[1], [[48]] * 4)
        self.assertEqual(sizes[2], [[24, 24]] * 3)
        self.assertEqual(sizes[3], [[16, 16, 16]] * 2)
        self.assertEqual(len(self.candidates), 9)

    def test_accepted_v5_geometry_is_enumerated(self):
        candidate = self.strategy.accepted_v5_candidate(self.candidates)
        self.assertEqual([s["cu_id"] for s in candidate["stages"]],
                         ["inferswarm01/gpu-0", "inferswarm01/gpu-1", "inferswarm03/gpu-0"])
        self.assertEqual([s["layer_start"] for s in candidate["stages"]], [0, 16, 32])
        self.assertEqual([s["layer_end"] for s in candidate["stages"]], [16, 32, 48])

    def test_missing_v5_geometry_fails_closed(self):
        trimmed = strategy.GemmaDenseStrategy(
            catalog=self.catalog,
            snapshot={**strategy.RESOURCE_SNAPSHOT,
                      "chain_order": strategy.RESOURCE_SNAPSHOT["chain_order"][:3]})
        candidates = trimmed.legal_candidates(capacity_model=self.capacity)
        # chain of three 3060 CUs still produces the accepted geometry
        self.strategy.accepted_v5_candidate(candidates)
        two_node = strategy.GemmaDenseStrategy(
            catalog=self.catalog,
            snapshot={**strategy.RESOURCE_SNAPSHOT,
                      "chain_order": ["inferswarm01/gpu-0", "inferswarm01/gpu-1"]})
        with self.assertRaisesRegex(strategy.StrategyError, "missing"):
            two_node.accepted_v5_candidate(two_node.legal_candidates())

    def test_candidate_ids_are_deterministic_and_distinct(self):
        ids = [c["candidate_id"] for c in self.candidates]
        self.assertEqual(len(ids), len(set(ids)))
        again = self.strategy.legal_candidates(capacity_model=self.capacity)
        self.assertEqual(ids, [c["candidate_id"] for c in again])

    def test_qualification_subject_binds_checkpoint_backend_and_geometry(self):
        v5 = self.strategy.accepted_v5_candidate(self.candidates)
        subject = v5["qualification_subject"]
        self.assertEqual(subject["checkpoint_sha256"],
                         strategy.MODEL_SUBJECT["checkpoint_sha256"])
        self.assertEqual(subject["backend"]["triton"], "3.6.0")
        self.assertEqual(subject["stage_structure"][0]["layer_end"], 16)

    def test_any_geometry_change_changes_the_subject_digest(self):
        v5 = self.strategy.accepted_v5_candidate(self.candidates)
        mutated = json.loads(json.dumps(v5))
        mutated["stages"][0]["layer_end"] = 17
        mutated["stages"][1]["layer_start"] = 17
        mutated_subject = self.strategy.qualification_subject(mutated)
        self.assertNotEqual(
            v5["qualification_subject_digest"],
            strategy.digest_of_bytes(
                __import__("issue74_methodology").canonical_json_bytes(mutated_subject)))


class FeasibilityAndPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="issue117-strategy-")
        cls.strategy, cls.catalog, _ = build_strategy(Path(cls.temp.name))
        cls.capacity = capacity_model_for(cls.catalog)
        cls.candidates = cls.strategy.legal_candidates(capacity_model=cls.capacity)

    def _find(self, *, stage_count, contains_3090):
        matches = []
        for candidate in self.candidates:
            if candidate["stage_count"] != stage_count:
                continue
            has = any("inferswarm04" in stage["cu_id"] for stage in candidate["stages"])
            if has == contains_3090:
                matches.append(candidate)
        return matches

    def test_single_3090_reference_candidate_is_technically_feasible(self):
        single = self._find(stage_count=1, contains_3090=True)[0]
        feasibility = self.strategy.feasibility(single, capacity_model=self.capacity)
        self.assertTrue(feasibility["technical_feasibility"])
        self.assertFalse(feasibility["hard_policy_eligible"])

    def test_single_3060_candidate_is_capacity_infeasible(self):
        single = self._find(stage_count=1, contains_3090=False)[0]
        feasibility = self.strategy.feasibility(single, capacity_model=self.capacity)
        self.assertFalse(feasibility["technical_feasibility"])

    def test_two_stage_candidates_are_capacity_infeasible(self):
        for candidate in self._find(stage_count=2, contains_3090=False):
            feasibility = self.strategy.feasibility(candidate, capacity_model=self.capacity)
            self.assertFalse(feasibility["technical_feasibility"], candidate["candidate_id"])

    def test_v5_candidate_is_feasible_and_policy_eligible(self):
        v5 = self.strategy.accepted_v5_candidate(self.candidates)
        feasibility = self.strategy.feasibility(v5, capacity_model=self.capacity)
        self.assertTrue(feasibility["technical_feasibility"])
        self.assertTrue(feasibility["hard_policy_eligible"])

    def test_three_stage_candidates_on_reference_path_are_policy_excluded(self):
        for candidate in self._find(stage_count=3, contains_3090=True):
            feasibility = self.strategy.feasibility(candidate, capacity_model=self.capacity)
            self.assertTrue(feasibility["technical_feasibility"])
            self.assertFalse(feasibility["hard_policy_eligible"])

    def test_unknown_capacity_fails_closed(self):
        v5 = self.strategy.accepted_v5_candidate(self.candidates)
        feasibility = self.strategy.feasibility(v5, capacity_model=None)
        self.assertFalse(feasibility["technical_feasibility"])
        self.assertFalse(feasibility["technical_feasibility_known"])


class QualificationRecordTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="issue117-strategy-")
        cls.strategy, cls.catalog, _ = build_strategy(Path(cls.temp.name))
        cls.capacity = capacity_model_for(cls.catalog)
        cls.candidates = cls.strategy.legal_candidates(capacity_model=cls.capacity)
        cls.record = cls.strategy.accepted_v5_qualification_record()

    def test_record_binds_terminal_v5_disposition_and_subject(self):
        self.assertEqual(
            self.record["authority"]["terminal_disposition"], "V5_QUALIFICATION_PASS")
        v5 = self.strategy.accepted_v5_candidate(self.candidates)
        self.assertEqual(self.record["qualification_subject_digest"],
                         v5["qualification_subject_digest"])

    def test_non_v5_candidates_do_not_match_the_qualified_subject(self):
        v5 = self.strategy.accepted_v5_candidate(self.candidates)
        for candidate in self.candidates:
            if candidate["candidate_id"] == v5["candidate_id"]:
                continue
            self.assertNotEqual(self.record["qualification_subject_digest"],
                                candidate["qualification_subject_digest"])

    def test_record_is_deterministic(self):
        self.assertEqual(self.record, self.strategy.accepted_v5_qualification_record())


class PlanAndRequirementsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="issue117-strategy-")
        cls.strategy, cls.catalog, _ = build_strategy(Path(cls.temp.name))
        cls.capacity = capacity_model_for(cls.catalog)
        cls.candidates = cls.strategy.legal_candidates(capacity_model=cls.capacity)
        cls.v5 = cls.strategy.accepted_v5_candidate(cls.candidates)
        cls.plan = cls.strategy.plan(cls.v5)
        cls.requirements = derive_participant_requirements(
            cls.plan, cls.strategy.resolve)

    def test_plan_declares_every_logical_state_unit(self):
        ids = {unit["id"] for unit in self.plan["logical_state_units"]}
        self.assertEqual(len(ids), 48 + 3 + 2)  # layers + embedding/final_norm/output_head + metadata

    def test_stage_one_owns_embedding_and_layers_zero_to_fifteen(self):
        participant = self.requirements["participants"][0]
        state = participant["required_logical_state"]
        self.assertIn("state.embedding", state["assigned"])
        for layer in range(16):
            self.assertIn(f"state.layer.{layer}", state["assigned"])
        for layer in range(16, 48):
            self.assertNotIn(f"state.layer.{layer}", state["assigned"])
        self.assertEqual(state["declared_shared"], [])

    def test_final_stage_declares_tied_head_as_shared_state(self):
        participant = self.requirements["participants"][2]
        state = participant["required_logical_state"]
        self.assertIn("state.embedding", state["declared_shared"])
        self.assertIn("state.output_head", state["declared_shared"])
        self.assertNotIn("state.embedding", state["assigned"])
        self.assertIn("state.final_norm", state["assigned"])
        for layer in range(32, 48):
            self.assertIn(f"state.layer.{layer}", state["assigned"])

    def test_participants_are_exact_and_disjoint_except_declared_shared(self):
        participants = self.requirements["participants"]
        owners: dict[str, set[str]] = {}
        for participant in participants:
            for record in participant["required_artifacts"]:
                if record["requirement_class"] == "declared_shared_state":
                    continue
                for state_id in record["satisfies_logical_state_ids"]:
                    if state_id.startswith("metadata."):
                        continue
                    owners.setdefault(state_id, set()).add(participant["participant_id"])
        multi = {state_id: participant_ids for state_id, participant_ids in owners.items()
                 if len(participant_ids) > 1}
        self.assertEqual(multi, {})

    def test_no_participant_requires_the_complete_model(self):
        total = strategy.checkpoint_weight_bytes(self.catalog)
        for participant in self.requirements["participants"]:
            weight_bytes = sum(
                record["length"] for record in participant["required_artifacts"]
                if record["requirement_class"] != "required_metadata")
            self.assertLess(weight_bytes, total)

    def test_shared_head_state_acquires_zero_extra_bytes_across_stages(self):
        participants = self.requirements["participants"]
        stage_three = participants[2]
        shared_digests = {
            record["content_digest"] for record in stage_three["required_artifacts"]
            if record["requirement_class"] == "declared_shared_state"}
        stage_one_digests = {
            record["content_digest"] for record in participants[0]["required_artifacts"]}
        self.assertTrue(shared_digests)
        self.assertEqual(shared_digests, shared_digests & stage_one_digests)

    def test_layer_artifacts_are_exact_tensor_ranges(self):
        participant = self.requirements["participants"][0]
        ranges = [record for record in participant["required_artifacts"]
                  if record["kind"] == "byte_range"]
        self.assertTrue(ranges)
        for record in ranges:
            origin = record["origin"]
            self.assertEqual(origin["byte_end"] - origin["byte_start"], record["length"])

    def test_plan_is_immutable_per_candidate_epoch(self):
        self.assertEqual(self.plan, self.strategy.plan(self.v5))
        other = self.strategy.plan(self.v5, epoch=2)
        self.assertNotEqual(self.plan["plan_digest"], other["plan_digest"])


if __name__ == "__main__":
    unittest.main()
