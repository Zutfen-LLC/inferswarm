"""Evidence-regeneration and static-discipline checks for issue #200 (R8-F).

Correction round 2 (schema /4): byte-complete from-exec capture, participant
full-release backing, derived cache freshness/staging/runtime attribution,
and the TRUE reuse arm."""
import ast
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import issue200_r8f_proof as proof
import issue200_r8f_rpc_cache_mechanism as cache_mechanism
import issue200_r8f_terminal_reduction as reduction
import issue200_r8f_physical as physical
import issue200_r8f_range_receipt as range_receipt
import issue200_r8f_network_reduce as network_reduce
import issue200_r8f_cache_enum as cache_enum
import issue200_r8f_stage_cache as stage_cache




def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def valid_cache_finding(**overrides):
    finding = {
        "schema": "inferswarm.issue200.rpc-cache-mechanical-finding/1",
        "pinned_llama_cpp_commit": cache_mechanism.PINNED_LLAMA_CPP_COMMIT,
        "measured": {"cold_set_phase_bytes_sent": 12583546, "warm_restart_set_phase_bytes_sent": 321,
                     "prestaged_set_phase_bytes_sent": 321, "wrong_content_get_exit_code": 2,
                     "truncated_get_exit_code": 2},
        "cold_exceeded_hash_threshold": True,
        "durable_cache_reuse_suppresses_retransmission": True,
        "prestaged_verified_backing_consumed_without_prior_network_pass": True,
        "upstream_cache_is_fail_open_on_wrong_or_truncated_content": True,
        "case_classification": "C",
        "case_classification_meaning": "existing cache can consume pre-staged backing with a bounded external adapter, no llama.cpp modification",
        "legal_non_runtime_modifying_seam_exists": True,
        "requires_external_provenance_verification_before_cache_population": True,
        "non_claim_fnv1a_is_not_inferswarm_trust_authority": "test",
        "boundary_condition_not_proven": "test",
    }
    finding.update(overrides)
    return finding


def _receipt(root, name, document):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(document, sort_keys=True).encode()
    path.write_bytes(payload)
    return {"path": name, "sha256": hashlib.sha256(payload).hexdigest()}


CLIENT_ARGV = ["/opt/llama-server", "-m", "/models/m1.gguf", "--rpc", "10.0.0.204:50052",
               "-ot", "t=RPC0[10.0.0.204:50052]", "--host", "127.0.0.1", "--port", "8341",
               "-ngl", "0", "-c", "8192", "--no-warmup"]
CLIENT_SHA = physical.accepted_client_binary_authority()


def synthetic_authority(root, payload_bytes=b"r8-f-observed-payload-" * 4):
    member_path = (root / "node-local" / "tiny-accepted-member.gguf").resolve()
    member_path.parent.mkdir(parents=True, exist_ok=True)
    member_path.write_bytes(b"tiny-prefix/" + payload_bytes + b"/tiny-suffix")
    return ({"authority_path": "synthetic/tiny-authority.json", "members": [{
        "file": member_path.name, "bytes": member_path.stat().st_size,
        "sha256": sha(member_path)}], "total_bytes": member_path.stat().st_size}, member_path)


def synthetic_backing_receipt(root, authority, node_id):
    return {
        "schema": "inferswarm.issue200.participant-full-release-receipt/1",
        "tool": {"path": "scripts/issue200_r8f_backing_verify.py",
                 "sha256": physical.backing_verify.helper_sha256()},
        "node_id": node_id, "backing_dir": "/srv/models/synthetic",
        "authority_path": f"/deployed{physical.AUTHORITY_PATH}",
        "members": [{**m, "expected_bytes": m["bytes"], "expected_sha256": m["sha256"],
                     "present": True, "actual_bytes": m["bytes"],
                     "actual_sha256": m["sha256"], "verified": True} for m in authority["members"]],
        "total_bytes": authority["total_bytes"], "all_members_verified": True}


def strace_escape(data: bytes) -> str:
    """Render bytes the way strace -xx renders them in a string literal."""
    return "".join((chr(b) if 32 <= b < 127 and chr(b) not in '"\\'
                    else f"\\x{b:02x}") for b in data)


def quote_arg(text: str) -> str:
    """Render one argv element as a complete strace -xx string literal."""
    return f'"{strace_escape(text.encode())}"'


def _empty_receipt(root, name):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"")
    return {"path": name, "sha256": hashlib.sha256(b"").hexdigest()}


