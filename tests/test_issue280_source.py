"""Exact-source transform tests: pinned SOURCE ONLY, no binaries/models/devices."""
from pathlib import Path
import importlib.util
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/issue280_source.py"


class SourceTransformTests(unittest.TestCase):
    def module(self):
        self.assertTrue(SCRIPT.is_file(), "exact-source transformer is missing")
        spec = importlib.util.spec_from_file_location("issue280_source", SCRIPT)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_local_pinned_source_transform_is_additions_only(self):
        m = self.module()
        source = Path("/home/zutfen/llama.cpp-252")
        if not source.is_dir():
            self.skipTest("host-local pinned public source not present")
        originals = {p: (source / p).read_bytes() for p in m.SOURCE_HASHES}
        transformed, identity = m.transform(originals)
        self.assertEqual(identity["source_pin"], "b29c606e28a01b1bc8c1351026a0fa6e616bf6c4")
        self.assertEqual(identity["physical_runner"], "HELD_UNAVAILABLE")
        for path, original in originals.items():
            self.assertEqual(m.remove_insertions(path, transformed[path]), original)
            self.assertEqual((source / path).read_bytes(), original)
        self.assertIn("issue280::event", "\n".join(v.decode() for v in transformed.values()))

    def test_unpinned_source_refused_before_transform(self):
        m = self.module()
        with self.assertRaisesRegex(ValueError, "pinned source identity"):
            m.transform({p: b"not pinned source" for p in m.SOURCE_HASHES})

    def test_original_wait_and_transfer_calls_are_preserved(self):
        m = self.module()
        for operations in m.INSERTIONS.values():
            for anchor, extra, where in operations:
                self.assertIn(where, {"before", "after"})
                self.assertTrue(anchor)
                # New hooks may reference metadata, but cannot add synchronization,
                # transfers, dispatches, tensor gets/sets, or execution callbacks.
                for forbidden in ("waitForFences(", "getFenceStatus(", "waitSemaphores(",
                                  "ggml_backend_synchronize(", "ggml_vk_synchronize(",
                                  "ggml_backend_tensor_get(", "ggml_backend_tensor_set(",
                                  "ggml_backend_sched_set_eval_callback(", ".dispatch(",
                                  "memcpy(", "memset(", "queue.submit("):
                    self.assertNotIn(forbidden, extra)

    def test_full_transformed_git_tree_is_bound_to_pin(self):
        m = self.module()
        self.assertTrue(hasattr(m, "full_tree_identity"), "full transformed Git tree binding is missing")
        source = Path("/home/zutfen/llama.cpp-252")
        if not source.is_dir():
            self.skipTest("host-local pinned public source not present")
        originals = {p: (source / p).read_bytes() for p in m.SOURCE_HASHES}
        files, _ = m.transform(originals)
        identity = m.full_tree_identity(source, files)
        self.assertRegex(identity["full_transformed_git_tree"], r"^[0-9a-f]{40}$")
        self.assertRegex(identity["base_git_tree"], r"^[0-9a-f]{40}$")
        self.assertNotEqual(identity["full_transformed_git_tree"], identity["base_git_tree"])
        self.assertEqual(identity, m.full_tree_identity(source, files))

    def test_cpu_tests_are_registered_in_current_qualification_group(self):
        from scripts import plan_ci
        group = "r8i-qwen-qualification"
        modules = ("test_issue280_observer", "test_issue280_source")
        for module in modules:
            self.assertIn(module, plan_ci.GROUP_TEST_MODULES[group])
        paths = ("scripts/issue280_observer.py", "scripts/issue280_source.py",
                 "docs/investigations/vulkan-same-request-280/fixtures/recording.cpp",
                 "docs/investigations/vulkan-same-request-280/instrumentation/issue280_observer.h")
        for path in paths:
            planned = plan_ci.plan([path])
            self.assertFalse(planned["full_regression"], planned)
            self.assertIn(group, planned["groups"])

    def test_logging_sinks_are_translation_unit_local(self):
        header_dir = ROOT / "docs/investigations/vulkan-same-request-280/instrumentation"
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            common = '#include <iostream>\n#define I280_LOG(s) (std::cout << LABEL << s << "\\n")\n#include "issue280_observer.h"\n'
            (td / "a.cpp").write_text('#define LABEL "A "\n' + common + 'void a() { I280_EVENT("test").emit(); }\n')
            (td / "b.cpp").write_text('#define LABEL "B "\n' + common + 'void b() { I280_EVENT("test").emit(); }\n')
            (td / "main.cpp").write_text('#include <cstdlib>\nvoid a(); void b(); int main(){setenv("ISSUE280_OBSERVE","1",1);a();b();}\n')
            binary = td / "two-sinks"
            subprocess.run(["c++", "-std=c++17", "-O0", "-I", str(header_dir),
                            str(td/"a.cpp"), str(td/"b.cpp"), str(td/"main.cpp"),
                            "-o", str(binary)], check=True, capture_output=True, text=True)
            raw = subprocess.run([str(binary)], check=True, capture_output=True, text=True).stdout
            self.assertEqual([line[:2] for line in raw.splitlines()], ["A ", "B "])


