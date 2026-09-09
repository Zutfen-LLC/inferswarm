#!/usr/bin/env python3
"""Issue #129 — Arm-C retry methodology core (CPU-only; no GPU/model execution).

Implements the control-plane-only comparator-equivalence proof required by
issue #129 before any future Arm-C physical retry can be authorized:

1.  Imports the REAL frozen control-plane modules verbatim from retained
    producer bytes. The accepted #128 bytes stay under
    ``evidence/arm-c/frozen-freetoken/924cd22e/``. The three #129-only
    bytes stay under ``evidence/arm-c-retry/frozen-source/924cd22e/``.
    These modules include the generic planner ``freetoken.research.r3_planner``,
    the plan/realization machinery ``freetoken.research.r5a_serving``,
    the epoch controller ``freetoken.research.r5b_epochs``, and the R6
    dense strategy adapters ``benchmarks.inferswarm_r6.{strategy,
    xc_strategy}``). Every imported byte is sha256-pinned: the accepted
    #128-pinned files (``r5b_epochs.py``, ``xc_strategy.py``) are
    cross-checked, fail-closed, through
    ``scripts/issue117_arm_c_frozen_pins.py``; the files added by #129
    (``r3_planner.py``, ``r5a_serving.py``, ``strategy.py``) are pinned
    by this module. No FreeToken working checkout is used.

2.  Derives the frozen 24-case rendered-prompt-token fixture from
    retained ACCEPTED Arm-C evidence (read-only): the exact chat-rendered
    prompt token ids per case, cross-derived from BOTH retained accepted
    sides (direct-run results and the ordinary coordinator per-request
    records), with per-case sha256 and a fixture digest. The retry
    direct comparator consumes these frozen ids; no tokenizer/Source
    read exists at observation time.

3.  Exercises the actual ordinary Coordinator ingress/tokenizer seam
    (``R6CoordinatorRuntime.handle_chat``): the render/tokenize and
    sampling functions are MECHANICALLY EXTRACTED, verbatim, from the
    sha256-pinned frozen Coordinator bytes (AST extraction with
    fail-closed structural verification), and the ``handle_chat``
    ingress statements (session allocation, max-token derivation,
    sampling derivation, the ``serve_tokens(prompt_token_ids=…)``
    dispatch) are needle-verified in the pinned bytes with recorded
    line citations. The exact ordinary request bodies are reconstructed
    and verified equal (parsed-JSON equality) against the retained
    accepted ordinary-http records; rendering runs through the
    extracted frozen function against the real tokenizer loaded by
    ``AutoTokenizer.from_pretrained`` from five retained local assets.
    The exact package versions are frozen. The derived prompt ids must
    equal the frozen fixture 24/24 before the ordinary arm may serve
    them. A reconstructed tokenizer remains only as a mutation helper.

4.  Runs, entirely on CPU with a recording/fake runtime, both arms over
    all 24 frozen cases:

    - ORDINARY: the real ``EpochServingController`` — real planner
      decision (AUTOMATIC_PLANNER_SELECTION), real
      ``freeze_execution_plan``, real realization reconciliation, real
      ``serve_tokens`` replay-prefix loop — driven through a realizer
      that returns the recording runtime, fed by the ingress-derived
      ordinary prompt ids. Every runtime ``generate`` call is recorded.
    - DIRECT: an independently coded comparator that mechanically
      reproduces the ordinary controller's runtime invocation contract
      (per committed position: replay prefix = prompt + committed ids,
      one ``generate(max_new_tokens=2)`` call, commit the step-0 token,
      discard the speculative step-1 token; repeat until 8 committed),
      INCLUDING the frozen controller's runtime-session allocation,
      which is mechanically extracted from the pinned
      ``r5b_epochs.py`` bytes — never hand-copied. Mutator variants
      for the mandatory negative controls are selected by ``variant``.

    Both arms share one deterministic fake model response function
    seeded from the frozen fixture bytes, so equivalence is a property
    of the two control-plane paths, not of model outputs.

5.  Compares the ordered runtime-call transcripts mechanically and
    fail-closed (``reduce_transcripts``): case identity, call count and
    position, the COMPLETE ``generate()`` argument values — runtime
    ``session_id`` (the exact keyword value; it is part of the
    model-execution invocation, never a control-plane-only field),
    prompt/replay token ids, ``max_new_tokens``, ``on_token``
    presence, and the exact generate-argument name set — plus
    commit/discard semantics, committed counts, sampling and stopping
    contracts. Genuinely control-plane-only fields (epoch ids,
    generation counters, realization ids, the plan-digest VALUE,
    logical session numbering, wall stamps) are enumerated explicitly
    and proven outside the generate() argument set. Stored ``equal``
    flags or terminal strings are never consulted.

6.  Exposes an executable attempt/STOP state machine
    (``classify_attempt`` / ``reduce_attempts``) that mechanically
    separates methodology readiness, physical-retry authorization,
    correctness-bearing state, deployment-identity validity, the
    mandatory STOP state, and terminal campaign observations. Each
    attempt carries campaign, physical authorization, methodology, and
    execution-freeze identities. A correctness-bearing invalid attempt
    permanently blocks its campaign. Later observations in that
    campaign are diagnostic only and cannot clear the STOP. A new
    campaign needs a fresh lineage root and an authorization issued
    after the recorded STOP and maintainer review. The reducer binds
    every campaign to a separate accepted authority record. It requires
    an authoritative terminal attempt before the campaign can pass.

7.  Exposes the exact deployed-script identity contract
    (``verify_deployment_identity``): repository SHA + file sha256 +
    expected path + read-only deployment + pre/post verification,
    rejecting mutable/unpinned staged drivers and post-freeze script
    changes.

8.  Freezes the tokenizer Source rule for the future physical retry
    (``verify_tokenizer_asset_contract``): the exact immutable
    tokenizer/config assets the Coordinator needs (with sha256 pins
    derived from the accepted checkpoint-authority provenance) must be
    published to a dedicated non-Source location and
    ``tokenizer_path`` pointed there BEFORE the observation window;
    digests must be verified pre-window; zero opens under the
    forbidden Source root (``/srv/models/``) may occur during the
    observation window (audited mechanically via a ``sys.addaudithook``
    monitor in this CPU run; a simulated forbidden open downgrades the
    terminal to BLOCKED). The methodology does NOT hinge on any
    assumption that ``transformers`` is absent — the Coordinator
    legitimately uses a tokenizer.

9.  Proves the accepted #128 blocker evidence is preserved byte-exact
    (``verify_accepted_blocker_preservation``): every evidence path
    that existed under ``evidence/arm-c/`` at the accepted merge
    ``718efbf…`` must remain byte-identical in the working tree. The
    accepted blocker is immutable historical authority; all #129
    authority lives additively under ``evidence/arm-c-retry/``.

No GPU execution, no model execution, no holdout use, no mutation of
accepted Arm-B participant state. The accepted #128 blocker evidence is
read-only input.
"""
from __future__ import annotations

import ast
import hashlib
import importlib.metadata
import importlib.util
import json
import os
import subprocess
import sys
import types
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
AREA = ROOT / "docs/implementation/r6-successor-dense-full-integration-117"
ARM_C_EVIDENCE = AREA / "evidence" / "arm-c"
ARM_C_RETRY_EVIDENCE = AREA / "evidence" / "arm-c-retry"
ACCEPTED_FROZEN_PREFIX = "frozen-freetoken/924cd22e/"
RETRY_FROZEN_PREFIX = "frozen-source/924cd22e/"
TOKENIZER_ROOT = ARM_C_RETRY_EVIDENCE / "frozen-tokenizer"
TOKENIZER_ASSET_DIR = TOKENIZER_ROOT / "assets"

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
#: runtime-invocation argument set (never among generate() arguments).
#: The runtime ``session_id`` is deliberately NOT here: it is a
#: generate() keyword value and is compared exactly in the transcript.
CONTROL_PLANE_ONLY_FIELDS = (
    "epoch_id",
    "generation",
    "realization_id",
    "plan_digest_value",
    "logical_session_id",
    "wall_ns",
)

#: forbidden Source root for the future observation window (frozen
#: #128 zero-Source rule; the accepted campaign observed four
#: tokenizer-metadata reads under this root)
FORBIDDEN_SOURCE_ROOT = "/srv/models/"

#: accepted identity of the Source tokenizer the Coordinator's
#: ``tokenizer_path`` pointed at during the accepted campaign
SOURCE_TOKENIZER_PATH = "/srv/models/gemma-r6"


def _repo_override() -> Path:
    env = os.environ.get("ARM_C_RETRY_REPO")
    return Path(env) if env else ROOT


def _accepted_merge_override() -> str:
    return os.environ.get("ARM_C_RETRY_ACCEPTED_MERGE",
                          ACCEPTED_BLOCKER_MERGE)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_canonical_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


# ---------------------------------------------------------------------------
# 1. Frozen producer bytes: fail-closed pins + import
# ---------------------------------------------------------------------------

#: Every frozen control-plane byte this methodology touches. A local pin
#: identifies a #129-only byte retained under the additive retry area.
#: ``None`` identifies an accepted #128 byte that stays in its historical
#: namespace and delegates its pin to the accepted #128 pins module.
#: (scripts/issue117_arm_c_frozen_pins.py): the key must exist there,
#: the value must be a valid sha256, and the retained bytes must equal
#: it. Any import failure, missing key, malformed digest, or mismatch
#: fails closed — an absent pins module never silently degrades to an
#: empty pin set.
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
    "benchmarks/inferswarm_r6/coordinator.py": None,
}

_SHA256_HEX = set("0123456789abcdef")


def _is_sha256(value: object) -> bool:
    return (isinstance(value, str) and len(value) == 64
            and all(c in _SHA256_HEX for c in value))


def _is_git_sha(value: object) -> bool:
    return (isinstance(value, str) and len(value) == 40
            and all(c in _SHA256_HEX for c in value))


def load_inherited_pins(repo_root: Path) -> dict[str, str]:
    """Load the accepted #128 pins module; fail closed on ANY defect.

    A missing file, a broken module, a missing ``FROZEN_SHA256``
    attribute, or a non-dict/malformed pin table raises — it never
    degrades to an empty pin set."""
    scripts = repo_root / "scripts"
    pins_path = scripts / "issue117_arm_c_frozen_pins.py"
    if not pins_path.is_file():
        raise FileNotFoundError(
            "accepted #128 pins module is missing: "
            f"{pins_path} (inherited frozen-byte pins cannot be "
            "verified; failing closed)")
    spec = importlib.util.spec_from_file_location(
        "_issue129_pins_128", pins_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load accepted #128 pins module: {pins_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # a broken module raises here
    pins = getattr(module, "FROZEN_SHA256", None)
    if not isinstance(pins, dict) or not pins:
        raise RuntimeError(
            "accepted #128 pins module carries no FROZEN_SHA256 pin "
            f"table: {pins_path}")
    for key, value in pins.items():
        if not _is_sha256(value):
            raise RuntimeError(
                f"accepted #128 pin for {key} is not a valid sha256 "
                f"(got {value!r}); failing closed")
    return dict(pins)


def verify_frozen_bytes(repo_root: Path | None = None) -> dict[str, str]:
    """Verify every retained control-plane byte against its pin;
    fail-closed (delegated #128 pins included — see
    ``load_inherited_pins``).

    Returns {retained-relative-path: sha256}."""
    root = repo_root or _repo_override()
    pins_128 = load_inherited_pins(root)
    digests = {}
    for rel, local_pin in FROZEN_CONTROL_PLANE_FILES.items():
        if local_pin is None:
            evidence_root = ARM_C_EVIDENCE
            prefix = ACCEPTED_FROZEN_PREFIX
        else:
            evidence_root = ARM_C_RETRY_EVIDENCE
            prefix = RETRY_FROZEN_PREFIX
        path = root / evidence_root.relative_to(ROOT) / prefix / rel
        if not path.is_file():
            raise FileNotFoundError(f"missing frozen producer byte: {path}")
        digest = sha256_file(path)
        if local_pin is not None and digest != local_pin:
            raise RuntimeError(f"frozen byte drift against #129 pin: {rel}")
        repo_rel = str((evidence_root / prefix / rel).relative_to(ROOT))
        if local_pin is None:
            # delegated to the accepted #128 pins module: the key must
            # exist, be a valid sha256 (enforced at load), and match
            pinned = pins_128.get(repo_rel)
            if pinned is None:
                raise RuntimeError(
                    f"accepted #128 pins module has no pin for {repo_rel}; "
                    "delegated frozen-byte verification fails closed")
            if digest != pinned:
                raise RuntimeError(
                    f"frozen byte drift against accepted #128 pin: {rel}")
        else:
            pinned = pins_128.get(repo_rel)
            if pinned is not None and digest != pinned:
                raise RuntimeError(
                    f"frozen byte drift against accepted #128 pin: {rel}")
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
    accepted_base = (root / ARM_C_EVIDENCE.relative_to(ROOT)
                     / ACCEPTED_FROZEN_PREFIX)
    retry_base = (root / ARM_C_RETRY_EVIDENCE.relative_to(ROOT)
                  / RETRY_FROZEN_PREFIX)
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
        retry_base / "python/freetoken/research/r3_planner.py")
    serving = _load_module(
        "freetoken.research.r5a_serving",
        retry_base / "python/freetoken/research/r5a_serving.py")
    epochs = _load_module(
        "freetoken.research.r5b_epochs",
        accepted_base / "python/freetoken/research/r5b_epochs.py")
    strategy = _load_module(
        "benchmarks.inferswarm_r6.strategy",
        retry_base / "benchmarks/inferswarm_r6/strategy.py")
    xc_strategy = _load_module(
        "benchmarks.inferswarm_r6.xc_strategy",
        accepted_base / "benchmarks/inferswarm_r6/xc_strategy.py")
    _LOADED = True
    return planner, serving, epochs, strategy, xc_strategy


_LOADED = False


# ---------------------------------------------------------------------------
# 1b. Mechanical extraction: the frozen runtime-session allocation
# ---------------------------------------------------------------------------

