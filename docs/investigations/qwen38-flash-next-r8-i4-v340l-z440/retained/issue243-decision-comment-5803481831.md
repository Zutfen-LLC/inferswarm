# R8-I4 — V340L on high-RAM Z440 (inferswarm05) practicality + stability characterization

Issue #243. Campaign `issue243-r8i4-v340l-z440-characterization`.
Starting main: `3aa59aed74df7f00302a6a2eb84640623b7cc14b` (#237/PR #238
merge, verified ancestor of origin/main at campaign start).

## Decision report (pre-closure, per issue contract)

1. Starting main SHA: `3aa59aed74df7f00302a6a2eb84640623b7cc14b`.
2. Host: inferswarm05, machine-id `39ac8e342ef845c2a0a90c7c7a407243`,
   HP Z440 (baseboard 103C-212B per dmidecode), Xeon E5-2683 v3
   (14C/28T, 2.0-3.0 GHz), 134,985,306,112 B RAM (~125.6 GiB),
   swap 6,609,170,432 B on /dev/sda3 (never used: SwapFree constant),
   root SSD 112 GiB (LITEONIT LCT-128M3S), model backing 1.9 TB SATA
   SSD (TEAM T2532TB) at /srv/models (ext4, noatime), Debian 13
   trixie, kernel 6.12.107+deb13uamd64, no amdgpu cmdline params.
3. V340L: both Vega10 dies [1002:6864] rev 05, subsystem 1002:0c00,
   VBIOS 113-D0531800-101 (both), amdgpu 3.61.0 driver, 8,573,157,376 B
   HBM2 each (7.984 GiB), MEM ECC active. Vulkan: two "AMD Radeon Pro
   V340 (RADV VEGA10)" physical devices, Mesa 25.0.7-2+deb13u1,
   loader 1.4.305 (libvulkan1 Debian 13). GTX 1060 3GB (nouveau,
   02:00.0) present but excluded from all campaigns (ICD-restricted).
   Vulkan UUID encodes BDF: GPU0->07:00.0, GPU1->0b:00.0.
4. PCIe: both dies behind root port 00:03.0 (Gen3 x16 capable), idle
   AND loaded link = 8.0 GT/s x16 both dies (verified under load in
   phase 4/6 samples; not only idle).
5. BARs: 8G prefetchable 64-bit MMIO per die (380400000000 /
   380000000000), non-overlapping, above 4G. IOMMU: disabled (0
   groups). 512K MMIO + 2M prefetch BARs per die.
6. Cooling: temporary high-CFM 140 mm fan attached at card rear
   (operator arrangement; retained as described, no shroud).
7. Thermal burn-in (15 min each, model-driven at top ladder rung
   ngl=7, ~6.3 GiB residency):
   - die0 (07:00.0): junction 32-39C, edge <=35C, power <=33 W,
     THERMAL_PLATFORM_STABLE_FOR_BOUNDED_TESTING;
   - die1 (0b:00.0): junction 41-44C, power <=31 W, stable;
   - dual (both dies, independent servers): junction 32-34C / 41-55C,
     both stable; zero amdgpu resets/faults/GPU hangs, zero AER/
     pcieport errors, zero process failures in ALL windows.
8. Frozen HBM reserve: 1,073,741,824 B (1.0 GiB) per die, frozen
   before any comparative performance observation.
9. Placement law (fresh, from sysfs residency deltas at ngl=1/2/3 on
   this host): per-layer 939.07 MiB, output-head 1003.31 MiB, budget
   7152 MiB -> mechanical max ngl=7. Frozen ladder: 1, 2, 4, 6, 7.
10. Selected rung: ngl=7 (6.29-6.32 GiB selected-die residency =
    ~79% of the 7.984 GiB die; excluded die flat at ~8 MiB Vulkan
    instance noise, far below the 64 MiB frozen noise bound).
11. Excluded-die proof: every rung/regime/dual record carries both
    BDFs' mem_info_vram_used; excluded die never exceeded ~12 MiB
    during single-die phases.
12. Host memory behavior: RSS ~27.7 GB (mostly RssFile, the lazy
    PLE/mmap tier), Anonymous <1 GB, VmSwap 0, read_bytes 0, major
    faults ~57 total (first-touch), iowait 0.0000 in every sample.
    MemAvailable never dropped below ~120 GiB.
13. Old pathology REMOVED: process physical reads = 0 bytes and
    warm==cold wall times (<3% delta) on every case, versus #240's
    inferswarm02 measurements of ~55-319 GB repeated physical reads
    per request class under ngl=1. The Z440 host eliminates the
    pathological repeated physical model reads / page-cache thrash.
14. Historical-regime wall times (die0, ngl=7, warm repeats;
    cold/first-touch within ~5%):
    - case-256 (256 tok): 13.0-13.6 s wall; prompt 24.6 tok/s;
      decode 2.13 tok/s
    - case-1024 (1022 tok): 24.3-24.7 s; 48.1 tok/s; 2.01
    - case-3072 (3077 tok): 62.8-64.3 s; 52.3 tok/s; 1.76
    - case-4096 (4097 tok): 79.6-81.3 s; 53.1 tok/s; 1.68
    (die1 within ~2% of die0 on every case; per-case token streams
    die0==die1 for all four cases at this geometry.)
