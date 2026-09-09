"""Pins for the retained producer-side sources (Issue #117 Arm B).

Every file under evidence/arm-b/raw/producer/ is a byte-exact copy of the
script that the historical campaign actually executed, retrieved read-only
from the fabric (participant copies where the participants ran them). The
pins below bind each copy; the reducer enforces them so the producer
semantics used in derivations cannot silently change.

FreeToken worktree files (stage_runtime.py, loader.py, r6_dense_census.py)
come from the frozen producer worktrees at 924cd22e on the participant
hosts (read via sudo cat; the worktrees are root-owned).
"""
from __future__ import annotations

#: sha256 pins of the retained producer sources (raw/producer/)
PRODUCER_SHA256 = {
    "armb_common.py":
        "2f344c118691d17deb714086260206f71c6f990bd1cbb5def86e5f0dd1297c3c",
    "armb_inventory.py":
        "bc6e43b61fbe2efe302f3347796af97d5f9c6495a17501902eabe839cf42326f",
    "armb_materialize.py":
        "b56d7a468e3b994faff1a8cc40962f1f01bebea067f559fbf0ba46a39912fdf6",
    "armb_node_acquire.py":
        "9d726c63888f985f44db349df3481c0ad0538c4fc20839343204e13b00478b9f",
    "armb_plan_core.py":
        "9c8360f4fb308b816e6abd6735bc592bfb67113b623e118c675b4d40cf8271bf",
    "armb_read_audit.py":
        "7abf0e3219c67a7ebef8ffe26952694af85950f4904a87a2539248a8a8dcc2bd",
    "armb_realize_child.inferswarm03.py":
        "1b7aef3aebae7023e22fd3d9e7b23d03402d5893c4760b495b782992c0c75ada",
    "armb_realize_child.py":
        "1b7aef3aebae7023e22fd3d9e7b23d03402d5893c4760b495b782992c0c75ada",
    "armb_source_server.py":
        "90fdec771e6a31df1a906bc61c4ececef736c172f8f9bb09fca72b1e8a1c71aa",
    "issue74_methodology.py":
        "e075c099c9f97c78fa9c138951772248291a62fa02a041dbb5d70b50d109e2ec",
    "issue99_artifact_core.py":
        "8b88af5b2f738c2a7428c9538cf76a14f889cb573a1722122951c45fc5965321",
    "loader.inferswarm03.py":
        "51d9ac30325ab3799f894fcc78f33c4e9c2d5048105081fe2d55921bc67cab5d",
    "loader.py":
        "51d9ac30325ab3799f894fcc78f33c4e9c2d5048105081fe2d55921bc67cab5d",
    "r6_dense_census.py":
        "7a305d09b124a0a942c150cc34dbcdd17c1c477da8abfe549b4efaaa250133d8",
    "stage_runtime.inferswarm03.py":
        "1cca03969a14d5b3d9b150a7972fa9bb2bee5a693073d603fb46e9af897f8737",
    "stage_runtime.py":
        "1cca03969a14d5b3d9b150a7972fa9bb2bee5a693073d603fb46e9af897f8737",
}

#: the tracing command the historical campaign used for realization
#: (verbatim from the retained armb_materialize.py source)
HISTORICAL_TRACING_COMMAND = (
    "strace -f -qq -e trace=file -o <out_dir>/realize-strace.log "
    "<child python> armb_realize_child.py --role … --model-path <out_dir> …")


def verify(raw_producer_dir) -> list:
    """Return a list of pin problems (empty == all pins hold)."""
    import hashlib
    problems = []
    for name, expected in PRODUCER_SHA256.items():
        try:
            data = open(f"{raw_producer_dir}/{name}", "rb").read()
        except OSError as exc:
            problems.append(f"producer source missing: {name} ({exc})")
            continue
        got = hashlib.sha256(data).hexdigest()
        if got != expected:
            problems.append(f"producer source digest drift: {name}")
    return problems
