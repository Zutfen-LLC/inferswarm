#!/usr/bin/env python3
"""Issue #117 V5 qualification-applicability barrier (CPU-only, fail-closed).

Fail-closed mechanisms required before any correctness-bearing integrated
execution:

1. **V5 authority byte identity.** The accepted V5 execution authority files
   and the retained physical-identity evidence files on ``main`` are pinned
   by exact SHA-256. Any drift, mutation, or deletion is a hard stop: the
   qualification being inherited no longer exists in its accepted form.

2. **Producer-bound integration-delta classification.** The audit applies to
   exactly ONE FreeToken integration producer SHA
   (``FROZEN_INTEGRATION_PRODUCER``) and is derived from mechanically
   collected per-file delta evidence: the transitive import closure of the
   accepted V5 runner entrypoints (the correctness-bearing execution zone)
   is computed by AST parsing at both the accepted V5 execution authority
   producer and the integration producer; every zone file is hashed at both
   refs; the whole tree is compared for out-of-zone changes. A surface is
   provably unchanged only when every bound file is observed byte-identical.
   Any changed, missing, extra, or unknown execution-math surface — or any
   unprovable closure — yields ``R6_SUCCESSOR_REQUALIFICATION_REQUIRED`` and
   must stop the gate before correctness-bearing integrated execution.
   Control/artifact/materialization/observability changes remain admissible
   only on the closed set of surfaces whose bound files are admission /
   decision-row evidence wiring (``benchmarks/inferswarm_110b/``) or
   InferSwarm-side control plane (no FreeToken files).

3. **Accepted physical Compute Unit identities.** The exact per-CU GPU
   identities (node, index, UUID, product, compute capability, role) are
   frozen from the retained accepted evidence; the physical preflight must
   match them per Compute Unit, never per node.

Pure stdlib; never initializes a model runtime. The delta collector shells
out to ``git`` and only runs where the FreeToken repository exists; the
frozen ``producer-delta.json`` it produced is validated everywhere else.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

from issue74_methodology import sha256_file
from issue99_artifact_core import self_digest, write_canonical_json

AUDIT_SCHEMA = "inferswarm.issue117.applicability-audit/2"
PRODUCER_DELTA_SCHEMA = "inferswarm.issue117.producer-delta/1"
COLLECTOR_ID = "issue117.producer-delta-collector/1"

CONTROL_ONLY = "CONTROL_ONLY"
ARTIFACT_ACQUISITION_ONLY = "ARTIFACT_ACQUISITION_ONLY"
PRE_MODEL_MATERIALIZATION_ONLY = "PRE_MODEL_MATERIALIZATION_ONLY"
OBSERVABILITY_ONLY = "OBSERVABILITY_ONLY"
EXECUTION_MATH_AFFECTING = "EXECUTION_MATH_AFFECTING"
UNKNOWN = "UNKNOWN"

CLASSIFICATIONS = (
    CONTROL_ONLY,
    ARTIFACT_ACQUISITION_ONLY,
    PRE_MODEL_MATERIALIZATION_ONLY,
    OBSERVABILITY_ONLY,
    EXECUTION_MATH_AFFECTING,
    UNKNOWN,
)

R6_SUCCESSOR_REQUALIFICATION_REQUIRED = "R6_SUCCESSOR_REQUALIFICATION_REQUIRED"
DELTA_CONTROL_ARTIFACT_MATERIALIZATION_ONLY = "DELTA_CONTROL_ARTIFACT_MATERIALIZATION_ONLY"

DELTA_IDENTICAL = "IDENTICAL"
DELTA_CHANGED = "CHANGED"
DELTA_MISSING = "MISSING"
DELTA_EXTRA = "EXTRA"

#: Accepted starting state of the correctness campaign (issue #117 canon).
ACCEPTED_INFERSWARM_BASE = "d37bd301a5ea361644160f92427aa75bff658b61"
ACCEPTED_FREETOKEN_RESEARCH_HEAD = "b05564a7f3f7ca1b141d54842357ff2624dc6a19"
ACCEPTED_FREETOKEN_CALIBRATION_PRODUCER = "7e5c852163afd9aadfccc406be267e8d060e79ef"
ACCEPTED_FREETOKEN_HOLDOUT_PRODUCER = "924cd22ea081f6d4ed471016faf01d427fc5b0d2"
ACCEPTED_V5_METHODOLOGY = "bc6f0ec657d025702d5928771bf8f51aa563a8be"
ACCEPTED_TERMINAL_ADJUDICATION_SHA256 = (
    "f024f8b3394686ff098459b657ce6dba62d7f190972663e3929ef4a574ab7a70")

#: The accepted V5 execution authority producer: the accepted producer state
#: of the correctness-bearing V5 execution math (calibration producer; the
#: holdout producer adds admission wrappers only, on top of it).
ACCEPTED_FREETOKEN_EXECUTION_AUTHORITY = ACCEPTED_FREETOKEN_CALIBRATION_PRODUCER

#: The ONE FreeToken producer SHA this freeze's applicability audit applies
#: to. No #117 integration producer has been cut yet; the frozen audit
#: therefore binds the terminal accepted producer state (the holdout
#: producer). Against the execution authority its only observed zone delta
#: is the holdout admission wrappers — the accepted, zero-execution-math
#: change. Any different producer SHA — including any future #117
#: integration producer — requires mechanically re-collecting the
#: producer-delta evidence and re-earning this audit for that exact SHA.
FROZEN_INTEGRATION_PRODUCER = ACCEPTED_FREETOKEN_HOLDOUT_PRODUCER

#: Accepted V5 authority files with their byte-exact SHA-256 on accepted
#: ``main`` ``d37bd30``. These are immutable comparison authority.
V5_AUTHORITY_FILES: dict[str, str] = {
    "docs/qualification/gemma4-12b-it-v5/METHODOLOGY.md":
        "d058c2da578c33504816d24d43aa57b3b5c43176dfb57f6819578edf3be46c71",
    "docs/qualification/gemma4-12b-it-v5/TOOLING.md":
        "9dd0b2ce2e4df553561cd39de0950744bd5fd4d59824d99568a3569dd03b960a",
    "docs/qualification/gemma4-12b-it-v5/manifests/physical-subject.json":
        "8b840eed2b858623be6abd1bfbac1bc7f3bf3637ac7acfa383ce039137226aee",
    "docs/qualification/gemma4-12b-it-v5/manifests/statistical-derivation.json":
        "97fcb4c968e76d067f156d52c97124f1b52ae209ebc92d7f975c46df3e0720b5",
    "docs/qualification/gemma4-12b-it-v5/manifests/comparator-tier-contract.json":
        "ebba447573ea7af9faeab91e1036a780db453661fbc5eb067f6acfd78a1df5af",
    "docs/qualification/gemma4-12b-it-v5/manifests/mixture-population.json":
        "c272c08e475ce576fe3f314ef091f81f05fd2839753cfaa0b95923307a66ee25",
    "docs/qualification/gemma4-12b-it-v5/manifests/calibration-corpus.json":
        "b35f1915231d455cd964e9b645e58269ec63cdf483742907af39cc850f9fdb35",
    "docs/qualification/gemma4-12b-it-v5/manifests/sealed-holdout-commitment.json":
        "b0dcff2a241b20cbd24f1b54f30e77a33512d8ceb12f79afc6c1761b2c994fd2",
    "docs/qualification/gemma4-12b-it-v5-campaign-110/b/TERMINAL-REPORT.md":
        "d7f5e4954bded41e03208018c4887abb40c301f78d115e233104f265ac9882c6",
    "docs/qualification/gemma4-12b-it-v5-campaign-110/b/holdout-adjudication.json":
        "f024f8b3394686ff098459b657ce6dba62d7f190972663e3929ef4a574ab7a70",
    "docs/qualification/gemma4-12b-it-v5-campaign-110/b/holdout-rows.json":
        "de553f6c1b06e39ea69f2a526fc4b36dac76eb239ce1a09de776d0df1dfd4eb6",
    "docs/qualification/gemma4-12b-it-v5-campaign-110/b/h109-unseal-record.json":
        "0150a363be3d8898c6b69b82e5f8c4455591bf8a7095f31ae36c3ad082791145",
    "docs/qualification/gemma4-12b-it-v5-campaign-110/preflight/HOLDOUT-EXECUTION-AUTHORITY.json":
        "6f6c583f656ee28fde6d1094c47033374657929ae7d623615bd7e81753f8b492",
}

#: Retained accepted evidence files that record the physical Compute Unit
#: identities (per-GPU UUID/product/compute capability/role). The physical
#: preflight's expected identities are frozen from exactly these records.
ACCEPTED_PHYSICAL_IDENTITY_FILES: dict[str, str] = {
    "docs/qualification/gemma4-12b-it-v2-campaign-81/preflight-applicability.json":
        "f2c3590da2a16a11889bbb164df73c9aee334453b6bccf0ead27a9c3265b9313",
    "docs/qualification/gemma4-12b-it-v4-campaign-97/EXECUTION-AUTHORITY.json":
        "bb6a084fb448f8804c268273d222ece7ed50a2d4da03413edfab4ae9e136b585",
    "docs/benchmarks/results/phase0/p0c-hardware-profile.json":
        "806421cf5753cad7e2b52748ecb0bed54e8803eba20191a4829d141b7aea33fd",
}

#: Exact per-Compute-Unit identities retained by the accepted evidence above
#: (values cross-checked against the pinned files by tests). One record per
#: Compute Unit — never one per node. ``compute_capability`` is the measured
#: value recorded by the accepted evidence (8.6 for both the RTX 3060 and
#: RTX 3090 devices; anything else — e.g. a guessed "8.9" — must fail).
ACCEPTED_COMPUTE_UNITS: tuple[dict[str, Any], ...] = (
    {"cu_id": "inferswarm01/gpu-0", "node": "inferswarm01", "gpu_index": 0,
     "gpu_uuid": "GPU-1fc28f83-1d45-926e-54d0-ba1e835ef099",
     "product": "NVIDIA GeForce RTX 3060", "compute_capability": "8.6",
     "v5_role": "stage1", "layers": "[0,16)",
     "evidence_ref": "docs/qualification/gemma4-12b-it-v4-campaign-97/EXECUTION-AUTHORITY.json"},
    {"cu_id": "inferswarm01/gpu-1", "node": "inferswarm01", "gpu_index": 1,
     "gpu_uuid": "GPU-d5c05739-96c1-7e49-89b6-bf54c2121c55",
     "product": "NVIDIA GeForce RTX 3060", "compute_capability": "8.6",
     "v5_role": "stage2", "layers": "[16,32)",
     "evidence_ref": "docs/qualification/gemma4-12b-it-v4-campaign-97/EXECUTION-AUTHORITY.json"},
    {"cu_id": "inferswarm03/gpu-0", "node": "inferswarm03", "gpu_index": 0,
     "gpu_uuid": "GPU-e1f2f90c-49ab-2689-0cf1-e5d9da520176",
     "product": "NVIDIA GeForce RTX 3060", "compute_capability": "8.6",
     "v5_role": "stage3", "layers": "[32,48)",
     "evidence_ref": "docs/qualification/gemma4-12b-it-v4-campaign-97/EXECUTION-AUTHORITY.json"},
    {"cu_id": "inferswarm04/gpu-0", "node": "inferswarm04", "gpu_index": 0,
     "gpu_uuid": "GPU-ecda1aaa-0c66-857b-8218-3d511dc75c03",
     "product": "NVIDIA GeForce RTX 3090", "compute_capability": "8.6",
     "v5_role": "reference", "layers": None,
     "evidence_ref": "docs/qualification/gemma4-12b-it-v4-campaign-97/EXECUTION-AUTHORITY.json"},
)

#: The accepted V5 runner entrypoints whose import closure defines the
#: correctness-bearing execution zone of the FreeToken producer.
V5_EXECUTION_ENTRYPOINTS: tuple[str, ...] = (
    "benchmarks/inferswarm_110/__init__.py",
    "benchmarks/inferswarm_110/chain_runner.py",
    "benchmarks/inferswarm_110/last_stage_service.py",
    "benchmarks/inferswarm_110/reference_runner.py",
    "benchmarks/inferswarm_110b/__init__.py",
    "benchmarks/inferswarm_110b/chain_runner_holdout.py",
    "benchmarks/inferswarm_110b/reference_runner_holdout.py",
)

#: Closed execution-relevant surface list from the issue #117 applicability
#: barrier. Every surface is classified exactly once, from observed deltas.
AUDITED_SURFACES = (
    "dense_stage_model_math",
    "attention_implementation",
    "precision",
    "layer_partitioning",
    "tensor_interpretation_layout",
    "boundary_serialization_deserialization",
    "prefill",
    "replay_decode",
    "canonical_prefix_logic",
    "decision_row_construction",
    "fp32_consumer_logit_capture",
    "argmax_tie_semantics",
    "finite_output_checks",
    "session_state_output_semantics",
    "graph_capture_replay_behavior",
    "backend_initialization",
    "checkpoint_interpretation",
)

#: Frozen seam classification per surface (the category the #117 integration
#: claims for it). This column alone proves nothing; the mechanical verdict
#: comes from the observed producer delta and the admissible-change rule.
SURFACE_CLASSIFICATIONS: dict[str, str] = {
    "dense_stage_model_math": CONTROL_ONLY,
    "attention_implementation": CONTROL_ONLY,
    "precision": CONTROL_ONLY,
    "layer_partitioning": CONTROL_ONLY,
    "tensor_interpretation_layout": PRE_MODEL_MATERIALIZATION_ONLY,
    "boundary_serialization_deserialization": PRE_MODEL_MATERIALIZATION_ONLY,
    "prefill": CONTROL_ONLY,
    "replay_decode": CONTROL_ONLY,
    "canonical_prefix_logic": CONTROL_ONLY,
    "decision_row_construction": OBSERVABILITY_ONLY,
    "fp32_consumer_logit_capture": OBSERVABILITY_ONLY,
    "argmax_tie_semantics": CONTROL_ONLY,
    "finite_output_checks": CONTROL_ONLY,
    "session_state_output_semantics": CONTROL_ONLY,
    "graph_capture_replay_behavior": CONTROL_ONLY,
    "backend_initialization": CONTROL_ONLY,
    "checkpoint_interpretation": ARTIFACT_ACQUISITION_ONLY,
}

#: The ONLY surfaces on which observed FreeToken-side changes are admissible.
#: ``decision_row_construction`` binds exactly the holdout admission wrappers
#: (accepted authority: "admission wiring ONLY, zero execution/model math");
#: ``session_state_output_semantics`` binds no FreeToken files at all (the
#: fencing is InferSwarm control-plane, bounded by the InferSwarm producer
#: hashes). Every other surface binds execution-bearing files: any observed
#: change there is changed or unknown execution math -> requalification.
ADMISSIBLE_CHANGE_SURFACES = ("decision_row_construction",
                              "session_state_output_semantics")

#: Surface -> correctness-bearing FreeToken path bindings (repo-relative
#: prefixes). Bindings may overlap: one file can be evidence for several
#: surfaces. A zone file matching no surface binding is UNKNOWN and fails
#: the gate.
SURFACE_BINDINGS: dict[str, tuple[str, ...]] = {
    "dense_stage_model_math": (
        "benchmarks/inferswarm_76/",
        "benchmarks/inferswarm_97/",
        "benchmarks/inferswarm_97b/",
        "benchmarks/inferswarm_r6/",
        "benchmarks/inferswarm_110/",
        "python/freetoken/models/",
        "python/freetoken/layers/",
        "python/freetoken/kernel/",
        "python/freetoken/moe/",
        "python/freetoken/research/",
        "python/freetoken/engine/",
        "python/freetoken/scheduler/",
        "python/freetoken/message/",
    ),
    "attention_implementation": (
        "python/freetoken/attention/",
        "python/freetoken/models/gemma4/attention.py",
        "python/freetoken/kernel/triton/gemma4_fused.py",
    ),
    "precision": (
        "python/freetoken/models/config.py",
        "python/freetoken/models/gemma4/config.py",
        "python/freetoken/models/nvfp4_banks.py",
        "python/freetoken/models/gguf/dequant.py",
        "python/freetoken/kernel/gguf.py",
        "python/freetoken/kernel/triton/nvfp4_linear.py",
        "python/freetoken/kernel/triton/nvfp4_dequant.py",
        "python/freetoken/kernel/triton/e4m3_compat.py",
        "python/freetoken/engine/config.py",
    ),
    "layer_partitioning": (
        "benchmarks/inferswarm_76/stage_entry.py",
        "benchmarks/inferswarm_110/chain_runner.py",
        "benchmarks/inferswarm_r6/stage_runtime.py",
    ),
    "tensor_interpretation_layout": (
        "python/freetoken/models/gemma4/weight.py",
        "python/freetoken/models/gemma4/gguf.py",
        "python/freetoken/models/weight.py",
        "python/freetoken/models/gguf/",
        "python/freetoken/layers/gguf.py",
    ),
    "boundary_serialization_deserialization": (
        "python/freetoken/distributed/",
        "python/freetoken/message/",
        "python/freetoken/research/r4_wire.py",
        "benchmarks/inferswarm_76/wire_client.py",
    ),
    "prefill": (
        "benchmarks/inferswarm_76/stage_entry.py",
        "benchmarks/inferswarm_110/chain_runner.py",
        "benchmarks/inferswarm_110/last_stage_service.py",
        "python/freetoken/engine/engine.py",
        "python/freetoken/scheduler/prefill.py",
        "python/freetoken/scheduler/utils.py",
    ),
    "replay_decode": (
        "benchmarks/inferswarm_76/stage_entry.py",
        "benchmarks/inferswarm_76/reference_runner.py",
        "benchmarks/inferswarm_110/chain_runner.py",
        "benchmarks/inferswarm_110/last_stage_service.py",
        "benchmarks/inferswarm_110/reference_runner.py",
        "python/freetoken/engine/engine.py",
        "python/freetoken/scheduler/decode.py",
        "python/freetoken/scheduler/utils.py",
    ),
    "canonical_prefix_logic": (
        "python/freetoken/kvcache/",
        "python/freetoken/engine/engine.py",
        "python/freetoken/engine/cache_budget.py",
        "python/freetoken/scheduler/cache.py",
        "python/freetoken/scheduler/table.py",
        "benchmarks/inferswarm_76/reference_runner.py",
        "benchmarks/inferswarm_110/chain_runner.py",
        "benchmarks/inferswarm_110/reference_runner.py",
    ),
    "decision_row_construction": (
        "benchmarks/inferswarm_110b/",
    ),
    "fp32_consumer_logit_capture": (
        "benchmarks/inferswarm_76/capture.py",
        "benchmarks/inferswarm_110/last_stage_service.py",
    ),
    "argmax_tie_semantics": (
        "benchmarks/inferswarm_76/reference_runner.py",
        "benchmarks/inferswarm_110/chain_runner.py",
        "benchmarks/inferswarm_110/reference_runner.py",
        "python/freetoken/engine/sample.py",
    ),
    "finite_output_checks": (
        "benchmarks/inferswarm_76/reference_runner.py",
        "benchmarks/inferswarm_110/chain_runner.py",
        "benchmarks/inferswarm_110/reference_runner.py",
        "python/freetoken/engine/correctness_diagnostics.py",
    ),
    "session_state_output_semantics": (),
    "graph_capture_replay_behavior": (
        "python/freetoken/kernel/backend.py",
        "python/freetoken/kernel/aot_models.py",
        "python/freetoken/engine/graph.py",
    ),
    "backend_initialization": (
        "python/freetoken/env.py",
        "python/freetoken/gpu_select.py",
        "python/freetoken/core.py",
        "python/freetoken/version.py",
        "python/freetoken/kernel/_toolchain.py",
        "python/freetoken/utils/",
    ),
    "checkpoint_interpretation": (
        "python/freetoken/checkpoint/",
        "python/freetoken/models/loader.py",
        "python/freetoken/models/register.py",
        "python/freetoken/utils/hf.py",
        "python/freetoken/message/tokenizer.py",
    ),
}

PRODUCER_DELTA_RELATIVE_PATH = (
    "docs/implementation/r6-successor-dense-full-integration-117"
    "/evidence/producer-delta.json")


class ApplicabilityBlocked(RuntimeError):
    """A fail-closed applicability condition fired; stop before execution."""


# ---------------------------------------------------------------------------
# Mechanical producer-delta collector (requires the FreeToken repository)
# ---------------------------------------------------------------------------


def _git(root: Path, *args: str) -> bytes:
    result = subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True)
    if result.returncode != 0:
        raise ApplicabilityBlocked(
            f"git {' '.join(args[:2])} failed at {root}: "
            f"{result.stderr.decode(errors='replace').strip()[:200]}")
    return result.stdout


def _git_blob(root: Path, ref: str, path: str) -> bytes | None:
    result = subprocess.run(
        ["git", "-C", str(root), "show", f"{ref}:{path}"], capture_output=True)
    if result.returncode != 0:
        return None
    return result.stdout


def _resolve_import(root: Path, ref: str, module: str) -> str | None:
    base = module.replace(".", "/")
    for candidate in (f"python/{base}.py", f"python/{base}/__init__.py",
                      f"{base}.py", f"{base}/__init__.py"):
        if _git_blob(root, ref, candidate) is not None:
            return candidate
    return None


def _imports_of(source: bytes, path: str) -> set[str]:
    """In-repository modules referenced by one file's import statements."""
    tree = ast.parse(source)
    modules: set[str] = set()
    package: str | None = None
    if "/" in path:
        package = path.rsplit("/", 1)[0].replace("/", ".")

    def add(module: str) -> None:
        if module:
            modules.add(module)

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            prefix = ""
            if node.level:
                if package is None:
                    continue
                parts = package.split(".")
                base_parts = (parts[:len(parts) - (node.level - 1)]
                              if node.level > 1 else parts)
                prefix = ".".join(base_parts)
            name = node.module or ""
            add(f"{prefix}.{name}" if prefix and name else (prefix or name))
            # `from pkg import submodule` also imports (and executes) the
            # submodule; record every alias as a potential module path.
            if name or prefix:
                base = f"{prefix}.{name}" if prefix and name else (prefix or name)
                for alias in node.names:
                    if alias.name != "*":
                        add(f"{base}.{alias.name}")
    return modules


