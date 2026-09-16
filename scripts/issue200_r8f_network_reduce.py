#!/usr/bin/env python3
"""Deterministically reduce an unmodified ``strace -xx`` send capture.

Only client-to-server ``sendto`` records bound to the retained PID and
endpoint are counted.  Immutable bytes are discovered by matching the actual
observed SET_TENSOR byte strings; no authored event classification is read.
"""
from __future__ import annotations

import ast
import hashlib
import re
from pathlib import Path
from typing import Any

from issue74_methodology import canonical_json_bytes

LINE = re.compile(r'^(?P<pid>\d+)\s+\S+\s+sendto\([^,]+,\s*(?P<data>"(?:[^"\\]|\\.)*"),\s*(?P<length>\d+).*?sin_port=htons\((?P<port>\d+)\).*?inet_addr\("(?P<host>[^"]+)"\).*?=\s*(?P<result>-?\d+)\s*$')


def reducer_sha256() -> str:
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def reduce_capture(raw: bytes, *, client_pid: int, server_endpoint: str,
                   payloads: list[dict[str, Any]]) -> dict[str, Any]:
    host, port_text = server_endpoint.rsplit(":", 1)
    port = int(port_text)
    sends: list[bytes] = []
    for line in raw.decode("utf-8", "strict").splitlines():
        match = LINE.match(line)
        if not match:
            continue
        if int(match["pid"]) != client_pid or match["host"] != host or int(match["port"]) != port:
            continue
        data = ast.literal_eval(match["data"]).encode("latin1")
        if len(data) != int(match["length"]) or int(match["result"]) != len(data):
            raise ValueError("strace send length/result does not bind raw bytes")
        sends.append(data)
    if not sends:
        raise ValueError("raw capture has no client-to-server sends for bound PID/endpoint")
    immutable = 0
    matched: list[dict[str, Any]] = []
    for payload in payloads:
        data = payload["bytes"]
        if len(data) != payload["length"] or hashlib.sha256(data).hexdigest() != payload["sha256"]:
            raise ValueError("payload bytes do not bind observation identity")
        exact = [chunk for chunk in sends if chunk == data]
        partial = [chunk for chunk in sends if chunk and chunk != data and chunk in data]
        if len(exact) > 1 or (exact and partial):
            raise ValueError("payload transfer is duplicated or only partly accounted")
        if partial:
            raise ValueError("only part of frozen SET_TENSOR payload appears in raw capture")
        if exact:
            immutable += len(data)
            matched.append({key: payload[key] for key in ("participant", "observation_id", "order", "offset", "length", "sha256")})
    total = sum(map(len, sends))
    return {"schema": "inferswarm.issue200.network-reduction/1",
            "reducer_sha256": reducer_sha256(), "client_to_server_bytes": total,
            "immutable_payload_bytes": immutable, "protocol_control_hash_probe_bytes": total - immutable,
            "payload_identities": sorted(matched, key=lambda item: item["order"])}


def canonical_reduce(*args: Any, **kwargs: Any) -> bytes:
    return canonical_json_bytes(reduce_capture(*args, **kwargs))
