#!/usr/bin/env python3
"""Issue #264 bounded real BASE/H5-MMV pilot producer.

CPU-only until run_unit is explicitly invoked on a maintainer-prepared,
exact-head checkout with the completed binary identity record. This module
never accepts caller authority, identity, prompt, or observations.
"""
from __future__ import annotations
import hashlib, json, os, re, signal, subprocess, sys, time, urllib.request
from pathlib import Path
from typing import Any
sys.path.insert(0,str(Path(__file__).resolve().parent))
import issue250_diagnostic as D
import issue250_physical as B250
import issue252_constants as C252
import issue248_identity as I248
import issue264_h5 as H5
import issue262_h5 as H262

API="https://api.github.com/repos/Zutfen-LLC/inferswarm"
ISSUE=264
BASE_HEAD="7f666c99b043519e359610a90d4d06f8c34ea798"
SOURCE_TREE="23d38b96e371ad0634454d7bd6fe238da87eb1cb"
SOURCE_VK_SHA="551b6e7fd963fbf9cada48510df201cfa4bffa6a64bf4ea1d6d11d9e66999ebe"
BINARY_SHA="2734ba263fb2e0eb0154eaa75b15b07da54d679d8203d22e45eedee25b754330"
BUILD_SCHEMA="inferswarm.issue264.build-identity/1"
IDENTITY_PATH=Path(__file__).resolve().parents[1]/"docs/investigations/qwen38-flash-next-r8-i3c-vulkan-mechanism/issue264-source-identity-v2.json"
BUILD_IDENTITY=IDENTITY_PATH.with_name("issue264-build-identity.json")
PILOT_SCHEMA="inferswarm.issue264.pilot-unit/1"
ARMS={"BASE":{},"H5_MMV_CANDIDATE":{"GGML_VK_I264_MMV":"large"}}
ARM_ENV=ARMS
MAX_UNITS=3
class PilotError(RuntimeError): pass

def sha(data:bytes)->str:return hashlib.sha256(data).hexdigest()
def canonical(value:Any)->bytes:return json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()
def git(root:Path,*args:str)->str:
 p=subprocess.run(["git","-C",str(root),*args],capture_output=True,text=True)
 if p.returncode: raise PilotError(f"git {args[0]} failed: {p.stderr.strip()}")
 return p.stdout.strip()
def api(path:str)->Any:
 h={"Accept":"application/vnd.github+json","User-Agent":"inferswarm-issue264-pilot"}
 if os.environ.get("GH_TOKEN"):h["Authorization"]="Bearer "+os.environ["GH_TOKEN"]
 with urllib.request.urlopen(urllib.request.Request(f"{API}/{path}",headers=h),timeout=30) as r:return json.loads(r.read())
def verify_authority(root:Path)->dict:
 """Check immutable recorded #256 ancestor and live exact open stacked PR."""
 if not BUILD_IDENTITY.is_file():raise PilotError("completed issue264-build-identity.json absent; no execution")
 ident=json.loads(BUILD_IDENTITY.read_text())
 if ident.get("schema")!=BUILD_SCHEMA or ident.get("binary_sha256")!=BINARY_SHA:raise PilotError("build identity schema or externally supplied binary digest mismatch")
 expected=ident.get("execution_head")
 if not isinstance(expected,str) or not re.fullmatch(r"[0-9a-f]{40}",expected):raise PilotError("build identity lacks frozen execution_head")
 if git(root,"rev-parse","HEAD")!=expected:raise PilotError("local HEAD differs from frozen execution head")
 if git(root,"status","--porcelain","--untracked-files=all"):raise PilotError("repository worktree is dirty")
 if not git(root,"merge-base","--is-ancestor",BASE_HEAD,expected) == "":
  # git helper returns empty for success; failures raise.
  raise PilotError("accepted PR #256 ancestor not preserved")
 branch=git(root,"symbolic-ref","--short","HEAD")
 issue=api(f"issues/{ISSUE}")
 if issue.get("state")!="open":raise PilotError("issue #264 is not open")
 pulls=api("pulls?state=all&per_page=100")
 matches=[p for p in pulls if p.get("head",{}).get("ref")==branch and p.get("base",{}).get("ref")=="issue-254-r8i3c-producer"]
 if len(matches)!=1:raise PilotError("exact stacked PR is not uniquely identifiable")
 pr=matches[0]
 if pr.get("state")!="open" or pr.get("merged") or pr.get("draft") or pr.get("head",{}).get("sha")!=expected:raise PilotError("stacked PR is not open, non-draft, unmerged at frozen head")
 return {"issue":ISSUE,"pr":pr["number"],"head":expected}
