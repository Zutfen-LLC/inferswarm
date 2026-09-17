# Current-inventory capture 2026-09-17 (Issue #215 V2-C)

Backing the living-ledger refresh recording the V340L as the current
inferswarm02 GPU configuration. Receipts are the read-only platform
snapshot probes from the final accepted (cold) boot of the V2-C
platform-stability campaign — boot id 9345db65-58de-477a-958e-d2c1487f2b93.
Full campaign raw bytes live under
`docs/investigations/vulkan-v2-c-v340l-platform-stability/cycles-v2/`.

Measured facts: PM8533 fanout @02:00.0 behind root port 00:1d.0 (Gen3 x1),
two Vega 10 dies 1002:6864 @06:00.0 and @09:00.0, each 8,573,157,376 B
HBM2 amdgpu-bound; RTL8111 NIC @01:00.0 (r8169, 10.0.0.137/24); Intel
200-series xHCI @00:14.0; root fs /dev/sda3; kernel 7.1.8+deb13-amd64,
cmdline amdgpu.rebar=0; MINERDUDE 12XTREME, BIOS 5.12.
