#!/usr/bin/env python3
"""Bootstrap the canonical CPU test environment (Issue #131).

Creates or refreshes the repository-local ``.venv`` and installs the
canonical CPU test dependency set declared in ``requirements-test.txt``
(the single dependency authority, which itself installs the immutable
Issue #117 frozen tokenizer requirements by reference).

Contract:

- **Idempotent** — safe to run repeatedly; an existing healthy ``.venv``
  is upgraded in place with the same requirement set.
- **CPU-only** — refuses to install any model runtime (torch/CUDA/
  Triton/NVIDIA wheels); the requirement graph is screened before
  installation and the environment is re-screened after installation.
- **Non-mutating to the working tree** — writes only inside ``.venv/``
  (gitignored) and ``/tmp``; a full tracked-file digest before/after the
  run proves it. No git state is ever touched.
- **Offline of model runtimes only** — installs from PyPI; it never
  contacts a GPU node or downloads model weights.

Usage::

    python3 scripts/bootstrap_test_env.py            # bootstrap .venv (Python 3.12)
    python3 scripts/bootstrap_test_env.py --venv DIR # explicit venv dir

The canonical suite interpreter is Python 3.12: the accepted Issue
#129 real-tokenizer proof pins its frozen software identity to 3.12,
so the bootstrap requests a 3.12 interpreter (using an installed one,
or letting ``uv`` fetch a managed one when the system python differs)
and the doctor rejects any other minor version.

Afterwards run the doctor and the suite::

    .venv/bin/python scripts/check_test_env.py
    .venv/bin/python -m unittest discover -s tests -p 'test_*.py'
"""
from __future__ import annotations

import argparse
import hashlib
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQUIREMENTS = ROOT / "requirements-test.txt"
VENV = ROOT / ".venv"

# Model-runtime package names whose presence in the CPU test environment
# is prohibited (Issue #131: heavy GPU/model dependencies must not enter
# the ordinary CPU bootstrap).
FORBIDDEN_PACKAGES = frozenset({
    "torch", "torchvision", "torchaudio", "triton", "cuda-python",
    "nvidia-cublas-cu12", "nvidia-cuda-runtime-cu12", "nvidia-cudnn-cu12",
    "xformers", "vllm", "flash-attn",
})

# The freeze takes a module-level import of the doctor so negative
# controls can assert the contract constants without a subprocess.
sys.path.insert(0, str(ROOT / "scripts"))


def tracked_file_digests() -> dict[str, str]:
    """Digest every tracked path (staged content or HEAD blob)."""
    digests: dict[str, str] = {}
    listing = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files", "-z"],
        capture_output=True, check=True).stdout
    for relative in listing.split(b"\0"):
        if not relative:
            continue
        path = ROOT / relative.decode()
        if path.is_file() and not path.is_symlink():
            digests[relative.decode()] = hashlib.sha256(
                path.read_bytes()).hexdigest()
    return digests


def forbidden_in_requirements(text: str) -> list[str]:
    """Return forbidden package names referenced by a requirements text."""
    found: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or line.startswith("-r"):
            continue
        match = re.match(r"([A-Za-z0-9][A-Za-z0-9._-]*)", line)
        if match is None:
            continue
        name = match.group(1)
        for candidate in {name.lower(), name.lower().replace("_", "-")}:
            if candidate in FORBIDDEN_PACKAGES:
                found.append(candidate)
                break
    return found