if __name__ == "__main__":
    unittest.main()


class SourceCorrectionTests(unittest.TestCase):
    def test_source_hooks_cover_collector_causality_and_inventory_shapes(self):
        m = SourceTransformTests().module()
        source = Path("/home/zutfen/llama.cpp-252")
        if not source.is_dir():
            self.skipTest("host-local pinned public source not present")
        originals = {path: (source / path).read_bytes() for path in m.SOURCE_HASHES}
        transformed, _ = m.transform(originals)
        self.assertIn("src/llama-model.cpp", m.SOURCE_HASHES)
        self.assertIn("src/llama-kv-cache.cpp", m.SOURCE_HASHES)
        server = transformed["tools/server/server-context.cpp"].decode()
        model = transformed["src/llama-model.cpp"].decode()
        kv = transformed["src/llama-kv-cache.cpp"].decode()
        self.assertIn('.json("token_ids", observed_tokens_json)', server)
        self.assertIn('.json("positions", observed_positions_json)', server)
        self.assertIn('.n("pos_present", observed_pos_present ? 1 : 0)', server)
        self.assertIn('.n("ordinal", ++observed_request_ordinal)', server)
        self.assertIn('.s("stop_reason", observed_stop_reason)', server)
        self.assertIn('.n("absolute_position", slot.prompt.tokens.pos_next())', server)
        self.assertIn('event("weight_inventory")', model)
        self.assertIn('event("kv_inventory")', kv)
        for path, original in originals.items():
            self.assertEqual(m.remove_insertions(path, transformed[path]), original)

    def test_emitter_json_field_preserves_array_type(self):
        header_dir = ROOT / "docs/investigations/vulkan-same-request-280/instrumentation"
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            (td / "probe.cpp").write_text(
                '#include <iostream>\n'
                '#define I280_LOG(s) (std::cout << s << "\\n")\n'
                '#include "issue280_observer.h"\n'
                'int main() { setenv("ISSUE280_OBSERVE", "1", 1); '
                'I280_EVENT("batch_begin").json("token_ids", "[7,8]").emit(); }\n')
            binary = td / "json-field"
            subprocess.run(["c++", "-std=c++17", "-I", str(header_dir),
                            str(td / "probe.cpp"), "-o", str(binary)],
                           check=True, capture_output=True, text=True)
            raw = subprocess.run([str(binary)], check=True, capture_output=True, text=True).stdout
            self.assertIn('"token_ids":[7,8]', raw)


SCRIPT_OBSERVER = ROOT / "scripts/issue280_observer.py"
FIXTURES = ROOT / "docs/investigations/vulkan-same-request-280/fixtures"
INSTR = ROOT / "docs/investigations/vulkan-same-request-280/instrumentation"


