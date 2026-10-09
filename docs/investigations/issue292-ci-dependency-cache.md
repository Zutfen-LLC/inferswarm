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

The contract is encoded offline and deterministically in
`tests/test_issue131_cpu_test_env.py` (`DependencyCacheContractTests`,
`CacheContractBypassTests`, `CacheKeyAndMissContractTests`); section 7
records the fail-closed correction of the first version. In summary:

- the closure of the real authority is exactly those two files. It follows
  `-r`/`--requirement` and `-c`/`--constraint` includes in every spelling
  (nested, recursive, relative to the including file as in pip, cycle-safe) and
  fails closed on any directive or line it cannot account for (section 9);
- `setup-python` caching must be `pip` with every closure file listed as a
  literal repo-relative path (default path, root-only list, unlisted transitive
  file, glob, absolute or dynamic entries are each rejected);
- `actions/cache` may store only an allowlisted pip download-cache directory,
  keyed on REAL evaluated expressions (`runner.os`, `runner.arch`,
  `steps.<id>.outputs.python-version` from an unconditional setup-python step
  that runs earlier, and a literal `hashFiles` over the whole closure), with no
  `restore-keys`, cross-OS archive or `fail-on-cache-miss`;
- every environment-bearing job must run the canonical bootstrap, then the
  canonical doctor, unconditionally, before using the environment;
- the real `ci.yml` and `final-cpu-validation.yml` satisfy the policy today
  (neither caches), with the 17 + 1 environment-bearing jobs pinned so the
  detector cannot go vacuous.

RED/GREEN control, run against the real Final workflow text in memory: adding
`cache: pip` with the default path yields a finding naming both
`requirements-test.txt` and the nested frozen file (RED); adding an explicit
`cache-dependency-path` listing the closure yields no findings (GREEN).

## 5. Trust model if a cache is ever enabled

A restored cache is an untrusted hint and must not become execution authority.
The canonical bootstrap still runs `pip install -r requirements-test.txt`,
re-screens the installed environment for model-runtime packages, and checks
tracked-file immutability; the doctor still enforces interpreter, version and
CPU-only rules; no cache path may hold the venv, the checkout or any validation
output; and the contract tests require bootstrap and doctor to run
unconditionally on every cache state, so a hit can never skip them. A cache
miss is an ordinary cold run (`fail-on-cache-miss` is rejected), and the
bootstrap never reads cache environment or adds cache flags (tested).

**Limitation (corrects the first version of this section).** pip does not
re-verify the integrity of a wheel it finds in its cache, and the frozen
requirements carry no `--hash` pins. The doctor checks installed versions, CPU-only
rules and the tracked tree, not wheel contents. A poisoned cache entry that
reached a restore would therefore be installed. The only defences are GitHub's
cache scoping (restores come from the current ref or the default branch, and
fork pull requests are isolated), the absence of any write privilege or secret
in these workflows, and keeping the cache out of any workflow that is not
already running the same code. Neither the scoping nor a poisoned-entry
installation was exercised here. Enabling caching for authoritative validation
should wait for that to be settled (for example hash-pinned requirements, which
would change the frozen authority and is out of scope for this issue).

## 6. Decision and revisit conditions

Defer caching for both workflows. Revisit only if one of these is measured on
hosted runs: bootstrap grows materially (e.g. a larger frozen dependency set or
a slower mirror) or its download/resolve share exceeds a few percent of a job's
critical path; or the Final validation moves to `main`-scoped or multi-run use
where a warm entry exists. The contract tests above are the pre-approved
integration gate.

## 7. Correction round 1 (PR #294 review)

The first version of the contract failed open. Reviewed head
`fac2cfe54d925111e672a86d1fb95e2b0b740af3` on main
`57adca1ffac11fe70a914d5862910100690f9947` (no main drift at the start of the
round). The defects, each demonstrated RED before the fix
(`ffe8676`, 64 accepted bypasses across 7 tests):

