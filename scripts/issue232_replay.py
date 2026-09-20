#!/usr/bin/env python3
"""Issue #232 — V2-G Phase 5 bounded replay authorization + driver.

authorize() emits the machine-readable replay authorization decision
from retained gate/qualification evidence ONLY (issue Phase 5). It is
refused unless:
  * the clean-link gate PASSED and its required cold confirmations
    are retained (never a warm substitute);
  * the bounded qualification passed with no stop condition;
  * predecessor evidence preservation holds (authority re-verify);
  * the replay producer is byte-identical to the accepted #230
    producer (closure digest + transfer source blob hash re-derived
    from the pinned V2-F head; any change requires a separately
    reviewed freeze — control 14);
  * the exact replay arm ladder is frozen in advance (control 15:
    first arm is 4 KiB, never the 64-MiB fault scale).

run_arm() executes ONE ladder rung per invocation under a
digest-chained order state (same discipline as the accepted V2-F
safety machine): predecessors must have passed, no duplicate
execution under the same authority, any failure halts permanently (no
rerun seeking a cleaner outcome — control 19).

Every arm runs with per-arm health windows (AER delta on the chain
BDFs, amdgpu journal scan with cursor chaining, link state, host
sentinels) and immediate-stop evaluation including MATERIAL RxErr
recurrence (control 17).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import issue232_receipt as rc
import issue232_host as host

ROOT = Path(__file__).resolve().parents[1]

SCHEMA_AUTHZ = "inferswarm.v2g.replay-authorization/1"
SCHEMA_ORDER = "inferswarm.v2g.replay-order/1"

#: Material RxErr recurrence during replay: the chronic flood ran at
#: ~477 events/min. MATERIAL means a sustained rate consistent with
#: flood recurrence, NOT a handful of events; frozen prospectively at
#: 1/100th of the chronic rate (order of magnitude below) so a
#: recurrence cannot be waved away, while isolated single events
#: (recorded, never ignored) do not themselves halt the campaign.
MATERIAL_RXERR_RATE_PER_MIN = 4.77  # chronic 477 / 100

ORDER_SEQUENCE = tuple(
    f"replay-{r['size_bytes']}" for r in rc.REPLAY_LADDER)


class ReplayError(RuntimeError):
    pass


def _load(path: Path, schema: str | None = None) -> dict[str, Any]:
    doc = json.loads(path.read_text(encoding="utf-8"))
    if schema and doc.get("schema") != schema:
        raise ReplayError(f"bad schema in {path}: {doc.get('schema')}")
    return doc


def authorize(*, repo: Path, evidence_root: Path) -> dict[str, Any]:
    """Emit the machine-readable replay authorization decision."""
    gate_path = evidence_root / "gate-result.json"
    gate = _load(gate_path, "inferswarm.v2g.clean-link-gate/1")
    qual_path = evidence_root / "qualification" / "qualification.json"
    qual = _load(qual_path, "inferswarm.v2g.qualification/1")

    reasons: list[str] = []
    ok = True

    if gate.get("result") != "PASS":
        ok = False
        reasons.append("clean-link gate has not passed")
    if not gate.get("checks", {}).get("cold_confirmation_repeated"):
        ok = False
        reasons.append("required cold confirmation(s) missing")
    if qual.get("stop_condition") is not None:
        ok = False
        reasons.append(
            f"qualification stopped: {qual.get('stop_condition')}")

    # predecessor preservation (authority re-verify)
    import issue232_authority as pa
    authority = json.loads(
        (repo / rc.AREA_REL / "PHYSICAL-AUTHORITY.json")
        .read_text(encoding="utf-8"))
    try:
        pa.verify_authority(authority, repo)
    except pa.AuthorityError as exc:
        ok = False
        reasons.append(f"authority re-verify failed: {exc}")

    # replay producer byte-identity (control 14)
    pin = authority["replay_producer_pin"]
    blob = subprocess.run(
        ["git", "-C", str(repo), "cat-file", "blob",
         f"{pin['producer_head']}:{pin['transfer_source']}"],
        capture_output=True).stdout
    blob_sha = hashlib.sha256(blob).hexdigest()
    if blob_sha != pin["transfer_source_sha256"]:
        ok = False
        reasons.append(
            "replay producer source diverges from the accepted V2-F "
            "pin — a changed producer requires a separately reviewed "
            "freeze")
    closure = rc.verify_closure(repo)

    doc = {
        "schema": SCHEMA_AUTHZ,
        "campaign_id": rc.CAMPAIGN_ID,
        "decision_utc": datetime.now(timezone.utc).isoformat(),
        "authorized": ok,
        "decision": "REPLAY_AUTHORIZED" if ok else "REPLAY_REFUSED",
        "reasons": reasons,
        "gate_result_digest": rc.sha256_bytes(
            gate_path.read_bytes()),
        "qualification_digest": rc.sha256_bytes(
            qual_path.read_bytes()),
        "replay_producer": {
            "campaign": pin["campaign"],
            "producer_head": pin["producer_head"],
            "closure_digest": pin["closure_digest"],
            "transfer_source": pin["transfer_source"],
            "transfer_source_sha256_rederived": blob_sha,
            "byte_identical_to_accepted": blob_sha
            == pin["transfer_source_sha256"],
        },
        "frozen_arm_ladder": [dict(r) for r in rc.REPLAY_LADDER],
        "first_arm_bytes": rc.REPLAY_LADDER[0]["size_bytes"],
        "stop_conditions": list(rc.REPLAY_STOP_CONDITIONS),
        "material_rxerr_rate_per_min": MATERIAL_RXERR_RATE_PER_MIN,
        "closure_digest": closure["closure_digest"],
        "producer_head": closure["producer_head"],
    }
    out = evidence_root / "replay-authorization.json"
    if out.exists() and _load(out).get("authorized") is True:
        # an existing AUTHORIZED decision is immutable under this
        # authority (rerunning the authorization to flip it is the
        # rerun-seeeking-cleaner-outcome failure mode)
        raise ReplayError(
            "an authorized replay decision already exists; it is "
            "immutable under this authority")
    host.durable_write(out, json.dumps(doc, indent=1,
                                       sort_keys=True).encode() + b"\n")
    return doc


# ---------------------------------------------------------------------------
# Order state (append-only, digest-chained — the accepted V2-F pattern).
# ---------------------------------------------------------------------------

def _load_order(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"schema": SCHEMA_ORDER, "campaign_id": rc.CAMPAIGN_ID,
                "entries": [], "chain_digest": None}
    doc = json.loads(path.read_text(encoding="utf-8"))
    if doc.get("schema") != SCHEMA_ORDER:
        raise ReplayError(f"bad order-state schema: {path}")
    if doc.get("campaign_id") != rc.CAMPAIGN_ID:
        raise ReplayError(f"order state belongs to another campaign")
    return doc


def _chain(doc: dict[str, Any]) -> str:
    body = {k: v for k, v in doc.items() if k != "chain_digest"}
    return hashlib.sha256(rc.canonical(body)).hexdigest()


def _verify_chain(doc: dict[str, Any]) -> None:
    if doc.get("chain_digest") is None:
        if doc.get("entries"):
            raise ReplayError("order state has entries but no digest")
        return
    if doc.get("chain_digest") != _chain(doc):
        raise ReplayError("order-state chain digest mismatch")


def order_state_path(evidence_root: Path) -> Path:
    return evidence_root / "replay-order-state.json"


def authorize_arm(evidence_root: Path, arm: str) -> dict[str, Any]:
    """Fail-closed arm authorization (V2-F semantics): arm known;
    predecessors all passed; no failure anywhere (earliest failure
    halts permanently); no duplicates."""
    if arm not in ORDER_SEQUENCE:
        raise ReplayError(f"unknown arm: {arm}")
    # the replay authorization must be standing
    authz = _load(evidence_root / "replay-authorization.json",
                  SCHEMA_AUTHZ)
    if not authz.get("authorized"):
        raise ReplayError("replay is not authorized (gate/qualification)")
    doc = _load_order(order_state_path(evidence_root))
    _verify_chain(doc)
    states = {e["arm"]: e["state"] for e in doc["entries"]}
    if arm in states:
        raise ReplayError(
            f"arm {arm} already recorded ({states[arm]}); duplicate "
            "execution under the same authority is refused")
    if any(s == "failed" for s in states.values()):
        failed = [a for a, s in states.items() if s == "failed"]
        raise ReplayError(
            f"campaign halted: earlier failure retained ({failed}); "
            "no escalation, no rerun under the same authority")
    idx = ORDER_SEQUENCE.index(arm)
    for pred in ORDER_SEQUENCE[:idx]:
        if states.get(pred) != "passed":
            raise ReplayError(
                f"predecessor arm {pred} not passed "
                f"(state={states.get(pred)!r})")
    return {"arm": arm, "authorized": True,
            "predecessors_passed": list(ORDER_SEQUENCE[:idx])}


def record_arm_result(evidence_root: Path, arm: str, state: str,
                      detail: dict[str, Any]) -> dict[str, Any]:
    if state not in ("passed", "failed"):
        raise ReplayError(f"bad arm state: {state}")
    path = order_state_path(evidence_root)
    doc = _load_order(path)
    _verify_chain(doc)
    states = {e["arm"]: e["state"] for e in doc["entries"]}
    if arm in states:
        raise ReplayError(f"arm {arm} already recorded")
    if any(s == "failed" for s in states.values()):
        raise ReplayError("campaign already halted by earlier failure")
    entry = {
        "arm": arm,
        "state": state,
        "recorded_utc": datetime.now(timezone.utc).isoformat(),
        "detail": detail,
    }
    doc["entries"].append(entry)
    doc["chain_digest"] = _chain(doc)
    path.parent.mkdir(parents=True, exist_ok=True)
    host.durable_write(path, json.dumps(doc, indent=1,
                                        sort_keys=True).encode()
                       + b"\n")
    return doc


def run_arm(*, repo: Path, evidence_root: Path, arm: str,
            build_dir: Path) -> dict[str, Any]:
    """Execute ONE replay rung (issue Phase 5): compile the ACCEPTED
    V2-F producer source verbatim, identity-bind the dies on the
    current boot, run ONE exact-correct rep of the frozen size in the
    frozen direction/mechanism, close the health window, evaluate
    immediate-stop conditions."""
    closure = rc.verify_closure(repo)
    authz = _load(evidence_root / "replay-authorization.json",
                  SCHEMA_AUTHZ)
    if not authz.get("authorized"):
        raise ReplayError("replay not authorized")
    auth = authorize_arm(evidence_root, arm)
    size = int(arm.split("-")[1])
    rung = next(r for r in rc.REPLAY_LADDER
                if r["size_bytes"] == size)
    if rung["reps"] != 1 or rung["warmups"] != 0:
        raise ReplayError("frozen replay rung must be 1 rep, 0 warmup")

    # compile the accepted V2-F producer source, verbatim; the byte
    # identity is re-derived HERE (run-time) from the pinned V2-F head
    # and cross-checked against both the authority pin and the
    # authorization document's rederived hash
    pin = authz["replay_producer"]
    import issue232_authority as pa
    authority = json.loads(
        (repo / rc.AREA_REL / "PHYSICAL-AUTHORITY.json")
        .read_text(encoding="utf-8"))
    apin = authority["replay_producer_pin"]
    blob = subprocess.run(
        ["git", "-C", str(repo), "cat-file", "blob",
         f"{pin['producer_head']}:{pin['transfer_source']}"],
        capture_output=True).stdout
    blob_sha = hashlib.sha256(blob).hexdigest()
    if blob_sha != apin["transfer_source_sha256"] \
            or blob_sha != pin.get("transfer_source_sha256_rederived"):
        raise ReplayError("producer bytes diverge from the accepted pin")
    sys.path.insert(0, str(repo / "scripts"))
    import issue230_transfer as transfer
    build_dir.mkdir(parents=True, exist_ok=True)
    binary, src = transfer.compile_transfer(
        build_dir, source_override=blob.decode("utf-8"))
    # bind the executed source bytes
    raw = evidence_root / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    host.durable_write(raw / f"{arm}-producer-source.c", blob)
    host.durable_write(
        raw / f"{arm}-producer-binary.sha256",
        hashlib.sha256(binary.read_bytes()).hexdigest().encode())

    # fresh identity binding (current boot)
    nn = host.run_probe(["lspci", "-nn"])["stdout"]
    rows = host.parse_lspci_nn(nn)
    vegas = sorted(r["bdf"] for r in rows if r["id"] == host.VEGA_ID)
    if len(vegas) != 2:
        raise ReplayError(f"expected 2 dies, saw {vegas}")
    idy = transfer.run_probe(
        binary, ["identity", vegas[0], vegas[1]], raw,
        f"{arm}-identity", timeout=120)
    if idy["returncode"] != 0:
        record_arm_result(evidence_root, arm, "failed",
                          {"reason": "identity probe failed",
                           "exit": idy["returncode"],
                           "stderr": idy["stderr"][:500]})
        raise ReplayError("identity probe failed")

    # die A = first BDF, die B = second (sorted); the replay direction
    # is B->A: src=B, dst=A. Cross-check against the authority's
    # historical die BDFs by bus order (die A historically 06:00.0 <
    # die B 09:00.0 — sorted order preserves A,B).
    src_bdf, dst_bdf = vegas[1], vegas[0]

    # fresh chain derivation for the health-window BDF set (control 1:
    # never hardcode the historical upstream BDF after a slot move)
    tree = host.run_probe(["lspci", "-tv"])["stdout"]
    vv = host.collect_vv_bytes()
    live_chain = host.derive_chain(nn, tree, vv)
    up_bdf = live_chain["switch_upstream_bdf"]
    rp_bdf = live_chain["root_port_bdf"]

    j0 = host.journal_scan()
    start_aer = {bdf: host.aer_counters(bdf) for bdf in
                 sorted({*vegas, up_bdf, rp_bdf})}
    start_links = {bdf: host.link_state(bdf) for bdf in start_aer}
    start_monotonic = time.monotonic_ns()

    rep = transfer.run_probe(
        binary,
        ["transfer", rc.REPLAY_MECHANISM, rc.REPLAY_DIRECTION,
         src_bdf, dst_bdf, str(size), str(rung["reps"]),
         str(rung["warmups"]),
         str(rc.REPLAY_SEED_BASE + size)],
        raw, arm, timeout=1800)

    end_monotonic = time.monotonic_ns()
    j1 = host.journal_scan(cursor=j0["next_cursor"])
    end_aer = {bdf: host.aer_counters(bdf) for bdf in start_aer}
    end_links = {bdf: host.link_state(bdf) for bdf in start_aer}
    census_delta = host.aer_event_census(j1["text"])
    host.durable_write(raw / f"{arm}-journal-delta.stdout",
                       j1["text"].encode())
    elapsed_min = (end_monotonic - start_monotonic) / 60e9

    # correctness (control 16: a missing correctness observation is
    # never accepted)
    correctness_ok = False
    summary_tail = rep["stdout"].rsplit('"event":"summary"', 1)
    if rep["returncode"] == 0 and len(summary_tail) == 2:
        correctness_ok = '"ok":true' in summary_tail[-1]
    try:
        parsed = transfer.parse_transfer_stdout(rep["stdout"])
        validated = transfer.validate_transfer_run(
            parsed, mechanism=rc.REPLAY_MECHANISM,
            direction=rc.REPLAY_DIRECTION, size=size,
            reps_expected=rung["reps"],
            warmups_expected=rung["warmups"])
    except transfer.ProbeError as exc:
        validated = None
        correctness_ok = False
        rep = dict(rep)
        rep["validation_error"] = str(exc)

    # stop evaluation
    up_corr = ((host.aer_delta({"aer": start_aer}, {"aer": end_aer})
                .get(up_bdf) or {})
               .get("aer_dev_correctable") or {})
    rxerr_delta = up_corr.get("RxErr", -1)
    rxerr_rate = (rxerr_delta / elapsed_min
                  if isinstance(rxerr_delta, int) and rxerr_delta > 0
                  and elapsed_min > 0 else 0)
    stop = None
    if rep["returncode"] != 0:
        stop = "nonzero_producer_exit"
    elif not correctness_ok or validated is None:
        stop = "correctness_mismatch"
    elif j1["counts"].get("amdgpu_timeout"):
        stop = "ring_timeout_or_hang"
    elif j1["counts"].get("amdgpu_reset"):
        stop = "gpu_reset_or_reset_failure"
    elif (census_delta["events"]["Uncorrectable"] > 0
          or census_delta["events"]["DPC"] > 0):
        stop = "uncorrectable_aer_or_dpc"
    elif isinstance(rxerr_delta, int) and rxerr_delta > 0 \
            and rxerr_rate >= MATERIAL_RXERR_RATE_PER_MIN:
        stop = "material_rxerr_flood_recurrence"
    elif any((end_links[bdf].get("current_link_width")
              != start_links[bdf].get("current_link_width"))
             for bdf in start_links):
        stop = "unexpected_topology_or_width_change"

    arm_record = {
        "arm": arm,
        "size_bytes": size,
        "mechanism": rc.REPLAY_MECHANISM,
        "direction": rc.REPLAY_DIRECTION,
        "src_bdf": src_bdf, "dst_bdf": dst_bdf,
        "upstream_bdf": up_bdf, "root_port_bdf": rp_bdf,
        "exit_code": rep["returncode"],
        "stdout_rel": f"raw/{arm}.stdout",
        "stdout_sha256": rep.get("stdout_sha256"),
        "validated": validated is not None,
        "validation_error": rep.get("validation_error"),
        "health_window": {
            "journal_fault_counts": j1["counts"],
            "journal_census_delta": census_delta,
            "aer_delta": host.aer_delta({"aer": start_aer},
                                        {"aer": end_aer}),
            "link_start": start_links, "link_end": end_links,
            "elapsed_minutes": elapsed_min,
        },
        "stop_condition": stop,
        "closure_digest": closure["closure_digest"],
        "producer_head": closure["producer_head"],
        "replay_producer_head": pin["producer_head"],
        "authorized_predecessors": auth["predecessors_passed"],
    }
    out_dir = evidence_root / "arms"
    out_dir.mkdir(parents=True, exist_ok=True)
    host.durable_write(out_dir / f"{arm}.json",
                       json.dumps(arm_record, indent=1,
                                  sort_keys=True).encode() + b"\n")
    if stop is not None:
        record_arm_result(evidence_root, arm, "failed",
                          {"stop_condition": stop,
                           "size": size,
                           "exit": rep["returncode"]})
    else:
        record_arm_result(evidence_root, arm, "passed",
                          {"size": size,
                           "ns": (validated or {})
                           .get("measured_reps", [{}])[0]
                           .get("elapsed_ns") if validated else None})
    return arm_record


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=str(ROOT))
    ap.add_argument("--evidence-root", required=True)
    ap.add_argument("--build-dir", default="/var/tmp/issue232-build")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("authorize")
    sub.add_parser("order-state")
    r = sub.add_parser("arm")
    r.add_argument("--size", type=int, required=True)
    args = ap.parse_args()
    repo = Path(args.repo)
    ev = Path(args.evidence_root)
    if args.cmd == "authorize":
        doc = authorize(repo=repo, evidence_root=ev)
        print(json.dumps({"decision": doc["decision"],
                          "reasons": doc["reasons"]}, indent=1))
        return 0 if doc["authorized"] else 1
    if args.cmd == "order-state":
        print(order_state_path(ev).read_text())
        return 0
    doc = run_arm(repo=repo, evidence_root=ev,
                  arm=f"replay-{args.size}", build_dir=Path(args.build_dir))
    print(json.dumps({"arm": doc["arm"],
                      "stop_condition": doc["stop_condition"],
                      "validated": doc["validated"]}, indent=1))
    return 0 if doc["stop_condition"] is None else 1


if __name__ == "__main__":
    raise SystemExit(main())
