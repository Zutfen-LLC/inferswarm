# Bounded initial acquisition (opt-in)

This CPU/offline engineering successor amortizes fixed request and checkpoint
costs during **initial assigned-byte preparation**. It does not alter native
RPC, placement, computation, cache keys, disk admission, or execution authority.
The retained #99/#101/#311 producers remain byte-identical. Existing callers
keep their 64 KiB acquisition loop and per-chunk state publication.

The supplied diagnostic bundle `is321-diag-bundle.zip` was materialized from
Library `libfile_e149e9617edc819198f1a62c93c087be`; its SHA-256 is
`32e63ef8f156af12a56cc3c627d4b45fc5599511fcf7dd5991cdb6f7e37916f0`.
The outer hash and every internal manifest row were checked locally. Its
operational `ChainHttpSource` and `range_server.py` each cap requests at 64 KiB;
the client creates a fresh urllib connection for each request. The unchanged
#311 cache atomically rewrites/fsyncs the state file and directory every append.
Server records contain 40,800 full chunks plus 64 B: 2,673,868,864 B total over
approximately 1,132 s, median request cycle approximately 30 ms (10 ms clock
resolution). These supplied server observations do not separate checkpoint,
relay, connection, file-open, or payload cost. The three banks themselves total
2,673,868,800 B. No rate limiter was found in those wrappers.

## Paired recipe

Use `scripts/bounded_acquisition.py` only for one owned preparation writer with
the participant runtime stopped, under the existing preparation lock/budget.
The source is an explicit operator-owned **loopback or loopback tunnel**.
There is no discovery, parallel scheduler, retry loop, daemon, or new cache
layout. Keep the source files immutable for the preparation scope.

First derive the authenticated records using the existing projection:

```python
from issue311_native_backing import project_q8_preparation, runtime_identity
projection = project_q8_preparation(payload, epoch=epoch,
    runtime=runtime_identity(executable, executable_sha256))
records = [record for record, key in projection['native_ranges']]
```

Provision that exact record list on both ends through the existing trusted
control path. On the source host, replace the operational 64 KiB query server
with the paired helper (explicit port, existing owned source directory):

```python
from bounded_acquisition import AssignedRangeServer
with AssignedRangeServer(models_directory, records, port=source_port,
                         range_bytes=1 << 20) as server:
    server.serve_forever()
```

On the participant, use the same explicit provisioned `file://` descriptor
expected by #101 and the local end of the existing owned tunnel:

```python
from bounded_acquisition import AssignedHttpSource, BatchedArtifactCache, BoundedStreamingNode
from issue311_native_backing import prepare_q8_participant

node = BoundedStreamingNode(node_id,
    BatchedArtifactCache(backing_directory, checkpoint_bytes=8 << 20),
    range_bytes=1 << 20)
with AssignedHttpSource(source_id='origin', endpoint=provisioned_source_endpoint,
        port=local_tunnel_port, records=records, range_bytes=1 << 20) as origin:
    result = prepare_q8_participant(payload=payload, epoch=epoch,
        executable=executable, executable_sha256=executable_sha256,
        node=node, origin_source=origin, budget=budget, fnv_binary=fnv_binary)
```

The generated assigned metadata stays on #311's existing small exact local
metadata path. Network reads stay within **one** frozen assigned range; adjacent
ranges are never merged to cross a whitelist boundary. The server rejects other
objects, off-range requests and requests over its explicit cap. HTTP/1.1 uses
`Range` and `If-Match`; every response must be 206 and echo exact Content-Range,
total source length, Content-Length, and immutable source ETag. Encoded/chunked
responses are refused. ETag is a source-manifest assertion, not independent
verification of source file bytes: destination length/SHA remains authoritative.

Both helpers must be changed together; this client is deliberately incompatible
with the old `?off=&len=` wrapper. Merely changing repository code cannot improve
an unchanged 64 KiB operational server. Range caps may be explicitly configured
from 1 to 4 MiB on both ends, with the node's read size no larger than either
cap. Checkpoint intervals are bounded from one range through 64 MiB. Defaults
are 1 MiB reads and 8 MiB checkpoints. Preparation receipts retain #311's
`application_read_chunk_bytes=1 MiB` file-verification scratch field; record the
selected acquisition range/checkpoint settings separately when using overrides.

