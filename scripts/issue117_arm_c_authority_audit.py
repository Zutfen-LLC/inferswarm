#!/usr/bin/env python3
"""Issue #117 Arm C — pre-execution authority audit + attempt-lineage
recovery builder (retention/derivation only; CPU-only; no rerun).

Correction /2 (blocker-derivation correction pass): the audit gains the
mechanically derived frozen-comparator defect statement, the
comparator-modification forensics the blocker reducer cross-checks, and
the FAIL-CLOSED post-audit correction allowlist (exact sha256 per
corrected file; the frozen methodology/driver are never allowable).

Builds two retained evidence documents from mechanically verifiable
sources only:

1. ``pre-execution-authority-audit.json``
   Binds, by Git blob SHA and SHA-256, every correctness-bearing Arm-C
   file at the claimed pre-execution freeze commit
   ``5e2c83a09031d68784c3098fc9dad319b684f0da``
   (``run-record.json:pre_execution_inferwarm_sha``), mechanically
   classifies every post-freeze change (``5e2c83a..HEAD``), and
   discloses that the direct driver and the reducer changed after the
   declared freeze — i.e. the final current scripts are NOT the scripts
   frozen by ``pre_execution_inferwarm_sha``.

2. ``attempt-lineage.json`` (schema /3)
   Recovers the methodology §10 lineage dimensions from existing
   contemporaneous evidence only. Schema /3 supersedes /2: attempt
   classifications are corrected to the mechanically derived campaign
   disposition (the frozen comparator's invocation-semantics defect),
   physical chronology is carried separately from the authored logical
   order, and every previously authored validity flag is retained
   verbatim as historical/post-hoc classification. No timestamp or
   worktree identity is invented: unrecoverable fields carry an
   explicit ``unknown / not retained`` marker with an explanation.

Run from the repo root:  python3 scripts/issue117_arm_c_authority_audit.py
"""
from __future__ import annotations

import datetime
import hashlib
import json
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AREA = ROOT / "docs/implementation/r6-successor-dense-full-integration-117"
ARM_C = AREA / "evidence/arm-c"

#: The claimed pre-execution freeze (run-record.json binds this SHA).
FREEZE_SHA = "5e2c83a09031d68784c3098fc9dad319b684f0da"

#: The physical campaign/evidence commit (first commit after the
#: campaign; binds the retained physical bytes).
CAMPAIGN_COMMIT = "dd4154dbc4109a0966490e5b1137ef55fd6c9306"

#: Correctness-bearing Arm-C code/method files that existed at the
#: freeze commit. Files added after the freeze are disclosed below as
#: post-freeze additions (they are not frozen authority).
FROZEN_FILES = [
    "docs/implementation/r6-successor-dense-full-integration-117/METHODOLOGY-ARM-C.md",
    "scripts/issue117_arm_c_direct.py",
    "scripts/issue117_arm_c_evidence.py",
    "scripts/issue117_arm_c_client.py",
    "scripts/issue117_arm_c_plan.py",
    "scripts/issue117_arm_c_fakeroot.py",
    "scripts/issue117_arm_c_observe.py",
    "tests/test_issue117_arm_c_retention.py",
]

#: Contemporaneous execution session (the channel through which every
#: fabric command of the campaign was issued). Read-only.
SESSION_ID = "20260909_004724_7f3f1e"
SESSION_DB = Path.home() / ".hermes" / "state.db"

#: Host-observed identity of the staged direct driver on inferswarm01
#: (``/srv/inferswarm/state/arm-c/scripts/issue117_arm_c_direct.py``),
#: recorded during the correction pass (2026-09-09, read-only ssh):
#: sha256 c0f03ef5…, mtime 2026-09-09T10:43:04Z — i.e. AFTER direct-6
#: completed (10:28:36Z) and BEFORE direct-9 completed (11:09:05Z).
STAGED_DRIVER_SHA256 = (
    "c0f03ef5d5b7aaba1e36cdee3ca310d29ce9d1bd70b9b1bfa4f947ddeefa204a")
STAGED_DRIVER_MTIME_UTC = "2026-09-09T10:43:07.698991040Z"  # stat(2) ns

TT = datetime.timezone.utc


def utc(ns_or_ts: float) -> str:
    return datetime.datetime.fromtimestamp(ns_or_ts, TT).isoformat()


def git(args: list[str]) -> str:
    return subprocess.check_output(
        ["git", "-c", f"safe.directory={ROOT}", "-C", str(ROOT), *args],
        text=True).strip()


