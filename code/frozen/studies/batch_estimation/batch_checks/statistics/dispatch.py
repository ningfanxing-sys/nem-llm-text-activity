'Dispatch scoring after checking the requested inputs.'
import argparse
import os
from pathlib import Path
import sys
HERE=Path(__file__).absolute().parent

def _sources():
    import hashlib,json
    manifest=json.loads((HERE/'PUBLIC_RUNTIME_SOURCE_MANIFEST.json').read_bytes())
    if manifest.get('schema')!='C_SCORING_PUBLIC_SOURCE_MANIFEST_V1':raise PermissionError('Source manifest schema')
    for rel,pin in manifest['files'].items():
        p=HERE/rel
        if rel!=Path(rel).as_posix() or any(x.is_symlink() for x in (p,*p.parents)) or '..' in Path(rel).parts or Path(rel).is_absolute() or not p.is_file():raise PermissionError('Source alias/census')
        data=p.read_bytes()
        if len(data)!=pin['bytes'] or hashlib.sha256(data).hexdigest()!=pin['sha256']:raise PermissionError('C source drift before dispatch')
    spec=json.loads((HERE/'SCIENTIFIC_ACCEPTANCE_SPEC.json').read_bytes())
    if set(manifest['files'])!=set(spec['tested_source_files']):raise PermissionError('Source manifest missing/extra member')

def main(argv=None,*,forced_consumer=None):

    if os.environ.get('SCORING_PHASE','prepare')=='prepare':raise PermissionError('SCORING prepare: CLI cannot execute')
    _sources()
    parser=argparse.ArgumentParser()
    parser.add_argument('command',choices=['r2-score','postscore','bootstrap','arm','capture','r2-complete','optional-r2','scorer-metadata'])
    parser.add_argument('--project',required=True);parser.add_argument('--synthetic',action='store_true')
    parser.add_argument('--request',required=True);parser.add_argument('--request-bytes',type=int,required=True);parser.add_argument('--request-sha256',required=True)
    parser.add_argument('--request-provenance');parser.add_argument('--request-provenance-bytes',type=int);parser.add_argument('--request-provenance-sha256')
    parser.add_argument('--consumer');parser.add_argument('--destination')
    raw=list(sys.argv[1:] if argv is None else argv)
    split=raw.index('--') if '--' in raw else len(raw)
    ns=parser.parse_args(raw[:split]);ns.native_argv=raw[split+1:] if split<len(raw) else []
    from contract_io import _phase,_snapshot,_json,ContractError
    project=Path(ns.project);_phase(project,ns.synthetic)
    item=dict(path=ns.request,bytes=ns.request_bytes,sha256=ns.request_sha256)
    request=_json(_snapshot(item,project))
    import consumer_roots as C
    a=C.Association(project,synthetic=ns.synthetic)
    if ns.command=='bootstrap':
        from bootstrap import _propose
        return _propose(a,item,ns.destination)
    if ns.command=='scorer-metadata':


        from scorer_metadata import _proposal
        with a.installed(preparation=True,metadata_only=True):
            with a._source_loading():common=a._load_verified('batch_inputs')
            return _proposal(a,common,request['scorer_bindings'],request['test_provenance'],request['numerical_inputs'])
    with a.installed():
        a.authorize_ap_route('AP6' if ns.command=='postscore' and (forced_consumer or ns.consumer) in {'AP6','notice_delays'} else 'AP5')


        if not ns.request_provenance or ns.request_provenance_bytes is None or not ns.request_provenance_sha256:raise ContractError('Detached runtime request provenance required')
        from request_contract import _verify
        request=_verify(a,ns.command,item,dict(path=ns.request_provenance,bytes=ns.request_provenance_bytes,sha256=ns.request_provenance_sha256))
        if ns.command=='r2-score':
            from scorer_adapter import _run_r2
            return _run_r2(a,request)
        from dispatcher import _control,_postscore,_optional
        if ns.command in {'arm','capture','r2-complete'}:return _control(a,ns.command.replace('-','_'),request)
        if ns.command=='optional-r2':return _optional(a,request)
        if ns.command=='postscore':return _postscore(a,forced_consumer or ns.consumer,request,ns.native_argv[1:] if ns.native_argv[:1]==['--'] else ns.native_argv)
    raise ContractError('Unreachable dispatch')
if __name__=='__main__':main()
