#!/usr/bin/env python3
"""Issue #153 Arm-C remediation: Phase-0 code-path inventory builder.

Derives the chunk-policy inventory record from pinned source bytes —
never from names/comments alone. Every conclusion is bound to an
executable check against the exact FreeToken producer bytes (accepted
924cd22e and the remediation candidate) and, after the maintainer
correction, the ACCEPTED #137 population facts are derived from the
retained, hash-pinned diagnosis record bytes.

Corrected classification: Branch B (BACKEND_REQUIRES_MULTI_CHUNK).  The
six divergent Arm-C cases are exactly the multi-chunk population
(prompt_len 65-67, all > PREFILL_CHUNK=64; every stable case <= 53).
A 65-67-row single backend call is ILLEGAL under the frozen contract
(wire bound, frozen boundary geometry, wire buffer sizing), so branch A
(UNNECESSARY_PARTITION_POLICY) is unavailable for the actual failing
logical units; it was wrongly derived from the C2 53-row control's
one-call legality and is withdrawn.

CPU-only, stdlib-only. No model execution, no node access.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = Path(
    "docs/implementation/r6-successor-dense-full-integration-117/"
    "remediation"
)
ACCEPTED_PRODUCER = "924cd22ea081f6d4ed471016faf01d427fc5b0d2"
STARTING_RESEARCH = "b05564a7f3f7ca1b141d54842357ff2624dc6a19"
SCHEMA = "inferswarm.issue117.arm-c-remediation.phase0-inventory/2"

# The accepted #137 diagnosis record this builder binds the population
# facts to (never re-typed: read + sha256-pinned from the repo bytes).
I137_INVENTORY_REL = Path(
    "docs/implementation/r6-successor-dense-full-integration-117/"
    "evidence/arm-c-regime4-diagnosis-137/phase1-inventory.json"
)
I137_DIAG_CONCLUSIONS_REL = Path(
    "docs/implementation/r6-successor-dense-full-integration-117/"
    "evidence/arm-c-regime4-diagnosis-137/diagnostic-conclusions.json"
)
I137_INVENTORY_SHA256 = (
    "369b2c81faf8ed1b2a68b1e1d039d6e6e7924d02254443c4707ad1b006ac7b3f"
)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fetch_blob(repo: Path, commit: str, path: str) -> bytes:
    out = subprocess.check_output(
        ["git", "-C", str(repo), "show", f"{commit}:{path}"]
    )
    return out


def load_pinned_i137(root: Path) -> dict:
    """Load the accepted #137 inventory record and fail closed on drift."""
    path = root / I137_INVENTORY_REL
    data = path.read_bytes()
    digest = sha256_bytes(data)
    if digest != I137_INVENTORY_SHA256:
        raise SystemExit(
            f"accepted #137 inventory drifted: {digest} != pinned"
        )
    record = json.loads(data)
    chunk_partition = record["chunk_partition"]
    if not chunk_partition["two_chunk_equals_divergent_population"]:
        raise SystemExit(
            "accepted #137 record no longer binds two-chunk == divergent"
        )
    if chunk_partition["prefill_chunk"] != 64:
        raise SystemExit("accepted #137 prefill_chunk is not 64")
    return record


def accepted_population_facts(root: Path) -> dict:
    """Derive the failing/stable population facts from pinned #137 bytes.

    Returns the EXACT accepted population: the six divergent cases, their
    prompt lens (must all be 65-67), the stable population max (must be
    <= 53), and the frozen chunk size (64).
    """
    record = load_pinned_i137(root)
    cp = record["chunk_partition"]
    cases = cp["cases"]
    divergent_ids = cp["two_chunk_population"]
    lens = sorted(int(cases[c]["prompt_len"]) for c in divergent_ids)
    if lens != [65, 65, 66, 67, 67, 67]:
        raise SystemExit(
            f"accepted divergent prompt lens are not 65-67: {lens}"
        )
    stable_max = int(cp["max_single_chunk_len"])
    if stable_max > 53:
        raise SystemExit(f"stable max {stable_max} exceeds 53")
    return {
        "divergent_case_ids": divergent_ids,
        "divergent_prompt_lens": lens,
        "failing_population_rows": [65, 66, 67],
        "stable_max_prompt_len": stable_max,
        "prefill_chunk": int(cp["prefill_chunk"]),
        "two_chunk_equals_divergent_population": True,
        "pinned_record": {
            "path": I137_INVENTORY_REL.as_posix(),
            "sha256": I137_INVENTORY_SHA256,
        },
    }


