#!/usr/bin/env python3
"""Fail-closed reduction of the retained Phase-5 strace capture.

The pinned client establishes its RPC TCP peer with ``connect`` and emits RPC
bytes with ``sendto``.  The capture records network plus write/writev; a
different bound-peer outbound form is a rejection, never a zero-byte claim.
"""
from __future__ import annotations

import ast
import hashlib
import re
from pathlib import Path
from typing import Any

from issue74_methodology import canonical_json_bytes


# One exact argv contract, not an authored list that merely contains ``-xx``.
# ``-s 0`` is strace's unlimited string limit.  ``network`` catches send*;
# write/writev catch socket writes outside strace's network class.
CAPTURE_TOOL = "strace phase5-full-payload/1"
CAPTURE_PREFIX = ("strace", "-ttt", "-xx", "-s", "0", "-e",
                  "trace=network,write,writev", "-p")
SUPPORTED_OUTBOUND = "sendto"
OTHER_OUTBOUND = {"send", "sendmsg", "sendmmsg", "write", "writev"}
PID_LINE = re.compile(r"^(?P<pid>\d+)\s+\S+\s+(?P<record>.*)$")
CALL = re.compile(r"^(?P<name>[a-z][a-z0-9_]*)\(")
FD = re.compile(r"^[a-z][a-z0-9_]*\((?P<fd>\d+)(?:,|\))")
RESULT = re.compile(r"\)\s+=\s*(?P<result>-?\d+)\s*$")
PORT = re.compile(r"sin_port=htons\((?P<port>\d+)\)")
HOST = re.compile(r'inet_addr\("(?P<host>[^"]+)"\)')
STRING = r'"(?:[^"\\]|\\.)*"'
SENDTO = re.compile(r"^sendto\((?P<fd>\d+),\s*(?P<data>" + STRING
                    + r"),\s*(?P<length>\d+),")
# strace writes a closing quote followed by an ellipsis on abbreviation.  This
# cannot match literal dots inside the quoted payload.
ABBREVIATED_STRING = re.compile(STRING + r"\.\.\.")


def required_capture_command(client_pid: int) -> list[str]:
    """The only capture argv eligible for a Phase-5 claim."""
    if not isinstance(client_pid, int) or client_pid <= 0:
        raise ValueError("capture client PID must be a positive integer")
    return [*CAPTURE_PREFIX, str(client_pid)]


def validate_capture_contract(command: Any, client_pid: int) -> None:
    """Mechanically bind unlimited payload capture, syscall coverage and PID."""
    if command != required_capture_command(client_pid):
        raise ValueError("capture command does not equal the Phase-5 full-payload/PID syscall contract")


def reducer_sha256() -> str:
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def _endpoint(record: str) -> tuple[str, int] | None:
    host, port = HOST.search(record), PORT.search(record)
    if host is None or port is None:
        return None
    return host["host"], int(port["port"])


def _fd(record: str) -> int | None:
    match = FD.match(record)
    return int(match["fd"]) if match else None


def _complete_data(text: str) -> bytes:
    try:
        value = ast.literal_eval(text)
    except (SyntaxError, ValueError) as error:
        raise ValueError("strace outbound data string is not decodable") from error
    if not isinstance(value, str):
        raise ValueError("strace outbound data argument is not a string")
    try:
        return value.encode("latin1")
    except UnicodeEncodeError as error:
        raise ValueError("strace outbound data string is not byte-preserving") from error


def reduce_capture(raw: bytes, *, client_pid: int, server_endpoint: str,
                   payloads: list[dict[str, Any]]) -> dict[str, Any]:
    """Derive counts only from complete raw records for the bound peer.

    Only another PID or an explicit different endpoint is ignored.  A bound
    peer's malformed/abbreviated/unsupported outbound record fails closed.
    """
    try:
        host, port_text = server_endpoint.rsplit(":", 1)
        target = (host, int(port_text))
    except (ValueError, TypeError) as error:
        raise ValueError("bound server endpoint must be host:port") from error
    if not isinstance(client_pid, int) or client_pid <= 0:
        raise ValueError("bound client PID must be a positive integer")
    try:
        lines = raw.decode("utf-8", "strict").splitlines()
    except UnicodeDecodeError as error:
        raise ValueError("raw strace capture is not strict UTF-8") from error

    sends: list[bytes] = []
    fd_peers: dict[int, tuple[str, int]] = {}
    socket_fds: set[int] = set()
    for line in lines:
        prefixed = PID_LINE.match(line)
        if prefixed is None or int(prefixed["pid"]) != client_pid:
            continue
        record = prefixed["record"]
        name_match = CALL.match(record)
        if name_match is None:
            if any(token in record for token in (*OTHER_OUTBOUND, "sendto")):
                raise ValueError("bound outbound strace record is incomplete or unparseable")
            continue
        name, fd = name_match["name"], _fd(record)
        if name == "socket":
            result = RESULT.search(record)
            if result and int(result["result"]) >= 0:
                socket_fds.add(int(result["result"]))
            continue
        if name == "connect":
            result, endpoint = RESULT.search(record), _endpoint(record)
            if fd is not None and result and int(result["result"]) == 0 and endpoint is not None:
                fd_peers[fd] = endpoint
            continue
        if name in OTHER_OUTBOUND:
            # send* always writes a socket.  write* becomes relevant after a
            # socket() receipt; this exact pinned path has neither form.
            if name.startswith("send") or (fd is not None and fd in socket_fds):
                raise ValueError(f"unsupported outbound {name} record in Phase-5 capture")
            continue
        if name != SUPPORTED_OUTBOUND:
            continue

        endpoint = _endpoint(record)
        relevant = endpoint == target or (endpoint is None and fd is not None and fd_peers.get(fd) == target)
        if not relevant:
            if endpoint is not None:  # mechanically shown to be a different peer
                continue
            raise ValueError("sendto peer cannot be mechanically bound to the retained endpoint")
        if ABBREVIATED_STRING.search(record):
            raise ValueError("relevant sendto payload is abbreviated by strace")
        match, result = SENDTO.match(record), RESULT.search(record)
        if match is None or result is None:
            raise ValueError("relevant sendto record is unparseable")
        data = _complete_data(match["data"])
        if len(data) != int(match["length"]) or int(result["result"]) != len(data):
            raise ValueError("strace send length/result does not bind complete raw bytes")
        sends.append(data)
    if not sends:
        raise ValueError("raw capture has no client-to-server sends for bound PID/endpoint")
    immutable, matched = 0, []
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
