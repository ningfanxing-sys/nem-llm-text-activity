
'Bind two verified timestamp tokens to the notice constraint record.'
import argparse
import datetime as dt
import importlib.util
from pathlib import Path
import subprocess
import sys
sys.dont_write_bytecode=True

spec=importlib.util.spec_from_file_location('_a8am3_local_freezer',Path(__file__).with_name('freeze_notice_constraints.py'))
F=importlib.util.module_from_spec(spec); spec.loader.exec_module(F)


def tsa_evidence(root,label):
    openssl='/opt/homebrew/bin/openssl'; evidence={}; times=[]
    man=root/label/('MANIFEST_'+label+'.sha256')
    for name in ('freetsa','digicert'):
        token=root/label/(label+'_'+name+'.tsr')
        certs=[root/'certs/freetsa_cacert.pem',root/'certs/freetsa_tsa.crt'] if name=='freetsa' else [root/'certs/macos_system_roots.pem']
        item=dict(token=F.identity(token),certificates=[F.identity(p) for p in certs])
        cmd=[openssl,'ts','-verify','-data',str(man),'-in',str(token),'-CAfile',str(certs[0])]
        if name=='freetsa': cmd += ['-untrusted',str(certs[1])]
        v=subprocess.run(cmd,capture_output=True,text=True,timeout=30)
        F.require(v.returncode==0 and 'Verification: OK' in v.stdout+v.stderr, 'TSA signature verification failed: '+name)
        v=subprocess.run([openssl,'ts','-reply','-in',str(token),'-text'],capture_output=True,text=True,timeout=30,check=True)
        rows=[l.split(':',1)[1].strip() for l in v.stdout.splitlines() if l.startswith('Time stamp:')]
        F.require(len(rows)==1, 'TSA timestamp missing/duplicate')
        stamp=dt.datetime.strptime(rows[0],'%b %d %H:%M:%S %Y GMT').replace(tzinfo=dt.timezone.utc)
        item['verified_utc']=stamp.isoformat(); times.append(stamp); evidence[name]=item
    return evidence,times


def record_binding(here=F.HERE, *, specification, af_code_freeze=None):
    here=Path(here).absolute();F.current_version(here,entry='bind_notice_constraints.py');F.require(specification.get('current_version')=='AM3DLE','INACTIVE specification cannot be bound'); q=here.parent.parent; root=q/'confirmation/TIMESTAMPS'
    man=root/F.LABEL/('MANIFEST_'+F.LABEL+'.sha256')
    headers,rows=F.manifest(man,F.LABEL,q)
    required=[F.identity(here/F.RECEIPT),*specification['files'],specification['author_attestation']]
    code=specification['af_code_freeze']
    if af_code_freeze:
        late=F.af_freeze(af_code_freeze,q,specification['af_sources'],specification['final_af_source_commitment'])
        F.require(code is None or code==late, 'Cannot replace bound AF code freeze'); code=late
    if code: required.append(code)
    final=specification['final_af_source_commitment']
    required += [*final['final_sources'],*final['final_consumer_files'],final['owner_interface_json'],final['owner_interface_md'],final['owner_final_source_commitment']]
    required += [v for v in specification['review8_inputs'].values() if 'TIMESTAMPS' not in Path(v['path']).parts]
    required += [v for v in specification['deadline_inputs'].values() if 'TIMESTAMPS' not in Path(v['path']).parts]
    required=list({v['path']:v for v in required}.values())
    for item in required:
        F.checked(item,Path(item['path']))
        rel=str(Path(item['path']).relative_to(q))
        F.require(rows.get(rel)==item, 'T4G missing/mismatched coverage: '+rel)
    evidence,times=tsa_evidence(root,F.LABEL)

    manifest_time=F.utc(headers['created_utc']); freeze_time=F.utc(specification['frozen_utc'])
    F.require(manifest_time>=freeze_time.replace(microsecond=0), 'T4G manifest predates AM3 freeze')
    F.require(all(t>=freeze_time and t>=manifest_time for t in times), 'T4G TSA predates AM3 freeze/manifest')
    return dict(schema='A8_SPECIFICATION_3_TIMESTAMP_BINDING_V1',state='A8_SPECIFICATION_3_T4G_BOUND',
        bound_utc=F.now(),timestamp_label=F.LABEL,specification=F.identity(here/F.RECEIPT),
        manifest=F.identity(man),coverage=required,tsa=evidence,af_code_freeze=code,
        chronology='Final AF source mapping, reviewed additive overlay source snapshots and owner source commitment -> AM3 REVIEW8 freeze -> after batch/DLY8-R8: real AF CODE_FREEZE and reviewed owner runtime overlay freeze -> both T4G TSAs covering AM3 and owner root union -> AM3 and owner bindings -> corrected combined +5/+15/+60 run/verified seal -> T5 -> scoring; no calendar deadline',
        outcome_access='none; metadata and timestamp tokens only')


def verify_binding(path,here=F.HERE,*,specification=None,require_af_freeze=False):
    here=Path(here).absolute(); F.require(Path(path).absolute()==here/'T4G_BINDING.json', 'Effective T4G binding path required')
    if specification is None: specification=F.verify(here/F.RECEIPT,here,here/'freeze_notice_constraints.py')
    frozen=F.strict(path)
    expected=record_binding(here,specification=specification,af_code_freeze=frozen['af_code_freeze']['path'] if frozen['af_code_freeze'] else None)
    F.require(set(frozen)==set(expected), 'T4G binding field set')
    for k in expected: F.require(k=='bound_utc' or frozen[k]==expected[k], 'T4G binding drift: '+k)
    stamp=F.utc(frozen['bound_utc'])
    F.require(max(F.utc(v['verified_utc']) for v in frozen['tsa'].values())<=stamp<=dt.datetime.now(dt.timezone.utc), 'Binding time chronology')
    F.require(not require_af_freeze or frozen['af_code_freeze'] is not None, 'Corrected execution/scoring requires bound AF CODE_FREEZE')
    return frozen


def create(here=F.HERE,af_code_freeze=None):
    F.resource_gate(); here=Path(here).absolute()
    specification=F.verify(here/F.RECEIPT,here,here/'freeze_notice_constraints.py')
    value=record_binding(here,specification=specification,af_code_freeze=af_code_freeze)
    F.exclusive_json(here/'T4G_BINDING.json',value)
    verify_binding(here/'T4G_BINDING.json',here,specification=specification)
    return value


def main():
    p=argparse.ArgumentParser(description=__doc__); m=p.add_mutually_exclusive_group(required=True)
    m.add_argument('--source-bind',action='store_true'); m.add_argument('--verify',type=Path)
    p.add_argument('--af-code-freeze',type=Path); p.add_argument('--require-af-freeze',action='store_true'); a=p.parse_args()
    F.resource_gate()
    if a.verify: verify_binding(a.verify,require_af_freeze=a.require_af_freeze); print('inference_design AM3 T4G BINDING VERIFIED')
    else:
        F.require(not a.require_af_freeze, '--require-af-freeze is a verifier option')
        create(af_code_freeze=a.af_code_freeze); print('inference_design AM3 T4G BOUND; no timestamp created')

if __name__=='__main__':
    try: main()
    except (ValueError,RuntimeError,OSError,KeyError,TypeError,subprocess.SubprocessError) as e:
        raise SystemExit('inference_design AM3 BINDING REFUSED: '+str(e))
