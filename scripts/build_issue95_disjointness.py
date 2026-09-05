#!/usr/bin/env python3
"""Build issue #95 public prompt/token hash disjointness proof; CPU-only."""
import json
from pathlib import Path
from issue74_methodology import canonical_json_bytes

ROOT = Path(__file__).resolve().parents[1]
V4 = ROOT / 'docs/qualification/gemma4-12b-it-v4/manifests'


def cases(path: Path, key: str = 'cases'):
    return json.loads(path.read_text())[key]


def hashes(rows):
    return ({x['prompt_sha256'] for x in rows}, {x['token_ids_sha256'] for x in rows})


def main():
    v4 = {'c95-calibration':cases(V4/'calibration-corpus.json'), 'p95-stress':cases(V4/'stress-pool.json'), 'h95-holdout':cases(V4/'sealed-holdout-commitment.json', 'cells')}
    old = {
        'c74-calibration':cases(ROOT/'docs/qualification/gemma4-12b-it-v1/manifests/calibration-corpus.json'),
        'p74-stress':cases(ROOT/'docs/qualification/gemma4-12b-it-v1/manifests/margin-stress-pool.json'),
        'p76-stress':cases(ROOT/'docs/qualification/gemma4-12b-it-v2/manifests/margin-stress-pool.json'),
        'c86-calibration':cases(ROOT/'docs/qualification/gemma4-12b-it-v3/manifests/calibration-corpus.json'),
        'p86-stress':cases(ROOT/'docs/qualification/gemma4-12b-it-v3/manifests/stress-pool.json'),
        'h74-holdout':cases(ROOT/'docs/qualification/gemma4-12b-it-v1/manifests/sealed-holdout-commitment.json', 'cells'),
        'h86-holdout':cases(ROOT/'docs/qualification/gemma4-12b-it-v3/manifests/sealed-holdout-commitment.json', 'cells'),
    }
    rows=[]
    for new_name,new_cases in v4.items():
        np,nt=hashes(new_cases)
        for old_name,old_cases in old.items():
            op,ot=hashes(old_cases); row={'new_artifact':new_name,'prior_artifact':old_name,'prompt_sha256_overlap':len(np&op),'token_ids_sha256_overlap':len(nt&ot)}
            if row['prompt_sha256_overlap'] or row['token_ids_sha256_overlap']: raise SystemExit(f'OVERLAP {row}')
            rows.append(row)
    for left,right in [('c95-calibration','p95-stress'),('c95-calibration','h95-holdout'),('p95-stress','h95-holdout')]:
        lp,lt=hashes(v4[left]);rp,rt=hashes(v4[right]);
        if lp&rp or lt&rt: raise SystemExit(f'INTERNAL_OVERLAP {left} {right}')
    (V4/'disjointness-proof.json').write_bytes(canonical_json_bytes({'schema':'inferswarm.issue95.v4-disjointness-proof/1','method':'public prompt_sha256 and token_ids_sha256 set intersections','comparisons':rows,'verdict':'MECHANICALLY_DISJOINT'}))

if __name__ == '__main__': main()
