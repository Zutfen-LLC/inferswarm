#!/usr/bin/env python3
"""Issue #133 — terminal reduction: mechanically derive the terminal
classification and all mandatory zero invariants from retained raw evidence.

Schema /2 — correction round for maintainer review 5172615768.

Pure stdlib. Fails closed. No stored terminal/verdict text is authority.

Change log for /2 (each item closes a maintainer finding):

* P1 (invariant gating): the reducer now loads and validates EVERY
  evidence family Issue #133 makes a prerequisite for an admissible
  semantic PASS/FAIL — canonical prelaunch verdicts, execution-freeze /
  authority binding, tokenizer deployment/render proof, host preflights,
  substrate reconciliations for inferswarm01 and inferswarm03, direct and
  ordinary deployment identity evidence, strace-audit.json,
  strace-raw-pins.json, attempt/launch lineage, direct run, ordinary
  campaign, serving report, fencing evidence, Coordinator pre/post
  observations, and the equality reduction.  A semantic PASS/FAIL is
  legal only if every non-semantic invariant passes; an ordinary semantic
  mismatch can never mask an invariant failure.
* P1 (derived zeros): every mandatory zero counter (fencing/attribution
  and Coordinator families) is DERIVED from retained observations; no
  terminal-authority value is an assigned constant.  Controlled rejected
  injections are excluded from commit counters by their RETAINED
  rejection records (coordinator-side accepted:false entries mirrored by
  serving-report late_result_rejections), not by intent.
* P1/P2 (invocation seam): the equality reduction must mechanically
  prove pre-divergence model-input equivalence; the terminal consumes
  that proof (equality-reduction schema /2 field
  invocation_equivalence.holds) and refuses a semantic FAIL without it.
* P3 (launch-1 lineage): the reducer explicitly consumes
  attempts/launch1-failure.log + attempts/execution-plan.launch1.json
  and derives that launch 1 qualifies as
  PRE_OBSERVATION_INFRASTRUCTURE from the retained bytes (dependency
  failure signature, zero launch-1 case/commit observations) — not from
  the authored classification_at_emission field alone.

The docstring of each section below names the exact retained evidence
establishing each invariant (authority ladder: raw/low-level observation
> derived artifact > stored summary > terminal classification).
"""
import hashlib
import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

COLLECTED = Path(sys.argv[1])
# Repo root (for freeze/authority bytes and the frozen direct driver);
# default: two levels above scripts/ when run from a checkout.
ROOT = Path(os.environ.get("ARM_C_RETRY_REPO_ROOT",
                           str(Path(__file__).resolve().parents[1])))
EVIDENCE = COLLECTED.parent          # evidence/arm-c-retry/

problems = []
invariants = {}
blocker = []          # narrowest-first blockers; first hit wins


def blocker_class(name):
    blocker.append(name)
    return name


def load(rel):
    return json.loads((COLLECTED / rel).read_text())


def sha256_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def require(cond, msg):
    if not cond:
        problems.append(msg)
    return cond


# ---- load retained evidence -------------------------------------------------
direct_run = load("direct/direct-run.json")
equality = load("equality-reduction.json")
serving = load("ordinary-http/serving-report.json")
campaign = load("ordinary-http/ordinary-campaign.json")
attempt = load("attempts/armc-retry-physical-1.json")
coord_pre = load("ordinary-http/coordinator-observation-pre.json")
coord_post = load("ordinary-http/coordinator-observation-post.json")
coordinator_config = load("ordinary-http/coordinator-config.json")
fencing_arm = load("ordinary-http/fencing-arm.json")
serving_evidence = load("ordinary-http/serving-evidence.json")
last_stage_direct = load("last-stage-direct.json")
last_stage_ordinary = load("last-stage-ordinary.json")
strace_audit = load("strace-audit.json")
strace_raw_pins = load("strace-raw-pins.json")
substrate01 = load("substrate-reconciliation-01.json")
substrate03 = load("substrate-reconciliation-03.json")
boundary_pins = load("coordinator-boundary-source-pins.json")
verdict_run1 = load("preflight/prelaunch-verdict-run1.json")
verdict_final = load("preflight/prelaunch-verdict-immediate-prelaunch.json")
tokenizer_proof = load("preflight/tokenizer-deployment-proof.json")
preflight01 = load("preflight/host-preflight-01.json")
preflight03 = load("preflight/host-preflight-03.json")
freeze = json.loads((EVIDENCE / "execution-freeze.json").read_text())
authority = json.loads(
    (EVIDENCE / "physical-campaign-authority.json").read_text())
fixture = json.loads((EVIDENCE / "prompt-fixture.json").read_text())
launch1_log = (COLLECTED / "attempts/launch1-failure.log").read_text()
launch1_plan = load("attempts/execution-plan.launch1.json")
gpu_identity = json.loads((EVIDENCE / "gpu-identity-observation.json")
                          .read_text())
integrity = json.loads((EVIDENCE / "integrity.json").read_text())

CAMPAIGN = "armc-retry-afcdc4428f95d50c"
FREEZE = "88389598ac485f82aa3ec00caadcebcb3cafb56cf967751262e8ab5bc9bf9a1c"
AUTHORITY_COMMIT = "c42a0ea3f12532ab74c4e79772e1a126b5028514"
FROZEN_PRODUCER = "924cd22ea081f6d4ed471016faf01d427fc5b0d2"
DIRECT_DRIVER_SHA = freeze["drivers"]["direct"]["file_sha256"]
R5B_EPOCHS_SHA = freeze["dependencies"][
    "runtime_session_allocator_source"]["file_sha256"]

# ---- 1. campaign/attempt identity -------------------------------------------
facts = attempt["facts"]
require(facts["campaign_id"] == CAMPAIGN, "attempt campaign id drift")
require(facts["execution_freeze_identity"] == FREEZE,
        "attempt freeze identity drift")
require(attempt.get("classification_final") in (
    "CORRECTNESS_BEARING_VALID", "TERMINAL_CAMPAIGN_ATTEMPT"),
    "attempt classification not in legal terminal set")
require(facts["correctness_bearing_result_emitted"] is True,
        "attempt did not emit correctness-bearing results")
require(facts["stop_occurred"] is False, "authored stop flag set")

# authority document binds this campaign to exactly this freeze + methodology
auth_campaign = authority["campaigns"].get(CAMPAIGN)
require(auth_campaign is not None, "campaign absent from authority")
if auth_campaign:
    require(auth_campaign["execution_freeze_identity"] == FREEZE,
            "authority freeze binding drift")
    require(auth_campaign["physical_retry_authorized"] is True,
            "physical retry not authorized")
    require(all(auth_campaign.get(f) is None for f in (
        "prior_stop_attempt_id", "prior_stop_review_id",
        "prior_stop_reviewed_at", "prior_stopped_campaign_id")),
        "campaign lineage carries a prior stop")

# execution freeze: canonical identity = sha256 of the file bytes as
# retained (the campaign tool's canonical dump: indent=2, sort_keys, \n)
freeze_bytes = (EVIDENCE / "execution-freeze.json").read_bytes()
require(hashlib.sha256(freeze_bytes).hexdigest() == FREEZE,
        "execution freeze bytes do not hash to the frozen identity")

