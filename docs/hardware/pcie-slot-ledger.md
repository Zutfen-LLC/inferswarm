# InferSwarm PCIe Slot Ledger

> **Status: living hardware inventory.** Update this document whenever a GPU is moved, a riser or slot path changes, firmware changes lane allocation, or fleet hardware changes. Historical experiment evidence remains immutable; record the topology/repository revision used by an experiment rather than rewriting old results.

Initial baseline collected: 2026-09-13 via SSH (`dmidecode -t slot` + `lspci -PP -nn -vv`) for inferswarm01-04.  
Valinor audit added: 2026-09-13.  
Issue #189 R8-A accelerator census refresh (read-only sysfs/lspci/nvidia-smi, per-device VRAM measured): 2026-09-14 — see `docs/investigations/qwen38-flash-next-r8-a/hardware-census.json` for the authoritative per-resource record.  
Issue #196 living inventory refresh (Valinor RX 6800 XT installed; inferswarm02 RX 5600 XT observed alongside both Ellesmere): 2026-09-15 — raw receipts at `docs/hardware/current-inventory/2026-09-15/`.  
Last topology refresh: 2026-09-15.

The original inferswarm01-04 collection notes referenced raw JSON per host (`inferswarm0{1..4}.json`). Those captures were not included in this repository import and are not reconstructed here.

Speed key: 2.5GT/s=Gen1, 5GT/s=Gen2, 8GT/s=Gen3, 16GT/s=Gen4.
CAVEAT on "now" speeds: GPU links may downtrain link SPEED to Gen1 (2.5GT/s) at idle; negotiated width remains meaningful. Re-scan under load for true speed when speed matters.

## inferswarm01  (HP Z440, X99/C610 workstation, Debian 13)
| Slot | Designation | Capability | Wired | Occupant | Device LnkCap | Negotiated now |
|------|-------------|------------|-------|----------|---------------|----------------|
| 2 | SLOT 2 | PCIe 3.0 x16 | x16 | RTX 3060 LHR 12GB (GA106) @02:00.0 | Gen3 x16 | Gen1 x16 (idle downtrain) |
| 5 | SLOT 5 | PCIe 3.0 x16 | x16 | RTX 3060 LHR 12GB (GA106) @03:00.0 | Gen3 x16 | Gen1 x16 (idle downtrain) |
| 4 | SLOT 4 | PCIe 3.0 x8 | x8 | EMPTY (available) | - | - |
| 3 | SLOT 3 | PCIe 2.0 x8 | x4 | EMPTY (available) | - | - |
| 1 | SLOT 1 | PCIe 2.0 x4 | x1 | EMPTY (available) | - | - |
| 6 | SLOT 6 | legacy PCI 32-bit | - | EMPTY (available) | - | - |

## inferswarm02  (MINERDUDE 12XTREME, Intel 200-series/B250 PCH, Debian 13)
Current arrangement (V2-C platform-stability campaign, Issue #215,
2026-09-17 — mechanically measured and re-verified across baseline + 4 warm
reboots + 1 cold power cycle; raw receipts under
`docs/investigations/vulkan-v2-c-v340l-platform-stability/cycles-v2/`):

| Slot / root port | Designation | Capability | Occupant | Device LnkCap | Negotiated now |
|------|-------------|------------|----------|---------------|----------------|
| 00:1d.0 | PCH Root Port #11 (x1 wiring) | Gen3 x1 | **Microchip PM8533 fanout switch @02:00.0 [11f8:8533]** → two Vega 10 dies of the AMD Radeon Pro V340L: die A `1002:6864` @06:00.0, die B `1002:6864` @09:00.0, each 8,573,157,376 B HBM2, amdgpu-bound | switch upstream cap x16 | **Gen3 x1 (8.0 GT/s, width 1)** — stable across every qualified boot |
| (switch-internal) | PM8533 downstream 03:00.0 / 03:01.0 | Gen3 x16 | Vega 10 PCIe Bridges (1022:1470/1471) feeding each die | Gen3 x16 | Gen3 x16 |
| 00:1c.0 | DMI x1 | Gen1 x1 | Realtek RTL8111 GbE @01:00.0 [10ec:8168], driver r8169, addressed 10.0.0.137/24 | Gen1 x1 | Gen1 x1 |
| 00:14.0 | chipset USB | - | Intel 200-Series xHCI USB 3.0 [8086:a2af] + root hubs | - | - |
| (SATA) | - | - | root storage /dev/sda3 (ext4, 223.9G) | - | - |

