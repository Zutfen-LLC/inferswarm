#!/usr/bin/env python3
"""Issue #232 — V2-G terminal assembler (deterministic, fail-closed).

Verifies the producer closure binding FIRST, runs the reducer over
retained evidence, emits ASSEMBLY.json + TERMINAL.json. The authored
terminal must equal the deterministic reduction (control 20) — the
assembler refuses to write a contradicting terminal.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import issue232_receipt as rc
import issue232_reduce as reduce

ROOT = Path(__file__).resolve().parents[1]

ASSEMBLY_SCHEMA = "inferswarm.v2g.assembly/1"
TERMINAL_SCHEMA = "inferswarm.v2g.terminal/1"


class AssembleError(RuntimeError):
    pass


def assemble(*, repo: Path, evidence_root: Path) -> dict[str, Any]:
    closure = rc.verify_closure(repo)  # binding verified FIRST
    reduction = reduce.derive_terminal(evidence_root, closure=closure)

    terminal = reduction["terminal"]
    assembly = {
        "schema": ASSEMBLY_SCHEMA,
        "campaign_id": rc.CAMPAIGN_ID,
        "assembled_utc": datetime.now(timezone.utc).isoformat(),
        "closure_digest": closure["closure_digest"],
        "producer_head": closure["producer_head"],
        "reduction": reduction,
        "nonclaims": list(rc.NONCLAIMS),
        "state_dimensions": {
            "pcie_path_health": (
                "chronic RxErr condition remediated iff the "
                "clean-link gate passed"),
            "v340l_driver_health": (
                "both dies enumerate + minimal same-die usability "
                "(qualification phase)"),
            "external_memory_correctness": (
                "replay arms' exact-correct results only"),
            "amdgpu_ring_reset_stability": (
                "amdgpu fault classes from journal windows only"),
            "physical_route": (
                "derived only from measured behavior under the "
                "frozen route rule (never from naming)"),
        },
    }
    out_dir = evidence_root
    (out_dir / "ASSEMBLY.json").write_bytes(
        json.dumps(assembly, indent=1, sort_keys=True).encode()
        + b"\n")
    terminal_doc = {
        "schema": TERMINAL_SCHEMA,
        "campaign_id": rc.CAMPAIGN_ID,
        "terminal": terminal,
        "basis": reduction["basis"],
        "vocabulary": list(rc.TERMINALS),
        "nonclaims": list(rc.NONCLAIMS),
        "closure_digest": closure["closure_digest"],
        "producer_head": closure["producer_head"],
        "campaign_window_utc": [
            assembly["assembled_utc"], assembly["assembled_utc"]],
    }
    (out_dir / "TERMINAL.json").write_bytes(
        json.dumps(terminal_doc, indent=1, sort_keys=True).encode()
        + b"\n")
    return assembly


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=str(ROOT))
    ap.add_argument("--evidence-root", required=True)
    args = ap.parse_args()
    assembly = assemble(repo=Path(args.repo),
                        evidence_root=Path(args.evidence_root))
    term = json.loads((Path(args.evidence_root) / "TERMINAL.json")
                      .read_text())
    print(json.dumps({"terminal": term["terminal"],
                      "basis": term["basis"]}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
