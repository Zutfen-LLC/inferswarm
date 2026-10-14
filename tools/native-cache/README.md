# Verified native RPC cache development slice (#311)

The initial [evidence comment](https://github.com/Zutfen-LLC/inferswarm/issues/311#issuecomment-6170026415)
proved useful zero-payload reconnect/restart reuse, but reproduced corrupt and
truncated false hits and a full-object cache-load vector. This additive patch
addresses those demonstrated native mechanisms at llama.cpp
`b29c606e28a01b1bc8c1351026a0fa6e616bf6c4`. It is a CPU development slice,
not completion of selective Q8 operator startup or physical acceptance.

## Reuse and boundaries

Backend-neutral requirements already exist: exact immutable artifact
revision/representation/range identity and selective resumable acquisition in
[`issue99_artifact_core.py`](../../scripts/issue99_artifact_core.py), reverified
inventory and missing-only epoch-fenced deltas in
[`issue101_orchestration.py`](../../scripts/issue101_orchestration.py), and
verify/fsync/atomic publication semantics in
[`issue200_r8f_stage_cache.py`](../../scripts/issue200_r8f_stage_cache.py).
Those historical producers remain unchanged. Their contracts can serve another
engine; this patch neither chooses llama.cpp as a permanent foundation nor
adds a backend framework. llama.cpp is the current experimental baseline; a
Strata-like engine remains a candidate without a comparison in this delivery.

The native-specific changes are isolated here:

- Preserve the FNV filenames and raw payload format used by #200 staging. FNV
  remains a lookup key. The existing >10 MiB cache threshold is unchanged;
  smaller transfers continue to send payload. The client supplies SHA-256 and exact transfer length
  derived from the actual source bytes; the worker rechecks each use.
- Stream each cold transfer directly from the caller through the dispatcher,
  with a 1 MiB worker scratch buffer. Cache hits use the same fixed bound.
  The buffer-set call waits for a verified acknowledgement. Async tensor SET
  uses a synchronous fallback to bound owned copies and preserve data lifetime
  and event ordering; scheduling/performance may change.
- Stream into the backend using the existing tensor descriptor, offsets, type,
  strides, allocation and device APIs. A corrupt/incomplete hit reports MISS;
  its provisional destination bytes are overwritten by a complete verified
  upload before the same connection can submit a graph. A broken upload closes
  the connection before acknowledging or processing later commands.
- Cold cache writes use a unique dot-prefixed temporary file in the target
  directory, complete-write/SHA readback checks, file fsync and atomic rename.
  Interrupted dot files are never lookup candidates. Warm verification hashes
  precisely the bytes written to the backend, eliminating a verify-then-read
  race. Final files must be regular, exact-length files; symlinks are refused.
- Reuse the pinned vendored SHA-256 implementation, without a new dependency.
  The changed layouts and SET acknowledgement require RPC major version 7;
  both endpoints must use this patch. There is no silent fallback to unsafe
  v6 cache hits. This POSIX development patch is tested on Linux/TCP/CPU only.

The coordinator still supplies and locally reads/hashes each entire upload
range, including a warm hit. Its loader may still retain full source members
or stage a tensor. Wire reuse is not elimination of coordinator-local work.
CPU backend destination memory is actual resident weight state; it is separate
from the fixed transfer scratch. GET readback and graph commands retain their
existing staging behavior. No full-model or GPU memory bound is claimed.

## Concrete remaining integration gap

[`qwen_q8.py`](../../inferswarm/operator/qwen_q8.py) and
[`source.py`](../../inferswarm/operator/source.py) explicitly enforce
`full-source-both-hosts/1`, all six authenticated members on both hosts, stock
runtime identities, and provisioned cache descriptors. The ordinary Q8 runner
already passes `--cache` and `LLAMA_CACHE`. This patch does not loosen those
validators or alter the historical #299/#301 observer overlay.

The smallest next connection is a reviewed successor source contract: keep
complete coordinator GGUF scaffolding where the loader requires it; project
frozen participant immutable assignments plus shared metadata to #99 artifacts;
use #101's verified missing-only delta and a bounded successor to #200 staging;
prepare only assigned native payload ranges, retain valid unassigned entries
within an explicit disk budget, then verify before owned-worker startup. Bind
the patched executable identity and update the source-derived memory ledger.
Exact tensor-split upload boundaries need source-backed support before admission.
A worker's RPC API itself requires no model repository and this fixture supplies
only assigned tensors; that does not establish the operator successor contract.

Disk budgeting, stale temporary cleanup, and participant prepare/reconcile are
not implemented by this native slice. Native cache retention remains optional
and unbounded unless externally managed. Mutable/KV ownership is unchanged.
#311 remains open; #300 is unchanged. No physical qualification is inferred.

## Local build and focused tests

Reuse an existing source object store; this does not read its modified checkout:

```bash
python3 tools/native-cache/build.py --source /path/to/retained/llama.cpp \
  --output /new/owned/build --cmake /path/to/cmake
NATIVE_CACHE_BUILD=/new/owned/build/build python3 -m unittest tests.test_native_cache -v
```

Without `NATIVE_CACHE_BUILD`, the tests build the CPU/RPC closure with two jobs
and per-process address-space/time bounds. `NATIVE_CACHE_SOURCE` selects retained
Git objects. CI reuses #309's authenticated native-source archive acquisition
when local objects are unavailable; only native source is fetched. No model
weights, CUDA compilation, inference, packages, cluster hosts, or security
changes occur. `NATIVE_CACHE_CMAKE` can select an existing CMake executable.
`NATIVE_CACHE_RESULTS` optionally writes a compact result JSON outside the
checkout. Earlier test evidence is retained separately and never rewritten.

The focused cases cover cold, fresh connections, process restart, B+C delta,
post-startup corrupt/truncated/same-size wrong content, interrupted worker
publication and recovery, Q8 encoded tensor bytes, nonzero offsets, async SET,
and cold/warm staging before GET. The relay counts application weight payload
separately from metadata/control and verification GET; it does not count TCP/IP
headers or inference activations. CPU fixtures do not establish model quality.

See [hardware-recipe.md](hardware-recipe.md) for a short future recipe requiring
separate physical dispatch.
