# Bounded real-stream compatibility correction (D1/D2/D3)

## Outcome and scope

The unchanged complete retained R1-cold raw stream now passes the corrected
observer under baseline A's frozen **logical output-role** contract. The original
accepted collector permanently reproduces its RED result:
`graph sequence/request mismatch`. This is CPU replay, not a new execution,
retroactive physical acceptance, performance result, or authorization. The
original terminal remains STOP and the other three requests remain not attempted.

Final verification: **173 Issue280 tests passed**, all eight Issue280 modules;
**27 independent adversarial mutations rejected with their target reasons**;
prelaunch compatibility failure invokes zero injected executors. The full native
`llama-context.cpp` successor passes CPU-only `c++ -fsyntax-only`; the actual
inserted graph block additionally compiles/runs in a CPU metadata probe. No
Vulkan build, GPU/model/device execution, network, SSH, purchases, holdouts,
branch operations, commits or pushes were performed.

## D1: sequence sets are not unique sequence IDs

At the pinned source, `llama_ubatch.n_seqs` counts sequence-set layout slots.
`split_simple` uses one slot per token even for one sequence. `n_seqs_unq`
counts the union of per-token IDs, and `seq_id_unq` enumerates its complete
sorted unique IDs (`source-semantics/src/llama-batch.h:34-41`,
`src/llama-batch.cpp:507,790-831`). The successor emits:

- the unchanged `sequences` (n_seqs) and first `seq` fields;
- `n_seq_tokens`, `b_equal_seqs`, `n_seqs_unq`, complete `seq_ids_unq`.

General new physical streams require complete direct uniqueness metadata,
exactly one ID equal to the accepted request/batch sequence, count/list
agreement, sorted/deduplicated nonnegative IDs and
`tokens == n_seq_tokens * sequences`. Missing/partial/conflicting metadata,
wrong sequence/request and actual multisequence graphs fail closed.
Old CPU_FIXTURE fields remain legal under the old synthetic law. No general
`sequences == tokens` or unconditional positive-count admission is introduced.

### The bounded old-stream witness

The old raw alone does **not** prove exclusive token membership. For this one
original capture only, the validator authenticates the complete retained
raw/server/terminal bytes and pinned initialization source semantics. The full
server says `initializing, n_slots = 1, n_ctx_slot = 4096, kv_unified = 'false'`
at original server line 2688. It does **not** log literal `n_seq_max=1`.

The one-slot inference is source-derived: server's n_slots is n_parallel;
`common/common.cpp:1722,1749` maps n_parallel and kv_unified to context
parameters; `src/llama-context.cpp:99,1674` applies the effective sequence
limit; `src/llama-batch.cpp:58-64` rejects IDs outside that limit. Non-unified KV
is essential: unified KV instead permits LLAMA_MAX_SEQ. This is corroborated
local artifact custody plus pinned initialization-path semantics, not an
independent attestation of the historical runtime executable.

The witness is bound to the **exact retained bytes**: the legacy inference is
granted only by the compatibility module's single-use authority, which is
accepted exclusively at consumption time through non-virtual re-validation
(exact authority-class type identity, an in-module SHA-256 equality check of
the supplied stream against the retained capture, single-use slot — PR #286
round 3). A stream that merely shares the historical request/batch/graph
projection is NOT byte-identical and obtains nothing: subclasses, duck types,
foreign-module instances, fabricated `object.__new__` instances and any
non-identical stream all fail closed. This deliberately lets
inventory/compute/KV mutations traverse the same validator and fail at D2/D3
rather than being masked by a whole-mutated-raw hash refusal (the projection
digest remains a test-only probe, never an admission input). Unrelated
old-shaped streams without direct metadata fail closed. Explicit terminal
sequence conflicts are also rejected.

## D2: exact host vocabulary and byte accounting

The central literal host-buffer allowlist is `{CPU, CPU_Mapped, Vulkan_Host}`.
These names derive from pinned CPU buffer/get_name/is_host callbacks and the
Vulkan host buffer callback, with `GGML_VK_NAME` explicitly `Vulkan`:
`ggml/src/ggml-backend.cpp:2438-2509`,
`ggml/src/ggml-vulkan/ggml-vulkan.cpp:16902-16957`,
`ggml/include/ggml-vulkan.h:10`. There is no prefix/suffix normalization.

