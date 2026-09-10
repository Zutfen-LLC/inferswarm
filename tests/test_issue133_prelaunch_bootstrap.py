"""Issue #133 — external Git-rooted bootstrap tests (review 5167622668).

The round-2 defect: the gate-tooling closure was verified by the very
working-tree modules it was supposed to distrust (the campaign module
imported the #129 core, then "verified" itself). These tests prove the
corrected architecture:

- the CANONICAL physical pre-execution entrypoint is
  scripts/issue133_physical_prelaunch_gate.py — a stdlib/Git-only
  bootstrap that never imports any repository module, resolves the
  accepted authority-bearing commit from refs/remotes/origin/main +
  the Git object database, materializes that commit's complete tree
  via git archive, byte-binds the COMPLETE closure (gate tooling +
  the bootstrap itself) against the accepted blobs, and executes the
  gate from that accepted materialization only;

- ADVERSARIAL, NON-VACUOUS controls: a working-tree campaign module
  whose verify_gate_tooling_closure returns success unconditionally
  (or which bypasses the gate entirely and just prints PASS), and the
  equivalent substitutions for issue129_arm_c_retry_core.py, can
  NEVER cause the canonical prelaunch gate to pass on their own
  authority — the substituted module is never executed (proved by an
  execution marker the hostile module would leave behind), and the
  verdict's executed-file hashes equal the accepted Git blobs;

- fail-closed controls: a missing refs/remotes/origin/main rejects;
  the REAL pre-merge repository rejects (the authority bytes are not
  accepted history yet);

- later-main semantics, executed-origin provenance, and the
  bootstrap/campaign closure-constant agreement.

Every canonical-entrypoint invocation runs the REAL bootstrap file in
a fresh subprocess. CPU-only: no GPU, no model execution, no
participant-state mutation.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP = ROOT / "scripts/issue133_physical_prelaunch_gate.py"
AUTHORITY_REL = (
    "docs/implementation/r6-successor-dense-full-integration-117"
    "/evidence/arm-c-retry/physical-campaign-authority.json")
FREEZE_REL = (
    "docs/implementation/r6-successor-dense-full-integration-117"
    "/evidence/arm-c-retry/execution-freeze.json")

#: marker a HOSTILE working-tree module leaves behind if it is ever
#: executed as authorization authority
_MARKER = "WORKING_TREE_GATE_WAS_EXECUTED"


def _git(repo: Path, *args: str, env: dict) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo), *args], stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True, env=env, check=True)


class _AcceptedFixture:
    """An accepted-history Git repository whose authority-bearing
    commit carries the COMPLETE corrected closure, the retained
    evidence, and a regenerated /6 execution freeze bound into the
    authority document.

    Ordering mirrors production: code committed first, then the real
    unmocked builder dry run executed and the freeze regenerated from
    the working fixture repository, then history amended so the
    authority-bearing commit carries the bound freeze bytes.
    """

    def __init__(self, tmp: str):
        import shutil
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
            ignore=shutil.ignore_patterns("__pycache__"))
        self.env = dict(
            os.environ,
            GIT_AUTHOR_NAME="Issue 133 Bootstrap Control",
            GIT_AUTHOR_EMAIL="issue133-bootstrap@example.invalid",
            GIT_COMMITTER_NAME="Issue 133 Bootstrap Control",
            GIT_COMMITTER_EMAIL="issue133-bootstrap@example.invalid",
            HOME=os.environ.get("HOME", str(self.tmp)))
        self.env.pop("PYTHONPATH", None)
        _git(self.repo, "init", "-q", "-b", "main", env=self.env)
        _git(self.repo, "add", ".", env=self.env)
        _git(self.repo, "commit", "-q", "-m", "accepted closure",
             env=self.env)
        # the real unmocked builder dry run + freeze regeneration from
        # the fixture repository bytes (production ordering)
        regenerate = subprocess.run(
            [sys.executable,
             str(self.repo / "scripts"
                 / "issue133_regenerate_corrected_freeze.py")],
            cwd=str(self.repo), capture_output=True, text=True,
            env=self.env)
        assert regenerate.returncode == 0, regenerate.stderr
        # fold the regenerated authority+freeze into the accepted
        # history: the authority-bearing commit must carry them
        _git(self.repo, "add", str(AUTHORITY_REL), env=self.env)
        _git(self.repo, "add", str(FREEZE_REL), env=self.env)
        _git(self.repo, "commit", "--amend", "--no-edit", "-q",
             env=self.env)
        self.accepted_head = subprocess.run(
            ["git", "-C", str(self.repo), "rev-parse", "HEAD"],
            capture_output=True, text=True, env=self.env,
            check=True).stdout.strip()
        _git(self.repo, "update-ref", "refs/remotes/origin/main",
             self.accepted_head, env=self.env)

    # -- working-tree substitutions ----------------------------------
    def substitute(self, relative: str, text: str) -> None:
        path = self.repo / relative
        path.write_text(text)

    def run_bootstrap(self) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(BOOTSTRAP), "--repo", str(self.repo)],
            capture_output=True, text=True, env=self.env,
            timeout=900)

    def verdict_of(self, result: subprocess.CompletedProcess) -> dict:
        payload = json.loads(result.stdout)
        assert payload["schema"] == (
            "inferswarm.issue133.physical-prelaunch-bootstrap/1")
        return payload


#: a campaign module whose gate verifier returns success
#: UNCONDITIONALLY — and leaves a marker AT IMPORT TIME if it is ever
#: loaded by anything as authorization authority
_BYPASSED_VERIFIER_CAMPAIGN = '''\
import json
import sys
from pathlib import Path
Path(__file__).resolve().parents[2].joinpath("{marker}").write_text(
    "executed as authority\\n")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


def verify_gate_tooling_closure(accepted_commit, repo_root=None,
                                repo_path=None):
    return {{"schema": "inferswarm.issue133.gate-tooling-closure/1",
            "accepted_authority_commit": "0" * 40,
            "bound_paths": [], "verified": {{}}}}


def verify_pre_execution_authority_gate(repo_root=None, repo_path=None):
    return {{"schema": "inferswarm.issue133.pre-execution-gate/3",
            "gate": "SPOOFED_UNCONDITIONAL_PASS",
            "accepted_authority_commit": "0" * 40,
            "accepted_ref": "refs/remotes/origin/main",
            "campaign_ids": ["spoofed"],
            "gate_tooling_closure": verify_gate_tooling_closure(None),
            "execution_freeze_binding": {{
                "campaign_id": "spoofed",
                "authorized_execution_freeze_identity": "f" * 64,
                "retained_bytes_sha256": "f" * 64,
                "bound": True}},
            "real_builder_dry_run": {{
                "digest": "sha256:" + "f" * 64,
                "frozen_digest": "sha256:" + "f" * 64,
                "freeze_bound_verdict_fields": {{
                    "r5a_static_plan_schema":
                        "inferswarm.r5a.static-execution-plan/1",
                    "r5a_static_plan_digest": "sha256:" + "f" * 64}},
                "environment_canonical_sha256": "f" * 64}}}}
'''.format(marker=_MARKER)


class BootstrapAdversarialControls(unittest.TestCase):
    """Requirement: the canonical physical pre-execution entrypoint
    must never accept current-working-tree Python as authorization
    authority, no matter how the working-tree gate modules are
    modified."""

    def test_control_passing_gate_in_accepted_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = _AcceptedFixture(tmp)
            result = fixture.run_bootstrap()
            self.assertEqual(result.returncode, 0, result.stderr)
            verdict = fixture.verdict_of(result)
            self.assertTrue(verdict["pass"])
            self.assertEqual(
                verdict["source_mode"], "accepted_git_materialization")
            self.assertEqual(
                verdict["accepted_authority_commit"],
                fixture.accepted_head)
            self.assertEqual(
                verdict["origin_main_observed_sha"], fixture.accepted_head)
            # execution-origin provenance: EVERY executed closure file
            # hash equals its accepted blob hash
            provenance = verdict["gate_tooling_execution_provenance"]
            self.assertEqual(len(provenance), 7)
            for relative, entry in provenance.items():
                self.assertTrue(entry["equal"], relative)
                self.assertEqual(
                    entry["executed_sha256"],
                    entry["accepted_blob_sha256"], relative)
            self.assertIn("scripts/issue133_physical_prelaunch_gate.py",
                          provenance)
            # The authorization bootstrap itself runs from the accepted
            # materialization, never from this checkout's invocation path.
            bootstrap_execution = verdict["bootstrap_execution"]
            self.assertTrue(bootstrap_execution["equal"])
            self.assertNotEqual(
                Path(bootstrap_execution["executed_path"]).resolve(),
                BOOTSTRAP.resolve())
            self.assertIn("issue133-bootstrap-loader-",
                          bootstrap_execution["executed_path"])
            # identity fields required by the review
            authority = json.loads(
                (fixture.repo / AUTHORITY_REL).read_text())
            self.assertEqual(
                verdict["execution_freeze_identity"],
                authority["campaigns"]["armc-retry-afcdc4428f95d50c"]
                ["execution_freeze_identity"])
            self.assertEqual(
                verdict["r5a_static_plan_digest"],
                "sha256:a730405dab8bad2ee8c4eea9a4fb97b8ef53ea1541"
                "5a4d904bf666d020cdc625")
            self.assertEqual(
                verdict["environment_canonical_sha256"],
                "98c04387215915acf54a9ff769492e3f7cb7b0266d3664963"
                "1a531a9b5edbf67")
            self.assertEqual(verdict["working_tree_drift"], {})
            # no working-tree gate module was executed
            self.assertFalse(
                (fixture.repo / _MARKER).exists())

    def test_adversarial_unconditional_pass_campaign_cannot_win(self):
        """The working-tree campaign module's verify_gate_tooling_closure
        returns success unconditionally and the module spoofs a PASS
        verdict. The CANONICAL entrypoint must still pass on the
        ACCEPTED gate only, never executing the substituted module."""
        with tempfile.TemporaryDirectory() as tmp:
            fixture = _AcceptedFixture(tmp)
            fixture.substitute(
                "scripts/issue133_arm_c_retry_campaign.py",
                _BYPASSED_VERIFIER_CAMPAIGN)
            result = fixture.run_bootstrap()
            self.assertEqual(result.returncode, 0, result.stderr)
            verdict = fixture.verdict_of(result)
            self.assertTrue(verdict["pass"])
            # the substituted module was NEVER executed as authority
            self.assertFalse(
                (fixture.repo / _MARKER).exists(),
                "the working-tree campaign module was executed as "
                "authorization authority")
            # the accepted gate — not the spoof — produced the verdict
            gate = verdict["pre_execution_gate_verdict"]
            self.assertEqual(
                gate["gate"],
                "ACCEPTED_HISTORY_TOOLING_FREEZE_AND_REAL_BUILDER_BOUND")
            # executed bytes are the ACCEPTED bytes, and the drift
            # report surfaces the substitution (defense in depth)
            for entry in (
                    verdict["gate_tooling_execution_provenance"]
                    .values()):
                self.assertTrue(entry["equal"])
            self.assertIn(
                "scripts/issue133_arm_c_retry_campaign.py",
                verdict["working_tree_drift"])

    def test_adversarial_bypassed_entirely_campaign_cannot_win(self):
        """The working-tree campaign module deletes every verification
        call and simply prints a passing verdict with a decoy
        authority commit. The canonical bootstrap ignores it entirely;
        the verdict's authority commit is the accepted one."""
        with tempfile.TemporaryDirectory() as tmp:
            fixture = _AcceptedFixture(tmp)
            hostile = (
                "import json, sys\n"
                "from pathlib import Path\n"
                f"(Path(__file__).resolve().parents[2] / '{_MARKER}')"
                ".write_text('executed\\n')\n"
                "print(json.dumps({\n"
                "  'schema': 'inferswarm.issue133.pre-execution-gate/3',\n"
                "  'gate': 'HOSTILE_BYPASS',\n"
                "  'accepted_authority_commit': '" + "e" * 40 + "',\n"
                "  'execution_freeze_binding': {'bound': True},\n"
                "  'real_builder_dry_run': {'digest': 'sha256:" + "e" * 64 + "'}}))\n"
                "raise SystemExit(0)\n")
            fixture.substitute(
                "scripts/issue133_arm_c_retry_campaign.py", hostile)
            result = fixture.run_bootstrap()
            self.assertEqual(result.returncode, 0, result.stderr)
            verdict = fixture.verdict_of(result)
            self.assertTrue(verdict["pass"])
            # the hostile module never ran: no marker, accepted (not
            # decoy) authority commit in the verdict
            self.assertFalse((fixture.repo / _MARKER).exists())
            self.assertEqual(
                verdict["accepted_authority_commit"],
                fixture.accepted_head)

    def test_adversarial_hostile_129_core_cannot_win(self):
        """Equivalent substitution control for the #129 methodology
        core: a working-tree core that would abort (or spoof) any
        gate run can never become authorization authority."""
        with tempfile.TemporaryDirectory() as tmp:
            fixture = _AcceptedFixture(tmp)
            hostile_core = (
                "import sys\n"
                "from pathlib import Path\n"
                f"(Path(__file__).resolve().parents[2] / '{_MARKER}')"
                ".write_text('executed\\n')\n"
                "raise SystemExit('HOSTILE_129_CORE_REACHED')\n")
            fixture.substitute(
                "scripts/issue129_arm_c_retry_core.py", hostile_core)
            result = fixture.run_bootstrap()
            self.assertEqual(result.returncode, 0, result.stderr)
            verdict = fixture.verdict_of(result)
            self.assertTrue(verdict["pass"])
            self.assertFalse((fixture.repo / _MARKER).exists())
            self.assertIn(
                "scripts/issue129_arm_c_retry_core.py",
                verdict["working_tree_drift"])
            for entry in (
                    verdict["gate_tooling_execution_provenance"]
                    .values()):
                self.assertTrue(entry["equal"])

    def test_control_missing_origin_main_rejects(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = _AcceptedFixture(tmp)
            _git(fixture.repo, "update-ref", "-d",
                 "refs/remotes/origin/main", env=fixture.env)
            result = fixture.run_bootstrap()
            self.assertEqual(result.returncode, 1)
            self.assertIn("PHYSICAL_PRELAUNCH_GATE_REJECT", result.stderr)
            self.assertIn("origin/main", result.stderr)

    def test_control_real_premerge_repository_rejects(self):
        """In THIS repository (PR branch, unmerged authority bytes) the
        canonical entrypoint must fail closed: the authority document
        carrying the current freeze identity exists only on the
        branch."""
        result = subprocess.run(
            [sys.executable, str(BOOTSTRAP)], capture_output=True,
            text=True, timeout=900)
        self.assertEqual(result.returncode, 1)
        self.assertIn("PHYSICAL_PRELAUNCH_GATE_REJECT", result.stderr)


class BootstrapMechanicsTests(unittest.TestCase):
    """Structural controls on the bootstrap itself."""

    def test_bootstrap_is_stdlib_git_only(self):
        """The bootstrap must not import any repository module (AST
        audit: only stdlib imports are permitted)."""
        import ast
        tree = ast.parse(BOOTSTRAP.read_text())
        allowed = {
            "__future__", "argparse", "hashlib", "json", "os",
            "subprocess", "sys", "tarfile", "tempfile", "pathlib", "typing",
            "shutil",
        }
        found = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                found.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                found.add(node.module)
        self.assertTrue(found <= allowed, found - allowed)

    def test_closure_constants_agree_with_campaign_module(self):
        sys.path.insert(0, str(ROOT / "scripts"))
        try:
            import issue133_arm_c_retry_campaign as camp
        finally:
            sys.path.remove(str(ROOT / "scripts"))
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "_prelaunch_bootstrap", BOOTSTRAP)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertEqual(
            sorted(module.PHYSICAL_PRELAUNCH_CLOSURE),
            sorted(set(camp.GATE_TOOLING_CLOSURE)
                   | {camp.EXTERNAL_BOOTSTRAP_REL_PATH}))
        # every closure member is a real non-symlink repository file
        for relative in module.PHYSICAL_PRELAUNCH_CLOSURE:
            path = ROOT / relative
            self.assertFalse(path.is_symlink(), relative)
            self.assertTrue(path.is_file(), relative)

    def test_bootstrap_execution_cannot_reach_working_tree_modules(self):
        """The scrubbed subprocess environment plus the campaign
        module's scripts/-first sys.path guarantee: a same-named
        working-tree module cannot shadow the materialized accepted
        bytes (proved end-to-end by the adversarial controls above;
        here we assert the scrub list covers the injection vectors)."""
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "_prelaunch_bootstrap", BOOTSTRAP)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertLessEqual(
            {"PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP",
             "PYTHONUSERBASE"},
            set(module._SCRUBBED_ENV_KEYS))
    def test_bootstrap_materializes_without_tar_executable(self):
        """The pre-authorization bootstrap is stdlib/Git-only: archive
        extraction uses tarfile, never a PATH-resolved tar program."""
        import ast
        tree = ast.parse(BOOTSTRAP.read_text())
        self.assertIn("import tarfile", BOOTSTRAP.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if not (isinstance(node.func, ast.Attribute)
                    and node.func.attr == "run") or not node.args:
                continue
            command = node.args[0]
            if isinstance(command, (ast.List, ast.Tuple)) and command.elts:
                first = command.elts[0]
                if isinstance(first, ast.Constant) and first.value == "tar":
                    self.fail("bootstrap must not execute external tar")

    def test_accepted_gate_uses_isolated_no_site_interpreter(self):
        """Accepted gate execution must reject PYTHONPATH and system
        sitecustomize/.pth import injection before campaign imports."""
        source = BOOTSTRAP.read_text()
        self.assertIn("sys.executable, \"-I\", \"-S\"", source)


if __name__ == "__main__":
    unittest.main()
