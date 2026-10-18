# Layer-7 H5: frozen preparation and retained comparison (#314)

**PREPARATION / ANALYSIS ONLY. Explicitly do not run hardware now.** No command
in the preparation tools starts a native process, probes a host, opens an SSH
connection, acquires backing or grants execution authority. The explicit
`gather` command reads/hashes authenticated source bytes only during later
authorized preparation; its tests use tiny synthetic byte banks.
No new launcher or supervision mechanism is introduced. No accepted capability,
physical qualification, CI/Final CPU validation or issue closure follows.

## 1. Authenticate the retained hypothesis, not a new profile

Run from the repository root, controller-local:

```bash
python3 tools/native-hot-experts/provenance.py \
  --bundle /home/zutfen/data/demand-retry-20261018T0154Z/demand-retry-evidence.tar.gz \
  --check tools/native-hot-experts/capture-provenance.json
```

The fixed archive SHA-256 is
`5d52bf5badee1cdbf450d9c5ba59a1089c85ac45f0c386574cf0a7500b3bf42f`.
`capture-provenance.json` is canonical JSON plus one newline. Its member ledger
binds `REPORT.txt`, raw capture, controller reserialization, actual production
reducer source, retained reducer output, exact request artifacts, configuration,
model/source identity, completion receipts and historical limitations. The
verifier reads small tar members **without extracting or executing archived
code**, checks the archive's complete member ledger, requires the current
production reducer to match the retained reducer bytes, executes that production
reducer on the authenticated raw capture, and compares its entire canonical
output to retained `demand-summary.json`. Model-member identities are joined to
the checked-in Q8 metadata. No private raw capture or tensors are checked in.

The raw profile is 272,981 bytes with SHA-256
`00e9dff6d9f5e471c2f82e3fa52782b1461267ec1f288082d31c6ddf0ab54cee`.
Coverage is 48 layers, 512 experts, top-k 10, prefill plus 32 decode evaluations,
**1,584 observed/retained rows, zero drops**, qwen4exp-last-output mapping. Layer 7
H5 order is exactly **54, 74, 136, 290, 394**. Each appears at all 32 decode
positions: 160 of 320 selected slots. Layer 7 has 14 distinct decode experts but
92 distinct prefill experts. This is repetitive ABCD evidence only, not a
representative workload or a speedup. Prefill misses stay on the original path.
The historical general observer dropped events and remains REFUSED; the generic
raw-retention manifest remains partial. Neither limitation is silently repaired
or conflated with the independently complete dedicated capture.

## 2. Frozen requests and correctness checks

`frozen-requests.json` contains the base five-request native `/completion`
session. Do not add a demand capture: that would load a separate profiler and
change the experiment. Both arms send exactly these bodies, in this order:

| Index | Role | Generated cap | Frozen offline check |
|---|---|---:|---|
| 1 | Original red warmup | 8 | Completion only, no semantic acceptance |
| 2 | Original ABCD | 32 | At least `A B C D`, all remaining whitespace words in that cycle |
| 3 | Factual extraction | 32 | Entire stripped answer exactly `Lima` |
| 4 | Code/structured transformation | 32 | Entire response JSON parses as integer array `[1,2,3]`, no prose/fence |
| 5 | Original ABCD repeat | 32 | Same cycle check as index 2 |

Warmup and ABCD prompt UTF-8 bytes and canonical body bytes are identical to the
retained original session; index 5 is an exact copy of index 2. Preserve
`temperature:0`, `seed:42`, `stream:false`, `cache_prompt:false` and **every
`n_predict` value**. The new prompts and their checks are frozen before candidate
execution; do not replace prompts, increase caps, add corrective requests or
loosen checks after observing an answer. Warmup consumes the same load/budget and
request limit but is excluded from measured pairs. A generation cap includes any
unexpected reasoning. `stop_type:limit` is cap completion, not proven EOS.
Semantic failures remain failures even when timing looks favorable. Do not
require exact text equality across CPU/CUDA or overwrite raw runner correctness.

### Actual tokenization is a mandatory pre-inference gate

No actual tokenizer count for either new prompt has been measured in this coding
slice. Whitespace/character counts are not token counts. Before **any inference
in each arm**, use the admitted model's actual tokenizer with the exact native
raw-completion preprocessing (`add_special=true`, `parse_special=true`, no chat
template; pinned `tools/server/server-context.cpp` calls
`tokenize_input_prompts(..., true, true, ...)`), retain actual token IDs and validate **all five inputs <=128 tokens**.
Do not send an inference request to discover whether a prompt is too long.
Missing tokenizer results or any input above 128 are a STOP, not an invitation to
truncate/rewrite the frozen prompt. Tokenization consumes the same outer budget.

