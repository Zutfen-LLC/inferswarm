# Phase 1 NO-GO disposition — what would change the answer

```
Status: RESULT ADDENDUM
Canonical report: phase1-go-no-go-report.md
Canonical campaign verdict: NO-GO
```

This addendum records the project disposition required by issue #10 after the
canonical Phase-1 result. It does not change, reinterpret, or supersede any
measurement, threshold, campaign identity, or verdict in the canonical report.

## The canonical result cannot change

The canonical campaign on FreeToken
`f29013fda7f1dcda94c6e44957d8b503795928dd` is permanently **NO-GO**.

No later optimization, diagnostic, placement change, P2P experiment, transport
change, or alternative candidate may be substituted into that campaign or used
to rewrite its verdict. Any materially changed implementation is a **new
experiment** with a new identity and, where appropriate, new methodology and
success criteria frozen before measurement.

The immediate Phase-1 project decision is therefore:

> **STOP / RECONSIDER. Do not proceed directly into scaling, networking,
> heterogeneous workers, or generalized runtime extraction on the current
> execution mechanism.**

ROADMAP phases that assume the tested distributed-execution mechanism is
performance-viable must be reconsidered rather than executed on momentum.

## What this NO-GO establishes

The campaign established that the tested mechanism is real and numerically
correct: F1-F6 and C1-C4 passed, remote expert weights remained resident, no
silent fallback occurred, and both canonical sessions were COMPLETE / VALID.
The failure is performance, not mechanism validity.

The measured deficit is architectural in scale:

- B1 median complete MoE-layer wall: **0.233472 ms**;
- candidate median complete MoE-layer wall: **3.612-3.787 ms**;
- Session-1 `R_agg`: **0.072446**;
- Session-2 `R_agg`: **0.072116**;
- every workload class is significantly slower and below the frozen
  `R_c = 0.95` ITERATE floor;
- the largest cleanly named individual candidate cost,
  `host_remote_submit_control`, is only about **0.677-0.698 ms**.

Removing that one cost cannot remotely move an approximately `0.07x` aggregate
ratio above the frozen `1.20x` GO threshold. The complete-layer components also
overlap, so they cannot be additively subtracted to manufacture a projected
success case.

Accordingly, small transfer, Python, or control-path optimizations are not a
credible basis for continuing this candidate as an ITERATE result. The tested
shape needs an **order-of-magnitude reduction in the distributed critical
path**, not a marginal tuning win.

## What this NO-GO does not establish

Section 8 is explicitly **INCONCLUSIVE**. The canonical schema does not expose
the per-touch baseline residency state required to construct
`MATCHED_NONLOCAL_TOUCH_SET`, `REMOTE_INTRINSIC`, or
`BASE_NONLOCAL_SERVICE` without prohibited aggregate apportionment. Therefore
Rule B / N5 does not fire.

That means this result does **not** prove that remote expert execution is
intrinsically incapable of working under every architecture. It proves that
this tested execution shape is decisively nonviable:

- same-host two RTX 3060s;
- NVFP4;
- static placement;
- stock host-staged transport;
- graph-disabled distributed decode;
- route-preserving return/reconstruction;
- current per-layer host orchestration.

It also does not prove or disprove network execution, 1 GbE viability, larger
GPU counts, heterogeneous vendors, other quantizations, dense-model execution,
or a generalized InferSwarm runtime.

## What future evidence could justify revisiting the direction

A future investigation could justify a **new experiment** only if it proposes
a materially different, source-grounded execution shape capable of addressing
the measured order-of-magnitude deficit.

Examples of hypotheses that may be investigated — without any claim that they
will succeed — include:

- graph-compatible multi-GPU execution that removes the candidate's
  graph-disabled serving penalty as part of a genuinely different critical
  path;
- GPU-resident routing/control that removes per-layer host orchestration rather
  than merely making the existing host calls slightly faster;
- direct device-to-device/P2P transport **combined with** a redesigned critical
  path;
- a different return/reduction architecture that preserves the required
  numerical semantics while avoiding the current route-contribution return and
  reconstruction costs.

**P2P alone is not supported as a rescue hypothesis by this result.** The
measured transfer components are too small relative to the total deficit for
removing host staging by itself to bridge the gap.

Likewise, substituting faster-memory GPUs, a different static placement, or a
single micro-optimization does not change this campaign's answer. Such changes
may motivate a new bounded investigation, but they do not convert this NO-GO
into ITERATE.

If a future experiment tests the same broad H1 under a materially different
execution architecture, it must:

1. define the new candidate and causal hypothesis before performance is seen;
2. freeze its success criteria and evidence requirements before measurement;
3. retain an honest strongest-baseline comparison;
4. measure the complete end-to-end serving path, not extrapolate from transfer
   or expert microbenchmarks;
5. publish its result independently of this Phase-1 campaign.

Until such a new hypothesis exists with a plausible path to an
order-of-magnitude critical-path reduction, the evidence-backed disposition is
**STOP / RECONSIDER**, not Phase-2 scaling of the current mechanism.
