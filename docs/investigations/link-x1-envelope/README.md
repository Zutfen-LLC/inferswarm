# LINK-X1 — minimum viable PCIe interconnect envelope for local participants

Status: IN PROGRESS (Issue #35). Additive investigation namespace; no prior
namespace is modified. Campaign host: `inferswarm02` (local session; SSH not
used).

## Purpose

Characterize the minimum useful local PCIe interconnect for an InferSwarm
accelerator participant, starting at x1-class links, and separate:

1. raw capacity utility;
2. communication-sensitive throughput utility;
3. workload/placement shapes that amortize a narrow link;
4. the boundary where an additional GPU becomes throughput-neutral/positive.

This campaign supersedes the original "Gen3 x8 retest" framing of #35 per the
issue body: x4/x8 are later comparison points, not prerequisites.

## Bound accepted prior evidence (not reinterpreted)

The accepted D3–D7 Phase1R result (measured on `inferswarm01`, Gen2 x1
mining-riser third worker):

- capacity-positive;
- throughput-negative on the tested placement/execution path;
- expensive enough that removing simultaneous A+B participation did not by
  itself make the A-only layer path attractive.

Sources bound as-is (byte-frozen, immutable):

- `docs/implementation/phase1r-final-disposition.md`
- `docs/implementation/phase1r-architecture-search-handoff.md`
- `docs/investigations/data/phase1r-d3-three-device-placement.json` (+ `.sha256.txt`)
- `docs/investigations/data/phase1r-d4-capability-weighted-placement.json` (+ `.sha256.txt`)
- `docs/investigations/data/phase1r-d7-fanin-sparse-placement.json` (+ `.sha256.txt`)

That result proves only that the tested communication pattern was a poor fit
for that measured x1 worker on that host. It is preserved, not reinterpreted;
this campaign measures the CURRENT `inferswarm02` topology as a new
measurement identity.

## Measured topology baseline (to be frozen in SUBJECT-FREEZE.json)

All three discrete GPUs sit on electrically x1 root ports (slots `00:1c.5`,
`00:1d.0`, `00:1d.3`; each LnkCap x1): two identical AMD RX 580 twins
(`02:00.0`, `03:00.0`, Vulkan selectors `Vulkan1`/`Vulkan2`, ambiguous by
name) and one NVIDIA RTX 3060 Ti (`04:00.0`, `Vulkan3`). Idle links
downtrain to 2.5 GT/s; negotiated generation/width is re-measured UNDER LOAD
during Phase 1 and retained per measurement. No wider-than-x1 slot exists on
this host; the wider-link matched control is recorded as
`NOT_PHYSICALLY_AVAILABLE` rather than approximated.

## Campaign phases (prospective order)

0. namespace + baseline (this README); subject/link identity freeze pushed
   BEFORE performance collection;
1. transport substrate characterization (per subject: negotiated gen/width
   under load, H2D/D2H sustained bandwidth by transfer size, small-transfer
   latency/service profile, bidirectional behavior, worker-path bulk load
   throughput, worker-local compute service via matched single-GPU decode);
2. reproduction of the known communication-sensitive failure mode under
   current supported semantics (per-token row-split multiworker serving);
3. prospectively frozen bounded role/placement sweep (A communication-heavy,
   B coarse boundary, C capacity-feasibility; D only if supported);
4. measured utility envelope + per-role taxonomy classifications + AMD/NVIDIA
   cross-device separation (link-dominated vs device-dominated);
5. planner/resource-doctrine implications (measured facts, no universal
   score, no vendor/width special cases in generic semantics).

## Classification taxonomy (per role, from the issue)

- `CAPACITY_POSITIVE_THROUGHPUT_NEGATIVE`
- `CAPACITY_POSITIVE_THROUGHPUT_NEUTRAL`
- `THROUGHPUT_POSITIVE`
- `NOT_USEFUL_FOR_TESTED_ROLE`
- `EVIDENCE_INSUFFICIENT`

Classifications are per role/workload/placement shape, not permanent grades
for a device.

## Rules

- Raw records retained under `raw/` with exact producer identity; repeated
  measurements reported as distributions.
- Correctness/paging/fallback validity recorded separately from performance.
- MEASURED/CALCULATED labels per `BENCHMARKING.md`.
- No selector/vendor/device/BDF literal in reusable logic (test-enforced);
  subject values live only in frozen evidence JSON and fixtures bound to it.
- Manifest: `v2a_manifest.py --contract manifest-contract.json` ladder (the
  accepted generalized generator, imported not forked).
