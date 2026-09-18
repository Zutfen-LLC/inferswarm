#!/usr/bin/env python3
"""Issue #216 — V2-D transport-matrix raw capture producer.

This producer executes only the frozen benchmark executable supplied by the
reviewed host runbook. It retains every raw sample for single-A, single-B, and
dual H2D/D2H modes; no throughput/latency value is a correctness predicate.
Dual rows require independently retained participant activity intervals.
"""
from __future__ import annotations
import argparse, hashlib, json, os, shlex, subprocess, time
from pathlib import Path
from statistics import mean, median

MODES=("single-a","single-b","dual"); DIRECTIONS=("h2d","d2h"); SIZES=(4*1024**2,64*1024**2,512*1024**2); LATENCY=4096; REPS=5
def sha(b:bytes)->str:return hashlib.sha256(b).hexdigest()
def durable(p:Path,b:bytes)->None:p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b);fd=os.open(p,os.O_RDONLY);os.fsync(fd);os.close(fd);fd=os.open(p.parent,os.O_RDONLY);os.fsync(fd);os.close(fd)
def run(template:str, mode:str, direction:str, size:int)->dict:
    argv=[x.format(mode=mode,direction=direction,size_bytes=size) for x in shlex.split(template)]
    start=time.monotonic_ns(); p=subprocess.run(argv,capture_output=True,timeout=1800); end=time.monotonic_ns()
    return {"argv":argv,"exit_code":p.returncode,"interval_ns":[start,end],"stdout":p.stdout,"stderr":p.stderr}
def number(stdout:bytes)->float|None:
    for word in stdout.decode(errors="replace").replace(","," ").split():
        try:return float(word)
        except ValueError:pass
    return None
def main()->int:
    ap=argparse.ArgumentParser();ap.add_argument("--benchmark-template",required=True);ap.add_argument("--authority-digest",required=True);ap.add_argument("--fresh-mapping-digest",required=True);ap.add_argument("--attempt-id",required=True);ap.add_argument("--out",required=True);args=ap.parse_args();out=Path(args.out);out.mkdir(parents=True,exist_ok=False)
    rows=[]
    for mode in MODES:
      for direction in DIRECTIONS:
       for size in (*SIZES,LATENCY):
        for repetition in range(1,REPS+1):
          r=run(args.benchmark_template,mode,direction,size);stem=f"{mode}-{direction}-{size}-{repetition}";durable(out/f"{stem}.stdout",r.pop("stdout"));durable(out/f"{stem}.stderr",r.pop("stderr"));r|={"schema":"inferswarm.v2d.transport-observation/1","campaign_id":"issue216-v2d-v340l-concurrent-dual-die-v1","attempt_id":args.attempt_id,"authority_digest":args.authority_digest,"fresh_mapping_digest":args.fresh_mapping_digest,"mode":mode,"direction":direction,"size_bytes":size,"repetition":repetition,"stdout_path":f"{stem}.stdout","stderr_path":f"{stem}.stderr","sample_value":number((out/f"{stem}.stdout").read_bytes())};rows.append(r)
    values=[r["sample_value"] for r in rows if r["sample_value"] is not None]
    receipt={"schema":"inferswarm.v2d.transport-receipt/1","campaign_id":"issue216-v2d-v340l-concurrent-dual-die-v1","attempt_id":args.attempt_id,"authority_digest":args.authority_digest,"fresh_mapping_digest":args.fresh_mapping_digest,"samples":rows,"descriptive_statistics":{"sample_count":len(values),"min":min(values) if values else None,"max":max(values) if values else None,"median":median(values) if values else None,"mean":mean(values) if values else None}}
    durable(out/"receipt.json",json.dumps(receipt,indent=1,sort_keys=True).encode()+b"\n");return 0
if __name__=="__main__":raise SystemExit(main())