# ---- 1a. canonical prelaunch verdicts ----------------------------------------
# Evidence: preflight/prelaunch-verdict-{run1,immediate-prelaunch}.json —
# the accepted Git-rooted pre-execution gate, executed twice.
for name, v in (("run1", verdict_run1),
                ("immediate-prelaunch", verdict_final)):
    require(v.get("pass") is True, f"prelaunch verdict {name} not PASS")
    require(v.get("source_mode") == "accepted_git_materialization",
            f"prelaunch verdict {name} source mode drift")
    require(v.get("accepted_authority_commit") == AUTHORITY_COMMIT,
            f"prelaunch verdict {name} authority commit drift")
    require(v.get("execution_freeze_identity") == FREEZE,
            f"prelaunch verdict {name} freeze binding drift")

# ---- 1b. tokenizer deployment / render proof ---------------------------------
# Evidence: preflight/tokenizer-deployment-proof.json — 24/24 ordinary
# Coordinator chat-template render equality against the frozen fixture,
# zero forbidden Source opens, frozen software identity.
require(tokenizer_proof.get("passed") is True,
        "tokenizer deployment proof not passed")
require(tokenizer_proof.get("equal_count") == 24
        and tokenizer_proof.get("case_count") == 24,
        "tokenizer render equality != 24/24")
require(tokenizer_proof.get("forbidden_source_opens") == [],
        "tokenizer deployment opened forbidden sources")
require(tokenizer_proof.get("installed") == dict(
    freeze["tokenizer_software_identity"]),
    "tokenizer software identity drift vs freeze")
# the deployed asset set must be exactly the frozen pins
for rel, pin in freeze["tokenizer_asset_pins"].items():
    actual = sha256_file(EVIDENCE / "frozen-tokenizer" / "assets" / rel)
    require(actual == pin, f"frozen tokenizer asset digest drift: {rel}")

# ---- 1c. host preflights ------------------------------------------------------
# Evidence: preflight/host-preflight-{01,03}.json — producer cleanliness,
# frozen driver/allocator deployment digests, GPU identity, tokenizer dir.
for host, pf in (("01", preflight01), ("03", preflight03)):
    require(pf.get("passed") is True, f"host preflight {host} not passed")
    checks = pf.get("checks", {})
    require(checks.get("producer", {}).get("clean") is True
            and checks.get("producer", {}).get("head") == FROZEN_PRODUCER,
            f"host {host} producer drift")
    require(checks.get("gpu_compute_apps") == "none",
            f"host {host} GPUs busy at preflight")
if preflight01["checks"].get("driver", {}).get("sha256") != DIRECT_DRIVER_SHA:
    problems.append("host 01 deployed driver digest != freeze pin")
if preflight01["checks"].get("r5b_epochs", {}).get(
        "sha256") != R5B_EPOCHS_SHA:
    problems.append("host 01 deployed allocator digest != freeze pin")

# ---- 1d. substrate reconciliation (both participants) -------------------------
# Evidence: substrate-reconciliation-{01,03}.json — the accepted Arm-B
# participant materializations byte-identical (path set + per-file sha256)
# before and after the campaign.
for host, rec in (("01", substrate01), ("03", substrate03)):
    require(rec.get("passed") is True,
            f"substrate reconciliation {host} not passed")
    require(rec.get("problems") == [],
            f"substrate reconciliation {host} problems")
    for row in rec.get("rows", []):
        require(row.get("sha256_ok") and row.get("size_ok"),
                f"substrate {host} row drift: {row.get('path')}")

# ---- 1e. strace audit + raw pins ---------------------------------------------
# Evidence: strace-audit.json (participant data-path: zero Source opens,
# zero participant-state writes across all traced processes) and
# strace-raw-pins.json (sha256 pins of the out-of-repo raw strace bytes).
require(strace_audit.get("passed") is True, "strace audit not passed")
for name, t in strace_audit.get("traces", {}).items():
    require(t.get("source_models_opens") == 0,
            f"strace {name}: Source opens != 0")
    require(t.get("materialized_writes") == 0,
            f"strace {name}: participant-state writes != 0")
for name, pin in strace_raw_pins.get("pins", {}).items():
    require(isinstance(pin.get("sha256"), str)
            and len(pin["sha256"]) == 64,
            f"strace raw pin {name} malformed")

# ---- 1f. deployment identity (direct driver post-run) ------------------------
# Evidence: the frozen direct driver + allocator must still be, at
# reduction time, the exact bytes the freeze pinned and the hosts
# deployed (repository bytes == freeze pin == preflight deployment).
driver_repo = ROOT / "scripts/issue133_arm_c_retry_direct.py"
if driver_repo.is_file():
    require(sha256_file(driver_repo) == DIRECT_DRIVER_SHA,
            "repository direct driver bytes != freeze pin (post-run "
            "identity drift)")
allocator_vendored = (EVIDENCE / "frozen-source/924cd22e/python/freetoken"
                      "/research/r5b_epochs.py")
if allocator_vendored.is_file():
    require(sha256_file(allocator_vendored) == R5B_EPOCHS_SHA,
            "vendored frozen allocator bytes != freeze pin")
# last-stage producer check (both arms): frozen == running producer
for name, ls in (("direct", last_stage_direct),
                 ("ordinary", last_stage_ordinary)):
    require(ls.get("producer_check", {}).get("mode") == "PLAN_FROZEN"
            and ls["producer_check"].get("running_producer")
            == FROZEN_PRODUCER,
            f"last-stage {name} producer identity drift")

# ---- 2. launch-1 lineage + fail-closed attempt attribution --------------
# Evidence: attempts/launch1-failure.log (ModuleNotFoundError before any
# correctness-bearing output), attempts/execution-plan.launch1.json (the
# launch-1 frozen plan exists and predates the retained case evidence),
# and the ABSENCE of launch-1 case/commit observations.
#
# Review 5173318161 P2: a correctness-bearing observation with a NULL or
# missing attempt attribution is itself an evidence defect; the /2 logic
# treated attempt_id == None as harmless.  Every physical observation is
# now required to bind POSITIVELY to its authorized attempt/sub-attempt:
#   * direct-run.json must carry attempt_id == the authorized attempt;
#   * every direct per-case file carries no attempt field in its frozen
#     schema, so each must bind by FULL content identity to a results
#     row of the attempt-attributed direct run (and its transcript row
#     must commit exactly the case's generated ids);
#   * ordinary-campaign.json must carry attempt_id == the authorized
#     ordinary sub-attempt;
#   * every ordinary per-case file must bind by full content identity to
#     a record of that campaign;
#   * any attempt_id-bearing case file must name exactly the authorized
#     attempt (null/wrong/missing all fail);
#   * no other attempt ids may appear anywhere in the retained set.
AUTHORIZED_ATTEMPT = "armc-retry-physical-1"
AUTHORIZED_ORDINARY_SUBATTEMPT = "armc-retry-physical-1-ordinary"
launch1_dependency_failure = (
    "ModuleNotFoundError" in launch1_log
    and re.search(r"No module named 'tvm_ffi'", launch1_log) is not None)
require(launch1_dependency_failure,
        "launch-1 log does not show the retained dependency failure")
