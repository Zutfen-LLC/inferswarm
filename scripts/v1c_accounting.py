#!/usr/bin/env python3
"""Issue #161 V1-C selector-aware successor accounting reducer.

This is the narrowest SUCCESSOR to the accepted V0-C materialization/
residency accounting reducer (``scripts/v0c_canonical_run.py::
parse_accounting``). The accepted reducer is hash-pinned by accepted
V0-C/V1-A/V1-B manifests and pins the first subject's observed
selector label in its named-buffer and memory-breakdown parsing; it
therefore fails closed on any other subject's transcript. This module
preserves the accepted accounting SEMANTICS byte-for-byte while
parameterizing the selected Vulkan resource label from trusted
authority/adapter data:

  * the exact expected selected resource label is a REQUIRED input
    consumed from frozen authority or an equivalently bound execution
    proof — it is never inferred from whichever device row happens to
    appear first in the transcript;
  * the selector identity is validated (it must be a ``Vulkan<N>``
    resource label) BEFORE any parsing;
  * named-buffer lines (``<selector> model/KV/compute buffer size``)
    and pre/post-ready device memory-breakdown rows are matched for
    that exact resource only;
  * host accounting semantics are unchanged (``CPU_Mapped`` /
    ``Vulkan_Host`` labels, Host before/after breakdown rows, no
    process-RSS inference).

The output schema is incremented to
``inferswarm.v0c.materialization-accounting/2``. Compatibility
semantics: on an identical transcript reduced under the matching
selector, every accounting FACT and every retained raw line of schema
/1 is reproduced IDENTICALLY; the only differences are (a) the schema
string, (b) a new ``selected_resource`` field naming the validated
selector the facts were reduced under, and (c) a ``predecessor``
pointer to the accepted /1 reducer identity. This equivalence is
proven mechanically (field-by-field) in ``tests/test_v1c_accounting.py``
against the ACCEPTED retained V1-A raw bytes and the accepted V1-A
accounting artifact, and byte-identical canonical-JSON equality holds
for the shared fact fields.

No selector, BDF, vendor, or device name is special-cased here: the
selector is consumed from the caller's frozen authority, and the only
``Vulkan<N>`` grammar knowledge here is the runtime's printed
resource-label grammar itself.
"""
from __future__ import annotations

import re
from typing import Any

MIB = 1024 * 1024

PREDECESSOR = {
    "reducer": "scripts/v0c_canonical_run.py::parse_accounting",
    "reducer_sha256": "db3eff0587204c5ea6aebde34380611dc34a58ba7f772293df425f61f3c546bb",
    "schema": "inferswarm.v0c.materialization-accounting/1",
    "limitation": "pinned the first subject's observed selector label; failed closed on any other subject",
}

SCHEMA = "inferswarm.v0c.materialization-accounting/2"

_SELECTOR_PATTERN = re.compile(r"^Vulkan[0-9]+$")


class AccountingError(RuntimeError):
    """Direct runtime accounting is absent, malformed, or contradictory."""


def validate_selector(selector: Any) -> str:
    """Validate the authority-provided selected Vulkan resource label.

    The selector must be a non-empty string matching the runtime's
    ``Vulkan<N>`` resource-label grammar. Anything else — missing,
    wrong type, empty, whitespace, a BDF, a vendor/device name — fails
    closed before any transcript parsing happens.
    """
    if not isinstance(selector, str) or not _SELECTOR_PATTERN.match(selector):
        raise AccountingError(f"malformed selected Vulkan resource identity: {selector!r}")
    return selector


def _line_values(stderr: str, label: str) -> tuple[int, list[str]]:
    pattern = re.compile(re.escape(label) + r"\s*=\s*([0-9]+(?:\.[0-9]+)?)\s+MiB")
    matches = [(round(float(match.group(1)) * MIB), line) for line in stderr.splitlines()
               if (match := pattern.search(line))]
    if len(matches) != 1:
        raise AccountingError(f"missing or ambiguous direct accounting line: {label}")
    return matches[0][0], [matches[0][1]]


def _breakdowns(stderr: str) -> tuple[list[dict[str, int | str]], list[str]]:
    # This is llama.cpp's printed accounting grammar, not a process/RSS estimate.
    expression = re.compile(
        r"\|\s+-\s+(?P<resource>Vulkan\d+|Host).*?\|\s*"
        r"(?:(?P<total>\d+)\s*=\s*)?(?P<free>\d+)\s*\+\s*"
        r"\(?(?P<self>\d+)\s*=\s*(?P<model>\d+)\s*\+\s*"
        r"(?P<context>\d+)\s*\+\s*(?P<compute>\d+)\)?"
    )
    rows, lines = [], []
    for line_index, line in enumerate(stderr.splitlines()):
        match = expression.search(line)
        if match:
            row = {key: (int(value) if value is not None else -1)
                   for key, value in match.groupdict().items() if key != "resource"}
            row["resource"] = match.group("resource")
            row["line_index"] = line_index
            rows.append(row)
            lines.append(line)
    return rows, lines


