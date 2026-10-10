"""Offline RED-first /2 identity/parser safety; reconciliation remains unsupported."""
import copy
from dataclasses import fields, replace
import hashlib
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from inferswarm.operator import phased_observation as contract
from inferswarm.operator.bindings import TransportReply
from inferswarm.operator.profiles import canonical, thaw


def build_manifest():
    return {
        'schema': 'q8-native-build-manifest/2',
        'base_revision': contract.PINNED_BASE_REVISION,
        'base_tree': contract.PINNED_BASE_TREE,
        'patch_sha256': '1' * 64, 'transformed_manifest_sha256': '2' * 64,
        'protocol': contract.NATIVE_STREAM_SCHEMA, 'compiler': 'fixture-c++ version 1',
        'build_options': ['-O2', '-DOBSERVE=1'], 'executable_sha256': '3' * 64,
        'backend_libraries': [{'name': 'libggml.so', 'sha256': '4' * 64},
                              {'name': 'libcpu.so', 'sha256': '5' * 64}],
    }


def seal(record):
    record['terminal_digest'] = hashlib.sha256(canonical(
        {k: v for k, v in record.items() if k != 'terminal_digest'})).hexdigest()
    return record


def stream_record(phase='static', *, numbers=None, facts=None):
    """Same otherwise-valid fixture on retained predecessor and current schema.

    The predecessor lacks completeness fields; keep its fixtures legal so the
    retained behavioral replay cannot fail merely at an unrelated schema guard.
    """
    numbers = ([] if phase == 'static' else [0, 1]) if numbers is None else numbers
    record = {
        'schema': contract.NATIVE_STREAM_SCHEMA, 'phase': phase,
        'participant_id': 'node-a', 'plan_digest': 'a' * 64,
        'invocation_token': 'inv-1', 'stream_generation': 'stream-1',
        'sequence': [{'sequence': n, 'event': 'native-event'} for n in numbers],
        'terminal': True, 'facts': {'inventory': [{'name': 'observed', 'shape': [2, 3]}]}
        if facts is None else facts,
    }
    if 'stream_kind' in {f.name for f in fields(contract.ParsedObservation)}:
        record.update(stream_kind='snapshot' if phase == 'static' and not numbers else 'whole',
                      sequence_start=0, terminal_sequence=len(numbers), event_count=len(numbers),
                      snapshot_fence=phase == 'static' and not numbers,
                      dropped_events=0, overflow=False)
    return seal(record)


def parse(record):
    return contract.parse_observation(TransportReply(0, json.dumps(record).encode()))


def plan_fixture():
    participant = SimpleNamespace(participant_id='node-a', role='client', runtime_sha256='d' * 64)
    assignment = SimpleNamespace(state_id='weight-0', binding_id='cpu0', memory_id='ram0',
                                 member='member.gguf', absolute_offset=32, encoded_bytes=64)
    state = SimpleNamespace(state_id='state-0', binding_id='cpu0', memory_id='ram0', representation='f32')
    return SimpleNamespace(digest='a' * 64, selection='cpu-only', participants=(participant,),
                           metadata=SimpleNamespace(digest='e' * 64), candidate=SimpleNamespace(
                               assignments=(assignment,), required_state=(state,)))


def static_fixture():
    plan = plan_fixture()
    source = {'schema': 'q8-source-receipt/1', 'participant_id': 'node-a', 'role': 'client',
              'status': 'VERIFIED-not-consumed', 'plan_digest': plan.digest,
              'metadata_digest': plan.metadata.digest, 'runtime_sha256': 'd' * 64,
              'physical_observation': False, 'cache_consumed': False}
    facts = {'weights': [{'state_id': 'weight-0', 'binding_id': 'cpu0', 'memory_id': 'ram0',
                         'member': 'member.gguf', 'offset': 32, 'length': 64}],
             'persistent_states': [{'state_id': 'state-0', 'binding_id': 'cpu0',
                                    'memory_id': 'ram0', 'representation': 'f32'}],
             'completed_request_copies': [],
             'source_receipt_digest': hashlib.sha256(canonical(source)).hexdigest()}
    return plan, parse(stream_record(facts=facts)), {'node-a': source}


def dynamic_fixture(empty=False):
    plan = plan_fixture()
    kwargs = dict(invocation_token='inv-1', request_nonce='nonce-1', task_id='task-1', response_id='resp-1')
    # Only this old single-generation fixture needs adapting for old-byte replay.
    if 'graph_generations' in {f.name for f in fields(contract.RequestIdentity)}:
        kwargs['graph_generations'] = (4,)
    else:
        kwargs['graph_generation'] = 4
    request = contract.RequestIdentity(**kwargs)
    static = contract.PhaseReceipt(contract.RECEIPT_SCHEMA, 'static', 'STATIC_ADMITTED',
                                   plan.digest, 'cpu-only', 'inv-1', 'c' * 64, True, False, False)
    facts = {'request_nonce': 'nonce-1', 'task_id': 'task-1', 'response_id': 'resp-1',
             'graph_generation': 4, 'terminal_event': True,
             'events': [] if empty else [{'event_id': 'copy-1', 'sequence': 0,
                                          'invocation_token': 'inv-1', 'request_nonce': 'nonce-1'}]}
    return plan, static, parse(stream_record('dynamic', facts=facts)), request


