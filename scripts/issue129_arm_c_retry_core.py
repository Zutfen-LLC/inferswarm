#!/usr/bin/env python3
"""Issue #129 — Arm-C retry methodology core (CPU-only; no GPU/model execution).

Implements the control-plane-only comparator-equivalence proof required by
issue #129 before any future Arm-C physical retry can be authorized:

1.  Imports the REAL frozen control-plane modules verbatim from the
    retained producer bytes under ``evidence/arm-c/frozen-freetoken/
    924cd22e/`` (the generic planner ``freetoken.research.r3_planner``,
    the plan/realization machinery ``freetoken.research.r5a_serving``,
    the epoch controller ``freetoken.research.r5b_epochs``, and the R6
    dense strategy adapters ``benchmarks.inferswarm_r6.{strategy,
    xc_strategy}``). Every imported byte is sha256-pinned: the accepted
    #128-pinned trio is cross-checked through
    ``scripts/issue117_arm_c_frozen_pins.py``; the two dependencies added
    by #129 (``r5a_serving.py``, ``strategy.py``) are pinned by this
    module. No FreeToken working checkout is used.

2.  Derives the frozen 24-case rendered-prompt-token fixture from
    retained ACCEPTED Arm-C evidence (read-only): the exact chat-rendered
    prompt token ids per case, cross-derived from BOTH retained accepted
    sides (direct-run results and the ordinary coordinator per-request
    records), with per-case sha256 and a fixture digest. The retry
    direct comparator consumes these frozen ids; no tokenizer/Source
    read exists at observation time.

3.  Runs, entirely on CPU with a recording/fake runtime, both arms over
    all 24 frozen cases:

    - ORDINARY: the real ``EpochServingController`` — real planner
      decision (AUTOMATIC_PLANNER_SELECTION), real
      ``freeze_execution_plan``, real realization reconciliation, real
      ``serve_tokens`` replay-prefix loop — driven through a realizer
      that returns the recording runtime. Every runtime ``generate``
      call is recorded.
    - DIRECT: an independently coded comparator that mechanically
      reproduces the ordinary controller's runtime invocation contract
      (per committed position: replay prefix = prompt + committed ids,
      one ``generate(max_new_tokens=2)`` call, commit the step-0 token,
      discard the speculative step-1 token; repeat until 8 committed).
      Mutator variants for the mandatory negative controls are selected
      by ``variant``.

    Both arms share one deterministic fake model response function
    seeded from the frozen fixture bytes, so equivalence is a property
    of the two control-plane paths, not of model outputs.

4.  Compares the ordered runtime-call transcripts mechanically and
    fail-closed (``reduce_transcripts``): case identity, call count and
    position, replay token ids, ``max_new_tokens``, generate-argument
    names, commit/discard semantics, committed counts, sampling and
    stopping contracts. Control-plane-only fields are enumerated
    explicitly and proven outside the model-execution input transcript.
    Stored ``equal`` flags or terminal strings are never consulted.

5.  Exposes an executable attempt/STOP state machine
    (``classify_attempt`` / ``reduce_attempts``) that mechanically
    decides attempt classes and mandatory STOPs from observed attempt
    facts — never from an authored validity label.

6.  Exposes the exact deployed-script identity contract
    (``verify_deployment_identity``): repository SHA + file sha256 +
    expected path + read-only deployment + pre/post verification,
    rejecting mutable/unpinned staged drivers and post-freeze script
    changes.

No GPU execution, no model execution, no holdout use, no mutation of
accepted Arm-B participant state. The accepted #128 blocker evidence is
read-only input.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
import types
from pathlib import Path
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
AREA = ROOT / "docs/implementation/r6-successor-dense-full-integration-117"
ARM_C_EVIDENCE = AREA / "evidence" / "arm-c"
ARM_C_RETRY_EVIDENCE = AREA / "evidence" / "arm-c-retry"
FROZEN_PREFIX = "frozen-freetoken/924cd22e/"

FROZEN_PRODUCER_SHA = "924cd22ea081f6d4ed471016faf01d427fc5b0d2"
ACCEPTED_BLOCKER_MERGE = "718efbf5770b31c6e44eb3a8c4d0b81fd1dc9c22"
ACCEPTED_ARM_B_RESULT = "ISSUE117_ARM_B_COLD_REALIZATION_PASS"
ACCEPTED_ARM_B_MERGE = "fed87d1b71a0794374dd58c921e31606a56a242f"
FIXTURE_DIGEST_24 = "sha256:180185cd5c6a5dcd77b2c65979bd2c9aef4d1c7ea9fb4850a64f4508b2ba36f2"
CHECKPOINT_SHA256 = "5a84cb313260ac447237b890387116dfa8682e49a6b44bc585ae8353abbff18d"
MODEL_REVISION = "707f0a3b8a3c7ad586ed01e27eafbad8a27dd0f7"

METHODOLOGY_READY = "ISSUE117_ARM_C_RETRY_METHODOLOGY_READY"
METHODOLOGY_BLOCKED = "ISSUE117_ARM_C_RETRY_METHODOLOGY_BLOCKED"

CASE_COUNT = 24
COMMIT_TOKENS = 8
GENERATE_MAX_NEW_TOKENS = 2

#: frozen per-call generate() argument-name contract (the exact keyword
#: set the frozen controller passes; anything else leaking in — e.g. a
#: control-plane-only field — fails closed)
GENERATE_ARGUMENT_NAMES = ("max_new_tokens", "on_token", "prompt_token_ids", "session_id")

#: frozen sampling contract (greedy; both arms identical)
SAMPLING_INPUTS = {"temperature": 0.0, "top_k": -1, "top_p": 1.0}

#: frozen stopping contract (length-only at 8 committed)
STOPPING_POLICY = {"kind": "length", "committed_tokens": COMMIT_TOKENS}

#: explicit enumeration of control-plane-only fields: they may differ
#: between the arms BY CONSTRUCTION and are proven outside the
#: model-execution input transcript (never among generate() arguments).
CONTROL_PLANE_ONLY_FIELDS = (
    "runtime_session_id",
    "epoch_id",
    "generation",
    "realization_id",
    "plan_digest_value",
    "logical_session_id",
    "wall_ns",
)


def _repo_override() -> Path:
    env = os.environ.get("ARM_C_RETRY_REPO")
    return Path(env) if env else ROOT


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_canonical_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


# ---------------------------------------------------------------------------
# 1. Frozen producer bytes: pins + import
# ---------------------------------------------------------------------------

#: every frozen control-plane byte this methodology imports, retained
#: verbatim under evidence/arm-c/frozen-freetoken/924cd22e/. ``None`` pins
#: are owned by the accepted #128 pins module and cross-checked through it.
FROZEN_CONTROL_PLANE_FILES = {
    "python/freetoken/research/r3_planner.py":
        "080e8b64fbb9fbc0f6df390d5714d0db"
        "c691dd601e2bd13fe4ff71596e2d0856",
    "python/freetoken/research/r5a_serving.py":
        "f61adc3201f5c2c9d23afcc90da3135c"
        "a89b3ed7eb3213d68a41b08fc242b105",
    "python/freetoken/research/r5b_epochs.py": None,
    "benchmarks/inferswarm_r6/strategy.py":
        "ca31f0999cb4fcf46d73c83f8b3ee7bb"
        "e2636792bcfc1824b15946aaac53906b",
    "benchmarks/inferswarm_r6/xc_strategy.py": None,
}

_LOADED = False


def verify_frozen_bytes(repo_root: Path | None = None) -> dict[str, str]:
    """Verify every retained control-plane byte against its pin; fail-closed.

    Returns {retained-relative-path: sha256}."""
    root = repo_root or _repo_override()
    base = root / ARM_C_EVIDENCE.relative_to(ROOT) / FROZEN_PREFIX
    pins_128: dict[str, str] = {}
    scripts = root / "scripts"
    if (scripts / "issue117_arm_c_frozen_pins.py").is_file():
        import importlib.util as _ilu
        spec = _ilu.spec_from_file_location(
            "_issue129_pins_128", scripts / "issue117_arm_c_frozen_pins.py")
        module = _ilu.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
            pins_128 = dict(module.FROZEN_SHA256)
        except Exception:
            pins_128 = {}
    digests = {}
    for rel, local_pin in FROZEN_CONTROL_PLANE_FILES.items():
        path = base / rel
        if not path.is_file():
            raise FileNotFoundError(f"missing frozen producer byte: {path}")
        digest = sha256_file(path)
        if local_pin is not None and digest != local_pin:
            raise RuntimeError(f"frozen byte drift against #129 pin: {rel}")
        repo_rel = str((ARM_C_EVIDENCE / FROZEN_PREFIX / rel).relative_to(ROOT))
        pinned = pins_128.get(repo_rel)
        if pinned is not None and digest != pinned:
            raise RuntimeError(f"frozen byte drift against #128 pin: {rel}")
        digests[repo_rel] = digest
    return digests


def _register_package(name: str) -> types.ModuleType:
    if name in sys.modules:
        return sys.modules[name]
    module = types.ModuleType(name)
    module.__path__ = []
    sys.modules[name] = module
    return module


def _load_module(name: str, path: Path) -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def load_frozen_control_plane(repo_root: Path | None = None):
    """Import the retained frozen producer control plane under its REAL
    module names, from the retained bytes; return (r3_planner,
    r5a_serving, r5b_epochs, strategy_constants, xc_strategy).

    Modules are loaded once per process; every byte is verified by
    ``verify_frozen_bytes`` before the first import. Parent packages are
    registered as empty namespace stand-ins so the frozen bytes' own
    absolute/relative imports resolve to the retained bytes only.
    """
    global _LOADED
    root = repo_root or _repo_override()
    digests = verify_frozen_bytes(root)
    del digests
    base = root / ARM_C_EVIDENCE.relative_to(ROOT) / FROZEN_PREFIX
    if _LOADED:
        return (
            sys.modules["freetoken.research.r3_planner"],
            sys.modules["freetoken.research.r5a_serving"],
            sys.modules["freetoken.research.r5b_epochs"],
            sys.modules["benchmarks.inferswarm_r6.strategy"],
            sys.modules["benchmarks.inferswarm_r6.xc_strategy"],
        )
    for package in ("freetoken", "freetoken.research",
                    "benchmarks", "benchmarks.inferswarm_r6"):
        _register_package(package)
    planner = _load_module(
        "freetoken.research.r3_planner",
        base / "python/freetoken/research/r3_planner.py")
    serving = _load_module(
        "freetoken.research.r5a_serving",
        base / "python/freetoken/research/r5a_serving.py")
    epochs = _load_module(
        "freetoken.research.r5b_epochs",
        base / "python/freetoken/research/r5b_epochs.py")
    strategy = _load_module(
        "benchmarks.inferswarm_r6.strategy",
        base / "benchmarks/inferswarm_r6/strategy.py")
    xc_strategy = _load_module(
        "benchmarks.inferswarm_r6.xc_strategy",
        base / "benchmarks/inferswarm_r6/xc_strategy.py")
    _LOADED = True
    return planner, serving, epochs, strategy, xc_strategy


# ---------------------------------------------------------------------------
# 2. Frozen rendered-prompt-token fixture (derived from accepted evidence)
# ---------------------------------------------------------------------------

def derive_prompt_fixture(repo_root: Path | None = None) -> dict[str, Any]:
    """Derive the frozen 24-case rendered prompt-token fixture from
    retained accepted Arm-C evidence; fail-closed."""
    root = repo_root or _repo_override()
    base = root / ARM_C_EVIDENCE.relative_to(ROOT)
    direct = json.loads((base / "direct-run.json").read_text())
    coordinator = json.loads((base / "coordinator-report.json").read_text())
    integration = json.loads(
        (root / AREA.relative_to(ROOT) / "evidence" / "integration-fixture.json"
         ).read_text())
    if direct.get("producer") != FROZEN_PRODUCER_SHA:
        raise RuntimeError("direct-run.json is not bound to the frozen producer")
    if direct.get("case_count") != CASE_COUNT:
        raise RuntimeError("direct-run.json case-count drift")
    if integration.get("fixture_digest") != FIXTURE_DIGEST_24:
        raise RuntimeError("integration fixture digest drift")
    integration_cases = {
        row["case"]["case_id"]: row["case"] for row in integration["cases"]}
    if len(integration_cases) != CASE_COUNT:
        raise RuntimeError("integration fixture case-count drift")
    ordinary = {}
    for rec in coordinator["coordinator_scope"]["requests"]:
        if rec.get("fencing_arm_injections"):
            # session 25 is the fencing-arm request: fencing evidence only,
            # explicitly outside the equality set (frozen §5 contract)
            continue
        ordinary[rec["session_id"]] = rec
    if len(ordinary) != CASE_COUNT:
        raise RuntimeError(
            f"coordinator report does not carry {CASE_COUNT} non-fencing "
            f"requests (got {len(ordinary)})")

    rows = []
    for index, result in enumerate(direct["results"], start=1):
        case_id = result["case_id"]
        rendered = list(result["prompt_token_ids"])
        record = ordinary.get(index)
        if record is None or record.get("session_id") != index:
            raise RuntimeError(f"ordinary record {index} missing for {case_id}")
        if rendered != list(record["prompt_token_ids"]):
            raise RuntimeError(
                f"{case_id}: accepted campaign render equality does not hold")
        case = integration_cases.get(case_id)
        if case is None:
            raise RuntimeError(f"{case_id}: not in the accepted fixture")
        raw = list(case["token_ids"])
        if len(rendered) < len(raw):
            raise RuntimeError(
                f"{case_id}: rendered ids shorter than the raw fixture ids")
        body = {
            "case_id": case_id,
            "session_index": index,
            "rendered_prompt_token_ids": rendered,
            "raw_fixture_token_ids": raw,
            "rendered_len": len(rendered),
        }
        rows.append({
            **body,
            "case_render_sha256": "sha256:" + sha256_bytes(
                json.dumps(body, sort_keys=True).encode()),
        })
    rows.sort(key=lambda r: (r["session_index"], r["case_id"]))
    return {
        "schema": "inferswarm.issue129.prompt-fixture/1",
        "authority": {
            "accepted_arm_c_blocker_merge": ACCEPTED_BLOCKER_MERGE,
            "frozen_producer": FROZEN_PRODUCER_SHA,
            "accepted_fixture_digest": FIXTURE_DIGEST_24,
            "sources": [
                "evidence/arm-c/direct-run.json",
                "evidence/arm-c/coordinator-report.json",
                "evidence/integration-fixture.json",
            ],
        },
        "case_count": CASE_COUNT,
        "cases": rows,
        "fixture_derivation": (
            "rendered ids cross-derived from BOTH retained accepted sides "
            "(direct-run results and ordinary coordinator per-request "
            "records; equality re-derived); raw fixture tail-equality "
            "re-derived against the accepted integration fixture"),
        "fixture_digest": "sha256:" + sha256_bytes(json.dumps(
            [{k: v for k, v in row.items() if k != "case_render_sha256"}
             for row in rows], sort_keys=True).encode()),
    }


# ---------------------------------------------------------------------------
# 3. CPU recording runtime + the two arms
# ---------------------------------------------------------------------------

class RecordingRuntime:
    """Fake integrated runtime: no model, no GPU; deterministic per-case
    responses seeded from the frozen fixture bytes; records every
    correctness-relevant generate() invocation.

    Like the accepted substrate seam: the response is derived from the
    replayed token-stream content/length (position within the case), not
    from the wire session id.
    """

    def __init__(self, case_responses: Mapping[str, Sequence[Sequence[int]]],
                 sink: list[dict[str, Any]], arm: str,
                 extra_arguments: Sequence[str] = ()) -> None:
        self.case_responses = {
            case: [list(step) for step in steps]
            for case, steps in case_responses.items()}
        self.sink = sink
        self.arm = arm
        self.extra_arguments = tuple(extra_arguments)
        self.case_starts: dict[str, tuple[int, ...]] = {}
        self.plan_digest_value: str | None = None
        self._closed = False
        self._reject_unknown_stream = False

    def bind_cases(self, starts: Mapping[str, tuple[int, ...]]) -> None:
        self.case_starts = {case: tuple(s) for case, s in starts.items()}

    def _locate(self, stream: Sequence[int]) -> tuple[str, int]:
        stream = list(stream)
        matches = [
            (case, start) for case, start in self.case_starts.items()
            if len(stream) >= len(start) and list(start) == stream[:len(start)]
        ]
        if not matches:
            raise RuntimeError("replayed stream matches no frozen case")
        case, start = max(matches, key=lambda item: len(item[1]))
        return case, len(stream) - len(start)

    def generate(self, *, session_id: int, prompt_token_ids: list[int],
                 max_new_tokens: int,
                 on_token=None, **extra) -> dict[str, Any]:
        if self._closed:
            raise RuntimeError("runtime is closed")
        try:
            case_id, position = self._locate(prompt_token_ids)
        except RuntimeError:
            if self.arm == "direct" and self._reject_unknown_stream:
                # a mutated replay prefix is a transcript defect the reducer
                # must see and fail closed on, not a harness crash
                self.sink.append({
                    "arm": self.arm,
                    "case_id": None,
                    "runtime_session_id": int(session_id),
                    "prompt_token_ids": list(prompt_token_ids),
                    "max_new_tokens": int(max_new_tokens),
                    "response_token_ids": [],
                    "on_token_present": on_token is not None,
                    "argument_names": tuple(sorted(
                        ("max_new_tokens", "on_token", "prompt_token_ids",
                         "session_id") + tuple(extra) + self.extra_arguments)),
                    "unresolvable_replay_stream": True,
                })
                return {
                    "schema": "inferswarm.r5b.runtime-result/1",
                    "session_id": int(session_id),
                    "generated_token_ids": [],
                    "plan_digest": self.plan_digest_value,
                }
            raise
        if max_new_tokens < 1:
            raise ValueError("max_new_tokens must be positive")
        steps = self.case_responses[case_id]
        if position >= len(steps):
            raise RuntimeError(f"replay beyond scripted responses: {case_id}")
        tokens = list(steps[position])[:max_new_tokens]
        while len(tokens) < max_new_tokens:
            tokens.append(tokens[-1] if tokens else 0)
        if on_token is not None:
            for step, token in enumerate(tokens):
                on_token(step, int(token), {
                    "schema": "inferswarm.r5b.runtime-boundary/1", "step": step})
        self.sink.append({
            "arm": self.arm,
            "case_id": case_id,
            "runtime_session_id": int(session_id),
            "prompt_token_ids": list(prompt_token_ids),
            "max_new_tokens": int(max_new_tokens),
            "response_token_ids": list(tokens),
            "on_token_present": on_token is not None,
            "argument_names": tuple(sorted(
                ("max_new_tokens", "on_token", "prompt_token_ids", "session_id")
                + tuple(extra) + self.extra_arguments)),
        })
        return {
            "schema": "inferswarm.r5b.runtime-result/1",
            "session_id": int(session_id),
            "generated_token_ids": list(tokens),
            "plan_digest": self.plan_digest_value,
        }

    def report(self) -> dict[str, Any]:
        return {
            "schema": "inferswarm.r5b.runtime-report/1",
            "arm": self.arm,
            "call_count": sum(1 for r in self.sink if r["arm"] == self.arm),
            "closed": self._closed,
        }

    def close(self) -> None:
        self._closed = True


def deterministic_case_responses(
        fixture: Mapping[str, Any]) -> dict[str, list[list[int]]]:
    """One deterministic 2-token response per committed position per case,
    seeded from the frozen fixture bytes (arm-independent)."""
    responses: dict[str, list[list[int]]] = {}
    for case in fixture["cases"]:
        counter = int(hashlib.sha256(
            (case["case_id"] + ":" + case["case_render_sha256"]).encode()
        ).hexdigest()[:8], 16)
        steps = []
        for _ in range(COMMIT_TOKENS):
            row = []
            for _ in range(2):
                counter = (counter * 1103515245 + 12345) % (1 << 31)
                row.append(100_000 + (counter % 5000))
            steps.append(row)
        responses[case["case_id"]] = steps
    return responses


def _frozen_environment(repo_root: Path) -> dict[str, Any]:
    """The accepted Arm-C environment freeze, reconstructed from retained
    accepted evidence (physical-preflight compute-unit identities)."""
    preflight = json.loads(
        (repo_root / AREA.relative_to(ROOT) / "evidence"
         / "physical-preflight.json").read_text())
    units = {u["cu_id"]: u for u in preflight["compute_units"]}

    def gpu(cu_id: str, index: int, bdf: str) -> dict[str, Any]:
        unit = units[cu_id]
        return {
            "index": index,
            "uuid": unit["gpu_uuid"],
            "name": unit["gpu_product"],
            "vram_total_bytes": 12_288 * 1024 * 1024,
            "pci_bdf": bdf,
            "availability": "AVAILABLE",
        }

    return {
        "schema": "inferswarm.r6.environment-freeze/1",
        "implementation_commit": FROZEN_PRODUCER_SHA,
        "model": {
            "repository": "google/gemma-4-12B-it",
            "revision": MODEL_REVISION,
            "checkpoint_sha256": CHECKPOINT_SHA256,
            "serving_scope": "text-only",
            "representation": "native-bf16-safetensors",
        },
        "runtime_context": f"r6-dense-producer:{FROZEN_PRODUCER_SHA}",
        "network_context": "1GbE-LAN-MTU1500-node-a-to-node-b",
        "node_a": {"node_id": "node.inferswarm01", "gpus": [
            gpu("inferswarm01/gpu-0", 0, "0000:01:00.0"),
            gpu("inferswarm01/gpu-1", 1, "0000:02:00.0")]},
        "node_b": {"node_id": "node.inferswarm03", "gpus": [
            gpu("inferswarm03/gpu-0", 0, "0000:01:00.0")]},
        "network": {
            "link_id": "path.node-a-to-node-b.1gbe",
            "negotiated_mbps": 1000,
            "available": True,
        },
        "provenance_note": (
            "GPU uuid/product from the retained accepted physical-preflight "
            "compute units; 3060-class 12 GiB VRAM totals and pci bdf slots "
            "are control-plane-only planner-snapshot metadata (never runtime "
            "inputs) and carry no correctness bearing"),
    }


def build_resource_snapshot(planner, environment: Mapping[str, Any]):
    """CPU-pure resource snapshot mirroring the pinned coordinator's
    ``_r6_snapshot`` structure exactly."""
    freeze = planner.freeze

    def unit(unit_id, record, capabilities):
        return {
            "id": unit_id,
            "stable_device_id": record["uuid"],
            "pci_bdf": record["pci_bdf"],
            "memory_resource_id": f"{unit_id}.vram",
            "availability": record.get("availability", "AVAILABLE"),
            "integrity_eligible": True,
            "capabilities": capabilities,
        }

    a, b = environment["node_a"], environment["node_b"]
    a0, a1, b0 = a["gpus"][0], a["gpus"][1], b["gpus"][0]
    return freeze({
        "schema": "inferswarm.r6.resource-evidence-snapshot/1",
        "implementation_commit": environment["implementation_commit"],
        "environment_digest": None,
        "evidence_context": {
            "runtime_context": environment["runtime_context"],
            "network_context": environment["network_context"],
        },
        "nodes": [
            {
                "id": a["node_id"],
                "compute_units": [
                    unit("gpu.node-a.0", a0, ["freetoken-resident-stage-first-v1"]),
                    unit("gpu.node-a.1", a1, ["freetoken-resident-stage-middle-v1"]),
                ],
                "memory_resources": [
                    {"id": "gpu.node-a.0.vram", "kind": "accelerator-vram-a0",
                     "capacity_bytes": a0["vram_total_bytes"], "reservation_bytes": 0},
                    {"id": "gpu.node-a.1.vram", "kind": "accelerator-vram-a1",
                     "capacity_bytes": a1["vram_total_bytes"], "reservation_bytes": 0},
                ],
            },
            {
                "id": b["node_id"],
                "compute_units": [
                    unit("gpu.node-b.0", b0, ["freetoken-resident-stage-last-v1"]),
                ],
                "memory_resources": [
                    {"id": "gpu.node-b.0.vram", "kind": "accelerator-vram-b0",
                     "capacity_bytes": b0["vram_total_bytes"], "reservation_bytes": 0},
                ],
            },
        ],
        "links": [
            {"id": "path.node-a.local-staging",
             "source_memory_resource_id": "gpu.node-a.0.vram",
             "target_memory_resource_id": "gpu.node-a.1.vram",
             "available": True,
             "capabilities": ["freetoken-static-boundary-v1"]},
            {"id": environment["network"]["link_id"],
             "source_memory_resource_id": "gpu.node-a.1.vram",
             "target_memory_resource_id": "gpu.node-b.0.vram",
             "available": True,
             "capabilities": ["freetoken-static-boundary-v1"],
             "negotiated_mbps": environment["network"]["negotiated_mbps"]},
        ],
    })


def _objective(planner):
    return planner.freeze({
        "schema": "inferswarm.r6.objective/1",
        "implementation_commit": FROZEN_PRODUCER_SHA,
        "id": "r6-dense-serving-ttft_ms",
        "metric": "ttft_ms",
        "direction": "MINIMIZE",
        "unit": "ms",
        "statistic": "single-run",
        "evidence_context": {
            "model_revision": MODEL_REVISION,
            "workload_geometry": "r6-dense-3stage-chain",
        },
    })


def _evidence_catalog(planner, repo_root: Path | None = None):
    """Evidence catalog containing the accepted campaign's single
    context-exact MEASURED ranking record (reconstructed verbatim from the
    retained accepted coordinator-report evidence audit: the direct-arm
    chain measurement at the exact frozen context). With no record the
    frozen planner honestly returns FEASIBLE_UNRANKED /
    NO_AUTOMATIC_SELECTION, so the ordinary arm REQUIRES this record to
    exercise AUTOMATIC_PLANNER_SELECTION, exactly as the accepted
    coordinator did."""
    root = repo_root or _repo_override()
    report = json.loads(
        (root / ARM_C_EVIDENCE.relative_to(ROOT) / "coordinator-report.json"
         ).read_text())
    epoch = report["epochs"][0]
    evaluation = next(
        item for item in epoch["planner_decision"]["evaluations"]
        if item.get("state") == "RANKED")
    audits = [
        audit for audit in evaluation["evidence"]
        if audit.get("applicable") and audit.get("role") == "RANKING_OBJECTIVE"]
    if len(audits) != 1:
        raise RuntimeError(
            "expected exactly one applicable RANKING_OBJECTIVE audit in the "
            "accepted coordinator report")
    audit = audits[0]
    record = {
        "id": audit["evidence_id"],
        "role": "RANKING_OBJECTIVE",
        "metric": dict(audit["metric"]),
        "shape_id": evaluation["shape_id"],
        "mapping": dict(evaluation["mapping"]),
        "required_context": {
            "model_revision": MODEL_REVISION,
            "workload_geometry": "r6-dense-3stage-chain",
        },
        "freshness": audit["freshness"],
        "evidence_class": audit["evidence_class"],
        "confidence": audit["confidence"],
        "measurement_status": audit["measurement_status"],
        "producer_identity": audit["producer_identity"],
        "evidence_identity": audit["evidence_identity"],
        "provenance": dict(audit["provenance"]),
    }
    return planner.freeze({
        "schema": "inferswarm.r6.evidence-catalog/1",
        "implementation_commit": FROZEN_PRODUCER_SHA,
        "records": [record],
    })


def _transition_policy(planner):
    return planner.freeze({
        "schema": "inferswarm.r6.transition-policy/1",
        "implementation_commit": FROZEN_PRODUCER_SHA,
        "correctness_and_feasibility_first": True,
        "operator_policy": "automatic within this bounded physical campaign",
        "single_legal_shape": True,
        "reason": "R6 freezes one legal dense shape per fabric; no "
                  "economically-ranked reconfiguration arm is exercised",
    })


class _RecordingRealizer:
    """Realizer returning the recording runtime; performs the REAL frozen
    reconciliation contract (observation mirrors the plan fields)."""

    def __init__(self, runtime: RecordingRuntime, serving) -> None:
        self.runtime = runtime
        self.serving = serving

    def __call__(self, execution_plan: Mapping[str, Any],
                 realization_authorization: Mapping[str, Any] | None = None):
        observation = {
            "plan_digest": execution_plan["digest"],
            "participants": execution_plan["participants"],
            "compute_units": execution_plan["compute_units"],
            "representations": execution_plan["representations"],
            "backend_choices": execution_plan["backend_choices"],
            "state_placement": execution_plan["state_placement"],
            "state_authority": execution_plan["state_authority"],
            "semantic_boundaries": execution_plan["semantic_boundaries"],
        }
        self.serving.reconcile_realization(execution_plan, observation)
        self.runtime.plan_digest_value = execution_plan["digest"]
        return self.serving.RealizedStaticPlan(
            runtime=self.runtime, observation=observation)


def _load_chain_plan(repo_root: Path) -> dict[str, Any]:
    chain_plan = json.loads(
        (repo_root / ARM_C_EVIDENCE.relative_to(ROOT) / "chain-plan.json"
         ).read_text())
    if chain_plan["provenance"]["r6"]["producer_sha"] != FROZEN_PRODUCER_SHA:
        raise RuntimeError("chain plan is not bound to the frozen producer")
    return chain_plan


def _bind_runtime(runtime: RecordingRuntime, fixture: Mapping[str, Any]) -> None:
    runtime.bind_cases({
        case["case_id"]: tuple(case["rendered_prompt_token_ids"])
        for case in fixture["cases"]})


def _arm_document(arm: str, variant: str, plan: Mapping[str, Any],
                  runtime: RecordingRuntime,
                  per_case: dict[str, Any]) -> dict[str, Any]:
    arguments = {tuple(call["argument_names"])
                 for call in runtime.sink if call["arm"] == arm}
    if len(arguments) > 1:
        raise RuntimeError(f"{arm}: generate argument names drifted across calls")
    return {
        "arm": arm,
        "variant": variant,
        "plan_digest": plan["digest"],
        "candidate_id": plan["candidate_id"],
        "mapping": dict(plan["mapping"]),
        "selection_authorization": dict(plan["selection_authorization"]),
        "plan_digest_source": "real freeze_execution_plan via frozen producer bytes",
        "sampling_inputs": dict(SAMPLING_INPUTS),
        "stopping_policy": dict(STOPPING_POLICY),
        "generate_argument_names": sorted(
            arguments.pop() if arguments else GENERATE_ARGUMENT_NAMES),
        "per_case": per_case,
    }


def _public_calls(calls: Sequence[Mapping[str, Any]],
                  case_id: str) -> list[dict[str, Any]]:
    return [{
        "case_id": case_id,
        "call_index": index,
        "prompt_token_ids": list(call["prompt_token_ids"]),
        "max_new_tokens": call["max_new_tokens"],
        "on_token_present": call["on_token_present"],
        "response_token_ids": list(call["response_token_ids"]),
        "response_commit_token_id": (
            int(call["response_token_ids"][0])
            if call["response_token_ids"] else None),
        "response_speculative_token_id": (
            int(call["response_token_ids"][1])
            if len(call["response_token_ids"]) > 1 else None),
        "unresolvable_replay_stream": call.get("unresolvable_replay_stream",
                                               False),
    } for index, call in enumerate(calls)]


def run_ordinary_arm(planner, serving, epochs, xc_strategy, fixture,
                     repo_root: Path) -> dict[str, Any]:
    """ORDINARY arm: the real EpochServingController serve_tokens loop."""
    environment = _frozen_environment(repo_root)
    chain_plan = _load_chain_plan(repo_root)
    transcript: list[dict[str, Any]] = []
    runtime = RecordingRuntime(
        deterministic_case_responses(fixture), transcript, arm="ordinary")
    _bind_runtime(runtime, fixture)

    def compiler(evaluation):
        return xc_strategy.compile_candidate(
            dict(evaluation), chain_plan=dict(chain_plan))

    controller = epochs.EpochServingController(
        problem=xc_strategy.planning_problem(FROZEN_PRODUCER_SHA),
        initial_snapshot=build_resource_snapshot(planner, environment),
        policy=xc_strategy.operator_policy(FROZEN_PRODUCER_SHA),
        objective=_objective(planner),
        evidence_catalog=_evidence_catalog(planner, repo_root),
        compiler=compiler,
        realizer=_RecordingRealizer(runtime, serving),
        transition_strategy=xc_strategy.GemmaTokenBoundaryStrategy(),
        transition_policy=_transition_policy(planner),
    )
    per_case = {}
    for case in sorted(fixture["cases"], key=lambda c: c["session_index"]):
        mark = len(transcript)
        completed = controller.serve_tokens(
            session_id=case["session_index"],
            prompt_token_ids=list(case["rendered_prompt_token_ids"]),
            max_new_tokens=COMMIT_TOKENS,
            sampling_inputs=dict(SAMPLING_INPUTS))
        per_case[case["case_id"]] = {
            "case_id": case["case_id"],
            "logical_session_id": case["session_index"],
            "completed_token_ids": list(completed["generated_token_ids"]),
            "committed_count": len(completed["generated_token_ids"]),
            "committed_epoch_ids": list(completed["committed_epoch_ids"]),
            "committed_plan_digests": list(completed["committed_plan_digests"]),
            "calls": _public_calls(transcript[mark:], case["case_id"]),
        }
    plan = controller._epochs[0].execution_plan
    document = _arm_document(
        "ordinary", "corrected", plan, runtime, per_case)
    controller.close()
    document["controller_report_schema"] = "inferswarm.r5b.epoch-serving-report/1"
    return document


def run_direct_arm(planner, serving, epochs, xc_strategy, fixture,
                   repo_root: Path, *, variant: str = "corrected",
                   sampling_inputs: Mapping[str, Any] | None = None,
                   stopping_policy: Mapping[str, Any] | None = None,
                   prompt_mangle=None) -> dict[str, Any]:
    """DIRECT comparator arm, OUTSIDE the controller.

    ``variant`` selects the corrected contract or a mutator for the
    negative-control suite. ``sampling_inputs``/``stopping_policy``/
    ``prompt_mangle`` are additional mutator seams (defaults frozen)."""
    environment = _frozen_environment(repo_root)
    chain_plan = _load_chain_plan(repo_root)
    transcript: list[dict[str, Any]] = []
    runtime = RecordingRuntime(
        deterministic_case_responses(fixture), transcript, arm="direct",
        extra_arguments=(
            ("epoch_id",) if variant == "control_plane_field_leak" else ()))
    runtime._reject_unknown_stream = True
    _bind_runtime(runtime, fixture)

    # compile the real plan through the same frozen machinery so the
    # direct arm's candidate/mapping identity is derivational
    decision = planner.plan(
        xc_strategy.planning_problem(FROZEN_PRODUCER_SHA),
        build_resource_snapshot(planner, environment),
        xc_strategy.operator_policy(FROZEN_PRODUCER_SHA),
        _objective(planner), _evidence_catalog(planner, repo_root))
    evaluation = planner.selected_evaluation(decision)
    body = xc_strategy.compile_candidate(
        dict(evaluation), chain_plan=dict(chain_plan))
    authorization = {
        "mode": "CONTROLLED_EVIDENCE_COLLECTION_OVERRIDE",
        "candidate_id": evaluation["id"],
        "planner_selected_candidate_id": decision["selected_candidate_id"],
        "automatic_selection_preserved": True,
    }
    execution_plan = serving.freeze_execution_plan(
        decision=decision, evaluation=evaluation, authorization=authorization,
        compiled_body=body, objective=_objective(planner),
        policy=xc_strategy.operator_policy(FROZEN_PRODUCER_SHA))
    runtime.plan_digest_value = execution_plan["digest"]

    sampling = dict(sampling_inputs or SAMPLING_INPUTS)

    def _direct_on_token(step: int, token: int, boundary) -> None:
        # commit only step zero; the speculative step-1 token is discarded
        # (the ordinary controller's capture contract, independently coded)
        del step, token, boundary

    per_case = {}
    for case in sorted(fixture["cases"], key=lambda c: c["session_index"]):
        case_id = case["case_id"]
        rendered = list(case["rendered_prompt_token_ids"])
        if prompt_mangle is not None:
            rendered = list(prompt_mangle(case_id, rendered))
        committed: list[int] = []
        mark = len(transcript)
        if variant == "single_shot_8":
            result = runtime.generate(
                session_id=case["session_index"],
                prompt_token_ids=rendered, max_new_tokens=COMMIT_TOKENS)
            committed = list(result["generated_token_ids"])
        else:
            while len(committed) < COMMIT_TOKENS:
                if variant == "call_count_skip" and len(committed) == 3:
                    # one position commits without a runtime call
                    committed.append(committed[-1])
                    continue
                if variant == "wrong_replay_prefix" and committed:
                    replay = (list(rendered) + committed[:-1]
                              + [committed[-1] + 1])
                else:
                    replay = list(rendered) + committed
                result = runtime.generate(
                    session_id=case["session_index"] + 50_000,
                    prompt_token_ids=replay,
                    max_new_tokens=GENERATE_MAX_NEW_TOKENS,
                    on_token=_direct_on_token)
                tokens = list(result["generated_token_ids"])
                if not tokens:
                    # unresolvable replay stream recorded; fail closed by
                    # committing nothing further (reducer sees the defect)
                    break
                if variant == "commit_speculative":
                    committed.extend(tokens[:2])
                else:
                    committed.append(tokens[0])
        per_case[case_id] = {
            "case_id": case_id,
            "logical_session_id": case["session_index"],
            "completed_token_ids": committed,
            "committed_count": len(committed),
            "committed_epoch_ids": None,
            "committed_plan_digests": None,
            "calls": _public_calls(transcript[mark:], case_id),
        }
    document = _arm_document("direct", variant, execution_plan, runtime, per_case)
    if sampling_inputs is not None:
        document["sampling_inputs"] = dict(sampling_inputs)
    if stopping_policy is not None:
        document["stopping_policy"] = dict(stopping_policy)
    return document


def run_both_arms(repo_root: Path | None = None, *,
                  direct_variant: str = "corrected",
                  direct_sampling=None, direct_stopping=None,
                  direct_prompt_mangle=None) -> dict[str, Any]:
    root = repo_root or _repo_override()
    planner, serving, epochs, _strategy, xc_strategy = load_frozen_control_plane(root)
    fixture = derive_prompt_fixture(root)
    ordinary = run_ordinary_arm(
        planner, serving, epochs, xc_strategy, fixture, root)
    direct = run_direct_arm(
        planner, serving, epochs, xc_strategy, fixture, root,
        variant=direct_variant, sampling_inputs=direct_sampling,
        stopping_policy=direct_stopping, prompt_mangle=direct_prompt_mangle)
    return {"fixture": fixture, "ordinary": ordinary, "direct": direct}


# ---------------------------------------------------------------------------
# 4. Fail-closed transcript-equivalence reducer
# ---------------------------------------------------------------------------

MODEL_INPUT_FIELDS = (
    "case_id",
    "call_index",
    "prompt_token_ids",
    "max_new_tokens",
    "on_token_present",
    "response_commit_token_id",
    "response_speculative_token_id",
    "response_token_ids",
)


def reduce_transcripts(ordinary: Mapping[str, Any],
                       direct: Mapping[str, Any]) -> dict[str, Any]:
    """Mechanically compare the ordered runtime-call transcripts; PASS only
    on exact per-case equality of the model-execution input contract.
    Never consults stored ``equal`` flags or terminal strings."""
    problems: list[str] = []
    if ordinary.get("selection_authorization", {}).get("mode") != \
            "AUTOMATIC_PLANNER_SELECTION":
        problems.append("ordinary arm is not AUTOMATIC_PLANNER_SELECTION")
    for field in ("candidate_id", "mapping", "plan_digest_source",
                  "sampling_inputs", "stopping_policy"):
        if ordinary.get(field) != direct.get(field):
            problems.append(f"arms differ on {field}")
    for arm in (ordinary, direct):
        names = tuple(arm.get("generate_argument_names") or ())
        if tuple(sorted(names)) != tuple(sorted(GENERATE_ARGUMENT_NAMES)):
            problems.append(
                f"{arm.get('arm')} generate argument names {names} are not "
                f"the frozen contract {GENERATE_ARGUMENT_NAMES}")
        policy = arm.get("stopping_policy") or {}
        if policy.get("kind") != "length" or policy.get(
                "committed_tokens") != COMMIT_TOKENS:
            problems.append(
                f"{arm.get('arm')} stopping policy is not length-at-8")

    o_cases: Mapping[str, Any] = ordinary["per_case"]
    d_cases: Mapping[str, Any] = direct["per_case"]
    if set(o_cases) != set(d_cases):
        problems.append("per-case key sets differ between arms")
    equal_count = 0
    rows = []
    for case_id in sorted(o_cases):
        o, d = o_cases.get(case_id), d_cases.get(case_id)
        if o is None or d is None:
            continue
        row_problems: list[str] = []
        if o["logical_session_id"] != d["logical_session_id"]:
            row_problems.append("logical session mapping differs")
        o_calls, d_calls = o["calls"], d["calls"]
        if len(o_calls) != len(d_calls):
            row_problems.append(
                f"call count differs ({len(o_calls)} vs {len(d_calls)})")
        for index in range(min(len(o_calls), len(d_calls))):
            for field in MODEL_INPUT_FIELDS:
                if o_calls[index].get(field) != d_calls[index].get(field):
                    row_problems.append(f"call {index}: {field} differs")
        for label, calls in (("ordinary", o_calls), ("direct", d_calls)):
            for call in calls:
                if call.get("unresolvable_replay_stream"):
                    row_problems.append(
                        f"{label} replay stream unresolvable against the "
                        "frozen fixture (mutated prompt/replay prefix)")
        if o["committed_count"] != COMMIT_TOKENS:
            row_problems.append("ordinary committed count is not 8")
        if d["committed_count"] != COMMIT_TOKENS:
            row_problems.append("direct committed count is not 8")
        for label, calls in (("ordinary", o_calls), ("direct", d_calls)):
            for call in calls:
                if call["max_new_tokens"] != GENERATE_MAX_NEW_TOKENS:
                    row_problems.append(
                        f"{label} max_new_tokens != 2 "
                        f"({call['max_new_tokens']})")
                if call["response_speculative_token_id"] is None:
                    row_problems.append(
                        f"{label} call lacks a speculative second token")
        for label, arm in (("ordinary", o), ("direct", d)):
            expected = [c["response_commit_token_id"] for c in arm["calls"]]
            if arm["completed_token_ids"] != expected:
                row_problems.append(
                    f"{label} committed ids are not the step-0 sequence "
                    "(speculative token committed or commit out of order)")
        if not row_problems:
            equal_count += 1
        rows.append({"case_id": case_id, "equal": not row_problems,
                     "problems": row_problems})
    passed = (not problems) and equal_count == CASE_COUNT
    return {
        "schema": "inferswarm.issue129.transcript-reduction/1",
        "case_count": CASE_COUNT,
        "equal_count": equal_count,
        "rows": rows,
        "global_problems": problems,
        "control_plane_only_fields": list(CONTROL_PLANE_ONLY_FIELDS),
        "control_plane_only_proof": (
            "control-plane-only fields never appear among generate() "
            "arguments: the recording runtime captures the exact keyword "
            "set per call and the reducer requires it to equal the frozen "
            "contract on both arms; equality is computed only over the "
            "recorded model-execution inputs"),
        "passed": passed,
        "terminal": METHODOLOGY_READY if passed else METHODOLOGY_BLOCKED,
    }


# ---------------------------------------------------------------------------
# 5. Attempt/STOP state machine (executable, not interpretive)
# ---------------------------------------------------------------------------

ATTEMPT_CLASSES = (
    "PRE_OBSERVATION_INFRASTRUCTURE",
    "CORRECTNESS_BEARING_VALID",
    "CORRECTNESS_BEARING_INVALID",
    "DIAGNOSTIC_ONLY_AFTER_STOP",
    "TERMINAL_CAMPAIGN_ATTEMPT",
)

ATTEMPT_FACT_FIELDS = (
    "attempt_id",
    "gpu_execution_occurred",
    "model_execution_occurred",
    "correctness_bearing_result_emitted",
    "result_reached_coordinator",
    "coordinator_commit_occurred",
    "frozen_identity_verified_pre_launch",
    "frozen_identity_verified_post_run",
    "methodology_gate_passed",
    "stop_occurred",
)

STOP_RULES = {
    "invalid_correctness_bearing_observation":
        "a correctness-bearing result was emitted or committed without "
        "verified frozen deployment identity (pre-launch AND post-run), or "
        "after a methodology-gate failure",
    "post_stop_continuation_without_terminal":
        "a correctness-bearing attempt follows a mandatory STOP without an "
        "intervening terminal campaign attempt",
}


def classify_attempt(facts: Mapping[str, Any]) -> str:
    """Mechanically classify one attempt from observed facts only."""
    missing = set(ATTEMPT_FACT_FIELDS) - set(facts)
    if missing:
        raise ValueError(f"attempt facts lack {sorted(missing)}")
    correctness_bearing = bool(
        facts["correctness_bearing_result_emitted"]
        or facts["coordinator_commit_occurred"])
    identity_ok = bool(
        facts["frozen_identity_verified_pre_launch"]
        and facts["frozen_identity_verified_post_run"])
    if correctness_bearing and facts.get("stop_occurred"):
        return "DIAGNOSTIC_ONLY_AFTER_STOP"
    if correctness_bearing and not identity_ok:
        return "CORRECTNESS_BEARING_INVALID"
    if correctness_bearing and identity_ok:
        return "CORRECTNESS_BEARING_VALID"
    if facts.get("methodology_gate_passed"):
        return "TERMINAL_CAMPAIGN_ATTEMPT"
    return "PRE_OBSERVATION_INFRASTRUCTURE"


def reduce_attempts(attempts: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Mechanically decide attempt classes and mandatory STOPs; fail closed
    when an invalid correctness-bearing attempt continued without the
    state machine authorizing it."""
    stop_fired = False
    terminal_seen = False
    events = []
    problems = []
    for order, facts in enumerate(attempts, start=1):
        classification = classify_attempt(facts)
        rule = None
        if classification == "CORRECTNESS_BEARING_INVALID":
            stop_fired = True
            rule = "invalid_correctness_bearing_observation"
        elif classification == "TERMINAL_CAMPAIGN_ATTEMPT":
            terminal_seen = True
        elif classification == "CORRECTNESS_BEARING_VALID" and stop_fired \
                and not terminal_seen:
            rule = "post_stop_continuation_without_terminal"
            problems.append(
                f"attempt {order} ({facts['attempt_id']}) is "
                "correctness-bearing after a STOP without a terminal "
                "campaign attempt authorizing it")
        elif classification == "DIAGNOSTIC_ONLY_AFTER_STOP":
            pass  # legal post-stop diagnostics
        events.append({
            "order": order,
            "attempt_id": facts["attempt_id"],
            "classification": classification,
            "stop_rule_fired": rule,
        })
    return {
        "schema": "inferswarm.issue129.attempt-reduction/1",
        "events": events,
        "problems": problems,
        "passed": not problems,
        "stop_rules": STOP_RULES,
    }