require(launch1_plan.get("digest") == "sha256:a730405dab8bad2ee8c4eea9a4"
        "fb97b8ef53ea15415a4d904bf666d020cdc625",
        "launch-1 execution plan digest drift")

# 2a. aggregates carry the exact authorized attribution
require(direct_run.get("attempt_id") == AUTHORIZED_ATTEMPT,
        "direct run attempt attribution drift")
require(campaign.get("attempt_id") == AUTHORIZED_ORDINARY_SUBATTEMPT,
        "ordinary campaign attempt attribution drift")

# 2b. per-case files: content-identity binding to the attributed
# aggregates + explicit attempt-field fail-closed checks
import glob as _glob  # noqa: E402

_direct_case_files = sorted(
    (COLLECTED / "direct").glob("direct-c109-*.json"))
require(len(_direct_case_files) == 24,
        f"direct case file count {len(_direct_case_files)} != 24")
_dr_rows = {r["case_id"]: r for r in direct_run["results"]}
_dr_transcript = {t["case_id"]: t
                  for t in direct_run["invocation_transcript"]}
for cf in _direct_case_files:
    doc = json.loads(cf.read_text())
    cid = doc.get("case_id")
    row = _dr_rows.get(cid)
    if row is None:
        problems.append(f"direct case {cid}: no attributed direct-run row")
        continue
    if json.dumps(doc, sort_keys=True) != json.dumps(row, sort_keys=True):
        problems.append(
            f"direct case {cid}: content does not bind to the "
            "attempt-attributed direct-run results row")
    tr = _dr_transcript.get(cid)
    if tr is None:
        problems.append(f"direct case {cid}: no transcript row")
        continue
    if [c["committed_token"] for c in tr["calls"]] != list(
            doc.get("generated_token_ids", [])):
        problems.append(
            f"direct case {cid}: transcript commits != case ids")
    if tr.get("logical_session_id") != doc.get("logical_session_id"):
        problems.append(f"direct case {cid}: logical session drift")
    # fail-closed attribution for any explicit attempt field
    aid = doc.get("attempt_id", "__absent__")
    if aid != "__absent__" and aid != AUTHORIZED_ATTEMPT:
        problems.append(
            f"direct case {cid}: attempt_id {aid!r} is not the "
            "authorized attempt (null/missing/wrong fail closed)")

_ordinary_case_files = sorted(
    (COLLECTED / "ordinary-http").glob("ordinary-c109-*.json"))
require(len(_ordinary_case_files) == 24,
        f"ordinary case file count {len(_ordinary_case_files)} != 24")
_oc_recs = {r["case_id"]: r for r in campaign["records"]}
for cf in _ordinary_case_files:
    doc = json.loads(cf.read_text())
    cid = doc.get("case_id")
    rec = _oc_recs.get(cid)
    if rec is None:
        problems.append(
            f"ordinary case {cid}: no attributed campaign record")
        continue
    if json.dumps(doc, sort_keys=True) != json.dumps(rec, sort_keys=True):
        problems.append(
            f"ordinary case {cid}: content does not bind to the "
            "sub-attempt-attributed campaign record")
    aid = doc.get("attempt_id", "__absent__")
    if aid != "__absent__" and aid != AUTHORIZED_ORDINARY_SUBATTEMPT:
        problems.append(
            f"ordinary case {cid}: attempt_id {aid!r} is not the "
            "authorized ordinary sub-attempt")

# 2c. no unexpected attempt ids anywhere in the retained evidence tree
_ALLOWED_ATTEMPT_IDS = {AUTHORIZED_ATTEMPT, AUTHORIZED_ORDINARY_SUBATTEMPT,
                        "armc-direct-6"}  # historical ranking-evidence id