class BehavioralRegressionTests(unittest.TestCase):
    """These exact methods also run against authenticated predecessor bytes."""

    def test_static_partial_reconciler_refuses_otherwise_valid_inventory(self):
        plan, stream, sources = static_fixture()
        with self.assertRaisesRegex(ValueError, 'static incomplete reconciliation'):
            contract.reconcile_static(plan, (stream,), sources)

    def test_dynamic_partial_reconciler_refuses_otherwise_valid_terminal(self):
        plan, static, stream, request = dynamic_fixture()
        with self.assertRaisesRegex(ValueError, 'dynamic incomplete reconciliation'):
            contract.reconcile_dynamic(plan, static, (stream,), request)

    def test_empty_dynamic_catalog_cannot_mint_acceptance(self):
        plan, static, stream, request = dynamic_fixture(empty=True)
        with self.assertRaisesRegex(ValueError, 'dynamic incomplete reconciliation'):
            contract.reconcile_dynamic(plan, static, (stream,), request)

    def test_gapped_sequence_cannot_parse_as_whole_stream(self):
        record = stream_record('dynamic', numbers=[3, 5])
        with self.assertRaisesRegex(ValueError, 'contiguous declared interval'):
            parse(record)

    def test_parsed_sequence_has_no_mutable_rows(self):
        parsed = parse(stream_record('dynamic'))
        with self.assertRaises(TypeError):
            parsed.sequence[0]['event'] = 'forged'

    def test_direct_constructor_defensively_snapshots_facts(self):
        original = parse(stream_record())
        mutable = thaw(original.facts)
        before = copy.deepcopy(mutable)
        constructed = replace(original, facts=mutable)
        self.assertEqual(mutable, before)
        mutable['inventory'][0]['shape'].append(99)
        self.assertEqual(thaw(constructed.facts), before)

    def test_direct_constructor_defensively_snapshots_sequence(self):
        original = parse(stream_record('dynamic'))
        rows = thaw(original.sequence)
        before = copy.deepcopy(rows)
        constructed = replace(original, sequence=rows)
        self.assertEqual(rows, before)
        rows[0]['event'] = 'forged'
        self.assertEqual(thaw(constructed.sequence), before)

    def test_direct_constructor_rejects_invalid_schema(self):
        with self.assertRaisesRegex(ValueError, 'schema'):
            replace(parse(stream_record()), schema='unsupported/9')

    def test_direct_constructor_rejects_bool_sequence_integer(self):
        record = stream_record('dynamic', numbers=[0])
        record['sequence'][0]['sequence'] = False
        seal(record)
        valid = parse(stream_record('dynamic', numbers=[0]))
        with self.assertRaisesRegex(ValueError, 'sequence.*integer'):
            replace(valid, sequence=record['sequence'], terminal_digest=record['terminal_digest'])

    def test_direct_constructor_rejects_forged_terminal_digest(self):
        with self.assertRaisesRegex(ValueError, 'terminal digest mismatch'):
            replace(parse(stream_record()), terminal_digest='b' * 64)

    def test_build_direct_constructor_rejects_wrong_base(self):
        identity = contract.parse_build_manifest(build_manifest())
        with self.assertRaisesRegex(ValueError, 'base identity mismatch'):
            replace(identity, base_revision='a' * 40)

    def test_build_direct_constructor_rejects_bad_manifest_digest(self):
        identity = contract.parse_build_manifest(build_manifest())
        with self.assertRaisesRegex(ValueError, 'manifest digest mismatch'):
            replace(identity, manifest_sha256='b' * 64)

    def test_build_direct_constructor_defensively_snapshots_options(self):
        identity = contract.parse_build_manifest(build_manifest())
        options = list(identity.build_options)
        libraries = [list(row) for row in identity.backend_libraries]
        rebuilt = replace(identity, build_options=options, backend_libraries=libraries)
        options.append('-bad')
        libraries[0][1] = 'f' * 64
        self.assertEqual(rebuilt, identity)

    def test_zero_patch_cannot_claim_derived_observer_build(self):
        manifest = build_manifest()
        manifest['patch_sha256'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'patch_sha256.*nonzero'):
            contract.parse_build_manifest(manifest)

    def test_zero_transformed_manifest_cannot_claim_derived_observer_build(self):
        manifest = build_manifest()
        manifest['transformed_manifest_sha256'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'transformed_manifest_sha256.*nonzero'):
            contract.parse_build_manifest(manifest)


class ByteguardRegressionTests(unittest.TestCase):
    """Tiny ordering regressions replayed unchanged on the retained predecessor."""

    def _assert_early_refusal(self, facts, cap=1024, *, wire=False):
        record = stream_record(facts=facts)
        payload = json.dumps(record, separators=(',', ':'), ensure_ascii=False).encode('utf-8')
        if wire:
            self.assertLess(len(payload), cap, 'must reach canonical guard, not raw transport guard')
        construct = (lambda: contract.parse_observation(TransportReply(0, payload))) if wire else (
            lambda: contract.ParsedObservation(**record))
        # Independent seal and successful uninstrumented construction rule out
        # schema/digest/primitive failures masquerading as byte containment.
        construct()
        material = {k: v for k, v in record.items() if k != 'terminal_digest'}
        self.assertGreater(len(canonical(material)), cap)
        full_serializations = []
        streams = []
        real_canonical = contract.canonical
        real_iterencode = json.JSONEncoder.iterencode

        def observe_full(value):
            encoded = real_canonical(value)
            full_serializations.append(len(encoded))
            return encoded

        def observe_chunks(encoder, value, *args, **kwargs):
            stats = {'bytes': 0, 'chunks': 0, 'max_chunk': 0, 'finished': False}
            streams.append(stats)
            for chunk in real_iterencode(encoder, value, *args, **kwargs):
                stats['bytes'] += len(chunk)
                stats['chunks'] += 1
                stats['max_chunk'] = max(stats['max_chunk'], len(chunk))
                yield chunk
            stats['finished'] = True

        with patch.object(contract, 'MAX_OBSERVATION_BYTES', cap), \
                patch.object(contract, 'canonical', side_effect=observe_full), \
                patch.object(json.JSONEncoder, 'iterencode', new=observe_chunks):
            with self.assertRaisesRegex(ValueError, '^oversized observation payload$'):
                construct()
        self.assertEqual([n for n in full_serializations if n > cap], [],
                         'over-budget full canonical aggregates allocated before refusal')
        self.assertEqual(len(streams), 1, 'oversized envelope must stop before digest encoding')
        self.assertFalse(streams[0]['finished'], 'over-budget envelope must not finish encoding')
        self.assertGreater(streams[0]['bytes'], cap)
        self.assertLessEqual(streams[0]['bytes'], cap + streams[0]['max_chunk'])
        self.assertLessEqual(streams[0]['max_chunk'], 6 * contract.MAX_TEXT_BYTES + 3)

    def test_repeated_string_occurrences_stop_before_full_aggregation(self):
        self._assert_early_refusal({'rows': ['x' * 64] * 16})

    def test_repeated_container_occurrences_stop_before_full_aggregation(self):
        row = {'nested': ['x' * 64, 'y' * 64]}
        self._assert_early_refusal({'rows': [row] * 8})

    def test_unicode_ascii_escape_expansion_stops_before_full_aggregation(self):
        record = stream_record(facts={'rows': ['\u00e9' * 32] * 4})
        self.assertLess(len(json.dumps(record, separators=(',', ':'), ensure_ascii=False).encode()), 1024)
        for wire in (False, True):
            with self.subTest(wire=wire):
                self._assert_early_refusal(record['facts'], wire=wire)

    def test_large_keys_and_escaped_controls_stop_before_full_aggregation(self):
        for facts in ({'\u00e9' * 2048: 0}, {'rows': ['\x01\n\t\\\"' * 16] * 4}):
            with self.subTest(facts_kind='large-key' if 'rows' not in facts else 'controls'):
                self._assert_early_refusal(facts)

    def test_valid_digest_uses_incremental_chunks_not_unbounded_canonical(self):
        record = stream_record('dynamic', facts={'rows': ['\u00e9', -0.0, -(1 << 63), (1 << 63) - 1]})
        expected = canonical({k: v for k, v in record.items() if k != 'terminal_digest'})
        updates = []
        real_sha256 = hashlib.sha256

        class DigestWitness:
            def __init__(self):
                self.digest = real_sha256()

            def update(self, chunk):
                updates.append(chunk)
                self.digest.update(chunk)

            def hexdigest(self):
                return self.digest.hexdigest()

        with patch.object(contract, 'canonical', side_effect=AssertionError('unbounded observation canonical path')), \
                patch.object(hashlib, 'sha256', side_effect=DigestWitness):
            constructed = contract.ParsedObservation(**record)
        self.assertGreater(len(updates), 1)
        self.assertEqual(b''.join(updates), expected)
        self.assertEqual(constructed.terminal_digest, record['terminal_digest'])


