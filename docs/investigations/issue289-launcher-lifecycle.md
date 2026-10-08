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

## Tests (`tests/test_issue289_launcher.py`, 24 tests, ~90 s)

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
from scripts.issue289_launcher import campaign_executor

def command_builder(arm, port, log_path, env_extra):
    dev = ["--device", "Vulkan0"] if arm == "A" else \
          ["--device", "Vulkan0,Vulkan1", "--tensor-split", "1,1"]
    env_extra.update(LD_LIBRARY_PATH=..., VK_DRIVER_FILES=...,
                     ISSUE280_OBSERVE="1")
    return [llama_server_path, "--model", model_path, ..., *dev,
            "--host", "127.0.0.1", "--port", str(port)]

summary, launches = campaign_executor(
    MINIMAL_RERUN_MATRIX,            # unchanged frozen matrix
    command_builder=command_builder,
    workdir=runs_dir, port=8791,
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
