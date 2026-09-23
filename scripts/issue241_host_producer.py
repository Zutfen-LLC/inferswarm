#!/usr/bin/env python3
"""Authorized issue #241 host census and comparator/2 build producer.

No operation is callable without an explicit dispatch authority object and
injected runner. Commands are executed only through ``runner.run``; no model
or inference command is part of this producer.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tarfile
import tempfile
from pathlib import Path
from typing import Any

import issue241_census as census_validator
import issue241_constants as C
import issue241_observer_patch as observer_patch
import issue241_dispatch as dispatch

AUTHORITY_REQUIRED = True


class ProducerError(RuntimeError):
    """Fail-closed producer or authorization error."""


class SubprocessRunner:
    """Bounded production command seam; injected test runners use the same API."""

    def run(self, command: list[str], *, cwd: Path | None = None,
            timeout: int = 120) -> subprocess.CompletedProcess[str]:
        return subprocess.run(command, cwd=cwd, timeout=timeout,
                              text=True, capture_output=True, check=False)


def _authorize(authority: dict[str, Any] | None) -> None:
    if (not isinstance(authority, dict)
            or authority.get("schema") != dispatch.AUTHORITY_SCHEMA):
        raise ProducerError("exact dispatch.AUTHORITY_SCHEMA authority required")
    head = authority.get("head_sha")
    if not isinstance(head, str) or re.fullmatch(r"[0-9a-f]{40}", head) is None:
        raise ProducerError("authority must bind an exact lowercase head_sha")
    if (authority.get("repository") != dispatch.REPO
            or authority.get("issue_number") != dispatch.ISSUE_NUMBER
            or not isinstance(authority.get("pr_number"), int)
            or isinstance(authority.get("pr_number"), bool)
            or authority["pr_number"] <= 0
            or authority.get("pr_state") != "open"
            or authority.get("merged_at", "missing") is not None
            or authority.get("base_ref") != dispatch.BASE_REF
            or authority.get("review_commit_id") != head
            or authority.get("reviewer_association") not in dispatch.AUTHORIZED_ASSOCIATIONS
            or authority.get("dispatch_phrase") != dispatch.DISPATCH_PHRASE
            or not isinstance(authority.get("review_id"), int)
            or isinstance(authority.get("review_id"), bool)
            or authority["review_id"] <= 0
            or not isinstance(authority.get("reviewer"), str)
            or not authority["reviewer"]):
        raise ProducerError("incomplete or revoked dispatch authority")
    try:
        dispatch._parse_timestamp(authority.get("submitted_at"))
    except ValueError as exc:
        raise ProducerError("invalid dispatch authority timestamp") from exc


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def require_regular_nonsymlink(path: Path) -> Path:
    path = Path(path)
    if path.is_symlink():
        raise ProducerError(f"symlink rejected: {path}")
    if not path.is_file():
        raise ProducerError(f"regular file required: {path}")
    return path


def run_recorded(runner: Any, command: list[str], *, authority: dict[str, Any],
                 cwd: Path | None = None, timeout: int = 120) -> dict[str, Any]:
    _authorize(authority)
    result = runner.run(command, cwd=cwd, timeout=timeout)
    if isinstance(result, tuple):
        if len(result) != 3:
            raise ProducerError("runner result must be (returncode, stdout, stderr)")
        code, stdout, stderr = result
    else:
        code = result.returncode
        stdout, stderr = result.stdout or "", result.stderr or ""
    if isinstance(stdout, bytes):
        stdout = stdout.decode("utf-8", "replace")
    if isinstance(stderr, bytes):
        stderr = stderr.decode("utf-8", "replace")
    return {"argv": list(command), "cwd": str(cwd) if cwd else None,
            "returncode": int(code), "stdout": stdout, "stderr": stderr,
            "stdout_sha256": _sha(stdout.encode()),
            "stderr_sha256": _sha(stderr.encode())}


def _checked(runner: Any, command: list[str], *, authority: dict[str, Any],
             cwd: Path | None = None, timeout: int = 120) -> dict[str, Any]:
    row = run_recorded(runner, command, authority=authority, cwd=cwd,
                       timeout=timeout)
    if row["returncode"] != 0:
        raise ProducerError(f"command failed: {command!r}: {row['stderr'][:400]}")
    return row


def _json_cmd(runner: Any, command: list[str], authority: dict[str, Any],
              *, cwd: Path | None = None) -> tuple[Any, dict[str, Any]]:
    row = _checked(runner, command, authority=authority, cwd=cwd)
    try:
        return json.loads(row["stdout"]), row
    except (TypeError, json.JSONDecodeError) as exc:
        raise ProducerError(f"invalid JSON from {command[0]}") from exc


def _atomic_json(path: Path, document: Any) -> None:
    """Never overwrite a retained receipt or follow an evidence symlink."""
    if path.exists() or path.is_symlink():
        raise ProducerError(f"evidence already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_name(path.name + ".pending")
    with pending.open("xb") as stream:
        stream.write((json.dumps(document, sort_keys=True, indent=2) + "\n").encode())
        stream.flush()
        os.fsync(stream.fileno())
    pending.replace(path)


def _gpu_bdf(value: str) -> str:
    match = re.fullmatch(r"(?:([0-9a-fA-F]{4,8}):)?([0-9a-fA-F]{2}):([0-9a-fA-F]{2}\.[0-7])", value.strip())
    if not match:
        raise ProducerError(f"invalid GPU BDF: {value!r}")
    return f"{int(match[1] or '0', 16):08x}:{match[2].lower()}:{match[3].lower()}"


def _vulkan_summary(text: str) -> list[dict[str, str]]:
    devices: list[dict[str, str]] = []
    current = None
    for line in text.splitlines():
        stripped = line.strip()
        if re.fullmatch(r"GPU[0-9]+:", stripped):
            current = {}
            devices.append(current)
        elif current is not None and "=" in stripped:
            key, value = stripped.split("=", 1)
            current[key.strip()] = value.strip()
    return devices


def collect_census(root: Path, runner: Any,
                   authority: dict[str, Any] | None = None, *,
                   out_dir: Path | None = None) -> dict[str, Any]:
    """Capture real read-only measurements, retaining raw output before parsing."""
    _authorize(authority)
    root = Path(root)
    require_regular_nonsymlink(root / C.R8I_MANIFEST_REL)
    if out_dir is None:
        out_dir = Path(tempfile.mkdtemp(prefix="issue241-census-"))
    out_dir = Path(out_dir)
    if out_dir.is_symlink() or (out_dir / "raw").is_symlink():
        raise ProducerError("evidence directory symlink rejected")
    if (out_dir / "census.json").exists() or (out_dir / "census.json").is_symlink():
        raise ProducerError("census receipt already exists")
    commands: dict[str, dict[str, Any]] = {}
    def capture(key: str, argv: list[str], *, optional: bool = False) -> str:
        row = run_recorded(runner, argv, authority=authority)
        _atomic_json(out_dir / "raw" / (key + ".json"), row)
        commands[key] = row
        if row["returncode"] and not optional:
            raise ProducerError(f"command failed: {argv!r}: {row['stderr'][:400]}")
        return row["stdout"]

    host = capture("hostname", ["hostname"]).strip()
    cpuinfo = capture("cpu", ["python3", "-c",
        "import json;print(json.dumps([x.strip() for x in open('/proc/cpuinfo') if x.startswith('model name')][:1]))"])
    meminfo = capture("memory", ["python3", "-c",
        "import json;print(json.dumps({'mem_total_kib':int(next(x.split()[1] for x in open('/proc/meminfo') if x.startswith('MemTotal:')))}))"])
    memory_state_text = capture("memory_state", ["python3", "-c",
        "import json;mem_state={k:int(v.split()[0]) for k,v in (line.split(':',1) for line in open('/proc/meminfo')) if k in ('MemAvailable','Cached','Buffers','SReclaimable','SwapTotal','SwapFree')};print(json.dumps(mem_state))"])
    motherboard_text = capture("motherboard", ["python3", "-c",
        "import json,pathlib;d=pathlib.Path('/sys/class/dmi/id');print(json.dumps({k:(d/k).read_text().strip() for k in ('board_vendor','board_name','board_version','bios_version')}))"])
    pci_text = capture("pci", ["lspci", "-Dnn"])
    pci_tree = capture("pci_tree", ["lspci", "-Dnn", "-t"])
    capture("pci_verbose", ["lspci", "-Dnnvv"])
    nv_text = capture("nvidia", ["nvidia-smi", "--query-gpu=index,uuid,pci.bus_id,name,driver_version,memory.total,temperature.gpu,power.draw,power.limit", "--format=csv,noheader"])
    platform_raw = capture("platform", ["python3", "-c",
        "import json,platform;print(json.dumps({'machine':platform.machine(),'release':platform.release()}))"])
    # Record all installed ICD paths, not the prospectively frozen arm paths.
    icd_text = capture("icd_inventory", ["python3", "-c",
        "import glob,json;print(json.dumps(sorted(glob.glob('/usr/share/vulkan/icd.d/*.json')+glob.glob('/etc/vulkan/icd.d/*.json'))))"])
    sensors_text = capture("sensors", ["python3", "-c",
        "import glob,json,pathlib; h=[{p.name:p.read_text().strip() for p in d.iterdir() if p.is_file() and p.name in ('name','temp1_input','power1_average','power1_input','fan1_input')} for d in map(pathlib.Path,glob.glob('/sys/class/hwmon/hwmon*'))]; s=[{'name':d.name,'online':(d/'online').read_text().strip() if (d/'online').exists() else None} for d in map(pathlib.Path,glob.glob('/sys/class/power_supply/*'))];print(json.dumps({'hwmon':h,'power_supply':s}))"])
    gpus = []
    for line in pci_text.splitlines():
        match = re.match(r"^(\S+)\s+.*?\[(03[0-9a-fA-F]{2})\]:.*?\[([0-9a-fA-F]{4}):([0-9a-fA-F]{4})\]", line)
        if match:
            gpus.append({"bdf": _gpu_bdf(match[1]), "class_id": match[2].lower(),
                         "vendor_id": match[3].lower(), "device_id": match[4].lower(),
                         "pci_id": match[3].lower() + ":" + match[4].lower(),
                         "pci_description": line, "revision": (re.search(r"\(rev ([0-9a-fA-F]{2})\)", line) or [None, None])[1],
                         "pci_tree": pci_tree})
    if len(gpus) != 2:
        raise ProducerError(f"expected two display GPUs; observed {len(gpus)}")
    for gpu in gpus:
        bdf = gpu["bdf"]
        sysfs = "/sys/bus/pci/devices/" + f"{int(bdf[:8], 16):04x}" + bdf[8:]
        for attr, field in (("vendor", "vendor_id"), ("device", "device_id"),
                            ("subsystem_vendor", "subsystem_vendor_id"),
                            ("subsystem_device", "subsystem_device_id"),
                            ("revision", "revision"), ("current_link_width", "link_width"),
                            ("current_link_speed", "link_speed"),
                            ("max_link_width", "max_link_width"),
                            ("max_link_speed", "max_link_speed")):
            value = capture("sys_" + bdf + "_" + attr, ["cat", sysfs + "/" + attr]).strip()
            if attr in ("vendor", "device", "subsystem_vendor", "subsystem_device", "revision"):
                value = value.lower().removeprefix("0x")
                if re.fullmatch(r"[0-9a-f]{2}" if attr == "revision" else r"[0-9a-f]{4}", value) is None:
                    raise ProducerError(f"invalid sysfs {attr} for {bdf}")
            if field in ("vendor_id", "device_id", "revision") and gpu[field] != value:
                raise ProducerError(f"lspci/sysfs {field} mismatch on {bdf}")
            gpu[field] = "x" + value if attr.endswith("link_width") else value
        gpu["driver_in_use"] = capture("driver_" + bdf,
            ["readlink", "-f", sysfs + "/driver"]).strip().rsplit("/", 1)[-1]
        if gpu["vendor_id"] == "1002":
            vram = int(capture("vram_" + bdf, ["cat", sysfs + "/mem_info_vram_total"]).strip())
            if vram <= 0 or vram % (1024 * 1024):
                raise ProducerError("invalid AMD sysfs VRAM capacity")
            gpu["vram_mib"] = vram // (1024 * 1024)
    for row in nv_text.splitlines():
        vals = [v.strip() for v in row.split(",")]
        if len(vals) != 9:
            raise ProducerError("malformed nvidia-smi CSV")
        matches = [g for g in gpus if g["bdf"] == _gpu_bdf(vals[2]) and g["vendor_id"] == "10de"]
        if len(matches) != 1:
            raise ProducerError("NVIDIA BDF cannot be uniquely joined")
        matches[0].update(gpu_uuid=vals[1], nvidia_name=vals[3], driver_version=vals[4],
                          vram_mib=int(vals[5].split()[0]), temperature_c=vals[6],
                          power_draw_w=vals[7], power_limit_w=vals[8])
    try:
        icds = json.loads(icd_text)
        if not isinstance(icds, list) or any(not isinstance(x, str) or not x.endswith('.json') for x in icds):
            raise ValueError("malformed ICD inventory")
        vulkan_devices = {}
        for i, icd in enumerate(icds):
            raw = capture(f"vulkan_{i}", ["env", "VK_DRIVER_FILES=" + icd, "vulkaninfo", "--summary"], optional=True)
            if commands[f"vulkan_{i}"]["returncode"]:
                continue
            vulkan_devices[icd] = _vulkan_summary(raw)
        for gpu in gpus:
            matches = [(icd, dev) for icd, devs in vulkan_devices.items() for dev in devs
                       if dev.get("vendorID", "").lower().removeprefix("0x") == gpu["vendor_id"]
                       and dev.get("deviceID", "").lower().removeprefix("0x") == gpu["device_id"]]
            if len(matches) != 1:
                raise ProducerError(f"Vulkan physical device/ICD ambiguous or absent for {gpu['bdf']}")
            gpu.update(vulkan_icd=matches[0][0], vulkan_device_name=matches[0][1].get("deviceName"),
                       vulkan_device_uuid=matches[0][1].get("deviceUUID"),
                       vulkan_api_version=matches[0][1].get("apiVersion"),
                       vulkan_driver_name=matches[0][1].get("driverName"),
                       vulkan_driver_info=matches[0][1].get("driverInfo"))
        cpus = json.loads(cpuinfo)
        mem_total = json.loads(meminfo)["mem_total_kib"]
        memory_state = json.loads(memory_state_text)
        motherboard = json.loads(motherboard_text)
        platform = json.loads(platform_raw)
        sensors = json.loads(sensors_text)
        if not isinstance(sensors, dict) or not isinstance(sensors.get("hwmon"), list):
            raise ValueError("malformed hwmon observations")
    except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        raise ProducerError("could not parse captured host identity") from exc
    backing = {}
    for member in C.MODEL_MEMBERS:
        model_path = C.MODEL_DIR / member
        require_regular_nonsymlink(model_path)
        digest_text = capture("model_sha_" + member, ["sha256sum", "--", str(model_path)])
        digest_match = re.fullmatch(r"([0-9a-f]{64})  (.+)\n?", digest_text)
        if not digest_match or digest_match[2].strip() != str(model_path):
            raise ProducerError(f"malformed model digest for {member}")
        digest = digest_match[1]
        size = int(capture("model_size_" + member, ["stat", "-c", "%s", "--", str(model_path)]).strip())
        if size <= 0:
            raise ProducerError(f"invalid model size for {member}")
        backing[member] = {"bytes": size, "sha256": digest, "path": str(model_path)}
    if sum(item["bytes"] for item in backing.values()) != C.MODEL_TOTAL_BYTES:
        raise ProducerError("model backing total bytes drift")
    doc = {"schema": census_validator.CENSUS_SCHEMA, "host": host,
           "campaign": C.CAMPAIGN_ID, "cpu": cpus, "mem_total_kib": mem_total,
           "memory_state": memory_state, "motherboard": motherboard,
           "gpus": gpus, "model_backing": backing,
           "power_thermal": {"sensors_available": bool(sensors["hwmon"] or
                                                     any(g.get("temperature_c") not in (None, "[N/A]")
                                                         for g in gpus)), **sensors,
                             "nvidia": [{k: g[k] for k in ("bdf", "temperature_c",
                                         "power_draw_w", "power_limit_w")}
                                        for g in gpus if g["vendor_id"] == "10de"]},
           "raw": commands,
           "raw_artifact_sha256": {
               key: _sha((out_dir / "raw" / (key + ".json")).read_bytes())
               for key in commands},
           "platform": platform, "vulkan_devices": vulkan_devices,
           "source_tree": str(root / C.R8I_AREA_REL), "authority": authority,
           "out_dir": str(out_dir)}
    try:
        verdict = census_validator.validate_census(doc)
    except ValueError as exc:
        raise ProducerError(str(exc)) from exc
    result = {"census": doc, "verdict": verdict}
    _atomic_json(out_dir / "census.json", result)
    return result

def build_comparator(root: Path, r8e_patch: Path, runner: Any,
                     authority: dict[str, Any] | None = None) -> dict[str, Any]:
    """Apply accepted R8-E and comparator/2 patches, configure and build.

    All subprocess work, including git/cmake/build and package identity,
    goes through the injected runner. No inference or model command runs.
    """
    _authorize(authority)
    assert authority is not None  # _authorize rejects absent authority before any command
    root, r8e_patch = Path(root), Path(r8e_patch)
    require_regular_nonsymlink(r8e_patch)
    observer_patch.verify_r8e_patch(r8e_patch)
    head = _checked(runner, ["git", "rev-parse", "HEAD"], authority=authority,
                    cwd=root)["stdout"].strip()
    if head != C.LLAMA_CPP_PIN:
        raise ProducerError(f"source HEAD {head!r} != pinned {C.LLAMA_CPP_PIN}")
    original = root / observer_patch.TARGET
    require_regular_nonsymlink(original)
    base = original.read_bytes()
    status = _checked(runner, ["git", "status", "--porcelain", "--untracked-files=all"],
                      authority=authority, cwd=root)
    if status["stdout"].strip():
        raise ProducerError("pinned source tree must be clean before isolated build")
    # Leave the worktree available for independent binary/source audit. Never
    # apply a patch or configure inside the supplied source checkout.
    workspace = Path(tempfile.mkdtemp(prefix="issue241-build-"))
    isolated = workspace / "checkout"
    worktree = _checked(runner, ["git", "worktree", "add", "--detach",
                                 str(isolated), C.LLAMA_CPP_PIN],
                        authority=authority, cwd=root)
    target = isolated / observer_patch.TARGET
    require_regular_nonsymlink(target)
    if target.read_bytes() != base:
        raise ProducerError("isolated pinned source differs from supplied source")
    patch_check = _checked(runner, ["git", "apply", "--check", str(r8e_patch)],
                           authority=authority, cwd=isolated)
    applied = _checked(runner, ["git", "apply", str(r8e_patch)], authority=authority, cwd=isolated)
    # Runner-backed patch execution is authoritative; verify actual resulting bytes.
    r8e_source = target.read_bytes()
    if r8e_source == base:
        raise ProducerError("R8-E patch command did not modify server-context.cpp")
    patched_text = observer_patch.apply(r8e_source.decode("utf-8"))
    target.write_text(patched_text, encoding="utf-8")
    actual_sha = _sha(target.read_bytes())
    if actual_sha != C.OBSERVER_PATCHED_SOURCE_SHA256:
        raise ProducerError(f"patched source digest mismatch: {actual_sha}")
    configure = _checked(runner, ["cmake", "-S", ".", "-B", "build-issue241", *C.OBSERVER_BUILD_FLAGS], authority=authority, cwd=isolated, timeout=1800)
    build = _checked(runner, ["cmake", "--build", "build-issue241", "--target", "llama-server", "-j2"], authority=authority, cwd=isolated, timeout=7200)
    binary = isolated / "build-issue241" / "bin" / "llama-server"
    require_regular_nonsymlink(binary)
    binary_sha = _sha(binary.read_bytes())
    dynamic_dependencies = _checked(runner, ["ldd", str(binary)],
                                    authority=authority, cwd=isolated)
    runtime_packages = _checked(runner, ["dpkg-query", "-W",
        "-f=${binary:Package}=${Version}\\n", "libvulkan1", "mesa-vulkan-drivers"],
        authority=authority, cwd=isolated)
    if (not dynamic_dependencies["stdout"].strip()
            or "not found" in dynamic_dependencies["stdout"]
            or not runtime_packages["stdout"].strip()):
        raise ProducerError("dynamic/runtime package identity missing or unresolved")
    package = {}
    for entry in sorted(binary.parent.iterdir()):
        if entry.name == "llama-server" or ".so" in entry.name:
            resolved = entry.resolve(strict=True)
            if resolved.parent != binary.parent or not resolved.is_file():
                raise ProducerError(f"package member escapes build/bin: {entry}")
            package[entry.name] = _sha(resolved.read_bytes())
    package_path = workspace / "comparator-v2-package.tar"
    with tarfile.open(package_path, "w", dereference=True) as archive:
        for name in sorted(package):
            archive.add(binary.parent / name, arcname=name, recursive=False)
    package_digest = _sha(package_path.read_bytes())
    return {"schema": "inferswarm.issue241.comparator-v2-build/1",
            "dispatch_authority": authority, "producer_head_sha": authority["head_sha"],
            "source_head": head, "r8e_patch_sha256": observer_patch.R8E_ACCEPTED_PATCH_SHA256,
            "patched_source_sha256": actual_sha,
            "cmake_flags": list(C.OBSERVER_BUILD_FLAGS),
            "worktree": str(isolated), "source_pin": C.LLAMA_CPP_PIN,
            "r8e_patch_actual_sha256": _sha(r8e_patch.read_bytes()),
            "commands": {"worktree": worktree, "r8e_check": patch_check, "r8e_apply": applied,
                         "configure": configure, "build": build},
            "binary": {"path": str(binary), "sha256": binary_sha},
            "dynamic_dependencies": dynamic_dependencies,
            "runtime_packages": runtime_packages,
            "package_sha256": package,
            "package": {"path": str(package_path), "sha256": package_digest,
                        "member_sha256": package}}
