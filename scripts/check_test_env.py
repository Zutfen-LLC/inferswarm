#!/usr/bin/env python3
"""Fast CPU test-environment doctor (Issue #131).

Verifies — before the expensive suite starts — that the interpreter has
every dependency the canonical CPU test/check surface declares in
``requirements-test.txt``, that no model runtime leaked into the
environment, that required external executables exist, and that CI and
documentation still consume the canonical contract instead of ad-hoc
package installs.

Fail-closed: any missing dependency, forbidden package, missing
external tool, or contract drift exits nonzero with a precise reason.
A doctor PASS is a precondition for claiming test results; a missing
declared dependency is an environment setup failure, never a
"pre-existing test failure".

Usage::

    python3 scripts/check_test_env.py           # check this interpreter
    .venv/bin/python scripts/check_test_env.py  # check the bootstrapped venv
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQUIREMENTS = ROOT / "requirements-test.txt"
CI_WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
DOCS_CONTRACT = {
    "CONTRIBUTING.md": ("bootstrap_test_env.py", "check_test_env.py"),
    "tests/README.md": ("bootstrap_test_env.py", "check_test_env.py"),
}

# Minimum supported interpreter (CI pins 3.12; the suite needs >= 3.11).
MIN_PYTHON = (3, 11)

# The accepted Issue #129 real-tokenizer proof pins the exact interpreter
# identity (scripts/issue129_arm_c_retry_core.py TOKENIZER_PYTHON); running
# its modules under any other minor version fails the frozen software
# identity check mid-suite. The doctor fails fast instead.
REQUIRED_EXACT_PYTHON = ("3", "12")

# Living CPU test dependencies that the doctor must find importable.
# This mirrors requirements-test.txt's direct (non-referenced) entries;
# the authority check below proves the mirror cannot drift silently.
EXPECTED_DIRECT_PACKAGES = frozenset({"jsonschema", "numpy", "pyyaml"})

# Referenced immutable frozen requirement files (authoritative for their
# own exact pins; the doctor verifies presence, not duplication).
REFERENCED_REQUIREMENTS = (
    "docs/implementation/r6-successor-dense-full-integration-117/"
    "evidence/arm-c-retry/frozen-tokenizer/requirements.txt",
)

# Frozen tokenizer packages that specific CPU tests import directly.
FROZEN_TOKENIZER_PACKAGES = frozenset({
    "transformers", "tokenizers", "jinja2", "markupsafe"})

# External (non-Python) executables the ordinary CPU suite shells out to.
REQUIRED_EXECUTABLES = ("openssl",)

# Model-runtime packages prohibited from the CPU test environment.
FORBIDDEN_PACKAGES = frozenset({
    "torch", "torchvision", "torchaudio", "triton", "cuda-python",
    "nvidia-cublas-cu12", "nvidia-cuda-runtime-cu12", "nvidia-cudnn-cu12",
    "xformers", "vllm", "flash-attn",
})

# pip requirement line -> distribution-name normalization (PEP 503).
def _normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).strip().lower()


class DoctorError(ValueError):
    """One fail-closed doctor finding."""


def parse_requirements(text: str) -> tuple[set[str], set[str]]:
    """Return (direct package names, referenced requirement paths)."""
    packages: set[str] = set()
    references: set[str] = set()
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("-r ") or line.startswith("-c "):
            references.add(line.split()[1])
            continue
        match = re.match(r"([A-Za-z0-9][A-Za-z0-9._-]*)", line)
        if match is None:
            raise DoctorError(f"unparseable requirement line: {line!r}")
        packages.add(_normalize(match.group(1)))
    return packages, references


def check_python_version() -> None:
    if sys.version_info[:2] < MIN_PYTHON:
        raise DoctorError(
            f"unsupported interpreter {sys.version.split()[0]}; the CPU "
            f"test environment requires Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+")
    if (str(sys.version_info.major), str(sys.version_info.minor)) != (
            REQUIRED_EXACT_PYTHON):
        raise DoctorError(
            f"interpreter {sys.version.split()[0]} is not the pinned "
            f"CPU-suite interpreter {'.'.join(REQUIRED_EXACT_PYTHON)}: the "
            "accepted Issue #129 real-tokenizer proof pins its software "
            "identity to Python 3.12 and fails under any other minor "
            "version. Bootstrap with a 3.12 interpreter "
            "(scripts/bootstrap_test_env.py --python3.12 or set "
            "UV_PYTHON=3.12)")


def installed_versions() -> dict[str, str]:
    import importlib.metadata as metadata
    versions: dict[str, str] = {}
    for distribution in metadata.distributions():
        name = (distribution.metadata.get("Name") or "").strip().lower()
        if name:
            versions[_normalize(name)] = distribution.version
    return versions


def parse_bound(spec: str, package: str) -> tuple[str | None, str | None]:
    """Extract (floor, ceiling) from a simple bounded specifier."""
    floor = ceiling = None
    for match in re.finditer(r"(>=|<|==|~=)\s*([0-9][0-9A-Za-z.*-]*)", spec):
        operator, version = match.groups()
        if operator == ">=":
            floor = version
        elif operator == "<":
            ceiling = version
        elif operator == "==":
            floor = ceiling = version
        elif operator == "~=":
            floor = version
    return floor, ceiling


def _version_tuple(version: str) -> tuple[int, ...]:
    match = re.match(r"[0-9]+(\.[0-9]+)*", version)
    if match is None:
        raise DoctorError(f"unparseable version string: {version!r}")
    return tuple(int(part) for part in match.group(0).split("."))


def check_dependencies(requirements_text: str,
                       versions: dict[str, str]) -> None:
    packages, references = parse_requirements(requirements_text)
    # Authority/doctor agreement: the doctor's expected direct set must
    # exactly match the direct entries of the canonical file.
    if packages != EXPECTED_DIRECT_PACKAGES:
        raise DoctorError(
            "dependency authority drift: requirements-test.txt direct "
            f"entries {sorted(packages)} do not match the doctor's "
            f"expected set {sorted(EXPECTED_DIRECT_PACKAGES)}; update "
            "scripts/check_test_env.py in the same change as the "
            "authority file")
    for relative in REFERENCED_REQUIREMENTS:
        if not (ROOT / relative).is_file():
            raise DoctorError(
                f"referenced frozen requirements file is missing: {relative}")
    if references != {REFERENCED_REQUIREMENTS[0]}:
        raise DoctorError(
            "referenced requirements drift: authority references "
            f"{sorted(references)} but the accepted frozen tokenizer "
            f"contract is {REFERENCED_REQUIREMENTS[0]}")
    for raw_line in requirements_text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or line.startswith(("-r ", "-c ")):
            continue
        match = re.match(r"([A-Za-z0-9][A-Za-z0-9._-]*)", line)
        if match is None:
            raise DoctorError(f"unparseable requirement line: {line!r}")
        package = _normalize(match.group(1))
        if package not in versions:
            raise DoctorError(f"declared dependency is not installed: {package}")
        floor, ceiling = parse_bound(line, package)
        installed = _version_tuple(versions[package])
        if floor is not None and installed < _version_tuple(floor):
            raise DoctorError(
                f"{package} {versions[package]} is older than the declared "
                f"floor {floor}")
        if ceiling is not None and installed >= _version_tuple(ceiling):
            raise DoctorError(
                f"{package} {versions[package]} violates the declared "
                f"ceiling <{ceiling}")
    for package in FROZEN_TOKENIZER_PACKAGES:
        if package not in versions:
            raise DoctorError(
                "frozen tokenizer dependency is not installed: "
                f"{package} (install the immutable Issue #117 requirements "
                "referenced by requirements-test.txt)")


def check_forbidden(versions: dict[str, str]) -> None:
    present = sorted(FORBIDDEN_PACKAGES & set(versions))
    if present:
        raise DoctorError(
            "model-runtime packages present in the CPU test environment: "
            + ", ".join(present))


def check_executables() -> None:
    for executable in REQUIRED_EXECUTABLES:
        probe = subprocess.run(["sh", "-c", f"command -v {executable}"],
                               capture_output=True, text=True)
        if probe.returncode != 0 or not probe.stdout.strip():
            raise DoctorError(
                f"required external executable is not on PATH: {executable}")


def check_ci_contract() -> None:
    if not CI_WORKFLOW.is_file():
        raise DoctorError("CI workflow is missing")
    workflow = CI_WORKFLOW.read_text(encoding="utf-8")
    # CI must install from the canonical authority, not ad-hoc packages.
    if not re.search(r"bootstrap_test_env\.py", workflow):
        raise DoctorError(
            "CI no longer bootstraps from scripts/bootstrap_test_env.py; "
            "CI must consume the canonical dependency contract")
    # Any ad-hoc Python package install outside the contract is drift.
    for match in re.finditer(r"^\s*(?:run:\s*)?(.*)pip install(.*)$",
                             workflow, re.MULTILINE):
        command = (match.group(1) + "pip install" + match.group(2)).strip()
        if "-r " in command and "requirements-test.txt" in command:
            continue
        raise DoctorError(
            "CI installs Python packages outside the canonical contract: "
            f"'{command}'")


def check_docs_contract() -> None:
    for relative, commands in DOCS_CONTRACT.items():
        path = ROOT / relative
        if not path.is_file():
            raise DoctorError(f"documented contract file is missing: {relative}")
        text = path.read_text(encoding="utf-8")
        for command in commands:
            if command not in text:
                raise DoctorError(
                    f"{relative} no longer names the canonical bootstrap/"
                    f"doctor command ({command})")
        if re.search(r"pip install[^\n]*\b(jsonschema|numpy|pyyaml)\b",
                     text):
            raise DoctorError(
                f"{relative} still documents a package-specific "
                "'pip install' command instead of the canonical bootstrap")


def doctor() -> list[DoctorError]:
    findings: list[DoctorError] = []
    if not REQUIREMENTS.is_file():
        return [DoctorError(
            f"canonical dependency authority is missing: {REQUIREMENTS}")]
    requirements_text = REQUIREMENTS.read_text(encoding="utf-8")
    for check in (check_python_version,
                  lambda: check_dependencies(requirements_text,
                                             installed_versions()),
                  lambda: check_forbidden(installed_versions()),
                  check_executables,
                  check_ci_contract,
                  check_docs_contract):
        try:
            check()
        except DoctorError as error:
            findings.append(error)
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.parse_args(argv)
    findings = doctor()
    for error in findings:
        print(f"doctor: FAIL {error}", file=sys.stderr)
    if findings:
        print("doctor: environment NOT qualified — fix the findings above "
              "before running or claiming the CPU test suite",
              file=sys.stderr)
        return 1
    print(f"doctor: OK — CPU test environment qualified "
          f"(python {sys.version.split()[0]})")
    print("doctor: run the suite with:")
    print("  python3 -m unittest discover -s tests -p 'test_*.py'")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
