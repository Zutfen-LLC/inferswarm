#!/usr/bin/env python3
"""Issue #170 — Arm-C long-remainder public corpus PRODUCER.

Deterministically generates the prospective 16-case public Arm-C
long-remainder generalization corpus required by issue #170, CPU-only,
with the accepted frozen tokenizer assets and the accepted #129/#133
chat-render semantics. This is the physical-census-style PRODUCER, not
a CI test: it imports ``transformers``. Its retained output is
validated by pure-stdlib modules (scripts/issue170_terminal_reduction.py
and tests/test_issue170_long_remainder_corpus.py), neither of which
imports transformers.

Fail-closed order of operations (nothing is generated before every
authority check passes):

1. assert offline HF env and the frozen tokenizer software identity
   (python major.minor, transformers, tokenizers, Jinja2, MarkupSafe)
   against the accepted software-identity.json, exactly as the accepted
   #168 census did;
2. mechanically reproduce all 24 accepted #133 regression-fixture
   renders byte-exact (preflight; any mismatch -> stop BLOCKED);
3. verify the #168 accepted blocker record is present and untouched
   (its terminal is consumed, never reinterpreted);
4. build the public historical exclusion inventory (prompt-text
   sha256 + raw-token-ids sha256 of all 1416 c109 calibration cases,
   the p109 stress pool, the 24-case accepted fixture, and the #157
   anchor/control identities where separately represented) — public
   namespaces only, h109 FORBIDDEN;
5. for each of the 16 frozen target rendered lengths (ascending
   ordinal), under the frozen content-class assignment and the frozen
   raw-target/nonce search order with the frozen finite ceiling,
   generate public prompt material with the #74-lineage lexeme
   machinery (imported, never copied or mutated), render it through
   the frozen chat template, and accept the FIRST candidate whose
   measured rendered length equals the target exactly and which is
   disjoint from every public historical identity;
6. retain the complete frozen methodology + corpus record.

No GPU, no model execution, no FreeToken candidate runtime, no
candidate-output inspection, no h109-* access, no Arm-C PASS/FAIL
derivation.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata as md
import json
import os
import platform
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import issue170_corpus_methodology as M  # noqa: E402

#: accepted digest of the 24-case #133 Arm-C regression fixture —
#: consumed from the accepted #133 authority module
#: (import-don't-restate; cross-pinned by the record tests)
from issue129_arm_c_retry_core import FIXTURE_DIGEST_24  # noqa: E402

#: #74-lineage public prompt-construction machinery — imported, never
#: copied or mutated (CONTENT_CLASSES ordering and LEXEMES are the
#: accepted public constants)
from generate_issue74_corpora import LEXEMES  # noqa: E402
from issue74_methodology import CONTENT_CLASSES  # noqa: E402

TOKENIZER_DIR = Path(
    "docs/implementation/r6-successor-dense-full-integration-117/"
    "evidence/arm-c-retry/frozen-tokenizer")
INTEGRATION_FIXTURE = Path(
    "docs/implementation/r6-successor-dense-full-integration-117/"
    "evidence/integration-fixture.json")
BLOCKER_DIR = Path(
    "docs/implementation/r6-successor-arm-c-requal-blocked-168/evidence")
CORPUS_OUT = M.EVIDENCE_DIR / "corpus.json"
AUTHORITY_OUT = M.EVIDENCE_DIR / "authority-record.json"


def sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def render(tokenizer, text: str) -> list[int]:
    """Accepted #129/#133 render semantics (frozen)."""
    prompt = tokenizer.apply_chat_template(
        [{"role": "user", "content": text}], tokenize=False,
        add_generation_prompt=True)
    return list(tokenizer.encode(prompt, add_special_tokens=False))


def verify_software_identity(repo: Path) -> dict:
    software = json.loads(
        (repo / TOKENIZER_DIR / "software-identity.json").read_text())
    expected = software["packages"]
    import transformers
    import tokenizers  # noqa: F401
    actual = {
        "transformers": transformers.__version__,
        "tokenizers": tokenizers.__version__,
    }
    for package, version in expected.items():
        if package in ("Jinja2", "MarkupSafe"):
            dist = "jinja2" if package == "Jinja2" else "markupsafe"
            got = md.version(dist)
            if got != version:
                raise SystemExit(
                    f"software identity drift: {package} {got} != "
                    f"frozen {version}")
        elif package in actual:
            if actual[package] != version:
                raise SystemExit(
                    f"software identity drift: {package} "
                    f"{actual[package]} != frozen {version}")
    py = platform.python_version()
    if py.rsplit(".", 1)[0] != software["python"]:
        raise SystemExit(
            f"software identity drift: python {py} != frozen "
            f"{software['python']}")
    return {
        "software_identity_file": str(TOKENIZER_DIR /
                                      "software-identity.json"),
        "software_identity_sha256": "sha256:" + sha_bytes(
            (repo / TOKENIZER_DIR / "software-identity.json")
            .read_bytes()),
        "identity_verified": {
            "python": py,
            "transformers": actual["transformers"],
            "tokenizers": actual["tokenizers"],
        },
        "render_semantics": (
            "apply_chat_template([{role:user}], tokenize=False, "
            "add_generation_prompt=True) then "
            "encode(add_special_tokens=False)"),
    }


