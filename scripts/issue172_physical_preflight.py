#!/usr/bin/env python3
"""Issue #172 — Phase 3 physical preflight (runs per host, read-only).

Collected on each node before the first canonical result:

- git identity + cleanliness of the deployed FreeToken producer and the
  sha256 of every correctness-bearing benchmark/runtime file;
- live GPU inventory (index, UUID, BDF, driver) and the frozen-geometry
  binding check (frozen devices present at frozen indices);
- software identity (python, torch, CUDA, nvcc, transformers);
- accepted substrate byte reconciliation (materialized participant
  safetensors + reports against the accepted #133 reconciliation rows);
- #157 instrumentation-off proof (no ISSUE157 env gates, no injected
  sitecustomize on the serving path);
- tokenizer deployment pin check (the five assets, exact digests);

Usage: issue172_physical_preflight.py --host inferswarm01 --out FILE
Run ON the target host. Pure stdlib. Read-only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import issue172_campaign_pins as P  # noqa: E402

FROZEN_GEOMETRY = {
    "inferswarm01": {
        "0": "GPU-1fc28f83-1d45-926e-54d0-ba1e835ef099",
        "1": "GPU-d5c05739-96c1-7e49-89b6-bf54c2121c55",
    },
    "inferswarm03": {
        "0": "GPU-e1f2f90c-49ab-2689-0cf1-e5d9da520176",
    },
}

#: accepted #133 substrate reconciliation rows (byte-pinned)
SUBSTRATE_01 = {
    "dense.6171f32b4413.stage-1/armb-participant.safetensors":
        "2e8cf1af3ff64f7d5f800dac72fea2d418ffa81b15c3a90da5fd42542eaa9ed5",
    "dense.6171f32b4413.stage-2/armb-participant.safetensors":
        "85b218060e0242af6fb27a2e988a24a66892511e8067c38ca90280efa3af038d",
}
SUBSTRATE_03 = {
    "dense.6171f32b4413.stage-3/armb-participant.safetensors":
        "120e9c29173e91419fe1cfd355651bede6bf195f331e9dac2fd682c4420e6036",
}

SUBSTRATE_ROOT = "/srv/inferswarm/materialized/issue117"

#: correctness-bearing producer files (the r6 serving closure minus
#: pure docs); every file must match its git blob at the pinned commit
PRODUCER_FILES = [
    "benchmarks/inferswarm_r6/stage_runtime.py",
    "benchmarks/inferswarm_r6/stage_chain.py",
    "benchmarks/inferswarm_r6/chain_runtime.py",
    "benchmarks/inferswarm_r6/coordinator.py",
    "benchmarks/inferswarm_r6/node_agent.py",
    "benchmarks/inferswarm_r6/last_stage_service.py",
    "benchmarks/inferswarm_r6/wire_client.py",
    "benchmarks/inferswarm_r6/strategy.py",
    "benchmarks/inferswarm_r6/xc_strategy.py",
    "benchmarks/inferswarm_r6/freeze_environment.py",
    "benchmarks/inferswarm_xc/node_agent.py",
    "benchmarks/inferswarm_xc/cpu_only.py",
    "python/freetoken/research/r3_planner.py",
    "python/freetoken/research/r5a_serving.py",
    "python/freetoken/research/r5b_epochs.py",
    "python/freetoken/research/xc_coordinator.py",
    "python/freetoken/research/xc_wire.py",
    "python/freetoken/research/prefill_partition.py",
]

TOKENIZER_ASSET_PINS = {
    "chat_template.jinja":
        "ae53464bf3be25802b3a5b37def7fd89667067d7577049b3b2d74c4d8de4c6d4",
    "config.json":
        "478c46e8d2c52d5c2d85bf67e3b3e8c90e7c9d91086cee27e3c267907e936bd9",
    "generation_config.json":
        "a8349d9bd64cc5841297fcb5002f0fdc4749c473c8f1b10ea337f9ce4ee7014e",
    "tokenizer.json":
        "cc8d3a0ce36466ccc1278bf987df5f71db1719b9ca6b4118264f45cb627bfe0f",
    "tokenizer_config.json":
        "a62f4e85a47c0c136edaaa3a4f591fd6783717299a9def47e5ad03a49f6a5eb9",
}
TOKENIZER_DEPLOYMENT = "/srv/inferswarm/tokenizers/gemma-r6-frozen"


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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", required=True)
    parser.add_argument("--repo", required=True,
                        help="deployed FreeToken worktree")
    parser.add_argument("--venv-python", default=None,
                        help="compute-node venv python (torch identity)")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    repo = Path(args.repo)
    problems: list[str] = []

    # producer identity
    head = check(["git", "-c", f"safe.directory={repo}", "-C", str(repo),
                  "rev-parse", "HEAD"])
    dirty = check(["git", "-c", f"safe.directory={repo}", "-C", str(repo),
                   "status", "--porcelain"])
    if head != P.FREETOKEN_RESEARCH_172:
        problems.append(f"producer head {head} != {P.FREETOKEN_RESEARCH_172}")
    if dirty:
        problems.append("producer tree dirty")

    # correctness-bearing file digests vs pinned git blobs
    file_hashes = {}
    for rel in PRODUCER_FILES:
        live = repo / rel
        if not live.is_file():
            problems.append(f"missing producer file {rel}")
            continue
        digest = sha256_file(live)
        file_hashes[rel] = digest
        blob = subprocess.run(
            ["git", "-c", f"safe.directory={repo}", "-C", str(repo),
             "show", f"{P.FREETOKEN_RESEARCH_172}:{rel}"],
            capture_output=True).stdout
        if hashlib.sha256(blob).hexdigest() != digest:
            problems.append(f"live byte drift for {rel}")
    if file_hashes.get("benchmarks/inferswarm_r6/stage_runtime.py") != \
            P.STAGE_RUNTIME_SHA256_AT_166:
        problems.append("stage_runtime.py is not the #166-remediated bytes")

    # GPU inventory + frozen geometry binding
    gpus = []
    smi = check(["nvidia-smi", "--query-gpu=index,uuid,pci.bus_id,name,"
                 "driver_version", "--format=csv,noheader"])
    for line in smi.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) >= 5:
            gpus.append({"index": parts[0], "uuid": parts[1],
                         "pci_bdf": parts[2], "name": parts[3],
                         "driver_version": parts[4]})
    for index, uuid in FROZEN_GEOMETRY.get(args.host, {}).items():
        match = [g for g in gpus if g["index"] == index]
        if not match or match[0]["uuid"] != uuid:
            problems.append(
                f"frozen geometry device {args.host}/gpu-{index} "
                f"({uuid}) not present at that index")

    # software identity
    software = {
        "python": check([sys.executable, "--version"]).split()[-1],
        "nvcc": check(["/usr/local/cuda/bin/nvcc", "--version"]).split(
            "release ")[-1].split(",")[0] if Path(
                "/usr/local/cuda/bin/nvcc").exists() else None,
    }
    if args.venv_python:
        venv = check([args.venv_python, "-c",
                      "import torch;print(torch.__version__,"
                      " torch.version.cuda)"])
        software["torch"] = venv

    # substrate reconciliation (participant bytes)
    substrate = {}
    expected = SUBSTRATE_01 if args.host == "inferswarm01" else (
        SUBSTRATE_03 if args.host == "inferswarm03" else {})
    for rel, want in expected.items():
        path = Path(SUBSTRATE_ROOT) / rel
        if not path.is_file():
            problems.append(f"substrate missing {rel}")
            continue
        got = sha256_file(path)
        substrate[rel] = got
        if got != want:
            problems.append(f"substrate byte drift {rel}")

    # #157 instrumentation off
    instrumentation = {
        "issue157_env_gates_present": sorted(
            k for k in os.environ if "ISSUE157" in k),
        "r6_localization_env_gates_present": sorted(
            k for k in os.environ if "R6_LOCALIZATION" in k),
        "pythonpath": os.environ.get("PYTHONPATH", ""),
        "sitecustomize_on_path": any(
            (Path(p) / "sitecustomize.py").exists()
            for p in sys.path if p and p != "" and Path(p).is_dir()),
    }
    if instrumentation["issue157_env_gates_present"]:
        problems.append("ISSUE157 instrumentation gate is set")
    if instrumentation["r6_localization_env_gates_present"]:
        problems.append("R6_LOCALIZATION gate is set")

    # tokenizer deployment (exact five assets)
    tokenizer = {"path": TOKENIZER_DEPLOYMENT, "assets": {}}
    tok_dir = Path(TOKENIZER_DEPLOYMENT)
    if tok_dir.is_dir():
        entries = sorted(p.name for p in tok_dir.iterdir())
        if entries != sorted(TOKENIZER_ASSET_PINS):
            problems.append(f"tokenizer deployment entries {entries}")
        for name, want in TOKENIZER_ASSET_PINS.items():
            asset = tok_dir / name
            if asset.is_file():
                got = sha256_file(asset)
                tokenizer["assets"][name] = got
                if got != want:
                    problems.append(f"tokenizer asset drift {name}")

    record = {
        "schema": "inferswarm.issue172.arm-c-requal.physical-preflight/1",
        "campaign_id": P.CAMPAIGN_ID,
        "host": args.host,
        "producer": {"head": head, "clean": not dirty},
        "producer_file_sha256": file_hashes,
        "gpus": gpus,
        "extra_gpu_hardware_note": (
            "frozen geometry binds only the frozen devices at the frozen "
            "indices; additional physical GPUs are recorded inventory"),
        "software": software,
        "substrate_reconciliation": substrate,
        "instrumentation_off": instrumentation,
        "tokenizer_deployment": tokenizer,
        "collected_at_unix": int(time.time()),
        "passed": not problems,
        "problems": problems,
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"host": args.host, "passed": not problems,
                      "problems": problems}))
    return 0 if not problems else 1


if __name__ == "__main__":
    raise SystemExit(main())
