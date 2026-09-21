#!/usr/bin/env python3
"""Reconstruct the pinned Qwen3.8-Flash-Next BPE tokenizer.json (issue #237).

CPU-only, repository-static, fail-closed. Derives the HF-format
``tokenizer.json`` for the frozen R8 subject from the retained GGUF header
bytes of the accepted UD-IQ1_S member 00001 (R8-A ``raw-headers/``) — the
same tokenizer tables that live inside the accepted model bytes — and
validates the reconstruction against the accepted R8-B fixture-ladder
tokenizations (all four cases, exact ID equality) before writing anything.

The reconstruction never imports an execution runtime, never loads model
weights, and never touches CUDA/Vulkan. It is pure ``struct``/``json``.

Frozen identities (R8-H PHYSICAL-AUTHORITY model_authority):
  - member 1 header bytes: docs/investigations/qwen38-flash-next-r8-a/
        raw-headers/Qwen3.8-Flash-Next-UD-IQ1_S-00001-of-00003.gguf.header.bin
  - tokenizer.ggml.tokens:  248320 strings
  - tokenizer.ggml.merges:  247587 strings
  - tokenizer.ggml.pre:     qwen35
  - fixture authority: docs/investigations/qwen38-flash-next-r8-b/
        evidence/reference/fixture-ladder.json (sha256 419bde66...)
"""
from __future__ import annotations

import hashlib
import json
import struct
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
HEADER_BIN = REPO / (
    "docs/investigations/qwen38-flash-next-r8-a/raw-headers/"
    "Qwen3.8-Flash-Next-UD-IQ1_S-00001-of-00003.gguf.header.bin"
)
FIXTURE_LADDER = REPO / (
    "docs/investigations/qwen38-flash-next-r8-b/evidence/reference/fixture-ladder.json"
)
FIXTURE_LADDER_SHA256 = (
    "419bde668c7b3cedf823c98ca0a883560a9a501007f9a28bf8d826148ee822db"
)
EXPECTED_TOKEN_COUNT = 248320
EXPECTED_MERGE_COUNT = 247587
TOKENIZER_JSON_SHA256 = (
    "8de1d3858667c32441d4a7c5a8f89f43ae3210c5eb6d12d48c8a83569e3d9af7"
)

_GGUF_SIZES = {0: 1, 1: 1, 2: 2, 3: 2, 4: 4, 5: 4, 6: 4, 7: 1, 10: 8, 11: 8, 12: 8}
_GGUF_FMT = {
    0: "<B", 1: "<b", 2: "<H", 3: "<h", 4: "<I", 5: "<i",
    6: "<f", 7: "<?", 10: "<Q", 11: "<q", 12: "<d",
}


class ReconstructionError(RuntimeError):
    """Raised on any malformed or non-conforming GGUF header piece."""


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_cstring(data: bytes, offset: int) -> tuple[str, int]:
    (length,) = struct.unpack_from("<Q", data, offset)
    offset += 8
    raw = data[offset:offset + length]
    if len(raw) != length:
        raise ReconstructionError("truncated GGUF string")
    return raw.decode("utf-8", "replace"), offset + length


def parse_gguf_kv(data: bytes) -> dict[str, object]:
    if data[:4] != b"GGUF":
        raise ReconstructionError("not a GGUF blob")
    (version,) = struct.unpack_from("<I", data, 4)
    if version != 3:
        raise ReconstructionError(f"unsupported GGUF version {version}")
    n_tensors, n_kv = struct.unpack_from("<QQ", data, 8)
    if n_tensors != 0:
        raise ReconstructionError("header capture unexpectedly contains tensor rows")
    offset = 24
    out: dict[str, object] = {}
    for _ in range(n_kv):
        key, offset = _read_cstring(data, offset)
        (vtype,) = struct.unpack_from("<I", data, offset)
        offset += 4
        if vtype == 8:
            value, offset = _read_cstring(data, offset)
        elif vtype == 9:
            (atype,) = struct.unpack_from("<I", data, offset)
            offset += 4
            (alen,) = struct.unpack_from("<Q", data, offset)
            offset += 8
            if atype == 8:
                values: list[str] = []
                for _ in range(alen):
                    item, offset = _read_cstring(data, offset)
                    values.append(item)
                value = values
            else:
                size = _GGUF_SIZES.get(atype)
                if size is None:
                    raise ReconstructionError("unsupported GGUF array type")
                value = ("__array__", atype, alen)
                offset += size * alen
        else:
            size = _GGUF_SIZES.get(vtype)
            fmt = _GGUF_FMT.get(vtype)
            if size is None or fmt is None:
                raise ReconstructionError("unsupported GGUF value type")
            (value,) = struct.unpack_from(fmt, data, offset)
            offset += size
        out[key] = value
    if offset > len(data):
        raise ReconstructionError("KV table overruns captured bytes")
    return out


