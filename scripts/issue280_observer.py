#!/usr/bin/env python3
"""Issue #280 bounded, CPU-only raw-log collector. Physical runner is HELD.

One sequential server request; no speculative decoding, prompt-cache reuse,
interleaved requests/graphs, parallel copies, tensor reads or inference launch.
The parser makes NO physical-performance or acceptance claim, even for a valid
raw stream. Expected boundary bytes are an explicit graph/token contract, NOT
PCIe wire traffic. Only outer boundary intervals are accumulated; nested host
legs are reconciled as bytes and never counted again as time.
"""
from __future__ import annotations
import argparse
import json
import re
from pathlib import Path
from typing import NoReturn

PIN = "b29c606e28a01b1bc8c1351026a0fa6e616bf6c4"
SCHEMA = "issue280-raw/1"
EVENTS = {
    "recording", "batch_begin", "batch_end", "graph_begin", "graph_end",
    "vk_graph_begin", "vk_graph_end", "ctx_create", "node", "weight",
    "dispatch", "submit", "complete", "boundary_begin", "boundary_end",
    "host_leg", "sample", "response", "gap", "copy_path", "event_record", "event_complete", "fence_marker", "copy_manifest",
}
BDF = re.compile(r"[0-9a-f]{4}:[0-9a-f]{2}:[0-1][0-9a-f]\.[0-7]\Z")


def fixture_contract():
    """Synthetic contract; never a frozen physical/model acceptance criterion."""
    return {"kind": "CPU_FIXTURE", "dies": ["0000:01:00.0", "0000:02:00.0"],
            "layers": {"0000:01:00.0": [0], "0000:02:00.0": [1]},
            "boundaries": [{"tensor": "ffn_out-0", "src": "0000:01:00.0",
                            "dst": "0000:02:00.0", "bytes_per_token": 16}]}


