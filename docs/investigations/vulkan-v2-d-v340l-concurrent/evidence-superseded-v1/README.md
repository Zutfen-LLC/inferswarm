# Evidence superseded by the V2-D correction campaign

SUPERSEDED: true. Campaign-id note: this directory's retained records
(including its TERMINAL.json STABILITY_PASS) carry the SAME campaign_id
as the corrected chain-2 evidence at ../evidence/ (opposite terminals,
distinguished only by directory). Consumers MUST NOT treat
campaign_id+terminal as unique across the two; directory location plus
this README is the supersession marker. Never delete; never cite as
terminal authority.

The evidence formerly at `evidence/` (this directory) was produced by the
DEFECTIVE producer closure (schema /2): its `closure_document()` hashed
`git show :<path>` (the Git INDEX) while Python executed WORKING-TREE
bytes, so the retained records cannot mechanically prove which bytes
executed. Per the correction campaign's terms (PR #221 correction, issue
#216), retained physical output from that producer may not stand as
terminal authority.

What it DID prove (retained for history, 762 files):
- physical campaign v1 chain: preflight, fresh A/B mapping, single-die
  baselines, concurrent repeats c01–c03 with #219 overlap lower bounds,
  shared-x1 transport matrix, 3600 s soak, both process-fault arms, and
  the read-only reset determination — all executed on inferswarm02's
  V340L dual-die Vulkan topology under producer head lineage d0a3120.
- The v1 chain COMPLETED all phases cleanly (including soak and fault
  arms). It is superseded on PROVENANCE (executed-byte identity could
  not be proven), not because any phase failed.

Supersession: corrected closure schema /3 (executed-byte identity:
worktree == index == HEAD per source) landed at producer pin d921033 /
evidence head f6af8c7; the corrected chain-2 rerun is at `../evidence/`.
Chain-2 retained an affirmative platform fault (see ../evidence/
fault-capture/ and the campaign README): amdgpu ring gfx timeout on die
B (0000:09:00.0) during the transport probe, GPU reset failed ret=-62,
reset kworker wedged (dm_suspend). The v1 chain's clean completion does
NOT erase that later fault observation — per issue #216 a valid frozen
campaign failure is retained, never relabeled, and never rerun-under-
same-authority seeking a PASS.

Do not delete this directory; it is retained history.
