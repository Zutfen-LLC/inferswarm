"""InferSwarm #170 — Arm-C long-remainder public corpus freeze tests.

CPU-only, pure stdlib. Every fact asserted here is re-derived from
hash-pinned committed bytes (corpus.json, authority-record.json,
terminal-reduction.json, the accepted fixture/corpus bytes), never
from narrative. Negative controls mutate copies of the real records
and require the terminal reducer to fail closed on exactly the
mutated check.

The tokenizer-bound generation determinism itself (byte-deterministic
output from the frozen public seed/source/tokenizer) is proven by the
producer; this suite pins the retained bytes, re-runs the stdlib
reducer, and re-derives every structural property.
"""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / (
    "docs/implementation/r6-successor-arm-c-long-remainder-corpus-170")
EVIDENCE = BUNDLE / "evidence"
CORPUS = EVIDENCE / "corpus.json"
AUTHORITY = EVIDENCE / "authority-record.json"
TERMINAL = EVIDENCE / "terminal-reduction.json"
BLOCKER = ROOT / (
    "docs/implementation/r6-successor-arm-c-requal-blocked-168/"
    "evidence/terminal-reduction.json")
FIXTURE = ROOT / (
    "docs/implementation/r6-successor-dense-full-integration-117/"
    "evidence/arm-c-retry/prompt-fixture.json")
HIST_CALIBRATION = ROOT / (
    "docs/qualification/gemma4-12b-it-v5/manifests/"
    "calibration-corpus.json")

SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


M = _load("issue170_corpus_methodology",
          SCRIPTS / "issue170_corpus_methodology.py")
REDUCER = _load("issue170_terminal_reduction",
                SCRIPTS / "issue170_terminal_reduction.py")

#: independent cross-check pins (a literal here is correct: it guards
#: against mutation of the authority modules themselves)
FIXTURE_DIGEST_24 = (
    "sha256:180185cd5c6a5dcd77b2c65979bd2c9aef4d1c7ea9fb4850a64f4508b2ba36f2")
STARTING_MAIN = "941d0fe52ecedff1c5294a5582af3fedecb1018e"
FREETOKEN_RESEARCH = (
    "6202eeebcdf63e7bc8bb3498dd3c364ae42ee469")
FROZEN = "ISSUE117_ARM_C_LONG_REMAINDER_CORPUS_FROZEN"

CORPUS_DATA = json.loads(CORPUS.read_text())
AUTHORITY_DATA = json.loads(AUTHORITY.read_text())


