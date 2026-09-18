# V2-D — concurrent Radeon Pro V340L dual-die qualification (Issue #216)

Status: PRE-EXECUTION PRODUCER FREEZE ONLY — no retained V2-D physical output,
terminal observation, acceptance, or execution authorization exists.

This additive campaign consumes, but does not reinterpret, accepted V2-A, V2-B,
V2-C, and Issue #35 evidence. Its accepted base is
`main@605d0b465dc2bd015a7c832c67f4adcd7aefeb61` (PR #217).

The prospective intent remains fixed: three retained concurrent repetitions;
matched three-per-die baselines; single-A/single-B/dual H2D/D2H transport at 4,
64, and 512 MiB plus 4 KiB service profile; a 60-minute simultaneous soak with
60-second telemetry and ten-minute checkpoints; symmetric A-loss/B-survival and
B-loss/A-survival process fault arms; and conditional reset only through a
documented supported mechanism.

Physical identity architecture

`PHYSICAL-AUTHORITY.json` is derived from SHA-pinned accepted V2-B and V2-C
authority/terminal bytes. It fixes only the intended A/B CU/MR/resource
identities, device characteristics, runtime, and accepted topology identity;
historical selector/BDF observations are preserved separately as historical
qualification provenance, never as live mapping authority. Before any execution, `issue216_physical_authority.py fresh-map` must reuse the
accepted V2-A R3 discovery/binding validator to issue a fresh, raw-byte-backed
selector↔BDF↔physical-device mapping receipt. Every V2-D receipt binds that
mapping digest and the immutable authority digest. A future observation of
`Vulkan1/06:00.0` or `Vulkan2/09:00.0` is a V2-D observation, not an inherited
assumption.

Trust chain and closure

Primary raw receipts live under `evidence/`. `issue216_assemble.py` consumes a
closed immutable `INPUT-MANIFEST.json` of primary regular files only and rejects
symlinks/path aliases, drift, duplicate receipt identities, and authority
mismatch. `issue216_terminal.py` consumes that assembly; it never reads an
authored `CAMPAIGN-RECORD.json` and never accepts aggregate PASS booleans or
prose as authority. `issue216_manifest.py` produces a separate final closure
only after terminal reduction, preventing an input/output digest cycle.

Workload concurrency requires a positive intersection of retained per-die
correctness-bearing workload activity intervals, not merely wrapper process
lifetimes. Performance measurements remain descriptive: a slowdown is never a
correctness failure.

Taxonomy

A prerequisite/mapping or pre-concurrency evidence defect is
`V2D_EVIDENCE_BLOCKED`. A valid concurrent correctness violation is
`V2D_V340L_CONCURRENT_CORRECTNESS_FAIL`. After valid concurrent observation,
missing/corrupt later evidence is
`V2D_EVIDENCE_INCOMPLETE_AFTER_CONCURRENCY`; affirmative transport/soak/fault
platform failure is `V2D_V340L_PLATFORM_STRESS_FAIL`. This prospective
correction prevents missing evidence from being misreported as a physical stress
failure or erasing an observed failure as BLOCKED.

Nonclaims: no coherent 16-GiB resource, model-program qualification, mixed
AMD/NVIDIA run, SR-IOV/ROCm/HIP support, planner policy, production service/HA,
or device-reset isolation without documented support plus retained
reset/rediscovery/recovery evidence.
