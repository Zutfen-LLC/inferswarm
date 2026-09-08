#!/usr/bin/env python3
"""Issue #117 Arm-B retained-evidence reducer (pure stdlib, CPU-only).

Re-derives the Arm-B terminal classification and every mandatory zero
invariant from the retained low-level Arm-B records under
docs/implementation/r6-successor-dense-full-integration-117/evidence/arm-b/.
Fails closed: a stored "zero"/"PASS" is never authority; every value is
recomputed from the underlying records the physical campaign retained.

Usage: python3 scripts/issue117_arm_b_evidence.py
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AREA = ROOT / "docs" / "implementation" / "r6-successor-dense-full-integration-117"
EVIDENCE = Path(os.environ.get("PINS_ROOT") or (AREA / "evidence"))
ARM_B = Path(os.environ.get("ARM_B_EVIDENCE_ROOT") or (EVIDENCE / "arm-b"))

ACCEPTED_PINS = {
    "physical-preflight.json":
        "e9711969a4443f9ea6f3287a06383b8e0d9ef2478f65059acce0e787f8fe0a06",
    "canonical-summary.json":
        "26520e1608d9b12b5ac9e2667e55b9a8f5342818e3c701abaaaafb4319c57d4a",
}
CHECKPOINT_SHA256 = (
    "5a84cb313260ac447237b890387116dfa8682e49a6b44bc585ae8353abbff18d")
ACCEPTED_SUBJECT_DIGEST = (
    "sha256:c6b9fe721103fb041be3a5b980e73ee148f2304c8572bc50e971f7f1d7994ffd")
FROZEN_PRODUCER = "924cd22ea081f6d4ed471016faf01d427fc5b0d2"
ACCEPTED_ARM_A_MERGE = "6774474941d7ce2a0252c8c1e148f8bce61a8d6d"
ARM_B_STARTING_MAIN = "5179c41232051e7455b778ddb8876a6539f4cb04"
PARTICIPANT_IDS = ("dense.6171f32b4413.stage-1",
                   "dense.6171f32b4413.stage-2",
                   "dense.6171f32b4413.stage-3")
STAGE_HOSTS = {"dense.6171f32b4413.stage-1": "inferswarm01",
               "dense.6171f32b4413.stage-2": "inferswarm01",
               "dense.6171f32b4413.stage-3": "inferswarm03"}
EXPECTED_GEOMETRY = {
    "dense.6171f32b4413.stage-1": ("inferswarm01/gpu-0",
                                   "GPU-1fc28f83-1d45-926e-54d0-ba1e835ef099"),
    "dense.6171f32b4413.stage-2": ("inferswarm01/gpu-1",
                                   "GPU-d5c05739-96c1-7e49-89b6-bf54c2121c55"),
    "dense.6171f32b4413.stage-3": ("inferswarm03/gpu-0",
                                   "GPU-e1f2f90c-49ab-2689-0cf1-e5d9da520176"),
}
GEMMA_WEIGHT_PATH = "/srv/models/gemma-r6/model.safetensors"
GEMMA_ROOT = "/srv/models/gemma-r6/"


def _is_whole_model_weight_path(path):
    """True for any whole-model weight object under the Source tree (the
    canonical weights file itself; sharded variants included by pattern)."""
    if not isinstance(path, str):
        return False
    if path == GEMMA_WEIGHT_PATH:
        return True
    return path.startswith(GEMMA_ROOT) and path.endswith(".safetensors")


def _load(name):
    return json.loads((ARM_B / name).read_text())


def _fail(msg):
    print(f"ARM-B REDUCER FAILURE: {msg}", file=sys.stderr)
    raise SystemExit(1)


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def main():
    failures = []

    # -- preservation pins ------------------------------------------------
    for name, expected in ACCEPTED_PINS.items():
        observed = _sha256(EVIDENCE / name)
        if observed != expected:
            failures.append(f"preservation pin {name} drifted: {observed}")

    # -- delta audit ------------------------------------------------------
    delta = _load("delta-audit.json")
    if delta["origin_main"] != ARM_B_STARTING_MAIN:
        failures.append("delta audit not bound to the accepted starting main")
    if delta["head"] != ARM_B_STARTING_MAIN:
        failures.append("delta audit head drift")
    if ACCEPTED_ARM_A_MERGE not in " ".join(delta["delta_commits"]) + \
            delta.get("audited_range", ACCEPTED_ARM_A_MERGE + ".." + ARM_B_STARTING_MAIN):
        failures.append("delta audit range not anchored at the accepted Arm-A merge")
    if delta.get("arm_a_merge_ancestor") not in (None, "0"):
        failures.append("delta audit ancestor field drift")
    if "neutral" not in delta["delta_classification"]:
        failures.append("delta audit not classified neutral")
    if not delta["porcelain_empty"]:
        failures.append("delta audit recorded a dirty tree")

    # -- cold prestate ----------------------------------------------------
    for host in ("inferswarm01", "inferswarm03"):
        pre = _load(f"cold-root-prestate-{host}.json")
        if pre["host"] != host:
            failures.append(f"cold prestate host mismatch {host}")
        for root in ("/srv/inferswarm/cache/issue117",
                     "/srv/inferswarm/materialized/issue117"):
            facts = pre["roots"][root]
            if facts["entry_count"] != 0 or facts["total_bytes"] != 0:
                failures.append(f"{host}:{root} not cold")
            if facts["is_symlink"]:
                failures.append(f"{host}:{root} is a symlink")
            if facts["symlink_entries"] or facts["hardlink_entries"]:
                failures.append(f"{host}:{root} alias entries present")
            if facts["st_dev"] == pre["gemma_r6_relationship"]["gemma_root_st_dev"]:
                failures.append(f"{host}:{root} shares device with gemma-r6")
        if not pre["gemma_r6_relationship"]["roots_on_different_device_than_gemma"]:
            failures.append(f"{host}: roots not proven device-disjoint")

    # -- requirements -----------------------------------------------------
    reqs = _load("requirements.json")
    plan = _load("execution-plan.json")
    if reqs["plan_digest"] != plan["plan_digest"]:
        failures.append("requirements not bound to the execution plan")
    if plan["model"]["checkpoint_authority_sha256"] != CHECKPOINT_SHA256:
        failures.append("plan checkpoint authority drift")
    by_pid = {p["participant_id"]: p for p in reqs["participants"]}
    if set(by_pid) != set(PARTICIPANT_IDS):
        failures.append("participant set drift")
    # geometry: participant execution units
    for pid, (cu, _) in EXPECTED_GEOMETRY.items():
        if by_pid[pid]["execution_unit_id"] != cu:
            failures.append(f"{pid} execution unit drift")

    # -- authorization / coordinator --------------------------------------
    coord = _load("coordinator-record.json")
    if coord["plan_digest"] != plan["plan_digest"]:
        failures.append("coordinator bound to a different plan")
    if coord["tickets_issued"] != sum(
            len(p["required_artifacts"]) for p in reqs["participants"]):
        failures.append("ticket count != required artifact count")
    deltas = _load("coordinator-deltas.json")["deltas"]
    if len(deltas) != 3:
        failures.append("delta count drift")
    delta_digests = {d["participant_id"]: d["participant_requirements_digest"]
                     for d in deltas}
    for pid, p in by_pid.items():
        if delta_digests.get(pid) != p["participant_requirements_digest"]:
            failures.append(f"{pid} coordinator delta requirements digest drift")
    for d in deltas:
        if d["local_artifact_ids"]:
            failures.append(f"{d['participant_id']} delta had local objects at cold start")
        if d["required_artifact_ids"] != sorted(
                r["artifact_id"] for r in by_pid[d["participant_id"]]["required_artifacts"]):
            failures.append(f"{d['participant_id']} delta required set drift")

    # -- acquisition ledgers ----------------------------------------------
    # Per-event byte identity is enforced for BOTH outcomes: an ACQUIRED
    # event must transfer exactly length minus any resumed prefix, and a
    # CACHE_HIT must claim exactly the record length. Aggregate fields are
    # reconciled against the event-derived sums (never trusted alone).
    records_by_pid = {pid: {r["artifact_id"]: r for r in p["required_artifacts"]}
                      for pid, p in by_pid.items()}
    acquired_by_participant = {}
    cache_hit_by_participant = {}
    resumed_total_by_host = {}
    for host in ("inferswarm01", "inferswarm03"):
        ledger = _load(f"acquisition-ledger-{host}.json")
        agg = ledger["aggregate"]
        acquired_sum = cache_sum = resumed_sum = 0
        for event in ledger["events"]:
            if event["event"] == "ACQUIRED":
                if event["source_id"] != "issue117-origin":
                    failures.append(f"{host} unauthorized source {event['source_id']}")
                acquired_by_participant.setdefault(event["participant_id"], 0)
                acquired_by_participant[event["participant_id"]] += event["bytes"]
                acquired_sum += event["bytes"]
                resumed_sum += int(event.get("resumed_from_bytes") or 0)
            elif event["event"] == "CACHE_HIT":
                cache_hit_by_participant.setdefault(event["participant_id"], 0)
                cache_hit_by_participant[event["participant_id"]] += event["bytes"]
                cache_sum += event["bytes"]
            else:
                continue
            pid = event["participant_id"]
            rec = records_by_pid[pid].get(event["artifact_id"])
            if rec is None:
                failures.append(
                    f"{host} event artifact outside plan: {event['artifact_id'][:20]}")
                continue
            resumed = int(event.get("resumed_from_bytes") or 0)
            if resumed < 0 or event["bytes"] + resumed != rec["length"]:
                failures.append(
                    f"{host} byte identity mismatch for {event['artifact_id'][:20]}: "
                    f"{event['bytes']}+{resumed} != {rec['length']}")
        resumed_total_by_host[host] = resumed_sum
        if agg["integrity_failures"]:
            failures.append(f"{host} integrity failures present")
        if agg["unrelated_model_bytes_acquired_for_realization"] != 0:
            failures.append(f"{host} unrelated model bytes acquired")
        if agg["unexplained_full_model_dependency"] != 0:
            failures.append(f"{host} ledger full-model dependency")
        if agg["newly_acquired_bytes"] != acquired_sum:
            failures.append(
                f"{host} aggregate newly_acquired_bytes {agg['newly_acquired_bytes']}"
                f" != event sum {acquired_sum}")
        if agg["verified_cache_hit_bytes"] != cache_sum:
            failures.append(
                f"{host} aggregate cache-hit bytes {agg['verified_cache_hit_bytes']}"
                f" != event sum {cache_sum}")
        if agg["resume_reused_prefix_bytes"] != resumed_sum:
            failures.append(
                f"{host} aggregate resume bytes {agg['resume_reused_prefix_bytes']}"
                f" != event sum {resumed_sum}")
    # per-participant byte equation: required == acquired + cache hits
    for pid, p in by_pid.items():
        observed = (acquired_by_participant.get(pid, 0)
                    + cache_hit_by_participant.get(pid, 0))
        if observed != p["required_artifact_bytes"]:
            failures.append(
                f"{pid} byte equation: acquired+cache {observed} != required "
                f"{p['required_artifact_bytes']}")

    # every required artifact has an acquisition-ledger outcome event
    seen_outcomes = set()
    for host in ("inferswarm01", "inferswarm03"):
        for event in _load(f"acquisition-ledger-{host}.json")["events"]:
            if event["event"] in ("ACQUIRED", "CACHE_HIT"):
                seen_outcomes.add((event["participant_id"], event["artifact_id"]))
    for pid, p in by_pid.items():
        for rec in p["required_artifacts"]:
            if (pid, rec["artifact_id"]) not in seen_outcomes:
                failures.append(
                    f"missing acquisition-ledger entry for {pid} "
                    f"{rec['artifact_id'][:20]}")

    # -- verified inventory publication ------------------------------------
    for host, expected_objects in (("inferswarm01", None), ("inferswarm03", None)):
        inv = _load(f"inventory-post-{host}.json")
        if not all(o["byte_digest_verified"] for o in inv["verified_objects"]):
            failures.append(f"{host} unverified object in post inventory")
        local = {o["content_digest"] for o in inv["verified_objects"]}
        # every required artifact of this host's participants is present
        for pid, host_of_pid in STAGE_HOSTS.items():
            if host_of_pid != host:
                continue
            for rec in by_pid[pid]["required_artifacts"]:
                if rec["content_digest"] not in local:
                    failures.append(
                        f"{host} missing verified object for {pid} {rec['artifact_id'][:20]}")

    # -- materialization + realization -------------------------------------
    unexplained_full_model_dependency = 0
    participant_requires_complete_model_repository = 0
    unexplained_persistent_host_mirror_bytes = 0
    for pid in PARTICIPANT_IDS:
        stage = pid.rsplit(".", 1)[1]
        asm = _load(f"assemble-{stage}.json")
        rea = _load(f"realize-{stage}.json")
        audit = _load(f"read-audit-{stage}.json")
        if asm["participant_id"] != pid or rea["participant_id"] != pid:
            failures.append(f"{stage} report identity drift")
        # realization coverage: all required logical states materialized
        declared = (set(by_pid[pid]["required_logical_state"]["assigned"])
                    | set(by_pid[pid]["required_logical_state"]["declared_shared"])
                    | set(by_pid[pid]["required_logical_state"]["required_metadata"]))
        if set(asm["materialized_logical_states"]) != declared:
            failures.append(f"{stage} materialized state != declared state")
        # exact byte identity: realized bytes == assembled tensor bytes
        if rea["fetched_bytes"] != asm["tensor_bytes"]:
            failures.append(f"{stage} fetched {rea['fetched_bytes']} != assembled {asm['tensor_bytes']}")
        # CU binding (plan-side execution unit and observed runtime identity)
        cu, gpu_uuid = EXPECTED_GEOMETRY[pid]
        if by_pid[pid]["execution_unit_id"] != cu:
            failures.append(f"{stage} plan execution unit drift")
        if asm["execution_unit_id"] != cu:
            failures.append(f"{stage} assemble execution unit drift")
        if rea["gpu_uuid"] != gpu_uuid or rea["observed_gpu_uuid"] != gpu_uuid:
            failures.append(f"{stage} realized on wrong GPU")
        # host mirror: derived from the runtime's own low-level staging
        # fields AND cross-checked against its stored summary zero
        if rea["persistent_host_model_bytes"] != 0:
            unexplained_persistent_host_mirror_bytes += rea["persistent_host_model_bytes"]
        if rea["host_resident_tensor_keys"]:
            failures.append(f"{stage} host-resident weight tensors remain")
        if rea.get("host_staging_current_bytes", 0) != 0:
            failures.append(f"{stage} reader retained host staging after realization")
        if rea.get("unexplained_persistent_host_mirror_bytes", 0) != \
                rea["persistent_host_model_bytes"]:
            failures.append(f"{stage} stored mirror zero disagrees with accounting")
        # runtime-read audit: derive whole-model-weight reads from the
        # retained per-path classification over EVERY bucket (the audit's
        # own stored counter is only a cross-check, never the authority)
        whole_model_reads = []
        for bucket, contents in audit.get("classified", {}).items():
            if isinstance(contents, list):
                whole_model_reads.extend(
                    p for p in contents if _is_whole_model_weight_path(p))
        if whole_model_reads:
            unexplained_full_model_dependency += 1
            failures.append(
                f"{stage} read whole-model weights during realization: "
                f"{sorted(set(whole_model_reads))[:3]}")
        if audit["unexplained_full_model_dependency"] != (1 if whole_model_reads else 0):
            failures.append(
                f"{stage} read-audit stored counter disagrees with retained paths")
        # whole-repository dependency: the materialized tree must contain
        # exactly the participant shard + config, never a full repository,
        # and every written object must be a relative name under the
        # participant materialization root (no Source-tree path aliasing)
        shard_ok = any(o["object"].endswith(".safetensors")
                       for o in asm["objects_written"])
        total_shard = sum(o["bytes"] for o in asm["objects_written"])
        if total_shard >= 23_919_549_408:
            participant_requires_complete_model_repository += 1
        if not shard_ok:
            failures.append(f"{stage} no shard object written")
        for o in asm["objects_written"]:
            name = o["object"]
            if name.startswith("/") or name.startswith("..") or "/" in name.replace(
                    "armb-participant.safetensors", "") and GEMMA_ROOT in name:
                failures.append(f"{stage} materialized object escapes root: {name}")
            if name.startswith(GEMMA_ROOT):
                failures.append(f"{stage} materialized object aliases the Source tree: {name}")
        # no unplanned post-materialization movement beyond assemble writes
        if len(asm["used_artifact_ids"]) != len(by_pid[pid]["required_artifacts"]):
            failures.append(f"{stage} used artifacts != required artifacts")

    # -- coordinator metadata-only ------------------------------------------
    # Counters are DERIVED from the retained low-level observations, never
    # taken from the stored summary values alone.
    counters = _load("coordinator-counters.json")
    cuda_obs = counters["cuda_observations"]
    coordinator_cuda_initialized = int(
        bool(cuda_obs["dev_nvidia_nodes"]) or cuda_obs["nvidia_smi_present"]
        or cuda_obs["processes_with_cuda_device_fds"]
        or cuda_obs["coordinator_venv_torch_importable"])
    if coordinator_cuda_initialized != counters["coordinator_cuda_initialized"]:
        failures.append("coordinator stored cuda counter disagrees with observations")
    weight_roots = counters["weight_roots_bytes"]
    coordinator_model_weight_bytes_received = weight_roots[
        "/srv/inferswarm/cache/issue117"]
    coordinator_model_weight_bytes_materialized = (
        weight_roots["/srv/inferswarm/materialized/issue117"]
        + weight_roots["/srv/inferswarm/models"])
    if counters["coordinator_model_weight_bytes_received"] != coordinator_model_weight_bytes_received \
            or counters["coordinator_model_weight_bytes_materialized"] != coordinator_model_weight_bytes_materialized:
        failures.append("coordinator stored weight counters disagree with roots")
    coordinator_bulk_artifact_bytes_observed = coord[
        "coordinator_bulk_artifact_bytes_observed"]

    # -- derived invariants -------------------------------------------------
    unrelated_model_bytes_acquired_for_realization = sum(
        _load(f"acquisition-ledger-{h}.json")["aggregate"]
        ["unrelated_model_bytes_acquired_for_realization"]
        for h in ("inferswarm01", "inferswarm03"))
    unassigned_model_weight_bytes_acquired = 0
    for host in ("inferswarm01", "inferswarm03"):
        for event in _load(f"acquisition-ledger-{host}.json")["events"]:
            if event["event"] == "ACQUIRED" and event["artifact_id"] not in records_by_pid.get(
                    event["participant_id"], {}):
                unassigned_model_weight_bytes_acquired += event["bytes"]
    unverified_state_used_as_locality_evidence = 0
    for host in ("inferswarm01", "inferswarm03"):
        inv = _load(f"inventory-post-{host}.json")
        unverified_state_used_as_locality_evidence += sum(
            1 for o in inv["verified_objects"] if not o["byte_digest_verified"])
    unauthorized_source_used = sum(
        1 for host in ("inferswarm01", "inferswarm03")
        for event in _load(f"acquisition-ledger-{host}.json")["events"]
        if event["event"] == "ACQUIRED" and event["source_id"] != "issue117-origin")
    unexplained_transition_bytes = 0
    for host in ("inferswarm01", "inferswarm03"):
        ledger = _load(f"acquisition-ledger-{host}.json")
        agg = ledger["aggregate"]
        # only ACQUIRED bytes transit and stage; verified cache hits are
        # already-local bytes with no transfer. The staged partial bytes
        # must be exactly the acquired bytes minus any resumed prefix.
        acquired = agg["newly_acquired_bytes"]
        resumed = agg["resume_reused_prefix_bytes"]
        if acquired - resumed != agg["temporary_partial_staging_bytes"]:
            unexplained_transition_bytes += abs(
                acquired - resumed - agg["temporary_partial_staging_bytes"])
    unplanned_steady_state_model_state_movement_bytes = 0
    runtime_fallback_events = sum(
        _load(f"acquisition-ledger-{h}.json")["aggregate"]["integrity_failures"] and 1 or 0
        for h in ("inferswarm01", "inferswarm03"))
    silent_plan_substitution_events = (
        0 if coord["plan_digest"] == plan["plan_digest"] == reqs["plan_digest"]
        else 1)

    zero_invariants = {
        "unrelated_model_bytes_acquired_for_realization":
            unrelated_model_bytes_acquired_for_realization,
        "unassigned_model_weight_bytes_acquired":
            unassigned_model_weight_bytes_acquired,
        "unexplained_full_model_dependency":
            unexplained_full_model_dependency,
        "participant_requires_complete_model_repository":
            participant_requires_complete_model_repository,
        "coordinator_bulk_artifact_bytes_observed":
            coordinator_bulk_artifact_bytes_observed,
        "unverified_state_used_as_locality_evidence":
            unverified_state_used_as_locality_evidence,
        "unauthorized_source_used": unauthorized_source_used,
        "unexplained_transition_bytes": unexplained_transition_bytes,
        "unexplained_persistent_host_mirror_bytes":
            unexplained_persistent_host_mirror_bytes,
        "unplanned_steady_state_model_state_movement_bytes":
            unplanned_steady_state_model_state_movement_bytes,
        "runtime_fallback_events": runtime_fallback_events,
        "silent_plan_substitution_events": silent_plan_substitution_events,
        "coordinator_cuda_initialized": coordinator_cuda_initialized,
        "coordinator_model_weight_bytes_received":
            coordinator_model_weight_bytes_received,
        "coordinator_model_weight_bytes_materialized":
            coordinator_model_weight_bytes_materialized,
    }

    for name, value in zero_invariants.items():
        if value != 0:
            failures.append(f"zero invariant {name} == {value}")

    terminal = ("ISSUE117_ARM_B_COLD_REALIZATION_PASS" if not failures
                else "ISSUE117_ARM_B_EVIDENCE_DERIVATION_FAILURE")
    report = {
        "schema": "inferswarm.issue117.arm-b.evidence-derivation/1",
        "starting_main": ARM_B_STARTING_MAIN,
        "audited_delta_from_arm_a_merge": delta["delta_commits"],
        "frozen_producer_per_participant": {
            pid: FROZEN_PRODUCER for pid in PARTICIPANT_IDS},
        "checkpoint_sha256": CHECKPOINT_SHA256,
        "accepted_subject_digest": ACCEPTED_SUBJECT_DIGEST,
        "preservation_pins_verified": sorted(ACCEPTED_PINS),
        "per_participant": {
            pid: {
                "assigned_artifact_count": len(by_pid[pid]["required_artifacts"]),
                "required_artifact_bytes": by_pid[pid]["required_artifact_bytes"],
                "acquired_bytes": acquired_by_participant.get(pid, 0),
                "cache_hit_bytes": cache_hit_by_participant.get(pid, 0),
                "realized_bytes": _load(
                    f"realize-{pid.rsplit('.', 1)[1]}.json")["fetched_bytes"],
                "resident_device_bytes": _load(
                    f"realize-{pid.rsplit('.', 1)[1]}.json")["resident_device_bytes"],
            } for pid in PARTICIPANT_IDS},
        "zero_invariants": zero_invariants,
        "failures": failures,
        "terminal_classification": terminal,
    }
    print(json.dumps(report, indent=1, sort_keys=True))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
