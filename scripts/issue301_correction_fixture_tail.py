#!/usr/bin/env python3
"""PR #304 correction — supervised fixture-tail phase (incremental).

The phase5 build compiled ALL 37 GGML-closure TUs against the corrected
observer header and linked the three executables; only the RPC fixture run
failed (missing sched reserve, now fixed in the fixture TU). This phase
recompiles ONLY the fixture TU, relinks native-buffer-graph-observed, and
runs the three fixtures + manifests + provenance. Expected spend < 60s.
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
OUT = SCRATCH / 'issue301-correction-ggml'

# Refresh EVERY overlay file in the authenticated tree (the observer header
# and any transformed bytes may have changed since the tree was materialized),
# then re-verify all inputs against the CURRENT retained manifest.
import shutil
for rel in list(overlay_module.TRANSFORMED) + list(overlay_module.NEW_FILES):
    src = Path(fb.OVERLAY) / rel
    (TREE / rel).write_bytes(src.read_bytes())
shutil.copyfile(Path(fb.FIXTURES) / 'native-observer-transformed.json',
                TREE / 'native-observer-transformed.json')
verified = fb.verify_tree_inputs(TREE, SOURCE)
print('re-authenticated input files:', len(verified))

recipe = json.loads((OUT / 'recipe.json').read_text())
# Recompile every header-dependent TU: transformed C++ files + sink + fixtures.
recompile_names = ('ggml-backend.cpp', 'ggml-rpc.cpp', 'is301_sink.cpp',
                   'native-buffer-graph-observed.cpp', 'native-fact-bounds.cpp')
recompiles = [[str(a) for a in c] for c in recipe['commands']
              if '-c' in c and any(n in str(c[c.index('-c') + 1]) for n in recompile_names)]
compile_fb = recompiles[0]

with Supervisor(SCRATCH / 'issue301-correction-tail2', workspace=Workspace(SCRATCH)) as supervisor:
    for c in recompiles:
        supervisor.run(c)
    # relink observed fixture: reuse GGML objects + sink + fresh fixture obj
    import glob
    ggml_objs = sorted(glob.glob(str(OUT / '0*.o')))
    keep = []
    for c in recipe['commands']:
        if '-c' not in c:
            continue
        src = c[c.index('-c') + 1]
        if '/ggml/' in src or '/vendor/hash/' in src or src.endswith('/is301_sink.cpp'):
            keep.append(c[c.index('-o') + 1])
    sink = [o for o in keep if o.endswith('.o') and 'is301' not in o]
    # sink object is identified by the compile command output for is301_sink.cpp
    sink_obj = [c[c.index('-o') + 1] for c in recipe['commands']
                if '-c' in c and str(c[c.index('-c') + 1]).endswith('is301_sink.cpp')][0]
    fb_obj = [c[c.index('-o') + 1] for c in recipe['commands']
              if '-c' in c and 'native-fact-bounds' in str(c[c.index('-c') + 1])][0]
    observed_obj = compile_fb[compile_fb.index('-o') + 1]
    ggml_only = [c[c.index('-o') + 1] for c in recipe['commands']
                 if '-c' in c and ('/ggml/' in str(c[c.index('-c') + 1]) or '/vendor/hash/' in str(c[c.index('-c') + 1]))]
    link = ['/usr/bin/c++', '-pthread', '-ldl', '-lm']
    supervisor.run([*link, *ggml_only, sink_obj, observed_obj,
                    '-o', str(OUT / 'native-buffer-graph-observed')])
    rpc_obj = [c[c.index('-o') + 1] for c in recipe['commands']
               if '-c' in c and 'rpc-server.cpp' in str(c[c.index('-c') + 1])][0]
    supervisor.run([*link, *ggml_only, sink_obj, rpc_obj,
                    '-o', str(OUT / 'ggml-rpc-server')])
    supervisor.run([*link, *ggml_only, sink_obj, fb_obj,
                    '-o', str(OUT / 'native-fact-bounds')])
    print('all three executables relinked')

    cpu_dir = OUT / 'fixture-cpu'
    rpc_dir = OUT / 'fixture-rpc'
    export_root = OUT / 'exports'
    for d in (cpu_dir, rpc_dir, export_root / 'fixture-cpu', export_root / 'rpc-server',
              export_root / 'fixture-rpc'):
        d.mkdir(parents=True, exist_ok=True)
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
    fb_dir.mkdir(exist_ok=True)
    supervisor.run([str(OUT / 'native-fact-bounds'), str(fb_dir)],
                   seconds=supervisor.limits.fixture_seconds,
                   env_extra={'IS301_OBSERVE': '1'})
    print('fixtures executed')

    fb.verify_tree_inputs(TREE, SOURCE)
    manifest_meta = json.loads((TREE / 'native-observer-transformed.json').read_text())
    transformed_paths = set(overlay_module.TRANSFORMED) | set(overlay_module.NEW_FILES)
    untransformed_inputs = {p: d for p, d in verified.items()
                            if p not in transformed_paths and p != 'native-observer-transformed.json'}
    compiler = subprocess.check_output(['/usr/bin/c++', '--version'], text=True).splitlines()[0].strip()
    link_inputs = {}
    executable_hashes = {}
    for exe, member_objs in (('ggml-rpc-server', ggml_only + [sink_obj] + [o for o in [c[c.index('-o')+1] for c in recipe['commands'] if '-c' in c and 'rpc-server.cpp' in str(c[c.index('-c')+1])]]),
                             ('native-buffer-graph-observed', ggml_only + [sink_obj, observed_obj]),
                             ('native-fact-bounds', ggml_only + [sink_obj, fb_obj])):
        ordered = [hashlib.sha256(Path(o).read_bytes()).digest() for o in member_objs]
        link_inputs[exe] = {'objects': [str(o) for o in member_objs],
                            'sha256': hashlib.sha256(b''.join(ordered)).hexdigest()}
        archive = OUT / 'libggml-static.a'
        subprocess.run(['/usr/bin/ar', 'rc', str(archive), *[str(o) for o in member_objs]], check=True)
        executable_hashes[exe] = hashlib.sha256((OUT / exe).read_bytes()).hexdigest()
        body = build_manifest_body(
            compiler=compiler, options=tuple(fb.CFLAGS),
            executable_sha256=executable_hashes[exe],
            backend_libraries=((archive.name, hashlib.sha256(archive.read_bytes()).hexdigest()),),
            patch_sha256=manifest_meta['patch_sha256'],
            transformed_manifest_sha256=hashlib.sha256(
                (Path(fb.FIXTURES) / 'native-observer-transformed.json').read_bytes()).hexdigest())
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
print('FIXTURE-TAIL PHASE COMPLETE')
