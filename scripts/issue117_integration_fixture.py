#!/usr/bin/env python3
"""Issue #117 prospective integration fixture (CPU-only, fail-closed).

Selects exactly one public case from each of the frozen 24-component v5
mixture-population components out of the accepted public ``c109-*``
calibration corpus. Within a component the case is chosen deterministically
by ascending ``sha256(SEED_LINE + case_id)``; ties (identical digest) break
by ascending ``case_id``. The fixture is an integration regression set only:
it makes no statistical qualification claim and contributes no new v5
threshold evidence. Consumed ``h109-*`` holdout material is never read.

If any component has no public c109 case the construction stops with
``FIXTURE_CONSTRUCTION_BLOCKED`` instead of silently changing the rule.

Pure stdlib; never imports torch, transformers, CUDA, or any runtime.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

from issue74_methodology import canonical_json_bytes
from issue99_artifact_core import self_digest, write_canonical_json

SEED_LINE = "issue117-integration-fixture-v1\n"
FIXTURE_SCHEMA = "inferswarm.issue117.integration-fixture/1"
CORPUS_SCHEMA = "inferswarm.issue109.v5-calibration-corpus/1"
EXPECTED_COMPONENT_COUNT = 24
EXPECTED_CASE_COUNT = 1416
CASE_FIELDS = (
    "case_id", "case_sha256", "content_class", "draw_index",
    "historical_rejection_attempt", "length_regime", "prompt_sha256",
    "prompt_text", "token_count", "token_ids", "token_ids_sha256",
)


class FixtureBlocked(RuntimeError):
    """The fixture rule cannot be applied honestly to the supplied corpus."""


def selection_digest(case_id: str, *, seed_line: str = SEED_LINE) -> str:
    return hashlib.sha256((seed_line + case_id).encode()).hexdigest()


def recompute_case_hashes(case: Mapping[str, Any]) -> dict[str, str]:
    """Recompute the accepted generator's case identity hashes (no tokenizer)."""
    identity = {
        "content_class": case["content_class"],
        "length_regime": [int(case["length_regime"][0]), int(case["length_regime"][1])],
        "prompt_text": case["prompt_text"],
        "token_ids": case["token_ids"],
    }
    return {
        "prompt_sha256": hashlib.sha256(case["prompt_text"].encode("utf-8")).hexdigest(),
        "token_ids_sha256": hashlib.sha256(
            canonical_json_bytes(case["token_ids"])).hexdigest(),
        "case_sha256": hashlib.sha256(canonical_json_bytes(identity)).hexdigest(),
    }


def verify_case_hashes(case: Mapping[str, Any]) -> None:
    recomputed = recompute_case_hashes(case)
    for field, expected in recomputed.items():
        if case[field] != expected:
            raise FixtureBlocked(f"case {case['case_id']}: {field} mismatch against accepted generator rule")


def _component_key(case: Mapping[str, Any]) -> str:
    regime = case["length_regime"]
    if not isinstance(regime, list) or len(regime) != 2:
        raise FixtureBlocked(f"case {case.get('case_id')}: malformed length_regime")
    return canonical_json_bytes([case["content_class"], [int(regime[0]), int(regime[1])]]).decode()


def _load_corpus(corpus_path: Path) -> dict[str, Any]:
    raw = corpus_path.read_bytes()
    try:
        document = json.loads(raw)
    except json.JSONDecodeError as error:
        raise FixtureBlocked(f"corpus is not JSON: {error}") from error
    if document.get("schema") != CORPUS_SCHEMA:
        raise FixtureBlocked(f"unexpected corpus schema {document.get('schema')!r}")
    cases = document.get("cases")
    if not isinstance(cases, list) or len(cases) != EXPECTED_CASE_COUNT:
        raise FixtureBlocked(
            f"expected {EXPECTED_CASE_COUNT} public calibration cases, found "
            f"{len(cases) if isinstance(cases, list) else type(cases)}")
    components = document.get("mixture_population", {}).get("components")
    if not isinstance(components, list) or len(components) != EXPECTED_COMPONENT_COUNT:
        raise FixtureBlocked(
            f"expected {EXPECTED_COMPONENT_COUNT} frozen mixture components, found "
            f"{len(components) if isinstance(components, list) else type(components)}")
    for case in cases:
        missing = [field for field in CASE_FIELDS if field not in case]
        if missing:
            raise FixtureBlocked(f"case {case.get('case_id')}: missing fields {missing}")
        if case["case_id"].startswith("h109-"):
            raise FixtureBlocked("consumed h109 material must never enter the fixture")
        verify_case_hashes(case)
    return {
        "corpus_path_name": corpus_path.name,
        "corpus_file_sha256": hashlib.sha256(raw).hexdigest(),
        "cases": cases,
        "components": components,
        "mixture_contract_id": document.get("mixture_population", {}).get("contract_id"),
    }


