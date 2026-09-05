#!/usr/bin/env python3
"""InferSwarm issue #99 plan-driven model artifact acquisition core (CPU-only).

Implements the minimum generic seam required by ADR 0009 and
docs/architecture/model-artifact-distribution.md between a frozen Execution
Plan and participant Materializations:

    frozen plan -> participant requirements -> artifact resolution
        -> authorized Source -> verified acquisition -> durable local cache
        -> bounded staging input

This module is deliberately MODEL-INDEPENDENT. It must not learn any
model-family noun (checkpoint formats, tensor names, producers, layers): the
mapping from Logical State Unit requirements to concrete immutable objects
belongs to the Model Execution Strategy / model-adapter boundary, which
supplies opaque artifact records to this core. Tests enforce that boundary
statically.

All identity is content/provenance based; a filesystem path or filename alone
is never artifact identity. Internal record schemas are implementation
details and intentionally unfrozen (no public CAS/manifest API is defined
here). The control-plane components handle identities and descriptors only:
bulk model bytes never transit the Coordinator, which is proven mechanically
by a bytes-observed guard on every control-plane entry point.

Pure stdlib. Fail-closed everywhere: wrong bytes, wrong provenance,
unauthorized sources, foreign partial-transfer state, and undeclared
requirements raise before anything becomes trusted state.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Sequence

from issue74_methodology import canonical_json_bytes

REQUIREMENTS_SCHEMA = "inferswarm.issue99.participant-requirements/1"
ARTIFACT_RECORD_SCHEMA = "inferswarm.issue99.artifact-record/1"
AUTHORIZATION_SCHEMA = "inferswarm.issue99.realization-authorization/1"
CACHE_INVENTORY_SCHEMA = "inferswarm.issue99.cache-inventory/1"
LEDGER_SCHEMA = "inferswarm.issue99.acquisition-ledger/1"

REQUIREMENT_CLASSES = ("assigned_logical_state", "declared_shared_state", "required_metadata")
ARTIFACT_KINDS = ("byte_range", "whole_object", "transform")
DEFAULT_CHUNK_BYTES = 65536


#: The closed fail-closed reason taxonomy. Every AcquisitionError carries one
#: of these as the first token of its message; strategy adapters construct
#: errors through ``fail`` so no undocumented reason code can appear.
REASONS = (
    "MALFORMED_ARTIFACT_RECORD",
    "PROVENANCE_IDENTITY_MISMATCH",
    "REQUIRED_STATE_COVERAGE_INCOMPLETE",
    "UNDECLARED_REQUIREMENT_ARTIFACT",
    "SOURCE_UNAUTHORIZED",
    "SOURCE_OBJECT_UNAVAILABLE",
    "INTEGRITY_DIGEST_MISMATCH",
    "UNVERIFIED_OBJECT_PUBLICATION_REFUSED",
    "UNVERIFIED_SOURCE_READ_REFUSED",
    "PARTIAL_STATE_IDENTITY_MISMATCH",
    "CACHE_OBJECT_TAMPERED",
    "RECONCILIATION_MISMATCH",
    "UPSTREAM_OBJECT_FULLY_ACQUIRED_WITHOUT_DECLARATION",
    "STAGING_UNPLANNED_KEY",
    "EXECUTION_IDENTITY_MISMATCH",
)


class AcquisitionError(RuntimeError):
    """Fail-closed acquisition/identity failure.

    The first token of ``str(err)`` is always a stable machine reason code.
    """

    REASONS = REASONS


def _fail(reason: str, detail: str = "") -> AcquisitionError:
    if reason not in REASONS:
        raise AssertionError(f"unknown acquisition reason code: {reason!r}")
    message = reason if not detail else f"{reason}: {detail}"
    return AcquisitionError(message)


# Strategy adapters construct fail-closed errors through the same taxonomy.
fail = _fail


def digest_of_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def self_digest(document: Mapping[str, Any]) -> str:
    """Digest of a document excluding its own identity fields.

    A frozen document carries exactly one top-level self-identity key
    (``digest``-like, or ``artifact_id`` for records); it is excluded so the
    digest covers only the content it identities.
    """
    identity_keys = ("digest", "plan_digest", "requirements_digest",
                     "authorization_digest", "participant_requirements_digest",
                     "artifact_id")
    payload = {key: value for key, value in document.items() if key not in identity_keys}
    return digest_of_bytes(canonical_json_bytes(payload))


def write_canonical_json(path: Path, document: Mapping[str, Any]) -> None:
    """Write deterministic canonical JSON (sorted keys, indent 2)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json_bytes(document))


# ---------------------------------------------------------------------------
# Artifact records (internal, unfrozen representation)
# ---------------------------------------------------------------------------


