# Deterministic repository finalization

Issue #130 replaced manual regeneration ordering with one fail-closed command:

```bash
python3 scripts/finalize_repository.py --write   # regenerate in dependency order, prove byte no-op
python3 scripts/finalize_repository.py --check   # fail on any drift (CI mode)
python3 scripts/finalize_repository.py --list-stages
```

## The agent workflow

**Edit primary inputs → run the finalizer once → run tests.**

Primary inputs are authored files: `docs/project-status.json`, methodology
documents, producer sources, tests. Never hand-edit a generated path (the
living status sections, the Issue #130 successor-bundle indexes, or a bundle
`MANIFEST.sha256`) — the finalizer owns those bytes, `--check` fails on hand
edits, and the second-pass fixed-point proof catches any generator that
cannot converge. The closed Issue #117 parent artifacts
(`scripts/issue117_proof.py`, its `purity-audit.json`,
`producer-hashes.json`, and `MANIFEST.sha256`) are *accepted bytes*: no
workflow ever regenerates them; the successor bundle pins them instead.

## Dependency model

Every generated artifact is a stage in an explicit DAG declared in
`scripts/finalize_repository.py` (`default_registry`). Each stage declares a
stable id, kind (`primary` / `derived` / `index` / `terminal-manifest` /
`verify`), the inputs it reads, the paths it writes, the paths a terminal
manifest covers, whether its inputs are **protected** primary/frozen
authority records, and its dependencies. **Declarations are derived from the
canonical constants of the producers themselves** — `sync_project_status.
TARGETS`, `issue117_proof`'s closed-bundle bindings, and `issue137_manifest`'s
bundle constants — never hand-maintained duplicates. The engine mechanically
proves, before writing anything:

- the graph is **acyclic** — a cycle is reported with its member cycle;
- every generated path has **exactly one writer**;
- **no stage writes a path an earlier stage reads** (reader-after-writer
  invalidation);
- a terminal manifest is generated **after every covered path reaches final
  bytes** and is read by nothing (manifest-last);
- a manifest never covers its own bytes (no approved self-digest contract);
- **protected primary/frozen inputs are globally write-forbidden**: any
  stage writing such a path is rejected regardless of topological order —
  a writer scheduled before the protected reader is rejected exactly like
  one scheduled after it.

A stage that consumes the existing bytes of a path it also writes declares
the path in **both** `reads` and `writes` (a *self-input*). The status-sync
managed documents are self-inputs: their authored bytes outside the
generated sections are real dependencies of the desired bytes, and the DAG
represents them mechanically.

Declared reads are also **enforced at run time**, not just declared:

- `Run.read` rejects any path the active stage did not declare;
- each stage executes against its own **restricted projection** — a
  filesystem containing byte copies of *only* the paths that stage
  declared — so a direct filesystem read of an undeclared sibling input
  cannot observe the bytes at all (it is not merely discouraged, it is
  impossible inside the projection);
- the DAG therefore describes the real correctness dependency graph: a
  stage cannot silently consume another stage's input that happens to be
  present in a shared sandbox.

The current chain:

```text
docs/project-status.json (authored)
  → living status sections (sync_project_status renderer; managed docs are self-inputs)
  → issue117-parent-bind (verify, protected): the closed Issue #117 parent
      artifacts must equal their accepted bytes (commit:path + sha256
      bindings from the successor bundle's parent-binding record)
  → issue-130-finalization successor bundle (additive):
      producer-hashes.json (index over the Issue #130 sources)
      MANIFEST.sha256 (terminal; pins the Issue #130 sources AND the
      closed parent bindings with their accepted digests)
  → Issue #137 bundle verification (closed, read-only, protected; declares
      its bundle inputs)
```

## Closed parent and additive successor (the #137 lifecycle model)

The Issue #117 bundle is a **closed accepted parent**. Its artifacts are
verification-only inputs bound through immutable Git `commit:path` identity
plus expected SHA-256 (`evidence/issue-130-finalization/parent-binding.json`),
following the lifecycle in `docs/evidence-manifests.md`:

- no stage writes any parent artifact (they are registered `protected`);
- no Issue #130 source appears in the parent's historical `PRODUCERS`
  inventory;
- the successor bundle's manifest *pins* the parent rows with their
  accepted digests — pinning, never regenerating;