def blob_sha(rev: str, path: str) -> str | None:
    try:
        return git(["rev-parse", f"{rev}:{path}"])
    except subprocess.CalledProcessError:
        return None


def blob_bytes(rev: str, path: str) -> bytes:
    return subprocess.check_output(
        ["git", "-c", f"safe.directory={ROOT}", "-C", str(ROOT),
         "cat-file", "blob", f"{rev}:{path}"])


def transcript_launch_observations() -> tuple[dict, str, str]:
    """Read-only census of per-attempt launch commands in the retained
    execution-session transcript. Returns ({attempt_id: earliest
    message timestamp mentioning its --attempt-id launch}, chain
    digest over the census messages)."""
    db = sqlite3.connect(f"file:{SESSION_DB}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    rows = db.execute(
        "SELECT m.id AS mid, m.timestamp, m.content FROM messages m "
        "JOIN sessions s ON m.session_id = s.id "
        "WHERE s.id = ? AND m.content LIKE '%--attempt-id armc-%' "
        "ORDER BY m.id", (SESSION_ID,)).fetchall()
    first_seen: dict[str, float] = {}
    chain = hashlib.sha256()
    for row in rows:
        chain.update(str(row["mid"]).encode())
        chain.update(row["content"].encode())
        for attempt_id in set(re.findall(
                r"--attempt-id (armc-[a-z0-9-]+)", row["content"])):
            first_seen.setdefault(attempt_id, row["timestamp"])
    # last-stage-service (lss) observations: first transcript message
    # mentioning the arm-c last-stage service launch.
    lss = db.execute(
        "SELECT m.id AS mid, m.timestamp FROM messages m JOIN sessions s "
        "ON m.session_id = s.id WHERE s.id = ? AND m.content LIKE "
        "'%last_stage_service%arm-c%' ORDER BY m.id LIMIT 1",
        (SESSION_ID,)).fetchone()
    lss_utc = utc(lss["timestamp"]) if lss else "unknown / not retained"
    db.close()
    return {k: utc(v) for k, v in first_seen.items()}, lss_utc, \
        chain.hexdigest()


