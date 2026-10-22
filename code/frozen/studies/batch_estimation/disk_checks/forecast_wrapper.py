"""Explicit host entry; inert import. Requires amendment freeze and T4C."""
import argparse,json,os,sys
from pathlib import Path
sys.dont_write_bytecode=True
from disk_overlay import *


def verify_release():
    verify_parent()
    frozen=json.loads((HERE/'DISK_FREEZE.json').read_text())
    if frozen['state']!='FROZEN_RESOURCE_ONLY_DISK_AMENDMENT': raise PermissionError('Invalid disk freeze')
    for rel,expected in frozen['files'].items():
        if ident(HERE/rel)!=expected: raise PermissionError('Disk supplement drift: '+rel)
    t4c=json.loads((HERE/'T4C_BINDING.json').read_text())
    expected=dict(batch=str(PARENT),state=str(HERE/'state'),dly8=str(HERE/'dly8'),cps8=str(HERE/'cps8'))
    if t4c.get('label')!='T4C' or t4c.get('roots')!=expected or t4c.get('supplement_freeze')!=dict(path=str(HERE/'DISK_FREEZE.json'),**ident(HERE/'DISK_FREEZE.json')):
        raise PermissionError('T4C roots/freeze drift')
    # Same coordinator cryptographic-verification attestation pattern as T4B.
    if t4c.get('state')!='T4C_VERIFIED' or t4c.get('coordinator_verified') is not True or not t4c.get('utc'):
        raise PermissionError('Verified, dated coordinator T4C attestation required')
    import datetime as dt
    parse=lambda value:dt.datetime.fromisoformat(value.replace('Z','+00:00'))
    if parse(t4c['utc']).utcoffset()!=dt.timedelta(0) or parse(t4c['utc'])<parse(frozen['utc']):
        raise PermissionError('T4C must be dated in UTC after supplement freeze')
    files={str(Path(i['path']).resolve()):i for i in t4c.get('files',[])}
    for p in (HERE/'DISK_FREEZE.json',HERE/'T4C_ROOTS.json',PARENT/'CODE_FREEZE.json'):
        expected=dict(path=str(p),**ident(p))
        if files.get(str(p))!=expected:raise PermissionError('T4C missing exact root/parent identity')
    for item in t4c['files']:
        if ident(item['path'])!={k:item[k] for k in ('bytes','sha256')}: raise PermissionError('T4C attested file drift')
    receipts=t4c.get('tsa_receipts',[])
    if len(receipts)<2:raise PermissionError('Two independently verified TSA receipts required')
    for item in receipts:
        if ident(item['path'])!={k:item[k] for k in ('bytes','sha256')}:raise PermissionError('T4C TSA receipt drift')
    return frozen


def dly_child_entry(dly,mode):
    """The real child entry; release verification remains in main before this."""
    return dly.host_mode(mode,dly.child_context())


def finish_sealed_entry(runner,dly):
    """Complete mode-1 evidence as well as the frozen mode-2/export recovery."""
    # The parent function obtains the reviewed context and exclusive state. Its
    # export callback installed by install_host verifies both family chains.
    return runner.finish_sealed()


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--execute',action='store_true');parser.add_argument('--plan-only',action='store_true')
    parser.add_argument('--finish-sealed',action='store_true');parser.add_argument('--workers',type=int,default=4)
    parser.add_argument('--dly-child',action='store_true');parser.add_argument('--child',action='store_true');parser.add_argument('--mode',type=int,choices=(1,2))
    args=parser.parse_args()
    resource_guard()
    sys.path.insert(0,str(PARENT/'code'))
    verify_release()
    runner,r8,dly=install_host()
    # These path-only aliases preserve original freeze/T4B identities; all writes
    # occur below the amendment. They are created only by explicit host execution.
    for name in ('CODE_FREEZE.json','T4B_BINDING.json'):
        target=HERE/name
        if not target.exists(): target.symlink_to(PARENT/name)
        elif target.resolve()!=(PARENT/name).resolve(): raise PermissionError('Parent alias drift')
    # Frozen host code requires nice >=10. Keep that stronger runtime condition.
    if os.getpriority(os.PRIO_PROCESS,0)<10: os.setpriority(os.PRIO_PROCESS,0,20)
    with dly_persistence(dly):
        if args.dly_child:
            if not args.child or not args.execute or args.mode is None: raise PermissionError('Explicit child dispatch required')
            dly_child_entry(dly,args.mode)
        elif args.plan_only: print(json.dumps(runner.plan_only(args.workers),indent=2))
        elif args.execute: runner.host_run(args.workers)
        elif args.finish_sealed: finish_sealed_entry(runner,dly)
        else: print('Verified only; coordinator later uses --plan-only or --execute.')

if __name__=='__main__': main()
