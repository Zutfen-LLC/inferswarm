"""Documentation drift and preservation regressions; no network or runtime work."""
import contextlib
import copy
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
        for path, rows in sync.LIVE_ROWS.items():
            target = root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            for row in rows:
                file = root / row
                if not file.exists():
                    file.parent.mkdir(parents=True, exist_ok=True)
                    file.write_text('workflow fixture\n')
            target.write_text(''.join('0' * 64 + '  ' + row + '\n' for row in rows)
                              + 'a' * 64 + '  frozen/result.json\n')

    def run_main(self, root, *args):
        with patch.object(sync, 'ROOT', root), contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(io.StringIO()):
            return sync.main(list(args))

    def snapshot(self, root):
        return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*') if p.is_file()}

    def test_committed_sections_and_living_manifest_rows_are_current(self):
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
            self.record['frontier']['execution']['state'] = 'blocked'
            self.record['frontier']['execution']['reference'] = None
            (root / sync.SOURCE).write_text(json.dumps(self.record))
            updates = sync.prepare_updates(root)
            for path in sync.TARGETS:
                self.assertIn(b'authorization:** blocked', updates[path])
            self.assertEqual(self.run_main(root, '--write'), 0)
            target = root / 'README.md'
            target.write_text(target.read_text().replace('authorization:** blocked', 'authorization:** authorized'))
            before = target.read_bytes()
            self.assertEqual(self.run_main(root), 1)
            self.assertEqual(target.read_bytes(), before)

    def test_manifest_refresh_preserves_all_frozen_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.fixture(root)
            self.assertEqual(self.run_main(root, '--write'), 0)
            for path in sync.LIVE_ROWS:
                self.assertTrue((root / path).read_bytes().endswith(
                    b'a' * 64 + b'  frozen/result.json\n'))
            self.assertFalse((root / 'frozen/result.json').exists())

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

    def test_observed_pass_does_not_imply_acceptance_or_authorization(self):
        self.record['frontier']['prerequisite']['acceptance'] = {'state': 'pending', 'reference': None}
        self.record['frontier']['execution']['state'] = 'blocked'
        self.record['frontier']['execution']['reference'] = None
        output = sync.render(self.record)['frontier']
        self.assertIn('ISSUE117_PHYSICAL_PREFLIGHT_PASS', output)
        self.assertIn('pending maintainer acceptance', output)
        self.assertIn('authorization:** blocked', output)

    def test_accepted_prerequisite_does_not_authorize_execution(self):
        self.record['frontier']['execution']['state'] = 'blocked'
        self.record['frontier']['execution']['reference'] = None
        self.assertIn('authorization:** blocked', sync.render(self.record)['frontier'])

    def test_missing_or_inconsistent_authority_fails(self):
        mutations = [
            lambda r: r['frontier']['execution'].update(reference=None),
            lambda r: r['frontier']['prerequisite']['acceptance'].update(state='pending', reference=None),
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

    def test_missing_manifest_row_fails_before_any_write(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.fixture(root)
            manifest = root / next(iter(sync.LIVE_ROWS))
            manifest.write_text('\n'.join(manifest.read_text().splitlines()[1:]) + '\n')
            before = self.snapshot(root)
            self.assertEqual(self.run_main(root, '--write'), 1)
            self.assertEqual(self.snapshot(root), before)


if __name__ == '__main__':
    unittest.main()
