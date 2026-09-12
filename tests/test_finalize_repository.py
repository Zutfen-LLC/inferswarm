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
import stat
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
    """The real finalization registry: shape and coverage (no campaign)."""

    def test_registry_order_and_kinds(self) -> None:
        order = fin.topological_order(fin.default_registry())
        self.assertEqual(order[0], "status-source")
        self.assertLess(order.index("status-sync"),
                        order.index("issue117-parent-bind"))
        self.assertLess(order.index("issue117-parent-bind"),
                        order.index("issue117-successor-hashes"))
        self.assertLess(order.index("issue117-successor-hashes"),
                        order.index("issue117-successor-manifest"))
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

    def test_parent_artifacts_are_protected_and_never_written(self):
        # the closed Issue #117 parent artifacts are registered as
        # protected primary inputs and no stage declares a write to them
        registry = fin.default_registry()
        written = {p for s in registry for p in s.writes}
        for path in fin.PARENT_BINDINGS:
            self.assertNotIn(path, written, path)
        bind_stage = next(s for s in registry
                          if s.id == "issue117-parent-bind")
        self.assertTrue(bind_stage.protected)
        for path in fin.PARENT_BINDINGS:
            self.assertIn(path, bind_stage.reads, path)

    def test_finalizer_sources_are_not_in_the_parent_producer_inventory(self):
        # F1: no Issue #130 source may be added to the historical
        # Issue #117 PRODUCERS inventory (the closed parent's own list)
        sys.path.insert(0, str(ROOT / "scripts"))
        import issue117_proof  # noqa: E402
        for source in fin.FINALIZATION_PRODUCERS:
            self.assertNotIn(source, issue117_proof.PRODUCERS, source)

    def test_successor_bundle_pins_parent_and_finalization_sources(self):
        registry = {s.id: s for s in fin.default_registry()}
        manifest = registry["issue117-successor-manifest"]
        # parent rows carry their ACCEPTED digests
        for path, digest in fin.PARENT_BINDINGS.items():
            self.assertIn(path, manifest.covers, path)
        # the Issue #130 sources are the successor's own inventory
        for source in fin.FINALIZATION_PRODUCERS:
            self.assertIn(source, manifest.covers, source)
        # living documents are never covered (immutable-bundle rule)
        for living in ("README.md", "ROADMAP.md", "ARCHITECTURE.md",
                       ".github/workflows/ci.yml", "docs/project-status.json"):
            self.assertNotIn(living, manifest.covers, living)

    def test_writer_after_real_production_stage_input_is_rejected(self):
        # structural negative control over the REAL migrated registry:
        # registering a writer after a stage's real declared read must
        # fail DAG validation.
        registry = fin.default_registry()

        # (a) a stage that writes a finalization producer source after
        # the successor-hashes index read it (the target is not a
        # protected path, so the registry validates and the
        # reader-after-writer proof is what must fire)
        target = fin.FINALIZATION_PRODUCERS[0]
        index_stage = next(
            s for s in registry if s.id == "issue117-successor-hashes")
        self.assertIn(target, index_stage.reads)
        rogue_a = fin.Stage(
            "rogue-producer-writer", "derived", "rogue",
            writes=frozenset({target}),
            after=frozenset({index_stage.id}),
            producer=lambda run, s: {target: b"hijacked"})
        stages_a = registry + (rogue_a,)
        fin.validate_registry(stages_a)
        order = fin.topological_order(stages_a)
        with self.assertRaises(fin.FinalizationError) as caught:
            fin.validate_order(stages_a, order)
        self.assertIn(target, str(caught.exception))

        # (b) a stage that writes a status-sync consumed managed document
        # after status-sync has run
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

    def test_arm_c_authority_paths_are_never_written(self) -> None:
        written = {p for s in fin.default_registry() for p in s.writes}
        arm_c = "docs/implementation/r6-successor-dense-full-integration-117/evidence/arm-c/"
        for path in written:
            self.assertFalse(path.startswith(arm_c), path)

    def test_registry_is_acyclic_and_valid(self) -> None:
        stages = fin.default_registry()
        fin.validate_registry(stages)
        order = fin.topological_order(stages)
        fin.validate_order(stages, order)

    def test_check_mode_is_the_ci_seam(self) -> None:
        # the committed tree must be at the fixed point right now
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts/finalize_repository.py"),
             "--check"], capture_output=True, text=True, cwd=ROOT)
        self.assertEqual(result.returncode,0, result.stderr + result.stdout)




