"""Canonical CPU test environment contract (Issue #131).

Focused controls for the single dependency authority
(``requirements-test.txt``), the bootstrap, and the doctor. Every
fail-closed path has a negative control, per the repository test
conventions: the environment contract must reject a removed dependency,
an ad-hoc CI install, a declared-but-unavailable package, an
incompatible version, a bootstrap that mutates tracked files, a
model-runtime package entering the CPU environment, and documentation
that names a different install command than the canonical bootstrap.
"""
from __future__ import annotations

import contextlib
import io
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import bootstrap_test_env as bootstrap  # noqa: E402
import check_test_env as doctor  # noqa: E402


REQUIREMENTS = ROOT / "requirements-test.txt"
CI_WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def sandbox_repo(test: unittest.TestCase) -> tuple[Path, Path]:
    """A throwaway git repo mimicking the repository layout.

    Returns (sandbox, venv_target) with requirements-test.txt and
    .gitignore copied in; call patch_module_root so the bootstrap
    module's ROOT/VENV point at the sandbox.
    """
    sandbox = Path(tempfile.mkdtemp())
    test.addCleanup(shutil.rmtree, sandbox, ignore_errors=True)
    for relative in ("requirements-test.txt", ".gitignore"):
        destination = sandbox / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, destination)
    subprocess.run(["git", "init", "-q", str(sandbox)], check=True,
                   capture_output=True)
    subprocess.run(
        ["git", "-C", str(sandbox), "config", "user.email",
         "test@example.invalid"], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(sandbox), "config", "user.name", "Test"],
        check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(sandbox), "add", ".gitignore"],
        check=True, capture_output=True)
    return sandbox, sandbox / ".venv"


def patch_module_root(test: unittest.TestCase, sandbox: Path) -> None:
    """Point the bootstrap module's ROOT/VENV at a sandbox repo."""
    original_root, original_venv = bootstrap.ROOT, bootstrap.VENV
    bootstrap.ROOT = sandbox
    bootstrap.VENV = sandbox / ".venv"
    test.addCleanup(setattr, bootstrap, "ROOT", original_root)
    test.addCleanup(setattr, bootstrap, "VENV", original_venv)


class DependencyAuthorityTests(unittest.TestCase):
    """The single repository-owned dependency definition."""

    def test_authority_exists_and_declares_expected_direct_packages(self):
        text = REQUIREMENTS.read_text(encoding="utf-8")
        packages, references = doctor.parse_requirements(text)
        self.assertEqual(packages, {"jsonschema", "numpy", "pyyaml"})
        self.assertEqual(references, {doctor.REFERENCED_REQUIREMENTS[0]})

    def test_authority_references_frozen_tokenizer_without_duplicating_pins(self):
        """The immutable #117 pins are consumed by reference, never copied."""
        referenced = (ROOT / doctor.REFERENCED_REQUIREMENTS[0]).read_text(
            encoding="utf-8")
        frozen_names = {
            doctor._normalize(line.split("==")[0].strip())
            for line in referenced.splitlines()
            if "==" in line and not line.strip().startswith("#")}
        self.assertTrue(frozen_names)
        authority = REQUIREMENTS.read_text(encoding="utf-8")
        for name in frozen_names:
            duplicated = re.search(
                rf"^\s*{re.escape(name)}\s*(==|>=|<|~=)", authority,
                re.MULTILINE)
            self.assertIsNone(
                duplicated,
                f"authority duplicates the frozen pin for {name}; the "
                "accepted #117 requirements must be installed by reference")

    def test_negative_control_removing_a_declared_dependency_fails_the_doctor(self):
        original = REQUIREMENTS.read_text(encoding="utf-8")
        mutated = re.sub(r"^jsonschema.*$", "", original, flags=re.MULTILINE)
        self.assertNotEqual(mutated, original)
        try:
            write(REQUIREMENTS, mutated)
            findings = doctor.doctor()
            self.assertTrue(
                any("drift" in str(finding) for finding in findings),
                [str(finding) for finding in findings])
        finally:
            write(REQUIREMENTS, original)

    def test_negative_control_authority_referencing_a_model_runtime_fails_bootstrap(self):
        original = REQUIREMENTS.read_text(encoding="utf-8")
        try:
            write(REQUIREMENTS, original + "\ntorch>=2\n")
            violations = bootstrap.forbidden_in_requirements(
                REQUIREMENTS.read_text(encoding="utf-8"))
            self.assertEqual(violations, ["torch"])
        finally:
            write(REQUIREMENTS, original)


