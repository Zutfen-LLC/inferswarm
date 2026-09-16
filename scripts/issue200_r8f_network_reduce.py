#!/usr/bin/env python3
"""Fail-closed reduction of the retained process-wide Phase-5 strace capture.

Phase-5 correction (see docs/implementation/r8-f-local-backing-source-policy-200
/README.md, "Phase 5").  The first physical Qwen execution under the exact
mandated argv discovered the actual capture boundary this reducer must honor:

- On the pinned fleet ``strace`` 6.13, the mandated ``-s 0`` string limit
  renders every nonempty send payload as a zero-byte quoted string followed
  by strace's ellipsis marker (``""...``).  A retained capture under the
  exact contract is therefore LENGTH-COMPLETE (declared length + syscall
  result for every record) but not byte-complete.  A record is admissible
  only when it is structurally self-consistent: the decoded prefix is
  shorter than the declared length, the ellipsis marker is present, and the
  syscall result equals the declared length.  Any truncated, partial
  (result < length), over-long, or unparseable relevant record still fails
  closed.
- The pinned RPC client (ggml-rpc.cpp send_rpc_cmd) frames every
  ``RPC_CMD_SET_TENSOR`` as three ``send()`` calls: a 1-byte command, an
  8-byte size, then ONE body record holding ``rpc_tensor | offset |
  payload``.  The immutable payload is the suffix of a framed record up to
  a bounded framing overhead (observed 304 bytes on the physical Qwen run)
  larger than the payload itself; bare-payload records do not occur.

Payload attribution therefore uses the strongest evidence the retained
bytes support, and says which rung it is on:

1. exact retained bytes, when a record's decoded string is complete and
   byte-equal to the verified payload;
2. otherwise the framed-length window: exactly one target-bound record
   whose length lies in ``(payload_length, payload_length +
   MAX_RPC_FRAME_OVERHEAD]``.

The zero-reacquisition derivation is fragmentation-proof: an immutable
payload can cross the wire only if the target-bound byte total reaches the
payload length, so an arm with no window-matching record is accepted as
zero ONLY when its total target-bound bytes are strictly below every
frozen payload length.  A payload fragmented into sub-window records can
never satisfy that bound.  Every other large record is rejected as an
unexplained payload-class transfer, duplicates are rejected, and the exact
process-wide rules of the previous revision are retained: PID/TID prefixes
are mandatory, a target ``sendto`` is accepted only after a retained
successful target ``connect()`` on its FD, and a bound-peer
``send``/``sendmsg``/``sendmmsg``/``write``/``writev`` is a rejection,
never a silent exclusion.
"""
from __future__ import annotations

import ast
import hashlib
import re
from pathlib import Path
from typing import Any

from issue74_methodology import canonical_json_bytes


# One exact argv contract, not an authored list that merely contains ``-xx``.
# ``-s 0`` is strace's zero-length string limit: on strace 6.13 it retains
# every record's declared length and result while abbreviating the payload
# string itself (see module docstring).  ``network`` catches send*;
# write/writev catch socket writes outside strace's network class.
CAPTURE_TOOL = "strace phase5-process-wide-length-accounting/3"
CAPTURE_PREFIX = ("strace", "-f", "--always-show-pid", "-ttt", "-xx", "-s", "0", "-e",
                  "trace=network,write,writev", "-p")
