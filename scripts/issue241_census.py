#!/usr/bin/env python3
"""Issue #241 Phase 1 precheck reducer: fresh same-host AMD/NVIDIA Vulkan
identity census validation (CPU-pure; consumes a census JSON captured
read-only on inferswarm01, never queries a device itself).

The census snapshot must bind, per the issue's hardware-preparation
boundary:
  - motherboard/CPU/RAM identity and capacity;
  - all PCIe slots and ancestry (both GPUs present, exact BDFs);
  - remaining RTX 3060 exact UUID/BDF/link;
  - RX 580 exact vendor/device/subsystem/revision/BDF/link;
  - NVIDIA + AMD Vulkan physical-device identities and selectors;
  - driver/ICD identities;
  - system RAM/page-cache capacity and model backing path;
  - PSU/power/thermal state (sensor availability recorded, values
    retained; stability NOT assessed by the census itself).

Fail closed on ANY drift from the prospectively frozen constants.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import issue241_constants as C

CENSUS_SCHEMA = "inferswarm.issue241.host-census/1"
PCIID_RE = re.compile(r"^[0-9a-f]{4}:[0-9a-f]{4}$")
BDF16_RE = re.compile(r"^[0-9a-f]{8}:[0-9a-f]{2}:[0-9a-f]{2}\.[0-9a-f]$")


def _require(cond: bool, message: str) -> None:
    if not cond:
        raise ValueError(f"census validation failed: {message}")


def identity_problems(arm: str, observed: Any) -> list[str]:
    """Mechanical frozen-subject-identity predicate for one arm's census
    gpu entry. Returns one stable problem string per drifted field (no
    exception, so callers can surface every drift at once)."""
    if arm not in ("B", "C"):
        return [f"identity check requires arm 'B' or 'C', got {arm!r}"]
    cfg = C.REFERENCE_ARM if arm == "B" else C.CANDIDATE_ARM
    problems: list[str] = []
    if not isinstance(observed, dict):
        return [f"{arm} census gpu entry missing (not an object)"]

    # observed field name -> constants key (observed documents use
    # sysfs/census spellings; the constants use arm-config spellings)
    _CFG_KEY = {"driver_in_use": "kernel_driver", "vulkan_icd": "icd"}

    def eq(field: str, transform=None) -> None:
        expected = cfg[_CFG_KEY.get(field, field)]
        value = observed.get(field)
        if transform is not None:
            try:
                value = transform(value)
            except (TypeError, ValueError, AttributeError):
                problems.append(
                    f"{arm} {field} unparseable: {value!r}")
                return
        if value != expected:
            problems.append(
                f"{arm} frozen-identity drift {field}: "
                f"observed {value!r} != frozen {expected!r}")

    eq("vendor_id")
    eq("device_id")
    eq("subsystem_vendor_id")
    eq("subsystem_device_id")
    eq("revision")
    eq("bdf")
    eq("link_width")
    eq("max_link_width")
    eq("max_link_speed")
    eq("driver_in_use", lambda v: v)
    eq("vulkan_icd")
    eq("vulkan_device_name")
    eq("vulkan_device_uuid")
    if arm == "B":
        eq("gpu_uuid")
        eq("pci_id")
    else:
        eq("pci_id")
        vram = observed.get("vram_mib")
        if vram != C.CANDIDATE_VRAM_CENSUS_MIB:
            problems.append(
                f"C frozen-identity drift vram_mib: observed {vram!r} "
                f"!= frozen {C.CANDIDATE_VRAM_CENSUS_MIB!r}")
    # speed is OBSERVED, never frozen (power-management downtraining)
    if "link_speed" in observed and not isinstance(observed.get("link_speed"), str):
        problems.append(f"{arm} link_speed malformed: {observed.get('link_speed')!r}")
    return problems


def validate_census(census: dict[str, Any]) -> dict[str, Any]:
    """Validate a fresh inferswarm01 census against the frozen subject."""
    if not isinstance(census, dict):
        raise ValueError("census must be a JSON object")
    _require(census.get("schema") == CENSUS_SCHEMA, "schema mismatch")
    _require(census.get("host") == "inferswarm01", "census host must be inferswarm01")
    _require(census.get("campaign") == C.CAMPAIGN_ID, "campaign mismatch")

    cpus = census.get("cpu")
    _require(isinstance(cpus, list) and len(cpus) >= 1, "cpu census missing")
    mem = census.get("mem_total_kib")
    _require(isinstance(mem, int) and mem >= 120 * 1024 * 1024,
             "high-RAM host requirement (>=120 GiB) not met")

    gpus = census.get("gpus")
    _require(isinstance(gpus, list) and len(gpus) == 2,
             "exactly two GPUs (one RTX 3060 + one RX 580-class) required")

    by_bdf: dict[str, dict[str, Any]] = {}
    for gpu in gpus:
        if not isinstance(gpu, dict):
            raise ValueError("census validation failed: gpu entry must be an object")
        bdf = gpu.get("bdf")
        if not isinstance(bdf, str) or BDF16_RE.fullmatch(bdf) is None:
            raise ValueError(
                f"census validation failed: gpu bdf {bdf!r} must be the "
                "16-char domain-prefixed form")
        by_bdf[bdf] = gpu

    ref = C.REFERENCE_ARM
    cand = C.CANDIDATE_ARM
    _require(ref["bdf"] in by_bdf, f"reference BDF {ref['bdf']} absent")
    _require(cand["bdf"] in by_bdf, f"candidate BDF {cand['bdf']} absent")

    nv = by_bdf[ref["bdf"]]
    amd = by_bdf[cand["bdf"]]
    # Mechanical frozen-subject-identity predicate (fail-closed on ANY
    # subsystem/revision/BDF/UUID/driver/ICD/Vulkan/link drift; the old
    # "one of x1/x4/x8/x16" link acceptance is replaced by the exact
    # frozen expected-width predicate inside identity_problems).
    problems = [*identity_problems("B", nv), *identity_problems("C", amd)]
    _require(not problems, "; ".join(problems))
    _require(PCIID_RE.fullmatch(amd.get("pci_id") or "") is not None,
             "candidate pci_id must be present as vendor:device")
    _require(isinstance(amd.get("vram_mib"), int) and amd.get("vram_mib") == 8192,
             "candidate VRAM census must be 8192 MiB")

    model = census.get("model_backing")
    _require(isinstance(model, dict), "model backing census missing")
    for member in C.MODEL_MEMBERS:
        entry = model.get(member)
        _require(isinstance(entry, dict), f"model member {member} census missing")
        _require(entry.get("bytes") is not None
                 and int(entry["bytes"]) > 0,
                 f"model member {member} size missing")
        digest = entry.get("sha256")
        _require(digest == C.MODEL_MEMBER_SHA256[member],
                 f"model member {member} sha256 drift")

    power = census.get("power_thermal")
    _require(isinstance(power, dict) and isinstance(
        power.get("sensors_available"), bool),
        "power/thermal sensor availability must be recorded")
    return {
        "schema": "inferswarm.issue241.phase1-census-verdict/1",
        "campaign": C.CAMPAIGN_ID,
        "validated": True,
        "reference_bdf": ref["bdf"],
        "candidate_bdf": cand["bdf"],
        "same_host": census.get("host") == ref["host"] == cand["host"],
        "vram_census_mib": amd.get("vram_mib"),
        "stability_assessed": False,
        "notes": ("identity validation only; stability is assessed by the "
                  "bounded historical-fixture runs, not by this reducer"),
    }


def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("census", type=Path, help="census JSON captured on inferswarm01")
    args = ap.parse_args(argv)
    census = json.loads(args.census.read_text())
    verdict = validate_census(census)
    print(json.dumps(verdict, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
