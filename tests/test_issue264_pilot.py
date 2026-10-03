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
        self.assertEqual(P.screen_class([{"row_digest":"a"}]*3),"screening-stable")

    def test_missing_controller_build_identity_fails_before_binary_use(self):
        with self.assertRaisesRegex(P.PilotError,"build identity absent"):
            P.verify_source_and_binary(Path("/not-used/llama-server"))

if __name__ == "__main__": unittest.main()
