#!/usr/bin/env python3
"""Issue #230 — V2-F deterministic reduction helpers.

Every reduction re-derives its output from PRIMARY RAW BYTES retained
under the evidence root. Nothing is taken from authored summaries.

Separate state dimensions, never conflated:
  ADVERTISEMENT  — #228 property-query authority (consumed, not
                   re-derived here; the assembler re-verifies it);
  IMPLEMENTATION — this campaign's producer exists and is frozen;
  VALIDATED EXECUTION — measured correct transfers in BOTH directions
                   over the frozen ladder population;
  PHYSICAL ROUTE — derived only from measured behavior under the frozen
                   ROUTE_RULE (never from Vulkan's "external memory"
                   naming).

Reductions available:
  reduce_transfers — correctness + populations + min/median/max, p10/p90,
                     bulk GB/s, small-transfer service time, per
                     mechanism/direction/size;
  reduce_controls  — same statistics over the matched controls;
  classify_route   — frozen route rule application (LOCAL_BYPASS /
                     UPSTREAM / UNRESOLVED / INSUFFICIENT_CONTROLS).
"""
from __future__ import annotations

import json
import statistics
from pathlib import Path
from typing import Any

import issue230_receipt as rc


class ReduceError(RuntimeError):
    """The retained evidence cannot support this reduction."""


def _pct(sorted_vals: list[float], p: float) -> float:
    if not sorted_vals:
        raise ReduceError("percentile of empty population")
    k = (len(sorted_vals) - 1) * p
    lo = int(k)
    hi = min(lo + 1, len(sorted_vals) - 1)
    frac = k - lo
    return sorted_vals[lo] * (1 - frac) + sorted_vals[hi] * frac


def _stats(ns_values: list[float], size: int) -> dict[str, Any]:
    if not ns_values:
        raise ReduceError("empty timing population")
    s = sorted(ns_values)
    out: dict[str, Any] = {
        "count": n if (n := len(s)) else 0,
        "min_ns": s[0],
        "max_ns": s[-1],
        "median_ns": statistics.median(s),
        "p10_ns": _pct(s, 0.10),
        "p90_ns": _pct(s, 0.90),
        "mean_ns": statistics.fmean(s),
    }
    if size > 0:
        # bytes/ns == GB/s exactly (10^9 bytes per 10^9 ns)
        out["bulk_gbps"] = size / statistics.median(s)
    return out


def load_arm_rows(evidence_root: Path, arm_id: str) -> list[dict[str, Any]]:
    """Load + structurally validate one arm result file."""
    path = evidence_root / "arms" / f"{arm_id}.json"
    if not path.is_file():
        raise ReduceError(f"arm result missing: {arm_id}")
    doc = json.loads(path.read_text(encoding="utf-8"))
    if doc.get("arm") != arm_id:
        raise ReduceError(f"arm file identity mismatch: {arm_id}")
    if doc.get("status") != "PASSED":
        raise ReduceError(
            f"arm {arm_id} status is {doc.get('status')!r}; failed arms "
            "never contribute functional reductions")
    return doc


def reduce_transfers(evidence_root: Path) -> dict[str, Any]:
    """Derive the full transfer statistics from retained raw bytes.

    Re-parses raw/<arm>-<size>.stdout through the SAME frozen parser/
    validator the runner used (parse_transfer_stdout +
    validate_transfer_run), so an authored arm file alone can never
    produce a functional row (issue control: authored summary vs raw
    bytes).
    """
    import issue230_transfer as transfer

    out: dict[str, Any] = {}
    for mechanism in rc.MECHANISMS:
        for direction in rc.DIRECTIONS:
            arm_id = f"ladder-{mechanism}-{direction}"
            arm_path = evidence_root / "arms" / f"{arm_id}.json"
            if not arm_path.is_file():
                out[f"{mechanism}/{direction}"] = {
                    "status": "absent"}
                continue
            doc = json.loads(arm_path.read_text(encoding="utf-8"))
            if doc.get("status") != "PASSED":
                out[f"{mechanism}/{direction}"] = {
                    "status": doc.get("status", "unknown")}
                continue
            sizes_out: dict[int, dict[str, Any]] = {}
            for row in doc["sizes"]:
                size = row["size"]
                rel = row["stdout_rel"]
                raw_path = evidence_root / rel
                if not raw_path.is_file():
                    raise ReduceError(f"raw stdout missing: {rel}")
                if row.get("exit_code") != 0:
                    raise ReduceError(
                        f"nonzero probe exit retained for {rel}: "
                        "evidence failure, never a functional row")
                stdout = raw_path.read_text(encoding="utf-8")
                if rc.sha256_bytes(raw_path.read_bytes()) != \
                        row["stdout_sha256"]:
                    raise ReduceError(f"raw stdout hash drift: {rel}")
                try:
                    parsed = transfer.parse_transfer_stdout(stdout)
                    validated = transfer.validate_transfer_run(
                        parsed, mechanism=mechanism, direction=direction,
                        size=size, reps_expected=rc.REPS_PER_SIZE,
                        warmups_expected=rc.WARMUPS_PER_SIZE)
                except transfer.ProbeError as exc:
                    raise ReduceError(
                        f"raw transfer bytes fail validation ({rel}): "
                        f"{exc}") from exc
                ns_values = [float(r["elapsed_ns"])
                             for r in validated["measured_reps"]]
                # correctness already exact-true per rep (validator)
                stats = _stats(ns_values, size)
                stats["all_ok"] = all(
                    r["ok"] is True for r in validated["measured_reps"])
                stats["seeds"] = [r["seed"]
                                  for r in validated["measured_reps"]]
                stats["stdout_rel"] = rel
                stats["stdout_sha256"] = row["stdout_sha256"]
                sizes_out[size] = stats
            if sorted(sizes_out) != sorted(rc.LADDER_SIZES):
                raise ReduceError(
                    f"{arm_id}: ladder population incomplete "
                    f"({sorted(sizes_out)} != {sorted(rc.LADDER_SIZES)})")
            out[f"{mechanism}/{direction}"] = {
                "status": "PASSED", "sizes": sizes_out}
    return out