def _validated_origin(kind: str, origin: Mapping[str, Any], length: int) -> dict[str, Any]:
    origin = dict(origin)
    if kind == "byte_range":
        required = ("source_object", "source_object_digest", "source_object_length",
                    "byte_start", "byte_end")
        for field in required:
            if field not in origin:
                raise _fail("MALFORMED_ARTIFACT_RECORD", f"range origin missing {field!r}")
        span = origin["byte_end"] - origin["byte_start"]
        if span <= 0 or origin["byte_start"] < 0 or origin["byte_end"] > origin["source_object_length"]:
            raise _fail("MALFORMED_ARTIFACT_RECORD", "range outside source object bounds")
        if span != length:
            raise _fail("MALFORMED_ARTIFACT_RECORD", "range length != content length")
    elif kind == "whole_object":
        for field in ("source_object", "source_object_digest", "source_object_length"):
            if field not in origin:
                raise _fail("MALFORMED_ARTIFACT_RECORD", f"whole origin missing {field!r}")
        if origin["source_object_length"] != length:
            raise _fail("MALFORMED_ARTIFACT_RECORD", "whole-object length != content length")
    return origin


def freeze_artifact_record(
    *,
    kind: str,
    content: bytes,
    model_id: str,
    revision: str,
    representation: str,
    satisfies_logical_state_ids: Sequence[str],
    requirement_class: str,
    origin: Mapping[str, Any],
    transform: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    """Build an artifact identity record from its exact bytes (source/strategy side).

    ``content`` are the exact bytes the artifact resolves to, held by the
    operator/strategy side that can see the frozen upstream objects. The
    control plane and participants only ever see the resulting record; they
    verify fetched bytes against ``content_digest`` instead of trusting it.
    """
    if kind not in ARTIFACT_KINDS:
        raise _fail("MALFORMED_ARTIFACT_RECORD", f"kind {kind!r}")
    if requirement_class not in REQUIREMENT_CLASSES:
        raise _fail("MALFORMED_ARTIFACT_RECORD", f"requirement class {requirement_class!r}")
    if not satisfies_logical_state_ids:
        raise _fail("MALFORMED_ARTIFACT_RECORD", "no logical-state requirement satisfied")
    if kind == "transform" and (
        not transform or "transform_id" not in transform or "transform_version" not in transform
    ):
        raise _fail("MALFORMED_ARTIFACT_RECORD", "transform identity missing")
    record = {
        "schema": ARTIFACT_RECORD_SCHEMA,
        "kind": kind,
        "content_digest": digest_of_bytes(content),
        "length": len(content),
        "provenance": {
            "model_id": model_id,
            "revision": revision,
            "representation": representation,
        },
        "satisfies_logical_state_ids": sorted(satisfies_logical_state_ids),
        "requirement_class": requirement_class,
        "origin": _validated_origin(kind, origin, len(content)),
    }
    if transform is not None:
        record["transform"] = dict(transform)
    record["artifact_id"] = self_digest(record)
    return record


def validate_artifact_record(record: Mapping[str, Any]) -> dict[str, Any]:
    """Fail-closed structural + self-identity validation of a frozen record."""
    try:
        if record["schema"] != ARTIFACT_RECORD_SCHEMA:
            raise _fail("MALFORMED_ARTIFACT_RECORD", str(record.get("schema")))
        if record["kind"] not in ARTIFACT_KINDS:
            raise _fail("MALFORMED_ARTIFACT_RECORD", str(record["kind"]))
        if record["requirement_class"] not in REQUIREMENT_CLASSES:
            raise _fail("MALFORMED_ARTIFACT_RECORD", str(record["requirement_class"]))
        satisfies = record["satisfies_logical_state_ids"]
        if not isinstance(satisfies, list) or not satisfies:
            raise _fail("MALFORMED_ARTIFACT_RECORD", "empty satisfies set")
        if record["length"] != int(record["length"]) or record["length"] <= 0:
            raise _fail("MALFORMED_ARTIFACT_RECORD", "length")
        if not str(record["content_digest"]).startswith("sha256:"):
            raise _fail("MALFORMED_ARTIFACT_RECORD", "content digest form")
        origin = _validated_origin(record["kind"], record["origin"], record["length"])
        if origin is not record["origin"]:
            record = dict(record)
            record["origin"] = origin
        if record["kind"] == "transform" and "transform" not in record:
            raise _fail("MALFORMED_ARTIFACT_RECORD", "transform identity missing")
        expected = self_digest(record)
        if record["artifact_id"] != expected:
            raise _fail("MALFORMED_ARTIFACT_RECORD", "artifact_id self-identity mismatch")
    except KeyError as missing:
        raise _fail("MALFORMED_ARTIFACT_RECORD", f"missing field {missing}") from missing
    return dict(record)


# ---------------------------------------------------------------------------
# Plan-driven participant requirement derivation (generic control plane)
# ---------------------------------------------------------------------------


def derive_participant_requirements(
    plan: Mapping[str, Any],
    resolver: Callable[[str, str], Sequence[Mapping[str, Any]]],
) -> dict[str, Any]:
    """Derive each participant's required immutable artifact set from a frozen plan.

    ``resolver(requirement_class, requirement_id)`` is the Model Execution
    Strategy adapter: the only component allowed to know how a logical-state
    requirement maps to concrete upstream objects/ranges/transforms. It
    returns frozen artifact records (see ``freeze_artifact_record``). The
    resolver output crosses the strategy boundary as descriptors only — the
    exact bytes stay on the data path.

    Fail-closed guards:
    - every declared requirement must be covered by >= 1 artifact;
    - every artifact must carry the plan's exact model/revision/representation;
    - every artifact must satisfy only requirements declared for that
      participant under the same requirement class (no silent whole-model
      inclusion, no convenience preloads).
    """
    model = plan["model"]
    declared_unit_ids = {unit["id"] for unit in plan["logical_state_units"]}
    participants_out = []
    for participant in plan["participants"]:
        required_state = participant["required_state"]
        declared: dict[str, str] = {}
        for requirement_class in REQUIREMENT_CLASSES:
            for requirement_id in required_state[requirement_class]:
                if requirement_id not in declared_unit_ids:
                    raise _fail("UNDECLARED_REQUIREMENT_ARTIFACT",
                                f"{participant['participant_id']}: {requirement_id} is not a "
                                "declared Logical State Unit of the plan")
                if requirement_id in declared:
                    raise _fail("REQUIRED_STATE_COVERAGE_INCOMPLETE",
                                f"{participant['participant_id']}: {requirement_id} declared twice")
                declared[requirement_id] = requirement_class
        records: dict[str, dict[str, Any]] = {}
        satisfied_by: dict[str, list[str]] = {rid: [] for rid in declared}
        for requirement_class in REQUIREMENT_CLASSES:
            for requirement_id in required_state[requirement_class]:
                produced = resolver(requirement_class, requirement_id)
                if not produced:
                    raise _fail("REQUIRED_STATE_COVERAGE_INCOMPLETE",
                                f"{requirement_id}: resolver produced no artifacts")
                for raw in produced:
                    record = validate_artifact_record(raw)
                    provenance = record["provenance"]
                    if (provenance["model_id"], provenance["revision"], provenance["representation"]) != (
                        model["model_id"], model["revision"], model["representation"]
                    ):
                        raise _fail("PROVENANCE_IDENTITY_MISMATCH",
                                    f"{record['satisfies_logical_state_ids']} provenance "
                                    f"{provenance} != plan model identity")
                    for state_id in record["satisfies_logical_state_ids"]:
                        if state_id not in declared:
                            raise _fail("UNDECLARED_REQUIREMENT_ARTIFACT",
                                        f"{state_id} not declared for {participant['participant_id']}")
                        if declared[state_id] != record["requirement_class"]:
                            raise _fail("UNDECLARED_REQUIREMENT_ARTIFACT",
                                        f"{state_id} declared as {declared[state_id]} but artifact "
                                        f"claims {record['requirement_class']}")
                        satisfied_by[state_id].append(record["artifact_id"])
                    records[record["artifact_id"]] = record
        missing = sorted(rid for rid, ids in satisfied_by.items() if not ids)
        if missing:
            raise _fail("REQUIRED_STATE_COVERAGE_INCOMPLETE", f"uncovered: {missing}")
        participant_doc = {
            "participant_id": participant["participant_id"],
            "node_id": participant["node_id"],
            "execution_unit_id": participant["execution_unit_id"],
            "required_logical_state": {
                "assigned": sorted(required_state["assigned_logical_state"]),
                "declared_shared": sorted(required_state["declared_shared_state"]),
                "required_metadata": sorted(required_state["required_metadata"]),
            },
            "required_artifacts": [records[aid] for aid in sorted(records)],
            "required_artifact_bytes": sum(r["length"] for r in records.values()),
        }
        participant_doc["participant_requirements_digest"] = self_digest(participant_doc)
        participants_out.append(participant_doc)
    document = {
        "schema": REQUIREMENTS_SCHEMA,
        "plan_digest": plan["plan_digest"],
        "model": dict(model),
        "participants": participants_out,
    }
    document["requirements_digest"] = self_digest(document)
    return document


# ---------------------------------------------------------------------------
# Coordinator-side authorization (control plane only; never bulk bytes)
# ---------------------------------------------------------------------------


def _walk_for_bytes(value: Any, sink: list[int]) -> None:
    if isinstance(value, (bytes, bytearray)):
        sink.append(len(value))
        return
    if isinstance(value, Mapping):
        for item in value.values():
            _walk_for_bytes(item, sink)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _walk_for_bytes(item, sink)


class CoordinatorAuthority:
    """CPU-only control authority: freezes realization authorization.

    Handles only identities/descriptors. Every entry point rejects ``bytes``
    payloads anywhere in its inputs, so bulk model bytes can never transit
    the Coordinator; ``bytes_observed`` proves it mechanically.
    """

    def __init__(self, *, plan: Mapping[str, Any], requirements: Mapping[str, Any],
                 eligible_sources: Sequence[Mapping[str, Any]]) -> None:
        self.bytes_observed = 0
        self._reject_bytes(plan, requirements, eligible_sources)
        if requirements["plan_digest"] != plan["plan_digest"]:
            raise _fail("RECONCILIATION_MISMATCH", "requirements do not belong to the plan")
        source_ids = [s["source_id"] for s in eligible_sources]
        if len(set(source_ids)) != len(source_ids):
            raise _fail("SOURCE_UNAUTHORIZED", "duplicate eligible source ids")
        for source in eligible_sources:
            if set(source) != {"source_id", "endpoint"}:
                raise _fail("SOURCE_UNAUTHORIZED", f"source descriptor fields {sorted(source)}")
        self._declared_states: dict[str, set[str]] = {}
        self._required_records: dict[str, dict[str, dict[str, Any]]] = {}
        participants: dict[str, dict[str, Any]] = {}
        for participant in requirements["participants"]:
            pid = participant["participant_id"]
            state = participant["required_logical_state"]
            self._declared_states[pid] = set(
                state["assigned"]) | set(state["declared_shared"]) | set(state["required_metadata"])
            self._required_records[pid] = {r["artifact_id"]: r for r in participant["required_artifacts"]}
            participants[pid] = {
                "required_artifact_ids": sorted(r["artifact_id"] for r in participant["required_artifacts"]),
                "eligible_source_ids": sorted(source_ids),
            }
        authorization = {
            "schema": AUTHORIZATION_SCHEMA,
            "plan_digest": plan["plan_digest"],
            "requirements_digest": requirements["requirements_digest"],
            "eligible_sources": [dict(s) for s in eligible_sources],
            "participants": participants,
        }
        authorization["authorization_digest"] = self_digest(authorization)
        self.authorization = authorization

    def _reject_bytes(self, *values: Any) -> None:
        sink: list[int] = []
        for value in values:
            _walk_for_bytes(value, sink)
        if sink:
            self.bytes_observed += sum(sink)
            raise _fail("SOURCE_UNAUTHORIZED", "bulk bytes presented to the Coordinator")

    def check_acquisition(self, *, participant_id: str, artifact_record: Mapping[str, Any],
                          source_id: str) -> None:
        """Node-side gate: may this participant fetch this artifact from this source?"""
        self._reject_bytes(artifact_record)
        participant = self.authorization["participants"].get(participant_id)
        if participant is None:
            raise _fail("SOURCE_UNAUTHORIZED", f"participant {participant_id} not in authorization")
        if artifact_record["artifact_id"] not in participant["required_artifact_ids"]:
            raise _fail("UNDECLARED_REQUIREMENT_ARTIFACT",
                        f"artifact {artifact_record['artifact_id']} not in the required set")
        if source_id not in participant["eligible_source_ids"]:
            raise _fail("SOURCE_UNAUTHORIZED", f"source {source_id} not eligible")
        expected = self._required_records[participant_id][artifact_record["artifact_id"]]
        if dict(artifact_record) != dict(expected):
            raise _fail("PROVENANCE_IDENTITY_MISMATCH", "authorized artifact record drifted")

    def reconcile(self, *, participant_id: str, used_artifact_ids: Sequence[str],
                  materializations: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
        """Audit which verified artifacts/materializations satisfied the realization."""
        self._reject_bytes(materializations)
        required_ids = set(self.authorization["participants"][participant_id]["required_artifact_ids"])
        used = set(used_artifact_ids)
        if used != required_ids:
            raise _fail("RECONCILIATION_MISMATCH",
                        f"artifacts used {sorted(used)} != required {sorted(required_ids)}")
        observed_states: set[str] = set()
        for materialization in materializations:
            if materialization["verification"] != "VERIFIED_CACHE_SOURCE":
                raise _fail("RECONCILIATION_MISMATCH",
                            f"materialization {materialization['logical_state_id']} "
                            "not from a verified cache source")
            if materialization["observed_bytes"] != materialization["expected_bytes"]:
                raise _fail("RECONCILIATION_MISMATCH",
                            f"materialization {materialization['logical_state_id']} "
                            "byte accounting mismatch")
            observed_states.add(materialization["logical_state_id"])
        missing = sorted(self._declared_states[participant_id] - observed_states)
        if missing:
            raise _fail("REQUIRED_STATE_COVERAGE_INCOMPLETE", f"never materialized: {missing}")
        return {
            "participant_id": participant_id,
            "status": "PLANNED_AND_REALIZED",
            "artifacts_used": sorted(used),
            "materializations": [dict(m) for m in materializations],
        }


# ---------------------------------------------------------------------------
# Authorized Sources (one at a time; direct participant data movement)
# ---------------------------------------------------------------------------


def _requests_for(access_log: list[dict[str, Any]], source_object: str) -> list[dict[str, Any]]:
    return [entry for entry in access_log if entry["source_object"] == source_object]


class TransferInterrupted(Exception):
    """Controlled source-side interruption (retained partial state is legal).

    ``partial`` carries the bytes that did arrive before the connection died;
    the engine retains them as identity-bound partial state for a legal resume.
    """

    def __init__(self, message: str, partial: bytes = b"") -> None:
        super().__init__(message)
        self.partial = partial


class LocalFileSource:
    """Operator-managed local filesystem test source (file:// semantics)."""

    kind = "operator-local-file"

    def __init__(self, *, source_id: str, root: Path) -> None:
        self.source_id = source_id
        self.endpoint = f"file://{root}"
        self.root = Path(root)
        self.access_log: list[dict[str, Any]] = []
        self._lock = threading.Lock()

    def descriptor(self) -> dict[str, Any]:
        return {"source_id": self.source_id, "endpoint": self.endpoint}

    def read(self, origin: Mapping[str, Any], offset: int, length: int) -> bytes:
        name = origin["source_object"]
        with self._lock:
            self.access_log.append({"source_object": name, "offset": offset, "length": length})
        path = self.root / name
        if not path.is_file():
            raise _fail("SOURCE_OBJECT_UNAVAILABLE", name)
        with open(path, "rb") as handle:
            handle.seek(offset)
            data = handle.read(length)
        if len(data) != length:
            raise _fail("SOURCE_OBJECT_UNAVAILABLE", "short read")
        return data

    def requests_for(self, source_object: str) -> list[dict[str, Any]]:
        return _requests_for(self.access_log, source_object)


class LocalHttpSource:
    """Operator-managed local HTTP test source with Range support.

    Proof-harness knobs (disabled by default) exercise the architecture
    honestly: ``interrupt_after`` truncates a response mid-object to prove
    resumable transfer; ``corrupt_at`` flips one byte in flight to prove
    fail-closed integrity rejection. Both are source-side behaviors.
    """

    kind = "operator-local-http"

    def __init__(self, *, source_id: str, root: Path, host: str = "127.0.0.1") -> None:
        self.source_id = source_id
        self.root = Path(root)
        self.access_log: list[dict[str, Any]] = []
        self.interrupt_after: dict[str, int] = {}
        self.corrupt_at: dict[str, int] = {}
        self._lock = threading.Lock()
        outer = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *_args: Any) -> None:  # silence stderr noise
                return

            def do_GET(self) -> None:  # noqa: N802 (http.server API)
                name = self.path.lstrip("/")
                path = outer.root / name
                with outer._lock:
                    outer.access_log.append({
                        "source_object": name, "range_header": self.headers.get("Range"),
                    })
                if not path.is_file():
                    self.send_error(404, "SOURCE_OBJECT_UNAVAILABLE")
                    return
                data = path.read_bytes()
                start, end = 0, len(data)
                range_header = self.headers.get("Range")
                if range_header and range_header.startswith("bytes="):
                    first, _, last = range_header[len("bytes="):].partition("-")
                    start = int(first)
                    end = len(data) if not last else int(last) + 1
                served = end - start
                interrupt_at = outer.interrupt_after.get(name)
                if interrupt_at is not None:
                    # Controlled interruption: the connection has delivered
                    # only the first ``interrupt_at`` bytes of the OBJECT.
                    served = min(served, max(0, interrupt_at - start))
                body = bytearray(data[start:start + served])
                corrupt_at = outer.corrupt_at.get(name)
                if corrupt_at is not None and start <= corrupt_at < start + len(body):
                    body[corrupt_at - start] ^= 0xFF
                try:
                    self.send_response(206 if range_header else 200)
                    self.send_header("Content-Type", "application/octet-stream")
                    self.send_header("Content-Length", str(len(body)))
                    if range_header:
                        self.send_header(
                            "Content-Range",
                            f"bytes {start}-{start + len(body) - 1}/{len(data)}")
                    self.end_headers()
                    self.wfile.write(bytes(body))
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    pass  # the controlled interruption already served its prefix

        self._server = ThreadingHTTPServer((host, 0), Handler)
        self.port = self._server.server_address[1]
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def descriptor(self) -> dict[str, Any]:
        return {"source_id": self.source_id, "endpoint": f"http://127.0.0.1:{self.port}"}

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)

    def read(self, origin: Mapping[str, Any], offset: int, length: int) -> bytes:
        name = origin["source_object"]
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/{name}",
            headers={"Range": f"bytes={offset}-{offset + length - 1}"})
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                data = response.read()
        except urllib.error.HTTPError as error:
            if error.code == 404:
                raise _fail("SOURCE_OBJECT_UNAVAILABLE", name) from error
            raise
        if len(data) < length:
            raise TransferInterrupted(
                f"INTERRUPTED_AFTER_{len(data)}_OF_{length}", partial=data)
        if len(data) != length:
            raise _fail("SOURCE_OBJECT_UNAVAILABLE", "unexpected length")
        return data

    def requests_for(self, source_object: str) -> list[dict[str, Any]]:
        return _requests_for(self.access_log, source_object)