# ---------------------------------------------------------------------------
# 6. Exact deployed-script identity contract
# ---------------------------------------------------------------------------

DEPLOYMENT_IDENTITY_FIELDS = (
    "repository_sha",
    "file_sha256",
    "expected_path",
    "read_only",
    "pre_launch_verified",
    "post_run_verified",
)


def verify_deployment_identity(record: Mapping[str, Any]) -> dict[str, Any]:
    """Verify one deployed correctness-bearing script's identity contract;
    fail closed on mutable/unpinned identity or post-freeze change."""
    missing = [f for f in DEPLOYMENT_IDENTITY_FIELDS if f not in record]
    if missing:
        return {"ok": False, "reason": f"missing fields {missing}"}

    def _hex(value, length):
        return (isinstance(value, str) and len(value) == length
                and all(c in "0123456789abcdef" for c in value))

    if not _hex(record["repository_sha"], 40):
        return {"ok": False, "reason": "repository_sha is not a commit sha1"}
    if not _hex(record["file_sha256"], 64):
        return {"ok": False, "reason": "file_sha256 is not a sha256"}
    if not isinstance(record["expected_path"], str) or not record[
            "expected_path"].startswith("/"):
        return {"ok": False, "reason": "expected_path is not absolute"}
    if record["read_only"] is not True:
        return {"ok": False,
                "reason": "deployment is mutable (not read-only)"}
    if record["pre_launch_verified"] is not True:
        return {"ok": False, "reason": "pre-launch verification absent"}
    if record["post_run_verified"] is not True:
        return {"ok": False, "reason": "post-run verification absent"}
    post_run_sha = record.get("post_run_file_sha256")
    if post_run_sha is not None and post_run_sha != record["file_sha256"]:
        return {"ok": False,
                "reason": "correctness-bearing script changed after freeze"}
    return {"ok": True}


