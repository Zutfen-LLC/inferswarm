"""Issue #260 prospective, synthetic-only observation and closure contract."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

PIN = "b29c606e28a01b1bc8c1351026a0fa6e616bf6c4"
P = "ggml_vk_i260:v1|"


def graph(ident=1, phase="begin", count=None):
    return P + f"graph|id={ident}|phase={phase}" + (f"|compute_submits={count}" if count is not None else "") + "\n"


def submit(g=1, ident=1, path="serialized"):
    return P + f"submit|graph={g}|id={ident}|phase=submit|path={path}\n"


def wait(g=1, ident=1):
    return P + f"submit|graph={g}|id={ident}|phase=wait|path=serialized|wait=success\n"


def h2(path="serialized", g=1, ident=1):
    return graph(g) + submit(g, ident, path) + (wait(g, ident) if path == "serialized" else "") + graph(g, "end", 1)


def memory(ident=1, branch="default", typ=0, flags="1"):
    return P + f"memory|role=backend|buffer={ident}|branch={branch}|type={typ}|flags=0x{flags}\n"


def tensor(ident=1, offset=8, size=16, allocation=64):
    return P + f"tensor|name=output.weight|buffer={ident}|offset={offset}|bytes={size}|allocation_size={allocation}\n"


def retire(ident=1):
    return P + f"memory|role=backend|event=retire|buffer={ident}\n"


def staging(ident=4, owner="device", event="create"):
    return P + f"staging|owner={owner}|event={event}|buffer={ident}\n"


class ProspectiveObservationTests(unittest.TestCase):
    def parse(self, log, arm="A1", tree=None):
        import issue260_instrumentation as I
        return I.parse_unit(log, arm=arm, source_tree=tree if tree is not None else I.INSTRUMENTED_TREE)

    def rejected(self, log, arm):
        from issue260_instrumentation import ObservationError
        with self.assertRaises(ObservationError):
            self.parse(log, arm)

    def test_old_generic_log_and_old_marker_cannot_forge_h2(self):
        self.rejected("ggml_vulkan: GGML_VK_SERIALIZE_SUBMISSIONS=1\n", "A1")
        self.rejected(P + "submit|graph=1|path=serialized|wait=success\n", "A1")

    def test_serialized_submissions_are_paired_with_exact_waits_in_order(self):
        log = graph(8) + submit(8, 21) + wait(8, 21) + submit(8, 23) + wait(8, 23) + graph(8, "end", 2)
        self.assertEqual(self.parse(log, "A1")["graphs"], [8])
        self.assertEqual(self.parse(h2() + h2(g=3, ident=7), "A1")["graphs"], [1, 3])
        self.assertEqual(self.parse(h2("normal"), "BASE")["submission"], "normal")
        for bad in (h2("normal"), graph() + submit() + graph(1, "end", 1),
                    graph() + wait() + submit() + graph(1, "end", 1),
                    graph() + submit() + wait(1, 2) + graph(1, "end", 1),
                    graph() + submit() + wait() + wait() + graph(1, "end", 1),
                    graph() + submit() + wait() + submit(1, 1) + wait() + graph(1, "end", 2),
                    graph() + submit() + wait() + graph(1, "end", 2),
                    graph() + submit() + wait() + graph(1, "end", 0),
                    h2() + wait(), h2() + graph(1) + graph(1, "end", 0),
                    h2(g=3) + h2(g=2, ident=4),
                    h2() + h2(g=2, ident=1),
                    graph(1) + graph(1, "end", 0),
                    h2().replace("id=1", "id=18446744073709551616"),
                    graph() + graph(2) + submit() + wait() + graph(2, "end", 1) + graph(1, "end", 0),
                    graph() + submit(2) + wait(2) + graph(1, "end", 1),
                    graph() + submit() + wait() + graph(2, "end", 1),
                    graph() + submit() + wait() + graph(1, "end", 1) + graph(2),
                    h2().replace("graph=1", "graph=01"),
                    h2().replace("wait=success", "wait=none"),
                    h2().replace("phase=submit", "phase=sent"),
                    h2().replace("v1|", "v2|")):
            with self.subTest(bad=bad):
                self.rejected(bad, "A1")

    def test_baseline_has_no_wait_or_serialized_submits(self):
        self.assertEqual(self.parse(graph() + submit(path="normal") + submit(1, 2, "normal") + graph(1, "end", 2), "BASE")["graphs"], [1])
        for bad in (h2(), graph() + submit(path="normal") + wait() + graph(1, "end", 1),
                    graph() + submit(path="normal") + submit(1, 2) + wait(1, 2) + graph(1, "end", 2)):
            with self.subTest(bad=bad):
                self.rejected(bad, "BASE")

    def test_h3_exact_target_range_and_backend_lifecycle(self):
        good = memory(3, "disable_host_visible") + tensor(3, 48, 16, 64) + staging() + staging(event="retire") + retire(3)
        self.assertEqual(self.parse(good, "A5")["target"]["buffer"], 3)
        self.assertEqual(self.parse(memory(2, "prefer_host", 1, "6") + tensor(2), "A4")["target"]["type"], 1)
        self.assertEqual(self.parse(memory() + tensor(), "BASE")["target"]["branch"], "default")
        for bad in (memory(3, "disable_host_visible"), tensor(3) + memory(3, "disable_host_visible"),
                    retire(3) + memory(3, "disable_host_visible") + tensor(3),
                    memory(3, "disable_host_visible") + retire(3) + tensor(3),
                    memory(3, "disable_host_visible") + tensor(4),
                    memory(3, "disable_host_visible") + tensor(3, 49, 16, 64),
                    memory(3, "disable_host_visible") + tensor(3, 0, 0, 64),
                    memory(3, "disable_host_visible") + tensor(3, 0, 65, 64),
                    memory(3, "disable_host_visible") + tensor(3, 0, 1, 0),
                    memory(3, "disable_host_visible") + tensor(3, 0, 1, 64) + tensor(3),
                    memory(3, "disable_host_visible") + tensor(3) + retire(3) + retire(3),
                    memory(3, "disable_host_visible") + tensor(3) + memory(3, "disable_host_visible"),
                    memory(3, "default") + tensor(3),
                    memory(3, "disable_host_visible", flags="X") + tensor(3),
                    memory(3, "disable_host_visible") + tensor(3).replace("bytes=16", "bytes=016"),
                    memory(3, "disable_host_visible") + tensor(3).replace("offset=8", "offset=-1"),
                    memory(3, "disable_host_visible") + tensor(3).replace("allocation_size=64", "allocation_size=0"),
                    memory(3, "disable_host_visible") + tensor(3) + staging(3),
                    staging(3) + memory(3, "disable_host_visible") + tensor(3),
                    memory(3, "disable_host_visible") + tensor(3) + staging(event="retire"),
                    memory(3, "disable_host_visible") + tensor(3) + staging() + staging(4, "context", "retire"),
                    memory(3, "disable_host_visible") + tensor(3) + staging() + staging(),
                    "ggml_vulkan memory: ggml_vk_ensure_sync_staging_buffer(4096)\n" + staging()):
            with self.subTest(bad=bad):
                self.rejected(bad, "A5")

    def test_h3_choice_is_conditional_on_actual_type_or_flags(self):
        import issue260_instrumentation as I
        baseline = self.parse(memory() + tensor(), "BASE")
        self.assertFalse(I.memory_choice_changed(baseline, self.parse(memory(3, "disable_host_visible") + tensor(3), "A5")))
        self.assertTrue(I.memory_choice_changed(baseline, self.parse(memory(2, "prefer_host", 1, "6") + tensor(2), "A4")))
        self.assertTrue(I.memory_choice_changed(baseline, self.parse(memory(3, "disable_host_visible", 0, "2") + tensor(3), "A5")))

    def test_old_source_pin_rejected_even_with_exact_markers(self):
        from issue260_instrumentation import ObservationError
        with self.assertRaises(ObservationError):
            self.parse(h2(), "A1", PIN)
        with self.assertRaises(ObservationError):
            self.parse(memory(3, "disable_host_visible") + tensor(3), "A5", PIN)

    def test_prospective_h5_gap_remains(self):
        import issue258_theorem as H
        import issue260_instrumentation as I
        import issue252_arms as A
        from issue252_vulkanpath import ENV_EFFECTS
        self.assertEqual(H.terminal_capable_arms(), ["A3"])
        self.assertEqual({g["hypothesis"] for g in H.terminal_closure()["coverage_gaps"]}, {"H2", "H3", "H5"})
        prospective = I.prospective_closure()
        self.assertEqual(prospective["source_identity"], I.INSTRUMENTED_TREE)
        self.assertEqual(prospective["coverage_gaps"], ["H3", "H5"])
        self.assertEqual(prospective["observation_capable_arms"], ["A1", "A4", "A5"])
        self.assertEqual(prospective["terminal_capable_prospective_arms"], ["A1"])
        self.assertFalse(prospective["closure_possible"])
        self.assertEqual(prospective["required_arms"], [])
        self.assertEqual(prospective["h5_blocker"], "H5_DISCRIMINATOR_NOT_BOUNDED")
        self.assertFalse(H.TERMINAL_CAPABLE["A2"])
        self.assertEqual(A.HYPOTHESES[4]["id"], "H5")
        self.assertIn("GGML_VK_DISABLE_COOPMAT2", ENV_EFFECTS)
        self.assertNotIn("A6", A.ARMS)


if __name__ == "__main__":
    unittest.main()
