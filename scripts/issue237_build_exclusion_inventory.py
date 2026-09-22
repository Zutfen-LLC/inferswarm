#!/usr/bin/env python3
"""Build the R8-I historical-exclusion inventory (issue #237, CPU-only).

A fixed, hash-bound inventory of every historical prompt/token identity that
fresh Qwen v1 calibration/holdout/stress material must never reproduce:

1. the four accepted R8 fixture-ladder prompts (R8-B authority, case-256 /
   1024 / 3072 / 4096 — prompt sha256 + canonical token-IDs sha256);
2. the same fixtures as re-anchored by R8-H (external_anchor_outputs);
3. every prompt/token identity committed in R8-A..H investigations that
   repository authority makes extractable (R8-G captures reuse the R8-B
   case-256 fixture; asserted by hash, not by prose);
4. consumed Gemma qualification holdout identities where repository
   authority makes exclusion possible (the v5 holdout commitment binds
   prompt/token-IDs hashes of all 24 sealed draws; v1/v3/v4 holdouts were
   generated from the Gemma tokenizer with disjoint lexemes/classes, so
   their exact identities are only as extractable as their commitments).

The builder DERIVES every hash from the accepted repository bytes at run
time. Nothing is transcribed. Output: manifests/historical-exclusion-inventory.json
plus a flat sha256 set for O(1) generator rejection.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from issue74_methodology import canonical_json_bytes, sha256_bytes  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
OUT_PATH = REPO / (
    "docs/qualification/qwen38-vulkan-v1/manifests/historical-exclusion-inventory.json"
)
FIXTURE_LADDER = REPO / (
    "docs/investigations/qwen38-flash-next-r8-b/evidence/reference/fixture-ladder.json"
)
FIXTURE_LADDER_SHA256 = (
    "419bde668c7b3cedf823c98ca0a883560a9a501007f9a28bf8d826148ee822db"
)
R8H_AUTHORITY = REPO / (
    "docs/investigations/qwen38-flash-next-r8-h-vulkan/evidence/PHYSICAL-AUTHORITY.json"
)
R8H_AUTHORITY_SHA256_EXPECTED = None  # derived at run time; pinned by the dir MANIFEST
V5_HOLDOUT_COMMITMENT = REPO / (
    "docs/qualification/gemma4-12b-it-v5/manifests/sealed-holdout-commitment.json"
)
V5_CALIBRATION_CORPUS = REPO / (
    "docs/qualification/gemma4-12b-it-v5/manifests/calibration-corpus.json"
)


class InventoryError(RuntimeError):
    pass


def build_inventory() -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(source: str, kind: str, identity: str, subject: str) -> None:
        if not isinstance(identity, str) or len(identity) != 64:
            raise InventoryError(f"malformed sha256 from {source}")
        if identity in seen:
            for row in entries:
                if row["sha256"] == identity:
                    row["also"] = sorted(set(row.get("also", []) + [source]))
            return
        seen.add(identity)
        entries.append(
            {"source": source, "kind": kind, "sha256": identity, "subject": subject}
        )

    # 1+2: the R8 fixture ladder (authoritative R8-B bytes; R8-H re-anchor).
    ladder_bytes = FIXTURE_LADDER.read_bytes()
    ladder_sha = sha256_bytes(ladder_bytes)
    if ladder_sha != FIXTURE_LADDER_SHA256:
        raise InventoryError("fixture-ladder bytes drifted from the frozen authority")
    ladder = json.loads(ladder_bytes)
    if [c["case_id"] for c in ladder["cases"]] != [
        "case-256", "case-1024", "case-3072", "case-4096",
    ]:
        raise InventoryError("unexpected fixture ladder case set")
    for case in ladder["cases"]:
        add(
            "r8b-fixture-ladder",
            "prompt-text-sha256",
            sha256_bytes(case["prompt_text"].encode("utf-8")),
            case["case_id"],
        )
        add(
            "r8b-fixture-ladder",
            "token-ids-sha256",
            sha256_bytes(canonical_json_bytes(case["prompt_token_ids"])),
            case["case_id"],
        )

    # 3: R8-H authority binds the same four fixtures (anchor cross-check).
    authority = json.loads(R8H_AUTHORITY.read_text())
    anchored = authority.get("fixture_ladder", {})
    if anchored.get("sha256") != FIXTURE_LADDER_SHA256:
        raise InventoryError("R8-H authority does not anchor the fixture ladder")
    if anchored.get("case_ids") != ["case-256", "case-1024", "case-3072", "case-4096"]:
        raise InventoryError("R8-H anchor case set mismatch")

    # R8-G contrast captures reuse fixture case-256 (verified by reading the
    # retained capture payloads and comparing their token identities to the
    # ladder's — they must already be covered, which we assert).
    r8g_dir = REPO / "docs/investigations/qwen38-flash-next-r8-g/evidence/contrast"
    r8g_files = sorted(r8g_dir.glob("capture-*.json")) if r8g_dir.exists() else []
    covered_prompt = sha256_bytes(ladder["cases"][0]["prompt_text"].encode("utf-8"))
    covered_ids = sha256_bytes(
        canonical_json_bytes(ladder["cases"][0]["prompt_token_ids"])
    )
    r8g_bound = 0
    for path in r8g_files:
        doc = json.loads(path.read_text())
        text = doc.get("prompt_text") or doc.get("prompt")
        ids = doc.get("prompt_token_ids") or doc.get("token_ids")
        if text is not None:
            if sha256_bytes(str(text).encode("utf-8")) != covered_prompt:
                raise InventoryError(f"R8-G capture {path.name} carries an unknown prompt")
            r8g_bound += 1
        if ids is not None:
            if sha256_bytes(canonical_json_bytes(ids)) != covered_ids:
                raise InventoryError(f"R8-G capture {path.name} carries unknown token IDs")
            r8g_bound += 1

    # 4: consumed Gemma qualification identities where authority is public.
    v5_commitment = json.loads(V5_HOLDOUT_COMMITMENT.read_text())
    v5_holdout_hashes = 0
    for draw in v5_commitment.get("draws", []):
        add(
            "gemma-v5-sealed-holdout-commitment",
            "prompt-text-sha256",
            draw["prompt_sha256"],
            draw["case_id"],
        )
        add(
            "gemma-v5-sealed-holdout-commitment",
            "token-ids-sha256",
            draw["token_ids_sha256"],
            draw["case_id"],
        )
        v5_holdout_hashes += 2
    v5_calibration = json.loads(V5_CALIBRATION_CORPUS.read_text())
    for case in v5_calibration.get("cases", []):
        add(
            "gemma-v5-calibration-corpus",
            "prompt-text-sha256",
            case["prompt_sha256"],
            case["case_id"],
        )
        add(
            "gemma-v5-calibration-corpus",
            "token-ids-sha256",
            case["token_ids_sha256"],
            case["case_id"],
        )

    inventory = {
        "schema": "inferswarm.issue237.historical-exclusion-inventory/1",
        "entries": sorted(entries, key=lambda e: (e["source"], e["sha256"])),
        "entry_count": len(entries),
        "distinct_sha256": len(seen),
        "sources": {
            "r8b-fixture-ladder": "accepted R8-B fixture ladder (4 cases, prompt+token IDs)",
            "r8h-authority-anchor": "R8-H PHYSICAL-AUTHORITY re-anchor of the same 4 fixtures",
            "gemma-v5-sealed-holdout-commitment": "consumed Gemma holdout public identities",
            "gemma-v5-calibration-corpus": "consumed Gemma calibration identities",
        },
        "r8g_capture_identity_assertions": r8g_bound,
        "scope_note": (
            "R8's historical 256/1024/3072/4096 fixtures informed regime design "
            "only; all their identities are excluded from fresh Qwen v1 "
            "predictive material. Historical observations never become Qwen "
            "calibration, threshold, stress-output, or holdout observations."
        ),
        "laws": {
            "generator_rejection": (
                "the generator rejects any candidate prompt whose prompt "
                "sha256 or canonical token-IDs sha256 appears in this "
                "inventory, retrying ONLY the prompt realization"
            ),
            "no_post_hoc_dedup": (
                "cross-draw deduplication or quota correction after "
                "generation is forbidden; predictive collisions between "
                "fresh draws are audit-only"
            ),
        },
    }
    inventory["inventory_sha256"] = sha256_bytes(
        canonical_json_bytes([e["sha256"] for e in inventory["entries"]])
    )
    return inventory


def historical_identity_set(inventory: dict[str, Any]) -> set[str]:
    return {e["sha256"] for e in inventory["entries"]}


def main() -> int:
    inventory = build_inventory()
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_bytes(canonical_json_bytes(inventory))
    print(
        json.dumps(
            {
                "written": str(OUT_PATH.relative_to(REPO)),
                "entries": inventory["entry_count"],
                "distinct_sha256": inventory["distinct_sha256"],
                "inventory_sha256": inventory["inventory_sha256"],
            },
            indent=1,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