Emitted host names are retained in `placement.cpu_state[*].backend`.
Host weights enter `cpu_weight_bytes` and the model-weight denominator only;
KV/other host state enters host state accounting, never a die's numerator.
Explicit bdf/backend conflicts fail, including BDF-plus-backend claims that
contradict the graph's actual name/BDF binding. `unassigned` denotes the
producer's null buffer, hence UNKNOWN ownership, not CPU. Lookalikes and
unknown accelerators cannot acquire host or GPU credit.

## D3: logical output role, not a nonexistent required name

Baseline A still requires the output role on `0000:07:00.0`; candidate B still
requires it on `0000:0b:00.0`. All old block-placement, KV, per-die completed
compute, request framing, shape/stride, copy occurrence/range and host-leg
laws remain active.

The role policy is frozen to Qwen2.5-3B-Instruct-Q4_K_M, model SHA-256
`9c9f56a391a3abbd5b89d0245bf6106081bcc3173119d4229235dd9d23253f94`,
architecture qwen2 and the pinned producer source. The authenticated historical
terminal records that model hash/size, and the full server records its model
filename. Explicit conflicting model/source/architecture fields fail.

Pinned `src/models/qwen2.cpp:22-31` uses optional output.weight and, if absent,
a **duplicated** token_embd.weight output allocation. Loader duplication across
buffer contexts preserves the tensor name; tensors_by_name is a list, not a
unique-name dictionary. `qwen2.cpp:144-151` and llama graph build_lora_mm show
that `result_output` is the MUL_MAT consuming this actual output operand.

A tied-role witness requires all of:

1. Authenticated pinned model/source policy; output.weight is absent from all
   inventory (including host inventory).
2. Exactly one GPU token_embd.weight inventory allocation, on the frozen
   output die, with the model-bound 255252480 bytes.
3. The distinct host input backing allocation with matching exact bytes.
   It is not required to be GPU resident and is not merged with the GPU copy.
4. In **every graph**, a completed submitted dispatch on the output die whose
   node is exactly result_output / MUL_MAT and whose actual weight operand is
   exactly token_embd.weight with matching bytes and an independently valid
   observed allocation range.

A distinct output.weight path, if present, instead requires that exact inventory
and result_output / MUL_MAT operand/compute proof; tied fallback is not silently
used. output_norm alone is never sufficient. Wrong owner, missing operand,
wrong op, noncompleted work, ambiguous GPU copies, absent/corrupt CPU backing
and even coordinated corruption of all matching tied sizes fail.

No D3 producer changes are needed. New streams with D1 direct metadata can use
this same frozen model-role policy and existing output node/operand rows.
`output_role_evidence.model_binding` explicitly labels this as authenticated
**model policy**, not observation of a new runtime model hash. Actual runtime
binary/model authentication remains a separately authorized execution concern;
CPU replay is not that attestation. Inventory buffer pointers are ggml backend
buffer pointers, whereas runtime weight pointers are underlying Vulkan buffer
pointers: their literal equality is deliberately **not asserted**.

## Custody and historical preservation

`observer-R1-cold.i280.raw.gz` is the parent's exact complete 762447-byte archive.
Its decompressed 13264272 bytes have SHA-256
`b1fa13966a715d2009efdde4fa602a5a6f0b70d93c3884ceef0d14426bfcc796`.
There are 69058 total lines, **69053 I280 JSON records** and five framing/noise
lines. The full server archive decompresses to the original 13670081 bytes /
71243 total lines, SHA-256
`2dc0d51bb11113536b6993123510bf2ddfc088bd58db97ad91a3806d66cb82ff`.
`TERMINAL.json` is an unchanged byte copy, SHA-256
`c7bccbc3e613ee537aef012d02076b5d861d27d1c02974956a981c0497deaa66`.

The permanent gate matches every raw I280 row to the full server by timestamp
and all semantic fields, normalizing **only** the recording cut's added
requests_planned. Startup/warmup graphs in the server are not inserted into the
raw or credited to request work. No original rows were reconstructed.

