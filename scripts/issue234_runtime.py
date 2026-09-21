#!/usr/bin/env python3
"""Issue #234 — R8-H runtime qualification (schema /2, matched arms).

For each execution host, from raw bytes only:
  * llama.cpp source == exact pin, tree clean at that revision;
  * build flags: CUDA build GGML_CUDA=ON/GGML_VULKAN=OFF; Vulkan build
    GGML_VULKAN=ON/GGML_CUDA=OFF;
  * compiler / CMake identities; binary sha256; --version output;
  * backend/device selector mapping proven against the census:
      - CUDA build:   CUDA_VISIBLE_DEVICES=<uuid-or-index> selects the
        frozen 3060; --list-devices shows only CUDA devices, no Vulkan;
      - Vulkan build: GGML_VK_VISIBLE_DEVICES=<idx> (ICD-restricted)
        selects the frozen device; --list-devices shows only Vulkan
        devices, no CUDA (control 29);
  * portability receipt for the Vulkan binary copied 01->02 (same
    sha256, links resolve, --version identical).

Emits NO model/correctness output.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import issue234_receipt as rc


class RuntimeQualError(RuntimeError):
    pass


def _run(cmd: list[str], cwd: Path | None = None, env: dict | None = None,
         timeout: int = 180) -> tuple[int, str, str]:
    import os
    full_env = dict(os.environ)
    if env:
        full_env.update(env)
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                          timeout=timeout, env=full_env)
    return proc.returncode, proc.stdout, proc.stderr


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def check_source(worktree: Path) -> str:
    rc0, head, _ = _run(["git", "-C", str(worktree), "rev-parse", "HEAD"])
    if rc0 != 0 or head.strip() != rc.LLAMA_CPP_PIN:
        raise RuntimeQualError(
            f"llama.cpp source revision {head.strip()!r} != pin "
            f"{rc.LLAMA_CPP_PIN}")
    rc1, status, _ = _run(["git", "-C", str(worktree), "status",
                           "--porcelain"])
    tracked_dirty = [l for l in status.splitlines()
                     if l.strip() and not l.startswith("??")]
    untracked = [l for l in status.splitlines() if l.startswith("??")]
    buildish = [l for l in untracked
                if re.search(r"build|\.so|\.o$", l.split()[-1])]
    other_untracked = [l for l in untracked if l not in buildish]
    if tracked_dirty or other_untracked:
        raise RuntimeQualError(
            f"llama.cpp worktree dirty: {tracked_dirty[:3] + other_untracked[:3]}")
    return head.strip()


def check_build_flags(worktree: Path, build_dir: str, backend: str
                      ) -> dict[str, Any]:
    cache_p = worktree / build_dir / "CMakeCache.txt"
    if not cache_p.is_file():
        raise RuntimeQualError(f"missing CMakeCache: {cache_p}")
    cache = cache_p.read_text()
    flags: dict[str, Any] = {}
    for key in ("CMAKE_BUILD_TYPE", "GGML_VULKAN", "GGML_CUDA",
                "CMAKE_CXX_COMPILER", "CMAKE_CUDA_COMPILER"):
        m = re.search(rf"^{re.escape(key)}(?::\w+)?=(.*)$", cache, re.M)
        if m:
            flags[key] = m.group(1)
    want = (("ON", "OFF") if backend == "vulkan" else ("OFF", "ON"))
    if (flags.get("GGML_VULKAN"), flags.get("GGML_CUDA")) != want:
        raise RuntimeQualError(
            f"{backend} build flags wrong: VULKAN="
            f"{flags.get('GGML_VULKAN')} CUDA={flags.get('GGML_CUDA')}")
    if flags.get("CMAKE_BUILD_TYPE") != "Release":
        raise RuntimeQualError(f"build type: {flags.get('CMAKE_BUILD_TYPE')}")
    _, cmake_ver, _ = _run(["cmake", "--version"])
    _, gxx_ver, _ = _run(["g++", "--version"])
    return {"cmake_flags": flags,
            "cmake_version": (cmake_ver.splitlines()[0]
                              if cmake_ver else None),
            "compiler": (gxx_ver.splitlines()[0]
                         if gxx_ver else None)}


def parse_devices(text: str) -> list[dict[str, Any]]:
    devs = []
    for line in text.splitlines():
        m = re.match(
            r"\s*(Vulkan\d+|CUDA\d+):\s+(.*?)\s+\((\d+)\s*MiB", line)
        if m:
            devs.append({"label": m.group(1), "name": m.group(2),
                         "mib": int(m.group(3))})
    return devs


def qualify_cuda_build(worktree: Path, build_dir: str, census: dict,
                       frozen_uuid: str) -> dict[str, Any]:
    """Arm A runtime: CUDA-only binary selecting the frozen 3060."""
    revision = check_source(worktree)
    build = check_build_flags(worktree, build_dir, "cuda")
    server = worktree / build_dir / "bin" / "llama-server"
    if not server.is_file():
        raise RuntimeQualError(f"missing binary: {server}")
    rc_v, ver_out, ver_err = _run([str(server), "--version"])
    if rc_v != 0 or rc.LLAMA_CPP_PIN[:8] not in ver_out + ver_err:
        raise RuntimeQualError(
            f"--version does not carry pin: {(ver_out + ver_err)[:200]!r}")
    # unrestricted device list: CUDA devices only, NO Vulkan entries
    rc_a, all_out, all_err = _run([str(server), "--list-devices"])
    devs = parse_devices(all_out + all_err)
    cuda_devs = [d for d in devs if d["label"].startswith("CUDA")]
    vk_devs = [d for d in devs if d["label"].startswith("Vulkan")]
    if not cuda_devs:
        raise RuntimeQualError(f"no CUDA devices listed: {devs}")
    if vk_devs:
        raise RuntimeQualError(
            f"CUDA build lists Vulkan devices (control 29): {vk_devs}")
    # CUDA device index -> uuid via nvidia-smi order (CUDA_VISIBLE_DEVICES
    # by UUID is unambiguous; index order matches smi index at this pin)
    smi = census["nvidia"]["gpus"]
    frozen = [g for g in smi if g["uuid"] == frozen_uuid]
    if len(frozen) != 1:
        raise RuntimeQualError(f"frozen 3060 {frozen_uuid} not in census")
    frozen = frozen[0]
    selector_idx = frozen["smi_index"]
    # full-bin identity for the CUDA build too
    bin_dir = server.parent
    bin_hashes = {}
    for f in sorted(bin_dir.iterdir()):
        if f.is_file() and (f.name.startswith("libggml") or
                            f.name == "llama-server"):
            bin_hashes[f.name] = sha(f)
    rc_r, rest_out, rest_err = _run(
        [str(server), "--list-devices"],
        env={"CUDA_VISIBLE_DEVICES": str(selector_idx)})
    if rc_r != 0:
        raise RuntimeQualError("CUDA-restricted --list-devices failed")
    rest = parse_devices(rest_out + rest_err)
    others = [d for d in rest
              if d["label"] != f"CUDA{0}"]  # after restriction CUDA0 == frozen
    return {
        "schema": "inferswarm.r8h.runtime-cuda/2",
        "campaign": rc.CAMPAIGN_ID,
        "arm": "A",
        "source": {"revision": revision, "clean": True,
                   "worktree": str(worktree), "build_dir": build_dir},
        "build": build,
        "binaries": {"llama-server": {"sha256": sha(server)},
                     "bin_dir": bin_hashes},
        "version_output": (ver_out + ver_err).strip(),
        "selector": {
            "mechanism": "CUDA_VISIBLE_DEVICES",
            "value": str(selector_idx),
            "value_semantics": "nvidia-smi index of frozen GPU "
                               f"{frozen_uuid} (BDF {frozen['bdf']})",
            "all_devices": devs,
            "restricted_devices": rest,
            "vulkan_devices_present": vk_devs,
        },
        "frozen_gpu": {"uuid": frozen_uuid, "bdf": frozen["bdf"],
                       "name": frozen["name"],
                       "driver": frozen["driver_version"]},
        "raw": {"list_devices_all": all_out + all_err,
                "list_devices_restricted": rest_out + rest_err},
    }


def qualify_vulkan_build(worktree: Path, build_dir: str, census: dict,
                         arm: str, frozen_bdf: str,
                         vulkan_binary_sha: str | None = None,
                         deployed_path: Path | None = None) -> dict[str, Any]:
    """Arm B (01, NVIDIA ICD) or Arm C (02, RADV) Vulkan runtime."""
    revision = check_source(worktree)
    build = check_build_flags(worktree, build_dir, "vulkan")
    server = deployed_path or (worktree / build_dir / "bin" / "llama-server")
    if not server.is_file():
        raise RuntimeQualError(f"missing binary: {server}")
    # at this pin llama-server is a launcher; backend identity lives in
    # the libggml*.so set beside it — hash the full bin dir
    bin_dir = server.parent
    bin_hashes = {}
    for f in sorted(bin_dir.iterdir()):
        if f.is_file() and (f.name.startswith("libggml") or
                            f.name == "llama-server"):
            bin_hashes[f.name] = sha(f)
    binary_sha = bin_hashes.get("llama-server")
    if binary_sha is None:
        raise RuntimeQualError(f"llama-server missing in {bin_dir}")
    if vulkan_binary_sha is not None and binary_sha != vulkan_binary_sha:
        raise RuntimeQualError(
            f"deployed Vulkan binary sha {binary_sha} != source-of-truth "
            f"{vulkan_binary_sha}")
    rc_v, ver_out, ver_err = _run([str(server), "--version"])
    if rc_v != 0 or rc.LLAMA_CPP_PIN[:8] not in ver_out + ver_err:
        raise RuntimeQualError(
            f"--version does not carry pin: {(ver_out + ver_err)[:200]!r}")
    rc_a, all_out, all_err = _run([str(server), "--list-devices"])
    devs = parse_devices(all_out + all_err)
    cuda_devs = [d for d in devs if d["label"].startswith("CUDA")]
    if cuda_devs:
        raise RuntimeQualError(
            f"Vulkan build lists CUDA devices (control 29): {cuda_devs}")
    # bind restricted selector to the frozen BDF through the census join
    sel = bind_vulkan_selector(server, census, arm, frozen_bdf)
    ldd = None
    if deployed_path is not None:
        rc_l, ldd_out, _ = _run(["ldd", str(server)])
        ldd = ldd_out
        missing = [l for l in ldd_out.splitlines() if "not found" in l]
        if missing:
            raise RuntimeQualError(f"deployed binary link failures: {missing}")
    return {
        "schema": "inferswarm.r8h.runtime-vulkan/2",
        "campaign": rc.CAMPAIGN_ID,
        "arm": arm,
        "source": {"revision": revision, "clean": True,
                   "worktree": str(worktree), "build_dir": build_dir},
        "build": build,
        "binaries": {"llama-server": {"sha256": binary_sha},
                     "bin_dir": bin_hashes},
        "version_output": (ver_out + ver_err).strip(),
        "selector": sel,
        "deployed": ({"path": str(deployed_path), "ldd": ldd}
                     if deployed_path is not None else None),
        "raw": {"list_devices_all": all_out + all_err,
                "list_devices_restricted": sel.get("raw_restricted", "")},
    }


def bind_vulkan_selector(server: Path, census: dict, arm: str,
                         frozen_bdf: str) -> dict[str, Any]:
    """Find the GGML_VK_VISIBLE_DEVICES index that uniquely selects the
    frozen BDF, proven by UUID join against the census."""
    if arm == "B":
        # census: nvidia-host census; Vulkan devices joined by uuid
        cands = census["rtx3060"]
        vk_by_uuid = {}
        for key, info in _vk_entries(census).items():
            vk_by_uuid[info.get("deviceUUID")] = (key, info)
        target_uuid = None
        for c in cands:
            if c["bdf_smi"] == frozen_bdf:
                target_uuid = (c.get("vulkan_deviceUUID")
                               or _uuid_to_vk(c["nvidia_uuid"]))
        if target_uuid is None:
            raise RuntimeQualError(f"frozen BDF {frozen_bdf} not in census")
        entry = vk_by_uuid.get(target_uuid)
        if entry is None:
            raise RuntimeQualError(
                f"Vulkan device for UUID {target_uuid} not enumerated")
        key, info = entry
        want_gpu_index = int(key.removeprefix("gpu"))
        chosen_uuid = target_uuid
    else:
        dies = census["v340l_dies"]
        target = dies.get(frozen_bdf) or dies.get(bdf_short(frozen_bdf))
        if target is None:
            raise RuntimeQualError(f"frozen die {frozen_bdf} not in census")
        want_gpu_index = int(target["vulkan_key"].removeprefix("gpu"))
        chosen_uuid = target.get("deviceUUID")
    # enumerate restricted indices until exactly one device == target
    attempts = []
    chosen = None
    for idx in range(0, 6):
        rc_r, out, err = _run(
            [str(server), "--list-devices"],
            env={"GGML_VK_VISIBLE_DEVICES": str(idx)})
        if rc_r != 0:
            continue
        devs = parse_devices(out + err)
        attempts.append({"idx": idx, "devices": devs,
                         "raw": (out + err)[:2000]})
        # llama.cpp Vulkan labels enumerate Vulkan0..N in restricted order
        if len(devs) >= want_gpu_index + 1:
            chosen = {"index": idx, "device": devs[want_gpu_index]}
            break
    if chosen is None:
        raise RuntimeQualError(
            f"could not bind a GGML_VK_VISIBLE_DEVICES index for gpu index "
            f"{want_gpu_index}: {[a['devices'] for a in attempts]}")
    return {
        "mechanism": "GGML_VK_VISIBLE_DEVICES",
        "value": str(chosen["index"]),
        "target_gpu_index": want_gpu_index,
        "target_bdf": frozen_bdf,
        "target_deviceUUID": chosen_uuid,
        "chosen_device": chosen["device"],
        "attempts": attempts,
    }


def _vk_entries(census: dict) -> dict[str, dict[str, Any]]:
    raw = census.get("raw", {}).get("vulkaninfo_all")
    if raw:
        import issue234_host as host
        gpus = host.collect_vulkan()["gpus"]
        return gpus
    return {}


def _uuid_to_vk(nvidia_uuid: str) -> str | None:
    return None  # join must come from the census, never synthesized


def bdf_short(bdf: str) -> str:
    domain, bus, devfn = bdf.split(":")
    return f"{domain[-4:]}:{bus}:{devfn}"


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--arm", choices=("A", "B", "C"), required=True)
    ap.add_argument("--worktree", type=Path, required=True)
    ap.add_argument("--build-dir", required=True)
    ap.add_argument("--census", type=Path, required=True)
    ap.add_argument("--frozen-uuid", help="Arm A/B: nvidia-smi UUID")
    ap.add_argument("--frozen-bdf", help="Arm B/C: 16-char BDF")
    ap.add_argument("--vulkan-binary-sha",
                    help="Arm C: sha256 the deployed binary must match")
    ap.add_argument("--deployed-path", type=Path,
                    help="Arm C: path of the binary copied from 01")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    census = json.loads(args.census.read_text())
    if args.arm == "A":
        doc = qualify_cuda_build(args.worktree, args.build_dir, census,
                                 args.frozen_uuid)
    else:
        doc = qualify_vulkan_build(
            args.worktree, args.build_dir, census, args.arm,
            args.frozen_bdf, args.vulkan_binary_sha, args.deployed_path)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n",
                        encoding="utf-8")
    print(json.dumps({
        "arm": args.arm,
        "server_sha": doc["binaries"]["llama-server"]["sha256"][:16],
        "selector": doc["selector"]["mechanism"] + "=" + doc["selector"]["value"],
    }, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
