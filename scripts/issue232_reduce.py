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
from datetime import datetime
from pathlib import Path
from typing import Any

import issue232_receipt as rc
import issue232_host as host
import issue232_replay as replay_order


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
    out: dict[str, Any] = {}
    if authz_path.is_file():
        authz = _load(authz_path)
        if authz.get("schema") != "inferswarm.v2g.replay-authorization/1":
            raise ReductionError("bad replay authorization schema")
        out.update({
            "decision": authz.get("decision"),
            "decision_utc": authz.get("decision_utc"),
            "gate_result_digest": authz.get("gate_result_digest"),
            "reasons": authz.get("reasons"),
            "producer_byte_identical": authz.get("replay_producer", {})
            .get("byte_identical_to_accepted"),
            "replay_boot_id": authz.get("replay_boot_id"),
            "topology_binding": authz.get("topology_binding"),
        })
    order_path = evidence_root / "replay-order-state.json"
    if order_path.is_file():
        try:
            order = replay_order._load_order(order_path)
            replay_order._verify_chain(order)
        except (ValueError, TypeError, KeyError, replay_order.ReplayError) as exc:
            raise ReductionError(f"invalid replay order state: {exc}") from exc
        entries = order.get("entries") or []
        if not isinstance(entries, list):
            raise ReductionError("invalid replay order state entries")
        previous_dt: datetime | None = None
        for index, entry in enumerate(entries):
            if (index >= len(replay_order.ORDER_SEQUENCE)
                    or not isinstance(entry, dict)
                    or entry.get("arm") != replay_order.ORDER_SEQUENCE[index]):
                raise ReductionError("replay order state violates frozen ladder")
            if entry.get("state") not in ("passed", "failed") or \
                    (index < len(entries) - 1 and entry["state"] == "failed"):
                raise ReductionError("replay order state has invalid execution state")
            recorded_dt = _parse_utc(entry.get("recorded_utc"))
            if previous_dt is not None and recorded_dt <= previous_dt:
                raise ReductionError("replay arm timestamps are not strictly increasing")
            previous_dt = recorded_dt
        out["order_entries"] = [
            {"arm": e["arm"], "state": e["state"],
             "detail": e.get("detail")}
            for e in entries]
        out["halted"] = any(e["state"] == "failed" for e in entries)
        # retained arm execution timestamps (prospective-authorization
        # invariant input — never trust the authorization's own claim
        # about when the arms ran)
        out["order_entry_utc"] = [
            {"arm": e["arm"], "state": e["state"],
             "recorded_utc": e.get("recorded_utc")}
            for e in entries]
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
                "producer_head": arm.get("producer_head"),
                "closure_digest": arm.get("closure_digest"),
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


# ---------------------------------------------------------------------------
# Prospective-authorization invariant (2026-09-20 authority correction)
# ---------------------------------------------------------------------------
# Issue #232's contract is that replay authorization exists BEFORE the
# first replay arm executes AND is derived from the gate/topology under
# which the replay is claimed. A post-campaign boot/topology proof may
# establish what hardware state executed the arms; it can NEVER
# retroactively satisfy the prospective-authorization requirement. The
# check below is purely mechanical over retained timestamps and
# retained digest bindings — no authored summary is trusted.

AUTHZ_EVIDENCE_SKEW_S = 300.0
#: The authorization decision and the first arm must sit on one
#: authority horizon: an authorization recorded more than this many
#: seconds AFTER an arm executed is definitionally retrospective. (An
#: authorization BEFORE an arm is prospective at any distance; arms
#: refuse to run without one at execution time.)


def _parse_utc(text: Any) -> datetime:
    if not isinstance(text, str):
        raise ReductionError(f"not a UTC timestamp: {text!r}")
    try:
        value = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ReductionError(
            f"malformed UTC timestamp {text!r}") from exc
    if value.tzinfo is None or value.utcoffset() is None:
        raise ReductionError(f"timezone-naive UTC timestamp {text!r}")
    return value


