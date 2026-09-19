#!/usr/bin/env python3
"""Issue #222 R7-C DeepSeek V4.1 physical-feasibility authority and reducer.

This stdlib-only producer derives the frozen two-stage text-only footprint from
R7-A/R7-B bytes, accepts a fresh read-only NVIDIA fleet census, and emits the
earliest truthful terminal. It never downloads model bodies or initializes a
model runtime. A physical probe is deliberately unreachable unless a legal
per-stage capacity placement exists.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
AREA = "docs/investigations/deepseek-v41-flash-r7-c"
R7A = "docs/investigations/deepseek-v41-flash-r7-a"
R7B = "docs/investigations/deepseek-v41-flash-r7-b"
R7A_CENSUS = f"{R7A}/tensor-census.json"
R7A_TERMINAL = f"{R7A}/terminal-reduction.json"
R7A_MANIFEST = f"{R7A}/MANIFEST.sha256"
R7B_STRATEGY = f"{R7B}/strategy-authority.json"
R7B_RUNTIME = f"{R7B}/runtime-authority.json"
R7B_TERMINAL = f"{R7B}/terminal-reduction.json"
R7B_MANIFEST = f"{R7B}/MANIFEST.sha256"
AUTHORITY_SCHEMA = "inferswarm.issue222.r7c-authority/1"
FLEET_SCHEMA = "inferswarm.issue222.r7c-fleet-census/1"
TERMINAL_SCHEMA = "inferswarm.issue222.r7c-terminal/1"
CAPACITY_PREREQUISITE = "R7C_CURRENT_FLEET_CAPACITY_PREREQUISITE"
MATERIALIZATION_PREREQUISITE = "R7C_OFFICIAL_STATE_MATERIALIZATION_PREREQUISITE"
RUNTIME_PREREQUISITE = "R7C_RUNTIME_DEVICE_PREREQUISITE"
EVIDENCE_BLOCKED = "R7C_EVIDENCE_BLOCKED"
PASS_TERMINAL = "R7C_DEEPSEEK_V41_PHYSICAL_FEASIBILITY_PASS"
HOST_RECORD_SCHEMA = "inferswarm.issue222.r7c-host-record/1"
CONNECTION_FAILURE_SCHEMA = "inferswarm.issue222.r7c-connection-failure/1"
EXPECTED_RECEIPT_ARGV = {
    "nvidia_smi_gpu": ["nvidia-smi", "--query-gpu=index,uuid,pci.bus_id,name,memory.total,memory.free,memory.used,driver_version", "--format=csv,noheader,nounits"],
    "nvidia_smi_apps": ["nvidia-smi", "--query-compute-apps=pid,gpu_uuid,used_memory", "--format=csv,noheader,nounits"],
    "hostname": ["hostname"],
    "storage": ["df", "-B1", "."],
    "memory": ["free", "-b"],
}
EXPECTED = {
    R7A_CENSUS: "25f61e88289ae4b6f101fea563e5556d37cb96291f6c108ad26d9513d6da1bbc",
    R7A_TERMINAL: "aee287f59199622b97bdf9862624f990416ee838eebea397e6a64d99526806dc",
    R7A_MANIFEST: "6730826a7c00b92cc88bda814583ccc6955370cde37d685261f764b5146e640c",
    R7B_STRATEGY: "c85da5685b81a77d144017d9bee3413be12af09be0141a3a68b1c585d7a76e6c",
    R7B_RUNTIME: "2a3751560ef0f5cf2818b5d1087d5a702569ee70c78705c38696cba5aa146f1a",
    R7B_TERMINAL: "8fbea3f5cd4005bb69bb1de499211515b12918820205ea741d3143d2a4c2cea7",
    R7B_MANIFEST: "4af8766d634e59b978527f68c284b56204e3337561cef3eb7e5fabc33bfd5edf",
}
MODEL_REPOSITORY = "deepseek-ai/DeepSeek-V4.1-Flash"
MODEL_REVISION = "dba1be0a40aa45a94ad051997016db3960a90277"
VLLM_REVISION = "0eae9acd4d01574e12d4ecf6a0229813f7fdb799"
FRESHNESS_SECONDS = 900
R7B_MERGE = "54d36cb9d8a4c0603abeb18968a8ffb7b52ca10e"
RECONCILED_MAIN = "fe690249873a9bf7ca19d788a2fab5e580473394"
CANDIDATE_HOSTS = ("inferswarm01", "inferswarm02", "inferswarm03", "inferswarm04")
_LAYER = re.compile(r"^layers\.(\d+)\.")


def canonical(document: dict[str, Any]) -> bytes:
    return json.dumps(document, sort_keys=True, separators=(",", ":")).encode() + b"\n"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(root: Path, relative: str) -> dict[str, Any]:
    try:
        return json.loads((root / relative).read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"ISSUE222_FAIL: missing or malformed {relative}") from error


def _require_hashes(root: Path) -> None:
    for relative, expected in EXPECTED.items():
        try:
            actual = sha256(root / relative)
        except OSError as error:
            raise ValueError(f"ISSUE222_FAIL: predecessor input missing {relative}") from error
        if actual != expected:
            prefix = "R7-A" if relative.startswith(R7A) else "R7-B"
            raise ValueError(f"ISSUE222_FAIL: {prefix} predecessor drift {relative}")


def copy_predecessor_inputs(source: Path, destination: Path) -> None:
    """Copy the bounded predecessor trees for adversarial sandbox tests."""
    for area in (R7A, R7B):
        target = destination / area
        if target.exists():
            shutil.rmtree(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source / area, target)


def _owner(name: str, state_class: str) -> str | None:
    """Return the exact R7-B stage owner for a text-only tensor."""
    if state_class in {"vision", "draft_mtp"} or name.startswith(("vision.", "aligner.", "mtp.", "image_")):
        return None
    if name.startswith("embed."):
        return "stage-a"
    if name.startswith(("head.", "norm.")):
        return "stage-b"
    match = _LAYER.match(name)
    if match is None:
        raise ValueError(f"ISSUE222_FAIL: text tensor lacks stage ownership: {name}")
    layer = int(match.group(1))
    if 0 <= layer < 20:
        return "stage-a"
    if 20 <= layer < 40:
        return "stage-b"
    raise ValueError(f"ISSUE222_FAIL: backbone layer outside R7-B subject: {name}")


def derive_stage_footprints(root: Path) -> dict[str, dict[str, Any]]:
    census = load(root, R7A_CENSUS)
    if (census.get("repository") != MODEL_REPOSITORY
            or census.get("revision") != MODEL_REVISION
            or census.get("tensor_count") != 96085):
        raise ValueError("ISSUE222_FAIL: R7-A census identity drift")
    stages: dict[str, dict[str, Any]] = {
        "stage-a": {"tensors": [], "unassigned_tensors": []},
        "stage-b": {"tensors": [], "unassigned_tensors": []},
    }
    excluded = []
    for tensor in census.get("tensors", []):
        name = tensor.get("name")
        size = tensor.get("encoded_bytes")
        if not isinstance(name, str) or not isinstance(size, int) or size < 0:
            raise ValueError("ISSUE222_FAIL: malformed R7-A tensor row")
        owner = _owner(name, str(tensor.get("state_class", "")))
        if owner is None:
            excluded.append(name)
            continue
        stages[owner]["tensors"].append({
            "name": name,
            "shard": tensor.get("shard"),
            "encoded_bytes": size,
            "dtype": tensor.get("dtype"),
            "shape": tensor.get("shape"),
            "state_class": tensor.get("state_class"),
        })
    for stage_id, stage in stages.items():
        stage["tensors"].sort(key=lambda row: row["name"])
        if not stage["tensors"]:
            raise ValueError(f"ISSUE222_FAIL: {stage_id} tensor membership empty")
        stage["tensor_count"] = len(stage["tensors"])
        stage["logical_required_bytes"] = sum(row["encoded_bytes"] for row in stage["tensors"])
        stage["shards"] = sorted({str(row["shard"]) for row in stage["tensors"]})
        stage["ownership_rules"] = (
            "embed. plus layers.[0,20)" if stage_id == "stage-a"
            else "layers.[20,40) plus norm. and head.")
        stage["unassigned_tensors"] = []
    stages["excluded_text_scope"] = {
        "reason": "R7-C text-only R7-B subject excludes vision/aligner/image and MTP state",
        "tensor_count": len(excluded),
        "names": sorted(excluded),
    }
    return stages


def mainline_applicability_audit(root: Path) -> dict[str, Any]:
    """Mechanically classify all post-R7-B mainline paths before R7-C output."""
    result = subprocess.run(["git", "-C", str(root), "diff", "--name-only",
                             f"{R7B_MERGE}..{RECONCILED_MAIN}"],
                            capture_output=True, text=True)
    if result.returncode != 0:
        raise ValueError("ISSUE222_FAIL: cannot audit post-R7-B mainline")
    paths = sorted(path for path in result.stdout.splitlines() if path)
    r7_paths = [path for path in paths if path.startswith((R7A + "/", R7B + "/",
                                                            "scripts/issue187_", "scripts/issue209_",
                                                            "tests/test_issue187_", "tests/test_issue209_"))]
    if r7_paths:
        raise ValueError("ISSUE222_FAIL: post-R7-B mainline changes R7 authority or strategy")
    scope_counts = {
        "campaign_gate_ordering_or_ci": sum(path.startswith((".github/", "scripts/issue213_", "tests/test_issue213_", "docs/campaign-gate-ordering")) for path in paths),
        "vulkan_campaigns_and_hardware_inventory": sum(path.startswith(("docs/investigations/vulkan", "docs/hardware/", "scripts/issue215_", "scripts/issue216_", "scripts/issue219_", "tests/test_issue215", "tests/test_issue216", "tests/test_issue219")) for path in paths),
        "other_docs_or_tests": 0,
    }
    scope_counts["other_docs_or_tests"] = len(paths) - sum(scope_counts.values())
    return {
        "start_after_r7b_merge": R7B_MERGE,
        "reconciled_main": RECONCILED_MAIN,
        "changed_path_count": len(paths),
        "scope_counts": scope_counts,
        "r7_authority_or_strategy_changes": r7_paths,
        "conclusion": (
            "The post-R7-B mainline delta contains campaign-gate ordering/CI and "
            "separate V340L Vulkan/hardware campaign material; it changes neither "
            "the R7-A census, R7-B vLLM source authority, selected contiguous-stage "
            "strategy, nor DeepSeek artifact/materialization authority."),
    }


def build_authority(root: Path = ROOT, repo_head: str | None = None) -> dict[str, Any]:
    """Freeze all static R7-C inputs before any physical census is admitted."""
    _require_hashes(root)
    r7a = load(root, R7A_TERMINAL)
    r7b = load(root, R7B_TERMINAL)
    strategy = load(root, R7B_STRATEGY)
    runtime = load(root, R7B_RUNTIME)
    if r7a.get("terminal") != "R7A_DEEPSEEK_V41_SUBSTRATE_PREREQUISITE":
        raise ValueError("ISSUE222_FAIL: wrong R7-A terminal")
    if r7b.get("terminal") != "R7B_DEEPSEEK_V41_PHYSICAL_GATE_READY":
        raise ValueError("ISSUE222_FAIL: wrong R7-B terminal")
    if (strategy.get("shape") != "contiguous_stage"
            or strategy.get("cut_layer") != 20
            or strategy.get("layer_interval") != [20, 40]
            or strategy.get("model_revision") != MODEL_REVISION
            or strategy.get("runtime_revision") != VLLM_REVISION):
        raise ValueError("ISSUE222_FAIL: R7-B strategy/cut authority drift")
    selected = [row for row in runtime.get("candidates", [])
                if row.get("id") == "vllm-current-source" and row.get("disposition") == "SELECTED"]
    if len(selected) != 1 or selected[0].get("revision") != VLLM_REVISION:
        raise ValueError("ISSUE222_FAIL: R7-B runtime authority drift")
    derived = derive_stage_footprints(root)
    stages = {key: derived[key] for key in ("stage-a", "stage-b")}
    excluded = derived["excluded_text_scope"]
    stage_rows = stages
    document: dict[str, Any] = {
        "schema": AUTHORITY_SCHEMA,
        "issue": 222,
        "campaign_id": "r7c-deepseek-v41-physical-feasibility/1",
        "repo_head": repo_head,
        "mainline_applicability_audit": mainline_applicability_audit(root),
        "model": {"repository": MODEL_REPOSITORY, "revision": MODEL_REVISION,
                  "representation": "48 official sharded safetensors"},
        "runtime": {"id": "vllm-current-source", "revision": VLLM_REVISION},
        "candidate_hosts": list(CANDIDATE_HOSTS),
        "strategy": {"shape": "contiguous_stage", "cut_layer": 20,
                     "stage_a_layers": [0, 20], "stage_b_layers": [20, 40],
                     "cross_stage_cache": "none at layer-20 cut"},
        "r7a": {"terminal": r7a["terminal"], "terminal_sha256": EXPECTED[R7A_TERMINAL],
                "manifest_sha256": EXPECTED[R7A_MANIFEST], "census_sha256": EXPECTED[R7A_CENSUS]},
        "r7b": {"terminal": r7b["terminal"], "terminal_sha256": EXPECTED[R7B_TERMINAL],
                "manifest_sha256": EXPECTED[R7B_MANIFEST],
                "strategy_sha256": EXPECTED[R7B_STRATEGY],
                "runtime_sha256": EXPECTED[R7B_RUNTIME]},
        "stage_footprints": stages,
        "excluded_text_scope": excluded,
        "capacity_contract": {
            "stage_lower_bound_definition": (
                "logical-required BF16 tensor bytes from exact official header census; "
                "this is a parameter lower bound, not a claim about runtime workspace, "
                "KV/cache allocation, or host staging"),
            "simultaneous_logical_lower_bound_bytes": sum(
                stage["logical_required_bytes"] for stage in stage_rows.values()),
            "placement_rule": "each contiguous stage must fit one compatible resource; aggregate VRAM is never a substitute",
            "runtime_terms": {
                "immutable_parameter_backing": "exact logical tensor bytes",
                "device_resident_parameters": "at least logical-required bytes; runtime initialization otherwise unmeasured",
                "host_staging": "unknown",
                "kv_cache": "prospectively measurable only after legal capacity",
                "workspace_graph_allocator": "unknown",
                "intermediate_tensors": "boundary hidden-state contract retained by R7-B; capacity not measured in R7-C early stop",
            },
        },
        "producer_sha256": sha256(Path(__file__).resolve()),
        "non_claims": [
            "No checkpoint body download, model runtime initialization, full-model inference, serving, conversion, alternate cut, tensor parallelism, CPU offload, hybrid placement, or AMD/Vulkan work occurred.",
            "A capacity prerequisite is a successful bounded R7-C result, not a model execution failure.",
        ],
    }
    document["authority_sha256"] = hashlib.sha256(canonical(document)).hexdigest()
    return document


def _receipt(receipts: dict[str, Any], name: str) -> dict[str, Any]:
    receipt = receipts.get(name)
    if not isinstance(receipt, dict):
        raise ValueError(f"ISSUE222_FAIL: raw receipt absent {name}")
    if receipt.get("argv") != EXPECTED_RECEIPT_ARGV[name]:
        raise ValueError(f"ISSUE222_FAIL: raw receipt command drift {name}")
    for field in ("stdout", "stderr"):
        if not isinstance(receipt.get(field), str):
            raise ValueError(f"ISSUE222_FAIL: raw receipt bytes absent {name}")
        if receipt.get(f"{field}_sha256") != hashlib.sha256(receipt[field].encode()).hexdigest():
            raise ValueError(f"ISSUE222_FAIL: raw receipt hash drift {name}")
    if not isinstance(receipt.get("returncode"), int):
        raise ValueError(f"ISSUE222_FAIL: raw receipt return code absent {name}")
    return receipt


def _raw_resources(host: str, receipts: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    """Recompute resource and foreign-process rows from retained raw bytes."""
    checked = {name: _receipt(receipts, name) for name in EXPECTED_RECEIPT_ARGV}
    if checked["hostname"]["returncode"] != 0 or checked["hostname"]["stdout"].strip() != host:
        raise ValueError("ISSUE222_FAIL: hostname receipt contradicts host identity")
    gpu, apps = checked["nvidia_smi_gpu"], checked["nvidia_smi_apps"]
    if gpu["returncode"] != 0 or apps["returncode"] != 0:
        raise ValueError("ISSUE222_FAIL: required NVIDIA raw receipt failed")
    apps_by_uuid: dict[str, list[dict[str, str]]] = {}
    for line in apps["stdout"].splitlines():
        parts = [item.strip() for item in line.split(",")]
        if len(parts) != 3 or not all(parts) or not parts[0].isdigit() or not parts[2].isdigit():
            raise ValueError("ISSUE222_FAIL: nvidia-smi app raw receipt unparseable")
        apps_by_uuid.setdefault(parts[1], []).append(
            {"pid": parts[0], "used_memory_mib": parts[2]})
    resources: list[dict[str, Any]] = []
    seen_indexes, seen_uuids = set(), set()
    for line in gpu["stdout"].splitlines():
        parts = [item.strip() for item in line.split(",")]
        if len(parts) != 8 or not all(parts) or not parts[0].isdigit():
            raise ValueError("ISSUE222_FAIL: nvidia-smi GPU raw receipt unparseable")
        try:
            total, free, used = (int(parts[index]) * 1024 * 1024 for index in (4, 5, 6))
        except ValueError as error:
            raise ValueError("ISSUE222_FAIL: nvidia-smi GPU raw receipt unparseable") from error
        if min(total, free, used) < 0 or free + used > total or parts[0] in seen_indexes or parts[1] in seen_uuids:
            raise ValueError("ISSUE222_FAIL: nvidia-smi GPU raw receipt contradictory")
        seen_indexes.add(parts[0])
        seen_uuids.add(parts[1])
        resources.append({
            "resource_id": f"{host}/gpu-{parts[0]}", "host": host, "index": parts[0],
            "uuid": parts[1], "pci_bdf": parts[2], "name": parts[3],
            "total_device_bytes": total, "available_device_bytes": free,
            "used_device_bytes": used, "usable_device_bytes": free,
            "driver_version": parts[7], "compatible": True,
            "foreign_processes": apps_by_uuid.pop(parts[1], []),
        })
    if apps_by_uuid:
        raise ValueError("ISSUE222_FAIL: nvidia-smi app receipt names unknown GPU")
    problems = [name for name, receipt in checked.items() if receipt["returncode"] != 0]
    return resources, problems


def _validate_record(authority: dict[str, Any], host: str, record: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str], bool]:
    """Validate provenance and derive every admitted resource from raw receipts."""
    if not isinstance(record, dict) or record.get("host") != host:
        raise ValueError("ISSUE222_FAIL: host identity drift in census record")
    if (record.get("campaign_id") != authority.get("campaign_id")
            or record.get("authority_sha256") != authority.get("authority_sha256")
            or record.get("collector_sha256") != authority.get("producer_sha256")):
        raise ValueError("ISSUE222_FAIL: host record provenance drift")
    if not isinstance(record.get("collected_at_unix"), int):
        raise ValueError("ISSUE222_FAIL: host record collection time absent")
    failed = record.get("connection_failure")
    if failed is not None:
        if (record.get("schema") != CONNECTION_FAILURE_SCHEMA or not isinstance(failed, dict)
                or not isinstance(failed.get("returncode"), int) or failed["returncode"] == 0
                or not isinstance(failed.get("stderr"), str) or not failed["stderr"]
                or failed.get("stderr_sha256") != hashlib.sha256(failed["stderr"].encode()).hexdigest()):
            raise ValueError("ISSUE222_FAIL: malformed connection-failure receipt")
        if "resources" in record or "receipts" in record:
            raise ValueError("ISSUE222_FAIL: unavailable host carries resource receipt")
        return [], [], True
    if record.get("schema") != HOST_RECORD_SCHEMA:
        raise ValueError("ISSUE222_FAIL: host record schema drift")
    receipts = record.get("receipts")
    if not isinstance(receipts, dict):
        raise ValueError("ISSUE222_FAIL: host raw receipts absent")
    resources, problems = _raw_resources(host, receipts)
    if record.get("resources") != resources or record.get("problems") != problems:
        raise ValueError("ISSUE222_FAIL: parsed resource rows contradict raw receipts")
    return resources, problems, False


def assemble_fleet(authority: dict[str, Any], records: dict[str, dict[str, Any]], *,
                   collected_at_unix: int | None = None) -> dict[str, Any]:
    """Assemble one provenance-checked census from every frozen candidate."""
    expected_hosts = authority.get("candidate_hosts")
    if expected_hosts != list(CANDIDATE_HOSTS) or set(records) != set(CANDIDATE_HOSTS):
        raise ValueError("ISSUE222_FAIL: candidate-host set drift")
    resources: list[dict[str, Any]] = []
    unavailable: list[str] = []
    observation_problems: list[dict[str, Any]] = []
    for host in CANDIDATE_HOSTS:
        host_resources, problems, failed = _validate_record(authority, host, records[host])
        if failed:
            unavailable.append(host)
        else:
            resources.extend(host_resources)
            if problems:
                observation_problems.append({"host": host, "problems": problems})
    collected = int(time.time()) if collected_at_unix is None else collected_at_unix
    if not isinstance(collected, int):
        raise ValueError("ISSUE222_FAIL: fleet collection time absent")
    return {
        "schema": FLEET_SCHEMA, "campaign_id": authority.get("campaign_id"),
        "authority_sha256": authority.get("authority_sha256"),
        "candidate_hosts": list(CANDIDATE_HOSTS), "unavailable_hosts": unavailable,
        "host_records": {host: records[host] for host in CANDIDATE_HOSTS},
        "resources": resources, "observation_problems": observation_problems,
        "collected_at_unix": collected,
    }


def record_connection_failure(authority: dict[str, Any], host: str, returncode: int, stderr: str,
                              *, collected_at_unix: int | None = None) -> dict[str, Any]:
    """Preserve a provenance-bound failed read-only SSH attempt."""
    if host not in CANDIDATE_HOSTS or returncode == 0 or not stderr:
        raise ValueError("ISSUE222_FAIL: invalid connection-failure receipt")
    return {
        "schema": CONNECTION_FAILURE_SCHEMA, "campaign_id": authority.get("campaign_id"),
        "authority_sha256": authority.get("authority_sha256"), "host": host,
        "collected_at_unix": int(time.time()) if collected_at_unix is None else collected_at_unix,
        "connection_failure": {"returncode": returncode, "stderr": stderr,
                               "stderr_sha256": hashlib.sha256(stderr.encode()).hexdigest()},
        "collector_sha256": sha256(Path(__file__).resolve()),
    }


def legal_placement(stages: dict[str, dict[str, Any]], fleet: dict[str, Any]) -> dict[str, Any]:
    resources = fleet.get("resources")
    if not isinstance(resources, list) or not resources:
        raise ValueError("ISSUE222_FAIL: fleet contains no resource rows")
    compatible = [row for row in resources
                  if row.get("compatible") is True
                  and not row.get("foreign_processes")]
    aggregate = sum(int(row.get("usable_device_bytes", 0)) for row in compatible)
    placements: dict[str, str] = {}
    rejected: dict[str, dict[str, Any]] = {}
    selected_resources: set[str] = set()
    for stage_id in ("stage-a", "stage-b"):
        required = stages[stage_id].get("logical_required_bytes")
        if not isinstance(required, int) or required < 0:
            raise ValueError("ISSUE222_FAIL: malformed stage lower bound")
        candidates = [row for row in compatible
                      if isinstance(row.get("usable_device_bytes"), int)
                      and row["usable_device_bytes"] >= required
                      and str(row.get("resource_id")) not in selected_resources]
        if not candidates:
            largest = max((int(row.get("usable_device_bytes", 0)) for row in compatible), default=0)
            rejected[stage_id] = {
                "required_lower_bound_bytes": required,
                "largest_compatible_usable_bytes": largest,
                "deficit_bytes": max(required - largest, 0),
                "reason": "no single compatible resource satisfies the stage lower bound",
            }
        else:
            selected = sorted(candidates, key=lambda row: (-row["usable_device_bytes"], row.get("resource_id", "")))[0]
            selected_id = str(selected.get("resource_id"))
            placements[stage_id] = selected_id
            selected_resources.add(selected_id)
    return {
        "legal": not rejected,
        "terminal": PASS_TERMINAL if not rejected else CAPACITY_PREREQUISITE,
        "aggregate_compatible_usable_bytes": aggregate,
        "placements": placements,
        "rejected": rejected,
    }


def _validate_fleet(authority: dict[str, Any], fleet: dict[str, Any], now_unix: int) -> None:
    if not isinstance(now_unix, int):
        raise ValueError("ISSUE222_FAIL: explicit reduction time required")
    if fleet.get("schema") != FLEET_SCHEMA:
        raise ValueError("ISSUE222_FAIL: fleet schema drift")
    records = fleet.get("host_records")
    if not isinstance(records, dict):
        raise ValueError("ISSUE222_FAIL: host records absent from fleet")
    observed = fleet.get("collected_at_unix")
    if not isinstance(observed, int):
        raise ValueError("ISSUE222_FAIL: fleet freshness invalid")
    expected = assemble_fleet(authority, records, collected_at_unix=observed)
    if canonical(fleet) != canonical(expected):
        raise ValueError("ISSUE222_FAIL: fleet bypasses assembled raw-receipt provenance")
    timestamps = [observed] + [records[host].get("collected_at_unix") for host in CANDIDATE_HOSTS]
    if any(not isinstance(value, int) or value < now_unix - FRESHNESS_SECONDS
           or value > now_unix + 60 for value in timestamps):
        raise ValueError("ISSUE222_FAIL: fleet freshness invalid")


def reduction_document(authority: dict[str, Any], fleet: dict[str, Any], *, now_unix: int | None = None) -> dict[str, Any]:
    if authority.get("schema") != AUTHORITY_SCHEMA:
        raise ValueError("ISSUE222_FAIL: authority schema drift")
    raw = dict(authority)
    claimed = raw.pop("authority_sha256", None)
    if claimed != hashlib.sha256(canonical(raw)).hexdigest():
        raise ValueError("ISSUE222_FAIL: authority self-digest drift")
    if now_unix is None:
        raise ValueError("ISSUE222_FAIL: explicit reduction time required")
    _validate_fleet(authority, fleet, now_unix)
    stage_footprints = authority.get("stage_footprints")
    if not isinstance(stage_footprints, dict):
        raise ValueError("ISSUE222_FAIL: stage footprints absent")
    placement = legal_placement(stage_footprints, fleet)
    if placement["legal"]:
        raise ValueError("ISSUE222_FAIL: legal capacity requires separately frozen materialization probe; no PASS is admitted by this reducer")
    document = {
        "schema": TERMINAL_SCHEMA,
        "campaign_id": authority["campaign_id"],
        "authority_sha256": authority["authority_sha256"],
        "model": authority["model"],
        "runtime": authority["runtime"],
        "strategy": authority["strategy"],
        "stage_footprints": {key: {
            "tensor_count": authority["stage_footprints"][key]["tensor_count"],
            "logical_required_bytes": authority["stage_footprints"][key]["logical_required_bytes"],
            "shards": authority["stage_footprints"][key]["shards"],
        } for key in ("stage-a", "stage-b")},
        "fleet_census_sha256": hashlib.sha256(canonical(fleet)).hexdigest(),
        "reduced_at_unix": now_unix,
        "placement": placement,
        "terminal": CAPACITY_PREREQUISITE,
        "smallest_prerequisite": (
            "A compatible single-resource capacity path for each exact R7-B contiguous stage, without tensor parallelism, offload, conversion, or an alternate cut."),
        "phase_stop": "Phase 2 capacity gate; no Phase 3 official-state acquisition was authorized",
        "non_claims": authority["non_claims"],
    }
    document["record_sha256"] = hashlib.sha256(canonical(document)).hexdigest()
    return document


def verify_committed_terminal(authority: dict[str, Any], fleet: dict[str, Any], committed: dict[str, Any]) -> None:
    preserved_time = committed.get("reduced_at_unix")
    if not isinstance(preserved_time, int):
        raise ValueError("ISSUE222_FAIL: committed terminal lacks preserved reduction time")
    expected = reduction_document(authority, fleet, now_unix=preserved_time)
    if committed.get("terminal") != expected["terminal"]:
        raise ValueError("ISSUE222_FAIL: authored terminal contradicts reduction")
    if committed != expected:
        raise ValueError("ISSUE222_FAIL: committed terminal differs from deterministic reduction")


def _probe(argv: list[str]) -> dict[str, Any]:
    result = subprocess.run(argv, capture_output=True, text=True)
    stdout = result.stdout or ""
    stderr = result.stderr or ""
    return {"argv": argv, "returncode": result.returncode, "stdout": stdout,
            "stderr": stderr, "stdout_sha256": hashlib.sha256(stdout.encode()).hexdigest(),
            "stderr_sha256": hashlib.sha256(stderr.encode()).hexdigest()}


def collect_local(authority_path: Path, out: Path) -> dict[str, Any]:
    """Collect a read-only current-host NVIDIA census bound to frozen authority."""
    authority = load(authority_path.parent.parent.parent.parent, str(authority_path)) if not authority_path.is_absolute() else json.loads(authority_path.read_text())
    raw = dict(authority)
    claimed = raw.pop("authority_sha256", None)
    if claimed != hashlib.sha256(canonical(raw)).hexdigest():
        raise SystemExit("ISSUE222_COLLECT_FAIL: authority self-digest")
    if authority.get("producer_sha256") != sha256(Path(__file__).resolve()):
        raise SystemExit("ISSUE222_COLLECT_FAIL: collector source identity")
    gpu = _probe(["nvidia-smi", "--query-gpu=index,uuid,pci.bus_id,name,memory.total,memory.free,memory.used,driver_version", "--format=csv,noheader,nounits"])
    apps = _probe(["nvidia-smi", "--query-compute-apps=pid,gpu_uuid,used_memory", "--format=csv,noheader,nounits"])
    host = _probe(["hostname"])
    storage = _probe(["df", "-B1", "."])
    memory = _probe(["free", "-b"])
    receipts = {"nvidia_smi_gpu": gpu, "nvidia_smi_apps": apps, "hostname": host,
                "storage": storage, "memory": memory}
    host_name = host["stdout"].strip()
    try:
        resources, problems = _raw_resources(host_name, receipts)
    except ValueError as error:
        raise SystemExit(f"ISSUE222_COLLECT_FAIL: {error}") from error
    document = {"schema": HOST_RECORD_SCHEMA, "campaign_id": authority.get("campaign_id"),
                "host": host_name, "authority_sha256": authority.get("authority_sha256"),
                "collector_sha256": sha256(Path(__file__).resolve()),
                "collected_at_unix": int(time.time()), "receipts": receipts,
                "resources": resources, "problems": problems}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(canonical(document))
    return document


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write-authority", action="store_true")
    mode.add_argument("--collect", action="store_true")
    mode.add_argument("--assemble-fleet", action="store_true")
    mode.add_argument("--record-connection-failure", action="store_true")
    mode.add_argument("--reduce", action="store_true")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--authority", type=Path)
    parser.add_argument("--fleet", type=Path)
    parser.add_argument("--records-dir", type=Path)
    parser.add_argument("--host")
    parser.add_argument("--returncode", type=int)
    parser.add_argument("--stderr-file", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--repo-head")
    args = parser.parse_args()
    if args.write_authority:
        document = build_authority(args.root, repo_head=args.repo_head)
    elif args.collect:
        if args.authority is None:
            parser.error("--collect requires --authority")
        document = collect_local(args.authority, args.out)
        print(json.dumps({"resources": len(document["resources"]), "problems": document["problems"]}))
        return 0
    elif args.assemble_fleet:
        if args.authority is None or args.records_dir is None:
            parser.error("--assemble-fleet requires --authority and --records-dir")
        records = {}
        for host in CANDIDATE_HOSTS:
            path = args.records_dir / f"{host}.json"
            if not path.is_file():
                parser.error(f"missing host record: {path}")
            records[host] = json.loads(path.read_text())
        document = assemble_fleet(json.loads(args.authority.read_text()), records)
    elif args.record_connection_failure:
        if (args.authority is None or args.host is None or args.returncode is None
                or args.stderr_file is None):
            parser.error("--record-connection-failure requires --authority --host --returncode --stderr-file")
        document = record_connection_failure(json.loads(args.authority.read_text()), args.host,
                                             args.returncode, args.stderr_file.read_text())
    else:
        if args.authority is None or args.fleet is None:
            parser.error("--reduce requires --authority and --fleet")
        document = reduction_document(json.loads(args.authority.read_text()), json.loads(args.fleet.read_text()), now_unix=int(time.time()))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes(canonical(document))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
