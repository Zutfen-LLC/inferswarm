#!/usr/bin/env python3
"""Issue #216 raw-receipt manifest and deterministic assembly boundary.

Only raw retained receipts below ``evidence/`` are authoritative.  The assembly
is deliberately strict: a handwritten campaign record, result flag, or summary
cannot enter the terminal path.
"""
from __future__ import annotations

import hashlib
import json
import os
import stat
from pathlib import Path
from typing import Any

SCHEMA = "inferswarm.v2d.input-manifest/2"
ASSEMBLY_SCHEMA = "inferswarm.v2d.campaign-assembly/2"
CAMPAIGN_ID = "issue216-v2d-v340l-concurrent-dual-die-v1"
FIXTURE_ID = "issue216-v2d-fixture-not-physical-v1"
EXCLUDED = {"INPUT-MANIFEST.json", "CAMPAIGN-RECORD.json", "TERMINAL.json", "FINAL-CLOSURE.json"}
TYPED_SCHEMAS = {
    "inferswarm.v2d.fresh-physical-mapping/1", "inferswarm.v2d.preflight-receipt/1",
    "inferswarm.v2d.execution-attempt/1", "inferswarm.v2d.participant-receipt/1",
    "inferswarm.v2d.concurrent-attempt/1", "inferswarm.v2d.transport-sample/1",
    "inferswarm.v2d.soak-telemetry/1", "inferswarm.v2d.soak-checkpoint/1",
    "inferswarm.v2d.soak-run/1", "inferswarm.v2d.fault-isolation/1",
    "inferswarm.v2d.reset-disposition/1",
}


class AssemblyError(RuntimeError):
    pass


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _safe(root: Path, rel: str) -> Path:
    if not isinstance(rel, str) or not rel or rel.startswith("/"):
        raise AssemblyError("absolute/empty authority path")
    pure = Path(rel)
    if any(part in {"", ".", ".."} for part in pure.parts):
        raise AssemblyError("path traversal/alias component")
    root = root.resolve()
    path = root / pure
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise AssemblyError("authority path escapes root") from exc
    parent = path.parent
    while parent != root:
        try:
            if parent.lstat().st_mode & stat.S_IFLNK:
                raise AssemblyError("symlinked authority parent")
        except FileNotFoundError as exc:
            raise AssemblyError("missing authority parent") from exc
        parent = parent.parent
    try:
        st = path.lstat()
    except FileNotFoundError as exc:
        raise AssemblyError("missing authority input") from exc
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode) or st.st_nlink != 1:
        raise AssemblyError("non-independent regular authority input")
    return path


def primary_paths(root: Path) -> list[Path]:
    evidence = root / "evidence"
    if not evidence.is_dir() or evidence.is_symlink():
        raise AssemblyError("evidence root absent or aliased")
    rows: list[Path] = []
    for path in sorted(evidence.rglob("*")):
        if path.is_dir():
            if path.is_symlink():
                raise AssemblyError("symlink directory")
            continue
        rel = path.relative_to(root).as_posix()
        if path.name in EXCLUDED:
            raise AssemblyError("derived artifact in primary namespace")
        _safe(root, rel)
        rows.append(path)
    if not rows:
        raise AssemblyError("no primary raw receipts")
    return rows


def build_input_manifest(root: Path) -> dict[str, Any]:
    inputs = []
    for path in primary_paths(root):
        data = path.read_bytes()
        inputs.append({"path": path.relative_to(root).as_posix(), "sha256": sha(data), "bytes": len(data)})
    doc = {"schema": SCHEMA, "inputs": inputs}
    doc["manifest_digest"] = sha(canonical(doc))
    return doc


def verify_input_manifest(manifest: dict[str, Any], root: Path) -> bool:
    try:
        body = dict(manifest)
        stated = body.pop("manifest_digest")
        return body.get("schema") == SCHEMA and stated == sha(canonical(body)) and build_input_manifest(root) == manifest
    except (AssemblyError, KeyError, TypeError, ValueError, OSError):
        return False


def _load(root: Path, manifest: dict[str, Any]) -> list[dict[str, Any]]:
    receipts: list[dict[str, Any]] = []
    seen_paths: set[str] = set()
    for row in manifest.get("inputs", []):
        rel = row.get("path")
        if not isinstance(rel, str) or rel in seen_paths:
            raise AssemblyError("duplicate/malformed manifest path")
        seen_paths.add(rel)
        path = _safe(root, rel)
        data = path.read_bytes()
        if len(data) != row.get("bytes") or sha(data) != row.get("sha256"):
            raise AssemblyError("manifest byte mismatch")
        if not rel.endswith(".json"):
            continue
        try:
            receipt = json.loads(data)
        except json.JSONDecodeError as exc:
            raise AssemblyError("invalid retained receipt JSON") from exc
        if not isinstance(receipt, dict) or receipt.get("schema") not in TYPED_SCHEMAS:
            raise AssemblyError("unexpected/unknown JSON authority artifact")
        receipt = dict(receipt)
        receipt["_path"] = rel
        receipt["_sha256"] = row["sha256"]
        receipts.append(receipt)
    return receipts


