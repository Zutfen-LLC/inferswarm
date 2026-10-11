#!/usr/bin/env python3
"""PR #304 correction — supervised GGML-closure phase (budget-scoped).

The remaining cumulative ledger (~555s) cannot fund a full 338-TU rebuild
(~770s measured). This phase builds the COMPLETE authenticated GGML closure
plus the RPC server and both fixtures — proving natively: the scheduler
completion hook (ggml-backend.cpp), the collector export seam (ggml-rpc.cpp
per-connection export + fixture exports), and the fail-closed fact fences —
then runs the CPU/RPC-loopback/fact-bounds fixtures with exports and emits
/2 manifests + separated provenance for the three executables it builds.

llama-server's corrected-executable re-link is the remaining STOP item
(exact additional budget reported by the controller).
"""
import hashlib
import json
import socket
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from inferswarm.operator.native_observer.build import (Supervisor, Workspace,
                                                        SCRATCH, dump, wait_listener)
from inferswarm.operator.native_observer import full_build as fb
from inferswarm.operator.native_observer import overlay as overlay_module
from inferswarm.operator.native_observer.producer import build_manifest_body

SOURCE = SCRATCH.parent / 'llama-src'
TREE = SCRATCH / 'issue301-overlay-tree'
OUT = SCRATCH / 'issue301-correction-final'

KEEP_SUFFIXES = ('/build-info.cpp', '/is301_sink.cpp', '/rpc-server.cpp',
                 '/native-buffer-graph-observed.cpp', '/native-fact-bounds.cpp')

# 1. Fresh authenticated overlay tree (uncharged; git-blob materialization).
if TREE.exists():
    raise SystemExit('overlay tree already exists: ' + str(TREE))
overlay_module.apply(SOURCE, TREE)
verified = fb.verify_tree_inputs(TREE, SOURCE)
print('authenticated input files:', len(verified))

# 2. Assemble the full recipe, then keep only the GGML-closure commands.
recipe = fb.assemble(TREE, OUT)
compiles = [c for c in recipe['commands'] if '-c' in c]
links = [c for c in recipe['commands'] if '-c' not in c]
keep = []
for c in compiles:
    src = Path(c[c.index('-c') + 1])
    s = str(src)
    if ('/ggml/' in s or '/vendor/hash/' in s
            or s.endswith(KEEP_SUFFIXES)):
        keep.append(c)
print(f'compiles kept: {len(keep)} of {len(compiles)}')

