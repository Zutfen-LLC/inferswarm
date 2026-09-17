#!/usr/bin/env python3
"""Issue #215 — V2-C per-boot V340L execution sentinel (Phase 4).

Runs DIRECTLY on inferswarm02. For each die (a, b) separately:
  1. fresh discovery: llama-cli --list-devices enumeration + zero-generation
     identity probe binding selector -> BDF (accepted #210 semantics);
  2. bounded execution sentinel: the frozen argv (8 tokens, full offload,
     temp 0 / seed 42), visible output extracted by the ACCEPTED V0-C
     comparator (extract_visible_response, imported never forked) and
     compared byte-exact against the accepted V1-A reference prefix;
  3. accounting via the ACCEPTED V1-C selector-aware reducer (imported,
     never forked) over the sentinel stderr;
  4. offload completion derived from the runtime's own offload line.

Never reuses a previous boot's selector authority. Writes raw + structured
records; attribution (cycle, boot_id, die, selector, BDF) is sealed into
every record and every raw artifact set.

Usage (on inferswarm02, sudo):
  python3 issue215_sentinel.py --cycle <n> --boot-id <id> \
      --repo <inferswarm checkout> --out-root <evidence root>
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = "inferswarm.v2c.execution-sentinel/1"
CAMPAIGN_ID = "issue215-v2c-v340l-platform-stability-v1"

RUNTIME_EXECUTABLE = "/home/zutfen/.cache/v0c-llama.cpp/build-v0c-vulkan/bin/llama-cli"
MODEL = "/home/zutfen/.cache/v0c-models/Qwen2.5-3B-Instruct-Q4_K_M.gguf"
PROMPT = "The quick brown fox jumps over the lazy dog. Explain what happens next in one sentence:"
N_TOKENS = 8

VEGA_ID = "1002:6864"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def list_devices() -> tuple[list[dict], bytes]:
    """Fresh Vulkan enumeration through the runtime's own device list."""
    p = subprocess.run([RUNTIME_EXECUTABLE, "--list-devices"], capture_output=True, text=False, timeout=300)
    if p.returncode != 0:
        raise RuntimeError(f"--list-devices failed rc={p.returncode}")
    devices = []
    for line in p.stdout.decode("utf-8", "replace").splitlines():
        m = re.match(r"^(Vulkan[0-9]+): (.*)$", line.strip())
        if m:
            devices.append({"selector": m.group(1), "name": m.group(2)})
    return devices, p.stdout


def probe_identity(selector: str) -> dict:
    """Zero-generation identity probe (accepted #210 semantics): the
    runtime's own selected-device line proves selector -> BDF without
    generating any model token."""
    argv = [RUNTIME_EXECUTABLE, "-m", MODEL, "--temp", "0", "--seed", "42", "-n", "0",
            "-ngl", "0", "--device", selector, "-lv", "4", "-p", PROMPT, "-st"]
    p = subprocess.run(argv, capture_output=True, text=False, timeout=600)
    stderr = p.stderr.decode("utf-8", "replace")
    matches = re.findall(r"using device.*$", stderr, re.M)
    bdf = None
    for line in matches:
        m = re.search(r"([0-9a-f]{2}:[0-9a-f]{2}\.[0-9])", line)
        if m:
            bdf = m.group(1)
            break
    rates = re.findall(r"^Generation: ([0-9.]+) t/s", stderr, re.M)
    return {"argv": argv, "rc": p.returncode, "identity_proof_line": matches[0] if matches else None,
            "bdf": bdf, "zero_generation_proof": [f"Generation: {r} t/s" for r in rates],
            "stderr": stderr}


def vega_bdfs() -> list[str]:
    lspci = subprocess.run(["lspci", "-nn"], capture_output=True, text=True, timeout=60)
    return [line.split()[0] for line in lspci.stdout.splitlines() if VEGA_ID in line]


