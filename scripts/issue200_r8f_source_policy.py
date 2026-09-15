#!/usr/bin/env python3
"""InferSwarm issue #200 (R8-F) internal Source-policy seam (CPU-only).

Extends the *accepted* issue #99/#101 plan-driven artifact seam with an
internal, unfrozen policy input over Source *selection* for an already
frozen requirement set. This module never modifies
``scripts/issue99_artifact_core.py`` or ``scripts/issue101_orchestration.py``
(both are hash-pinned producers of prior accepted evidence, see
``docs/implementation/plan-driven-artifact-acquisition-99/evidence/MANIFEST.sha256``
and ``docs/implementation/plan-driven-artifact-orchestration-101/evidence/MANIFEST.sha256``);
it extends the accepted ``Coordinator`` purely by subclassing and composing
its public surface, so every existing #99/#101 test and retained evidence
byte remains untouched.

Scope discipline (ADR 0009 / model-artifact-distribution.md):

- Source *policy* changes only which authorized Source satisfies an already
  frozen participant requirement. It never adds, removes, or reinterprets a
  Logical State Unit, never changes ``derive_participant_requirements``
  output, and never makes whole-model local possession a feasibility
  prerequisite: ``REQUIRE_LOCAL_VERIFIED`` fails closed instead of silently
  falling back, exactly as ``REQUIRE_REMOTE_AUTHORIZED`` fails closed instead
  of silently reusing a local cache.
- "Local verified backing" means the exact accepted #101 meaning: content the
  requesting participant's own ``NodeArtifactCache`` already holds verified,
  the same fact ``Coordinator.delta()`` already reports as
  ``local_artifact_ids``. A Node may hold *more* verified content than any
  currently frozen plan requires (an operator-preloaded full release staged
  as optional backing/cache) without that surplus ever being required or
  silently treated as residency; see ``local_backing_accounting`` below.

This module is deliberately MODEL-INDEPENDENT: no model-family noun, no
backend/vendor noun, no hostname. Tests enforce that boundary statically the
same way the accepted #99/#101 tests do.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping, Sequence

from issue74_methodology import canonical_json_bytes
from issue99_artifact_core import (
    AcquisitionError, CoordinatorAuthority, fail, self_digest, validate_self_identity,
)
from issue101_orchestration import Coordinator

# ---------------------------------------------------------------------------
# Phase 1 - internal Source policy modes
# ---------------------------------------------------------------------------

#: Use an eligible exact local verified Source first; otherwise fall back to
#: an authorized non-local Source. This reproduces the accepted #101
#: ``Coordinator.authorize`` ordering exactly (local, then peer, then
#: origin) and is the default so unpolicied behavior never changes.
SOURCE_POLICY_PREFER_LOCAL_VERIFIED = "PREFER_LOCAL_VERIFIED"

#: Fail closed if the required artifact cannot be satisfied from eligible
#: local verified backing. Never falls back to a remote Source.
SOURCE_POLICY_REQUIRE_LOCAL_VERIFIED = "REQUIRE_LOCAL_VERIFIED"

#: Select an eligible non-local Source even when a local verified copy
#: exists, for controlled comparison.
SOURCE_POLICY_PREFER_REMOTE_AUTHORIZED = "PREFER_REMOTE_AUTHORIZED"

#: Fail closed if no eligible non-local authorized Source exists. Never
#: silently substitutes a local cache hit.
SOURCE_POLICY_REQUIRE_REMOTE_AUTHORIZED = "REQUIRE_REMOTE_AUTHORIZED"

SOURCE_POLICIES = (
    SOURCE_POLICY_PREFER_LOCAL_VERIFIED,
    SOURCE_POLICY_REQUIRE_LOCAL_VERIFIED,
    SOURCE_POLICY_PREFER_REMOTE_AUTHORIZED,
    SOURCE_POLICY_REQUIRE_REMOTE_AUTHORIZED,
)

LOCAL_BACKING_ACCOUNTING_SCHEMA = "inferswarm.issue200.local-backing-accounting/1"


def _source_key(artifact_id: str, descriptor: Mapping[str, Any]):
    """Local re-derivation of #101's private ``_source_key`` (artifact, descriptor)."""
    return artifact_id, canonical_json_bytes(descriptor)