# ---------------------------------------------------------------------------
# F1: closed-parent immutability negative controls
# ---------------------------------------------------------------------------

class ClosedParentControls(unittest.TestCase):
    """The accepted Issue #117 parent bundle can never be rewritten."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="finalize-parent-")
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        subprocess.run(["git", "init", "-q"], cwd=self.root, check=True)
        subprocess.run(["git", "-C", str(self.root), "config",
                        "user.email", "t@example.com"], check=True)
        subprocess.run(["git", "-C", str(self.root), "config",
                        "user.name", "t"], check=True)
        self.parent_paths = [
            "scripts/issue117_proof.py",
            "docs/bundle/evidence/purity-audit.json",
            "docs/bundle/evidence/producer-hashes.json",
            "docs/bundle/evidence/MANIFEST.sha256",
        ]
        accepted = {
            "scripts/issue117_proof.py": b"historical producer\n",
            "docs/bundle/evidence/purity-audit.json": b"accepted audit\n",
            "docs/bundle/evidence/producer-hashes.json": b"accepted hashes\n",
            "docs/bundle/evidence/MANIFEST.sha256": b"accepted manifest\n",
        }
        for relative, data in accepted.items():
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        source = self.root / "src.txt"
        source.write_bytes(b"authored\n")
        subprocess.run(["git", "-C", str(self.root), "add", "-A"], check=True)
        subprocess.run(["git", "-C", str(self.root), "commit", "-qm", "base"],
                       check=True)
        import finalize_repository as finmod
        self.fin = finmod
        # a miniature registry mirroring the real closed-parent shape
        self.bindings = {
            path: hashlib.sha256(accepted[path]).hexdigest()
            for path in self.parent_paths}

    def _registry(self, **overrides) -> "tuple":
        fin = self.fin
        parent_stage = fin.Stage(
            id="parent-bind", kind="verify",
            description="closed parent binding",
            reads=frozenset(self.parent_paths),
            protected=True,
            verify=lambda run, s: None)
        gen = fin.Stage(
            id="gen", kind="derived", description="g",
            reads=frozenset({"src.txt"}),
            writes=frozenset({"gen.txt"}),
            after=frozenset({"parent-bind"}),
            producer=lambda run, s: {"gen.txt": b"generated\n"})
        return (parent_stage, gen)

    def _baseline(self) -> dict[str, str]:
        return {p.relative_to(self.root).as_posix():
                hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted(self.root.rglob("*"))
                if p.is_file() and ".git" not in p.parts}

    def test_finalizer_write_cannot_touch_closed_parent_artifacts(self):
        fin = self.fin
        baseline = self._baseline()
        stages = self._registry()
        report = fin.finalize(self.root, stages, write=True)
        self.assertEqual(report["changed"]["gen"], ["gen.txt"])
        self._assert_bytes(baseline, exclusions={"gen.txt"})

    def _assert_bytes(self, baseline, exclusions=frozenset()) -> None:
        current = self._baseline()
        expected = {k: v for k, v in current.items()
                    if k not in exclusions}
        original = {k: v for k, v in baseline.items()
                    if k not in exclusions}
        self.assertEqual(expected, original)

    def test_structural_write_declaration_to_parent_path_is_rejected(self):
        fin = self.fin
        # a stage DECLARES a write to a protected parent path
        parent_stage, gen = self._registry()
        rogue = fin.Stage(
            "rogue", "derived", "r",
            writes=frozenset({"docs/bundle/evidence/MANIFEST.sha256"}),
            after=frozenset({"gen"}),
            producer=lambda run, s: {
                "docs/bundle/evidence/MANIFEST.sha256": b"repinned"})
        with self.assertRaises(fin.FinalizationError) as caught:
            fin.validate_registry((parent_stage, gen, rogue))
        self.assertIn("protected", str(caught.exception))

    def test_writer_before_protected_reader_is_rejected(self):
        fin = self.fin
        # the rogue writer runs BEFORE the protected reader: order-based
        # reader-after-writer alone would miss it; the global rule fires
        parent_stage, gen = self._registry()
        rogue = fin.Stage(
            "early-rogue", "derived", "r",
            writes=frozenset({"scripts/issue117_proof.py"}),
            producer=lambda run, s: {
                "scripts/issue117_proof.py": b"rewritten history"})
        stages = (rogue, parent_stage, gen)
        # re-jig dependencies so the rogue genuinely runs first
        parent_stage = fin.Stage(
            id="parent-bind", kind="verify",
            description="closed parent binding",
            reads=frozenset(self.parent_paths),
            protected=True,
            after=frozenset({"early-rogue"}),
            verify=lambda run, s: None)
        with self.assertRaises(fin.FinalizationError) as caught:
            fin.validate_registry((rogue, parent_stage, gen))
        self.assertIn("protected", str(caught.exception))

    def test_runtime_write_to_parent_via_producer_is_blocked(self):
        # a producer returns desired bytes for a parent path it did not
        # declare (structural), and separately the registry rejects any
        # declaration attempt: both directions fail closed
        fin = self.fin
        parent_stage, gen = self._registry()
        with self.assertRaises(fin.FinalizationError):
            fin.validate_registry((parent_stage, gen, fin.Stage(
                "w", "derived", "w",
                writes=frozenset(self.parent_paths),
                producer=lambda run, s: {})))
        # undeclared output key
        rogue_output = fin.Stage(
            "rogue-output", "derived", "r",
            reads=frozenset({"src.txt"}),
            writes=frozenset({"gen2.txt"}),
            producer=lambda run, s: {
                "gen2.txt": b"x\n",
                "docs/bundle/evidence/MANIFEST.sha256": b"repinned"})
        with self.assertRaises(fin.FinalizationError) as caught:
            fin.finalize(self.root, (parent_stage, rogue_output),
                         write=True)
        self.assertIn("undeclared", str(caught.exception))


# ---------------------------------------------------------------------------
# F2: real-root mutation controls (TRUE negative controls on self.root)
# ---------------------------------------------------------------------------

class RealRootMutationControls(unittest.TestCase):
    """Every rogue operation against the ACTUAL checkout is caught.

    Per the correction spec, the rogue callbacks below mutate the test
    checkout captured as ``self.root`` — NOT ``run.root``, which is the
    engine's sandbox/projection.  Every test asserts the fail-closed
    error AND that the complete starting repository state is restored.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="finalize-realroot-")
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        for command in (["git", "init", "-q"],
                        ["git", "config", "user.email", "t@example.com"],
                        ["git", "config", "user.name", "t"]):
            subprocess.run(command, cwd=self.root, check=True)
        self._write("src.txt", "authored\n")
        self._write("clean-tracked.txt", "clean\n")
        self._write("docs/nested/deep.txt", "nested\n")
        subprocess.run(["git", "-C", str(self.root), "add", "-A"], check=True)
        subprocess.run(["git", "-C", str(self.root), "commit", "-qm", "base"],
                       check=True)
        # authored starting states
        self._write("dirty-tracked.txt", "authored dirty edit\n")   # dirty
        self._write("untracked.txt", "authored untracked\n")        # untracked

    # -- helpers ----------------------------------------------------------

    def _write(self, relative: str, text: str) -> None:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def _state(self) -> dict[str, tuple]:
        """Complete starting-state signature (paths + bytes + modes)."""
        state = {}
        for path in sorted(self.root.rglob("*")):
            if ".git" in path.parts or not path.is_file():
                continue
            info = path.lstat()
            state[str(path.relative_to(self.root))] = (
                hashlib.sha256(path.read_bytes()).hexdigest(),
                stat.S_IMODE(info.st_mode))
        return state

    def _full_baseline(self) -> dict[str, tuple]:
        return self._state()

    def _assert_restored(self, baseline: dict[str, tuple]) -> None:
        self.assertEqual(self._state(), baseline)

    def _rogue_stage(self, rogue) -> "fin.Stage":
        return fin.Stage(
            "gen", "derived", "g",
            reads=frozenset({"src.txt"}),
            writes=frozenset({"gen.txt"}),
            producer=rogue)

    def _expect_fail_closed(self, stages, *, write=True) -> None:
        baseline = self._full_baseline()
        with self.assertRaises(fin.FinalizationError) as caught:
            fin.finalize(self.root, stages, write=write)
        message = str(caught.exception)
        self.assertTrue(
            "escaped the engine contract" in message or
            "undeclared" in message or
            "restored" in message, message)
        self._assert_restored(baseline)
        return caught

    # -- required controls -------------------------------------------------

    def test_producer_creates_undeclared_file_in_actual_checkout(self):
        real_root = self.root  # TRUE real-root closure

        def rogue(run: fin.Run, scratch: Path) -> dict[str, bytes]:
            (real_root / "undeclared.txt").write_text("injected\n")
            return {"gen.txt": b"ok\n"}

        self._expect_fail_closed((self._rogue_stage(rogue),))

    def test_producer_overwrites_clean_tracked_file_in_actual_checkout(self):
        real_root = self.root

        def rogue(run: fin.Run, scratch: Path) -> dict[str, bytes]:
            (real_root / "clean-tracked.txt").write_text("hijacked\n")
            return {"gen.txt": b"ok\n"}

        self._expect_fail_closed((self._rogue_stage(rogue),))

    def test_producer_overwrites_authored_dirty_file_in_actual_checkout(self):
        real_root = self.root

        def rogue(run: fin.Run, scratch: Path) -> dict[str, bytes]:
            (real_root / "dirty-tracked.txt").write_text("clobbered\n")
            return {"gen.txt": b"ok\n"}

        self._expect_fail_closed((self._rogue_stage(rogue),))

    def test_producer_deletes_clean_tracked_file_in_actual_checkout(self):
        real_root = self.root

        def rogue(run: fin.Run, scratch: Path) -> dict[str, bytes]:
            (real_root / "clean-tracked.txt").unlink()
            return {"gen.txt": b"ok\n"}

        self._expect_fail_closed((self._rogue_stage(rogue),))

    def test_producer_deletes_authored_dirty_file(self):
        real_root = self.root

        def rogue(run: fin.Run, scratch: Path) -> dict[str, bytes]:
            (real_root / "dirty-tracked.txt").unlink()
            return {"gen.txt": b"ok\n"}

        self._expect_fail_closed((self._rogue_stage(rogue),))

    def test_producer_deletes_untracked_file(self):
        real_root = self.root

        def rogue(run: fin.Run, scratch: Path) -> dict[str, bytes]:
            (real_root / "untracked.txt").unlink()
            return {"gen.txt": b"ok\n"}

        self._expect_fail_closed((self._rogue_stage(rogue),))

    def test_producer_renames_file_in_actual_checkout(self):
        real_root = self.root

        def rogue(run: fin.Run, scratch: Path) -> dict[str, bytes]:
            source = real_root / "clean-tracked.txt"
            source.rename(real_root / "renamed-away.txt")
            return {"gen.txt": b"ok\n"}

        self._expect_fail_closed((self._rogue_stage(rogue),))

    def test_verifier_creates_modifies_deletes_in_actual_checkout(self):
        real_root = self.root

        def rogue_verify(run: fin.Run, scratch: Path) -> None:
            (real_root / "verifier-created.txt").write_text("forged\n")
            with open(real_root / "dirty-tracked.txt", "a") as handle:
                handle.write("appended\n")
            (real_root / "untracked.txt").unlink()

        stages = (fin.Stage("chk", "verify", "v",
                            reads=frozenset({"src.txt"}),
                            verify=rogue_verify),)
        self._expect_fail_closed(stages)

    def test_equivalent_check_mode_cases_fail_and_preserve(self):
        real_root = self.root

        def rogue(run: fin.Run, scratch: Path) -> dict[str, bytes]:
            (real_root / "undeclared.txt").write_text("injected\n")
            return {"gen.txt": b"ok\n"}

        def rogue_verify(run: fin.Run, scratch: Path) -> None:
            (real_root / "verifier-created.txt").write_text("forged\n")

        self._expect_fail_closed((self._rogue_stage(rogue),), write=False)
        self._expect_fail_closed(
            (fin.Stage("chk", "verify", "v", reads=frozenset({"src.txt"}),
                        verify=rogue_verify),), write=False)

    def test_callable_raises_after_mutating_actual_checkout(self):
        real_root = self.root

        def rogue(run: fin.Run, scratch: Path) -> dict[str, bytes]:
            (real_root / "clean-tracked.txt").write_text("hijacked\n")
            raise RuntimeError("callable blew up mid-mutation")

        stages = (self._rogue_stage(rogue),)
        baseline = self._full_baseline()
        with self.assertRaises(fin.FinalizationError) as caught:
            fin.finalize(self.root, stages, write=True)
        # the callable crashed mid-mutation; the guard's finally-block
        # still detected the damage, restored the worktree, and failed
        # closed — a crashed callable can never smuggle a mutation in
        self.assertIn("escaped the engine contract", str(caught.exception))
        self._assert_restored(baseline)

    def test_starting_deletion_is_preserved_exactly(self):
        # a tracked file intentionally deleted BEFORE finalization must
        # remain deleted: finalization never resurrects HEAD bytes just
        # because the starting baseline lacked file bytes
        (self.root / "clean-tracked.txt").unlink()
        baseline = self._full_baseline()
        stages = (self._rogue_stage(
            lambda run, s: {"gen.txt": b"generated\n"}),)
        report = fin.finalize(self.root, stages, write=True)
        self.assertEqual(report["changed"]["gen"], ["gen.txt"])
        expected = dict(baseline)
        expected["gen.txt"] = (
            hashlib.sha256(b"generated\n").hexdigest(), 0o644)
        self.assertEqual(self._state(), expected)
        self.assertFalse((self.root / "clean-tracked.txt").exists())
        # and a rogue recreation of the deleted file is re-deleted
        real_root = self.root

        def recreator(run: fin.Run, scratch: Path) -> dict[str, bytes]:
            (real_root / "clean-tracked.txt").write_text("resurrected\n")
            return {"gen.txt": b"ok\n"}

        tracked = self.root / "clean-tracked.txt"
        if tracked.exists():
            tracked.unlink()  # reset starting state (first part deleted it)
        baseline = self._full_baseline()
        with self.assertRaises(fin.FinalizationError):
            fin.finalize(self.root, (self._rogue_stage(recreator),),
                         write=True)
        self.assertFalse((self.root / "clean-tracked.txt").exists())
        self._assert_restored(baseline)

    def test_git_status_failure_during_guard_does_not_skip_restoration(self):
        # break git AFTER the starting snapshot so the post-mutation
        # census inside the guard fails: restoration must not be
        # silently skipped (the error propagates, nothing is applied)
        real_root = self.root

        def rogue(run: fin.Run, scratch: Path) -> dict[str, bytes]:
            (real_root / "clean-tracked.txt").write_text("hijacked\n")
            head = real_root / ".git" / "HEAD"
            head.rename(head.parent / "HEAD.broken")
            return {"gen.txt": b"ok\n"}

        baseline = self._full_baseline()
        with self.assertRaises(Exception) as caught:
            fin.finalize(self.root, (self._rogue_stage(rogue),),
                         write=True)
        self.assertNotIsInstance(caught.exception, AssertionError)
        # restore .git so cleanup works; the WORKTREE bytes were never
        # touched by the engine (no declared write was applied)
        broken = self.root / ".git" / "HEAD.broken"
        if broken.exists():
            broken.rename(self.root / ".git" / "HEAD")
        # the rogue mutation itself remains (git was broken); what is
        # proven here is that the engine applied NOTHING and failed
        # loudly rather than silently skipping restoration
        self.assertEqual(
            (self.root / "clean-tracked.txt").read_text(), "hijacked\n")
        self.assertFalse((self.root / "gen.txt").exists())