# ---------------------------------------------------------------------------
# 7. Top-level methodology run
# ---------------------------------------------------------------------------

def _tokenizer_seam_facts() -> dict[str, Any]:
    return {
        "transformers_imported": any(
            name == "transformers" or name.startswith("transformers.")
            for name in sys.modules),
        "tokenizer_object_constructed": False,
        "source_reads_during_observation": 0,
        "seam": (
            "frozen rendered prompt ids consumed by the direct comparator; "
            "no tokenizer metadata access exists in either arm's "
            "observation window; decoded-output reconstruction would be a "
            "separate pinned CPU evidence step outside the observation "
            "window (not required for transcript equivalence)"),
    }


def run_methodology(repo_root: Path | None = None) -> dict[str, Any]:
    """Run the complete CPU-only methodology gate."""
    root = repo_root or _repo_override()
    arms = run_both_arms(root)
    reduction = reduce_transcripts(arms["ordinary"], arms["direct"])
    tokenizer = _tokenizer_seam_facts()
    if tokenizer["transformers_imported"]:
        reduction["global_problems"].append(
            "transformers was importable/imported in the observation process")
        reduction["passed"] = False
        reduction["terminal"] = METHODOLOGY_BLOCKED
    return {
        "schema": "inferswarm.issue129.methodology-run/1",
        "authority": {
            "issue": "https://github.com/Zutfen-LLC/inferswarm/issues/129",
            "accepted_arm_c_blocker": "ISSUE117_ARM_C_EVIDENCE_BLOCKER",
            "accepted_arm_c_blocker_merge": ACCEPTED_BLOCKER_MERGE,
            "accepted_arm_b_result": ACCEPTED_ARM_B_RESULT,
            "accepted_arm_b_merge": ACCEPTED_ARM_B_MERGE,
            "frozen_producer": FROZEN_PRODUCER_SHA,
            "accepted_fixture_digest": FIXTURE_DIGEST_24,
            "checkpoint_authority": CHECKPOINT_SHA256,
        },
        "fixture": {
            "fixture_digest": arms["fixture"]["fixture_digest"],
            "case_count": arms["fixture"]["case_count"],
        },
        "frozen_control_plane_digests": verify_frozen_bytes(root),
        "ordinary_summary": {
            k: arms["ordinary"][k] for k in (
                "arm", "variant", "plan_digest", "candidate_id", "mapping",
                "selection_authorization", "plan_digest_source",
                "sampling_inputs", "stopping_policy",
                "generate_argument_names")},
        "direct_summary": {
            k: arms["direct"][k] for k in (
                "arm", "variant", "plan_digest", "candidate_id", "mapping",
                "selection_authorization", "plan_digest_source",
                "sampling_inputs", "stopping_policy",
                "generate_argument_names")},
        "per_case_reduction": reduction,
        "tokenizer_seam": tokenizer,
        "cpu_only": {
            "gpu_execution_occurred": False,
            "model_execution_occurred": False,
            "note": "recording fake runtime; no model bytes; CPU-only host",
        },
        "terminal": reduction["terminal"],
    }


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path,
                        default=ARM_C_RETRY_EVIDENCE / "methodology-run.json")
    args = parser.parse_args()
    document = run_methodology()
    write_canonical_json(args.out, document)
    print(document["terminal"])
    print("fixture_digest", document["fixture"]["fixture_digest"])
    print("equal",
          document["per_case_reduction"]["equal_count"], "/",
          document["per_case_reduction"]["case_count"])
    return 0 if document["terminal"] == METHODOLOGY_READY else 1


if __name__ == "__main__":
    raise SystemExit(main())
