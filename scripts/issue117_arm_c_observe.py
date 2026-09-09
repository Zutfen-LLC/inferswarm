#!/usr/bin/env python3
"""Issue #117 Arm C — read-only host census observer (run ON each host).

Pure stdlib, read-only. Collects: canonical root stat/inode census,
materialized tree census (path/size/mtime/sha256 of small files), cache
object name set, running GPU process census, and (option) an strace-ready
command wrapper is NOT here — tracing is launched by the orchestrator.

Usage: issue117_arm_c_observe.py --tag pre|post --out FILE
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import socket
import subprocess
import time
from pathlib import Path

ROOTS = [
    "/srv/inferswarm/cache/issue117",
    "/srv/inferswarm/materialized/issue117",
    "/srv/inferswarm/state/arm-c",
]
HASH_LIMIT = 64 * 1024 * 1024  # hash files up to 64 MiB (reports/configs)


def stat_entry(path: Path) -> dict | None:
    try:
        info = path.lstat()
    except OSError:
        return None
    entry = {
        "path": str(path),
        "type": "d" if path.is_dir() and not path.is_symlink()
        else ("l" if path.is_symlink() else "f"),
        "size": info.st_size,
        "mtime_ns": info.st_mtime_ns,
        "ino": info.st_ino,
    }
    if path.is_symlink():
        entry["target"] = os.readlink(path)
    return entry


def census(root: str) -> dict:
    base = Path(root)
    if not base.exists():
        return {"exists": False}
    entries = []
    for current, dirnames, filenames in os.walk(root):
        dirnames.sort()
        for name in sorted(dirnames) + sorted(filenames):
            path = Path(current) / name
            entry = stat_entry(path)
            if entry is None:
                continue
            if (entry["type"] == "f" and 0 < entry["size"] <= HASH_LIMIT
                    and not path.is_symlink()):
                digest = hashlib.sha256()
                try:
                    with path.open("rb") as stream:
                        for chunk in iter(
                                lambda: stream.read(1 << 20), b""):
                            digest.update(chunk)
                    entry["sha256"] = digest.hexdigest()
                except OSError:
                    pass
            entries.append(entry)
    return {"exists": True, "entry_count": len(entries), "entries": entries}


def gpu_census() -> dict:
    try:
        rows = subprocess.check_output(
            ["nvidia-smi", "--query-compute-apps=pid,used_memory",
             "--format=csv,noheader"], text=True).strip()
    except Exception as error:  # noqa: BLE001
        return {"available": False, "error": str(error)}
    return {"available": True, "compute_apps": rows}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    record = {
        "schema": "inferswarm.issue117.arm-c.host-census/1",
        "host": socket.gethostname(),
        "tag": args.tag,
        "observed_at_ns": time.time_ns(),
        "roots": {root: census(root) for root in ROOTS},
        "gpu": gpu_census(),
        "source_tree_present": Path("/srv/models/gemma-r6").exists(),
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"host": record["host"], "tag": args.tag,
                      "out": str(out)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
