'Run the seven specified result calculation steps.'
from copy import deepcopy
from datetime import datetime, timezone
import importlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from adapters import exclusive_json, official_certificate, independent_eligibility
from source_bytes import checked, document, identity, require

now=lambda:datetime.now(timezone.utc).isoformat()


def declare_inputs(a,value):

    from association import identities
    for item in identities(value):a._reads[item['path']]=item


def complete_context(a,template,clock,capture,path):
    from association import register
    value=deepcopy(document(template));declare_inputs(a,value)
    value['fill_clock']['score_utc']=document(clock)['score_complete_utc']
    value['fill_clock']['filled_utc']=document(capture)['observed_utc']
    return register(a,exclusive_json(path,value))


def complete_rd_bindings(bindings,manifest,specified_receipt,main_reading,t5_projection):
    return dict(bindings,manifest=manifest,specified_receipt=specified_receipt,
                main_reading=main_reading,t5_projection=t5_projection)


class NativeAdapters:
    synthetic_only=False
    def __init__(self,control,sources):self.control,self.sources=control,sources;self.association_context=None
    def preflight(self):
        c=self.control
        require(self.sources is not None and 'original' in c,'K2 complete CONTROL inputs required')
        require(c['original']['argv']==['/usr/bin/caffeinate','-i',c['interpreter']['path'],c['original']['cli_source'],'score'],
                'K2 real original CLI argv')
        require(not Path(c['original']['receipt_path']).exists() and not (Path(c['original']['state_root'])/'scored').exists(),
                'K3 fresh original score destination; no original resume')
        require(c['r2']['state_root']!=c['original']['state_root'] and not Path(c['r2']['state_root']).exists(),'K3 fresh R2 state')
        self.load_definitions()
    def load_definitions(self):

        c=self.control
        for row in self.sources.rows.values():
            if row['logical_path'].endswith('.py'):compile(self.sources.bytes(row['logical_path']),row['logical_path'],'exec',dont_inherit=True)

        sys.path.insert(0,str(Path(c['capture']['source']).parent))
        self.capture_module=self.sources.module('cutoff_snapshot',c['capture']['source'])
        from scoring_entry import namespace
        namespace(c,self.sources)
        self.r2_module=self.sources.module('_minrun_r2',c['r2']['source'])
        self.branch=self.sources.module('_minrun_consumer_branch',c['r2']['consumer_source'])
        for key in ('entry_contract','scorer_contract'):document(c['c'][key])
        for item in (c['ap']['manifest_template'],c['rd']['request_template'],c['sensitivity_export']['permit'],c['sensitivity_export']['matching_contract']):document(item)
    def arm(self,out):
        self.armed=now()
        return dict(schema='MINRUN_ARM_V1',armed_utc=self.armed,release=self.control['release'],
            quiet_host=self.control['quiet_host'],original_argv=self.control['original']['argv'],synthetic_only=False)
    def score(self,out):
        from scoring_entry import invoke
        return invoke(self.control)
    def capture_after_exit(self,out,arm,finish):
        c=self.control;cfg=c['capture'];self.original_receipt=identity(c['original']['receipt_path'])
        clock=dict(state='POSTSCORE_CLOCK_ASSOCIATION_VERIFIED',source_verified=True,
            source_permission=c['release'],conf_score_receipt=self.original_receipt,score_complete_utc=finish,
            host_log=cfg['host_log'],turn_state=cfg['turn_state'],producer_outputs=cfg['producer_outputs'],initial_inputs=cfg['initial_inputs'])
        self.clock_id=exclusive_json(cfg['clock_path'],clock)
        result=self.capture_module.capture(cfg['clock_path'],cfg['snapshot_path'])
        self.capture_id=identity(cfg['snapshot_path']);return result
    def r2_after_capture(self,capture):
        from scoring_entry import fresh_r2
        self.r2_started=now();fresh_r2(self.control,self.sources);self.r2_completed=now()
        cfg=self.control['r2'];receipt=identity(cfg['receipt_path']);report=identity(cfg['report_path'])
        self.r2_receipt=receipt;return dict(score_receipt=receipt,score_report=report,
            started_utc=self.r2_started,completed_utc=self.r2_completed)
    def certificate(self,capture,r2):
        import association
        self.association_context=association.installed(self.control,self.sources)
        self.a=self.association_context.__enter__()
        original=dict(seal=identity(self.control['original']['seal_path']),score_receipt=self.original_receipt,
            score_report=identity(self.control['original']['report_path']))
        revised=dict(seal=original['seal'],score_receipt=r2['score_receipt'],score_report=r2['score_report'])
        execution=dict(capture=self.capture_id,clock=self.clock_id,armed_utc=self.armed,
            r2_started_utc=self.r2_started,r2_completed_utc=self.r2_completed,
            release=self.control['release'],quiet_host=self.control['quiet_host'])
        cert=official_certificate(self.a,original,revised,execution)
        self.certificate_id=association.register(self.a,exclusive_json(self.control['c']['certificate_path'],cert))
    def readers(self,order):
        from reader_dispatch import run
        self.reader_results=run(self.a,self.sources,order);return self.reader_results
    def request(self,kwargs):
        return dict(schema='C_SCORING_POSTSCORE_REQUEST_V1',score_views=self.a._official_ready['view_inputs'],function_kwargs=kwargs)
    def ap_numbers(self,readers):
        import score_news_full_window
        from native_entries import ap5_science
        from association import register
        self.original_science=score_news_full_window.produce(self.a,self.sources,self.control['ap']['score_news_full_window'])
        cfg=self.control['ap'];manifest=document(cfg['manifest_template']);manifest=deepcopy(manifest)
        declare_inputs(self.a,manifest['inputs'])
        manifest['inputs']['context']=complete_context(self.a,manifest['inputs']['context'],self.clock_id,self.capture_id,cfg['context_path'])
        view=self.a._official_ready['view_inputs']['r2'];manifest['inputs'].update(view)
        for key,role in (('a2','primary_tests'),('a3','sensitivity_tests'),('a4','robustness_tests'),('batch','batch-parity')):
            manifest['inputs'][key]=readers[role]['source']
        manifest['inputs'].update({k:v for k,v in readers['authorized-optional']['outputs'].items() if k!='dispositions'})
        mid=register(self.a,exclusive_json(cfg['manifest_path'],manifest))
        contract=deepcopy(document(cfg['scientific_contract']))
        declare_inputs(self.a,contract)
        contract.update(manifest=mid,original_attachment=self.original_science['source'],cutoff_snapshot=self.capture_id,
            output_directory=cfg['output_directory'],chunk=cfg['chunk'])
        self.ap_contract=contract
        self.ap=ap5_science(association=self.a,request=self.request(dict(scientific_contract=contract)),argv=[],
            scientific_scope=self.branch.scope,sources=self.sources)
        return self.ap['record']
    def rd_and_independent_eligibility(self,numeric):
        from native_entries import rd_joint
        from association import register
        import verify_numeric_receipts
        cfg=self.control['rd'];args=deepcopy(document(cfg['request_template']))
        declare_inputs(self.a,args)
        args['bindings']=complete_rd_bindings(args['bindings'],self.ap_contract['manifest'],self.r2_receipt,
                                             self.ap['numeric_source'],cfg['t5_projection'])
        manifest=document(self.ap_contract['manifest'])
        records={k:document(v) for k,v in manifest['inputs'].items()}
        args.update(manifest=self.ap_contract['manifest'],records=records,numeric_source=self.ap['numeric_source'],
            numeric_evidence=self.ap['numeric_evidence'],output_directory=cfg['output_directory'],
            t5_projection=document(cfg['t5_projection']))
        sys.path.insert(0,str(Path(cfg['entry_source']).parent))
        self.rd=rd_joint(association=self.a,request=self.request(args),argv=[],scientific_scope=self.branch.scope,sources=self.sources)
        inputs=dict(schema='MINRUN_G42_INPUTS_V1',joint_source=self.rd['joint'],native_source=self.rd['native'],
            schema_=args['schema'],bindings=args['bindings'],corrected_seal_verified_utc=document(args['af_acceptance'])['corrected_seal_verified_utc'])
        inputs['schema_identity']=inputs.pop('schema_')

        self.eligibility=register(self.a,exclusive_json(cfg['g42_input_path'],inputs))
        self.receipts=dict(original_score=self.original_receipt,r2_score=self.r2_receipt,capture_clock=self.clock_id,
            capture_snapshot=self.capture_id,a2=self.reader_results['primary_tests']['receipt'],a3=self.reader_results['sensitivity_tests']['receipt'],
            a4=self.reader_results['robustness_tests']['receipt'],batch=self.reader_results['batch-parity']['receipt'],
            numeric=self.ap['numeric_receipt'],score_news_full_window=self.original_science['receipt'],rd=self.rd['receipt'],
            af_acceptance=args['af_acceptance'],am3=args['am3_freeze'])
        self.verification=dict(eligibility=self.eligibility,numeric_source=self.ap['numeric_source'],rd_source=self.rd['source'],receipts=self.receipts)
        self.verified=independent_eligibility(verify_numeric_receipts.verify,self.a,**self.verification)
        register(self.a,exclusive_json(cfg['g42_output_path'],self.verified))
        return self.rd['record'],self.verified
    def sens35_from_detached_ap(self,numeric):
        from sensitivity_contracts import release_source_delivery
        return release_source_delivery(self.a,self.sources,self.ap,self.verified)
    def export(self,numeric,rd,eligibility,sens,attachment):
        from native_entries import ap6_joint, boundary_function, runtime_type, ap_package
        from association import register
        _,name=ap_package(self.a,self.sources,self.control['ap']['entry_source'])
        bridge=importlib.import_module(name+'.numeric.bridge');scalars=importlib.import_module(name+'.exporter.specified_scalars')
        runtime=runtime_type(bridge.Runtime)(self.a,self.ap_contract)

        from verify_numeric_receipts import verify
        def independent(*args,**kwargs):
            require(verify(association=self.a,**self.verification)==self.verified,'K6 independent export verification')
        runtime.verify_rd_eligibility=independent
        runtime.verify_specified_association=independent
        evaluator_module=importlib.import_module(name+'.exporter.delay_adapter')
        evaluator=evaluator_module.Evaluator(runtime)


        evaluator.check_sources_and_authority=runtime.check_sources_and_authority
        receipts=dict(original=self.original_receipt['sha256'],r2=self.r2_receipt['sha256'],specified_notice=self.r2_receipt['sha256'])
        qualify=boundary_function(scalars.evaluate_artificial,artificial_accept=lambda root:Path(root))
        qualifications=qualify(document(self.ap['numeric_source']),rd,numeric_source=self.ap['numeric_source'],
            rd_source=self.rd['source'],receipts=receipts,evaluator=evaluator,runtime=runtime,fixture_root=self.a.project)
        qid=register(self.a,exclusive_json(self.control['exporter']['qualification_path'],qualifications))
        kwargs=dict(qualifications=qualifications,qualification_source=qid,census=document(self.control['exporter']['census']),
            numeric_source=self.ap['numeric_source'],rd_source=self.rd['source'],original_source=self.original_science['source'],
            original_document=attachment,receipts=receipts)
        args=dict(record=numeric,rd=rd,projection_kwargs=kwargs,sens=sens,attachment=attachment,
            output_directory=self.control['exporter']['output_directory'],verification=self.verification,eligibility_result=eligibility)
        return ap6_joint(association=self.a,request=self.request(args),argv=[],scientific_scope=self.branch.scope,sources=self.sources)
    def close(self):
        if self.association_context is not None:self.association_context.__exit__(None,None,None);self.association_context=None
