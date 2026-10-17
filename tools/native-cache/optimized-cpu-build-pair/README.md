# Reviewed optimized CPU05 identity

`optimized-cpu05-cuda03` selects the complete CPU client manifest in this
directory and the unchanged Step A CUDA worker manifest. This is additive
static identity admission after review of the actual PR #332 candidate. It is
not physical qualification, numerical correctness, performance acceptance, or
authorization for model/hardware execution. Historical selectors and manifests
retain their exact identities.

| Role | Manifest SHA-256 | Executable SHA-256 |
| --- | --- | --- |
| CPU client on 05 | `f2c97e88b28fe59f11a0f6940269a94f37b3d219dfce65a60227cc8f67c5e9da` | `8fbea89ca86a22572fe9b83807a7943a75dccaaaa0ec283c4fc24508c90b3156` |
| Unchanged CUDA worker on 03 | `e08ea250e56823072a5582a28e77edfe34774dafe0c3d8a0568f24274152f47d` | `46345f6c4df4f229aa11e76514c6c6eff9c9a148257f9232a505c8173d2ebf73` |

## Evidence and comparison

The CPU manifest is copied byte-for-byte from
`optimized-cpu-candidate/llama-server.build-manifest.json` in the supplied
`is332-cpu-review.tar.gz`. The private controller retains the bundle; its
SHA-256 is `92176e82b287a253764466d5e15324ad12cd4a8fdb83a54035ffd54825007aa8`.
Review verified that digest and all 40 indexed files. Included scripts were
inspected, not executed. The full receipt, effective flags, cache, compilation
databases, build/check logs, historical comparisons and binary readback report
remain in the bundle. No binaries or private host paths are published here.

The bundled recipe and build-recipe documentation match main
`df226a10ef78a7bed06e9d3f0381afd670b049d3`. Native source remains
`b29c606e28a01b1bc8c1351026a0fa6e616bf6c4`, archive SHA-256
`03fb04316eb32a7b7347004a79a8dd60531c02f5a064d853fed3b53828951723`,
and patch SHA-256
`df52ba458ad8c6758de9084b2cc56d4dcdae9683f97405f1a4b17f88e738bfd4`.
The candidate's recorded path-dependent composite is
`629886f199f2455f4be1b939ce0e7ccd8e6a0d99b263c3176013283ef3bbc80d`;
it is not substituted for the historical composite.

Independent inspection reproduced the recipe's effective-flag result for all
229 exported compilation commands: Debug, `-O3 -g0`, assertions retained.
Like-for-like historical/candidate Ninja compilation databases also contain
229 compile commands. After only owned-root normalization and historical
`-O0` to `-O3` substitution, every command agrees. All 158 compared
backend/toolchain cache entries agree. Exported CMake commands omit Ninja's
dependency-tracking switches; that difference is not a compiler-option delta.
GCC remains `c++ (Debian 14.2.0-19) 14.2.0`; static linkage, RPC and backend
settings are unchanged. All 13 static-library names match the historical CPU
closure; their actual candidate hashes remain in the manifest and receipt.
The receipt's embedded client manifest matches the separate manifest exactly.

The supplied reports record a 330.509-second successful build, executable and
library hash readback, both no-model CLI commands exiting zero, 44 focused
tests passing, and no remaining owned processes. `--list-devices` printed
`(none)`: the retained pinned implementation excludes CPU devices from its
printed list; this does not demonstrate GPU discovery. The archive build's
unknown Git version string is not its source identity. This local admission
review did not rerun binaries, rebuild native code, or access a model.

## Limits and follow-through

Binaries and static libraries remain on the build host. Their readback is
reported by the retained build verification; this review checked the bound
reports and manifest, not a fresh host-binary readback. The bundle does not
carry the full transformed source tree, so its recorded composite was checked
for consistency rather than recomputed. Existing runtime checks must still
bind actual executable/library bytes and source identities before use.

Aggregate build-tree RSS is unavailable. The reported child max-RSS is a
largest-child value; sampled PGID totals omit Ninja job-specific process
groups. This limits resource conclusions and does not require rebuilding the
candidate. No fit, speedup, inference correctness or GPU execution claim follows.
The supplied tests used existing Python 3.13.5; they do not substitute for the
repository's required publication gates.

The existing [controlled follow-through](../optimized-cpu-recipe.md#b-controlled-follow-through-describe-only-separately-authorized)
retains its separate authorization, bounded session, source/cache verification,
unknown-allocation refusals, cleanup and unaccepted-output boundaries. Only the
CPU identity changes; the CUDA worker is not rebuilt or replaced. This change
does not alter project-status acceptance or execution-authorization records.
