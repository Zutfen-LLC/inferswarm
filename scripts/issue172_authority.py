#!/usr/bin/env python3
"""Issue #172 — Phase 0 authority/freeze record builder (CPU-only, stdlib).

Freezes the physical campaign authority BEFORE any correctness-bearing
execution:

1. verifies the exact accepted starting heads (InferSwarm main, FreeToken
   research) and the #166/#170 ancestry proofs;
2. re-derives the execution-delta audit of the FreeToken producer lineage
   from the accepted Arm-C producer 924cd22e through the accepted #153/#166
   steps to 6202eeeb, proving the ONLY execution-bearing deltas are the
   accepted ones (hash-bound), so no unreviewed model-math/tokenizer/
   geometry/planner/comparator change is introduced;
3. binds the subject/checkpoint/candidate/plan/geometry identities;
4. binds the 24-case regression fixture and 16-case #170 corpus digests;
5. freezes campaign_id / physical_authorization_id, the attempt state
   machine, STOP rules, and non-claims;
6. updates living project status via the canonical generator is done by
   the status step, not here.

Fail-closed: any drift raises and writes nothing.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import issue172_campaign_pins as P  # noqa: E402


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_canonical_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def git(args: list[str], cwd: Path) -> str:
    return subprocess.check_output(
        ["git", "-c", f"safe.directory={cwd}", "-C", str(cwd), *args],
        text=True).strip()


def git_blob(repo: Path, revision: str, rel_path: str) -> bytes:
    return subprocess.check_output(
        ["git", "-c", f"safe.directory={repo}", "-C", str(repo),
         "show", f"{revision}:{rel_path}"])


def is_ancestor(repo: Path, ancestor: str, descendant: str) -> bool:
    result = subprocess.run(
        ["git", "-c", f"safe.directory={repo}", "-C", str(repo),
         "merge-base", "--is-ancestor", ancestor, descendant])
    return result.returncode == 0


def verify_starting_heads(inferswarm: Path, freetoken: Path) -> dict:
    is_main = git(["rev-parse", "HEAD"], inferswarm)
    ft_head = git(["rev-parse", "HEAD"], freetoken)
    proofs = {
        "inferswarm_head_equals_expected": is_main == P.INFERSWARM_MAIN_172,
        "freetoken_head_equals_expected":
            ft_head == P.FREETOKEN_RESEARCH_172,
        "freetoken_166_implementation_is_ancestor":
            is_ancestor(freetoken, P.FREETOKEN_166_IMPLEMENTATION, ft_head),
    }
    if not all(proofs.values()):
        raise SystemExit(f"ISSUE172_AUTHORITY_FAIL: head drift {proofs}")
    return {
        "inferswarm_main": is_main,
        "freetoken_inferswarm_research": ft_head,
        "expected_inferswarm_main": P.INFERSWARM_MAIN_172,
        "expected_freetoken_inferswarm_research": P.FREETOKEN_RESEARCH_172,
        "ancestor_proofs": proofs,
        "ancestor_proofs_note": (
            "FreeToken commits are not resolvable in the InferSwarm object "
            "database, so these booleans are not re-verifiable from this "
            "bundle alone; the underlying commands and their verbatim "
            "observed output are retained in "
            "evidence/cross-repo-provenance.json"),
        "cross_repo_proof_retained_at": "evidence/cross-repo-provenance.json",
        "verified": True,
    }


def execution_delta_audit(freetoken: Path) -> dict:
    """Enumerate the FreeToken delta from the accepted Arm-C producer
    924cd22e to 6202eeeb by class, and hash-bind every execution-bearing
    file at the exact 6202eeeb bytes. The accepted #168 audit already
    adjudicated this delta; this re-derives it mechanically so drift in
    the audit itself is impossible."""
    base = "924cd22ea081f6d4ed471016faf01d427fc5b0d2"
    names = git(
        ["diff", "--name-only", base, P.FREETOKEN_RESEARCH_172], freetoken
    ).splitlines()
    by_class = {"execution_bearing": [], "test_only": [], "docs_only": [],
                "other": []}
    for name in names:
        if name.startswith("tests/"):
            by_class["test_only"].append(name)
        elif name.startswith("docs/"):
            by_class["docs_only"].append(name)
        elif (name.startswith("benchmarks/") or
              name.startswith("python/freetoken/")):
            by_class["execution_bearing"].append(name)
        else:
            by_class["other"].append(name)
    hashes = {}
    for name in by_class["execution_bearing"]:
        blob = git_blob(freetoken, P.FREETOKEN_RESEARCH_172, name)
        hashes[name] = sha256_bytes(blob)
    stage_runtime_ok = (
        hashes.get(P.STAGE_RUNTIME_REL) == P.STAGE_RUNTIME_SHA256_AT_166)
    if not stage_runtime_ok:
        raise SystemExit(
            "ISSUE172_AUTHORITY_FAIL: stage_runtime.py at the research head "
            "is not the accepted #166-remediated bytes "
            f"({hashes.get(P.STAGE_RUNTIME_REL)})")
    comparison = issue168_comparison(freetoken, base, by_class, hashes)
    return {
        "accepted_arm_c_producer": base,
        "producer_head": P.FREETOKEN_RESEARCH_172,
        "changed_files_by_class": by_class,
        "execution_bearing_sha256_at_head": hashes,
        "stage_runtime_matches_166_remediation": stage_runtime_ok,
        "changed_set_is_identical_to_issue168_audit":
            comparison["sets_identical"],
        "issue168_comparison": comparison,
        "delta_statement": (
            "the only execution-bearing runtime change in this campaign's "
            "producer lineage beyond the accepted Arm-C producer (924cd22) "
            "is the accepted #153 single-chunk policy and the accepted #166 "
            "session-SWA-lifecycle ownership (hashes bound here). The "
            "changed set is exactly 'git diff --name-only "
            f"924cd22..6202eee': "
            f"{len(by_class['execution_bearing'])} execution-bearing files "
            f"plus {len(by_class['test_only'])} test-only files. This "
            "campaign's head IS the #168-audited FreeToken commit, so no new "
            "delta exists between the #168-audited head and this campaign's "
            "head. NOTE: this campaign's execution-bearing set is NOT "
            "identical to the set named in the accepted #168 audit, which "
            f"lists {comparison['issue168_execution_bearing_count']} files; "
            "the extra files are byte-identical at both endpoints, so the "
            "#168 set is the more conservative, over-inclusive one. The "
            "difference is enumerated and resolved in "
            "evidence/cross-repo-provenance.json rather than glossed as "
            "agreement."),
    }


def issue168_comparison(freetoken: Path, base: str, by_class: dict,
                        hashes: dict) -> dict:
    """Mechanically compare this campaign's execution-bearing delta against
    the set named by the accepted Issue #168 audit, and prove that every
    file the #168 audit names but this delta does not is byte-identical at
    both endpoints. Authored agreement is not acceptable here: the
    comparison is computed and a contradiction fails closed."""
    accepted = json.loads(
        (P.ROOT / P.ISSUE168_AUTHORITY_RECORD).read_text())
    audit = accepted["execution_delta_audit"]
    theirs = set(audit["changed_files_by_class"]["execution_bearing"])
    ours = set(by_class["execution_bearing"])
    extra = sorted(theirs - ours)
    missing = sorted(ours - theirs)
    unchanged = {}
    for name in extra:
        a = git_blob(freetoken, base, name)
        b = git_blob(freetoken, P.FREETOKEN_RESEARCH_172, name)
        unchanged[name] = a == b
    if missing:
        raise SystemExit(
            "ISSUE172_AUTHORITY_FAIL: #168 audit omits changed "
            f"execution-bearing files {missing}; the campaign delta is "
            "wider than the accepted audit")
    if not all(unchanged.values()):
        changed = [n for n, ok in unchanged.items() if not ok]
        raise SystemExit(
            "ISSUE172_AUTHORITY_FAIL: #168 audit names files that DO differ "
            f"between endpoints ({changed}); the two audits are not "
            "reconcilable")
    return {
        "issue168_audit": P.ISSUE168_AUTHORITY_RECORD,
        "issue168_execution_bearing_count": len(theirs),
        "campaign_execution_bearing_count": len(ours),
        "sets_identical": theirs == ours,
        "extra_files_named_by_issue168_that_did_not_change": extra,
        "files_in_campaign_delta_omitted_by_issue168": missing,
        "every_extra_file_byte_identical_at_both_endpoints": all(
            unchanged.values()),
        "per_file_blob_identity": unchanged,
        "direction_of_discrepancy":
            "issue168 over-inclusive; nothing that changed is omitted from "
            "either set",
        "detail": ("evidence/cross-repo-provenance.json"
                   "#execution_delta_proof.comparison_with_accepted_"
                   "issue168_audit"),
    }


def corpus_bindings() -> dict:
    regression = json.loads(
        (P.ROOT / P.REGRESSION_FIXTURE_PATH).read_text())
    integration = json.loads(
        (P.ROOT / P.INTEGRATION_FIXTURE_PATH).read_text())
    corpus = json.loads((P.ROOT / P.CORPUS_170_PATH).read_text())
    if regression.get("case_count") != P.REGRESSION_ARM_CASE_COUNT:
        raise SystemExit("ISSUE172_AUTHORITY_FAIL: regression fixture count")
    if integration.get("fixture_digest") != P.REGRESSION_FIXTURE_DIGEST_24:
        raise SystemExit(
            "ISSUE172_AUTHORITY_FAIL: integration fixture digest drift")
    cases = corpus["cases"]
    canonical = "sha256:" + sha256_bytes(json.dumps(
        cases, sort_keys=True, separators=(",", ":")).encode())
    if canonical != P.CORPUS_170_DIGEST:
        raise SystemExit(
            f"ISSUE172_AUTHORITY_FAIL: #170 corpus digest drift ({canonical})")
    if len(cases) != P.GENERALIZATION_ARM_CASE_COUNT:
        raise SystemExit("ISSUE172_AUTHORITY_FAIL: #170 corpus count")
    for case in cases:
        if P.FORBIDDEN_NAMESPACE in json.dumps(case):
            raise SystemExit("ISSUE172_AUTHORITY_FAIL: forbidden namespace")
    return {
        "regression_fixture": {
            "file": P.REGRESSION_FIXTURE_PATH,
            "case_count": P.REGRESSION_ARM_CASE_COUNT,
            "fixture_digest": regression["fixture_digest"],
            "integration_fixture_digest":
                integration["fixture_digest"],
        },
        "generalization_corpus": {
            "file": P.CORPUS_170_PATH,
            "corpus_id": corpus["corpus_id"],
            "case_count": len(cases),
            "canonical_corpus_digest": canonical,
            "consumed_without_regeneration": True,
        },
        "combined_identity": {
            "case_count": P.TOTAL_CASE_COUNT,
            "statement": (
                "exact 24 accepted #133 regression identities + exact 16 "
                "accepted #170 generalization identities = 40 canonical "
                "cases; digests re-derived from retained bytes before "
                "launch by issue172_corpus_bind.py"),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inferswarm", default=str(P.ROOT))
    parser.add_argument("--freetoken", required=True)
    parser.add_argument("--out", default=str(P.EVIDENCE_DIR / "authority.json"))
    args = parser.parse_args()

    heads = verify_starting_heads(Path(args.inferswarm), Path(args.freetoken))
    delta = execution_delta_audit(Path(args.freetoken))
    corpus = corpus_bindings()

    record = {
        "schema": P.AUTHORITY_SCHEMA,
        "issue": P.ISSUE,
        "campaign_id": P.CAMPAIGN_ID,
        "physical_authorization_id": P.PHYSICAL_AUTHORIZATION_ID,
        "starting_heads": heads,
        "execution_delta_audit": delta,
        "subject": dict(P.SUBJECT),
        "plan_identities": {
            "arm_b_participant_plan_digest": P.ARM_B_PARTICIPANT_PLAN_DIGEST,
            "chain_plan_digest": P.AUTHORIZED_CHAIN_PLAN_DIGEST,
            "participant_identity": P.AUTHORIZED_PARTICIPANT_IDENTITY,
            "r5a_static_plan_digest_accepted_predecessor":
                P.AUTHORIZED_R5A_STATIC_PLAN_DIGEST,
            "r5a_static_plan_digest_requalified_campaign":
                P.REQUALIFIED_R5A_STATIC_PLAN_DIGEST,
            "r5a_fence_note": (
                "both fences are bound explicitly: the accepted predecessor "
                "fence and the fence the physical run actually used under "
                "producer 6202eee"),
            "environment_canonical_sha256":
                P.AUTHORIZED_ENVIRONMENT_CANONICAL_SHA256,
        },
        "corpus_bindings": corpus,
        "attempt_state_machine": {
            "attempt_id": P.ATTEMPT_ID,
            "rules": [
                "retain every launch and attempt",
                "a pre-observation infrastructure failure is correctable only "
                "when mechanically proven to have emitted/committed zero "
                "correctness-bearing results and to have preserved the "
                "frozen substrate",
                "an invalid attempt that emitted any correctness-bearing "
                "result is terminal STOP: no later run in this issue "
                "derives PASS/FAIL authority",
                "after any valid admissible mismatch, repeatability "
                "variation, or correctness-bearing invariant failure the "
                "terminal is FAIL; the campaign is never restarted to seek "
                "a passing sample",
            ],
            "stopping_condition": "8 committed tokens (length-only)",
            "repeat_counts": {
                "canonical_cases": 1,
                "sentinel_repeats_per_identity_per_arm":
                    P.SENTINEL_REPEATS,
            },
        },
        "non_claims": [
            "a PASS here does not rewrite the historical #133 FAIL; it is a "
            "new post-remediation physical result",
            "Arm D and Arm E are not started in this issue",
            "no diagnosis/remediation of a FAIL happens inside this issue",
            "no h109-* material was opened, generated, copied, inferred, "
            "reconstructed, decrypted, or used",
        ],
        "pre_observation_state": {
            "physical_execution_performed": False,
            "outputs_inspected": False,
            "h109_material_accessed": False,
        },
        "built_at_unix": int(time.time()),
    }
    write_canonical_json(Path(args.out), record)
    print(json.dumps({
        "authority": args.out,
        "campaign_id": P.CAMPAIGN_ID,
        "heads_verified": heads["verified"],
        "stage_runtime_ok": delta["stage_runtime_matches_166_remediation"],
        "corpus": corpus["combined_identity"],
    }, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