def preflight_24_renders(repo: Path, tokenizer) -> dict:
    """Reproduce all 24 accepted #133 fixture renders byte-exact.

    Authority binding (consumed, never restated): the accepted
    24-case fixture identity is FIXTURE_DIGEST_24, imported from the
    accepted #133 authority module; it is the ``fixture_digest`` of the
    accepted integration-fixture.json (the selection authority for the
    24 case ids). The retained rendered-id fixture (prompt-fixture.json,
    its own derived digest) must cover exactly the same 24 case ids and
    must reproduce byte-exact under the frozen tokenizer.
    """
    integration = json.loads(
        (repo / INTEGRATION_FIXTURE).read_text())
    if integration.get("fixture_digest") != FIXTURE_DIGEST_24:
        raise SystemExit("accepted integration fixture digest drift; "
                         "preflight fails closed")
    fixture = json.loads((repo / Path(
        "docs/implementation/r6-successor-dense-full-integration-117/"
        "evidence/arm-c-retry/prompt-fixture.json")).read_text())
    integration_ids = {row["case"]["case_id"]
                       for row in integration["cases"]}
    fixture_ids = {row["case_id"] for row in fixture["cases"]}
    if len(integration_ids) != 24 or fixture_ids != integration_ids:
        raise SystemExit("retained fixture case ids do not cover the "
                         "accepted 24-case integration fixture; "
                         "preflight fails closed")
    texts = {row["case"]["case_id"]: row["case"]["prompt_text"]
             for row in integration["cases"]}
    reproduced = 0
    for row in fixture["cases"]:
        accepted_ids = list(row["rendered_prompt_token_ids"])
        rendered = render(tokenizer, texts[row["case_id"]])
        if rendered != accepted_ids:
            raise SystemExit(
                f"{row['case_id']}: frozen tokenizer does not reproduce "
                "the accepted rendered fixture; corpus generation stops "
                "BLOCKED")
        reproduced += 1
    return {
        "accepted_fixture_digest": FIXTURE_DIGEST_24,
        "case_count": 24,
        "renders_reproduced": reproduced,
    }


