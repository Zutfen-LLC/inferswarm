"""#252 prospective mechanism-localization contracts per frozen arm.

Each arm's terminal-capability is defined NOW, from the pinned llama.cpp
source b29c606e, before any physical execution. An arm can only localize a
terminal if retained, digest-bound RAW observations prove the named
intervention actually changed the intended Vulkan-side runtime path -- never
a narrative label, boolean, or the mere presence of an environment variable.

Source-grounded seam map (all lines at pin b29c606e, ggml-vulkan.cpp):
- A1 serialize_submissions: set at :7435; the serialized wait at :18105
  waitForFences emits NO retained observable. => NON-TERMINAL-CAPABLE.
- A2 GGML_VK_DISABLE_COOPMAT gates ONLY the KHR cooperative-matrix feature
  (:6600). The device enumeration line (:7695) prints the resulting matrix
  core family per device. Runtime liveness is provable: the retained per-unit
  server.log must show the device line with a NON-KHR matrix-core family.
- A3 GGML_VK_DISABLE_ASYNC flips support_async (:6722) and the disabled state
  emits the exact stderr line (:6727) "Async execution disabled on certain
  Intel devices." => retained marker line proves async backend disabled.
- A4/A5 allocation paths: ggml_vk_create_buffer_device (:3810-3845) selects
  host-visible vs device-local by prefer_host_memory /
  disable_host_visible_vidmem; the VK memory logger (:7789 enable, :2757
  allocation lines) records each allocation as "device" or "host" typed.
  Weight loads reach the GPU through the staged copy path exactly when the
  buffer is NOT host-visible (ggml_vk_buffer_write_2d :3779/:8748 fallback
  via ggml_vk_ensure_sync_staging_buffer :8755, logged at :8603).

All schemas are frozen here; the reducer consumes only retained bytes that
match them, and mutation tests flip one retained byte at a time.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

MECHANISM_TRACE_SCHEMA = "inferswarm.issue252.mechanism-observation/1"

ASYNC_DISABLED_MARKER = "Async execution disabled on certain Intel devices."
DEVICE_LINE_PREFIX = "ggml_vulkan: "
MATRIX_CORES_FIELD = re.compile(r"matrix cores: (\S+)")
MEMORY_ALLOCATION = re.compile(
    r"^ggml_vulkan memory: [^:]+: \+[0-9.]+ [KMG]?i?B (device|host) at 0x[0-9a-f]+")
SYNC_STAGING_LINE = "ggml_vk_ensure_sync_staging_buffer("

# Matrix-core families reported by the enumeration line at the pin
# (ggml-vulkan.cpp:7678): only "KHR_coopmat" derives from the KHR
# cooperative-matrix feature that GGML_VK_DISABLE_COOPMAT gates (:6600).
KHR_FAMILY = "KHR_coopmat"


class MechanismInvalid(ValueError):
    """Retained mechanism observations do not prove this arm's intervention."""


def _load(root: Path, rel: str) -> bytes:
    path = Path(root) / rel
    if path.is_symlink() or not path.is_file():
        raise MechanismInvalid(f"retained mechanism artifact missing/unsafe: {rel}")
    return path.read_bytes()


def _json(root: Path, rel: str) -> dict[str, Any]:
    try:
        doc = json.loads(_load(root, rel))
    except json.JSONDecodeError as exc:
        raise MechanismInvalid(f"retained mechanism JSON malformed: {rel}") from exc
    if not isinstance(doc, dict):
        raise MechanismInvalid(f"retained mechanism object missing: {rel}")
    return doc


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _arm_units(root: Path, namespace: str) -> list[Path]:
    base = Path(root) / namespace
    if base.is_symlink() or not base.is_dir():
        raise MechanismInvalid(f"arm namespace absent/unsafe: {namespace}")
    return sorted(p for p in base.iterdir() if p.is_dir() and not p.is_symlink())


def _unit_server_log(unit: Path) -> str:
    raw = _load(unit, "server.log")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise MechanismInvalid("retained server log is not UTF-8") from exc


# --- per-arm retained-observation validators --------------------------------

def _mechanism_a2(root: Path, namespace: str) -> dict[str, Any]:
    """A2: coopmat feature/path disabled for the measured execution.

    Law: the subject device's retained enumeration line must report a
    NON-KHR_coopmat matrix-core family in EVERY retained unit, proving the
    KHR cooperative-matrix feature detection was disabled at runtime. The
    pre-existing accepted capability line for this RTX 3060 subject records
    NV_coopmat2, which is NOT gated by GGML_VK_DISABLE_COOPMAT: if the
    retained line still shows NV_coopmat2, the intervention was live for KHR
    detection but the report must record that the KHR path was absent in both
    states (dead control on this subject), and localization is refused.
    """
    families = []
    for unit in _arm_units(root, namespace):
        log = _unit_server_log(unit)
        lines = [l for l in log.splitlines() if "matrix cores: " in l]
        if not lines:
            raise MechanismInvalid(
                "A2 retained server log lacks the device enumeration line")
        for line in lines:
            match = MATRIX_CORES_FIELD.search(line)
            if not match:
                raise MechanismInvalid("A2 enumeration line lacks matrix-cores field")
            families.append(match.group(1))
    if not families:
        raise MechanismInvalid("A2 no retained matrix-core observations")
    if any(f == KHR_FAMILY for f in families):
        raise MechanismInvalid(
            "A2 retained observation shows KHR coopmat still active; "
            "intervention not proven")
    # Dead-control honesty: on a subject whose active matrix-core family is
    # NV_coopmat2 (not gated by GGML_VK_DISABLE_COOPMAT), the KHR gate did
    # not change the selected path, so no bounded mechanism is established.
    if all(f != KHR_FAMILY for f in families) and any(
            f.startswith("NV_coopmat") for f in families):
        raise MechanismInvalid(
            "A2 dead control on this subject: active family is NV_coopmat2, "
            "not gated by GGML_VK_DISABLE_COOPMAT; no bounded mechanism")
    return {"arm": "A2", "families": sorted(set(families)),
            "mechanism": "KHR cooperative-matrix feature detection disabled "
                         "at runtime (enumeration line retained)"}


