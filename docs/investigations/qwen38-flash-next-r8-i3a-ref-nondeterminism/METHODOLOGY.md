METHODOLOGY — R8-I3A diagnostic (Issue #248)
============================================

FROZEN 2026-09-25, BEFORE any Issue #248 physical execution. This
document freezes the diagnostic methodology prospectively. The accepted
#241 campaign, its terminal `R8I3_COMPARATOR_V2_BLOCKED`, and its
evidence are READ-ONLY inputs; comparator/2 methodology is NOT changed
by anything here.

0. Subject and inputs (exact, read-only)
----------------------------------------
- Accepted campaign head: 4e8b4fc369defe409f68da46e26d152eade4df47
- Accepted evidence root: inferswarm01:/home/hermes/is241-campaign-v3/
  (top-level SHA256SUMS, 356 rows, self-digest 78400bcf…; the
  Issue-body-quoted a5d7f02d… is a classified superseded snapshot).
- Host: inferswarm01. Reference arm B: NVIDIA RTX 3060,
  BDF 00000000:03:00.0, GPU-UUID GPU-d5c05739-96c1-7e49-89b6-bf54c2121c55,
  driver 610.57.04, nvidia ICD. Candidate arm C: replacement RX 580
  (generation-2 subject), BDF 00000000:02:00.0, amdgpu, radeon ICD.
- Model: /srv/models/qwen38-ud-iq1-s/ (three members; frozen sha256 set
  from the accepted campaign).
- llama.cpp pin b29c606e28a01b1bc8c1351026a0fae616bf6c4; binaries:
  canonical 21707f25…, r8e-obs dcee5bcf…, comparator-patched 6f8b56bd….
- Cases: the accepted historical excluded fixture ladder (sha
  419bde66…): case-256, case-1024, case-3072 (+ case-4096 only under
  explicit dispatch preauthorization; the accepted campaign never
  executed it).
- Request contract: BYTE-EXACT accepted #241 contract (samplers
  ["top_k"], top_k 1, seed 0, return_tokens true, stream false,
  temperature 0.0, n_predict 8, cache_prompt false).
- Launch shape: one fresh llama-server process per request unit;
  --ctx-size 8192 --batch-size 512; ngl per probe; ports 19000 (B) /
  19001 (C); CUDA_VISIBLE_DEVICES=-1; per-arm ICD + device selector.

1. Phase-0 (offline, complete) — retained-byte analysis
-------------------------------------------------------
scripts/issue248_analysis.py (stdlib-only, deterministic) re-derives,
under manifest custody: per-decision digests; max/rms/p99 |Δ|;
unequal counts/fractions; NaN/Inf counts; winner/runner-up; top1/top2
margin; winner-flip possibility; sign/bias and magnitude-bucket
distribution; the same for the three deterministic controls; the
manifest reconciliation; the hypothesis matrix. No physical work
precedes completion of this phase (satisfied: analysis committed).

2. Phase-1 — minimum repeatability probe (namespace d248-ref-repeats)
---------------------------------------------------------------------
>= 5 successful fresh-process repeats of case-3072 arm B at ngl=8,
comparator binary, observer enabled. Fewer repeats are permitted only
when an earlier deterministic fail-closed observation makes more
redundant. Never select a "matching" repeat; every repeat is retained.
Per unit retention: full row bytes (8 decisions), observer meta, raw
HTTP response, server log, device samples, identity pre/post, process
attribution, launch argv/env, authority snapshot, wall time (metadata
only). Judgement: token determinism = equality of independently
computed canonical digests; row determinism = equality of
independently computed row digests per decision.

3. Phase-2A — placement dependence (namespace d248-placement-rungs)
-------------------------------------------------------------------
The frozen reference-arm rung ladder ngl ∈ {1,2,4,6,8} at case-3072
arm B, comparator binary, observer on; 2 fresh-process repeats per
rung. Determine the first/largest rung at which full-row repeat
nondeterminism appears. One factor varies (ngl); everything else exact.

4. Phase-2B — regime dependence (namespace d248-regime-sweep)
-------------------------------------------------------------
case-256, case-1024, case-3072 arm B at ngl=8 (2 repeats each) as
regime controls; case-4096 ONLY under explicit dispatch
preauthorization line `case-4096:<reason>` in the authority comment.
Determines whether nondeterminism is associated with long context /
a runtime path transition. Diagnostic cases are never promoted into
qualification evidence.

