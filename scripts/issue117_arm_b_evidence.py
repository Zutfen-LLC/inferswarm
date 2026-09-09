#!/usr/bin/env python3
"""Issue #117 Arm-B retained-evidence reducer (pure stdlib, CPU-only).

Re-derives the Arm-B terminal classification and every mandatory zero
invariant from the retained low-level Arm-B records under
docs/implementation/r6-successor-dense-full-integration-117/evidence/arm-b/.
Fails closed: a stored "zero"/"PASS" is never authority; every value is
recomputed from the underlying records the physical campaign retained.

AUTHORITY LADDER (per mandatory zero invariant, lowest evidence first).
Each entry names the LOWEST retained evidence that establishes the
invariant; stored summaries appear only as cross-checks:

  unrelated_model_bytes_acquired_for_realization
      RAW acquisition-ledger events (per-event artifact_id -> planned
      required-artifact binding; recomputed sums) [ledgers]
  unassigned_model_weight_bytes_acquired
      RAW ledger ACQUIRED events vs the frozen requirements set
  unexplained_full_model_dependency
      read-audit per-path classification, every bucket (whole-model
      weight paths) + assemble object listing
  participant_requires_complete_model_repository
      read-audit per-path classification (ANY Source-tree read) +
      assemble byte total vs the whole-checkpoint size bound
  coordinator_bulk_artifact_bytes_observed
      RAW source-server access log (raw/source-server-access.log,
      parsed by scripts/issue117_parsers/source_server_log.py: sha256-
      pinned, then client histogram + coordinator count derived from
      the raw lines) + observed coordinator state-tree inventory
      (observations/coordinator-state-inventory.json, derived by
      scripts/issue117_parsers/coordinator_state.py)
  unverified_state_used_as_locality_evidence
      post-acquisition inventory verified_objects flags
  unauthorized_source_used
      RAW ledger ACQUIRED source_id fields
  unexplained_transition_bytes
      RAW ledger aggregates vs event-derived sums
  unexplained_persistent_host_mirror_bytes
      realize reports' runtime staging fields (persistent_host_model_
      bytes, host_resident_tensor_keys, host_staging_current_bytes)
  unplanned_steady_state_model_state_movement_bytes
      (1) RAW realize-strace logs (raw/realize-strace.stage-N.log,
          parsed by scripts/issue117_parsers/realize_strace.py:
          sha256-pinned; zero model-state opens after the last shard
          open; zero cache/source opens across the whole log) —
          PATH-level support only, the trace cannot measure bytes;
      (2) runtime FINALIZATION-BOUNDARY counters in the realize
          reports (safetensors_mapping_open_count == close_count,
          host_staging_current_bytes == 0) whose semantics are fixed
          by the sha256-pinned producer sources retained under
          raw/producer/ (loader.py context managers close every
          mapping; stage_runtime.py raises if staging is retained;
          armb_realize_child.py arms the sentinel after construction
          and only serializes the report);
      (3) the retained read audits (path classification);
      the invariant is established by the finalized-state invariant +
      zero post-boundary opens, NOT by byte measurement and NOT by
      any stored summary zero.
  runtime_fallback_events
      realize reports (per-stage substrate fields) + raw-strace
      nvidia-node opens
  silent_plan_substitution_events
      coordinator-record vs requirements vs execution-plan digests
  coordinator_cuda_initialized
      coordinator-counters cuda_observations (derived there from
      device nodes/smi/process fds/importability)
  coordinator_model_weight_bytes_received
      RECEIPT-PATH derivation (round 4): zero coordinator requests in
      the RAW source-server log + the Source HTTP server as the only
      authorized remote model-byte path (frozen ledger transports) +
      every ACQUIRED event belonging to a participant + the
      digest-bound execution-session transport audit (zero
      coordinator/model-byte co-targeting commands; zero destructive
      ops on the coordinator or canonical roots) + the exact observed
      coordinator state set (no payload) + pinned producer semantics.
      Final occupancy is a cross-check, NEVER the derivation — a
      receive-then-delete history cannot derive zero.
  coordinator_model_weight_bytes_materialized
      received == 0 + accepted pre-campaign preflight coordinator
      model-state inventory zero + exact observed state holds no
      payload + pinned execution semantics have no coordinator
      materialization path. Occupancy-independent by construction.

Fail-closed states: any pin drift, any derivation disagreement, or any
missing raw/low-level input yields ISSUE117_ARM_B_EVIDENCE_DERIVATION_
FAILURE (never a PASS).

Usage: python3 scripts/issue117_arm_b_evidence.py
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path
from typing import NoReturn

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from issue117_parsers import realize_strace, source_server_log  # noqa: E402
from issue117_parsers import coordinator_state, producer_pins   # noqa: E402
from issue117_parsers import transport_audit                    # noqa: E402

AREA = ROOT / "docs" / "implementation" / "r6-successor-dense-full-integration-117"
EVIDENCE = Path(os.environ.get("PINS_ROOT") or (AREA / "evidence"))
ARM_B = Path(os.environ.get("ARM_B_EVIDENCE_ROOT") or (EVIDENCE / "arm-b"))
RAW = ARM_B / "raw"
OBS = ARM_B / "observations"

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
#: frozen campaign enumeration (retained logical ids, PR #127 correction):
#: six invalid launches + the one valid encompassing campaign, recovered
#: from the contemporaneous transcript and host evidence
#: (attempt-lineage.json schema /2). A lineage record that loses, adds,
#: or renames an attempt fails closed.
EXPECTED_ATTEMPT_IDS = (
    "i117-arm-b-cold-acquisition.launch-1",
    "i117-arm-b-cold-acquisition.launch-2",
    "i117-arm-b-cold-acquisition.launch-3",
    "i117-arm-b-cold-acquisition.launch-4",
    "i117-arm-b-cold-acquisition.launch-5",
    "i117-arm-b-cold-acquisition.launch-6",
    "i117-arm-b-cold-acquisition.campaign-1",
)
#: frozen per-id validity labels (third states fail closed)
EXPECTED_VALIDITY = {
    "i117-arm-b-cold-acquisition.launch-1": "INVALID",
    "i117-arm-b-cold-acquisition.launch-2": "INVALID",
    "i117-arm-b-cold-acquisition.launch-3": "INVALID",
    "i117-arm-b-cold-acquisition.launch-4": "INVALID",
    "i117-arm-b-cold-acquisition.launch-5": "INVALID",
    "i117-arm-b-cold-acquisition.launch-6": "INVALID",
    "i117-arm-b-cold-acquisition.campaign-1": "VALID",
}
#: frozen parent/child lineage (schema /2): launches 4-6 are nested
#: phase attempts of the valid campaign; launches 1-3 are outside it
EXPECTED_PARENTS = {
    "i117-arm-b-cold-acquisition.launch-1": None,
    "i117-arm-b-cold-acquisition.launch-2": None,
    "i117-arm-b-cold-acquisition.launch-3": None,
    "i117-arm-b-cold-acquisition.launch-4":
        "i117-arm-b-cold-acquisition.campaign-1",
    "i117-arm-b-cold-acquisition.launch-5":
        "i117-arm-b-cold-acquisition.campaign-1",
    "i117-arm-b-cold-acquisition.launch-6":
        "i117-arm-b-cold-acquisition.campaign-1",
    "i117-arm-b-cold-acquisition.campaign-1": None,
}
#: frozen per-attempt physical-execution flags (schema /2): relabeling
#: any dimension of physical execution vs correctness-bearing retention
#: fails closed, while keeping launch-6's honest combination (executed
#: to device residency, zero retained correctness-bearing records)
EXPECTED_EXECUTION_FLAGS = {
    "i117-arm-b-cold-acquisition.launch-1": (False, False, False),
    "i117-arm-b-cold-acquisition.launch-2": (False, False, False),
    "i117-arm-b-cold-acquisition.launch-3": (False, False, False),
    "i117-arm-b-cold-acquisition.launch-4": (False, False, False),
    "i117-arm-b-cold-acquisition.launch-5": (True, False, False),
    "i117-arm-b-cold-acquisition.launch-6": (True, True, True),
    "i117-arm-b-cold-acquisition.campaign-1": (True, True, True),
}
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


def _is_source_repository_path(path):
    """True for ANY path under the Source repository tree. During
    realization a participant must not read the Source repository at
    all — not only the weight file, but no auxiliary whole-repository
    model file either (tokenizer, config, index, …): the participant's
    declared dependency is its own materialized shard."""
    return isinstance(path, str) and (
        path == GEMMA_WEIGHT_PATH or path.startswith(GEMMA_ROOT))


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


def _sha256_text(text):
    return hashlib.sha256(text.encode()).hexdigest()


def _parse_raw_server_log():
    """Parse the RAW source-server log; a missing/drifted file fails
    closed (never falls back to a stored summary)."""
    try:
        return source_server_log.parse_file(RAW / "source-server-access.log")
    except (OSError, ValueError) as exc:
        _fail(f"raw source-server log unusable: {exc}")


def _parse_raw_strace():
    """Parse the three RAW realize-strace logs; any missing/drifted file
    fails closed."""
    facts = {}
    for pid, name in (
            ("dense.6171f32b4413.stage-1", "realize-strace.stage-1.log"),
            ("dense.6171f32b4413.stage-2", "realize-strace.stage-2.log"),
            ("dense.6171f32b4413.stage-3", "realize-strace.stage-3.log")):
        try:
            facts[pid] = realize_strace.parse_file(RAW / name)
        except (OSError, ValueError) as exc:
            _fail(f"raw strace log unusable ({pid}): {exc}")
    return facts


def _derive_coordinator_inventory():
    try:
        inventory = json.loads(
            (OBS / "coordinator-state-inventory.json").read_bytes())
    except (OSError, json.JSONDecodeError) as exc:
        _fail(f"coordinator state inventory unreadable: {exc}")
    derived = coordinator_state.derive(inventory)
    if derived["problems"]:
        _fail("coordinator state inventory derivation failed: "
              + "; ".join(derived["problems"]))
    # round-4 (P1-1): the eight operational files are retained
    # byte-exact under raw/coordinator/ and cross-bound to the frozen
    # pins — a substituted or drifted operational file fails closed
    raw_problems = coordinator_state.verify_raw_retention(RAW / "coordinator")
    if raw_problems:
        _fail("retained raw coordinator copies failed pin verification: "
              + "; ".join(raw_problems))
    return inventory, derived


def _verify_producer_pins():
    problems = producer_pins.verify(RAW / "producer")
    if problems:
        _fail("producer source pins failed: " + "; ".join(problems))


def main():
    failures = []

    # -- preservation pins ------------------------------------------------
    for name, expected in ACCEPTED_PINS.items():
        observed = _sha256(EVIDENCE / name)
        if observed != expected:
            failures.append(f"preservation pin {name} drifted: {observed}")

    # -- raw evidence (parsed directly; the authority for transport,
    #    movement support, and coordinator storage) ------------------------
    server = _parse_raw_server_log()
    strace_facts = _parse_raw_strace()
    _verify_producer_pins()
    inventory, coord_tree = _derive_coordinator_inventory()

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
            if pid not in records_by_pid:
                # round-4: a ledger event bound to a non-participant
                # (e.g. the coordinator) is a receipt-path violation —
                # report and fail closed instead of crashing
                failures.append(
                    f"{host} event participant {pid} is not a campaign "
                    "participant (coordinator receipt?)")
                continue
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
    for host, expected_objects in ((("inferswarm01"), None), (("inferswarm03"), None)):
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
        source_repository_reads = []
        for bucket, contents in audit.get("classified", {}).items():
            if isinstance(contents, list):
                whole_model_reads.extend(
                    p for p in contents if _is_whole_model_weight_path(p))
                source_repository_reads.extend(
                    p for p in contents if _is_source_repository_path(p))
        if whole_model_reads:
            unexplained_full_model_dependency += 1
            failures.append(
                f"{stage} read whole-model weights during realization: "
                f"{sorted(set(whole_model_reads))[:3]}")
        # the complete conjunction for repository completeness: ANY read
        # of the Source tree during realization (weights OR auxiliary
        # whole-repository files) is an undeclared repository dependency
        if source_repository_reads:
            participant_requires_complete_model_repository += 1
            failures.append(
                f"{stage} read the Source repository during realization "
                f"(undeclared whole-repository dependency): "
                f"{sorted(set(source_repository_reads))[:3]}")
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
        # RAW-strace cross-check: the parsed raw log must agree with the
        # read audit's own whole-model/cache buckets (a diverging audit
        # summary fails closed)
        raw_facts = strace_facts[pid]
        if raw_facts["cache_root_opens"] != 0 or \
                raw_facts["source_tree_opens"] != 0:
            failures.append(
                f"{stage} raw strace shows cache/source opens during "
                f"realization (cache={raw_facts['cache_root_opens']}, "
                f"source={raw_facts['source_tree_opens']})")

    # -- attempt lineage (schema /2; fail closed) ---------------------------
    # The lineage record is retained evidence, never authority: every
    # count below is re-derived from the acquisition ledgers, assemble
    # reports, realize reports, and read audits, and cross-checked
    # against the lineage record's own claims. Schema /2 additionally
    # separates physical execution from correctness-bearing retention
    # and pins the parent/child campaign structure.
    lineage = _load("attempt-lineage.json")
    attempts = lineage.get("attempts", [])
    attempt_ids = [a.get("attempt_id") for a in attempts]
    if len(set(attempt_ids)) != len(attempt_ids):
        failures.append("attempt lineage: duplicated attempt ids")
    if sorted(attempt_ids) != sorted(EXPECTED_ATTEMPT_IDS):
        failures.append(
            "attempt lineage: retained attempt set != the frozen campaign "
            "enumeration (missing or extra attempt)")
    by_id = {a.get("attempt_id"): a for a in attempts}
    valid = [a for a in attempts if a.get("validity") == "VALID"]
    invalid = [a for a in attempts if a.get("validity") == "INVALID"]
    # fail closed on any third validity state: every retained attempt must
    # be explicitly VALID or INVALID (a 'PENDING'/missing label must not
    # dodge the per-invalid enforcement below)
    unlabeled = [a.get("attempt_id") for a in attempts
                 if a.get("validity") not in ("VALID", "INVALID")]
    if unlabeled:
        failures.append(
            f"attempt lineage: attempts not explicitly VALID/INVALID: "
            f"{unlabeled}")
    # the frozen enumeration pins the per-id validity labels too
    for a in attempts:
        if a.get("validity") != EXPECTED_VALIDITY.get(a.get("attempt_id")):
            failures.append(
                f"attempt lineage: {a.get('attempt_id')} validity label "
                f"differs from the frozen campaign enumeration")
    if len(valid) != 1:
        failures.append(
            f"attempt lineage: expected exactly one VALID campaign, "
            f"found {len(valid)}")
    if not invalid:
        failures.append("attempt lineage: no invalid attempts retained")
    if lineage.get("valid_attempt_logical_id") != (
            valid[0].get("attempt_id") if valid else None):
        failures.append("attempt lineage: valid_attempt_logical_id mismatch")
    orderings = [a.get("ordering") for a in attempts]
    if sorted(orderings) != list(range(1, len(attempts) + 1)):
        failures.append("attempt lineage: ordering not a strict 1..N sequence")
    if valid and invalid and valid[0].get("ordering") != max(orderings):
        failures.append("attempt lineage: valid campaign does not follow "
                        "every invalid attempt")
    # schema /2: parent/child structure is pinned — launches 4-6 must be
    # nested subattempts of the valid campaign, launches 1-3 outside it
    for aid, expected_parent in EXPECTED_PARENTS.items():
        a = by_id.get(aid)
        if a is None:
            continue
        if a.get("parent_campaign_id") != expected_parent or \
                a.get("subattempt_of") != expected_parent:
            failures.append(
                f"attempt lineage: {aid} parent/child structure differs "
                f"from the frozen campaign nesting")
    if valid:
        camp = valid[0]
        declared_children = set(camp.get("subattempt_ids") or [])
        actual_children = {aid for aid, parent in EXPECTED_PARENTS.items()
                           if parent == camp.get("attempt_id")}
        if declared_children != actual_children:
            failures.append(
                "attempt lineage: campaign subattempt_ids != the frozen "
                "nested phase attempts")
        interval = camp.get("campaign_interval_utc_observed")
        if not (isinstance(interval, list) and len(interval) == 2
                and interval[0] <= interval[1]):
            failures.append("attempt lineage: campaign interval malformed")
    # observed timestamps must be consistent with the retained ordering.
    # Schema /2 semantics: launches 1-3 are serial pre-VALIDITY
    # iterations — each started BEFORE the campaign's acquisition
    # validity was established; launches 4-6 are in-campaign phase
    # failures INSIDE the campaign interval; the campaign's interval
    # must encompass every nested attempt, and no pre-validity launch
    # may start after validity was established (it would be a nested
    # phase attempt mislabeled as pre-validity, or a contradiction).
    if invalid:
        inv_seq = sorted(invalid, key=lambda a: a.get("ordering") or 0)
        prev_start = None
        for a in inv_seq:
            started = a.get("started_utc_observed")
            if not isinstance(started, str):
                failures.append(
                    f"attempt {a.get('attempt_id')} lacks observed start")
                continue
            if prev_start is not None and started < prev_start:
                failures.append(
                    f"attempt lineage: timestamp ordering contradicts "
                    f"retained ordering at {a.get('attempt_id')} "
                    f"(started {started} after-ordering but before "
                    f"{prev_start})")
            prev_start = started
        if valid:
            v = valid[0]
            interval = v.get("campaign_interval_utc_observed") or []
            v_started = interval[0] if len(interval) == 2 else \
                v.get("started_utc_observed")
            v_ended = interval[1] if len(interval) == 2 else \
                v.get("ended_utc_observed")
            validity_ts = v.get("acquisition_validity_established_utc")
            if not isinstance(validity_ts, str):
                failures.append(
                    "attempt lineage: campaign lacks the acquisition-"
                    "validity establishment timestamp")
            for a in inv_seq:
                aid = a.get("attempt_id")
                s = a.get("started_utc_observed")
                e = a.get("ended_utc_observed")
                nested = EXPECTED_PARENTS.get(aid) == v.get("attempt_id")
                if nested:
                    # nested phase attempt: must fall INSIDE the interval
                    # AND must start after acquisition validity was
                    # established (nested attempts are post-acquisition
                    # phase attempts by declared kind — a backdated
                    # start would silently re-label a pre-validity
                    # failure as an in-campaign one)
                    if isinstance(s, str) and isinstance(v_started, str) \
                            and s < v_started:
                        failures.append(
                            f"nested attempt {aid} started before the "
                            f"campaign interval began")
                    if isinstance(s, str) and isinstance(validity_ts, str) \
                            and s < validity_ts:
                        failures.append(
                            f"nested attempt {aid} started before the "
                            f"campaign's acquisition validity was "
                            f"established (backdated phase attempt)")
                    if isinstance(e, str) and isinstance(v_ended, str) \
                            and e > v_ended:
                        failures.append(
                            f"nested attempt {aid} ended after the "
                            f"campaign interval completed")
                else:
                    # pre-validity launch: must precede the campaign's
                    # acquisition-validity establishment
                    if isinstance(s, str) and isinstance(validity_ts, str) \
                            and s > validity_ts:
                        failures.append(
                            f"pre-validity attempt {aid} started after "
                            f"the campaign's acquisition validity was "
                            f"established (lineage contradiction)")
    # schema /2: physical execution vs correctness-bearing retention are
    # separate dimensions; per-invalid enforcement covers BOTH, and an
    # invalid attempt that physically executed a realization must not
    # be able to smuggle a correctness-bearing record
    for a in attempts:
        # every digest-bound transcript excerpt must re-verify
        ev = a.get("evidence")
        blocks = ev if isinstance(ev, list) else ([ev] if ev else [])
        if not blocks:
            failures.append(
                f"attempt {a.get('attempt_id')} retains no evidence block")
        for b in blocks:
            if not isinstance(b, dict):
                failures.append(
                    f"attempt {a.get('attempt_id')} malformed evidence block")
                continue
            verbatim = b.get("excerpt_verbatim")
            digest = b.get("excerpt_digest", "")
            if not isinstance(verbatim, str) or not verbatim:
                failures.append(
                    f"attempt {a.get('attempt_id')} evidence lacks a "
                    f"verbatim excerpt")
            elif "sha256:" + _sha256_text(verbatim) != digest:
                failures.append(
                    f"attempt {a.get('attempt_id')} excerpt digest does "
                    f"not bind its verbatim content")
        diag = a.get("diagnosis_output")
        if isinstance(diag, dict) and "sha256:" + _sha256_text(
                diag.get("excerpt_verbatim", "")) != \
                diag.get("excerpt_digest", "\x00"):
            failures.append(
                f"attempt {a.get('attempt_id')} diagnosis digest does not "
                f"bind its verbatim content")

    for a in invalid:
        aid = a.get("attempt_id")
        if a.get("verified_publications", 1) != 0:
            failures.append(f"invalid attempt {aid} claims a publication")
        if a.get("materializations", 1) != 0:
            failures.append(f"invalid attempt {aid} claims a materialization")
        # correctness-bearing retention (schema /2 fields)
        if a.get("correctness_bearing_realization_records", 1) != 0:
            failures.append(
                f"invalid attempt {aid} claims a correctness-bearing "
                f"realization record")
        if a.get("correctness_bearing_observations", 1) != 0:
            failures.append(
                f"invalid attempt {aid} claims a correctness observation")
        # physical execution flags must be internally consistent: a
        # device-resident attempt must have executed the realization path
        if a.get("device_residency_achieved") and not a.get(
                "realization_execution_reached"):
            failures.append(
                f"invalid attempt {aid} claims device residency without "
                f"realization execution (contradiction)")
        if a.get("realization_execution_reached") and not a.get(
                "realization_request_made"):
            failures.append(
                f"invalid attempt {aid} claims realization execution "
                f"without a request (contradiction)")
        # the frozen enumeration pins the execution flags per attempt:
        # relabeling physical execution or retention dimensions fails
        expected_flags = EXPECTED_EXECUTION_FLAGS.get(aid)
        if expected_flags is not None and (
                a.get("realization_request_made") != expected_flags[0]
                or a.get("realization_execution_reached") !=
                expected_flags[1]
                or a.get("device_residency_achieved") != expected_flags[2]):
            failures.append(
                f"invalid attempt {aid} execution-flag labels differ "
                f"from the frozen campaign enumeration")
        if a.get("canonical_cold_condition_preserved", {}).get("result") \
                is not True:
            failures.append(
                f"invalid attempt {aid} does not preserve the cold condition")
        if not a.get("canonical_cold_condition_preserved", {}).get("derivation"):
            failures.append(
                f"invalid attempt {aid} cold-preservation lacks derivation")
        if a.get("preexisting_cold_root_state_destroyed_or_reset"):
            failures.append(
                f"invalid attempt {aid} destroyed or reset cold-root state")
        # cleanup containment: any cleanup must be explicitly recorded as
        # either n/a, outside canonical roots, or an in-place overwrite
        # that destroyed nothing pre-existing
        loc = a.get("cleanup_location")
        if loc is not None and not isinstance(loc, str):
            failures.append(f"invalid attempt {aid} cleanup location malformed")
    # cold-condition structural proof (independent of stored booleans):
    # the retained prestate inodes must equal the observed inode record
    # (no root was ever recreated), and no destructive canonical-root
    # transition may be claimed anywhere
    inode_map = (lineage.get("cold_condition_summary", {})
                 .get("root_inode_continuity", {}))
    for host in ("inferswarm01", "inferswarm03"):
        pre = _load(f"cold-root-prestate-{host}.json")
        observed = inode_map.get("roots", {}).get(host, {})
        pinned = inode_map.get("retained_prestate_st_ino", {}).get(host, {})
        for root in ("/srv/inferswarm/cache/issue117",
                     "/srv/inferswarm/materialized/issue117"):
            st_ino = pre["roots"][root]["st_ino"]
            if observed.get(root) != st_ino or pinned.get(root) != st_ino:
                failures.append(
                    f"{host}:{root} inode continuity broken "
                    f"(prestate {st_ino}, observed {observed.get(root)}, "
                    f"pinned {pinned.get(root)})")
    # the observed inode record must agree with the independent fresh
    # observation under observations/ (regenerated read-only)
    try:
        inode_obs = json.loads(
            (OBS / "root-inode-continuity.json").read_bytes())
        for host in ("inferswarm01", "inferswarm03"):
            for root in ("/srv/inferswarm/cache/issue117",
                         "/srv/inferswarm/materialized/issue117"):
                if inode_obs["roots"][host][root]["st_ino"] != \
                        inode_map.get("roots", {}).get(host, {}).get(root):
                    failures.append(
                        f"{host}:{root} lineage inode disagrees with the "
                        f"observed inode record")
    except (OSError, KeyError, json.JSONDecodeError) as exc:
        failures.append(f"root-inode observation unusable: {exc}")
    # the valid campaign's ledger identity: the retained ledgers and
    # inventories must postdate every invalid acquisition attempt and
    # carry the frozen plan digest
    if valid:
        v = valid[0]
        if v.get("plan_digest") != plan["plan_digest"]:
            failures.append("valid campaign plan digest != retained plan digest")
        if v.get("verified_publications") != sum(
                len(_load(f"inventory-post-{h}.json")["verified_objects"])
                for h in ("inferswarm01", "inferswarm03")):
            failures.append("valid campaign publication count != inventory "
                            "object count")
        if v.get("materializations") != len(PARTICIPANT_IDS) or \
                v.get("correctness_bearing_realization_records") != \
                len(PARTICIPANT_IDS):
            failures.append("valid campaign materialization/correctness-"
                            "bearing realization count drift")
        if v.get("device_residency_achieved") is not True or \
                v.get("realization_execution_reached") is not True:
            failures.append("valid campaign lacks physical execution claims")

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
    # Round-4 (P1-2): received/materialized are RECEIPT-PATH semantics,
    # NOT final-occupancy semantics. Final weight-root occupancy is a
    # cross-check only — a receive-then-delete history would leave the
    # roots empty, so zero occupancy alone can NEVER establish zero
    # received. The derivation lives in the transport section below
    # (raw log + ledgers + frozen topology + transport audit +
    # exact-set coordinator state + pinned execution semantics).
    weight_roots = counters["weight_roots_bytes"]
    if set(weight_roots) != {
            "/srv/inferswarm/cache/issue117",
            "/srv/inferswarm/materialized/issue117",
            "/srv/inferswarm/models"}:
        failures.append("coordinator weight-roots key set drift")
    if any(v != 0 for v in weight_roots.values()):
        failures.append(
            "coordinator weight roots nonzero: final occupancy alone "
            "cannot carry the invariants (see receipt-path derivation)")
    coordinator_model_weight_bytes_received = None  # derived below
    coordinator_model_weight_bytes_materialized = None  # derived below
    coordinator_bulk_artifact_bytes_observed = None  # derived below from
    # the RAW source-server log + observed coordinator inventory

    # -- runtime fallback accounting (runtime evidence, NOT acquisition) ----
    fallback_doc = _load("runtime-fallback-accounting.json")
    runtime_fallback_events = 0
    for pid in PARTICIPANT_IDS:
        stage = pid.rsplit(".", 1)[1]
        rea = _load(f"realize-{stage}.json")
        entry = fallback_doc["per_stage"].get(pid)
        if entry is None:
            failures.append(f"runtime-fallback accounting missing {pid}")
            runtime_fallback_events += 1  # fail closed on missing evidence
            continue
        cu, gpu_uuid = EXPECTED_GEOMETRY[pid]
        # re-derive every fallback dimension from the low-level realize
        # report + RAW-strace facts; the stored per-stage counter is
        # only cross-checked, never authority
        wrong_gpu = (rea["gpu_uuid"] != gpu_uuid
                     or rea["observed_gpu_uuid"] != gpu_uuid)
        cpu_fallback = (rea["cpu_owned_decoder_layers"] != 0
                        or rea["persistent_host_model_bytes"] != 0
                        or bool(rea["host_resident_tensor_keys"]))
        backend_fallback = (rea["whole_shard_sentinel_calls"] != 0
                            or rea["host_staging_current_bytes"] != 0)
        host_exec = rea["resident_device_bytes"] < rea["fetched_bytes"]
        derived_stage_events = int(wrong_gpu or cpu_fallback
                                   or backend_fallback or host_exec)
        # cross-check the retained accounting record's own observations
        # against the realize report: a substituted observed UUID in
        # either record must fail
        if entry.get("observed_gpu_uuid") != rea["observed_gpu_uuid"] or \
                entry.get("plan_gpu_uuid") != rea["gpu_uuid"]:
            failures.append(
                f"{pid} runtime-fallback record GPU identity disagrees "
                f"with the realize report")
        if entry["wrong_gpu_substitution"] != wrong_gpu or \
                entry["cpu_model_state_fallback"] != cpu_fallback or \
                entry["backend_or_compat_fallback"] != backend_fallback or \
                entry["undeclared_host_execution"] != host_exec:
            failures.append(
                f"{pid} runtime-fallback record disagrees with realize report")
        # nvidia node opens now come from the RAW strace parse
        nvidia_nodes = strace_facts[pid]["nvidia_nodes_opened"]
        if entry.get("nvidia_device_nodes_opened") != nvidia_nodes:
            failures.append(
                f"{pid} runtime-fallback record nvidia nodes disagree "
                f"with the raw strace parse")
        if not ({"/dev/nvidiactl", "/dev/nvidia-uvm"} <= set(nvidia_nodes)):
            failures.append(
                f"{pid} CUDA execution path not established by device nodes")
            derived_stage_events += 1
        if entry.get("runtime_fallback_events_stage") != derived_stage_events:
            failures.append(
                f"{pid} stored stage fallback count disagrees with derivation")
        runtime_fallback_events += derived_stage_events
    if fallback_doc.get("total_runtime_fallback_events") != \
            runtime_fallback_events:
        failures.append("runtime-fallback total disagrees with per-stage sum")

    # -- steady-state movement accounting (schema /2) -----------------------
    # Two independent retained sources, BOTH required:
    #   (a) RAW strace path-opens (support; cannot measure bytes);
    #   (b) finalization-boundary lifecycle counters from the realize
    #       reports, whose semantics are fixed by the pinned producer
    #       sources (verified above via producer_pins).
    # A stored summary zero is never authority; if either source cannot
    # be established the invariant is NOT derived (fail closed).
    movement_doc = _load("steady-state-movement.json")
    unplanned_steady_state_model_state_movement_bytes = 0
    movement_establishable = True
    for pid in PARTICIPANT_IDS:
        stage = pid.rsplit(".", 1)[1]
        rea = _load(f"realize-{stage}.json")
        entry = movement_doc["per_stage"].get(pid)
        if entry is None:
            failures.append(f"steady-state movement missing {pid}")
            movement_establishable = False
            continue
        raw = strace_facts[pid]
        unexplained = 0
        movement_derived = True
        # (a) raw path-open facts
        if raw["cache_root_opens"] != 0 or raw["source_tree_opens"] != 0:
            unexplained += 1
            movement_derived = False
        if raw["model_state_opens_after_last_shard_open"]:
            unexplained += len(raw["model_state_opens_after_last_shard_open"])
            movement_derived = False
        # (b) finalization-boundary counters
        open_c = rea.get("safetensors_mapping_open_count")
        close_c = rea.get("safetensors_mapping_close_count")
        if not isinstance(open_c, int) or not isinstance(close_c, int) \
                or open_c != close_c or open_c == 0:
            failures.append(
                f"{pid} finalization counters unusable (mapping open/close"
                f" {open_c}/{close_c}): movement invariant NOT derivable")
            movement_derived = False
            unexplained += 1
        if rea.get("host_staging_current_bytes", -1) != 0 or \
                rea.get("persistent_host_model_bytes", -1) != 0:
            unexplained += (rea.get("host_staging_current_bytes", 0)
                            + rea.get("persistent_host_model_bytes", 0))
            movement_derived = False
        if rea.get("host_staging_total_bytes_processed", -1) != \
                rea.get("fetched_bytes", -2):
            failures.append(
                f"{pid} staging processed != fetched: byte identity broken")
            movement_derived = False
            unexplained += 1
        # cross-check the stored movement record against the raw parse
        smf = movement_doc.get("strace_facts", {}).get("stages", {}).get(pid, {})
        if smf.get("strace_sha256") != raw["strace_sha256"] or \
                smf.get("lines") != raw["lines"]:
            failures.append(
                f"{pid} stored strace facts disagree with the raw parse")
        # every stored path-open fact must equal the raw parse: a
        # mutated summary (histogram-style) without a raw-log change
        # fails here
        for field in ("shard_open_count", "cache_root_opens",
                      "source_tree_opens", "model_state_opens_total"):
            if smf.get(field) != raw[field]:
                failures.append(
                    f"{pid} stored strace fact '{field}' disagrees with "
                    f"the raw parse")
        if list(smf.get("model_state_opens_after_last_shard_open")
               or []) != raw["model_state_opens_after_last_shard_open"]:
            failures.append(
                f"{pid} stored post-boundary opens disagree with the raw "
                f"parse")
        fc = entry.get("finalization_counters", {})
        if fc.get("safetensors_mapping_open_count") != open_c or \
                fc.get("safetensors_mapping_close_count") != close_c or \
                fc.get("host_staging_current_bytes") != \
                rea.get("host_staging_current_bytes"):
            failures.append(
                f"{pid} stored finalization counters disagree with the "
                f"realize report")
        if entry.get("post_finalization_model_state_path_opens") != \
                raw["model_state_opens_after_last_shard_open"]:
            failures.append(
                f"{pid} stored post-boundary opens disagree with the raw "
                f"parse")
        if entry["unexplained_movement_bytes"] != unexplained:
            failures.append(
                f"{pid} stored unexplained movement disagrees with derivation")
        if entry["planned_initial_materialization_bytes"] != rea["fetched_bytes"]:
            failures.append(
                f"{pid} planned materialization bytes != fetched bytes")
        if not movement_derived:
            movement_establishable = False
        unplanned_steady_state_model_state_movement_bytes += unexplained
    if movement_doc.get("unplanned_steady_state_model_state_movement_bytes")\
            != unplanned_steady_state_model_state_movement_bytes:
        failures.append("steady-state movement total disagrees with sum")
    if not movement_establishable:
        # the invariant could not be established from retained evidence:
        # force the non-PASS terminal state with an explicit reason
        failures.append(
            "steady-state movement NOT establishable from retained "
            "evidence (finalization counters or raw trace unusable)")

    # -- coordinator bulk transport accounting -------------------------------
    # Derived from the RAW source-server log parse + the observed
    # coordinator state-tree inventory; the stored accounting record is
    # only cross-checked.
    transport_doc = _load("coordinator-transport-accounting.json")
    tdoc = transport_doc["derived_counters"]
    srv = transport_doc["low_level_observations"]["source_server_log"]
    ledger03 = _load("acquisition-ledger-inferswarm03.json")
    # raw-parse authority: coordinator clients on the only model-byte
    # network path
    if server["coordinator_get_requests"] != 0:
        failures.append(
            f"coordinator appeared in the RAW source-server log "
            f"({server['coordinator_get_requests']} GETs)")
    if server["client_ip_histogram"].get("10.0.0.219") != \
            ledger03["transport"]["requests"]:
        failures.append(
            "RAW source-server client count != 03 ledger requests")
    if server["get_requests"] != sum(server["client_ip_histogram"].values()):
        failures.append("RAW source-server histogram does not sum to total")
    if server["malformed_lines"] != 0:
        failures.append("RAW source-server log has malformed lines")
    # stored record must agree with the raw parse (histogram mutations
    # without a raw-log change fail here)
    if srv.get("client_ip_histogram") != server["client_ip_histogram"] or \
            srv.get("total_get_requests") != server["get_requests"] or \
            srv.get("coordinator_get_requests") != \
            server["coordinator_get_requests"]:
        failures.append(
            "stored source-server observations disagree with the RAW "
            "log parse")
    # inventory-derived storage dimension ( Finding 1B ): payload bytes
    # come from the observed inventory, never from a filename allowlist
    if coord_tree["model_payload_bytes_under_state_arm_b"] != 0 or \
            coord_tree["model_payload_files"]:
        failures.append(
            "coordinator state tree holds model payload bytes "
            f"({coord_tree['model_payload_files']})")
    cstate = transport_doc["low_level_observations"]["coordinator_state_tree"]
    if cstate.get("observed_file_count") != coord_tree["observed_file_count"] \
            or cstate.get("observed_total_bytes") != \
            coord_tree["observed_total_bytes"] \
            or cstate.get("data_file_total_bytes") != \
            coord_tree["data_file_total_bytes"] \
            or cstate.get("model_payload_bytes_under_state_arm_b") != \
            coord_tree["model_payload_bytes_under_state_arm_b"]:
        failures.append(
            "stored coordinator tree observations disagree with the "
            "observed inventory derivation")
    # per-file sum == stored numeric total == any embedded total in the
    # derivation text (Finding 3 regression: stale textual totals fail)
    data_files = {
        name: entry for name, entry in
        coordinator_state.ALLOWED_DATA_FILES.items()}
    derived_data_total = sum(size for size, _ in data_files.values())
    if cstate.get("data_file_total_bytes") != derived_data_total:
        failures.append(
            f"coordinator data-file total {cstate.get('data_file_total_bytes')}"
            f" != per-file sum {derived_data_total}")
    derivation_text = transport_doc.get("derivation", "")
    textual_total = str(derived_data_total)
    textual_commas = f"{derived_data_total:,}"
    for stale in ("34887199", "34,887,199"):
        if stale in derivation_text:
            failures.append(
                f"stale textual coordinator total '{stale}' survives in "
                f"the derivation text")
    if textual_total not in derivation_text and \
            textual_commas not in derivation_text:
        failures.append(
            "derivation text does not embed the corrected coordinator "
            "data-file total")
    # cross-bind the allowlisted ticket/plan/requirements digests to the
    # repo-retained copies (byte sizes AND digests; the coordinator-held
    # copies must equal the retained evidence copies)
    try:
        retained = {
            "source/arm-b-plan.json": ARM_B / "execution-plan.json",
            "source/arm-b-requirements.json": ARM_B / "requirements.json",
            "authorization/coordinator-deltas.json":
                ARM_B / "coordinator-deltas.json",
            "authorization/coordinator-record.json":
                ARM_B / "coordinator-record.json",
        }
        for name, path in retained.items():
            size, digest = coordinator_state.ALLOWED_DATA_FILES[name]
            if path.stat().st_size != size:
                failures.append(
                    f"coordinator-held {name} size != repo-retained copy")
            elif _sha256(path) != digest:
                failures.append(
                    f"coordinator-held {name} digest != repo-retained copy")
    except OSError as exc:
        failures.append(f"repo-retained coordinator copy unreadable: {exc}")
    # raw log pin cross-check against the observation record
    try:
        host_pins = json.loads(
            (OBS / "host-raw-log-pins.json").read_bytes())
        pin = host_pins["logs"]["source-server-access.log"]
        if pin["sha256"] != source_server_log.RAW_LOG_SHA256 or \
                pin["size_bytes"] != source_server_log.RAW_LOG_BYTES:
            failures.append(
                "host raw-log pin disagrees with the parser pins")
        for pid, name in (
                ("dense.6171f32b4413.stage-1", "realize-strace.stage-1.log"),
                ("dense.6171f32b4413.stage-2", "realize-strace.stage-2.log"),
                ("dense.6171f32b4413.stage-3", "realize-strace.stage-3.log")):
            pin = host_pins["logs"][name]
            if pin["sha256"] != realize_strace.RAW_STRACE_SHA256[name]:
                failures.append(
                    f"host raw-log pin disagrees for {name}")
    except (OSError, KeyError, json.JSONDecodeError) as exc:
        failures.append(f"host raw-log pins unusable: {exc}")
    derived_rx = derived_tx = derived_writes = derived_proxy = 0
    # -- coordinator receipt-path derivation (round-4 P1-2) -----------------
    # coordinator_model_weight_bytes_received == 0 is derived from the
    # ABSENCE OF ANY PERMITTED OR OBSERVED RECEIPT PATH, never from
    # final occupancy (which receive-then-delete would also satisfy):
    #   (a) zero coordinator requests in the retained RAW Source HTTP
    #       log, and the Source HTTP server was the only authorized
    #       remote model-byte path (frozen transport topology: the
    #       01 participant used local-file transport, the 03
    #       participant used operator-local-http from the Source host,
    #       both bound to their acquisition ledgers);
    #   (b) every ledger ACQUIRED event's participant is one of the two
    #       participants (never the coordinator);
    #   (c) the digest-bound command/transport audit of the
    #       contemporaneous execution session transcript: zero issued
    #       commands co-target the coordinator and a model-byte path,
    #       and zero destructive ops target the coordinator or any
    #       canonical root (so nothing was received-then-deleted by a
    #       session-issued command);
    #   (d) the exact observed coordinator state set (P1-1) contains no
    #       model payload;
    #   (e) the pinned producer sources fix the execution semantics:
    #       the acquisition engine (issue99_artifact_core) transfers
    #       bytes only Source->participant cache, and the coordinator
    #       driver (armb_coordinator.py, retained byte-exact under
    #       raw/coordinator/) issues tickets only — no byte path.
    ledger01 = _load("acquisition-ledger-inferswarm01.json")
    receipt_path_ok = True
    # (a) raw Source log: zero coordinator requests (checked against the
    # RAW parse above in the bulk-transport section; re-assert here as
    # a receipt-path condition)
    if server["coordinator_get_requests"] != 0:
        receipt_path_ok = False
    # frozen topology: only two transports exist in the ledgers
    if ledger01["transport"]["kind"] != "local-file":
        receipt_path_ok = False
        failures.append(
            "01 ledger transport kind drift: "
            f"{ledger01['transport'].get('kind')}")
    if ledger03["transport"]["kind"] != "operator-local-http":
        receipt_path_ok = False
        failures.append(
            "03 ledger transport kind drift: "
            f"{ledger03['transport'].get('kind')}")
    for led in (ledger01, ledger03):
        if led["transport"]["descriptor"]["source_id"] != "issue117-origin":
            receipt_path_ok = False
            failures.append("ledger source_id drift")
        if led["transport"]["descriptor"]["endpoint"] != \
                "file:///srv/models/gemma-r6":
            receipt_path_ok = False
            failures.append("ledger source endpoint drift")
    # 03's HTTP request count must equal the raw-log client count
    # (binding already enforced in the bulk-transport section; assert
    # as a receipt-path condition)
    if server["client_ip_histogram"].get("10.0.0.219") != \
            ledger03["transport"]["requests"]:
        receipt_path_ok = False
    # (b) every ACQUIRED event belongs to a participant
    for host in ("inferswarm01", "inferswarm03"):
        for event in _load(f"acquisition-ledger-{host}.json")["events"]:
            if event["event"] == "ACQUIRED" and event.get(
                    "participant_id") not in PARTICIPANT_IDS:
                receipt_path_ok = False
                failures.append(
                    f"ACQUIRED event participant {event.get('participant_id')}"
                    " is not a campaign participant (coordinator receipt?)")
    # (c) transport audit of the execution-session transcript
    try:
        audit = json.loads(
            (OBS / "coordinator-transport-audit.json").read_bytes())
        taudit = transport_audit.derive(audit)
        if taudit["problems"]:
            receipt_path_ok = False
            failures.extend(
                "transport-audit: " + p for p in taudit["problems"])
        if not taudit["zero_model_byte_cotargeting_commands"]:
            receipt_path_ok = False
            failures.append(
                "transport audit: a session-issued command co-targets the "
                "coordinator and a model-byte path")
        if not taudit["zero_destructive_coordinator_or_root_targeting"]:
            receipt_path_ok = False
            failures.append(
                "transport audit: destructive op targets the coordinator "
                "or a canonical root")
    except (OSError, json.JSONDecodeError) as exc:
        receipt_path_ok = False
        failures.append(f"coordinator transport audit unusable: {exc}")
    # (d) exact-set coordinator state carries no payload (P1-1)
    if coord_tree["problems"]:
        receipt_path_ok = False  # already failed closed in _derive step
    if coord_tree["model_payload_bytes_under_state_arm_b"] != 0 or \
            coord_tree["model_payload_files"]:
        receipt_path_ok = False
        failures.append(
            "coordinator state tree holds model payload bytes "
            f"({coord_tree['model_payload_files']})")
    # (e) pinned producer semantics: the byte-pinned acquisition engine
    # + the retained coordinator driver admit no coordinator byte path
    # (pins verified above via producer_pins + the retained raw
    # coordinator copies verified via coordinator_state pins)
    if receipt_path_ok:
        # no permitted path was used and no observed path exists: the
        # coordinator received zero model-weight bytes during the
        # campaign. Final occupancy (weight_roots all zero) is an
        # additional cross-check, never the derivation.
        coordinator_model_weight_bytes_received = 0
    else:
        coordinator_model_weight_bytes_received = -1
        failures.append(
            "coordinator receipt path not provably empty: received-bytes "
            "invariant NOT derivable (fail closed)")
    # -- materialization semantics (round-4 P1-2) ---------------------------
    # coordinator_model_weight_bytes_materialized == 0 is derived from:
    #   (1) received == 0 above (nothing arrived that could be stored);
    #   (2) the accepted pre-campaign physical preflight froze the
    #       coordinator as CPU-only with pre-campaign model-state
    #       inventory zero (resource_identity), so no usable Issue #117
    #       model source pre-existed on the coordinator;
    #   (3) the exact observed coordinator state set contains no model
    #       payload (P1-1 exact identity, not extension scanning);
    #   (4) the pinned execution semantics contain no coordinator
    #       materialization path (coordinator runs ticket issuance
    #       only; materialization is participant-side per the frozen
    #       plan/requirements and the pinned producer sources).
    # Clearing the final materialized directory alone cannot establish
    # this: (1)-(4) are all occupancy-independent.
    try:
        preflight = json.loads((EVIDENCE / "physical-preflight.json")
                               .read_bytes())
        ri = preflight["resource_identity"]
        preflight_coord_zero = (
            ri.get("coordinator", {}).get("node") == "inferswarm00"
            and ri.get("coordinator", {}).get("cpu_only") is True
            and ri.get("coordinator_model_weight_bytes_received") == 0
            and ri.get("coordinator_model_weight_bytes_materialized") == 0
            and ri.get("coordinator_cuda_initialized") == 0)
    except (OSError, KeyError, json.JSONDecodeError) as exc:
        preflight_coord_zero = False
        failures.append(f"physical preflight coordinator facts unusable: {exc}")
    if coordinator_model_weight_bytes_received == 0 \
            and preflight_coord_zero \
            and coord_tree["model_payload_bytes_under_state_arm_b"] == 0 \
            and not coord_tree["problems"]:
        coordinator_model_weight_bytes_materialized = 0
    else:
        coordinator_model_weight_bytes_materialized = -1
        if coordinator_model_weight_bytes_received != 0:
            failures.append(
                "materialized-zero cannot be derived: received-bytes "
                "derivation itself failed (occupancy is not authority)")
        else:
            failures.append(
                "materialized-zero derivation failed: pre-campaign "
                "coordinator inventory or exact observed state not "
                "established")
    # stored counters must equal the derived values
    if counters["coordinator_model_weight_bytes_received"] != \
            coordinator_model_weight_bytes_received:
        failures.append(
            "coordinator stored received-bytes counter disagrees with the "
            "receipt-path derivation")
    if counters["coordinator_model_weight_bytes_materialized"] != \
            coordinator_model_weight_bytes_materialized:
        failures.append(
            "coordinator stored materialized-bytes counter disagrees with "
            "the materialization derivation")
    # the transport-accounting record must describe the round-4
    # semantics (a record still claiming occupancy-based derivation
    # fails closed)
    if "occupancy" in transport_doc.get(
            "received_bytes_derivation", "occupancy") and \
            "receipt" not in transport_doc.get(
                "received_bytes_derivation", ""):
        failures.append(
            "transport record retains occupancy-based received-bytes "
            "derivation text")

    if server["coordinator_get_requests"] == 0 and \
            coord_tree["model_payload_bytes_under_state_arm_b"] == 0:
        # zero coordinator clients on the only network path + zero payload
        # bytes on coordinator storage => zero bulk artifact bytes
        coordinator_bulk_artifact_bytes_observed = 0
        if tdoc["coordinator_artifact_rx_bytes"] != derived_rx or \
                tdoc["coordinator_artifact_tx_bytes"] != derived_tx or \
                tdoc["coordinator_artifact_file_write_bytes"] != derived_writes or \
                tdoc["coordinator_artifact_proxy_bytes"] != derived_proxy:
            failures.append(
                "coordinator transport record counters disagree with "
                "low-level observations")
    else:
        coordinator_bulk_artifact_bytes_observed = -1
        failures.append("coordinator bulk bytes not derivable as zero")
    if coord["coordinator_bulk_artifact_bytes_observed"] != \
            coordinator_bulk_artifact_bytes_observed:
        failures.append(
            "stored coordinator bulk bytes disagree with low-level derivation")


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
        "schema": "inferswarm.issue117.arm-b.evidence-derivation/2",
        "starting_main": ARM_B_STARTING_MAIN,
        "audited_delta_from_arm_a_merge": delta["delta_commits"],
        "frozen_producer_per_participant": {
            pid: FROZEN_PRODUCER for pid in PARTICIPANT_IDS},
        "checkpoint_sha256": CHECKPOINT_SHA256,
        "accepted_subject_digest": ACCEPTED_SUBJECT_DIGEST,
        "preservation_pins_verified": sorted(ACCEPTED_PINS),
        "raw_evidence_parsed": {
            "source_server_log": {
                "path": "raw/source-server-access.log",
                "sha256": source_server_log.RAW_LOG_SHA256,
                "get_requests_derived": server["get_requests"],
                "client_ip_histogram_derived": server["client_ip_histogram"],
                "coordinator_get_requests_derived":
                    server["coordinator_get_requests"]},
            "realize_strace_logs": {
                pid: {"sha256": realize_strace.RAW_STRACE_SHA256[name],
                      "lines_derived": strace_facts[pid]["lines"]}
                for pid, name in (
                    ("dense.6171f32b4413.stage-1",
                     "realize-strace.stage-1.log"),
                    ("dense.6171f32b4413.stage-2",
                     "realize-strace.stage-2.log"),
                    ("dense.6171f32b4413.stage-3",
                     "realize-strace.stage-3.log"))},
            "coordinator_state_inventory": {
                "observed_file_count": coord_tree["observed_file_count"],
                "observed_total_bytes": coord_tree["observed_total_bytes"],
                "model_payload_bytes":
                    coord_tree["model_payload_bytes_under_state_arm_b"]},
            "producer_sources_pinned": len(producer_pins.PRODUCER_SHA256),
        },
        "movement_proof_method":
            "finalization-boundary lifecycle counters (mapping open==close, "
            "staging drained) + zero post-boundary model-state opens in the "
            "raw trace; see scripts/issue117_arm_b_evidence.py docstring",
        "coordinator_receipt_derivation": {
            "received": "receipt-path absence: zero coordinator requests "
                        "in the RAW source-server log; frozen ledger "
                        "transports (local-file on 01, operator-local-http "
                        "from the Source host on 03); every ACQUIRED event "
                        "participant-bound; execution-session transport "
                        "audit (zero model-byte co-targeting commands, "
                        "zero coordinator/root-targeting destructive ops); "
                        "exact observed coordinator state holds no payload; "
                        "pinned producer semantics. Final occupancy is a "
                        "cross-check only (receive-then-delete cannot "
                        "derive zero received).",
            "materialized": "received == 0 AND accepted pre-campaign "
                            "preflight coordinator model-state inventory "
                            "== 0 AND exact observed coordinator state "
                            "contains no model payload AND pinned "
                            "execution semantics contain no coordinator "
                            "materialization path.",
            "transport_audit_record":
                "observations/coordinator-transport-audit.json",
            "exact_coordinator_file_set":
                "14 files: 6 data (35,399,067 B) + 8 operational "
                "(46,008 B), each pinned by exact path/size/sha256; raw "
                "copies of all 8 operational files retained under "
                "raw/coordinator/",
        },
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