class DoctorNegativeControls(unittest.TestCase):
    """Doctor mode fails closed on each prohibited environment state."""

    def test_negative_control_doctor_fails_when_declared_package_is_unavailable(self):
        """`jsonschema` masked out of the environment must fail the doctor."""
        with tempfile.TemporaryDirectory() as directory:
            sandbox = Path(directory)
            copies = ["requirements-test.txt", "CONTRIBUTING.md",
                      "tests/README.md", ".github/workflows/ci.yml",
                      "scripts/check_test_env.py",
                      "scripts/bootstrap_test_env.py"]
            for reference in doctor.REFERENCED_REQUIREMENTS:
                copies.append(reference)
            for relative in copies:
                destination = sandbox / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(ROOT / relative, destination)
            write(sandbox / "mask_jsonschema.py",
                  "import importlib.metadata as m\n"
                  "real = m.distributions\n"
                  "def filtered():\n"
                  "    for d in real():\n"
                  "        n = (d.metadata.get('Name') or '').lower()\n"
                  "        if n not in ('jsonschema',):\n"
                  "            yield d\n"
                  "m.distributions = filtered\n"
                  "import runpy, sys\n"
                  "sys.argv = ['check_test_env.py']\n"
                  "sys.path.insert(0, 'scripts')\n"
                  "try:\n"
                  "    runpy.run_path('scripts/check_test_env.py',"
                  " run_name='__main__')\n"
                  "except SystemExit as e:\n"
                  "    sys.exit(e.code)\n")
            result = subprocess.run(
                [sys.executable, "mask_jsonschema.py"],
                cwd=sandbox, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0,
                                result.stdout + result.stderr)
            self.assertIn("jsonschema", result.stderr)

    def test_negative_control_doctor_fails_on_incompatible_declared_version(self):
        original = doctor.installed_versions

        def older_jsonschema():
            versions = original()
            versions["jsonschema"] = "4.17.0"
            return versions

        doctor.installed_versions = older_jsonschema
        try:
            findings = doctor.doctor()
        finally:
            doctor.installed_versions = original
        self.assertTrue(
            any("older than the declared floor" in str(f) for f in findings),
            [str(finding) for finding in findings])

    def test_negative_control_doctor_fails_when_model_runtime_is_installed(self):
        original = doctor.installed_versions

        def with_torch():
            versions = original()
            versions["torch"] = "2.9.0"
            return versions

        doctor.installed_versions = with_torch
        try:
            findings = doctor.doctor()
        finally:
            doctor.installed_versions = original
        self.assertTrue(
            any("model-runtime" in str(f) for f in findings),
            [str(finding) for finding in findings])

    def test_negative_control_doctor_fails_when_openssl_is_missing(self):
        original = doctor.check_executables
        doctor.check_executables = lambda: (_ for _ in ()).throw(
            doctor.DoctorError(
                "required external executable is not on PATH: openssl"))
        try:
            findings = doctor.doctor()
        finally:
            doctor.check_executables = original
        self.assertTrue(
            any("openssl" in str(f) for f in findings),
            [str(finding) for finding in findings])


class CIContractTests(unittest.TestCase):
    """CI consumes the canonical contract and installs nothing ad hoc."""

    def test_ci_bootstraps_from_the_canonical_contract(self):
        workflow = CI_WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("scripts/bootstrap_test_env.py", workflow)
        self.assertIn("scripts/check_test_env.py", workflow)
        # No ad-hoc package-name installs survive anywhere in the workflow.
        for line in workflow.splitlines():
            if "pip install" in line:
                self.assertIn(
                    "requirements-test.txt", line,
                    f"CI pip install not from the canonical authority: {line}")

    def test_negative_control_ad_hoc_ci_install_is_rejected(self):
        original = CI_WORKFLOW.read_text(encoding="utf-8")
        try:
            write(CI_WORKFLOW, original + (
                "\n      - name: rogue\n"
                "        run: python3 -m pip install --user sympy\n"))
            findings = doctor.doctor()
            self.assertTrue(
                any("outside the canonical contract" in str(f)
                    for f in findings),
                [str(finding) for finding in findings])
        finally:
            write(CI_WORKFLOW, original)

    def test_negative_control_ci_without_bootstrap_is_rejected(self):
        original = CI_WORKFLOW.read_text(encoding="utf-8")
        try:
            write(CI_WORKFLOW, original.replace(
                "python3 scripts/bootstrap_test_env.py", "true"))
            findings = doctor.doctor()
            self.assertTrue(
                any("bootstrap_test_env.py" in str(f) for f in findings),
                [str(finding) for finding in findings])
        finally:
            write(CI_WORKFLOW, original)


