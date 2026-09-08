#!/usr/bin/env python3
"""Issue #117 accepted V5 qualification-subject reconstruction (fail-closed).

This module reconstructs the exact historical subject against which the
accepted V5 qualification (#110) was adjudicated, purely from byte-pinned
accepted historical evidence, and packages it as one accepted qualification
record for the generic qualification-applicability gate.

Independence rule (issue #117): the reconstruction must NOT call or
semantically depend on ``canonical_v5_candidate()``,
``GemmaDenseStrategy.legal_candidates()``, current candidate enumeration,
current planner selection, current #117 catalog construction, or the #117
synthetic fixture. This module imports only the shared digest/projection
conventions (``issue74_methodology``, ``issue99_artifact_core``,
``issue117_subject_identity``); it never imports the strategy, planner,
preflight, or proof modules. Current code may later COMPARE a freshly
constructed candidate against the reconstructed subject; it may not create
the subject from that candidate.

Evidence sources (all byte-pinned on accepted ``main``):
- ``docs/qualification/gemma4-12b-it-v5/manifests/physical-subject.json``
  (#109 freeze): model, revision, checkpoint authority, execution semantics.
- ``docs/qualification/gemma4-12b-it-v4-campaign-97/EXECUTION-AUTHORITY.json``
  (#97 freeze, unchanged by #110): chain topology — per-stage host, GPU UUID,
  and layer range — plus the reference path.
- ``docs/qualification/gemma4-12b-it-v2-campaign-81/preflight-applicability.json``
  (#81 preflight): per-GPU UUID -> node/index/product/compute-capability and
  the per-node runtime stack (torch/CUDA/driver/triton/flashinfer).
- ``docs/qualification/gemma4-12b-it-v4-campaign-97/PREFLIGHT-APPLICABILITY.json``
  (#97 preflight): independent cross-check of the runtime stack.
- ``docs/qualification/gemma4-12b-it-v5-campaign-110/b/holdout-adjudication.json``
  (#110 terminal): ``V5_QUALIFICATION_PASS`` disposition; the file's own
  SHA-256 IS the accepted terminal adjudication identity.
- ``docs/qualification/gemma4-12b-it-v5-campaign-110/b/TERMINAL-REPORT.md``
  (#110 terminal report): corroborates the runtime/backend identity line.
- ``docs/implementation/r6-successor-dense-full-integration-117/evidence/
  checkpoint-authority-provenance.json`` (PR #119 recovery): the
  representation identity — the qualified checkpoint object is the single
  ``model.safetensors`` file whose sha256 IS the checkpoint authority.

Naming conventions (machinery-local, value-neutral): the #117 subject field
names ``cu_id`` (``<node>/gpu-<index>``) and the representation token
``checkpoint-safetensors`` name facts that the historical evidence states in
its own vocabulary (per-GPU node+index; a single-file safetensors checkpoint
whose authority is the sha256 of that file's bytes). No convention invents
an identity fact.

Pure stdlib. Fails closed on any missing, drifted, contradictory, or
insufficient evidence.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Mapping

from issue74_methodology import canonical_json_bytes
from issue99_artifact_core import self_digest, validate_self_identity
from issue117_subject_identity import execution_equality_subject, subject_digest

SUBJECT_RECORD_SCHEMA = "inferswarm.issue117.accepted-v5-qualification-subject/1"
QUALIFICATION_RECORD_SCHEMA = "inferswarm.issue117.qualification-record/2"

#: The accepted terminal adjudication identity: the SHA-256 of the terminal
#: ``holdout-adjudication.json`` itself (the value already frozen by the
#: #117 applicability barrier).
ACCEPTED_TERMINAL_ADJUDICATION_SHA256 = (
    "f024f8b3394686ff098459b657ce6dba62d7f190972663e3929ef4a574ab7a70")
ACCEPTED_TERMINAL_DISPOSITION = "V5_QUALIFICATION_PASS"

ACCEPTED_RECORD_ID = "inferswarm.issue117.accepted-v5-qualification/1"

#: Byte-pinned accepted historical evidence this reconstruction consumes.
#: Every pin is on accepted ``main`` ``753e4613...`` (physical-subject,
#: execution authority, v2 preflight, and both terminal files are the same
#: pins the #117 applicability barrier already freezes; the #97 preflight
#: and the PR #119 provenance package are pinned here additively).
ACCEPTED_SUBJECT_EVIDENCE_FILES: dict[str, str] = {
    "docs/qualification/gemma4-12b-it-v5/manifests/physical-subject.json":
        "8b840eed2b858623be6abd1bfbac1bc7f3bf3637ac7acfa383ce039137226aee",
    "docs/qualification/gemma4-12b-it-v4-campaign-97/EXECUTION-AUTHORITY.json":
        "bb6a084fb448f8804c268273d222ece7ed50a2d4da03413edfab4ae9e136b585",
    "docs/qualification/gemma4-12b-it-v2-campaign-81/preflight-applicability.json":
        "f2c3590da2a16a11889bbb164df73c9aee334453b6bccf0ead27a9c3265b9313",
    "docs/qualification/gemma4-12b-it-v4-campaign-97/PREFLIGHT-APPLICABILITY.json":
        "71c869afbb8fd136527c2cb5a3d70718740c4839aa25f6e696b27d3a93d261d3",
    "docs/qualification/gemma4-12b-it-v5-campaign-110/b/holdout-adjudication.json":
        ACCEPTED_TERMINAL_ADJUDICATION_SHA256,
    "docs/qualification/gemma4-12b-it-v5-campaign-110/b/TERMINAL-REPORT.md":
        "d7f5e4954bded41e03208018c4887abb40c301f78d115e233104f265ac9882c6",
    "docs/implementation/r6-successor-dense-full-integration-117"
    "/evidence/checkpoint-authority-provenance.json":
        "b6b5acd28f9c41d2ee080afbad06edc7b6a4cd7dc49df64f062cddfe693b67f8",
}

#: Retained committed record (convenience copy; authority is always
#: re-derived from the pinned evidence above, never trusted from disk).
ACCEPTED_SUBJECT_RECORD_RELATIVE_PATH = (
    "docs/implementation/r6-successor-dense-full-integration-117"
    "/evidence/accepted-v5-qualification-subject.json")

#: The #117 representation token naming the historically established
#: representation: a single-file safetensors checkpoint whose authority is
#: the sha256 of that file's complete bytes (PR #119 recovery,
#: ``derivation_rule.input``; corroborated by FreeToken a68ed8d's first
#: committed record "native BF16 single safetensors").
REPRESENTATION_TOKEN = "checkpoint-safetensors"

#: Backend keys of the execution-equality projection, and the historical
#: field each is loaded from (v2 stack vocabulary -> projection vocabulary).
BACKEND_KEY_SOURCES = (
    ("torch", "torch"),
    ("cuda_runtime", "cuda_runtime"),
    ("nvidia_driver", "driver"),
    ("triton", "triton"),
    ("flashinfer", "flashinfer"),
)


class SubjectReconstructionError(RuntimeError):
    """Fail-closed accepted-subject reconstruction error."""


def _sha256_file(path: Path) -> str:
    import hashlib
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_pinned(root: Path, relative: str) -> dict[str, Any]:
    path = root / relative
    if not path.is_file():
        raise SubjectReconstructionError(
            f"accepted subject evidence missing: {relative}")
    observed = _sha256_file(path)
    expected = ACCEPTED_SUBJECT_EVIDENCE_FILES[relative]
    if observed != expected:
        raise SubjectReconstructionError(
            f"accepted subject evidence drifted: {relative} "
            f"expected {expected} observed {observed}")
    document = json.loads(path.read_text())
    if not isinstance(document, dict):
        raise SubjectReconstructionError(f"{relative}: not a JSON object")
    return document


def _load_pinned_text(root: Path, relative: str) -> str:
    """Load a pinned non-JSON evidence file, verifying its exact bytes first.

    Same fail-closed contract as ``_load_pinned``: the file must exist, its
    SHA-256 over exact bytes must equal the declared pin in
    ``ACCEPTED_SUBJECT_EVIDENCE_FILES`` (never a semantic-string check),
    and only then is the text decoded. A modified file that still happens
    to contain the expected strings fails on byte drift.
    """
    path = root / relative
    if not path.is_file():
        raise SubjectReconstructionError(
            f"accepted subject evidence missing: {relative}")
    observed = _sha256_file(path)
    expected = ACCEPTED_SUBJECT_EVIDENCE_FILES[relative]
    if observed != expected:
        raise SubjectReconstructionError(
            f"accepted subject evidence drifted: {relative} "
            f"expected {expected} observed {observed}")
    try:
        return path.read_text()
    except UnicodeDecodeError as error:
        raise SubjectReconstructionError(
            f"accepted subject evidence is not text: {relative}: {error}") from error


def _require(mapping: Mapping[str, Any], key: str, source: str) -> Any:
    if key not in mapping:
        raise SubjectReconstructionError(f"{source}: missing {key!r}")
    return mapping[key]


def _layer_range(layers: str, source: str) -> tuple[int, int]:
    match = re.fullmatch(r"\[(\d+),\s*(\d+)\)", str(layers).strip())
    if not match:
        raise SubjectReconstructionError(
            f"{source}: unparsable layer range {layers!r}")
    start, end = int(match.group(1)), int(match.group(2))
    if not (0 <= start < end):
        raise SubjectReconstructionError(
            f"{source}: non-increasing layer range {layers!r}")
    return start, end


def reconstruct_accepted_v5_subject(
        root: Path | None = None) -> dict[str, Any]:
    """Reconstruct the accepted V5 execution-equality subject from evidence.

    Reads only byte-pinned accepted historical files. Fails closed on any
    drift, contradiction, or insufficient field. The returned dict is the
    complete qualification subject in the shared #117 subject vocabulary
    (``issue117_subject_identity`` projection inputs).
    """
    root = Path(root if root is not None else Path(__file__).resolve().parents[1])

    physical_subject = _load_pinned(
        root, "docs/qualification/gemma4-12b-it-v5/manifests/physical-subject.json")
    execution_authority = _load_pinned(
        root, "docs/qualification/gemma4-12b-it-v4-campaign-97/EXECUTION-AUTHORITY.json")
    v2_preflight = _load_pinned(
        root, "docs/qualification/gemma4-12b-it-v2-campaign-81/preflight-applicability.json")
    v4_preflight = _load_pinned(
        root, "docs/qualification/gemma4-12b-it-v4-campaign-97/PREFLIGHT-APPLICABILITY.json")
    adjudication = _load_pinned(
        root, "docs/qualification/gemma4-12b-it-v5-campaign-110/b/holdout-adjudication.json")
    terminal_report_text = _load_pinned_text(
        root, "docs/qualification/gemma4-12b-it-v5-campaign-110/b/"
              "TERMINAL-REPORT.md")
    authority_provenance = _load_pinned(
        root, "docs/implementation/r6-successor-dense-full-integration-117"
              "/evidence/checkpoint-authority-provenance.json")

    # -- terminal adjudication identity ------------------------------------
    if adjudication.get("terminal") != ACCEPTED_TERMINAL_DISPOSITION:
        raise SubjectReconstructionError(
            "terminal adjudication does not carry the accepted disposition "
            f"({adjudication.get('terminal')!r})")

    # -- model / checkpoint authority / execution semantics -----------------
    subject: dict[str, Any] = {
        "model_id": _require(physical_subject, "model", "physical-subject"),
        "revision": _require(physical_subject, "revision", "physical-subject"),
        "checkpoint_authority_sha256": _require(
            physical_subject, "checkpoint_sha256", "physical-subject"),
        "execution": _require(physical_subject, "execution", "physical-subject"),
    }
    # representation: the qualified checkpoint object is the single
    # model.safetensors file; its sha256 IS the authority (PR #119 rule).
    derivation = authority_provenance.get("derivation_rule", {})
    rule_input = str(derivation.get("input", ""))
    if "model.safetensors" not in rule_input \
            or authority_provenance.get("subject", {}).get(
                "checkpoint_authority_sha256") != subject["checkpoint_authority_sha256"] \
            or authority_provenance.get("subject", {}).get("revision") != subject["revision"]:
        raise SubjectReconstructionError(
            "checkpoint-authority provenance does not bind the accepted "
            "subject identity and the single-file safetensors rule")
    subject["representation"] = REPRESENTATION_TOKEN

    # -- Compute Unit identities / stage structure --------------------------
    uuid_index: dict[str, tuple[str, int, str, str]] = {}
    nodes = _require(v2_preflight, "nodes", "v2-preflight")
    for node, record in nodes.items():
        for gpu in record.get("gpu", []):
            uuid = gpu.get("uuid")
            if not isinstance(uuid, str) or uuid in uuid_index:
                raise SubjectReconstructionError(
                    "v2 preflight carries a missing/duplicate GPU UUID")
            index = gpu.get("index")
            if index is None:
                # single-GPU node (the reference): index 0 by topology record
                if len(record.get("gpu", [])) != 1:
                    raise SubjectReconstructionError(
                        f"v2 preflight GPU record on {node} has no index")
                index = 0
            uuid_index[uuid] = (node, int(index),
                                str(gpu.get("product")),
                                str(gpu.get("compute_capability")))

    topology = _require(execution_authority, "topology", "execution-authority")
    stages = []
    for stage in topology.get("candidate", []):
        uuid = _require(stage, "gpu_uuid", "execution-authority")
        if uuid not in uuid_index:
            raise SubjectReconstructionError(
                f"execution-authority stage GPU {uuid!r} has no retained "
                "identity in the v2 preflight")
        node, gpu_index, _product, _cc = uuid_index[uuid]
        if _require(stage, "host", "execution-authority") != node:
            raise SubjectReconstructionError(
                f"execution-authority stage host {stage['host']!r} != the "
                f"v2-preflight node {node!r} for UUID {uuid!r}")
        start, end = _layer_range(
            _require(stage, "layers", "execution-authority"),
            "execution-authority")
        stages.append({
            "cu_id": f"{node}/gpu-{gpu_index}",
            "node": node,
            "layer_start": start,
            "layer_end": end,
        })
    if not stages:
        raise SubjectReconstructionError("execution authority has no candidate stages")
    covered = sorted((stage["layer_start"], stage["layer_end"]) for stage in stages)
    if covered[0][0] != 0 or any(
            covered[i][1] != covered[i + 1][0] for i in range(len(covered) - 1)):
        raise SubjectReconstructionError(
            f"stage layer ranges are not a contiguous cover: {covered}")
    layer_count = covered[-1][1]
    subject["layer_count"] = layer_count
    subject["stage_structure"] = stages

    # -- backend / runtime identity ------------------------------------------
    stacks = [record.get("stack") for record in nodes.values()]
    if not stacks or any(not isinstance(stack, dict) for stack in stacks):
        raise SubjectReconstructionError("v2 preflight has no usable stacks")
    backend: dict[str, str] = {}
    for projection_key, historical_key in BACKEND_KEY_SOURCES:
        values = {str(stack.get(historical_key)) for stack in stacks}
        if len(values) != 1 or "None" in values:
            raise SubjectReconstructionError(
                f"v2 preflight runtime field {historical_key!r} is missing "
                f"or disagrees across nodes: {sorted(values)}")
        backend[projection_key] = values.pop()
    # independent cross-check: the #97 preflight software record (a separate
    # campaign document) must agree on every field it records.
    software = _require(v4_preflight, "software", "v4-preflight")
    for key in ("torch", "cuda_runtime", "nvidia_driver", "triton"):
        if str(software.get(key)) != backend[key]:
            raise SubjectReconstructionError(
                f"v4 preflight software field {key!r} ({software.get(key)!r}) "
                f"disagrees with the v2 stack ({backend[key]!r})")
    # corroborate the full five-field line (incl. flashinfer) in the
    # terminal report prose.
    for key, value in backend.items():
        if value not in terminal_report_text:
            raise SubjectReconstructionError(
                f"terminal report does not corroborate runtime identity "
                f"{key}={value!r}")
    subject["backend"] = backend
    return subject


def accepted_v5_qualification_record(
        root: Path | None = None) -> dict[str, Any]:
    """Build the accepted V5 qualification record from pinned evidence.

    The record follows the shared qualification-record convention so the
    generic planner gate can consume it; its authority binds the accepted
    terminal disposition and the exact terminal adjudication SHA-256 (the
    pinned ``holdout-adjudication.json`` file's own hash). Constructed here
    from evidence only — never from candidate machinery.
    """
    root = Path(root if root is not None else Path(__file__).resolve().parents[1])
    subject = reconstruct_accepted_v5_subject(root)
    record = {
        "schema": QUALIFICATION_RECORD_SCHEMA,
        "qualification_record_id": ACCEPTED_RECORD_ID,
        "scope": "accepted-authority",
        "authority": {
            "terminal_disposition": ACCEPTED_TERMINAL_DISPOSITION,
            "terminal_adjudication_sha256": ACCEPTED_TERMINAL_ADJUDICATION_SHA256,
            "accepted_v5_methodology": "bc6f0ec657d025702d5928771bf8f51aa563a8be",
            "accepted_freetoken_calibration_producer":
                "7e5c852163afd9aadfccc406be267e8d060e79ef",
            "accepted_freetoken_holdout_producer":
                "924cd22ea081f6d4ed471016faf01d427fc5b0d2",
            "reconstruction": "scripts/issue117_accepted_subject.py",
        },
        "qualification_subject": subject,
    }
    record["qualification_subject_digest"] = subject_digest(subject)
    record["record_digest"] = self_digest(record, identity_field="record_digest")
    return record


def build_subject_record_document(root: Path | None = None) -> dict[str, Any]:
    """Build the retained accepted-subject provenance record.

    Contains the reconstructed subject, its mechanically derived digest,
    per-field source evidence (path + SHA-256 + JSON path), the projection
    convention, explicit unavailable fields (none), and the independence
    statement. This is the committed convenience record; the loader below
    re-derives everything and never trusts it.
    """
    root = Path(root if root is not None else Path(__file__).resolve().parents[1])
    subject = reconstruct_accepted_v5_subject(root)
    record = accepted_v5_qualification_record(root)

    field_provenance = {
        "model_id": [{
            "source": "docs/qualification/gemma4-12b-it-v5/manifests/physical-subject.json",
            "sha256": ACCEPTED_SUBJECT_EVIDENCE_FILES[
                "docs/qualification/gemma4-12b-it-v5/manifests/physical-subject.json"],
            "json_path": "$.model"}],
        "revision": [{
            "source": "docs/qualification/gemma4-12b-it-v5/manifests/physical-subject.json",
            "sha256": ACCEPTED_SUBJECT_EVIDENCE_FILES[
                "docs/qualification/gemma4-12b-it-v5/manifests/physical-subject.json"],
            "json_path": "$.revision"}],
        "checkpoint_authority_sha256": [
            {"source": "docs/qualification/gemma4-12b-it-v5/manifests/physical-subject.json",
             "sha256": ACCEPTED_SUBJECT_EVIDENCE_FILES[
                 "docs/qualification/gemma4-12b-it-v5/manifests/physical-subject.json"],
             "json_path": "$.checkpoint_sha256"},
            {"source": "docs/implementation/r6-successor-dense-full-integration-117"
                       "/evidence/checkpoint-authority-provenance.json",
             "sha256": ACCEPTED_SUBJECT_EVIDENCE_FILES[
                 "docs/implementation/r6-successor-dense-full-integration-117"
                 "/evidence/checkpoint-authority-provenance.json"],
             "json_path": "$.derivation_rule (sha256 of model.safetensors bytes; "
                          "PR #119 recovery)"}],
        "representation": [{
            "source": "docs/implementation/r6-successor-dense-full-integration-117"
                      "/evidence/checkpoint-authority-provenance.json",
            "sha256": ACCEPTED_SUBJECT_EVIDENCE_FILES[
                "docs/implementation/r6-successor-dense-full-integration-117"
                "/evidence/checkpoint-authority-provenance.json"],
            "json_path": "$.derivation_rule.input",
            "note": "the token 'checkpoint-safetensors' names the historically "
                    "established representation: the single-file safetensors "
                    "checkpoint whose sha256 is the authority"}],
        "execution": [{
            "source": "docs/qualification/gemma4-12b-it-v5/manifests/physical-subject.json",
            "sha256": ACCEPTED_SUBJECT_EVIDENCE_FILES[
                "docs/qualification/gemma4-12b-it-v5/manifests/physical-subject.json"],
            "json_path": "$.execution",
            "note": "covers precision (native BF16), attention/backend mode "
                    "(Triton attention), and replay/chunk geometry "
                    "(one <=64-row replay chunk)"}],
        "backend.torch": [{
            "source": "docs/qualification/gemma4-12b-it-v2-campaign-81/preflight-applicability.json",
            "sha256": ACCEPTED_SUBJECT_EVIDENCE_FILES[
                "docs/qualification/gemma4-12b-it-v2-campaign-81/preflight-applicability.json"],
            "json_path": "$.nodes.*.stack.torch",
            "cross_check": "docs/qualification/gemma4-12b-it-v4-campaign-97/"
                           "PREFLIGHT-APPLICABILITY.json $.software.torch"}],
        "backend.cuda_runtime": [{
            "source": "docs/qualification/gemma4-12b-it-v2-campaign-81/preflight-applicability.json",
            "sha256": ACCEPTED_SUBJECT_EVIDENCE_FILES[
                "docs/qualification/gemma4-12b-it-v2-campaign-81/preflight-applicability.json"],
            "json_path": "$.nodes.*.stack.cuda_runtime",
            "cross_check": "docs/qualification/gemma4-12b-it-v4-campaign-97/"
                           "PREFLIGHT-APPLICABILITY.json $.software.cuda_runtime"}],
        "backend.nvidia_driver": [{
            "source": "docs/qualification/gemma4-12b-it-v2-campaign-81/preflight-applicability.json",
            "sha256": ACCEPTED_SUBJECT_EVIDENCE_FILES[
                "docs/qualification/gemma4-12b-it-v2-campaign-81/preflight-applicability.json"],
            "json_path": "$.nodes.*.stack.driver",
            "cross_check": "docs/qualification/gemma4-12b-it-v4-campaign-97/"
                           "PREFLIGHT-APPLICABILITY.json $.software.nvidia_driver"}],
        "backend.triton": [{
            "source": "docs/qualification/gemma4-12b-it-v2-campaign-81/preflight-applicability.json",
            "sha256": ACCEPTED_SUBJECT_EVIDENCE_FILES[
                "docs/qualification/gemma4-12b-it-v2-campaign-81/preflight-applicability.json"],
            "json_path": "$.nodes.*.stack.triton",
            "cross_check": "docs/qualification/gemma4-12b-it-v4-campaign-97/"
                           "PREFLIGHT-APPLICABILITY.json $.software.triton"}],
        "backend.flashinfer": [{
            "source": "docs/qualification/gemma4-12b-it-v2-campaign-81/preflight-applicability.json",
            "sha256": ACCEPTED_SUBJECT_EVIDENCE_FILES[
                "docs/qualification/gemma4-12b-it-v2-campaign-81/preflight-applicability.json"],
            "json_path": "$.nodes.*.stack.flashinfer",
            "cross_check": "docs/qualification/gemma4-12b-it-v5-campaign-110/b/"
                           "TERMINAL-REPORT.md runtime identity line"}],
        "layer_count": [{
            "source": "docs/qualification/gemma4-12b-it-v4-campaign-97/EXECUTION-AUTHORITY.json",
            "sha256": ACCEPTED_SUBJECT_EVIDENCE_FILES[
                "docs/qualification/gemma4-12b-it-v4-campaign-97/EXECUTION-AUTHORITY.json"],
            "json_path": "$.topology.candidate[*].layers (contiguous-cover upper bound)",
            "note": "corroborated by the producer's frozen chain plan "
                    "(number_of_layers 48, block ranges [0,16)/[16,32)/[32,48))"}],
        "stage_structure": [{
            "source": "docs/qualification/gemma4-12b-it-v4-campaign-97/EXECUTION-AUTHORITY.json",
            "sha256": ACCEPTED_SUBJECT_EVIDENCE_FILES[
                "docs/qualification/gemma4-12b-it-v4-campaign-97/EXECUTION-AUTHORITY.json"],
            "json_path": "$.topology.candidate[*] (host, gpu_uuid, layers)",
            "cross_check": "docs/qualification/gemma4-12b-it-v2-campaign-81/"
                           "preflight-applicability.json $.nodes.*.gpu (uuid -> "
                           "node/index/product/compute_capability)"}],
    }

    document = {
        "schema": SUBJECT_RECORD_SCHEMA,
        "classification": "V5_QUALIFICATION_SUBJECT_PROVENANCE_RECOVERED",
        "recovered_by": "forensic reconstruction commissioned by the maintainer, 2026-09-07",
        "terminal_adjudication": {
            "disposition": ACCEPTED_TERMINAL_DISPOSITION,
            "adjudication_sha256": ACCEPTED_TERMINAL_ADJUDICATION_SHA256,
            "source": "docs/qualification/gemma4-12b-it-v5-campaign-110/b/holdout-adjudication.json",
            "note": "the adjudication SHA-256 is the terminal file's own byte hash",
        },
        "projection_convention": {
            "module": "scripts/issue117_subject_identity.py",
            "machinery_local_subject_keys": ["catalog_content_digest"],
            "rule": "sha256 over canonical_json_bytes(subject minus "
                    "machinery-local keys)",
        },
        "naming_conventions": {
            "cu_id": "'<node>/gpu-<index>' names the per-GPU node+index facts "
                     "retained by the v2 preflight",
            "representation": "the token 'checkpoint-safetensors' names the "
                              "single-file safetensors representation whose "
                              "authority rule PR #119 recovered",
        },
        "qualification_subject": subject,
        "qualification_subject_digest": record["qualification_subject_digest"],
        "accepted_qualification_record": record,
        "field_provenance": field_provenance,
        "unavailable_fields": [],
        "independence": {
            "imports": ["issue74_methodology", "issue99_artifact_core",
                        "issue117_subject_identity"],
            "forbidden_not_imported": [
                "issue117_gemma_strategy", "issue117_planner",
                "issue117_preflight", "issue117_proof",
                "issue117_integration_fixture"],
            "statement": "the subject is reconstructed only from byte-pinned "
                         "accepted historical evidence; current candidate "
                         "construction, planner selection, catalog "
                         "construction, and the synthetic fixture are not "
                         "inputs",
        },
    }
    document["record_digest"] = self_digest(document, identity_field="record_digest")
    return document


def load_accepted_v5_qualification_record(
        root: Path | None = None) -> dict[str, Any]:
    """Load and fully validate the accepted V5 qualification record.

    Authority is re-derived from the pinned evidence on every call; the
    committed retained record (if present) must agree byte-semantically with
    the re-derivation, and no duplicate/conflicting retained record may
    exist. Fails closed otherwise.
    """
    root = Path(root if root is not None else Path(__file__).resolve().parents[1])
    derived = accepted_v5_qualification_record(root)

    retained_path = root / ACCEPTED_SUBJECT_RECORD_RELATIVE_PATH
    if retained_path.is_file():
        try:
            retained = json.loads(retained_path.read_text())
        except ValueError as error:
            raise SubjectReconstructionError(
                f"retained accepted-subject record is unreadable: {error}")
        validate_self_identity(dict(retained), identity_field="record_digest")
        if retained.get("qualification_subject_digest") \
                != derived["qualification_subject_digest"] \
                or execution_equality_subject(
                    retained.get("qualification_subject", {})) \
                != execution_equality_subject(derived["qualification_subject"]):
            raise SubjectReconstructionError(
                "retained accepted-subject record disagrees with the "
                "evidence-derived subject (tampered or stale record)")

    # duplicate/conflicting accepted-subject records fail closed: exactly
    # one retained file may carry this record's schema in the evidence tree.
    evidence_root = root / "docs/implementation" / \
        "r6-successor-dense-full-integration-117" / "evidence"
    duplicates = []
    if evidence_root.is_dir():
        payload = canonical_json_bytes({
            key: derived[key] for key in
            ("qualification_subject", "qualification_subject_digest")})
        for candidate in sorted(evidence_root.glob("accepted-v5-qualification-subject*.json")):
            if candidate == retained_path:
                continue
            try:
                other = json.loads(candidate.read_text())
            except ValueError:
                duplicates.append(candidate.name)
                continue
            if other.get("schema") in (SUBJECT_RECORD_SCHEMA, QUALIFICATION_RECORD_SCHEMA) \
                    or canonical_json_bytes({
                        key: other.get(key) for key in
                        ("qualification_subject", "qualification_subject_digest")}) == payload:
                duplicates.append(candidate.name)
    if duplicates:
        raise SubjectReconstructionError(
            f"duplicate/conflicting accepted qualification records: {duplicates}")
    return derived


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path,
                        default=Path(__file__).resolve().parents[1])
    parser.add_argument("--write-record", action="store_true",
                        help="write the retained accepted-subject record")
    args = parser.parse_args(argv)
    if args.write_record:
        document = build_subject_record_document(args.root)
        target = args.root / ACCEPTED_SUBJECT_RECORD_RELATIVE_PATH
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(canonical_json_bytes(document) + b"\n")
        print(f"wrote {ACCEPTED_SUBJECT_RECORD_RELATIVE_PATH}")
    record = load_accepted_v5_qualification_record(args.root)
    print(f"accepted subject digest: {record['qualification_subject_digest']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
