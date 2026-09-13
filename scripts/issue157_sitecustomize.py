#!/usr/bin/env python3
"""Env-gated #157 instrumentation shim (staged as sitecustomize.py).

OFF BY DEFAULT: without ISSUE157_STAGE_INSTRUMENT=1 this module does
NOTHING (imports nothing from FreeToken, patches nothing), and ordinary
execution — including every accepted test path — is byte-identical to
the uninstrumented producer.

When ISSUE157_STAGE_INSTRUMENT=1 (set only by the #157 probe driver in
the stage-process env it builds), the shim installs the chunk-2
observer into the freshly started stage process BEFORE any FreeToken
module executes, so class-level patches land on the pristine classes.
The instrumentation directory and role label arrive via
ISSUE157_OUT_DIR / ISSUE157_STAGE_ROLE.
"""

import os
import sys

_ENABLED = os.environ.get("ISSUE157_STAGE_INSTRUMENT") == "1"

if _ENABLED:
    _out_dir = os.environ.get("ISSUE157_OUT_DIR")
    _role = os.environ.get("ISSUE157_STAGE_ROLE", "unknown")
    if not _out_dir:
        raise SystemExit(
            "ISSUE157_STAGE_INSTRUMENT=1 requires ISSUE157_OUT_DIR"
        )
    # Defer installation until freetoken/benchmarks classes exist: the
    # stage entry imports them AFTER sitecustomize runs.  Register an
    # import hook that fires the first time the stage runtime module is
    # imported.
    import importlib.abc
    import importlib.util

    _MARKER = "benchmarks.inferswarm_r6.stage_runtime"

    class _PostImportInstaller(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path=None, target=None):
            if fullname != _MARKER:
                return None
            # Let the normal machinery import it, then patch.
            spec = importlib.util.find_spec(fullname)
            loader = getattr(spec, "loader", None) if spec else None
            if spec is None or loader is None:
                return None
            orig_exec = loader.exec_module

            def exec_module(module):
                orig_exec(module)
                try:
                    sys.path.insert(
                        0, os.environ.get("ISSUE157_SCRIPTS_DIR", "")
                    )
                    import issue157_instrumentation

                    issue157_instrumentation.install(
                        os.environ["ISSUE157_OUT_DIR"],
                        os.environ.get("ISSUE157_STAGE_ROLE", "unknown"),
                    )
                except Exception as exc:  # never break the stage process
                    print(
                        f"[issue157] instrumentation install failed: {exc}",
                        file=sys.stderr,
                    )

            loader.exec_module = exec_module
            return spec

    sys.meta_path.insert(0, _PostImportInstaller())
