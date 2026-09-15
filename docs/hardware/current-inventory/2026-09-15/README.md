# Current GPU/PCIe inventory refresh — 2026-09-15 (Issue #196)

Living current-state capture. This is NOT a historical experiment evidence
bundle: it holds fresh read-only receipts backing the living PCIe slot ledger,
and it may be superseded by any later refresh without correction procedures.
The accepted, time-scoped R8-A census of 2026-09-14
(`docs/investigations/qwen38-flash-next-r8-a/hardware-census.json`) remains
byte-preserved and correct for its capture window.

## Method

Read-only SSH scans on 2026-09-15 (all timestamps UTC):

- Valinor and inferswarm02: `dmidecode -t baseboard/-t slot`, `lspci -nn`,
  `lspci -tv`, `lspci -PP -nn -vvv` on every GPU-class endpoint plus its
  parent/upstream bridges, sysfs `drm`/PCI attributes (driver, VRAM
  `mem_info_vram_total`, link speed/width), `vulkaninfo --summary`,
  `nvidia-smi` where present, `lsmod`. No GPU context was created and no
  compute was executed. Full console log: `raw/<host>-console.txt`.
- inferswarm01/03/04 (disambiguation sweep only): `nvidia-smi --query-gpu`
  (name, bus id, device id, memory.total, driver, current/max link gen and
  width) plus `lspci -nn` GPU lines: `raw/inv-inferswarm0{1,3,4}.txt`.

## Measured current GPU population (per-device, driver-derived VRAM)

| Host | BDF | Device [vendor:device] | Subsystem | Rev | Driver | VRAM (bytes) | Endpoint LnkCap | Negotiated link |
|------|-----|------------------------|-----------|-----|--------|--------------|-----------------|-----------------|
| Valinor | 09:00.0 | AMD/ATI Navi 21 [Radeon RX 6800/6800 XT/6900 XT] [1002:73bf] | XFX Speedster MERC 319 RX 6800 XT [1eae:6701] | c1 | amdgpu | 17163091968 (15.98 GiB) | Gen4 x16 | root port 00:03.1 Gen4 x8 (see notes) |
| inferswarm02 | 02:00.0 | AMD/ATI Ellesmere [RX 470/480/570/580] [1002:67df] | Sapphire "Radeon RX 570 Pulse 4GB" label [1da2:e353] | e7 | amdgpu | 8589934592 (8 GiB) | Gen3 x16 | Gen1 x1 (riser) |
| inferswarm02 | 05:00.0 | AMD/ATI Navi 10 [Radeon RX 5600 OEM/5600 XT/5700/5700 XT] [1002:731f] | Sapphire Navi 10 [1da2:e411] | ca | amdgpu | 6425673728 (5.98 GiB) | Gen4 x16 | Gen4 x16 behind on-card switch, Gen1 x1 at root (riser) |
| inferswarm02 | 06:00.0 | AMD/ATI Ellesmere [RX 470/480/570/580] [1002:67df] | Sapphire Nitro+ RX 570/580/590 [1da2:e366] | e7 | amdgpu | 8589934592 (8 GiB) | Gen3 x16 | Gen1 x1 (riser) |
| inferswarm02 | 07:00.0 | NVIDIA GA104 RTX 3060 Ti LHR [10de:2489] | eVga [3842:4667] | a1 | nvidia | 8589934592 (8 GiB) | Gen1 x16 (riser-masked; native Gen4) | Gen1 x1 (riser) |
| inferswarm01 | 02:00.0, 03:00.0 | NVIDIA GA106 RTX 3060 LHR 12GB [10de:2504] | 1458:4074 | a1 | nvidia | 12884901888 each | Gen3 x16 | Gen1 x16 (idle downtrain) |
| inferswarm03 | 01:00.0, 03:00.0 | NVIDIA GA106 RTX 3060 LHR 12GB [10de:2504] | 1458:4074 / 1462:3903 | a1 | nvidia | 12884901888 each | Gen3 x16 / x4-width-limited | Gen1 x16 / Gen1 x4 |
| inferswarm04 | 01:00.0 | NVIDIA GA102 RTX 3090 24GB [10de:2204] | 1043:87af | a1 | nvidia | 25769803776 | Gen4 x16 (platform Gen2) | Gen1 x16 (idle downtrain) |

Corrections and ambiguity notes:

- The operator report "an installed AMD GPU is an RX 5600 XT 6GB, not the
  previously assumed RX 580" is mechanically RESOLVED as follows: both
  historical Ellesmere cards remain installed (02:00.0 and 06:00.0, both
  8 GiB amdgpu-measured); the RX 5600 XT is a THIRD AMD device, newly
  observed at 05:00.0 on a Navi 10 switch behind PCH root port 00:1d.0 —
  not a re-identification of either Ellesmere. The prior living-ledger
  statement "RX 580-class (Ellesmere) x2" is therefore incomplete rather
  than wrong: the current population is 3x AMD + 1x NVIDIA on inferswarm02.
- The 3060 Ti moved from BDF 04:00.0 (R8-A census) to 07:00.0 (root port
  00:1d.3), consistent with riser re-plumbing for the 5600 XT insertion.
- Valinor PCIEX16_2 is now EMPTY (`dmidecode -t slot`: Current Usage
  "Available"; no second CPU-PEG endpoint in `lspci`). The Toshiba Cx5 NVMe
  adapter recorded 2026-09-13/14 is no longer present. NVMe inventory now:
  Intel 660p at 01:00.0 (M.2_1 CPU path) only.
- Valinor RX 6800 XT external link: the card's Navi 10 XL upstream port
  (07:00.0) and root port 00:03.1 both report LnkSta Gen4 x8. The endpoint's
  own internal switch link (08:00.0 → 09:00.0) trains Gen4 x16. Despite
  PCIEX16_2 being empty, the CPU PEG allocation measured is x8, not the x16
  ASUS documents for single-slot population. Recorded as measured; cause
  (BIOS setting or CPU/board lane population) is not determined by this
  read-only scan and no inference is made.
- Vulkan visibility (capability observation only, not a qualification):
  inferswarm02 enumerates Intel HD 510, two "AMD Radeon RX 580 Series (RADV
  POLARIS10)", "AMD Radeon RX 5600 XT (RADV NAVI10)", and "NVIDIA GeForce
  RTX 3060 Ti". Valinor: amdgpu bound, no vulkaninfo capture retained this
  pass (tool absent); driver-level visibility only.

## Current aggregates (derived from the per-device rows above)

- Deployed GPU count: 10 (inferswarm01 x2, 02 x4, 03 x2, 04 x1, Valinor x1).
- Execution-fleet VRAM (inferswarm01-04): 109504888832 bytes (101.98 GiB)
  = 80 GiB NVIDIA + 21.98 GiB AMD.
- Including Valinor RX 6800 XT: 126667980800 bytes (117.97 GiB).
- These supersede the 2026-09-14 living-ledger figures (8 GPUs, 96 GiB
  execution fleet). The R8-A census totals (96 GiB / 8 GPUs at its capture
  time) remain the correct time-scoped record for that campaign.

## Non-claims

- No GPU context was initialized, no benchmark or qualification was run,
  and no link was re-trained; idle Gen1 speeds are power management, not
  throughput facts.
- Gen4 x8 on Valinor PCIEX16_1 is an observation, not a performance claim
  and not a board-capability claim.
- VRAM figures are driver-measured (`amdgpu mem_info_vram_total`,
  `nvidia-smi memory.total`); none are inferred from model family.
