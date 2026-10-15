"""Bounded role-specific CUDA worker build for the selective-backing pair.

Composes the SAME pinned archive, retained observer overlay and #316/#311
native cache patch as ``operator-build.py`` (its ``compose`` is imported, never
duplicated or edited: its own bytes are part of the accepted CPU
``patch_sha256`` identity). This recipe then configures the pin's own CMake
with ``GGML_CUDA=ON`` for the RPC worker role only. The coordinator CPU/RPC
build and the accepted CPU identity table are untouched.

Conventions are reused, not re-listed: nvcc flags, ``--extended-lambda``, the
FlashAttention instance defines, cuBLAS/cudart linkage and the CUDA driver
(VMM) dependency all come from the pinned tree's own CMake files, so no
hand-maintained compiler-flag list is introduced here. Only the real driver
library location is resolved separately, through the repository's corrected
stub-refusing probe in ``tools/moe-overlap/build.py``; ``CUDA_CUDA_LIBRARY``
is bound explicitly so CMake cannot silently link a toolkit stub. No compiler
wrapper is used.

Candidate receipts stay separate from accepted identities: this script writes
its receipt under the owned output directory only. It never edits
``operator-build-identities.json``; a ``remote-cuda`` row appears there only
after maintainer review of a real hardware build, and until then ordinary
startup refuses the one-GPU selective pair.

No download, install, model bytes, GPU probe or inference happens here; the
build itself never touches a device. The CUDA compile has historically taken
roughly 45-60 minutes with two jobs, so the per-command timeout defaults to
90 minutes and must not be shortened to an impossible 30-minute budget.
"""
from __future__ import annotations
import argparse
import ast
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve().parent


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise SystemExit('cannot load module from ' + str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        while data := stream.read(1 << 20): h.update(data)
    return h.hexdigest()


def cpu_build_options(operator_build_source):
    """Extract operator-build.py's exact CPU option list without editing it.

    The list is a literal inside ``build()``; reading it through ``ast``
    keeps one source of truth and fails closed if the recipe ever changes
    shape (a silent duplicated copy could drift from the accepted CPU build).
    """
    tree = ast.parse(operator_build_source.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == 'options' for t in node.targets):
            try:
                return list(ast.literal_eval(node.value))
            except ValueError:
                break
    raise SystemExit('cannot extract the CPU option list from operator-build.py; '
                     'refusing to guess a duplicate')


def cuda_options(cpu_options, arch, toolkit, driver_arguments):
    """Backend-bound option list; the pin's CMake owns every nvcc flag.

    Starts from the accepted CPU recipe's exact option list (one source of
    truth) and flips exactly one backend switch, adds the single-GPU
    architecture, the nvcc location and the validated driver binding.
    """
    if '-DGGML_CUDA=OFF' not in cpu_options:
        raise SystemExit('CPU option list does not carry the expected CUDA=OFF switch')
    options = [o for o in cpu_options if o != '-DGGML_CUDA=OFF']
    nvcc = str(Path(toolkit) / 'bin' / 'nvcc')
    return options + ['-DGGML_CUDA=ON', '-DCMAKE_CUDA_ARCHITECTURES=' + str(arch),
                      '-DCMAKE_CUDA_COMPILER=' + nvcc, *driver_arguments]


def driver_resolution(cxx, pin):
    """Validated real-driver resolution through the corrected shared probe.

    ``pin.cuda_driver_flags`` already refuses toolkit stubs, requires ELF and
    proves the VMM symbol link. Map its verdict to an explicit
    ``CUDA_CUDA_LIBRARY`` so CMake binds the same validated library.
    """
    flags = pin.cuda_driver_flags(cxx)
    if '-lcuda' in flags:
        # The probe linked -lcuda; resolve the development library through
        # the reviewed probe's own -L directory (fail closed on shape drift
        # rather than guessing a path).
        link_dir = next((f[2:] for f in flags if f.startswith('-L')), None)
        if link_dir is None:
            raise SystemExit('shared CUDA probe returned no -L directory; refusing to guess')
        resolved = Path(link_dir) / 'libcuda.so'
    else:
        resolved = Path(flags[0])
    if not resolved.is_file():
        raise SystemExit('validated CUDA driver path is not a file: ' + str(resolved))
    record = dict(link_flags=flags, resolved_path=str(resolved),
                  resolved_sha256=digest(resolved))
    return record, ['-DCUDA_CUDA_LIBRARY=' + str(resolved)]


def cuda_build(archive, output, cmake, *, arch, jobs, timeout, toolkit):
    cpu = _load('operator_build_cpu', HERE / 'operator-build.py')
    pin = _load('moe_overlap_pin', HERE.parent / 'moe-overlap' / 'build.py')
    source, composite = cpu.compose(Path(archive), Path(output))
    output = Path(output)
    binary = output / 'build'
    cxx = pin.pick_compiler('c++')
    driver_record, driver_arguments = driver_resolution(cxx, pin)
    nvcc = shutil.which('nvcc') or str(Path(toolkit) / 'bin' / 'nvcc')
    if not Path(nvcc).is_file():
        raise SystemExit('nvcc not found; CUDA worker build requires the CUDA toolkit')
    options = cuda_options(cpu_build_options(HERE / 'operator-build.py'), arch,
                           str(Path(nvcc).parent.parent), driver_arguments)
    commands = [
        [cmake, '-S', str(source), '-B', str(binary), '-G', 'Ninja', *options],
        [cmake, '--build', str(binary), '--target', 'ggml-rpc-server', '-j', str(jobs)],
    ]
    for index, command in enumerate(commands):
        with (output / f'cuda-build-{index}.log').open('w') as log:
            subprocess.run(command, stdout=log, stderr=subprocess.STDOUT,
                           check=True, timeout=timeout, preexec_fn=cpu.limits)
    compiler = subprocess.check_output([cxx, '--version'], text=True).splitlines()[0]
    nvcc_version = subprocess.check_output([nvcc, '--version'], text=True).splitlines()[0]
    libraries = tuple((str(p.relative_to(binary)), digest(p))
                      for p in sorted(binary.rglob('*.a')))
    closure = tuple(row for row in libraries if row[0].startswith('ggml/'))
    if not any('ggml-cuda' in name for name, _ in closure):
        raise SystemExit('CUDA worker closure does not contain the ggml-cuda backend archive')
    patch = hashlib.sha256((HERE / 'native.patch').read_bytes()
                           + (HERE / 'assigned.h').read_bytes()
                           + (HERE / 'operator-build.py').read_bytes()).hexdigest()
    executable = binary / 'bin' / 'ggml-rpc-server'
    from inferswarm.operator.native_observer.producer import build_manifest_body
    body = build_manifest_body(executable_sha256=digest(executable), backend_libraries=closure,
        patch_sha256=patch, transformed_manifest_sha256=composite, compiler=compiler,
        options=options)
    manifest_path = output / 'ggml-rpc-server.build-manifest.json'
    manifest_path.write_text(json.dumps(body, indent=2) + '\n')
    # Receipt only. Accepted identities live in operator-build-identities.json
    # and change exclusively through maintainer review; nothing here writes,
    # updates or promotes them, and a receipt never becomes approval.
    receipt = dict(
        role='remote-cuda', native_commit=cpu.PIN, archive_sha256=cpu.ARCHIVE_SHA,
        composite_sha256=composite, patch_sha256=patch, compiler=compiler,
        nvcc=nvcc_version, cuda_architectures=str(arch), cuda_driver=driver_record,
        build_options=options, commands=commands,
        executable=str(executable), executable_sha256=body['executable_sha256'],
        manifest=str(manifest_path), identity=body,
        note='candidate build receipt; not an accepted runtime identity')
    (output / 'cuda-worker-receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    return receipt


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--cmake', default='cmake')
    parser.add_argument('--arch', default='86', help='CUDA architecture of the single worker GPU')
    parser.add_argument('--jobs', type=int, default=2)
    parser.add_argument('--timeout', type=int, default=5400,
                        help='per-command seconds; keep >= 45 min for the CUDA compile')
    parser.add_argument('--toolkit', default='/usr/local/cuda')
    args = parser.parse_args()
    print(json.dumps(cuda_build(args.archive, args.output, args.cmake, arch=args.arch,
                                jobs=args.jobs, timeout=args.timeout, toolkit=args.toolkit), indent=2))
