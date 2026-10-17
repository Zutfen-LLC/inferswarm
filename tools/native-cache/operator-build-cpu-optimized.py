"""Bounded optimized CPU candidate, not runtime approval.

Reuse the historical composer and patch bytes unchanged. Keep Debug assertions,
-g0 and every backend option; replace only C/C++ Debug -O0 with -O3. Exporting
compile commands is diagnostic metadata, not a compiler/backend change.
No downloads, installs, CUDA build, model reads or runtime execution.
"""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shlex
import subprocess

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('cpu_build_support', HERE/'operator-build-cuda.py')
if spec is None or spec.loader is None:
    raise RuntimeError('cannot load historical build-option support')
support = importlib.util.module_from_spec(spec)
spec.loader.exec_module(support)
cpu = support._load('historical_cpu_composer', HERE/'operator-build.py')


def optimized_options():
    options = support.cpu_build_options(HERE/'operator-build.py')
    for language in ('C', 'CXX'):
        old = f'-DCMAKE_{language}_FLAGS_DEBUG=-O0 -g0'
        if options.count(old) != 1:
            raise ValueError('historical CPU optimization options drift')
        options[options.index(old)] = f'-DCMAKE_{language}_FLAGS_DEBUG=-O3 -g0'
    return options + ['-DCMAKE_EXPORT_COMPILE_COMMANDS=ON']


def inspect_effective_flags(binary):
    """Inspect generated CMake cache AND every generated translation unit.

    Last optimization option wins. Refuse a trailing -O0 (or any non-O3),
    assertion removal, missing command evidence or option/cache drift before
    compiling. Preserve the complete compile database for human inspection.
    """
    binary = Path(binary)
    cache = {}
    for line in (binary/'CMakeCache.txt').read_text().splitlines():
        if line and not line.startswith(('#', '//')) and ':' in line and '=' in line:
            key, value = line.split('=', 1)
            cache[key.split(':', 1)[0]] = value
    for option in optimized_options():
        key, value = option[2:].split('=', 1)
        if cache.get(key) != value:
            raise ValueError('effective CPU flags: CMake cache drift: '+key)
    rows = json.loads((binary/'compile_commands.json').read_text())
    if not rows:
        raise ValueError('missing compile commands for effective CPU flags')
    flags = set()
    for row in rows:
        argv = row.get('arguments') or shlex.split(row['command'])
        optimization = [a for a in argv if re.fullmatch(r'-O(?:[0-9]+|g|s|z|fast)?', a)]
        if not optimization or optimization[-1] != '-O3' or any('NDEBUG' in a for a in argv):
            raise ValueError('effective CPU flags: optimization/assertion drift: '+row['file'])
        flags.add(tuple(a for a in argv if a.startswith(('-O', '-g', '-D', '-U', '-f', '-m'))))
    return dict(translation_units=len(rows), cache=cache,
                compiler_flags=[list(f) for f in sorted(flags)],
                compile_commands_sha256=cpu.digest(binary/'compile_commands.json'),
                cmake_cache_sha256=cpu.digest(binary/'CMakeCache.txt'))


def build(archive, output, cmake):
    # compose owns a NEW directory and refuses existing outputs. No accepted
    # path is written and no candidate is installed or registered.
    output = Path(output)
    source, composite = cpu.compose(Path(archive), output)
    binary = output/'build'
    options = optimized_options()
    commands = [[cmake, '-S', str(source), '-B', str(binary), '-G', 'Ninja', *options],
                [cmake, '--build', str(binary), '--target', 'llama-server',
                 'ggml-rpc-server', 'is311-loader', '-j', '2']]
    effective = None
    for index, command in enumerate(commands):
        with (output/f'optimized-build-{index}.log').open('w') as log:
            subprocess.run(command, stdout=log, stderr=subprocess.STDOUT,
                           check=True, timeout=3600, preexec_fn=cpu.limits)
        if index == 0:
            effective = inspect_effective_flags(binary)
            (output/'effective-flags.json').write_text(json.dumps(effective, indent=2)+'\n')
    compiler_versions = {
        language: dict(path=effective['cache']['CMAKE_'+language+'_COMPILER'],
                       version=subprocess.check_output(
                           [effective['cache']['CMAKE_'+language+'_COMPILER'], '--version'], text=True))
        for language in ('C', 'CXX')}
    compiler = compiler_versions['CXX']['version'].splitlines()[0]
    libraries = tuple((str(p.relative_to(binary)), cpu.digest(p))
                      for p in sorted(binary.rglob('*.a')))
    # Exactly the historical native patch identity, NOT this additive recipe.
    patch = hashlib.sha256((HERE/'native.patch').read_bytes()
                           +(HERE/'assigned.h').read_bytes()
                           +(HERE/'operator-build.py').read_bytes()).hexdigest()
    result = dict(native_commit=cpu.PIN, archive_sha256=cpu.ARCHIVE_SHA,
                  composite_sha256=composite, patch_sha256=patch, compiler=compiler,
                  compiler_versions=compiler_versions,
                  cmake_version=subprocess.check_output([cmake, '--version'], text=True),
                  build_options=options, commands=commands, effective_flags=effective,
                  recipe_sha256=cpu.digest(__file__), loader_sha256=cpu.digest(binary/'bin/is311-loader'),
                  roles={}, note='candidate build receipt; not an accepted runtime identity')
    for role, name in (('client', 'llama-server'), ('remote', 'ggml-rpc-server')):
        executable = binary/'bin'/name
        closure = libraries if role == 'client' else tuple(r for r in libraries if r[0].startswith('ggml/'))
        manifest = cpu.build_manifest_body(executable_sha256=cpu.digest(executable),
            backend_libraries=closure, patch_sha256=patch,
            transformed_manifest_sha256=composite, compiler=compiler, options=options)
        path = output/(name+'.build-manifest.json')
        path.write_text(json.dumps(manifest, indent=2)+'\n')
        result['roles'][role] = dict(executable=str(executable), manifest=str(path), identity=manifest)
    (output/'optimized-cpu-receipt.json').write_text(json.dumps(result, indent=2)+'\n')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--cmake', default='cmake')
    args = parser.parse_args()
    print(json.dumps(build(args.archive, args.output, args.cmake), indent=2))
