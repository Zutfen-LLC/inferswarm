"""Parser for the retained RAW realize-strace logs (Issue #117 Arm B).

Input: evidence/arm-b/raw/realize-strace.stage-{1,2,3}.log — byte-exact
copies of the participant-host realization strace logs captured by the
historical command (retained in raw/producer/armb_materialize.py):

    strace -f -qq -e trace=file -o <log> <child python> armb_realize_child.py …

Because the historical trace filtered to file-class syscalls ONLY, this
parser NEVER claims byte-level read/movement measurement: it derives
path-level open facts only. Byte-level steady-state conclusions must come
from the runtime lifecycle counters in realize-stage-N.json plus the
pinned producer source semantics (see the reducer's movement section).
"""
from __future__ import annotations

import hashlib
import re

#: pins of the raw logs as retained (repo copy must match host copy)
RAW_STRACE_SHA256 = {
    "realize-strace.stage-1.log":
        "36c8845b35e2387c383e9a53ca8d943eaa448ad432ad69a385b33a2ed8a73b13",
    "realize-strace.stage-2.log":
        "ffbf4ddbe1bea8efdcbb11fe5a983e096284cd083193c0b2da07954a4f195d9f",
    "realize-strace.stage-3.log":
        "5703a180438172626f7c6585fbe99ba5253c8fff31aed3af894ce25b0d30c033",
}

CACHE_ROOT = "/srv/inferswarm/cache/issue117"
SOURCE_TREE = "/srv/models/gemma-r6/"
MATERIALIZED_ROOT = "/srv/inferswarm/materialized/issue117/"
#: the participant shard object (the only model-data file under the root)
SHARD_OBJECT = "armb-participant.safetensors"
#: post-finalization WRITES the child provably performs (report output);
#: opening these for WRITE after the last shard read is not model-state
#: movement. Any OTHER model-state path open after the boundary is.
POST_FINALIZATION_WRITE_ALLOWLIST = ("realize-report.json",)

_FILE_LINE = re.compile(
    r'^\d+ (?:\d+\.\d+ )?(?P<call>openat|open|creat|truncate|ftruncate)\('
)


def _extract_path(line: str):
    m = re.search(r'"((?:[^"\\]|\\.)*)"', line)
    if not m:
        return None
    return m.group(1).replace('\\"', '"')


def parse_file(path) -> dict:
    """Derive open-facts from one raw strace log. Fails on sha256 drift."""
    name = str(path).rsplit("/", 1)[-1]
    if name not in RAW_STRACE_SHA256:
        raise ValueError(f"unrecognized raw strace log: {name}")
    data = open(path, "rb").read()
    if hashlib.sha256(data).hexdigest() != RAW_STRACE_SHA256[name]:
        raise ValueError(
            f"raw strace log sha256 drift: {name} is not the retained raw "
            f"log (expected {RAW_STRACE_SHA256[name][:16]}…)")
    lines = data.decode("utf-8", "replace").splitlines()
    line_count = len(lines)
    last_shard_open_line = None
    shard_open_count = 0
    model_state_opens_total = 0
    cache_root_opens = 0
    source_tree_opens = 0
    nvidia_nodes = set()
    model_state_opens_after_last_shard_open = []
    non_file_syscalls = 0
    for idx, line in enumerate(lines, 1):
        m = _FILE_LINE.match(line)
        if m is None:
            # count data-class syscalls if any slipped past -e trace=file
            if re.match(r"^\d+ (?:\d+\.\d+ )?(read|pread64|pwrite64|mmap)\(", line):
                non_file_syscalls += 1
            continue
        path_ = _extract_path(line)
        if path_ is None:
            continue
        call = m.group("call")
        if call in ("truncate", "ftruncate") and path_ == "-1":
            # ftruncate carries no path argument
            continue
        if path_.startswith("/dev/nvidia"):
            nvidia_nodes.add(path_)
            continue
        is_shard = path_.startswith(MATERIALIZED_ROOT)
        is_cache = path_.startswith(CACHE_ROOT)
        is_source = path_.startswith(SOURCE_TREE)
        if is_shard:
            shard_open_count += 1
            model_state_opens_total += 1
            # the boundary is the last MODEL-DATA open: the shard object.
            # Post-finalization report WRITES under the same root are
            # classified separately (they are the child's own output, not
            # model-state movement).
            if path_.endswith("/" + SHARD_OBJECT):
                last_shard_open_line = idx
        elif is_cache:
            cache_root_opens += 1
            model_state_opens_total += 1
        elif is_source:
            source_tree_opens += 1
            model_state_opens_total += 1
    # second pass for the post-boundary window: every model-state path
    # open after the last shard open EXCEPT the report write allowlist
    if last_shard_open_line is not None:
        for idx, line in enumerate(lines, 1):
            if idx <= last_shard_open_line:
                continue
            m = _FILE_LINE.match(line)
            if m is None:
                continue
            path_ = _extract_path(line)
            if path_ and (path_.startswith(MATERIALIZED_ROOT)
                          or path_.startswith(CACHE_ROOT)
                          or path_.startswith(SOURCE_TREE)):
                if any(path_.endswith("/" + name) for name in
                       POST_FINALIZATION_WRITE_ALLOWLIST):
                    continue
                model_state_opens_after_last_shard_open.append(
                    {"line": idx, "path": path_})
    return {
        "raw_log": name,
        "strace_sha256": RAW_STRACE_SHA256[name],
        "lines": line_count,
        "shard_open_count": shard_open_count,
        "cache_root_opens": cache_root_opens,
        "source_tree_opens": source_tree_opens,
        "model_state_opens_total": model_state_opens_total,
        "nvidia_nodes_opened": sorted(nvidia_nodes),
        "model_state_opens_after_last_shard_open":
            model_state_opens_after_last_shard_open,
        "last_shard_open_line": last_shard_open_line,
        "data_class_syscall_lines_observed": non_file_syscalls,
    }
