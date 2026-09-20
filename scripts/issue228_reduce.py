#!/usr/bin/env python3
"""Issue #228 — V2-E deterministic reduction helpers.

Correction round (maintainer NO-GO on c9822fe):

* ``reduce_transfers`` now REQUIRES per-repeat correctness: every timed
  row must have a matching correctness row (same direction, same rep
  identity) whose ``ok`` is exactly true; duplicate rep ids, dropped
  reps, rep-set mismatch against the frozen repetition count, and any
  ``ok=false`` or ``correctness_fail`` row are ReduceErrors — a
  correctness failure can never become a functional terminal;
* ``reduce_route`` separates advertised capability from validated
  execution: without measured correct transfers there is no functional
  route conclusion at all;
* census verdicts come from probe.validate_capability_census — the
  reduction never re-derives capability from raw rows with looser
  rules than the validator.

Every reduction re-derives its output from PRIMARY RAW BYTES retained
under the evidence root. Nothing is taken from authored summaries.

Correction round 2 (maintainer rejection of the 549b997 docs/verdict):
the frozen producer's capability validator mis-transcribed the Vulkan
registry handle-type bits (its table maps dma_buf to 0x80, which is
HOST_ALLOCATION's bit; the registry value is 0x200). Against the
retained raw ext-matrix bytes (dma_buf transfer buffers advertise
export/import with compatibleHandleTypes=513=0x1|0x200 on BOTH dies)
the frozen mask check ``513 & 0x80`` yielded 0, so the derived verdict
falsely classified dma_buf as incompatible. ``rederive_external_memory``
below re-derives the external-memory advertisement classification from
the SAME unchanged raw bytes using the registry bit values plus an
explicit enabling-extension enumeration gate. It is a REDUCTION-layer
correction only: no physical producer byte changed (recorded in the
area AMENDMENTS.json ledger per the accepted #216 protocol).

Advertisement vs execution is kept explicit: a handle type classified
``advertised-bidirectional`` is an API-level property-query
advertisement only — never a reviewed cross-device implementation,
never a validated transfer, and never evidence about the physical
route.
"""
from __future__ import annotations

import json
import statistics
from typing import Any

import issue228_receipt as rc


class ReduceError(RuntimeError):
    pass


def parse_probe_stream(stdout: str, exit_code: int) -> list[dict[str, Any]]:
    """Parse a transfer probe's JSON-lines stream (fail-closed)."""
    if exit_code != 0:
        raise ReduceError(f"probe exited {exit_code}")
    records = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        records.append(json.loads(line))  # malformed -> ValueError -> caller
    if not records or "schema" not in records[0]:
        raise ReduceError("probe stream lacks a header record")
    return records


def reduce_transfers(records: list[dict[str, Any]], direction: str,
                     expected_reps: int | None = None,
                     ) -> dict[str, Any]:
    """Reduce one direction's timed rows to the frozen distribution
    summary, requiring per-repeat correctness evidence.

    Fail-closed on: zero timed rows; any correctness_fail row; any
    correctness row with ok != true; timed/correctness rep-set
    mismatch; duplicate rep ids; dropped reps (when ``expected_reps``
    is given, the rep set must be exactly 0..expected_reps-1); zero/
    negative times or bytes; mixed sizes.
    """
    timed = [r for r in records
             if r.get("kind") == "transfer" and r.get("dir") == direction]
    checks = [r for r in records
              if r.get("kind") == "correctness" and r.get("dir") == direction]
    fails = [r for r in records
             if r.get("kind") == "correctness_fail"
             and r.get("dir") == direction]
    if not timed:
        raise ReduceError(f"no timed rows for direction {direction}")
    if fails:
        raise ReduceError(
            f"correctness failures retained for {direction}: "
            f"{[r.get('rep') for r in fails]}")
    not_ok = [r for r in checks if r.get("ok") is not True]
    if not_ok:
        raise ReduceError(
            f"correctness rows with ok != true for {direction}: "
            f"{[(r.get('rep'), r.get('ok')) for r in not_ok]}")
    timed_ids = [r.get("rep") for r in timed]
    check_ids = [r.get("rep") for r in checks]
    int_timed = sorted(int(i) for i in timed_ids if isinstance(i, int))
    if len(set(timed_ids)) != len(timed_ids):
        raise ReduceError(
            f"duplicate timed rep ids for {direction}: {timed_ids}")
    if len(set(check_ids)) != len(check_ids):
        raise ReduceError(
            f"duplicate correctness rep ids for {direction}: {check_ids}")
    if set(timed_ids) != set(check_ids):
        raise ReduceError(
            f"timed/correctness rep-set mismatch for {direction}: "
            f"timed={sorted(timed_ids)} correctness={sorted(check_ids)}")
    if expected_reps is not None:
        if timed_ids != list(range(expected_reps)):
            raise ReduceError(
                f"incomplete repetition set for {direction}: expected "
                f"reps 0..{expected_reps - 1}, saw {sorted(timed_ids)}")
    for row in timed:
        if row.get("ms", 0) <= 0 or row.get("bytes", 0) <= 0:
            raise ReduceError(f"invalid timed row: {row!r}")
    times_ms = [row["ms"] for row in timed]
    bytes_ = timed[0]["bytes"]
    if any(row["bytes"] != bytes_ for row in timed):
        raise ReduceError("mixed transfer sizes in one reduction")
    gbps = [bytes_ / (t / 1e3) / 1e9 for t in times_ms]

    def pct(values: list[float], fraction: float) -> float:
        ordered = sorted(values)
        idx = min(int(round(fraction * (len(ordered) - 1))),
                  len(ordered) - 1)
        return ordered[idx]

    return {
        "direction": direction,
        "count": len(timed),
        "bytes_per_transfer": bytes_,
        "time_ms_min": round(min(times_ms), 6),
        "time_ms_median": round(statistics.median(times_ms), 6),
        "time_ms_p10": round(pct(times_ms, 0.10), 6),
        "time_ms_p90": round(pct(times_ms, 0.90), 6),
        "time_ms_max": round(max(times_ms), 6),
        "gbps_median": round(statistics.median(gbps), 3),
        "gbps_min": round(min(gbps), 3),
        "gbps_max": round(max(gbps), 3),
        "correctness_ok": True,
        "correctness_reps": int_timed,
    }


