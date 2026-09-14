#!/usr/bin/env python3
"""Issue #182 — Arm-E authority/freeze record builder (CPU-only, stdlib).

Freezes the Arm-E locality-mutation campaign authority BEFORE any fresh
physical inventory observation:

1. verifies actual heads: InferSwarm main at the accepted PR #181 merge
   head d4d50b20 (issue #182 starting authority) via git ancestry;
2. classifies ALL post-Arm-D drift (52c3b560-equivalent range: from the
   accepted #172 merge to current main) by file class — test/CI-only,
   documentation-only, or execution-bearing (none expected);
3. binds the frozen subject/candidate/plan/requirements identities and
   the accepted #117 CPU locality-mutation analog (loaded by digest,
   semantics consumed not reinterpreted);
4. binds the accepted Arm-D authority/terminal and the warm-inventory
   reference pins by file sha256;
5. binds the cold-arm source records: the retained Arm-B sequence-1
   pre-realization node inventory snapshots + frozen requirements +
   execution plan, each by sha256;
6. derives the technical capacity planning input method and the
   path-bandwidth figure from retained Arm-B acquisition-ledger bytes;
7. freezes the observation fence, normalization projection, attempt
   state machine, STOP rules, and non-claims;
8. records producer hashes for every correctness-bearing Arm-E script.

Fail-closed: any drift raises and writes nothing.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import issue182_campaign_pins as P  # noqa: E402

from issue74_methodology import canonical_json_bytes  # noqa: E402
from issue99_artifact_core import self_digest, validate_self_identity  # noqa: E402


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def git(repo: Path, args: list[str]) -> str:
    return subprocess.check_output(
        ["git", "-c", f"safe.directory={repo}", "-C", str(repo), *args],
        text=True).strip()


def is_ancestor(repo: Path, ancestor: str, descendant: str) -> bool:
    result = subprocess.run(
        ["git", "-c", f"safe.directory={repo}", "-C", str(repo),
         "merge-base", "--is-ancestor", ancestor, descendant])
    return result.returncode == 0


def verify_heads(inferswarm: Path) -> dict:
    proofs = {
        "merge_181_is_ancestor_of_main":
            is_ancestor(inferswarm, P.INFERSWARM_MERGE_181,
                        P.INFERSWARM_MAIN_182),
    }
    if not all(proofs.values()):
        raise SystemExit(f"ISSUE182_AUTHORITY_FAIL: ancestry {proofs}")
    return {
        "inferswarm_main": P.INFERSWARM_MAIN_182,
        "freetoken_inferswarm_research_retained": P.FREETOKEN_RESEARCH_182,
        "ancestor_proofs": proofs,
        "verified": True,
        "note": (
            "the accepted FreeToken producer is retained predecessor "
            "identity only; it is NOT executed in this planning-only arm"),
    }


def classify_drift(inferswarm: Path) -> dict:
    """Classify the accepted #172 merge..current-main file delta.

    Arm D already classified 52c3b560..246dcca8; this builder extends the
    same classification over 246dcca8..d4d50b20 (the accepted Arm-D
    campaign itself) so the WHOLE post-#172 delta is mechanically
    classified before Arm-E authority freezes.
    """
    names = git(inferswarm, [
        "diff", "--name-only",
        "52c3b560d560f69d0f009ed5772c1a70efc01ba2",
        P.INFERSWARM_MAIN_182]).splitlines()
    by_class = {"execution_bearing": [], "test_or_ci_only": [],
                "docs_only": [], "other": []}
    for name in names:
        if name.startswith(("benchmarks/", "python/freetoken/")):
            by_class["execution_bearing"].append(name)
        elif name.startswith(("tests/", "scripts/run_full_cpu_suite.py",
                              "scripts/plan_ci.py", "scripts/ci_groups.json",
                              ".github/")):
            by_class["test_or_ci_only"].append(name)
        elif name.startswith("scripts/issue175_"):
            # the accepted Arm-D campaign tooling itself: CPU-only stdlib
            # reduction/evidence scripts consumed by tests; explicitly
            # allowlisted so any OTHER scripts/ drift still fails closed
            by_class["test_or_ci_only"].append(name)
        elif name.startswith("docs/") or name.endswith(".md"):
            by_class["docs_only"].append(name)
        else:
            by_class["other"].append(name)
    if by_class["execution_bearing"] or by_class["other"]:
        raise SystemExit(
            "ISSUE182_AUTHORITY_FAIL: execution-bearing or unclassified "
            f"post-#172 drift {by_class}")
    commits = git(inferswarm, [
        "rev-list", "--count",
        f"52c3b560d560f69d0f009ed5772c1a70efc01ba2..{P.INFERSWARM_MAIN_182}"])
    return {
        "range": f"52c3b560..{P.INFERSWARM_MAIN_182}",
        "commit_count": int(commits),
        "changed_files_by_class": by_class,
        "classification": (
            "post-#172 drift through the accepted Arm-D merge is "
            "test/CI-orchestration-only and documentation-only; no "
            "execution-bearing change to the Issue #117 planner/"
            "artifact/locality semantics exists in the delta, so no "
            "applicability audit beyond this classification is required"),
    }


def bind_subject_and_plan() -> dict:
    """Bind subject, candidate, plan, requirements from retained bytes."""
    requirements = json.loads(P.ARM_B_REQUIREMENTS.read_text())
    plan = json.loads(P.ARM_B_PLAN.read_text())
    validate_self_identity(dict(plan), identity_field="plan_digest")
    if plan["plan_digest"] != P.ARM_B_PLAN_DIGEST:
        raise SystemExit("ISSUE182_AUTHORITY_FAIL: Arm-B plan digest drift")
    if requirements["requirements_digest"] != P.ARM_B_REQUIREMENTS_DIGEST:
        raise SystemExit(
            "ISSUE182_AUTHORITY_FAIL: Arm-B requirements digest drift")
    if requirements["plan_digest"] != plan["plan_digest"]:
        raise SystemExit(
            "ISSUE182_AUTHORITY_FAIL: Arm-B requirements/plan cross-bind")
    participants = {
        p["participant_id"]: {"node_id": p["node_id"],
                              "execution_unit_id": p["execution_unit_id"],
                              "digest": p["participant_requirements_digest"]}
        for p in requirements["participants"]}
    if participants.keys() != P.PARTICIPANT_NODES.keys():
        raise SystemExit(
            "ISSUE182_AUTHORITY_FAIL: participant set != pinned binding")
    for pid, binding in participants.items():
        if binding["node_id"] != P.PARTICIPANT_NODES[pid]:
            raise SystemExit(
                f"ISSUE182_AUTHORITY_FAIL: participant {pid} node binding")
    model = requirements["model"]
    if (model["model_id"], model["revision"],
            model["checkpoint_authority_sha256"]) != (
            P.SUBJECT["model"], P.SUBJECT["revision"],
            P.SUBJECT["checkpoint_sha256"]):
        raise SystemExit("ISSUE182_AUTHORITY_FAIL: subject identity drift")
    return {
        "plan_digest": plan["plan_digest"],
        "requirements_digest": requirements["requirements_digest"],
        "participants": participants,
        "model_identity": {
            "model_id": model["model_id"],
            "revision": model["revision"],
            "checkpoint_authority_sha256": model["checkpoint_authority_sha256"],
        },
        "file_sha256": {
            "requirements": sha256_file(P.ARM_B_REQUIREMENTS),
            "execution_plan": sha256_file(P.ARM_B_PLAN),
        },
    }


def bind_cold_arm() -> dict:
    """Bind the cold (pre-realization) inventory source records."""
    binding = {}
    for label, path in (("inferswarm01", P.ARM_B_COLD_INVENTORY_01),
                        ("inferswarm03", P.ARM_B_COLD_INVENTORY_03)):
        document = json.loads(path.read_text())
        if document.get("schema") != (
                "inferswarm.issue101.node-inventory-snapshot/1"):
            raise SystemExit(
                f"ISSUE182_AUTHORITY_FAIL: cold inventory schema {label}")
        if document.get("node_id") != label:
            raise SystemExit(
                f"ISSUE182_AUTHORITY_FAIL: cold inventory node {label}")
        if document.get("sequence") != 1:
            raise SystemExit(
                "ISSUE182_AUTHORITY_FAIL: cold inventory not sequence 1")
        if document["verified_objects"]:
            raise SystemExit(
                "ISSUE182_AUTHORITY_FAIL: cold inventory not pre-realization")
        binding[label] = {
            "path": str(path.relative_to(P.ROOT)),
            "sha256": sha256_file(path),
            "sequence": document["sequence"],
            "verified_object_count": len(document["verified_objects"]),
        }
    return binding


def accepted_cache_objects_document() -> tuple[dict, bytes]:
    """Build the accepted verified-cache provenance sidecar (P1-3).

    Derives, from the RETAINED accepted Arm-B post-acquisition node
    inventory snapshots, the exact per-node set of (content_digest,
    length) pairs that carry accepted verified-cache provenance. The
    fresh observation must EQUAL this set — missing objects are cache
    drift and EXTRA objects are unaccepted provenance; both stop the
    campaign. Every object consumed as verified locality evidence is
    thereby cross-bound to the accepted Arm-B verified inventory.
    """
    per_node = {}
    for node in P.OBSERVATION_HOSTS:
        path = P.ARM_B / f"inventory-post-{node}.json"
        document = json.loads(path.read_text())
        if document.get("schema") != (
                "inferswarm.issue101.node-inventory-snapshot/1"):
            raise SystemExit(
                f"ISSUE182_AUTHORITY_FAIL: post inventory schema {node}")
        if document.get("node_id") != node:
            raise SystemExit(
                f"ISSUE182_AUTHORITY_FAIL: post inventory node {node}")
        if document.get("sequence") != 2:
            raise SystemExit(
                "ISSUE182_AUTHORITY_FAIL: accepted post-acquisition "
                f"inventory not sequence 2 ({node})")
        objects = document["verified_objects"]
        for obj in objects:
            if not obj.get("byte_digest_verified"):
                raise SystemExit(
                    "ISSUE182_AUTHORITY_FAIL: accepted post-acquisition "
                    f"inventory carries an unverified object ({node})")
        per_node[node] = {
            "sequence": document["sequence"],
            "source_record": {
                "path": str(path.relative_to(P.ROOT)),
                "sha256": sha256_file(path),
            },
            "objects": [
                {"content_digest": obj["content_digest"],
                 "length": obj["length"]}
                for obj in objects],
        }
    sidecar = {
        "schema": P.ACCEPTED_CACHE_OBJECTS_SCHEMA,
        "campaign_id": P.CAMPAIGN_ID,
        "derivation": (
            "retained accepted Arm-B post-acquisition verified node "
            "inventories (sequence 2); the fresh Arm-E observation's "
            "verified object set must EQUAL the per-node set — no "
            "missing object (cache drift) and no extra object "
            "(unaccepted provenance)"),
        "per_node": per_node,
    }
    payload = json.dumps(sidecar, indent=2, sort_keys=True).encode() + b"\n"
    return sidecar, payload


def bind_accepted_cache_objects() -> dict:
    """Bind the sidecar bytes on disk (must have been written first)."""
    path = P.ACCEPTED_CACHE_OBJECTS_PATH
    if not path.is_file():
        raise SystemExit(
            "ISSUE182_AUTHORITY_FAIL: accepted-cache-objects sidecar "
            "missing (write it before freezing authority)")
    sidecar = json.loads(path.read_text())
    if sidecar.get("schema") != P.ACCEPTED_CACHE_OBJECTS_SCHEMA:
        raise SystemExit(
            "ISSUE182_AUTHORITY_FAIL: accepted-cache-objects schema")
    return {
        "path": str(path.relative_to(P.ROOT)),
        "sha256": sha256_file(path),
        "per_node_object_count": {
            node: len(binding["objects"])
            for node, binding in sidecar["per_node"].items()},
    }


def bind_geometry_uuids() -> dict:
    """Verify the pinned GPU UUID literals byte-for-byte against the
    accepted Arm-D authority (geometry) and the retained Arm-D
    terminal-window observation (full host GPU sets). Hand-copied
    digest/UUID constants always drift; this closes that seam at
    authority build (correction round 2026-09-14: the inferswarm03
    gpu-0 pin had silently dropped a hex character)."""
    authority = json.loads(P.ARM_D_AUTHORITY.read_text())
    accepted_geometry = authority.get("frozen_geometry_uuids", {})
    for host, gpus in P.FROZEN_GEOMETRY_UUIDS.items():
        accepted = accepted_geometry.get(host, {})
        if gpus != accepted:
            raise SystemExit(
                f"ISSUE182_AUTHORITY_FAIL: geometry uuid pin drift vs "
                f"accepted Arm-D authority on {host}: "
                f"{gpus} != {accepted}")
    retained = {}
    for node, path in (("inferswarm01", P.ARM_D_WARM_INVENTORY_01),
                       ("inferswarm03", P.ARM_D_WARM_INVENTORY_03)):
        document = json.loads(path.read_text())
        retained[node] = {gpu["index"]: gpu["uuid"]
                          for gpu in document.get("gpus", [])}
    for host, gpus in P.FROZEN_HOST_GPU_UUIDS.items():
        accepted = retained.get(host, {})
        if gpus != accepted:
            raise SystemExit(
                f"ISSUE182_AUTHORITY_FAIL: host gpu uuid pin drift vs "
                f"retained Arm-D observation on {host}: "
                f"{gpus} != {accepted}")
    return {
        "geometry_verified_against": "accepted Arm-D authority "
                                     "frozen_geometry_uuids",
        "host_sets_verified_against": "retained Arm-D terminal-window "
                                      "observation inventories",
        "per_host": {host: dict(gpus)
                     for host, gpus in P.FROZEN_HOST_GPU_UUIDS.items()},
    }


def bind_arm_d() -> dict:
    """Bind the accepted Arm-D authority/terminal/warm reference pins."""
    authority = json.loads(P.ARM_D_AUTHORITY.read_text())
    terminal = json.loads(P.ARM_D_TERMINAL.read_text())
    if terminal.get("terminal") != "ISSUE117_ARM_D_WARM_RESTART_CACHE_REUSE_PASS":
        raise SystemExit(
            "ISSUE182_AUTHORITY_FAIL: Arm-D terminal is not the accepted PASS")
    cache_binding = authority.get("artifact_cache_binding", {})
    for node, pins in P.MATERIALIZED_PINS.items():
        bound = cache_binding.get("per_node_artifacts", {}).get(node, {})
        for rel, digest in pins.items():
            if bound.get(rel) != digest:
                raise SystemExit(
                    "ISSUE182_AUTHORITY_FAIL: materialized pin drift "
                    f"{node}:{rel}")
    for label, path in (("authority", P.ARM_D_AUTHORITY),
                        ("terminal_reduction", P.ARM_D_TERMINAL),
                        ("warm_inventory_01", P.ARM_D_WARM_INVENTORY_01),
                        ("warm_inventory_03", P.ARM_D_WARM_INVENTORY_03)):
        if not path.is_file():
            raise SystemExit(
                f"ISSUE182_AUTHORITY_FAIL: Arm-D record missing {label}")
    inv01 = json.loads(P.ARM_D_WARM_INVENTORY_01.read_text())
    inv03 = json.loads(P.ARM_D_WARM_INVENTORY_03.read_text())
    for node, doc in (("inferswarm01", inv01), ("inferswarm03", inv03)):
        problems = doc.get("problems") or []
        if problems:
            raise SystemExit(
                f"ISSUE182_AUTHORITY_FAIL: Arm-D warm inventory problems "
                f"on {node}: {problems}")
        for rel, pin in P.MATERIALIZED_PINS[node].items():
            entry = doc["cache_artifacts"].get(rel)
            if entry is None or not entry.get("verified"):
                raise SystemExit(
                    "ISSUE182_AUTHORITY_FAIL: Arm-D warm inventory entry "
                    f"missing/unverified {node}:{rel}")
            if entry["sha256"] != pin:
                raise SystemExit(
                    "ISSUE182_AUTHORITY_FAIL: Arm-D warm inventory digest "
                    f"drift {node}:{rel}")
    return {
        "terminal": terminal["terminal"],
        "campaign_id": terminal.get("campaign_id"),
        "file_sha256": {
            "authority": sha256_file(P.ARM_D_AUTHORITY),
            "terminal_reduction": sha256_file(P.ARM_D_TERMINAL),
            "warm_inventory_01": sha256_file(P.ARM_D_WARM_INVENTORY_01),
            "warm_inventory_03": sha256_file(P.ARM_D_WARM_INVENTORY_03),
        },
        "materialized_reference": {
            node: {rel: {
                "sha256": doc["cache_artifacts"][rel]["sha256"],
                "bytes": doc["cache_artifacts"][rel]["bytes"],
            } for rel in P.MATERIALIZED_PINS[node]}
            for node, doc in (("inferswarm01", inv01),
                              ("inferswarm03", inv03))
        },
    }


def bind_locality_analog() -> dict:
    """Load/bind the accepted #117 CPU locality-mutation analog."""
    document = json.loads(P.LOCALITY_MUTATION_117.read_text())
    for key in P.LOCALITY_MUTATION_117_REQUIRED_KEYS:
        if key not in document:
            raise SystemExit(
                "ISSUE182_AUTHORITY_FAIL: locality analog missing " + key)
    return {
        "path": str(P.LOCALITY_MUTATION_117.relative_to(P.ROOT)),
        "sha256": sha256_file(P.LOCALITY_MUTATION_117),
        "objective": document["objective"],
        "selected_candidate_id": document["selected_candidate_id"],
        "v5_missing_bytes_cold": document["v5_missing_bytes_cold"],
        "v5_missing_bytes_warm": document["v5_missing_bytes_warm"],
        "all_gates_unchanged": document["all_gates_unchanged"],
    }