# ---------------------------------------------------------------------------
# Node-local durable content-addressed cache
# ---------------------------------------------------------------------------


def _digest_path_component(digest: str) -> str:
    return digest.replace("sha256:", "sha256-")


def _artifact_path_component(artifact_id: str) -> str:
    return artifact_id.replace("sha256:", "sha256-")


class NodeArtifactCache:
    """One Node-local durable artifact cache.

    Layout (implementation detail, unfrozen):
      objects/<content_digest>       verified immutable objects (atomic publish)
      partial/<artifact_id>.part     retained partial transfer bytes
      partial/<artifact_id>.state    identity binding sidecar for resume
      inventory.json                 durable inventory snapshot

    An object becomes a trusted local Source only via ``publish`` /
    ``finish_partial``, which verify the exact expected digest first. A
    filesystem path or filename is never artifact identity.
    """

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        (self.root / "objects").mkdir(parents=True, exist_ok=True)
        (self.root / "partial").mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    # -- verified objects ---------------------------------------------------

    def lookup(self, content_digest: str) -> Optional[Path]:
        path = self.root / "objects" / _digest_path_component(content_digest)
        return path if path.is_file() else None

    def has_verified(self, record: Mapping[str, Any]) -> bool:
        return self.lookup(record["content_digest"]) is not None

    def open_verified(self, record: Mapping[str, Any]) -> bytes:
        """Read a trusted object, re-verifying exact bytes (tamper-evident)."""
        validate_artifact_record(record)
        path = self.lookup(record["content_digest"])
        if path is None:
            raise _fail("UNVERIFIED_SOURCE_READ_REFUSED", record["content_digest"])
        data = path.read_bytes()
        if digest_of_bytes(data) != record["content_digest"]:
            raise _fail("CACHE_OBJECT_TAMPERED", record["content_digest"])
        return data

    def publish(self, record: Mapping[str, Any], data: bytes) -> Path:
        """Verify-then-publish. Wrong bytes can never enter the verified store."""
        validate_artifact_record(record)
        if digest_of_bytes(data) != record["content_digest"] or len(data) != record["length"]:
            raise _fail("INTEGRITY_DIGEST_MISMATCH", record["content_digest"])
        with self._lock:
            target = self.root / "objects" / _digest_path_component(record["content_digest"])
            if target.is_file():
                self._discard_partial_locked(record["artifact_id"])
                return target  # deduplication: content identity already verified
            temp = self.root / "partial" / f"publish-{record['content_digest']}.tmp"
            temp.write_bytes(data)
            if digest_of_bytes(temp.read_bytes()) != record["content_digest"]:
                temp.unlink(missing_ok=True)
                raise _fail("INTEGRITY_DIGEST_MISMATCH", "read-back verification failed")
            os.replace(temp, target)
            self._discard_partial_locked(record["artifact_id"])
        return target

    # -- partial transfer state ----------------------------------------------

    def _part_path(self, artifact_id: str) -> Path:
        return self.root / "partial" / (_artifact_path_component(artifact_id) + ".part")

    def _state_path(self, artifact_id: str) -> Path:
        return self.root / "partial" / (_artifact_path_component(artifact_id) + ".state")

    def partial_state(self, artifact_id: str) -> Optional[dict[str, Any]]:
        state_path = self._state_path(artifact_id)
        if not state_path.is_file():
            return None
        try:
            return json.loads(state_path.read_text())
        except json.JSONDecodeError:
            return None

    def begin_partial(self, record: Mapping[str, Any]) -> None:
        validate_artifact_record(record)
        with self._lock:
            self._discard_partial_locked(record["artifact_id"])
            self._part_path(record["artifact_id"]).write_bytes(b"")
            self._write_state_locked(record, 0)

    def append_partial(self, record: Mapping[str, Any], data: bytes) -> int:
        """Append bytes; returns retained length. Binding must match exactly."""
        retained = self._require_matching_partial(record)
        with self._lock:
            with open(self._part_path(record["artifact_id"]), "ab") as handle:
                handle.write(data)
            retained += len(data)
            self._write_state_locked(record, retained)
        return retained

    def resume_partial(self, record: Mapping[str, Any]) -> int:
        """Retained prefix legally bound to this exact artifact identity.

        Returns the retained byte count to resume from. A partial belonging
        to any other identity/range is discarded and the mismatch is raised
        so the caller restarts the object rather than stitching bytes.
        """
        state = self.partial_state(record["artifact_id"])
        if state is None:
            return 0
        binding_ok = (
            state["artifact_id"] == record["artifact_id"]
            and state["content_digest"] == record["content_digest"]
            and state["length"] == record["length"]
        )
        part = self._part_path(record["artifact_id"])
        part_ok = part.is_file() and part.stat().st_size == state["retained_bytes"]
        if binding_ok and part_ok:
            return state["retained_bytes"]
        self.discard_partial(record["artifact_id"])
        raise _fail("PARTIAL_STATE_IDENTITY_MISMATCH", record["artifact_id"])

    def discard_partial(self, artifact_id: str) -> None:
        with self._lock:
            self._discard_partial_locked(artifact_id)

    def _discard_partial_locked(self, artifact_id: str) -> None:
        self._part_path(artifact_id).unlink(missing_ok=True)
        self._state_path(artifact_id).unlink(missing_ok=True)

    def _require_matching_partial(self, record: Mapping[str, Any]) -> int:
        state = self.partial_state(record["artifact_id"])
        if state is None:
            raise _fail("PARTIAL_STATE_IDENTITY_MISMATCH", "no bound partial state")
        if (state["artifact_id"], state["content_digest"], state["length"]) != (
            record["artifact_id"], record["content_digest"], record["length"]
        ):
            raise _fail("PARTIAL_STATE_IDENTITY_MISMATCH", record["artifact_id"])
        return state["retained_bytes"]

    def _write_state_locked(self, record: Mapping[str, Any], retained: int) -> None:
        state = {
            "artifact_id": record["artifact_id"],
            "content_digest": record["content_digest"],
            "length": record["length"],
            "retained_bytes": retained,
        }
        self._state_path(record["artifact_id"]).write_text(
            canonical_json_bytes(state).decode())

    def finish_partial(self, record: Mapping[str, Any]) -> Path:
        """Promote the bound partial to a verified object (verify-then-publish)."""
        retained = self._require_matching_partial(record)
        if retained != record["length"]:
            raise _fail("INTEGRITY_DIGEST_MISMATCH",
                        f"partial incomplete: {retained} of {record['length']}")
        data = self._part_path(record["artifact_id"]).read_bytes()
        return self.publish(record, data)

    # -- inventory ------------------------------------------------------------

    def inventory(self) -> dict[str, Any]:
        verified = []
        for path in sorted((self.root / "objects").iterdir()):
            data = path.read_bytes()
            digest = "sha256:" + path.name.replace("sha256-", "")
            verified.append({
                "content_digest": digest,
                "length": len(data),
                "byte_digest_verified": digest_of_bytes(data) == digest,
            })
        partials = []
        for state_path in sorted((self.root / "partial").glob("*.state")):
            state = json.loads(state_path.read_text())
            part = self._part_path(state["artifact_id"])
            state["part_bytes_on_disk"] = part.stat().st_size if part.is_file() else 0
            partials.append(state)
        return {
            "schema": CACHE_INVENTORY_SCHEMA,
            "cache_root": str(self.root),
            "verified_objects": verified,
            "partial_transfers": partials,
            "verified_bytes": sum(o["length"] for o in verified),
            "partial_bytes": sum(p["part_bytes_on_disk"] for p in partials),
        }


