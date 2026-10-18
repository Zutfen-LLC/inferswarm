#!/usr/bin/env python3
"""Separate #314 CPU native-server candidate; no accepted identities changed.

Complete #311 RPCv7 + #301 observer + #309 overlap/hot overlay composition.
Build only; no model, hardware, install or promotion. --fixtures-only avoids
server compilation during focused loopback tests. --server is explicit and
builds the real server target (the default).
"""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('is314_base_composed', HERE / 'demand-build-composed.py')
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)
optimized = base.optimized
cpu = base.cpu

def build_options():
    return optimized.optimized_options()

def build(archive, output, cmake='cmake', fixtures_only=False, portable_fixtures=False):
    if portable_fixtures and not fixtures_only:
        raise ValueError('portable CPU override is only for local fixture builds')
    output = Path(output).resolve()
    source, _ = base.demand_compose(Path(archive), output)
    # The native model library owns all private FFN/collector definitions,
    # including when linked into llama-server. No second sink or dispatcher.
    with (source/'CMakeLists.txt').open('a') as stream:
        stream.write('target_sources(llama PRIVATE src/demand.cpp)\n'
                     'target_include_directories(llama PRIVATE ggml/src)\n')
        for name, main in [('native-hot-fixture', HERE/'native_hot_fixture.cpp'),
                           ('rpc-worker', HERE.parent/'moe-overlap/rpc_worker.cpp')]:
            stream.write(f'add_executable({name} "{main}")\n'
                         f'target_include_directories({name} PRIVATE src ggml/src ggml/include vendor)\n'
                         f'target_link_libraries({name} PRIVATE llama ggml-rpc)\n')
    source_inputs = {str(p.relative_to(source)):cpu.digest(p)
                     for p in sorted(source.rglob('*')) if p.is_file()}
    # External fixture/worker source are explicit build inputs too.
    source_inputs.update({str(p):cpu.digest(p) for p in
                         (HERE/'native_hot_fixture.cpp',HERE.parent/'moe-overlap/rpc_worker.cpp')})
    composite = hashlib.sha256(json.dumps(source_inputs, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    binary = output/'build'
    names = ['native-hot-fixture', 'rpc-worker']
    if not fixtures_only: names += ['llama-server', 'ggml-rpc-server']
    options = build_options()
    if portable_fixtures:
        options += [f'-DGGML_{feature}=OFF' for feature in ('AVX','AVX2','FMA','F16C','BMI2','AVX512','AVX512_VBMI','AVX512_VNNI','AMX_TILE','AMX_INT8','AMX_BF16')]
    commands = [[cmake,'-S',str(source),'-B',str(binary),'-G','Ninja',*options],
                [cmake,'--build',str(binary),'--target',*names,'-j','2']]
    for i, command in enumerate(commands):
        with (output/f'hot-build-{i}.log').open('w') as log:
            subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,check=True,timeout=3600,preexec_fn=cpu.limits)
        if i==0: effective = optimized.inspect_effective_flags(binary)
    compilers = {}
    for language in ('C','CXX'):
        path = Path(effective['cache'][f'CMAKE_{language}_COMPILER']).resolve()
        compilers[language] = dict(path=str(path),sha256=cpu.digest(path),
            version=subprocess.check_output([str(path),'--version'],text=True))
    libraries = [(str(p.relative_to(binary)),cpu.digest(p)) for p in sorted(binary.rglob('*.a'))]
    patch_sha = hashlib.sha256(json.dumps(source_inputs,sort_keys=True).encode()).hexdigest()
    result = dict(schema='is314-hot-candidate-build/1',native_commit=cpu.PIN,archive_sha256=cpu.ARCHIVE_SHA,
        build_directory=str(binary),source_inputs=source_inputs,composite_sha256=composite,
        compiler_versions=compilers,backend_libraries=libraries,commands=commands,build_options=options,
        effective_flags=effective,rpc_protocol={'major':7},roles={},
        portable_fixture_build=portable_fixtures,recipe_sha256=cpu.digest(__file__),note='candidate only; no accepted runtime identity or execution authority')
    for name in names:
        executable = binary/'bin'/name
        manifest = cpu.build_manifest_body(compiler=compilers['CXX']['version'].splitlines()[0],options=options,
            executable_sha256=cpu.digest(executable),backend_libraries=libraries,patch_sha256=patch_sha,
            transformed_manifest_sha256=composite)
        path = output/(name+'.build-manifest.json')
        path.write_text(json.dumps(manifest,indent=2)+'\n')
        result['roles'][name] = dict(executable=str(executable),manifest=str(path),identity=manifest)
    (output/'hot-candidate-receipt.json').write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
    return result

if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive',required=True)
    parser.add_argument('--output',required=True)
    parser.add_argument('--cmake',default='cmake')
    parser.add_argument('--portable-fixtures',action='store_true',help='local pre-AVX CPU fixture build only; never server')
    scope=parser.add_mutually_exclusive_group()
    scope.add_argument('--server',action='store_true',help='build complete server closure (default)')
    scope.add_argument('--fixtures-only',action='store_true')
    args=parser.parse_args()
    print(json.dumps(build(args.archive,args.output,args.cmake,args.fixtures_only,args.portable_fixtures),indent=2))
