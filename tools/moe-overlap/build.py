#!/usr/bin/env python3
"""Build the MoE overlap prototype harness against the pinned llama.cpp sources.

Bounded engineering support for tools/moe-overlap (prototype; no campaign
authority implied). Downloads the pinned llama.cpp source tarball exactly once
into a cache directory (sha256-pinned), then compiles the harness plus the
minimal ggml CPU translation-unit closure with the same direct-GCC recipe
approach as inferswarm/operator/native_observer/build.py (no CMake, no
installs, no persistent artifacts outside the cache).

CPU-only is the default (offline validation). --cuda additionally compiles the
CUDA TU closure for the hardware host (requires nvcc and the CUDA toolkit);
it is a build action only and never runs the harness.

Usage:
  python3 tools/moe-overlap/build.py [--cache DIR] [--cuda] [--jobs N]

Environment:
  MOE_OVERLAP_SOURCE   existing extracted llama.cpp pin root (skips download)
  MOE_OVERLAP_TARBALL  existing pin tarball path (skips download, still verified)
"""
from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import tarfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.request import urlopen

PIN = "b29c606e28a01b1bc8c1351026a0fa6e616bf6c4"
TARBALL_SHA256 = "03fb04316eb32a7b7347004a79a8dd60531c02f5a064d853fed3b53828951723"
TARBALL_URL = f"https://github.com/ggml-org/llama.cpp/archive/{PIN}.tar.gz"

REPO = Path(__file__).resolve().parents[2]
HARNESS = REPO / "tools" / "moe-overlap" / "moe_overlap_harness.cpp"
DEFAULT_CACHE = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "inferswarm-moe-overlap"

# Minimal ggml CPU closure (mirrors inferswarm/operator/native_observer/full_build.py,
# trimmed to what the harness links: no RPC, no llama.* sources, no subprocess).
C_SOURCES = ["ggml/src/ggml.c", "ggml/src/ggml-alloc.c", "ggml/src/ggml-quants.c",
             "ggml/src/ggml-cpu/ggml-cpu.c", "ggml/src/ggml-cpu/repack.cpp",
             "ggml/src/ggml-cpu/iqp.cpp", "ggml/src/ggml-cpu/quants.c",
             "ggml/src/ggml-cpu/arch/x86/quants.c",
             "ggml/src/ggml-cpu/arch/x86/repack.cpp"]
CXX_SOURCES = ["ggml/src/ggml.cpp", "ggml/src/ggml-backend.cpp", "ggml/src/ggml-backend-meta.cpp",
               "ggml/src/ggml-backend-reg.cpp", "ggml/src/ggml-backend-dl.cpp",
               "ggml/src/ggml-threading.cpp", "ggml/src/gguf.cpp",
               "ggml/src/ggml-cpu/ggml-cpu.cpp", "ggml/src/ggml-cpu/traits.cpp",
               "ggml/src/ggml-cpu/binary-ops.cpp", "ggml/src/ggml-cpu/unary-ops.cpp",
               "ggml/src/ggml-cpu/vec.cpp", "ggml/src/ggml-cpu/ops.cpp"]
CUDA_SOURCES = ["ggml/src/ggml-cuda/ggml-cuda.cu"]  # the pin builds one fat CUDA TU

BASE_FLAGS = ["-O3", "-pthread", "-D_GNU_SOURCE", "-D_FILE_OFFSET_BITS=64",
              "-DGGML_SCHED_MAX_COPIES=4", "-DGGML_USE_CPU"]
# Tests may trade optimization for compile time; hardware runs keep -O3.
OPT = os.environ.get("MOE_OVERLAP_OPT", "-O3")
BASE_FLAGS[0] = OPT
INCLUDES = ["ggml/include", "ggml/src", "ggml/src/ggml-cpu", "ggml/src/ggml-cpu/include"]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def pick_compiler(kind: str) -> str:
    """Prefer $CC/$CXX; otherwise pick the first candidate that can compile.

    A broken system compiler (e.g. a replaced gcc that cannot spawn cc1) must
    not abort the build when another toolchain works.
    """
    env = os.environ.get("CC" if kind == "c" else "CXX")
    if env:
        return env
    for cand in (["gcc", "clang", "cc"] if kind == "c" else ["g++", "clang++", "c++"]):
        if not shutil.which(cand):
            continue
        src = out_smoke = None
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=(".c" if kind == "c" else ".cpp"), delete=False) as f:
            f.write("int main(void){return 0;}\n" if kind == "c" else "int main(){return 0;}\n")
            src = f.name
        out_smoke = src + ".o"
        try:
            r = subprocess.run([cand, "-c", src, "-o", out_smoke],
                               capture_output=True, timeout=60)
            if r.returncode == 0:
                return cand
        except subprocess.TimeoutExpired:
            pass
        finally:
            for p in (src, out_smoke):
                try:
                    os.unlink(p)
                except OSError:
                    pass
    raise SystemExit("no working C/C++ compiler found")


