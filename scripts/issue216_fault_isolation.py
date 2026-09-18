#!/usr/bin/env python3
"""Issue #216 — symmetric process-level fault-isolation receipt producer.

The frozen arm kills only the named participant PID. It retains pre-loss health,
survivor liveness and post-loss correctness command output, relaunch evidence,
per-die sentinels, and a final concurrent sentinel. Device reset is expressly
outside this producer.
"""
from __future__ import annotations
import argparse, hashlib, json, os, shlex, signal, subprocess, time
from pathlib import Path

def sha(b:bytes)->str:return hashlib.sha256(b).hexdigest()
def durable(p:Path,b:bytes)->None:p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b);fd=os.open(p,os.O_RDONLY);os.fsync(fd);os.close(fd);fd=os.open(p.parent,os.O_RDONLY);os.fsync(fd);os.close(fd)
def invoke(label:str,command:str,out:Path)->dict:
 p=subprocess.run(shlex.split(command),capture_output=True,timeout=1800);durable(out/f"{label}.stdout",p.stdout);durable(out/f"{label}.stderr",p.stderr);return {"label":label,"argv":shlex.split(command),"exit_code":p.returncode,"stdout_sha256":sha(p.stdout),"stderr_sha256":sha(p.stderr)}
def main()->int:
 ap=argparse.ArgumentParser();ap.add_argument("--arm",choices=("a-loss-b-survives","b-loss-a-survives"),required=True);ap.add_argument("--target-pid",type=int,required=True);ap.add_argument("--survivor-pid",type=int,required=True);ap.add_argument("--pre-health",required=True);ap.add_argument("--survivor-work",required=True);ap.add_argument("--relaunch",required=True);ap.add_argument("--per-die-sentinels",required=True);ap.add_argument("--final-concurrent",required=True);ap.add_argument("--authority-digest",required=True);ap.add_argument("--fresh-mapping-digest",required=True);ap.add_argument("--attempt-id",required=True);ap.add_argument("--out",required=True);args=ap.parse_args();out=Path(args.out);out.mkdir(parents=True,exist_ok=False)
 pre=invoke("pre-health",args.pre_health,out); before={"target_alive":os.path.exists(f"/proc/{args.target_pid}"),"survivor_alive":os.path.exists(f"/proc/{args.survivor_pid}")};os.kill(args.target_pid,signal.SIGTERM);deadline=time.monotonic()+30
 while os.path.exists(f"/proc/{args.target_pid}") and time.monotonic()<deadline:time.sleep(.1)
 escalated=False
 if os.path.exists(f"/proc/{args.target_pid}"):os.kill(args.target_pid,signal.SIGKILL);escalated=True
 survivor=invoke("survivor-post-loss",args.survivor_work,out);relaunch=invoke("relaunch",args.relaunch,out);sentinels=invoke("per-die-sentinels",args.per_die_sentinels,out);final=invoke("final-concurrent",args.final_concurrent,out)
 receipt={"schema":"inferswarm.v2d.fault-isolation/1","campaign_id":"issue216-v2d-v340l-concurrent-dual-die-v1","attempt_id":args.attempt_id,"arm":args.arm,"authority_digest":args.authority_digest,"fresh_mapping_digest":args.fresh_mapping_digest,"target_pid":args.target_pid,"survivor_pid":args.survivor_pid,"pre_health":pre,"before":before,"termination":{"sigterm_sent":True,"sigkill_after_30_second_grace":escalated,"target_alive_after":os.path.exists(f"/proc/{args.target_pid}")},"survivor_post_loss":survivor,"relaunch":relaunch,"per_die_sentinels":sentinels,"final_concurrent_sentinel":final}
 durable(out/"receipt.json",json.dumps(receipt,indent=1,sort_keys=True).encode()+b"\n");return 0
if __name__=="__main__":raise SystemExit(main())
