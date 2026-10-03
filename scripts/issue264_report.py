#!/usr/bin/env python3
"""Pure report/reducer for retained Issue #264 pilot bytes."""
from __future__ import annotations
import json,sys,math
from array import array
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import issue264_pilot as P
import issue264_h5 as H5
ACCEPTED_262_INVENTORY_SHA="806160f67aeff84d2b4d1531d65e582cd7e599cdf601aad877d70f83924f6038"

def preservation_status(context_sha:str)->dict:
 """Frozen expected inventory only; actual remote pre/post preservation is external."""
 path=P.IDENTITY_PATH.parent/"evidence/issue262/remote-inventory.tsv"
 raw=path.read_bytes()
 if P.sha(raw)!=ACCEPTED_262_INVENTORY_SHA:raise P.PilotError("accepted #262 remote inventory drift")
 lines=raw.decode("utf-8").splitlines()
 if len(lines)!=150 or len(set(line.split("\t",1)[0] for line in lines))!=150:raise P.PilotError("accepted #262 remote inventory population drift")
 return {"status":"external-pending","scope":"#262 retained 150-file inventory; controller preflight/postflight verification required","expected_file_count":150,"expected_inventory_sha256":ACCEPTED_262_INVENTORY_SHA,"pilot_context_sha256":context_sha}

def row_facts(raw:bytes)->dict:
 """Descriptive full-vocabulary float32 facts; never an acceptance metric."""
 if sys.byteorder!="little":raise P.PilotError("float32 row decoding requires little-endian host")
 vals=array("f");vals.frombytes(raw)
 finite=sum(math.isfinite(v) for v in vals)
 valid=[(v,i) for i,v in enumerate(vals) if math.isfinite(v)]
 best=max(valid,key=lambda item:item[0]) if valid else None
 return {"sha256":P.sha(raw),"finite_count":finite,"nonfinite_count":len(vals)-finite,"argmax_token":best[1] if best else None,"argmax_value":best[0] if best else None}

def compare_rows(a:dict,b:dict)->dict:
 if len(a["row_bytes"])!=len(b["row_bytes"]):raise P.PilotError("full-row comparison population differs")
 equal=[];argmax_equal=[];differences=[]
 for left,right in zip(a["row_bytes"],b["row_bytes"]):
  equal.append(left==right)
  lv=array("f");rv=array("f");lv.frombytes(left);rv.frombytes(right)
  if len(lv)!=len(rv):raise P.PilotError("full-row vocabulary widths differ")
  paired=[abs(x-y) for x,y in zip(lv,rv) if math.isfinite(x) and math.isfinite(y)]
  differences.append(max(paired) if paired else None)
  argmax_equal.append(row_facts(left)["argmax_token"]==row_facts(right)["argmax_token"])
 return {"base_unit":a["unit_index"],"other_unit":b["unit_index"],"equal_by_position":equal,"argmax_equal_by_position":argmax_equal,"max_abs_finite_difference_by_position":differences,"all_rows_equal":all(equal),"response_tokens_equal":json.loads(a["response_raw"])["tokens"]==json.loads(b["response_raw"])["tokens"]}

def build_report(root:Path)->dict:
 root=Path(root);context=P.load_execution_context(root);context_sha=P.sha(P.canonical(context));arms={}
 for arm in P.ARMS:
  units=P.load_completed_units(root,arm)
  if not units:
   raise P.PilotError(f"both complete legal arms are required; missing {arm}")
  if (len(units) not in (2,3) or [u.get("unit_index") for u in units]!=list(range(1,len(units)+1))
      or (len(units)==2)!=(units[0]["row_digest"]!=units[1]["row_digest"])):
   raise P.PilotError(f"{arm} is not a complete legal screening prefix")
  for u in units:
   if u.get("execution_context_sha256")!=context_sha or u.get("expected_head")!=context.get("expected_head"):
    raise P.PilotError("report units do not share the retained execution context")
  arms[arm]={"classification":P.screen_class(units),"units":[{"unit_index":u["unit_index"],"row_digest":u["row_digest"],"rows":[row_facts(raw) for raw in u["row_bytes"]],"response_sha256":u["response_sha256"],"response_raw":u["response_raw"].decode("utf-8"),"response":{"content":json.loads(u["response_raw"]).get("content"),"tokens":json.loads(u["response_raw"])["tokens"],"tokens_predicted":json.loads(u["response_raw"])["tokens_predicted"]},"observer_meta_sha256":u["observer_meta_sha256"],"server_log_sha256":u["server_log_sha256"],"placement":u["placement"],"markers":u["markers"]} for u in units]}
 transitions=[]
 for base in arms["BASE"]["units"]:
  for candidate in arms["H5_MMV_CANDIDATE"]["units"]:
   transitions.append(H5.candidate_transition(base["markers"],candidate["markers"]))
 if any(t!=transitions[0] for t in transitions[1:]):
  raise P.PilotError("paired dispatch transition differs across retained units")
 units={a:P.load_completed_units(root,a) for a in P.ARMS}
 comparisons={"within_arms":{a:[compare_rows(units[a][i],units[a][j]) for i in range(len(units[a])) for j in range(i+1,len(units[a]))] for a in P.ARMS},"across_arms":[compare_rows(b,c) for b in units["BASE"] for c in units["H5_MMV_CANDIDATE"]]}
 return {"schema":"inferswarm.issue264.pilot-report/1","execution_context_sha256":context_sha,"source_closure":context["source_closure"],"expected_head":context["expected_head"],"arms":arms,"row_comparisons":comparisons,"evidence_preservation":preservation_status(context_sha),"control_difference":{"GGML_VK_I264_MMV":{"BASE":"base","H5_MMV_CANDIDATE":"large"}},"paired_path_transition":transitions[0],"h5_discriminator":{"status":"path-transition-only","scope":"frozen output.weight MMV dispatch; not numerical causality or theorem closure"},"all_unit_pair_count":len(transitions),"interpretation":"Row digests, full-row descriptions, and raw responses are descriptive screening observations; no numerical causal inference or theorem closure is asserted.","theorem_gaps":["H2/H3 mechanisms remain open; not re-tested by the H5 MMV pilot","H5 numerical attribution beyond screening variability remains open","prospective H5 hypothesis-class discrimination remains open"]}
def main()->None:
 import argparse
 p=argparse.ArgumentParser(description=__doc__);p.add_argument("evidence_root",type=Path);p.add_argument("--output",type=Path);a=p.parse_args();data=json.dumps(build_report(a.evidence_root),sort_keys=True,indent=2)+"\n"
 if a.output:a.output.write_text(data)
 else:print(data,end="")
if __name__=="__main__":main()
