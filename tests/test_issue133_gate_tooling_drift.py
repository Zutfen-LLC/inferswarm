"""Issue #133 corrected freeze — pre-execution gate-tooling mutation
controls (maintainer review 5166773760).

These tests prove the PRE-EXECUTION GATE itself fails closed when the
authority/freeze are unchanged but the EXECUTING GATE TOOLING drifts:

- DRY-RUN MUTATION: one byte changed in
  scripts/issue133_real_builder_dry_run.py, authority/freeze untouched
  => the gate rejects BEFORE the dry run executes;
- CANONICAL-ENVIRONMENT MUTATION: one correctness-bearing byte changed
  in scripts/issue133_canonical_environment.py => the gate rejects;
- DIRECT-DRIVER MUTATION: the working-tree direct driver drifts while
  the frozen driver identity is unchanged => the gate rejects before
  the modified module is used;
- ACCEPTED-METHODOLOGY DEPENDENCY MUTATION: issue129_arm_c_retry_core.py
  and issue117_arm_c_frozen_pins.py (dynamically consumed by the gate)
  mutate => the gate rejects before trusting them;
- SELF mutation: the campaign/gate module itself drifts => rejects;
- symlink / missing gate tooling => rejects;
- LATER-MAIN CONTROLS: an accepted authority commit plus a later
  UNRELATED accepted commit with the gate closure byte-identical is
  ALLOWED; a later accepted commit changing a gate dependency byte is
  REJECTED;
- FREEZE-VS-CODE MISMATCH: the executing module's expected r5a or
  environment identity differing from the authority-bound freeze
  record => the gate rejects.

Every gate invocation runs in a SUBPROCESS with a fresh interpreter and
a fresh sys.modules; scratch-repository mutation can never be masked by
Python module caching. CPU-only: no GPU, no model execution, no
participant-state mutation (the real-builder path builds plans only).
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AUTHORITY_REL = Path(
    "docs/implementation/r6-successor-dense-full-integration-117"
    "/evidence/arm-c-retry/physical-campaign-authority.json")
FREEZE_REL = Path(
    "docs/implementation/r6-successor-dense-full-integration-117"
    "/evidence/arm-c-retry/execution-freeze.json")

#: the probe executed inside every scratch repository: import the
#: (possibly mutated) campaign module fresh and run the FULL gate
_GATE_PROBE = '''
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent / "scripts"))
import issue133_arm_c_retry_campaign as camp
try:
    verdict = camp.verify_pre_execution_authority_gate()
except RuntimeError as error:
    print("GATE_REJECT:", error)
    raise SystemExit(17)
print("GATE_PASS", verdict["schema"], verdict["accepted_authority_commit"])
'''

#: probe for the freeze-vs-code seam (no accepted-history needed)
_DRY_RUN_PROBE = '''
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent / "scripts"))
import issue133_arm_c_retry_campaign as camp
try:
    verdict = camp.verify_real_builder_dry_run()
except RuntimeError as error:
    print("DRY_RUN_REJECT:", error)
    raise SystemExit(17)
print("DRY_RUN_PASS", verdict["digest"])
'''


def _git(repo: Path, *args: str, env: dict) -> "subprocess.CompletedProcess[str]":
    return subprocess.run(
        ["git", "-C", str(repo), *args], stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True, env=env, check=True)


class _ScratchFixture:
    """An accepted-history scratch repository: base commit carrying the
    gate tooling + retained evidence (EXCLUDING the authority document),
    then an authority commit, with refs/remotes/origin/main pointing at
    it — the minimum accepted history in which the full pre-execution
    gate can pass."""

    def __init__(self, tmp: str):
        self.tmp = Path(tmp)
        self.repo = self.tmp / "repo"
        self.repo.mkdir()
        shutil.copytree(ROOT / "scripts", self.repo / "scripts",
                        ignore=shutil.ignore_patterns("__pycache__"))
        area = ROOT / "docs/implementation"
        shutil.copytree(
            area / "r6-successor-dense-full-integration-117",
            self.repo / "docs/implementation"
            / "r6-successor-dense-full-integration-117",
            ignore=shutil.ignore_patterns(
                "__pycache__", AUTHORITY_REL.name))
        (self.repo / "_issue133_gate_probe.py").write_text(_GATE_PROBE)
        (self.repo / "_issue133_dry_run_probe.py").write_text(_DRY_RUN_PROBE)
        self.env = dict(
            os.environ,
            GIT_AUTHOR_NAME="Issue 133 Mutation Control",
            GIT_AUTHOR_EMAIL="issue133-mutation@example.invalid",
            GIT_COMMITTER_NAME="Issue 133 Mutation Control",
            GIT_COMMITTER_EMAIL="issue133-mutation@example.invalid",
            HOME=os.environ.get("HOME", str(self.tmp)))
        _git(self.repo, "init", "-q", env=self.env)
        marker = self.repo / "README.marker"
        marker.write_text("scratch fixture\n")
        _git(self.repo, "add", "README.marker", env=self.env)
        _git(self.repo, "add", "scripts", env=self.env)
        _git(self.repo, "add", "docs", env=self.env)
        _git(self.repo, "commit", "-q", "-m", "scratch base", env=self.env)
        # the authority document lands ONLY here, so the accepted
        # authority commit is unambiguous
        shutil.copy2(ROOT / AUTHORITY_REL, self.repo / AUTHORITY_REL)
        _git(self.repo, "add", str(AUTHORITY_REL), env=self.env)
        _git(self.repo, "commit", "-q", "-m", "authority", env=self.env)
        self.authority_commit = subprocess.run(
            ["git", "-C", str(self.repo), "rev-parse", "HEAD"],
            capture_output=True, text=True, env=self.env,
            check=True).stdout.strip()
        _git(self.repo, "update-ref", "refs/remotes/origin/main",
             self.authority_commit, env=self.env)

    # -- mutations ----------------------------------------------------
    def mutate_byte(self, relative: str, anchor: str,
                    replacement: str) -> None:
        """Change exactly the anchored bytes in the scratch working tree
        (uncommitted drift against the accepted authority commit)."""
        path = self.repo / relative
        text = path.read_text()
        assert anchor in text, f"anchor missing in {relative}"
        path.write_text(text.replace(anchor, replacement, 1))

    def commit_later(self, relative: str | None, message: str) -> str:
        """A LATER accepted commit (origin/main advanced); optionally
        committing a mutated gate file so the drift is accepted history
        rather than working-tree-only."""
        if relative is not None:
            _git(self.repo, "add", relative, env=self.env)
        else:
            (self.repo / "README.marker").write_text(
                "later unrelated accepted commit\n")
            _git(self.repo, "add", "README.marker", env=self.env)
        _git(self.repo, "commit", "-q", "-m", message, env=self.env)
        head = subprocess.run(
            ["git", "-C", str(self.repo), "rev-parse", "HEAD"],
            capture_output=True, text=True, env=self.env,
            check=True).stdout.strip()
        _git(self.repo, "update-ref", "refs/remotes/origin/main", head,
             env=self.env)
        return head

    # -- subprocess probes ---------------------------------------------
    def run_gate_probe(self) -> "subprocess.CompletedProcess[str]":
        return subprocess.run(
            [sys.executable, str(self.repo / "_issue133_gate_probe.py")],
            cwd=str(self.repo), capture_output=True, text=True,
            env=self.env)

    def run_dry_run_probe(self) -> "subprocess.CompletedProcess[str]":
        return subprocess.run(
            [sys.executable, str(self.repo / "_issue133_dry_run_probe.py")],
            cwd=str(self.repo), capture_output=True, text=True,
            env=self.env)

    def rewrite_freeze_field(self, mutate) -> None:
        """Rewrite the retained freeze record with `mutate(record)`
        applied, preserving the canonical encoding."""
        path = self.repo / FREEZE_REL
        record = json.loads(path.read_text())
        mutate(record)
        path.write_text(
            json.dumps(record, indent=2, sort_keys=True) + "\n")


class GateToolingMutationControlTests(unittest.TestCase):
    """The gate must reject gate-tooling drift BEFORE the dry run —
    with authority/freeze bytes unchanged. Every case runs the FULL
    gate in a fresh subprocess against a fresh accepted-history
    scratch repository."""

    def _assert_rejects_before_dry_run(self, fixture, output: str) -> None:
        # the closure rejects before dynamically importing/executing
        # the dry run: the rejection names the closure, and the mutated
        # bytes are inert (a comment/docstring byte the dry run would
        # happily execute), so only the pre-import byte binding can
        # have produced this rejection.
        self.assertIn("gate-tooling closure FAILED", output)

    def test_control_passing_gate_in_accepted_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = _ScratchFixture(tmp)
            result = fixture.run_gate_probe()
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("GATE_PASS", result.stdout)
            self.assertIn("inferswarm.issue133.pre-execution-gate/3",
                          result.stdout)
            self.assertIn(fixture.authority_commit, result.stdout)

    def test_control_dry_run_single_byte_mutation_rejects(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = _ScratchFixture(tmp)
            fixture.mutate_byte(
                "scripts/issue133_real_builder_dry_run.py",
                "Executes the ACTUAL frozen producer planning/build path",
                "Executes the ACTUAL frozen producer planning/build pat#")
            result = fixture.run_gate_probe()
            self.assertEqual(result.returncode, 17, result.stderr)
            self._assert_rejects_before_dry_run(fixture, result.stdout)
            self.assertIn("issue133_real_builder_dry_run.py", result.stdout)
            self.assertIn("byte drift", result.stdout)

    def test_control_canonical_environment_mutation_rejects(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = _ScratchFixture(tmp)
            # a correctness-bearing byte: the environment document family
            fixture.mutate_byte(
                "scripts/issue133_canonical_environment.py",
                'ENVIRONMENT_SCHEMA = "inferswarm.r6.environment-freeze/1"',
                'ENVIRONMENT_SCHEMA = "inferswarm.r6.environment-freeze/2"')
            result = fixture.run_gate_probe()
            self.assertEqual(result.returncode, 17, result.stderr)
            self._assert_rejects_before_dry_run(fixture, result.stdout)
            self.assertIn("issue133_canonical_environment.py", result.stdout)

    def test_control_direct_driver_mutation_rejects(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = _ScratchFixture(tmp)
            fixture.mutate_byte(
                "scripts/issue133_arm_c_retry_direct.py",
                "ARM_C_RETRY_DIRECT_FAIL: plan-family conflation",
                "ARM_C_RETRY_DIRECT_FAIL: plan-family conflamatio")
            result = fixture.run_gate_probe()
            self.assertEqual(result.returncode, 17, result.stderr)
            self._assert_rejects_before_dry_run(fixture, result.stdout)
            self.assertIn("issue133_arm_c_retry_direct.py", result.stdout)

    def test_control_129_core_mutation_rejects(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = _ScratchFixture(tmp)
            # an inert docstring byte the core still imports fine —
            # only the closure's byte binding can catch it
            fixture.mutate_byte(
                "scripts/issue129_arm_c_retry_core.py",
                "locally by scripts/issue129_arm_c_retry_core.py",
                "locally by scripts/issue129_arm_c_retry_core.p#")
            result = fixture.run_gate_probe()
            self.assertEqual(result.returncode, 17, result.stderr)
            self._assert_rejects_before_dry_run(fixture, result.stdout)
            self.assertIn("issue129_arm_c_retry_core.py", result.stdout)

    def test_control_frozen_pins_mutation_rejects(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = _ScratchFixture(tmp)
            fixture.mutate_byte(
                "scripts/issue117_arm_c_frozen_pins.py",
                "import hashlib",
                "import hashl#b")
            result = fixture.run_gate_probe()
            self.assertEqual(result.returncode, 17, result.stderr)
            self._assert_rejects_before_dry_run(fixture, result.stdout)
            self.assertIn("issue117_arm_c_frozen_pins.py", result.stdout)

    def test_control_gate_module_self_mutation_rejects(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = _ScratchFixture(tmp)
            fixture.mutate_byte(
                "scripts/issue133_arm_c_retry_campaign.py",
                "PRE-EXECUTION GATE-TOOLING CLOSURE",
                "PRE-EXECUTION GATE-TOOLING CLOSUR#")
            result = fixture.run_gate_probe()
            self.assertEqual(result.returncode, 17, result.stderr)
            # the (mutated) gate module still rejects ITS OWN drift
            # against the accepted authority commit
            self.assertIn("gate-tooling closure FAILED", result.stdout)
            self.assertIn("issue133_arm_c_retry_campaign.py", result.stdout)

    def test_control_symlinked_gate_tool_rejects(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = _ScratchFixture(tmp)
            target = fixture.repo / "scripts" / "issue133_real_builder_dry_run.py"
            real = target.with_suffix(".real.py")
            target.rename(real)
            target.symlink_to(real)
            result = fixture.run_gate_probe()
            self.assertEqual(result.returncode, 17, result.stderr)
            self.assertIn("not a regular non-symlink", result.stdout)

    def test_control_missing_gate_tool_rejects(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = _ScratchFixture(tmp)
            (fixture.repo / "scripts" / "issue133_canonical_environment.py").unlink()
            result = fixture.run_gate_probe()
            self.assertEqual(result.returncode, 17, result.stderr)
            self.assertIn("not a regular non-symlink working-tree file",
                          result.stdout)


class LaterMainControlTests(unittest.TestCase):
    """Later accepted history is compatible ONLY while every gate byte
    stays identical to the accepted authority commit."""

    def test_later_unrelated_commit_with_closure_unchanged_allowed(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = _ScratchFixture(tmp)
            later = fixture.commit_later(
                None, "later unrelated accepted commit")
            result = fixture.run_gate_probe()
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("GATE_PASS", result.stdout)
            # the accepted AUTHORITY commit (not the later commit) is
            # the trust anchor the closure is bound against
            self.assertIn(fixture.authority_commit, result.stdout)
            self.assertNotIn(later, result.stdout.split("GATE_PASS")[-1])

    def test_later_commit_changing_gate_dependency_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = _ScratchFixture(tmp)
            fixture.mutate_byte(
                "scripts/issue133_canonical_environment.py",
                'ENVIRONMENT_SCHEMA = "inferswarm.r6.environment-freeze/1"',
                'ENVIRONMENT_SCHEMA = "inferswarm.r6.environment-freeze/2"')
            fixture.commit_later(
                "scripts/issue133_canonical_environment.py",
                "later commit changing a gate dependency")
            # working tree == later accepted main; yet the gate rejects:
            # the closure is bound to the accepted AUTHORITY commit
            result = fixture.run_gate_probe()
            self.assertEqual(result.returncode, 17, result.stderr)
            self.assertIn("gate-tooling closure FAILED", result.stdout)
            self.assertIn("issue133_canonical_environment.py", result.stdout)
            self.assertIn("byte drift", result.stdout)


class FreezeVsCodeMismatchTests(unittest.TestCase):
    """The dry-run verdict is bound to the authority-bound freeze
    record's own values; a module constant or freeze value that
    disagrees with the other side fails closed."""

    def test_control_freeze_r5a_digest_drift_rejects(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = _ScratchFixture(tmp)
            def mutate(record):
                digest = record["r5a_static_plan_digest"]
                record["r5a_static_plan_digest"] = (
                    digest[:10] + ("0" if digest[10] != "0" else "1")
                    + digest[11:])
            fixture.rewrite_freeze_field(mutate)
            result = fixture.run_dry_run_probe()
            self.assertEqual(result.returncode, 17, result.stderr)
            self.assertIn("authority-bound freeze record", result.stdout)

    def test_control_module_r5a_constant_drift_rejects(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = _ScratchFixture(tmp)
            fixture.mutate_byte(
                "scripts/issue133_arm_c_retry_campaign.py",
                'AUTHORIZED_R5A_STATIC_PLAN_DIGEST = (\n'
                '    "sha256:a730405dab8bad2ee8c4eea9a4fb97b8ef53ea1541'
                '5a4d904bf666d020cdc625")',
                'AUTHORIZED_R5A_STATIC_PLAN_DIGEST = (\n'
                '    "sha256:a730405dab8bad2ee8c4eea9a4fb97b8ef53ea1541'
                '5a4d904bf666d020cdc626")')
            result = fixture.run_dry_run_probe()
            self.assertEqual(result.returncode, 17, result.stderr)
            # rejected: the module constant no longer equals the
            # authority-bound freeze record / really-built digest
            self.assertIn("DRY_RUN_REJECT", result.stdout)
            self.assertIn("a730405dab8bad2ee8c4eea9a4fb97b8ef53ea1541"
                          "5a4d904bf666d020cdc626", result.stdout)

    def test_control_freeze_environment_identity_drift_rejects(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = _ScratchFixture(tmp)
            def mutate(record):
                sha = record["authorized_realization_inputs"]["environment"][
                    "canonical_sha256"]
                record["authorized_realization_inputs"]["environment"][
                    "canonical_sha256"] = (
                        sha[:10] + ("0" if sha[10] != "0" else "1")
                        + sha[11:])
            fixture.rewrite_freeze_field(mutate)
            result = fixture.run_dry_run_probe()
            self.assertEqual(result.returncode, 17, result.stderr)
            self.assertIn("environment canonical sha256", result.stdout)

    def test_control_freeze_arm_b_identity_drift_rejects(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = _ScratchFixture(tmp)
            def mutate(record):
                digest = record["arm_b_participant_plan_digest"]
                record["arm_b_participant_plan_digest"] = (
                    digest[:10] + ("0" if digest[10] != "0" else "1")
                    + digest[11:])
            fixture.rewrite_freeze_field(mutate)
            result = fixture.run_dry_run_probe()
            self.assertEqual(result.returncode, 17, result.stderr)
            self.assertIn("Arm-B participant digest", result.stdout)


class GateToolingClosureStaticTests(unittest.TestCase):
    """Cheap in-process structural checks on the closure itself."""

    def test_closure_covers_the_gate_import_graph(self):
        sys.path.insert(0, str(ROOT / "scripts"))
        try:
            import issue133_arm_c_retry_campaign as camp
        finally:
            sys.path.remove(str(ROOT / "scripts"))
        expected_minimum = {
            "scripts/issue133_arm_c_retry_campaign.py",
            "scripts/issue133_real_builder_dry_run.py",
            "scripts/issue133_canonical_environment.py",
            "scripts/issue133_arm_c_retry_direct.py",
            "scripts/issue129_arm_c_retry_core.py",
            "scripts/issue117_arm_c_frozen_pins.py",
        }
        self.assertEqual(set(camp.GATE_TOOLING_CLOSURE), expected_minimum)
        # every closure member is a real, non-symlink repository file
        for relative in camp.GATE_TOOLING_CLOSURE:
            path = ROOT / relative
            self.assertFalse(path.is_symlink(), relative)
            self.assertTrue(path.is_file(), relative)
            self.assertEqual(path.parent, ROOT / "scripts")

    def test_dry_run_imports_are_all_closure_members(self):
        """The dry-run module (dynamically executed by the gate) must
        import only closure-covered repository modules."""
        sys.path.insert(0, str(ROOT / "scripts"))
        try:
            import issue133_arm_c_retry_campaign as camp
        finally:
            sys.path.remove(str(ROOT / "scripts"))
        import ast
        source = (ROOT / "scripts" / "issue133_real_builder_dry_run.py"
                  ).read_text()
        tree = ast.parse(source)
        repo_imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    repo_imports.add(alias.name)
            elif isinstance(node, ast.ImportFrom) and node.module:
                repo_imports.add(node.module)
        module_names = {
            member.rsplit("/", 1)[-1][:-3]
            for member in camp.GATE_TOOLING_CLOSURE}
        # only repository-side gate modules (scripts/issue*) can affect
        # the authorization decision; the Python stdlib is outside the
        # repository trust boundary
        for name in repo_imports:
            if not name.startswith("issue"):
                continue
            self.assertIn(
                name, module_names,
                f"the dry-run gate imports {name!r} which is NOT in the "
                "gate-tooling closure; the closure audit is incomplete")


if __name__ == "__main__":
    unittest.main()
