#!/usr/bin/env python3
"""Issue #168 — Arm-C post-SWA requalification authority/freeze record
builder (Phase 0 + Phase 1 pre-observation record).

CPU-only, pure stdlib. Builds the additive evidence-namespace authority
record for the fresh Arm-C requalification campaign authorized by issue
#168, consuming — never reinterpreting — the accepted authority chain:

- #133 (ISSUE117_ARM_C_ORDINARY_SERVING_FAIL), #153
  (ISSUE117_ARM_C_REMEDIATION_BLOCKED / BACKEND_REQUIRES_MULTI_CHUNK),
  #157 (ISSUE117_ARM_C_CHUNK2_CAUSE_LOCALIZED), #166
  (ISSUE117_ARM_C_SWA_REMEDIATION_READY).

Frozen identities are consumed from scripts/issue133_arm_c_retry_campaign
(accepted #133 authority constants) and
tests/test_issue166_swa_remediation_record (accepted #166 producer
hashes) at import time — never restated by hand.

The record binds, BEFORE any physical output:

- fresh campaign_id / physical_authorization_id (issue #168);
- exact InferSwarm and FreeToken execution heads, #166 implementation
  content head and merge, changed runtime-file hashes from #166;
- subject/checkpoint/candidate/geometry identities (accepted #117
  subject, unchanged);
- the exact 24-case accepted #133 regression fixture digest;
- the fresh-corpus census (scripts/issue168_corpus_census.py output)
  with per-bucket eligible counts under both two-chunk readings;
- the pre-observation terminal classification.

It also performs the Phase 0.5 mechanical execution-delta audit of the
remediated producer lineage (Arm-C accepted producer 924cd22e → #153
corrections → #166 SWA lifecycle), re-derived from git history at the
recorded heads rather than narrative.

No GPU, no model execution, no tokenizer import (this module), no
h109-* material.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

import issue133_arm_c_retry_campaign as issue133  # noqa: E402

#: accepted heads named by issue #168 (authority: the issue text)
INFERSWARM_MAIN_168 = "00140a14e3ecbbbd64fdaf1803fe3922e7f4a554"
FREETOKEN_RESEARCH_168 = (
    "6202eeebcdf63e7bc8bb3498dd3c364ae42ee469")
FREETOKEN_IMPLEMENTATION_166 = (
    "64a37a1f1a2797a190610c5adcdcb4157bce63b9")
#: accepted #166 producer hashes (consumed from the accepted record's
#: test module constants — the machine-checked source of truth)
from test_issue166_swa_remediation_record import (  # noqa: E402
    FREETOKEN_STAGE_RUNTIME_SHA as STAGE_RUNTIME_SHA_166,
    FREETOKEN_STAGE_RUNTIME_BASE_SHA as STAGE_RUNTIME_BASE_SHA,
    FREETOKEN_BASE as FREETOKEN_BASE_166,
)

CAMPAIGN_ID = "issue168-arm-c-post-swa-requal-v1"
PHYSICAL_AUTHORIZATION_ID = (
    "physical-authorization-issue168-"
    "inferswarm-00140a14-freetoken-6202eeeb")

EVIDENCE_DIR = Path(
    "docs/implementation/r6-successor-arm-c-requal-blocked-168/evidence")

#: the accepted #133 Arm-C physical producer (the lineage the fresh
#: campaign would execute forward from)
ARM_C_ACCEPTED_PRODUCER = issue133.ISSUE133["frozen_producer"]

#: terminal mandated by issue #168 Phase 1B for corpus insufficiency
BLOCKED_TERMINAL = "ISSUE117_ARM_C_REQUALIFICATION_EVIDENCE_BLOCKED"


def sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def git(repo: Path, *args: str) -> str:
    out = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True, capture_output=True, text=True)
    return out.stdout.strip()


def audit_execution_delta(freetoken: Path) -> dict:
    """Mechanically bound the execution-producing delta from the
    accepted Arm-C producer (924cd22e) through the accepted #166 merge
    (6202eeeb). Lists every commit and every changed file, classifying
    each file as execution-bearing (runtime model math/geometry/planner/
    comparator bytes) or not, from the git trees — never narrative."""
    commits = git(
        freetoken, "rev-list", "--reverse",
        f"{ARM_C_ACCEPTED_PRODUCER}..{FREETOKEN_RESEARCH_168}"
    ).splitlines()
    files: dict[str, list[str]] = {}
    for commit in commits:
        names = git(
            freetoken, "diff-tree", "--no-commit-id", "--name-only",
            "-r", "-m", commit).splitlines()
        for name in names:
            files.setdefault(name, []).append(commit)
    execution_bearing = sorted(
        name for name in files
        if name.startswith(("python/", "benchmarks/"))
        and not name.startswith(("python/tests/", "benchmarks/tests/")))
    test_only = sorted(
        name for name in files if name.startswith((
            "tests/", "python/tests/", "benchmarks/tests/")))
    docs_only = sorted(
        name for name in files if name.startswith("docs/"))
    other = sorted(
        name for name in files
        if name not in execution_bearing and name not in test_only
        and name not in docs_only)
    return {
        "accepted_arm_c_producer": ARM_C_ACCEPTED_PRODUCER,
        "producer_lineage": commits,
        "file_list_convention": (
            "per-commit diff-tree with first-parent merge enumeration "
            "(-m); changed_files_by_class entries are the cumulative "
            "union over the lineage's commits, so reproducing a list "
            "requires the same first-parent -m enumeration, not a "
            "two-dot name-only diff"),
        "changed_files_by_class": {
            "execution_bearing": execution_bearing,
            "test_only": test_only,
            "docs_only": docs_only,
            "other": other,
        },
        "stage_runtime_sha256_at_166": STAGE_RUNTIME_SHA_166,
        "stage_runtime_sha256_at_base": STAGE_RUNTIME_BASE_SHA,
        "delta_statement": (
            "the only execution-bearing runtime change in the fresh "
            "campaign's producer lineage beyond the accepted Arm-C "
            "producer is the #153 single-chunk policy correction and "
            "the #166 session-SWA-lifecycle ownership in "
            "benchmarks/inferswarm_r6/stage_runtime.py (hashes bound "
            "above); model math, weights, tokenizer semantics, "
            "geometry, planner semantics, fencing contract, and "
            "comparator semantics are byte-identical otherwise "
            "(mechanically enumerated here, adjudicated by the "
            "maintainer at acceptance)"),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=ROOT)
    parser.add_argument("--freetoken", type=Path, required=True,
                        help="local FreeToken checkout (read-only)")
    parser.add_argument("--campaign-id", default=CAMPAIGN_ID)
    args = parser.parse_args(argv)
    repo = args.repo.resolve()
    freetoken = args.freetoken.resolve()

    census = json.loads(
        (repo / EVIDENCE_DIR / "corpus-census.json").read_text())

    # Phase 0.1 head verification (remote truth already recorded in the
    # issue; re-proved locally at freeze time)
    is_head = git(repo, "rev-parse", "origin/main")
    ft_head = git(freetoken, "rev-parse", "origin/inferswarm-research")
    heads_ok = (is_head == INFERSWARM_MAIN_168
                and ft_head == FREETOKEN_RESEARCH_168)
    ancestor_proofs = {
        "inferswarm_166_merge_is_ancestor_of_main": subprocess.run(
            ["git", "-C", str(repo), "merge-base", "--is-ancestor",
             INFERSWARM_MAIN_168, is_head]).returncode == 0,
        "freetoken_166_merge_is_ancestor_of_research": subprocess.run(
            ["git", "-C", str(freetoken), "merge-base", "--is-ancestor",
             FREETOKEN_RESEARCH_168, ft_head]).returncode == 0,
        "freetoken_166_implementation_in_merge": subprocess.run(
            ["git", "-C", str(freetoken), "merge-base", "--is-ancestor",
             FREETOKEN_IMPLEMENTATION_166,
             FREETOKEN_RESEARCH_168]).returncode == 0,
    }

    record = {
        "schema": "inferswarm.issue168.arm-c-requal-authority/1",
        "campaign_id": args.campaign_id,
        "physical_authorization_id": PHYSICAL_AUTHORIZATION_ID,
        "issue": "https://github.com/Zutfen-LLC/inferswarm/issues/168",
        "starting_heads": {
            "inferswarm_main": is_head,
            "expected_inferswarm_main": INFERSWARM_MAIN_168,
            "freetoken_inferswarm_research": ft_head,
            "expected_freetoken_inferswarm_research":
                FREETOKEN_RESEARCH_168,
            "verified": heads_ok,
            "ancestor_proofs": ancestor_proofs,
        },
        "accepted_authority_chain": [
            {"issue": 133, "terminal":
             "ISSUE117_ARM_C_ORDINARY_SERVING_FAIL",
             "merge": "1b83bcab0a5e682a438ca0554f71dd0ace15be55"},
            {"issue": 153, "terminal":
             "ISSUE117_ARM_C_REMEDIATION_BLOCKED",
             "classification": "BACKEND_REQUIRES_MULTI_CHUNK"},
            {"issue": 157, "terminal":
             "ISSUE117_ARM_C_CHUNK2_CAUSE_LOCALIZED",
             "merge": "df0365ea606a54222415e34f6cfb127e9f938f0c"},
            {"issue": 166, "terminal":
             "ISSUE117_ARM_C_SWA_REMEDIATION_READY",
             "inferswarm_merge": INFERSWARM_MAIN_168,
             "freetoken_merge": FREETOKEN_RESEARCH_168,
             "freetoken_implementation_head":
                 FREETOKEN_IMPLEMENTATION_166},
        ],
        "subject": {
            "model": issue133.ISSUE133["model"],
            "revision": issue133.ISSUE133["revision"],
            "checkpoint_sha256": issue133.ISSUE133["checkpoint_sha256"],
            "qualification_subject":
                issue133.ISSUE133["qualification_subject"],
            "candidate": issue133.ISSUE133["candidate"],
            "geometry": issue133.ISSUE133["geometry"],
            "chunk_boundary_contract": "64 rows per prefill call",
        },
        "regression_fixture_binding": {
            "accepted_arm_c_fixture_digest":
                issue133.ISSUE133["fixture_digest"],
            "case_count": issue133.ISSUE133["case_count"],
            "renders_reproduced_under_frozen_tokenizer":
                census["regression_fixture"]["renders_reproduced"],
        },
        "fresh_corpus_census": {
            "file": "corpus-census.json",
            "schema": census["schema"],
            "salt": census["salt"],
            "eligible_counts": {
                name: reading["eligible_counts"]
                for name, reading in
                census["eligibility_readings"].items()},
            "insufficient_buckets": {
                name: reading["insufficient_buckets"]
                for name, reading in
                census["eligibility_readings"].items()},
            "max_rendered_len_corpus":
                census["max_rendered_len_corpus"],
        },
        "execution_delta_audit": audit_execution_delta(freetoken),
        "preflight_state": {
            "phase_reached": "phase-1-corpus-freeze",
            "physical_execution_performed": False,
            "outputs_inspected": False,
            "h109_material_accessed": False,
        },
        "pre_observation_terminal": BLOCKED_TERMINAL,
        "terminal_basis": (
            "issue #168 Phase 1B: the fresh public multi-chunk "
            "generalization arm requires four eligible public cases in "
            "each of the second-chunk-remainder buckets 1-8, 9-24, "
            "25-48, and 49-64, derived from the public c109 calibration "
            "corpus; the mechanically derived census (corpus-census.json) "
            "shows upper buckets empty under EVERY defensible reading of "
            "the two-chunk length requirement (the corpus's frozen "
            "length regimes cap raw prompts at 56 tokens, bounding "
            "rendered lengths at 69), so buckets 25-48 and 49-64 are "
            "corpus-insufficient. The issue forbids adapting buckets or "
            "inspecting outputs and mandates stopping pre-observation "
            "with ISSUE117_ARM_C_REQUALIFICATION_EVIDENCE_BLOCKED"),
        "non_claims": [
            "no physical/GPU/model execution occurred",
            "no direct/ordinary observation exists; the Arm-C "
            "requalification question is NOT answered by this record",
            "the accepted #133 FAIL terminal and the #157/#166 records "
            "are untouched and remain the accepted state",
            "no h109-* material was opened, generated, copied, "
            "inferred, reconstructed, or used",
            "Arm D and Arm E were not started",
        ],
        "built_at_unix": int(time.time()),
    }
    if not heads_ok:
        record["starting_heads"]["drift_note"] = (
            "protected heads moved beyond the issue-named heads; the "
            "delta was not mechanically bounded in this record — "
            "maintainer disposition required before any execution")

    out_path = repo / EVIDENCE_DIR / "authority-record.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(record, sort_keys=True, indent=1) + "\n")
    print(f"wrote {out_path}")
    print(f"terminal: {record['pre_observation_terminal']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
