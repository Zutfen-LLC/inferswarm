#!/usr/bin/env python3
"""Issue #182 — Arm-E terminal reduction (CPU-only, stdlib, fail-closed).

Re-derives the Arm-E terminal from the retained campaign records only:

- authority.json (frozen before observation; producer hashes verified)
- warm-inventory-<host>.json (fresh read-only observation, per host)
- comparison.json (two-arm planning comparison)

No stored pass/equal/unchanged boolean is authority: every acceptance
condition is re-derived from the underlying records. The comparison's
own problems list is re-checked, not trusted: the reducer independently
re-derives gate-ledger equality, locality causality, and selection
safety from the per-candidate rows retained in the comparison record.

Terminals:
- ISSUE117_ARM_E_LOCALITY_MUTATION_PASS  (all invariants hold)
- ISSUE117_ARM_E_LOCALITY_MUTATION_FAIL  (admissible comparison violates)
- ISSUE117_ARM_E_EVIDENCE_BLOCKED        (pre-comparison authority or
  observation STOP fired; never a relabel of a valid planning failure)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import issue182_campaign_pins as P  # noqa: E402

from issue74_methodology import canonical_json_bytes  # noqa: E402

MIN_TRANSITION_COST = "MIN_TRANSITION_COST"

#: probes whose successful receipts the terminal re-verifies
REQUIRED_RECEIPTS = ("ps", "ss:18080", "ss:18485", "ss:18486", "nvidia-smi")


def _parse_gpu_mib(text) -> int | None:
    try:
        return int(str(text).split()[0])
    except (ValueError, IndexError):
        return None


def observation_record_digest(record: dict) -> str:
    """Recompute the collector's record self-digest."""
    return hashlib.sha256(json.dumps(
        {k: v for k, v in record.items() if k != "record_digest"},
        sort_keys=True).encode()).hexdigest()


def accepted_object_sets() -> dict:
    """Independently re-derive the accepted verified object sets from
    the RETAINED accepted Arm-B post-acquisition inventories (review
    lanes A/B: a rebuilt authority with a doctored sidecar must not
    survive the terminal even when every digest is re-bound)."""
    per_node = {}
    for node in P.OBSERVATION_HOSTS:
        path = P.ARM_B / f"inventory-post-{node}.json"
        document = json.loads(path.read_text())
        per_node[node] = {(obj["content_digest"], obj["length"])
                          for obj in document["verified_objects"]}
    return per_node


def normalized_object_set(record: dict) -> set:
    return {(obj["content_digest"], obj["length"])
            for obj in record.get("verified_objects") or []
            if obj.get("byte_digest_verified")}


#: content-authenticated cache for the comparison re-derivation (the
#: planner runs are deterministic; identical retained inputs must not
#: pay re-derivation twice within one process)
_REDERIVATION_CACHE: dict[tuple, str | None] = {}


def rederive_comparison_digest(authority_path: Path,
                               record_01: dict, record_03: dict) -> str | None:
    """Re-derive the ENTIRE comparison document from retained bytes and
    return its canonical digest (None if the derivation fails closed).

    Review round 2 (lanes A/B P0-1/P0-2, lane B P1-1): the terminal
    must never trust authored row content — economics, gate ledgers,
    admissibility — because cross-arm coupling checks cannot detect a
    jointly forged self-consistent comparison. The only authority is
    the deterministic rebuild over the pinned Arm-B inputs, the frozen
    authority, and the retained observation records.
    """
    import issue182_compare as C  # noqa: PLC0415  (lazy, stdlib-only)
    key = (hashlib.sha256(authority_path.read_bytes()).hexdigest(),
           observation_record_digest(record_01),
           observation_record_digest(record_03))
    if key not in _REDERIVATION_CACHE:
        try:
            document = C.build_comparison_document(
                authority_path, record_01, record_03)
            _REDERIVATION_CACHE[key] = hashlib.sha256(
                canonical_json_bytes(document)).hexdigest()
        except SystemExit:
            _REDERIVATION_CACHE[key] = None
    return _REDERIVATION_CACHE[key]


def gpu_used_from_receipt_stdout(receipt) -> dict:
    """Re-derive {uuid: memory_used} from the retained nvidia-smi
    receipt stdout (review round 2 lane B P1-2: the collector's
    stdout-to-row derivation must not be trusted post-hoc)."""
    rows = {}
    if receipt is None or receipt.get("returncode") != 0:
        return rows
    for line in (receipt.get("stdout") or "").splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) >= 5:
            rows[parts[1]] = parts[3]
    return rows


def load(path: Path) -> dict:
    return json.loads(path.read_text())


