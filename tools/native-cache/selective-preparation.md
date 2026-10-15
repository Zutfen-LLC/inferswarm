# Selective participant backing adapter (#311)

This bounded development slice composes existing authority and recovery
contracts. It does not add a manifest framework, cache daemon, scheduler or a
permanent runtime choice. The opt-in CPU startup connection below is development coverage, not physical Q8 acceptance.

## Reuse map and loader boundary

| Source | Reuse or concrete gap |
| --- | --- |
| `scripts/issue99_artifact_core.py` | Exact content/provenance/range identity, requirement classes, authorization, identity-bound partial/resume and acquisition ledger. Its whole-object verification/finalization is replaced by a streaming subclass; the frozen producer is unchanged. |
| `scripts/issue101_orchestration.py` | Frozen participant/Node/epoch requirements, verified inventory, issued missing-only delta, source attempts and reconciliation. No second distribution protocol. |
| `scripts/issue200_r8f_stage_cache.py` | Verify, fsync, atomic publish, final revalidation semantics. The successor publishes a same-filesystem hardlink from verified backing, avoiding another weight-sized disk copy. The historical producer is unchanged. |
| `tools/native-cache/native.patch` / PR #316 | Same raw payload/FNV cache view; SHA-256 and length remain authority. Actual protocol-v7 cache consumption uses bounded worker scratch. |
| `inferswarm/operator/source.py:validate_q8_payload` | Existing controller identity joins exact assignment/quantization/type/shape/member/range/unit ownership to metadata and range SHA authority. The projection includes only this participant's immutable assignments. |
| Pinned `src/llama-model-loader.cpp:570–647,1732–1735` | Coordinator opens every GGUF split; fallback loading reads a full tensor and calls tensor SET. Warm RPC still hashes locally supplied source bytes. Changing the coordinator loader is separate from worker backing. |
| Pinned `tools/rpc/rpc-server.cpp` | Worker has no model-path API. It consumes the tensor descriptors and bytes supplied over RPC. It does not need tokenizer arrays, unrelated tensor descriptors, GGUF headers or a complete repository. |

The explicit successor is
`coordinator-full-source/participant-assigned-rpc-backing/1`, implemented for
stopped-worker preparation in `scripts/issue311_native_backing.py`. Ordinary Q8
startup accepts this opt-in contract for the historical CPU build pair
in `operator-build-identities.json`, or the explicitly selected
[Step A CPU05 + CUDA03 pair](step-a-build-pair/README.md). Legacy `full-source-both-hosts/1` remains
available with its existing checks. See the startup scope below.

The callable `prepare_q8_participant` accepts an already authenticated existing
Q8 source payload, a separately reviewed patched executable SHA, an explicit
epoch, a streaming Node, a provisioned Source and `DiskBudget`. It verifies the
actual executable before preparation and requires the protocol-v7 patch
identity. The controller must authenticate that binary's build provenance;
merely computing the hash of an arbitrary executable cannot establish its
native implementation. No runtime is built, installed or spawned by this API.
Large ranges require the existing provisioned bounded FNV helper.

## Exact metadata and immutable backing

The single required metadata artifact contains exactly:

- successor backing contract and exact model/revision/representation;
- participant/Node identity and the authenticated metadata-index digest;
- native source pin, patch SHA, protocol major and executable SHA;
- assigned tensor state/member/offset/length/type/shape, binding/memory/immutable
  authority, unit ownership, artifact identity, content SHA and native lookup key.

The worker does not acquire the global index or raw headers. The controller's
index is retained as provenance authority, not duplicated as worker state.
Every assigned weight artifact uses the existing #99 record and binds exact
source-object SHA/length and byte range to its own SHA/length and model identity.
Header descriptors alone do not establish weight content SHA authority.
Generated shared metadata is capped at 1 MiB; changing assignments changes only
that small dependency plus the missing weight delta. Mutable/KV/session state
is never cached or reconstructed by this adapter.

