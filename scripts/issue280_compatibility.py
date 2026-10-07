#!/usr/bin/env python3
"""Bound R1 CPU compatibility replay. No execution authority or physical access.

The legacy witness authenticates only original request/batch/graph semantics;
other rows still traverse the exact same collector laws, allowing independent
D2/D3 attacks without a global hash refusal hiding the actual defect.
"""
from __future__ import annotations
import argparse
import gzip
import hashlib
import importlib.util
import json
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "docs/investigations/vulkan-same-request-280/compatibility"
PIN = "b29c606e28a01b1bc8c1351026a0fa6e616bf6c4"
MODEL_SHA256 = "9c9f56a391a3abbd5b89d0245bf6106081bcc3173119d4229235dd9d23253f94"
RAW_SHA256 = "b1fa13966a715d2009efdde4fa602a5a6f0b70d93c3884ceef0d14426bfcc796"
SERVER_SHA256 = "2dc0d51bb11113536b6993123510bf2ddfc088bd58db97ad91a3806d66cb82ff"
TERMINAL_SHA256 = "c7bccbc3e613ee537aef012d02076b5d861d27d1c02974956a981c0497deaa66"
PROJECTION_SHA256 = "67f3f44dcaffb44a74c0efcdc085d31f323c20b024075ddef317ff96cf847a6e"
ACCEPTED_OBSERVER_SHA256 = "17021e0fb8e9fe10db1b363142bf8e73e56a616d5e61833475cf90129b036d5a"
DIRECT_FIELDS = {"n_seqs_unq", "seq_ids_unq", "n_seq_tokens", "b_equal_seqs"}
HOST_BUFFERS = frozenset({"CPU", "CPU_Mapped", "Vulkan_Host"})


def load_script(name):
    spec = importlib.util.spec_from_file_location("i280_bound_" + name, ROOT / "scripts" / (name + ".py"))
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sha(data):
    return hashlib.sha256(data).hexdigest()


def sequence_projection(rows):
    projection = [{k: v for k, v in row.items() if not (row["event"] == "graph_begin" and k in DIRECT_FIELDS)}
                  for row in rows if row["event"] in {"request_accept", "batch_begin", "graph_begin"}]
    return sha(json.dumps(projection, sort_keys=True, separators=(",", ":")).encode())


def _read_gzip(path):
    try:
        return gzip.decompress(path.read_bytes())
    except zlib.error as exc:
        raise ValueError("compatibility gzip custody: " + path.name + ": " + str(exc)) from exc


def authenticate(bundle=BUNDLE, relationship=False):
    """Re-read actual bytes on every call; never cache custody on mutable files."""
    bundle = Path(bundle)
    raw = _read_gzip(bundle / "observer-R1-cold.i280.raw.gz")
    server = _read_gzip(bundle / "server-R1.log.gz")
    terminal = (bundle / "TERMINAL.json").read_bytes()
    for name, data, expected in (("raw", raw, RAW_SHA256), ("server", server, SERVER_SHA256),
                                 ("terminal", terminal, TERMINAL_SHA256),
                                 ("accepted observer", (bundle / "accepted-observer.py").read_bytes(), ACCEPTED_OBSERVER_SHA256)):
        if sha(data) != expected:
            raise ValueError("compatibility custody: " + name + " digest drift")
    provenance = json.loads(terminal)
    if (provenance["build"]["source_pin"] != PIN or provenance["model"]["sha256"] != MODEL_SHA256
            or provenance["model"]["size"] != 1929903264
            or provenance["build"]["full_transformed_git_tree"] != "b070e4ace586d44d9abc30665176e54bb8564749"
            or provenance["build"]["overlay_tree_sha256"] != "543ed89d8a0043d872bf9b4d6933a85d8632bba71942c1ca77216f8ec565a565"):
        raise ValueError("compatibility producer/model identity drift")
    if b"initializing, n_slots = 1, n_ctx_slot = 4096, kv_unified = 'false'" not in server:
        raise ValueError("compatibility missing source-derived one-slot initialization witness")
    if b"Qwen2.5-3B-Instruct-Q4_K_M.gguf" not in server:
        raise ValueError("compatibility missing pinned Qwen2 model witness")
    # Authenticate the archived source semantics used for the one-slot inference
    # and tied output inference, independently of runtime logs.
    identities = json.loads((BUNDLE / "source-semantics/sha256.json").read_text())
    for path, expected in SEMANTIC_HASHES.items():
        if identities.get(path) != expected or sha((BUNDLE / "source-semantics" / path).read_bytes()) != expected:
            raise ValueError("compatibility pinned semantics drift: " + path)
    if relationship:
        observer = load_script("issue280_observer")
        rows = observer.parse(raw.decode())
        server_rows = observer.parse(server.decode())
        by_time = {r["ts_ns"]: r for r in server_rows}
        for row in rows:
            normalized = dict(row)
            if normalized["event"] == "recording":
                normalized.pop("requests_planned", None)
            if by_time.get(row["ts_ns"]) != normalized:
                raise ValueError("compatibility full raw/server semantic mismatch")
        if sequence_projection(rows) != PROJECTION_SHA256:
            raise ValueError("compatibility sequence projection drift")
    return raw.decode()