def inventory_from_bytes(
    accepted: dict[str, bytes],
    remediated: dict[str, bytes],
    population: dict,
) -> dict:
    """Build every Phase-0 conclusion from the pinned bytes."""
    chain_acc = accepted["stage_chain.py"].decode()
    chain_rem = remediated["stage_chain.py"].decode()
    two_acc = accepted["two_stage.py"].decode()
    two_rem = remediated["two_stage.py"].decode()
    wire_acc = accepted["last_stage_service.py"].decode()
    wire_rem = remediated["last_stage_service.py"].decode()
    strategy = accepted["strategy.py"].decode()
    partition = remediated["prefill_partition.py"].decode()

    # (1) exact function/module deciding extend-prefill chunk boundaries
    owner_accepted = "GemmaStageChainRuntime.generate"
    owner_match = re.search(
        r"class GemmaStageChainRuntime.*?def generate\(", chain_acc, re.S
    )
    assert owner_match, "accepted stage_chain: generate() not found"
    hand_literal = re.search(r"^        chunk = 64", chain_acc, re.M)
    assert hand_literal, "accepted stage_chain: hand literal chunk = 64 absent"
    inputs = {
        "accepted_stage_chain_chunk_literal": 64,
        "accepted_two_stage_chunk_literal": 32,
        "accepted_last_stage_MAX_TOKEN_COUNT": 64,
        "strategy_PREFILL_CHUNK": int(
            re.search(r"^PREFILL_CHUNK = (\d+)", strategy, re.M).group(1)
        ),
        "wire_validate_request_bound": "contract['max_token_count']",
    }
    two32 = re.search(r"^        chunk = 32", two_acc, re.M)
    assert two32, "accepted two_stage: chunk = 32 absent"
    wire64 = re.search(r"^MAX_TOKEN_COUNT = 64", wire_acc, re.M)
    assert wire64, "accepted last_stage_service: MAX_TOKEN_COUNT = 64 absent"

    # (2) corrected remediation shape: capacity-derived partition, the
    # wire service derives the SAME frozen constant directly from
    # strategy (corrected ownership: strategy -> chain + wire service),
    # and the nanosecond timing contract is restored.
    assert "plan_prefill_partitions(" in chain_rem and (
        "admitted_prefill_rows()" in chain_rem
    ), "remediated stage_chain: capacity-derived partition absent"
    assert "chunk = 64" not in chain_rem
    assert "chunk = 32" not in chain_rem
    assert "chunk = 32" not in two_rem
    assert (
        "from benchmarks.inferswarm_r6.strategy import PREFILL_CHUNK "
        "as MAX_TOKEN_COUNT" in wire_rem
    ), "remediated last_stage_service: strategy-derived capacity absent"
    assert (
        "from benchmarks.inferswarm_r6.stage_chain import" not in wire_rem
    ), "remediated last_stage_service still imports the chain runtime"
    two_rem_ns = "prefill_ns += time.perf_counter_ns() - t" in two_rem and (
        "time.perf_counter()" not in two_rem
    )
    assert two_rem_ns, "remediated two_stage: nanosecond timing not restored"

    # (3) BRANCH DECISION, corrected: one 65-67-row call is ILLEGAL under
    # the frozen contract — the wire validate_request rejects
    # token_count > max_token_count (=64), and the frozen boundary
    # geometry sizes the boundary bytes and activation staging buffers
    # at exactly 64 rows.  The accepted failing population therefore
    # REMAINS multi-chunk under any admissible unchanged contract.
    wire_reject = (
        "token_count <= 0 or token_count > contract[\"max_token_count\"]"
        in accepted["r4_wire.py"].decode()
    )
    assert wire_reject, "accepted r4_wire: max_token_count bound absent"
    strategy_binds = (
        '"prefill_bytes": PREFILL_CHUNK * HIDDEN_SIZE * 2' in strategy
        and "activation-staging-buffers" in strategy
    )
    assert strategy_binds, "frozen geometry does not bind 64-row sizing"
    assert "buffer_bytes = MAX_TOKEN_COUNT * ROW_WIDTH * 2" in wire_rem

    # (4) same policy on direct and ordinary paths: both realize through
    # realize_dense_chain -> GemmaStageChainRuntime.generate.
    for name in ("chain_runtime.py", "node_agent.py"):
        src = accepted[name].decode()
        assert "realize_dense_chain" in src, name

    # (5) downstream state transitions affected by chunk count: the KV
    # pools advance per PREFILL (reset via RESET between replays), the
    # boundary wire transfers one payload per chunk, decode positions are
    # offset by the consumed row count.
    assert "for _offset, count in partitions:" in chain_rem
    assert "position += count" in chain_rem

    # (6) decode/KV authority/session identity/graph state/stage
    # boundaries: decode path unchanged (no decode edit), session ids and
    # plan digests flow through unchanged surfaces.
    assert "def _chain_decode" in chain_rem
    rem_strategy = remediated["strategy.py"].decode()
    assert "PREFILL_CHUNK = 64" in rem_strategy  # frozen constant untouched

    # no case-specific nouns anywhere in the remediation seam
    for src, label in ((partition, "prefill_partition"), (wire_rem, "wire")):
        stripped = re.sub(r'""".*?"""', "", src, flags=re.S)
        for token in ("c109", "regime4", "regime-4"):
            assert token not in stripped, (label, token)
    for token in ("c109", "regime4", "regime-4"):
        assert token not in chain_rem and token not in two_rem, token

    failing_rows = population["failing_population_rows"]
    return {
        "schema": SCHEMA,
        "chunk_policy_owner": {
            "function": owner_accepted,
            "module": "benchmarks/inferswarm_r6/stage_chain.py",
            "accepted_line_class": "hand literal chunk = 64 inside generate()",
            "remediated_line_class": (
                "plan_prefill_partitions(len(prompt), admitted_prefill_rows()) "
                "inside the same generate()"
            ),
        },
        "row_limit_inputs": inputs,
        "accepted_137_population": population,
        "branch_classification": {
            "branch": "BACKEND_REQUIRES_MULTI_CHUNK",
            "branch_a_available": False,
            "branch_a_withdrawn_rationale": (
                "UNNECESSARY_PARTITION_POLICY was derived from the C2 "
                "53-row control's one-call legality; C2 proves only that "
                "partitioning is SUFFICIENT for instability on a stable "
                "input, not that the accepted 65-67-row failing units "
                "can legally be one call.  Under the frozen contract "
                "(wire max_token_count=64, boundary bytes and staging "
                "buffers sized 64*3840*2), a 65-67-row single call is "
                "inadmissible; making it legal would change a frozen "
                "semantic/wire contract, which exceeds #153 authority.  "
                "Branch A is therefore WITHDRAWN for the actual failing "
                "population."
            ),
            "branch_b_rationale": (
                "The complete actual failing logical units (65-67 rows) "
                "MUST remain multi-chunk (64 + remainder) under the "
                "frozen contract.  The corrected candidate keeps that "
                "path byte-identical to the accepted producer."
            ),
            "branch_b_option_1_available_cpu_only": False,
            "branch_b_option_1_rationale": (
                "Source inspection of the required multi-chunk extend "
                "path (stage_runtime._make_batch -> triton "
                "prepare_metadata -> extend_paged_attention, and the "
                "1-row second-chunk decode-kernel route) found no "
                "provable backend/state defect: metadata and causal "
                "semantics are correct, tiles are fixed (no autotune), "
                "no atomics, KV writes land at the passed position.  "
                "The #137 record shows the instability is "
                "execution-level (3/6 cases vary in-session; 3 are "
                "stable per-session but distinct across sessions) — "
                "not a CPU-provable state wiring defect.  Identifying "
                "a defect would require new physical evidence, which "
                "is not authorized."
            ),
            "terminal": "ISSUE117_ARM_C_REMEDIATION_BLOCKED",
        },
        "failing_population_single_call_legal": {
            "rows": failing_rows,
            "verdict": False,
            "wire_bound": "0 < token_count <= max_token_count (=64)",
            "frozen_boundary_contract_prefill_chunk_rows": 64,
            "frozen_geometry_sizing": (
                "prefill_bytes = 64*3840*2; activation staging buffers "
                "sized 64*2*3840*2; wire receive buffer "
                "MAX_TOKEN_COUNT*ROW_WIDTH*2"
            ),
            "runtime_capacity_tokens": 256,
            "runtime_capacity_note": (
                "session KV capacity, NOT per-call boundary authority"
            ),
        },
        "one_call_53_rows_legal_control_only": {
            "wire_bound": "0 < token_count <= max_token_count (=64)",
            "frozen_boundary_contract_prefill_chunk_rows": 64,
            "runtime_capacity_tokens": 256,
            "verdict": True,
            "role": (
                "causal CONTROL from #137 probe C2 (single 53-row call "
                "deterministic; 32+21 varied); proves partitioning is "
                "sufficient for instability on a stable input — NOT "
                "legality of a 65-67-row single call"
            ),
        },
        "remediation_scope_of_the_candidate": (
            "The <=64 single-chunk policy cleanup (capacity-derived, "
            "no drifting literals, wire/chain agreement) is RETAINED as "
            "useful: it removes the unnecessary-partition DEFECT CLASS "
            "for legal units.  It does NOT remediate the accepted "
            "65-67 failing population, whose canonical execution path "
            "is unchanged (64 + remainder, same requests)."
        ),
        "same_policy_direct_and_ordinary": (
            "Both paths drive realize_dense_chain -> "
            "GemmaStageChainRuntime.generate (single seam)"
        ),
        "downstream_chunk_count_dependents": [
            "per-stage KV pool advance (RESET between replays)",
            "one boundary wire payload per chunk",
            "decode position offset by consumed rows",
        ],
        "chunk_count_independent": [
            "decode path (untouched)",
            "session/request identity",
            "plan/candidate identity and digests",
            "fencing / epoch / position attribution",
            "stage ownership (frozen plan)",
        ],
    }


