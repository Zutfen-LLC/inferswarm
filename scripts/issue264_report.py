#!/usr/bin/env python3
"""Pure report/reducer for retained Issue #264 pilot bytes."""
from __future__ import annotations
import json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import issue264_pilot as P
import issue264_h5 as H5

def build_report(root:Path)->dict:
 root=Path(root);context=P.load_execution_context(root);context_sha=P.sha(P.canonical(context));arms={}
 for arm in P.ARMS:
  units=P.load_completed_units(root,arm)
  if not units:
   raise P.PilotError(f"both complete legal arms are required; missing {arm}")
  if len(units) not in (2,3) or P.screen_class(units) not in ("screening-variable","screening-stable"):
   raise P.PilotError(f"{arm} is not a complete legal screening prefix")
  for u in units:
   if u.get("execution_context_sha256")!=context_sha or u.get("expected_head")!=context.get("expected_head"):
    raise P.PilotError("report units do not share the retained execution context")
  arms[arm]={"classification":P.screen_class(units),"units":[{"unit_index":u["unit_index"],"row_digest":u["row_digest"],"response_sha256":u["response_sha256"],"response_raw":u["response_raw"].decode("utf-8","replace"),"observer_meta_sha256":u["observer_meta_sha256"],"server_log_sha256":u["server_log_sha256"],"markers":u["markers"]} for u in units]}
 transitions=[]
 for base in arms["BASE"]["units"]:
  for candidate in arms["H5_MMV_CANDIDATE"]["units"]:
   transitions.append(H5.candidate_transition(base["markers"],candidate["markers"]))
 if any(t!=transitions[0] for t in transitions[1:]):
  raise P.PilotError("paired dispatch transition differs across retained units")
 return {"schema":"inferswarm.issue264.pilot-report/1","execution_context_sha256":context_sha,"expected_head":context["expected_head"],"arms":arms,"control_difference":{"GGML_VK_I264_MMV":{"BASE":"base","H5_MMV_CANDIDATE":"large"}},"paired_path_transition":transitions[0],"all_unit_pair_count":len(transitions),"interpretation":"Row digests and raw responses are descriptive screening observations; no numerical causal inference or theorem closure is asserted.","theorem_gaps":["H2/H3 integration with the path-specific H5 contrast","causal attribution beyond screening variability","prospective hypothesis-class discrimination"]}
def main()->None:
 import argparse
 p=argparse.ArgumentParser(description=__doc__);p.add_argument("evidence_root",type=Path);p.add_argument("--output",type=Path);a=p.parse_args();data=json.dumps(build_report(a.evidence_root),sort_keys=True,indent=2)+"\n"
 if a.output:a.output.write_text(data)
 else:print(data,end="")
if __name__=="__main__":main()
