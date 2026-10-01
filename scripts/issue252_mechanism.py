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


def _require_retained_a3_placement(unit: Path) -> None:
    """A3 placement/identity law under METHODOLOGY-AMENDMENT-005 (round 5).

    Physical fact (second A3 attempt, dispatched head a090c41): the retained
    server-log stream of this frozen host/runtime family physically carries
    NO ``ggml_vulkan`` device-enumeration banner, so the enum line can no
    longer be REQUIRED as A3's Vulkan-participation observable. The A3
    placement proof instead re-derives from the retained facts captured for
    every unit: the frozen producer-attested Vulkan placement (the /3
    producer law — env CUDA_VISIBLE_DEVICES=-1, frozen NVIDIA ICD,
    GGML_VK_VISIBLE_DEVICES=0, ngl=1, frozen GPU UUID, no CUDA
    participation, argv/env read back from /proc and bound into the
    attestation) and the frozen subject identity observations (pre/post
    equal to the frozen HOST_FACTS). This helper is A3-only; A2/A5 keep
    their genuine enum/memory observables untouched.
    """
    import issue254_producer as PR254

    def _obj(rel: str) -> dict[str, Any]:
        path = unit / rel
        if path.is_symlink() or not path.is_file():
            raise MechanismInvalid(
                f"A3 retained unit lacks {rel} (placement/identity evidence)")
        try:
            doc = json.loads(path.read_bytes())
        except json.JSONDecodeError as exc:
            raise MechanismInvalid(
                f"A3 retained {rel} is not valid JSON") from exc
        if not isinstance(doc, dict):
            raise MechanismInvalid(f"A3 retained {rel} is not an object")
        return doc

    placement = _obj("placement.json")
    if (placement.get("output_projection") != "Vulkan"
            or placement.get("embedding") != "CPU"
            or placement.get("ngl") != 1
            or placement.get("cuda_participation") is not False):
        raise MechanismInvalid(
            "A3 retained placement is not the frozen producer-attested "
            "Vulkan geometry (Vulkan output projection, CPU embedding, "
            "ngl=1, no CUDA participation)")
    gpu_uuid = placement.get("gpu_uuid")
    if (not isinstance(gpu_uuid, str)
            or not gpu_uuid
            or gpu_uuid != PR254.C252.HOST_FACTS["gpu_uuid"]):
        raise MechanismInvalid(
            "A3 retained placement GPU UUID differs from the frozen "
            "subject identity")
    family = placement.get("vulkan_family")
    if family is not None and family != SUBJECT_ENUM_FAMILY:
        # identity-authority value only (frozen HOST_FACTS capability);
        # when present it must be the frozen subject capability.
        raise MechanismInvalid(
            "A3 placement vulkan_family differs from the frozen HOST_FACTS "
            "capability authority")
    for phase in ("identity-pre.json", "identity-post.json"):
        identity = _obj(phase)
        if any(identity.get(k) != v
               for k, v in PR254.C252.HOST_FACTS.items()):
            raise MechanismInvalid(
                f"A3 retained {phase} differs from the frozen subject "
                "identity (one-factor law)")


def _mechanism_a3(root: Path, namespace: str) -> dict[str, Any]:
    """A3: async backend behavior disabled for the measured execution.

    Law (amended round 5, METHODOLOGY-AMENDMENT-005): every retained unit's
    server.log contains the EXACT stderr line the pin emits when
    support_async is false (:6727), full-line equality — plus the frozen
    producer-attested Vulkan placement/identity facts for the same unit
    (enum banner no longer physically retained by this instrument, so the
    old one-factor enum requirement is replaced by the /3 producer
    attestation's retained identity/env facts; A2/A5 unchanged).
    """
    for unit in _arm_units(root, namespace):
        obs = _unit_observations(_unit_server_log(unit))
        if not obs["async_disabled"]:
            raise MechanismInvalid(
                "A3 retained server log lacks the exact async-disabled line")
        if obs["families"] and obs["families"][0] != SUBJECT_ENUM_FAMILY:
            # The enum banner is no longer REQUIRED (AMENDMENT-005), but a
            # banner that IS retained must still report the frozen subject
            # capability: a forged family change under A3 violates the
            # one-factor law (A3's control cannot change coopmat detection).
            raise MechanismInvalid(
                f"A3 enumeration family {obs['families'][0]!r} differs "
                f"from the frozen subject capability "
                f"{SUBJECT_ENUM_FAMILY!r}; this arm's control cannot "
                "change cooperative-matrix detection — the run was not "
                "one-factor on the frozen subject")
        if len(obs["families"]) > 1:
            raise MechanismInvalid(
                "multiple device enumeration lines in one unit; the "
                "frozen one-device launch emits exactly one")
        _require_retained_a3_placement(unit)
    return {"arm": "A3",
            "mechanism": "backend async interface disabled at runtime "
                         "(exact disabled-marker line retained in every "
                         "unit, producer-attested Vulkan placement and "
                         "frozen subject identity retained per unit "
                         "(AMENDMENT-005))"}


