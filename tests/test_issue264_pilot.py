"""CPU-only contracts for the bounded #264 MMV pilot and byte report."""
from __future__ import annotations
import hashlib, json, sys, tempfile, unittest
from datetime import datetime, timezone
from pathlib import Path
REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
import issue264_pilot as P
import issue264_report as R

def sha(b): return hashlib.sha256(b).hexdigest()
def utc(value):
    parsed=datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo != timezone.utc: raise AssertionError("timestamp must be UTC")
    return parsed
def retained_skeleton(parent: Path):
    unit=parent/"BASE"/"unit-001";unit.mkdir(parents=True)
    names={"request.json","response.json.raw","server.log","obs.meta.json","identity-pre.json","identity-post.json","markers.json","unit.json",*(f"obs.row{i}.f32" for i in range(8))}
    for name in names:(unit/name).write_bytes(b"test")
    hashes={name:sha((unit/name).read_bytes()) for name in names}
    (unit/"files.sha256.json").write_text(json.dumps(hashes))
    return unit

class PilotContracts(unittest.TestCase):
    def test_only_two_public_arms_and_one_factor(self):
        self.assertEqual(set(P.ARM_ENV), {"BASE", "H5_MMV_CANDIDATE"})
        self.assertEqual(P.ARM_ENV["BASE"], {})
        self.assertEqual(P.ARM_ENV["H5_MMV_CANDIDATE"], {"GGML_VK_I264_MMV":"large"})
        with self.assertRaises(P.PilotError): P.launch_env("A1", Path("obs"))

    def test_launch_environment_is_allowlisted_and_exact(self):
        env=P.launch_env("BASE", Path("/retained/obs"))
        self.assertEqual(env["CUDA_VISIBLE_DEVICES"], "-1")
        self.assertEqual(env["VK_ICD_FILENAMES"], "/usr/share/vulkan/icd.d/nvidia_icd.json")
        self.assertEqual(env["GGML_VK_VISIBLE_DEVICES"], "0")
        self.assertEqual(env["GGML_VK_I264_MMV"], "base")
        self.assertFalse(any(k.startswith("GGML_VK_DISABLE") for k in env))
        self.assertEqual(env["PATH"], "/usr/bin:/bin")

    def test_runtime_identity_cannot_be_substituted_by_caller(self):
        self.assertNotIn("authority", P.run_unit.__annotations__)
        self.assertNotIn("prompt", P.run_unit.__annotations__)
        self.assertNotIn("identity", P.run_unit.__annotations__)
        self.assertNotIn("authority", P.run_arm.__annotations__)
        self.assertNotIn("prompt", P.run_arm.__annotations__)

    def test_report_rejects_empty_or_unretained_roots(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(P.PilotError): R.build_report(Path(tmp))

    def test_row_comparison_is_full_vocabulary_descriptive_not_causal(self):
        import struct
        a={"unit_index":1,"row_bytes":[struct.pack("<3f",1,2,3)],"response_raw":b'{"tokens":[1]}'}
        b={"unit_index":2,"row_bytes":[struct.pack("<3f",1,4,3)],"response_raw":b'{"tokens":[1]}'}
        comparison=R.compare_rows(a,b)
        self.assertEqual(comparison["max_abs_finite_difference_by_position"],[2.0])
        self.assertEqual(comparison["argmax_equal_by_position"],[False])
        self.assertFalse(comparison["all_rows_equal"])

    def test_report_rejects_illegal_three_unit_mismatch_prefix(self):
        from unittest import mock
        with mock.patch.object(P,"load_execution_context",return_value={"expected_head":"a"*40}), mock.patch.object(P,"load_completed_units",return_value=[{"unit_index":i,"row_digest":str(i)} for i in (1,2,3)]):
            with self.assertRaisesRegex(P.PilotError,"screening prefix"):
                R.build_report(Path("/unused"))

    def test_retained_restart_refuses_modified_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);unit=retained_skeleton(root)
            (unit/"server.log").write_bytes(b"tampered")
            with self.assertRaisesRegex(P.PilotError,"hash mismatch"):
                P.load_completed_units(root,"BASE")

    def test_retained_restart_refuses_orphan_staging(self):
        with tempfile.TemporaryDirectory() as tmp:
            staging=Path(tmp)/"BASE"/".unit-001.staging";staging.mkdir(parents=True)
            with self.assertRaises(P.PilotError):P.load_completed_units(Path(tmp),"BASE")

    def test_screening_repeat_law_stops_at_first_mismatch(self):
        units=[{"row_digest":"a"},{"row_digest":"b"},{"row_digest":"b"}]
        self.assertEqual(P.screen_class(units),"screening-variable")
        self.assertEqual(P.screen_class([{"row_digest":"a"},{"row_digest":"a"}]),"matching-prefix")
        self.assertEqual(P.screen_class([{"row_digest":"a"},{"row_digest":"a"},{"row_digest":"b"}]),"screening-variable")
        self.assertEqual(P.screen_class([{"row_digest":"a"}]*3),"screening-stable")

    def test_markers_validate_resolved_arm_name_not_environment_value(self):
        raw=b"".join((f"ggml_vk_i262:v1|route|id={i}|graph={i}|weight=output.weight|node=n|side=0|route=mat-vec|pipe=mul_mat_vec_q4_k_f32_f32|family=mmv|quant_y=0|split_k=0|64b=0|dims=2560x248320:2560x1->248320x1|types=q4_K*f32->f32\n"
                     f"ggml_vk_i264:v1|mmv|id={i}|node=n|weight=output.weight|state=large|route=mat-vec|pipe=mul_mat_vec_q4_k_f32_f32|wg=large|reduction=hybrid|local=128x1x1|dims=2560x248320:2560x1->248320x1|types=q4_K*f32->f32|quant_y=0|split_k=0|64b=0\n").encode() for i in range(1,11))
        parsed=P.parse_unit_markers(raw,"H5_MMV_CANDIDATE")
        self.assertEqual(parsed["variant"],"large")
        with self.assertRaises(P.PilotError):P.parse_unit_markers(raw,"large")

    def test_observer_rejects_truncated_rows_and_metadata(self):
        import issue250_diagnostic as D
        metadata=b"".join((json.dumps({"pos":i,"sampled_winner":i+1,"forced_token":-1,"n_vocab":D.N_VOCAB})+"\n").encode() for i in range(D.DECISIONS))
        rows=[bytes(D.ROW_BYTES) for _ in range(D.DECISIONS)]
        P._validate_observer(metadata,rows)
        with self.assertRaisesRegex(P.PilotError,"geometry"):
            P._validate_observer(metadata,rows[:-1]+[bytes(D.ROW_BYTES-1)])
        with self.assertRaisesRegex(P.PilotError,"metadata"):
            P._validate_observer(metadata+b"{}\n",rows)

    def test_observer_and_response_reject_wrong_vocabulary_and_short_completion(self):
        import issue250_diagnostic as D
        rows=[bytes(D.ROW_BYTES) for _ in range(D.DECISIONS)]
        records=[{"pos":i,"sampled_winner":i+1,"forced_token":-1,"n_vocab":D.N_VOCAB} for i in range(8)]
        response=json.dumps({"tokens":list(range(1,9)),"tokens_predicted":8,"content":"fixture"}).encode()
        def meta(): return b"".join((json.dumps(r)+"\n").encode() for r in records)
        P._validate_observer(meta(),rows,response)
        for key,value in (("sampled_winner",True),("n_vocab",D.N_VOCAB-1),("forced_token","-1")):
            old=records[0][key];records[0][key]=value
            with self.assertRaisesRegex(P.PilotError,"metadata"):P._validate_observer(meta(),rows,response)
            records[0][key]=old
        records[0]["unexpected"]="not emitted by the retained #262 observer"
        with self.assertRaisesRegex(P.PilotError,"metadata"):P._validate_observer(meta(),rows,response)
        del records[0]["unexpected"]
        for bad in ({"tokens":[1]*7,"tokens_predicted":8}, {"tokens":list(range(1,9)),"tokens_predicted":7}, {"tokens":list(range(1,8))+[9],"tokens_predicted":8}):
            with self.assertRaisesRegex(P.PilotError,"response"):
                P._validate_observer(meta(),rows,json.dumps(bad).encode())

    def test_source_patch_and_working_tree_drift_are_not_caller_claims(self):
        from unittest import mock
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/"source";source.mkdir()
            (source/"ggml/src/ggml-vulkan").mkdir(parents=True)
            (source/P.S264.VK).write_bytes(b"fixture")
            with mock.patch.object(P.S264,"PATCH",root/"wrong.patch"):
                with self.assertRaisesRegex(P.PilotError,"patch"):
                    P.source_closure(source)
            with mock.patch.object(P.S264,"authenticate",return_value="0"*40), mock.patch.object(P,"SOURCE_VK_SHA",sha(b"fixture")):
                with self.assertRaisesRegex(P.PilotError,"tree"):
                    P.source_closure(source)

    def test_placement_uses_accepted_parser_and_rejects_second_device(self):
        from tests.test_issue254_round5 import TWO_ENUM_LOG
        env=P.launch_env("BASE",Path("/tmp/obs"));argv=P.launch_argv(Path("/tmp/binary"))
        self.assertNotIn("enumeration_line",P.placement_from_log(b"no banner\n",env,argv))
        with self.assertRaisesRegex(P.PilotError,"second|more than one"):
            P.placement_from_log(TWO_ENUM_LOG.encode(),env,argv)
        env["CUDA_VISIBLE_DEVICES"]="0"
        with self.assertRaisesRegex(P.PilotError,"CUDA"):
            P.placement_from_log(b"no banner",env,argv)

    def test_publication_preserves_matching_staged_raw_bytes_and_rejects_bad_bytes(self):
        from unittest import mock
        raw=b"already collected raw bytes"
        record={"request_raw":raw,"response_raw":b"response","server_log":b"log",
                "observer_meta":b"meta","identity_pre":{},"identity_post":{},
                "markers":{},"observer_rows":[b"row"]}
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);stage=root/"stage";target=root/"unit";stage.mkdir()
            (stage/"request.json").write_bytes(raw)
            with mock.patch.object(P.os,"fsync"):
                P.publish_unit(stage,target,record)
            self.assertEqual((target/"request.json").read_bytes(),raw)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);stage=root/"stage";target=root/"unit";stage.mkdir()
            (stage/"request.json").write_bytes(b"different")
            with self.assertRaisesRegex(P.PilotError,"staged bytes differ"):
                P.publish_unit(stage,target,record)

    def test_missing_controller_build_identity_fails_before_binary_use(self):
        from unittest import mock
        with tempfile.TemporaryDirectory() as tmp:
            missing=Path(tmp)/"not-yet-written-build-identity.json"
            with mock.patch.object(P,"BUILD_IDENTITY",missing):
                with self.assertRaisesRegex(P.PilotError,"build identity absent"):
                    P.verify_source_and_binary(Path("/not-used/llama-server"))

    def test_execution_context_required_and_freezes_self_consistent_head(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            with self.assertRaisesRegex(P.PilotError,"execution context"):
                P.load_execution_context(root)

    def test_execution_context_is_create_only_and_binds_facts(self):
        from unittest import mock
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); evidence=root/"evidence"; evidence.mkdir()
            with mock.patch.object(P, "git", side_effect=["a"*40, "a"*40, "", "", "issue-264-h5-mmv", "", "issue-264-h5-mmv"]), \
                 mock.patch.object(P, "api", side_effect=[{"state":"open","body":P.PILOT_CLAUSE}, [{"number":999,"state":"open","merged":False,"draft":False,"head":{"ref":"issue-264-h5-mmv","sha":"a"*40},"base":{"ref":"issue-254-r8i3c-producer"}}]]), \
                 mock.patch.object(P, "verify_source_and_binary", return_value=P.BINARY_SHA), \
                 mock.patch.object(P, "source_closure", return_value={"source_root":"inferswarm01:"+str(P.SOURCE_ROOT),"source_tree":P.SOURCE_TREE,"source_vk_sha256":P.SOURCE_VK_SHA,"source_patch_sha256":P.SOURCE_PATCH_SHA}), \
                 mock.patch.object(P, "model_stat_witness", return_value=[{"name":n,"device":1,"inode":2,"size":3,"mtime_ns":4,"ctime_ns":5} for n in P.C252.MODEL_MEMBERS]), \
                 mock.patch.object(P, "frozen_prompt", return_value="frozen"), \
                 mock.patch.object(P.B250, "verify_fixtures", return_value={"fixture":"frozen"}):
                context=P.prepare_execution(repo_root=root,evidence_root=evidence,binary=root/"llama-server")
            self.assertEqual(context["schema"],P.EXECUTION_SCHEMA)
            self.assertEqual(context["expected_head"],"a"*40)
            self.assertNotIn("execution_head",context)
            self.assertIn("binary_sha256",context)
            self.assertTrue((evidence/P.EXECUTION_CONTEXT_NAME).is_file())
            with self.assertRaisesRegex(P.PilotError,"already exists"):
                P.prepare_execution(repo_root=root,evidence_root=evidence,binary=root/"llama-server")

    def test_verify_authority_rejects_head_movement(self):
        from unittest import mock
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); context={"expected_head":"a"*40}
            with mock.patch.object(P,"git",return_value="b"*40):
                with self.assertRaisesRegex(P.PilotError,"HEAD"):
                    P.verify_authority(root,context)

    def test_execution_freeze_rejects_changed_model_stats_and_request(self):
        context={"source_tree":P.SOURCE_TREE,"source_vk_sha256":P.SOURCE_VK_SHA,"source_closure":{"source_root":"inferswarm01:"+str(P.SOURCE_ROOT),"source_tree":P.SOURCE_TREE,"source_vk_sha256":P.SOURCE_VK_SHA,"source_patch_sha256":P.SOURCE_PATCH_SHA},"binary_sha256":P.BINARY_SHA,"fixture_payload_sha256":"payload","fixture_sha256":"fixture","model_stats":[{"inode":1}]}
        with self.assertRaisesRegex(P.PilotError,"model stat"):
            P.validate_execution_freeze(context,binary_sha=P.BINARY_SHA,payload_sha="payload",fixture_sha="fixture",model_stats=[{"inode":2}])
        with self.assertRaisesRegex(P.PilotError,"fixture/request"):
            P.validate_execution_freeze(context,binary_sha=P.BINARY_SHA,payload_sha="changed",fixture_sha="fixture",model_stats=[{"inode":1}])

    def test_build_identity_contract_does_not_require_execution_head(self):
        from unittest import mock
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); source=root/"source.json"; build=root/"build.json"; binary=root/"llama-server"
            source.write_text(json.dumps({"issue264_tree":P.SOURCE_TREE,"issue264_vk_sha256":P.SOURCE_VK_SHA,"patch_sha256":P.SOURCE_PATCH_SHA}))
            identity={"schema":P.BUILD_SCHEMA,"source_tree":P.SOURCE_TREE,"source_vk_sha256":P.SOURCE_VK_SHA,"binary_sha256":P.BINARY_SHA,"binary_path":"inferswarm01:/home/hermes/is264-mmv-v2/build-i264/bin/llama-server","version":"0.4.1-dev","build_number":10964,"predecessor_commit":"b29c606e28a01b1bc8c1351026a0fa6e616bf6c4","compiler":"GNU 14.2.0","gpu_applications_during_build":[]}
            build.write_text(json.dumps(identity));binary.write_bytes(b"verified-by-test")
            self.assertNotIn("execution_head",identity)
            with mock.patch.object(P,"IDENTITY_PATH",source), mock.patch.object(P,"BUILD_IDENTITY",build), mock.patch.object(P,"sha",side_effect=lambda data: P.BINARY_SHA if data==b"verified-by-test" else hashlib.sha256(data).hexdigest()):
                self.assertEqual(P.verify_source_and_binary(binary),P.BINARY_SHA)

    def test_live_issue_must_retain_exact_conditional_pilot_clause(self):
        from unittest import mock
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            with mock.patch.object(P,"git",side_effect=["a"*40,"", "", "issue-264-h5-mmv"]), mock.patch.object(P,"api",return_value={"state":"open","body":"issue remains open but pilot condition removed"}):
                with self.assertRaisesRegex(P.PilotError,"conditional pilot clause"):
                    P.verify_authority(root,{"expected_head":"a"*40})