def rederive_problems(comparison: dict) -> list[str]:
    """Independently re-derive the comparison invariants from rows."""
    problems: list[str] = []
    cold_rows = comparison["cold_arm"]["rows"]
    warm_rows = comparison["warm_arm"]["rows"]
    if comparison.get("objective") != MIN_TRANSITION_COST:
        problems.append("objective drift")
    if sorted(cold_rows) != sorted(warm_rows):
        problems.append("candidate set drift between arms")
    for candidate_id, cold_row in cold_rows.items():
        warm_row = warm_rows[candidate_id]
        if cold_row["gates"] != warm_row["gates"]:
            problems.append(f"{candidate_id}: gate ledger changed")
        if cold_row["admissible"] != warm_row["admissible"]:
            problems.append(f"{candidate_id}: admissibility moved")
        # safety: a failed non-ranking gate in cold may never pass in warm
        for gate in ("technical_feasibility", "hard_policy_eligible",
                     "integrity_eligible"):
            if not cold_row["gates"][gate].get("passed", False) and \
                    warm_row["gates"][gate].get("passed", False):
                problems.append(
                    f"{candidate_id}: gate {gate} failed-cold passes-warm")
        cold_q = cold_row["gates"]["qualification_applicability"]["status"]
        warm_q = warm_row["gates"]["qualification_applicability"]["status"]
        if cold_q != "QUALIFICATION_APPLICABLE" and \
                warm_q == "QUALIFICATION_APPLICABLE":
            problems.append(
                f"{candidate_id}: qualification became applicable in warm")
        if not warm_row["admissible"] and \
                warm_row["ranking_status"] == "RANKED":
            problems.append(f"{candidate_id}: inadmissible but ranked")
    v5 = P.SUBJECT["candidate"]
    cold_v5, warm_v5 = cold_rows[v5], warm_rows[v5]
    if not cold_v5["admissible"] or not warm_v5["admissible"]:
        problems.append("V5 candidate not admissible")
    if warm_v5["missing_bytes"] > cold_v5["missing_bytes"]:
        problems.append("warm missing bytes increased")
    if (cold_v5["missing_bytes"] == warm_v5["missing_bytes"]
            and cold_v5["ranking_value"] != warm_v5["ranking_value"]):
        problems.append("economics moved without locality change")
    if cold_v5["missing_bytes"] != warm_v5["missing_bytes"] and \
            cold_v5["ranking_value"] == warm_v5["ranking_value"]:
        problems.append("locality moved without economics change")
    if comparison["warm_arm"]["selected_candidate_id"] not in (None, v5):
        problems.append("warm selection is an unqualified candidate")
    # cold economics must be non-zero-derived (missing bytes priced)
    if cold_v5["ranking_status"] != "RANKED":
        problems.append("V5 candidate unranked in cold arm")
    if warm_v5["ranking_status"] != "RANKED":
        problems.append("V5 candidate unranked in warm arm")
    return problems