def build_authority_audit(head: str) -> dict:
    frozen: dict[str, dict] = {}
    for path in FROZEN_FILES:
        bs = blob_sha(FREEZE_SHA, path)
        assert bs is not None, f"frozen file missing at {FREEZE_SHA}: {path}"
        content = blob_bytes(FREEZE_SHA, path)
        current = hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
        frozen[path] = {
            "git_blob_sha_at_freeze": bs,
            "sha256_at_freeze": hashlib.sha256(content).hexdigest(),
            "sha256_at_campaign_commit": hashlib.sha256(
                blob_bytes(CAMPAIGN_COMMIT, path)).hexdigest(),
            "sha256_current_head": current,
            "status_at_head": (
                "unchanged_since_freeze"
                if current == hashlib.sha256(content).hexdigest()
                else "changed_after_freeze"),
        }

    # mechanical classification of EVERY post-freeze change
    name_status = git(["diff", "--name-status", f"{FREEZE_SHA}..{head}"])
    classifications = []
    for line in name_status.splitlines():
        if not line.strip():
            continue
        status, path = line.split("\t", 1)
        path = path.strip()
        note = {
            "M": "modified after the declared pre-execution freeze",
            "A": "added after the declared pre-execution freeze "
                 "(not frozen authority)",
        }.get(status[0], f"post-freeze change ({status})")
        if path.endswith("scripts/issue117_arm_c_direct.py"):
            note = ("POST-FREEZE COMPARATOR CHANGE: the direct driver at "
                    "the freeze implemented the frozen single-shot "
                    "generate(..., max_new_tokens=8) comparator; the "
                    "committed post-campaign version implements per-token "
                    "replay-prefill generate(..., max_new_tokens=2) and "
                    "declares the single-shot invocation invalid")
        elif path.endswith("scripts/issue117_arm_c_evidence.py"):
            note = ("POST-FREEZE REDUCER CHANGE: the reducer at the "
                    "freeze failed closed on any invalid attempt with a "
                    "correctness-bearing result and counted every "
                    "/srv/models/ open toward participant_source_tree_"
                    "reads; the post-campaign version accumulated such "
                    "attempts into a maintainer-review list and exempted "
                    "tokenizer/config metadata reads — reducer semantics "
                    "changed after observation")
        classifications.append({
            "path": path, "git_status": status,
            "first_commit_after_freeze": git([
                "log", "--format=%H", "--reverse",
                f"{FREEZE_SHA}..{head}", "--", path]).splitlines()[0],
            "classification": "disclosed post-freeze change",
            "note": note,
        })

    audit = {
        "schema": "inferswarm.issue117.arm-c."
                  "pre-execution-authority-audit/2",
        "claimed_pre_execution_inferswarm_sha": FREEZE_SHA,
        "freeze_commit_committed_utc": utc(float(git([
            "log", "-1", "--format=%ct", FREEZE_SHA]))),
        "physical_campaign_commit": CAMPAIGN_COMMIT,
        "head_classified": head,
        "frozen_correctness_bearing_files": frozen,
        "post_freeze_changes": classifications,
        "comparator_freeze_findings": [
            "METHODOLOGY-ARM-C.md §4 (frozen at 5e2c83a) defines the "
            "direct comparator as one generate(session_id=i, "
            "prompt_token_ids=<rendered ids>, max_new_tokens=8) per case",
            "scripts/issue117_arm_c_direct.py at 5e2c83a implements "
            "exactly that single-shot invocation — the single-shot "
            "invocation is what the frozen methodology told the direct "
            "arm to use",
            "the frozen ordinary path is NOT a single-shot generate: "
            "the frozen FreeToken producer 924cd22e's "
            "EpochServingController.serve_tokens (retained verbatim, "
            "sha256-pinned, under evidence/arm-c/frozen-freetoken/"
            "924cd22e/) invokes the runtime per committed position with "
            "the full replay prefix and max_new_tokens=2, commits only "
            "step zero, discards the speculative second token, and "
            "repeats; the ordinary HTTP Coordinator dispatches every "
            "/v1/chat/completions request through exactly this call",
            "MECHANICALLY DERIVED COMPARATOR DEFECT: the frozen Arm-C "
            "methodology failed its own comparator-isolation "
            "requirement — the direct arm and the ordinary arm "
            "differed in runtime invocation semantics in addition to "
            "differing in control-plane routing, so the frozen "
            "campaign could not establish ordinary-vs-direct serving "
            "equivalence or semantic failure as designed",
            "the direct driver was modified after correctness-bearing "
            "execution: the staged driver on inferswarm01 was overwritten "
            "in place at 2026-09-09T10:43:04Z (between armc-direct-6 "
            "completion 10:28:36Z and armc-direct-7 observation "
            "10:49:28Z) and first committed (per-token replay-prefill, "
            "max_new_tokens=2) at dd4154d",
            "the exact staged driver bytes used by armc-direct-1..6 "
            "are unknown / not retained (the staged copy was "
            "overwritten in place; no direct-6-era copy exists); the "
            "unrecoverability independently strengthens the evidence "
            "blocker",
            "therefore the current scripts/issue117_arm_c_direct.py is "
            "NOT the direct driver frozen by "
            "pre_execution_inferwarm_sha; armc-direct-9's replay-prefill "
            "comparator is a post-stop revised diagnostic invocation, "
            "not the frozen comparator",
            "the reducer (scripts/issue117_arm_c_evidence.py) was "
            "similarly modified after observation (fail-closed invalid-"
            "attempt rule weakened to a review list; /srv/models/ "
            "tokenizer-metadata exemption added); the blocker reducer "
            "restores fail-closed semantics bound to the pre-execution "
            "methodology",
        ],
        "comparator_modification_forensics": {
            "direct6_completed_utc": "2026-09-09T10:28:36.248255+00:00",
            "staged_driver_mtime_utc": STAGED_DRIVER_MTIME_UTC,
            "direct7_first_observed_utc":
                "2026-09-09T10:49:28.249147+00:00",
            "source": (
                "retained completion evidence "
                "(invalid-attempt-6/direct-run.json completed_at_ns), "
                "the host-observed staged-driver stat recorded during "
                "the /2 correction pass, and the retained "
                "execution-session transcript first observation of the "
                "armc-direct-7 launch"),
        },
        "post_audit_correction_allowlist": {},  # filled by caller
        "execution_code_identity_disclosure": {
            "armc-direct-1..armc-direct-6": {
                "driver_bytes": "unknown / not retained",
                "explanation": (
                    "the direct driver executed from a staged copy at "
                    "/srv/inferswarm/state/arm-c/scripts/"
                    "issue117_arm_c_direct.py on inferswarm01 which was "
                    "modified in place during the campaign; its current "
                    "bytes (sha256 c0f03ef5…, mtime 2026-09-09T10:43:04Z) "
                    "postdate armc-direct-6, and no copy of the "
                    "direct-6-era bytes was retained; the earliest "
                    "staged-copy mtime observable is 2026-09-09T03:45Z "
                    "(setup), so the exact driver identity used by "
                    "direct-1..6 cannot be recovered — this is part of "
                    "the evidence blocker"),
            },
            "armc-direct-7..armc-direct-9": {
                "driver_sha256": STAGED_DRIVER_SHA256,
                "evidence": ("staged-copy bytes on inferswarm01 equal the "
                             "driver first committed at dd4154d "
                             "(replay-prefill revision); staged mtime "
                             "2026-09-09T10:43:04Z precedes the "
                             "direct-7/8/9 launches"),
            },
            "armc-ordinary-1": {
                "coordinator_producer": ("924cd22ea081f6d4ed471016faf01d4"
                                         "27fc5b0d2 (clean worktree on "
                                         "inferswarm00, /srv/inferswarm/"
                                         "repos/FreeToken)"),
                "participant_producers": ("924cd22e… clean on "
                                          "inferswarm01 and inferswarm03 "
                                          "(/home/zutfen/FreeToken)"),
                "client": ("scripts/issue117_arm_c_client.py @ 5e2c83a "
                           "(unchanged since freeze; sha256 "
                           "17d2896385e939cb7ef5381a5d5093a743f40ef95c"
                           "e4efdd10fb0bc1db6a2b98)"),
            },
        },
    }
    return audit