class ByteguardCoverageTests(unittest.TestCase):
    """Existing-correct boundaries and /2 semantic parity, not claimed REDs."""

    def test_exact_complete_cap_and_one_byte_over_include_terminal_digest(self):
        record = stream_record(facts={'rows': ['x' * 64] * 4})
        material = {k: v for k, v in record.items() if k != 'terminal_digest'}
        complete_size = len(canonical(record))
        material_size = len(canonical(material))
        self.assertEqual(complete_size - material_size, len(b',"terminal_digest":"' + b'a' * 64 + b'"'))
        for path in (lambda: contract.ParsedObservation(**record),
                     lambda: contract.parse_observation(TransportReply(0, canonical(record)))):
            with self.subTest(path=path):
                with patch.object(contract, 'MAX_OBSERVATION_BYTES', complete_size):
                    self.assertEqual(path().terminal_digest, record['terminal_digest'])
                for cap in (complete_size - 1, material_size):
                    with patch.object(contract, 'MAX_OBSERVATION_BYTES', cap):
                        with self.assertRaisesRegex(ValueError, '^oversized observation payload$'):
                            path()

    def test_constructor_and_real_parse_preserve_canonical_scalar_digests(self):
        facts = {'\u00e9-key': ['\u00e9', '\U0001f600', '\x01\n\t\\\"', None, True, False,
                            -(1 << 63), (1 << 63) - 1, -0.0, 0.0, 1.5, 1e-300, 1e300],
                 'empty-array': [], 'empty-object': {}, 'nested': [{'v': [3, 2, 1]}]}
        for phase in ('static', 'dynamic'):
            record = stream_record(phase, facts=facts)
            before = copy.deepcopy(record)
            # Noncanonical UTF-8 wire bytes still bind the exact canonical /2 hash.
            payload = json.dumps(record, ensure_ascii=False).encode('utf-8')
            direct = contract.ParsedObservation(**record)
            parsed = contract.parse_observation(TransportReply(0, payload))
            self.assertEqual(direct, parsed)
            self.assertEqual(record, before)
            self.assertEqual(canonical(thaw(direct.facts)), canonical(facts))
            self.assertEqual(direct.terminal_digest, record['terminal_digest'])
            self.assertIn(b'-0.0', canonical(thaw(direct.facts)))

    def test_constructor_and_parse_keep_primitive_refusal_reasons(self):
        for value in (float('inf'), float('-inf'), float('nan')):
            record = stream_record()
            record['facts'] = {'v': value}
            for path in (lambda: contract.ParsedObservation(**record), lambda: parse(record)):
                with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'nonfinite observation number'):
                    path()
        for facts, reason in (({'v': '\x00'}, 'text exceeds limit or contains NUL'),
                              ({'x' * 4097: 0}, 'observation key text exceeds limit'),
                              ({'v': 'x' * 65537}, 'text exceeds limit'),
                              ({'v': 1 << 63}, 'integer outside bounds')):
            record = stream_record(facts=facts)
            for path in (lambda: contract.ParsedObservation(**record), lambda: parse(record)):
                with self.subTest(reason=reason), self.assertRaisesRegex(ValueError, reason):
                    path()

    def test_incomplete_outcomes_and_reconcilers_remain_refused(self):
        record = stream_record('dynamic')
        record['terminal'] = False
        with self.assertRaisesRegex(ValueError, 'whole stream requires terminal fence'):
            contract.ParsedObservation(**seal(record))
        static = contract.ParsedObservation(**stream_record())
        with self.assertRaisesRegex(ValueError, 'static incomplete reconciliation: unsupported admission'):
            contract.reconcile_static(None, (static,), {})
        with self.assertRaisesRegex(ValueError, 'dynamic incomplete reconciliation: unsupported acceptance'):
            contract.reconcile_dynamic(None, None, (), None)


