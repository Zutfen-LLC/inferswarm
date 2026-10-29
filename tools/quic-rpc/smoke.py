#!/usr/bin/env python3
"""Finite loopback-only interoperability runner. Reads supplied credentials; issues none.

Execution requires the parent's separately approved local-smoke dispatch. Do not run
on an active benchmark host merely because this file exists. Logs remain private.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time

BASE = ("positive", "wrong-server-san", "wrong-client-san", "missing-client-cert",
        "header-cut", "payload-cut", "disconnect", "stall-frame")
KINDS = ("untrusted", "expired", "wrong-eku", "incomplete-chain")


def events(text):
    result = []
    for line in text.splitlines():
        try:
            value = json.loads(line)
            if isinstance(value, dict):
                result.append(value)
        except json.JSONDecodeError:
            pass
    return result


def command(config, role, transport, address, case):
    identity = dict(config[role])
    override = config.get("negative", {}).get(case)
    if override and override["role"] == role:
        identity.update({k: override[k] for k in ("cert", "key")})
    expected = config["client" if role == "server" else "server"]["dns"]
    if case == "wrong-server-san" and role == "client":
        expected = "wrong-peer.invalid"
    if case == "wrong-client-san" and role == "server":
        expected = "wrong-peer.invalid"
    return [config["benchmark"], role, transport, address,
            address if role == "server" else "127.0.0.1:0", "127.0.0.1",
            config["ca"], identity["cert"], identity["key"], expected,
            "1", "5", "1", "0", "0", "1"]


def peer_command(config, transport, address, case):
    if case == "missing-client-cert":
        if transport == "tcp":
            # Intentionally no -cert, -key or -pass arguments. This reaches a real TLS handshake.
            return [config["openssl"], "s_client", "-connect", address,
                    "-CAfile", config["ca"], "-verify_hostname", config["server"]["dns"],
                    "-verify_return_error", "-tls1_3", "-no_ticket", "-quiet"]
        return [config["peer"], "quic", address, config["ca"],
                config["server"]["dns"], "no-client-cert"]
    mode = "stall-handshake" if case == "stall-handshake-tcp" else case
    return [config["peer"], transport, address, config["ca"], config["server"]["dns"],
            mode, config["client"]["cert"], config["client"]["key"]]


def validate(config):
    for name in ("benchmark", "peer", "openssl", "ca"):
        if not Path(config[name]).is_absolute() or not Path(config[name]).is_file():
            raise ValueError(f"{name}: require existing absolute file path")
    cases = config["cases"]
    if not cases or len(cases) > 24 or len(cases) != len(set(cases)):
        raise ValueError("select 1..24 unique cases")
    for role in ("server", "client"):
        for name in ("cert", "key"):
            if not Path(config[role][name]).is_absolute() or not Path(config[role][name]).is_file():
                raise ValueError(f"missing supplied {role} {name}")
        name = config[role]["dns"]
        if not name or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-" for c in name):
            raise ValueError("require explicit SAN DNS name")
    for case in cases:
        if case in BASE or case == "stall-handshake-tcp":
            continue
        n = config.get("negative", {}).get(case)
        if not n or n.get("role") not in ("client", "server") or n.get("kind") not in KINDS:
            raise ValueError(f"{case}: missing approved negative fixture declaration")
        for name in ("cert", "key"):
            if not Path(n[name]).is_absolute() or not Path(n[name]).is_file():
                raise ValueError(f"{case}: missing supplied {name}")
    # Positive controls must precede negatives on each transport, so a generic setup error
    # cannot be relabeled as a passing authentication rejection.
    if cases[0] != "positive":
        raise ValueError("first case must be positive")


def preflight(config):
    # Validate only the positive identities, with role purpose and current clock unchanged.
    # Negative fixture provenance is supplied by the parent's manifest, not manufactured here.
    receipts = {}
    for role, purpose in (("server", "sslserver"), ("client", "sslclient")):
        item = config[role]
        args = [config["openssl"], "verify", "-CAfile", config["ca"], "-purpose", purpose,
                "-verify_hostname", item["dns"]]
        if item.get("intermediates"):
            args += ["-untrusted", item["intermediates"]]
        result = subprocess.run(args + [item["cert"]], capture_output=True, timeout=5)
        if result.returncode:
            raise ValueError(f"positive {role} certificate verification failed: {result.stderr.decode(errors='replace')}")
        pub = subprocess.run([config["openssl"], "x509", "-in", item["cert"], "-pubkey", "-noout"],
                             capture_output=True, check=True, timeout=5).stdout
        cert_pub = subprocess.run([config["openssl"], "pkey", "-pubin", "-outform", "DER"],
                                  input=pub, capture_output=True, check=True, timeout=5).stdout
        key_pub = subprocess.run([config["openssl"], "pkey", "-in", item["key"], "-pubout", "-outform", "DER"],
                                 stdin=subprocess.DEVNULL, capture_output=True, check=True, timeout=5).stdout
        if cert_pub != key_pub:
            raise ValueError(f"{role} certificate/private-key public identities differ")
        receipts[role] = {"public_key_sha256": hashlib.sha256(cert_pub).hexdigest(), "verify": "PASS"}
    return receipts


def stop_owned(child):
    if child.poll() is None:
        os.killpg(child.pid, signal.SIGTERM)
        try:
            child.wait(timeout=2)
        except subprocess.TimeoutExpired:
            os.killpg(child.pid, signal.SIGKILL)
            child.wait(timeout=2)


def timeout_evidence(case, server_events, timing):
    stage_name = "handshake" if case == "stall-handshake-tcp" else "frame_read"
    anchor_event = "handshake_attempt" if stage_name == "handshake" else "authenticated_ready"
    anchor = next((e.get("mono_ns") for e in server_events
                   if e.get("event") == anchor_event and e.get("role") == "server"), None)
    expired = next((e.get("mono_ns") for e in server_events
                    if e.get("event") == "stage_timeout" and e.get("role") == "server"
                    and e.get("stage") == stage_name), None)
    exit_ns = (timing or {}).get("server_exit_ns")
    if not all(isinstance(v, int) for v in (anchor, expired, exit_ns)):
        return False
    # Same-host CLOCK_MONOTONIC, independently observed server exit. A sleeping
    # helper cannot supply time to either server interval.
    return 9.5e9 <= expired - anchor <= 20e9 and expired <= exit_ns and 9.5e9 <= exit_ns - anchor <= 20e9


def evaluate(case, transport, server_rc, client_rc, server_out, server_err, client_out, client_err,
             verifier=None, timing=None):
    se, ce = events(server_err), events(client_out + "\n" + client_err)
    ready_s = any(e.get("event") == "authenticated_ready" for e in se)
    ready_c = any(e.get("event") == "authenticated_ready" for e in ce)
    success_s = [e for e in events(server_out) if e.get("schema") == 1]
    success_c = [e for e in events(client_out) if e.get("schema") == 1]
    if case == "positive":
        for rc, out in ((server_rc, success_s), (client_rc, success_c)):
            if rc != 0 or len(out) != 1:
                return False, "positive process/receipt failure"
            r = out[0]
            if (r.get("completed"), r.get("errors"), r.get("integrity"), r.get("connections"),
                    r.get("chains"), r.get("warmup_chains")) != (52, 0, "all bytes exact", 1, 1, 0):
                return False, "positive count/integrity mismatch"
        return ready_s and ready_c, "positive full exchange and final close"
    if success_s or (case not in ("header-cut", "payload-cut", "disconnect", "stall-frame", "stall-handshake-tcp") and success_c):
        return False, "negative case produced a success receipt"
    if server_rc == 0 or server_rc == -signal.SIGKILL or client_rc == -signal.SIGKILL:
        return False, "negative peer not rejected or outer timeout"
    if case in ("header-cut", "payload-cut", "disconnect", "stall-frame"):
        if not ready_s or not ready_c or client_rc != 0:
            return False, "fault did not reach authenticated-ready or helper failed"
        if case == "header-cut" and "header short/deadline" not in server_err and transport == "tcp":
            return False, "not a TCP short-header failure"
        if case == "payload-cut" and "payload short/deadline" not in server_err and transport == "tcp":
            return False, "not a TCP short-payload failure"
        if case == "stall-frame" and not timeout_evidence(case, se, timing):
            return False, "missing intended server read/idle timeout stage and independent duration"
        return True, "authenticated injected stream fault caused bounded failure"
    if case == "stall-handshake-tcp":
        return (client_rc == 0 and not ready_s and '"event":"connected"' in client_out
                and timeout_evidence(case, se, timing)), "connected TCP peer stalled before TLS progress"
    if ready_s or client_rc == 0:
        return False, "negative authentication reached ready or client did not fail"
    if case == "missing-client-cert":
        attempted_s = any(e.get("event") == "handshake_attempt" and e.get("role") == "server" for e in se)
        rejected_s = any(e.get("event") == "peer_verification_rejected" and e.get("role") == "server"
                         and e.get("kind") == "missing_certificate" for e in se)
        if transport == "tcp":
            return attempted_s and rejected_s and "certificate required" in client_err.lower(), "real certificate-free OpenSSL client; require local server rejection and peer alert"
        attempted = any(e.get("event") == "handshake_attempt" and e.get("certificate_configured") is False for e in ce)
        return attempted_s and rejected_s and attempted and not ready_c, "real certificate-free Quinn client; require local server verification rejection"
    verifier = {"wrong-server-san": "client", "wrong-client-san": "server"}.get(case, verifier)
    if verifier not in ("client", "server"):
        return False, "missing expected verifying endpoint for supplied fixture"
    attempts = {role: any(e.get("event") == "handshake_attempt" and e.get("role") == role
                          for e in log) for role, log in (("server", se), ("client", ce))}
    verifying_events = se if verifier == "server" else ce
    rejected = any(e.get("event") == "peer_verification_rejected" and e.get("role") == verifier
                   and e.get("kind") in ("invalid_certificate", "exact_san") for e in verifying_events)
    return (not ready_c and all(attempts.values()) and rejected), "require real attempts and local rejection at expected verifier"


def observe_exits(server, client, deadline, clock=time.monotonic, clock_ns=time.monotonic_ns, pause=time.sleep):
    observed = {}
    while len(observed) != 2:
        for role, child in (("server", server), ("client", client)):
            if role not in observed and child.poll() is not None:
                observed[role] = clock_ns()
        if len(observed) == 2:
            break
        if clock() >= deadline:
            raise RuntimeError("pair/whole-smoke deadline; not a passing internal timeout")
        pause(0.01)
    return observed


def run_pair(config, root, transport, case, total_deadline):
    directory = root / f"{transport}-{case}"
    directory.mkdir(mode=0o700)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM if transport == "quic" else socket.SOCK_STREAM) as reserve:
        reserve.bind(("127.0.0.1", 0))
        address = f"127.0.0.1:{reserve.getsockname()[1]}"
    handles = []
    children = []
    processes = {}
    observed_exits = {}
    def launch(role, argv):
        out = open(directory / f"{role}.stdout", "w", encoding="utf-8")
        err = open(directory / f"{role}.stderr", "w", encoding="utf-8")
        handles.extend([out, err])
        child = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=out, stderr=err, start_new_session=True)
        children.append(child)
        processes[role] = {"pid": child.pid, "argv": argv}
        (directory / "processes.json").write_text(json.dumps(processes, indent=2) + "\n")
        return child
    started = time.monotonic()
    deadline = min(total_deadline, started + 40)
    try:
        server = launch("server", command(config, "server", transport, address, case))
        # Passive readiness only: no probe connections and no connect retries.
        while time.monotonic() < min(deadline, started + 5):
            if any(e.get("event") == "listening" for e in events((directory / "server.stderr").read_text())):
                break
            if server.poll() is not None:
                raise RuntimeError("server failed before listener readiness; not a passing negative handshake")
            time.sleep(0.02)
        else:
            raise RuntimeError("listener readiness deadline")
        fault = case in ("header-cut", "payload-cut", "disconnect", "stall-frame", "stall-handshake-tcp", "missing-client-cert")
        argv = peer_command(config, transport, address, case) if fault else command(config, "client", transport, address, case)
        client = launch("client", argv)
        # Poll both children independently; never let helper sleep inflate the
        # observed server lifetime. No extra connections or process retries.
        observed_exits = observe_exits(server, client, deadline)
    finally:
        for child in children:
            stop_owned(child)
        for f in handles:
            f.close()
    logs = [(directory / name).read_text() for name in ("server.stdout", "server.stderr", "client.stdout", "client.stderr")]
    fixture = config.get("negative", {}).get(case)
    verifier = ("client" if fixture["role"] == "server" else "server") if fixture else None
    timing = {"server_exit_ns": observed_exits["server"], "client_exit_ns": observed_exits["client"]}
    passed, reason = evaluate(case, transport, server.returncode, client.returncode, *logs, verifier=verifier, timing=timing)
    # Passive Linux socket inventory: TIME_WAIT is kernel cleanup, not a lingering listener.
    # Rebinding TCP would falsely fail when its old connection legitimately remains TIME_WAIT.
    port = int(address.rsplit(":", 1)[1])
    table = Path("/proc/net/udp" if transport == "quic" else "/proc/net/tcp").read_text()
    lingering = [line for line in table.splitlines()[1:]
                 if int(line.split()[1].rsplit(":", 1)[1], 16) == port
                 and (transport == "quic" or line.split()[3] == "0A")]
    if lingering:
        raise RuntimeError("owned pair exited but selected listener/UDP socket remains")
    record = {"case": case, "transport": transport, "pass": passed, "reason": reason,
              "server_pid": server.pid, "client_pid": client.pid, "server_exit": server.returncode,
              "client_exit": client.returncode, "elapsed_seconds": time.monotonic() - started,
              "exit_observations": timing,
              "owned_children_reaped": True, "no_listener_or_udp_socket": True}
    (directory / "receipt.json").write_text(json.dumps(record, indent=2) + "\n")
    if not passed:
        raise RuntimeError(f"STOP: {transport}/{case}: {reason}")
    return record


def main():
    def interrupted(signum, _frame):
        raise RuntimeError(f"STOP: received signal {signum}; cleaning owned children")
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--manifest", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--preflight-only", action="store_true")
    a = p.parse_args()
    config = json.loads(a.manifest.read_text())
    validate(config)
    identity = preflight(config)
    a.out.mkdir(mode=0o700, parents=True, exist_ok=False)
    summary = {"status": "PREFLIGHT_ONLY", "identity": identity,
               "binary_sha256": {k: hashlib.sha256(Path(config[k]).read_bytes()).hexdigest() for k in ("benchmark", "peer")},
               "cases": [], "pending": [f"{kind}-{role}" for kind in KINDS for role in ("server", "client")
                                         if not any(v["kind"] == kind and v["role"] == role and name in config["cases"]
                                                    for name, v in config.get("negative", {}).items())]
               + [name for name in BASE + ("stall-handshake-tcp",) if name not in config["cases"]]
               + ["QUIC stalled handshake", "forced blocked frame write (both transports)"]}
    try:
        if not a.preflight_only:
            deadline = time.monotonic() + 600
            for case in config["cases"]:
                for transport in (("tcp",) if case == "stall-handshake-tcp" else ("tcp", "quic")):
                    if time.monotonic() >= deadline:
                        raise RuntimeError("whole local smoke 600-second budget expired")
                    summary["cases"].append(run_pair(config, a.out, transport, case, deadline))
            summary["status"] = "SELECTED_CASES_PASS"
    except Exception as e:
        summary["status"] = "STOP"
        summary["error"] = str(e)
        raise
    finally:
        (a.out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
        print(json.dumps({"status": summary["status"], "completed_cases": len(summary["cases"]), "pending": summary["pending"]}))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"STOP: {exc}", file=sys.stderr)
        sys.exit(1)
