#!/usr/bin/env python3
"""Issue #228 — V2-E matched baseline collectors (Phase 4) — DISABLED.

Correction round: baselines are CONTROLS for peer transfer arms. With
transfer execution hard-disabled (see issue228_ladder) there is no arm
to control, so this collector always emits the refusal artifact. The
#216 faulting transport seam is not rerun under any circumstances.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import issue228_receipt as rc
import issue228_ladder as ladder

ROOT = Path(__file__).resolve().parents[1]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def emit_refusal(*, repo: Path, out: Path, attempt_id: str,
                 verdict: dict[str, Any]) -> dict[str, Any]:
    closure = rc.verify_closure(repo)
    mechanism = ladder.classify_mechanism(verdict)
    decision = ladder.authorize_execution(mechanism)
    out.mkdir(parents=True, exist_ok=True)
    doc = {
        "schema": "inferswarm.v2e.baselines-refusal/2",
        "campaign_id": rc.CAMPAIGN_ID,
        "attempt_id": attempt_id,
        "captured_utc": _now(),
        "closure_digest": closure["closure_digest"],
        "producer_head": closure["producer_head"],
        "mechanism": mechanism,
        "execution_decision": decision,
        "refusal": (
            "Matched baselines are controls for peer arms; transfer "
            "execution is disabled for this campaign (no reviewed "
            "transfer producer), so no baseline arm runs and the #216 "
            "faulting transport seam is not rerun."),
        "executed": False,
        "executed_transfers": 0,
    }
    (out / "refusal.json").write_bytes(
        json.dumps(doc, indent=1, sort_keys=True).encode() + b"\n")
    return doc


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=str(ROOT))
    ap.add_argument("--out", required=True)
    ap.add_argument("--attempt-id", default="base2")
    ap.add_argument("--preflight", required=True)
    args = ap.parse_args()
    preflight = json.loads(Path(args.preflight).read_text())
    verdict = preflight.get("capability_verdict")
    if not verdict:
        raise SystemExit(
            "preflight carries no capability_verdict; only a corrected "
            "(pf2) preflight may drive the baseline gate")
    doc = emit_refusal(repo=Path(args.repo), out=Path(args.out),
                       attempt_id=args.attempt_id, verdict=verdict)
    print(json.dumps({"baselines": str(Path(args.out)),
                      "executed": doc["executed"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
