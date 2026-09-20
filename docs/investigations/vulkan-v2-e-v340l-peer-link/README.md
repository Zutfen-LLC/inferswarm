# V2-E — V340L inter-die peer-link qualification (issue #228)

Status: CORRECTION ROUND 2 — attempt-1 campaign SUPERSEDED (invalid
capability-census producer); corrected producers + corrected read-only
census (attempt `pf2`) retained; transfer execution HARD-DISABLED.
Round 2 is a reduction-only amendment (see `AMENDMENTS.json`): the
round-1 derived verdict and prose mis-stated dma_buf; both fd-carried
handle types are now classified from the unchanged raw bytes exactly
as the retained observations justify. Terminal re-derived mechanically
from the corrected attempt: **`V2E_EVIDENCE_BLOCKED`** (capable
mechanisms advertised; no reviewed transfer implementation; zero
transfers executed). PR OPEN/UNMERGED awaiting maintainer exact-head
review.

Campaign: `issue228-v2e-v340l-interdie-peer-link`

## Superseded attempt-1 (pf1, NON-AUTHORITATIVE history)

The original campaign (producer pin `8c25184`, closure `/1` digest
`0973306a…`) claimed `V2E_V340L_P2P_API_PREREQUISITE` from a census
whose Vulkan instance was created WITHOUT `pApplicationInfo` — a
Vulkan 1.0 instance per the specification — while calling Vulkan 1.1
core functionality (`vkEnumeratePhysicalDeviceGroups`,
`vkGetDeviceGroupPeerMemoryFeatures`). Under that invalid
configuration the negative observations cannot establish that a
different runtime is required. The maintainer exact-head review of
c9822fe returned NO-GO. All attempt-1 evidence is preserved byte-for-
byte under `evidence/attempt-1-superseded/` with its original
producer/closure bindings and file identities; nothing was relabeled
as output of a corrected producer. Machine-readable supersession
record: `evidence/SUPERSESSION.json` (also retains, for the record:
the non-spec peer-query argument order; the transfer path's
device-zero execution labeling; OR-gated external-memory mechanism
authorization; permissive reduction accepting incomplete repetitions
and mapping correctness failures to a functional terminal).

## Corrected attempt (pf2)

Correction sequence (freeze-before-output honored): corrected
producers committed and pushed FIRST, producer closure re-frozen at
the corrected head (closure `/1`, new digest), closure verified on
inferswarm02, then the corrected read-only census collected under
attempt `pf2` and retained separately from the superseded attempt.
Zero transfers were executed at any point (the fence is structural —
see below).

### What the corrected census establishes (physically bound)

Every enumerated device carries its `deviceUUID` (the RADV UUID
encodes the PCI BDF) and the census is joined to the fresh accepted
A/B mapping by UUID→BDF corroboration — never by name substring or
enumeration order. The census ran under an explicit Vulkan 1.1
instance configuration (requested 1.1.0, effective loader 1.4.309;
versions and relevant instance/device extension availability retained
in the census artifacts):

1. **Device-group peer path**: the loader exposes every physical
   device in a single-device group — the two V340 dies are never
   co-members of any group, so `VkDeviceGroupDeviceCreateInfo` cannot
   span the dies and `vkGetDeviceGroupPeerMemoryFeatures` (invoked in
   its spec argument order by the corrected probe) is unreachable for
   the pair on this stack.
2. **External-memory path**: valid resource usages only (the invalid
   zero-usage rows of the superseded round are excluded from
   authoritative decisions). Host-only handle types (host_allocation /
   host_mapped_foreign) are recorded as observations and never treated
   as direct peer access.

**The corrected census FINDS capable mechanisms the superseded census
reported absent.** On BOTH dies, for transfer-usage buffers, the
retained raw observations report, for BOTH fd-carried handle types:

- `VK_KHR_external_memory_fd` and `VK_EXT_external_memory_dma_buf` are
  enumerated as DEVICE extensions on both dies (the loader exposes
  neither as an INSTANCE extension — that instance-level `false` is a
  scoped observation, not absence of the device extension);
- `opaque_fd`: exportable=true, importable=true,
  compatibleHandleTypes=513;
- `dma_buf`: exportable=true, importable=true,
  compatibleHandleTypes=513 (0x1|0x200 — the mask carries the dma_buf
  registry bit).

The round-1 derived verdict mis-classified dma_buf as
handle-type-incompatible because the frozen producer validator's bit
table mapped dma_buf to 0x80 (HOST_ALLOCATION's bit; the registry
value is 0x200), so its mask test `513 & 0x80 == 0` failed against
the same retained bytes; the accompanying prose additionally denied
the device-extension enumeration. Both statements are corrected by
this round: the reduction-layer re-derivation
(`scripts/issue228_reduce.py::rederive_external_memory`, recorded in
`AMENDMENTS.json`) classifies BOTH `opaque_fd` and `dma_buf` as
advertised-bidirectional for transfer-usage buffers.

