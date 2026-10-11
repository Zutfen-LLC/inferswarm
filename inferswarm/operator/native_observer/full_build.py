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
                    TREE, Workspace, compiled_inputs, dump, output_root)
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
                        root / 'tools/mtmd', root / 'tools/server', out]


def assemble(root: Path, out: Path):
    """Ordered no-effects command list; one compile job, deterministic order."""
    root, out = Path(root).resolve(), Path(out).resolve()
    sources = list(closure(root))
    extras = ['build-info.cpp', 'is301_sink.cpp', 'vendor/cpp-httplib/httplib.cpp',
              'tools/ui/ui.cpp', 'tools/server/main.cpp', 'tools/rpc/rpc-server.cpp',
              'tests/native-buffer-graph-observed.cpp', 'tests/native-fact-bounds.cpp',
              'tests/native-export-claim.cpp']
    commands, objects = [], {}
    inc = [f'-I{p}' for p in includes(root, out)]
    for index, rel in enumerate(sources + extras):
        src = (out / 'build-info.cpp' if rel == 'build-info.cpp' else
               out / 'ui.cpp' if rel == 'tools/ui/ui.cpp' else root / rel)
        obj = out / f'{index:04d}.o'
        compiler = '/usr/bin/cc' if src.suffix == '.c' else '/usr/bin/c++'
        std = '-std=c11' if src.suffix == '.c' else '-std=c++17'
        if src.name == 'sha1.c':
            compiler, std = '/usr/bin/c++', '-std=c++17'
        commands.append([compiler, std, *CFLAGS, *inc, '-MD', '-MF',
                         str(obj.with_suffix('.d')), '-c', str(src), '-o', str(obj)])
        objects[rel] = str(obj)
    ggml_sources = [rel for rel in sources if rel.startswith('ggml/')]
    ggml_members = [objects[rel] for rel in ggml_sources] + [objects['is301_sink.cpp']]
    mains = {'llama-server': 'tools/server/main.cpp',
             'ggml-rpc-server': 'tools/rpc/rpc-server.cpp',
             'native-buffer-graph-observed': 'tests/native-buffer-graph-observed.cpp',
             'native-fact-bounds': 'tests/native-fact-bounds.cpp',
             'native-export-claim': 'tests/native-export-claim.cpp'}
    server_members = [obj for rel, obj in objects.items() if rel not in set(mains.values())]
    for target, main in mains.items():
        members = server_members if target == 'llama-server' else ggml_members
        commands.append(['/usr/bin/c++', *members, objects[main], '-pthread', '-ldl',
                         '-lm', '-o', str(out / target)])
    return {'sources': sources, 'commands': commands, 'flags': list(CFLAGS)}


EXECUTABLES = ('llama-server', 'ggml-rpc-server', 'native-buffer-graph-observed',
               'native-fact-bounds', 'native-export-claim')


def _link_membership(recipe):
    """Keep exact ordered object paths from actual linker commands."""
    return {Path(command[command.index('-o') + 1]).name:
            [arg for arg in command[:command.index('-o')] if arg.endswith('.o')]
            for command in recipe['commands'] if '-o' in command and '-c' not in command
            and Path(command[command.index('-o') + 1]).name in EXECUTABLES}


def _archive_membership(recipe):
    """Backend/library closures only: never executable main translation units."""
    compiles = {c[c.index('-o') + 1]: Path(c[c.index('-c') + 1])
                for c in recipe['commands'] if '-c' in c}
    links = _link_membership(recipe)
    server_main = next(obj for obj in links['llama-server']
                       if compiles[obj].as_posix().endswith('/tools/server/main.cpp'))
    rpc_main = next(obj for obj in links['ggml-rpc-server']
                    if compiles[obj].as_posix().endswith('/tools/rpc/rpc-server.cpp'))
    return {'libllama-full.a': [obj for obj in links['llama-server'] if obj != server_main],
            'libggml-static.a': [obj for obj in links['ggml-rpc-server'] if obj != rpc_main]}


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


def verify_tree_inputs(tree, source) -> dict[str, str]:
    """Full-build gate: authenticate all overlay files before command assembly."""
    try:
        return overlay_module.verify_tree_inputs(Path(tree), Path(source))
    except overlay_module.OverlayError as exc:
        raise BuildError(str(exc)) from exc


