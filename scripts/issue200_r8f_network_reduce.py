#!/usr/bin/env python3
"""Fail-closed reduction of the retained process-wide Phase-5 strace capture.

Phase-5 correction round 2 (byte-complete capture, schema /4).  The previous
revision (/3) accepted strace's zero-length string limit (``-s 0``), under
which every nonempty send renders as ``""...``: the capture was LENGTH-only,
and the cold arm's "identity proof" was a length window.  Issue #200 requires
the exact immutable network bytes.  This revision therefore demands a
BYTE-COMPLETE capture:

- The capture argv is the frozen ``strace -f --always-show-pid -ttt -xx -s S
  -e trace=network,write,writev,execve <client-cmd...>``, started FROM EXEC
  (the traced process is a child of strace).  ``S`` is mechanically derived
  as ``max(payload_lengths) + FRAME_ALLOWANCE`` so the complete largest
  frozen framed payload is retained verbatim; the first tracee record MUST
  be the client's own ``execve`` of the recorded frozen client command —
  proving the capture began before the client existed and therefore before
  any participant connection.  A ``-p <pid>`` attach (capture starting after
  process creation) can never satisfy this contract.
- ``sendto`` is the only supported target-bound outbound syscall form; a
  bound-peer ``send``/``sendmsg``/``sendmmsg``/``write``/``writev`` record
  is a rejection, never a silent exclusion.
- Payload identity is BYTE IDENTITY, never a length window: a target-bound
  record whose decoded bytes are non-abbreviated must contain the exact
  payload as the SUFFIX of its framed body; abbreviated records (ellipsis
  marker / decoded prefix shorter than declared) are REJECTED as payload
  identity evidence for every arm.  For the cold arm exactly one such exact
  payload-bearing record must exist; zero elsewhere.  Any target-bound
  record larger than every frozen payload (plus frame allowance) that does
  not carry an exact payload is rejected as unexplained payload-class
  traffic.  A same-length record carrying different bytes is rejected (it
  can never match the payload suffix), and duplicate payload records are
  rejected.
- Zero claims are derived from total target-bound bytes: an arm claims zero
  immutable bytes only when its total target-bound byte count is strictly
  below the smallest frozen payload length — fragmentation cannot hide a
  payload — AND no abbreviated target-bound record exists whose declared
  length lies in any frozen payload's frame window (an abbreviated
  payload-class record is never countable evidence, it is a rejection).
- ``-xx`` hex-escapes sockaddr bytes and payloads; both are unescaped
  mechanically.  ``<unfinished ...>``/``<... resumed>`` splits are merged.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from issue74_methodology import canonical_json_bytes

CAPTURE_TOOL = "strace phase5-process-wide-byte-complete/4"
SYSCALL_CLASSES = "network,write,writev,execve"
# Generous bound on the pinned client's SET_TENSOR framing overhead
# (| cmd(1) | size(8) | rpc_tensor | offset(8) |; observed 304 bytes on the
# physical Qwen run).  The -s limit is derived as max payload + allowance.
FRAME_ALLOWANCE = 4096
SUPPORTED_OUTBOUND = "sendto"
OTHER_OUTBOUND = {"send", "sendmsg", "sendmmsg", "write", "writev"}
PID_LINE = re.compile(r"^(?P<pid>\d+)\s+\S+\s+(?P<record>.*)$")
CALL = re.compile(r"^(?P<name>[a-z][a-z0-9_]*)\(")
FD = re.compile(r"^[a-z][a-z0-9_]*\((?P<fd>\d+)(?:,|\))")
RESULT = re.compile(r"\)\s+=\s+(?P<result>-?\d+)\s*$")
PORT = re.compile(r"sin_port=htons\((?P<port>\d+)\)")
HOST = re.compile(r'inet_addr\("(?P<host>(?:[^"\\]|\\.)*)"')
HEX_ESCAPE = re.compile(r"\\x([0-9a-fA-F]{2})")
STRING = r'"(?:[^"\\]|\\.)*"'
SENDTO = re.compile(r"^sendto\((?P<fd>\d+), (?P<data>" + STRING
                    + r")(?P<ellipsis>\.\.\.)?, (?P<length>\d+), [^,]+, (?P<rest>.*)\)"
                    r"\s+=\s+(?P<result>-?\d+)$")
UNFINISHED = re.compile(r"(?P<body>.*)<unfinished \.\.\.>\s*$")
RESUMED = re.compile(r"^(?P<pid>\d+)\s+\S+\s+<\.\.\.\s+(?P<name>[a-z][a-z0-9_]*) resumed>(?P<rest>.*)$")


def required_string_limit(payload_lengths: list[int]) -> int:
    """The -s limit that retains the complete largest frozen framed payload.

    Mechanically derived from the frozen payload sizes plus a bounded frame
    allowance — never a hand-tuned constant.
    """
    if not payload_lengths or any(not isinstance(n, int) or n <= 0 for n in payload_lengths):
        raise ValueError("payload lengths must be positive integers")
    return max(payload_lengths) + FRAME_ALLOWANCE


def required_capture_command(client_argv: list[str], payload_lengths: list[int]) -> list[str]:
    """The only capture argv eligible for a Phase-5 claim.

    ``client_argv`` is the frozen client command the strace child-execs; the
    capture must start at that exec, never at an attach.
    """
    if (not isinstance(client_argv, list) or not client_argv
            or not all(isinstance(item, str) and item for item in client_argv)):
        raise ValueError("capture contract requires the frozen client argv")
    return ["strace", "-f", "--always-show-pid", "-ttt", "-xx",
            "-s", str(required_string_limit(payload_lengths)),
            "-e", f"trace={SYSCALL_CLASSES}", *client_argv]


def validate_capture_contract(command: Any, client_argv: list[str], payload_lengths: list[int]) -> None:
    if command != required_capture_command(client_argv, payload_lengths):
        raise ValueError("capture command does not equal the Phase-5 byte-complete from-exec contract")


def reducer_sha256() -> str:
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def _unescape(text: str) -> str:
    def replace(match: re.Match) -> str:
        return chr(int(match.group(1), 16))
    return HEX_ESCAPE.sub(replace, text.replace('\\"', '"').replace("\\\\", "\\"))


def _endpoint(record: str) -> tuple[str, int] | None:
    host, port = HOST.search(record), PORT.search(record)
    if host is None or port is None:
        return None
    return _unescape(host["host"]), int(port["port"])


def _fd(record: str) -> int | None:
    match = FD.match(record)
    return int(match["fd"]) if match else None


def _complete_data(text: str) -> bytes:
    """Decode a strace -xx string literal (WITH its surrounding quotes)
    into bytes (latin1-preserving)."""
    if len(text) < 2 or text[0] != '"' or text[-1] != '"':
        raise ValueError("strace outbound data string is not a quoted literal")
    return _unescape(text[1:-1]).encode("latin1")


def _merge_unfinished(lines: list[str]) -> list[str]:
    pending: dict[str, str] = {}
    merged: list[str] = []
    for line in lines:
        unfinished = UNFINISHED.search(line)
        if unfinished:
            prefixed = PID_LINE.match(line)
            if prefixed is None:
                if any(token in line for token in (*OTHER_OUTBOUND, SUPPORTED_OUTBOUND, "connect")):
                    raise ValueError("captured network record lacks required PID/TID prefix")
                continue
            pending[prefixed["pid"]] = unfinished["body"].rstrip()
            continue
        resumed = RESUMED.match(line)
        if resumed:
            body = pending.pop(resumed["pid"], None)
            if body is not None:
                merged.append(f"{resumed['pid']} x {body}{resumed['rest'].lstrip()}")
            else:
                merged.append(line)
            continue
        merged.append(line)
    for text in pending.values():
        if any(token in text for token in (*OTHER_OUTBOUND, SUPPORTED_OUTBOUND, "connect")):
            raise ValueError("tracee syscall record is truncated by the end of the capture")
    return merged


def reduce_capture(raw: bytes, *, client_pid: int, server_endpoint: str,
                   payloads: list[dict[str, Any]],
                   client_argv: list[str] | None = None) -> dict[str, Any]:
    """Derive byte-exact accounting from every PID-prefixed tracee record
    bound to the participant endpoint.

    ``client_argv`` (the frozen client command) enables the from-exec start
    gate: the first tracee record must be the client's own execve.
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
    lines = _merge_unfinished(lines)

    sends: list[tuple[int, bytes | None]] = []  # (declared length, complete bytes or None)
    fd_peers: dict[int, tuple[str, int]] = {}
    tracee_pids: set[int] = set()
    first_record_seen = False
    for line in lines:
        prefixed = PID_LINE.match(line)
        if prefixed is None:
            if any(token in line for token in (*OTHER_OUTBOUND, SUPPORTED_OUTBOUND, "connect")):
                raise ValueError("captured network record lacks required PID/TID prefix")
            continue
        tracee_pids.add(int(prefixed["pid"]))
        record = prefixed["record"]
        if not first_record_seen:
            # The capture must begin at the client's own exec: strace was the
            # parent, so the very first tracee syscall is the client execve
            # of the frozen argv.  An attached capture (-p) begins later and
            # can never produce this.
            name_match = CALL.match(record)
            if name_match is None or name_match["name"] != "execve":
                raise ValueError("capture does not begin at the client execve (from-exec start gate)")
            if int(prefixed["pid"]) != client_pid:
                raise ValueError("first tracee record is not the bound client PID")
            if client_argv is not None:
                observed = _unescape(record.split('"', 2)[1]).encode("latin1") if '"' in record else b""
                if observed.decode("latin1", "replace") != client_argv[0]:
                    raise ValueError("client execve binary does not match the frozen client argv")
            first_record_seen = True
            continue
        name_match = CALL.match(record)
        if name_match is None:
            if any(token in record for token in (*OTHER_OUTBOUND, "sendto")):
                raise ValueError("tracee outbound strace record is incomplete or unparseable")
            continue
        name, fd = name_match["name"], _fd(record)
        if name == "execve":
            continue  # later execs (thread helpers) are legal descendants
        if name == "connect":
            result, endpoint = RESULT.search(record), _endpoint(record)
            if fd is not None and result and int(result["result"]) == 0 and endpoint is not None:
                fd_peers[fd] = endpoint
            continue
        if name in OTHER_OUTBOUND:
            if fd is not None and fd_peers.get(fd) == target:
                raise ValueError(f"unsupported outbound {name} record in Phase-5 capture")
            continue
        if name != SUPPORTED_OUTBOUND:
            continue
        endpoint = _endpoint(record)
        connected_target = fd is not None and fd_peers.get(fd) == target
        if endpoint == target and not connected_target:
            raise ValueError("target sendto lacks preceding successful target connect provenance")
        if endpoint is None and not connected_target:
            raise ValueError("sendto peer cannot be mechanically bound to the retained endpoint")
        if endpoint is not None and endpoint != target:
            continue
        match, result = SENDTO.match(record), RESULT.search(record)
        if match is None or result is None:
            raise ValueError("relevant sendto record is unparseable")
        data = _complete_data(match["data"])
        declared, returned = int(match["length"]), int(result["result"])
        if len(data) > declared:
            raise ValueError("sendto data string is longer than its declared length")
        if len(data) < declared or match["ellipsis"]:
            # Abbreviated records are NEVER admissible in a byte-complete
            # capture: the -s contract derived from the frozen payloads
            # guarantees complete strings for payload-class records.
            raise ValueError("abbreviated target-bound sendto record in byte-complete capture")
        if returned != declared:
            raise ValueError("strace send length/result does not bind complete record bytes")
        sends.append((declared, data))
    if not first_record_seen:
        raise ValueError("capture contains no client execve start record")
    if not sends:
        raise ValueError("raw capture has no tracee-to-server sends for bound PID/endpoint")

    lengths = [length for length, _ in sends]
    total = sum(lengths)
    largest_payload = max(int(p["length"]) for p in payloads)
    smallest_payload = min(int(p["length"]) for p in payloads)
    immutable, matched = 0, []
    exact_ids: set[tuple] = set()
    for payload in payloads:
        data = payload.get("bytes")
        length = int(payload["length"])
        if data is not None and (len(data) != length
                                 or hashlib.sha256(data).hexdigest() != payload["sha256"]):
            raise ValueError("payload bytes do not bind observation identity")
        # BYTE identity: the exact payload bytes as the SUFFIX of one
        # complete target-bound record.  A length window is never identity.
        exact = [i for i, (rec_len, rec) in enumerate(sends)
                 if rec is not None and data is not None
                 and rec_len >= length and rec.endswith(data)]
        if len(exact) > 1:
            raise ValueError("payload transfer is duplicated")
        window = [i for i, (rec_len, _) in enumerate(sends)
                  if length <= rec_len <= length + FRAME_ALLOWANCE]
        if exact and set(window) - set(exact):
            raise ValueError("another payload-class record shares this payload's frame window")
        if exact:
            immutable += length
            matched.append({key: payload[key] for key in
                            ("participant", "observation_id", "order", "offset", "length", "sha256")})
            exact_ids.add((payload["observation_id"], payload["sha256"]))
        elif window:
            # An abbreviated/reshaped record in the payload window without
            # byte identity is unexplained payload-class traffic.
            raise ValueError("payload-class target record does not carry the exact frozen payload bytes")
        elif total >= smallest_payload:
            raise ValueError("payload-sized target traffic is not attributable to the frozen payload boundary")
    for index, (rec_len, rec) in enumerate(sends):
        if rec_len > largest_payload + FRAME_ALLOWANCE:
            raise ValueError("unexplained payload-class target record exceeds every frozen payload")
    return {"schema": "inferswarm.issue200.network-reduction/4",
            "reducer_sha256": reducer_sha256(), "client_to_server_bytes": total,
            "immutable_payload_bytes": immutable, "protocol_control_hash_probe_bytes": total - immutable,
            "traced_pids": sorted(tracee_pids),
            "payload_identities": sorted(matched, key=lambda item: item["order"])}


def canonical_reduce(*args: Any, **kwargs: Any) -> bytes:
    return canonical_json_bytes(reduce_capture(*args, **kwargs))
