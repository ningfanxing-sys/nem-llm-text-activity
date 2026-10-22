'Select the frozen entry points for numerical evaluation and export.'
import ast
from contextlib import contextmanager, nullcontext
from copy import deepcopy
import importlib
import json
from pathlib import Path
import sys
from types import FunctionType, ModuleType, SimpleNamespace
from adapters import exclusive_json, export_values, rd_native_projection
from association import register
from source_bytes import checked, document, identity, require


def boundary_function(fn, **globals_delta):
    new = FunctionType(fn.__code__,dict(fn.__globals__,**globals_delta),fn.__name__,fn.__defaults__,fn.__closure__)
    new.__kwdefaults__ = fn.__kwdefaults__
    return new


def reader_modules(sources, project):

    root = Path(project)/'studies/confirmation'
    def module(relative, substitutions):
        path=root/relative;tree=ast.parse(sources.bytes(path));body=[];found=[]
        for n in tree.body:
            key=n.targets[0].id if isinstance(n,ast.Assign) and len(n.targets)==1 and isinstance(n.targets[0],ast.Name) else None
            if key in substitutions:
                require(isinstance(n.value,ast.Call) and n.value.func.id=='load_'+key.lower(), 'K2 reader constructor seam')
                found.append(key)
            else:body.append(n)
        require(found==list(substitutions),'K2 reader import census')
        m=ModuleType('_minrun_'+path.stem);m.__file__=str(path);m.__dict__.update(substitutions)
        exec(compile(ast.Module(body=body,type_ignores=[]),str(path),'exec',dont_inherit=True),vars(m))
        return m
    primary_tests=module('primary_tests/code/primary_comparisons.py',{});sensitivity_tests=module('sensitivity_tests/code/sensitivity_comparisons.py',{'primary_tests':primary_tests})
    robustness_tests=module('robustness_tests/code/robustness_comparisons.py',{'sensitivity_tests':sensitivity_tests})
    robustness_tests.primary_tests=primary_tests
    sys.path.insert(0,str(root/'code'))
    sc=sources.module('_minrun_scoring',root/'code/scoring.py')
    primary_tests.load_frozen_scoring=lambda *a,**kw:sc
    return primary_tests,sensitivity_tests,robustness_tests,sc,None


@contextmanager
def native_dependencies(P, sources, modules):
    old=P.dependencies;oldload=P.load_module
    primary_tests,sensitivity_tests,robustness_tests,sc,_=modules
    known={str(Path(m.__file__)):m for m in modules if m is not None}
    def dependencies(*args,**kwargs):
        pins=json.loads(sources.bytes(P.HERE/'DEPENDENCY_PINS.json'))
        for rel,digest in pins['files'].items():
            if rel.startswith('tables/'):continue
            path=P.PROJ/rel
            require(P.sha256(path)==digest,'K1 frozen numeric dependency drift: '+rel)
        robustness_tests.verify_a4_documents()
        return modules
    def load(name,path):return known.get(str(path)) or sources.module(name,path)
    P.dependencies,P.load_module=dependencies,load
    try:yield
    finally:P.dependencies,P.load_module=old,oldload


def ap_package(a, sources, entry_source):
    entry=sources.module('_minrun_ap_owner_entry',entry_source)
    return entry,entry.package(a)


def runtime_type(base):
    class Runtime(base):
        def load_scientific_inputs(self,path,digest,synthetic=False):


            from importlib import import_module
            loader=import_module(base.__module__.rsplit('.',1)[0]+'.scientific_inputs').load_scientific_inputs
            m,r=loader(self.P,self,path,digest,synthetic,author_validator=self.author_validator)
            self.verify_official_items(m['inputs'])
            snap=self.checked_payload(self.contract['cutoff_snapshot'])
            require(snap['source_values_decoded'] is False and snap['pending_is_negative'] is False
                and snap['clock_association']==self.association._official_ready['view_inputs']['execution']['clock'],
                'K3 original immutable capture binding')
            cs8=r['batch']['CS8']; require('score_receipt' in cs8,'K4 CS8 own R2 anchor required')
            require(self.checked_payload(cs8['score_receipt']).get('evaluation_view') == r['score_receipt']['evaluation_view'],
                    'K4 original optional anchor cannot replace R2')
            return m,r
    return Runtime


