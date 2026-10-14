"""Finite CPU #311 successor of the retained observer and cache build recipes.

Uses a retained SHA-pinned source archive, preserves the #301 fact hooks, and
builds only CPU/RPC targets. No download, install, model or GPU operation.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import resource
import shutil
import subprocess
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from inferswarm.operator.native_observer.producer import build_manifest_body

HERE = Path(__file__).resolve().parent
PIN = 'b29c606e28a01b1bc8c1351026a0fa6e616bf6c4'
ARCHIVE_SHA = '03fb04316eb32a7b7347004a79a8dd60531c02f5a064d853fed3b53828951723'
OVERLAY = ROOT/'tests/fixtures/issue299/overlay'

def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        while data := stream.read(1 << 20): h.update(data)
    return h.hexdigest()

def substitute(path, old, new):
    data = path.read_text()
    if data.count(old) != 1: raise ValueError('composite source substitution drift: '+str(path))
    path.write_text(data.replace(old, new))

def compose(archive, output):
    if digest(archive) != ARCHIVE_SHA: raise ValueError('native source archive identity mismatch')
    output.mkdir(parents=True, exist_ok=False)
    with tarfile.open(archive) as tar: tar.extractall(output, filter='data')
    source = output/('llama.cpp-'+PIN)
    manifest = json.loads((OVERLAY.parent/'native-observer-transformed.json').read_text())
    for row in manifest['files']:
        name = row['path']; origin = OVERLAY/name
        if digest(origin) != row['sha256']: raise ValueError('retained observer identity drift: '+name)
        target = source/name; target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(origin, target)
    rpc = source/'ggml/src/ggml-rpc/ggml-rpc.cpp'
    text = rpc.read_text()
    start = text.index('    if (is301::enabled()) {', text.index('static void ggml_backend_rpc_buffer_set_tensor('))
    end = text.index('\n    }', start)+6
    hook = text[start:end]
    rpc.write_text(text[:start]+text[end+1:])
    with (output/'patch.log').open('w') as log:
        subprocess.run(['patch','--batch','--fuzz=0','-p1','-i',str(HERE/'native.patch')],
            cwd=source,stdout=log,stderr=subprocess.STDOUT,check=True,timeout=30)
    # Record all attempted immutable uploads, including hash hits. The old
    # hook was after a miss-only early return and cannot prove warm consumption.
    hook = hook.replace('ctx->remote_ptr', 'request->tensor.buffer')
    substitute(rpc,'static void rpc_set_tensor(', '#include "is311_assigned.h"\n\nstatic void rpc_set_tensor(')
    substitute(rpc,'    if (size > HASH_THRESHOLD) {\n        rpc_msg_set_tensor_hash_rsp response;',
        '    if (getenv("IS311_ASSIGNED") && ggml_backend_buffer_get_usage(tensor->buffer) == GGML_BACKEND_BUFFER_USAGE_WEIGHTS) {\n'
        '        static std::map<std::string, uint64_t> destinations;\n'
        '        auto owner = destinations.emplace(tensor->name, request->tensor.id);\n'
        '        if ((!owner.second && owner.first->second != request->tensor.id) || !assigned_upload(*request)) { fprintf(stderr, "#311 unsupported immutable upload boundary/identity: %s\\n", tensor->name); GGML_ABORT("assigned upload refused"); }\n'
        '    }\n'+hook+'\n    if (size > HASH_THRESHOLD) {\n        rpc_msg_set_tensor_hash_rsp response;')
    substitute(rpc,'cache_stage stage(cache_dir && request.size > HASH_THRESHOLD ? cache_dir : nullptr);',
        'cache_stage stage(cache_dir && request.size > HASH_THRESHOLD && (!getenv("IS311_ASSIGNED") || assigned_upload(request)) ? cache_dir : nullptr);')
    substitute(rpc,'    response.result = 0;\n    ggml_context_ptr ctx',
        '    response.result = 0;\n    if (getenv("IS311_ASSIGNED") && !assigned_upload(request)) { return true; }\n    ggml_context_ptr ctx')
    shutil.copyfile(HERE/'assigned.h',source/'ggml/src/ggml-rpc/is311_assigned.h')
    shutil.copyfile(HERE/'loader.cpp',source/'is311_loader.cpp')
    # One sink owner in ggml-base is shared by both actual executables.
    with (source/'ggml/src/CMakeLists.txt').open('a') as stream:
        stream.write('\ntarget_sources(ggml-base PRIVATE "'+str(source/'is301_sink.cpp')+'")\n'
                     'target_include_directories(ggml-base PRIVATE "'+str(source)+'")\n')
    # Hooks in loader/backend/server queue resolve the same sink.
    with (source/'CMakeLists.txt').open('a') as stream:
        stream.write('\nforeach(target ggml-rpc llama server-context)\n target_include_directories(${target} PRIVATE "'+str(source)+'")\nendforeach()\n'
                     'add_executable(is311-loader is311_loader.cpp)\n'
                     'target_include_directories(is311-loader PRIVATE src ggml/src)\n'
                     'target_link_libraries(is311-loader PRIVATE llama ggml-rpc)\n')
    transformed = {str(p.relative_to(source)):digest(p) for p in source.rglob('*') if p.is_file()}
    composite = hashlib.sha256(json.dumps(transformed,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    return source, composite

def limits():
    resource.setrlimit(resource.RLIMIT_AS,(3 << 30,3 << 30))
    resource.setrlimit(resource.RLIMIT_CORE,(0,0))

def build(archive, output, cmake):
    source, composite = compose(Path(archive),Path(output))
    output = Path(output); binary = output/'build'
    options = ['-DCMAKE_BUILD_TYPE=Debug','-DCMAKE_C_FLAGS_DEBUG=-O0 -g0','-DCMAKE_CXX_FLAGS_DEBUG=-O0 -g0',
        '-DBUILD_SHARED_LIBS=OFF','-DGGML_RPC=ON','-DGGML_CUDA=OFF','-DGGML_VULKAN=OFF',
        '-DGGML_OPENMP=OFF','-DGGML_BLAS=OFF','-DGGML_NATIVE=OFF','-DLLAMA_OPENSSL=OFF',
        '-DLLAMA_BUILD_TESTS=OFF','-DLLAMA_BUILD_EXAMPLES=OFF','-DLLAMA_BUILD_TOOLS=ON',
        '-DLLAMA_BUILD_APP=OFF','-DLLAMA_BUILD_UI=OFF','-DLLAMA_USE_PREBUILT_UI=OFF']
    commands = [[cmake,'-S',str(source),'-B',str(binary),'-G','Ninja',*options],
        [cmake,'--build',str(binary),'--target','llama-server','ggml-rpc-server','is311-loader','-j','2']]
    for i, command in enumerate(commands):
        with (output/f'build-{i}.log').open('w') as log:
            subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,check=True,timeout=1200,preexec_fn=limits)
    compiler = subprocess.check_output(['c++','--version'],text=True).splitlines()[0]
    libs = tuple((str(p.relative_to(binary)),digest(p)) for p in sorted(binary.rglob('*.a')))
    patch = hashlib.sha256((HERE/'native.patch').read_bytes()+(HERE/'assigned.h').read_bytes()+Path(__file__).read_bytes()).hexdigest()
    result = dict(native_commit=PIN,archive_sha256=ARCHIVE_SHA,composite_sha256=composite,
                  patch_sha256=patch,compiler=compiler,build_options=options,commands=commands,roles={})
    for role,name in [('client','llama-server'),('remote','ggml-rpc-server')]:
        executable = binary/'bin'/name
        closure=libs if role=='client' else tuple(row for row in libs if row[0].startswith('ggml/'))
        manifest = build_manifest_body(executable_sha256=digest(executable),backend_libraries=closure,
            patch_sha256=patch,transformed_manifest_sha256=composite,compiler=compiler,options=options)
        path = output/(name+'.build-manifest.json'); path.write_text(json.dumps(manifest,indent=2)+'\n')
        result['roles'][role] = dict(executable=str(executable),manifest=str(path),identity=manifest)
    (output/'build.json').write_text(json.dumps(result,indent=2)+'\n')
    return result

if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive',required=True); parser.add_argument('--output',required=True)
    parser.add_argument('--cmake',default='cmake')
    args=parser.parse_args(); print(json.dumps(build(args.archive,args.output,args.cmake),indent=2))