def _import_closure(root: Path, ref: str,
                    entrypoints: Sequence[str]) -> dict[str, Any]:
    """Transitive in-repository import closure of the V5 entrypoints at ref."""
    zone: set[str] = set()
    queue: list[str] = list(entrypoints)
    unresolved: set[str] = set()
    dynamic_import_files: set[str] = set()
    syntax_errors: list[str] = []
    while queue:
        path = queue.pop()
        if path in zone:
            continue
        zone.add(path)
        blob = _git_blob(root, ref, path)
        if blob is None:
            continue
        if b"importlib" in blob or b"__import__" in blob:
            dynamic_import_files.add(path)
        try:
            modules = sorted(_imports_of(blob, path))
        except SyntaxError as error:
            syntax_errors.append(f"{path}: {error}")
            continue
        for module in modules:
            resolved = _resolve_import(root, ref, module)
            if resolved is None:
                if module.startswith(("freetoken", "benchmarks")):
                    unresolved.add(module)
                continue
            if resolved not in zone:
                queue.append(resolved)
    return {
        "zone_files": sorted(zone),
        "dynamic_import_files": sorted(dynamic_import_files),
        "unresolved_in_repository_imports": sorted(unresolved),
        "syntax_errors": sorted(syntax_errors),
    }


def _bound_surfaces(path: str) -> list[str]:
    return [surface for surface in AUDITED_SURFACES
            if any(path.startswith(prefix)
                   for prefix in SURFACE_BINDINGS[surface])]


