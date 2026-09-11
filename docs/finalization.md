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
living status sections, Issue #117 campaign evidence, `producer-hashes.json`,
or a bundle `MANIFEST.sha256`) — the finalizer owns those bytes, `--check`
fails on hand edits, and the second-pass fixed-point proof catches any
generator that cannot converge.

## Dependency model

Every generated artifact is a stage in an explicit DAG declared in
`scripts/finalize_repository.py` (`default_registry`). Each stage declares a
stable id, kind (`primary` / `derived` / `index` / `terminal-manifest` /
`verify`), the inputs it reads, the paths it writes, the paths a terminal
manifest covers, and its dependencies. **Declarations are derived from the
canonical constants of the producers themselves** — `sync_project_status.
TARGETS`, `issue117_proof.PRODUCERS`, the pinned authority dictionaries in
`issue117_applicability` / `issue117_accepted_subject`, and `issue137_
manifest`'s bundle constants — never hand-maintained duplicates. The engine
mechanically proves, before writing anything:

- the graph is **acyclic** — a cycle is reported with its member cycle;
- every generated path has **exactly one writer**;
- **no stage writes a path an earlier stage reads** (reader-after-writer
  invalidation);
- a terminal manifest is generated **after every covered path reaches final
  bytes** and is read by nothing (manifest-last);
- a manifest never covers its own bytes (no approved self-digest contract).

A stage that consumes the existing bytes of a path it also writes declares
the path in **both** `reads` and `writes` (a *self-input*). The status-sync
managed documents are self-inputs: their authored bytes outside the
generated sections are real dependencies of the desired bytes, and the DAG
represents them mechanically.

The current migrated chain:

```text
docs/project-status.json (authored)
  → living status sections (sync_project_status renderer; managed docs are self-inputs)
  → Issue #117 CPU campaign evidence (frozen issue117_proof producer)
      reads: integration fixture, purity-audited planner source, and every
             pinned authority input (registered as the issue117-authority stage)
  → producer-hashes.json (index; declares every producer path it hashes)
  → Issue #117 evidence MANIFEST.sha256 (terminal)
  → Issue #137 bundle verification (closed, read-only; declares its bundle inputs)
```

## Authority / integrity split

Circular pinning is eliminated by role, not by ordering tricks. Records a
reducer consumes — frozen identities, the pinned V5 authority files, the
physical-identity evidence, the accepted-subject evidence package, the
frozen producer-delta audit, and the immutable accepted records under
`evidence/arm-c/` — are registered as the `issue117-authority` primary
stage's declared reads: part of the actual registry, not prose, and never
written by any stage. Integrity indexes that pin derived outputs
(`producer-hashes.json`, retention manifests) are terminal stages written
last and read by no producer:

```text
authority facts → derived evidence → producer hashes → manifest
```

Registering a new campaign means declaring its stages in the registry —
there is no engine change and no separate per-issue finalizer.

## Callable isolation (no silent repository mutation)

Stage producers and verifiers never execute against the real working tree:

- each pass materializes a **sandbox** of byte copies of every declared
  input, and `run.root` *is* the sandbox — callables run with the sandbox as
  their working directory, so a relative-path write lands in the sandbox,
  and a `run.root`-based write hits copies, never authored bytes;
- around every callable the engine compares **full content digests of the
  sandbox tree** and a **dirty/untracked census of the real worktree**
  (tracked *and* untracked paths), so a direct write, modification, deletion
  or rename by a callable — via an absolute path, or relative into the
  sandbox — fails closed *before any declared write is applied*;
- on detection the worktree is restored from a starting byte snapshot
  (authored dirty/untracked bytes from engine-made copies; clean tracked
  bytes re-read read-only from the git object store). `git reset`,
  `checkout`, `clean`, and `stash` are never used as recovery;
- the engine's apply step is the **only** code that writes the real tree,
  and it does not run in check mode — `--check` is mechanically no-write,
  not no-write by convention.

## Transaction behavior

`--write` records the starting dirty paths (NUL-delimited porcelain, so
spaces, quoting, renames, copies, and untracked paths are unambiguous;
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
producers/verifiers (sandbox and real-tree), check-mode mechanical
read-onlyness, and fail-closed dirty-state acquisition. The expensive full
test suite runs after finalization, not between repin attempts.