def _digest_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _provenance_body(*, revision, tree, retained_patch_sha256,
                     transformed_manifest_sha256, transformed_sources,
                     untransformed_inputs, generated_inputs, compiler_identity,
                     link_inputs, executable_sha256, overlay_root,
                     legacy_compiler=None):
    pairs = sorted(untransformed_inputs.items())
    generated_rows = ([{'path': path, 'sha256': digest} for path, digest in generated_inputs.items()]
                      if isinstance(generated_inputs, dict) else list(generated_inputs))
    aggregate = hashlib.sha256(json.dumps(pairs, separators=(',', ':')).encode()).hexdigest()
    return {
        'base_revision': revision, 'base_tree': tree,
        'pinned_base': {'revision': revision, 'tree': tree},
        'overlay_root': str(overlay_root),
        'patch_sha256': retained_patch_sha256,
        'retained_patch_sha256': retained_patch_sha256,
        'transformed_manifest_sha256': transformed_manifest_sha256,
        'transformed_sources': sorted(transformed_sources, key=lambda row: row['path']),
        'untransformed_input_count': len(untransformed_inputs),
        'untransformed_inputs_sha256': aggregate,
        'generated_inputs': generated_rows,
        'compiler': legacy_compiler if legacy_compiler is not None else compiler_identity,
        'compiler_identity': compiler_identity,
        'link_inputs': link_inputs,
        'executable_sha256': executable_sha256,
        'verdict': 'observation-patched full llama-server + ggml-rpc-server built; '
                   'tiny CPU/RPC fixtures executed with genuine native captures',
    }


def _verify_generated_inputs(generated):
    for path, expected in generated.items():
        if not Path(path).is_file() or _digest_file(Path(path)) != expected:
            raise BuildError('dirty or foreign source input: ' + str(path))


def _verify_include_paths(recipe, tree, output):
    allowed = {Path(p).resolve() for p in includes(Path(tree).resolve(), Path(output).resolve())}
    for command in recipe['commands']:
        for arg in command:
            if arg.startswith('-I'):
                if not arg[2:] or Path(arg[2:]).resolve() not in allowed:
                    raise BuildError('foreign include search path: ' + arg)
            elif arg.startswith(('-isystem', '-iquote', '-idirafter', '-include',
                                 '-imacros', '--sysroot', '-isysroot', '-B', '-specs')):
                raise BuildError('foreign include/toolchain search option: ' + arg)


def _freeze_system_inputs(supervisor):
    """Freeze default C/C++ search trees BEFORE any translation unit compile.

    Discover compiler-owned and platform include roots through the SAME
    supervised sanitized environment, not ambient CPATH/CPLUS_INCLUDE_PATH.
    Depfiles later select actual consumed headers from this frozen inventory.
    """
    roots = set()
    for compiler, language in (('/usr/bin/cc', 'c'), ('/usr/bin/c++', 'c++')):
        row = supervisor.run([compiler, '-E', '-v', '-x', language, '/dev/null',
                              '-o', str(supervisor.root / ('include-probe-' + language))])
        lines = Path(row['stderr']).read_text().splitlines()
        active = False
        for line in lines:
            if line.strip() == '#include <...> search starts here:':
                active = True
            elif active and line.strip() == 'End of search list.':
                active = False
            elif active:
                root = Path(line.strip())
                if not root.is_absolute() or not root.is_dir():
                    raise BuildError('unsupported compiler include root: ' + str(root))
                roots.add(root.resolve())
    if not roots:
        raise BuildError('missing compiler include search inventory')
    frozen = {}
    for root in sorted(roots):
        for path in sorted(root.rglob('*')):
            if path.is_file():
                actual = path.resolve()
                frozen[str(actual)] = _digest_file(actual)
    return frozen


def _compiler_binary_identities(supervisor):
    binaries = {'/usr/bin/cc', '/usr/bin/c++', '/usr/bin/ar'}
    for compiler, programs in (('/usr/bin/cc', ('cc1', 'as', 'ld')),
                                ('/usr/bin/c++', ('cc1plus', 'collect2'))):
        for program in programs:
            row = supervisor.run([compiler, '-print-prog-name=' + program])
            path = Path(Path(row['stdout']).read_text().strip())
            if not path.is_absolute():
                path = Path('/usr/bin') / path
            if not path.is_file():
                raise BuildError('missing compiler binary: ' + str(path))
            binaries.add(str(path))
    return {name: {'path': str(Path(name).resolve()), 'sha256': _digest_file(Path(name))}
            for name in sorted(binaries)}