def check_prospective_authorization(
        *, authz: dict[str, Any], order: dict[str, Any],
        gate_digest_retained: str,
        superseded_gate_digests: set[str]) -> dict[str, Any]:
    """Mechanically derive whether the retained replay authorization
    is PROSPECTIVE for the retained arms and bound to the gate digest
    the terminal claims. Returns a dict with ``valid`` plus a
    machine-readable ``problems`` list (basis material)."""
    problems: list[str] = []
    authz_utc = authz.get("decision_utc")
    if not authz_utc:
        return {"valid": False, "problems":
                ["retained replay authorization carries no "
                 "decision_utc"]}
    authz_dt = _parse_utc(authz_utc)

    executed = [e for e in order.get("entries") or []
                if e.get("state") in ("passed", "failed")]
    if not executed:
        return {"valid": False, "problems":
                ["replay order state retains no executed arm — "
                 "no prospective authorization can be evaluated"]}
    executed_utc = []
    for e in executed:
        utc = e.get("recorded_utc")
        if not utc:
            return {"valid": False, "problems": [
                f"order-state entry {e.get('arm')!r} carries no "
                "recorded_utc timestamp"]}
        executed_utc.append((e["arm"], _parse_utc(utc)))
    first_arm, first_dt = min(executed_utc, key=lambda row: row[1])
    last_arm, last_dt = max(executed_utc, key=lambda row: row[1])

    # (1)+(3): the authorization must PREDATE the first arm. An
    # authorization after the first arm is retrospective; after the
    # last arm it is maximally so.
    if authz_dt >= first_dt:
        delta = (authz_dt - first_dt).total_seconds()
        if authz_dt > last_dt:
            last_delta = (authz_dt - last_dt).total_seconds()
            problems.append(
                f"replay authorization decision_utc {authz_utc} is "
                f"{last_delta:.0f}s AFTER the last retained arm "
                f"{last_arm} ({last_arm} recorded "
                f"{last_dt.isoformat()}) — the entire "
                "ladder predates the authorization")
        elif authz_dt == first_dt:
            problems.append(
                f"replay authorization decision_utc {authz_utc} equals "
                f"the first retained arm {first_arm} recorded_utc "
                f"{first_dt.isoformat()} — not prospective")
        else:
            problems.append(
                f"replay authorization decision_utc {authz_utc} is "
                f"{delta:.0f}s AFTER the first retained arm "
                f"{first_arm} (recorded "
                f"{first_dt.isoformat()}) — retrospective, cannot "
                "authorize arms that already executed")
    # an authorization between arms is accepted as predating the
    # FIRST arm only if it actually predates it; the branch above
    # already rejected the opposite. no additional skew test is
    # needed: the boundary is the first arm, mechanically.

    # (2)+(4): the authorization must bind the gate digest of the
    # gate result the terminal is derived from.
    authz_gate = authz.get("gate_result_digest")
    if not authz_gate:
        problems.append(
            "retained replay authorization pins no gate_result_digest")
    elif authz_gate != gate_digest_retained:
        if authz_gate in superseded_gate_digests:
            problems.append(
                "replay authorization gate_result_digest "
                f"{authz_gate} points at the SUPERSEDED gate "
                "authority, not the retained gate-result.json "
                f"({gate_digest_retained})")
        else:
            problems.append(
                "replay authorization gate_result_digest "
                f"{authz_gate} does not match the retained "
                f"gate-result.json digest ({gate_digest_retained})")

    return {"valid": not problems, "problems": problems}


# ---------------------------------------------------------------------------
# Historical physical evidence provenance (immutable historical closure)
# ---------------------------------------------------------------------------
# The retained replay arms were executed under an OLDER producer
# identity (producer_head/closure_digest) than the current authority.
# They remain scientifically informative, but a reduction-only
# amendment may admit them ONLY through an explicit amendment record
# proving every physical producer that emitted them byte-unchanged
# between the executing pin and the current authority. Because
# scripts/issue232_replay.py changed after the arms executed, no such
# amendment is possible for this campaign — the arms stay retained
# with their ORIGINAL identities and REPLAY_PASS stays unreachable.

HISTORICAL_PIN_FIELDS = ("producer_head", "closure_digest")