def parse(raw):
    """Consume actual emitter/log bytes; noise is allowed, broken rows are not."""
    rows = []
    for lineno, line in enumerate(raw.splitlines(), 1):
        if "I280 " not in line:
            continue
        text = line.split("I280 ", 1)[1]
        def unique(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError(f"line {lineno}: duplicate field {key}")
                result[key] = value
            return result
        try:
            row = json.loads(text, object_pairs_hook=unique)
        except (ValueError, TypeError) as exc:
            raise ValueError(f"line {lineno}: malformed raw record: {exc}") from exc
        if not isinstance(row, dict) or row.get("schema") != SCHEMA or row.get("event") not in EVENTS:
            raise ValueError(f"line {lineno}: unknown raw schema/event")
        if type(row.get("ts_ns")) is not int or row["ts_ns"] < 0:
            raise ValueError(f"line {lineno}: invalid timestamp")
        if rows and row["ts_ns"] < rows[-1]["ts_ns"]:
            raise ValueError(f"line {lineno}: reordered timestamps")
        rows.append(row)
    if not rows:
        raise ValueError("no Issue #280 raw records")
    return rows


def collect(raw, contract):
    """Replay bounded records through correlation + reconciliation, fail closed."""
    result = {"schema": "issue280-cpu-replay/1", "ok": False, "problems": [],
              "claim": "CPU_RECORDING_REPLAY_ONLY", "physical_runner": "HELD_UNAVAILABLE",
              "source_pin": PIN, "graphs": [], "sampled_tokens": 0, "non_eos_tokens": 0,
              "logical_boundary_bytes": 0, "host_leg_bytes": 0,
              "boundary_elapsed_ns": 0, "pcie_wire_bytes": None}
    problems = result["problems"]
    def fail(message) -> NoReturn:
        raise ValueError(message)
    samples = []
    pending = {}
    commands = {}
    boundary = None
    def integer(row, field, minimum=0):
        v = row.get(field)
        if type(v) is not int or v < minimum:
            fail(f"{row['event']}: invalid {field}")
        return v
    def text(row, field):
        v = row.get(field)
        if not isinstance(v, str) or not v:
            fail(f"{row['event']}: missing {field}")
        return v
    try:
        if contract.get("kind") != "CPU_FIXTURE":
            fail("physical replay/runner unavailable; only CPU_FIXTURE contract admitted")
        dies = contract["dies"]
        if len(dies) != 2 or len(set(dies)) != 2 or any(not BDF.fullmatch(d) for d in dies):
            fail("contract requires two distinct BDFs")
        if set(contract["layers"]) != set(dies) or any(not layers for layers in contract["layers"].values()):
            fail("contract requires named layer placement on both dies")
        expected = contract["boundaries"]
        if not expected or any(type(b["bytes_per_token"]) is not int or b["bytes_per_token"] <= 0
                               or b["src"] not in dies or b["dst"] not in dies or b["src"] == b["dst"]
                               or not b["tensor"] for b in expected):
            fail("invalid expected logical boundary contract")
        rows = parse(raw)
        if rows[0]["event"] != "recording" or rows[0].get("kind") not in {"CPU_FIXTURE", "SOURCE_OBSERVER"} or rows[0].get("source_pin") != PIN:
            fail("missing explicit recording/source identity")
        if rows[0]["kind"] == "SOURCE_OBSERVER":
            result["claim"] = "SOURCE_LOG_REPLAY_ONLY_NOT_PHYSICAL_PROOF"
        request = None
        batch = None
        graph = None
        vk = {}
        backend_bdfs = {}
        owners = {}
        commands = {}
        pending = {}
        timeline = {}
        markers = set()
        boundary = None
        samples = []
        response = None
        seen_prefill = False
        for index, row in enumerate(rows[1:], 1):
            ev = row["event"]
            if response is not None:
                fail("records after terminal response")
            if ev == "gap":
                fail("producer observation gap: " + text(row, "reason"))
            if ev == "recording":
                fail("duplicate recording identity")
            if ev == "batch_begin":
                if batch is not None or graph is not None or boundary is not None:
                    fail("interleaved request/batch")
                r = integer(row, "request")
                if request is None:
                    request = r
                if request != r:
                    fail("request mismatch")
                phase = text(row, "phase")
                if phase not in {"prefill", "decode"} or integer(row, "speculative"):
                    fail("unsupported phase/speculative request")
                ntok = integer(row, "tokens", 1)
                if phase == "decode" and (ntok != 1 or not samples):
                    fail("decode must consume exactly one previous sampled token")
                if phase == "prefill" and samples:
                    fail("prefill after sampling")
                batch = {"tokens": ntok, "phase": phase, "seq": integer(row, "seq"),
                         "graph_tokens": 0, "graphs": []}
            elif ev == "graph_begin":
                if batch is None or graph is not None or boundary is not None:
                    fail("unbound/interleaved graph")
                if integer(row, "sequences", 1) != 1 or integer(row, "seq") != batch["seq"]:
                    fail("graph sequence/request mismatch")
                graph = {"index": len(result["graphs"]), "id": text(row, "graph"),
                         "phase": batch["phase"], "tokens": integer(row, "tokens", 1),
                         "completed_compute": {d: [] for d in dies}, "boundaries": [], "manifest": {}}
                result["graphs"].append(graph)
                batch["graph_tokens"] += graph["tokens"]
                batch["graphs"].append(graph["index"])
            elif ev == "vk_graph_begin":
                if graph is None:
                    fail("Vulkan graph outside bound graph")
                ctx, bdf, backend = text(row, "ctx"), text(row, "bdf"), text(row, "backend")
                if bdf not in dies:
                    fail("unexpected/missing die BDF")
                if ctx in vk and vk[ctx].get("active"):
                    fail("interleaved Vulkan graph")
                if backend in backend_bdfs and backend_bdfs[backend] != bdf:
                    fail("backend BDF drift")
                backend_bdfs[backend] = bdf
                vk[ctx] = {"bdf": bdf, "graph": graph["index"], "active": True}
            elif ev == "vk_graph_end":
                ctx = text(row, "ctx")
                if ctx not in vk or not vk[ctx]["active"]:
                    fail("unmatched Vulkan graph end")
                vk[ctx]["active"] = False
            elif ev == "ctx_create":
                owners[text(row, "subctx")] = text(row, "ctx")
            elif ev in {"node", "weight", "dispatch"}:
                ctx = text(row, "ctx")
                if graph is None or ctx not in vk or not vk[ctx]["active"]:
                    fail("unbound compute recording")
                key = (text(row, "cmd"), integer(row, "use", 1))
                data = commands.setdefault(key, {"ctx": ctx, "graph": graph["index"],
                                                "bdf": vk[ctx]["bdf"], "nodes": [], "weights": [],
                                                "dispatches": [], "submitted": False})
                if data["ctx"] != ctx or data["graph"] != graph["index"] or data["submitted"]:
                    fail("command-buffer lifecycle/graph reuse mismatch")
                if ev == "node":
                    data["weights"] = []
                    data["nodes"].append({"tensor": text(row, "tensor"), "op": text(row, "op")})
                elif ev == "weight":
                    offset = integer(row, "offset")
                    size = integer(row, "bytes", 1)
                    if offset + size > integer(row, "buffer_bytes", 1):
                        fail("weight outside containing allocation")
                    data["weights"].append({"tensor": text(row, "tensor"), "buffer": text(row, "buffer"),
                                            "offset": offset, "bytes": size})
                else:
                    if not data["nodes"]:
                        fail("dispatch has no named compute node")
                    dispatch = {"pipeline": text(row, "pipeline"),
                                "workgroups": [integer(row, d, 1) for d in ("x", "y", "z")]}
                    # Capture the node/weights ACTUALLY current when dispatch was recorded.
                    dispatch["node"] = data["nodes"][-1]
                    dispatch["weights"] = list(data["weights"])
                    data["dispatches"].append(dispatch)
            elif ev == "submit":
                key = (text(row, "cmd"), integer(row, "use", 1))
                subctx = text(row, "subctx")
                if subctx not in owners:
                    fail("submission has no owner context")
                ctx = owners[subctx]
                data = commands.get(key)
                if data is None:
                    # An empty/barrier/copy-only command does not prove compute.
                    data = {"ctx": ctx, "graph": None, "dispatches": [], "submitted": False}
                    commands[key] = data
                if data["ctx"] != ctx or data["submitted"]:
                    fail("duplicate/mismatched submission")
                data["submitted"] = True
                pending.setdefault(ctx, []).append(key)
            elif ev == "fence_marker":
                if "ctx" in row:
                    markers.add(text(row, "ctx"))
                else:
                    subctx = text(row, "subctx")
                    if subctx not in owners:
                        fail("unbound empty fence marker")
                    markers.add(owners[subctx])
            elif ev == "event_record":
                ctx = text(row, "ctx")
                key = (text(row, "sync_event"), integer(row, "value", 1))
                if key in timeline or not pending.get(ctx):
                    fail("timeline record has no unique pending submission identity")
                timeline[key] = (ctx, list(pending[ctx]))
            elif ev in {"complete", "event_complete"}:
                if ev == "complete":
                    ctx = text(row, "ctx")
                    text(row, "wait")
                    if not pending.get(ctx) and ctx not in markers:
                        fail("completion has no pending submission")
                    completed_keys = list(pending.get(ctx, []))
                    markers.discard(ctx)
                else:
                    key = (text(row, "sync_event"), integer(row, "value", 1))
                    if key not in timeline:
                        fail("timeline completion identity does not match recorded event/value")
                    ctx, completed_keys = timeline.pop(key)
                for key in completed_keys:
                    data = commands[key]
                    if data.get("completed"):
                        continue  # native waits may cover already completed earlier work
                    data["completed"] = True
                    if key in pending.get(ctx, []):
                        pending[ctx].remove(key)
                    if data["dispatches"]:
                        result["graphs"][data["graph"]]["completed_compute"][data["bdf"]].append(
                            {"command": list(key), "dispatches": data["dispatches"]})
                if not pending.get(ctx):
                    pending.pop(ctx, None)
            elif ev == "copy_manifest":
                if graph is None or graph["boundaries"] or any(v["active"] for v in vk.values()):
                    fail("boundary manifest must precede graph execution")
                key = (text(row, "input"), text(row, "copy"))
                if key in graph["manifest"]:
                    fail("duplicate boundary manifest range")
                manifest = {"input": key[0], "copy": key[1], "tensor": text(row, "tensor"),
                            "src": text(row, "src"), "dst": text(row, "dst"), "bytes": integer(row, "bytes", 1),
                            "type": text(row, "type"), "shape": [integer(row, f"ne{i}", 1) for i in range(4)],
                            "strides": [integer(row, f"nb{i}", 1) for i in range(4)],
                            "view_offset": integer(row, "view_offset"), "consumed": False}
                graph["manifest"][key] = manifest
            elif ev == "boundary_begin":
                if graph is None or boundary is not None:
                    fail("unbound/nested boundary interval")
                manifest = graph["manifest"].get((text(row, "input"), text(row, "copy")))
                if manifest is None or manifest["consumed"]:
                    fail("missing or consumed preexecution boundary manifest")
                if any(row.get(k) != manifest[k] for k in ("tensor", "src", "dst")):
                    fail("boundary manifest identity mismatch")
                if row.get("bytes") != manifest["bytes"]:
                    fail("expected logical bytes disagree with preexecution manifest")
                manifest["consumed"] = True
                boundary = {"tensor": text(row, "tensor"), "src": text(row, "src"), "dst": text(row, "dst"),
                            "input": text(row, "input"), "copy": text(row, "copy"), "bytes": integer(row, "bytes", 1),
                            "begin_ns": row["ts_ns"], "legs": []}
            elif ev == "copy_path":
                if boundary is None or row.get("input") != boundary["input"] or row.get("copy") != boundary["copy"]:
                    fail("copy path outside logical boundary")
                if "src_buffer" in boundary:
                    fail("duplicate copy path")
                boundary["src_buffer"] = text(row, "src_buffer")
                boundary["dst_buffer"] = text(row, "dst_buffer")
            elif ev == "host_leg":
                if boundary is None:
                    fail("host leg outside its logical boundary")
                if "src_buffer" in row:
                    if row.get("src_buffer") != boundary.get("src_buffer") or row.get("dst_buffer") != boundary.get("dst_buffer"):
                        fail("host staging buffer path mismatch")
                elif row.get("input") != boundary["input"] or row.get("copy") != boundary["copy"]:
                    fail("host leg outside its logical boundary")
                boundary["legs"].append({"direction": text(row, "direction"), "bytes": integer(row, "bytes", 1)})
            elif ev == "boundary_end":
                if boundary is None or graph is None or row.get("input") != boundary["input"] or row.get("copy") != boundary["copy"]:
                    fail("unmatched boundary end")
                boundary["elapsed_ns"] = row["ts_ns"] - boundary.pop("begin_ns")
                if boundary["elapsed_ns"] <= 0:
                    fail("nonpositive synchronized boundary elapsed")
                graph["boundaries"].append(boundary)
                boundary = None
            elif ev == "graph_end":
                if graph is None or row.get("graph") != graph["id"] or boundary is not None or any(v["active"] for v in vk.values()):
                    fail("incomplete/unmatched graph end")
                if integer(row, "status") != 0:
                    fail("graph compute failed")
                if not graph["manifest"] or any(not m["consumed"] for m in graph["manifest"].values()):
                    fail("boundary manifest multiplicity/ranges disagree with copy events")
                graph["manifest"] = list(graph["manifest"].values())
                graph = None
            elif ev == "batch_end":
                if batch is None or graph is not None or batch["graph_tokens"] != batch["tokens"]:
                    fail("batch/ubatch graph token reconciliation")
                if integer(row, "status") != 0:
                    fail("batch decode failed")
                if batch["phase"] == "prefill":
                    seen_prefill = True
                batch = None
            elif ev == "sample":
                if batch is not None or graph is not None or integer(row, "request") != request:
                    fail("sample request mismatch")
                if not seen_prefill or integer(row, "position") != len(samples) or integer(row, "eos") not in (0, 1) or (samples and samples[-1]["eos"]):
                    fail("sample/EOS order mismatch")
                samples.append(row)
            elif ev == "response":
                if batch is not None or graph is not None or integer(row, "request") != request:
                    fail("response request mismatch")
                if integer(row, "prompt_cached"):
                    fail("prompt-cache reuse outside bounded contract")
                if integer(row, "sampled", 1) != len(samples):
                    fail("response sampled count disagrees with sampling seam")
                if integer(row, "eos") not in (0, 1) or bool(row["eos"]) != bool(samples[-1]["eos"]):
                    fail("response EOS mismatch")
                response = row
        if response is None or graph is not None or batch is not None or boundary is not None:
            fail("incomplete request/response stream")
        if pending:
            problems.append("unfinished compute submissions")
        prefill_tokens = sum(g["tokens"] for g in result["graphs"] if g["phase"] == "prefill")
        decode_graphs = [g for g in result["graphs"] if g["phase"] == "decode"]
        if response["prompt_processed"] != prefill_tokens:
            problems.append("prefill graph tokens disagree with actual prompt_processed")
        # Final prefill generates sample 0. Each decode consumes the preceding
        # sampled token and generates one next sample; terminal EOS is not decoded.
        if len(decode_graphs) != len(samples) - 1:
            problems.append("decode graph count must equal sampled tokens minus first prefill sample")
        for g in result["graphs"]:
            for die in dies:
                completed = g["completed_compute"][die]
                if not completed:
                    problems.append(f"graph {g['index']}: no completed nonempty compute on {die}")
                actual_layers = set()
                for command in completed:
                    for dispatch in command["dispatches"]:
                        for weight in dispatch["weights"]:
                            m = re.match(r"blk\.(\d+)\.", weight["tensor"])
                            if m:
                                actual_layers.add(int(m[1]))
                if not set(contract["layers"][die]).issubset(actual_layers):
                    problems.append(f"graph {g['index']}: missing dispatched named layer weights on {die}")
            matched = set()
            for b in g["boundaries"]:
                src, dst = backend_bdfs.get(b["src"]), backend_bdfs.get(b["dst"])
                matches = [i for i, exp in enumerate(expected)
                           if (b["tensor"], src, dst) == (exp["tensor"], exp["src"], exp["dst"])]
                if not matches:
                    problems.append(f"graph {g['index']}: unexpected/unbound logical boundary")
                    continue
                i = matches[0]
                if i in matched:
                    problems.append(f"graph {g['index']}: duplicate logical boundary")
                matched.add(i)
                nbytes = expected[i]["bytes_per_token"] * g["tokens"]
                b["expected_bytes"] = nbytes
                b["src_bdf"], b["dst_bdf"] = src, dst
                if b["bytes"] != nbytes:
                    problems.append(f"graph {g['index']}: expected logical bytes {nbytes}, observed {b['bytes']}")
                if b["legs"] != [{"direction": "device_to_host", "bytes": b["bytes"]},
                                 {"direction": "host_to_device", "bytes": b["bytes"]}]:
                    problems.append(f"graph {g['index']}: host staging legs do not reconcile")
                result["logical_boundary_bytes"] += b["bytes"]
                result["host_leg_bytes"] += sum(leg["bytes"] for leg in b["legs"])
                result["boundary_elapsed_ns"] += b["elapsed_ns"]
            if matched != set(range(len(expected))):
                problems.append(f"graph {g['index']}: expected boundary missing")
        result["sampled_tokens"] = len(samples)
        result["non_eos_tokens"] = sum(not s["eos"] for s in samples)
        result["ok"] = not problems
    except (ValueError, KeyError, TypeError, IndexError) as exc:
        problems.append(str(exc))
    finally:
        result["sampled_tokens"] = len(samples)
        result["non_eos_tokens"] = sum(not s["eos"] for s in samples)
        result["pending_submissions"] = [
            {"ctx": ctx, "command": list(key), "dispatches": commands[key]["dispatches"]}
            for ctx, keys in pending.items() for key in keys]
        result["incomplete_boundary"] = boundary
        if pending and "unfinished compute submissions" not in problems:
            problems.append("unfinished compute submissions")
        # Convert partially collected graph manifest keys for JSON/CLI retention.
        for g in result["graphs"]:
            if isinstance(g["manifest"], dict):
                g["manifest"] = list(g["manifest"].values())
        result["ok"] = not problems
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("raw", type=Path, help="CPU emitter log ONLY; never a model path")
    parser.add_argument("--contract", type=Path, required=True)
    args = parser.parse_args()
    # There is deliberately no physical subcommand or launch authorization seam.
    out = collect(args.raw.read_text(), json.loads(args.contract.read_text()))
    print(json.dumps(out, sort_keys=True, indent=2))
    return 0 if out["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
