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

if __name__ == '__main__':
    unittest.main()