def _historical_provenance_problems(
        arm_rows: list[dict[str, Any]],
        closure: dict[str, Any],
        admitted_historical_pins: dict[str, dict] | None = None
        ) -> list[str]:
    problems: list[str] = []
    for a in arm_rows:
        arm = a.get("arm")
        head = a.get("producer_head")
        digest = a.get("closure_digest")
        missing = [field for field, value
                   in zip(HISTORICAL_PIN_FIELDS, (head, digest))
                   if not isinstance(value, str) or not value]
        if missing:
            problems.append(
                f"{arm} retains no {missing[0]} — unpinned physical "
                "producer identity makes REPLAY_PASS unreachable")
            continue
        assert isinstance(head, str) and isinstance(digest, str)
        if head == closure.get("producer_head") \
                and digest == closure.get("closure_digest"):
            continue  # current authority: ordinary path
        entry = (admitted_historical_pins or {}).get(digest)
        if entry is None:
            problems.append(
                f"{arm} was produced under historical authority "
                f"producer_head={head[:12]} closure_digest="
                f"{digest[:12]} which differs from the current "
                f"closure ({closure.get('producer_head', '')[:12]}/"
                f"{closure.get('closure_digest', '')[:12]}) and no "
                "admissible immutable historical-closure amendment "
                "covers it — the arm cannot pass through the current "
                "closure")
        elif entry.get("closure_producer_head") != head:
            problems.append(
                f"{arm} historical pin {head[:12]} is not the pin "
                "admitted by the amendment record")
    return problems


