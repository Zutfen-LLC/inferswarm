"""Focused tests for the issue #117 integration fixture rule."""
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
import sys  # noqa: E402

sys.path.insert(0, str(ROOT / "scripts"))

import issue117_integration_fixture as fixture  # noqa: E402

CORPUS = ROOT / "docs/qualification/gemma4-12b-it-v5/manifests/calibration-corpus.json"


class IntegrationFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.document = fixture.build_fixture_document(CORPUS)

    def test_selects_exactly_one_case_per_component(self):
        self.assertEqual(fixture.EXPECTED_COMPONENT_COUNT, len(self.document["cases"]))
        components = [
            (identity[0], tuple(identity[1]))
            for identity in (json.loads(entry["component"]) for entry in self.document["cases"])
        ]
        self.assertEqual(len(components), len(set(components)))
        # the selected component identities must equal the corpus's frozen set
        corpus = json.loads(CORPUS.read_text())
        expected = {
            (c["content_class"], (int(c["length_regime"][0]), int(c["length_regime"][1])))
            for c in corpus["mixture_population"]["components"]
        }
        self.assertEqual(expected, set(components))

    def test_only_public_c109_cases(self):
        for entry in self.document["cases"]:
            self.assertTrue(entry["case"]["case_id"].startswith("c109-"))

    def test_selection_follows_seed_rule(self):
        for entry in self.document["cases"]:
            expected = fixture.selection_digest(entry["case"]["case_id"])
            self.assertEqual(expected, entry["selection_sha256"])

    def test_selection_is_minimum_over_component(self):
        corpus = json.loads(CORPUS.read_text())
        by_id = {c["case_id"]: c for c in corpus["cases"]}
        for entry in self.document["cases"]:
            component = json.loads(entry["component"])
            peers = [
                c for c in corpus["cases"]
                if c["content_class"] == component[0]
                and [int(c["length_regime"][0]), int(c["length_regime"][1])] == component[1]
            ]
            best = min(peers, key=lambda c: (fixture.selection_digest(c["case_id"]), c["case_id"]))
            self.assertEqual(best["case_id"], entry["case"]["case_id"])

    def test_case_hashes_match_accepted_generator_rule(self):
        for entry in self.document["cases"]:
            recomputed = fixture.recompute_case_hashes(entry["case"])
            for field, value in recomputed.items():
                self.assertEqual(entry["case"][field], value, field)

    def test_document_is_deterministic_and_self_consistent(self):
        again = fixture.build_fixture_document(CORPUS)
        self.assertEqual(self.document, again)
        fixture.validate_fixture_document(self.document)

    def test_validation_rejects_tampered_case_bytes(self):
        tampered = json.loads(json.dumps(self.document))
        tampered["cases"][0]["case"]["prompt_text"] += " tampered"
        with self.assertRaises(fixture.FixtureBlocked):
            fixture.validate_fixture_document(tampered)

    def test_validation_rejects_wrong_selection_digest(self):
        tampered = json.loads(json.dumps(self.document))
        tampered["cases"][3]["selection_sha256"] = "0" * 64
        with self.assertRaises(fixture.FixtureBlocked):
            fixture.validate_fixture_document(tampered)

    def test_validation_rejects_stale_fixture_digest(self):
        tampered = json.loads(json.dumps(self.document))
        tampered["purpose"] = "rewritten"
        with self.assertRaises(fixture.FixtureBlocked):
            fixture.validate_fixture_document(tampered)

    def test_rejects_h109_contamination(self):
        with tempfile.TemporaryDirectory() as temp:
            corpus = json.loads(CORPUS.read_text())
            corpus["cases"][0]["case_id"] = "h109-99-99-999"
            path = Path(temp) / "corpus.json"
            path.write_text(json.dumps(corpus))
            with self.assertRaises(fixture.FixtureBlocked):
                fixture.build_fixture_document(path)

    def test_blocks_when_component_has_no_public_case(self):
        with tempfile.TemporaryDirectory() as temp:
            corpus = json.loads(CORPUS.read_text())
            component = corpus["mixture_population"]["components"][0]
            survivor = corpus["mixture_population"]["components"][1]

            def in_component(case, comp):
                return (case["content_class"] == comp["content_class"]
                        and [int(case["length_regime"][0]), int(case["length_regime"][1])]
                        == [int(comp["length_regime"][0]), int(comp["length_regime"][1])])

            # relabel the component's cases into the survivor component so the
            # case count stays exact while the component loses every case
            for case in corpus["cases"]:
                if in_component(case, component):
                    case["content_class"] = survivor["content_class"]
                    case["length_regime"] = [int(survivor["length_regime"][0]),
                                             int(survivor["length_regime"][1])]
                    recomputed = fixture.recompute_case_hashes(case)
                    case["case_sha256"] = recomputed["case_sha256"]
            path = Path(temp) / "corpus.json"
            path.write_text(json.dumps(corpus))
            with self.assertRaisesRegex(fixture.FixtureBlocked, "FIXTURE_CONSTRUCTION_BLOCKED"):
                fixture.build_fixture_document(path)

    def test_rejects_wrong_case_count(self):
        with tempfile.TemporaryDirectory() as temp:
            corpus = json.loads(CORPUS.read_text())
            corpus["cases"] = corpus["cases"][:100]
            path = Path(temp) / "corpus.json"
            path.write_text(json.dumps(corpus))
            with self.assertRaisesRegex(fixture.FixtureBlocked, "1416"):
                fixture.build_fixture_document(path)

    def test_rejects_wrong_schema(self):
        with tempfile.TemporaryDirectory() as temp:
            corpus = json.loads(CORPUS.read_text())
            corpus["schema"] = "something.else/9"
            path = Path(temp) / "corpus.json"
            path.write_text(json.dumps(corpus))
            with self.assertRaises(fixture.FixtureBlocked):
                fixture.build_fixture_document(path)


if __name__ == "__main__":
    unittest.main()