| Bypass accepted by the first validator | Cause |
| --- | --- |
| absolute checkout-root and `${{ github.workspace }}` cache paths | path screened by substring markers |
| `**`, `*`, `.v*nv`, `te*ts`, `..` traversal, `!` negation | globs/dynamic paths evade a denylist |
| `if/then`, `&&`/`\|\|`, `\|\| true`, `set +e`, continuation, background, step `if`/`continue-on-error`/`shell`/`working-directory`/`env` | "present" meant the command text appeared in the script |
| `echo`, `printf`, comment, heredoc, `:` embeddings | text match counted inert commands |
| environment-bearing job with no, partial or misordered bootstrap/doctor | checked only when the job also used a cache |

Corrections (all in the test module; no workflow, script or authority change):
cache paths are an explicit allowlist (`~/.cache/pip`,
`/home/runner/.cache/pip`); bootstrap/doctor count only as a plain `run` step
with no escape-hatch key whose every command line is exactly a canonical line
(so nothing can make it conditional, ignored, inert or reordered); every
environment-bearing job is validated whether or not it caches; the `actions/cache`
key is validated for OS, architecture, Python version and the literal closure
hash; `restore-keys`, cross-OS archives, `fail-on-cache-miss`, other
cache-enabling actions, pip source-redirecting environment and
`GITHUB_ENV`/`defaults.run` rewrites are rejected. Acceptance fixtures (the
real no-cache workflows, a non-environment job, valid narrow `setup-python` and
`actions/cache` shapes) pass before and after.

Key invalidation is covered by `simulate_cache_key`, which evaluates a
validated key offline and asserts it changes with OS, architecture, Python
version, the root requirements file and the nested frozen file. Cache-miss
behaviour is covered by asserting the bootstrap's pip command is identical with
and without a (poisoned) `PIP_CACHE_DIR`.

**Deferred until caching is actually enabled** (not testable offline): the
exact key `actions/setup-python` computes (documented OS/architecture/Python/
hash composition); a hosted cold-versus-warm elapsed-time measurement; restore
behaviour for fork pull requests and cross-branch scoping; poisoned-wheel
behaviour (see the limitation in section 5).

## 8. Correction round 2 (maintainer re-review of `cd6fd13`)

Re-review verdict: NO-GO on two remaining fail-open defects (reviewed head
`cd6fd13af45eb0850184b2b932e28af91e0c27ac`, main unchanged at
`57adca1ffac11fe70a914d5862910100690f9947`). Both reproduced before any change;
RED controls are commit `44f095f` (29 failing subtests across 6 of 8 new
tests).

| Defect | Why the round-1 validator accepted it | Correction |
| --- | --- | --- |
| **B1** static look-alike cache key | `runner.os`, `hashFiles(...)` etc. were matched as arbitrary substrings, so static text spelling them passed although nothing is evaluated and the key never changes | the key is parsed into literal text and REAL `${{ }}` expressions; only four whole-expression shapes are understood (`runner.os`, `runner.arch`, `steps.<id>.outputs.python-version`, `hashFiles('<literal>', ...)`); words in static text, string literals, `format()`, operator-combined or unbalanced expressions confer nothing |
| **B1** reference ordering | the python-version reference only needed a setup-python step anywhere in the job | the referenced step must be an `actions/setup-python` step that runs BEFORE the cache step |
| **B2** arbitrary `GITHUB_PATH` write | only `GITHUB_ENV` was screened | every `run` line mentioning `GITHUB_PATH` (or legacy `::add-path`/`::set-env`) is rejected unless it is exactly the reviewed canonical `.venv/bin` export inside a provably canonical bootstrap step |

Found in my own adversarial pass of the new parser (each RED first, then
fixed): a `'!requirements-test.txt'` negation in `hashFiles` or
`cache-dependency-path` could cancel a closure file that is listed literally,
and a conditional or soft-failing setup-python step yields an empty
python-version output (a static key). Both are now rejected.

