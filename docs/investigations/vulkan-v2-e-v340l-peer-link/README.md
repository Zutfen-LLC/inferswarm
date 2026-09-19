# V2-E — V340L inter-die peer-link qualification (issue #228)

Status: CAMPAIGN COMPLETE — terminal **`V2E_V340L_P2P_API_PREREQUISITE`**
(re-derived deterministically by `scripts/issue228_assemble.py` from the
retained evidence bytes; see `evidence/ASSEMBLY.json`,
`evidence/TERMINAL.json`).

Campaign: `issue228-v2e-v340l-peer-link`
Producer pin: `8c25184c54ce660020047711a2755c55178f8195`
(closure `/1`, digest `0973306a…`; executed-byte freeze: worktree ==
index == HEAD per closure source, verified on the proving host before
any collection and by the assembler before any reduction).
Authority: `PHYSICAL-AUTHORITY.json` (intended identity derived
exclusively from accepted V2-B/V2-C/V2-D0/V2-D manifest-pinned bytes;
every predecessor file re-hashed at build through its own accepted
`MANIFEST.sha256` rows).

## What this campaign asked (issue #228)

> Can the V340L's two independently addressable Vega dies exchange data
> directly through their on-card PM8533 PCIe-switch topology at
> materially different bandwidth/latency from host-mediated traffic,
> and can that route be proven without relying on the X12's shared
> Gen3 x1 upstream link?

## What the retained evidence establishes

**No in-stack peer-memory mechanism exists on the accepted software
stack.** Both candidate mechanisms were probed mechanically and are
unavailable:

1. **Vulkan device-group peer path** (the preferred mechanism): the
   loader (`libvulkan1` 1.3.150 / RADV Mesa 25.0.7-2+deb13u1) exposes
   exactly 5 physical-device groups, EVERY one single-device — the two
   Vega dies are never co-members of any group. With no multi-device
   group, `VkDeviceGroupDeviceCreateInfo` cannot span the dies and
   `vkGetDeviceGroupPeerMemoryFeatures` is unreachable for the pair.
   Retained: `evidence/preflight/raw/capability-probe.stdout`
   (`vega_group_present: false`).
2. **Secondary in-stack mechanism — external-memory import**
   (`VK_EXT_external_memory_dma_buf` + `VK_KHR_external_memory_fd`,
   both enumerated as present on both dies): the full handle-type ×
   usage × feature matrix returns ZERO exportable and ZERO importable
   features for buffers (transfer/storage/uniform) and images
   (opaque_fd, dma_buf, host_allocation, host_mapped_foreign) on BOTH
   dies. Retained: `evidence/preflight/raw/ext-matrix.stdout`.

The ladder runner's mechanism gate therefore REFUSED the frozen
transfer ladder (`evidence/ladder/refusal.json`,
`executed_transfers: 0`), and the matched-baseline collectors refused
for the same reason (`evidence/baselines/refusal.json`). No transfer
was executed; the #216 faulting transport seam was not rerun; no model
inference was run.

This is the issue's `V2E_V340L_P2P_API_PREREQUISITE` case exactly:
"topology suggests a possible peer path but the current accepted
software stack exposes no safe mechanism capable of exercising or
observing it without installing/replacing a materially different
runtime/driver substrate." The topology DOES suggest a possible path
(same-card PM8533 fanout ancestry), and substrate replacement (ROCm/HIP
compute ICD, different loader/driver) would be required — which the
issue forbids introducing.

## Why this is not `V2E_V340L_P2P_UNAVAILABLE`

`P2P_UNAVAILABLE` requires the CURRENT physical/kernel/IOMMU/ACS/
device-group authority to mechanically establish that direct peer
access is unavailable. The retained capability census establishes an
API-level absence on the accepted stack, not a platform-level
prohibition. Notable supporting (non-authoritative) context retained
in the preflight: ACS is ENABLED on both Vega bridge downstream ports
(05:00.0/08:00.0: `SrcValid+ ReqRedir+ CmpltRedir+ UpstreamFwd+`),
which would redirect peer transactions upstream even if an API path
existed — a routing-config observation, not a capability prohibition,
and explicitly not promoted to authority per the issue's "verify, do
not promote" instruction for operator observations.

