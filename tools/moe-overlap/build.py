#!/usr/bin/env python3
"""Build the MoE overlap prototype harness against the pinned llama.cpp sources.

Bounded engineering support for tools/moe-overlap (prototype; no campaign
authority implied). Downloads the pinned llama.cpp source tarball exactly once
into a cache directory (sha256-pinned), verifies the tree against selected
complete-file digests recorded in the accepted #299 runtime contract, then
compiles the harness plus the ggml CPU translation-unit closure with a direct
GCC/Clang recipe (no CMake, no installs, no persistent artifacts outside the
cache). Object files carry stamps (source hash + flags + compiler) and are
rebuilt whenever any of those changes — a stale cached build cannot silently
test old code.

CPU-only is the default (offline validation). --cuda additionally compiles the
complete CUDA closure at this pin (every ggml/src/ggml-cuda/*.cu plus the
template-instance TUs, as the pin's own CMake GLOBs do) with GGML_USE_CUDA
defined at compile time for every TU so backend registration is enabled; it is
a build action only and never runs the harness.

Usage:
  python3 tools/moe-overlap/build.py [--cache DIR] [--cuda] [--jobs N]

Environment:
  MOE_OVERLAP_SOURCE   existing extracted llama.cpp pin root (identity-verified,
                       never trusted by path alone)
  MOE_OVERLAP_TARBALL  existing pin tarball path (skips download, still verified)
  MOE_OVERLAP_OPT      optimization level override (default -O3; tests may use -O1)
"""
from __future__ import annotations

import argparse
import glob
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

# The source tree is identity-verified on every use against the complete-file
# SHA-256 table of the accepted #299 runtime contract
# (docs/implementation/profiled-q8-299/runtime-contract.md), parsed at runtime
# from that authority file — no hand-transcribed digests (a mistyped constant
# in an earlier revision slipped through a marker shortcut locally and was
# caught only by a fresh runner cache).
CONTRACT_PATH = Path(__file__).resolve().parents[2] / "docs/implementation/profiled-q8-299/runtime-contract.md"
CONTRACT_VERIFY_FILES = [
    "ggml/src/ggml-backend.cpp",
    "ggml/src/ggml-cuda/ggml-cuda.cu",
    "ggml/src/ggml-cuda/common.cuh",
    "ggml/src/ggml-cuda/top-k.cu",
    "ggml/src/ggml-rpc/ggml-rpc.cpp",
    "src/models/qwen4exp.cpp",
    "src/llama-model.cpp",
    "src/llama-arch.cpp",
]


def _contract_digests() -> dict:
    import re as _re
    text = CONTRACT_PATH.read_text()
    table = {}
    for m in _re.finditer(r"^\| `([^`]+)` \| `([0-9a-f]{64})` \|$",
                          text, _re.MULTILINE):
        table[m.group(1)] = m.group(2)
    if not table:
        raise SystemExit(f"cannot parse digest table from {CONTRACT_PATH}")
    missing = [f for f in CONTRACT_VERIFY_FILES if f not in table]
    if missing:
        raise SystemExit(f"contract table lacks: {missing}")
    return {f: table[f] for f in CONTRACT_VERIFY_FILES}


REPO = Path(__file__).resolve().parents[2]
HARNESS = REPO / "tools" / "moe-overlap" / "moe_overlap_harness.cpp"
DEFAULT_CACHE = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "inferswarm-moe-overlap"

# Minimal ggml CPU closure (mirrors inferswarm/operator/native_observer/full_build.py,
# trimmed to what the harness links: no llama.* sources, no subprocess). The
# pinned RPC backend (client + TCP transport) is linked into the same binary
# for the --secondary rpc mode; GGML_USE_RPC is NOT defined so global device
# registration is unchanged — the harness reaches the backend through
# ggml_backend_rpc_init() directly.
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
               "ggml/src/ggml-cpu/vec.cpp", "ggml/src/ggml-cpu/ops.cpp",
               "ggml/src/ggml-rpc/ggml-rpc.cpp", "ggml/src/ggml-rpc/transport.cpp"]

BASE_FLAGS = ["-O3", "-pthread", "-D_GNU_SOURCE", "-D_FILE_OFFSET_BITS=64",
              "-DGGML_SCHED_MAX_COPIES=4", "-DGGML_USE_CPU"]
