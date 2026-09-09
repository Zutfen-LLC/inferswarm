#!/usr/bin/env python3
"""Issue #117 Arm C — frozen-evidence blocker reducer, correction /2
(retention/derivation only; CPU-only; no physical execution).

Re-derives the Arm-C terminal classification for the RETAINED 2026-09-09
campaign under the authority that was actually frozen before execution
(commit ``5e2c83a09031d68784c3098fc9dad319b684f0da`` =
``run-record.json:pre_execution_inferwarm_sha``).

Correction /2 replaces the previous post-hoc derivation (which
classified armc-direct-6 as an invalid comparator merely because it used
the frozen single-shot ``max_new_tokens=8`` invocation) with the actual
frozen-methodology defect, derived mechanically:

  The frozen Arm-C methodology failed its own comparator-isolation
  requirement. The direct arm and the ordinary arm differed in runtime
  invocation semantics in addition to differing in control-plane
  routing. Therefore the frozen campaign could not establish
  ordinary-vs-direct serving equivalence or semantic failure as
  designed.

Authority ladder (each step mechanically verified, never asserted):

  1. the claimed pre-execution SHA in run-record.json is 5e2c83a… and
     the retained methodology/driver/reducer digests at that SHA match
     the digests recorded in pre-execution-authority-audit.json;
  2. post-freeze deltas of the direct driver and the reducer are
     mechanically disclosed in the same audit, and the exact-head
     audit is FAIL-CLOSED: no frozen methodology/driver change after
     the audited head is ever admissible, and every other file that
     changed after the audited head must carry an explicit,
     individually pinned entry in the audit's correction allowlist
     (exact sha256), else the reduction fails;
  3. the frozen direct comparator semantics are single-shot: the
     methodology (§4, frozen bytes from git) defines one
     ``generate(session_id=i, prompt_token_ids=<rendered ids>,
     max_new_tokens=8)`` per case and the frozen driver implements
     exactly that — that invocation is what the methodology told the
     direct arm to use;
  4. the frozen ordinary-path semantics are derived from the retained,
     sha256-pinned FreeToken producer bytes at 924cd22e
     (``issue117_arm_c_frozen_pins.derive_invocation_semantics``):
     ``EpochServingController.serve_tokens`` loops per committed
     position, re-derives the full replay prefix (prompt + committed
     tokens) through ``GemmaTokenBoundaryStrategy.replay_input``,
     invokes the runtime with ``max_new_tokens=2``, commits only
     step/token zero, discards the speculative second token, and
     repeats — and the ordinary HTTP Coordinator dispatches every
     /v1/chat/completions request through exactly this call;
  5. therefore the frozen comparator violates its own frozen
     "The ONLY intended difference is the control-plane path"
     requirement (methodology §4): the arms differed in runtime
     invocation semantics (single-shot vs replay-prefix per-position)
     as designed at the freeze — a methodology defect that existed
     before any execution;
  6. armc-direct-6 is a correctness-bearing physical observation (24
     retained result rows, GPU residency) whose invocation is
     consistent with the frozen single-shot comparator and whose exact
     staged driver bytes are ``unknown / not retained`` (the staged
     driver was overwritten in place at 2026-09-09T10:43:07Z, after
     direct-6 completed at 10:28:36Z and before direct-7 was observed
     at 10:49:28Z — mechanically checked against the audit's
     comparator-modification forensics);
  7. the exact historical moment at which the operator first regarded
     direct-6 as an invalid comparator is NOT independently retained.
     Both exhaustive possibilities are derived mechanically and BOTH
     converge on the blocker:
       Branch A — direct-6 was regarded as valid when ordinary-1 ran:
       the campaign followed the frozen methodology, but the frozen
       comparator itself was defective (step 5) → blocker.
       Branch B — direct-6 had already been regarded as invalid before
       ordinary-1 ran: frozen methodology §10 required STOP for
       maintainer review after direct-6's correctness-bearing output
       (retained timestamps place direct-6 at 10:28 UTC before
       ordinary-1 at 10:38 UTC), and ordinary-1 improperly ran
       afterward → blocker.
     The reducer never needs a post-hoc ``retained_validity_flag``
     judgment to obtain the terminal;
  8. armc-ordinary-1 is a correctness-bearing ordinary-path observation
     (24 cases + fencing, executed 10:38 UTC, before the replay-prefill
     rewrite reached a completed direct run), inadmissible to a
     semantic PASS/FAIL because the comparator methodology was
     defective; armc-direct-7/8/9 are post-observation,
     post-methodology-revision diagnostics (10:49/10:56/11:09 UTC),
     inadmissible to the terminal campaign; the retained 18/24 replay
     comparison (direct-9 side) remains diagnostic only;
  9. four tokenizer-metadata Source-tree opens and one Source-root
     directory stat occurred under the frozen zero-Source rule
     (methodology §9 had no exemption) → the campaign cannot be PASS;
 10. therefore: PASS impossible; semantic ordinary-serving FAIL
     inadmissible; terminal is the Arm-C evidence/methodology blocker:
     ``ISSUE117_ARM_C_EVIDENCE_BLOCKER``, qualified as a
     post-correctness-bearing methodology / evidence-admissibility
     failure. A stored blocker string is never authority: the terminal
     is re-derived from the retained evidence on every run.

Chronology is derived only from retained timestamp evidence
(per-attempt completion evidence and transcript observations); the
authored logical ``order`` field is retained separately and must not
contradict the timestamp-supported chronology (a contradiction fails
closed).

Fail-closed: any missing document, digest mismatch, erased attempt,
mutated fact, or allowlist violation is a ReductionError → BLOCKED
output with the reason.
"""
from __future__ import annotations

