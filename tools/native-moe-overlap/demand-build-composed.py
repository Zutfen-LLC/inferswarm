#!/usr/bin/env python3
"""Issue #314 composed CPU demand-client candidate; no acceptance authority.

Reuses the authenticated pinned archive, the complete #311 v7 assigned-cache
+#301 observer composition, the #309 qwen4exp overlap overlay, the #312 demand
collector and the -O3/Debug-assertion recipe of the reviewed CPU client. The
single emitted binary is `native-demand`; both accepted step-a/optimized
executables keep their exact identities. No download beyond the existing pin
mechanism, install, CUDA build, model read or runtime execution happens here.
"""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError('cannot load build support module: ' + str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


optimized = _load('is314_cpu_optimized', HERE.parent / 'native-cache' / 'operator-build-cpu-optimized.py')
cpu = optimized.cpu
pin = _load('is314_pin_build', HERE / 'build.py')
sys.path.insert(0, str(ROOT))


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        while data := stream.read(1 << 20):
            h.update(data)
    return h.hexdigest()


# Exactly the files build.py already composes into its derived tree; demand.h
# is added beside them. native.patch + overlay are #309, native-cache inputs
# are the accepted #311 v7 composition; nothing is re-derived ad hoc.
def demand_compose(archive, output):
    output = Path(output)
    source, composite = cpu.compose(Path(archive), output)
    subprocess.run(['patch', '--batch', '--fuzz=0', '-p1', '-i', str(HERE / 'native.patch')],
                   cwd=source, check=True, timeout=30,
                   stdout=subprocess.DEVNULL)
    overlay = HERE / 'overlay'
    for row in sorted(overlay.rglob('*')):
        target = source / row.relative_to(overlay)
        if row.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(row.read_bytes())
    (source / 'src/demand.h').write_bytes((HERE / 'demand.h').read_bytes())
    (source / 'src/demand.cpp').write_bytes((HERE / 'demand.cpp').read_bytes())
    (source / 'src/demand_cli.cpp').write_bytes((HERE / 'demand_cli.cpp').read_bytes())
    transformed = {str(p.relative_to(source)): digest(p)
                   for p in source.rglob('*') if p.is_file()}
    composite = hashlib.sha256(json.dumps(transformed, sort_keys=True,
                                          separators=(',', ':')).encode()).hexdigest()
    return source, composite


def build(archive, output, cmake):
    source, composite = demand_compose(Path(archive), Path(output))
    output = Path(output)
    binary = output / 'build'
    # The #311 composer appends its loader wiring to the base CMakeLists; add
    # the composed demand client target beside it (same appended block). The
    # llama target needs ggml/src because the #309 patch builds
    # llama-moe-overlap.cpp inside it (the standalone #309 recipe passes the
    # same include explicitly).
    with (source / 'CMakeLists.txt').open('a') as stream:
        stream.write('target_include_directories(llama PRIVATE ggml/src)\n'
                     'target_sources(llama PRIVATE src/demand.cpp)\n'
                     'add_executable(native-demand src/demand_cli.cpp)\n'
                     'target_include_directories(native-demand PRIVATE src ggml/src ggml/src/ggml-cpu ggml/include common)\n'
                     'target_link_libraries(native-demand PRIVATE llama ggml-rpc)\n')
    options = optimized.optimized_options()
    commands = [[cmake, '-S', str(source), '-B', str(binary), '-G', 'Ninja', *options],
                [cmake, '--build', str(binary), '--target', 'native-demand', '-j', '2']]
    effective = None
    for index, command in enumerate(commands):
        with (output / f'composed-build-{index}.log').open('w') as log:
            subprocess.run(command, stdout=log, stderr=subprocess.STDOUT,
                           check=True, timeout=3600, preexec_fn=cpu.limits)
        if index == 0:
            effective = optimized.inspect_effective_flags(binary)
            (output / 'effective-flags.json').write_text(json.dumps(effective, indent=2) + '\n')
    executable = binary / 'bin' / 'native-demand'
    libraries = tuple((str(p.relative_to(binary)), digest(p))
                      for p in sorted(binary.rglob('*.a')))
    patch = hashlib.sha256((HERE.parent / 'native-cache' / 'native.patch').read_bytes()
                           + (HERE.parent / 'native-cache' / 'assigned.h').read_bytes()
                           + (HERE.parent / 'native-cache' / 'operator-build.py').read_bytes()).hexdigest()
    demand_patch = hashlib.sha256((HERE / 'native.patch').read_bytes()
                                  + (HERE / 'demand.h').read_bytes()
                                  + (HERE / 'demand.cpp').read_bytes()
                                  + (HERE / 'demand_cli.cpp').read_bytes()).hexdigest()
    result = dict(schema='native-demand-composed-build/1',
                  native_commit=cpu.PIN, archive_sha256=cpu.ARCHIVE_SHA,
                  composite_sha256=composite, patch_sha256=patch,
                  demand_patch_sha256=demand_patch,
                  compiler=subprocess.check_output(['c++', '--version'], text=True).splitlines()[0],
                  build_options=options, commands=commands, effective_flags=effective,
                  rpc_protocol={'major': 7}, note=(
                      'candidate demand-client build receipt; not an accepted '
                      'runtime identity; workers keep their reviewed identities'))
    path = output / 'native-demand.build-manifest.json'
    path.write_text(json.dumps(result, indent=2) + '\n')
    result = dict(result)
    result['executable'] = str(executable)
    result['executable_sha256'] = digest(executable)
    result['manifest'] = str(path)
    (output / 'composed-demand-receipt.json').write_text(json.dumps(result, indent=2) + '\n')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--cmake', default='cmake')
    args = parser.parse_args()
    print(json.dumps(build(args.archive, args.output, args.cmake), indent=2))