def publish_numeric(a, record, evidence, out, sens):
    out=Path(out);out.mkdir(parents=True,exist_ok=False)
    report={k:v for k,v in record.items() if k!='sens35_detached_losses'}
    source=register(a,exclusive_json(out/'SCORING_NUMERIC.json',report))
    ev=register(a,exclusive_json(out/'SCORING_NUMERIC_EVIDENCE.json',evidence))
    receipt=dict(schema='AP_SCORING_NUMERIC_OUTPUT_RECEIPT_V1',state='NUMERIC_OUTPUT_COMPLETE',
        synthetic_only=a.synthetic,production_authority=False,files=[source,ev])
    rec=register(a,exclusive_json(out/'SCORING_NUMERIC_RECEIPT.json',receipt))
    losses=sens.bind_replay_exports(record['sens35_detached_losses'],record,evidence,numeric_source=source,numeric_evidence=ev,numeric_receipt=rec)
    lossfiles={t:register(a,exclusive_json(out/(t+'__SENS35_LOSSES.json'),losses[t])) for t in losses}
    return dict(record=record,evidence=evidence,numeric_source=source,numeric_evidence=ev,numeric_receipt=rec,loss_exports=lossfiles)


def ap5_science(*, association, request, argv, scientific_scope, sources):
    a=association;require(argv==[] and request['score_views']==a._official_ready['view_inputs'],'K2 AP exact ABI')
    entry,name=ap_package(a,sources,a._control['ap']['entry_source'])
    bridge=importlib.import_module(name+'.numeric.bridge');sens=importlib.import_module(name+'.exporter.sensitivity_export')
    P=bridge.parent(a);R=runtime_type(bridge.Runtime);oldR=bridge.Runtime
    validator=entry.author_validation
    contract=request['function_kwargs']['scientific_contract'];runtime=R(a,contract,validator);runtime.P=P
    modules=reader_modules(sources,a._control['project'])
    oldassembly=P.assemble_output;oldbuild=P.build
    bridge.Runtime=R
    P.assemble_output=lambda *args,**kwargs:bridge.assemble(association=a,args=args,kwargs=kwargs,
         scientific_contract=contract,author_validator=validator)
    try:
        from comparison_parity import installed as representation_parity
        L=sources.module('frozen_losses',P.HERE/'code/frozen_losses.py')
        cs8=sources.module('replay_composite_losses',P.HERE/'code/replay_composite_losses.py')
        with representation_parity(P,L,cs8),native_dependencies(P,sources,modules),bridge.specified_scope(P,runtime) as producer:
            with scientific_scope(producer,contract['r2_source_contract']):
                from reference_gate import ap_boundary, capture_boundary
                L=sources.module('frozen_losses',P.HERE/'code/frozen_losses.py')
                with capture_boundary(L), ap_boundary(P,contract['output_directory']):
                    record,evidence=P.build(Path(contract['manifest']['path']),contract['manifest']['sha256'],
                        chunk=contract['chunk'],gate=P.resource_gate,synthetic=a.synthetic,production=not a.synthetic)
        runtime.reverify_official_views()
        return publish_numeric(a,record,evidence,contract['output_directory'],sens)
    finally:bridge.Runtime=oldR;P.assemble_output=oldassembly;P.build=oldbuild


