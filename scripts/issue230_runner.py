#!/usr/bin/env python3
"""Issue #230 — V2-F arm/controls runner (physical execution driver).

Runs one arm (probe / ladder / controls) per invocation, under:
  * the frozen producer closure (verified before anything runs);
  * the safety gate's execution-order state machine (authorize_arm);
  * per-arm health windows with immediate-stop evaluation;
  * fail-closed raw retention (probe stdout/stderr/exit bytes).

One invocation = one arm. The runner never chains arms itself: the
orchestrator (run instructions in the area README) invokes it once per
arm in the frozen order. A failed arm records 'failed' in the order
state and the campaign halts (retained earliest failure).
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import issue230_receipt as rc
import issue230_host as host
import issue230_safety as safety
import issue230_transfer as transfer

ROOT = Path(__file__).resolve().parents[1]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _durable(path: Path, doc: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    host.durable_write(path, json.dumps(doc, indent=1, sort_keys=True)
                       .encode() + b"\n")


def _arm_bdfs(mapping: dict[str, Any]) -> dict[str, str]:
    # normalize to the 16-char domain-prefixed form the C probe's
    # UUID-derived BDFs use (R3 mapping carries short BDFs)
    return {die: host.sysfs_bdf(row["fresh_pci_bdf"])
            for die, row in mapping["participants"].items()}


def run_transfer_arm(*, evidence_root: Path, repo: Path, build_dir: Path,
                     mechanism: str, direction: str, sizes: tuple[int, ...],
                     reps: int, warmups: int, probe: bool) -> dict[str, Any]:
    """Execute one transfer arm (probe or ladder) for one mechanism and
    direction across the given sizes, in ascending order."""
    closure = rc.verify_closure(repo)
    mapping = json.loads(
        (evidence_root / "preflight" / "mapping" / "fresh-mapping.json")
        .read_text(encoding="utf-8"))
    arm_id = ("probe" if probe else "ladder") + \
        f"-{mechanism}-{direction}"
    auth = safety.authorize_arm(evidence_root, arm_id)

    raw = evidence_root / "raw"
    binary, source = transfer.compile_transfer(build_dir)

    # identity binding for THIS arm (read-only, current boot)
    bdfs = _arm_bdfs(mapping)
    bdf_src = bdfs["a"] if direction == "a_to_b" else bdfs["b"]
    bdf_dst = bdfs["b"] if direction == "a_to_b" else bdfs["a"]
    idy = transfer.run_probe(binary, ["identity", bdfs["a"], bdfs["b"]],
                             raw, f"{arm_id}-identity", timeout=120)
    if idy["returncode"] != 0:
        safety.record_arm_result(
            evidence_root, arm_id, "failed",
            {"reason": "identity probe failed",
             "exit": idy["returncode"], "stderr": idy["stderr"][:500]})
        raise RuntimeError(f"identity probe failed: {idy['stderr'][:300]}")

    journal = host.journal_scan()
    window = safety.collect_health_window(
        evidence_root, arm_id, journal["next_cursor"])

    seed_base = 0x23000000
    per_size: list[dict[str, Any]] = []
    failed: dict[str, Any] | None = None
    for size in sizes:
        name = f"{arm_id}-{size}"
        rep = transfer.run_probe(
            binary,
            ["transfer", mechanism, direction, bdf_src, bdf_dst,
             str(size), str(reps), str(warmups),
             str(seed_base + size)],
            raw, name, timeout=1800)
        parsed = None
        try:
            if rep["returncode"] == 0:
                parsed = transfer.parse_transfer_stdout(rep["stdout"])
                validated = transfer.validate_transfer_run(
                    parsed, mechanism=mechanism, direction=direction,
                    size=size, reps_expected=reps,
                    warmups_expected=warmups)
            else:
                validated = None
        except transfer.ProbeError as exc:
            validated = None
            rep = dict(rep)
            rep["validation_error"] = str(exc)
        row = {
            "size": size,
            "exit_code": rep["returncode"],
            "stdout_sha256": rep["stdout_sha256"],
            "stderr_sha256": rep["stderr_sha256"],
            "stdout_rel": f"raw/{name}.stdout",
            "validated": validated is not None,
        }
        if validated is not None:
            row["arm_record"] = validated["arm"]
            row["measured_reps"] = validated["measured_reps"]
            row["warmup_reps"] = validated["warmup_reps"]
        else:
            row["validation_error"] = rep.get("validation_error")
            row["stderr_excerpt"] = rep["stderr"][:500]
            failed = row
            break
        per_size.append(row)

    delta = safety.close_health_window(window)
    stop = safety.stop_condition_fired(
        delta, {"counts": delta["journal_fault_counts"]},
        0 if failed is None else (failed.get("exit_code") or 0))

    if failed is not None or stop is not None:
        safety.record_arm_result(
            evidence_root, arm_id, "failed",
            {"failed_size": (failed or {}).get("size"),
             "stop_condition": stop,
             "validation_error": (failed or {}).get("validation_error"),
             "stderr_excerpt": (failed or {}).get("stderr_excerpt")})
        result = {
            "arm": arm_id, "status": "FAILED",
            "stop_condition": stop,
            "failed_size_row": failed,
            "health_window": delta,
            "closure_digest": closure["closure_digest"],
            "producer_head": closure["producer_head"],
            "authorized_predecessors": auth["predecessors_passed"],
        }
        _durable(evidence_root / "arms" / f"{arm_id}.json", result)
        return result

    safety.record_arm_result(
        evidence_root, arm_id, "passed",
        {"sizes": [r["size"] for r in per_size],
         "reps": reps, "warmups": warmups,
         "mechanism": mechanism, "direction": direction})
    result = {
        "arm": arm_id, "status": "PASSED",
        "sizes": per_size,
        "health_window": delta,
        "closure_digest": closure["closure_digest"],
        "producer_head": closure["producer_head"],
        "authorized_predecessors": auth["predecessors_passed"],
    }
    _durable(evidence_root / "arms" / f"{arm_id}.json", result)
    return result


def run_controls_arm(*, evidence_root: Path, repo: Path, build_dir: Path,
                     dma: bool) -> dict[str, Any]:
    """Execute the matched controls: same-die, host-staged (both
    directions), fresh linkio on both dies, across the ladder sizes."""
    closure = rc.verify_closure(repo)
    mapping = json.loads(
        (evidence_root / "preflight" / "mapping" / "fresh-mapping.json")
        .read_text(encoding="utf-8"))
    arm_id = "controls-dma_buf" if dma else "controls"
    auth = safety.authorize_arm(evidence_root, arm_id)
    raw = evidence_root / "raw"
    binary, _source = transfer.compile_transfer(build_dir)
    bdfs = _arm_bdfs(mapping)
    a, b = bdfs["a"], bdfs["b"]

    journal = host.journal_scan()
    window = safety.collect_health_window(
        evidence_root, arm_id, journal["next_cursor"])

    seed_base = 0x23010000
    plan: list[tuple[str, list[str]]] = []
    for size in rc.LADDER_SIZES:
        plan.append((f"controls-samedie-a-{size}",
                     ["samedie", a, str(size), str(rc.CONTROL_REPS),
                      str(rc.CONTROL_WARMUPS),
                      str(seed_base + 0x100 + size)]))
        plan.append((f"controls-samedie-b-{size}",
                     ["samedie", b, str(size), str(rc.CONTROL_REPS),
                      str(rc.CONTROL_WARMUPS),
                      str(seed_base + 0x200 + size)]))
        plan.append((f"controls-hoststaged-ab-{size}",
                     ["hoststaged", a, b, str(size), str(rc.CONTROL_REPS),
                      str(rc.CONTROL_WARMUPS),
                      str(seed_base + 0x300 + size)]))
        plan.append((f"controls-hoststaged-ba-{size}",
                     ["hoststaged", b, a, str(size), str(rc.CONTROL_REPS),
                      str(rc.CONTROL_WARMUPS),
                      str(seed_base + 0x400 + size)]))
        plan.append((f"controls-linkio-a-{size}",
                     ["linkio", a, str(size), str(rc.CONTROL_REPS),
                      str(rc.CONTROL_WARMUPS),
                      str(seed_base + 0x500 + size)]))
        plan.append((f"controls-linkio-b-{size}",
                     ["linkio", b, str(size), str(rc.CONTROL_REPS),
                      str(rc.CONTROL_WARMUPS),
                      str(seed_base + 0x600 + size)]))

    rows: list[dict[str, Any]] = []
    failed: dict[str, Any] | None = None
    for name, argv in plan:
        rep = transfer.run_probe(binary, argv, raw, name, timeout=1800)
        ok = rep["returncode"] == 0 and \
            '"event":"summary"' in rep["stdout"] and \
            '"ok":true' in rep["stdout"].rsplit('"event":"summary"', 1)[-1]
        row = {"name": name, "argv_kind": argv[0],
               "exit_code": rep["returncode"],
               "stdout_sha256": rep["stdout_sha256"],
               "stdout_rel": f"raw/{name}.stdout",
               "summary_ok": ok}
        if not ok:
            row["stderr_excerpt"] = rep["stderr"][:500]
            failed = row
            break
        rows.append(row)

    delta = safety.close_health_window(window)
    stop = safety.stop_condition_fired(
        delta, {"counts": delta["journal_fault_counts"]},
        0 if failed is None else (failed.get("exit_code") or 0))

    if failed is not None or stop is not None:
        safety.record_arm_result(
            evidence_root, arm_id, "failed",
            {"failed_control": (failed or {}).get("name"),
             "stop_condition": stop})
        result = {"arm": arm_id, "status": "FAILED",
                  "stop_condition": stop, "failed_row": failed,
                  "health_window": delta,
                  "closure_digest": closure["closure_digest"],
                  "producer_head": closure["producer_head"],
                  "authorized_predecessors": auth["predecessors_passed"]}
        _durable(evidence_root / "arms" / f"{arm_id}.json", result)
        return result

    safety.record_arm_result(
        evidence_root, arm_id, "passed",
        {"controls": [r["name"] for r in rows]})
    result = {"arm": arm_id, "status": "PASSED", "controls": rows,
              "health_window": delta,
              "closure_digest": closure["closure_digest"],
              "producer_head": closure["producer_head"],
              "authorized_predecessors": auth["predecessors_passed"]}
    _durable(evidence_root / "arms" / f"{arm_id}.json", result)
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=str(ROOT))
    ap.add_argument("--evidence-root", required=True)
    ap.add_argument("--build-dir", default="/var/tmp/issue230-build")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("probe")
    p.add_argument("--mechanism", choices=rc.MECHANISMS, required=True)
    p.add_argument("--direction", choices=rc.DIRECTIONS, required=True)
    l = sub.add_parser("ladder")
    l.add_argument("--mechanism", choices=rc.MECHANISMS, required=True)
    l.add_argument("--direction", choices=rc.DIRECTIONS, required=True)
    sub.add_parser("controls")
    sub.add_parser("controls-dma")
    sub.add_parser("order-state")
    args = ap.parse_args()

    ev = Path(args.evidence_root)
    repo = Path(args.repo)
    build = Path(args.build_dir)

    if args.cmd == "probe":
        result = run_transfer_arm(
            evidence_root=ev, repo=repo, build_dir=build,
            mechanism=args.mechanism, direction=args.direction,
            sizes=(rc.PROBE_SIZE,), reps=1, warmups=0, probe=True)
    elif args.cmd == "ladder":
        result = run_transfer_arm(
            evidence_root=ev, repo=repo, build_dir=build,
            mechanism=args.mechanism, direction=args.direction,
            sizes=rc.LADDER_SIZES, reps=rc.REPS_PER_SIZE,
            warmups=rc.WARMUPS_PER_SIZE, probe=False)
    elif args.cmd == "controls":
        result = run_controls_arm(evidence_root=ev, repo=repo,
                                  build_dir=build, dma=False)
    elif args.cmd == "controls-dma":
        result = run_controls_arm(evidence_root=ev, repo=repo,
                                  build_dir=build, dma=True)
    else:
        doc = json.loads(safety.order_state_path(ev).read_text())
        print(json.dumps(doc, indent=1))
        return 0
    print(json.dumps({"arm": result["arm"], "status": result["status"],
                      "stop_condition": result.get("stop_condition")},
                     indent=2))
    return 0 if result["status"] == "PASSED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
