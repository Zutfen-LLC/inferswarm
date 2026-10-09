# Issue #289 — #280 physical launcher server lifecycle (r3 defect fix)

Status: engineering fix implemented on branch `issue-289-launcher-lifecycle`
(RED commit `8314d92`, GREEN commit `a66ca34`, registration commit follows).
CPU/loopback only — no physical execution, no GPU/Vulkan, no model loading,
no new campaign authority. Issue: #289. Parent: #280.

## Defect (retained r3 evidence)

The #280 r3 campaign terminated STOP (TERMINAL.json: 2 launches / 4 request
slots, 3 physical requests served, zero candidate-B requests) because the
session-local physical driver
(`inferswarm05:~/is280r3-physical/driver.py`, sha256
`2cc001b521cbefd56a5fedb29c7ff2e774e5154851fdb1dd2fdce633237f8e39`)
never terminated the R1 baseline server before starting the R2 candidate:

1. the driver's `launch()` executor never stopped the previous launch —
   stop ran only in the post-campaign `finally`;
2. readiness was a plain HTTP `/health` poll returning 200 with `"ok"` —
   the still-running R1 server answered R2's readiness probe, so R2 was
   declared ready while its own process had already exited on bind failure
   (`server-R2.log`: `couldn't bind HTTP server socket, hostname:
   127.0.0.1, port: 8791`, exit within 39 ms);
3. the R2-cold HTTP request was dispatched to whichever process answered
   the fixed port — the R1 baseline server served it (three
   `request_accept` rows in `server-R1.log`).

The pure gate engine (`scripts/issue280_runner.run_campaign`) correctly
failed closed on the missing retained R2 observer bytes (synchronous STOP).
The defect was entirely in the physical executor, which lived only on the
host — untracked, unauditable, and untestable. The observer admission/STOP
law was and remains correct and is NOT modified by this fix.

## Fix

`scripts/issue289_launcher.py` — the minimal launcher/lifecycle component
extracted into a tracked repository module with a deterministic production
entry point `campaign_executor(matrix, ...)` that the next physical
operator drives exactly like the r3 driver: the unchanged gate engine over
one `launch(matrix_row) -> request(kind)` executor per matrix row. Laws:

- **Ownership**: a launch owns exactly the child it spawned — PID + process
  group (`start_new_session`) + the non-inherited `/proc` start time
  (PID-reuse guard). Nothing is ever killed by port or process name.
- **Sequencing**: every prior owned launch is stopped and reaped (SIGTERM,
  bounded wait, SIGKILL restricted to the owned group) and the port verified
  released BEFORE the next launch. Failure to stop cleanly is a hard
  failure, never a retry or stale dispatch.
- **Port ownership**: the port must be free before spawn; a foreign
  occupant is never contacted.
- **Live identity**: readiness requires the owned child alive under the
  same process instance AND the server reporting THIS launch's identity
  token (`I280_LAUNCH_IDENTITY`, unique per launch
  `<label>#<launcher-pid>#<monotonic-nonce>`, echoed on `/health` and in
  every completion). A bare 200, open port, cached health response, or
  foreign-identity answer is never readiness
  (`FOREIGN_SERVER_IDENTITY`).
- **Environment plumbing (review 5459338940 B2)**: the child environment
  is built from the SAME dict handed to ``command_builder`` — builder
  additions/updates (``LD_LIBRARY_PATH``, ``VK_DRIVER_FILES``,
  ``ISSUE280_OBSERVE`` in the documented production pattern) reach the
  spawned process; builder values override caller values
  deterministically; the launcher's generated ``I280_LAUNCH_IDENTITY``
  always wins over caller- or builder-supplied values.
- **Strict process identity (review 5459338940 B3)**:
  ``pid_alive_same_instance(pid, None)`` is false — a missing/unreadable
  ``/proc`` start time NEVER authenticates a live PID. ``Launch.start()``
  requires a captured non-null start-time identity before readiness
  (``START_IDENTITY_CAPTURE_FAILED`` otherwise); every subsequent check
  requires exact PID+start-time equality; identity-unavailable and
  identity-mismatch both fail closed with zero HTTP dispatch, and the
  owned child is still stopped/reaped through the bounded owned-group
  path (never a kill by port or name).