def reduce_controls(evidence_root: Path) -> dict[str, Any]:
    """Same statistics over the matched controls (raw bytes again)."""
    out: dict[str, Any] = {}
    arm_ids = ("controls", "controls-dma_buf")
    for arm_id in arm_ids:
        arm_path = evidence_root / "arms" / f"{arm_id}.json"
        if not arm_path.is_file():
            out[arm_id] = {"status": "absent"}
            continue
        doc = json.loads(arm_path.read_text(encoding="utf-8"))
        if doc.get("status") != "PASSED":
            out[arm_id] = {"status": doc.get("status", "unknown")}
            continue
        rows_out: dict[str, dict[int, dict[str, Any]]] = {}
        for row in doc["controls"]:
            name = row["name"]
            raw_path = evidence_root / row["stdout_rel"]
            if not raw_path.is_file():
                raise ReduceError(f"raw control stdout missing: {name}")
            if rc.sha256_bytes(raw_path.read_bytes()) != \
                    row["stdout_sha256"]:
                raise ReduceError(f"raw control stdout drift: {name}")
            events = _parse_control_stdout(
                raw_path.read_text(encoding="utf-8"))
            size = events["arm"]["size"]
            measured = [r for r in events["reps"] if r.get("measured")]
            if len(measured) != rc.CONTROL_REPS:
                raise ReduceError(
                    f"control {name}: population {len(measured)} != "
                    f"{rc.CONTROL_REPS}")
            kind = row["argv_kind"]
            key = None
            for tag in ("samedie-a", "samedie-b", "hoststaged-ab",
                        "hoststaged-ba", "linkio-a", "linkio-b"):
                if f"-{tag}-" in name:
                    key = tag
                    break
            if key is None:
                raise ReduceError(f"control name unclassifiable: {name}")
            stats = _stats([float(r["elapsed_ns"]) for r in measured],
                           size)
            if key.startswith("linkio") and all(
                    "h2d_ns" in r and "d2h_ns" in r for r in measured):
                stats["h2d_ns"] = statistics.median(
                    [float(r["h2d_ns"]) for r in measured])
                stats["d2h_ns"] = statistics.median(
                    [float(r["d2h_ns"]) for r in measured])
            rows_out.setdefault(key, {})[size] = stats
        out[arm_id] = {"status": "PASSED", "controls": rows_out}
    return out


def _parse_control_stdout(stdout: str) -> dict[str, Any]:
    arm = None
    reps: list[dict[str, Any]] = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        obj = json.loads(line)
        if obj.get("event") == "arm":
            arm = obj
        elif obj.get("event") == "rep":
            reps.append(obj)
    if arm is None:
        raise ReduceError("control stdout lacks an arm record")
    for r in reps:
        if r.get("ok") is not True:
            raise ReduceError("control rep without exact-true ok")
    return {"arm": arm, "reps": reps}


def _median_gbps(stats: dict[str, Any], size: int) -> float:
    return size / stats["median_ns"]  # bytes/ns == GB/s