def _verify_compiler_binaries(identities):
    for name, row in identities.items():
        if str(Path(name).resolve()) != row['path'] or _digest_file(Path(name)) != row['sha256']:
            raise BuildError('changed compiler binary: ' + name)


def _verify_compiled_inputs(depfiles, cwd, frozen):
    """Verify consumed depfile inputs against separated precompile inventories."""
    actual = compiled_inputs(depfiles, cwd)
    result = {kind: {} for kind in frozen}
    for path, digest in actual.items():
        kinds = [kind for kind, inventory in frozen.items() if path in inventory]
        if len(kinds) != 1:
            raise BuildError('unknown dependency (not frozen): ' + path)
        kind = kinds[0]
        if digest != frozen[kind][path]:
            raise BuildError('changed dependency since precompile freeze: ' + path)
        result[kind][path] = digest
    return result


def _sealed_record(path):
    from ..profiles import canonical
    record = json.loads(Path(path).read_bytes())
    digest = record.get('terminal_digest')
    if digest != hashlib.sha256(canonical({k: v for k, v in record.items()
                                         if k != 'terminal_digest'})).hexdigest():
        raise BuildError('invalid native capture seal: ' + str(path))
    return record


def _verify_fact_captures(directory):
    from ..bindings import TransportReply
    from ..phased_observation import parse_observation
    for name in ('fact-bounds-capture.json', 'fact-scalar-overwrite.json'):
        path = directory / name
        record = _sealed_record(path)
        if record['dropped_events'] != 1:
            raise BuildError('native fact refusal completeness mismatch: ' + name)
        if name == 'fact-scalar-overwrite.json':
            if not record['overflow'] or record['facts'].get('overwrite-bound') != 'small':
                raise BuildError('native scalar overwrite corrupted prior value')
        try:
            parse_observation(TransportReply(0, path.read_bytes()))
        except ValueError:
            pass
        else:
            raise BuildError('native overbound capture accepted: ' + name)
    clean = parse_observation(TransportReply(0, (directory / 'fact-bounds-clean.json').read_bytes()))
    if clean.dropped_events or clean.overflow:
        raise BuildError('native clean capture is incomplete')


def _verify_claim_proof(directory):
    from ..bindings import TransportReply
    from ..phased_observation import parse_observation
    files = sorted(Path(directory).iterdir())
    captures = [p for p in files if p.suffix == '.json']
    if len(captures) != 1 or len(files) != 2 or not (directory / 'is301-claim').is_file():
        raise BuildError('native two-process claim proof produced unexpected files')
    owner = (directory / 'is301-claim').read_text().splitlines()
    record = _sealed_record(captures[0])
    process = record['facts']['process']
    if owner != [str(process['pid']), str(process['start_ticks']), 'claim-race']:
        raise BuildError('native claim owner identity mismatch')
    parse_observation(TransportReply(0, captures[0].read_bytes()))


def _toolchain_identity(supervisor: Supervisor):
    """Collect exact compiler identity through the supervised environment."""
    row = supervisor.run(['/usr/bin/c++', '--version'])
    return Path(row['stdout']).read_text().splitlines()[0].strip()