class PolicyCoordinator(Coordinator):
    """A #101 ``Coordinator`` with one additive method: policy-driven authorize.

    ``authorize`` (inherited, unmodified) keeps the exact accepted #101
    behavior byte-for-byte. ``authorize_under_policy`` is new: it reuses the
    same frozen plan/requirements/inventory/exclusion state and the same
    ``CoordinatorAuthority``/ticket contract, differing only in *which*
    eligible Source it selects for the exact same required artifact.
    """

    def authorize_under_policy(self, delta: Mapping[str, Any], artifact_id: str,
                               policy: str = SOURCE_POLICY_PREFER_LOCAL_VERIFIED) -> dict[str, Any]:
        self._guard(delta, artifact_id, policy)
        if policy not in SOURCE_POLICIES:
            raise fail("SOURCE_UNAUTHORIZED", f"unsupported source policy {policy!r}")
        validate_self_identity(delta, identity_field="delta_digest")
        if self._deltas.get(delta["delta_digest"]) != delta:
            raise fail("RECONCILIATION_MISMATCH", "unissued or stale delta")
        if self._snapshots[delta["node_id"]]["sequence"] != delta["inventory_sequence"]:
            raise fail("RECONCILIATION_MISMATCH", "target inventory changed; derive a fresh delta")
        participant = self._participant(delta["participant_id"])
        records = {r["artifact_id"]: r for r in participant["required_artifacts"]}
        if artifact_id not in records:
            raise fail("UNDECLARED_REQUIREMENT_ARTIFACT", "artifact outside frozen requirement")
        record = records[artifact_id]
        local_eligible = artifact_id in delta["local_artifact_ids"]

        def remote_candidates():
            peers = [e["source"] for e in self.source_index().get(artifact_id, [])
                     if e["record"] == record and e["node_id"] != delta["node_id"]]
            if peers:
                return peers, "PEER_CACHE"
            origins = [s for s in self._origins if _source_key(artifact_id, s) not in self._excluded]
            return origins, "ORIGIN"

        candidates: list[dict[str, Any]] = []
        if policy == SOURCE_POLICY_REQUIRE_LOCAL_VERIFIED:
            if not local_eligible:
                raise fail("SOURCE_UNAUTHORIZED",
                           "no eligible local verified backing under REQUIRE_LOCAL_VERIFIED")
            source, mode = self._nodes[delta["node_id"]], "LOCAL_CACHE"
        elif policy == SOURCE_POLICY_REQUIRE_REMOTE_AUTHORIZED:
            candidates, mode = remote_candidates()
            if not candidates:
                raise fail("SOURCE_UNAUTHORIZED",
                           "no eligible non-local authorized source under REQUIRE_REMOTE_AUTHORIZED")
            source = candidates[0]
        elif policy == SOURCE_POLICY_PREFER_REMOTE_AUTHORIZED:
            candidates, mode = remote_candidates()
            if candidates:
                source = candidates[0]
            elif local_eligible:
                source, mode = self._nodes[delta["node_id"]], "LOCAL_CACHE"
            else:
                raise fail("SOURCE_UNAUTHORIZED", "no authorized source")
        else:  # SOURCE_POLICY_PREFER_LOCAL_VERIFIED: identical ordering to accepted #101 authorize
            if local_eligible:
                source, mode = self._nodes[delta["node_id"]], "LOCAL_CACHE"
            else:
                candidates, mode = remote_candidates()
                if not candidates:
                    raise fail("SOURCE_UNAUTHORIZED", "no authorized source")
                source = candidates[0]

        authority = CoordinatorAuthority(plan=self._plan, requirements=self._requirements,
                                         eligible_sources=[source])
        ticket = {"epoch": self._plan["epoch"],
                  "plan_digest": self._plan["plan_digest"], "generation": self._generation,
                  "participant_id": delta["participant_id"], "node_id": delta["node_id"],
                  "participant_requirements_digest": participant["participant_requirements_digest"],
                  "delta_digest": delta["delta_digest"], "artifact_id": artifact_id,
                  "source": deepcopy(source), "mode": mode, "source_policy": policy,
                  "candidates": deepcopy(candidates),
                  "attempt_number": len(self.selections) + 1,
                  "authorization": deepcopy(authority.authorization)}
        ticket["attempt_digest"] = self_digest(ticket, identity_field="attempt_digest")
        self._attempts[ticket["attempt_digest"]] = (deepcopy(ticket), authority)
        self.selections.append(deepcopy(ticket))
        return ticket


# ---------------------------------------------------------------------------
# Controlled-comparison acquisition: honor a policy that deliberately chose a
# non-local Source even though the node already verifies the bytes locally.
# ---------------------------------------------------------------------------


