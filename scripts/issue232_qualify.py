#!/usr/bin/env python3
"""Issue #232 — V2-G Phase 4 bounded post-remediation qualification.

Runs ONLY after the clean-link gate passes (refused otherwise —
control 13 in reverse: this phase itself refuses to precede the gate).

Steps (read-only / minimal non-faulting):
  1. Vulkan enumeration/identity (the accepted #230 identity probe
     binary shape: UUID->BDF join against the current census chain);
  2. VRAM/resource census per die (sysfs, read-only);
  3. ONE small same-die operation per die (a 4-MiB same-die copy
     through the accepted #230 producer's `samedie` subcommand —
     the minimal driver-usability check, no cross-die transfer);
  4. health/AER/journal delta over the qualification window;
  5. re-confirm the clean-link gate on a fresh observation.

Any amdgpu fault or material RxErr recurrence STOPS the campaign here.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import issue232_receipt as rc
import issue232_host as host
import issue232_baseline as baseline

ROOT = Path(__file__).resolve().parents[1]

QUALIFY_SCHEMA = "inferswarm.v2g.qualification/1"

SAME_DIE_SIZE = 4 << 20
SAME_DIE_REPS = 1
SAME_DIE_WARMUPS = 0


class QualifyError(RuntimeError):
    pass


def _load(path: Path, schema: str) -> dict[str, Any]:
    doc = json.loads(path.read_text(encoding="utf-8"))
    if doc.get("schema") != schema:
        raise QualifyError(f"bad schema in {path}: {doc.get('schema')}")
    return doc


def run_qualification(*, repo: Path, evidence_root: Path,
                      gate_result_rel: str,
                      build_dir: Path) -> dict[str, Any]:
    gate = _load(evidence_root / gate_result_rel,
                 "inferswarm.v2g.clean-link-gate/1")
    if gate.get("result") != "PASS":
        raise QualifyError(
            "qualification refused: clean-link gate has not passed "
            "(issue Phase 4 runs only after the gate)")
    closure = rc.verify_closure(repo)
    authority = json.loads(
        (repo / rc.AREA_REL / "PHYSICAL-AUTHORITY.json")
        .read_text(encoding="utf-8"))

    out = evidence_root / "qualification"
    out.mkdir(parents=True, exist_ok=True)
    raw = out / "raw"
    raw.mkdir(parents=True, exist_ok=True)

    # fresh chain
    nn = host.run_probe(["lspci", "-nn"])["stdout"]
    tree = host.run_probe(["lspci", "-tv"])["stdout"]
    vv = "\n".join(host.run_probe(
        ["lspci", "-PP", "-nn", "-vv", "-d", i], timeout=180)["stdout"]
        for i in (host.PM8533_ID, "8086:a29a", host.VEGA_ID))
    chain = host.derive_chain(nn, tree, vv)
    rows = host.parse_lspci_nn(nn)
    vegas = sorted(r["bdf"] for r in rows if r["id"] == host.VEGA_ID)
    if len(vegas) != 2:
        raise QualifyError(f"expected 2 dies, saw {vegas}")

    # ---- 1. Vulkan identity (compile the accepted #230 producer) ---
    sys.path.insert(0, str(
        repo / "scripts"))
    import issue230_transfer as transfer  # the accepted replay source
    binary, src = transfer.compile_transfer(build_dir)
    host.durable_write(raw / "transfer-source.c", src.encode())
    host.durable_write(raw / "transfer-binary.sha256",
                       hashlib.sha256(binary.read_bytes())
                       .hexdigest().encode())
    idy = transfer.run_probe(
        binary, ["identity", vegas[0], vegas[1]], raw,
        "qualify-identity", timeout=120)
    if idy["returncode"] != 0:
        raise QualifyError(
            f"identity probe failed rc={idy['returncode']}: "
            f"{idy['stderr'][:300]}")
    # UUID->BDF join must contain both expected die BDFs
    idy_doc = json.loads(idy["stdout"])
    bdfs_seen = {d.get("bdf") for d in idy_doc.get("devices", [])}
    if not set(vegas) <= bdfs_seen:
        raise QualifyError(
            f"identity join missing dies: expected {vegas}, "
            f"probe saw {bdfs_seen}")

    # ---- 2. VRAM/resource census ---------------------------------
    vram = {}
    for bdf in vegas:
        dev = Path("/sys/bus/pci/devices") / bdf
        vram[bdf] = {
            "vram_total_bytes": host._int_or_none(host._read(
                dev / "mem_info_vram_total")),
            "vram_used_bytes": host._int_or_none(host._read(
                dev / "mem_info_vram_used")),
            "driver": host._read(dev / "driver") or
                      (host.run_probe(
                          ["lspci", "-k", "-s",
                           bdf.removeprefix("0000:")])["stdout"]),
        }

    # ---- 3. one small same-die op per die -------------------------
    j0 = host.journal_scan()
    start_aer = {bdf: host.aer_counters(bdf)
                 for bdf in {chain["root_port_bdf"],
                             chain["switch_upstream_bdf"], *vegas}}
    same_die = {}
    for idx, bdf in enumerate(vegas):
        rep = transfer.run_probe(
            binary, ["samedie", bdf, str(SAME_DIE_SIZE),
                     str(SAME_DIE_REPS), str(SAME_DIE_WARMUPS),
                     str(0x23250000 + idx)], raw,
            f"qualify-samedie-{idx}", timeout=300)
        same_die[bdf] = {
            "exit_code": rep["returncode"],
            "stdout_rel": f"raw/qualify-samedie-{idx}.stdout",
            "ok": rep["returncode"] == 0 and '"ok":true'
                  in rep["stdout"].rsplit('"event":"summary"', 1)[-1],
        }
    j1 = host.journal_scan(cursor=j0["next_cursor"])
    end_aer = {bdf: host.aer_counters(bdf)
               for bdf in start_aer}
    census_delta = host.aer_event_census(j1["text"])
    host.durable_write(raw / "journal-delta.stdout",
                       j1["text"].encode())

    # ---- stop evaluation ------------------------------------------
    up_bdf = chain["switch_upstream_bdf"]
    corr = ((host.aer_delta(
        {"aer": start_aer}, {"aer": end_aer})
        .get(up_bdf) or {}).get("aer_dev_correctable") or {})
    rxerr_delta = corr.get("RxErr", -1)
    stop = None
    if any(not r["ok"] for r in same_die.values()):
        stop = "same_die_operation_failed"
    elif j1["counts"].get("amdgpu_timeout"):
        stop = "ring_timeout_or_hang"
    elif j1["counts"].get("amdgpu_reset"):
        stop = "gpu_reset_or_reset_failure"
    elif (census_delta["events"]["Uncorrectable"] > 0
          or census_delta["events"]["DPC"] > 0):
        stop = "uncorrectable_aer_or_dpc"
    elif rxerr_delta is None or rxerr_delta > rc.CLEAN_LINK_RXERR_MAX:
        stop = "material_rxerr_flood_recurrence"

    doc = {
        "schema": QUALIFY_SCHEMA,
        "campaign_id": rc.CAMPAIGN_ID,
        "qualification_id": f"v2g-qual-{int(time.time())}",
        "gate_result_rel": gate_result_rel,
        "gate_checks_passed": gate["checks"],
        "collected_utc": datetime.now(timezone.utc).isoformat(),
        "boot_id": host.boot_id(),
        "chain": chain,
        "vega_bdfs": vegas,
        "identity_join_ok": True,
        "vram_census": vram,
        "same_die_operations": same_die,
        "journal_fault_counts": j1["counts"],
        "journal_census_delta": census_delta,
        "upstream_rxerr_delta": rxerr_delta,
        "stop_condition": stop,
        "closure_digest": closure["closure_digest"],
        "producer_head": closure["producer_head"],
    }
    host.durable_write(out / "qualification.json",
                       json.dumps(doc, indent=1, sort_keys=True).encode()
                       + b"\n")
    return doc


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=str(ROOT))
    ap.add_argument("--evidence-root", required=True)
    ap.add_argument("--gate-result-rel", required=True)
    ap.add_argument("--build-dir", default="/var/tmp/issue232-build")
    args = ap.parse_args()
    doc = run_qualification(
        repo=Path(args.repo), evidence_root=Path(args.evidence_root),
        gate_result_rel=args.gate_result_rel,
        build_dir=Path(args.build_dir))
    print(json.dumps({"stop_condition": doc["stop_condition"],
                      "same_die": {k: v["ok"] for k, v in
                                   doc["same_die_operations"].items()},
                      "rxerr_delta": doc["upstream_rxerr_delta"]},
                     indent=1))
    return 0 if doc["stop_condition"] is None else 1


if __name__ == "__main__":
    raise SystemExit(main())
