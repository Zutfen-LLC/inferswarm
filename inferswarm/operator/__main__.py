"""Ordinary fixed-topology operator entrypoint."""
import argparse
import json
import sys
from .runtime import run_config


def main(argv=None):
    parser=argparse.ArgumentParser(prog='python -m inferswarm.operator')
    commands=parser.add_subparsers(dest='command',required=True)
    run=commands.add_parser('run',help='one verified fixed-plan generation')
    run.add_argument('--config',required=True,help='strict operator-config/2 JSON')
    experiment=commands.add_parser('experimental-q8-two-cuda',
        help='one explicitly authorized, unqualified #313 systemd-supervised diagnostic')
    experiment.add_argument('--config',required=True,help='strict profiled operator config JSON')
    experiment.add_argument('--envelope',required=True,help='strict q8-two-cuda-experiment/1 JSON')
    experiment.add_argument('--evidence-root',required=False,help=(
        'absolute controller-local directory for durable raw-evidence retention; '
        'must not already exist (default: fresh token directory under '
        '~/.local/share/inferswarm)'))
    args=parser.parse_args(argv)
    try:
        if args.command=='run': result=run_config(args.config)
        else:
            from .q8_experiment import run_experimental_campaign
            result=run_experimental_campaign(args.config,args.envelope,
                evidence_root=args.evidence_root)
        print(json.dumps(result,sort_keys=True))
        return 0
    except Exception as exc:
        error={'error':str(exc),'type':type(exc).__name__}
        if hasattr(exc,'campaign_receipt'): error['campaign']=exc.campaign_receipt
        print(json.dumps(error,sort_keys=True),file=sys.stderr)
        return 1

if __name__=='__main__': raise SystemExit(main())