def build_exclusion_inventory(repo: Path) -> tuple[dict, set[str]]:
    """Public historical identities only (prompt sha256 + raw-token
    sha256 + rendered-token sha256 where separately represented)."""
    inventory: dict[str, dict] = {}

    def add(kind: str, case_id: str, prompt_sha: str | None,
            token_sha: str | None, rendered_sha: str | None = None) -> None:
        entry = inventory.setdefault(
            case_id, {"kinds": [], "prompt_sha256": None,
                      "token_ids_sha256": None,
                      "rendered_ids_sha256": None})
        if kind not in entry["kinds"]:
            entry["kinds"].append(kind)
        if prompt_sha:
            entry["prompt_sha256"] = prompt_sha
        if token_sha:
            entry["token_ids_sha256"] = token_sha
        if rendered_sha:
            entry["rendered_ids_sha256"] = rendered_sha

    calibration = json.loads((repo / Path(
        "docs/qualification/gemma4-12b-it-v5/manifests/"
        "calibration-corpus.json")).read_text())
    calibration_sha = sha_bytes((repo / Path(
        "docs/qualification/gemma4-12b-it-v5/manifests/"
        "calibration-corpus.json")).read_bytes())
    for case in calibration["cases"]:
        if not case["case_id"].startswith("c109-"):
            continue
        add("c109-calibration", case["case_id"],
            case["prompt_sha256"], case["token_ids_sha256"])

    stress = json.loads((repo / Path(
        "docs/qualification/gemma4-12b-it-v5/manifests/"
        "stress-pool.json")).read_text())
    stress_sha = sha_bytes((repo / Path(
        "docs/qualification/gemma4-12b-it-v5/manifests/"
        "stress-pool.json")).read_bytes())
    for case in stress["cases"]:
        if not case["case_id"].startswith("p109-"):
            continue
        add("p109-stress-pool", case["case_id"],
            case["prompt_sha256"], case["token_ids_sha256"])

    fixture = json.loads((repo / Path(
        "docs/implementation/r6-successor-dense-full-integration-117/"
        "evidence/arm-c-retry/prompt-fixture.json")).read_text())
    integration = json.loads(
        (repo / INTEGRATION_FIXTURE).read_text())
    texts = {row["case"]["case_id"]: row["case"]["prompt_text"]
             for row in integration["cases"]}
    fixture_sha = sha_bytes((repo / Path(
        "docs/implementation/r6-successor-dense-full-integration-117/"
        "evidence/arm-c-retry/prompt-fixture.json")).read_bytes())
    for row in fixture["cases"]:
        rendered_sha = sha_bytes(
            M.canonical_json_bytes(row["rendered_prompt_token_ids"]))
        raw_sha = sha_bytes(
            M.canonical_json_bytes(row["raw_fixture_token_ids"]))
        add("accepted-133-fixture", row["case_id"],
            sha_bytes(texts[row["case_id"]].encode("utf-8")),
            raw_sha, rendered_sha)

    authority157 = json.loads((repo / Path(
        "docs/implementation/r6-successor-dense-full-integration-117/"
        "evidence/arm-c-chunk2-diagnosis-157/"
        "physical-diagnostic-authority.json")).read_text())
    authority157_sha = sha_bytes((repo / Path(
        "docs/implementation/r6-successor-dense-full-integration-117/"
        "evidence/arm-c-chunk2-diagnosis-157/"
        "physical-diagnostic-authority.json")).read_bytes())
    anchor_ids = []
    frozen_corpus = authority157.get("frozen_corpus", {})
    for key in ("anchor_a", "anchor_b", "stable_control"):
        value = frozen_corpus.get(key)
        if isinstance(value, dict) and isinstance(
                value.get("case_id"), str):
            anchor_ids.append(value["case_id"])
    record = {
        "namespaces": {
            "c109_calibration": {
                "case_count": sum(
                    1 for e in inventory.values()
                    if "c109-calibration" in e["kinds"]),
                "file_sha256": "sha256:" + calibration_sha},
            "p109_stress_pool": {
                "case_count": sum(
                    1 for e in inventory.values()
                    if "p109-stress-pool" in e["kinds"]),
                "file_sha256": "sha256:" + stress_sha},
            "accepted_133_fixture": {
                "case_count": 24,
                "file_sha256": "sha256:" + fixture_sha,
                "accepted_fixture_digest": FIXTURE_DIGEST_24},
            "accepted_157_anchor_control": {
                "case_ids": sorted(set(anchor_ids)),
                "file_sha256": "sha256:" + authority157_sha,
                "note": ("identities consumed from the public c109 "
                         "corpus rows where separately represented; "
                         "no new material derived from #157")},
        },
        "total_distinct_public_identities": len(inventory),
        "checked_identity_kinds": [
            "prompt_text_sha256", "raw_token_ids_sha256",
            "rendered_token_ids_sha256"],
        "forbidden_namespace": M.FORBIDDEN_NAMESPACE,
    }
    digest_set = set()
    for entry in inventory.values():
        for value in (entry["prompt_sha256"], entry["token_ids_sha256"],
                      entry["rendered_ids_sha256"]):
            if value:
                digest_set.add(value)
    record["inventory_digest"] = "sha256:" + M.canonical_sha(
        {cid: inventory[cid] for cid in sorted(inventory)})
    return record, digest_set


def candidate_text(seed: str, namespace: str, content_class: str,
                   ordinal: int, raw_target: int, nonce: int) -> str:
    """Deterministic public prompt material, #74-lineage machinery
    (sha256-seeded RNG over the accepted public lexemes). The RNG
    derivation is issue-local and additive; the historical generators
    and their constants are untouched."""
    import random
    material = "\0".join((
        seed, namespace, content_class, str(ordinal),
        str(raw_target), str(nonce))).encode()
    rng = random.Random(int.from_bytes(
        hashlib.sha256(material).digest(), "big"))
    lexemes = LEXEMES[content_class]
    count = raw_target * 4 + 16
    words = [lexemes[rng.randrange(len(lexemes))] for _ in range(count)]
    return " ".join(words)


