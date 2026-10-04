"""CPU serialized custody-path regressions; no hardware execution."""
from __future__ import annotations
import copy
import hashlib
import json
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'scripts'))
import issue273_reducer as R

class DispatchContinuationRedTests(unittest.TestCase):
    def transport(self, namespace, body_extra=''):
        head = 'a' * 40
        comments = [{'id': 1, 'user': {'login': 'maintainer'},
                     'author_association': 'MEMBER',
                     'body': f'{R.DISPATCH_PHRASE_273}\nhead={head}\nnamespace={namespace}{body_extra}'}]
        def get(path):
            if path.endswith('/comments'): return comments
            if '/pulls/' in path: return {'merged': True, 'merged_at': '2026-10-04T00:00:00Z', 'merge_commit_sha': head}
            return {'object': {'sha': head}}
        return get

    def test_authenticated_dispatch_cannot_authorize_historical_namespace(self):
        with self.assertRaises(R.ReducerError):
            R.authenticate_dispatch_273(self.transport('c270-v340-comparator2'), 'a'*40, 274, 'c270-v340-comparator2')

    def test_duplicate_dispatch_fields_are_not_last_value_authority(self):
        with self.assertRaises(R.ReducerError):
            R.authenticate_dispatch_273(self.transport(R.NAMESPACE_273, '\nhead='+'b'*40+'\nhead='+'a'*40), 'a'*40, 274)


import issue270_authority as C
import issue270_comparator as K
import issue273_admission as A


def dump(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, sort_keys=True, indent=2) + '\n')


def digest(data):
    return hashlib.sha256(data).hexdigest()


class ByteSnapshotTests(unittest.TestCase):
    def test_directory_swap_during_read_cannot_substitute_outside_bytes(self):
        import os
        from unittest.mock import patch
        import issue273_evidence as E
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base/'root'
            (root/'rows').mkdir(parents=True)
            (root/'rows/payload').write_bytes(b'original')
            (base/'evil').mkdir()
            (base/'evil/payload').write_bytes(b'outside-forgery')
            real_open = os.open
            swapped = False
            def adversarial_open(path, *args, **kwargs):
                nonlocal swapped
                if Path(path).name == 'payload' and not swapped:
                    swapped = True
                    (root/'rows').rename(base/'original-rows')
                    (root/'rows').symlink_to(base/'evil', target_is_directory=True)
                return real_open(path, *args, **kwargs)
            with patch.object(E.os, 'open', adversarial_open):
                try:
                    retained = E.snapshot(root)
                except E.EvidenceError:
                    return
            self.assertEqual(retained['rows/payload'], b'original')


