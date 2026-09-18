#!/usr/bin/env python3
"""Issue #216 acyclic producer, input, and final-closure lifecycle."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import issue216_assemble as assemble

ROOT = Path(__file__).resolve().parents[1]
AREA = ROOT / "docs/investigations/vulkan-v2-d-v340l-concurrent"
PRODUCERS = (
    "scripts/issue216_campaign_plan.py", "scripts/issue216_physical_authority.py",
    "scripts/issue216_preflight.py", "scripts/issue216_concurrent.py",
    "scripts/issue216_transport.py", "scripts/issue216_soak.py",
    "scripts/issue216_fault_isolation.py", "scripts/issue216_reset.py",
    "scripts/issue216_assemble.py", "scripts/issue216_terminal.py",
    "scripts/issue216_manifest.py", "tests/test_issue216_v2d_concurrent.py",
)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def producer_document() -> dict:
    return {"schema": "inferswarm.v2d.producer-hashes/2", "campaign_id": assemble.CAMPAIGN_ID,
            "producers": [{"path": path, "sha256": sha(ROOT / path)} for path in PRODUCERS]}


def write_producers() -> Path:
    out = AREA / "producer-hashes.json"
    out.write_bytes(json.dumps(producer_document(), indent=1, sort_keys=True).encode()+b"\n")
    return out


def closure_rows(paths: tuple[Path, ...]) -> list[dict[str, str]]:
    return [{"path": path.relative_to(ROOT).as_posix(), "sha256": sha(path)} for path in paths]


def write_preexecution_closure() -> Path:
    """Freeze all correctness-bearing source before any physical receipt exists."""
    assemble.assert_preexecution_namespace_clean(ROOT)
    paths = (AREA / "CAMPAIGN-PLAN.json", AREA / "PHYSICAL-AUTHORITY.json", AREA / "README.md", AREA / "producer-hashes.json")
    doc = {"schema": "inferswarm.v2d.preexecution-producer-closure/2", "campaign_id": assemble.CAMPAIGN_ID,
           "zero_physical_receipts": True, "closure_inputs": closure_rows(paths),
           "producer_hashes": producer_document()["producers"],
           "supersession_rule": "Any correctness-bearing producer hash drift invalidates this closure; physical receipts bound to it must not flow through a new producer head. A new campaign ID and closure are required."}
    doc["closure_digest"] = hashlib.sha256(json.dumps(doc, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    out = AREA / "PREEXECUTION-PRODUCER-CLOSURE.json"
    out.write_bytes(json.dumps(doc, indent=1, sort_keys=True).encode()+b"\n")
    (AREA / "PREEXECUTION-PRODUCER-CLOSURE.sha256").write_text(f"{sha(out)}  {out.name}\n")
    return out


def write_inputs(area: Path) -> Path:
    doc = assemble.build_input_manifest(area)
    out = area / "evidence" / "INPUT-MANIFEST.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(json.dumps(doc, indent=1, sort_keys=True).encode()+b"\n")
    return out


def write_final_closure() -> Path:
    paths = (AREA / "PREEXECUTION-PRODUCER-CLOSURE.json", AREA / "evidence" / "INPUT-MANIFEST.json", AREA / "TERMINAL.json", AREA / "README.md")
    doc = {"schema": "inferswarm.v2d.final-closure/2", "campaign_id": assemble.CAMPAIGN_ID,
           "closure_inputs": closure_rows(paths)}
    doc["closure_digest"] = hashlib.sha256(json.dumps(doc, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    out = AREA / "FINAL-CLOSURE.json"
    out.write_bytes(json.dumps(doc, indent=1, sort_keys=True).encode()+b"\n")
    return out


def check_preexecution() -> bool:
    assemble.assert_preexecution_namespace_clean(ROOT)
    saved = json.loads((AREA / "producer-hashes.json").read_text())
    closure = json.loads((AREA / "PREEXECUTION-PRODUCER-CLOSURE.json").read_text())
    return saved == producer_document() and closure.get("producer_hashes") == producer_document()["producers"] and closure.get("zero_physical_receipts") is True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write-producers", action="store_true"); ap.add_argument("--write-preexecution-closure", action="store_true")
    ap.add_argument("--write-inputs", action="store_true"); ap.add_argument("--write-final-closure", action="store_true")
    ap.add_argument("--check-preexecution", action="store_true")
    args = ap.parse_args()
    if args.write_producers: print(write_producers())
    if args.write_preexecution_closure: print(write_preexecution_closure())
    if args.write_inputs: print(write_inputs(AREA))
    if args.write_final_closure: print(write_final_closure())
    if args.check_preexecution and not check_preexecution(): raise SystemExit("pre-execution producer closure failed")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