5. Phase-3 — observer vs backend localization (namespace
   d248-observer-ladder)
---------------------------------------------------------
All at case-3072 arm B ngl=8, 2+ fresh-process repeats per variant:
  a. comparator observer (accepted patched binary; r8i3 capture);
  b. comparator-dual: SAME process additionally enables the R8-E
     observation hook row capture (LLAMA_OBSERVE_LOGITS +
     LLAMA_OBSERVE_POS=0). Discriminating logic: two independently
     coded capture paths reading the same consumer row; agreement
     within every process while rows vary across processes proves the
     capture faithful and localizes the variation upstream of capture;
  c. r8e-only: the R8-E observation binary (dcee5bcf…) with only the
     R8-E capture path;
  d. comparator-off: patched binary with observer env unset (inert
     patched path; token-level custody);
  e. canonical: accepted canonical no-hook binary (token custody).
Token equality never proves row equality; row-level capture (a–c) is
required for row claims. If code changes were needed for capture they
would require a separate reviewed diagnostic branch (not needed here:
all capture paths already exist in accepted binaries).

6. Phase-4 — bounded one-variable interventions (namespace
   d248-interventions)
----------------------------------------------------------
Only after earlier phases narrow the cause; every intervention
predeclared against a hypothesis in the retained plan; one factor at a
time (e.g. changed offload rung — already covered by 2A; fresh
process/runtime initialization — inherent to every unit; explicit
serialization/concurrency controls if the Vulkan implementation
exposes them, labeled as interventions; deterministic/reproducibility
flags if available, labeled as interventions). CUDA reference
comparison is permitted DIAGNOSTIC_ONLY to determine whether
variability is Vulkan-specific; it never substitutes into #241/#239
authority. Never "try settings until deterministic".

7. Health, custody, and honesty rules
-------------------------------------
- Kernel/AER/device-health window retained around every physical
  probe; per-process residency sampling; polaris fan pre-spun and held
  for any arm-C-adjacent work (accepted operational lesson).
- Append-only unit custody: no overwrite; re-runs quarantine the prior
  unit (-quarantined sibling) first.
- Timing is diagnostic metadata, never a gate.
- Determinism verdicts derive only from independently computed digests
  of derived acceptance-bearing outputs (canonical 8-token pack) and
  row bytes; raw responses are custody-only.
- Failed units are retained, never deleted.
- Zero predictive c237-* execution, zero holdout plaintext/decrypt/
  secret access, zero threshold derivation (structurally enforced by
  the tooling namespace/authority gates and mutation-tested).

8. Terminals (exact Issue #248 vocabulary)
------------------------------------------
R8I3_REF_VULKAN_NONDETERMINISM_LOCALIZED
R8I3_REF_OBSERVER_PERTURBATION_LOCALIZED
R8I3_REF_PLATFORM_INSTABILITY_LOCALIZED
R8I3_REF_NONDETERMINISM_UNRESOLVED
R8I3_REF_NONDETERMINISM_NOT_REPRODUCED

A terminal is derived only by the offline reducer from retained unit
bytes against the frozen plan; a missing/incomplete probe fails closed.
The derivation is MECHANICAL (scripts/issue248_physical.py
derive_terminal): the decision tree distinguishes (A) NOT_REPRODUCED
(complete fresh repeatability population, row-deterministic under the
frozen digest criterion; the accepted retained #241 mismatch stays
verified and no later probe reinterprets it), (D) PLATFORM_INSTABILITY_
LOCALIZED (retained causal platform evidence — recorded identity drift
or fatal device-sample markers; numerical variation alone never
selects D), (B) OBSERVER_PERTURBATION_LOCALIZED (comparator-observer
rows vary while the dual-capture discriminator agrees within every
process AND the comparator-independent capture path AND the canonical
unobserved ladder stay deterministic), (C) VULKAN_NONDETERMINISM_
LOCALIZED (reproducible row variation, dual-capture agreement, variation
surviving fresh processes in every capture mode, clean platform
health), or (E) UNRESOLVED (complete probes confirm repeatable
variation, no localization predicate satisfied). Missing/malformed
evidence yields the machine-readable `R8I3_REDUCER_BLOCKED_INCOMPLETE`
state — never a hand-selected terminal. None of these terminals
qualifies comparator/2. After the terminal is derived: STOP for
maintainer review. No automatic merge into #241.