class ProducerOccurrenceTests(unittest.TestCase):
    """R8-A2 (round-9): the producer's emitted occurrence identity must match
    the collector's graph-local, (input, copy)-keyed derivation. The
    producer_occurrence.cpp TEMPLATE has its five counter expressions
    substituted AT TEST TIME with the ACTUAL expressions extracted from the
    transform's production insertions, so compiling and running the harness
    executes the real generated counter logic, and its raw stream is fed to
    the REAL collector. Semantic binding is proven by mutation tests: each
    of four broken transform mutations must produce a harness the collector
    rejects (or the tests fail)."""

    FIXTURE = FIXTURES / "producer_occurrence.cpp"

    @staticmethod
    def production_expressions(backend_ops=None, vk_ops=None, mutations=None):
        """Extract the VERBATIM inserted lines carrying the occurrence
        counters from the transform's production insertions. Whole-line
        extraction (not sub-expression regex): any semantic change to a
        counter line — arithmetic suffix, guard change, decoy duplicate —
        either changes the substituted harness line or trips the strict
        exactly-one-line assertion. Optionally apply semantic mutations to
        the extracted lines."""
        m = SourceTransformTests().module()
        backend_ops = backend_ops if backend_ops is not None else m.INSERTIONS["ggml/src/ggml-backend.cpp"]
        vk_ops = vk_ops if vk_ops is not None else m.INSERTIONS["ggml/src/ggml-vulkan/ggml-vulkan.cpp"]
        lines = [ln.strip() for ln in
                 [l for _, extra, _ in backend_ops for l in extra.splitlines()]
                 + [l for _, extra, _ in vk_ops for l in extra.splitlines()]
                 if ln]
        normalize = lambda text: "".join(text.split())
        def pick(pattern, label):
            # Whitespace-normalized whole-line matching: a duplicate counter
            # call with ANY spacing (e.g. begin(input,input_cpy)) also
            # matches and trips the exactly-one assertion.
            needle = normalize(pattern)
            matches = [ln for ln in lines if needle in normalize(ln)]
            if len(matches) != 1:
                raise AssertionError(
                    f"{label}: expected exactly one inserted line containing {pattern!r}, "
                    f"found {len(matches)}: {matches}")
            line = matches[0]
            if mutations and label in mutations:
                old, new = mutations[label]
                assert old in line, f"{label}: mutation anchor {old!r} absent from {line!r}"
                line = line.replace(old, new)
            return line
        return {
            "RESET": pick("issue280_occurrence::reset()", "reset"),
            "ASSIGN": pick("issue280_occurrence::assign(input, copy)", "assign"),
            "BEGIN": pick("issue280_occurrence::begin(input, input_cpy)", "begin"),
            "END": pick("issue280_occurrence::current(input, input_cpy)", "end"),
            "PATH": pick("issue280_occurrence::current(src, dst)", "path"),
        }

    def harness_source(self, expressions):
        source = self.FIXTURE.read_text()
        for placeholder, expression in expressions.items():
            token = "{" + placeholder + "}"
            # The placeholder must exist in EXECUTABLE position: a token
            # kept only in a comment would silently disable binding.
            executable = [ln for ln in source.splitlines()
                          if not ln.lstrip().startswith(("//", "/*", "*", "*/"))]
            self.assertTrue(any(token in ln for ln in executable),
                            f"harness template lost its executable {token} placeholder")
            source = source.replace(token, expression)
        return source

    def run_harness(self, case, expressions):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            source = td / "harness.cpp"
            source.write_text(self.harness_source(expressions))
            binary = td / "producer-occurrence"
            subprocess.run(["c++", "-std=c++17", "-Wall", "-Wextra", "-Werror",
                            "-I", str(INSTR), str(source),
                            "-o", str(binary)], check=True, capture_output=True, text=True)
            return subprocess.run([str(binary), case], check=True,
                                  capture_output=True, text=True).stdout

    def collect(self, case, contract_boundaries=None, expressions=None):
        self.assertTrue(self.FIXTURE.is_file(), "producer occurrence harness template is missing")
        spec = importlib.util.spec_from_file_location("issue280_observer_r9", SCRIPT_OBSERVER)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        exprs = expressions if expressions is not None else self.production_expressions()
        raw = self.run_harness(case, exprs)
        contract = module.fixture_contract()
        if contract_boundaries is not None:
            contract["boundaries"] = contract_boundaries
        return module.collect(raw, contract), raw

    def boundary_rows(self, count, occurrences=None):
        rows = [{"tensor": "ffn_out-0", "src": "0000:01:00.0",
                 "dst": "0000:02:00.0", "bytes_per_token": 16}
                for _ in range(count)]
        if occurrences is not None:
            rows[0]["occurrences"] = occurrences
        return rows

    def test_same_pair_across_two_graphs_emits_zero_then_zero(self):
        # Required case 1: same (input, copy) across two graph invocations
        # in one process, graph object reused — occurrence 0, then 0. At the
        # round-8 head the producer's process-lifetime counter emitted 1 for
        # the second graph and the collector rejected the valid stream.
        result, raw = self.collect("two-graphs-same-pair", self.boundary_rows(1))
        self.assertTrue(result["ok"], result["problems"])
        occurrences = [(b["input"], b["copy"], b["occ"])
                       for graph in result["graphs"] for b in graph["boundaries"]]
        self.assertEqual(occurrences, [("0x1000", "0x2000", 0), ("0x1000", "0x2000", 0)])

    def test_one_input_two_copies_emit_zero_for_each_pair(self):
        # Required case 2: one input with two distinct copies in one graph —
        # occurrence 0 for each (input, copy) pair.
        result, _ = self.collect("one-input-two-copies", self.boundary_rows(2))
        self.assertTrue(result["ok"], result["problems"])
        boundaries = result["graphs"][0]["boundaries"]
        self.assertEqual([(b["input"], b["copy"], b["occ"]) for b in boundaries],
                         [("0x1000", "0x2000", 0), ("0x1000", "0x3000", 0)])

    def test_repeated_pair_within_graph_emits_zero_then_one(self):
        # Required case 3: repeated occurrences of the same pair within a
        # graph — 0, then 1.
        result, _ = self.collect("repeat-pair", self.boundary_rows(1, occurrences=2))
        self.assertTrue(result["ok"], result["problems"])
        self.assertEqual([b["occ"] for b in result["graphs"][0]["boundaries"]], [0, 1])

    def test_manifest_begin_copy_path_end_agree(self):
        # Required case 4 (agreement half): manifest, begin, copy_path and
        # end carry ONE occurrence; the stream is admitted.
        result, raw = self.collect("agree", self.boundary_rows(1))
        self.assertTrue(result["ok"], result["problems"])
        self.assertEqual(result["logical_boundary_bytes"], 64)
        # All four row kinds agree on occ=0 for the pair.
        for line in raw.splitlines():
            if '"copy_manifest"' in line or '"boundary_begin"' in line \
                    or '"copy_path"' in line or '"boundary_end"' in line:
                self.assertIn('"occ":0', line)

    def test_wrong_copy_path_occurrence_rejects(self):
        # Required case 4 (wrong-occurrence half): a deliberately wrong
        # occurrence on copy_path must still reject. Expressed as a
        # production-expression mutation (path + 1) flowing through the
        # normal binding path.
        backend, vk = self.mutated_insertions(
            "path", "issue280_occurrence::current(src, dst)",
            "issue280_occurrence::current(src, dst) + 1")
        expressions = self.production_expressions(backend_ops=backend, vk_ops=vk)
        result, _ = self.collect("agree", self.boundary_rows(1), expressions)
        self.assertFalse(result["ok"])
        self.assertIn("copy path outside logical boundary occurrence",
                      "\n".join(result["problems"]))

    def test_wrong_begin_occurrence_rejects(self):
        # Required case 4 (wrong-occurrence half): a deliberately wrong
        # occurrence on boundary_begin must still reject (begin + 1 makes
        # the begin key disagree with its manifest).
        backend, vk = self.mutated_insertions(
            "begin", "issue280_occurrence::begin(input, input_cpy)",
            "issue280_occurrence::begin(input, input_cpy) + 1")
        expressions = self.production_expressions(backend_ops=backend, vk_ops=vk)
        result, _ = self.collect("agree", self.boundary_rows(1), expressions)
        self.assertFalse(result["ok"])
        joined = "\n".join(result["problems"])
        self.assertTrue("missing or consumed preexecution boundary manifest" in joined
                        or "unmatched boundary end" in joined,
                        f"wrong begin occ not rejected: {result['problems']}")

    def test_harness_executes_production_counter_expressions(self):
        # Binding: the harness template's placeholders are substituted with
        # the expressions extracted from the transform's production
        # insertions — the harness literally contains the transform's code.
        expressions = self.production_expressions()
        source = self.harness_source(expressions)
        for expression in expressions.values():
            self.assertIn(expression, source)
        self.assertNotIn("{RESET}", source)
        self.assertNotIn("{ASSIGN}", source)
        self.assertNotIn("{BEGIN}", source)
        self.assertNotIn("{END}", source)
        self.assertNotIn("{PATH}", source)

    # End-to-end mutations applied to the transform's inserted text itself
    # (the same shape a real transform regression would take), then
    # extracted and executed through the normal binding path.
    TRANSFORM_MUTATIONS = {
        "assign": ("issue280_occurrence::assign(input, copy)",
                   "issue280_occurrence::assign(input, copy) + 1"),
        "begin": ("issue280_occurrence::begin(input, input_cpy)",
                  "issue280_occurrence::begin(input, input_cpy) + 1"),
        "path": ("issue280_occurrence::current(src, dst)",
                 "issue280_occurrence::current(src, dst) + 1"),
        "reset": ("issue280::enabled()", "false"),
    }

    @staticmethod
    def mutated_insertions(label, old, new):
        """Return (backend_ops, vk_ops) copies of the transform's INSERTIONS
        with one counter line semantically mutated, mimicking a transform
        regression."""
        m = SourceTransformTests().module()
        # The reset mutation's anchor (the enabled() guard) appears in every
        # hook; restrict it to the reset line so the rejection provably
        # comes from the lost graph-local reset, not from silenced hooks.
        scope = "issue280_occurrence::reset()" if label == "reset" else None

        def mutate(ops):
            mutated = []
            hit = 0
            for anchor, extra, where in ops:
                if old in extra and (scope is None or scope in extra):
                    extra = extra.replace(old, new)
                    hit += 1
                mutated.append((anchor, extra, where))
            return mutated, hit

        backend, b_hit = mutate(m.INSERTIONS["ggml/src/ggml-backend.cpp"])
        vk, v_hit = mutate(m.INSERTIONS["ggml/src/ggml-vulkan/ggml-vulkan.cpp"])
        total = b_hit + v_hit
        assert total == 1, f"{label}: mutation anchor found {total} times (expected exactly 1)"
        return backend, vk

    def test_mutated_transform_is_detected_by_collector_rejection(self):
        # Semantic binding (round-9 review findings): a transform whose
        # inserted counter line is semantically broken must produce a
        # harness whose stream the REAL collector rejects. The mutations
        # are applied to the transform's insertion text itself and flow
        # through the SAME extraction path as the unmutated transform —
        # arithmetic suffixes, guard disabling, decoy duplicates and
        # removed placeholders cannot pass (extraction asserts exactly one
        # matching line; the template refuses missing placeholders).
        for label, (old, new) in self.TRANSFORM_MUTATIONS.items():
            with self.subTest(mutation=label):
                backend, vk = self.mutated_insertions(label, old, new)
                expressions = self.production_expressions(backend_ops=backend, vk_ops=vk)
                case = "two-graphs-same-pair" if label == "reset" else "agree"
                result, _ = self.collect(case, self.boundary_rows(1), expressions)
                self.assertFalse(result["ok"],
                                 f"{label} mutation admitted: {result['problems']}")

    def test_extraction_rejects_duplicate_or_missing_counter_lines(self):
        # Evasion guards: a decoy duplicate counter line in the insertions
        # and a removed placeholder in the template both fail loudly.
        m = SourceTransformTests().module()
        backend = list(m.INSERTIONS["ggml/src/ggml-backend.cpp"])
        decoy = ("", "// decoy: issue280_occurrence::assign(input, copy)\n", "after")
        backend.append(decoy)
        with self.assertRaises(AssertionError):
            self.production_expressions(backend_ops=backend)
        # Whitespace-variant duplicate (delta2 review finding P1): a second
        # begin call with different spacing must also trip uniqueness.
        vk = list(m.INSERTIONS["ggml/src/ggml-vulkan/ggml-vulkan.cpp"])
        vk.append(("", "issue280_occurrence::begin(input,input_cpy);\n", "after"))
        with self.assertRaises(AssertionError):
            self.production_expressions(vk_ops=vk)
        # Comment-only placeholder (delta2 review finding P2): a placeholder
        # present ONLY in a comment must fail the executable-position check.
        template = self.FIXTURE.read_text()
        hidden = "\n".join(
            ("// {END}" if ln.strip() == "{END}" else ln)
            for ln in template.splitlines())
        original_fixture = self.FIXTURE.read_text()
        try:
            self.FIXTURE.write_text(hidden)
            with self.assertRaises(AssertionError):
                self.harness_source(self.production_expressions())
        finally:
            self.FIXTURE.write_text(original_fixture)

    def test_harness_lifecycle_matches_production_anchors(self):
        # The harness lifecycle corresponds to the pinned production source:
        # reset anchored at ggml_backend_sched_graph_compute_async entry
        # (1:1 with the observer graph_begin on the process_ubatch path),
        # assign in the compute_splits manifest loop, begin/end at the
        # per-split input copy, copy_path in the Vulkan TU on the (src, dst)
        # pair the scheduler copied.
        m = SourceTransformTests().module()
        ops = m.INSERTIONS["ggml/src/ggml-backend.cpp"]
        self.assertTrue(any("ggml_backend_sched_graph_compute_async" in anchor and
                            "issue280_occurrence::reset()" in extra
                            for anchor, extra, _ in ops),
                        "reset is not anchored at the sched entry function")
        self.assertTrue(any("struct ggml_backend_sched_split * splits = sched->splits;" in anchor
                            and "issue280_occurrence::assign(input, copy)" in extra
                            for anchor, extra, _ in ops),
                        "assign is not in the compute_splits manifest loop")
        vk_ops = m.INSERTIONS["ggml/src/ggml-vulkan/ggml-vulkan.cpp"]
        self.assertTrue(any("issue280_occurrence::current(src, dst)" in extra
                            for _, extra, _ in vk_ops),
                        "copy_path does not recall the shared occurrence in the Vulkan TU")