def derive_bandwidth() -> dict:
    """Derive the Source path bandwidth from retained Arm-B ledger bytes."""
    per_node = {}
    for node in ("inferswarm01", "inferswarm03"):
        path = P.ARM_B / f"acquisition-ledger-{node}.json"
        ledger = json.loads(path.read_text())
        events = [e for e in ledger["events"]
                  if e["event"] == "ACQUIRED" and e["source_id"] == "issue117-origin"]
        acquired = sum(e["bytes"] for e in events)
        wall = sum(e["wall_time_seconds"] for e in events)
        if not events or wall <= 0 or acquired <= 0:
            raise SystemExit(
                f"ISSUE182_AUTHORITY_FAIL: no ACQUIRED events {node}")
        per_node[node] = {
            "acquired_bytes": acquired,
            "wall_time_seconds": wall,
            "bandwidth_bytes_per_second": acquired / wall,
            "event_count": len(events),
            "ledger_sha256": sha256_file(path),
        }
    return {"method": P.PATH_BANDWIDTH_METHOD, "per_node": per_node}


def producer_hashes() -> dict:
    entries = {}
    for name in sorted((
            "issue182_campaign_pins.py",
            "issue182_authority.py",
            "issue182_inventory.py",
            "issue182_compare.py",
            "issue182_terminal.py",
            "issue182_manifest.py",
    )):
        path = Path(__file__).resolve().parent / name
        if path.is_file():
            entries[name] = sha256_file(path)
    # accepted planner/strategy/locality machinery consumed read-only
    for name in ("issue117_planner.py", "issue103_planner.py",
                 "issue117_gemma_strategy.py", "issue117_accepted_subject.py",
                 "issue99_artifact_core.py", "issue101_orchestration.py",
                 "issue74_methodology.py"):
        path = Path(__file__).resolve().parent / name
        if path.is_file():
            entries[name] = sha256_file(path)
    return entries