The guarded runner now calls its already-loaded, identity-bound server's
`/tokenize` endpoint for all five bodies before the first `/completion`, retains
`actual-tokenizer.json`, and calls
`comparison.validate_tokenizer_receipt(receipt, full_arm_session)`. This adds no
model load or inference request. The standalone offline validation command is:

```bash
python3 tools/native-hot-experts/comparison.py validate-tokenizer \
  --session /absolute/private/inputs/session-A.json \
  --receipt /absolute/private/actual-tokenizer-A.json
```

Receipt schema (values here are field descriptions, **not fabricated results**):

- `schema`: `is314-tokenizer-receipt/1`;
- `model_sha256`: the retained canonical complete-model identity object digest;
- `session_sha256`: SHA-256 of the **canonical full arm session**, including its
  `hot_experts` block;
- `tokenizer`: `source_revision` (native source pin), `executable_sha256` (actual
  admitted tokenizer executable digest), `add_special:true`,
  `parse_special:true`, `actual_model_input:true`;
- `requests`: exactly five ordered objects with `index` (1..5), `body_sha256`
  (canonical exact body), and `token_ids` (actual nonnegative integer IDs).

This validator authenticates field/count bindings, not producer honesty: the
runner binds the endpoint through its existing owned client/tunnel and uses the
admitted executable/model identity before inference. A standalone `TOKEN-BOUND-ONLY` result does not
prove that runner integration, source admission or execution authority exists.
The full arm digests differ; a receipt for A cannot be substituted for B.

## 3. Archive a non-authorizing executable plan

```bash
# Choose a genuinely fresh controller-local output directory.
python3 tools/native-hot-experts/comparison.py prepare \
  --output /absolute/private/fresh-comparison-inputs
```

This writes `plan.json` and the frozen base session, 0700 directory / 0600 files.
It records source/request/provenance hashes, fixed constraints, pending actual
tokenization, missing identity promotion and `execution_authorized:false`. It is
useful even while the immutable compact preparation artifact is not ready.
Existing destinations refuse, never overwrite an earlier freeze.

The checked-in example is immutable INTENT, not invented compact hashes. During
later authorized preparation, under the existing aggregate-owned helper and the
shared clock from section 4, gather/hash the exact source member locally on the
coordinator (no separate launcher, native model load or remote connection):

```bash
python3 tools/native-hot-experts/comparison.py gather \
  --manifest tools/native-hot-experts/example-manifest.json \
  --manifest-sha256 ae733f217a6f9dff7e7a40cf1b4e8c7c601d9e71fe0e078f0231c518a030994c \
  --source "Qwen3.8-Flash-Next-Q8_0-00004-of-00006.gguf=$MODEL_MEMBER" \
  --rpc-endpoint "$EXISTING_GPU0_ENDPOINT" \
  --clock /absolute/private/outer-clock.json \
  --output /absolute/controller/immutable-prepared.json
```

`MODEL_MEMBER` and `EXISTING_GPU0_ENDPOINT` must come from the exact admitted
config, not guessed host paths. The output path must be new. Every bounded
source-read chunk checks the shared execution deadline; worker upload remains
three complete offset-zero tensors during native context setup. Only the small
prepared JSON is persisted by this command, not another model bank. It emits
actual source/compact hashes, ordered ranges and global-to-local mapping. It
never claims persistent cache hits: each H5 component is below the unchanged
strict >10 MiB threshold. The existing guarded source verifier still joins this
preparation to independently authenticated model metadata/member/tensor ranges.

Once this API has produced its immutable controller JSON,
prepare a **new** directory with:

```bash
python3 tools/native-hot-experts/comparison.py prepare \
  --prepared /absolute/controller/immutable-prepared.json \
  --output /absolute/private/fresh-bound-comparison-inputs
```

It additionally emits `session-A.json` / `session-B.json`. To archive the actual
arm configs too, supply `--config-a /absolute/config-A.json --config-b
/absolute/config-B.json` together. Their raw bytes and hashes are retained as
`config-A.json` / `config-B.json`. The tool requires the candidate build-pair,
model identity, fixed workload and default41/45; every material setting must
match, allowing only `plan_id` and participant `lifecycle_dir` ownership names to
differ. This content check is not candidate identity promotion or runner
admission. Configs/envelopes are not invented when absent.

Each full session contains the same five bodies and the optional runner block:

```
hot_experts = {enabled: false for A / true for B,
              prepared_path: absolute controller JSON path,
              prepared_sha256: SHA-256 of that file's exact raw bytes}
```

The preparation API/runner, not this plan writer, validates prepared intent,
compact tensor/source hashes, native spec and assigned guards. The plan writer
never invents those identities. Preserve the prepared artifact in immutable
storage at the bound absolute path. Each envelope's `request_sha256` must bind
its **own entire canonical arm session**, not the base bodies, historical session
hash or the other arm's digest. Freeze each exact config/envelope raw hash too.