def parse_accounting(stderr: str, *, selector: str) -> dict[str, Any]:
    """Reduce direct llama.cpp buffer/breakdown diagnostics without RSS inference.

    Identical semantics to the accepted V0-C /1 reducer, with the
    selected Vulkan resource label consumed from trusted authority
    data instead of hardcoded to the first subject.
    """
    if not isinstance(stderr, str) or not stderr:
        raise AccountingError("runtime stderr is required for accounting")
    selector = validate_selector(selector)
    model, model_lines = _line_values(stderr, f"{selector} model buffer size")
    context, context_lines = _line_values(stderr, f"{selector} KV buffer size")
    compute, compute_lines = _line_values(stderr, f"{selector} compute buffer size")
    mapped, mapped_lines = _line_values(stderr, "CPU_Mapped model buffer size")
    output, output_lines = _line_values(stderr, "Vulkan_Host  output buffer size")
    host_compute, host_compute_lines = _line_values(stderr, "Vulkan_Host compute buffer size")
    all_lines = stderr.splitlines()
    ready_indices = [index for index, line in enumerate(all_lines)
                   if "cached n_tokens = 0" in line and "memory_seq_rm" in line]
    if len(ready_indices) != 1:
        raise AccountingError("missing or ambiguous ready-state accounting")
    ready_index = ready_indices[0]
    ready_lines = [all_lines[ready_index]]
    rows, breakdown_lines = _breakdowns(stderr)
    indexed_rows = list(zip(rows, breakdown_lines, strict=True))
    # Device rows for the EXACT authority-selected resource only. Rows
    # belonging to other Vulkan resources are inert for this reduction
    # and never mixed in; the fail-closed controls below still pin the
    # selected resource's own pre/post-ready rows to exactly one final
    # post-ready row.
    device_events = [(row, line, int(row["line_index"])) for row, line in indexed_rows
                     if row["resource"] == selector]
    host_pattern = re.compile(r"\|\s+-\s+Host\s+\|\s*(\d+)\s*=\s*(\d+)\s*\+\s*(\d+)\s*\+\s*(\d+)")
    host_events = [(tuple(map(int, match.groups())), line, index)
                   for index, line in enumerate(all_lines)
                   if (match := host_pattern.search(line))]
    pre_device = [(row, line, index) for row, line, index in device_events if index < ready_index]
    post_device = [(row, line, index) for row, line, index in device_events if index > ready_index]
    pre_host = [(row, line, index) for row, line, index in host_events if index < ready_index]
    post_host = [(row, line, index) for row, line, index in host_events if index > ready_index]
    if not pre_device:
        raise AccountingError("missing pre-ready direct device memory breakdown")
    if not post_device:
        raise AccountingError("missing final direct device memory breakdown")
    if not post_host:
        raise AccountingError("missing final direct host memory breakdown")
    if len(post_device) != 1:
        raise AccountingError("ambiguous final direct device memory breakdown")
    if len(post_host) != 1:
        raise AccountingError("ambiguous final direct host memory breakdown")
    before, before_line, _ = pre_device[-1]
    after, after_line, _ = post_device[0]
    (host_total, host_model, host_context, host_compute_mib), host_line, _ = post_host[0]
    for row, name in ((before, "before device"), (after, "after device")):
        # The displayed total/free/self columns include the runtime's explicit
        # unaccounted field, so only the directly decomposed self total is exact.
        if abs(row["self"] - (row["model"] + row["context"] + row["compute"])) > 1:
            raise AccountingError(f"contradictory {name} breakdown components")
    if host_total != host_model + host_context + host_compute_mib:
        raise AccountingError("contradictory host breakdown total")
    if (abs(after["model"] * MIB - model) > 2 * MIB
            or abs(after["context"] * MIB - context) > 2 * MIB
            or abs(after["compute"] * MIB - compute) > 2 * MIB):
        raise AccountingError("contradictory final device buffers and breakdown")
    if host_model * MIB + 2 * MIB < mapped or abs(host_compute_mib * MIB - host_compute) > 2 * MIB:
        raise AccountingError("contradictory host buffers and breakdown")
    # A direct Host model component not labelled CPU_Mapped is not silently zeroed.
    unexplained = max(0, (host_model * MIB) - mapped)
    after_ready = all_lines[ready_index + 1:]
    source_fetch_lines = [line for line in after_ready if re.search(r"\b(fetch|download|remote source)\b", line, re.I)]
    movement_lines = [line for line in after_ready if re.search(r"\b(rematerializ|state movement|migration|copying state)\b", line, re.I)]
    return {
        "schema": SCHEMA,
        "selected_resource": selector,
        "predecessor": PREDECESSOR,
        "device_resident_model_bytes": model,
        "device_context_bytes": context,
        "device_compute_bytes": compute,
        "required_persistent_host_bytes": 0,
        "intentional_host_mapping_or_cache_bytes": mapped,
        "host_context_kv_output_compute_bytes": output + host_compute,
        "released_staging_bytes": 0,
        "representation_conversion_bytes": 0,
        "unexplained_persistent_host_mirror_bytes": unexplained,
        "source_fetches_after_ready": len(source_fetch_lines),
        "unplanned_state_movements": len(movement_lines),
        "raw_lines": {
            "device_model": model_lines, "device_context": context_lines,
            "device_compute": compute_lines, "host_mapping": mapped_lines,
            "host_output": output_lines, "host_compute": host_compute_lines,
            "ready_state": ready_lines, "device_memory_before_after": [before_line, after_line],
            "host_memory_pre_realization": [line for _, line, _ in pre_host],
            "host_memory_final": [host_line],
            "source_fetches_after_ready": source_fetch_lines,
            "unplanned_state_movements": movement_lines,
        },
        "basis": "direct llama.cpp named buffers plus before/after memory-breakdown rows; never process RSS",
    }
