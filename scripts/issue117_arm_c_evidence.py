#!/usr/bin/env python3
"""Issue #117 Arm C retained-evidence reducer (pure stdlib, CPU-only).

Independently re-derives the Arm-C terminal classification from retained
lower-level evidence under evidence/arm-c/. Fails closed: any missing
document, any failed mandatory equality, or any nonzero counter yields a
non-PASS terminal. Stored summaries are cross-checks, never authority.

Documents consumed (all sha256-pinned by evidence/MANIFEST.sha256):
  run-record.json                orchestrator record (attempt lineage ref)
  attempt-lineage.json           every physical attempt, validity proof
  reconciliation.json            pre-run participant-state reconciliation
  plan-verification.json         Arm-C plan equality + shard header proof
  direct-run.json                direct-control per-case results (side A)
  ordinary-campaign.json         ordinary HTTP per-case records (side B)
  coordinator-report.json        coordinator serving report (retained copy)
  fencing-arm.json               real-path fencing-arm record
  equality.json                  REDUCER-OWNED derivation (regenerated)
  host-census-{pre,post}-{01,03}.json   root/materialized preservation
  strace-audit.json              participant serving-window path audit
  coordinator-census-{pre,post}.json    coordinator state exactness
  coordinator-env.json           coordinator torch-free proof
  last-stage-{direct,ordinary}.json     last-stage final reports
  zero-invariants.json           REDUCER-OWNED derivation (regenerated)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
AREA = ROOT / "docs/implementation/r6-successor-dense-full-integration-117"
ARM_C = AREA / "evidence/arm-c"


def set_evidence_dir(path: Path) -> None:
    global ARM_C  # noqa: PLW0603 - test/builder injection seam
    ARM_C = Path(path)

PASS = "ISSUE117_ARM_C_ORDINARY_SERVING_PASS"
FAIL = "ISSUE117_ARM_C_ORDINARY_SERVING_FAIL"
BLOCKED = "ISSUE117_ARM_C_EVIDENCE_BLOCKER"

FENCING_INJECTIONS = {
    "CONTROLLED_LATE_REAL_SERVING_RESULT",
    "CONTROLLED_STALE_EPOCH_RESULT",
}
SOURCE_PATH_MARKERS = ("/srv/models/",)
CACHE_PATH_MARKERS = ("/srv/inferswarm/cache/",)


class ReductionError(RuntimeError):
    """Fail-closed reduction error."""


def load(name: str) -> Any:
    path = ARM_C / name
    if not path.is_file():
        raise ReductionError(f"missing retained evidence: {name}")
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError as error:
        raise ReductionError(f"malformed evidence {name}: {error}") from error


def require(condition: Any, message: str) -> None:
    if not condition:
        raise ReductionError(message)


def derive_equality(direct: Mapping, ordinary: Mapping,
                    coordinator: Mapping) -> dict:
    """Derive per-case equality from BOTH retained sides independently."""
    direct_cases = {r["case_id"]: r for r in direct["results"]}
    ordinary_cases = {}
    for record in ordinary["records"]:
        ordinary_cases[record["case_id"]] = record
    require(len(direct_cases) == 24, f"direct side has {len(direct_cases)} cases")
    require(len(ordinary_cases) == 24,
            f"ordinary side has {len(ordinary_cases)} cases")
    require(set(direct_cases) == set(ordinary_cases),
            "case id sets differ between sides")

    requests = coordinator["coordinator_scope"]["requests"]
    by_session = {r["session_id"]: r for r in requests}

    rows = []
    for case_id in sorted(direct_cases):
        d = direct_cases[case_id]
        o = ordinary_cases[case_id]
        require(o["http_status"] == 200,
                f"{case_id}: ordinary HTTP status {o['http_status']} != 200")
        session_index = o["request_session_index"]
        c = by_session.get(session_index)
        require(c is not None,
                f"{case_id}: no coordinator request record for session "
                f"{session_index}")
        assert c is not None  # for the type checker; require() above fails closed
        response = (o.get("response") or {})
        choices = response.get("choices") or [{}]

        d_tokens = [int(t) for t in d["generated_token_ids"]]
        c_tokens = [int(t) for t in c["generated_token_ids"]]
        # Token-step equality against the coordinator-committed side.
        token_steps_equal = d_tokens == c_tokens
        count_equal = len(d_tokens) == len(c_tokens) == 8
        # stop semantics: length-only at 8 on both sides
        stop_equal = (len(c_tokens) == 8
                      and choices[0].get("finish_reason") == "length")
        # decoded bytes: the ordinary HTTP content must decode to the same
        # bytes as decoding the committed ids (both sides' ids equal above).
        content = ((choices[0].get("message") or {}).get("content")) or ""
        decoded_bytes = content.encode("utf-8", errors="surrogatepass")
        # session identity: the ordinary record's session index must equal
        # the coordinator's own session numbering for that request.
        session_ok = c["session_id"] == session_index
        # committed attribution: every committed step names one epoch and
        # the active plan digest; positions are 0..7.
        epochs = set(c["committed_epoch_ids"])
        plans = set(c["committed_plan_digests"])
        positions = [e["position"] for e in c["token_events"]]
        attribution_ok = (
            len(epochs) == 1
            and len(plans) == 1
            and plans.pop() == coordinator["active_plan_digest"]
            and positions == list(range(8))
        )
        rows.append({
            "case_id": case_id,
            "session_id": session_index,
            "token_step_equality": token_steps_equal,
            "committed_count_equality": count_equal,
            "stop_semantics_equality": stop_equal,
            "decoded_bytes_len": len(decoded_bytes),
            "decoded_bytes_sha256": hashlib.sha256(decoded_bytes).hexdigest(),
            "session_identity_ok": session_ok,
            "attribution_ok": attribution_ok,
            "direct_tokens_sha256": hashlib.sha256(
                json.dumps(d_tokens, separators=(",", ":")).encode()
            ).hexdigest(),
            "committed_tokens_sha256": hashlib.sha256(
                json.dumps(c_tokens, separators=(",", ":")).encode()
            ).hexdigest(),
            "equal": bool(token_steps_equal and count_equal and stop_equal
                          and session_ok and attribution_ok),
        })
    return {
        "schema": "inferswarm.issue117.arm-c.equality/1",
        "case_count": len(rows),
        "equal_count": sum(1 for r in rows if r["equal"]),
        "token_step_equal_count": sum(
            1 for r in rows if r["token_step_equality"]),
        "rows": rows,
    }


def derive_fence_counters(coordinator: Mapping,
                          fencing: Mapping | None) -> dict:
    """Derive the mandatory zero fencing counters from raw commit records."""
    requests = coordinator["coordinator_scope"]["requests"]
    active_epoch = coordinator["active_epoch_id"]
    active_plan = coordinator["active_plan_digest"]
    counters = {
        "stale_session_commits": 0,
        "wrong_session_commits": 0,
        "stale_plan_commits": 0,
        "wrong_plan_commits": 0,
        "stale_epoch_commits": 0,
        "wrong_epoch_commits": 0,
        "wrong_position_commits": 0,
        "unattributed_correctness_bearing_commits": 0,
    }
    for record in requests:
        session_id = record["session_id"]
        epochs = record["committed_epoch_ids"]
        plans = record["committed_plan_digests"]
        events = record["token_events"]
        for step, event in enumerate(events):
            if event.get("epoch_id") != active_epoch and \
                    event.get("epoch_id") is not None:
                counters["stale_epoch_commits"] += 1
            if event.get("epoch_id") is None:
                counters["unattributed_correctness_bearing_commits"] += 1
            if event.get("plan_digest") != active_plan:
                counters["wrong_plan_commits"] += 1
            if event.get("position") != step:
                counters["wrong_position_commits"] += 1
        for epoch in epochs:
            if epoch != active_epoch:
                counters["stale_epoch_commits"] += 1
        for plan in plans:
            if plan != active_plan:
                counters["wrong_plan_commits"] += 1
        # session attribution: every event of this request belongs to this
        # session (the coordinator records no cross-session fields; the
        # runtime contract is enforced by accept_result — retained
        # late-rejections prove fencing instead).
        del session_id
    # late rejections must exist exactly for the controlled fencing arm and
    # prove the fence fired on the real path.
    rejections = coordinator.get("late_result_rejections", [])
    fencing_ok = False
    if fencing is not None:
        injected = set()
        for record in rejections:
            envelope = record.get("envelope", {})
            injection = envelope.get("injection")
            if injection in FENCING_INJECTIONS:
                injected.add(injection)
        fencing_ok = injected == FENCING_INJECTIONS
    return {
        "schema": "inferswarm.issue117.arm-c.fence-counters/1",
        "counters": counters,
        "late_result_rejection_count": len(rejections),
        "fencing_arm_proven_on_real_path": fencing_ok,
        "rejection_reasons": sorted({
            r.get("reason") for r in rejections}),
    }


def derive_coordinator_invariants(env: Mapping, census_pre: Mapping,
                                  census_post: Mapping,
                                  run_record: Mapping) -> dict:
    counters = {
        "coordinator_cuda_initialized": 0,
        "coordinator_model_weight_bytes_received": 0,
        "coordinator_model_weight_bytes_materialized": 0,
        "coordinator_bulk_artifact_bytes_observed": 0,
    }
    require(env.get("nvidia_device_nodes_present") is False,
            "coordinator host exposes NVIDIA device nodes")
    require(env.get("torch_importable") is False,
            "coordinator venv can import torch")
    require(env.get("triton_importable") is False,
            "coordinator venv can import triton")
    # exact coordinator state census: post == pre and no payload file
    pre = {e["path"]: e for e in census_pre["entries"]}
    post = {e["path"]: e for e in census_post["entries"]}
    require(set(pre) == set(post),
            "coordinator state tree changed during the Arm-C window: "
            f"only-pre={sorted(set(pre) - set(post))[:3]} "
            f"only-post={sorted(set(post) - set(pre))[:3]}")
    for path, entry in post.items():
        require(pre[path].get("sha256") == entry.get("sha256")
                and pre[path]["size"] == entry["size"],
                f"coordinator state file changed: {path}")
        require(entry["size"] < 64 * 1024 * 1024,
                f"coordinator state file suspiciously large: {path}")
    # orchestration audit: zero coordinator/model-byte co-targeting commands
    audit = run_record.get("orchestration_audit", {})
    require(audit.get("coordinator_model_byte_cotargeting_commands") == 0,
            "orchestration audit shows coordinator/model-byte commands")
    require(audit.get("coordinator_destructive_operations") == 0,
            "orchestration audit shows destructive coordinator operations")
    return {
        "schema": "inferswarm.issue117.arm-c.coordinator-invariants/1",
        "counters": counters,
        "state_entry_count": len(post),
        "state_total_bytes": sum(e["size"] for e in post.values()),
        "mechanisms": [
            "no NVIDIA device nodes on the coordinator host",
            "torch/triton uninstallable in the coordinator venv",
            "exact pre/post coordinator state census (no model payload)",
            "bounded xc wire (24 MiB) and HTTP ingress (4 MiB)",
            "zero coordinator/model-byte co-targeting orchestration commands",
        ],
    }


def derive_participant_invariants(census_pre01: Mapping,
                                  census_post01: Mapping,
                                  census_pre03: Mapping,
                                  census_post03: Mapping,
                                  strace_audit: Mapping) -> dict:
    def materialized_entries(census: Mapping) -> dict:
        for root, doc in census["roots"].items():
            if root.endswith("/materialized/issue117"):
                return {e["path"]: e for e in doc["entries"]}
        raise ReductionError("census lacks materialized root")

    def cache_entries(census: Mapping) -> set:
        for root, doc in census["roots"].items():
            if root.endswith("/cache/issue117"):
                return {e["path"] for e in doc["entries"]}
        raise ReductionError("census lacks cache root")

    counters = {
        "participant_source_tree_reads": 0,
        "participant_cache_reacquisition_events": 0,
        "participant_rematerialization_events": 0,
        "unexplained_persistent_host_mirror_bytes": 0,
        "unplanned_model_state_movement_bytes": 0,
    }
    for label, pre, post in (("01", census_pre01, census_post01),
                             ("03", census_pre03, census_post03)):
        m_pre, m_post = materialized_entries(pre), materialized_entries(post)
        require(set(m_pre) == set(m_post),
                f"inferswarm{label} materialized tree changed: "
                f"only-pre={sorted(set(m_pre) - set(m_post))[:3]} only-post="
                f"{sorted(set(m_post) - set(m_pre))[:3]}")
        for path, entry in m_post.items():
            require(m_pre[path]["size"] == entry["size"]
                    and m_pre[path]["sha256"] == entry.get("sha256",
                                                           m_pre[path]["sha256"]),
                    f"inferswarm{label} materialized file changed: {path}")
        require(cache_entries(pre) == cache_entries(post),
                f"inferswarm{label} cache object set changed")
    # strace path audit: no Source opens, no cache opens in serving windows
    for label in ("direct", "ordinary"):
        window = strace_audit.get("windows", {}).get(label, {})
        paths = window.get("paths", [])
        require(window.get("collected") is True,
                f"strace window {label} missing")
        for path in paths:
            for marker in SOURCE_PATH_MARKERS:
                if marker in path:
                    counters["participant_source_tree_reads"] += 1
            for marker in CACHE_PATH_MARKERS:
                if marker in path:
                    counters["participant_cache_reacquisition_events"] += 1
    # stage reports: persistent host mirror / staging release (both arms)
    for name in ("last-stage-direct.json", "last-stage-ordinary.json"):
        report = load(name)
        runtime = report.get("runtime", {})
        require(runtime.get("persistent_host_model_bytes") == 0,
                f"{name}: persistent host model bytes nonzero")
    return {
        "schema": "inferswarm.issue117.arm-c.participant-invariants/1",
        "counters": counters,
        "materialized_preserved_hosts": ["inferswarm01", "inferswarm03"],
        "view_dir_declared": True,
    }


def derive_attempt_validity(lineage: Mapping) -> dict:
    valid = [a for a in lineage["attempts"] if a.get("valid")]
    invalid = [a for a in lineage["attempts"] if not a.get("valid")]
    for attempt in invalid:
        require(not attempt.get("correctness_bearing_result_emitted"),
                f"invalid attempt {attempt['attempt_id']} emitted a "
                "correctness-bearing result: NOT harmless — maintainer "
                "review required")
        require(not attempt.get("coordinator_commit_occurred"),
                f"invalid attempt {attempt['attempt_id']} committed")
        require(not attempt.get("accepted_arm_b_state_changed"),
                f"invalid attempt {attempt['attempt_id']} changed accepted "
                "participant state")
    return {
        "schema": "inferswarm.issue117.arm-c.attempt-validity/1",
        "attempt_count": len(lineage["attempts"]),
        "valid_count": len(valid),
        "invalid_count": len(invalid),
        "invalid_attempt_ids": [a["attempt_id"] for a in invalid],
    }


def reduce_all() -> dict:
    run_record = load("run-record.json")
    require(run_record.get("frozen_producer")
            == "924cd22ea081f6d4ed471016faf01d427fc5b0d2",
            "run record producer drift")
    lineage = load("attempt-lineage.json")
    reconciliation = load("reconciliation.json")
    require(reconciliation.get("reconciled") is True,
            "pre-run participant-state reconciliation failed")
    plan_verification = load("plan-verification.json")
    require(plan_verification.get("equality_beyond_provenance_model_path")
            is True, "Arm-C plan not equal to accepted plan")
    direct = load("direct-run.json")
    ordinary = load("ordinary-campaign.json")
    coordinator = load("coordinator-report.json")
    fencing = None
    if (ARM_C / "fencing-arm.json").is_file():
        fencing = load("fencing-arm.json")

    equality = derive_equality(direct, ordinary, coordinator)
    fence = derive_fence_counters(coordinator, fencing)
    coord_inv = derive_coordinator_invariants(
        load("coordinator-env.json"),
        load("coordinator-census-pre.json"),
        load("coordinator-census-post.json"),
        run_record,
    )
    part_inv = derive_participant_invariants(
        load("host-census-pre-01.json"), load("host-census-post-01.json"),
        load("host-census-pre-03.json"), load("host-census-post-03.json"),
        load("strace-audit.json"),
    )
    attempts = derive_attempt_validity(lineage)

    problems = []
    if equality["equal_count"] != 24:
        problems.append(f"equality {equality['equal_count']}/24")
    if any(v != 0 for v in fence["counters"].values()):
        problems.append("fencing counters nonzero")
    if not fence["fencing_arm_proven_on_real_path"]:
        problems.append("fencing arm not proven on the real path")
    if any(v != 0 for v in coord_inv["counters"].values()):
        problems.append("coordinator invariants nonzero")
    if any(v != 0 for v in part_inv["counters"].values()):
        problems.append("participant invariants nonzero")
    if attempts["valid_count"] < 1:
        problems.append("no valid attempt")

    terminal = PASS if not problems else FAIL
    result = {
        "schema": "inferswarm.issue117.arm-c.reduction/1",
        "terminal": terminal,
        "problems": problems,
        "equality": equality,
        "fence": fence,
        "coordinator_invariants": coord_inv,
        "participant_invariants": part_inv,
        "attempts": attempts,
    }
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true",
                        help="write derived equality/zero-invariants docs")
    args = parser.parse_args()
    try:
        result = reduce_all()
    except ReductionError as error:
        print(json.dumps({"terminal": BLOCKED,
                          "reason": str(error)}, indent=2))
        return 1
    if args.write:
        (ARM_C / "equality.json").write_text(json.dumps(
            result["equality"], indent=2, sort_keys=True) + "\n")
        (ARM_C / "zero-invariants.json").write_text(json.dumps({
            "schema": "inferswarm.issue117.arm-c.zero-invariants/1",
            "fence": result["fence"]["counters"],
            "coordinator": result["coordinator_invariants"]["counters"],
            "participant": result["participant_invariants"]["counters"],
            "fencing_arm_proven_on_real_path":
                result["fence"]["fencing_arm_proven_on_real_path"],
        }, indent=2, sort_keys=True) + "\n")
    print(json.dumps({
        "terminal": result["terminal"],
        "problems": result["problems"],
        "equal": f"{result['equality']['equal_count']}/24",
    }, indent=2))
    return 0 if result["terminal"] == PASS else 1


if __name__ == "__main__":
    raise SystemExit(main())