import datetime
import hashlib
import importlib.util
import json
import re
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
FROZEN_PINS_PATH = "scripts/issue117_arm_c_frozen_pins.py"
PRE_EXECUTION_AUDIT = "pre-execution-authority-audit.json"

PASS = "ISSUE117_ARM_C_ORDINARY_SERVING_PASS"
FAIL = "ISSUE117_ARM_C_ORDINARY_SERVING_FAIL"
BLOCKED = "ISSUE117_ARM_C_EVIDENCE_BLOCKER"
BLOCKER_QUALIFICATION = (
    "post-correctness-bearing methodology / evidence-admissibility "
    "failure")

UNKNOWN = "unknown / not retained"

#: frozen §4 comparator contract (verbatim frozen-methodology text)
METHODOLOGY_COMPARATOR_TEXT = "one `generate(session_id=i,"
DIRECT_MAX_NEW_TOKENS = 8
ORDINARY_MAX_NEW_TOKENS = 2
ONLY_INTENDED_DIFFERENCE_TEXT = (
    "The ONLY intended difference is the")
REPLAY_MARKER = "per-token-replay-prefill/1"

DIRECT_ATTEMPT = "armc-direct-6"
ORDINARY_ATTEMPT = "armc-ordinary-1"
POST_REVISION_DIAGNOSTICS = [
    "armc-direct-7", "armc-direct-8", "armc-direct-9",
]

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


def git_diff_names(rev_a: str, rev_b: str) -> list[str]:
    try:
        # --no-renames is SECURITY-CRITICAL: with rename detection a
        # high-similarity rename of a frozen file would list only the
        # NEW path, escaping the frozen-path hard fail; --no-renames
        # always enumerates both the deleted frozen path and the new
        # path (review P1, correction /2)
        return subprocess.check_output(
            ["git", "-c", f"safe.directory={ROOT}", "-C", str(ROOT),
             "diff", "--no-renames", "--name-only",
             f"{rev_a}..{rev_b}"],
            text=True).strip().splitlines()
    except subprocess.CalledProcessError as error:
        raise ReductionError(
            f"cannot diff {rev_a}..{rev_b}") from error


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def parse_utc(value: object, what: str) -> datetime.datetime:
    require(isinstance(value, str), f"{what} is not a retained string")
    assert isinstance(value, str)
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        stamp = datetime.datetime.fromisoformat(text)
    except ValueError as error:
        raise ReductionError(
            f"{what} is not a parseable UTC timestamp: {value!r}") from error
    require(stamp.tzinfo is not None,
            f"{what} is not timezone-qualified: {value!r}")
    return stamp.astimezone(datetime.timezone.utc)


