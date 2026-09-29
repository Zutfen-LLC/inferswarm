#!/usr/bin/env python3
"""Issue #250 (R8-I3B) bounded physical diagnostic producer.

DIAGNOSTIC-ONLY. Correction pass 2 (maintainer NO-GO comment
5840630050, blocker 1): this module is the physical execution path
PR #251 previously lacked. It reuses the accepted Issue #248
producer architecture (scripts/issue248_physical.py) — same
authority/custody model, same raw identity/health helpers
(issue248_identity / issue248_health, the accepted implementations) —
adapted to Issue #250's frozen discriminator geometry
(scripts/issue250_diagnostic.py): four arms, namespace<->arm exact
binding, CPU-only inheritance for B and C, retained-byte terminal
reduction with the sequential A->B->C->D reachability law.

CORRECTION PASS 6 (METHODOLOGY-AMENDMENT-003): the retained failed
Arm-A v1 unit exposed the producer timeout defect (global
HTTP_TIMEOUT_S = 1200 vs a ~1368 s legitimate CPU-only case-3072
prefill at the retained 2.25 tok/s). The global constant is retired:
every request now runs under the frozen per-condition
TIMEOUT-BUDGET AUTHORITY (scripts/issue250_timeout.py), receipts
retain the budget + derivation inputs, the Arm-C serial regime moved
behind the separate d250-arm-c2 maintainer gate (C1
reduced-parallelism probe is the bounded automatic discriminator),
and canonical execution is bound to the fresh evidence generation
EVIDENCE_GENERATION (gen-2-pass6) — the read-only v1 generation
(gen-1-v1-timeout-defect) is rejected as a write target and can
never mix into a canonical reduction.

Every entrypoint gates FIRST and only then performs any work:
no qualification path exists here, comparator/2 methodology is
untouched, no threshold exists, no holdout access is possible, and
the diagnostic terminal is derived by the offline reducer from
retained bytes only.

Production path per unit (fresh-process units):

  live exact-head dispatch authority (early)
  -> namespace/arm exact binding
  -> frozen arm/unit plan membership
  -> exact clean local head
  -> fixture authority (ladder sha)
  -> campaign opening model attestation + per-unit stat witness
  -> accepted binary authority (sha256)
  -> frozen request contract
  -> fresh raw subject identity (pre)
  -> live exact-head dispatch authority (final; two-pass binding)
  -> physical launch (one fresh llama-server per unit)
  -> identity postcheck
  -> append-only raw custody (rows, response, log, health)
  -> unit receipt

Same-process Arm-B lifecycle (correction pass 2: five nominal unit
records launched as five separate processes do NOT satisfy Arm B):

  per-request authority revalidation + all fresh-unit gates
  -> ONE server launch (CPU-only `-dev none`)
  -> slot 3 pinned via id_slot request field
  -> 5 sequential requests to that SAME PID/runtime, each with
     cache_prompt=false full-recompute proof retained from the server
     log (slot-selected-by-id line, prompt-eval 3077-token line,
     graphs-reused count)
  -> per-request rows/responses/log slices retained
  -> ONE shared process identity (single PID bound to every request)
  -> teardown after the arm population

There is NO authority parameter anywhere: dispatch authority always
comes from a mandatory live fetch (tests inject
``revalidate_authority``; production resolves the real fetcher in
issue250_diagnostic-validated form below).
"""
from __future__ import annotations

import hashlib
import copy
import json
import os
import re
import base64
import signal
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import issue250_diagnostic as D
import issue250_timeout as TB
import issue248_health as H
import issue248_identity as I

# ---------------------------------------------------------------------------
# FROZEN EVIDENCE GENERATION (correction pass 6, AMENDMENT-003). The
# failed v1 tree is historical DEFECT evidence: read-only, never a
# canonical write target, never mixable into a canonical reduction.
# ---------------------------------------------------------------------------
EVIDENCE_GENERATION = "gen-2-pass6"
RETIRED_EVIDENCE_GENERATIONS = frozenset({
    "gen-1-v1-timeout-defect",       # the retained failed Arm-A v1 run
    "gen-1", "v1", "gen-1-v1",       # lexical near-misses, refused too
})
RETIRED_V1_EVIDENCE_ROOT = TB.V1_EVIDENCE_ROOT


def validate_evidence_generation(root: Path) -> str:
    """Fail-closed generation binding for a canonical evidence root.

    Refuses: the retired v1 generation paths/identifiers (the defect
    record is immutable), symlinked roots, and — critically — any
    root that already carries a foreign generation marker. Returns
    the canonical generation this producer writes.
    """
    root = Path(root)
    if root.is_symlink():
        raise PhysicalDiagnosticError(
            "canonical evidence root may not be a symlink")
    resolved = str(root)
    for marker in RETIRED_EVIDENCE_GENERATIONS:
        if f"/{marker}" in resolved or resolved.endswith(f"-{marker}"):
            raise PhysicalDiagnosticError(
                f"refusing retired v1 evidence generation {marker!r} as "
                f"a canonical write target (read-only defect record): "
                f"{resolved}")
    marker_path = root / "evidence-generation.json"
    if marker_path.is_symlink():
        raise PhysicalDiagnosticError(
            "generation marker is a symlink")
    if marker_path.is_file():
        try:
            doc = json.loads(marker_path.read_bytes())
        except (OSError, json.JSONDecodeError) as exc:
            raise PhysicalDiagnosticError(
                f"generation marker unreadable: {exc}") from exc
        gen = doc.get("generation") if isinstance(doc, dict) else None
        if gen != EVIDENCE_GENERATION:
            raise PhysicalDiagnosticError(
                f"evidence root belongs to generation {gen!r}; this "
                f"producer writes only {EVIDENCE_GENERATION!r} "
                "(no mixing across generations)")
    return EVIDENCE_GENERATION


def write_generation_marker(evidence_root: Path) -> dict[str, Any]:
    """Retain the canonical generation marker (append-only, once)."""
    root = Path(evidence_root)
    if root.is_symlink() or not root.is_dir():
        raise PhysicalDiagnosticError(
            f"evidence root missing: {root}")
    marker = root / "evidence-generation.json"
    if marker.exists() or marker.is_symlink():
        raise PhysicalDiagnosticError(
            f"generation marker already retained (append-only): {marker}")
    doc = {
        "schema": "inferswarm.issue250.evidence-generation/1",
        "generation": EVIDENCE_GENERATION,
        "predecessor_generation": TB.V1_EVIDENCE_GENERATION,
        "predecessor_disposition": (
            "retained read-only as the timeout-defect record; never a "
            "canonical reduction input"),
        "predecessor_root": TB.V1_EVIDENCE_ROOT,
        "created_by": "METHODOLOGY-AMENDMENT-003",
    }
    _write_json(marker, doc)
    return doc


def retain_cost_planning_record(evidence_root: Path) -> dict[str, Any]:
    """Retain the frozen prospective cost-planning record (once)."""
    root = Path(evidence_root)
    target = root / "cost-planning-record.json"
    if target.exists() or target.is_symlink():
        raise PhysicalDiagnosticError(
            f"cost planning record already retained (append-only): "
            f"{target}")
    doc = TB.canonical_cost_planning_record()
    if doc["evidence_generation"] != EVIDENCE_GENERATION:
        raise PhysicalDiagnosticError("cost record generation differs from producer")
    _write_json(target, doc)
    return doc


def _unit_cost_condition(unit: dict[str, Any], arm: str) -> str:
    """Map frozen execution context, not caller cost, to the cost entry."""
    condition = TB.unit_condition(unit)
    if arm == "B-process-init" and condition == "arm-a-cpu-only":
        return "arm-b-fresh"
    if arm == "C-cpu-threads" and condition == "arm-a-cpu-only":
        return "arm-c-default"
    return condition


def _retained_cost_verdict(evidence_root: Path, condition: str,
                           namespace: str, arm: str) -> dict[str, Any]:
    """Authenticate canonical prospective cost; this does not admit spend."""
    path = Path(evidence_root) / "cost-planning-record.json"
    if path.is_symlink() or not path.is_file():
        raise PhysicalDiagnosticError("retained cost planning record missing")
    try:
        record = json.loads(path.read_bytes())
    except (OSError, ValueError) as exc:
        raise PhysicalDiagnosticError("retained cost planning record unreadable") from exc
    verdict = TB.evaluate_cost_gate(condition, record)
    if (verdict["namespace"], verdict["arm"]) != (namespace, arm):
        raise PhysicalDiagnosticError(
            "cost planning condition is not bound to this dispatch")
    return verdict


def _admit_retained_cost(evidence_root: Path, condition: str,
                         namespace: str, arm: str, *,
                         c2_gate_authorized: bool = False) -> dict[str, Any]:
    """Admit over-ceiling spend only after the separate C2 proof closes."""
    verdict = _retained_cost_verdict(evidence_root, condition, namespace, arm)
    if verdict["over_cost_ceiling"] and not (
            c2_gate_authorized and condition == "arm-c2-serial"
            and namespace == D.C2_SERIAL_NAMESPACE
            and arm == D.ARM_C2_NAME):
        raise PhysicalDiagnosticError(
            "cost planning condition exceeds the ceiling without "
            "dedicated verified C2 authorization")
    # Conditional B/D dispositions are NOT auto-dispatches. The live
    # exact-head per-arm dispatch AND producer's retained-row sequential
    # reachability gates still have to pass before any physical launch.
    return verdict


UNIT_SCHEMA = "inferswarm.issue250.diagnostic-unit/1"
LIFECYCLE_SCHEMA = "inferswarm.issue250.same-process-lifecycle/1"
REDUCTION_SCHEMA = "inferswarm.issue250.diagnostic-reduction/2"
TERMINAL_SCHEMA = "inferswarm.issue250.terminal/1"
MODEL_ATTESTATION_OPEN_SCHEMA = (
    "inferswarm.issue250.model-attestation-open/1")
MODEL_ATTESTATION_CLOSE_SCHEMA = (
    "inferswarm.issue250.model-attestation-close/1")
MODEL_ATTESTATION_OPEN_NAME = "model-attestation-open.json"
MODEL_ATTESTATION_CLOSE_NAME = "model-attestation-close.json"
WITNESS_STAT_KEYS = ("bytes", "device", "inode", "mtime_ns", "ctime_ns")

PORT = 19000  # accepted arm-B reference port (unchanged)
ARM = "B"     # every #250 unit executes on the accepted reference arm
SERVER_CTX_SIZE = 8192
SERVER_BATCH_SIZE = 512
SERVER_READY_TIMEOUT_S = 1800
# CORRECTION PASS 6 (AMENDMENT-003): the GLOBAL request timeout is
# RETIRED. The old frozen constant HTTP_TIMEOUT_S = 1200 predates
# CPU-only execution and killed a legitimate Arm-A case-3072 prefill
# at 83% (retained v1 server.log: 2.25 tok/s, cancel at t = 1143.45 s).
# Request deadlines now come ONLY from the frozen per-condition
# TIMEOUT-BUDGET AUTHORITY (issue250_timeout.request_timeout_budget,
# mechanically bound to the unit plan; receipts retain budget +
# derivation inputs). No global constant exists anymore; the defect
# value is retained ONLY as the timeout module's defect record
# (issue250_timeout.DEFECT_HTTP_TIMEOUT_S / LEGACY_FIXED_TIMEOUT_S).
assert TB.DEFECT_HTTP_TIMEOUT_S == 1200  # defect record stays pinned

# Same-process reset-evidence grammar. CORRECTION PASS 3: the old
# unanchored SLOT_BY_ID_RE / PROMPT_EVAL_RE (any slot-3 line + any
# 3077-token prompt-eval line anywhere in the slice) admitted delayed
# prior-task evidence; superseded by the task-bound state machine at
# SELECTION_BY_ID_RE / LAUNCH_TASK_RE / PROMPT_EVAL_TASK_RE below.
# Kept (unused by proofs) only for documentation continuity.
SLOT_BY_ID_RE = re.compile(
    r"slot get_availabl[^\n]*\bid\s+3\b[^\n]*selected slot by id")
PROMPT_EVAL_RE = re.compile(
    r"prompt eval time\s*=\s*[0-9.]+ ms\s*/\s*(\d+) tokens")


class PhysicalDiagnosticError(RuntimeError):
    pass


def _write_json(path: Path, doc: Any) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n")
    tmp.replace(path)


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


V0_NAMESPACE = "d250-arm-v0-amd"
V0_ARM = "V0-amd-vulkan-concordance"
V0_UNIT_TAGS = tuple(f"case-3072-V0-amd-vulkan-{i:03d}"
                     for i in range(1, 4))
V0_PLACEMENT_NGL = 1
V0_PLACEMENT_BACKEND = "Vulkan"
V0_PLACEMENT_EMBEDDING = "CPU"
V0_PLACEMENT_OUTPUT_PROJECTION = "Vulkan"
# Phase-0 pinned-source law: i_gpu_start = n_layer + 1 - ngl;
# ngl=1 offloads the output head, not the input embedding.
V0_SOURCE_PIN = "b29c606e28a01b1bc8c1351026a0fae616bf6c4"
V0_COMPARATOR_SHA = D.SERVER_BINARIES["comparator"]
V0_RADV_ICD = "/usr/share/vulkan/icd.d/radeon_icd.json"
V0_BINDING_SCHEMA = "inferswarm.issue250.v0-selector-binding/1"
# Identity-bearing device fields emitted by _v0_observe_device(). Every
# canonical device entry must carry exactly these fields as non-empty
# strings; a normalized identity never discards a field to pass equality.
V0_DEVICE_IDENTITY_FIELDS = (
    "vendor_id", "device_id", "name", "driver_id",
    "driver_info", "driver_version", "api_version")
V0_EXCLUDED_NOISE_BYTES = 64 * 1024 * 1024  # accepted #243 bound
V0_MIN_SELECTED_BYTES = V0_EXCLUDED_NOISE_BYTES
V0_BINDING_PRODUCER = "issue250_physical.py:v0-load-only-binding/1"
V0_FREEZE_SCHEMA = "inferswarm.issue250.v0-screen-freeze/1"
V0_FREEZE_PRODUCER = "issue250_physical.py:v0-screen-freeze/1"
V0_FREEZE_NAME = "v0-screen-freeze.json"
# Deterministic, record-derived freeze rule: among the two validated
# selector->BDF entries of the retained preflight mapping, freeze the
# entry whose selected BDF sorts lowest. The choice is derived from the
# validated record content only — never from historical enumeration
# order, host constants, or a caller-supplied preference.
V0_FREEZE_RULE = "lexicographically-smallest-selected-bdf-of-validated-two-index-preflight"
V0_OBSERVER_LIBS = {
    "libllama-server-impl.so": "4c20f44656c19d30f5c10cd40ca3493e6850db2fd86d46f7944943527e67206c",
    "libllama-common.so.0": "218474f78c6749cf72b694451ee8df6a7a56d47e94468c92b1ee730b9aefa5eb",
    "libmtmd.so.0": "1341b0fa4d4e9e3cd9e1ec930b5b990b171058086711f7eaa406a14b41ad16d1",
    "libllama.so.0": "2f86df90a3187c006be6be097714e4c6fb612566f8c604c8551acf8fc9938775",
    "libggml.so.0": "f02894a957a21603c59a44a38b0e27adb9b88d904175e3c26a8cfff2d99a82b6",
    "libggml-base.so.0": "179340356d779c4a7d442c283a0a52d74f6770752fbfaad2cfedf3e383086b2b",
    "libggml-cpu.so.0": "dd1d2904df703f8cf6e9048a17fc0757e3679a8edc351b803889137bbeef365f",
    "libggml-vulkan.so.0": "df589e63511f8154e14ee19be14d5e20e573b81f3b518c7a8eb10d1b1a85e7fe",
}

# ---------------------------------------------------------------------------
# Issue #250 V0n — prospective current-window NVIDIA RTX 3060 Vulkan screen
# (METHODOLOGY-AMENDMENT-007). Same frozen model, prompt, request, llama.cpp
# source/build family, observation seam, Vulkan backend and ngl=1 placement
# intent as the completed V0 AMD screen — but on the NVIDIA RTX 3060 that
# produced the retained #248 rows (inferswarm01), under a SEPARATE exact-head
# dispatch for the V0n namespace/arm. CUDA is excluded mechanically (env +
# ICD + link family); a CUDA-active or CUDA-fallback execution fails closed.
# ---------------------------------------------------------------------------
V0N_NAMESPACE = D.V0N_NAMESPACE
V0N_ARM = D.V0N_ARM
V0N_UNIT_TAGS = D.V0N_UNIT_TAGS
V0N_PLACEMENT_BACKEND = "Vulkan"
V0N_PLACEMENT_EMBEDDING = "CPU"
V0N_PLACEMENT_OUTPUT_PROJECTION = "Vulkan"
V0N_SOURCE_PIN = D.LLAMA_PIN
V0N_COMPARATOR_SHA = D.SERVER_BINARIES["comparator"]
V0N_NVIDIA_ICD = "/usr/share/vulkan/icd.d/nvidia_icd.json"
V0N_HOST = "inferswarm01"
V0N_GPU_VENDOR_ID = "0x10de"
V0N_GPU_DEVICE_ID = "0x2504"          # GA106 [GeForce RTX 3060 Lite Hash Rate]
V0N_GPU_NAME = "NVIDIA GeForce RTX 3060"
V0N_DRIVER_ID = "DRIVER_ID_NVIDIA_PROPRIETARY"
V0N_MIN_RESIDENCY_BYTES = 64 * 1024 * 1024  # ngl=1 output-layer residency bound
# Every stale #250 dispatch comment ID that must NEVER authorize a V0n unit:
# 5852485456/5862772797 (superseded correction heads), 5868617068 (completed
# AMD V0 dispatch — AMD-only authority, consumed at its own head).
V0N_STALE_DISPATCH_COMMENT_IDS = frozenset({
    5852485456, 5862772797, 5868617068})
# --- V0n screen-identity freeze (NO-GO correction, comment 5874443020) ---
# The V0n screen subject is EXACTLY the accepted #248 Arm-B reference
# GPU. Physical identity authority is the accepted main module
# scripts/issue248_identity.py (REFERENCE_IDENTITY / observe_arm_identity
# ("B") / derive_identity_from_raw / identity_problems) — V0n adds NO
# parallel identity schema and never weakens #248 semantics. The freeze
# below additionally binds the mid-screen runtime identity (kernel,
# Vulkan instance) observed at screen start: every unit must reobserve
# and equal the SAME complete identity before launch and after
# execution.
V0N_FREEZE_NAME = "v0n-screen-freeze.json"
V0N_FREEZE_SCHEMA = "inferswarm.issue250.v0n-screen-freeze/1"
V0N_FREEZE_PRODUCER = "issue250_physical.write_v0n_screen_freeze"
V0N_IDENTITY_ARM = "B"  # accepted #248 reference arm authority

# --- Arm-A reachability bridge law (METHODOLOGY-AMENDMENT-008) ----------
# The bridge is recorded once at amendment freeze time against the
# accepted V0+V0n evidence (executed head aa059713…). A future Arm-A
# execution at a NEW head validates the record against these frozen
# accepted-evidence digests — never against its own head.
ARM_A_BRIDGE_PRODUCER = "issue250_physical.validate_arm_a_bridge"
ARM_A_BRIDGE_EVIDENCE_HEAD = "aa059713d83204a4dd8be2ea903aa31bddfdf3b8"

# Every accepted #248 identity field the V0n freeze binds (derived
# fresh from raw bytes; never copied from constants at observe time).
V0N_IDENTITY_FIELDS = (
    "host", "gpu_uuid", "bdf", "pci_id", "subsystem_vendor_id",
    "subsystem_device_id", "revision", "negotiated_width", "max_width",
    "max_link_speed_capability", "kernel_driver", "nvidia_driver", "icd",
    "vulkan_device_name", "vulkan_device_uuid", "vulkan_api",
    "vulkan_driver", "selector",
)
V0N_RUNTIME_FIELDS = ("kernel", "vulkan_instance")
V0N_SELECTOR_KEYS = ("VK_ICD_FILENAMES", "GGML_VK_VISIBLE_DEVICES",
                     "CUDA_VISIBLE_DEVICES")
_V0N_BDF_RE = re.compile(r"^[0-9a-f]{8}:[0-9a-f]{2}:[0-9a-f]{2}\.[0-9a-f]$")


def v0_probe_plan() -> list[dict[str, Any]]:
    """Return the immutable AMD screen order: two, third only conditionally.

    The runner must stop on the first mismatch. This pure plan carries no
    dispatch authority and deliberately remains outside the A-D reducer map.
    """
    return [{"tag": tag, "arm": V0_ARM, "namespace": V0_NAMESPACE,
             "fresh_process": True, "ngl": V0_PLACEMENT_NGL,
             "backend": V0_PLACEMENT_BACKEND,
             "embedding_placement": V0_PLACEMENT_EMBEDDING,
             "output_projection_placement": V0_PLACEMENT_OUTPUT_PROJECTION,
             "screen_index": i, "minimum_first": 2,
             "third_if_first_two_identical": True,
             "stop_on_first_mismatch": True}
            for i, tag in enumerate(V0_UNIT_TAGS, 1)]


def validate_v0_dispatch(namespace: str, arm: str,
                         authority: dict[str, Any],
                         expected_head: str | None = None) -> dict[str, Any]:
    """Validate V0 dispatch as an isolated exact namespace/arm authority."""
    if namespace != V0_NAMESPACE or arm != V0_ARM:
        raise PhysicalDiagnosticError(
            "V0 dispatch requires its exact AMD namespace and arm")
    if not isinstance(authority, dict):
        raise PhysicalDiagnosticError("V0 dispatch authority is missing")
    if (authority.get("namespace") != V0_NAMESPACE
            or authority.get("arm") != V0_ARM):
        raise PhysicalDiagnosticError("V0 dispatch authority mismatch")
    # Existing D validator intentionally knows only A-D. Validate the common
    # attestation facts directly while preserving exact V0 arm isolation.
    body = authority.get("body")
    if not isinstance(body, str):
        raise PhysicalDiagnosticError("V0 dispatch body is missing")
    lines = [line.strip() for line in body.splitlines()]
    if (f"diagnostic-namespace={V0_NAMESPACE}" not in lines
            or f"arm={V0_ARM}" not in lines
            or sum(x.startswith("diagnostic-namespace=") for x in lines) != 1
            or sum(x.startswith("arm=") for x in lines) != 1
            or lines.count(D.DIAGNOSTIC_DISPATCH_PHRASE) != 1):
        raise PhysicalDiagnosticError("V0 dispatch body binding mismatch")
    head = authority.get("head_sha")
    if expected_head is not None and head != expected_head:
        raise PhysicalDiagnosticError("V0 dispatch stale exact head")
    if (not isinstance(head, str) or len(head) != 40
            or any(ch not in "0123456789abcdef" for ch in head)
            or authority.get("author_association") not in {"OWNER", "MEMBER"}
            or authority.get("open_pr") is not True
            or authority.get("issue_open") is not True
            or type(authority.get("comment_id")) is not int
            or authority["comment_id"] <= 0
            or authority["comment_id"] == D.STALE_DISPATCH_COMMENT_ID
            or f"head={head}" not in lines
            or sum(x.startswith("head=") for x in lines) != 1
            or authority.get("issue_url") !=
               f"https://api.github.com/repos/Zutfen-LLC/inferswarm/issues/{D.DIAGNOSTIC_PR_NUMBER}"
            or not re.fullmatch(
                r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z",
                str(authority.get("created_at", "")))):
        raise PhysicalDiagnosticError("V0 dispatch payload invalid")
    return dict(authority)


def v0_server_argv(binary: Path, model_member: Path, port: int = PORT) -> list[str]:
    """The frozen ordinary argv; AMD device selection is ONLY in the env."""
    return [str(binary), "--model", str(model_member), "-ngl", "1",
            "--ctx-size", str(SERVER_CTX_SIZE),
            "--batch-size", str(SERVER_BATCH_SIZE),
            "--host", "127.0.0.1", "--port", str(port)]


def v0_environment(index: int, unit_dir: Path, binding: dict[str, Any]
                   ) -> dict[str, str]:
    """Accepted #243 RADV/visible-devices selector, bound to a record."""
    if (type(index) is not int or index < 0
            or str(index) not in binding.get("mapping", {})):
        raise PhysicalDiagnosticError("unvalidated AMD Vulkan selector index")
    return {"VK_ICD_FILENAMES": V0_RADV_ICD,
            "GGML_VK_VISIBLE_DEVICES": str(index),
            "CUDA_VISIBLE_DEVICES": "-1", "LLAMA_OBSERVE_CAPTURE": "8",
            "LLAMA_OBSERVE_OUT": str(unit_dir / "obs"),
            "LLAMA_OBSERVE_FORCE": "",
            "LD_LIBRARY_PATH": str(Path(binding["binary_lib_dir"]))}


