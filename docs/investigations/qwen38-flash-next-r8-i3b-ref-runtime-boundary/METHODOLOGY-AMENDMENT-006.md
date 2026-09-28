# METHODOLOGY AMENDMENT 006 — Issue #250 V0 runtime-identity JSON canonicalization

Dated: 2026-09-28. Repository-only correction on PR #251 following the
failed physical V0 attempt at reviewed head `028dce94e7a5eb848b3f13d54d7c4717d7de8a4d`.
This amendment records the exact serialization defect that stopped the
canonical-freeze step, the canonical runtime-identity contract that
corrects it, and the fresh-evidence-root rule for the next physical
attempt. It authorizes no dispatch, no model request, and no merge.
Earlier methodology amendments remain unchanged and preserved verbatim.

## The physical attempt and its disposition

Under maintainer dispatch comment `5862772797` (authority digest
`48261af7289f3cbcf13c27f56be78a746cdf54a0f8c927d4487076c8d6067677`) at
head `028dce94`, the V0 arm on `inferswarm05` executed the two-index
load-only physical preflight successfully (index 0 -> BDF `0000:07:00.0`,
index 1 -> BDF `0000:0b:00.0`, selected-die VRAM deltas ~1 GiB, excluded
noise < 64 MiB) and retained the selector binding. ZERO AMD completion
units were executed: the campaign stopped fail-closed at
`write_v0_screen_freeze()` before any model load or inference request.

The root cause was proven to be a tooling serialization defect, NOT
substrate drift: `_v0_observe_device()` built
`runtime_identity.devices` with INTEGER keys (`devices[int]` from the
vulkaninfo parse); the retained `v0-selector-binding.json`, after its
production JSON retention and `json.loads` re-read, carries STRING keys
(`"0"`/`"1"`); `validate_v0_selector_binding()` compared the two dicts
with raw Python equality. The preflight itself passed because it
validated the in-memory record against the in-memory observation (both
integer-keyed); every freeze/launch consumer that re-reads the retained
JSON then deterministically failed with
`V0 selector binding digest/head/runtime identity mismatch`. After
normalizing the device-map keys the two identities are byte-identical
(same kernel `6.12.107+deb13-amd64`, same Vulkan instance `1.4.309`,
same per-device vendor/device/name/driver/API fields) — no substrate
drift occurred. The canonical digest also survived the round-trip
(single-digit keys sort identically under `sort_keys=True`), so digest
law was never the failure and is NOT changed by this correction.

The retained root `/home/hermes/is250-campaign/evidence/` is preserved
UNMODIFIED as HISTORICAL FAILED-V0-ATTEMPT EVIDENCE: its physical
selector/BDF observations remain valid as observations, but the binding
is bound to head `028dce94` and dispatch `5862772797` and is NOT
reusable as prospective exact-head preflight authority for any later
changed PR head. No adoption or migration exception exists or may be
added.

## Canonical runtime-identity contract

One explicit canonical schema/normalizer (`_v0_normalize_runtime_identity`)
now governs every retained/live runtime-identity comparison:

- `runtime_identity` is a dict with exactly the keys `kernel`,
  `vulkan_instance`, `devices`; `kernel` and `vulkan_instance` are
  non-empty strings.
- `devices` is exactly the two Vulkan devices. Accepted device-map keys
  at the raw-input boundary are only integer `0`/`1` (the live
  vulkaninfo parse) or decimal strings `"0"`/`"1"` (any JSON-retained
  record). The canonical representation always uses string keys `"0"`
  and `"1"`.
- Each canonical device entry retains and compares exactly the
  identity-bearing fields emitted by `_v0_observe_device()`:
  `vendor_id`, `device_id`, `name`, `driver_id`, `driver_info`,
  `driver_version`, `api_version` — all non-empty strings. No field is
  discarded to make equality pass.
- Rejected fail-closed: booleans, floats, key aliases (`"00"`, `0.0`),
  duplicate/colliding normalized keys (`0` and `"0"` together), missing
  indices, extra indices (device `2`), malformed device objects,
  unknown structural substitutions, non-string or empty field values,
  and unknown top-level identity keys.

`_v0_observe_device()` now emits the canonical string-keyed device map
from the outset (the live top-level `index` stays an integer and
`vulkan_indices` stays the integer list `[0, 1]`), and
`run_v0_binding_preflight()` retains the normalized identity, so the
retained record equals its own JSON bytes. `validate_v0_selector_binding()`
normalizes both the record's and the live observation's identity and
requires canonical semantic equality: any kernel, Vulkan-instance, or
per-device field drift still fails closed with the same error class.
This automatically covers every retained consumer —
`write_v0_screen_freeze()`, `_v0_load_freeze_with_preflight()`,
`run_v0_unit()`, `_v0_retained_rows()`, and the terminal/reducer paths
that authenticate the retained binding. There is no freeze-only
exception, and the serialized runtime identity remains part of
`v0-selector-binding.json` and its canonical digest: a mutated retained
runtime identity still invalidates the binding digest, and a re-signed
mutated identity still fails the canonical comparison.

## Next physical attempt requires a fresh evidence root

Dispatch `5862772797` is STALE for any head other than `028dce94`; it
must never be reused after this correction moves the PR head. After
this correction is reviewed and freshly dispatched, the next V0
physical execution must create a NEW SIBLING evidence root, e.g.

`/home/hermes/is250-campaign/evidence-v0-<NEW_HEAD_SHORT>`

or an equivalent explicitly recorded fresh root, independently
retaining: the canonical evidence-generation marker, the current
cost-planning record, the current opening model attestation, a fresh
corrected-head two-index load-only preflight, a fresh selector binding,
a fresh canonical freeze, and the subsequent V0 units. Old-head and
new-head prospective authority must never be mixed in one reduction.
The old `/home/hermes/is250-campaign/evidence/` root remains read-only
historical failed-at-freeze evidence.