class FrozenRuntimeSessionAllocator:
    """The frozen controller's runtime-session allocation, built by
    MECHANICALLY EXTRACTING ``EpochServingController._runtime_session_id``
    (plus its ``__init__`` sequence-zero initialization) from the
    sha256-pinned ``r5b_epochs.py`` bytes and exec'ing the verbatim
    extracted method — the direct comparator never re-codes the
    formula by hand. The extraction structurally verifies the method
    body (one sequence increment; one return of
    ``logical_session_id * <constant> + sequence``) so a drifted
    producer byte fails closed instead of silently changing the
    comparator's allocation semantics."""

    def __init__(self, method_source: str, facts: Mapping[str, Any],
                 *, sequence_start: int = 0) -> None:
        self.facts = dict(facts)
        namespace: dict[str, Any] = {}
        text = (
            "class _FrozenRuntimeSessionAllocation:\n"
            "    _runtime_session_sequence = 0\n"
            + "\n".join("    " + line for line in method_source.splitlines())
            + "\n\n    def allocate(self, logical_session_id: int) -> int:\n"
            "        return self._runtime_session_id(logical_session_id)\n"
        )
        exec(compile(text, "<frozen-runtime-session-allocation>", "exec"),
             namespace)
        self._impl = namespace["_FrozenRuntimeSessionAllocation"]()
        # the frozen controller initializes the sequence to 0 in
        # __init__; the negative-control seam may shift it
        self._impl._runtime_session_sequence = int(sequence_start)

    def allocate(self, logical_session_id: int) -> int:
        return int(self._impl.allocate(int(logical_session_id)))


def extract_runtime_session_allocator(
        repo_root: Path | None = None, *,
        sequence_start: int = 0) -> FrozenRuntimeSessionAllocator:
    """Extract + verify the frozen runtime-session allocation from the
    pinned ``r5b_epochs.py`` bytes; return the executing allocator."""
    root = repo_root or _repo_override()
    verify_frozen_bytes(root)  # fail closed before reading
    source_path = (root / ARM_C_EVIDENCE.relative_to(ROOT)
                   / ACCEPTED_FROZEN_PREFIX
                   / "python/freetoken/research/r5b_epochs.py")
    source = source_path.read_text()
    tree = ast.parse(source)
    cls = next(
        (node for node in tree.body
         if isinstance(node, ast.ClassDef)
         and node.name == "EpochServingController"), None)
    if cls is None:
        raise RuntimeError(
            "pinned r5b_epochs.py carries no EpochServingController")
    init = next(
        (node for node in cls.body
         if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
         and node.name == "__init__"), None)
    if init is None:
        raise RuntimeError("pinned EpochServingController has no __init__")
    init_source = ast.get_source_segment(source, init) or ""
    if "self._runtime_session_sequence = 0" not in init_source:
        raise RuntimeError(
            "pinned __init__ does not zero _runtime_session_sequence; "
            "runtime-session allocation extraction fails closed")
    fn = next(
        (node for node in cls.body
         if isinstance(node, ast.FunctionDef)
         and node.name == "_runtime_session_id"), None)
    if fn is None:
        raise RuntimeError(
            "pinned EpochServingController has no _runtime_session_id; "
            "the runtime-session allocation contract cannot be derived")
    segment = ast.get_source_segment(source, fn)
    if segment is None:
        raise RuntimeError("cannot extract _runtime_session_id source")
    # structural verification of the extracted body: exactly one
    # sequence increment followed by one return of
    # logical_session_id * <numeric constant> + sequence
    body = fn.body
    if len(body) != 2 or not isinstance(body[0], ast.AugAssign) \
            or not isinstance(body[1], ast.Return):
        raise RuntimeError(
            "extracted _runtime_session_id does not have the frozen "
            "increment+return structure; allocation extraction fails "
            "closed")
    ret = body[1].value
    if not (isinstance(ret, ast.BinOp) and isinstance(ret.op, ast.Add)
            and isinstance(ret.left, ast.BinOp)
            and isinstance(ret.left.op, ast.Mult)
            and isinstance(ret.left.left, ast.Name)
            and ret.left.left.id == "logical_session_id"
            and isinstance(ret.left.right, ast.Constant)
            and isinstance(ret.left.right.value, int)):
        raise RuntimeError(
            "extracted _runtime_session_id return is not "
            "logical_session_id * <int> + <sequence>; allocation "
            "extraction fails closed")
    multiplier = ret.left.right.value
    facts = {
        "source_sha256": sha256_bytes(source.encode()),
        "method_sha256": sha256_bytes(segment.encode()),
        "method_line": fn.lineno,
        "multiplier": multiplier,
        "derivation": (
            "verbatim AST extraction of "
            "EpochServingController._runtime_session_id from the "
            "sha256-pinned r5b_epochs.py bytes (structure verified: "
            "one sequence increment; return logical_session_id * "
            f"{multiplier} + sequence; sequence zeroed in __init__); "
            "the direct comparator allocates through this extracted "
            "method, never through a hand-copied formula"),
    }
    return FrozenRuntimeSessionAllocator(
        segment, facts, sequence_start=sequence_start)


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
    # prefix-disambiguation property the recording runtime relies on: no
    # frozen rendered prompt may be a prefix of another (else longest-
    # prefix replay-stream matching could be ambiguous). Mechanical,
    # fail-closed.
    prompts = [tuple(row["rendered_prompt_token_ids"]) for row in rows]
    for i, a in enumerate(prompts):
        for j, b in enumerate(prompts):
            if i != j and len(a) <= len(b) and list(a) == list(b)[:len(a)]:
                raise RuntimeError(
                    f"frozen rendered prompt {rows[i]['case_id']} is a "
                    f"prefix of {rows[j]['case_id']} (ambiguous replay "
                    "matching)")
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
# 2b. The frozen ordinary Coordinator ingress/tokenizer seam
# ---------------------------------------------------------------------------

#: the exact ordinary request-body construction of the accepted
#: campaign (verified byte-equal against the retained ordinary-http
#: records at proof time; never trusted from these constants alone)
ORDINARY_REQUEST_MODEL = "gemma-4-12B-it"
ORDINARY_REQUEST_MAX_TOKENS = 8
ORDINARY_REQUEST_TEMPERATURE = 0.0

#: chat-template wrapper token sequences of the frozen gemma-r6
#: tokenizer, cross-derived from BOTH accepted campaign sides for all
#: 24 cases (verified mechanically by ``derive_template_contract``)
CHAT_TEMPLATE_HEADER_TOKEN_IDS = (2, 105, 2364, 107)
CHAT_TEMPLATE_FOOTER_TOKEN_IDS = (
    106, 107, 105, 4368, 107, 100, 45518, 107, 101)

#: the SentencePiece space piece: a content string ending in a space
#: has its trailing space piece absorbed at the ``<end_of_turn>``
#: template boundary (the one boundary-merge case in the frozen
#: corpus, present identically on BOTH accepted sides)
TRAILING_SPACE_PIECE = 236743

#: stand-in literals for the frozen template's prefix/suffix text.
#: The real template text lives in the Source-pinned
#: chat_template.jinja; CPU-only, its characters are NOT asserted —
#: what is pinned and cross-derived is its TOKEN ENCODING (the
#: header/footer sequences above). encode() recognizes exactly these
#: sentinels, so no text↔id claim beyond the pin is made.
_TEMPLATE_PREFIX_SENTINEL = "\ue000"
_TEMPLATE_SUFFIX_SENTINEL = "\ue001"


def derive_template_contract(repo_root: Path | None = None) -> dict[str, Any]:
    """Mechanically derive the frozen chat-template wrapper contract
    from BOTH retained accepted sides: for every case,
    ``rendered == HEADER + content_ids + FOOTER`` where content ids are
    the accepted fixture ids with the trailing-space piece dropped iff
    the content string ends with a space. Any deviation fails closed."""
    root = repo_root or _repo_override()
    base = root / ARM_C_EVIDENCE.relative_to(ROOT)
    fixture = derive_prompt_fixture(root)
    integration = json.loads(
        (root / AREA.relative_to(ROOT) / "evidence" / "integration-fixture.json"
         ).read_text())
    prompt_texts = {
        row["case"]["case_id"]: row["case"]["prompt_text"]
        for row in integration["cases"]}
    direct = json.loads((base / "direct-run.json").read_text())
    direct_by_case = {row["case_id"]: row for row in direct["results"]}
    header = list(CHAT_TEMPLATE_HEADER_TOKEN_IDS)
    footer = list(CHAT_TEMPLATE_FOOTER_TOKEN_IDS)
    trailing_space_cases: list[str] = []
    for row in fixture["cases"]:
        case_id = row["case_id"]
        rendered = list(row["rendered_prompt_token_ids"])
        raw = list(row["raw_fixture_token_ids"])
        text = prompt_texts[case_id]
        candidates = [header + raw + footer]
        if text.endswith(" ") and raw and raw[-1] == TRAILING_SPACE_PIECE:
            candidates.insert(0, header + raw[:-1] + footer)
            trailing_space_cases.append(case_id)
        if rendered not in candidates:
            raise RuntimeError(
                f"{case_id}: accepted rendered ids do not match the "
                "header+content+footer wrapper structure on the "
                "ordinary side; template-contract derivation fails "
                "closed")
        direct_rendered = list(direct_by_case[case_id]["prompt_token_ids"])
        if direct_rendered != rendered:
            raise RuntimeError(
                f"{case_id}: accepted direct-side render differs from "
                "the ordinary side; template-contract derivation fails "
                "closed")
    return {
        "schema": "inferswarm.issue129.template-contract/1",
        "header_token_ids": header,
        "footer_token_ids": footer,
        "trailing_space_piece": TRAILING_SPACE_PIECE,
        "trailing_space_cases": sorted(trailing_space_cases),
        "derivation": (
            "cross-derived from BOTH retained accepted sides: every "
            "case's rendered ids equal HEADER + content + FOOTER with "
            "content = accepted fixture ids (trailing-space piece "
            "absorbed at the template boundary iff the content string "
            "ends with a space); identical on the direct and ordinary "
            "sides"),
        "contract_sha256": "sha256:" + sha256_bytes(json.dumps({
            "header": header, "footer": footer,
            "trailing_space_piece": TRAILING_SPACE_PIECE,
        }, sort_keys=True).encode()),
    }


class FrozenSourceTokenizerStandIn:
    """CPU-only stand-in for ``AutoTokenizer.from_pretrained(
    tokenizer_path)`` on the frozen Source tokenizer.

    The real tokenizer assets live under the forbidden Source root
    (``/srv/models/gemma-r6``); their identities are pinned by sha256
    (see ``tokenizer_asset_contract``) but their bytes are never read
    here. The stand-in implements EXACTLY the two methods the frozen
    Coordinator seam calls:

    - ``apply_chat_template(messages, tokenize=False,
      add_generation_prompt=True, **ctk)`` — composes the frozen
      chat-template structure around the message content (prefix +
      content + suffix; sentinel literals whose token encodings are the
      pinned header/footer sequences);
    - ``encode(prompt, add_special_tokens=False)`` — maps the composed
      prompt to ids through the pinned wrapper plus the accepted
      per-case content encodings (with the cross-derived
      trailing-space boundary rule).

    Any text outside the pin (a mutated body, a mutated template)
    fails closed; this stand-in can never silently invent an encoding.
    """

    def __init__(self, template: Mapping[str, Any],
                 content_encodings: Mapping[str, Sequence[int]],
                 *, footer_mutator=None, content_mutator=None) -> None:
        self.template = dict(template)
        self.content_encodings = {
            text: list(ids) for text, ids in content_encodings.items()}
        self._footer_mutator = footer_mutator
        self._content_mutator = content_mutator
        self.encode_failures: list[str] = []

    def _header_ids(self) -> list[int]:
        return list(self.template["header_token_ids"])

    def _footer_ids(self) -> list[int]:
        footer = list(self.template["footer_token_ids"])
        if self._footer_mutator is not None:
            footer = list(self._footer_mutator(footer))
        return footer

    def _content_ids(self, text: str) -> list[int] | None:
        ids = self.content_encodings.get(text)
        if ids is None:
            return None
        ids = list(ids)
        if (text.endswith(" ") and ids
                and ids[-1] == self.template["trailing_space_piece"]):
            ids = ids[:-1]
        if self._content_mutator is not None:
            ids = list(self._content_mutator(text, ids))
        return ids

    def apply_chat_template(self, messages, *, tokenize=False,
                            add_generation_prompt=True, **ctk) -> str:
        if tokenize is not False:
            raise RuntimeError(
                "frozen coordinator seam calls apply_chat_template with "
                "tokenize=False; stand-in refuses tokenize=True")
        if add_generation_prompt is not True:
            raise RuntimeError(
                "frozen coordinator seam calls apply_chat_template with "
                "add_generation_prompt=True; stand-in refuses otherwise")
        if ctk:
            raise RuntimeError(
                "frozen ordinary bodies carry no chat_template_kwargs; "
                "stand-in refuses unexpected template kwargs")
        if (not isinstance(messages, list) or len(messages) != 1
                or not isinstance(messages[0], dict)
                or messages[0].get("role") != "user"
                or not isinstance(messages[0].get("content"), str)):
            raise RuntimeError(
                "frozen ordinary bodies are single user messages; "
                "stand-in refuses any other message shape")
        return (_TEMPLATE_PREFIX_SENTINEL + messages[0]["content"]
                + _TEMPLATE_SUFFIX_SENTINEL)

    def encode(self, text: str, *, add_special_tokens=False) -> list[int]:
        if add_special_tokens is not False:
            raise RuntimeError(
                "frozen coordinator seam calls encode with "
                "add_special_tokens=False; stand-in refuses otherwise")
        if (not isinstance(text, str)
                or not text.startswith(_TEMPLATE_PREFIX_SENTINEL)
                or not text.endswith(_TEMPLATE_SUFFIX_SENTINEL)
                or text.count(_TEMPLATE_PREFIX_SENTINEL) != 1
                or text.count(_TEMPLATE_SUFFIX_SENTINEL) != 1):
            self.encode_failures.append("unrecognized prompt structure")
            raise RuntimeError(
                "encode: prompt is not the frozen template composition "
                "(mutated rendering); failing closed")
        content = text[len(_TEMPLATE_PREFIX_SENTINEL):
                       len(text) - len(_TEMPLATE_SUFFIX_SENTINEL)]
        ids = self._content_ids(content)
        if ids is None:
            self.encode_failures.append(f"unpinned content: {content!r}")
            raise RuntimeError(
                "encode: content is outside the pinned accepted "
                "encodings; failing closed")
        return self._header_ids() + ids + self._footer_ids()