def load_frozen_pins():
    """Import the sibling frozen-pins module by path (works both as a
    script and under the test importlib loader)."""
    path = Path(__file__).resolve().parent / "issue117_arm_c_frozen_pins.py"
    spec = importlib.util.spec_from_file_location(
        "issue117_arm_c_frozen_pins", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# steps 1-2: frozen identities + fail-closed exact-head audit
# ---------------------------------------------------------------------------

def verify_frozen_identities(head: str) -> dict:
    """Pin the pre-execution authority by git blob SHA and sha256,
    require the audit's disclosure to match, and enforce the
    FAIL-CLOSED exact-head policy for everything after the audited
    head."""
    run_record = load("run-record.json")
    require(run_record.get("pre_execution_inferwarm_sha")
            == FROZEN_INFERSWARM_SHA,
            "run-record pre_execution_inferswarm_sha is not the claimed "
            f"{FROZEN_INFERSWARM_SHA}")
    audit = load(PRE_EXECUTION_AUDIT)
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
    # post-freeze deltas disclosed: the driver and reducer at head are
    # NOT the frozen bytes
    require(frozen_files[FROZEN_DIRECT_DRIVER_PATH]["status_at_head"]
            == "changed_after_freeze",
            "direct driver status at head not disclosed as changed")
    require(frozen_files[FROZEN_REDUCER_PATH]["status_at_head"]
            == "changed_after_freeze",
            "reducer status at head not disclosed as changed")
    disclosed = {c["path"] for c in audit.get("post_freeze_changes", [])}
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
    name_status = git_diff_names(FROZEN_INFERSWARM_SHA, audited_head)
    require(set(name_status) == disclosed,
            "post-freeze change classification is incomplete: "
            f"{sorted(set(name_status) ^ disclosed)[:5]}")

    # ---- FAIL-CLOSED exact-head policy (correction /2) -------------
    # The previous logic (`not frozen_changed or FROZEN_REDUCER_PATH in
    # frozen_changed`) admitted methodology+driver+reducer changes after
    # the audited head whenever the legacy reducer also changed. It is
    # replaced by an explicit allowlist: every file that changed after
    # the audited head must be individually listed with its exact final
    # sha256, and the frozen methodology/driver are NEVER allowable.
    allowlist = audit.get("post_audit_correction_allowlist")
    require(isinstance(allowlist, dict) and allowlist,
            "authority audit does not carry a correction allowlist")
    if head != audited_head:
        later = git_diff_names(audited_head, head)
        for path in later:
            if path in (FROZEN_METHODOLOGY_PATH, FROZEN_DIRECT_DRIVER_PATH):
                raise ReductionError(
                    "FAIL-CLOSED exact-head audit: frozen methodology/"
                    f"driver changed after the audited head: {path}")
            entry = allowlist.get(path)
            if entry is None:
                raise ReductionError(
                    "FAIL-CLOSED exact-head audit: unexpected file "
                    f"changed after the audited head without an "
                    f"allowlist entry: {path}")
            if entry.get("self") or entry.get("derived"):
                # the audit document itself cannot pin its own digest
                # (MANIFEST-bound); derived maintenance artifacts
                # (producer-hashes / MANIFEST) are pure functions of
                # the final tree, regenerated last and verified by
                # the retention manifest suites
                continue
            expected = entry.get("sha256")
            require(isinstance(expected, str)
                    and re.fullmatch(r"[0-9a-f]{64}", expected or ""),
                    f"allowlist entry for {path} has no exact sha256")
            actual = sha256_bytes(git_show(head, path))
            require(actual == expected,
                    f"FAIL-CLOSED exact-head audit: {path} changed "
                    f"after the audited head with a digest that is not "
                    f"the allowlisted one")
    return {
        "pre_execution_inferwarm_sha": FROZEN_INFERSWARM_SHA,
        "audited_head": audited_head,
        "head": head,
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
        "exact_head_policy": (
            "fail-closed: frozen methodology/driver may never change "
            "after the audited head; every other post-audit change "
            "must be individually allowlisted with its exact sha256"),
        "disclosure": (
            "the direct driver and the reducer committed at the final "
            "head are NOT the scripts frozen by "
            "pre_execution_inferwarm_sha; every post-freeze change is "
            "classified in pre-execution-authority-audit.json and "
            "every post-audit correction file is individually pinned "
            "in its correction allowlist"),
    }


# ---------------------------------------------------------------------------
# steps 3-5: frozen invocation semantics + comparator defect
# ---------------------------------------------------------------------------

def derive_frozen_direct_semantics() -> dict:
    """Step 3: the frozen methodology defines the single-shot direct
    comparator and the frozen driver implements exactly that."""
    methodology = git_show(FROZEN_INFERSWARM_SHA,
                           FROZEN_METHODOLOGY_PATH).decode()
    require(METHODOLOGY_COMPARATOR_TEXT in methodology,
            "frozen methodology does not freeze the single-shot "
            "comparator")
    require(f"max_new_tokens={DIRECT_MAX_NEW_TOKENS}" in methodology,
            "frozen methodology lacks the max_new_tokens=8 comparator")
    require(ONLY_INTENDED_DIFFERENCE_TEXT in methodology,
            "frozen methodology lacks the comparator-isolation "
            "requirement (only-intended-difference clause)")
    driver = git_show(FROZEN_INFERSWARM_SHA,
                      FROZEN_DIRECT_DRIVER_PATH).decode()
    require(f"max_new_tokens={DIRECT_MAX_NEW_TOKENS}" in driver,
            "frozen direct driver does not implement the frozen "
            "single-shot comparator")
    require(f"max_new_tokens={ORDINARY_MAX_NEW_TOKENS}" not in driver,
            "frozen direct driver unexpectedly implements replay "
            "prefill")
    return {
        "invocation": "single-shot",
        "runtime_generate_calls_per_case": 1,
        "max_new_tokens": DIRECT_MAX_NEW_TOKENS,
        "prefill": "case prompt only, once per case",
        "source": (
            "METHODOLOGY-ARM-C §4 + scripts/issue117_arm_c_direct.py, "
            f"both pinned by git at {FROZEN_INFERSWARM_SHA}"),
    }


def derive_frozen_ordinary_semantics() -> dict:
    """Step 4: ordinary semantics from the sha256-pinned FreeToken
    producer bytes retained under frozen-freetoken/924cd22e/."""
    pins = load_frozen_pins()
    try:
        semantics = pins.derive_invocation_semantics()
    except pins.FrozenSourceError as error:
        raise ReductionError(str(error)) from error
    ordinary = semantics["ordinary"]
    require(ordinary["max_new_tokens"] == ORDINARY_MAX_NEW_TOKENS
            and ordinary["runtime_generate_calls_per_case"] == 8,
            "frozen ordinary semantics derivation is not the "
            "replay-prefix per-position loop")
    return ordinary


def derive_comparator_defect(direct: dict, ordinary: dict,
                             coordinator_provenance: dict) -> dict:
    """Step 5: the frozen comparator violated its own isolation
    requirement — the arms differed in runtime invocation semantics,
    not only in control-plane routing."""
    require(direct["max_new_tokens"] != ordinary["max_new_tokens"],
            "comparator defect vanished: direct and ordinary "
            "max_new_tokens are identical")
    require(direct["invocation"] != ordinary["invocation"],
            "comparator defect vanished: direct and ordinary "
            "invocations are identical")
    require(coordinator_provenance.get("planner_provenance_attempt_id")
            == DIRECT_ATTEMPT,
            "ordinary arm planner provenance does not cite the "
            "direct-6 ranking record")
    return {
        "defect": True,
        "frozen_requirement": ONLY_INTENDED_DIFFERENCE_TEXT,
        "violation": (
            "the frozen direct arm invokes the runtime single-shot "
            f"(max_new_tokens={DIRECT_MAX_NEW_TOKENS}, one prefill per "
            "case) while the frozen ordinary path invokes the runtime "
            "as a replay-prefix per-position loop "
            f"(max_new_tokens={ORDINARY_MAX_NEW_TOKENS} per committed "
            "token, full prefix re-fed, only the first of two "
            "speculative tokens committed) — a runtime invocation "
            "semantics difference in addition to the control-plane "
            "routing difference"),
        "authority_statement": (
            "The frozen Arm-C methodology failed its own "
            "comparator-isolation requirement. The direct arm and "
            "ordinary arm differed in runtime invocation semantics in "
            "addition to differing in control-plane routing. "
            "Therefore the frozen campaign could not establish "
            "ordinary-vs-direct serving equivalence or semantic "
            "failure as designed."),
        "note": (
            "the direct arm's single-shot invocation is NOT itself an "
            "error: it is exactly what the frozen methodology told the "
            "direct arm to use; the defect is in the frozen "
            "comparator's design, established before any execution"),
    }


# ---------------------------------------------------------------------------
# step 6-8: observations, chronology, modification forensics
# ---------------------------------------------------------------------------

def attempt_map(lineage: dict) -> dict:
    attempts = {a["attempt_id"]: a for a in lineage.get("attempts", [])}
    require(len(attempts) == len(lineage.get("attempts", [])),
            "duplicate attempt ids in lineage")
    return attempts


def completion_time(entry: dict, attempt_id: str) -> datetime.datetime:
    stamps = entry.get("observed_timestamps", {})
    source = stamps.get("completion_evidence_utc",
                        stamps.get("transcript_first_observed_utc"))
    return parse_utc(
        source,
        f"{attempt_id} completion/transcript timestamp")


def derive_observations(lineage: dict) -> dict:
    """Steps 6-8: correctness-bearing observations, retained chronology,
    direct-6 code identity, comparator-modification forensics."""
    require(lineage.get("schema")
            in ("inferswarm.issue117.arm-c.attempt-lineage/2",
                "inferswarm.issue117.arm-c.attempt-lineage/3"),
            "attempt lineage schema drift")
    attempts = attempt_map(lineage)

    # --- direct-6: correctness-bearing, single-shot-consistent,
    #     exact driver bytes unknown / not retained
    trigger = attempts.get(DIRECT_ATTEMPT)
    require(trigger is not None, f"{DIRECT_ATTEMPT} erased from lineage")
    assert trigger is not None
    require(trigger.get("correctness_bearing_result_emitted") is True,
            f"{DIRECT_ATTEMPT} correctness-bearing flag missing")
    require(trigger.get("gpu_residency_achieved") is True,
            f"{DIRECT_ATTEMPT} GPU residency flag missing")
    identity = trigger.get("code_identity", {})
    require(identity.get("driver_bytes") == UNKNOWN,
            f"{DIRECT_ATTEMPT} exact staged driver bytes are not "
            "retained as 'unknown / not retained' — a forged exact "
            "driver identity is not supported by retained evidence")
    inv6 = load("invalid-attempt-6/direct-run.json")
    require(inv6.get("attempt_id") == DIRECT_ATTEMPT,
            "invalid-attempt-6/direct-run.json attempt id drift")
    require(inv6.get("case_count") == 24
            and len(inv6.get("results", [])) == 24,
            "invalid-attempt-6 results do not carry 24 cases")
    for row in inv6["results"]:
        require(row.get("invocation") != REPLAY_MARKER,
                "invalid-attempt-6 rows unexpectedly carry the "
                "replay-prefill marker")
    d6_time = completion_time(trigger, DIRECT_ATTEMPT)

    # --- ordinary-1: correctness-bearing ordinary-path observation
    ordinary = attempts.get(ORDINARY_ATTEMPT)
    require(ordinary is not None,
            f"{ORDINARY_ATTEMPT} erased from lineage")
    assert ordinary is not None
    require(ordinary.get("correctness_bearing_result_emitted") is True,
            f"{ORDINARY_ATTEMPT} correctness-bearing flag missing")
    campaign = load("ordinary-campaign.json")
    require(campaign.get("attempt_id") == ORDINARY_ATTEMPT,
            "ordinary-campaign.json attempt id drift")
    require(campaign.get("case_count") == 24
            and campaign.get("ok_count") == 24,
            "ordinary campaign is not the retained 24-case run")
    # the ordinary per-token commit ledger: >= 24 coordinator sessions,
    # each with 8 committed positions and per-position attribution
    report = load("coordinator-report.json")
    sessions = report.get("sessions", [])
    require(len(sessions) >= 24,
            "coordinator report does not carry the 24 ordinary "
            "sessions")
    for session in sessions[:24]:
        boundary = session.get("latest_committed_boundary", {})
        require(boundary.get("committed_position") == 8,
                "ordinary session is not an 8-position committed "
                "ledger")
        require(len(session.get("committed_epoch_ids", [])) == 8
                and len(session.get("committed_plan_digests", [])) == 8,
                "ordinary session lacks per-position commit "
                "attribution")
    # ordinary planner provenance cites the direct-6 ranking record
    epochs = report.get("epochs", [])
    require(epochs, "coordinator report carries no epoch")
    provenance_id = None
    audit_rows = epochs[0].get("execution_plan", {}).get(
        "evidence_audit", [])
    if audit_rows:
        provenance_id = audit_rows[0].get(
            "provenance", {}).get("attempt_id")
    o1_time = completion_time(ordinary, ORDINARY_ATTEMPT)

    # --- direct-7/8/9: post-revision diagnostics
    diagnostics = {}
    for attempt_id in POST_REVISION_DIAGNOSTICS:
        entry = attempts.get(attempt_id)
        require(entry is not None,
                f"post-revision diagnostic {attempt_id} erased from "
                "lineage")
        assert entry is not None
        classification = entry.get("campaign_classification", "")
        require("diagnostic" in classification
                and "inadmissible" in classification,
                f"{attempt_id} not classified as a retained diagnostic "
                f"inadmissible to the terminal campaign")
        require("admissible terminal" not in classification,
                f"{attempt_id} classification claims terminal "
                "admissibility it cannot have")
        diagnostics[attempt_id] = completion_time(entry, attempt_id)
    # no attempt may claim terminal admissibility
    for attempt_id, entry in attempts.items():
        require("admissible terminal" not in entry.get(
            "campaign_classification", ""),
            f"{attempt_id} classification claims terminal "
            "admissibility it cannot have")
    # the retained 18/24 comparison used the post-revision direct-9
    direct9 = load("direct-run.json")
    require(direct9.get("attempt_id") == "armc-direct-9",
            "direct-run.json is not the direct-9 side")
    marked = sum(1 for r in direct9.get("results", [])
                 if r.get("invocation") == REPLAY_MARKER)
    require(marked == 24,
            "retained direct-run.json is not the replay-prefill "
            "(direct-9) side")

    # --- chronology from retained timestamps only
    chronology = {
        "armc-direct-6": d6_time,
        "armc-ordinary-1": o1_time,
        **diagnostics,
    }
    order_keys = list(chronology)
    for earlier, later in zip(order_keys, order_keys[1:]):
        require(chronology[earlier] < chronology[later],
                f"retained timestamp chronology violated: {earlier} "
                f"({chronology[earlier].isoformat()}) is not before "
                f"{later} ({chronology[later].isoformat()})")
    # every correctness-bearing attempt MUST be in the derived
    # chronology (no correctness-bearing attempt escapes timestamp
    # scrutiny); non-correctness-bearing attempts without completion
    # evidence (e.g. armc-lss-1, whose transcript value is a first
    # MENTION that postdates the campaign due to census-query
    # semantics) are excluded by design and documented in the lineage
    for attempt_id, entry in attempts.items():
        if entry.get("correctness_bearing_result_emitted"):
            require(attempt_id in chronology,
                    f"correctness-bearing attempt {attempt_id} lacks "
                    "timestamp-derived chronology")
    # the authored logical order field must not contradict the
    # timestamp-supported chronology
    for earlier, later in zip(order_keys, order_keys[1:]):
        logical_earlier = attempts[earlier].get("order")
        logical_later = attempts[later].get("order")
        if isinstance(logical_earlier, int) \
                and isinstance(logical_later, int):
            require(logical_earlier < logical_later,
                    f"authored logical order contradicts retained "
                    f"timestamps: {earlier}(order={logical_earlier}) "
                    f"precedes {later}(order={logical_later}) in "
                    "timestamp evidence but not in logical order")

    # --- comparator-modification forensics: the staged driver was
    #     overwritten after direct-6 completed and before direct-7
    audit = load(PRE_EXECUTION_AUDIT)
    forensics = audit.get("comparator_modification_forensics", {})
    d6_done = parse_utc(
        forensics.get("direct6_completed_utc"),
        "comparator forensics direct6_completed_utc")
    staged_mtime = parse_utc(
        forensics.get("staged_driver_mtime_utc"),
        "comparator forensics staged_driver_mtime_utc")
    d7_seen = parse_utc(
        forensics.get("direct7_first_observed_utc"),
        "comparator forensics direct7_first_observed_utc")
    require(d6_done < staged_mtime < d7_seen,
            "comparator modification forensics inconsistent: the "
            "staged-driver overwrite must postdate direct-6 completion "
            "and predate direct-7")
    require(abs((d6_done - d6_time).total_seconds()) < 300,
            "audit direct-6 completion time disagrees with the "
            "lineage timestamp evidence")

    return {
        "direct6": {
            "correctness_bearing": True,
            "gpu_residency": True,
            "retained_result_rows": 24,
            "invocation": (
                "consistent with the frozen single-shot comparator "
                "(no replay marker in any retained row; the marker was "
                "introduced by the post-observation driver revision)"),
            "exact_staged_driver_bytes": UNKNOWN,
            "completed_utc": d6_time.isoformat(),
        },
        "ordinary1": {
            "correctness_bearing": True,
            "cases": 24,
            "committed_ledger_sessions": len(sessions),
            "planner_provenance_attempt_id": provenance_id,
            "completed_utc": o1_time.isoformat(),
        },
        "diagnostics_789": {
            aid: t.isoformat() for aid, t in diagnostics.items()},
        "chronology_utc": {
            aid: t.isoformat() for aid, t in chronology.items()},
        "chronology_note": (
            "physical chronology is derived only from retained "
            "completion-evidence and transcript timestamps; the "
            "authored logical order field is retained separately and "
            "must agree with it"),
        "comparator_modification": {
            "direct6_completed_utc": d6_done.isoformat(),
            "staged_driver_overwrite_utc": staged_mtime.isoformat(),
            "direct7_first_observed_utc": d7_seen.isoformat(),
        },
        "direct9_is_frozen_comparator": False,
        "direct9_note": (
            "armc-direct-9 used the post-freeze, post-observation "
            "replay-prefill invocation (its result rows carry "
            f"{REPLAY_MARKER}); it is a revised diagnostic "
            "invocation, not the comparator frozen at "
            f"{FROZEN_INFERSWARM_SHA}"),
        "historical_validity_flag_direct6":
            trigger.get("retained_validity_flag"),
    }


# ---------------------------------------------------------------------------
# step 7: dual-history branch analysis
# ---------------------------------------------------------------------------

def derive_branch_analysis(observations: dict) -> dict:
    """Both exhaustive histories converge on the blocker. The terminal
    never depends on resolving the historical ambiguity or on a
    post-hoc validity judgment."""
    flag = observations["historical_validity_flag_direct6"]
    require(isinstance(flag, bool),
            "armc-direct-6 retained_validity_flag (the historical/"
            "post-hoc classification, retained verbatim) is missing")
    chronology = observations["chronology_utc"]
    d6_first = chronology["armc-direct-6"] < chronology[
        "armc-ordinary-1"]

    branch_a = {
        "condition": (
            "direct-6 was regarded as valid when ordinary-1 ran"),
        "derivable": flag is True,
        "derivation": (
            "direct-6 + ordinary-1 followed the frozen campaign, but "
            "the frozen comparator itself was defective: the arms "
            "differed in runtime invocation semantics by design "
            "(single-shot max_new_tokens=8 vs replay-prefix "
            "max_new_tokens=2 per-position commit loop)"),
        "terminal": BLOCKED,
    }
    branch_b = {
        "condition": (
            "direct-6 had already been regarded as invalid before "
            "ordinary-1 ran"),
        "derivable": flag is False and d6_first,
        "derivation": (
            "frozen methodology §10 required STOP for maintainer "
            "review after direct-6's correctness-bearing output "
            f"({chronology['armc-direct-6']} precedes ordinary-1 at "
            f"{chronology['armc-ordinary-1']} per retained timestamp "
            "evidence), and ordinary-1 improperly ran afterward"),
        "terminal": BLOCKED,
    }
    derivable = [b for b in (branch_a, branch_b) if b["derivable"]]
    require(derivable,
            "neither history is mechanically derivable: the retained "
            "validity flag is ambiguous and the retained chronology "
            "does not support the §10 stop ordering")
    return {
        "historical_ambiguity": (
            "the exact moment at which the operator first regarded "
            "direct-6 as an invalid comparator is not independently "
            "retained; both exhaustive possibilities are derived and "
            "both converge on the blocker"),
        "branches": [branch_a, branch_b],
        "convergence": BLOCKED,
        "stop_rule_ambiguity_reported": True,
        "note": (
            "the §10 stop-rule ambiguity is REPORTED but never "
            "REQUIRED to derive the terminal: the comparator-methods "
            "defect alone establishes the blocker"),
    }


# ---------------------------------------------------------------------------
# step 9: frozen-rule Source reads
# ---------------------------------------------------------------------------

def derive_source_read_violation() -> dict:
    """The four tokenizer-metadata Source opens and one Source-root
    directory stat under the frozen zero-Source rule (no exemption at
    the freeze)."""
    audit = load(PRE_EXECUTION_AUDIT)
    accounting = audit.get("source_read_accounting_frozen_rule", {})
    require(accounting.get("model_weight_file_reads") == 0,
            "Source model-weight reads present — reclassify before "
            "using this reducer")
    metadata = accounting.get("tokenizer_metadata_file_reads")
    require(isinstance(metadata, int),
            "tokenizer metadata read count missing from the audit")
    require(metadata == 4,
            "tokenizer metadata read count is not the retained four")
    require(accounting.get("source_root_directory_stats") == 1,
            "Source-root directory stat count is not the retained one")
    # cross-check against the raw retained strace audit paths
    strace = load("strace-audit.json")
    seen_files, seen_dirs = 0, 0
    for window in strace.get("windows", {}).values():
        for path in window.get("paths", []):
            if "/srv/models/" not in path:
                continue
            if path.endswith((
                    "/config.json", "/chat_template.jinja",
                    "/tokenizer.json", "/tokenizer_config.json",
                    "/generation_config.json", "/processor_config.json",
                    "/preprocessor_config.json")):
                seen_files += 1
            elif path.rstrip("/").endswith("/gemma-r6"):
                seen_dirs += 1
    require(seen_files == metadata,
            "audit metadata-read count disagrees with the retained "
            f"strace paths ({seen_files} != {metadata})")
    require(seen_dirs == accounting.get("source_root_directory_stats"),
            "audit directory-stat count disagrees with the retained "
            f"strace paths ({seen_dirs})")
    return {
        "frozen_rule": "zero /srv/models/ opens in the serving windows",
        "tokenizer_metadata_file_reads": metadata,
        "source_root_directory_stats":
            accounting.get("source_root_directory_stats"),
        "model_weight_file_reads": 0,
        "participant_source_tree_reads_under_frozen_rule": metadata,
        "classification": (
            "the four tokenizer-metadata opens and one Source-root "
            "stat are retained and counted under the frozen rule (no "
            "post-hoc exemption); they independently bar PASS and "
            "reinforce the methodology/evidence blocker"),
    }


# ---------------------------------------------------------------------------
# terminal
# ---------------------------------------------------------------------------

def reduce_all() -> dict:
    head = subprocess.check_output(
        ["git", "-c", f"safe.directory={ROOT}", "-C", str(ROOT),
         "rev-parse", "HEAD"], text=True).strip()
    authority = verify_frozen_identities(head)
    direct = derive_frozen_direct_semantics()
    ordinary = derive_frozen_ordinary_semantics()
    lineage = load("attempt-lineage.json")
    observations = derive_observations(lineage)
    defect = derive_comparator_defect(
        direct, ordinary,
        {"planner_provenance_attempt_id":
         observations["ordinary1"]["planner_provenance_attempt_id"]})
    branches = derive_branch_analysis(observations)
    source_reads = derive_source_read_violation()

    # terminal derivation (never from a stored string):
    #  - PASS impossible: frozen-rule Source reads + no admissible
    #    comparator methodology;
    #  - semantic ordinary-serving FAIL inadmissible: the frozen
    #    comparator itself was defective (the arms differed in runtime
    #    invocation semantics by design); under every possible history
    #    the campaign is methodology/evidence-blocked;
    #  - blocker is the narrowest defensible terminal.
    terminal = BLOCKED
    return {
        "schema": "inferswarm.issue117.arm-c.blocker-reduction/2",
        "head_audited": authority["audited_head"],
        "terminal": terminal,
        "terminal_qualification": BLOCKER_QUALIFICATION,
        "authority": authority,
        "frozen_invocation_semantics": {
            "direct": direct,
            "ordinary": ordinary,
        },
        "comparator_defect": defect,
        "observations": observations,
        "branch_analysis": branches,
        "source_reads_frozen_rule": source_reads,
        "attempt_dispositions": {
            "armc-direct-6": (
                "correctness-bearing physical observation; invocation "
                "consistent with the frozen single-shot comparator; "
                "exact staged driver bytes unknown / not retained; "
                "part of the evidence that exposes the frozen "
                "comparator defect; NOT accepted terminal comparator "
                "evidence"),
            "armc-ordinary-1": (
                "correctness-bearing ordinary-path observation, "
                "executed after direct-6 and before the replay-prefill "
                "rewrite reached a completed direct run; part of the "
                "frozen-methodology campaign evidence; inadmissible "
                "to a semantic PASS/FAIL because the comparator "
                "methodology was defective"),
            "armc-direct-7": (
                "post-observation/post-methodology-revision "
                "diagnostic; inadmissible to the terminal campaign"),
            "armc-direct-8": (
                "post-observation/post-methodology-revision "
                "diagnostic; inadmissible to the terminal campaign"),
            "armc-direct-9": (
                "post-observation/post-methodology-revision "
                "diagnostic (replay-prefill side of the retained "
                "18/24 comparison); inadmissible to the terminal "
                "campaign"),
        },
        "terminal_derivation": [
            "claimed pre-execution SHA verified: 5e2c83a…",
            "frozen methodology/driver/reducer digests pinned by git "
            "blob SHA + sha256; exact-head audit fail-closed",
            "frozen direct invocation semantics derived from git: "
            "single-shot max_new_tokens=8 (what the methodology told "
            "the direct arm to use)",
            "frozen ordinary invocation semantics derived from the "
            "sha256-pinned FreeToken bytes at 924cd22e: replay-prefix "
            "per-position loop, max_new_tokens=2 per call, commit "
            "step zero, discard the speculative second token",
            "frozen same-substrate / same-generation-semantics / "
            "only-control-plane-difference requirement violated by "
            "design → comparator-methodology defect",
            "correctness-bearing direct and ordinary observations "
            "verified retained (24 rows each; 24-session committed "
            "ledger)",
            "comparator-script identity for direct-6 verified NOT "
            "fully retained (unknown / not retained) — "
            "unrecoverability independently strengthens the blocker",
            "later comparator modification verified to occur only "
            "after the correctness-bearing observation (staged "
            "overwrite 10:43 UTC between direct-6 completion 10:28 "
            "UTC and direct-7 observation 10:49 UTC)",
            "four tokenizer-metadata Source file reads + one "
            "Source-root stat retained under the frozen zero-Source "
            "rule → PASS impossible",
            "both exhaustive histories (direct-6 valid or already "
            "invalid when ordinary-1 ran) converge on the blocker → "
            "semantic ordinary-serving FAIL inadmissible",
            "terminal is the Arm-C evidence/methodology blocker "
            "(post-correctness-bearing methodology / "
            "evidence-admissibility failure)",
        ],
        "retained_diagnostic_value": {
            "equality_18_of_24": (
                "retained as diagnostic evidence only (post-revision "
                "replay-prefill comparator); it does NOT establish "
                "the terminal Arm-C ordinary-serving result"),
            "six_regime_4_divergences": (
                "retained as diagnostic evidence; a FOLLOW-UP KV/"
                "multi-chunk hypothesis, not the accepted result of "
                "this campaign"),
        },
        "arm_d": "blocked",
        "arm_c_retry_authorized": False,
        "physical_execution_performed_by_this_correction": False,
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
        "head_audited": result["head_audited"],
        "frozen_direct": (
            result["frozen_invocation_semantics"]["direct"]
            ["invocation"] + " mnt=" + str(
                result["frozen_invocation_semantics"]["direct"]
                ["max_new_tokens"])),
        "frozen_ordinary": (
            result["frozen_invocation_semantics"]["ordinary"]
            ["invocation"] + " mnt=" + str(
                result["frozen_invocation_semantics"]["ordinary"]
                ["max_new_tokens"])),
        "branch_convergence":
            result["branch_analysis"]["convergence"],
        "tokenizer_metadata_source_reads":
            result["source_reads_frozen_rule"][
                "tokenizer_metadata_file_reads"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