def build_lineage(transcript: dict, lss_utc: str) -> dict:
    cb = json.loads((ARM_C / "invalid-attempt-6/direct-run.json").read_text())
    direct6_done = utc(cb["completed_at_ns"] / 1e9)
    d9 = json.loads((ARM_C / "direct-run.json").read_text())
    direct9_done = utc(d9["completed_at_ns"] / 1e9)
    ordinary = json.loads((ARM_C / "ordinary-campaign.json").read_text())
    ordinary_done = utc(ordinary["completed_at_ns"] / 1e9)
    unknown = "unknown / not retained"

    def attempt(aid: str, order: int, hosts: list[str], phase: str,
                failure: str | None, realization: bool, gpu: bool,
                cb_emitted: bool, reached_coord: bool, commit: bool,
                cleanup: str, evidence: dict, first_observed: str,
                code_identity: dict, valid: bool,
                classification: str,
                historical_validity: str | None = None) -> dict:
        stamps = {"transcript_first_observed_utc": first_observed}
        completion = evidence.get("completed_utc_from_evidence")
        if completion:
            stamps["completion_evidence_utc"] = completion
        entry = {
            "attempt_id": aid, "order": order, "hosts": hosts,
            "phase_reached": phase, "failure": failure,
            "realization_request_made": realization,
            "gpu_residency_achieved": gpu,
            "correctness_bearing_result_emitted": cb_emitted,
            "result_reached_coordinator": reached_coord,
            "coordinator_commit_occurred": commit,
            "accepted_arm_b_state_changed": False,
            "cleanup_containment": cleanup,
            "observed_timestamps": stamps,
            "code_identity": code_identity,
            "evidence_bindings": evidence,
            "retained_validity_flag": valid,
            "campaign_classification": classification,
        }
        if historical_validity is not None:
            entry["historical_validity_classification"] = (
                historical_validity)
        return entry

    staged = {
        "inferswarm_inferwarm_worktree_sha": unknown,
        "worktree_note": ("no commit was made on "
                          "issue-117-arm-c-ordinary-serving between the "
                          "freeze 5e2c83a and the campaign commit "
                          "dd4154d; the working tree during the campaign "
                          "carried uncommitted modifications (disclosed "
                          "in pre-execution-authority-audit.json)"),
        "freetoken_producer": "924cd22ea081f6d4ed471016faf01d427fc5b0d2",
    }
    staged_late = dict(staged)
    staged_late["driver_sha256"] = STAGED_DRIVER_SHA256
    driver_unknown = dict(staged)
    driver_unknown["driver_bytes"] = unknown

    attempts = [
        attempt("armc-lss-1", 1, ["inferswarm03"],
                "last-stage startup (plan file not yet staged)",
                "FileNotFoundError participant-plan", False, False,
                False, False, False, "process exited; restarted",
                {"transcript": SESSION_ID}, lss_utc, staged,
                False, "pre-stop infrastructure (non-correctness-bearing)"),
        attempt("armc-direct-1", 2, ["inferswarm01"],
                "git verification",
                "repo path inferred from scripts dir (not a git repo)",
                False, False, False, False, False, "none needed",
                {"transcript": SESSION_ID},
                transcript.get("armc-direct-1", unknown), driver_unknown,
                False, "pre-stop infrastructure (non-correctness-bearing)"),
        attempt("armc-direct-2", 3, ["inferswarm01"],
                "git verification (same path defect)",
                "CalledProcessError git rev-parse", False, False,
                False, False, False, "--repo flag added",
                {"transcript": SESSION_ID},
                transcript.get("armc-direct-2", unknown), driver_unknown,
                False, "pre-stop infrastructure (non-correctness-bearing)"),
        attempt("armc-direct-3", 4, ["inferswarm01", "inferswarm03"],
                "chain construction",
                "KeyError participants (execution-plan body incomplete)",
                False, True, False, False, False,
                "stage processes killed; GPUs cleared",
                {"transcript": SESSION_ID, "strace_window": (
                    "the retained direct.strace.gz (mtime 2026-09-09"
                    "T08:16:38Z) covers this era of direct-window "
                    "attempts; window-attribution to a single attempt "
                    "is not recoverable from retained bytes")},
                transcript.get("armc-direct-3", unknown), driver_unknown,
                False, "pre-stop infrastructure (non-correctness-bearing)"),
        attempt("armc-direct-4", 5, ["inferswarm01", "inferswarm03"],
                "last-stage connect",
                "ConnectionRefused (service had exited after prior "
                "disconnect)", False, False, False, False, False,
                "service restarted", {"transcript": SESSION_ID},
                transcript.get("armc-direct-4", unknown), driver_unknown,
                False, "pre-stop infrastructure (non-correctness-bearing)"),
        attempt("armc-direct-5", 6, ["inferswarm01", "inferswarm03"],
                "first prefill",
                "r4 wire 30s timeout (cold page cache + JIT under "
                "strace, run as root)", True, True, False, False, False,
                "processes killed; switched to zutfen user with warm "
                "caches", {"transcript": SESSION_ID},
                transcript.get("armc-direct-5", unknown), driver_unknown,
                False, "pre-stop infrastructure (non-correctness-bearing)"),
        attempt("armc-direct-6", 7, ["inferswarm01", "inferswarm03"],
                "completed 24 cases (invocation consistent with the "
                "frozen single-shot max_new_tokens=8 comparator; exact "
                "staged driver bytes unknown / not retained)",
                "INVALID COMPARATOR (historical/post-hoc classification, "
                "authored after the observation): single-shot "
                "max_new_tokens=8 incremental decode (documented "
                "anomalous KV-append path); the mechanically derived "
                "defect is in the frozen comparator's design, not in "
                "this attempt's use of the invocation the methodology "
                "prescribed",
                True, True, True, False, False,
                "retained under invalid-attempt-6/; part of the "
                "evidence that exposes the frozen comparator defect; "
                "NOT accepted terminal comparator evidence",
                {"results": "invalid-attempt-6/direct-run.json",
                 "execution_plan": "invalid-attempt-6/execution-plan.json",
                 "planner_ranking_record_derived": (
                     "coordinator-report.json (the ordinary arm's "
                     "planner record cites attempt_id armc-direct-6)"),
                 "transcript": SESSION_ID,
                 "completed_utc_from_evidence": direct6_done},
                transcript.get("armc-direct-6", unknown), driver_unknown,
                False,
                "correctness-bearing physical observation; invocation "
                "consistent with the frozen single-shot comparator; "
                "exact staged driver bytes unknown / not retained; "
                "part of the evidence that exposes the frozen "
                "comparator defect (the arms differed in runtime "
                "invocation semantics by frozen design); NOT accepted "
                "terminal comparator evidence",
                historical_validity=(
                    "invalid (authored post-hoc classification retained "
                    "verbatim; the exact moment of the operator's "
                    "invalid-comparator judgment is not independently "
                    "retained — see the blocker reducer's branch "
                    "analysis)"),
        ),
        attempt("armc-ordinary-1", 8,
                ["inferswarm00", "inferswarm01", "inferswarm03"],
                "24 cases + fencing request through the ordinary path "
                "(its planner consumed a ranking record measured by "
                "armc-direct-6; retained completion evidence places it "
                "at 10:38 UTC, after direct-6 at 10:28 UTC and before "
                "the replay-prefill rewrite reached a completed direct "
                "run)",
                None, True, True, True, True, True,
                "coordinator/agent/service stopped gracefully",
                {"records": "ordinary-campaign.json",
                 "per_case_http": "ordinary-http/",
                 "coordinator_report": "coordinator-report.json",
                 "fencing": "fencing-arm.json",
                 "completed_utc_from_evidence": ordinary_done},
                transcript.get("armc-ordinary-1", unknown),
                {"coordinator_producer": ("924cd22ea081f6d4ed4710"
                                          "16faf01d427fc5b0d2 (clean)"),
                 "inferswarm_inferwarm_worktree_sha": unknown},
                True,
                "correctness-bearing ordinary-path observation; part of "
                "the frozen-methodology campaign evidence; inadmissible "
                "to a semantic PASS/FAIL because the comparator "
                "methodology was defective",
                historical_validity=(
                    "valid (authored classification retained verbatim; "
                    "the §10 stop-rule consequence of the historical "
                    "direct-6 validity question is analyzed, not "
                    "resolved, by the blocker reducer)"),
        ),
        attempt("armc-direct-7", 9, ["inferswarm01", "inferswarm03"],
                "output write",
                "PermissionError (root-owned out dir)", False, False,
                False, False, False, "ownership fixed",
                {"transcript": SESSION_ID},
                transcript.get("armc-direct-7", unknown), staged_late,
                False,
                "post-observation/post-methodology-revision diagnostic "
                "(timestamp evidence places it at 10:49 UTC, after the "
                "staged-driver overwrite at 10:43 UTC); inadmissible "
                "to the terminal campaign"),
        attempt("armc-direct-8", 10, ["inferswarm01", "inferswarm03"],
                "first replay prefill",
                "r4 wire 30s timeout (page cache evicted; 9.29GB cold "
                "shard read)", True, True, False, False, False,
                "processes killed; page-cache warm reads issued "
                "(read-only cat > /dev/null)", {"transcript": SESSION_ID},
                transcript.get("armc-direct-8", unknown), staged_late,
                False,
                "post-observation/post-methodology-revision diagnostic; "
                "inadmissible to the terminal campaign"),
        attempt("armc-direct-9", 11, ["inferswarm01", "inferswarm03"],
                "completed 24 cases (per-token replay-prefill "
                "comparator — POST-FREEZE, POST-OBSERVATION revised "
                "diagnostic invocation; NOT the comparator frozen at "
                "5e2c83a)",
                None, True, True, True, False, False,
                "retained as diagnostic comparison side",
                {"results": "direct-run.json (= direct/direct-run.json)",
                 "execution_plan": "direct/execution-plan.json",
                 "completed_utc_from_evidence": direct9_done},
                transcript.get("armc-direct-9", unknown), staged_late,
                True,
                "post-observation/post-methodology-revision diagnostic "
                "(replay-prefill side of the retained 18/24 comparison); "
                "inadmissible to the terminal campaign"),
    ]
    return {
        "schema": "inferswarm.issue117.arm-c.attempt-lineage/3",
        "supersedes": (
            "inferswarm.issue117.arm-c.attempt-lineage/2 (all retained "
            "fields preserved; /3 corrects the campaign classifications "
            "to the mechanically derived disposition, separates "
            "physical chronology from the authored logical order, and "
            "retains the previously authored validity flags verbatim "
            "under historical_validity_classification; no attempt "
            "added or removed)"),
        "chronology_note": (
            "physical chronology is derived only from retained "
            "completion-evidence and transcript timestamps "
            "(direct-6 10:28:36Z < ordinary-1 10:38:52Z < direct-7 "
            "10:49:28Z < direct-8 10:56:57Z < direct-9 11:09:05Z); the "
            "logical 'order' field is an authored narrative ordering, "
            "retained separately and never used as physical "
            "chronology where timestamp evidence exists"),
        "execution_session": {
            "session_id": SESSION_ID,
            "started_utc": utc(1788929244.675144),
            "ended_utc": utc(1788958324.979750),
            "transcript_census_chain_sha256": None,  # filled by caller
            "note": "retained Hermes session database (read-only)",
        },
        "attempts": attempts,
    }