`accepted-observer.py` was copied with `git show` from accepted HEAD
`832a9f4adcba2bebfa66f0ed5f1e004cba7fb16d`, SHA-256
`17021e0fb8e9fe10db1b363142bf8e73e56a616d5e61833475cf90129b036d5a`.
This preserved source reproduces historical RED without rewriting old evidence.
`custody.json` is explanatory; decision hashes are independently fixed in the
compatibility module. Each invocation re-reads actual bound bytes; no mutable
source/fixture gate cache is used. Twelve complete public pinned source files
are retained under source-semantics, with byte hashes checked by the gate or
source transform.

The original transform and original instrumentation identities are untouched.
The successor inherits five transformed files byte-for-byte; only the existing
llama-context graph metadata insertion changes. Its identity is separately
regenerated from the full local pinned Git tree and independently replayed into
a new scratch destination:

| Identity | Value |
|---|---|
| Source pin | b29c606e28a01b1bc8c1351026a0fa6e616bf6c4 |
| Base Git tree | 950999fe62b7fe55f44ab5b7394e3c8542f37f12 |
| Successor full transformed Git tree | f3cd359feada1ba883955582cecf13dc75f1dcb8 |
| Successor overlay SHA-256 | 6e73ce72b8c6f5a06ead05dc2db64fb2274cf90a51a1d2a2936e100fd3ab7f8b |
| Successor patch SHA-256 | 48e3882a0a8ec03c875cc7b5a91ed912f4dfef54fe87339dcff3b3c8367980c5 |
| Successor llama-context.cpp SHA-256 | 43ccf1ba0b543bfcdbd9f17b43fd1231fbcc7001ae165ca150a6650077e5daa7 |
| Inherited emitter SHA-256 | d537c86b83bef00e4eff7d631830f4ca09ef0d0dcab69ed1f38bef082949475f |
| Inherited occurrence helper SHA-256 | 253dc2eeb5020075a6bd52824ac73c14ae88ab3a6744f8f4ac070cea7aced68d |

The standalone gate verifies regenerated source hashes, patch, overlay/header
bytes, full-tree identity and the compiled actual inserted block. Producer or
model/provenance drift is structured false. The native context syntax probe and
`git apply --check` both exited 0. A unified patch has whitespace-prefixed blank
context lines by definition: do not strip them or change its frozen digest;
use Git's patch-aware whitespace settings when checking the patch artifact.

## Terminal bundle integrity

The controller additionally reproduced a hosted-portability RED: the successor
source test depended on `/home/zutfen/llama.cpp-252`. It now reads the retained,
SHA-bound pinned source archive instead; hosted CI needs no local llama.cpp clone.
A RED-first ninth source-compatibility test checks the bundle-local deterministic
manifest emitter. Together with the original handback this extends focused
coverage from 173 to 174 tests; prior RED/GREEN logs remain unmodified historical
verification receipts. The advisory review then reproduced two additional
failures: an agent-specific temporary-directory fallback, and uncaught malformed
DEFLATE in either retained gzip archive. Three RED-first regressions cover the
portable no-TMPDIR/non-Hermes-HOME gate, both compressed-custody seams, and the
runner's STOP/not_attempted/zero-executor response. The probe now uses standard
`TemporaryDirectory` selection (honoring TMPDIR); invalid DEFLATE is translated
at the custody boundary into structured rejection. Source-compatibility coverage
is now 12 tests and total focused coverage is 177. The original advisory NO-GO
and exact RED/GREEN correction logs are retained as historical review receipts;
these fixes do not alter producer overlay identities or grant execution authority.

After bundle, collector and test bytes are final, from the repository root run:

```sh
python3 docs/investigations/vulkan-same-request-280/compatibility/manifest.py > docs/investigations/vulkan-same-request-280/compatibility/MANIFEST.sha256
```

The emitter does not read an existing manifest. It excludes its terminal output,
Python caches and living CI/status metadata. The repository evidence lifecycle
checks enforce digest integrity. The bundle-local `.gitattributes` disables only
end-of-line whitespace lint for the exact retained patch and two verbatim RED
receipts; it does not alter their bytes or relax collector/admission checks.
It is a CPU-only custody tool, not a campaign executor or authorization grant.

## Acceptance mapping

