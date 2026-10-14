#!/usr/bin/env python3
"""Build the #311 cache fix from retained native source; CPU/RPC only, no download.

This is an explicit development recipe, not a Q8 runtime/campaign launcher.
The existing checkout and all historical evidence remain read-only.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import shutil
import json
import os
from pathlib import Path
import resource
import subprocess
import tarfile

PIN = 'b29c606e28a01b1bc8c1351026a0fa6e616bf6c4'
TREE = '950999fe62b7fe55f44ab5b7394e3c8542f37f12'
HERE = Path(__file__).resolve().parent


def limits():
    resource.setrlimit(resource.RLIMIT_AS, (1900000 * 1024, 1900000 * 1024))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def build(source, output, cmake='cmake'):
    output = Path(output).resolve()
    source = Path(source).resolve() if source else None
    identity = subprocess.check_output(['git', '-C', str(source), 'rev-parse',
                                       PIN + '^{commit}', PIN + '^{tree}'], text=True).splitlines() if source else [PIN, TREE]
    if identity != [PIN, TREE]:
        raise ValueError('retained native source identity mismatch')
    # Never overwrite an earlier build, source, cache, or evidence directory.
    output.mkdir(parents=True, exist_ok=False)
    native = output / 'native-source'
    if source:
        archive = output / 'pin.tar'
        with archive.open('wb') as stream:
            subprocess.run(['git', '-C', str(source), 'archive', PIN], stdout=stream,
                           check=True, timeout=60)
        native.mkdir()
        with tarfile.open(archive) as tar:
            tar.extractall(native, filter='data')
        archive.unlink()
    else:
        # CI reuses #309's authenticated source acquisition. Only native source
        # can be fetched here; neither recipe knows a model-weight URL.
        spec = importlib.util.spec_from_file_location('moe_pin', HERE.parent / 'moe-overlap/build.py')
        pin = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(pin)
        cache = HERE.parents[1] / '.cache/native-moe-overlap'
        cache.mkdir(parents=True, exist_ok=True)
        shutil.copytree(pin.ensure_source(cache), native)
    with (output / 'patch.log').open('w') as log:
        subprocess.run(['patch', '--batch', '--fuzz=0', '-p1', '-i', str(HERE / 'native.patch')],
                       cwd=native, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=30)
    # The wrapper uses only GGML + rpc-server, avoiding model/CUDA compilation.
    probe = output / 'probe'
    probe.mkdir()
    for name in ('CMakeLists.txt', 'driver.cpp'):
        (probe / name).write_bytes((HERE / name).read_bytes())
    build_dir = output / 'build'
    commands = [
        [cmake, '-S', str(probe), '-B', str(build_dir), '-G', 'Ninja', '-DCMAKE_BUILD_TYPE=Release'],
        [cmake, '--build', str(build_dir), '--target', 'ggml-rpc-server', 'driver', '-j', '2'],
    ]
    for index, command in enumerate(commands):
        with (output / f'build-{index}.log').open('w') as log:
            subprocess.run(command, stdout=log, stderr=subprocess.STDOUT,
                           check=True, timeout=600, preexec_fn=limits)
    result = {'native_commit': PIN, 'native_tree': TREE,
              'patch_sha256': hashlib.sha256((HERE / 'native.patch').read_bytes()).hexdigest(),
              'commands': commands, 'binaries': {}}
    for name in ('ggml-rpc-server', 'driver'):
        path = build_dir / 'bin' / name
        result['binaries'][name] = {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    (output / 'build.json').write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', help='retained llama.cpp Git object store/checkout')
    parser.add_argument('--output', required=True, help='new owned build directory')
    parser.add_argument('--cmake', default='cmake')
    args = parser.parse_args()
    print(json.dumps(build(args.source, args.output, args.cmake), indent=2))