def verify_source_and_binary(binary:Path)->str:
 ident=json.loads(IDENTITY_PATH.read_text())
 if ident.get("issue264_tree")!=SOURCE_TREE or ident.get("issue264_vk_sha256")!=SOURCE_VK_SHA:raise PilotError("gen2 source identity mismatch")
 if not BUILD_IDENTITY.is_file():raise PilotError("build identity absent; refusing binary")
 b=json.loads(BUILD_IDENTITY.read_text())
 required={"schema":BUILD_SCHEMA,"source_tree":SOURCE_TREE,"source_vk_sha256":SOURCE_VK_SHA,"binary_sha256":BINARY_SHA,"binary_path":"inferswarm01:/home/hermes/is264-mmv-v2/build-i264/bin/llama-server","version":"0.4.1-dev","build_number":10964,"predecessor_commit":"b29c606e28a01b1bc8c1351026a0fa6e616bf6c4","compiler":"GNU 14.2.0","gpu_applications_during_build":[]}
 if any(b.get(k)!=v for k,v in required.items()):raise PilotError("build identity does not match supplied gen2 build facts")
 expected=b.get("binary_sha256")
 if not isinstance(expected,str) or not re.fullmatch("[0-9a-f]{64}",expected):raise PilotError("build identity lacks real comparator SHA-256")
 if expected!=BINARY_SHA:raise PilotError("build identity binary digest mismatch")
 if not binary.is_file() or sha(binary.read_bytes())!=expected:raise PilotError("comparator bytes differ from completed build identity")
 return expected
def launch_env(arm:str,observer:Path)->dict[str,str]:
 if arm not in ARMS:raise PilotError("only BASE and H5_MMV_CANDIDATE are permitted")
 env={"PATH":"/usr/bin:/bin","HOME":"/home/hermes","LANG":"C.UTF-8","CUDA_VISIBLE_DEVICES":"-1","VK_ICD_FILENAMES":"/usr/share/vulkan/icd.d/nvidia_icd.json","GGML_VK_VISIBLE_DEVICES":"0","GGML_VK_MEMORY_LOGGER":"1","LLAMA_OBSERVE_CAPTURE":"8","LLAMA_OBSERVE_OUT":str(observer),"LLAMA_OBSERVE_FORCE":""}
 env["GGML_VK_I264_MMV"]="base" if arm=="BASE" else "large"
 return env
def launch_argv(binary:Path)->list[str]:
 member=next(iter(C252.MODEL_MEMBERS))
 return [str(binary),"--model",f"/srv/models/qwen38-ud-iq1-s/{member}","-ngl","1","--ctx-size","8192","--batch-size","512","--host","127.0.0.1","--port","19000","-v"]
def frozen_prompt(root:Path)->str:
 fixture=B250.verify_fixtures(root);entry=fixture.get(D.CASE) if isinstance(fixture,dict) else None
 prompt=entry.get("prompt_text") if isinstance(entry,dict) else None
 if not isinstance(prompt,str) or not prompt:raise PilotError("frozen case-3072 prompt unavailable")
 return prompt
def parse_unit_markers(raw:bytes,arm:str)->dict:
 try:text=raw.decode("utf-8")
 except UnicodeDecodeError as e:raise PilotError("server log not UTF-8") from e
 state="base" if arm=="BASE" else "large"
 try:return H5.parse_unit(text,state=state)
 except (ValueError,TypeError) as e:raise PilotError(f"invalid actual MMV dispatch: {e}") from e
def validate_pair(base:dict,candidate:dict)->dict:
 try:return H5.candidate_transition(base,candidate)
 except (ValueError,TypeError,KeyError) as e:raise PilotError(str(e)) from e
def observe_subject()->dict:
 p=subprocess.run(["nvidia-smi","--query-gpu=name,uuid,pci.bus_id,driver_version","--format=csv,noheader"],capture_output=True,text=True,timeout=20)
 if p.returncode:raise PilotError("nvidia-smi subject verification failed")
 wanted=C252.HOST_FACTS
 for line in p.stdout.splitlines():
  cells=[x.strip() for x in line.split(",")]
  if len(cells)==4 and cells[1]==wanted["gpu_uuid"] and cells[2].lower()==wanted["bdf"].lower():return {"gpu":cells[0],"gpu_uuid":cells[1],"bdf":cells[2],"driver":cells[3]}
 raise PilotError("frozen RTX 3060 UUID/BDF not present")