def _component_identity(component: Mapping[str, Any]) -> str:
    return canonical_json_bytes(
        [component["content_class"], [int(component["length_regime"][0]),
                                      int(component["length_regime"][1])]]
    ).decode()


def build_fixture_document(corpus_path: Path, *, seed_line: str = SEED_LINE) -> dict[str, Any]:
    """Derive the frozen 24-case fixture from the accepted public corpus."""
    corpus = _load_corpus(corpus_path)
    by_component: dict[str, list[Mapping[str, Any]]] = {}
    for case in corpus["cases"]:
        by_component.setdefault(_component_key(case), []).append(case)

    expected = {_component_identity(component) for component in corpus["components"]}
    if len(expected) != EXPECTED_COMPONENT_COUNT:
        raise FixtureBlocked("frozen components are not distinct")
    empty = sorted(expected - set(by_component))
    if empty:
        raise FixtureBlocked(
            "FIXTURE_CONSTRUCTION_BLOCKED: no public c109 case for components " + json.dumps(empty))

    selected = []
    for identity in sorted(expected):
        ranked = sorted(
            by_component[identity],
            key=lambda case: (selection_digest(case["case_id"], seed_line=seed_line),
                              case["case_id"]),
        )
        case = ranked[0]
        selected.append({
            "component": identity,
            "selection_sha256": selection_digest(case["case_id"], seed_line=seed_line),
            "case": {field: case[field] for field in CASE_FIELDS},
        })

    document = {
        "schema": FIXTURE_SCHEMA,
        "purpose": "integration regression set only; no statistical qualification claim",
        "selection_rule": {
            "seed_line": seed_line,
            "rule": "per component, ascending sha256(seed_line + case_id), tie by ascending case_id",
        },
        "source_corpus": {
            "file_name": corpus["corpus_path_name"],
            "file_sha256": corpus["corpus_file_sha256"],
            "mixture_contract_id": corpus["mixture_contract_id"],
            "case_count": len(corpus["cases"]),
        },
        "cases": selected,
        "case_count": len(selected),
    }
    document["fixture_digest"] = self_digest(document, identity_field="fixture_digest")
    return document


def validate_fixture_document(document: Mapping[str, Any], *, seed_line: str = SEED_LINE) -> None:
    """Fail closed unless the document reproduces the frozen fixture rule."""
    if document.get("schema") != FIXTURE_SCHEMA:
        raise FixtureBlocked(f"unexpected fixture schema {document.get('schema')!r}")
    if document.get("fixture_digest") != self_digest(
            dict(document), identity_field="fixture_digest"):
        raise FixtureBlocked("fixture_digest self-identity mismatch")
    cases = document["cases"]
    if len(cases) != EXPECTED_COMPONENT_COUNT:
        raise FixtureBlocked(f"expected {EXPECTED_COMPONENT_COUNT} cases, found {len(cases)}")
    components = [case["component"] for case in cases]
    if len(set(components)) != EXPECTED_COMPONENT_COUNT:
        raise FixtureBlocked("components are not one-per-fixture-case")
    for entry in cases:
        case = entry["case"]
        if any(field not in case for field in CASE_FIELDS):
            raise FixtureBlocked(f"case {case.get('case_id')}: missing fields")
        if case["case_id"].startswith("h109-"):
            raise FixtureBlocked("h109 material in fixture")
        if entry["selection_sha256"] != selection_digest(case["case_id"], seed_line=seed_line):
            raise FixtureBlocked(f"case {case['case_id']}: selection digest mismatch")
        verify_case_hashes(case)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    document = build_fixture_document(args.corpus)
    write_canonical_json(args.out, document)
    validate_fixture_document(document)
    print(f"fixture_digest: {document['fixture_digest']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
