"""Arm-B participant-exact materialization + realization (compute nodes).

Two phases:
  assemble  - reconstruct the participant's model repository from VERIFIED
              cache objects only: config.json from its metadata artifact,
              one materialized safetensors shard containing EXACTLY the
              planned tensors (content-addressed reassembly, every tensor
              digest re-verified against its cache object). Written under
              /srv/inferswarm/materialized/issue117/<participant>/.
  realize   - construct GemmaDenseStage (the accepted frozen producer seam,
              FreeToken 924cd22e) against that repository, proving
              participant-exact residency (fetched keys/bytes, CU binding,
              staging release, host-mirror zero). NO PREFILL/decode/generate.

Runs under strace -f -e trace=file for the runtime-read audit.
"""
from __future__ import annotations

import argparse
import json
import os
import struct
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, "/srv/inferswarm/state/arm-b/scripts")
sys.path.insert(0, str(Path(__file__).resolve().parent))

import armb_plan_core as core  # noqa: E402

MATERIALIZED_ROOT = Path("/srv/inferswarm/materialized/issue117")


def load_json(path):
    return json.loads(Path(path).read_text())


def cache_objects_index(cache_root: Path):
    """content_digest -> path for every verified cache object."""
    index = {}
    for path in sorted((cache_root / "objects").iterdir()):
        index["sha256:" + path.name.replace("sha256-", "")] = path
    return index


def assemble(participant, requirements, cache_root, out_dir: Path):
    index = cache_objects_index(cache_root)
    layout_file = Path("/srv/inferswarm/state/arm-b/source/arm-b-layout.json")
    layout = load_json(layout_file) if layout_file.exists() else None
    if layout is None:
        raise SystemExit("missing arm-b-layout.json (run source build)")

    # metadata artifact -> config.json
    meta_records = [r for r in participant["required_artifacts"]
                    if r["requirement_class"] == "required_metadata"]
    written = []
    digest_checks = 0
    used_artifact_ids = []
    logical_states = set()
    for rec in meta_records:
        data = index[rec["content_digest"]].read_bytes()
        if core.digest_of_bytes(data) != rec["content_digest"]:
            raise SystemExit(f"CACHE_OBJECT_TAMPERED {rec['artifact_id']}")
        digest_checks += 1
        name = rec["origin"]["source_object"]
        (out_dir / name).write_bytes(data)
        written.append({"object": name, "bytes": len(data),
                        "content_digest": rec["content_digest"]})
        used_artifact_ids.append(rec["artifact_id"])
        for s in rec["satisfies_logical_state_ids"]:
            logical_states.add(s)

    # tensor artifacts -> one materialized shard with EXACTLY planned keys
    tensor_recs = [r for r in participant["required_artifacts"]
                   if r["requirement_class"] != "required_metadata"]
    shard_name = "armb-participant.safetensors"
    header = {}
    offset = 0
    body_parts = []
    # dedupe by tensor key (declared shared state produces two records for
    # the SAME embedding key; distinct keys with identical content — e.g.
    # equal norm weights — remain distinct tensors)
    seen_key = {}
    per_tensor = []
    for rec in sorted(tensor_recs, key=lambda r: r["artifact_id"]):
        data = index[rec["content_digest"]].read_bytes()
        if core.digest_of_bytes(data) != rec["content_digest"]:
            raise SystemExit(f"CACHE_OBJECT_TAMPERED {rec['artifact_id']}")
        digest_checks += 1
        key = tensor_key_of(rec, layout)
        if key in seen_key:
            if seen_key[key] != rec["content_digest"]:
                raise SystemExit(
                    f"tensor key {key} maps to two different contents")
            used_artifact_ids.append(rec["artifact_id"])
            for s in rec["satisfies_logical_state_ids"]:
                logical_states.add(s)
            continue
        seen_key[key] = rec["content_digest"]
        t = layout[key]
        header[key] = {"dtype": t["dtype"], "shape": t["shape"],
                       "data_offsets": [offset, offset + len(data)]}
        body_parts.append(data)
        offset += len(data)
        used_artifact_ids.append(rec["artifact_id"])
        for s in rec["satisfies_logical_state_ids"]:
            logical_states.add(s)
        per_tensor.append({"key": key, "bytes": len(data),
                           "content_digest": rec["content_digest"]})

    header_bytes = json.dumps(header, separators=(",", ":")).encode()
    pad = (8 - len(header_bytes) % 8) % 8
    header_bytes += b" " * pad
    shard_path = out_dir / shard_name
    with open(shard_path, "wb") as f:
        f.write(struct.pack("<Q", len(header_bytes)))
        f.write(header_bytes)
        for part in body_parts:
            f.write(part)
    written.append({"object": shard_name, "bytes": shard_path.stat().st_size,
                    "tensors": len(per_tensor)})

    # coverage proof: every planned logical state materialized exactly
    declared = (set(participant["required_logical_state"]["assigned"])
                | set(participant["required_logical_state"]["declared_shared"])
                | set(participant["required_logical_state"]["required_metadata"]))
    missing = sorted(declared - logical_states)
    if missing:
        raise SystemExit(f"REQUIRED_STATE_COVERAGE_INCOMPLETE {missing}")
    if len(seen_key) != len(header):
        raise SystemExit("internal: key/content mismatch")

    doc = {
        "schema": "inferswarm.issue117.arm-b.materialization-assemble/1",
        "participant_id": participant["participant_id"],
        "node_id": participant["node_id"],
        "execution_unit_id": participant["execution_unit_id"],
        "out_dir": str(out_dir),
        "shard": shard_name,
        "tensor_count": len(per_tensor),
        "tensor_bytes": sum(t["bytes"] for t in per_tensor),
        "shard_bytes": shard_path.stat().st_size,
        "objects_written": written,
        "used_artifact_ids": sorted(used_artifact_ids),
        "materialized_logical_states": sorted(logical_states),
        "digest_checks_performed": digest_checks,
        "participant_requirements_digest":
            participant["participant_requirements_digest"],
    }
    return doc