def forbidden_installed(python: Path) -> list[str]:
    """Return forbidden packages importable/present in the environment."""
    probe = (
        "import importlib.metadata as m, sys\n"
        "names = {}\n"
        "for d in m.distributions():\n"
        "    n = (d.metadata.get('Name') or '').lower().replace('_','-')\n"
        "    if n:\n"
        "        names[n] = d.version\n"
        "for n in names:\n"
        "    print(n, names[n])\n"
    )
    result = subprocess.run([str(python), "-c", probe],
                            capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError("environment enumeration failed: "
                           + result.stderr.strip())
    return sorted(line.split()[0] for line in result.stdout.splitlines()
                  if line.split()[0] in FORBIDDEN_PACKAGES)


def _fail(message: str) -> None:
    print(f"bootstrap: {message}", file=sys.stderr)
    raise SystemExit(1)


def create_venv(venv_dir: Path, python_request: str = "3.12") -> Path:
    """Create the venv with stdlib, falling back to ``uv``.

    ``python_request`` is the canonical suite interpreter (3.12; the
    accepted Issue #129 real-tokenizer proof pins that identity). If the
    launching interpreter already matches, it is used directly; otherwise
    ``uv`` resolves or fetches the requested version.
    """
    if (venv_dir / "pyvenv.cfg").is_file() and (venv_dir / "bin" / "python").exists():
        return venv_dir / "bin" / "python"
    if venv_dir.exists():
        # A partial venv from a failed creation attempt is not reusable.
        shutil.rmtree(venv_dir, ignore_errors=True)
    launching = f"{sys.version_info.major}.{sys.version_info.minor}"
    if launching == python_request:
        if subprocess.run([sys.executable, "-m", "venv", str(venv_dir)],
                          capture_output=True).returncode == 0:
            return venv_dir / "bin" / "python"
        # stdlib venv may fail (Debian ships venv without ensurepip).
        shutil.rmtree(venv_dir, ignore_errors=True)
    uv = subprocess.run(["uv", "venv", "--python", python_request,
                         str(venv_dir)], capture_output=True)
    if uv.returncode != 0:
        _fail(f"cannot create the Python {python_request} virtual "
              "environment: stdlib venv and uv both failed; install "
              f"python{python_request}-venv or uv")
    return venv_dir / "bin" / "python"


def pip_available(python: Path) -> bool:
    return subprocess.run([str(python), "-m", "pip", "--version"],
                          capture_output=True).returncode == 0


def install(python: Path, *args: str) -> None:
    """Install with stdlib pip, falling back to ``uv pip``."""
    if pip_available(python):
        command = [str(python), "-m", "pip", "install", "--disable-pip-version-check", *args]
        completed = subprocess.run(command)
    else:
        completed = subprocess.run(
            ["uv", "pip", "install", "--python", str(python), *args])
    if completed.returncode != 0:
        _fail("dependency installation failed (exit "
              f"{completed.returncode})")


def bootstrap(venv_dir: Path = VENV, python_request: str = "3.12") -> Path:
    """Create/refresh the environment; returns the venv interpreter."""
    if not REQUIREMENTS.is_file():
        _fail(f"missing dependency authority: {REQUIREMENTS}")

    requirements_text = REQUIREMENTS.read_text(encoding="utf-8")
    violations = forbidden_in_requirements(requirements_text)
    if violations:
        _fail("dependency authority declares model-runtime packages ("
              + ", ".join(violations) + ") — refusing to bootstrap")

    # Referenced frozen requirement files inherit the same screen.
    for raw_line in requirements_text.splitlines():
        line = raw_line.strip()
        if line.startswith("-r "):
            referenced = (ROOT / line[3:].strip()).resolve()
            if not referenced.is_file():
                _fail(f"referenced requirements file is missing: {referenced}")
            violations = forbidden_in_requirements(
                referenced.read_text(encoding="utf-8"))
            if violations:
                _fail("referenced requirements declare model-runtime "
                      "packages (" + ", ".join(violations) + ") — "
                      "refusing to bootstrap")

    before = tracked_file_digests()
    python = create_venv(venv_dir, python_request)
    install(python, "-r", str(REQUIREMENTS))
    present = forbidden_installed(python)
    if present:
        _fail("model-runtime packages entered the CPU environment ("
              + ", ".join(present) + ") — this is a dependency-authority "
              "bug; the environment is not qualified for the CPU suite")
    after = tracked_file_digests()
    if before != after:
        changed = sorted(set(before) ^ set(after)
                         | {p for p in set(before) & set(after)
                            if before[p] != after[p]})
        _fail("bootstrap modified tracked repository files: "
              + ", ".join(changed))
    return python


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--venv", type=Path, default=VENV,
        help="virtual environment directory (default: <repo>/.venv)")
    parser.add_argument(
        "--python", default="3.12", dest="python_request",
        help="canonical suite interpreter request (default: 3.12; the "
             "Issue #129 frozen tokenizer identity pins it)")
    args = parser.parse_args(argv)
    venv_dir = args.venv.resolve()
    if ROOT not in venv_dir.parents and venv_dir != (ROOT / ".venv").resolve():
        _fail("the bootstrap venv must live inside the repository")
    python = bootstrap(venv_dir, args.python_request)
    print("CPU test environment ready:", python)
    print("Next: run the doctor and the suite:")
    print(f"  {python} scripts/check_test_env.py")
    print(f"  {python} -m unittest discover -s tests -p 'test_*.py'")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
