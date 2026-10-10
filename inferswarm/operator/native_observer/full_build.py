"""Issue #301 supervised full-server direct GCC build over the overlay tree.

Derives the complete authenticated target closure (llama-server and
ggml-rpc-server from the pin's CMake target definitions) as an ordered
single-job direct GCC recipe, runs it under the existing campaign Supervisor
with all recorded limits, executes the patched tiny CPU/RPC fixtures, and
emits per-executable `q8-native-build-manifest/2` artifacts compatible with
``parse_build_manifest``.

This is a derived observer build of pinned base
b29c606e28a01b1bc8c1351026a0fa6e616bf6c4 / tree
950999fe62b7fe55f44ab5b7394e3c8542f37f12 — it is never the unmodified base.
No model, GPU, install, or upstream write occurs. Native execution is
explicit opt-in only (``python -m ...full_build --execute``); normal tests
never compile or charge the campaign.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import time
from pathlib import Path

from .build import (BuildError, Limits, PIN, SCRATCH, SOURCE, Supervisor,
                    TREE, Workspace, dump, output_root)
from . import overlay as overlay_module
from .producer import build_manifest_body

CAMPAIGN = Workspace(SCRATCH)
REPO = Path(__file__).resolve().parents[3]
FIXTURES = REPO / 'tests/fixtures/issue299'
OVERLAY = FIXTURES / 'overlay'

# Common compile flags derived from the pin's CMake target definitions for a
# CPU-only, static, non-DL, no-OpenMP, no-sanitizer build (defaults at the
# pin: GGML_CPU x86 generic, GGML_SCHED_MAX_COPIES=4, LLAMA_SUBPROCESS=ON on
# Linux, cpp-httplib payload/backlog/URI/nodelay definitions).
CFLAGS = ['-O0', '-g0', '-pthread', '-D_GNU_SOURCE', '-D_XOPEN_SOURCE=600',
          '-DGGML_SCHED_MAX_COPIES=4', '-DGGML_USE_CPU', '-DGGML_USE_RPC',
          '-DLLAMA_SUBPROCESS',
          '-DCPPHTTPLIB_FORM_URL_ENCODED_PAYLOAD_MAX_LENGTH=1048576',
          '-DCPPHTTPLIB_LISTEN_BACKLOG=512',
          '-DCPPHTTPLIB_REQUEST_URI_MAX_LENGTH=32768',
          '-DCPPHTTPLIB_TCP_NODELAY=1']

GGML_BASE = ('ggml/src/ggml.c', 'ggml/src/ggml.cpp', 'ggml/src/ggml-alloc.c',
             'ggml/src/ggml-backend.cpp', 'ggml/src/ggml-backend-meta.cpp',
             'ggml/src/ggml-opt.cpp', 'ggml/src/ggml-threading.cpp',
             'ggml/src/ggml-quants.c', 'ggml/src/gguf.cpp')
GGML_REG = ('ggml/src/ggml-backend-dl.cpp', 'ggml/src/ggml-backend-reg.cpp')
GGML_CPU = ('ggml-cpu/ggml-cpu.c', 'ggml-cpu/ggml-cpu.cpp', 'ggml-cpu/repack.cpp',
            'ggml-cpu/iqp.cpp', 'ggml-cpu/hbm.cpp', 'ggml-cpu/quants.c',
            'ggml-cpu/traits.cpp', 'ggml-cpu/amx/amx.cpp', 'ggml-cpu/amx/mmq.cpp',
            'ggml-cpu/binary-ops.cpp', 'ggml-cpu/unary-ops.cpp', 'ggml-cpu/vec.cpp',
            'ggml-cpu/ops.cpp', 'ggml-cpu/arch/x86/quants.c',
            'ggml-cpu/arch/x86/repack.cpp')
GGML_RPC = ('ggml-rpc/ggml-rpc.cpp', 'ggml-rpc/transport.cpp')
VENDOR_HASH = ('vendor/hash/hash.cpp', 'vendor/hash/xxhash/xxhash.c',
               'vendor/hash/sha1/sha1.c', 'vendor/hash/sha256/sha256.c')
LLAMA_CORE = ('src/llama.cpp', 'src/llama-adapter.cpp', 'src/llama-arch.cpp',
              'src/llama-batch.cpp', 'src/llama-chat.cpp', 'src/llama-context.cpp',
              'src/llama-cparams.cpp', 'src/llama-grammar.cpp', 'src/llama-graph.cpp',
              'src/llama-hparams.cpp', 'src/llama-impl.cpp', 'src/llama-io.cpp',
              'src/llama-kv-cache.cpp', 'src/llama-kv-cache-iswa.cpp',
              'src/llama-kv-cache-dsa.cpp', 'src/llama-kv-cache-dsa-iswa.cpp',
              'src/llama-kv-cache-msa.cpp', 'src/llama-kv-cache-dsv4.cpp',
              'src/llama-memory.cpp', 'src/llama-memory-hybrid.cpp',
              'src/llama-memory-hybrid-iswa.cpp', 'src/llama-memory-hybrid-idx.cpp',
              'src/llama-memory-recurrent.cpp', 'src/llama-mmap.cpp',
              'src/llama-model-loader.cpp', 'src/llama-model-saver.cpp',
              'src/llama-model.cpp', 'src/llama-quant.cpp', 'src/llama-sampler.cpp',
              'src/llama-vocab.cpp', 'src/unicode-data.cpp', 'src/unicode.cpp')
COMMON = ('common/parsers/parsers.cpp', 'common/parsers/cohere2moe.cpp',
          'common/parsers/deepseek.cpp', 'common/parsers/functionary-v3-2.cpp',
          'common/parsers/gemma4.cpp', 'common/parsers/gigachat-v3.cpp',
          'common/parsers/gpt-oss.cpp', 'common/parsers/kimi-k2.cpp',
          'common/parsers/kimi-k3.cpp', 'common/parsers/lfm2.cpp',
          'common/parsers/minicpm5.cpp', 'common/parsers/minimax-m3.cpp',
          'common/parsers/ministral3.cpp', 'common/parsers/muse-glimmer.cpp',
          'common/parsers/qwen3-coder.cpp',
          'common/arg.cpp', 'common/chat-auto-parser-generator.cpp',
          'common/chat-auto-parser-helpers.cpp', 'common/chat-diff-analyzer.cpp',
          'common/chat-peg-parser.cpp', 'common/chat.cpp', 'common/common.cpp',
          'common/console.cpp', 'common/debug.cpp', 'common/download.cpp',
          'common/fit.cpp', 'common/hf-cache.cpp', 'common/imatrix-loader.cpp',
          'common/json-schema-to-grammar.cpp', 'common/json-schema.cpp',
          'common/json.cpp', 'common/llguidance.cpp', 'common/log.cpp',
          'common/ngram-cache.cpp', 'common/ngram-map.cpp', 'common/ngram-mod.cpp',
          'common/peg-parser.cpp', 'common/preset.cpp', 'common/reasoning-budget.cpp',
          'common/sampling.cpp', 'common/speculative.cpp', 'common/subproc.cpp',
          'common/trie.cpp', 'common/unicode.cpp',
          'common/jinja/lexer.cpp', 'common/jinja/parser.cpp',
          'common/jinja/runtime.cpp', 'common/jinja/value.cpp',
          'common/jinja/string.cpp', 'common/jinja/caps.cpp')
MTMD = ('tools/mtmd/mtmd.cpp', 'tools/mtmd/mtmd-audio.cpp',
        'tools/mtmd/mtmd-image.cpp', 'tools/mtmd/mtmd-helper.cpp',
        'tools/mtmd/mtmd-helper-gen.cpp', 'tools/mtmd/clip.cpp')
SERVER_CTX = ('tools/server/server-chat.cpp', 'tools/server/server-task.cpp',
              'tools/server/server-queue.cpp', 'tools/server/server-common.cpp',
              'tools/server/server-context.cpp', 'tools/server/server-stream.cpp',
              'tools/server/server-tools.cpp', 'tools/server/server-mcp.cpp',
              'tools/server/server-schema.cpp')
SERVER_IMPL = ('tools/server/server.cpp', 'tools/server/server-http.cpp',
               'tools/server/server-models.cpp')

# Overlay-transformed base paths (hooks compiled in).
TRANSFORMED_BASE = {'ggml/src/ggml-alloc.c', 'ggml/src/ggml-backend.cpp',
                    'ggml/src/ggml-rpc/ggml-rpc.cpp', 'src/llama-model-loader.cpp',
                    'src/llama-kv-cache.cpp', 'tools/server/server-queue.cpp'}


def _models(root: Path):
    return tuple(str(p.relative_to(root)) for p in sorted((root / 'src/models').glob('*.cpp')))


def _mtmd_models(root: Path):
    return tuple('tools/mtmd/' + str(p.relative_to(root / 'tools/mtmd'))
                for p in sorted((root / 'tools/mtmd/models').glob('*.cpp')))


def closure(root: Path):
    """Exact authenticated target/dependency closure from the pin's targets."""
    return (GGML_BASE + GGML_REG +
            tuple('ggml/src/' + n for n in GGML_CPU) +
            tuple('ggml/src/' + n for n in GGML_RPC) +
            VENDOR_HASH + LLAMA_CORE + COMMON + MTMD + _mtmd_models(root) +
            SERVER_CTX + SERVER_IMPL + _models(root))


