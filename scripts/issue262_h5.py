#!/usr/bin/env python3
"""#262 H5 route-marker grammar and coopmat2 eligibility (repository-side).

Parses the exact-format ``ggml_vk_i262:v1|route|...`` markers emitted by the
#262 instrumented comparator at the ACTUAL dispatch/selection sites:

* mat-vec route: emitted in ``ggml_vk_mul_mat_vec_q_f16`` after the final
  ``dmmv`` pipeline resolution (post 64b-variant selection);
* mat-mat route: emitted in ``ggml_vk_mul_mat_q_f16`` after the pipeline
  guess and the split-K decision are final.

The family classification originates at pipeline creation
(``ggml_vk_load_shaders`` records which configuration branch — coopmat2,
coopmat1, or the scalar/BF16-fallback — created each named matmul pipeline),
and the vector path classifies mmv vs mmvq-idp by the actual ``quantize_y``
selection. Device-level NV_coopmat2 availability alone can NEVER satisfy
H5: parsing requires the retained marker bound to the frozen
``output.weight`` weight identity with exact node shapes/types.

No physical result is established by parsing; a future producer binds exact
source tree and binary bytes before using these laws.
"""
from __future__ import annotations

import re

PREFIX = "ggml_vk_i262:v1|"
POS = r"([1-9][0-9]*)"
NONNEG = r"(0|[1-9][0-9]*)"
WORD = r"[A-Za-z0-9._+-]+"

ROUTE = re.compile(
    re.escape(PREFIX) + r"route\|id=" + POS + r"\|graph=" + NONNEG
    + r"\|weight=output\.weight\|node=(" + WORD + r")\|side=([01])"
    r"\|route=(mat-vec|mat-mat)\|pipe=(" + WORD + r")"
    r"\|family=(mmv|mmvq-idp|coopmat2|coopmat1|scalar-bf16-fallback|unclassified)"
    r"\|quant_y=([01])\|split_k=" + NONNEG + r"\|64b=([01])"
    r"\|dims=" + POS + r"x" + POS + r":" + POS + r"x" + POS
    + r"->" + POS + r"x" + POS
    + r"\|types=(" + WORD + r")\*(" + WORD + r")->(" + WORD + r")")

# Weight-tensor shape of the frozen output projection (Qwen3.8-Flash-Next
# UD-IQ1_S): output.weight is [n_vocab, n_embd] = 248320 x 2048, IQ1_S.
WEIGHT_NE = (248320, 2048)
WEIGHT_TYPE = "IQ1_S"
# Vector route: activation [1, 2048] F32 -> logits [1, 248320] F32.
VEC_IN_NE = (1, 2048)
VEC_OUT_NE = (1, 248320)
# Mat-mat route (prompt prefill): [3072, 2048] -> [3072, 248320].
MAT_IN_NE = (3072, 2048)
MAT_OUT_NE = (3072, 248320)
LIMIT = (1 << 64) - 1


class RouteError(ValueError):
    """Missing, malformed, or non-H5 route observation."""


def parse_routes(log: str) -> list[dict]:
    """Parse every retained route marker line; fail closed on any malformed
    marker, non-positive identity, or impossible value."""
    if not isinstance(log, str):
        raise RouteError("log must be a string")
    routes = []
    seen: set[int] = set()
    last_id = 0
    for line in log.splitlines():
        if "ggml_vk_i262:" not in line:
            continue
        if not line.startswith(PREFIX):
            raise RouteError("copied or unknown i262 marker")
        match = ROUTE.fullmatch(line)
        if not match:
            raise RouteError("unknown or malformed i262 route marker")
        (rid, graph_id, node, side, route, pipe, family, quant_y,
         split_k, b64, ne00, ne01, ne10, ne11, ne20, ne21,
         t0, t1, t2) = match.groups()
        rid_i = int(rid)
        if rid_i > LIMIT or rid_i in seen or rid_i <= last_id:
            raise RouteError("duplicate or non-monotonic route identity")
        seen.add(rid_i)
        last_id = rid_i
        dims = tuple(int(x) for x in (ne00, ne01, ne10, ne11, ne20, ne21))
        if any(d > LIMIT for d in dims):
            raise RouteError("dimension overflow")
        routes.append({
            "id": rid_i, "graph": int(graph_id), "node": node,
            "side": int(side), "route": route, "pipe": pipe,
            "family": family, "quant_y": quant_y == "1",
            "split_k": int(split_k), "indexing64": b64 == "1",
            "dims": {"src0": dims[0:2], "src1": dims[2:4], "dst": dims[4:6]},
            "types": [t0, t1, t2], "line": line,
        })
    return routes