def source_read_accounting() -> dict:
    """Classify every retained /srv/models/ open in the serving windows
    under the FROZEN zero-Source rule (methodology §9: no open of any
    path under /srv/models/ — no tokenizer-metadata exemption existed
    at the freeze)."""
    audit_json = json.loads((ARM_C / "strace-audit.json").read_text())
    metadata_suffixes = (
        "/config.json", "/chat_template.jinja", "/tokenizer.json",
        "/tokenizer_config.json", "/generation_config.json",
        "/processor_config.json", "/preprocessor_config.json",
    )
    file_metadata, dir_stats, weight = [], [], []
    for label, window in audit_json.get("windows", {}).items():
        for path in window.get("paths", []):
            if "/srv/models/" not in path:
                continue
            if path.endswith(metadata_suffixes):
                file_metadata.append(f"{label}:{path}")
            elif path.rstrip("/").endswith("/gemma-r6"):
                dir_stats.append(f"{label}:{path}")
            else:
                weight.append(f"{label}:{path}")
    return {
        "frozen_rule": ("METHODOLOGY-ARM-C §9 @ 5e2c83a: the retained "
                        "trace must show no open of any path under "
                        "/srv/models/ — no exemption existed at the "
                        "freeze; tokenizer metadata reads are counted "
                        "toward participant_source_tree_reads and are "
                        "separately disclosed, never zeroed"),
        "total_opens_counted": len(file_metadata) + len(dir_stats)
                               + len(weight),
        "tokenizer_metadata_file_reads": len(file_metadata),
        "source_root_directory_stats": len(dir_stats),
        "model_weight_file_reads": len(weight),
        "observed_paths": {
            "tokenizer_metadata_files": sorted(file_metadata),
            "directory_stats": sorted(dir_stats),
            "model_weight_files": sorted(weight),
        },
        "historical_classification": (
            "the four tokenizer-metadata file opens violate the frozen "
            "zero-Source rule for this campaign; they are retained, "
            "counted, and disclosed — a future methodology may pre-"
            "declare an immutable-tokenizer-metadata exception, but only "
            "if frozen BEFORE a new correctness-bearing campaign; it "
            "cannot be backported to this one"),
    }