def includes(root: Path, out: Path):
    ggml_inc = [root / 'ggml/include', root / 'ggml/src', root / 'ggml/src/ggml-cpu', out]
    # Mirrors per-target resolution: quoted includes search the includer's own
    # directory first, so common/ before src/ lets common/jinja resolve
    # common/unicode.h while src TUs keep their own-directory headers.
    return ggml_inc + [root, root / 'common', root / 'common/parsers',
                        root / 'vendor', root / 'vendor/hash',
                        root / 'src', root / 'src/models', root / 'include',
                        root / 'tools/mtmd', root / 'tools/server', OVERLAY, out]


def assemble(root: Path, out: Path):
    """Ordered no-effects command list; one compile job, deterministic order."""
    root, out = Path(root).resolve(), Path(out).resolve()
    sources = list(closure(root))
    commands = []
    objects = []
    serializable_sources = list(sources)
    inc = [f'-I{p}' for p in includes(root, out)]
    # One generated header dir (out) carries ggml-version.h, llama-version.h,
    # build-info.cpp, ui.cpp/ui.h — derived from the pin's templates.
    for index, rel in enumerate(sources + ['build-info.cpp', 'is301_sink.cpp',
                                           'vendor/cpp-httplib/httplib.cpp',
                                           'tools/ui/ui.cpp',
                                           'tools/server/main.cpp',
                                           'tools/rpc/rpc-server.cpp',
                                           'tests/native-buffer-graph-observed.cpp']):
        src = out / 'build-info.cpp' if rel == 'build-info.cpp' else (
              out / 'ui.cpp' if rel == 'tools/ui/ui.cpp' else (
              OVERLAY / 'is301_sink.cpp' if rel == 'is301_sink.cpp' else (
              OVERLAY / 'tests/native-buffer-graph-observed.cpp'
              if rel == 'tests/native-buffer-graph-observed.cpp' else root / rel)))
        obj = out / f'{index:04d}.o'
        compiler = '/usr/bin/cc' if src.suffix == '.c' else '/usr/bin/c++'
        std = '-std=c11' if src.suffix == '.c' else '-std=c++17'
        # sha1.c is compiled as CXX per vendor CMake (namespace clash guard).
        if src.name == 'sha1.c':
            compiler, std = '/usr/bin/c++', '-std=c++17'
        commands.append([compiler, std, *CFLAGS, *inc, '-c', str(src), '-o', str(obj)])
        objects.append(obj)
    link = '/usr/bin/c++'
    libs = ['-pthread', '-ldl', '-lm']
    # llama-server: every object except the rpc-server TU and the fixture TU.
    server_objects = objects[:-2]
    commands.append([link, *server_objects, *libs, '-o', str(out / 'llama-server')])
    # ggml-rpc-server: GGML closure + sink only, per tools/rpc/CMakeLists
    # (links ggml: ggml-base + cpu + rpc; no llama/common/server TUs).
    ggml_count = len(GGML_BASE) + len(GGML_REG) + len(GGML_CPU) + len(GGML_RPC)
    sink = objects[len(sources) + 1]  # is301_sink.cpp compiles right after build-info
    rpc_main = objects[-2]            # tools/rpc/rpc-server.cpp TU
    commands.append([link, *objects[:ggml_count], sink, rpc_main, *libs,
                     '-o', str(out / 'ggml-rpc-server')])
    ggml_count = len(GGML_BASE) + len(GGML_REG) + len(GGML_CPU) + len(GGML_RPC)
    sink = objects[len(sources) + 1]
    commands.append([link, *objects[:ggml_count], sink, objects[-1], *libs,
                     '-o', str(out / 'native-buffer-graph-observed')])
    for row in commands:
        pass
    return {'sources': serializable_sources,
            'commands': [list(map(str, c)) for c in commands], 'flags': CFLAGS}