# 3. Supervised phase: compile kept TUs, link the three executables.
with Supervisor(OUT, workspace=Workspace(SCRATCH)) as supervisor:
    dump(OUT / 'recipe.json', recipe)
    fb._render_templates(TREE, OUT)
    compiler = subprocess.check_output(['/usr/bin/c++', '--version'],
                                       text=True).splitlines()[0].strip()
    for command in keep:
        supervisor.run(command)
    objects = {}
    for c in keep:
        src = c[c.index('-c') + 1]
        obj = c[c.index('-o') + 1]
        objects[Path(src).name] = Path(obj)
    sink = objects['is301_sink.cpp']
    rpc_main = objects['rpc-server.cpp']
    observed = objects['native-buffer-graph-observed.cpp']
    fact_bounds = objects['native-fact-bounds.cpp']
    ggml_objs = [c[c.index('-o') + 1] for c in keep
                 if '/ggml/' in c[c.index('-c') + 1] or '/vendor/hash/' in c[c.index('-c') + 1]]
    link = ['/usr/bin/c++', '-pthread', '-ldl', '-lm']
    supervisor.run([*link, *ggml_objs, str(sink), str(rpc_main),
                    '-o', str(OUT / 'ggml-rpc-server')])
    supervisor.run([*link, *ggml_objs, str(sink), str(observed),
                    '-o', str(OUT / 'native-buffer-graph-observed')])
    supervisor.run([*link, *ggml_objs, str(sink), str(fact_bounds),
                    '-o', str(OUT / 'native-fact-bounds')])
    print('three executables linked')

    # 4. Fixtures with collector exports.
    cpu_dir = OUT / 'fixture-cpu'
    rpc_dir = OUT / 'fixture-rpc'
    export_root = OUT / 'exports'
    (export_root / 'fixture-cpu').mkdir(parents=True)
    (export_root / 'rpc-server').mkdir(parents=True)
    cpu_dir.mkdir()
    rpc_dir.mkdir()
    supervisor.run([str(OUT / 'native-buffer-graph-observed'), 'cpu', str(cpu_dir)],
                   seconds=supervisor.limits.fixture_seconds,
                   env_extra={'IS301_OBSERVE': '1',
                              'IS301_EXPORT_DIR': str(export_root / 'fixture-cpu')})
    with socket.socket() as reservation:
        reservation.bind(('127.0.0.1', 0))
        port = reservation.getsockname()[1]
    cmd = [str(OUT / 'ggml-rpc-server'), '-H', '127.0.0.1', '-p', str(port),
           '-d', 'CPU', '-t', '1']
    with supervisor.server(cmd, env_extra={'IS301_OBSERVE': '1',
                                           'IS301_RPC_ENDPOINT': f'127.0.0.1:{port}',
                                           'IS301_EXPORT_DIR': str(export_root / 'rpc-server')}) as server:
        wait_listener(supervisor, server, port)
        supervisor.run([str(OUT / 'native-buffer-graph-observed'), 'rpc', str(rpc_dir)],
                       seconds=supervisor.limits.fixture_seconds,
                       env_extra={'IS301_OBSERVE': '1',
                                  'IS301_RPC_ENDPOINT': f'127.0.0.1:{port}',
                                  'IS301_EXPORT_DIR': str(export_root / 'fixture-rpc')})
    fb_dir = OUT / 'fixture-fact-bounds'
    fb_dir.mkdir()
    supervisor.run([str(OUT / 'native-fact-bounds'), str(fb_dir)],
                   seconds=supervisor.limits.fixture_seconds,
                   env_extra={'IS301_OBSERVE': '1'})
    print('fixtures executed')

    # 5. Close the tampering window; manifests + provenance.
    fb.verify_tree_inputs(TREE, SOURCE)
    manifest_meta = json.loads((TREE / 'native-observer-transformed.json').read_text())
    transformed_paths = set(overlay_module.TRANSFORMED) | set(overlay_module.NEW_FILES)
    untransformed_inputs = {p: d for p, d in verified.items()
                            if p not in transformed_paths and p != 'native-observer-transformed.json'}
    manifests = {}
    link_inputs = {}
    executable_hashes = {}
    for exe, member_objs in (('ggml-rpc-server', ggml_objs + [sink, rpc_main]),
                             ('native-buffer-graph-observed', ggml_objs + [sink, observed]),
                             ('native-fact-bounds', ggml_objs + [sink, fact_bounds])):
        ordered = [hashlib.sha256(Path(o).read_bytes()).digest() for o in member_objs]
        link_inputs[exe] = {'objects': [str(o) for o in member_objs],
                            'sha256': hashlib.sha256(b''.join(ordered)).hexdigest()}
        archive = OUT / ('libggml-static.a' if exe != 'ggml-rpc-server' else 'libggml-static.a')
        subprocess.run(['/usr/bin/ar', 'rc', str(archive), *[str(o) for o in member_objs]], check=True)
        executable_hashes[exe] = hashlib.sha256((OUT / exe).read_bytes()).hexdigest()
        body = build_manifest_body(
            compiler=compiler, options=tuple(fb.CFLAGS),
            executable_sha256=executable_hashes[exe],
            backend_libraries=((archive.name, hashlib.sha256(archive.read_bytes()).hexdigest()),),
            patch_sha256=manifest_meta['patch_sha256'],
            transformed_manifest_sha256=hashlib.sha256(
                (Path(fb.FIXTURES) / 'native-observer-transformed.json').read_bytes()).hexdigest())
        manifests[exe] = body
        dump(OUT / f'{exe}.build-manifest.json', body)
    generated = {str(OUT / n): hashlib.sha256((OUT / n).read_bytes()).hexdigest()
                 for n in ('build-info.cpp', 'ggml-version.h', 'llama-version.h', 'ui.cpp', 'ui.h')}
    prov = fb._provenance_body(
        revision=overlay_module.PIN, tree=overlay_module.TREE,
        retained_patch_sha256=manifest_meta['patch_sha256'],
        transformed_manifest_sha256=hashlib.sha256(
            (Path(fb.FIXTURES) / 'native-observer-transformed.json').read_bytes()).hexdigest(),
        transformed_sources=manifest_meta['files'],
        untransformed_inputs=untransformed_inputs,
        generated_inputs=generated, compiler_identity=compiler,
        link_inputs=link_inputs, executable_sha256=executable_hashes,
        overlay_root=TREE, legacy_compiler=compiler)
    prov['llama_server_rebuild'] = ('STOP: not rebuilt in this correction round; remaining '
                                    'cumulative ledger insufficient for the ~300-TU server '
                                    'closure. Exact additional budget reported by controller.')
    dump(OUT / 'provenance.json', prov)
    print('manifests + provenance emitted')
print('GGML-CORRECTION PHASE COMPLETE')