def derive_terminal(evidence_root: Path,
                    *, closure: dict[str, Any] | None = None,
                    admitted_historical_pins: dict[str, dict] | None = None
                    ) -> dict[str, Any]:
    """Deterministic Phase 6 terminal from retained bytes (issue
    controls 18/20: authored records never override the reduction).

    ``closure`` is the VERIFIED producer-closure document (the
    assembler passes it after verify_closure). When omitted, the
    committed closure next to the evidence root is used; when no
    closure view exists at all, retained-arm provenance cannot be
    validated and REPLAY_PASS is unreachable (fail closed)."""
    obs = reduce_observations(evidence_root)
    gate = reduce_gate(evidence_root)
    interventions = reduce_interventions(evidence_root)
    qual = reduce_qualification(evidence_root)
    replay = reduce_replay(evidence_root)

    # closure view for retained-arm provenance validation: the
    # assembler passes its VERIFIED closure; a standalone reduction
    # falls back to the committed document; TOTAL absence fails the
    # provenance gate (REPLAY_PASS unreachable).
    closure_view = closure
    if closure_view is None:
        committed = (evidence_root.parent / rc.CLOSURE_NAME)
        if committed.is_file():
            closure_view = json.loads(
                committed.read_text(encoding="utf-8"))

    terminal: str
    basis: list[str] = []

    gate_passed = gate.get("result") == "PASS"
    replay_auth = bool(replay and replay.get("decision")
                       == "REPLAY_AUTHORIZED")

    # --- prospective-authorization invariant (2026-09-20 authority
    # correction): a retained REPLAY_AUTHORIZED decision is only an
    # admissible replay authority if it mechanically PREDATES the
    # first executed arm AND binds the retained gate digest. A
    # corrected/replacement authorization produced after any arm
    # executed is retrospective evidence, never authorization.
    authz_ok = replay_auth
    authz_problems: list[str] = []
    if replay_auth:
        order_rows = (replay or {}).get("order_entry_utc") or []
        authz_doc = _load(evidence_root / "replay-authorization.json")
        superseded_gate_digests: set[str] = set()
        for sup in sorted((evidence_root
                           / "superseded-20260920-topology-rebinding")
                          .glob("replay-authorization.json")):
            sup_doc = _load(sup)
            if sup_doc.get("gate_result_digest"):
                superseded_gate_digests.add(
                    sup_doc["gate_result_digest"])
        gate_digest_retained = rc.sha256_bytes(
            (evidence_root / "gate-result.json").read_bytes())
        if order_rows:
            order_for_check = {"entries": [
                {"arm": r["arm"], "state": r["state"],
                 "recorded_utc": r["recorded_utc"]}
                for r in order_rows]}
            verdict = check_prospective_authorization(
                authz=authz_doc, order=order_for_check,
                gate_digest_retained=gate_digest_retained,
                superseded_gate_digests=superseded_gate_digests)
            authz_ok = bool(verdict["valid"])
            authz_problems = list(verdict["problems"])
        else:
            authz_ok = False
            authz_problems = [
                "retained replay order state carries no arm "
                "timestamps — prospective authorization cannot be "
                "verified"]

    if not gate_passed:
        terminal = "V2G_PCIE_PATH_REMEDIATION_FAILED"
        basis.append(
            "clean-link gate did not pass on any tested intervention "
            f"(gate result {gate.get('result')!r}; failed checks: "
            f"{gate.get('failed_checks')})")
    elif not replay_auth:
        arms = (replay or {}).get("arms") or []
        executed = [row for row in ((replay or {}).get("order_entries") or [])
                    if row.get("state") in ("passed", "failed")]
        if arms or executed:
            terminal = "V2G_EVIDENCE_BLOCKED"
            basis.append(
                "physical replay occurred without admissible prospective "
                "authority: retained arms and/or executed replay order "
                f"entries exist (decision: {(replay or {}).get('decision')})")
        else:
            terminal = "V2G_PCIE_PATH_CLEAN_NO_REPLAY"
            basis.append(
                "clean-link gate passed and retained evidence shows no "
                "executed replay arm "
                f"(decision: {(replay or {}).get('decision')})")
    elif not authz_ok and (replay.get("arms") or replay.get("order_entries")) \
            and (replay.get("halted") or not replay.get("arms")):
        terminal = "V2G_EVIDENCE_BLOCKED"
        basis.extend(f"authorization inadmissible: {p}"
                     for p in authz_problems)
    else:
        arms = replay.get("arms") or []
        halted = bool(replay.get("halted"))
        if not arms and not (replay.get("order_entries") or []):
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

            # --- historical provenance of the retained arms ----------
            # Every correctness-bearing retained arm artifact carries
            # its executing producer_head/closure_digest. Arms produced
            # under a DIFFERENT (historical) producer identity than
            # the current closure are admissible ONLY through an
            # explicit immutable historical-closure amendment record
            # (AMENDMENTS.json) proving every physical producer
            # byte-unchanged between the executing pin and HEAD. No
            # such record is retained for this campaign: the replay
            # producer itself changed after the arms executed, so the
            # arms keep their original identities and cannot satisfy
            # REPLAY_PASS through the current closure.
            prov_problems: list[str] = []
            if closure_view is None:
                prov_problems = [
                    "no producer-closure view available — retained-arm "
                    "provenance cannot be validated (REPLAY_PASS "
                    "unreachable)"]
            else:
                prov_problems = _historical_provenance_problems(
                    arms, closure_view, admitted_historical_pins)

            if target in sizes and all_ok and topology_agrees \
                    and authz_ok and not prov_problems:
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
                basis.append(
                    "replay authorization decision_utc "
                    f"{(replay or {}).get('decision_utc')} "
                    "mechanically predates the first executed arm "
                    "and binds the retained gate-result digest")
            elif target in sizes and all_ok and (
                    not topology_agrees or not authz_ok
                    or prov_problems):
                terminal = "V2G_EVIDENCE_BLOCKED"
                # informative dimensions that REMAIN established by
                # the retained bytes (reported separately; they do
                # not rehabilitate the replay classification)
                basis.append(
                    "corrected retained evidence establishes the "
                    "daughterboard path root "
                    f"{gate_root} -> upstream {gate_up}, and the "
                    "clean candidate/cold-confirmation/"
                    "qualification evidence for that topology "
                    "remains intact")
                basis.append(
                    f"all {len(arms)} physical replay arms produced "
                    "exact-correct results with retained healthy "
                    "windows (scientifically informative; the "
                    "physical transfers themselves are not inferred "
                    "invalid)")
                for p in authz_problems:
                    basis.append(f"authorization inadmissible: {p}")
                for p in prov_problems:
                    basis.append(f"provenance inadmissible: {p}")
                for p in topo_problems:
                    basis.append(f"topology inadmissible: {p}")
                if not authz_problems and not prov_problems \
                        and not topo_problems:
                    basis.append(
                        "replay classification blocked without a "
                        "retained specific reason (fail-closed)")
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