The contract is now behavioural as well as structural: for every crafted key
the validator ACCEPTS, a strict offline evaluator (`simulate_cache_key`, which
raises on any expression it cannot evaluate, and treats a missing `hashFiles`
file as an empty hash, like Actions) must produce a different key for a changed
OS, architecture, Python version, root requirements and nested requirements.
Round-1 fixture note: one ordering fixture in `44f095f` also put a valid
setup-python step before the cache step, masking the case it meant to test; it
is corrected in the fix commit, and the prior validator was re-run on the
corrected arrangement and accepts it (RED).

Remaining limitation: the checks read the workflow statically. Obfuscated shell
(for example assembling the name `GITHUB_PATH` from pieces, or `eval`) is not
statically decidable and is outside this contract; maintainer review of any
future cache-enabling change remains the backstop. Likewise a job that uses
the environment only through a `uses:` composite action is not recognised as
environment-bearing.

## 9. Correction round 3 (maintainer re-review of `69b3013`)

Re-review verdict: NO-GO on two further dependency-authority gaps (reviewed head
`69b301322de1cf2a3900ce21bebb1384d496c83c`, main unchanged at
`57adca1ffac11fe70a914d5862910100690f9947`, hosted CI 37852776613 green).
Both reproduced before any change. RED controls are commit `1125034`
(278 failing subtests across 10 of 15 new tests: 274 assertion failures and 4
errors, where the old code only failed closed *accidentally* through
`FileNotFoundError` on `https://…`, `file:///…`, `~/…` and a bare `\` instead of
a deliberate rejection).

| Defect | Why the round-2 validator accepted it | Correction |
| --- | --- | --- |
| **B1** pip resolver/config environment | the forbidden-environment list was a short denylist that omitted `PIP_CONFIG_FILE`, `PIP_CONSTRAINT`, `PIP_REQUIREMENT` and every other `PIP_<OPTION>`; a config file can also change cache settings while the requirements-derived key stays the same | an allowlist: every `PIP_*` and `UV_*` variable (uv is the bootstrap's documented fallback installer) is rejected case-insensitively at workflow, job and step level, with the single reviewed exception `PIP_DISABLE_PIP_VERSION_CHECK`; the explicit denylist now also covers proxy, CA-bundle, config-location, `HOME`, `LD_*` and `PYTHON*` inputs |
| **B2** `-c`/`--constraint` omitted from the closure | `requirement_closure` followed only `-r file` through a regex, so constraints (resolver authority), no-space forms (`-rfile`, `-cfile`), `--requirement=file`, backslash continuations and every other directive were silently dropped, yielding an incomplete closure and cache key | pip-faithful parsing (line joining, comment stripping) that follows all `-r`/`-c` spellings recursively and raises `RequirementsAuthorityError` for any other option line (`--find-links`, `--index-url`, `-e`, hashes, `--no-index`, ...), direct URL/path/`@` requirements, `${VAR}` expansion, and includes that are non-local, outside the repository or missing |

Behavioural controls: a constraint change must change an accepted key, and a key
that omits a constraint file must be rejected (the closure now includes it).
Mutation confirmation: injecting `PIP_CONFIG_FILE` or `PIP_CONSTRAINT` into the
parsed real `ci.yml` and `final-cpu-validation.yml` at workflow, job and step
level is rejected, while the unmodified workflows stay GREEN; the real closure is
unchanged (the two files).

Found in my own adversarial pass (RED first, 12 failing subtests, then fixed): a
whole-map `env: ${{ fromJSON(...) }}` is a string, not a mapping, and its keys
cannot be known statically (now rejected), and newer `actions/setup-python`
releases accept pip inputs such as `pip-install` and `pip-version` (the action's
inputs are now an allowlist: `python-version`, `cache`,
`cache-dependency-path`).

Remaining limitations: pip configuration can also come from files outside the
workflow (system, user or in-venv `pip.conf`), which a static workflow check
cannot see, and the doctor does not inspect it; this joins the obfuscated-shell
limitation in section 8 as a reason to keep caching out of authoritative
validation until it is explicitly authorised.

## 10. Correction round 4 (maintainer re-review of `cceb11a`)

Re-review verdict: NO-GO on two fail-open policy defects (reviewed head
`cceb11ab3fd4cde99b945258cb9b0a66653a8df4`, main
`a8c690e1e7aca37769dcc39c1dc8f6d6bab00769`). Both reproduced before any change.
RED controls are commit `c912527` (1244 failing subtests across 6 new tests, all
assertion failures; the round-3 validator rejected none of the 67 new
environment names at any scope or value). GREEN is commit `12fced0`.

| Defect | Why the round-3 validator accepted it | Correction |
| --- | --- | --- |
| **B1** interpreter / dynamic-loader environment | outside the `PIP_*`/`UV_*` families the list was still a denylist of names: `LD_PRELOAD`/`LD_LIBRARY_PATH` but not `LD_AUDIT` (loads code into every process), `PYTHONPATH`-style names but not `PYTHONOPTIMIZE` (strips `assert`, silently weakening the suite) | reviewed **prefix families**, matched on the upper-cased name: `PIP_`, `UV_`, `PYTHON`, `_PYTHON`, `LD_`, `DYLD_`, `GLIBC_`, `MALLOC_`, `VIRTUALENV_`, `SETUPTOOLS_`, `DISTUTILS_`, `PYTEST_`, `COVERAGE_`, `OPENSSL_`, `BASH_FUNC_`; plus explicit shell (`SHELLOPTS`, `BASHOPTS`, `IFS`, `CDPATH`), locale/iconv loading (`GCONV_PATH`, `LOCPATH`, `NLSPATH`) and name-resolution (`HOSTALIASES`, `RES_OPTIONS`, `LOCALDOMAIN`) names alongside the existing proxy, CA-bundle, config-location and `PATH`/`HOME` names; any env **name** that is not a plain identifier (a `${{ }}` key, padding, `%%`) is rejected outright. Values are never consulted, so literal and expression values are rejected alike. The single reviewed exception is still `PIP_DISABLE_PIP_VERSION_CHECK` (set by `ci.yml`); names that merely *contain* a family (`MY_PYTHON_LABEL`) stay accepted because the rules are anchored prefixes |
| **B2** job-level failure tolerance | `continue-on-error` was checked only on steps (where it removes the bootstrap/doctor role); a job-level `continue-on-error: true` or `${{ matrix.experimental }}` on an environment-bearing job reports a failed bootstrap, doctor or suite as success to `needs` and the CI gate | `environment_job_findings` rejects a job-level `continue-on-error` on every environment-bearing job unless it is a literal false; any expression is treated as possibly true. Non-environment jobs may still tolerate failure, and the planner's job-level `if:` selection is untouched |

Preservation: the real workflows stay GREEN; injecting `LD_AUDIT`,
`PYTHONOPTIMIZE` or `ld_audit` into them at workflow, job or step level is
rejected; setting job-level `continue-on-error` on every real job flags exactly
the 17 + 1 environment-bearing jobs and no others. A source-mutation pass (19
mutants, each reverting one rule) is killed in full, including mutants of the
earlier rounds' cache-path allowlist, step-level bootstrap/doctor structure,
key-expression and closure-hash checks, `-c` closure following, fail-closed
directives, `GITHUB_PATH` and `PIP_*` rules. One mutant initially survived (the
round-3 non-mapping `env` rule, masked by the new name check), so that rule now
has a direct test.

## Preserved, not changed

`scripts/bootstrap_test_env.py`, `scripts/check_test_env.py`,
`requirements-test.txt`, the frozen tokenizer requirements, both workflows, the
CI planner/registry, and all retained evidence are untouched. Issue #291
(run deduplication) is a separate optimization and was not conflated here.