def generate_corpus(tokenizer, exclusions: set[str]) -> tuple[list, dict]:
    """Frozen search: for each target ordinal (ascending), under the
    frozen content-class assignment, enumerate raw targets in the
    frozen wrapper-delta order with a monotonically increasing nonce;
    accept the first exact-length disjoint realization."""
    cases = []
    stats = []
    collision_retries = 0
    for ordinal, target in enumerate(M.TARGET_RENDERED_LENGTHS):
        content_class = M.assigned_content_class(ordinal, CONTENT_CLASSES)
        case_id = f"{M.CASE_PREFIX}{ordinal + 1:02d}"
        accepted = None
        attempts_used = 0
        # nonce strictly increases across this target's whole search
        nonce = 0
        while nonce < M.SEARCH_CEILING:
            for delta in M.WRAPPER_DELTA_ORDER:
                raw_target = target - delta
                if raw_target < 1:
                    continue
                attempts_used += 1
                raw_text = candidate_text(
                    M.SEED, M.NAMESPACE, content_class, ordinal,
                    raw_target, nonce)
                raw_ids = tokenizer.encode(
                    raw_text, add_special_tokens=False)
                if len(raw_ids) < raw_target:
                    continue
                ids = raw_ids[:raw_target]
                text = tokenizer.decode(ids, skip_special_tokens=False)
                round_trip = tokenizer.encode(
                    text, add_special_tokens=False)
                if round_trip != ids:
                    continue
                rendered = render(tokenizer, text)
                if len(rendered) != target:
                    continue
                prompt_sha = sha_bytes(text.encode("utf-8"))
                raw_token_sha = sha_bytes(M.canonical_json_bytes(ids))
                rendered_sha = sha_bytes(
                    M.canonical_json_bytes(rendered))
                if (prompt_sha in exclusions
                        or raw_token_sha in exclusions
                        or rendered_sha in exclusions):
                    collision_retries += 1
                    break  # deterministic retry: next nonce
                accepted = {
                    "case_id": case_id,
                    "target_ordinal": ordinal,
                    "content_class": content_class,
                    "target_rendered_length": target,
                    "prompt_text": text,
                    "raw_token_ids": list(ids),
                    "raw_token_count": len(ids),
                    "rendered_prompt_token_ids": rendered,
                    "rendered_length": len(rendered),
                    "second_chunk_remainder":
                        len(rendered) - M.ROW_BOUNDARY,
                    "bucket": M.bucket_of(
                        len(rendered) - M.ROW_BOUNDARY),
                    "prompt_sha256": prompt_sha,
                    "raw_token_ids_sha256": raw_token_sha,
                    "rendered_ids_sha256": rendered_sha,
                    "accepted_nonce": nonce,
                    "accepted_wrapper_delta": len(rendered) - len(ids),
                    "raw_target_tokens": raw_target,
                }
                break
            if accepted:
                break
            nonce += 1
        if accepted is None:
            return cases, {
                "blocked": True,
                "blocked_target_ordinal": ordinal,
                "blocked_target_length": target,
                "search_ceiling": M.SEARCH_CEILING,
            }
        stats.append({
            "case_id": case_id,
            "target_rendered_length": target,
            "accepted_nonce": accepted["accepted_nonce"],
            "raw_target_tokens": accepted["raw_target_tokens"],
            "attempts_searched": attempts_used,
            "wrapper_delta": accepted["accepted_wrapper_delta"],
        })
        cases.append(accepted)
        print(f"  {case_id}: class={content_class} "
              f"target={target} raw={accepted['raw_token_count']} "
              f"nonce={accepted['accepted_nonce']} "
              f"attempts={attempts_used}")
    return cases, {"blocked": False, "collision_retries": collision_retries,
                   "search_ceiling": M.SEARCH_CEILING}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=ROOT)
    args = parser.parse_args(argv)
    repo = args.repo.resolve()

    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

    software_record = verify_software_identity(repo)

    from transformers import AutoTokenizer
    tokenizer = AutoTokenizer.from_pretrained(
        str(repo / TOKENIZER_DIR / "assets"))

    preflight = preflight_24_renders(repo, tokenizer)
    print(f"preflight: {preflight['renders_reproduced']}/24 accepted "
          "renders reproduced byte-exact")

    # consume (never reinterpret) the accepted #168 blocker terminal
    blocker = json.loads(
        (repo / BLOCKER_DIR / "terminal-reduction.json").read_text())
    if blocker.get("verdict") != M.ACCEPTED_BLOCKER_TERMINAL:
        raise SystemExit("accepted #168 blocker terminal missing or "
                         "altered; authority contradiction -> BLOCKED")

    exclusion_record, exclusions = build_exclusion_inventory(repo)
    print(f"exclusion inventory: "
          f"{exclusion_record['total_distinct_public_identities']} "
          "distinct public historical identities")

    cases, gen_stats = generate_corpus(tokenizer, exclusions)

    generator_source = Path(__file__).read_bytes()
    generator_sha = sha_bytes(generator_source)
    methodology_sha = sha_bytes(
        (SCRIPTS / "issue170_corpus_methodology.py").read_bytes())

    if gen_stats.get("blocked"):
        record = {
            "schema": M.CORPUS_SCHEMA,
            "corpus_id": M.CORPUS_ID,
            "terminal": M.BLOCKED_TERMINAL,
            "blocked_reason": (
                "a frozen target rendered length could not be realized "
                "within the frozen search ceiling"),
            "generation": gen_stats,
            "non_claims": [
                "no model execution, no GPU access, no candidate "
                "output inspection occurred",
                "no h109-* material was opened, generated, copied, "
                "or used",
            ],
        }
        M.EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
        (M.EVIDENCE_DIR / "corpus.json").write_text(
            json.dumps(record, sort_keys=True, indent=1) + "\n")
        print("BLOCKED: " + json.dumps(gen_stats))
        return 0

    content_class_counts = {name: 0 for name in CONTENT_CLASSES}
    for case in cases:
        content_class_counts[case["content_class"]] += 1

    corpus_digest = "sha256:" + M.canonical_sha(cases)
    record = {
        "schema": M.CORPUS_SCHEMA,
        "corpus_id": M.CORPUS_ID,
        "issue": ("https://github.com/Zutfen-LLC/inferswarm/"
                  "issues/170"),
        "seed": M.SEED,
        "case_prefix": M.CASE_PREFIX,
        "namespace": M.NAMESPACE,
        "generator": "scripts/issue170_corpus_producer.py",
        "generator_sha256": generator_sha,
        "methodology_module": "scripts/issue170_corpus_methodology.py",
        "methodology_sha256": methodology_sha,
        "tokenizer": software_record,
        "preflight_24_render_reproduction": preflight,
        "accepted_blocker_consumed": {
            "issue": M.ACCEPTED_BLOCKER_ISSUE,
            "terminal": M.ACCEPTED_BLOCKER_TERMINAL,
            "record": str(BLOCKER_DIR / "terminal-reduction.json"),
        },
        "row_boundary": M.ROW_BOUNDARY,
        "target_rendered_lengths": list(M.TARGET_RENDERED_LENGTHS),
        "target_remainders": list(M.TARGET_REMAINDERS),
        "buckets": {
            "definitions": [list(b) for b in M.BUCKETS],
            "required_per_bucket": M.REQUIRED_PER_BUCKET,
        },
        "content_class_assignment": {
            "rule": ("case ordinal i (0-based, ascending target length) "
                     "-> CONTENT_CLASSES[(2 + 5*i) % 6], consumed from "
                     "scripts/issue74_methodology.py CONTENT_CLASSES"),
            "stride": M.CLASS_ASSIGNMENT_STRIDE,
            "offset": M.CLASS_ASSIGNMENT_OFFSET,
            "realized_counts": content_class_counts,
        },
        "search": {
            "raw_target_order": ("per nonce n (monotonically increasing "
                                 "from 0), raw token target "
                                 "L - delta for delta in (13, 12) — the "
                                 "frozen wrapper-delta hypothesis order; "
                                 "measured rendered length must equal the "
                                 "target exactly"),
            "wrapper_delta_order": list(M.WRAPPER_DELTA_ORDER),
            "search_ceiling": M.SEARCH_CEILING,
            "generation": gen_stats,
        },
        "exclusions": exclusion_record,
        "case_count": len(cases),
        "cases": cases,
        "canonical_corpus_digest": corpus_digest,
        "non_claims": [
            "no model execution, no GPU access, no candidate output "
            "inspection occurred during generation",
            "no h109-* material was opened, generated, copied, or used",
            "this corpus makes no statistical-qualification claim and "
            "does not answer whether #166 fixes Arm C",
        ],
    }
    M.EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    (M.EVIDENCE_DIR / "corpus.json").write_text(
        json.dumps(record, sort_keys=True, indent=1) + "\n")
    print(f"wrote {M.EVIDENCE_DIR / 'corpus.json'}: {len(cases)} cases, "
          f"digest {corpus_digest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