Both configs must use `build_pair: hot-experts-candidate-cpu05-cuda03` and the
**same candidate coordinator binary/build receipt**. The reviewed candidate
identity receipt is deliberately absent until a later real05 build and separate
reviewed promotion. Do not substitute a locally built executable, self-mint an
identity, use the old optimized binary for A or weaken identity admission. The
prepared/runner integration and actual tokenizer gate must be complete before
execution is eligible. Missing receipts mean refusal. Preparing files here is
not a hardware authorization or a request to perform that future build.

## 4. Later separately authorized A then B, no retry (not run now)

Before ANY later verification/gather/preparation, freeze one clock on the same
controller and boot that will run both arms. Do not run this now:

```bash
python3 tools/native-hot-experts/comparison.py clock --output /absolute/private/outer-clock.json
# Before each preparation phase and each arm, check the SAME record:
python3 tools/native-hot-experts/comparison.py clock --check /absolute/private/outer-clock.json
T0=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["started_monotonic"])' /absolute/private/outer-clock.json)
```

Retain that record and its hash in the final dispatch freeze; use its exact T0
for both arms. Execute preparation under the existing aggregate-owned guarded
helper with its runtime clamped to T0+9600, not an unbounded standalone process.
Use only the existing guarded CLI for each arm:

```bash
# FUTURE ONLY, after all separately granted authority and gates exist.
python3 -m inferswarm.operator experimental-q8-two-cuda \
  --config /absolute/private/config-A.json \
  --envelope /absolute/private/envelope-A.json \
  --session /absolute/private/inputs/session-A.json \
  --source-digest-cache /absolute/coordinator/source-digests.json \
  --outer-start-monotonic "$T0" \
  --evidence-root /absolute/private/fresh-arm-A
# After owned A cleanup and only if the original shared budget remains:
python3 -m inferswarm.operator experimental-q8-two-cuda \
  --config /absolute/private/config-B.json \
  --envelope /absolute/private/envelope-B.json \
  --session /absolute/private/inputs/session-B.json \
  --source-digest-cache /absolute/coordinator/source-digests.json \
  --outer-start-monotonic "$T0" \
  --evidence-root /absolute/private/fresh-arm-B
```

Both invocations now reuse the existing guard with the SAME explicit outer
start; the hot-expert session refuses an omitted outer start. Service/helper
RuntimeMax and request deadlines clamp to its remaining execution time. Keep
the existing spanning watchdog/ownership for preparation and cleanup; no new
launcher is introduced. One original T0 covers
preparation, hash verification, staging/upload, both loads, requests, retention
and cleanup. Total **180 min**, execution STOP **T0+160 min**, remaining **20 min
cleanup**. Never reset T0 at arm B or grant a fresh 160-minute inner window.
STOP rather than start B if remaining guarded time cannot cover it. A genuine
failure preserves partial evidence, stops the sequence and forbids a rescue run.
At most **one coordinator load per arm**; no retries, separate profiler load,
hidden warmups or repeat-until-PASS. No tuning/topology matrix.

- **A:** `enabled:false`; same candidate binary, `IS314_HOT_SPEC` absent; all
  layer-7 experts compute on original CPU path.
- **B:** `enabled:true`; only the existing runner stages the authenticated native
  spec and sets `IS314_HOT_SPEC`; use existing **RPC0/GPU0** context backend and
  persistent worker connections, never connect a third dispatcher/listener.
- Everything else identical: 41/45 complete-layer ownership, eight offload
  slots, split 4,4, RPC0/RPC1 order and UUID mapping, model/source/representation,
  coordinator CPU weights/shared path, cache/backing contract, threads, context
  2048, batch 128, microbatch 32, parallel 1, f16 K/V, KV offload on, op-offload
  off, flash attention off, unified KV off, fit off, lazy on, load-mode none.
  Do not copy the profiling client's 28 threads into the ordinary 14-thread
  configuration. Freeze and verify the actual ordinary thread setting for both.
- Aggregate coordinator **110 GiB**, aggregate workers **10 GiB**, owned swap
  zero; existing per-service bounds and floors unchanged: coordinator host
  MemAvailable 8 GiB, worker 4 GiB, each GPU reserve 512 MiB, relevant volumes
  64 GiB free. Keep aggregate ownership across source/helper/native activity.
- Use #311 stopped-worker assigned preparation and disjoint authenticated guards;
  never acquire missing bytes during load. Authenticate compact gate/up/down
  source slices and their complete encoded payloads through the prepared
  artifact. Reuse source digest witnesses only under the existing validation
  policy. Keep acquisition, hash-read, upload and steady-state traffic separate.
  A recorded zero must come from the actual relevant ledger/counter.