def build(repo: Path, remediated_commit: str) -> dict:
    paths = {
        "stage_chain.py": "benchmarks/inferswarm_r6/stage_chain.py",
        "two_stage.py": "benchmarks/inferswarm_r6/two_stage.py",
        "last_stage_service.py": "benchmarks/inferswarm_r6/last_stage_service.py",
        "chain_runtime.py": "benchmarks/inferswarm_r6/chain_runtime.py",
        "node_agent.py": "benchmarks/inferswarm_r6/node_agent.py",
        "strategy.py": "benchmarks/inferswarm_r6/strategy.py",
        "r4_wire.py": "python/freetoken/research/r4_wire.py",
    }
    accepted = {k: fetch_blob(repo, ACCEPTED_PRODUCER, p) for k, p in paths.items()}
    remediated = dict(accepted)
    for k, p in paths.items():
        remediated[k] = fetch_blob(repo, remediated_commit, p)
    remediated["prefill_partition.py"] = fetch_blob(
        repo, remediated_commit, "python/freetoken/research/prefill_partition.py"
    )
    population = accepted_population_facts(ROOT)
    record = inventory_from_bytes(accepted, remediated, population)
    record["inputs"] = {
        "accepted_producer": ACCEPTED_PRODUCER,
        "starting_research_base": STARTING_RESEARCH,
        "remediation_producer": remediated_commit,
        "pinned_blobs": {
            name: {
                "path": (
                    paths.get(name)
                    or "python/freetoken/research/prefill_partition.py"
                ),
                "accepted_sha256": sha256_bytes(accepted.get(name, b"")),
                "remediated_sha256": sha256_bytes(remediated[name]),
            }
            for name in sorted(set(accepted) | set(remediated))
        },
    }
    return record


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--freetoken-repo", default=str(ROOT.parent / "FreeToken"))
    parser.add_argument("--remediation-commit", default=None)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args(argv)
    repo = Path(args.freetoken_repo).resolve()
    commit = args.remediation_commit
    if commit is None:
        commit = subprocess.check_output(
            ["git", "-C", str(repo), "rev-parse", "HEAD"], text=True
        ).strip()
    record = build(repo, commit)
    rendered = json.dumps(record, indent=2, sort_keys=True) + "\n"
    if args.write:
        target = ROOT / BUNDLE / "evidence" / "phase0-inventory.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(rendered)
        print(f"wrote {target}")
    else:
        sys.stdout.write(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
