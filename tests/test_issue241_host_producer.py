"""CPU-only host producer tests under the repository's unittest harness."""
from __future__ import annotations
import hashlib
import inspect
import tempfile
import unittest
from pathlib import Path
import sys
import json
import shutil
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import issue241_host_producer as producer
import issue241_dispatch as dispatch
import issue241_constants as C

AUTHORITY = {"schema": dispatch.AUTHORITY_SCHEMA, "head_sha": "a" * 40,
             "repository": dispatch.REPO, "issue_number": 241, "pr_number": 242,
             "pr_state": "open", "merged_at": None, "base_ref": "main",
             "comment_id": 1, "commenter": "maintainer",
             "commenter_association": "OWNER",
             "created_at": "2026-09-23T00:00:00Z",
             "dispatch_phrase": dispatch.DISPATCH_PHRASE}

class FakeRunner:
    def __init__(self, responses=None):
        self.responses = responses or {}
        self.calls = []
    def run(self, command, *, cwd=None, timeout=None):
        self.calls.append((list(command), cwd, timeout))
        return self.responses.get(tuple(command), (0, "", ""))

class HostProducerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_authority_required_before_runner_calls(self):
        runner = FakeRunner()
        with self.assertRaisesRegex(producer.ProducerError, "authority"):
            producer.collect_census(self.root, runner)
        self.assertEqual(runner.calls, [])

    def test_raw_command_receipt_has_sha256_and_rejects_symlink(self):
        runner = FakeRunner({("fixture",): (0, "raw out", "raw err")})
        result = producer.run_recorded(runner, ["fixture"], authority=AUTHORITY)
        self.assertEqual(result["stdout"], "raw out")
        self.assertEqual(result["stderr"], "raw err")
        self.assertEqual(result["stdout_sha256"], hashlib.sha256(b"raw out").hexdigest())
        p = self.root / "link"
        p.symlink_to(self.root / "missing")
        with self.assertRaisesRegex(producer.ProducerError, "symlink"):
            producer.require_regular_nonsymlink(p)

    def test_build_authority_and_patch_digest_checks(self):
        with self.assertRaisesRegex(producer.ProducerError, "authority"):
            producer.build_comparator(self.root, self.root / "missing", FakeRunner())
        self.assertTrue(producer.AUTHORITY_REQUIRED)

    def test_public_api_signatures(self):
        self.assertEqual(list(inspect.signature(producer.collect_census).parameters),
                         ["root", "runner", "authority", "out_dir"])
        self.assertEqual(list(inspect.signature(producer.build_comparator).parameters),
                         ["root", "r8e_patch", "runner", "authority"])

    def test_weak_dispatch_boolean_is_rejected_before_runner(self):
        runner = FakeRunner()
        with self.assertRaisesRegex(producer.ProducerError, "AUTHORITY_SCHEMA"):
            producer.run_recorded(runner, ["fixture"], authority={"dispatch": True})
        self.assertEqual(runner.calls, [])

    def test_wrong_exact_authority_schema_is_rejected_before_runner(self):
        runner = FakeRunner()
        with self.assertRaisesRegex(producer.ProducerError, "AUTHORITY_SCHEMA"):
            producer.run_recorded(runner, ["fixture"],
                                  authority={"schema": "other", "head_sha": "a" * 40})
        self.assertEqual(runner.calls, [])

    def test_incomplete_or_revoked_authority_rejected_before_runner(self):
        for authority in ({"schema": dispatch.AUTHORITY_SCHEMA, "head_sha": "a" * 40},
                          {**AUTHORITY, "pr_state": "closed"},
                          {**AUTHORITY, "commenter_association": "CONTRIBUTOR"},
                          {**AUTHORITY, "created_at": "not-a-time"}):
            runner = FakeRunner()
            with self.assertRaisesRegex(producer.ProducerError, "authority"):
                producer.run_recorded(runner, ["fixture"], authority=authority)
            self.assertEqual(runner.calls, [])

    def test_census_live_values_and_raw_before_derivation(self):
        class CensusRunner:
            def __init__(inner): inner.calls = []
            def run(inner, command, *, cwd=None, timeout=None):
                inner.calls.append(command)
                if len(inner.calls) > 1:
                    self.assertTrue(list((self.root / 'raw').glob('*.json')))
                joined = ' '.join(command)
                if command == ['hostname']: value = 'inferswarm01\n'
                elif command[:2] == ['lspci', '-Dnn'] and '-t' in command: value = 'PCI ancestry\n'
                elif command[:2] == ['lspci', '-Dnn']: value = ('0000:02:00.0 VGA compatible controller [0300]: AMD Ellesmere [1002:67df] (rev e7)\n'
                    '0000:03:00.0 VGA compatible controller [0300]: NVIDIA GA106 [10de:2504] (rev a1)\n')
                elif command[:2] == ['lspci', '-Dnnvv']: value = 'verbose PCI evidence\n'
                elif 'nvidia-smi' in joined: value = '0, ' + C.REFERENCE_ARM['gpu_uuid'] + ', 00000000:03:00.0, NVIDIA GeForce RTX 3060, 610.57.04, 12288 MiB, 40, 20.5 W, 170.0 W\n'
                elif 'vulkaninfo' in joined:
                    name = 'AMD Radeon RX 580 Series (RADV POLARIS10)' if C.CANDIDATE_ARM['icd'] in joined else 'NVIDIA GeForce RTX 3060'
                    vendor, device = ('0x1002', '0x67df') if 'RADV' in name else ('0x10de', '0x2504')
                    uuid = C.CANDIDATE_ARM['vulkan_device_uuid'] if 'RADV' in name else C.REFERENCE_ARM['vulkan_device_uuid']
                    value = f'GPU0:\n deviceName = {name}\n vendorID = {vendor}\n deviceID = {device}\n deviceUUID = {uuid}\n'
                elif command[:1] == ['readlink']: value = '/sys/bus/pci/drivers/' + ('amdgpu' if '02:00.0' in joined else 'nvidia')
                elif command[:1] == ['cat']:
                    key = command[-1].rsplit('/', 1)[-1]
                    value = {'vendor':'0x1002','device':'0x67df','subsystem_vendor':'0x1da2',
                        'subsystem_device':'0xe353','revision':'0xe7','current_link_width':'8',
                        'current_link_speed':'8.0 GT/s','max_link_width':'16',
                        'max_link_speed':'8.0 GT/s','mem_info_vram_total':str(8*1024**3)}.get(key, '1')
                    if '03:00.0' in joined: value = {'vendor':'0x10de','device':'0x2504','revision':'0xa1',
                        'subsystem_vendor':'0x1458','subsystem_device':'0x4074',
                        'current_link_width':'16','current_link_speed':'2.5 GT/s',
                        'max_link_width':'16','max_link_speed':'16.0 GT/s'}.get(key, value)
                elif command[:1] == ['sha256sum']: value = C.MODEL_MEMBER_SHA256[command[-1].rsplit('/', 1)[-1]] + '  ' + command[-1]
                elif command[:1] == ['stat']: value = '24346461344' if C.MODEL_MEMBERS[2] in joined else '24100000000'
                elif command[:1] == ['python3']:
                    if '/proc/cpuinfo' in joined: value = json.dumps(['model name : Fake CPU'])
                    elif 'mem_state' in joined: value = json.dumps({'MemAvailable':120000000,'Cached':80000000,'Buffers':1000000})
                    elif '/proc/meminfo' in joined: value = json.dumps({'mem_total_kib':128*1024*1024})
                    elif 'board_vendor' in joined: value = json.dumps({'board_vendor':'FixtureVendor','board_name':'FixtureBoard'})
                    elif 'platform' in joined: value = json.dumps({'machine':'x86_64','release':'test'})
                    elif 'icd.d' in joined: value = json.dumps([C.CANDIDATE_ARM['icd'], C.REFERENCE_ARM['icd']])
                    else: value = json.dumps({'hwmon':[{'name':'amdgpu','temp1_input':42000}], 'power_supply':[]})
                else: raise AssertionError(f'unexpected command {command}')
                return 0, value, ''
        manifest = self.root / C.R8I_MANIFEST_REL
        manifest.parent.mkdir(parents=True)
        manifest.write_text('')
        model_dir = self.root / 'fake-models'
        model_dir.mkdir()
        for member in C.MODEL_MEMBERS:
            (model_dir / member).write_bytes(b'fixture only')
        model_dir_patch = patch.object(C, 'MODEL_DIR', model_dir)
        model_dir_patch.start()
        self.addCleanup(model_dir_patch.stop)
        runner = CensusRunner()
        result = producer.collect_census(self.root, runner, AUTHORITY, out_dir=self.root)
        for command in runner.calls:
            if command[0] == 'python3':
                compile(command[2], '<capture-command>', 'exec')
        gpu = next(g for g in result['census']['gpus'] if g['vendor_id'] == '1002')
        self.assertEqual(gpu['vram_mib'], 8192)
        self.assertEqual(gpu['subsystem_device_id'], 'e353')
        self.assertEqual(gpu['revision'], 'e7')
        self.assertEqual(gpu['link_speed'], '8.0 GT/s')
        self.assertEqual(gpu['vulkan_icd'], C.CANDIDATE_ARM['icd'])
        self.assertEqual(result['census']['motherboard']['board_name'], 'FixtureBoard')
        self.assertEqual(result['census']['memory_state']['Cached'], 80000000)
        self.assertEqual(result['census']['power_thermal']['nvidia'][0]['power_draw_w'], '20.5 W')
        self.assertTrue(result['verdict']['validated'])
        self.assertEqual(json.loads((self.root / 'census.json').read_text())['census'], result['census'])
        class DriftRunner(CensusRunner):
            def __init__(inner, mutation):
                super().__init__()
                inner.mutation = mutation
            def run(inner, command, *, cwd=None, timeout=None):
                code, stdout, stderr = super().run(command, cwd=cwd, timeout=timeout)
                return code, inner.mutation(command, stdout), stderr
        for name, mutate in (
            ('vram', lambda cmd, value: str(4 * 1024**3) if cmd[-1].endswith('mem_info_vram_total') else value),
            ('icd', lambda cmd, value: value.replace('RADV POLARIS10', 'wrong GPU') if 'vulkaninfo' in cmd else value),
            ('model', lambda cmd, value: 'f' * 64 + value[64:] if cmd[0] == 'sha256sum' else value),
        ):
            with self.subTest(drift=name):
                with self.assertRaises(producer.ProducerError):
                    producer.collect_census(self.root, DriftRunner(mutate), AUTHORITY,
                                            out_dir=self.root / name)
                self.assertFalse((self.root / name / 'census.json').exists())

    def test_frozen_third_digest_matches_accepted_r8h_authority(self):
        authority_path = (Path(__file__).resolve().parents[1] /
            'docs/investigations/qwen38-flash-next-r8-h-vulkan/evidence/PHYSICAL-AUTHORITY.json')
        accepted = json.loads(authority_path.read_text())['model_authority']['members']
        expected = {row['member']: row['sha256'] for row in accepted}
        self.assertEqual(C.MODEL_MEMBER_SHA256, expected)
        self.assertTrue(all(len(value) == 64 for value in expected.values()))

    def test_build_isolated_worktree_and_actual_package_hashes(self):
        source = self.root / producer.observer_patch.TARGET
        source.parent.mkdir(parents=True)
        source.write_text('base')
        patch_file = self.root / 'accepted.patch'
        patch_file.write_text('fixture patch')
        class BuildRunner:
            def __init__(inner): inner.commands = []
            def run(inner, command, *, cwd=None, timeout=None):
                inner.commands.append((command, cwd))
                if command[:3] == ['git', 'rev-parse', 'HEAD']:
                    return 0, C.LLAMA_CPP_PIN + '\n', ''
                if command[:3] == ['git', 'worktree', 'add']:
                    worktree = Path(command[-2])
                    target = worktree / producer.observer_patch.TARGET
                    target.parent.mkdir(parents=True)
                    shutil.copy2(source, target)
                elif command[:2] == ['git', 'apply'] and '--check' not in command:
                    (Path(cwd) / producer.observer_patch.TARGET).write_text('r8e')
                elif command[:2] == ['cmake', '--build']:
                    directory = Path(cwd) / 'build-issue241' / 'bin'
                    directory.mkdir(parents=True)
                    (directory / 'llama-server').write_bytes(b'actual binary')
                    (directory / 'libggml.so').write_bytes(b'actual shared library')
                    (directory / 'libggml.so.0').symlink_to('libggml.so')
                elif command[:1] == ['ldd']:
                    return 0, 'libvulkan.so.1 => /usr/lib/libvulkan.so.1 (fixture)\n', ''
                elif command[:1] == ['dpkg-query']:
                    return 0, 'libvulkan1=1.4.fixture\nmesa-vulkan-drivers=25.0.fixture\n', ''
                return 0, '', ''
        runner = BuildRunner()
        expected = hashlib.sha256(b'r8e-v2').hexdigest()
        with patch.object(producer.observer_patch, 'verify_r8e_patch'), \
             patch.object(producer.observer_patch, 'apply', side_effect=lambda s: s + '-v2'), \
             patch.object(C, 'OBSERVER_PATCHED_SOURCE_SHA256', expected):
            result = producer.build_comparator(self.root, patch_file, runner, AUTHORITY)
        self.assertEqual(source.read_text(), 'base')
        self.assertEqual(result['patched_source_sha256'], expected)
        self.assertEqual(result['binary']['sha256'], hashlib.sha256(b'actual binary').hexdigest())
        self.assertEqual(result['package_sha256']['libggml.so'], hashlib.sha256(b'actual shared library').hexdigest())
        self.assertEqual(result['package_sha256']['libggml.so.0'], hashlib.sha256(b'actual shared library').hexdigest())
        package_path = Path(result['package']['path'])
        self.assertEqual(result['package']['sha256'], hashlib.sha256(package_path.read_bytes()).hexdigest())
        self.assertTrue(any(cmd[:3] == ['git', 'worktree', 'add'] for cmd, _ in runner.commands))
        self.assertIn('libvulkan.so.1', result['dynamic_dependencies']['stdout'])
        self.assertIn('mesa-vulkan-drivers=25.0.fixture', result['runtime_packages']['stdout'])

if __name__ == "__main__":
    unittest.main()
