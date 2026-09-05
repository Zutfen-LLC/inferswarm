import ast
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'scripts'
sys.path.insert(0, str(SCRIPTS))

from issue74_methodology import canonical_json_bytes  # noqa: E402
from issue99_mini_model import PLAN_SCHEMA  # noqa: E402

from issue99_artifact_core import (  # noqa: E402
    AcquisitionError,
    AcquisitionLedger,
    CoordinatorAuthority,
    LocalFileSource,
    LocalHttpSource,
    NodeArtifactCache,
    TransferInterrupted,
    acquire_artifact,
    _unexplained_full_object_bytes,
    derive_participant_requirements,
    digest_of_bytes,
    freeze_artifact_record,
    guard_full_object_acquisition,
    validate_artifact_record,
)

MODEL = {"model_id": "issue99/test-model", "revision": "r" * 40, "representation": "native-f32"}


def make_object(root: Path, name: str, size: int, seed: bytes = b"seed") -> bytes:
    data = b"".join(
        hashlib.sha256(seed + i.to_bytes(4, "big")).digest()
        for i in range(size // 32 + 1)
    )[:size]
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return data


def range_record(root: Path, name: str, data: bytes, start: int, end: int,
                 state_id: str = "unit.state", requirement_class: str = "assigned_logical_state",
                 revision: str | None = None):
    return freeze_artifact_record(
        kind="byte_range",
        content=data[start:end],
        model_id=MODEL["model_id"],
        revision=revision or MODEL["revision"],
        representation=MODEL["representation"],
        satisfies_logical_state_ids=[state_id],
        requirement_class=requirement_class,
        origin={
            "source_object": name,
            "source_object_digest": digest_of_bytes(data),
            "source_object_length": len(data),
            "byte_start": start,
            "byte_end": end,
        },
    )


def whole_record(name: str, data: bytes, state_id: str = "unit.meta"):
    return freeze_artifact_record(
        kind="whole_object",
        content=data,
        model_id=MODEL["model_id"],
        revision=MODEL["revision"],
        representation=MODEL["representation"],
        satisfies_logical_state_ids=[state_id],
        requirement_class="required_metadata",
        origin={
            "source_object": name,
            "source_object_digest": digest_of_bytes(data),
            "source_object_length": len(data),
        },
    )


def unit_plan(participants, units=None):
    document = {
        "schema": PLAN_SCHEMA,
        "model": dict(MODEL),
        "logical_state_units": units if units is not None else [
            {"id": "unit.state", "semantic_class": "immutable_source"},
            {"id": "unit.meta", "semantic_class": "derived_reconstructible"},
        ],
        "participants": participants,
    }
    document["plan_digest"] = digest_of_bytes(canonical_json_bytes(document))
    return document


def participant(pid="unit-node", assigned=("unit.state",), shared=(), metadata=("unit.meta",)):
    return {
        "participant_id": pid,
        "node_id": pid,
        "execution_unit_id": f"exec.{pid}",
        "required_state": {
            "assigned_logical_state": list(assigned),
            "declared_shared_state": list(shared),
            "required_metadata": list(metadata),
        },
    }


class ArtifactRecordTests(unittest.TestCase):
    def test_record_self_identity_and_validation_round_trip(self):
        data = b"x" * 128
        record = range_record(Path("/tmp"), "obj.bin", data, 0, 64)
        validated = validate_artifact_record(json.loads(json.dumps(record)))
        self.assertEqual(validated["artifact_id"], record["artifact_id"])
        self.assertEqual(validated["content_digest"], digest_of_bytes(data[:64]))

    def test_tampered_record_fails_self_identity(self):
        data = b"x" * 128
        record = range_record(Path("/tmp"), "obj.bin", data, 0, 64)
        record["length"] = 63
        with self.assertRaisesRegex(AcquisitionError, "MALFORMED_ARTIFACT_RECORD"):
            validate_artifact_record(record)

    def test_range_outside_object_bounds_is_malformed(self):
        data = b"x" * 128
        with self.assertRaisesRegex(AcquisitionError, "MALFORMED_ARTIFACT_RECORD"):
            range_record(Path("/tmp"), "obj.bin", data, 96, 160)

    def test_unknown_kind_and_class_are_malformed(self):
        with self.assertRaisesRegex(AcquisitionError, "MALFORMED_ARTIFACT_RECORD"):
            freeze_artifact_record(
                kind="shard", content=b"x", model_id=MODEL["model_id"],
                revision=MODEL["revision"], representation=MODEL["representation"],
                satisfies_logical_state_ids=["s"], requirement_class="assigned_logical_state",
                origin={})
        with self.assertRaisesRegex(AcquisitionError, "MALFORMED_ARTIFACT_RECORD"):
            freeze_artifact_record(
                kind="whole_object", content=b"x", model_id=MODEL["model_id"],
                revision=MODEL["revision"], representation=MODEL["representation"],
                satisfies_logical_state_ids=["s"], requirement_class="convenience_preload",
                origin={"source_object": "o", "source_object_digest": "sha256:x",
                        "source_object_length": 1})


class RequirementDerivationTests(unittest.TestCase):
    def _fixture(self, temp: Path):
        data = make_object(temp, "obj.bin", 256)
        records = {
            "unit.state": [range_record(temp, "obj.bin", data, 0, 100)],
            "unit.meta": [whole_record("meta.json", b'{"layers": 4}')],
        }

        def resolver(requirement_class, requirement_id):
            if requirement_class == "required_metadata":
                return records.get(requirement_id, [])
            return records.get(requirement_id, [])

        return data, records, resolver

    def test_derivation_covers_declared_requirements_deterministically(self):
        with tempfile.TemporaryDirectory() as temp:
            temp = Path(temp)
            _, _, resolver = self._fixture(temp)
            plan = unit_plan([participant()])
            first = derive_participant_requirements(plan, resolver)
            second = derive_participant_requirements(plan, resolver)
            self.assertEqual(first["requirements_digest"], second["requirements_digest"])
            artifacts = first["participants"][0]["required_artifacts"]
            self.assertEqual({a["kind"] for a in artifacts}, {"byte_range", "whole_object"})
            self.assertEqual(first["participants"][0]["required_artifact_bytes"], 100 + 13)

    def test_provenance_mismatch_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            temp = Path(temp)
            data, _, _ = self._fixture(temp)
            other_revision = range_record(
                Path(temp), "obj.bin", data, 0, 100, revision="f" * 40)

            def resolver(requirement_class, requirement_id):
                return [other_revision] if requirement_id == "unit.state" else []

            plan = unit_plan([participant(metadata=())])
            with self.assertRaisesRegex(AcquisitionError, "PROVENANCE_IDENTITY_MISMATCH"):
                derive_participant_requirements(plan, resolver)

    def test_incomplete_coverage_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            temp = Path(temp)
            _, _, resolver = self._fixture(temp)

            def dropping_resolver(requirement_class, requirement_id):
                return [] if requirement_id == "unit.meta" else resolver(requirement_class, requirement_id)

            plan = unit_plan([participant()])
            with self.assertRaisesRegex(AcquisitionError, "REQUIRED_STATE_COVERAGE_INCOMPLETE"):
                derive_participant_requirements(plan, dropping_resolver)

    def test_undeclared_state_injection_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            temp = Path(temp)
            data = make_object(temp / "inject", "obj.bin", 256)
            injected = range_record(temp, "obj.bin", data, 200, 256, state_id="unrelated.state")

            def resolver(requirement_class, requirement_id):
                if requirement_id == "unit.state":
                    return [range_record(temp, "obj.bin", data, 0, 100), injected]
                return []

            plan = unit_plan([participant(metadata=())])
            with self.assertRaisesRegex(AcquisitionError, "UNDECLARED_REQUIREMENT_ARTIFACT"):
                derive_participant_requirements(plan, resolver)

    def test_wrong_requirement_class_claim_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            temp = Path(temp)
            data = make_object(temp, "obj.bin", 256)
            miscategorized = range_record(
                temp, "obj.bin", data, 0, 100, state_id="unit.meta",
                requirement_class="assigned_logical_state")

            def resolver(requirement_class, requirement_id):
                return [miscategorized] if requirement_id == "unit.meta" else []

            plan = unit_plan([participant(assigned=(), metadata=("unit.meta",))])
            with self.assertRaisesRegex(AcquisitionError, "UNDECLARED_REQUIREMENT_ARTIFACT"):
                derive_participant_requirements(plan, resolver)

    def test_plan_referencing_undeclared_logical_state_unit_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            temp = Path(temp)
            _, _, resolver = self._fixture(temp)
            # A tampered plan adds a whole-repository requirement that is not
            # a declared Logical State Unit of the plan.
            tampered = unit_plan(
                [participant(assigned=("unit.state", "whole.model.repository"), metadata=())],
                units=[{"id": "unit.state", "semantic_class": "immutable_source"}])
            with self.assertRaisesRegex(AcquisitionError, "UNDECLARED_REQUIREMENT_ARTIFACT"):
                derive_participant_requirements(tampered, resolver)


class CoordinatorAuthorityTests(unittest.TestCase):
    def _coordinator(self, temp: Path):
        data = make_object(temp, "obj.bin", 256)
        state_record = range_record(temp, "obj.bin", data, 0, 100)
        meta_record = whole_record("meta.json", b'{"layers": 4}')

        def resolver(requirement_class, requirement_id):
            return {"unit.state": [state_record], "unit.meta": [meta_record]}.get(
                requirement_id, [])

        plan = unit_plan([participant()])
        requirements = derive_participant_requirements(plan, resolver)
        authority = CoordinatorAuthority(
            plan=plan, requirements=requirements,
            eligible_sources=[{"source_id": "op-http", "endpoint": "http://127.0.0.1:1"}])
        return plan, requirements, authority, state_record, meta_record

    def test_authorization_freezes_required_set_and_sources(self):
        with tempfile.TemporaryDirectory() as temp:
            _, _, authority, state_record, meta_record = self._coordinator(Path(temp))
            entry = authority.authorization["participants"]["unit-node"]
            self.assertEqual(
                entry["required_artifact_ids"],
                sorted([state_record["artifact_id"], meta_record["artifact_id"]]))
            self.assertEqual(entry["eligible_source_ids"], ["op-http"])
            self.assertTrue(
                authority.authorization["authorization_digest"].startswith("sha256:"))

    def test_bulk_bytes_cannot_transit_the_coordinator(self):
        with tempfile.TemporaryDirectory() as temp:
            temp = Path(temp)
            plan, requirements, _, _, _ = self._coordinator(temp)
            poisoned = json.loads(json.dumps(requirements))
            poisoned["participants"][0]["required_artifacts"][0]["origin"]["leak"] = b"bulk"
            with self.assertRaisesRegex(AcquisitionError, "SOURCE_UNAUTHORIZED"):
                CoordinatorAuthority(
                    plan=plan, requirements=poisoned,
                    eligible_sources=[{"source_id": "op-http", "endpoint": "http://127.0.0.1:1"}])

    def test_acquisition_gate_refuses_unauthorized_source(self):
        with tempfile.TemporaryDirectory() as temp:
            temp = Path(temp)
            _, _, authority, state_record, _ = self._coordinator(temp)
            with self.assertRaisesRegex(AcquisitionError, "SOURCE_UNAUTHORIZED"):
                authority.check_acquisition(
                    participant_id="unit-node", artifact_record=state_record,
                    source_id="some-other-source")

    def test_acquisition_gate_refuses_undeclared_artifact(self):
        with tempfile.TemporaryDirectory() as temp:
            temp = Path(temp)
            data = make_object(temp, "obj.bin", 256)
            _, _, authority, _, _ = self._coordinator(temp)
            unrelated = range_record(temp, "obj.bin", data, 200, 256, state_id="other.state")
            with self.assertRaisesRegex(AcquisitionError, "UNDECLARED_REQUIREMENT_ARTIFACT"):
                authority.check_acquisition(
                    participant_id="unit-node", artifact_record=unrelated, source_id="op-http")

    def test_acquisition_gate_refuses_drifted_record(self):
        with tempfile.TemporaryDirectory() as temp:
            temp = Path(temp)
            _, _, authority, state_record, _ = self._coordinator(temp)
            drifted = json.loads(json.dumps(state_record))
            drifted["content_digest"] = "sha256:" + "0" * 64
            with self.assertRaisesRegex(AcquisitionError, "PROVENANCE_IDENTITY_MISMATCH"):
                authority.check_acquisition(
                    participant_id="unit-node", artifact_record=drifted, source_id="op-http")

    def test_reconciliation_requires_verified_sources_and_exact_bytes(self):
        with tempfile.TemporaryDirectory() as temp:
            temp = Path(temp)
            _, requirements, authority, state_record, meta_record = self._coordinator(temp)
            good = [
                {"logical_state_id": "unit.state", "verification": "VERIFIED_CACHE_SOURCE",
                 "expected_bytes": 100, "observed_bytes": 100},
                {"logical_state_id": "unit.meta", "verification": "VERIFIED_CACHE_SOURCE",
                 "expected_bytes": 13, "observed_bytes": 13},
            ]
            result = authority.reconcile(
                participant_id="unit-node",
                used_artifact_ids=[state_record["artifact_id"], meta_record["artifact_id"]],
                materializations=good)
            self.assertEqual(result["status"], "PLANNED_AND_REALIZED")
            unverified = json.loads(json.dumps(good))
            unverified[0]["verification"] = "UNVERIFIED_PARTIAL"
            with self.assertRaisesRegex(AcquisitionError, "RECONCILIATION_MISMATCH"):
                authority.reconcile(
                    participant_id="unit-node",
                    used_artifact_ids=[state_record["artifact_id"], meta_record["artifact_id"]],
                    materializations=unverified)
            wrong_bytes = json.loads(json.dumps(good))
            wrong_bytes[0]["observed_bytes"] = 99
            with self.assertRaisesRegex(AcquisitionError, "RECONCILIATION_MISMATCH"):
                authority.reconcile(
                    participant_id="unit-node",
                    used_artifact_ids=[state_record["artifact_id"], meta_record["artifact_id"]],
                    materializations=wrong_bytes)


class NodeArtifactCacheTests(unittest.TestCase):
    def test_publish_verifies_and_deduplicates(self):
        with tempfile.TemporaryDirectory() as temp:
            temp = Path(temp)
            cache = NodeArtifactCache(temp / "cache")
            data = b"y" * 100
            record = range_record(Path(temp), "obj.bin", data, 0, 100)
            cache.publish(record, data)
            self.assertIsNotNone(cache.lookup(record["content_digest"]))
            self.assertEqual(cache.open_verified(record), data)
            cache.publish(record, data)  # idempotent cache hit publication

    def test_wrong_bytes_never_publish(self):
        with tempfile.TemporaryDirectory() as temp:
            temp = Path(temp)
            cache = NodeArtifactCache(temp / "cache")
            data = b"y" * 100
            record = range_record(Path(temp), "obj.bin", data, 0, 100)
            with self.assertRaisesRegex(AcquisitionError, "INTEGRITY_DIGEST_MISMATCH"):
                cache.publish(record, b"n" * 100)
            self.assertIsNone(cache.lookup(record["content_digest"]))
            self.assertEqual(cache.inventory()["verified_objects"], [])

    def test_unverified_partial_is_not_a_readable_source(self):
        with tempfile.TemporaryDirectory() as temp:
            temp = Path(temp)
            cache = NodeArtifactCache(temp / "cache")
            data = b"y" * 100
            record = range_record(Path(temp), "obj.bin", data, 0, 100)
            cache.begin_partial(record)
            cache.append_partial(record, data[:40])
            with self.assertRaisesRegex(AcquisitionError, "UNVERIFIED_SOURCE_READ_REFUSED"):
                cache.open_verified(record)
            inventory = cache.inventory()
            self.assertEqual(len(inventory["partial_transfers"]), 1)
            self.assertEqual(inventory["partial_transfers"][0]["retained_bytes"], 40)
            self.assertEqual(inventory["verified_objects"], [])

    def test_tampered_verified_object_detected_on_read(self):
        with tempfile.TemporaryDirectory() as temp:
            temp = Path(temp)
            cache = NodeArtifactCache(temp / "cache")
            data = b"y" * 100
            record = range_record(Path(temp), "obj.bin", data, 0, 100)
            path = cache.publish(record, data)
            path.write_bytes(b"z" * 100)
            with self.assertRaisesRegex(AcquisitionError, "CACHE_OBJECT_TAMPERED"):
                cache.open_verified(record)

    def test_partial_binding_and_finish(self):
        with tempfile.TemporaryDirectory() as temp:
            temp = Path(temp)
            cache = NodeArtifactCache(temp / "cache")
            data = b"y" * 100
            record = range_record(Path(temp), "obj.bin", data, 0, 100)
            cache.begin_partial(record)
            cache.append_partial(record, data[:40])
            self.assertEqual(cache.resume_partial(record), 40)
            cache.append_partial(record, data[40:])
            path = cache.finish_partial(record)
            self.assertTrue(path.is_file())
            self.assertEqual(cache.open_verified(record), data)
            self.assertEqual(cache.inventory()["partial_transfers"], [])

    def test_incomplete_partial_fails_finish(self):
        with tempfile.TemporaryDirectory() as temp:
            temp = Path(temp)
            cache = NodeArtifactCache(temp / "cache")
            data = b"y" * 100
            record = range_record(Path(temp), "obj.bin", data, 0, 100)
            cache.begin_partial(record)
            cache.append_partial(record, data[:40])
            with self.assertRaisesRegex(AcquisitionError, "INTEGRITY_DIGEST_MISMATCH"):
                cache.finish_partial(record)

    def test_foreign_partial_is_discarded_not_stitched(self):
        with tempfile.TemporaryDirectory() as temp:
            temp = Path(temp)
            cache = NodeArtifactCache(temp / "cache")
            data = b"y" * 200
            record = range_record(temp, "obj.bin", data, 0, 100)
            other = range_record(temp, "obj.bin", data, 10, 110)
            cache.begin_partial(record)
            cache.append_partial(record, data[:40])
            # Simulate a mis-bound/stale sidecar: the state stored under
            # `other`'s identity still carries `record`'s binding (and bytes).
            cache._state_path(other["artifact_id"]).write_text(
                cache._state_path(record["artifact_id"]).read_text())
            cache._part_path(other["artifact_id"]).write_bytes(
                cache._part_path(record["artifact_id"]).read_bytes())
            # Resume must refuse the foreign binding, discard, and raise —
            # never stitch `other`'s expected bytes onto `record`'s partial.
            with self.assertRaisesRegex(AcquisitionError, "PARTIAL_STATE_IDENTITY_MISMATCH"):
                cache.resume_partial(other)
            self.assertIsNone(cache.partial_state(other["artifact_id"]))
            self.assertEqual(cache.resume_partial(other), 0)


class SourceTests(unittest.TestCase):
    def test_file_source_reads_ranges_and_fails_missing(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            data = make_object(root, "obj.bin", 256)
            source = LocalFileSource(source_id="op-file", root=root)
            self.assertEqual(source.read({"source_object": "obj.bin"}, 10, 10), data[10:20])
            with self.assertRaisesRegex(AcquisitionError, "SOURCE_OBJECT_UNAVAILABLE"):
                source.read({"source_object": "missing.bin"}, 0, 4)

    def test_http_source_range_read(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            data = make_object(root, "obj.bin", 4096)
            source = LocalHttpSource(source_id="op-http", root=root)
            try:
                self.assertEqual(source.read({"source_object": "obj.bin"}, 100, 200), data[100:300])
                with self.assertRaisesRegex(AcquisitionError, "SOURCE_OBJECT_UNAVAILABLE"):
                    source.read({"source_object": "missing.bin"}, 0, 4)
            finally:
                source.close()

    def test_http_source_controlled_interruption(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            make_object(root, "obj.bin", 4096)
            source = LocalHttpSource(source_id="op-http", root=root)
            try:
                source.interrupt_after["obj.bin"] = 1000
                with self.assertRaises(TransferInterrupted):
                    source.read({"source_object": "obj.bin"}, 0, 4096)
            finally:
                source.close()


class AcquireArtifactTests(unittest.TestCase):
    def _setup(self, temp: Path):
        root = temp / "repo"
        data = make_object(root, "obj.bin", 150_000)
        meta = (root / "meta.json")
        meta.write_bytes(b'{"layers": 4}')
        # Non-zero byte_start proves artifact-relative offsets map onto
        # object-absolute positions correctly.
        state_record = range_record(root, "obj.bin", data, 10_000, 130_000)
        meta_record = whole_record("meta.json", meta.read_bytes())

        def resolver(requirement_class, requirement_id):
            return {"unit.state": [state_record], "unit.meta": [meta_record]}.get(
                requirement_id, [])

        plan = unit_plan([participant()])
        requirements = derive_participant_requirements(plan, resolver)
        return {
            "data": data, "state_record": state_record, "meta_record": meta_record,
            "plan": plan, "requirements": requirements, "root": root,
        }

    def _authority(self, fixture, source_id="op-http"):
        return CoordinatorAuthority(
            plan=fixture["plan"], requirements=fixture["requirements"],
            eligible_sources=[{"source_id": source_id, "endpoint": "http://127.0.0.1:1"}])

    def test_fresh_acquire_then_cache_hit(self):
        with tempfile.TemporaryDirectory() as temp:
            temp = Path(temp)
            fixture = self._setup(temp)
            http = LocalHttpSource(source_id="op-http", root=fixture["root"])
            try:
                cache = NodeArtifactCache(temp / "node-cache")
                ledger = AcquisitionLedger()
                authority = self._authority(fixture)
                result = acquire_artifact(
                    cache=cache, source=http, record=fixture["state_record"],
                    authorization=authority, participant_id="unit-node", ledger=ledger,
                    chunk_bytes=32_768)
                self.assertEqual(result["status"], "ACQUIRED")
                self.assertEqual(result["bytes"], 120_000)
                hit = acquire_artifact(
                    cache=cache, source=http, record=fixture["state_record"],
                    authorization=authority, participant_id="unit-node", ledger=ledger)
                self.assertEqual(hit["status"], "CACHE_HIT")
                records = {fixture["state_record"]["content_digest"]: fixture["state_record"]}
                participants = {"unit-node": {
                    "required_artifact_bytes": 120_000 + 13,
                    "declared_state_ids": ["unit.state", "unit.meta"],
                }}
                aggregate = ledger.document(
                    records_by_digest=records, participants=participants)["aggregate"]
                self.assertEqual(aggregate["newly_acquired_bytes"], 120_000)
                self.assertEqual(aggregate["verified_cache_hit_bytes"], 120_000)
                self.assertEqual(aggregate["acquired_bytes_by_source"], {"op-http": 120_000})
                self.assertEqual(aggregate["unrelated_model_bytes_acquired_for_realization"], 0)
                self.assertEqual(aggregate["unexplained_full_model_dependency"], 0)
            finally:
                http.close()

    def test_corrupt_transfer_fails_closed_and_publishes_nothing(self):
        with tempfile.TemporaryDirectory() as temp:
            temp = Path(temp)
            fixture = self._setup(temp)
            http = LocalHttpSource(source_id="op-http", root=fixture["root"])
            try:
                http.corrupt_at["obj.bin"] = 60_000
                cache = NodeArtifactCache(temp / "node-cache")
                ledger = AcquisitionLedger()
                authority = self._authority(fixture)
                with self.assertRaisesRegex(AcquisitionError, "INTEGRITY_DIGEST_MISMATCH"):
                    acquire_artifact(
                        cache=cache, source=http, record=fixture["state_record"],
                        authorization=authority, participant_id="unit-node", ledger=ledger,
                        chunk_bytes=32_768)
                self.assertIsNone(cache.lookup(fixture["state_record"]["content_digest"]))
                self.assertEqual(cache.inventory()["partial_transfers"], [])
                self.assertIn(
                    "INTEGRITY_DIGEST_MISMATCH",
                    ledger.document()["aggregate"]["integrity_failures"])
            finally:
                http.close()

    def test_interrupted_transfer_resumes_from_bound_partial(self):
        with tempfile.TemporaryDirectory() as temp:
            temp = Path(temp)
            fixture = self._setup(temp)
            http = LocalHttpSource(source_id="op-http", root=fixture["root"])
            try:
                cache = NodeArtifactCache(temp / "node-cache")
                ledger = AcquisitionLedger()
                authority = self._authority(fixture)
                http.interrupt_after["obj.bin"] = 60_000
                first = acquire_artifact(
                    cache=cache, source=http, record=fixture["state_record"],
                    authorization=authority, participant_id="unit-node", ledger=ledger,
                    chunk_bytes=60_000)
                self.assertEqual(first["status"], "INTERRUPTED")
                self.assertEqual(first["retained_bytes"], 50_000)
                del http.interrupt_after["obj.bin"]
                second = acquire_artifact(
                    cache=cache, source=http, record=fixture["state_record"],
                    authorization=authority, participant_id="unit-node", ledger=ledger,
                    chunk_bytes=60_000)
                self.assertEqual(second["status"], "ACQUIRED")
                self.assertEqual(second["bytes"], 70_000)
                self.assertEqual(cache.open_verified(fixture["state_record"]),
                                 fixture["data"][10_000:130_000])
                aggregate = ledger.document()["aggregate"]
                self.assertEqual(aggregate["resume_reused_prefix_bytes"], 50_000)
                self.assertEqual(aggregate["retry_resume_transfer_bytes"], 70_000)
            finally:
                http.close()

    def test_foreign_partial_state_is_discarded_and_restarted(self):
        with tempfile.TemporaryDirectory() as temp:
            temp = Path(temp)
            fixture = self._setup(temp)
            http = LocalHttpSource(source_id="op-http", root=fixture["root"])
            try:
                cache = NodeArtifactCache(temp / "node-cache")
                # A stale partial bound to a DIFFERENT artifact identity sits
                # at the acquired artifact's cache location (mis-bound
                # sidecar). Acquisition must discard it, restart from zero,
                # and never stitch the retained bytes.
                foreign = range_record(temp, "obj.bin", fixture["data"], 1, 120_001)
                cache.begin_partial(foreign)
                cache.append_partial(foreign, fixture["data"][1:30_001])
                misbound_state = cache._state_path(foreign["artifact_id"]).read_text()
                misbound_part = cache._part_path(foreign["artifact_id"]).read_bytes()
                cache.discard_partial(foreign["artifact_id"])
                cache._state_path(fixture["state_record"]["artifact_id"]).write_text(
                    misbound_state)
                cache._part_path(fixture["state_record"]["artifact_id"]).write_bytes(
                    misbound_part)
                ledger = AcquisitionLedger()
                authority = self._authority(fixture)
                result = acquire_artifact(
                    cache=cache, source=http, record=fixture["state_record"],
                    authorization=authority, participant_id="unit-node", ledger=ledger,
                    chunk_bytes=60_000)
                self.assertEqual(result["status"], "ACQUIRED")
                self.assertEqual(result["bytes"], 120_000)
                events = [e["event"] for e in ledger.document()["events"]]
                self.assertIn("PARTIAL_DISCARDED", events)
                self.assertNotIn("RESUME_REUSED_PREFIX", events)
                self.assertEqual(cache.open_verified(fixture["state_record"]),
                                 fixture["data"][10_000:130_000])
            finally:
                http.close()

    def test_unauthorized_source_refused_before_any_bytes_move(self):
        with tempfile.TemporaryDirectory() as temp:
            temp = Path(temp)
            fixture = self._setup(temp)
            http = LocalHttpSource(source_id="op-http", root=fixture["root"])
            file_source = LocalFileSource(source_id="op-file", root=fixture["root"])
            try:
                # Only the HTTP source is authorized; the file source is a
                # present-but-ineligible Source with identical bytes.
                authority = self._authority(fixture, source_id="op-http")
                cache = NodeArtifactCache(temp / "node-cache")
                ledger = AcquisitionLedger()
                with self.assertRaisesRegex(AcquisitionError, "SOURCE_UNAUTHORIZED"):
                    acquire_artifact(
                        cache=cache, source=file_source, record=fixture["state_record"],
                        authorization=authority, participant_id="unit-node", ledger=ledger)
                self.assertEqual(http.access_log, [])
                self.assertEqual(file_source.access_log, [])
                self.assertEqual(cache.inventory()["verified_objects"], [])
            finally:
                http.close()

    def test_whole_object_ranges_guard_detects_hidden_full_model(self):
        data = b"z" * 300
        left = range_record(Path("/tmp"), "shard.bin", data, 0, 150, state_id="a")
        right = range_record(Path("/tmp"), "shard.bin", data, 150, 300, state_id="b")
        self.assertEqual(_unexplained_full_object_bytes([left, right]), 300)
        with self.assertRaisesRegex(
                AcquisitionError, "UPSTREAM_OBJECT_FULLY_ACQUIRED_WITHOUT_DECLARATION"):
            guard_full_object_acquisition([left, right])
        partial = range_record(Path("/tmp"), "shard.bin", data, 0, 150, state_id="a")
        self.assertEqual(_unexplained_full_object_bytes([partial]), 0)
        metadata = whole_record("meta.json", b'{}')
        self.assertEqual(_unexplained_full_object_bytes([metadata]), 0)


class CoreBoundaryTests(unittest.TestCase):
    """The generic control plane must stay model-independent (ADR 0009)."""

    FORBIDDEN_TEXT = ("safetensors", "has_complete_model_repository", "qwen", "gemma",
                      "huggingface")

    def test_core_source_has_no_model_family_nouns(self):
        source = (SCRIPTS / "issue99_artifact_core.py").read_text()
        for forbidden in self.FORBIDDEN_TEXT:
            self.assertNotIn(forbidden, source.lower())

    def test_core_identifiers_have_no_model_nouns(self):
        tree = ast.parse((SCRIPTS / "issue99_artifact_core.py").read_text())
        identifiers = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                identifiers.add(node.id)
            elif isinstance(node, ast.Attribute):
                identifiers.add(node.attr)
            elif isinstance(node, ast.arg):
                identifiers.add(node.arg)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                identifiers.add(node.name)
        model_nouns = {"tensor", "layer", "checkpoint", "logits", "token", "lm_head",
                       "embedding", "expert", "shard"}
        self.assertFalse(identifiers & model_nouns, identifiers & model_nouns)

    def test_core_imports_stdlib_only(self):
        tree = ast.parse((SCRIPTS / "issue99_artifact_core.py").read_text())
        modules = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules.add(node.module.split(".")[0])
        self.assertEqual(modules - {"__future__"}, {
            "hashlib", "json", "os", "threading", "time", "urllib", "http",
            "pathlib", "typing", "issue74_methodology"})


if __name__ == "__main__":
    unittest.main()
