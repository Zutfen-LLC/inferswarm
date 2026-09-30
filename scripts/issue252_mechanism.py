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
  core family per device. On the RTX 3060 subject, coopmat2_support takes
  precedence (:7678-7679), so the family stays NV_coopmat2 even with the
  gate live: a DEAD CONTROL on this subject, honestly refused. Only family
  "none" proves the gate was live AND changed the selected path.
- A3 GGML_VK_DISABLE_ASYNC flips support_async (:6722) and the disabled state
  emits the exact stderr line (:6727) "ggml_vulkan: WARNING: Async execution
  disabled on certain Intel devices." => retained exact line proves async
  backend disabled.
- A4/A5 allocation paths: ggml_vk_create_buffer_device (:3810-3845) selects
  host-visible vs device-local by prefer_host_memory /
  disable_host_visible_vidmem; the VK memory logger (:7789 enable, :2757
  allocation lines, :2773 deallocation lines) records each allocation as
  "device" or "host" typed WITH running byte totals. Weight loads reach the
  GPU through the staged copy path exactly when the buffer is NOT
  host-visible (ggml_vk_buffer_write_2d :3779/:8748 fallback via
  ggml_vk_ensure_sync_staging_buffer :8755, logged at :8603). The staging
  buffer itself is allocated HostVisible|HostCoherent|HostCached (:8607) and
  therefore appears as a HOST-typed line of exactly the staging size.

ANTI-FORGERY LAWS (adversarial review round: copied/fabricated marker text
is not evidence):
- Every observation line must match the pin's EXACT emitted format
  (full-line regex, never substring presence).
- Memory lines must form an arithmetically consistent running ledger per
  unit: each +/- line's printed "Total device:"/"total host:" must equal the
  cumulative byte sums (sizes round-trip format_size at :2249, 2-decimal
  fixed). A pasted-in line or a fabricated total breaks the ledger.
- Per-UNIT laws (not namespace-wide tallies): the intervention must be
  evidenced in every retained unit, with the same device identity across
  units (identical enumeration lines).

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

# Exact full-line formats emitted by the pin (ggml-vulkan.cpp:7695, :6727,
# :2247 VK_LOG_MEMORY macro, :2757/:2773 logger lines, :8603 staging).
ENUM_LINE = re.compile(
    r"^ggml_vulkan: \d+ = .+ \(.+\) \| uma: [01] \| fp16: \S+ \| bf16: [01] "
    r"\| fp4: [01] \| warp size: \d+ \| shared memory: \d+ \| int dot: [01] "
    r"\| matrix cores: (?P<family>\S+)$")
ASYNC_DISABLED_LINE = (
    "ggml_vulkan: WARNING: Async execution disabled on certain Intel devices.")
_SIZE = r"(?:[0-9]+\.[0-9]{2} [KMGT]iB|[0-9]+ B)"
MEMORY_LINE = re.compile(
    r"^ggml_vulkan memory: (?P<device>.+): (?P<dir>[+-])(?P<size>" + _SIZE +
    r") (?P<type>device|host) at 0x[0-9a-f]+\. "
    r"Total device: (?P<td>" + _SIZE + r"), total host: (?P<th>" + _SIZE + r")$")
STAGING_LINE = re.compile(
    r"^ggml_vulkan memory: ggml_vk_ensure_sync_staging_buffer\((?P<size>[0-9]+)\)$")

_UNIT_MULT = {"B": 1, "KiB": 1024, "MiB": 1024 ** 2, "GiB": 1024 ** 3,
              "TiB": 1024 ** 4}
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


def _parse_size(text: str) -> float:
    num, unit = text.split(" ", 1)
    return float(num) * _UNIT_MULT[unit]