def _tree_blob_ids(root: Path, ref: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in _git(root, "ls-tree", "-r", ref).decode().splitlines():
        meta, _, path = line.partition("\t")
        fields = meta.split()
        if len(fields) >= 3:
            out[path] = fields[2]
    return out


def collect_producer_delta(freetoken_root: Path, *, integration_producer: str,
                           execution_authority: str =
                           ACCEPTED_FREETOKEN_EXECUTION_AUTHORITY,
                           entrypoints: Sequence[str] =
                           V5_EXECUTION_ENTRYPOINTS) -> dict[str, Any]:
    """Mechanically collect per-file delta evidence between two producers.

    Computes the correctness-bearing import closure at BOTH refs, hashes
    every zone file at both refs, derives per-file deltas, and lists all
    out-of-zone tree changes. Pure observation; no verdict is taken here.
    """
    freetoken_root = Path(freetoken_root)
    authority_closure = _import_closure(freetoken_root, execution_authority,
                                        entrypoints)
    integration_closure = _import_closure(freetoken_root, integration_producer,
                                          entrypoints)
    files = sorted(set(authority_closure["zone_files"])
                   | set(integration_closure["zone_files"]))
    zone_entries = []
    for path in files:
        authority_blob = _git_blob(freetoken_root, execution_authority, path)
        integration_blob = _git_blob(freetoken_root, integration_producer, path)
        authority_digest = ("sha256:" + hashlib.sha256(authority_blob).hexdigest()
                            if authority_blob is not None else None)
        integration_digest = ("sha256:" + hashlib.sha256(integration_blob).hexdigest()
                              if integration_blob is not None else None)
        if authority_digest is None:
            delta = DELTA_EXTRA
        elif integration_digest is None:
            delta = DELTA_MISSING
        elif authority_digest != integration_digest:
            delta = DELTA_CHANGED
        else:
            delta = DELTA_IDENTICAL
        zone_entries.append({
            "path": path,
            "authority_sha256": authority_digest,
            "integration_sha256": integration_digest,
            "delta": delta,
            "surfaces": _bound_surfaces(path),
        })
    unbound = [entry["path"] for entry in zone_entries if not entry["surfaces"]]
    authority_tree = _tree_blob_ids(freetoken_root, execution_authority)
    integration_tree = _tree_blob_ids(freetoken_root, integration_producer)
    zone_set = set(files)
    out_of_zone = {
        "changed": sorted(path for path in authority_tree
                          if path in integration_tree
                          and path not in zone_set
                          and authority_tree[path] != integration_tree[path]),
        "added": sorted(path for path in integration_tree
                        if path not in authority_tree and path not in zone_set),
        "removed": sorted(path for path in authority_tree
                          if path not in integration_tree and path not in zone_set),
    }
    document = {
        "schema": PRODUCER_DELTA_SCHEMA,
        "collector": COLLECTOR_ID,
        "freetoken_entrypoints": list(entrypoints),
        "integration_producer": integration_producer,
        "execution_authority": execution_authority,
        "authority_closure": authority_closure,
        "integration_closure": integration_closure,
        "zone_files": zone_entries,
        "unbound_zone_files": unbound,
        "out_of_zone_changes": out_of_zone,
    }
    document["producer_delta_digest"] = self_digest(
        document, identity_field="producer_delta_digest")
    return document


def load_producer_delta(root: Path | None = None) -> dict[str, Any]:
    """Load and self-validate the frozen producer-delta evidence document."""
    root = root or Path(__file__).resolve().parents[1]
    path = root / PRODUCER_DELTA_RELATIVE_PATH
    if not path.is_file():
        raise ApplicabilityBlocked(
            "frozen producer-delta evidence missing: "
            f"{PRODUCER_DELTA_RELATIVE_PATH}")
    document = json.loads(path.read_text())
    validate_producer_delta(document)
    return document


def validate_producer_delta(document: Mapping[str, Any]) -> None:
    """Fail closed unless the delta document is self-consistent and bound to
    the frozen integration producer with a provable zone."""
    if document.get("schema") != PRODUCER_DELTA_SCHEMA:
        raise ApplicabilityBlocked(
            f"unexpected producer-delta schema {document.get('schema')!r}")
    if document.get("producer_delta_digest") != self_digest(
            dict(document), identity_field="producer_delta_digest"):
        raise ApplicabilityBlocked("producer_delta_digest self-identity mismatch")
    if document.get("integration_producer") != FROZEN_INTEGRATION_PRODUCER:
        raise ApplicabilityBlocked(
            "producer-delta evidence is bound to producer "
            f"{document.get('integration_producer')!r}, not the frozen "
            f"integration producer {FROZEN_INTEGRATION_PRODUCER!r}")
    if document.get("execution_authority") != ACCEPTED_FREETOKEN_EXECUTION_AUTHORITY:
        raise ApplicabilityBlocked("producer-delta execution authority mismatch")
    for closure_name in ("authority_closure", "integration_closure"):
        closure = document.get(closure_name, {})
        if closure.get("syntax_errors"):
            raise ApplicabilityBlocked(
                f"{closure_name} unparsable: {closure['syntax_errors'][:3]}")
    if (document.get("authority_closure", {}).get("dynamic_import_files")
            != document.get("integration_closure", {}).get("dynamic_import_files")):
        raise ApplicabilityBlocked(
            "dynamic-import usage differs between the execution authority and "
            "the integration producer; the execution zone is not provable")
    if document.get("unbound_zone_files"):
        raise ApplicabilityBlocked(
            "zone files match no surface binding (UNKNOWN): "
            f"{document['unbound_zone_files']}")
    for entry in document.get("zone_files", []):
        if sorted(entry.get("surfaces", [])) != sorted(_bound_surfaces(entry["path"])):
            raise ApplicabilityBlocked(
                f"zone file surface binding drifted: {entry['path']}")


# ---------------------------------------------------------------------------
# Audit document: classification derived from observed producer delta
# ---------------------------------------------------------------------------


def _delta_summary(entries: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    summary = {delta: 0 for delta in
               (DELTA_IDENTICAL, DELTA_CHANGED, DELTA_MISSING, DELTA_EXTRA)}
    for entry in entries:
        summary[entry["delta"]] += 1
    return summary


def _observed_delta(summary: Mapping[str, int]) -> str:
    if (summary[DELTA_CHANGED] == 0 and summary[DELTA_MISSING] == 0
            and summary[DELTA_EXTRA] == 0):
        return DELTA_IDENTICAL
    return "OBSERVED_CHANGES"


def build_audit_document(delta: Mapping[str, Any], *,
                         authority: Mapping[str, Any]) -> dict[str, Any]:
    """Freeze one evidence-backed classification per audited surface.

    Every surface's observed delta and bound-file counts are derived from
    the mechanically collected producer-delta evidence; the verdict is then
    derived by :func:`evaluate_audit`.
    """
    validate_producer_delta(delta)
    zone_files = delta["zone_files"]
    entries = []
    for surface in AUDITED_SURFACES:
        bound = [entry for entry in zone_files if surface in entry["surfaces"]]
        summary = _delta_summary(bound)
        if surface == "session_state_output_semantics":
            binding = "INFERSWARM_CONTROL_PLANE"
        else:
            binding = "FREETOKEN_EXECUTION_ZONE"
        entries.append({
            "surface": surface,
            "classification": SURFACE_CLASSIFICATIONS[surface],
            "binding": binding,
            "bound_file_count": len(bound),
            "observed_delta": _observed_delta(summary),
            "delta_summary": summary,
            "evidence_ref": PRODUCER_DELTA_RELATIVE_PATH,
        })
    document = {
        "schema": AUDIT_SCHEMA,
        "authority": dict(authority),
        "producer_delta": {
            "producer_delta_digest": delta["producer_delta_digest"],
            "integration_producer": delta["integration_producer"],
            "execution_authority": delta["execution_authority"],
            "zone_file_count": len(zone_files),
            "zone_delta_summary": _delta_summary(zone_files),
            "out_of_zone_change_count": sum(
                len(paths) for paths in delta["out_of_zone_changes"].values()),
        },
        "entries": entries,
    }
    verdict = evaluate_audit(document)
    document["overall_result"] = verdict
    document["audit_digest"] = self_digest(document, identity_field="audit_digest")
    return document


def evaluate_audit(document: Mapping[str, Any]) -> str:
    """Mechanically derive the terminal applicability verdict; fail closed.

    The rule is the issue barrier: control/artifact/materialization/
    observability changes are admissible; changed, missing, extra, or
    unknown execution-math surfaces are not.
    """
    if document.get("schema") != AUDIT_SCHEMA:
        raise ApplicabilityBlocked(
            f"unexpected audit schema {document.get('schema')!r}")
    authority = document.get("authority", {})
    if authority.get("integration_producer") != FROZEN_INTEGRATION_PRODUCER:
        raise ApplicabilityBlocked(
            "audit authority is not bound to the frozen integration producer "
            f"{FROZEN_INTEGRATION_PRODUCER!r}")
    if authority.get("execution_authority") != ACCEPTED_FREETOKEN_EXECUTION_AUTHORITY:
        raise ApplicabilityBlocked("audit execution authority mismatch")
    delta_record = document.get("producer_delta", {})
    if delta_record.get("integration_producer") != FROZEN_INTEGRATION_PRODUCER:
        raise ApplicabilityBlocked(
            "producer-delta binding is not the frozen integration producer")
    if delta_record.get("execution_authority") != ACCEPTED_FREETOKEN_EXECUTION_AUTHORITY:
        raise ApplicabilityBlocked("producer-delta execution authority mismatch")
    entries = document.get("entries", [])
    surfaces = [entry["surface"] for entry in entries]
    missing = sorted(set(AUDITED_SURFACES) - set(surfaces))
    extra = sorted(set(surfaces) - set(AUDITED_SURFACES))
    duplicated = sorted({s for s in surfaces if surfaces.count(s) > 1})
    if missing or extra or duplicated:
        raise ApplicabilityBlocked(
            f"audit surface mismatch (missing={missing}, extra={extra}, "
            f"duplicated={duplicated})")
    zone_count = delta_record.get("zone_file_count", 0)
    zone_summary = delta_record.get("zone_delta_summary", {})
    if sum(zone_summary.values()) != zone_count:
        raise ApplicabilityBlocked("zone delta accounting is inconsistent")
    for entry in entries:
        if entry["classification"] not in CLASSIFICATIONS:
            raise ApplicabilityBlocked(
                f"{entry['surface']}: unknown classification "
                f"{entry['classification']!r}")
        summary = entry.get("delta_summary", {})
        if sum(summary.values()) != entry.get("bound_file_count"):
            raise ApplicabilityBlocked(
                f"{entry['surface']}: delta summary does not match the bound "
                "file count")
        if entry.get("observed_delta") != _observed_delta(summary):
            raise ApplicabilityBlocked(
                f"{entry['surface']}: observed_delta is not derived from the "
                "recorded delta summary")
        changed = (summary.get(DELTA_CHANGED, 0) + summary.get(DELTA_MISSING, 0)
                   + summary.get(DELTA_EXTRA, 0))
        if changed and entry["surface"] not in ADMISSIBLE_CHANGE_SURFACES:
            raise ApplicabilityBlocked(
                f"{R6_SUCCESSOR_REQUALIFICATION_REQUIRED}: execution-bearing "
                f"surface {entry['surface']} has {changed} changed/missing/"
                "extra zone file(s); the V5 execution math is changed or unknown")
        if changed and entry["classification"] not in (
                CONTROL_ONLY, ARTIFACT_ACQUISITION_ONLY,
                PRE_MODEL_MATERIALIZATION_ONLY, OBSERVABILITY_ONLY):
            raise ApplicabilityBlocked(
                f"{entry['surface']}: a changed surface cannot claim "
                f"{entry['classification']!r}")
    return DELTA_CONTROL_ARTIFACT_MATERIALIZATION_ONLY


def validate_audit_document(document: Mapping[str, Any]) -> str:
    """Validate self-identity and re-derive the verdict of a frozen audit."""
    if document.get("schema") != AUDIT_SCHEMA:
        raise ApplicabilityBlocked(
            f"unexpected audit schema {document.get('schema')!r}")
    if document.get("overall_result") != evaluate_audit(document):
        raise ApplicabilityBlocked(
            "overall_result does not match the mechanical verdict")
    if document.get("audit_digest") != self_digest(
            dict(document), identity_field="audit_digest"):
        raise ApplicabilityBlocked("audit_digest self-identity mismatch")
    frozen = canonical_issue117_audit()
    if document["audit_digest"] != frozen["audit_digest"]:
        raise ApplicabilityBlocked(
            "audit is not the frozen #117 producer-bound applicability audit")
    return document["overall_result"]


def canonical_issue117_audit(root: Path | None = None) -> dict[str, Any]:
    """The frozen, producer-bound #117 integration-delta audit.

    Built from the mechanically collected producer-delta evidence at
    ``evidence/producer-delta.json`` (committed input). The audit applies to
    exactly ``FROZEN_INTEGRATION_PRODUCER``; the observed zone deltas prove
    the V5 execution math unchanged for that producer.
    """
    delta = load_producer_delta(root)
    authority = {
        "accepted_inferswarm_base": ACCEPTED_INFERSWARM_BASE,
        "accepted_freetoken_research_head": ACCEPTED_FREETOKEN_RESEARCH_HEAD,
        "accepted_freetoken_calibration_producer": ACCEPTED_FREETOKEN_CALIBRATION_PRODUCER,
        "accepted_freetoken_holdout_producer": ACCEPTED_FREETOKEN_HOLDOUT_PRODUCER,
        "accepted_freetoken_execution_authority": ACCEPTED_FREETOKEN_EXECUTION_AUTHORITY,
        "accepted_v5_methodology": ACCEPTED_V5_METHODOLOGY,
        "terminal_adjudication_sha256": ACCEPTED_TERMINAL_ADJUDICATION_SHA256,
        "integration_producer": FROZEN_INTEGRATION_PRODUCER,
        "execution_authority": ACCEPTED_FREETOKEN_EXECUTION_AUTHORITY,
        "claim": "control plane + artifact acquisition + selective materialization "
                 "change; V5 execution math reused unchanged",
    }
    return build_audit_document(delta, authority=authority)


def _verify_pinned_files(root: Path, pinned: Mapping[str, str],
                         description: str) -> dict[str, str]:
    """Verify every pinned file is byte-identical; fail closed on drift."""
    results = {}
    for relative, expected in sorted(pinned.items()):
        path = root / relative
        if not path.is_file():
            raise ApplicabilityBlocked(f"accepted {description} missing: {relative}")
        observed = sha256_file(path)
        if observed != expected:
            raise ApplicabilityBlocked(
                f"accepted {description} drifted: {relative} "
                f"expected {expected} observed {observed}")
        results[relative] = observed
    return results


def verify_v5_authority(root: Path, *, files: Mapping[str, str] | None = None) -> dict[str, Any]:
    """Prove every accepted authority file is byte-identical; fail closed."""
    pinned = dict(V5_AUTHORITY_FILES if files is None else files)
    results = _verify_pinned_files(root, pinned, "V5 authority file")
    adjudication_relative = (
        "docs/qualification/gemma4-12b-it-v5-campaign-110/b/holdout-adjudication.json")
    if adjudication_relative in pinned and \
            results[adjudication_relative] != ACCEPTED_TERMINAL_ADJUDICATION_SHA256:
        raise ApplicabilityBlocked(
            "terminal adjudication identity is not the accepted SHA-256")
    physical = _verify_pinned_files(root, ACCEPTED_PHYSICAL_IDENTITY_FILES,
                                    "physical identity evidence")
    return {
        "accepted_inferswarm_base": ACCEPTED_INFERSWARM_BASE,
        "accepted_freetoken_research_head": ACCEPTED_FREETOKEN_RESEARCH_HEAD,
        "accepted_freetoken_calibration_producer": ACCEPTED_FREETOKEN_CALIBRATION_PRODUCER,
        "accepted_freetoken_holdout_producer": ACCEPTED_FREETOKEN_HOLDOUT_PRODUCER,
        "accepted_freetoken_execution_authority": ACCEPTED_FREETOKEN_EXECUTION_AUTHORITY,
        "accepted_v5_methodology": ACCEPTED_V5_METHODOLOGY,
        "terminal_adjudication_sha256": ACCEPTED_TERMINAL_ADJUDICATION_SHA256,
        "verified_files": results,
        "verified_file_count": len(results),
        "verified_physical_identity_files": physical,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify-authority", action="store_true",
                        help="verify accepted V5 authority files and exit")
    parser.add_argument("--collect-producer-delta", action="store_true",
                        help="mechanically collect the producer-delta evidence")
    parser.add_argument("--freetoken-root", type=Path, default=None,
                        help="path to the FreeToken repository (collector)")
    parser.add_argument("--integration-producer", default=FROZEN_INTEGRATION_PRODUCER,
                        help="integration producer SHA to audit")
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args(argv)
    if args.verify_authority:
        record = verify_v5_authority(args.root)
        print(f"verified {record['verified_file_count']} accepted V5 authority files "
              f"and {len(record['verified_physical_identity_files'])} "
              "physical identity files")
    if args.collect_producer_delta:
        if args.freetoken_root is None:
            parser.error("--collect-producer-delta requires --freetoken-root")
        delta = collect_producer_delta(args.freetoken_root,
                                       integration_producer=args.integration_producer)
        out = args.out or (args.root / PRODUCER_DELTA_RELATIVE_PATH)
        write_canonical_json(out, delta)
        summary = _delta_summary(delta["zone_files"])
        print(f"producer delta collected: {len(delta['zone_files'])} zone files "
              f"{summary} out-of-zone changes "
              f"{sum(len(v) for v in delta['out_of_zone_changes'].values())}")
    if not args.verify_authority and not args.collect_producer_delta:
        document = canonical_issue117_audit(args.root)
        print(f"overall_result: {document['overall_result']}")
        if args.out is not None:
            write_canonical_json(args.out, document)
    return 0


if __name__ == "__main__":
    sys.exit(main())
