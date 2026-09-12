# Evidence manifest lifecycle

Evidence manifests are immutable, bundle-local integrity indexes.  They bind
the exact retained evidence, methodology, producer, and verifier bytes used by
one reviewable evidence slice.  They are not a checksum of the current
repository checkout.

## Required dependency shape

A manifest is the terminal node of its bundle's hash graph:

- evidence and bundle documentation may bind immutable ancestor inputs;
- producers and verifiers may read immutable ancestor inputs;
- the bundle manifest hashes those files after generation is complete;
- no manifest input may read, record, or otherwise depend on that manifest's
  current bytes.

An ancestor manifest must be addressed through an immutable Git
`commit:path` identity and its expected SHA-256.  Reading the working-tree copy
of an ancestor manifest is not an authority binding: later additive evidence
may legitimately have changed that path.

## Scope

Include only files needed to reproduce, interpret, or verify the evidence
slice:

- retained authored and derived evidence;
- the accepted methodology or bundle-local method record;
- exact producer, reducer, and verifier sources;
- tests that enforce the evidence contract;
- small manifests that bind retained out-of-repository bytes.

Do not include living repository state such as `.github/workflows/ci.yml`, the
root `README.md`, `ROADMAP.md`, `ARCHITECTURE.md`, project-status outputs, or
current index pages.  Git already identifies those bytes at each commit, and
including them forces historical evidence manifests to move for unrelated
maintenance.

## Parent and successor evidence

Accepted parent bundles remain closed.  A later diagnosis, retry, remediation,
or qualification creates its own additive directory and manifest.  It names
the accepted parent commit and parent-manifest SHA when that authority is an
input; it does not add its files to the parent manifest or edit the parent's
producer inventory.

Changing a hash-pinned producer requires a successor producer and a new bundle.
Regenerating `producer-hashes.json` and a manifest after editing the original
producer does not preserve the original evidence provenance.

## Generation and CI

Generate authored and derived evidence first, then generate the bundle
manifest exactly once.  CI runs manifest verifiers in read-only mode.  A green
check establishes current byte consistency and declared scope; it does not
grant acceptance or execution authority and does not replace review of a
manifest change.

Issue #137 is the first additive Issue #117 slice using this lifecycle:

```bash
python3 scripts/issue137_manifest.py --write
python3 scripts/issue137_manifest.py --check
```

The older Issue #74, #99, #101, and #103 manifests predate this policy. Their
CI/status and legacy verifier rows remain as historical snapshots but are no
longer refreshed or treated as current-worktree integrity rows. Their
historical methodology and accepted producer identities remain unchanged.
Issue #117 is closed during the Issue #137 migration by moving the later
diagnosis into its own bundle. Future slices must not restore the legacy
review-manifest practice.

Since Issue #130, living-bundle generation order is owned by the repository
finalizer: [`scripts/finalize_repository.py`](../scripts/finalize_repository.py)
runs every declared generator once in proven topological order, writes
terminal manifests last, and proves a second pass is a byte no-op
([docs/finalization.md](finalization.md)). `--write` there replaces the
manual `--write` invocations above for every migrated bundle.

The closed Issue #117 parent is bound, never regenerated: the additive
Issue #130 successor bundle
(`evidence/issue-130-finalization/`) pins the parent artifacts through
immutable `commit:path` identity plus expected SHA-256
(`parent-binding.json`), and its manifest records the parent rows with
their accepted digests. The parent's historical `producer-hashes.json` and
`MANIFEST.sha256` remain the accepted bytes; Issue #130 finalizer sources
are hashed only by the successor bundle's own indexes, never added to the
parent's producer inventory.
