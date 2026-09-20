#!/usr/bin/env python3
"""Issue #234 — R8-H runtime qualification record builder.

Runs on inferswarm02 NEXT TO the pinned build. Records, from raw bytes:
source revision + clean status, cmake config/build flags, compiler
versions, Vulkan loader/ICD inventory, binary hashes, --version output,
and the llama.cpp Vulkan selector <-> die mapping (list-devices with
and without GGML_VK_VISIBLE_DEVICES restriction, parsed against the
fresh census).

Emits NO correctness output (no model, no tokens).
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import issue234_receipt as rc
import issue234_host as host


class RuntimeQualError(RuntimeError):
    pass


def _run(cmd: list[str], cwd: Path | None = None, env: dict | None = None,
         timeout: int = 120) -> tuple[int, str, str]:
    import os
    full_env = dict(os.environ)
    if env:
        full_env.update(env)
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                          timeout=timeout, env=full_env)
    return proc.returncode, proc.stdout, proc.stderr


def qualify(worktree: Path, build_dir: str = "build-vulkan",
            census_path: Path | None = None) -> dict[str, Any]:
    census = json.loads(
        (census_path or Path("/tmp/is234/census.json")).read_text())
    server = worktree / build_dir / "bin" / "llama-server"
    cli = worktree / build_dir / "bin" / "llama-cli"

    # 1. source identity — exact pin + clean tree (control 4/5)
    rc0, head, _ = _run(["git", "-C", str(worktree), "rev-parse", "HEAD"])
    if rc0 != 0 or head.strip() != rc.LLAMA_CPP_PIN:
        raise RuntimeQualError(
            f"llama.cpp source revision {head.strip()!r} != pin "
            f"{rc.LLAMA_CPP_PIN}")
    rc1, status, _ = _run(["git", "-C", str(worktree), "status",
                           "--porcelain"])
    dirty = [l for l in status.splitlines() if l.strip()]
    # build dirs are untracked-ignored; anything else is dirty source
    dirty = [l for l in dirty if not re.search(
        r"build|\.so|\.o$", l.split()[-1] if l.split() else "")]
    if dirty:
        raise RuntimeQualError(f"llama.cpp worktree dirty: {dirty[:5]}")

    # 2. cmake identity
    cache = (worktree / build_dir / "CMakeCache.txt").read_text()
    flags = {}
    for key in ("CMAKE_BUILD_TYPE", "GGML_VULKAN", "GGML_CUDA",
                "GGML_VULKAN_SHADER_DEBUG", "CMAKE_CXX_COMPILER",
                "CMAKE_CXX_FLAGS"):
        m = re.search(rf"^{re.escape(key)}(?::\w+)?=(.*)$", cache, re.M)
        if m:
            flags[key] = m.group(1)
    if flags.get("GGML_VULKAN") != "ON" or flags.get("GGML_CUDA") != "OFF":
        raise RuntimeQualError(f"backend flags wrong: {flags}")
    if flags.get("CMAKE_BUILD_TYPE") != "Release":
        raise RuntimeQualError(f"build type: {flags.get('CMAKE_BUILD_TYPE')}")

    _, cmake_ver, _ = _run(["cmake", "--version"])
    _, gxx_ver, _ = _run(["g++", "--version"])

    # 3. binary hashes + version output
    def sha(p: Path) -> str:
        import hashlib
        return hashlib.sha256(p.read_bytes()).hexdigest()

    rc_v, ver_out, ver_err = _run([str(server), "--version"])
    if rc_v != 0 or rc.LLAMA_CPP_PIN[:8] not in ver_out + ver_err:
        raise RuntimeQualError(
            f"server --version does not carry pin: {ver_out!r}")

    # 4. Vulkan selector mapping (no model): all devices vs restricted
    _, all_out, all_err = _run([str(server), "--list-devices"])
    rc_r, rest_out, rest_err = _run(
        [str(server), "--list-devices"],
        env={"GGML_VK_VISIBLE_DEVICES": "1"})
    if rc_r != 0:
        raise RuntimeQualError("restricted --list-devices failed")

    def parse_devices(text: str) -> list[dict[str, Any]]:
        devs = []
        for line in text.splitlines():
            m = re.match(r"\s*(Vulkan\d+):\s+(.*?)\s+\((\d+) MiB", line)
            if m:
                devs.append({"label": m.group(1), "name": m.group(2),
                             "mib": int(m.group(3))})
        return devs

    all_devs = parse_devices(all_out)
    rest_devs = parse_devices(rest_out)
    v340_all = [d for d in all_devs if "V340" in d["name"]]
    if len(v340_all) != 2:
        raise RuntimeQualError(
            f"expected 2 V340L in unrestricted list: {all_devs}")
    if len(rest_devs) != 1 or "V340" not in rest_devs[0]["name"]:
        raise RuntimeQualError(
            f"GGML_VK_VISIBLE_DEVICES=1 must expose exactly one V340L: "
            f"{rest_devs}")

    # 5. tie the selector to the census die via vulkaninfo GPU index
    #    ordering (vulkan GPU order == list-devices order for radv)
    vk = census["vulkan_devices"]
    def _idx(g: dict) -> int:
        try:
            return int(str(g.get("vulkan_key", "gpu?")).removeprefix("gpu"))
        except ValueError:
            return 999
    v340_vk = sorted(
        (dict(g, gpu_index=_idx(g))
         for g in vk if "V340" in (g.get("vulkan_name") or "")),
        key=lambda g: g["gpu_index"])
    selected = None
    for g in v340_vk:
        if int(g["gpu_index"]) == 1:
            selected = g
    if selected is None or selected.get("bdf") is None:
        raise RuntimeQualError("census did not bind gpu1 to a BDF")
    other = [g for g in v340_vk if int(g["gpu_index"]) != 1]
    if len(other) != 1 or other[0].get("bdf") is None:
        raise RuntimeQualError("census did not bind the other die")

    return {
        "schema": "inferswarm.r8h.runtime-qualification/1",
        "campaign": rc.CAMPAIGN_ID,
        "source": {
            "repo": "https://github.com/ggml-org/llama.cpp.git",
            "revision": head.strip(),
            "clean": True,
            "worktree": str(worktree),
        },
        "build": {
            "cmake_flags": flags,
            "cmake_version": cmake_ver.splitlines()[0] if cmake_ver else None,
            "compiler": gxx_ver.splitlines()[0] if gxx_ver else None,
            "config_log": (worktree / build_dir / "CMakeCache.txt")
            .read_text()[:20000],
        },
        "binaries": {
            "llama-server": {"sha256": sha(server)},
            "llama-cli": {"sha256": sha(cli)},
        },
        "version_output": (ver_out + ver_err).strip(),
        "vulkan_selector_mapping": {
            "env_var": "GGML_VK_VISIBLE_DEVICES",
            "restricted_value": "1",
            "all_devices": all_devs,
            "restricted_devices": rest_devs,
            "selected_die": {
                "vulkan_gpu_index": selected["gpu_index"],
                "deviceUUID": selected["deviceUUID"],
                "bdf": selected["bdf"],
                "heap_mib_reported": rest_devs[0]["mib"],
            },
            "excluded_die": {
                "vulkan_gpu_index": other[0]["gpu_index"],
                "deviceUUID": other[0]["deviceUUID"],
                "bdf": other[0]["bdf"],
            },
        },
        "census_boot_id": census["host"]["boot_id"],
        "raw": {
            "list_devices_all": all_out,
            "list_devices_restricted": rest_out,
        },
    }


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--worktree", type=Path, required=True)
    ap.add_argument("--census", type=Path, default=Path("/tmp/is234/census.json"))
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    doc = qualify(args.worktree, census_path=args.census)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n",
                        encoding="utf-8")
    print(json.dumps({
        "source": doc["source"]["revision"][:12],
        "server_sha": doc["binaries"]["llama-server"]["sha256"][:16],
        "selected": doc["vulkan_selector_mapping"]["selected_die"]["bdf"],
        "excluded": doc["vulkan_selector_mapping"]["excluded_die"]["bdf"],
    }, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
