"""Apply the retained #301 observation overlay to an authenticated base tree.

Derives an overlay copy under an explicit destination directory; the pinned
read-only base checkout is never written. Refuses any source not exactly at
the pinned commit/tree. The overlay copy carries the retained transformed
files (from tests/fixtures/issue299/overlay), the observer header, and the
transformed-file manifest for build-manifest identity.
"""
from __future__ import annotations

import hashlib
import json
import os
import stat
from pathlib import Path
import subprocess

PIN = 'b29c606e28a01b1bc8c1351026a0fa6e616bf6c4'
TREE = '950999fe62b7fe55f44ab5b7394e3c8542f37f12'

REPO = Path(__file__).resolve().parents[3]
FIXTURES = REPO / 'tests/fixtures/issue299'
OVERLAY_DIR = FIXTURES / 'overlay'

# Transformed base files + new overlay files, relative to the overlay dir.
TRANSFORMED = (
    'ggml/src/ggml-alloc.c',
    'ggml/src/ggml-backend.cpp',
    'ggml/src/ggml-rpc/ggml-rpc.cpp',
    'src/llama-model-loader.cpp',
    'src/llama-kv-cache.cpp',
    'tools/server/server-queue.cpp',
)
NEW_FILES = (
    'is301_observer.h',
    'is301_c_shim.h',
    'is301_sink.cpp',
    'tests/native-buffer-graph-observed.cpp',
    'tests/native-fact-bounds.cpp',
    'tests/native-export-claim.cpp',
)


class OverlayError(RuntimeError):
    pass


def _git(source: Path, *args: str) -> bytes:
    return subprocess.check_output(['git', '-C', str(source), *args], timeout=30)


def authenticate(source: Path) -> None:
    source = Path(source).resolve()
    identity = _git(source, 'rev-parse', 'HEAD', 'HEAD^{tree}').decode().splitlines()
    if identity != [PIN, TREE]:
        raise OverlayError('base identity mismatch: ' + repr(identity))


def _pinned_entries(source: Path):
    """Return the exact pin tree as {path: (mode, blob_oid)}."""
    raw = _git(source, 'ls-tree', '-r', '-z', PIN)
    entries = {}
    for record in raw.split(b'\0'):
        if not record:
            continue
        metadata, name = record.split(b'\t', 1)
        mode, kind, oid = metadata.decode('ascii').split()
        path = name.decode('utf-8', 'surrogateescape')
        if mode == '160000' or kind == 'commit':
            raise OverlayError('pinned source contains unsupported submodule: ' + path)
        if kind != 'blob' or mode not in ('100644', '100755', '120000'):
            raise OverlayError('unsupported pinned tree entry: ' + path)
        entries[path] = (mode, oid)
    return entries


def _manifest_rows(manifest):
    rows = {row['path']: row['sha256'] for row in manifest.get('files', [])}
    expected = set(TRANSFORMED) | set(NEW_FILES)
    if set(rows) != expected:
        raise OverlayError('retained transformed manifest path set mismatch')
    return rows