def _healthy(proc,timeout):
 import urllib.error
 end=time.monotonic()+timeout
 while time.monotonic()<end:
  if proc.poll() is not None:raise PilotError(f"server exited early rc={proc.returncode}")
  try:
   with urllib.request.urlopen("http://127.0.0.1:19000/health",timeout=2) as r:
    if r.status==200:return
  except (urllib.error.URLError,OSError):time.sleep(1)
 raise PilotError("server health timeout")
def _stop(proc):
 if proc.poll() is None:
  try:os.killpg(proc.pid,signal.SIGTERM)
  except ProcessLookupError:pass
  try:proc.wait(timeout=15)
  except subprocess.TimeoutExpired:os.killpg(proc.pid,signal.SIGKILL);proc.wait(timeout=5)
 if proc.poll() is None:raise PilotError("server process survived cleanup")
def run_unit(*,repo_root:Path,evidence_root:Path,arm:str,binary:Path,unit_index:int,timeout_s:float=900)->dict:
 """Run one actual unit; all authority and execution identity are internal."""
 if arm not in ARMS or unit_index not in (1,2,3):raise PilotError("invalid arm/unit")
 root=Path(repo_root);evidence=Path(evidence_root);verify_authority(root);binary_sha=verify_source_and_binary(Path(binary));subject=observe_subject()
 fixture=B250.verify_fixtures(root);prompt=frozen_prompt(root);request={**D.REQUEST_CONTRACT,"prompt":prompt};payload=canonical(request)
 pre=I248.observe_arm_identity("B");problems=I248.identity_problems("B",pre)
 if problems:raise PilotError(f"pre-launch identity drift: {problems}")
 target=evidence/arm/ f"unit-{unit_index:03d}";stage=evidence/arm/ f".unit-{unit_index:03d}.staging"
 if target.exists() or target.is_symlink() or stage.exists() or stage.is_symlink():raise PilotError("unit destination/staging already exists")
 completed=load_completed_units(evidence,arm)
 if len(completed)!=unit_index-1:raise PilotError("units must replay a contiguous legal prefix")
 if completed and completed[-1]["row_digest"]!=completed[0]["row_digest"] and unit_index>2:raise PilotError("repeat law forbids continuing after mismatch")
 if unit_index==3 and (len(completed)!=2 or completed[0]["row_digest"]!=completed[1]["row_digest"]):raise PilotError("unit 003 allowed only after two matching full-row digests")
 stage.mkdir(parents=True)
 env=launch_env(arm,stage/"obs");argv=launch_argv(Path(binary));log=stage/"server.log";proc=None
 try:
  with log.open("wb") as fp:
   child_env={k:v for k,v in os.environ.items() if not k.startswith("GGML_VK_") and k not in env};child_env.update(env)
   proc=subprocess.Popen(argv,env=child_env,stdout=fp,stderr=subprocess.STDOUT,start_new_session=True)
   _healthy(proc,timeout_s)
   actual=[x.decode("utf-8","surrogateescape") for x in Path(f"/proc/{proc.pid}/cmdline").read_bytes().rstrip(b"\0").split(b"\0")]
   if actual!=argv:raise PilotError("live argv mismatch")
   live=dict(x.split(b"=",1) for x in Path(f"/proc/{proc.pid}/environ").read_bytes().split(b"\0") if b"=" in x)
   for k,v in env.items():
    if live.get(k.encode())!=v.encode():raise PilotError(f"live environment mismatch {k}")
   req=urllib.request.Request("http://127.0.0.1:19000/completion",data=payload,headers={"Content-Type":"application/json"},method="POST")
   with urllib.request.urlopen(req,timeout=timeout_s) as response:
    if response.status!=200:raise PilotError("completion request failed")
    response_bytes=response.read(16*1024*1024)
   meta=(stage/"obs.meta.json").read_bytes();rows=[(stage/f"obs.row{i}.f32").read_bytes() for i in range(8)]
   post=I248.observe_arm_identity("B");problems=I248.identity_problems("B",post)
   if problems:raise PilotError(f"post-unit identity drift: {problems}")
 finally:
  if proc is not None:_stop(proc)
 server_log=log.read_bytes();markers=parse_unit_markers(server_log,ARMS[arm].get("GGML_VK_I264_MMV","base"))
 transition=None
 if arm=="H5_MMV_CANDIDATE":
  bases=load_completed_units(evidence,"BASE")
  if not bases:raise PilotError("candidate requires retained BASE unit from same exact identity")
  transition=validate_pair(bases[0]["markers"],markers)
 ended=time.strftime("%Y-%m-%dT%H:%M:%SZ",time.gmtime())
 record={"schema":PILOT_SCHEMA,"arm":arm,"unit_index":unit_index,"binary_sha256":binary_sha,"source_tree":SOURCE_TREE,"subject":subject,"argv":argv,"env":env,"request_sha256":sha(payload),"request_raw":payload,"response_sha256":sha(response_bytes),"response_raw":response_bytes,"server_log_sha256":sha(server_log),"server_log":server_log,"observer_meta_sha256":sha(meta),"observer_meta":meta,"row_sha256":[sha(x) for x in rows],"row_digest":sha(b"".join(rows)),"observer_rows":rows,"identity_pre":pre,"identity_post":post,"markers":markers,"transition":transition,"process_exit":{"returncode":proc.returncode,"cleanup_verified":True},"completed_at":ended,"fixture_sha256":sha(canonical(fixture))}
 publish_unit(stage,target,record);verify_authority(root)
 return {k:record[k] for k in ("arm","unit_index","row_digest","response_sha256","server_log_sha256","markers")}