Warm preparation revalidates local backing without source reads. Reconstructed
Nodes/controllers use the same durable objects; #101 sequence/attempt fencing
within a controller lifetime is preserved. Only issued required artifacts can
be acquired. Unassigned cached content stays optional. Final SHA verification
rejects corrupt resumed prefixes; interrupted identity-bound prefixes use #99
resume. Bad final backing is refused and preserved. Explicit operator recovery
may move it aside and run preparation again; the adapter never deletes unrelated
or historical final content. Dot-prefixed/interrupted native files are never
eligible hits.

Only existing native whole-tensor, single-SET, offset-zero payload boundaries are
projected. The pinned RPC device has no host-buffer capability, excluding the loader's
asynchronous chunk path. The real pinned loader fixture below observes and
checks whole-tensor requests, including cache hits. Other boundaries are refused
by the opt-in native guard before immutable weight transmission. No arbitrary expert slices or tensor-split cache
support is implied. Native hash reuse still applies only above 10 MiB; smaller
tensors have verified participant backing but SET sends their bytes.

## Disk and host-memory accounting

`DiskBudget(limit_bytes, min_free_bytes, reserve_bytes)` is mandatory. Admission
runs before acquisition, under a preparation lock, with the owned worker stopped.
It charges every retained file under the owned backing root, including history,
foreign content, corrupt files and partials, by max(logical length, allocated
blocks), deduplicated by inode. Hardlinked RPC views do not double-count weights.
Missing contents plus conservative state/directory overhead, explicit reserve
and filesystem free headroom must fit. Partial prefixes are conservatively not
credited. Exceeding budget fails; there is no eviction optimizer or automatic
deletion. For unique native hash-eligible contents, let `D` be their summed payload
length, `L` the largest payload, and `N` their count. The native adapter requires
`reserve_bytes >= D + L + 16384 * (N + 1)`: durable repair duplication, one active
replacement temporary file, and conservative filesystem/metadata overhead. This
minimum is checked before acquisition. Low-level `publish_rpc_views` composition
also requires the budget and rechecks the reserve and actual retained accounting
before publishing. Final accounting is rechecked before a success receipt.

The first native repair may break a prepared object/RPC hardlink, preserving the
corrupt object inode and adding a valid independent RPC inode. Every unique
eligible content can do this; reserving only the largest payload was insufficient.
Later successful serial repairs replace the independent RPC inode and free its
previous instance, so another durable copy does not accumulate on every repair.
The reserve is deliberately conservative even for views already independent;
existing duplicates are additionally charged by their actual distinct inodes.
Repeated successful repairs of the declared view are covered, with one active
replacement at a time. Interrupted native leftovers remain charged on the next
stopped-worker preparation before restart; this is not an unlimited interruption
or concurrent-write quota. No damaged or historical object is automatically deleted.

This is admission for a stopped-worker preparation and its declared immutable
view, not a quota daemon. The existing native server's independent optional
cache writes remain unbounded outside that declared experiment. Stop and
reconcile before reassignment; undeclared uploads or multiple writers require a
separate runtime contract. Do not infer live enforcement from a preparation
receipt.

Native-only legacy `rpc/<key>` files are not adopted into the #99 object inventory
by this slice. First preparation can fetch a separate verified object; both copies
are charged. Prepared restart reuse is distinct from native-only migration.

### Preserved repair-budget failure and correction

Maintainer review of `52f95384bf46ec63423faa55d57443b71e7ad674` reproduced the
P2 counterexample: two declared 12 MiB ranges repaired with correct readback, yet
retained backing reached **MEASURED** 50,331,848 bytes against an admitted
38,010,880-byte ceiling. The original largest-temp-only reserve did not cover the
durable extra inodes. That finding supersedes the earlier repair-budget claim;
the passing original tests and CI did not exercise this counterexample.

The new actual Q8-adapter/native regression is RED on that reviewed implementation:
50,344,196 retained bytes against the same ceiling, including its small exact
metadata dependency. After the correction, the insufficient reserve is refused
before acquisition. A 64 MiB ceiling admits the corrected allowance and contains
multiple repairs of both declared ranges, with repeated repairs retaining no
further copies and the largest active temporary replacement still fitting. A
separate case starts with already independent object/RPC copies: a tight total
refuses without source reads or deletion, while a sufficient total reuses them
and bounds repeated repairs. A descriptor-only check proves content deduplication
of the repair reserve. These are synthetic CPU observations and calculated bounds.

