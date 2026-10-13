# Scheduling-equivalence contract (PR #307)

`moe-scheduling-equivalence/1` is a **separately versioned, deliberately
narrow verdict** introduced to separate the experiment's scheduling question
from backend numerical qualification:

> Did the serial and overlapped scheduling arms execute the **same work** and
> produce **bitwise-identical outputs**, with the native replay/determinism,
> compute/status and negative-control checks in place?

It reuses the existing `--dump-reference-case` exports and `run.json`
unchanged — no new harness mode, no new export fields, no new capture:

```bash
python3 tools/moe-overlap/check_scheduling.py "$CASE" [--json OUT.json]
```

The checker is **read-only** over the case directory.

## What PASS requires (all evidenced from retained artifacts)

1. **Same inputs, routing and workload for both arms**: per repetition, the
   exported F32 inputs, top-10 expert ids (unique per token, in range) and
   routing weights are present, finite and consistent with the native
   `routed_counts_ok` accounting (`k_cpu_real + k_sec_real == 10 × T`).
2. **Ownership split consistency**: the per-device real selection counts
   re-derived from the routing bytes match the native `k_cpu_real`/`k_sec_real`
   (and, per shape, the padded width `k` accounting: exact at T=1, per-token
   maxima at T=128).
3. **Every selected expert and the shared branch retained in the outputs**:
   both arm outputs must equal, **bitwise**, the F32 combine
   `(cpu_partial + sec_partial) + shared` of the retained partials — omitted
   expert-subset or shared work cannot reproduce it.
4. **Bitwise-identical serial and overlapped final outputs** (bytes equal).
5. **Successful native replay/determinism checks**
   (`determinism_recheck.reference_bitwise` and `.serial_bitwise`).
6. **Successful native compute/status checks and complete outputs**: a
   required export missing, malformed, non-finite or inconsistent is a FAIL
   (`INVALID_OR_INCOMPLETE` when the run document itself is unusable).
7. **Negative-control evidence**: `negative_control.comparator_rejected`
   must be true (omitted shared work is rejected by the comparator).

Fields not evidenced by the run artifacts are covered by documented
construction invariants rather than invented proof: model-weight identity and
cross-arm input/routing identity are single-process invariants of the resident
harness (weights load once per process; both arms consume one `ArmContext`
per repetition), and T>1 distinct-unique zero-weight padding is guarded by the
unit-routing seam regressions. These limits are printed in every report
(`scope_limits`).

## What PASS explicitly does NOT mean

- `hardware_qualified` is **always false**; no backend correctness, kernel
  accuracy or full-model qualification is claimed.
- **Both arms can share a numerical defect**: the legacy CPU-unsplit
  comparison and the `moe-operand-reference/2` results are carried as separate
  diagnostics, their historical FAIL records are preserved verbatim, and a
  scheduling PASS never upgrades, rewrites or reclassifies them.

## Native FAIL classification

An overall native FAIL is **not** automatically an execution failure:

- `LEGACY_NUMERICAL_ONLY_FAIL` — exit 3 where the legacy cross-backend
  numerical comparison is the only failing diagnostic (every schedule,
  routing, replay, status and control gate green). Scheduling equivalence may
  still be assessed and may PASS.
- `EXECUTION_FAILURE` — anything else: routing defects, nondeterminism,
  compute/status failures, failed negative control, incomplete repetitions.
  Exit 3 is never blanket-ignored, and these cases are FAIL under this
  contract too.

## Statuses

`SCHEDULING_EQUIVALENT`, `FAIL` (evidenced but non-equivalent/incomplete),
`INVALID_OR_INCOMPLETE` (run document unusable). The verdict is named and
scoped to scheduling; it is not a certification subsystem and adds no new
approval layer, threshold or capture requirement.
