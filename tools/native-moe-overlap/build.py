#!/usr/bin/env python3
"""Issue #309 CPU development build, no model/GPU/install or campaign action.

Authenticates the complete source archive, creates a separate overlay, and
compiles the native llama library/model closure plus the small FFN fixture.
--server adds the pinned llama-server closure for a separately authorized
hardware handoff. It never runs a model. Historical caches/overlays stay intact.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile

REPO = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO))
from inferswarm.operator.native_observer import full_build

spec = importlib.util.spec_from_file_location("moe_pin_build", REPO / "tools/moe-overlap/build.py")
pin = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pin)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def source_tree(cache):
    """Always derive from the authenticated archive, never a historical overlay."""
    archive = Path(os.environ.get("MOE_OVERLAP_TARBALL", cache / "pin.tar.gz"))
    if not archive.is_file():
        pin.ensure_source(cache)
    if digest(archive) != pin.TARBALL_SHA256:
        raise ValueError("native source archive digest mismatch")
    with tempfile.TemporaryDirectory(dir=cache, prefix="source-") as td:
        tree = Path(td)
        with tarfile.open(archive) as tar:
            for member in tar.getmembers():
                parts = Path(member.name).parts
                if parts[0] != "llama.cpp-" + pin.PIN or ".." in parts:
                    raise ValueError("unexpected source archive path")
                if len(parts) == 1:
                    continue
                member.name = str(Path(*parts[1:]))
                tar.extract(member, tree, filter="data")
        pin.verify_pin_identity(tree)
        subprocess.run(["patch", "--batch", "--fuzz=0", "-p1", "-i", str(HERE / "native.patch")],
                       cwd=tree, check=True, stdout=subprocess.DEVNULL)
        shutil.copytree(HERE / "overlay", tree, dirs_exist_ok=True)
        entries = {str(p.relative_to(tree)): digest(p) for p in sorted(tree.rglob("*")) if p.is_file()}
        dest = cache / "native-source"
        # Compare every input on every use. Existing objects also include this
        # aggregate in their stamps, so header/overlay changes invalidate them.
        if dest.exists():
            actual = {str(p.relative_to(dest)): digest(p) for p in sorted(dest.rglob("*")) if p.is_file()}
            if actual != entries:
                shutil.rmtree(dest)
        if not dest.exists():
            shutil.copytree(tree, dest)
    return dest, entries


def build(cache, jobs=2, server=False, cuda=False):
    cache = Path(cache).resolve()
    cache.mkdir(parents=True, exist_ok=True)
    source, entries = source_tree(cache)
    out = cache / "build"
    out.mkdir(exist_ok=True)
    full_build._render_templates(source, out)
    cc, cxx = pin.pick_compiler("c"), pin.pick_compiler("c++")
    identities = {p: pin.compiler_identity(p) for p in (cc, cxx)}
    flags = ["-O3" if cuda else "-O1", "-g0", "-pthread", "-D_GNU_SOURCE", "-D_XOPEN_SOURCE=600",
             "-DGGML_SCHED_MAX_COPIES=4", "-DGGML_USE_CPU", "-DGGML_USE_RPC",
             "-DLLAMA_SUBPROCESS", "-ffunction-sections", "-fdata-sections"]
    flags += [x for x in full_build.CFLAGS if x.startswith("-DCPPHTTPLIB")]
    cuda_rels, driver_flags, nvcc = (), [], None
    if cuda:
        # Same authenticated CUDA closure/flags/driver link recipe as #307.
        # This option is build-only; CUDA compilation is untested by CPU CI.
        flags.append("-DGGML_USE_CUDA")
        nvcc = shutil.which("nvcc") or shutil.which("/usr/local/cuda/bin/nvcc")
        if not nvcc:
            raise ValueError("CUDA build requires the existing toolkit; no installs")
        driver_flags = pin.cuda_driver_flags(cxx)
        cuda_rels = tuple(pin.cuda_sources(source))
        identities[nvcc] = pin.compiler_identity(nvcc)
    build_info = (source / "common/build-info.cpp.in").read_text()
    build_info = build_info.replace("@LLAMA_BUILD_NUMBER@", "0").replace(
        "@LLAMA_BUILD_COMMIT@", pin.PIN[:7] + "-is309-" + digest(HERE / "native.patch")[:12]).replace(
        "@BUILD_COMPILER@", identities[cxx].splitlines()[1]).replace(
        "@BUILD_TARGET@", "x86_64-linux-gnu " + ("CUDA" if cuda else "CPU") + " native-moe-overlap-309 overlay")
    (out / "build-info.cpp").write_text(build_info)
    inc = ["-I" + str(p) for p in full_build.includes(source, out)]
    ggml = full_build.GGML_BASE + full_build.GGML_REG + tuple("ggml/src/" + p for p in full_build.GGML_CPU + full_build.GGML_RPC)
    llama = full_build.VENDOR_HASH + full_build.LLAMA_CORE + ("src/llama-moe-overlap.cpp",) + full_build._models(source)
    extras = (full_build.COMMON + full_build.MTMD + full_build._mtmd_models(source) +
              full_build.SERVER_CTX + full_build.SERVER_IMPL +
              ("vendor/cpp-httplib/httplib.cpp",)) if server else ()
    generated = ("build-info.cpp", "ui.cpp") if server else ()
    headers = {p: sha for p, sha in entries.items() if Path(p).suffix not in (".c", ".cpp", ".cu")}
    headers.update({str(p): digest(p) for p in out.glob("*.h")})
    inputs_sha = hashlib.sha256(json.dumps(headers, sort_keys=True).encode()).hexdigest()
    commands = []

    def compile_one(rel):
        path = out / rel if rel in generated else Path(rel) if Path(rel).is_absolute() else source / rel
        obj = out / (str(rel).replace("/", "_") + ".o")
        compiler = cc if path.suffix == ".c" and path.name != "sha1.c" else cxx
        if path.suffix == ".cu":
            compiler = nvcc
            cmd = [nvcc, "-ccbin", cxx, *pin.NVCC_FLAGS, "-std=c++17", "-arch=sm_86",
                   "--compiler-options", "-fPIC", *inc, "-c", str(path), "-o", str(obj)]
        else:
            cmd = [compiler, "-std=c17" if compiler == cc else "-std=c++17", *flags, *inc,
                   "-c", str(path), "-o", str(obj)]
        stamp = obj.with_suffix(".stamp")
        key = hashlib.sha256((inputs_sha + digest(path) + identities[compiler] + repr(cmd)).encode()).hexdigest()
        if not obj.is_file() or not stamp.is_file() or stamp.read_text() != key:
            subprocess.run(cmd, check=True)
            stamp.write_text(key)
        return obj, cmd

    rels = list(dict.fromkeys(ggml + cuda_rels + llama + extras + generated))
    mains = {"native-ffn-fixture": str(HERE / "native_ffn_fixture.cpp"),
             "rpc-worker": str(REPO / "tools/moe-overlap/rpc_worker.cpp")}
    if server:
        mains["llama-server"] = "tools/server/main.cpp"
        mains["ggml-rpc-server"] = "tools/rpc/rpc-server.cpp"
    rels += list(mains.values())
    with ThreadPoolExecutor(max_workers=max(1, min(jobs, 4))) as pool:
        results = list(pool.map(compile_one, rels))
    objects = {rel: result[0] for rel, result in zip(rels, results)}
    commands = [r[1] for r in results]
    binaries = {}
    for name, main in mains.items():
        closure = ggml if name in ("rpc-worker", "ggml-rpc-server") else ggml + llama
        if name == "llama-server":
            closure += extras + generated
        closure += cuda_rels
        target = out / name
        cmd = [cxx, *(str(objects[p]) for p in dict.fromkeys(closure)), str(objects[main]),
               "-pthread", "-ldl", "-lm", "-Wl,--gc-sections",
               *(pin.CUDA_LIB_FLAGS + driver_flags if cuda else []), "-o", str(target)]
        subprocess.run(cmd, check=True)
        commands.append(cmd)
        binaries[name] = {"path": str(target), "sha256": digest(target)}
    manifest = {"schema": "native-moe-overlap-build/1", "base_revision": pin.PIN,
                "archive_sha256": pin.TARBALL_SHA256, "patch_sha256": digest(HERE / "native.patch"),
                "source_inputs": entries, "compiler": identities, "commands": commands,
                "binaries": binaries, "cuda_enabled": cuda, "fixture_execution": "separate from build"}
    (out / "build-identity.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return binaries


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, default=REPO / ".cache/native-moe-overlap")
    parser.add_argument("--jobs", type=int, default=2)
    parser.add_argument("--server", action="store_true")
    parser.add_argument("--cuda", action="store_true", help="build only; separate hardware authorization required")
    args = parser.parse_args()
    print(json.dumps(build(args.cache, args.jobs, args.server, args.cuda), sort_keys=True))
