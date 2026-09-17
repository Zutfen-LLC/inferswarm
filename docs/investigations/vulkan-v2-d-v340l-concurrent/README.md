# V2-D — concurrent Radeon Pro V340L dual-die qualification (Issue #216)

Status: PRE-EXECUTION FREEZE ONLY — no terminal has been observed or accepted.

This additive campaign consumes, but does not reinterpret, accepted V2-A, V2-B,
V2-C, and Issue #35 evidence. Its exact starting authority is
`origin/main@605d0b465dc2bd015a7c832c67f4adcd7aefeb61` (PR #217).

`CAMPAIGN-PLAN.json` prospectively freezes three retained concurrent repeats,
matched three-per-die baselines, direct H2D/D2H single-A/single-B/dual profiles,
a 60-minute paired soak with 60-second telemetry and ten-minute sentinels, and
symmetric process-level isolation/recovery. `scripts/issue216_terminal.py`
reduces retained observations into exactly one Issue #216 terminal.

The observed current `inferswarm02` runtime location is part of the frozen V2-D
subject rather than assumed from V2-C's old path. Its source commit remains
`8ea290247c87ced2ab245b056ffe96dbcf90d36c`; its executable SHA-256 is recorded
in the plan. Fresh V2-D sentinels and the applicability audit must establish
whether that current executable preserves the accepted V2-compatible contract
before any concurrent conclusion.

No physical evidence has been collected in this namespace. Do not create it
until all V2-D collectors/reducer bytes are committed and pushed. A missing or
ambiguous required runtime/device identity before valid concurrent output must
reduce to `V2D_EVIDENCE_BLOCKED`; a failure after valid concurrent output cannot
be relabeled blocked.

Nonclaims: no coherent 16-GiB resource, model-program qualification, mixed
AMD/NVIDIA run, SR-IOV/ROCm/HIP support, planner policy, production service/HA,
or device-reset isolation without a documented supported mechanism and retained
post-reset rediscovery/sentinel evidence.