- any drift of a parent path from its accepted bytes fails `--check` and
  `--write` alike.

Current-finalization integrity (producer hashes and the retention manifest
for `scripts/finalize_repository.py` and its test suites) lives in the
additive successor bundle `evidence/issue-130-finalization/` and nowhere
else.

## Authority / integrity split

Circular pinning is eliminated by role, not by ordering tricks. Records a
reducer consumes — frozen identities, the pinned authority files, the
immutable accepted records under `evidence/arm-c/`, and the closed Issue
#117 parent artifacts — are registered as **protected** declared reads:
part of the actual registry, not prose, and never written by any stage.
Integrity indexes that pin derived outputs (the successor bundle's
`producer-hashes.json` and retention `MANIFEST.sha256`) are terminal stages
written last and read by no producer:

```text
authority facts → derived evidence → producer hashes → manifest
```

Registering a new campaign means declaring its stages in the registry —
there is no engine change and no separate per-issue finalizer.

## Callable isolation (no silent repository mutation)

Stage producers and verifiers never execute against the real working tree:

- each stage executes inside its own **restricted projection** (byte copies
  of only its declared inputs and outputs); `run.root` *is* the projection —
  callables run with it as their working directory, so a relative-path
  write lands in the projection, and a `run.root`-based write hits copies,
  never authored bytes;
- around every callable the engine compares **full content digests of the
  projection** and a **complete path-state census of the real worktree**
  (tracked and untracked, present *and deleted*: clean-tracked,
  dirty-tracked, deleted-tracked, untracked, with content digest and file
  mode), so any create, overwrite, delete, or rename by a callable — via an
  absolute path, or relative into the projection — fails closed *before any
  declared write is applied*. A callable that crashes mid-mutation is
  caught the same way: detection and restoration run in the guard's
  cleanup path;
- on detection the worktree is restored to its **exact starting state**:
  authored dirty/untracked bytes from engine-made copies (clean-tracked
  copies are kept too, so restoration never depends on git succeeding
  after a mutation), an authored *deletion* stays deleted — HEAD bytes are
  never resurrected merely because the starting baseline lacked file
  bytes — and files created during execution are removed as engine debris;
  if the post-mutation census itself fails, that failure propagates:
  preservation is never silently skipped. `git reset`, `checkout`,
  `clean`, and `stash` are never used as recovery;
- the engine's apply step is the **only** code that writes the real tree,
  and it does not run in check mode — `--check` is mechanically no-write,
  not no-write by convention.

## Symlink-safe writes

The apply step validates every real-tree destination immediately before
writing it: the destination itself must not be a symlink, no ancestor
component beneath the repository root may be a symlink (checked with
no-follow `lstat` per component — a `resolve()` check followed by a
follow-symlink write would reintroduce the escape), and the write opens the
final component with `O_NOFOLLOW` so a race between validation and write
cannot redirect the byte landing. Registry path identity is canonical: alias
spellings (`./x`, `a//b.txt`, trailing slashes) are rejected, so no spelling
can bypass single-writer, protected-path, or manifest-coverage rules.

## Transaction behavior

`--write` records the starting path-state census (NUL-delimited porcelain,
so spaces, quoting, renames, copies, and untracked paths are unambiguous;
failure to obtain trustworthy git status is a hard error, never an empty
census), runs each producer exactly once in topological order, applies only
declared writes, then audits that nothing outside the declared writes
changed, and finally re-runs the entire pipeline and fails unless the second
pass wants **zero byte changes** — a non-converging generator is a
dependency diagnostic, never a retry loop.

## CI

CI runs the same `--check` contract humans and agents run, plus the engine
negative controls in `tests/test_finalize_repository.py`: cycle rejection,
reader-after-writer, undeclared result paths, manifest-self-coverage,
fixed-point failure, dirty-tree preservation, direct-filesystem-mutation
producers/verifiers against the *actual checkout* (create, overwrite clean,
overwrite dirty, delete clean, delete dirty/untracked, rename, verifier
mutations, mid-callable crash, equivalent `--check` cases, and
starting-deletion preservation), undeclared-read enforcement (mediated and
direct-projection), protected-primary writers before and after the reader,
frozen-authority write attempts, symlink-destination and symlinked-parent
escapes, alias-spelling rejection, and fail-closed dirty-state acquisition.
The expensive full test suite runs after finalization, not between repin
attempts.