def write_ggml_version(source: Path, out_dir: Path) -> None:
    """The pin ships ggml-version.h.in; generate the header as CMake would."""
    header = out_dir / "generated" / "ggml-version.h"
    if not header.is_file():
        header.parent.mkdir(parents=True, exist_ok=True)
        header.write_text(
            "#pragma once\n\n"
            f'#define GGML_VERSION "0.24.0"\n'
            f'#define GGML_COMMIT "{PIN[:7]}"\n')


def ensure_source(cache: Path) -> Path:
    root = cache / "llama.cpp-pin"
    if os.environ.get("MOE_OVERLAP_SOURCE"):
        root = Path(os.environ["MOE_OVERLAP_SOURCE"])
        if not (root / "ggml" / "src" / "ggml.c").is_file():
            raise SystemExit(f"MOE_OVERLAP_SOURCE invalid: {root}")
        return root
    marker = root / ".pin-ok"
    if marker.is_file():
        return root
    tarball = Path(os.environ["MOE_OVERLAP_TARBALL"]) if os.environ.get("MOE_OVERLAP_TARBALL") else cache / "pin.tar.gz"
    if not tarball.is_file():
        cache.mkdir(parents=True, exist_ok=True)
        print(f"downloading {TARBALL_URL}")
        with urlopen(TARBALL_URL) as r, open(tarball, "wb") as f:
            shutil.copyfileobj(r, f)
    got = sha256_file(tarball)
    if got != TARBALL_SHA256:
        raise SystemExit(f"tarball sha256 mismatch: {got} != {TARBALL_SHA256}")
    if not root.is_dir():
        with tarfile.open(tarball, "r:gz") as t:
            t.extractall(cache)
        (cache / f"llama.cpp-{PIN}").rename(root)
    marker.write_text(PIN + "\n")
    return root


def build(source: Path, out_dir: Path, jobs: int, cuda: bool) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    cc = pick_compiler("c")
    cxx = pick_compiler("c++")
    write_ggml_version(source, out_dir)
    inc = [f"-I{out_dir / 'generated'}"] + [f"-I{source / p}" for p in INCLUDES]
    print(f"compilers: CC={cc} CXX={cxx}")

    objects: list[Path] = []

    def obj_path(rel: str) -> Path:
        return out_dir / (rel.replace("/", "__") + ".o")

    jobs_list = []
    for s in C_SOURCES:
        o = obj_path(s)
        objects.append(o)
        flags = ["-std=c17"] if s.endswith(".c") else ["-std=c++17"]
        jobs_list.append(([cc if s.endswith(".c") else cxx], s, o, flags))
    for s in CXX_SOURCES:
        o = obj_path(s)
        objects.append(o)
        jobs_list.append(([cxx], s, o, ["-std=c++17"]))
    harness_o = out_dir / "moe_overlap_harness.o"
    objects.append(harness_o)
    jobs_list.append(([cxx], str(HARNESS), harness_o, ["-std=c++17"]))

    def compile_one(cmd_prefix, src, o, std):
        if o.is_file():
            return
        src_path = source / src if not src.startswith("/") else Path(src)
        cmd = [*cmd_prefix, *BASE_FLAGS, *std, *inc, "-c", str(src_path), "-o", str(o)]
        subprocess.run(cmd, check=True)

    with ThreadPoolExecutor(max_workers=jobs) as ex:
        futs = [ex.submit(compile_one, *j) for j in jobs_list]
        for f in futs:
            f.result()

    if cuda:
        nvcc = shutil.which("nvcc") or shutil.which("/usr/local/cuda/bin/nvcc")
        if not nvcc:
            raise SystemExit("nvcc not found; CUDA build requires the CUDA toolkit")
        cuda_flags = ["-O3", "-std=c++17", "--compiler-options", "-fPIC",
                      "-DGGML_SCHED_MAX_COPIES=4", "-arch=sm_86"]
        for s in CUDA_SOURCES:
            o = obj_path(s)
            objects.append(o)
            cmd = [nvcc, *cuda_flags, *inc, "-c", str(source / s), "-o", str(o)]
            print("nvcc:", s)
            subprocess.run(cmd, check=True)

    binary = out_dir / ("moe_overlap_harness_cuda" if cuda else "moe_overlap_harness")
    link = [cxx, *BASE_FLAGS, "-std=c++17"]
    if cuda:
        link.append("-DGGML_USE_CUDA")
    link += [str(o) for o in objects]
    if cuda:
        link += ["-L/usr/local/cuda/lib64", "-lcudart", "-lcublas", "-lcublasLt", "-lculibos"]
    link += ["-o", str(binary)]
    print("linking", binary.name)
    subprocess.run(link, check=True)
    return binary


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    ap.add_argument("--cuda", action="store_true")
    ap.add_argument("--jobs", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    args = ap.parse_args()
    source = ensure_source(args.cache)
    out_dir = args.cache / ("build-cuda" if args.cuda else "build-cpu")
    binary = build(source, out_dir, args.jobs, args.cuda)
    # marker line: robust machine-readable handoff (stray env/log output may
    # follow the binary path in some sandboxes)
    print(f"MOE_OVERLAP_BINARY {binary}")
    print(binary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
