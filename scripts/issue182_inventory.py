#!/usr/bin/env python3
"""Issue #182 — Arm-E node-side read-only warm inventory collector.

Runs ON the observation host (read-only; no root required). Hardened
per maintainer review comment 5666244858 (P1-1/P1-2/P1-3):

- every acceptance-bearing host probe (`ps`, per-port `ss`,
  `nvidia-smi`) retains a structured receipt (exact argv, return code,
  stdout/stderr byte counts + sha256 digests + bounded raw text) in
  the observation record, and a nonzero exit is the STOP rule
  OBS-PROBE-FAILED — a failed probe is NEVER converted into an empty
  observation;
- the observation freshness/version identity is mechanically bound:
  the collector loads the STAGED frozen authority, verifies its
  self-digest, campaign id and attempt id, and embeds
  (authority_digest, campaign_id, attempt_id, host, sequence) in the
  record; the sequence is the frozen authority constant, not a value
  manufactured by the planner adapter;
- every `sha256-<hex>` cache object must carry matching
  content-address identity (object name hex == recomputed bytes
  digest) or the campaign stops OBS-CONTENT-ADDRESS-MISMATCH; any
  unexpected file class in the objects root stops
  OBS-UNACCEPTED-CACHE-OBJECT;
- every frozen GPU of the observation host must be observed with
  parseable telemetry, a pinned memory.total, and memory.used within
  the frozen idle bound.

Strictly read-only:

- snapshot A ("before"): sha256 + stat of every file under the cache
  objects root, plus the materialized shard pins;
- semantic observation: the verified byte-range object inventory;
- snapshot B ("after"): identical re-scan; byte-preservation proof
  derives from A == B (digests AND stat).

FAILS CLOSED: any STOP rule fires -> the blocked record is written
with its problems list and `passed: false`; nothing is repaired.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import issue182_campaign_pins as P  # noqa: E402
from issue99_artifact_core import validate_self_identity  # noqa: E402

SERVICE_PATTERNS = (
    "inferswarm_xc.coordinator", "inferswarm_r6.coordinator",
    "inferswarm_r6.node_agent", "inferswarm_r6.last_stage_service",
    "spawn_main",
)

#: layout: <objects>/<artifact-hex> is a regular file whose whole bytes
#: are the artifact content; content-address identity REQUIRES the
#: object name hex to equal the recomputed sha256 of those bytes.
OBJECTS_LAYOUT = "flat content-addressed files named sha256-<hex>"

OBJECT_NAME_RE = re.compile(r"^sha256-([0-9a-f]{64})$")

FENCE_PORTS = (18080, 18485, 18486)

#: GPU telemetry columns requested (receipt retains the exact argv)
GPU_QUERY = [
    "nvidia-smi",
    "--query-gpu=index,uuid,memory.total,memory.used,driver_version",
    "--format=csv,noheader",
]


def sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 22), b""):
            digest.update(chunk)
    return digest.hexdigest()


def probe(name: str, command: list[str]) -> dict:
    """Run one acceptance-bearing probe, retaining a full receipt.

    The receipt is returned regardless of exit status; classification
    (OBS-PROBE-FAILED on nonzero) is the caller's fail-closed gate.
    """
    result = subprocess.run(command, capture_output=True, text=True)
    stdout = result.stdout or ""
    stderr = result.stderr or ""
    return {
        "name": name,
        "argv": list(command),
        "returncode": result.returncode,
        "stdout_bytes": len(stdout.encode()),
        "stdout_sha256": hashlib.sha256(stdout.encode()).hexdigest(),
        "stdout": stdout[:P.PROBE_STDOUT_CAP_BYTES],
        "stderr_bytes": len(stderr.encode()),
        "stderr_sha256": hashlib.sha256(stderr.encode()).hexdigest(),
        "stderr": stderr[:2048],
    }


def collect_fence(problems: list[dict]) -> dict:
    receipts: dict[str, dict] = {}
    processes = []

    ps_receipt = probe("ps", ["ps", "-eo", "pid,args", "--no-headers"])
    receipts["ps"] = ps_receipt
    if ps_receipt["returncode"] != 0:
        problems.append({"stop_rule": "OBS-PROBE-FAILED", "probe": "ps",
                         "returncode": ps_receipt["returncode"]})
    else:
        # `ps` succeeded: an empty match set is now admissible evidence
        for line in ps_receipt["stdout"].splitlines():
            line = line.strip()
            if not line:
                continue
            pid_text, _, args = line.partition(" ")
            if not any(pattern in args for pattern in SERVICE_PATTERNS):
                continue
            if "ps -eo" in args or "issue182" in args or "grep" in args:
                continue
            processes.append({"pid": pid_text, "args": args[:300]})

    ports = {}
    for port in FENCE_PORTS:
        receipt = probe(f"ss:{port}", ["ss", "-tln", f"sport = :{port}"])
        receipts[f"ss:{port}"] = receipt
        if receipt["returncode"] != 0:
            problems.append({"stop_rule": "OBS-PROBE-FAILED",
                             "probe": f"ss:{port}",
                             "returncode": receipt["returncode"]})
            ports[str(port)] = None
        else:
            ports[str(port)] = [
                line for line in receipt["stdout"].splitlines()
                if line.strip() and not line.lstrip().startswith("State")]

    gpu_receipt = probe("nvidia-smi", GPU_QUERY)
    receipts["nvidia-smi"] = gpu_receipt
    gpus = []
    if gpu_receipt["returncode"] != 0:
        problems.append({"stop_rule": "OBS-PROBE-FAILED",
                         "probe": "nvidia-smi",
                         "returncode": gpu_receipt["returncode"]})
    else:
        for line in gpu_receipt["stdout"].splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 5:
                gpus.append({"index": parts[0], "uuid": parts[1],
                             "memory_total": parts[2],
                             "memory_used": parts[3],
                             "driver": parts[4]})

    return {"processes": processes, "ports": ports, "gpus": gpus,
            "probe_receipts": receipts,
            "collected_at_unix": int(time.time())}


def gpu_total_mib(text: str) -> int | None:
    try:
        return int(text.split()[0])
    except (ValueError, IndexError):
        return None


def check_gpus(host: str, gpus: list[dict], problems: list[dict]) -> None:
    """Every frozen GPU of the host: observed, parseable, pinned, idle."""
    observed = {gpu["uuid"]: gpu for gpu in gpus}
    pinned = P.FROZEN_HOST_GPU_UUIDS.get(host, {})
    for extra_uuid in sorted(set(observed) - set(pinned.values())):
        problems.append({"stop_rule": "OBS-GPU-SET-MISMATCH",
                         "host": host, "unexpected_uuid": extra_uuid})
    for index, uuid in sorted(pinned.items()):
        cu_id = f"{host}/gpu-{index}"
        gpu = observed.get(uuid)
        if gpu is None:
            problems.append({"stop_rule": "OBS-GPU-SET-MISMATCH",
                             "host": host, "missing_cu": cu_id,
                             "expected_uuid": uuid})
            continue
        total = gpu_total_mib(gpu["memory_total"])
        used = gpu_total_mib(gpu["memory_used"])
        if total is None or used is None:
            problems.append({"stop_rule": "OBS-GPU-TELEMETRY-UNPARSEABLE",
                             "host": host, "cu": cu_id,
                             "memory_total": gpu["memory_total"],
                             "memory_used": gpu["memory_used"]})
            continue
        pinned_total = P.PINNED_GPU_TOTAL_BYTES.get(cu_id)
        if pinned_total is not None and total * 1024 * 1024 != pinned_total:
            problems.append({"stop_rule": "OBS-GPU-TOTAL-DRIFT",
                             "host": host, "cu": cu_id,
                             "pinned": pinned_total,
                             "actual": total * 1024 * 1024})
        if used > P.GPU_MEMORY_USED_MAX_MIB:
            problems.append({"stop_rule": "OBS-GPU-NOT-IDLE",
                             "host": host, "cu": cu_id,
                             "memory_used_mib": used,
                             "bound_mib": P.GPU_MEMORY_USED_MAX_MIB})


def scan_tree(root: str) -> dict:
    """sha256 + stat of every regular file under root (read-only)."""
    files = {}
    root_path = Path(root)
    if not root_path.is_dir():
        return {"exists": False, "files": files}
    for path in sorted(root_path.rglob("*")):
        if path.is_file() and not path.is_symlink():
            stat = path.stat()
            files[path.relative_to(root_path).as_posix()] = {
                "size": stat.st_size,
                "mtime_ns": stat.st_mtime_ns,
                "inode": stat.st_ino,
                "sha256": sha256_file(str(path)),
            }
    return {"exists": True, "files": files}


def authority_attempt_id(authority: dict) -> str | None:
    return (authority.get("attempt_state_machine") or {}).get("attempt_id")


def bind_observation_epoch(authority_path: Path,
                           host: str) -> dict:
    """Verify the staged frozen authority and derive the epoch block."""
    authority = json.loads(authority_path.read_text())
    validate_self_identity(dict(authority),
                           identity_field="authority_digest")
    if authority.get("schema") != P.AUTHORITY_SCHEMA:
        raise SystemExit(
            f"ISSUE182_COLLECT_FAIL: staged authority schema "
            f"{authority.get('schema')}")
    if authority.get("campaign_id") != P.CAMPAIGN_ID:
        raise SystemExit("ISSUE182_COLLECT_FAIL: staged authority "
                         "campaign identity")
    if authority_attempt_id(authority) != P.ATTEMPT_ID:
        raise SystemExit("ISSUE182_COLLECT_FAIL: staged authority "
                         "attempt identity")
    frozen = authority.get("observation_epoch", {})
    if frozen.get("sequence") != P.OBSERVATION_SEQUENCE:
        raise SystemExit(
            "ISSUE182_COLLECT_FAIL: staged authority observation "
            "sequence != frozen pin")
    return {
        "sequence": P.OBSERVATION_SEQUENCE,
        "authority_digest": authority["authority_digest"],
        "campaign_id": authority["campaign_id"],
        "attempt_id": authority_attempt_id(authority),
        "host": host,
    }


def classify_tree_objects(files: dict) -> tuple[list[dict], list[dict]]:
    """Classify scanned cache files into verified objects + problems.

    Pure function over the scan_tree result: every file must be a
    regular `sha256-<64-hex>` object whose name hex EQUALS the
    recomputed bytes digest (content-address identity, P1-3).
    """
    verified_objects: list[dict] = []
    problems: list[dict] = []
    for name, facts in sorted(files.items()):
        match = OBJECT_NAME_RE.match(name)
        if match is None:
            problems.append({"stop_rule": "OBS-UNACCEPTED-CACHE-OBJECT",
                             "object": name,
                             "reason": "not a sha256-<hex> object name"})
            continue
        if match.group(1) != facts["sha256"]:
            problems.append({
                "stop_rule": "OBS-CONTENT-ADDRESS-MISMATCH",
                "object": name,
                "name_hex": match.group(1),
                "bytes_sha256": facts["sha256"]})
            continue
        verified_objects.append({
            "content_digest": "sha256:" + facts["sha256"],
            "length": facts["size"],
            "byte_digest_verified": True,
            "content_address_verified": True,
            "host_path": name,
        })
    return verified_objects, problems


def collect(host: str, authority_path: Path, out_dir: Path) -> int:
    problems: list[dict] = []
    epoch = bind_observation_epoch(authority_path, host)
    fence = collect_fence(problems)

    # STOP: execution-bearing process live at observation (admissible
    # only because the ps receipt proves the probe succeeded)
    if fence["processes"]:
        problems.append({
            "stop_rule": "OBS-PROCESSES-LIVE",
            "detail": fence["processes"][:5]})

    # every frozen GPU of this host: observed, parseable, pinned, idle
    check_gpus(host, fence["gpus"], problems)

    # cache objects root: before/after byte-preservation + inventory
    before = scan_tree(P.CACHE_OBJECTS_ROOT)
    if not before["exists"]:
        problems.append({"stop_rule": "OBS-ROOT-MISSING",
                         "root": P.CACHE_OBJECTS_ROOT})

    # materialized substrate pins (read-only digest verification)
    materialized = {}
    substrate = Path(P.SUBSTRATE_ROOT)
    if not substrate.is_dir():
        problems.append({"stop_rule": "OBS-ROOT-MISSING",
                         "root": P.SUBSTRATE_ROOT})
    else:
        for rel, pin in P.MATERIALIZED_PINS.get(host, {}).items():
            path = substrate / rel.split("/", 1)[0] / rel.split("/", 1)[1] \
                if "/" in rel else substrate / rel
            entry = {"path": str(path), "expected_sha256": pin}
            if path.is_file():
                stat = path.stat()
                entry["bytes"] = stat.st_size
                entry["sha256"] = sha256_file(str(path))
                entry["verified"] = entry["sha256"] == pin
                if not entry["verified"]:
                    problems.append({
                        "stop_rule": "OBS-CACHE-DIGEST-MISMATCH",
                        "path": str(path), "expected": pin,
                        "actual": entry["sha256"]})
            else:
                entry["verified"] = False
                problems.append({"stop_rule": "OBS-ROOT-MISSING",
                                 "path": str(path)})
            materialized[rel] = entry

    # semantic observation between the two preservation scans:
    # content-address identity is PROVEN, not assumed (P1-3)
    verified_objects, classify_problems = (
        classify_tree_objects(before["files"]))
    problems.extend(classify_problems)

    after = scan_tree(P.CACHE_OBJECTS_ROOT)
    if before != after:
        problems.append({"stop_rule": "OBS-MUTATION-DETECTED",
                         "before_count": len(before["files"]),
                         "after_count": len(after["files"])})

    record = {
        "schema": P.INVENTORY_SCHEMA,
        "campaign_id": P.CAMPAIGN_ID,
        "attempt_id": P.ATTEMPT_ID,
        "host": host,
        "collected_at_unix": int(time.time()),
        "observation_epoch": epoch,
        "collector_sha256": sha256_file(str(Path(__file__).resolve())),
        "fence": fence,
        "objects_layout": OBJECTS_LAYOUT,
        "cache_root": P.CACHE_OBJECTS_ROOT,
        "preservation_before": {
            "file_count": len(before["files"]),
            "tree_digest": hashlib.sha256(json.dumps(
                before, sort_keys=True).encode()).hexdigest()},
        "preservation_after": {
            "file_count": len(after["files"]),
            "tree_digest": hashlib.sha256(json.dumps(
                after, sort_keys=True).encode()).hexdigest()},
        "byte_preservation_proven": before == after,
        "verified_objects": verified_objects,
        "materialized": materialized,
        "problems": problems,
        "passed": not problems,
    }
    record["record_digest"] = hashlib.sha256(json.dumps(
        {k: v for k, v in record.items() if k != "record_digest"},
        sort_keys=True).encode()).hexdigest()

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"warm-inventory-{host}.json").write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"host": host, "passed": record["passed"],
                      "problems": len(problems),
                      "verified_objects": len(verified_objects)}))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", required=True)
    parser.add_argument("--authority", type=Path, required=True,
                        help="staged frozen authority.json "
                             "(self-digest verified before observing)")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    return collect(args.host, args.authority, args.out)


if __name__ == "__main__":
    raise SystemExit(main())
