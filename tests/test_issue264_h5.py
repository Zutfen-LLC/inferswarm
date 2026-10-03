"""Issue #264 exact output.weight MMV selector and variant pairing tests."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import issue264_h5 as H

P = "ggml_vk_i264:v1|mmv|"
ROUTE = ("ggml_vk_i262:v1|route|id={id}|graph=1|weight=output.weight|node=result_output"
         "|side=0|route=mat-vec|pipe=mul_mat_vec_q4_k_f32_f32|family=mmv"
         "|quant_y=0|split_k=0|64b=0|dims=2560x248320:2560x1->248320x1"
         "|types=q4_K*f32->f32\n")
BASE = (P + "id=1|node=result_output|weight=output.weight|state=base"
        "|route=mat-vec|pipe=mul_mat_vec_q4_k_f32_f32|wg=subgroup"
        "|reduction=subgroup|local=32x1x1|dims=2560x248320:2560x1->248320x1"
        "|types=q4_K*f32->f32|quant_y=0|split_k=0|64b=0\n")
LARGE = BASE.replace("id=1", "id=2").replace("state=base", "state=large")\
    .replace("wg=subgroup", "wg=large").replace("reduction=subgroup", "reduction=hybrid")\
    .replace("local=32x1x1", "local=128x1x1")


class SelectorContractTests(unittest.TestCase):
    def test_default_and_two_explicit_states(self):
        self.assertEqual(H.select_variant(None), "base")
        self.assertEqual(H.select_variant("base"), "base")
        self.assertEqual(H.select_variant("large"), "large")

    def test_unknown_selector_fails_closed(self):
        for value in ("", "BASE", "subgroup", "large ", "other"):
            with self.subTest(value=value), self.assertRaises(H.RouteError):
                H.select_variant(value)


def paired(base=BASE, large=LARGE):
    return ROUTE.format(id=1) + base + ROUTE.format(id=2) + large


class MarkerPairTests(unittest.TestCase):
    def test_accepts_exact_actual_base_to_large_transition(self):
        pair = H.parse_pair(paired())
        self.assertEqual(pair["states"], ["base", "large"])
        self.assertEqual(pair["variants"], ["subgroup", "large"])
        self.assertEqual(pair["local_sizes"], ["32x1x1", "128x1x1"])

    def test_rejects_missing_duplicate_out_of_order_and_spoofed_variants(self):
        for log in (BASE, LARGE + BASE, paired(BASE, BASE),
                    paired(large=LARGE.replace("wg=large", "wg=subgroup")),
                    paired(large=LARGE.replace("local=128x1x1", "local=32x1x1")),
                    paired(large=LARGE.replace("node=result_output", "node=other")),
                    paired(large=LARGE.replace("dims=2560x248320", "dims=1x248320")),
                    paired(large=LARGE.replace("types=q4_K*f32->f32", "types=f16*f32->f32")),
                    paired(large=LARGE.replace("route=mat-vec", "route=mat-mat")),
                    ROUTE.format(id=1) + BASE + ROUTE.format(id=1) + BASE,
                    ROUTE.format(id=1) + BASE + LARGE + ROUTE.format(id=2)):
            with self.subTest(log=log[-100:]), self.assertRaises(H.RouteError):
                H.parse_pair(log)

    def test_log_prefix_and_separate_process_event_id_reset(self):
        second = LARGE.replace("id=2", "id=1")
        log = "ggml_vulkan: " + ROUTE.format(id=1) + "ggml_vulkan: " + BASE
        log += "ggml_vulkan: " + ROUTE.format(id=1) + "ggml_vulkan: " + second
        self.assertEqual(H.parse_pair(log)["event_ids"], [1, 1])

    def test_rejects_trailing_spoof_and_dead_variant(self):
        for log in (paired(large=LARGE.rstrip() + "|spoof=1\n"),
                    ROUTE.format(id=1) + BASE + ROUTE.format(id=2) +
                    "ggml_vk_i264:v1|mmv|id=2|state=large\n",
                    paired() + ROUTE.format(id=3) + LARGE.replace("id=2", "id=3")):
            with self.subTest(log=log[-100:]), self.assertRaises(H.RouteError):
                H.parse_pair(log)

    def test_unrelated_i262_route_marker_is_not_a_variant_proof(self):
        with self.assertRaises(H.RouteError):
            H.parse_pair("ggml_vk_i262:v1|route|id=1|graph=1|weight=output.weight\n")


if __name__ == "__main__":
    unittest.main()
