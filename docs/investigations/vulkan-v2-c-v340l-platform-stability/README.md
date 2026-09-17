# V2-C — Radeon Pro V340L platform-stability qualification (issue #215)

Status: **COMPLETE — terminal `V2C_V340L_PLATFORM_STABILITY_PASS`**
(campaign `issue215-v2c-v340l-platform-stability-v2`, derived by
`scripts/issue215_terminal.py` from retained bytes under `cycles-v2/`;
see `cycles-v2/TERMINAL-V2.json`).

The current stabilized V340L installation on `inferswarm02` is a
repeatably stable host/platform configuration. Across the prospectively
frozen campaign — baseline + **4 warm reboots + 1 real operator cold
power-off→power-on cycle** — every retained boot passed every platform
predicate with **zero manual interventions**:

- both Vega 10 endpoints (`1002:6864`) amdgpu-bound with valid,
  non-overlapping final BARs and 8,573,157,376 B HBM2 each, behind the
  PM8533 fanout; upstream root port `00:1d.0` and switch upstream
  `02:00.0` negotiated Gen3 x1 on every boot;
- RTL8111 NIC present, driver-bound, DHCP-addressed, link up, gateway
  reachable 3/3 on every boot;
- USB xHCI controllers and root hubs enumerated on every boot;
- root storage on `/dev/sda3` mounted and healthy (non-destructive
  read/write sentinel) on every boot;
- fresh per-boot Vulkan discovery; selector↔physical-device binding
  unique (`Vulkan1→06:00.0`, `Vulkan2→09:00.0` — stable across all boots,
  rediscovered fresh each time, never assumed);
- per-die execution sentinel PASS on **every** boot: byte-exact prefix of
  the accepted V1-A reference, accounting `0/0/0`, full 37/37 offload,
  no fallback;
- on the final accepted boot (cold boot `9345db65…`), the full
  #210-compatible canonical check reproduced both dies' independently
  qualified behavior through the accepted V2-A reusable harness,
  byte-unchanged (qualification PASS, canonical PASS, byte-exact visible
  output, accounting `0/0/0`);
- recurring **correctable** AER physical-layer messages on the PM8533
  upstream port are retained as observations (they do not indicate
  unresolved resource failure; final device state is valid on every boot).

## Campaign history

- **v1** (`issue215-v2c-v340l-platform-stability-v1`, retained whole under
  `campaign-v1/`): terminal `V2C_EVIDENCE_BLOCKED`. Cycles 1/2/3/5 and the
  final-boot canonical check all PASS, but cycle 4's sentinel record was
  lost when the operator power cut landed while the tool's final writes
  were still in the page cache (the tool completed and printed PASS; the
  bytes never reached disk). A capture fault, not platform instability —
  honestly classified BLOCKED, never relabeled FAIL, and never counted as
  evidence of instability.
- **v2** (this campaign): supersedes v1 with capture-side hardening only —
  fsync-durable artifact writes in both collectors and a cold-cycle
  protocol requiring an on-disk readback verification of every retained
  byte before the power-off signal. No platform mutation, no predicate
  loosening. Supersession record: `CAMPAIGN-PLAN-V2.json` (digest
  `6324c123…`).

## Environment (measured, per-boot)

Host `inferswarm02`, MINERDUDE 12XTREME (Intel 200-series/B250 PCH), BIOS
5.12, Debian 13 trixie, kernel `7.1.8+deb13-amd64`, cmdline
`amdgpu.rebar=0`, amdgpu (module version in `raw/`), Vulkan loader 1.4.309
with RADV Mesa 25.0.7-2+deb13u1. Runtime bytes identical to accepted
V2-A/V2-B: llama-cli `5a8f5ede…`, Qwen2.5-3B-Instruct Q4_K_M
`9c9f56a3…`.

## Nonclaims

V2-C establishes NO: simultaneous dual-die correctness or throughput;
shared-x1 contention envelope; sustained dual-load thermal/power
stability; process/device fault isolation; aggregate 16 GiB
single-address-space semantics; Qwen3.8 or DeepSeek V4.1 correctness;
mixed AMD/NVIDIA execution; SR-IOV VF support; ROCm/HIP support;
production Vulkan support; production platform certification; preferred
backend or planner policy. This terminal authorizes a separately scoped
simultaneous dual-die stress/fault-isolation campaign and does not itself
qualify concurrent dual-die operation.

## Negative controls

`tests/test_issue215_v2c_platform_stability.py` (26 tests) mutates
synthetic-but-faithful sandbox campaign trees and proves the terminal
reducer fails closed on: stale BDF/selector authority, one-die-claimed-two,
duplicate PF, missing PM8533, upstream-link drift from Gen3 x1, unresolved
BAR failure (lspci and journal variants), NIC down/unroutable, USB
controller loss, wrong root storage, storage sentinel failure, fatal AER,
amdgpu failure, removed-cycle denominator shrink, hidden manual recovery,
wrong-boot sentinel attribution, substituted snapshot bytes, warm-relabel
cold claim, non-derivable ledger facts, and historical-evidence writes —
plus structural no-bare-True-check and plan-digest bindings.