def reduce_route(assembly: dict[str, Any]) -> dict[str, Any]:
    """Derive the route conclusion from retained evidence.

    Route vocabulary (issue Phase 6, never collapsed):
      LOCAL_SWITCH_BYPASS_PROVEN — needs per-port byte counters proving
        downstream activity without upstream activity;
      UPSTREAM_OR_HOST_ROUTE_PROVEN — counters/observations prove the
        host-facing path carried the peer traffic;
      PEER_FUNCTIONAL_ROUTE_UNRESOLVED — peer transfers functional but
        route evidence cannot distinguish;
      NO_PEER_TRANSFER_AVAILABLE — no peer mechanism existed to observe.

    Correction: a functional-route conclusion of any kind requires
    MEASURED CORRECT TRANSFERS; without them the only derivable
    conclusions are NO_PEER_TRANSFER_AVAILABLE or none at all.
    """
    mechanism = (assembly.get("mechanism") or {})
    transfers = assembly.get("validated_transfers")
    if not mechanism.get("available"):
        return {
            "route_conclusion": "NO_PEER_TRANSFER_AVAILABLE",
            "basis": "no peer-transfer mechanism was available to observe",
        }
    if not transfers:
        raise ReduceError(
            "mechanism available but no measured correct transfers "
            "retained; a functional route conclusion requires validated "
            "transfer evidence")
    route_counters = assembly.get("route_counters_available")
    if not route_counters:
        return {
            "route_conclusion": "PEER_FUNCTIONAL_ROUTE_UNRESOLVED",
            "basis": "peer transfers functional but no per-port byte "
                     "counters retained to distinguish local switch "
                     "bypass from upstream routing",
        }
    raise ReduceError(
        "per-port counter derivation not implemented in this campaign "
        "(counters unavailable on this kernel); refusing to fabricate a "
        "route conclusion")


def rederive_capability_facts(verdict: dict[str, Any]) -> dict[str, Any]:
    """Reduction-side capability facts FROM A VALIDATED CENSUS VERDICT.

    The raw-row derivation of the rejected round lived here and
    accepted one-sided/duplicated/host-only evidence; it is replaced by
    consumption of probe.validate_capability_census output, which the
    assembler re-runs over the retained raw bytes.
    """
    if not verdict.get("census_valid"):
        return {"census_valid": False,
                "failure_reasons":
                    list(verdict.get("failure_reasons") or [])}
    peer = verdict.get("peer_features") or {}
    dirs = peer.get("directions") or {}
    return {
        "census_valid": True,
        "multi_device_vega_group_present":
            (verdict.get("group") or {}).get(
                "both_dies_in_one_group", False),
        "peer_copy_directions_present": sorted(
            str(d) for d, row in dirs.items() if row.get("present")),
        "secondary_ext_memory_features":
            bool((verdict.get("external_memory") or {}).get(
                "usable_handle_types")),
        "capable_mechanisms":
            list(verdict.get("capable_mechanisms") or []),
    }