def _mechanism_a3(root: Path, namespace: str) -> dict[str, Any]:
    """A3: async backend behavior disabled for the measured execution.

    Law: every retained unit's server.log must contain the exact stderr
    marker the pin emits when support_async is false (:6727).
    """
    for unit in _arm_units(root, namespace):
        log = _unit_server_log(unit)
        if ASYNC_DISABLED_MARKER not in log:
            raise MechanismInvalid(
                "A3 retained server log lacks the async-disabled marker line")
    return {"arm": "A3",
            "mechanism": "backend async interface disabled at runtime "
                         "(exact disabled-marker line retained in every unit)"}


def _memory_allocation_types(root: Path, namespace: str) -> dict[str, int]:
    """Tally device/host allocation-type lines across retained units."""
    tally: dict[str, int] = {"device": 0, "host": 0}
    for unit in _arm_units(root, namespace):
        log = _unit_server_log(unit)
        for line in log.splitlines():
            match = MEMORY_ALLOCATION.match(line)
            if match:
                tally[match.group(1)] += 1
    return tally


def _mechanism_a4(root: Path, namespace: str) -> dict[str, Any]:
    """A4: host-memory preference materially selected the tested path.

    Law: the memory logger must record at least one HOST-typed allocation in
    the retained units (the intervention's intended effect: coherent
    host-visible allocation preferred at :3812) AND at least one DEVICE-typed
    allocation (the Vulkan compute path itself stayed on device memory;
    placement.json already proves output projection on Vulkan).
    """
    tally = _memory_allocation_types(root, namespace)
    if tally["host"] < 1:
        raise MechanismInvalid(
            "A4 no host-typed allocation retained; preference did not "
            "materially select host-visible memory")
    if tally["device"] < 1:
        raise MechanismInvalid(
            "A4 no device-typed allocation retained; Vulkan path absent")
    return {"arm": "A4", "allocations": tally,
            "mechanism": "coherent host-visible allocation materially "
                         "selected (host-typed allocation lines retained) "
                         "while Vulkan compute placement remained active"}


def _mechanism_a5(root: Path, namespace: str) -> dict[str, Any]:
    """A5: host-visible VRAM disabled; device-local path selected.

    Law: with host-visible VRAM disabled and no sysmem fallback, weight
    buffers are NOT host-visible, so weight uploads must route through the
    staged copy path: every retained unit's server.log must contain the
    sync-staging line (:8603) AND zero host-typed allocation lines must
    appear for the weight buffers (all allocations device-typed).
    """
    tally = _memory_allocation_types(root, namespace)
    for unit in _arm_units(root, namespace):
        log = _unit_server_log(unit)
        if SYNC_STAGING_LINE not in log:
            raise MechanismInvalid(
                "A5 retained server log lacks the sync-staging allocation "
                "line; device-local-only path not evidenced")
    if tally["host"] > 0:
        raise MechanismInvalid(
            "A5 host-typed allocation retained; host-visible VRAM not "
            "disabled as claimed")
    if tally["device"] < 1:
        raise MechanismInvalid("A5 no device-typed allocation retained")
    return {"arm": "A5", "allocations": tally,
            "mechanism": "host-visible VRAM disabled and device-local path "
                         "selected (staged upload lines retained, zero "
                         "host-typed allocations)"}


# A1: GGML_VK_SERIALIZE_SUBMISSIONS sets device->serialize_submissions
# (:7435) and the serialized submission path waits on the device fence
# (:18105), but the pin emits NO retained observable distinguishing a
# serialized submission from an unfenced batch. Marking it here (not in the
# reducer's control flow) keeps the reason auditable and testable.
NON_TERMINAL_CAPABLE = {
    "A1": "no retained submission-serialization observable exists at pin "
          "b29c606e; the serialized wait path emits no distinguishable "
          "retained bytes",
}

MECHANISM_VALIDATORS = {
    "A2": _mechanism_a2,
    "A3": _mechanism_a3,
    "A4": _mechanism_a4,
    "A5": _mechanism_a5,
}


def mechanism_status(root: Path, arm: str, namespace: str) -> dict[str, Any]:
    """Derive the retained mechanism facts for one arm. Fail closed.

    Returns {"capable": bool, "facts": dict} — never a caller boolean. For a
    non-terminal-capable arm the status is {"capable": False, reason} and no
    retained observation can localize through this arm.
    """
    if arm in NON_TERMINAL_CAPABLE:
        return {"capable": False, "arm": arm, "reason": NON_TERMINAL_CAPABLE[arm]}
    validator = MECHANISM_VALIDATORS.get(arm)
    if validator is None:
        raise MechanismInvalid(f"no prospective mechanism contract for arm {arm}")
    facts = validator(root, namespace)
    # Determinism contrast stays SEPARATE: these facts prove only that the
    # named intervention changed the intended Vulkan-side runtime path.
    return {"capable": True, "arm": arm, "facts": facts}
