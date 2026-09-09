#!/usr/bin/env python3
"""Issue #117 Arm C — frozen-evidence blocker reducer (retention/
derivation only; CPU-only; no physical execution).

Re-derives the Arm-C terminal classification for the RETAINED 2026-09-09
campaign under the authority that was actually frozen before execution
(commit ``5e2c83a09031d68784c3098fc9dad319b684f0da`` =
``run-record.json:pre_execution_inferwarm_sha``), NOT under the
post-observation reducer/driver revisions committed at dd4154d.

Authority ladder (each step mechanically verified, never asserted):

  1. the claimed pre-execution SHA in run-record.json is 5e2c83a… and
     the retained methodology/driver/reducer digests at that SHA match
     the digests recorded in pre-execution-authority-audit.json;
  2. post-freeze deltas of the direct driver and the reducer are
     mechanically disclosed in the same audit (git blob-SHA + sha256
     classification of every 5e2c83a..head change);
  3. armc-direct-6 physically completed all 24 cases with GPU residency
     and emitted correctness-bearing results (its retained
     invalid-attempt-6/direct-run.json carries 24 result rows) using
     the frozen single-shot max_new_tokens=8 invocation (its result
     rows predate the replay-prefill revision and carry no
     ``invocation`` marker);
  4. direct-6 is retained INVALID in attempt-lineage.json → under
     METHODOLOGY-ARM-C §10 an invalid attempt with a correctness-bearing
     observation is NOT harmless: STOP for maintainer review. The stop
     boundary is therefore mechanically derived
     (``correctness_bearing_stop_trigger = true`` on armc-direct-6);
  5. later attempts (armc-direct-7/8/9, armc-ordinary-1) exist after
     the stop boundary → they are post-stop diagnostic evidence,
     retained but inadmissible to the Arm-C terminal serving claim;
  6. four tokenizer-metadata Source-tree opens occurred under the
     frozen zero-Source rule (methodology §9 had no exemption) → the
     campaign cannot be PASS;
  7. the frozen comparator (single-shot direct vs ordinary) never
     produced an admissible terminal comparison (its only execution is
     the INVALID direct-6; the 18/24 comparison used the post-stop
     replay-prefill direct-9) → the campaign cannot be a semantic
     ordinary-serving FAIL either;
  8. therefore the terminal is the Arm-C evidence/methodology blocker:
     ``ISSUE117_ARM_C_EVIDENCE_BLOCKER``, qualified as a
     post-correctness-bearing methodology / evidence-admissibility
     failure. A stored blocker string is never authority: the terminal
     is re-derived from the retained evidence on every run.

Fail-closed: any missing document, digest mismatch, erased attempt, or
mutated fact is a ReductionError → BLOCKED output with the reason.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AREA = ROOT / "docs/implementation/r6-successor-dense-full-integration-117"
ARM_C = AREA / "evidence/arm-c"

#: test seam: the mutation suite points the reducer's git identity
#: checks at a scratch git repository carrying the synthetic freeze.
import os  # noqa: E402
_REPO_OVERRIDE = os.environ.get("ARM_C_BLOCKER_REPO")
if _REPO_OVERRIDE:
    ROOT = Path(_REPO_OVERRIDE)
    AREA = ROOT / "docs/implementation/r6-successor-dense-full-integration-117"

FROZEN_INFERSWARM_SHA = os.environ.get(
    "ARM_C_BLOCKER_FREEZE_SHA",
    "5e2c83a09031d68784c3098fc9dad319b684f0da")
FROZEN_METHODOLOGY_PATH = (
    "docs/implementation/r6-successor-dense-full-integration-117/"
    "METHODOLOGY-ARM-C.md")
FROZEN_DIRECT_DRIVER_PATH = "scripts/issue117_arm_c_direct.py"
FROZEN_REDUCER_PATH = "scripts/issue117_arm_c_evidence.py"

PASS = "ISSUE117_ARM_C_ORDINARY_SERVING_PASS"
FAIL = "ISSUE117_ARM_C_ORDINARY_SERVING_FAIL"
BLOCKED = "ISSUE117_ARM_C_EVIDENCE_BLOCKER"
BLOCKER_QUALIFICATION = (
    "post-correctness-bearing methodology / evidence-admissibility "
    "failure")

STOP_TRIGGER_ATTEMPT = "armc-direct-6"
POST_STOP_ATTEMPTS = [
    "armc-direct-7", "armc-direct-8", "armc-direct-9", "armc-ordinary-1",
]
#: frozen §4 comparator contract: the single-shot invocation text that
#: MUST appear in the frozen methodology and be implemented by the
#: frozen driver.
FROZEN_COMPARATOR_TEXT = "max_new_tokens=8"
REPLAY_MARKER = "per-token-replay-prefill/1"

ARM_C_DEFAULT = ARM_C  # test injection seam via set_evidence_dir


class ReductionError(RuntimeError):
    """Fail-closed reduction error."""


def set_evidence_dir(path: Path) -> None:
    global ARM_C  # noqa: PLW0603 - test/builder injection seam
    ARM_C = Path(path)


def load(name: str) -> dict:
    path = ARM_C / name
    if not path.is_file():
        raise ReductionError(f"missing retained evidence: {name}")
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError as error:
        raise ReductionError(f"malformed evidence {name}: {error}") from error


def require(condition: object, message: str) -> None:
    if not condition:
        raise ReductionError(message)


def git_blob_sha(rev: str, path: str) -> str:
    try:
        return subprocess.check_output(
            ["git", "-c", f"safe.directory={ROOT}", "-C", str(ROOT),
             "rev-parse", f"{rev}:{path}"], text=True).strip()
    except subprocess.CalledProcessError as error:
        raise ReductionError(
            f"cannot resolve {path} at {rev}") from error


def git_show(rev: str, path: str) -> bytes:
    try:
        return subprocess.check_output(
            ["git", "-c", f"safe.directory={ROOT}", "-C", str(ROOT),
             "cat-file", "blob", f"{rev}:{path}"])
    except subprocess.CalledProcessError as error:
        raise ReductionError(
            f"cannot read {path} at {rev}") from error


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def verify_frozen_identities(head: str) -> dict:
    """Step 1-2: pin the pre-execution authority by git blob SHA and
    sha256, and require the audit's disclosure to match the same
    mechanical facts."""
    run_record = load("run-record.json")
    require(run_record.get("pre_execution_inferwarm_sha")
            == FROZEN_INFERSWARM_SHA,
            "run-record pre_execution_inferswarm_sha is not the claimed "
            f"{FROZEN_INFERSWARM_SHA}")
    audit = load("pre-execution-authority-audit.json")
    require(audit.get("claimed_pre_execution_inferswarm_sha")
            == FROZEN_INFERSWARM_SHA,
            "authority audit pre-execution SHA drift")
    frozen_files = audit.get("frozen_correctness_bearing_files", {})
    for path in (FROZEN_METHODOLOGY_PATH, FROZEN_DIRECT_DRIVER_PATH,
                 FROZEN_REDUCER_PATH):
        entry = frozen_files.get(path)
        require(entry is not None,
                f"authority audit does not bind frozen file {path}")
        assert entry is not None  # for the type checker; require() fails
        actual_blob = git_blob_sha(FROZEN_INFERSWARM_SHA, path)
        actual_sha = sha256_bytes(git_show(FROZEN_INFERSWARM_SHA, path))
        require(entry["git_blob_sha_at_freeze"] == actual_blob,
                f"{path}: audit freeze blob SHA does not match git")
        require(entry["sha256_at_freeze"] == actual_sha,
                f"{path}: audit freeze sha256 does not match git")
    # the frozen methodology freezes the single-shot comparator and the
    # frozen driver implements it
    methodology = git_show(FROZEN_INFERSWARM_SHA,
                           FROZEN_METHODOLOGY_PATH).decode()
    require("one `generate(session_id=i," in methodology,
            "frozen methodology does not freeze the single-shot "
            "comparator")
    require(FROZEN_COMPARATOR_TEXT in methodology,
            "frozen methodology lacks the max_new_tokens=8 comparator")
    driver = git_show(FROZEN_INFERSWARM_SHA,
                      FROZEN_DIRECT_DRIVER_PATH).decode()
    require("max_new_tokens=8" in driver,
            "frozen direct driver does not implement the frozen "
            "single-shot comparator")
    require("max_new_tokens=2" not in driver,
            "frozen direct driver unexpectedly implements replay "
            "prefill")
    # post-freeze deltas disclosed: the driver and reducer at head are
    # NOT the frozen bytes
    require(frozen_files[FROZEN_DIRECT_DRIVER_PATH]["status_at_head"]
            == "changed_after_freeze",
            "direct driver status at head not disclosed as changed")
    require(frozen_files[FROZEN_REDUCER_PATH]["status_at_head"]
            == "changed_after_freeze",
            "reducer status at head not disclosed as changed")
    disclosed = {c["path"] for c in audit.get("post_freeze_changes", [])}
    # The audit classifies changes up to the audited head (the reviewed
    # correction-pass base, recorded in the audit as head_classified).
    # The live head must be the audited head or a descendant; changes
    # introduced after the audited head must be disclosed too.
    audited_head = audit.get("head_classified")
    require(audited_head is not None,
            "authority audit does not record the classified head")
    assert audited_head is not None
    is_descendant = subprocess.run(
        ["git", "-c", f"safe.directory={ROOT}", "-C", str(ROOT),
         "merge-base", "--is-ancestor", audited_head, head],
        capture_output=True).returncode == 0
    require(is_descendant,
            f"live head {head} is not a descendant of the audited head "
            f"{audited_head}")
    name_status = subprocess.check_output(
        ["git", "-c", f"safe.directory={ROOT}", "-C", str(ROOT), "diff",
         "--name-only", f"{FROZEN_INFERSWARM_SHA}..{audited_head}"],
        text=True).strip().splitlines()
    require(set(name_status) == disclosed,
            "post-freeze change classification is incomplete: "
            f"{sorted(set(name_status) ^ disclosed)[:5]}")
    if head != audited_head:
        # the audited window is immutable history; a later head is fine
        # (this correction's own commit) but the correctness-bearing
        # frozen files must not change after the audited head without a
        # fresh authority audit
        later = subprocess.check_output(
            ["git", "-c", f"safe.directory={ROOT}", "-C", str(ROOT),
             "diff", "--name-only", f"{audited_head}..{head}"],
            text=True).strip().splitlines()
        frozen_changed = [p for p in later if p in (
            FROZEN_METHODOLOGY_PATH, FROZEN_DIRECT_DRIVER_PATH,
            FROZEN_REDUCER_PATH)]
        require(
            not frozen_changed or FROZEN_REDUCER_PATH in frozen_changed,
            "frozen methodology/driver changed after the audited head "
            f"without a fresh authority audit: {frozen_changed}")
    return {
        "pre_execution_inferwarm_sha": FROZEN_INFERSWARM_SHA,
        "frozen_methodology": {
            "git_blob_sha": frozen_files[FROZEN_METHODOLOGY_PATH][
                "git_blob_sha_at_freeze"],
            "sha256": frozen_files[FROZEN_METHODOLOGY_PATH][
                "sha256_at_freeze"],
        },
        "frozen_direct_driver": {
            "git_blob_sha": frozen_files[FROZEN_DIRECT_DRIVER_PATH][
                "git_blob_sha_at_freeze"],
            "sha256": frozen_files[FROZEN_DIRECT_DRIVER_PATH][
                "sha256_at_freeze"],
        },
        "frozen_reducer": {
            "git_blob_sha": frozen_files[FROZEN_REDUCER_PATH][
                "git_blob_sha_at_freeze"],
            "sha256": frozen_files[FROZEN_REDUCER_PATH][
                "sha256_at_freeze"],
        },
        "post_freeze_change_count": len(disclosed),
        "driver_changed_after_freeze": True,
        "reducer_changed_after_freeze": True,
        "disclosure": ("the direct driver and the reducer committed at "
                       "the final head are NOT the scripts frozen by "
                       "pre_execution_inferwarm_sha; every post-freeze "
                       "change is classified in "
                       "pre-execution-authority-audit.json"),
    }


def derive_stop_boundary(lineage: dict) -> dict:
    """Steps 3-5: derive the correctness-bearing stop boundary from the
    retained lineage and evidence bytes."""
    require(lineage.get("schema")
            == "inferswarm.issue117.arm-c.attempt-lineage/2",
            "attempt lineage is not the recovered /2 schema")
    attempts = {a["attempt_id"]: a for a in lineage.get("attempts", [])}
    require(len(attempts) == len(lineage.get("attempts", [])),
            "duplicate attempt ids in lineage")
    trigger = attempts.get(STOP_TRIGGER_ATTEMPT)
    require(trigger is not None,
            f"{STOP_TRIGGER_ATTEMPT} erased from lineage")
    require(trigger.get("correctness_bearing_result_emitted") is True,
            f"{STOP_TRIGGER_ATTEMPT} correctness-bearing flag missing/")
    require(trigger.get("gpu_residency_achieved") is True,
            f"{STOP_TRIGGER_ATTEMPT} GPU residency flag missing")
    require(trigger.get("retained_validity_flag") is False,
            f"{STOP_TRIGGER_ATTEMPT} is not retained invalid")
    # the retained invalid-attempt-6 results really carry 24 cases
    inv6 = load("invalid-attempt-6/direct-run.json")
    require(inv6.get("attempt_id") == STOP_TRIGGER_ATTEMPT,
            "invalid-attempt-6/direct-run.json attempt id drift")
    require(inv6.get("case_count") == 24
            and len(inv6.get("results", [])) == 24,
            "invalid-attempt-6 results do not carry 24 cases")
    # and they used the FROZEN single-shot invocation: result rows
    # carry NO replay-prefill marker (the marker was introduced by the
    # post-freeze driver revision)
    for row in inv6["results"]:
        require(row.get("invocation") != REPLAY_MARKER,
                "invalid-attempt-6 rows unexpectedly carry the "
                "replay-prefill marker")
    # post-stop attempts retained and classified
    for attempt_id in POST_STOP_ATTEMPTS:
        entry = attempts.get(attempt_id)
        require(entry is not None, f"post-stop attempt {attempt_id} "
                "erased from lineage")
        classification = entry.get("campaign_classification", "")
        require("post-stop diagnostic" in classification,
                f"{attempt_id} not classified as post-stop diagnostic")
    # ordering: every post-stop attempt is ordered after the trigger
    for attempt_id in POST_STOP_ATTEMPTS:
        require(attempts[attempt_id]["order"] > trigger["order"],
                f"{attempt_id} is not ordered after the stop trigger")
    # the trigger classification itself
    require("correctness_bearing_stop_trigger" in trigger.get(
        "campaign_classification", ""),
        "stop-trigger classification missing on armc-direct-6")
    # the retained 18/24 comparison used the post-stop direct-9 side
    direct9 = load("direct-run.json")
    require(direct9.get("attempt_id") == "armc-direct-9",
            "direct-run.json is not the direct-9 side")
    marked = sum(1 for r in direct9.get("results", [])
                 if r.get("invocation") == REPLAY_MARKER)
    require(marked == 24,
            "retained direct-run.json is not the replay-prefill "
            "(direct-9) side")
    return {
        "stop_trigger_attempt": STOP_TRIGGER_ATTEMPT,
        "correctness_bearing_stop_trigger": True,
        "derivation": (
            "armc-direct-6 physically completed 24 cases with GPU "
            "residency and emitted correctness-bearing results using "
            "the frozen single-shot max_new_tokens=8 invocation, and is "
            "retained invalid → METHODOLOGY-ARM-C §10: STOP for "
            "maintainer review"),
        "post_stop_diagnostic_attempts": list(POST_STOP_ATTEMPTS),
        "post_stop_attempts_retained": True,
        "post_stop_attempts_admissible_to_terminal": False,
        "direct9_is_frozen_comparator": False,
        "direct9_note": ("armc-direct-9 used the post-freeze, post-stop "
                         "replay-prefill invocation (its result rows "
                         "carry per-token-replay-prefill/1); it is a "
                         "revised diagnostic invocation, not the "
                         "comparator frozen at 5e2c83a"),
    }


def derive_source_read_violation() -> dict:
    """Step 6: the four tokenizer-metadata Source opens under the
    frozen zero-Source rule (no exemption at the freeze)."""
    audit = load("pre-execution-authority-audit.json")
    accounting = audit.get("source_read_accounting_frozen_rule", {})
    require(accounting.get("model_weight_file_reads") == 0,
            "Source model-weight reads present — reclassify before "
            "using this reducer")
    metadata = accounting.get("tokenizer_metadata_file_reads")
    require(isinstance(metadata, int),
            "tokenizer metadata read count missing from the audit")
    require(metadata == 4,
            "tokenizer metadata read count is not the retained four")
    # cross-check against the raw retained strace audit paths
    strace = load("strace-audit.json")
    seen = 0
    for window in strace.get("windows", {}).values():
        for path in window.get("paths", []):
            if "/srv/models/" in path and path.endswith((
                    "/config.json", "/chat_template.jinja",
                    "/tokenizer.json", "/tokenizer_config.json",
                    "/generation_config.json", "/processor_config.json",
                    "/preprocessor_config.json")):
                seen += 1
    require(seen == metadata,
            "audit metadata-read count disagrees with the retained "
            f"strace paths ({seen} != {metadata})")
    return {
        "frozen_rule": "zero /srv/models/ opens in the serving windows",
        "tokenizer_metadata_file_reads": metadata,
        "model_weight_file_reads": 0,
        "participant_source_tree_reads_under_frozen_rule": metadata,
        "classification": (
            "the four tokenizer-metadata opens are retained and counted "
            "under the frozen rule (no post-hoc exemption); they "
            "contribute to the evidence blocker and independently bar "
            "PASS"),
    }


def reduce_all() -> dict:
    head = subprocess.check_output(
        ["git", "-c", f"safe.directory={ROOT}", "-C", str(ROOT),
         "rev-parse", "HEAD"], text=True).strip()
    authority = verify_frozen_identities(head)
    lineage = load("attempt-lineage.json")
    stop = derive_stop_boundary(lineage)
    source_reads = derive_source_read_violation()

    # terminal derivation (never from a stored string):
    #  - PASS is impossible: post-correctness-bearing methodology/
    #    evidence-admissibility failure (stop boundary + frozen-rule
    #    Source reads) — admissible terminal evidence does not exist;
    #  - semantic ordinary-serving FAIL is impossible: the mandatory
    #    stop precedes every retained direct/ordinary comparison; the
    #    18/24 equality used the post-stop replay-prefill comparator;
    #  - blocker is the narrowest defensible terminal.
    terminal = BLOCKED
    return {
        "schema": "inferswarm.issue117.arm-c.blocker-reduction/1",
        "head": head,
        "terminal": terminal,
        "terminal_qualification": BLOCKER_QUALIFICATION,
        "authority": authority,
        "stop_boundary": stop,
        "source_reads_frozen_rule": source_reads,
        "terminal_derivation": [
            "claimed pre-execution SHA verified: 5e2c83a…",
            "frozen methodology/driver/reducer digests pinned by git "
            "blob SHA + sha256",
            "post-freeze driver/reducer deltas mechanically disclosed",
            "armc-direct-6 emitted correctness-bearing results "
            "(24-case retained run), GPU-resident, frozen single-shot "
            "invocation",
            "armc-direct-6 is retained invalid → mandatory STOP",
            "armc-direct-7/8/9 and armc-ordinary-1 exist after the "
            "stop → diagnostic only, inadmissible as terminal evidence",
            "four tokenizer-metadata Source opens occurred under the "
            "frozen zero-Source rule → terminal cannot be PASS",
            "no admissible frozen-comparator vs ordinary comparison "
            "exists → terminal cannot be semantic ordinary-serving FAIL",
            "terminal is the Arm-C evidence/methodology blocker "
            "(post-correctness-bearing methodology / "
            "evidence-admissibility failure)",
        ],
        "retained_diagnostic_value": {
            "equality_18_of_24": ("retained as diagnostic evidence "
                                  "(post-stop, replay-prefill "
                                  "comparator); it does NOT establish "
                                  "the terminal Arm-C ordinary-serving "
                                  "result"),
            "six_regime_4_divergences": (
                "retained as diagnostic evidence; they strongly suggest "
                "a real multi-chunk/KV nondeterminism defect, which is "
                "a FOLLOW-UP HYPOTHESIS, not the accepted result of "
                "this campaign"),
        },
        "arm_d": "blocked",
    }


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true",
                        help="write the derived blocker record")
    args = parser.parse_args()
    try:
        result = reduce_all()
    except ReductionError as error:
        print(json.dumps({"terminal": BLOCKED,
                          "terminal_qualification": BLOCKER_QUALIFICATION,
                          "reason": str(error)}, indent=2))
        return 1
    if args.write:
        (ARM_C / "blocker-reduction.json").write_text(json.dumps(
            result, indent=2, sort_keys=True) + "\n")
    print(json.dumps({
        "terminal": result["terminal"],
        "terminal_qualification": result["terminal_qualification"],
        "head": result["head"],
        "stop_trigger": result["stop_boundary"]["stop_trigger_attempt"],
        "post_stop_diagnostic_attempts":
            result["stop_boundary"]["post_stop_diagnostic_attempts"],
        "tokenizer_metadata_source_reads":
            result["source_reads_frozen_rule"][
                "tokenizer_metadata_file_reads"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