def run_sentinel(selector: str) -> dict:
    argv = [RUNTIME_EXECUTABLE, "-m", MODEL, "--temp", "0", "--seed", "42", "-n", str(N_TOKENS),
            "-ngl", "99", "--device", selector, "-lv", "4", "-p", PROMPT, "-st"]
    started = _now()
    p = subprocess.run(argv, capture_output=True, text=False, timeout=1800)
    return {"argv": argv, "started_utc": started, "rc": p.returncode,
            "stdout": p.stdout, "stderr": p.stderr}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cycle", type=int, required=True)
    parser.add_argument("--boot-id", required=True)
    parser.add_argument("--out-root", required=True)
    parser.add_argument("--repo", required=True, help="inferswarm checkout with scripts/v0c_*.py, v1c_accounting.py")
    args = parser.parse_args()

    repo = Path(args.repo)
    sys.path.insert(0, str(repo / "scripts"))
    import v0c_correctness  # noqa: E402  (accepted comparator; never forked)
    import v1c_accounting  # noqa: E402  (accepted selector-aware accounting reducer)

    repo_head = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                               capture_output=True, text=True).stdout.strip()
    repo_dirty = bool(subprocess.run(["git", "-C", str(repo), "status", "--porcelain"],
                                     capture_output=True, text=True).stdout.strip())

    out_root = Path(args.out_root)
    out = out_root / f"cycle-{args.cycle:02d}-sentinels"
    out.mkdir(parents=True, exist_ok=True)

    devices, enum_stdout = list_devices()
    (out / "list-devices.stdout").write_bytes(enum_stdout)
    bdfs = vega_bdfs()
    record: dict = {
        "schema": SCHEMA,
        "campaign_id": CAMPAIGN_ID,
        "cycle_index": args.cycle,
        "boot_id": args.boot_id,
        "repo_head": repo_head,
        "repo_dirty": repo_dirty,
        "comparator_identity": {
            "v0c_correctness_sha256": sha256_bytes((repo / "scripts/v0c_correctness.py").read_bytes()),
            "v1c_accounting_sha256": sha256_bytes((repo / "scripts/v1c_accounting.py").read_bytes()),
        },
        "enumeration": {"devices": devices, "vega_bdfs_live": bdfs},
        "dies": {},
        "captured_utc": _now(),
    }

    vega_selectors = [d for d in devices if "V340" in d["name"] or "Vega" in d["name"]]
    if len(vega_selectors) != 2:
        record["result"] = "DISCOVERY_FAILED"
        record["reason"] = f"expected exactly 2 Vega selectors, saw {len(vega_selectors)}"
        (out / "sentinel-record.json").write_bytes(json.dumps(record, indent=1).encode() + b"\n")
        print(json.dumps({"result": "DISCOVERY_FAILED", "reason": record["reason"]}))
        return 1

    ref_path = repo / "docs/investigations/vulkan-v1-a/reference-visible-output.txt"
    ref_bytes = ref_path.read_bytes()
    ref_sha = sha256_bytes(ref_bytes)

    for i, dev in enumerate(sorted(vega_selectors, key=lambda d: d["selector"])):
        die = "a" if i == 0 else "b"
        d_out = out / f"die-{die}"
        d_out.mkdir()
        probe = probe_identity(dev["selector"])
        (d_out / "probe-stderr.txt").write_bytes(probe["stderr"].encode())
        (d_out / "probe.json").write_bytes(json.dumps(
            {k: v for k, v in probe.items() if k != "stderr"}, indent=1).encode() + b"\n")
        run = run_sentinel(dev["selector"])
        (d_out / "stdout.txt").write_bytes(run["stdout"])
        (d_out / "stderr.txt").write_bytes(run["stderr"])
        (d_out / "exit-code.txt").write_text(f"{run['rc']}\n")
        stderr_text = run["stderr"].decode("utf-8", "replace")
        # Accepted comparator grammar extracts the visible response; the
        # sentinel policy is byte-exact PREFIX equality against the frozen
        # reference (frozen plan: comparator = byte-exact-prefix-of-accepted-
        # reference; -n 8 vs the 48-token full canonical reference).
        try:
            visible = v0c_correctness.extract_visible_response(run["stdout"], PROMPT.encode())
            byte_exact = bool(visible) and ref_bytes.startswith(visible)
        except Exception as exc:  # grammar failure = sentinel FAIL
            visible = b""
            byte_exact = False
            correctness = {"error": f"{type(exc).__name__}: {exc}"}
        else:
            correctness = {
                "visible_response_sha256": sha256_bytes(visible),
                "reference_sha256": ref_sha,
                "byte_exact_prefix_of_reference": byte_exact,
            }
        (d_out / "visible-output.txt").write_bytes(visible)
        # Accepted selector-aware accounting reducer.
        try:
            accounting = v1c_accounting.parse_accounting(stderr_text, selector=dev["selector"])
            accounting_clean = all(accounting[k] == 0 for k in (
                "unexplained_persistent_host_mirror_bytes", "source_fetches_after_ready",
                "unplanned_state_movements"))
            accounting_reduced = {k: accounting[k] for k in (
                "unexplained_persistent_host_mirror_bytes", "source_fetches_after_ready",
                "unplanned_state_movements")}
        except Exception as exc:
            accounting_reduced = {"error": f"{type(exc).__name__}: {exc}"}
            accounting_clean = False
        m = re.search(r"offloaded (\d+)/(\d+) layers", stderr_text)
        offloaded = [int(m.group(1)), int(m.group(2))] if m else None
        offload_full = offloaded is not None and offloaded[0] == offloaded[1]
        ok = run["rc"] == 0 and byte_exact and accounting_clean and offload_full
        record["dies"][die] = {
            "selector": dev["selector"], "device_name": dev["name"],
            "probe_bdf": probe["bdf"], "identity_proof_line": probe["identity_proof_line"],
            "probe_rc": probe["rc"],
            "stdout_sha256": sha256_bytes(run["stdout"]), "stderr_sha256": sha256_bytes(run["stderr"]),
            "visible_output_sha256": sha256_bytes(visible),
            "byte_exact_visible_output": byte_exact,
            "exit_code": run["rc"], "argv": run["argv"],
            "offloaded_layers": offloaded, "offload_full": offload_full,
            "accounting_three_tuple": accounting_reduced,
            "accounting_clean": accounting_clean,
            "reference_sha256": ref_sha, "reference_len": len(ref_bytes),
            "visible_len": len(visible),
            "result": "PASS" if ok else "FAIL",
        }

    (out / "sentinel-record.json").write_bytes(json.dumps(record, indent=1).encode() + b"\n")
    summary = {d: record["dies"][d]["result"] for d in record["dies"]}
    print(json.dumps({"cycle": args.cycle, "boot_id": args.boot_id, "dies": summary}))
    return 0 if all(v == "PASS" for v in summary.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