## Recovery and resource bounds

Data is appended directly to disk. At a checkpoint the data file is flushed and
fsynced **before** publishing the sidecar through #311's fsynced temporary file,
atomic replace and directory fsync. A fresh process accepts only an exactly
identity-bound checkpoint whose extent is in bounds and present on disk. It
truncates an uncheckpointed tail before requesting more bytes. A malformed,
foreign, or truncated checkpoint discards only that artifact's owned partial;
unrelated/verified/history files remain under existing disk accounting.

A controlled connection interruption checkpoints completed ranges (and a
bounded partial explicitly supplied by another source). An incomplete HTTP
response is dropped; it does not enter the partial. A process or write failure
may replay bytes after the last checkpoint, bounded by the checkpoint interval
plus one range (at most 8 MiB with the aligned defaults) for this one writer.
There is no power-loss guarantee
beyond filesystem fsync/atomic-rename semantics. A failed directory sync after
state replacement leaves either an old checkpoint or the new data-fsynced one.

Only complete expected-length content with a matching SHA-256 reaches atomic
object publication through unchanged #311 finalization. A corrupt resumed
prefix still fails that final check. If publication fails before object rename,
the complete checkpoint can be finalized after restart without reacquisition.
If an object is already published, ordinary verified-cache reuse applies.

The checkpoint interval consumes disk, not a RAM buffer. Client application
scratch is bounded by two acquisition ranges plus small state/HTTP overhead
(the inherited loop may retain its preceding range while reading the next).
File verification uses 1 MiB scratch. The source helper holds one bounded range
per active connection; this recipe provisions one acquiring participant. This
is not a capacity or RSS claim about hardware or the OS page cache.

## Reproducible offline evidence

Run with the canonical Python 3.12 CPU environment:

```bash
.venv/bin/python -m unittest tests.test_bounded_acquisition -v
```

COUNTED in the local synthetic A/B fixture: 2 MiB + 17 B assigned payload, same
bytes/offset/hash, one loopback HTTP server, one participant, no model or GPU.
The legacy arm uses fresh urllib connections and the unchanged #311 cache;
the opt-in arm uses 1 MiB ranges, a persistent connection and 8 MiB checkpoints.

| Operation | Legacy arm | Opt-in arm |
|---|---:|---:|
| Requests | 33 | 3 |
| Accepted TCP connections | 33 | 1 |
| Atomic state publications (including initial empty state) | 34 | 2 |

A separate 9 MiB + 17 B fixture counts 10 requests and state extents
`0, 8 MiB, 9 MiB + 17 B`. These are deterministic operation counts, **not
wallclock speedup or end-to-end inference evidence**. CPU, storage, RAM, link
rate, GPU, driver and model performance are not measured by this fixture.

Regressions cover off-whitelist/server-cap refusal; truncated, oversized,
wrong-range, changed-identity, wrong-status and corrupt HTTP responses;
mid-transfer disconnect/identity change; controlled interruption; partial data
writes; data-before-state ordering; atomic state-replace and object-publication
failures; fresh-process tail truncation; invalid checkpoint bounds/binding;
corrupt prefix rejection; warm missing-source reuse; explicit 4 MiB reads; and
application allocation bounded independently of object/checkpoint size.

## Documentation impact and limits

This opt-in helper and recipe are prospective coding work. There is no accepted
new capability, physical gate result, execution authorization or integration
branch change to enter into `docs/project-status.json`; the roadmap and
architecture frontier therefore retain their recorded authority. The separately
supplied IS321B hardware result must remain labeled operator-reported until its
bundle is independently inspected and accepted. Historical FAIL/STOP records
remain unchanged; #311/#313/#315/#300 remain open and #321 was closed by #322.
No new hardware runs, native builds, host contact or physical performance claim
is part of this change.