SEMANTIC_HASHES = {
    "src/llama-batch.h": "7000dfd8750e06c544642dd7b84c882191702ad46ced1a4d6ad109462d1a1013",
    "src/llama-batch.cpp": "484607d92fb08d510727e0c4b01139e27a40137ef03e74e1dbea4aac3965e328",
    "src/llama-context.cpp": "6429ebec7c926945987e6fe037317af0f99265490bc14b0606d9487a62a76453",
    "common/common.cpp": "e6eccdf376a80a3f534fc71ad7775fcac52eb6089367f1592ce1d293b147db66",
    "tools/server/server-context.cpp": "2f5d65ce6ef0504b5c8cf55a74c68d3959c49784ba380ef836566b7a7d5fa12b",
    "src/models/qwen2.cpp": "0da43ff61f449be3a3da8ca2e7cc0eee119b4b8e07c8accce0041998241824e8",
    "src/llama-model-loader.cpp": "5ef07476310d4678df18a61a6ec0a1ebcbb58c7534ac3c624b9fe0f315a4ab01",
    "ggml/src/ggml-backend.cpp": "a39c4fe81b043c7e8616ebe57afb75d727c692fe3b26c3e9bc2ddde3c6991041",
    "ggml/src/ggml-vulkan/ggml-vulkan.cpp": "c84f67465dfa0a24e034663f510d8b92310e3be7a7fbca231760be234b7c9f9d",
    "ggml/include/ggml-vulkan.h": "7eae5dad2cc7bb4d3eca828539f441816d5fd59fdc7b224d49aa229fc7b7248c",
}


class _LegacyCompatibilityAuthority:
    """Single-use compatibility-only legacy sequence authority (PR #286 R2).

    Instantiable ONLY inside this module, with the exact retained
    historical R1 bytes authenticated byte-for-byte (RAW_SHA256 over the
    decompressed custody archive). The authority is consumed exactly once,
    by the collector replaying THOSE bytes under the compatibility gate;
    it never applies to any other stream. Production admission never
    constructs it: a different stream that merely shares the historical
    request/batch/graph projection cannot borrow it.
    """

    __slots__ = ("_used",)

    def __init__(self):
        # Compatibility-gate arming only (check_compatibility). A boolean or
        # string parameter elsewhere must never enable legacy inference.
        if not _legacy_authority_arming:
            raise TypeError(
                "legacy sequence authority is compatibility-gate only; "
                "production admission requires successor direct sequence metadata")
        self._used = False

    def sequence_known(self, raw):
        if self._used or sha(raw.encode()) != RAW_SHA256:
            return False
        self._used = True
        return True


_legacy_authority_arming = False


def arm_legacy_authority(raw):
    """Compatibility-gate-only constructor (never called by the runner).

    Binds the narrow legacy inference to the exact retained historical
    capture: the decompressed bytes must equal the authenticated raw
    custody stream byte-for-byte (RAW_SHA256). Any other stream — even
    with an identical request/batch/graph projection — gets no legacy
    sequence inference.
    """
    global _legacy_authority_arming
    if sha(raw.encode()) != RAW_SHA256:
        raise ValueError(
            "legacy compatibility authority requires the exact retained "
            "historical R1 capture bytes")
    _legacy_authority_arming = True
    try:
        return _LegacyCompatibilityAuthority()
    finally:
        _legacy_authority_arming = False


def legacy_sequence_witness():
    """Historical R1 custody diagnostic (arity-0, projection-blind).

    Reports whether the retained compatibility bundle authenticates. It
    takes NO rows argument on purpose: the historical legacy inference is
    a property of the exact retained bytes under the compatibility gate,
    never of a caller-supplied stream. Not consulted by production
    admission.
    """
    try:
        authenticate()
        return True
    except (OSError, ValueError, KeyError, EOFError):
        return False



def legacy_sequence_witness_rows(rows):
    """Test-only projection probe: does ``rows`` carry the historical shape?

    Exposed for adversarial mutation testing of the retained capture's
    derived stream only; never consulted by production admission.
    """
    return sequence_projection(rows) == PROJECTION_SHA256



def check_compatibility(bundle=BUNDLE):
    result = {"schema": "issue280-compatibility-gate/1", "ok": False, "problems": [],
              "physical_execution": "NONE", "authorization": "NONE"}
    try:
        raw = authenticate(bundle, relationship=True)
        source = load_script("issue280_source_compat")
        result["source_probe"] = source.cpu_probe()
        if not result["source_probe"]["ok"]:
            raise ValueError("compatibility successor CPU source probe failure")
        observer = load_script("issue280_observer")
        # Arm through the observer's own compatibility module instance: the
        # collector type-checks the authority against that exact instance's
        # class, so an authority object forged in any other module (or a
        # duck-typed fake) is never accepted.
        result["replay"] = observer.validate_admission(
            raw, observer.physical_280_contracts()["A"],
            legacy_authority=observer._compat.arm_legacy_authority(raw))
        if not result["replay"]["ok"]:
            raise ValueError("compatibility collector failure: " + "; ".join(result["replay"]["problems"]))
        result["ok"] = True
    except (OSError, ValueError, KeyError, TypeError, EOFError, ImportError, SyntaxError, AssertionError) as exc:
        result["problems"].append(str(exc))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, default=BUNDLE)
    args = parser.parse_args()
    result = check_compatibility(args.bundle)
    print(json.dumps(result, sort_keys=True, indent=2))
    return 0 if result["ok"] else 1

if __name__ == "__main__":
    raise SystemExit(main())
