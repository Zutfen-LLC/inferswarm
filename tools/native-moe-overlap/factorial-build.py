#!/usr/bin/env python3
"""Separate opt-in CPU/RPC factorial candidate. No accepted worker rebuild."""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import time

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('factorial_base', HERE/'hot-build-composed.py')
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)


def build(archive, output, cmake='cmake', portable_fixtures=False):
    started = time.monotonic()
    output = Path(output).resolve()
    source, _ = base.base.demand_compose(Path(archive), output)
    subprocess.run(['patch', '--batch', '--fuzz=0', '-p1', '-i', str(HERE/'factorial-rpc.patch')],
                   cwd=source, check=True, timeout=30, stdout=subprocess.DEVNULL)
    shutil.copytree(HERE/'factorial-overlay', source, dirs_exist_ok=True)
    for name in ('factorial-rpc.h', 'factorial-rpc-io.h'):
        shutil.copyfile(HERE/name, source/'ggml/include'/name)
    mains = {'native-factorial-bench': HERE/'factorial_bench.cpp',
             'rpc-worker': HERE.parent/'moe-overlap/rpc_worker.cpp',
             'factorial-rpc-fixture': HERE/'factorial_rpc_fixture.cpp'}
    with (source/'CMakeLists.txt').open('a') as stream:
        stream.write('target_sources(llama PRIVATE src/demand.cpp)\n'
                     'target_include_directories(llama PRIVATE ggml/src)\n')
        for name, main in mains.items():
            stream.write(f'add_executable({name} "{main}")\n'
                         f'target_include_directories({name} PRIVATE src ggml/src ggml/include vendor)\n'
                         f'target_link_libraries({name} PRIVATE llama ggml-rpc)\n')
    source_inputs = {str(p.relative_to(source)): base.cpu.digest(p)
                     for p in sorted(source.rglob('*')) if p.is_file()}
    source_inputs.update({str(p): base.cpu.digest(p) for p in mains.values()})
    composite = hashlib.sha256(json.dumps(source_inputs, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    binary = output/'build'
    options = base.build_options()
    if portable_fixtures:
        options += [f'-DGGML_{feature}=OFF' for feature in
                    ('AVX','AVX2','FMA','F16C','BMI2','AVX512','AVX512_VBMI','AVX512_VNNI','AMX_TILE','AMX_INT8','AMX_BF16')]
    commands = [[cmake, '-S', str(source), '-B', str(binary), '-G', 'Ninja', *options],
                [cmake, '--build', str(binary), '--target', *mains, '-j', '2']]
    for index, command in enumerate(commands):
        with (output/f'factorial-build-{index}.log').open('w') as log:
            subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=900,
                           preexec_fn=base.cpu.limits)
        if index == 0:
            effective = base.optimized.inspect_effective_flags(binary)
    compilers = {}
    for language in ('C', 'CXX'):
        path = Path(effective['cache']['CMAKE_'+language+'_COMPILER']).resolve()
        compilers[language] = dict(path=str(path), sha256=base.cpu.digest(path), version=subprocess.check_output([str(path),'--version'],text=True))
    libraries = [(str(p.relative_to(binary)), base.cpu.digest(p)) for p in sorted(binary.rglob('*.a'))]
    result = dict(schema='factorial-candidate-build/1', native_commit=base.cpu.PIN,
                  archive_sha256=base.cpu.ARCHIVE_SHA, source_inputs=source_inputs, composite_sha256=composite,
                  build_directory=str(binary), commands=commands, compiler_versions=compilers, build_options=options, effective_flags=effective,
                  portable_fixture_build=portable_fixtures, rpc_protocol={'major': 7}, roles={},
                  backend_libraries=libraries, preparation_seconds=time.monotonic()-started,
                  recipe_sha256=base.cpu.digest(__file__),
                  note='unmerged diagnostic CPU client; local CPU helper only; accepted CUDA worker unchanged')
    for name in mains:
        executable = binary/'bin'/name
        result['roles'][name] = dict(executable=str(executable), executable_sha256=base.cpu.digest(executable))
    (output/'factorial-candidate-receipt.json').write_text(json.dumps(result, indent=2, sort_keys=True)+'\n')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--cmake', default='cmake')
    parser.add_argument('--portable-fixtures', action='store_true')
    args = parser.parse_args()
    print(json.dumps(build(args.archive, args.output, args.cmake, args.portable_fixtures), indent=2))
