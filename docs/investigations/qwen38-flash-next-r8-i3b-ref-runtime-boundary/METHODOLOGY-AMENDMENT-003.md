METHODOLOGY AMENDMENT 003 — R8-I3B (Issue #250, PR #251)

CORRECTION PASS 6 — TWO DEFECTS FROM THE RETAINED FAILED v1 ARM-A
EXECUTION. Implemented repository-only on branch
issue-250-r8i3b-ref-runtime-boundary (correction pass 6 head; base
main unchanged at bc71774dc68e7d7fddaf97bd794bbbc297e66ca5). Zero
physical diagnostic execution; zero new dispatch comments; PR #251
not merged. The frozen METHODOLOGY.md, AMENDMENT-001 and
AMENDMENT-002 texts remain preserved verbatim (dated-amendment
discipline).

0. RETAINED v1 DEFECT RECORD (READ-ONLY; NEVER A CANONICAL INPUT)

The first bounded Arm-A execution attempt (dispatch comment
5852485456, head 1c86e97da42401ff7cfa98e3dc48a33517c65def,
namespace d250-arm-a, arm A-vulkan-necessity) failed at unit 001
and is RETAINED READ-ONLY as the defect record:

  - evidence root: inferswarm01:/home/hermes/is250-campaign/evidence/
    (mode 0555, sha256 manifest:
     inferswarm01:/home/hermes/is250-v1-evidence-manifest.sha256)
  - generation identifier: gen-1-v1-timeout-defect
  - failed unit: case-3072-B-devnone-001 — retained server.log
    sha256 27c50c364d65e2ae4220329b1bd7859cea1768968f566f32527150c2a
    980d75f; opening model attestation sha256
    e270a69a1ece5b9d1e57ec3f057d2b8c409951d31d299338798f49746c650a34
  - custody: zero output rows; no receipt; server.log retains
    "prompt processing, n_tokens = 2560, progress = 0.83,
    t = 1140.46 s / 2.24 tokens per second" and
    "srv stop: cancel task, id_task = 0" at client elapsed
    t ~= 1143 s; fail-closed retention itself was CORRECT.

The generation identifier gen-1-v1-timeout-defect is retired: no
producer may write it, no reducer may reduce it, and no rerun may
launder or overwrite the failed record. The canonical rerun (a
future dispatch) uses generation gen-2-pass6 under a NEW evidence
root, with an append-only evidence-generation.json marker naming
this predecessor.

1. PRODUCER DEFECT — RETIRED GLOBAL 1200s HTTP TIMEOUT

DEFECT: the frozen fixed request timeout HTTP_TIMEOUT_S = 1200
predates CPU-only execution and is shorter than a LEGITIMATE Arm-A
case-3072 CPU-only request. Retained evidence: the true CPU-only
(-dev none, default threading) prefill ran at ~2.25 prompt
tokens/second over a 3077-token prompt (~1368 s implied prefill);
the request was killed at ~83% (~1143 s) by the 1200 s client
deadline; the server was terminated; the unit retained failed with
zero output. 1200 s < legitimate Arm-A execution time. This is a
PRODUCER DEFECT, not evidence that CPU-only execution is
nondeterministic or unhealthy.

CORRECTION (timeout-budget authority, scripts/issue250_timeout.py):
the global constant is REMOVED from the request path. Every request
deadline is now derived per arm/unit by the frozen law

  predicted_prefill_s = expected_prompt_tokens / planning_rate
  budget_s = ceil(min(max(predicted_prefill_s * 1.5 + 1920,
                          1800), ceiling))

with planning rates frozen in TIMEOUT_BASIS (each entry naming its
evidence basis): cpu-only-default-threads = 2.25 tok/s (MEASURED,
retained v1 server.log); cpu-only-c1-t4 = 0.6428 tok/s and
cpu-only-serial-t1 = 0.1607 tok/s (FROZEN PROSPECTIVE PLANNING
rates, linear per-thread scaling from the retained measurement;
never treated as measured facts); gpu-accepted-placement = 71.7
tok/s (MEASURED, retained accepted #248 case-3072 GPU-offload
server log). Safety factor 1.5; startup/decode margin 1920 s
(model load + decode/control); sanity bounds [1800 s, 14400 s]
per request (the gated serial condition alone may expand to
36000 s, and ONLY behind its gate, section 3).

Invariants (all mechanically tested in
tests/test_issue250_pass6_corrections.py):

  A. a valid expected Arm-A case-3072 CPU-only completion at the
     retained ~2.25 tok/s is NOT killed by the normal request
     deadline (derived budget ~= 3972 s >> ~1368 s legitimate
     prefill);
  B. the timeout remains a bounded safety mechanism — no timeout
     removal, no effectively infinite budget, no single universal
     constant (different conditions derive different budgets; a
     stalled request still dies at the derived bound);
  C. the policy is mechanically bound to the frozen unit/arm plan
     (unit_condition -> frozen basis -> pure derivation);
  D. receipts retain the timeout budget AND its full derivation
     inputs (condition, arm, prompt tokens, rate basis id, rate,
     safety factor, margins, bounds, digest) under
     `timeout_policy`, digest-bound (timeout_policy_sha256);
  E. the reducer verifies the block via
     issue250_timeout.verify_timeout_budget_block and fails closed
     on any mutation;
  F. any timeout is still a FAILED physical unit and is never
     interpreted as numerical evidence.

2. METHODOLOGY-COST DEFECT — FROZEN PROSPECTIVE COST GATE

DEFECT: executability is not reasonableness. At the measured CPU
rates, the OLD Arm-C serial regime is operationally unreasonable
as an automatically executed discriminator (~19,150 s ~= 5.3 h per
case-3072 unit at the exact 2.25/14 tok/s fraction; >= 10.5 h for
two serial observations; ~26.5 h for a five-identical
deterministic confirmation).

CORRECTION: a frozen machine-readable cost-planning record
(scripts/issue250_timeout.cost_planning_record) is generated and
retained at every canonical evidence root (append-only) BEFORE any
expensive arm executes, per condition: condition/arm, prompt
tokens, retained planning throughput + basis, estimated
seconds/unit, min units to establish a mismatch (2), units for a
deterministic claim (5), estimated minimum mismatch cost,
estimated deterministic-proof cost, and the frozen disposition.
The producer does NOT proceed merely because the HTTP timeout is
large enough: evaluate_cost_gate refuses auto-execution for any
condition whose deterministic-proof cost exceeds the 12 h campaign
ceiling or whose disposition is not an authorized one. Frozen
dispositions: arm-a-cpu-only / arm-c-default / arm-c1-reduced =
authorized_by_pass6_dispatch; arm-b-fresh / arm-b-sameproc =
conditional_not_dispatched (reachability unchanged: B only if A
varies); arm-c2-serial =
blocked_requires_separate_authorization.

Projected Arm-A cost at the retained rate (~23 min/request,
~45-50 min two-request mismatch opportunity, ~2 h five-repeat
deterministic confirmation, ~4.6 h worst case) is expensive but
bounded and potentially decisive; Arm A is KEPT with corrected
timeout budget, cost accounting, and fresh evidence-root
generation only. Arm B is kept conditional and cost-gated with no
automatic five-repeat tails after a valid mismatch.

3. ARM-C AMENDMENT — BOUNDED THREAD-REGIME DISCRIMINATOR (C1)
   AND SEPARATE SERIAL MAINTAINER GATE (C2)

The old one-shot serial (-t 1 -tb 1 vs default) Arm-C geometry is
RETIRED as an automatically executed discriminator. It is NOT
rescued by a larger timeout. The amended Arm C answers "does
materially reducing CPU execution parallelism change the
row-nondeterminism regime?" with ONE predeclared bounded probe:

  C1 (namespace d250-arm-c1, arm C1-reduced-parallelism): FIVE
  fresh CPU-only (-dev none) case-3072 units at the frozen
  intermediate regime `-t 4 -tb 4` — one intermediate regime,
  substantially below the accepted default 14 threads, frozen
  BEFORE any execution (never chosen after outputs). Everything
  else stays identical to the accepted geometry: same model,
  binary, request, batch/ubatch, case prompt; no affinity/NUMA/
  polling/priority changes; the normal prefix early-stop law
  (first full-row mismatch establishes variation; a deterministic
  claim requires the frozen five-identical population).

  The -t 4 -tb 4 regime was frozen on mechanical grounds: it is
  materially reduced (3.5x below default), bounded (~4790 s/unit
  at the planning rate; ~6.6 h deterministic proof, under the 12 h
  ceiling), and keeps meaningful core parallelism so a negative
  result is informative about parallelism as a factor.

  C2 (namespace d250-arm-c2, arm C2-serial): the serial
  `-t 1 -tb 1` deep discriminator is retained ONLY as an optional
  second maintainer gate. It is NOT reachable under any pass-6
  dispatch. Requirements, all mechanically enforced: C1 completed
  and remained variable; a retained c1-varied-c2-gate.json record
  binding BOTH the C1 and C2 authority digests at the evidence
  root; an explicit maintainer exact-head dispatch in the
  dedicated d250-arm-c2 namespace carrying the frozen
  c2-serial-gate line; a producer gate
  (issue250_physical.c2_launch_allowed) that refuses serial units
  otherwise; budget refusal without the gate flag. No generic
  Arm-C authority can reach C2 (namespace<->arm binding map +
  plan membership), and C1 authority can never authorize C2.

TERMINAL SEMANTICS (reducer, prospective): if C1 is deterministic
while default CPU-only is proven varying, the terminal is
R8I3B_REFERENCE_RUNTIME_BOUNDARY_LOCALIZED with the narrow factor
"CPU thread-regime / parallelism boundary", naming the EXACT
regimes (default 14-thread vs frozen -t 4 -tb 4) and explicitly
NOT claiming single-thread execution was tested. If C1 also
varies, the reducer does NOT silently fall through to Arm D and
does NOT return UNRESOLVED: it stops at a maintainer gate
(BLOCKED, reducer-state arm_c_gate_status recording
c2_serial_gate_closed/c2_serial_executed) stating that the bounded
probe did not localize and serial C2 remains optional/unexecuted
behind its separate cost gate. Only when the gated serial work is
genuinely complete (or explicitly absent by a frozen rule) does
the pre-existing D law proceed, unchanged.

4. ARM D — UNCHANGED

All accepted Arm-D corrections stand as frozen (attributed
tokenizer-server authority, actual token counts, runtime/tokenizer
equality, QSA all-cells maximum 2051, first selective population
2052, retired wall-clock/ubatch progress causality, screening
pair, five-repeat deterministic confirmation,
source-proven indexer_top_k_boundary at the corrected equality
sides per AMENDMENT-002, no retrospective ladder selection).

5. DISPATCH STALENESS — PASS-5 DISPATCH IS RETIRED

Dispatch comment 5852485456 (d250-arm-a) binds ONLY head
1c86e97da42401ff7cfa98e3dc48a33517c65def. Once this correction
commit moves PR HEAD, that dispatch is mechanically stale: the
exact-head authority law rejects it and no physical unit can
launch under it. A fresh maintainer review of the new head and a
fresh exact-head dispatch (per arm, per namespace) are REQUIRED
before any physical execution. The regression
(bind_stale_dispatch_record +
tests/test_issue250_pass6_corrections.DispatchStalenessTests)
pins comment id, bound head, namespace, and arm, and proves the
stale comment cannot authorize a unit at any moved head.

6. PHYSICAL EXECUTION STATUS

Zero physical diagnostic execution occurred during this
correction. No Arm A/B/C/D unit ran; case-4096 was not executed;
no c237-* predictive work was performed; no holdout
plaintext/decrypt/key/secret material was accessed; accepted
#241/#248 evidence and terminals are untouched; the failed v1
#250 evidence is retained read-only and unmodified.