**Advertisement is not validated execution.** These are API
property-query advertisements (extension enumeration + feature flags +
compatible-handle-type masks). Neither handle type has a reviewed
cross-device transfer implementation in this campaign, zero transfers
were executed, and nothing here establishes whether either path
actually moves data between the dies, how it performs, or what
physical route (switch-internal or host-facing x1) it would use.

Because capable mechanisms ARE advertised (both `opaque_fd` and
`dma_buf`, transfer-usage buffers, both directions) but this campaign
has no reviewed transfer implementation (execution hard-disabled), no
measured transfers exist and no functional peer-path conclusion is
derivable. The mechanically derived terminal for attempt pf2 remains
**`V2E_EVIDENCE_BLOCKED`**: the evidence cannot establish an
authorized classification. This is NOT `P2P_API_PREREQUISITE`
(advertised in-stack mechanisms exist — the superseded round's
prerequisite conclusion is retired), NOT a functional claim, and NOT
a claim that the advertised capability would work in practice
(advertised capability is not validated execution).

## Transfer fence (structural)

Physical transfer execution is disabled in code for this campaign:
the attempt-1 transfer producer — which retrieved one logical queue
for every group device, submitted without device-group execution
masks (all work executed on device zero), and allocated two command
buffers into scalar handles in its staged/bidir paths — was DELETED,
not repaired. `issue228_ladder.authorize_execution` always refuses
(0 transfers), and the assembler rejects any ladder artifact
outright. Re-enabling physical transfers requires a new, reviewed
producer; a corrected positive census can never authorize the old
ladder.

## Topology and health context (retained read-only)

Unchanged from the attempt-1 preflight and still retained verbatim
under `evidence/attempt-1-superseded/preflight/` (raw lspci/-vv/ACS/
IOMMU/AER/journal bytes; same-card PM8533 fanout ancestry; die B
bridge `07:00.0` width-downgrade observation; ACS enabled on both
Vega bridge downstream ports — routing-config context, not capability
authority). The corrected pf2 preflight re-collects this context
freshly; both attempts' bytes are retained.

## Safety inheritance (V2-D)

The retained #216 fault (`V2D_V340L_PLATFORM_STRESS_FAIL`: die B
ring-gfx timeout, failed reset ret=-62, wedged reset worker during
the accepted #35 x1 transport seam) remains pinned inside
`PHYSICAL-AUTHORITY.json` (unchanged, sha256
`621d465f…`) as a hard constraint. V2-E executed no transfer in
either attempt; the refusal path is the safety-correct outcome.

## Non-claims (inherited, unchanged)

No coherent 16-GiB GPU address space; no xGMI / Infinity Fabric; no
unified-memory semantics; no model-inference correctness or utility;
no production V340L support; no multi-card X12 compatibility; no
generic planner preference; no sustained dual-die stability claim; no
safety claim for the #216 faulting transport mechanism; advertised
capability is never conflated with validated execution. Correctable
AER RxErr activity on the PM8533 upstream port is retained
quantitatively and is not promoted to any failure threshold.

## Evidence layout

- `evidence/attempt-1-superseded/` — the complete superseded attempt-1
  tree (preflight incl. raw bytes + fresh mapping, ladder/baselines
  refusals, ASSEMBLY/TERMINAL), byte-preserved.
- `evidence/SUPERSESSION.json` — machine-readable supersession record.
- `evidence/preflight/` — corrected attempt-pf2 census (validated,
  UUID-bound), fresh pf2 mapping, raw probe bytes.
- `evidence/ladder/refusal.json`, `evidence/baselines/refusal.json` —
  corrected-attempt execution refusals (0 transfers).
- `evidence/ASSEMBLY.json`, `evidence/TERMINAL.json` — deterministic
  reduction of the corrected attempt (regenerable:
  `scripts/issue228_assemble.py --evidence-root <this dir>/evidence`).
- `PHYSICAL-AUTHORITY.json`, `PRODUCER-CLOSURE.json` — frozen authority
  (unchanged) and the re-frozen executed-byte closure.
- `AMENDMENTS.json` — reduction-only amendment ledger (accepted #216
  protocol): pins the evidence closure the retained pf2 bytes bind and
  mechanically proves the collector producers byte-unchanged.
- `MANIFEST.sha256` — regenerated by `scripts/issue228_manifest.py`
  (never hand-edited).

## Successor implications

A cross-die inference placement experiment is NOT justified on the
current evidence. The corrected census has NOT established any
physical route — no transfer occurred, so whether an A↔B path via
`opaque_fd` or `dma_buf` is switch-internal or host-mediated through
the shared Gen3 x1 root link is unmeasured (the accepted #35 envelope
and the retained #216 transport evidence characterize the host-facing
x1 link itself, not the route any external-memory transfer would
take). Justifying a placement experiment requires a separately
reviewed, #216-safety-classified external-memory transfer producer
that establishes correctness, performance, and route — a maintainer
decision outside this campaign.