def verify_tree_inputs(tree, source) -> dict[str, str]:
    """Authenticate every materialized tree byte against pin/retained blobs."""
    # Inspect the caller's root before resolve() can hide a symlink.
    tree, source = Path(tree).absolute(), Path(source).resolve()
    try:
        if not stat.S_ISDIR(tree.lstat().st_mode):
            raise OverlayError('dirty or foreign source input: overlay root')
    except OSError as exc:
        raise OverlayError('dirty or foreign source input: overlay root') from exc
    manifest_path = tree / 'native-observer-transformed.json'
    try:
        if not stat.S_ISREG(manifest_path.lstat().st_mode):
            raise OverlayError('dirty or foreign source input: native-observer-transformed.json')
        manifest = json.loads(manifest_path.read_text())
    except (OSError, ValueError) as exc:
        raise OverlayError('dirty or foreign source input: native-observer-transformed.json') from exc
    rows = _manifest_rows(manifest)
    retained_manifest = FIXTURES / 'native-observer-transformed.json'
    if not retained_manifest.is_file() or hashlib.sha256(manifest_path.read_bytes()).digest() != hashlib.sha256(retained_manifest.read_bytes()).digest():
        raise OverlayError('dirty or foreign source input: native-observer-transformed.json')
    pinned = _pinned_entries(source)
    pinned_sha256 = {
        path: hashlib.sha256(_git(source, 'cat-file', 'blob', f'{PIN}:{path}')).hexdigest()
        for path in pinned
    }
    expected = set(pinned) | set(NEW_FILES) | {'native-observer-transformed.json'}
    expected_dirs = {str(parent) for path in expected
                     for parent in Path(path).parents if str(parent) != '.'}
    actual = set()
    actual_dirs = set()
    pending = [tree]
    while pending:
        directory = pending.pop()
        with os.scandir(directory) as entries:
            for entry in entries:
                rel = str(Path(entry.path).relative_to(tree))
                mode = entry.stat(follow_symlinks=False).st_mode
                if stat.S_ISDIR(mode):
                    if rel not in expected_dirs:
                        raise OverlayError('dirty or foreign source input: ' + rel)
                    actual_dirs.add(rel)
                    pending.append(Path(entry.path))
                elif stat.S_ISREG(mode):
                    actual.add(rel)
                else:
                    raise OverlayError('dirty or foreign source input (not a regular file): ' + rel)
    if actual_dirs != expected_dirs:
        raise OverlayError('dirty or foreign source input: missing directory')

    verified = {}
    for path in sorted(expected | actual):
        file = tree / path
        if path not in expected or path not in actual:
            raise OverlayError('dirty or foreign source input: ' + path)
        if file.is_symlink() or not stat.S_ISREG(file.stat(follow_symlinks=False).st_mode):
            raise OverlayError('dirty or foreign source input (not a regular file): ' + path)
        digest = hashlib.sha256(file.read_bytes()).hexdigest()
        expected_digest = rows.get(path, pinned_sha256.get(path))
        if path == 'native-observer-transformed.json':
            expected_digest = hashlib.sha256(retained_manifest.read_bytes()).hexdigest()
        if digest != expected_digest:
            raise OverlayError('dirty or foreign source input: ' + path)
        if path in pinned:
            mode, _oid = pinned[path]
            st = file.stat(follow_symlinks=False)
            # Pinned regular files must remain regular, non-symlink, with the
            # exact pinned mode class: no added/lost executable bits and no
            # regular<->symlink substitution (symlinks can be retargeted after
            # verification, so a pinned regular file must never become one).
            if mode in ('100644', '100755'):
                if file.is_symlink() or not stat.S_ISREG(st.st_mode):
                    raise OverlayError('dirty or foreign source input (not a regular file): ' + path)
                if mode == '100755' and not st.st_mode & 0o111:
                    raise OverlayError('dirty or foreign source input (lost executable bit): ' + path)
                if mode == '100644' and st.st_mode & 0o111:
                    raise OverlayError('dirty or foreign source input (added executable bit): ' + path)
            elif mode == '120000':
                if not file.is_symlink():
                    raise OverlayError('dirty or foreign source input (symlink materialized as regular file): ' + path)
        verified[path] = digest
    return verified


def apply(source, destination) -> dict:
    """Derive the overlay using only authenticated Git blobs and retained files."""
    source = Path(source).resolve()
    destination = Path(destination).resolve()
    authenticate(source)
    if destination.exists():
        raise OverlayError('destination already exists: ' + str(destination))
    if not destination.is_relative_to(Path('/home/zutfen/.hermes/cache/scratch')):
        raise OverlayError('overlay trees stay in authorized scratch')
    entries = _pinned_entries(source)
    destination.mkdir(parents=True)
    for name, (mode, oid) in entries.items():
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        content = _git(source, 'cat-file', 'blob', f'{PIN}:{name}')
        target.write_bytes(content)
        if mode == '100755':
            target.chmod(target.stat().st_mode | 0o111)
        elif mode == '120000':
            target.unlink()
            target.symlink_to(content.decode('utf-8', 'surrogateescape'))
    for name in TRANSFORMED:
        patched = OVERLAY_DIR / name
        if not patched.is_file():
            raise OverlayError('retained transformed file missing: ' + name)
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(patched.read_bytes())
    for name in NEW_FILES:
        origin = OVERLAY_DIR / name
        if not origin.is_file():
            raise OverlayError('retained overlay file missing: ' + name)
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(origin.read_bytes())
    manifest = json.loads((FIXTURES / 'native-observer-transformed.json').read_text())
    rows = _manifest_rows(manifest)
    for name, expected_digest in rows.items():
        path = destination / name
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected_digest:
            raise OverlayError('overlay tree byte mismatch: ' + name)
    (destination / 'native-observer-transformed.json').write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + '\n')
    verify_tree_inputs(destination, source)
    return manifest