def acquire_under_policy(node: Any, coordinator: Coordinator, ticket: Mapping[str, Any],
                         source: Any) -> dict[str, Any]:
    """Node-side acquisition honoring an R8-F policy ticket.

    For every ticket whose selected ``mode`` is ``LOCAL_CACHE``, or whose
    node does not already verify the artifact locally, this is byte-for-byte
    ``Node.acquire`` (inherited, unmodified): the ordinary accepted #101
    acquisition path, including its lifecycle/failure bookkeeping and its
    already-verified-locally shortcut.

    Only when the *policy itself* deliberately selected a non-local Source
    despite the node already holding the exact verified bytes locally (the
    ``PREFER_REMOTE_AUTHORIZED`` / ``REQUIRE_REMOTE_AUTHORIZED`` controlled-
    comparison arms) does this bypass that shortcut, using only the same
    public cache/ledger primitives ``acquire_artifact`` itself uses, so the
    authorized Source is genuinely read and the transferred bytes are
    honestly attributed instead of being silently absorbed by incidental
    local possession. This never authorizes anything ``check_acquisition``
    would not: ``coordinator.validate_attempt`` is still the sole gate.
    """
    authority, record = coordinator.validate_attempt(ticket, node.node_id, source.descriptor())
    if ticket["mode"] == "LOCAL_CACHE" or not node.cache.has_verified(record):
        return node.acquire(coordinator, ticket, source)

    identity = {"attempt_digest": ticket["attempt_digest"], "artifact_id": record["artifact_id"],
                "participant_id": ticket["participant_id"], "node_id": node.node_id,
                "epoch": ticket["epoch"], "plan_digest": ticket["plan_digest"]}
    try:
        node.cache.begin_partial(record)
        offset = 0
        object_base = record["origin"]["byte_start"] if record["kind"] == "byte_range" else 0
        while offset < record["length"]:
            want = min(65536, record["length"] - offset)
            data = source.read(record["origin"], object_base + offset, want)
            offset = node.cache.append_partial(record, data)
        node.cache.finish_partial(record)
    except AcquisitionError as error:
        node.failures.append({**identity, "reason": str(error).split(":")[0]})
        raise
    event = {"event": "ACQUIRED", "participant_id": ticket["participant_id"],
             "artifact_id": record["artifact_id"], "content_digest": record["content_digest"],
             "source_id": source.source_id, "bytes": record["length"],
             "resumed_from_bytes": 0, "partial_staging_bytes": record["length"],
             "policy_forced_transfer": True}
    event.update(identity)
    node.ledger.record(event)
    node.lifecycle.append({**identity, "state": "VERIFIED_AVAILABLE"})
    return {"status": "ACQUIRED", "bytes": record["length"]}


# ---------------------------------------------------------------------------
# Phase 2 - full-release optional local backing accounting
# ---------------------------------------------------------------------------


def local_backing_accounting(*, node: Any, participant_requirements: Mapping[str, Any]) -> dict[str, Any]:
    """Distinguish required-bytes-satisfied-from-backing from optional surplus.

    A Node's durable cache (``node.cache``) may hold more verified immutable
    objects than ``participant_requirements`` currently declares required
    (an operator deliberately staged a complete release as backing). This
    reports both quantities from the Node's own re-verified inventory
    (``NodeArtifactCache.inventory``, which independently re-hashes every
    object) without ever treating the surplus as required, residency, or a
    feasibility prerequisite:

    - ``required_bytes_satisfied_from_local_backing``: bytes of the exact
      required artifact set that happen to already be verified in this
      Node's own cache (would resolve to ``LOCAL_CACHE`` / a ``CACHE_HIT``);
    - ``total_verified_local_backing_bytes``: every verified byte in the
      Node's cache, required or not;
    - ``retained_optional_backing_bytes``: the surplus, i.e. verified bytes
      that satisfy no currently declared requirement of this participant.

    Both quantities are derived mechanically from the Node's own inventory
    and the frozen requirements document; neither is an authored claim.
    """
    required = {r["artifact_id"]: r for r in participant_requirements["required_artifacts"]}
    inventory = node.cache.inventory()
    verified_identities = {(obj["content_digest"], obj["length"])
                           for obj in inventory["verified_objects"] if obj["byte_digest_verified"]}
    required_bytes_satisfied_from_local_backing = sum(
        r["length"] for r in required.values()
        if (r["content_digest"], r["length"]) in verified_identities)
    total_verified_local_backing_bytes = sum(
        obj["length"] for obj in inventory["verified_objects"] if obj["byte_digest_verified"])
    document = {
        "schema": LOCAL_BACKING_ACCOUNTING_SCHEMA,
        "node_id": node.node_id,
        "participant_id": participant_requirements["participant_id"],
        "participant_requirements_digest": participant_requirements["participant_requirements_digest"],
        "required_artifact_bytes": participant_requirements["required_artifact_bytes"],
        "required_bytes_satisfied_from_local_backing": required_bytes_satisfied_from_local_backing,
        "total_verified_local_backing_bytes": total_verified_local_backing_bytes,
        "retained_optional_backing_bytes": (
            total_verified_local_backing_bytes - required_bytes_satisfied_from_local_backing),
    }
    return document


def ledger_network_accounting(ledger_events: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Mechanically re-derive network/cache byte totals from ledger events.

    Never trusts an authored "zero network bytes" claim: this recomputes it
    from the same acquisition-ledger events accepted #99 accounting already
    produces (``CACHE_HIT`` vs ``ACQUIRED``), so a wrong authored claim is
    mechanically distinguishable from the true event-derived total.
    """
    cache_hit_bytes = sum(e["bytes"] for e in ledger_events if e["event"] == "CACHE_HIT")
    acquired_bytes = sum(e["bytes"] for e in ledger_events if e["event"] == "ACQUIRED")
    forced_transfer_bytes = sum(
        e["bytes"] for e in ledger_events
        if e["event"] == "ACQUIRED" and e.get("policy_forced_transfer"))
    return {
        "verified_cache_hit_bytes": cache_hit_bytes,
        "newly_acquired_bytes": acquired_bytes,
        "policy_forced_transfer_bytes": forced_transfer_bytes,
        "network_bytes_moved": acquired_bytes,
    }