def rd_joint(*, association, request, argv, scientific_scope, sources):
    a=association;require(argv==[] and request['score_views']==a._official_ready['view_inputs'],'K2 notice_delays exact ABI')
    owner=sources.module('_minrun_rd_owner_entry',a._control['rd']['entry_source']);owner._association(a)

    from native import compute, reader, deadline_specification, decision_metadata
    from evaluator import api
    data=request['function_kwargs'];manifest=document(data['manifest']);records=data['records']
    t5=data['t5_projection'];acceptance=document(data['af_acceptance'])
    require(deadline_specification.corrected_seal_precedes_t5(acceptance,t5,reader.checked,reader.require,
        lambda s:__import__('datetime').datetime.fromisoformat(s.replace('Z','+00:00'))),'K6 corrected seal verified before T5')
    decision_metadata.verify_decision(t5)
    import forecast_metadata
    from forecast_score_inputs import installed as scientific_association
    binding=document(data['minrun_am3_t4g'])
    require(binding['am3_freeze']==data['am3_freeze'], 'K6 same actual AM3 scientific freeze')
    with scientific_association(data['minrun_am3_t4g'],forecast_metadata):

        forecast_metadata.verify_combined(data['af_seal'],manifest['inputs']['seal'],data['batch_seal'],acceptance,t5)
    P=sources.module('read_comparisons',Path(a._control['project'])/'studies/inference/code/read_comparisons.py')
    modules=reader_modules(sources,a._control['project'])
    L=sources.module('frozen_losses',P.HERE/'code/frozen_losses.py');G=sources.module('parity_gate',P.HERE/'code/parity_gate.py')
    BS=sources.module('score_batch',reader.B/'code/score_batch.py')
    primary_tests,sensitivity_tests,robustness_tests,sc,_=modules
    M=SimpleNamespace(P=P,L=L,G=G,primary_tests=primary_tests,sensitivity_tests=sensitivity_tests,robustness_tests=robustness_tests,sc=sc,native=SimpleNamespace(**L.native_functions()),BS=BS)
    numeric=document(data['numeric_source']);evidence=document(data['numeric_evidence'])
    evidence=dict(evidence,frozen_2000_parity='PASS' if all(v['state']=='PASS' for v in evidence['loss_replay']['native_parity'].values()) else 'DEVIATION')
    require(evidence['frozen_2000_parity']=='PASS','K4 specified native parity incomplete')
    specified=dict(numeric,identities=dict(source_receipt_sha256=numeric['source_receipt_sha256']))
    with native_dependencies(P,sources,modules):
        kernel=compute.compute_notice(M,records,manifest,document(data['correction']),specified,evidence,gate=P.resource_gate)
        out=Path(data['output_directory']);out.mkdir(parents=True,exist_ok=False)
        nativeid=register(a,exclusive_json(out/'DELAY_FAMILIES.json',kernel))
        familyfiles={k:register(a,exclusive_json(out/('FAMILY_'+k.replace('/','_')+'.json'),v)) for k,v in kernel['families'].items()}
        authorities={k:{f:item[f] for f in ('path','sha256')} for k,item in familyfiles.items()}
        schema=document(data['schema']);bindings={k:{f:v[f] for f in ('path','sha256')} for k,v in data['bindings'].items()}
        joint=compute.joint_from_native(M,kernel['families'],authorities,bindings,alert=numeric['tasks']['notice']['alert'],schema=schema)
        jid=register(a,exclusive_json(out/'DELAY_JOINT_COMPARISONS.json',joint))
        seeds=[{'class':c['three_seed_class'],'effect_percent':c['three_seed_effect'],
            'timestamp_checks':dict(path=data['numeric_source']['path'],sha256=data['numeric_source']['sha256'],
                pointer='/tasks/notice/contrasts/'+str(i))} for i,c in enumerate(numeric['tasks']['notice']['contrasts'])]
        provenance=dict(synthetic_only=a.synthetic,bindings=bindings,native_rows={
            r['arm']+'/'+r['origin']+'/'+str(r['delay_minutes']):r['native_authority'] for c in joint['contrasts'] for r in c['readings']},
            specified_record=data['numeric_source'],specified_seed_rows=seeds,source_receipt_sha256=numeric['source_receipt_sha256'])
        projected=rd_native_projection(api,joint,numeric['tasks']['notice'],provenance,schema,a.project)
        pid=register(a,exclusive_json(out/'DELAY_SCALAR_PROJECTION.json',projected))
        receipt=register(a,exclusive_json(out/'DELAY_READING_RECEIPT.json',dict(schema='MINRUN_RD_RECEIPT_V1',
            files=[nativeid,jid,pid,*familyfiles.values()],bindings=bindings,proofs=kernel['proofs'],synthetic_only=a.synthetic)))
    return dict(record=projected,native=nativeid,joint=jid,source=pid,receipt=receipt)


def ap6_joint(*, association, request, argv, scientific_scope, sources):
    a=association;require(argv==[] and request['score_views']==a._official_ready['view_inputs'],'K2 AP6 exact ABI')
    _,name=ap_package(a,sources,a._control['ap']['entry_source'])
    projection=importlib.import_module(name+'.exporter.projection');formats=importlib.import_module(name+'.exporter.formats')
    args=request['function_kwargs']
    from verify_numeric_receipts import verify
    verified=verify(association=a,**args['verification'])
    require(verified==args['eligibility_result'],'K6 G42 independent repeat mismatch')
    return export_values(projection,formats,args['record'],args['rd'],args['projection_kwargs'],
        args['sens'],args['attachment'],args['output_directory'])