def build_authority(inferswarm: Path) -> dict:
    document = {
        "schema": P.AUTHORITY_SCHEMA,
        "campaign_id": P.CAMPAIGN_ID,
        "physical_authorization_id": P.PHYSICAL_AUTHORIZATION_ID,
        "issue": P.ISSUE,
        "heads": verify_heads(inferswarm),
        "drift_classification": classify_drift(inferswarm),
        "subject_and_plan": bind_subject_and_plan(),
        "cold_arm_binding": bind_cold_arm(),
        "arm_d_binding": bind_arm_d(),
        "geometry_uuid_binding": bind_geometry_uuids(),
        "accepted_cache_objects": bind_accepted_cache_objects(),
        "locality_analog": bind_locality_analog(),
        "path_bandwidth": derive_bandwidth(),
        "observation_epoch": {
            "rule": P.OBSERVATION_EPOCH_RULE,
            "sequence": P.OBSERVATION_SEQUENCE,
            "retained_cold_sequence": 1,
            "retained_accepted_sequence": 2,
            "bound_to": ("authority_digest", "campaign_id", "attempt_id",
                         "host"),
            "note": (
                "the fresh observation's inventory sequence is a frozen "
                "authority constant derived from the retained accepted "
                "inventory lineage; the collector embeds it only after "
                "verifying the staged authority bytes, and comparison "
                "and terminal re-derive it independently"),
        },
        "probe_contract": {
            "fail_closed": True,
            "probes": list(P.FENCE_PROBE_NAMES),
            "receipt_fields": (
                "name, argv, returncode, stdout/stderr byte counts, "
                "sha256 digests, bounded raw text"),
            "stop_rule": "OBS-PROBE-FAILED",
            "gpu_requirements": (
                "every frozen GPU of an observation host must be "
                "observed with parseable telemetry, memory.total equal "
                "to the pinned authority total, and memory.used within "
                f"the frozen idle bound ({P.GPU_MEMORY_USED_MAX_MIB} "
                "MiB, derived from the retained Arm-D terminal-window "
                "observation)"),
            "note": (
                "an empty process list / port set / GPU row set is "
                "admissible evidence ONLY against a retained "
                "successful (returncode 0) probe receipt; a failed "
                "probe is never converted into an empty observation"),
        },
        "capacity_method": {
            "usable_weight_bytes": (
                "observed nvidia-smi memory.total bytes minus the frozen "
                "CAPACITY_RESERVE_BYTES (3072 MiB) per serving GPU"),
            "reserve_bytes": P.CAPACITY_RESERVE_BYTES,
            "pinned_gpu_total_bytes": dict(P.PINNED_GPU_TOTAL_BYTES),
            "note": (
                "the capacity model is a planning input held identical "
                "across both arms; it is not a hardware claim"),
        },
        "planning_evidence_contract": dict(P.PLANNING_EVIDENCE_CONTRACT),
        "normalization": {
            "projection": P.NORMALIZATION_PROJECTION,
            "sequence_monotonic": P.INVENTORY_SEQUENCE_MONOTONIC,
        },
        "observation_plan": {
            "hosts": list(P.OBSERVATION_HOSTS),
            "roots": {
                "cache_objects": P.CACHE_OBJECTS_ROOT,
                "substrate": P.SUBSTRATE_ROOT,
                "model_view_01": P.MODEL_VIEW_01,
                "tokenizer_deployment": P.TOKENIZER_DEPLOYMENT,
            },
            "read_only": True,
            "byte_preservation": (
                "sha256 of every object file under the cache objects root "
                "+ stat (size, mtime_ns, inode) per file, captured before "
                "and after the semantic observation; any difference stops "
                "OBS-MUTATION-DETECTED"),
            "process_fence": (
                "pgrep over the accepted #175 service patterns; any live "
                "execution-bearing process stops OBS-PROCESSES-LIVE"),
            "no_runtime_start": True,
            "no_cuda_init": True,
            "no_source_contact": True,
            "no_peer_transfer": True,
        },
        "attempt_state_machine": {
            "attempt_id": P.ATTEMPT_ID,
            "transitions": [
                "FROZEN -> OBSERVING -> REDUCING -> TERMINAL",
                "OBSERVING -> BLOCKED (STOP rule) -> STOPPED",
            ],
            "stop_rules": list(P.STOP_RULES),
            "no_retry": True,
        },
        "non_claims": list(P.NON_CLAIMS),
        "producer_hashes": producer_hashes(),
    }
    document["authority_digest"] = self_digest(
        document, identity_field="authority_digest")
    return document


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inferswarm-root", type=Path, default=P.ROOT)
    parser.add_argument("--out", type=Path, default=P.EVIDENCE_DIR / "authority.json")
    args = parser.parse_args()
    # write the accepted-cache provenance sidecar FIRST (deterministic
    # derivation from retained bytes) so the authority binds the exact
    # sidecar bytes on disk
    _, payload = accepted_cache_objects_document()
    P.ACCEPTED_CACHE_OBJECTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    P.ACCEPTED_CACHE_OBJECTS_PATH.write_bytes(payload)
    document = build_authority(args.inferswarm_root)
    write_json(args.out, document)
    print(json.dumps({
        "authority": str(args.out),
        "campaign_id": document["campaign_id"],
        "authority_digest": document["authority_digest"],
    }, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
