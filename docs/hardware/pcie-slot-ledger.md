# InferSwarm PCIe Slot Ledger

> **Status: living hardware inventory.** Update this document whenever a GPU is moved, a riser or slot path changes, firmware changes lane allocation, or fleet hardware changes. Historical experiment evidence remains immutable; record the topology/repository revision used by an experiment rather than rewriting old results.

Baseline collected: 2026-09-13 via SSH (`dmidecode -t slot` + `lspci -PP -nn -vv`), user `hermes`, per host.  
Last topology refresh: 2026-09-13.

The original collection notes referenced raw JSON per host (`inferswarm0{1..4}.json`). Those captures were not included in this repository import and are not reconstructed here.

Speed key: 2.5GT/s=Gen1, 5GT/s=Gen2, 8GT/s=Gen3, 16GT/s=Gen4.
CAVEAT on "now" speeds: all links were scanned at GPU idle. NVIDIA/AMD GPUs downtrain
link SPEED to Gen1 (2.5GT/s) when idle; width is real. Re-scan under load for true speed.

## inferswarm01  (HP X99/C610 workstation, Debian 13)
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

## Fleet aggregate — slot capability census
| Slot class | Count | Hosts |
|------------|-------|-------|
| PCIe 3.0 x16 | 5 | 01 x2, 02 x1, 03 x2 (03 slots observed Gen3 on root ports; TGL CPU lanes may be Gen4) |
| PCIe 3.0 x8 | 1 | 01 SLOT 4 |
| PCIe 3.0 x4 | 1 | 02 PCIE-8 |
| PCIe 3.0 x1 | 2 | 02 PCIE-6/7 (one occupied by NIC) |
| PCIe 2.0 x8 (wired x4) | 1 | 01 SLOT 3 |
| PCIe 2.0 x4 (wired x1) | 1 | 01 SLOT 1 |
| PCIe 2.0 x1 (or Gen2 platform) | 6 | 03 x2, 04 x4 (one occupied by NIC) |
| legacy PCI 32-bit | 1 | 01 SLOT 6 |
| TOTAL PCIe slots | 17 | + 1 legacy PCI |

## Fleet aggregate — GPU population (7 GPUs)
| Host | GPU | Slot link (capability / current wiring) |
|------|-----|----------------------------------------|
| 01 | RTX 3060 LHR 12GB x2 | Gen3 x16 each |
| 02 | RX 580-class (Ellesmere) x2 | Gen3 x16 capable, on x1 risers |
| 02 | RTX 3060 Ti LHR | Gen4 native, on x1 riser |
| 03 | RTX 3060 LHR 12GB x2 | Gen3 x16 / second card width-limited to x4 |
| 04 | RTX 3090 24GB | Gen2 x16 on this platform |

## Actionable observations
1. inferswarm03 GPU2 (03:00.0) negotiated WIDTH x4 (downgraded) in an x16 slot - worth
   checking BIOS bifurcation settings if full x16 expected.
2. All GPU link speeds read Gen1 at idle (normal power management); verify under load
   with `sudo lspci -s <bdf> -vv | grep LnkSta` while a CUDA job runs.
3. inferswarm02's three GPUs all sit on x1 mining risers - ~985MB/s ceiling each.
4. inferswarm04's x16 slot is Gen2 (5GT/s = 4GB/s ceiling for the RTX 3090).

## Topology change log

Record test-relevant physical changes here in addition to updating the current tables above. Git history remains the authoritative byte-level history.

| Date | Change | Reason / evidence |
|------|--------|-------------------|
| 2026-09-13 | Initial repository baseline | Imported the collected inferswarm01-04 PCIe/device inventory. |
