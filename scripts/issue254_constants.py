"""Frozen authority constants for Issue #254 (R8-I3C Phase 1 live producer).

Succession law (issue #254): the merged Phase-0 campaign PR #253 is closed,
so the frozen #252 dispatch law (phrase ``#252`` on PR 253, which requires
an OPEN/unmerged/non-draft PR) is structurally undispatchable. Live physical
authority for this issue is a NEW exact phrase on the producer PR created
from this branch. The producer PR number is resolved at runtime (never a
guessed constant) through the production GitHub HTTPS seam and may be pinned
via the ISSUE254_PR environment variable on the executing host.
"""
from __future__ import annotations

ISSUE = 254
PARENT_ISSUE = 252
KIND = "R8-I3C-PHASE1"
# The live dispatch phrase mandated verbatim by issue #254 Phase B.
DISPATCH_PHRASE = "R8I3C PHYSICAL DISPATCH #254"
# Producer PR branch (this branch); the live gate requires the dispatch
# comment to sit on a PR whose head branch carries this prefix.
PRODUCER_BRANCH_PREFIX = "issue-254-"
# First-executed arm (issue #254 ordering): A3 only; one dispatch authorizes
# one arm.
FIRST_ARM = "A3"

# Environment override pinning the producer PR number on the executing host
# (resolved dynamically through the GitHub search API otherwise).
PR_ENV = "ISSUE254_PR"

PRODUCER_SCHEMA = "inferswarm.issue254.producer-attestation/1"
LIVE_CAPTURE_SCHEMA = "inferswarm.issue254.dispatch-capture/3"