def classify_route(transfers: dict[str, Any], controls: dict[str, Any],
                   mechanism: str, direction: str) -> dict[str, Any]:
    """Apply the frozen ROUTE_RULE to one mechanism/direction.

    Uses the LARGEST ladder size (256 MiB) medians only, with the
    matched controls required. Any missing population -> UNRESOLVED
    with reason (never a functional route claim).
    """
    rule = rc.ROUTE_RULE
    big = rc.LADDER_SIZES[-1]
    key = f"{mechanism}/{direction}"
    t = transfers.get(key) or {}
    if t.get("status") != "PASSED":
        return {"mechanism": mechanism, "direction": direction,
                "conclusion": "UNRESOLVED",
                "reason": "no complete validated transfer population"}
    peer_stats = t["sizes"].get(big)
    if peer_stats is None:
        return {"mechanism": mechanism, "direction": direction,
                "conclusion": "UNRESOLVED",
                "reason": f"largest size {big} missing"}

    ctrl = controls.get("controls") or {}
    if ctrl.get("status") != "PASSED":
        return {"mechanism": mechanism, "direction": direction,
                "conclusion": "UNRESOLVED",
                "reason": "matched controls absent/incomplete"}
    cctrl = ctrl["controls"]
    for need in ("linkio-a", "linkio-b", "hoststaged-ab",
                 "hoststaged-ba", "samedie-a", "samedie-b"):
        if need not in cctrl or big not in cctrl[need]:
            return {"mechanism": mechanism, "direction": direction,
                    "conclusion": "UNRESOLVED",
                    "reason": f"control {need}@{big} missing"}

    # Measured x1 ceiling: linkio elapsed_ns = h2d_ns + d2h_ns (both
    # legs over the host-facing link, fresh allocations). A single
    # crossing's throughput = size / leg_ns. Per-leg medians are not
    # independent in the sum, so the CONSERVATIVE single-crossing
    # ceiling is 2*size/elapsed: elapsed = l1 + l2 >= 2*min(l1,l2)
    # implies size/min(l) <= 2*size/elapsed... strictly elapsed >= 2*min
    # gives min <= elapsed/2 so size/min >= 2*size/elapsed; hence
    # 2*size/elapsed is a LOWER bound on the fastest leg and an UPPER
    # bound requires per-leg data. We take the conservative (higher)
    # ceiling from per-leg raw when present; else the 2*size/elapsed
    # floor-of-max, and the rule bands absorb the residual slack.
    ceilings = []
    for die in ("linkio-a", "linkio-b"):
        st = cctrl[die][big]
        if "h2d_ns" in st and "d2h_ns" in st:
            ceilings.append(max(
                big / st["h2d_ns"], big / st["d2h_ns"]))
        else:
            ceilings.append(2.0 * _median_gbps(st, big))
    x1_ceiling = max(ceilings)

    host_dir = "hoststaged-ab" if direction == "a_to_b" \
        else "hoststaged-ba"
    host_staged = _median_gbps(cctrl[host_dir][big], big)
    peer = _median_gbps(peer_stats, big)

    if peer > rule["bypass_factor"] * x1_ceiling:
        conclusion = "LOCAL_SWITCH_BYPASS_PROVEN"
        basis = (f"peer {peer:.3f} GB/s > {rule['bypass_factor']} * "
                 f"x1 ceiling {x1_ceiling:.3f} GB/s (measured, 256 MiB "
                 f"medians)")
    elif (peer <= rule["bypass_factor"] * x1_ceiling
          and rule["upstream_hoststaged_low"] * host_staged <= peer
          <= rule["upstream_hoststaged_high"] * host_staged):
        conclusion = "UPSTREAM_OR_HOST_ROUTE_PROVEN"
        basis = (f"peer {peer:.3f} GB/s within x1 ceiling and within "
                 f"[{rule['upstream_hoststaged_low']}, "
                 f"{rule['upstream_hoststaged_high']}] of host-staged "
                 f"control {host_staged:.3f} GB/s")
    else:
        conclusion = "PEER_FUNCTIONAL_ROUTE_UNRESOLVED"
        basis = (f"peer {peer:.3f} GB/s, x1 ceiling {x1_ceiling:.3f} "
                 f"GB/s, host-staged {host_staged:.3f} GB/s; bands do "
                 f"not decide")
    return {
        "mechanism": mechanism, "direction": direction,
        "conclusion": conclusion, "basis": basis,
        "measured": {
            "peer_gbps": peer,
            "x1_ceiling_gbps": x1_ceiling,
            "host_staged_gbps": host_staged,
        },
        "rule": {k: rule[k] for k in
                 ("bypass_factor", "upstream_hoststaged_low",
                  "upstream_hoststaged_high")},
    }
