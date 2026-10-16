# Hermes recipe: fixed 05 + dual-GPU 03 diagnostic baseline

Coding handoff only: this recipe is NOT hardware execution authorization. Do
not run host probes, native builds, model hashing, preparation or inference as
part of implementing/reviewing it. The new workloads are NOT directly
comparable to the historical IS326/327 chat request.

## Freeze before a separately authorized run

Keep the existing reviewed `step-a-cpu05-cuda03` config, native build pair,
source pin, model, device order and placement unchanged: full source and layers
0–40 on 05; layers 41–44 on 03/CUDA0; layers 45–47 plus output on 03/CUDA1.
No topology matrix, optimizer, quantization change or Vulkan work. A later
experiment may change ONE placement decision while retaining these workloads.

Reuse the verified assigned backing and disjoint per-listener guards via the
existing preparation/verification path in [the two-CUDA recipe](q8-two-cuda-recipe.md).
Require the verification receipts to authenticate BOTH banks, and record
preparation acquisition as zero only when the actual retained ledger says zero.
The runner does not acquire missing backing. Stop rather than repair/retry
inside this session. Retain the existing opt-in source digest cache; it skips
only authenticated unchanged source reads, never the remaining integrity checks.

Freeze exactly three sequential native `/completion` requests: one explicit
warmup, short-prompt decode, and longer-prompt uncached prefill. This example
uses raw text completions, NOT the historical chat template, and deliberately
small output caps; there is no request asking for a reasoning explanation.
Generation caps include every generated token, including any unexpected
reasoning. Do not increase caps or replace prompts after observing responses.

The following CONTROLLER-LOCAL preparation writes only small JSON files. Set
`run` to a fresh private local directory first. It neither reads model bytes
nor contacts either host. The config still contains its legacy request for
backward compatibility, but in session mode that request is NOT sent.

```python
import json
from pathlib import Path
from inferswarm.operator.q8_session import validate_session

run = Path('/absolute/private/baseline-inputs')  # fresh, controller-local
run.mkdir(mode=0o700)
rows = '\n'.join(f'row-{i:03d}: the stored color is blue.' for i in range(128))
def entry(prompt, cap, warmup=False):
    return {'warmup': warmup, 'body': {
        'prompt': prompt, 'n_predict': cap, 'temperature': 0, 'seed': 42,
        'stream': False, 'cache_prompt': False}}
raw = {'schema': 'q8-two-cuda-session/1', 'requests': [
    entry('Complete the sequence with the next word only.\nred red red red', 8, True),
    entry('Repeat the sequence, separated by spaces, without commentary.\n'
          'A B C D A B C D A B C D A B C D', 32),
    entry('Read the records. Answer the final question with the color only.\n'
          + rows + '\nQuestion: What color is stored in row-064?\nAnswer:', 16),
]}
session = validate_session(raw)
path = run / 'session.json'
path.write_bytes(session.canonical_bytes)
path.chmod(0o600)
print('session request_sha256:', session.digest)
```

Create the envelope using the existing exact `q8-two-cuda-experiment/1` fields,
opt-in string, limits and freshly applicable device bindings. Its config hash
still covers exact config bytes. In session mode its `request_sha256` MUST be
`session.digest` above, binding the entire ordered list, warmup flags and all
settings—not the legacy config request hash. Do not reuse an IS326/327 envelope.

## One bounded invocation

Under separately granted authority, use the existing spanning watchdog and
cleanup ownership described in the two-CUDA recipe. One absolute Phase-B budget
covers verification, load, every request, observer collection, retention and
cleanup; warmup consumes the same budget. The existing 180-minute total,
160-minute execution STOP, 20-minute cleanup reserve and all memory/swap,
headroom, disk and per-GPU reserve limits remain unchanged. Preparation, if
needed, also consumes the outer Hermes budget; never reset it at invocation.

```bash
python3 -m inferswarm.operator experimental-q8-two-cuda \
  --config /absolute/path/step-a-cpu05-cuda03.json \
  --envelope /absolute/path/session-envelope.json \
  --session /absolute/private/baseline-inputs/session.json \
  --source-digest-cache /absolute/coordinator/path/source-digests.json \
  --evidence-root /absolute/private/fresh-baseline-evidence
```

One server and its two workers start once. All three POSTs use that same loaded
server, in order. No retries, hidden warmups, reloads or adaptive tuning. Source
identity, owned liveness and resource checks remain active between requests.
A genuine execution, watchdog, allocator, device, headroom or deadline failure
stops the sequence. Keep all completed responses and any partial attempt.

`cache_prompt:false` explicitly requests the pinned native completion path's
prompt reset. Record the returned raw `timings.cache_n` when available; absent
reuse reporting means UNKNOWN, not proven zero. `tokens_cached` alone is not
reused-prefill proof. A request for uncached prefill does not prove cold OS page
cache, cold kernels or all runtime caches disabled. This is a loaded-model
baseline, not a cold-start benchmark.

## Sanity check and report (no further requests)

Read the private `session-report.json`, all `request-NN-response.json` files,
per-request started/received/final metadata and final `manifest.json`. Never
publish raw content automatically. The evidence root is 0700; artifacts are
0600. Verify the frozen order, exactly one warmup and one load; exclude the
warmup from measured summaries, but include it in consumed time and requests.

For each response, inspect `stop`, `stop_type`, generated content and reported
counts. `stop:true` plus `stop_type:limit` means the bounded generation ended at
its cap; it is not proof of an EOS-complete answer. Empty/error/malformed
responses are execution failures. Record cap truncation separately from answer
correctness. Do not infer success from a nonempty HTTP response alone.

Explicit workload sanity evaluation, performed offline on retained bytes:

- Warmup: record completion only; no accepted correctness claim.
- Decode: check that whitespace-separated generated tokens begin `A B C D`;
  report the checked prefix and whether the remainder remains in that cycle.
  A cap ending the sequence is expected, not a claim of EOS completion.
- Prefill: check the first nonempty generated answer line, stripped, equals
  `blue` (case-insensitive, allowing only a trailing period). Report FAIL if
  it reasons, gives another color or never supplies the requested answer.

These checks are workload-specific observations, not model qualification. The
runner deliberately records correctness as `NOT-EVALUATED`; attach these
separate offline check results rather than rewriting its raw report or flags.
Do not send a corrective request when a sanity check fails.

Report five independent outcomes: (1) attempted/completed requests and finish
reasons, (2) explicit sanity-check results, (3) timing/resources, (4) observer
completeness/refusal, (5) cleanup. Keep setup verification/load timestamps
separate from each POST's wall duration. Use native prompt/predicted timings
and counts only when returned; missing fields stay null. Nonstreaming HTTP
wall time is NOT TTFT. Retain timestamped CPU/disk/RAM/cgroup and per-GPU samples
with their phases, not invented utilization-to-throughput estimates.

A saturated/dropped-event observer refusal remains visible and does not erase
response/timing measurements. Existing detailed completeness reporting concerns
the two RPC terminal streams; raw client artifacts are retained too, but there
is no complete per-request native dynamic acceptance. Exhaustive observer
capture is not required for diagnostic timing. Do not attempt to fix saturation
here. Neither successful graph submission nor sampled residency/utilization
proves owned GPU kernel execution. Always retain `output_accepted:false` and
`physical_qualified:false`; two-GPU physical qualification remains unsupported.
Stop after reporting and verified owned cleanup. No subsequent hardware run is
authorized by this recipe, the code, tests, review or CI.
