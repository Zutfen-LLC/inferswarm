# Issue #292 — dependency caching for hosted CPU validation

**Outcome: no dependency cache is enabled; ordinary CI and Final CPU
Validation are unchanged.** The measured benefit is below the threshold the
issue sets ("apply only where measured benefit exists"), and the cache would
rarely hit for the workflow it was meant to speed up. What ships is the
measurement, the key-coverage audit, and offline contract tests that make any
future enablement prove it is only an untrusted performance hint.

Evidence labels follow [BENCHMARKING.md](../../BENCHMARKING.md). No hosted
workflow was dispatched for this issue; hosted figures are read from
already-retained runs.

## 1. Baseline (step 1)

### Final CPU Validation, run 37775047769 (exact head on `main`, success)

MEASURED from the retained step timestamps (job 18 m 29 s = 1109 s):

| Stage | Seconds | Share |
| --- | ---: | ---: |
| Set up job + sha checks | 1 | 0.1% |
| Checkout (`fetch-depth: 0`) | 10 | 0.9% |
| Set up Python | 1 | 0.1% |
| **Bootstrap** (`bootstrap_test_env.py`) | **22** | **2.0%** |
| Doctor | 0 | 0.0% |
| Canonical full CPU suite | 1009 | 91.0% |
| Finalizer check | 62 | 5.6% |
| Status check, receipt, upload, summary | 4 | 0.4% |

The critical path is the suite; setup is ~2% of the job.

### Ordinary CI, run 37837730876 (PR #290 head, 15 environment-bearing jobs)

MEASURED: every group job spends 17–26 s in Bootstrap and ~10–18 s in
Checkout, concurrently. The longest job (`r8i-qwen-qualification shard 1`)
runs 462 s of which Bootstrap is 24 s (5.2%). Group wall time is dominated by
the test step, not setup.

### Where bootstrap time goes (job 113519111028, CI `issue-74-79`)

MEASURED from pip's timestamped output in the retained log:

| Phase | Seconds |
| --- | ---: |
| venv creation + pip start-up | ~5 |
| resolve / fetch metadata | ~2.6 |
| download wheels (~40 MB at ~250 MB/s) | ~0.4 |
| **install (unpack, byte-compile)** | **~12.9** |
| post-install screen + tracked-file digest | ~1.6 |

Only the ~3 s resolve/download phase is addressable by a pip wheel/HTTP cache.
The 12.9 s install phase is not: pip must still unpack and byte-compile every
wheel into the fresh `.venv`, and caching `.venv` itself is prohibited by the
issue.

## 2. Estimated benefit (step 2, bounded)

CALCULATED from the table above: the most a perfect warm cache can save is
~3 s per bootstrap, i.e. ~0.3% of the Final CPU Validation critical path
(3/1109) and ~0.6–0.7% of the longest ordinary CI job (3/462), **before**
paying for restoring a ~49 MB archive and saving it in the post step (the
`setup-python` post step also runs on cache misses).

MEASURED local A/B (non-hosted; one machine, cold = empty `PIP_CACHE_DIR`,
warm = populated, `.venv` deleted before each run, canonical Python 3.12.3,
bootstrap wall time):

| Run | Seconds |
| --- | ---: |
| cold 1 / cold 2 | 32.8 / 33.4 |
| warm 1 / 2 / 3 | 29.6 / 29.9 / 29.3 |

Mean saving 3.5 s (10.6% of bootstrap) with a local-fast download path. It is
consistent with the ~3 s hosted bound and is not hosted evidence. The populated
pip cache was 49 MB.

## 3. Why Final CPU Validation would rarely be warm

CALCULATED from GitHub's documented cache scoping (a run can restore caches
created on its own ref or on the default branch, and saves are scoped to the
saving ref; not re-verified in this session). Final CPU Validation is
`workflow_dispatch` only and runs **once per reviewed PR head, on the PR
branch**. Its cache would be saved under that branch's scope, which no other
branch can read, so a cold branch only warms from entries the default branch
holds. Those would exist only if a `main` run (push CI, or a Final run on
`main`) saved the same key. Ordinary CI group jobs all start concurrently, so
they cannot warm each other within one run either (the issue states this).

## 4. Key-coverage audit (steps 2 and 5)

The canonical dependency closure is `requirements-test.txt` plus its `-r` file
`docs/implementation/r6-successor-dense-full-integration-117/evidence/arm-c-retry/frozen-tokenizer/requirements.txt`.
By `actions/setup-python`'s documented behaviour (not re-verified in this
session), `cache: pip` hashes the files matched by `cache-dependency-path`,
defaulting to `**/requirements.txt`, and its key also carries the runner OS,
architecture and exact Python version. In this repository that default would
match only the nested frozen file and **miss `requirements-test.txt`**, so a
change to the root ranges (e.g. `numpy>=1.26,<3`) would reuse a stale key. Any
future enablement must therefore list every closure file literally in
`cache-dependency-path`.

`tests/test_issue131_cpu_test_env.py::DependencyCacheContractTests` encodes
this offline and deterministically:

- the closure of the real authority is exactly those two files (pip semantics,
  nested `-r` relative to the including file, cycle-safe);
- a workflow that enables pip caching must list the whole closure literally; the
  default path, a root-only list, and an unlisted transitive file are each
  rejected by a negative control;
- `actions/cache` may not store `.venv`, `tests`, `/tmp`, receipts, suite
  results, or the repository root;
- bootstrap and doctor steps stay present and unconditional in every
  environment-bearing job, so a cache hit can never skip them;
- the real `ci.yml` and `final-cpu-validation.yml` satisfy the policy today
  (vacuously: neither caches).

RED/GREEN control, run against the real Final workflow text in memory: adding
`cache: pip` with the default path yields a finding naming both
`requirements-test.txt` and the nested frozen file (RED); adding an explicit
`cache-dependency-path` listing the closure yields no findings (GREEN).

## 5. Trust model if a cache is ever enabled

A restored cache is an untrusted hint. The canonical bootstrap still runs
`pip install -r requirements-test.txt` (pip verifies the pinned frozen
packages and re-resolves the ranged ones), re-screens the installed
environment for model-runtime packages, and checks tracked-file immutability;
the doctor still enforces interpreter/version/CPU-only rules; no cache path may
hold the venv or any validation output. A poisoned or mismatched cache can at
worst cause a download/resolve failure or a different wheel for the ranged
test dependencies — which the doctor and the suite then judge exactly as they
judge a cold install. It cannot skip a test, alter the suite population, or
produce a receipt. The workflows use `contents: read` and add no secrets; the
policy adds no write privilege. Final CPU Validation is dispatch-only (never a
fork PR); for ordinary fork PRs, GitHub's own cache scoping applies (not
re-verified here) and the policy above is the same.

## 6. Decision and revisit conditions

Defer caching for both workflows. Revisit only if one of these is measured on
hosted runs: bootstrap grows materially (e.g. a larger frozen dependency set or
a slower mirror) or its download/resolve share exceeds a few percent of a job's
critical path; or the Final validation moves to `main`-scoped or multi-run use
where a warm entry exists. The contract tests above are the pre-approved
integration gate.

## Preserved, not changed

`scripts/bootstrap_test_env.py`, `scripts/check_test_env.py`,
`requirements-test.txt`, the frozen tokenizer requirements, both workflows, the
CI planner/registry, and all retained evidence are untouched. Issue #291
(run deduplication) is a separate optimization and was not conflated here.
