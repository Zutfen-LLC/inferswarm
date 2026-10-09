"""Opt-in bounded public GGUF metadata reproduction and offline fixture reader.

No weights, model runtime, adaptive probes or retries. Header SHA-256 is the
metadata authority; full-object LFS identities are attributed, NOT verified here.
Reproduce with:
  python -m inferswarm.operator.metadata reproduce --manifest MANIFEST \
      --output INDEX --allow-network [--raw-header-dir OUTSIDE_REPOSITORY]
Normal fixture loading has no network or subprocess path.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass, replace
import hashlib
import json
import math
from pathlib import Path
import re
from urllib.parse import parse_qs, urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .config import ModelIdentity
from .source import TensorRecord, _encoded_bytes, _validate_extents, parse_gguf_header

SOURCE_ID = 'unsloth/Qwen3.8-Flash-Next-GGUF'
REVISION = '38bb39ee97821de2c9009abb7e93950eec396e66'
# Issue #299 appendix and immutable #189 census; no lookup or mutable URLs.
_PUBLIC = (
    (10946624, '2dabcbb53ca537a7947bc7d20414fd464eeaf4d66d43021b5b2556cc87544ad2', 10946617, '1393b18f5fc05a7b2e17d480ef7933aa1c400be511b2f0de0c18e2a8f45363d6', 0),
    (682434912, '494ca4ed3dbf97bc28da88af3890b8877b9032f909812d00c0526a9ca5e91d2e', 331, 'c4f6af2a64fce038e65572189fb76448ff4a5102fbb32c472185664355d895ba', 4),
    (54400261312, '34efd79a80a1ce540a517a5d56171924b66ce1c38b04c904f17ad6d8ef17cf20', 172, 'a0c549cedf05179c34faab89eb4537e157b3a65a88095e46e7c2486fab7a0c1b', 1),
    (49446841216, 'bfa634025fabbd2658bf7694bc80b90e571699c768723f844c934c7ef06c691a', 28140, '1649c5b437a79d421378c5c650414c79bfc55bb639b4a403c3d14064cc831b73', 444),
    (49668930400, '232a8f14cc0fa4262e7efe8593774b136fe40909e39c7a020342ddaa27259a97', 29255, '4964cffe16b75a997d34c43d1b343690a226a2ddacb2e555951e71d0c2a47024', 458),
    (34015618784, '538a93bca918064983409a41187ad4c68640f9aced6f29564da8f551bf86d7a5', 20316, '5d02a2d43c4247c7fb7f778ece3dd5077b9491e1dfd09941847a113f1050c777', 317),
)
PROVENANCE = {
    'issue': 'Zutfen-LLC/inferswarm#299',
    'census_path': 'docs/investigations/qwen38-flash-next-r8-a/gguf-census.json',
    'census_git_commit': '008e0727a08191d7ba47c0b7ea28a6493e662de1',
    'census_sha256': '5664961903f0b6afd1066ac88d287471231c962604fe7e7176f2b3f41ee43fe1',
    'claim': 'Header SHA-256 authenticates metadata only; LFS SHA-256 is attributable full-object identity, not independent weight verification.',
}
MAX_JSON_BYTES = 4 << 20


@dataclass(frozen=True)
class MetadataIndex:
    source: ModelIdentity
    metadata_digest: str
    # (member, inclusive start, inclusive end, header SHA, object bytes, LFS SHA)
    header_identities: tuple
    model_metadata: tuple
    tensors: tuple[TensorRecord, ...]


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _digest(value, where):
    if not isinstance(value, str) or not re.fullmatch('[0-9a-f]{64}', value):
        raise ValueError(f'invalid {where} SHA-256')
    return value


def _integer(value, where, *, minimum=0, maximum=(1 << 63) - 1):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f'invalid {where}')
    return value


def _keys(value, keys, where):
    if not isinstance(value, dict) or set(value) != set(keys):
        raise ValueError(f'{where} fields must be exactly {sorted(keys)}')


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result: raise ValueError(f'duplicate JSON key: {key}')
        result[key] = value
    return result


def _read_json(path, *, expected_sha256=None):
    with Path(path).open('rb') as stream:
        data = stream.read(MAX_JSON_BYTES + 1)
    if len(data) > MAX_JSON_BYTES: raise ValueError('oversized metadata JSON')
    if expected_sha256 is not None:
        _digest(expected_sha256, 'metadata file')
        if _sha(data) != expected_sha256: raise ValueError('metadata file SHA-256 mismatch')
    def constant(_):
        raise ValueError('nonfinite JSON')
    def finite_float(text):
        number = float(text)
        if not math.isfinite(number): raise ValueError('nonfinite JSON')
        return number
    try:
        return json.loads(data, object_pairs_hook=_pairs, parse_constant=constant, parse_float=finite_float)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError('invalid metadata JSON') from exc


def _public_members():
    rows = []
    for number, (size, lfs, end, digest, count) in enumerate(_PUBLIC, 1):
        name = f'Qwen3.8-Flash-Next-Q8_0-{number:05d}-of-00006.gguf'
        rows.append(dict(member=name, url=f'https://huggingface.co/{SOURCE_ID}/resolve/{REVISION}/Q8_0/{name}',
                         object_bytes=size, object_sha256=lfs, range_start=0,
                         range_end=end, header_sha256=digest, tensor_count=count))
    return rows


def _validate_source(value):
    _keys(value, ('source_id', 'revision', 'representation'), 'source')
    if value != dict(source_id=SOURCE_ID, revision=REVISION, representation='Q8_0'):
        raise ValueError('source identity mismatch')


def _manifest(manifest):
    value = _read_json(manifest) if isinstance(manifest, (str, Path)) else manifest
    _keys(value, ('schema', 'source', 'provenance', 'members'), 'public manifest')
    if value['schema'] != 'public-gguf-headers/1': raise ValueError('unsupported public manifest schema')
    _validate_source(value['source'])
    if value['provenance'] != PROVENANCE: raise ValueError('public provenance mismatch')
    rows = value['members']
    if not isinstance(rows, list) or len(rows) != 6: raise ValueError('missing or changed public members')
    for row in rows:
        _keys(row, ('member', 'url', 'object_bytes', 'object_sha256', 'range_start', 'range_end', 'header_sha256', 'tensor_count'), 'public member')
        for field in ('object_bytes', 'range_start', 'range_end', 'tensor_count'):
            _integer(row[field], field)
        for field in ('object_sha256', 'header_sha256'):
            _digest(row[field], field)
    if sorted(rows, key=lambda r: r['member']) != _public_members():
        raise ValueError('missing or changed public members')
    # Copy after validation: callers cannot change the bounded requests in flight.
    return tuple(dict(row) for row in sorted(rows, key=lambda r: r['member']))


class _PinnedRedirectHandler(HTTPRedirectHandler):
    """Approve only the pinned resolver or its identity-bound signed CDN target.

    CDN authorization is minted ONLY by a redirect from the exact pinned HF URL,
    carrying matching X-Linked-Etag/size and the exact filename. Subsequent hops
    are refused. Validation runs before urllib issues the redirected request.
    """
    def __init__(self, row):
        super().__init__()
        self.row = row
        self.approved = {row['url']}

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target = urlsplit(newurl)
        filename = parse_qs(target.query).get('response-content-disposition', [''])[0]
        hosts = {'us.aws.cdn.hf.co', 'cas-bridge.xethub.hf.co', 'cdn-lfs.huggingface.co', 'cdn-lfs-us-1.huggingface.co'}
        if (req.full_url != self.row['url'] or len(self.approved) != 1
                or target.scheme != 'https' or target.hostname not in hosts
                or target.port not in (None, 443) or target.username or target.password
                or target.fragment or self.row['member'] not in filename
                or headers.get('X-Linked-Etag', '').strip('"') != self.row['object_sha256']
                or headers.get('X-Linked-Size') != str(self.row['object_bytes'])):
            raise ValueError(f'unapproved redirect resource: host={target.hostname}, path={target.path}, linked_etag={headers.get("X-Linked-Etag")!r}, linked_size={headers.get("X-Linked-Size")!r}, filename={filename!r}')
        self.approved.add(newurl)
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected is None: raise ValueError('unapproved redirect resource')
        redirected.add_header('Range', f"bytes=0-{self.row['range_end']}")
        redirected.add_header('Accept-Encoding', 'identity')
        return redirected

    def http_error_302(self, req, fp, code, msg, headers):
        # The stdlib implementation drains fp.read() without a bound. Redirect
        # bodies are not approved metadata: close without consuming ANY bytes.
        try:
            location = headers.get('Location')
            if not location: raise ValueError('unapproved redirect resource')
            redirected = self.redirect_request(req, fp, code, msg, headers, urljoin(req.full_url, location))
        finally:
            fp.close()
        return self.parent.open(redirected, timeout=req.timeout)

    http_error_301 = http_error_303 = http_error_307 = http_error_308 = http_error_302


def _fetch_header(row, *, opener):
    policy = _PinnedRedirectHandler(row)
    open_request = build_opener(policy).open if opener is None else opener
    request = Request(row['url'], headers={'Range': f"bytes=0-{row['range_end']}", 'Accept-Encoding': 'identity'})
    response = open_request(request, timeout=60)
    try:
        # Never inspect/read a 200 body, even when it happens to be metadata-only.
        if response.status != 206: raise ValueError('expected HTTP 206')
        if response.geturl() not in policy.approved: raise ValueError('unapproved response resource')
        expected = f"bytes 0-{row['range_end']}/{row['object_bytes']}"
        if response.headers.get('Content-Range') != expected: raise ValueError('Content-Range mismatch')
        if response.headers.get('Content-Encoding', 'identity').lower() != 'identity':
            raise ValueError('nonidentity Content-Encoding')
        size = row['range_end'] + 1
        if response.headers.get('Content-Length') not in (None, str(size)):
            raise ValueError('Content-Length mismatch')
        # Exact budget plus one byte ONLY for oversize rejection, never a retry.
        data = response.read(size)
        if len(data) != size: raise ValueError('truncated header response')
        if response.read(1): raise ValueError('oversized header response')
        if _sha(data) != row['header_sha256']: raise ValueError('header SHA-256 mismatch')
        return data
    finally:
        response.close()


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode('utf-8')


def _payload(source, identities, metadata, tensors):
    return dict(schema='gguf-metadata-index/1',
                source=dict(source_id=source.source_id, revision=source.revision, representation=source.representation),
                header_identities=identities, model_metadata=metadata,
                tensors=[asdict(row) for row in tensors], provenance=PROVENANCE)


def _index(metadata, tensors):
    members = _public_members()
    source = ModelIdentity(SOURCE_ID, REVISION, 'Q8_0', tuple((r['member'], r['object_sha256'], r['object_bytes']) for r in members))
    identities = tuple((r['member'], 0, r['range_end'], r['header_sha256'], r['object_bytes'], r['object_sha256']) for r in members)
    metadata = tuple(sorted(metadata))
    tensors = tuple(sorted(tensors, key=lambda r: r.state_id))
    digest = _sha(_canonical(_payload(source, identities, metadata, tensors)))
    return MetadataIndex(source, digest, identities, metadata, tensors)


def _assemble_index(parsed):
    """Validate authenticated member splits and global names before publication."""
    members = _public_members()
    if len(parsed) != 6: raise ValueError('missing GGUF members')
    metadata = {}; tensors = []; names = set()
    for number, ((pairs, rows), member) in enumerate(zip(parsed, members)):
        values = dict(pairs)
        split = tuple(values.get(k) for k in ('split.no', 'split.count', 'split.tensors.count'))
        if any(type(v) is not int for v in split) or split != (number, 6, 1224):
            raise ValueError('GGUF split identity mismatch')
        if len(rows) != member['tensor_count']: raise ValueError('GGUF member tensor count mismatch')
        for key, value in pairs:
            if key.startswith('split.'): continue
            if key in metadata and metadata[key] != value: raise ValueError('changed model metadata')
            metadata[key] = value
        for row in rows:
            if row.state_id in names: raise ValueError('duplicate GGUF tensor across members')
            names.add(row.state_id)
            tensors.append(replace(row, member=member['member']))
    required = {'general.architecture': 'qwen4exp', 'general.file_type': 7,
                'qwen4exp.block_count': 48, 'qwen4exp.embedding_length': 2560,
                'qwen4exp.expert_count': 512, 'qwen4exp.expert_used_count': 10}
    if any(metadata.get(k) != v or type(metadata.get(k)) is not type(v) for k, v in required.items()):
        raise ValueError('changed model metadata')
    if len(tensors) != 1224 or sum(r.encoded_bytes for r in tensors) != 188214008320:
        raise ValueError('public GGUF census mismatch')
    return _index(tuple(metadata.items()), tensors)


def reproduce_metadata(manifest, *, opener, allow_network: bool = False, raw_header_dir=None) -> MetadataIndex:
    """Acquire only the six exact approved header ranges, once each, opt-in only."""
    if allow_network is not True: raise ValueError('network reproduction requires explicit opt-in')
    members = _manifest(manifest)
    raw = None
    if raw_header_dir is not None:
        raw = Path(raw_header_dir).resolve()
        if raw.is_relative_to(Path(__file__).resolve().parents[2]):
            raise ValueError('raw headers must remain outside repository')
    parsed = []
    for row in members:
        data = _fetch_header(row, opener=opener)
        decoded = parse_gguf_header(data, object_bytes=row['object_bytes'], expected_header_sha256=row['header_sha256'])
        parsed.append(decoded)
        if raw is not None:
            raw.mkdir(parents=True, exist_ok=True)
            with (raw / row['member']).open('xb') as stream:
                stream.write(data)
    return _assemble_index(tuple(parsed))


def metadata_index_bytes(index):
    """Canonical compact descriptor fixture, including its normalized digest."""
    value = _payload(index.source, index.header_identities, index.model_metadata, index.tensors)
    value['metadata_digest'] = index.metadata_digest
    return _canonical(value) + b'\n'


def _metadata_value(value):
    if isinstance(value, list):
        if len(value) > 4096: raise ValueError('oversized model metadata array')
        return tuple(_metadata_value(v) for v in value)
    if type(value) not in (str, int, float, bool) or isinstance(value, float) and not math.isfinite(value):
        raise ValueError('invalid model metadata value')
    if isinstance(value, str) and (len(value.encode('utf-8')) > 65536 or '\x00' in value):
        raise ValueError('invalid model metadata string')
    if type(value) is int and not -(1 << 63) <= value < (1 << 64): raise ValueError('invalid model metadata integer')
    return value


def load_metadata_index(path, *, expected_sha256: str) -> MetadataIndex:
    """Authenticate actual fixture bytes, then validate immutable descriptors.

    The caller's file SHA is the fixture authority. Recomputing a digest of an
    invented inventory alone cannot prove correspondence to public header bytes.
    Independent public reproduction/review establishes that correspondence.
    """
    value = _read_json(path, expected_sha256=expected_sha256)
    _keys(value, ('schema', 'source', 'header_identities', 'model_metadata', 'tensors', 'provenance', 'metadata_digest'), 'metadata index')
    if value['schema'] != 'gguf-metadata-index/1': raise ValueError('unsupported metadata index schema')
    _validate_source(value['source'])
    if value['provenance'] != PROVENANCE: raise ValueError('public provenance mismatch')
    digest = _digest(value['metadata_digest'], 'metadata')
    payload = {k: v for k, v in value.items() if k != 'metadata_digest'}
    if _sha(_canonical(payload)) != digest: raise ValueError('metadata digest mismatch')
    public = _public_members()
    identities = [[r['member'], 0, r['range_end'], r['header_sha256'], r['object_bytes'], r['object_sha256']] for r in public]
    actual = value['header_identities']
    if not isinstance(actual, list) or len(actual) != 6: raise ValueError('header identities mismatch')
    for row in actual:
        if not isinstance(row, list) or len(row) != 6: raise ValueError('header identities mismatch')
        for offset in (1, 2, 4): _integer(row[offset], 'header identity integer')
    if actual != identities: raise ValueError('header identities mismatch')
    pairs = value['model_metadata']
    if not isinstance(pairs, list) or len(pairs) > 10000: raise ValueError('invalid model metadata')
    metadata = {}; parsed_pairs = []
    for pair in pairs:
        if not isinstance(pair, list) or len(pair) != 2 or not isinstance(pair[0], str) or not pair[0] or len(pair[0]) > 4096:
            raise ValueError('invalid model metadata pair')
        key, item = pair
        if key in metadata: raise ValueError('duplicate model metadata')
        if key.startswith(('tokenizer.', 'split.')): raise ValueError('unexpected model metadata key')
        item = _metadata_value(item)
        metadata[key] = item
        parsed_pairs.append((key, item))
    raw_rows = value['tensors']
    if not isinstance(raw_rows, list) or len(raw_rows) != 1224: raise ValueError('public GGUF census mismatch')
    names = set(); tensors = []; grouped = {r['member']: [] for r in public}
    for row in raw_rows:
        _keys(row, ('state_id', 'member', 'ggml_type', 'shape', 'relative_offset', 'absolute_offset', 'encoded_bytes'), 'tensor')
        name, member = row['state_id'], row['member']
        if not isinstance(name, str) or not name or len(name) > 4096 or '\x00' in name: raise ValueError('invalid tensor state_id')
        if name in names: raise ValueError('duplicate GGUF tensor')
        names.add(name)
        if not isinstance(member, str) or member not in grouped: raise ValueError('unknown GGUF member')
        typ = _integer(row['ggml_type'], 'ggml_type')
        if not isinstance(row['shape'], list): raise ValueError('invalid GGUF shape')
        shape = tuple(row['shape'])
        size = _encoded_bytes(shape, typ)
        if _integer(row['encoded_bytes'], 'encoded_bytes', minimum=1) != size: raise ValueError('GGUF encoded extent mismatch')
        off = _integer(row['relative_offset'], 'relative_offset')
        absolute = _integer(row['absolute_offset'], 'absolute_offset')
        tensor = TensorRecord(name, member, typ, shape, off, absolute, size)
        tensors.append(tensor); grouped[member].append(tensor)
    alignment = metadata.get('general.alignment', 32)
    if type(alignment) is not int or not 1 <= alignment <= 4096 or alignment & (alignment - 1): raise ValueError('invalid GGUF alignment')
    for member in public:
        rows = grouped[member['member']]
        if len(rows) != member['tensor_count']: raise ValueError('GGUF member tensor count mismatch')
        start = (member['range_end'] + 1 + alignment - 1) // alignment * alignment
        _validate_extents(rows, member['object_bytes'], start, alignment)
    required = {'general.architecture': 'qwen4exp', 'general.file_type': 7,
                'qwen4exp.block_count': 48, 'qwen4exp.embedding_length': 2560,
                'qwen4exp.expert_count': 512, 'qwen4exp.expert_used_count': 10}
    if any(metadata.get(k) != v or type(metadata.get(k)) is not type(v) for k, v in required.items()):
        raise ValueError('changed model metadata')
    if sum(r.encoded_bytes for r in tensors) != 188214008320: raise ValueError('public GGUF census mismatch')
    index = _index(parsed_pairs, tensors)
    if index.metadata_digest != digest: raise ValueError('noncanonical metadata inventory')
    return index


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    reproduce = commands.add_parser('reproduce', help='opt-in six exact public metadata ranges, no weights')
    reproduce.add_argument('--manifest', required=True)
    reproduce.add_argument('--output', required=True)
    reproduce.add_argument('--allow-network', action='store_true')
    reproduce.add_argument('--raw-header-dir')
    args = parser.parse_args(argv)
    try:
        index = reproduce_metadata(args.manifest, opener=None, allow_network=args.allow_network, raw_header_dir=args.raw_header_dir)
        encoded = metadata_index_bytes(index)
        with Path(args.output).open('xb') as stream:
            stream.write(encoded)
        print(json.dumps(dict(metadata_digest=index.metadata_digest, file_sha256=_sha(encoded),
                              tensors=len(index.tensors), encoded_bytes=sum(r.encoded_bytes for r in index.tensors),
                              authenticated_header_bytes=sum(r[2] - r[1] + 1 for r in index.header_identities),
                              weight_content_verified=False), sort_keys=True))
        return 0
    except (ValueError, OSError) as exc:
        parser.exit(1, f'{exc}\n')


if __name__ == '__main__':
    raise SystemExit(main())
