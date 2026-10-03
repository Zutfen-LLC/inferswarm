"""Issue #264 per-process output.weight MMV dispatch evidence tests."""
from __future__ import annotations

import gzip
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
import issue264_h5 as H

AREA = REPO / "docs/investigations/qwen38-flash-next-r8-i3c-vulkan-mechanism"
ROUTE = ("ggml_vk_i262:v1|route|id={id}|graph={graph}|weight=output.weight|node={node}"
         "|side=0|route=mat-vec|pipe=mul_mat_vec_q4_k_f32_f32|family=mmv"
         "|quant_y=0|split_k=0|64b=0|dims=2560x248320:2560x1->248320x1"
         "|types=q4_K*f32->f32")
VARIANT = ("ggml_vk_i264:v1|mmv|id={id}|node={node}|weight=output.weight|state={state}"
           "|route=mat-vec|pipe=mul_mat_vec_q4_k_f32_f32|wg={wg}"
           "|reduction={reduction}|local={local}x1x1"
           "|dims=2560x248320:2560x1->248320x1"
           "|types=q4_K*f32->f32|quant_y=0|split_k=0|64b=0")


def event(id=1, state="base", node="result_output", graph=61, prefix=""):
    wg, reduction, local = {"base": ("subgroup", "subgroup", 32),
                            "large": ("large", "hybrid", 128)}[state]
    route = ROUTE.format(id=id, node=node, graph=graph)
    variant = VARIANT.format(id=id, node=node, state=state, wg=wg,
                             reduction=reduction, local=local)
    return prefix + route + "\n" + prefix + variant + "\n"


class SelectorContractTests(unittest.TestCase):
    def test_default_and_two_explicit_states(self):
        self.assertEqual(H.select_variant(None), "base")
        self.assertEqual(H.select_variant("base"), "base")
        self.assertEqual(H.select_variant("large"), "large")

    def test_unknown_selector_fails_closed(self):
        for value in ("", "BASE", "subgroup", "large ", "other"):
            with self.subTest(value=value), self.assertRaises(H.RouteError):
                H.select_variant(value)


class UnitEvidenceTests(unittest.TestCase):
    def test_ten_actual_route_events_per_retained_unit(self):
        paths = sorted((AREA / "evidence/issue262/logs").glob("*.server.log.gz"))
        self.assertEqual(len(paths), 8)
        for path in paths:
            with self.subTest(path=path.name):
                text = gzip.open(path, "rt").read()
                routes = [line for line in text.splitlines() if "ggml_vk_i262:" in line]
                self.assertEqual(len(routes), 10)
                # Reuse the actual retained timestamped route lines and cardinality,
                # inserting the proposed marker directly after each dispatch.
                paired = text
                for line in routes:
                    fields = dict(part.split("=", 1) for part in line.split("| ", 1)[-1].split("|") if "=" in part)
                    rid = int(fields["id"])
                    prefix = line[:line.index("ggml_vk_i262:")]
                    marker = VARIANT.format(id=rid, node=fields["node"], state="base",
                                            wg="subgroup", reduction="subgroup", local=32)
                    paired = paired.replace(line + "\n", line + "\n" + prefix + marker + "\n", 1)
                result = H.parse_unit(paired, state="base")
                self.assertEqual(result["marker_count"], 10)
                self.assertEqual(result["event_ids"], list(range(1, 11)))
                self.assertEqual(result["node"], "result_output")

    def test_separate_processes_transition_and_log_prefix(self):
        base = H.parse_unit(event(1, prefix="0.05.221.233 I ") +
                            "ordinary server stdout between events\n" + event(2), state="base")
        large = H.parse_unit(event(1, state="large") + event(2, state="large"), state="large")
        self.assertEqual(H.candidate_transition(base, large)["variants"], ["subgroup", "large"])
        self.assertEqual(base["event_ids"], [1, 2])
        self.assertEqual(large["event_ids"], [1, 2])

    def test_rejects_missing_duplicate_out_of_order_reset_and_unbound_marker(self):
        for log in (ROUTE.format(id=1, graph=61, node="result_output") + "\n",
                    VARIANT.format(id=1, node="result_output", state="base", wg="subgroup", reduction="subgroup", local=32) + "\n",
                    event() + event(), event(2) + event(1), event(2) + event(1) + event(3),
                    event(1).splitlines()[0] + "\n" + event(2),
                    event(1) + event(2).splitlines()[0] + "\n",
                    event(1).replace("mmv|id=1", "mmv|id=2")):
            with self.subTest(log=log[-100:]), self.assertRaises(H.RouteError):
                H.parse_unit(log, state="base")

    def test_rejects_spoofed_variant_non_mmv_and_wrong_frozen_route(self):
        valid = event()
        variants = (valid.replace("state=base", "state=large"),
                    valid.replace("wg=subgroup", "wg=large"),
                    valid.replace("reduction=subgroup", "reduction=hybrid"),
                    valid.replace("local=32x1x1", "local=128x1x1"),
                    valid.replace("node=result_output", "node=other", 1),
                    valid.replace("dims=2560x248320", "dims=1x248320"),
                    valid.replace("types=q4_K*f32->f32", "types=f16*f32->f32"),
                    valid.replace("family=mmv", "family=coopmat2"),
                    valid.replace("route=mat-vec", "route=mat-mat"),
                    valid.replace("quant_y=0", "quant_y=1"),
                    valid.replace("split_k=0", "split_k=1"),
                    valid.replace("64b=0", "64b=1"),
                    valid.replace("|side=0", "|side=1"),
                    valid.replace("graph=61", "graph=0"),
                    valid.replace("|pipe=mul_mat_vec_q4_k_f32_f32", "|pipe=other"),
                    valid.replace("64b=0\n", "64b=0|spoof=1\n"))
        for log in variants:
            with self.subTest(log=log[-100:]), self.assertRaises(H.RouteError):
                H.parse_unit(log, state="base")
        with self.assertRaises(H.RouteError):
            H.parse_unit(valid, state="large")
        with self.assertRaises(H.RouteError):
            H.parse_unit("GGML_VK_I264_MMV=large\n", state="large")

    def test_rejects_unknown_versions_copied_prefix_and_in_stream_node_drift(self):
        for log in (event().replace("i264:v1", "i264:v2"),
                    event().replace("i262:v1", "i262:v2"),
                    event().replace("ggml_vk_i264:v1", "copied ggml_vk_i264:v1"),
                    event().replace("ggml_vk_i262:v1", "copied ggml_vk_i262:v1"),
                    event().replace("ggml_vk_i264:v1", "ggml_vulkan: ggml_vk_i264:v1"),
                    event() + event(2, node="different"),
                    event().replace("ggml_vk_i264:v1|mmv", "ggml_vk_i264:v1|other"),
                    event() + "ggml_vk_i264-v2|mmv|id=2\n",
                    event() + "ggml_vk_i262-v2|route|id=2\n"):
            with self.subTest(log=log[-100:]), self.assertRaises(H.RouteError):
                H.parse_unit(log, state="base")

    def test_cross_arm_requires_same_node_and_real_variant_change(self):
        base = H.parse_unit(event(), state="base")
        large = H.parse_unit(event(state="large"), state="large")
        H.candidate_transition(base, large)
        with self.assertRaises(H.RouteError):
            H.candidate_transition(base, base)
        with self.assertRaises(H.RouteError):
            H.candidate_transition(base, H.parse_unit(event(state="large", node="other"), state="large"))


if __name__ == "__main__":
    unittest.main()
