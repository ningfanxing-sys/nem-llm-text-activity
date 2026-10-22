"""Separate serial base/extension PCX turns through the current REPIN8 launch.py."""
from a8_common import *
import argparse
import subprocess

def commands(phase,attestation,python=str(PROJ.parents[1]/'.venv/bin/python')):
    launch=CONF/'A4/PCX/REPIN_CONFX8/launch.py'
    suffix=['--seal-attestation',attestation['path'],'--seal-attestation-sha256',attestation['sha256']]
    if phase=='base':
        rows=[['build','--task',s] for s in ('news','notice')]
        rows += [['fit','--task','news','--tier',t,'--workers','2'] for t in ('N1','N2')]
        rows += [['fit','--task','notice'],['fit','--task','news','--tier','CAP','--workers','2'],['score'],['bind-base']]
    else:
        require(phase=='extension','Unknown PCX turn')
        rows=[['prepare-extension'],['fit','--phase','extension','--task','news','--tier','N2','--workers','2'],
              ['fit','--phase','extension','--task','notice'],['score','--phase','extension'],['publish']]
    return [[python,'-B',str(launch),'pcx_runner.py',*r,*suffix] for r in rows]

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--execute',action='store_true');parser.add_argument('--phase',choices=['base','extension'],required=True)
    args=parser.parse_args();require(args.execute and os.environ.get('A8BATCH_HOST_RUN')=='1','Separate host authorization required')
    require(os.getpriority(os.PRIO_PROCESS,0)>=10,'Production nice 10 required')
    from a8_freeze import verify,validate_t5_binding
    code=verify();validate_t5_binding(code,OUT/'state')
    binding=read_json(checked(code['bindings']))
    from repin_plan import validate_effective
    validate_effective(binding)
    sys.path.insert(0,str(Q/'REPIN8'))
    from launcher import assert_idle
    from overlap import clear_control_environment
    clear_control_environment();assert_idle()
    seal=read_json(OUT/'PCX_SEAL_ASSOCIATION.json');checked(seal['seal_attestation'])
    # Every child still verifies immutable freeze, T5 and original host gates.
    for argv in commands(args.phase,seal['seal_attestation']):subprocess.run(argv,check=True)

if __name__=='__main__':main()