def output_projection_routes(routes: list[dict]) -> dict:
    """Derive the frozen output-projection observation from retained routes.

    Requires exactly one route family per route kind actually retained, with
    the weight bound on a consistent side and the exact frozen shapes/types.
    Returns the H5 observation dict; raises RouteError fail-closed.
    """
    if not routes:
        raise RouteError("no route markers retained")
    sides = {r["side"] for r in routes}
    if len(sides) != 1:
        raise RouteError("output.weight bound to inconsistent operand sides")
    side = sides.pop()
    for r in routes:
        w_dims = r["dims"]["src0"] if side == 0 else r["dims"]["src1"]
        if w_dims != WEIGHT_NE:
            raise RouteError(f"weight shape {w_dims} is not the frozen projection")
        if r["types"][side] != WEIGHT_TYPE:
            raise RouteError(f"weight type {r['types'][side]} is not {WEIGHT_TYPE}")
        if r["route"] == "mat-vec":
            expect_in, expect_out = VEC_IN_NE, VEC_OUT_NE
        else:
            expect_in, expect_out = MAT_IN_NE, MAT_OUT_NE
        in_dims = r["dims"]["src1"] if side == 0 else r["dims"]["src0"]
        if in_dims != expect_in or r["dims"]["dst"] != expect_out:
            raise RouteError(
                f"{r['route']} shapes {in_dims}->{r['dims']['dst']} are not "
                f"the frozen geometry {expect_in}->{expect_out}")
        if r["types"][2] != "F32":
            raise RouteError("projection output type is not F32")
    per_route = {r["route"]: r for r in routes}
    if len(per_route) != len(routes):
        # Same route kind twice is physical (prefill + decode graphs); fold
        # into a per-kind list but require identical classification.
        by_kind: dict[str, list[dict]] = {}
        for r in routes:
            by_kind.setdefault(r["route"], []).append(r)
        for kind, group in by_kind.items():
            keys = {(
                g["pipe"], g["family"], g["quant_y"], g["split_k"],
                g["indexing64"], tuple(map(tuple, g["dims"].values())),
                tuple(g["types"])) for g in group}
            if len(keys) != 1:
                raise RouteError(
                    f"conflicting {kind} classifications for one unit")
        per_route = {kind: group[0] for kind, group in by_kind.items()}
    return {
        "side": side,
        "routes": {kind: {
            "route": g["route"], "pipe": g["pipe"], "family": g["family"],
            "quant_y": g["quant_y"], "split_k": g["split_k"],
            "indexing64": g["indexing64"],
            "dims": g["dims"], "types": g["types"],
        } for kind, g in per_route.items()},
        "marker_count": len(routes),
    }


def coopmat2_candidate_eligible(observation: dict) -> tuple[bool, str]:
    """Stage-3 predicate: is GGML_VK_DISABLE_COOPMAT2=1 a live one-factor
    control for the OBSERVED output-projection path?

    Eligible iff EVERY retained route kind's dispatched pipeline belongs to
    the coopmat2 creation family (a path the switch actually selects between).
    A vector/mmvq path or a coopmat1/scalar pipeline is unaffected by the
    switch: the dead control must not run.
    """
    routes = observation.get("routes")
    if not isinstance(routes, dict) or not routes:
        return False, "no retained output-projection routes"
    families = {r["family"] for r in routes.values()}
    if families <= {"mmv", "mmvq-idp"}:
        return False, ("output projection dispatched on the vector path "
                       f"({sorted(families)}); coopmat2 switch does not "
                       "select this path")
    if "coopmat2" not in families:
        return False, ("output projection pipeline created outside the "
                       f"coopmat2 configuration branch ({sorted(families)})")
    if families != {"coopmat2"}:
        return False, ("mixed creation families across retained routes "
                       f"({sorted(families)}); not a single-factor control")
    return True, ("output projection dispatched a coopmat2-family pipeline; "
                  "GGML_VK_DISABLE_COOPMAT2=1 is a live one-factor control")


def candidate_transition(baseline: dict, candidate: dict) -> dict:
    """Paired H5_CANDIDATE transition: same node shapes/types, changed
    route/pipeline/shader family. Fail closed when the intervention did not
    change the selected path (the control then proves nothing for H5)."""
    base_routes = baseline["routes"]
    cand_routes = candidate["routes"]
    if set(base_routes) != set(cand_routes):
        raise RouteError("candidate retained a different route-kind set")
    transitions = {}
    for kind in base_routes:
        b, c = base_routes[kind], cand_routes[kind]
        if (b["dims"] != c["dims"] or b["types"] != c["types"]):
            raise RouteError(
                f"{kind} node/shape/type not retained exactly under the "
                "candidate")
        transitions[kind] = {
            "pipe": [b["pipe"], c["pipe"]],
            "family": [b["family"], c["family"]],
            "changed": (b["pipe"], b["family"]) != (c["pipe"], c["family"]),
        }
    return transitions