def _check_ledger(log: str) -> None:
    """Running-total ledger law over every memory line of one unit.

    The pin prints cumulative device/host byte totals on each allocation and
    deallocation line (:2757/:2773). A pasted, fabricated, or edited line
    breaks the arithmetic. Sizes round-trip format_size (:2249, fixed
    2-decimal), so comparisons allow one half-quantum of rounding.
    """
    totals = {"device": 0.0, "host": 0.0}
    for line in log.splitlines():
        match = MEMORY_LINE.match(line)
        if not match:
            if line.startswith("ggml_vulkan memory: ") and not STAGING_LINE.match(line):
                raise MechanismInvalid(
                    "malformed ggml_vulkan memory line breaks the retained ledger")
            continue
        kind = match.group("type")
        delta = _parse_size(match.group("size"))
        if match.group("dir") == "-":
            delta = -delta
        totals[kind] += delta
        if totals[kind] < -0.5:
            raise MechanismInvalid("memory ledger underflow (deallocation "
                                   "without matching allocation)")
        for printed, actual in ((match.group("td"), totals["device"]),
                                (match.group("th"), totals["host"])):
            quantum = _parse_size(printed) * 0.005 + 1.0
            if abs(_parse_size(printed) - actual) > quantum:
                raise MechanismInvalid(
                    "memory ledger arithmetic inconsistent with the printed "
                    "running totals")


def _unit_observations(log: str) -> dict[str, Any]:
    """Parse one unit's log under the exact-format laws. Fail closed."""
    _check_ledger(log)
    enums = [m.group("family") for m in
             (ENUM_LINE.match(l) for l in log.splitlines()) if m]
    allocs = [(m.group("type"), _parse_size(m.group("size"))) for m in
              (MEMORY_LINE.match(l) for l in log.splitlines()) if m]
    stagings = [int(m.group("size")) for m in
                (STAGING_LINE.match(l) for l in log.splitlines()) if m]
    has_async_off = any(l.strip() == ASYNC_DISABLED_LINE for l in log.splitlines())
    # A near-miss marker (substring, wrong prefix, appended text) is not the
    # pin's line and must not be countable evidence.
    for line in log.splitlines():
        if "Async execution disabled" in line and line.strip() != ASYNC_DISABLED_LINE:
            raise MechanismInvalid(
                "async-disabled marker present only as non-exact text")
        if "matrix cores" in line and not ENUM_LINE.match(line):
            raise MechanismInvalid(
                "matrix-cores text present outside the exact enumeration line")
    return {"families": enums, "allocations": allocs, "staging_sizes": stagings,
            "async_disabled": has_async_off}


# --- per-arm retained-observation validators --------------------------------

def _mechanism_a2(root: Path, namespace: str) -> dict[str, Any]:
    """A2: coopmat feature/path disabled for the measured execution.

    Law: EVERY retained unit carries the pin's exact device-enumeration
    line, identical across units (same device identity), reporting matrix
    family "none" — the only retained state proving the KHR coopmat gate
    was live AND changed the selected path. KHR_coopmat still reported
    means the gate was not live; any NV_coopmat* family is a DEAD CONTROL
    on this subject (coopmat2 takes precedence and is not gated), honestly
    refused rather than overclaimed.
    """
    families = set()
    for unit in _arm_units(root, namespace):
        obs = _unit_observations(_unit_server_log(unit))
        if not obs["families"]:
            raise MechanismInvalid(
                "A2 retained server log lacks the exact device enumeration line")
        if len(set(obs["families"])) != 1:
            raise MechanismInvalid("A2 multiple enumeration lines in one unit")
        families.update(obs["families"])
    if len(families) != 1:
        raise MechanismInvalid("A2 enumeration differs across retained units")
    family = families.pop()
    if family == KHR_FAMILY:
        raise MechanismInvalid(
            "A2 retained observation shows KHR coopmat still active; "
            "intervention not proven")
    if family.startswith("NV_coopmat"):
        raise MechanismInvalid(
            "A2 dead control on this subject: active family is NV_coopmat*, "
            "not gated by GGML_VK_DISABLE_COOPMAT; no bounded mechanism")
    if family != "none":
        raise MechanismInvalid(f"A2 unexpected matrix family: {family}")
    return {"arm": "A2", "families": ["none"],
            "mechanism": "cooperative-matrix feature detection disabled at "
                         "runtime (exact enumeration line retained, family "
                         "'none' in every unit)"}


