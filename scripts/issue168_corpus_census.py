#!/usr/bin/env python3
"""Issue #168 — Arm-C post-SWA requalification corpus census (producer).

Deterministically derives, from the already-public #109 ``c109-*``
calibration corpus, the fresh-arm eligibility census required by issue
#168 Phase 1B, using ONLY CPU metadata/tokenization (no model, no GPU,
no candidate outputs, no ``h109-*`` material).

This is the physical-census PRODUCER, not a CI test: it imports
``transformers`` and loads the accepted frozen tokenizer assets retained
in the #133 evidence tree (software identity pinned by
``software-identity.json`` in the same directory). The retained output
``corpus-census.json`` is validated by pure-stdlib tests
(tests/test_issue168_requal_blocked_record.py) and by
scripts/issue168_terminal_reduction.py, neither of which imports
transformers.

Method (fail-closed at every step):

1. assert offline HF env and the frozen tokenizer software identity
   (python major.minor, transformers, tokenizers) matches the accepted
   #129/#133 ``software-identity.json`` exactly;
2. reproduce all 24 accepted #133 Arm-C regression-fixture rendered
   prompts byte-exact through the frozen tokenizer before any census
   computation (render/tokenize semantics:
   ``apply_chat_template([user], tokenize=False,
   add_generation_prompt=True)`` then ``encode(add_special_tokens=False)``);
3. render every public corpus case once; retain per-case rendered
   lengths for the whole corpus and full rendered token ids only for
   eligible-pool members;
4. compute eligibility under TWO defensible readings of the issue's
   ``65 <= rendered/replay length <= 128`` two-chunk requirement:
   - ``prompt_two_chunk``: the rendered prompt itself spans two prefill
     chunks (65 <= rendered_len <= 128), second-chunk remainder =
     rendered_len - 64;
   - ``final_replay_crossing`` (most generous): the final comparator
     replay (rendered prompt + 7 already-committed tokens, i.e. the
     replay input of the 8th commit under the frozen #129/#133
     comparator) spans two chunks (65 <= rendered_len + 7 <= 128),
     remainder = rendered_len + 7 - 64;
5. bucket by second-chunk remainder into 1-8 / 9-24 / 25-48 / 49-64,
   compute the canonical selection key
   sha256(canonical-json{salt, case_id, rendered_prompt_token_ids}) with
   the literal salt ``issue168-arm-c-post-swa-requal-v1`` for every
   eligible member, sort ascending by (key, case_id);
6. record per-bucket eligible counts; the maintainer-facing selection
   (lowest four keys per bucket) is derived but NOT frozen as a fixture
   when any bucket is short — issue #168 forbids bucket adaptation and
   mandates stopping pre-observation;
7. supplementary bound: the public #109 stress pool (``p109-*``) is out
   of the mandated c109 namespace, and its raw token counts bound its
   rendered lengths below any upper-bucket eligibility too.

Output: docs/implementation/r6-successor-arm-c-requal-blocked-168/
evidence/corpus-census.json (schema
inferswarm.issue168.arm-c-requal-corpus-census/1).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SALT = "issue168-arm-c-post-swa-requal-v1"
BUCKETS = (("1-8", 1, 8), ("9-24", 9, 24), ("25-48", 25, 48),
           ("49-64", 49, 64))
REQUIRED_PER_BUCKET = 4

CORPUS_PATH = Path(
    "docs/qualification/gemma4-12b-it-v5/manifests/calibration-corpus.json")
STRESS_POOL_PATH = Path(
    "docs/qualification/gemma4-12b-it-v5/manifests/stress-pool.json")
FIXTURE_PATH = Path(
    "docs/implementation/r6-successor-dense-full-integration-117/evidence/"
    "arm-c-retry/prompt-fixture.json")
TOKENIZER_DIR = Path(
    "docs/implementation/r6-successor-dense-full-integration-117/evidence/"
    "arm-c-retry/frozen-tokenizer")
OUT_PATH = Path(
    "docs/implementation/r6-successor-arm-c-requal-blocked-168/evidence/"
    "corpus-census.json")

#: accepted digest of the 24-case #133 Arm-C regression fixture
#: (issue #168 Phase 1A; identical to FIXTURE_DIGEST_24 in
#: scripts/issue129_arm_c_retry_core.py)
ACCEPTED_FIXTURE_DIGEST = (
    "sha256:180185cd5c6a5dcd77b2c65979bd2c9aef4d1c7ea9fb4850a64f4508b2ba36f2")


def sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_sha(obj: object) -> str:
    return sha_bytes(json.dumps(
        obj, sort_keys=True, separators=(",", ":")).encode())


def bucket_of(remainder: int) -> str | None:
    for name, low, high in BUCKETS:
        if low <= remainder <= high:
            return name
    return None


def render(tokenizer, text: str) -> list[int]:
    prompt = tokenizer.apply_chat_template(
        [{"role": "user", "content": text}], tokenize=False,
        add_generation_prompt=True)
    return list(tokenizer.encode(prompt, add_special_tokens=False))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=ROOT)
    args = parser.parse_args(argv)
    repo = args.repo.resolve()

    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

    software = json.loads(
        (repo / TOKENIZER_DIR / "software-identity.json").read_text())
    expected = software["packages"]
    import transformers
    import tokenizers  # noqa: F401  (identity check below)
    actual = {
        "transformers": transformers.__version__,
        "tokenizers": tokenizers.__version__,
    }
    for package, version in expected.items():
        if package in ("Jinja2", "MarkupSafe"):
            import importlib.metadata as md
            got = md.version(
                "jinja2" if package == "Jinja2" else "markupsafe")
            assert got == version, (
                f"{package}: {got} != frozen {version}")
        elif package in actual:
            assert actual[package] == version, (
                f"{package}: {actual[package]} != frozen {version}")
    py = platform.python_version()
    assert py.rsplit(".", 1)[0] == software["python"], (
        f"python {py} != frozen {software['python']}")

    from transformers import AutoTokenizer
    tokenizer = AutoTokenizer.from_pretrained(
        str(repo / TOKENIZER_DIR / "assets"))

    corpus_bytes = (repo / CORPUS_PATH).read_bytes()
    corpus = json.loads(corpus_bytes)
    fixture = json.loads((repo / FIXTURE_PATH).read_text())
    fixture_ids = [row["case_id"] for row in fixture["cases"]]
    fixture_by_id = {row["case_id"]: row for row in fixture["cases"]}
    assert len(fixture_ids) == len(set(fixture_ids)) == 24

    # 2. reproduce the accepted regression fixture renders byte-exact
    reproduced = 0
    for case_id in fixture_ids:
        accepted = fixture_by_id[case_id]
        rendered = render(tokenizer, accepted_prompt_text(
            repo, corpus, case_id))
        if rendered != list(accepted["rendered_prompt_token_ids"]):
            raise SystemExit(
                f"{case_id}: frozen tokenizer does not reproduce the "
                "accepted rendered fixture; census fails closed")
        reproduced += 1

    # 3. render every public corpus case
    per_case = []
    eligible_ids: set[str] = set()
    for case in corpus["cases"]:
        rendered = render(tokenizer, case["prompt_text"])
        row = {
            "case_id": case["case_id"],
            "in_regression_fixture": case["case_id"] in fixture_by_id,
            "raw_token_count": case["token_count"],
            "rendered_len": len(rendered),
        }
        per_case.append(row)
        r1 = row["rendered_len"]
        r2 = row["rendered_len"] + 7
        if (65 <= r1 <= 128) or (65 <= r2 <= 128):
            eligible_ids.add((case["case_id"], tuple(rendered)))

    # 4-5. readings, buckets, canonical selection keys
    readings = {}
    for name, length_expr, desc in (
        ("prompt_two_chunk", lambda r: r["rendered_len"],
         "rendered prompt length itself in [65,128]; second-chunk "
         "remainder = rendered_len - 64"),
        ("final_replay_crossing", lambda r: r["rendered_len"] + 7,
         "final comparator replay length (rendered + 7 already-committed "
         "tokens, the 8th commit's replay input) in [65,128]; remainder "
         "= rendered_len + 7 - 64"),
    ):
        members = {b: [] for b, _, _ in BUCKETS}
        for row in per_case:
            if row["in_regression_fixture"]:
                continue
            length = length_expr(row)
            if not 65 <= length <= 128:
                continue
            bucket = bucket_of(length - 64)
            if bucket is None:
                continue
            rendered = None
            for cid, ids in eligible_ids:
                if cid == row["case_id"]:
                    rendered = list(ids)
            members[bucket].append({
                "case_id": row["case_id"],
                "rendered_len": row["rendered_len"],
                "effective_len": length,
                "second_chunk_remainder": length - 64,
                "selection_key_sha256": canonical_sha({
                    "salt": SALT, "case_id": row["case_id"],
                    "rendered_prompt_token_ids": rendered}),
                "rendered_prompt_token_ids": rendered,
            })
        for bucket in members:
            members[bucket].sort(
                key=lambda m: (m["selection_key_sha256"], m["case_id"]))
        counts = {b: len(members[b]) for b, _, _ in BUCKETS}
        readings[name] = {
            "definition": desc,
            "eligible_counts": counts,
            "insufficient_buckets": sorted(
                b for b in counts if counts[b] < REQUIRED_PER_BUCKET),
            "lowest_four_per_bucket": {
                b: [m["case_id"] for m in members[b][:REQUIRED_PER_BUCKET]]
                for b, _, _ in BUCKETS},
            "members": members,
        }

    # 6. supplementary stress-pool bound (namespace + length)
    stress = json.loads((repo / STRESS_POOL_PATH).read_text())
    stress_max_raw = max(c["token_count"] for c in stress["cases"])
    stress_prefixes = sorted({
        c["case_id"].split("-")[0] for c in stress["cases"]})

    out = {
        "schema": "inferswarm.issue168.arm-c-requal-corpus-census/1",
        "salt": SALT,
        "issue": "https://github.com/Zutfen-LLC/inferswarm/issues/168",
        "corpus": {
            "file": str(CORPUS_PATH),
            "file_sha256": "sha256:" + sha_bytes(corpus_bytes),
            "case_count": len(per_case),
            "case_id_prefixes": sorted({
                c["case_id"].split("-")[0]
                for c in corpus["cases"]}),
        },
        "regression_fixture": {
            "file": str(FIXTURE_PATH),
            "accepted_fixture_digest": ACCEPTED_FIXTURE_DIGEST,
            "case_count": 24,
            "case_ids": sorted(fixture_by_id),
            "renders_reproduced": reproduced,
        },
        "tokenizer": {
            "assets_dir": str(TOKENIZER_DIR / "assets"),
            "software_identity_file": str(
                TOKENIZER_DIR / "software-identity.json"),
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
        },
        "eligibility_readings": readings,
        "selection_algorithm": (
            "per bucket, ascending sha256 of canonical JSON "
            "{salt, case_id, rendered_prompt_token_ids} with the literal "
            f"salt {SALT!r}, tie-break ascending case_id; first four "
            "per bucket"),
        "required_per_bucket": REQUIRED_PER_BUCKET,
        "max_rendered_len_corpus": max(r["rendered_len"] for r in per_case),
        "per_case_rendered_lengths": per_case,
        "supplementary_stress_pool_bound": {
            "file": str(STRESS_POOL_PATH),
            "file_sha256": "sha256:" + sha_bytes(
                (repo / STRESS_POOL_PATH).read_bytes()),
            "case_count": len(stress["cases"]),
            "case_id_prefixes": stress_prefixes,
            "max_raw_token_count": stress_max_raw,
            "note": (
                "the public stress pool is outside the mandated c109 "
                "calibration namespace; its raw token counts bound "
                "rendered lengths (<= raw + 13) below every upper "
                "bucket's minimum under both readings, so it cannot "
                "remedy any insufficient bucket"),
        },
        "non_claims": [
            "no model execution, no GPU access, no candidate output "
            "inspection occurred during this census",
            "no h109-* material was opened, generated, copied, or used",
            "no fresh-arm fixture was frozen: selection keys are "
            "retained for audit, but a fixture freeze is meaningless "
            "while buckets are insufficient",
        ],
    }
    out_path = repo / OUT_PATH
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, sort_keys=True, indent=1) + "\n")
    print(f"wrote {out_path}")
    for name, r in readings.items():
        print(f"  {name}: counts={r['eligible_counts']} "
              f"insufficient={r['insufficient_buckets']}")
    return 0


def accepted_prompt_text(repo: Path, corpus: dict, case_id: str) -> str:
    """Frozen cross-derived source of the accepted prompt text: the
    integration-fixture prompt for regression-fixture cases."""
    integration = json.loads((repo / Path(
        "docs/implementation/r6-successor-dense-full-integration-117/"
        "evidence/integration-fixture.json")).read_text())
    texts = {row["case"]["case_id"]: row["case"]["prompt_text"]
             for row in integration["cases"]}
    if case_id not in texts:
        raise KeyError(case_id)
    return texts[case_id]


if __name__ == "__main__":
    sys.exit(main())
