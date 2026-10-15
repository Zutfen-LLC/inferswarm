# Step A CPU05 + CUDA03 build descriptions

The opt-in selector `step-a-cpu05-cuda03` binds **both** complete manifests in
this directory. This is a coding prerequisite for future functional testing,
pending maintainer review; it is not physical execution qualification. The
omitted selector (or explicit `historical-cpu`) retains
`../operator-build-identities.json` unchanged. No candidate receipt is imported
or promoted at runtime, and neither role can be substituted independently.

| Role | Uploaded manifest SHA-256 | Executable SHA-256 |
| --- | --- | --- |
| CPU coordinator on 05 | `dffc6a2ce7028a973a41949aac094f39dbc8d7884abfca25ba3430d0d4a7a01c` | `91f7ada4cb5d9805a292ec14b56518f80cb1b550834f30f225aeed676fcd518e` |
| CUDA worker on 03 | `e08ea250e56823072a5582a28e77edfe34774dafe0c3d8a0568f24274152f47d` | `46345f6c4df4f229aa11e76514c6c6eff9c9a148257f9232a505c8173d2ebf73` |

The manifests are copied byte-for-byte from `llama-server.build-manifest.json`
in the supplied `is319-stepa-evidence.tar.gz` and
`ggml-rpc-server.build-manifest.json` in `is319-cuda-evidence.tar.gz`.
The original private archives are retained by the operator, with SHA-256:

- CPU archive: `bb8d619fd8ea797aff5ef6ca750d24c1668169a771effdf153d37b2ea8ca6253`.
- CUDA archive: `1a8ce71eee4a637c7e1b8f1cadc205c8faaa843c77873583128afd17070ab7bb`.

Both archive digests and all 38 `SHA256SUMS` entries (16 CPU, 22 CUDA) were
checked before selecting these descriptions. Archive members were inspected
before extraction; included scripts were never executed. Raw logs, launch
scripts, receipts containing operator paths and access details are not published.
The two manifests contain no private addresses or usernames. Their path-bearing
identity options (`/usr/local/cuda/bin/nvcc` and the absolute system driver
library path) are preserved exactly, without redaction or hash substitution.
`SHA256SUMS` here covers only this provenance note and the two manifests.

Shared native inputs remain commit `b29c606e28a01b1bc8c1351026a0fa6e616bf6c4`,
source archive SHA-256
`03fb04316eb32a7b7347004a79a8dd60531c02f5a064d853fed3b53828951723`,
and composed patch SHA-256
`df52ba458ad8c6758de9084b2cc56d4dcdae9683f97405f1a4b17f88e738bfd4`.
The CPU/CUDA composites are respectively
`77d7518482dd8c9a308c5c0fbab0e2a5fc79e188745549c6cd087714edfe0dab` and
`aeb8d04eb4d6010c07baaf265372d8829fe8960b2019cf2506bc8d290951e38d`.
Complete compiler/options/base-tree/protocol and library closure identities
are in the manifests. GCC 14.2.0 and absolute-path composition differ from the
historical GCC 16.2.1 CPU pair; its accepted bytes and prior failures remain.

These Debug / `-O0 -g0` builds are for functional tests, not benchmarking.
Receipts and logs establish candidate build identities only. The archives lack
exact discovery argv/environment/live executable digest and verbose link/`ldd`
evidence. CMake reported `CUDA_CUDA_LIBRARY` unused: the recorded option and
static library hashes do **not** establish verified driver link closure.
CPU cgroup/swap samples are incomplete; CUDA `memory.peak` values are bytes
despite the uploaded kB label. Binary and library contents are host-retained,
not present in these archives. No discovery, memory-fit, physical GPU execution,
inference correctness or performance acceptance is inferred here.

Future [Step B](../cuda-prerequisite-recipe.md#step-b--selective-backing-and-gpu-readback)
must bind the actual executables, dependencies and masked physical GPU using
existing checks. It does not need a fresh build to recreate historical proof.
