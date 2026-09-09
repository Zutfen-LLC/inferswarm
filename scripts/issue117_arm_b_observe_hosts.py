#!/usr/bin/env python3
"""Regenerate the host-observation records under evidence/arm-b/observations/.

READ-ONLY: every fabric interaction here is a read (ssh find/stat/
sha256sum/scp of existing logs). No host file is modified, created, or
deleted; no model bytes, cold roots, caches, or holdout material are
touched. Run from the repo root:

    python3 scripts/issue117_arm_b_observe_hosts.py

Outputs (overwrites in place, deterministic given unchanged hosts):
  observations/coordinator-state-inventory.json
  observations/root-inode-continuity.json
  observations/host-raw-log-pins.json

The raw logs themselves (raw/*.log) are fetched separately via scp; this
script only pins them.
"""
from __future__ import annotations

import datetime
import json
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OBS = (REPO / "docs" / "implementation" /
       "r6-successor-dense-full-integration-117" / "evidence" /
       "arm-b" / "observations")


def ssh(host: str, cmd: str) -> str:
    r = subprocess.run(["ssh", host, cmd], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"{host}: {cmd}\n{r.stderr}")
    return r.stdout


def main() -> int:
    stamp = datetime.datetime.now(
        datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # 1. coordinator state-tree inventory (read-only)
    out = ssh("inferswarm00",
              "sudo -n find /srv/inferswarm/state/arm-b -mindepth 1 "
              "-printf '%y|%s|%P|%l\\n'")
    entries = []
    for line in out.strip().splitlines():
        parts = line.split("|")
        ftype, size, rel = parts[0], int(parts[1]), parts[2]
        link = parts[3] if len(parts) > 3 else ""
        entries.append({"path": rel, "type": ftype, "size": size,
                        "symlink_target": link or None})
    entries.sort(key=lambda e: e["path"])
    dig = ssh("inferswarm00",
              "sudo -n bash -c 'find /srv/inferswarm/state/arm-b -type f "
              "-exec sha256sum {} +'")
    files = {}
    for line in dig.strip().splitlines():
        h, p = line.split(None, 1)
        files[p.replace("/srv/inferswarm/state/arm-b/", "")] = h
    inv = {
        "schema": "inferswarm.issue117.arm-b.coordinator-state-inventory/1",
        "observation_utc": stamp,
        "path_on_inferswarm00": "/srv/inferswarm/state/arm-b/",
        "mechanism": ("read-only ssh find/stat/sha256sum over the "
                      "coordinator state tree (no writes)"),
        "entries": entries,
        "regular_file_digests": files,
        "symlink_count": sum(1 for e in entries if e["type"] == "l"),
        "total_file_count": sum(1 for e in entries if e["type"] == "f"),
        "total_bytes": sum(e["size"] for e in entries if e["type"] == "f"),
    }
    assert len(files) == inv["total_file_count"]
    (OBS / "coordinator-state-inventory.json").write_text(
        json.dumps(inv, indent=1, sort_keys=True) + "\n")
    print(f"coordinator inventory: {inv['total_file_count']} files, "
          f"{inv['total_bytes']} bytes, {inv['symlink_count']} symlinks")

    # 2. canonical-root inode continuity (read-only)
    roots = {"inferswarm01": ["/srv/inferswarm/cache/issue117",
                              "/srv/inferswarm/materialized/issue117"],
             "inferswarm03": ["/srv/inferswarm/cache/issue117",
                              "/srv/inferswarm/materialized/issue117"]}
    obs = {"schema": "inferswarm.issue117.arm-b.root-inode-observation/1",
           "observation_utc": stamp,
           "mechanism": "read-only ssh stat of the canonical roots",
           "roots": {}}
    for host, ps in roots.items():
        o = {}
        for p in ps:
            st = ssh(host, f"stat -c '%i %F' {p}").strip()
            ino, typ = st.split(None, 1)
            o[p] = {"st_ino": int(ino), "type": typ}
        obs["roots"][host] = o
    (OBS / "root-inode-continuity.json").write_text(
        json.dumps(obs, indent=1, sort_keys=True) + "\n")

    # 3. host-side raw log pins (read-only)
    pins = {"schema": "inferswarm.issue117.arm-b.host-raw-log-pins/1",
            "observation_utc": stamp, "logs": {}}
    for host, path, key in [
        ("inferswarm01", "/tmp/armb-source-server.log",
         "source-server-access.log"),
        ("inferswarm01",
         "/srv/inferswarm/materialized/issue117/"
         "dense.6171f32b4413.stage-1/realize-strace.log",
         "realize-strace.stage-1.log"),
        ("inferswarm01",
         "/srv/inferswarm/materialized/issue117/"
         "dense.6171f32b4413.stage-2/realize-strace.log",
         "realize-strace.stage-2.log"),
        ("inferswarm03",
         "/srv/inferswarm/materialized/issue117/"
         "dense.6171f32b4413.stage-3/realize-strace.log",
         "realize-strace.stage-3.log")]:
        line = ssh(host, f"sha256sum {path}").strip()
        meta = ssh(host, f"stat -c '%s %y' {path}").strip()
        h = line.split()[0]
        size, mtime = meta.split(None, 1)
        pins["logs"][key] = {"host": host, "path": path, "sha256": h,
                             "size_bytes": int(size),
                             "mtime": mtime.strip()}
    (OBS / "host-raw-log-pins.json").write_text(
        json.dumps(pins, indent=1, sort_keys=True) + "\n")
    print("observations refreshed (read-only)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
