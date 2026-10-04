"""Documentation drift and preservation regressions; no network or runtime work."""
import contextlib
import copy
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import sync_project_status as sync


class ProjectStatusTests(unittest.TestCase):
    def setUp(self):
        self.record = json.loads((sync.ROOT / sync.SOURCE).read_text())

    def fixture(self, root):
        (root / sync.SOURCE).parent.mkdir(parents=True, exist_ok=True)
        (root / sync.SOURCE).write_text(json.dumps(self.record))
        for path, sections in sync.TARGETS.items():
            target = root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text('Hand-authored introduction.\n\n' + '\n\n'.join(
                f'<!-- project-status:{name}:start -->\nold\n'
                f'<!-- project-status:{name}:end -->' for name in sections
            ) + '\n\nHand-authored ending.\n')

    def run_main(self, root, *args):
        with patch.object(sync, 'ROOT', root), contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(io.StringIO()):
            return sync.main(list(args))

    def snapshot(self, root):
        return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*') if p.is_file()}

    def test_committed_sections_are_current(self):
        self.assertEqual(sync.prepare_updates(sync.ROOT), {})

    def test_check_is_read_only_and_write_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.fixture(root)
            before = self.snapshot(root)
            self.assertEqual(self.run_main(root, '--check'), 1)
            self.assertEqual(before, self.snapshot(root))
            self.assertEqual(self.run_main(root, '--write'), 0)
            after = self.snapshot(root)
            self.assertEqual(self.run_main(root, '--check'), 0)
            self.assertEqual(self.run_main(root, '--write'), 0)
            self.assertEqual(after, self.snapshot(root))
            for path in sync.TARGETS:
                self.assertTrue(after[path].startswith(b'Hand-authored introduction.\n\n'))
                self.assertTrue(after[path].endswith(b'\n\nHand-authored ending.\n'))

    def test_source_change_updates_every_frontier_and_detects_manual_drift(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.fixture(root)
            self.assertEqual(self.run_main(root, '--write'), 0)
            # Synthetic accepted prerequisite for the authorization fixture;
            # the real #255 observation remains pending and cannot authorize it.
            self.record['frontier']['prerequisite']['acceptance'] = {
                'state': 'accepted',
                'reference': 'https://github.com/Zutfen-LLC/inferswarm/issues/999'}
            self.record['frontier']['execution']['state'] = 'authorized'
            self.record['frontier']['execution']['reference'] = (
                'https://github.com/Zutfen-LLC/inferswarm/issues/999')
            (root / sync.SOURCE).write_text(json.dumps(self.record))
            updates = sync.prepare_updates(root)
            for path in sync.TARGETS:
                self.assertIn(b'authorization:** authorized', updates[path])
            self.assertEqual(self.run_main(root, '--write'), 0)
            target = root / 'README.md'
            target.write_text(target.read_text().replace(
                'authorization:** authorized', 'authorization:** blocked'))
            before = target.read_bytes()
            self.assertEqual(self.run_main(root), 1)
            self.assertEqual(target.read_bytes(), before)

    def test_missing_duplicate_reversed_nested_and_unknown_markers_fail_before_writes(self):
        for mutation in ('missing', 'duplicate', 'reversed', 'nested', 'unknown'):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                self.fixture(root)
                target = root / 'docs/protocols/README.md'
                start = '<!-- project-status:frontier:start -->'
                end = '<!-- project-status:frontier:end -->'
                source = target.read_text()
                if mutation == 'missing':
                    source = source.replace(end, '')
                elif mutation == 'duplicate':
                    source += '\n' + start
                elif mutation == 'reversed':
                    source = source.replace(start, 'TEMP').replace(end, start).replace('TEMP', end)
                elif mutation == 'nested':
                    source = source.replace('old', '<!-- project-status:runtime:start -->')
                else:
                    source += '\n<!-- project-status:other:end -->'
                target.write_text(source)
                before = self.snapshot(root)
                self.assertEqual(self.run_main(root, '--write'), 1)
                self.assertEqual(self.snapshot(root), before)

    def test_completed_266_authority_preserves_bounded_264_and_250_scope(self):
        output = sync.render(self.record)['frontier']
        execution = self.record['frontier']['execution']
        for retained in (
                'Issue #266 is COMPLETED', 'PR #256 is MERGED',
                '442e2a02ce89e7fb42bceff1f7a47c8789c17733',
                'historical R8-I3C authority', '5969219338',
                'SUBGROUP/subgroup/32x1x1', 'LARGE/hybrid/128x1x1',
                'subgroup32→large128 hybrid', 'output.weight MMV q4_K*f32 route',
                'four fresh-process units', 'screening-variable',
                '5969219338', 'H2/H3/H5 theorem closure remain open',
                'PR #265 merged into the aggregate producer branch',
                'ARM_A_STOPS_LADDER', '5904093750', '5904094070',
                'not established as root cause',
                '#241 remains accepted as R8I3_COMPARATOR_V2_BLOCKED',
                '#244 and #239 remain blocked', '#258'):
            with self.subTest(retained=retained):
                self.assertTrue(retained in output or any(retained in item for item in execution['constraints']))
        self.assertEqual(execution['state'], 'blocked')
        self.assertTrue(any('ARM_A_STOPS_LADDER localized boundary only' in item and 'not established as root cause' in item for item in execution['constraints']))
        self.assertIn('no further execution authority', execution['step'])
        self.assertEqual(len(self.record['capabilities']), 9)
        self.assertNotIn('H5', {item['id'] for item in self.record['capabilities']})

    def test_268_frontier_preserves_accepted_255_and_blocks_premature_acceptance(self):
        frontier = self.record['frontier']
        prerequisite = frontier['prerequisite']
        output = sync.render(self.record)['frontier']
        self.assertIn('Issue #268', frontier['title'])
        self.assertNotIn('UNACCEPTED', frontier['title'])
        self.assertEqual(frontier['reference'],
                         'https://github.com/Zutfen-LLC/inferswarm/issues/268')
        self.assertEqual(frontier['execution']['reference'],
                         'https://github.com/Zutfen-LLC/inferswarm/issues/268')
        self.assertEqual(prerequisite['acceptance']['state'], 'accepted')
        self.assertEqual(prerequisite['acceptance']['reference'],
                         'https://github.com/Zutfen-LLC/inferswarm/issues/255#issuecomment-5974171991')
        self.assertEqual(prerequisite['observation']['result'],
                         'MVP_DISTRIBUTED_INFERENCE_PASS')
        self.assertIn('Issue #268', output)
        self.assertIn('Final CPU Validation requires maintainer GO', output)
        for denied in ('numerical equivalence', 'mixed-vendor readiness',
                       'production readiness', 'R8-J/Vulkan execution authority'):
            self.assertIn(denied, output)
        self.assertIn('MVP_DISTRIBUTED_INFERENCE_PASS',
                      json.dumps(self.record['capabilities']))
        self.assertEqual(len(self.record['capabilities']), 9)
        self.assertNotRegex(output, r'(?i)Issue #255 does not establish[^.]*accepted capabilities')
        self.assertNotRegex(output, r'(?i)observation remains outside accepted capabilities')
        self.assertNotRegex(output, r'(?i)does not assert the MVP terminal')

        # Test the source AND every generated living-status section, plus
        # authored product prose. Historical evidence is deliberately excluded.
        surfaces = {'source': json.dumps(self.record), **sync.render(self.record)}
        for relative, sections in sync.TARGETS.items():
            content = (sync.ROOT / relative).read_text()
            surfaces[relative] = '\n'.join(content.split(
                f'<!-- project-status:{name}:start -->', 1)[1].split(
                f'<!-- project-status:{name}:end -->', 1)[0] for name in sections)
        for name in ('README.md', 'product-report.md'):
            relative = 'docs/implementation/two-host-mvp-255/' + name
            surfaces[relative] = (sync.ROOT / relative).read_text()
        for name, content in surfaces.items():
            with self.subTest(surface=name):
                self.assertNotRegex(content, r'(?i)PR #256\s+(?:(?:remains|is)\s+)?(?:OPEN|UNMERGED|pending|awaiting)')
                self.assertNotRegex(content, r'(?i)PR #256[^.\n]*pending maintainer')
                self.assertNotRegex(content, r'(?i)(?:Issue )?#266[^.\n]*(?:pending|awaiting|requires aggregate|reviews the aggregate)')
                self.assertNotIn('#266/R8-I3C frontier', content)
                self.assertNotIn('R8-I3C/#266 frontier', content)
                self.assertNotIn('Issue #266 — aggregate R8-I3C mainline review', content)

    def test_accepted_255_status_cannot_revert_to_pending_final_cpu(self):
        rendered = sync.render(self.record)
        combined = json.dumps(self.record) + "\n" + "\n".join(rendered.values())
        self.assertIn('MVP_DISTRIBUTED_INFERENCE_PASS', combined)
        self.assertNotIn('UNACCEPTED CUDA/RPC product observation pending', combined)
        self.assertNotIn('Final CPU Validation must NOT run before explicit maintainer GO', combined)
        self.assertIn('Issue #268', combined)

    def test_268_physical_observed_but_not_accepted_on_all_living_surfaces(self):
        frontier = self.record['frontier']
        execution = frontier['execution']
        self.assertIn('not accepted', frontier['title'])
        self.assertEqual(execution['state'], 'blocked')
        self.assertEqual(frontier['prerequisite']['acceptance']['state'], 'accepted')
        surfaces = {'source': json.dumps(frontier), **sync.render(self.record)}
        for relative, sections in sync.TARGETS.items():
            content = (sync.ROOT / relative).read_text()
            surfaces[relative] = '\n'.join(content.split(
                f'<!-- project-status:{name}:start -->', 1)[1].split(
                f'<!-- project-status:{name}:end -->', 1)[0] for name in sections)
        for name, content in surfaces.items():
            if name not in ('source', 'frontier') and 'frontier' not in sync.TARGETS.get(name, ()):
                continue
            with self.subTest(surface=name):
                self.assertIn('three ordinary', content.lower())
                self.assertIn('not accepted', content.lower())
                self.assertIn('Final CPU Validation', content)
                self.assertNotIn('No #268 acceptance or physical execution is asserted here', content)
                self.assertNotIn('R8K_QWEN_CUDA_ORDINARY_OPERATOR_PATH_PASS', content)
                self.assertNotIn('Issue #255 is pending', content)

    def test_268_compact_publication_is_digest_bound_and_nonterminal(self):
        area = sync.ROOT / 'docs/implementation/ordinary-operator-path-268'
        evidence = area / 'evidence'
        compact = json.loads((evidence / 'physical-observation.json').read_text())
        self.assertEqual(compact['measured_product_head'],
                         '478eb5efc93476dc2be990ac738c7ddd40e11eab')
        self.assertEqual(compact['acceptance'], 'NOT_ACCEPTED')
        self.assertIn('DEFERRED', compact['final_cpu_validation'])
        self.assertEqual(compact['original_observer_status'], 'INCOMPLETE')
        self.assertEqual(compact['continuation_attempted_indices'], [2, 3])
        self.assertEqual(len(compact['requests']), 3)
        self.assertEqual([r['client']['positive_sm'] for r in compact['requests']],
                         [8, 8, 9])
        self.assertEqual([r['remote']['positive_sm'] for r in compact['requests']],
                         [0, 0, 0])
        self.assertEqual(len({r['response_id'] for r in compact['requests']}), 3)
        self.assertEqual(len({r['lease_token'] for r in compact['requests']}), 3)
        raw = {relative:digest for digest, relative in (line.split('  ', 1)
              for line in (evidence / 'RAW-MANIFEST.sha256').read_text().splitlines())}
        self.assertEqual(len(raw), 12)
        for request in compact['requests']:
            self.assertEqual(request['raw_receipt_sha256'],
                             raw[request['raw_receipt']])
            self.assertEqual(request['remote']['cuda_graph_lines'], 4)
            self.assertEqual(request['remote']['log_delta_bytes'], [1258, 1498])
            self.assertEqual(request['backing']['owned_remote_startup_cache_opens'], 9)
            self.assertTrue(request['cleanup']['exact_owner_absent'])
        covered = {}
        for row in (evidence / 'MANIFEST.sha256').read_text().splitlines():
            digest, relative = row.split('  ', 1)
            self.assertNotIn(relative, covered)
            self.assertNotEqual(relative,
                'docs/implementation/ordinary-operator-path-268/evidence/MANIFEST.sha256')
            covered[relative] = digest
            self.assertEqual(hashlib.sha256((sync.ROOT / relative).read_bytes()).hexdigest(),
                             digest)
        prefix = 'docs/implementation/ordinary-operator-path-268/'
        self.assertEqual(set(covered), {prefix + path for path in (
            'product-report.md', 'evidence/RAW-MANIFEST.sha256',
            'evidence/physical-observation.json',
            *(f'evidence/retained-producers/{name}' for name in (
                'acceptance-observer.py', 'continue-ordinary-acceptance.py',
                'test_acceptance_observer.py', 'test_continue_ordinary_acceptance.py')),
        )})

    def test_accepted_prerequisite_does_not_authorize_execution(self):
        self.record['frontier']['execution']['state'] = 'blocked'
        self.record['frontier']['execution']['reference'] = None
        self.assertIn('authorization:** blocked', sync.render(self.record)['frontier'])

    def test_missing_or_inconsistent_authority_fails(self):
        mutations = [
            lambda r: r['frontier']['execution'].update(state='maybe'),
            lambda r: r['frontier']['prerequisite']['observation'].update(reference=None),
            lambda r: r['capabilities'][0]['acceptance'].update(reference=None),
            lambda r: r['capabilities'][0]['observation'].update(result=None, reference=None),
        ]
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                record = copy.deepcopy(self.record)
                mutate(record)
                with self.assertRaises(ValueError):
                    sync.render(record)

    def test_schema_scope_duplicates_and_unsafe_links_fail(self):
        mutations = [
            lambda r: r.update(schema='unknown'),
            lambda r: r.update(extra=True),
            lambda r: r['capabilities'][0].update(scope='universal'),
            lambda r: r['capabilities'].append(copy.deepcopy(r['capabilities'][0])),
            lambda r: r['frontier'].update(reference='javascript:alert(1)'),
            lambda r: r['frontier'].update(title='title\n<!-- injected -->'),
        ]
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                record = copy.deepcopy(self.record)
                mutate(record)
                with self.assertRaises(ValueError):
                    sync.render(record)

if __name__ == '__main__':
    unittest.main()
