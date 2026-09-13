# LINK-X1 — minimum viable PCIe interconnect envelope for local participants

Status: campaign complete on `inferswarm02` (Issue #35); terminal `X1_MINIMUM_VIABLE_PARTICIPANT_ENVELOPE_ESTABLISHED`, recorded in draft PR #165 pending maintainer review. Additive investigation namespace; no prior
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


## Measured results (MEASURED/CALCULATED per BENCHMARKING.md)

Transport (both subjects Gen1 x1 under load, sysfs-sampled concurrently):

| Subject | BDF | H2D 128 MiB | D2H 128 MiB | 4 KiB service | Bidir |
|---|---|---|---|---|---|
| AMD-A | 02:00.0 | 0.169 GB/s | 0.166 GB/s | 0.155 ms | 0.167 GB/s |
| NV-A | 04:00.0 | 0.200 GB/s | 0.210 GB/s | 0.120 ms | 0.413 GB/s |

Role sweep (frozen workload, greedy temp 0 seed 42, 48 tokens; byte-exact vs
the accepted frozen reference where declared):

| Role | Median t/s | Offload | Byte-exact | Classification |
|---|---|---|---|---|
| single AMD-A control | 44.4 | 37/37 | yes | (control) |
| single NV-A control | 89.95 | 37/37 | yes | (control) |
| adverse layer split | 55.95 | 37/37 | yes | THROUGHPUT_POSITIVE vs AMD anchor (1.26x); 0.62x vs NV anchor |
| coarse split + batch np=4 | 52.35/seq | 37/37 | n/a (declared) | THROUGHPUT_POSITIVE vs AMD anchor (1.18x); below single-seq split |
| capacity 14B two-subject | 21.3 | 49/49 | n/a | THROUGHPUT_POSITIVE, decisive capacity (vs 0.2 t/s paging control, ~106x) |
| capacity 14B single control | 0.2 | 49/49 nominal, 417.66 MiB CPU-mapped | n/a | paging-dominated control |
| R0 row-split control | failed at load | - | - | NOT_USEFUL_FOR_TESTED_ROLE (unsupported) |

## Envelope conclusion (planner-facing)

On this measured substrate (Gen1-class x1 links pinned at their floor under
load), a narrow-link participant is:

- **net-useful as a capacity/residency contributor**: models that page on a
  single subject execute genuinely resident with the participant
  (~106x measured feasibility gain, complete offload, split device buffers);
- **conditionally throughput-useful**: adding a stronger participant to a
  weaker anchor improves matched serving (1.26x measured); adding a weaker
  participant to a stronger anchor degrades it (0.62x measured) — the
  marginal sign depends on the anchor, not on the link alone;
- **dominated for fine-grained fan-out from a strong anchor** under current
  supported semantics; and the finer-grained tensor-split shape is not
  supported at all on these backends (fails closed, control R0).

Measured facts a future planner needs (no vendor/width special cases):
per-direction sustained bandwidth by size class; small-transfer service
latency; residency/host-paging cost when oversubscribed; device-local
service rate for the execution-unit class; and the anchor-relative
throughput ratio. Recorded in `UTILITY-ENVELOPE.json`; wider links (x4/x8)
remain later comparison points, not prerequisites.

Terminal: `X1_MINIMUM_VIABLE_PARTICIPANT_ENVELOPE_ESTABLISHED` (see
`STATUS.json`).