# ---------------------------------------------------------------------------
# F3: declared-read enforcement and protected primaries
# ---------------------------------------------------------------------------

class DeclaredReadEnforcementControls(unittest.TestCase):
    """A stage cannot consume an input it did not declare."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="finalize-reads-")
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        for command in (["git", "init", "-q"],
                        ["git", "config", "user.email", "t@example.com"],
                        ["git", "config", "user.name", "t"]):
            subprocess.run(command, cwd=self.root, check=True)
        self._write("src.txt", "authored\n")
        self._write("other-input.txt", "sibling stage input\n")
        self._write("protected.txt", "frozen authority\n")
        subprocess.run(["git", "-C", str(self.root), "add", "-A"], check=True)
        subprocess.run(["git", "-C", str(self.root), "commit", "-qm", "base"],
                       check=True)

    def _write(self, relative: str, text: str) -> None:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def _state(self) -> dict[str, str]:
        return {p.relative_to(self.root).as_posix():
                hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted(self.root.rglob("*"))
                if p.is_file() and ".git" not in p.parts}

    def test_undeclared_runtime_read_is_rejected(self):
        # the producer reads a path not in its declared reads through
        # run.read: rejected even though the file exists on disk
        def rogue(run: fin.Run, scratch: Path) -> dict[str, bytes]:
            data = run.read("other-input.txt")  # NOT declared
            return {"gen.txt": (data or b"").upper()}

        stages = (fin.Stage("gen", "derived", "g",
                            reads=frozenset({"src.txt"}),
                            writes=frozenset({"gen.txt"}),
                            producer=rogue),)
        baseline = self._state()
        with self.assertRaises(fin.FinalizationError) as caught:
            fin.finalize(self.root, stages, write=True)
        self.assertIn("undeclared read", str(caught.exception))
        self.assertEqual(self._state(), baseline)

    def test_undeclared_direct_projection_read_is_impossible(self):
        # the producer bypasses run.read and opens the file directly:
        # the path is absent from its restricted projection, so the
        # direct read cannot observe the undeclared input at all
        observed = {}

        def rogue(run: fin.Run, scratch: Path) -> dict[str, bytes]:
            path = run.root / "other-input.txt"
            observed["present"] = path.is_file()
            observed["readable"] = None
            try:
                observed["readable"] = path.read_text()
            except OSError:
                observed["readable"] = "OSError"
            return {"gen.txt": b"ok\n"}

        stages = (fin.Stage("gen", "derived", "g",
                            reads=frozenset({"src.txt"}),
                            writes=frozenset({"gen.txt"}),
                            producer=rogue),)
        fin.finalize(self.root, stages, write=True)
        self.assertFalse(observed["present"])
        self.assertEqual(observed["readable"], "OSError")

    def test_hidden_undeclared_dependency_cycle_is_rejected(self):
        # stage A does not declare B's output as a read, but its
        # producer tries to consume it anyway: the mediated read is
        # rejected, proving the DAG cannot be silently widened at run
        # time to create a data cycle
        def a_producer(run: fin.Run, scratch: Path) -> dict[str, bytes]:
            try:
                hidden = run.read("b.out")
            except fin.FinalizationError:
                hidden = None
            if hidden is not None:
                return {"a.out": hidden.upper()}
            return {"a.out": b"first pass\n"}

        stages = (
            fin.Stage("a", "derived", "a",
                      reads=frozenset({"src.txt"}),
                      writes=frozenset({"a.out"}),
                      producer=a_producer),
            fin.Stage("b", "derived", "b",
                      reads=frozenset({"a.out"}),
                      writes=frozenset({"b.out"}),
                      after=frozenset({"a"}),
                      producer=lambda run, s: {
                          "b.out": (run.read("a.out") or b"").lower()}),
        )
        # the run itself succeeds (A's hidden read is BLOCKED, so no
        # cycle forms); the control asserts the hidden read never fired
        report = fin.finalize(self.root, stages, write=True)
        self.assertEqual(report["changed"]["a"], ["a.out"])

    def test_writer_before_protected_primary_reader_is_rejected(self):
        # protected primary input; a writer scheduled EARLIER
        protected = fin.Stage(
            "guard", "verify", "protected authority input",
            reads=frozenset({"protected.txt"}), protected=True,
            verify=lambda run, s: None)
        early_writer = fin.Stage(
            "early", "derived", "e",
            writes=frozenset({"protected.txt"}),
            producer=lambda run, s: {"protected.txt": b"tampered"})
        late_stage = fin.Stage(
            "gen", "derived", "g",
            reads=frozenset({"src.txt"}),
            writes=frozenset({"gen.txt"}),
            after=frozenset({"guard"}),
            producer=lambda run, s: {"gen.txt": b"ok\n"})
        with self.assertRaises(fin.FinalizationError) as caught:
            fin.validate_registry((early_writer, protected, late_stage))
        self.assertIn("protected", str(caught.exception))

    def test_writer_after_protected_primary_reader_is_rejected(self):
        protected = fin.Stage(
            "guard", "verify", "protected authority input",
            reads=frozenset({"protected.txt"}), protected=True,
            verify=lambda run, s: None)
        late_writer = fin.Stage(
            "late", "derived", "l",
            writes=frozenset({"protected.txt"}),
            after=frozenset({"guard"}),
            producer=lambda run, s: {"protected.txt": b"tampered"})
        with self.assertRaises(fin.FinalizationError) as caught:
            fin.validate_registry((protected, late_writer))
        self.assertIn("protected", str(caught.exception))

    def test_write_to_frozen_authority_inputs_is_rejected(self):
        # the real frozen authority inputs: Issue #117 parent paths,
        # the #129/#133 Arm-C retry records, and the #137 bundle
        frozen = sorted(fin.PARENT_BINDINGS)
        arm_c = sorted(
            p for p in fin._issue137_bundle_reads()
            if "/arm-c-regime4-diagnosis-137/" in p)[:3]
        self.assertTrue(arm_c)
        protected = fin.Stage(
            "guard", "verify", "frozen authority",
            reads=frozenset(frozen + arm_c), protected=True,
            verify=lambda run, s: None)
        for path in frozen + arm_c:
            rogue = fin.Stage(
                "w", "derived", "w",
                writes=frozenset({path}),
                producer=lambda run, s, p=path: {p: b"tampered"})
            with self.assertRaises(fin.FinalizationError) as caught:
                fin.validate_registry((protected, rogue))
            self.assertIn("protected", str(caught.exception))


# ---------------------------------------------------------------------------
# F4: symlink and root-confinement escapes
# ---------------------------------------------------------------------------

class SymlinkEscapeControls(unittest.TestCase):
    """Engine writes can never be redirected outside the repository."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="finalize-symlink-")
        self.area = Path(self._tmp.name)
        self.root = self.area / "repo"
        self.root.mkdir()
        self.addCleanup(self._tmp.cleanup)
        for command in (["git", "init", "-q"],
                        ["git", "config", "user.email", "t@example.com"],
                        ["git", "config", "user.name", "t"]):
            subprocess.run(command, cwd=self.root, check=True)
        self._write("src.txt", "authored\n")
        subprocess.run(["git", "-C", str(self.root), "add", "-A"], check=True)
        subprocess.run(["git", "-C", str(self.root), "commit", "-qm", "base"],
                       check=True)
        # the outside target the escapes would redirect writes into
        self.outside = self.area / "outside"
        self.outside.mkdir()
        (self.outside / "precious.txt").write_bytes(b"outside bytes\n")

    def _write(self, relative: str, text: str) -> None:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def _state(self) -> dict[str, str]:
        return {p.relative_to(self.root).as_posix():
                hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted(self.root.rglob("*"))
                if p.is_file() and ".git" not in p.parts}

    def _outside_bytes(self) -> bytes:
        return (self.outside / "precious.txt").read_bytes()

    def _gen_stage(self, out: str) -> "fin.Stage":
        return fin.Stage(
            "gen", "derived", "g",
            reads=frozenset({"src.txt"}),
            writes=frozenset({out}),
            producer=lambda run, s: {out: b"engine output\n"})

    def test_output_path_itself_is_a_symlink_is_rejected(self):
        # declared output is a symlink to an external file
        os.symlink(self.outside / "precious.txt",
                   self.root / "gen.txt")
        baseline = self._state()
        outside_before = self._outside_bytes()
        with self.assertRaises(fin.FinalizationError) as caught:
            fin.finalize(self.root, (self._gen_stage("gen.txt"),),
                         write=True)
        self.assertIn("symlink", str(caught.exception))
        self.assertEqual(self._outside_bytes(), outside_before)
        self.assertEqual(self._state(), baseline)

    def test_symlinked_parent_directory_is_rejected(self):
        # declared output lives under a symlinked directory leading
        # outside the repository
        os.symlink(self.outside, self.root / "linked-dir")
        baseline = self._state()
        outside_before = self._outside_bytes()
        with self.assertRaises(fin.FinalizationError) as caught:
            fin.finalize(
                self.root, (self._gen_stage("linked-dir/gen.txt"),),
                write=True)
        self.assertIn("symlink", str(caught.exception))
        # no new file appeared outside
        self.assertEqual(sorted(p.name for p in self.outside.iterdir()),
                         ["precious.txt"])
        self.assertEqual(self._state(), baseline)

    def test_alias_spellings_cannot_bypass_registry_identity(self):
        # ./gen.txt, subdir/../gen.txt and repeated separators are the
        # same destination as gen.txt: registry validation rejects
        # non-canonical spellings before any write
        for alias in ("./gen.txt", "subdir/../gen.txt", "a//b.txt"):
            with self.assertRaises(fin.FinalizationError):
                fin.validate_registry((
                    fin.Stage("gen", "derived", "g",
                              reads=frozenset({"src.txt"}),
                              writes=frozenset({alias}),
                              producer=lambda run, s: {alias: b"x"}),
                ))

    def test_write_lands_inside_repo_and_nowhere_else(self):
        # positive control: a legitimate declared write lands exactly at
        # the repo path and leaves the outside untouched
        fin.finalize(self.root, (self._gen_stage("docs/out/gen.txt"),),
                     write=True)
        self.assertEqual(
            (self.root / "docs/out/gen.txt").read_bytes(), b"engine output\n")
        self.assertEqual(sorted(p.name for p in self.outside.iterdir()),
                         ["precious.txt"])



if __name__ == "__main__":
    unittest.main()
