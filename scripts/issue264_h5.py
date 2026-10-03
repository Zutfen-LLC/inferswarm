#!/usr/bin/env python3
"""CPU-only #264 verifier for per-process, actual output MMV dispatches.

Pass one fresh-process server log to parse_unit for each arm. Never concatenate
process logs: an event-ID reset is valid only across separate calls.
"""
from __future__ import annotations

import re

from issue262_h5 import LOG_PREFIX

I262_PREFIX = "ggml_vk_i262"
I264_PREFIX = "ggml_vk_i264"
NODE = r"([A-Za-z0-9._+-]+)"
DIMS = "2560x248320:2560x1->248320x1"
TYPES = "q4_K*f32->f32"
PIPE = "mul_mat_vec_q4_k_f32_f32"
LIMIT = (1 << 64) - 1
I262 = re.compile(
    r"ggml_vk_i262:v1\|route\|id=([1-9][0-9]*)\|graph=([1-9][0-9]*)"
    r"\|weight=output\.weight\|node=" + NODE + r"\|side=0\|route=mat-vec"
    r"\|pipe=mul_mat_vec_q4_k_f32_f32\|family=mmv\|quant_y=0"
    r"\|split_k=0\|64b=0\|dims=2560x248320:2560x1->248320x1"
    r"\|types=q4_K\*f32->f32")
I264 = re.compile(
    r"ggml_vk_i264:v1\|mmv\|id=([1-9][0-9]*)\|node=" + NODE
    + r"\|weight=output\.weight\|state=(base|large)"
    r"\|route=mat-vec\|pipe=mul_mat_vec_q4_k_f32_f32"
    r"\|wg=(subgroup|large)\|reduction=(subgroup|hybrid|shmem)"
    r"\|local=([1-9][0-9]*)x1x1\|dims=2560x248320:2560x1->248320x1"
    r"\|types=q4_K\*f32->f32\|quant_y=0\|split_k=0\|64b=0")
VARIANTS = {"base": ("subgroup", "subgroup", 32),
            "large": ("large", "hybrid", 128)}


class RouteError(ValueError):
    """Incomplete or inconsistent dispatch evidence."""


def select_variant(value: str | None) -> str:
    """Absence is base; reject all other spellings and states."""
    if value is None:
        return "base"
    if value not in VARIANTS:
        raise RouteError("GGML_VK_I264_MMV must be exactly 'base' or 'large'")
    return value


def _marker(raw: str, prefix: str, grammar: re.Pattern) -> re.Match:
    """Accept only a bare marker or the actual ggml common-log envelope."""
    index = raw.find(prefix)
    if index < 0 or (index and not LOG_PREFIX.fullmatch(raw[:index])):
        raise RouteError("copied or unknown marker prefix")
    match = grammar.fullmatch(raw[index:])
    if match is None:
        raise RouteError("unknown or malformed dispatch marker")
    return match


def parse_unit(log: str, *, state: str) -> dict:
    """Validate all i262/i264 output dispatches in ONE fresh-process log.

    Every route requires its matching variant before the next marker. Ordinary
    server lines may intervene; marker identity, node and actual variant may not.
    The returned summary contains only observations, not an authorization.
    """
    if not isinstance(log, str):
        raise RouteError("log must be text")
    if state not in VARIANTS:
        raise RouteError("expected state must be base or large")
    ids: list[int] = []
    graphs: list[int] = []
    node = None
    pending = None
    for raw in log.splitlines():
        has262 = I262_PREFIX in raw
        has264 = I264_PREFIX in raw
        if not has262 and not has264:
            continue
        if has262 and has264:
            raise RouteError("multiple markers in one line")
        if has262:
            match = _marker(raw, I262_PREFIX, I262)
            rid, graph, route_node = int(match[1]), int(match[2]), match[3]
            if pending is not None or rid > LIMIT or graph > LIMIT or (ids and rid <= ids[-1]):
                raise RouteError("unpaired, duplicate or non-monotonic route identity")
            if node is not None and node != route_node:
                raise RouteError("output node changed within unit")
            pending = rid, graph, route_node
        else:
            match = _marker(raw, I264_PREFIX, I264)
            if pending is None:
                raise RouteError("variant has no actual route")
            rid, graph, route_node = pending
            if int(match[1]) != rid or match[2] != route_node:
                raise RouteError("variant id/node does not match dispatch")
            if match[3] != state or (match[4], match[5], int(match[6])) != VARIANTS[state]:
                raise RouteError("actual selected workgroup/reduction does not match arm")
            node = route_node
            ids.append(rid)
            graphs.append(graph)
            pending = None
    if pending is not None or not ids:
        raise RouteError("missing complete output MMV dispatch evidence")
    if len(ids) != 10:
        raise RouteError("frozen output MMV population requires exactly 10 events")
    wg, reduction, local = VARIANTS[state]
    return {"state": state, "node": node, "dims": DIMS, "types": TYPES,
            "route": "mat-vec", "pipe": PIPE, "family": "mmv",
            "quant_y": 0, "split_k": 0, "indexing64": 0,
            "variant": wg, "reduction": reduction, "local_size": f"{local}x1x1",
            "event_ids": ids, "graph_ids": graphs, "marker_count": len(ids)}


def candidate_transition(base: dict, candidate: dict) -> dict:
    """Prove equal frozen dispatch identity and actual subgroup→large change."""
    keys = ("node", "dims", "types", "route", "pipe", "family",
            "quant_y", "split_k", "indexing64")
    if any(base.get(key) != candidate.get(key) for key in keys):
        raise RouteError("candidate changes frozen output projection identity")
    for unit, state in ((base, "base"), (candidate, "large")):
        wg, reduction, local = VARIANTS[state]
        if (unit.get("state") != state or unit.get("variant") != wg
                or unit.get("reduction") != reduction
                or unit.get("local_size") != f"{local}x1x1"
                or not unit.get("event_ids") or unit.get("marker_count") != len(unit["event_ids"])):
            raise RouteError("actual subgroup-to-large transition not proven")
    return {"node": base["node"], "variants": [base["variant"], candidate["variant"]],
            "reductions": [base["reduction"], candidate["reduction"]],
            "local_sizes": [base["local_size"], candidate["local_size"]],
            "marker_counts": [base["marker_count"], candidate["marker_count"]]}
