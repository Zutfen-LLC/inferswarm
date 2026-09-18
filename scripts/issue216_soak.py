#!/usr/bin/env python3
"""Issue #216 — V2-D 60-minute simultaneous-soak evidence producer.

The caller supplies the two already-frozen participant commands and a read-only
telemetry command. This collector records every PID, monotonic timestamp, raw
telemetry response, and periodic concurrent checkpoint. It never silently
restarts a worker; any exit is retained as an event and ends collection.
"""
from __future__ import annotations
import argparse, hashlib, json, os, shlex, subprocess, time
from pathlib import Path

def sha(b:bytes)->str:return hashlib.sha256(b).hexdigest()
def durable(p:Path,b:bytes)->None:p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b);fd=os.open(p,os.O_RDONLY);os.fsync(fd);os.close(fd);fd=os.open(p.parent,os.O_RDONLY);os.fsync(fd);os.close(fd)
def main()->int:
 ap=argparse.ArgumentParser();ap.add_argument("--participant-a",required=True);ap.add_argument("--participant-b",required=True);ap.add_argument("--telemetry",required=True);ap.add_argument("--checkpoint",required=True);ap.add_argument("--authority-digest",required=True);ap.add_argument("--fresh-mapping-digest",required=True);ap.add_argument("--attempt-id",required=True);ap.add_argument("--out",required=True);ap.add_argument("--duration",type=int,default=3600);ap.add_argument("--cadence",type=int,default=60);ap.add_argument("--tolerance",type=int,default=15);args=ap.parse_args()
 if args.duration<3600 or args.cadence!=60 or args.tolerance<0:raise SystemExit("frozen soak parameters rejected")
 out=Path(args.out);out.mkdir(parents=True,exist_ok=False);a=subprocess.Popen(shlex.split(args.participant_a));b=subprocess.Popen(shlex.split(args.participant_b));start=time.monotonic_ns();events=[];sample=0;next_checkpoint=0
 try:
  while (now:=time.monotonic_ns())-start < args.duration*1_000_000_000:
   sample+=1; p=subprocess.run(shlex.split(args.telemetry),capture_output=True,timeout=max(30,args.cadence));raw=f"telemetry-{sample:03d}.stdout";durable(out/raw,p.stdout);durable(out/f"telemetry-{sample:03d}.stderr",p.stderr);events.append({"schema":"inferswarm.v2d.soak-telemetry/1","campaign_id":"issue216-v2d-v340l-concurrent-dual-die-v1","attempt_id":args.attempt_id,"authority_digest":args.authority_digest,"fresh_mapping_digest":args.fresh_mapping_digest,"monotonic_ns":now,"pids":{"a":a.pid,"b":b.pid},"polls":{"a":a.poll(),"b":b.poll()},"stdout_path":raw,"stdout_sha256":sha(p.stdout),"stderr_sha256":sha(p.stderr)})
   if a.poll() is not None or b.poll() is not None:break
   elapsed=(now-start)//1_000_000_000
   if elapsed>=next_checkpoint:
    cp=subprocess.run(shlex.split(args.checkpoint),capture_output=True,timeout=1800);durable(out/f"checkpoint-{elapsed:04d}.stdout",cp.stdout);durable(out/f"checkpoint-{elapsed:04d}.stderr",cp.stderr);events.append({"schema":"inferswarm.v2d.soak-checkpoint/1","monotonic_ns":time.monotonic_ns(),"exit_code":cp.returncode,"stdout_sha256":sha(cp.stdout),"stderr_sha256":sha(cp.stderr)});next_checkpoint+=600
   target=now+args.cadence*1_000_000_000;time.sleep(max(0,(target-time.monotonic_ns())/1e9))
 finally:
  for p in (a,b):
   if p.poll() is None:p.terminate()
  for p in (a,b):
   try:p.wait(timeout=30)
   except subprocess.TimeoutExpired:p.kill()
 receipt={"schema":"inferswarm.v2d.soak-receipt/1","campaign_id":"issue216-v2d-v340l-concurrent-dual-die-v1","attempt_id":args.attempt_id,"authority_digest":args.authority_digest,"fresh_mapping_digest":args.fresh_mapping_digest,"started_monotonic_ns":start,"ended_monotonic_ns":time.monotonic_ns(),"telemetry_cadence_seconds":args.cadence,"allowed_scheduling_tolerance_seconds":args.tolerance,"events":events,"participant_final_exit":{"a":a.returncode,"b":b.returncode}}
 durable(out/"receipt.json",json.dumps(receipt,indent=1,sort_keys=True).encode()+b"\n");return 0
if __name__=="__main__":raise SystemExit(main())