| Seam/law | Positive proof | Negative proof and required reason |
|---|---|---|
| Historical failure | accepted observer on full raw is RED | exact graph sequence/request mismatch |
| Corrected real replay | 40 graphs, 457 completed compute commands | no problems |
| D1 simple layout | 31 sequence sets, one unique ID | multi-ID/wrong-ID/layout mismatch: sequence |
| D1 arbitrary legacy stream | only the exact retained bytes through the compatibility module's non-virtual single-use authority | changed token/sequence/timestamp/unrelated stream: sequence or ordering |
| D1 explicit attribution | accepted/batch/graph/end seq consistent | wrong request: cross-request; wrong end seq: sequence |
| D2 host names | all three literal names, preserved backend, host-only denominator | lookalikes/unknown: placement; conflicting fields: conflicting |
| D2 null allocation | no host/GPU credit | unassigned: UNKNOWN ownership |
| D3 tied model role | unique GPU output alias plus separate host input copy | missing/ambiguous/wrong die: output role |
| D3 actual computation | per-graph completed result_output/MUL_MAT and exact operand bytes | missing operand, wrong op/name/bytes/completion: output role |
| D3 tied identity | pinned model hash/architecture/alias bytes | missing backing/model drift/coordinated size corruption: output role |
| D3 distinct output | output.weight inventory and actual output compute | explicit distinct inventory disables tied fallback: output role |
| Full placement | blocks 0-35 baseline; exact 0-18/19-35 candidate | missing upper block: inventory/placement |
| KV ownership | every contract die has positive KV | missing KV: kv_cache |
| Completed compute | every graph has completed nonempty work on each die | removed completions: completed |
| Other preserved laws | valid two-die synthetic boundary and full existing suites | wrong BDF, range, shape, occurrence, host attribution still reject |
| Permanent gate | authenticated archive + producer CPU probe + corrected replay | missing/digest/model/producer/module drift: structured false |
| Prelaunch safety | full compatibility check before injected launch | injected failed gate: zero launches; all slots not_attempted |

`adversarial-results.json` retains all 27 exact verdict/reason sets. Mutations
that leave original sequence rows alone retain their authenticated sequence
witness and therefore genuinely reach D2/D3; target reasons are asserted by
`mutation-check.py`, not substituted with a digest failure.

## RED-first and GREEN results

Production fixes followed observed tests, never merely a plan or generated
plausible verdict. `RED-real-corrected-harness.txt` ran 23 tests with 24 failing
assertions/subtests and **zero harness errors**, before production edits.
`RED-source.txt` ran six tests with six feature-absence assertion failures.

The initial `RED-real.txt` is also retained for transparency: its 15 errors came
from a test mutator assuming every raw line was JSON and from a missing-field
assertion. The mutator was corrected to preserve framing/noise, the assertion
made a real failure, and the corrected RED suite was run before implementation.
The initial bare `python` command was unavailable; all actual verification uses
`python3`. Follow-up RED logs pin coordinated tied-byte corruption, frozen
full-tree drift, new successor tied-role compatibility, explicit terminal seq
conflict and broken producer-module structured failure before their fixes.
Exact counts/timings and archive hashes are in `verification-results.json`.

Final command:

```sh
python3 -m unittest discover -s tests -p 'test_issue280_*.py' -v
```

| Module | Passing tests |
|---|---:|
| test_issue280_admission | 31 |
| test_issue280_observer | 57 |
| test_issue280_real_compat | 43 |
| test_issue280_retention_fix | 5 |
| test_issue280_runner | 10 |
| test_issue280_source | 18 |
| test_issue280_source_compat | 12 |
| test_issue280_task_check | 14 |
| **Total** | **190** |