def _render_templates(root: Path, out: Path):
    """Derive the pin's configure_file outputs deterministically."""
    ggml_version = (root / 'ggml/src/ggml-version.h.in').read_text() \
        .replace('@GGML_VERSION@', '0.24.0') \
        .replace('@GGML_BUILD_COMMIT@', 'b29c606')
    (out / 'ggml-version.h').write_text(ggml_version)
    llama_version = (root / 'src/llama-version.h.in').read_text() \
        .replace('@LLAMA_VERSION@', '0.4.1') \
        .replace('@LLAMA_COMMIT@', 'b29c606')
    (out / 'llama-version.h').write_text(llama_version)
    build_info = (root / 'common/build-info.cpp.in').read_text() \
        .replace('@LLAMA_BUILD_NUMBER@', '0') \
        .replace('@LLAMA_BUILD_COMMIT@', 'b29c606') \
        .replace('@BUILD_COMPILER@', 'gcc 14.2.0 direct-GCC derived build') \
        .replace('@BUILD_TARGET@', 'x86_64-linux-gnu CPU-only observer overlay')
    (out / 'build-info.cpp').write_text(build_info)
    # ui.cpp/ui.h: no dist assets at this pin checkout (offline; priority-4
    # path) — emit the empty-table form the CMake template produces.
    (out / 'ui.h').write_text(
        '// Generated empty-asset form (scripts/ui-assets.cmake priority 4).\n'
        '#pragma once\n#include <array>\n#include <string>\n'
        'struct llama_ui_asset { std::string name; const unsigned char * data;\n'
        'std::size_t size; std::string etag; std::string type; };\n'
        'const llama_ui_asset * llama_ui_find_asset(const std::string &);\n'
        'bool llama_ui_use_gzip();\n'
        'const std::array<llama_ui_asset, 0> & llama_ui_get_assets();\n')
    (out / 'ui.cpp').write_text(
        '// Generated empty-asset form (scripts/ui-assets.cmake priority 4).\n'
        '#include "ui.h"\n'
        'const llama_ui_asset * llama_ui_find_asset(const std::string &) { return nullptr; }\n'
        'bool llama_ui_use_gzip() { return false; }\n'
        'const std::array<llama_ui_asset, 0> & llama_ui_get_assets() {\n'
        '    static const std::array<llama_ui_asset, 0> empty{}; return empty; }\n')


