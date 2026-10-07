# Issue280 advisory correctness/portability review

## Verdict

**ADVISORY NO-GO pending two scoped fixes:** the real D1/D2/D3 replay and all local tests are green, but the permanent source probe is not portable to an ordinary hosted environment, and malformed DEFLATE bytes escape the structured prelaunch failure contract. These findings do not authorize changes, physical work, acceptance, or maintainer adjudication.

Reviewed `/home/zutfen/code/is280-compat`, branch `fix/issue280-real-stream-compat`, base HEAD `832a9f4adcba2bebfa66f0ed5f1e004cba7fb16d`. Branch and HEAD matched at both initial and final reads. Scope: working implementation diff, named compatibility/source scripts and tests, observer/runner admission integration, compatibility README, retained source findings and archived pinned source. No repository files edited; no commits, branch changes, fetch, gh, network, SSH, device/GPU/model/physical actions. Only CPU reads/tests, scratch reports and throwaway CPU probe files. Parent-owned additive manifest/test/docs changes were not treated as defects.

## Findings

### 1. P1 — Source probe requires an agent-specific directory when TMPDIR is unset

**Location:** `scripts/issue280_source_compat.py:126-127`.

`cpu_probe()` passes `dir=os.environ.get("TMPDIR", str(Path.home() / ".hermes/cache/scratch"))` to `TemporaryDirectory`. With no TMPDIR, a home without that Hermes directory cannot run even the otherwise valid archived producer probe. This is a production gate false negative, not an absent local llama.cpp checkout: `verify_overlay()` succeeds, then temporary-directory creation fails. The permanent gate consequently reports `compatibility successor CPU source probe failure`, and successful synthetic/request fixtures cannot overcome it. The workflow contains no TMPDIR/Hermes-scratch provisioning.

**Reproduction (exit 1; two assertion failures):**

```sh
cd /home/zutfen/code/is280-compat
env -u TMPDIR \
  HOME=/home/zutfen/.hermes/cache/scratch/is280-nonexistent-hosted-home \
  PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest \
  tests.test_issue280_source_compat.SuccessorSourceTests.test_inserted_cpu_probe_executes_complete_ids \
  tests.test_issue280_source_compat.PermanentGateTests.test_bound_fixture_and_source_probe_pass -v
```

Both fail with `[Errno 2] No such file or directory: '<HOME>/.hermes/cache/scratch/i280-d1-probe-...'`. Full output: `/home/zutfen/.hermes/cache/scratch/is280-advisory-hosted-portability.txt`.

**Smallest scoped fix:** let `TemporaryDirectory(prefix="i280-d1-probe-")` choose the standard portable temporary root; it already honors valid TMPDIR, so this host still uses its configured scratch root. Remove the hardcoded fallback/explicit dir rather than creating a Hermes tree in every hosted home. Add a no-TMPDIR, non-Hermes-HOME positive regression, restoring environment afterwards. Re-run the two tests and full Issue280 suite.

### 2. P2 — Corrupt gzip payload bypasses structured false and runner STOP reporting

**Location:** `scripts/issue280_compatibility.py:50-51,128-129`; downstream `scripts/issue280_runner.py:142`.

The gate catches gzip header/trailer failures through OSError/EOFError, but `gzip.decompress()` also raises `zlib.error` for malformed compressed data. That exception is not caught. `check_compatibility()` therefore raises instead of returning its declared false verdict; `run_campaign()` propagates it instead of returning STOP with all four requests not_attempted. This is a failure-reporting/availability defect, **not an execution bypass**: the reproduction observes zero executor calls.

**Reproduction:** place bytes `1f8b0800000000000003070000000000000000` at a scratch bundle's `observer-R1-cold.i280.raw.gz`, then call `check_compatibility(bundle)`. It raises `zlib.error: Error -3 while decompressing data: invalid block type` before any other bundle lookup. Feed that same real check through the runner's prelaunch gate; it raises the same exception with zero launches instead of returning a summary. No repository artifacts were corrupted.

