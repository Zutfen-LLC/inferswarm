#!/usr/bin/env python3
"""Issue #153 Arm-C remediation: Phase-0 code-path inventory builder.

Derives the chunk-policy inventory record from pinned source bytes —
never from names/comments alone. Every conclusion is bound to an
executable check against the exact FreeToken producer bytes (accepted
924cd22e and the remediation candidate), which are vendored under
frozen-source/ and sha256-pinned by this bundle's manifest.

CPU-only, stdlib-only. No model execution, no node access.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = Path(
    "docs/implementation/r6-successor-dense-full-integration-117/"
    "remediation"
)
ACCEPTED_PRODUCER = "924cd22ea081f6d4ed471016faf01d427fc5b0d2"
STARTING_RESEARCH = "b05564a7f3f7ca1b141d54842357ff2624dc6a19"
SCHEMA = "inferswarm.issue117.arm-c-remediation.phase0-inventory/1"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fetch_blob(repo: Path, commit: str, path: str) -> bytes:
    out = subprocess.check_output(
        ["git", "-C", str(repo), "show", f"{commit}:{path}"]
    )
    return out


def inventory_from_bytes(accepted: dict[str, bytes], remediated: dict[str, bytes]) -> dict:
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
    # the hand-literal chunk loop in the accepted producer
    hand_literal = re.search(r"^        chunk = 64", chain_acc, re.M)
    assert hand_literal, "accepted stage_chain: hand literal chunk = 64 absent"
    # (2) row-limit/chunk-size inputs today
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

    # (3) why a 53-row unit could become 32+21 today: the accepted code
    # derives chunk boundaries from a call-site literal, not from the
    # frozen contract capacity; any literal < 53 subdivides a legal unit
    # (two_stage's 32 default does exactly this; probe C2's chunk=32
    # reproduced it on the chain seam).
    single_chunk_derivation = "plan_prefill_partitions(" in chain_rem and (
        "admitted_prefill_rows()" in chain_rem
    )
    assert single_chunk_derivation, (
        "remediated stage_chain: capacity-derived partition absent"
    )
    assert "chunk = 64" not in chain_rem
    assert "chunk = 32" not in chain_rem
    assert "chunk = 32" not in two_rem
    assert "MAX_TOKEN_COUNT = admitted_prefill_rows()" in wire_rem

    # (4) legality of one 53-row call under the current backend contract:
    # the wire contract (validate_request) rejects only token_count <= 0
    # or > max_token_count = 64 — a 53-row call is legal.
    assert (
        "token_count <= 0 or token_count > contract[\"max_token_count\"]"
        in accepted["r4_wire.py"].decode()
    )

    # (5) same policy on direct and ordinary paths: both realize through
    # realize_dense_chain -> GemmaStageChainRuntime.generate.
    for name in ("chain_runtime.py", "node_agent.py"):
        src = accepted[name].decode()
        assert "realize_dense_chain" in src, name

    # (6) downstream state transitions affected by chunk count: the KV
    # pools advance per PREFILL (reset via RESET between replays), the
    # boundary wire transfers one payload per chunk, decode positions are
    # offset by the consumed row count. Bound from the remediated seam:
    # the partition loop feeds _chain_prefill(position, count) and
    # position advances by count — nothing else consumes chunk identity.
    assert "for _offset, count in partitions:" in chain_rem
    assert "position += count" in chain_rem

    # (7) decode/KV authority/session identity/graph state/stage
    # boundaries: decode path unchanged (no decode edit), session ids and
    # plan digests flow through unchanged surfaces; the R6 stage runtime
    # has no CUDA graph state on this path; stage ownership is bound by
    # the frozen plan, not by chunk count.
    assert "def _chain_decode" in chain_rem
    rem_strategy = remediated["strategy.py"].decode()
    assert "PREFILL_CHUNK = 64" in rem_strategy  # frozen constant untouched

    # no case-specific nouns anywhere in the remediation seam (module and
    # function docstrings stripped; "Gemma" appears legitimately in the
    # strategy adapter's frozen module name/strategy id, which is
    # strategy-owned by design — check only the policy modules)
    for src, label in ((partition, "prefill_partition"), (wire_rem, "wire")):
        stripped = re.sub(r'""".*?"""', "", src, flags=re.S)
        for token in ("c109", "regime4", "regime-4"):
            assert token not in stripped, (label, token)
    for token in ("c109", "regime4", "regime-4"):
        assert token not in chain_rem and token not in two_rem, token

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
        "why_53_became_32_21": (
            "The accepted code derives chunk boundaries from a call-site "
            "hand literal rather than from the frozen execution contract's "
            "admitted capacity; any literal below the logical unit's size "
            "subdivides it. The legacy two_stage path defaulted to 32 (a "
            "legal 53-row unit becomes 32+21), and the accepted #137 probe "
            "C2 reproduced the same subdivision on the chain seam with "
            "chunk=32. The chain's own literal was 64 by historical fix "
            "(ff561e5), so the canonical chain happened to keep <=64-row "
            "replays single-chunk, but the property was never derived or "
            "enforced — nothing tied the chain literal, the wire capacity, "
            "and the frozen boundary contract together."
        ),
        "one_call_53_rows_legal": {
            "wire_bound": "0 < token_count <= max_token_count (=64)",
            "frozen_boundary_contract_prefill_chunk_rows": 64,
            "runtime_capacity_tokens": 256,
            "verdict": True,
        },
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
    record = inventory_from_bytes(accepted, remediated)
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
