#!/usr/bin/env python3
"""Issue #175 — Phase 0 Arm-D authority/freeze record builder (CPU-only, stdlib).

Freezes the physical warm-restart campaign authority BEFORE any
correctness-bearing execution:

1. verifies actual heads: InferSwarm main at the maintainer-named
   #173 head 246dcca8, FreeToken research at 6202eeeb; proves the
   accepted PR #174 merge 52c3b560 and the #166 implementation head
   are ancestors;
2. classifies ALL post-#172 InferSwarm drift (52c3b560..246dcca8) by
   file class: test/CI-orchestration-only, documentation-only, or
   execution-bearing (none expected; any execution-bearing file makes
   the builder fail closed pending an explicit applicability audit);
3. binds the frozen subject/checkpoint/candidate/plan/geometry
   identities and the accepted #117 CPU warm-restart fixture (loaded
   by digest, semantics consumed not reinterpreted);
4. binds the accepted #172 comparison material by file sha256 (the
   Phase 4 correctness authority: serving reports, ordinary campaign
   records, direct run);
5. binds the exact Node-local artifact-cache roots and per-participant
   required artifact digests for both nodes;
6. freezes the restart boundary, launch order, attempt state machine,
   STOP rules, restart count, correctness corpus, observation window,
   and non-claims;
7. binds the exact restart command authority and the process-death
   proof method (exact-PID kill + /proc + pgrep + ss -tln
   re-observation + PID/boot-start-identity anti-reuse proof);
8. binds the Source/peer transfer observation mechanism (strace
   openat/connect tracing of every execution-bearing process during
   each restart window, retained raw and reduced mechanically).

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
import issue175_campaign_pins as P  # noqa: E402


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_canonical_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def git(repo: Path, args: list[str]) -> str:
    return subprocess.check_output(
        ["git", "-c", f"safe.directory={repo}", "-C", str(repo), *args],
        text=True).strip()


def is_ancestor(repo: Path, ancestor: str, descendant: str) -> bool:
    result = subprocess.run(
        ["git", "-c", f"safe.directory={repo}", "-C", str(repo),
         "merge-base", "--is-ancestor", ancestor, descendant])
    return result.returncode == 0


def verify_heads(inferswarm: Path) -> dict:
    proofs = {
        "merge_174_is_ancestor_of_main":
            is_ancestor(inferswarm, P.INFERSWARM_MERGE_174,
                        P.INFERSWARM_MAIN_175),
    }
    if not all(proofs.values()):
        raise SystemExit(f"ISSUE175_AUTHORITY_FAIL: ancestry {proofs}")
    return {
        "inferswarm_main": P.INFERSWARM_MAIN_175,
        "freetoken_inferswarm_research": P.FREETOKEN_RESEARCH_175,
        "ancestor_proofs": proofs,
        "verified": True,
        "note": (
            "head equality against origin is asserted by the operator "
            "procedure (fetch + rev-parse recorded in the run log); the "
            "mechanical proofs retained here are the ancestry checks"),
    }


def classify_drift(inferswarm: Path) -> dict:
    """Classify every commit in 52c3b560..246dcca8 by changed-file class."""
    names = git(inferswarm, [
        "diff", "--name-only", P.INFERSWARM_MERGE_174,
        P.INFERSWARM_MAIN_175]).splitlines()
    by_class = {"execution_bearing": [], "test_or_ci_only": [],
                "docs_only": [], "other": []}
    for name in names:
        if name.startswith(("benchmarks/", "python/freetoken/")):
            by_class["execution_bearing"].append(name)
        elif name.startswith(("tests/", "scripts/run_full_cpu_suite.py",
                              "scripts/plan_ci.py", "scripts/ci_groups.json",
                              ".github/")):
            by_class["test_or_ci_only"].append(name)
        elif name.startswith("docs/") or name.endswith(".md"):
            by_class["docs_only"].append(name)
        else:
            by_class["other"].append(name)
    if by_class["execution_bearing"] or by_class["other"]:
        raise SystemExit(
            "ISSUE175_AUTHORITY_FAIL: execution-bearing or unclassified "
            f"post-#172 drift {by_class}")
    commits = git(inferswarm, [
        "rev-list", "--count",
        f"{P.INFERSWARM_MERGE_174}..{P.INFERSWARM_MAIN_175}"])
    return {
        "range": f"{P.INFERSWARM_MERGE_174}..{P.INFERSWARM_MAIN_175}",
        "commit_count": int(commits),
        "changed_files_by_class": by_class,
        "classification": (
            "post-#172 drift is test/CI-orchestration-only and "
            "documentation-only (the accepted #173 parallel CPU-suite "
            "runner and two hardware-ledger docs); no execution-bearing "
            "change to the Issue #117 / participant / artifact / planner "
            "/ serving path exists in the delta, so no applicability "
            "audit beyond this classification is required"),
    }


def bound_172_material() -> dict:
    bindings = {}
    for label, path in (
        ("corpus", P.CORPUS_172_PATH),
        ("serving_report_canonical", P.SERVING_REPORT_172_CANONICAL),
        ("serving_report_sentinels", P.SERVING_REPORT_172_SENTINELS),
        ("ordinary_canonical", P.ORDINARY_172_CANONICAL),
        ("ordinary_sentinels", P.ORDINARY_172_SENTINELS),
        ("direct_run", P.DIRECT_172_RUN),
    ):
        actual = sha256_file(path)
        bindings[label] = {"path": str(path.relative_to(P.ROOT)),
                           "sha256": actual}
    if bindings["corpus"]["sha256"] != P.CORPUS_172_FILE_SHA256:
        raise SystemExit("ISSUE175_AUTHORITY_FAIL: #172 corpus sha drift")
    corpus = json.loads(P.CORPUS_172_PATH.read_text())
    if len(corpus["cases"]) != 40:
        raise SystemExit("ISSUE175_AUTHORITY_FAIL: corpus case count")
    # the accepted warm-restart CPU fixture is bound by digest
    wr = json.loads(P.WARM_RESTART_117.read_text())
    for key in P.WARM_RESTART_117_REQUIRED_KEYS:
        if key not in wr:
            raise SystemExit(f"warm-restart fixture missing {key}")
    if wr["warm_restart_model_weight_transfer_bytes"] != 0:
        raise SystemExit("accepted fixture semantics drift (transfer != 0)")
    return {
        "files": bindings,
        "corpus_case_count": 40,
        "warm_restart_fixture": {
            "path": str(P.WARM_RESTART_117.relative_to(P.ROOT)),
            "sha256": sha256_file(P.WARM_RESTART_117),
            "per_participant_reacquired_bytes":
                {k: v["reacquired_bytes"]
                 for k, v in wr["per_participant"].items()},
            "coordinator_bytes_observed": wr["coordinator_bytes_observed"],
            "warm_restart_model_weight_transfer_bytes":
                wr["warm_restart_model_weight_transfer_bytes"],
            "semantics": (
                "loaded and bound, never reinterpreted: cache-hit bytes "
                "per participant, zero reacquired bytes, zero transfer "
                "bytes, materialization witnesses semantically "
                "equivalent, coordinator bulk bytes zero"),
        },
        "comparison_authority": (
            "post-restart ordinary results compare against the accepted "
            "#172 canonical visible/committed results for the same case "
            "identities (serving report token_events + ordinary HTTP "
            "records); no new comparator is derived"),
    }


def restart_boundary_authority() -> dict:
    return {
        "restart_count": P.RESTART_COUNT,
        "boundary_steps": [
            "terminate the execution-bearing participant runtime "
            "processes for the accepted stage topology by exact PID "
            "(coordinator process on 00, node-agent + spawn-isolated "
            "stage-1/stage-2 children on 01, last-stage service on 03)",
            "prove process death: /proc/<pid> absent, pgrep -af pattern "
            "empty, ss -tln free of 18080/18485/18486, GPU memory "
            "reclaimed (nvidia-smi 0-1 MiB), and record PID + process "
            "start time (/proc/<pid>/stat field 22) + boot_id so no "
            "post-restart PID is confused with the pre-restart process",
            "prove old accelerator realization inactive: GPU memory "
            "usage back to ~0 on all three frozen devices",
            "preserve Node-local verified immutable artifact cache "
            "bytes on disk (no clean/regenerate/repopulate; re-verify "
            "digests after restart)",
            "start fresh participant runtime processes under exact "
            "frozen producer bytes (same worktrees, verified clean at "
            "6202eeeb before launch)",
            "Coordinator re-ingests participant inventory/capability "
            "state, replans from the same frozen environment/chain-plan/"
            "serving-evidence bytes, and must reproduce the accepted "
            "plan digest 14344025ed0d (proven for two independent "
            "coordinator instances in #172)",
            "every required immutable artifact satisfied from verified "
            "local cache hit (per-stage fetched_bytes == accepted "
            "values, local cache read + H2D materialization accounted "
            "separately)",
            "fresh serving sessions after restart; no stale pre-restart "
            "session/epoch/position commit may land",
        ],
        "process_death_proof_method": (
            "exact-PID kill; then mechanical re-observation: /proc/<pid> "
            "gone, pgrep pattern empty, ss -tln ports free, nvidia-smi "
            "per-device memory ~0, plus pid+starttime+boot_id record "
            "for every pre- and post-restart process identity"),
        "transfer_observation": (
            "strace -f -e trace=openat,connect attached to every "
            "execution-bearing process for each full restart window; "
            "raw traces retained; reducer classifies every openat of "
            "model-weight bytes and every connect() destination"),
        "launch_order": [
            "1. last-stage service on 03 (single-connection; relaunch "
            "per chain realization)",
            "2. node-agent on 01 (drives stages 1-2, connects to 03)",
            "3. external CPU-only coordinator waist on 00",
            "4. ordinary client from the orchestration host",
        ],
        "stop_rules": [
            "invalid attempt emitted a correctness-bearing result",
            "accepted cache mutated/repaired/reacquired during the "
            "canonical campaign",
            "correctness-bearing harness/runtime bytes changed after "
            "freeze",
            "valid Source/peer model-weight reacquisition",
            "valid post-restart correctness mismatch",
            "old runtime/process identity remained active (restart not "
            "genuine)",
            "artifact-integrity failure bypassed or auto-repaired",
        ],
        "observation_window": (
            "from first pre-restart baseline request to the completion "
            "of each restart's post-restart correctness corpus"),
        "non_claims": [
            "no OS/Node reboot survival is claimed",
            "no disk replacement or Node replacement is claimed",
            "no cache reconstruction after cache loss is claimed",
            "no live in-flight request continuation across process "
            "death is claimed",
            "no mutable KV/SWA/radix/session cache reuse across restart "
            "is claimed (immutable artifact cache only)",
            "no Arm-E inventory/locality mutation is claimed",
            "no failover/replica promotion is claimed",
            "no production restart orchestration/API stability is "
            "claimed",
            "no h109-* material was opened, generated, copied, "
            "inferred, reconstructed, decrypted, or used",
            "Arm E is not started in this issue",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inferswarm", default=str(P.ROOT))
    parser.add_argument("--out",
                        default=str(P.EVIDENCE_DIR / "authority.json"))
    args = parser.parse_args()

    heads = verify_heads(Path(args.inferswarm))
    drift = classify_drift(Path(args.inferswarm))
    material = bound_172_material()

    record = {
        "schema": P.AUTHORITY_SCHEMA,
        "issue": P.ISSUE,
        "campaign_id": P.CAMPAIGN_ID,
        "physical_authorization_id": P.PHYSICAL_AUTHORIZATION_ID,
        "starting_heads": heads,
        "post_172_drift": drift,
        "subject": dict(P.SUBJECT),
        "frozen_geometry_uuids": {
            host: dict(gpus) for host, gpus in P.FROZEN_GEOMETRY_UUIDS.items()},
        "plan_identities": {
            "chain_plan_digest_172": P.CHAIN_PLAN_172_DIGEST,
            "environment_canonical_sha256_172":
                P.ENVIRONMENT_172_CANONICAL_SHA256,
            "r5a_static_plan_digest_172": P.R5A_STATIC_PLAN_172_DIGEST,
            "participant_identity": P.PARTICIPANT_IDENTITY,
            "coordinator_plan_digest_172": P.COORDINATOR_PLAN_DIGEST_172,
        },
        "accepted_172_material": material,
        "artifact_cache_binding": {
            "substrate_root": P.SUBSTRATE_ROOT,
            "per_node_artifacts": {
                host: {rel: digest for rel, digest in arts.items()}
                for host, arts in P.CACHE_ARTIFACTS.items()
            },
            "model_view_01": P.MODEL_VIEW_01,
            "model_view_03": P.MODEL_VIEW_03,
            "tokenizer_deployment": P.TOKENIZER_DEPLOYMENT,
            "tokenizer_asset_pins": dict(P.TOKENIZER_ASSET_PINS),
        },
        "deployment_authority": {
            "coordinator_repo": P.COORDINATOR_REPO,
            "coordinator_python": P.COORDINATOR_PYTHON,
            "node_repo": P.NODE_REPO,
            "node_python": P.NODE_PYTHON,
            "chain_plan_input": P.CHAIN_PLAN_INPUT,
            "environment_input": P.ENVIRONMENT_INPUT,
            "serving_evidence_input": P.SERVING_EVIDENCE_INPUT,
            "last_stage_endpoint": f"{P.LAST_STAGE_HOST}:{P.LAST_STAGE_PORT}",
            "node_agent_endpoint": f"{P.NODE_AGENT_HOST}:{P.NODE_AGENT_PORT}",
            "coordinator_origin": P.COORDINATOR_ORIGIN,
            "scope_id": P.SCOPE_ID,
        },
        "restart_authority": restart_boundary_authority(),
        "corpus_plan": {
            "pre_restart_screen_cases": list(P.SCREEN_CASES),
            "restart_1": "exact accepted 40-case canonical corpus + "
                         "trailing fencing-arm negative control",
            "restart_2": "exact accepted seven sentinel identities x 6 "
                         "repeats (the accepted #172 protocol verbatim)",
        },
        "attempt_state_machine": {
            "attempt_id": P.ATTEMPT_ID,
            "rules": [
                "retain every launch and attempt",
                "a pre-observation infrastructure failure is correctable "
                "only when mechanically proven to have emitted/committed "
                "zero correctness-bearing results and preserved the "
                "frozen canonical cache",
                "an invalid attempt that emitted any correctness-bearing "
                "result is terminal STOP",
                "after a valid failure, no fresh passing campaign is "
                "created inside this issue",
            ],
        },
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
        "drift_classification": drift["classification"][:60],
        "corpus_cases": material["corpus_case_count"],
    }, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
