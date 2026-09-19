#!/usr/bin/env python3
"""Issue #228 — V2-E matched baseline collectors (Phase 4).

Same-die and host-staged controls. Executed ONLY when a peer mechanism
is available (the ladder's own refusal otherwise classifies the
campaign). These collectors mirror the #35 accepted probe grammar for
the host-facing x1 measurements: fresh measured H2D/D2H single-leg
values come from a bounded same-die Vulkan copy through a HOST_VISIBLE
staging buffer — the accepted #35 transport evidence already retains
the sustained x1 envelope; V2-E re-measures a fresh bounded sample
only when the ladder runs, and never reruns the #216 faulting
concurrent transport matrix.

When the mechanism is unavailable this collector emits the same
refusal artifact class as the ladder.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import issue228_host as host
import issue228_probe as probe
import issue228_receipt as rc
import issue228_ladder as ladder

ROOT = Path(__file__).resolve().parents[1]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_baselines(*, repo: Path, out: Path, attempt_id: str,
                  preflight: dict[str, Any], build_dir: Path) -> dict[str, Any]:
    closure = rc.verify_closure(repo)
    mechanism = ladder.classify_mechanism(preflight["capability"])
    out.mkdir(parents=True, exist_ok=True)

    if not mechanism["available"]:
        doc = {
            "schema": "inferswarm.v2e.baselines-refusal/1",
            "campaign_id": rc.CAMPAIGN_ID,
            "attempt_id": attempt_id,
            "captured_utc": _now(),
            "closure_digest": closure["closure_digest"],
            "producer_head": closure["producer_head"],
            "mechanism": mechanism,
            "refusal": (
                "Matched baselines are controls for peer arms; with no "
                "peer mechanism available there is nothing to control, "
                "and the #216 faulting transport seam is not rerun."),
            "executed": False,
        }
        (out / "refusal.json").write_bytes(
            json.dumps(doc, indent=1, sort_keys=True).encode() + b"\n")
        return doc

    binary, _, source_sha = probe.compile_probe(build_dir)
    raw = out / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []

    for dev in (0, 1):
        for size in rc.LADDER_SIZES:
            result = probe.run_transfer(binary=binary, mode="samedie",
                                        args=[str(dev), str(size),
                                              str(rc.REPS_PER_SIZE)],
                                        timeout=900)
            rel = f"samedie-{dev}-{size}.stdout"
            host.durable_write(raw / rel, result["stdout"].encode())
            host.durable_write(raw / f"samedie-{dev}-{size}.stderr",
                               result["stderr"].encode())
            rows.append({
                "control": f"same_die_{dev}", "size": size,
                "stdout_rel": f"raw/{rel}",
                "stdout_sha256": hashlib.sha256(
                    result["stdout"].encode()).hexdigest(),
                "exit_code": result["returncode"],
            })
    for size in rc.LADDER_SIZES:
        result = probe.run_transfer(binary=binary, mode="staged",
                                    args=[str(size), str(rc.REPS_PER_SIZE)],
                                    timeout=900)
        rel = f"staged-{size}.stdout"
        host.durable_write(raw / rel, result["stdout"].encode())
        host.durable_write(raw / f"staged-{size}.stderr",
                           result["stderr"].encode())
        rows.append({
            "control": "host_staged", "size": size,
            "stdout_rel": f"raw/{rel}",
            "stdout_sha256": hashlib.sha256(
                result["stdout"].encode()).hexdigest(),
            "exit_code": result["returncode"],
        })

    doc = {
        "schema": "inferswarm.v2e.baselines/1",
        "campaign_id": rc.CAMPAIGN_ID,
        "attempt_id": attempt_id,
        "captured_utc": _now(),
        "closure_digest": closure["closure_digest"],
        "producer_head": closure["producer_head"],
        "frozen_sizes": list(rc.LADDER_SIZES),
        "reps": rc.REPS_PER_SIZE,
        "rows": rows,
        "probe_source_sha256": source_sha,
    }
    (out / "baselines.json").write_bytes(
        json.dumps(doc, indent=1, sort_keys=True).encode() + b"\n")
    return doc


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=str(ROOT))
    ap.add_argument("--out", required=True)
    ap.add_argument("--attempt-id", default="base1")
    ap.add_argument("--preflight", required=True)
    ap.add_argument("--build-dir", default="/var/tmp/issue228-build")
    args = ap.parse_args()
    preflight = json.loads(Path(args.preflight).read_text())
    doc = run_baselines(repo=Path(args.repo), out=Path(args.out),
                        attempt_id=args.attempt_id, preflight=preflight,
                        build_dir=Path(args.build_dir))
    print(json.dumps({"baselines": str(Path(args.out)),
                      "executed": doc.get("executed", True)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