# ---------------------------------------------------------------------------
# Acquisition engine + accounting ledger
# ---------------------------------------------------------------------------


class AcquisitionLedger:
    """Distinguishes every byte class required by the architecture supplement."""

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []
        self.started = time.monotonic()

    def record(self, event: dict[str, Any]) -> None:
        event = dict(event)
        event.setdefault("wall_time_seconds", round(time.monotonic() - self.started, 6))
        self.events.append(event)

    def document(self, *, records_by_digest: Mapping[str, Mapping[str, Any]] = {},
                 participants: Mapping[str, Mapping[str, Any]] = {}) -> dict[str, Any]:
        hits = [e for e in self.events if e["event"] == "CACHE_HIT"]
        acquired = [e for e in self.events if e["event"] == "ACQUIRED"]
        resumed = [e for e in self.events if e["event"] == "RESUME_REUSED_PREFIX"]
        integrity = [e for e in self.events if e["event"] == "INTEGRITY_FAILURE"]
        by_source: dict[str, int] = {}
        for event in acquired:
            by_source[event["source_id"]] = by_source.get(event["source_id"], 0) + event["bytes"]
        unrelated = 0
        for event in acquired:
            record = records_by_digest.get(event["content_digest"])
            if record is None:
                unrelated += event["bytes"]
                continue
            declared = set(participants.get(event["participant_id"], {}).get("declared_state_ids", []))
            if not set(record["satisfies_logical_state_ids"]) & declared:
                unrelated += event["bytes"]
        acquired_records = [dict(records_by_digest[e["content_digest"]])
                            for e in acquired if e["content_digest"] in records_by_digest]
        document = {
            "schema": LEDGER_SCHEMA,
            "events": self.events,
            "aggregate": {
                "required_source_bytes": sum(
                    p.get("required_artifact_bytes", 0) for p in participants.values()),
                "verified_cache_hit_bytes": sum(e["bytes"] for e in hits),
                "newly_acquired_bytes": sum(e["bytes"] for e in acquired),
                "acquired_bytes_by_source": by_source,
                "resume_reused_prefix_bytes": sum(e["bytes"] for e in resumed),
                "retry_resume_transfer_bytes": sum(
                    e["bytes"] for e in acquired if e.get("resumed_from_bytes", 0) > 0),
                "temporary_partial_staging_bytes": sum(
                    e.get("partial_staging_bytes", 0) for e in self.events
                    if e["event"] in ("ACQUIRED", "TRANSFER_INTERRUPTED", "PARTIAL_DISCARDED")),
                "integrity_failures": [e["reason"] for e in integrity],
                "unrelated_model_bytes_acquired_for_realization": unrelated,
                "unexplained_full_model_dependency": _unexplained_full_object_bytes(acquired_records),
            },
        }
        return document