class PhasedObservationContractTests(unittest.TestCase):
    def test_module_exposes_distinct_contracts(self):
        self.assertEqual(contract.BUILD_SCHEMA, 'q8-owned-observation/2')
        self.assertEqual(contract.RECEIPT_SCHEMA, 'q8-observation-receipt/2')
        self.assertEqual(contract.NATIVE_STREAM_SCHEMA, 'inferswarm-native-observation/2')

    def test_valid_static_snapshot_parses_without_execution_claim(self):
        record = stream_record()
        before = copy.deepcopy(record)
        parsed = parse(record)
        self.assertEqual(record, before)
        self.assertTrue(parsed.terminal)
        self.assertEqual(parsed.stream_kind, 'snapshot')
        self.assertEqual(parsed.sequence, ())
        self.assertEqual(thaw(parsed.facts), record['facts'])
        self.assertEqual(copy.deepcopy(parsed), parsed)

    def test_valid_dynamic_whole_stream_parses(self):
        parsed = parse(stream_record('dynamic'))
        self.assertEqual(parsed.stream_kind, 'whole')
        self.assertEqual(parsed.event_count, 2)
        self.assertEqual(parsed.terminal_sequence, 2)

    def test_prefix_is_explicit_nonterminal_not_snapshot(self):
        record = stream_record('dynamic')
        record.update(stream_kind='prefix', terminal=False)
        parsed = parse(seal(record))
        self.assertFalse(parsed.terminal)
        self.assertEqual(parsed.stream_kind, 'prefix')
        record['terminal'] = True
        with self.assertRaisesRegex(ValueError, 'prefix.*nonterminal'):
            parse(seal(record))

    def test_empty_static_requires_explicit_snapshot_fence(self):
        record = stream_record()
        record['snapshot_fence'] = False
        with self.assertRaisesRegex(ValueError, 'snapshot fence'):
            parse(seal(record))
        record.update(snapshot_fence=False, stream_kind='whole')
        with self.assertRaisesRegex(ValueError, 'empty static.*snapshot'):
            parse(seal(record))

    def test_dynamic_cannot_use_empty_static_snapshot(self):
        record = stream_record()
        record['phase'] = 'dynamic'
        with self.assertRaisesRegex(ValueError, 'snapshot.*static'):
            parse(seal(record))

    def test_empty_dynamic_whole_requires_native_events(self):
        with self.assertRaisesRegex(ValueError, 'dynamic whole.*events'):
            parse(stream_record('dynamic', numbers=[]))

    def test_whole_stream_cannot_start_at_arbitrary_counter(self):
        record = stream_record('dynamic', numbers=[3, 4])
        record.update(sequence_start=3, terminal_sequence=5)
        with self.assertRaisesRegex(ValueError, 'whole.*start at zero'):
            parse(seal(record))

    def test_noncontiguous_duplicate_and_reversed_sequences_reject(self):
        for numbers in ([0, 2], [0, 0], [1, 0]):
            with self.subTest(numbers=numbers), self.assertRaisesRegex(ValueError, 'contiguous declared interval'):
                parse(stream_record('dynamic', numbers=numbers))

    def test_declared_interval_and_count_match_rows(self):
        for field in ('terminal_sequence', 'event_count'):
            record = stream_record('dynamic')
            record[field] = 3
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'declared.*(interval|count)'):
                parse(seal(record))

    def test_drop_and_overflow_are_named_refusals_after_valid_schema(self):
        for field, value, reason in (('dropped_events', 1, 'dropped events'), ('overflow', True, 'overflow')):
            record = stream_record('dynamic')
            record[field] = value
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, reason):
                parse(seal(record))

    def test_digest_binds_each_envelope_field(self):
        changes = {'participant_id': 'node-b', 'plan_digest': 'b' * 64,
                   'invocation_token': 'inv-2', 'stream_generation': 'stream-2',
                   'sequence_start': 1, 'terminal_sequence': 3, 'event_count': 3,
                   'dropped_events': 1, 'overflow': True, 'snapshot_fence': True,
                   'stream_kind': 'prefix', 'terminal': False,
                   'phase': 'static', 'facts': {'inventory': []},
                   'sequence': [{'sequence': 0, 'event': 'changed'}, {'sequence': 1, 'event': 'native-event'}]}
        for field, value in changes.items():
            record = stream_record('dynamic')
            record[field] = value
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'terminal digest mismatch'):
                parse(record)

    def test_resealed_truncation_still_fails_declared_interval(self):
        record = stream_record('dynamic')
        record['sequence'].pop()
        with self.assertRaisesRegex(ValueError, 'declared.*(interval|count)'):
            parse(seal(record))

    def test_transport_status_checked_before_invalid_json(self):
        for code in (7, True, 0.0):
            with self.subTest(code=code), self.assertRaisesRegex(ValueError, 'transport exit'):
                contract.parse_observation(TransportReply(code, b'not-json'))
        with self.assertRaisesRegex(ValueError, 'typed.*transport'):
            contract.parse_observation(b'{}')
        with self.assertRaisesRegex(ValueError, 'payload must be bytes'):
            contract.parse_observation(TransportReply(0, '{}'))

    def test_truncated_utf8_and_json_refuse(self):
        for payload in (b'\xff', b'{', b''):
            with self.subTest(payload=payload), self.assertRaisesRegex(ValueError, 'invalid observation JSON'):
                contract.parse_observation(TransportReply(0, payload))

    def test_duplicate_top_level_and_nested_keys_refuse(self):
        payload = json.dumps(stream_record()).encode()
        for raw in (payload.replace(b'"schema":', b'"schema":"duplicate", "schema":', 1),
                    payload.replace(b'"name": "observed"', b'"name":"observed","name":"observed"')):
            with self.subTest(raw=raw), self.assertRaisesRegex(ValueError, 'duplicate'):
                contract.parse_observation(TransportReply(0, raw))

    def test_nonfinite_numbers_refuse_before_digest(self):
        for value in ('NaN', 'Infinity', '-Infinity', '1e999'):
            payload = json.dumps(stream_record()).replace('"shape": [2, 3]', '"shape": [' + value + ']').encode()
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'nonfinite'):
                contract.parse_observation(TransportReply(0, payload))

    def test_unknown_or_missing_fields_refuse(self):
        for target in ('envelope', 'sequence'):
            for action in ('add', 'delete'):
                record = stream_record('dynamic')
                row = record if target == 'envelope' else record['sequence'][0]
                if action == 'add':
                    row['extra'] = 1
                else:
                    del row['phase' if target == 'envelope' else 'event']
                with self.subTest(target=target, action=action), self.assertRaisesRegex(ValueError, 'fields must be exactly'):
                    parse(seal(record))

    def test_scalar_types_refuse_bool_as_integer(self):
        for field in ('sequence_start', 'terminal_sequence', 'event_count', 'dropped_events'):
            record = stream_record('dynamic')
            record[field] = True
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, field + '.*integer'):
                parse(seal(record))
        for field in ('terminal', 'overflow', 'snapshot_fence'):
            record = stream_record('dynamic')
            record[field] = 1
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, field + '.*boolean'):
                parse(seal(record))

    def test_byte_row_depth_string_and_integer_bounds(self):
        with self.assertRaisesRegex(ValueError, 'oversized observation payload'):
            contract.parse_observation(TransportReply(0, b' ' * (contract.MAX_OBSERVATION_BYTES + 1)))
        cases = [({'rows': [None] * (contract.MAX_ROWS + 1)}, 'row limit'),
                 ({'string': 'x' * 65537}, 'text exceeds limit'),
                 ({'number': 1 << 63}, 'integer outside bounds'),
                 ({'number': -(1 << 63) - 1}, 'integer outside bounds')]
        deep = 0
        for _ in range(34):
            deep = [deep]
        cases.append(({'nested': deep}, 'nesting exceeds limit'))
        for facts, reason in cases:
            with self.subTest(reason=reason), self.assertRaisesRegex(ValueError, reason):
                parse(stream_record(facts=facts))

    def test_total_node_budget_is_bounded(self):
        record = stream_record(facts={'rows': [[None] * 1000 for _ in range(70)]})
        with self.assertRaisesRegex(ValueError, 'node limit'):
            parse(record)

    def test_direct_constructor_primitives_cannot_bypass_bounds(self):
        valid = parse(stream_record())
        for facts, reason in (({'v': object()}, 'unsupported observation primitive'),
                              ({'v': float('inf')}, 'nonfinite'),
                              ({'v': 'x' * 65537}, 'text exceeds limit')):
            with self.subTest(reason=reason), self.assertRaisesRegex(ValueError, reason):
                replace(valid, facts=facts)

    def test_direct_constructor_deepcopy_preserves_frozen_rows(self):
        parsed = parse(stream_record('dynamic'))
        cloned = copy.deepcopy(parsed)
        self.assertEqual(parsed, cloned)
        inventory = dict(cloned.facts)['inventory']
        shape = dict(inventory[0])['shape']
        self.assertIsInstance(inventory, tuple)
        self.assertIsInstance(shape, tuple)
        with self.assertRaises(AttributeError):
            shape.append(4)

    def test_request_nonce_is_known_before_post(self):
        identity = contract.RequestIdentity('inv-1', 'nonce-1')
        self.assertIsNone(identity.task_id)
        self.assertIsNone(identity.response_id)
        self.assertEqual(identity.graph_generations, ())
        with self.assertRaises((AttributeError, TypeError)):
            identity.request_nonce = 'native-chosen'

    def test_request_later_binds_multiple_graph_generations_without_mutation(self):
        generations = [4, 5]
        identity = contract.RequestIdentity('inv-1', 'nonce-1', 'task-1', 'resp-1', generations)
        generations.append(6)
        self.assertEqual(identity.graph_generations, (4, 5))
        self.assertEqual(copy.deepcopy(identity), identity)

    def test_request_types_and_generation_bounds_are_strict(self):
        for kwargs in ({'invocation_token': False}, {'request_nonce': 4}, {'task_id': ''},
                       {'response_id': True}, {'graph_generations': [False]},
                       {'graph_generations': [-1]}, {'graph_generations': [4, 4]}):
            args = dict(invocation_token='inv-1', request_nonce='nonce-1')
            args.update(kwargs)
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                contract.RequestIdentity(**args)

    def test_build_exact_match_and_library_normalization(self):
        manifest = build_manifest()
        before = copy.deepcopy(manifest)
        actual = contract.parse_build_manifest(manifest)
        self.assertEqual(manifest, before)
        reordered = copy.deepcopy(manifest)
        reordered['backend_libraries'].reverse()
        expected = contract.parse_build_manifest(reordered)
        self.assertTrue(contract.native_build_matches(actual, expected))
        contract.require_native_build_match(actual, expected)
        self.assertEqual(copy.deepcopy(actual), actual)
        self.assertFalse(actual.is_unmodified_base)

    def test_legal_changed_components_have_specific_mismatch(self):
        expected = contract.parse_build_manifest(build_manifest())
        for component, value in (('patch_sha256', '6' * 64), ('transformed_manifest_sha256', '7' * 64),
                                 ('compiler', 'fixture-c++ version 2'), ('build_options', ['-DOBSERVE=1', '-O2']),
                                 ('executable_sha256', '8' * 64),
                                 ('backend_libraries', [{'name': 'libggml.so', 'sha256': '9' * 64}])):
            manifest = build_manifest()
            manifest[component] = value
            changed = contract.parse_build_manifest(manifest)
            with self.subTest(component=component):
                self.assertFalse(contract.native_build_matches(changed, expected))
                with self.assertRaisesRegex(ValueError, component + ' mismatch'):
                    contract.require_native_build_match(changed, expected)

    def test_build_base_and_protocol_refuse_specifically(self):
        for field, value, reason in (('base_revision', 'a' * 40, 'base identity mismatch'),
                                     ('base_tree', 'b' * 40, 'base identity mismatch'),
                                     ('protocol', 'inferswarm-native-observation/1', 'protocol mismatch')):
            manifest = build_manifest()
            manifest[field] = value
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, reason):
                contract.parse_build_manifest(manifest)

    def test_manifest_unknown_duplicate_library_and_bad_types_refuse(self):
        for field, value, reason in (('extra', True, 'fields must be exactly'),
                                     ('build_options', [], 'build options'),
                                     ('compiler', False, 'compiler'),
                                     ('patch_sha256', 'bad', 'SHA-256'),
                                     ('backend_libraries', [{'name': 'x', 'sha256': '4' * 64}] * 2, 'duplicate backend')):
            manifest = build_manifest()
            manifest[field] = value
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, reason):
                contract.parse_build_manifest(manifest)

    def test_direct_build_constructor_validates_each_component(self):
        identity = contract.parse_build_manifest(build_manifest())
        for kwargs, reason in (({'protocol': 'wrong/1'}, 'protocol mismatch'),
                               ({'patch_sha256': False}, 'SHA-256'),
                               ({'transformed_manifest_sha256': '0' * 64}, 'nonzero'),
                               ({'executable_sha256': 'bad'}, 'SHA-256'),
                               ({'backend_libraries': [('x', 'bad')]}, 'SHA-256'),
                               ({'build_options': [True]}, 'build option')):
            with self.subTest(kwargs=kwargs), self.assertRaisesRegex(ValueError, reason):
                replace(identity, **kwargs)