#: exact ingress statements of the frozen ``handle_chat`` that bind the
#: ordinary seam (verified verbatim in the pinned bytes, with line
#: citations recorded)
COORDINATOR_INGRESS_LINES = {
    "render_call":
        "prompt_ids = self._render_and_tokenize(body)",
    "max_tokens_derivation":
        'maximum = int(body.get("max_tokens") or DEFAULT_MAX_OUTPUT_TOKENS)',
    "max_tokens_guard":
        'if maximum < 1:',
    "sampling_call":
        "sampling = self._sampling_of(body)",
    "session_allocation":
        "session_id = len(self.request_log) + 1",
    "serve_dispatch":
        "completed = self.controller.serve_tokens(",
    "serve_session_arg":
        "session_id=session_id,",
    "serve_prompt_arg":
        "prompt_token_ids=prompt_ids,",
    "serve_max_arg":
        "max_new_tokens=maximum,",
    "serve_sampling_arg":
        "sampling_inputs=sampling,",
}


def extract_coordinator_ingress(
        repo_root: Path | None = None) -> dict[str, Any]:
    """Mechanically extract the frozen Coordinator's render/tokenize and
    sampling functions (verbatim AST source segments) and verify the
    ``handle_chat`` ingress statements, all from the sha256-pinned
    ``coordinator.py`` bytes. Returns the executing render/sampling
    seam plus citations. Fail-closed on any drift."""
    root = repo_root or _repo_override()
    verify_frozen_bytes(root)
    source_path = (root / ARM_C_EVIDENCE.relative_to(ROOT)
                   / ACCEPTED_FROZEN_PREFIX
                   / "benchmarks/inferswarm_r6/coordinator.py")
    source = source_path.read_text()
    tree = ast.parse(source)
    cls = next(
        (node for node in tree.body
         if isinstance(node, ast.ClassDef)
         and node.name == "R6CoordinatorRuntime"), None)
    if cls is None:
        raise RuntimeError(
            "pinned coordinator.py carries no R6CoordinatorRuntime")
    segments: dict[str, str] = {}
    citations: dict[str, dict[str, Any]] = {}
    for name, expect_static in (("_render_and_tokenize", False),
                                ("_sampling_of", True)):
        fn = next(
            (node for node in cls.body
             if isinstance(node, ast.FunctionDef) and node.name == name),
            None)
        if fn is None:
            raise RuntimeError(
                f"pinned R6CoordinatorRuntime has no {name}; the "
                "ordinary ingress seam cannot be extracted")
        segment = ast.get_source_segment(source, fn)
        if segment is None:
            raise RuntimeError(f"cannot extract {name} source segment")
        decorators = [
            d.id for d in fn.decorator_list
            if isinstance(d, ast.Name)]
        if expect_static and "staticmethod" not in decorators:
            raise RuntimeError(
                f"pinned {name} is not a staticmethod; extraction "
                "assumption violated")
        if not expect_static and decorators:
            raise RuntimeError(
                f"pinned {name} unexpectedly decorated: {decorators}")
        segments[name] = segment
        citations[name] = {
            "line": fn.lineno,
            "source_sha256": sha256_bytes(segment.encode()),
            "decorators": decorators,
        }
    handle = next(
        (node for node in cls.body
         if isinstance(node, ast.FunctionDef)
         and node.name == "handle_chat"), None)
    if handle is None:
        raise RuntimeError(
            "pinned R6CoordinatorRuntime has no handle_chat; the "
            "ordinary ingress statements cannot be verified")
    handle_source = ast.get_source_segment(source, handle) or ""
    lines = source.splitlines()
    for key, needle in COORDINATOR_INGRESS_LINES.items():
        if needle not in handle_source:
            raise RuntimeError(
                f"pinned handle_chat does not contain the frozen "
                f"ingress statement for {key!r}: {needle!r}")
        line_no = next(
            (i for i, line in enumerate(lines, 1) if needle in line), None)
        if line_no is None:
            raise RuntimeError(f"cannot locate line for {needle!r}")
        citations[key] = {"line": line_no, "text": needle}
    default_max = next(
        (node for node in tree.body
         if isinstance(node, ast.Assign)
         and any(isinstance(t, ast.Name)
                 and t.id == "DEFAULT_MAX_OUTPUT_TOKENS"
                 for t in node.targets)
         and isinstance(node.value, ast.Constant)), None)
    if default_max is None:
        raise RuntimeError(
            "pinned coordinator.py does not define "
            "DEFAULT_MAX_OUTPUT_TOKENS")
    seam_class = _exec_extracted_ingress(segments)
    return {
        "seam_class": seam_class,
        "citations": citations,
        "default_max_output_tokens": default_max.value.value,
        "coordinator_source_sha256": sha256_bytes(source.encode()),
    }


def _exec_extracted_ingress(segments: Mapping[str, str]) -> type:
    """Execute the VERBATIM extracted functions as an ordinary-ingress
    seam class: the render function sees exactly the stand-in tokenizer
    through the same ``_load_tokenizer`` indirection the pinned bytes
    use; the frozen ``@staticmethod`` decorator is restored around the
    verbatim ``_sampling_of`` source (AST source segments exclude
    decorators, so the decorator is re-attached, never re-coded)."""
    text = (
        "class _FrozenCoordinatorIngress:\n"
        "    def __init__(self, tokenizer):\n"
        "        self._tokenizer = tokenizer\n"
        "    def _load_tokenizer(self):\n"
        "        return self._tokenizer\n"
        + "\n".join("    " + line
                    for line in segments["_render_and_tokenize"].splitlines())
        + "\n\n    @staticmethod\n"
        + "\n".join("    " + line
                    for line in segments["_sampling_of"].splitlines())
        + "\n"
    )
    namespace: dict[str, Any] = {
        "Mapping": Mapping, "Any": Any, "list": list, "dict": dict}
    exec(compile(text, "<frozen-coordinator-ingress>", "exec"), namespace)
    return namespace["_FrozenCoordinatorIngress"]


def _retained_ordinary_bodies(
        repo_root: Path) -> dict[str, Mapping[str, Any]]:
    """Load the retained accepted ordinary-http request records
    (the exact bodies the accepted campaign posted), keyed by case."""
    root = repo_root
    directory = root / ARM_C_EVIDENCE.relative_to(ROOT) / "ordinary-http"
    records: dict[str, Mapping[str, Any]] = {}
    for path in sorted(directory.glob("ordinary-*.json")):
        record = json.loads(path.read_text())
        if record.get("schema") != "inferswarm.issue117.arm-c.ordinary-case/1":
            continue
        records[record["case_id"]] = record
    if len(records) != CASE_COUNT:
        raise RuntimeError(
            f"expected {CASE_COUNT} retained ordinary-http records "
            f"(got {len(records)})")
    return records


def run_stand_in_ingress_proof(
        repo_root: Path | None = None, *,
        footer_mutator=None, content_mutator=None,
        body_mutator=None) -> dict[str, Any]:
    """Run the reconstructed tokenizer only as a mutation helper.

    For all 24 frozen ``c109-*`` requests: reconstruct the exact
    This helper is not authority for methodology readiness. It remains
    available for focused wrapper, content, and request-body mutations."""
    root = repo_root or _repo_override()
    fixture = derive_prompt_fixture(root)
    template = derive_template_contract(root)
    extracted = extract_coordinator_ingress(root)
    integration = json.loads(
        (root / AREA.relative_to(ROOT) / "evidence" / "integration-fixture.json"
         ).read_text())
    prompt_texts = {
        row["case"]["case_id"]: row["case"]["prompt_text"]
        for row in integration["cases"]}
    content_encodings = {
        prompt_texts[row["case_id"]]: list(row["raw_fixture_token_ids"])
        for row in fixture["cases"]}
    retained = _retained_ordinary_bodies(root)
    tokenizer = FrozenSourceTokenizerStandIn(
        template, content_encodings,
        footer_mutator=footer_mutator, content_mutator=content_mutator)
    ingress = extracted["seam_class"](tokenizer)

    rows = []
    problems: list[str] = []
    request_log: list[int] = []  # the frozen session-allocation basis
    for row in sorted(fixture["cases"], key=lambda c: c["session_index"]):
        case_id = row["case_id"]
        text = prompt_texts[case_id]
        body = {
            "model": ORDINARY_REQUEST_MODEL,
            "messages": [{"role": "user", "content": text}],
            "max_tokens": ORDINARY_REQUEST_MAX_TOKENS,
            "temperature": ORDINARY_REQUEST_TEMPERATURE,
        }
        if body_mutator is not None:
            body = dict(body_mutator(case_id, body))
        retained_record = retained.get(case_id)
        if retained_record is None:
            problems.append(f"{case_id}: no retained ordinary-http record")
            continue
        if body != retained_record["request_body"]:
            problems.append(
                f"{case_id}: reconstructed ordinary request body does "
                "not equal the retained accepted record")
        # frozen handle_chat ingress: session id from the request log
        session_id = len(request_log) + 1
        request_log.append(session_id)
        if session_id != row["session_index"]:
            problems.append(
                f"{case_id}: frozen ingress session allocation "
                f"(len(request_log)+1 = {session_id}) does not match the "
                f"frozen session index {row['session_index']}")
        maximum = int(body.get("max_tokens")
                      or extracted["default_max_output_tokens"])
        if maximum < 1:
            problems.append(f"{case_id}: frozen max-token guard rejects")
        sampling = ingress._sampling_of(body)
        if sampling != SAMPLING_INPUTS:
            problems.append(
                f"{case_id}: frozen _sampling_of derivation "
                f"{sampling} is not the frozen greedy contract")
        try:
            derived = list(ingress._render_and_tokenize(body))
        except RuntimeError as error:
            problems.append(f"{case_id}: render/tokenize failed closed: "
                            f"{error}")
            continue
        expected = list(row["rendered_prompt_token_ids"])
        equal = derived == expected
        if not equal:
            problems.append(
                f"{case_id}: ordinary Coordinator rendering does not "
                "equal the frozen prompt-token fixture")
        rows.append({
            "case_id": case_id,
            "session_index": session_id,
            "derived_equals_fixture": equal,
            "derived_prompt_token_ids": derived,
            "derived_len": len(derived),
            "fixture_len": len(expected),
        })
    return {
        "schema": "inferswarm.issue129.ordinary-ingress/1",
        "case_count": CASE_COUNT,
        "equal_count": sum(1 for r in rows if r["derived_equals_fixture"]),
        "rows": rows,
        "problems": problems,
        "passed": (not problems)
        and sum(1 for r in rows if r["derived_equals_fixture"]) == CASE_COUNT,
        "template_contract": {
            k: v for k, v in template.items() if k != "schema"},
        "coordinator_ingress_citations": extracted["citations"],
        "coordinator_source_sha256":
            extracted["coordinator_source_sha256"],
        "default_max_output_tokens":
            extracted["default_max_output_tokens"],
        "tokenizer_stand_in": {
            "class": "FrozenSourceTokenizerStandIn",
            "stands_for": "AutoTokenizer.from_pretrained("
            f"{SOURCE_TOKENIZER_PATH})",
            "asset_identities_pinned_by":
                "tokenizer_asset_contract (accepted checkpoint-authority "
                "provenance sha256 pins; bytes never read CPU-only)",
            "content_encodings_pin": (
                "accepted integration-fixture text->ids pairs; encode "
                "fails closed on any text outside the pin"),
            "encode_failures": list(tokenizer.encode_failures),
        },
        "derivation": (
            "the frozen Coordinator's _render_and_tokenize and "
            "_sampling_of are executed VERBATIM (AST-extracted from the "
            "sha256-pinned coordinator.py bytes) over the reconstructed "
            "exact ordinary request bodies; bodies verified byte-equal "
            "against the retained ordinary-http records; the stand-in "
            "tokenizer applies the cross-derived chat-template wrapper "
                "and the pinned accepted content encodings"),
    }


