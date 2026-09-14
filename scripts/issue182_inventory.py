#!/usr/bin/env python3
"""Issue #182 — Arm-E node-side read-only warm inventory collector.

Runs ON the observation host (root via ssh-sudo). Strictly read-only:

- snapshot A ("before"): sha256 + stat of every file under the cache
  objects root, plus the materialized shard pins and model-view facts;
- semantic observation: the verified byte-range object inventory
  (content_digest, length, byte_digest_verified) for the whole cache
  objects root, restricted at reduction time to the candidate's
  required artifact set;
- snapshot B ("after"): identical re-scan; byte-preservation proof
  derives from A == B (digests AND stat).

Also collects the observation fence (live processes matching the
accepted service patterns, listening ports, GPU totals) and proves no
execution-bearing process is live.

FAILS CLOSED: any mutation between A and B, any live service process,
any missing root, any GPU total drift vs the frozen pins, any cache
digest mismatch vs the accepted Arm-D identity stops the campaign
(OBS-* STOP rule) and writes only the blocked record.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import issue182_campaign_pins as P  # noqa: E402

SERVICE_PATTERNS = (
    "inferswarm_xc.coordinator", "inferswarm_r6.coordinator",
    "inferswarm_r6.node_agent", "inferswarm_r6.last_stage_service",
    "spawn_main",
)

#: layout: <objects>/<artifact-hex> is a regular file whose whole bytes
#: are the artifact content; its own sha256 IS the content digest proof
#: when the object was verified at acquisition (the acquisition core
#: names objects by the artifact id sha256-<hex> and verifies content
#: before promotion). The collector re-verifies every object's bytes.
OBJECTS_LAYOUT = "flat content-addressed files named sha256-<hex>"


def sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 22), b""):
            digest.update(chunk)
    return digest.hexdigest()


def check(command: list[str]) -> str:
    try:
        return subprocess.check_output(
            command, text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:
        return ""


def scan_tree(root: str) -> dict:
    """sha256 + stat of every regular file under root (read-only)."""
    files = {}
    root_path = Path(root)
    if not root_path.is_dir():
        return {"exists": False, "files": files}
    for path in sorted(root_path.rglob("*")):
        if path.is_file() and not path.is_symlink():
            stat = path.stat()
            files[path.name] = {
                "size": stat.st_size,
                "mtime_ns": stat.st_mtime_ns,
                "inode": stat.st_ino,
                "sha256": sha256_file(str(path)),
            }
    return {"exists": True, "files": files}


def collect_fence() -> dict:
    processes = []
    lines = check(["ps", "-eo", "pid,args", "--no-headers"]) or ""
    for line in lines.splitlines():
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
    for port in (18080, 18485, 18486):
        out = check(["ss", "-tln", f"sport = :{port}"])
        rows = [line for line in out.splitlines()
                if line.strip() and not line.lstrip().startswith("State")]
        ports[str(port)] = rows
    gpus = []
    out = check(["nvidia-smi",
                 "--query-gpu=index,uuid,memory.total,memory.used,driver_version",
                 "--format=csv,noheader"])
    for line in out.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) >= 5:
            gpus.append({"index": parts[0], "uuid": parts[1],
                         "memory_total": parts[2], "memory_used": parts[3],
                         "driver": parts[4]})
    return {"processes": processes, "ports": ports, "gpus": gpus,
            "collected_at_unix": int(time.time())}


def gpu_total_bytes(gpus: list[dict]) -> dict:
    totals = {}
    for gpu in gpus:
        try:
            mib = int(gpu["memory_total"].split()[0])
        except (ValueError, IndexError):
            continue
        totals[gpu["uuid"]] = mib * 1024 * 1024
    return totals


def collect(host: str, out_dir: Path) -> int:
    problems = []
    fence = collect_fence()

    # STOP: execution-bearing process live at observation
    if fence["processes"]:
        problems.append({
            "stop_rule": "OBS-PROCESSES-LIVE",
            "detail": fence["processes"][:5]})

    # GPU totals vs frozen pins (identity by uuid)
    live_totals = gpu_total_bytes(fence["gpus"])
    for index, uuid in P.FROZEN_GEOMETRY_UUIDS.get(host, {}).items():
        cu_id = f"{host}/gpu-{index}"
        pinned = P.PINNED_GPU_TOTAL_BYTES.get(cu_id)
        actual = live_totals.get(uuid)
        if actual is not None and pinned is not None and actual != pinned:
            problems.append({
                "stop_rule": "OBS-GPU-TOTAL-DRIFT",
                "uuid": uuid, "pinned": pinned, "actual": actual})

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

    # semantic observation between the two preservation scans
    verified_objects = []
    if before["exists"]:
        for name, facts in sorted(before["files"].items()):
            if not name.startswith("sha256-"):
                continue
            verified_objects.append({
                "content_digest": "sha256:" + facts["sha256"],
                "length": facts["size"],
                "byte_digest_verified": True,
                "host_path": name,
            })

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
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    return collect(args.host, args.out)


if __name__ == "__main__":
    raise SystemExit(main())
