"""Issue #262 H5 route-marker grammar, dispatch binding, and eligibility."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import issue262_h5 as H

P = "ggml_vk_i262:v1|"

# Real observed geometry (first real #262 baseline unit): output.weight is
# [2560, 248320] q4_K; vector route 2560x1 f32 -> 248320x1 f32.
W = "2560x248320"
VTYPES = "q4_K*f32->f32"


def route(rid=1, graph=1, node="result_output", side=0, kind="mat-vec",
          pipe="mul_mat_vec_q4_k_f32_f32", family="mmv", quant_y=0,
          split_k=0, b64=0,
          dims=f"{W}:2560x1->248320x1",
          types=VTYPES, prefix=""):
    return (prefix + P + f"route|id={rid}|graph={graph}|weight=output.weight"
            f"|node={node}|side={side}|route={kind}|pipe={pipe}"
            f"|family={family}|quant_y={quant_y}|split_k={split_k}"
            f"|64b={b64}|dims={dims}|types={types}\n")


def mat_route(rid=2, graph=2, pipe="matmul_q4_k_f16", family="coopmat2",
              quant_y=0, split_k=1, dims=None):
    return route(rid=rid, graph=graph, kind="mat-mat", pipe=pipe,
                 family=family, quant_y=quant_y, split_k=split_k,
                 dims=dims or f"{W}:2560x3072->248320x3072",
                 types="q4_K*f16->f32")


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
        self.assertEqual(r["dims"]["src0"], (2560, 248320))
        self.assertEqual(r["dims"]["dst"], (248320, 1))
        self.assertEqual(r["types"], ["q4_K", "f32", "f32"])

    def test_real_log_prefix_is_accepted_and_anything_else_fails(self):
        prefixed = route(prefix="0.05.069.746 I ")
        routes = H.parse_routes(prefixed)
        self.assertEqual(routes[0]["id"], 1)
        for bad_prefix in ("garbage ", "0.05.069 I ", "x 0.05 I "):
            with self.subTest(bad_prefix=bad_prefix):
                with self.assertRaises(H.RouteError):
                    H.parse_routes(route(prefix=bad_prefix))

    def test_generic_text_and_old_markers_are_ignored(self):
        self.assertEqual(H.parse_routes("ggml_vulkan: init\n"), [])
        self.assertEqual(H.parse_routes(
            "0.03.976 I ggml_vk_i260:v1|graph|id=1|phase=begin\n"), [])

    def test_malformed_or_forged_markers_fail_closed(self):
        for bad in (
            route().replace("route|id=1", "route|id=0"),
            route().replace("weight=output.weight", "weight=other.weight"),
            route().replace("route=mat-vec", "route=mat-batch"),
            route().replace("family=mmv", "family=cuda"),
            route().replace("split_k=0", "split_k=-1"),
            route().replace("64b=0", "64b=2"),
            route().replace(f"dims={W}", "dims=0x248320"),
            route() + route(rid=1),                      # duplicate id
            route(rid=5) + route(rid=5, graph=2),        # non-monotonic
            route().replace("id=1", "id=18446744073709551616"),
            P + "route|id=1|partial\n",
            "garbage ggml_vk_i262: line\n",
            route().replace("v1|", "v2|"),
            route().replace("types=q4_K*f32->f32", "types=q4_K*f32->"),
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
            route(dims="123x456:2560x1->248320x1"),          # wrong weight
            route(dims=f"{W}:2x1->248320x2"),                # wrong batch
            route(types="f16*f32->f32"),                       # wrong weight type
            route(types="q4_K*f32->f16"),                      # wrong out type
            route(side=1, dims=f"2560x1:{W}->248320x1"),
            route(side=0) + route(rid=2, side=1, graph=2,
                                  dims=f"2560x1:{W}->248320x1"),
        ):
            with self.subTest(bad=bad[:80]):
                with self.assertRaises(H.RouteError):
                    self.observe(bad)

    def test_mat_mat_requires_frozen_prefill_geometry(self):
        obs = self.observe(mat_route())
        self.assertEqual(obs["routes"]["mat-mat"]["family"], "coopmat2")
        with self.assertRaises(H.RouteError):
            self.observe(mat_route(dims=f"{W}:2560x999->248320x999"))

    def test_capability_enumeration_alone_cannot_masquerade(self):
        # A device-capability banner without a bound route marker is not H5.
        log = ("ggml_vulkan: NV_cooperative_matrix2 available\n"
               "0.03 I ggml_vk_i260:v1|memory|role=backend|buffer=1|branch=default"
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
        # Real mixed case: mat-vec mmv + mat-mat coopmat2 in one unit.
        log = route() + mat_route()
        ok, why = self.eligible(log)
        self.assertFalse(ok)
        self.assertIn("mixed", why)

    def test_real_baseline_observation_is_not_eligible(self):
        # The actual first-unit observation shape: 10 identical mat-vec/mmvs.
        log = "".join(route(rid=i, graph=60 + i) for i in range(1, 11))
        obs = self.observe(log)
        self.assertEqual(obs["marker_count"], 10)
        ok, why = self.eligible(log)
        self.assertFalse(ok)
        self.assertIn("vector", why)


class CandidateTransitionTests(unittest.TestCase):
    def test_changed_path_transition(self):
        def obs(pipe, family):
            return {"routes": {"mat-mat": {
                "pipe": pipe, "family": family, "quant_y": False,
                "split_k": 1, "indexing64": False,
                "dims": {"src0": (2560, 248320), "src1": (2560, 3072),
                         "dst": (248320, 3072)},
                "types": ["q4_K", "f16", "f32"]}}}
        t = H.candidate_transition(obs("matmul_q4_k_f16", "coopmat2"),
                                   obs("matmul_q4_k_f32", "coopmat1"))
        self.assertTrue(t["mat-mat"]["changed"])
        self.assertEqual(t["mat-mat"]["family"], ["coopmat2", "coopmat1"])

    def test_shape_change_fails_closed(self):
        base = {"routes": {"mat-mat": {
            "pipe": "p", "family": "coopmat2", "quant_y": False,
            "split_k": 1, "indexing64": False,
            "dims": {"src0": (2560, 248320), "src1": (2560, 3072),
                     "dst": (248320, 3072)},
            "types": ["q4_K", "f16", "f32"]}}}
        cand = {"routes": {"mat-mat": dict(base["routes"]["mat-mat"],
                                           dims={"src0": (1, 1),
                                                 "src1": (2560, 3072),
                                                 "dst": (248320, 3072)})}}
        with self.assertRaises(H.RouteError):
            H.candidate_transition(base, cand)

    def test_unchanged_path_is_reported_not_minted(self):
        base = {"routes": {"mat-mat": {
            "pipe": "p", "family": "coopmat2", "quant_y": False,
            "split_k": 1, "indexing64": False,
            "dims": {"src0": (2560, 248320), "src1": (2560, 3072),
                     "dst": (248320, 3072)},
            "types": ["q4_K", "f16", "f32"]}}}
        t = H.candidate_transition(base, {"routes": dict(base["routes"])})
        self.assertFalse(t["mat-mat"]["changed"])


if __name__ == "__main__":
    unittest.main()