def _unexplained_full_object_bytes(records: Sequence[Mapping[str, Any]]) -> int:
    """Bytes acquired that secretly amount to whole upstream objects.

    A hidden whole-model dependency exists if the acquired byte ranges cover a
    complete upstream object without that object being declared as a legitimate
    whole-object requirement (``required_metadata``), or if a whole upstream
    object was acquired under a range/shared class. Ranges that happen to
    cover a small file the plan genuinely requires as metadata are explained.
    """
    by_object: dict[str, dict[str, Any]] = {}
    unexplained = 0
    for record in records:
        origin = record["origin"]
        if record["kind"] == "whole_object":
            if record["requirement_class"] != "required_metadata":
                unexplained += record["length"]
            continue
        if record["kind"] != "byte_range":
            continue
        key = origin["source_object_digest"]
        entry = by_object.setdefault(key, {
            "source_object": origin["source_object"],
            "length": origin["source_object_length"],
            "covered": [],
        })
        entry["covered"].append((origin["byte_start"], origin["byte_end"]))
    for entry in by_object.values():
        position = 0
        complete = True
        for start, end in sorted(entry["covered"]):
            if start > position:
                complete = False
                break
            position = max(position, end)
        if complete and position >= entry["length"]:
            unexplained += entry["length"]
    return unexplained


