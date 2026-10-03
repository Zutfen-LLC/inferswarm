#!/usr/bin/env python3
"""Apply Issue 260's frozen, context-checked Vulkan instrumentation transform."""
import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

COMMIT = 'b29c606e28a01b1bc8c1351026a0fa6e616bf6c4'
TREE = '950999fe62b7fe55f44ab5b7394e3c8542f37f12'
PATCH_REL = 'docs/investigations/qwen38-flash-next-r8-i3c-vulkan-mechanism/patches/issue260-vulkan-instrumentation.patch'
IDENTITY_REL = 'docs/investigations/qwen38-flash-next-r8-i3c-vulkan-mechanism/issue260-source-identity.json'

def git(root, *args):
    return subprocess.run(['git', '-C', str(root), *args], text=True, capture_output=True)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--source', required=True, type=Path)
    ap.add_argument('--output', required=True, type=Path)
    ap.add_argument('--freeze', action='store_true', help='Create the identity once; otherwise verify it')
    args = ap.parse_args()
    source = args.source.resolve()
    head, tree = git(source, 'rev-parse', 'HEAD'), git(source, 'rev-parse', 'HEAD^{tree}')
    if head.returncode or head.stdout.strip() != COMMIT or tree.returncode or tree.stdout.strip() != TREE:
        sys.exit('source is not the exact pinned clean checkout (pinned commit/tree mismatch)')
    status = git(source, 'status', '--porcelain')
    if status.returncode or status.stdout.strip():
        sys.exit('pinned source must be clean')
    patch = Path(__file__).resolve().parents[1] / PATCH_REL
    if not patch.is_file():
        sys.exit(f'pinned instrumentation patch missing: {patch}')
    check = subprocess.run(['git', '-C', str(source), 'apply', '--check', str(patch)], text=True, capture_output=True)
    if check.returncode:
        sys.exit('pinned patch context check failed: ' + check.stderr.strip())
    if args.output.exists():
        sys.exit('output directory already exists')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    clone = subprocess.run(['git', 'clone', '--shared', '--no-checkout', str(source), str(args.output)], text=True, capture_output=True)
    if clone.returncode:
        sys.exit(clone.stderr.strip())
    checkout = subprocess.run(['git', '-C', str(args.output), 'checkout', '--detach', COMMIT], text=True, capture_output=True)
    if checkout.returncode:
        shutil.rmtree(args.output, ignore_errors=True)
        sys.exit(checkout.stderr.strip())
    applied = subprocess.run(['git', '-C', str(args.output), 'apply', str(patch)], text=True, capture_output=True)
    if applied.returncode:
        shutil.rmtree(args.output, ignore_errors=True)
        sys.exit(applied.stderr.strip())
    source_sha = hashlib.sha256((args.output / 'ggml/src/ggml-vulkan/ggml-vulkan.cpp').read_bytes()).hexdigest()
    patch_sha = hashlib.sha256(patch.read_bytes()).hexdigest()
    staged = subprocess.run(['git', '-C', str(args.output), 'add', '-A'], text=True, capture_output=True)
    tree_result = git(args.output, 'write-tree') if staged.returncode == 0 else staged
    if tree_result.returncode:
        sys.exit('cannot determine transformed tree: ' + tree_result.stderr.strip())
    identity = {
        'predecessor_commit': COMMIT,
        'predecessor_tree': TREE,
        'patch_sha256': patch_sha,
        'instrumented_tree': tree_result.stdout.strip(),
    }
    identity_path = Path(__file__).resolve().parents[1] / IDENTITY_REL
    if identity_path.exists():
        if args.freeze:
            sys.exit('instrumented source identity is already frozen')
        if json.loads(identity_path.read_text(encoding='utf-8')) != identity:
            sys.exit('instrumented source identity drift')
    elif args.freeze:
        identity_path.parent.mkdir(parents=True, exist_ok=True)
        with identity_path.open('x', encoding='utf-8') as stream:
            stream.write(json.dumps(identity, sort_keys=True, separators=(',', ':')) + '\n')
    else:
        sys.exit('source identity is not frozen; use --freeze exactly once')
    print(f'source_sha256={source_sha} patch_sha256={patch_sha} instrumented_tree={identity["instrumented_tree"]}')

if __name__ == '__main__':
    main()