- **Explicit prompt binding (review 5459338940 B4)**: the production
  launcher has NO default prompt text. The exact frozen prompt bytes and
  request settings must be supplied explicitly (``prompt_binding`` keyed
  by prompt id, bound to the frozen workload identity — e.g. the
  accepted ``workload.json`` ``utf8_sha256``); a missing, mismatched, or
  ambiguous binding is rejected BEFORE HTTP dispatch
  (``PROMPT_BINDING_MISSING`` / ``PROMPT_BINDING_MISMATCH``), consumed
  as a transport-failed slot. Every request record carries
  ``request_identity`` evidence (prompt id, sha256, byte count — never
  the prompt text). Review 5461889945 additionally authenticates the
  repository-retained workload against an independent SHA-256 pin, rejects
  every in-row override and incomplete/unapproved request setting, and
  derives identity from the final serialized POST bytes. CPU synthetic
  bindings are isolated by patching `frozen_prompts` in the test harness;
  there is no production test-mode argument.
- **Traceable request-to-server binding**: every request record carries
  launch label, arm, server PID, and both identity tokens; a completion
  response not echoing the launch identity is recorded as
  `SERVER_IDENTITY_MISMATCH` transport failure and never admitted as an
  observation of this arm — baseline bytes can never satisfy a candidate
  observation.
- **Fail-closed launch failures**: occupied port, spawn error, early
  death, startup timeout, and wrong-identity readiness consume request
  slots as transport-failed requests through the unchanged gate engine
  (synchronous STOP; no HTTP dispatched to any unverified server).
- **Deterministic cleanup**: stop/reap of every owned child on COMPLETE,
  gate STOP, launch failure, and executor exception — no orphan survives
  `campaign_executor` returning.

`scripts/issue280_runner.py` is untouched (verified byte-identical in the
PR diff). The r3 observer-bracket slice law is retained verbatim as
`slice_request_bracket`.

## Tests (`tests/test_issue289_launcher.py`, 56 tests, ~124 s)

Two distinct CPU-only loopback stub servers (`tests/stub_issue289_server.py`,
stdlib `http.server`) — one per arm, distinct identities and observer
streams — on the SAME port, driven through the REAL gate engine (and its
REAL prelaunch compatibility gate):

- sequential R1→R2: all four admitted, every response attributed to its
  launch's own child PID, prior launch dead/reaped before the next starts,
  no orphan after return;
- stale-arm: stale-identity completion → `SERVER_IDENTITY_MISMATCH`
  transport failure, slot consumed, STOP (never admitted); foreign-health
  readiness race → `FOREIGN_SERVER_IDENTITY`, foreign listener not killed;
- port ownership: foreign listener → `PORT_OCCUPIED` refusal with zero
  completion requests to it; R2 child early death → fail-closed with R1
  provably dead first;
- termination: SIGTERM-refusing R1 escalated and reaped via the owned
  group; startup timeout bounded and cleaned;
- cleanup: exception mid-campaign leaves no port holder; gate STOP stops
  all children;
- pure laws: PID-reuse guard, port probe, r3 slice law unchanged;
- negative controls: four fail-open mutations (no prior stop, any-200
  readiness, no request identity, no port preflight) each demonstrably
  break the corresponding GREEN guarantee — the suite catches fail-open;
- r3 faithfulness: applying ALL four mutations reproduces the retained
  terminal shape exactly (R1 accepted twice, R2-cold transport-ok from the
  baseline server with R2's child dead on bind failure, gate STOP via
  missing R2 observer bytes).

### RED/GREEN record

- RED (module = faithful r3-law port, commit `8314d92`): 20/24 failed —
  stale-arm routing reproduced on CPU.
- GREEN (fix commit `a66ca34`): 24/24 OK (~88 s), same test file, byte
  unchanged between runs.
- Review 5459338940 correction round (B2/B3/B4): RED commit `c66e456`
  added 14 regressions against the merged head — 9 failed exactly per
  the review findings (builder environment values lost; permissive
  None-identity; silent `"stub"` prompt substitution / no binding
  interface); GREEN fix commit turned all 38 (24 original + 14 new)
  green with the corrected interface. The old permissive assertion
  (`pid_alive_same_instance(me, None)` is true) is inverted by the B3
  strict law.

