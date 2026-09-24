#!/usr/bin/env python3
"""Issue #248 (R8-I3A) — exact accepted runtime/device subject identity.

Holds the accepted #241 generation-2 physical subject FIXED for both
arms as machine-readable constants and verifies EVERY relevant frozen
field from FRESH RAW HOST EVIDENCE before any baseline/reference probe
(maintainer NO-GO correction 6: the prelaunch gate previously checked
only UUID/name/BDF/vendor/device and failed open on driver, ICD,
Vulkan, subsystem, revision, and link-identity drift).

Design rules:
  * Frozen constants are ACCEPTED AUTHORITY, never observations. Every
    field the predicate consumes is DERIVED at runtime from raw
    observer bytes by a parser that never reads the constants, then
    compared against them. A missing or malformed raw source fails
    closed.
  * The observer is an INJECTABLE SEAM (``observe_arm_identity``
    production default reads the host read-only; tests inject
    retained-census-shaped raw text) so CPU-only suites can prove the
    fail-closed behavior without a GPU.
  * A changed driver/runtime/device state fails baseline execution
    unless exactly ONE frozen factor is an explicitly declared
    DIAGNOSTIC_ONLY intervention (single-factor; the baseline receipt
    stays in the unit record; two simultaneous factor changes reject).
  * Provenance: the frozen constants restate the accepted #241
    generation-2 freeze (PR #242 head 4e8b4fc, scripts/issue241_
    constants.py REFERENCE_ARM/CANDIDATE_ARM, itself mechanically
    derived from the retained replacement census of 2026-09-24 under
    docs/qualification/qwen38-vulkan-v2-rx580/ on the qualification
    branch). They are cross-checked by
    test_issue248_diagnostic.AnteriorityTests against the retained
    census summary values quoted in the accepted evidence.

Spelling notes (accepted-lesson): sysfs link-width files spell
``Width 16`` and link-speed files ``16.0 GT/s PCIe``; the frozen
constants use the bare canonical forms (``x16``, ``16.0 GT/s``) and
the parser normalizes observed spellings. BDFs are handled in the
16-char domain-prefixed form everywhere. PCI subsystem sysfs files are
hex with the 0x prefix; revision is a 0x-prefixed 32-bit word whose
low byte is the PCI revision.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any


class IdentityError(RuntimeError):
    """Raised when subject identity cannot be verified fail-closed."""


# ---------------------------------------------------------------------------
# Frozen accepted subject identity (generation 2 — READ-ONLY authority)
# ---------------------------------------------------------------------------

IDENTITY_SCHEMA = "inferswarm.issue248.subject-identity/1"

IDENTITY_PROVENANCE = {
    "accepted_campaign_head": "4e8b4fc369defe409f68da46e26d152eade4df47",
    "subject_generation": 2,
    "derived_from": (
        "docs/qualification/qwen38-vulkan-v2-rx580/evidence/"
        "replacement-census-2026-09-24 (accepted #241 branch)"),
    "frozen": ("negotiated link WIDTH + max capability are the frozen "
               "link identity; current link SPEED is downtrainable by "
               "power management and is never a frozen field"),
}

HOST = "inferswarm01"

REFERENCE_IDENTITY = {
    "host": HOST,
    "role": "reference",
    "gpu_uuid": "GPU-d5c05739-96c1-7e49-89b6-bf54c2121c55",
    "bdf": "00000000:03:00.0",
    "pci_id": "10de:2504",
    "subsystem_vendor_id": "1458",
    "subsystem_device_id": "4074",
    "revision": "a1",
    "negotiated_width": "x16",
    "max_width": "x16",
    "max_link_speed_capability": "16.0 GT/s",
    "icd": "/usr/share/vulkan/icd.d/nvidia_icd.json",
    "kernel_driver": "nvidia",
    "nvidia_driver": "610.57.04",
    "vulkan_device_name": "NVIDIA GeForce RTX 3060",
    "vulkan_device_uuid": "d5c05739-96c1-7e49-89b6-bf54c2121c55",
    "vulkan_api": "1.4.341",
    "vulkan_driver": "NVIDIA proprietary 610.57.04",
    "selector": {"GGML_VK_VISIBLE_DEVICES": "0",
                 "CUDA_VISIBLE_DEVICES": "-1"},
}

# Candidate arm C — accepted #241 generation-2 subject (replacement RX
# 580, 2026-09-24 census). Arm-C execution is supported only through the
# same fail-closed identity logic (correction 6 requirement).
CANDIDATE_IDENTITY = {
    "host": HOST,
    "role": "candidate",
    "bdf": "00000000:02:00.0",
    "pci_id": "1002:67df",
    "subsystem_vendor_id": "1da2",
    "subsystem_device_id": "e353",
    "revision": "e7",
    "negotiated_width": "x16",
    "max_width": "x16",
    "max_link_speed_capability": "8.0 GT/s",
    "icd": "/usr/share/vulkan/icd.d/radeon_icd.json",
    "kernel_driver": "amdgpu",
    "vulkan_device_name": "AMD Radeon RX 580 Series (RADV POLARIS10)",
    "vulkan_device_uuid": "00000000-0200-0000-0000-000000000000",
    "vulkan_api": "1.4.305",
    "vulkan_driver": "RADV (Mesa 25.0.7-2+deb13u1)",
    "selector": {"GGML_VK_VISIBLE_DEVICES": "0",
                 "CUDA_VISIBLE_DEVICES": "-1"},
}


def frozen_identity(arm: str) -> dict[str, str]:
    """The frozen identity constants for arm B or C (copy)."""
    if arm == "B":
        return dict(REFERENCE_IDENTITY)
    if arm == "C":
        return dict(CANDIDATE_IDENTITY)
    raise IdentityError(f"unknown arm: {arm!r}")


# Fields verified for every arm, plus the arm-specific additions.
BASE_IDENTITY_FIELDS = (
    "host", "bdf", "pci_id", "subsystem_vendor_id", "subsystem_device_id",
    "revision", "negotiated_width", "max_width",
    "max_link_speed_capability", "icd", "kernel_driver",
    "vulkan_device_name", "vulkan_device_uuid", "vulkan_api",
    "vulkan_driver",
)


def _require_raw(raw: dict[str, Any], key: str) -> Any:
    if key not in raw or raw[key] is None:
        raise IdentityError(f"raw identity source missing: {key}")
    return raw[key]


# ---------------------------------------------------------------------------
# Parsers: raw observation bytes -> derived identity field values.
# Each parser is INDEPENDENT of the frozen constants (a changed value is
# derived and reported, never silently normalized onto the expectation).
# ---------------------------------------------------------------------------

def _parse_nvidia_smi_identity(text: str) -> dict[str, str]:
    """Parse an `nvidia-smi --query-gpu=...` identity line.

    Handles the accepted census capture shape
    (index, uuid, pci.bus_id, name, driver_version, ...) and the short
    (uuid, name, pci.bus_id, driver_version) shape: the uuid field is
    located by its ``GPU-`` prefix and the bus-id field by its
    domain-prefixed BDF shape; every consumed field must be present.
    Empty output fails closed.
    """
    bdf_re = re.compile(r"^[0-9a-f]{8}:[0-9a-f]{2}:[0-9a-f]{2}\.[0-9a-f]$")
    for line in str(text).splitlines():
        fields = [f.strip() for f in line.split(",")]
        uuid_idx = next((i for i, f in enumerate(fields)
                         if f.startswith("GPU-")), None)
        if uuid_idx is None:
            continue
        rest = fields[uuid_idx + 1:]
        if len(rest) < 3:
            break
        if bdf_re.fullmatch(rest[0]):
            bdf, name, driver = rest[0], rest[1], rest[2]
        elif bdf_re.fullmatch(rest[1]):
            name, bdf, driver = rest[0], rest[1], rest[2]
        else:
            break
        return {"gpu_uuid": fields[uuid_idx], "vulkan_device_name": name,
                "bdf": bdf, "nvidia_driver": driver}
    raise IdentityError("nvidia-smi identity line absent or malformed")


def _normalize_width(text: str) -> str:
    # The accepted census spells sysfs link widths as bare lane counts
    # ("16"); lspci-style observers spell "Width 16"; constants use
    # "x16". All normalize to the bare canonical form.
    m = re.fullmatch(r"(?:Width\s+)?x?(\d+)", str(text).strip())
    if not m:
        raise IdentityError(f"unparseable link width: {text!r}")
    return f"x{m.group(1)}"


def _normalize_speed(text: str) -> str:
    m = re.fullmatch(r"([0-9.]+ GT/s)(?:\s+PCIe)?", str(text).strip())
    if not m:
        raise IdentityError(f"unparseable link speed: {text!r}")
    return m.group(1)


def _normalize_revision(text: str) -> str:
    m = re.fullmatch(r"0x([0-9a-fA-F]{1,8})", str(text).strip())
    if not m:
        raise IdentityError(f"unparseable PCI revision: {text!r}")
    value = int(m.group(1), 16)
    if value > 0xFF:
        raise IdentityError(f"PCI revision word carries more than rev: {text!r}")
    return f"{value:x}"


def _normalize_pciid(vendor: str, device: str) -> str:
    def strip(text: str, what: str) -> str:
        m = re.fullmatch(r"0x([0-9a-fA-F]{4})", str(text).strip())
        if not m:
            raise IdentityError(f"unparseable PCI {what}: {text!r}")
        return m.group(1).lower()
    return f"{strip(vendor, 'vendor')}:{strip(device, 'device')}"


def _hex4(text: str, what: str) -> str:
    m = re.fullmatch(r"0x([0-9a-fA-F]{4})", str(text).strip())
    if not m:
        raise IdentityError(f"unparseable PCI {what}: {text!r}")
    return m.group(1).lower()


def _derive_icd_from_inventory(inventory: dict[str, str],
                               vendor_library_marker: str) -> str:
    """Derive the vendor ICD path from a {relpath: content} inventory.

    Selects the unique ``*.json`` entry whose FILENAME begins with the
    vendor marker (``nvidia_icd`` / ``radeon_icd`` — the accepted
    census's inventory shape); zero or multiple matches fail closed.
    Filename selection cannot be fooled by unrelated drivers shipping
    content that merely mentions the marker. The JSON body is still
    parsed and must carry an ``ICD.library_path`` string.
    """
    matches = {rel: content for rel, content in sorted(inventory.items())
               if rel.endswith(".json")
               and rel.startswith(f"{vendor_library_marker}_icd")}
    if len(matches) != 1:
        raise IdentityError(
            f"expected exactly one {vendor_library_marker}_icd JSON in "
            f"inventory, found {len(matches)}")
    rel = next(iter(matches))
    try:
        doc = json.loads(matches[rel])
    except json.JSONDecodeError as exc:
        raise IdentityError(f"ICD inventory entry is not JSON: {rel}") from exc
    if not isinstance(doc.get("ICD", {}).get("library_path"), str):
        raise IdentityError(f"ICD inventory entry lacks library_path: {rel}")
    return f"/usr/share/vulkan/icd.d/{rel}"


def _parse_vulkaninfo_summary(text: str) -> dict[str, str]:
    """Parse a per-ICD `vulkaninfo --summary` device block.

    Returns apiVersion/deviceName/deviceUUID/driver identity. Requires
    the VULKANINFO header, exactly one GPU block, and rc-0-shaped
    content; fails closed otherwise.
    """
    text = str(text)
    if "VULKANINFO" not in text or "Vulkan Instance Version" not in text:
        raise IdentityError("vulkaninfo receipt lacks its header")
    blocks = re.split(r"^GPU\d+:\s*$", text, flags=re.MULTILINE)[1:]
    if len(blocks) != 1:
        raise IdentityError(
            f"expected exactly one Vulkan device block, found {len(blocks)}")
    fields: dict[str, str] = {}
    for line in blocks[0].splitlines():
        m = re.fullmatch(r"\s*(\w+)\s+=\s+(.+?)\s*", line)
        if m:
            fields[m.group(1)] = m.group(2)
    for key in ("apiVersion", "deviceName", "deviceUUID", "driverID",
                "driverInfo"):
        if key not in fields:
            raise IdentityError(f"vulkaninfo field missing: {key}")
    return fields


def _vulkan_driver_value(fields: dict[str, str]) -> str:
    """Canonical vulkan_driver string from driverID/driverInfo."""
    driver_id, info = fields["driverID"], fields["driverInfo"]
    if driver_id == "DRIVER_ID_NVIDIA_PROPRIETARY":
        return f"NVIDIA proprietary {info}"
    if driver_id == "DRIVER_ID_MESA_RADV":
        return f"RADV (Mesa {info})"
    raise IdentityError(f"unexpected Vulkan driverID: {driver_id!r}")


def derive_identity_from_raw(arm: str, raw: dict[str, Any]) -> dict[str, Any]:
    """Derive every frozen identity field from raw observation bytes.

    Fails closed on any missing/malformed source. Never reads the
    frozen constants: a drifted field derives to its NEW value and is
    then reported by :func:`identity_problems`.
    """
    frozen = frozen_identity(arm)  # arm/role shape only, no field reads
    bdf = str(_require_raw(raw, "bdf"))  # observed/selected device address
    prefix = "sysfs."
    derived: dict[str, Any] = {"host": _require_raw(raw, "host"),
                               "bdf": str(bdf)}
    vendor = _require_raw(raw, prefix + "vendor")
    device = _require_raw(raw, prefix + "device")
    derived["pci_id"] = _normalize_pciid(vendor, device)
    derived["subsystem_vendor_id"] = _hex4(
        _require_raw(raw, prefix + "subsystem_vendor"), "subsystem vendor")
    derived["subsystem_device_id"] = _hex4(
        _require_raw(raw, prefix + "subsystem_device"), "subsystem device")
    derived["revision"] = _normalize_revision(
        _require_raw(raw, prefix + "revision"))
    derived["negotiated_width"] = _normalize_width(
        _require_raw(raw, prefix + "current_link_width"))
    derived["max_width"] = _normalize_width(
        _require_raw(raw, prefix + "max_link_width"))
    derived["max_link_speed_capability"] = _normalize_speed(
        _require_raw(raw, prefix + "max_link_speed"))
    derived["kernel_driver"] = str(_require_raw(raw, "sysfs.driver"))
    if arm == "B":
        smi = _parse_nvidia_smi_identity(_require_raw(raw, "nvidia-smi"))
        # The sysfs address and the nvidia-smi bus id are two channels
        # for the SAME fact: they must AGREE. Neither overwrites the
        # other (a BDF drift hidden by a later update would be exactly
        # the fail-open being corrected).
        if smi["bdf"] != str(bdf):
            raise IdentityError(
                f"device address disagreement: sysfs {bdf} != nvidia-smi "
                f"{smi['bdf']}")
        derived.update(smi)
    icd = _derive_icd_from_inventory(
        dict(_require_raw(raw, "icd_inventory")),
        "nvidia" if arm == "B" else "radeon")
    derived["icd"] = icd
    vulkan_receipt = _require_raw(raw, "vulkaninfo")
    # Cross-bind: the vulkaninfo receipt must have been produced by the
    # derived ICD (the receipt carries the file text it was invoked on).
    receipt_icd = str(vulkan_receipt.get("icd_path", ""))
    if receipt_icd != icd:
        raise IdentityError(
            "vulkaninfo receipt was not produced by the derived ICD: "
            f"{receipt_icd!r} != {icd!r}")
    fields = _parse_vulkaninfo_summary(vulkan_receipt.get("stdout", ""))
    derived["vulkan_api"] = fields["apiVersion"]
    derived["vulkan_device_name"] = fields["deviceName"]
    derived["vulkan_device_uuid"] = fields["deviceUUID"]
    derived["vulkan_driver"] = _vulkan_driver_value(fields)
    if arm == "B":
        # The Vulkan UUID and the NVIDIA GPU UUID must be the same
        # hardware identity modulo the GPU- prefix (cross-binding).
        if not derived["gpu_uuid"].endswith(derived["vulkan_device_uuid"]):
            raise IdentityError(
                "Vulkan deviceUUID does not cross-bind to the NVIDIA "
                "GPU UUID")
    return derived


# ---------------------------------------------------------------------------
# Fail-closed predicate
# ---------------------------------------------------------------------------

def identity_problems(arm: str, observation: dict[str, Any]) -> list[str]:
    """Every frozen identity drift in one raw observation, fail-closed.

    Returns a list of problems (empty == verified). Missing raw sources
    and malformed bytes are problems, never silent passes.
    """
    problems: list[str] = []
    raw = observation.get("raw") if isinstance(observation, dict) else None
    if not isinstance(raw, dict):
        return [f"identity observation carries no raw block (arm {arm})"]
    try:
        derived = derive_identity_from_raw(arm, raw)
    except IdentityError as exc:
        return [f"identity derivation failed: {exc}"]
    frozen = frozen_identity(arm)
    for field in BASE_IDENTITY_FIELDS + (
            ("gpu_uuid", "nvidia_driver") if arm == "B" else ()):
        expected = frozen.get(field)
        observed = derived.get(field)
        if observed is None:
            problems.append(f"{field}: not derived from raw evidence")
        elif observed != expected:
            problems.append(
                f"{field}: drift (observed {observed!r} != frozen "
                f"{expected!r})")
    return problems


# ---------------------------------------------------------------------------
# Single-factor DIAGNOSTIC_ONLY intervention mode
# ---------------------------------------------------------------------------

def intervention_problems(arm: str, observation: dict[str, Any],
                          intervention: dict[str, Any] | None
                          ) -> list[str]:
    """Validate one declared single-factor intervention.

    ``intervention`` is None (no intervention, full frozen equality) or
    {"field": <frozen field>, "expected_value": <the one deliberately
    changed value>}. Exactly one field may differ; anything else fails
    closed (two-factor changes reject).
    """
    if intervention is None:
        return identity_problems(arm, observation)
    if not isinstance(intervention, dict):
        return ["intervention declaration is not a dict"]
    field = intervention.get("field")
    expected_value = intervention.get("expected_value")
    frozen = frozen_identity(arm)
    if field not in frozen or field in ("host", "role"):
        return [f"intervention field is not an intervenable frozen "
                f"identity field: {field!r}"]
    if expected_value is None or expected_value == frozen[field]:
        return ["intervention must declare a value that DIFFERS from "
                "the frozen authority"]
    problems: list[str] = []
    raw = observation.get("raw") if isinstance(observation, dict) else None
    if not isinstance(raw, dict):
        return ["identity observation carries no raw block"]
    try:
        derived = derive_identity_from_raw(arm, raw)
    except IdentityError as exc:
        return [f"identity derivation failed: {exc}"]
    for other in BASE_IDENTITY_FIELDS + (
            ("gpu_uuid", "nvidia_driver") if arm == "B" else ()):
        if other == field:
            continue
        observed = derived.get(other)
        if observed is None:
            problems.append(f"{other}: not derived from raw evidence")
        elif observed != frozen[other]:
            problems.append(
                f"{other}: drift outside the declared intervention "
                f"(observed {observed!r} != frozen {frozen[other]!r})")
    observed = derived.get(field)
    if observed != expected_value:
        problems.append(
            f"{field}: observed {observed!r} != declared intervention "
            f"value {expected_value!r}")
    return problems


# ---------------------------------------------------------------------------
# Production observer (read-only host reads; injectable in tests)
# ---------------------------------------------------------------------------

def _sysfs(bdf: str, rel: str) -> str:
    path = Path("/sys/bus/pci/devices") / bdf / rel
    if path.is_symlink() or not path.is_file():
        raise IdentityError(f"sysfs source missing: {path}")
    return path.read_text().strip()


def observe_arm_identity(arm: str) -> dict[str, Any]:
    """Fresh READ-ONLY raw identity observation for the executing arm.

    sysfs + nvidia-smi (arm B) + ICD inventory + per-ICD vulkaninfo.
    No GPU compute, no model reads, no dispatch machinery.
    """
    if arm not in ("B", "C"):
        raise IdentityError(f"unknown arm: {arm!r}")
    bdf = frozen_identity(arm)["bdf"]  # the ADDRESS to observe (selection)
    raw: dict[str, Any] = {"host": HOST, "bdf": bdf}
    for rel in ("vendor", "device", "subsystem_vendor", "subsystem_device",
                "revision", "current_link_width", "max_link_width",
                "max_link_speed"):
        raw[f"sysfs.{rel}"] = _sysfs(bdf, rel)
    driver_link = Path("/sys/bus/pci/devices") / bdf / "driver"
    if not driver_link.is_symlink():
        raise IdentityError(f"kernel driver link missing for {bdf}")
    raw["sysfs.driver"] = driver_link.resolve().name
    if arm == "B":
        smi = subprocess.run(
            ["nvidia-smi", "--query-gpu=uuid,name,pci.bus_id,driver_version",
             "--format=csv,noheader"], capture_output=True, text=True,
            timeout=15)
        if smi.returncode != 0:
            raise IdentityError(f"nvidia-smi failed: {smi.stderr.strip()}")
        raw["nvidia-smi"] = smi.stdout
    marker = "nvidia" if arm == "B" else "radeon"
    icd_dir = Path("/usr/share/vulkan/icd.d")
    inventory = {}
    for p in sorted(icd_dir.glob("*.json")):
        inventory[p.name] = p.read_text()
    if not inventory:
        raise IdentityError("ICD inventory is empty")
    raw["icd_inventory"] = inventory
    icd = _derive_icd_from_inventory(inventory, marker)
    env = {**{k: v for k, v in __import__("os").environ.items()
              if not k.startswith(("VK_", "VK_ICD"))},
           "VK_DRIVER_FILES": icd}
    proc = subprocess.run(["vulkaninfo", "--summary"], capture_output=True,
                          text=True, timeout=60, env=env)
    raw["vulkaninfo"] = {"icd_path": icd, "stdout": proc.stdout,
                         "stderr": proc.stderr, "rc": proc.returncode}
    if proc.returncode != 0:
        raise IdentityError(
            f"vulkaninfo --summary failed via {icd}: "
            f"{proc.stderr.strip()[:200]}")
    return {"schema": IDENTITY_SCHEMA, "arm": arm, "raw": raw}
