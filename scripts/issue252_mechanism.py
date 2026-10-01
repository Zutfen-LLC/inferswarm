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
# The pin's informational memory-prefixed lines (:8221 host_malloc,
# :8244 host_free, :15944/:15952/:15963/:15971 preallocate_buffers,
# :16723 buffer_free_buffer, :16859 buffer_type_alloc_buffer,
# :16909/:16914 host buffer free/alloc, :2776 ERROR deallocation).
# They carry NO allocation/deallocation bytes: the ledger must ignore them,
# and a near-miss of them (same prefix family, unlisted name/format) is a
# malformed retained line, never silently skipped evidence.
_INFO_MEMORY = (
    "ggml_vulkan memory: ggml_vk_host_malloc(",
    "ggml_vulkan memory: ggml_vk_host_free(",
    "ggml_vulkan memory: ggml_vk_preallocate_buffers(",
    "ggml_vulkan memory: ggml_backend_vk_buffer_free_buffer()",
    "ggml_vulkan memory: ggml_backend_vk_buffer_type_alloc_buffer(",
    "ggml_vulkan memory: ggml_backend_vk_host_buffer_free_buffer()",
    "ggml_vulkan memory: ggml_backend_vk_host_buffer_type_alloc_buffer(",
)
_ERROR_MEMORY_PREFIX = "ggml_vulkan memory: ERROR "

# One-factor subject-capability law (frozen HOST_FACTS, accepted #248/#250
# preflight): the frozen subject reports the NV_coopmat2 matrix-core family.
# A2/A5/A3 do not gate cooperative-matrix detection, so an arm whose control
# cannot change the family must retain the frozen family in every unit; any
# other family under those arms proves a second factor moved (wrong device,
# doctored log, or non-one-factor run).
SUBJECT_ENUM_FAMILY = "NV_coopmat2"

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


def _is_known_info_line(line: str) -> bool:
    """Exact prefix-family membership for the pin's informational lines.

    The informational formats are function-name + '(' + digits/sizes + ')'
    (or exactly '()'). A line sharing the 'ggml_vulkan memory:' prefix but
    not matching any pin-emitted format is a malformed/near-miss retained
    line and must fail closed.
    """
    if line.startswith(_ERROR_MEMORY_PREFIX):
        return True
    for prefix in _INFO_MEMORY:
        if not line.startswith(prefix):
            continue
        rest = line[len(prefix):]
        if rest == ")":
            return True  # exactly '()' variants
        if not rest.endswith(")"):
            return False
        inner = rest[:-1]
        if prefix.endswith("()"):  # constant-form prefix already consumed
            return False
        # digits, optional suffix label before the value (x_size: 524288)
        inner = inner.split(":")[-1].strip() if ":" in inner else inner
        return inner.isdigit()
    return False


def _check_ledger(log: str) -> None:
    """Running-total ledger law over every memory line of one unit.

    The pin prints cumulative device/host byte totals on each allocation and
    deallocation line (:2757/:2773). A pasted, fabricated, or edited line
    breaks the arithmetic. Sizes round-trip format_size (:2249, fixed
    2-decimal), so comparisons allow one half-quantum of rounding. The
    pin's informational memory-prefixed lines carry no ledger bytes and are
    skipped; any OTHER line sharing the memory prefix is malformed retained
    evidence and fails closed.
    """
    totals = {"device": 0.0, "host": 0.0}
    for line in log.splitlines():
        match = MEMORY_LINE.match(line)
        if not match:
            if (line.startswith("ggml_vulkan memory: ")
                    and not STAGING_LINE.match(line)
                    and not _is_known_info_line(line)):
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
    lines = log.splitlines()
    enums = [m.group("family") for m in
             (ENUM_LINE.match(l) for l in lines) if m]
    if len(enums) > 1:
        raise MechanismInvalid(
            "multiple device enumeration lines in one unit; the frozen "
            "one-device launch emits exactly one")
    ordered: list[tuple[str, str, float]] = []
    stagings: list[dict[str, Any]] = []
    pending_staging: dict[str, Any] | None = None
    for line in lines:
        m = MEMORY_LINE.match(line)
        s = STAGING_LINE.match(line)
        if s is not None:
            if pending_staging is not None:
                raise MechanismInvalid(
                    "staging event without its paired host-typed staging "
                    "allocation")
            pending_staging = {"size": float(s.group("size")), "index": len(ordered)}
            stagings.append(pending_staging)
            continue
        if m is not None:
            kind = m.group("type")
            direction = m.group("dir")
            size = _parse_size(m.group("size"))
            entry = (kind, direction, size)
            ordered.append(entry)
            if pending_staging is not None:
                if direction == "+":
                    pending_staging["alloc_index"] = len(ordered) - 1
                    pending_staging = None
                # a '-' line between the staging line and its allocation is
                # the growth path's destroyed previous buffer; binding waits
                # for the paired ALLOCATION line (validated in _mechanism_a5)
    if pending_staging is not None:
        raise MechanismInvalid(
            "staging event without its paired host-typed staging allocation")
    has_async_off = any(l.strip() == ASYNC_DISABLED_LINE for l in lines)
    # A near-miss marker (substring, wrong prefix, appended text) is not the
    # pin's line and must not be countable evidence.
    for line in lines:
        if "Async execution disabled" in line and line.strip() != ASYNC_DISABLED_LINE:
            raise MechanismInvalid(
                "async-disabled marker present only as non-exact text")
        if "matrix cores" in line and not ENUM_LINE.match(line):
            raise MechanismInvalid(
                "matrix-cores text present outside the exact enumeration line")
    return {"families": enums, "ordered": ordered, "staging_sizes": stagings,
            "async_disabled": has_async_off}