def _mechanism_a5(root: Path, namespace: str) -> dict[str, Any]:
    """A5: host-visible VRAM disabled; device-local path selected.

    Per-unit law, enforced as an ORDERED STAGING-BUFFER STATE TRANSITION
    over the retained event stream (source-derived at pin b29c606e,
    ggml_vk_ensure_sync_staging_buffer :8601/:8611):

    - Growth condition (:8602): the ensure grows the buffer only when
      `sync_staging == nullptr || sync_staging->size < size` (strict <).
      On growth the pin logs the exact STAGING_LINE (:8603/:8613), then
      DESTROYS the current buffer (:8604 — ggml_vk_destroy_buffer logs a
      host-typed deallocation of exactly the CURRENT buffer's size, and is
      a null no-op when no buffer exists), then allocates the new buffer
      of exactly the requested size (host-typed allocation under the
      pin's format_size :2249 2-decimal rounding). A repeated ensure that
      does NOT require growth emits NOTHING — no staging line, no
      deallocation, no allocation.
    - State machine over the ordered stream: initial active staging size
      is none; each exact STAGING_LINE opens one pending transition; with
      no active buffer the very next memory event must be the paired
      +host allocation of the exact staging size; with an active buffer
      the request must strictly exceed it (a staging line for a request
      at or below the active size is inauthentic — the pin would have
      emitted nothing) and the transition must be exactly one -host
      deallocation matching the CURRENT active size followed by the
      paired +host allocation of the requested size. After pairing the
      active size becomes the new allocation's size. Historical staging
      allocations are already deallocated: they are never summed, never
      again deallocatable, and a deallocation of their sizes is a foreign
      host buffer.
    - Every other host-typed memory event anywhere in the unit is
      rejected: no unrelated host allocation may exist (a host-visible
      weight buffer would prove the intervention was NOT live), no
      duplicate or reordered deallocation, no missing destroy on growth.
      One-to-one and multiplicity-enforcing by construction: aggregate
      set/multiset/total equality proves nothing and is not consulted.
    - At least one DEVICE-typed allocation must be retained (Vulkan
      compute placement active).
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
        transition_at = {st["index"]: st for st in obs["staging_sizes"]}
        active: float | None = None  # current live staging buffer size
        paired_events: set[int] = set()
        for idx, (kind, direction, size) in enumerate(events):
            st = transition_at.get(idx)
            if st is not None:
                # A staging transition opens at this position: the pin
                # logs the staging line BEFORE the (optional) destroy and
                # the paired allocation, so the transition occupies the
                # immediately following event(s) — nothing may interleave.
                requested = st["size"]
                ai = st.get("alloc_index")
                if active is None:
                    # First buffer: the pin's destroy is a null no-op
                    # (:3848 early return) — the NEXT event must be the
                    # paired +host allocation itself.
                    if ai != idx:
                        raise MechanismInvalid(
                            "A5 initial staging transition not immediately "
                            "followed by its own host-typed staging "
                            "allocation (ordered pairing law)")
                else:
                    if requested <= active:
                        raise MechanismInvalid(
                            "A5 retained staging line for a request that "
                            "does not require growth: the pin emits nothing "
                            "when sync_staging->size >= size (:8602), so an "
                            "exact staging line here is inauthentic")
                    if ai != idx + 1:
                        raise MechanismInvalid(
                            "A5 staging growth must destroy the current "
                            "staging buffer before allocating (:8604): "
                            "exactly one host deallocation then the paired "
                            "host-typed staging allocation (ordered "
                            "transition law)")
                    dkind, ddir, dsize = events[idx]
                    if not (dkind == "host" and ddir == "-"
                            and _size_eq(dsize, active)):
                        raise MechanismInvalid(
                            "A5 growth deallocation does not match the "
                            "CURRENT active staging buffer size; historical "
                            "staging allocations are already deallocated "
                            "and are never summed")
                    paired_events.add(idx)
                pkind, pdir, psize = events[ai]
                if pkind != "host" or pdir != "+" or not _size_eq(psize,
                                                                  requested):
                    raise MechanismInvalid(
                        "A5 paired allocation is not the staging buffer's "
                        "own host-typed allocation of the exact staging "
                        "size")
                paired_events.add(ai)
                active = psize
                continue
            if kind == "host" and idx not in paired_events:
                raise MechanismInvalid(
                    "A5 host-typed memory event outside the staging "
                    "growth-replacement state machine retained"
                    + ("; host-visible VRAM not disabled as claimed"
                       if direction == "+" else
                       " (unrelated/duplicate/reordered host "
                       "deallocation)"))
        if not any(kind == "device" for kind, _, _ in events):
            raise MechanismInvalid("A5 no device-typed allocation retained")
        staging_events += len(obs["staging_sizes"])
    return {"arm": "A5", "staging_events": staging_events,
            "mechanism": "host-visible VRAM disabled and staged-upload path "
                         "selected (every exact sync-staging line drives an "
                         "ordered staging-buffer state transition: initial "
                         "or growth pairing with its own host-typed "
                         "allocation of the exact staging size, growth "
                         "destroying exactly the current buffer, no "
                         "no-growth staging lines, no other host-typed "
                         "memory event; device-typed compute allocations "
                         "in every unit)"}


def _size_eq(a: float, b: float) -> bool:
    """Equality under the pin's format_size (:2249) 2-decimal rounding."""
    quantum = max(a, b) * 0.005 + 1.0
    return abs(a - b) <= quantum


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