def reduce_terminal(evidence_dir: Path) -> dict:
    authority = load(evidence_dir / "authority.json")
    if authority.get("schema") != P.AUTHORITY_SCHEMA:
        raise SystemExit("ISSUE182_TERMINAL_FAIL: authority schema")
    if authority.get("campaign_id") != P.CAMPAIGN_ID:
        raise SystemExit("ISSUE182_TERMINAL_FAIL: campaign identity")

    # observation records: any STOP rule fired -> BLOCKED
    stop_problems = []
    planning_evidence = {
        "hosts": [], "gpu_state": [], "probe_failures": [],
        "byte_preservation_hosts": [],
    }
    for host in P.OBSERVATION_HOSTS:
        record = load(evidence_dir / f"observation/warm-inventory-{host}.json")
        if record.get("schema") != P.INVENTORY_SCHEMA:
            raise SystemExit(
                f"ISSUE182_TERMINAL_FAIL: inventory schema {host}")
        if record.get("attempt_id") != P.ATTEMPT_ID:
            stop_problems.append({
                "host": host,
                "stop_rule": "OBS-OBSERVATION-EPOCH-INVALID",
                "detail": "attempt id does not match the frozen attempt"})
        for problem in record.get("problems") or []:
            stop_problems.append({"host": host, **problem})
        if not record.get("byte_preservation_proven"):
            stop_problems.append({
                "host": host, "stop_rule": "OBS-MUTATION-DETECTED",
                "detail": "byte_preservation_proven false"})
        fence = record.get("fence") or {}
        if fence.get("processes"):
            stop_problems.append({
                "host": host, "stop_rule": "OBS-PROCESSES-LIVE"})
        # P1-1: an empty observation is admissible ONLY against
        # retained successful probe receipts
        receipts = fence.get("probe_receipts") or {}
        for probe_name in ("ps", "ss:18080", "ss:18485", "ss:18486",
                           "nvidia-smi"):
            receipt = receipts.get(probe_name)
            if receipt is None or receipt.get("returncode") != 0:
                stop_problems.append({
                    "host": host, "stop_rule": "OBS-PROBE-FAILED",
                    "probe": probe_name})
        # P1-2: freshness identity re-derived against the live authority
        epoch = record.get("observation_epoch") or {}
        if (epoch.get("authority_digest") != authority.get("authority_digest")
                or epoch.get("campaign_id") != P.CAMPAIGN_ID
                or epoch.get("attempt_id") != P.ATTEMPT_ID
                or epoch.get("host") != host
                or epoch.get("sequence") != P.OBSERVATION_SEQUENCE):
            stop_problems.append({
                "host": host, "stop_rule": "OBS-OBSERVATION-EPOCH-INVALID"})
        # P1-3: content-address identity proven for every object
        for obj in record.get("verified_objects") or []:
            if not obj.get("content_address_verified"):
                stop_problems.append({
                    "host": host,
                    "stop_rule": "OBS-CONTENT-ADDRESS-MISMATCH",
                    "object": obj.get("host_path")})
                break
        # review lane B: the record's self-digest must verify (a
        # post-hoc tampered record with a stale digest fails closed)
        if record.get("record_digest") != observation_record_digest(record):
            stop_problems.append({
                "host": host,
                "stop_rule": "OBS-RECORD-DIGEST-MISMATCH"})
        # review lane B: the verified object set must EQUAL the set
        # independently re-derived from the RETAINED accepted Arm-B
        # post-acquisition inventories — a rebuilt authority with a
        # doctored sidecar cannot survive this even fully re-bound
        accepted = accepted_object_sets().get(host, set())
        observed = normalized_object_set(record)
        if observed != accepted:
            stop_problems.append({
                "host": host,
                "stop_rule": "OBS-UNACCEPTED-CACHE-OBJECT",
                "detail": {
                    "missing": sorted(accepted - observed)[:3],
                    "extra": sorted(observed - accepted)[:3]}})
        # review lane B: GPU totals re-checked against the frozen pins
        for gpu in fence.get("gpus") or []:
            total = _parse_gpu_mib(gpu.get("memory_total"))
            uuid = gpu.get("uuid")
            cu_id = next((f"{host}/gpu-{index}"
                          for index, pinned_uuid in
                          P.FROZEN_HOST_GPU_UUIDS.get(host, {}).items()
                          if pinned_uuid == uuid), None)
            pinned_total = P.PINNED_GPU_TOTAL_BYTES.get(cu_id) \
                if cu_id else None
            if pinned_total is not None and total is not None \
                    and total * 1024 * 1024 != pinned_total:
                stop_problems.append({
                    "host": host, "stop_rule": "OBS-GPU-TOTAL-DRIFT",
                    "cu": cu_id, "pinned": pinned_total,
                    "actual": total * 1024 * 1024})
        # P1-1: every frozen GPU of the host observed, parseable,
        # pinned total, idle within the frozen bound (re-derived here
        # from the record's GPU rows, not trusted from the collector)
        observed_uuids = {gpu.get("uuid") for gpu in fence.get("gpus") or []}
        pinned_uuids = set(P.FROZEN_HOST_GPU_UUIDS.get(host, {}).values())
        if observed_uuids != pinned_uuids:
            stop_problems.append({
                "host": host, "stop_rule": "OBS-GPU-SET-MISMATCH"})
        for gpu in fence.get("gpus") or []:
            used = _parse_gpu_mib(gpu.get("memory_used"))
            total = _parse_gpu_mib(gpu.get("memory_total"))
            if used is None or total is None:
                stop_problems.append({
                    "host": host,
                    "stop_rule": "OBS-GPU-TELEMETRY-UNPARSEABLE",
                    "uuid": gpu.get("uuid")})
            elif used > P.GPU_MEMORY_USED_MAX_MIB:
                stop_problems.append({
                    "host": host, "stop_rule": "OBS-GPU-NOT-IDLE",
                    "uuid": gpu.get("uuid"),
                    "memory_used_mib": used})
        # planning-only derivation evidence (comment 5666244858: the
        # terminal fields below are DERIVED from these retained facts,
        # not authored as literal booleans)
        planning_evidence["hosts"].append(host)
        if record.get("byte_preservation_proven"):
            planning_evidence["byte_preservation_hosts"].append(host)
        # review round 2 lane B P2: byte preservation is RE-DERIVED
        # from the retained before/after tree digests, not trusted
        # from the boolean
        if (record.get("preservation_before", {}).get("tree_digest")
                != record.get("preservation_after", {}).get("tree_digest")):
            stop_problems.append({
                "host": host, "stop_rule": "OBS-MUTATION-DETECTED",
                "detail": "before/after tree digests differ"})
        # review round 2 lane B P1-2: GPU memory_used is RE-DERIVED
        # from the retained nvidia-smi receipt stdout, not trusted
        # from the fence rows
        used_from_stdout = gpu_used_from_receipt_stdout(
            (fence.get("probe_receipts") or {}).get("nvidia-smi"))
        for gpu in fence.get("gpus") or []:
            row_used = gpu.get("memory_used")
            stdout_used = used_from_stdout.get(gpu.get("uuid"))
            if stdout_used is not None and row_used != stdout_used:
                stop_problems.append({
                    "host": host, "stop_rule": "OBS-GPU-TELEMETRY-DRIFT",
                    "uuid": gpu.get("uuid"),
                    "row": row_used, "receipt_stdout": stdout_used})
        for gpu in fence.get("gpus") or []:
            planning_evidence["gpu_state"].append({
                "host": host, "uuid": gpu.get("uuid"),
                "memory_used": gpu.get("memory_used")})
        for probe_name, receipt in sorted(
                (fence.get("probe_receipts") or {}).items()):
            if receipt.get("returncode") != 0:
                planning_evidence["probe_failures"].append(
                    {"host": host, "probe": probe_name})
        # review round 2 lane B P3: the record names its collector;
        # bind it to the frozen authority producer hash
        collector_hash = authority.get("producer_hashes", {}).get(
            "issue182_inventory.py")
        if (record.get("collector_sha256") and collector_hash
                and record["collector_sha256"] != collector_hash):
            stop_problems.append({
                "host": host,
                "stop_rule": "OBS-COLLECTOR-IDENTITY-MISMATCH"})

    comparison = load(evidence_dir / "comparison.json")
    if comparison.get("schema") != P.COMPARISON_SCHEMA:
        raise SystemExit("ISSUE182_TERMINAL_FAIL: comparison schema")
    # review round 2 lane A P2-4: comparison identity is bound, not
    # just its schema
    if (comparison.get("campaign_id") != P.CAMPAIGN_ID
            or comparison.get("attempt_id") != P.ATTEMPT_ID):
        raise SystemExit("ISSUE182_TERMINAL_FAIL: comparison identity")

    # review lane A: the retained comparison's warm arm must be
    # CROSS-BOUND to the observation records — the warm snapshot each
    # arm consumed is re-derived from the record's verified object set
    # and its canonical identity pinned in the comparison document, so
    # a comparison authored over DIFFERENT inventory bytes than the
    # retained observation cannot terminate PASS
    if not stop_problems:
        warm_bindings = comparison.get("warm_arm_binding") or {}
        for host in P.OBSERVATION_HOSTS:
            record = load(
                evidence_dir / f"observation/warm-inventory-{host}.json")
            snapshot = {
                "node_id": record["host"],
                "sequence": P.OBSERVATION_SEQUENCE,
                "source": {"source_id": record["host"],
                           "endpoint": f"file://{P.CACHE_ROOT}"},
                "verified_objects": [
                    {"content_digest": obj["content_digest"],
                     "length": obj["length"],
                     "byte_digest_verified": bool(
                         obj["byte_digest_verified"])}
                    for obj in record["verified_objects"]],
                "entries": [],
            }
            digest = hashlib.sha256(
                canonical_json_bytes(snapshot)).hexdigest()
            binding = warm_bindings.get(host) or {}
            if (binding.get("snapshot_canonical_sha256") != digest
                    or binding.get("object_count")
                    != len(record["verified_objects"])
                    or binding.get("sequence") != P.OBSERVATION_SEQUENCE):
                stop_problems.append({
                    "host": host,
                    "stop_rule": "OBS-WARM-ARM-BINDING-MISMATCH"})

    # review round 2 (lanes A/B, P0-1/P0-2 + lane B P1-1): the ENTIRE
    # comparison document is re-derived from retained bytes (pinned
    # Arm-B planning inputs + frozen authority + the retained
    # observation records) and byte-compared against the retained
    # comparison. A self-consistent forged comparison — fabricated
    # economics, jointly flipped gate ledgers — cannot survive this:
    # the rebuild produces the authoritative rows.
    if not stop_problems:
        records = {
            host: load(
                evidence_dir / f"observation/warm-inventory-{host}.json")
            for host in P.OBSERVATION_HOSTS}
        rederived_digest = rederive_comparison_digest(
            evidence_dir / "authority.json",
            records["inferswarm01"], records["inferswarm03"])
        retained_digest = hashlib.sha256(
            canonical_json_bytes(comparison)).hexdigest()
        if rederived_digest != retained_digest:
            stop_problems.append({
                "host": "comparison",
                "stop_rule": "OBS-COMPARISON-REDERIVATION-MISMATCH",
                "detail": {
                    "retained": retained_digest,
                    "rederived": rederived_digest}})

    if stop_problems:
        terminal = P.BLOCKED_TERMINAL
        problems = [f"stop:{p['stop_rule']}@{p['host']}" for p in stop_problems]
    else:
        problems = rederive_problems(comparison)
        # stored problems list must equal the re-derived one
        if sorted(comparison.get("problems") or []) != sorted(problems):
            problems.append("stored problems disagree with re-derived set")
        terminal = P.PASS_TERMINAL if not problems else P.FAIL_TERMINAL

    v5 = P.SUBJECT["candidate"]
    cold_v5 = comparison["cold_arm"]["rows"][v5]
    warm_v5 = comparison["warm_arm"]["rows"][v5]

    # planning-only fields are DERIVED from the retained observation
    # records, never authored as literal booleans (maintainer comment
    # 5666244858). The fence receipts prove no execution-bearing
    # process was live and no probe failed; GPU telemetry proves every
    # observed GPU idle; byte preservation proves no cache bytes were
    # touched; no retained campaign record references the forbidden
    # namespace.
    def _gpu_idle(gpu: dict) -> bool:
        try:
            return int(str(gpu["memory_used"]).split()[0]) <= \
                P.GPU_MEMORY_USED_MAX_MIB
        except (ValueError, IndexError, KeyError):
            return False

    planning_only = {
        "no_model_execution": bool(
            planning_evidence["hosts"])
            and not planning_evidence["probe_failures"]
            and all(not _procs for _procs in [
                (load(evidence_dir / f"observation/warm-inventory-{h}.json")
                 .get("fence") or {}).get("processes")
                for h in planning_evidence["hosts"]]),
        "no_gpu_initialization": bool(planning_evidence["gpu_state"])
            and all(_gpu_idle(g) for g in planning_evidence["gpu_state"]),
        "no_artifact_acquisition": (
            sorted(planning_evidence["byte_preservation_hosts"])
            == sorted(P.OBSERVATION_HOSTS)),
        "no_h109_access": all(
            P.FORBIDDEN_NAMESPACE not in json.dumps(record)
            for record in [load(
                evidence_dir / f"observation/warm-inventory-{h}.json")
                for h in P.OBSERVATION_HOSTS]),
        "derivation": (
            "no_model_execution: every retained fence receipt succeeded "
            "and no execution-bearing process was live; "
            "no_gpu_initialization: every observed GPU memory.used is "
            "within the frozen idle bound; no_artifact_acquisition: "
            "before/after byte preservation proven on every observation "
            "host; no_h109_access: no retained campaign record mentions "
            "the forbidden namespace"),
    }

    document = {
        "schema": P.TERMINAL_SCHEMA,
        "campaign_id": P.CAMPAIGN_ID,
        "physical_authorization_id": P.PHYSICAL_AUTHORIZATION_ID,
        "attempt_id": P.ATTEMPT_ID,
        "note": ("mechanically re-derived from retained bytes; no authored "
                 "terminal/pass/equality boolean consulted"),
        "problems": problems,
        "v5": {
            "missing_bytes_cold": cold_v5["missing_bytes"],
            "missing_bytes_warm": warm_v5["missing_bytes"],
            "required_bytes": cold_v5["required_bytes"],
            "transition_seconds_cold": cold_v5["ranking_value"],
            "transition_seconds_warm": warm_v5["ranking_value"],
        },
        "selection": {
            "cold": comparison["cold_arm"]["selected_candidate_id"],
            "warm": comparison["warm_arm"]["selected_candidate_id"],
        },
        "gate_ledger_unchanged": comparison.get("all_gates_unchanged"),
        "planning_only": planning_only,
        "terminal": terminal,
    }
    return document


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, default=P.EVIDENCE_DIR)
    parser.add_argument("--out", type=Path,
                        default=P.EVIDENCE_DIR / "terminal-reduction.json")
    args = parser.parse_args()
    document = reduce_terminal(args.evidence)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")
    print(json.dumps({
        "terminal": document["terminal"],
        "problems": document["problems"],
    }, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
