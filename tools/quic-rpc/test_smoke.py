"""Pure command/result tests. Never opens sockets, launches peers or reads credentials."""
import unittest
import json
import smoke


def config():
    return {"benchmark": "/test/benchmark", "peer": "/test/smoke_peer", "openssl": "/test/openssl",
            "ca": "/test/ca.pem", "server": {"dns": "server.test", "cert": "/test/server.pem", "key": "/test/server.key"},
            "client": {"dns": "client.test", "cert": "/test/client.pem", "key": "/test/client.key"}}


class SmokeTest(unittest.TestCase):
    @staticmethod
    def auth(role, kind=None):
        result = [json.dumps({"event": "handshake_attempt", "role": role})]
        if kind:
            result.append(json.dumps({"event": "peer_verification_rejected", "role": role, "kind": kind}))
        return "\n".join(result)

    def test_missing_client_has_no_certificate_arguments(self):
        for transport in ("tcp", "quic"):
            c = smoke.peer_command(config(), transport, "127.0.0.1:12345", "missing-client-cert")
            for forbidden in ("-cert", "-key", "/test/client.pem", "/test/client.key"):
                self.assertNotIn(forbidden, c)
        self.assertIn("-verify_return_error", smoke.peer_command(config(), "tcp", "127.0.0.1:12345", "missing-client-cert"))
        self.assertIn("no-client-cert", smoke.peer_command(config(), "quic", "127.0.0.1:12345", "missing-client-cert"))

    def test_wrong_san_changes_only_verifying_role(self):
        for case, role in (("wrong-server-san", "client"), ("wrong-client-san", "server")):
            c = smoke.command(config(), role, "tcp", "127.0.0.1:12345", case)
            self.assertEqual(c[9], "wrong-peer.invalid")
            other = "client" if role == "server" else "server"
            self.assertNotIn("wrong-peer.invalid", smoke.command(config(), other, "quic", "127.0.0.1:12345", case))

    def test_cli_refusal_not_missing_certificate_proof(self):
        ok, _ = smoke.evaluate("missing-client-cert", "tcp", 1, 1, "", "handshake rejected", "", "missing file")
        self.assertFalse(ok)
        ok, _ = smoke.evaluate("missing-client-cert", "tcp", 1, 1, "", self.auth("server", "missing_certificate"), "", "alert certificate required")
        self.assertTrue(ok)

    def test_actual_certificate_free_quic_rejection(self):
        attempt = '{"event":"handshake_attempt","certificate_configured":false}'
        rejected = self.auth("server", "missing_certificate")
        ok, _ = smoke.evaluate("missing-client-cert", "quic", 1, 1, "", rejected, attempt, "connection lost")
        self.assertTrue(ok)
        ready = attempt + '\n{"event":"authenticated_ready","certificate_configured":false}'
        ok, _ = smoke.evaluate("missing-client-cert", "quic", 1, 1, "", rejected, ready, "")
        self.assertFalse(ok)

    def test_truncation_requires_authenticated_ready(self):
        ok, _ = smoke.evaluate("payload-cut", "tcp", 1, 0, "", "payload short/deadline", "", "")
        self.assertFalse(ok)
        ready = '{"event":"authenticated_ready"}'
        ok, _ = smoke.evaluate("payload-cut", "tcp", 1, 0, "", ready+'\npayload short/deadline', ready, "")
        self.assertTrue(ok)

    def test_regression_setup_certificate_error_is_not_handshake_rejection(self):
        server = 'listener ready\ndeadline has elapsed'
        client = 'empty certificates'
        # The removed classifier matched only these generic error words.
        self.assertTrue(any(word in (server + client).lower()
                            for word in ("handshake", "certificate", "san", "invalid peer")))
        ok, _ = smoke.evaluate("wrong-server-san", "quic", 1, 1, "", server, "", client)
        self.assertFalse(ok)

    def test_authentication_rejection_must_belong_to_verifying_endpoint(self):
        # Both peers attempted TLS, but a server-side rejection does not prove
        # the client's expected-server-SAN check rejected the server.
        ok, _ = smoke.evaluate("wrong-server-san", "quic", 1, 1, "", self.auth("server", "invalid_certificate"),
                               "", self.auth("client"))
        self.assertFalse(ok)
        ok, _ = smoke.evaluate("wrong-server-san", "quic", 1, 1, "", self.auth("server"),
                               "", self.auth("client", "exact_san"))
        self.assertTrue(ok)

    def test_regression_sleeping_helper_cannot_supply_server_timeout_duration(self):
        ready = json.dumps({"event": "authenticated_ready", "role": "server", "mono_ns": 2_000_000_000})
        # Server dies immediately, while the fault helper lives for 11.5 seconds.
        overall_seconds = 11.5
        self.assertGreaterEqual(overall_seconds, 9.5)  # removed pair-wall predicate falsely passed
        timing = {"server_exit_ns": 2_020_000_000, "client_exit_ns": 13_500_000_000}
        ok, _ = smoke.evaluate("stall-frame", "tcp", 1, 0, "", ready+'\nTCP header short/deadline',
                               ready, "", timing=timing)
        self.assertFalse(ok)
        # Even a contradictory timeout event cannot override an independently early exit.
        expired = json.dumps({"event": "stage_timeout", "role": "server", "stage": "frame_read", "mono_ns": 12_000_000_000})
        self.assertFalse(smoke.timeout_evidence("stall-frame", smoke.events(ready+'\n'+expired), timing))
        timing["server_exit_ns"] = 12_010_000_000
        ok, _ = smoke.evaluate("stall-frame", "tcp", 1, 0, "", ready+'\n'+expired,
                               ready, "", timing=timing)
        self.assertTrue(ok)

    def test_timeout_requires_correct_stage_and_anchor(self):
        attempt = json.dumps({"event": "handshake_attempt", "role": "server", "mono_ns": 1_000_000_000})
        wrong_stage = json.dumps({"event": "stage_timeout", "role": "server", "stage": "frame_read", "mono_ns": 11_000_000_000})
        timing = {"server_exit_ns": 11_010_000_000}
        self.assertFalse(smoke.timeout_evidence("stall-handshake-tcp", smoke.events(attempt+'\n'+wrong_stage), timing))
        right_stage = wrong_stage.replace('frame_read', 'handshake')
        self.assertTrue(smoke.timeout_evidence("stall-handshake-tcp", smoke.events(attempt+'\n'+right_stage), timing))

    def test_exit_monitor_observes_early_server_while_helper_keeps_running(self):
        class Clock:
            now = 0.0
            def pause(self, seconds):
                self.now += seconds
        clock = Clock()
        class Process:
            def __init__(self, end):
                self.end = end
            def poll(self):
                return 1 if clock.now >= self.end else None
        observations = smoke.observe_exits(Process(0.02), Process(11.5), 40,
                                           clock=lambda: clock.now, clock_ns=lambda: int(clock.now*1e9),
                                           pause=clock.pause)
        self.assertLess(observations["server"], 100_000_000)
        self.assertGreaterEqual(observations["client"], 11_500_000_000)


if __name__ == "__main__":
    unittest.main()