def _require(value: dict[str, Any], fields: tuple[str, ...], context: str) -> None:
    missing = [field for field in fields if value.get(field) in (None, "", [], {})]
    if missing:
        raise AssemblyError(f"{context}: missing {','.join(missing)}")


def _common(receipt: dict[str, Any], authority_digest: str, fixture: bool) -> None:
    _require(receipt, ("schema", "campaign_id", "receipt_id", "producer_path", "producer_sha256", "repo_head", "host", "boot_id", "attempt_id", "authority_digest", "fresh_mapping_digest"), receipt["_path"])
    wanted = FIXTURE_ID if fixture else CAMPAIGN_ID
    if receipt["campaign_id"] != wanted or receipt["authority_digest"] != authority_digest:
        raise AssemblyError("campaign/authority mismatch")
    if bool(receipt.get("fixture", False)) != fixture:
        raise AssemblyError("fixture/physical namespace confusion")
    if len(str(receipt["producer_sha256"])) != 64 or len(str(receipt["fresh_mapping_digest"])) != 64:
        raise AssemblyError("invalid producer/fresh-map digest")


def _index(receipts: list[dict[str, Any]], schema: str) -> list[dict[str, Any]]:
    return [r for r in receipts if r["schema"] == schema]


def _unique(receipts: list[dict[str, Any]], key: tuple[str, ...], label: str) -> None:
    values = []
    for receipt in receipts:
        _require(receipt, key, label)
        values.append(tuple(str(receipt[x]) for x in key))
    if len(set(values)) != len(values):
        raise AssemblyError(f"duplicate logical {label}")


def _raw_bound(receipt: dict[str, Any], root: Path) -> None:
    raw = receipt.get("raw")
    if not isinstance(raw, dict) or not raw:
        raise AssemblyError("receipt lacks raw-byte bindings")
    for rel, digest in raw.items():
        if not isinstance(rel, str) or not isinstance(digest, str) or len(digest) != 64:
            raise AssemblyError("malformed raw binding")
        if not rel.startswith("evidence/") or sha(_safe(root, rel).read_bytes()) != digest:
            raise AssemblyError("raw-byte binding mismatch")


def _validate(receipts: list[dict[str, Any]], authority_digest: str, fixture: bool, root: Path) -> None:
    for receipt in receipts:
        _common(receipt, authority_digest, fixture)
        _raw_bound(receipt, root)
        rendered = canonical(receipt).decode("utf-8")
        if "16 GiB" in rendered or "aggregate_memory_bytes" in rendered:
            raise AssemblyError("forbidden coherent aggregate memory claim")
        if "Qwen" in rendered or "DeepSeek" in rendered or "model_program_result" in rendered:
            raise AssemblyError("forbidden model-program result")
    _unique(receipts, ("receipt_id",), "receipt identity")
    fresh = _index(receipts, "inferswarm.v2d.fresh-physical-mapping/1")
    if len(fresh) != 1:
        raise AssemblyError("exactly one fresh physical map required")
    participants = fresh[0].get("participants")
    if not isinstance(participants, dict) or set(participants) != {"a", "b"}:
        raise AssemblyError("fresh map must bind exactly A and B")
    values = []
    for die in ("a", "b"):
        row = participants[die]
        _require(row, ("selector", "bdf", "physical_id", "compute_unit_id", "memory_resource_id", "hbm_bytes"), "fresh participant")
        values.append(tuple(row[x] for x in ("selector", "bdf", "physical_id", "compute_unit_id", "memory_resource_id")))
    if any(values[0][i] == values[1][i] for i in range(5)):
        raise AssemblyError("same-die/fresh-map alias")
    if fresh[0].get("mapping_digest") != sha(canonical({"participants": participants})):
        raise AssemblyError("fresh map digest does not bind current observations")
    fresh_digest = fresh[0]["mapping_digest"]
    if any(r["fresh_mapping_digest"] != fresh_digest for r in receipts):
        raise AssemblyError("receipt not bound to exact fresh map")
    preflight = _index(receipts, "inferswarm.v2d.preflight-receipt/1")
    if len(preflight) != 1:
        raise AssemblyError("exactly one preflight required")
    if preflight[0].get("accepted_predecessors") != {"v2b": "accepted-v2b", "v2c": "accepted-v2c", "x1": "accepted-35"}:
        raise AssemblyError("wrong/superseded/mutated predecessor authority")
    topology = preflight[0].get("topology", {})
    _require(topology, ("root_port", "switch_upstream", "endpoint_a", "endpoint_b", "negotiated"), "topology")
    if topology["negotiated"] != "Gen3 x1" or topology["endpoint_a"] == topology["endpoint_b"]:
        raise AssemblyError("missing/wrong Gen3 x1 topology")
    if preflight[0].get("preexisting_fault") is True:
        raise AssemblyError("preflight platform fault")
    execution = _index(receipts, "inferswarm.v2d.execution-attempt/1")
    _unique(execution, ("attempt_id", "die"), "execution attempt")
    for r in execution:
        _require(r, ("die", "runtime", "model", "argv", "clean_exit", "correctness", "offload", "fallback", "accounting"), "execution")
    pairs = _index(receipts, "inferswarm.v2d.concurrent-attempt/1")
    _unique(pairs, ("attempt_id",), "concurrent attempt")
    for r in pairs:
        _require(r, ("participants", "workload_intervals_ns"), "concurrent pair")
        if set(r["participants"]) != {"a", "b"} or set(r["workload_intervals_ns"]) != {"a", "b"}:
            raise AssemblyError("invalid pair participant set")
        for die in ("a", "b"):
            part = r["participants"][die]
            _require(part, ("participant_receipt", "die", "physical_id", "correctness", "offload", "fallback", "accounting", "clean_exit"), "pair participant")
            if part["die"] != die or part["physical_id"] != participants[die]["physical_id"]:
                raise AssemblyError("wrong-die/cross-substituted participant")
            interval = r["workload_intervals_ns"][die]
            if not isinstance(interval, list) or len(interval) != 2 or interval[0] >= interval[1]:
                raise AssemblyError("invalid workload interval")
        a, b = r["workload_intervals_ns"]["a"], r["workload_intervals_ns"]["b"]
        if max(a[0], b[0]) >= min(a[1], b[1]):
            raise AssemblyError("no correctness-bearing workload overlap")
    transport = _index(receipts, "inferswarm.v2d.transport-sample/1")
    _unique(transport, ("mode", "direction", "size_bytes", "repetition", "participant"), "transport sample")
    for r in transport:
        _require(r, ("mode", "direction", "size_bytes", "repetition", "participant", "bytes_transferred", "measured_value", "interval_ns"), "transport")
        if r["mode"] not in {"single-a", "single-b", "dual"} or r["direction"] not in {"h2d", "d2h"}:
            raise AssemblyError("transport mode/direction")
        if r["size_bytes"] not in {4096, 4 * 1024**2, 64 * 1024**2, 512 * 1024**2} or r["repetition"] not in range(1, 6):
            raise AssemblyError("transport matrix/repetition")
        if r["mode"] == "dual" and r.get("dual_workload_overlap") is not True:
            raise AssemblyError("dual transport without overlap")


