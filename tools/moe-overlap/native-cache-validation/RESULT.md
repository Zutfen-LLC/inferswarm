# #321 CPU loopback integration result

Implementation source: `f269e073f58408cec721a0cde8b10f887c2a1e7a`, based on
main `203133661cfef9ce343d4402644c338fa54b4148`. Exact source hashes and immutable
commit binding are in `source-binding.json`; build manifests identify derived
harness/worker executables, compiler, flags and composed source. The unchanged
native-cache composer/patch/guard and reviewed operator identity table were
reused, not modified. This is CPU fixture engineering awaiting maintainer
review, with no GPU, physical, performance or numerical qualification claim.

RED: the build CLI lacked `--native-cache`; the harness lacked
`--assigned-banks`. Original failure logs are retained. GREEN: eight focused
tests pass through actual compiled pinned CPU/RPC graphs, rather than mocked
verdicts. The original harness/native-MoE tests passed; the initial aggregate
run stopped only at the existing native-cache build's absent `cmake` PATH
entry. Its six tests then passed with the already installed CMake executable.
152 planner/status tests and the finalizer's 19-stage drift check pass.

The fixture has 12 complete Q8_0 experts at the existing block geometry, with
sparse expert-dependent weights, reordered GGUF tensor storage, ten selected
experts and nonzero local shared work. No model is downloaded. The original
fixture generator and existing unchanged CPU operand reference independently
check mapping/layout and complete outputs: max absolute difference
3.725290298461914e-09, max ratio to its existing tolerance 0.022562583769759118.
This known CPU fixture comparison is separate from the remote numerical
checker, which continues to refuse `rpc-remote-unverified`.

Actual observations (byte counts MEASURED by the existing loopback relay):

| Observation | Cold | Worker restart |
|---|---:|---:|
| Assigned weight SET payload | 62,668,800 | 0 |
| Assigned hash lookups with successful graph execution | 3 | 3 |
| Output/verification GET payload | 51,200 | 51,200 |
| Scheduling status | SCHEDULING_EQUIVALENT | SCHEDULING_EQUIVALENT |
| Numerical checker | INVALID_OR_INCOMPLETE | INVALID_OR_INCOMPLETE |

Three cold native cache objects equal the exact original bank bytes. The
owned worker exits and a new process starts against those same durable files.
Restart makes three hash attempts and sends no weight payload, then executes
the graph and produces identical complete outputs. Both scheduling arms and
cold/restart match byte-for-byte. The omitted-shared negative control rejects.
`summary.json` records graph request counts, activation/routing, wire totals,
complete output digests and the independent comparison. The full request
ledgers and complete input, routing, partial/shared and arm-output exports are
retained. Cold wire totals also include one intentionally refused stock-v6
HELLO: it reports `RPC server version mismatch: 7.0.0` before upload.

There is no external model acquisition in this fixture: source bytes are
locally generated, and cold native SET publication supplies durable assigned
backing. Restart reuses it without reacquisition. These tests do not claim a
physical #311 distribution run or measured 05→03 memory/headroom. Coordinator
source reads and hashing remain; the worker uses the existing bounded native
cache path. Future physical acquisition, control and readback accounting is
specified in `../native-cache-recipe.md` and remains a later admitted task.

The manifest is bundle-local and terminal. Its source binding addresses the
implementation by immutable commit plus file hashes, so later living status
or CI changes do not rewrite these results. No merge or Final CPU Validation
dispatch occurred.