## Preservation

No changes to the #280 observer/collector, source/model/threshold laws,
pinned comparator (`b29c606e` / tree `950999fe`), successor overlay
(`f3cd359feada1ba883955582cecf13dc75f1dcb8`), accepted r3 terminal
(STOP stands), or #273/#239/R8-J authority. The r3 terminal remains STOP;
any candidate-B launch is a separate maintainer authorization per issue
#289's completion section.

## Operator usage (next authorized physical campaign)

Deploy the repo at the accepted head to the physical host and drive the
campaign exactly like r3, replacing the session-local `LaunchCtx`/`launch`
with the tracked launcher:

```python
import json
from scripts.issue289_launcher import campaign_executor
from scripts.issue280_runner import MINIMAL_RERUN_MATRIX

# The frozen prompt bytes + request settings, bound to the accepted
# workload identity (review 5459338940 B4): load the accepted workload
# binding and pass it EXPLICITLY. The launcher authenticates the retained
# workload against an independent digest pin, then compares the caller's
# bytes/hash/settings to that authority (not to its own claims). Missing
# or mismatched authority/settings refuse completion dispatch.
workload = json.load(open("docs/investigations/"
                          "vulkan-same-request-280/workload.json"))
prompt_binding = workload["prompts"]   # {"P1": {text, utf8_sha256, settings}}

def command_builder(arm, port, log_path, env_extra):
    dev = ["--device", "Vulkan0"] if arm == "A" else \
          ["--device", "Vulkan0,Vulkan1", "--tensor-split", "1,1"]
    # The dict handed in IS the child's environment base (B2): values
    # added/updated here reach the spawned server. The launcher's
    # I280_LAUNCH_IDENTITY is injected after the builder returns and
    # always wins.
    env_extra.update(LD_LIBRARY_PATH=..., VK_DRIVER_FILES=...,
                     ISSUE280_OBSERVE="1")
    return [llama_server_path, "--model", model_path, ..., *dev,
            "--host", "127.0.0.1", "--port", str(port)]

summary, launches = campaign_executor(
    MINIMAL_RERUN_MATRIX,            # unchanged frozen matrix
    command_builder=command_builder,
    workdir=runs_dir, port=8791,
    prompt_binding=prompt_binding,    # REQUIRED: exact frozen bytes
    retain=lambda label, kind, record, bracket: ...,   # r3 retention law
    health=health_sampler,           # r3 health law
)
```

The launcher injects `I280_LAUNCH_IDENTITY` into each child environment;
the server wrapper must echo it (header `X-I280-LAUNCH-IDENTITY` or JSON
field) on `/health` and completions — the production llama-server build
needs a small addition for that, to be staged under its own review before
any authorized physical run. Every request record binds the response to
the launch/arm identity for the traceability record.

## Physical integration limitation (review 5459338940 §4) — NOT EXECUTABLE

The pinned production `llama-server` currently does **not** echo
`I280_LAUNCH_IDENTITY` on `/health` or completion responses. The
launcher's identity-verified readiness and response-attribution laws
therefore make the real physical path **NOT EXECUTABLE** as-is: this is
a deliberate barrier, not a defect to code around. This PR does not
bypass, mock, weaken, or disable the identity requirement in production
(the CPU stub servers echo it, as tests only).

The physical path becomes executable only after a narrowly reviewed
identity-echo implementation in the server wrapper (or an equivalently
independently verified identity-binding adapter) exists, with source and
build identities explicitly approved under its own review. Nothing in
this coding PR authorizes such a build, a source/overlay change to the
frozen binary, or any physical dispatch.

The accepted #280 r3 terminal remains STOP. Any candidate-B experiment
is a separate physical authorization decision (issue #289 completion
section), not granted here.

## Exact-head correction for review 5461889945 (N1 / N2)

Starting reviewed head: `3b499400fba555249185b8669216f46b86442eee`.
Preflight local HEAD, remote PR branch and GitHub PR object all matched.
`origin/main` remained `57adca1ffac11fe70a914d5862910100690f9947`:
no main drift. Existing B1–B4 history is preserved additively.