class StaticPlanContextTests(unittest.TestCase):
    """Original controller expectations, public metadata, SYNTHETIC resources."""

    def _inputs(self, selection='one-gpu'):
        from inferswarm.operator.plan import build_plan
        from tests.test_issue299_q8_plan import config, metadata
        from tests.issue299_fixture import NOW
        return build_plan(config(selection), now=NOW), metadata()

    def _derive(self, plan, metadata, original=None):
        return contract.derive_static_plan_context(plan, metadata,
            original_plan_digest=plan.digest if original is None else original)

    def test_retained_original_digest_cannot_be_replaced_by_coherent_new_plan(self):
        from inferswarm.operator.plan import build_plan
        from tests.issue299_fixture import NOW
        p, m = self._inputs()
        c = replace(p.config, plan_id='new-controller-plan')
        changed = build_plan(c, now=NOW)
        self.assertNotEqual(p.digest, changed.digest)
        with self.assertRaisesRegex(ValueError, '^static context original plan digest$'):
            self._derive(changed, m, p.digest)
        self.assertEqual(self._derive(changed, m).original_plan_digest, changed.digest)

    def test_resealed_digest_without_changed_input_refuses_integrity(self):
        p, m = self._inputs()
        changed = replace(p, digest='a' * 64)
        with self.assertRaisesRegex(ValueError, '^static context plan digest integrity mismatch$'):
            self._derive(changed, m)

    def test_all_mirrored_plan_fields_require_exact_config_equality(self):
        p, m = self._inputs()
        mutations = dict(plan_id='other', model=replace(p.model, source_id='other'),
            participants=p.participants[::-1], strategy_id='other', placement=p.placement[::-1],
            request=tuple((k, 'other' if k == 'prompt' else v) for k, v in p.request),
            selection='cpu-only', metadata=replace(p.metadata, path='/other'),
            profiles=replace(p.profiles, digest='a' * 64), policy=replace(p.policy, max_age_seconds=1),
            workload=replace(p.workload, context=p.workload.context+1),
            strategy_options=type(p.strategy_options)(reversed(p.strategy_options)))
        for field, value in mutations.items():
            with self.subTest(field=field), patch.object(contract, 'q8_static_inventory') as inventory, \
                    patch.object(contract, '_profiled_digest_from_metadata') as digest:
                with self.assertRaisesRegex(ValueError, '^static context plan field mismatch: '+field+'$'):
                    self._derive(replace(p, **{field:value}), m)
                inventory.assert_not_called(); digest.assert_not_called()

    def test_profile_normalized_identity_is_integrity_not_freshness(self):
        from inferswarm.operator.plan import revalidate_admission
        from datetime import timedelta
        from tests.issue299_fixture import NOW
        p, m = self._inputs()
        profile = replace(p.profiles, digest='a' * 64)
        changed = replace(p, profiles=profile, config=replace(p.config, profiles=profile))
        with self.assertRaisesRegex(ValueError, '^static context profile integrity mismatch$'):
            self._derive(changed, m)
        self.assertEqual(self._derive(p, m).config.profiles, p.profiles)
        self.assertTrue(any('expired evidence' in r for r in
                            revalidate_admission(p, now=NOW+timedelta(hours=2)).deficits))
        # Cached verdict never substitutes for current admission or integrity.
        forged = replace(p, admission=replace(p.admission, execution_ready=True, status='ADMITTED'))
        self.assertEqual(self._derive(forged, m), self._derive(p, m))

    def _alter(self, root, path, value):
        """Mutate caller-owned frozen records without constructor coercion."""
        root = copy.deepcopy(root)
        def change(node, parts):
            if not parts:
                return value
            first, *rest = parts
            node = copy.deepcopy(node)
            if type(first) is int:
                rows = list(node); rows[first] = change(rows[first], rest)
                return type(node)(rows)
            object.__setattr__(node, first, change(getattr(node, first), rest))
            return node
        return change(root, path)

    def _path(self, root, parts):
        return root+''.join('['+str(p)+']' if type(p) is int else '.'+p for p in parts)

    def _typed_refusal(self, p, m, path, original=None):
        import re
        with patch.object(contract, 'q8_static_inventory', side_effect=AssertionError('late inventory')) as inv, \
                patch.object(contract, '_profiled_digest_from_metadata', side_effect=AssertionError('late digest')) as dig, \
                patch('inferswarm.operator.profiles.parse_profiles', side_effect=AssertionError('late profiles')) as prof:
            with self.assertRaisesRegex(ValueError, '^static context typed input: '+re.escape(path)+'$'):
                self._derive(p, m, original)
            inv.assert_not_called(); dig.assert_not_called(); prof.assert_not_called()

    def test_closed_exact_roots_and_nested_record_classes(self):
        from dataclasses import make_dataclass
        p, m = self._inputs()
        for path in ((), ('config',), ('candidate',), ('config', 'workload'),
                     ('config', 'participants', 0), ('candidate', 'semantic_contract', 0)):
            node = p
            for part in path:
                node = node[part] if type(part) is int else getattr(node, part)
            derived = make_dataclass('DerivedRecord', [], bases=(type(node),), frozen=True)
            lookalike = make_dataclass('FrozenLookalike', [(f.name, object) for f in fields(node)], frozen=True)
            for cls in (derived, lookalike):
                with self.subTest(path=path, cls=cls.__name__):
                    self._typed_refusal(self._alter(p, path, cls(**vars(node))), m, self._path('plan', path))
        self._typed_refusal(p, SimpleNamespace(**vars(m)), 'metadata')

    def test_exact_numeric_and_boolean_slots_refuse_before_derivation(self):
        p, m = self._inputs()
        int_paths = [
            ('config', 'model', 'members', 0, 2), ('config', 'participants', 0, 'port'),
            ('config', 'participants', 0, 'backing', 0, 'size_bytes'),
            ('config', 'policy', 'max_age_seconds'), ('config', 'policy', 'memory_limits', 0, 'peak_bytes'),
            ('config', 'workload', 'context'), ('config', 'workload', 'slots'),
            ('config', 'workload', 'batch'), ('config', 'workload', 'microbatch'),
            ('config', 'placement', 0, 'state_ranges', 0, 2),
            ('config', 'profiles', 'snapshot', 'memory_resources', 0, 'total_bytes'),
            ('config', 'profiles', 'snapshot', 'links', 0, 'throughput_bytes_per_second'),
            ('candidate', 'assignments', 0, 'absolute_offset'), ('candidate', 'assignments', 0, 'encoded_bytes'),
            ('candidate', 'assignments', 0, 'ggml_type'), ('candidate', 'assignments', 0, 'shape', 0),
            ('candidate', 'required_state', 0, 'lower_bound_bytes'),
            ('candidate', 'boundaries', 0, 'before_layer'), ('candidate', 'boundaries', 0, 'logical_bytes'),
            ('candidate', 'boundaries', 0, 'shape', 0), ('candidate', 'boundaries', 0, 'strides', 0),
            ('candidate', 'charges', 0, 'bytes'), ('candidate', 'source_contract', 5, 'gpu_layers'),
            ('candidate', 'semantic_contract', 0, 'workload', 'slots'),
            ('admission', 'peaks', 0, 'peak_bytes'), ('admission', 'peaks', 0, 'phase_bytes', 0, 1)]
        for path in int_paths:
            for bad in (True, 1.0, '1', None):
                # Only schema-authorized optional integers permit None.
                if bad is None and path[-1] in ('lower_bound_bytes', 'bytes'):
                    continue
                with self.subTest(path=path, bad=bad):
                    self._typed_refusal(self._alter(p, path, bad), m, self._path('plan', path))
        for path in (('candidate', 'required_state', 0, 'reconstructible'),
                     ('candidate', 'source_contract', 5, 'kv_offload'),
                     ('candidate', 'source_contract', 5, 'op_offload'),
                     ('candidate', 'source_contract', 5, 'kv_unified'), ('admission', 'execution_ready')):
            for bad in (0, 1, 0.0, None):
                with self.subTest(path=path, bad=bad):
                    self._typed_refusal(self._alter(p, path, bad), m, self._path('plan', path))

    def test_bad_config_workload_precedes_bad_metadata_in_declaration_order(self):
        p, m = self._inputs()
        changed = copy.deepcopy(p)
        for field in ('context', 'slots', 'batch', 'microbatch'):
            object.__setattr__(changed.config.workload, field, 1.0)
        for field in ('context', 'slots', 'batch', 'microbatch'):
            self._typed_refusal(changed, (), 'plan.config.workload.'+field)
            object.__setattr__(changed.config.workload, field, getattr(p.config.workload, field))

    def test_mutable_and_tagged_object_array_shapes_refuse(self):
        from inferswarm.operator.profiles import FrozenMapping
        p, m = self._inputs()
        cases = [
            (('config', 'participants'), list(p.config.participants)),
            (('config', 'workload', 'cache_settings'), tuple(p.config.workload.cache_settings)),
            (('config', 'strategy_options'), tuple(p.config.strategy_options)),
            (('config', 'request'), FrozenMapping(p.config.request)),
            (('candidate', 'assignments', 0, 'shape'), list(p.candidate.assignments[0].shape)),
            (('candidate', 'semantic_contract', 0, 'links'), list(p.config.profiles.snapshot.links)),
            (('candidate', 'canonical_strategy_options'), {}),
            (('admission', 'deficits'), list(p.admission.deficits))]
        for path, bad in cases:
            with self.subTest(path=path):
                self._typed_refusal(self._alter(p, path, bad), m, self._path('plan', path))
        for path in (('tensors', 0, 'ggml_type'), ('tensors', 0, 'relative_offset'),
                     ('tensors', 0, 'shape', 0), ('header_identities', 0, 1),
                     ('header_identities', 0, 2), ('header_identities', 0, 4)):
            for bad in (True, 1.0, '1', None):
                with self.subTest(path=path, bad=bad):
                    self._typed_refusal(p, self._alter(m, path, bad), self._path('metadata', path))

    def test_lowercase_identity_strings_are_exact_typed_slots(self):
        p, m = self._inputs()
        for bad in (p.digest.upper(), True, 'a'*63, 'a'*64+' '):
            with self.subTest(original=bad):
                self._typed_refusal(p, m, 'original_plan_digest', bad)
        for path in (('digest',), ('config', 'metadata', 'sha256'),
                     ('config', 'metadata', 'digest'), ('config', 'profiles', 'digest'),
                     ('config', 'participants', 0, 'runtime_sha256')):
            self._typed_refusal(self._alter(p, path, 'A'*64), m, self._path('plan', path), p.digest)

    def test_context_constructor_checks_closed_shapes_before_detachment(self):
        p, m = self._inputs()
        from inferswarm.operator.qwen_q8 import q8_static_inventory
        inv = q8_static_inventory(p.config, m, candidate=p.candidate)
        bad = self._alter(p.config, ('workload', 'slots'), True)
        with self.assertRaisesRegex(ValueError, '^static context typed input: config.workload.slots$'):
            contract.StaticPlanContext(p.digest, bad, inv)
        bad_inv = self._alter(inv, ('persistent_caches', 0, 'native_dimensions', 0), 1.0)
        with self.assertRaisesRegex(ValueError, r'^static context typed input: inventory.persistent_caches\[0\].native_dimensions\[0\]$'):
            contract.StaticPlanContext(p.digest, p.config, bad_inv)
        with self.assertRaisesRegex(ValueError, '^static context typed input: original_plan_digest$'):
            contract.StaticPlanContext(p.digest.upper(), p.config, inv)

    def test_context_detaches_every_dataclass_and_preserves_internal_aliases(self):
        from dataclasses import is_dataclass, FrozenInstanceError
        from inferswarm.operator.qwen_q8 import q8_static_inventory
        p, m = self._inputs()
        inv = q8_static_inventory(p.config, m, candidate=p.candidate)
        # Constructor is a DESCRIPTION, not semantic derivation/authority.
        inv = replace(inv, metadata_source=p.config.model)
        direct = contract.StaticPlanContext(p.digest, p.config, inv)
        self.assertIs(direct.config.model, direct.inventory.metadata_source)
        derived = self._derive(p, m)
        self.assertEqual(derived, self._derive(copy.deepcopy(p), copy.deepcopy(m)))
        def nodes(value, result):
            if is_dataclass(value):
                result[id(value)] = value
                for f in fields(value): nodes(getattr(value, f.name), result)
            elif isinstance(value, tuple):
                for child in value: nodes(child, result)
        caller, retained = {}, {}
        nodes((p.config, inv, m), caller)
        nodes((direct, derived), retained)
        self.assertFalse(set(caller) & set(retained))
        before = copy.deepcopy((direct, derived))
        for node in caller.values():
            object.__setattr__(node, fields(node)[0].name, 'caller-mutated')
        self.assertEqual((direct, derived), before)
        with self.assertRaises(FrozenInstanceError):
            derived.original_plan_digest = 'a'*64
        with self.assertRaises(TypeError):
            derived.config.strategy_options[0] = ('x', True)

    def test_success_is_pure_and_has_no_observation_or_receipt_inputs(self):
        from contextlib import ExitStack
        import inspect
        p, m = self._inputs()
        expected = self._derive(p, m)
        with ExitStack() as stack:
            mocks = [stack.enter_context(patch(target, side_effect=AssertionError('context I/O/authority')))
                for target in ('builtins.open', 'pathlib.Path.open',
                    'inferswarm.operator.metadata.load_metadata_index', 'subprocess.run',
                    'subprocess.Popen', 'socket.socket',
                    'inferswarm.operator.phased_observation.PhaseReceipt')]
            self.assertEqual(self._derive(p, m), expected)
            for mock in mocks: mock.assert_not_called()
        self.assertEqual(tuple(inspect.signature(contract.derive_static_plan_context).parameters),
                         ('plan', 'metadata', 'original_plan_digest'))
        self.assertIn('StaticPlanContext', contract.__all__)
        self.assertIn('derive_static_plan_context', contract.__all__)

    def test_context_never_opens_actual_static_or_dynamic_reconcilers(self):
        p, m = self._inputs()
        context = self._derive(p, m)
        _, receipt, observation, request = dynamic_fixture()
        receipt = replace(receipt, plan_digest=p.digest, physical_qualified=True, execution_authorized=True)
        for value in (p, context):
            with self.subTest(value=type(value).__name__):
                with self.assertRaisesRegex(contract.IncompleteReconciliation,
                        '^static incomplete reconciliation: unsupported admission$'):
                    contract.reconcile_static(value, (observation,), {'forged': receipt})
                with self.assertRaisesRegex(contract.IncompleteReconciliation,
                        '^dynamic incomplete reconciliation: unsupported acceptance$'):
                    contract.reconcile_dynamic(value, receipt, (observation,), request)

    def test_every_candidate_field_is_independently_checked(self):
        from inferswarm.operator.profiles import freeze, thaw
        p, m = self._inputs(); c = p.candidate
        options = thaw(c.canonical_strategy_options); options['startup_timeout_seconds'] += 1
        values = dict(candidate_id='other', assignments=c.assignments[:-1],
            required_state=c.required_state[:-1], boundaries=c.boundaries[:-1], charges=c.charges[:-1],
            capability_requirements=c.capability_requirements[:-1],
            source_contract=('other',)+c.source_contract[1:], subject=replace(c.subject, mode='live'),
            required_charge_ids=c.required_charge_ids[:-1], calculated_evidence=('other',),
            unsupported=('UNSUPPORTED_PLACEMENT: synthetic mutation',),
            semantic_contract=(replace(c.semantic_contract[0], route='server-local'),),
            canonical_strategy_options=freeze(options))
        self.assertEqual(set(values), {f.name for f in fields(c)})
        for field, value in values.items():
            with self.subTest(field=field):
                with self.assertRaisesRegex(ValueError, '^inventory candidate mismatch: '+field+'$'):
                    self._derive(replace(p, candidate=replace(c, **{field:value})), m)

    def test_metadata_and_pin_mutations_propagate_existing_source_predicates(self):
        p, m = self._inputs()
        cases = [
            (replace(m, source=replace(m.source, revision='other')), 'model member identity authentication'),
            (replace(m, header_identities=(m.header_identities[0][:-1]+('a'*64,),)+m.header_identities[1:]),
                'model header identity authentication'),
            (replace(m, tensors=m.tensors[:-1]), 'coverage'),
            (replace(m, metadata_digest='a'*64), 'metadata descriptor authentication')]
        for changed, reason in cases:
            with self.subTest(reason=reason), self.assertRaisesRegex(ValueError, reason):
                self._derive(p, changed)
        runtime = p.config.profiles.snapshot.runtime_capabilities[0]
        snapshot = replace(p.config.profiles.snapshot,
            runtime_capabilities=(replace(runtime, source_revision='a'*40),)+p.config.profiles.snapshot.runtime_capabilities[1:])
        # Exact payload/hash law catches a changed typed profile before strategy.
        identity = replace(p.profiles, snapshot=snapshot)
        changed = replace(p, profiles=identity, config=replace(p.config, profiles=identity))
        with self.assertRaisesRegex(ValueError, 'evidence payload mismatch'):
            self._derive(changed, m)

    def test_metadata_path_exclusion_describes_without_actual_file_claim(self):
        p, m = self._inputs()
        identity = replace(p.metadata, path='/description/not-read')
        changed = replace(p, metadata=identity, config=replace(p.config, metadata=identity))
        context = self._derive(changed, m)
        self.assertEqual(context.original_plan_digest, p.digest)
        self.assertEqual(context.config.metadata.path, '/description/not-read')
        self.assertEqual(context.inventory, self._derive(p, m).inventory)

    def test_authorized_finite_float_slots_keep_their_exact_types(self):
        p, m = self._inputs()
        context = self._derive(p, m)
        self.assertIs(type(dict(context.config.request)['temperature']), float)
        self.assertIs(type(context.config.profiles.snapshot.links[0].latency_seconds), float)
        self.assertIs(type(dict(context.inventory.model_metadata)['general.sampling.temp']), float)
        for path in (('config', 'request', 3, 1),
                     ('config', 'profiles', 'snapshot', 'links', 0, 'latency_seconds')):
            self._typed_refusal(self._alter(p, path, float('inf')), m, self._path('plan', path))

    def test_nested_cache_options_payload_and_nullable_slot_shapes(self):
        p, m = self._inputs()
        cache = p.config.workload.cache_settings
        options = p.config.strategy_options
        key_index = lambda rows, key: next(i for i, (k, _) in enumerate(rows) if k == key)
        paths = [
            ('config', 'workload', 'cache_settings', key_index(cache, 'attention_cells'), 1),
            ('config', 'workload', 'cache_settings', key_index(cache, 'text_only'), 1),
            ('config', 'strategy_options', key_index(options, 'startup_timeout_seconds'), 1),
            ('candidate', 'semantic_contract', 0, 'bindings', 0, 1, 'binding_id')]
        for path in paths:
            for bad in (1.0, None):
                with self.subTest(path=path, bad=bad):
                    self._typed_refusal(self._alter(p, path, bad), m, self._path('plan', path))
        evidence_index = next(i for i, e in enumerate(p.config.profiles.snapshot.evidence)
                              if e.evidence_id == p.config.profiles.snapshot.memory_resources[0].evidence_id)
        evidence = p.config.profiles.snapshot.evidence[evidence_index]
        payload_index = key_index(evidence.payload, 'total_bytes')
        path = ('config', 'profiles', 'snapshot', 'evidence', evidence_index, 'payload', payload_index, 1)
        self._typed_refusal(self._alter(p, path, True), m, self._path('plan', path))
        for path in (('candidate', 'boundaries', 0, 'wire_bytes'),
                     ('admission', 'peaks', 0, 'bounded_peak_bytes')):
            for bad in (True, 1.0, '1'):
                with self.subTest(path=path, bad=bad):
                    self._typed_refusal(self._alter(p, path, bad), m, self._path('plan', path))

    def test_resealed_wrong_runtime_pin_refuses_source_law_without_resealing_original(self):
        from inferswarm.operator.config import parse_config
        from tests.test_issue299_q8_plan import q8_mapping
        from tests.issue299_fixture import NOW, reseal_profiles, profile_digest
        p, m = self._inputs()
        raw = q8_mapping()
        profiles = raw['profiles']['snapshot']
        runtime = profiles['runtime_capabilities'][0]
        runtime['source_revision'] = 'a'*40
        evidence = next(e for e in profiles['evidence'] if e['evidence_id'] == runtime['evidence_id'])
        evidence['dependencies']['runtime:'+runtime['runtime_id']+':source_revision'] = 'a'*40
        reseal_profiles(profiles); raw['profiles']['digest'] = profile_digest(profiles)
        c = parse_config(raw, now=NOW, profile_mode='replay')
        changed = replace(p, config=c, profiles=c.profiles)
        with self.assertRaisesRegex(ValueError, 'runtime source pin'):
            self._derive(changed, m)

    def test_full_metadata_descriptor_hparams_type_and_extent_are_source_checked(self):
        p, m = self._inputs()
        tensor = m.tensors[0]
        cases = [(replace(m, model_metadata=tuple((k, 49 if k == 'qwen4exp.block_count' else v)
                                                  for k, v in m.model_metadata)), 'metadata descriptor authentication'),
                 (replace(m, tensors=(replace(tensor, ggml_type=0),)+m.tensors[1:]), 'tensor shape/type'),
                 (replace(m, tensors=(replace(tensor, encoded_bytes=tensor.encoded_bytes+32),)+m.tensors[1:]), 'encoded extent')]
        for changed, reason in cases:
            with self.subTest(reason=reason), self.assertRaisesRegex(ValueError, reason):
                self._derive(p, changed)

    def test_original_plan_context_describes_without_admission(self):
        from inferswarm.operator.config import parse_config
        from inferswarm.operator.plan import build_plan
        from inferswarm.operator.qwen_q8 import q8_static_inventory
        from tests.test_issue299_q8_plan import q8_mapping, fully_bounded_mapping, metadata
        from tests.issue299_fixture import NOW
        m = metadata()
        for selection in ('one-gpu', 'cpu-only'):
            for bounded in (False, True):
                raw = fully_bounded_mapping(selection) if bounded else q8_mapping(selection)
                config = parse_config(raw, now=NOW, profile_mode='replay')
                plan = build_plan(config, now=NOW)
                expected = q8_static_inventory(config, m, candidate=plan.candidate)
                with self.subTest(selection=selection, synthetic_bounds=bounded):
                    context = contract.derive_static_plan_context(
                        plan, m, original_plan_digest=plan.digest)
                    self.assertIs(type(context), contract.StaticPlanContext)
                    self.assertEqual(context.original_plan_digest, plan.digest)
                    self.assertEqual(context.config, config)
                    self.assertEqual(context.inventory, expected)
                    self.assertEqual((len(context.inventory.weights),
                                      len(context.inventory.persistent_caches)), (1224, 109))
                    self.assertEqual(tuple(r.state.state_id for r in context.inventory.logical_composites),
                                     ('client-control', 'final-output-state'))
                    self.assertEqual(context.inventory.charges, plan.candidate.charges)
                    self.assertEqual(context.inventory.capability_requirements, plan.candidate.capability_requirements)
                    self.assertEqual(context.inventory.pending_dynamic,
                        ('request-valued-control-and-state-authority', 'same-request-graph-and-ubatch',
                         'actual-boundary-and-side-input-copies', 'final-output-computation-and-custody',
                         'original-controller-and-owned-process-binding'))
                    self.assertFalse(plan.admission.execution_ready)
                    self.assertEqual(plan.admission.status, 'ADMITTED' if bounded else 'BLOCKED')
                    self.assertEqual(tuple(f.name for f in fields(context)),
                                     ('original_plan_digest', 'config', 'inventory'))
                    self.assertFalse(hasattr(context, 'execution_ready'))
                    self.assertFalse(hasattr(context, 'physical_qualified'))


if __name__ == '__main__':
    unittest.main()