Final result (PR #286 round 3): `Ran 190 tests`, `OK`. No skips/failures/errors.
This was every Issue280 module, not the full canonical CPU suite. The parent
owns canonical/hosted gates and finalization. (Round-1 closing receipt was 173
tests in 197.858s; rounds 2-3 added the authority-boundary and exact-type
regressions retained below.)

Reproduction commands (offline, CPU-only):

```sh
python3 scripts/issue280_compatibility.py
python3 docs/investigations/vulkan-same-request-280/compatibility/mutation-check.py
c++ -std=c++17 -fsyntax-only \
  -I docs/investigations/vulkan-same-request-280/compatibility/instrumentation/src \
  -I /home/zutfen/llama.cpp-252/src -I /home/zutfen/llama.cpp-252/include \
  -I /home/zutfen/llama.cpp-252/ggml/include -I /home/zutfen/llama.cpp-252/ggml/src \
  docs/investigations/vulkan-same-request-280/compatibility/instrumentation/src/llama-context.cpp
```

Exact structured corrected replay is retained in `GREEN-replay.json`: baseline
A / 40 graphs; weights 1923946496 bytes; KV 150994944 bytes; completed commands
457; logical boundary and host-leg bytes 0; tied output operand token_embd.weight
255252480 bytes on die A; physical_execution NONE; ok true; problems empty.

## Round-3 exact-type authority boundary (PR #286)

The round-2 authority boundary used `isinstance`, which Python subclasses
satisfy, and consumption dispatched virtually through
`authority.sequence_known(raw)`. A same-module adversarial subclass
overriding `__init__` (bypassing `_legacy_authority_arming`) and
`sequence_known` to return True therefore conferred
AUTHENTICATED_R1_ONE_SLOT_SOURCE_INFERENCE on the known non-byte-identical
same-projection attack stream (reproduced RED at reviewed head 1eda081:
ok=true, 40 graphs, 457 completed compute commands). The corrected invariant
is mechanical, not a claim about object fabrication:

- The authority object carries no authority of its own; `sequence_known()`
  is removed. Authority exists only while the compatibility module's
  `consume_legacy_authority(authority, raw)` re-derives every fact
  non-virtually inside that module: exact class identity
  (`type(x) is _LegacyCompatibilityAuthority`, never isinstance — an
  override-bearing subclass is a different type), an independent SHA-256
  equality check of the supplied bytes against the retained capture
  (RAW_SHA256), and an unspent single-use slot spent on the sole success
  path.
- The collector performs no authority type check and never dispatches
  caller-supplied methods; it forwards both the object and the raw bytes
  to its own `_compat` instance and fails closed on False.
- Constructor arming remains defense-in-depth only: correctness does not
  depend on `_legacy_authority_arming` being inaccessible or on instances
  being unfabricable — `object.__new__` fabrication is refused at
  consumption, not construction.
- Production `run_campaign()` admission never constructs or forwards the
  authority; the exact historical R1 replay through `check_compatibility()`
  remains the sole intended compatibility path, and direct successor
  metadata admission is unchanged.

Ten focused regressions pin the boundary (same-module adversarial subclass;
no virtual dispatch of `sequence_known`; duck type; foreign
compatibility-module instance; fabricated exact-class instance on changed
bytes; the changed same-projection stream under every forged/fabricated
authority; genuine authority + exact bytes once; second consumption;
genuine authority + modified bytes; production runner STOP with no legacy
evidence in campaign output). No overclaim of unforgability is made
anywhere: Python object fabrication always allows constructing the exact
class; the invariant is the non-virtual consumption-time revalidation
itself.

## Ownership handback / remaining limits

Implementation-owned repository paths, now handed back without committing:

- scripts/issue280_observer.py
- scripts/issue280_runner.py (small prelaunch gate only)
- scripts/issue280_compatibility.py (new)
- scripts/issue280_source_compat.py (new)
- tests/test_issue280_admission.py (legal fixture and role assertions adapted)
- tests/test_issue280_real_compat.py
- tests/test_issue280_source_compat.py (new)
- this compatibility directory, including preserved complete capture/provenance,
  accepted collector, pinned source semantics, successor instrumentation,
  mutation tool/results and exact RED/GREEN verification reports.

No changes were required to test_issue280_runner.py or retention-fix tests.
The parent owns CI, registry, status, living docs, finalization and all other
worktree changes. This implementation did not edit those paths or any old
instrumentation/evidence identity. No implementation blocker remains in the
bounded correction. Native Vulkan build/integration, independent actual runtime
binary/model attestation and any physical verification remain explicitly
unperformed and unauthorized; inferred legacy sequence/output evidence is not
promoted to observed metadata or physical proof.
