#!/usr/bin/env python3
"""Deterministic builder for the issue #110 v5 threshold adapter.

Reads the accepted scripts/issue109_v5_thresholds.py (exact SHA-256 required),
performs exactly ONE semantic source transformation — replacing the historical
incomplete custody-record hash constant with the SHA-256 of the #110 effective
completed custody record — and emits scripts/issue110_v5_thresholds.py.

No other executable line may differ. The generated adapter is therefore the
accepted #109 threshold deriver with only the custody identity substitution:
N/H/M/alpha, comparator tiers, all-eight reducer logic, E_D logic,
stress-selection replay, threshold rule, telemetry semantics, and the holdout
commitment binding are byte-identical. CPU/static only; never reads private
material; never decrypts.
"""
from __future__ import annotations

import re
from pathlib import Path

from issue74_methodology import MethodologyError, sha256_file
from issue110_v5_custody import (
    ACCEPTED_THRESHOLDS_TOOL_SHA256,
    CAMPAIGN,
    effective_custody_record_sha256,
    load_accepted_baseline,
)

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "scripts/issue109_v5_thresholds.py"
ADAPTER = ROOT / "scripts/issue110_v5_thresholds.py"

HISTORICAL_CONSTANT = "6adaa4e5743cdee65f659806d81039dca499c7997cf0240ce92d48cfc2a23b46"
_CONSTANT_LINE_RE = re.compile(r'^V5_HOLDOUT_CUSTODY_RECORD_SHA256 = "[0-9a-f]{64}"$', re.MULTILINE)


def effective_custody_sha256_from_disk() -> str:
    import json
    completion = json.loads((CAMPAIGN / "holdout-custody-completion.json").read_text())
    record = json.loads((CAMPAIGN / "effective-holdout-custody-record.json").read_text())
    # Re-derive the record from the completion record and require the committed
    # effective record to be exactly the deterministic construction.
    from issue110_v5_custody import build_effective_custody_record
    if json.dumps(record, sort_keys=True) != json.dumps(build_effective_custody_record(completion), sort_keys=True):
        raise MethodologyError("110 effective custody record on disk is not the deterministic construction")
    return effective_custody_record_sha256(record)


def build_adapter_source(effective_custody_sha256: str, source: str | None = None) -> str:
    if source is None:
        source = SOURCE.read_text()
        if sha256_file(SOURCE) != ACCEPTED_THRESHOLDS_TOOL_SHA256:
            raise MethodologyError("110 accepted #109 thresholds tool hash drift")
    matches = _CONSTANT_LINE_RE.findall(source)
    if len(matches) != 1:
        raise MethodologyError("110 thresholds tool must contain exactly one custody-record hash constant")
    adapted = _CONSTANT_LINE_RE.sub(f'V5_HOLDOUT_CUSTODY_RECORD_SHA256 = "{effective_custody_sha256}"', source)
    if adapted == source:
        raise MethodologyError("110 adapter substitution did not change the source")
    # Prove the transformation is exactly one constant substitution.
    if sum(1 for a, b in zip(source.splitlines(), adapted.splitlines()) if a != b) != 1:
        raise MethodologyError("110 adapter must differ from #109 in exactly one line")
    return adapted


def write_adapter(path: Path | None = None) -> str:
    # Fail closed if the accepted baseline custody record has drifted.
    load_accepted_baseline()
    effective_sha = effective_custody_sha256_from_disk()
    out = path or ADAPTER
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build_adapter_source(effective_sha))
    return sha256_file(out)


def main() -> None:
    effective_sha = effective_custody_sha256_from_disk()
    adapter_sha = write_adapter()
    print(f"effective custody record sha256: {effective_sha}")
    print(f"#110 threshold adapter sha256:   {adapter_sha}")


if __name__ == "__main__":
    main()
