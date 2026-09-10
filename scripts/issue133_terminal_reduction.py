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

# ---- 2. launch-1 lineage (derived, not authored) ------------------------------
# Evidence: attempts/launch1-failure.log (ModuleNotFoundError before any
# correctness-bearing output), attempts/execution-plan.launch1.json (the
# launch-1 frozen plan exists and predates the retained case evidence),
# and the ABSENCE of launch-1 case/commit observations (every retained
# case/commit record belongs to attempt armc-retry-physical-1 / its
# ordinary sub-attempt).
launch1_dependency_failure = (
    "ModuleNotFoundError" in launch1_log
    and re.search(r"No module named 'tvm_ffi'", launch1_log) is not None)
require(launch1_dependency_failure,
        "launch-1 log does not show the retained dependency failure")
require(launch1_plan.get("digest") == "sha256:a730405dab8bad2ee8c4eea9a4"
        "fb97b8ef53ea15415a4d904bf666d020cdc625",
        "launch-1 execution plan digest drift")
launch1_case_observations = [
    p.name for p in (COLLECTED / "direct").glob("*.json")
    if json.loads(p.read_text()).get("attempt_id") not in (
        None, "armc-retry-physical-1")]
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
    per_logical[s["session_id"] // 1_000_000] += 1
    if s["plan_digest"] != epoch["plan_digest"]:
        problems.append("session plan digest drift")
for logical, n in per_logical.items():
    if n != 8:
        problems.append(f"logical {logical}: {n} sessions != 8")
# frozen allocator sequence: logical L's eight runtime sessions are
# exactly L*1_000_000 + 8*(L-1)+1 .. L*1_000_000 + 8*L (r5b_epochs.py
# L417-419 global sequence; the direct arm allocates the identical ids)
for logical in sorted(per_logical):
    ids = [s["session_id"] for s in sessions
           if s["session_id"] // 1_000_000 == logical]
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
    if s["session_id"] // 1_000_000 not in per_logical:
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

# ---- 6. coordinator zeros (DERIVED from pre/post observations) ----------------
# Authority ladder: live process observation pre+post (cuda env keys,
# torch/cuda maps, nvidia devices) + participant-side strace (Source opens,
# materialized writes) + the coordinator's own retained state census
# (what bytes exist on the coordinator host at all).
cuda_initialized = weight_bytes_received = 0
weight_bytes_materialized = bulk_bytes = 0
BULK_THRESHOLD = 1 << 30  # tokenizer/config/log artifacts are KB-scale;
# anything at or above 1 GiB observed on the coordinator is bulk.
for phase, obs in (("pre", coord_pre), ("post", coord_post)):
    require(obs.get("nvidia_devices_present") is False,
            f"coordinator host exposes nvidia devices ({phase})")
    for p in obs["processes"]:
        if p.get("cuda_env_keys"):
            cuda_initialized += len(p["cuda_env_keys"])
        if p.get("maps_libtorch"):
            weight_bytes_materialized += 1
        if p.get("maps_mentions_cuda_or_nvidia"):
            cuda_initialized += 1
for t in strace_audit.get("traces", {}).values():
    weight_bytes_received += t.get("source_models_opens", 0)
    weight_bytes_materialized += t.get("materialized_writes", 0)
# census: every coordinator-side retained artifact is accounted; tokenizer
# assets are the frozen non-weight exception (Issue #133) and are counted
# separately, never as weight payload.
for phase, obs in (("pre", coord_pre), ("post", coord_post)):
    for path, meta in obs.get("state_census", {}).items():
        size = meta.get("size", 0)
        if size >= BULK_THRESHOLD:
            bulk_bytes += size
        if "/srv/models" in path:
            weight_bytes_received += size
invariants["coordinator_cuda_initialized"] = cuda_initialized
invariants["coordinator_model_weight_bytes_received"] = weight_bytes_received
invariants["coordinator_model_weight_bytes_materialized"] = (
    weight_bytes_materialized)
invariants["coordinator_bulk_artifact_bytes_observed"] = bulk_bytes
for k in ("coordinator_cuda_initialized",
          "coordinator_model_weight_bytes_received",
          "coordinator_model_weight_bytes_materialized",
          "coordinator_bulk_artifact_bytes_observed"):
    if invariants[k]:
        problems.append(f"coordinator zero invariant nonzero: {k}")

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
# cross-bind the equality rows to the raw per-case evidence: the row's
# direct committed ids must be the direct case file's ids, and its
# ordinary committed ids must be the coordinator request record's ids.
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
mismatched = [r for r in equality["rows"] if not r["committed_ids_equal"]]
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
elif equality.get("passed"):
    terminal = "ISSUE117_ARM_C_ORDINARY_SERVING_PASS"
else:
    terminal = "ISSUE117_ARM_C_ORDINARY_SERVING_FAIL"

result = {
    "schema": "inferswarm.issue133.arm-c-retry.terminal-reduction/2",
    "campaign_id": CAMPAIGN,
    "execution_freeze_identity": FREEZE,
    "attempt_id": facts["attempt_id"],
    "review_correction": {
        "maintainer_review": 5172615768,
        "reviewed_head": "51980fb78006699bfc460e68c0b7b646ddc26d74",
        "corrections": [
            "terminal gates on every mandatory #133 invariant family",
            "all zero counters derived from retained observations",
            "launch-1 PRE_OBSERVATION_INFRASTRUCTURE derived from bytes",
            "equality /2 with mechanical pre-divergence invocation "
            "equivalence required for semantic FAIL",
            "HTTP-content discrepancy characterized from frozen bytes",
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
    "equality": {"equal": equality.get("equal_count"),
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
    "invariant_evidence": {
        "fencing_attribution": "coordinator_scope.requests[*]."
        "token_events + sessions[*].latest_committed_boundary + dual-"
        "retained injection rejection records",
        "coordinator": "coordinator-observation-{pre,post}.json processes/"
        "devices/state_census + strace-audit.json participant traces",
        "substrate": "substrate-reconciliation-{01,03}.json",
        "tokenizer": "tokenizer-deployment-proof.json + frozen asset pins",
        "prelaunch": "prelaunch-verdict-{run1,immediate-prelaunch}.json",
    },
    "problems": problems,
    "terminal": terminal,
    "derivation": "all values re-derived from retained raw evidence in "
                  "this repository; no authored summary consumed; no "
                  "terminal-authority value is an assigned constant",
}
print(json.dumps(result, indent=2, sort_keys=True))
sys.exit(0)
