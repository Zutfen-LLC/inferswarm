"""Issue #130 deterministic finalization — contract and negative controls.

Two layers:

- Engine contract tests use a synthetic stage registry in a temporary
  directory: every negative control from Issue #130 is exercised against
  the real engine (``scripts/finalize_repository.py``), not a mock.
- Migration integration tests bind the real Issue #117 chain (registry
  shape, manifest coverage, and the living-check seam) without re-running
  the 25-second campaign per test.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import finalize_repository as fin  # noqa: E402


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def touch(path: Path, text: str = "x\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


class EngineHarness(unittest.TestCase):
    """Synthetic-tree engine tests: real engine, tiny fake producers."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="finalize-engine-")
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        # minimal git repo so dirty-path accounting works
        subprocess.run(["git", "init", "-q"], cwd=self.root, check=True)
        subprocess.run(
            ["git", "-c", f"safe.directory={self.root}", "-C", str(self.root),
             "config", "user.email", "t@example.com"], check=True)
        subprocess.run(
            ["git", "-c", f"safe.directory={self.root}", "-C", str(self.root),
             "config", "user.name", "t"], check=True)
        touch(self.root / "src.txt", "authored\n")
        touch(self.root / "arm-c/audit.json", "frozen authority\n")
        subprocess.run(
            ["git", "-c", f"safe.directory={self.root}", "-C", str(self.root),
             "add", "-A"], check=True)
        subprocess.run(
            ["git", "-c", f"safe.directory={self.root}", "-C", str(self.root),
             "commit", "-qm", "base"], check=True)

    # -- helpers ---------------------------------------------------------

    @staticmethod
    def derive_from(reads: list[str], out: str,
                    transform=lambda data: data.upper()) -> "callable":
        def producer(run: fin.Run, scratch: Path) -> dict[str, bytes]:
            payload = b"".join(run.read(r) or b"" for r in reads)
            return {out: transform(payload)}
        return producer

    def manifest_producer(self, manifest: str, covered: list[str]):
        def producer(run: fin.Run, scratch: Path) -> dict[str, bytes]:
            rows = {}
            for relative in sorted(covered):
                data = run.read(relative)
                rows[relative] = sha(data) if data else None
            if any(v is None for v in rows.values()):
                missing = [k for k, v in rows.items() if v is None]
                raise fin.FinalizationError(f"missing covered: {missing}")
            body = "".join(
                f"{d}  {p}\n" for p, d in sorted(rows.items()))
            return {manifest: body.encode()}
        return producer

    # -- structural proofs ----------------------------------------------

    def test_registry_is_acyclic_and_orders_topologically(self) -> None:
        stages = (
            fin.Stage("primary", "primary", "src", reads=frozenset({"src.txt"}),
                      verify=lambda run, s: None),
            fin.Stage("gen", "derived", "g", reads=frozenset({"src.txt"}),
                      writes=frozenset({"gen.txt"}), after=frozenset({"primary"}),
                      producer=self.derive_from(["src.txt"], "gen.txt")),
            fin.Stage("idx", "index", "i", reads=frozenset({"gen.txt"}),
                      writes=frozenset({"idx.json"}), after=frozenset({"gen"}),
                      producer=self.derive_from(["gen.txt"], "idx.json")),
            fin.Stage("man", "terminal-manifest", "m",
                      writes=frozenset({"MANIFEST.sha256"}),
                      covers=frozenset({"gen.txt", "idx.json"}),
                      after=frozenset({"idx"}),
                      producer=self.manifest_producer(
                          "MANIFEST.sha256", ["gen.txt", "idx.json"])),
        )
        order = fin.topological_order(stages)
        self.assertLess(order.index("primary"), order.index("gen"))
        self.assertLess(order.index("gen"), order.index("idx"))
        self.assertLess(order.index("idx"), order.index("man"))
        fin.validate_registry(stages)  # does not raise
        fin.validate_order(stages, order)

    def test_dependency_cycle_is_rejected_with_the_actual_cycle(self) -> None:
        stages = (
            fin.Stage("a", "derived", "a", reads=frozenset({"src.txt"}),
                      writes=frozenset({"a.txt"}), after=frozenset({"b"}),
                      producer=self.derive_from(["src.txt"], "a.txt")),
            fin.Stage("b", "derived", "b", reads=frozenset({"a.txt"}),
                      writes=frozenset({"b.txt"}), after=frozenset({"a"}),
                      producer=self.derive_from(["a.txt"], "b.txt")),
        )
        fin.validate_registry(stages)
        with self.assertRaises(fin.FinalizationError) as caught:
            fin.topological_order(stages)
        self.assertIn("cycle", str(caught.exception))
        self.assertIn("a", str(caught.exception))
        self.assertIn("b", str(caught.exception))

    def test_stage_writing_a_later_stage_manifest_covered_input_fails(self):
        # stage A (a generator) writes gen.txt; terminal manifest M covers
        # gen.txt and runs BEFORE another stage B that also writes gen.txt
        # — impossible (single writer), so the control is instead: a stage
        # writes a path an ALREADY-RUN stage read (reader-after-writer).
        stages = (
            fin.Stage("reader-first", "index", "r",
                      reads=frozenset({"src.txt"}),
                      writes=frozenset({"r.out"}),
                      producer=self.derive_from(["src.txt"], "r.out")),
            fin.Stage("writer-late", "derived", "w",
                      writes=frozenset({"src.txt"}),
                      after=frozenset({"reader-first"}),
                      producer=lambda run, s: {"src.txt": b"mutated"}),
        )
        order = fin.topological_order(stages)
        with self.assertRaises(fin.FinalizationError) as caught:
            fin.validate_order(stages, order)
        self.assertIn("src.txt", str(caught.exception))

    def test_writer_after_terminal_manifest_rejected(self) -> None:
        # a stage mutates a manifest-covered path after the manifest
        stages = (
            fin.Stage("gen", "derived", "g", reads=frozenset({"src.txt"}),
                      writes=frozenset({"gen.txt"}),
                      producer=self.derive_from(["src.txt"], "gen.txt")),
            fin.Stage("man", "terminal-manifest", "m",
                      writes=frozenset({"MANIFEST.sha256"}),
                      covers=frozenset({"gen.txt"}),
                      producer=self.manifest_producer(
                          "MANIFEST.sha256", ["gen.txt"])),
            fin.Stage("late", "derived", "l",
                      writes=frozenset({"gen.txt"}),
                      after=frozenset({"man"}),
                      producer=lambda run, s: {"gen.txt": b"late rewrite"}),
        )
        # single-writer validation fires first
        with self.assertRaises(fin.FinalizationError):
            fin.validate_registry(stages)
        # and even with distinct paths, a post-manifest writer of a
        # covered path is rejected in order validation
        stages2 = (
            fin.Stage("gen", "derived", "g", reads=frozenset({"src.txt"}),
                      writes=frozenset({"gen.txt"}),
                      producer=self.derive_from(["src.txt"], "gen.txt")),
            fin.Stage("man", "terminal-manifest", "m",
                      writes=frozenset({"MANIFEST.sha256"}),
                      covers=frozenset({"gen.txt", "src.txt"}),
                      producer=self.manifest_producer(
                          "MANIFEST.sha256", ["gen.txt", "src.txt"])),
            fin.Stage("late", "derived", "l",
                      writes=frozenset({"src.txt"}),
                      after=frozenset({"man"}),
                      producer=lambda run, s: {"src.txt": b"late"}),
        )
        order = fin.topological_order(stages2)
        with self.assertRaises(fin.FinalizationError) as caught:
            fin.validate_order(stages2, order)
        self.assertIn("after", str(caught.exception))

    def test_manifest_covering_itself_is_rejected(self) -> None:
        stages = (
            fin.Stage("gen", "derived", "g", reads=frozenset({"src.txt"}),
                      writes=frozenset({"gen.txt"}),
                      producer=self.derive_from(["src.txt"], "gen.txt")),
            fin.Stage("man", "terminal-manifest", "m",
                      writes=frozenset({"MANIFEST.sha256"}),
                      covers=frozenset({"gen.txt", "MANIFEST.sha256"}),
                      producer=self.manifest_producer(
                          "MANIFEST.sha256",
                          ["gen.txt", "MANIFEST.sha256"])),
        )
        with self.assertRaises(fin.FinalizationError) as caught:
            fin.validate_registry(stages)
        self.assertIn("self", str(caught.exception).lower())

    def test_generator_writing_undeclared_path_fails(self) -> None:
        stages = (
            fin.Stage("gen", "derived", "g", reads=frozenset({"src.txt"}),
                      writes=frozenset({"gen.txt"}),
                      producer=lambda run, s: {
                          "gen.txt": b"ok", "undeclared.txt": b"surprise"}),
        )
        with self.assertRaises(fin.FinalizationError) as caught:
            fin.run_pipeline(self.root, stages, write=False)
        self.assertIn("undeclared", str(caught.exception))

    def test_producer_hash_after_manifest_is_structurally_impossible(self):
        # producer-hashes is an index consumed (covered) by the manifest:
        # registering it AFTER the manifest is rejected by the engine
        stages = (
            fin.Stage("gen", "derived", "g", reads=frozenset({"src.txt"}),
                      writes=frozenset({"gen.txt"}),
                      producer=self.derive_from(["src.txt"], "gen.txt")),
            fin.Stage("man", "terminal-manifest", "m",
                      writes=frozenset({"MANIFEST.sha256"}),
                      covers=frozenset({"gen.txt", "hashes.json"}),
                      producer=self.manifest_producer(
                          "MANIFEST.sha256", ["gen.txt", "hashes.json"])),
            fin.Stage("late-index", "index", "h",
                      writes=frozenset({"hashes.json"}),
                      after=frozenset({"man"}),
                      producer=lambda run, s: {
                          "hashes.json": json.dumps(
                              {"gen.txt": sha(b"GEN\n")}).encode()}),
        )
        order = fin.topological_order(stages)
        with self.assertRaises(fin.FinalizationError):
            fin.validate_order(stages, order)

    def test_missing_input_fails_closed(self) -> None:
        stages = (
            fin.Stage("gen", "derived", "g", reads=frozenset({"absent.txt"}),
                      writes=frozenset({"gen.txt"}),
                      producer=self.derive_from(["absent.txt"], "gen.txt")),
        )
        with self.assertRaises(fin.FinalizationError) as caught:
            fin.run_pipeline(self.root, stages, write=False)
        self.assertIn("missing", str(caught.exception))

    # -- transaction behavior --------------------------------------------

    def test_second_pass_byte_changes_fail_the_fixed_point(self) -> None:
        counter = {"n": 0}

        def flaky(run: fin.Run, scratch: Path) -> dict[str, bytes]:
            counter["n"] += 1
            return {"gen.txt": f"attempt {counter['n']}\n".encode()}

        stages = (
            fin.Stage("gen", "derived", "g", reads=frozenset({"src.txt"}),
                      writes=frozenset({"gen.txt"}), producer=flaky),
        )
        with self.assertRaises(fin.FinalizationError) as caught:
            fin.finalize(self.root, stages, write=True)
        self.assertIn("fixed point", str(caught.exception))
        # the tree was left with the first-pass bytes (no retries)
        self.assertEqual((self.root / "gen.txt").read_text(), "attempt 1\n")

    def test_authored_dirty_files_are_never_stashed_or_reverted(self) -> None:
        # an unrelated authored edit in the worktree survives finalization
        touch(self.root / "notes.md", "user's in-progress edit\n")
        stages = (
            fin.Stage("gen", "derived", "g", reads=frozenset({"src.txt"}),
                      writes=frozenset({"gen.txt"}),
                      producer=self.derive_from(["src.txt"], "gen.txt")),
        )
        report = fin.finalize(self.root, stages, write=True)
        self.assertEqual(
            (self.root / "notes.md").read_text(), "user's in-progress edit\n")
        self.assertIn("notes.md", report["starting_dirty_paths"])
        # generated output did not clobber the authored primary input
        self.assertEqual((self.root / "src.txt").read_text(), "authored\n")

    def test_check_mode_detects_drift_without_writing(self) -> None:
        stages = (
            fin.Stage("gen", "derived", "g", reads=frozenset({"src.txt"}),
                      writes=frozenset({"gen.txt"}),
                      producer=self.derive_from(["src.txt"], "gen.txt")),
        )
        fin.finalize(self.root, stages, write=True)
        self.assertEqual((self.root / "gen.txt").read_text(), "AUTHORED\n")
        # drift the authored input (making it dirty); check must fail on
        # the stale derived artifact and must not write anything
        touch(self.root / "src.txt", "authored v2\n")
        with self.assertRaises(fin.FinalizationError) as caught:
            fin.finalize(self.root, stages, write=False)
        self.assertIn("stale", str(caught.exception))
        self.assertEqual((self.root / "gen.txt").read_text(), "AUTHORED\n")
        self.assertEqual((self.root / "src.txt").read_text(), "authored v2\n")

    def test_stage_error_reports_which_stage_changed_what(self) -> None:
        stages = (
            fin.Stage("up", "derived", "u", reads=frozenset({"src.txt"}),
                      writes=frozenset({"up.txt"}),
                      producer=self.derive_from(["src.txt"], "up.txt")),
            fin.Stage("down", "derived", "d", reads=frozenset({"up.txt"}),
                      writes=frozenset({"down.txt"}),
                      after=frozenset({"up"}),
                      producer=self.derive_from(["up.txt"], "down.txt",
                                                lambda d: d.lower())),
        )
        report = fin.finalize(self.root, stages, write=True)
        self.assertEqual(report["changed"]["up"], ["up.txt"])
        self.assertEqual(report["changed"]["down"], ["down.txt"])

    # -- real-filesystem-mutation negative controls (Issue #130 review) --

    def _baseline(self) -> dict[str, str]:
        """Map every real-root file to its content digest."""
        return {
            p.relative_to(self.root).as_posix(): sha(p.read_bytes())
            for p in sorted(self.root.rglob("*"))
            if p.is_file() and ".git" not in p.parts}

    def _assert_tree_unchanged(self, baseline: dict[str, str]) -> None:
        self.assertEqual(self._baseline(), baseline)

    def test_producer_directly_writing_undeclared_repo_path_fails_closed(self):
        # a producer writes run.root / "undeclared.txt" with an absolute
        # path while returning only a valid declared output: the guard
        # catches the real-worktree mutation, fails closed, and restores
        # the repository byte-identically
        touch(self.root / "authored-dirty.md", "precious authored edit\n")
        baseline = self._baseline()

        def rogue(run: fin.Run, scratch: Path) -> dict[str, bytes]:
            (run.root / "undeclared.txt").write_text("surprise\n")
            return {"gen.txt": b"ok\n"}

        stages = (
            fin.Stage("gen", "derived", "g", reads=frozenset({"src.txt"}),
                      writes=frozenset({"gen.txt"}), producer=rogue),
        )
        with self.assertRaises(fin.FinalizationError) as caught:
            fin.finalize(self.root, stages, write=True)
        self.assertIn("escaped the engine contract", str(caught.exception))
        self._assert_tree_unchanged(baseline)
        self.assertFalse((self.root / "undeclared.txt").exists())

    def test_producer_writing_via_sandbox_relative_path_fails_closed(self):
        # the callable executes chdir'd into the sandbox, so a relative
        # write lands in the sandbox and is caught by the sandbox digest
        touch(self.root / "authored-dirty.md", "precious authored edit\n")
        baseline = self._baseline()

        def rogue(run: fin.Run, scratch: Path) -> dict[str, bytes]:
            os.makedirs("docs", exist_ok=True)
            with open("docs/injected.txt", "w") as handle:
                handle.write("sandbox injection\n")
            return {"gen.txt": b"ok\n"}

        stages = (
            fin.Stage("gen", "derived", "g", reads=frozenset({"src.txt"}),
                      writes=frozenset({"gen.txt"}), producer=rogue),
        )
        with self.assertRaises(fin.FinalizationError) as caught:
            fin.finalize(self.root, stages, write=True)
        self.assertIn("sandbox", str(caught.exception))
        self._assert_tree_unchanged(baseline)

    def test_producer_modifying_existing_authored_dirty_file_fails_closed(self):
        # a producer directly modifies an unrelated authored dirty file:
        # the starting bytes are preserved byte-identically
        touch(self.root / "notes with spaces.md",
              "user's in-progress edit, byte one\n")
        baseline = self._baseline()

        def rogue(run: fin.Run, scratch: Path) -> dict[str, bytes]:
            (run.root / "notes with spaces.md").write_text("clobbered\n")
            return {"gen.txt": b"ok\n"}

        stages = (
            fin.Stage("gen", "derived", "g", reads=frozenset({"src.txt"}),
                      writes=frozenset({"gen.txt"}), producer=rogue),
        )
        with self.assertRaises(fin.FinalizationError) as caught:
            fin.finalize(self.root, stages, write=True)
        self.assertIn("escaped the engine contract", str(caught.exception))
        self.assertEqual((self.root / "notes with spaces.md").read_text(),
                         "user's in-progress edit, byte one\n")
        self._assert_tree_unchanged(baseline)

    def test_producer_modifying_clean_tracked_file_fails_closed(self):
        # a producer rewrites a clean tracked file: the guard fails
        # closed and the file is restored to its proven HEAD bytes
        baseline = self._baseline()

        def rogue(run: fin.Run, scratch: Path) -> dict[str, bytes]:
            (run.root / "src.txt").write_text("hijacked\n")
            return {"gen.txt": b"ok\n"}

        stages = (
            fin.Stage("gen", "derived", "g", reads=frozenset({"arm-c/audit.json"}),
                      writes=frozenset({"gen.txt"}), producer=rogue),
        )
        with self.assertRaises(fin.FinalizationError) as caught:
            fin.finalize(self.root, stages, write=True)
        self.assertIn("escaped the engine contract", str(caught.exception))
        self.assertEqual((self.root / "src.txt").read_text(), "authored\n")
        self._assert_tree_unchanged(baseline)

    def test_verifier_directly_creating_repo_file_fails_closed(self):
        touch(self.root / "authored-dirty.md", "precious authored edit\n")
        baseline = self._baseline()

        def rogue_verify(run: fin.Run, scratch: Path) -> None:
            (run.root / "verifier-artifact.txt").write_text("forged\n")

        stages = (
            fin.Stage("chk", "verify", "v", reads=frozenset({"src.txt"}),
                      verify=rogue_verify),
        )
        with self.assertRaises(fin.FinalizationError) as caught:
            fin.finalize(self.root, stages, write=True)
        self.assertIn("escaped the engine contract", str(caught.exception))
        self._assert_tree_unchanged(baseline)
        self.assertFalse((self.root / "verifier-artifact.txt").exists())

    def test_verifier_modifying_repo_file_fails_closed(self):
        touch(self.root / "authored-dirty.md", "precious authored edit\n")
        baseline = self._baseline()

        def rogue_verify(run: fin.Run, scratch: Path) -> None:
            with open(run.root / "authored-dirty.md", "a") as handle:
                handle.write("appended by verifier\n")

        stages = (
            fin.Stage("chk", "verify", "v", reads=frozenset({"src.txt"}),
                      verify=rogue_verify),
        )
        with self.assertRaises(fin.FinalizationError) as caught:
            fin.finalize(self.root, stages, write=True)
        self.assertIn("escaped the engine contract", str(caught.exception))
        self.assertEqual((self.root / "authored-dirty.md").read_text(),
                         "precious authored edit\n")
        self._assert_tree_unchanged(baseline)

    def test_check_mode_with_mutating_callable_is_mechanically_no_write(self):
        # --check encountering a mutating callable fails and leaves the
        # repository byte-identical to its starting state
        touch(self.root / "authored-dirty.md", "precious authored edit\n")
        baseline = self._baseline()

        def rogue(run: fin.Run, scratch: Path) -> dict[str, bytes]:
            (run.root / "undeclared.txt").write_text("surprise\n")
            return {"gen.txt": b"ok\n"}

        stages = (
            fin.Stage("gen", "derived", "g", reads=frozenset({"src.txt"}),
                      writes=frozenset({"gen.txt"}), producer=rogue),
        )
        with self.assertRaises(fin.FinalizationError):
            fin.finalize(self.root, stages, write=False)
        self._assert_tree_unchanged(baseline)
        self.assertFalse((self.root / "gen.txt").exists())

    def test_check_mode_with_mutating_verifier_is_mechanically_no_write(self):
        touch(self.root / "authored-dirty.md", "precious authored edit\n")
        baseline = self._baseline()

        def rogue_verify(run: fin.Run, scratch: Path) -> None:
            (run.root / "verifier-artifact.txt").write_text("forged\n")

        stages = (
            fin.Stage("chk", "verify", "v", reads=frozenset({"src.txt"}),
                      verify=rogue_verify),
        )
        with self.assertRaises(fin.FinalizationError):
            fin.finalize(self.root, stages, write=False)
        self._assert_tree_unchanged(baseline)
        self.assertFalse((self.root / "verifier-artifact.txt").exists())

    # -- fail-closed dirty-state census (Issue #130 review) ---------------

    def test_dirty_paths_handles_spaces_and_special_filenames(self) -> None:
        # filenames with spaces, quotes, and non-ASCII must survive the
        # NUL-delimited porcelain census unquoted and unambiguous
        weird = [
            "notes with spaces.md",
            'file "quoted" name.txt',
            "résumé-ünïcode.md",
            "sub dir/inner file.txt",
        ]
        for name in weird:
            touch(self.root / name)
        subprocess.run(
            ["git", "-c", f"safe.directory={self.root}", "-C",
             str(self.root), "add", "-A"], check=True)
        touch(self.root / "staged then edited.txt", "staged\n")
        dirty = fin.dirty_paths(self.root)
        for name in weird + ["staged then edited.txt"]:
            self.assertIn(name, dirty)

    def test_dirty_paths_fails_closed_when_git_fails(self) -> None:
        # a git binary that cannot report status must raise, never return
        # an invented empty census: break the repository header so every
        # git plumbing call fails
        original = self.root / ".git" / "HEAD"
        original.rename(original.parent / "HEAD.broken")
        try:
            with self.assertRaises(fin.FinalizationError) as caught:
                fin.dirty_paths(self.root)
            self.assertIn("trustworthy", str(caught.exception))
        finally:
            (self.root / ".git" / "HEAD.broken").rename(original)

    def test_dirty_paths_fails_closed_outside_a_repository(self) -> None:
        with tempfile.TemporaryDirectory() as empty:
            with self.assertRaises(fin.FinalizationError):
                fin.dirty_paths(Path(empty))




