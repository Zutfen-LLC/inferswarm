"""Focused tests for the issue #117 Gemma dense strategy seam."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import issue117_gemma_strategy as strategy  # noqa: E402
from issue74_methodology import canonical_json_bytes  # noqa: E402
from issue99_artifact_core import derive_participant_requirements, digest_of_bytes  # noqa: E402
from issue117_subject_identity import (  # noqa: E402
    MACHINERY_LOCAL_SUBJECT_KEYS,
    subject_digest,
)


def build_strategy(temp: Path, *, seed: str = "issue117-synthetic-gemma-v1"):
    repo = temp / "checkpoint"
    config, objects = strategy.build_synthetic_gemma_repository(repo, seed=seed)
    catalog = strategy.catalog_from_repository(repo, config=config)
    source_bytes = {name: data for name, data in objects.items()}

    def provider(name: str) -> bytes:
        return source_bytes[name]

    manifest = strategy.build_source_manifest(catalog, source_bytes=provider)
    subject = strategy.subject_from_catalog(
        catalog, execution=strategy.SYNTHETIC_SUBJECT_EXECUTION,
        backend=strategy.SYNTHETIC_SUBJECT_BACKEND)
    instance = strategy.GemmaDenseStrategy(catalog=catalog, subject=subject,
                                           source_manifest=manifest)
    return instance, catalog, config, manifest, subject


def capacity_model_for(catalog):
    """Synthetic capacity model with the real topology's feasibility shape.

    Declared per-CU usable weight bytes as a fraction of the synthetic
    checkpoint. The fraction window is derived from the exact
    participant-requirement accounting: a 16-layer stage with its
    embedding/shared-head state needs 42.9% of the checkpoint, a 24-layer
    stage needs 57.1%; 0.50 lies strictly between, so accepted-geometry
    stages are feasible and 24-layer stages are not. The whole checkpoint
    fits only the reference CU (1.06).
    """
    total = strategy.checkpoint_weight_bytes(catalog)
    usable = {}
    for cu in strategy.RESOURCE_SNAPSHOT["compute_units"]:
        fraction = 1.06 if "3090" in cu["product"] else 0.50
        usable[cu["cu_id"]] = int(total * fraction)
    return usable


class CatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="issue117-strategy-")
        (cls.strategy, cls.catalog, cls.config,
         cls.manifest, cls.subject) = build_strategy(Path(cls.temp.name))

    def test_catalog_covers_all_weight_state_units(self):
        units = strategy.weight_unit_ids(self.catalog)
        self.assertIn("state.embedding", units)
        self.assertIn("state.final_norm", units)
        self.assertIn("state.output_head", units)
        for layer in range(48):
            self.assertIn(f"state.layer.{layer}", units)

    def test_catalog_carries_two_separate_checkpoint_identities(self):
        content_digest = self.catalog["catalog_content_digest"]
        authority = self.catalog["checkpoint_authority_sha256"]
        self.assertTrue(content_digest.startswith("sha256:"))
        self.assertEqual(len(authority), 64)
        self.assertNotIn(authority, content_digest)
        # the content identity binds the checkpoint content, not just the
        # model id: a materially different checkpoint carries a different
        # content identity while its (synthetic) authority also differs
        other_temp = tempfile.TemporaryDirectory(prefix="issue117-strategy-other-")
        self.addCleanup(other_temp.cleanup)
        _, other_catalog, _, _, other_subject = build_strategy(
            Path(other_temp.name), seed="a-materially-different-checkpoint")
        self.assertNotEqual(content_digest, other_catalog["catalog_content_digest"])
        self.assertNotEqual(authority, other_catalog["checkpoint_authority_sha256"])
        self.assertNotEqual(self.subject["catalog_content_digest"],
                            other_subject["catalog_content_digest"])

    def test_catalog_records_source_side_bytes_hashed(self):
        weight = strategy.checkpoint_weight_bytes(self.catalog)
        self.assertGreater(self.catalog["source_bytes_hashed"], 0)
        # whole safetensors objects are hashed source-side, including the
        # safetensors headers, so at least every weight byte was read
        self.assertGreaterEqual(self.catalog["source_bytes_hashed"], weight)
        self.assertEqual(
            self.catalog["source_bytes_hashed"],
            sum(path.stat().st_size for path in
                (Path(self.temp.name) / "checkpoint").glob("*.safetensors")))

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


class SourceManifestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="issue117-strategy-")
        (cls.strategy, cls.catalog, _,
         cls.manifest, _) = build_strategy(Path(cls.temp.name))

    def test_manifest_is_self_consistent_and_bound_to_catalog(self):
        self.assertEqual(self.manifest["model"], self.catalog["model"])
        self.assertEqual(self.manifest["checkpoint_authority_sha256"],
                         self.catalog["checkpoint_authority_sha256"])
        self.assertEqual(self.manifest["catalog_content_digest"],
                         self.catalog["catalog_content_digest"])
        self.assertEqual(
            self.manifest["manifest_digest"],
            strategy.self_digest(self.manifest, identity_field="manifest_digest"))

    def test_manifest_records_source_side_reads(self):
        self.assertGreater(self.manifest["source_bytes_read"], 0)

    def test_resolve_serves_records_without_byte_access(self):
        records = self.strategy.resolve("assigned_logical_state", "state.layer.0")
        self.assertTrue(records)
        for record in records:
            self.assertNotIn(b"", record.values())
            self.assertEqual(record["requirement_class"], "assigned_logical_state")

    def test_resolve_refuses_illegal_combinations(self):
        # a tied head is declared shared state only; no assigned record exists
        with self.assertRaises(strategy.StrategyError):
            self.strategy.resolve("assigned_logical_state", "state.output_head")
        with self.assertRaises(strategy.StrategyError):
            self.strategy.resolve("assigned_logical_state", "state.nonexistent")


class CandidateEnumerationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="issue117-strategy-")
        (cls.strategy, cls.catalog, _,
         _, _) = build_strategy(Path(cls.temp.name))
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
            catalog=self.catalog, subject=self.strategy.subject,
            source_manifest=self.strategy.source_manifest,
            snapshot={**strategy.RESOURCE_SNAPSHOT,
                      "chain_order": strategy.RESOURCE_SNAPSHOT["chain_order"][:3]})
        candidates = trimmed.legal_candidates(capacity_model=self.capacity)
        # chain of three 3060 CUs still produces the accepted geometry
        self.strategy.accepted_v5_candidate(candidates)
        two_node = strategy.GemmaDenseStrategy(
            catalog=self.catalog, subject=self.strategy.subject,
            source_manifest=self.strategy.source_manifest,
            snapshot={**strategy.RESOURCE_SNAPSHOT,
                      "chain_order": ["inferswarm01/gpu-0", "inferswarm01/gpu-1"]})
        with self.assertRaisesRegex(strategy.StrategyError, "missing"):
            two_node.accepted_v5_candidate(two_node.legal_candidates())

    def test_candidate_ids_are_deterministic_and_distinct(self):
        ids = [c["candidate_id"] for c in self.candidates]
        self.assertEqual(len(ids), len(set(ids)))
        again = self.strategy.legal_candidates(capacity_model=self.capacity)
        self.assertEqual(ids, [c["candidate_id"] for c in again])

    def test_qualification_subject_binds_catalog_backend_and_geometry(self):
        v5 = self.strategy.accepted_v5_candidate(self.candidates)
        subject = v5["qualification_subject"]
        # the subject's checkpoint identities are the CATALOG's own, both the
        # synthetic authority identity and the mechanical content identity —
        # never an externally supplied constant
        self.assertEqual(subject["checkpoint_authority_sha256"],
                         self.catalog["checkpoint_authority_sha256"])
        self.assertEqual(subject["catalog_content_digest"],
                         self.catalog["catalog_content_digest"])
        self.assertEqual(subject["backend"]["triton"],
                         strategy.SYNTHETIC_SUBJECT_BACKEND["triton"])
        self.assertEqual(subject["stage_structure"][0]["layer_end"], 16)

    def test_any_geometry_change_changes_the_subject_digest(self):
        v5 = self.strategy.accepted_v5_candidate(self.candidates)
        mutated = json.loads(json.dumps(v5))
        mutated["stages"][0]["layer_end"] = 17
        mutated["stages"][1]["layer_start"] = 17
        mutated_subject = self.strategy.qualification_subject(mutated)
        self.assertNotEqual(
            v5["qualification_subject_digest"],
            digest_of_bytes(canonical_json_bytes(mutated_subject)))


class SubjectBindingTests(unittest.TestCase):
    """P0-2: the qualification subject is inseparable from the catalog."""

    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="issue117-strategy-")
        (cls.strategy, cls.catalog, _,
         cls.manifest, cls.subject) = build_strategy(Path(cls.temp.name))

    def test_subject_from_catalog_is_catalog_derived(self):
        self.assertEqual(self.subject["model_id"], self.catalog["model"]["model_id"])
        self.assertEqual(self.subject["revision"], self.catalog["model"]["revision"])
        self.assertEqual(self.subject["checkpoint_authority_sha256"],
                         self.catalog["checkpoint_authority_sha256"])
        self.assertEqual(self.subject["catalog_content_digest"],
                         self.catalog["catalog_content_digest"])
        self.assertNotEqual(self.subject["checkpoint_authority_sha256"],
                            strategy.MODEL_SUBJECT["checkpoint_authority_sha256"])

    def test_strategy_refuses_foreign_checkpoint_subject(self):
        # the accepted real Gemma subject cannot qualify a synthetic catalog
        with self.assertRaisesRegex(strategy.StrategyError, "catalog identity"):
            strategy.GemmaDenseStrategy(
                catalog=self.catalog,
                subject={**strategy.MODEL_SUBJECT,
                         "catalog_content_digest":
                             self.catalog["catalog_content_digest"]},
                source_manifest=self.manifest)

    def test_strategy_refuses_tampered_checkpoint_identities(self):
        tampered = dict(self.subject)
        tampered["checkpoint_authority_sha256"] = "f" * 64
        with self.assertRaisesRegex(strategy.StrategyError, "catalog identity"):
            strategy.GemmaDenseStrategy(catalog=self.catalog, subject=tampered,
                                        source_manifest=self.manifest)
        content_tampered = dict(self.subject)
        content_tampered["catalog_content_digest"] = "sha256:" + "f" * 64
        with self.assertRaisesRegex(strategy.StrategyError, "catalog identity"):
            strategy.GemmaDenseStrategy(catalog=self.catalog,
                                        subject=content_tampered,
                                        source_manifest=self.manifest)

    def test_strategy_refuses_tampered_revision(self):
        tampered = dict(self.subject)
        tampered["revision"] = "some-other-revision"
        with self.assertRaisesRegex(strategy.StrategyError, "catalog identity"):
            strategy.GemmaDenseStrategy(catalog=self.catalog, subject=tampered,
                                        source_manifest=self.manifest)

    def test_strategy_refuses_tampered_backend(self):
        with self.assertRaisesRegex(strategy.StrategyError, "backend field"):
            strategy.subject_from_catalog(
                self.catalog, execution="e", backend={})
        tampered = dict(self.subject)
        tampered["backend"] = {**self.subject["backend"], "triton": ""}
        with self.assertRaisesRegex(strategy.StrategyError, "backend field"):
            strategy.GemmaDenseStrategy(catalog=self.catalog, subject=tampered,
                                        source_manifest=self.manifest)

    def test_strategy_refuses_missing_subject_or_manifest(self):
        with self.assertRaises(strategy.StrategyError):
            strategy.GemmaDenseStrategy(catalog=self.catalog, subject=None,
                                        source_manifest=self.manifest)
        with self.assertRaisesRegex(strategy.StrategyError, "manifest"):
            strategy.GemmaDenseStrategy(catalog=self.catalog, subject=self.subject,
                                        source_manifest=None)

    def test_plan_refuses_foreign_candidate_subject(self):
        v5 = self.strategy.accepted_v5_candidate(
            self.strategy.legal_candidates())
        foreign = json.loads(json.dumps(v5))
        foreign["qualification_subject"]["revision"] = "another-revision"
        foreign["qualification_subject_digest"] = digest_of_bytes(
            canonical_json_bytes(foreign["qualification_subject"]))
        with self.assertRaisesRegex(strategy.StrategyError, "foreign subject"):
            self.strategy.plan(foreign)

    def test_plan_embeds_the_bound_subject(self):
        v5 = self.strategy.accepted_v5_candidate(
            self.strategy.legal_candidates())
        plan = self.strategy.plan(v5)
        self.assertEqual(plan["qualification_subject"], v5["qualification_subject"])
        self.assertEqual(plan["qualification_subject_digest"],
                         v5["qualification_subject_digest"])
        self.assertEqual(plan["model"]["checkpoint_authority_sha256"],
                         self.catalog["checkpoint_authority_sha256"])
        self.assertEqual(plan["model"]["catalog_content_digest"],
                         self.catalog["catalog_content_digest"])
        self.assertEqual(plan["model"]["layer_count"], strategy.LAYER_COUNT)


class FeasibilityAndPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="issue117-strategy-")
        (cls.strategy, cls.catalog, _,
         _, _) = build_strategy(Path(cls.temp.name))
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

    def test_stage_bytes_come_from_exact_participant_requirements(self):
        from issue99_artifact_core import derive_participant_requirements
        v5 = self.strategy.accepted_v5_candidate(self.candidates)
        requirements = derive_participant_requirements(
            self.strategy.plan(v5), self.strategy.resolve)
        for index, participant in enumerate(requirements["participants"]):
            exact = sum(record["length"] for record in participant["required_artifacts"]
                        if record["requirement_class"] != "required_metadata")
            self.assertEqual(self.strategy.stage_weight_bytes(v5, index), exact)

    def test_feasibility_accounting_includes_embedding_and_shared_head(self):
        v5 = self.strategy.accepted_v5_candidate(self.candidates)
        layer_bytes = strategy.checkpoint_weight_bytes(self.catalog) \
            - strategy.checkpoint_weight_bytes(self.catalog)  # placeholder; computed below
        tensors = self.catalog["tensors"]
        per_layer = sum(t["byte_count"] for name, t in tensors.items()
                        if strategy.layer_of_tensor(name) is not None)
        embed = tensors["model.embed_tokens.weight"]["byte_count"]
        norm = tensors["model.norm.weight"]["byte_count"]
        # stage 1: 16 layers + the embedding state it owns
        self.assertEqual(self.strategy.stage_weight_bytes(v5, 0),
                         16 * per_layer // 48 + embed)
        # stage 3: 16 layers + final norm + the shared tied-head state
        self.assertEqual(self.strategy.stage_weight_bytes(v5, 2),
                         16 * per_layer // 48 + norm + embed)
        # the legacy layers-only accounting would have missed both
        self.assertGreater(self.strategy.stage_weight_bytes(v5, 0),
                           per_layer // 3)
        self.assertGreater(self.strategy.stage_weight_bytes(v5, 2),
                           per_layer // 3 + norm)

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
        self.assertEqual(feasibility["accounting_source"],
                         "exact_participant_requirements")

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

    def test_missing_shared_state_would_change_the_feasibility_input(self):
        # the accounting derives from requirements: a requirement set without
        # the shared tied-head state yields strictly fewer bytes than the
        # true plan, so a strategy that dropped shared state would not match
        # the exact participant requirements (regression guard for P0-3)
        v5 = self.strategy.accepted_v5_candidate(self.candidates)
        requirements = self.strategy.stage_requirements(v5)
        stage_three = requirements["participants"][2]
        without_shared = sum(
            record["length"] for record in stage_three["required_artifacts"]
            if record["requirement_class"] not in ("required_metadata",
                                                   "declared_shared_state"))
        self.assertLess(without_shared, self.strategy.stage_weight_bytes(v5, 2))
        shared_records = [record for record in stage_three["required_artifacts"]
                          if record["requirement_class"] == "declared_shared_state"]
        self.assertTrue(shared_records)


class QualificationAuthorityTests(unittest.TestCase):
    def test_retained_v5_authority_is_recovered_from_evidence(self):
        record = strategy.retained_v5_qualification_authority()
        self.assertEqual(
            record["authority"]["terminal_adjudication_sha256"],
            "f024f8b3394686ff098459b657ce6dba62d7f190972663e3929ef4a574ab7a70")
        self.assertEqual(record["authority"]["terminal_disposition"],
                         "V5_QUALIFICATION_PASS")
        self.assertEqual(
            record["qualification_subject"]["checkpoint_authority_sha256"],
            strategy.MODEL_SUBJECT["checkpoint_authority_sha256"])

class PlanAndRequirementsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="issue117-strategy-")
        (cls.strategy, cls.catalog, _,
         _, _) = build_strategy(Path(cls.temp.name))
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


class CanonicalCandidateDiagnosticTests(unittest.TestCase):
    def test_canonical_candidate_is_a_diagnostic_not_accepted_authority(self):
        candidate = strategy.canonical_v5_candidate()
        self.assertIn("qualification_subject", candidate)
        # the accepted authority loads independently of the diagnostic
        # candidate: it comes from pinned evidence, not from the candidate
        record = strategy.retained_v5_qualification_authority()
        self.assertEqual(
            record["qualification_subject_digest"],
            candidate["qualification_subject_digest"])

    def test_canonical_authority_is_evidence_bound_not_a_config_field(self):
        catalog = strategy.canonical_authority_catalog(inferswarm_root=ROOT)
        self.assertEqual(
            catalog["checkpoint_authority_sha256"],
            strategy.MODEL_SUBJECT["checkpoint_authority_sha256"])

    def test_descriptor_only_catalog_refuses_byte_level_planning(self):
        catalog = strategy.canonical_authority_catalog()
        subject = strategy.subject_from_catalog(
            catalog, execution=strategy.MODEL_SUBJECT["execution"],
            backend=strategy.MODEL_SUBJECT["backend"])
        instance = strategy.GemmaDenseStrategy(
            catalog=catalog, subject=subject, source_manifest=None)
        with self.assertRaisesRegex(strategy.StrategyError, "byte-level"):
            instance.plan(instance.accepted_v5_candidate(
                instance.legal_candidates()))

class CheckpointAuthorityAttestationTests(unittest.TestCase):
    """Finding 1: the repository-to-authority binding is evidence-backed."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="issue117-attest-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "checkpoint"
        self.config, self.objects = strategy.build_synthetic_gemma_repository(
            self.root)

    def write_attestation(self, *, model_id, revision, authority,
                          evidence="test attestation"):
        from issue74_methodology import canonical_json_bytes
        attestation = strategy.build_checkpoint_authority_attestation(
            self.root, model_id=model_id, revision=revision,
            checkpoint_authority_sha256=authority, authority_evidence=evidence)
        (self.root / strategy.AUTHORITY_ATTESTATION_OBJECT).write_bytes(
            canonical_json_bytes(attestation))
        return attestation

    def rebuild_catalog(self, *, model_id=None, revision=None):
        config = {**self.config,
                  "model_id": model_id or self.config["model_id"],
                  "revision": revision or self.config["revision"]}
        return strategy.catalog_from_repository(self.root, config=config,
                                                inferswarm_root=ROOT)

    def test_materially_changed_bytes_change_content_digest_and_break(self):
        catalog = self.rebuild_catalog()
        # mutate one weight byte in place, keeping the attestation stale
        shard = self.root / "model-00001-of-00002.safetensors"
        data = bytearray(shard.read_bytes())
        data[-1] ^= 0xFF
        shard.write_bytes(bytes(data))
        with self.assertRaisesRegex(strategy.StrategyError, "drifted"):
            strategy.catalog_from_repository(self.root, config=self.config,
                                             inferswarm_root=ROOT)
        # with a fresh (honest) attestation the construction succeeds but
        # the mechanical content identity has materially changed
        self.write_attestation(model_id=self.config["model_id"],
                               revision=self.config["revision"],
                               authority="b" * 64,
                               evidence="re-attested after byte change")
        drifted = strategy.catalog_from_repository(self.root, config=self.config,
                                                   inferswarm_root=ROOT)
        self.assertNotEqual(drifted["catalog_content_digest"],
                            catalog["catalog_content_digest"])
        self.assertNotEqual(drifted["checkpoint_authority_sha256"],
                            catalog["checkpoint_authority_sha256"])

    def test_same_model_revision_with_foreign_authority_is_refused(self):
        # a repository claiming the canonical Gemma identity must carry the
        # accepted authority; a foreign authority claim is a forgery
        self.write_attestation(model_id=strategy.MODEL_SUBJECT["model_id"],
                               revision=strategy.MODEL_SUBJECT["revision"],
                               authority="c" * 64,
                               evidence="foreign checkpoint authority")
        with self.assertRaisesRegex(strategy.StrategyError, "accepted authority"):
            self.rebuild_catalog(model_id=strategy.MODEL_SUBJECT["model_id"],
                                 revision=strategy.MODEL_SUBJECT["revision"])

    def test_forged_accepted_authority_over_foreign_content_is_refused(self):
        # foreign (synthetic F32 fixture) content fronting the accepted
        # authority SHA under the canonical model identity: the observed
        # structure (dtypes/layout) is mechanically unlike the accepted
        # native-BF16 checkpoint, and construction fails closed
        self.write_attestation(
            model_id=strategy.MODEL_SUBJECT["model_id"],
            revision=strategy.MODEL_SUBJECT["revision"],
            authority=strategy.MODEL_SUBJECT["checkpoint_authority_sha256"],
            evidence="forged")
        with self.assertRaisesRegex(strategy.StrategyError, "representation drift"):
            self.rebuild_catalog(model_id=strategy.MODEL_SUBJECT["model_id"],
                                 revision=strategy.MODEL_SUBJECT["revision"])

    def test_missing_or_tampered_attestation_is_refused(self):
        (self.root / strategy.AUTHORITY_ATTESTATION_OBJECT).unlink()
        with self.assertRaisesRegex(
                strategy.StrategyError,
                "carries no checkpoint-authority.json"):
            strategy.catalog_from_repository(self.root, config=self.config)
        strategy.build_synthetic_gemma_repository(self.root)
        attestation = json.loads(
            (self.root / strategy.AUTHORITY_ATTESTATION_OBJECT).read_text())
        attestation["objects"]["model-00002-of-00002.safetensors"]["sha256"] = "0" * 64
        from issue74_methodology import canonical_json_bytes
        (self.root / strategy.AUTHORITY_ATTESTATION_OBJECT).write_bytes(
            canonical_json_bytes(attestation))
        with self.assertRaisesRegex(strategy.StrategyError, "object set"):
            strategy.catalog_from_repository(self.root, config=self.config)
        strategy.build_synthetic_gemma_repository(self.root)
        attestation = json.loads(
            (self.root / strategy.AUTHORITY_ATTESTATION_OBJECT).read_text())
        attestation["objects"]["model-00002-of-00002.safetensors"]["sha256"] = "0" * 64
        from issue74_methodology import canonical_json_bytes
        (self.root / strategy.AUTHORITY_ATTESTATION_OBJECT).write_bytes(
            canonical_json_bytes(attestation))
        with self.assertRaisesRegex(strategy.StrategyError, "object set"):
            strategy.catalog_from_repository(self.root, config=self.config)

    def test_synthetic_fixture_cannot_inherit_v5_authority(self):
        # the accepted authority is bound to the accepted Gemma subject
        # recovered from pinned evidence; a synthetic fixture subject (model
        # id, execution, backend all fixture-scoped) can never equal it
        record = strategy.retained_v5_qualification_authority()
        fixture_subject = strategy.subject_from_catalog(
            strategy.canonical_authority_catalog(inferswarm_root=ROOT),
            execution=strategy.SYNTHETIC_SUBJECT_EXECUTION,
            backend=strategy.SYNTHETIC_SUBJECT_BACKEND)
        self.assertNotEqual(
            strategy.subject_digest(dict(fixture_subject)),
            record["qualification_subject_digest"])


if __name__ == "__main__":
    unittest.main()