SUPPORTED_OUTBOUND = "sendto"
OTHER_OUTBOUND = {"send", "sendmsg", "sendmmsg", "write", "writev"}
# ggml-rpc.cpp frames SET_TENSOR as | cmd(1) | size(8) | rpc_tensor |
# offset(8) | payload |.  The observed physical overhead is 304 bytes; the
# acceptance window is bounded generously and independently of any single
# observation.
MAX_RPC_FRAME_OVERHEAD = 4096
PID_LINE = re.compile(r"^(?P<pid>\d+)\s+\S+\s+(?P<record>.*)$")
CALL = re.compile(r"^(?P<name>[a-z][a-z0-9_]*)\(")
FD = re.compile(r"^[a-z][a-z0-9_]*\((?P<fd>\d+)(?:,|\))")
RESULT = re.compile(r"\)\s+=\s+(?P<result>-?\d+)\s*$")
PORT = re.compile(r"sin_port=htons\((?P<port>\d+)\)")
# -xx renders the sockaddr host as fully hex-escaped string bytes.
HOST = re.compile(r'inet_addr\("(?P<host>(?:[^"\\]|\\.)*)"\)')
HEX_ESCAPE = re.compile(r"\\x([0-9a-fA-F]{2})")
STRING = r'"(?:[^"\\]|\\.)*"'
SENDTO = re.compile(r"^sendto\((?P<fd>\d+), (?P<data>" + STRING
                    + r")(?P<ellipsis>\.\.\.)?, (?P<length>\d+), [^,]+, (?P<rest>.*)\)"
                    r"\s+=\s+(?P<result>-?\d+)$")
UNFINISHED = re.compile(r"(?P<body>.*)<unfinished \.\.\.>\s*$")
RESUMED = re.compile(r"^(?P<pid>\d+)\s+\S+\s+<\.\.\.\s+(?P<name>[a-z][a-z0-9_]*) resumed>(?P<rest>.*)$")


def required_capture_command(client_pid: int) -> list[str]:
    """The only capture argv eligible for a Phase-5 claim."""
    if not isinstance(client_pid, int) or client_pid <= 0:
        raise ValueError("capture client PID must be a positive integer")
    return [*CAPTURE_PREFIX, str(client_pid)]


def validate_capture_contract(command: Any, client_pid: int) -> None:
    """Mechanically bind the exact argv, syscall coverage and PID."""
    if command != required_capture_command(client_pid):
        raise ValueError("capture command does not equal the Phase-5 full-payload/PID syscall contract")


def reducer_sha256() -> str:
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def _unescape(text: str) -> str:
    """Decode strace ``-xx`` string escapes (``\\xHH`` plus ``\\\\``/``\\"``)."""

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