def _v0_digest(record: dict[str, Any]) -> str:
    return D.sha256_bytes(json.dumps(
        {k: v for k, v in record.items() if k != "canonical_digest_sha256"},
        sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode())


def _v0_dies() -> dict[str, str]:
    """Read the live DRM card->PCI mapping; never freeze historical BDFs."""
    dies: dict[str, str] = {}
    for card in sorted(Path("/sys/class/drm").glob("card[0-9]*")):
        dev = card / "device"
        if not dev.is_dir() or not (dev / "vendor").is_file():
            continue
        if (dev / "vendor").read_text().strip().lower() != "0x1002":
            continue
        if (dev / "device").read_text().strip().lower() != "0x6864":
            continue
        bdf = dev.resolve().name
        if not re.fullmatch(r"[0-9a-f]{4}:[0-9a-f]{2}:[0-9a-f]{2}\.[0-7]", bdf):
            raise PhysicalDiagnosticError("AMD DRM mapping has invalid BDF")
        dies[bdf] = card.name
    if len(dies) != 2 or len(set(dies.values())) != 2:
        raise PhysicalDiagnosticError("exactly two distinct V340L dies required")
    return dies


def _v0_vram(dies: dict[str, str]) -> dict[str, int]:
    return {bdf: int((Path("/sys/class/drm") / card / "device" /
                       "mem_info_vram_used").read_text().strip())
            for bdf, card in dies.items()}


def _v0_normalize_runtime_identity(value: Any) -> dict[str, Any]:
    """Canonical V0 runtime identity (METHODOLOGY-AMENDMENT-006 contract).

    The raw-input boundary accepts exactly two Vulkan devices whose map
    keys are integer 0/1 (as ``_v0_observe_device`` parses vulkaninfo) or
    decimal strings "0"/"1" (as any JSON-retained record carries them
    after ``json.loads``). The canonical representation always uses
    string keys "0" and "1", so a retained record and a fresh live
    observation compare equal exactly when their substantive identity
    fields are equal — never on a Python int-vs-str serialization
    accident. This is structural normalization at a single seam; the
    serialized runtime identity remains inside the canonical binding
    digest untouched (digest law unchanged).

    Rejected: booleans/floats/other key types, alias or colliding
    normalized keys ("00", 0.0, duplicate 0-and-"0"), missing or extra
    device indices, malformed device objects, unknown structural
    substitutions, and non-string/non-fields device values. Fail-closed
    ``PhysicalDiagnosticError``; never coerces and never drops a field.
    """
    if not isinstance(value, dict):
        raise PhysicalDiagnosticError("V0 runtime identity malformed")
    kernel = value.get("kernel")
    instance = value.get("vulkan_instance")
    devices = value.get("devices")
    if (set(value) != {"kernel", "vulkan_instance", "devices"}
            or not isinstance(kernel, str) or not kernel
            or not isinstance(instance, str) or not instance
            or not isinstance(devices, dict)):
        raise PhysicalDiagnosticError("V0 runtime identity malformed")
    canonical: dict[str, Any] = {"kernel": kernel,
                                 "vulkan_instance": instance, "devices": {}}
    seen: set[str] = set()
    for raw_key, entry in devices.items():
        # Raw-input boundary: int 0/1 or decimal string "0"/"1" only.
        # bool is an int subclass and is explicitly refused; floats,
        # "00", " 0", "+0", "1.0" and any other alias fail the pattern.
        if isinstance(raw_key, bool):
            raise PhysicalDiagnosticError("V0 runtime identity device key "
                                          "rejected (boolean)")
        if isinstance(raw_key, int):
            key = str(raw_key)
        elif isinstance(raw_key, str) and re.fullmatch(r"[01]", raw_key):
            key = raw_key
        else:
            raise PhysicalDiagnosticError("V0 runtime identity device key "
                                          f"rejected: {raw_key!r}")
        if key not in ("0", "1") or key in seen:
            # A pre-normalized collision (e.g. 0 and "0", or two aliases
            # of one index) means the map is not exactly two devices.
            raise PhysicalDiagnosticError("V0 runtime identity duplicate or "
                                          f"colliding device key: {key!r}")
        if not isinstance(entry, dict) or set(entry) != set(
                V0_DEVICE_IDENTITY_FIELDS) or any(
                    not isinstance(entry[f], str) or not entry[f]
                    for f in V0_DEVICE_IDENTITY_FIELDS):
            raise PhysicalDiagnosticError("V0 runtime identity device entry "
                                          f"malformed at index {key}")
        seen.add(key)
        canonical["devices"][key] = {f: entry[f]
                                     for f in V0_DEVICE_IDENTITY_FIELDS}
    if seen != {"0", "1"}:
        raise PhysicalDiagnosticError("V0 runtime identity requires exactly "
                                      "the two Vulkan device indices")
    return canonical


def validate_v0_selector_binding(record: dict[str, Any], expected_head: str,
                                 index: int, live: dict[str, Any],
                                 binary_sha: str, *,
                                 verify_lib_dir: bool = True) -> dict[str, Any]:
    """Authenticate a fresh two-index, two-die #243-style physical binding.

    Record is prospective load-only evidence, NOT fabricated by this
    repository-only pass. The selected index is never inferred from ordering.
    Live enumeration/DRM/driver identity must still match at launch.

    Runtime identities are compared CANONICALLY (AMENDMENT-006): both the
    retained record's and the live observation's runtime_identity are
    normalized through _v0_normalize_runtime_identity, so a JSON-retained
    ("0"/"1" string keys) record and a fresh _v0_observe_device (int keys)
    observation compare on substantive identity only. Any kernel, Vulkan
    instance, or per-device field drift still fails closed.
    """
    if not isinstance(record, dict) or record.get("schema") != V0_BINDING_SCHEMA:
        raise PhysicalDiagnosticError("V0 selector binding record missing")
    canonical_record_identity = _v0_normalize_runtime_identity(
        record.get("runtime_identity"))
    canonical_live_identity = _v0_normalize_runtime_identity(
        live.get("runtime_identity"))
    if (record.get("canonical_digest_sha256") != _v0_digest(record)
            or record.get("expected_pr_head") != expected_head
            or record.get("host") != "inferswarm05"
            or record.get("producer") != V0_BINDING_PRODUCER
            or record.get("source_pin") != V0_SOURCE_PIN
            or record.get("binary_sha256") != V0_COMPARATOR_SHA
            or binary_sha != V0_COMPARATOR_SHA
            or record.get("icd") != V0_RADV_ICD
            or record.get("cuda_visible_devices") != "-1"
            or not isinstance(record.get("binary_lib_dir"), str)
            or not isinstance(record.get("binary_path"), str)
            or str(Path(record["binary_path"]).parent) != record["binary_lib_dir"]
            or (verify_lib_dir and not Path(record["binary_lib_dir"]).is_dir())
            or record.get("binary_lib_dir") != live.get("binary_lib_dir")
            or record.get("enumeration_sha256") != live.get("enumeration_sha256")
            or record.get("icd_sha256") != live.get("icd_sha256")
            or canonical_record_identity != canonical_live_identity
            or record.get("drm_cards") != live.get("drm_cards")):
        raise PhysicalDiagnosticError("V0 selector binding digest/head/runtime identity mismatch")
    mapping = record.get("mapping")
    cards = record.get("drm_cards")
    if (type(index) is not int or index < 0 or not isinstance(mapping, dict)
            or not isinstance(cards, dict) or len(cards) != 2
            or set(mapping) != {"0", "1"} or str(index) not in mapping
            or set(live.get("vulkan_indices", [])) != {0, 1}
            or live.get("index") != index or live.get("vendor_id") != "0x1002"
            or live.get("device_id") != "0x6864"):
        raise PhysicalDiagnosticError("V0 unvalidated index or AMD enumeration")
    selected: set[str] = set()
    for key, entry in mapping.items():
        if not isinstance(entry, dict):
            raise PhysicalDiagnosticError("V0 selector mapping malformed")
        a, b = entry.get("selected_bdf"), entry.get("excluded_bdf")
        if (a not in cards or b not in cards or a == b
                or entry.get("selected_card") != cards[a]
                or entry.get("excluded_card") != cards[b]):
            raise PhysicalDiagnosticError("V0 selector BDF/card mismatch")
        before, after = entry.get("vram_before"), entry.get("vram_after")
        if (not isinstance(before, dict) or not isinstance(after, dict)
                or set(before) != set(cards) or set(after) != set(cards)
                or any(type(v) is not int or v < 0 for v in
                       list(before.values()) + list(after.values()))
                or after[a] - before[a] <= V0_MIN_SELECTED_BYTES
                or after[b] - before[b] >= V0_EXCLUDED_NOISE_BYTES):
            raise PhysicalDiagnosticError("V0 selected/excluded die residency unproven")
        selected.add(str(a))
    if len(selected) != 2:
        raise PhysicalDiagnosticError("V0 duplicate selector-to-BDF mapping")
    entry = mapping[str(index)]
    return entry


def _v0_verify_probe_records(record: dict[str, Any], root: Path,
                             authority: dict[str, Any]) -> None:
    """Bind selected/excluded delta claims to retained load-only probes."""
    probes = record.get("preflight_probe_sha256")
    directory = Path(root) / "v0-selector-preflight"
    if (not isinstance(probes, dict) or set(probes) != {"0", "1"}
            or record.get("dispatch_sha256") != D.authority_digest(authority)
            or directory.is_symlink() or not directory.is_dir()):
        raise PhysicalDiagnosticError("V0 preflight probe custody/dispatch missing")
    for idx in (0, 1):
        path = directory / f"index-{idx}.json"
        if (path.is_symlink() or not path.is_file()
                or D.file_sha256(path) != probes[str(idx)]):
            raise PhysicalDiagnosticError("V0 preflight probe bytes drift")
        try:
            probe = json.loads(path.read_bytes())
        except (ValueError, OSError) as exc:
            raise PhysicalDiagnosticError("V0 preflight probe unreadable") from exc
        entry = record["mapping"][str(idx)]
        attr = probe.get("process_attribution", {})
        env = attr.get("server_env", {})
        if (probe.get("index") != idx
                or probe.get("vram_before") != entry["vram_before"]
                or probe.get("vram_after") != entry["vram_after"]
                or attr.get("server_exe_sha256") != V0_COMPARATOR_SHA
                or env.get("VK_ICD_FILENAMES") != V0_RADV_ICD
                or env.get("GGML_VK_VISIBLE_DEVICES") != str(idx)
                or env.get("CUDA_VISIBLE_DEVICES") != "-1"
                or env.get("LD_LIBRARY_PATH") != record["binary_lib_dir"]
                or attr.get("server_argv") != v0_server_argv(
                    Path(record["binary_path"]),
                    Path(D.MODEL_DIR) / D.MODEL_MEMBER_1)):
            raise PhysicalDiagnosticError("V0 preflight probe/selector identity mismatch")


def _v0_freeze_digest(record: dict[str, Any]) -> str:
    """Canonical digest over the freeze record (same law as _v0_digest)."""
    return _v0_digest(record)


def _read_v0_screen_freeze(root: Path, expected_head: str) -> dict[str, Any]:
    """Load and fully authenticate the retained V0 screen freeze record.

    The freeze is the ONLY canonical selector/device authority for the
    V0 AMD screening population: it names exactly one Vulkan index and
    the selected/excluded BDF pair, bound to the exact head, the live
    dispatch authority, and the digest of the validated two-index
    preflight selector-binding record it was derived from.
    """
    root = Path(root)
    path = root / V0_FREEZE_NAME
    if path.is_symlink() or not path.is_file():
        raise PhysicalDiagnosticError("V0 screen freeze record missing")
    try:
        record = json.loads(path.read_bytes())
    except (ValueError, OSError) as exc:
        raise PhysicalDiagnosticError("V0 screen freeze unreadable") from exc
    if not isinstance(record, dict):
        raise PhysicalDiagnosticError("V0 screen freeze malformed")
    index = record.get("v0_screen_vulkan_index")
    selected = record.get("v0_screen_selected_bdf")
    excluded = record.get("v0_screen_excluded_bdf")
    if (record.get("schema") != V0_FREEZE_SCHEMA
            or record.get("producer") != V0_FREEZE_PRODUCER
            or record.get("freeze_rule") != V0_FREEZE_RULE
            or record.get("expected_pr_head") != expected_head
            or type(index) is not int or index not in (0, 1)
            or record.get("canonical_digest_sha256") != _v0_freeze_digest(record)
            or not isinstance(selected, str) or not isinstance(excluded, str)
            or selected == excluded
            or not re.fullmatch(r"[0-9a-f]{4}:[0-9a-f]{2}:[0-9a-f]{2}\.[0-7]",
                                selected)
            or not re.fullmatch(r"[0-9a-f]{4}:[0-9a-f]{2}:[0-9a-f]{2}\.[0-7]",
                                excluded)):
        raise PhysicalDiagnosticError("V0 screen freeze digest/head/binding mismatch")
    return record


def _v0_freeze_binding_digest(record: dict[str, Any]) -> str:
    """Digest of the selector-binding record the freeze was derived from."""
    value = record.get("selector_binding_digest")
    if (not isinstance(value, str)
            or not re.fullmatch(r"[0-9a-f]{64}", value)):
        raise PhysicalDiagnosticError("V0 screen freeze missing selector binding digest")
    return value


def _v0_load_freeze_with_preflight(root: Path, expected_head: str,
                                   authority: dict[str, Any]
                                   ) -> tuple[dict[str, Any], dict[str, Any]]:
    """Authenticate the freeze AND its derivation from the validated preflight.

    Re-derive the canonical lexical-BDF choice from the authenticated
    two-index preflight, rather than accepting either valid mapping entry.
    This is shared by the launch, retained-row and terminal consumers.
    """
    root = Path(root)
    freeze = _read_v0_screen_freeze(root, expected_head)
    binding_path = root / "v0-selector-binding.json"
    if binding_path.is_symlink() or not binding_path.is_file():
        raise PhysicalDiagnosticError("fresh V0 selector binding record missing")
    try:
        binding = json.loads(binding_path.read_bytes())
    except (ValueError, OSError) as exc:
        raise PhysicalDiagnosticError("V0 selector binding unreadable") from exc
    if not isinstance(binding, dict):
        raise PhysicalDiagnosticError("V0 selector binding malformed")
    if (binding.get("canonical_digest_sha256") != _v0_digest(binding)
            or _v0_freeze_binding_digest(freeze)
               != binding.get("canonical_digest_sha256")
            or freeze.get("dispatch_sha256") != binding.get("dispatch_sha256")
            or freeze.get("dispatch_sha256") != D.authority_digest(authority)):
        raise PhysicalDiagnosticError("V0 screen freeze not derived from retained preflight")
    mapping = binding.get("mapping")
    if (not isinstance(mapping, dict) or set(mapping) != {"0", "1"}
            or any(not isinstance(mapping[key], dict) for key in ("0", "1"))):
        raise PhysicalDiagnosticError("V0 screen freeze diverges from preflight mapping")
    # Authenticate BOTH retained candidates against the probe bytes before
    # applying the selection law. No live host or inference is needed by a
    # retained consumer, and no previously retained unit is trusted here.
    for index in (0, 1):
        live = {key: binding.get(key) for key in (
            "binary_lib_dir", "enumeration_sha256", "icd_sha256",
            "runtime_identity", "drm_cards")}
        live.update(index=index, vulkan_indices=[0, 1],
                    vendor_id="0x1002", device_id="0x6864")
        validate_v0_selector_binding(binding, expected_head, index, live,
                                     V0_COMPARATOR_SHA, verify_lib_dir=False)
    _v0_verify_probe_records(binding, root, authority)
    canonical_index = min((0, 1),
                          key=lambda i: mapping[str(i)]["selected_bdf"])
    canonical = mapping[str(canonical_index)]
    if (freeze["v0_screen_vulkan_index"] != canonical_index
            or freeze["v0_screen_selected_bdf"] != canonical["selected_bdf"]
            or freeze["v0_screen_excluded_bdf"] != canonical["excluded_bdf"]
            or freeze.get("selected_card") != canonical["selected_card"]
            or freeze.get("excluded_card") != canonical["excluded_card"]):
        raise PhysicalDiagnosticError("V0 screen freeze violates canonical preflight selection")
    if (freeze.get("source_pin") != V0_SOURCE_PIN
            or freeze.get("binary_sha256") != V0_COMPARATOR_SHA
            or freeze.get("icd") != V0_RADV_ICD
            or freeze.get("cuda_visible_devices") != "-1"
            or freeze.get("namespace") != V0_NAMESPACE
            or freeze.get("arm") != V0_ARM):
        raise PhysicalDiagnosticError("V0 screen freeze authority fields mismatch")
    return freeze, binding


def write_v0_screen_freeze(repo_root: Path, evidence_root: Path, *,
                           binary: Path, binary_id: str, model_dir: Path,
                           expected_head: str, model_attestation: dict[str, Any],
                           revalidate_authority: Callable[..., dict[str, Any]] | None = None,
                           device_observer: Callable[[int], dict[str, Any]] | None = None,
                           github_api: str = "https://api.github.com"
                           ) -> dict[str, Any]:
    """Freeze exactly one validated V0 AMD selector/device for the population.

    PROSPECTIVE, repository-only: creates no model load, no load-only
    probe and no inference unit. Must run AFTER the two-index preflight
    binding is retained and BEFORE the first V0 unit. The choice is
    derived mechanically from the validated preflight record via the
    frozen V0_FREEZE_RULE (lexicographically smallest selected BDF of
    the two validated entries) — never from enumeration order, host BDF
    constants, or caller preference. The record is append-only: an
    existing freeze is refused, so a later unit can never silently
    re-choose a different device after a failure.
    """
    if binary_id != "comparator" or str(model_dir) != D.MODEL_DIR:
        raise PhysicalDiagnosticError("V0 frozen comparator/model identity mismatch")
    root = Path(evidence_root)
    validate_evidence_generation(root)
    _admit_retained_cost(root, TB.V0_CONDITION, V0_NAMESPACE, V0_ARM)
    early = require_live_dispatch(repo_root, expected_head, V0_NAMESPACE,
                                  revalidate_authority, github_api)
    D._require_clean_head(Path(repo_root), expected_head)
    target = root / V0_FREEZE_NAME
    if target.exists() or target.is_symlink():
        raise PhysicalDiagnosticError("V0 screen freeze already retained")
    if (root / V0_NAMESPACE).exists():
        raise PhysicalDiagnosticError(
            "V0 screen freeze must precede the first inference unit")
    binary_sha = _verify_v0_amd_binary(Path(binary), binary_id)
    attestation = validate_model_attestation(model_attestation, expected_head)
    opening = root / MODEL_ATTESTATION_OPEN_NAME
    if (opening.is_symlink() or not opening.is_file()
            or json.loads(opening.read_bytes()) != attestation):
        raise PhysicalDiagnosticError("V0 screen freeze model attestation absent")
    problems, _ = attestation_witness(Path(model_dir), attestation)
    if problems or str(model_dir) != D.MODEL_DIR:
        raise PhysicalDiagnosticError("V0 screen freeze model witness drift")
    binding_path = root / "v0-selector-binding.json"
    if binding_path.is_symlink() or not binding_path.is_file():
        raise PhysicalDiagnosticError("fresh V0 selector binding record missing")
    try:
        binding = json.loads(binding_path.read_bytes())
    except (ValueError, OSError) as exc:
        raise PhysicalDiagnosticError("V0 selector binding unreadable") from exc
    late = require_live_dispatch(repo_root, expected_head, V0_NAMESPACE,
                                 revalidate_authority, github_api)
    if D.authority_digest(early) != D.authority_digest(late):
        raise PhysicalDiagnosticError("V0 screen freeze dispatch drift")
    D._require_clean_head(Path(repo_root), expected_head)
    _admit_retained_cost(root, TB.V0_CONDITION, V0_NAMESPACE, V0_ARM)
    # Validate the retained two-index preflight against the LIVE substrate
    # (enumeration/DRM/runtime identity) for the index the rule will pick;
    # validate_v0_selector_binding performs the full selector/BDF/
    # residency/probe-custody checks without any model load.
    mapping = binding.get("mapping") if isinstance(binding, dict) else None
    if (not isinstance(mapping, dict) or set(mapping) != {"0", "1"}
            or not all(isinstance(mapping[k], dict) for k in mapping)):
        raise PhysicalDiagnosticError("V0 preflight binding malformed")
    chosen_index = min((0, 1),
                       key=lambda i: str(mapping[str(i)]["selected_bdf"]))
    chosen = mapping[str(chosen_index)]
    observer = device_observer or _v0_observe_device
    live = observer(chosen_index)
    live["binary_lib_dir"] = str(Path(binary).parent)
    entry = validate_v0_selector_binding(
        binding, expected_head, chosen_index, live, binary_sha)
    _v0_verify_probe_records(binding, root, early)
    record = {
        "schema": V0_FREEZE_SCHEMA, "producer": V0_FREEZE_PRODUCER,
        "freeze_rule": V0_FREEZE_RULE, "expected_pr_head": expected_head,
        "v0_screen_vulkan_index": chosen_index,
        "v0_screen_selected_bdf": entry["selected_bdf"],
        "v0_screen_excluded_bdf": entry["excluded_bdf"],
        "selected_card": entry["selected_card"],
        "excluded_card": entry["excluded_card"],
        "source_pin": V0_SOURCE_PIN, "binary_sha256": binary_sha,
        "icd": V0_RADV_ICD, "cuda_visible_devices": "-1",
        "selector_binding_digest": binding.get("canonical_digest_sha256"),
        "dispatch_sha256": D.authority_digest(early),
        "namespace": V0_NAMESPACE, "arm": V0_ARM,
    }
    record["canonical_digest_sha256"] = _v0_freeze_digest(record)
    _write_json(target, record)
    # Re-authenticate the retained bytes exactly as every later consumer will.
    frozen, rebind = _v0_load_freeze_with_preflight(root, expected_head, early)
    if (frozen["canonical_digest_sha256"] != record["canonical_digest_sha256"]
            or rebind.get("canonical_digest_sha256")
               != binding.get("canonical_digest_sha256")):
        raise PhysicalDiagnosticError("V0 screen freeze retention mismatch")
    return record


def _v0_retained_rows(root: Path, count: int, head: str,
                      authority: dict[str, Any]) -> list[str]:
    """Recheck each predecessor against retained full-row bytes and custody.

    CORRECTION (one-factor V0): the whole retained population must share
    ONE frozen Vulkan selector index and selected/excluded BDF pair, bound
    canonically by the retained v0-screen-freeze record. A population whose
    receipts use different indices or selected BDFs is rejected even if
    every receipt is individually valid — mixed-die rows are not AMD
    fresh-process evidence.
    """
    import hashlib
    rows = []
    base = Path(root) / V0_NAMESPACE
    if base.is_symlink():
        raise PhysicalDiagnosticError("V0 namespace symlink refused")
    freeze, binding = _v0_load_freeze_with_preflight(
        Path(root), head, authority)
    frozen_index = freeze["v0_screen_vulkan_index"]
    frozen_selected = freeze["v0_screen_selected_bdf"]
    frozen_excluded = freeze["v0_screen_excluded_bdf"]
    binding_digest = _v0_freeze_binding_digest(freeze)
    if base.exists():
        present = {p.name for p in base.iterdir()
                   if p.is_dir() or p.is_symlink()}
        if present != set(V0_UNIT_TAGS[:count]):
            raise PhysicalDiagnosticError(
                "V0 unexpected/partial/future unit population; no selective repeats")
    elif count:
        raise PhysicalDiagnosticError("V0 predecessor namespace missing")
    for tag in V0_UNIT_TAGS[:count]:
        directory = base / tag
        receipt_path = directory / "unit.json"
        row_path = directory / "obs.row0.f32"
        if (directory.is_symlink() or receipt_path.is_symlink()
                or row_path.is_symlink() or not receipt_path.is_file()
                or not row_path.is_file()):
            raise PhysicalDiagnosticError("V0 predecessor retained row missing")
        try:
            receipt = json.loads(receipt_path.read_bytes())
            raw = row_path.read_bytes()
        except (OSError, ValueError) as exc:
            raise PhysicalDiagnosticError("V0 predecessor unreadable") from exc
        digest = hashlib.sha256(raw).hexdigest()
        if (len(raw) != D.ROW_BYTES or not isinstance(receipt, dict)
                or receipt.get("schema") != D.V0_SCHEMA
                or receipt.get("tag") != tag
                or receipt.get("namespace") != V0_NAMESPACE
                or receipt.get("arm") != V0_ARM
                or receipt.get("head_sha") != head
                or receipt.get("evidence_generation") != EVIDENCE_GENERATION
                or receipt.get("decision0_row_sha256") != digest
                or receipt.get("authority_sha256") != D.authority_digest(authority)
                or receipt.get("placement_verified") is not True
                or receipt.get("fresh_process") is not True
                or receipt.get("case_id") != D.CONTRAST_CASE
                or receipt.get("ngl") != 1
                or receipt.get("model_dir") != D.MODEL_DIR
                or receipt.get("model_member_sha256") !=
                   D.MODEL_MEMBER_SHA256[D.MODEL_MEMBER_1]
                or receipt.get("request_contract") != D.REQUEST_CONTRACT
                or receipt.get("prompt_token_ids") is None
                or D.sha256_bytes(json.dumps(
                    receipt["prompt_token_ids"], separators=(",", ":")).encode())
                   != receipt.get("prompt_sha256")
                or receipt.get("row_bytes") != D.ROW_BYTES
                or type(receipt.get("server_pid")) is not int
                or receipt["server_pid"] <= 0
                or not isinstance(receipt.get("amd_device"), dict)
                or receipt["amd_device"].get("vendor_id") != "0x1002"
                or receipt.get("binary_sha256") != V0_COMPARATOR_SHA
                or not isinstance(receipt.get("v0_selector_binding"), dict)
                or receipt["v0_selector_binding"].get("expected_pr_head") != head
                or receipt["v0_selector_binding"].get("source_pin") != V0_SOURCE_PIN
                or receipt["v0_selector_binding"].get("binary_sha256") != V0_COMPARATOR_SHA
                or receipt["v0_selector_binding"].get("canonical_digest_sha256")
                   != _v0_digest(receipt["v0_selector_binding"])
                or not isinstance(receipt.get("server_env"), dict)
                or receipt["server_env"].get("VK_ICD_FILENAMES") != V0_RADV_ICD
                or receipt["server_env"].get("CUDA_VISIBLE_DEVICES") != "-1"
                or receipt["server_env"].get("GGML_VK_VISIBLE_DEVICES")
                   != str(receipt["amd_device"].get("index"))
                or not isinstance(receipt.get("server_argv"), list)
                or not receipt["server_argv"]
                or receipt["server_argv"][0] !=
                   receipt["v0_selector_binding"].get("binary_path")
                or receipt.get("model_launch_member") !=
                   str(Path(D.MODEL_DIR) / D.MODEL_MEMBER_1)
                or receipt["server_argv"] != v0_server_argv(
                    Path(receipt["server_argv"][0]),
                    Path(receipt.get("model_launch_member", "")), PORT)
                or receipt.get("placement_source_law") != {
                    "source_pin": V0_SOURCE_PIN, "ngl": 1,
                    "embedding": "CPU", "output_projection": "Vulkan"}):
            raise PhysicalDiagnosticError("V0 predecessor retained byte/custody mismatch")
        binding = receipt["v0_selector_binding"]
        device = receipt["amd_device"]
        # One-factor V0: every retained repeat must carry the FROZEN
        # selector index and the selected/excluded BDF pair it implies.
        if (device.get("index") != frozen_index
                or receipt.get("selected_bdf") != frozen_selected
                or receipt.get("excluded_bdf") != frozen_excluded):
            raise PhysicalDiagnosticError(
                "V0 retained population is not bound to one frozen AMD die")
        if binding.get("canonical_digest_sha256") != binding_digest:
            raise PhysicalDiagnosticError(
                "V0 retained population selector binding digest mismatch")
        validate_v0_selector_binding(binding, head, device["index"],
                                     device, receipt["binary_sha256"],
                                     verify_lib_dir=False)
        _v0_verify_probe_records(binding, root, authority)
        if (receipt.get("process_attribution", {}).get("server_env")
                != receipt["server_env"]
                or receipt.get("process_attribution", {}).get("server_argv")
                   != receipt["server_argv"]
                or receipt.get("process_attribution", {}).get("server_exe_sha256")
                   != V0_COMPARATOR_SHA):
            raise PhysicalDiagnosticError("V0 predecessor process attribution mismatch")
        _v0_verify_placement(directory, device, {
            "vulkan_device_index": device["index"], "backend": receipt.get("backend"),
            "cuda_participation": False if receipt["server_env"].get(
                "CUDA_VISIBLE_DEVICES") == "-1" else None,
            "vram_before": receipt.get("vram_before"),
            "vram_after": receipt.get("vram_after")}, binding)
        rows.append(digest)
    return rows


def _v0_observe_device(index: int) -> dict[str, Any]:
    """Non-model RADV enumeration + live sysfs identity on inferswarm05."""
    import platform
    if socket.gethostname() != "inferswarm05":
        raise PhysicalDiagnosticError("V0 host must be inferswarm05")
    icd = Path(V0_RADV_ICD)
    if not icd.is_file():
        raise PhysicalDiagnosticError("RADV ICD unavailable")
    result = subprocess.run(["vulkaninfo", "--summary"], capture_output=True,
                            text=True, timeout=30, check=True,
                            env={**os.environ, "VK_ICD_FILENAMES": V0_RADV_ICD,
                                 "CUDA_VISIBLE_DEVICES": "-1"})
    blocks = re.split(r"(?=GPU[0-9]+:\s*)", result.stdout)
    devices = {}
    for block in blocks:
        m = re.match(r"GPU(\d+):\s*", block)
        if m:
            devices[int(m.group(1))] = {
                key: match.group(1).strip() for key, pattern in {
                    "vendor_id": r"vendorID\s*=\s*(0x[0-9a-f]+)",
                    "device_id": r"deviceID\s*=\s*(0x[0-9a-f]+)",
                    "name": r"deviceName\s*=\s*(.+)",
                    "driver_id": r"driverID\s*=\s*(.+)",
                    "driver_info": r"driverInfo\s*=\s*(.+)",
                    "driver_version": r"driverVersion\s*=\s*(.+)",
                    "api_version": r"apiVersion\s*=\s*(.+)",
                }.items() if (match := re.search(pattern, block, re.I))}
    if (set(devices) != {0, 1} or index not in devices
            or any(x.get("vendor_id") != "0x1002"
                   or x.get("device_id") != "0x6864"
                   or x.get("driver_id") != "DRIVER_ID_MESA_RADV"
                   for x in devices.values())):
        raise PhysicalDiagnosticError("two V340L RADV Vulkan indices not observed")
    runtime = {"kernel": platform.release(),
               "vulkan_instance": (re.search(
                   r"Vulkan Instance Version:\s*(\S+)", result.stdout) or
                   [None, ""])[1],
               # AMENDMENT-006: canonical JSON-stable device map — string
               # keys "0"/"1" from the outset, so the retained binding and
               # any fresh observation are byte-equal after JSON retention.
               # The live index and vulkan_indices above remain integers.
               "devices": {str(i): entry for i, entry in devices.items()}}
    return {"index": index, **devices[index],
            "vulkan_indices": sorted(devices),
            "enumeration_sha256": D.sha256_bytes(result.stdout.encode()),
            "icd_sha256": D.file_sha256(icd),
            "runtime_identity": runtime, "drm_cards": _v0_dies(),
            "binary_lib_dir": ""}


def _v0_verify_placement(unit_dir: Path, device: dict[str, Any],
                         result: dict[str, Any],
                         binding: dict[str, Any] | None = None) -> None:
    """Pinned source law + selected/excluded-die runtime residency."""
    if (not isinstance(binding, dict) or binding.get("source_pin") != V0_SOURCE_PIN
            or binding.get("binary_sha256") != V0_COMPARATOR_SHA
            or device.get("vendor_id") != "0x1002"
            or result.get("vulkan_device_index") != device.get("index")
            or result.get("backend") != "Vulkan"
            or result.get("cuda_participation") is not False):
        raise PhysicalDiagnosticError("V0 pinned source/backend/AMD placement unverified")
    entry = binding["mapping"][str(device["index"])]
    before, after = result.get("vram_before"), result.get("vram_after")
    a, b = entry["selected_bdf"], entry["excluded_bdf"]
    if (not isinstance(before, dict) or not isinstance(after, dict)
            or set(before) != set(binding["drm_cards"])
            or set(after) != set(before)
            or any(type(v) is not int or v < 0 for v in
                   list(before.values()) + list(after.values()))
            or after[a] - before[a] <= V0_MIN_SELECTED_BYTES
            or after[b] - before[b] >= V0_EXCLUDED_NOISE_BYTES):
        raise PhysicalDiagnosticError("V0 selected/excluded physical die residency unverified")


def _verify_v0_amd_binary(binary: Path, binary_id: str) -> str:
    """Exact observer executable AND its dynamic Vulkan library family."""
    if (V0_SOURCE_PIN != D.LLAMA_PIN
            or V0_COMPARATOR_SHA != D.SERVER_BINARIES["comparator"]
            or binary_id != "comparator"
            or verify_binary(binary, binary_id) != V0_COMPARATOR_SHA):
        raise PhysicalDiagnosticError("V0 requires exact pinned comparator observer")
    for name, digest in V0_OBSERVER_LIBS.items():
        path = binary.parent / name
        if not path.is_file() or D.file_sha256(path) != digest:
            raise PhysicalDiagnosticError(f"V0 observer library mismatch: {name}")
    env = {**os.environ, "LD_LIBRARY_PATH": str(binary.parent),
           "VK_ICD_FILENAMES": V0_RADV_ICD, "CUDA_VISIBLE_DEVICES": "-1"}
    dep = subprocess.run(["ldd", str(binary)], env=env, capture_output=True,
                         text=True, timeout=20, check=True)
    if ("not found" in dep.stdout or "libggml-vulkan.so.0" not in dep.stdout
            or any(str(binary.parent / name) not in dep.stdout
                   for name in V0_OBSERVER_LIBS)):
        raise PhysicalDiagnosticError("V0 observer dynamic loader incompatibility")
    help_run = subprocess.run([str(binary), "--help"], env=env,
                              capture_output=True, timeout=30)
    if help_run.returncode != 0 or b"--n-gpu-layers" not in (
            help_run.stdout + help_run.stderr):
        raise PhysicalDiagnosticError("V0 observer non-model execution failed")
    return V0_COMPARATOR_SHA


def _v0_check_live_process(proc: subprocess.Popen, argv: list[str],
                           env: dict[str, str]) -> None:
    """Read back the live server's actual argv/environment, not caller claims."""
    observed_env = dict(chunk.split(b"=", 1) for chunk in
                        Path(f"/proc/{proc.pid}/environ").read_bytes().split(b"\0")
                        if b"=" in chunk)
    if (any(observed_env.get(k.encode()) != v.encode()
            for k, v in env.items())
            or Path(f"/proc/{proc.pid}/cmdline").read_bytes().rstrip(b"\0").split(b"\0")
               != [x.encode() for x in argv]):
        raise PhysicalDiagnosticError("V0 process argv/environment drift")


def _real_v0_execute(argv: list[str], env: dict[str, str],
                     request: dict[str, Any], prompt: str, port: int,
                     unit_dir: Path, timeout_budget: dict[str, Any],
                     device_binding: dict[str, Any]) -> dict[str, Any]:
    """AMD fresh process, selected/excluded VRAM measured while loaded."""
    dies = device_binding["drm_cards"]
    before = _v0_vram(dies)
    with (unit_dir / "server.log").open("wb") as log:
        proc = subprocess.Popen(argv, env={**os.environ, **env}, stdout=log,
                                stderr=subprocess.STDOUT, start_new_session=True)
        try:
            _wait_healthy(proc, port)
            after = _v0_vram(dies)
            attribution = _proc_attribution(proc, argv, env)
            _v0_check_live_process(proc, argv, env)
            raw, response = _http_completion(
                port, request, prompt, timeout_s=timeout_budget["budget_s"])
            return {"response_raw": raw, "tokens": response.get("tokens"),
                    "process_attribution": attribution,
                    "vulkan_device_index": int(env["GGML_VK_VISIBLE_DEVICES"]),
                    "vram_before": before, "vram_after": after,
                    "backend": "Vulkan", "cuda_participation": False,
                    "timeout_budget": timeout_budget}
        finally:
            if proc.poll() is None:
                os.killpg(proc.pid, signal.SIGTERM)
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(proc.pid, signal.SIGKILL)
                    proc.wait(timeout=5)


def _v0_probe_load(binary: Path, model_member: Path, index: int,
                   dies: dict[str, str], probe_dir: Path) -> dict[str, Any]:
    """Future dispatch-only load/health probe; NEVER request completion."""
    argv = v0_server_argv(binary, model_member)
    env = {"VK_ICD_FILENAMES": V0_RADV_ICD,
           "GGML_VK_VISIBLE_DEVICES": str(index),
           "CUDA_VISIBLE_DEVICES": "-1",
           "LD_LIBRARY_PATH": str(binary.parent)}
    before = _v0_vram(dies)
    with (probe_dir / f"index-{index}.server.log").open("wb") as log:
        proc = subprocess.Popen(argv, env={**os.environ, **env},
                                stdout=log, stderr=subprocess.STDOUT,
                                start_new_session=True)
        try:
            _wait_healthy(proc, PORT)
            after = _v0_vram(dies)
            attribution = _proc_attribution(proc, argv, env)
            _v0_check_live_process(proc, argv, env)
            return {"index": index, "vram_before": before,
                    "vram_after": after, "process_attribution": attribution}
        finally:
            if proc.poll() is None:
                os.killpg(proc.pid, signal.SIGTERM)
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(proc.pid, signal.SIGKILL)
                    proc.wait(timeout=5)


def v0n_probe_plan() -> list[dict[str, Any]]:
    """Immutable V0n NVIDIA current-window screen order: two, third conditional.

    Same bounded screen structure as the V0 AMD screen (AMENDMENT-007):
    minimum first pair, third ONLY after a byte-identical first pair,
    stop on first mismatch. Pure plan; carries no dispatch authority.
    """
    return [{"tag": tag, "arm": V0N_ARM, "namespace": V0N_NAMESPACE,
             "fresh_process": True, "ngl": 1,
             "backend": V0N_PLACEMENT_BACKEND,
             "embedding_placement": V0N_PLACEMENT_EMBEDDING,
             "output_projection_placement": V0N_PLACEMENT_OUTPUT_PROJECTION,
             "screen_index": i, "minimum_first": 2,
             "third_if_first_two_identical": True,
             "stop_on_first_mismatch": True}
            for i, tag in enumerate(V0N_UNIT_TAGS, 1)]


def validate_v0n_dispatch(namespace: str, arm: str,
                          authority: dict[str, Any],
                          expected_head: str | None = None
                          ) -> dict[str, Any]:
    """Validate V0n dispatch as an isolated exact namespace/arm authority.

    Mirrors validate_v0_dispatch with the NVIDIA-current binding, and
    additionally refuses the known stale #250 dispatch comment IDs
    (including the completed AMD V0 dispatch) — a completed or
    superseded dispatch can never authorize a V0n unit.
    """
    if namespace != V0N_NAMESPACE or arm != V0N_ARM:
        raise PhysicalDiagnosticError(
            "V0n dispatch requires its exact NVIDIA namespace and arm")
    if not isinstance(authority, dict):
        raise PhysicalDiagnosticError("V0n dispatch authority is missing")
    if (authority.get("namespace") != V0N_NAMESPACE
            or authority.get("arm") != V0N_ARM):
        raise PhysicalDiagnosticError("V0n dispatch authority mismatch")
    body = authority.get("body")
    if not isinstance(body, str):
        raise PhysicalDiagnosticError("V0n dispatch body is missing")
    lines = [line.strip() for line in body.splitlines()]
    if (f"diagnostic-namespace={V0N_NAMESPACE}" not in lines
            or f"arm={V0N_ARM}" not in lines
            or sum(x.startswith("diagnostic-namespace=") for x in lines) != 1
            or sum(x.startswith("arm=") for x in lines) != 1
            or lines.count(D.DIAGNOSTIC_DISPATCH_PHRASE) != 1):
        raise PhysicalDiagnosticError("V0n dispatch body binding mismatch")
    head = authority.get("head_sha")
    if expected_head is not None and head != expected_head:
        raise PhysicalDiagnosticError("V0n dispatch stale exact head")
    if (not isinstance(head, str) or len(head) != 40
            or any(ch not in "0123456789abcdef" for ch in head)
            or authority.get("author_association") not in {"OWNER", "MEMBER"}
            or authority.get("open_pr") is not True
            or authority.get("issue_open") is not True
            or type(authority.get("comment_id")) is not int
            or authority["comment_id"] <= 0
            or authority["comment_id"] in V0N_STALE_DISPATCH_COMMENT_IDS
            or authority["comment_id"] == D.STALE_DISPATCH_COMMENT_ID
            or f"head={head}" not in lines
            or sum(x.startswith("head=") for x in lines) != 1
            or authority.get("issue_url") !=
               f"https://api.github.com/repos/Zutfen-LLC/inferswarm/issues/{D.DIAGNOSTIC_PR_NUMBER}"
            or not re.fullmatch(
                r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z",
                str(authority.get("created_at", "")))):
        raise PhysicalDiagnosticError("V0n dispatch payload invalid")
    return dict(authority)


def v0n_server_argv(binary: Path, model_member: Path,
                    port: int = PORT) -> list[str]:
    """The frozen ordinary V0n argv — IDENTICAL law to the V0 AMD argv.

    Device selection is ONLY in the environment (NVIDIA ICD + visible
    devices); no CUDA flag, no --device flag, no per-vendor argv drift.
    """
    return [str(binary), "--model", str(model_member), "-ngl", "1",
            "--ctx-size", str(SERVER_CTX_SIZE),
            "--batch-size", str(SERVER_BATCH_SIZE),
            "--host", "127.0.0.1", "--port", str(port)]


def v0n_environment(unit_dir: Path) -> dict[str, str]:
    """Frozen V0n NVIDIA Vulkan environment: NVIDIA ICD only, CUDA off.

    GGML_VK_VISIBLE_DEVICES=0 selects the single enumerated NVIDIA
    Vulkan device; CUDA_VISIBLE_DEVICES=-1 removes every CUDA device
    so no CUDA backend can silently substitute for Vulkan.
    """
    return {"VK_ICD_FILENAMES": V0N_NVIDIA_ICD,
            "GGML_VK_VISIBLE_DEVICES": "0",
            "CUDA_VISIBLE_DEVICES": "-1", "LLAMA_OBSERVE_CAPTURE": "8",
            "LLAMA_OBSERVE_OUT": str(unit_dir / "obs"),
            "LLAMA_OBSERVE_FORCE": "",
            "LD_LIBRARY_PATH": "{{BINARY_LIB_DIR}}"}


def _v0n_observe_runtime() -> dict[str, str]:
    """Live kernel + Vulkan-instance runtime identity (read-only).

    The two fields that can drift MID-SCREEN without changing any PCI
    identity: the running kernel release and the Vulkan loader/instance
    version servicing the NVIDIA ICD. Frozen at screen start inside the
    V0n freeze and reobserved before/after every unit.
    """
    import platform
    if socket.gethostname() != V0N_HOST:
        raise PhysicalDiagnosticError("V0n host must be inferswarm01")
    proc = subprocess.run(
        ["vulkaninfo", "--summary"], capture_output=True, text=True,
        timeout=30, check=True,
        env={**os.environ, "VK_ICD_FILENAMES": V0N_NVIDIA_ICD,
             "CUDA_VISIBLE_DEVICES": "-1"})
    match = re.search(r"Vulkan Instance Version:\s*(\S+)", proc.stdout)
    kernel = platform.release()
    if not match or not kernel:
        raise PhysicalDiagnosticError("V0n runtime identity unobservable")
    return {"kernel": kernel, "vulkan_instance": match.group(1)}


def v0n_identity_from_observation(observation: dict[str, Any],
                                  runtime: dict[str, Any] | None = None
                                  ) -> dict[str, Any]:
    """Complete V0n subject identity from a FRESH #248 Arm-B observation.

    Reuses the accepted main authority ``scripts/issue248_identity.py``
    EXACTLY: the observation must carry a raw block, derive cleanly
    through ``derive_identity_from_raw("B", ...)`` and have ZERO
    ``identity_problems("B", ...)``. No V0n-local identity schema, no
    weakened comparison: a missing/malformed raw source or any frozen-
    field drift fails closed here. The returned identity additionally
    cross-binds the V0n launch law (NVIDIA ICD + Vulkan selector index
    + CUDA removed) to the SAME accepted physical subject.
    """
    if not isinstance(observation, dict):
        raise PhysicalDiagnosticError("V0n identity observation malformed")
    problems = I.identity_problems(V0N_IDENTITY_ARM, observation)
    if problems:
        raise PhysicalDiagnosticError(
            "V0n subject identity problems: " + "; ".join(problems))
    derived = I.derive_identity_from_raw(
        V0N_IDENTITY_ARM, observation["raw"])
    identity = {"identity_schema": I.IDENTITY_SCHEMA}
    for field in V0N_IDENTITY_FIELDS:
        if field == "selector":
            identity["selector"] = dict(
                I.frozen_identity(V0N_IDENTITY_ARM)["selector"])
        else:
            identity[field] = derived[field]
    # Cross-bind the selector/index/environment law to the accepted
    # subject: the units launch through the SAME NVIDIA ICD and the
    # SAME frozen Vulkan selector index with CUDA removed.
    if (identity["icd"] != V0N_NVIDIA_ICD
            or identity["selector"]["GGML_VK_VISIBLE_DEVICES"] != "0"
            or identity["selector"]["CUDA_VISIBLE_DEVICES"] != "-1"):
        raise PhysicalDiagnosticError(
            "V0n selector law diverges from the accepted #248 subject")
    if runtime is not None:
        for field in V0N_RUNTIME_FIELDS:
            value = runtime.get(field) if isinstance(runtime, dict) else None
            if not isinstance(value, str) or not value:
                raise PhysicalDiagnosticError(
                    f"V0n runtime identity field missing: {field}")
            identity[f"runtime_{field}"] = value
    return identity


def _v0n_identity_digest(identity: dict[str, Any]) -> str:
    return D.sha256_bytes(json.dumps(
        identity, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False).encode())


def _v0n_identity_matches(frozen_identity: dict[str, Any],
                          observed: dict[str, Any]) -> None:
    """Require a fresh identity to EQUAL the retained freeze identity.

    Both sides are COMPLETE derived identities. Any drift in any bound
    field — GPU UUID, BDF, PCI/subsystem/revision/link identity,
    kernel/NVIDIA driver, ICD, Vulkan device UUID/name/API/driver,
    selector, or the mid-screen runtime fields — fails closed.
    """
    if not isinstance(frozen_identity, dict) or not isinstance(observed, dict):
        raise PhysicalDiagnosticError("V0n identity record malformed")
    for field in sorted(set(frozen_identity) | set(observed)):
        if frozen_identity.get(field) != observed.get(field):
            raise PhysicalDiagnosticError(
                f"V0n subject identity drift: {field} (observed "
                f"{observed.get(field)!r} != frozen "
                f"{frozen_identity.get(field)!r})")


def _v0n_identity_matches_authority(identity: Any) -> bool:
    """An identity record equals the accepted #248 authority constants.

    Authority is NOT proven by the record's own digest (self-consistent
    forgeries recompute digests). It is proven field-by-field against
    ``issue248_identity.frozen_identity("B")`` — the accepted constants
    — plus the required runtime fields and the accepted selector law.
    """
    if not isinstance(identity, dict):
        return False
    try:
        frozen = I.frozen_identity(V0N_IDENTITY_ARM)
    except Exception:
        return False
    if identity.get("identity_schema") != I.IDENTITY_SCHEMA:
        return False
    for field in V0N_IDENTITY_FIELDS:
        if identity.get(field) != frozen[field]:
            return False
    for field in V0N_RUNTIME_FIELDS:
        value = identity.get(f"runtime_{field}")
        if not isinstance(value, str) or not value:
            return False
    return True


def _v0n_freeze_digest(record: dict[str, Any]) -> str:
    """Canonical digest over the freeze record (same law as _v0_digest)."""
    return _v0_digest(record)


def _v0n_require_freeze_authority(freeze: dict[str, Any],
                                  authority: dict[str, Any]) -> None:
    """The freeze is bound to exactly the live dispatch authority."""
    if freeze.get("dispatch_sha256") != D.authority_digest(authority):
        raise PhysicalDiagnosticError(
            "V0n screen freeze dispatch authority mismatch")


def _verify_v0n_selector_law(freeze: dict[str, Any]) -> None:
    """The freeze's selector/index law matches the frozen launch env.

    The unit environment (v0n_environment) and the freeze must select
    the SAME Vulkan index through the SAME NVIDIA ICD with CUDA
    removed — the cross-binding between the #248 physical subject and
    the selector the units actually launch under.
    """
    selector = freeze.get("vulkan_selector")
    cuda_law = freeze.get("cuda_law")
    if (not isinstance(selector, dict)
            or selector.get("GGML_VK_VISIBLE_DEVICES") != "0"
            or selector.get("VK_ICD_FILENAMES") != V0N_NVIDIA_ICD
            or not isinstance(cuda_law, dict)
            or cuda_law.get("CUDA_VISIBLE_DEVICES") != "-1"):
        raise PhysicalDiagnosticError(
            "V0n selector/index law diverges from the retained freeze")


def _read_v0n_screen_freeze(root: Path, expected_head: str) -> dict[str, Any]:
    """Load and fully authenticate the retained V0n screen freeze.

    The freeze is the ONLY identity authority for the V0n screening
    population: it binds the accepted #248 Arm-B subject identity
    (UUID/BDF/PCI/driver/ICD/Vulkan + selector law + runtime identity)
    to the exact PR head, the V0n namespace/arm, the pinned comparator
    and the live dispatch authority. A re-signed or tampered freeze
    whose identity no longer equals the accepted #248 constants fails
    closed even when its canonical digest is internally consistent.
    """
    path = Path(root) / V0N_FREEZE_NAME
    if path.is_symlink() or not path.is_file():
        raise PhysicalDiagnosticError("V0n screen freeze record missing")
    try:
        record = json.loads(path.read_bytes())
    except (ValueError, OSError) as exc:
        raise PhysicalDiagnosticError("V0n screen freeze unreadable") from exc
    if not isinstance(record, dict):
        raise PhysicalDiagnosticError("V0n screen freeze malformed")
    identity = record.get("subject_identity")
    if (record.get("schema") != V0N_FREEZE_SCHEMA
            or record.get("producer") != V0N_FREEZE_PRODUCER
            or record.get("expected_pr_head") != expected_head
            or record.get("namespace") != V0N_NAMESPACE
            or record.get("arm") != V0N_ARM
            or record.get("identity_arm") != V0N_IDENTITY_ARM
            or not isinstance(identity, dict)
            or not _v0n_identity_matches_authority(identity)
            or identity.get("gpu_uuid") != record.get("gpu_uuid")
            or identity.get("bdf") != record.get("bdf")
            or record.get("subject_identity_sha256")
               != _v0n_identity_digest(identity)
            or record.get("source_pin") != V0N_SOURCE_PIN
            or record.get("binary_sha256") != V0N_COMPARATOR_SHA
            or record.get("llama_source_pin") != V0N_SOURCE_PIN
            or record.get("icd") != V0N_NVIDIA_ICD
            or record.get("vulkan_selector") != {
                "GGML_VK_VISIBLE_DEVICES": "0",
                "VK_ICD_FILENAMES": V0N_NVIDIA_ICD}
            or record.get("cuda_law") != {
                "CUDA_VISIBLE_DEVICES": "-1",
                "link_family_cuda_exclusion": True}
            or record.get("observer_libraries") != dict(V0_OBSERVER_LIBS)
            or record.get("canonical_digest_sha256")
               != _v0n_freeze_digest(record)
            or not isinstance(record.get("dispatch_sha256"), str)):
        raise PhysicalDiagnosticError(
            "V0n screen freeze digest/head/identity-authority mismatch")
    return record


def write_v0n_screen_freeze(repo_root: Path, evidence_root: Path, *,
                            binary: Path, binary_id: str,
                            model_dir: Path, expected_head: str,
                            model_attestation: dict[str, Any],
                            revalidate_authority: Callable[..., dict[str, Any]] | None = None,
                            identity_observer: Callable[[], dict[str, Any]] | None = None,
                            runtime_observer: Callable[[], dict[str, Any]] | None = None,
                            github_api: str = "https://api.github.com"
                            ) -> dict[str, Any]:
    """Freeze the V0n screen identity from FRESH #248 Arm-B authority.

    PROSPECTIVE, repository-only: no model load, no probe, no inference
    unit. Must run AFTER the V0n dispatch is live and BEFORE the first
    V0n unit. The identity is NOT re-invented: a fresh
    ``issue248_identity.observe_arm_identity("B")`` raw observation is
    required to have zero identity problems, the complete identity is
    derived through the accepted machinery, and the freeze binds it to
    the exact PR head + live dispatch authority + pinned comparator.
    Append-only: an existing freeze is refused, so no later unit can
    silently re-choose a different physical subject.
    """
    if binary_id != "comparator" or str(model_dir) != D.MODEL_DIR:
        raise PhysicalDiagnosticError(
            "V0n freeze frozen comparator/model identity mismatch")
    root = Path(evidence_root)
    validate_evidence_generation(root)
    _admit_retained_cost(root, TB.V0N_CONDITION, V0N_NAMESPACE, V0N_ARM)
    early = require_live_dispatch(repo_root, expected_head, V0N_NAMESPACE,
                                  revalidate_authority, github_api)
    D._require_clean_head(Path(repo_root), expected_head)
    target = root / V0N_FREEZE_NAME
    if target.exists() or target.is_symlink():
        raise PhysicalDiagnosticError("V0n screen freeze already retained")
    if (root / V0N_NAMESPACE).exists():
        raise PhysicalDiagnosticError(
            "V0n screen freeze must precede the first inference unit")
    binary_sha = _verify_v0n_binary(Path(binary), binary_id)
    attestation = validate_model_attestation(model_attestation, expected_head)
    opening = root / MODEL_ATTESTATION_OPEN_NAME
    if (opening.is_symlink() or not opening.is_file()
            or json.loads(opening.read_bytes()) != attestation):
        raise PhysicalDiagnosticError(
            "V0n screen freeze model attestation absent")
    problems, _ = attestation_witness(Path(model_dir), attestation)
    if problems or str(model_dir) != D.MODEL_DIR:
        raise PhysicalDiagnosticError("V0n screen freeze model witness drift")
    if identity_observer is not None:
        observation = identity_observer()
    else:
        observation = I.observe_arm_identity(V0N_IDENTITY_ARM)
    runtime = (runtime_observer or _v0n_observe_runtime)()
    identity = v0n_identity_from_observation(observation, runtime=runtime)
    late = require_live_dispatch(repo_root, expected_head, V0N_NAMESPACE,
                                 revalidate_authority, github_api)
    if D.authority_digest(early) != D.authority_digest(late):
        raise PhysicalDiagnosticError("V0n screen freeze dispatch drift")
    D._require_clean_head(Path(repo_root), expected_head)
    _admit_retained_cost(root, TB.V0N_CONDITION, V0N_NAMESPACE, V0N_ARM)
    record = {
        "schema": V0N_FREEZE_SCHEMA, "producer": V0N_FREEZE_PRODUCER,
        "expected_pr_head": expected_head,
        "namespace": V0N_NAMESPACE, "arm": V0N_ARM,
        "identity_arm": V0N_IDENTITY_ARM,
        "identity_authority": (
            "scripts/issue248_identity.py — accepted #248 Arm-B reference "
            "machinery (observe_arm_identity/identity_problems/"
            "derive_identity_from_raw); no V0n-local identity schema"),
        "subject_identity": identity,
        "subject_identity_sha256": _v0n_identity_digest(identity),
        "gpu_uuid": identity["gpu_uuid"], "bdf": identity["bdf"],
        "icd": V0N_NVIDIA_ICD,
        "vulkan_selector": {"GGML_VK_VISIBLE_DEVICES": "0",
                            "VK_ICD_FILENAMES": V0N_NVIDIA_ICD},
        "cuda_law": {"CUDA_VISIBLE_DEVICES": "-1",
                     "link_family_cuda_exclusion": True},
        "source_pin": V0N_SOURCE_PIN, "llama_source_pin": V0N_SOURCE_PIN,
        "binary_sha256": binary_sha,
        "comparator_sha256": V0N_COMPARATOR_SHA,
        "observer_libraries": dict(V0_OBSERVER_LIBS),
        "dispatch_sha256": D.authority_digest(early),
    }
    record["canonical_digest_sha256"] = _v0n_freeze_digest(record)
    _write_json(target, record)
    # Re-authenticate the retained bytes exactly as later consumers will.
    frozen = _read_v0n_screen_freeze(root, expected_head)
    if frozen["canonical_digest_sha256"] != record["canonical_digest_sha256"]:
        raise PhysicalDiagnosticError("V0n screen freeze retention mismatch")
    return record


def _v0n_observe_device() -> dict[str, Any]:
    """Fresh V0n device observation bound to #248 Arm-B authority.

    Read-only: the accepted #248 raw identity observation (sysfs +
    nvidia-smi + ICD inventory + per-ICD vulkaninfo), the live runtime
    identity, and the NVIDIA Vulkan enumeration. The returned record
    carries the COMPLETE derived subject identity so callers can
    require exact equality with the retained V0n freeze — vendor/
    device/driver-ID alone is never physical identity.
    """
    if socket.gethostname() != V0N_HOST:
        raise PhysicalDiagnosticError("V0n host must be inferswarm01")
    icd = Path(V0N_NVIDIA_ICD)
    if not icd.is_file():
        raise PhysicalDiagnosticError("NVIDIA ICD unavailable")
    observation = I.observe_arm_identity(V0N_IDENTITY_ARM)
    runtime = _v0n_observe_runtime()
    identity = v0n_identity_from_observation(observation, runtime=runtime)
    result = subprocess.run(
        ["vulkaninfo", "--summary"], capture_output=True, text=True,
        timeout=30, check=True,
        env={**os.environ, "VK_ICD_FILENAMES": V0N_NVIDIA_ICD,
             "CUDA_VISIBLE_DEVICES": "-1"})
    blocks = re.split(r"(?=GPU[0-9]+:\s*)", result.stdout)
    devices: dict[int, dict[str, str]] = {}
    for block in blocks:
        m = re.match(r"GPU(\d+):\s*", block)
        if m:
            devices[int(m.group(1))] = {
                key: match.group(1).strip() for key, pattern in {
                    "vendor_id": r"vendorID\s*=\s*(0x[0-9a-f]+)",
                    "device_id": r"deviceID\s*=\s*(0x[0-9a-f]+)",
                    "name": r"deviceName\s*=\s*(.+)",
                    "driver_id": r"driverID\s*=\s*(.+)",
                    "driver_info": r"driverInfo\s*=\s*(.+)",
                    "driver_version": r"driverVersion\s*=\s*(.+)",
                    "api_version": r"apiVersion\s*=\s*(.+)",
                }.items() if (match := re.search(pattern, block, re.I))}
    if (set(devices) != {0}
            or devices[0].get("vendor_id") != V0N_GPU_VENDOR_ID
            or devices[0].get("device_id") != V0N_GPU_DEVICE_ID
            or devices[0].get("driver_id") != V0N_DRIVER_ID):
        raise PhysicalDiagnosticError(
            "exactly one NVIDIA RTX 3060 Vulkan device required")
    import platform
    runtime_record = {"kernel": platform.release(),
                      "vulkan_instance": (re.search(
                          r"Vulkan Instance Version:\s*(\S+)", result.stdout)
                          or [None, ""])[1],
                      "devices": {str(i): entry
                                  for i, entry in devices.items()}}
    return {"index": 0, **devices[0],
            "vulkan_indices": sorted(devices),
            "enumeration_sha256": D.sha256_bytes(result.stdout.encode()),
            "icd_sha256": D.file_sha256(icd),
            "runtime_identity": runtime_record,
            "host": V0N_HOST,
            "subject_identity": identity,
            "subject_identity_sha256": _v0n_identity_digest(identity)}


def _verify_v0n_binary(binary: Path, binary_id: str) -> str:
    """Exact comparator executable + observer library family + NO CUDA.

    Same observer-library digest law as the AMD leg (the identical
    build family), plus the explicit CUDA-exclusion link check: the
    loaded ggml backend set must contain libggml-vulkan and must NOT
    contain any CUDA backend library under the NVIDIA ICD environment.
    """
    if (V0N_SOURCE_PIN != D.LLAMA_PIN
            or V0N_COMPARATOR_SHA != D.SERVER_BINARIES["comparator"]
            or binary_id != "comparator"
            or verify_binary(binary, binary_id) != V0N_COMPARATOR_SHA):
        raise PhysicalDiagnosticError(
            "V0n requires exact pinned comparator observer")
    for name, digest in V0_OBSERVER_LIBS.items():
        path = binary.parent / name
        if not path.is_file() or D.file_sha256(path) != digest:
            raise PhysicalDiagnosticError(f"V0n observer library mismatch: {name}")
    env = {**os.environ, "LD_LIBRARY_PATH": str(binary.parent),
           "VK_ICD_FILENAMES": V0N_NVIDIA_ICD, "CUDA_VISIBLE_DEVICES": "-1"}
    dep = subprocess.run(["ldd", str(binary)], env=env, capture_output=True,
                         text=True, timeout=20, check=True)
    if ("not found" in dep.stdout or "libggml-vulkan.so.0" not in dep.stdout
            or any(str(binary.parent / name) not in dep.stdout
                   for name in V0_OBSERVER_LIBS)):
        raise PhysicalDiagnosticError("V0n observer dynamic loader incompatibility")
    if re.search(r"libggml-cuda|libcuda\b|libcudart", dep.stdout):
        raise PhysicalDiagnosticError(
            "V0n CUDA library in the comparator link family is forbidden")
    help_run = subprocess.run([str(binary), "--help"], env=env,
                              capture_output=True, timeout=30)
    if help_run.returncode != 0 or b"--n-gpu-layers" not in (
            help_run.stdout + help_run.stderr):
        raise PhysicalDiagnosticError("V0n observer non-model execution failed")
    return V0N_COMPARATOR_SHA


def _v0n_require_unique_accepted_row(rows, uuid: str, bus: str,
                                     where: str) -> Any:
    """The ONE canonical GPU-row targeting law, shared by the live
    producer (_v0n_gpu_vram_bytes) and the canonical residency-evidence
    validator (_v0n_validate_residency_evidence): the population must
    contain EXACTLY ONE row matching BOTH the accepted GPU UUID and the
    accepted BDF. Zero matches reject; a SECOND row for the same
    accepted UUID+BDF rejects even when its memory field differs —
    memory never disambiguates physical identity. Returns the unique
    matching row.
    """
    matches = [row for row in rows if row[0] == uuid and row[1] == bus]
    if len(matches) != 1:
        raise PhysicalDiagnosticError(
            f"{where} requires exactly one row matching accepted "
            f"UUID+BDF, found {len(matches)} of {len(rows)} GPU row(s)")
    return matches[0]


def _v0n_gpu_vram_bytes(smi_runner: Callable[..., Any] | None = None,
                        gpu_uuid: str | None = None,
                        bdf: str | None = None
                        ) -> tuple[int, dict[str, Any]]:
    """Live memory usage of the ACCEPTED physical GPU (read-only).

    Targets the accepted #248 subject by BOTH GPU UUID and BDF — never
    enumeration order, never an unqualified one-line population. Parses
    every returned GPU row, requires exactly one row matching BOTH the
    accepted UUID and the accepted BDF, and returns only that row's
    memory. Zero matches, duplicate matches, and malformed rows all
    fail closed. (Defaults resolve the accepted #248 authority
    constants; tests inject explicit values.)
    """
    frozen = I.frozen_identity(V0N_IDENTITY_ARM)
    uuid = gpu_uuid if gpu_uuid is not None else frozen["gpu_uuid"]
    bus = bdf if bdf is not None else frozen["bdf"]
    run = smi_runner or subprocess.run
    proc = run(
        ["nvidia-smi",
         "--query-gpu=uuid,pci.bus_id,memory.used",
         "--format=csv,noheader,nounits"],
        capture_output=True, text=True, timeout=30, check=True)
    rows: list[tuple[str, str, str]] = []
    evidence: dict[str, Any] = {"gpu_uuid": uuid, "bdf": bus,
                                "population": []}
    for line in str(proc.stdout).splitlines():
        fields = [f.strip() for f in line.split(",")]
        if not any(fields):
            continue
        evidence["population"].append(fields)
        if len(fields) != 3 or not fields[0].startswith("GPU-") \
                or not _V0N_BDF_RE.fullmatch(fields[1]) \
                or not fields[2].isdigit():
            raise PhysicalDiagnosticError(
                "V0n nvidia-smi GPU row malformed")
        rows.append((fields[0], fields[1], fields[2]))
    selected_row = _v0n_require_unique_accepted_row(
        rows, uuid, bus, "V0n targeted nvidia-smi read")
    evidence["selected_row"] = list(selected_row)
    return int(selected_row[2]) * 1024 * 1024, evidence


def _v0n_validate_residency_evidence(vram_evidence: Any,
                                     identity: dict[str, Any],
                                     vram_before: Any,
                                     vram_after: Any) -> None:
    """Canonical fail-closed targeted residency-evidence contract.

    ONE contract shared by placement validation (live results) and
    retained-receipt validation (unit.json custody): the production
    shape emitted by _real_v0n_execute —

        vram_evidence = {
          "before": {"gpu_uuid", "bdf", "population",
                     "selected_row": [uuid, bdf, memory_mib]},
          "after":  {...same record shape...},
        }

    The retired test-only flat {"selected_row": ...} shape is NOT a
    valid contract anywhere (no physical V0n evidence exists yet, so
    no backward-compatibility path is required).

    For BOTH "before" and "after", fail closed unless:
      - the phase record is a dict naming EXACTLY the accepted freeze
        subject gpu_uuid and bdf;
      - selected_row is exactly a valid 3-field [uuid, bdf, memory]
        row whose uuid/bdf EQUAL the accepted freeze values and whose
        memory field is a decimal nonnegative string;
      - the selected memory (MiB -> bytes) EXACTLY equals the
        corresponding vram_before / vram_after integer;
      - the population is a list of valid 3-field rows containing
        EXACTLY ONE row matching BOTH the accepted UUID and the
        accepted BDF (the SAME targeting law as the live
        _v0n_gpu_vram_bytes producer), and that unique matching row
        IS the selected row — a second row for the accepted UUID+BDF
        rejects even when its memory field differs, and rows for
        OTHER UUID/BDF combinations remain permitted.
    """
    if not isinstance(vram_evidence, dict):
        raise PhysicalDiagnosticError(
            "V0n canonical residency evidence missing or not a dict")
    uuid = identity["gpu_uuid"]
    bus = identity["bdf"]
    for phase, bound in (("before", vram_before), ("after", vram_after)):
        if type(bound) is not int or bound < 0:
            raise PhysicalDiagnosticError(
                f"V0n residency {phase} measurement is not a "
                f"nonnegative integer")
        record = vram_evidence.get(phase)
        if (not isinstance(record, dict)
                or record.get("gpu_uuid") != uuid
                or record.get("bdf") != bus):
            raise PhysicalDiagnosticError(
                f"V0n residency {phase} record does not name the "
                f"accepted UUID+BDF subject")
        selected = record.get("selected_row")
        population = record.get("population")
        if (not isinstance(selected, list) or len(selected) != 3
                or not _v0n_valid_population_row(selected)):
            raise PhysicalDiagnosticError(
                f"V0n residency {phase} selected_row is not a valid "
                f"3-field [uuid, bdf, memory] row")
        sel_uuid, sel_bus, sel_mem = selected
        if sel_uuid != uuid or sel_bus != bus:
            raise PhysicalDiagnosticError(
                f"V0n residency {phase} selected_row is not the "
                f"accepted UUID+BDF row")
        if not isinstance(population, list) or not population:
            raise PhysicalDiagnosticError(
                f"V0n residency {phase} population missing or empty")
        for row in population:
            if not _v0n_valid_population_row(row):
                raise PhysicalDiagnosticError(
                    f"V0n residency {phase} population row malformed")
        # Canonical targeting law (correction: the reviewed head
        # counted exact selected-row duplicates, so a second row for
        # the accepted UUID+BDF with a DIFFERENT memory value slipped
        # through — the live producer's len(matches)==1 UUID+BDF law
        # is now enforced identically here, via the ONE shared helper).
        unique = _v0n_require_unique_accepted_row(
            population, uuid, bus,
            f"V0n residency {phase} population")
        if list(unique) != list(selected):
            raise PhysicalDiagnosticError(
                f"V0n residency {phase} selected row is not the unique "
                f"accepted UUID+BDF population row")
        if int(sel_mem) * 1024 * 1024 != bound:
            raise PhysicalDiagnosticError(
                f"V0n residency {phase} selected-row memory does not "
                f"cross-bind to the retained {phase} byte count")


def _v0n_valid_population_row(row: Any) -> bool:
    """A valid nvidia-smi population row: exactly [uuid, bdf, memory]."""
    return (isinstance(row, list) and len(row) == 3
            and all(isinstance(field, str) for field in row)
            and row[0].startswith("GPU-")
            and _V0N_BDF_RE.fullmatch(row[1]) is not None
            and row[2].isdigit())


def _v0n_verify_placement(unit_dir: Path, device: dict[str, Any],
                          result: dict[str, Any],
                          binary_lib_dir: str,
                          freeze: dict[str, Any] | None = None
                          ) -> None:
    """Pinned source law + NVIDIA Vulkan backend + no-CUDA + residency.

    Fail closed if: CUDA participation is not explicitly false; the
    backend is not Vulkan; the selected device index/identity drifts
    from the live enumeration; the canonical before+after residency
    evidence does not cross-bind to the accepted freeze UUID+BDF with
    memory consistent with vram_before/vram_after; or the
    selected-GPU residency delta under the ngl=1 load does not exceed
    the frozen bound.

    CORRECTION (NO-GO 5874443020): when the retained V0n freeze is
    supplied, the observation's COMPLETE derived subject identity
    (UUID/BDF/PCI/driver/ICD/Vulkan/runtime) must EQUAL the freeze —
    vendor/device/driver-ID alone is no longer sufficient physical
    identity.

    CORRECTION (residency-shape): the validator now consumes the
    production residency shape (nested before+after records from
    _v0n_gpu_vram_bytes) through the ONE shared fail-closed helper
    _v0n_validate_residency_evidence; the retired test-only flat
    {"selected_row": ...} shape is rejected everywhere.
    """
    if (device.get("vendor_id") != V0N_GPU_VENDOR_ID
            or device.get("device_id") != V0N_GPU_DEVICE_ID
            or device.get("driver_id") != V0N_DRIVER_ID
            or result.get("vulkan_device_index") != device.get("index")
            or result.get("backend") != "Vulkan"
            or result.get("cuda_participation") is not False):
        raise PhysicalDiagnosticError(
            "V0n pinned source/NVIDIA Vulkan placement unverified")
    if freeze is not None:
        _v0n_identity_matches(freeze["subject_identity"],
                              device.get("subject_identity"))
    # Canonical residency-evidence custody (correction: the reviewed
    # head read a test-only FLAT vram_evidence["selected_row"] that the
    # production executor never emits). With a freeze the records must
    # cross-bind BOTH before+after to the SAME accepted #248 UUID+BDF;
    # without a freeze the executor's own targeted-selection law is
    # still enforced end-to-end through the shared helper.
    identity_source = (freeze["subject_identity"] if freeze is not None
                       else I.frozen_identity(V0N_IDENTITY_ARM))
    _v0n_validate_residency_evidence(
        result.get("vram_evidence"), identity_source,
        result.get("vram_before"), result.get("vram_after"))
    before, after = result.get("vram_before"), result.get("vram_after")
    if not (isinstance(before, int) and isinstance(after, int)
            and after - before > V0N_MIN_RESIDENCY_BYTES):
        raise PhysicalDiagnosticError(
            "V0n selected-GPU ngl=1 residency unverified")
    del unit_dir, binary_lib_dir


def _real_v0n_execute(argv: list[str], env: dict[str, str],
                      request: dict[str, Any], prompt: str, port: int,
                      unit_dir: Path, timeout_budget: dict[str, Any]
                      ) -> dict[str, Any]:
    """NVIDIA fresh-process unit; GPU residency measured while loaded.

    Residency is measured on the ACCEPTED physical GPU (targeted
    UUID+BDF selection via _v0n_gpu_vram_bytes), never an unqualified
    one-line population; the evidence block naming the selected row is
    retained in the result.
    """
    before, vram_before_evidence = _v0n_gpu_vram_bytes()
    with (unit_dir / "server.log").open("wb") as log:
        proc = subprocess.Popen(argv, env={**os.environ, **env}, stdout=log,
                                stderr=subprocess.STDOUT, start_new_session=True)
        try:
            _wait_healthy(proc, port)
            after, vram_after_evidence = _v0n_gpu_vram_bytes()
            attribution = _proc_attribution(proc, argv, env)
            _v0_check_live_process(proc, argv, env)
            raw, response = _http_completion(
                port, request, prompt, timeout_s=timeout_budget["budget_s"])
            return {"response_raw": raw, "tokens": response.get("tokens"),
                    "process_attribution": attribution,
                    "vulkan_device_index": int(env["GGML_VK_VISIBLE_DEVICES"]),
                    "vram_before": before, "vram_after": after,
                    "vram_evidence": {"before": vram_before_evidence,
                                      "after": vram_after_evidence},
                    "backend": "Vulkan", "cuda_participation": False,
                    "timeout_budget": timeout_budget}
        finally:
            if proc.poll() is None:
                os.killpg(proc.pid, signal.SIGTERM)
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(proc.pid, signal.SIGKILL)
                    proc.wait(timeout=5)


def run_v0n_unit(repo_root: Path, evidence_root: Path, namespace: str,
                 arm: str, tag: str, *, binary: Path, binary_id: str,
                 model_dir: Path, expected_head: str,
                 model_attestation: dict[str, Any],
                 execute: Callable[..., dict[str, Any]] | None = None,
                 revalidate_authority: Callable[..., dict[str, Any]] | None = None,
                 device_observer: Callable[[], dict[str, Any]] | None = None,
                 github_api: str = "https://api.github.com"
                 ) -> dict[str, Any]:
    """One canonical V0n unit; exact-head two-pass authority and row order.

    Mirrors run_v0_unit with the NVIDIA-current law: no two-index AMD
    selector preflight (exactly one NVIDIA Vulkan device exists), no
    cross-die freeze; instead the retained V0n screen freeze binds the
    accepted #248 Arm-B subject identity (UUID/BDF/PCI/driver/ICD/
    Vulkan/runtime + selector law) and EVERY unit reobserves that
    complete identity live BEFORE launch and again AFTER execution,
    requiring exact equality with the freeze both times (NO-GO
    correction 5874443020). Fails closed on any identity/backend/
    placement/custody mismatch and on any attempt to execute the third
    unit without a verified byte-identical first pair.
    """
    if ((namespace, arm) != (V0N_NAMESPACE, V0N_ARM)
            or tag not in V0N_UNIT_TAGS):
        raise PhysicalDiagnosticError("V0n namespace/arm/plan mismatch")
    if binary_id != "comparator" or str(model_dir) != D.MODEL_DIR:
        raise PhysicalDiagnosticError(
            "V0n frozen comparator/model identity mismatch")
    root = Path(evidence_root)
    validate_evidence_generation(root)
    _admit_retained_cost(root, TB.V0N_CONDITION, namespace, arm)
    early = require_live_dispatch(repo_root, expected_head, namespace,
                                  revalidate_authority, github_api)
    D._require_clean_head(Path(repo_root), expected_head)
    # The retained V0n screen freeze is the population's identity
    # authority: it must exist, authenticate against the accepted #248
    # constants, and bind exactly the live dispatch.
    freeze = _read_v0n_screen_freeze(root, expected_head)
    _v0n_require_freeze_authority(freeze, early)
    index = V0N_UNIT_TAGS.index(tag)
    rows = _v0n_retained_rows(root, index, expected_head, early)
    if index == 2 and rows[0] != rows[1]:
        raise PhysicalDiagnosticError(
            "V0n variable pair forbids third unit")
    fixtures = verify_fixtures(Path(repo_root))
    binary_sha = _verify_v0n_binary(Path(binary), binary_id)
    attestation = validate_model_attestation(model_attestation, expected_head)
    opening = root / MODEL_ATTESTATION_OPEN_NAME
    if (opening.is_symlink() or not opening.is_file() or json.loads(
            opening.read_bytes()) != attestation):
        raise PhysicalDiagnosticError(
            "V0n opening attestation missing or drifted")
    problems, witness = attestation_witness(Path(model_dir), attestation)
    if problems or attestation["model_dir"] != str(Path(model_dir)):
        raise PhysicalDiagnosticError("V0n model identity drift")
    fixture = fixtures[D.CASE]
    if len(fixture["prompt_token_ids"]) != TB.V0N_PROMPT_TOKENS:
        raise PhysicalDiagnosticError("V0n frozen prompt-token count drift")
    request = D.validate_request_contract(D.REQUEST_CONTRACT)
    budget = TB.v0n_request_timeout(len(fixture["prompt_token_ids"]))
    argv = v0n_server_argv(Path(binary), Path(model_dir) / D.MODEL_MEMBER_1)
    budget["vulkan_device_index"] = 0
    late = require_live_dispatch(repo_root, expected_head, namespace,
                                 revalidate_authority, github_api)
    if D.authority_digest(early) != D.authority_digest(late):
        raise PhysicalDiagnosticError("V0n live dispatch drift")
    D._require_clean_head(Path(repo_root), expected_head)
    _v0n_retained_rows(root, index, expected_head, late)
    _admit_retained_cost(root, TB.V0N_CONDITION, namespace, arm)
    # PRE-LAUNCH identity law: reobserve the complete #248 Arm-B
    # identity fresh and require EXACT equality with the retained
    # freeze (UUID/BDF/PCI/driver/ICD/Vulkan/runtime/selector). No
    # model launch is permitted from a drifted identity.
    device_pre = (device_observer or _v0n_observe_device)()
    _v0n_identity_matches(freeze["subject_identity"],
                          device_pre.get("subject_identity"))
    _verify_v0n_selector_law(freeze)
    unit_dir = prepare_unit_dir(root, namespace, tag)
    env = dict(v0n_environment(unit_dir))
    env["LD_LIBRARY_PATH"] = str(Path(binary).parent)
    try:
        result = (execute or _real_v0n_execute)(
            argv=argv, env=env, request=request,
            prompt=fixture["prompt_text"], port=PORT, unit_dir=unit_dir,
            timeout_budget=budget)
        # POST-EXECUTION identity law: reobserve the complete identity
        # again and require exact equality with the SAME freeze before
        # any row/receipt is accepted. A physical run from a drifted
        # identity can never become numerical evidence.
        device = (device_observer or _v0n_observe_device)()
        _v0n_identity_matches(freeze["subject_identity"],
                              device.get("subject_identity"))
        _v0n_verify_placement(unit_dir, device, result,
                              str(Path(binary).parent), freeze)
    except Exception as exc:
        _write_json(unit_dir / "failure.json", {
            "schema": "inferswarm.issue250.v0n-failed-unit/1",
            "tag": tag, "head_sha": expected_head,
            "reason": str(exc), "failed_at": _utcnow()})
        raise
    row_path = unit_dir / "obs.row0.f32"
    if row_path.is_symlink() or not row_path.is_file():
        raise PhysicalDiagnosticError("V0n full decision-0 row missing")
    row = row_path.read_bytes()
    if len(row) != D.ROW_BYTES:
        raise PhysicalDiagnosticError("V0n full decision-0 row malformed")
    attribution = result.get("process_attribution")
    if (not isinstance(attribution, dict)
            or type(attribution.get("server_pid")) is not int
            or attribution["server_pid"] <= 0
            or attribution.get("server_exe_sha256") != binary_sha
            or attribution.get("server_argv") != argv
            or attribution.get("server_env") != env):
        raise PhysicalDiagnosticError("V0n fresh process attribution unverified")
    for prior_tag in V0N_UNIT_TAGS[:index]:
        prior = json.loads(
            (root / namespace / prior_tag / "unit.json").read_bytes())
        if prior["server_pid"] == attribution["server_pid"]:
            raise PhysicalDiagnosticError("V0n fresh process PID reused")
    receipt = {"schema": D.V0N_SCHEMA, "tag": tag, "namespace": namespace,
               "arm": arm, "head_sha": expected_head,
               "evidence_generation": EVIDENCE_GENERATION,
               "decision0_row_sha256": D.sha256_bytes(row),
               "row_bytes": len(row),
               "authority_sha256": D.authority_digest(late),
               "v0n_freeze_digest": freeze["canonical_digest_sha256"],
               "v0n_subject_identity": copy.deepcopy(
                   freeze["subject_identity"]),
               "v0n_subject_identity_sha256": freeze[
                   "subject_identity_sha256"],
               "prelaunch_identity_sha256": device_pre.get(
                   "subject_identity_sha256"),
               "postexec_identity_sha256": device.get(
                   "subject_identity_sha256"),
               "gpu_uuid": freeze["gpu_uuid"], "bdf": freeze["bdf"],
               "vulkan_selector": dict(freeze["vulkan_selector"]),
               "placement_verified": True,
               "vram_before": result["vram_before"],
               "vram_after": result["vram_after"],
               "vram_evidence": copy.deepcopy(result["vram_evidence"]),
               "nvidia_device": device,
               "case_id": D.CONTRAST_CASE, "ngl": 1, "backend": "Vulkan",
               "cuda_participation": False,
               "embedding_placement": "CPU",
               "output_projection_placement": "Vulkan",
               "placement_source_law": {
                   "source_pin": V0N_SOURCE_PIN, "ngl": 1,
                   "embedding": "CPU", "output_projection": "Vulkan"},
               "model_dir": D.MODEL_DIR,
               "model_launch_member": str(Path(model_dir) / D.MODEL_MEMBER_1),
               "model_member_sha256": D.MODEL_MEMBER_SHA256[D.MODEL_MEMBER_1],
               "prompt_sha256": D.sha256_bytes(json.dumps(
                   fixture["prompt_token_ids"], separators=(",", ":")).encode()),
               "prompt_token_ids": fixture["prompt_token_ids"],
               "prompt_text_sha256": D.sha256_bytes(
                   fixture["prompt_text"].encode()),
               "prompt_len": len(fixture["prompt_token_ids"]),
               "request_contract": request,
               "request_contract_sha256": D.canonical_request_digest(request),
               "fresh_process": True,
               "server_pid": attribution["server_pid"],
               "binary_sha256": binary_sha,
               "model_stat_witness": witness,
               "server_argv": argv, "server_env": env,
               "process_attribution": attribution,
               "timeout_policy": budget,
               "response_raw_sha256": D.sha256_bytes(result["response_raw"])}
    _write_json(unit_dir / "unit.json", receipt)
    return receipt


def _v0n_retained_rows(root: Path, count: int, head: str,
                       authority: dict[str, Any]) -> list[str]:
    """Recheck each V0n predecessor against retained full-row bytes/custody.

    The whole retained V0n population must share ONE authenticated V0n
    screen freeze (the accepted #248 Arm-B physical subject: GPU UUID,
    BDF, PCI/subsystem/revision/link identity, kernel/NVIDIA driver,
    ICD, Vulkan device UUID/name/API/driver, selector law, runtime
    identity) and the frozen NVIDIA Vulkan environment law. CORRECTION
    (NO-GO 5874443020): mixed-identity populations (driver/runtime/
    ICD/Vulkan/UUID/BDF drift between repeats), mixed freeze digests,
    and CUDA-tainted populations are all rejected even if every
    receipt is individually valid and vendor/device/driver-ID match.
    CORRECTION (residency custody): every retained receipt must ALSO
    carry the canonical before+after targeted residency evidence,
    independently revalidated against the authenticated freeze
    (accepted UUID+BDF identity, exact vram_before/vram_after
    cross-binding, reapplied minimum residency delta) —
    placement_verified alone is not placement proof.
    """
    import hashlib
    rows: list[str] = []
    base = Path(root) / V0N_NAMESPACE
    if base.is_symlink():
        raise PhysicalDiagnosticError("V0n namespace symlink refused")
    freeze = _read_v0n_screen_freeze(Path(root), head)
    _v0n_require_freeze_authority(freeze, authority)
    if base.exists():
        present = {p.name for p in base.iterdir()
                   if p.is_dir() or p.is_symlink()}
        if present != set(V0N_UNIT_TAGS[:count]):
            raise PhysicalDiagnosticError(
                "V0n unexpected/partial/future unit population")
    elif count:
        raise PhysicalDiagnosticError("V0n predecessor namespace missing")
    for tag in V0N_UNIT_TAGS[:count]:
        directory = base / tag
        receipt_path = directory / "unit.json"
        row_path = directory / "obs.row0.f32"
        if (directory.is_symlink() or receipt_path.is_symlink()
                or row_path.is_symlink() or not receipt_path.is_file()
                or not row_path.is_file()):
            raise PhysicalDiagnosticError("V0n predecessor retained row missing")
        try:
            receipt = json.loads(receipt_path.read_bytes())
            raw = row_path.read_bytes()
        except (OSError, ValueError) as exc:
            raise PhysicalDiagnosticError("V0n predecessor unreadable") from exc
        digest = hashlib.sha256(raw).hexdigest()
        if (len(raw) != D.ROW_BYTES or not isinstance(receipt, dict)
                or receipt.get("schema") != D.V0N_SCHEMA
                or receipt.get("tag") != tag
                or receipt.get("namespace") != V0N_NAMESPACE
                or receipt.get("arm") != V0N_ARM
                or receipt.get("head_sha") != head
                or receipt.get("evidence_generation") != EVIDENCE_GENERATION
                or receipt.get("decision0_row_sha256") != digest
                or receipt.get("authority_sha256")
                   != D.authority_digest(authority)
                or receipt.get("placement_verified") is not True
                or receipt.get("fresh_process") is not True
                or receipt.get("case_id") != D.CONTRAST_CASE
                or receipt.get("ngl") != 1
                or receipt.get("backend") != "Vulkan"
                or receipt.get("cuda_participation") is not False
                or receipt.get("model_dir") != D.MODEL_DIR
                or receipt.get("model_member_sha256") !=
                   D.MODEL_MEMBER_SHA256[D.MODEL_MEMBER_1]
                or receipt.get("request_contract") != D.REQUEST_CONTRACT
                or receipt.get("prompt_token_ids") is None
                or D.sha256_bytes(json.dumps(
                    receipt["prompt_token_ids"], separators=(",", ":")).encode())
                   != receipt.get("prompt_sha256")
                or receipt.get("row_bytes") != D.ROW_BYTES
                or type(receipt.get("server_pid")) is not int
                or receipt["server_pid"] <= 0
                or not isinstance(receipt.get("nvidia_device"), dict)
                or receipt["nvidia_device"].get("vendor_id") != V0N_GPU_VENDOR_ID
                or receipt["nvidia_device"].get("device_id") != V0N_GPU_DEVICE_ID
                or receipt["nvidia_device"].get("driver_id") != V0N_DRIVER_ID
                or receipt["binary_sha256"] != V0N_COMPARATOR_SHA
                or not isinstance(receipt.get("server_env"), dict)
                or receipt["server_env"].get("VK_ICD_FILENAMES") != V0N_NVIDIA_ICD
                or receipt["server_env"].get("CUDA_VISIBLE_DEVICES") != "-1"
                or receipt["server_env"].get("GGML_VK_VISIBLE_DEVICES") != "0"
                or not isinstance(receipt.get("server_argv"), list)
                or not receipt["server_argv"]
                or receipt["server_argv"] != v0n_server_argv(
                    Path(receipt["server_argv"][0]),
                    Path(receipt.get("model_launch_member", "")), PORT)
                or receipt.get("model_launch_member") !=
                   str(Path(D.MODEL_DIR) / D.MODEL_MEMBER_1)
                or receipt.get("placement_source_law") != {
                    "source_pin": V0N_SOURCE_PIN, "ngl": 1,
                    "embedding": "CPU", "output_projection": "Vulkan"}
                or receipt.get("embedding_placement") != "CPU"
                or receipt.get("output_projection_placement") != "Vulkan"
                or receipt.get("v0n_freeze_digest")
                   != freeze["canonical_digest_sha256"]
                or receipt.get("v0n_subject_identity_sha256")
                   != freeze["subject_identity_sha256"]
                or receipt.get("v0n_subject_identity")
                   != freeze["subject_identity"]
                or receipt.get("gpu_uuid") != freeze["gpu_uuid"]
                or receipt.get("bdf") != freeze["bdf"]
                or receipt.get("vulkan_selector") != freeze["vulkan_selector"]
                or not isinstance(
                    receipt.get("prelaunch_identity_sha256"), str)
                or not isinstance(
                    receipt.get("postexec_identity_sha256"), str)
                or receipt["prelaunch_identity_sha256"]
                   != freeze["subject_identity_sha256"]
                or receipt["postexec_identity_sha256"]
                   != freeze["subject_identity_sha256"]
                or not isinstance(
                    receipt.get("nvidia_device", {}).get(
                        "subject_identity"), dict)
                or receipt["nvidia_device"]["subject_identity"]
                   != freeze["subject_identity"]):
            raise PhysicalDiagnosticError(
                "V0n predecessor retained byte/custody mismatch")
        if (receipt.get("process_attribution", {}).get("server_env")
                != receipt["server_env"]
                or receipt.get("process_attribution", {}).get("server_argv")
                != receipt["server_argv"]
                or receipt.get("process_attribution", {}).get("server_exe_sha256")
                != V0N_COMPARATOR_SHA
                or receipt.get("process_attribution", {}).get("server_pid")
                != receipt["server_pid"]):
            raise PhysicalDiagnosticError(
                "V0n predecessor process attribution mismatch")
        # Independent residency re-authentication: placement_verified
        # alone is not placement proof. The retained canonical
        # before+after residency evidence is revalidated against the
        # SAME authenticated freeze (accepted #248 UUID+BDF), the
        # selected memory values must cross-bind exactly to the
        # retained vram_before/vram_after, and the minimum residency
        # delta is reapplied — missing, malformed, flat/test-only,
        # altered, mixed-GPU, UUID/BDF-drifted, or memory-inconsistent
        # receipts reject before any numerical row is returned.
        _v0n_validate_residency_evidence(
            receipt.get("vram_evidence"), freeze["subject_identity"],
            receipt.get("vram_before"), receipt.get("vram_after"))
        if not (isinstance(receipt.get("vram_before"), int)
                and isinstance(receipt.get("vram_after"), int)
                and receipt["vram_after"] - receipt["vram_before"]
                > V0N_MIN_RESIDENCY_BYTES):
            raise PhysicalDiagnosticError(
                "V0n predecessor retained residency delta unverified")
        rows.append(digest)
    return rows


def run_v0_binding_preflight(repo_root: Path, evidence_root: Path, *,
                             binary: Path, model_dir: Path, expected_head: str,
                             model_attestation: dict[str, Any],
                             revalidate_authority: Callable[..., dict[str, Any]] | None = None,
                             probe_load: Callable[..., dict[str, Any]] | None = None,
                             device_observer: Callable[[int], dict[str, Any]] | None = None,
                             github_api: str = "https://api.github.com"
                             ) -> dict[str, Any]:
    """Prospective post-dispatch #243-style two-index physical binding.

    This function is NOT called by repository validation. No preflight load
    may occur until fresh exact-head V0 dispatch, cost/model/clean-head
    authorities all pass. The evidence root is append-only on any failure.
    """
    root = Path(evidence_root)
    validate_evidence_generation(root)
    _admit_retained_cost(root, TB.V0_CONDITION, V0_NAMESPACE, V0_ARM)
    early = require_live_dispatch(repo_root, expected_head, V0_NAMESPACE,
                                  revalidate_authority, github_api)
    D._require_clean_head(Path(repo_root), expected_head)
    binary_sha = _verify_v0_amd_binary(Path(binary), "comparator")
    attestation = validate_model_attestation(model_attestation, expected_head)
    opening = root / MODEL_ATTESTATION_OPEN_NAME
    if (opening.is_symlink() or not opening.is_file()
            or json.loads(opening.read_bytes()) != attestation):
        raise PhysicalDiagnosticError("V0 preflight model attestation absent")
    problems, _ = attestation_witness(Path(model_dir), attestation)
    if problems or str(model_dir) != D.MODEL_DIR:
        raise PhysicalDiagnosticError("V0 preflight model witness drift")
    target = root / "v0-selector-binding.json"
    probe_dir = root / "v0-selector-preflight"
    if (target.exists() or target.is_symlink() or probe_dir.exists()
            or probe_dir.is_symlink()):
        raise PhysicalDiagnosticError("V0 selector preflight already retained")
    observer = device_observer or _v0_observe_device
    live = observer(0)
    if (live.get("vulkan_indices") != [0, 1]
            or live.get("vendor_id") != "0x1002"
            or live.get("device_id") != "0x6864"
            or not isinstance(live.get("drm_cards"), dict)):
        raise PhysicalDiagnosticError("V0 preflight V340L substrate unavailable")
    live["binary_lib_dir"] = str(Path(binary).parent)
    late = require_live_dispatch(repo_root, expected_head, V0_NAMESPACE,
                                 revalidate_authority, github_api)
    if D.authority_digest(early) != D.authority_digest(late):
        raise PhysicalDiagnosticError("V0 preflight dispatch drift")
    D._require_clean_head(Path(repo_root), expected_head)
    _admit_retained_cost(root, TB.V0_CONDITION, V0_NAMESPACE, V0_ARM)
    probe_dir.mkdir()  # append-only; any failed probe remains visible
    mapping: dict[str, Any] = {}
    for index in (0, 1):
        current = observer(index)
        current["binary_lib_dir"] = str(Path(binary).parent)
        if any(current.get(k) != live.get(k) for k in (
                "vulkan_indices", "enumeration_sha256", "icd_sha256",
                "runtime_identity", "drm_cards")):
            raise PhysicalDiagnosticError("V0 preflight enumeration drift")
        # Revalidate dispatch before EVERY physical load-only probe.
        new = require_live_dispatch(repo_root, expected_head, V0_NAMESPACE,
                                    revalidate_authority, github_api)
        if D.authority_digest(new) != D.authority_digest(early):
            raise PhysicalDiagnosticError("V0 preflight dispatch changed")
        D._require_clean_head(Path(repo_root), expected_head)
        _admit_retained_cost(root, TB.V0_CONDITION, V0_NAMESPACE, V0_ARM)
        probe = (probe_load or _v0_probe_load)(
            Path(binary), Path(model_dir) / D.MODEL_MEMBER_1,
            index, live["drm_cards"], probe_dir)
        before, after = probe["vram_before"], probe["vram_after"]
        dies = live["drm_cards"]
        if (probe.get("index") != index or set(before) != set(dies)
                or set(after) != set(dies)):
            raise PhysicalDiagnosticError("V0 preflight malformed probe")
        selected = max(dies, key=lambda b: after[b] - before[b])
        excluded = next(b for b in dies if b != selected)
        entry = {"selected_bdf": selected, "excluded_bdf": excluded,
                 "selected_card": dies[selected], "excluded_card": dies[excluded],
                 "vram_before": before, "vram_after": after}
        if (after[selected] - before[selected] <= V0_MIN_SELECTED_BYTES
                or after[excluded] - before[excluded] >= V0_EXCLUDED_NOISE_BYTES
                or probe.get("process_attribution", {}).get("server_exe_sha256")
                   != V0_COMPARATOR_SHA
                or probe["process_attribution"].get("server_argv") !=
                   v0_server_argv(Path(binary), Path(model_dir) / D.MODEL_MEMBER_1)
                or probe["process_attribution"].get("server_env", {}).get(
                    "GGML_VK_VISIBLE_DEVICES") != str(index)):
            raise PhysicalDiagnosticError("V0 preflight selector/residency unproven")
        mapping[str(index)] = entry
        _write_json(probe_dir / f"index-{index}.json", probe)
    if mapping["0"]["selected_bdf"] == mapping["1"]["selected_bdf"]:
        raise PhysicalDiagnosticError("V0 preflight duplicate selector-to-BDF")
    record = {"schema": V0_BINDING_SCHEMA, "host": "inferswarm05",
              "producer": V0_BINDING_PRODUCER, "expected_pr_head": expected_head,
              "source_pin": V0_SOURCE_PIN, "binary_sha256": binary_sha,
              "binary_path": str(Path(binary)),
              "binary_lib_dir": str(Path(binary).parent),
              "icd": V0_RADV_ICD, "cuda_visible_devices": "-1",
              "enumeration_sha256": live["enumeration_sha256"],
              "icd_sha256": live["icd_sha256"],
              # AMENDMENT-006: retain the CANONICAL runtime identity, so
              # the retained record equals its own JSON bytes regardless
              # of the observer's device-map key spelling.
              "runtime_identity": _v0_normalize_runtime_identity(
                  live["runtime_identity"]),
              "drm_cards": live["drm_cards"], "mapping": mapping,
              "preflight_probe_sha256": {str(i): D.file_sha256(
                  probe_dir / f"index-{i}.json") for i in (0, 1)},
              "dispatch_sha256": D.authority_digest(early)}
    record["canonical_digest_sha256"] = _v0_digest(record)
    validate_v0_selector_binding(record, expected_head, 0, live, binary_sha)
    _write_json(target, record)
    return record


def run_v0_unit(repo_root: Path, evidence_root: Path, namespace: str, arm: str,
                tag: str, *, binary: Path, binary_id: str, model_dir: Path,
                expected_head: str, model_attestation: dict[str, Any],
                execute: Callable[..., dict[str, Any]] | None = None,
                revalidate_authority: Callable[..., dict[str, Any]] | None = None,
                vulkan_device_index: int | None = None,
                device_observer: Callable[[int], dict[str, Any]] | None = None,
                github_api: str = "https://api.github.com") -> dict[str, Any]:
    """One canonical V0 unit; exact-head two-pass authority and row order."""
    if (namespace, arm) != (V0_NAMESPACE, V0_ARM) or tag not in V0_UNIT_TAGS:
        raise PhysicalDiagnosticError("V0 namespace/arm/plan mismatch")
    if binary_id != "comparator" or str(model_dir) != D.MODEL_DIR:
        raise PhysicalDiagnosticError("V0 frozen comparator/model identity mismatch")
    root = Path(evidence_root)
    validate_evidence_generation(root)
    _admit_retained_cost(root, TB.V0_CONDITION, namespace, arm)
    early = require_live_dispatch(repo_root, expected_head, namespace,
                                  revalidate_authority, github_api)
    D._require_clean_head(Path(repo_root), expected_head)
    index = V0_UNIT_TAGS.index(tag)
    rows = _v0_retained_rows(root, index, expected_head, early)
    if index == 2 and rows[0] != rows[1]:
        raise PhysicalDiagnosticError("V0 variable pair forbids third unit")
    fixtures = verify_fixtures(Path(repo_root))
    binary_sha = _verify_v0_amd_binary(Path(binary), binary_id)
    attestation = validate_model_attestation(model_attestation, expected_head)
    opening = root / MODEL_ATTESTATION_OPEN_NAME
    if opening.is_symlink() or not opening.is_file() or json.loads(
            opening.read_bytes()) != attestation:
        raise PhysicalDiagnosticError("V0 opening attestation missing or drifted")
    problems, witness = attestation_witness(Path(model_dir), attestation)
    if problems or attestation["model_dir"] != str(Path(model_dir)):
        raise PhysicalDiagnosticError("V0 model identity drift")
    if type(vulkan_device_index) is not int or vulkan_device_index < 0:
        raise PhysicalDiagnosticError("V0 AMD Vulkan device index required")
    # CORRECTION (one-factor V0): the selector/device is NOT a free
    # per-unit choice. Exactly one index/BDF pair is canonically frozen
    # for the whole screening population by the retained append-only
    # v0-screen-freeze record, derived from the validated two-index
    # preflight. Any other index fails closed BEFORE any launch; a
    # failure can never silently move the population to the sibling die.
    freeze, binding = _v0_load_freeze_with_preflight(root, expected_head, early)
    if (vulkan_device_index != freeze["v0_screen_vulkan_index"]):
        raise PhysicalDiagnosticError(
            "V0 unit selector does not match the frozen screen device")
    device = (device_observer or _v0_observe_device)(vulkan_device_index)
    if (device.get("index") != vulkan_device_index
            or device.get("vendor_id") != "0x1002"
            or not device.get("name")):
        raise PhysicalDiagnosticError("V0 AMD device identity unverified")
    # A physical #243-style load-only binding is a required future artifact;
    # this correction creates no model load and cannot fabricate one.
    binding_path = root / "v0-selector-binding.json"
    if binding_path.is_symlink() or not binding_path.is_file():
        raise PhysicalDiagnosticError("fresh V0 selector binding record missing")
    try:
        binding = json.loads(binding_path.read_bytes())
    except (ValueError, OSError) as exc:
        raise PhysicalDiagnosticError("V0 selector binding unreadable") from exc
    device["binary_lib_dir"] = str(Path(binary).parent)
    selected = validate_v0_selector_binding(
        binding, expected_head, vulkan_device_index, device, binary_sha)
    _v0_verify_probe_records(binding, root, early)
    fixture = fixtures[D.CASE]
    if len(fixture["prompt_token_ids"]) != TB.V0_PROMPT_TOKENS:
        raise PhysicalDiagnosticError("V0 frozen prompt-token count drift")
    request = D.validate_request_contract(D.REQUEST_CONTRACT)
    budget = TB.v0_request_timeout(len(fixture["prompt_token_ids"]))
    argv = v0_server_argv(Path(binary), Path(model_dir) / D.MODEL_MEMBER_1)
    budget["vulkan_device_index"] = vulkan_device_index
    late = require_live_dispatch(repo_root, expected_head, namespace,
                                 revalidate_authority, github_api)
    if D.authority_digest(early) != D.authority_digest(late):
        raise PhysicalDiagnosticError("V0 live dispatch drift")
    D._require_clean_head(Path(repo_root), expected_head)
    _v0_retained_rows(root, index, expected_head, late)
    _admit_retained_cost(root, TB.V0_CONDITION, namespace, arm)
    unit_dir = prepare_unit_dir(root, namespace, tag)
    env = v0_environment(vulkan_device_index, unit_dir, binding)
    try:
        result = (execute or _real_v0_execute)(
            argv=argv, env=env, request=request, prompt=fixture["prompt_text"],
            port=PORT, unit_dir=unit_dir, timeout_budget=budget,
            device_binding=binding)
        _v0_verify_placement(unit_dir, device, result, binding)
    except Exception as exc:
        # The partial unit is permanently retained, never silently retried or
        # selected around. Manual quarantine is required for any rerun.
        _write_json(unit_dir / "failure.json", {
            "schema": "inferswarm.issue250.v0-failed-unit/1",
            "tag": tag, "head_sha": expected_head,
            "reason": str(exc), "failed_at": _utcnow()})
        raise
    row_path = unit_dir / "obs.row0.f32"
    if row_path.is_symlink() or not row_path.is_file():
        raise PhysicalDiagnosticError("V0 full decision-0 row missing")
    row = row_path.read_bytes()
    if len(row) != D.ROW_BYTES:
        raise PhysicalDiagnosticError("V0 full decision-0 row malformed")
    attribution = result.get("process_attribution")
    if (not isinstance(attribution, dict)
            or type(attribution.get("server_pid")) is not int
            or attribution["server_pid"] <= 0
            or attribution.get("server_exe_sha256") != binary_sha
            or attribution.get("server_argv") != argv
            or attribution.get("server_env") != env):
        raise PhysicalDiagnosticError("V0 fresh process attribution unverified")
    for prior_tag in V0_UNIT_TAGS[:index]:
        prior = json.loads((root / namespace / prior_tag / "unit.json").read_bytes())
        if prior["server_pid"] == attribution["server_pid"]:
            raise PhysicalDiagnosticError("V0 fresh process PID reused")
    receipt = {"schema": D.V0_SCHEMA, "tag": tag, "namespace": namespace,
               "arm": arm, "head_sha": expected_head,
               "evidence_generation": EVIDENCE_GENERATION,
               "decision0_row_sha256": D.sha256_bytes(row),
               "row_bytes": len(row), "authority_sha256": D.authority_digest(late),
               "placement_verified": True, "amd_device": device,
               "v0_selector_binding": binding,
               "selected_bdf": selected["selected_bdf"],
               "excluded_bdf": selected["excluded_bdf"],
               "vram_before": result["vram_before"],
               "vram_after": result["vram_after"],
               "placement_source_law": {
                   "source_pin": V0_SOURCE_PIN, "ngl": 1,
                   "embedding": "CPU", "output_projection": "Vulkan"},
               "case_id": D.CONTRAST_CASE, "ngl": 1, "backend": "Vulkan",
               "embedding_placement": "CPU",
               "output_projection_placement": "Vulkan",
               "model_dir": str(model_dir),
               "model_launch_member": str(Path(model_dir) / D.MODEL_MEMBER_1),
               "model_member_sha256": D.MODEL_MEMBER_SHA256[D.MODEL_MEMBER_1],
               "prompt_sha256": D.sha256_bytes(json.dumps(
                   fixture["prompt_token_ids"], separators=(",", ":")).encode()),
               "prompt_token_ids": fixture["prompt_token_ids"],
               "prompt_text_sha256": D.sha256_bytes(
                   fixture["prompt_text"].encode()),
               "prompt_len": len(fixture["prompt_token_ids"]),
               "request_contract": request,
               "request_contract_sha256": D.canonical_request_digest(request),
               "fresh_process": True,
               "server_pid": attribution["server_pid"],
               "binary_sha256": binary_sha, "model_stat_witness": witness,
               "server_argv": argv, "server_env": env,
               "process_attribution": attribution,
               "timeout_policy": budget,
               "response_raw_sha256": D.sha256_bytes(result["response_raw"])}
    _write_json(unit_dir / "unit.json", receipt)
    return receipt



def fetch_dispatch_authority(repo_root: Path, expected_head: str,
                             namespace: str,
                             github_api: str = "https://api.github.com",
                             ) -> dict[str, Any]:
    """Fetch and verify the live #250 dispatch comment (fail-closed).

    Mirrors the accepted #248 fetcher: GET-only, paginated, clean
    exact-head worktree, live PR state (OPEN, unmerged, base main,
    head == expected_head), live Issue #250 state (OPEN), OWNER/MEMBER
    top-level PR-conversation comment carrying the exact dispatch
    phrase / ``head=<sha>`` / one ``diagnostic-namespace=`` / one
    ``arm=`` stripped lines with the namespace<->arm pair exactly
    bound (issue250_diagnostic.NAMESPACE_ARM_BINDING).
    """
    if namespace != V0_NAMESPACE:
        D.validate_namespace(namespace)
    D._require_clean_head(Path(repo_root), expected_head)
    headers = {"Accept": "application/vnd.github+json",
               "User-Agent": "inferswarm-issue250-diagnostic"}
    token = os.environ.get("GH_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"

    def _get_json(path: str) -> Any:
        url = f"{github_api}/repos/Zutfen-LLC/inferswarm/{path}"
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=30) as response:
            return json.loads(response.read())

    pr = _get_json(f"pulls/{D.DIAGNOSTIC_PR_NUMBER}")
    if pr.get("state") != "open" or pr.get("merged"):
        raise D.DiagnosticError(
            f"PR #{D.DIAGNOSTIC_PR_NUMBER} is not open/unmerged "
            f"(state={pr.get('state')!r}, merged={pr.get('merged')!r})")
    if pr.get("base", {}).get("ref") != "main":
        raise D.DiagnosticError(
            f"PR #{D.DIAGNOSTIC_PR_NUMBER} base is not main: "
            f"{pr.get('base', {}).get('ref')!r}")
    if pr.get("head", {}).get("sha") != expected_head:
        raise D.DiagnosticError(
            f"GitHub PR head {pr.get('head', {}).get('sha')} != expected "
            f"{expected_head}")
    issue = _get_json(f"issues/{D.DIAGNOSTIC_ISSUE}")
    if issue.get("state") != "open":
        raise D.DiagnosticError(
            f"Issue #{D.DIAGNOSTIC_ISSUE} is not open "
            f"(state={issue.get('state')!r})")
    comments: list[dict[str, Any]] = []
    page = 1
    while True:
        batch = _get_json(
            f"issues/{D.DIAGNOSTIC_PR_NUMBER}/comments"
            f"?page={page}&per_page=100")
        if not isinstance(batch, list) or not batch:
            break
        comments.extend(batch)
        if len(batch) < 100:
            break
        page += 1
        if page > 50:
            raise D.DiagnosticError("unbounded comment pagination")
    for comment in comments:
        if D.DIAGNOSTIC_DISPATCH_PHRASE not in str(comment.get("body")):
            continue
        # The arm line is parsed from the comment body; the exact
        # namespace<->arm pair is enforced by validate_authority_payload.
        body_lines = [ln.strip()
                      for ln in str(comment.get("body")).splitlines()]
        arms = [ln.split("=", 1)[1] for ln in body_lines
                if ln.startswith("arm=")]
        authority = {
            "comment_id": comment.get("id"),
            "issue_url": comment.get("issue_url"),
            "author_association": comment.get("author_association"),
            "created_at": comment.get("created_at"),
            "body": comment.get("body"),
            "head_sha": expected_head,
            "namespace": namespace,
            "open_pr": True,
            "issue_open": True,
            "arm": arms[0] if len(arms) == 1 else None,
        }
        try:
            if namespace == V0_NAMESPACE:
                return validate_v0_dispatch(
                    namespace, V0_ARM, authority, expected_head)
            if namespace == V0N_NAMESPACE:
                return validate_v0n_dispatch(
                    namespace, V0N_ARM, authority, expected_head)
            return D.validate_authority_payload(authority, expected_head)
        except (D.DiagnosticError, PhysicalDiagnosticError):
            continue
    raise D.DiagnosticError(
        f"no valid dispatch authority for head {expected_head} "
        f"namespace {namespace}")


def require_live_dispatch(repo_root: Path, expected_head: str,
                          namespace: str,
                          revalidate_authority: Any = None,
                          github_api: str = "https://api.github.com",
                          ) -> dict[str, Any]:
    """MANDATORY live revalidation; omission never disables it."""
    if revalidate_authority is None:
        revalidate_authority = fetch_dispatch_authority
    authority = revalidate_authority(repo_root, expected_head, namespace,
                                     github_api)
    if namespace == V0_NAMESPACE:
        return validate_v0_dispatch(namespace, V0_ARM, authority, expected_head)
    if namespace == V0N_NAMESPACE:
        return validate_v0n_dispatch(namespace, V0N_ARM, authority,
                                     expected_head)
    return D.validate_authority_payload(authority, expected_head)


# ---------------------------------------------------------------------------
# Fixtures, binaries, campaign model attestation (#248 architecture)
# ---------------------------------------------------------------------------

def verify_fixtures(repo_root: Path) -> dict[str, Any]:
    """Load and sha-verify the accepted historical fixture ladder."""
    path = Path(repo_root) / D.FIXTURE_LADDER_REL
    raw = path.read_bytes()
    digest = D.sha256_bytes(raw)
    if digest != D.FIXTURE_LADDER_SHA256:
        raise PhysicalDiagnosticError(
            f"fixture ladder sha drift: {digest} != {D.FIXTURE_LADDER_SHA256}")
    doc = json.loads(raw)
    cases = doc.get("cases")
    if not isinstance(cases, list):
        raise PhysicalDiagnosticError("fixture ladder is not a case list")
    fixtures: dict[str, Any] = {}
    for entry in cases:
        case = entry.get("case_id")
        ids = entry.get("prompt_token_ids")
        if (not isinstance(case, str) or case in fixtures
                or not isinstance(ids, list) or len(ids) < 8
                or any(type(t) is not int for t in ids)
                or not isinstance(entry.get("prompt_text"), str)
                or not entry["prompt_text"]):
            raise PhysicalDiagnosticError(f"fixture entry malformed: {case}")
        fixtures[case] = entry
    for case in ("case-256", "case-1024", "case-3072"):
        if case not in fixtures:
            raise PhysicalDiagnosticError(f"fixture case missing: {case}")
    return fixtures


def verify_binary(path: Path, binary_id: str) -> str:
    """Verify an executing binary is one of the accepted builds."""
    if binary_id not in D.SERVER_BINARIES:
        raise PhysicalDiagnosticError(f"unknown binary id: {binary_id}")
    digest = D.file_sha256(path)
    if digest != D.SERVER_BINARIES[binary_id]:
        raise PhysicalDiagnosticError(
            f"binary sha mismatch for {binary_id}: {digest}")
    return digest


def attestation_canonical_digest(doc: dict[str, Any]) -> str:
    payload = {key: value for key, value in doc.items()
               if key not in ("attestation_sha256", "closing_sha256")}
    return D.sha256_bytes(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode())


def observe_model_stats(model_dir: Path,
                        stat_fn: Callable[[Path], Any] | None = None,
                        ) -> dict[str, dict[str, Any]]:
    """Live per-member file-identity observation (lstat; no byte reads)."""
    import stat as stat_module
    stat_fn = stat_fn or os.lstat
    model_dir = Path(model_dir)
    if not model_dir.is_dir():
        raise D.DiagnosticError(
            f"model dir is not a directory: {model_dir}")
    present = sorted(p.name for p in model_dir.iterdir()
                     if p.suffix == ".gguf")
    if present != sorted(D.MODEL_MEMBERS):
        raise D.DiagnosticError(
            f"unexpected split topology in {model_dir}: {present}")
    out: dict[str, dict[str, Any]] = {}
    for member in D.MODEL_MEMBERS:
        path = model_dir / member
        info = stat_fn(path)
        mode = info.st_mode
        if stat_module.S_ISLNK(mode):
            raise D.DiagnosticError(f"model member is a symlink: {path}")
        if not stat_module.S_ISREG(mode):
            raise D.DiagnosticError(
                f"model member is not a regular file: {path}")
        out[member] = {
            "bytes": info.st_size, "device": info.st_dev,
            "inode": info.st_ino, "mtime_ns": info.st_mtime_ns,
            "ctime_ns": info.st_ctime_ns,
            "symlink": False, "regular_file": True}
    return out


def build_model_attestation(model_dir: Path, expected_head: str, *,
                            hasher: Callable[[Path], str] | None = None,
                            stat_observer=None) -> dict[str, Any]:
    """Opening attestation: full three-member hash + stat witnesses.

    The single full ~72.5 GiB verification against the accepted #241
    digests, performed ONCE per campaign (Issue #250 efficiency rule).
    """
    hasher = hasher or D.file_sha256
    stats = (stat_observer or observe_model_stats)(model_dir)
    members = []
    for member in D.MODEL_MEMBERS:
        path = Path(model_dir) / member
        digest = hasher(path)
        if digest != D.MODEL_MEMBER_SHA256[member]:
            raise D.DiagnosticError(
                f"model member sha mismatch for {member}: {digest} != "
                f"{D.MODEL_MEMBER_SHA256[member]}")
        members.append({"name": member, "path": str(path),
                        "sha256": digest, **stats[member]})
    doc: dict[str, Any] = {
        "schema": MODEL_ATTESTATION_OPEN_SCHEMA,
        "head_sha": expected_head,
        "model_dir": str(Path(model_dir)),
        "members": sorted(members, key=lambda m: m["name"]),
    }
    doc["attestation_sha256"] = attestation_canonical_digest(doc)
    return doc


def _validate_member_entries(doc: dict[str, Any]) -> None:
    members = doc.get("members")
    if (not isinstance(members, list) or len(members) != len(D.MODEL_MEMBERS)
            or any(not isinstance(m, dict) for m in members)):
        raise D.DiagnosticError("attestation member population malformed")
    names = sorted(m["name"] for m in members)
    if names != sorted(D.MODEL_MEMBERS) or len(set(names)) != len(names):
        raise D.DiagnosticError(
            "attestation member names do not match the accepted set")
    for member in members:
        name = member["name"]
        if member.get("path") != str(Path(doc["model_dir"]) / name):
            raise D.DiagnosticError(f"attestation path mismatch: {name}")
        if member.get("sha256") != D.MODEL_MEMBER_SHA256[name]:
            raise D.DiagnosticError(
                f"attestation digest is not the accepted value: {name}")
        if member.get("symlink") is not False or (
                member.get("regular_file") is not True):
            raise D.DiagnosticError(
                f"attestation file status malformed: {name}")
        for key in WITNESS_STAT_KEYS:
            if type(member.get(key)) is not int or member[key] < 0:
                raise D.DiagnosticError(
                    f"attestation witness field {key} malformed: {name}")


def validate_model_attestation(doc: Any,
                               expected_head: str | None = None,
                               ) -> dict[str, Any]:
    if not isinstance(doc, dict) or doc.get(
            "schema") != MODEL_ATTESTATION_OPEN_SCHEMA:
        raise D.DiagnosticError("opening attestation schema mismatch")
    head = doc.get("head_sha")
    if (not isinstance(head, str)
            or not re.fullmatch(r"[0-9a-f]{40}", head)):
        raise D.DiagnosticError("opening attestation head is not a 40-hex sha")
    if expected_head is not None and head != expected_head:
        raise D.DiagnosticError(
            f"opening attestation binds head {head} != expected "
            f"{expected_head}")
    if doc.get("model_dir") != D.MODEL_DIR:
        raise D.DiagnosticError(
            f"opening attestation model dir mismatch: "
            f"{doc.get('model_dir')!r}")
    _validate_member_entries(doc)
    if doc.get("attestation_sha256") != attestation_canonical_digest(doc):
        raise D.DiagnosticError("opening attestation canonical digest mismatch")
    return doc


def validate_closing_attestation(doc: Any,
                                 opening: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(doc, dict) or doc.get(
            "schema") != MODEL_ATTESTATION_CLOSE_SCHEMA:
        raise D.DiagnosticError("closing attestation schema mismatch")
    if doc.get("opening_attestation_sha256") != opening.get(
            "attestation_sha256"):
        raise D.DiagnosticError(
            "closing attestation is not bound to the opening attestation")
    for key in ("head_sha", "model_dir"):
        if doc.get(key) != opening.get(key):
            raise D.DiagnosticError(
                f"closing attestation {key} differs from the opening")
    _validate_member_entries(doc)
    if doc.get("members") != opening.get("members"):
        raise D.DiagnosticError(
            "closing attestation members differ from the opening "
            "(digest or stat drift between open and close)")
    if doc.get("closing_sha256") != attestation_canonical_digest(doc):
        raise D.DiagnosticError("closing attestation canonical digest mismatch")
    return doc


def attestation_witness(model_dir: Path, attestation: dict[str, Any], *,
                        stat_observer=None
                        ) -> tuple[list[str], dict[str, Any] | None]:
    """Cheap fail-closed pre-unit identity check (no member byte reads)."""
    validate_model_attestation(attestation)
    try:
        observed = (stat_observer or observe_model_stats)(model_dir)
    except D.DiagnosticError as exc:
        return [str(exc)], None
    problems: list[str] = []
    for member in attestation["members"]:
        name = member["name"]
        live = observed.get(name)
        if live is None:
            problems.append(f"{name}: missing from live model topology")
            continue
        for key in WITNESS_STAT_KEYS:
            if live.get(key) != member.get(key):
                problems.append(
                    f"{name}: {key} drift ({live.get(key)!r} != "
                    f"{member.get(key)!r})")
    witness = {m["name"]: {key: observed[m["name"]][key]
                           for key in WITNESS_STAT_KEYS}
               for m in attestation["members"]} if not problems else None
    return problems, witness


def open_campaign_attestation(evidence_root: Path, model_dir: Path,
                              expected_head: str,
                              hasher: Callable[[Path], str] | None = None,
                              ) -> dict[str, Any]:
    """Build and durably retain the campaign OPENING model attestation."""
    evidence_root = Path(evidence_root)
    doc = build_model_attestation(model_dir, expected_head,
                                  hasher=hasher or D.file_sha256)
    target = evidence_root / MODEL_ATTESTATION_OPEN_NAME
    if target.exists() or target.is_symlink():
        raise PhysicalDiagnosticError(
            f"opening attestation already retained (append-only): {target}")
    evidence_root.mkdir(parents=True, exist_ok=True)
    _write_json(target, doc)
    return doc


def close_campaign_attestation(evidence_root: Path, model_dir: Path,
                               expected_head: str,
                               hasher: Callable[[Path], str] | None = None,
                               ) -> dict[str, Any]:
    """Campaign closing full re-hash bound to the retained opening."""
    evidence_root = Path(evidence_root)
    opening_path = evidence_root / MODEL_ATTESTATION_OPEN_NAME
    if opening_path.is_symlink() or not opening_path.is_file():
        raise PhysicalDiagnosticError(
            "closing requires a retained opening attestation")
    opening = json.loads(opening_path.read_bytes())
    validate_model_attestation(opening, expected_head)
    fresh = build_model_attestation(model_dir, expected_head,
                                    hasher=hasher or D.file_sha256)
    doc = {key: value for key, value in fresh.items()
           if key != "attestation_sha256"}
    doc["schema"] = MODEL_ATTESTATION_CLOSE_SCHEMA
    doc["opening_attestation_sha256"] = opening["attestation_sha256"]
    doc["closing_sha256"] = attestation_canonical_digest(doc)
    validate_closing_attestation(doc, opening)
    target = evidence_root / MODEL_ATTESTATION_CLOSE_NAME
    if target.exists() or target.is_symlink():
        raise PhysicalDiagnosticError(
            f"closing attestation already retained (append-only): {target}")
    _write_json(target, doc)
    return doc


# ---------------------------------------------------------------------------
# Arm-D ladder fixture derivation (frozen, predeclared)
# ---------------------------------------------------------------------------

def derive_ladder_prompt(base_prompt: str, length: int,
                         base_repeats: int) -> str:
    """Derive a ladder-length prompt by the accepted derivation rule.

    The accepted ladder fixtures are a frozen prologue + N repeats of
    one sentence block + a frozen suffix. A ladder prompt at length L
    uses the SAME prologue/suffix with the sentence repeat count from
    the frozen ARM_D_LADDER_SENTENCE_REPEATS table (predeclared in
    scripts/issue250_diagnostic.py before any execution; never picked
    after seeing outputs).

    CORRECTION PASS 3 (NO-GO 5847890177, blocker 4A): the old
    signature carried ``base_tokens`` but never used it, implying the
    nominal ladder label was a token length. It is not: the label is
    a TEXT GENERATION PARAMETER. The actual token count is derived
    separately through the pinned-server tokenizer authority
    (``tokenize_prompt`` / tokenizer receipts) and retained per unit.
    """
    if length not in D.ARM_D_LADDER_SENTENCE_REPEATS:
        raise PhysicalDiagnosticError(
            f"length {length} is not in the predeclared ladder")
    if base_repeats <= 0:
        raise PhysicalDiagnosticError("malformed base fixture")
    return _scale_sentence_block(base_prompt, base_repeats,
                                 D.ARM_D_LADDER_SENTENCE_REPEATS[length])


def _scale_sentence_block(prompt: str, base_repeats: int,
                          target_repeats: int) -> str:
    if target_repeats == base_repeats:
        return prompt
    # The accepted sentence block (from the frozen ladder document):
    # "The lighthouse keeper counted forty-one waves before the foghorn
    #  answered twice. " repeated; prologue and suffix fixed.
    block = ("The lighthouse keeper counted forty-one waves before the "
             "foghorn answered twice. ")
    head = prompt[:prompt.index(block)]
    tail = prompt[prompt.rindex(block) + len(block):]
    if head + block * base_repeats + tail != prompt:
        raise PhysicalDiagnosticError(
            "base fixture is not a prologue+N-blocks+suffix shape")
    return head + block * target_repeats + tail


def ladder_token_authority_receipt(nominal_length: int,
                                   sentence_repeats: int,
                                   prompt_text: str,
                                   prompt_sha256: str,
                                   token_count: int,
                                   token_ids: list[int] | None = None,
                                   ) -> dict[str, Any]:
    """Build the per-ladder-length tokenizer-authority receipt.

    Binds: nominal ladder label (TEXT PARAMETER, not a token count),
    sentence-repeat count, prompt text digest, and the ACTUAL token
    count derived through the pinned tokenizer authority (server
    /tokenize receipt or authoritative fixture token ids). Retained
    append-only per unit; the reducer recomputes the digest binding.
    """
    if nominal_length not in D.ARM_D_LADDER_SENTENCE_REPEATS:
        raise PhysicalDiagnosticError(
            f"nominal length {nominal_length} not in the frozen ladder")
    if sentence_repeats != D.ARM_D_LADDER_SENTENCE_REPEATS[
            nominal_length]:
        raise PhysicalDiagnosticError(
            f"sentence repeats {sentence_repeats} do not match the "
            f"frozen ladder entry for {nominal_length}")
    if (not isinstance(prompt_text, str) or not prompt_text
            or not re.fullmatch(r"[0-9a-f]{64}", prompt_sha256)
            or type(token_count) is not int or token_count <= 0):
        raise PhysicalDiagnosticError("malformed token authority inputs")
    if token_ids is not None and (not isinstance(token_ids, list)
                                  or len(token_ids) != token_count
                                  or any(type(t) is not int
                                         for t in token_ids)):
        raise PhysicalDiagnosticError(
            "token id population does not match the token count")
    return {
        "nominal_length": nominal_length,
        "sentence_repeats": sentence_repeats,
        "prompt_sha256": prompt_sha256,
        "actual_token_count": token_count,
        "token_ids_sha256": (
            D.sha256_bytes(
                json.dumps(token_ids, separators=(",", ":")).encode())
            if token_ids is not None else None),
        "token_ids": token_ids,
    }


def validate_ladder_token_authority(receipt: Any,
                                    prompt_text: str | None = None,
                                    ) -> dict[str, Any]:
    """Fail-closed validation of a retained token-authority receipt,
    recomputing the prompt-text digest when the prompt is supplied."""
    if not isinstance(receipt, dict):
        raise PhysicalDiagnosticError(
            "ladder token authority receipt is not an object")
    nominal = receipt.get("nominal_length")
    repeats = receipt.get("sentence_repeats")
    if nominal not in D.ARM_D_LADDER_SENTENCE_REPEATS:
        raise PhysicalDiagnosticError("unknown nominal ladder length")
    if repeats != D.ARM_D_LADDER_SENTENCE_REPEATS[nominal]:
        raise PhysicalDiagnosticError(
            "token authority receipt does not match the frozen ladder")
    count = receipt.get("actual_token_count")
    if type(count) is not int or count <= 0:
        raise PhysicalDiagnosticError("actual token count malformed")
    sha = receipt.get("prompt_sha256")
    if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{64}", sha):
        raise PhysicalDiagnosticError("prompt digest malformed")
    if prompt_text is not None and D.sha256_bytes(
            prompt_text.encode()) != sha:
        raise PhysicalDiagnosticError(
            "token authority receipt binds a different prompt text")
    ids = receipt.get("token_ids")
    if ids is not None:
        if (not isinstance(ids, list) or len(ids) != count
                or any(type(t) is not int for t in ids)):
            raise PhysicalDiagnosticError("token id population malformed")
        if receipt.get("token_ids_sha256") != D.sha256_bytes(
                json.dumps(ids, separators=(",", ":")).encode()):
            raise PhysicalDiagnosticError(
                "token id digest binding mismatch")
    elif receipt.get("token_ids_sha256") is not None:
        raise PhysicalDiagnosticError(
            "token id digest present without token ids")
    return dict(receipt)


LADDER_TOKEN_AUTHORITY_NAME = "ladder-token-authority.json"
LADDER_TOKEN_AUTHORITY_SCHEMA = (
    "inferswarm.issue250.ladder-token-authority/1")


def tokenize_prompt(port: int, prompt: str,
                    http_post: Callable[[str, bytes], Any] | None = None,
                    ) -> tuple[int, list[int]]:
    """Tokenize one prompt through a server's /tokenize endpoint.

    CORRECTION PASS 4 (NO-GO 5851078451, blocker 2): this helper is
    NO LONGER production token authority by itself — it blindly
    POSTs to ``http://127.0.0.1:<port>/tokenize`` with no proof that
    the listener is the accepted binary launched with the accepted
    model. Production tokenization goes through
    ``launch_tokenizer_server`` + ``_tokenize_via_attributed_server``
    which launch, attribute, and verify ONE dedicated pinned process
    (add_special defaults true server-side; parse_special true —
    mirroring the pinned /completion tokenize call at
    server-context.cpp:4579). Returns (token_count, token_ids).
    """
    if http_post is None:
        http_post = _http_json_post
    body = json.dumps({"content": prompt}).encode()
    doc = http_post(f"http://127.0.0.1:{port}/tokenize", body)
    tokens = doc.get("tokens") if isinstance(doc, dict) else None
    if (not isinstance(tokens, list) or not tokens
            or any(type(t) is not int for t in tokens)):
        raise PhysicalDiagnosticError(
            f"malformed tokenize response: {str(doc)[:200]}")
    return len(tokens), list(tokens)


def _http_json_post(url: str, body: bytes) -> Any:
    req = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"},
        method="POST")
    with urllib.request.urlopen(req, timeout=120) as response:
        if response.status != 200:
            raise PhysicalDiagnosticError(
                f"tokenize HTTP status {response.status}")
        return json.loads(response.read(16 * 1024 * 1024))


def _port_occupied(port: int) -> bool:
    """True when something is already listening on the loopback port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.5)
        return probe.connect_ex(("127.0.0.1", port)) == 0


# Frozen tokenization-server launch geometry (correction pass 4,
# blocker 2): the dedicated tokenize-only process uses the EXACT
# accepted server geometry (same ctx/batch/host/port contract as the
# campaign launch shape) with NO observer hook — tokenization must
# not perturb or be perturbed by the observation seam, and it serves
# ONLY /tokenize requests (never /completion).
TOKENIZER_SERVER_CTX_SIZE = SERVER_CTX_SIZE
TOKENIZER_SERVER_BATCH_SIZE = SERVER_BATCH_SIZE
TOKENIZER_SERVER_PORT = PORT
TOKENIZER_SCHEMA = "inferswarm.issue250.token-authority-process/1"


def tokenizer_server_argv(binary: Path, model_member: Path,
                          port: int = TOKENIZER_SERVER_PORT,
                          ) -> list[str]:
    """FROZEN argv for the dedicated tokenize-only server process.

    Byte-identical geometry to the accepted campaign launch shape
    (--ctx-size 8192 --batch-size 512, host/port) with NO argv delta:
    no observer env, no thread regime, no placement change — the
    tokenizer authority must come from the accepted binary+model
    under the accepted launch shape.
    """
    return [str(binary), "--model", str(model_member),
            "-ngl", str(D.ACCEPTED_MATCHED_NGL),
            "--ctx-size", str(TOKENIZER_SERVER_CTX_SIZE),
            "--batch-size", str(TOKENIZER_SERVER_BATCH_SIZE),
            "--host", "127.0.0.1", "--port", str(port)]


def launch_tokenizer_server(
        binary: Path, binary_sha: str, model_dir: Path,
        model_member: Path, *, port: int = TOKENIZER_SERVER_PORT,
        spawn=None, wait_healthy: Callable[..., None] | None = None,
        port_occupied: Callable[[int], bool] | None = None,
        attribution_fn=None, log_dir: Path | None = None,
        ) -> dict[str, Any]:
    """Launch and MECHANICALLY ATTRIBUTE the tokenize-only server.

    CORRECTION PASS 4 (NO-GO 5851078451, blocker 2) — the production
    ladder-token authority producer. Steps (fail-closed at each):

    1. refuse a pre-existing unknown listener on the target port
       (fail closed; never silently reuse, never kill unrelated
       processes to obtain the port);
    2. launch ONE accepted llama-server process under the frozen
       tokenization geometry above (no observer hook env);
    3. wait for /health;
    4. capture PID + process attribution and verify
       ``/proc/<pid>/exe`` byte SHA == the accepted binary SHA (the
       listener is PROVEN to be the verified binary);
    5. bind argv to the exact accepted model member / model dir.

    Returns the process handle: ``{"proc", "attribution", "argv"}``.
    The caller MUST ``_stop_tokenizer_server`` the process in a
    finally block. ``spawn``/``wait_healthy``/``port_occupied``/
    ``attribution_fn`` are test seams; production omission resolves
    the real implementations.
    """
    if port_occupied is None:
        port_occupied = _port_occupied
    if spawn is None:
        spawn = _spawn_server
    if wait_healthy is None:
        wait_healthy = _wait_healthy
    if attribution_fn is None:
        attribution_fn = _proc_attribution
    # PRE-EXISTING PORT RULE: an unknown listener fails closed.
    if port_occupied(port):
        raise PhysicalDiagnosticError(
            f"port {port} is already occupied by an unknown process — "
            f"refusing to attribute token authority to an unverified "
            f"listener (no unrelated process is killed to obtain the "
            f"port)")
    argv = tokenizer_server_argv(Path(binary), Path(model_member),
                                 port=port)
    if log_dir is None:
        log_dir = Path(model_dir).parent / "tokenizer-authority"
    log_dir.mkdir(parents=True, exist_ok=True)
    proc = spawn(argv, log_dir / "tokenizer-server.log")
    try:
        wait_healthy(proc, port)
        attribution = attribution_fn(proc, argv, {})
        exe_sha = attribution.get("server_exe_sha256")
        if exe_sha != binary_sha:
            raise PhysicalDiagnosticError(
                f"tokenizer server executable SHA mismatch: {exe_sha} "
                f"!= accepted binary {binary_sha}")
        attribution["model_dir"] = str(Path(model_dir))
        attribution["model_launch_member"] = str(Path(model_member))
        attribution["argv"] = list(argv)
        return {"proc": proc, "attribution": attribution,
                "argv": argv}
    except BaseException:
        if proc.poll() is None:
            _terminate_process_group(proc)
        raise


def _spawn_server(argv: list[str], log_path: Path
                  ) -> subprocess.Popen:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_file = log_path.open("wb")
    proc = subprocess.Popen(
        argv, env=dict(os.environ), stdout=log_file,
        stderr=subprocess.STDOUT, start_new_session=True)
    return proc


def _terminate_process_group(proc: subprocess.Popen) -> None:
    if proc.poll() is None:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError, OSError):
            pass
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError, OSError):
                pass
            proc.wait(timeout=5)


def _stop_tokenizer_server(handle: dict[str, Any]) -> None:
    """Teardown the dedicated tokenizer server process (always runs)."""
    proc = handle.get("proc")
    if proc is not None:
        _terminate_process_group(proc)


def _verify_tokenizer_process_still_attributed(
        handle: dict[str, Any], binary_sha: str) -> None:
    """Re-verify the live PID + executable mid-authority generation.

    The process answering the tokenize requests must STILL be the
    attributed process: PID alive, /proc/<pid>/exe SHA unchanged. A
    process replacement mid-generation fails closed (control 8).
    """
    proc = handle["proc"]
    attribution = handle["attribution"]
    if proc.poll() is not None:
        raise PhysicalDiagnosticError(
            f"tokenizer server exited mid-authority (rc="
            f"{proc.returncode})")
    try:
        exe = os.path.realpath(f"/proc/{proc.pid}/exe")
    except OSError as exc:
        raise PhysicalDiagnosticError(
            f"tokenizer server process vanished mid-authority "
            f"(pid {proc.pid}): {exc}") from exc
    if not Path(exe).exists():
        raise PhysicalDiagnosticError(
            f"tokenizer server process vanished mid-authority "
            f"(pid {proc.pid}): no /proc/{proc.pid}/exe")
    live_sha = D.file_sha256(Path(exe))
    if live_sha != binary_sha or live_sha != attribution[
            "server_exe_sha256"]:
        raise PhysicalDiagnosticError(
            f"tokenizer server process changed mid-authority: live "
            f"executable SHA {live_sha} != attributed "
            f"{attribution['server_exe_sha256']}")


def _tokenize_via_attributed_server(
        port: int, prompt: str, handle: dict[str, Any],
        binary_sha: str,
        http_post: Callable[[str, bytes], Any] | None = None,
        verify_alive: Callable[[dict[str, Any], str], None]
        | None = None,
        ) -> tuple[int, list[int], bytes, str]:
    """Tokenize ONE prompt through the attributed server process.

    Verifies the process attribution immediately before the request,
    issues ONLY a /tokenize POST, retains the RAW response bytes and
    their digest alongside the parsed token ids. Returns
    (count, ids, raw_bytes, raw_sha256).
    """
    if verify_alive is None:
        verify_alive = _verify_tokenizer_process_still_attributed
    verify_alive(handle, binary_sha)
    if http_post is None:
        http_post = _raw_json_post
    body = json.dumps({"content": prompt}).encode()
    raw, doc = http_post(f"http://127.0.0.1:{port}/tokenize", body)
    tokens = doc.get("tokens") if isinstance(doc, dict) else None
    if (not isinstance(tokens, list) or not tokens
            or any(type(t) is not int for t in tokens)):
        raise PhysicalDiagnosticError(
            f"malformed tokenize response: {str(doc)[:200]}")
    return len(tokens), list(tokens), raw, D.sha256_bytes(raw)


def _raw_json_post(url: str, body: bytes) -> tuple[bytes, Any]:
    """POST returning (raw_bytes, decoded_json) — custody-grade."""
    req = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"},
        method="POST")
    with urllib.request.urlopen(req, timeout=120) as response:
        if response.status != 200:
            raise PhysicalDiagnosticError(
                f"tokenize HTTP status {response.status}")
        raw = response.read(16 * 1024 * 1024)
    return raw, json.loads(raw)


def derive_ladder_token_authority(
        repo_root: Path, evidence_root: Path, expected_head: str,
        *, binary: Path, binary_id: str, model_dir: Path,
        attestation: dict[str, Any] | None = None,
        launch_server: Callable[..., dict[str, Any]] | None = None,
        stop_server: Callable[[dict[str, Any]], None] | None = None,
        verify_alive: Callable[[dict[str, Any], str], None]
        | None = None,
        tokenize: Callable[[str], tuple[int, list[int]]] | None = None,
        http_post: Callable[[str, bytes], Any] | None = None,
        ) -> dict[str, Any]:
    """Derive and retain the campaign ladder-token-authority document.

    CORRECTION PASS 3 (NO-GO 5847890177, blocker 4A): BEFORE any
    physical Arm-D execution, every predeclared ladder prompt is
    tokenized through the pinned tokenizer authority — the accepted
    comparator binary itself serving /tokenize (the same tokenizer the
    pinned /completion path uses). The document retains, per nominal
    ladder length: nominal label (TEXT PARAMETER), sentence-repeat
    count, prompt text digest, actual token ids (full population), and
    the actual token count. Append-only; regeneration is refused.

    CORRECTION PASS 4 (NO-GO 5851078451, blocker 2): the production
    path now LAUNCHES AND ATTRIBUTES the pinned server. The tokens
    are proven to come from ONE accepted llama-server process:
    exact clean head -> binary file verification -> accepted campaign
    model attestation binding -> model stat witness -> port free of
    unknown listeners -> ONE process launched under the frozen
    tokenization geometry -> healthy -> PID + /proc/<pid>/exe SHA ==
    accepted binary SHA -> argv bound to the accepted model member ->
    per-prompt re-attribution + /tokenize ONLY -> raw response bytes
    + digests retained -> teardown. ``tokenize`` is the TEST-ONLY
    injection seam (a bare callback returning ids produces
    NON-production authority — the retained document then names
    ``test_seam`` and the reducer rejects it for production use);
    production callers pass nothing.
    """
    repo_root = Path(repo_root)
    D._require_clean_head(repo_root, expected_head)
    fixtures = verify_fixtures(repo_root)
    binary_sha = verify_binary(Path(binary), binary_id)
    # Campaign model attestation binding: the tokenizer authority
    # must use the SAME accepted model bytes as the physical
    # campaign (accepted member digests + opening attestation digest
    # + live stat witness).
    if attestation is None:
        attestation = validate_model_attestation(
            _load_retained_attestation(evidence_root), expected_head)
    else:
        attestation = validate_model_attestation(attestation,
                                                 expected_head)
    witness_problems, stat_witness = attestation_witness(
        Path(model_dir), attestation)
    if witness_problems:
        raise PhysicalDiagnosticError(
            f"tokenizer-authority model stat witness drift: "
            f"{witness_problems}")
    if attestation["model_dir"] != str(Path(model_dir)):
        raise PhysicalDiagnosticError(
            "attested model dir differs from the tokenizer model dir")
    launch_member = Path(model_dir) / D.MODEL_MEMBER_1
    base = fixtures[D.CASE]
    lengths: dict[str, Any] = {}
    process_block: dict[str, Any] | None = None
    if tokenize is not None:
        # TEST SEAM ONLY — never production authority.
        for length in D.ARM_D_LADDER_LENGTHS:
            prompt = derive_ladder_prompt(
                base["prompt_text"], length, base["sentence_repeats"])
            count, ids = tokenize(prompt)
            lengths[str(length)] = ladder_token_authority_receipt(
                length, D.ARM_D_LADDER_SENTENCE_REPEATS[length], prompt,
                D.sha256_bytes(prompt.encode()), count, token_ids=ids)
        process_block = None
    else:
        launcher = launch_server or launch_tokenizer_server
        stopper = stop_server or _stop_tokenizer_server
        verifier = (verify_alive
                    or _verify_tokenizer_process_still_attributed)
        handle = launcher(Path(binary), binary_sha, Path(model_dir),
                          launch_member)
        try:
            for length in D.ARM_D_LADDER_LENGTHS:
                prompt = derive_ladder_prompt(
                    base["prompt_text"], length,
                    base["sentence_repeats"])
                count, ids, raw, raw_sha = _tokenize_via_attributed_server(
                    TOKENIZER_SERVER_PORT, prompt, handle, binary_sha,
                    http_post=http_post, verify_alive=verifier)
                receipt = ladder_token_authority_receipt(
                    length, D.ARM_D_LADDER_SENTENCE_REPEATS[length],
                    prompt, D.sha256_bytes(prompt.encode()), count,
                    token_ids=ids)
                receipt["tokenize_response_raw_sha256"] = raw_sha
                receipt["tokenize_response_bytes"] = len(raw)
                # retain the RAW response bytes themselves so the
                # reducer can re-verify the digest against content
                # (raw mutation control 9)
                receipt["tokenize_response_raw_b64"] = base64.b64encode(
                    raw).decode("ascii")
                lengths[str(length)] = receipt
            process_block = dict(handle["attribution"])
            process_block["schema"] = TOKENIZER_SCHEMA
            process_block["head_sha"] = expected_head
            process_block["binary_id"] = binary_id
            process_block["binary_sha256"] = binary_sha
            process_block["model_attestation_sha256"] = attestation[
                "attestation_sha256"]
            process_block["model_stat_witness"] = stat_witness
            process_block["tokenizer_semantics"] = {
                "same_accepted_model_bytes": True,
                "add_special": "server-default-true",
                "parse_special": True,
                "reference": ("pinned /completion tokenize call "
                              "(server-context.cpp:4579)"),
            }
        finally:
            stopper(handle)
    doc = {
        "schema": LADDER_TOKEN_AUTHORITY_SCHEMA,
        "head_sha": expected_head,
        "binary_id": binary_id,
        "binary_sha256": binary_sha,
        "authority": ("attributed_pinned_server_tokenize_endpoint"
                      if process_block is not None else "test_seam"),
        "method": ("dedicated accepted-binary llama-server launched "
                   "under the frozen tokenization geometry, attributed "
                   "by PID + /proc/<pid>/exe SHA == accepted binary "
                   "SHA, serving ONLY /tokenize; add_special "
                   "server-default (true) + parse_special true — the "
                   "same tokenize call the pinned /completion path "
                   "makes (server-context.cpp:4579)"),
        "model_attestation_sha256": attestation[
            "attestation_sha256"],
        "process_attribution": process_block,
        "lengths": lengths,
    }
    root = Path(evidence_root)
    target = root / LADDER_TOKEN_AUTHORITY_NAME
    if target.exists() or target.is_symlink():
        raise PhysicalDiagnosticError(
            f"ladder token authority already retained (append-only): "
            f"{target}")
    root.mkdir(parents=True, exist_ok=True)
    _write_json(target, doc)
    return doc


def _load_retained_attestation(evidence_root: Path) -> dict[str, Any]:
    """Load the retained campaign OPENING attestation (fail-closed)."""
    path = Path(evidence_root) / MODEL_ATTESTATION_OPEN_NAME
    if path.is_symlink() or not path.is_file():
        raise PhysicalDiagnosticError(
            f"campaign opening model attestation is not retained: "
            f"{path}")
    return json.loads(path.read_bytes())


def validate_token_authority_process_block(block: Any,
                                           expected_head: str,
                                           ) -> dict[str, Any]:
    """Fail-closed validation of the retained token-authority PROCESS
    ATTRIBUTION (correction pass 4, NO-GO 5851078451, blocker 2).

    Production token authority must be bound to the attributed
    pinned-server process: schema, exact head, binary id + SHA (the
    accepted digest), live server PID, executable SHA == the accepted
    binary SHA, the exact frozen argv (bound to the accepted model
    member + model dir), the opening model-attestation digest, the
    per-member stat witness, and the tokenizer-semantics declaration
    (same accepted model bytes; add_special/parse_special behavior).
    A document without this block is NOT production authority.
    """
    if not isinstance(block, dict):
        raise PhysicalDiagnosticError(
            "ladder token authority lacks process attribution — a "
            "synthetic/unattributed endpoint cannot produce "
            "production token authority")
    if block.get("schema") != TOKENIZER_SCHEMA:
        raise PhysicalDiagnosticError(
            "token-authority process attribution schema mismatch")
    if block.get("head_sha") != expected_head:
        raise PhysicalDiagnosticError(
            "token-authority process attribution binds a different head")
    pid = block.get("server_pid")
    if type(pid) is not int or pid <= 0:
        raise PhysicalDiagnosticError(
            "token-authority process attribution lacks a server PID")
    binary_id = block.get("binary_id")
    accepted = (D.SERVER_BINARIES.get(binary_id)
                if isinstance(binary_id, str) else None)
    if (not isinstance(binary_id, str) or accepted is None
            or block.get("binary_sha256") != accepted
            or block.get("server_exe_sha256") != accepted):
        raise PhysicalDiagnosticError(
            "token-authority process executable/binary binding "
            "mismatch (wrong binary id, binary SHA, or /proc/<pid>/exe "
            "SHA)")
    argv = block.get("argv")
    if (not isinstance(argv, list)
            or argv != tokenizer_server_argv(
                Path(argv[0]) if argv else Path(""),
                Path(str(block.get("model_launch_member"))))):
        raise PhysicalDiagnosticError(
            "token-authority process argv is not the frozen "
            "tokenization geometry bound to the accepted model member")
    if (block.get("model_launch_member")
            != str(Path(str(block.get("model_dir")))
                   / D.MODEL_MEMBER_1)):
        raise PhysicalDiagnosticError(
            "token-authority process model launch member mismatch")
    attestation_sha = block.get("model_attestation_sha256")
    if (not isinstance(attestation_sha, str)
            or not re.fullmatch(r"[0-9a-f]{64}", attestation_sha)):
        raise PhysicalDiagnosticError(
            "token-authority process lacks the opening "
            "model-attestation digest")
    # (the doc-level digest binding to the retained campaign opening
    # is enforced by load_ladder_token_authority, which knows the
    # evidence root)
    witness = block.get("model_stat_witness")
    if (not isinstance(witness, dict)
            or sorted(witness) != sorted(D.MODEL_MEMBERS)):
        raise PhysicalDiagnosticError(
            "token-authority process stat witness population malformed")
    for member, fields in witness.items():
        if (not isinstance(fields, dict)
                or sorted(fields) != sorted(WITNESS_STAT_KEYS)
                or any(type(fields[k]) is not int for k in
                       WITNESS_STAT_KEYS)):
            raise PhysicalDiagnosticError(
                f"token-authority stat witness malformed: {member}")
    semantics = block.get("tokenizer_semantics")
    if (not isinstance(semantics, dict)
            or semantics.get("same_accepted_model_bytes") is not True
            or semantics.get("add_special") != "server-default-true"
            or semantics.get("parse_special") is not True):
        raise PhysicalDiagnosticError(
            "token-authority tokenizer semantics declaration malformed")
    return block


def load_ladder_token_authority(evidence_root: Path,
                                expected_head: str) -> dict[str, Any]:
    """Load and fail-closed validate the retained token authority."""
    path = Path(evidence_root) / LADDER_TOKEN_AUTHORITY_NAME
    if path.is_symlink() or not path.is_file():
        raise PhysicalDiagnosticError(
            f"retained ladder token authority missing: {path}")
    doc = json.loads(path.read_bytes())
    if not isinstance(doc, dict) or doc.get(
            "schema") != LADDER_TOKEN_AUTHORITY_SCHEMA:
        raise PhysicalDiagnosticError(
            "ladder token authority schema mismatch")
    if doc.get("head_sha") != expected_head:
        raise PhysicalDiagnosticError(
            "ladder token authority binds a different head")
    binary_id = doc.get("binary_id")
    if not isinstance(binary_id, str) or doc.get(
            "binary_sha256") != D.SERVER_BINARIES.get(binary_id):
        raise PhysicalDiagnosticError(
            "ladder token authority binary binding mismatch")
    # CORRECTION PASS 4 (blocker 2): production authority REQUIRES the
    # attributed pinned-server process block (a synthetic HTTP
    # endpoint alone — or a test-seam document — is rejected).
    if doc.get("authority") != (
            "attributed_pinned_server_tokenize_endpoint"):
        raise PhysicalDiagnosticError(
            "ladder token authority is not bound to an attributed "
            "pinned-server tokenize process")
    block = doc.get("process_attribution")
    validate_token_authority_process_block(block, expected_head)
    doc_sha = doc.get("model_attestation_sha256")
    if (not isinstance(doc_sha, str)
            or block.get("model_attestation_sha256") != doc_sha):
        raise PhysicalDiagnosticError(
            "token-authority doc/process-block attestation digest "
            "binding mismatch")
    opening_path = Path(evidence_root) / MODEL_ATTESTATION_OPEN_NAME
    if opening_path.is_file():
        opening = json.loads(opening_path.read_bytes())
        if (opening.get("attestation_sha256") != doc_sha
                or opening.get("schema") != MODEL_ATTESTATION_OPEN_SCHEMA
                or opening.get("head_sha") != expected_head):
            raise PhysicalDiagnosticError(
                "token-authority attestation digest does not match "
                "the retained campaign opening")
    lengths = doc.get("lengths")
    if (not isinstance(lengths, dict)
            or sorted(lengths) != sorted(
                str(n) for n in D.ARM_D_LADDER_LENGTHS)):
        raise PhysicalDiagnosticError(
            "ladder token authority does not cover exactly the frozen "
            "ladder lengths")
    for key, entry in lengths.items():
        validate_ladder_token_authority(entry)
        if entry["nominal_length"] != int(key):
            raise PhysicalDiagnosticError(
                "ladder token authority key/entry mismatch")
        raw_sha = entry.get("tokenize_response_raw_sha256")
        if (not isinstance(raw_sha, str)
                or not re.fullmatch(r"[0-9a-f]{64}", raw_sha)
                or type(entry.get("tokenize_response_bytes")) is not int
                or entry["tokenize_response_bytes"] <= 0):
            raise PhysicalDiagnosticError(
                "ladder token authority entry lacks the raw tokenize "
                "response digest/size binding")
        raw_b64 = entry.get("tokenize_response_raw_b64")
        if not isinstance(raw_b64, str):
            raise PhysicalDiagnosticError(
                "ladder token authority entry lacks the retained raw "
                "tokenize response bytes")
        try:
            raw_bytes = base64.b64decode(raw_b64, validate=True)
        except Exception:
            raise PhysicalDiagnosticError(
                "ladder token authority raw response bytes are not "
                "valid base64") from None
        if (len(raw_bytes) != entry["tokenize_response_bytes"]
                or D.sha256_bytes(raw_bytes) != raw_sha):
            raise PhysicalDiagnosticError(
                "ladder token authority raw response bytes do not "
                "match the retained digest/size (mutation detected)")
        ids = entry.get("token_ids")
        if (not isinstance(ids, list) or len(ids) == 0
                or any(type(t) is not int for t in ids)
                or json.loads(raw_bytes).get("tokens") != ids):
            raise PhysicalDiagnosticError(
                "ladder token authority token ids do not match the "
                "retained raw tokenize response (mutation detected)")
        if entry.get("actual_token_count") != len(ids):
            raise PhysicalDiagnosticError(
                "ladder token authority count does not match the "
                "retained token id population (mutation detected)")
    return doc


def validate_ladder_token_authority_entry(entry: Any,
                                          prompt_text: str) -> dict[str, Any]:
    """Validate one retained entry against the exact prompt text the
    unit will send (digest recompute — prompt mutation is fatal)."""
    return validate_ladder_token_authority(entry, prompt_text)


# ---------------------------------------------------------------------------
# Server launch geometry (exact accepted shape + the one arm factor)
# ---------------------------------------------------------------------------

def server_argv(binary: Path, model_member: Path, unit: dict[str, Any],
                port: int = PORT, c2_verification: bool = False,
                ) -> list[str]:
    """Exact accepted launch shape with the unit's declared argv delta.

    Base shape is byte-identical to the accepted #248 producer
    (--ctx-size 8192 --batch-size 512, -ngl placement, host/port); the
    unit's frozen ``argv_delta`` appends exactly the one declared
    factor tokens (e.g. ``-dev none``, ``-t 4 -tb 4``). Arm D ladder
    units run at the accepted placement (length is the factor).

    CORRECTION PASS 6 (AMENDMENT-003): serial `-t 1 -tb 1` units are
    REFUSED here unless ``allow_c2_serial=True`` — and that flag is
    accepted only from the dedicated C2 path, which itself requires
    the d250-arm-c2 gate (c2_launch_allowed). No generic unit path can
    launch a serial regime.
    """
    delta = tuple(unit.get("argv_delta", ()))
    is_serial = (delta == ("-dev", "none") + D.ARM_C2_ARGV_DELTA)
    if is_serial and not (unit.get("c2_serial_authorized")
                          or c2_verification):
        raise PhysicalDiagnosticError(
            "serial `-t 1 -tb 1` (C2) units are not launchable through "
            "the generic path: they require the dedicated d250-arm-c2 "
            "maintainer gate (AMENDMENT-003)")
    if unit.get("ladder_length"):
        if delta:
            raise PhysicalDiagnosticError(
                "ladder units cannot carry an argv delta")
        ngl = D.ACCEPTED_MATCHED_NGL
    else:
        ngl = int(unit["ngl"])
        if ngl != 0:
            raise PhysicalDiagnosticError(
                f"#250 non-ladder units are CPU-only (-dev none); "
                f"ngl={ngl} is not a #250 current-unit condition")
    argv = [str(binary), "--model", str(model_member), "-ngl", str(ngl),
            "--ctx-size", str(SERVER_CTX_SIZE),
            "--batch-size", str(SERVER_BATCH_SIZE),
            "--host", "127.0.0.1", "--port", str(port)]
    argv.extend(delta)
    return argv


def c2_launch_allowed(namespace: str, arm: str, authority: dict[str, Any],
                      expected_head: str, evidence_root: Path, *,
                      repo_root: Path, model_attestation: dict[str, Any],
                      revalidate_authority: Callable[..., dict[str, Any]] | None,
                      github_api: str = "https://api.github.com",
                      ) -> dict[str, Any]:
    """Authorize C2 only with verified completed C1 and both live digests."""
    if namespace != D.C2_SERIAL_NAMESPACE or arm != D.ARM_C2_NAME:
        raise PhysicalDiagnosticError(
            f"serial C2 launch requires the {D.C2_SERIAL_NAMESPACE!r} "
            f"namespace and the {D.ARM_C2_NAME!r} arm (got "
            f"{namespace!r}/{arm!r}) — no generic Arm-C or C1 dispatch "
            "can authorize serial units")
    payload = D.validate_authority_payload(dict(authority), expected_head)
    if payload.get("namespace") != D.C2_SERIAL_NAMESPACE:
        raise PhysicalDiagnosticError(
            "c2 authority payload is not a d250-arm-c2 dispatch")
    # The terminal imports physical; import only when the dedicated gate
    # executes, never at module initialization.
    import issue250_terminal as T

    root = Path(evidence_root)
    opening = root / MODEL_ATTESTATION_OPEN_NAME
    if opening.is_symlink() or not opening.is_file():
        raise PhysicalDiagnosticError("C1 campaign opening attestation missing")
    try:
        attestation = json.loads(opening.read_bytes())
        validate_model_attestation(attestation, expected_head)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        raise PhysicalDiagnosticError(
            "C1 campaign opening attestation invalid") from exc
    if attestation != model_attestation:
        raise PhysicalDiagnosticError(
            "C1 rows require the retained campaign opening attestation")
    c1_authority = require_live_dispatch(
        repo_root, expected_head, "d250-arm-c1",
        revalidate_authority=revalidate_authority, github_api=github_api)
    if c1_authority.get("arm") != "C1-reduced-parallelism":
        raise PhysicalDiagnosticError("C1 live dispatch binds another arm")
    tags = [u["tag"] for u in D.probe_list_for(
        "C1-reduced-parallelism")]
    population, problems = T._verify_namespace_population(
        root, "d250-arm-c1", "C1-reduced-parallelism",
        expected_head, c1_authority, attestation, tags,
        lambda tag: "accepted")
    verdict = T._walk_condition(population)
    completed = ("deterministic" if verdict["deterministic"]
                 else "variable" if verdict["nondeterministic"] else None)
    if problems or completed is None:
        raise PhysicalDiagnosticError(
            "serial C2 launch refused: completed verified C1 rows missing")
    if not D.c1_dispatch_c2_unlocked(
            root, expected_head, c2_authority=payload,
            c1_authority=c1_authority, c1_verdict=completed):
        raise PhysicalDiagnosticError(
            "serial C2 launch refused: the frozen C1-completed gate "
            f"record is absent or does not bind both live authorities "
            f"({D.C2_GATE_RECORD_NAME})")
    _admit_retained_cost(root, "arm-c2-serial", namespace, arm,
                         c2_gate_authorized=True)
    return {"authority": c1_authority, "verdict": completed}


def validate_arm_a_bridge(evidence_root: Path, expected_head: str,
                          ) -> dict[str, Any]:
    """Authenticate the post-V0n Arm-A reachability bridge (AMENDMENT-008).

    CORRECTION ROUND 2 (reviewed head 35f427b): eligibility is decided
    by an EXACT authenticated predecessor DECISION revalidated from
    retained bytes — never by a bridge-record claim and never by a
    historical-gate refusal message prefix. Fail-closed in every
    direction: absent, unreadable, malformed, wrongly bound, or tampered
    records reject; both predecessor populations must authenticate
    through their FROZEN retained-population verifiers
    (revalidating_arm_a_predecessors), and both frozen reducers must
    re-derive exactly the accepted states. Eligibility is NOT execution
    authority.
    """
    root = Path(evidence_root)
    path = root / D.ARM_A_BRIDGE_NAME
    if path.is_symlink() or not path.is_file():
        raise PhysicalDiagnosticError(
            "post-V0n Arm-A reachability bridge record missing "
            f"({D.ARM_A_BRIDGE_NAME}); the accepted stable-disagreement + "
            "V0n variable combination is not mechanically consumable "
            "without it")
    try:
        record = json.loads(path.read_bytes())
    except (OSError, ValueError) as exc:
        raise PhysicalDiagnosticError(
            "Arm-A reachability bridge record unreadable") from exc
    if not isinstance(record, dict):
        raise PhysicalDiagnosticError("Arm-A reachability bridge malformed")
    v0 = record.get("v0") if isinstance(record.get("v0"), dict) else {}
    v0n = record.get("v0n") if isinstance(record.get("v0n"), dict) else {}
    if (record.get("schema") != D.ARM_A_BRIDGE_SCHEMA
            or record.get("recorded_by") != ARM_A_BRIDGE_PRODUCER
            or record.get("evidence_generation") != EVIDENCE_GENERATION
            or record.get("namespace") != "d250-arm-a"
            or record.get("arm") != "A-vulkan-necessity"
            or record.get("evidence_head") != ARM_A_BRIDGE_EVIDENCE_HEAD
            or v0.get("dispatch_sha256")
            != D.ARM_A_BRIDGE_V0_DISPATCH_DIGEST_SHA256
            or v0.get("state") != D.V0_STATE_DISAGREEMENT_STOP
            or v0.get("stable_row_sha256")
            != D.ARM_A_BRIDGE_V0_STABLE_ROW_SHA256
            or v0.get("units") != 3
            or v0.get("executed_head") != D.ACCEPTED_V0_EXECUTED_HEAD
            or v0n.get("dispatch_sha256")
            != D.ARM_A_BRIDGE_V0N_DISPATCH_DIGEST_SHA256
            or v0n.get("state") != D.V0N_STATE_NVIDIA_VARIABLE_STOP
            or v0n.get("freeze_sha256") != D.ARM_A_BRIDGE_V0N_FREEZE_SHA256
            or v0n.get("row_sha256") != list(D.ARM_A_BRIDGE_V0N_ROW_SHA256)
            or v0n.get("units") != 2
            or v0n.get("executed_head") != ARM_A_BRIDGE_EVIDENCE_HEAD
            or record.get("maintainer_adjudicated") is not True
            or v0n.get("a_eligible") is not False
            or v0n.get("terminal") is not None
            or record.get("eligible_arms") != ["A-vulkan-necessity"]
            or record.get("requires_fresh_dispatch") is not True
            or record.get("executes_arm_a") is not False):
        raise PhysicalDiagnosticError(
            "Arm-A reachability bridge binding/authority mismatch")
    if record.get("canonical_digest_sha256") != _v0_digest(record):
        raise PhysicalDiagnosticError(
            "Arm-A reachability bridge canonical digest mismatch")
    # The bridge cannot authorize from bytes alone: BOTH predecessor
    # populations must re-authenticate through the frozen verifiers and
    # both frozen reducers must re-derive the accepted decisions.
    revalidating_arm_a_predecessors(root)
    return record


# --- Cross-host read-only predecessor evidence path (AMENDMENT-008 r2) ---
#
# The accepted predecessor roots live on two distinct hosts (AMD V0 on
# inferswarm05 at /home/hermes/is250-campaign/evidence-v0-c5cc132/,
# V0n on inferswarm01 at /home/hermes/is250-campaign/
# evidence-v0n-nvidia-aa05971/). The original append-only roots are
# IMMUTABLE and never rewritten; a future Arm-A campaign mounts them
# read-only under its own evidence root as self-contained copies:
#
#   <evidence-root>/predecessor-v0/   (AMD V0 root copy)
#   <evidence-root>/predecessor-v0n/  (V0n root copy)
#
# The copies are verified against the accepted identities the bridge
# record names (dispatch digests, freeze digests, row digests) by the
# SAME frozen verifiers that ran at acceptance time; nothing on the
# original roots is read by the Arm-A producer, so the mount can never
# perturb accepted evidence. CPU-only regression hosts cannot hold the
# physical rows; tests patch the frozen bridge constants to the
# synthetic population's real digests (the ACCEPTED_248_MANIFEST_SELF_
# DIGEST fixture precedent) and every frozen verifier then runs
# unmodified over real bytes.

ARM_A_PREDECESSOR_V0_MOUNT = "predecessor-v0"
ARM_A_PREDECESSOR_V0N_MOUNT = "predecessor-v0n"


def _arm_a_frozen_v0_authority() -> dict[str, Any]:
    """The completed AMD V0 dispatch payload, reconstructed byte-exact
    from the retained dispatch-comment fields (AMENDMENT-006 precedent:
    dispatch authority digests are derivable offline). Digest equals
    the frozen accepted constant ARM_A_BRIDGE_V0_DISPATCH_DIGEST_SHA256
    (asserted by validate_arm_a_bridge via the record binding and again
    here through authority_digest)."""
    authority = {
        "comment_id": D.ARM_A_BRIDGE_V0_DISPATCH_COMMENT_ID,
        "issue_url": (f"https://api.github.com/repos/Zutfen-LLC/"
                      f"inferswarm/issues/{D.DIAGNOSTIC_PR_NUMBER}"),
        "author_association": "MEMBER",
        "created_at": D.ARM_A_BRIDGE_V0_DISPATCH_CREATED_AT,
        "head_sha": D.ACCEPTED_V0_EXECUTED_HEAD,
        "namespace": D.V0_NAMESPACE,
        "arm": D.V0_ARM,
        "body": "\n".join([
            D.DIAGNOSTIC_DISPATCH_PHRASE,
            f"head={D.ACCEPTED_V0_EXECUTED_HEAD}",
            f"diagnostic-namespace={D.V0_NAMESPACE}",
            f"arm={D.V0_ARM}",
        ]),
        "open_pr": True,
        "issue_open": True,
    }
    if (D.authority_digest(authority)
            != D.ARM_A_BRIDGE_V0_DISPATCH_DIGEST_SHA256):
        raise PhysicalDiagnosticError(
            "frozen V0 dispatch authority reconstruction drifted")
    return authority


def _arm_a_frozen_v0n_authority() -> dict[str, Any]:
    """The completed V0n dispatch payload, reconstructed byte-exact
    from the retained dispatch-comment fields; digest equals the frozen
    accepted constant ARM_A_BRIDGE_V0N_DISPATCH_DIGEST_SHA256."""
    authority = {
        "comment_id": D.ARM_A_BRIDGE_V0N_DISPATCH_COMMENT_ID,
        "issue_url": (f"https://api.github.com/repos/Zutfen-LLC/"
                      f"inferswarm/issues/{D.DIAGNOSTIC_PR_NUMBER}"),
        "author_association": "MEMBER",
        "created_at": D.ARM_A_BRIDGE_V0N_DISPATCH_CREATED_AT,
        "head_sha": ARM_A_BRIDGE_EVIDENCE_HEAD,
        "namespace": D.V0N_NAMESPACE,
        "arm": D.V0N_ARM,
        "body": "\n".join([
            D.DIAGNOSTIC_DISPATCH_PHRASE,
            f"head={ARM_A_BRIDGE_EVIDENCE_HEAD}",
            f"diagnostic-namespace={D.V0N_NAMESPACE}",
            f"arm={D.V0N_ARM}",
        ]) + "\n",
        "open_pr": True,
        "issue_open": True,
    }
    if (D.authority_digest(authority)
            != D.ARM_A_BRIDGE_V0N_DISPATCH_DIGEST_SHA256):
        raise PhysicalDiagnosticError(
            "frozen V0n dispatch authority reconstruction drifted")
    return authority


def revalidating_arm_a_predecessors(root: Path) -> dict[str, Any]:
    """Revalidate BOTH accepted predecessor populations from retained
    bytes under the read-only mounts, through the FROZEN verifiers, and
    re-derive both decisions through the FROZEN reducers.

    V0 (predecessor-v0/): exactly the accepted three-unit
    repeat-stable population; ``_v0_retained_rows`` re-checks every
    receipt/row/custody clause (one-factor freeze, selector binding,
    probe records, process attribution, placement) under the frozen
    accepted dispatch authority; ``reduce_v0_screen`` must derive
    exactly CROSS_VENDOR_DISAGREEMENT_STOP_BLOCKED with all three rows
    equal to the accepted stable row and equal to NEITHER retained
    #248 NVIDIA row (accepted contrast law).

    V0n (predecessor-v0n/): exactly the accepted two-unit mismatched
    population; ``_v0n_retained_rows`` re-checks the complete frozen
    custody (identity/freeze/residency/argv/env/authority/PID/
    generation) under the frozen accepted dispatch authority;
    ``reduce_v0n_screen`` must derive exactly
    CURRENT_NVIDIA_VARIABLE_STOP with both rows novel (differing from
    the AMD stable row and BOTH retained #248 rows).
    """
    root = Path(root)
    # --- V0 half -------------------------------------------------------
    v0_mount = root / ARM_A_PREDECESSOR_V0_MOUNT
    if v0_mount.is_symlink() or not v0_mount.is_dir():
        raise PhysicalDiagnosticError(
            "Arm-A bridge V0 predecessor mount missing or symlink "
            f"({ARM_A_PREDECESSOR_V0_MOUNT}); the accepted AMD V0 "
            "evidence is not consumable without it")
    v0_authority = _arm_a_frozen_v0_authority()
    v0_rows = _v0_retained_rows(v0_mount, 3, D.ACCEPTED_V0_EXECUTED_HEAD,
                                v0_authority)
    if len(v0_rows) != 3:
        raise PhysicalDiagnosticError(
            "Arm-A bridge V0 population is not the accepted three units")
    v0_base = v0_mount / V0_NAMESPACE
    v0_bytes = [(v0_base / tag / "obs.row0.f32").read_bytes()
                for tag in V0_UNIT_TAGS[:3]]
    v0_decision = D.reduce_v0_screen(v0_bytes, D.V0_NVIDIA_ROW0_SHA256)
    if v0_decision.get("state") != D.V0_STATE_DISAGREEMENT_STOP:
        raise PhysicalDiagnosticError(
            "Arm-A bridge V0 decision is not the accepted stable "
            f"cross-vendor disagreement stop: {v0_decision.get('state')}")
    if (v0_decision.get("amd_rows") != [D.ARM_A_BRIDGE_V0_STABLE_ROW_SHA256]
            * 3 or v0_decision.get("matched_retained_nvidia") is not False):
        raise PhysicalDiagnosticError(
            "Arm-A bridge V0 rows are not the accepted repeat-stable "
            "novel population")
    # --- V0n half ------------------------------------------------------
    v0n_mount = root / ARM_A_PREDECESSOR_V0N_MOUNT
    if v0n_mount.is_symlink() or not v0n_mount.is_dir():
        raise PhysicalDiagnosticError(
            "Arm-A bridge V0n predecessor mount missing or symlink "
            f"({ARM_A_PREDECESSOR_V0N_MOUNT}); the accepted V0n "
            "evidence is not consumable without it")
    v0n_authority = _arm_a_frozen_v0n_authority()
    v0n_rows = _v0n_retained_rows(v0n_mount, 2, ARM_A_BRIDGE_EVIDENCE_HEAD,
                                  v0n_authority)
    if len(v0n_rows) != 2:
        raise PhysicalDiagnosticError(
            "Arm-A bridge V0n population is not the accepted two units")
    # Fresh-process custody (the terminal's derive_v0n_state law): the
    # two retained units must carry DISTINCT PIDs — a duplicated PID is
    # not two fresh processes.
    v0n_base = v0n_mount / V0N_NAMESPACE
    v0n_pids = []
    for tag in V0N_UNIT_TAGS[:2]:
        rec = json.loads((v0n_base / tag / "unit.json").read_bytes())
        v0n_pids.append(rec.get("server_pid"))
    if len(set(v0n_pids)) != 2:
        raise PhysicalDiagnosticError(
            "Arm-A bridge V0n population violates the fresh-process "
            "PID-custody law")
    v0n_bytes = [(v0n_base / tag / "obs.row0.f32").read_bytes()
                 for tag in V0N_UNIT_TAGS[:2]]
    v0n_decision = D.reduce_v0n_screen(
        v0n_bytes, D.ARM_A_BRIDGE_V0_STABLE_ROW_SHA256,
        D.V0_NVIDIA_ROW0_SHA256)
    if v0n_decision.get("state") != D.V0N_STATE_NVIDIA_VARIABLE_STOP:
        raise PhysicalDiagnosticError(
            "Arm-A bridge V0n decision is not the accepted current "
            f"NVIDIA variable stop: {v0n_decision.get('state')}")
    for row_class in v0n_decision.get("row_classes", []):
        if row_class.get("novel") is not True:
            raise PhysicalDiagnosticError(
                "Arm-A bridge V0n rows are not the accepted novel "
                "population (equals AMD current or a retained #248 row)")
    return {"v0": v0_decision, "v0n": v0n_decision}



def _sha256_file(path: Path) -> str:
    """Row-digest seam (module-level for test injection).

    Production resolves to the canonical file SHA-256. Tests inject a
    translating digester when the accepted physical bytes are not on
    the CPU-only host (the accepted 993280-byte rows cannot be
    synthesized); the real content hash is always the fallback, so a
    mutated row rejects even under an injected digest map.
    """
    return D.file_sha256(path)


def _v0_refusal_is_adjudicated_stop(historical: PhysicalDiagnosticError
                                    ) -> bool:
    """CORRECTION ROUND 2: classify a historical-gate refusal EXACTLY.

    The historical gate's terminal refusal message carries the
    rederived V0 state ('V0 precedes CPU fallback; verified AMD
    variability required: <STATE>: <reason>'). Only an ADJUDICATED
    maintainer-stop state — the class the accepted bridge record was
    adjudicated against (DISAGREEMENT_STOP, CONCORDANCE_STOP, or the
    explicit third-required screen state) — may hand control to the
    bridge. V0_INVALID_BLOCKED (absent/unreadable/tampered/invalid V0
    evidence, network loss, custody failure) and every non-terminal
    failure re-raise unchanged: the bridge must never be reachable
    from an un-adjudicated failure. State names are matched EXACTLY
    (substring law, so a forged 'reason' string cannot smuggle a state
    name past the classifier)."""
    message = str(historical)
    prefix = "V0 precedes CPU fallback; verified AMD variability required: "
    reason = message[len(prefix):] if message.startswith(prefix) else ""
    if not reason:
        return False
    return any(state in reason for state in (
        D.V0_STATE_DISAGREEMENT_STOP,
        D.V0_STATE_CONCORDANCE_STOP,
        D.V0_STATE_IDENTICAL_PAIR_NEEDS_THIRD))


def _require_sequential_reachability(
        repo_root: Path, evidence_root: Path, arm: str,
        expected_head: str, model_attestation: dict[str, Any],
        revalidate_authority: Callable[..., dict[str, Any]] | None,
        github_api: str) -> None:
    """Verify the predecessor ladder from retained rows, never summaries.

    A condition may be cost-admissible and dispatched yet unreachable.
    This check runs before any physical runner/process and uses the same
    exact-head live authority and retained-byte verifiers as the reducer.

    Returns nothing; callers needing the Arm-A reachability SOURCE
    (historical AMD_VARIABLE vs post-V0n bridge) use
    ``arm_a_reachability_source``. METHODOLOGY-AMENDMENT-008: Arm A
    alone may additionally open through the post-V0n
    maintainer-adjudicated bridge record (validate_arm_a_bridge) when
    the accepted V0+V0n evidence combination — stable AMD cross-vendor
    disagreement plus a current-window NVIDIA VARIABLE_STOP — is
    authenticated from retained bytes. Every later arm still requires
    the historical `_require_v0_fallback`-preceded variable ladder
    verbatim.
    """
    if arm == "A-vulkan-necessity":
        arm_a_reachability_source(
            repo_root, evidence_root, expected_head, model_attestation,
            revalidate_authority, github_api)
        return
    _require_sequential_reachability_ladder(
        repo_root, evidence_root, arm, expected_head, model_attestation,
        revalidate_authority, github_api)


def arm_a_reachability_source(
        repo_root: Path, evidence_root: Path, expected_head: str,
        model_attestation: dict[str, Any],
        revalidate_authority: Callable[..., dict[str, Any]] | None,
        github_api: str) -> str:
    """Decide (and authenticate) HOW Arm A is reachable; fail closed.

    Returns the reachability provenance, exactly one of:
      * ``historical-v0-amd-variable`` — the historical AMD_VARIABLE
        law opened Arm A (retained V0 population re-verified variable
        through the frozen reducers and live dispatch authority);
      * ``arm-a-bridge`` — the top-level V0 state is an ADJUDICATED
        maintainer stop (or the V0 namespace is absent because the
        campaign root is bridge-only) AND the corrected AMENDMENT-008
        bridge authenticated the exact accepted predecessor decisions
        from retained bytes (validate_arm_a_bridge).

    Any other failure raises. Later arms are NOT decided here.

    CORRECTION ROUND 2: eligibility is decided from the rederived V0
    STATE, never from a refusal-message prefix. An invalid V0 state
    (absent/tampered/unreadable evidence, custody failure) can NEVER
    open the bridge — the state must be an adjudicated stop state, or
    the V0 namespace must be entirely absent (a bridge-only campaign
    root carries no top-level V0 evidence at all, and the bridge is
    then the only adjudicated path; the bridge itself revalidates the
    accepted V0 decision from the read-only mount).
    """
    import issue250_terminal as T
    state: dict[str, Any]
    try:
        state = T.derive_v0_state(
            Path(evidence_root),
            Path(evidence_root) / "accepted-248-contrast",
            Path(repo_root), expected_head,
            authority_fetcher=revalidate_authority, github_api=github_api)
    except Exception:
        state = {"state": D.V0_STATE_INVALID, "valid": False}
    if (state.get("state") == D.V0_STATE_AMD_VARIABLE
            and state.get("a_eligible") is True):
        return "historical-v0-amd-variable"
    v0_root = Path(evidence_root) / D.V0_NAMESPACE
    namespace_absent = not (v0_root.exists() or v0_root.is_symlink())
    if not namespace_absent:
        if state.get("state") not in (
                D.V0_STATE_DISAGREEMENT_STOP,
                D.V0_STATE_CONCORDANCE_STOP,
                D.V0_STATE_IDENTICAL_PAIR_NEEDS_THIRD):
            raise PhysicalDiagnosticError(
                "V0 precedes CPU fallback; verified AMD variability "
                f"required: {state.get('state')}: "
                f"{state.get('reason', 'V0 evidence invalid')}")
    validate_arm_a_bridge(Path(evidence_root), expected_head)
    return "arm-a-bridge"


def _require_sequential_reachability_ladder(
        repo_root: Path, evidence_root: Path, arm: str,
        expected_head: str, model_attestation: dict[str, Any],
        revalidate_authority: Callable[..., dict[str, Any]] | None,
        github_api: str) -> None:
    """Historical variable-ladder proof for every arm AFTER A."""
    import issue250_terminal as T

    root = Path(evidence_root)
    opening = root / MODEL_ATTESTATION_OPEN_NAME
    if opening.is_symlink() or not opening.is_file():
        raise PhysicalDiagnosticError("sequential campaign attestation missing")
    try:
        retained = json.loads(opening.read_bytes())
        validate_model_attestation(retained, expected_head)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        raise PhysicalDiagnosticError("sequential campaign attestation invalid") from exc
    if retained != model_attestation:
        raise PhysicalDiagnosticError("sequential campaign attestation mismatch")

    def authority(namespace: str, predecessor: str) -> dict[str, Any]:
        live = require_live_dispatch(
            repo_root, expected_head, namespace,
            revalidate_authority=revalidate_authority, github_api=github_api)
        if live.get("arm") != predecessor:
            raise PhysicalDiagnosticError(
                f"sequential {namespace} live dispatch binds wrong arm")
        return live

    def variable(pop: dict[str, Any], problems: list[str], label: str) -> None:
        verdict = T._walk_condition(pop)
        if problems or not verdict["nondeterministic"]:
            raise PhysicalDiagnosticError(
                f"sequential {label} requires verified variable rows: "
                f"{problems or verdict['population']}")

    try:
        a = authority("d250-arm-a", "A-vulkan-necessity")
        pop, problems = T._verify_namespace_population(
            root, "d250-arm-a", "A-vulkan-necessity", expected_head,
            a, retained, [u["tag"] for u in D.probe_list_for(
                "A-vulkan-necessity")], lambda tag: "accepted")
        variable(pop, problems, "Arm A CPU-only")
        if arm == "B-process-init":
            return

        b = authority("d250-arm-b", "B-process-init")
        plan_b = D.probe_list_for("B-process-init")
        fresh = [u["tag"] for u in plan_b if not u.get("same_process")]
        same = {u["tag"] for u in plan_b if u.get("same_process")}
        pop, problems = T._verify_namespace_population(
            root, "d250-arm-b", "B-process-init", expected_head,
            b, retained, fresh, lambda tag: "accepted",
            extra_expected=same)
        variable(pop, problems, "Arm B fresh")
        pop, problems = T._verify_same_process_units(
            root, "d250-arm-b", "B-process-init", expected_head,
            b, retained)
        variable(pop, problems, "Arm B same-process")
        if arm == "C-cpu-threads":
            return

        c = authority("d250-arm-c", "C-cpu-threads")
        pop, problems = T._verify_namespace_population(
            root, "d250-arm-c", "C-cpu-threads", expected_head,
            c, retained, [u["tag"] for u in D.probe_list_for(
                "C-cpu-threads")], lambda tag: "accepted")
        variable(pop, problems, "Arm C default")
        if arm in ("C1-reduced-parallelism", D.ARM_C2_NAME):
            return  # C2 additionally checks C1 via c2_launch_allowed.
        if arm != "D-context-transition":
            raise PhysicalDiagnosticError("unknown sequential arm")

        c2 = authority(D.C2_SERIAL_NAMESPACE, D.ARM_C2_NAME)
        c2_launch_allowed(
            D.C2_SERIAL_NAMESPACE, D.ARM_C2_NAME, c2, expected_head,
            root, repo_root=repo_root, model_attestation=retained,
            revalidate_authority=revalidate_authority, github_api=github_api)
        pop, problems = T._verify_namespace_population(
            root, D.C2_SERIAL_NAMESPACE, D.ARM_C2_NAME, expected_head,
            c2, retained, [u["tag"] for u in D.probe_list_for(
                D.ARM_C2_NAME)], lambda tag: "accepted")
        variable(pop, problems, "Arm C2 serial")
    except PhysicalDiagnosticError:
        raise
    except (OSError, ValueError, TypeError, KeyError,
            D.DiagnosticError) as exc:
        raise PhysicalDiagnosticError(
            f"sequential predecessor verification failed: {exc}") from exc


def _require_v0_fallback(repo_root: Path, evidence_root: Path,
                         expected_head: str,
                         revalidate_authority: Callable[..., dict[str, Any]] | None,
                         github_api: str) -> None:
    """No CPU fallback until the retained historical + AMD V0 gate varies.

    The accepted #248 contrast corpus must be mounted under this evidence
    root as accepted-248-contrast; absence blocks, never guesses a digest.
    """
    import issue250_terminal as T
    try:
        state = T.derive_v0_state(
            Path(evidence_root), Path(evidence_root) / "accepted-248-contrast",
            Path(repo_root), expected_head,
            authority_fetcher=revalidate_authority, github_api=github_api)
    except Exception as exc:
        raise PhysicalDiagnosticError(
            f"V0 predecessor evidence unavailable: {exc}") from exc
    if (state.get("valid") is not True
            or state.get("state") != D.V0_STATE_AMD_VARIABLE
            or state.get("a_eligible") is not True):
        raise PhysicalDiagnosticError(
            f"V0 precedes CPU fallback; verified AMD variability required: "
            f"{state.get('reason', state.get('state'))}")


def timeout_budget_condition_is_c2(unit: dict[str, Any]) -> bool:
    return TB.unit_condition(unit) == "arm-c2-serial"


def c2_unit(unit: dict[str, Any]) -> dict[str, Any]:
    """Mark a C2-serial plan unit as gate-authorized (dedicated path).

    The RETURNED copy carries ``c2_serial_authorized`` so
    ``server_argv`` accepts it; the copy is produced only AFTER
    ``c2_launch_allowed`` succeeded (the dedicated C2 driver calls
    them in that order). The frozen plan itself never carries the
    flag.
    """
    if tuple(unit.get("argv_delta", ())) != \
            (("-dev", "none") + D.ARM_C2_ARGV_DELTA):
        raise PhysicalDiagnosticError(
            "c2_unit refuses non-serial units")
    out = dict(unit)
    out["c2_serial_authorized"] = True
    return out


def launch_env(out_prefix: Path) -> dict[str, str]:
    """Environment for one #250 server launch (accepted observer env)."""
    identity = I.frozen_identity(ARM)
    env = {**identity["selector"], "VK_ICD_FILENAMES": identity["icd"],
           "CUDA_VISIBLE_DEVICES": "-1",
           "LLAMA_OBSERVE_CAPTURE": "8",
           "LLAMA_OBSERVE_OUT": str(out_prefix),
           "LLAMA_OBSERVE_FORCE": ""}
    return env


# ---------------------------------------------------------------------------
# Unit directories (append-only; quarantine-before-rerun)
# ---------------------------------------------------------------------------

def prepare_unit_dir(root: Path, namespace: str, tag: str) -> Path:
    """Create (or refuse to replace) the append-only unit directory."""
    base = D.namespace_dir(root, namespace)
    base.mkdir(parents=True, exist_ok=True)
    unit = base / tag
    if unit.exists() or unit.is_symlink():
        raise D.DiagnosticError(
            f"existing diagnostic unit cannot be replaced: {unit}. "
            f"Move it to a -quarantined sibling first (append-only custody).")
    unit.mkdir()
    return unit


def quarantine_unit(root: Path, namespace: str, tag: str) -> Path:
    """Move a failed/superseded unit aside; never overwrite in place."""
    base = D.namespace_dir(root, namespace)
    unit = base / tag
    if not unit.is_dir():
        raise D.DiagnosticError(f"unit to quarantine does not exist: {unit}")
    target = base / f"{tag}-quarantined"
    if target.exists():
        raise D.DiagnosticError(f"quarantine target already exists: {target}")
    unit.rename(target)
    return target


# ---------------------------------------------------------------------------
# Raw observation helpers (device samples; injectable runner seams)
# ---------------------------------------------------------------------------

def _device_sample() -> dict[str, Any]:
    """One residency/telemetry sample (same seam as accepted #248)."""
    sample: dict[str, Any] = {
        "stage": None, "captured_at": _utcnow(), "residency_mib": {}}
    smi = subprocess.run(
        ["nvidia-smi", "--query-gpu=uuid,memory.used",
         "--format=csv,noheader,nounits"],
        capture_output=True, text=True, timeout=15).stdout
    for line in smi.splitlines():
        fields = [f.strip() for f in line.split(",")]
        if len(fields) == 2:
            sample["residency_mib"]["00000000:03:00.0"] = int(fields[1])
    telemetry = subprocess.run(
        ["nvidia-smi", f"--query-gpu={H.NVIDIA_QUERY}",
         "--format=csv,noheader,nounits"],
        capture_output=True, text=True, timeout=15)
    if telemetry.returncode != 0 or not telemetry.stdout:
        raise PhysicalDiagnosticError(
            "in-window NVIDIA telemetry unavailable")
    sample["nvidia_smi_raw"] = telemetry.stdout
    return sample


def _http_completion(port: int, request: dict[str, Any],
                     prompt: str, timeout_s: float | None = None,
                     ) -> tuple[bytes, dict[str, Any]]:
    """One completion POST under the unit's frozen timeout budget.

    CORRECTION PASS 6 (AMENDMENT-003): the retired global
    HTTP_TIMEOUT_S = 1200 constant is GONE from the request path.
    ``timeout_s`` is the unit's derived budget
    (issue250_timeout.request_timeout_budget) — production callers
    MUST pass it; the None default exists so stale callers fail
    loudly (ValueError) instead of silently inheriting any constant.
    A timeout is still a FAILED request/unit and never numerical
    evidence.
    """
    if timeout_s is None:
        raise ValueError(
            "refusing an unbounded completion request: pass the "
            "unit's frozen timeout budget (issue250_timeout."
            "request_timeout_budget) — the retired global 1200 s "
            "constant killed a legitimate CPU-only prefill at 83%")
    payload = json.dumps({**request, "prompt": prompt}).encode()
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/completion", data=payload,
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout_s) as response:
        if response.status != 200:
            raise PhysicalDiagnosticError(
                f"completion HTTP status {response.status}")
        raw = response.read(1024 * 1024)
    return raw, json.loads(raw)


def _wait_healthy(proc: subprocess.Popen, port: int) -> None:
    deadline = time.monotonic() + SERVER_READY_TIMEOUT_S
    ready = False
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise PhysicalDiagnosticError(
                f"server exited early rc={proc.returncode}")
        try:
            with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/health", timeout=2) as response:
                if response.status == 200:
                    ready = True
                    break
        except (urllib.error.URLError, OSError):
            time.sleep(1.0)
    if not ready:
        raise PhysicalDiagnosticError("server never became healthy")


def _proc_attribution(proc: subprocess.Popen, argv: list[str],
                      env: dict[str, str]) -> dict[str, Any]:
    exe = os.path.realpath(f"/proc/{proc.pid}/exe")
    return {
        "server_pid": proc.pid,
        "server_exe_sha256": D.file_sha256(Path(exe)),
        "server_argv": list(argv),
        "server_env": dict(env),
    }


def _observe_arm_identity() -> dict[str, Any]:
    """Raw device identity observation (accepted #248 seam)."""
    return I.observe_arm_identity(ARM)


# ---------------------------------------------------------------------------
# Physical execution (one fresh process per unit)
# ---------------------------------------------------------------------------

def _real_execute(argv: list[str], env: dict[str, str],
                  request: dict[str, Any], prompt: str, port: int,
                  unit_dir: Path,
                  timeout_budget: dict[str, Any] | None = None,
                  ) -> dict[str, Any]:
    """Launch one fresh server process; issue one completion; tear down.

    CORRECTION PASS 6 (AMENDMENT-003): production callers pass the
    unit's frozen ``timeout_budget``; the completion deadline is
    budget["budget_s"]. The budget dict is mirrored into the result
    so the unit receipt retains the exact policy (invariant D).
    """
    samples = [_device_sample() | {"stage": "before"}]
    full_env = {**os.environ, **env}
    log_path = unit_dir / "server.log"
    with log_path.open("wb") as log_file:
        proc = subprocess.Popen(
            argv, env=full_env, stdout=log_file, stderr=subprocess.STDOUT,
            start_new_session=True)
        attribution: dict[str, Any] = {}
        try:
            _wait_healthy(proc, port)
            attribution = _proc_attribution(proc, argv, env)
            stop = threading.Event()
            errors: list[Exception] = []

            def sample_loop() -> None:
                while not stop.is_set():
                    try:
                        samples.append(_device_sample() | {"stage": "during"})
                    except Exception as exc:  # pragma: no cover
                        errors.append(exc)
                        return
                    time.sleep(2.0)

            samples.append(_device_sample() | {"stage": "during"})
            thread = threading.Thread(target=sample_loop, daemon=True)
            thread.start()
            try:
                if timeout_budget is None:
                    raise PhysicalDiagnosticError(
                        "_real_execute requires the unit's frozen "
                        "timeout budget (AMENDMENT-003)")
                raw, response = _http_completion(
                    port, request, prompt,
                    timeout_s=timeout_budget["budget_s"])
            finally:
                stop.set()
                thread.join(timeout=2)
            if errors:
                raise PhysicalDiagnosticError(
                    "device sampling failed") from errors[0]
            samples.append(_device_sample() | {"stage": "after"})
            tokens = response.get("tokens", response.get("tokens_predicted"))
            return {"returncode": proc.poll(),
                    "tokens": tokens, "response_raw": raw,
                    "timeout_budget": timeout_budget,
                    "process_attribution": attribution,
                    "device_samples": samples}
        finally:
            if proc.poll() is None:
                os.killpg(proc.pid, signal.SIGTERM)
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(proc.pid, signal.SIGKILL)
                    proc.wait(timeout=5)


def _collect_rows(unit_dir: Path) -> tuple[dict[str, bytes], list[dict]]:
    """Collect r8i3 observer rows + meta from a unit directory."""
    rows: dict[str, bytes] = {}
    meta_raw = (unit_dir / "obs.meta.json").read_bytes()
    meta = [json.loads(line) for line in meta_raw.decode().splitlines()
            if line.strip()]
    for d in range(D.DECISIONS):
        rows[str(d)] = (unit_dir / f"obs.row{d}.f32").read_bytes()
    return rows, meta


def run_diagnostic_unit(
    repo_root: Path, evidence_root: Path, namespace: str, arm: str,
    tag: str, *, binary: Path, binary_id: str,
    model_dir: Path, expected_head: str,
    model_attestation: dict[str, Any],
    execute: Callable[..., dict[str, Any]] | None = None,
    identity_observer: Callable[[], dict[str, Any]] | None = None,
    revalidate_authority: Callable[..., dict[str, Any]] | None = None,
    request_contract: dict[str, Any] | None = None,
    health_runner: Callable[..., Any] = H._run_readonly,
    github_api: str = "https://api.github.com",
) -> dict[str, Any]:
    """Execute ONE fresh-process diagnostic unit under full gating.

    GATE ORDER (fail fast, all before any launch):
      namespace<->arm exact binding -> frozen plan membership ->
      fresh evidence generation + retained canonical cost admission ->
      EARLY live dispatch authority -> exact clean local head ->
      retained-byte sequential predecessor proof (live per-arm dispatch,
      canonical opening attestation, verified variable rows) ->
      fixture authority -> campaign model attestation + stat witness ->
      binary identity -> request contract -> subject identity (pre) ->
      prelaunch custody -> FINAL live dispatch authority + repeated
      sequential proof (two-pass binding + clean head re-check) ->
      physical launch.

    ``execute``/``identity_observer``/``revalidate_authority``/
    ``health_runner`` are injectable test seams; production resolves
    the real implementations. There is NO authority parameter.
    """
    repo_root = Path(repo_root).resolve(strict=True)
    # Namespace<->arm exact binding (blocker 5) FIRST. AMENDMENT-003:
    # the dedicated d250-arm-c2 <-> C2-serial pairing is validated by
    # its own gate (c2_launch_allowed) instead of the auto-reachable
    # binding map — no generic dispatch can ever reach it.
    if not (namespace == D.C2_SERIAL_NAMESPACE and arm == D.ARM_C2_NAME):
        D.validate_namespace_arm_binding(namespace, arm)
    plan = D.probe_list_for(arm)
    tags = [u["tag"] for u in plan]
    if tag not in tags:
        raise PhysicalDiagnosticError(
            f"unit {tag!r} is not in the frozen plan for arm {arm}")
    unit = next(u for u in plan if u["tag"] == tag)
    if unit.get("same_process"):
        raise PhysicalDiagnosticError(
            "same-process units run through run_same_process_lifecycle; "
            "the fresh-process unit path cannot satisfy Arm B arm-2")
    # No runner, subprocess, fixture or model operation precedes cost
    # admission: even the clean-head Git subprocess runs only afterward.
    canonical_generation = validate_evidence_generation(Path(evidence_root))
    condition = _unit_cost_condition(unit, arm)
    if condition == "arm-c2-serial":
        # Authenticate the complete retained canonical cost record before
        # fetching authority; only the dedicated C2 gate may admit spend.
        _retained_cost_verdict(evidence_root, condition, namespace, arm)
    else:
        _admit_retained_cost(evidence_root, condition, namespace, arm)
    authority_early = require_live_dispatch(
        repo_root, expected_head, namespace,
        revalidate_authority=revalidate_authority, github_api=github_api)
    if authority_early.get("arm") != arm:
        raise PhysicalDiagnosticError(
            "live dispatch arm does not match the executing arm")
    D._require_clean_head(repo_root, expected_head)
    # AMENDMENT-008 r2: persist the authenticated Arm-A reachability
    # provenance (historical AMD_VARIABLE vs post-V0n bridge) in every
    # Arm-A unit receipt; later arms carry none.
    reachability_source: str | None = None
    if arm == "A-vulkan-necessity":
        reachability_source = arm_a_reachability_source(
            repo_root, Path(evidence_root), expected_head,
            model_attestation, revalidate_authority, github_api)
    else:
        _require_sequential_reachability(
            repo_root, Path(evidence_root), arm, expected_head,
            model_attestation, revalidate_authority, github_api)
    c2_gate = None
    if condition == "arm-c2-serial":
        c2_gate = c2_launch_allowed(
            namespace, arm, authority_early, expected_head,
            Path(evidence_root), repo_root=repo_root,
            model_attestation=model_attestation,
            revalidate_authority=revalidate_authority, github_api=github_api)
    # The canonical generation and cost record were checked before
    # dispatch and before any process/subprocess could be started.
    fixtures = verify_fixtures(repo_root)
    binary_sha = verify_binary(Path(binary), binary_id)
    attestation = validate_model_attestation(model_attestation,
                                             expected_head)
    retained_opening_path = (Path(evidence_root)
                             / MODEL_ATTESTATION_OPEN_NAME)
    if (retained_opening_path.is_symlink()
            or not retained_opening_path.is_file()):
        raise PhysicalDiagnosticError(
            "campaign opening model attestation is not retained in the "
            f"evidence root: {retained_opening_path}")
    retained_opening = json.loads(retained_opening_path.read_bytes())
    if attestation != retained_opening:
        raise PhysicalDiagnosticError(
            "unit attestation differs from the retained campaign opening")
    witness_problems, stat_witness = attestation_witness(
        Path(model_dir), attestation)
    if witness_problems:
        raise PhysicalDiagnosticError(
            "model stat witness drift — full re-hash required before "
            f"further execution: {witness_problems}")
    if attestation["model_dir"] != str(Path(model_dir)):
        raise PhysicalDiagnosticError(
            "attested model dir differs from the launched model dir")
    launch_member = Path(model_dir) / D.MODEL_MEMBER_1

    if unit.get("ladder_length"):
        length = unit["ladder_length"]
        base = fixtures[D.CASE]
        prompt = derive_ladder_prompt(
            base["prompt_text"], length, base["sentence_repeats"])
        prompt_token_ids = None  # ladder token ids live in the authority
        # CORRECTION PASS 3 (blocker 4A): the ACTUAL token count comes
        # from the retained campaign ladder-token-authority document,
        # derived BEFORE physical Arm-D execution through the pinned
        # tokenizer (see derive_ladder_token_authority). No ladder unit
        # can execute without it — a nominal label is never a token
        # count.
        authority_doc = load_ladder_token_authority(
            evidence_root, expected_head)
        entry = authority_doc["lengths"].get(str(length))
        if entry is None:
            raise PhysicalDiagnosticError(
                f"retained ladder token authority does not cover "
                f"nominal length {length}")
        validate_ladder_token_authority_entry(entry, prompt)
        token_authority = entry
    else:
        prompt = fixtures[D.CASE]["prompt_text"]
        prompt_token_ids = fixtures[D.CASE]["prompt_token_ids"]
        token_authority = None

    unit_dir = prepare_unit_dir(evidence_root, namespace, tag)

    identity_pre = (identity_observer or _observe_arm_identity)()
    problems_pre = I.identity_problems(ARM, identity_pre)
    if problems_pre:
        _write_json(unit_dir / "identity-pre.json", identity_pre)
        raise PhysicalDiagnosticError(
            f"pre-launch identity drift: {problems_pre}")

    if unit.get("request") == "arm-b":
        raise PhysicalDiagnosticError(
            "arm-b contract extension is same-process only")
    request = D.validate_request_contract(
        request_contract if request_contract is not None
        else D.REQUEST_CONTRACT)

    if TB.unit_condition(unit) == "arm-c2-serial":
        # Dedicated C2 cost + C1 proof closed before fixtures/model operations.
        if c2_gate is None:
            raise PhysicalDiagnosticError("serial C2 gate not established")
        unit = c2_unit(unit)
    out_prefix = unit_dir / "obs"
    env = launch_env(out_prefix)
    argv = server_argv(Path(binary), launch_member, unit)
    # TIMEOUT-BUDGET AUTHORITY (AMENDMENT-003): the frozen per-unit
    # budget, derived from the retained planning basis BEFORE launch.
    # C2-serial units are refused by the budget law unless the
    # dedicated d250-arm-c2 gate already fired (c2_launch_allowed).
    expected_prompt_tokens = (
        len(prompt_token_ids) if prompt_token_ids is not None
        else TB.DEFAULT_PROMPT_TOKENS)
    timeout_budget = TB.request_timeout_budget(
        unit, prompt_tokens=expected_prompt_tokens,
        c2_serial_gate_authorized=(
            TB.unit_condition(unit) == "arm-c2-serial"))
    timeout_budget["timeout_policy_sha256"] = TB.timeout_budget_digest(
        timeout_budget)
    TB.verify_timeout_budget_block(
        timeout_budget, unit, prompt_tokens=expected_prompt_tokens)
    if timeout_budget["condition"] == "arm-c2-serial" and not unit.get(
            "c2_serial_authorized"):
        raise PhysicalDiagnosticError(
            "serial C2 unit reached the launch path without the "
            "d250-arm-c2 gate (AMENDMENT-003)")

    # FINAL GOVERNANCE GATE: second live fetch bound to the first;
    # remote drift between preflight and launch => zero runner calls.
    authority_late = require_live_dispatch(
        repo_root, expected_head, namespace,
        revalidate_authority=revalidate_authority, github_api=github_api)
    final_authority = D.bind_authority_observations(
        authority_early, authority_late)
    if final_authority.get("arm") != arm:
        raise PhysicalDiagnosticError(
            "final live dispatch arm does not match the executing arm")
    if c2_gate is not None:
        c1_late = require_live_dispatch(
            repo_root, expected_head, "d250-arm-c1",
            revalidate_authority=revalidate_authority, github_api=github_api)
        D.bind_authority_observations(c2_gate["authority"], c1_late)
        if not D.c1_dispatch_c2_unlocked(
                evidence_root, expected_head, c2_authority=final_authority,
                c1_authority=c1_late, c1_verdict=c2_gate["verdict"]):
            raise PhysicalDiagnosticError("C2 gate record drift before launch")
        _admit_retained_cost(evidence_root, "arm-c2-serial", namespace, arm,
                             c2_gate_authorized=True)
    _require_sequential_reachability(
        repo_root, Path(evidence_root), arm, expected_head,
        model_attestation, revalidate_authority, github_api)
    D._require_clean_head(repo_root, expected_head)
    # A preflight-valid record can be replaced during fixture/identity or
    # sequential verification. Re-read it immediately before the physical
    # runner; even a re-signed lower cost never grants launch authority.
    _admit_retained_cost(
        evidence_root, condition, namespace, arm,
        c2_gate_authorized=(c2_gate is not None))

    unit_started_at = _utcnow()
    started = time.monotonic()
    runner = execute or _real_execute
    result = runner(argv=argv, env=env, request=request,
                    prompt=prompt, port=PORT, unit_dir=unit_dir,
                    timeout_budget=timeout_budget)
    wall = time.monotonic() - started
    unit_ended_at = _utcnow()

    return _finalize_unit_receipt(
        unit_dir=unit_dir, tag=tag, namespace=namespace, arm=arm,
        unit=unit, result=result, request=request, argv=argv, env=env,
        binary_id=binary_id, binary_sha=binary_sha,
        attestation=attestation, stat_witness=stat_witness,
        model_dir=model_dir, launch_member=launch_member,
        prompt=prompt, prompt_token_ids=prompt_token_ids,
        identity_pre=identity_pre, identity_observer=identity_observer,
        problems_pre=problems_pre, final_authority=final_authority,
        unit_started_at=unit_started_at, unit_ended_at=unit_ended_at,
        wall=wall, health_runner=health_runner,
        token_authority=token_authority,
        reachability_source=reachability_source,
        canonical_generation=canonical_generation)


def _finalize_unit_receipt(*, unit_dir, tag, namespace, arm, unit, result,
                           request, argv, env, binary_id, binary_sha,
                           attestation, stat_witness, model_dir,
                           launch_member, prompt, prompt_token_ids,
                           identity_pre, identity_observer, problems_pre,
                           final_authority, unit_started_at, unit_ended_at,
                           wall, health_runner,
                           same_process_block=None,
                           token_authority=None,
                           reachability_source=None,
                           canonical_generation=EVIDENCE_GENERATION,
                           ) -> dict[str, Any]:
    """Post-execution custody: identity postcheck, rows, health, receipt."""
    identity_post = (identity_observer or _observe_arm_identity)()
    problems_post = I.identity_problems(ARM, identity_post)
    _write_json(unit_dir / "identity-pre.json", identity_pre)
    _write_json(unit_dir / "identity-post.json", identity_post)
    if problems_post:
        raise PhysicalDiagnosticError(
            f"post-execution identity drift: {problems_post}")

    tokens = result.get("tokens")
    if (not isinstance(tokens, list) or len(tokens) != D.DECISIONS
            or any(type(t) is not int for t in tokens)):
        raise PhysicalDiagnosticError(f"{tag}: malformed token output")
    (unit_dir / "response.json.raw").write_bytes(result["response_raw"])

    device_samples = result.get("device_samples")
    if not isinstance(device_samples, list):
        raise PhysicalDiagnosticError("execution returned no device samples")
    health_receipt = H.capture_platform_health(
        unit_dir, unit_started_at, unit_ended_at,
        samples=device_samples, runner=health_runner)
    verified_health = H.verify_platform_health(
        unit_dir, health_receipt,
        expected_gpu_uuid=I.REFERENCE_IDENTITY["gpu_uuid"],
        expected_bdf=I.frozen_identity(ARM)["bdf"],
        expected_arm=ARM)
    if not verified_health["valid"]:
        raise PhysicalDiagnosticError(
            f"retained platform health invalid: "
            f"{verified_health['problems']}")

    receipt: dict[str, Any] = {
        "schema": UNIT_SCHEMA,
        "kind": "diagnostic-unit",
        "namespace": namespace,
        "arm_id": arm,
        "tag": tag,
        "case_id": D.CASE,
        "arm": ARM,
        "unit": {k: (list(v) if isinstance(v, tuple) else v)
                 for k, v in unit.items()},
        "ngl": unit["ngl"],
        "argv_delta": list(unit.get("argv_delta", ())),
        "binary_id": binary_id,
        "binary_sha256": binary_sha,
        "model_dir": str(model_dir),
        "model_attestation_sha256": attestation["attestation_sha256"],
        "model_stat_witness": stat_witness,
        "model_launch_member": str(launch_member),
        "request_contract": request,
        "request_contract_sha256": D.canonical_request_digest(request),
        "prompt_len": len(prompt),
        "prompt_token_ids": prompt_token_ids,
        "prompt_sha256": D.sha256_bytes(prompt.encode()),
        "ladder_token_authority": token_authority,
        "server_argv": argv,
        "server_env": {k: env[k] for k in sorted(env)
                       if k.startswith(("LLAMA_", "VK_", "CUDA_"))},
        "process_attribution": result.get("process_attribution"),
        "platform_health": health_receipt,
        "platform_health_receipt": {
            "path": "platform-health-receipt.json",
            "bytes": len((unit_dir / "platform-health-receipt.json")
                         .read_bytes()),
            "sha256": D.file_sha256(
                unit_dir / "platform-health-receipt.json"),
            "window": {"start": unit_started_at, "end": unit_ended_at},
        },
        "tokens": tokens,
        "response_raw_sha256": D.sha256_bytes(result["response_raw"]),
        "deterministic_output_sha256": D.canonical_token_digest(tokens),
        "identity_problems_pre": problems_pre,
        "identity_problems_post": problems_post,
        "subject_identity_schema": I.IDENTITY_SCHEMA,
        "authority": unit_authority_block(final_authority),
        # AMENDMENT-008 r2: bridge-path provenance. Present (and one of
        # the two frozen vocabulary values) on EVERY Arm-A receipt;
        # absent on every later arm. Persisted from the authenticated
        # launch-gate decision, never caller-supplied.
        "reachability_source": reachability_source,
        # CORRECTION PASS 6 (AMENDMENT-003): receipts identify the
        # evidence generation and retain the exact timeout policy that
        # governed the request (budget + derivation inputs + digest).
        "evidence_generation": canonical_generation,
        "timeout_policy": result.get("timeout_budget"),
        "wall_time_s": wall,
    }
    meta_path = unit_dir / "obs.meta.json"
    if meta_path.is_file():
        rows, metadata = _collect_rows(unit_dir)
        if (len(metadata) != D.DECISIONS
                or any(not isinstance(m, dict) or m.get("pos") != i
                       for i, m in enumerate(metadata))):
            raise PhysicalDiagnosticError("observer meta population malformed")
        receipt["observer_rows"] = [D.row_digest(rows[str(i)])
                                    for i in range(D.DECISIONS)]
        receipt["observer_meta_sha256"] = D.file_sha256(meta_path)
    else:
        raise PhysicalDiagnosticError(
            "required full-row capture missing (observer seam)")
    if same_process_block is not None:
        receipt["same_process"] = same_process_block
    _write_json(unit_dir / "unit.json", receipt)
    return receipt


def unit_authority_block(final_authority: dict[str, Any]) -> dict[str, Any]:
    """Canonical per-unit dispatch-authority block (receipt binding)."""
    if not isinstance(final_authority, dict):
        raise D.DiagnosticError("final authority must be a dict")
    return {
        "comment_id": final_authority["comment_id"],
        "head_sha": final_authority["head_sha"],
        "namespace": final_authority["namespace"],
        "arm": final_authority["arm"],
        "created_at": final_authority["created_at"],
        "author_association": final_authority["author_association"],
        "pr_number": D.DIAGNOSTIC_PR_NUMBER,
        "issue_number": D.DIAGNOSTIC_ISSUE,
        "dispatch_sha256": D.authority_digest(final_authority),
    }


# ---------------------------------------------------------------------------
# Same-process Arm-B lifecycle (correction pass 2: one process, five
# equivalent requests, reset semantics proven per request).
#
# CORRECTION PASS 3 (NO-GO 5847890177, blockers 1+3):
#   * authority is revalidated LIVE before EACH completion request
#     (not only before the launch) and cross-bound to the original
#     dispatch generation;
#   * the reset proof is bound to the CURRENT request's task identity
#     through the pinned server's ACTUAL log grammar.
#
# Pinned grammar (llama.cpp b29c606e, server-common.h SLT_INF prefix
# ``slot %12s: id %2d | task %d |``; verified against the retained
# #248 evidence logs):
#   selection : "slot get_availabl: id  3 | task -1 | selected slot
#                by id (3)"          (slot.task is unset during
#               get_available_slot -> the task field is STRUCTURALLY
#               -1 here; task identity therefore comes from the
#               launch line, not the selection line)
#   launch    : "slot launch_slot_: id  3 | task 7 | processing task,
#                is_child = 0"
#   timing    : "slot print_timing: id  3 | task 7 | prompt eval time
#                =  48215.02 ms /  3077 tokens (...)"
# Every request consumes a fresh task id from the server's monotonic
# counter (server-queue.cpp get_new_id: ``id++``; /health consumes no
# task id, but NEXT_RESPONSE/control tasks may — task ids are NOT
# assumed equal to request indexes). The proof is therefore a
# REQUEST-DELIMITED LOG STATE MACHINE: selection-by-id(slot 3) ->
# launch(slot 3, task N, processing task) -> prompt-eval(slot 3,
# task N, EXACTLY the expected token count), with N fresh w.r.t. all
# task ids consumed by earlier requests of the SAME lifecycle.
# ---------------------------------------------------------------------------

_SLOT_LINE = r"slot\s+[^\s:]+:\s*id\s+{id}\s*\|\s*task\s*(-?\d+)\s*\|"


def _slot_line_re(slot_id: int) -> re.Pattern[str]:
    return re.compile(_SLOT_LINE.format(id=slot_id))


SELECTION_BY_ID_RE = re.compile(
    r"slot\s+get_availabl:[^\n]*\bid\s+3\b[^\n]*task\s+-1\b[^\n]*"
    r"selected slot by id\s*\(3\)")
# a non-by-id selection (LRU/LCP) mentioning slot 3 must NOT satisfy
# the selected-by-id requirement
SELECTION_NOT_BY_ID_RE = re.compile(
    r"slot\s+get_availabl:[^\n]*\bid\s+3\b[^\n]*"
    r"selected slot by (?!id)")
LAUNCH_TASK_RE = re.compile(
    _SLOT_LINE.format(id=3).replace("(-?\\d+)", "(-?\\d+)") +
    r"[^\n]*processing task")
PROMPT_EVAL_TASK_RE = re.compile(
    r"slot\s+[^\s:]+:\s*id\s+3\s*\|\s*task\s+(\d+)\s*\|[^\n]*"
    r"prompt eval time\s*=\s*[0-9.]+ ms\s*/\s*(\d+)\s*tokens")


def _parse_slot_log(text: str, request_index: int,
                    expected_prompt_tokens: int,
                    consumed_task_ids: frozenset[int] | set[int] = frozenset(),
                    ) -> dict[str, Any]:
    """Prove reset semantics for one same-process request from the
    retained server-log slice, BOUND to the current request's task.

    Fail-closed requirements (all must hold):
      1. the LAST selection line for slot 3 in the slice selects BY
         ID (an LRU/LCP selection is fatal);
      2. after that selection, slot 3 launches EXACTLY ONE task N
         ("processing task");
      3. a prompt-eval line for slot 3 | task N covers EXACTLY
         ``expected_prompt_tokens`` (full recompute; a smaller count
         is cache reuse and is fatal);
      4. task N is FRESH: not among ``consumed_task_ids`` (the task
         ids proven by earlier requests of this lifecycle) — delayed
         evidence from request N-1 carries request N-1's task id and
         CANNOT certify request N;
      5. exactly one fresh task boundary exists (two unseen task ids
         is ambiguous -> fail closed).

    Returns the mechanically parsed task id and evidence; raises
    nothing (callers check ``proven``).
    """
    consumed = set(consumed_task_ids)
    selection_matches = list(SELECTION_BY_ID_RE.finditer(text))
    lru_matches = list(SELECTION_NOT_BY_ID_RE.finditer(text))
    last_selection_end = (
        selection_matches[-1].end() if selection_matches else -1)
    # a non-by-id selection AFTER the last by-id selection means the
    # slot was re-selected without id pinning (fatal); before it, an
    # earlier request's LRU line is historical noise only if a later
    # by-id selection exists for the fresh task
    late_lru = [m for m in lru_matches if m.start() > last_selection_end]
    launches = [(m.start(), int(m.group(1)))
                for m in LAUNCH_TASK_RE.finditer(text)
                if m.start() > last_selection_end]
    evals = [(m.start(), int(m.group(1)), int(m.group(2)))
             for m in PROMPT_EVAL_TASK_RE.finditer(text)]
    fresh_launches = [(pos, tid) for pos, tid in launches
                      if tid not in consumed]
    problems: list[str] = []
    if not selection_matches:
        problems.append("no slot-3 selected-by-id line in slice")
    if late_lru:
        problems.append("slot 3 selected by LRU/LCP after the by-id "
                        "selection")
    if not fresh_launches:
        problems.append(
            "no launch of a FRESH task on slot 3 after the by-id "
            "selection (delayed prior-task evidence cannot certify "
            "this request)")
    if len({tid for _, tid in fresh_launches}) > 1:
        problems.append("multiple conflicting fresh task boundaries")
    task_id: int | None = None
    prompt_eval_tokens: int | None = None
    if fresh_launches:
        task_id = fresh_launches[-1][1]
        task_evals = [n for _, tid, n in evals if tid == task_id]
        if not task_evals:
            problems.append(
                f"no prompt-eval line for the current task {task_id}")
        else:
            prompt_eval_tokens = task_evals[-1]
            if prompt_eval_tokens != expected_prompt_tokens:
                problems.append(
                    f"prompt eval covers {prompt_eval_tokens} tokens != "
                    f"expected {expected_prompt_tokens} (cache reuse or "
                    f"wrong-task evidence)")
        prior_evals = sorted({tid for _, tid, _ in evals
                              if tid in consumed})
        if prior_evals:
            problems.append(
                f"slice carries delayed prompt-eval evidence of prior "
                f"tasks {prior_evals}")
    proven = not problems
    return {
        "request_index": request_index,
        "task_id": task_id,
        "slot_selected_by_id": bool(selection_matches) and not late_lru,
        "launch_proven": bool(fresh_launches),
        "prompt_eval_tokens": prompt_eval_tokens,
        "full_recompute_proven": (
            proven and prompt_eval_tokens == expected_prompt_tokens),
        "consumed_prior_task_ids": sorted(consumed),
        "problems": problems,
        "proven": proven,
    }


def _validate_reset_proof(proof: dict[str, Any], index: int) -> int:
    """Fail-closed check of one parsed reset proof; returns task id."""
    if (not isinstance(proof, dict) or not proof.get("proven")
            or proof.get("request_index") != index
            or type(proof.get("task_id")) is not int
            or not proof.get("slot_selected_by_id")
            or not proof.get("launch_proven")
            or not proof.get("full_recompute_proven")):
        detail = (proof.get("problems") if isinstance(proof, dict)
                  else "malformed proof")
        raise PhysicalDiagnosticError(
            f"same-process request {index} lacks a task-bound reset "
            f"proof (slot-by-id + fresh-task launch + full prompt "
            f"recompute): {detail}")
    return proof["task_id"]


def run_same_process_lifecycle(
    repo_root: Path, evidence_root: Path, namespace: str, arm: str,
    tag_prefix: str, *, binary: Path, binary_id: str,
    model_dir: Path, expected_head: str,
    model_attestation: dict[str, Any],
    execute: Callable[..., dict[str, Any]] | None = None,
    identity_observer: Callable[[], dict[str, Any]] | None = None,
    revalidate_authority: Callable[..., dict[str, Any]] | None = None,
    health_runner: Callable[..., Any] = H._run_readonly,
    github_api: str = "https://api.github.com",
) -> dict[str, Any]:
    """Execute the Arm-B same-process population under full gating.

    ONE server launch (CPU-only `-dev none`), slot 3 pinned via the
    frozen ``id_slot: 3`` request extension, five sequential equivalent
    requests to the SAME PID/runtime, each with reset semantics proven
    from the retained log slice, per-request rows/responses retained,
    one shared process identity bound to every request, teardown after
    the arm population. Five separate processes would NOT satisfy
    Arm B and are structurally impossible here.

    CORRECTION PASS 3 (NO-GO 5847890177, blocker 1): authority is
    revalidated LIVE immediately before EACH completion request —
    not only before the launch — through the canonical fetch path,
    and every per-request observation must cross-bind to the SAME
    original dispatch generation (same comment id/head/namespace/arm/
    author association/created-at/body digest). A drift at request N
    stops the lifecycle BEFORE request N issues: already-completed
    request evidence stays retained (append-only), the lifecycle is
    marked incomplete (fail-closed), and no later request executes.
    The ``preflight_request`` callback is the ONLY mechanism by which
    the runner may request a gate check; the runner itself never
    fetches authority and cannot bypass the gate.
    """
    repo_root = Path(repo_root).resolve(strict=True)
    D.validate_namespace_arm_binding(namespace, arm)
    if arm != "B-process-init":
        raise PhysicalDiagnosticError(
            "same-process lifecycle is an Arm-B population only")
    plan = D.probe_list_for(arm)
    same_units = [u for u in plan if u.get("same_process")
                  and u["tag"].startswith(tag_prefix)]
    if len(same_units) != D.DETERM_MIN_REPEATS:
        raise PhysicalDiagnosticError(
            f"same-process population is frozen at "
            f"{D.DETERM_MIN_REPEATS} requests, plan lists {len(same_units)}")
    canonical_generation = validate_evidence_generation(Path(evidence_root))
    _admit_retained_cost(evidence_root, "arm-b-sameproc", namespace, arm)

    # Per-request live authority revalidation (blocker 1): every
    # completion request begins under CURRENT authority, cross-bound
    # to the original dispatch generation. CORRECTION PASS 4 (NO-GO
    # 5851078451, blocker 1) mechanically separates four concepts that
    # pass 3 conflated: gate ATTEMPTS (every gate call, including the
    # one that fails), SUCCESSFUL authority observations, COMPLETED
    # requests, and the FAILED gate index. A failed gate attempt never
    # corresponds to a completed request; the accounting below must
    # hold for BOTH shapes so an authority-drift prefix is retained
    # durably instead of raising before custody is written.
    request_authorities: list[dict[str, Any]] = []
    request_gate_attempts: list[int] = []
    request_gate_failed_index: int | None = None
    generation_anchor: dict[str, Any] | None = None

    def _request_gate(index: int) -> None:
        request_gate_attempts.append(index)
        try:
            payload = require_live_dispatch(
                repo_root, expected_head, namespace,
                revalidate_authority=revalidate_authority,
                github_api=github_api)
            if payload.get("arm") != arm:
                raise PhysicalDiagnosticError(
                    f"per-request authority at request {index} binds arm "
                    f"{payload.get('arm')!r} != {arm!r}")
            D._require_clean_head(repo_root, expected_head)
            nonlocal generation_anchor, request_gate_failed_index
            if generation_anchor is None:
                generation_anchor = payload
            else:
                # cross-bind EVERY observation to the original generation
                D.bind_authority_observations(generation_anchor, payload)
            _require_sequential_reachability(
                repo_root, Path(evidence_root), arm, expected_head,
                model_attestation, revalidate_authority, github_api)
            request_authorities.append(dict(payload))
        except BaseException:
            if request_gate_failed_index is None:
                request_gate_failed_index = index
            raise

    authority_early = require_live_dispatch(
        repo_root, expected_head, namespace,
        revalidate_authority=revalidate_authority, github_api=github_api)
    if authority_early.get("arm") != arm:
        raise PhysicalDiagnosticError(
            "live dispatch arm does not match the executing arm")
    generation_anchor = dict(authority_early)
    D._require_clean_head(repo_root, expected_head)
    _require_sequential_reachability(
        repo_root, Path(evidence_root), arm, expected_head,
        model_attestation, revalidate_authority, github_api)
    # Timeout-budget authority is still derived for the same retained
    # generation, whose cost record was admitted before the first subprocess.
    fixtures = verify_fixtures(repo_root)
    lifecycle_budget = TB.request_timeout_budget(
        same_units[0],
        prompt_tokens=len(fixtures[D.CASE]["prompt_token_ids"]))
    lifecycle_budget["timeout_policy_sha256"] = TB.timeout_budget_digest(
        lifecycle_budget)
    binary_sha = verify_binary(Path(binary), binary_id)
    attestation = validate_model_attestation(model_attestation,
                                             expected_head)
    retained_opening_path = (Path(evidence_root)
                             / MODEL_ATTESTATION_OPEN_NAME)
    if (retained_opening_path.is_symlink()
            or not retained_opening_path.is_file()):
        raise PhysicalDiagnosticError(
            "campaign opening model attestation is not retained")
    retained_opening = json.loads(retained_opening_path.read_bytes())
    if attestation != retained_opening:
        raise PhysicalDiagnosticError(
            "lifecycle attestation differs from the retained campaign "
            "opening")
    witness_problems, stat_witness = attestation_witness(
        Path(model_dir), attestation)
    if witness_problems:
        raise PhysicalDiagnosticError(
            f"model stat witness drift: {witness_problems}")
    if attestation["model_dir"] != str(Path(model_dir)):
        raise PhysicalDiagnosticError(
            "attested model dir differs from the launched model dir")
    launch_member = Path(model_dir) / D.MODEL_MEMBER_1
    prompt = fixtures[D.CASE]["prompt_text"]
    expected_prompt_tokens = len(fixtures[D.CASE]["prompt_token_ids"])
    request = D.validate_request_contract(
        dict(D.ARM_B_CONTRACT), extra_keys=frozenset({"id_slot"}))

    lifecycle_dir = D.namespace_dir(evidence_root, namespace) / (
        tag_prefix + "-lifecycle")
    if lifecycle_dir.exists() or lifecycle_dir.is_symlink():
        raise D.DiagnosticError(
            f"existing lifecycle directory cannot be replaced: "
            f"{lifecycle_dir}")
    lifecycle_dir.mkdir(parents=True)

    identity_pre = (identity_observer or _observe_arm_identity)()
    problems_pre = I.identity_problems(ARM, identity_pre)
    if problems_pre:
        _write_json(lifecycle_dir / "identity-pre.json", identity_pre)
        raise PhysicalDiagnosticError(
            f"pre-launch identity drift: {problems_pre}")

    out_prefix = lifecycle_dir / "obs"
    env = launch_env(out_prefix)
    unit = same_units[0]
    argv = server_argv(Path(binary), launch_member, unit)

    # FINAL live governance gate before the single launch.
    authority_late = require_live_dispatch(
        repo_root, expected_head, namespace,
        revalidate_authority=revalidate_authority, github_api=github_api)
    final_authority = D.bind_authority_observations(
        authority_early, authority_late)
    if final_authority.get("arm") != arm:
        raise PhysicalDiagnosticError(
            "final live dispatch arm does not match the executing arm")
    _require_sequential_reachability(
        repo_root, Path(evidence_root), arm, expected_head,
        model_attestation, revalidate_authority, github_api)
    D._require_clean_head(repo_root, expected_head)
    # The shared server is one physical launch. Recheck the retained cost
    # authority after all prelaunch work, before invoking its runner.
    _admit_retained_cost(evidence_root, "arm-b-sameproc", namespace, arm)

    started_at = _utcnow()
    started = time.monotonic()
    runner = execute or _real_same_process_execute
    result = runner(argv=argv, env=env, request=request, prompt=prompt,
                    port=PORT, unit_dir=lifecycle_dir,
                    repeats=D.DETERM_MIN_REPEATS,
                    expected_prompt_tokens=expected_prompt_tokens,
                    preflight_request=_request_gate,
                    timeout_s=lifecycle_budget["budget_s"])
    wall = time.monotonic() - started
    ended_at = _utcnow()

    # ---- custody + fail-closed lifecycle verification ----
    shared_pid = result.get("server_pid")
    if type(shared_pid) is not int or shared_pid <= 0:
        raise PhysicalDiagnosticError("lifecycle carried no server PID")
    per_request = result.get("requests")
    if not isinstance(per_request, list):
        raise PhysicalDiagnosticError(
            "same-process lifecycle returned no request records")
    stop_kind = result.get("stop_kind", "completed_all")
    stop_reason = result.get("stop_reason")
    if stop_kind not in ("completed_all", "truncated", "mismatch_stop"):
        raise PhysicalDiagnosticError(
            f"lifecycle stop kind malformed: {stop_kind!r}")
    truncated = stop_kind == "truncated"
    mismatch_stop = stop_kind == "mismatch_stop"
    # CORRECTION PASS 4 (NO-GO 5851078451, blocker 1): a drift/proof
    # failure truncates the lifecycle — the COMPLETED PREFIX IS
    # RETAINED AND FINALIZED append-only (per-request unit
    # directories, receipts, shared identity/health custody, and the
    # lifecycle record), and the lifecycle is marked INCOMPLETE
    # (fail-closed; the reducer never treats an authority-truncated
    # prefix as a terminal-complete population). A MISMATCH STOP is
    # the frozen early-stop law firing: the retained prefix is a
    # COMPLETE nondeterministic population. Authority gate
    # accounting: ATTEMPTS are every gate invocation (a failed
    # attempt corresponds to NO completed request), successful
    # OBSERVATIONS correspond 1:1 with completed requests. The
    # runner's preflight hook is the only gate mechanism; the
    # recorded attempts prove no request was issued without a gate
    # call, and the failed index is the attempt that fired last.
    if request_gate_attempts:
        # monotone, no duplicates, contiguous from 0
        if (request_gate_attempts
                != list(range(len(request_gate_attempts)))):
            raise PhysicalDiagnosticError(
                f"per-request authority gate attempts are not a "
                f"contiguous request sequence (attempts: "
                f"{request_gate_attempts})")
        last_attempt = request_gate_attempts[-1]
        if len(per_request) not in (last_attempt, last_attempt + 1):
            raise PhysicalDiagnosticError(
                f"per-request authority gate accounting mismatch: "
                f"{len(per_request)} completed requests vs last gate "
                f"attempt {last_attempt} — no request may complete "
                f"without a preceding gate call, and at most the "
                f"gate-failing request may be absent")
        if len(request_authorities) != len(per_request):
            raise PhysicalDiagnosticError(
                "per-request authority observation count mismatch")
        if truncated and request_gate_failed_index is not None:
            if len(per_request) != request_gate_failed_index:
                raise PhysicalDiagnosticError(
                    f"truncated lifecycle retained {len(per_request)} "
                    f"requests but the authority gate failed at index "
                    f"{request_gate_failed_index} — the failed gate "
                    f"must correspond to the first unexecuted request")
        elif truncated and request_gate_failed_index is None:
            # truncation without a gate failure: the runner reported a
            # reset-proof/process truncation. No failed gate index is
            # recorded; the stop_reason carries the cause.
            pass
    else:
        # zero gate attempts: the runner never invoked the preflight
        # hook — no request may exist (an unfenced request path is
        # a producer defect, not a lifecycle shape).
        if per_request:
            raise PhysicalDiagnosticError(
                "same-process runner issued requests without any "
                "authority gate attempt (preflight hook bypassed)")
        if len(request_authorities) != 0:
            raise PhysicalDiagnosticError(
                "per-request authority observation count mismatch")
    request_records = []
    consumed_task_ids: set[int] = set()
    for index, record in enumerate(per_request):
        for field in ("tokens", "response_raw", "log_slice",
                      "row_files", "meta_file", "reset_proof"):
            if field not in record:
                raise PhysicalDiagnosticError(
                    f"same-process request {index} missing {field}")
        if record.get("server_pid") != shared_pid:
            raise PhysicalDiagnosticError(
                f"same-process request {index} executed on a different "
                f"PID ({record.get('server_pid')!r} != {shared_pid}); "
                "PID changes mid-arm are fatal")
        # task-bound reset proof (blocker 3): re-derive from the
        # retained log slice with the consumed-task set; the runner's
        # own proof must agree exactly.
        rederived = _parse_slot_log(
            record["log_slice"].decode("utf-8", errors="replace"),
            index, expected_prompt_tokens,
            consumed_task_ids=frozenset(consumed_task_ids))
        proof = record["reset_proof"]
        if (not isinstance(proof, dict)
                or proof.get("task_id") != rederived["task_id"]
                or not rederived["proven"]):
            raise PhysicalDiagnosticError(
                f"same-process request {index} lacks a task-bound reset "
                f"proof (slot-by-id + fresh-task launch + full prompt "
                f"recompute): {rederived['problems']}")
        task_id = _validate_reset_proof(rederived, index)
        consumed_task_ids.add(task_id)
        tokens = record["tokens"]
        if (not isinstance(tokens, list) or len(tokens) != D.DECISIONS
                or any(type(t) is not int for t in tokens)):
            raise PhysicalDiagnosticError(
                f"same-process request {index} malformed tokens")
        # request-history drift: every request's contract must be the
        # frozen Arm-B contract (no drift across the sequence)
        contract = record.get("request_contract")
        if contract != D.ARM_B_CONTRACT:
            raise PhysicalDiagnosticError(
                f"same-process request {index} contract drift")
        # per-request authority receipt binding (blocker 1): the
        # observation CURRENT at this request, with its digest.
        authority_receipt = unit_authority_block(request_authorities[index])
        if authority_receipt["dispatch_sha256"] != D.authority_digest(
                request_authorities[index]):
            raise PhysicalDiagnosticError(
                f"same-process request {index} authority receipt digest "
                "mismatch")
        record["_authority"] = authority_receipt
        record["_reset_proof_verified"] = rederived
        request_records.append(record)

    # Retain per-request custody under each planned tag.
    for record, unit_spec in zip(request_records, same_units):
        tag = unit_spec["tag"]
        unit_dir = prepare_unit_dir(evidence_root, namespace, tag)
        for name, data in record["row_files"].items():
            (unit_dir / name).write_bytes(data)
        (unit_dir / "obs.meta.json").write_bytes(record["meta_file"])
        (unit_dir / "response.json.raw").write_bytes(record["response_raw"])
        (unit_dir / "server.log").write_bytes(record["log_slice"])
        _write_json(unit_dir / "identity-pre.json", identity_pre)

    identity_post = (identity_observer or _observe_arm_identity)()
    problems_post = I.identity_problems(ARM, identity_post)
    _write_json(lifecycle_dir / "identity-pre.json", identity_pre)
    _write_json(lifecycle_dir / "identity-post.json", identity_post)
    if problems_post:
        raise PhysicalDiagnosticError(
            f"post-execution identity drift: {problems_post}")

    samples = result.get("device_samples")
    if not isinstance(samples, list):
        raise PhysicalDiagnosticError("lifecycle returned no samples")
    health_receipt = H.capture_platform_health(
        lifecycle_dir, started_at, ended_at,
        samples=samples, runner=health_runner)
    verified_health = H.verify_platform_health(
        lifecycle_dir, health_receipt,
        expected_gpu_uuid=I.REFERENCE_IDENTITY["gpu_uuid"],
        expected_bdf=I.frozen_identity(ARM)["bdf"],
        expected_arm=ARM)
    if not verified_health["valid"]:
        raise PhysicalDiagnosticError(
            f"retained platform health invalid: "
            f"{verified_health['problems']}")

    # Per-tag receipts bind the shared lifecycle identity.
    receipts = []
    for record, unit_spec in zip(request_records, same_units):
        tag = unit_spec["tag"]
        unit_dir = D.namespace_dir(evidence_root, namespace) / tag
        tokens = record["tokens"]
        rows, metadata = _collect_rows(unit_dir)
        if (len(metadata) != D.DECISIONS
                or any(not isinstance(m, dict) or m.get("pos") != i
                       for i, m in enumerate(metadata))):
            raise PhysicalDiagnosticError(
                "same-process observer meta population malformed")
        receipt = {
            "schema": UNIT_SCHEMA,
            "kind": "same-process-request",
            "namespace": namespace,
            "arm_id": arm,
            "tag": tag,
            "case_id": D.CASE,
            "arm": ARM,
            "unit": {k: (list(v) if isinstance(v, tuple) else v)
                     for k, v in unit_spec.items()},
            "ngl": unit_spec["ngl"],
            "argv_delta": list(unit_spec.get("argv_delta", ())),
            "binary_id": binary_id,
            "binary_sha256": binary_sha,
            "model_dir": str(model_dir),
            "model_attestation_sha256": attestation["attestation_sha256"],
            "model_stat_witness": stat_witness,
            "model_launch_member": str(launch_member),
            "request_contract": D.ARM_B_CONTRACT,
            "request_contract_sha256": D.canonical_request_digest(
                D.ARM_B_CONTRACT),
            "prompt_len": len(prompt),
            "prompt_token_ids": fixtures[D.CASE]["prompt_token_ids"],
            "server_argv": argv,
            "server_env": {k: env[k] for k in sorted(env)
                           if k.startswith(("LLAMA_", "VK_", "CUDA_"))},
            "process_attribution": result.get("process_attribution"),
            "platform_health": health_receipt,
            "platform_health_receipt": {
                "path": "../" + tag_prefix + "-lifecycle/"
                        "platform-health-receipt.json",
                "bytes": len((lifecycle_dir /
                              "platform-health-receipt.json").read_bytes()),
                "sha256": D.file_sha256(
                    lifecycle_dir / "platform-health-receipt.json"),
                "window": {"start": started_at, "end": ended_at},
            },
            "tokens": tokens,
            "response_raw_sha256": D.sha256_bytes(record["response_raw"]),
            "deterministic_output_sha256": D.canonical_token_digest(tokens),
            "identity_problems_pre": problems_pre,
            "identity_problems_post": problems_post,
            "subject_identity_schema": I.IDENTITY_SCHEMA,
            "authority": record["_authority"],
            # CORRECTION PASS 6: generation + timeout policy binding.
            "evidence_generation": canonical_generation,
            "timeout_policy": lifecycle_budget,
            "wall_time_s": wall,
            "same_process": {
                "lifecycle_schema": LIFECYCLE_SCHEMA,
                "shared_server_pid": shared_pid,
                "request_index": record["reset_proof"]["request_index"],
                "reset_proof": record["reset_proof"],
                "lifecycle_dir": lifecycle_dir.name,
            },
        }
        receipt["observer_rows"] = [D.row_digest(rows[str(i)])
                                    for i in range(D.DECISIONS)]
        receipt["observer_meta_sha256"] = D.file_sha256(
            unit_dir / "obs.meta.json")
        _write_json(unit_dir / "unit.json", receipt)
        receipts.append(receipt)

    lifecycle_doc = {
        "schema": LIFECYCLE_SCHEMA,
        "namespace": namespace,
        "arm_id": arm,
        "tag_prefix": tag_prefix,
        "shared_server_pid": shared_pid,
        "process_attribution": result.get("process_attribution"),
        "request_count": len(request_records),
        "planned_request_count": D.DETERM_MIN_REPEATS,
        # complete == the lifecycle answered its question: either
        # all planned requests executed (completed_all) or the frozen
        # early-stop law fired on a mechanically derived mismatch
        # (mismatch_stop). An authority/process truncation is an
        # INCOMPLETE population (blocker 1).
        "complete": stop_kind in ("completed_all", "mismatch_stop"),
        "stop_kind": stop_kind,
        "stop_reason": stop_reason,
        # CORRECTION PASS 4 (NO-GO 5851078451, blocker 1): the
        # truncated-lifecycle schema mechanically states the authority
        # accounting — attempted gate calls, successful observations,
        # and (for authority drift) the FAILED gate index, which has
        # no corresponding completed request by construction.
        "gate_attempt_count": len(request_gate_attempts),
        "successful_gate_count": len(request_authorities),
        "failed_gate_index": request_gate_failed_index if truncated
        else None,
        "reset_proofs": [r["reset_proof"] for r in request_records],
        "verified_reset_proofs": [r["_reset_proof_verified"]
                                  for r in request_records],
        "per_request_authorities": [r["_authority"]
                                    for r in request_records],
        "evidence_generation": canonical_generation,
        "timeout_policy": lifecycle_budget,
        "platform_health": health_receipt,
        "identity_problems_pre": problems_pre,
        "identity_problems_post": problems_post,
        "authority": unit_authority_block(final_authority),
        "wall_time_s": wall,
        "binary_id": binary_id,
        "binary_sha256": binary_sha,
        "model_attestation_sha256": attestation["attestation_sha256"],
        "model_stat_witness": stat_witness,
        "server_argv": argv,
        "server_env": {k: env[k] for k in sorted(env)
                       if k.startswith(("LLAMA_", "VK_", "CUDA_"))},
        "request_contract": D.ARM_B_CONTRACT,
        "request_contract_sha256": D.canonical_request_digest(
            D.ARM_B_CONTRACT),
    }
    _write_json(lifecycle_dir / "lifecycle.json", lifecycle_doc)
    return {"lifecycle": lifecycle_doc, "receipts": receipts}


def _real_same_process_execute(
        argv: list[str], env: dict[str, str], request: dict[str, Any],
        prompt: str, port: int, unit_dir: Path, repeats: int,
        expected_prompt_tokens: int,
        preflight_request: Callable[[int], None] | None = None,
        timeout_s: float | None = None,
        ) -> dict[str, Any]:
    """ONE server launch; ``repeats`` sequential requests; teardown.

    CORRECTION PASS 3 (blocker 1): before EVERY completion request the
    producer calls ``preflight_request(index)`` — the lifecycle's live
    authority revalidation seam. A gate failure raises before the HTTP
    completion is issued; the server is torn down and no later request
    executes (fail-closed mid-lifecycle stop).

    CORRECTION PASS 6 (AMENDMENT-003): every completion runs under the
    lifecycle's frozen timeout budget (``timeout_s``); production
    callers must pass it (None fails closed).
    """
    samples = [_device_sample() | {"stage": "before"}]
    full_env = {**os.environ, **env}
    log_path = unit_dir / "server.log.full"
    with log_path.open("wb") as log_file:
        proc = subprocess.Popen(
            argv, env=full_env, stdout=log_file, stderr=subprocess.STDOUT,
            start_new_session=True)
        try:
            _wait_healthy(proc, port)
            attribution = _proc_attribution(proc, argv, env)
            stop = threading.Event()
            errors: list[Exception] = []

            def sample_loop() -> None:
                while not stop.is_set():
                    try:
                        samples.append(
                            _device_sample() | {"stage": "during"})
                    except Exception as exc:  # pragma: no cover
                        errors.append(exc)
                        return
                    time.sleep(2.0)

            samples.append(_device_sample() | {"stage": "during"})
            thread = threading.Thread(target=sample_loop, daemon=True)
            thread.start()
            records = []
            consumed_task_ids: set[int] = set()
            stop_kind = "completed_all"
            stop_reason: str | None = None
            baseline_rows: list[str] | None = None
            try:
                for index in range(repeats):
                    # LIVE authority gate BEFORE the HTTP completion
                    # (blocker 1); a drift retains the completed prefix
                    # and stops here (fail-closed truncation).
                    if preflight_request is not None:
                        try:
                            preflight_request(index)
                        except Exception as exc:
                            stop_kind = "truncated"
                            stop_reason = (
                                f"authority-revalidation failure before "
                                f"request {index}: {exc}")
                            break
                    offset_before = log_path.stat().st_size
                    if timeout_s is None:
                        raise PhysicalDiagnosticError(
                            "same-process completion refuses an unbounded "
                            "request: the lifecycle timeout budget is "
                            "required (AMENDMENT-003)")
                    raw, response = _http_completion(
                        port, request, prompt, timeout_s=timeout_s)
                    time.sleep(0.2)  # let the slot log flush
                    with log_path.open("rb") as stream:
                        stream.seek(offset_before)
                        log_slice = stream.read()
                    tokens = response.get(
                        "tokens", response.get("tokens_predicted"))
                    proof = _parse_slot_log(
                        log_slice.decode("utf-8", errors="replace"),
                        index, expected_prompt_tokens,
                        consumed_task_ids=frozenset(consumed_task_ids))
                    if not proof["proven"]:
                        stop_kind = "truncated"
                        stop_reason = (
                            f"reset-proof failure at request {index}: "
                            f"{proof['problems']}")
                        break
                    consumed_task_ids.add(proof["task_id"])
                    row_files = {}
                    for d in range(D.DECISIONS):
                        name = f"obs.row{d}.f32"
                        row_files[name] = (unit_dir / name).read_bytes()
                    meta_file = (unit_dir / "obs.meta.json").read_bytes()
                    records.append({
                        "server_pid": proc.pid,
                        "tokens": tokens,
                        "response_raw": raw,
                        "log_slice": log_slice,
                        "row_files": row_files,
                        "meta_file": meta_file,
                        "reset_proof": proof,
                        "request_contract": dict(request),
                    })
                    # roll observer outputs aside so the next request's
                    # hook writes fresh files (retained per-request)
                    for d in range(D.DECISIONS):
                        src = unit_dir / f"obs.row{d}.f32"
                        dst = (unit_dir /
                               f"req{index + 1}.obs.row{d}.f32")
                        if src.exists():
                            src.replace(dst)
                    meta_src = unit_dir / "obs.meta.json"
                    meta_dst = unit_dir / f"req{index + 1}.obs.meta.json"
                    if meta_src.exists():
                        meta_src.replace(meta_dst)
                    # FROZEN EARLY-STOP LAW (correction pass 3, blocker
                    # 2): the first row-digest mismatch answers the
                    # discriminator — never burn further repeats. A
                    # mismatch stop is a VALID completion cause,
                    # distinct from truncation.
                    row_digests = [D.row_digest(row_files[
                        f"obs.row{d}.f32"]) for d in range(D.DECISIONS)]
                    if baseline_rows is None:
                        baseline_rows = row_digests
                    elif row_digests != baseline_rows:
                        stop_kind = "mismatch_stop"
                        stop_reason = (
                            f"first row-digest mismatch at request "
                            f"{index}")
                        break
            finally:
                stop.set()
                thread.join(timeout=2)
            if errors:
                raise PhysicalDiagnosticError(
                    "device sampling failed") from errors[0]
            samples.append(_device_sample() | {"stage": "after"})
            return {"server_pid": proc.pid,
                    "process_attribution": attribution,
                    "requests": records,
                    "device_samples": samples,
                    "stop_kind": stop_kind,
                    "stop_reason": stop_reason}
        finally:
            if proc.poll() is None:
                os.killpg(proc.pid, signal.SIGTERM)
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(proc.pid, signal.SIGKILL)
                    proc.wait(timeout=5)
