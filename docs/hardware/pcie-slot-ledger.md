# InferSwarm PCIe Slot Ledger

> **Status: living hardware inventory.** Update this document whenever a GPU is moved, a riser or slot path changes, firmware changes lane allocation, or fleet hardware changes. Historical experiment evidence remains immutable; record the topology/repository revision used by an experiment rather than rewriting old results.

Initial baseline collected: 2026-09-13 via SSH (`dmidecode -t slot` + `lspci -PP -nn -vv`) for inferswarm01-04.  
Valinor audit added: 2026-09-13.  
Last topology refresh: 2026-09-13.

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

## inferswarm02  (Intel 200-series PCH consumer board, Debian 13)
DMI slot usage flags unreliable on this board (all "Available"); occupancy derived from lspci.
| Slot | Designation | Capability | Occupant | Device LnkCap | Negotiated now |
|------|-------------|------------|----------|---------------|----------------|
| 1 | PCI-Express | x16 (Gen3) | AMD Radeon RX 470/480/570/580 (Ellesmere) @02:00.0 | Gen3 x16 | Gen1 x1 (riser) |
| 1 | PCI-Express | (2nd device shares/bifurcated or open-ended) | AMD Radeon RX 470/480/570/580 (Ellesmere) @03:00.0 | Gen3 x16 | Gen1 x1 (riser) |
| ? | riser | x1 | RTX 3060 Ti LHR (GA104) @04:00.0 | Gen1 x16 (see note) | Gen1 x1 (riser) |
| PCIE-6/7 | x1 slots | Gen3 x1 | Realtek RTL8111 GbE @01:00.0 | Gen1 x1 | Gen1 x1 |
| PCIE-8 | x4 slot | Gen3 x4 | EMPTY (available) | - | - |
Note: 3060 Ti reports LnkCap Gen1 x16 (native GA104 is Gen4 x16) - cheap x1 riser/bridge
masks endpoint capability. Known fleet state: 2 GPUs on x1 mining risers.

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
| PCIEX16_1 | CPU PCIe 4.0 x16 alone; x8 in dual-slot split | GTX 1060 3GB | Gen3 x16 | Gen1 x8 at idle; x8 width expected while PCIEX16_2 is populated |
| PCIEX16_2 | CPU PCIe 4.0 x8 when paired with PCIEX16_1 | Toshiba Cx5 NVMe adapter | Gen3 x4 | Gen3 x4 (device max) |
| PCIEX16_3 | B550 chipset PCIe 3.0 x4 | EMPTY (available) | - | - |
| PCIEX1_1 | B550 chipset PCIe 3.0 x1 | EMPTY (available) | - | - |
| PCIEX1_2 | B550 chipset PCIe 3.0 x1 | EMPTY (available) | - | - |
| M.2_1 (CPU) | CPU PCIe 4.0 x4 | Intel 660p NVMe | Gen3 x4 | Gen3 x4 (device max) |
| onboard | B550 chipset path | Intel AX200 Wi-Fi | Gen2 x1 observed | Gen2 x1 |
| onboard | B550 chipset path | Intel I225-V 2.5GbE | Gen2 x1 observed | Gen2 x1 |

Board capability authority:
- [ASUS ROG STRIX B550-E GAMING specifications](https://rog.asus.com/us/motherboards/rog-strix/rog-strix-b550-e-gaming-model/spec/)
- [ASUS ROG STRIX B550-E GAMING user manual](https://dlcdnets.asus.com/pub/ASUS/mb/SocketAM4/ROG_STRIX_B550-E_GAMING/E16546_ROG_STRIX_B550-E_GAMING_UM_WEB.pdf)

Current interpretation: the GTX 1060's x8 width is not a permanent limitation of PCIEX16_1. PCIEX16_2 is populated by the NVMe adapter, so the board allocates the CPU graphics lanes x8/x8. Removing or relocating that device should return PCIEX16_1 to x16; verify mechanically with `LnkSta` after any move.

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

## Deployed fleet aggregate — GPU population (8 GPUs)
| Host | GPU | Slot link (capability / current wiring) |
|------|-----|----------------------------------------|
| 01 | RTX 3060 LHR 12GB x2 | Gen3 x16 each |
| 02 | RX 580-class (Ellesmere) x2 | Gen3 x16 capable, on x1 risers |
| 02 | RTX 3060 Ti LHR | Gen4 native, on x1 riser |
| 03 | RTX 3060 LHR 12GB x2 | Gen3 x16 / second card width-limited to x4 |
| 04 | RTX 3090 24GB | Gen2 x16 on this platform |
| Valinor | GTX 1060 3GB | CPU PEG slot; currently x8 due to x8/x8 split, Gen1 speed observed at idle |

## Actionable observations
1. inferswarm03 GPU2 (03:00.0) negotiated WIDTH x4 (downgraded) in an x16 slot - worth
   checking BIOS bifurcation settings if full x16 expected.
2. GPU link speeds may read Gen1 at idle (normal power management); verify under load
   with `sudo lspci -s <bdf> -vv | grep LnkSta` while a GPU job runs.
3. inferswarm02's three GPUs all sit on x1 mining risers - ~985MB/s ceiling each.
4. inferswarm04's x16 slot is Gen2 (5GT/s = 4GB/s ceiling for the RTX 3090).
5. Valinor supplies verified PCIe 4.0 CPU-lane capability, but no currently installed endpoint exercises Gen4 signaling: its GTX 1060 and listed NVMe devices are Gen3-generation endpoints.
6. Valinor supports controlled same-host topology experiments: CPU PEG x16 versus x8 allocation, CPU-direct versus B550-chipset paths, and chipset x4/x1 constraints after deliberate card moves.
7. The two reserve Z440s can provide replication of inferswarm01-class topology after commissioning, reducing host-specific confounding in future bus-sensitivity experiments.

## Topology change log

Record test-relevant physical changes here in addition to updating the current tables above. Git history remains the authoritative byte-level history.

| Date | Change | Reason / evidence |
|------|--------|-------------------|
| 2026-09-13 | Initial repository baseline | Imported the collected inferswarm01-04 PCIe/device inventory. |
| 2026-09-13 | Added Valinor audit | Physical inventory added; ASUS board documentation resolves CPU PEG allocation as x16 single / x8+x8 dual. |
| 2026-09-13 | Added two reserve HP Z440 chassis | Reported identical to deployed inferswarm01; kept outside deployed census pending per-host audit and commissioning. |