def publish_unit(stage:Path,target:Path,r:dict)->None:
 files={"request.json":r["request_raw"],"response.json.raw":r["response_raw"],"server.log":r["server_log"],"obs.meta.json":r["observer_meta"],"identity-pre.json":canonical(r["identity_pre"]),"identity-post.json":canonical(r["identity_post"]),"markers.json":canonical(r["markers"]),"unit.json":canonical({k:v for k,v in r.items() if k not in {"request_raw","response_raw","server_log","observer_meta","observer_rows","identity_pre","identity_post","markers"}})+b"\n"}
 for i,data in enumerate(r["observer_rows"]):files[f"obs.row{i}.f32"]=data
 for name,data in files.items():
  with (stage/name).open("xb") as f:f.write(data);f.flush();os.fsync(f.fileno())
 hashmap={n:sha(b) for n,b in sorted(files.items())}
 with (stage/"files.sha256.json").open("xb") as f:f.write(canonical(hashmap)+b"\n");f.flush();os.fsync(f.fileno())
 os.rename(stage,target)
def load_completed_units(root:Path,arm:str)->list[dict]:
 if arm not in ARMS:raise PilotError("invalid arm")
 parent=Path(root)/arm
 if not parent.exists():return []
 if parent.is_symlink():raise PilotError("arm directory symlink refused")
 allowed={f"unit-{i:03d}" for i in range(1,4)}
 for p in parent.iterdir():
  if p.is_symlink() or p.name.endswith(".staging") or p.name not in allowed:raise PilotError("orphan, symlink or unexpected retained entry")
 out=[]
 for i in range(1,4):
  p=parent/f"unit-{i:03d}"
  if not p.exists():
   if any((parent/f"unit-{j:03d}").exists() for j in range(i+1,4)):raise PilotError("non-contiguous retained units")
   break
  if p.is_symlink() or not p.is_dir():raise PilotError("invalid unit path")
  hashes=json.loads((p/"files.sha256.json").read_text());expected={"request.json","response.json.raw","server.log","obs.meta.json","identity-pre.json","identity-post.json","markers.json","unit.json",*(f"obs.row{x}.f32" for x in range(8))}
  if set(hashes)!=expected or set(x.name for x in p.iterdir())!=expected|{"files.sha256.json"}:raise PilotError("retained file inventory mismatch")
  if any((p/n).is_symlink() for n in hashes):raise PilotError("retained file symlink refused")
  files={n:(p/n).read_bytes() for n in hashes}
  if any(sha(data)!=hashes[n] for n,data in files.items()):raise PilotError("retained byte hash mismatch")
  meta=json.loads(files["unit.json"])
  if sha(files["request.json"])!=meta.get("request_sha256") or sha(files["response.json.raw"])!=meta.get("response_sha256") or sha(files["server.log"])!=meta.get("server_log_sha256") or sha(files["obs.meta.json"])!=meta.get("observer_meta_sha256"):raise PilotError("retained request/response/log/meta digest mismatch")
  if meta.get("source_tree")!=SOURCE_TREE or meta.get("binary_sha256")!=BINARY_SHA:raise PilotError("retained source/binary identity mismatch")
  rows=[files[f"obs.row{x}.f32"] for x in range(8)]
  if len(rows)!=8 or sha(b"".join(rows))!=meta.get("row_digest") or [sha(x) for x in rows]!=meta.get("row_sha256"):raise PilotError("retained full-row digest mismatch")
  markers=json.loads(files["markers.json"]); log=files["server.log"]
  state="base" if arm=="BASE" else "large"
  if H5.parse_unit(log.decode("utf-8"),state=state)!=markers:raise PilotError("retained dispatch parse mismatch")
  if meta.get("schema")!=PILOT_SCHEMA or meta.get("arm")!=arm or meta.get("unit_index")!=i:raise PilotError("retained unit identity mismatch")
  exit_facts=meta.get("process_exit",{})
  if exit_facts.get("cleanup_verified") is not True or not isinstance(exit_facts.get("returncode"),int):raise PilotError("retained process cleanup fact missing")
  pre=json.loads(files["identity-pre.json"]);post=json.loads(files["identity-post.json"])
  if I248.identity_problems("B",pre) or I248.identity_problems("B",post):raise PilotError("retained identity snapshot is invalid")
  request=json.loads(files["request.json"]);fixture=B250.verify_fixtures(Path(__file__).resolve().parents[1]);entry=fixture.get(D.CASE,{})
  if request!={**D.REQUEST_CONTRACT,"prompt":entry.get("prompt_text")} or meta.get("fixture_sha256")!=sha(canonical(fixture)):raise PilotError("retained frozen fixture/request mismatch")
  if meta.get("argv")!=launch_argv(Path(meta.get("argv",[""])[0])) or meta.get("env")!=launch_env(arm,Path(meta.get("env",{}).get("LLAMA_OBSERVE_OUT",""))):raise PilotError("retained launch identity mismatch")
  out.append({**meta,"markers":markers,"row_digest":sha(b"".join(rows)),"response_sha256":sha(files["response.json.raw"]),"server_log_sha256":sha(log)})
 return out
