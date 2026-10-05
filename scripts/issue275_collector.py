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
    """Probe protocol; concrete hardware implementations are intentionally absent."""
    def read_boot_identity(self) -> bytes: raise NotImplementedError
    def read_start_ticks(self, pid: int) -> bytes: raise NotImplementedError
    def read_process_census(self) -> bytes: raise NotImplementedError
    def read_process_cmdline(self, pid: int) -> bytes: raise NotImplementedError
    def read_exe_identity(self, pid: int) -> bytes: raise NotImplementedError
    def read_open_model_members(self, pid: int) -> bytes: raise NotImplementedError
    def read_device_census(self) -> bytes: raise NotImplementedError
    def read_residency(self, bdf: str) -> bytes: raise NotImplementedError


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
        else: dest.mkdir()
    target = dest / p.parts[-1]
    if target.exists() or target.is_symlink(): raise CollectorError(f"append-only destination exists: {target}")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(target, flags, 0o600)
        with os.fdopen(fd, "wb") as stream: stream.write(data)
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
    pid = receipt.get("process_attribution", {}).get("server_pid")
    if type(pid) is not int or pid <= 0: raise CollectorError("process_attribution.server_pid invalid")
    ticks_raw = keep("start_ticks", _raw(probes, "read_start_ticks", pid))
    census_raw = keep("process_census", _raw(probes, "read_process_census"))
    cmd_raw = keep("process_cmdline", _raw(probes, "read_process_cmdline", pid))
    exe_raw = keep("exe_identity", _raw(probes, "read_exe_identity", pid))
    members_raw = keep("open_model_members", _raw(probes, "read_open_model_members", pid))
    devices_raw = keep("device_census", _raw(probes, "read_device_census"))
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
    for key in ("bdf", "vulkan_uuid", "index"):
        vals = [d.get(key) for d in devices]
        if any(v is None for v in vals) or len(set(vals)) != len(vals): raise CollectorError(f"ambiguous device census duplicate/missing {key}")
    env = receipt.get("process_attribution", {}).get("server_env", {})
    selected = [d for d in devices if str(d.get("index")) == str(env.get("GGML_VK_VISIBLE_DEVICES")) and d.get("icd") == env.get("VK_ICD_FILENAMES")]
    if len(selected) != 1: raise CollectorError("selector does not resolve exactly one census device")
    selected[0]["selected"] = True
    for d in devices:
        if d is not selected[0]: d["selected"] = False
    if receipt.get("subject_identity", {}).get("bdf") != selected[0].get("bdf"):
        raise CollectorError("receipt claim subject_identity.bdf contradicts derived selected device")
    if receipt.get("model_members") != model_members: raise CollectorError("receipt claim model_members contradicts derived open members")
    if receipt.get("exe_sha256") != exe_sha: raise CollectorError("receipt claim exe_sha256 contradicts derived exe sha")
    residencies = {}
    for d in devices:
        bdf = d["bdf"]
        samples = []
        for phase in ("before", "peak", "after"):
            raw = _raw(probes, "read_residency", bdf)
            retained[f"raw/residency.{phase}.{bdf}.bin"] = raw
            value = _json(raw, f"residency {phase}/{bdf}")
            if not isinstance(value.get("bytes"), int) or value["bytes"] < 0: raise CollectorError(f"residency {phase}/{bdf} counter malformed")
            samples.append(value["bytes"])
        residencies[bdf] = dict(zip(("before", "peak", "after"), samples))
        if not d["selected"] and samples[1] - samples[0] >= C.EXCLUDED_NOISE_BYTES: raise CollectorError(f"excluded device {bdf} residency delta exceeds noise bound")
    checks = ["process_attribution.server_pid", "process_attribution.server_env.GGML_VK_VISIBLE_DEVICES", "process_attribution.server_env.VK_ICD_FILENAMES", "subject_identity.bdf", "model_members", "exe_sha256"]
    inventory = {name:{"sha256":hashlib.sha256(data).hexdigest(),"bytes":len(data)} for name,data in retained.items()}
    obs = {"schema":SCHEMA, "captured_at":dt.datetime.now(dt.timezone.utc).isoformat(), "probe_inventory":inventory,
           "process":{"pid":pid,"boot_id":boot,"start_ticks":ticks,"cmdline":cmd_raw.decode().rstrip("\0").split("\0"),
                      "exe":{"path":exe_path,"sha256":exe_sha},"effective_model":model_path,"open_model_members":model_members},
           "devices":devices,"residency":residencies,"receipt_claims_checked":checks}
    retained["receipt.json"] = encode(receipt)
    retained["observation.json"] = encode(obs)
    root = Path(capture_root)
    if root.is_symlink(): raise CollectorError(f"symlink capture root: {root}")
    if not root.exists(): root.mkdir(parents=True)
    try:
        for rel, data in retained.items(): _write_new(root, f"{stem}/{rel}", data)
    except Exception:
        base = root / stem
        if base.exists() and not base.is_symlink():
            for path in sorted(base.rglob("*"), reverse=True):
                if path.is_file() and not path.is_symlink(): path.unlink()
                elif path.is_dir() and not path.is_symlink(): path.rmdir()
            base.rmdir()
        raise
    return obs
