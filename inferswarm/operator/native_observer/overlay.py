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


def apply(source, destination) -> dict:
    """Pure derivation: copy the base tree, then overlay retained files."""
    source = Path(source).resolve()
    destination = Path(destination).resolve()
    authenticate(source)
    if destination.exists():
        raise OverlayError('destination already exists: ' + str(destination))
    if not destination.is_relative_to(Path('/home/zutfen/.hermes/cache/scratch')):
        raise OverlayError('overlay trees stay in authorized scratch')
    subprocess.run(['cp', '-a', str(source) + '/.', str(destination)],
                   check=True, timeout=600)
    # The copied .git would let later git commands see the base; keep it as
    # read-only provenance but never write to the base itself.
    for name in TRANSFORMED:
        patched = OVERLAY_DIR / name
        if not patched.is_file():
            raise OverlayError('retained transformed file missing: ' + name)
        (destination / name).write_bytes(patched.read_bytes())
    for name in NEW_FILES:
        origin = OVERLAY_DIR / name
        if not origin.is_file():
            raise OverlayError('retained overlay file missing: ' + name)
        (destination / name).write_bytes(origin.read_bytes())
    manifest = json.loads((FIXTURES / 'native-observer-transformed.json').read_text())
    # Re-verify every declared transformed byte inside the derived tree.
    for row in manifest['files']:
        path = destination / row['path']
        if not path.is_file():
            raise OverlayError('manifest file missing in overlay tree: ' + row['path'])
        if hashlib.sha256(path.read_bytes()).hexdigest() != row['sha256']:
            raise OverlayError('overlay tree byte mismatch: ' + row['path'])
    (destination / 'native-observer-transformed.json').write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + '\n')
    return manifest
