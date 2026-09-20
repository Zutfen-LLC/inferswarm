# V2-G — inferswarm02 PCIe RxErr path remediation + clean-link requalification (issue #232)

Status: **CAMPAIGN COMPLETE — terminal
`V2G_PCIE_PATH_REMEDIATED_REPLAY_PASS` (derived deterministically
from retained evidence).** The chronic Correctable RxErr flood was
remediated by the physical intervention sequence (see the four-state
ladder below), the clean-link gate passed and repeated across a
genuine cold power cycle, the bounded qualification passed, and the
authorized B→A replay ran all four arms (4 KiB → 64 MiB, one
exact-correct rep each) with ZERO platform fault or RxErr recurrence
— including the historical 64-MiB fault scale. PR OPEN/UNMERGED
awaiting maintainer exact-head review.

**Nonclaim (issue-mandated):** this does NOT establish that the
chronic RxErr condition caused (or was the only precondition of) the
historical #216/#230 amdgpu faults — the retained evidence shows the
fault did not reproduce on the remediated path at the replayed scale,
nothing more. No soak stability, no route, no production support.

Campaign: `issue232-v2g-pcie-path-remediation`

Successor to V2-F (#230/PR #231, merged `c21840e4`).

## Why this campaign exists

V2-F established two facts that must stay separate:

1. **V340L external-memory execution is real** — exact-correct
   cross-die transfers both directions through 16 MiB (B→A) / 256 MiB
   (A→B); at the 64-MiB B→A rung die A hit the #216-class fault
   (ring gfx timeout → failed ring reset → GPU reset ret=-62).
2. **The fault boot carried a CHRONIC Correctable RxErr flood** on the
   PM8533 upstream port `0000:02:00.0` over the width-downgraded Gen3
   x1 link — 250,851 parsed events across the boot, ~477/min, starting
   at boot init 34.5 h before the campaign, zero Uncorrectable/DPC.

The accepted evidence makes NO causal claim between them. V2-G tests
the PCIe transport environment FIRST: remediate the physical path, prove
a clean link under a prospective gate, and only then authorize one
narrowly bounded replay of the previously faulting seam.

## Outcome (retained evidence, 2026-09-20)

| State | Config | Result |
|---|---|---|
| chronic baseline | original: root port 00:1d.0 + 3060 Ti neighbor | FLOOD (~250k events/boot fault boot; 11180 in 1.6 h fresh boot; 188 sysfs RxErr in the first post-bundle minute) |
| intervention 1 (bundle) | reseat + 3060 Ti removal (declared bundle, no individual attribution) | FLOOD persists |
| intervention 2 | upstream moved to motherboard slot (root port 00:1c.5) | CLEAN (zero events, zero counters) |
| intervention 3 | returned to daughterboard port 2 (root port 00:1d.0 again) | **CLEAN** — same path as chronic, now clean |

The daughterboard path itself is not intrinsically faulty: the same
root port that carried the chronic flood runs clean after the
intervention sequence. Operator testimony (retained): the card now
sits in daughterboard port 2; daughterboard slots 3+ steal PCH lanes
from the NIC (RTL8111 stops functioning), constraining alternatives.
No causal attribution beyond the retained four-state ladder is made.

Replay (B→A opaque_fd, one rep each, immediate-stop armed, producer
byte-identical to the accepted V2-F pin `30cf6996`): 4 KiB ✓,
1 MiB ✓, 16 MiB ✓, **64 MiB ✓** — every arm exact-correct, zero
RxErr delta, zero amdgpu journal events, no width/topology change.

## Separate state dimensions (never conflated)

- **PCIE_PATH_HEALTH** — the chronic RxErr condition and its remediation;
- **V340L_DRIVER_HEALTH** — die enumeration/identity/driver usability;
- **EXTERNAL_MEMORY_CORRECTNESS** — replay arm results only;
- **AMDGPU_RING_RESET_STABILITY** — amdgpu fault classes from journal
  windows only;
- **PHYSICAL_ROUTE** — measured behavior only, never naming.

## Frozen campaign parameters (before any retained observation)

- Clean-link gate: **zero Correctable RxErr** on the candidate upstream
  path over a fixed interval — **2 minutes since the 2026-09-20
  operator-directed amendment (15 min originally frozen; amended before
  any gate evaluation was retained; zero threshold and cold-cycle
  confirmation unchanged; basis: the chronic condition measures
  120-850 events/min, so a 2-minute window separates fault from clean
  by ~3 orders of magnitude)** (both sources: sysfs counters
  AND journal event census, which must agree), zero Uncorrectable/DPC,
  no amdgpu fault classes, expected topology + declared width (idle
  speed downtraining is NOT width downgrade), no peripheral
  regression — repeated across **one cold power-cycle confirmation**
  (a warm reboot never substitutes). The zero threshold is frozen
  prospectively; no nonzero threshold may be invented after observing
  results.
- Replay ladder (only after gate + qualification pass): B→A opaque_fd,
  4 KiB → 1 MiB → 16 MiB → 64 MiB, **one exact-correct rep each**, no
  warmups, no repetition ladder until the single 64-MiB result is
  known. First arm is never the fault scale. Immediate stop on:
  correctness mismatch, ring timeout/hang, reset, device loss,
  D-state, Uncorrectable/DPC, material RxErr recurrence (frozen at
  ≥4.77 events/min = chronic-rate/100), width/topology change, nonzero
  producer exit. No arm reruns under the same authority.
- Replay producer: the ACCEPTED #230 transfer producer bytes, pinned
  at V2-F head `30cf6996` (closure digest + blob sha re-derived at
  authority build; any change requires a separately reviewed freeze).
- Material RxErr recurrence threshold during replay: 4.77/min
  (chronic 477/min ÷ 100) — frozen before any replay.

## Authority + preservation

`PHYSICAL-AUTHORITY.json` re-hashes every predecessor manifest row
(V2-B/C/D/E/F) at build/verify; the chronic-condition baseline is
RE-PARSED from the retained fault-boot journal bytes (cross-checked
against the accepted supplementary quantification: 250,851 Correctable,
250,507 from the upstream port); the replay producer is pinned by
blob hash. Accepted #216/#228/#230 evidence is preserved byte-for-byte
— mechanically enforced, never re-collected "to seek a different
answer."

## Terminal vocabulary (Phase 6)

`V2G_PCIE_PATH_REMEDIATED_REPLAY_PASS` ·
`V2G_PCIE_PATH_REMEDIATED_FAULT_REPRODUCED` ·
`V2G_PCIE_PATH_REMEDIATED_DIFFERENT_FAILURE` ·
`V2G_PCIE_PATH_REMEDIATION_FAILED` ·
`V2G_PCIE_PATH_CLEAN_NO_REPLAY` · `V2G_EVIDENCE_BLOCKED`

Derived deterministically from retained evidence only; an authored
terminal that contradicts the reduction fails the assembler (control
20). A REPLAY_PASS does NOT establish soak stability, route, production
support, or that the old PCIe condition caused the historical faults.

## Runbook (inferswarm02; one phase per invocation, under sudo)

```
# 0. sync worktree to the frozen producer head; tree clean
git fetch && git reset --hard <producer-head>

# Phase 0/1: census + bounded idle observation (pre-intervention)
sudo python3 scripts/issue232_baseline.py --evidence-root <ev> census \
    --note "post-power-cycle baseline"
sudo python3 scripts/issue232_baseline.py --evidence-root <ev> observe \
    --minutes 15 --note "phase-1 idle baseline"

# Phase 2 (one variable at a time; record BEFORE the boot):
sudo python3 scripts/issue232_baseline.py --evidence-root <ev> intervention \
    --component pm8533_upstream_reseat --description "..." \
    --pre-census-rel censuses/<ts>/census.json
#   ... cold power-cycle, then census + observe again; repeat per
#   intervention; stop escalating once a clean candidate is found.

# Phase 3: clean-link gate (needs a clean observation + one cold
# confirmation observation + cold-proof from the censuses)
sudo python3 scripts/issue232_gate.py --evidence-root <ev> \
    --observation-rel observations/<ts>/observation.json \
    --census-rel censuses/<ts>/census.json \
    --cold-observation-rel observations/<ts2>/observation.json \
    --cold-proof-rel <synthesized cold-proof json>

# Phase 4: qualification (refused unless gate PASSED)
sudo python3 scripts/issue232_qualify.py --evidence-root <ev> \
    --gate-result-rel gate-result.json

# Phase 5: replay authorization then one arm per invocation
sudo python3 scripts/issue232_replay.py --evidence-root <ev> authorize
sudo python3 scripts/issue232_replay.py --evidence-root <ev> arm --size 4096
sudo python3 scripts/issue232_replay.py --evidence-root <ev> arm --size 1048576
sudo python3 scripts/issue232_replay.py --evidence-root <ev> arm --size 16777216
sudo python3 scripts/issue232_replay.py --evidence-root <ev> arm --size 67108864

# Phase 6: deterministic reduction + terminal (authored terminal must match)
sudo python3 scripts/issue232_assemble.py --evidence-root <ev>
python3 scripts/issue232_manifest.py   # manifest LAST
```

Any stop condition: STOP, retain, reduce (the assembler derives the
terminal from the order state and arm records automatically), report.
Nothing is rerun under the same authority.

## Controls (fail-closed; 39-test suite)

The issue's 20 required rejections are exercised through the real
gate/reducer/assembler paths in
`tests/test_issue232_v2g_pcie_remediation.py`: stale-BDF chain
rejection (fresh-bytes re-derivation, duplicate-block injection),
speed-vs-width conflation, journal-context-vs-event conflation,
Correctable-vs-Uncorrectable conflation, cross-BDF source attribution,
bundle attribution, evidence relabeling (authority re-parse refusal),
warm-reboot-as-cold, single-interval acceptance, post-hoc threshold
(no nonzero threshold exists in code), clean-AER-with-amdgpu-fault,
topology/width mismatch, replay-before-gate, changed producer, direct
fault-scale jump, missing correctness observation, RxErr recurrence
during replay, predecessor rewrite (authority refusal), rerun-after-
failure, authored-terminal contradiction.