def main() -> int:
    head = git(["rev-parse", "HEAD"])
    audit = build_authority_audit(head)
    audit["source_read_accounting_frozen_rule"] = source_read_accounting()
    transcript, lss_utc, chain = transcript_launch_observations()
    lineage = build_lineage(transcript, lss_utc)
    lineage["execution_session"]["transcript_census_chain_sha256"] = chain
    # FAIL-CLOSED post-audit correction allowlist: every file that
    # differs between the audited head (head_classified = the reviewed
    # base this correction builds on) and the FINAL correction commit
    # must be listed here with its exact final sha256. The correction
    # commit does not exist yet at build time, so the working tree
    # bytes ARE the final bytes: re-run this builder after staging the
    # correction (before committing) so the allowlist pins exactly the
    # committed content. The frozen methodology/driver are never
    # allowable (enforced by the blocker reducer, not just here).
    audit["post_audit_correction_allowlist"] = {
        str(path): {
            "role": role,
            "sha256": hashlib.sha256(
                (ROOT / path).read_bytes()).hexdigest(),
        }
        for path, role in (
            ("scripts/issue117_arm_c_blocker_reducer.py",
             "correction /2 blocker reducer (this pass)"),
            ("scripts/issue117_arm_c_frozen_pins.py",
             "correction /2 frozen FreeToken invocation-semantics "
             "derivation (new)"),
            ("scripts/issue117_arm_c_blocker_fakeroot.py",
             "correction /2 blocker mutation-suite fakeroot"),
            ("tests/test_issue117_arm_c_blocker.py",
             "correction /2 blocker mutation suite"),
            ("scripts/issue117_arm_c_authority_audit.py",
             "correction /2 authority-audit/lineage builder (this "
             "file; self-pinned role only — the audit document's own "
             "integrity is bound by the retention MANIFEST row)"),
            ("docs/implementation/r6-successor-dense-full-"
             "integration-117/evidence/arm-c/attempt-lineage.json",
             "retained lineage, schema /3 (rebuilt by this builder)"),
            ("docs/implementation/r6-successor-dense-full-"
             "integration-117/evidence/arm-c/pre-execution-"
             "authority-audit.json",
             "retained authority audit, schema /2 (self-referential; "
             "MANIFEST-bound)"),
            ("docs/implementation/r6-successor-dense-full-"
             "integration-117/evidence/arm-c/blocker-reduction.json",
             "retained blocker reduction record, schema /2 (regenerated "
             "by the corrected reducer)"),
            ("scripts/issue117_proof.py",
             "correction /2: PRODUCERS list gains the frozen-pins "
             "module (manifest/producer-hash coverage)"),
            ("docs/project-status.json",
             "correction /2: Arm-C constraint rewritten to the "
             "comparator-semantics derivation"),
            # sync --write living sections + refreshed live manifest
            # rows (derived maintenance, verified by sync --check)
            ("README.md", "derived: sync living section (frontier)"),
            ("ROADMAP.md", "derived: sync living section (frontier)"),
            ("ARCHITECTURE.md", "derived: sync living section (frontier)"),
            ("docs/implementation/README.md",
             "derived: sync living section (frontier)"),
            ("docs/integrations/freetoken.md",
             "derived: sync living sections (frontier, runtime)"),
            ("docs/protocols/README.md",
             "derived: sync living section (frontier)"),
            ("docs/qualification/gemma4-12b-it-v1/MANIFEST.sha256",
             "derived: sync live manifest row"),
            ("docs/implementation/plan-driven-artifact-acquisition-99/"
             "evidence/MANIFEST.sha256",
             "derived: sync live manifest row"),
            ("docs/implementation/r6-successor-dense-full-"
             "integration-117/README.md",
             "correction /2: Arm-C section rewritten to the "
             "comparator-semantics derivation (MANIFEST-row bound)"),
            # frozen FreeToken producer bytes retained verbatim
            # (correction /2); sha256-pinned by
            # scripts/issue117_arm_c_frozen_pins.py AND by the
            # retention MANIFEST — pinned here too so the exact-head
            # audit admitlists exactly these bytes
            ("docs/implementation/r6-successor-dense-full-"
             "integration-117/evidence/arm-c/frozen-freetoken/"
             "924cd22e/python/freetoken/research/r5b_epochs.py",
             "frozen FreeToken producer bytes @ 924cd22e (verbatim)"),
            ("docs/implementation/r6-successor-dense-full-"
             "integration-117/evidence/arm-c/frozen-freetoken/"
             "924cd22e/benchmarks/inferswarm_r6/coordinator.py",
             "frozen FreeToken producer bytes @ 924cd22e (verbatim)"),
            ("docs/implementation/r6-successor-dense-full-"
             "integration-117/evidence/arm-c/frozen-freetoken/"
             "924cd22e/benchmarks/inferswarm_r6/xc_strategy.py",
             "frozen FreeToken producer bytes @ 924cd22e (verbatim)"),
            # derived maintenance artifacts: pure functions of the
            # final tree, regenerated last; sha-pinning them is
            # circular (the manifest covers the audit itself), so
            # they are allowlisted as derived and their integrity is
            # enforced by the retention manifest suites (every row
            # verified against bytes) + sync --check
            ("docs/implementation/r6-successor-dense-full-"
             "integration-117/evidence/producer-hashes.json",
             "derived: producer hash ledger (regenerated last)"),
            ("docs/implementation/r6-successor-dense-full-"
             "integration-117/evidence/MANIFEST.sha256",
             "derived: retention manifest (regenerated last)"),
        )
    }
    for entry in audit["post_audit_correction_allowlist"].values():
        if entry["role"].startswith("derived:"):
            entry["derived"] = True
    # the two evidence documents the builder itself writes cannot be
    # pre-pinned by content (they are being written now); mark them
    # self-referential so the reducer binds them via the MANIFEST row
    for rel in (
        "docs/implementation/r6-successor-dense-full-integration-117/"
        "evidence/arm-c/attempt-lineage.json",
        "docs/implementation/r6-successor-dense-full-integration-117/"
        "evidence/arm-c/pre-execution-authority-audit.json",
    ):
        audit["post_audit_correction_allowlist"][rel]["self"] = True
        audit["post_audit_correction_allowlist"][rel].pop("sha256", None)
    (ARM_C / "pre-execution-authority-audit.json").write_text(
        json.dumps(audit, indent=2, sort_keys=True) + "\n")
    (ARM_C / "attempt-lineage.json").write_text(
        json.dumps(lineage, indent=2, sort_keys=True) + "\n")
    print(json.dumps({
        "head": head,
        "audit": str(ARM_C / "pre-execution-authority-audit.json"),
        "lineage": str(ARM_C / "attempt-lineage.json"),
        "transcript_chain": chain,
        "first_observed": transcript,
        "allowlist": sorted(
            audit["post_audit_correction_allowlist"]),
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
