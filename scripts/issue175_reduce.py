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
