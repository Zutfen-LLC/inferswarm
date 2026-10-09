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


if __name__ == '__main__':
    unittest.main()