def valid_physical_phase5_document(root, **overrides):
    authority, member_path = synthetic_authority(root)
    node_id = "inferswarm03"
    binary = physical.accepted_rpc_binary_authority()[node_id]
    payload_bytes = b"r8-f-observed-payload-" * 4
    payload_sha = hashlib.sha256(payload_bytes).hexdigest()
    payload_path = "raw/payload.bin"
    (root / "raw").mkdir(parents=True, exist_ok=True)
    (root / payload_path).write_bytes(payload_bytes)
    payload = {"offset": 0, "length": len(payload_bytes), "sha256": payload_sha,
               "fnv1a_cache_key": physical.fnv1a64(payload_bytes)}
    now = 1000.0
    backing = _receipt(root, "raw/backing.json", synthetic_backing_receipt(root, authority, node_id))

    def arm(name, policy, source, immutable_bytes):
        measured = range_receipt.measure_range(
            node_id=node_id, source_path=member_path, member=member_path.name,
            accepted_member_bytes=authority["members"][0]["bytes"],
            accepted_member_sha256=authority["members"][0]["sha256"],
            offset=len(b"tiny-prefix/"), length=len(payload_bytes),
            retained_range_path=root / f"raw/{name}.range.bin")
        stdout = _receipt(root, f"raw/{name}.range.stdout.json", measured)
        stderr_path = root / f"raw/{name}.range.stderr"
        stderr_path.write_bytes(b"")
        stderr = {"path": f"raw/{name}.range.stderr", "sha256": hashlib.sha256(b"").hexdigest()}
        range_bytes = {"path": f"raw/{name}.range.bin", "sha256": payload_sha}
        accepted_range = {"member": member_path.name, "offset": measured["offset"],
                          "length": len(payload_bytes), "sha256": payload_sha,
                          "provenance_receipt": {"command": ["python3", "scripts/issue200_r8f_range_receipt.py"],
                              "exit_code": 0, "stdout": stdout, "stderr": stderr, "retained_range": range_bytes}}
        # From-exec byte-complete capture: execve first, then connect, then
        # complete (non-abbreviated) target-bound records.
        framed = b"\x00" * 8 + payload_bytes  # small frame prefix + payload suffix
        exec_line = (f'999 1.000 execve("{strace_escape(CLIENT_ARGV[0].encode())}", '
                     f'[{", ".join(quote_arg(a) for a in CLIENT_ARGV)}], 0x1 /* 1 var */) = 0')
        records = [exec_line,
                   '999 1.000 socket(AF_INET, SOCK_STREAM, IPPROTO_TCP) = 3',
                   '999 1.000 connect(3, {sa_family=AF_INET, sin_port=htons(50052), '
                   'sin_addr=inet_addr("100.77.187.38")}, 16) = 0',
                   '999 1.001 sendto(3, "control", 7, 0, NULL, 0) = 7']
        if immutable_bytes:
            records.append(f'1001 1.002 sendto(3, "{strace_escape(framed)}", '
                           f'{len(framed)}, 0, NULL, 0) = {len(framed)}')
        raw_trace = ("\n".join(records) + "\n").encode()
        raw_capture = {"path": f"raw/{name}.strace", "sha256": hashlib.sha256(raw_trace).hexdigest()}
        (root / raw_capture["path"]).write_bytes(raw_trace)
        derived = network_reduce.reduce_capture(raw_trace, client_pid=999, server_endpoint="100.77.187.38:50052",
                                                payloads=[{**payload, "participant": node_id, "observation_id": "set-1", "order": 1,
                                                           "bytes": payload_bytes}], client_argv=CLIENT_ARGV)
        reduction_stdout = {"path": f"raw/{name}.network.reduced.json", "sha256": hashlib.sha256(physical.canonical_json_bytes(derived)).hexdigest()}
        (root / reduction_stdout["path"]).write_bytes(physical.canonical_json_bytes(derived))
        network = {"arm": name, "capture_tool": network_reduce.CAPTURE_TOOL,
                   "capture_command": network_reduce.required_capture_command(CLIENT_ARGV, [len(payload_bytes)]),
                   "client_argv": CLIENT_ARGV, "client_pid": 999, "server_endpoint": "100.77.187.38:50052",
                   "raw_capture": raw_capture, "reducer_sha256": network_reduce.reducer_sha256(),
                   "reduction_stdout": reduction_stdout}
        observed_payload = {**payload, "participant": node_id, "observation_id": "set-1", "order": 1}
        client_log = (root / f"raw/{name}.client.log")
        client_log.write_bytes(b"llama-server listening on http://127.0.0.1:8341\n")
        client_log_ref = {"path": f"raw/{name}.client.log", "sha256": sha(client_log)}
        bin_live = _receipt(root, f"raw/{name}.client-binary.json",
                            {"argv": ["sha256sum", CLIENT_ARGV[0]], "sha256": CLIENT_SHA})
        client_launch = _receipt(root, f"raw/{name}.client-launch.json", {
            "arm": name, "schema": "inferswarm.issue200.client-launch-receipt/1",
            "argv": CLIENT_ARGV, "pid": 999, "started_at": now, "exit_status": "terminated-after-listening",
            "binary_path": CLIENT_ARGV[0], "binary_sha256": CLIENT_SHA,
            "binary_live_receipt": {"path": bin_live["path"], "sha256": bin_live["sha256"]},
            "client_log": client_log_ref})
        server_log = root / f"raw/{name}.server.log"
        server_log.write_bytes(b"rpc server listening\n")
        rpc_bin_live = _receipt(root, f"raw/{name}.rpc-binary.json",
                                {"argv": ["sha256sum", "/opt/ggml-rpc-server"], "sha256": binary})
        cache_dir = f"/private/{name}"
        rpc_launch = _receipt(root, f"raw/{name}.rpc-launch.json", {
            "arm": name, "schema": "inferswarm.issue200.rpc-server-launch-receipt/1",
            "argv": ["ggml-rpc-server", "-H", "0.0.0.0", "-p", "50052", "-d", "CUDA0", "-c"],
            "env": {"LLAMA_CACHE": cache_dir}, "pid": 777, "started_at": now - 1,
            "binary_sha256": binary,
            "binary_live_receipt": {"path": rpc_bin_live["path"], "sha256": rpc_bin_live["sha256"]},
            "server_log": {"path": f"raw/{name}.server.log", "sha256": sha(server_log)}})
        read_cache_dir = cache_dir
        rpc_exec_path = physical.FROZEN_RPC_EXEC[0]
        rpc_exec_argv = [rpc_exec_path, *physical.FROZEN_RPC_EXEC[1]]
        rpc_exec_line = (f'777 1.000 execve("{strace_escape(rpc_exec_path.encode())}", '
                         f'[{", ".join(quote_arg(a) for a in rpc_exec_argv)}], 0x1 /* 1 var */) = 0')
        if name == "cold_remote":
            # cold arm: the server OPENS the cache file for WRITING (miss path)
            # and never reads it — the zero-read denial holds.
            read_strace_lines = [
                rpc_exec_line,
                f'777 2.000 openat(AT_FDCWD, "{read_cache_dir}/rpc/{payload["fnv1a_cache_key"]}", O_WRONLY|O_CREAT|O_TRUNC, 0666) = 5',
                f'777 2.001 write(5, "", {len(payload_bytes)}) = {len(payload_bytes)}',
            ]
        else:
            read_strace_lines = [
                rpc_exec_line,
                f'777 2.000 openat(AT_FDCWD, "{read_cache_dir}/rpc/{payload["fnv1a_cache_key"]}", O_RDONLY) = 5',
                f'777 2.001 read(5, "", {len(payload_bytes)}) = {len(payload_bytes)}',
            ]
        read_strace = ("\n".join(read_strace_lines) + "\n").encode()
        read_strace_ref = {"path": f"raw/{name}.reads.strace", "sha256": hashlib.sha256(read_strace).hexdigest()}
        (root / read_strace_ref["path"]).write_bytes(read_strace)
        read_receipt = _receipt(root, f"raw/{name}.reads.json", {
            "arm": name, "schema": "inferswarm.issue200.participant-cache-read-receipt/1",
            "server_pid": 777, "cache_dir": cache_dir,
            "strace_capture": read_strace_ref,
            "derived_read_bytes": len(payload_bytes) if name != "cold_remote" else 0,
            "read_syscalls": 1 if name != "cold_remote" else 0})
        result = {"source_policy": policy, "source_attribution": source,
                  "participants": [node_id], "required_state_identity": "sha256:state",
                  "participant_requirements_identity": "sha256:requirements",
                  "placement_identity": "sha256:placement", "materialization_identity": "sha256:materialization",
                  "initialization_wall_time_ms": 1.0, "network_receipt": network,
                  "client_launch_receipt": client_launch, "rpc_server_receipt": rpc_launch,
                  "participant_read_receipt": read_receipt,
                  "private_cache_dir": cache_dir,
                  "set_tensor_payloads": [observed_payload],
                  "accepted_artifact_ranges": [{"accepted_artifact_range": accepted_range,
                                                   "set_tensor_payload": observed_payload}]}
        fnv = payload["fnv1a_cache_key"]
        ENUM_TOOL = {"path": "scripts/issue200_r8f_cache_enum.py", "sha256": cache_enum.helper_sha256()}
        def enum_receipt(name_, entries_, measured_at_):
            return _receipt(root, f"raw/{name_}.cache-enum.json", {
                "schema": "inferswarm.issue200.cache-enumeration-receipt/2", "arm": name_,
                "tool": ENUM_TOOL,
                "node_id": node_id, "cache_dir": cache_dir, "measured_at": measured_at_,
                "command": [sys.executable, "/deployed/issue200_r8f_cache_enum.py", name_, cache_dir],
                "entries": entries_})
        if name == "cold_remote":
            result["cache_initialization_receipt"] = enum_receipt(name, [], now - 2)
        elif name == "local_verified":
            result["cache_initialization_receipt"] = enum_receipt(name, [], now - 2)
            after = _receipt(root, f"raw/{name}.cache-after.json", {
                "schema": "inferswarm.issue200.cache-enumeration-receipt/2", "arm": name,
                "tool": ENUM_TOOL,
                "node_id": node_id, "cache_dir": cache_dir, "measured_at": now - 1.5,
                "command": [sys.executable, "/deployed/issue200_r8f_cache_enum.py", name, cache_dir],
                "entries": [{"name": f"rpc/{fnv}", "size": len(payload_bytes), "sha256": payload_sha}]})
            staged_path = f"{cache_dir}/{fnv}"
            staging_measurement = {
                "arm": name, "schema": "inferswarm.issue200.cache-staging-measurement/1",
                "tool": {"path": "scripts/issue200_r8f_stage_cache.py", "sha256": stage_cache.helper_sha256()},
                "node_id": node_id, "source_path": str(member_path), "member": member_path.name,
                "accepted_member_bytes": authority["members"][0]["bytes"],
                "accepted_member_sha256": authority["members"][0]["sha256"],
                "offset": measured["offset"], "length": len(payload_bytes),
                "range_sha256": payload_sha, "fnv1a_cache_key": fnv,
                "cache_dir": cache_dir, "staged_path": staged_path,
                "tmp_path": f"{cache_dir}/.{fnv}.stage-tmp",
                "tmp_size": len(payload_bytes), "tmp_sha256": payload_sha,
                "final_size": len(payload_bytes), "final_sha256": payload_sha,
                "atomic_publish": "os.rename after fsync inside target directory"}
            staging_raw = _receipt(root, f"raw/{name}.staging.stdout", staging_measurement)
            staging_stderr = {"path": f"raw/{name}.staging.stderr", "sha256": hashlib.sha256(b"").hexdigest()}
            (root / staging_stderr["path"]).write_bytes(b"")
            result["cache_initialization_receipt"] = enum_receipt(name, [], now - 2)
            result["cache_after_staging_receipt"] = after
            result["cache_staging"] = [{
                "accepted_artifact_range": accepted_range,
                "set_tensor_payload": observed_payload,
                "staged_cache": {"path": staged_path,
                                 "raw_stdout": staging_raw,
                                 "raw_stderr": staging_stderr,
                                 "range_bytes": range_bytes}}]
        else:  # repeat: TRUE reuse of local_verified's cache
            reused_dir = "/private/local_verified"
            pre = _receipt(root, f"raw/{name}.cache-precheck.json", {
                "schema": "inferswarm.issue200.cache-enumeration-receipt/2", "arm": name,
                "tool": {"path": "scripts/issue200_r8f_cache_enum.py", "sha256": cache_enum.helper_sha256()},
                "node_id": node_id, "cache_dir": reused_dir, "measured_at": 0.5,
                "command": [sys.executable, "/deployed/issue200_r8f_cache_enum.py", name, reused_dir],
                "entries": [{"name": f"rpc/{fnv}", "size": len(payload_bytes), "sha256": payload_sha}]})
            result["private_cache_dir"] = reused_dir
            result["cache_precheck_receipt"] = pre
            # fix the read receipt + rpc launch to the reused dir
            rpc_doc = json.loads((root / rpc_launch["path"]).read_text())
            rpc_doc["env"] = {"LLAMA_CACHE": reused_dir}
            result["rpc_server_receipt"] = _receipt(root, rpc_launch["path"], rpc_doc)
            read_doc = json.loads((root / read_receipt["path"]).read_text())
            read_doc["cache_dir"] = reused_dir
            cap_path = root / read_doc["strace_capture"]["path"]
            cap = cap_path.read_bytes().replace(cache_dir.encode(), reused_dir.encode())
            cap_path.write_bytes(cap)
            read_doc["strace_capture"]["sha256"] = hashlib.sha256(cap).hexdigest()
            result["participant_read_receipt"] = _receipt(root, read_receipt["path"], read_doc)
        return result

    doc = {
        "schema": reduction.PHYSICAL_PHASE5_SCHEMA,
        "accepted_model_members": authority["members"], "accepted_total_bytes": authority["total_bytes"],
        "runtime": {"llama_cpp_commit": physical.PINNED_LLAMA_CPP_COMMIT,
                    "source_files": cache_mechanism.UPSTREAM_SOURCE_IDENTITY,
                    "binaries": [{"node_id": node_id, "binary": "ggml-rpc-server", "sha256": binary},
                                 {"node_id": "inferswarm01", "binary": "llama-server", "sha256": CLIENT_SHA}]},
        "participants": [{"node_id": node_id, "rpc_endpoint": "100.77.187.38:50052",
                          "rpc_command": "ggml-rpc-server -H 0.0.0.0 -p 50052 -c /private/cache"}],
        "frozen": {"required_state_identity": "sha256:state",
                   "participant_requirements_identity": "sha256:requirements",
                   "placement_identity": "sha256:placement", "materialization_identity": "sha256:materialization"},
        "frozen_client_argv": CLIENT_ARGV,
        "participant_backing_verification": {
            "node_id": node_id,
            "command": ["python3", "scripts/issue200_r8f_backing_verify.py", "--node-id", node_id],
            "exit_code": 0, "receipt": backing, "stderr": _empty_receipt(root, "raw/backing.stderr")},
        "arms": {
            "cold_remote": arm("cold_remote", "PREFER_REMOTE_AUTHORIZED", "REMOTE_AUTHORIZED", len(payload_bytes)),
            "local_verified": arm("local_verified", "REQUIRE_LOCAL_VERIFIED", "LOCAL_VERIFIED", 0),
            "repeat_local_verified": arm("repeat_local_verified", "REQUIRE_LOCAL_VERIFIED", "LOCAL_VERIFIED", 0),
        },
    }
    doc.update(overrides)
    return doc


class CommittedEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.evidence = ROOT / proof.AREA / "evidence"
        self.retained = {name: json.loads((self.evidence / name).read_text())
                         for name in proof.EVIDENCE_FILES}
        self.retained["terminal-reduction.json"] = json.loads(
            (self.evidence / "terminal-reduction.json").read_text())

    def test_all_evidence_documents_present(self):
        extra = {"terminal-reduction.json", "MANIFEST.sha256", "rpc-cache-mechanism.json",
                 "rpc-cache-experiment.json"}
        for name in proof.EVIDENCE_FILES | extra:
            self.assertTrue((self.evidence / name).is_file(), name)

    def test_manifest_covers_and_matches_every_retained_path(self):
        listed = {}
        for line in (self.evidence / "MANIFEST.sha256").read_text().splitlines():
            digest, path = line.split("  ", 1)
            self.assertNotIn(path, listed)
            listed[path] = digest
        for path, digest in listed.items():
            self.assertEqual(sha(ROOT / path), digest, path)
        for producer in proof.PRODUCERS:
            self.assertIn(producer, listed)
        self.assertIn(str(proof.AREA / "README.md"), listed)

    def test_terminal_reduction_regenerates_identically(self):
        document, _ = reduction.reduce_terminal()

        def normalize(value):
            if isinstance(value, dict):
                return {k: normalize(v) for k, v in value.items() if k != "temporary_root"}
            if isinstance(value, list):
                return [normalize(v) for v in value]
            return value

        self.assertEqual(normalize(document), normalize(self.retained["terminal-reduction.json"]))

    def test_committed_campaign_terminal_resolved_by_phase5(self):
        """Phase 5 has now physically run: the committed terminal reduction
        must carry the mechanically validated PASS and no handoff."""
        document = self.retained["terminal-reduction.json"]
        self.assertEqual(document["terminal"], reduction.TERMINAL_LOCAL_VERIFIED_BACKING_PASS)
        self.assertEqual(document["status"], "TERMINAL_RESOLVED")
        self.assertFalse(document["incomplete"])
        self.assertTrue(document["compact_source_policy_seam_pass"])
        self.assertTrue(document["physical_phase5_ran"])
        self.assertTrue(document["physical_phase5_evidence_status"]["valid"])
        self.assertIsNone(document["physical_phase5_handoff"])
        self.assertTrue(document["cache_mechanism_finding"]["legal_non_runtime_modifying_seam_exists"])
        self.assertEqual(document["cache_mechanism_finding"]["case_classification"], "C")

    def test_all_arms_and_negative_controls_recorded(self):
        arms = self.retained["arms.json"]
        for arm in ("L1", "L2", "R1", "LREQ", "RREQ"):
            self.assertIn(arm, arms)
        invariance = self.retained["materialization-invariance.json"]
        self.assertEqual(invariance["local_verified"]["materialization_identity"],
                         invariance["remote_authorized"]["materialization_identity"])
        controls = self.retained["negative-controls.json"]
        self.assertEqual(len(controls), 12, sorted(controls))


class FreshCampaignTests(unittest.TestCase):
    def test_campaign_regenerates_and_all_checks_pass(self):
        documents = proof.run_campaign()
        summary = documents["canonical-summary.json"]
        self.assertTrue(summary["all_arms_passed"])
        self.assertTrue(summary["all_negative_controls_failed_closed"])
        self.assertEqual(documents["isolation.json"]["network_operations"], [])
        self.assertEqual(documents["isolation.json"]["process_operations"], [])
        self.assertEqual(documents["isolation.json"]["outside_root_paths"], [])

    def test_campaign_is_deterministic_across_runs(self):
        first = proof.run_campaign()
        second = proof.run_campaign()

        def normalize(value):
            if isinstance(value, dict):
                return {k: normalize(v) for k, v in value.items() if k != "temporary_root"}
            if isinstance(value, list):
                return [normalize(v) for v in value]
            return value

        self.assertEqual(normalize(first), normalize(second))


class StaticDisciplineTests(unittest.TestCase):
    def test_upstream_source_identity_hashes_are_well_formed_sha256(self):
        for path, entry in cache_mechanism.UPSTREAM_SOURCE_IDENTITY.items():
            digest = entry["sha256"]
            self.assertEqual(len(digest), 64, f"{path}: sha256 must be 64 hex chars, got {len(digest)}")
            self.assertRegex(digest, r"^[0-9a-f]{64}$", f"{path}: sha256 must be lowercase hex")

    def test_proof_stack_imports_only_stdlib_and_accepted_modules(self):
        allowed = set(sys.stdlib_module_names) | {
            "issue74_methodology", "issue99_artifact_core", "issue101_orchestration",
            "issue200_r8f_source_policy", "issue200_r8f_fixture", "issue200_r8f_proof",
            "issue200_r8f_terminal_reduction", "issue200_r8f_rpc_cache_mechanism",
            "issue200_r8f_physical"}
        for name in ("issue200_r8f_proof.py", "issue200_r8f_terminal_reduction.py"):
            tree = ast.parse((ROOT / "scripts" / name).read_text())
            modules = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    modules.update(alias.name.split(".")[0] for alias in node.names)
                if isinstance(node, ast.ImportFrom) and node.module:
                    modules.add(node.module.split(".")[0])
            self.assertTrue(modules <= allowed, modules - allowed)
            self.assertFalse(modules & {"socket", "subprocess", "torch", "triton"})

    def test_phase4_finding_is_mechanically_derived_not_authored(self):
        finding = reduction.phase4_mechanical_finding()
        self.assertTrue(finding["client_process_receives_model_path_argument"])
        self.assertFalse(finding["rpc_backend_process_receives_model_path_argument"])
        self.assertFalse(finding["rpc_backend_process_receives_cache_flag"])
        self.assertIn("retraction_note", finding)

    def test_cache_mechanism_finding_is_mechanically_derived_from_retained_experiment(self):
        finding = reduction.cache_mechanism_finding()
        self.assertEqual(finding["case_classification"], "C")
        self.assertTrue(finding["legal_non_runtime_modifying_seam_exists"])
        self.assertTrue(finding["durable_cache_reuse_suppresses_retransmission"])
        self.assertTrue(finding["prestaged_verified_backing_consumed_without_prior_network_pass"])
        self.assertTrue(finding["upstream_cache_is_fail_open_on_wrong_or_truncated_content"])
        self.assertTrue(finding["requires_external_provenance_verification_before_cache_population"])
        evidence = ROOT / proof.AREA / "evidence"
        experiment = json.loads((evidence / "rpc-cache-experiment.json").read_text())
        phases = experiment["phases"]
        cold = phases["A_cold"]["result"]["bytes_set_phase_alloc_to_set_done"]["sent"]
        warm = phases["B_warm_restart"]["result"]["bytes_set_phase_alloc_to_set_done"]["sent"]
        prestaged = phases["C_prestaged"]["result"]["bytes_set_phase_alloc_to_set_done"]["sent"]
        self.assertGreater(cold, cache_mechanism.HASH_THRESHOLD_BYTES)
        self.assertLess(warm, cache_mechanism.SMALL_RESPONSE_THRESHOLD_BYTES)
        self.assertLess(prestaged, cache_mechanism.SMALL_RESPONSE_THRESHOLD_BYTES)
        self.assertEqual(phases["D_wrong_content"]["result"]["exit_code"], 2)
        self.assertEqual(phases["E_truncated"]["result"]["exit_code"], 2)

    def test_terminal_reduction_carries_no_authored_magnitudes(self):
        document, _ = reduction.reduce_terminal()
        self.assertNotIn("staged_bytes", document)
        self.assertNotIn("network_bytes", document)