GPU population on inferswarm02 is now exactly the V340L (two Vega 10
dies, ~16 GiB aggregate HBM2 as two independent 8 GiB resources). The
prior RX 5600 XT / Ellesmere / 3060 Ti arrangement recorded by Issue #196
(2026-09-15) is HISTORICAL — the host was restabilized after the V340L
installation incident and those cards are no longer observed. SR-IOV: 4
total VFs per die, 0 enabled.

## inferswarm03  (Tiger Lake-H platform, Debian 13)
| Slot | Designation | Capability | Occupant | Device LnkCap | Negotiated now |
|------|-------------|------------|----------|---------------|----------------|
| 1 | PCIEX16_1 | x16 (Gen3 observed on root port) | RTX 3060 LHR 12GB (GA106) @01:00.0 | Gen3 x16 | Gen1 x16 (idle downtrain) |
| 2 | PCIEX16_2 | x16 | RTX 3060 LHR 12GB (GA106) @03:00.0 | Gen3 x16 | Gen1 x4 (width-limited!) |
| 3 | PCIEX1_1 | x1 | EMPTY (available) | - | - |
| 4 | PCIEX1_2 | x1 | EMPTY (available) | - | - |
| - | onboard | Gen2 x1 | Intel I225-V 2.5GbE @05:00.0 | Gen2 x1 | Gen2 x1 |

## inferswarm04  (Intel 8-Series/C220 Haswell board, Debian 13)
DMI usage flags unreliable (all "In Use"); occupancy derived from lspci.
| Slot | Designation | Capability | Occupant | Device LnkCap | Negotiated now |
|------|-------------|------------|----------|---------------|----------------|
| 1 | J6B2 | x16 (root port Gen2) | RTX 3090 24GB (GA102) @01:00.0 | Gen2 x16 (native Gen4; platform-limited) | Gen1 x16 (idle downtrain) |
| 2 | J6B1 | x1 | (DMI claims In Use; no endpoint found) | - | - |
| 3 | J6D1 | x1 | (DMI claims In Use; no endpoint found) | - | - |
| 4 | J7B1 | x1 | (DMI claims In Use; no endpoint found) | - | - |
| 5 | J8B4 | x1 | Realtek RTL8111 GbE @03:00.0 | Gen1 x1 | Gen1 x1 |

## Valinor  (ASUS ROG STRIX B550-E GAMING, AMD B550 / AM4)

Valinor is the fleet's currently verified board-level PCIe 4.0 CPU-lane test host. Linux may identify the CPU/root complex with Starship/Matisse-family names; the physical motherboard is an ASUS ROG STRIX B550-E GAMING.

ASUS documents the two CPU-connected graphics slots as PCIe 4.0 x16 when PCIEX16_1 is used alone, or x8/x8 when PCIEX16_1 and PCIEX16_2 are both populated. PCIEX16_3 is chipset-attached PCIe 3.0 x4 and shares bandwidth with PCIEX1_1 and PCIEX1_2.