## Topology and health retained (Phase 1, read-only)

- Complete `lspci -PP -nn -vv` for the whole root→switch→die path:
  root port `00:1d.0` (PCH RP#11, LnkCap/ Sta Gen3 x1), PM8533
  upstream `02:00.0` (LnkSta Gen3 x1; AER correctable RxErr baseline
  ~1.47M retained — the known background class on this port),
  downstream `03:00.0`/`03:01.0` (Gen3 x16), separate Vega bridge
  chains `04:00.0/05:00.0 → 06:00.0` (die A) and
  `07:00.0/08:00.0 → 09:00.0` (die B; upstream bridge 07:00.0
  negotiates `Width x1 (downgraded)` — a fresh observation retained in
  the raw lspci bytes, distinct from V2-C's ledger row).
- Both dies: Gen3 x16 endpoint links, 8 GiB HBM each (heap map
  retained inside the capability census), amdgpu-bound, distinct IOMMU
  groups (14 / 17).
- Fresh mapping (R3 zero-token identity probes, no model tokens):
  `Vulkan1 ↔ 06:00.0` (die A), `Vulkan2 ↔ 09:00.0` (die B),
  corroborating the accepted V2-B/V2-C authority identity
  (`evidence/preflight/mapping/`).
- Journal fault baseline at collection: zero fault-class lines in the
  current boot window; AER/telemetry baseline retained in
  `evidence/preflight/preflight.json`.

## Safety inheritance (V2-D)

The retained #216 fault (`V2D_V340L_PLATFORM_STRESS_FAIL`: die B
ring-gfx timeout, failed reset ret=-62, wedged reset worker during the
accepted #35 x1 transport seam) is pinned inside
`PHYSICAL-AUTHORITY.json` as a hard constraint and carried in
`evidence/ASSEMBLY.json` as inherited context (not re-counted in this
campaign's window). V2-E executed no transfer at all; the refusal
path is the safety-correct outcome of the mechanism gate.

## Non-claims (inherited, unchanged)

No coherent 16-GiB GPU address space; no xGMI / Infinity Fabric; no
unified-memory semantics; no model-inference correctness or utility;
no production V340L support; no multi-card X12 compatibility; no
generic planner preference; no sustained dual-die stability claim; no
safety claim for the #216 faulting transport mechanism. Correctable
AER RxErr activity on the PM8533 upstream port is retained
quantitatively and is not promoted to any failure threshold.

## Evidence layout

- `evidence/preflight/` — Phase 1-2 census: 31 probes with raw bytes +
  receipts, fresh mapping, capability census + external-memory matrix,
  health/journal baselines.
- `evidence/ladder/refusal.json` — Phase 3 mechanism-gate refusal
  (frozen ladder never executed).
- `evidence/baselines/refusal.json` — Phase 4 refusal (controls for
  peer arms that do not exist; #216 seam not rerun).
- `evidence/ASSEMBLY.json`, `evidence/TERMINAL.json` — deterministic
  reduction (regenerable: `scripts/issue228_assemble.py
  --evidence-root docs/investigations/vulkan-v2-e-v340l-peer-link/evidence`).
- `PHYSICAL-AUTHORITY.json`, `PRODUCER-CLOSURE.json` — frozen authority
  and executed-byte closure.
- `MANIFEST.sha256` — regenerated by `scripts/issue228_manifest.py`
  (never hand-edited).

## Successor implications

The result determines the next experiment boundary the issue asked
for: a cross-die inference placement experiment is NOT justified on
the current stack — any A↔B data path would be host-mediated through
the shared Gen3 x1 root link (already characterized by the accepted
#35 envelope and the retained #216 transport evidence). Revisiting the
peer-link question requires a different, explicitly-authorized runtime
substrate decision (e.g. a compute ICD with dmabuf peer support),
which is a maintainer decision outside this campaign.
