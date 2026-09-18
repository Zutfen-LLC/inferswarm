# V2-D — concurrent V340L dual-die qualification (issue #216) — CORRECTED campaign

Status: COMPLETE — terminal **`V2D_V340L_PLATFORM_STRESS_FAIL`**
(retained; derived by `scripts/issue216_assemble.py` from retained
bytes; see `evidence/ASSEMBLY.json`).

Campaign: `issue216-v2d-v340l-concurrent-dual-die-v2`
Authority: `PHYSICAL-AUTHORITY.json` (intended identity from accepted
V2-B/V2-C manifest-pinned bytes; #219 corrected-seam runtime pins).

## Why a corrected campaign

The original tooling's producer closure (schema /2) hashed the Git
INDEX (`git show :<path>`) while Python executed WORKING-TREE bytes —
it could not prove executed-byte identity. The correction (PR #221
correction campaign) replaced it with a fail-closed producer freeze
(schema /3: worktree == index == HEAD per closure source, pinned
producer head, self-bound digest) and rebuilt every reducer named in
the correction spec (mapping→execution binding, sentinel re-derivation,
fault-arm exactness, transport re-derivation, soak hardening, reset
re-derivation), then re-ran the physical campaign under the corrected
freeze. Reduction-only changes after retained output are admitted via
`AMENDMENTS.json` with a mechanical collector-unchanged proof.

## Chain-2 results (producer pin d921033, evidence head f6af8c7)

1. Preflight (fresh topology/mapping/sentinels): PASS — both fresh
   sentinels correct (re-derived from raw bytes), journal fault-free;
   fresh mapping Vulkan1 ↔ `0000:06:00.0`, Vulkan2 ↔ `0000:09:00.0`
   (R3 re-verified; every execution argv-selector + stderr-BDF bound
   to it).
2. Single-die baselines (3 reps each): both dies 3/3 correct, full
   offload, accounting 0/0/0, correct die identity throughout.
3. Concurrent pairs c01/c02/c03: 3/3 clean repeats, seam-classified
   OVERLAP. #219 overlap lower bounds: c01 2 511 893 ns,
   c02 4 588 483 ns, c03 2 586 522 ns. (The stale "+~9.17 ms on c01"
   statement described the superseded chain's assembly and is removed.)
4. Transport: single-A arm completed clean. The single-B probe was in
   flight when the platform fault (below) struck.

## The retained platform fault (why the terminal is STRESS_FAIL)

2026-09-18 16:28:33 EDT (20:28:33 UTC), seconds after the transport
phase began: `amdgpu 0000:09:00.0: ring gfx timeout, signaled
seq=5131, emitted seq=5132` while the accepted #35 probe measured
die B. The driver dumped IP state (devcoredump created), the GPU
reset FAILED (`GPU reset end with ret = -62`), and the reset kworker
wedged in `dm_suspend` (D-state) for over an hour; the probe process
hung uninterruptibly in `dma_fence_wait` inside `amdgpu_vm_fini` on
device close. The host needed a reboot, which itself stalled on the
wedged kworker before eventually completing.

Retained proof: `evidence/fault-capture/` (dmesg at fault, full
boot journal at fault, process states incl. the D-state stack, both
dies' lspci -vvv, SHA256SUMS verified). The assembler's campaign-
window fault scan (journalctl + dmesg -T grammars; window bounded by
the phase records' own timestamps) re-derives 9 in-window fault lines
from the journal capture and classifies
`V2D_V340L_PLATFORM_STRESS_FAIL`.

Per issue #216's terminal vocabulary: a valid frozen campaign whose
retained evidence positively demonstrates a GPU hang/reset is a
PLATFORM_STRESS_FAIL — never relabeled, never erased by later missing
evidence (soak/fault/reset never ran after the fault), and the
campaign may not be rerun under the same authority seeking a PASS.

Honest context: the SUPERSEDED chain-1 (defective index-based closure;
`evidence-superseded-v1/`) completed ALL phases cleanly — including a
3600 s soak and both fault arms — the same evening, hours before
chain-2 hit the fault. Within chain-1 the producers were frozen
byte-stable for its whole run (git diff over its own span is empty),
but chain-1's collector bytes are NOT identical to chain-2's: the
correction branch rebuilt 7 of 9 physical producers between the
chains, so cross-chain tooling-regression claims are NOT what the
byte-diff proves. What the evidence does establish: chain-2 itself —
under the corrected, executed-byte-proven freeze — passed preflight,
baselines, and 3/3 concurrent pairs, then hit the fault; the fault
lines are kernel-originated (ring gfx timeout, driver-initiated reset,
ret=-62) on the mapping-verified die B, and no producer defect can
synthesize kernel journal lines. The fault is retained as a platform
observation of this V340L dual-die topology under sustained concurrent
load; chain-1's earlier clean completion does not erase it.

## Non-claims (inherited + fault-driven)

- Device-level reset isolation was NOT executed; the read-only
  determination (`DEVICE_RESET_ISOLATION_NOT_AVAILABLE`) is retained
  — both Vega functions sit behind one physical PM8533 fanout switch
  and no documented function-isolated reset exists for this topology.
- No throughput threshold is a PASS predicate anywhere; transport
  magnitudes are descriptive only.
- The topology is NOT qualified as a trustworthy concurrent resource:
  the retained fault stands against it.
- No 16-GiB unified memory claim; no model-specific Qwen/DeepSeek
  qualification; no mixed-vendor execution; no planner policy; no
  production support.
- Correctable PCIe AER events on the NVMe fanout path (02:00.0,
  Phison 11f8:8533) appeared at background rates all day (554 lines);
  they are correctable-error noise on the switch port, not GPU faults.

## Evidence layout

- `evidence/` — chain-2 retained output: 143 files total (phase
  records/raw bytes plus `fault-capture/`; the 141 figure sometimes
  cited counts phases before ASSEMBLY/TERMINAL were emitted).
- `evidence-superseded-v1/` — chain-1 output under the defective
  /2 closure (762 files); retained history, never deleted; see its
  README for what it DID prove and why it cannot carry terminal
  authority.
- Phase summaries at the evidence root; raw bytes in phase subdirs;
  receipts bind raw bytes by content; `PRODUCER-CLOSURE.json`
  (schema /3), `AMENDMENTS.json`, `MANIFEST.sha256` regenerated by
  `scripts/issue216_manifest.py` (never hand-edited).
