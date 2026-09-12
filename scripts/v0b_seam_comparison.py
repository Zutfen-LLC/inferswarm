#!/usr/bin/env python3
"""V0-B Phase 4 — integration-seam investigation.

Emits the structured comparison of the five integration-seam classes the
issue requires (additive, evidence-cited; no seam is chosen here — the
recommendation JSON owns that). Maps each class to existing InferSwarm
doctrine, states what it could execute, materialization implications,
host-state expectations, correctness-qualification requirements, scope
estimates, planner-leak risk, CUDA/HIP coexistence, and what V0-C could
prove without freezing a public API.

Writes docs/investigations/vulkan-v0-b/results/seam-comparison.json.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "docs/investigations/vulkan-v0-b/results/seam-comparison.json"

SEAMS = [
    {
        "id": "S1-runtime-vulkan-path",
        "class": "1. Existing runtime gains a Vulkan-native execution path",
        "description": "The current FreeToken research runtime's execution stack itself grows a Vulkan execution path alongside its CUDA path.",
        "doctrine_map": "fabric-doctrine 10.1 (backend-native fast execution) / 10.2 (same-backend fusion); ADR 0006 backend-independent boundary",
        "granularity": "whatever the runtime's execution boundary already is (stage/expert granularity on the tested Gemma path)",
        "representation_materialization": "would require the runtime's state representations to be producible by a Vulkan compute path — new kernel/representation work at the runtime's internal seam",
        "host_state_expectation": "runtime-defined; the RSS-shadow observation from V0-A suggests a ggml-style Vulkan path keeps significant host state, which must be accounted per residency rules",
        "qualification_requirements": "full three-layer ADR 0010 qualification for the new execution path on the #117 model line — same bar as the CUDA path",
        "scope_risk": "LARGE — the current execution stack is CUDA/capture-shaped (Phase1R: leaving the captured path was catastrophically expensive on the tested stack); a Vulkan sibling inside it is a second full backend port inside the most performance-sensitive component",
        "planner_leak": "low if done behind the strategy/backend boundary; high temptation to leak 'vulkan' nouns into a runtime that already carries CUDA-shaped internals",
        "coexistence": "technically yes, but the implementation cost concentrates in the one runtime where backend neutrality is hardest to keep honest",
        "v0c_could_prove": "only a narrow 'Vulkan executes one strategy-defined unit beside CUDA in one Swarm' fact, at material implementation cost",
        "assessment": "RULED INAPPLICABLE for a first spike: the current stack exposes no practical Vulkan seam, and Phase1R evidence shows execution-path swaps inside it are disproportionately costly",
    },
    {
        "id": "S2-backend-adapter-participant",
        "class": "2. Backend-specific execution adapter/participant",
        "description": "A bounded Vulkan-capable executor/adapter realizes ONE strategy-defined execution unit (e.g. a single-model local serving unit) while the generic planner/resource model stays backend-neutral; the adapter is evidence-associated with a Compute Unit.",
        "doctrine_map": "fabric-doctrine 2.4/2.8 (Compute Unit / runtime executor is plan construct), 6.6 (representation/backend legality owned by strategy), ADR 0006; matches the proven integration flow (freetoken.md: strategy-owned backend detail, generic planner backend-neutral)",
        "granularity": "one whole-model (or strategy-chosen block-set) serving unit on one Compute Unit — matched to what the V0-A probe actually proved (single GPU, whole model, 37/37 layers)",
        "representation_materialization": "GGUF/model-file materialization on device-local memory, exactly the V0-A-proven shape; no new representation invented",
        "host_state_expectation": "bounded and measurable: ready-state RSS deltas already characterized on NV-A (+213.7 MB vs CUDA); AMD-A RSS ~0.47 GB; a residency rule for the adapter is writable from retained evidence",
        "qualification_requirements": "ADR 0010 three-layer qualification scoped to the adapter's declared semantic profile — the prospective-freeze list in this bundle's correctness-stability reduction",
        "scope_risk": "MODERATE — an executor from a maintained ggml/llama.cpp-class backend (Vulkan build) behind a narrow participant interface; no changes to the frozen CUDA line; failure isolates in the adapter",
        "planner_leak": "LOW — planner sees a backend-neutral execution capability + capability/evidence records; 'Vulkan' appears only as evidence and adapter implementation",
        "coexistence": "YES by construction — CUDA/HIP/Vulkan adapters are peers under one resource graph (doctrine 10.2 permits per-backend fast executors)",
        "v0c_could_prove": "that a Vulkan-backed Compute Unit can join one Swarm, be selected by the generic planner under capability/evidence, execute the pinned model, and produce committed output beside a CUDA unit — without freezing any public API (API-unfrozen doctrine)",
        "assessment": "STRONGEST candidate: directly tests the architectural hypothesis (portable backend under vendor-neutral semantics) at the smallest honest scope",
    },
    {
        "id": "S3-external-substrate",
        "class": "3. External ggml/llama.cpp-style execution substrate",
        "description": "Treat an external whole-model executor (e.g. llama.cpp server) as a research participant/execution substrate without embedding it.",
        "doctrine_map": "edge of doctrine: a participant must expose strategy/state/execution semantics, not just an HTTP text interface; ADR 0006 boundary bytes/identity",
        "granularity": "whole model per process; the substrate owns scheduling — InferSwarm could not control block/state granularity",
        "representation_materialization": "substrate-defined; opaque to the strategy — Logical State Unit semantics cannot be verified inside it",
        "host_state_expectation": "opaque; slotting/KV management internal to the server",
        "qualification_requirements": "cannot satisfy exact-integrity layer for internal state movement (no boundary visibility); only end-to-end semantic checks possible",
        "scope_risk": "SMALL to stand up, but architecturally weak: it proves an external server works, not that InferSwarm can plan/execute over a portable backend",
        "planner_leak": "low, but only because so little is exposed to plan over",
        "coexistence": "yes, as an external service",
        "v0c_could_prove": "only availability/economics of an opaque endpoint — the weakest architectural test",
        "assessment": "INSUFFICIENT as the primary seam: it cannot test state/materialization semantics the architecture cares about; useful only as a reference implementation detail inside S2",
    },
    {
        "id": "S4-custom-vulkan-kernels",
        "class": "4. Custom Vulkan kernel/backend work",
        "description": "Write InferSwarm-owned Vulkan kernels/compute pipeline for model execution.",
        "doctrine_map": "would be a new backend implementation from scratch under the strategy/backend boundary",
        "granularity": "unbounded in principle, years of kernel coverage in practice",
        "representation_materialization": "fully self-owned; maximum freedom, maximum cost",
        "host_state_expectation": "self-defined",
        "qualification_requirements": "entire numerical-equivalence contract from zero",
        "scope_risk": "VERY LARGE — a materially larger program by any measure; the issue itself flags this class as not casually selectable",
        "planner_leak": "n/a (no planner change needed)",
        "coexistence": "yes in principle",
        "v0c_could_prove": "nothing proportionate to cost at research scale",
        "assessment": "RULED OUT for now: retained evidence shows maintained portable runtimes (ggml Vulkan) already execute the subject model correctly on both vendor stacks; no evidence shows a missing capability that only custom kernels supply",
    },
    {
        "id": "S5-no-integration",
        "class": "5. No integration",
        "description": "Correctness/stability/economics do not justify further Vulkan work.",
        "doctrine_map": "honest negative result recorded as evidence on Compute Units",
        "scope_risk": "none",
        "assessment": "NOT SUPPORTED by the evidence: the Vulkan path is physically real, device-proven, backend-locally stable, near-native on NVIDIA (0.949/0.884), and — pending the supplemental CPU arm — materially useful on AMD where NO native backend exists. 'Slow but correct' is exactly the compatibility-tier or strategy-economics case the doctrine accommodates. Rejection merely for losing to the native backend is explicitly barred by the issue.",
    },
]

if __name__ == "__main__":
    out = {
        "schema": "inferswarm.vulkan-v0-b.seam-comparison/1",
        "issue": 142,
        "seams": SEAMS,
        "classes_all_considered": True,
        "note": "selection + authorization belong to the terminal recommendation, not to this comparison",
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=1, sort_keys=True) + "\n")
    print(json.dumps({"written": str(OUT.relative_to(REPO)),
                      "seams": [s["id"] for s in SEAMS]}))
    sys.exit(0)