Executable reproduction and exact results:

```sh
PYTHONDONTWRITEBYTECODE=1 TMPDIR=/home/zutfen/.hermes/cache/scratch \
  python3 -B /home/zutfen/.hermes/cache/scratch/is280-advisory-probes.py
```

Results retained at `/home/zutfen/.hermes/cache/scratch/is280-advisory-probes.json`, including reviewed file SHA-256 identities.

**Smallest scoped fix:** import zlib and catch `zlib.error` at the compressed-custody read boundary, translating it into a specific ValueError already handled by the gate; alternatively add that specific exception to the gate's catch set. Keep the runner unchanged if the gate reliably returns false. Add malformed-DEFLATE regressions for structured gate failure and STOP/not_attempted/zero-executor behavior. Consider both raw and server archives, which share this decompression seam.

## Verified as correct

- **All 174 current Issue280 tests PASS**, no skips/failures/errors, in 194.208s. Counts by module: admission 31; observer 57; real_compat 30; retention_fix 5; runner 10; source 18; source_compat 9; task_check 14. The extra test beyond the parent's earlier 173 is the disclosed parent-owned manifest emitter test, which passes. Log: `/home/zutfen/.hermes/cache/scratch/is280-advisory-tests.txt`.
- The unchanged complete retained raw authenticates and replays GREEN: baseline A, 40 graphs, 457 completed compute commands, 1923946496 GPU weight bytes and 150994944 KV bytes. The preserved accepted observer reproduces exact RED: `graph sequence/request mismatch`.
- All **27 retained adversarial mutations** reject with their specifically asserted target reasons, not merely global digest failures. Independent rerun output: `/home/zutfen/.hermes/cache/scratch/is280-advisory-mutations.json`.
- **D1:** legacy uniqueness is confined to the exact full original request/batch/graph semantic projection plus re-read raw/server/terminal/source custody. Direct fields, when supplied, are validated independently and conflicting multi-ID/wrong-ID/layout/request evidence rejects. The one-slot, non-unified-KV limit remains explicitly source-inferred, not a nonexistent runtime n_seq_max log claim.
- **D2:** literal CPU/CPU_Mapped/Vulkan_Host vocabulary; unknown/lookalike/unassigned owners reject; host bytes remain denominator-only and are not die numerator credit. Explicit inventory/backend conflicts are checked against graph bindings.
- **D3:** tied fallback is model-policy inference, not a synthetic output rename; exact 255252480-byte unique GPU allocation on the required die, separate matching host backing, and per-graph completed result_output/MUL_MAT with matching actual operand are required. output_norm, missing/wrong-size operand, ambiguous GPU copies, wrong owner, missing backing and missing completion reject. Distinct output inventory disables tied fallback. The documented ggml/Vulkan pointer-identity limitation is not hidden or falsely asserted.
- Prelaunch compatibility rejection prevents executor calls; existing block/BDF/KV/completion/request/copy/occurrence/staging/STOP/budget/RSS regression suites pass. Exact historical retained bytes—not a synthetic fixture—are mandatory input to the permanent gate.
- Old source transform and old instrumentation have no Git diff. Successor preservation tests confirm the other five transformed files are unchanged; new insertion is only D1 observer metadata. The complete affected successor `llama-context.cpp` passes the README's CPU-only `c++ -std=c++17 -fsyntax-only` command, exit 0. This is not a Vulkan integration build or physical proof.

## Files produced / remaining scope

Created only scratch files: this report, `is280-advisory-tests.txt`, `is280-advisory-hosted-portability.txt`, `is280-advisory-mutations.json`, `is280-advisory-probes.py`, and `is280-advisory-probes.json`. No repository changes. Parent retains CI/status/manifests/finalization ownership. No actual hosted run, Vulkan build, runtime binary/model attestation, or physical measurements were performed or requested. No further bounded D1/D2/D3 admission defect was established in the inspected paths and executed controls.
