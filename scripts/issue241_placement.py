#!/usr/bin/env python3
"""Issue #241 Phase 2 gate: prospectively frozen matched-placement ladder.

Both arms run on inferswarm01 SEQUENTIALLY at the SAME ngl: the RX 580
sets the placement (largest stable rung under the frozen reserve); the
RTX 3060 reference runs at that exact same offloaded-layer count even
though it has 12 GB.

Ladder derivation is PURE arithmetic on the frozen placement-law
constants and the candidate's census VRAM (8192 MiB) minus the frozen
reserve (1536 MiB) = 6656 MiB model budget. Performance observations and
candidate-vs-reference numerical agreement NEVER enter the derivation or
rung selection.

Rung invalidation: startup failure, GPU allocation failure, DEVICE-side
buffer-type fallback (CPU-side "Vulkan_Host -> CPU" lines are the
expected host-mapped pipeline and NOT fallbacks), placement mismatch vs
requested ngl, excluded-device residency above the noise floor, OOM.

Selection = max valid rung; matched placement = that rung on BOTH arms.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import issue241_constants as C

SCHEMA = "inferswarm.issue241.phase2-matched-placement/1"
RUNG_SCHEMA = "inferswarm.issue241.placement-rung/1"


def parse_placement(log_text: str) -> dict[str, Any]:
    """Extract layer placement + buffer sizes from a -lv 5 server log."""
    dev_layers: dict[str, set[int]] = {}
    for m in re.finditer(
            r"load_tensors: layer\s+(\d+) assigned to device (\S+)", log_text):
        dev_layers.setdefault(m.group(2), set()).add(int(m.group(1)))
    offloaded = re.findall(r"offloaded (\d+)/(\d+) layers to GPU", log_text)
    buffers: dict[str, list[float]] = {}
    buffer_records = []
    for m in re.finditer(
            r"(Vulkan0|Vulkan_Host|CPU) (model|compute|KV|output|RS)"
            r" buffer size =\s*([\d.]+) MiB", log_text):
        device, kind, amount = m.groups()
        value = float(amount)
        buffers.setdefault(device, []).append(value)
        buffer_records.append({"device": device, "kind": kind, "mib": value})
    return {
        "devices_layer_counts": {k: len(v) for k, v in dev_layers.items()},
        "offloaded_layers": list(offloaded[-1]) if offloaded else None,
        "buffer_mib": buffers,
        "buffer_records": buffer_records,
        "alloc_failures": len(re.findall(r"failed to allocate", log_text)),
        # CPU-side weights legitimately report "cannot be used with
        # preferred buffer type Vulkan_Host, using CPU instead" at every
        # ngl (host-mapped pipeline; present in accepted R8-H logs). A
        # SILENT fallback is a DEVICE-side demotion only.
        "fallback_markers": len(re.findall(
            r"preferred buffer type Vulkan[0-9](?!_Host)", log_text)),
    }


def judge_rung(rung: dict[str, Any]) -> dict[str, Any]:
    """Judge one placement rung record; derive problems from raw fields."""
    if rung.get("schema") != RUNG_SCHEMA:
        raise ValueError("rung schema mismatch")
    problems: list[str] = []
    arm = rung.get("arm")
    ngl = rung.get("ngl")
    if arm not in ("B", "C"):
        problems.append(f"unknown arm {arm!r}")
    if not isinstance(ngl, int) or ngl < 1 or ngl not in C.LADDER_NGLS:
        problems.append(f"ngl {ngl!r} not on the frozen ladder")
    if not rung.get("loaded"):
        problems.append("startup failure")
    placement = rung.get("placement") or {}
    if placement.get("alloc_failures"):
        problems.append("GPU allocation failure")
    if placement.get("fallback_markers"):
        problems.append("device-side silent fallback")
    offloaded = placement.get("offloaded_layers")
    if not (isinstance(offloaded, list) and len(offloaded) == 2 and
            str(ngl) == str(offloaded[0])):
        problems.append(f"placement mismatch vs requested ngl ({offloaded!r})")
    if arm == "C":
        budget = placement.get("buffer_records") or []
        model_mib = sum(r.get("mib", 0.0) for r in budget
                        if r.get("device") == "Vulkan0" and r.get("kind") == "model")
        if model_mib > C.CANDIDATE_MODEL_BUDGET_MIB + 0.5:
            problems.append(
                f"candidate model buffers {model_mib:.1f} MiB exceed the "
                f"prospective budget {C.CANDIDATE_MODEL_BUDGET_MIB} MiB")
    excluded = rung.get("excluded_device_residency_mib") or {}
    for bdf, used in excluded.items():
        if used > C.EXCLUDED_RESIDENCY_NOISE_MIB:
            problems.append(
                f"excluded device {bdf} residency {used} MiB over noise floor")
    return {
        "schema": "inferswarm.issue241.rung-verdict/1",
        "arm": arm, "ngl": ngl,
        "valid": not problems, "problems": problems,
    }


def select_matched_rung(rungs_by_arm: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    """Largest rung valid on BOTH arms = the matched placement."""
    if set(rungs_by_arm) != {"B", "C"}:
        raise ValueError("both arms required for matched placement")
    verdicts = {
        arm: {r["ngl"]: judge_rung(r) for r in rungs}
        for arm, rungs in rungs_by_arm.items()
    }
    valid_common = sorted(
        ngl for ngl in C.LADDER_NGLS
        if all(v.get(ngl, {}).get("valid") for v in verdicts.values())
    )
    problems = {
        arm: {str(ngl): v["problems"] for ngl, v in verdicts[arm].items()
              if not v["valid"]}
        for arm in verdicts
    }
    if not valid_common:
        return {
            "schema": SCHEMA, "campaign": C.CAMPAIGN_ID,
            "matched_ngl": None,
            "placement_blocked": True,
            "problems": problems,
            "rule": "no rung valid on both arms; R8I3 placement cannot freeze",
        }
    matched = valid_common[-1]
    return {
        "schema": SCHEMA, "campaign": C.CAMPAIGN_ID,
        "matched_ngl": matched,
        "placement_blocked": False,
        "valid_common_rungs": valid_common,
        "problems": problems,
        "rule": ("largest rung valid on both arms; reference runs at the "
                 "candidate's exact offloaded-layer count; performance and "
                 "candidate-vs-reference agreement never entered selection"),
    }


def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--rungs", type=Path, required=True,
                    help="JSON {arm: [rung records]}")
    args = ap.parse_args(argv)
    data = json.loads(args.rungs.read_text())
    print(json.dumps(select_matched_rung(data), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