def run_ordinary_ingress_proof(
        repo_root: Path | None = None, *,
        asset_dir: Path | None = None,
        body_mutator=None,
        rendered_ids_mutator=None,
        installed_versions: Mapping[str, str] | None = None,
        stand_in_footer_mutator=None,
        stand_in_content_mutator=None) -> dict[str, Any]:
    """Prove the frozen Coordinator rendering with the real tokenizer.

    The proof loads only the five retained assets. It uses local-only
    loading and disables remote code. It executes the mechanically
    extracted frozen ``_render_and_tokenize`` function for all 24 exact
    retained request bodies. The reconstructed tokenizer is used only
    when a caller requests one of its mutation controls.
    """
    root = repo_root or _repo_override()
    load_directory = asset_dir or (
        root / TOKENIZER_ASSET_DIR.relative_to(ROOT))
    assets = verify_retained_tokenizer_assets(
        root, asset_dir=load_directory)
    software = verify_tokenizer_software_identity(
        root, installed_versions=installed_versions)
    try:
        from transformers import AutoTokenizer
    except ImportError as error:
        raise RuntimeError(
            "the frozen tokenizer software is not installed") from error

    fixture = derive_prompt_fixture(root)
    retained = _retained_ordinary_bodies(root)
    extracted = extract_coordinator_ingress(root)
    tokenizer = AutoTokenizer.from_pretrained(
        str(load_directory),
        local_files_only=True,
        trust_remote_code=False,
    )
    ingress = extracted["seam_class"](tokenizer)
    problems: list[str] = []
    rows = []
    request_log: list[int] = []
    for row in sorted(fixture["cases"], key=lambda c: c["session_index"]):
        case_id = row["case_id"]
        retained_record = retained.get(case_id)
        if retained_record is None:
            problems.append(f"{case_id}: no retained ordinary-http record")
            continue
        body = json.loads(json.dumps(retained_record["request_body"]))
        if body_mutator is not None:
            body = dict(body_mutator(case_id, body))
        if body != retained_record["request_body"]:
            problems.append(
                f"{case_id}: request-body drift from retained exact body")
        session_id = len(request_log) + 1
        request_log.append(session_id)
        if session_id != row["session_index"]:
            problems.append(
                f"{case_id}: frozen session allocation drift")
        maximum = int(body.get("max_tokens")
                      or extracted["default_max_output_tokens"])
        sampling = ingress._sampling_of(body)
        if maximum != ORDINARY_REQUEST_MAX_TOKENS:
            problems.append(f"{case_id}: max-token derivation drift")
        if sampling != SAMPLING_INPUTS:
            problems.append(f"{case_id}: sampling derivation drift")
        derived = list(ingress._render_and_tokenize(body))
        if rendered_ids_mutator is not None:
            derived = list(rendered_ids_mutator(case_id, derived))
        expected = list(row["rendered_prompt_token_ids"])
        equal = derived == expected
        if not equal:
            problems.append(
                f"{case_id}: real tokenizer output differs from frozen fixture")
        rows.append({
            "case_id": case_id,
            "session_index": session_id,
            "derived_equals_fixture": equal,
            "derived_prompt_token_ids": derived,
            "derived_len": len(derived),
            "fixture_len": len(expected),
        })

    stand_in_control = None
    if (stand_in_footer_mutator is not None
            or stand_in_content_mutator is not None):
        stand_in_control = run_stand_in_ingress_proof(
            root,
            footer_mutator=stand_in_footer_mutator,
            content_mutator=stand_in_content_mutator)
        if not stand_in_control["passed"]:
            problems.append(
                "reconstructed-tokenizer mutation control failed closed")

    equal_count = sum(1 for row in rows if row["derived_equals_fixture"])
    return {
        "schema": "inferswarm.issue129.real-tokenizer-ingress/1",
        "case_count": CASE_COUNT,
        "equal_count": equal_count,
        "rows": rows,
        "problems": problems,
        "passed": not problems and equal_count == CASE_COUNT,
        "tokenizer": {
            "loader": "AutoTokenizer.from_pretrained",
            "local_files_only": True,
            "trust_remote_code": False,
            "class": f"{type(tokenizer).__module__}.{type(tokenizer).__name__}",
            "assets": assets,
            "software": software,
        },
        "coordinator_ingress_citations": extracted["citations"],
        "coordinator_source_sha256":
            extracted["coordinator_source_sha256"],
        "default_max_output_tokens":
            extracted["default_max_output_tokens"],
        "stand_in_authority": False,
        **({"stand_in_mutation_control": {
            "passed": stand_in_control["passed"],
            "problems": stand_in_control["problems"],
        }} if stand_in_control is not None else {}),
        "derivation": (
            "five retained sha256-pinned assets -> AutoTokenizer.from_pretrained"
            "(local_files_only=True, trust_remote_code=False) -> frozen "
            "Coordinator _render_and_tokenize -> exact 24-case prompt fixture"),
    }


# ---------------------------------------------------------------------------
# 3. CPU recording runtime + the two arms
# ---------------------------------------------------------------------------