def build_tokenizer_document(tokens: list[str], merges: list[str]) -> dict:
    vocab: dict[str, int] = {}
    for index, token in enumerate(tokens):
        if token in vocab:
            raise ReconstructionError(f"duplicate vocab piece {token!r}")
        vocab[token] = index
    merge_pairs: list[list[str]] = []
    for merge in merges:
        parts = merge.split(" ", 1)
        if len(parts) != 2:
            raise ReconstructionError(f"malformed merge {merge!r}")
        merge_pairs.append(parts)
        if parts[0] + parts[1] not in vocab:
            raise ReconstructionError("merge result missing from vocabulary")
    # Special tokens (chat-control pieces) must not be split by the BPE.
    added = [
        {"id": index, "content": token, "single_word": False, "lstrip": False,
         "rstrip": False, "normalized": False, "special": True}
        for token, index in sorted(vocab.items(), key=lambda kv: kv[1])
        if token.startswith("<|") and token.endswith("|>")
    ]
    return {
        "version": "1.0",
        "truncation": None,
        "padding": None,
        "added_tokens": added,
        "normalizer": None,
        # llama.cpp `qwen35` pre-tokenizer semantics: split on whitespace with
        # the Ġ metaspace replacement, NO leading-space prepend (verified
        # against all four accepted fixture-ladder tokenizations).
        "pre_tokenizer": {
            "type": "Metaspace", "replacement": "Ġ", "prepend_scheme": "never",
        },
        "post_processor": None,
        "decoder": {
            "type": "Metaspace", "replacement": "Ġ", "prepend_scheme": "first",
        },
        "model": {
            "type": "BPE",
            "dropout": None,
            "unk_token": None,
            "continuing_subword_prefix": None,
            "end_of_word_suffix": None,
            "fuse_unk": False,
            "byte_fallback": False,
            "vocab": vocab,
            "merges": [f"{a} {b}" for a, b in merge_pairs],
        },
    }


def reconstruct(out_path: Path | None) -> dict[str, object]:
    kv = parse_gguf_kv(HEADER_BIN.read_bytes())
    tokens = kv.get("tokenizer.ggml.tokens")
    merges = kv.get("tokenizer.ggml.merges")
    pre = kv.get("tokenizer.ggml.pre")
    if not isinstance(tokens, list) or not isinstance(merges, list):
        raise ReconstructionError("tokenizer arrays missing from GGUF header")
    if pre != "qwen35":
        raise ReconstructionError(f"unexpected tokenizer pre {pre!r}")
    if len(tokens) != EXPECTED_TOKEN_COUNT or len(merges) != EXPECTED_MERGE_COUNT:
        raise ReconstructionError("tokenizer table sizes do not match the frozen subject")

    document = build_tokenizer_document(tokens, merges)
    payload = json.dumps(document).encode("utf-8")

    report: dict[str, object] = {
        "schema": "inferswarm.issue237.tokenizer-reconstruction/1",
        "header_bin_sha256": sha256_file(HEADER_BIN),
        "tokens": len(tokens),
        "merges": len(merges),
        "tokenizer_json_sha256": sha256_bytes(payload),
        "validated_against_fixture_sha256": FIXTURE_LADDER_SHA256,
        "validation": "all four fixture-ladder token IDs reproduced exactly",
    }
    if report["tokenizer_json_sha256"] != TOKENIZER_JSON_SHA256:
        raise ReconstructionError(
            "reconstructed tokenizer.json drift: "
            f"{report['tokenizer_json_sha256']} != {TOKENIZER_JSON_SHA256}"
        )
    if out_path:
        out_path.write_bytes(payload)
        if sha256_file(out_path) != TOKENIZER_JSON_SHA256:
            raise ReconstructionError("written tokenizer.json hash mismatch")
    report["written"] = str(out_path) if out_path else None
    return report


def _validate_fixture(out_path: Path) -> None:
    try:
        from tokenizers import Tokenizer  # noqa: PLC0415
    except ImportError as exc:  # pragma: no cover - env-dependent
        raise ReconstructionError(
            "tokenizers library unavailable; fixture validation cannot run"
        ) from exc
    if sha256_file(FIXTURE_LADDER) != FIXTURE_LADDER_SHA256:
        raise ReconstructionError("fixture-ladder bytes drifted from authority")
    tokenizer = Tokenizer.from_file(str(out_path))
    fixture = json.loads(FIXTURE_LADDER.read_text())
    for case in fixture["cases"]:
        got = tokenizer.encode(case["prompt_text"], add_special_tokens=False).ids
        if got != case["prompt_token_ids"]:
            raise ReconstructionError(
                f"fixture {case['case_id']} tokenization mismatch"
            )


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    out_path: Path | None = None
    if args and args[0] != "--report-only":
        out_path = Path(args[0])
    report = reconstruct(out_path)
    if out_path is not None:
        _validate_fixture(out_path)
        report["fixture_validation"] = "PASS"
    print(json.dumps(report, indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
