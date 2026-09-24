# R8-I4 durable record — V340L on inferswarm05 / HP Z440

Status: COMPLETE historical engineering import for Issue #244 Phase 0.

This additive record preserves the accepted Issue #243 engineering disposition:
`R8I4_V340_Z440_PRACTICAL_SINGLE_DIE_AND_DUAL_RESOURCE`.
It is the durable repository import of 79 retained evidence files from
`inferswarm05:/home/hermes/is243`, verified byte-for-byte before this record
was authored. It also preserves exact GitHub API snapshots of decision report
comment `5803481831` and maintainer GO-for-closure comment `5803559861`.
`SOURCE-MANIFEST.json` binds every imported artifact and identifies its source;
this bundle's `MANIFEST.sha256` binds this record, all retained bytes, and its
focused verifier.

## Scope and authority

The accepted source is Issue #243 decision report comment `5803481831`, with
maintainer acceptance/precision notes in comment `5803559861` and closure
handoff in comment `5803624698`. The source campaign is
`issue243-r8i4-v340l-z440-characterization`, captured on 2026-09-23. It is an
engineering/practicality result for a single V340L Vega10 die on the HP Z440;
it is not comparator/2 authority.

The retained record establishes these bounded observations:

- MEASURED host identity: `inferswarm05`, HP Z440 / baseboard `103C:212B`,
  Xeon E5-2683 v3, 134,985,306,112 B RAM, Debian 13, and local `/srv/models`
  SATA backing. The full raw census is `retained/evidence/phase1/phase1-census.json`.
- MEASURED card identity: two independently addressable Vega10 endpoints,
  `0000:07:00.0` and `0000:0b:00.0`, each `1002:6864`, each 8,573,157,376 B
  HBM2. The acceptance subject is one freshly bound die, never a coherent
  16-GiB resource.
- MEASURED placement: `ngl=7`, with approximately 6.29–6.32 GiB selected-die
  residency and an independently sampled excluded die below the 64 MiB noise
  boundary. The fixed reserve is 1 GiB.
- MEASURED topology: both endpoints reported loaded Gen3 x16 links. Their
  complete `lspci -PP` paths are retained in
  `retained/raw/phase1/lspci-PP-nn.txt`; both share root port `00:03.0` and
  the PM8533/card path. Endpoint/downstream x16 is not evidence of two
  independent x16 host uplinks.
- MEASURED bounded workload health: retained historical-fixture results show
  zero physical process reads, no swap use, no observed iowait, and retained
  thermal maxima no higher than 55 C under the bounded Qwen workload with the
  temporary 140 mm cooling arrangement.

## Corrected practicality projection

Using the frozen realized population counts 338 / 366 / 363 / 349 and the
retained representative walls 13.6 / 24.7 / 63.9 / 81.3 s for the roughly
256 / 1024 / 3072 / 4096-token regimes gives a CALCULATED sequential
engineering projection of approximately 18.11 h before comparator/observer
overhead. The approximately 9 h two-die value is an engineering throughput
projection only, not numerical-qualification authority.

## Thermal and topology limits

The retained <=55 C observation is scoped only to the bounded retained Qwen
workload and temporary 140 mm cooling arrangement; it is not a full-TDP or universal cooling qualification. The living PCIe ledger records the complete
source topology and explicitly distinguishes endpoint/downstream x16 links
from the shared upstream/root-port path.

## Explicit non-claims

This import does not authorize comparator/2 execution, redefine the unresolved
#241/#242 comparator/2 contract, or authorize R8-J. It does not authorize
predictive `c237-*` calibration, threshold derivation, selected-stress
candidate work, holdout plaintext/decryption/secret access, a coherent 16-GiB
claim, cross-die P2P, or generic planner hardware/model policy. It preserves
#240 as historical evidence and does not rewrite it.

No current state or physical rerun is inferred from this historical import.
Any future V340L comparator work must freshly bind the selected die and satisfy
its own accepted predecessor and execution authority.