# Tests may trade optimization for compile time; hardware runs keep -O3.
BASE_FLAGS[0] = os.environ.get("MOE_OVERLAP_OPT", "-O3")
INCLUDES = ["ggml/include", "ggml/src", "ggml/src/ggml-cpu", "ggml/src/ggml-cpu/include",
            "ggml/src/ggml-rpc"]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_pin_identity(root: Path) -> None:
    """Verify the tree really is the pin via the #299 contract digests."""
    for rel, want in _contract_digests().items():
        p = root / rel
        if not p.is_file():
            raise SystemExit(f"pin identity check: missing {rel} in {root}")
        got = sha256_file(p)
        if got != want:
            raise SystemExit(
                f"pin identity check FAILED for {rel}: {got} != {want} "
                f"(source tree is not llama.cpp {PIN[:12]}; refusing to build)")


def pick_compiler(kind: str) -> str:
    """Prefer $CC/$CXX; otherwise pick the first candidate that can compile.

    A broken system compiler (e.g. a replaced gcc that cannot spawn cc1) must
    not abort the build when another toolchain works.
    """
    env = os.environ.get("CC" if kind == "c" else "CXX")
    if env:
        return env
    import tempfile
    for cand in (["gcc", "clang", "cc"] if kind == "c" else ["g++", "clang++", "c++"]):
        if not shutil.which(cand):
            continue
        with tempfile.NamedTemporaryFile("w", suffix=(".c" if kind == "c" else ".cpp"), delete=False) as f:
            f.write("int main(void){return 0;}\n" if kind == "c" else "int main(){return 0;}\n")
            src = f.name
        out = src + ".o"
        try:
            r = subprocess.run([cand, "-c", src, "-o", out], capture_output=True, timeout=60)
            if r.returncode == 0:
                return cand
        except subprocess.TimeoutExpired:
            pass
        finally:
            for p in (src, out):
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
            '#define GGML_VERSION "0.24.0"\n'
            f'#define GGML_COMMIT "{PIN[:7]}"\n')


def ensure_source(cache: Path) -> Path:
    root = cache / "llama.cpp-pin"
    if os.environ.get("MOE_OVERLAP_SOURCE"):
        root = Path(os.environ["MOE_OVERLAP_SOURCE"])
        if not (root / "ggml" / "src" / "ggml.c").is_file():
            raise SystemExit(f"MOE_OVERLAP_SOURCE invalid: {root}")
        # a source override must still prove it IS the pin, not just claim it
        verify_pin_identity(root)
        return root
    # identity is verified on every use (cheap: a handful of files); a stale
    # marker must never shortcut it — a mistyped digest in an earlier revision
    # slipped through exactly such a shortcut locally and was only caught by a
    # fresh runner cache
    marker = root / ".pin-ok"
    if marker.is_file():
        verify_pin_identity(root)
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
    verify_pin_identity(root)
    marker.write_text(PIN + "\n")
    return root


def cuda_sources(source: Path) -> list[str]:
    """The pin's CUDA closure: every top-level .cu plus the template-instance
    TUs its own CMakeLists GLOBs (fattn-tile*, fattn-mma*, mmq*, mmf*)."""
    top = sorted(str(p.relative_to(source)) for p in
                 (source / "ggml/src/ggml-cuda").glob("*.cu"))
    inst = sorted(str(p.relative_to(source)) for p in
                  (source / "ggml/src/ggml-cuda/template-instances").glob("*.cu"))
    if not top or not inst:
        raise SystemExit("unexpected source layout: no CUDA TUs found")
    return top + inst