def _require_subject_family(obs: dict[str, Any], arm: str) -> None:
    """Arms that do not gate coopmat detection must retain the frozen
    subject's family (one-factor law, frozen HOST_FACTS capability)."""
    if not obs["families"]:
        raise MechanismInvalid(f"{arm} retained unit lacks the Vulkan "
                               "enumeration line")
    if obs["families"][0] != SUBJECT_ENUM_FAMILY:
        raise MechanismInvalid(
            f"{arm} enumeration family {obs['families'][0]!r} differs from "
            f"the frozen subject capability {SUBJECT_ENUM_FAMILY!r}; this "
            "arm's control cannot change cooperative-matrix detection — "
            "the run was not one-factor on the frozen subject")


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
    the exact enumeration line proving the Vulkan path stayed active on the
    frozen subject (one-factor law: A3's control cannot change the reported
    matrix-core family).
    """
    for unit in _arm_units(root, namespace):
        obs = _unit_observations(_unit_server_log(unit))
        if not obs["async_disabled"]:
            raise MechanismInvalid(
                "A3 retained server log lacks the exact async-disabled line")
        _require_subject_family(obs, "A3")
    return {"arm": "A3",
            "mechanism": "backend async interface disabled at runtime "
                         "(exact disabled-marker line retained in every unit, "
                         "Vulkan path active)"}


def _mechanism_a5(root: Path, namespace: str) -> dict[str, Any]:
    """A5: host-visible VRAM disabled; device-local path selected.

    Per-unit law, enforced as an ORDERED one-to-one pairing over the
    retained event stream (source-derived at pin b29c606e):

    - With host-visible VRAM disabled and no sysmem fallback, weight
      buffers are not host-visible, so uploads route through the staged
      copy path: for every exact STAGING_LINE (:8603/:8613) the NEXT
      memory-logger allocation line must be its own HOST-typed allocation
      (:8605/:8615 -> log_allocation :2757) whose size equals the staging
      line's size under the pin's format_size (:2249) 2-decimal rounding.
      Between the two, at most ONE HOST-typed DEALLOCATION line — and only
      when its size equals the CURRENT staging buffer's last allocation
      (the growth path :8604 destroys the smaller existing buffer first).
      One-to-one and multiplicity-enforcing: a staging line without its
      allocation, two staging lines sharing one allocation, a same-sized
      allocation from elsewhere, and a correct-sized allocation in the
      wrong position are ALL rejected. Aggregate set/multiset/total
      equality proves nothing and is not consulted.
    - At least one DEVICE-typed allocation must be retained (Vulkan
      compute placement active).
    - No OTHER host-typed allocation may exist anywhere in the unit (a
      host-visible weight buffer would prove the intervention was NOT
      live). Staging-buffers' own paired allocations are the only legal
      host-typed lines; a host deallocation is legal only as the growth
      replacement above.
    - The enumeration line must report the frozen subject family
      (one-factor law).
    - The arithmetic running-total ledger law stays independently enforced
      (:2757/:2773) over every allocation/deallocation line.
    """
    staging_events = 0
    for unit in _arm_units(root, namespace):
        obs = _unit_observations(_unit_server_log(unit))
        _require_subject_family(obs, "A5")
        if not obs["staging_sizes"]:
            raise MechanismInvalid(
                "A5 retained server log lacks the exact sync-staging line; "
                "device-local-only path not evidenced")
        events = obs["ordered"]
        stagings = obs["staging_sizes"]
        allocated_as_staging: set[int] = set()
        for st in stagings:
            ai = st.get("alloc_index")
            if ai is None:
                raise MechanismInvalid(
                    "A5 staging line without its matching host-typed "
                    "staging allocation")
            kind, direction, size = events[ai]
            # The paired allocation must be the NEXT allocation line after
            # the staging line (direct: index+1), or index+2 when exactly one
            # host deallocation of the CURRENT staging buffer sits between
            # (the pin's growth path :8604 destroys the smaller existing
            # buffer before allocating the larger one).
            if ai == st["index"] + 1:
                # growth path: exactly one host deallocation of the current
                # staging buffer between the staging line and its allocation
                dkind, ddir, dsize = events[ai - 1]
                if not (dkind == "host" and ddir == "-"
                        and _size_eq(dsize, _current_staging_host_total(obs, ai - 1))):
                    raise MechanismInvalid(
                        "A5 host deallocation retained outside the "
                        "staging growth-replacement path")
            elif ai != st["index"]:
                raise MechanismInvalid(
                    "A5 staging event not immediately followed by its "
                    "own host-typed allocation (ordered pairing law)")
            if kind != "host" or direction != "+" or not _size_eq(size, st["size"]):
                raise MechanismInvalid(
                    "A5 paired allocation is not the staging buffer's own "
                    "host-typed allocation of the exact staging size")
            allocated_as_staging.add(ai)
        for idx, (kind, direction, size) in enumerate(events):
            if kind != "host" or idx in allocated_as_staging:
                continue
            if direction == "+":
                raise MechanismInvalid(
                    "A5 host-typed allocation other than the staging buffer "
                    "itself retained; host-visible VRAM not disabled as claimed")
            # host deallocation outside pairing: only legal as the growth
            # path's replaced buffer (immediately followed by the paired
            # larger allocation); anything else is a foreign host buffer
            if not _is_growth_replacement_dealloc(obs, idx):
                raise MechanismInvalid(
                    "A5 host deallocation outside the staging "
                    "growth-replacement path retained")
        if not any(kind == "device" for kind, _, _ in events):
            raise MechanismInvalid("A5 no device-typed allocation retained")
        staging_events += len(stagings)
    return {"arm": "A5", "staging_events": staging_events,
            "mechanism": "host-visible VRAM disabled and staged-upload path "
                         "selected (every exact sync-staging line paired "
                         "one-to-one, in order, with its own host-typed "
                         "allocation of the exact staging size; no other "
                         "host-typed allocation; device-typed compute "
                         "allocations in every unit)"}


def _size_eq(a: float, b: float) -> bool:
    """Equality under the pin's format_size (:2249) 2-decimal rounding."""
    quantum = max(a, b) * 0.005 + 1.0
    return abs(a - b) <= quantum