class TerminalReductionFailClosedTests(unittest.TestCase):
    """PASS is derived from raw receipts; it is never an authored boolean."""

    def test_legal_seam_plus_no_physical_evidence_cannot_pass(self):
        with tempfile.TemporaryDirectory() as td:
            missing = Path(td) / "physical-phase5.json"
            with mock.patch.object(cache_mechanism, "mechanical_cache_finding",
                                   return_value=valid_cache_finding()):
                document, _ = reduction.reduce_terminal(physical_phase5_evidence_path=missing)
        self.assertNotEqual(document["terminal"], reduction.TERMINAL_LOCAL_VERIFIED_BACKING_PASS)
        self.assertIsNone(document["terminal"])
        self.assertEqual(document["status"], "PHASE5_REQUIRED")

    def test_missing_physical_evidence_cannot_pass(self):
        with tempfile.TemporaryDirectory() as td:
            missing_path = Path(td) / "physical-phase5.json"
            with mock.patch.object(cache_mechanism, "mechanical_cache_finding",
                                   return_value=valid_cache_finding()):
                document, _ = reduction.reduce_terminal(physical_phase5_evidence_path=missing_path)
        self.assertFalse(document["physical_phase5_ran"])

    def test_invalid_or_mismatched_physical_evidence_cannot_pass(self):
        for bad_doc in ({}, {"schema": "wrong-schema"}):
            with tempfile.TemporaryDirectory() as td:
                path = Path(td) / "physical-phase5.json"
                path.write_text(json.dumps(bad_doc))
                with mock.patch.object(cache_mechanism, "mechanical_cache_finding",
                                       return_value=valid_cache_finding()):
                    document, _ = reduction.reduce_terminal(physical_phase5_evidence_path=path)
                self.assertNotEqual(document["terminal"], reduction.TERMINAL_LOCAL_VERIFIED_BACKING_PASS,
                                    bad_doc)
                self.assertFalse(document["physical_phase5_ran"], bad_doc)

    def test_valid_physical_evidence_enables_pass(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            path = root / "physical-phase5.json"
            path.write_text(json.dumps(valid_physical_phase5_document(Path(td))))
            with mock.patch.object(cache_mechanism, "mechanical_cache_finding", return_value=valid_cache_finding()), \
                 mock.patch.object(physical, "accepted_model_authority", return_value=synthetic_authority(root)[0]):
                document, _ = reduction.reduce_terminal(physical_phase5_evidence_path=path)
        self.assertEqual(document["terminal"], reduction.TERMINAL_LOCAL_VERIFIED_BACKING_PASS)
        self.assertTrue(document["physical_phase5_ran"])

    def _rejects_pass_after_mutation(self, mutate):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            doc = valid_physical_phase5_document(root)
            mutate(doc, root)
            path = root / "physical-phase5.json"
            path.write_text(json.dumps(doc))
            with mock.patch.object(cache_mechanism, "mechanical_cache_finding", return_value=valid_cache_finding()), \
                 mock.patch.object(physical, "accepted_model_authority", return_value=synthetic_authority(root)[0]):
                result, _ = reduction.reduce_terminal(physical_phase5_evidence_path=path)
            self.assertNotEqual(result["terminal"], reduction.TERMINAL_LOCAL_VERIFIED_BACKING_PASS)
            self.assertFalse(result["physical_phase5_ran"])

    def test_required_physical_mutations_reject_pass(self):
        mutations = [
            lambda d, r: d["arms"]["local_verified"].__setitem__("placement_identity", "sha256:drift"),
            lambda d, r: d["arms"]["local_verified"].__setitem__("required_state_identity", "sha256:drift"),
            lambda d, r: d["arms"]["local_verified"].__setitem__("materialization_identity", "sha256:drift"),
            lambda d, r: d["accepted_model_members"][0].__setitem__("sha256", "0" * 64),
            lambda d, r: d["accepted_model_members"][0].__setitem__("bytes", 1),
            lambda d, r: d["participants"].clear(),
            lambda d, r: d["arms"]["local_verified"].pop("source_attribution"),
            lambda d, r: d["arms"]["repeat_local_verified"].__setitem__(
                "private_cache_dir", "/private/other-cache"),
            lambda d, r: d.__setitem__("zero_reacquisition_bytes_measured", True),
        ]
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                self._rejects_pass_after_mutation(mutation)

    def test_byte_complete_capture_and_provenance_adversaries_reject(self):
        """Every corrected weakness fails closed: abbreviated cold payload,
        same-length wrong payload, attach-form capture, missing/tampered
        retained bytes, cross-arm range substitution, missing backing member,
        forged entries_before, tampered runtime logs, synthetic attribution,
        staging digest mismatch, absent cache read, secret re-stage, wrong
        reused bytes, wrong argv/binary binding."""

        def abbreviated_cold_payload(doc, root):
            receipt = doc["arms"]["cold_remote"]["network_receipt"]
            path = root / receipt["raw_capture"]["path"]
            payload = b"r8-f-observed-payload-" * 4
            records = [
                '999 1.000 execve("{strace_escape(CLIENT_ARGV[0].encode())}", ...) = 0',
                '999 1.000 connect(3, {sa_family=AF_INET, sin_port=htons(50052), '
                'sin_addr=inet_addr("100.77.187.38")}, 16) = 0',
                f'1001 1.002 sendto(3, "{strace_escape(payload[:8])}...", {len(payload)}, 0, NULL, 0) = {len(payload)}',
            ]
            path.write_bytes(("\n".join(records) + "\n").encode())
            receipt["raw_capture"]["sha256"] = sha(path)

        def same_length_wrong_payload(doc, root):
            receipt = doc["arms"]["cold_remote"]["network_receipt"]
            path = root / receipt["raw_capture"]["path"]
            wrong = bytearray(b"r8-f-observed-payload-" * 4)
            wrong[0] ^= 0xFF
            framed = b"\x00" * 8 + bytes(wrong)
            records = [
                '999 1.000 execve("{strace_escape(CLIENT_ARGV[0].encode())}", ...) = 0',
                '999 1.000 connect(3, {sa_family=AF_INET, sin_port=htons(50052), '
                'sin_addr=inet_addr("100.77.187.38")}, 16) = 0',
                f'1001 1.002 sendto(3, "{strace_escape(framed)}", {len(framed)}, 0, NULL, 0) = {len(framed)}',
            ]
            path.write_bytes(("\n".join(records) + "\n").encode())
            receipt["raw_capture"]["sha256"] = sha(path)

        def attach_form_capture(doc, root):
            receipt = doc["arms"]["cold_remote"]["network_receipt"]
            payload_len = doc["arms"]["cold_remote"]["set_tensor_payloads"][0]["length"]
            receipt["capture_command"] = ["strace", "-f", "--always-show-pid", "-ttt", "-xx",
                                          "-s", str(payload_len + 4096),
                                          "-e", "trace=network,write,writev,execve", "-p", "999"]

        def capture_without_execve_start(doc, root):
            receipt = doc["arms"]["cold_remote"]["network_receipt"]
            path = root / receipt["raw_capture"]["path"]
            lines = path.read_text().splitlines()
            path.write_bytes(("\n".join(l for l in lines if "execve" not in l) + "\n").encode())
            receipt["raw_capture"]["sha256"] = sha(path)

        def tampered_retained_bytes(doc, root):
            path = root / "raw/cold_remote.range.bin"
            data = bytearray(path.read_bytes())
            data[0] ^= 0xFF
            path.write_bytes(bytes(data))
            receipt = doc["arms"]["cold_remote"]["accepted_artifact_ranges"][0][
                "accepted_artifact_range"]["provenance_receipt"]["retained_range"]
            receipt["sha256"] = sha(path)

        def cold_range_substituted_from_local(doc, root):
            # same length, different bytes than the cold receipt measured
            path = root / "raw/cold_remote.range.bin"
            data = bytearray(path.read_bytes())
            data[-1] ^= 0x01
            path.write_bytes(bytes(data))
            receipt = doc["arms"]["cold_remote"]["accepted_artifact_ranges"][0][
                "accepted_artifact_range"]["provenance_receipt"]["retained_range"]
            receipt["sha256"] = sha(path)

        def missing_backing_member(doc, root):
            backing = json.loads((root / doc["participant_backing_verification"]["receipt"]["path"]).read_text())
            backing["members"].pop()
            doc["participant_backing_verification"]["receipt"] = _receipt(
                root, "raw/backing.json", backing)

        def unverified_backing_member(doc, root):
            backing = json.loads((root / doc["participant_backing_verification"]["receipt"]["path"]).read_text())
            backing["members"][0]["verified"] = False
            doc["participant_backing_verification"]["receipt"] = _receipt(
                root, "raw/backing.json", backing)

        def forged_entries_before(doc, root):
            init = json.loads((root / doc["arms"]["cold_remote"]["cache_initialization_receipt"]["path"]).read_text())
            init["entries"] = [{"name": "rpc/stale", "size": 1, "sha256": "0" * 64}]
            doc["arms"]["cold_remote"]["cache_initialization_receipt"] = _receipt(
                root, "raw/cold_remote.cache-init.json", init)

        def nonempty_fresh_local_cache(doc, root):
            init = json.loads((root / doc["arms"]["local_verified"]["cache_initialization_receipt"]["path"]).read_text())
            init["entries"] = [{"name": "rpc/preexisting", "size": 5, "sha256": "0" * 64}]
            doc["arms"]["local_verified"]["cache_initialization_receipt"] = _receipt(
                root, "raw/local_verified.cache-init.json", init)

        def tampered_client_log(doc, root):
            launch = json.loads((root / doc["arms"]["local_verified"]["client_launch_receipt"]["path"]).read_text())
            log = root / launch["client_log"]["path"]
            log.write_bytes(b"client exited unexpectedly\n")
            launch["client_log"]["sha256"] = sha(log)
            doc["arms"]["local_verified"]["client_launch_receipt"] = _receipt(
                root, "raw/local_verified.client-launch.json", launch)

        def missing_server_log(doc, root):
            launch = json.loads((root / doc["arms"]["local_verified"]["rpc_server_receipt"]["path"]).read_text())
            launch.pop("server_log")
            doc["arms"]["local_verified"]["rpc_server_receipt"] = _receipt(
                root, "raw/local_verified.rpc-launch.json", launch)

        def synthetic_source_attribution(doc, root):
            doc["arms"]["local_verified"].pop("participant_read_receipt")

        def attribution_disagreeing_with_strace(doc, root):
            reads = json.loads((root / doc["arms"]["local_verified"]["participant_read_receipt"]["path"]).read_text())
            reads["derived_read_bytes"] = 1
            doc["arms"]["local_verified"]["participant_read_receipt"] = _receipt(
                root, "raw/local_verified.reads.json", reads)

        def cold_read_receipt_masking_local_read(doc, root):
            """Review L2-1's demonstrated attack: swap the COLD arm's
            participant-read receipt for the local arm's (relabel + digest
            fix).  The hardened cold-arm zero-read denial must reject."""
            import shutil
            src = root / "raw/local_verified.reads.strace"
            dst = root / "raw/cold_remote.reads.strace"
            cold_cache = doc["arms"]["cold_remote"]["private_cache_dir"]
            local_cache = doc["arms"]["local_verified"]["private_cache_dir"]
            data = src.read_bytes().replace(local_cache.encode(), cold_cache.encode())
            dst.write_bytes(data)
            reads = json.loads((root / doc["arms"]["cold_remote"]["participant_read_receipt"]["path"]).read_text())
            reads["cache_dir"] = cold_cache
            reads["strace_capture"] = {"path": "raw/cold_remote.reads.strace",
                                       "sha256": hashlib.sha256(data).hexdigest()}
            reads["derived_read_bytes"] = len(payload_bytes) if (payload_bytes := b"r8-f-observed-payload-" * 4) else 0
            reads["read_syscalls"] = 1
            doc["arms"]["cold_remote"]["participant_read_receipt"] = _receipt(
                root, "raw/cold_remote.reads.json", reads)

        def absent_cache_read(doc, root):
            reads = json.loads((root / doc["arms"]["local_verified"]["participant_read_receipt"]["path"]).read_text())
            cap = root / reads["strace_capture"]["path"]
            cap.write_bytes(b'777 1.000 execve("' + strace_escape(physical.FROZEN_RPC_EXEC[0].encode()).encode() + b'", []) = 0\n')
            reads["strace_capture"]["sha256"] = sha(cap)
            reads["derived_read_bytes"] = 0
            reads["read_syscalls"] = 0
            doc["arms"]["local_verified"]["participant_read_receipt"] = _receipt(
                root, "raw/local_verified.reads.json", reads)

        def staging_digest_mismatch(doc, root):
            staged = doc["arms"]["local_verified"]["cache_staging"][0]["staged_cache"]
            receipt = json.loads((root / staged["raw_stdout"]["path"]).read_text())
            receipt["final_sha256"] = "0" * 64
            staged["raw_stdout"] = _receipt(root, "raw/local_verified.staging.stdout", receipt)

        def staging_exit_mismatch(doc, root):
            # raw-stdout authority: exit status is non-authoritative, but a
            # TAMPERED raw stdout (wrong member) must still reject.
            staged = doc["arms"]["local_verified"]["cache_staging"][0]["staged_cache"]
            receipt = json.loads((root / staged["raw_stdout"]["path"]).read_text())
            receipt["member"] = "wrong-member.gguf"
            staged["raw_stdout"] = _receipt(root, "raw/local_verified.staging.stdout", receipt)

        def repeat_arm_secretly_restages(doc, root):
            arm = doc["arms"]["repeat_local_verified"]
            arm["cache_staging"] = json.loads(json.dumps(
                doc["arms"]["local_verified"]["cache_staging"]))

        def reused_cache_wrong_bytes(doc, root):
            pre = json.loads((root / doc["arms"]["repeat_local_verified"]["cache_precheck_receipt"]["path"]).read_text())
            pre["entries"][0]["sha256"] = "0" * 64
            doc["arms"]["repeat_local_verified"]["cache_precheck_receipt"] = _receipt(
                root, "raw/repeat_local_verified.cache-precheck.json", pre)

        def wrong_client_argv(doc, root):
            doc["frozen_client_argv"] = CLIENT_ARGV[:-1]

        def wrong_client_binary(doc, root):
            launch = json.loads((root / doc["arms"]["local_verified"]["client_launch_receipt"]["path"]).read_text())
            launch["binary_sha256"] = "0" * 64
            doc["arms"]["local_verified"]["client_launch_receipt"] = _receipt(
                root, "raw/local_verified.client-launch.json", launch)

        def wrong_rpc_env(doc, root):
            launch = json.loads((root / doc["arms"]["local_verified"]["rpc_server_receipt"]["path"]).read_text())
            launch["env"] = {"LLAMA_CACHE": "/somewhere/else"}
            doc["arms"]["local_verified"]["rpc_server_receipt"] = _receipt(
                root, "raw/local_verified.rpc-launch.json", launch)

        def local_capture_contains_payload(doc, root):
            receipt = doc["arms"]["local_verified"]["network_receipt"]
            path = root / receipt["raw_capture"]["path"]
            payload = b"r8-f-observed-payload-" * 4
            framed = b"\x00" * 8 + payload
            line = (f'\n1001 9.999 sendto(3, "{strace_escape(framed)}", {len(framed)}, '
                    f'0, NULL, 0) = {len(framed)}')
            path.write_bytes(path.read_bytes() + line.encode())
            receipt["raw_capture"]["sha256"] = sha(path)

        # ---- review item 6: execve argv mutation controls (same accepted
        # binary, one acceptance-significant argument changed, ALL JSON
        # metadata still claiming the frozen argv).  The full-argv byte
        # comparison must reject each one.
        def _rewritten_client_capture(doc, root, argv):
            receipt = doc["arms"]["cold_remote"]["network_receipt"]
            path = root / receipt["raw_capture"]["path"]
            payload = b"r8-f-observed-payload-" * 4
            framed = b"\x00" * 8 + payload
            records = [
                f'999 1.000 execve("{strace_escape(argv[0].encode())}", '
                f'[{", ".join(quote_arg(a) for a in argv)}], 0x1 /* 1 var */) = 0',
                '999 1.000 connect(3, {sa_family=AF_INET, sin_port=htons(50052), '
                'sin_addr=inet_addr("100.77.187.38")}, 16) = 0',
                f'1001 1.002 sendto(3, "{strace_escape(framed)}", {len(framed)}, 0, NULL, 0) = {len(framed)}',
            ]
            path.write_bytes(("\n".join(records) + "\n").encode())
            receipt["raw_capture"]["sha256"] = sha(path)
            receipt["capture_command"] = network_reduce.required_capture_command(argv, [len(payload)])

        def argv_mutated_model_path(doc, root):
            argv = list(CLIENT_ARGV)
            argv[argv.index("-m") + 1] = "/models/a-different-member.gguf"
            _rewritten_client_capture(doc, root, argv)

        def argv_mutated_rpc_endpoint(doc, root):
            argv = list(CLIENT_ARGV)
            argv[argv.index("--rpc") + 1] = "10.0.0.204:50053"
            _rewritten_client_capture(doc, root, argv)

        def argv_mutated_ot_mapping(doc, root):
            argv = list(CLIENT_ARGV)
            argv[argv.index("-ot") + 1] = "blk.99.attn_gate.weight=RPC0[10.0.0.204:50052]"
            _rewritten_client_capture(doc, root, argv)

        def argv_mutated_ngl(doc, root):
            argv = list(CLIENT_ARGV)
            argv[argv.index("-ngl") + 1] = "99"
            _rewritten_client_capture(doc, root, argv)

        def argv_mutated_context(doc, root):
            argv = list(CLIENT_ARGV)
            argv[argv.index("-c") + 1] = "4096"
            _rewritten_client_capture(doc, root, argv)

        def argv_mutated_no_warmup_removed(doc, root):
            argv = [a for a in CLIENT_ARGV if a != "--no-warmup"]
            _rewritten_client_capture(doc, root, argv)

        def argv_reordered(doc, root):
            argv = list(CLIENT_ARGV)
            i, j = argv.index("--no-warmup"), argv.index("-ngl")
            argv[i], argv[j] = argv[j], argv[i]
            _rewritten_client_capture(doc, root, argv)

        def argv_extra_argument(doc, root):
            argv = list(CLIENT_ARGV) + ["--threads", "8"]
            _rewritten_client_capture(doc, root, argv)

        def abbreviated_execve_record(doc, root):
            receipt = doc["arms"]["cold_remote"]["network_receipt"]
            path = root / receipt["raw_capture"]["path"]
            lines = path.read_text().splitlines()
            lines[0] = f'999 1.000 execve("{strace_escape(CLIENT_ARGV[0].encode())}", ...) = 0'
            path.write_bytes(("\n".join(lines) + "\n").encode())
            receipt["raw_capture"]["sha256"] = sha(path)

        # ---- review item 7: RPC-server execution binding controls.
        def _rewritten_rpc_capture(doc, root, arm_name, argv):
            reads = json.loads((root / doc["arms"][arm_name]["participant_read_receipt"]["path"]).read_text())
            cap = root / reads["strace_capture"]["path"]
            lines = cap.read_text().splitlines()
            lines[0] = (f'777 1.000 execve("{strace_escape(argv[0].encode())}", '
                        f'[{", ".join(quote_arg(a) for a in argv)}], 0x1 /* 1 var */) = 0')
            cap.write_bytes(("\n".join(lines) + "\n").encode())
            reads["strace_capture"]["sha256"] = sha(cap)
            doc["arms"][arm_name]["participant_read_receipt"] = _receipt(
                root, f"raw/{arm_name}.reads.json", reads)

        def rpc_execve_wrong_binary(doc, root):
            argv = ["/some/other/ggml-rpc-server", "-H", "0.0.0.0", "-p", "50052", "-d", "CUDA0", "-c"]
            _rewritten_rpc_capture(doc, root, "local_verified", argv)

        def rpc_execve_cache_flag_removed(doc, root):
            argv = [physical.FROZEN_RPC_EXEC[0], "-H", "0.0.0.0", "-p", "50052", "-d", "CUDA0"]
            _rewritten_rpc_capture(doc, root, "local_verified", argv)

        def rpc_execve_wrong_port(doc, root):
            argv = [physical.FROZEN_RPC_EXEC[0], "-H", "0.0.0.0", "-p", "60000", "-d", "CUDA0", "-c"]
            _rewritten_rpc_capture(doc, root, "local_verified", argv)

        def rpc_strace_not_from_exec(doc, root):
            reads = json.loads((root / doc["arms"]["local_verified"]["participant_read_receipt"]["path"]).read_text())
            cap = root / reads["strace_capture"]["path"]
            lines = cap.read_text().splitlines()
            lines[0] = '777 2.000 openat(AT_FDCWD, "/etc/ld.so.cache", O_RDONLY) = 3'
            cap.write_bytes(("\n".join(lines) + "\n").encode())
            reads["strace_capture"]["sha256"] = sha(cap)
            doc["arms"]["local_verified"]["participant_read_receipt"] = _receipt(
                root, "raw/local_verified.reads.json", reads)

        # ---- review item 10: backing verification controls.
        def _rewrite_backing(doc, root, mutate):
            backing = json.loads((root / doc["participant_backing_verification"]["receipt"]["path"]).read_text())
            mutate(backing)
            doc["participant_backing_verification"]["receipt"] = _receipt(
                root, "raw/backing.json", backing)

        def backing_forged_verified_wrong_sha(doc, root):
            def mutate(b):
                b["members"][0]["actual_sha256"] = "0" * 64  # forged verified:true, wrong measured SHA
            _rewrite_backing(doc, root, mutate)

        def backing_forged_verified_wrong_size(doc, root):
            def mutate(b):
                b["members"][0]["actual_bytes"] = 1  # forged verified:true, wrong measured size
            _rewrite_backing(doc, root, mutate)

        def backing_zero_helper_sha(doc, root):
            def mutate(b):
                b["tool"]["sha256"] = "0" * 64
            _rewrite_backing(doc, root, mutate)

        def backing_wrong_helper_path(doc, root):
            def mutate(b):
                b["tool"]["path"] = "scripts/some_other_helper.py"
            _rewrite_backing(doc, root, mutate)

        def backing_extra_member(doc, root):
            def mutate(b):
                b["members"].append({"file": "extra.gguf", "bytes": 1, "sha256": "0" * 64,
                                     "present": True, "verified": True, "actual_bytes": 1,
                                     "actual_sha256": "0" * 64})
            _rewrite_backing(doc, root, mutate)

        def backing_wrong_authority_path(doc, root):
            def mutate(b):
                b["authority_path"] = "/some/other/authority.json"
            _rewrite_backing(doc, root, mutate)

        def backing_nonempty_stderr(doc, root):
            path = root / doc["participant_backing_verification"]["stderr"]["path"]
            path.write_bytes(b"helper warning noise\n")
            doc["participant_backing_verification"]["stderr"]["sha256"] = sha(path)

        # ---- review item 12: cache-enum helper identity controls.
        def _rewrite_enum(doc, root, arm_name, key, mutate):
            ref = doc["arms"][arm_name].get("cache_initialization_receipt") \
                or doc["arms"][arm_name]["cache_precheck_receipt"]
            enum = json.loads((root / ref["path"]).read_text())
            mutate(enum)
            doc["arms"][arm_name][ "cache_initialization_receipt" if "cache_initialization_receipt"
                                   in doc["arms"][arm_name] else "cache_precheck_receipt"] = _receipt(
                root, f"raw/{arm_name}.cache-enum-forged.json", enum)

        def enum_wrong_helper_identity(doc, root):
            _rewrite_enum(doc, root, "cold_remote", "tool",
                          lambda e: e.__setitem__("tool", {"path": "scripts/issue200_r8f_cache_enum.py",
                                                           "sha256": "0" * 64}))

        def enum_missing_helper_identity(doc, root):
            def mutate(e):
                e.pop("tool", None)
                e["command"] = ["cache-enum.sh", e["arm"], e["cache_dir"]]  # fictitious pre-correction form
            _rewrite_enum(doc, root, "cold_remote", "tool", mutate)

        def precheck_wrong_helper_identity(doc, root):
            _rewrite_enum(doc, root, "repeat_local_verified", "tool",
                          lambda e: e.__setitem__("tool", {"path": "scripts/issue200_r8f_cache_enum.py",
                                                           "sha256": "1" * 64}))

        def precheck_fictitious_command(doc, root):
            _rewrite_enum(doc, root, "repeat_local_verified", "command",
                          lambda e: e.__setitem__("command", ["cache-enum.sh", e["arm"], e["cache_dir"]]))

        # ---- review item 14: staging provenance controls.
        def _rewrite_staging(doc, root, mutate):
            staged = doc["arms"]["local_verified"]["cache_staging"][0]["staged_cache"]
            measurement = json.loads((root / staged["raw_stdout"]["path"]).read_text())
            mutate(measurement)
            staged["raw_stdout"] = _receipt(root, "raw/local_verified.staging.stdout", measurement)

        def staging_wrong_helper_hash(doc, root):
            _rewrite_staging(doc, root, lambda m: m["tool"].__setitem__("sha256", "0" * 64))

        def staging_wrong_helper_path(doc, root):
            _rewrite_staging(doc, root, lambda m: m["tool"].__setitem__("path", "scripts/wrong_stage.py"))

        def staging_forged_wrapper_only(doc, root):
            # A perfect wrapper document with NO raw stdout cannot validate.
            doc["arms"]["local_verified"]["cache_staging"][0]["staged_cache"].pop("raw_stdout")

        def staging_mismatched_raw_vs_wrapper(doc, root):
            staged = doc["arms"]["local_verified"]["cache_staging"][0]["staged_cache"]
            measurement = json.loads((root / staged["raw_stdout"]["path"]).read_text())
            measurement["staged_path"] = f"{measurement['cache_dir']}/ffffffffffffffff"
            staged["path"] = measurement["staged_path"]  # wrapper agrees, FNV wrong
            staged["raw_stdout"] = _receipt(root, "raw/local_verified.staging.stdout", measurement)

        def staging_nonempty_stderr(doc, root):
            staged = doc["arms"]["local_verified"]["cache_staging"][0]["staged_cache"]
            path = root / staged["raw_stderr"]["path"]
            path.write_bytes(b"staging stderr noise\n")
            staged["raw_stderr"]["sha256"] = sha(path)

        def staging_missing_raw_stdout(doc, root):
            staged = doc["arms"]["local_verified"]["cache_staging"][0]["staged_cache"]
            (root / staged["raw_stdout"]["path"]).unlink()
            # digest reference still points at the missing file

        def cold_decoy_fd_rebind_laundering_read(doc, root):
            """Review LANE-B-1's demonstrated forgery (round 3): inject an
            O_RDONLY openat of the cold cache file, then a decoy same-fd
            openat of /etc/hostname, then a successful read — the fd-reuse
            clearing must NOT launder the read-mode cache open."""
            reads = json.loads((root / doc["arms"]["cold_remote"]["participant_read_receipt"]["path"]).read_text())
            cap = root / reads["strace_capture"]["path"]
            cold_cache = doc["arms"]["cold_remote"]["private_cache_dir"]
            fnv = doc["arms"]["cold_remote"]["set_tensor_payloads"][0]["fnv1a_cache_key"]
            injection = (f'777 3.000 openat(AT_FDCWD, "{cold_cache}/rpc/{fnv}", O_RDONLY) = 38\n'
                         '777 3.001 openat(AT_FDCWD, "/etc/hostname", O_RDONLY) = 38\n'
                         '777 3.002 read(38, "zz", 10) = 10\n')
            cap.write_bytes(cap.read_bytes() + injection.encode())
            reads["strace_capture"]["sha256"] = sha(cap)
            doc["arms"]["cold_remote"]["participant_read_receipt"] = _receipt(
                root, "raw/cold_remote.reads.json", reads)

        cases = {
            "abbreviated-cold-payload": abbreviated_cold_payload,
            "same-length-wrong-payload": same_length_wrong_payload,
            "attach-form-capture": attach_form_capture,
            "capture-without-execve-start": capture_without_execve_start,
            "tampered-retained-bytes": tampered_retained_bytes,
            "cold-range-substituted": cold_range_substituted_from_local,
            "cold-read-receipt-masks-local-read": cold_read_receipt_masking_local_read,
            "cold-decoy-fd-rebind-laundering-read": cold_decoy_fd_rebind_laundering_read,
            "missing-backing-member": missing_backing_member,
            "unverified-backing-member": unverified_backing_member,
            "forged-entries-before": forged_entries_before,
            "nonempty-fresh-local-cache": nonempty_fresh_local_cache,
            "tampered-client-log": tampered_client_log,
            "missing-server-log": missing_server_log,
            "synthetic-source-attribution": synthetic_source_attribution,
            "attribution-disagrees-with-strace": attribution_disagreeing_with_strace,
            "absent-cache-read": absent_cache_read,
            "staging-digest-mismatch": staging_digest_mismatch,
            "staging-exit-mismatch": staging_exit_mismatch,
            "repeat-arm-secretly-restages": repeat_arm_secretly_restages,
            "reused-cache-wrong-bytes": reused_cache_wrong_bytes,
            "wrong-client-argv": wrong_client_argv,
            "wrong-client-binary": wrong_client_binary,
            "wrong-rpc-env": wrong_rpc_env,
            "payload-in-local-capture": local_capture_contains_payload,
            # item 6 — client execve argv mutations
            "argv-mutated-model-path": argv_mutated_model_path,
            "argv-mutated-rpc-endpoint": argv_mutated_rpc_endpoint,
            "argv-mutated-ot-mapping": argv_mutated_ot_mapping,
            "argv-mutated-ngl": argv_mutated_ngl,
            "argv-mutated-context": argv_mutated_context,
            "argv-no-warmup-removed": argv_mutated_no_warmup_removed,
            "argv-reordered": argv_reordered,
            "argv-extra-argument": argv_extra_argument,
            "abbreviated-execve-record": abbreviated_execve_record,
            # item 7 — RPC execve binding
            "rpc-execve-wrong-binary": rpc_execve_wrong_binary,
            "rpc-execve-cache-flag-removed": rpc_execve_cache_flag_removed,
            "rpc-execve-wrong-port": rpc_execve_wrong_port,
            "rpc-strace-not-from-exec": rpc_strace_not_from_exec,
            # item 10 — backing controls
            "backing-forged-verified-wrong-sha": backing_forged_verified_wrong_sha,
            "backing-forged-verified-wrong-size": backing_forged_verified_wrong_size,
            "backing-zero-helper-sha": backing_zero_helper_sha,
            "backing-wrong-helper-path": backing_wrong_helper_path,
            "backing-extra-member": backing_extra_member,
            "backing-wrong-authority-path": backing_wrong_authority_path,
            "backing-nonempty-stderr": backing_nonempty_stderr,
            # item 12 — enum helper identity
            "enum-wrong-helper-identity": enum_wrong_helper_identity,
            "enum-missing-helper-identity": enum_missing_helper_identity,
            "precheck-wrong-helper-identity": precheck_wrong_helper_identity,
            "precheck-fictitious-command": precheck_fictitious_command,
            # item 14 — staging provenance
            "staging-wrong-helper-hash": staging_wrong_helper_hash,
            "staging-wrong-helper-path": staging_wrong_helper_path,
            "staging-forged-wrapper-only": staging_forged_wrapper_only,
            "staging-mismatched-raw-vs-wrapper": staging_mismatched_raw_vs_wrapper,
            "staging-nonempty-stderr": staging_nonempty_stderr,
            "staging-missing-raw-stdout": staging_missing_raw_stdout,
        }
        for name, mutation in cases.items():
            with self.subTest(name=name):
                self._rejects_pass_after_mutation(mutation)


class ByteCompleteReducerTests(unittest.TestCase):
    """Reducer-level controls for the /4 byte-complete contract."""

    PAYLOAD = b"byte-complete-payload-0123456789-0123456789-0123456789"

    def _identity(self):
        return {"participant": "inferswarm04", "observation_id": "set-1", "order": 1,
                "offset": 0, "length": len(self.PAYLOAD),
                "sha256": hashlib.sha256(self.PAYLOAD).hexdigest(), "bytes": self.PAYLOAD}

    def _connect(self):
        return ('999 1.000 connect(3, {sa_family=AF_INET, sin_port=htons(50052), '
                'sin_addr=inet_addr("100.77.187.38")}, 16) = 0\n').encode()

    def _exec(self):
        return (f'999 1.000 execve("{strace_escape(CLIENT_ARGV[0].encode())}", '
                f'[{", ".join(quote_arg(a) for a in CLIENT_ARGV)}], 0x1 /* 1 var */) = 0\n').encode()

    def test_string_limit_is_mechanically_derived(self):
        self.assertEqual(network_reduce.required_string_limit([100]), 100 + 4096)
        self.assertEqual(network_reduce.required_string_limit([100, 200]), 200 + 4096)
        with self.assertRaises(ValueError):
            network_reduce.required_string_limit([])

    def test_capture_contract_rejects_attach_form(self):
        good = network_reduce.required_capture_command(CLIENT_ARGV, [len(self.PAYLOAD)])
        self.assertIn("-s", good)
        self.assertEqual(good[good.index("-s") + 1], str(len(self.PAYLOAD) + 4096))
        attached = ["strace", "-f", "--always-show-pid", "-ttt", "-xx",
                    "-s", str(len(self.PAYLOAD) + 4096),
                    "-e", "trace=network,write,writev,execve", "-p", "999"]
        with self.assertRaises(ValueError):
            network_reduce.validate_capture_contract(attached, CLIENT_ARGV, [len(self.PAYLOAD)])

    def test_exact_bytes_attributed_and_abbreviation_rejected(self):
        identity = self._identity()
        framed = b"\x00" * 8 + self.PAYLOAD
        base = self._exec() + self._connect()
        complete = (f'1001 1.002 sendto(3, "{strace_escape(framed)}", {len(framed)}, '
                    f'0, NULL, 0) = {len(framed)}\n').encode()
        out = network_reduce.reduce_capture(base + complete, client_pid=999,
                                            server_endpoint="100.77.187.38:50052",
                                            payloads=[identity], client_argv=CLIENT_ARGV)
        self.assertEqual(out["immutable_payload_bytes"], len(self.PAYLOAD))
        # An abbreviated record (the -s 0 form) is NEVER identity evidence.
        abbreviated = (f'1001 1.002 sendto(3, "{strace_escape(self.PAYLOAD[:8])}...", '
                       f'{len(framed)}, 0, NULL, 0) = {len(framed)}\n').encode()
        with self.assertRaisesRegex(ValueError, "abbreviated"):
            network_reduce.reduce_capture(base + abbreviated, client_pid=999,
                                          server_endpoint="100.77.187.38:50052",
                                          payloads=[identity], client_argv=CLIENT_ARGV)
        # Same-length wrong bytes never match the payload suffix.
        wrong = bytearray(self.PAYLOAD)
        wrong[5] ^= 0xFF
        wrong_framed = b"\x00" * 8 + bytes(wrong)
        wrong_rec = (f'1001 1.002 sendto(3, "{strace_escape(wrong_framed)}", {len(wrong_framed)}, '
                     f'0, NULL, 0) = {len(wrong_framed)}\n').encode()
        with self.assertRaisesRegex(ValueError, "unexplained payload-class|not attributable|does not carry the exact frozen payload"):
            network_reduce.reduce_capture(base + wrong_rec, client_pid=999,
                                          server_endpoint="100.77.187.38:50052",
                                          payloads=[identity], client_argv=CLIENT_ARGV)
        # Missing execve start record rejects (attach evidence).
        with self.assertRaisesRegex(ValueError, "execve"):
            network_reduce.reduce_capture(self._connect() + complete, client_pid=999,
                                          server_endpoint="100.77.187.38:50052",
                                          payloads=[identity], client_argv=CLIENT_ARGV)
        # Fragmented sub-window sends cannot zero-claim.
        fragmented = (base
                      + f'1001 1.002 sendto(3, "{strace_escape(self.PAYLOAD[:16])}", 16, 0, NULL, 0) = 16\n'.encode()
                      + f'1001 1.003 sendto(3, "{strace_escape(self.PAYLOAD[16:])}", {len(self.PAYLOAD) - 16}, 0, NULL, 0) = {len(self.PAYLOAD) - 16}\n'.encode())
        with self.assertRaisesRegex(ValueError, "not attributable|does not carry the exact frozen payload"):
            network_reduce.reduce_capture(fragmented, client_pid=999,
                                          server_endpoint="100.77.187.38:50052",
                                          payloads=[identity], client_argv=CLIENT_ARGV)
        # Unsupported target-bound outbound form rejects.
        for record in (b'1001 1.001 write(3, "x", 1) = 1\n',
                       b'1001 1.001 writev(3, [{iov_base="x", iov_len=1}], 1) = 1\n',
                       b'1001 1.001 sendmsg(3, {msg_iov=[{iov_base="x", iov_len=1}]}, 0) = 1\n'):
            with self.subTest(record=record[:20]):
                with self.assertRaisesRegex(ValueError, "unsupported outbound"):
                    network_reduce.reduce_capture(base + record, client_pid=999,
                                                  server_endpoint="100.77.187.38:50052",
                                                  payloads=[], client_argv=CLIENT_ARGV)
        # Unprovenanced target sendto rejects.
        unprovenanced = (f'1001 1.002 sendto(3, "{strace_escape(framed)}", {len(framed)}, '
                         f'0, {{sin_port=htons(50052), sin_addr=inet_addr("100.77.187.38")}}, 16) = {len(framed)}\n').encode()
        with self.assertRaisesRegex(ValueError, "connect provenance"):
            network_reduce.reduce_capture(self._exec() + unprovenanced, client_pid=999,
                                          server_endpoint="100.77.187.38:50052",
                                          payloads=[identity], client_argv=CLIENT_ARGV)
        # PID/TID prefix mandatory.
        with self.assertRaisesRegex(ValueError, "PID/TID prefix"):
            network_reduce.reduce_capture(base + complete.replace(b"1001 ", b"", 1), client_pid=999,
                                          server_endpoint="100.77.187.38:50052",
                                          payloads=[identity], client_argv=CLIENT_ARGV)
        # Zero-claim derivation: control-only traffic is fine.
        control_only = (base + b'999 1.010 sendto(3, "control", 7, 0, NULL, 0) = 7\n')
        out = network_reduce.reduce_capture(control_only, client_pid=999,
                                            server_endpoint="100.77.187.38:50052",
                                            payloads=[identity], client_argv=CLIENT_ARGV)
        self.assertEqual(out["immutable_payload_bytes"], 0)
        self.assertEqual(out["client_to_server_bytes"], 7)


class AssemblerClosureTests(unittest.TestCase):
    """Review items 17/18: every acceptance-significant external input the
    assembler consumes must be retained under the evidence tree + MANIFEST,
    and the retained raw evidence alone (run-summary withheld) must
    re-derive the terminal."""

    EVIDENCE = ROOT / proof.AREA / "evidence"

    def test_assembler_consumes_no_unretained_external_input(self):
        """Closure gate: grep the assembler source for path/string inputs;
        every non-repo input must be under the retained raw tree."""
        import ast
        source = (ROOT / "scripts/issue200_r8f_phase5_assemble.py").read_text()
        tree = ast.parse(source)
        external_roots = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                    and node.func.id == "Path" and node.args:
                arg = node.args[0]
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    external_roots.add(arg.value)
        # Only the fleet-run root may be external, and every acceptance-
        # significant file under it must be copied into the committed tree.
        self.assertEqual(external_roots, {"/tmp/issue200-p5c3-evidence"},
                         f"assembler consumes unexpected external input roots: {external_roots}")
        # Every raw receipt the assembler copies must exist under the
        # retained evidence tree and be covered by MANIFEST.sha256.
        raw_dir = self.EVIDENCE / "physical-phase5-raw"
        manifest = {}
        for line in (self.EVIDENCE / "MANIFEST.sha256").read_text().splitlines():
            digest, _, path = line.partition("  ")
            manifest[path.strip()] = digest
        for retained in sorted(raw_dir.rglob("*")):
            if not retained.is_file():
                continue
            rel = str(retained.relative_to(ROOT))
            self.assertIn(rel, manifest, f"retained raw evidence not in MANIFEST: {rel}")
            self.assertEqual(manifest[rel], sha(retained), f"MANIFEST digest mismatch: {rel}")
        # The fleet-run root itself must NOT be a terminal input: the run
        # summary is retained retention-only, and the producer source is
        # committed and retained.
        self.assertTrue((raw_dir / "run-summary.json").is_file(),
                        "orchestrator run summary must be retained byte-for-byte")
        self.assertTrue((raw_dir / "issue200_r8f_phase5_orchestrator.py").is_file(),
                        "orchestrator producer source must be retained byte-for-byte")
        committed = (ROOT / "scripts/issue200_r8f_phase5_orchestrator.py").read_bytes()
        self.assertEqual(committed, (raw_dir / "issue200_r8f_phase5_orchestrator.py").read_bytes(),
                         "retained orchestrator differs from the committed producer")

    def test_terminal_survives_run_summary_withheld(self):
        """Review item 18: deleting the retained run-summary.json (and every
        reference to it) must NOT change the terminal — the retained raw
        evidence alone re-derives it."""
        doc = json.loads((self.EVIDENCE / "physical-phase5.json").read_text())
        doc.pop("run_summary_retained", None)
        with tempfile.TemporaryDirectory() as td:
            scratch = Path(td) / "evidence"
            import shutil
            shutil.copytree(self.EVIDENCE, scratch)
            (scratch / "physical-phase5-raw" / "run-summary.json").unlink()
            target = scratch / "physical-phase5.json"
            target.write_bytes(json.dumps(doc).encode())
            validation = physical.validate_physical_evidence(doc, evidence_root=scratch)
            self.assertTrue(validation["valid"],
                            f"raw evidence alone must re-derive the terminal; got: {validation.get('reason')}")
            with mock.patch.object(cache_mechanism, "mechanical_cache_finding",
                                   return_value=valid_cache_finding()):
                document, _ = reduction.reduce_terminal(physical_phase5_evidence_path=target)
        self.assertEqual(document["terminal"], reduction.TERMINAL_LOCAL_VERIFIED_BACKING_PASS)


if __name__ == "__main__":
    unittest.main()
