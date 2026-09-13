#!/usr/bin/env python3
"""Issue #170 — Arm-C long-remainder corpus FROZEN-terminal reducer.

Pure stdlib, CPU-only, fail-closed. Re-derives the terminal from
retained bytes only (corpus.json + authority-record.json + the frozen
methodology constants), never from authored terminal/boolean fields
inside those records.

Classification logic (exactly the issue #170 rule):

- re-derive the content-class assignment from the frozen rule for
  every case ordinal and require equality with the retained classes;
- re-derive every case's second-chunk remainder from its own retained
  rendered token-id list (len), require remainder == rendered_len - 64,
  bucket membership from the frozen buckets, and the exact frozen
  16-value target-length and remainder sequences;
- require exactly four cases per bucket, all six accepted content
  classes at least twice, unique case ids/prompt bytes/token ids;
- re-derive the canonical corpus digest from the retained cases and
  require equality with the recorded digest;
- re-derive the public historical disjointness digest set from the
  public exclusion sources (c109/p109 corpora, accepted fixture
  renders) and require no case identity collides;
- fail closed on structural drift (schemas, seed, search order/
  ceiling, preflight < 24/24, any h109 reference, any claim of
  GPU/model/candidate execution, heads not verified).

If every check passes and the authority record states no physical
execution, the terminal is
ISSUE117_ARM_C_LONG_REMAINDER_CORPUS_FROZEN; any contradiction leaves
the corpus unfrozen (BLOCKED semantics; the reducer reports the
failure list instead of a terminal).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import issue170_corpus_methodology as M  # noqa: E402
from issue74_methodology import CONTENT_CLASSES  # noqa: E402

#: accepted digest of the 24-case #133 Arm-C regression fixture —
#: consumed from the accepted #133 authority module
from issue129_arm_c_retry_core import FIXTURE_DIGEST_24  # noqa: E402

EVIDENCE = M.EVIDENCE_DIR


def sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def public_exclusion_digests(repo: Path = ROOT) -> set[str]:
    """Re-derive the public historical identity digests directly from
    the public sources (c109 corpus, p109 pool, accepted fixture
    renders). Pure stdlib; h109 namespaces are never enumerated."""
    digests: set[str] = set()
    corpus = json.loads((repo / Path(
        "docs/qualification/gemma4-12b-it-v5/manifests/"
        "calibration-corpus.json")).read_text())
    for case in corpus["cases"]:
        if case["case_id"].startswith("c109-"):
            digests.add(case["prompt_sha256"])
            digests.add(case["token_ids_sha256"])
    stress = json.loads((repo / Path(
        "docs/qualification/gemma4-12b-it-v5/manifests/"
        "stress-pool.json")).read_text())
    for case in stress["cases"]:
        if case["case_id"].startswith("p109-"):
            digests.add(case["prompt_sha256"])
            digests.add(case["token_ids_sha256"])
    fixture = json.loads((repo / Path(
        "docs/implementation/r6-successor-dense-full-integration-117/"
        "evidence/arm-c-retry/prompt-fixture.json")).read_text())
    for row in fixture["cases"]:
        digests.add(sha_bytes(
            M.canonical_json_bytes(row["raw_fixture_token_ids"])))
        digests.add(sha_bytes(
            M.canonical_json_bytes(row["rendered_prompt_token_ids"])))
    return digests


def reduce_terminal(evidence_dir: Path = EVIDENCE,
                    repo: Path = ROOT) -> dict:
    corpus = json.loads((evidence_dir / "corpus.json").read_text())
    authority = json.loads(
        (evidence_dir / "authority-record.json").read_text())
    failures: list[str] = []

    def require(condition: bool, message: str) -> bool:
        if not condition:
            failures.append(message)
        return condition

    require(corpus.get("schema") == M.CORPUS_SCHEMA, "corpus schema drift")
    require(authority.get("schema") == M.AUTHORITY_SCHEMA,
            "authority schema drift")
    require(corpus.get("seed") == M.SEED, "corpus seed drift")
    require(corpus.get("case_prefix") == M.CASE_PREFIX,
            "case prefix drift")
    require(tuple(corpus.get("target_rendered_lengths", ()))
            == M.TARGET_RENDERED_LENGTHS,
            "target rendered lengths are not the frozen 16-value "
            "sequence")
    require(tuple(corpus.get("target_remainders", ()))
            == M.TARGET_REMAINDERS,
            "target remainders are not the frozen 16-value sequence")
    require(corpus.get("row_boundary") == M.ROW_BOUNDARY,
            "row boundary drift (64-row contract changed)")
    search = corpus.get("search", {})
    require(tuple(search.get("wrapper_delta_order", ()))
            == M.WRAPPER_DELTA_ORDER, "search order drift")
    require(search.get("search_ceiling") == M.SEARCH_CEILING,
            "search ceiling drift")
    software = corpus.get("tokenizer", {}).get("identity_verified", {})
    software_file = json.loads((ROOT / Path(
        "docs/implementation/r6-successor-dense-full-integration-117/"
        "evidence/arm-c-retry/frozen-tokenizer/"
        "software-identity.json")).read_text())
    expected_versions = {
        "transformers": software_file["packages"]["transformers"],
        "tokenizers": software_file["packages"]["tokenizers"],
    }
    expected_python = software_file["python"]
    require(software.get("transformers")
            == expected_versions["transformers"],
            "tokenizer software identity drift (transformers)")
    require(software.get("tokenizers")
            == expected_versions["tokenizers"],
            "tokenizer software identity drift (tokenizers)")
    require(str(software.get("python", "")).rsplit(".", 1)[0]
            == expected_python,
            "tokenizer software identity drift (python)")

    preflight = corpus.get("preflight_24_render_reproduction", {})
    require(preflight.get("renders_reproduced") == 24,
            "24/24 accepted render preflight not satisfied")
    require(preflight.get("accepted_fixture_digest")
            == FIXTURE_DIGEST_24, "accepted fixture digest drift")

    heads = authority.get("starting_heads", {})
    require(heads.get("verified") is True,
            "starting heads not verified")
    require(all(heads.get("ancestor_proofs", {}).values()),
            "starting-head ancestor proofs not all true (includes "
            "FreeToken research head unchanged)")
    require(authority.get("physical_execution", {}
                          ).get("performed") is False,
            "authority record claims physical execution")
    require(authority.get("accepted_authority_chain", [{}])[-1].get(
        "terminal") == M.ACCEPTED_BLOCKER_TERMINAL,
        "accepted #168 blocker terminal not consumed")

    cases = corpus.get("cases", [])
    require(len(cases) == M.CASE_COUNT,
            f"corpus does not contain exactly {M.CASE_COUNT} cases")
    if failures:
        return {"verdict": "CORPUS_REDUCTION_FAILED", "failures": failures}

    # uniqueness
    case_ids = [c["case_id"] for c in cases]
    require(len(set(case_ids)) == M.CASE_COUNT, "duplicate case ids")
    prompt_shas = [c["prompt_sha256"] for c in cases]
    require(len(set(prompt_shas)) == M.CASE_COUNT,
            "duplicate prompt bytes")
    rendered_shas = [c["rendered_ids_sha256"] for c in cases]
    require(len(set(rendered_shas)) == M.CASE_COUNT,
            "duplicate rendered token identities")

    # per-case re-derivation from retained bytes
    for case in cases:
        ordinal = case["target_ordinal"]
        cid = case["case_id"]
        require(cid == f"{M.CASE_PREFIX}{ordinal + 1:02d}",
                f"{cid}: case id does not follow the frozen namespace")
        require(0 <= ordinal < M.CASE_COUNT, f"{cid}: ordinal out of range")
        rendered = list(case["rendered_prompt_token_ids"])
        require(len(rendered) == case["rendered_length"],
                f"{cid}: rendered_length does not equal its id list len")
        require(len(rendered) == M.TARGET_RENDERED_LENGTHS[ordinal],
                f"{cid}: rendered length is not its frozen target")
        require(case["target_rendered_length"]
                == M.TARGET_RENDERED_LENGTHS[ordinal],
                f"{cid}: target length drift")
        remainder = len(rendered) - M.ROW_BOUNDARY
        require(remainder == case["second_chunk_remainder"],
                f"{cid}: remainder does not equal rendered_len - 64")
        require(remainder == M.TARGET_REMAINDERS[ordinal],
                f"{cid}: remainder is not its frozen target")
        require(case["bucket"] == M.bucket_of(remainder),
                f"{cid}: bucket membership drift")
        require(M.ROW_BOUNDARY < len(rendered) <= 2 * M.ROW_BOUNDARY,
                f"{cid}: case does not require exactly two prefill "
                "chunks under the 64-row contract")
        require(sha_bytes(case["prompt_text"].encode("utf-8"))
                == case["prompt_sha256"], f"{cid}: prompt digest drift")
        require(sha_bytes(M.canonical_json_bytes(rendered))
                == case["rendered_ids_sha256"],
                f"{cid}: rendered-ids digest drift")
        require(len(case["raw_token_ids"]) == case["raw_token_count"],
                f"{cid}: raw token count drift")
        require(sha_bytes(M.canonical_json_bytes(case["raw_token_ids"]))
                == case["raw_token_ids_sha256"],
                f"{cid}: raw-token-ids digest drift")
        require(case["content_class"]
                == M.assigned_content_class(ordinal, CONTENT_CLASSES),
                f"{cid}: content class does not follow the frozen "
                "assignment rule")
        require(0 <= case["accepted_nonce"] < M.SEARCH_CEILING,
                f"{cid}: accepted nonce outside the frozen ceiling")

    # bucket counts
    counts = {name: 0 for name, _, _ in M.BUCKETS}
    for case in cases:
        name = M.bucket_of(case["second_chunk_remainder"])
        if name in counts:
            counts[name] += 1
    for name, _, _ in M.BUCKETS:
        require(counts[name] == M.REQUIRED_PER_BUCKET,
                f"bucket {name} does not contain exactly "
                f"{M.REQUIRED_PER_BUCKET} cases (has {counts[name]})")

    # content-class coverage
    class_counts = {name: 0 for name in CONTENT_CLASSES}
    for case in cases:
        if case["content_class"] in class_counts:
            class_counts[case["content_class"]] += 1
    for name in CONTENT_CLASSES:
        require(class_counts[name] >= 2,
                f"content class {name} appears fewer than twice "
                f"({class_counts[name]})")

    # canonical digest re-derivation
    require("sha256:" + M.canonical_sha(cases)
            == corpus["canonical_corpus_digest"],
            "canonical corpus digest drift")

    # public historical disjointness, re-derived from public sources
    exclusions = public_exclusion_digests(repo)
    for case in cases:
        for kind, value in (
                ("prompt", case["prompt_sha256"]),
                ("raw tokens", case["raw_token_ids_sha256"]),
                ("rendered tokens", case["rendered_ids_sha256"])):
            require(value not in exclusions,
                    f"{case['case_id']}: {kind} identity collides with "
                    "a public historical identity")

    # forbidden namespace: no h109 identity reference anywhere in the
    # retained bytes. A reference is a literal `h109-` followed by an
    # id character (case ids, paths, seeds); the retained non-claims
    # mention the forbidden namespace only as `h109-*` prose.
    import re
    retained = ((evidence_dir / "corpus.json").read_text()
                + (evidence_dir / "authority-record.json").read_text())
    h_refs = sorted(set(re.findall(r"h109-[0-9A-Za-z_]", retained)))
    require(not h_refs,
            f"h109 reference present in retained bytes: {h_refs[:3]}")

    if failures:
        return {"verdict": "CORPUS_REDUCTION_FAILED", "failures": failures}

    return {
        "verdict": M.FROZEN_TERMINAL,
        "corpus_id": M.CORPUS_ID,
        "canonical_corpus_digest": corpus["canonical_corpus_digest"],
        "case_count": M.CASE_COUNT,
        "bucket_counts": counts,
        "content_class_counts": class_counts,
        "classification_basis": (
            "16 unique public cases; exact frozen target lengths and "
            "remainders re-derived from retained rendered-id lists; "
            "exactly four cases per original #168 bucket; all six "
            "accepted content classes at least twice; canonical "
            "digest and public disjointness re-derived; preflight "
            "24/24; no physical execution"),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, default=EVIDENCE)
    parser.add_argument("--repo", type=Path, default=ROOT)
    parser.add_argument("--write", action="store_true",
                        help="write terminal-reduction.json")
    args = parser.parse_args(argv)
    result = reduce_terminal(args.evidence, args.repo)
    print(json.dumps(result, indent=1, sort_keys=True))
    if result["verdict"] == "CORPUS_REDUCTION_FAILED":
        return 1
    if args.write:
        out = args.evidence / "terminal-reduction.json"
        out.write_text(json.dumps(result, indent=1, sort_keys=True) + "\n")
        print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
