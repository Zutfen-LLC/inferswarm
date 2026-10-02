#!/usr/bin/env python3
"""Prospective #260 Vulkan event grammar and source-scoped closure (no physical IO).

Parsing a synthetic or retained log never authenticates its producer. A future
producer must bind exact source tree and binary bytes before using these laws.
Historical #254 evidence is never accepted under this new source identity.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IDENTITY_PATH = ROOT / "docs/investigations/qwen38-flash-next-r8-i3c-vulkan-mechanism/issue260-source-identity.json"
IDENTITY262_PATH = ROOT / "docs/investigations/qwen38-flash-next-r8-i3c-vulkan-mechanism/issue262-source-identity.json"
INSTRUMENTED_TREE = (json.loads(IDENTITY_PATH.read_text(encoding="utf-8"))["instrumented_tree"]
                     if IDENTITY_PATH.is_file() else "")
# #262 successor identity: the same H2/H3 marker grammar is emitted unchanged
# by the #262 instrumented comparator (the H5 route marker is additive and
# parsed by issue262_h5). H2/H3 parsing accepts EITHER frozen tree identity;
# every other source identity still fails closed.
INSTRUMENTED262_TREE = (json.loads(IDENTITY262_PATH.read_text(encoding="utf-8"))["instrumented262_tree"]
                        if IDENTITY262_PATH.is_file() else "")
PREFIX = "ggml_vk_i260:v1|"
# GGML common-log line prefix retained in the real server-log stream (e.g.
# ``0.03.976.621 I ``). A marker line must be bare or carry exactly this
# shape before the marker; any other prefix fails closed (#262 real-stream
# law — the synthetic-only startswith check never survived a real log).
LOG_PREFIX_PLAIN = re.compile(r"\d+\.\d+\.\d+\.\d+ [IWEC] ")
# Interleaved lines from other GGML log sites can wrap a marker in their
# own banner (two shapes observed in the real #262 stream: the memory
# logger ``ggml_vulkan memory: Vulkan0: -<ts> I `` and the preallocate
# trace ``ggml_vulkan memory: ggml_vk_preallocate_buffers(x_size: <ts> I
# ``). Law: the marker must be bare, preceded by the plain common-log
# prefix, or wrapped by exactly one of the observed banner shapes;
# anything else fails closed. A banner shape is only admitted when it
# ends with the common-log prefix, so arbitrary banner text can never
# carry a marker.
_BANNER_END = re.compile(r"[IWEC] $")
_BANNERS = (
    "ggml_vulkan memory: ",
    "ggml_vulkan memory: ggml_vk_preallocate_buffers(x_size: ",
)


def _valid_prefix(prefix: str) -> bool:
    if prefix == "":
        return True
    if LOG_PREFIX_PLAIN.fullmatch(prefix):
        return True
    if not _BANNER_END.search(prefix):
        return False
    for banner in _BANNERS:
        if not prefix.startswith(banner):
            continue
        rest = prefix[len(banner):]
        # the banner may carry a site tag (e.g. ``Vulkan0: ``) and/or a
        # leading ``-``; exactly one common-log prefix must remain
        rest = re.sub(r"^[A-Za-z0-9]+: -?", "", rest)
        if LOG_PREFIX_PLAIN.fullmatch(rest):
            return True
    return False
POS = r"([1-9][0-9]*)"
NONNEG = r"(0|[1-9][0-9]*)"
GRAPH_BEGIN = re.compile(re.escape(PREFIX) + r"graph\|id=" + POS + r"\|phase=begin")
GRAPH_END = re.compile(re.escape(PREFIX) + r"graph\|id=" + POS + r"\|phase=end\|compute_submits=" + NONNEG)
SUBMIT = re.compile(re.escape(PREFIX) + r"submit\|graph=" + POS + r"\|id=" + POS + r"\|phase=submit\|path=(serialized|normal)")
WAIT = re.compile(re.escape(PREFIX) + r"submit\|graph=" + POS + r"\|id=" + POS + r"\|phase=wait\|path=serialized\|wait=success")
MEMORY = re.compile(re.escape(PREFIX) + r"memory\|role=backend\|buffer=" + POS + r"\|branch=(prefer_host|uma|disable_host_visible|default)\|type=" + NONNEG + r"\|flags=0x([1-9a-f][0-9a-f]*)")
RETIRE = re.compile(re.escape(PREFIX) + r"memory\|role=backend\|event=retire\|buffer=" + POS)
TENSOR = re.compile(re.escape(PREFIX) + r"tensor\|name=output\.weight\|buffer=" + POS + r"\|offset=" + NONNEG + r"\|bytes=" + POS + r"\|allocation_size=" + POS)
STAGING = re.compile(re.escape(PREFIX) + r"staging\|owner=(device|context)\|event=(create|retire)\|buffer=" + POS)
EXPECTED = {"BASE": "normal", "A1": "serialized", "A4": "prefer_host", "A5": "disable_host_visible"}


class ObservationError(ValueError):
    """Missing, ambiguous, or source-incompatible prospective observation."""


def parse_unit(log: str, *, arm: str, source_tree: str) -> dict:
    """Validate whole-line producer events; neither generic text nor staging proves H2/H3."""
    accepted_trees = {t for t in (INSTRUMENTED_TREE, INSTRUMENTED262_TREE) if t}
    if not accepted_trees or source_tree not in accepted_trees:
        raise ObservationError("instrumented source identity required")
    if arm not in EXPECTED or not isinstance(log, str):
        raise ObservationError("unknown arm or malformed log")
    limit = (1 << 64) - 1
    allocations: dict[int, dict] = {}
    retired: set[int] = set()
    target_id: int | None = None
    staging: dict[int, str] = {}
    seen_staging: set[int] = set()
    graphs: list[int] = []
    seen_graphs: set[int] = set()
    seen_submits: set[int] = set()
    last_submit_id: int | None = None
    active_graph: int | None = None
    graph_submits = 0
    pending: set[int] = set()
    paths: set[str] = set()
    for raw_line in log.splitlines():
        if "ggml_vk_i260:" not in raw_line:
            continue
        line = raw_line
        if not line.startswith(PREFIX):
            index = line.find(PREFIX)
            if index < 0 or not _valid_prefix(line[:index]):
                raise ObservationError("copied or unknown instrumented marker")
            line = line[index:]
        if not line.startswith(PREFIX):
            raise ObservationError("copied or unknown instrumented marker")
        if match := GRAPH_BEGIN.fullmatch(line):
            ident = int(match.group(1))
            if ident > limit or ident in seen_graphs or active_graph is not None or (seen_graphs and ident <= max(seen_graphs)):
                raise ObservationError("duplicate or nested graph begin")
            seen_graphs.add(ident)
            active_graph = ident
            graph_submits = 0
            pending.clear()
            continue
        if match := GRAPH_END.fullmatch(line):
            ident, count = map(int, match.groups())
            if ident != active_graph or count != graph_submits or pending:
                raise ObservationError("graph end/count/wait mismatch")
            graphs.append(ident)
            active_graph = None
            continue
        if match := SUBMIT.fullmatch(line):
            graph_id, submit_id, path = match.groups()
            graph_id, submit_id = int(graph_id), int(submit_id)
            if (graph_id != active_graph or submit_id > limit or submit_id in seen_submits
                    or (last_submit_id is not None and submit_id <= last_submit_id)
                    or (path == "serialized" and pending)):
                raise ObservationError("unscoped, duplicate or non-monotonic submission")
            seen_submits.add(submit_id)
            last_submit_id = submit_id
            graph_submits += 1
            paths.add(path)
            if path == "serialized":
                pending.add(submit_id)
            continue
        if match := WAIT.fullmatch(line):
            graph_id, submit_id = map(int, match.groups())
            if graph_id != active_graph or submit_id not in pending:
                raise ObservationError("wait lacks matching preceding serialized submit")
            pending.remove(submit_id)
            continue
        if match := MEMORY.fullmatch(line):
            ident, branch, memory_type, flags_hex = match.groups()
            ident_int, flags = int(ident), int(flags_hex, 16)
            if (ident_int > limit or ident_int in allocations or ident_int in seen_staging
                    or int(memory_type) >= 32 or flags > 0xffffffff):
                raise ObservationError("invalid or duplicate allocation")
            allocations[ident_int] = {"buffer": ident_int, "branch": branch,
                                      "type": int(memory_type), "flags": flags}
            continue
        if match := RETIRE.fullmatch(line):
            ident = int(match.group(1))
            if ident not in allocations or ident in retired:
                raise ObservationError("backend retire without live allocation")
            retired.add(ident)
            continue
        if match := TENSOR.fullmatch(line):
            ident, offset, size, allocation_size = map(int, match.groups())
            if (target_id is not None or ident not in allocations or ident in retired
                    or max(ident, offset, size, allocation_size) > limit
                    or offset > allocation_size or size > allocation_size - offset):
                raise ObservationError("target missing live backend allocation or valid span")
            target_id = ident
            allocations[ident]["offset"] = offset
            allocations[ident]["bytes"] = size
            allocations[ident]["allocation_size"] = allocation_size
            continue
        if match := STAGING.fullmatch(line):
            owner, event, ident = match.groups()
            ident_int = int(ident)
            if ident_int > limit or ident_int in allocations:
                raise ObservationError("staging masquerades as backend buffer")
            if event == "create":
                if ident_int in seen_staging:
                    raise ObservationError("reused staging identity")
                staging[ident_int] = owner
                seen_staging.add(ident_int)
            elif staging.get(ident_int) != owner:
                raise ObservationError("staging retire before create or wrong owner")
            else:
                del staging[ident_int]
            continue
        raise ObservationError("unknown or malformed instrumented marker")
    if active_graph is not None:
        raise ObservationError("unterminated graph")
    if len(paths) > 1 or (paths and paths != ({"serialized"} if arm == "A1" else {"normal"})):
        raise ObservationError("contradictory submission paths")
    if arm == "A1":
        if not seen_submits or paths != {"serialized"}:
            raise ObservationError("serialized path not consistently recorded")
        return {"submission": "serialized", "graphs": graphs}
    if arm == "BASE" and seen_submits and target_id is None:
        return {"submission": "normal", "graphs": graphs}
    if target_id is not None:
        target = allocations[target_id]
        expected = EXPECTED[arm] if arm != "BASE" else "default"
        if target["branch"] != expected:
            raise ObservationError("selected target branch differs from frozen control")
        return {"target": target, "staging_active": dict(staging),
                "submission": "normal" if seen_submits else None, "graphs": graphs}
    raise ObservationError("target output.weight allocation/binding absent")


def memory_choice_changed(baseline: dict, intervention: dict) -> bool:
    """A branch difference alone or eDeviceLocal in both paths proves no choice.

    A choice contrast means the target output.weight selected a different
    memory type or set of property flags; the backend/staging ID is NOT a
    type difference. This is a necessary, not sufficient, mechanism condition.
    """
    base, target = baseline["target"], intervention["target"]
    if base["branch"] == target["branch"]:
        return False
    return (base["type"], base["flags"]) != (target["type"], target["flags"])


def prospective_closure() -> dict:
    """Prospective source capability, not a result or execution authorization.

    H3 capability is conditional on a future verified model-buffer choice
    contrast. H5 has no bounded one-factor discriminator for the whole frozen
    hypothesis class, so closure remains impossible and no arms are required.
    """
    return {"source_identity": INSTRUMENTED_TREE,
            "observation_capable_arms": ["A1", "A4", "A5"],
            "terminal_capable_prospective_arms": ["A1"],
            "conditional_capability": {"A4": "target memory type/flags differ from baseline",
                                       "A5": "target memory type/flags differ from baseline"},
            "coverage_gaps": ["H3", "H5"], "closure_possible": False,
            "required_arms": [], "h5_blocker": "H5_DISCRIMINATOR_NOT_BOUNDED"}
