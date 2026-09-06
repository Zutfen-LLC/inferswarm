#!/usr/bin/env python3
"""Build issue #109 historical-exclusion and collision audit; CPU-only.

Predictive calibration and holdout draws are IID draws. Their realized prompt
or token identities can repeat. This tool proves historical exclusion and
records predictive collisions without rejecting or replacing a draw.
"""
import json
from pathlib import Path
from issue74_methodology import canonical_json_bytes

ROOT = Path(__file__).resolve().parents[1]
V5 = ROOT / 'docs/qualification/gemma4-12b-it-v5/manifests'


def cases(path: Path, key: str = 'cases'):
    return json.loads(path.read_text())[key]


def hashes(rows):
    return ({x['prompt_sha256'] for x in rows}, {x['token_ids_sha256'] for x in rows})


def collision_count(rows):
    prompts, tokens = hashes(rows)
    return {
        'draw_count': len(rows),
        'distinct_prompt_sha256_count': len(prompts),
        'distinct_token_ids_sha256_count': len(tokens),
        'repeated_prompt_draw_count': len(rows) - len(prompts),
        'repeated_token_ids_draw_count': len(rows) - len(tokens),
    }


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
    # The stress pool is non-predictive and deliberately distinct. Do not use
    # this convenience property to alter or reject predictive draws.
    for left, right in [('c109-calibration', 'p109-stress'), ('p109-stress', 'h109-holdout')]:
        lp, lt = hashes(v5[left])
        rp, rt = hashes(v5[right])
        if lp & rp or lt & rt:
            raise SystemExit(f'INTERNAL_OVERLAP {left} {right}')
    (V5 / 'disjointness-proof.json').write_bytes(canonical_json_bytes({
        'schema': 'inferswarm.issue109.v5-disjointness-proof/2',
        'method': 'fixed historical identity exclusion plus audit-only predictive collision counts',
        'historical_comparisons': rows,
        'predictive_collision_audit': {
            'calibration': collision_count(v5['c109-calibration']),
            'holdout': collision_count(v5['h109-holdout']),
            'calibration_holdout': {
                'prompt_sha256_overlap': len(hashes(v5['c109-calibration'])[0] & hashes(v5['h109-holdout'])[0]),
                'token_ids_sha256_overlap': len(hashes(v5['c109-calibration'])[1] & hashes(v5['h109-holdout'])[1]),
                'handling': 'RETAINED_IID_AUDIT_ONLY',
            },
        },
        'stress_distinctness_checked': True,
        'verdict': 'HISTORICAL_EXCLUSION_PASS_PREDICTIVE_COLLISIONS_RETAINED',
    }))


if __name__ == '__main__':
    main()