def corpus_digest(cases) -> str:
    return "sha256:" + hashlib.sha256(json.dumps(
        cases, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class TempEvidence:
    """Copy the retained evidence into a tmp dir, mutate, reduce."""

    def __init__(self, corpus=None, authority=None):
        self.dir = tempfile.mkdtemp(prefix="issue170-")
        base = Path(self.dir)
        data = {"corpus.json": corpus if corpus is not None
                else copy.deepcopy(CORPUS_DATA),
                "authority-record.json": authority if authority is not None
                else copy.deepcopy(AUTHORITY_DATA)}
        for name, value in data.items():
            (base / name).write_text(
                json.dumps(value, sort_keys=True, indent=1) + "\n")

    def reduce(self):
        return REDUCER.reduce_terminal(Path(self.dir), ROOT)


class CorpusStructure(unittest.TestCase):
    def test_terminal_frozen_and_mechanically_rederived(self):
        result = REDUCER.reduce_terminal(EVIDENCE, ROOT)
        self.assertEqual(result["verdict"], FROZEN)
        self.assertEqual(
            json.loads(TERMINAL.read_text())["verdict"], FROZEN)

    def test_exactly_16_unique_cases(self):
        cases = CORPUS_DATA["cases"]
        self.assertEqual(len(cases), 16)
        self.assertEqual(len({c["case_id"] for c in cases}), 16)
        self.assertEqual(
            len({c["prompt_sha256"] for c in cases}), 16)
        self.assertEqual(
            len({c["rendered_ids_sha256"] for c in cases}), 16)

    def test_exact_target_lengths_and_remainders(self):
        cases = CORPUS_DATA["cases"]
        self.assertEqual(
            sorted(c["rendered_length"] for c in cases),
            list(M.TARGET_RENDERED_LENGTHS))
        for case in cases:
            self.assertEqual(
                case["rendered_length"],
                len(case["rendered_prompt_token_ids"]))
            self.assertEqual(
                case["second_chunk_remainder"],
                case["rendered_length"] - 64)
            self.assertEqual(
                case["second_chunk_remainder"],
                M.TARGET_REMAINDERS[case["target_ordinal"]])

    def test_four_cases_per_bucket(self):
        counts = {name: 0 for name, _, _ in M.BUCKETS}
        for case in CORPUS_DATA["cases"]:
            counts[M.bucket_of(case["second_chunk_remainder"])] += 1
        self.assertEqual(counts, {"1-8": 4, "9-24": 4,
                                  "25-48": 4, "49-64": 4})

    def test_every_case_two_prefill_chunks(self):
        for case in CORPUS_DATA["cases"]:
            self.assertGreater(case["rendered_length"], 64)
            self.assertLessEqual(case["rendered_length"], 128)

    def test_six_classes_at_least_twice(self):
        from issue74_methodology import CONTENT_CLASSES
        counts = {name: 0 for name in CONTENT_CLASSES}
        for case in CORPUS_DATA["cases"]:
            self.assertIn(case["content_class"], counts)
            counts[case["content_class"]] += 1
        for name, count in counts.items():
            self.assertGreaterEqual(count, 2, name)

    def test_content_class_assignment_follows_frozen_rule(self):
        from issue74_methodology import CONTENT_CLASSES
        for case in CORPUS_DATA["cases"]:
            self.assertEqual(
                case["content_class"],
                M.assigned_content_class(
                    case["target_ordinal"], CONTENT_CLASSES))

    def test_canonical_corpus_digest_pinned(self):
        self.assertEqual(
            CORPUS_DATA["canonical_corpus_digest"],
            corpus_digest(CORPUS_DATA["cases"]))

    def test_preflight_24_24_and_fixture_binding(self):
        pre = CORPUS_DATA["preflight_24_render_reproduction"]
        self.assertEqual(pre["renders_reproduced"], 24)
        self.assertEqual(pre["accepted_fixture_digest"],
                         FIXTURE_DIGEST_24)

    def test_generator_and_methodology_hashes_recorded(self):
        for rel, key in (
                ("scripts/issue170_corpus_producer.py",
                 "generator_sha256"),
                ("scripts/issue170_corpus_methodology.py",
                 "methodology_sha256")):
            expected = hashlib.sha256(
                (ROOT / rel).read_bytes()).hexdigest()
            self.assertEqual(CORPUS_DATA[key], expected)

    def test_seed_and_namespace_frozen(self):
        self.assertEqual(
            CORPUS_DATA["seed"],
            "issue170-arm-c-long-remainder-corpus-v1")
        self.assertEqual(CORPUS_DATA["case_prefix"], "g170-")
        self.assertEqual(CORPUS_DATA["search"]["search_ceiling"], 4096)
        self.assertEqual(
            CORPUS_DATA["search"]["wrapper_delta_order"], [13, 12])

    def test_attempt_metadata_within_ceiling(self):
        for case in CORPUS_DATA["cases"]:
            self.assertGreaterEqual(case["accepted_nonce"], 0)
            self.assertLess(case["accepted_nonce"], 4096)

    def test_accepted_168_blocker_consumed_unchanged(self):
        blocker = json.loads(BLOCKER.read_text())
        self.assertEqual(
            blocker["verdict"],
            "ISSUE117_ARM_C_REQUALIFICATION_EVIDENCE_BLOCKED")
        chain = AUTHORITY_DATA["accepted_authority_chain"]
        self.assertEqual(chain[-1]["issue"], 168)
        self.assertTrue(chain[-1]["consumed_not_reinterpreted"])

    def test_starting_heads(self):
        heads = AUTHORITY_DATA["starting_heads"]
        self.assertEqual(heads["inferswarm_main"], STARTING_MAIN)
        self.assertEqual(
            heads["freetoken_inferswarm_research"],
            FREETOKEN_RESEARCH)
        self.assertTrue(heads["verified"])
        self.assertTrue(all(heads["ancestor_proofs"].values()))


class Disjointness(unittest.TestCase):
    def test_no_public_historical_collision(self):
        exclusions = REDUCER.public_exclusion_digests(ROOT)
        self.assertGreater(len(exclusions), 2800)
        for case in CORPUS_DATA["cases"]:
            for value in (case["prompt_sha256"],
                          case["raw_token_ids_sha256"],
                          case["rendered_ids_sha256"]):
                self.assertNotIn(value, exclusions, case["case_id"])

    def test_exclusion_inventory_covers_all_namespaces(self):
        namespaces = CORPUS_DATA["exclusions"]["namespaces"]
        self.assertEqual(
            namespaces["c109_calibration"]["case_count"], 1416)
        self.assertGreater(
            namespaces["p109_stress_pool"]["case_count"], 0)
        self.assertEqual(
            namespaces["accepted_133_fixture"]["case_count"], 24)
        self.assertEqual(
            namespaces["accepted_157_anchor_control"]
            ["case_ids"],
            ["c109-03-04-003", "c109-04-02-047", "c109-04-06-074"])


class Purity(unittest.TestCase):
    def test_no_h109_in_retained_bytes(self):
        import re
        for path in (CORPUS, AUTHORITY, TERMINAL):
            text = path.read_text()
            refs = re.findall(r"h109-[0-9A-Za-z_]", text)
            self.assertEqual(refs, [], str(path))

    def test_stdlib_modules_import_no_runtime(self):
        for name, banned in (
                ("issue170_corpus_methodology.py",
                 ("torch", "transformers", "tokenizers", "freetoken")),
                ("issue170_terminal_reduction.py",
                 ("torch", "transformers", "tokenizers", "freetoken")),
                ("issue170_authority_record.py",
                 ("torch", "transformers", "tokenizers", "freetoken"))):
            source = (SCRIPTS / name).read_text()
            for module in banned:
                self.assertNotRegex(
                    source, rf"^\s*import {module}\b",
                    f"{name} imports {module}")
                self.assertNotRegex(
                    source, rf"^\s*from {module}\b",
                    f"{name} imports {module}")

    def test_no_gpu_or_execution_claim(self):
        self.assertFalse(
            AUTHORITY_DATA["physical_execution"]["performed"])
        for case in CORPUS_DATA["cases"]:
            self.assertNotIn("cuda", json.dumps(case).lower())
            self.assertNotIn("gpu", json.dumps(case).lower())


class Manifest(unittest.TestCase):
    def test_manifest_covers_all_evidence(self):
        lines = (EVIDENCE / "MANIFEST.sha256").read_text().splitlines()
        listed = {}
        for line in lines:
            digest, rel = line.split("  ", 1)
            listed[rel] = digest
        for path in sorted(EVIDENCE.rglob("*")):
            if path.is_file() and path.name != "MANIFEST.sha256":
                rel = str(path.relative_to(ROOT))
                self.assertIn(rel, listed)
                self.assertEqual(
                    listed[rel],
                    hashlib.sha256(path.read_bytes()).hexdigest())

    def test_producer_hashes_pinned(self):
        record = json.loads(
            (EVIDENCE / "producer-hashes.json").read_text())
        for rel, digest in record["producers"].items():
            self.assertEqual(
                digest,
                hashlib.sha256((ROOT / rel).read_bytes()).hexdigest())


def _mutated_corpus(**kwargs):
    data = copy.deepcopy(CORPUS_DATA)
    for key, value in kwargs.items():
        data[key] = value
    return data


class NegativeControls(unittest.TestCase):
    """Every mandated mutation must make the reducer fail closed."""

    def _assert_fails(self, corpus=None, authority=None,
                      needle=None) -> None:
        ev = TempEvidence(corpus=corpus, authority=authority)
        result = ev.reduce()
        self.assertEqual(
            result["verdict"], "CORPUS_REDUCTION_FAILED",
            f"mutation unexpectedly passed: {result}")
        if needle:
            self.assertTrue(
                any(needle in f for f in result["failures"]),
                f"expected failure about {needle!r}; got "
                f"{result['failures']}")

    def test_missing_case_fails(self):
        data = _mutated_corpus()
        data["cases"] = data["cases"][:15]
        self._assert_fails(corpus=data, needle="exactly 16")

    def test_duplicate_case_fails(self):
        data = _mutated_corpus()
        data["cases"][1] = copy.deepcopy(data["cases"][0])
        self._assert_fails(corpus=data, needle="duplicate")

    def test_altered_target_length_fails(self):
        data = _mutated_corpus()
        case = data["cases"][0]
        case["rendered_prompt_token_ids"] = (
            case["rendered_prompt_token_ids"] + [5])
        case["rendered_length"] += 1
        self._assert_fails(corpus=data)

    def test_target_length_sequence_drift_fails(self):
        data = _mutated_corpus()
        data["target_rendered_lengths"] = list(
            M.TARGET_RENDERED_LENGTHS)
        data["target_rendered_lengths"][0] = 66
        self._assert_fails(corpus=data, needle="frozen 16-value")

    def test_wrong_remainder_fails(self):
        data = _mutated_corpus()
        data["cases"][0]["second_chunk_remainder"] = 2
        self._assert_fails(corpus=data, needle="remainder")

    def test_wrong_bucket_fails(self):
        data = _mutated_corpus()
        data["cases"][0]["bucket"] = "9-24"
        self._assert_fails(corpus=data, needle="bucket membership")

    def test_changed_seed_fails(self):
        data = _mutated_corpus()
        data["seed"] = "issue170-arm-c-long-remainder-corpus-v2"
        self._assert_fails(corpus=data, needle="seed drift")

    def test_changed_class_assignment_fails(self):
        data = _mutated_corpus()
        data["cases"][0]["content_class"] = "ordinary-prose"
        self._assert_fails(corpus=data, needle="assignment rule")

    def test_class_coverage_below_two_fails(self):
        # swap two classes so one appears only once
        data = _mutated_corpus()
        ords = {c["target_ordinal"]: c for c in data["cases"]}
        # multilingual-text appears at ordinals 5 and 11; change 11
        ords[11]["content_class"] = "ordinary-prose"
        self._assert_fails(corpus=data, needle="fewer than twice")

    def test_search_ceiling_drift_fails(self):
        data = _mutated_corpus()
        data["search"]["search_ceiling"] = 8192
        self._assert_fails(corpus=data, needle="search ceiling")

    def test_search_order_drift_fails(self):
        data = _mutated_corpus()
        data["search"]["wrapper_delta_order"] = [12, 13]
        self._assert_fails(corpus=data, needle="search order")

    def test_tokenizer_identity_drift_fails(self):
        data = _mutated_corpus()
        data["tokenizer"]["identity_verified"]["transformers"] = "4.0.0"
        self._assert_fails(corpus=data, needle="software identity")

    def test_preflight_drift_fails(self):
        data = _mutated_corpus()
        data["preflight_24_render_reproduction"][
            "renders_reproduced"] = 23
        self._assert_fails(corpus=data, needle="preflight")

    def test_historical_collision_fails(self):
        data = _mutated_corpus()
        calibration = json.loads(HIST_CALIBRATION.read_text())
        historic = next(c for c in calibration["cases"]
                        if c["case_id"].startswith("c109-"))
        data["cases"][0]["prompt_sha256"] = historic["prompt_sha256"]
        self._assert_fails(corpus=data, needle="collides")

    def test_corpus_digest_mutation_fails(self):
        data = _mutated_corpus()
        data["canonical_corpus_digest"] = (
            "sha256:" + "0" * 64)
        self._assert_fails(corpus=data, needle="digest drift")

    def test_case_digest_mutation_fails(self):
        data = _mutated_corpus()
        data["cases"][2]["prompt_text"] += " mutation"
        self._assert_fails(corpus=data, needle="prompt digest drift")

    def test_h109_reference_fails(self):
        data = _mutated_corpus()
        data["cases"][0]["prompt_text"] = "h109-01-01-001 leak"
        data["cases"][0]["prompt_sha256"] = hashlib.sha256(
            data["cases"][0]["prompt_text"].encode()).hexdigest()
        self._assert_fails(corpus=data, needle="h109")

    def test_execution_claim_fails(self):
        authority = copy.deepcopy(AUTHORITY_DATA)
        authority["physical_execution"]["performed"] = True
        self._assert_fails(authority=authority,
                           needle="physical execution")

    def test_heads_not_verified_fails(self):
        authority = copy.deepcopy(AUTHORITY_DATA)
        authority["starting_heads"]["verified"] = False
        self._assert_fails(authority=authority,
                           needle="starting heads")

    def test_blocker_terminal_not_consumed_fails(self):
        authority = copy.deepcopy(AUTHORITY_DATA)
        authority["accepted_authority_chain"][-1]["terminal"] = "OTHER"
        self._assert_fails(authority=authority,
                           needle="blocker terminal")

    def test_hypothetical_sufficient_corpus_still_frozen(self):
        # a corpus whose buckets/lengths are all valid MUST reduce to
        # FROZEN (the reducer is not a rubber stamp the other way)
        result = REDUCER.reduce_terminal(EVIDENCE, ROOT)
        self.assertEqual(result["verdict"], FROZEN)

    def test_row_boundary_drift_fails(self):
        data = _mutated_corpus()
        data["row_boundary"] = 32
        self._assert_fails(corpus=data, needle="row boundary")


class PredecessorPreservation(unittest.TestCase):
    """Predecessor evidence bytes are untouched (spot-bound)."""

    def test_168_bundle_manifest_verifies(self):
        blocker_dir = ROOT / (
            "docs/implementation/r6-successor-arm-c-requal-blocked-168/"
            "evidence")
        for line in (blocker_dir / "MANIFEST.sha256").read_text() \
                .splitlines():
            digest, rel = line.split("  ", 1)
            path = ROOT / rel
            self.assertEqual(
                digest,
                hashlib.sha256(path.read_bytes()).hexdigest(), rel)

    def test_accepted_fixture_digest_unchanged(self):
        fixture = json.loads(FIXTURE.read_text())
        self.assertEqual(len(fixture["cases"]), 24)
        integration = json.loads((ROOT / (
            "docs/implementation/r6-successor-dense-full-integration-117"
            "/evidence/integration-fixture.json")).read_text())
        self.assertEqual(
            integration["fixture_digest"], FIXTURE_DIGEST_24)


if __name__ == "__main__":
    unittest.main()
