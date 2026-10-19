#!/usr/bin/env python3
"""CPU-only synthetic offline checker cost probe; never inference timing."""
import importlib.util, json, pathlib, struct, subprocess, tempfile, time
root=pathlib.Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('costchecker',root/'factorial_check.py');c=importlib.util.module_from_spec(spec);spec.loader.exec_module(c)
with tempfile.TemporaryDirectory() as tmp:
    so=pathlib.Path(tmp)/'math.so'
    subprocess.run(['c++','-O3','-std=c++17','-shared','-fPIC','-mf16c','-ffp-contract=off',str(root/'layer7_arithmetic.cpp'),'-o',str(so)],check=True)
    model=c.legacy.arithmetic.Arithmetic(so);d,f,t,hot=2560,640,4,10
    bank=struct.pack('<e32b',1/512,*([1]*32))*(26*f*d//32)
    mapping=[dict(token=token,branch='hot',original_slot=slot,branch_slot=slot,compact_expert=(token+slot)%26,global_expert=c.stages.RESIDENT10[(token+slot)%26]) for token in range(t) for slot in range(hot)]
    inputs=[.5]*(t*d);gate=[.5]*(t*hot*f);up=gate[:];swiglu=[.15561483800411224]*len(gate)
    results={}
    start=time.monotonic()
    for stage in ('gate','up','down'):
        at=time.monotonic();down=stage=='down';cols,rows=(f,d) if down else (d,f)
        c.mmvq.projection(model,bank,swiglu if down else inputs,[0.]*(t*hot*rows),mapping,cols,rows,t,down,hot,26)
        results['conditional_'+stage+'_seconds']=time.monotonic()-at
    for stage in ('gate','up'):
        at=time.monotonic();c.cpu_projection(model,bank,inputs,[0.]*(t*10*f),mapping,d,f,t,hot,arm='A');results['cpu_'+stage+'_seconds']=time.monotonic()-at
    at=time.monotonic();c.mmvq.swiglu(gate,up,swiglu,f,t,hot);results['conditional_swiglu_seconds']=time.monotonic()-at
    results.update(total_edge_seconds=time.monotonic()-start,dimensions=[d,f],tokens=t,selected_remote=hot,resident=26,bank_bytes=len(bank),scope='Measured offline checker edge cost on geekom with synthetic operands only; does not measure inference or complete replay I/O. Fullgrid estimate assumes coordinate-linear cost; actual operand variability and I/O remain additional.')
    results['calculated_coordinate_scaled_fullgrid_edge_seconds']=results['total_edge_seconds']*75
    results['calculated_160_times_largest_pair_edge_seconds']=results['total_edge_seconds']*160
    print(json.dumps(results,indent=2))