def execute(source: Path = SOURCE, output: Path = SCRATCH / 'issue301-full',
            *, overlay_root=None, workspace: Workspace = CAMPAIGN,
            issue301_authorized_extension: bool = False):
    if workspace != CAMPAIGN:
        raise BuildError('unauthorized native workspace')
    output = output_root(output, workspace)
    source = Path(source).resolve()
    tree = Path(overlay_root).absolute() if overlay_root else (SCRATCH / 'issue301-overlay-tree')
    if tree.exists():
        overlay_module.authenticate(source)
    else:
        overlay_module.apply(source, tree)
    authenticated_inputs = verify_tree_inputs(tree, source)
    manifest_meta = json.loads((tree / 'native-observer-transformed.json').read_text())
    transformed_paths = set(overlay_module.TRANSFORMED) | set(overlay_module.NEW_FILES)
    untransformed_inputs = {path: digest for path, digest in authenticated_inputs.items()
                            if path not in transformed_paths and path != 'native-observer-transformed.json'}
    recipe = assemble(tree, output)
    _verify_include_paths(recipe, tree, output)
    if type(issue301_authorized_extension) is not bool:
        raise BuildError('issue301 extension requires explicit boolean opt-in')
    supervisor_options = {}
    if issue301_authorized_extension:
        from .build import Issue301Authorization
        supervisor_options['authorization'] = Issue301Authorization()
    with Supervisor(output, workspace=workspace, **supervisor_options) as supervisor:
        dump(output / 'recipe.json', recipe)
        _render_templates(tree, output)
        generated_paths = ('build-info.cpp', 'ggml-version.h', 'llama-version.h', 'ui.cpp', 'ui.h')
        generated_inputs = {str(output / name): _digest_file(output / name) for name in generated_paths}
        compiler = _toolchain_identity(supervisor)
        compiler_binaries = _compiler_binary_identities(supervisor)
        frozen = {'tree': {str(tree / path): digest for path, digest in authenticated_inputs.items()},
                  'generated': generated_inputs, 'system': _freeze_system_inputs(supervisor)}
        dump(output / 'precompile-inputs.json', frozen)
        depfiles = []
        for command in recipe['commands']:
            _verify_compiler_binaries(compiler_binaries)
            supervisor.run(command)
            if '-c' in command:
                dep = Path(command[command.index('-MF') + 1])
                _verify_compiled_inputs([dep], output, frozen)
                depfiles.append(dep)
        consumed_inputs = _verify_compiled_inputs(depfiles, output, frozen)
        # Close the tampering window before any fixture execution or manifests.
        verify_tree_inputs(tree, source)
        _verify_generated_inputs(generated_inputs)
        _verify_compiler_binaries(compiler_binaries)
        # Bounded no-model executable smoke check: build identity only, no
        # model loading, inference, device qualification or performance claim.
        supervisor.run([str(output / 'llama-server'), '--version'],
                       seconds=supervisor.limits.fixture_seconds)
        # Patched tiny fixture: CPU then RPC loopback, both observed.
        export_root = output / 'exports'
        for name in ('fixture-cpu', 'rpc-server', 'fixture-rpc'):
            (export_root / name).mkdir(parents=True, exist_ok=True)
        cpu_dir = output / 'fixture-cpu'
        rpc_dir = output / 'fixture-rpc'
        cpu_dir.mkdir()
        rpc_dir.mkdir()
        supervisor.run([str(output / 'native-buffer-graph-observed'), 'cpu', str(cpu_dir)],
                       seconds=supervisor.limits.fixture_seconds,
                       env_extra={'IS301_OBSERVE': '1',
                                  'IS301_EXPORT_DIR': str(output / 'exports' / 'fixture-cpu')})
        import socket
        with socket.socket() as reservation:
            reservation.bind(('127.0.0.1', 0))
            port = reservation.getsockname()[1]
        cmd = [str(output / 'ggml-rpc-server'), '-H', '127.0.0.1', '-p', str(port),
               '-d', 'CPU', '-t', '1']
        from .build import wait_listener
        with supervisor.server(cmd, env_extra={'IS301_OBSERVE': '1',
                                              'IS301_RPC_ENDPOINT': f'127.0.0.1:{port}',
                                              'IS301_EXPORT_DIR': str(export_root / 'rpc-server')}) as server:
            wait_listener(supervisor, server, port)
            supervisor.run([str(output / 'native-buffer-graph-observed'), 'rpc', str(rpc_dir)],
                           seconds=supervisor.limits.fixture_seconds,
                           env_extra={'IS301_OBSERVE': '1',
                                      'IS301_RPC_ENDPOINT': f'127.0.0.1:{port}',
                                      'IS301_EXPORT_DIR': str(export_root / 'fixture-rpc')})
        # Adversarial fact-bounds fixture: refused-overbound capture + clean capture.
        fact_bounds_dir = output / 'fixture-fact-bounds'
        fact_bounds_dir.mkdir()
        supervisor.run([str(output / 'native-fact-bounds'), str(fact_bounds_dir)],
                       seconds=supervisor.limits.fixture_seconds,
                       env_extra={'IS301_OBSERVE': '1'})
        _verify_fact_captures(fact_bounds_dir)
        claim_dir = export_root / 'claim-proof'
        claim_dir.mkdir()
        supervisor.run([str(output / 'native-export-claim'), str(claim_dir)],
                       seconds=supervisor.limits.fixture_seconds,
                       env_extra={'IS301_OBSERVE': '1', 'IS301_EXPORT_DIR': str(claim_dir)})
        _verify_claim_proof(claim_dir)
        # Create each distinct library closure once. These exclude executable
        # mains; ordered full executable membership is recorded separately.
        archive_members = _archive_membership(recipe)
        archive_hashes = {}
        for name, objects in archive_members.items():
            archive = output / name
            supervisor.run(['/usr/bin/ar', 'rc', str(archive), *objects])
            listing = supervisor.run(['/usr/bin/ar', 't', str(archive)])
            if Path(listing['stdout']).read_text().splitlines() != [Path(p).name for p in objects]:
                raise BuildError('archive ordered membership mismatch: ' + name)
            archive_hashes[name] = _digest_file(archive)
        manifests, link_inputs, executable_hashes = {}, {}, {}
        for exe, objects in _link_membership(recipe).items():
            ordered_hashes = [_digest_file(Path(obj)) for obj in objects]
            command = next(c for c in recipe['commands'] if '-c' not in c and
                           Path(c[c.index('-o') + 1]).name == exe)
            link_inputs[exe] = {
                'objects': objects, 'object_sha256': ordered_hashes, 'command': command,
                'sha256': hashlib.sha256(b''.join(bytes.fromhex(d) for d in ordered_hashes)).hexdigest(),
            }
            name = 'libllama-full.a' if exe == 'llama-server' else 'libggml-static.a'
            executable_hashes[exe] = _digest_file(output / exe)
            body = build_manifest_body(
                compiler=compiler, options=tuple(CFLAGS),
                executable_sha256=executable_hashes[exe],
                backend_libraries=((name, archive_hashes[name]),),
                patch_sha256=manifest_meta['patch_sha256'],
                transformed_manifest_sha256=_digest_file(tree / 'native-observer-transformed.json'))
            manifests[exe] = body
            dump(output / f'{exe}.build-manifest.json', body)
        provenance = _provenance_body(
            revision=overlay_module.PIN, tree=overlay_module.TREE,
            retained_patch_sha256=manifest_meta['patch_sha256'],
            transformed_manifest_sha256=_digest_file(tree / 'native-observer-transformed.json'),
            transformed_sources=manifest_meta['files'], untransformed_inputs=untransformed_inputs,
            generated_inputs=generated_inputs, compiler_identity=compiler,
            link_inputs=link_inputs, executable_sha256=executable_hashes,
            overlay_root=tree, legacy_compiler=compiler)
        provenance.update({
            'authenticated_tree_inputs': authenticated_inputs,
            'consumed_inputs': consumed_inputs, 'compiler_binaries': compiler_binaries,
            'compile_objects': [
                {'command': c, 'object': c[c.index('-o') + 1],
                 'sha256': _digest_file(Path(c[c.index('-o') + 1])),
                 'depfile': c[c.index('-MF') + 1]}
                for c in recipe['commands'] if '-c' in c],
            'backend_archives': {name: {'objects': objects, 'sha256': archive_hashes[name]}
                                 for name, objects in archive_members.items()},
        })
        # Recheck source/generated/consumed and archive bytes before publication.
        verify_tree_inputs(tree, source)
        _verify_generated_inputs(generated_inputs)
        _verify_compiled_inputs(depfiles, output, frozen)
        _verify_compiler_binaries(compiler_binaries)
        for name, digest in archive_hashes.items():
            if _digest_file(output / name) != digest:
                raise BuildError('changed backend archive: ' + name)
        dump(output / 'provenance.json', provenance)
    return output


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--source', type=Path, default=SOURCE)
    parser.add_argument('--output', type=Path, default=SCRATCH / 'issue301-full')
    parser.add_argument('--overlay-root', type=Path, default=None)
    parser.add_argument('--issue301-authorized-extension', action='store_true',
                        help='explicit #301 approval: 6600s on the pinned continuous ledger only')
    args = parser.parse_args()
    if args.execute:
        print(execute(args.source, args.output, overlay_root=args.overlay_root,
                      issue301_authorized_extension=args.issue301_authorized_extension))
    else:
        print(json.dumps(assemble(args.source, args.output), sort_keys=True, indent=2))