# ---------------------------------------------------------------------------
# Correction-round-2 external-memory re-derivation (reduction layer).
#
# The frozen producer validator (issue228_probe.validate_capability_census)
# mis-transcribed the Vulkan registry handle-type bits:
#   registry: OPAQUE_FD 0x1, HOST_ALLOCATION 0x80,
#             HOST_MAPPED_FOREIGN_MEMORY 0x100, DMA_BUF 0x200
#   frozen:   dma_buf -> 0x80 (HOST_ALLOCATION's bit)
# Against the retained raw bytes (dma_buf transfer rows carry
# compatibleHandleTypes=513=0x1|0x200) the frozen mask test
# ``513 & 0x80 == 0`` failed, so the derived verdict misclassified dma_buf
# as handle-type-incompatible. The retained raw bytes themselves prove the
# registry layout: a handle type's compatibleHandleTypes always includes
# its own bit (dma_buf rows report 513 -> 0x200 set; host_allocation rows
# report 128 -> 0x80 set).
# ---------------------------------------------------------------------------

#: VkExternalMemoryHandleTypeFlagBits (Vulkan registry, core 1.1 +
#: extensions). Handle types that can carry device memory across an fd.
REGISTRY_HANDLE_TYPE_BITS = {
    "opaque_fd": 0x1,
    "dma_buf": 0x200,
}

#: Device extension that MUST be enumerated for each fd-carried handle
#: type to be usable at all (the extension that provides the handle
#: type's import/export entry points on the device side).
HANDLE_ENABLING_EXTENSIONS = {
    "opaque_fd": "VK_KHR_external_memory_fd",
    "dma_buf": "VK_EXT_external_memory_dma_buf",
}

#: Advertisement classification states, deliberately distinct from any
#: execution/implementation fact (see the module docstring). The state
#: ladder derives from (in order) the export/import feature flags, the
#: enabling-extension enumeration, then the compatible-mask own-bit
#: consistency:
#:   not-advertised              — no export/import flags in any row
#:   advertised-one-direction    — flags present but not bilateral
#:   extension-not-enumerated    — bilateral flags, enabling extension
#:                                 not enumerated on a die
#:   compatible-mask-inconsistent — bilateral flags + extension, but a
#:                                 compatible mask lacks the handle
#:                                 type's own registry bit (per the
#:                                 Vulkan spec the mask always includes
#:                                 it — retained as an observation)
#:   advertised-bidirectional    — the full conjunction
ADVERTISEMENT_STATES = (
    "not-advertised",
    "advertised-one-direction",
    "extension-not-enumerated",
    "compatible-mask-inconsistent",
    "advertised-bidirectional",
)


def _die_extensions(die: dict[str, Any]) -> dict[str, Any]:
    """Relevant device-extension map from one ext-matrix die row."""
    for key in ("die_0_extensions", "die_1_extensions"):
        ext = die.get(key)
        if isinstance(ext, dict):
            relevant = ext.get("relevant")
            if isinstance(relevant, dict):
                return relevant
    return {}


def _extension_enumerated(relevant: dict[str, Any],
                          extension: str) -> bool | None:
    """True/False from the retained enumeration; None = not recorded."""
    value = relevant.get(extension)
    if isinstance(value, bool):
        return value
    return None


def _transfer_row(die: dict[str, Any], handle: str) -> dict[str, Any] | None:
    for row in die.get("buffer_matrix", []):
        if row.get("handle_type") == handle \
                and row.get("usage") == "transfer":
            return row
    return None