def _attempt_ids(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            # identity fields only (attempt_id / *_attempt_id);
            # prose fields like reason_attempted are not attribution
            if isinstance(k, str) and k.endswith("attempt_id") \
                    and isinstance(v, str):
                yield v
            yield from _attempt_ids(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _attempt_ids(v)


for jf in sorted(COLLECTED.rglob("*.json")):
    if jf.name in ("terminal-reduction.json", "equality-reduction.json"):
        continue  # derived artifacts, not physical observations
    try:
        doc = json.loads(jf.read_text())
    except json.JSONDecodeError:
        problems.append(f"unparseable retained evidence: {jf.name}")
        continue
    unexpected = sorted(set(_attempt_ids(doc)) - _ALLOWED_ATTEMPT_IDS)
    if unexpected:
        problems.append(
            f"{jf.name}: unexpected attempt ids {unexpected[:3]}")

launch1_case_observations = [
    p.name for p in (COLLECTED / "direct").glob("*.json")
    if p.name.startswith("direct-c109-")
    and json.loads(p.read_text()).get("attempt_id")
    not in (None, AUTHORIZED_ATTEMPT)
    and json.loads(p.read_text()).get("attempt_id") is not None]
# (a direct case file naming ANY attempt other than the authorized one
# is already a defect above; launch-1 attribution is proven by the
# content binding to the launch-2 direct run plus the retained
# dependency failure log with zero launch-1 output.)
require(not launch1_case_observations,
        f"launch-1 correctness-bearing observations found: "
        f"{launch1_case_observations[:3]}")
# derived classification: launch 1 is PRE_OBSERVATION_INFRASTRUCTURE iff
# the dependency failure is retained AND no case/commit observation is
# attributable to it.
launch1_pre_observation = (launch1_dependency_failure
                           and not launch1_case_observations)
require(launch1_pre_observation,
        "launch-1 does not mechanically qualify as "
        "PRE_OBSERVATION_INFRASTRUCTURE")
# the authored field must AGREE with the derivation (it is not authority)
require(attempt.get("classification_at_emission")
        == "PRE_OBSERVATION_INFRASTRUCTURE",
        "authored launch-1 classification contradicts the derivation")

# ---- 3. direct arm ------------------------------------------------------------
require(direct_run["plan_digest"] == "sha256:a730405dab8bad2ee8c4eea9a4"
        "fb97b8ef53ea15415a4d904bf666d020cdc625",
        "direct plan digest drift")
require(not direct_run["comparator_contract"]
        ["single_shot_max_new_tokens_8_used"], "forbidden single-shot used")
require(direct_run["case_count"] == 24, "direct case count drift")
require(direct_run.get("attempt_id") == "armc-retry-physical-1",
        "direct run attempt attribution drift")
calls = 0
for t in direct_run["invocation_transcript"]:
    calls += len(t["calls"])
    for c in t["calls"]:
        if c["max_new_tokens"] != 2 or not c["on_token_present"]:
            problems.append(f"{t['case_id']}: invocation drift")
        if c["speculative_discarded"] and len(c["speculative_discarded"]) != 1:
            problems.append(f"{t['case_id']}: speculative discard drift")
require(calls == 24 * 8, f"direct invocation count {calls} != 192")
invariants["direct_invocations"] = calls
invariants["direct_comparator"] = (
    "per-token-replay max_new_tokens=2, step-0 commit, step-1 discard")

# ---- 4. ordinary arm ----------------------------------------------------------
epoch = serving["epochs"][0]
require(epoch["state"] == "RECLAIMED", "epoch not reclaimed")
sessions = epoch["runtime_sessions"]
require(len(sessions) == 200, f"runtime sessions {len(sessions)} != 200")
per_logical = defaultdict(int)
for s in sessions:
    sid = s.get("session_id")
    if not isinstance(sid, int) or isinstance(sid, bool):
        problems.append("runtime session id malformed")
        continue
    per_logical[sid // 1_000_000] += 1
    if s.get("plan_digest") != epoch["plan_digest"]:
        problems.append("session plan digest drift")
for logical, n in per_logical.items():
    if n != 8:
        problems.append(f"logical {logical}: {n} sessions != 8")
# frozen allocator sequence: logical L's eight runtime sessions are
# exactly L*1_000_000 + 8*(L-1)+1 .. L*1_000_000 + 8*L (r5b_epochs.py
# L417-419 global sequence; the direct arm allocates the identical ids)
for logical in sorted(per_logical):
    ids = [s.get("session_id", -1) for s in sessions
           if isinstance(s.get("session_id"), int)
           and s["session_id"] // 1_000_000 == logical]
    expected = [logical * 1_000_000 + 8 * (logical - 1) + j + 1
                for j in range(8)]
    if sorted(ids) != expected:
        problems.append(
            f"logical {logical}: runtime allocator sequence drift")
require(campaign["ok_count"] == 24 and len(campaign["records"]) == 24,
        "ordinary ok_count drift")
require(campaign.get("attempt_id") == "armc-retry-physical-1-ordinary",
        "ordinary campaign attempt attribution drift")
# coordinator instance identity across campaign, report, HTTP responses
instance = serving["coordinator_scope"]["instance_id"]
require(campaign["health"]["instance_id"] == instance,
        "coordinator instance id drift between campaign and report")
require(all(r["response"]["id"] == f"chatcmpl-{instance}"
            for r in campaign["records"]),
        "HTTP response ids do not bind to the coordinator instance")

# ---- 5. fencing/attribution zeros (DERIVED from commit records) ---------------
# Authority ladder per counter (strongest retained evidence named):
#   * commit attribution: coordinator_scope.requests[*].token_events (the
#     controller-copied commit mapping) cross-bound to sessions[*].
#     latest_committed_boundary — the coordinator's own per-session ledger.
#   * rejections: coordinator_scope.requests[24].fencing_arm_injections
#     (accepted:false) MIRRORED by serving-report.late_result_rejections
#     (fail-closed: both retained copies must agree).
creq = serving["coordinator_scope"]["requests"]
csess = {s["session_id"]: s for s in serving["sessions"]}
stale_session = wrong_session = stale_plan = wrong_plan = 0
stale_epoch = wrong_epoch = wrong_position = unattributed = 0
active_epoch = epoch["epoch_id"]
active_plan = epoch["plan_digest"]
rejection_mirrors = {r["envelope"]["injection"]: r
                     for r in serving.get("late_result_rejections", [])}
for r in creq:
    sid = r["session_id"]
    ledger = csess.get(sid)
    if ledger is None:
        problems.append(f"request session {sid} has no commit ledger")
        continue
    # committed id sequences must agree across all three retained copies
    ids_req = list(r["generated_token_ids"])
    ids_ledger = list(ledger["latest_committed_boundary"]
                      ["committed_generated_token_ids"])
    ids_events = [e["token_id"] for e in r["token_events"]]
    if not (ids_req == ids_ledger == ids_events):
        problems.append(f"session {sid}: committed id copies disagree")
    # prompt identity: request vs ledger boundary vs frozen fixture
    p_req = list(r["prompt_token_ids"])
    p_ledger = list(ledger["latest_committed_boundary"]["prompt_token_ids"])
    if p_req != p_ledger:
        problems.append(f"session {sid}: prompt copies disagree")
    if sid <= 24:
        fx = list(fixture["cases"][sid - 1]["rendered_prompt_token_ids"])
        if p_req != fx:
            problems.append(f"session {sid}: prompt != frozen fixture")
    # per-event attribution derivation
    for j, e in enumerate(r["token_events"]):
        if e["epoch_id"] != active_epoch:
            stale_epoch += 1
        if e["plan_digest"] != active_plan:
            wrong_plan += 1
        if e.get("generation") != epoch["generation"]:
            wrong_epoch += 1
        if e["position"] != j:
            wrong_position += 1
        if (e["epoch_id"] is None or e["plan_digest"] is None
                or e.get("position") is None
                or e.get("committed_at_ns") is None):
            unattributed += 1
    # ledger epoch/plan chains
    if any(x != active_epoch for x in r["committed_epoch_ids"]):
        stale_epoch += 1
    if any(x != active_plan for x in r["committed_plan_digests"]):
        stale_plan += 1
    # boundary position must be exactly the committed count
    b = ledger["latest_committed_boundary"]
    if b["committed_position"] != len(ids_req):
        problems.append(f"session {sid}: boundary position drift")
    # a stale-session commit = a commit landing under a superseded session
    # boundary: impossible when every event sits in the request's own
    # ordered ledger and the session-id sets match exactly.
    if b["session_id"] != sid:
        stale_session += 1
require(set(csess) == {r["session_id"] for r in creq},
        "coordinator session-id sets disagree")
# runtime sessions must attribute to exactly the 25 logical sessions
for s in sessions:
    if not isinstance(s.get("session_id"), int) or \
            s["session_id"] // 1_000_000 not in per_logical:
        wrong_session += 1

# controlled injections are NOT commits — proven by the retained rejection
# records on BOTH sides (coordinator request record and serving report).
injections = []
for r in creq:
    for inj in r.get("fencing_arm_injections", []):
        injections.append(inj)
        if inj.get("accepted") is not False:
            problems.append(
                "controlled fencing injection NOT rejected "
                f"({inj.get('injection')})")
# every coordinator-side rejected injection must be mirrored by exactly
# one serving-report late-result rejection on the same session; the
# envelope's own ``injection`` tag is the producer's generic envelope
# label (both controlled injections travel in
# CONTROLLED_LATE_REAL_SERVING_RESULT envelopes), so the mirror is bound
# by session id + the retained rejection-reason semantics (duplicate
# position / retired epoch), not by the envelope tag.
rejections_by_session = defaultdict(list)
for rej in serving.get("late_result_rejections", []):
    rejections_by_session[rej["envelope"].get("session_id")].append(rej)
for r in creq:
    for inj in r.get("fencing_arm_injections", []):
        mirrors = rejections_by_session.get(r["session_id"], [])
        ok_reasons = {"NON_NEXT_COMMIT_POSITION", "RETIRED_OR_SUPERSEDED_EPOCH"}
        if not any(m.get("reason") in ok_reasons for m in mirrors):
            problems.append(
                "coordinator-side injection rejection not mirrored in "
                "serving report")
require(len(injections) >= 2, "controlled fencing-injection proof missing")
invariants["stale_session_commits"] = stale_session
invariants["wrong_session_commits"] = wrong_session
invariants["stale_plan_commits"] = stale_plan
invariants["wrong_plan_commits"] = wrong_plan
invariants["stale_epoch_commits"] = stale_epoch
invariants["wrong_epoch_commits"] = wrong_epoch
invariants["wrong_position_commits"] = wrong_position
invariants["unattributed_correctness_bearing_commits"] = unattributed
invariants["controlled_fencing_injections_rejected"] = len(injections)
for k in ("stale_session_commits", "wrong_session_commits",
          "stale_plan_commits", "wrong_plan_commits", "stale_epoch_commits",
          "wrong_epoch_commits", "wrong_position_commits",
          "unattributed_correctness_bearing_commits"):
    if invariants[k]:
        problems.append(f"fencing nonzero counter: {k}={invariants[k]}")

# ---- 6. coordinator boundary (DERIVED: exact transport accounting --
# pinned executed producer semantics + process/state observations) -------
#
# Review 5173318161 P1: absence of /srv/models opens or persistent census
# entries does NOT exclude transient model/artifact receipt on the
# Coordinator's sockets.  The receive/materialization/bulk zeros are
# therefore derived from a mechanical transport accounting:
#
# (a) EXECUTED SOURCE IDENTITY.  coordinator-boundary-source-pins.json
#     pins the sha256 of every module that constructs or receives a
#     Coordinator-bound byte, byte-bound to the frozen producer
#     924cd22e (git blob == deployed participant trees == vendored
#     bytes; host preflights prove every tree clean at that HEAD and
#     the coordinator's own constructor re-verified it at process
#     start via _require_clean_exact_source; the pinned node-agent
#     strace records the agent opening exactly these deployed files).
# (b) RECEIVE SURFACE COMPLETENESS (AST over the pinned bytes): the
#     Coordinator process's only socket receive call is
#     xc_coordinator.RemoteEpochRuntime._request -> recv_frame (single
#     site) over ONE node-agent connection; every other network input
#     is the HTTP ingress (do_POST, bodies bounded to 4 MiB, all 25
#     retained verbatim).  Every Coordinator-bound wire frame is
#     CONSTRUCTED by node_agent.py at exactly two send_exact sites
#     (_accept_response / _reject) from metadata-only response records.
# (c) EXACT ENVELOPE ACCOUNTING.  The pinned r5b_epochs.py semantics
#     bound the exchange count: 1 REALIZE + one GENERATE response per
#     committed token (200 retained verbatim as
#     epochs[*].runtime_sessions) + 1 REPORT (retained as
#     final_runtime_report) + 1 CLOSE = 203 frames.  The 200 GENERATE
#     and 1 REPORT envelopes are re-encoded to their EXACT canonical
#     wire bytes from retained content; REALIZE/CLOSE results are not
#     retained verbatim and are accounted at the 24 MiB wire budget
#     bound under producer-semantics classification (their pinned
#     constructors are dict literals over observation/node_identity/
#     wall-ns and the runtime report -- no tensor passthrough exists).
#     Structural consequence: 203 frames x ~24 MiB < the 9.26 GB
#     participant checkpoint, so even adversarial max-size frames
#     cannot transport the model across this boundary.
# (d) VALUE CLASSIFICATION (fail-closed).  Every leaf of every
#     retained received payload is classified: ints/bools/None/floats
#     (timing statistics) = control metadata; a str > 512 chars or a
#     numeric list > 4096 entries = UNKNOWN potentially-bulk; a
#     base64/hex-blob-looking str or any bytes leaf = model payload.
#     An authoritative terminal additionally requires unknown == 0.
# (e) STATE CLASSIFICATION (no size threshold).  Census files are
#     classified by path/name against the executed coordinator's own
#     write set; the retained report/evidence/config files are
#     cross-bound to their census sizes; any other name = unclassified
#     defect.  The pre-census must be a subset of the post-census (a
#     file present before and gone after = deleted state = defect).
#     The invented 1-GiB BULK_THRESHOLD is removed entirely.
# (f) MATERIALIZATION.  Receipt == 0 (above) AND the coordinator-
#     process closure imports no torch/numpy/safetensors/triton (AST)
#     AND constructs no raw socket outside the pinned adapter AND
#     pre/post process maps show no libtorch and no CUDA env AND the
#     census holds no artifact-class file => materialized == 0,
#     derived not inferred from persistent-file absence.

import ast  # noqa: E402

# 6a. executed-source identity of the boundary closure
_boundary_files = boundary_pins.get("files", {})
require(bool(_boundary_files),
        "coordinator boundary source pins absent")
for rel, meta in sorted(_boundary_files.items()):
    actual = sha256_file(EVIDENCE / "frozen-source/924cd22e" / rel)
    require(actual == meta.get("file_sha256"),
            f"coordinator boundary source drift: {rel}")
require(boundary_pins.get("frozen_producer") == FROZEN_PRODUCER,
        "boundary pins do not bind the frozen producer")
require(boundary_pins.get("executed_binding", {})
        .get("post_run_deployed_reconciliation", {}).get("matched") is True,
        "boundary pins lack the deployed-tree reconciliation")


def _ast_of(rel):
    return ast.parse((EVIDENCE / "frozen-source/924cd22e" / rel)
                     .read_text())


def _call_sites(tree, name):
    return sorted(
        node.lineno for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and (getattr(node.func, "id", None) == name
             or getattr(node.func, "attr", None) == name))


# 6b. receive-surface completeness over the exact pinned bytes
_node_agent_ast = _ast_of("benchmarks/inferswarm_r6/node_agent.py")
_xc_coord_ast = _ast_of("python/freetoken/research/xc_coordinator.py")
_xc_wire_ast = _ast_of("python/freetoken/research/xc_wire.py")
require(_call_sites(_node_agent_ast, "send_exact") == [63, 87],
        "node_agent send_exact site set drifted (expected exactly the "
        "_reject and _accept_response constructions)")
require(_call_sites(_xc_coord_ast, "recv_frame") == [96],
        "coordinator receive site set drifted (expected the single "
        "RemoteEpochRuntime._request recv_frame)")
require(_call_sites(_xc_wire_ast, "recv_into") == [109],
        "wire read loop site drifted (expected the single read_exact "
        "recv_into)")
# the coordinator-process closure imports no tensor library and
# constructs no raw socket; the tokenizer (transformers) is the frozen
# #133-sanctioned exception, imported lazily for the local assets only
_COORD_PROCESS_MODULES = (
    "benchmarks/inferswarm_r6/coordinator.py",
    "python/freetoken/research/xc_coordinator.py",
    "python/freetoken/research/xc_wire.py",
    "python/freetoken/research/r5b_epochs.py",
    "python/freetoken/research/r5a_serving.py",
    "python/freetoken/research/r3_planner.py",
    "benchmarks/inferswarm_r6/strategy.py",
    "benchmarks/inferswarm_r6/xc_strategy.py",
    "benchmarks/inferswarm_xc/cpu_only.py",
)
for _rel in _COORD_PROCESS_MODULES:
    _tree = _ast_of(_rel)
    for _node in ast.walk(_tree):
        _roots = set()
        if isinstance(_node, ast.Import):
            _roots = {a.name.split(".")[0] for a in _node.names}
        elif isinstance(_node, ast.ImportFrom) and _node.module:
            _roots = {_node.module.split(".")[0]}
        _bad = _roots & {"torch", "numpy", "safetensors", "triton",
                         "tensor"}
        require(not _bad, f"{_rel} imports {_bad}")
    require(not _call_sites(_tree, "socket"),
            f"{_rel} constructs a raw socket")

# 6c. exact envelope accounting over retained content
_WIRE_HEADER_BYTES = 10  # struct "<4sHI" per the pinned xc_wire.py
_BUDGET = 24 * 1024 * 1024
_B64_RE = re.compile("[A-Za-z0-9+/=]+")
_TENSOR_RE = re.compile("[\\x00-\\x08\\x0e-\\x1f]{8,}")


def _classify_leaf(value, stats):
    if isinstance(value, bool) or value is None:
        stats["control_metadata"] += 1
    elif isinstance(value, int):
        stats["control_metadata"] += 1
    elif isinstance(value, float):
        stats["control_metadata"] += 1  # timing statistics
    elif isinstance(value, str):
        raw = value.encode()
        if len(value) > 256 and _B64_RE.fullmatch(value):
            # a base64-charset blob of any size is payload, never
            # absorbed as ordinary metadata (no retained control/
            # result string legitimately looks like this)
            stats["model_payload"] += len(raw)
        elif len(value) > 512:
            stats["unknown"] += len(raw)
        elif _TENSOR_RE.search(raw[:4096].decode("utf-8", errors="ignore")):
            stats["model_payload"] += len(raw)
        else:
            stats["control_metadata"] += len(raw)
    elif isinstance(value, bytes):
        stats["model_payload"] += len(value)
    else:
        stats["unknown"] += 1


def _classify_tree(value, stats):
    if isinstance(value, dict):
        for v in value.values():
            _classify_tree(v, stats)
    elif isinstance(value, list):
        numeric = all(isinstance(v, (int, float))
                      and not isinstance(v, bool) for v in value)
        if numeric and len(value) > 4096:
            stats["unknown"] += len(value) * 8
        else:
            for v in value:
                _classify_tree(v, stats)
    else:
        _classify_leaf(value, stats)


def _account_envelope(envelope):
    """Exact canonical wire bytes (mirrors xc_wire.canonical_body +
    header) and per-class byte accounting of one retained envelope."""
    data = json.dumps(envelope, sort_keys=True,
                      separators=(",", ":")).encode()
    stats = {"control_metadata": 0, "model_payload": 0, "unknown": 0}
    _classify_tree(envelope, stats)
    return _WIRE_HEADER_BYTES + len(data), stats


wire_meta_bytes = 0
wire_payload_bytes = 0
wire_unknown_bytes = 0
wire_frames = 0
_ep = serving["epochs"][0]
_authz = _ep.get("realization_authorization", {})
_envelope_common = {
    "kind": "response",
    "protocol": "inferswarm.external-coordinator.realization-wire/1",
    "scope_id": serving["coordinator_scope"].get("scope_id"),
    "epoch_id": _ep.get("epoch_id"),
    "generation": _ep.get("generation"),
    "realization_id": _authz.get("realization_id"),
    "plan_digest": _ep.get("plan_digest"),
    "ok": True,
}
_position = 0
for s in sessions:
    _position += 1  # RemoteEpochRuntime._operation_sequence: 1..200
    env = dict(_envelope_common)
    env.update({
        "operation": "GENERATE",
        "session_id": s.get("session_id"), "position": _position,
        "result": s,
        "result_checksum": "sha256:" + hashlib.sha256(
            json.dumps(s, sort_keys=True,
                       separators=(",", ":")).encode()).hexdigest()})
    fb, stats = _account_envelope(env)
    wire_frames += 1
    wire_meta_bytes += fb
    wire_payload_bytes += stats["model_payload"]
    wire_unknown_bytes += stats["unknown"]
# REPORT exchange: result retained verbatim as final_runtime_report;
# a missing/failed final report is missing transport evidence
require(isinstance(_ep.get("final_runtime_report"), dict)
        and bool(_ep.get("final_runtime_report"))
        and _ep.get("runtime_report_failure") is None,
        "coordinator REPORT transport evidence absent or failed")
fb, stats = _account_envelope(
    {**_envelope_common, "operation": "REPORT", "result":
     _ep.get("final_runtime_report", {})})
wire_frames += 1
wire_meta_bytes += fb
wire_payload_bytes += stats["model_payload"]
wire_unknown_bytes += stats["unknown"]
# REALIZE and CLOSE results are not retained verbatim: accounted at the
# wire-body budget bound with producer-semantics classification (their
# pinned constructors emit metadata-only records; no payload family
# exists at those sites).  Budget-bound bytes are part of the
# structural bound, never counted as a payload zero.
wire_frames += 2
wire_meta_bytes += 2 * (_WIRE_HEADER_BYTES + _BUDGET)
_structural_bound = wire_meta_bytes
_checkpoint_bytes = 9256814624  # participant stage report (fetched_bytes)
require(_structural_bound < _checkpoint_bytes,
        "structural bound no longer excludes checkpoint transport")

# 6d. HTTP ingress accounting (bodies bounded by the pinned coordinator;
# every leaf classified with the same fail-closed classifier as the wire
# payloads — a smuggled payload in a request body is payload, not
# metadata)
http_meta_bytes = 0
http_payload_bytes = 0
http_unknown_bytes = 0
_HTTP_BODY_BUDGET = 4 * 1024 * 1024  # pinned coordinator.py do_POST bound
for r in campaign["records"]:
    body = json.dumps(r.get("request_body", {}), sort_keys=True,
                      separators=(",", ":")).encode()
    require(len(body) <= _HTTP_BODY_BUDGET,
            "ordinary HTTP request body exceeds the pinned 4 MiB "
            "coordinator ingress bound")
    stats = {"control_metadata": 0, "model_payload": 0, "unknown": 0}
    _classify_tree(r.get("request_body", {}), stats)
    http_meta_bytes += len(body)
    http_payload_bytes += stats["model_payload"]
    http_unknown_bytes += stats["unknown"]
fence_body = json.dumps(fencing_arm.get("request_body", {}),
                        sort_keys=True,
                        separators=(",", ":")).encode()
require(len(fence_body) <= _HTTP_BODY_BUDGET,
        "fencing HTTP request body exceeds the pinned 4 MiB ingress "
        "bound")
_fstats = {"control_metadata": 0, "model_payload": 0, "unknown": 0}
_classify_tree(fencing_arm.get("request_body", {}), _fstats)
http_meta_bytes += len(fence_body)
http_payload_bytes += _fstats["model_payload"]
http_unknown_bytes += _fstats["unknown"]

# 6e. state census classification (name/type; NO size threshold)
census_unknown = []
census_class = {}
for phase, obs in (("pre", coord_pre), ("post", coord_post)):
    for path, meta in obs.get("state_census", {}).items():
        census_class[(phase, path)] = meta.get("size", 0)
_ALLOWED_CENSUS = (
    "coordinator-config.json", "coordinator.log",
    "coordinator-observation-pre.json",
    "coordinator-observation-post.json", "serving-evidence.json",
    "serving-report.json", "serving-report.json.sha256",
    "lifecycle/serving-report.json", "lifecycle/serving-report.json.sha256")
for (phase, path), size in census_class.items():
    if not path.startswith("/srv/inferswarm/state/arm-c-retry-ordinary/"):
        census_unknown.append(f"{phase}:{path}")
        continue
    tail = path[len("/srv/inferswarm/state/arm-c-retry-ordinary/"):]
    if tail not in _ALLOWED_CENSUS:
        census_unknown.append(f"{phase}:{path}")
require(not census_unknown,
        f"coordinator census has unclassified entries: "
        f"{census_unknown[:4]}")
# no coordinator state file may disappear during the window
_pre_paths = {p for (ph, p) in census_class if ph == "pre"}
_post_paths = {p for (ph, p) in census_class if ph == "post"}
require(_pre_paths <= _post_paths,
        f"coordinator state files deleted during window: "
        f"{sorted(_pre_paths - _post_paths)[:3]}")
# cross-bind census sizes to the retained bytes.  The post-census was
# observed BEFORE the final SIGTERM close write (reclamation records
# land in the last write_json_with_sha), so the retained final report
# is a legitimate superset: the census-observed size must be <= the
# retained size, and the intermediate content must be a prefix-stable
# report (same schema/instance; final adds reclamation fields only).
# Every other cross-bound file must match exactly.
for rel, census_tail in (
        ("ordinary-http/coordinator-config.json",
         "coordinator-config.json"),
        ("ordinary-http/serving-evidence.json", "serving-evidence.json")):
    retained = (COLLECTED / rel).stat().st_size
    observed = census_class.get(
        ("post", "/srv/inferswarm/state/arm-c-retry-ordinary/"
         + census_tail))
    require(observed == retained,
            f"census size drift for {census_tail}: {observed} != "
            f"{retained}")
_retained_report = (COLLECTED / "ordinary-http/serving-report.json")
_observed_report = census_class.get(
    ("post", "/srv/inferswarm/state/arm-c-retry-ordinary/"
     "lifecycle/serving-report.json"))
require(_observed_report is not None
        and _observed_report <= _retained_report.stat().st_size,
        f"serving-report census binding failed: {_observed_report} vs "
        f"{_retained_report.stat().st_size}")

# 6f. process observations
cuda_initialized = 0
libtorch_maps = 0
for phase, obs in (("pre", coord_pre), ("post", coord_post)):
    require(obs.get("nvidia_devices_present") is False,
            f"coordinator host exposes nvidia devices ({phase})")
    for p in obs["processes"]:
        if p.get("cuda_env_keys"):
            cuda_initialized += len(p["cuda_env_keys"])
        if p.get("maps_libtorch"):
            libtorch_maps += 1
        if p.get("maps_mentions_cuda_or_nvidia"):
            cuda_initialized += 1

# 6g-bis. census size bounds: an allowed NAME is not a license for an
# arbitrary SIZE.  Every census entry is bounded:
#   * retained cross-bound files: exact size (above) or superset bound;
#   * the sha256 sidecar: exactly 86 bytes ("sha256:" + 64 hex + newline);
#   * coordinator.log: bounded by the pinned coordinator's real output
#     (two startup lines, KB-scale; anything bulk-sized under this name
#     is a materialized artifact and fails the window).  The observed
#     log sizes (150/286 bytes pre/post) bound the cap at 64 KiB.
_LOG_CAP = 64 * 1024
_SIDECAR_SIZE = 86
for (phase, path), size in census_class.items():
    if path.endswith("coordinator.log"):
        require(size <= _LOG_CAP,
                f"coordinator.log census size {size} exceeds the "
                f"code-derived cap ({phase})")
    elif path.endswith(".sha256"):
        require(size == _SIDECAR_SIZE,
                f"sha256 sidecar census size {size} != {_SIDECAR_SIZE} "
                f"({phase})")

# 6g. the four zero invariants, derived (received = wire-classified
# payload + HTTP-ingress-classified payload; bulk = same totals)
invariants["coordinator_cuda_initialized"] = cuda_initialized
invariants["coordinator_model_weight_bytes_received"] = (
    wire_payload_bytes + http_payload_bytes)
invariants["coordinator_model_weight_bytes_materialized"] = libtorch_maps
invariants["coordinator_bulk_artifact_bytes_observed"] = (
    wire_payload_bytes + http_payload_bytes)
invariants["coordinator_wire_frames_accounted"] = wire_frames
invariants["coordinator_wire_metadata_bytes_accounted"] = wire_meta_bytes
invariants["coordinator_http_ingress_metadata_bytes"] = http_meta_bytes
invariants["coordinator_unclassified_wire_bytes"] = (
    wire_unknown_bytes + http_unknown_bytes)
invariants["coordinator_unclassified_census_entries"] = len(census_unknown)
for k in ("coordinator_cuda_initialized",
          "coordinator_model_weight_bytes_received",
          "coordinator_model_weight_bytes_materialized",
          "coordinator_bulk_artifact_bytes_observed",
          "coordinator_unclassified_wire_bytes",
          "coordinator_unclassified_census_entries"):
    if invariants[k]:
        problems.append(f"coordinator zero invariant nonzero: {k}="
                        f"{invariants[k]}")

# ---- 7. equality + invocation seam -------------------------------------------
# The equality reduction must be the /2 schema with the mechanical
# pre-divergence invocation-equivalence proof; a semantic FAIL is legal
# only when the mismatch was produced from otherwise equivalent frozen
# model-execution inputs.
eq_schema_ok = equality.get("schema") == (
    "inferswarm.issue133.arm-c-retry.equality-reduction/2")
if not eq_schema_ok:
    problems.append("equality reduction is not the corrected /2 schema")
inv_equiv = equality.get("invocation_equivalence", {})
invocation_equivalence_holds = bool(inv_equiv.get("holds"))
if not invocation_equivalence_holds:
    problems.append(
        "pre-divergence invocation equivalence not mechanically proven")
http_char = equality.get("http_content_characterization", {})
if not http_char.get("all_bind_frozen_incremental_decode"):
    problems.append(
        "ordinary HTTP content not characterized against the frozen "
        "incremental decoding algorithm")
# cross-bind the equality rows to the raw per-case evidence AND derive
# the semantic comparison from the raw id lists in hand (review-2 P1
# hardening: the authored equality verdict fields — passed,
# committed_ids_equal, equal_count — are NOT authority; the reducer
# recomputes them from the direct case file and the coordinator request
# record it loads itself).
derived_equal_count = 0
derived_mismatched = []
for row in equality.get("rows", []):
    cid = row.get("case_id")
    dcase_path = COLLECTED / "direct" / f"direct-{cid}.json"
    if not dcase_path.is_file():
        problems.append(f"equality row {cid}: no direct case file")
        continue
    dcase = json.loads(dcase_path.read_text())
    if list(row.get("direct_committed_token_ids", [])) != list(
            dcase["generated_token_ids"]):
        problems.append(
            f"equality row {cid}: direct ids not bound to case file")
    logical = row.get("logical_session")
    req = next((r for r in creq if r["session_id"] == logical), None)
    if req is None:
        problems.append(f"equality row {cid}: no ordinary request")
        continue
    if list(row.get("ordinary_committed_token_ids", [])) != list(
            req["generated_token_ids"]):
        problems.append(
            f"equality row {cid}: ordinary ids not bound to request")
    row_equal = (list(dcase["generated_token_ids"])
                 == list(req["generated_token_ids"]))
    if row_equal:
        derived_equal_count += 1
    else:
        derived_mismatched.append(cid)
    # an authored row verdict that contradicts the raw bytes is an
    # evidence-integrity problem, never silently accepted
    if bool(row.get("committed_ids_equal")) != row_equal:
        problems.append(
            f"equality row {cid}: authored committed_ids_equal "
            "contradicts raw committed ids")
if equality.get("equal_count") != derived_equal_count:
    problems.append(
        "authored equal_count contradicts raw committed-id comparison")
mismatched = [{"case_id": c} for c in derived_mismatched]
equality_all_equal = (derived_equal_count == len(equality.get("rows", []))
                      and len(equality.get("rows", [])) == 24)
regime4 = all(r["case_id"].startswith("c109-04") for r in mismatched)

# ---- 8. terminal classification ----------------------------------------------
# Narrowest-first: any invariant/evidence failure preempts a semantic
# verdict (an ordinary semantic mismatch must never mask one).
terminal = None
if any("fencing nonzero counter" in p or "coordinator zero invariant" in p
       for p in problems):
    terminal = blocker_class("ISSUE117_ARM_C_FENCING_OR_COORDINATOR_"
                             "INVARIANT_FAILURE")
elif any("pre-divergence invocation equivalence" in p for p in problems):
    terminal = blocker_class("ISSUE117_ARM_C_INVOCATION_EQUIVALENCE_"
                             "UNPROVEN")
elif any("HTTP content not characterized" in p for p in problems):
    terminal = blocker_class("ISSUE117_ARM_C_HTTP_CONTENT_EVIDENCE_"
                             "DEFECT")
elif problems:
    terminal = blocker_class("ISSUE117_ARM_C_INVARIANT_FAILURE")
elif equality_all_equal:
    terminal = "ISSUE117_ARM_C_ORDINARY_SERVING_PASS"
else:
    terminal = "ISSUE117_ARM_C_ORDINARY_SERVING_FAIL"

result = {
    "schema": "inferswarm.issue133.arm-c-retry.terminal-reduction/3",
    "campaign_id": CAMPAIGN,
    "execution_freeze_identity": FREEZE,
    "attempt_id": facts["attempt_id"],
    "review_correction": {
        "maintainer_review": 5173318161,
        "reviewed_head": "455557a85351a1cc4102f407b335f3ed7ee84a44",
        "prior_corrections": [
            {"maintainer_review": 5172615768,
             "reviewed_head": "51980fb78006699bfc460e68c0b7b646ddc26d74",
             "corrections": [
                 "terminal gates on every mandatory #133 invariant family",
                 "all zero counters derived from retained observations",
                 "launch-1 PRE_OBSERVATION_INFRASTRUCTURE derived from "
                 "bytes",
                 "equality /2 with mechanical pre-divergence invocation "
                 "equivalence required for semantic FAIL",
                 "HTTP-content discrepancy characterized from frozen "
                 "bytes",
             ]},
        ],
        "corrections": [
            "P1: coordinator receive/materialization/bulk zeros derived "
            "from exact transport accounting (pinned executed producer "
            "identity + AST receive-surface completeness + exact wire "
            "envelope reconstruction from retained payloads + fail-closed "
            "value classification + census classification by name, no "
            "size threshold; 1-GiB BULK_THRESHOLD removed)",
            "P2: fail-closed attempt attribution — every direct/ordinary "
            "per-case observation binds by full content identity to its "
            "attempt-attributed aggregate; null/missing/wrong attempt_id "
            "fails closed; no unexpected attempt ids anywhere in the "
            "retained tree",
        ],
    },
    "direct_arm": {"cases": direct_run["case_count"],
                   "plan_digest": direct_run["plan_digest"]},
    "ordinary_arm": {"cases": campaign["ok_count"],
                     "epoch_state": epoch["state"]},
    "launch_lineage": {
        "launch1_dependency_failure": launch1_dependency_failure,
        "launch1_case_observations": launch1_case_observations,
        "launch1_derived_classification":
            "PRE_OBSERVATION_INFRASTRUCTURE" if launch1_pre_observation
            else None,
        "launch1_derivation": "attempts/launch1-failure.log retained "
        "ModuleNotFoundError(tvm_ffi) + execution-plan.launch1.json + "
        "zero launch-1-attributed case/commit observations",
    },
    "equality": {"equal": derived_equal_count,
                 "of": equality.get("case_count"),
                 "mismatched_cases": [r["case_id"] for r in mismatched],
                 "all_mismatches_regime_4": regime4,
                 "first_divergent_positions":
                     inv_equiv.get("first_divergent_positions"),
                 "pre_divergence_invocation_equivalence":
                     invocation_equivalence_holds},
    "http_content": {
        "all_bind_frozen_incremental_decode":
            http_char.get("all_bind_frozen_incremental_decode"),
        "cases_differing_from_one_shot_decode":
            http_char.get("cases_differing_from_one_shot_decode"),
        "classification": http_char.get("classification"),
    },
    "zero_invariants": invariants,
    "coordinator_boundary": {
        "executed_source_pins":
            "coordinator-boundary-source-pins.json (12 modules, each "
            "sha256-pinned, bound to frozen producer 924cd22e == git "
            "blob == deployed participant trees)",
        "receive_surface": "AST over pinned bytes: single coordinator "
                           "recv_frame site (xc_coordinator L96) + HTTP "
                           "do_POST (25 retained bodies); node_agent "
                           "sends at exactly L63/L87",
        "wire_frames_accounted": wire_frames,
        "wire_bytes_exact_or_bound": wire_meta_bytes,
        "structural_bound_bytes": _structural_bound,
        "structural_vs_checkpoint":
            f"{_structural_bound} < {_checkpoint_bytes} "
            "(checkpoint cannot cross the boundary even at max-size "
            "frames)",
        "http_ingress_metadata_bytes": http_meta_bytes,
        "census_files_classified": len(census_class),
        "value_classes": "control_metadata / model_payload / unknown "
                         "(fail-closed; unknown==0 required)",
    },
    "invariant_evidence": {
        "fencing_attribution": "coordinator_scope.requests[*]."
        "token_events + sessions[*].latest_committed_boundary + dual-"
        "retained injection rejection records",
        "coordinator": "exact transport accounting: "
        "coordinator-boundary-source-pins.json + AST receive-surface "
        "completeness + 200 retained GENERATE wire results + "
        "final_runtime_report + coordinator-observation-{pre,post}.json "
        "processes/devices/state_census (name-classified, pre<=post)",
        "substrate": "substrate-reconciliation-{01,03}.json",
        "tokenizer": "tokenizer-deployment-proof.json + frozen asset pins",
        "prelaunch": "prelaunch-verdict-{run1,immediate-prelaunch}.json",
        "attempt_attribution": "direct-run.json/ordinary-campaign.json "
        "attempt_id + full content identity of all 48 per-case files "
        "to their attributed aggregates + tree-wide attempt-id census",
    },
    "problems": problems,
    "terminal": terminal,
    "derivation": "all values re-derived from retained raw evidence in "
                  "this repository; no authored summary consumed; no "
                  "terminal-authority value is an assigned constant",
}
print(json.dumps(result, indent=2, sort_keys=True))
sys.exit(0)
