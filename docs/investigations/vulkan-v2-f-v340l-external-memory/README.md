# V2-F — V340L external-memory inter-die transfer qualification (issue #230)

Status: PRODUCERS FROZEN — awaiting physical campaign execution on
inferswarm02 under this exact closure. This README is the frozen
methodology + runbook; physical results land under `evidence/` only
after the producer freeze is committed and verified on the host.

Campaign: `issue230-v2f-v340l-external-memory`

Successor to #228 (merged `78a91de`), which closed V2-E at
`V2E_EVIDENCE_BLOCKED`: both fd-carried handle types
(`opaque_fd`, `dma_buf`) are ADVERTISED-bidirectional for
transfer-usage buffers on both dies, but zero transfers were executed
and no reviewed implementation existed. V2-F supplies the reviewed
implementation and executes it under the #216 safety bound.

## State dimensions (never conflated)

1. **ADVERTISEMENT** — #228's corrected pf2 census, consumed as
   prerequisite authority via `PHYSICAL-AUTHORITY.json` (the accepted
   round-2 amended classification; every predecessor manifest row
   re-hashed at every authority build/verify — byte preservation is
   mechanically enforced, and re-collection of the census "merely to
   seek a different answer" is refused).
2. **IMPLEMENTATION** — `scripts/issue230_transfer.py`'s embedded C
   producer (this campaign's reviewed transfer implementation).
3. **VALIDATED EXECUTION** — measured, exactly-verified transfers in
   both directions over the frozen ladder population.
4. **PHYSICAL ROUTE** — derived only from MEASURED behavior under the
   frozen `ROUTE_RULE` (never from Vulkan's "external memory" naming).

## The transfer mechanism (Arm A opaque_fd / Arm B dma_buf)

One process; explicit `VkApplicationInfo` (API 1.1). Physical devices
are enumerated, each device's BDF derived from its
`VkPhysicalDeviceIDProperties` deviceUUID (RADV encodes the BDF), and
source/destination are selected BY EXPECTED BDF from the retained
fresh mapping — never by enumeration order or name substring. TWO
SEPARATE logical devices are created (one per physical device; no
device-group chaining, so no device-zero ambiguity), each enabling
`VK_KHR_external_memory_fd` (+ `VK_EXT_external_memory_dma_buf` for
the dma_buf arm only).

Per arm: a device-local exportable source buffer on the source die; a
host-visible staging buffer on each die; ONE fd exported via
`vkGetMemoryFdKHR`; the destination device queries
`vkGetMemoryFdPropertiesKHR` (fail-closed memory-type intersection),
imports the fd, and executes THE measured inter-die transfer as a
destination-submitted `vkCmdCopyBuffer(dst_local <- src_imported)`
under an explicit per-submit VkFence (sequential; never concurrent).
Every rep fills the source with a position-dependent deterministic
pattern through the source's staging (H2D on the source die only —
setup, not measured), runs the measured copy, then reads the
destination back through its own staging and verifies EVERY dword.
A mismatch prints the failing rep and exits 4 — the immediate-stop
correctness condition; no later rep runs.

fd lifecycle: `opaque_fd` transfers fd ownership to the driver on
successful import; `dma_buf` fds are closed by the caller after
import. Failure paths always close. Handle-type independence is
structural: separate arms, separately enabled extensions, distinct
bits; one arm's success is never evidence for the other.

Controls (same producer, `samedie`/`hoststaged`/`linkio` subcommands):
same-die device-local copy per die; explicit host-staged A→host→B and
B→host→A; fresh H2D/D2H per die over the ladder sizes with the same
rep policy.

## Safety (#216 inheritance) — machine-enforced

`safety-classification.json` (produced at preflight, retained) records
the classification of this seam against the #216 faulting transport
seam (llama.cpp #35 x1 transport under sustained CONCURRENT dual-die
load → ring-gfx timeout on die B, failed reset ret=-62): materially
different (no transport stack, no model, no concurrency — exactly one
submit in flight platform-wide, bounded sizes, immediate stop). The
`issue230_safety` order state machine REFUSES:

* any arm whose predecessors have not all passed (probe before
  ladder, ladder before controls; opaque_fd arms before dma_buf arms);
* any duplicate execution under the same authority (no rerun seeking
  a cleaner result);
* ANY arm after any failure (retained earliest failure halts
  escalation permanently).

First physical execution is ONE 4-KiB probe, a_to_b, opaque_fd —
never a benchmark ladder. Immediate-stop conditions (correctness
mismatch; ring timeout/hang; GPU reset; device disappearance;
fatal/nonfatal uncorrectable AER; kernel wedge; host reachability
loss; thermal critical; unexpected fallback/staging; any nonzero probe
exit) are evaluated per arm from the health window (AER deltas on all
7 health BDFs, amdgpu journal scan with cursor chaining, link state,
VRAM/busy telemetry, gateway ping, NIC counters, storage sentinel).

## Frozen ladder / route rule

Ladder: 4 KiB, 64 KiB, 1 MiB, 16 MiB, 64 MiB, 256 MiB — 5 measured
reps + 1 warmup per (mechanism, direction, size). 1 GiB is NOT
authorized by this campaign. Route classification (per functional
mechanism/direction, 256 MiB medians): `LOCAL_SWITCH_BYPASS_PROVEN`
iff peer > 1.25 × measured x1 ceiling; `UPSTREAM_OR_HOST_ROUTE_PROVEN`
iff peer within the ceiling AND within [0.70, 1.40] × host-staged
control; otherwise `PEER_FUNCTIONAL_ROUTE_UNRESOLVED`. The x1 ceiling
is MEASURED (fresh linkio per-leg medians; conservative 2·size/elapsed
fallback), never nominal Gen3 arithmetic. A bypass claim requires the
matched controls to exist.

## Runbook (inferswarm02, one arm per invocation)

```
# 0. sync worktree to the frozen producer head; tree clean
git fetch && git reset --hard <producer-head>
# 1. authority + preflight (read-only)
python3 scripts/issue230_authority.py build
python3 scripts/issue230_preflight.py --out /srv/inferswarm/is230/evidence/preflight \
    --authority docs/investigations/vulkan-v2-f-v340l-external-memory/PHYSICAL-AUTHORITY.json
# 2. arms, in the frozen order (each refuses unless predecessors passed)
python3 scripts/issue230_runner.py probe   --mechanism opaque_fd --direction a_to_b --evidence-root <ev>
python3 scripts/issue230_runner.py probe   --mechanism opaque_fd --direction b_to_a --evidence-root <ev>
python3 scripts/issue230_runner.py ladder  --mechanism opaque_fd --direction a_to_b --evidence-root <ev>
python3 scripts/issue230_runner.py ladder  --mechanism opaque_fd --direction b_to_a --evidence-root <ev>
python3 scripts/issue230_runner.py controls --evidence-root <ev>
python3 scripts/issue230_runner.py probe   --mechanism dma_buf  --direction a_to_b --evidence-root <ev>
python3 scripts/issue230_runner.py probe   --mechanism dma_buf  --direction b_to_a --evidence-root <ev>
python3 scripts/issue230_runner.py ladder  --mechanism dma_buf  --direction a_to_b --evidence-root <ev>
python3 scripts/issue230_runner.py ladder  --mechanism dma_buf  --direction b_to_a --evidence-root <ev>
python3 scripts/issue230_runner.py controls-dma --evidence-root <ev>
# 3. reduction + terminal (deterministic; authored terminal must match)
python3 scripts/issue230_assemble.py --evidence-root <ev>
# 4. manifest (last)
python3 scripts/issue230_manifest.py
```

Any stop condition: STOP, retain, reduce (the assembler derives
`V2F_V340L_PLATFORM_STRESS_FAIL` from the order state automatically),
and report. Do not rerun.

## Evidence layout (after execution)

- `evidence/preflight/` — raw probe bytes, fresh mapping (R3 + V2-F
  identity probe join), safety classification, baseline health.
- `evidence/raw/` — per-arm probe stdout/stderr/exit-code bytes.
- `evidence/arms/` — per-arm results with health windows.
- `evidence/order-state.json` — digest-chained execution order.
- `evidence/ASSEMBLY.json`, `evidence/TERMINAL.json` — deterministic
  reduction (regenerable via `scripts/issue230_assemble.py`).
- `PHYSICAL-AUTHORITY.json`, `PRODUCER-CLOSURE.json` — frozen
  authority and the executed-byte closure.
- `MANIFEST.sha256` — regenerated by `scripts/issue230_manifest.py`.

## Non-claims

No coherent 16-GiB address space; no xGMI / Infinity Fabric; no
unified-memory semantics; no model inference correctness/utility; no
production V340L support; no multi-card X12 compatibility; no
sustained/soak stability; no safety claim for the #216 faulting
transport mechanism; advertisement never conflated with validated
execution; validated execution never conflated with route proof; no
kernel/driver/firmware/ICD/ROCm/HIP changes were made or are implied
(the accepted installed stack is tested as-is).