class DocumentationContractTests(unittest.TestCase):
    """Docs name the canonical bootstrap, not package-specific installs."""

    def test_docs_name_the_canonical_commands(self):
        for relative in ("CONTRIBUTING.md", "tests/README.md",
                         "scripts/README.md"):
            text = (ROOT / relative).read_text(encoding="utf-8")
            self.assertIn("bootstrap_test_env.py", text,
                          f"{relative}: missing canonical bootstrap mention")
            self.assertIn("check_test_env.py", text,
                          f"{relative}: missing canonical doctor mention")

    def test_negative_control_package_specific_install_command_is_rejected(self):
        original = (ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")
        try:
            write(ROOT / "CONTRIBUTING.md", original.replace(
                "python3 scripts/bootstrap_test_env.py",
                "python3 -m pip install --user jsonschema numpy"))
            findings = doctor.doctor()
            self.assertTrue(
                any("CONTRIBUTING.md" in str(f) for f in findings),
                [str(finding) for finding in findings])
        finally:
            write(ROOT / "CONTRIBUTING.md", original)

    def test_negative_control_docs_dropping_the_bootstrap_command_are_rejected(self):
        original = (ROOT / "tests" / "README.md").read_text(encoding="utf-8")
        try:
            write(ROOT / "tests" / "README.md",
                  original.replace("bootstrap_test_env.py", "setup.py"))
            findings = doctor.doctor()
            self.assertTrue(
                any("tests/README.md" in str(f) for f in findings),
                [str(finding) for finding in findings])
        finally:
            write(ROOT / "tests" / "README.md", original)


class VenvTargetSafetyTests(unittest.TestCase):
    """The venv target is safe by construction, before any deletion.

    Negative controls prove a tracked directory, the repository root,
    an arbitrary --venv override, a symlink escape, and an existing
    ordinary (non-venv) directory are ALL rejected without modifying
    or deleting their sentinel contents.
    """

    def test_negative_control_tracked_directory_target_is_rejected(self):
        """A tracked repository directory must never be a venv target.

        Uses the real repository's tracked ``scripts/`` directory: the
        refusal must fire before any deletion and its sentinel file
        must survive byte-for-byte.
        """
        target = ROOT / "scripts"
        tracked = subprocess.run(
            ["git", "-C", str(ROOT), "ls-files", "--", "scripts"],
            capture_output=True, text=True, check=True).stdout.split()
        self.assertTrue(tracked)  # sanity: scripts/ is tracked
        sentinel = target / "bootstrap_test_env.py"
        before = sentinel.read_bytes()
        with contextlib.redirect_stderr(io.StringIO()) as captured:
            with self.assertRaises(SystemExit) as raised:
                bootstrap.validate_venv_target(target)
        self.assertEqual(raised.exception.code, 1)
        self.assertIn("refusing venv target", captured.getvalue())
        self.assertEqual(sentinel.read_bytes(), before)

    def test_negative_control_repository_root_is_rejected(self):
        sentinel = ROOT / "requirements-test.txt"
        before = sentinel.read_bytes()
        with contextlib.redirect_stderr(io.StringIO()) as captured:
            with self.assertRaises(SystemExit) as raised:
                bootstrap.validate_venv_target(ROOT)
        self.assertEqual(raised.exception.code, 1)
        self.assertIn("refusing venv target", captured.getvalue())
        self.assertEqual(sentinel.read_bytes(), before)

    def test_negative_control_arbitrary_venv_override_is_rejected(self):
        """There is no --venv surface left: any other target is refused,
        whether outside the repository or an untracked directory inside
        it. Sentinels survive both."""
        outside = Path(tempfile.mkdtemp()) / "escape-venv"
        outside.mkdir()
        sentinel_out = outside / "keep.txt"
        sentinel_out.write_text("sentinel", encoding="utf-8")
        inside = ROOT / "scratch-venv-under-test"
        inside.mkdir()
        sentinel_in = inside / "keep.txt"
        sentinel_in.write_text("sentinel", encoding="utf-8")
        try:
            for target in (outside, inside):
                with contextlib.redirect_stderr(io.StringIO()) as captured:
                    with self.assertRaises(SystemExit) as raised:
                        bootstrap.validate_venv_target(target)
                self.assertEqual(raised.exception.code, 1)
                self.assertIn("refusing venv target", captured.getvalue())
            self.assertEqual(
                sentinel_out.read_text(encoding="utf-8"), "sentinel")
            self.assertEqual(
                sentinel_in.read_text(encoding="utf-8"), "sentinel")
            # The CLI no longer exposes --venv at all.
            cli = subprocess.run(
                [sys.executable,
                 str(ROOT / "scripts" / "bootstrap_test_env.py"),
                 "--venv", str(outside)],
                capture_output=True, text=True, cwd=ROOT)
            self.assertNotEqual(cli.returncode, 0)
            self.assertIn("unrecognized arguments", cli.stderr)
            self.assertEqual(
                sentinel_out.read_text(encoding="utf-8"), "sentinel")
        finally:
            shutil.rmtree(outside)
            shutil.rmtree(inside)

    def test_negative_control_venv_shaped_ordinary_directory_is_refused(self):
        """The real create path must not rmtree `.venv/bin/keep.txt`.

        Generic names such as `bin` are not bootstrap ownership proof;
        the sentinel must survive byte-identically and create_venv must
        fail before any destructive operation.
        """
        sandbox, target = sandbox_repo(self)
        patch_module_root(self, sandbox)
        sentinel = target / "bin" / "keep.txt"
        sentinel.parent.mkdir(parents=True)
        sentinel.write_bytes(b"ordinary-user-content\n")
        before = sentinel.read_bytes()
        with contextlib.redirect_stderr(io.StringIO()) as captured:
            with self.assertRaises(SystemExit) as raised:
                bootstrap.create_venv(target, "3.12")
        self.assertEqual(raised.exception.code, 1)
        self.assertIn("without a bootstrap-owned pyvenv.cfg",
                      captured.getvalue())
        self.assertEqual(sentinel.read_bytes(), before)
        self.assertTrue(target.is_dir())

    def test_negative_control_empty_existing_target_is_refused(self):
        """Even an empty no-config target is not inferred bootstrap-owned."""
        sandbox, target = sandbox_repo(self)
        patch_module_root(self, sandbox)
        target.mkdir()
        with contextlib.redirect_stderr(io.StringIO()) as captured:
            with self.assertRaises(SystemExit):
                bootstrap.validate_venv_target(target)
        self.assertIn("without a bootstrap-owned pyvenv.cfg",
                      captured.getvalue())
        self.assertTrue(target.is_dir())

    def test_negative_control_existing_ordinary_directory_is_rejected(self):
        """An existing non-venv directory at the canonical target is
        refused, never rmtree'd — sentinel contents survive intact."""
        sandbox, target = sandbox_repo(self)
        patch_module_root(self, sandbox)
        target.mkdir()
        sentinel = target / "precious.txt"
        sentinel.write_text("do-not-delete", encoding="utf-8")
        with contextlib.redirect_stderr(io.StringIO()) as captured:
            with self.assertRaises(SystemExit):
                bootstrap.validate_venv_target(target)
        self.assertIn("refusing venv target", captured.getvalue())
        self.assertIn("without a bootstrap-owned pyvenv.cfg",
                      captured.getvalue())
        self.assertEqual(
            sentinel.read_text(encoding="utf-8"), "do-not-delete")
        self.assertTrue(target.is_dir())

    def test_negative_control_symlink_escape_is_rejected(self):
        """A symlinked venv directory could make deletion act outside
        the target; the target dir itself being a symlink is refused
        before anything else (internal bin/python symlinks are normal
        venv structure and harmless: rmtree never follows them)."""
        sandbox, target = sandbox_repo(self)
        patch_module_root(self, sandbox)
        real_home = sandbox / "real-home"
        real_home.mkdir()
        sentinel = real_home / "precious.txt"
        sentinel.write_text("do-not-delete", encoding="utf-8")
        target.symlink_to(real_home)
        with contextlib.redirect_stderr(io.StringIO()) as captured:
            with self.assertRaises(SystemExit):
                bootstrap.validate_venv_target(target)
        self.assertIn("refusing venv target", captured.getvalue())
        self.assertIn("symlink", captured.getvalue())
        self.assertEqual(
            sentinel.read_text(encoding="utf-8"), "do-not-delete")
        self.assertTrue(target.is_symlink())

    def test_validate_target_accepts_the_canonical_gitignored_home(self):
        # The real .venv (or its absence) must pass validation.
        bootstrap.validate_venv_target(ROOT / ".venv")  # must not exit


class BootstrapContractTests(unittest.TestCase):
    """Bootstrap contracts: idempotent design, CPU-only, tree-safe."""

    def test_bootstrap_screens_model_runtime_requirements(self):
        self.assertEqual(
            bootstrap.forbidden_in_requirements("torch>=2\nsympy\n"),
            ["torch"])
        self.assertEqual(
            bootstrap.forbidden_in_requirements(
                "# comment\n-r elsewhere.txt\njsonschema>=4.18,<5\n"),
            [])

    def test_bootstrap_cli_no_longer_exposes_a_venv_override(self):
        """The public --venv surface is removed: argparse rejects it."""
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(
                [sys.executable,
                 str(ROOT / "scripts" / "bootstrap_test_env.py"),
                 "--venv", str(Path(directory) / "escape-venv")],
                capture_output=True, text=True, cwd=ROOT)
            self.assertNotEqual(result.returncode, 0, result.stdout)
            self.assertIn("unrecognized arguments", result.stderr)

    def test_negative_control_bootstrap_mutation_of_tracked_files_is_detected(self):
        """The tree-digest guard fails closed on any tracked-file change.

        The install and venv creation are stubbed out so the guard is the
        only code under test.
        """
        real_digests = bootstrap.tracked_file_digests
        state = {"calls": 0}

        def mutating_digests():
            state["calls"] += 1
            digests = real_digests()
            if state["calls"] == 2:  # after the (stubbed) install
                digests["README.md"] = "0" * 64
            return digests

        bootstrap.tracked_file_digests = mutating_digests
        original_create, original_install, original_forbidden = (
            bootstrap.create_venv, bootstrap.install,
            bootstrap.forbidden_installed)
        bootstrap.create_venv = (
            lambda venv_dir, python_request="3.12": venv_dir / "bin" / "python")
        bootstrap.install = lambda python, *args: None
        bootstrap.forbidden_installed = lambda python: []
        try:
            with contextlib.redirect_stderr(io.StringIO()) as captured:
                with self.assertRaises(SystemExit) as raised:
                    bootstrap.bootstrap(ROOT / ".venv")
            self.assertEqual(raised.exception.code, 1)
            self.assertIn("modified tracked repository files",
                          captured.getvalue())
        finally:
            bootstrap.tracked_file_digests = real_digests
            bootstrap.create_venv = original_create
            bootstrap.install = original_install
            bootstrap.forbidden_installed = original_forbidden

    def test_forbidden_screen_covers_referenced_files(self):
        text = REQUIREMENTS.read_text(encoding="utf-8")
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if line.startswith("-r "):
                referenced = (ROOT / line[3:]).resolve()
                self.assertTrue(referenced.is_file(), referenced)
                self.assertEqual(
                    bootstrap.forbidden_in_requirements(
                        referenced.read_text(encoding="utf-8")),
                    [],
                    "frozen tokenizer requirements must stay CPU-only")


class ExistingVenvInterpreterTests(unittest.TestCase):
    """A pre-existing venv is reused only when its interpreter matches."""

    def _sandbox_venv(self) -> tuple[Path, Path]:
        """A sandbox git repo with a real venv inside it."""
        sandbox, venv = sandbox_repo(self)
        subprocess.run(
            [sys.executable, "-m", "venv", "--without-pip",
             str(venv)], check=True, capture_output=True)
        return sandbox, venv

    def test_control_existing_matching_venv_is_reused(self):
        sandbox, venv = self._sandbox_venv()
        python = venv / "bin" / "python"
        # Same minor as the request: create_venv must reuse it (the
        # recorded version line and the real interpreter both match).
        request = f"{sys.version_info.major}.{sys.version_info.minor}"
        marker = venv / "sentinel-from-original-creation"
        marker.write_text("original", encoding="utf-8")
        patch_module_root(self, sandbox)
        result = bootstrap.create_venv(venv, request)
        self.assertEqual(result, python)
        self.assertEqual(
            marker.read_text(encoding="utf-8"), "original",
            "a matching existing venv must be reused, not recreated")

    def test_negative_control_stale_wrong_minor_venv_is_recreated(self):
        """A stale venv whose real interpreter has the wrong minor must
        be recreated with the requested interpreter, not installed
        into. Proven with a real mismatched venv when the host has both
        interpreters, else with a forged pyvenv.cfg (which must also be
        refused because its real interpreter is unverifiable/mismatched
        and pyvenv.cfg disagrees with reality)."""
        sandbox, venv = sandbox_repo(self)
        # Build a real venv on a minor that differs from the 3.12
        # request (the host launching interpreter's minor if it is not
        # 3.12, else a forged-config stale venv).
        launching_minor = f"{sys.version_info.major}.{sys.version_info.minor}"
        forged = launching_minor == "3.12"
        if not forged:
            subprocess.run(
                [sys.executable, "-m", "venv", "--without-pip",
                 str(venv)], check=True, capture_output=True)
        else:
            # Launching interpreter IS 3.12; forge a stale 3.13 venv
            # whose recorded version lies about the linked host
            # interpreter — the dual-channel check must reject it.
            venv.mkdir()
            (venv / "pyvenv.cfg").write_text(
                "home = /usr/bin\nversion = 3.13\n", encoding="utf-8")
            (venv / "bin").mkdir()
            (venv / "bin" / "python").symlink_to(sys.executable)
        patch_module_root(self, sandbox)
        python = bootstrap.create_venv(venv, "3.12")
        probe = subprocess.run(
            [str(python), "-c",
             "import sys; print(sys.version_info[:2])"],
            capture_output=True, text=True)
        self.assertEqual(probe.stdout.strip(), "(3, 12)",
                         "the recreated venv must run 3.12")
        if forged:
            self.assertNotEqual(
                (venv / "pyvenv.cfg").read_text(encoding="utf-8"),
                "home = /usr/bin\nversion = 3.13\n",
                "the stale config must not survive recreation")

    def test_negative_control_unverifiable_venv_is_recreated(self):
        """pyvenv.cfg + a broken bin/python must not be trusted."""
        sandbox, venv = sandbox_repo(self)
        venv.mkdir()
        (venv / "pyvenv.cfg").write_text(
            "home = /usr/bin\nversion = 3.12\n", encoding="utf-8")
        (venv / "bin").mkdir()
        (venv / "bin" / "python").write_text("#!/bin/sh\nexit 9\n",
                                             encoding="utf-8")
        (venv / "bin" / "python").chmod(0o755)
        patch_module_root(self, sandbox)
        python = bootstrap.create_venv(venv, "3.12")
        probe = subprocess.run(
            [str(python), "-c",
             "import sys; print(sys.version_info[:2])"],
            capture_output=True, text=True)
        self.assertEqual(probe.stdout.strip(), "(3, 12)")
    def test_negative_control_malformed_pyvenv_cfg_is_recreated(self):
        """A malformed recorded version is not accepted for reuse.

        `pyvenv.cfg` exists, so ownership is established and safe
        recreation is permitted; its malformed bytes must not survive.
        """
        sandbox, venv = self._sandbox_venv()
        config = venv / "pyvenv.cfg"
        config.write_text("home = /usr/bin\nversion = broken\n",
                          encoding="utf-8")
        patch_module_root(self, sandbox)
        python = bootstrap.create_venv(venv, "3.12")
        probe = subprocess.run(
            [str(python), "-c", "import sys; print(sys.version_info[:2])"],
            capture_output=True, text=True)
        self.assertEqual(probe.stdout.strip(), "(3, 12)")
        self.assertEqual(bootstrap.venv_python_request(venv), "3.12")
        self.assertNotIn("version = broken",
                         config.read_text(encoding="utf-8"))


class MissingUvTests(unittest.TestCase):
    """No uv + wrong launching interpreter fails deterministically."""

    def test_negative_control_missing_uv_is_an_actionable_failure(self):
        sandbox, venv = sandbox_repo(self)
        original_which, original_launching = (
            shutil.which, bootstrap._launching_version)
        original_installed = bootstrap._installed_python_for
        patch_module_root(self, sandbox)
        shutil.which = lambda name: None
        bootstrap._launching_version = lambda: (3, 13)
        bootstrap._installed_python_for = lambda request: None
        try:
            with contextlib.redirect_stderr(io.StringIO()) as captured:
                with self.assertRaises(SystemExit) as raised:
                    bootstrap.create_venv(venv, "3.12")
            self.assertEqual(raised.exception.code, 1)
            message = captured.getvalue()
            expected = (
                "bootstrap: cannot create the Python 3.12 virtual environment: "
                "the launching interpreter is 3.13, no installed python3.12 "
                "was found on PATH, and 'uv' is not installed. Install "
                "python3.12 with its venv module (for example: install a "
                "Python 3.12 package that provides `python3.12 -m venv`) or "
                "install uv <https://docs.astral.sh/uv/>, then re-run.\n")
            self.assertEqual(message, expected)
            self.assertNotIn("3..", message)
            self.assertNotIn("python3..", message)
            self.assertNotIn("Traceback", message)
        finally:
            shutil.which = original_which
            bootstrap._launching_version = original_launching
            bootstrap._installed_python_for = original_installed


class ModelRuntimeRejectionTests(unittest.TestCase):
    """The CPU/model-runtime rejection covers the declared invariant."""

    def test_nvidia_cuda_runtime_families_are_rejected_mechanically(self):
        """Common NVIDIA runtime wheels the round-1 exemplar list missed."""
        for name in (
                "nvidia-cublas-cu12", "nvidia-cuda-cuperso-cu12",
                "nvidia-cuda-nvrtc-cu12", "nvidia-cuda-runtime-cu12",
                "nvidia-cufft-cu12", "nvidia-curand-cu12",
                "nvidia-cusolver-cu12", "nvidia-cusparse-cu12",
                "nvidia-nccl-cu12", "nvidia-nvtx-cu12", "nvidia-nvjitlink-cu12",
                "nvidia-cudnn-cu12", "nvidia-cudnn-cu11",
                "nvidia_cuda_nvrtc_cu12", "NVIDIA-CUSOLVER-Cu12",
                "pytorch-triton", "cuda-python", "ptxas"):
            self.assertTrue(
                bootstrap.is_forbidden_package(name),
                f"{name} must be rejected as a model runtime")
            self.assertTrue(
                doctor.is_forbidden_package(name),
                f"{name} must be rejected by the doctor rule")

    def test_explicit_framework_names_stay_rejected(self):
        for name in ("torch", "torchvision", "torchaudio", "triton",
                     "vllm", "xformers", "flash-attn"):
            self.assertTrue(bootstrap.is_forbidden_package(name))
            self.assertTrue(doctor.is_forbidden_package(name))

    def test_legitimate_packages_are_not_rejected(self):
        for name in ("jsonschema", "numpy", "pyyaml", "transformers",
                     "tokenizers", "jinja2", "markupsafe", "sympy",
                     "typing-extensions", "attrs"):
            self.assertFalse(bootstrap.is_forbidden_package(name))
            self.assertFalse(doctor.is_forbidden_package(name))

    def test_forbidden_rules_are_one_shared_implementation(self):
        """Bootstrap and doctor must share one rule: the doctor imports
        the bootstrap's implementation, so a drift is impossible."""
        self.assertIs(doctor.is_forbidden_package,
                      bootstrap.is_forbidden_package)

    def test_negative_control_declared_nvidia_cuda_wheel_fails_bootstrap(self):
        self.assertEqual(
            bootstrap.forbidden_in_requirements(
                "jsonschema>=4.18,<5\n"
                "nvidia-cuda-nvrtc-cu12==12.6.77\n"),
            ["nvidia-cuda-nvrtc-cu12"])
        self.assertEqual(
            bootstrap.forbidden_in_requirements(
                "nvidia_nccl_cu12>=2.21\n"),
            ["nvidia-nccl-cu12"])

    def test_negative_control_installed_transitive_nvidia_wheel_fails(self):
        """An NVIDIA CUDA wheel found by post-install inspection must
        be reported — the transitive-contamination path. Install is
        stubbed so no real package enters any environment."""
        original = bootstrap.forbidden_installed
        original_install = bootstrap.install

        def contaminated(python: Path) -> list[str]:
            return ["nvidia-cusolver-cu12"]

        def stub_install(python: Path, *args: str) -> None:
            return None

        bootstrap.forbidden_installed = contaminated
        bootstrap.install = stub_install
        try:
            with contextlib.redirect_stderr(io.StringIO()) as captured:
                with self.assertRaises(SystemExit) as raised:
                    bootstrap.bootstrap(ROOT / ".venv")
            self.assertEqual(raised.exception.code, 1)
            self.assertIn("nvidia-cusolver-cu12", captured.getvalue())
            self.assertIn("entered the CPU environment", captured.getvalue())
        finally:
            bootstrap.forbidden_installed = original
            bootstrap.install = original_install

    def test_negative_control_installed_prohibited_runtime_fails_doctor(self):
        original = doctor.installed_versions

        def with_nvidia():
            versions = original()
            versions["nvidia-cuda-nvrtc-cu12"] = "12.6.77"
            return versions

        doctor.installed_versions = with_nvidia
        try:
            findings = doctor.doctor()
        finally:
            doctor.installed_versions = original
        self.assertTrue(
            any("model-runtime" in str(f) for f in findings),
            [str(finding) for finding in findings])


class OldDefectRegressionTests(unittest.TestCase):
    """Prove the NEW controls catch the OLD round-1 defects.

    Each control re-implements the round-1 behavior inline and shows
    the old code accepted/missed what the corrected code rejects.
    """

    def test_old_round1_denylist_missed_common_nvidia_wheels(self):
        """The round-1 exemplar frozenset did not contain the common
        NVIDIA runtime wheels; the generalized rule rejects them."""
        round1_denylist = frozenset({
            "torch", "torchvision", "torchaudio", "triton", "cuda-python",
            "nvidia-cublas-cu12", "nvidia-cuda-runtime-cu12",
            "nvidia-cudnn-cu12", "xformers", "vllm", "flash-attn"})
        for missed in ("nvidia-cuda-nvrtc-cu12", "nvidia-nccl-cu12",
                       "nvidia-cufft-cu12", "nvidia-cusolver-cu12"):
            self.assertNotIn(missed, round1_denylist)  # the old gap
            self.assertTrue(bootstrap.is_forbidden_package(missed))
            self.assertTrue(doctor.is_forbidden_package(missed))

    def test_old_round1_reuse_check_could_not_detect_stale_venv(self):
        """Round-1 create_venv reused any venv with pyvenv.cfg +
        bin/python; show that check alone cannot distinguish a 3.12
        from a 3.13 venv — which is why the corrected code inspects
        the real interpreter."""
        sandbox, venv = sandbox_repo(self)
        venv.mkdir()
        (venv / "pyvenv.cfg").write_text(
            "home = /usr/bin\nversion = 3.13\n", encoding="utf-8")
        (venv / "bin").mkdir()
        (venv / "bin" / "python").symlink_to(sys.executable)

        def round1_reuse_check() -> bool:
            return ((venv / "pyvenv.cfg").is_file()
                    and (venv / "bin" / "python").exists())

        self.assertTrue(round1_reuse_check(),
                        "the old check accepted a stale 3.13 venv")
        # The old check could not see the real interpreter at all; the
        # corrected code requires BOTH channels to agree with the
        # request. Here the channels disagree with each other (cfg
        # says 3.13, real interpreter is the host's), so a request can
        # never be satisfied by both — exactly the stale shape.
        real = bootstrap.venv_interpreter_version(venv / "bin" / "python")
        recorded = bootstrap.venv_python_request(venv)
        self.assertIsNotNone(real)
        self.assertIsNotNone(recorded)
        self.assertTrue(
            real != (3, 12) or recorded != "3.12",
            "the forged venv must fail the corrected dual-channel check")

    def test_old_round1_venv_override_could_target_tracked_dirs(self):
        """Round-1 main() accepted any repo descendant as --venv; show
        that containment check alone accepted scripts/ — which is why
        the override is removed entirely."""
        venv_dir = (ROOT / "scripts" / ".venv").resolve()
        round1_containment_ok = ROOT in venv_dir.parents
        self.assertTrue(
            round1_containment_ok,
            "the old containment check accepted scripts/ as a venv target")
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                bootstrap.validate_venv_target(venv_dir)


class FrozenPinValidationTests(unittest.TestCase):
    """Referenced frozen pins are enforced, parsed dynamically."""

    def test_frozen_pins_are_parsed_from_the_immutable_file(self):
        frozen_path = ROOT / doctor.REFERENCED_REQUIREMENTS[0]
        pins = doctor.parse_frozen_pins(
            frozen_path.read_text(encoding="utf-8"))
        self.assertEqual(pins, {
            "transformers": "==5.17.0",
            "tokenizers": "==0.23.2",
            "jinja2": "==3.1.6",
            "markupsafe": "==3.0.3"})
        # The doctor module itself must not duplicate the pins.
        doctor_source = (ROOT / "scripts" / "check_test_env.py").read_text(
            encoding="utf-8")
        for version in ("5.17.0", "0.23.2", "3.1.6", "3.0.3"):
            self.assertNotIn(
                version, doctor_source,
                f"the doctor duplicates frozen pin {version}; the "
                "immutable file is the only authority")

    def test_negative_control_wrong_frozen_version_fails_the_doctor(self):
        """At least one frozen package at a wrong installed version
        must fail the doctor with the exact mismatch named."""
        original = doctor.installed_versions

        def wrong_transformers():
            versions = original()
            versions["transformers"] = "5.16.0"  # pin is 5.17.0
            return versions

        doctor.installed_versions = wrong_transformers
        try:
            findings = doctor.doctor()
        finally:
            doctor.installed_versions = original
        self.assertTrue(
            any("frozen dependency version mismatch" in str(f)
                and "transformers" in str(f)
                for f in findings),
            [str(finding) for finding in findings])

    def test_negative_control_wrong_jinja2_pin_fails_the_doctor(self):
        original = doctor.installed_versions

        def wrong_jinja2():
            versions = original()
            versions["jinja2"] = "3.1.5"  # pin is 3.1.6
            return versions

        doctor.installed_versions = wrong_jinja2
        try:
            findings = doctor.doctor()
        finally:
            doctor.installed_versions = original
        self.assertTrue(
            any("frozen dependency version mismatch" in str(f)
                and "jinja2" in str(f)
                for f in findings),
            [str(finding) for finding in findings])


class EnvironmentPurityTests(unittest.TestCase):
    """The CPU test environment must not carry model runtimes."""

    def test_this_interpreters_environment_is_model_runtime_free(self):
        violations = bootstrap.forbidden_installed(Path(sys.executable))
        self.assertEqual(violations, [])

    def test_doctor_passes_in_a_canonical_environment(self):
        """The real repository state satisfies the doctor end to end."""
        findings = doctor.doctor()
        self.assertEqual(findings, [], [str(f) for f in findings])


if __name__ == "__main__":
    unittest.main()