def _merge_unfinished(lines: list[str]) -> list[str]:
    """Rejoin strace ``<unfinished ...>``/``<... resumed>`` record splits.

    A relevant record left split by the end of the capture fails closed in
    the caller; the merge itself never invents content, it only concatenates
    the two halves strace printed of one syscall.
    """
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
                   payloads: list[dict[str, Any]]) -> dict[str, Any]:
    """Derive byte accounting from every PID-prefixed tracee record for the
    bound peer.

    The caller has already mechanically checked the sole eligible argv.  Every
    PID-prefixed syscall in this retained stream is a root-client thread or a
    followed descendant; they are never filtered back to the root PID.  A
    target send is accepted only after a successful target ``connect`` on its
    FD has been retained.
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

    # (length, data-or-None) per accepted target-bound sendto record.
    sends: list[tuple[int, bytes | None]] = []
    fd_peers: dict[int, tuple[str, int]] = {}
    tracee_pids: set[int] = set()
    for line in lines:
        prefixed = PID_LINE.match(line)
        if prefixed is None:
            # Non-syscall strace notices (for example an exit marker) are not
            # evidence.  An unprefixed candidate outbound record, however,
            # would defeat --always-show-pid's tracee binding.
            if any(token in line for token in (*OTHER_OUTBOUND, SUPPORTED_OUTBOUND, "connect")):
                raise ValueError("captured network record lacks required PID/TID prefix")
            continue
        tracee_pids.add(int(prefixed["pid"]))
        record = prefixed["record"]
        name_match = CALL.match(record)
        if name_match is None:
            if any(token in record for token in (*OTHER_OUTBOUND, "sendto")):
                raise ValueError("tracee outbound strace record is incomplete or unparseable")
            continue
        name, fd = name_match["name"], _fd(record)
        if name == "connect":
            result, endpoint = RESULT.search(record), _endpoint(record)
            if fd is not None and result and int(result["result"]) == 0 and endpoint is not None:
                fd_peers[fd] = endpoint
            continue
        if name in OTHER_OUTBOUND:
            # A successful target connect is sufficient FD provenance.  Do
            # not require a socket() record: attachment can occur after
            # socket() but before connect(), and writes on that connected FD
            # are still target-bound traffic that a zero claim must reject.
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
            # NULL peer form is safe only when the retained successful
            # connect establishes this FD's target peer.  Otherwise we cannot
            # distinguish it from an unrelated connected socket.
            raise ValueError("sendto peer cannot be mechanically bound to the retained endpoint")
        if endpoint is not None and endpoint != target:
            # Explicitly a different target, so it cannot be Phase-5 RPC
            # traffic even if an FD number was reused in a followed process.
            continue
        match, result = SENDTO.match(record), RESULT.search(record)
        if match is None or result is None:
            raise ValueError("relevant sendto record is unparseable")
        data = _complete_data(match["data"])
        declared, returned = int(match["length"]), int(result["result"])
        if len(data) > declared:
            raise ValueError("sendto data string is longer than its declared length")
        if len(data) < declared and not match["ellipsis"]:
            # A truncated string without strace's ellipsis marker is a
            # structurally inconsistent record, never length-complete
            # evidence.
            raise ValueError("relevant sendto payload is truncated without abbreviation marker")
        if returned != declared:
            # The pinned transport loops until the full framed body is sent;
            # a partial syscall result means the frozen transfer is only
            # partly accounted in this record.
            raise ValueError("strace send length/result does not bind complete record bytes")
        sends.append((declared, data if len(data) == declared else None))
    if not sends:
        raise ValueError("raw capture has no tracee-to-server sends for bound PID/endpoint")

    lengths = [length for length, _ in sends]
    total = sum(lengths)
    immutable, matched = 0, []
    largest_payload = max((int(p["length"]) for p in payloads), default=0)
    for index, length in enumerate(lengths):
        if length > largest_payload + MAX_RPC_FRAME_OVERHEAD:
            raise ValueError("unexplained payload-class target record exceeds every frozen payload")
        _ = index
    for payload in payloads:
        data = payload.get("bytes")
        length = int(payload["length"])
        if data is not None and (len(data) != length
                                 or hashlib.sha256(data).hexdigest() != payload["sha256"]):
            raise ValueError("payload bytes do not bind observation identity")
        exact = [i for i, (rec_len, rec) in enumerate(sends)
                 if rec is not None and data is not None and rec == data]
        window = [i for i, (rec_len, rec) in enumerate(sends)
                  if length <= rec_len <= length + MAX_RPC_FRAME_OVERHEAD]
        if len(exact) > 1 or (exact and window and set(exact) != set(window)):
            raise ValueError("payload transfer is duplicated or only partly accounted")
        candidates = sorted(set(exact) | set(window))
        if len(candidates) > 1:
            raise ValueError("payload transfer is duplicated or only partly accounted")
        if candidates:
            immutable += length
            matched.append({key: payload[key] for key in
                            ("participant", "observation_id", "order", "offset", "length", "sha256")})
        elif total >= length:
            # The payload (or payload-sized traffic) crossed the wire in
            # records this reducer cannot attribute to the frozen boundary:
            # fragmented below the framing window, or reshaped.  Never a
            # zero claim.
            raise ValueError("payload-sized target traffic is not attributable to the frozen payload boundary")
    return {"schema": "inferswarm.issue200.network-reduction/3",
            "reducer_sha256": reducer_sha256(), "client_to_server_bytes": total,
            "immutable_payload_bytes": immutable, "protocol_control_hash_probe_bytes": total - immutable,
            "traced_pids": sorted(tracee_pids),
            "payload_identities": sorted(matched, key=lambda item: item["order"])}


def canonical_reduce(*args: Any, **kwargs: Any) -> bytes:
    return canonical_json_bytes(reduce_capture(*args, **kwargs))