| Slot / path | Board capability | Current occupant | Endpoint/device max | Negotiated / observed now |
|-------------|------------------|------------------|---------------------|---------------------------|
| PCIEX16_1 (root port 00:03.1) | CPU PCIe 4.0 x16 alone; x8 in dual-slot split | XFX Speedster MERC 319 AMD Radeon RX 6800 XT (Navi 21) @09:00.0 behind on-card switch (07:00.0/08:00.0) | Endpoint Gen4 x16 | Root port AND card upstream port LnkSta Gen4 x8 (measured 2026-09-15) |
| PCIEX16_2 | CPU PCIe 4.0 x8 when paired with PCIEX16_1 | EMPTY (available) | - | - |
| PCIEX16_3 | B550 chipset PCIe 3.0 x4 | EMPTY (available) | - | - |
| PCIEX1_1 | B550 chipset PCIe 3.0 x1 | EMPTY (available) | - | - |
| PCIEX1_2 | B550 chipset PCIe 3.0 x1 | EMPTY (available) | - | - |
| M.2_1 (CPU) | CPU PCIe 4.0 x4 | Intel 660p NVMe @01:00.0 | Gen3 x4 | Gen3 x4 (device max) |
| onboard | B550 chipset path | Intel AX200 Wi-Fi | Gen2 x1 observed | Gen2 x1 |
| onboard | B550 chipset path | Intel I225-V 2.5GbE | Gen2 x1 observed | Gen2 x1 |

