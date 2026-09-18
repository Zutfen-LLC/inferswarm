#!/usr/bin/env python3
"""Issue #216 — documented device-reset support/disposition producer.

This producer never invents or probes a reset mechanism. `inspect` records raw
host/kernel/device documentation evidence. `execute` is refused unless an
explicit reviewed mechanism command and documented-support receipt are present,
then retains before/after fresh discovery and recovery sentinel outputs.
"""
from __future__ import annotations
import argparse, hashlib, json, os, shlex, subprocess
from pathlib import Path

def sha(b:bytes)->str:return hashlib.sha256(b).hexdigest()
def durable(p:Path,b:bytes)->None:p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b);fd=os.open(p,os.O_RDONLY);os.fsync(fd);os.close(fd);fd=os.open(p.parent,os.O_RDONLY);os.fsync(fd);os.close(fd)
def capture(command:str,out:Path,label:str)->dict:
 p=subprocess.run(shlex.split(command),capture_output=True,timeout=1800);durable(out/f"{label}.stdout",p.stdout);durable(out/f"{label}.stderr",p.stderr);return {"argv":shlex.split(command),"exit_code":p.returncode,"stdout_sha256":sha(p.stdout),"stderr_sha256":sha(p.stderr)}
def main()->int:
 ap=argparse.ArgumentParser();sub=ap.add_subparsers(dest="cmd",required=True)
 i=sub.add_parser("inspect");i.add_argument("--documentation-command",required=True);i.add_argument("--authority-digest",required=True);i.add_argument("--fresh-mapping-digest",required=True);i.add_argument("--attempt-id",required=True);i.add_argument("--out",required=True)
 e=sub.add_parser("execute");e.add_argument("--support-receipt",required=True);e.add_argument("--mechanism-command",required=True);e.add_argument("--before-discovery",required=True);e.add_argument("--after-discovery",required=True);e.add_argument("--recovery-sentinel",required=True);e.add_argument("--out",required=True)
 args=ap.parse_args();out=Path(args.out);out.mkdir(parents=True,exist_ok=False)
 if args.cmd=="inspect":
  evidence=capture(args.documentation_command,out,"documented-support")
  result="SUPPORTED_MECHANISM_IDENTIFIED" if evidence["exit_code"]==0 else "DEVICE_RESET_ISOLATION_NOT_AVAILABLE"
  rec={"schema":"inferswarm.v2d.reset-disposition/1","campaign_id":"issue216-v2d-v340l-concurrent-dual-die-v1","attempt_id":args.attempt_id,"authority_digest":args.authority_digest,"fresh_mapping_digest":args.fresh_mapping_digest,"result":result,"documented_support_evidence":evidence}
 else:
  support=json.loads(Path(args.support_receipt).read_text())
  if support.get("result")!="SUPPORTED_MECHANISM_IDENTIFIED":raise SystemExit("reset execute refused without documented supported mechanism")
  rec={"schema":"inferswarm.v2d.reset-disposition/1","campaign_id":support["campaign_id"],"attempt_id":support["attempt_id"],"authority_digest":support["authority_digest"],"fresh_mapping_digest":support["fresh_mapping_digest"],"result":"RESET_EXECUTED","documented_support_receipt":args.support_receipt,"before_discovery":capture(args.before_discovery,out,"before-discovery"),"mechanism":capture(args.mechanism_command,out,"mechanism"),"after_discovery":capture(args.after_discovery,out,"after-discovery"),"recovery_sentinel":capture(args.recovery_sentinel,out,"recovery-sentinel")}
 durable(out/"receipt.json",json.dumps(rec,indent=1,sort_keys=True).encode()+b"\n");return 0
if __name__=="__main__":raise SystemExit(main())
