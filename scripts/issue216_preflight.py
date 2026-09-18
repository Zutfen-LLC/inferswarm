#!/usr/bin/env python3
"""Issue #216 — fresh V2-D preflight raw collector.

Runs only on the approved host after the producer head is frozen. It captures
read-only host/discovery/topology inputs and emits a receipt bound to the
immutable V2-D authority plus its fresh mapping. It never starts a correctness
workload, transport benchmark, soak, fault arm, or reset.
"""
from __future__ import annotations
import argparse, hashlib, json, os, subprocess
from pathlib import Path
import issue216_physical_authority as pa


def sha(data: bytes) -> str: return hashlib.sha256(data).hexdigest()
def durable(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(data)
    fd=os.open(path, os.O_RDONLY); os.fsync(fd); os.close(fd)
    fd=os.open(path.parent, os.O_RDONLY); os.fsync(fd); os.close(fd)
def command(name: str, argv: list[str], out: Path) -> dict:
    try: p=subprocess.run(argv, capture_output=True, timeout=600)
    except subprocess.TimeoutExpired as e: p=None; stdout=e.stdout or b""; stderr=(e.stderr or b"")+b"\nTIMEOUT\n"; rc=124
    else: stdout,stderr,rc=p.stdout,p.stderr,p.returncode
    durable(out/f"{name}.stdout", stdout); durable(out/f"{name}.stderr", stderr)
    return {"name":name,"argv":argv,"exit_code":rc,"stdout_path":f"raw/{name}.stdout","stdout_sha256":sha(stdout),"stderr_path":f"raw/{name}.stderr","stderr_sha256":sha(stderr)}
def main()->int:
    ap=argparse.ArgumentParser(); ap.add_argument("--repo",required=True); ap.add_argument("--authority",required=True); ap.add_argument("--attempt-id",required=True); ap.add_argument("--out",required=True); args=ap.parse_args()
    repo=Path(args.repo); out=Path(args.out); out.mkdir(parents=True,exist_ok=False)
    authority=json.loads(Path(args.authority).read_text())
    if not pa.verify_authority(authority,repo): raise SystemExit("invalid physical authority")
    # Exact accepted discovery grammar produces and verifies the mapping receipt.
    mapping=pa.fresh_map(Path(args.authority),args.attempt_id,out,repo)
    raw=out/"raw"; raw.mkdir(exist_ok=True)
    probes=[command("boot-id",["cat","/proc/sys/kernel/random/boot_id"],raw),command("uname",["uname","-a"],raw),command("lspci-nn",["lspci","-nn"],raw),command("lspci-tree",["lspci","-t"],raw),command("lspci-vv",["lspci","-PP","-nn","-vv"],raw),command("journal-aer-amdgpu",["journalctl","-b","-k","--no-pager","-g","AER|amdgpu"],raw)]
    boot=(raw/"boot-id.stdout").read_text(errors="replace").strip()
    receipt={"schema":"inferswarm.v2d.preflight-receipt/1","campaign_id":pa.CAMPAIGN_ID,"attempt_id":args.attempt_id,"repo_head":subprocess.run(["git","-C",str(repo),"rev-parse","HEAD"],capture_output=True,text=True,check=True).stdout.strip(),"host":os.uname().nodename,"boot_id":boot,"authority_digest":authority["authority_digest"],"fresh_mapping_path":"FRESH-PHYSICAL-MAPPING.json","fresh_mapping_digest":sha((out/"FRESH-PHYSICAL-MAPPING.json").read_bytes()),"mapping_schema":mapping["schema"],"raw_probes":probes}
    durable(out/"receipt.json",json.dumps(receipt,indent=1,sort_keys=True).encode()+b"\n"); print(json.dumps({"attempt_id":args.attempt_id,"authority_digest":authority["authority_digest"]})); return 0
if __name__=="__main__": raise SystemExit(main())