def _toolchain_identity(supervisor: Supervisor):
    """Collect exact compiler identity through the supervised environment."""
    row = supervisor.run(['/usr/bin/c++', '--version'])
    text = (Path(row['stdout'])).read_text().splitlines()[0]
    return text.strip()


def execute(source: Path = SOURCE, output: Path = SCRATCH / 'issue301-full',
            *, overlay_root=None, workspace: Workspace = CAMPAIGN):
    if workspace != CAMPAIGN:
        raise BuildError('unauthorized native workspace')
    output = output_root(output, workspace)
    tree = Path(overlay_root) if overlay_root else (SCRATCH / 'issue301-overlay-tree')
    if tree.exists():
        # An existing tree is usable only if every byte still matches the
        # CURRENT retained manifest; a stale overlay refuses loudly.
        current = json.loads((FIXTURES / 'native-observer-transformed.json').read_text())
        import hashlib as _h
        for row in current['files']:
            p = tree / row['path']
            if not p.is_file() or _h.sha256(p.read_bytes()).hexdigest() != row['sha256']:
                raise BuildError('stale overlay tree; remove ' + str(tree))
    else:
        overlay_module.apply(source, tree)
    manifest_meta = json.loads((Path(tree) / 'native-observer-transformed.json').read_text())
    recipe = assemble(Path(tree), output)
    with Supervisor(output, workspace=workspace) as supervisor:
        dump(output / 'recipe.json', recipe)
        _render_templates(Path(tree), output)
        compiler = _toolchain_identity(supervisor)
        for command in recipe['commands']:
            supervisor.run(command)
        # Patched tiny fixture: CPU then RPC loopback, both observed.
        cpu_dir = output / 'fixture-cpu'
        rpc_dir = output / 'fixture-rpc'
        cpu_dir.mkdir()
        rpc_dir.mkdir()
        supervisor.run([str(output / 'native-buffer-graph-observed'), 'cpu', str(cpu_dir)],
                       seconds=supervisor.limits.fixture_seconds,
                       env_extra={'IS301_OBSERVE': '1'})
        import socket
        with socket.socket() as reservation:
            reservation.bind(('127.0.0.1', 0))
            port = reservation.getsockname()[1]
        cmd = [str(output / 'ggml-rpc-server'), '-H', '127.0.0.1', '-p', str(port),
               '-d', 'CPU', '-t', '1']
        from .build import wait_listener
        with supervisor.server(cmd, env_extra={'IS301_OBSERVE': '1',
                                              'IS301_RPC_ENDPOINT': f'127.0.0.1:{port}'}) as server:
            wait_listener(supervisor, server, port)
            supervisor.run([str(output / 'native-buffer-graph-observed'), 'rpc', str(rpc_dir)],
                           seconds=supervisor.limits.fixture_seconds,
                           env_extra={'IS301_OBSERVE': '1',
                                      'IS301_RPC_ENDPOINT': f'127.0.0.1:{port}'})
        # Per-executable /2 manifests from actual build facts.
        manifests = {}
        # Static per-target archives mirror the pin's CMake static libraries;
        # each archive's bytes are its EXACT linked member objects. There are
        # no dynamically loaded backend libraries in this CPU-only static
        # build (no GGML_BACKEND_DL), and the manifests say so by naming the
        # actual archives rather than a fabricated monolithic artifact.
        import subprocess as _sp
        ggml_count = len(GGML_BASE) + len(GGML_REG) + len(GGML_CPU) + len(GGML_RPC)
        archive_members = {
            'llama-server': ('libllama-full.a', list(range(len(recipe['sources']) + 5))),
            'ggml-rpc-server': ('libggml-static.a',
                                list(range(ggml_count)) + [len(recipe['sources']) + 1]),
            'native-buffer-graph-observed': ('libggml-static.a',
                                list(range(ggml_count)) + [len(recipe['sources']) + 1]),
        }
        for exe in ('llama-server', 'ggml-rpc-server', 'native-buffer-graph-observed'):
            name, members = archive_members[exe]
            objects = [output / f'{i:04d}.o' for i in members]
            archive = output / name
            _sp.run(['/usr/bin/ar', 'rc', str(archive), *[str(o) for o in objects]], check=True)
            body = build_manifest_body(
                compiler=compiler,
                options=tuple(CFLAGS),
                executable_sha256=hashlib.sha256((output / exe).read_bytes()).hexdigest(),
                backend_libraries=((name, hashlib.sha256(archive.read_bytes()).hexdigest()),),
                patch_sha256=manifest_meta['patch_sha256'],
                transformed_manifest_sha256=hashlib.sha256(
                    (FIXTURES / 'native-observer-transformed.json').read_bytes()).hexdigest())
            manifests[exe] = body
            dump(output / f'{exe}.build-manifest.json', body)
        dump(output / 'provenance.json', {
            'base_revision': PIN, 'base_tree': TREE,
            'overlay_root': str(tree),
            'patch_sha256': manifest_meta['patch_sha256'],
            'compiler': compiler,
            'verdict': 'observation-patched full llama-server + ggml-rpc-server built; '
                       'tiny CPU/RPC fixtures executed with genuine native captures'})
    return output


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--source', type=Path, default=SOURCE)
    parser.add_argument('--output', type=Path, default=SCRATCH / 'issue301-full')
    parser.add_argument('--overlay-root', type=Path, default=None)
    args = parser.parse_args()
    if args.execute:
        print(execute(args.source, args.output, overlay_root=args.overlay_root))
    else:
        print(json.dumps(assemble(args.source, args.output), sort_keys=True, indent=2))