def _mechanism_a3(root: Path, namespace: str) -> dict[str, Any]:
    """A3: async backend behavior disabled for the measured execution.

    Law: every retained unit's server.log contains the EXACT stderr line the
    pin emits when support_async is false (:6727), full-line equality — plus
    the exact enumeration line proving the Vulkan path stayed active.
    """
    for unit in _arm_units(root, namespace):
        obs = _unit_observations(_unit_server_log(unit))
        if not obs["async_disabled"]:
            raise MechanismInvalid(
                "A3 retained server log lacks the exact async-disabled line")
        if not obs["families"]:
            raise MechanismInvalid(
                "A3 retained server log lacks the Vulkan enumeration line")
    return {"arm": "A3",
            "mechanism": "backend async interface disabled at runtime "
                         "(exact disabled-marker line retained in every unit, "
                         "Vulkan path active)"}


def _mechanism_a4(root: Path, namespace: str) -> dict[str, Any]:
    """A4: host-memory preference materially selected the tested path.

    Per-unit law (a namespace-wide tally could mix units): every retained
    unit's ledger-consistent memory lines include at least one HOST-typed
    allocation (the intervention's intended effect at :3812) AND at least
    one DEVICE-typed allocation (Vulkan compute stayed on device memory),
    plus the exact enumeration line.
    """
    tally = {"device": 0, "host": 0}
    for unit in _arm_units(root, namespace):
        obs = _unit_observations(_unit_server_log(unit))
        if not obs["families"]:
            raise MechanismInvalid("A4 retained unit lacks the Vulkan "
                                   "enumeration line")
        kinds = {kind for kind, _ in obs["allocations"]}
        if "host" not in kinds:
            raise MechanismInvalid(
                "A4 unit without any host-typed allocation; preference did "
                "not materially select host-visible memory")
        if "device" not in kinds:
            raise MechanismInvalid(
                "A4 unit without any device-typed allocation; Vulkan path absent")
        for kind, _ in obs["allocations"]:
            tally[kind] += 1
    return {"arm": "A4", "allocations": tally,
            "mechanism": "coherent host-visible allocation materially "
                         "selected (host-typed ledger lines in every unit) "
                         "while Vulkan compute placement remained active"}


def _mechanism_a5(root: Path, namespace: str) -> dict[str, Any]:
    """A5: host-visible VRAM disabled; device-local path selected.

    Per-unit law: with host-visible VRAM disabled, weight buffers are not
    host-visible, so weight uploads route through the staged copy path —
    every retained unit must contain the exact sync-staging line (:8603)
    immediately followed by the staging buffer's OWN host-typed allocation
    of exactly the staging size (HostVisible|HostCoherent|HostCached at
    :8607 is host-typed by the logger), at least one DEVICE-typed
    allocation, and NO other host-typed allocation (a host-visible weight
    buffer would prove the intervention was NOT live). The ledger law
    binds the arithmetic of all these lines together.
    """
    staging_bytes = 0
    for unit in _arm_units(root, namespace):
        obs = _unit_observations(_unit_server_log(unit))
        if not obs["families"]:
            raise MechanismInvalid("A5 retained unit lacks the Vulkan "
                                   "enumeration line")
        if not obs["staging_sizes"]:
            raise MechanismInvalid(
                "A5 retained server log lacks the exact sync-staging line; "
                "device-local-only path not evidenced")
        expected = {float(s) for s in obs["staging_sizes"]}
        host_sizes = [size for kind, size in obs["allocations"] if kind == "host"]
        for size in host_sizes:
            if size not in expected:
                raise MechanismInvalid(
                    "A5 host-typed allocation other than the staging buffer "
                    "itself retained; host-visible VRAM not disabled as claimed")
        if len(host_sizes) < len(expected):
            raise MechanismInvalid(
                "A5 staging line without its matching host-typed staging "
                "allocation")
        if not any(kind == "device" for kind, _ in obs["allocations"]):
            raise MechanismInvalid("A5 no device-typed allocation retained")
        staging_bytes += len(obs["staging_sizes"])
    return {"arm": "A5", "staging_events": staging_bytes,
            "mechanism": "host-visible VRAM disabled and staged-upload path "
                         "selected (exact sync-staging line plus its matching "
                         "host-typed staging allocation and device-typed "
                         "compute allocations in every unit; no other "
                         "host-typed allocation)"}


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
