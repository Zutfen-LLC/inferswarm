#!/usr/bin/env python3
"""CPU-only #264 validator: two actual, i262-bound output MMV dispatches."""
from __future__ import annotations

import re

PREFIX = "ggml_vk_i264:v1|mmv|"
SHAPE = r"2560x248320:2560x1->248320x1"
TYPES = r"q4_K*f32->f32"
I262 = re.compile(
    r"ggml_vk_i262:v1\|route\|id=([1-9][0-9]*)\|graph=([1-9][0-9]*)"
    r"\|weight=output\.weight\|node=([^|]+)\|side=0\|route=mat-vec"
    r"\|pipe=mul_mat_vec_q4_k_f32_f32\|family=mmv\|quant_y=0"
    r"\|split_k=0\|64b=0\|dims=2560x248320:2560x1->248320x1"
    r"\|types=q4_K\*f32->f32")
I264 = re.compile(
    r"ggml_vk_i264:v1\|mmv\|id=([1-9][0-9]*)\|node=([^|]+)"
    r"\|weight=output\.weight\|state=(base|large)"
    r"\|route=mat-vec\|pipe=mul_mat_vec_q4_k_f32_f32"
    r"\|wg=(subgroup|large)\|reduction=(subgroup|hybrid|shmem)"
    r"\|local=([1-9][0-9]*)x1x1\|dims=2560x248320:2560x1->248320x1"
    r"\|types=q4_K\*f32->f32\|quant_y=0\|split_k=0\|64b=0")


class RouteError(ValueError):
    """Incomplete or inconsistent dispatch evidence."""


def select_variant(value: str | None) -> str:
    """Absence is base; reject all other spellings and states."""
    if value is None:
        return "base"
    if value not in ("base", "large"):
        raise RouteError("GGML_VK_I264_MMV must be exactly 'base' or 'large'")
    return value


def parse_pair(log: str) -> dict:
    """Pair adjacent exact route+variant events, then prove BASE→LARGE."""
    if not isinstance(log, str):
        raise RouteError("log must be text")
    events = []
    pending = None
    for line in log.splitlines():
        if "ggml_vk_i262:v1|route|" in line:
            if pending is not None:
                raise RouteError("unpaired i262 route")
            match = I262.search(line)
            if match is None or match.end() != len(line):
                # Other i262 output routes cannot be evidence for this exact pair.
                if "weight=output.weight" in line:
                    raise RouteError("wrong output route")
                continue
            pending = (int(match[1]), match[2], match[3])
        elif PREFIX in line:
            match = I264.search(line)
            if match is None or match.end() != len(line) or pending is None:
                raise RouteError("unpaired or malformed i264 variant")
            rid, graph, node = pending
            if int(match[1]) != rid or match[2] != node:
                raise RouteError("i262/i264 event or node mismatch")
            if events and rid < events[-1][0] and rid != 1:
                raise RouteError("out-of-order event id without process reset")
            events.append((rid, graph, match[3], match[4], match[5], int(match[6])))
            pending = None
    if pending is not None or len(events) != 2:
        raise RouteError("expected exactly two paired output MMV events")
    if [(e[2], e[3], e[4], e[5]) for e in events] != [
        ("base", "subgroup", "subgroup", 32),
        ("large", "large", "hybrid", 128),
    ]:
        raise RouteError("actual subgroup→large pipeline transition not proven")
    return {"states": [e[2] for e in events], "variants": [e[3] for e in events],
            "reductions": [e[4] for e in events],
            "local_sizes": [f"{e[5]}x1x1" for e in events],
            "event_ids": [e[0] for e in events]}
