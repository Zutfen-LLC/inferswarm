"""Issue #262 H5 route-marker grammar, dispatch binding, and eligibility."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import issue262_h5 as H

P = "ggml_vk_i262:v1|"


def route(rid=1, graph=1, node="result.output", side=0, kind="mat-vec",
          pipe="mul_mat_vec_iq1_s_f32_f32", family="mmv", quant_y=0,
          split_k=0, b64=0,
          dims="248320x2048:1x2048->1x248320",
          types="IQ1_S*F32->F32"):
    return (P + f"route|id={rid}|graph={graph}|weight=output.weight"
            f"|node={node}|side={side}|route={kind}|pipe={pipe}"
            f"|family={family}|quant_y={quant_y}|split_k={split_k}"
            f"|64b={b64}|dims={dims}|types={types}\n")


def mat_route(rid=2, graph=2, pipe="matmul_iq1_s_f16", family="coopmat2",
              quant_y=0, split_k=1, dims=None):
    return route(rid=rid, graph=graph, kind="mat-mat", pipe=pipe,
                 family=family, quant_y=quant_y, split_k=split_k,
                 dims=dims or "248320x2048:3072x2048->3072x248320")


class RouteGrammarTests(unittest.TestCase):
    def test_exact_marker_parses_with_all_fields(self):
        routes = H.parse_routes(route(rid=7, graph=3))
        self.assertEqual(len(routes), 1)
        r = routes[0]
        self.assertEqual(r["id"], 7)
        self.assertEqual(r["graph"], 3)
        self.assertEqual(r["route"], "mat-vec")
        self.assertEqual(r["family"], "mmv")
        self.assertFalse(r["quant_y"])
        self.assertEqual(r["split_k"], 0)
        self.assertEqual(r["dims"]["dst"], (1, 248320))
        self.assertEqual(r["types"], ["IQ1_S", "F32", "F32"])

    def test_generic_text_and_old_markers_are_ignored(self):
        self.assertEqual(H.parse_routes("ggml_vulkan: init\n"), [])
        self.assertEqual(H.parse_routes(
            "ggml_vk_i260:v1|graph|id=1|phase=begin\n"), [])

    def test_malformed_or_forged_markers_fail_closed(self):
        for bad in (
            route().replace("route|id=1", "route|id=0"),
            route().replace("weight=output.weight", "weight=other.weight"),
            route().replace("route=mat-vec", "route=mat-batch"),
            route().replace("family=mmv", "family=cuda"),
            route().replace("split_k=0", "split_k=-1"),
            route().replace("64b=0", "64b=2"),
            route().replace("dims=248320x2048", "dims=0x2048"),
            # (type forgeries are rejected at dispatch binding, not by the
            # token grammar — covered in DispatchBindingTests)
            route() + route(rid=1),                      # duplicate id
            route(rid=5) + route(rid=5, graph=2),        # non-monotonic
            route().replace("id=1", "id=18446744073709551616"),
            P + "route|id=1|partial\n",
            "garbage ggml_vk_i262: line\n",
            route().replace("v1|", "v2|"),
            route().replace("types=IQ1_S*F32->F32", "types=IQ1_S*F32->"),
        ):
            with self.subTest(bad=bad[:80]):
                with self.assertRaises(H.RouteError):
                    H.parse_routes(bad)

    def test_monotonic_gaps_are_valid(self):
        routes = H.parse_routes(route(rid=9) + route(rid=400, graph=2))
        self.assertEqual([r["id"] for r in routes], [9, 400])


class DispatchBindingTests(unittest.TestCase):
    def observe(self, log):
        return H.output_projection_routes(H.parse_routes(log))

    def test_wrong_node_shape_path_fails_closed(self):
        for bad in (
            route(dims="123x456:1x2048->1x248320"),          # wrong weight
            route(dims="248320x2048:2x2048->2x248320"),      # wrong batch
            route(types="F16*F32->F32"),                      # wrong weight type
            route(types="IQ1_S*F32->F16"),                    # wrong out type
            route(side=1, dims="1x2048:248320x2048->1x248320"),
            route(side=0) + route(rid=2, side=1, graph=2,
                                  dims="1x2048:248320x2048->1x248320"),
        ):
            with self.subTest(bad=bad[:80]):
                with self.assertRaises(H.RouteError):
                    self.observe(bad)

    def test_mat_mat_requires_frozen_prefill_geometry(self):
        obs = self.observe(mat_route())
        self.assertEqual(obs["routes"]["mat-mat"]["family"], "coopmat2")
        with self.assertRaises(H.RouteError):
            self.observe(mat_route(dims="248320x2048:999x2048->999x248320"))

    def test_capability_enumeration_alone_cannot_masquerade(self):
        # A device-capability banner without a bound route marker is not H5.
        log = ("ggml_vulkan: NV_cooperative_matrix2 available\n"
               "ggml_vk_i260:v1|memory|role=backend|buffer=1|branch=default"
               "|type=0|flags=0xf\n")
        with self.assertRaises(H.RouteError):
            self.observe(log)

    def test_same_kind_duplicate_routes_must_agree(self):
        twin = route() + route(rid=2, graph=4)
        obs = self.observe(twin)
        self.assertEqual(obs["marker_count"], 2)
        with self.assertRaises(H.RouteError):
            self.observe(route() + route(rid=2, graph=4,
                                         pipe="mul_mat_vec_other"))


class EligibilityTests(unittest.TestCase):
    def observe(self, log):
        return H.output_projection_routes(H.parse_routes(log))

    def eligible(self, log):
        return H.coopmat2_candidate_eligible(self.observe(log))

    def test_vector_path_is_not_coopmat2_eligible(self):
        ok, why = self.eligible(route())
        self.assertFalse(ok)
        self.assertIn("vector", why)

    def test_mmvq_idp_path_is_not_eligible(self):
        ok, _ = self.eligible(route(family="mmvq-idp", quant_y=1))
        self.assertFalse(ok)

    def test_coopmat2_pipeline_is_eligible(self):
        ok, why = self.eligible(mat_route())
        self.assertTrue(ok)
        self.assertIn("live one-factor", why)

    def test_coopmat1_or_scalar_pipeline_is_not_eligible(self):
        for family in ("coopmat1", "scalar-bf16-fallback", "unclassified"):
            with self.subTest(family=family):
                ok, _ = self.eligible(mat_route(family=family))
                self.assertFalse(ok)

    def test_mixed_families_are_not_eligible(self):
        # A mat-vec route classified coopmat2 (impossible: the vector path
        # classifies mmv/mmvq-idp by construction) next to a mat-mat
        # coopmat2 route still routes through the mixed-family refusal
        # only when the families actually differ; construct the real mixed
        # case: mat-vec mmv + mat-mat coopmat2 in one unit.
        log = route() + mat_route()
        ok, why = self.eligible(log)
        self.assertFalse(ok)
        self.assertIn("mixed", why)


class CandidateTransitionTests(unittest.TestCase):
    def test_changed_path_transition(self):
        def obs(pipe, family):
            return {"routes": {"mat-mat": {
                "pipe": pipe, "family": family, "quant_y": False,
                "split_k": 1, "indexing64": False,
                "dims": {"src0": [248320, 2048], "src1": [3072, 2048],
                         "dst": [3072, 248320]},
                "types": ["IQ1_S", "F16", "F32"]}}}
        t = H.candidate_transition(obs("matmul_iq1_s_f16", "coopmat2"),
                                   obs("matmul_iq1_s_f32", "coopmat1"))
        self.assertTrue(t["mat-mat"]["changed"])
        self.assertEqual(t["mat-mat"]["family"], ["coopmat2", "coopmat1"])

    def test_shape_change_fails_closed(self):
        base = {"routes": {"mat-mat": {
            "pipe": "p", "family": "coopmat2", "quant_y": False,
            "split_k": 1, "indexing64": False,
            "dims": {"src0": [248320, 2048], "src1": [3072, 2048],
                     "dst": [3072, 248320]},
            "types": ["IQ1_S", "F16", "F32"]}}}
        cand = {"routes": {"mat-mat": dict(base["routes"]["mat-mat"],
                                           dims={"src0": [1, 1],
                                                 "src1": [3072, 2048],
                                                 "dst": [3072, 248320]})}}
        with self.assertRaises(H.RouteError):
            H.candidate_transition(base, cand)

    def test_unchanged_path_is_reported_not_minted(self):
        base = {"routes": {"mat-mat": {
            "pipe": "p", "family": "coopmat2", "quant_y": False,
            "split_k": 1, "indexing64": False,
            "dims": {"src0": [248320, 2048], "src1": [3072, 2048],
                     "dst": [3072, 248320]},
            "types": ["IQ1_S", "F16", "F32"]}}}
        t = H.candidate_transition(base, {"routes": dict(base["routes"])})
        self.assertFalse(t["mat-mat"]["changed"])


if __name__ == "__main__":
    unittest.main()
