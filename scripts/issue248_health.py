#!/usr/bin/env python3
"""Raw, bounded platform-health custody for Issue #248.

CPU-only by design: collection is read-only ``journalctl`` and
``nvidia-smi`` invocation; samples must be passed in from the execution
producer's returned ``device_samples``. This module never starts a GPU,
model, or workload. Summaries are always re-derived by
:func:`verify_platform_health` from retained bytes.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import os
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

SCHEMA = "inferswarm.issue248.platform-health/1"
ARTIFACT_KINDS = ("kernel_journal", "nvidia_smi", "producer_samples")
REQUIRED_SAMPLE_STAGES = {"before", "during", "after"}
NVIDIA_QUERY = ("uuid,temperature.gpu,power.draw,power.limit,"
                "clocks_throttle_reasons.active")


class PlatformHealthError(RuntimeError):
    """Health evidence is absent, malformed, out of window, or unretainable."""


def read_amd_hwmon(root: Path) -> dict[str, str]:
    """Read raw AMD driver sensors from one sysfs hwmon node, no GPU work.

    Required temperature and power measurements must be present; driver
    thermal/power limits are retained when exported. No numeric policy
    threshold is introduced here. A missing/ambiguous node fails closed.
    """
    candidates = sorted(Path(root).glob("hwmon*"))
    if len(candidates) != 1 or not candidates[0].is_dir():
        raise PlatformHealthError("AMD hwmon node missing or ambiguous")
    node = candidates[0]
    raw: dict[str, str] = {}
    for name in ("temp1_input", "temp1_crit", "power1_average",
                 "power1_cap", "power1_crit"):
        path = node / name
        if path.is_file():
            raw[name] = path.read_text()
    if "temp1_input" not in raw or "power1_average" not in raw:
        raise PlatformHealthError("AMD temperature/power driver data missing")
    for key, value in raw.items():
        if not re.fullmatch(r"\d+\s*", value):
            raise PlatformHealthError(f"AMD sensor malformed: {key}")
    return raw


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: bytes
    stderr: bytes = b""


def _run_readonly(argv: list[str], *, timeout: int = 30) -> CommandResult:
    completed = subprocess.run(argv, capture_output=True, timeout=timeout,
                               check=False)
    return CommandResult(completed.returncode, completed.stdout,
                         completed.stderr)


def _aware_timestamp(value: Any, label: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise PlatformHealthError(f"{label}: timestamp must be a string")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PlatformHealthError(f"{label}: invalid timestamp") from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise PlatformHealthError(f"{label}: timestamp must include timezone")
    return result.astimezone(timezone.utc)


def _bounded_window(start: str, end: str) -> tuple[datetime, datetime]:
    first, last = _aware_timestamp(start, "window start"), _aware_timestamp(end, "window end")
    if first >= last:
        raise PlatformHealthError("window start must precede window end")
    return first, last


def _stdout(result: Any, label: str) -> bytes:
    if isinstance(result, subprocess.CompletedProcess):
        rc, raw = result.returncode, result.stdout
    else:
        rc, raw = getattr(result, "returncode", None), getattr(result, "stdout", None)
    if type(rc) is not int or rc != 0:
        raise PlatformHealthError(f"{label}: command failed (exit={rc!r}); no fallback")
    if not isinstance(raw, bytes):
        if isinstance(raw, str):
            raw = raw.encode("utf-8")
        else:
            raise PlatformHealthError(f"{label}: command stdout is not bytes")
    return raw


def _validate_journal(raw: bytes, start: datetime, end: datetime) -> None:
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise PlatformHealthError("kernel journal is not UTF-8") from exc
    # A successful bounded journalctl query returning zero rows is a valid
    # negative observation; it is not an absent artifact. Command success,
    # exact window, and the retained (possibly zero-byte) stdout are bound
    # separately in the receipt.
    if text in ("", "-- No entries --\n"):
        return
    for index, line in enumerate(text.splitlines(), 1):
        # short-iso-precise timestamps are required on every journal row;
        # accepting continuation or untimestamped output breaks window identity.
        match = re.match(r"^(\d{4}-\d\d-\d\d[T ][^ ]+)\s+", line)
        if not match:
            raise PlatformHealthError(f"kernel journal line {index} lacks timestamp")
        when = _aware_timestamp(match.group(1), f"journal line {index}")
        if not start <= when <= end:
            raise PlatformHealthError(f"kernel journal line {index} outside requested window")


def _validate_samples(samples: Any, start: datetime, end: datetime,
                      expected_arm: str | None = None) -> list[dict[str, Any]]:
    if not isinstance(samples, list) or not samples:
        raise PlatformHealthError("producer device_samples must be a non-empty list")
    copied: list[dict[str, Any]] = []
    seen: set[str] = set()
    previous: datetime | None = None
    phases = {"before": 0, "during": 1, "after": 2}
    previous_phase = 0
    for index, sample in enumerate(samples):
        if not isinstance(sample, dict):
            raise PlatformHealthError(f"sample {index} is not an object")
        stage = sample.get("stage")
        if stage not in ("before", "during", "after"):
            raise PlatformHealthError(f"sample {index} has unknown stage")
        stamp = _aware_timestamp(sample.get("captured_at"), f"sample {index}")
        if not start <= stamp <= end:
            raise PlatformHealthError(f"sample {index} outside requested window")
        if ((index == 0 and stage != "before")
                or phases[stage] < previous_phase
                or (previous is not None and stamp < previous)):
            raise PlatformHealthError("sample stage/time order invalid")
        previous, previous_phase = stamp, phases[stage]
        if expected_arm == "B":
            smi_raw = sample.get("nvidia_smi_raw")
            if not isinstance(smi_raw, str):
                raise PlatformHealthError("NVIDIA executing-device telemetry missing")
            _parse_smi(smi_raw.encode("utf-8"))
        if expected_arm == "C":
            sensor = sample.get("amd_hwmon_raw")
            if (not isinstance(sensor, dict)
                    or not {"temp1_input", "power1_average"} <= set(sensor)
                    or set(sensor) - {"temp1_input", "temp1_crit",
                                      "power1_average", "power1_cap",
                                      "power1_crit"}):
                raise PlatformHealthError("AMD executing-device sensors missing/malformed")
            for key, value in sensor.items():
                if not isinstance(value, str) or not re.fullmatch(r"\d+\s*", value):
                    raise PlatformHealthError(f"AMD sensor malformed: {key}")
        seen.add(stage)
        copied.append(dict(sample))
    missing = sorted(REQUIRED_SAMPLE_STAGES - seen)
    if missing:
        raise PlatformHealthError(f"producer samples missing stages: {missing}")
    if copied[-1]["stage"] != "after":
        raise PlatformHealthError("last device sample is not post-execution")
    return copied


def _write_new_artifact(root: Path, rel: str, raw: bytes,
                        start: str, end: str, kind: str) -> dict[str, Any]:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError as exc:
        raise PlatformHealthError(f"refusing to overwrite retained artifact: {rel}") from exc
    return {"kind": kind, "path": rel, "bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "window": {"start": start, "end": end}}


def capture_platform_health(
    evidence_dir: Path, start: str, end: str, *, samples: list[dict[str, Any]],
    runner: Callable[..., Any] = _run_readonly,
) -> dict[str, Any]:
    """Capture bounded raw health bytes into a fresh evidence directory.

    ``samples`` must be the execution producer's returned ``device_samples``;
    this helper intentionally does not take its own substituted samples.
    Commands are read-only and injected in CPU-only tests.
    """
    evidence_dir = Path(evidence_dir)
    first, last = _bounded_window(start, end)
    checked_samples = _validate_samples(samples, first, last)
    journal_argv = ["journalctl", "--since", start, "--until", end,
                    "--no-pager", "-k", "-o", "short-iso-precise"]
    journal = _stdout(runner(journal_argv, timeout=30), "journalctl")
    _validate_journal(journal, first, last)
    smi_argv = ["nvidia-smi", f"--query-gpu={NVIDIA_QUERY}",
                "--format=csv,noheader,nounits"]
    smi = _stdout(runner(smi_argv, timeout=30), "nvidia-smi")
    _parse_smi(smi)
    sample_bytes = (json.dumps(checked_samples, sort_keys=True,
                              separators=(",", ":"), allow_nan=False) + "\n").encode()
    artifacts = [
        _write_new_artifact(evidence_dir, "kernel-journal.raw", journal,
                            start, end, "kernel_journal"),
        _write_new_artifact(evidence_dir, "nvidia-smi.csv.raw", smi,
                            start, end, "nvidia_smi"),
        _write_new_artifact(evidence_dir, "device-samples.json", sample_bytes,
                            start, end, "producer_samples"),
    ]
    receipt = {"schema": SCHEMA, "window": {"start": start, "end": end},
               "collection": {
                   "kernel_journal": {"argv": journal_argv, "returncode": 0},
                   "nvidia_smi": {"argv": smi_argv, "returncode": 0},
               }, "artifacts": artifacts}
    _write_new_artifact(evidence_dir, "platform-health-receipt.json",
                        (json.dumps(receipt, sort_keys=True, indent=2) + "\n").encode(),
                        start, end, "receipt")
    return receipt


def _parse_smi(raw: bytes) -> list[dict[str, Any]]:
    try:
        text = raw.decode("utf-8", errors="strict")
        rows = list(csv.reader(io.StringIO(text), skipinitialspace=True))
    except (UnicodeDecodeError, csv.Error) as exc:
        raise PlatformHealthError("nvidia-smi CSV malformed") from exc
    if not rows:
        raise PlatformHealthError("nvidia-smi returned no GPU rows")
    parsed = []
    for index, row in enumerate(rows, 1):
        if len(row) != 5:
            raise PlatformHealthError(f"nvidia-smi row {index} has wrong field count")
        uuid, temp, power, power_limit, active = (field.strip() for field in row)
        if not uuid.startswith("GPU-"):
            raise PlatformHealthError(f"nvidia-smi row {index} has invalid GPU UUID")
        try:
            values = [float(temp), float(power), float(power_limit)]
            active_value = int(active, 0)
        except ValueError as exc:
            raise PlatformHealthError(f"nvidia-smi row {index} has invalid numeric field") from exc
        if not all(math.isfinite(x) for x in values) or active_value < 0:
            raise PlatformHealthError(f"nvidia-smi row {index} has non-finite/negative data")
        parsed.append({"uuid": uuid, "temperature.gpu": values[0],
                       "power.draw": values[1], "power.limit": values[2],
                       "clocks_throttle_reasons.active": active_value})
    return parsed


def _fatal_findings(journal: bytes, telemetry: list[dict[str, Any]],
                    start: str, end: str, *,
                    expected_bdf: str | None = None,
                    expected_gpu_uuid: str | None = None) -> list[dict[str, Any]]:
    first, last = _bounded_window(start, end)
    findings: list[dict[str, Any]] = []
    text = journal.decode("utf-8")
    for index, line in enumerate(text.splitlines(), 1):
        stamp_match = re.match(r"^(\d{4}-\d\d-\d\d[T ][^ ]+)\s+", line)
        if not stamp_match:
            continue
        when = _aware_timestamp(stamp_match.group(1), f"journal line {index}")
        if not first <= when <= last:
            continue
        body = line[stamp_match.end():]
        # A device-specific event is causal for this subject only when the
        # retained log names its PCI function. An upstream bridge needs an
        # independently retained topology join, so a bare root-port AER
        # line is not automatically attributed to the GPU.
        subject_named = (expected_bdf is None or bool(re.search(
            r"(?<![0-9a-f])(?:[0-9a-f]{4,8}:)?"
            + re.escape(expected_bdf[-7:-2]) + r"(?:\." +
            re.escape(expected_bdf[-1]) + r")?(?![0-9a-f])",
            body, re.I)))
        checks = (
            ("NVIDIA_XID", subject_named and re.search(r"\bXid\s*\(", body, re.I)),
            ("PCIe_AER_FATAL", subject_named and re.search(r"AER:.*(?:Uncorrected\s*\(Fatal\)|severity=Uncorrected\s*\(Fatal\))", body, re.I)),
            ("KERNEL_FATAL", re.search(r"\b(?:kernel BUG at|Oops:|Kernel panic|general protection fault)\b", body, re.I)),
            ("GPU_DEVICE_LOST", subject_named and re.search(r"(?:GPU has fallen off the bus|GPU.*(?:reset|fallen off the bus))", body, re.I)),
        )
        for kind, matched in checks:
            if matched:
                findings.append({"kind": kind, "source": "kernel_journal",
                                 "line": index, "timestamp": stamp_match.group(1),
                                 "causal_window": True, "raw_line": line})
    # Post-run, untimestamped telemetry is retained for identity/context only.
    # It cannot establish a causal throttle state inside the unit window.
    return findings


def _sample_findings(samples: list[dict[str, Any]], start: str,
                     end: str, *, expected_gpu_uuid: str | None = None
                     ) -> list[dict[str, Any]]:
    """Read explicit low-level markers from producer sample payloads only."""
    first, last = _bounded_window(start, end)
    findings = []
    # Values are exact machine indicators, not free-text summary matching.
    # XID/ECC counters are positive integer codes/counts; limit/violation
    # fields must be literal true. Temperature and watt values never enter.
    counter_keys = {"xid_code": "NVIDIA_XID_SAMPLE",
                    "ecc_uncorrected": "ECC_UNCORRECTED",
                    "ecc_uncorrectable": "ECC_UNCORRECTED"}
    boolean_keys = {"thermal_violation": "THERMAL_VIOLATION",
                    "power_violation": "POWER_VIOLATION",
                    "overcurrent": "OVERCURRENT"}
    for sample_index, sample in enumerate(samples):
        timestamp = sample["captured_at"]
        when = _aware_timestamp(timestamp, f"sample {sample_index}")
        if not first <= when <= last:
            continue
        smi_raw = sample.get("nvidia_smi_raw")
        if smi_raw is not None:
            if not isinstance(smi_raw, str):
                raise PlatformHealthError("in-window NVIDIA telemetry must be text")
            smi_rows = _parse_smi(smi_raw.encode("utf-8"))
            matched = [row for row in smi_rows
                       if expected_gpu_uuid is None or row["uuid"] == expected_gpu_uuid]
            if expected_gpu_uuid is not None and len(matched) != 1:
                raise PlatformHealthError("in-window executing GPU telemetry missing/duplicate")
            for row in matched:
                active = row["clocks_throttle_reasons.active"]
                for kind, mask in (("NVIDIA_THERMAL_LIMIT_ACTIVE", 0x60),
                                   ("NVIDIA_POWER_BRAKE_ACTIVE", 0x80)):
                    if active & mask:
                        findings.append({"kind": kind,
                                         "source": "in_window_nvidia_sample",
                                         "uuid": row["uuid"],
                                         "active_mask": active,
                                         "sample_index": sample_index,
                                         "timestamp": timestamp,
                                         "causal_window": True})
        sensor = sample.get("amd_hwmon_raw")
        if isinstance(sensor, dict):
            for measured, critical, kind in (
                    ("temp1_input", "temp1_crit", "AMD_THERMAL_CRITICAL"),
                    ("power1_average", "power1_crit", "AMD_POWER_CRITICAL")):
                if critical in sensor and int(sensor[measured]) >= int(sensor[critical]):
                    findings.append({"kind": kind, "source": "amd_hwmon_driver_limit",
                                     "sample_index": sample_index,
                                     "timestamp": timestamp,
                                     "measured": sensor[measured],
                                     "driver_critical": sensor[critical],
                                     "causal_window": True})
        stack: list[Any] = [sample]
        while stack:
            node = stack.pop()
            if isinstance(node, dict):
                for key, value in node.items():
                    if isinstance(value, (dict, list)):
                        stack.append(value)
                    normalized = str(key).lower().replace("-", "_")
                    kind = counter_keys.get(normalized)
                    if kind and type(value) is int and value > 0:
                        findings.append({"kind": kind, "source": "producer_sample",
                                         "sample_index": sample_index,
                                         "field": key, "value": value,
                                         "timestamp": timestamp,
                                         "causal_window": True})
                    kind = boolean_keys.get(normalized)
                    if kind and value is True:
                        findings.append({"kind": kind, "source": "producer_sample",
                                         "sample_index": sample_index,
                                         "field": key, "value": True,
                                         "timestamp": timestamp,
                                         "causal_window": True})
            elif isinstance(node, list):
                stack.extend(node)
    return findings


def verify_platform_health(evidence_dir: Path,
                           receipt: dict[str, Any] | None = None, *,
                           expected_gpu_uuid: str | None = None,
                           expected_bdf: str | None = None,
                           expected_arm: str | None = None) -> dict[str, Any]:
    """Recompute custody, parsing, sample completeness and fatal findings.

    The caller's summary fields are ignored. Every artifact must match the
    receipt's exact relative path, byte count, digest, and identical window.
    """
    root = Path(evidence_dir)
    problems: list[str] = []
    try:
        if receipt is None:
            receipt = json.loads((root / "platform-health-receipt.json").read_bytes())
        if not isinstance(receipt, dict) or receipt.get("schema") != SCHEMA:
            raise PlatformHealthError("receipt schema mismatch")
        window = receipt.get("window")
        if not isinstance(window, dict) or set(window) != {"start", "end"}:
            raise PlatformHealthError("receipt window malformed")
        first, last = _bounded_window(window["start"], window["end"])
        # The caller may decorate a returned verifier summary (for example,
        # fatal_states); only the on-disk custody descriptor is authoritative.
        # Compare its schema/window/artifact ledger with the supplied receipt,
        # so a caller cannot substitute a new digest ledger during verify.
        stored = json.loads((root / "platform-health-receipt.json").read_bytes())
        for field in ("schema", "window", "collection", "artifacts"):
            if stored.get(field) != receipt.get(field):
                raise PlatformHealthError(f"receipt {field} differs from retained receipt")
        collection = receipt.get("collection")
        if not isinstance(collection, dict) or set(collection) != {
                "kernel_journal", "nvidia_smi"}:
            raise PlatformHealthError("health collection provenance missing")
        expected_journal = ["journalctl", "--since", window["start"],
                            "--until", window["end"], "--no-pager", "-k",
                            "-o", "short-iso-precise"]
        expected_smi = ["nvidia-smi", f"--query-gpu={NVIDIA_QUERY}",
                        "--format=csv,noheader,nounits"]
        if collection["kernel_journal"] != {"argv": expected_journal,
                                             "returncode": 0}:
            raise PlatformHealthError("journal collection window/command mismatch")
        if collection["nvidia_smi"] != {"argv": expected_smi,
                                        "returncode": 0}:
            raise PlatformHealthError("driver telemetry collection command mismatch")
        artifacts = receipt.get("artifacts")
        if not isinstance(artifacts, list) or len(artifacts) != len(ARTIFACT_KINDS):
            raise PlatformHealthError("artifact population incomplete")
        by_kind: dict[str, bytes] = {}
        expected_paths = {"kernel_journal": "kernel-journal.raw",
                          "nvidia_smi": "nvidia-smi.csv.raw",
                          "producer_samples": "device-samples.json"}
        if {a.get("kind") for a in artifacts if isinstance(a, dict)} != set(ARTIFACT_KINDS):
            raise PlatformHealthError("artifact kinds incomplete or duplicated")
        for artifact in artifacts:
            if not isinstance(artifact, dict):
                raise PlatformHealthError("artifact receipt malformed")
            kind, rel = artifact.get("kind"), artifact.get("path")
            if rel != expected_paths.get(kind) or not isinstance(rel, str):
                raise PlatformHealthError("artifact path does not match kind")
            if Path(rel).is_absolute() or ".." in Path(rel).parts:
                raise PlatformHealthError("artifact path traversal rejected")
            path = root / rel
            if path.is_symlink() or not path.is_file():
                raise PlatformHealthError(f"artifact missing or symlink: {rel}")
            raw = path.read_bytes()
            if artifact.get("window") != window:
                raise PlatformHealthError(f"artifact window mismatch: {rel}")
            if type(artifact.get("bytes")) is not int or artifact["bytes"] != len(raw):
                raise PlatformHealthError(f"byte count mismatch: {rel}")
            digest = hashlib.sha256(raw).hexdigest()
            if artifact.get("sha256") != digest:
                raise PlatformHealthError(f"sha256 mismatch: {rel}")
            by_kind[kind] = raw
        _validate_journal(by_kind["kernel_journal"], first, last)
        telemetry = _parse_smi(by_kind["nvidia_smi"])
        if (expected_gpu_uuid is not None and
                sum(row["uuid"] == expected_gpu_uuid for row in telemetry) != 1):
            raise PlatformHealthError("executing GPU telemetry identity missing/duplicate")
        samples = json.loads(by_kind["producer_samples"].decode("utf-8"))
        samples = _validate_samples(samples, first, last,
                                    expected_arm=expected_arm)
        findings = _fatal_findings(by_kind["kernel_journal"], telemetry,
                                   window["start"], window["end"],
                                   expected_bdf=expected_bdf,
                                   expected_gpu_uuid=expected_gpu_uuid)
        findings.extend(_sample_findings(samples, window["start"],
                                         window["end"],
                                         expected_gpu_uuid=expected_gpu_uuid))
        return {"valid": True, "schema": SCHEMA, "window": window,
                "fatal_findings": findings, "fatal_states": findings,
                "telemetry": telemetry, "samples": samples,
                "negative_proof": {"journal_window_complete": True,
                                    "nvidia_smi_rows_present": bool(telemetry),
                                    "sample_stages_complete": True,
                                    "fatal_findings_empty": not findings}}
    except (OSError, ValueError, TypeError, KeyError, PlatformHealthError) as exc:
        problems.append(str(exc))
        return {"valid": False, "schema": SCHEMA,
                "fatal_findings": [], "fatal_states": [], "problems": problems,
                "negative_proof": {"journal_window_complete": False,
                                    "nvidia_smi_rows_present": False,
                                    "sample_stages_complete": False,
                                    "fatal_findings_empty": False}}