Application source requests are at most 64 KiB; verification reads are at most
1 MiB with no object-sized Python finalization or inventory buffer. The existing
native FNV helper uses 1 MiB reads. Metadata/descriptors, OS page cache, native
CPU destination weight residence, backend layout/scratch, GET/graph staging and
coordinator full-source/hash/loader work remain separate charges. No permanent
Python host weight mirror is created. This is not a proof of physical host peak
or GPU feasibility.

## Reproducible bounded checks

```bash
python3 -m unittest tests.test_issue311_preparation -v
NATIVE_CACHE_BUILD=/path/to/reviewed/build \
  NATIVE_CACHE_RESULTS=/new/owned/results.json \
  python3 -m unittest tests.test_native_cache -v
```

Offline cases cover cold assigned-only acquisition, warm reuse with origin files
absent in a fresh Python process, assignment delta, exact metadata and runtime
bindings, corrupt/truncated content, interruption and damaged-prefix recovery,
short/oversized reads, stale requirements, wrong revision/quantization/ranges,
disk budget/free headroom, deduplicated repair reserves and bounded Python allocation.
Native cases include multiple and repeated declared repairs plus preexisting
duplicate backing. No GPU/model download.

The synthetic CPU/loopback composition test prepares A+B (24 MiB), starts the
actual protocol-v7 worker, then reconstructs preparation and restarts the worker.
Cold acquisition is **MEASURED** 25,165,824 bytes; warm acquisition is **MEASURED**
0; reassignment to B+C+Q acquires **MEASURED** 25,186,304 bytes (only C and the Q8
encoded fixture). Prepared native loads have **MEASURED** zero weight SET payload
and exact readback. Maximum source read is **MEASURED** 65,536 bytes, with zero
unrelated acquisition. Native control bytes and verification GET are counted
separately by the existing relay; there is no inference/steady-state activation
measurement. Those are compact fixture observations, not real-model results.

## Ordinary CPU startup connection

`participant_backing` is an opt-in private strategy option alongside the successor
`source_contract`, enabled `rpc_cache`, and existing per-role `observer` paths:

```json
{"epoch": 1, "memory_id": "B-disk", "limit_bytes": 274877906944,
 "min_free_bytes": 1073741824, "reserve_bytes": 137438953472}
```

These are illustrative policy inputs, not a measured physical fit. The remote
participant declares an empty full-GGUF `backing` list. Its `cache_path` names
already prepared #317 objects/native views; its `source_path` remains provenance
and is never opened there. Run the existing stopped-worker preparation adapter
first, including cold/delta acquisition and its mandatory repair-aware admission.
Normal startup verifies prepared backing and refuses missing data; it does not
install an origin service or silently fetch complete source files. Reassignment
requires stopping the owned worker, preparing the delta and creating a new plan.

The ordinary runner acquires its leases, verifies participant backing plus the
coordinator's complete source, authenticates the finite per-role build manifests,
and only then spawns the owned RPC worker. Both owned runtime roles receive an
exact assigned upload guard through `IS311_ASSIGNED`. Worker verification receives
assigned descriptors/runtime metadata and small member provenance, without the
global tensor index, tokenizer or raw GGUF headers. Its receipt labels all member
identities as provenance and reports zero locally verified full members/headers.
The controller still opens every GGUF split and reads/hashes actual source bytes.
Warm worker reuse does not remove that coordinator dependency.

`operator-build.py` composes the retained #301 observer overlay and #316 cache
patch from the existing SHA-pinned source archive, preserves the conflicting
`rpc_set` hook, and records attempts before the hash-hit early return. It uses
the pin's CMake target closure for actual CPU `llama-server` and
`ggml-rpc-server`, with exact executable/archive/compiler/options identities in
`operator-build-identities.json`. The historical #301 manifests and producers
are unchanged. Arbitrary self-declared executable/manifest pairs are refused.
No runtime is built or installed by normal startup.

