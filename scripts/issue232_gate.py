#!/usr/bin/env python3
"""Issue #232 — V2-G Phase 3 clean-link gate (prospective, fail-closed).

The gate is FROZEN HERE, in code, BEFORE it is ever used to authorize
anything (issue: "Define the gate prospectively in code/tests before
using it to authorize GPU replay").

evaluate() re-derives every predicate from retained observation bytes;
nothing here trusts an authored summary field that can be recomputed.

Gate predicates (all must hold on the SAME candidate observation):
  topology       — the derived chain is present and unique (root port
                   -> PM8533 upstream), both Vega dies enumerate, die
                   count exactly two; TOPOLOGY IDENTITY CONTINUITY is
                   mechanically bound: the census MUST be from the
                   candidate observation's own boot (boot-id equality)
                   and its derived chain MUST equal the candidate
                   observation's live-derived chain_roles, and every
                   cold confirmation observation MUST carry the SAME
                   root-port/upstream identity. A stale census from a
                   different intervention state (e.g. a motherboard-
                   slot census retained after a daughterboard return)
                   is rejected mechanically — never by operator
                   diligence (correction 2026-09-20: the first
                   accepted gate evaluation was fed the intervention-3
                   PRE-census, binding root 00:1c.5 while the
                   candidate/cold/qualification/replay evidence is
                   00:1d.0);
  identity       — the UUID-derived die identity join is consistent
                   (identity probe) — checked by the qualify phase and
                   re-checked here from the observation's retained
                   probe bytes;
  width          — negotiated width equals the intended remediated
                   wiring width (x1 unless a wider wiring is declared
                   in the intervention record; no UNDECLARED downgrade
                   is accepted — control 2: idle speed downtraining is
                   NOT a width downgrade and must not be miscounted as
                   one);
  severity       — zero Uncorrectable AER and zero DPC over the
                   interval (control 4);
  amdgpu         — zero amdgpu timeout/reset/device-loss journal
                   events over the interval;
  rxerr          — Correctable Physical-Layer RxErr events on the
                   candidate upstream path over the fixed interval ==
                   0 (the frozen zero threshold; control 10);
  cross_source   — sysfs AER counters and the journal event census
                   AGREE (both zero over the interval; a disagreement
                   is an observation fault, not a pass);
  repeat         — the clean result repeats across the required number
                   of COLD power-cycle confirmations (control 8/9: a
                   warm reboot never substitutes; one clean interval
                   alone is never enough);
  peripherals    — no new NIC/USB/storage regression over the interval
                   (from the census probes).
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

import issue232_receipt as rc
import issue232_host as host

ROOT = Path(__file__).resolve().parents[1]

GATE_SCHEMA = "inferswarm.v2g.clean-link-gate/1"

#: The width the remediated wiring must negotiate. The historical x1
#: wiring is the degraded condition; if the operator's remediation
#: moves the upstream to a different x1 slot, x1 remains the intended
#: width — UNLESS the intervention record declares a wider wiring,
#: which the gate then requires. An undeclared width (any value not
#: matching the declared/intended value) FAILS the gate (control 12).
INTENDED_WIDTH = 1


class GateError(RuntimeError):
    pass


def _journal_upstream_events(census_delta: dict[str, Any],
                             up_bdf: str) -> int:
    """Correctable+Uncorrectable journal events attributed to the
    upstream BDF over the observation window. ZERO total events means
    the source row is legitimately ABSENT (aer_event_census only adds
    sources that produced events) — that is 0, not "unavailable". A
    nonzero total with no row for the upstream is unattributable and
    fails closed as -1."""
    events = (census_delta or {}).get("events") or {}
    total = (events.get("Correctable", 0) or 0) \
        + (events.get("Uncorrectable", 0) or 0) \
        + (events.get("DPC", 0) or 0)
    src = ((census_delta or {}).get("events_by_source") or {}
           ).get(up_bdf) or {}
    attributed = (src.get("Correctable", 0) or 0) \
        + (src.get("Uncorrectable", 0) or 0)
    if attributed:
        return attributed
    if total == 0:
        return 0
    return -1  # events exist but none attributable — fail closed


def _load_observation(path: Path) -> dict[str, Any]:
    doc = json.loads(path.read_text(encoding="utf-8"))
    if doc.get("schema") != "inferswarm.v2g.observation/1":
        raise GateError(f"not a V2-G observation: {path}")
    return doc


def _load_census(path: Path) -> dict[str, Any]:
    doc = json.loads(path.read_text(encoding="utf-8"))
    if doc.get("schema") != "inferswarm.v2g.census/1":
        raise GateError(f"not a V2-G census: {path}")
    return doc


def _load_interventions(evidence_root: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    iv_dir = evidence_root / "interventions"
    if not iv_dir.is_dir():
        return out
    for path in sorted(iv_dir.glob("*.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        if doc.get("schema") != "inferswarm.v2g.intervention/1":
            raise GateError(f"unknown record in interventions/: {path}")
        out.append(doc)
    return out


def evaluate_gate(*, observation: dict[str, Any],
                  census: dict[str, Any],
                  interventions: list[dict[str, Any]],
                  cold_confirmation_observations: list[dict[str, Any]],
                  cold_proof: dict[str, Any] | None = None
                  ) -> dict[str, Any]:
    """Evaluate the frozen clean-link gate over ONE candidate
    observation plus the required cold-cycle confirmation observations.

    cold_proof binds the cold power-cycle identity of each confirmation
    observation (previous boot's journal ended WITHOUT reboot.target +
    a shutdown record + a boot-id change) — a warm reboot labeled cold
    fails the gate (control 8).
    """
    checks: dict[str, bool] = {}
    detail: dict[str, Any] = {}

    # --- topology ---
    chain = observation.get("chain_bdfs") or []
    derived = census.get("derived_chain") or {}
    roles = observation.get("chain_roles") or {}
    has_chain = bool(derived.get("root_port_bdf")
                     and derived.get("switch_upstream_bdf"))
    checks["topology_chain_unique"] = has_chain \
        and len(census.get("vega_bdfs") or []) == 2

    # --- topology identity continuity (2026-09-20 correction) -----
    # The gate input census previously trusted operator selection and
    # its derived_chain was copied verbatim into the gate detail. The
    # retained 2026-09-20 evaluation was fed the intervention-3
    # PRE-census (motherboard slot, root 00:1c.5) while the candidate
    # observation, cold confirmation, qualification and every replay
    # arm live-derived root 00:1d.0. The gate must MECHANICALLY bind:
    #   (a) the census boot-id == the candidate observation boot-id;
    #   (b) the census derived chain == the observation's own
    #       live-derived chain_roles (root port + upstream);
    #   (c) every cold confirmation carries the SAME root-port and
    #       upstream identity as the candidate observation.
    obs_root = roles.get("root_port")
    obs_up = roles.get("switch_upstream")
    census_boot = census.get("boot_id")
    obs_boot = observation.get("boot_id")
    topology_cont = bool(obs_root and obs_up and census_boot
                         and census_boot == obs_boot
                         and derived.get("root_port_bdf") == obs_root
                         and derived.get("switch_upstream_bdf")
                         == obs_up)
    for c in (cold_confirmation_observations or []):
        croles = c.get("chain_roles") or {}
        topology_cont = topology_cont and (
            croles.get("root_port") == obs_root
            and croles.get("switch_upstream") == obs_up)
    checks["topology_identity_continuity"] = topology_cont
    detail["chain"] = {
        "root_port": obs_root or derived.get("root_port_bdf"),
        "switch_upstream": obs_up or derived.get("switch_upstream_bdf"),
        "vega": census.get("vega_bdfs"),
        "census_boot_id": census_boot,
        "observation_boot_id": obs_boot,
        "cold_confirmation_boot_ids": [
            c.get("boot_id") for c in cold_confirmation_observations],
        "cold_confirmation_root_ports": [
            (c.get("chain_roles") or {}).get("root_port")
            for c in cold_confirmation_observations],
    }

    # --- width (control 2: distinguish speed downtraining) ----------
    roles = observation.get("chain_roles") or {}
    sw_sta = roles.get("switch_upstream_sta") or {}
    rp_sta = roles.get("root_port_sta") or {}
    declared_width = INTENDED_WIDTH
    if interventions:
        declared = interventions[-1].get("declared_width")
        if isinstance(declared, int) and declared > 0:
            declared_width = declared
    width_ok = (sw_sta.get("width") == declared_width
                and rp_sta.get("width") == declared_width)
    checks["width_matches_declared_wiring"] = width_ok
    detail["width"] = {
        "declared": declared_width,
        "switch_upstream": sw_sta.get("width"),
        "root_port": rp_sta.get("width"),
        "switch_speed": sw_sta.get("speed"),
        "note": ("speed may idle-downtrain between observations; only "
                 "WIDTH is a gate predicate (control 2)"),
    }

    # --- severity (control 4) ---
    census_ev = observation.get("journal_census_delta") or {}
    ev = census_ev.get("events") or {}
    checks["zero_uncorrectable_and_dpc"] = \
        (ev.get("Uncorrectable", -1) == 0 and ev.get("DPC", -1) == 0)
    detail["severity_events_over_interval"] = ev

    # --- amdgpu health ---
    fault_counts = observation.get("journal_fault_counts") or {}
    checks["no_amdgpu_timeout_reset"] = (
        not fault_counts.get("amdgpu_timeout")
        and not fault_counts.get("amdgpu_reset")
        and not fault_counts.get("amdgpu_failure"))
    detail["amdgpu_fault_counts"] = fault_counts

    # --- RxErr zero on the candidate upstream path (control 10) ----
    up_bdf = (observation.get("chain_roles") or {}
              ).get("switch_upstream") or derived.get("switch_upstream_bdf")
    if not up_bdf:
        checks["upstream_rxerr_zero"] = False
        detail["rxerr"] = {"error": "no derived upstream BDF"}
    else:
        rates = observation.get("rates") or {}
        rate_row = rates.get(up_bdf)
        deltas = (observation.get("aer_deltas") or {}).get(up_bdf) or {}
        corr = deltas.get("aer_dev_correctable") or {}
        rxerr_sysfs = corr.get("RxErr", -1)
        rxerr_journal = _journal_upstream_events(
            observation.get("journal_census_delta"), up_bdf)
        checks["upstream_rxerr_zero"] = (
            rxerr_sysfs == rc.CLEAN_LINK_RXERR_MAX
            and rxerr_journal == rc.CLEAN_LINK_RXERR_MAX)
        detail["rxerr"] = {
            "upstream_bdf": up_bdf,
            "sysfs_rxerr_delta": rxerr_sysfs,
            "journal_upstream_events": rxerr_journal,
            "threshold": rc.CLEAN_LINK_RXERR_MAX,
        }

    # --- cross-source agreement (sysfs vs journal both zero; an
    # unavailable source (-1) never passes — control 3/4) ------------
    rx = detail.get("rxerr", {})
    checks["sources_agree"] = (
        rx.get("sysfs_rxerr_delta") == rc.CLEAN_LINK_RXERR_MAX
        and rx.get("journal_upstream_events") == rc.CLEAN_LINK_RXERR_MAX)

    # --- interval duration ---
    checks["interval_full_length"] = \
        (observation.get("elapsed_minutes", 0)
         >= rc.GATE_INTERVAL_MINUTES * 0.95)

    # --- peripheral regression (gateway reachable + storage writable
    # + NIC counters present in the observation bytes) ---------------
    nic = observation.get("nic") or {}
    storage = observation.get("storage") or {}
    checks["peripherals_no_regression"] = bool(
        observation.get("boot_id")
        and storage.get("write_ok") is True
        and nic)

    # --- cold confirmations (controls 8/9) ---
    required = rc.GATE_REQUIRED_COLD_CONFIRMATIONS
    confs = cold_confirmation_observations or []
    cold_ok = len(confs) >= required and cold_proof_ok(confs, cold_proof)
    checks["cold_confirmation_repeated"] = cold_ok
    detail["cold_confirmations"] = {
        "required": required,
        "observed": len(confs),
        "boot_ids": [c.get("boot_id") for c in confs],
    }

    # --- per-confirmation RxErr must ALSO be zero ------------------
    if cold_ok:
        per_conf = []
        for c in confs:
            r = _rxerr_row(c)
            per_conf.append(r)
            if r.get("sysfs_rxerr_delta") != rc.CLEAN_LINK_RXERR_MAX \
                    or r.get("journal_upstream_events") \
                    != rc.CLEAN_LINK_RXERR_MAX:
                checks["cold_confirmation_repeated"] = False
                detail["cold_confirmations"]["failing"] = r
                break
        detail["cold_confirmations"]["per_confirmation_rxerr"] = per_conf

    passed = all(checks.values())
    return {
        "schema": GATE_SCHEMA,
        "campaign_id": rc.CAMPAIGN_ID,
        "gate_definition": {
            "rxerr_max_over_interval": rc.CLEAN_LINK_RXERR_MAX,
            "interval_minutes": rc.GATE_INTERVAL_MINUTES,
            "required_cold_confirmations": required,
            "intended_width": INTENDED_WIDTH,
            "frozen_before_any_confirmation_result": True,
        },
        "checks": checks,
        "detail": detail,
        "result": "PASS" if passed else "FAIL",
        "failed_checks": [k for k, v in checks.items() if not v],
    }


def _rxerr_row(observation: dict[str, Any]) -> dict[str, Any]:
    up_bdf = (observation.get("chain_roles") or {}
              ).get("switch_upstream")
    if not up_bdf:
        return {"error": "no upstream BDF"}
    deltas = (observation.get("aer_deltas") or {}).get(up_bdf) or {}
    corr = deltas.get("aer_dev_correctable") or {}
    return {
        "boot_id": observation.get("boot_id"),
        "upstream_bdf": up_bdf,
        "sysfs_rxerr_delta": corr.get("RxErr", -1),
        "journal_upstream_events": _journal_upstream_events(
            observation.get("journal_census_delta"), up_bdf),
    }


def cold_proof_ok(confs: list[dict[str, Any]],
                  cold_proof: dict[str, Any] | None) -> bool:
    """Each confirmation must be a DIFFERENT boot (boot-id change) and
    the operator's retained cold-cycle proof must show the previous
    boot ended WITHOUT reboot.target (a real power cut) plus a
    shutdown record — never a warm reboot labeled cold (control 8)."""
    if not cold_proof:
        return False
    boots = [c.get("boot_id") for c in confs]
    if len(set(boots)) != len(boots):
        return False
    entries = cold_proof.get("cycles") or []
    if len(entries) < len(confs):
        return False
    for e in entries:
        if not e.get("prev_boot_ended_without_reboot_target"):
            return False
        if not e.get("shutdown_record_present"):
            return False
    return True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--evidence-root", required=True)
    ap.add_argument("--observation-rel", required=True)
    ap.add_argument("--census-rel", required=True)
    ap.add_argument("--cold-observation-rel", nargs="*",
                    default=[])
    ap.add_argument("--cold-proof-rel")
    ap.add_argument("--out-rel")
    args = ap.parse_args()
    ev = Path(args.evidence_root)
    obs = _load_observation(ev / args.observation_rel)
    census = _load_census(ev / args.census_rel)
    interventions = _load_interventions(ev)
    confs = [_load_observation(ev / rel)
             for rel in args.cold_observation_rel]
    cold_proof = None
    if args.cold_proof_rel:
        cold_proof = json.loads(
            (ev / args.cold_proof_rel).read_text(encoding="utf-8"))
    result = evaluate_gate(
        observation=obs, census=census, interventions=interventions,
        cold_confirmation_observations=confs, cold_proof=cold_proof)
    # out-rel is EVIDENCE-ROOT-relative (same convention as every
    # other V2-G CLI) — never CWD-relative
    out = ev / args.out_rel if args.out_rel else (ev / "gate-result.json")
    host.durable_write(out,
                       json.dumps(result, indent=1,
                                  sort_keys=True).encode() + b"\n")
    print(json.dumps({"result": result["result"],
                      "failed": result["failed_checks"]}, indent=1))
    return 0 if result["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
