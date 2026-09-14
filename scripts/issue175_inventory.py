#!/usr/bin/env python3
"""Issue #175 — Arm-D node-side inventory/fence collector (stdlib, read-only).

Runs ON the target host (as root via the orchestration ssh-sudo path).
Collects, without mutating anything:

- verified immutable artifact-cache inventory: exact path, byte length,
  sha256, participant binding (expected digest from the frozen pins);
- the 01-side model-view symlink targets and the 03-side direct dir;
- tokenizer deployment assets vs pins;
- execution-bearing process fence: for every process matching the
  frozen service patterns, pid + /proc/<pid>/stat starttime (field 22)
  + boot_id + cmdline + listening ports + per-GPU memory;
- the producer worktree head + cleanliness.

One record per invocation; the reducer compares records across the
restart boundary. Fail-closed on missing/corrupt cache artifacts.
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
import issue175_campaign_pins as P  # noqa: E402

SERVICE_PATTERNS = (
    "inferswarm_xc.coordinator", "inferswarm_r6.node_agent",
    "inferswarm_r6.last_stage_service", "spawn_main",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def check(command: list[str]) -> str:
    try:
        return subprocess.check_output(
            command, text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:
        return ""


def collect_processes() -> list[dict]:
    processes = []
    lines = check(["ps", "-eo", "pid,args", "--no-headers"]) or ""
    seen = set()
    for line in lines.splitlines():
        line = line.strip()
        if not line:
            continue
        pid_text, _, args = line.partition(" ")
        if not any(pattern in args for pattern in SERVICE_PATTERNS):
            continue
        if "ps -eo" in args or "issue175" in args or "grep" in args:
            continue
        try:
            pid = int(pid_text)
        except ValueError:
            continue
        if pid in seen:
            continue
        seen.add(pid)
        stat = Path(f"/proc/{pid}/stat")
        starttime = None
        if stat.is_file():
            fields = stat.read_text().rsplit(")", 1)[-1].split()
            # field 22 overall; after the comm split, starttime is
            # index 19 (fields 3.. map as 3+idx)
            starttime = fields[19] if len(fields) > 19 else None
        processes.append({
            "pid": pid,
            "starttime": starttime,
            "boot_id": (Path("/proc/sys/kernel/random/boot_id").read_text()
                        .strip() if Path("/proc/sys/kernel/random/boot_id")
                        .is_file() else None),
            "args": args[:300],
        })
    return processes


def collect_ports() -> dict:
    listening = {}
    for port in (18080, 18485, 18486):
        out = check(["ss", "-tlnp", f"sport = :{port}"])
        listening[str(port)] = out
    return listening


def collect_gpu() -> list[dict]:
    smi = check(["nvidia-smi",
                 "--query-gpu=index,uuid,memory.used,driver_version",
                 "--format=csv,noheader"])
    rows = []
    for line in smi.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) >= 4:
            rows.append({"index": parts[0], "uuid": parts[1],
                         "memory_used": parts[2],
                         "driver": parts[3]})
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", required=True)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--phase", required=True,
                        help="label: e.g. pre-restart-1, post-restart-1")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    problems: list[str] = []
    host = args.host

    # producer worktree identity
    repo = Path(args.repo)
    head = check(["git", "-c", f"safe.directory={repo}", "-C", str(repo),
                  "rev-parse", "HEAD"])
    dirty = check(["git", "-c", f"safe.directory={repo}", "-C", str(repo),
                   "status", "--porcelain"])
    if head != P.FREETOKEN_RESEARCH_175:
        problems.append(f"producer head {head}")
    if dirty:
        problems.append("producer tree dirty")

    # artifact cache inventory (expected artifacts for this host)
    cache = {}
    expected = P.CACHE_ARTIFACTS.get(host, {})
    for rel, want in expected.items():
        path = Path(P.SUBSTRATE_ROOT) / rel
        if not path.is_file():
            problems.append(f"cache artifact missing {rel}")
            continue
        size = path.stat().st_size
        digest = sha256_file(path)
        cache[rel] = {
            "path": str(path), "bytes": size, "sha256": digest,
            "expected_sha256": want,
            "verified": digest == want,
        }
        if digest != want:
            problems.append(f"cache artifact digest drift {rel}")

    # model view binding
    model_view = {"path": P.MODEL_VIEW_01 if host == "inferswarm01"
                  else P.MODEL_VIEW_03}
    view = Path(model_view["path"])
    if host == "inferswarm00":
        model_view["note"] = (
            "the CPU-only Coordinator holds no model view by design")
    elif view.is_dir():
        entries = {}
        for entry in sorted(view.iterdir()):
            if entry.is_symlink():
                target = str(entry.resolve())
                entries[entry.name] = {"symlink": str(
                    entry.readlink()), "resolved": target}
                if not entry.resolve().is_file():
                    problems.append(f"model view dangling {entry.name}")
            elif entry.is_file():
                entries[entry.name] = {"bytes": entry.stat().st_size}
        model_view["entries"] = entries
    else:
        problems.append("model view dir missing")

    # tokenizer deployment
    tokenizer: dict = {"path": P.TOKENIZER_DEPLOYMENT, "assets": {}}
    tok_dir = Path(P.TOKENIZER_DEPLOYMENT)
    if host == "inferswarm00" or tok_dir.is_dir():
        names = sorted(p.name for p in tok_dir.iterdir()) if (
            tok_dir.is_dir()) else []
        if names and names != sorted(P.TOKENIZER_ASSET_PINS):
            problems.append(f"tokenizer entries {names}")
        for name, want in P.TOKENIZER_ASSET_PINS.items():
            asset = tok_dir / name
            if asset.is_file():
                got = sha256_file(asset)
                tokenizer["assets"][name] = got
                if got != want:
                    problems.append(f"tokenizer drift {name}")

    record = {
        "schema": P.INVENTORY_SCHEMA,
        "campaign_id": P.CAMPAIGN_ID,
        "host": host,
        "phase": args.phase,
        "producer": {"head": head, "clean": not dirty},
        "cache_artifacts": cache,
        "model_view": model_view,
        "tokenizer": tokenizer,
        "processes": collect_processes(),
        "ports": collect_ports(),
        "gpus": collect_gpu() if host != "inferswarm00" else [],
        "problems": problems,
        "collected_at_unix": int(time.time()),
        "passed": not problems,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"host": host, "phase": args.phase,
                      "passed": not problems, "problems": problems,
                      "process_count": len(record["processes"])}))
    return 0 if not problems else 1


if __name__ == "__main__":
    raise SystemExit(main())
