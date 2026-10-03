"""CPU-only contracts for the bounded #264 MMV pilot and byte report."""
from __future__ import annotations
import hashlib, json, sys, tempfile, unittest
from pathlib import Path
REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
import issue264_pilot as P
import issue264_report as R

def sha(b): return hashlib.sha256(b).hexdigest()
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
        raw=(b"ggml_vk_i262:v1|route|id=1|graph=1|weight=output.weight|node=n|side=0|route=mat-vec|pipe=mul_mat_vec_q4_k_f32_f32|family=mmv|quant_y=0|split_k=0|64b=0|dims=2560x248320:2560x1->248320x1|types=q4_K*f32->f32\n"
             b"ggml_vk_i264:v1|mmv|id=1|node=n|weight=output.weight|state=large|route=mat-vec|pipe=mul_mat_vec_q4_k_f32_f32|wg=large|reduction=hybrid|local=128x1x1|dims=2560x248320:2560x1->248320x1|types=q4_K*f32->f32|quant_y=0|split_k=0|64b=0\n")
        parsed=P.parse_unit_markers(raw,"H5_MMV_CANDIDATE")
        self.assertEqual(parsed["variant"],"large")
        with self.assertRaises(P.PilotError):P.parse_unit_markers(raw,"large")

    def test_observer_rejects_truncated_rows_and_metadata(self):
        import issue250_diagnostic as D
        metadata=b"".join((json.dumps({"pos":i})+"\n").encode() for i in range(D.DECISIONS))
        rows=[bytes(D.ROW_BYTES) for _ in range(D.DECISIONS)]
        P._validate_observer(metadata,rows)
        with self.assertRaisesRegex(P.PilotError,"geometry"):
            P._validate_observer(metadata,rows[:-1]+[bytes(D.ROW_BYTES-1)])
        with self.assertRaisesRegex(P.PilotError,"metadata"):
            P._validate_observer(metadata+b"{}\n",rows)

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
        context={"source_tree":P.SOURCE_TREE,"source_vk_sha256":P.SOURCE_VK_SHA,"binary_sha256":P.BINARY_SHA,"fixture_payload_sha256":"payload","fixture_sha256":"fixture","model_stats":[{"inode":1}]}
        with self.assertRaisesRegex(P.PilotError,"model stat"):
            P.validate_execution_freeze(context,binary_sha=P.BINARY_SHA,payload_sha="payload",fixture_sha="fixture",model_stats=[{"inode":2}])
        with self.assertRaisesRegex(P.PilotError,"fixture/request"):
            P.validate_execution_freeze(context,binary_sha=P.BINARY_SHA,payload_sha="changed",fixture_sha="fixture",model_stats=[{"inode":1}])

    def test_build_identity_contract_does_not_require_execution_head(self):
        from unittest import mock
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); source=root/"source.json"; build=root/"build.json"; binary=root/"llama-server"
            source.write_text(json.dumps({"issue264_tree":P.SOURCE_TREE,"issue264_vk_sha256":P.SOURCE_VK_SHA}))
            identity={"schema":P.BUILD_SCHEMA,"source_tree":P.SOURCE_TREE,"source_vk_sha256":P.SOURCE_VK_SHA,"binary_sha256":P.BINARY_SHA,"binary_path":"inferswarm01:/home/hermes/is264-mmv-v2/build-i264/bin/llama-server","version":"0.4.1-dev","build_number":10964,"predecessor_commit":"b29c606e28a01b1bc8c1351026a0fa6e616bf6c4","compiler":"GNU 14.2.0","gpu_applications_during_build":[]}
            build.write_text(json.dumps(identity));binary.write_bytes(b"verified-by-test")
            self.assertNotIn("execution_head",identity)
            with mock.patch.object(P,"IDENTITY_PATH",source), mock.patch.object(P,"BUILD_IDENTITY",build), mock.patch.object(P,"sha",return_value=P.BINARY_SHA):
                self.assertEqual(P.verify_source_and_binary(binary),P.BINARY_SHA)

    def test_live_issue_must_retain_exact_conditional_pilot_clause(self):
        from unittest import mock
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            with mock.patch.object(P,"git",side_effect=["a"*40,"", "", "issue-264-h5-mmv"]), mock.patch.object(P,"api",return_value={"state":"open","body":"issue remains open but pilot condition removed"}):
                with self.assertRaisesRegex(P.PilotError,"conditional pilot clause"):
                    P.verify_authority(root,{"expected_head":"a"*40})

if __name__ == "__main__": unittest.main()