def _current_staging_host_total(obs: dict[str, Any], up_to: int) -> float:
    """Host bytes allocated by staging-paired allocations before index."""
    total = 0.0
    for st in obs["staging_sizes"]:
        ai = st.get("alloc_index")
        if ai is not None and ai < up_to:
            total += obs["ordered"][ai][2]
    return total


def _is_growth_replacement_dealloc(obs: dict[str, Any], idx: int) -> bool:
    """True when host-dealloc at idx is the growth path's replaced buffer
    (immediately followed by a staging-paired host allocation)."""
    for st in obs["staging_sizes"]:
        ai = st.get("alloc_index")
        if ai is not None and ai == idx + 1:
            return True
    return False


# A1: GGML_VK_SERIALIZE_SUBMISSIONS sets device->serialize_submissions
# (:7435) and the serialized submission path waits on the device fence
# (:18105), but the pin emits NO retained observable distinguishing a
# serialized submission from an unfenced batch. Marking it here (not in the
# reducer's control flow) keeps the reason auditable and testable.
NON_TERMINAL_CAPABLE = {
    "A1": "no retained submission-serialization observable exists at pin "
          "b29c606e; the serialized wait path emits no distinguishable "
          "retained bytes",
    "A4": "no retained observable at pin b29c606e binds an allocation line "
          "to the prefer_host_memory branch: the memory logger types "
          "allocations only by eDeviceLocal (:2749-2751) with no buffer "
          "identity or call-site provenance, host-typed lines arise "
          "identically from the staging (:8605/:8615) and pinned-host "
          "(:8222) paths, and no preference-off baseline allocation ledger "
          "exists to compare same-site typing against",
}

MECHANISM_VALIDATORS = {
    "A2": _mechanism_a2,
    "A3": _mechanism_a3,
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