def assemble(root: Path, manifest: dict[str, Any], authority_digest: str, *, fixture: bool = False) -> dict[str, Any]:
    if not verify_input_manifest(manifest, root):
        raise AssemblyError("input manifest mismatch or unsafe authority path")
    receipts = _load(root, manifest)
    if not receipts:
        raise AssemblyError("no typed raw receipts")
    _validate(receipts, authority_digest, fixture, root)
    return {
        "schema": ASSEMBLY_SCHEMA, "campaign_id": FIXTURE_ID if fixture else CAMPAIGN_ID,
        "fixture": fixture, "input_manifest_digest": manifest["manifest_digest"],
        "authority_digest": authority_digest, "receipts": receipts,
        "source_receipt_identities": [{"path": r["_path"], "sha256": r["_sha256"]} for r in receipts],
    }


def assert_preexecution_namespace_clean(repo: Path) -> None:
    """Reject accidental retained V2-D physical evidence before producer freeze."""
    area = repo / "docs/investigations/vulkan-v2-d-v340l-concurrent"
    forbidden = [p for p in area.rglob("*") if p.is_file() and (p.parts[-2:-1] == ("evidence",) or "evidence" in p.parts or p.name in {"TERMINAL.json", "INPUT-MANIFEST.json", "CAMPAIGN-RECORD.json"})]
    if forbidden:
        raise AssemblyError("pre-execution namespace contains physical/derived receipts: " + ", ".join(str(p.relative_to(area)) for p in forbidden))


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True); ap.add_argument("--authority-digest")
    ap.add_argument("--write-input-manifest", action="store_true"); ap.add_argument("--assemble", action="store_true")
    ap.add_argument("--fixture", action="store_true"); ap.add_argument("--assert-preexecution-clean", action="store_true")
    args = ap.parse_args(); root = Path(args.repo)
    if args.assert_preexecution_clean:
        assert_preexecution_namespace_clean(root); print("PREEXECUTION_NAMESPACE_CLEAN"); return 0
    manifest = build_input_manifest(root)
    if args.write_input_manifest:
        (root / "evidence" / "INPUT-MANIFEST.json").write_bytes(json.dumps(manifest, indent=1, sort_keys=True).encode()+b"\n")
    if args.assemble:
        if not args.authority_digest: raise SystemExit("--authority-digest required")
        print(json.dumps(assemble(root, manifest, args.authority_digest, fixture=args.fixture), indent=1, sort_keys=True))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