Board capability authority:
- [ASUS ROG STRIX B550-E GAMING specifications](https://rog.asus.com/us/motherboards/rog-strix/rog-strix-b550-e-gaming-model/spec/)
- [ASUS ROG STRIX B550-E GAMING user manual](https://dlcdnets.asus.com/pub/ASUS/mb/SocketAM4/ROG_STRIX_B550-E_GAMING/E16546_ROG_STRIX_B550-E_GAMING_UM_WEB.pdf)

Current interpretation (2026-09-15): the RX 6800 XT replaced the GTX 1060 3GB
in PCIEX16_1, and the Toshiba Cx5 NVMe adapter that occupied PCIEX16_2 was
removed (DMI reports PCIEX16_2 "Available"; no second CPU-PEG endpoint
exists; the only NVMe is the Intel 660p on the CPU M.2_1 path). With
PCIEX16_2 empty, ASUS documents x16 for single-slot population, but the
MEASURED link is Gen4 x8 on both the root port (00:03.1) and the card's
upstream port (07:00.0). The cause (firmware lane-allocation setting,
CPU/socket lane population, or board strap) is NOT determined by this
read-only scan; verify with `LnkSta` after any BIOS change before assuming
x16 is available. The card's internal switch link (08:00.0 → 09:00.0)
trains Gen4 x16; VRAM measured 17163091968 bytes (15.98 GiB) via amdgpu
sysfs; driver amdgpu; subsystem XFX [1eae:6701]; Vulkan/CUDA visibility not
probed this pass (capability observation pending a future qualification;
not a correctness qualification).

## Reserve hardware — HP Z440 x2 (undeployed)

Two additional HP Z440 workstations are physically available and reported identical to deployed inferswarm01. They are **reserve hardware**, not deployed InferSwarm nodes, so their expected slots are not included in the deployed-fleet census below until commissioned and independently audited.

Expected per chassis, based on identity with inferswarm01:
- 2 x PCIe 3.0 x16 wired x16
- 1 x PCIe 3.0 x8 wired x8
- 1 x PCIe 2.0 x8 wired x4
- 1 x PCIe 2.0 x4 wired x1
- 1 x legacy PCI 32-bit

Combined reserve capacity if both are commissioned:
- +4 PCIe 3.0 x16
- +2 PCIe 3.0 x8
- +2 PCIe 2.0 x8 wired x4
- +2 PCIe 2.0 x4 wired x1
- +2 legacy PCI

Before using either reserve Z440 for evidence-bearing work, collect its own `dmidecode`/`lspci` topology and record actual occupants, BDFs, negotiated widths, and link speeds.

## Deployed fleet aggregate — slot capability census
| Slot class | Count | Hosts |
|------------|-------|-------|
| PCIe 4.0 CPU PEG x16/x8 dynamic | 2 | Valinor PCIEX16_1/2 (x16/- or x8/x8 shared CPU lanes) |
| PCIe 3.0 x16 | 5 | 01 x2, 02 x1, 03 x2 (03 slots observed Gen3 on root ports; TGL CPU lanes may be Gen4) |
| PCIe 3.0 x8 | 1 | 01 SLOT 4 |
| PCIe 3.0 x4 | 2 | 02 PCIE-8, Valinor PCIEX16_3 |
| PCIe 3.0 x1 | 4 | 02 PCIE-6/7 (one occupied by NIC), Valinor PCIEX1_1/2 |
| PCIe 2.0 x8 (wired x4) | 1 | 01 SLOT 3 |
| PCIe 2.0 x4 (wired x1) | 1 | 01 SLOT 1 |
| PCIe 2.0 x1 (or Gen2 platform) | 6 | 03 x2, 04 x4 (one occupied by NIC) |
| legacy PCI 32-bit | 1 | 01 SLOT 6 |
| TOTAL PCIe expansion slots | 22 | + 1 legacy PCI; M.2 and onboard endpoints excluded |

## Deployed fleet aggregate — GPU population (10 GPUs, 2026-09-15 measured)
| Host | GPU | Slot link (capability / current wiring) |
|------|-----|----------------------------------------|
| 01 | RTX 3060 LHR 12GB x2 | Gen3 x16 each |
| 02 | RX 580-class (Ellesmere) x2 (8 GiB each) | Gen3 x16 capable, on x1 risers |
| 02 | RX 5600 XT (Navi 10, 5.98 GiB) | Gen4 x16 endpoint, on x1 riser |
| 02 | RTX 3060 Ti LHR (8 GiB) | Gen4 native, on x1 riser |
| 03 | RTX 3060 LHR 12GB x2 | Gen3 x16 / second card width-limited to x4 |
| 04 | RTX 3090 24GB | Gen2 x16 on this platform |
| Valinor | RX 6800 XT 16GB (Navi 21, XFX Merc 319) | CPU PEG slot; measured Gen4 x8 (see Valinor section) |

Per-device VRAM (2026-09-15 measured refresh, Issue #196): all figures below
are driver/runtime-measured per device this pass (amdgpu sysfs
`mem_info_vram_total`, `nvidia-smi memory.total`) and cross-checked against
the raw receipts in `docs/hardware/current-inventory/2026-09-15/`:

- Valinor RX 6800 XT: 17163091968 bytes (15.98 GiB), amdgpu.
- inferswarm02: Ellesmere 02:00.0 = 8589934592; Ellesmere 06:00.0 =
  8589934592; RX 5600 XT 05:00.0 = 6425673728; RTX 3060 Ti 07:00.0 =
  8589934592 (nvidia-smi).
- NVIDIA fleet on 01-04 unchanged from the R8-A census: 80 GiB total
  (re-verified by sweep 2026-09-15).
- Execution-fleet aggregate (01-04): 109504888832 bytes = 101.98 GiB
  (80 GiB NVIDIA + 21.98 GiB AMD). Including Valinor: 126667980800 bytes
  = 117.97 GiB across 10 GPUs.

Historical (2026-09-14, R8-A census window): the then-current deployed
accelerator census was 96 GiB execution-fleet (80 GiB NVIDIA + 16 GiB AMD =
2x Ellesmere) and no RX 6800 XT was observable on any reachable host. That
record remains correct for its capture window and is retained byte-preserved
in `docs/investigations/qwen38-flash-next-r8-a/hardware-census.json`; the
R8-A reported-not-observed RX 6800 XT row described a real 2026-09-14
observation and is superseded for CURRENT state by this 2026-09-15 refresh
(the card is now installed on Valinor). The Radeon Pro V340L described there was
installed on inferswarm02 after the #196 window and is CURRENT hardware
(see the inferswarm02 section and the V2-C campaign record); the #196
totals are historical for their capture window.

## Actionable observations
1. inferswarm03 GPU2 (03:00.0) negotiated WIDTH x4 (downgraded) in an x16 slot - worth
   checking BIOS bifurcation settings if full x16 expected.
2. GPU link speeds may read Gen1 at idle (normal power management); verify under load
   with `sudo lspci -s <bdf> -vv | grep LnkSta` while a GPU job runs.
3. inferswarm02's current GPU is the V340L behind the PM8533 fanout; the card's upstream path is Gen3 x1 (~985MB/s ceiling), mechanically proven in the V2-C campaign. The former four-GPU x1-riser arrangement is historical (#196).
4. inferswarm04's x16 slot is Gen2 (5GT/s = 4GB/s ceiling for the RTX 3090).
5. Valinor's RX 6800 XT now exercises Gen4 signaling (endpoint and internal switch
   link at Gen4 x16; external root-port link Gen4 x8). NOTE: x8 width with PCIEX16_2
   empty contradicts the ASUS single-slot x16 documentation - investigate BIOS
   PCIe lane allocation before relying on x16.
6. Valinor supports controlled same-host topology experiments: CPU PEG x16 versus x8 allocation, CPU-direct versus B550-chipset paths, and chipset x4/x1 constraints after deliberate card moves.
7. The two reserve Z440s can provide replication of inferswarm01-class topology after commissioning, reducing host-specific confounding in future bus-sensitivity experiments.

## Topology change log

Record test-relevant physical changes here in addition to updating the current tables above. Git history remains the authoritative byte-level history.

| Date | Change | Reason / evidence |
|------|--------|-------------------|
| 2026-09-13 | Initial repository baseline | Imported the collected inferswarm01-04 PCIe/device inventory. |
| 2026-09-13 | Added Valinor audit | Physical inventory added; ASUS board documentation resolves CPU PEG allocation as x16 single / x8+x8 dual. |
| 2026-09-13 | Added two reserve HP Z440 chassis | Reported identical to deployed inferswarm01; kept outside deployed census pending per-host audit and commissioning. |
| 2026-09-14 | Issue #189 R8-A accelerator census refresh | Read-only per-device VRAM measurement (amdgpu sysfs, nvidia-smi) and fleet-wide device sweep; retained in docs/investigations/qwen38-flash-next-r8-a/hardware-census.json. Confirmed 80 GiB NVIDIA on 01-04 and 2x8 GiB Ellesmere on 02; recorded reported-but-unobserved AMD devices and pending V340L as non-deployed. |
| 2026-09-15 | Issue #196 living inventory refresh | Valinor: GTX 1060 3GB replaced by XFX RX 6800 XT in PCIEX16_1; PCIEX16_2 NVMe adapter removed (slot now empty); measured external link Gen4 x8 despite empty PCIEX16_2. inferswarm02: RX 5600 XT (Navi 10, 5.98 GiB) newly observed at 05:00.0; both Ellesmere cards remain (02:00.0, 06:00.0 after BDF shift); 3060 Ti moved to 07:00.0. Measurement basis: read-only dmidecode/lspci -vvv/sysfs/vulkaninfo/nvidia-smi scans; raw receipts at docs/hardware/current-inventory/2026-09-15/. Fleet: 10 GPUs, 101.98 GiB execution-fleet (01-04), 117.97 GiB including Valinor. |
| 2026-09-17 | Issue #215 V2-C V2C_V340L_PLATFORM_STABILITY_PASS | inferswarm02: V340L (PM8533 + two Vega 10 dies @06:00.0/09:00.0, Gen3 x1 upstream) is the current installed configuration; prior #196 inventory (RX 5600 XT / Ellesmere x2 / 3060 Ti on x1 risers) is historical. Proven stable across baseline + 4 warm reboots + 1 operator cold power cycle with zero manual interventions; both dies independently reproduce the accepted V2-B byte-exact qualification. Raw receipts: docs/investigations/vulkan-v2-c-v340l-platform-stability/cycles-v2/. |