class RealSubprocessPilotRegression(unittest.TestCase):
    """Synthetic CPU fixture: real child, HTTP, /proc, custody and reducer.

    This is not a physical GPU observation or inference result.
    """

    def test_occupied_fixed_port_refuses_launch_and_never_posts_to_unrelated_listener(self):
        from http.server import BaseHTTPRequestHandler, HTTPServer
        from threading import Thread
        from unittest import mock

        posts=[]
        class Unrelated(BaseHTTPRequestHandler):
            def log_message(self, format, *args): pass
            def do_GET(self):
                self.send_response(200);self.end_headers()
            def do_POST(self):
                posts.append(self.rfile.read(int(self.headers["Content-Length"])))
                self.send_response(200);self.end_headers()

        with HTTPServer(("127.0.0.1",19000),Unrelated) as server, tempfile.TemporaryDirectory() as tmp:
            thread=Thread(target=server.serve_forever,daemon=True);thread.start()
            root=Path(tmp);evidence=root/"evidence";evidence.mkdir()
            sleeper=root/"not-a-server.py";sleeper.write_text("import time; time.sleep(30)\n")
            context={"schema":P.EXECUTION_SCHEMA,"expected_head":"a"*40,"source_closure":{}}
            real_popen=P.subprocess.Popen
            with mock.patch.object(P,"load_execution_context",return_value=context), \
                 mock.patch.object(P,"verify_authority"), \
                 mock.patch.object(P,"verify_source_and_binary",return_value=P.BINARY_SHA), \
                 mock.patch.object(P,"source_closure",return_value={}), \
                 mock.patch.object(P.B250,"verify_fixtures",return_value={}), \
                 mock.patch.object(P,"frozen_prompt",return_value="fixture"), \
                 mock.patch.object(P,"model_stat_witness",return_value=[]), \
                 mock.patch.object(P,"validate_execution_freeze"), \
                 mock.patch.object(P,"observe_subject",return_value={}), \
                 mock.patch.object(P.I248,"observe_arm_identity",return_value={}), \
                 mock.patch.object(P.I248,"identity_problems",return_value=[]), \
                 mock.patch.object(P,"load_completed_units",return_value=[]), \
                 mock.patch.object(P,"launch_argv",return_value=[sys.executable,str(sleeper)]), \
                 mock.patch.object(P.subprocess,"Popen",wraps=real_popen) as launched:
                with self.assertRaisesRegex(P.PilotError,"port|listener|occupied"):
                    P.run_unit(repo_root=REPO,evidence_root=evidence,arm="BASE",binary=sleeper,unit_index=1,timeout_s=3)
                self.assertEqual(launched.call_count,0)
            self.assertEqual(posts,[])
            self.assertTrue(thread.is_alive())
            self.assertFalse((evidence/"BASE/.unit-001.staging").exists())
            server.shutdown();thread.join(timeout=3)

    def test_health_200_from_unrelated_listener_is_not_child_health(self):
        from http.server import BaseHTTPRequestHandler, HTTPServer
        from threading import Thread
        import subprocess

        class Unrelated(BaseHTTPRequestHandler):
            def log_message(self, format, *args): pass
            def do_GET(self):
                self.send_response(200);self.end_headers()
        with HTTPServer(("127.0.0.1",19000),Unrelated) as server:
            thread=Thread(target=server.serve_forever,daemon=True);thread.start()
            proc=subprocess.Popen([sys.executable,"-c","import time;time.sleep(30)"],start_new_session=True)
            try:
                with self.assertRaisesRegex(P.PilotError,"listener|owned"):
                    P._healthy(proc,2)
            finally:
                P._stop(proc);server.shutdown();thread.join(timeout=3)

    def test_listener_disappearing_after_health_refuses_completion(self):
        import subprocess
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);script=root/"one-health.py";posted=root/"posted"
            script.write_text('''import sys,time
from http.server import BaseHTTPRequestHandler,HTTPServer
class Handler(BaseHTTPRequestHandler):
 def log_message(self,format,*args):pass
 def do_GET(self):
  self.server.server_close()
  self.send_response(200);self.end_headers();self.wfile.flush()
 def do_POST(self):
  open(sys.argv[1],"w").write("unexpected")
server=HTTPServer(("127.0.0.1",19000),Handler)
server.handle_request();time.sleep(30)
''')
            proc=subprocess.Popen([sys.executable,str(script),str(posted)],start_new_session=True)
            try:
                with self.assertRaisesRegex(P.PilotError,"disappeared|exited"):
                    P._healthy(proc,5)
                self.assertFalse(posted.exists())
            finally:P._stop(proc)

    def test_two_arms_execute_retain_replay_and_report_real_subprocesses(self):
        from unittest import mock
        from tests.test_issue248_diagnostic import CENSUS_RAW_B
        import issue250_diagnostic as D

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            evidence = root / "synthetic-CPU-fixture-NOT-physical"
            binary = root / "fixture_server.py"
            # An explicit interpreter makes /proc/<pid>/cmdline identical to
            # launch_argv; a shebang/env wrapper does not.
            binary.write_text('''import json, os, sys
from http.server import BaseHTTPRequestHandler, HTTPServer
out = os.environ["LLAMA_OBSERVE_OUT"]
state = os.environ["GGML_VK_I264_MMV"]
variant = {"base": ("subgroup", "subgroup", 32), "large": ("large", "hybrid", 128)}[state]
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args): pass
    def do_GET(self):
        self.send_response(200 if self.path == "/health" else 404)
        self.end_headers()
    def do_POST(self):
        if self.path != "/completion":
            self.send_error(404); return
        request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        assert request["prompt"] and os.environ["LLAMA_OBSERVE_CAPTURE"] == "8"
        index = int(out.rsplit("unit-", 1)[1][:3])
        with open(out + ".meta.json", "w") as f:
            for i in range(8): f.write(json.dumps({"pos": i, "sampled_winner": i+1, "forced_token": -1, "n_vocab": N_VOCAB if "failure" not in out else 1}) + "\\n")
        for i in range(8):
            with open(out + ".row%%d.f32" %% i, "wb") as f:
                f.write(bytes([index, i]) + bytes(ROW_BYTES - 2))
        for i in range(1, 11):
            print(f"ggml_vk_i262:v1|route|id={i}|graph={i}|weight=output.weight|node=result.output|side=0|route=mat-vec|pipe=mul_mat_vec_q4_k_f32_f32|family=mmv|quant_y=0|split_k=0|64b=0|dims=2560x248320:2560x1->248320x1|types=q4_K*f32->f32", flush=True)
            print(f"ggml_vk_i264:v1|mmv|id={i}|node=result.output|weight=output.weight|state={state}|route=mat-vec|pipe=mul_mat_vec_q4_k_f32_f32|wg={variant[0]}|reduction={variant[1]}|local={variant[2]}x1x1|dims=2560x248320:2560x1->248320x1|types=q4_K*f32->f32|quant_y=0|split_k=0|64b=0", flush=True)
        if "timeout" in out:
            import time
            time.sleep(5)
        body = json.dumps({"tokens": [1,2,3,4,5,6,7,8], "tokens_predicted": 8, "content": "synthetic CPU fixture"}).encode()
        self.send_response(200); self.send_header("Content-Length", str(len(body)))
        self.end_headers(); self.wfile.write(body)
ROW_BYTES = %d
N_VOCAB = %d
HTTPServer(("127.0.0.1", int(sys.argv[sys.argv.index("--port") + 1])), Handler).serve_forever()
''' % (D.ROW_BYTES,D.N_VOCAB))
            head = "a" * 40
            issue = {"state": "open", "body": P.PILOT_CLAUSE}
            pr = {"number": 999, "state": "open", "merged": False,
                  "draft": False, "head": {"ref": "issue-264-h5-mmv", "sha": head},
                  "base": {"ref": "issue-254-r8i3c-producer"}}
            def offline_git(repo, *args):
                if args == ("rev-parse", "HEAD"): return head
                if args == ("symbolic-ref", "--short", "HEAD"): return "issue-264-h5-mmv"
                if args in (("status", "--porcelain", "--untracked-files=all"),
                            ("merge-base", "--is-ancestor", P.BASE_HEAD, head)): return ""
                raise AssertionError(args)
            def offline_api(path):
                if path == "issues/264": return issue
                if path == "pulls?state=all&per_page=100": return [pr]
                raise AssertionError(path)
            def witness():
                return [{"name": name, "device": 1, "inode": i + 1,
                         "size": 3, "mtime_ns": 4, "ctime_ns": 5}
                        for i, name in enumerate(P.C252.MODEL_MEMBERS)]
            observation = {"schema": P.I248.IDENTITY_SCHEMA, "arm": "B", "raw": CENSUS_RAW_B}
            self.assertEqual(P.I248.identity_problems("B", observation), [])
            terminated = []
            stop = P._stop
            def checked_stop(proc):
                stop(proc)
                terminated.append(proc.pid)
                self.assertIsNotNone(proc.poll())
                self.assertFalse(Path(f"/proc/{proc.pid}").exists())
            # Only unavailable physical-host and GitHub facts are doubled;
            # the fixture ladder, process, HTTP, /proc, parser, custody,
            # retained reload and report remain production functions.
            with mock.patch.object(P, "git", side_effect=offline_git), \
                 mock.patch.object(P, "api", side_effect=offline_api), \
                 mock.patch.object(P, "verify_source_and_binary", return_value=P.BINARY_SHA), \
                 mock.patch.object(P, "source_closure", return_value={"source_root":"inferswarm01:"+str(P.SOURCE_ROOT),"source_tree":P.SOURCE_TREE,"source_vk_sha256":P.SOURCE_VK_SHA,"source_patch_sha256":P.SOURCE_PATCH_SHA}), \
                 mock.patch.object(P, "model_stat_witness", side_effect=witness), \
                 mock.patch.object(P, "observe_subject", return_value={
                     "gpu": "NVIDIA GeForce RTX 3060", **{
                         k: P.C252.HOST_FACTS[k] for k in ("gpu_uuid", "bdf", "driver")}}), \
                 mock.patch.object(P.I248, "observe_arm_identity", return_value=observation), \
                 mock.patch.object(P, "launch_argv", side_effect=lambda path: [
                     sys.executable, str(binary), "-ngl", "1", "--port", "19000"]), \
                 mock.patch.object(P, "_stop", side_effect=checked_stop):
                context = P.prepare_execution(repo_root=REPO, evidence_root=evidence, binary=binary)
                self.assertEqual(P.load_execution_context(evidence), context)
                stray=evidence/"unknown";stray.write_bytes(b"not pilot evidence")
                with self.assertRaisesRegex(P.PilotError,"unknown"):
                    P.run_unit(repo_root=REPO,evidence_root=evidence,arm="BASE",binary=binary,unit_index=1,timeout_s=15)
                stray.unlink()
                stray.symlink_to(binary)
                with self.assertRaisesRegex(P.PilotError,"symlink"):
                    P.run_unit(repo_root=REPO,evidence_root=evidence,arm="BASE",binary=binary,unit_index=1,timeout_s=15)
                stray.unlink()
                self.assertEqual(terminated,[])
                for arm in P.ARMS:
                    result = P.run_arm(repo_root=REPO, evidence_root=evidence,
                                       arm=arm, binary=binary, timeout_s=15)
                    self.assertEqual(result, {"arm": arm, "units": 2,
                                              "classification": "screening-variable"})
                    loaded = P.load_completed_units(evidence, arm)
                    self.assertEqual([u["unit_index"] for u in loaded], [1, 2])
                    self.assertNotEqual(loaded[0]["row_digest"], loaded[1]["row_digest"])
                    for u in loaded:
                        self.assertEqual(u["markers"]["marker_count"], 10)
                        self.assertLessEqual(utc(u["started_at"]),utc(u["completed_at"]))
                        self.assertEqual(u["execution_context_sha256"],P.sha(P.canonical(context)))
                        self.assertEqual(u["argv"], [sys.executable, str(binary), "-ngl", "1", "--port", "19000"])
                    self.assertEqual(P.run_arm(repo_root=REPO, evidence_root=evidence,
                                               arm=arm, binary=binary, timeout_s=15), result)
                report = R.build_report(evidence)
                self.assertEqual(report["all_unit_pair_count"], 4)
                self.assertEqual(report["paired_path_transition"]["variants"], ["subgroup", "large"])
                self.assertEqual(report["evidence_preservation"]["status"],"external-pending")
                self.assertEqual(report["evidence_preservation"]["expected_file_count"],150)
                self.assertEqual(report["evidence_preservation"]["expected_inventory_sha256"],"806160f67aeff84d2b4d1531d65e582cd7e599cdf601aad877d70f83924f6038")
                self.assertEqual(report["arms"]["BASE"]["units"][0]["response"]["tokens_predicted"],8)
                self.assertEqual(len(report["arms"]["BASE"]["units"][0]["rows"]),8)
                self.assertEqual(len(report["row_comparisons"]["across_arms"]),4)
                self.assertTrue(report["row_comparisons"]["across_arms"][0]["all_rows_equal"])
                self.assertEqual(report["h5_discriminator"]["status"],"path-transition-only")
                self.assertEqual({a: v["classification"] for a, v in report["arms"].items()},
                                 {"BASE": "screening-variable", "H5_MMV_CANDIDATE": "screening-variable"})
                failed=root/"failure-CPU-fixture-NOT-physical"
                P.prepare_execution(repo_root=REPO,evidence_root=failed,binary=binary)
                with self.assertRaisesRegex(P.PilotError,"metadata"):
                    P.run_unit(repo_root=REPO,evidence_root=failed,arm="BASE",binary=binary,unit_index=1,timeout_s=15)
                attempt=json.loads((failed/"attempts/BASE-001.failed.json").read_bytes())
                self.assertEqual(attempt["phase"],"observer")
                stage=failed/"BASE/.unit-001.staging"
                self.assertEqual(attempt["staging_files"]["obs.meta.json"],sha((stage/"obs.meta.json").read_bytes()))
                self.assertEqual(attempt["process_exit"]["cleanup_verified"],True)
                self.assertLessEqual(utc(attempt["started_at"]),utc(attempt["ended_at"]))
                with self.assertRaisesRegex(P.PilotError,"orphan|failed"):
                    P.run_unit(repo_root=REPO,evidence_root=failed,arm="BASE",binary=binary,unit_index=1,timeout_s=15)
                timeout_root=root/"timeout-CPU-fixture-NOT-physical"
                P.prepare_execution(repo_root=REPO,evidence_root=timeout_root,binary=binary)
                with self.assertRaises(TimeoutError):
                    P.run_unit(repo_root=REPO,evidence_root=timeout_root,arm="BASE",binary=binary,unit_index=1,timeout_s=2)
                timeout_attempt=json.loads((timeout_root/"attempts/BASE-001.failed.json").read_bytes())
                self.assertEqual(timeout_attempt["phase"],"completion")
                self.assertEqual(timeout_attempt["process_exit"]["cleanup_verified"],True)
                self.assertIn("server.log",timeout_attempt["staging_files"])
                self.assertLessEqual(utc(timeout_attempt["started_at"]),utc(timeout_attempt["ended_at"]))
                authority_root=root/"authority-CPU-fixture-NOT-physical"
                P.prepare_execution(repo_root=REPO,evidence_root=authority_root,binary=binary)
                authority_calls=0
                original_authority=P.verify_authority
                def revoke_final(repo,ctx):
                    nonlocal authority_calls
                    authority_calls+=1
                    if authority_calls==3: raise P.PilotError("final commit authority revoked")
                    return original_authority(repo,ctx)
                with mock.patch.object(P,"verify_authority",side_effect=revoke_final):
                    with self.assertRaisesRegex(P.PilotError,"final commit authority revoked"):
                        P.run_unit(repo_root=REPO,evidence_root=authority_root,arm="BASE",binary=binary,unit_index=1,timeout_s=15)
                self.assertEqual(authority_calls,3)
                self.assertFalse((authority_root/"BASE/unit-001").exists())
                authority_stage=authority_root/"BASE/.unit-001.staging"
                self.assertTrue((authority_stage/"response.json.raw").is_file())
                authority_receipt=json.loads((authority_root/"attempts/BASE-001.failed.json").read_bytes())
                self.assertEqual(authority_receipt["staging_files"]["response.json.raw"],sha((authority_stage/"response.json.raw").read_bytes()))
                self.assertEqual(authority_receipt["execution_context_sha256"],P.sha(P.canonical(context)))
                self.assertIsInstance(authority_receipt["pid"],int)
                self.assertTrue(authority_receipt["process_exit"]["cleanup_verified"])
                self.assertLessEqual(utc(authority_receipt["started_at"]),utc(authority_receipt["ended_at"]))
                with self.assertRaisesRegex(P.PilotError,"orphan|failed"):
                    P.run_unit(repo_root=REPO,evidence_root=authority_root,arm="BASE",binary=binary,unit_index=1,timeout_s=15)
                rename_root=root/"rename-CPU-fixture-NOT-physical"
                P.prepare_execution(repo_root=REPO,evidence_root=rename_root,binary=binary)
                target=rename_root/"BASE/unit-001"
                original_fsync=P.os.fsync
                def fail_parent_sync(fd):
                    if target.is_dir() and Path(f"/proc/self/fd/{fd}").resolve()==target.parent:
                        raise OSError("parent fsync after rename")
                    return original_fsync(fd)
                with mock.patch.object(P.os,"fsync",side_effect=fail_parent_sync):
                    with self.assertRaisesRegex(OSError,"parent fsync after rename"):
                        P.run_unit(repo_root=REPO,evidence_root=rename_root,arm="BASE",binary=binary,unit_index=1,timeout_s=15)
                self.assertFalse((rename_root/"BASE/.unit-001.staging").exists())
                receipt=json.loads((rename_root/"attempts/BASE-001.failed.json").read_bytes())
                self.assertEqual(receipt["staging_path"],"BASE/unit-001")
                self.assertEqual(receipt["staging_files"],{p.name:sha(p.read_bytes()) for p in target.iterdir()})
                self.assertEqual(receipt["execution_context_sha256"],P.sha(P.canonical(context)))
                self.assertIsInstance(receipt["pid"],int)
                self.assertTrue(receipt["process_exit"]["cleanup_verified"])
                self.assertLessEqual(utc(receipt["started_at"]),utc(receipt["ended_at"]))
                with self.assertRaisesRegex(P.PilotError,"failed"):
                    P.run_unit(repo_root=REPO,evidence_root=rename_root,arm="BASE",binary=binary,unit_index=2,timeout_s=15)
                # Reader re-derives semantics even if a local actor updates
                # both the unit digest and file manifest after publication.
                tampered=evidence/"BASE/unit-001"
                response_path=tampered/"response.json.raw"
                response=json.loads(response_path.read_bytes());response["tokens_predicted"]=7
                response_path.write_bytes(json.dumps(response).encode())
                unit_path=tampered/"unit.json";unit=json.loads(unit_path.read_bytes())
                unit["response_sha256"]=sha(response_path.read_bytes())
                unit_path.write_bytes(json.dumps(unit).encode())
                manifest_path=tampered/"files.sha256.json";manifest=json.loads(manifest_path.read_bytes())
                for name in ("response.json.raw","unit.json"):
                    manifest[name]=sha((tampered/name).read_bytes())
                manifest_path.write_bytes(json.dumps(manifest).encode())
                with self.assertRaisesRegex(P.PilotError,"response"):
                    P.load_completed_units(evidence,"BASE")
            self.assertEqual(len(terminated), 8)
            self.assertEqual(len(set(terminated)), 8)
            self.assertFalse(any(evidence.rglob("*.staging")))

if __name__ == "__main__": unittest.main()
