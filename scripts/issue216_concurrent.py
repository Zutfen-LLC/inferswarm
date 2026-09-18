#!/usr/bin/env python3
"""Issue #216 — authority-bound concurrent/baseline execution producer.

Only run after frozen review approval. Selectors, BDFs, runtime and model come
from the validated physical authority + fresh mapping receipt, never plan
literals. Pair proof uses correctness-bearing workload activity intervals, not
wrapper lifetimes alone.
"""
from __future__ import annotations
import argparse, hashlib, json, os, re, subprocess, sys, time
from pathlib import Path
import issue216_physical_authority as pa
PROMPT="The quick brown fox jumps over the lazy dog. Explain what happens next in one sentence:"
def sha(b:bytes)->str:return hashlib.sha256(b).hexdigest()
def durable(p:Path,b:bytes)->None:p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b);fd=os.open(p,os.O_RDONLY);os.fsync(fd);os.close(fd);fd=os.open(p.parent,os.O_RDONLY);os.fsync(fd);os.close(fd)
def load(authority_path:Path,mapping_path:Path,repo:Path,die:str)->tuple[dict,dict,dict]:
 a=json.loads(authority_path.read_text());m=json.loads(mapping_path.read_text())
 if not pa.verify_authority(a,repo) or m.get("authority_digest")!=a["authority_digest"] or die not in m.get("participants",{}):raise ValueError("invalid authority/mapping binding")
 return a,m,m["participants"][die]
def run(argv:list[str])->tuple[int,bytes,bytes,int,int]:
 start=time.monotonic_ns()
 try:p=subprocess.run(argv,capture_output=True,timeout=1800);rc,out,err=p.returncode,p.stdout,p.stderr
 except subprocess.TimeoutExpired as e:rc,out,err=124,e.stdout or b"",(e.stderr or b"")+b"\nTIMEOUT\n"
 return rc,out,err,start,time.monotonic_ns()
def participant(args:argparse.Namespace)->int:
 repo=Path(args.repo);a,m,resource=load(Path(args.authority),Path(args.mapping),repo,args.die);out=Path(args.out)/"participants"/args.die;out.mkdir(parents=True,exist_ok=True);rt=a["runtime"]
 ready=Path(args.gate+f".{args.die}.ready");durable(ready,b"ready\n");deadline=time.monotonic()+120
 while not Path(args.gate).exists() and time.monotonic()<deadline:time.sleep(.01)
 if not Path(args.gate).exists():raise RuntimeError("start gate absent")
 argv=[rt["executable"],"-m",rt["model"],"--temp","0","--seed","42","-n","8","-ngl","99","--device",resource["fresh_selector"],"-lv","4","-p",PROMPT,"-st"]
 rc,stdout,stderr,start,end=run(argv);durable(out/"stdout.txt",stdout);durable(out/"stderr.txt",stderr);durable(out/"exit-code.txt",f"{rc}\n".encode())
 sys.path.insert(0,str(repo/"scripts"));import v0c_correctness,v1c_accounting
 try:visible=v0c_correctness.extract_visible_response(stdout,PROMPT.encode());byte_exact=(repo/rt["reference_path"]).read_bytes().startswith(visible) and bool(visible)
 except Exception:visible=b"";byte_exact=False
 durable(out/"visible-output.txt",visible);text=stderr.decode(errors="replace");off=re.search(r"offloaded (\d+)/(\d+) layers",text);layers=[int(off.group(1)),int(off.group(2))] if off else None
 try:acct=v1c_accounting.parse_accounting(text,selector=resource["fresh_selector"]);clean=all(acct[k]==0 for k in ("unexplained_persistent_host_mirror_bytes","source_fetches_after_ready","unplanned_state_movements"))
 except Exception:acct={};clean=False
 # Activity interval is bounded by retained full workload execution, never the wrapper pre-gate lifetime.
 rec={"schema":"inferswarm.v2d.execution-attempt/1","campaign_id":pa.CAMPAIGN_ID,"attempt_id":args.attempt,"die":args.die,"authority_binding":{"authority_digest":a["authority_digest"],"fresh_mapping_digest":m["mapping_digest"],"selector":resource["fresh_selector"],"pci_bdf":resource["fresh_pci_bdf"],"compute_unit_id":resource["intended_identity"]["compute_unit_id"],"memory_resource_id":resource["intended_identity"]["memory_resource_id"]},"repo_head":subprocess.run(["git","-C",str(repo),"rev-parse","HEAD"],capture_output=True,text=True).stdout.strip(),"host":os.uname().nodename,"boot_id":Path("/proc/sys/kernel/random/boot_id").read_text().strip(),"runtime_binary_sha256":rt["executable_sha256"],"model_sha256":rt["model_sha256"],"argv":argv,"pid":os.getpid(),"workload_activity_interval_ns":[start,end],"exit_code":rc,"stdout_path":"stdout.txt","stdout_sha256":sha(stdout),"stderr_path":"stderr.txt","stderr_sha256":sha(stderr),"visible_output_path":"visible-output.txt","visible_output_sha256":sha(visible),"raw_correctness":rc==0 and byte_exact and layers is not None and layers[0]==layers[1] and layers[0]>0,"raw_accounting_clean":clean,"raw_no_fallback":"fallback" not in text.lower()}
 durable(out/"receipt.json",json.dumps(rec,indent=1,sort_keys=True).encode()+b"\n");return 0 if rec["raw_correctness"] and clean and rec["raw_no_fallback"] else 1
