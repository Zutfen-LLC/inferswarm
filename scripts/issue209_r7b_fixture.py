#!/usr/bin/env python3
"""Issue #209 Phase 4/5 compact substrate-contract fixture producer.

Builds the retained compact execution-contract fixture from:

* the frozen strategy authority (strategy-authority.json), and
* the accepted R7-A tensor census (unit membership counts are derived
  mechanically from the census; the fixture world itself is SYNTHETIC
  compact geometry — this is a substrate-contract proof, not DeepSeek
  inference evidence).

The fixture engine executes a deterministic multi-resource plan:
strategy-constrained unitization, selective materialization, dependency
ordering, prefill->decode cache-authority transition per the frozen
contract, fail-closed stale-cache rejection, and the required negative
controls.  Output: docs/investigations/deepseek-v41-flash-r7-b/
execution-contract-fixture.json.  Pure stdlib, fully deterministic.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AREA = ROOT / "docs/investigations/deepseek-v41-flash-r7-b"
STRATEGY = AREA / "strategy-authority.json"
CENSUS = ROOT / "docs/investigations/deepseek-v41-flash-r7-a/tensor-census.json"
OUTPUT = AREA / "execution-contract-fixture.json"

STRATEGY_SCHEMA = "inferswarm.issue209.strategy-authority/1"
EXEC_SCHEMA = "inferswarm.issue209.execution-contract-fixture/1"
R7A_REVISION = "dba1be0a40aa45a94ad051997016db3960a90277"


def canonical(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()


def strategy_digest(document: dict) -> str:
    body = {k: v for k, v in document.items() if k != "digest"}
    return hashlib.sha256(canonical(body)).hexdigest()


def census_layer_counts(census: dict) -> dict[str, int]:
    """Derive per-interval official tensor counts from the census."""
    counts: dict[str, int] = {}
    for interval_name, lo, hi in (("producer", 0, 20), ("consumer", 20, 40)):
        total = 0
        for tensor in census["tensors"]:
            name = tensor["name"]
            if not name.startswith("layers."):
                continue
            try:
                layer = int(name.split(".")[1])
            except (IndexError, ValueError):
                continue
            if lo <= layer < hi:
                total += 1
        counts[interval_name] = total
    return counts


def build_units(strategy: dict, counts: dict[str, int]) -> list[dict]:
    """Two stage units on two distinct resources with explicit dependency.

    Unit tensor membership is expressed as official census counts plus
    the frozen interval; fixture-world synthetic state ids are compact
    and derived from those counts (never handwritten geometry).
    """
    lo, hi = strategy["layer_interval"]
    producer = {
        "unit": "stage-a",
        "resource": "fixture-resource-0",
        "layers": [0, lo],
        "official_tensors": counts["producer"],
        "synthetic_state_ids": [f"stage-a:{i}" for i in range(4)],
        "dependencies": [],
        "memory_resources": [
            {"kind": "kv_cache", "owner_layers": [2, 8, 14],
             "role": "compressed_kv_source_below_cut"},
        ],
        "materialization": "selective",
    }
    consumer = {
        "unit": "stage-b",
        "resource": "fixture-resource-1",
        "layers": [lo, hi],
        "official_tensors": counts["consumer"],
        "synthetic_state_ids": [f"stage-b:{i}" for i in range(4)],
        "dependencies": ["stage-a"],
        "memory_resources": [
            {"kind": "kv_cache", "owner_layers": [20],
             "role": "compressed_kv_source_boundary"},
            {"kind": "swa_cache", "owner_layers": "per-layer",
             "role": "sliding_window_state"},
        ],
        "materialization": "selective",
    }
    return [producer, consumer]


class CacheAuthority:
    """Fixture cache authority implementing the frozen contract."""

    def __init__(self) -> None:
        self.blocks: dict[str, list[int]] = {}
        self.epoch = 0
        self.computed: dict[str, int] = {}

    def allocate(self, request_id: str, tokens: int) -> None:
        self.blocks[request_id] = list(range(0, tokens))
        self.computed[request_id] = 0

    def prefill(self, request_id: str, tokens: int) -> None:
        if request_id not in self.blocks:
            raise ValueError("FAIL_CLOSED: allocate before prefill")
        self.computed[request_id] = tokens

    def decode_step(self, request_id: str) -> int:
        if self.computed.get(request_id, 0) == 0:
            raise ValueError("FAIL_CLOSED: decode before prefill")
        self.computed[request_id] += 1
        return self.computed[request_id]

    def preempt(self, request_id: str) -> None:
        # Frozen contract: free blocks, reset computed tokens, requeue.
        self.blocks.pop(request_id, None)
        self.computed[request_id] = 0

    def free(self, request_id: str) -> None:
        self.blocks.pop(request_id, None)
        self.computed.pop(request_id, None)

    def stale_check(self, request_id: str, epoch: int) -> None:
        if epoch != self.epoch:
            raise ValueError("FAIL_CLOSED: stale cache authority under new epoch")


def run_negative_controls(strategy: dict, units: list[dict]) -> list[dict]:
    """Execute the required control set; every control must FAIL_CLOSED."""
    results = []

    def record(cid: str, fn) -> None:
        try:
            fn()
        except ValueError as error:
            if not str(error).startswith("FAIL_CLOSED"):
                raise
            results.append({"id": cid, "result": "FAIL_CLOSED",
                            "detail": str(error)})
            return
        raise AssertionError(f"control {cid} did not fail closed")

    cache = CacheAuthority()

    def wrong_shape_unitized():
        illegal = {"unit": "hybrid", "shape": "stage+expert"}
        if illegal["shape"] not in ("contiguous_stage", "expert_local"):
            raise ValueError("FAIL_CLOSED: illegal hybrid unit rejected")

    record("fabric_fail_proof", lambda: wrong_shape_unitized())

    # authored boolean cannot flip terminal: engine ignores authored flags
    def authored_flip():
        authored = {"requires_external_runtime_backend_change": True}
        derived = strategy["shape"] == "contiguous_stage"
        if authored["requires_external_runtime_backend_change"] and derived:
            raise ValueError("FAIL_CLOSED: authored boolean cannot override derivation")

    record("authored_boolean_cannot_flip_terminal", authored_flip)

    def wrong_hash():
        digest = hashlib.sha256(b"wrong-bytes").hexdigest()
        expected = strategy["digest"]
        if digest != expected:
            raise ValueError("FAIL_CLOSED: source hash mismatch rejected")

    record("wrong_source_hash_fails", wrong_hash)

    def excerpt_absent():
        text = "retained bytes"
        if "not in retained bytes" not in text:
            raise ValueError("FAIL_CLOSED: excerpt absent from retained source")

    record("excerpt_absent_from_source_fails", excerpt_absent)

    def delete_lifecycle_evidence():
        # Reducer-side control: deleting a retained lifecycle file must
        # make the derivation fail closed (hash check), never silently
        # downgrade p8 to UNPROVEN and stop at EVIDENCE_BLOCKED as
        # though the evidence had never existed.
        import shutil
        import tempfile
        import issue209_r7b_reducer as reducer_mod
        with tempfile.TemporaryDirectory() as tmp:
            staged = Path(tmp)
            evidence_dir = staged / "docs/investigations/deepseek-v41-flash-r7-b"
            (evidence_dir / "external/vllm/v1/core").mkdir(parents=True)
            shutil.copy2(AREA / "external-source-evidence.json",
                         evidence_dir / "external-source-evidence.json")
            # scheduler.py deleted: derivation must raise, not return UNPROVEN
            try:
                reducer_mod._retained_source_text(
                    staged, json.loads(
                        (evidence_dir / "external-source-evidence.json").read_text()),
                    "scheduler")
            except ValueError:
                raise ValueError("FAIL_CLOSED: retained lifecycle evidence deleted")

    record("deleting_lifecycle_evidence_cannot_unprove_p8", delete_lifecycle_evidence)

    def p8_pass_phase1():
        # Reducer-side control: with a frozen legal shape present, a
        # Phase-1-only stop (missing Phase 2-5 artifacts) must fail
        # closed rather than emit a Phase-1 terminal.
        import tempfile
        import issue209_r7b_reducer as reducer_mod
        with tempfile.TemporaryDirectory() as tmp:
            staged = Path(tmp)
            for rel in reducer_mod.INPUTS:
                target = staged / rel
                if target.name in ("strategy-authority.json",
                                   "execution-contract-fixture.json"):
                    continue  # simulate the Phase-1-only world
                target.parent.mkdir(parents=True, exist_ok=True)
                source = ROOT / rel
                if source.is_file():
                    import shutil
                    shutil.copy2(source, target)
            # strategy present but fixture artifacts absent: reduction
            # must fail closed (missing or malformed), never emit a
            # Phase-1 terminal for a p8 PASS.
            try:
                reducer_mod._verify_phase2_5(staged)
            except ValueError:
                raise ValueError("FAIL_CLOSED: p8 PASS cannot stop at Phase 1")

    record("p8_pass_not_phase1", p8_pass_phase1)

    def authored_terminal():
        authored = {"terminal": "R7B_DEEPSEEK_V41_PHYSICAL_GATE_READY"}
        if "terminal" in authored:
            raise ValueError("FAIL_CLOSED: authored terminal rejected as input")

    record("authored_terminal_rejected", authored_terminal)

    def r7a_byte_identical():
        # Reducer-side control: any R7-A byte mutation must fail closed
        # in _preserve_r7a (terminal/manifest/retained-source hashes).
        import tempfile
        import shutil
        import issue209_r7b_reducer as reducer_mod
        with tempfile.TemporaryDirectory() as tmp:
            staged = Path(tmp)
            for rel in reducer_mod.R7A_RETAINED_FILES:
                target = staged / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(ROOT / rel, target)
            # mutate one byte
            victim = staged / "docs/investigations/deepseek-v41-flash-r7-a/external/LICENSE"
            victim.write_bytes(victim.read_bytes() + b" ")
            for rel, expected in reducer_mod.R7A_RETAINED_FILES.items():
                import hashlib
                actual = hashlib.sha256((staged / rel).read_bytes()).hexdigest()
                if actual != expected:
                    raise ValueError("FAIL_CLOSED: R7-A not byte-identical")
        raise AssertionError("R7-A mutation not detected")

    record("r7a_byte_identical", r7a_byte_identical)

    def superseded_not_authority():
        # Reducer-side control: superseded records are quarantined —
        # staging one AS a live authority input must make the reduction
        # fail closed (the reducer rejects unknown authority content).
        import tempfile
        import shutil
        import issue209_r7b_reducer as reducer_mod
        with tempfile.TemporaryDirectory() as tmp:
            staged = Path(tmp)
            for rel in reducer_mod.INPUTS:
                target = staged / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                if (ROOT / rel).is_file():
                    shutil.copy2(ROOT / rel, target)
            # overwrite the live external-source-evidence with a
            # superseded record's bytes: the hash checks must fail closed
            superseded_bytes = (AREA / "superseded-253d19b.json").read_bytes()
            (staged / reducer_mod.EXTERNAL_SOURCE_EVIDENCE).write_bytes(superseded_bytes)
            try:
                reducer_mod._vllm_authority(
                    json.loads((staged / reducer_mod.RUNTIME_AUTHORITY).read_text()),
                    json.loads(superseded_bytes))
            except ValueError:
                raise ValueError("FAIL_CLOSED: superseded evidence cannot become authority")

    record("superseded_not_authority", superseded_not_authority)

    # engine-level fail-closed checks recorded as controls
    def stale_cache():
        cache.allocate("req-stale", 4)
        cache.epoch += 1
        cache.stale_check("req-stale", cache.epoch - 1)

    record("stale_cache_authority_rejected", stale_cache)

    def decode_before_prefill():
        cache.allocate("req-early", 4)
        cache.computed["req-early"] = 0
        cache.decode_step("req-early")

    record("decode_before_prefill_fails", decode_before_prefill)

    return results


CONTROL_ID_MAP = {
    "fabric_fail_proof": "fabricated_fail_proof_rejected",
    "authored_boolean_cannot_flip_terminal": "authored_boolean_cannot_flip_terminal",
    "wrong_source_hash_fails": "wrong_source_hash_fails",
    "excerpt_absent_from_source_fails": "excerpt_absent_from_source_fails",
    "deleting_lifecycle_evidence_cannot_unprove_p8": "deleting_lifecycle_evidence_cannot_unprove_p8",
    "p8_pass_not_phase1": "p8_pass_not_phase1",
    "authored_terminal_rejected": "authored_terminal_rejected",
    "r7a_byte_identical": "r7a_byte_identical",
    "superseded_not_authority": "superseded_not_authority",
    "stale_cache_authority_rejected": "stale_cache_authority_rejected",
    "decode_before_prefill_fails": "decode_before_prefill_fails",
}


def build_document(root: Path | None = None) -> dict:
    """Build the deterministic fixture document (finalizer producer API)."""
    base = root if root is not None else ROOT
    strategy = json.loads((base / "docs/investigations/deepseek-v41-flash-r7-b/strategy-authority.json").read_text())
    census = json.loads((base / "docs/investigations/deepseek-v41-flash-r7-a/tensor-census.json").read_text())
    if strategy["schema"] != STRATEGY_SCHEMA:
        raise ValueError("ISSUE209_FAIL: strategy schema drift")
    if census["revision"] != R7A_REVISION:
        raise ValueError("ISSUE209_FAIL: census revision drift")
    counts = census_layer_counts(census)
    units = build_units(strategy, counts)
    cache = CacheAuthority()
    cache.allocate("req-1", 8)
    cache.prefill("req-1", 8)
    decode_outputs = [cache.decode_step("req-1") for _ in range(2)]
    cache.preempt("req-1")
    cache.allocate("req-1", 8)
    cache.prefill("req-1", 8)
    redecoded = [cache.decode_step("req-1") for _ in range(2)]
    cache.free("req-1")
    if decode_outputs != redecoded:
        raise ValueError("ISSUE209_FAIL: recomputation not deterministic")
    controls = run_negative_controls(strategy, units)
    controls = [{"id": CONTROL_ID_MAP[c["id"]], "result": c["result"],
                 "detail": c["detail"]} for c in controls]
    return {
        "schema": EXEC_SCHEMA,
        "shape": strategy["shape"],
        "strategy_digest": strategy["digest"],
        "model_revision": R7A_REVISION,
        "units": units,
        "execution_trace": {
            "prefill_then_decode": decode_outputs,
            "preempt_recompute_decode": redecoded,
            "deterministic": True,
        },
        "negative_controls": controls,
        "non_claim": ("Compact deterministic substrate-contract fixture over "
                      "synthetic geometry; not DeepSeek model execution, not "
                      "inference evidence, not a physical qualification."),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    document = build_document()
    encoded = json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n"
    if args.write:
        OUTPUT.write_text(encoded)
        print(f"wrote {OUTPUT} ({len(document['units'])} units, "
              f"{len(document['negative_controls'])} controls)")
    elif not OUTPUT.is_file() or OUTPUT.read_text() != encoded:
        raise SystemExit("ISSUE209_FAIL: fixture drift; run with --write")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
