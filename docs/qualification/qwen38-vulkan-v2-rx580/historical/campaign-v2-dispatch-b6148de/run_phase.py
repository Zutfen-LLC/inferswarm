"""Issue #241 R8-I3 physical campaign runner (dispatch b6148de, comment 5806929798).

Fresh cascade at the corrected head after correction pass 8 (Phase-3
identity seam). Runs the frozen, dispatch-gated producers from the exact
head b6148de7897de49e961ceca2f3cc0ee2f59dc4b2. GitHub dispatch
validation flows through the authenticated GET-only proxy on the hermes
host (10.0.0.31:18443) because the anonymous 60/hr API limit cannot
cover the ~180 live revalidations this campaign performs; the proxy
forwards only the three exact read-only API paths the frozen verifier
reads. Identical transport to the accepted 286dc63 campaign.

Production runner note (unchanged from the 286dc63 campaign): the
frozen SubprocessRunner default timeout of 120 s predates this host's
measured single-core SHA-256 throughput (E5-2683 v3, no SHA-NI:
~250 MiB/s => the 50 GiB model member needs ~200 s). run_phase1's
documented runner injection seam is used with a subclass that extends
the timeout ONLY for sha256sum commands on the frozen model members;
command bytes, captured output, return codes and recorded evidence are
identical to the default runner.
"""
import json
import os
import sys
from pathlib import Path

# Proxy transport for dispatch validation ONLY (https; local llama-server
# HTTP on 127.0.0.1 is excluded via no_proxy and has no http_proxy set).
os.environ["https_proxy"] = "http://10.0.0.31:18443"
os.environ["HTTPS_PROXY"] = "http://10.0.0.31:18443"
os.environ["no_proxy"] = "127.0.0.1,localhost"
os.environ["NO_PROXY"] = "127.0.0.1,localhost"
os.environ["SSL_CERT_FILE"] = "/home/hermes/is241-campaign-v2/mitmproxy-ca-cert.pem"

REPO = Path("/home/hermes/is241-repo")
EVIDENCE = Path("/home/hermes/is241-campaign-v2")
LLAMA_PIN = Path("/home/hermes/is241-llama-pin")
CANONICAL_SERVER = Path(
    "/home/hermes/llama.cpp/r8h-matched/build-r8h-vk/bin/llama-server")

sys.path.insert(0, str(REPO / "scripts"))
import issue241_host_producer as host  # noqa: E402
import issue241_physical as phys  # noqa: E402

MODEL_DIR_PREFIX = "/srv/models/qwen38-ud-iq1-s/"


class ModelHashRunner(host.SubprocessRunner):
    """Same subprocess semantics; longer bound for the big model hashes."""

    def run(self, command, *, cwd=None, timeout=120):
        if (command and command[0] == "sha256sum"
                and any(str(a).startswith(MODEL_DIR_PREFIX)
                        for a in command[1:])):
            timeout = max(timeout, 1800)
        return super().run(command, cwd=cwd, timeout=timeout)


def main() -> int:
    phase = sys.argv[1]
    if phase == "phase1":
        receipt = phys.run_phase1(REPO, evidence_root=EVIDENCE,
                                  runner=ModelHashRunner())
        summary = {"phase": 1, "head": receipt["dispatch_head_sha"],
                   "verdict": receipt["census"]["verdict"]}
    elif phase == "phase2":
        receipt = phys.run_phase2(REPO, evidence_root=EVIDENCE,
                                  source_tree=LLAMA_PIN,
                                  build_runner=ModelHashRunner())
        summary = {"phase": 2, "head": receipt["dispatch_head_sha"],
                   "selected": receipt["selected"]}
    elif phase == "phase3":
        build = json.loads((EVIDENCE / "phase2" / "build-receipt.json")
                           .read_bytes())
        server = Path(build["binary"]["path"])
        selected = EVIDENCE / "phase2" / "phase2-placement-receipt.json"
        receipt = phys.run_phase3(REPO, evidence_root=EVIDENCE,
                                  selected_path=selected, server=server,
                                  canonical_server=CANONICAL_SERVER)
        summary = {"phase": 3, "head": receipt["dispatch_head_sha"],
                   "matched_ngl": receipt["matched_ngl"],
                   "measurements": receipt.get("measurements")}
    elif phase == "phase4":
        # CPU-only reducer; consumes retained receipts only.
        os.environ.pop("https_proxy", None)
        os.environ.pop("HTTPS_PROXY", None)
        sys.path.insert(0, str(EVIDENCE))
        import decision_inputs_v2
        return decision_inputs_v2.main()
    else:
        print(f"unknown phase {phase}", file=sys.stderr)
        return 2
    print("PHASE-RESULT " + json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