def screen_class(units:list[dict])->str:
 if len(units)>=2 and units[0]["row_digest"]!=units[1]["row_digest"]:return "screening-variable"
 if len(units)==3 and len({u["row_digest"] for u in units})==1:return "screening-stable"
 return "matching-prefix" if units else "not-run"
def run_arm(*,repo_root:Path,evidence_root:Path,arm:str,binary:Path,timeout_s:float=900)->dict:
 """Execute/replay one complete arm under the fixed 2/3-unit screening law."""
 if arm not in ARMS:raise PilotError("only BASE and H5_MMV_CANDIDATE are permitted")
 evidence=Path(evidence_root)
 if arm=="H5_MMV_CANDIDATE":
  base=load_completed_units(evidence,"BASE")
  if screen_class(base) not in ("screening-variable","screening-stable"):raise PilotError("finish BASE screening prefix before candidate arm")
 units=load_completed_units(evidence,arm)
 if screen_class(units) in ("screening-variable","screening-stable"):return {"arm":arm,"units":len(units),"classification":screen_class(units)}
 while len(units)<MAX_UNITS:
  ix=len(units)+1
  run_unit(repo_root=repo_root,evidence_root=evidence,arm=arm,binary=binary,unit_index=ix,timeout_s=timeout_s)
  units=load_completed_units(evidence,arm)
  if len(units)>=2 and units[0]["row_digest"]!=units[1]["row_digest"]:break
  if len(units)==MAX_UNITS:break
 return {"arm":arm,"units":len(units),"classification":screen_class(units)}
def main()->None:
 import argparse
 p=argparse.ArgumentParser(description=__doc__);p.add_argument("--repo-root",type=Path,required=True);p.add_argument("--evidence-root",type=Path,required=True);p.add_argument("--binary",type=Path,required=True);p.add_argument("--arm",choices=ARMS,required=True);p.add_argument("--timeout",type=float,default=900);a=p.parse_args()
 print(json.dumps(run_arm(repo_root=a.repo_root,evidence_root=a.evidence_root,arm=a.arm,binary=a.binary,timeout_s=a.timeout),sort_keys=True))
if __name__=="__main__":main()