def acquire_artifact(
    *,
    cache: NodeArtifactCache,
    source: Any,
    record: Mapping[str, Any],
    authorization: CoordinatorAuthority,
    participant_id: str,
    ledger: AcquisitionLedger,
    chunk_bytes: int = DEFAULT_CHUNK_BYTES,
) -> dict[str, Any]:
    """Acquire one required artifact.

    authorize -> cache lookup -> resume/fetch -> verify exact digest ->
    publish into the verified cache. Returns
    ``{"status": "CACHE_HIT" | "ACQUIRED" | "INTERRUPTED", ...}``.

    Interrupted transfers retain identity-bound partial state for a legal
    resume; every other failure fails closed and leaves no trusted state.
    """
    validate_artifact_record(record)
    authorization.check_acquisition(
        participant_id=participant_id, artifact_record=record, source_id=source.source_id)
    if cache.has_verified(record):
        ledger.record({"event": "CACHE_HIT", "participant_id": participant_id,
                       "artifact_id": record["artifact_id"],
                       "content_digest": record["content_digest"], "bytes": record["length"]})
        return {"status": "CACHE_HIT", "bytes": record["length"]}
    stale_state = cache.partial_state(record["artifact_id"])
    try:
        resumed_from = cache.resume_partial(record)
    except AcquisitionError:
        stale_bytes = stale_state["retained_bytes"] if stale_state else 0
        ledger.record({"event": "PARTIAL_DISCARDED", "participant_id": participant_id,
                       "artifact_id": record["artifact_id"],
                       "partial_staging_bytes": stale_bytes,
                       "reason": "PARTIAL_STATE_IDENTITY_MISMATCH"})
        resumed_from = 0
    if resumed_from:
        ledger.record({"event": "RESUME_REUSED_PREFIX", "participant_id": participant_id,
                       "artifact_id": record["artifact_id"], "bytes": resumed_from})
    else:
        cache.begin_partial(record)
    offset = resumed_from
    staged_partial_bytes = 0
    # byte_range artifacts live at an offset inside their upstream object:
    # artifact-relative positions map onto object-absolute byte positions.
    object_base = record["origin"]["byte_start"] if record["kind"] == "byte_range" else 0
    try:
        while offset < record["length"]:
            want = min(chunk_bytes, record["length"] - offset)
            data = source.read(record["origin"], object_base + offset, want)
            staged_partial_bytes += len(data)
            offset = cache.append_partial(record, data)
        cache.finish_partial(record)
    except TransferInterrupted as interrupted:
        if interrupted.partial:
            retained = cache.append_partial(record, interrupted.partial)
        else:
            state = cache.partial_state(record["artifact_id"])
            retained = state["retained_bytes"] if state else 0
        ledger.record({"event": "TRANSFER_INTERRUPTED", "participant_id": participant_id,
                       "artifact_id": record["artifact_id"],
                       "partial_staging_bytes": retained,
                       "reason": str(interrupted).split(":")[0]})
        return {"status": "INTERRUPTED", "retained_bytes": retained}
    except AcquisitionError as failure:
        cache.discard_partial(record["artifact_id"])
        ledger.record({"event": "INTEGRITY_FAILURE", "participant_id": participant_id,
                       "artifact_id": record["artifact_id"],
                       "attempted_bytes": record["length"],
                       "partial_staging_bytes": staged_partial_bytes,
                       "reason": str(failure).split(":")[0]})
        raise
    transferred = record["length"] - resumed_from
    ledger.record({"event": "ACQUIRED", "participant_id": participant_id,
                   "artifact_id": record["artifact_id"],
                   "content_digest": record["content_digest"],
                   "source_id": source.source_id, "bytes": transferred,
                   "resumed_from_bytes": resumed_from,
                   "partial_staging_bytes": staged_partial_bytes})
    return {"status": "ACQUIRED", "bytes": transferred}


# ---------------------------------------------------------------------------
# Whole-object acquisition guard used by callers that deliberately fetch a
# complete upstream object (none in the minimal proof; kept fail-closed).
# ---------------------------------------------------------------------------


def guard_full_object_acquisition(records: Sequence[Mapping[str, Any]]) -> None:
    """Raise when an acquisition set contains an unexplained whole-object dependency."""
    unexplained = _unexplained_full_object_bytes(records)
    if unexplained:
        raise _fail("UPSTREAM_OBJECT_FULLY_ACQUIRED_WITHOUT_DECLARATION",
                    f"{unexplained} bytes cover whole upstream objects")