15. #240 comparison (mechanically comparable ngl=1 baseline retained
    here too): rung ngl=1 wall ~14.4-15.0 s case-256. inferswarm02
    #240 measurements at matched minimal placement were dominated by
    host-memory/USB-I/O; here even ngl=1 shows read_bytes=0 with
    warm stability because the whole 72.5 GB model fits the page
    cache of 125.6 GiB RAM and the backing is a local SATA SSD.
16. Projected 1,416-case campaign (engineering projection ONLY, from
    measured per-regime warm walls; equal 4-regime split, sequential
    single-die): ~1416/4 * (13.6+24.7+63.9+81.3)/4 * ... = mean wall
    ~45.9 s/case -> ~18.0 hours sequential on ONE die; ~9 hours using
    both dies concurrently (dual-phase measured per-die wall inflation
    <2% for die0's case-256 class; die1 mixed-case mean 52.6 s
    reflects its case mix, not contention).
17. Die symmetry: comparable schedulable resources. Placement success
    identical, HBM identical, per-case walls within ~2%, token
    streams identical at this geometry, independent telemetry healthy
    on both. (Scheduling characterization only — NOT a numerical-
    equivalence qualification; byte-identical FP output was not an
    interchangeability criterion per issue text.)
18. Concurrent dual-die: PASS. Two independent llama-server processes,
    one per freshly-bound die, 15 min representative mixed-regime
    load: zero amdgpu faults, zero AER, zero cross-device leakage
    (each die held exactly its own 6.29 GiB residency), junction
    max 55C (die1), per-workload throughput ~ single-die execution.
19. Kernel/amdgpu/AER health: clean across every retained window
    (the only AER lines in any window are boot-time "AER: enabled"
    announcements, not errors).
20. Loaded PCIe authority: 8 GT/s x16 under load on both dies.

## Disposition

**`R8I4_V340_Z440_PRACTICAL_SINGLE_DIE_AND_DUAL_RESOURCE`**

All criteria met: burn-in stable; materially useful single-die Qwen
placement (ngl=7, 79% die occupancy) stable; old host-I/O pathology
materially removed (0-byte physical reads, 0 iowait); both dies
individually usable; simultaneous independent die workloads stable;
projected 1,416-case bounded workload operationally practical
(~18 h sequential / ~9 h dual-die engineering projection); predictive
calibration/holdout untouched (negative controls below).

A V340L-specific comparator/2 numerical-qualification successor IS
justified by this evidence (recommendation), to be proposed as a
child issue; it does not itself unblock #239/R8-J.

## Negative controls (all PROVEN absent)

1. zero c237-* predictive execution (only the 4 historical-excluded
   R8-B fixtures ran; fixtures.json sha256-verified against R8-H
   authority anchor);
2. zero holdout decrypt/read/secret access (custody record hashes
   unchanged; worktree clean at starting SHA);
3. exact model member bytes (3/3 sha256 match the frozen authority
   on the execution host, retained SHA256SUMS.is243);
4. exact pinned runtime (llama-server sha256
   21707f2568d80fb781b445cd472588e83501e1cc66dcf10885b286e34c02573e,
   commit b29c606e2 in --version output; Vulkan-only build: no CUDA
   device ever listed; CUDA_VISIBLE_DEVICES=-1 set on every launch);
5. no CUDA participation (Vulkan build has no CUDA backend);
6. no CPU-only/wrong-device fallback (per-BDF residency proves the
   selected die carried model-scale buffers every run);
7. no stale inferswarm02 identity reuse (fresh census; 02's BDFs
   06:00.0/09:00.0 vs 05's 07:00.0/0b:00.0);
8. die ordering freshly bound (placement-probe idx->BDF via sysfs
   delta, re-proven per phase);
9. excluded die never obtained material residency (max ~12 MiB =
   Vulkan instance noise);
10. no coherent-16GiB claim (each die addressed independently; no
    cross-die memory or P2P used);
11. no OOM-then-silent-reduction (top rung = mechanical budget max;
    no rung failed);
12. placement chosen by frozen budget arithmetic, never by output
    agreement or preferred tokens;
13. no thermal fault ignored (all fail-closed predicates evaluated on
    every window; zero hits);
14. loaded-link authority retained (8 GT/s x16 under load);
15. no cold-cache manipulation (natural first-touch vs warm repeats
    retained as-is);
16. physical reads MEASURED (/proc/pid/io read_bytes=0), not
    estimated;
17. dual-die: each process proven bound to its own die (per-BDF
    residency);
18. #240 evidence referenced as historical only, never rewritten;
19. no R8-J dispatch or unblock claim;
20. no planner policy change (repository untouched in this phase).

## Non-claims

No coherent 16-GiB VRAM pool. No predictive qualification, no
threshold derivation, no R8-J unblock. Token-stream equality between
dies is an engineering observation at this geometry, not a numerical-
equivalence result. Performance figures are descriptive of this
host/GPU/cooling arrangement only.

STOP FOR MAINTAINER REVIEW at this decision point (per issue
contract). Closure work (durable investigation record, manifest,
PCIe ledger update, PR) only after maintainer GO.
