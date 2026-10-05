#!/usr/bin/env python3
"""CPU fixture/recording evidence only; never physical authority.

ExecutionProbes is the sole trust boundary. Its methods return original
contemporaneous bytes; parsers below derive observations only from those bytes.
No hardware discovery, network access, or GPU execution is performed here.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import sys
from pathlib import Path, PurePosixPath
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import issue270_authority as C

SCHEMA = "inferswarm.issue275.collector-observation/1"


class CollectorError(RuntimeError):
    """Invalid or contradictory captured execution evidence."""


class CollectorMissing(CollectorError):
    """A required probe did not return bytes."""


class ExecutionProbes:
    """Probe protocol; concrete hardware implementations are intentionally absent.

    Finite trust boundary (documented in
    docs/investigations/qwen38-flash-next-r8-i6a-comparator2-corrective/issue275-collector.md):
    every downstream observation is derived ONLY from the bytes these methods
    return. The two selection-provenance probes were added by #275 round 3:

    * read_process_environ — original /proc/<pid>/environ bytes; the sole
      source for the process-owned Vulkan selector (GGML_VK_VISIBLE_DEVICES)
      and ICD (VK_ICD_FILENAMES) actually in effect for the captured process.
    * read_used_vulkan_device — collector-side observation of the Vulkan
      physical device actually used by the captured process (UUID/BDF/driver
      bytes); never derived from the available-device census or the receipt.
    """
    def read_boot_identity(self) -> bytes: raise NotImplementedError
    def read_start_ticks(self, pid: int) -> bytes: raise NotImplementedError
    def read_process_census(self) -> bytes: raise NotImplementedError
    def read_process_cmdline(self, pid: int) -> bytes: raise NotImplementedError
    def read_exe_identity(self, pid: int) -> bytes: raise NotImplementedError
    def read_open_model_members(self, pid: int) -> bytes: raise NotImplementedError
    def read_device_census(self) -> bytes: raise NotImplementedError
    def read_residency(self, bdf: str) -> bytes: raise NotImplementedError
    def read_process_environ(self, pid: int) -> bytes: raise NotImplementedError
    def read_used_vulkan_device(self, pid: int) -> bytes: raise NotImplementedError


_ENV_SELECTOR_KEY = "GGML_VK_VISIBLE_DEVICES"
_ENV_ICD_KEY = "VK_ICD_FILENAMES"


def _parse_environ(raw: bytes) -> dict[str, str]:
    """Parse original NUL-separated environ bytes into a str dict (lossless keys)."""
    try: entries = [e.decode("utf-8") for e in raw.rstrip(b"\x00").split(b"\x00") if e]
    except UnicodeDecodeError as exc: raise CollectorError("process environ is not UTF-8") from exc
    env: dict[str, str] = {}
    for entry in entries:
        if "=" not in entry: raise CollectorError(f"process environ entry malformed: {entry[:64]!r}")
        key, value = entry.split("=", 1)
        if key in env: raise CollectorError(f"process environ duplicate key: {key}")
        env[key] = value
    return env


def _required_env(env: dict[str, str], key: str) -> str:
    value = env.get(key)
    if not isinstance(value, str) or not value.strip():
        raise CollectorMissing(f"process environ lacks usable {key} observation")
    return value


def encode(doc: Any) -> bytes:
    return (json.dumps(doc, sort_keys=True, indent=2) + "\n").encode()


def _json(raw: bytes, label: str) -> Any:
    try: return json.loads(raw)
    except (ValueError, UnicodeDecodeError) as exc: raise CollectorError(f"{label} malformed: {exc}") from exc


def _raw(probes: Any, method: str, *args: Any) -> bytes:
    try: data = getattr(probes, method)(*args)
    except (FileNotFoundError, KeyError) as exc: raise CollectorMissing(f"{method} absent: {exc}") from exc
    if not isinstance(data, bytes) or not data: raise CollectorMissing(f"{method} returned missing/empty output")
    return data


def _safe_component(value: str, label: str) -> str:
    if not isinstance(value, str) or not value or value in (".", "..") or "/" in value or "\\" in value:
        raise CollectorError(f"unsafe {label}: {value!r}")
    return value


def _write_new(root: Path, rel: str, data: bytes) -> None:
    p = PurePosixPath(rel)
    if p.is_absolute() or not p.parts or any(x in ("", ".", "..") for x in p.parts):
        raise CollectorError(f"unsafe destination path: {rel!r}")
    root = Path(root).absolute()
    for ancestor in (*reversed(root.parents), root):
        if ancestor.is_symlink(): raise CollectorError(f"symlink destination ancestor: {ancestor}")
    dest = root
    for part in p.parts[:-1]:
        dest = dest / part
        if dest.exists() or dest.is_symlink():
            if dest.is_symlink() or not dest.is_dir(): raise CollectorError(f"unsafe destination directory: {dest}")
        else:
            try: dest.mkdir()
            except FileExistsError as exc: raise CollectorError(f"append-only destination exists: {dest}") from exc
            except OSError as exc: raise CollectorError(f"cannot create destination directory {dest}: {exc}") from exc
    target = dest / p.parts[-1]
    if target.exists() or target.is_symlink(): raise CollectorError(f"append-only destination exists: {target}")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(target, flags, 0o600)
        try:
            with os.fdopen(fd, "wb") as stream: stream.write(data)
        except OSError as exc:
            try: target.unlink()
            except FileNotFoundError: pass
            raise CollectorError(f"cannot write destination {target}: {exc}") from exc
    except FileExistsError as exc: raise CollectorError(f"append-only destination exists: {target}") from exc
    except OSError as exc: raise CollectorError(f"cannot write destination {target}: {exc}") from exc


def _read_exe(raw: bytes) -> tuple[str, str]:
    try: text = raw.decode("utf-8").strip().splitlines()
    except UnicodeDecodeError as exc: raise CollectorError("exe_identity is not UTF-8") from exc
    if len(text) != 1: raise CollectorError("exe_identity must contain one path and sha256 line")
    fields = text[0].rsplit(None, 1)
    if len(fields) != 2 or not re.fullmatch(r"[0-9a-f]{64}", fields[1]): raise CollectorError("exe_identity path/sha256 malformed")
    return fields[0], fields[1]


def _effective_model(raw: bytes) -> str:
    args = raw.rstrip(b"\0").split(b"\0")
    try: argv = [x.decode("utf-8") for x in args]
    except UnicodeDecodeError as exc: raise CollectorError("process cmdline is not UTF-8") from exc
    values = []
    i = 0
    while i < len(argv):
        token = argv[i]
        if token in ("--model", "-m"):
            values.append(argv[i + 1] if i + 1 < len(argv) else None); i += 1
        elif token.startswith(("--model=", "-m=")): values.append(token.split("=", 1)[1])
        i += 1
    expected = [f"{C.MODEL_DIR}/{C.MODEL_MEMBER_1}"]
    if values != expected: raise CollectorError("effective --model argument contradicts frozen model member path")
    return values[0]


def capture_execution_273(case: str, arm: str, repeat: bool, receipt: dict,
                          probes: ExecutionProbes, capture_root: Path) -> dict:
    case = _safe_component(case, "case")
    if arm not in ("reference", "candidate"): raise CollectorError(f"unknown arm {arm!r}")
    if type(repeat) is not bool: raise CollectorError("repeat must be bool")
    if not isinstance(receipt, dict): raise CollectorError("receipt must be an object")
    tag = arm + ("-repeat" if repeat else "")
    stem = f"source/{case}/{tag}"
    # Complete capture/validation happens in memory before any write.
    retained: dict[str, bytes] = {}
    def keep(name: str, raw: bytes): retained[f"raw/{name}.start.bin"] = raw; return raw
    boot_raw = keep("boot_identity", _raw(probes, "read_boot_identity"))
    attribution = receipt.get("process_attribution")
    if not isinstance(attribution, dict): raise CollectorError("process_attribution must be an object")
    env = attribution.get("server_env")
    if not isinstance(env, dict): raise CollectorError("process_attribution.server_env must be an object")
    subject = receipt.get("subject_identity")
    if not isinstance(subject, dict): raise CollectorError("subject_identity must be an object")
    pid = attribution.get("server_pid")
    if type(pid) is not int or pid <= 0: raise CollectorError("process_attribution.server_pid invalid")
    ticks_raw = keep("start_ticks", _raw(probes, "read_start_ticks", pid))
    census_raw = keep("process_census", _raw(probes, "read_process_census"))
    cmd_raw = keep("process_cmdline", _raw(probes, "read_process_cmdline", pid))
    exe_raw = keep("exe_identity", _raw(probes, "read_exe_identity", pid))
    members_raw = keep("open_model_members", _raw(probes, "read_open_model_members", pid))
    devices_raw = keep("device_census", _raw(probes, "read_device_census"))
    environ_raw = keep("process_environ", _raw(probes, "read_process_environ", pid))
    used_raw = keep("used_vulkan_device", _raw(probes, "read_used_vulkan_device", pid))
    try:
        boot = boot_raw.decode().strip()
        ticks = int(ticks_raw.decode().strip())
        census = _json(census_raw, "process_census")
        if census.get("boot_id") != boot: raise CollectorError("process census/boot mismatch")
        rows = [r for r in census.get("processes", []) if r.get("pid") == pid]
        if len(rows) != 1: raise CollectorError("process not found uniquely in census")
        if rows[0].get("boot_id") != boot or rows[0].get("start_ticks") != ticks: raise CollectorError("census/boot mismatch vs start-tick bytes")
    except (ValueError, AttributeError, TypeError) as exc: raise CollectorError(f"process identity malformed: {exc}") from exc
    exe_path, exe_sha = _read_exe(exe_raw)
    if exe_sha != C.COMPARATOR_SHA256: raise CollectorError("exe_identity.sha256 != expected comparator sha")
    model_path = _effective_model(cmd_raw)
    model_members = _json(members_raw, "open_model_members")
    if model_members != C.MODEL_MEMBER_SHA256: raise CollectorError("open_model_members contradict frozen model members")
    devices = _json(devices_raw, "device_census")
    if not isinstance(devices, list) or not devices: raise CollectorError("device census empty/malformed")
    required = ("bdf", "vendor_id", "device_id", "vulkan_uuid", "icd", "name", "physical_type")
    for d in devices:
        if not isinstance(d, dict): raise CollectorError("census entry malformed: expected object")
        for key in required:
            if not isinstance(d.get(key), str) or not d[key].strip(): raise CollectorError(f"census entry missing/malformed {key}")
        if not isinstance(d.get("bdf"), str) or not re.fullmatch(r"[0-9a-f]{4,8}:[0-9a-f]{2}:[0-9a-f]{2}\.[0-7]", d["bdf"]):
            raise CollectorError("census entry malformed bdf: expected PCI BDF")
        if type(d.get("index")) is not int: raise CollectorError("census entry missing/malformed index")
    for key in ("bdf", "vulkan_uuid", "index"):
        vals = [d.get(key) for d in devices]
        if any(v is None for v in vals) or len(set(vals)) != len(vals): raise CollectorError(f"ambiguous device census duplicate/missing {key}")
    # --- Observed selection provenance (#275 round 3) -------------------
    # Selector, ICD, backend, and used-device identity derive ONLY from
    # collector-owned contemporaneous bytes: the process's own environ and
    # the used-Vulkan-device observation, resolved against the census.
    # Receipt server_env values below are claims, never a selection source.
    proc_env = _parse_environ(environ_raw)
    obs_selector = _required_env(proc_env, _ENV_SELECTOR_KEY)
    if not re.fullmatch(r"[0-9]+", obs_selector):
        raise CollectorError(f"observed environ {_ENV_SELECTOR_KEY} must be a digit string")
    obs_icd = _required_env(proc_env, _ENV_ICD_KEY)
    used = _json(used_raw, "used_vulkan_device")
    if not isinstance(used, dict): raise CollectorError("used_vulkan_device must be an object")
    for key in ("backend", "icd", "vulkan_uuid", "bdf"):
        if not isinstance(used.get(key), str) or not used[key].strip():
            raise CollectorError(f"used_vulkan_device missing/malformed {key}")
    if type(used.get("index")) is not int: raise CollectorError("used_vulkan_device missing/malformed index")
    if used["backend"] != "vulkan":
        raise CollectorError(f"unsupported observed backend: {used['backend']!r}")
    obs_uuid = used["vulkan_uuid"]
    selected = [d for d in devices if d["vulkan_uuid"] == obs_uuid]
    if len(selected) != 1:
        raise CollectorError("observed used Vulkan UUID absent/ambiguous in device census")
    if selected[0]["bdf"] != used["bdf"]:
        raise CollectorError("used_vulkan_device BDF contradicts census entry for the used UUID")
    if selected[0]["index"] != used["index"] or selected[0]["index"] != int(obs_selector):
        raise CollectorError("observed selector/used-device index disagreement (stale index assumption)")
    if selected[0]["icd"] != obs_icd or used["icd"] != obs_icd:
        raise CollectorError("observed ICD disagrees between environ and used-device observation")
    # Receipt claim-only cross-checks: server_env selector/ICD may be present
    # and are compared against the observed values, but can never establish
    # selection identity.
    claim_selector = env.get(_ENV_SELECTOR_KEY)
    if claim_selector is not None:
        if not isinstance(claim_selector, str) or not re.fullmatch(r"[0-9]+", claim_selector):
            raise CollectorError(f"process_attribution.server_env.{_ENV_SELECTOR_KEY} must be a digit string")
        if claim_selector != obs_selector:
            raise CollectorError(f"receipt claim process_attribution.server_env.{_ENV_SELECTOR_KEY} contradicts observed selector")
    claim_icd = env.get(_ENV_ICD_KEY)
    if claim_icd is not None:
        if not isinstance(claim_icd, str) or not claim_icd.strip():
            raise CollectorError(f"process_attribution.server_env.{_ENV_ICD_KEY} must be a non-empty string")
        if claim_icd != obs_icd:
            raise CollectorError("receipt claim process_attribution.server_env.VK_ICD_FILENAMES contradicts observed ICD")
    reference_identity = None
    if arm == "candidate":
        for d in devices:
            if d["vendor_id"] != C.EXPECTED_CANDIDATE["vendor_id"] or d["device_id"] != C.EXPECTED_CANDIDATE["device_id"] or d["icd"] != C.RADV_ICD:
                raise CollectorError("candidate observed vendor/device/ICD drift")
            if d["bdf"] not in C.EXPECTED_VULKAN_DEVICE_UUIDS or d["vulkan_uuid"] != C.EXPECTED_VULKAN_DEVICE_UUIDS[d["bdf"]]:
                raise CollectorError("candidate observed Vulkan UUID drift")
    else:
        identity = C.reference_identity()
        reference_identity = identity
        d = selected[0]
        if (d["vendor_id"] != "0x10de" or d["device_id"] != "0x" + identity["pci_id"].split(":")[-1]
                or d.get("gpu_uuid") != identity["gpu_uuid"] or d["vulkan_uuid"] != identity["vulkan_device_uuid"]
                or d["bdf"] != identity["bdf"] or d["icd"] != identity["icd"] or used["icd"] != identity["icd"]
                or used.get("driver_id") not in (None, identity["kernel_driver"])): raise CollectorError("reference observed PCI/UUID lineage mismatch")
        excluded = [x for x in devices if x is not d]
        if not any(x["vendor_id"] == "0x1002" and x["device_id"] == "0x67df" and "RX 580" in x["name"] and x["icd"] == C.RADV_ICD for x in excluded):
            raise CollectorError("positive RX580 excluded census absent")
    selected[0]["selected"] = True
    for d in devices:
        if d is not selected[0]: d["selected"] = False
    if subject.get("bdf") != selected[0].get("bdf"):
        raise CollectorError("receipt claim subject_identity.bdf contradicts derived selected device")
    if receipt.get("model_members") != model_members: raise CollectorError("receipt claim model_members contradicts derived open members")
    if receipt.get("exe_sha256") != exe_sha: raise CollectorError("receipt claim exe_sha256 contradicts derived exe sha")
    residencies = {}
    # Retained filenames use start/end; observation counters use before/after.
    for d in devices:
        bdf = d["bdf"]
        samples = []
        for phase in ("start", "peak", "end"):
            raw = _raw(probes, "read_residency", bdf)
            retained[f"raw/residency.{phase}.{bdf}.bin"] = raw
            value = _json(raw, f"residency {phase}/{bdf}")
            if not isinstance(value.get("bytes"), int) or value["bytes"] < 0: raise CollectorError(f"residency {phase}/{bdf} counter malformed")
            samples.append(value["bytes"])
        residencies[bdf] = dict(zip(("before", "peak", "after"), samples))
        if not d["selected"] and samples[1] - samples[0] >= C.EXCLUDED_NOISE_BYTES: raise CollectorError(f"excluded device {bdf} residency delta exceeds noise bound")
    # --- Closing process-incarnation binding (#275 round 3) -------------
    # Re-observe boot identity and start ticks AFTER the execution-owned
    # observations: the capture window is bound to one unchanged process
    # incarnation (same PID + boot id + start ticks). A reused/replaced PID
    # or a reboot splices the evidence and fails closed.
    retained["raw/boot_identity.end.bin"] = _raw(probes, "read_boot_identity")
    retained["raw/start_ticks.end.bin"] = _raw(probes, "read_start_ticks", pid)
    try:
        close_boot = retained["raw/boot_identity.end.bin"].decode().strip()
        close_ticks = int(retained["raw/start_ticks.end.bin"].decode().strip())
    except (ValueError, UnicodeDecodeError) as exc: raise CollectorError(f"closing process identity malformed: {exc}") from exc
    if close_boot != boot or close_ticks != ticks:
        raise CollectorError("process incarnation changed during capture (boot identity/start ticks mismatch)")
    checks = ["process_attribution.server_pid", "process_attribution.server_env.GGML_VK_VISIBLE_DEVICES", "process_attribution.server_env.VK_ICD_FILENAMES", "subject_identity.bdf", "model_members", "exe_sha256"]
    observed_selection = {
        "derived_from": ["raw/process_environ.start.bin", "raw/used_vulkan_device.start.bin", "raw/device_census.start.bin"],
        "selector_env_key": _ENV_SELECTOR_KEY,
        "selector": obs_selector,
        "icd_env_key": _ENV_ICD_KEY,
        "icd": obs_icd,
        "backend": used["backend"],
        "used_vulkan_uuid": obs_uuid,
        "used_bdf": selected[0]["bdf"],
        "used_index": used["index"],
        "used_driver_id": used.get("driver_id"),
    }
    inventory = {name:{"sha256":hashlib.sha256(data).hexdigest(),"bytes":len(data)} for name,data in retained.items()}
    obs = {"schema":SCHEMA, "captured_at":dt.datetime.now(dt.timezone.utc).isoformat(), "probe_inventory":inventory,
           "process":{"pid":pid,"boot_id":boot,"start_ticks":ticks,"cmdline":cmd_raw.decode().rstrip("\0").split("\0"),
                      "exe":{"path":exe_path,"sha256":exe_sha},"effective_model":model_path,"open_model_members":model_members,
                      "incarnation_close":{"boot_id":close_boot,"start_ticks":close_ticks,"bound_same_process":True,
                                           "derived_from":["raw/boot_identity.end.bin","raw/start_ticks.end.bin"]}},
           "devices":devices,"residency":residencies,"observed_selection":observed_selection,"receipt_claims_checked":checks}
    if reference_identity is not None: obs["reference_identity"] = reference_identity
    retained["receipt.json"] = encode(receipt)
    retained["observation.json"] = encode(obs)
    root = Path(capture_root)
    if root.is_symlink(): raise CollectorError(f"symlink capture root: {root}")
    if not root.exists():
        try: root.mkdir(parents=True)
        except FileExistsError as exc: raise CollectorError(f"append-only destination exists: {root}") from exc
        except OSError as exc: raise CollectorError(f"cannot create capture root {root}: {exc}") from exc
    destinations = [root / stem / rel for rel in retained]
    if any(path.exists() or path.is_symlink() for path in destinations):
        raise CollectorError(f"append-only destination exists: {next(p for p in destinations if p.exists() or p.is_symlink())}")
    created: set[Path] = set()
    try:
        for rel, data in retained.items():
            path = root / stem / rel
            _write_new(root, f"{stem}/{rel}", data)
            created.add(path)
    except Exception:
        for path in created:
            if path.is_file() and not path.is_symlink(): path.unlink()
        raise
    return obs
