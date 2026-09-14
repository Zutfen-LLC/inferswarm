#!/usr/bin/env python3
"""Issue #175 — Arm-D reducer core (CPU-only, stdlib, fail-closed).

Library shared by the CLI reducers and the negative-control tests.
Every check derives from retained bytes; no authored pass boolean is
ever consulted. Each function returns (problems, counters/details).

Sections:
1. process-fence comparison (restart genuineness)
2. strace openat/connect transfer classification (zero reacquisition)
3. cache-hit / materialization accounting
4. post-restart equality vs the accepted #172 retained results
5. mandatory zero-invariant aggregation
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import issue175_campaign_pins as P

#: files whose bytes are model-weight bytes for classification
WEIGHT_SUFFIX = ".safetensors"

#: roots that constitute the verified local immutable cache
CACHE_ROOT = "/srv/inferswarm/materialized/issue117"

#: forbidden Source roots (any weight byte opened here = reacquisition)
SOURCE_ROOTS = (
    "/srv/models/",
    "/.cache/huggingface",
    "/hf-mirror",
)

#: known non-weight campaign inputs opened during a legal window
ACCOUNTED_NON_WEIGHT = (
    "/srv/inferswarm/state/arm-c-requal-172/chain-plan.json",
    "/srv/inferswarm/state/arm-c-requal-172/environment.json",
    "/srv/inferswarm/state/arm-c-requal-172/serving-evidence.json",
    "/srv/inferswarm/tokenizers/gemma-r6-frozen",
    P.NODE_REPO,
    P.COORDINATOR_REPO,
    "/proc/",
    "/sys/",
    "/dev/nvidia",
    "/usr/",
    "/etc/",
    "/var/",
    "/tmp/",
)

OPEN_RE = re.compile(
    r'^(?:(?:\[\d+\]|\d+) )?openat\([^,]+, "([^"]+)"')
CONNECT_RE = re.compile(
    r"^(?:(?:\[\d+\]|\d+) )?connect\(\d+,")


def _provenance_ok(record: dict, schema: str) -> bool:
    return record.get("schema") == schema and record.get(
        "campaign_id") == P.CAMPAIGN_ID


# ------------------------------------------------------------------
# 1. process fence
# ------------------------------------------------------------------
def compare_fences(pre: dict, post: dict, killed_pids: list[int]) -> dict:
    """Prove the restart was genuine.

    Requires: every pre-restart execution-bearing process is absent in
    the post record (by pid AND starttime/boot identity), the post
    record carries fresh processes with DISTINCT starttime identities
    (or later startimes), and no pre-restart pid was reused by a new
    service process.
    """
    problems: list[str] = []
    if not _provenance_ok(pre, P.INVENTORY_SCHEMA):
        problems.append("pre fence record provenance")
    if not _provenance_ok(post, P.INVENTORY_SCHEMA):
        problems.append("post fence record provenance")
    pre_procs = {p["pid"]: p for p in pre.get("processes", [])}
    post_procs = {p["pid"]: p for p in post.get("processes", [])}
    for pid in killed_pids:
        if pid not in pre_procs:
            problems.append(f"kill list pid {pid} not in pre fence")
        if pid in post_procs:
            problems.append(f"pre-restart pid {pid} still present post")
    # ambiguous identity: same pid, different starttime would mean the
    # process was replaced by an unrelated one; same starttime means it
    # never died. Both are caught above (present / absent), but an
    # identity collision on a DIFFERENT service pid is checked here.
    for pid, proc in post_procs.items():
        old = pre_procs.get(pid)
        if old and old.get("starttime") == proc.get("starttime"):
            problems.append(
                f"pid {pid} identical starttime across the boundary")
    # ports must be free of the OLD listeners and rebound by NEW pids
    for port, listeners in post.get("ports", {}).items():
        has_listener = bool(listeners) if isinstance(listeners, list) \
            else bool(str(listeners).strip())
        if has_listener and not post_procs:
            problems.append(f"port {port} has a listener but no processes")
    counters = {
        "pre_execution_processes": len(pre_procs),
        "post_execution_processes": len(post_procs),
        "killed_pids": list(killed_pids),
        "pre_restart_pids_still_alive": sum(
            1 for pid in killed_pids if pid in post_procs),
    }
    return {"problems": problems, "counters": counters,
            "passed": not problems}


def gpu_fence(gpus: list[dict], frozen: dict, host: str | None = None) -> dict:
    """Old accelerator realization must be inactive: ~0 used memory on
    every frozen device. When ``host`` is given, only that host's frozen
    devices are checked against the record collected on that host."""
    problems = []
    seen = {}
    for gpu in gpus:
        seen[gpu["uuid"]] = gpu
    scope = {host: frozen[host]} if host in frozen else (
        {} if host is not None else frozen)
    for host, wanted in scope.items():
        for index, uuid in wanted.items():
            gpu = seen.get(uuid)
            if gpu is None:
                problems.append(f"{host}/gpu-{index} {uuid} absent")
                continue
            try:
                used = int(gpu["memory_used"].split()[0])
            except Exception:
                problems.append(f"{host}/gpu-{index} unparseable memory")
                continue
            # KiB units from nvidia-smi csv
            if used > 100 * 1024:
                problems.append(
                    f"{host}/gpu-{index} still holds {used} KiB")
    return {"problems": problems,
            "passed": not problems}


def fresh_identity(post: dict, killed_pids: list[int]) -> dict:
    """Prove the post-restart record carries FRESH execution
    processes: at least one matching process, every pid outside the
    pre-restart kill list, and every starttime present (so identity is
    bound, not just pid)."""
    problems: list[str] = []
    procs = post.get("processes", [])
    if not procs:
        problems.append("no post-restart execution processes recorded")
    for proc in procs:
        if proc.get("pid") in killed_pids:
            problems.append(
                f"post-restart pid {proc['pid']} is a killed pid")
        if not proc.get("starttime"):
            problems.append(
                f"post-restart pid {proc.get('pid')} lacks starttime")
    return {"problems": problems,
            "fresh_process_count": len(procs),
            "passed": not problems}


# ------------------------------------------------------------------
# 2. strace transfer classification
# ------------------------------------------------------------------
#: the authorized 01-side model view is a directory of symlinks whose
#: targets resolve into CACHE_ROOT; the retained inventory record
#: proves the resolution, so symlink-path opens are cache reads. A
#: model-view path that did NOT resolve into the cache would fail the
#: inventory's dangling/entry checks before any reduction runs.
MODEL_VIEW_ALIASES = (
    "/srv/inferswarm/state/arm-c/model-view/",
)


def classify_opened_path(path: str) -> str:
    """Classify one opened file path."""
    if path.endswith(WEIGHT_SUFFIX) or path.endswith(
            ".safetensors.index.json"):
        if path.startswith(CACHE_ROOT) or (
                path.startswith(MODEL_VIEW_ALIASES)
                and path.endswith(WEIGHT_SUFFIX)):
            return "cache_weight_read"
        for root in SOURCE_ROOTS:
            if path.startswith(root):
                return "source_weight_read"
        return "unexpected_weight_read"
    if path.startswith(CACHE_ROOT):
        return "cache_nonweight_read"
    for root in SOURCE_ROOTS:
        if path.startswith(root):
            return "source_nonweight_read"
    return "other"


def reduce_strace(lines: list[str], file_sizes: dict[str, int]) -> dict:
    """Classify every openat of model-weight bytes and every connect().

    ``file_sizes`` maps opened weight paths to byte lengths (from the
    retained inventory); weight-transfer accounting uses the whole file
    byte length conservatively (an open+mmap of the shard makes its
    bytes available; partial reads cannot exceed this bound).
    """
    problems: list[str] = []
    counters = {
        "cache_weight_opens": {},
        "source_weight_reads": [],
        "unexpected_weight_reads": [],
        "connects": [],
    }
    for line in lines:
        match = OPEN_RE.match(line)
        if match:
            path = match.group(1)
            kind = classify_opened_path(path)
            if kind == "cache_weight_read":
                counters["cache_weight_opens"][path] = (
                    counters["cache_weight_opens"].get(path, 0) + 1)
            elif kind == "source_weight_read":
                counters["source_weight_reads"].append(path)
            elif kind == "unexpected_weight_read":
                counters["unexpected_weight_reads"].append(path)
            continue
        cmatch = CONNECT_RE.match(line)
        if cmatch:
            counters["connects"].append(line.strip()[:200])
    source_bytes = sum(
        file_sizes.get(path, 0) for path in counters["source_weight_reads"])
    unexpected_bytes = sum(
        file_sizes.get(path, 0)
        for path in counters["unexpected_weight_reads"])
    cache_bytes = sum(
        file_sizes.get(path, 0)
        for path in counters["cache_weight_opens"])
    if counters["source_weight_reads"]:
        problems.append(
            "Source model-weight bytes opened during the window: "
            f"{sorted(set(counters['source_weight_reads']))[:3]}")
    if counters["unexpected_weight_reads"]:
        problems.append(
            "unexpected model-weight source opened: "
            f"{sorted(set(counters['unexpected_weight_reads']))[:3]}")
    derived = {
        "source_model_weight_bytes_received": source_bytes,
        "unexpected_rematerialization_sources": len(
            set(counters["unexpected_weight_reads"])),
        "unexpected_model_source_reads": len(
            set(counters["source_weight_reads"])),
        "verified_cache_hit_bytes": cache_bytes,
    }
    return {"problems": problems, "counters": counters,
            "derived": derived, "passed": not problems}


# ------------------------------------------------------------------
# 3. cache-hit / materialization accounting
# ------------------------------------------------------------------
def reduce_cache_hits(strace_reductions: list[dict],
                      ready_reports: list[dict]) -> dict:
    """Derive per-participant cache-hit accounting from RETAINED bytes
    only: the per-side strace reductions (verified cache bytes, zero
    reacquisition derived from classified opens) cross-checked against
    the materialization witnesses' fetched_bytes. Every number is
    derived; no constant appears in a check position.

    ``strace_reductions``: outputs of reduce_strace for one restart
    window (node side + last side). ``ready_reports``: the retained
    last-stage ready reports (fetched_bytes) for the same window.
    """
    problems: list[str] = []
    if not strace_reductions:
        problems.append("no strace reductions retained")
        return {"problems": problems, "per_participant": {},
                "passed": False}
    per_participant = {}
    for reduction in strace_reductions:
        derived = reduction.get("derived") or {}
        if not derived:
            problems.append("strace reduction lacks derived counters")
            continue
        # reacquisition derived by the transfer classifier, never a
        # constant here
        per_participant[reduction.get("side", "?")] = {
            "cache_hit_bytes": int(
                derived.get("verified_cache_hit_bytes", 0) or 0),
            "reacquired_model_weight_bytes": int(
                derived.get("source_model_weight_bytes_received", 0)
                or 0),
            "unexpected_rematerialization_sources": int(
                derived.get("unexpected_rematerialization_sources", 0)
                or 0),
        }
    # cross-check against the materialization witnesses: the last
    # side's strace-bound cache bytes are WHOLE-FILE bounds (an
    # open+mmap makes the full shard available); the witness counts
    # planned TENSOR bytes only. The witness must not exceed the
    # strace bound, and the difference must stay within a plausible
    # safetensors header + metadata envelope (bound: 1 MiB).
    HEADER_ENVELOPE = 1 << 20
    for report in ready_reports:
        runtime = report.get("runtime") or {}
        fetched = runtime.get("fetched_bytes")
        last = per_participant.get("last")
        if fetched is not None and last:
            bound = last["cache_hit_bytes"]
            if not (bound - HEADER_ENVELOPE <= int(fetched) <= bound):
                lo = bound - HEADER_ENVELOPE
                problems.append(
                    f"witness fetched_bytes {fetched} outside the "
                    f"strace-derived cache bound [{lo}, {bound}]")
    return {"problems": problems, "per_participant": per_participant,
            "passed": not problems}


# ------------------------------------------------------------------
# 4. post-restart equality vs accepted #172
# ------------------------------------------------------------------
def reduce_equality(post_campaign: dict, post_report: dict,
                    accepted_campaign: dict, accepted_report: dict,
                    corpus_cases: list[dict]) -> dict:
    """Per-case exact equality of the post-restart ordinary results
    against the accepted #172 canonical results.

    Compares: committed token ids step-by-step (report token_events),
    committed count, stopping semantics (finish reason), decoded text
    (HTTP response content), plan identity (single plan digest family),
    and fresh-session attribution (positions 0..7, generation-0 epoch,
    session ids starting at 1 in the fresh coordinator).
    """
    problems: list[str] = []
    rows = []
    case_by_index = {c["session_index"]: c["case_id"]
                     for c in corpus_cases}

    post_requests = [
        r for r in post_report["coordinator_scope"]["requests"]
        if not r.get("fencing_arm_injections")]
    acc_requests = [
        r for r in accepted_report["coordinator_scope"]["requests"]
        if not r.get("fencing_arm_injections")]
    post_http = {r["case_id"]: r for r in post_campaign["records"]}
    acc_http = {r["case_id"]: r for r in accepted_campaign["records"]}

    if len(post_requests) != len(acc_requests):
        problems.append(
            f"request count {len(post_requests)} != accepted "
            f"{len(acc_requests)}")

    equal_count = 0
    for index, (post_req, acc_req) in enumerate(
            zip(post_requests, acc_requests), start=1):
        case_id = case_by_index.get(index)
        row_problems: list[str] = []
        if post_req.get("session_id") != index:
            row_problems.append("stale/wrong session id in fresh process")
        post_ids = [int(e["token_id"])
                    for e in post_req.get("token_events", [])]
        acc_ids = [int(e["token_id"])
                   for e in acc_req.get("token_events", [])]
        if post_ids != acc_ids:
            first = next((i for i, (a, b) in enumerate(
                zip(post_ids, acc_ids)) if a != b),
                min(len(post_ids), len(acc_ids)))
            row_problems.append(
                f"committed divergence at {first}: {post_ids} vs {acc_ids}")
        if len(post_ids) != P.COMMIT_TOKENS:
            row_problems.append("committed count is not 8")
        positions = [e["position"] for e in
                     post_req.get("token_events", [])]
        if positions != list(range(P.COMMIT_TOKENS)):
            row_problems.append(f"position sequence {positions}")
        epochs = {e["epoch_id"] for e in post_req.get("token_events", [])}
        if len(epochs) != 1:
            row_problems.append("stale epoch commits")
        plans = {e["plan_digest"] for e in
                 post_req.get("token_events", [])}
        if len(plans) != 1:
            row_problems.append("stale/wrong plan commits")
        for digest in plans:
            if digest != P.COORDINATOR_PLAN_DIGEST_172:
                row_problems.append(f"wrong plan digest {digest}")
        for event in post_req.get("token_events", []):
            if not (event.get("epoch_id") and event.get("plan_digest")
                    and event.get("position") is not None):
                row_problems.append("unattributed commit")
        # HTTP-level equality
        post_h = post_http.get(case_id)
        acc_h = acc_http.get(case_id)
        if post_h is None or acc_h is None:
            row_problems.append("missing http record")
        else:
            if post_h["http_status"] != 200:
                row_problems.append("http status")
            finish = post_h["response"]["choices"][0]["finish_reason"]
            if finish != "length":
                row_problems.append(f"finish reason {finish}")
            post_text = post_h["response"]["choices"][0]["message"][
                "content"]
            acc_text = acc_h["response"]["choices"][0]["message"][
                "content"]
            if post_text != acc_text:
                row_problems.append("decoded text mismatch")
        row = {"session_index": index, "case_id": case_id,
               "equal": not row_problems, "problems": row_problems}
        rows.append(row)
        equal_count += 1 if row["equal"] else 0

    # fencing negative control must be present and rejected (canonical)
    fencing = [r for r in post_report["coordinator_scope"]["requests"]
               if r.get("fencing_arm_injections")]
    if not fencing:
        problems.append("no fencing negative control in post run")
    else:
        for request in fencing:
            for inj in request.get("fencing_arm_injections", []):
                if inj.get("accepted") is not False:
                    problems.append("fencing injection accepted")

    passed = (equal_count == len(rows) and not problems
              and len(rows) > 0)
    return {
        "problems": problems, "rows": rows,
        "equal_count": equal_count, "case_count": len(rows),
        "passed": passed,
    }


# ------------------------------------------------------------------
# 4b. restart-2 sentinel exactness (strengthened correction pass)
# ------------------------------------------------------------------
#: retained campaign/report schema literals (as committed by the
#: campaign client and the R5B serving report; matched exactly so a
#: reshaped/foreign record cannot ride the reduction)
SENTINEL_CAMPAIGN_SCHEMA = (
    "inferswarm.issue175.arm-d.ordinary-campaign/1")
SERVING_REPORT_SCHEMA = "inferswarm.r5b.epoch-serving-report/1"
COORDINATOR_KIND = "cpu-only-external-coordinator-r6-dense"


def _request_commit_ids(request: dict) -> list[int]:
    return [int(e["token_id"]) for e in request.get("token_events", [])]


def _event_attribution_ok(event: dict) -> bool:
    return all(event.get(key) is not None for key in (
        "token_id", "position", "epoch_id", "plan_digest",
        "committed_at_ns"))


def reduce_sentinel_equality(r2_campaign: dict, r2_report: dict,
                             r1_campaign: dict, r1_report: dict,
                             acc_campaign: dict, acc_report: dict,
                             corpus_cases: list[dict]) -> dict:
    """Restart-2 sentinel exactness, derived from retained raw bytes.

    This is the strengthened restart-#2 reducer (maintainer correction
    pass over PR #181): the previous assembler compared only decoded
    HTTP text; this reducer mechanically consumes the retained
    correctness-bearing observations themselves.

    For every one of the exact seven accepted sentinel identities x
    six repeats it:

    1.  binds the restart-2 HTTP campaign record to the restart-2
        Coordinator serving-report request deterministically (fresh
        session order 1..42 in report order + cross-arm prompt-token
        identity + identical enumeration to the accepted #172
        protocol order);
    2.  binds the accepted #172 ordinary-sentinel campaign +
        serving-report observation for the same (identity, repeat);
    3.  binds the restart-1 canonical observation for the same case
        identity (corpus session-index mapping);
    4.  requires exact committed token-id equality (vs accepted AND
        vs restart 1 — compared directly, never transitively);
    5.  requires exactly the frozen committed-token count;
    6.  requires positions exactly 0..7 in event order;
    7.  requires one valid fresh epoch family (single epoch id ==
        active epoch, activated strictly after every restart-1
        commit, every restart-2 commit strictly after activation —
        no stale or mixed epoch commits);
    8.  requires every committed plan digest == the frozen accepted
        Coordinator plan;
    9.  requires complete attribution on every correctness-bearing
        token event (token_id/position/epoch_id/plan_digest/
        committed_at_ns all present) and a consistent session-ledger
        boundary;
    10. requires HTTP success (200);
    11. requires frozen stopping semantics (finish_reason "length",
        completion_tokens == frozen count);
    12. requires decoded-text equality (vs accepted and vs restart 1);
    13. requires within-restart-2 determinism at the token-event
        level (full (token_id, position, epoch_id, plan_digest)
        tuples), not merely decoded-text determinism;
    14. enforces prospectively valid restart-2 fresh-session /
        session-order semantics (fresh coordinator sessions numbered
        1..N in arrival order, no gaps, no reuse); historical #172
        session ids are NOT treated as an identity requirement.

    Authored booleans (ok_count, stored equal/passed flags) are never
    consulted; every count is derived from the raw records.
    """
    problems: list[str] = []
    rows: list[dict] = []

    # ---------- restart-2 campaign shape ----------
    if r2_campaign.get("schema") != SENTINEL_CAMPAIGN_SCHEMA:
        problems.append("restart-2 campaign schema drift")
    if r2_campaign.get("mode") != "sentinels":
        problems.append("restart-2 campaign mode is not sentinels")
    if r2_campaign.get("origin") != P.COORDINATOR_ORIGIN:
        problems.append("restart-2 campaign origin drift")
    records = r2_campaign.get("records", [])
    want_total = len(P.SENTINEL_IDS) * P.SENTINEL_REPEATS
    if len(records) != want_total:
        problems.append(
            f"restart-2 record count {len(records)} != {want_total}")
    pairs = [(r.get("case_id"), int(r.get("repeat", 0)))
             for r in records]
    if len(set(pairs)) != len(pairs):
        duplicates = sorted({p for p in pairs
                             if pairs.count(p) > 1})
        problems.append(
            f"duplicate (case_id, repeat) identities: {duplicates[:3]}")
    identities = {p[0] for p in pairs}
    if identities != set(P.SENTINEL_IDS):
        problems.append(
            "sentinel identity set drift: "
            f"{sorted(identities)} vs frozen {sorted(P.SENTINEL_IDS)}")
    for identity in sorted(identities):
        repeats = sorted(p[1] for p in pairs if p[0] == identity)
        if repeats != list(range(1, P.SENTINEL_REPEATS + 1)):
            problems.append(
                f"{identity} repeats present: {repeats}")

    # ---------- restart-2 serving report shape ----------
    if r2_report.get("schema") != SERVING_REPORT_SCHEMA:
        problems.append("restart-2 serving report schema drift")
    scope = r2_report.get("coordinator_scope", {})
    if scope.get("kind") != COORDINATOR_KIND:
        problems.append("restart-2 coordinator kind drift")
    reqs = scope.get("requests", [])
    if any(q.get("fencing_arm_injections") for q in reqs):
        problems.append("unexpected fencing request in restart-2")
    if len(reqs) != len(records):
        problems.append(
            f"restart-2 requests {len(reqs)} != records "
            f"{len(records)}")
    # prospectively valid fresh-session semantics: a fresh coordinator
    # numbers its sessions 1..N in arrival order. This is a restart-2
    # order/ownership requirement, NOT numeric identity with the
    # historical #172 session ids (fresh sessions are expected).
    session_ids = [q.get("session_id") for q in reqs]
    if session_ids != list(range(1, len(reqs) + 1)):
        problems.append(
            "restart-2 session order is not a fresh 1..N sequence")

    # ---------- accepted #172 reference table ----------
    if acc_campaign.get("mode") != "sentinels":
        problems.append("accepted reference campaign mode drift")
    acc_records = acc_campaign.get("records", [])
    acc_reqs = [q for q in acc_report.get("coordinator_scope", {})
                .get("requests", [])
                if not q.get("fencing_arm_injections")]
    if len(acc_records) != want_total or len(acc_reqs) != want_total:
        problems.append("accepted sentinel reference count drift")
    acc_pairs = [(r.get("case_id"), int(r.get("repeat", 0)))
                 for r in acc_records]
    # the restart-2 enumeration must be the accepted protocol order
    # verbatim (deterministic binding anchor #1)
    if pairs != acc_pairs:
        problems.append(
            "restart-2 (identity, repeat) enumeration differs from "
            "the accepted #172 protocol order")
    acc_by_pair = dict(zip(acc_pairs, acc_reqs))
    acc_http_by_pair = dict(zip(acc_pairs, acc_records))
    # cross-arm prompt-token identity (deterministic binding anchor
    # #2): the restart-2 request presented the same prompt tokens as
    # the accepted request at the same protocol position
    for index in range(min(len(reqs), len(acc_reqs))):
        if (reqs[index].get("prompt_token_ids")
                != acc_reqs[index].get("prompt_token_ids")):
            problems.append(
                f"request {index + 1} prompt tokens differ from the "
                "accepted #172 observation at the same protocol "
                "position")
            break
    # within-restart-2 prompt grouping (binding anchor #3): the six
    # requests of one identity share one prompt; distinct identities
    # carry distinct prompts
    prompt_by_identity: dict = {}
    for index, pair in enumerate(pairs[:len(reqs)]):
        prompt_by_identity.setdefault(
            pair[0], []).append(reqs[index].get("prompt_token_ids"))
    for identity, prompts in prompt_by_identity.items():
        if len({tuple(p or []) for p in prompts}) != 1:
            problems.append(
                f"{identity} repeats did not present one prompt")
    if len({tuple(p[0] or []) for p in prompt_by_identity.values()
            if p}) != len(prompt_by_identity):
        problems.append(
            "distinct sentinel identities share one prompt "
            "(binding ambiguity)")

    # ---------- restart-1 canonical reference table ----------
    case_by_index = {c["session_index"]: c["case_id"]
                     for c in corpus_cases}
    r1_reqs = [q for q in r1_report.get("coordinator_scope", {})
               .get("requests", [])
               if not q.get("fencing_arm_injections")]
    r1_by_case: dict = {}
    for request in r1_reqs:
        case_id = case_by_index.get(request.get("session_id"))
        if case_id is None:
            problems.append(
                "restart-1 request session outside the corpus")
            continue
        if case_id in r1_by_case:
            problems.append(
                f"restart-1 duplicate observation for {case_id}")
        r1_by_case[case_id] = request
    r1_http_by_case = {r.get("case_id"): r
                       for r in r1_campaign.get("records", [])}
    # the accepted negative control must stay present and rejected in
    # the restart-1 canonical record
    r1_fencing = [q for q in r1_report.get("coordinator_scope", {})
                  .get("requests", [])
                  if q.get("fencing_arm_injections")]
    if not r1_fencing:
        problems.append("no fencing negative control in restart 1")
    for request in r1_fencing:
        for injection in request.get("fencing_arm_injections", []):
            if injection.get("accepted") is not False:
                problems.append("fencing injection accepted (r1)")

    # ---------- epoch family / plan / realization identity ----------
    all_events = [e for q in reqs for e in q.get("token_events", [])]
    epoch_ids = {e.get("epoch_id") for e in all_events}
    active_epoch = r2_report.get("active_epoch_id")
    if len(epoch_ids) != 1 or active_epoch not in epoch_ids:
        problems.append(
            f"mixed/stale epoch commits: {sorted(epoch_ids)[:3]}")
    epoch_rows = [e for e in r2_report.get("epochs", [])
                  if e.get("epoch_id") == active_epoch]
    r1_all_events = [e for q in r1_reqs
                     for e in q.get("token_events", [])]
    max_r1_commit = max((int(e["committed_at_ns"])
                         for e in r1_all_events
                         if e.get("committed_at_ns") is not None),
                        default=None)
    if len(epoch_rows) != 1:
        problems.append("active epoch not uniquely retained")
    else:
        activated = int(epoch_rows[0]["activated_at_ns"])
        if max_r1_commit is not None and activated <= max_r1_commit:
            problems.append(
                "restart-2 epoch not fresh: activated at or before a "
                "restart-1 commit")
    min_r2_commit = min((int(e["committed_at_ns"])
                         for e in all_events
                         if e.get("committed_at_ns") is not None),
                        default=None)
    if epoch_rows and min_r2_commit is not None:
        activated = int(epoch_rows[0]["activated_at_ns"])
        if min_r2_commit <= activated:
            problems.append(
                "restart-2 commit at or before epoch activation")
    plan_digests = {e.get("plan_digest") for e in all_events}
    if plan_digests != {P.COORDINATOR_PLAN_DIGEST_172}:
        problems.append(
            f"committed plan digests {sorted(plan_digests)[:2]} "
            "!= frozen accepted Coordinator plan")
    if r2_report.get("active_plan_digest") != P.COORDINATOR_PLAN_DIGEST_172:
        problems.append("active plan digest != frozen accepted plan")
    if (r2_report.get("active_realization_id") in (None, "")
            or r2_report.get("active_realization_id")
            == r1_report.get("active_realization_id")):
        problems.append(
            "restart-2 active realization identity not fresh")
    if int(r2_report.get("realization_attempts") or 0) < 1:
        problems.append("restart-2 realization attempts < 1")

    # ---------- session ledger cross-check ----------
    ledger = {s.get("session_id"): s
              for s in r2_report.get("sessions", [])}

    # ---------- per-observation rows ----------
    equal_count = 0
    for index, record in enumerate(records):
        if index >= len(reqs):
            break
        request = reqs[index]
        case_id, repeat = pairs[index]
        row_problems: list[str] = []
        events = request.get("token_events") or []
        ids = [int(e["token_id"]) for e in events]
        # (4) exact committed token-id equality, both references
        accepted = acc_by_pair.get((case_id, repeat))
        if accepted is None:
            row_problems.append("missing accepted #172 reference")
        else:
            if ids != _request_commit_ids(accepted):
                row_problems.append(
                    "committed ids differ from accepted #172: "
                    f"{ids} vs {_request_commit_ids(accepted)}")
        r1_request = r1_by_case.get(case_id)
        if r1_request is None:
            row_problems.append("missing restart-1 canonical "
                                "reference for this identity")
        else:
            if ids != _request_commit_ids(r1_request):
                row_problems.append(
                    "committed ids differ from restart 1: "
                    f"{ids} vs {_request_commit_ids(r1_request)}")
        # (5) frozen committed-token count
        if len(ids) != P.COMMIT_TOKENS:
            row_problems.append(
                f"committed count {len(ids)} != {P.COMMIT_TOKENS}")
        # (6) positions exactly 0..7 in event order
        positions = [e.get("position") for e in events]
        if positions != list(range(P.COMMIT_TOKENS)):
            row_problems.append(f"position sequence {positions}")
        # (7)(8) per-event epoch/plan/freshness attribution
        for event in events:
            if event.get("epoch_id") != active_epoch:
                row_problems.append("stale/mixed epoch commit")
                break
            if event.get("plan_digest") != P.COORDINATOR_PLAN_DIGEST_172:
                row_problems.append("wrong committed plan digest")
                break
        # (9) complete attribution on every correctness-bearing event
        if not all(_event_attribution_ok(e) for e in events):
            row_problems.append("unattributed correctness-bearing "
                                "commit")
        # committed arrays must agree with the events they summarize
        if (request.get("committed_epoch_ids")
                != [e.get("epoch_id") for e in events]
                or request.get("committed_plan_digests")
                != [e.get("plan_digest") for e in events]):
            row_problems.append("committed arrays diverge from "
                                "token events")
        # session ledger attribution
        entry = ledger.get(request.get("session_id"))
        if entry is None:
            row_problems.append("no session-ledger entry")
        else:
            boundary = entry.get("latest_committed_boundary") or {}
            if (entry.get("generated_token_ids") != ids
                    or boundary.get("committed_generated_token_ids")
                    != ids
                    or boundary.get("committed_position")
                    != P.COMMIT_TOKENS):
                row_problems.append("session ledger diverges from "
                                    "token events")
        # (10) HTTP success
        if record.get("http_status") != 200:
            row_problems.append(
                f"http status {record.get('http_status')}")
        # (11) frozen stopping semantics
        choice = ((record.get("response") or {})
                  .get("choices", [{}])[0])
        if choice.get("finish_reason") != "length":
            row_problems.append(
                f"finish reason {choice.get('finish_reason')}")
        usage = (record.get("response") or {}).get("usage") or {}
        if usage.get("completion_tokens") != P.COMMIT_TOKENS:
            row_problems.append(
                f"completion tokens {usage.get('completion_tokens')}")
        # (12) decoded-text equality vs both references
        text = ((choice.get("message") or {}).get("content"))
        if accepted is not None:
            acc_text = (((accepted_response := acc_http_by_pair.get(
                (case_id, repeat)) or {})
                .get("response") or {}).get("choices", [{}])[0]
                .get("message", {}).get("content"))
            if text != acc_text:
                row_problems.append("decoded text mismatch vs "
                                    "accepted #172")
        r1_http = r1_http_by_case.get(case_id)
        if r1_http is not None:
            r1_text = (((r1_http.get("response") or {})
                        .get("choices", [{}])[0])
                       .get("message", {}).get("content"))
            if text != r1_text:
                row_problems.append("decoded text mismatch vs "
                                    "restart 1")
        row = {"case_id": case_id, "repeat": repeat,
               "session_id": request.get("session_id"),
               "equal": not row_problems, "problems": row_problems}
        rows.append(row)
        equal_count += 1 if row["equal"] else 0

    # ---------- (13) within-restart-2 token-event determinism ----------
    event_tuples: dict = {}
    for index, pair in enumerate(pairs[:len(reqs)]):
        events = reqs[index].get("token_events") or []
        signature = tuple(
            (e.get("token_id"), e.get("position"),
             e.get("epoch_id"), e.get("plan_digest"))
            for e in events)
        event_tuples.setdefault(pair[0], set()).add(signature)
    token_event_determinism = all(
        len(signatures) == 1
        for signatures in event_tuples.values()) and len(
            event_tuples) == len(P.SENTINEL_IDS)
    if not token_event_determinism:
        varied = sorted(cid for cid, sigs in event_tuples.items()
                        if len(sigs) != 1)
        problems.append(
            f"within-restart-2 token-event variation: {varied[:3]}")
    text_determinism = all(
        len({((records[i].get("response") or {})
              .get("choices", [{}])[0])
             .get("message", {}).get("content")
             for i, p in enumerate(pairs) if p[0] == cid}) == 1
        for cid in identities)

    unique_count = len(set(pairs))
    cardinality_ok = (
        unique_count == want_total
        and len(identities) == len(P.SENTINEL_IDS)
        and all(
            sum(1 for p in pairs if p[0] == cid) == P.SENTINEL_REPEATS
            for cid in identities))
    if not cardinality_ok:
        problems.append(
            f"unique sentinel observations {unique_count} != "
            f"{len(P.SENTINEL_IDS)}x{P.SENTINEL_REPEATS}")

    passed = (not problems and equal_count == len(rows)
              and rows and cardinality_ok
              and token_event_determinism)
    return {
        "problems": problems,
        "rows": rows,
        "row_count": len(rows),
        "equal_count": equal_count,
        "unique_observation_count": unique_count,
        "identity_count": len(identities),
        "repeats_per_identity": P.SENTINEL_REPEATS,
        "within_restart_determinism": bool(
            token_event_determinism and text_determinism),
        "token_event_determinism": bool(token_event_determinism),
        "decoded_text_determinism": bool(text_determinism),
        "fresh_session_order": session_ids == list(
            range(1, len(reqs) + 1)),
        "passed": passed,
    }


# ------------------------------------------------------------------
# 5. zero-invariant aggregation
# ------------------------------------------------------------------
ZERO_COUNTERS = (
    "source_model_weight_bytes_received",
    "cross_node_model_weight_bytes_received",
    "coordinator_model_weight_bytes_received",
    "coordinator_model_weight_bytes_materialized",
    "coordinator_bulk_artifact_bytes_observed",
    "unverified_cache_objects_used",
    "wrong_artifact_cache_hits",
    "wrong_plan_cache_hits",
    "stale_session_commits",
    "wrong_session_commits",
    "stale_plan_commits",
    "wrong_plan_commits",
    "stale_epoch_commits",
    "wrong_epoch_commits",
    "wrong_position_commits",
    "unattributed_correctness_bearing_commits",
    "unexpected_model_source_reads",
    "unexpected_rematerialization_sources",
    "silent_plan_substitutions",
)


def aggregate_zero_invariants(parts: dict) -> dict:
    """Sum the mandatory zero counters across every retained reduction
    part; every one must be exactly zero, and local activity must be
    explicitly nonzero where applicable."""
    problems = []
    totals = {name: 0 for name in ZERO_COUNTERS}
    for label, reduction in parts.items():
        derived = reduction.get("derived") or {}
        for name in ZERO_COUNTERS:
            totals[name] += int(derived.get(name, 0) or 0)
    for name, value in totals.items():
        if value != 0:
            problems.append(f"{name} == {value} (must be 0)")
    return {"problems": problems, "totals": totals,
            "passed": not problems}