class SerializedEvidenceTests(unittest.TestCase):
    def setUp(self):
        # A source-authenticated tiny repository, sharing only read-only objects.
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.repo = self.base / 'repo'
        self.capture = self.base / 'capture'
        self.evidence = self.base / 'evidence'
        self.repo.mkdir()
        self.git('init', '-q')
        common = subprocess.check_output(['git', 'rev-parse', '--git-common-dir'], cwd=REPO, text=True).strip()
        objects = (REPO / common / 'objects').resolve()
        (self.repo / '.git/objects/info/alternates').write_text(str(objects) + '\n')
        # Discovery of the API is an explicit new-feature RED, not historical RED.
        self.assertTrue(callable(getattr(R, 'derive_terminal_from_files_273', None)),
                        'public serialized producer-reader-terminal entrypoint missing')
        import issue273_evidence as E
        self.E = E
        for rel in E.AUTHORITY_PATHS + E.PRODUCER_PATHS:
            dest = self.repo / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes((REPO / rel).read_bytes())
        self.git('config', 'user.name', 'CPU Recording')
        self.git('config', 'user.email', 'recording@example.invalid')
        self.git('add', '--', *E.AUTHORITY_PATHS, *E.PRODUCER_PATHS)
        tree = self.git('write-tree')
        parent = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=REPO, text=True).strip()
        self.head = self.git('commit-tree', tree, '-p', parent, '-m', 'CPU fixture source closure')
        self.git('update-ref', 'refs/heads/master', self.head)
        self.comments = [{'id': 901, 'user': {'login': 'maintainer'}, 'author_association': 'MEMBER',
                          'created_at': '2026-10-04T00:00:01Z',
                          'body': f'{R.DISPATCH_PHRASE_273}\nhead={self.head}\nnamespace={R.NAMESPACE_273}'}]
        self.pull = {'merged': True, 'merged_at': '2026-10-04T00:00:00Z', 'merge_commit_sha': self.head,
                     'base': {'ref': 'main', 'repo': {'full_name': 'Zutfen-LLC/inferswarm'}}}
        self.dispatch = R.authenticate_dispatch_273(self.transport, self.head, 274)
        authority = E.authority_contract(self.repo, self.head, self.dispatch)
        self.freeze = {'schema': E.FREEZE_SCHEMA, 'head_sha': self.head, 'namespace': R.NAMESPACE_273,
                       'dispatch_id': 901, 'authority_sha256': C.authority_digest(authority),
                       'frozen_at': '2026-10-04T00:00:02Z', 'capture_mode': 'CPU_RECORDING',
                       'placement': dict(A.ARM_PLACEMENT),
                       'selection': {'rule': C.TWO_INDEX_RULE, 'selected_bdf': C.DIE_BDFS[0],
                                     'excluded_bdfs': [C.DIE_BDFS[1]], 'selected_index': '0'}}
        dump(self.capture / 'freeze.json', self.freeze)
        binding = {'schema': C.BINDING_SCHEMA, 'expected_pr_head': self.head, 'host': C.CANDIDATE_HOST,
                   'binary_sha256': C.COMPARATOR_SHA256, 'icd': C.RADV_ICD, 'cuda_visible_devices': '-1',
                   'mapping': {}}
        for i, bdf in enumerate(C.DIE_BDFS):
            other = C.DIE_BDFS[1-i]
            binding['mapping'][str(i)] = {'selected_bdf': bdf, 'excluded_bdf': other,
                                         'vram_before': {x: 0 for x in C.DIE_BDFS},
                                         'vram_after': {bdf: C.EXCLUDED_NOISE_BYTES+1, other: 0}}
        from tests.test_issue270_authority import synthetic_raw
        dump(self.capture / 'preflight.json', {'selector_binding': binding, 'candidate_raw': synthetic_raw()})
        self.serial = 0
        for arm in ('reference', 'candidate'):
            for case in C.FIXTURE_CASES:
                for repeat in (False, True):
                    self.record(case, arm, repeat)
        self.produce()

    def git(self, *args):
        return subprocess.check_output(['git', *args], cwd=self.repo, text=True).strip()

    def transport(self, path):
        if path.endswith('/comments'): return copy.deepcopy(self.comments)
        if '/pulls/' in path: return copy.deepcopy(self.pull)
        if path.endswith('/git/ref/heads/main'): return {'object': {'sha': self.head}}
        raise AssertionError(path)

    def record(self, case, arm, repeat):
        self.serial += 1
        tag = arm + ('-repeat' if repeat else '')
        stem = f'source/{case}/{tag}'
        pid = 10000+self.serial
        env = {'VK_ICD_FILENAMES': A.ARM_ICD[arm], 'GGML_VK_VISIBLE_DEVICES': '0',
               'CUDA_VISIBLE_DEVICES': '-1', 'INFERSWARM_HOST': A.ARM_HOST[arm],
               'LLAMA_OBSERVE_CAPTURE': '8', 'LLAMA_OBSERVE_OUT': f'/capture/{pid}',
               'LLAMA_OBSERVE_LOG': f'/capture/{pid}.log'}
        argv = ['/srv/bin/llama-server', '--model', f'{C.MODEL_DIR}/{C.MODEL_MEMBERS[0]}',
                '-ngl', str(A.ARM_PLACEMENT[arm]), '--ctx-size', '8192', '--batch-size', '512']
        proc = {'server_pid': pid, 'server_argv': argv, 'server_env': env}
        fx = C.load_fixtures(self.repo)[case]
        bdf = '00000000:03:00.0' if arm == 'reference' else C.DIE_BDFS[0]
        excluded = '0000:04:00.0' if arm == 'reference' else C.DIE_BDFS[1]
        winners = [11*(d+1) for d in range(8)]
        rows = {}
        for d in range(8):
            raw = bytearray(struct.pack('<f', 0.0 if arm == 'reference' else 0.001) * C.N_VOCAB)
            raw[4*winners[d]:4*winners[d]+4] = struct.pack('<f', 2.0)
            path = f'{stem}/rows/{d}.f32'
            dest = self.capture / path
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(raw)
            rows[str(d)] = {'path': path, 'sha256': digest(raw), 'bytes': len(raw)}
        ident = C.reference_identity() if arm == 'reference' else {'host': A.ARM_HOST[arm], 'bdf': bdf}
        start = 10 + self.serial * 3
        stamp = lambda n: f'2026-10-04T00:{n//60:02d}:{n%60:02d}Z'
        receipt = {'schema': self.E.RUN_SCHEMA, 'campaign': self.E.CAMPAIGN,
                   'namespace': R.NAMESPACE_273, 'head_sha': self.head, 'dispatch_authority': self.dispatch,
                   'case_id': case, 'arm': arm, 'repeat_of': arm if repeat else None,
                   'host': A.ARM_HOST[arm], 'bdf': bdf, 'icd': A.ARM_ICD[arm],
                   'selector': {'GGML_VK_VISIBLE_DEVICES': '0', 'CUDA_VISIBLE_DEVICES': '-1'},
                   'cuda_visible_devices': '-1', 'ngl': A.ARM_PLACEMENT[arm], 'subject_identity': ident,
                   'comparator_id': C.COMPARATOR_V2_ID, 'fixture_ladder_sha256': C.FIXTURE_LADDER_SHA256,
                   'prompt_token_ids': fx['prompt_token_ids'], 'prompt_len': fx['rendered_length'],
                   'prompt_text_sha256': digest(fx['prompt_text'].encode()),
                   'model_members': C.MODEL_MEMBER_SHA256, 'llama_source_pin': C.LLAMA_SOURCE_PIN,
                   'server_sha256': C.COMPARATOR_SHA256,
                   'build_flags': ['-DGGML_VULKAN=ON', '-DGGML_CUDA=OFF'],
                   'request_contract': C.REQUEST_CONTRACT, 'context_settings': C.CONTEXT_SETTINGS,
                   'excluded_device_residency_bytes': {excluded: 0}, 'process_attribution': proc,
                   'sampled_winners': winners, 'forced_tokens': winners if arm == 'candidate' else [-1]*8,
                   'meta_rows': [{'pos': d, 'n_vocab': C.N_VOCAB, 'sampled_winner': winners[d],
                                  'forced_token': winners[d] if arm == 'candidate' else -1,
                                  'prefix_tokens': fx['prompt_token_ids'] + winners[:d],
                                  'capture_before_force': True} for d in range(8)],
                   'rows': rows, 'observation_path': f'{stem}/observation.json',
                   'run_id': f'{R.NAMESPACE_273}-{case}-{tag}', 'session_id': f'session-{pid}',
                   'boot_id': f'boot-{arm}', 'start_ticks': pid*100,
                   'started_at': stamp(start), 'finished_at': stamp(start+2)}
        selected = {'index': '0', 'bdf': bdf, 'vendor_id': '0x10de' if arm=='reference' else '0x1002',
                    'device_id': '0x2504' if arm=='reference' else '0x6864',
                    'gpu_uuid': C.reference_identity()['gpu_uuid'] if arm=='reference' else C.EXPECTED_VULKAN_DEVICE_UUIDS[bdf],
                    'vulkan_uuid': C.reference_identity()['vulkan_device_uuid'] if arm=='reference' else C.EXPECTED_VULKAN_DEVICE_UUIDS[bdf],
                    'name': 'RTX 3060' if arm=='reference' else 'V340', 'icd': A.ARM_ICD[arm],
                    'physical_type': 'DISCRETE_GPU'}
        bystander = {'index': '1', 'bdf': excluded, 'vendor_id': '0x1002',
                     'device_id': '0x67df' if arm=='reference' else '0x6864',
                     'gpu_uuid': 'rx580-recording' if arm=='reference' else C.EXPECTED_VULKAN_DEVICE_UUIDS[excluded],
                     'vulkan_uuid': 'rx580-vk-recording' if arm=='reference' else C.EXPECTED_VULKAN_DEVICE_UUIDS[excluded],
                     'name': 'RX 580' if arm=='reference' else 'V340', 'icd': C.RADV_ICD,
                     'physical_type': 'DISCRETE_GPU'}
        obs = {'schema': self.E.OBSERVATION_SCHEMA, 'run_id': receipt['run_id'],
               'session_id': receipt['session_id'], 'boot_id': receipt['boot_id'], 'start_ticks': receipt['start_ticks'],
               'observed_at': stamp(start+1), 'host': receipt['host'], 'process_attribution': proc,
               'devices': [selected, bystander], 'used_device_uuids': [selected['vulkan_uuid']],
               'backend': 'Vulkan', 'icd': A.ARM_ICD[arm], 'reference_identity': ident if arm=='reference' else None,
               'residency': {bdf: {'before': 0, 'peak': 6_300_000_000 if arm=='candidate' else 8_220_000_000, 'after': 0},
                             excluded: {'before': 0, 'peak': 0, 'after': 0}},
               'runtime': {'exe_sha256': C.COMPARATOR_SHA256, 'source_pin': C.LLAMA_SOURCE_PIN,
                           'source_tree': C.ACCEPTED_LLAMA_SOURCE_TREE, 'observer_libs': C.OBSERVER_LIBS,
                           'model_members_open': C.MODEL_MEMBER_SHA256, 'model_members_close': C.MODEL_MEMBER_SHA256},
               'observer': {'disabled_tokens': winners, 'canonical_tokens': winners,
                            'disabled_artifacts': [], 'canonical_artifacts': [],
                            'canonical_sha256': C.CANONICAL_SHA256},
               'platform': {'probe_rcs': {'kernel_log': 0, 'pcie': 0, 'thermal': 0, 'storage': 0, 'power': 0},
                            'errors': [], 'link_width': 16, 'link_speed_gt_s': 8.0,
                            'temperature_c': 55, 'throttled': False, 'oom_kills': 0}}
        dump(self.capture / f'{stem}/receipt.json', receipt)
        dump(self.capture / f'{stem}/observation.json', obs)

    def produce(self):
        self.E.produce_evidence_273(self.capture, self.evidence, self.repo, self.head, transport=self.transport)
        self.seal()

    def seal(self):
        # Independent capture service holds this snapshot; the reader cannot
        # refresh it by editing an evidence-root self-digest.
        sha = digest((self.evidence / 'manifest.json').read_bytes())
        self.comments[:] = self.comments[:1] + [{'id': 902, 'user': {'login': 'maintainer'},
            'author_association': 'MEMBER', 'created_at': '2026-10-04T00:03:00Z',
            'body': f'{self.E.SEAL_PHRASE}\nhead={self.head}\nnamespace={R.NAMESPACE_273}\ndispatch_id=901\nmanifest_sha256={sha}'}]

    def reduce(self):
        return R.derive_terminal_from_files_273(self.evidence, self.repo, self.head, transport=self.transport)

    def edit(self, rel, fn, resign=False):
        path = self.evidence / rel
        obj = json.loads(path.read_bytes())
        fn(obj)
        dump(path, obj)
        if resign: self.refresh()

    def refresh(self):
        paths = self.E.expected_paths(include_candidate=True)
        dump(self.evidence / 'manifest.json', {p: digest((self.evidence/p).read_bytes()) for p in sorted(paths)})
        self.seal()

    def test_serialized_producer_reader_terminal_positive_recording(self):
        out = self.reduce()
        self.assertEqual(out['terminal'], R.TERMINAL_PASS_273, out['problems'])
        self.assertFalse(out['physical_authority'])
        self.assertEqual(set(out['pair_diagnostics']), set(C.FIXTURE_CASES))
        self.assertEqual(C.SELECTED_PLACEMENT_NGL, 7)

    def test_bytes_cannot_be_reauthorized_with_self_picked_manifest(self):
        for rel in ('source/case-256/reference/receipt.json', 'units/case-256/reference.json',
                    'source/case-256/reference-repeat/observation.json',
                    'source/case-256/reference/rows/0.f32', 'units/case-256/candidate-repeat/rows/7.f32'):
            with self.subTest(rel=rel):
                path = self.evidence/rel
                old = path.read_bytes()
                path.write_bytes(old+b' ')
                # Update consistency pin only, not the independent seal.
                manifest = json.loads((self.evidence/'manifest.json').read_bytes())
                before = (self.evidence/'manifest.json').read_bytes()
                manifest[rel] = digest(path.read_bytes())
                dump(self.evidence/'manifest.json', manifest)
                self.assertNotEqual(self.reduce()['terminal'], R.TERMINAL_PASS_273)
                path.write_bytes(old)
                (self.evidence/'manifest.json').write_bytes(before)

    def test_authenticated_mutations_rejected_at_semantic_boundaries(self):
        mutations = [
            ('units/case-256/reference.json', lambda r: r.update(host='inferswarm05')),
            ('source/case-256/reference/observation.json', lambda o: o['devices'][0].update(bdf='0000:04:00.0')),
            ('source/case-256/reference/observation.json', lambda o: o['devices'][0].update(vendor_id='0x1002')),
            ('source/case-256/reference/observation.json', lambda o: o.update(used_device_uuids=['rx580-vk-recording'])),
            ('source/case-256/reference/observation.json', lambda o: o['residency']['0000:04:00.0'].update(peak=C.EXCLUDED_NOISE_BYTES)),
            ('source/case-256/candidate/observation.json', lambda o: o['residency'][C.DIE_BDFS[1]].update(peak=C.EXCLUDED_NOISE_BYTES)),
            ('source/case-256/reference-repeat/observation.json', lambda o: o['observer'].update(disabled_tokens=[1]*8)),
            ('source/case-256/candidate-repeat/observation.json', lambda o: o['platform'].update(errors=['pcie fault'])),
            ('preflight.json', lambda p: p['selector_binding']['mapping']['0'].update(selected_bdf=C.DIE_BDFS[1])),
            ('freeze.json', lambda f: f.update(namespace='c270-v340-comparator2')),
            ('authority.json', lambda a: a.update(source_pin='0'*40)),
            ('units/case-256/candidate-repeat.json', lambda r: r['meta_rows'][0].update(forced_token=555)),
            ('units/case-256/reference-repeat.json', lambda r: r.update(session_id='session-10001')),
        ]
        for rel, fn in mutations:
            with self.subTest(rel=rel):
                old = (self.evidence/rel).read_bytes()
                self.edit(rel, fn, resign=True)
                self.assertNotEqual(self.reduce()['terminal'], R.TERMINAL_PASS_273)
                (self.evidence/rel).write_bytes(old)
                self.refresh()

    def test_row_sets_symlinks_and_traversal_fail_closed(self):
        rel = 'source/case-256/reference/rows/0.f32'
        path = self.evidence/rel
        old = path.read_bytes()
        path.unlink()
        self.assertNotEqual(self.reduce()['terminal'], R.TERMINAL_PASS_273)
        outside = self.base/'outside.f32'
        outside.write_bytes(old)
        path.symlink_to(outside)
        self.assertNotEqual(self.reduce()['terminal'], R.TERMINAL_PASS_273)
        path.unlink(); path.write_bytes(old)
        extra = self.evidence/'units/case-256/reference/rows/8.f32'
        extra.write_bytes(old)
        self.assertNotEqual(self.reduce()['terminal'], R.TERMINAL_PASS_273)
        extra.unlink()
        self.edit('units/case-256/reference.json', lambda r: r['rows']['0'].update(path='../outside.f32'), resign=True)
        self.assertNotEqual(self.reduce()['terminal'], R.TERMINAL_PASS_273)

    def test_reference_mismatch_stops_before_candidate_parse(self):
        # Honest, independently sealed nondeterministic repeat. Keep it finite
        # with the same greedy winner, but alter one nonwinner's FP32 bytes.
        for prefix in ('source', 'units'):
            rel = f'{prefix}/case-256/reference-repeat/rows/0.f32'
            path = self.evidence/rel
            raw = bytearray(path.read_bytes()); raw[:4] = struct.pack('<f', 0.5)
            path.write_bytes(raw)
        src = 'source/case-256/reference-repeat/receipt.json'
        stage = 'units/case-256/reference-repeat.json'
        sha = digest((self.evidence/'source/case-256/reference-repeat/rows/0.f32').read_bytes())
        self.edit(src, lambda r: r['rows']['0'].update(sha256=sha))
        self.edit(stage, lambda r: (r['rows']['0'].update(sha256=sha),
            r['staged_source'].update(receipt_sha256=digest((self.evidence/src).read_bytes())),
            r['staged_source']['row_digests'].update({'0': sha})))
        (self.evidence/'source/case-256/candidate/receipt.json').write_text('not JSON')
        self.refresh()
        out = self.reduce()
        self.assertEqual(out['terminal'], R.TERMINAL_REFERENCE_NONDETERMINISTIC_273, out['problems'])
        self.assertEqual(out['pair_diagnostics'], {})

    def test_dispatch_merge_head_maintainer_and_seal_required(self):
        for fn in (lambda: self.pull.update(merged=False),
                   lambda: self.pull.update(merge_commit_sha='f'*40),
                   lambda: self.comments[0].update(author_association='NONE'),
                   lambda: self.comments.pop(),
                   lambda: self.comments[1].update(author_association='NONE')):
            comments, pull = copy.deepcopy(self.comments), copy.deepcopy(self.pull)
            fn()
            self.assertNotEqual(self.reduce()['terminal'], R.TERMINAL_PASS_273)
            self.comments, self.pull = comments, pull

    def restage(self, case, tag):
        source_rel = f'source/{case}/{tag}/receipt.json'
        source = json.loads((self.evidence/source_rel).read_bytes())
        staged = copy.deepcopy(source)
        for d in source['rows']:
            staged['rows'][d]['path'] = f'units/{case}/{tag}/rows/{d}.f32'
        staged['staged_source'] = A.bind_staged_source(source, source_rel,
            digest((self.evidence/source_rel).read_bytes()),
            {d: digest((self.evidence/source['rows'][d]['path']).read_bytes()) for d in source['rows']})
        dump(self.evidence/f'units/{case}/{tag}.json', staged)

    def test_authenticated_source_binding_claims_do_not_override_bytes(self):
        rel = 'units/case-256/reference-repeat.json'
        old = (self.evidence/rel).read_bytes()
        for field in ('receipt_sha256', 'row_digests'):
            self.edit(rel, lambda r: r['staged_source'].update(
                {field: '0'*64 if field == 'receipt_sha256' else {str(d): '0'*64 for d in range(8)}}), resign=True)
            self.assertNotEqual(self.reduce()['terminal'], R.TERMINAL_PASS_273)
            (self.evidence/rel).write_bytes(old)
            self.refresh()

    def test_coherent_source_stage_prefix_forgery_is_rejected(self):
        source = 'source/case-256/candidate-repeat/receipt.json'
        self.edit(source, lambda r: r['meta_rows'][1].update(prefix_tokens=[555]))
        self.restage('case-256', 'candidate-repeat')
        self.refresh()
        out = self.reduce()
        self.assertNotEqual(out['terminal'], R.TERMINAL_PASS_273)
        self.assertTrue(any('canonical-prefix' in p for p in out['problems']), out['problems'])

    def test_coherent_source_stage_observation_session_reuse_is_rejected(self):
        source = 'source/case-256/reference-repeat/receipt.json'
        obs = 'source/case-256/reference-repeat/observation.json'
        self.edit(source, lambda r: r.update(session_id='session-10001'))
        self.edit(obs, lambda o: o.update(session_id='session-10001'))
        self.restage('case-256', 'reference-repeat')
        self.refresh()
        out = self.reduce()
        self.assertNotEqual(out['terminal'], R.TERMINAL_PASS_273)
        self.assertTrue(any('reused session' in p for p in out['problems']), out['problems'])

    def test_forged_digest_claims_and_authenticated_nonfinite_rows_are_rejected(self):
        source = 'source/case-256/reference-repeat/receipt.json'
        for prefix in ('source', 'units'):
            path = self.evidence/f'{prefix}/case-256/reference-repeat/rows/0.f32'
            raw = bytearray(path.read_bytes())
            raw[4000:4004] = struct.pack('<f', float('nan'))
            path.write_bytes(raw)
        # First retain stale claims even though all files have an authentic seal.
        self.refresh()
        self.assertNotEqual(self.reduce()['terminal'], R.TERMINAL_PASS_273)
        sha = digest((self.evidence/'source/case-256/reference-repeat/rows/0.f32').read_bytes())
        self.edit(source, lambda r: r['rows']['0'].update(sha256=sha))
        self.restage('case-256', 'reference-repeat')
        self.refresh()
        out = self.reduce()
        self.assertNotEqual(out['terminal'], R.TERMINAL_PASS_273)
        self.assertTrue(any('finite FP32' in p for p in out['problems']), out['problems'])

    def test_cpu_recording_cannot_turn_numerical_disagreement_into_a_gate(self):
        for tag in ('candidate', 'candidate-repeat'):
            source = f'source/case-256/{tag}/receipt.json'
            for prefix in ('source', 'units'):
                path = self.evidence/f'{prefix}/case-256/{tag}/rows/0.f32'
                raw = bytearray(path.read_bytes()); raw[4*55:4*56] = struct.pack('<f', 3.0)
                path.write_bytes(raw)
            sha = digest((self.evidence/f'source/case-256/{tag}/rows/0.f32').read_bytes())
            self.edit(source, lambda r: (r['rows']['0'].update(sha256=sha),
                r['sampled_winners'].__setitem__(0, 55), r['meta_rows'][0].update(sampled_winner=55)))
            self.restage('case-256', tag)
        self.refresh()
        out = self.reduce()
        self.assertEqual(out['terminal'], R.TERMINAL_PASS_273, out['problems'])
        self.assertEqual(out['pair_diagnostics']['case-256']['winner_agreement'], 7)

    def test_producer_stops_before_parsing_candidate_on_reference_mismatch(self):
        source = 'source/case-256/reference-repeat/receipt.json'
        path = self.capture/'source/case-256/reference-repeat/rows/0.f32'
        raw = bytearray(path.read_bytes()); raw[:4] = struct.pack('<f', 0.5)
        path.write_bytes(raw)
        receipt = json.loads((self.capture/source).read_bytes())
        receipt['rows']['0']['sha256'] = digest(raw)
        dump(self.capture/source, receipt)
        (self.capture/'source/case-256/candidate/receipt.json').write_text('not JSON')
        out_root = self.base/'blocked-evidence'
        result = self.E.produce_evidence_273(self.capture, out_root, self.repo, self.head, transport=self.transport)
        self.assertFalse(result['reached_candidate'])
        self.assertFalse((out_root/'units/case-256/candidate.json').exists())
        # Re-bind the independent CPU seal to this newly preserved blocked root.
        self.evidence = out_root
        self.seal()
        out = self.reduce()
        self.assertEqual(out['terminal'], R.TERMINAL_REFERENCE_NONDETERMINISTIC_273, out['problems'])

    def test_coherent_reference_selector_drift_cannot_override_frozen_identity(self):
        for tag in ('reference', 'reference-repeat'):
            source = f'source/case-256/{tag}/receipt.json'
            obs = f'source/case-256/{tag}/observation.json'
            def move_selector(r):
                r['selector']['GGML_VK_VISIBLE_DEVICES'] = '1'
                r['process_attribution']['server_env']['GGML_VK_VISIBLE_DEVICES'] = '1'
            def move_observation(o):
                o['process_attribution']['server_env']['GGML_VK_VISIBLE_DEVICES'] = '1'
                o['devices'][0]['index'], o['devices'][1]['index'] = '1', '0'
            self.edit(source, move_selector)
            self.edit(obs, move_observation)
            self.restage('case-256', tag)
        self.refresh()
        out = self.reduce()
        self.assertNotEqual(out['terminal'], R.TERMINAL_PASS_273)
        self.assertTrue(any('selector' in p for p in out['problems']), out['problems'])

    def test_checked_out_source_must_also_be_the_executing_verifier_bytes(self):
        path = self.repo/'scripts/issue273_evidence.py'
        path.write_text(path.read_text() + '\n# Different verifier bytes, same claimed checkout contract.\n')
        self.git('add', '--', 'scripts/issue273_evidence.py')
        self.git('commit', '-qm', 'CPU fixture divergent source')
        self.head = self.git('rev-parse', 'HEAD')
        self.pull['merge_commit_sha'] = self.head
        self.comments[0]['body'] = f'{R.DISPATCH_PHRASE_273}\nhead={self.head}\nnamespace={R.NAMESPACE_273}'
        self.dispatch = R.authenticate_dispatch_273(self.transport, self.head, 274)
        with self.assertRaises(self.E.EvidenceError):
            self.E.authority_contract(self.repo, self.head, self.dispatch)

    def test_historical_terminal_cannot_be_reclassified_by_a_new_schema(self):
        source = 'source/case-256/reference/receipt.json'
        self.edit(source, lambda r: r.update(terminal=C.TERMINAL_PASS))
        self.restage('case-256', 'reference')
        self.refresh()
        out = self.reduce()
        self.assertNotEqual(out['terminal'], R.TERMINAL_PASS_273)

    def test_producer_is_append_only_and_preserves_original_receipts(self):
        source = 'source/case-256/reference/receipt.json'
        self.assertEqual((self.capture/source).read_bytes(), (self.evidence/source).read_bytes())
        with self.assertRaises(self.E.EvidenceError):
            self.E.produce_evidence_273(self.capture, self.evidence, self.repo, self.head, transport=self.transport)

if __name__ == '__main__':
    unittest.main()