def rederive_external_memory(ext_matrix: dict[str, Any],
                             expected_bdfs: dict[str, str] | None = None,
                             ) -> dict[str, Any]:
    """Re-derive external-memory ADVERTISEMENT classification from the
    retained raw ext-matrix bytes with registry-correct bits.

    Distinguishes explicitly (never collapsed):

    * extension enumeration — whether the enabling device extension is
      enumerated by the loader/ICD (scoped to the die);
    * external-memory property query results — exportable/importable
      feature flags from vkGetPhysicalDeviceExternalBufferProperties;
    * compatibleHandleTypes — the compatible mask, tested against the
      handle type's own REGISTRY bit (never a transcribed constant);
    * advertisement state — the conjunction, per handle type, per
      direction, reported as structured rows.

    This is capability ADVERTISEMENT only. It is never a reviewed
    cross-device implementation, never a validated transfer, and never
    a physical-route fact; the assembler's terminal derivation keeps
    requiring measured transfer evidence for any functional terminal.
    """
    dies = list(ext_matrix.get("dies", []))
    by_uuid: dict[str, dict[str, Any]] = {
        d.get("device_uuid"): d for d in dies
        if d.get("device_uuid")
    }

    # identity join: participant labels come from the probe's
    # UUID->BDF derivation matched against the accepted mapping (same
    # join as the frozen validator); without expected_bdfs the dies are
    # labeled by ascending UUID-derived BDF order (die0/die1)
    import issue228_probe as probe
    uuid_bdf = {u: probe.bdf_from_device_uuid(u) for u in by_uuid}
    if expected_bdfs:
        expected_norm = {k: probe.normalize_bdf(v)
                         for k, v in expected_bdfs.items()}
        label_of: dict[str, str] = {}
        for uuid, bdf in uuid_bdf.items():
            if bdf is None:
                continue
            matches = [p for p, b in expected_norm.items() if b == bdf]
            if len(matches) == 1:
                label_of[uuid] = matches[0]
        if set(label_of) != set(by_uuid) \
                or len(set(label_of.values())) != len(label_of):
            return {
                "census_valid": False,
                "failure_reasons": [
                    "ext-matrix die UUIDs do not join exactly the "
                    "accepted mapping participants"],
                "advertisement": {},
            }
        pairs = (("a", "b"), ("b", "a"))
    else:
        uuid_order = sorted(by_uuid, key=lambda u: uuid_bdf[u] or u)
        label_of = {u: f"die{i}" for i, u in enumerate(uuid_order)}
        pairs = (("die0", "die1"), ("die1", "die0"))

    handles: dict[str, dict[str, Any]] = {}
    for handle in ("opaque_fd", "dma_buf"):
        bit = REGISTRY_HANDLE_TYPE_BITS[handle]
        per_direction: dict[str, dict[str, Any]] = {}
        for src_label, dst_label in pairs:
            src_uuid = next(u for u, lab in label_of.items()
                            if lab == src_label)
            dst_uuid = next(u for u, lab in label_of.items()
                            if lab == dst_label)
            src_die = by_uuid[src_uuid]
            dst_die = by_uuid[dst_uuid]
            src_row = _transfer_row(src_die, handle)
            dst_row = _transfer_row(dst_die, handle)
            src_ext_map = _die_extensions(src_die)
            dst_ext_map = _die_extensions(dst_die)
            enabling = HANDLE_ENABLING_EXTENSIONS[handle]
            extension_enumerated = _extension_enumerated(
                src_ext_map, enabling)
            extension_enumerated_dst = _extension_enumerated(
                dst_ext_map, enabling)
            export_ok = bool(src_row and src_row.get("exportable"))
            import_ok = bool(dst_row and dst_row.get("importable"))
            compat_ok = bool(
                src_row and dst_row
                and (int(src_row.get("compatible") or 0) & bit)
                and (int(dst_row.get("compatible") or 0) & bit))
            usable = (export_ok and import_ok and compat_ok
                      and extension_enumerated is not False
                      and extension_enumerated_dst is not False)
            per_direction[f"{src_label}_to_{dst_label}"] = {
                "source_exportable": export_ok,
                "destination_importable": import_ok,
                "compatible_handle_types_ok": compat_ok,
                "extension_enumerated": extension_enumerated,
                "usable": usable,
            }
        flags_bilateral = all(
            (r.get("source_exportable")
             and r.get("destination_importable"))
            for r in per_direction.values())
        flags_any = any(
            (r.get("source_exportable")
             or r.get("destination_importable"))
            for r in per_direction.values())
        ext_enum_all = all(
            r.get("extension_enumerated") is not False
            for r in per_direction.values())
        compat_all = all(
            r.get("compatible_handle_types_ok")
            for r in per_direction.values())
        if not flags_any:
            state = "not-advertised"
        elif not flags_bilateral:
            state = "advertised-one-direction"
        elif not ext_enum_all:
            state = "extension-not-enumerated"
        elif not compat_all:
            state = "compatible-mask-inconsistent"
        else:
            state = "advertised-bidirectional"
        all_usable = all(r["usable"] for r in per_direction.values())
        handles[handle] = {
            "advertisement_state": state,
            "extension_enumerated_both_dies": ext_enum_all,
            "compatible_handle_types_ok_both_directions": compat_all,
            "all_directions_usable": all_usable,
            "directions": per_direction,
        }

    advertised = sorted(
        h for h, row in handles.items()
        if row["advertisement_state"] == "advertised-bidirectional")
    return {
        "census_valid": True,
        "advertisement": handles,
        "advertised_bidirectional_handle_types": advertised,
        "nonclaims": [
            "advertisement is a property-query result, not a reviewed "
            "cross-device implementation",
            "advertisement is not a validated transfer; zero transfers "
            "were executed in this campaign",
            "advertisement establishes no physical route (no transfer "
            "occurred; route unmeasured)",
        ],
    }