N1: `_child_alive()` returned a nonempty `(alive, reason)` tuple, but
readiness tested the tuple itself. RED reproductions with a real loopback
child showed unreadable/changed start time after capture still producing
COMPLETE, and an exited child being recorded as ready when the expected
listener token was available. Readiness now unpacks/checks the Boolean and
reason before probing the identity token. Missing or changed evidence and
child exit are immediate failures; the real executor consumes the aborted
slot, stops synchronously, sends zero completions and performs bounded
owned-group cleanup. The request-path identity guard is unchanged. A
one-site mutation restoring tuple truthiness is killed in all three cases.

N2: caller-supplied text/hash consistency was not independent authority;
in-row text and arbitrary settings could replace the verified request.
Production now verifies the retained workload bytes against independent
SHA-256 `d49f7083fd78e244caf64b401cb35bc0a0392d5e0a545d8322ede5a9257050b9`
and frozen P1 SHA-256
`726fd522508fd0a0a89184017d30dd808c8538cbce850c3c04d8b07c31f371de`.
Caller bytes/hash must match that authenticated authority; a missing,
unknown, self-consistently substituted or row-overridden binding is refused.
The eight workload settings are mandatory and allowlisted, with exact
frozen values and strict types (booleans cannot masquerade as numbers).
Reserved `prompt`, unknown settings and conflicting settings fail closed.

Historical `samplers:["greedy"]` is normalized to `["top_k"]` only under
[the previously accepted #280 execution identity](https://github.com/Zutfen-LLC/inferswarm/issues/280#issuecomment-6030829366).
Temperature 0, top_k 1, seed 42, n_predict 128, repeat_penalty 1,
cache_prompt false and stream true remain unchanged. Existing
`timings_per_token:true` instrumentation remains fixed; an explicit false
is rejected. No context policy or configurable sampler policy is added.
No workload or frozen evidence bytes are rewritten.

The effective payload is validated before dispatch. Retained identity is
derived from the exact serialized bytes passed to urllib: body SHA-256/byte
count, parsed prompt SHA-256/UTF-8 byte count and parsed effective settings.
The real CPU HTTP stub captures those actual received bytes and verifies
equality with the record. Prompt plaintext remains absent from records.
Synthetic bindings live only in the CPU test harness via a scoped authority
patch; production accepts neither in-row synthetic data nor a bypass flag.

RED-first commit added 15 focused cases before production changes: 24
assertion/subtest failures against unchanged reviewed production code, no
loader errors. The identical primary regressions then passed GREEN.
Supplemental authority-file loss/drift coverage and the exact targeted
mutation were also exercised against immutable `git show` bytes of the
reviewed production module: 18 focused tests, 26 behavioral failures
(subtests counted separately); the positive approved sampler spelling and
mutation-detection controls passed. Final launcher suite: 56/56 PASS,
including all 38 original identities, lifecycle/cleanup/environment laws,
four original fail-open controls and deliberately mutated r3 STOP replay.
No original assertion was weakened: the sampler assertion now requires the
accepted top_k spelling, and the synthetic fixture uses an explicit scoped
CPU binding while retaining the actual P1 semantic gate.

The first combined run exposed a CPU-stub diagnostic race: SSE completion
was sent before its synthetic observer bracket finished appending, so a
reader could see a partial JSON line. The stub now finishes that bracket
before delivering the response body; production observer/slicing code is
untouched. This fixes test determinism, not physical execution semantics.

CI topology, planner registry and all five shard commands are unchanged.
The existing launcher module remains registered in shard 1 only; new
identities are discovered within that module. Ordinary hosted CI is a
maintainer-requested pre-review proof of the exact-head five-shard/aggregate
contract. Final CPU Validation remains deferred until renewed exact-head
GO; no local canonical full-suite ceremony is run in this correction.
Living project status is unchanged: this correction adds no acceptance,
physical result, capability promotion or execution permission. This guide
and the retention record document the software-only correction instead.

Physical integration remains NOT EXECUTABLE: the pinned production server
still requires independently reviewed launch-identity echo on both health
and completion responses. This PR does not implement or bypass that gap.
Accepted #280 r3 STOP stands. Zero physical execution, zero model/GPU work,
zero new hardware authority; no candidate-B, #281, holdouts, prerequisite
issue or broader campaign. Stop for renewed maintainer review, unmerged.