class MigrationContractTests(unittest.TestCase):
    """The real Issue #117 registry: shape and coverage (no campaign run)."""

    def test_registry_order_and_kinds(self) -> None:
        order = fin.topological_order(fin.default_registry())
        self.assertEqual(order[0], "status-source")
        self.assertLess(order.index("status-sync"),
                        order.index("issue117-evidence"))
        self.assertLess(order.index("issue117-evidence"),
                        order.index("issue117-producer-hashes"))
        self.assertEqual(order[-2], "issue117-manifest")
        self.assertEqual(order[-1], "issue137-bundle-verify")

    def test_status_sync_declares_consumed_documents_as_self_inputs(self):
        # status-sync's desired bytes consume the existing bytes of every
        # managed document (authored content outside the generated
        # sections), so each managed document is declared in both reads
        # and writes — a self-input the DAG represents mechanically
        registry = {s.id: s for s in fin.default_registry()}
        stage = registry["status-sync"]
        for relative in stage.writes:
            self.assertIn(relative, stage.reads, relative)

    def test_producer_hashes_stage_declares_every_hashed_producer(self):
        # the index stage hashes issue117_proof.PRODUCERS at run time, so
        # its declared reads must be exactly that canonical inventory —
        # zero declared reads while reading every producer is the lie the
        # review rejected
        registry = {s.id: s for s in fin.default_registry()}
        stage = registry["issue117-producer-hashes"]
        expected = fin._producer_paths()
        self.assertTrue(expected)
        self.assertEqual(stage.reads, expected)

    def test_writer_after_real_production_stage_input_is_rejected(self):
        # structural negative control over the REAL migrated registry:
        # registering a writer after (a) a producer-hash input and
        # (b) a status-sync consumed target must fail DAG validation.
        # The legitimate reader stage keeps its declaration (so the
        # attack targets a real read) but is swapped out where needed to
        # keep single-writer validity for the rogue.
        registry = fin.default_registry()

        # (a) a stage that writes a hashed producer path after the index
        # stage read it (the authority stage also declares that read; it
        # is dropped so single-writer validation lets the rogue in and
        # the reader-after-writer proof is what fires)
        rogue_a = fin.Stage(
            "rogue-producer-writer", "derived", "rogue",
            writes=frozenset({"scripts/issue117_planner.py"}),
            after=frozenset({"issue117-producer-hashes"}),
            producer=lambda run, s: {
                "scripts/issue117_planner.py": b"hijacked"})
        stages_a = []
        for stage in registry:
            if stage.id == "issue117-authority":
                continue  # single-writer room for the rogue
            if stage.id == "issue117-evidence":
                # keep its real reads; drop the removed stage from after
                stage = fin.Stage(
                    id=stage.id, kind=stage.kind,
                    description=stage.description, reads=stage.reads,
                    writes=stage.writes, covers=stage.covers,
                    after=stage.after - {"issue117-authority"},
                    producer=stage.producer, verify=stage.verify)
            stages_a.append(stage)
        stages_a = tuple(stages_a) + (rogue_a,)
        fin.validate_registry(stages_a)
        order = fin.topological_order(stages_a)
        with self.assertRaises(fin.FinalizationError) as caught:
            fin.validate_order(stages_a, order)
        self.assertIn("scripts/issue117_planner.py", str(caught.exception))

        # (b) a stage that writes a status-sync consumed managed document
        # after status-sync has run. status-sync keeps its REAL declared
        # reads (the self-inputs under attack); only its writes are
        # suppressed so the rogue is README.md's single writer and the
        # reader-after-writer proof — not single-writer — is what fires.
        real_sync = next(s for s in registry if s.id == "status-sync")
        sync_reads_only = fin.Stage(
            id=real_sync.id, kind=real_sync.kind,
            description=real_sync.description, reads=real_sync.reads,
            after=real_sync.after, producer=lambda run, s: {})
        rogue_b = fin.Stage(
            "rogue-doc-writer", "derived", "rogue",
            writes=frozenset({"README.md"}),
            after=frozenset({"status-sync"}),
            producer=lambda run, s: {"README.md": b"hijacked"})
        stages_b = tuple(s for s in registry
                         if s.id != "status-sync") \
            + (sync_reads_only, rogue_b)
        fin.validate_registry(stages_b)
        order = fin.topological_order(stages_b)
        with self.assertRaises(fin.FinalizationError) as caught:
            fin.validate_order(stages_b, order)
        self.assertIn("README.md", str(caught.exception))

    def test_issue117_evidence_declares_authority_inputs(self):
        # the campaign's applicability audit verifies pinned authority
        # files and the accepted-subject reconstruction consumes its
        # pinned evidence package: those bytes influence campaign
        # outputs and belong in the evidence stage's declared reads
        registry = {s.id: s for s in fin.default_registry()}
        stage = registry["issue117-evidence"]
        authority = registry["issue117-authority"]
        for relative in authority.reads:
            self.assertIn(relative, stage.reads, relative)
        self.assertIn("scripts/issue117_planner.py", stage.reads)

    def test_issue137_verify_declares_bundle_inputs(self):
        # the closed-bundle verifier hashes every bundle evidence file
        # and producer: the stage contract must declare those local
        # file inputs instead of hiding them
        registry = {s.id: s for s in fin.default_registry()}
        stage = registry["issue137-bundle-verify"]
        self.assertIn(fin._BUNDLE_137 + "/METHODOLOGY.md", stage.reads)
        self.assertIn(fin._BUNDLE_137 + "/MANIFEST.sha256", stage.reads)
        self.assertTrue(any(p.startswith("scripts/issue137_")
                            for p in stage.reads))

    def test_manifest_stage_covers_producer_hashes_and_living_docs(self) -> None:
        registry = {s.id: s for s in fin.default_registry()}
        covers = registry["issue117-manifest"].covers
        self.assertIn(fin._PRODUCER_HASHES, covers)
        # producers and methodology are covered...
        self.assertTrue(any(p.startswith("scripts/") for p in covers))
        # ...but living documents are never covered (immutable-bundle rule)
        for living in fin.FORBIDDEN_LIVING if hasattr(fin, "FORBIDDEN_LIVING") else (
                "README.md", "ROADMAP.md", "ARCHITECTURE.md",
                ".github/workflows/ci.yml", "docs/project-status.json"):
            self.assertNotIn(living, covers)

    def test_arm_c_authority_paths_are_never_written(self) -> None:
        written = {p for s in fin.default_registry() for p in s.writes}
        arm_c = "docs/implementation/r6-successor-dense-full-integration-117/evidence/arm-c/"
        for path in written:
            self.assertFalse(path.startswith(arm_c), path)

    def test_arm_c_authority_split_is_acyclic(self) -> None:
        # the reducer's authority inputs (evidence/arm-c/*) are read by no
        # producer and written by no stage: authority records and derived
        # outputs live on opposite sides of the manifest
        stages = fin.default_registry()
        fin.validate_registry(stages)
        order = fin.topological_order(stages)
        fin.validate_order(stages, order)

    def test_check_mode_is_the_ci_seam(self) -> None:
        # the committed tree must be at the fixed point right now
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts/finalize_repository.py"),
             "--check"], capture_output=True, text=True, cwd=ROOT)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)


if __name__ == "__main__":
    unittest.main()
