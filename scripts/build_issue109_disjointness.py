#!/usr/bin/env python3
"""Build issue #109 public prompt/token hash disjointness proof; CPU-only."""
import json
from pathlib import Path
from issue74_methodology import canonical_json_bytes

ROOT = Path(__file__).resolve().parents[1]
V5 = ROOT / 'docs/qualification/gemma4-12b-it-v5/manifests'


def cases(path: Path, key: str = 'cases'):
    return json.loads(path.read_text())[key]


def hashes(rows):
    return ({x['prompt_sha256'] for x in rows}, {x['token_ids_sha256'] for x in rows})


def main():
    v5 = {
        'c109-calibration': cases(V5 / 'calibration-corpus.json'),
        'p109-stress': cases(V5 / 'stress-pool.json'),
        'h109-holdout': cases(V5 / 'sealed-holdout-commitment.json', 'draws'),
    }
    old = {
        'c74-calibration': cases(ROOT / 'docs/qualification/gemma4-12b-it-v1/manifests/calibration-corpus.json'),
        'p74-stress': cases(ROOT / 'docs/qualification/gemma4-12b-it-v1/manifests/margin-stress-pool.json'),
        'h74-holdout': cases(ROOT / 'docs/qualification/gemma4-12b-it-v1/manifests/sealed-holdout-commitment.json', 'cells'),
        'p76-stress': cases(ROOT / 'docs/qualification/gemma4-12b-it-v2/manifests/margin-stress-pool.json'),
        'c86-calibration': cases(ROOT / 'docs/qualification/gemma4-12b-it-v3/manifests/calibration-corpus.json'),
        'p86-stress': cases(ROOT / 'docs/qualification/gemma4-12b-it-v3/manifests/stress-pool.json'),
        'h86-holdout': cases(ROOT / 'docs/qualification/gemma4-12b-it-v3/manifests/sealed-holdout-commitment.json', 'cells'),
        'c95-calibration': cases(ROOT / 'docs/qualification/gemma4-12b-it-v4/manifests/calibration-corpus.json'),
        'p95-stress': cases(ROOT / 'docs/qualification/gemma4-12b-it-v4/manifests/stress-pool.json'),
        'h95-holdout': cases(ROOT / 'docs/qualification/gemma4-12b-it-v4/manifests/sealed-holdout-commitment.json', 'cells'),
    }
    rows = []
    for new_name, new_cases in v5.items():
        np, nt = hashes(new_cases)
        for old_name, old_cases in old.items():
            op, ot = hashes(old_cases)
            row = {'new_artifact': new_name, 'prior_artifact': old_name,
                   'prompt_sha256_overlap': len(np & op), 'token_ids_sha256_overlap': len(nt & ot)}
            if row['prompt_sha256_overlap'] or row['token_ids_sha256_overlap']:
                raise SystemExit(f'OVERLAP {row}')
            rows.append(row)
    for left, right in [('c109-calibration', 'p109-stress'), ('c109-calibration', 'h109-holdout'),
                         ('p109-stress', 'h109-holdout')]:
        lp, lt = hashes(v5[left])
        rp, rt = hashes(v5[right])
        if lp & rp or lt & rt:
            raise SystemExit(f'INTERNAL_OVERLAP {left} {right}')
    (V5 / 'disjointness-proof.json').write_bytes(canonical_json_bytes({
        'schema': 'inferswarm.issue109.v5-disjointness-proof/1',
        'method': 'public prompt_sha256 and token_ids_sha256 set intersections',
        'comparisons': rows,
        'verdict': 'MECHANICALLY_DISJOINT',
    }))


if __name__ == '__main__':
    main()