def build(source: Path, out_dir: Path, jobs: int, cuda: bool, rpc_worker: bool = False) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    cc = pick_compiler("c")
    cxx = pick_compiler("c++")
    write_ggml_version(source, out_dir)
    flags = list(BASE_FLAGS)
    if cuda:
        # compile-time for every TU: ggml-backend-reg.cpp registers the CUDA
        # backend only under this define, so it cannot be a link-time-only flag
        flags.append("-DGGML_USE_CUDA")
    inc = [f"-I{out_dir / 'generated'}"] + [f"-I{source / p}" for p in INCLUDES]
    print(f"compilers: CC={cc} CXX={cxx} opt={flags[0]} cuda={cuda}")

    stamp_dir = out_dir / "stamps"
    stamp_dir.mkdir(exist_ok=True)

    def obj_path(rel: str) -> Path:
        return out_dir / (rel.replace("/", "__") + ".o")

    def compile_one(cmd_prefix, src_str, o, extra_flags, nvcc=False):
        src = Path(src_str)
        src_path = source / src if not src.is_absolute() else src
        key_src = HARNESS if src_path == HARNESS else src_path
        used = list(flags) if not nvcc else list(NVCC_FLAGS)
        key = hashlib.sha256(
            ("|".join([sha256_file(key_src), " ".join(used), " ".join(extra_flags),
                       " ".join(cmd_prefix)])).encode()).hexdigest()
        stamp = stamp_dir / (o.name + ".stamp")
        if o.is_file() and stamp.is_file() and stamp.read_text() == key:
            return  # unchanged source, flags and compiler: reuse the object
        cmd = [*cmd_prefix, *used, *extra_flags, *inc, "-c", str(src_path), "-o", str(o)]
        subprocess.run(cmd, check=True)
        stamp.write_text(key)

    # nvcc does not forward arbitrary host flags; the CUDA TUs get their own set
    NVCC_FLAGS = ["-O3", "-D_GNU_SOURCE", "-D_FILE_OFFSET_BITS=64",
                  "-DGGML_SCHED_MAX_COPIES=4", "-DGGML_USE_CUDA"]

    jobs_list = []
    objects: list[Path] = []

    for s in C_SOURCES:
        o = obj_path(s)
        objects.append(o)
        jobs_list.append(([cc if s.endswith(".c") else cxx], s, o,
                          ["-std=c17"] if s.endswith(".c") else ["-std=c++17"]))
    for s in CXX_SOURCES:
        o = obj_path(s)
        objects.append(o)
        jobs_list.append(([cxx], s, o, ["-std=c++17"]))

    # The RPC worker shares the same object closure; only the entry TU differs.
    entry_src = str(REPO / "tools" / "moe-overlap" / "rpc_worker.cpp") if rpc_worker else str(HARNESS)
    entry_obj_name = "rpc_worker.o" if rpc_worker else "moe_overlap_harness.o"
    entry_o = out_dir / entry_obj_name
    objects.append(entry_o)
    jobs_list.append(([cxx], entry_src, entry_o, ["-std=c++17"]))

    if cuda:
        nvcc = shutil.which("nvcc") or shutil.which("/usr/local/cuda/bin/nvcc")
        if not nvcc:
            raise SystemExit("nvcc not found; CUDA build requires the CUDA toolkit")
        print(f"nvcc: {len(cuda_sources(source))} CUDA translation units")
        # nvcc compiles are large; run them with bounded parallelism
        with ThreadPoolExecutor(max_workers=max(1, min(jobs, 8))) as ex:
            futs = [ex.submit(compile_one, [nvcc], s, obj_path(s),
                              ["-std=c++17", "-arch=sm_86", "--compiler-options", "-fPIC"], True)
                    for s in cuda_sources(source)]
            for f in futs:
                f.result()
        objects.extend(obj_path(s) for s in cuda_sources(source))

    with ThreadPoolExecutor(max_workers=jobs) as ex:
        futs = [ex.submit(compile_one, *j) for j in jobs_list]
        for f in futs:
            f.result()

    if cuda:
        # distinct names per role: a CUDA worker build must not overwrite the
        # CUDA harness binary (and vice versa) in the shared cache
        name = "moe_rpc_worker_cuda" if rpc_worker else "moe_overlap_harness_cuda"
    else:
        name = "moe_rpc_worker" if rpc_worker else "moe_overlap_harness"
    binary = out_dir / name
    link = [cxx, *flags, "-std=c++17", *[str(o) for o in objects]]
    if cuda:
        # VMM is enabled at this pin unless GGML_CUDA_NO_VMM is defined.
        # Mirror its ggml-cuda/CMakeLists.txt CUDA::cuda_driver dependency.
        link += ["-L/usr/local/cuda/lib64", "-lcudart", "-lcublas", "-lcublasLt", "-lculibos", "-lcuda"]
    link += ["-o", str(binary)]
    print("linking", binary.name)
    subprocess.run(link, check=True)
    return binary


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    ap.add_argument("--cuda", action="store_true")
    ap.add_argument("--rpc-worker", action="store_true",
                    help="build the RPC worker binary instead of the harness")
    ap.add_argument("--jobs", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    args = ap.parse_args()
    source = ensure_source(args.cache)
    out_dir = args.cache / ("build-cuda" if args.cuda else "build-cpu")
    binary = build(source, out_dir, args.jobs, args.cuda, rpc_worker=args.rpc_worker)
    # marker line: robust machine-readable handoff (stray env/log output may
    # follow the binary path in some sandboxes)
    print(f"MOE_OVERLAP_BINARY {binary}")
    print(binary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
