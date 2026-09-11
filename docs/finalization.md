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
manifest covers, and its dependencies. The engine mechanically proves, before
writing anything:

- the graph is **acyclic** — a cycle is reported with its member cycle;
- every generated path has **exactly one writer**;
- **no stage writes a path an earlier stage reads** (reader-after-writer
  invalidation);
- a terminal manifest is generated **after every covered path reaches final
  bytes** and is read by nothing (manifest-last);
- a manifest never covers its own bytes (no approved self-digest contract).

The current migrated chain:

```text
docs/project-status.json (authored)
  → living status sections (sync_project_status renderer)
  → Issue #117 CPU campaign evidence (frozen issue117_proof producer)
  → producer-hashes.json (index)
  → Issue #117 evidence MANIFEST.sha256 (terminal)
  → Issue #137 bundle verification (closed, read-only)
```

## Authority / integrity split

Circular pinning is eliminated by role, not by ordering tricks. Records a
reducer consumes (frozen identities, authority audits under
`evidence/arm-c/`) are primary inputs: no stage writes them. Integrity
indexes that pin derived outputs (`producer-hashes.json`, retention
manifests) are terminal stages written last and read by no producer:

```text
authority facts → derived evidence → producer hashes → manifest
```

Registering a new campaign means declaring its stages in the registry —
there is no engine change and no separate per-issue finalizer.

## Transaction behavior

`--write` records the starting dirty paths (git), writes only declared
generated paths, never stashes/resets/checks out, and reports exactly which
stage changed which file. A second, check-only pass must observe **zero byte
changes** or the command fails — a non-converging generator is a dependency
diagnostic, never a retry loop.

## CI

CI runs the same `--check` contract humans and agents run, plus the engine
negative controls in `tests/test_finalize_repository.py` (cycle rejection,
reader-after-writer, undeclared writes, manifest-self-coverage, fixed-point
failure, dirty-tree preservation). The expensive full test suite runs after
finalization, not between repin attempts.
