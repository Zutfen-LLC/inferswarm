#!/usr/bin/env python3
"""Issue #234 — R8-H immutable intended-identity authority builder.

`build` derives R8-H's authority exclusively from accepted predecessor
BYTES in this repository (paths/sha pinned through each predecessor's
own accepted MANIFEST.sha256 row, every file re-hashed at build — a
hand-copied digest always drifts):

  R8-D (#195/PR #197) — the frozen true-greedy reference + fixture
       ladder this campaign's candidate ladder must reproduce;
  R8-A (#189/PR #190) — model/representation identity authority;
  V2-G (#232/PR #233) — V340L platform/path predecessor (hardware
       authority context; no execution permission flows from it);
  V2-F (#230/PR #231) — historical amdgpu platform-fault context.

Nonclaims: this document authorizes NO physical execution by itself.
It binds intended identity only; every physical observation requires a
fresh census receipt on the current boot, bound by Vulkan
physical-device UUID -> BDF -> switch ancestry (historical BDFs never
authorize anything after hardware movement or reboot).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import issue234_receipt as rc

ROOT = rc.ROOT


def _manifest_rows(ns_dir: Path) -> dict[str, str]:
    man = ns_dir / "MANIFEST.sha256"
    rows: dict[str, str] = {}
    prefix = ns_dir.relative_to(ROOT).as_posix() + "/"
    for line in man.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        digest, _, rel = line.partition(" ")
        rel = rel.strip()
        # accept both repo-root-relative and ns-relative spellings
        if rel.startswith(prefix):
            rows[rel] = digest
        else:
            rows[prefix + rel] = digest
    return rows


def _verify_against_manifest(ns_dir: Path, rels: list[str]) -> dict[str, dict]:
    """Re-hash each predecessor file and compare with its accepted
    MANIFEST row. Any drift is fatal (predecessor bytes are immutable)."""
    rows = _manifest_rows(ns_dir)
    out: dict[str, dict] = {}
    for rel in rels:
        full_rel = rels and (ns_dir.name + "/" + rel if not rel.startswith(ns_dir.name) else rel)
        path = ns_dir / rel if not rel.startswith("..") else None
        # rels are given relative to the investigation dir
        target = ns_dir / rel
        if not target.is_file():
            raise SystemExit(f"authority input missing: {target}")
        manifest_rel = f"{ns_dir.relative_to(ROOT)}/{rel}".replace("\\", "/")
        expected = rows.get(manifest_rel)
        if expected is None:
            raise SystemExit(f"not pinned in accepted MANIFEST: {manifest_rel}")
        actual = hashlib.sha256(target.read_bytes()).hexdigest()
        if actual != expected:
            raise SystemExit(
                f"predecessor byte drift: {manifest_rel} "
                f"{actual} != {expected}")
        out[manifest_rel] = {"sha256": actual, "bytes": target.stat().st_size}
    return out


def build(repo: Path | None = None) -> dict[str, Any]:
    repo = (repo or ROOT).resolve()
    inv = repo / "docs" / "investigations"

    r8d_files = _verify_against_manifest(
        inv / "qwen38-flash-next-r8-d",
        ["evidence/reference/frozen-reference.json",
         "terminal-reduction.json"],
    )
    r8b_fixture = _verify_against_manifest(
        inv / "qwen38-flash-next-r8-b",
        ["evidence/reference/fixture-ladder.json",
         "evidence/split-identity/split-verification.json"],
    )
    r8d_split = _verify_against_manifest(
        inv / "qwen38-flash-next-r8-d",
        ["evidence/split-identity/split-rehash.json"],
    )
    v2g_files = _verify_against_manifest(
        inv / "vulkan-v2-g-pcie-path-remediation",
        ["evidence/TERMINAL.json"],
    )
    v2f_files = _verify_against_manifest(
        inv / "vulkan-v2-f-v340l-external-memory",
        ["evidence/TERMINAL.json"],
    )

    # Cross-bind the fixture ladder identity the issue text pins.
    fixture = json.loads((inv / "qwen38-flash-next-r8-b" /
                          "evidence/reference/fixture-ladder.json")
                         .read_text(encoding="utf-8"))
    fixture_bytes = (inv / "qwen38-flash-next-r8-b" /
                     "evidence/reference/fixture-ladder.json").read_bytes()
    fixture_sha = hashlib.sha256(fixture_bytes).hexdigest()
    if fixture_sha != rc.R8D_FIXTURE_SHA256:
        raise SystemExit(
            f"fixture ladder identity drift: {fixture_sha} != "
            f"{rc.R8D_FIXTURE_SHA256}")
    case_ids = [c["case_id"] for c in fixture["cases"]]
    if tuple(case_ids) != rc.LADDER_CASES:
        raise SystemExit(f"fixture case set mismatch: {case_ids}")

    # Cross-bind the frozen reference per-case expected outputs.
    reference = json.loads((inv / "qwen38-flash-next-r8-d" /
                            "evidence/reference/frozen-reference.json")
                           .read_text(encoding="utf-8"))
    r8d_terminal = json.loads(
        (inv / "qwen38-flash-next-r8-d" / "terminal-reduction.json")
        .read_text(encoding="utf-8"))
    if r8d_terminal.get("terminal") != \
            "R8D_QWEN38_TRUE_GREEDY_NVIDIA_RPC_QUALIFICATION_FAIL":
        raise SystemExit(
            f"R8-D terminal drift: {r8d_terminal.get('terminal')!r}")

    # The comparison domain: the REFERENCE arm outputs (the accepted
    # R8-D same-model/same-runtime true-greedy reference), NOT the R8-D
    # candidate (RPC) outputs — the issue asks whether the Vulkan
    # candidate reproduces "the accepted R8-D same-model/same-runtime
    # true-greedy reference outputs".
    for case_id in rc.LADDER_CASES:
        if case_id not in reference["cases"]:
            raise SystemExit(f"reference missing case: {case_id}")

    authority = {
        "schema": "inferswarm.r8h.authority/1",
        "campaign": rc.CAMPAIGN_ID,
        "predecessor_merges": {
            "r8a": rc.R8A_MERGE,
            "r8d": rc.R8D_MERGE,
            "r8f": rc.R8F_MERGE,
            "r8g": rc.R8G_MERGE,
            "v2e": rc.V2E_MERGE,
            "v2f": rc.V2F_MERGE,
            "v2g": rc.V2G_MERGE,
            "start_main": rc.START_MAIN,
        },
        "model_authority": {
            "official_qwen_revision": rc.OFFICIAL_QWEN_REVISION,
            "unsloth_revision": rc.UNSLOTH_REVISION,
            "representation": rc.REPRESENTATION,
            "total_bytes": rc.TOTAL_MODEL_BYTES,
            "members": list(rc.MODEL_MEMBERS),
            "split_verification_bytes":
                r8b_fixture["docs/investigations/qwen38-flash-next-r8-b/"
                            "evidence/split-identity/"
                            "split-verification.json"],
            "r8d_rehash_bytes":
                r8d_split["docs/investigations/qwen38-flash-next-r8-d/"
                          "evidence/split-identity/split-rehash.json"],
        },
        "runtime_authority": {
            "llama_cpp_pin": rc.LLAMA_CPP_PIN,
            "request_contract": rc.REQUEST_CONTRACT,
        },
        "fixture_ladder": {
            "sha256": fixture_sha,
            "cases": case_ids,
            "prompt_lengths": {
                c["case_id"]: len(c["prompt_token_ids"]) for c in fixture["cases"]
            },
        },
        "reference_outputs": {
            case_id: {
                "generated_tokens": reference["cases"][case_id]["generated_tokens"],
                "stop_type": reference["cases"][case_id]["stop_type"],
                "prompt_len": reference["cases"][case_id]["prompt_len"],
            }
            for case_id in rc.LADDER_CASES
        },
        "predecessor_files": {**r8d_files, **r8b_fixture,
                              **v2g_files, **v2f_files},
        "nonclaims": [
            "This document binds intended identity only; it authorizes no "
            "physical execution.",
            "Historical BDFs/selectors are not current authority after "
            "hardware movement or reboot.",
            "R8-G divergence characterization is diagnostic context, not a "
            "Vulkan defect claim or repair authorization.",
        ],
    }
    return authority


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path,
                    default=rc.ROOT / rc.AREA_REL / "PHYSICAL-AUTHORITY.json")
    args = ap.parse_args(argv)
    doc = build()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n",
                        encoding="utf-8")
    print(f"wrote {args.out} ({len(doc['predecessor_files'])} pinned files)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