def pair(args:argparse.Namespace)->int:
 out=Path(args.out);out.mkdir(parents=True,exist_ok=False);gate=out/"start-gate";children=[]
 for die in ("a","b"):children.append(subprocess.Popen([sys.executable,__file__,"participant","--die",die,"--attempt",args.attempt,"--out",str(out),"--repo",args.repo,"--authority",args.authority,"--mapping",args.mapping,"--gate",str(gate)]))
 deadline=time.monotonic()+120
 while time.monotonic()<deadline and not all(Path(str(gate)+f".{d}.ready").is_file() for d in ("a","b")):time.sleep(.01)
 if not all(Path(str(gate)+f".{d}.ready").is_file() for d in ("a","b")):raise RuntimeError("participants not ready")
 durable(gate,b"open\n");rc=[p.wait(timeout=1900) for p in children];r={d:json.loads((out/"participants"/d/"receipt.json").read_text()) for d in ("a","b")};ai,bi=r["a"]["workload_activity_interval_ns"],r["b"]["workload_activity_interval_ns"];overlap=max(ai[0],bi[0])<min(ai[1],bi[1])
 summary={"schema":"inferswarm.v2d.concurrent-attempt/1","campaign_id":pa.CAMPAIGN_ID,"attempt_id":args.attempt,"authority_digest":r["a"]["authority_binding"]["authority_digest"],"fresh_mapping_digest":r["a"]["authority_binding"]["fresh_mapping_digest"],"participants":r,"workload_activity_overlap":overlap,"participants_distinct":r["a"]["authority_binding"]["pci_bdf"]!=r["b"]["authority_binding"]["pci_bdf"],"raw_correctness":all(x["raw_correctness"] for x in r.values()),"raw_accounting_clean":all(x["raw_accounting_clean"] for x in r.values()),"raw_no_fallback":all(x["raw_no_fallback"] for x in r.values()),"participant_exit_codes":dict(zip(("a","b"),rc))};durable(out/"receipt.json",json.dumps(summary,indent=1,sort_keys=True).encode()+b"\n");return 0 if rc == [0, 0] and overlap else 1
def main()->int:
 ap=argparse.ArgumentParser();sub=ap.add_subparsers(dest="cmd",required=True)
 for name in ("participant","pair"):
  p=sub.add_parser(name);p.add_argument("--attempt",required=True);p.add_argument("--out",required=True);p.add_argument("--repo",required=True);p.add_argument("--authority",required=True);p.add_argument("--mapping",required=True)
  if name=="participant":p.add_argument("--die",choices=("a","b"),required=True);p.add_argument("--gate",required=True)
 args=ap.parse_args();return participant(args) if args.cmd=="participant" else pair(args)
if __name__=="__main__":raise SystemExit(main())