- Preserve original CPU banks as cold source and original ten routing slots.
  No rescue shrink, fewer H5 experts, moved complete layers, dtype changes,
  worker/cache patch relaxation, reserve reduction or alternative hardware.

## 5. Measurement and retention contract

Freeze phase markers and retain exact boundaries separately for **verification**,
**gather/hash/compact preparation**, **upload**, **model load**, **graph/context
setup**, then every **request** and **cleanup**. These are not additive guesses:
unknown/overlapping native phases stay explicitly unknown. Exclude setup from
request timing. Warmup is not a replacement for distinguishing upload/setup.

Record post-setup per-UUID VRAM **before requests** and runtime buffer/arena
allocation peaks (plus sampled device/host/cgroup peaks and their sampling
limitations). Preserve native setup/buffer logs; sampled `nvidia-smi` is not an
allocator high-water mark. Retain `IS314_SETUP` and `IS314_STEP` with request,
phase, layer and ownership joins. Keep hot/cold selection counts; original
routing/weights; per-layer and end-to-end latency; activation/routing/result
bytes; dispatch/shared/join timing **where actually available**. Missing counters
remain null with reason. Do not estimate kernels from RPC waits, infer expert
compute from general utilization or relabel RPC round-trip time as device time.

Retain exact source/build/compiler/patch/config/envelope/session/body/prepared
and model/member hashes, producer identities, raw response bytes, every
started/received/final request record, native logs, setup receipts, phase samples,
guard STOPs, resource outcomes and verified owned cleanup. Keep raw responses and
token IDs private; use fresh evidence roots. Never rewrite historical reports.
General observer saturation/completeness remains a separate outcome, not proof
against dedicated counts and not proof of per-expert GPU kernels.
Nonstreaming HTTP wall time **is not TTFT**; missing TTFT stays null. A no-gain or
slower B is a valid screening result. One A then B is not statistical speedup.

## 6. Executable retained analysis, no extra model requests

```bash
python3 tools/native-hot-experts/comparison.py compare \
  --a /absolute/private/fresh-arm-A --b /absolute/private/fresh-arm-B
```

The tool reads the existing runner's `session-report.json` and the five exact
`request-NN-response.json` files per arm. It checks full canonical session/body
hashes, order/settings, absence of extra response files, generated caps,
completion, A-off/B-on and the same prepared path/hash. It runs frozen semantics,
reports all four measured request pairs individually and preserves raw native
timings, cache_n, general observer status, cleanup and phase samples. Missing
responses, drift or incomplete execution refuse. Semantic FAIL returns nonzero
but preserves the analysis. Warmup is excluded from paired timings. No automatic
content publication, retry or output acceptance occurs.

**Response-only analysis cannot prove full config/build/topology equivalence,
one-load enforcement or a shared watchdog.** It labels equivalence unverified;
join the frozen config/build/source and outer-supervision receipts before
interpreting ratios. No ratio becomes a speedup/qualification claim by itself.

### Frozen numerical comparator, not fabricated tolerance

For *already retained* layer-7 input/output records in the existing IS309 binary
capture ABI (if available), not a new capture/launch:

```bash
python3 tools/native-hot-experts/comparison.py numerical \
  --reference /absolute/retained/A.bin --candidate /absolute/retained/B.bin
```

This reuses the existing bounded capture reader. All layer/shape/step records
must align, actual input arrays must match and every input/output must be finite.
It computes **max absolute error, RMS, relative L2 and cosine**. Zero reference
norm with nonzero error has undefined relative L2 (null); zero norm cosine is
null. The fixed verdict is `DIAGNOSTIC-NOT-QUALIFICATION`, with **no invented
CPU/CUDA tolerance** and no bitwise output requirement. Diverged autoregressive
inputs are not comparable same-input operands and refuse, rather than being
masked as backend error. Missing numerical captures remain `NOT-CAPTURED`.
The current native logging interface alone does not export these arrays; this
recipe does not imply otherwise or add a hardware profiling pass.

The existing independent `moe-operand-reference/2` contract in
`tools/moe-overlap/numerical-reference.md` is separately applicable only when all
original weights, captured F32 input/routing and independently reconstructed
plane masses are available and its supported-shape/backend assumptions hold.
Its unchanged per-element criterion is
`abs(observed-independent_expected) <= 2^-23 + 2^-19*independent_plane_mass`.
Do **not** replace independent plane mass with observed output, copy a legacy
CPU equality tolerance, widen a retained FAIL or declare this contract passed
from max_abs alone. A missing independent oracle stays NOT-EVALUATED and blocks
any numerical-acceptance claim. Text sanity and finite diagnostics are not model
qualification. `output_accepted:false` and `physical_qualified:false` stay false.