def tensor_key_of(rec, layout):
    """Map an artifact record back to its checkpoint tensor key via origin."""
    # records carry origin.byte_start/byte_end within model.safetensors
    start, end = rec["origin"]["byte_start"], rec["origin"]["byte_end"]
    matches = [k for k, t in layout.items()
               if t["object"] == rec["origin"]["source_object"]
               and t["byte_start"] == start and t["byte_end"] == end]
    if len(matches) != 1:
        raise SystemExit(f"artifact {rec['artifact_id'][:20]} maps to "
                         f"{len(matches)} tensors")
    return matches[0]


def realize(participant, out_dir: Path, block_plan_path: Path, gpu_uuid: str,
            runtime_capacity_tokens: int = 256):
    """Spawn the realization subprocess under strace and collect its report."""
    report_path = out_dir / "realize-report.json"
    strace_path = out_dir / "realize-strace.log"
    script = Path("/srv/inferswarm/state/arm-b/scripts/armb_realize_child.py")
    child_python = "/home/zutfen/FreeToken/.venv/bin/python"
    cmd = [
        "strace", "-f", "-qq", "-e", "trace=file",
        "-o", str(strace_path),
        child_python, str(script),
        "--role", ROLE_OF[participant["participant_id"]],
        "--model-path", str(out_dir),
        "--block-plan", str(block_plan_path),
        "--participant", participant["participant_id"],
        "--gpu-uuid", gpu_uuid,
        "--runtime-capacity-tokens", str(runtime_capacity_tokens),
        "--report", str(report_path),
    ]
    started = time.time()
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    elapsed = time.time() - started
    if proc.returncode != 0:
        print(proc.stdout[-3000:])
        print(proc.stderr[-3000:])
        raise SystemExit(f"realization subprocess failed rc={proc.returncode}")
    report = load_json(report_path)
    report["strace_log"] = str(strace_path)
    report["realize_elapsed_seconds"] = round(elapsed, 3)
    return report


ROLE_OF = {
    "dense.6171f32b4413.stage-1": "first",
    "dense.6171f32b4413.stage-2": "middle",
    "dense.6171f32b4413.stage-3": "last",
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", choices=("assemble", "realize", "both"),
                    default="both")
    ap.add_argument("--requirements",
                    default="/srv/inferswarm/state/arm-b/source/arm-b-requirements.json")
    ap.add_argument("--block-plan",
                    default="/srv/inferswarm/state/arm-b/source/arm-b-block-plan.json")
    ap.add_argument("--cache-root", default="/srv/inferswarm/cache/issue117")
    ap.add_argument("--participant", required=True)
    ap.add_argument("--gpu-uuid", required=True)
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args()

    requirements = load_json(args.requirements)
    core.validate_self_identity(requirements, identity_field="requirements_digest")
    participant = next(p for p in requirements["participants"]
                       if p["participant_id"] == args.participant)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    doc = None
    if args.phase in ("assemble", "both"):
        doc = assemble(participant, requirements, Path(args.cache_root), out_dir)
        (out_dir / "assemble-report.json").write_bytes(
            core.canonical_json_bytes(doc))
        print(json.dumps({k: doc[k] for k in
                         ("participant_id", "tensor_count", "tensor_bytes",
                          "shard_bytes", "digest_checks_performed")}))
    if args.phase in ("realize", "both"):
        report = realize(participant, out_dir, Path(args.block_plan),
                         args.gpu_uuid)
        (out_dir / "realize-report-wrapped.json").write_bytes(
            core.canonical_json_bytes(report))
        print(json.dumps({k: report.get(k) for k in
                         ("participant_id", "fetched_keys", "fetched_bytes",
                          "resident_device_bytes", "gpu_uuid")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
