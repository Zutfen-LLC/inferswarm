# Selective participant backing adapter (#311)

This bounded development slice composes existing authority and recovery
contracts. It does not add a manifest framework, cache daemon, scheduler or a
permanent runtime choice. It is not Q8 operator startup acceptance.

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
preparation only in `scripts/issue311_native_backing.py`. The old
`full-source-both-hosts/1` Q8 runner/validators are unchanged and still reject
this successor. They must not be advertised as selectively prepared.

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
projected. The ordinary native loader's chunked/asynchronous upload path may
choose other ranges; exact observed upload boundaries must be joined before
normal Q8 startup admission. No arbitrary expert slices or tensor-split cache
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

## Next bounded step

Connect the successor to normal owned-worker startup with reviewed per-role
patched build identities, actual upload-range observations, worker source
verification and updated memory charges. Keep the coordinator's full-source
dependency explicit until its loader is separately changed. Then separately
authorize the cold/warm physical recipe under #315 with roughly 16 GiB RAM and
two 12 GiB GPUs, per-device headroom and actual host residency observations.
#311 and #300 remain open. No merge or Final CPU Validation is dispatched here.