The native guard accepts one immutable destination per assigned tensor name,
exact original type/shape/SHA/length and one offset-zero whole-tensor SET.
Partial uploads, views, duplicate destinations, reshapes and changed runtime
identities are refused explicitly. Server cache reads/publication are restricted
to declared immutable payloads; unrelated mutable/activation SETs retain transfer
semantics but cannot create new cache entries against the assigned repair reserve.
Protocol-v7 per-use integrity, atomic repair and ownership checks remain intact.
This remains one controlled owned worker/writer, not a concurrent quota daemon.
Smaller tensors retain verified backing but still send SET bytes below the
unchanged >10 MiB hash gate. Arbitrary expert slices, row/tensor splits, missing
explicit output weights and alternate native/backend builds are unsupported.

Memory accounting retains coordinator full-source mappings, largest tensor reads,
source hashing/page residence, destination weights, backend overhead and explicit
UNKNOWN obligations. The successor replaces the obsolete weight-sized RPC
message copy with a 352-byte descriptor, receive/cache-hit vectors with fixed
1 MiB scratch charges, and full participant GGUF storage with the configured
prepared-backing ceiling (including reserve/history). Receive scratch is charged
for load and serve. Assigned metadata/guard payloads have a 2 MiB charge on each
role; native map/allocator overhead is UNKNOWN on both roles, and backing-page
residence remains UNKNOWN. No physical
host peak or automatic execution admission is claimed.

The compact native regression calls the actual pinned
`llama_model_loader::load_all_data`, using six synthetic GGUF members and F32/Q8_0
weights, through the same source-admission and owned-RPC-spawn functions called
by ordinary Q8 startup. It does not instantiate the full Qwen model or perform
inference. Native frame observations join name/type/shape/offset/length/SHA to
assigned metadata and exact GET readback. **MEASURED** weight acquisition is
51,348,736 bytes cold, 0 after fresh Node/worker restart, and 12,582,912 bytes
for the missing assignment delta. Including metadata, preparation acquires
51,351,132 / 0 / 12,585,766 bytes. All three prepared loads send 0 weight SET
payload bytes. Verification GET traffic is 51,348,736 / 51,348,736 / 63,931,648
bytes; control requests are separately 6,504 / 6,504 / 7,186 bytes. The coordinator
retains 89,098,816 bytes of full fixture source on every run. Native partial and
duplicate destination controls fail explicitly. These fixture results do not
prove full-Qwen placement, selector visibility or request correlation.

```bash
python3 tools/native-cache/operator-build.py --archive /retained/pin.tar.gz \
  --output /new/owned/operator-build --cmake /provisioned/cmake
NATIVE_ASSIGNED_BUILD=/path/to/the/exact/reviewed/operator-build \
  python3 -m unittest tests.test_issue311_startup -v
```

The historical identity table describes the retained CPU pair; a newly compiled
binary at another path/toolchain may differ and requires separate review.
`strategy_options.build_pair: "step-a-cpu05-cuda03"` selects both complete
uploaded Step A manifests together, including the distinct CPU05 client. Omission
or `historical-cpu` retains the old defaults. This private finite selector is
available only for selective backing; Step A requires `one-gpu`, enabled cache,
observer paths and the client-mediated route. Both participant executable hashes
are checked in admission and complete manifests are compared before spawn and
at static collection. Mixed pairs and incomplete descriptions refuse. This recipe does not automatically qualify arbitrary builds.
Without the explicit build environment variable, ordinary CI runs the offline
startup/config/identity regressions and skips the native fixture.

## Next physical step

Maintainer review of this coding slice comes first. CUDA builds and roughly
16 GiB RAM/two 12 GiB GPU qualification remain separate under #315, with per-device
headroom and actual host residency observations. The default finite pair remains CPU-only; the explicit Step A pair can describe
one-GPU startup but does not establish physical readiness. The
[compact Step B recipe](cuda-prerequisite-recipe.md#step-b--selective-backing-and-gpu-readback)
bounds testing on the small worker instead of reusing the full-model CPU partition. Existing #302 live observer
inventory/selector/request-correlation gaps remain explicit; this slice does not
turn static startup into physical or inference acceptance. #311 and #300 remain
open. No merge or Final CPU Validation is dispatched here.
