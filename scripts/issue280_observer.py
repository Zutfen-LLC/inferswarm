#!/usr/bin/env python3
"""Issue #280 bounded, CPU-only raw-log collector. Physical runner is HELD.

The collector replays request-scoped source/fixture rows. It does not make a
physical-performance or acceptance claim: logical payload bytes are not PCIe
wire bytes, and nested host legs are reconciled as bytes, not elapsed time.
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
    "recording", "request_accept", "request_end", "batch_begin", "batch_end",
    "graph_begin", "graph_end", "vk_graph_begin", "vk_graph_end", "ctx_create",
    "node", "weight", "dispatch", "submit", "complete", "boundary_begin",
    "boundary_end", "host_leg", "sample", "response", "gap", "copy_path",
    "event_record", "event_complete", "fence_marker", "copy_manifest",
    "weight_inventory", "kv_inventory", "buffer_decl", "cpu_state",
    "unexplained_placement",
}
BDF = re.compile(r"[0-9a-f]{4}:[0-9a-f]{2}:[0-1][0-9a-f]\.[0-7]\Z")
TYPE_BYTES = {"f32": 4, "f16": 2, "bf16": 2, "i32": 4, "i16": 2, "i8": 1}
STOP_REASONS = {"eos", "limit", "word", "abort", "none", "error"}


def layer_of(row, field="layer"):
    """Inventory layer identity: >=0 = layer index, -1 = none (emitted by the
    pinned hooks for tensors without a blk.N. prefix, e.g. output.weight)."""
    value = row.get(field)
    if type(value) is not int or value < -1:
        raise ValueError(f"{row['event']}: invalid {field}")
    return value


def fixture_contract():
    """Synthetic two-die contract; never a physical/model acceptance criterion."""
    return {
        "kind": "CPU_FIXTURE",
        "arm": "B",
        "dies": ["0000:01:00.0", "0000:02:00.0"],
        "layers": {"0000:01:00.0": [0], "0000:02:00.0": [1]},
        "boundaries": [{"tensor": "ffn_out-0", "src": "0000:01:00.0",
                        "dst": "0000:02:00.0", "bytes_per_token": 16}],
    }


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
    """Replay bounded raw records through request, work, range and placement laws."""
    result = {
        "schema": "issue280-cpu-replay/1", "ok": False, "problems": [],
        "claim": "CPU_RECORDING_REPLAY_ONLY", "physical_runner": "HELD_UNAVAILABLE",
        "source_pin": PIN, "graphs": [], "sampled_tokens": 0, "non_eos_tokens": 0,
        "logical_boundary_bytes": 0, "host_leg_bytes": 0, "boundary_elapsed_ns": 0,
        "pcie_wire_bytes": None, "requests": [], "placement": {},
        "placement_denominator_bytes": 0, "repeated_waits": 0,
        "unsubmitted_compute": [], "pending_submissions": [], "incomplete_boundary": None,
    }
    problems = result["problems"]
    active_boundary = None
    accepted = []
    active = None
    planned = 1
    commands = {}
    pending = {}

    def fail(message) -> NoReturn:
        raise ValueError(message)

    def integer(row, field, minimum=0):
        value = row.get(field)
        if type(value) is not int or value < minimum:
            fail(f"{row.get('event', 'record')}: invalid {field}")
        return value

    def text(row, field):
        value = row.get(field)
        if not isinstance(value, str) or not value:
            fail(f"{row.get('event', 'record')}: missing {field}")
        return value

    def int_array(row, field):
        value = row.get(field)
        if not isinstance(value, list) or any(type(item) is not int for item in value):
            fail(f"{row.get('event', 'record')}: invalid {field}")
        return value

    try:
        if contract.get("kind") != "CPU_FIXTURE":
            fail("physical replay/runner unavailable; only CPU_FIXTURE contract admitted")
        dies = contract.get("dies")
        # Legacy single-die fixture contracts predate the arm field; their explicit
        # one-BDF/empty-boundary shape is an unambiguous Arm A compatibility form.
        arm = contract.get("arm")
        if arm is None:
            arm = "A" if isinstance(dies, list) and len(dies) == 1 and contract.get("boundaries", []) == [] else "B"
        if arm not in {"A", "B"} or not isinstance(dies, list):
            fail("invalid contract arm/dies")
        expected_die_count = 1 if arm == "A" else 2
        if (len(dies) != expected_die_count or len(set(dies)) != len(dies)
                or any(not isinstance(d, str) or not BDF.fullmatch(d) for d in dies)):
            fail("Arm A requires exactly one BDF" if arm == "A" else "contract requires two distinct BDFs")
        layers = contract.get("layers", {})
        if (not isinstance(layers, dict) or set(layers) != set(dies)
                or any(not isinstance(layers[d], list) or not layers[d]
                       or any(type(layer) is not int or layer < 0 for layer in layers[d])
                       for d in dies)):
            fail("contract requires named layer placement on every die")
        expected = contract.get("boundaries", [])
        if not isinstance(expected, list) or (arm == "B" and not expected):
            fail("invalid expected logical boundary contract")
        for entry in expected:
            if (not isinstance(entry, dict) or not isinstance(entry.get("tensor"), str)
                    or not entry["tensor"] or entry.get("src") not in dies
                    or entry.get("dst") not in dies or entry["src"] == entry["dst"]
                    or type(entry.get("bytes_per_token")) is not int
                    or entry["bytes_per_token"] <= 0
                    or type(entry.get("occurrences", 1)) is not int
                    or entry.get("occurrences", 1) <= 0):
                fail("invalid expected logical boundary contract")
        request_contract = contract.get("requests", {})
        if not isinstance(request_contract, dict):
            fail("invalid requests contract")
        contract_planned = request_contract.get("planned")
        if contract_planned is not None and (type(contract_planned) is not int or contract_planned < 1):
            fail("invalid planned request count")

        rows = parse(raw)
        if (rows[0]["event"] != "recording"
                or rows[0].get("kind") not in {"CPU_FIXTURE", "SOURCE_OBSERVER"}
                or rows[0].get("source_pin") != PIN):
            fail("missing explicit recording/source identity")
        if rows[0]["kind"] == "SOURCE_OBSERVER":
            result["claim"] = "SOURCE_LOG_REPLAY_ONLY_NOT_PHYSICAL_PROOF"
        planned_row = rows[0].get("requests_planned", 1)
        if type(planned_row) is not int or planned_row < 1:
            fail("recording: invalid requests_planned")
        planned = contract_planned if contract_planned is not None else planned_row

        # Process-load placement inventory is intentionally separate from dispatch
        # operands, which are compute evidence only.
        placement = {
            d: {"weights_bytes": 0, "weights_named": 0, "kv_bytes": 0,
                "staging_bytes": 0, "compute_bytes": 0, "cpu_bytes": 0,
                "unexplained_bytes": 0, "buffers": []}
            for d in dies
        }
        result["placement"] = {"dies": placement, "cpu_state": [],
                               "placement_denominator_bytes": 0}
        placement_open = True
        inventory_rows = 0
        cpu_bytes = 0
        cpu_weight_bytes = 0
        accepted = []
        request_by_id = {}
        active = None
        current_batch = None
        current_graph = None
        active_boundary = None
        contexts = {}            # ctx -> {request, bdf, graph, active}
        owners = {}              # subctx -> {request, ctx}
        backends = {}            # request id -> backend name -> BDF
        commands = {}            # request id -> (cmd,use) -> command record
        pending = {}             # request id -> ctx -> [(cmd,use)]
        timelines = {}           # request id -> (sync_event,value) -> record
        markers = {}             # request id -> set(ctx)
        copy_occurrences = {}    # graph index -> (input,copy) -> next derived occurrence
        seen_recording = False
        final_request_ended = False

        def check_request(row, phrase="request mismatch"):
            nonlocal active
            if active is None:
                fail("request framing: event outside an accepted request")
            rid = active["request"]
            if "request" in row and row["request"] != rid:
                if row.get("frame_request") is not None or row["event"] in {"graph_begin", "vk_graph_begin"}:
                    fail(f"cross-request: {row['event']} is attributed to another request")
                fail(phrase)
            if row.get("frame_request") is not None and row["frame_request"] != rid:
                fail(f"cross-request: {row['event']} frame belongs to another request")
            return rid

        def same_command_set(left, right):
            return len(left) == len(right) and set(left) == set(right)

        def req_pending(rid):
            return pending.setdefault(rid, {})

        def graph_for_command(data):
            graph_index = data.get("graph")
            if graph_index is None:
                return None
            return result["graphs"][graph_index]

        def apply_completion(rid, ctx, keys, completed_ts, timeline_key=None):
            pending_ctx = req_pending(rid).get(ctx, [])
            for command_key in keys:
                data = commands[rid].get(command_key)
                if data is None:
                    fail("completion references unknown command")
                if data["request"] != rid:
                    fail("cross-request: completion command belongs to another request")
                if data.get("completed"):
                    continue
                data["completed"] = True
                data["completed_ts_ns"] = completed_ts
                if command_key in pending_ctx:
                    pending_ctx.remove(command_key)
                active["completed_submissions"].append({
                    "status": "submitted_and_completed", "ctx": ctx,
                    "command": list(command_key), "graph": data.get("graph"),
                    "dispatches": data.get("dispatches", []), "completed_ts_ns": completed_ts,
                })
                if data.get("dispatches"):
                    graph = graph_for_command(data)
                    if graph is None:
                        fail("compute command has no graph")
                    graph["completed_compute"][data["bdf"]].append({
                        "command": list(command_key), "dispatches": data["dispatches"]})
            if not pending_ctx:
                req_pending(rid).pop(ctx, None)

        def add_problem(message):
            if message not in problems:
                problems.append(message)

        def expected_for_boundary(boundary, graph, per_expected):
            source = backends.get(active["request"], {}).get(boundary["src"])
            destination = backends.get(active["request"], {}).get(boundary["dst"])
            boundary["src_bdf"], boundary["dst_bdf"] = source, destination
            candidates = [i for i, item in enumerate(expected)
                          if (boundary["tensor"], source, destination)
                          == (item["tensor"], item["src"], item["dst"])]
            if not candidates:
                add_problem(f"graph {graph['index']}: unexpected/unbound logical boundary")
                return None
            # Duplicate identical contract rows are assigned in declaration order,
            # honoring each row's declared occurrence capacity.
            available = [i for i in candidates
                         if per_expected[i] < expected[i].get("occurrences", 1)]
            return available[0] if available else candidates[0]

        def validate_graph(graph, request_record):
            rid = request_record["request"]
            per_expected = [0] * len(expected)
            for boundary in graph["boundaries"]:
                match_index = expected_for_boundary(boundary, graph, per_expected)
                if match_index is None:
                    continue
                per_expected[match_index] += 1
                exp = expected[match_index]
                wanted = exp["bytes_per_token"] * graph["tokens"]
                boundary["expected_bytes"] = wanted
                if boundary["bytes"] != wanted:
                    add_problem(f"graph {graph['index']}: expected logical bytes {wanted}, observed {boundary['bytes']}")
                logical = graph["manifest_by_key"].get(
                    (boundary["input"], boundary["copy"], boundary["occ"]))
                if logical is None or boundary["bytes"] != logical["bytes"]:
                    add_problem(f"graph {graph['index']}: expected logical bytes disagree with manifest")
                if boundary["legs"] != [
                    {"direction": "device_to_host", "bytes": boundary["bytes"]},
                    {"direction": "host_to_device", "bytes": boundary["bytes"]},
                ]:
                    add_problem(f"graph {graph['index']}: host staging legs do not reconcile")
            for index, exp in enumerate(expected):
                wanted_count = exp.get("occurrences", 1)
                got = per_expected[index]
                if got > wanted_count:
                    add_problem(f"graph {graph['index']}: duplicate logical boundary; exact multiplicity violated")
                elif got < wanted_count:
                    add_problem(f"graph {graph['index']}: expected boundary missing; exact multiplicity {wanted_count}")

            for die in dies:
                completed = graph["completed_compute"].get(die, [])
                if not completed:
                    add_problem(f"graph {graph['index']}: no completed nonempty compute on {die}")
                    continue
                actual_layers = set()
                for command in completed:
                    for dispatch in command["dispatches"]:
                        for weight in dispatch["weights"]:
                            layer_match = re.match(r"blk\.(\d+)\.", weight["tensor"])
                            if layer_match:
                                actual_layers.add(int(layer_match[1]))
                if not set(contract["layers"][die]).issubset(actual_layers):
                    add_problem(f"graph {graph['index']}: missing dispatched named layer weights on {die}")

        def finalize_request(request_record):
            rid = request_record["request"]
            for graph in request_record["graphs"]:
                validate_graph(graph, request_record)
            for (cmd, use), data in commands.get(rid, {}).items():
                if data.get("graph") is None or not data.get("dispatches"):
                    continue
                entry = {"request": rid, "cmd": cmd, "use": use,
                         "graph": data["graph"], "dispatches": data["dispatches"]}
                if not data.get("submitted"):
                    request_record["unsubmitted_compute"].append(entry)
                    if request_record["disposition"] == "completed":
                        add_problem(f"unsubmitted compute cmd={cmd} use={use}")
                elif not data.get("completed"):
                    # Pending rows are retained separately and are never success evidence.
                    if request_record["disposition"] == "completed":
                        add_problem(f"unfinished compute submissions cmd={cmd} use={use}")
            if request_record["disposition"] != "completed":
                return
            # Successful requests require every compute-bearing command to retire and
            # every contract die to own named weights as well as completed compute.
            for die in dies:
                if placement[die]["weights_bytes"] <= 0:
                    add_problem(f"placement: no declared model-weight ownership for {die}")
                if any(graph["completed_compute"].get(die) for graph in request_record["graphs"]):
                    continue
                add_problem(f"placement: no completed nonempty compute on {die}")
            if any(item["unexplained_bytes"] for item in placement.values()):
                add_problem("placement: unexplained placement cannot establish ownership")
            # Coherence law E2: a die's weight inventory must actually cover the
            # named layers its dispatched compute reads on that die (dispatch
            # operands observed with blk.N names within the request's graphs).
            for die in dies:
                inventory_layers = set()
                for entry in placement[die]["buffers"]:
                    if entry.get("kind") != "weight_inventory":
                        continue
                    m = re.match(r"blk\.(\d+)\.", entry.get("tensor", ""))
                    if m:
                        inventory_layers.add(int(m[1]))
                for graph in request_record["graphs"]:
                    dispatched = set()
                    for command in graph["completed_compute"].get(die, []):
                        for dispatch in command["dispatches"]:
                            for weight in dispatch["weights"]:
                                m = re.match(r"blk\.(\d+)\.", weight["tensor"])
                                if m:
                                    dispatched.add(int(m[1]))
                    if not dispatched.issubset(inventory_layers):
                        add_problem(
                            f"placement: die {die} compute reads layers "
                            f"{sorted(dispatched - inventory_layers)} absent from its weight inventory")
            # Exclusive-category law E3: one buffer identity cannot be declared
            # in two placement categories (e.g. staging AND weights).
            category_of_buffer = {}
            for die in dies:
                for entry in placement[die]["buffers"]:
                    kind = entry.get("kind")
                    if kind == "weight_inventory":
                        category = "weights"
                    elif kind == "kv_inventory":
                        category = "kv"
                    elif kind == "buffer_decl":
                        category = entry.get("purpose")
                    else:
                        continue
                    buffer_id = entry.get("buffer")
                    if not buffer_id:
                        continue
                    if buffer_id in category_of_buffer and category_of_buffer[buffer_id] != category:
                        add_problem(
                            f"placement: buffer {buffer_id} declared as both "
                            f"{category_of_buffer[buffer_id]} and {category}")
                    category_of_buffer[buffer_id] = category
            requirements = contract.get("placement", {}).get("required_categories", [])
            category_fields = {"weights": "weights_bytes", "kv_cache": "kv_bytes",
                               "staging": "staging_bytes", "compute": "compute_bytes"}
            for category in requirements:
                field = category_fields.get(category)
                if field is None or any(placement[d][field] <= 0 for d in dies):
                    add_problem(f"placement: required category {category} is not declared on every die")
            # Range law B13: a consumed copy occurrence whose containing-buffer
            # bounds were never supplied is UNPROVABLE; it may not stand inside
            # a successful request (fail closed, do not guess safety).
            for graph in request_record["graphs"]:
                for manifest in graph.get("manifest", []):
                    if manifest.get("consumed") and manifest.get("bounds_status") == "UNKNOWN":
                        add_problem(
                            "range: consumed copy occurrence without any backing buffer bounds "
                            f"(input={manifest['input']} copy={manifest['copy']} occ={manifest['occ']})")

        for row in rows[1:]:
            ev = row["event"]
            if ev == "recording":
                fail("duplicate recording identity")
            if ev == "gap":
                fail("producer observation gap: " + text(row, "reason"))

            if ev == "request_accept":
                if active is not None:
                    fail("request framing: requests are not sequential")
                if final_request_ended and len(accepted) >= planned:
                    fail("records after terminal response")
                placement_open = False
                ordinal = integer(row, "ordinal", 1)
                if ordinal != len(accepted) + 1:
                    fail("request framing: ordinals must increase by one")
                rid = integer(row, "request")
                if rid in request_by_id:
                    fail("request framing: duplicate request identity")
                if ordinal > planned:
                    fail("request framing: accepted requests exceed planned count")
                record = {
                    "request": rid, "ordinal": ordinal, "accepted_ts_ns": row["ts_ns"],
                    "batches": [], "graphs": [], "samples": [], "response": None,
                    "end": None, "stop_reason": None, "prompt_processed": None,
                    "prompt_cached": None, "completed_submissions": [],
                    "incomplete_submissions": [], "unsubmitted_compute": [],
                    "completed_copies": [], "incomplete_copies": 0,
                    "incomplete_copy_intervals": [], "logical_boundary_bytes": 0,
                    "host_leg_bytes": 0, "boundary_elapsed_ns": 0,
                    "disposition": "aborted",
                }
                accepted.append(record)
                result["requests"].append(record)
                request_by_id[rid] = record
                active = record
                commands[rid] = {}
                pending[rid] = {}
                timelines[rid] = {}
                markers[rid] = set()
                backends[rid] = {}
                continue

            if ev == "request_end":
                rid = check_request(row, "request framing")
                stop_reason = text(row, "stop_reason")
                if stop_reason not in STOP_REASONS:
                    fail("request framing: invalid stop_reason")
                if current_batch is not None or current_graph is not None:
                    if stop_reason != "abort":
                        fail("request framing: request_end with open batch/graph")
                if active_boundary is not None and stop_reason != "abort":
                    fail("request framing: request_end with open copy interval")
                prompt_processed = integer(row, "prompt_processed")
                prompt_cached = integer(row, "prompt_cached")
                if active["response"] is not None:
                    response_row = active["response"]
                    if (prompt_processed != integer(response_row, "prompt_processed")
                            or prompt_cached != integer(response_row, "prompt_cached")):
                        fail("request framing: request_end accounting disagrees with response")
                elif stop_reason not in {"abort", "error"}:
                    fail("request framing: successful request_end has no response")
                active["end"] = dict(row)
                active["stop_reason"] = stop_reason
                active["prompt_processed"] = prompt_processed
                active["prompt_cached"] = prompt_cached
                successful = (active["response"] is not None
                              and stop_reason in {"eos", "limit", "word", "none"})
                active["disposition"] = "completed" if successful else "aborted"
                if active_boundary is not None:
                    incomplete = dict(active_boundary)
                    incomplete["elapsed_ns"] = None
                    incomplete["interval_status"] = "UNKNOWN"
                    active["incomplete_copy_intervals"].append(incomplete)
                    active["incomplete_copies"] += 1
                    active_boundary = None
                active["incomplete_submissions"] = [
                    {"status": "submitted_incomplete", "ctx": ctx,
                     "command": list(key), "dispatches": commands[rid][key].get("dispatches", [])}
                    for ctx, keys in pending.get(rid, {}).items() for key in keys]
                if active["disposition"] == "aborted" and active["incomplete_submissions"]:
                    add_problem("unfinished compute submissions")
                finalize_request(active)
                current_batch = None
                current_graph = None
                active = None
                final_request_ended = len(accepted) >= planned
                continue

            if ev in {"weight_inventory", "kv_inventory", "buffer_decl", "cpu_state", "unexplained_placement"}:
                if not placement_open or active is not None:
                    fail("placement: inventory must be emitted once at process load before requests")
                inventory_rows += 1
                def resolve_die(raw_name):
                    """Inventory rows bind to a die either by BDF directly or by
                    backend NAME (pinned hooks emit ggml_backend_buffer_name).
                    Backend names resolve via the stream's own vk_graph_begin
                    bindings; unresolvable names fail closed."""
                    if raw_name == "CPU" or raw_name == "unassigned":
                        return raw_name
                    if raw_name in placement:
                        return raw_name
                    for per_request in backends.values():
                        if per_request.get(raw_name) in placement:
                            return per_request[raw_name]
                    fail(f"placement: inventory backend {raw_name!r} is neither a contract die, "
                         "CPU, nor a stream-bound backend name")
                if ev == "weight_inventory":
                    die = resolve_die(text(row, "bdf"))
                    name, size = text(row, "tensor"), integer(row, "bytes", 1)
                    layer_of(row)
                    if die == "CPU":
                        # CPU-owned intended state: real backend name fallback
                        # (ggml_backend_buffer_name), not a BDF. Accounted
                        # separately; never a candidate-die numerator.
                        if die in placement:
                            fail("placement: CPU inventory BDF collision")
                        cpu_weight_bytes += size
                        result["placement"]["cpu_state"].append(
                            {"kind": "cpu_weights:" + name, "bytes": size})
                        continue
                    if die not in placement:
                        fail("placement: unexpected weight inventory BDF")
                    placement[die]["weights_bytes"] += size
                    placement[die]["weights_named"] += 1
                    placement[die]["buffers"].append({"kind": "weight_inventory", "tensor": name,
                                                        "buffer": text(row, "buffer"), "bytes": size})
                    result["placement"]["placement_denominator_bytes"] += size
                elif ev == "kv_inventory":
                    die, kind = resolve_die(text(row, "bdf")), text(row, "kind")
                    if kind not in {"k", "v", "kv"}:
                        fail("placement: invalid KV inventory")
                    if die == "CPU":
                        # CPU-owned KV/mutable state (backend-name fallback).
                        size = integer(row, "bytes", 1)
                        layer_of(row)
                        cpu_bytes += size
                        result["placement"]["cpu_state"].append(
                            {"kind": "cpu_kv:" + text(row, "tensor"), "bytes": size})
                        continue
                    if die not in placement:
                        fail("placement: invalid KV inventory")
                    size = integer(row, "bytes", 1)
                    layer_of(row)
                    placement[die]["kv_bytes"] += size
                    placement[die]["buffers"].append({"kind": "kv_inventory", "tensor": text(row, "tensor"),
                                                        "buffer": row.get("buffer"), "bytes": size})
                elif ev == "buffer_decl":
                    die, purpose = resolve_die(text(row, "bdf")), text(row, "purpose")
                    if die not in placement or purpose not in {"weights", "kv", "staging", "compute", "unknown"}:
                        fail("placement: invalid buffer declaration")
                    size = integer(row, "bytes", 1)
                    if purpose == "staging":
                        placement[die]["staging_bytes"] += size
                    elif purpose == "compute":
                        placement[die]["compute_bytes"] += size
                    placement[die]["buffers"].append({"kind": "buffer_decl", "buffer": text(row, "buffer"),
                                                        "purpose": purpose, "bytes": size})
                elif ev == "cpu_state":
                    kind, size = text(row, "kind"), integer(row, "bytes", 1)
                    cpu_bytes += size
                    result["placement"]["cpu_state"].append({"kind": kind, "bytes": size})
                else:
                    die, size = resolve_die(text(row, "bdf")), integer(row, "bytes", 1)
                    if die not in placement:
                        fail("placement: unexplained row references unknown BDF")
                    placement[die]["unexplained_bytes"] += size
                    placement[die]["buffers"].append({"kind": "unexplained", "bytes": size,
                                                        "note": row.get("note", "")})
                continue

            if active is None:
                if (ev == "response" and row.get("request") in request_by_id
                        and request_by_id[row["request"]].get("end") is not None):
                    fail("cross-request: response for an already-ended request")
                if final_request_ended and len(accepted) >= planned:
                    fail("records after terminal response")
                fail("request framing: missing request_accept before request event")
            rid = active["request"]
            if active["response"] is not None and ev not in {"request_end"}:
                fail("request framing: records after this request's response")
            if ev in {"batch_begin", "batch_end", "graph_begin", "graph_end", "sample", "response"} and "request" not in row:
                fail(f"request framing: {ev} is missing request binding")
            if ev in {"batch_begin", "sample", "response"}:
                phrase = "cross-request: response belongs to another request" if ev == "response" else "request mismatch"
                check_request(row, phrase)
            elif "request" in row:
                check_request(row, "cross-request: row references a different request")
            elif "frame_request" in row:
                check_request(row)

            if ev == "batch_begin":
                if current_batch is not None or current_graph is not None or active_boundary is not None:
                    fail("interleaved request/batch")
                phase = text(row, "phase")
                if phase not in {"prefill", "decode"} or integer(row, "speculative") != 0:
                    fail("unsupported phase/speculative request")
                ntok = integer(row, "tokens", 1)
                token_ids = int_array(row, "token_ids")
                positions = int_array(row, "positions")
                if phase == "prefill":
                    if (len(token_ids) != ntok or len(positions) != ntok
                            or any(token < 0 for token in token_ids)
                            or positions != list(range(active.get("next_prefill_position", 0),
                                                       active.get("next_prefill_position", 0) + ntok))):
                        fail("prefill position/token law")
                    active["next_prefill_position"] = active.get("next_prefill_position", 0) + ntok
                    if active["samples"]:
                        fail("prefill after sampling")
                else:
                    if ntok != 1 or not active["samples"]:
                        fail("decode must consume exactly one previous sampled token")
                    previous = active["samples"][-1]
                    if len(token_ids) != 1 or token_ids[0] != previous["token_id"]:
                        fail("decode token does not match the prior sample")
                    if len(positions) != 1 or positions[0] != previous["absolute_position"]:
                        fail("decode position does not match the sampled token position")
                    if previous["eos"]:
                        fail("decode after terminal EOS sample")
                current_batch = {"request": rid, "tokens": ntok, "phase": phase,
                                 "seq": integer(row, "seq"), "graph_tokens": 0,
                                 "graphs": [], "token_ids": token_ids, "positions": positions}
                active["batches"].append(current_batch)
            elif ev == "graph_begin":
                if current_batch is None or current_graph is not None or active_boundary is not None:
                    fail("unbound/interleaved graph")
                if "request" in row and row["request"] != rid:
                    fail("cross-request: graph belongs to another request")
                if integer(row, "sequences", 1) != 1 or integer(row, "seq") != current_batch["seq"]:
                    fail("graph sequence/request mismatch")
                graph_index = len(result["graphs"])
                current_graph = {
                    "index": graph_index, "request": rid, "id": text(row, "graph"),
                    "phase": current_batch["phase"], "tokens": integer(row, "tokens", 1),
                    "completed_compute": {d: [] for d in dies}, "boundaries": [],
                    "manifest": [], "manifest_by_key": {}, "_manifest_rows": {},
                }
                result["graphs"].append(current_graph)
                active["graphs"].append(current_graph)
                current_batch["graph_tokens"] += current_graph["tokens"]
                current_batch["graphs"].append(graph_index)
                copy_occurrences[graph_index] = {}
            elif ev == "vk_graph_begin":
                if current_graph is None:
                    fail("Vulkan graph outside bound graph")
                ctx, bdf, backend = text(row, "ctx"), text(row, "bdf"), text(row, "backend")
                if "request" in row and row["request"] != rid:
                    fail("cross-request: Vulkan graph request binding mismatch")
                # The pinned vk hook omits the request field: bind structurally
                # to the request whose graph is open (a MISMATCHED explicit
                # request above is still rejected).
                if bdf not in dies:
                    fail("unexpected/missing die BDF")
                if ctx in contexts and contexts[ctx].get("active"):
                    fail("interleaved Vulkan graph")
                prior_bdf = backends[rid].get(backend)
                if prior_bdf is not None and prior_bdf != bdf:
                    fail("backend BDF drift")
                backends[rid][backend] = bdf
                contexts[ctx] = {"request": rid, "bdf": bdf,
                                 "graph": current_graph["index"], "active": True}
            elif ev == "vk_graph_end":
                ctx = text(row, "ctx")
                if ctx not in contexts or not contexts[ctx]["active"]:
                    fail("unmatched Vulkan graph end")
                if contexts[ctx]["request"] != rid:
                    fail("cross-request: Vulkan graph end belongs to another request")
                contexts[ctx]["active"] = False
            elif ev == "ctx_create":
                subctx, ctx = text(row, "subctx"), text(row, "ctx")
                if ctx in contexts and contexts[ctx]["request"] != rid:
                    fail("cross-request: context owner mismatch")
                owners[subctx] = {"request": rid, "ctx": ctx}
            elif ev in {"node", "weight", "dispatch"}:
                ctx = text(row, "ctx")
                if current_graph is None or ctx not in contexts or not contexts[ctx]["active"]:
                    fail("unbound compute recording")
                if contexts[ctx]["request"] != rid or contexts[ctx]["graph"] != current_graph["index"]:
                    fail("cross-request: command context belongs to another request/graph")
                key = (text(row, "cmd"), integer(row, "use"))
                command = commands[rid].setdefault(key, {
                    "request": rid, "ctx": ctx, "graph": current_graph["index"],
                    "bdf": contexts[ctx]["bdf"], "nodes": [], "weights": [],
                    "dispatches": [], "submitted": False, "completed": False,
                })
                if (command["ctx"] != ctx or command["graph"] != current_graph["index"]
                        or command["submitted"]):
                    fail("command-buffer lifecycle/graph reuse mismatch")
                if ev == "node":
                    command["weights"] = []
                    command["nodes"].append({"tensor": text(row, "tensor"), "op": text(row, "op")})
                elif ev == "weight":
                    offset, size = integer(row, "offset"), integer(row, "bytes", 1)
                    if offset + size > integer(row, "buffer_bytes", 1):
                        fail("weight outside containing allocation")
                    command["weights"].append({"tensor": text(row, "tensor"),
                                               "buffer": text(row, "buffer"),
                                               "offset": offset, "bytes": size})
                else:
                    if not command["nodes"]:
                        fail("dispatch has no named compute node")
                    dispatch = {"pipeline": text(row, "pipeline"),
                                "workgroups": [integer(row, field, 1) for field in ("x", "y", "z")],
                                "node": command["nodes"][-1], "weights": list(command["weights"])}
                    command["dispatches"].append(dispatch)
            elif ev == "submit":
                key = (text(row, "cmd"), integer(row, "use"))
                subctx = text(row, "subctx")
                owner = owners.get(subctx)
                if owner is None:
                    fail("submission has no owner context")
                if owner["request"] != rid:
                    fail("cross-request: submission owner belongs to another request")
                ctx = owner["ctx"]
                command = commands[rid].get(key)
                if command is None:
                    command = {"request": rid, "ctx": ctx, "graph": None, "bdf": None,
                               "nodes": [], "weights": [], "dispatches": [],
                               "submitted": False, "completed": False}
                    commands[rid][key] = command
                if command["ctx"] != ctx or command["submitted"]:
                    fail("duplicate/mismatched submission")
                command["submitted"] = True
                req_pending(rid).setdefault(ctx, []).append(key)
            elif ev == "fence_marker":
                if "ctx" in row:
                    ctx = text(row, "ctx")
                else:
                    subctx = text(row, "subctx")
                    owner = owners.get(subctx)
                    if owner is None or owner["request"] != rid:
                        fail("unbound empty fence marker")
                    ctx = owner["ctx"]
                if ctx in contexts and contexts[ctx]["request"] != rid:
                    fail("cross-request: fence marker belongs to another request")
                markers[rid].add(ctx)
            elif ev == "event_record":
                ctx = text(row, "ctx")
                if ctx in contexts and contexts[ctx]["request"] != rid:
                    fail("cross-request: timeline context belongs to another request")
                key = (text(row, "sync_event"), integer(row, "value"))
                if key in timelines[rid] or not req_pending(rid).get(ctx):
                    fail("timeline record has no unique pending submission identity")
                timelines[rid][key] = {"ctx": ctx, "commands": list(req_pending(rid)[ctx]),
                                       "completed": False}
            elif ev in {"complete", "event_complete"}:
                if ev == "complete":
                    ctx = text(row, "ctx")
                    if ctx in contexts and contexts[ctx]["request"] != rid:
                        fail("cross-request: completion context belongs to another request")
                    text(row, "wait")
                    if not req_pending(rid).get(ctx) and ctx not in markers[rid]:
                        fail("completion has no pending submission")
                    completed_keys = list(req_pending(rid).get(ctx, []))
                    markers[rid].discard(ctx)
                    apply_completion(rid, ctx, completed_keys, row["ts_ns"])
                else:
                    key = (text(row, "sync_event"), integer(row, "value"))
                    timeline = timelines[rid].get(key)
                    if timeline is None:
                        # A same-named identity in another request is not transferable.
                        foreign = any(key in entries for other, entries in timelines.items() if other != rid)
                        if foreign:
                            fail("cross-request: timeline identity belongs to another request")
                        fail("timeline completion identity does not match recorded event/value")
                    supplied = None
                    if "commands" in row:
                        supplied = row["commands"]
                        if (not isinstance(supplied, list)
                                or any(not isinstance(pair, list) or len(pair) != 2
                                       or type(pair[1]) is not int for pair in supplied)):
                            fail("event_complete: invalid command set")
                        supplied = [tuple(pair) for pair in supplied]
                    elif "cmd" in row or "use" in row:
                        supplied = [(text(row, "cmd"), integer(row, "use"))]
                    if timeline["completed"]:
                        if supplied is not None and not same_command_set(supplied, timeline["commands"]):
                            fail("conflicting timeline reuse")
                        result["repeated_waits"] += 1
                        continue
                    ctx, completed_keys = timeline["ctx"], list(timeline["commands"])
                    pending_keys = set(req_pending(rid).get(ctx, []))
                    if any(command_key not in pending_keys
                           and not commands[rid][command_key].get("completed")
                           for command_key in completed_keys):
                        fail("conflicting timeline reuse")
                    if supplied is not None and not same_command_set(supplied, completed_keys):
                        fail("conflicting timeline reuse")
                    apply_completion(rid, ctx, completed_keys, row["ts_ns"], key)
                    timeline["completed"] = True
            elif ev == "copy_manifest":
                if current_graph is None or current_graph["boundaries"] or any(
                        context["active"] and context["graph"] == current_graph["index"]
                        for context in contexts.values()):
                    fail("boundary manifest must precede graph execution")
                input_id, copy_id = text(row, "input"), text(row, "copy")
                occurrence_key = (input_id, copy_id)
                derived = copy_occurrences[current_graph["index"]].get(occurrence_key, 0)
                supplied_occ = integer(row, "occ")
                if supplied_occ != derived:
                    fail("occurrence identity mismatch")
                copy_occurrences[current_graph["index"]][occurrence_key] = derived + 1
                tensor_type = text(row, "type")
                if tensor_type not in TYPE_BYTES:
                    fail("unsupported tensor type")
                shape = [integer(row, f"ne{i}", 1) for i in range(4)]
                strides = [integer(row, f"nb{i}", 1) for i in range(4)]
                size = TYPE_BYTES[tensor_type]
                if strides[0] != size:
                    fail("nb0 inconsistent with type")
                law_bytes = size + sum((shape[i] - 1) * strides[i] for i in range(4))
                claimed = integer(row, "bytes", 1)
                if claimed != law_bytes:
                    fail("range: logical bytes inconsistent with type/shape/stride law")
                view_offset = integer(row, "view_offset")
                bounds = {}
                for field in ("buffer_bytes", "src_buffer_bytes", "dst_buffer_bytes"):
                    if field in row:
                        bounds[field] = integer(row, field)
                        if view_offset + law_bytes > bounds[field]:
                            fail("range overflow")
                    else:
                        bounds[field] = None
                for field in ("src_offset", "dst_offset"):
                    if field in row:
                        integer(row, field)
                manifest = {
                    "input": input_id, "copy": copy_id, "occ": supplied_occ,
                    "tensor": text(row, "tensor"), "src": text(row, "src"),
                    "dst": text(row, "dst"), "bytes": claimed, "type": tensor_type,
                    "shape": shape, "strides": strides, "view_offset": view_offset,
                    "bounds": bounds, "bounds_status": "KNOWN" if any(v is not None for v in bounds.values()) else "UNKNOWN",
                    "consumed": False,
                }
                key = (input_id, copy_id, supplied_occ)
                if key in current_graph["manifest_by_key"]:
                    fail("duplicate boundary manifest occurrence")
                current_graph["manifest_by_key"][key] = manifest
                current_graph["manifest"].append(manifest)
            elif ev == "boundary_begin":
                if current_graph is None or active_boundary is not None:
                    fail("unbound/nested boundary interval")
                key = (text(row, "input"), text(row, "copy"), integer(row, "occ"))
                manifest = current_graph["manifest_by_key"].get(key)
                if manifest is None or manifest["consumed"]:
                    fail("missing or consumed preexecution boundary manifest")
                if any(row.get(field) != manifest[field] for field in ("tensor", "src", "dst")):
                    fail("boundary manifest identity mismatch")
                if integer(row, "bytes", 1) != manifest["bytes"]:
                    fail("expected logical bytes disagree with preexecution manifest")
                bounds = {}
                for field in ("buffer_bytes", "src_buffer_bytes", "dst_buffer_bytes"):
                    if field in row:
                        bound = integer(row, field)
                        bounds[field] = bound
                        if manifest["view_offset"] + manifest["bytes"] > bound:
                            fail("range overflow")
                    else:
                        bounds[field] = manifest["bounds"].get(field)
                manifest["consumed"] = True
                active_boundary = {
                    "request": rid, "graph": current_graph["index"],
                    "tensor": text(row, "tensor"), "src": text(row, "src"),
                    "dst": text(row, "dst"), "input": key[0], "copy": key[1],
                    "occ": key[2], "bytes": integer(row, "bytes", 1),
                    "begin_ns": row["ts_ns"], "legs": [], "src_buffer": None,
                    "dst_buffer": None, "bounds": bounds,
                    "bounds_status": "KNOWN" if any(v is not None for v in bounds.values()) else "UNKNOWN",
                }
            elif ev == "copy_path":
                key = (text(row, "input"), text(row, "copy"), integer(row, "occ"))
                if (active_boundary is None or key != (active_boundary["input"],
                        active_boundary["copy"], active_boundary["occ"])):
                    fail("copy path outside logical boundary occurrence")
                if active_boundary["src_buffer"] is not None:
                    fail("duplicate copy path")
                active_boundary["src_buffer"] = text(row, "src_buffer")
                active_boundary["dst_buffer"] = text(row, "dst_buffer")
            elif ev == "host_leg":
                key = (text(row, "input"), text(row, "copy"), integer(row, "occ"))
                if active_boundary is None or key != (active_boundary["input"],
                        active_boundary["copy"], active_boundary["occ"]):
                    fail("host leg outside its logical boundary occurrence")
                if "src_buffer" in row:
                    if (row.get("src_buffer") != active_boundary.get("src_buffer")
                            or row.get("dst_buffer") != active_boundary.get("dst_buffer")):
                        fail("host staging buffer path mismatch")
                active_boundary["legs"].append({"direction": text(row, "direction"),
                                                 "bytes": integer(row, "bytes", 1)})
            elif ev == "boundary_end":
                key = (text(row, "input"), text(row, "copy"), integer(row, "occ"))
                if current_graph is None or active_boundary is None or key != (
                        active_boundary["input"], active_boundary["copy"], active_boundary["occ"]):
                    fail("unmatched boundary end")
                if "bytes" in row and integer(row, "bytes", 1) != active_boundary["bytes"]:
                    fail("boundary end bytes disagree with manifest")
                elapsed = row["ts_ns"] - active_boundary["begin_ns"]
                if elapsed <= 0:
                    fail("nonpositive synchronized boundary elapsed")
                completed = dict(active_boundary)
                completed.pop("begin_ns")
                completed["elapsed_ns"] = elapsed
                current_graph["boundaries"].append(completed)
                result["logical_boundary_bytes"] += completed["bytes"]
                result["host_leg_bytes"] += sum(leg["bytes"] for leg in completed["legs"])
                result["boundary_elapsed_ns"] += elapsed
                active["logical_boundary_bytes"] += completed["bytes"]
                active["host_leg_bytes"] += sum(leg["bytes"] for leg in completed["legs"])
                active["boundary_elapsed_ns"] += elapsed
                active["completed_copies"].append({
                    "graph": current_graph["index"], "input": completed["input"],
                    "copy": completed["copy"], "occ": completed["occ"],
                    "tensor": completed["tensor"], "bytes": completed["bytes"],
                    "elapsed_ns": elapsed,
                })
                active_boundary = None
            elif ev == "graph_end":
                if (current_graph is None or row.get("graph") != current_graph["id"]
                        or active_boundary is not None
                        or any(context["active"] and context["graph"] == current_graph["index"]
                               for context in contexts.values())):
                    fail("incomplete/unmatched graph end")
                if integer(row, "status") != 0:
                    fail("graph compute failed")
                if any(not manifest["consumed"] for manifest in current_graph["manifest"]):
                    fail("boundary manifest multiplicity/ranges disagree with copy events")
                current_graph.pop("_manifest_rows", None)
                current_graph = None
            elif ev == "batch_end":
                if current_batch is None or current_graph is not None or current_batch["graph_tokens"] != current_batch["tokens"]:
                    fail("batch/ubatch graph token reconciliation")
                if integer(row, "status") != 0:
                    fail("batch decode failed")
                current_batch = None
            elif ev == "sample":
                if current_batch is not None or current_graph is not None:
                    fail("sample emitted before batch/graph completion")
                seq_position = integer(row, "position")
                token_id = integer(row, "token_id")
                absolute_position = integer(row, "absolute_position")
                eos = integer(row, "eos")
                if eos not in (0, 1) or seq_position != len(active["samples"]):
                    fail("sample/EOS order mismatch")
                if active["samples"] and active["samples"][-1]["eos"]:
                    fail("sample after terminal EOS")
                if active["samples"]:
                    if absolute_position != active["samples"][-1]["absolute_position"] + 1:
                        fail("sample absolute position mismatch")
                else:
                    prompt_tokens = sum(g["tokens"] for g in active["graphs"] if g["phase"] == "prefill")
                    if absolute_position != prompt_tokens:
                        fail("sample absolute position mismatch")
                sample = {"request": rid, "position": seq_position, "token_id": token_id,
                          "absolute_position": absolute_position, "eos": eos,
                          "ts_ns": row["ts_ns"]}
                active["samples"].append(sample)
                result.setdefault("samples", []).append(sample)
            elif ev == "response":
                if current_batch is not None or current_graph is not None:
                    fail("response before batch/graph completion")
                if active["response"] is not None:
                    fail("cross-request: response for an already-ended request")
                sampled = integer(row, "sampled", 1)
                prompt_processed = integer(row, "prompt_processed")
                prompt_cached = integer(row, "prompt_cached")
                eos = integer(row, "eos")
                if sampled != len(active["samples"]):
                    fail("response sampled count disagrees with sampling seam")
                if eos not in (0, 1) or bool(eos) != bool(active["samples"][-1]["eos"]):
                    fail("response EOS mismatch")
                prefill_tokens = sum(g["tokens"] for g in active["graphs"] if g["phase"] == "prefill")
                if prompt_processed != prefill_tokens:
                    add_problem("prefill graph tokens disagree with actual prompt_processed")
                decode_graphs = [g for g in active["graphs"] if g["phase"] == "decode"]
                if len(decode_graphs) != len(active["samples"]) - 1:
                    add_problem("decode graph count must equal sampled tokens minus first prefill sample")
                active["response"] = dict(row)
                active["prompt_processed"] = prompt_processed
                active["prompt_cached"] = prompt_cached
                active["response_ts_ns"] = row["ts_ns"]
            else:
                fail(f"unsupported/unhandled event {ev}")

        if not accepted:
            fail("request framing: missing request_accept/request_end rows")
        if active is not None:
            # A truncated process stream is retained as an abort, but is never allowed
            # to pass framing or become a success observation.
            add_problem("request framing: missing request_end row")
            active["stop_reason"] = "abort"
            active["disposition"] = "aborted"
            active["incomplete_submissions"] = [
                {"status": "submitted_incomplete", "ctx": ctx, "command": list(key),
                 "dispatches": commands[active["request"]][key].get("dispatches", [])}
                for ctx, keys in pending.get(active["request"], {}).items() for key in keys]
            if active_boundary is not None:
                incomplete = dict(active_boundary)
                incomplete["elapsed_ns"] = None
                incomplete["interval_status"] = "UNKNOWN"
                active["incomplete_copy_intervals"].append(incomplete)
                active["incomplete_copies"] += 1
                active_boundary = None
            if active["incomplete_submissions"]:
                add_problem("unfinished compute submissions")
            finalize_request(active)
            active = None
        if current_batch is not None or current_graph is not None:
            add_problem("request framing: stream ended with open batch/graph")
        if active_boundary is not None:
            incomplete = dict(active_boundary)
            incomplete["elapsed_ns"] = None
            incomplete["interval_status"] = "UNKNOWN"
            accepted[-1]["incomplete_copy_intervals"].append(incomplete)
            accepted[-1]["incomplete_copies"] += 1
            active_boundary = None

        # Every accepted request must have explicit acceptance and end framing.
        for request_record in accepted:
            if request_record["end"] is None:
                add_problem("request framing: missing request_end row")
        not_attempted = []
        for ordinal in range(len(accepted) + 1, planned + 1):
            not_attempted.append({
                "request": None, "ordinal": ordinal, "accepted_ts_ns": None,
                "batches": [], "graphs": [], "samples": [], "response": None,
                "end": None, "stop_reason": None, "prompt_processed": None,
                "prompt_cached": None, "completed_submissions": [],
                "incomplete_submissions": [], "unsubmitted_compute": [],
                "completed_copies": [], "incomplete_copies": 0,
                "incomplete_copy_intervals": [], "disposition": "not_attempted",
            })
        result["requests"] = accepted + not_attempted
        for request_record in accepted:
            result["sampled_tokens"] += len(request_record["samples"])
            result["non_eos_tokens"] += sum(sample["eos"] == 0 for sample in request_record["samples"])
            result["unsubmitted_compute"].extend(request_record["unsubmitted_compute"])
            result["pending_submissions"].extend(request_record["incomplete_submissions"])
            if request_record["disposition"] == "aborted":
                result["ok"] = False
        all_incomplete = [copy for request_record in accepted
                          for copy in request_record["incomplete_copy_intervals"]]
        if all_incomplete:
            result["incomplete_boundary"] = all_incomplete[0] if len(all_incomplete) == 1 else all_incomplete
        result["abort_accounting"] = {
            "unsubmitted_compute": [entry for request_record in accepted
                                     if request_record["disposition"] == "aborted"
                                     for entry in request_record["unsubmitted_compute"]],
            "completed_submissions": [entry for request_record in accepted
                                       if request_record["disposition"] == "aborted"
                                       for entry in request_record["completed_submissions"]],
            "pending_submissions": [entry for request_record in accepted
                                     if request_record["disposition"] == "aborted"
                                     for entry in request_record["incomplete_submissions"]],
            "completed_copies": [entry for request_record in accepted
                                  if request_record["disposition"] == "aborted"
                                  for entry in request_record["completed_copies"]],
            "incomplete_copies": all_incomplete,
        }
        if len(accepted) == 1 and accepted[0]["disposition"] == "aborted":
            result["disposition"] = "ABORTED"
        result["placement"]["placement_denominator_bytes"] = sum(
            die["weights_bytes"] for die in placement.values()) + cpu_weight_bytes
        result["placement_denominator_bytes"] = result["placement"]["placement_denominator_bytes"]
        result["placement"]["cpu_bytes"] = cpu_bytes
        result["placement"]["cpu_weight_bytes"] = cpu_weight_bytes
        # Denominator law E5: make the relation explicit and machine-checkable.
        # die_numerators_sum + cpu_weight_bytes == denominator ALWAYS (the later
        # >=25%-per-die criterion reads the denominator; its numerator is a
        # single die's placement_numerator_bytes; CPU-owned state is never a
        # candidate-die numerator).
        for die in dies:
            placement[die]["placement_numerator_bytes"] = placement[die]["weights_bytes"]
            placement[die]["cpu_bytes"] = 0  # cpu_state has process scope, not a BDF
        die_numerators_sum = sum(placement[d]["placement_numerator_bytes"] for d in dies)
        result["placement"]["die_numerators_sum_bytes"] = die_numerators_sum
        result["placement"]["denominator_relation"] = (
            "die_numerators_sum_bytes + cpu_weight_bytes == placement_denominator_bytes"
            if die_numerators_sum + cpu_weight_bytes ==
            result["placement"]["placement_denominator_bytes"] else "INCONSISTENT")
        for graph in result["graphs"]:
            graph.pop("_manifest_rows", None)
            graph.pop("manifest_by_key", None)
            graph["manifest"] = graph.get("manifest", [])
        result["ok"] = not problems and all(
            request_record["disposition"] != "aborted" for request_record in accepted)
    except (ValueError, KeyError, TypeError, IndexError) as exc:
        problems.append(str(exc))
    finally:
        if active is not None and active.get("end") is None:
            active["stop_reason"] = active.get("stop_reason") or "error"
            active["disposition"] = "aborted"
            rid = active["request"]
            if active_boundary is not None:
                incomplete = dict(active_boundary)
                incomplete["elapsed_ns"] = None
                incomplete["interval_status"] = "UNKNOWN"
                active["incomplete_copy_intervals"].append(incomplete)
                active["incomplete_copies"] += 1
                active_boundary = None
            active["incomplete_submissions"] = [
                {"status": "submitted_incomplete", "ctx": ctx,
                 "command": list(key),
                 "dispatches": commands.get(rid, {}).get(key, {}).get("dispatches", [])}
                for ctx, keys in pending.get(rid, {}).items() for key in keys]
        if accepted:
            unattempted = [req for req in result["requests"]
                           if req.get("disposition") == "not_attempted"]
            known_ordinals = {req["ordinal"] for req in unattempted}
            for ordinal in range(len(accepted) + 1, planned + 1):
                if ordinal not in known_ordinals:
                    unattempted.append({
                        "request": None, "ordinal": ordinal, "accepted_ts_ns": None,
                        "batches": [], "graphs": [], "samples": [], "response": None,
                        "end": None, "stop_reason": None, "prompt_processed": None,
                        "prompt_cached": None, "completed_submissions": [],
                        "incomplete_submissions": [], "unsubmitted_compute": [],
                        "completed_copies": [], "incomplete_copies": 0,
                        "incomplete_copy_intervals": [], "logical_boundary_bytes": 0,
                        "host_leg_bytes": 0, "boundary_elapsed_ns": 0,
                        "disposition": "not_attempted",
                    })
            result["requests"] = accepted + sorted(unattempted, key=lambda req: req["ordinal"])
            for request_record in accepted:
                rid = request_record["request"]
                request_record["unsubmitted_compute"] = [
                    {"status": "recorded_never_submitted", "request": rid,
                     "cmd": cmd, "use": use, "graph": data.get("graph"),
                     "dispatches": data.get("dispatches", [])}
                    for (cmd, use), data in commands.get(rid, {}).items()
                    if data.get("dispatches") and not data.get("submitted")]
                request_record["incomplete_submissions"] = [
                    {"ctx": data["ctx"], "command": [cmd, use],
                     "dispatches": data.get("dispatches", [])}
                    for (cmd, use), data in commands.get(rid, {}).items()
                    if data.get("submitted") and not data.get("completed")]
            result["unsubmitted_compute"] = [
                entry for req in accepted for entry in req["unsubmitted_compute"]]
            result["pending_submissions"] = [
                entry for req in accepted for entry in req["incomplete_submissions"]]
            all_incomplete = [copy for req in accepted
                              for copy in req["incomplete_copy_intervals"]]
            if all_incomplete:
                result["incomplete_boundary"] = all_incomplete[0] if len(all_incomplete) == 1 else all_incomplete
            result["abort_accounting"] = {
                "unsubmitted_compute": [entry for req in accepted if req["disposition"] == "aborted"
                                         for entry in req["unsubmitted_compute"]],
                "completed_submissions": [entry for req in accepted if req["disposition"] == "aborted"
                                           for entry in req["completed_submissions"]],
                "pending_submissions": [entry for req in accepted if req["disposition"] == "aborted"
                                         for entry in req["incomplete_submissions"]],
                "completed_copies": [entry for req in accepted if req["disposition"] == "aborted"
                                      for entry in req["completed_copies"]],
                "incomplete_copies": all_incomplete,
            }
            if len(accepted) == 1 and accepted[0]["disposition"] == "aborted":
                result["disposition"] = "ABORTED"
        result["sampled_tokens"] = sum(
            len(req.get("samples", [])) for req in result.get("requests", []))
        result["non_eos_tokens"] = sum(
            sample["eos"] == 0 for req in result.get("requests", [])
            for sample in req.get("samples", []))
        if active_boundary is not None:
            incomplete = dict(active_boundary)
            incomplete["elapsed_ns"] = None
            incomplete["interval_status"] = "UNKNOWN"
            result["incomplete_boundary"] = incomplete
        if result["placement"].get("dies"):
            die_rows = result["placement"]["dies"]
            result["placement"]["placement_denominator_bytes"] = sum(
                data["weights_bytes"] for data in die_rows.values()) + \
                result["placement"].get("cpu_weight_bytes", 0)
            result["placement_denominator_bytes"] = result["placement"]["placement_denominator_bytes"]
            for die_data in die_rows.values():
                die_data["placement_numerator_bytes"] = die_data["weights_bytes"]
        for graph in result["graphs"]:
            graph.pop("_manifest_rows", None)
            graph.pop("manifest_by_key", None)
        result["ok"] = not problems and not any(
            req.get("disposition") == "aborted" for req in result.get("requests", []))
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
