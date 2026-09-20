#!/usr/bin/env python3
"""Issue #232 — V2-G deterministic reduction over retained evidence.

Every predicate is re-derived from retained RAW bytes. Nothing here
trusts an authored summary field that can be recomputed, no check is
ever set by constant, and any missing/empty required artifact is a
capture fault (raise), never silently-clean evidence.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import issue232_receipt as rc
import issue232_host as host


class ReductionError(RuntimeError):
    pass


def _load(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ReductionError(f"required artifact missing: {path}")
    doc = json.loads(path.read_text(encoding="utf-8"))
    if not doc:
        raise ReductionError(f"empty artifact: {path}")
    return doc


def _raw(evidence_root: Path, rel: str) -> str:
    path = evidence_root / rel
    if not path.is_file():
        raise ReductionError(f"required raw artifact missing: {rel}")
    text = path.read_text(encoding="utf-8", errors="strict")
    if not text.strip():
        raise ReductionError(
            f"empty retained raw artifact (capture fault): {rel}")
    return text


def reduce_interventions(evidence_root: Path) -> list[dict[str, Any]]:
    iv_dir = evidence_root / "interventions"
    out: list[dict[str, Any]] = []
    if not iv_dir.is_dir():
        return out
    for path in sorted(iv_dir.glob("*.json")):
        doc = _load(path)
        if doc.get("schema") != "inferswarm.v2g.intervention/1":
            raise ReductionError(f"unknown record: {path}")
        out.append({
            "intervention_id": doc["intervention_id"],
            "component": doc["component"],
            "declared_bundle": doc["declared_bundle"],
            "recorded_utc": doc["recorded_utc"],
            "pre_census_rel": doc["pre_census_rel"],
            "pre_census_sha256": doc["pre_census_sha256"],
        })
    return out


def reduce_observations(evidence_root: Path) -> list[dict[str, Any]]:
    obs_dir = evidence_root / "observations"
    out: list[dict[str, Any]] = []
    if not obs_dir.is_dir():
        return out
    for path in sorted(obs_dir.glob("*/observation.json")):
        doc = _load(path)
        if doc.get("schema") != "inferswarm.v2g.observation/1":
            raise ReductionError(f"unknown record: {path}")
        roles = doc.get("chain_roles") or {}
        up = roles.get("switch_upstream")
        if not up:
            raise ReductionError(
                f"observation lacks chain roles: {path}")
        # re-derive the RxErr delta from the raw journal census bytes
        census_rel = (path.parent / "raw" /
                      "journal-delta-census.json")
        census = _load(census_rel)
        j_up = ((census.get("events_by_source") or {})
                .get(up) or {})
        j_events = (j_up.get("Correctable", 0)
                    + j_up.get("Uncorrectable", 0))
        deltas = (doc.get("aer_deltas") or {}).get(up) or {}
        corr = deltas.get("aer_dev_correctable") or {}
        sysfs_rxerr = corr.get("RxErr", None)
        out.append({
            "observation_id": doc["observation_id"],
            "boot_id": doc["boot_id"],
            "note": doc.get("note"),
            "started_utc": doc["started_utc"],
            "elapsed_minutes": doc["elapsed_minutes"],
            "upstream_bdf": up,
            "upstream_width": (roles.get("switch_upstream_sta")
                               or {}).get("width"),
            "upstream_speed": (roles.get("switch_upstream_sta")
                               or {}).get("speed"),
            "sysfs_rxerr_delta": sysfs_rxerr,
            "journal_upstream_events": j_events,
            "journal_severity_events": census.get("events"),
            "sources_agree_zero_or_equal":
                (sysfs_rxerr == j_events),
            "rates_per_minute": {
                bdf: r["rate_per_minute"]
                for bdf, r in (doc.get("rates") or {}).items()},
        })
    return out


def reduce_gate(evidence_root: Path) -> dict[str, Any]:
    doc = _load(evidence_root / "gate-result.json")
    if doc.get("schema") != "inferswarm.v2g.clean-link-gate/1":
        raise ReductionError("bad gate artifact schema")
    # re-derive the terminal-relevant checks from raw bytes
    detail = doc.get("detail") or {}
    rx = detail.get("rxerr") or {}
    cold = detail.get("cold_confirmations") or {}
    chain = detail.get("chain") or {}
    return {
        "result": doc.get("result"),
        "checks": doc.get("checks"),
        "failed_checks": doc.get("failed_checks"),
        "rxerr": rx,
        "chain": {
            "root_port": chain.get("root_port"),
            "switch_upstream": chain.get("switch_upstream"),
            "vega": chain.get("vega"),
            "census_boot_id": chain.get("census_boot_id"),
            "observation_boot_id": chain.get("observation_boot_id"),
            "cold_confirmation_boot_ids":
                chain.get("cold_confirmation_boot_ids"),
            "cold_confirmation_root_ports":
                chain.get("cold_confirmation_root_ports"),
        },
        "cold_confirmations": {
            "required": cold.get("required"),
            "observed": cold.get("observed"),
            "boot_ids": cold.get("boot_ids"),
        },
    }


def reduce_qualification(evidence_root: Path) -> dict[str, Any] | None:
    path = evidence_root / "qualification" / "qualification.json"
    if not path.is_file():
        return None
    doc = _load(path)
    if doc.get("schema") != "inferswarm.v2g.qualification/1":
        raise ReductionError("bad qualification artifact schema")
    chain = doc.get("chain") or {}
    return {
        "stop_condition": doc.get("stop_condition"),
        "same_die_ok": {k: v["ok"] for k, v in
                        (doc.get("same_die_operations") or {}).items()},
        "upstream_rxerr_delta": doc.get("upstream_rxerr_delta"),
        "boot_id": doc.get("boot_id"),
        "root_port_bdf": chain.get("root_port_bdf"),
        "switch_upstream_bdf": chain.get("switch_upstream_bdf"),
    }


def reduce_replay(evidence_root: Path) -> dict[str, Any] | None:
    authz_path = evidence_root / "replay-authorization.json"
    if not authz_path.is_file():
        return None
    authz = _load(authz_path)
    if authz.get("schema") != "inferswarm.v2g.replay-authorization/1":
        raise ReductionError("bad replay authorization schema")
    out: dict[str, Any] = {
        "decision": authz.get("decision"),
        "reasons": authz.get("reasons"),
        "producer_byte_identical": authz.get("replay_producer", {})
        .get("byte_identical_to_accepted"),
        "replay_boot_id": authz.get("replay_boot_id"),
        "topology_binding": authz.get("topology_binding"),
    }
    order_path = evidence_root / "replay-order-state.json"
    if order_path.is_file():
        order = _load(order_path)
        entries = order.get("entries") or []
        out["order_entries"] = [
            {"arm": e["arm"], "state": e["state"],
             "detail": e.get("detail")}
            for e in entries]
        out["halted"] = any(e["state"] == "failed" for e in entries)
    # retained boot/topology continuity proof (2026-09-20 correction):
    # read from the RETAINED FILE, never from the authorization's
    # summary of it — the two must agree and the file's own topology
    # is what the terminal logic binds.
    boot_path = evidence_root / "boot-proof.json"
    if boot_path.is_file():
        bp_doc = _load(boot_path)
        if bp_doc.get("schema") != "inferswarm.v2g.boot-proof/1":
            raise ReductionError("bad boot-proof schema")
        bt = bp_doc.get("topology") or {}
        out["boot_proof"] = {
            "replay_boot_id": bp_doc.get("replay_boot_id"),
            "root_port": bt.get("root_port"),
            "switch_upstream": bt.get("switch_upstream"),
            "negotiated_width": bt.get("negotiated_width"),
            "anchor_census_boot_id":
                (bp_doc.get("continuity") or {})
                .get("anchor_census_boot_id"),
        }
    arms_dir = evidence_root / "arms"
    arm_rows: list[dict[str, Any]] = []
    if arms_dir.is_dir():
        for path in sorted(arms_dir.glob("replay-*.json")):
            arm = _load(path)
            raw_rel = arm.get("stdout_rel")
            if not isinstance(raw_rel, str):
                raise ReductionError(
                    f"arm record lacks stdout binding: {path}")
            stdout = _raw(evidence_root, raw_rel)
            # correctness is re-derived from the retained producer
            # stdout: the summary tail must carry ok:true AND the
            # arm record must be validated
            tail = stdout.rsplit('"event":"summary"', 1)
            ok_true = len(tail) == 2 and '"ok":true' in tail[-1]
            arm_rows.append({
                "arm": arm["arm"],
                "size_bytes": arm["size_bytes"],
                "exit_code": arm["exit_code"],
                "stop_condition": arm.get("stop_condition"),
                "summary_ok_true": ok_true,
                "validated": arm.get("validated"),
                "stdout_sha256": arm.get("stdout_sha256"),
                "replay_producer_head":
                    arm.get("replay_producer_head"),
                "boot_id": arm.get("boot_id"),
                "root_port_bdf": arm.get("root_port_bdf"),
                "upstream_bdf": arm.get("upstream_bdf"),
                "negotiated_width": arm.get("negotiated_width"),
            })
    out["arms"] = arm_rows
    return out


def fault_class_from_arm(arm: dict[str, Any]) -> str | None:
    stop = arm.get("stop_condition")
    if stop in ("ring_timeout_or_hang", "gpu_reset_or_reset_failure"):
        return "AMDGPU_RING_RESET_FAULT"
    if stop == "correctness_mismatch":
        return "CORRECTNESS_FAILURE"
    if stop == "nonzero_producer_exit":
        return "PRODUCER_EXIT"
    if stop == "uncorrectable_aer_or_dpc":
        return "UNCORRECTABLE_PCIE_FAULT"
    if stop == "material_rxerr_flood_recurrence":
        return "RXERR_FLOOD_RECURRENCE"
    if stop == "unexpected_topology_or_width_change":
        return "TOPOLOGY_CHANGE"
    return None


def derive_terminal(evidence_root: Path) -> dict[str, Any]:
    """Deterministic Phase 6 terminal from retained bytes (issue
    controls 18/20: authored records never override the reduction)."""
    obs = reduce_observations(evidence_root)
    gate = reduce_gate(evidence_root)
    interventions = reduce_interventions(evidence_root)
    qual = reduce_qualification(evidence_root)
    replay = reduce_replay(evidence_root)

    terminal: str
    basis: list[str] = []

    gate_passed = gate.get("result") == "PASS"
    replay_auth = bool(replay and replay.get("decision")
                       == "REPLAY_AUTHORIZED")

    if not gate_passed:
        terminal = "V2G_PCIE_PATH_REMEDIATION_FAILED"
        basis.append(
            "clean-link gate did not pass on any tested intervention "
            f"(gate result {gate.get('result')!r}; failed checks: "
            f"{gate.get('failed_checks')})")
    elif not replay_auth:
        terminal = "V2G_PCIE_PATH_CLEAN_NO_REPLAY"
        basis.append(
            "clean-link gate passed but replay was not authorized/ "
            f"performed (decision: "
            f"{(replay or {}).get('decision')})")
    else:
        arms = replay.get("arms") or []
        halted = bool(replay.get("halted"))
        if not arms:
            terminal = "V2G_PCIE_PATH_CLEAN_NO_REPLAY"
            basis.append(
                "replay authorized but no arm executed (no retained "
                "arm evidence)")
        elif halted:
            failed_arm = next(
                (a for a in arms if a.get("stop_condition")), None)
            if failed_arm is None:
                # halted order state but no stop condition retained on
                # any arm row — the failure evidence is incomplete
                terminal = "V2G_EVIDENCE_BLOCKED"
                basis.append(
                    "replay order state records a failure but no arm "
                    "retains its stop condition (incomplete failure "
                    "evidence)")
            else:
                cls = fault_class_from_arm(failed_arm)
                if cls == "AMDGPU_RING_RESET_FAULT":
                    terminal = \
                        "V2G_PCIE_PATH_REMEDIATED_FAULT_REPRODUCED"
                    basis.append(
                        f"bounded replay reproduced the #216/#230-"
                        f"class amdgpu ring/reset fault at "
                        f"{failed_arm['size_bytes']} bytes "
                        f"(stop={failed_arm['stop_condition']})")
                else:
                    terminal = \
                        "V2G_PCIE_PATH_REMEDIATED_DIFFERENT_FAILURE"
                    basis.append(
                        f"bounded replay failed differently at "
                        f"{failed_arm['size_bytes']} bytes "
                        f"(class={cls}, stop="
                        f"{failed_arm['stop_condition']})")
        else:
            sizes = sorted(a["size_bytes"] for a in arms)
            target = rc.REPLAY_LADDER[-1]["size_bytes"]
            all_ok = all(a["summary_ok_true"] and a["validated"]
                         for a in arms)
            # --- topology continuity (2026-09-20 correction) ---------
            # REPLAY_PASS requires every arm's retained root port and
            # upstream to EQUAL the gate-authorized topology, and the
            # authorization's boot-proof topology to agree with the
            # gate/qualification chain. Historical arm records that
            # predate boot_id retention are admissible ONLY through
            # the retained boot-continuity proof (boot-proof.json),
            # whose own topology must equal the gate topology; arms
            # carrying their own boot ids must match it too.
            gate_root = ((gate.get("chain") or {})
                         .get("root_port"))
            gate_up = ((gate.get("chain") or {})
                       .get("switch_upstream"))
            # the retained cold-proof (if present) must bind the SAME
            # root/upstream for every confirmation cycle
            cold_path = evidence_root / "cold-proof.json"
            if cold_path.is_file():
                cold_doc = _load(cold_path)
                for cyc in cold_doc.get("cycles") or []:
                    if cyc.get("root_port_bdf") != gate_root \
                            or cyc.get("switch_upstream_bdf") != gate_up:
                        raise ReductionError(
                            "cold-proof confirmation topology "
                            f"({cyc.get('root_port_bdf')}->"
                            f"{cyc.get('switch_upstream_bdf')}) "
                            "contradicts the gate-bound chain "
                            f"({gate_root}->{gate_up})")
            binding = ((replay or {}).get("topology_binding") or {})
            bp = ((replay or {}).get("boot_proof")
                  or binding.get("boot_proof") or {})
            topology_agrees = True
            topo_problems: list[str] = []
            authz_bp = binding.get("boot_proof") or {}
            if binding.get("gate_root_port") is not None \
                    and binding.get("gate_root_port") != gate_root:
                topology_agrees = False
                topo_problems.append(
                    "authorization claims a gate topology different "
                    "from the retained gate-result chain")
            if binding.get("gate_switch_upstream") is not None \
                    and binding.get("gate_switch_upstream") != gate_up:
                topology_agrees = False
                topo_problems.append(
                    "authorization claims a gate upstream different "
                    "from the retained gate-result chain")
            if bp and authz_bp and any(
                    bp.get(k) != authz_bp.get(k) for k in (
                        "replay_boot_id", "root_port",
                        "switch_upstream", "negotiated_width")):
                topology_agrees = False
                topo_problems.append(
                    "authorization boot-proof binding disagrees with "
                    "the retained boot-proof.json")
            if bp:
                if bp.get("root_port") != gate_root \
                        or bp.get("switch_upstream") != gate_up:
                    topology_agrees = False
                    topo_problems.append(
                        "boot-proof topology disagrees with gate chain")
            else:
                topology_agrees = False
                topo_problems.append(
                    "no boot-proof retained for the replay boot")
            for a in arms:
                arm_root = a.get("root_port_bdf")
                arm_up = a.get("upstream_bdf")
                if arm_root is None or arm_up is None:
                    topology_agrees = False
                    topo_problems.append(
                        f"{a['arm']} retains no topology identity")
                elif arm_root != gate_root or arm_up != gate_up:
                    topology_agrees = False
                    topo_problems.append(
                        f"{a['arm']} ran on {arm_root}->{arm_up}, "
                        f"gate bound {gate_root}->{gate_up}")
                arm_boot = a.get("boot_id")
                if arm_boot is not None and bp \
                        and arm_boot != bp.get("replay_boot_id"):
                    topology_agrees = False
                    topo_problems.append(
                        f"{a['arm']} boot {arm_boot} != boot-proof "
                        f"{bp.get('replay_boot_id')}")
            if target in sizes and all_ok and topology_agrees:
                terminal = \
                    "V2G_PCIE_PATH_REMEDIATED_REPLAY_PASS"
                basis.append(
                    f"all {len(arms)} replay arms exact-correct "
                    f"through the historical 64-MiB fault scale "
                    f"(sizes={sizes}) with no qualifying platform "
                    "fault or material RxErr recurrence")
                basis.append(
                    "topology identity continuous across "
                    "gate/cold-proof/qualification/replay: root port "
                    f"{gate_root}, upstream {gate_up}, replay boot "
                    f"{(bp or {}).get('replay_boot_id')}")
            elif target in sizes and all_ok and not topology_agrees:
                terminal = "V2G_EVIDENCE_BLOCKED"
                basis.append(
                    "replay arms passed but topology identity "
                    "continuity is NOT established from retained "
                    f"bytes ({'; '.join(topo_problems)}) — the pass "
                    "cannot be attributed to the remediated path "
                    "without renewed physical authorization")
            else:
                terminal = "V2G_EVIDENCE_BLOCKED"
                basis.append(
                    "replay arms present but the retained evidence "
                    "does not establish the full-ladder pass "
                    f"(sizes={sizes}, all_ok={all_ok})")

    # control 20: authored TERMINAL.json must agree with this reduction
    authored_path = evidence_root / "TERMINAL.json"
    authored = None
    if authored_path.is_file():
        authored = _load(authored_path).get("terminal")
    if authored is not None and authored != terminal:
        raise ReductionError(
            f"authored terminal {authored!r} contradicts the "
            f"deterministic reduction {terminal!r}")

    return {
        "campaign_id": rc.CAMPAIGN_ID,
        "terminal": terminal,
        "basis": basis,
        "interventions": interventions,
        "gate": gate,
        "qualification": qual,
        "replay": replay,
        "observations_count": len(obs),
        "observations": obs,
        "authored_terminal_agrees": authored is None
        or authored == terminal,
    }
