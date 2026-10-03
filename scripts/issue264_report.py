#!/usr/bin/env python3
"""Pure report/reducer for retained Issue #264 pilot bytes."""
from __future__ import annotations
import json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import issue264_pilot as P
import issue264_h5 as H5

def build_report(root:Path)->dict:
 root=Path(root);arms={}
 for arm in P.ARMS:
  units=P.load_completed_units(root,arm)
  if units:
   arms[arm]={"classification":P.screen_class(units),"units":[{"unit_index":u["unit_index"],"row_digest":u["row_digest"],"response_sha256":u["response_sha256"],"server_log_sha256":u["server_log_sha256"],"markers":u["markers"]} for u in units]}
 if not arms:raise P.PilotError("no authenticated retained pilot units")
 transition=None
 if "BASE" in arms and "H5_MMV_CANDIDATE" in arms:
  transition=H5.candidate_transition(arms["BASE"]["units"][0]["markers"],arms["H5_MMV_CANDIDATE"]["units"][0]["markers"])
 return {"schema":"inferswarm.issue264.pilot-report/1","arms":arms,"control_difference":{"GGML_VK_I264_MMV":{"BASE":"base","H5_MMV_CANDIDATE":"large"}},"paired_path_transition":transition,"interpretation":"Row digests and responses are descriptive screening observations; no numerical causal inference or theorem closure is asserted.","theorem_gaps":["H2/H3 integration with the path-specific H5 contrast","causal attribution beyond screening variability","prospective hypothesis-class discrimination"]}
def main()->None:
 import argparse
 p=argparse.ArgumentParser(description=__doc__);p.add_argument("evidence_root",type=Path);p.add_argument("--output",type=Path);a=p.parse_args();data=json.dumps(build_report(a.evidence_root),sort_keys=True,indent=2)+"\n"
 if a.output:a.output.write_text(data)
 else:print(data,end="")
if __name__=="__main__":main()
