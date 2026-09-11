# Maintaining project status

[`project-status.json`](project-status.json) is a living summary of recorded
project decisions. It is subordinate to ADRs, the Fabric Doctrine, and the
linked experiment/maintainer authority. It is not an execution permission file.

## Update in the same PR

When a change affects demonstrated capabilities, a gate result, acceptance,
execution authorization, or the integration branch:

1. Read the source evidence and maintainer decision. Record observation,
   acceptance, and execution authorization separately. Never infer acceptance
   from a PASS, or authorization from a merge or green CI.
2. Edit `docs/project-status.json` with the scoped claim and source references.
   Physical evidence and CPU fixtures must remain distinguishable. An observed
   result awaiting acceptance belongs in the frontier prerequisite, not in the
   accepted capabilities list.
3. Run `python3 scripts/finalize_repository.py --write` (it runs the status
   sync and every other maintained generator in dependency order, then proves
   a second pass changes nothing) and review the diff. The narrower
   `python3 scripts/sync_project_status.py --write` still covers the status
   sections alone; see [finalization.md](finalization.md).
4. Review explanatory prose outside generated sections in the README, roadmap,
   architecture overview, and active integration/implementation guides.
   Update affected prose in this PR or explain why it is unaffected.
5. Run `python3 scripts/finalize_repository.py --check`,
   `python3 scripts/sync_project_status.py --check`, and
   `python3 -m unittest tests.test_project_status -v`.

The existing CI workflow runs the drift check and tests on every PR update and
push to `main`. It fails when regeneration would change a managed section. It
does not push commits or run an external AI agent. The contributing coding
agent generates and commits the updates before review.

A maintainer decision made at merge time, or an issue-only authorization change,
needs a subsequent documentation PR to record the decision and regenerate the
sections. This offline check cannot detect a GitHub issue changing independently
of the repository. Include status synchronization in the acceptance/merge
handoff; do not pre-record a future acceptance to make a PR appear complete.

## Managed sections and preservation

The generator owns only marked `project-status` sections in:

- `README.md`: capability summary, current frontier, runtime branch;
- `ROADMAP.md`, `ARCHITECTURE.md`, `docs/implementation/README.md`, and
  `docs/protocols/README.md`: current frontier;
- `docs/integrations/freetoken.md`: current frontier and runtime branch.

Do not hand-edit or remove the markers. Missing, duplicate, nested, reversed,
or unexpected markers fail validation before writes begin. The same source
produces byte-identical output; there are no timestamps or network queries.

The generator never reads or writes an evidence manifest. Living project status
and immutable evidence have separate lifecycles; see
[Evidence manifest lifecycle](evidence-manifests.md). This script is maintenance
tooling, not a hash-pinned experimental producer. Future changes to it require
review and regression tests. A new generated section requires an explicit code
and test change.

## What CI can establish

CI establishes that the record has the expected shape, that recorded accepted
capabilities have observation and acceptance references, that authorization
has its own reference and an accepted prerequisite, and that generated output
matches the record. It does not establish the truth of prose or the authority
of a linked decision. Reviewers must verify those sources, scope, and semantics.
Existing physical preflight/applicability validators remain the execution gates.