class RecordingRuntime:
    """Fake integrated runtime: no model, no GPU; deterministic per-case
    responses seeded from the frozen fixture bytes; records every
    correctness-relevant generate() invocation INCLUDING the exact
    ``session_id`` keyword value (a runtime-invocation argument, never
    a control-plane-only field).

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
        "runtime_session_id": call["runtime_session_id"],
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
                     repo_root: Path, *,
                     ingress_rows: Mapping[str, Mapping[str, Any]] | None = None
                     ) -> dict[str, Any]:
    """ORDINARY arm: the real EpochServingController serve_tokens loop,
    fed by the ordinary-ingress-derived prompt ids (issue #129
    Finding 3): the derivation starts at the actual frozen Coordinator
    ingress — exact request body -> extracted frozen render/tokenize ->
    derived prompt_token_ids (proven equal to the frozen fixture by
    ``run_ordinary_ingress_proof``) -> ``serve_tokens``."""
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
        case_id = case["case_id"]
        if ingress_rows is not None:
            row = ingress_rows.get(case_id)
            if row is None:
                raise RuntimeError(
                    f"{case_id}: no ordinary-ingress row; the ordinary "
                    "arm may only serve ingress-derived ids")
            prompt_ids = list(row["derived_prompt_token_ids"])
        else:
            prompt_ids = list(case["rendered_prompt_token_ids"])
        mark = len(transcript)
        completed = controller.serve_tokens(
            session_id=case["session_index"],
            prompt_token_ids=prompt_ids,
            max_new_tokens=COMMIT_TOKENS,
            sampling_inputs=dict(SAMPLING_INPUTS))
        per_case[case_id] = {
            "case_id": case_id,
            "logical_session_id": case["session_index"],
            "prompt_ids_source": ("ordinary-ingress derivation"
                                  if ingress_rows is not None
                                  else "frozen fixture"),
            "completed_token_ids": list(completed["generated_token_ids"]),
            "committed_count": len(completed["generated_token_ids"]),
            "committed_epoch_ids": list(completed["committed_epoch_ids"]),
            "committed_plan_digests": list(completed["committed_plan_digests"]),
            "calls": _public_calls(transcript[mark:], case_id),
        }
    plan = controller._epochs[0].execution_plan
    document = _arm_document(
        "ordinary", "corrected", plan, runtime, per_case)
    controller.close()
    document["controller_report_schema"] = "inferswarm.r5b.epoch-serving-report/1"
    document["runtime_session_allocation"] = dict(
        extract_runtime_session_allocator(repo_root).facts)
    return document


def run_direct_arm(planner, serving, epochs, xc_strategy, fixture,
                   repo_root: Path, *, variant: str = "corrected",
                   sampling_inputs: Mapping[str, Any] | None = None,
                   stopping_policy: Mapping[str, Any] | None = None,
                   prompt_mangle=None,
                   session_sequence_start: int = 0) -> dict[str, Any]:
    """DIRECT comparator arm, OUTSIDE the controller.

    ``variant`` selects the corrected contract or a mutator for the
    negative-control suite. ``sampling_inputs``/``stopping_policy``/
    ``prompt_mangle`` are additional mutator seams (defaults frozen).
    Runtime-session ids are allocated by the allocator MECHANICALLY
    EXTRACTED from the pinned ``r5b_epochs.py`` bytes (the frozen
    ordinary controller's own allocation semantics); the
    ``session_sequence_shift`` control shifts only that allocation
    while leaving replay ids, outputs, max tokens, and everything else
    identical."""
    environment = _frozen_environment(repo_root)
    chain_plan = _load_chain_plan(repo_root)
    allocator = extract_runtime_session_allocator(
        repo_root, sequence_start=session_sequence_start)
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
                session_id=allocator.allocate(case["session_index"]),
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
                    session_id=allocator.allocate(case["session_index"]),
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
    document["runtime_session_allocation"] = dict(allocator.facts)
    return document


def run_both_arms(repo_root: Path | None = None, *,
                  direct_variant: str = "corrected",
                  direct_sampling=None, direct_stopping=None,
                  direct_prompt_mangle=None,
                  direct_session_sequence_start: int = 0,
                  use_ingress: bool = True) -> dict[str, Any]:
    root = repo_root or _repo_override()
    planner, serving, epochs, _strategy, xc_strategy = load_frozen_control_plane(root)
    fixture = derive_prompt_fixture(root)
    ingress_rows = None
    if use_ingress:
        ingress = run_ordinary_ingress_proof(root)
        if not ingress["passed"]:
            raise RuntimeError(
                "ordinary ingress proof failed; the ordinary arm refuses "
                "to serve non-ingress-derived ids: "
                + "; ".join(ingress["problems"][:3]))
        # the ordinary arm serves the ids the INGRESS derived (never
        # the fixture file directly); the proof above already required
        # derived == fixture 24/24
        ingress_rows = {
            row["case_id"]: {"derived_prompt_token_ids":
                             list(row["derived_prompt_token_ids"])}
            for row in ingress["rows"]}
    ordinary = run_ordinary_arm(
        planner, serving, epochs, xc_strategy, fixture, root,
        ingress_rows=ingress_rows)
    direct = run_direct_arm(
        planner, serving, epochs, xc_strategy, fixture, root,
        variant=direct_variant, sampling_inputs=direct_sampling,
        stopping_policy=direct_stopping, prompt_mangle=direct_prompt_mangle,
        session_sequence_start=direct_session_sequence_start)
    return {"fixture": fixture, "ordinary": ordinary, "direct": direct}


# ---------------------------------------------------------------------------
# 4. Fail-closed transcript-equivalence reducer
# ---------------------------------------------------------------------------

#: the COMPLETE compared per-call runtime-invocation field set: every
#: generate() argument VALUE that reaches the runtime (session id
#: included — it is part of the invocation, never control-plane-only)
#: plus the recorded response/commit contract
RUNTIME_CALL_FIELDS = (
    "case_id",
    "call_index",
    "runtime_session_id",
    "prompt_token_ids",
    "max_new_tokens",
    "on_token_present",
    "response_commit_token_id",
    "response_speculative_token_id",
    "response_token_ids",
)

#: retained alias for the model-execution-input comparison set
MODEL_INPUT_FIELDS = RUNTIME_CALL_FIELDS


def reduce_transcripts(ordinary: Mapping[str, Any],
                       direct: Mapping[str, Any]) -> dict[str, Any]:
    """Mechanically compare the ordered runtime-call transcripts; PASS only
    on exact per-case equality of the COMPLETE runtime-invocation
    contract (generate() argument values — runtime session_id included —
    commit/discard semantics, sampling, stopping). Never consults
    stored ``equal`` flags or terminal strings."""
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
            for field in RUNTIME_CALL_FIELDS:
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
        "schema": "inferswarm.issue129.transcript-reduction/2",
        "case_count": CASE_COUNT,
        "equal_count": equal_count,
        "rows": rows,
        "global_problems": problems,
        "compared_runtime_call_fields": list(RUNTIME_CALL_FIELDS),
        "control_plane_only_fields": list(CONTROL_PLANE_ONLY_FIELDS),
        "control_plane_only_proof": (
            "control-plane-only fields never appear among generate() "
            "arguments: the recording runtime captures the exact keyword "
            "set per call and the reducer requires it to equal the frozen "
            "contract on both arms; the runtime session_id IS a generate() "
            "argument value and is compared exactly per call; equality is "
            "computed only over the recorded runtime-invocation inputs"),
        "passed": passed,
        "terminal": METHODOLOGY_READY if passed else METHODOLOGY_BLOCKED,
    }


# ---------------------------------------------------------------------------
# 5. Attempt/STOP/physical-authorization state machine (executable)
# ---------------------------------------------------------------------------

ATTEMPT_CLASSES = (
    "PRE_OBSERVATION_INFRASTRUCTURE",
    "CORRECTNESS_BEARING_VALID",
    "CORRECTNESS_BEARING_INVALID",
    "DIAGNOSTIC_ONLY",
    "DIAGNOSTIC_ONLY_AFTER_STOP",
    "TERMINAL_CAMPAIGN_ATTEMPT",
    "TERMINAL_MARKER_NON_CORRECTNESS_BEARING",
)

ATTEMPT_FACT_FIELDS = (
    "campaign_id",
    "physical_authorization_id",
    "methodology_ready_identity",
    "execution_freeze_identity",
    "attempt_id",
    "observed_at",
    "campaign_lineage_root",
    "physical_authorization_issued_at",
    "prior_stopped_campaign_id",
    "prior_stop_attempt_id",
    "prior_stop_review_id",
    "prior_stop_reviewed_at",
    "gpu_execution_occurred",
    "model_execution_occurred",
    "correctness_bearing_result_emitted",
    "result_reached_coordinator",
    "coordinator_commit_occurred",
    "frozen_identity_verified_pre_launch",
    "frozen_identity_verified_post_run",
    "methodology_gate_passed",
    "physical_retry_authorized",
    "terminal_observation",
    "diagnostic_only_disclosure",
    "stop_occurred",
)

STOP_RULES = {
    "invalid_correctness_bearing_observation":
        "a correctness-bearing result was emitted or committed without "
        "verified frozen deployment identity (pre-launch AND post-run), "
        "or while methodology readiness was not accepted, or while "
        "physical retry execution was not authorized by the accepted "
        "gate state — including an UNDISCLOSED correctness-bearing "
        "continuation after the campaign's terminal observation",
    "permanent_campaign_stop":
        "after a correctness-bearing invalid attempt, all later "
        "observations in that campaign are diagnostic only and cannot "
        "produce a verdict",
    "non_correctness_bearing_terminal_cannot_clear_stop":
        "a non-correctness-bearing terminal marker attempted to clear a "
        "mandatory STOP and authorize further correctness-bearing "
        "attempts within the same campaign",
}

#: the frozen legal-transition table: per attempt class, its effect on
#: the mandatory STOP state and the terminal state, and whether it is
#: ever verdict-authoritative. This table — not ad-hoc code — defines
#: the state machine's dynamics.
LEGAL_TRANSITIONS = {
    "PRE_OBSERVATION_INFRASTRUCTURE": {
        "sets_terminal": False, "clears_stop": False,
        "mandatory_stop": False, "authoritative": False},
    "CORRECTNESS_BEARING_VALID": {
        "sets_terminal": False, "clears_stop": False,
        "mandatory_stop": False, "authoritative": True},
    "CORRECTNESS_BEARING_INVALID": {
        "sets_terminal": False, "clears_stop": False,
        "mandatory_stop": True, "authoritative": False,
        "stop_rule": "invalid_correctness_bearing_observation"},
    "DIAGNOSTIC_ONLY": {
        "sets_terminal": False, "clears_stop": False,
        "mandatory_stop": False, "authoritative": False},
    "DIAGNOSTIC_ONLY_AFTER_STOP": {
        "sets_terminal": False, "clears_stop": False,
        "mandatory_stop": False, "authoritative": False},
    "TERMINAL_CAMPAIGN_ATTEMPT": {
        "sets_terminal": True, "clears_stop": False,
        "mandatory_stop": False, "authoritative": True},
    "TERMINAL_MARKER_NON_CORRECTNESS_BEARING": {
        "sets_terminal": False, "clears_stop": False,
        "mandatory_stop": False, "authoritative": False,
        "stop_rule_if_stop_active":
            "non_correctness_bearing_terminal_cannot_clear_stop"},
}


CAMPAIGN_AUTHORITY_FIELDS = (
    "physical_retry_authorized",
    "physical_authorization_id",
    "methodology_ready_identity",
    "execution_freeze_identity",
    "campaign_lineage_root",
    "physical_authorization_issued_at",
    "prior_stopped_campaign_id",
    "prior_stop_attempt_id",
    "prior_stop_review_id",
    "prior_stop_reviewed_at",
)


def _attempt_state() -> dict[str, Any]:
    return {
        "stop_fired": False,
        "terminal_seen": False,
        "terminal_authoritative": False,
        "first_stop_attempt_id": None,
        "first_stop_observed_at": None,
    }


def _parse_utc(value: object, field: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a UTC timestamp")
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as error:
        raise ValueError(
            f"{field} must use YYYY-MM-DDTHH:MM:SSZ") from error


def _validate_attempt_identity(facts: Mapping[str, Any]) -> None:
    for field in ("campaign_id", "physical_authorization_id", "attempt_id",
                  "campaign_lineage_root"):
        if not isinstance(facts[field], str) or not facts[field].strip():
            raise ValueError(f"{field} must be a non-empty identity")
    if not _is_git_sha(facts["methodology_ready_identity"]):
        raise ValueError("methodology_ready_identity must be an accepted SHA")
    if not _is_sha256(facts["execution_freeze_identity"]):
        raise ValueError("execution_freeze_identity must be a sha256")
    _parse_utc(facts["observed_at"], "observed_at")
    issued_at = _parse_utc(
        facts["physical_authorization_issued_at"],
        "physical_authorization_issued_at")
    observed_at = _parse_utc(facts["observed_at"], "observed_at")
    if issued_at >= observed_at:
        raise ValueError(
            "physical authorization must be issued before the attempt")


def classify_attempt(facts: Mapping[str, Any],
                     *, stop_already_fired: bool = False,
                     terminal_seen: bool = False) -> str:
    """Mechanically classify one attempt from observed facts only.

    The classification separates, mechanically: methodology readiness
    (``methodology_gate_passed`` — load-bearing: a correctness-bearing
    attempt without it is INVALID), physical-retry authorization
    (``physical_retry_authorized`` — load-bearing the same way),
    deployment-identity validity, the correctness-bearing state, the
    mandatory STOP state, and terminal campaign observations. The
    authored ``stop_occurred`` field is a disclosure input the reducer
    records but never trusts; ``diagnostic_only_disclosure`` marks an
    observation as diagnostic (retained, never authoritative) but
    cannot launder a continuation into authority."""
    missing = set(ATTEMPT_FACT_FIELDS) - set(facts)
    if missing:
        raise ValueError(f"attempt facts lack {sorted(missing)}")
    _validate_attempt_identity(facts)
    correctness_bearing = bool(
        facts["correctness_bearing_result_emitted"]
        or facts["coordinator_commit_occurred"])
    identity_ok = bool(
        facts["frozen_identity_verified_pre_launch"]
        and facts["frozen_identity_verified_post_run"])
    authority_ok = bool(
        identity_ok
        and facts["methodology_gate_passed"]
        and facts["physical_retry_authorized"])
    if correctness_bearing and facts["diagnostic_only_disclosure"]:
        if stop_already_fired or terminal_seen:
            return "DIAGNOSTIC_ONLY_AFTER_STOP"
        return "DIAGNOSTIC_ONLY"
    if correctness_bearing and (stop_already_fired or terminal_seen):
        return "CORRECTNESS_BEARING_INVALID"
    if facts["terminal_observation"]:
        if not correctness_bearing:
            return "TERMINAL_MARKER_NON_CORRECTNESS_BEARING"
        if authority_ok:
            # a terminal physical campaign attempt IS representable as
            # a correctness-bearing attempt when fully authorized
            return "TERMINAL_CAMPAIGN_ATTEMPT"
        return "CORRECTNESS_BEARING_INVALID"
    if correctness_bearing:
        if not authority_ok:
            return "CORRECTNESS_BEARING_INVALID"
        return "CORRECTNESS_BEARING_VALID"
    return "PRE_OBSERVATION_INFRASTRUCTURE"


def reduce_attempts(
        attempts: Sequence[Mapping[str, Any]], *,
        accepted_campaign_authorities: Mapping[str, Mapping[str, Any]],
        ) -> dict[str, Any]:
    """Mechanically decide attempt classes and mandatory STOPs through
    the frozen LEGAL_TRANSITIONS table; fail closed when a
    correctness-bearing attempt continues without the state machine
    authorizing it.

    One ``campaign_id`` defines one authority domain. The required
    ``accepted_campaign_authorities`` input is a separate accepted-authority
    registry. Attempt facts cannot authorize themselves. A mandatory STOP
    is permanent in that domain. The latest campaign can pass even when
    an earlier campaign stays blocked, but the historical blocked state
    is never rewritten.

    Rules (all mechanical, from the reducer's OWN state — an authored
    ``stop_occurred`` or diagnostic label never launders authority):
    - CORRECTNESS_BEARING_INVALID fires the mandatory STOP (recorded
      as a stop event, with its reason). Post-terminal correctness-
      bearing continuations WITHOUT a diagnostic disclosure are
      INVALID: the campaign concluded; undisclosed follow-on
      correctness-bearing work is unauthorized.
    - TERMINAL_CAMPAIGN_ATTEMPT is possible only when the campaign has
      never fired a STOP. Only an authoritative terminal lets the campaign
      pass.
    - An explicitly disclosed diagnostic is never verdict authority.
    - A non-correctness-bearing terminal marker never clears a STOP;
      while a STOP is active it fires
      ``non_correctness_bearing_terminal_cannot_clear_stop``.
    - A new campaign after a STOP needs a new campaign id, physical
      authorization id, and lineage root. Its authorization timestamp
      must follow the prior STOP and the recorded maintainer review.
    - A new campaign cannot follow an intermediate nonterminal campaign.
      This rule prevents a STOP/review linkage bypass.
    """
    events = []
    problems = []
    stop_events = []
    campaign_states: dict[str, dict[str, Any]] = {}
    campaign_order: list[str] = []
    seen_authorizations: dict[str, str] = {}
    seen_lineage_roots: dict[str, str] = {}
    seen_attempt_ids: set[str] = set()
    if not isinstance(accepted_campaign_authorities, Mapping):
        raise ValueError(
            "accepted_campaign_authorities must be an accepted-authority "
            "mapping")
    for order, facts in enumerate(attempts, start=1):
        attempt_problem_count = len(problems)
        missing = set(ATTEMPT_FACT_FIELDS) - set(facts)
        if missing:
            raise ValueError(f"attempt facts lack {sorted(missing)}")
        _validate_attempt_identity(facts)
        campaign_id = facts["campaign_id"]
        if campaign_id in campaign_states and campaign_id != campaign_order[-1]:
            problems.append(
                f"campaign {campaign_id} resumed after a later campaign; "
                "a fresh reducer lineage cannot interleave campaigns")
        if facts["attempt_id"] in seen_attempt_ids:
            problems.append(f"duplicate attempt id: {facts['attempt_id']}")
        seen_attempt_ids.add(facts["attempt_id"])
        if campaign_id not in campaign_states:
            state = _attempt_state()
            state["authority_valid"] = True
            state["authority"] = {
                field: facts[field] for field in CAMPAIGN_AUTHORITY_FIELDS}
            accepted_record = accepted_campaign_authorities.get(campaign_id)
            if not isinstance(accepted_record, Mapping):
                state["accepted_authority_record"] = None
                problems.append(
                    f"campaign {campaign_id} has no accepted campaign "
                    "authority record")
            else:
                state["accepted_authority_record"] = dict(accepted_record)
                missing_authority = (
                    set(CAMPAIGN_AUTHORITY_FIELDS) - set(accepted_record))
                if missing_authority:
                    problems.append(
                        f"campaign {campaign_id} accepted authority record "
                        f"lacks {sorted(missing_authority)}")
                else:
                    for field in CAMPAIGN_AUTHORITY_FIELDS:
                        if facts[field] != accepted_record[field]:
                            problems.append(
                                f"campaign {campaign_id} attempt authority "
                                f"does not match accepted field {field}")
            state["events"] = []
            campaign_states[campaign_id] = state
            campaign_order.append(campaign_id)
            authorization_id = facts["physical_authorization_id"]
            lineage_root = facts["campaign_lineage_root"]
            if authorization_id in seen_authorizations:
                problems.append(
                    f"campaign {campaign_id} reuses physical authorization "
                    f"{authorization_id} from campaign "
                    f"{seen_authorizations[authorization_id]}")
            if lineage_root in seen_lineage_roots:
                problems.append(
                    f"campaign {campaign_id} reuses lineage root "
                    f"from campaign {seen_lineage_roots[lineage_root]}")
            seen_authorizations[authorization_id] = campaign_id
            seen_lineage_roots[lineage_root] = campaign_id
            prior_id = campaign_order[-2] if len(campaign_order) > 1 else None
            if prior_id is not None and campaign_states[prior_id]["stop_fired"]:
                prior = campaign_states[prior_id]
                if facts["prior_stopped_campaign_id"] != prior_id:
                    problems.append(
                        f"campaign {campaign_id} does not link to prior "
                        f"stopped campaign {prior_id}")
                if facts["prior_stop_attempt_id"] != \
                        prior["first_stop_attempt_id"]:
                    problems.append(
                        f"campaign {campaign_id} does not link to the prior "
                        "STOP attempt")
                review_id = facts["prior_stop_review_id"]
                if not isinstance(review_id, str) or not review_id.strip():
                    problems.append(
                        f"campaign {campaign_id} has no maintainer review id")
                try:
                    stopped_at = _parse_utc(
                        prior["first_stop_observed_at"], "prior STOP")
                    reviewed_at = _parse_utc(
                        facts["prior_stop_reviewed_at"],
                        "prior_stop_reviewed_at")
                    issued_at = _parse_utc(
                        facts["physical_authorization_issued_at"],
                        "physical_authorization_issued_at")
                    if not stopped_at < reviewed_at < issued_at:
                        problems.append(
                            f"campaign {campaign_id} authorization was not "
                            "issued after the prior STOP and review")
                except ValueError as error:
                    problems.append(str(error))
            elif prior_id is not None and not campaign_states[prior_id][
                    "terminal_authoritative"]:
                problems.append(
                    f"campaign {campaign_id} started before prior campaign "
                    f"{prior_id} reached an authoritative terminal; an "
                    "intermediate campaign cannot bypass a prior STOP/review")
            elif any(facts[field] is not None for field in (
                    "prior_stopped_campaign_id", "prior_stop_attempt_id",
                    "prior_stop_review_id", "prior_stop_reviewed_at")):
                problems.append(
                    f"campaign {campaign_id} claims a prior STOP review "
                    "when no prior campaign is stopped")
        state = campaign_states[campaign_id]
        for field in CAMPAIGN_AUTHORITY_FIELDS:
            if facts[field] != state["authority"][field]:
                problems.append(
                    f"campaign {campaign_id} changed authority field {field}")
        if len(problems) != attempt_problem_count:
            state["authority_valid"] = False
        prior_terminal = state["terminal_seen"]
        classification = classify_attempt(
            facts, stop_already_fired=state["stop_fired"],
            terminal_seen=state["terminal_seen"])
        transition = LEGAL_TRANSITIONS[classification]
        rule = None
        non_authoritative_note = None
        if classification == "CORRECTNESS_BEARING_INVALID":
            if not (facts["frozen_identity_verified_pre_launch"]
                    and facts["frozen_identity_verified_post_run"]):
                reason = "deployment identity defect"
            elif not facts["methodology_gate_passed"]:
                reason = "methodology readiness not accepted"
            elif not facts["physical_retry_authorized"]:
                reason = "physical retry not authorized"
            elif prior_terminal:
                reason = ("post-terminal continuation without a "
                          "diagnostic disclosure")
            elif state["stop_fired"]:
                reason = "campaign already has a permanent mandatory STOP"
            else:
                reason = "physical retry not authorized"
            rule = "invalid_correctness_bearing_observation"
            stop_events.append(
                f"campaign {campaign_id} attempt {order} "
                f"({facts['attempt_id']}) is "
                f"correctness-bearing INVALID ({reason}); mandatory STOP "
                "fired")
        elif classification == "TERMINAL_MARKER_NON_CORRECTNESS_BEARING":
            if state["stop_fired"]:
                rule = ("non_correctness_bearing_terminal_cannot_clear_stop")
                problems.append(
                    f"attempt {order} ({facts['attempt_id']}) is a "
                    "non-correctness-bearing terminal marker attempting to "
                    "clear a mandatory STOP")
        elif classification in ("DIAGNOSTIC_ONLY",
                                 "DIAGNOSTIC_ONLY_AFTER_STOP"):
            non_authoritative_note = (
                "explicitly disclosed and retained as diagnostic only; "
                "never verdict authority; "
                "clears neither the STOP nor the terminal requirement")
        # apply the frozen transition
        if transition["mandatory_stop"]:
            state["stop_fired"] = True
            if state["first_stop_attempt_id"] is None:
                state["first_stop_attempt_id"] = facts["attempt_id"]
                state["first_stop_observed_at"] = facts["observed_at"]
        if transition["sets_terminal"]:
            state["terminal_seen"] = True
            state["terminal_authoritative"] = bool(
                transition["authoritative"] and rule is None
                and state["authority_valid"])
        event = {
            "order": order,
            "campaign_id": campaign_id,
            "physical_authorization_id": facts["physical_authorization_id"],
            "methodology_ready_identity": facts["methodology_ready_identity"],
            "execution_freeze_identity": facts["execution_freeze_identity"],
            "attempt_id": facts["attempt_id"],
            "classification": classification,
            "stop_rule_fired": rule,
            # an event that fired a continuation stop rule is never
            # verdict authority, whatever its class label (review 1 P2)
            "authoritative": bool(
                transition["authoritative"] and rule is None
                and state["authority_valid"]),
            **({"non_authoritative_note": non_authoritative_note}
               if non_authoritative_note else {}),
            "state_after": {
                key: value for key, value in state.items()
                if key not in ("authority", "events")},
        }
        events.append(event)
        state["events"].append(event)
    campaign_results = {}
    for campaign_id in campaign_order:
        state = campaign_states[campaign_id]
        campaign_results[campaign_id] = {
            "authority": state["authority"],
            "accepted_authority_record":
                state["accepted_authority_record"],
            "blocked": state["stop_fired"],
            "authority_valid": state["authority_valid"],
            "terminal_seen": state["terminal_seen"],
            "terminal_authoritative": state["terminal_authoritative"],
            "passed": (not state["stop_fired"]
                       and state["authority_valid"]
                       and state["terminal_authoritative"]),
            "first_stop_attempt_id": state["first_stop_attempt_id"],
            "event_count": len(state["events"]),
        }
    latest = campaign_order[-1] if campaign_order else None
    final_state = (_attempt_state() if latest is None else {
        key: value for key, value in campaign_states[latest].items()
        if key not in ("authority", "accepted_authority_record", "events")})
    return {
        "schema": "inferswarm.issue129.attempt-reduction/4",
        "events": events,
        "problems": problems,
        "mandatory_stop_events": stop_events,
        "unresolved_mandatory_stops": list(stop_events),
        "campaigns": campaign_results,
        "latest_campaign_id": latest,
        "passed": bool(latest) and not problems
                  and campaign_results[latest]["passed"],
        "final_state": final_state,
        "stop_rules": STOP_RULES,
        "legal_transitions": LEGAL_TRANSITIONS,
        "authority_binding_rule": (
            "every campaign must match a separate accepted campaign "
            "authority record; attempt facts never establish their own "
            "methodology or physical execution authority"),
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
    # the byte-level post-run check is MANDATORY, not optional: an ok
    # verdict must prove the deployed bytes did not change after freeze
    post_run_sha = record.get("post_run_file_sha256")
    if not (isinstance(post_run_sha, str) and len(post_run_sha) == 64
            and all(c in "0123456789abcdef" for c in post_run_sha)):
        return {"ok": False,
                "reason": "post-run file sha256 is absent or malformed"}
    if post_run_sha != record["file_sha256"]:
        return {"ok": False,
                "reason": "correctness-bearing script changed after freeze"}
    return {"ok": True}


# ---------------------------------------------------------------------------
# 6b. Tokenizer Source rule: asset contract + observation monitor
# ---------------------------------------------------------------------------

#: The accepted physical environment did not retain a package inventory
#: that identifies its Transformers version. Issue #129 therefore freezes
#: this explicit software identity for the independent retry proof and for
#: any future physical retry authorized from this methodology.
REQUIRED_TOKENIZER_SOFTWARE = {
    "transformers": "5.17.0",
    "tokenizers": "0.23.2",
    "Jinja2": "3.1.6",
    "MarkupSafe": "3.0.3",
}
TOKENIZER_PYTHON = "3.12"
TOKENIZER_REQUIREMENTS_SHA256 = (
    "793616a40ed5902d8387b964347f6d391e95f52c046ac21e939f53938f5b308e")
TOKENIZER_SOFTWARE_IDENTITY_SHA256 = (
    "8133ae80ca8925f246d86a9bca1356ee46dc27d95201cf043261fd164e5b87a4")

#: the exact immutable tokenizer/config assets the frozen Coordinator
#: needs, with sha256 identities derived from the accepted
#: checkpoint-authority provenance (recovered_object_manifest). The
#: future physical retry must publish THESE byte-identical assets to a
#: dedicated non-Source location before the observation window.
REQUIRED_TOKENIZER_ASSETS = {
    "chat_template.jinja":
        "ae53464bf3be25802b3a5b37def7fd89667067d7577049b3b2d74c4d8de4c6d4",
    "config.json":
        "478c46e8d2c52d5c2d85bf67e3b3e8c90e7c9d91086cee27e3c267907e936bd9",
    "generation_config.json":
        "a8349d9bd64cc5841297fcb5002f0fdc4749c473c8f1b10ea337f9ce4ee7014e",
    "tokenizer.json":
        "cc8d3a0ce36466ccc1278bf987df5f71db1719b9ca6b4118264f45cb627bfe0f",
    "tokenizer_config.json":
        "a62f4e85a47c0c136edaaa3a4f591fd6783717299a9def47e5ad03a49f6a5eb9",
}


def verify_retained_tokenizer_assets(
        repo_root: Path | None = None, *,
        asset_dir: Path | None = None) -> dict[str, Any]:
    """Verify the retained real-tokenizer directory byte for byte."""
    root = repo_root or _repo_override()
    directory = asset_dir or (
        root / TOKENIZER_ASSET_DIR.relative_to(ROOT))
    resolved = directory.resolve()
    forbidden = Path(FORBIDDEN_SOURCE_ROOT).resolve()
    if resolved == forbidden or forbidden in resolved.parents:
        raise RuntimeError(
            "retained tokenizer path is under the forbidden /srv/models/ "
            "Source root")
    if directory.is_symlink():
        raise RuntimeError("retained tokenizer asset directory is a symlink")
    if not directory.is_dir():
        raise FileNotFoundError(
            f"retained tokenizer asset directory is missing: {directory}")
    entries = sorted(path.name for path in directory.iterdir())
    required = sorted(REQUIRED_TOKENIZER_ASSETS)
    if entries != required:
        missing = sorted(set(required) - set(entries))
        extra = sorted(set(entries) - set(required))
        raise RuntimeError(
            "retained tokenizer asset directory is not exhaustive: "
            f"missing={missing}, extra={extra}")
    digests = {}
    sizes = {}
    for name, expected in sorted(REQUIRED_TOKENIZER_ASSETS.items()):
        path = directory / name
        if not path.is_file() or path.is_symlink():
            raise RuntimeError(
                f"retained tokenizer asset is not a regular file: {name}")
        digest = sha256_file(path)
        if digest != expected:
            raise RuntimeError(f"retained tokenizer asset drift: {name}")
        digests[name] = digest
        sizes[name] = path.stat().st_size
    try:
        recorded_directory = str(resolved.relative_to(root.resolve()))
    except ValueError:
        recorded_directory = str(resolved)
    return {
        "asset_dir": recorded_directory,
        "asset_dir_exhaustive": True,
        "asset_count": len(digests),
        "digests": digests,
        "sizes": sizes,
    }


def verify_tokenizer_software_identity(
        repo_root: Path | None = None, *,
        installed_versions: Mapping[str, str] | None = None
        ) -> dict[str, Any]:
    """Verify the retained identity files and active package versions."""
    root = repo_root or _repo_override()
    identity_path = (root / TOKENIZER_ROOT.relative_to(ROOT)
                     / "software-identity.json")
    requirements_path = (root / TOKENIZER_ROOT.relative_to(ROOT)
                         / "requirements.txt")
    if sha256_file(identity_path) != TOKENIZER_SOFTWARE_IDENTITY_SHA256:
        raise RuntimeError("tokenizer software identity file drift")
    if sha256_file(requirements_path) != TOKENIZER_REQUIREMENTS_SHA256:
        raise RuntimeError("tokenizer requirements file drift")
    identity = json.loads(identity_path.read_text())
    if identity.get("schema") != \
            "inferswarm.issue129.tokenizer-software-identity/1":
        raise RuntimeError("tokenizer software identity schema drift")
    if identity.get("packages") != REQUIRED_TOKENIZER_SOFTWARE:
        raise RuntimeError("tokenizer software package identity drift")
    if identity.get("python") != TOKENIZER_PYTHON:
        raise RuntimeError("tokenizer Python identity drift")
    live_environment = installed_versions is None
    if live_environment:
        installed_versions = {}
        for package in REQUIRED_TOKENIZER_SOFTWARE:
            try:
                installed_versions[package] = importlib.metadata.version(
                    package)
            except importlib.metadata.PackageNotFoundError as error:
                raise RuntimeError(
                    f"required tokenizer package is missing: {package}") \
                    from error
    observed = dict(installed_versions)
    for package, expected in REQUIRED_TOKENIZER_SOFTWARE.items():
        if observed.get(package) != expected:
            raise RuntimeError(
                f"tokenizer package/version drift: {package} "
                f"{observed.get(package)!r} != {expected!r}")
    python_version = f"{sys.version_info.major}.{sys.version_info.minor}"
    if live_environment and python_version != TOKENIZER_PYTHON:
        raise RuntimeError(
            f"tokenizer Python version drift: {python_version} != "
            f"{TOKENIZER_PYTHON}")
    return {
        "python": TOKENIZER_PYTHON,
        "packages": observed,
        "requirements_sha256": TOKENIZER_REQUIREMENTS_SHA256,
        "software_identity_sha256": TOKENIZER_SOFTWARE_IDENTITY_SHA256,
    }

TOKENIZER_ASSET_CONTRACT_FIELDS = (
    "tokenizer_path",
    "asset_dir",
    "assets",
    "asset_dir_exhaustive",
    "asset_dir_extra_entries",
    "digests_verified_pre_window",
    "forbidden_root",
    "observation_window_source_opens",
)


def tokenizer_asset_contract_record(
        repo_root: Path | None = None, *,
        tokenizer_path: str = "/srv/inferswarm/tokenizers/gemma-r6-frozen",
        asset_dir: str | None = None,
        digests_verified_pre_window: bool = True,
        observation_window_source_opens: int = 0) -> dict[str, Any]:
    """Build the frozen tokenizer Source contract record for the future
    physical retry (preferred design, frozen by this methodology)."""
    root = repo_root or _repo_override()
    provenance = json.loads(
        (root / AREA.relative_to(ROOT) / "evidence"
         / "checkpoint-authority-provenance.json").read_text())
    manifest = {
        entry["path"]: entry for entry in provenance["recovered_object_manifest"]
    }
    assets = []
    for name in sorted(REQUIRED_TOKENIZER_ASSETS):
        entry = manifest.get(name)
        # LFS-hosted assets carry their content sha256 as the lfs oid
        digest = None
        if entry is not None:
            digest = entry.get("sha256") or entry.get("lfs_oid_sha256")
        if digest != REQUIRED_TOKENIZER_ASSETS[name]:
            raise RuntimeError(
                f"accepted checkpoint-authority provenance does not pin "
                f"{name} to the frozen identity; asset contract fails "
                "closed")
        assets.append({"name": name, "sha256": digest})
    return {
        "status": (
            "future-retry-obligation: this record freezes the contract "
            "the future physical retry must satisfy and verify; the "
            "digest/verification fields are the contract's requirements, "
            "not observations performed by this CPU-only run (the only "
            "in-run mechanical observation is the audit-hook monitor "
            "result)"),
        "tokenizer_path": tokenizer_path,
        "asset_dir": asset_dir or tokenizer_path,
        "assets": assets,
        "asset_dir_exhaustive": True,
        "asset_dir_extra_entries": [],
        "digests_verified_pre_window": digests_verified_pre_window,
        "forbidden_root": FORBIDDEN_SOURCE_ROOT,
        "observation_window_source_opens": observation_window_source_opens,
    }


def verify_tokenizer_asset_contract(
        record: Mapping[str, Any]) -> dict[str, Any]:
    """Verify the frozen tokenizer Source contract; fail closed.

    The real invariant (not any ``transformers``-absence proxy): the
    exact immutable tokenizer/config assets required by the Coordinator
    are sha256-pinned at a dedicated NON-Source location,
    ``tokenizer_path`` points there (never at the forbidden Source
    root), digests were verified before the observation window began,
    and zero opens under the forbidden Source root occurred during the
    observation window."""
    missing = [f for f in TOKENIZER_ASSET_CONTRACT_FIELDS if f not in record]
    if missing:
        return {"ok": False,
                "reason": f"missing fields {missing}"}
    forbidden = str(record["forbidden_root"])
    if forbidden != FORBIDDEN_SOURCE_ROOT:
        return {"ok": False,
                "reason": f"forbidden root is not the frozen {FORBIDDEN_SOURCE_ROOT!r}"}
    tokenizer_path = record["tokenizer_path"]
    asset_dir = record["asset_dir"]
    for value, what in ((tokenizer_path, "tokenizer_path"),
                        (asset_dir, "asset_dir")):
        if not isinstance(value, str) or not value.startswith("/"):
            return {"ok": False, "reason": f"{what} is not absolute"}
        if value == forbidden or value.startswith(forbidden):
            return {"ok": False,
                    "reason": f"{what} points at the forbidden Source "
                    f"root {forbidden}"}
    assets = record["assets"]
    if not isinstance(assets, list) or not assets:
        return {"ok": False, "reason": "no tokenizer assets are pinned"}
    seen = {}
    for asset in assets:
        if not isinstance(asset, dict):
            return {"ok": False, "reason": "malformed asset entry"}
        name = asset.get("name")
        digest = asset.get("sha256")
        if not isinstance(name, str) or not _is_sha256(digest):
            return {"ok": False,
                    "reason": f"asset {name!r} has no valid sha256 pin"}
        expected = REQUIRED_TOKENIZER_ASSETS.get(name)
        if expected is None:
            return {"ok": False,
                    "reason": f"asset {name!r} is not a required tokenizer asset"}
        if digest != expected:
            return {"ok": False,
                    "reason": f"tokenizer asset digest drift: {name}"}
        seen[name] = digest
    for name in sorted(REQUIRED_TOKENIZER_ASSETS):
        if name not in seen:
            return {"ok": False,
                    "reason": f"required tokenizer asset missing: {name}"}
    # exhaustive-directory rule (review 1 P2): the pinned set must be
    # EXACTLY what the asset directory contains — an unlisted extra
    # file AutoTokenizer could consume (special_tokens_map.json,
    # added_tokens.json, …) would change tokenizer behavior without
    # touching any pinned digest
    if record.get("asset_dir_exhaustive") is not True:
        return {"ok": False,
                "reason": "asset directory listing is not exhaustive "
                "(unlisted tokenizer files could alter behavior)"}
    extras = record.get("asset_dir_extra_entries")
    if extras:
        return {"ok": False,
                "reason": f"asset directory carries unlisted entries: "
                f"{sorted(extras)}"}
    if record["digests_verified_pre_window"] is not True:
        return {"ok": False,
                "reason": "asset digests were not verified before the "
                "observation window"}
    if record["observation_window_source_opens"] != 0:
        return {"ok": False,
                "reason": "forbidden Source opens occurred during the "
                "observation window"}
    return {"ok": True}


class SourceAccessMonitor:
    """Mechanical observation-window monitor for the forbidden Source
    root: a ``sys.addaudithook`` watcher that records every ``open``
    event whose path lies under the root. During the CPU methodology
    run this proves the real invariant — no Source access during the
    observation window — without depending on whether ``transformers``
    happens to be importable."""

    def __init__(self, forbidden_root: str = FORBIDDEN_SOURCE_ROOT) -> None:
        self.watched_root = forbidden_root
        self.forbidden_root = forbidden_root
        self.violations: list[dict[str, Any]] = []
        self._hook = None

    def _audit(self, event: str, args: tuple) -> None:
        if event != "open":
            return
        path = args[0] if args else None
        if isinstance(path, bytes):
            path = path.decode(errors="replace")
        if isinstance(path, str) and (
                path == self.forbidden_root
                or path.startswith(self.forbidden_root)):
            self.violations.append({
                "event": event,
                "path": path,
                "mode": str(args[1]) if len(args) > 1 else None,
            })

    def __enter__(self) -> "SourceAccessMonitor":
        sys.addaudithook(self._audit)
        return self

    def __exit__(self, *exc) -> None:
        # audit hooks cannot be removed; the hook self-disarms
        self.forbidden_root = "\0disarmed\0"

    def report(self) -> dict[str, Any]:
        return {
            "forbidden_root": self.watched_root,
            "frozen_rule_forbidden_root": FORBIDDEN_SOURCE_ROOT,
            "forbidden_opens": list(self.violations),
            "observation_window_source_opens": len(self.violations),
            "observation_window_clean": not self.violations,
        }


# ---------------------------------------------------------------------------
# 6c. Accepted #128 blocker byte-preservation (issue #129 Finding 1)
# ---------------------------------------------------------------------------

def accepted_blocker_evidence_paths(repo_root: Path | None = None) -> list[str]:
    """Every evidence path that existed under ``evidence/arm-c/`` at the
    accepted blocker merge ``718efbf…`` (git ls-tree)."""
    root = repo_root or _repo_override()
    merge = _accepted_merge_override()
    out = subprocess.run(
        ["git", "-c", f"safe.directory={root}", "-C", str(root),
         "ls-tree", "-r", "--name-only", merge, "--",
         str(ARM_C_EVIDENCE.relative_to(ROOT))],
        capture_output=True, text=True, check=True)
    paths = [line for line in out.stdout.splitlines() if line.strip()]
    if not paths:
        raise RuntimeError(
            f"no accepted arm-c evidence paths resolved at {merge}; "
            "preservation check fails closed")
    return paths


def verify_accepted_blocker_preservation(
        repo_root: Path | None = None) -> dict[str, Any]:
    """Prove every accepted #128 blocker evidence path that existed at
    the accepted merge remains byte-exact in the working tree; fail
    closed on any drift. The accepted blocker is immutable historical
    authority — issue #129 adds under ``evidence/arm-c-retry/`` only."""
    root = repo_root or _repo_override()
    merge = _accepted_merge_override()
    paths = accepted_blocker_evidence_paths(root)
    digests = {}
    for rel in paths:
        worktree = root / rel
        if not worktree.is_file():
            raise FileNotFoundError(
                f"accepted #128 blocker evidence path missing from the "
                f"working tree: {rel}")
        blob = subprocess.run(
            ["git", "-c", f"safe.directory={root}", "-C", str(root),
             "cat-file", "blob", f"{merge}:{rel}"],
            capture_output=True, check=True).stdout
        blob_sha = sha256_bytes(blob)
        worktree_sha = sha256_file(worktree)
        if worktree_sha != blob_sha:
            raise RuntimeError(
                f"accepted #128 blocker evidence drifted from {merge}: "
                f"{rel} (worktree {worktree_sha} != accepted "
                f"{blob_sha})")
        digests[rel] = worktree_sha
    accepted_set = set(paths)
    arm_c_root = root / ARM_C_EVIDENCE.relative_to(ROOT)
    current_paths = {
        str(path.relative_to(root))
        for path in arm_c_root.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
        and path.suffix != ".pyc"
    }
    new_paths = sorted(current_paths - accepted_set)
    if new_paths:
        raise RuntimeError(
            "issue #129 introduced paths inside the accepted evidence/arm-c/ "
            f"namespace: {new_paths}")
    ordered = ";".join(f"{rel}:{digests[rel]}" for rel in sorted(digests))
    return {
        "schema": "inferswarm.issue129.accepted-blocker-preservation/1",
        "accepted_blocker_merge": merge,
        "path_count": len(paths),
        "current_path_count": len(current_paths),
        "preserved": True,
        "no_new_paths": True,
        "new_paths": [],
        "preserved_paths_digest": "sha256:" + sha256_bytes(ordered.encode()),
        "digests": digests,
        "rule": (
            "every evidence path under evidence/arm-c/ that existed at "
            "the accepted merge is byte-identical in the working tree; "
            "the current namespace contains no additional path; all "
            "issue-#129 authority lives under evidence/arm-c-retry/"),
    }


# ---------------------------------------------------------------------------
# 7. Top-level methodology run
# ---------------------------------------------------------------------------

#: the mandatory attempt-state-machine control sequences, re-derived by
#: every methodology run (self-check evidence; the full mutation suite
#: lives in tests/test_issue129_arm_c_retry.py). Each row: (name,
#: sequence, expected passed, expected classifications).
ATTEMPT_STATE_SELF_CHECKS = (
    ("correctness_bearing_without_methodology_readiness",
     [{"id": "a-1", "cb": True, "readiness": False}], False,
     ["CORRECTNESS_BEARING_INVALID"]),
    ("correctness_bearing_without_physical_authorization",
     [{"id": "a-1", "cb": True, "authorized": False}], False,
     ["CORRECTNESS_BEARING_INVALID"]),
    ("same_campaign_terminal_cannot_clear_stop",
     [{"id": "a-1", "cb": True, "authorized": False},
      {"id": "a-2", "cb": True, "terminal": True}], False,
     ["CORRECTNESS_BEARING_INVALID", "CORRECTNESS_BEARING_INVALID"]),
    ("same_campaign_boolean_flip_cannot_clear_stop",
     [{"id": "a-1", "authorized": False},
      {"id": "a-2", "cb": True, "terminal": True,
       "authorized": True}], False,
     ["PRE_OBSERVATION_INFRASTRUCTURE", "TERMINAL_CAMPAIGN_ATTEMPT"]),
    ("post_stop_diagnostic_remains_non_authoritative",
     [{"id": "a-1", "cb": True, "authorized": False},
      {"id": "a-2", "cb": True, "diagnostic": True,
       "authorized": False}], False,
     ["CORRECTNESS_BEARING_INVALID", "DIAGNOSTIC_ONLY_AFTER_STOP"]),
    ("post_terminal_undisclosed_continuation_fails_closed",
     [{"id": "a-1", "cb": True, "terminal": True},
      {"id": "a-2", "cb": True}], False,
     ["TERMINAL_CAMPAIGN_ATTEMPT", "CORRECTNESS_BEARING_INVALID"]),
    ("terminal_without_stop_passes",
     [{"id": "a-1", "cb": True, "terminal": True}], True,
     ["TERMINAL_CAMPAIGN_ATTEMPT"]),
    ("nonterminal_campaign_cannot_pass",
     [{"id": "a-1", "cb": True}], False,
     ["CORRECTNESS_BEARING_VALID"]),
    ("diagnostic_disclosure_is_never_authority",
     [{"id": "a-1", "cb": True, "terminal": True,
       "diagnostic": True}], False,
     ["DIAGNOSTIC_ONLY"]),
    ("fresh_post_review_campaign_is_independent",
     [{"id": "a-1", "cb": True, "authorized": False},
      {"id": "b-1", "campaign": "campaign-B", "cb": True,
       "terminal": True}], True,
     ["CORRECTNESS_BEARING_INVALID", "TERMINAL_CAMPAIGN_ATTEMPT"]),
    ("intermediate_campaign_cannot_bypass_stop_review",
     [{"id": "a-1", "cb": True, "authorized": False},
      {"id": "b-1", "campaign": "campaign-B"},
      {"id": "c-1", "campaign": "campaign-C", "cb": True,
       "terminal": True}], False,
     ["CORRECTNESS_BEARING_INVALID", "PRE_OBSERVATION_INFRASTRUCTURE",
      "TERMINAL_CAMPAIGN_ATTEMPT"]),
)


def _self_check_facts(overrides: Mapping[str, Any]) -> dict[str, Any]:
    campaign = overrides.get("campaign", "campaign-A")
    is_b = campaign == "campaign-B"
    is_c = campaign == "campaign-C"
    suffix = "C" if is_c else ("B" if is_b else "A")
    if is_c:
        default_observed_at = "2026-09-09T00:00:06Z"
    elif is_b:
        default_observed_at = "2026-09-09T00:00:05Z"
    elif overrides.get("id") == "a-2":
        default_observed_at = "2026-09-09T00:00:02Z"
    else:
        default_observed_at = "2026-09-09T00:00:01Z"
    return {
        "attempt_id": overrides.get("id", "self-check"),
        "campaign_id": campaign,
        "physical_authorization_id": overrides.get(
            "authorization_id", f"authorization-{suffix}"),
        "methodology_ready_identity": "a" * 40,
        "execution_freeze_identity": "b" * 64,
        "campaign_lineage_root": overrides.get(
            "lineage_root", f"lineage-{suffix}"),
        "physical_authorization_issued_at": overrides.get(
            "issued_at", "2026-09-09T00:00:04Z" if is_b else
            "2026-09-09T00:00:00Z"),
        "prior_stopped_campaign_id": (
            overrides.get("prior_campaign", "campaign-A") if is_b else None),
        "prior_stop_attempt_id": (
            overrides.get("prior_attempt", "a-1") if is_b else None),
        "prior_stop_review_id": (
            overrides.get("review_id", "maintainer-review-A")
            if is_b else None),
        "prior_stop_reviewed_at": (
            overrides.get("reviewed_at", "2026-09-09T00:00:03Z")
            if is_b else None),
        "observed_at": overrides.get("observed_at", default_observed_at),
        "gpu_execution_occurred": False,
        "model_execution_occurred": False,
        "correctness_bearing_result_emitted": bool(overrides.get("cb")),
        "result_reached_coordinator": bool(overrides.get("cb")),
        "coordinator_commit_occurred": False,
        "frozen_identity_verified_pre_launch": True,
        "frozen_identity_verified_post_run": True,
        "methodology_gate_passed": bool(overrides.get("readiness", True)),
        "physical_retry_authorized": bool(overrides.get("authorized", True)),
        "terminal_observation": bool(overrides.get("terminal")),
        "diagnostic_only_disclosure": bool(overrides.get("diagnostic")),
        "stop_occurred": False,
    }


def _self_check_authority_records(
        attempts: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """Build explicit synthetic authority records for CPU-only controls.

    These records test reducer mechanics. They are not physical execution
    authority. A physical reducer caller must supply records from accepted
    project authority, separate from observed attempt facts.
    """
    records: dict[str, dict[str, Any]] = {}
    for facts in attempts:
        campaign_id = facts["campaign_id"]
        records.setdefault(campaign_id, {
            field: facts[field] for field in CAMPAIGN_AUTHORITY_FIELDS})
    return records


def run_attempt_state_self_checks() -> dict[str, Any]:
    rows = []
    ok = True
    for name, sequence, expect_passed, expect_classes \
            in ATTEMPT_STATE_SELF_CHECKS:
        attempts = [_self_check_facts(spec) for spec in sequence]
        reduction = reduce_attempts(
            attempts,
            accepted_campaign_authorities=
                _self_check_authority_records(attempts))
        classifications = [
            event["classification"] for event in reduction["events"]]
        verdict = (
            bool(reduction["passed"]) is expect_passed
            and classifications == list(expect_classes))
        if name == "post_stop_diagnostic_remains_non_authoritative":
            verdict = verdict and all(
                not event["authoritative"]
                for event in reduction["events"][1:])
        if name == "fresh_post_review_campaign_is_independent":
            verdict = verdict and (
                reduction["campaigns"]["campaign-A"]["blocked"]
                and reduction["campaigns"]["campaign-B"]["passed"]
                and reduction["latest_campaign_id"] == "campaign-B")
        ok = ok and verdict
        rows.append({
            "control": name,
            "expected_passed": expect_passed,
            "observed_passed": reduction["passed"],
            "expected_classifications": list(expect_classes),
            "observed_classifications": classifications,
            "ok": verdict,
        })
    return {"ok": ok, "rows": rows}


def _runtime_session_cross_check(
        ordinary: Mapping[str, Any],
        repo_root: Path | None = None) -> dict[str, Any]:
    """Prove the ordinary controller's recorded runtime session ids
    equal the EXTRACTED frozen allocation replayed in ordinary order —
    the extraction is faithful to the real controller, and the direct
    arm's ids are the same sequence."""
    problems = []
    representative = {}
    extracted = extract_runtime_session_allocator(repo_root)
    for case_id in sorted(ordinary["per_case"]):
        case = ordinary["per_case"][case_id]
        logical = case["logical_session_id"]
        expected = [extracted.allocate(logical) for _ in case["calls"]]
        observed = [call["runtime_session_id"] for call in case["calls"]]
        if expected != observed:
            problems.append(
                f"{case_id}: ordinary runtime session ids do not match "
                "the extracted frozen allocation")
        if len(representative) < 3:
            representative[case_id] = {
                "logical_session_id": logical,
                "runtime_session_ids": observed,
            }
    return {
        "ok": not problems,
        "problems": problems,
        "representative_sequences": representative,
        "derivation": (
            "the ordinary arm's per-call runtime session ids equal the "
            "allocator mechanically extracted from the pinned "
            "r5b_epochs.py bytes, replayed in ordinary case order "
            f"(logical_session_id * {extracted.facts['multiplier']} "
            "+ global call sequence, per the extracted method)"),
    }


def run_methodology(repo_root: Path | None = None, *,
                    direct_variant: str = "corrected",
                    direct_sampling=None, direct_stopping=None,
                    direct_prompt_mangle=None,
                    direct_session_sequence_start: int = 0,
                    ingress_footer_mutator=None,
                    ingress_content_mutator=None,
                    ingress_body_mutator=None,
                    tokenizer_contract_mutator=None,
                    simulated_forbidden_root: str | None = None
                    ) -> dict[str, Any]:
    """Run the complete CPU-only methodology gate.

    Negative-control seams (each must downgrade the terminal to
    BLOCKED): the direct-arm mutators (variant / sampling / stopping /
    prompt / session-sequence), the ingress mutators (template footer /
    content encodings / request body), the tokenizer-contract mutator,
    and ``simulated_forbidden_root`` (a real ``open()`` under that root
    is attempted inside the observation window so the audit monitor
    records it)."""
    root = repo_root or _repo_override()
    global_problems: list[str] = []

    # Finding 1: the accepted #128 blocker evidence is preserved
    # byte-exact; this raises (fail-closed) on any drift
    preservation = verify_accepted_blocker_preservation(root)

    # Finding 4: fail-closed frozen-byte pins (raises on any defect)
    frozen_digests = verify_frozen_bytes(root)

    # Finding 2: the frozen runtime-session allocation is extractable
    # from the pinned bytes (raises on drift)
    allocator = extract_runtime_session_allocator(root)
    del allocator

    # Finding 3: the ordinary Coordinator ingress/tokenizer seam
    ingress = run_ordinary_ingress_proof(
        root, stand_in_footer_mutator=ingress_footer_mutator,
        stand_in_content_mutator=ingress_content_mutator,
        body_mutator=ingress_body_mutator)

    tokenizer_contract = tokenizer_asset_contract_record(root)
    if tokenizer_contract_mutator is not None:
        tokenizer_contract = dict(
            tokenizer_contract_mutator(dict(tokenizer_contract)))
    tokenizer_verdict = verify_tokenizer_asset_contract(tokenizer_contract)

    arms = None
    reduction = None
    session_cross_check = None
    monitor_report = None
    if ingress["passed"]:
        with SourceAccessMonitor(
                simulated_forbidden_root or FORBIDDEN_SOURCE_ROOT
        ) as monitor:
            if simulated_forbidden_root is not None:
                # negative control: a real open attempt under the
                # (test-local) forbidden root inside the observation
                # window; the audit hook records it before any
                # filesystem result
                try:
                    open(Path(simulated_forbidden_root) / "tokenizer.json",
                         "rb").close()
                except OSError:
                    pass
            arms = run_both_arms(
                root, direct_variant=direct_variant,
                direct_sampling=direct_sampling,
                direct_stopping=direct_stopping,
                direct_prompt_mangle=direct_prompt_mangle,
                direct_session_sequence_start=direct_session_sequence_start)
            reduction = reduce_transcripts(arms["ordinary"], arms["direct"])
        monitor_report = monitor.report()
    else:
        global_problems.append(
            "ordinary Coordinator ingress proof failed: "
            + "; ".join(ingress["problems"][:3]))
        monitor_report = {
            "forbidden_root": FORBIDDEN_SOURCE_ROOT,
            "forbidden_opens": [],
            "observation_window_source_opens": 0,
            "observation_window_clean": True,
            "note": "arms not run: the ordinary arm refuses to serve "
                    "non-ingress-derived prompt ids",
        }

    if not tokenizer_verdict["ok"]:
        global_problems.append(
            "tokenizer Source contract violated: " + tokenizer_verdict["reason"])
    if arms is not None and reduction is not None:
        if not monitor_report["observation_window_clean"]:
            global_problems.append(
                "forbidden Source opens occurred during the observation "
                f"window: {monitor_report['forbidden_opens']}")
        session_cross_check = _runtime_session_cross_check(
            arms["ordinary"], root)
        if not session_cross_check["ok"]:
            global_problems.extend(session_cross_check["problems"])
        if not reduction["passed"]:
            global_problems.extend(reduction["global_problems"])

    attempt_self_checks = run_attempt_state_self_checks()
    if not attempt_self_checks["ok"]:
        global_problems.append(
            "attempt/STOP state machine self-checks failed")

    passed = (ingress["passed"]
              and tokenizer_verdict["ok"]
              and monitor_report["observation_window_clean"]
              and reduction is not None and reduction["passed"]
              and session_cross_check is not None and session_cross_check["ok"]
              and attempt_self_checks["ok"]
              and not global_problems)
    terminal = METHODOLOGY_READY if passed else METHODOLOGY_BLOCKED
    document = {
        "schema": "inferswarm.issue129.methodology-run/4",
        "authority": {
            "issue": "https://github.com/Zutfen-LLC/inferswarm/issues/129",
            "accepted_arm_c_blocker": "ISSUE117_ARM_C_EVIDENCE_BLOCKER",
            "accepted_arm_c_blocker_merge": ACCEPTED_BLOCKER_MERGE,
            "accepted_arm_b_result": ACCEPTED_ARM_B_RESULT,
            "accepted_arm_b_merge": ACCEPTED_ARM_B_MERGE,
            "frozen_producer": FROZEN_PRODUCER_SHA,
            "accepted_fixture_digest": FIXTURE_DIGEST_24,
            "checkpoint_authority": CHECKPOINT_SHA256,
            "additive_history_rule": (
                "the accepted #128 blocker evidence under evidence/arm-c/ "
                "is immutable history preserved byte-exact; every #129 "
                "authority, pin, and derived methodology output lives "
                "additively under evidence/arm-c-retry/"),
        },
        "accepted_blocker_preservation": {
            k: v for k, v in preservation.items() if k != "digests"},
        "frozen_control_plane_digests": frozen_digests,
        "runtime_session_allocation": extract_runtime_session_allocator(
            root).facts,
        "ordinary_ingress": {
            k: v for k, v in ingress.items() if k not in ("rows",)},
        "tokenizer_source_contract": {
            "record": tokenizer_contract,
            "verification": tokenizer_verdict,
            "observation_monitor": monitor_report,
            "transformers_imported_for_pre_window_proof": any(
                name == "transformers" or name.startswith("transformers.")
                for name in sys.modules),
            "rule": (
                "the future physical retry must publish the exact "
                "sha256-pinned tokenizer/config assets to a dedicated "
                "non-Source location, point tokenizer_path there, verify "
                "digests pre-window, and open nothing under "
                f"{FORBIDDEN_SOURCE_ROOT} during the observation "
                "window; the Coordinator legitimately uses a tokenizer "
                "— the gate never hinges on transformers being absent"),
        },
        "fixture": (
            {"fixture_digest": arms["fixture"]["fixture_digest"],
             "case_count": arms["fixture"]["case_count"]}
            if arms else None),
        "ordinary_summary": (
            {k: arms["ordinary"][k] for k in (
                "arm", "variant", "plan_digest", "candidate_id", "mapping",
                "selection_authorization", "plan_digest_source",
                "sampling_inputs", "stopping_policy",
                "generate_argument_names", "runtime_session_allocation")}
            if arms else None),
        "direct_summary": (
            {k: arms["direct"][k] for k in (
                "arm", "variant", "plan_digest", "candidate_id", "mapping",
                "selection_authorization", "plan_digest_source",
                "sampling_inputs", "stopping_policy",
                "generate_argument_names", "runtime_session_allocation")}
            if arms else None),
        "per_case_reduction": reduction,
        "runtime_session_cross_check": session_cross_check,
        "attempt_state_machine_self_checks": attempt_self_checks,
        "global_problems": global_problems,
        "cpu_only": {
            "gpu_execution_occurred": False,
            "model_execution_occurred": False,
            "note": "recording fake runtime; no model bytes; CPU-only host",
        },
        "terminal": terminal,
    }
    return document


def build_authority_record(repo_root: Path | None = None) -> dict[str, Any]:
    """The #129 authority/integrity record retained additively under
    evidence/arm-c-retry/authority.json: the authority chain, the
    additive-history policy, and the byte-preservation proof of the
    accepted #128 blocker evidence."""
    root = repo_root or _repo_override()
    preservation = verify_accepted_blocker_preservation(root)
    return {
        "schema": "inferswarm.issue129.arm-c-retry-authority/3",
        "issue": "https://github.com/Zutfen-LLC/inferswarm/issues/129",
        "accepted_base": {
            "arm_c_blocker": "ISSUE117_ARM_C_EVIDENCE_BLOCKER",
            "merge": ACCEPTED_BLOCKER_MERGE,
            "arm_b_result": ACCEPTED_ARM_B_RESULT,
            "arm_b_merge": ACCEPTED_ARM_B_MERGE,
        },
        "policy": {
            "additive_history": (
                "accepted #128 evidence paths are never modified, "
                "re-derived, or re-classified at later heads; all #129 "
                "authority, integrity pins, and derived methodology "
                "outputs live under evidence/arm-c-retry/"),
            "historical_blocker_mode": (
                "the accepted #128 blocker reducer runs only in its "
                "historical-verification mode pinned to the accepted "
                "merge (scripts/issue117_arm_c_blocker_reducer.py "
                "reduce_all(head=...) / ARM_C_BLOCKER_HEAD); the live "
                "head is never re-classified"),
            "physical_authorization": (
                "this PR authorizes NO physical Arm-C retry, no GPU "
                "execution, no model execution, no Arm D/E, no holdout "
                "use, and no accepted Arm-B participant-state mutation"),
            "campaign_stop": (
                "a correctness-bearing invalid observation permanently "
                "blocks its campaign_id; a later attempt in that campaign "
                "cannot clear the STOP or produce a verdict; a new campaign "
                "requires a fresh physical authorization and lineage root "
                "issued after maintainer review; the reducer binds every "
                "campaign to a separate accepted authority record, requires "
                "an authoritative terminal to pass, and rejects diagnostic "
                "authority or an intermediate-campaign review bypass"),
        },
        "accepted_blocker_preservation": preservation,
    }


def build_integrity_record(repo_root: Path | None = None) -> dict[str, Any]:
    """The #129 integrity pin record retained additively under
    evidence/arm-c-retry/integrity.json."""
    root = repo_root or _repo_override()
    digests = verify_frozen_bytes(root)
    allocator = extract_runtime_session_allocator(root)
    ingress = extract_coordinator_ingress(root)
    template = derive_template_contract(root)
    fixture = derive_prompt_fixture(root)
    integration = json.loads(
        (root / AREA.relative_to(ROOT) / "evidence" / "integration-fixture.json"
         ).read_text())
    prompt_texts = {
        row["case"]["case_id"]: row["case"]["prompt_text"]
        for row in integration["cases"]}
    content_encodings = {
        prompt_texts[row["case_id"]]: list(row["raw_fixture_token_ids"])
        for row in fixture["cases"]}
    real_tokenizer = run_ordinary_ingress_proof(root)
    return {
        "schema": "inferswarm.issue129.arm-c-retry-integrity/2",
        "frozen_control_plane_pins": digests,
        "pin_policy": (
            "r5b_epochs.py, xc_strategy.py, and coordinator.py pins are "
            "delegated to scripts/issue117_arm_c_frozen_pins.py "
            "(accepted #128 authority; the key must exist, be a valid "
            "sha256, and match the retained bytes — fail closed); "
            "r3_planner.py, r5a_serving.py, and strategy.py are pinned "
            "locally by scripts/issue129_arm_c_retry_core.py"),
        "runtime_session_allocation": allocator.facts,
        "coordinator_ingress_citations": ingress["citations"],
        "template_contract": {
            k: v for k, v in template.items() if k != "schema"},
        "content_encodings_pin": "sha256:" + sha256_bytes(json.dumps(
            content_encodings, sort_keys=True).encode()),
        "tokenizer_asset_pins": REQUIRED_TOKENIZER_ASSETS,
        "tokenizer_software_identity":
            real_tokenizer["tokenizer"]["software"],
        "real_tokenizer_proof": {
            "schema": real_tokenizer["schema"],
            "case_count": real_tokenizer["case_count"],
            "equal_count": real_tokenizer["equal_count"],
            "passed": real_tokenizer["passed"],
            "tokenizer_class": real_tokenizer["tokenizer"]["class"],
            "loader": real_tokenizer["tokenizer"]["loader"],
            "local_files_only":
                real_tokenizer["tokenizer"]["local_files_only"],
            "trust_remote_code":
                real_tokenizer["tokenizer"]["trust_remote_code"],
            "derivation": real_tokenizer["derivation"],
        },
    }


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path,
                        default=ARM_C_RETRY_EVIDENCE / "methodology-run.json")
    parser.add_argument("--write-evidence", action="store_true",
                        help="write methodology-run.json, prompt-fixture.json, "
                             "authority.json, and integrity.json")
    args = parser.parse_args()
    document = run_methodology()
    if args.write_evidence:
        write_canonical_json(args.out, document)
        fixture = derive_prompt_fixture()
        write_canonical_json(
            ARM_C_RETRY_EVIDENCE / "prompt-fixture.json", fixture)
        write_canonical_json(
            ARM_C_RETRY_EVIDENCE / "authority.json",
            build_authority_record())
        write_canonical_json(
            ARM_C_RETRY_EVIDENCE / "integrity.json",
            build_integrity_record())
    print(document["terminal"])
    if document["fixture"]:
        print("fixture_digest", document["fixture"]["fixture_digest"])
    if document["per_case_reduction"]:
        print("equal",
              document["per_case_reduction"]["equal_count"], "/",
              document["per_case_reduction"]["case_count"])
    print("ordinary_ingress_equal",
          document["ordinary_ingress"]["equal_count"], "/",
          document["ordinary_ingress"]["case_count"])
    return 0 if document["terminal"] == METHODOLOGY_READY else 1


if __name__ == "__main__":
    raise SystemExit(main())
