#!/usr/bin/env python3
"""Issue #170 — Arm-C long-remainder corpus authority-record builder.

CPU-only, pure stdlib. Builds the additive authority record for the
prospective 16-case public corpus, consuming — never reinterpreting —
the accepted authority chain (#133/#153/#157/#166/#168) and the
generated corpus record (scripts/issue170_corpus_producer.py output).

Binds, at freeze time:

- the exact accepted starting heads (InferSwarm main@941d0fe = PR #169
  merge, FreeToken inferswarm-research@6202eeeb = accepted #166
  remediation merge) with ancestry proofs re-derived from the local
  git objects (never narrative);
- the #168 accepted blocker terminal (consumed from its retained
  terminal-reduction.json);
- the frozen tokenizer/software identity and the 24/24 render
  preflight result (consumed from corpus.json);
- generator/methodology source hashes and the canonical corpus digest
  (consumed from corpus.json — never restated);
- explicit non-claims (no physical execution, no h109, no Arm-C
  verdict, no statistical inference claim).

No GPU, no model execution, no tokenizer import (this module), no
h109-* material.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import issue170_corpus_methodology as M  # noqa: E402

#: FreeToken identities consumed from the accepted #168 authority
#: module (import-don't-restate). The #170 starting InferSwarm head
#: (941d0fe…, PR #169 merge) did not exist when #168 froze its
#: constants, so it is pinned in the frozen methodology module and
#: independently cross-pinned in the record tests.
import issue168_authority_record as _issue168  # noqa: E402
FREETOKEN_RESEARCH_170 = _issue168.FREETOKEN_RESEARCH_168
FREETOKEN_IMPLEMENTATION_166 = _issue168.FREETOKEN_IMPLEMENTATION_166
assert M.FREETOKEN_RESEARCH_170 == FREETOKEN_RESEARCH_170, (
    "FreeToken research head drift between #170 methodology and the "
    "accepted #168 authority module")

EVIDENCE = M.EVIDENCE_DIR
BLOCKER_DIR = Path(
    "docs/implementation/r6-successor-arm-c-requal-blocked-168/evidence")


def sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def git(repo: Path, *args: str) -> str:
    out = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True, capture_output=True, text=True)
    return out.stdout.strip()


def is_ancestor(repo: Path, ancestor: str, descendant: str) -> bool:
    return subprocess.run(
        ["git", "-C", str(repo), "merge-base", "--is-ancestor",
         ancestor, descendant]).returncode == 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=ROOT)
    parser.add_argument("--freetoken", type=Path, required=True,
                        help="local FreeToken checkout (read-only)")
    args = parser.parse_args(argv)
    repo = args.repo.resolve()
    freetoken = args.freetoken.resolve()

    corpus = json.loads((EVIDENCE / "corpus.json").read_text())
    if corpus.get("schema") != M.CORPUS_SCHEMA:
        raise SystemExit("corpus schema drift; authority record fails "
                         "closed")

    blocker = json.loads(
        (repo / BLOCKER_DIR / "terminal-reduction.json").read_text())
    if blocker.get("verdict") != M.ACCEPTED_BLOCKER_TERMINAL:
        raise SystemExit("accepted #168 blocker terminal missing or "
                         "altered; authority contradiction")

    # starting-head verification (local git object truth)
    is_main = git(repo, "rev-parse", "origin/main")
    ft_head = git(freetoken, "rev-parse", "origin/inferswarm-research")
    heads_ok = (is_main == M.INFERSWARM_MAIN_170
                and ft_head == M.FREETOKEN_RESEARCH_170)
    head = git(repo, "rev-parse", "HEAD")
    ancestor_proofs = {
        "starting_main_is_ancestor_of_working_head":
            is_ancestor(repo, M.INFERSWARM_MAIN_170, head),
        "freetoken_166_implementation_in_research_merge":
            is_ancestor(freetoken, FREETOKEN_IMPLEMENTATION_166,
                        FREETOKEN_RESEARCH_170),
        "freetoken_166_merge_is_ancestor_of_research_head":
            is_ancestor(freetoken, FREETOKEN_RESEARCH_170, ft_head),
        "freetoken_research_head_unchanged":
            ft_head == FREETOKEN_RESEARCH_170,
    }

    record = {
        "schema": M.AUTHORITY_SCHEMA,
        "corpus_id": M.CORPUS_ID,
        "issue": "https://github.com/Zutfen-LLC/inferswarm/issues/170",
        "accepted_authority_chain": [
            {"issue": 133, "terminal":
             "ISSUE117_ARM_C_ORDINARY_SERVING_FAIL"},
            {"issue": 153, "terminal":
             "ISSUE117_ARM_C_REMEDIATION_BLOCKED",
             "classification": "BACKEND_REQUIRES_MULTI_CHUNK"},
            {"issue": 157, "terminal":
             "ISSUE117_ARM_C_CHUNK2_CAUSE_LOCALIZED"},
            {"issue": 166, "terminal":
             "ISSUE117_ARM_C_SWA_REMEDIATION_READY"},
            {"issue": 168, "terminal": M.ACCEPTED_BLOCKER_TERMINAL,
             "classification": "corpus_insufficiency_pre_observation",
             "record": str(BLOCKER_DIR / "terminal-reduction.json"),
             "consumed_not_reinterpreted": True},
        ],
        "starting_heads": {
            "inferswarm_main": is_main,
            "expected_inferswarm_main": M.INFERSWARM_MAIN_170,
            "freetoken_inferswarm_research": ft_head,
            "expected_freetoken_inferswarm_research":
                M.FREETOKEN_RESEARCH_170,
            "verified": heads_ok,
            "ancestor_proofs": ancestor_proofs,
        },
        "regression_fixture_binding": {
            "accepted_arm_c_fixture_digest":
                corpus["preflight_24_render_reproduction"]
                ["accepted_fixture_digest"],
            "case_count": 24,
            "renders_reproduced_under_frozen_tokenizer":
                corpus["preflight_24_render_reproduction"]
                ["renders_reproduced"],
        },
        "corpus_binding": {
            "file": "corpus.json",
            "schema": corpus["schema"],
            "canonical_corpus_digest":
                corpus["canonical_corpus_digest"],
            "case_count": corpus["case_count"],
            "generator_sha256": corpus["generator_sha256"],
            "methodology_sha256": corpus["methodology_sha256"],
            "seed": corpus["seed"],
            "case_prefix": corpus["case_prefix"],
        },
        "physical_execution": {
            "performed": False,
            "statement": (
                "no GPU, no CUDA initialization, no Gemma model "
                "execution, no FreeToken candidate runtime execution, "
                "no direct/ordinary serving, no candidate-output "
                "inspection, no correctness-bearing SSH execution "
                "occurred in this issue"),
        },
        "forbidden_material": {
            "namespace": M.FORBIDDEN_NAMESPACE,
            "statement": (
                "no h109-* path, metadata, seed, plaintext, or "
                "ciphertext-derived content was opened, generated, "
                "copied, inferred, or used in generation or exclusion "
                "logic"),
        },
        "non_claims": [
            "this corpus does not answer whether #166 fixes Arm C; "
            "no Arm-C PASS/FAIL is derived",
            "this is a coverage fixture, not a statistical population "
            "theorem; no statistical-qualification claim is made",
            "Arm D and Arm E are not started",
            "the physical Arm-C requalification successor remains "
            "separately blocked pending maintainer acceptance/merge "
            "of this corpus freeze",
        ],
    }
    out = EVIDENCE / "authority-record.json"
    out.write_text(json.dumps(record, sort_keys=True, indent=1) + "\n")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
