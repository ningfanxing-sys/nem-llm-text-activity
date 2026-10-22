'Map numerical input records to their checked source files.'
from copy import deepcopy
import ast
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
from ..input_checks import HERE, require, source_identity, checked_bytes, canonical
from .scientific_inputs import load_scientific_inputs


def installed(association):
    require(os.environ.get('SCORING_PHASE','prepare') in ('accept','source_runtime'),
            'Prepare: AP runtime cannot execute')
    mod=sys.modules.get(type(association).__module__)
    require(mod is not None and getattr(mod,'Association',None) is type(association)
            and getattr(mod,'ACTIVE',None) is association, 'Actual installed C association required')
    path=Path(mod.__file__).resolve()
    require(path.parts[-4:]==('batch_estimation','batch_checks','statistics','consumer_roots.py'), 'C source origin')
    association.verify_code(path)
    association.verify_t5_coverage()
    require(association._official_ready is not None,'Original capture and R2 completion required')
    association._check_official_score(association._official_ready)
    return association


class Runtime:
    def __init__(self,association,contract,author_validator=None):
        self.association=installed(association)
        require(contract.get('schema')=='AP_SCORING_SCIENTIFIC_EXECUTION_CONTRACT_V1','Scientific execution contract')
        self.contract=deepcopy(contract); self.author_validator=author_validator

        self.final_reviewed_contract=association._science_binding['entry_contracts']
        self.synthetic_only=association.synthetic
        self.r2_contract=deepcopy(contract['r2_source_contract'])

    def reverify_official_views(self):
        a=installed(self.association);a._check_official_score(a._official_ready)

    def check_sources_and_authority(self):
        a=installed(self.association);a._ap_runtime.revalidate()
        a.verify_code(__file__)

    def checked_source(self,path):
        a=self.association;self.check_sources_and_authority();path=Path(path)
        if a._ap_runtime.family(path) is not None:
            item=a._ap_runtime.member(path)
        else:
            a.verify_code(path)
            mod=sys.modules[type(a).__module__]
            rel=str(path.relative_to(mod.LIVE));item=dict(path=str(path),**a._effective_sources[rel]['identity'])
        with a._validation():data=path.read_bytes()
        require(len(data)==item['bytes'] and hashlib.sha256(data).hexdigest()==item['sha256'],'Exact checked source snapshot drift')
        a.verify_code(path)
        return data

    def checked_payload(self,item):
        self.reverify_official_views();path=Path(item['path'])
        expected=self.association._read_identity(path)
        require(expected is not None and item=={k:expected[k] for k in item},'Payload lacks independent C read timestamp_checks')
        require(source_identity(path)==dict(path=str(path),bytes=expected['bytes'],sha256=expected['sha256']), 'Payload bytes drift')
        def pairs(rows):
            result={}
            for k,v in rows:
                require(k not in result,'Duplicate payload key');result[k]=v
            return result
        value=json.loads(path.read_bytes(),object_pairs_hook=pairs,
                         parse_constant=lambda _:(_ for _ in ()).throw(ValueError('Nonfinite payload')))
        self.reverify_official_views();return value

    def verify_scientific_t5(self):
        self.check_sources_and_authority()
        self.association.verify_t5_coverage()

    def verify_official_items(self,items):
        self.reverify_official_views()
        expected=self.association._official_ready['view_inputs']['r2']
        for key in ('seal','score_receipt','score_report'):
            require(items[key]=={k:expected[key][k] for k in items[key]},'R2 input official identity drift: '+key)
        report=self.checked_payload(expected['score_report'])
        require(report.get('state')=='FROZEN_SCORE_COMPLETE' and report.get('seal_sha256')==expected['seal']['sha256'],'Official report completion/seal mismatch')

    def verify_manifest_location(self,path,root):
        p=Path(path); require(p.resolve()==p and p.is_relative_to(root),'Explicit artificial manifest location')
        require(source_identity(p)==self.contract['manifest'],'Exact manifest identity drift')

    def load_scientific_inputs(self,path,digest,synthetic=True):
        require(self.author_validator is not None,'Reviewed author entry required')
        self.reverify_official_views();self.verify_scientific_t5()
        m,r=load_scientific_inputs(self.P,self,path,digest,synthetic,author_validator=self.author_validator)
        self.verify_official_items(m['inputs'])
        marker=r['score_receipt']['evaluation_view']
        cs8=r['batch']['CS8']
        require('score_receipt' in cs8,'CS8 frozen score receipt required; no main-score substitution')
        receipt=self.checked_payload(cs8['score_receipt'])
        require(receipt.get('evaluation_view')==marker,
                'Old CS8 optional receipt/evaluation view refused')
        snap=self.checked_payload(self.contract['cutoff_snapshot'])
        require(snap.get('schema')=='A8POST5_CUTOFF_IDENTITIES_V1' and
                snap.get('state')=='OUTCOME_BLIND_IDENTITY_OBSERVATION' and
                snap.get('pending_is_negative') is False and snap.get('source_values_decoded') is False,
                'Genuine specified identity-only cutoff snapshot required')
        lateness=(self.P.utc(snap['observed_utc'])-self.P.utc(snap['cutoff_utc'])).total_seconds()
        require(lateness>=0 and snap['capture_lateness_seconds']==lateness and
                snap['exact_cutoff_observation'] is (lateness==0),
                'Specified cutoff observation/lateness mismatch')
        require(len({i['path'] for i in snap['files']})==len(snap['files']),
                'Cutoff duplicate file identity')
        guards=self.load_source(self.P.HERE/'table_inputs/code/postscore_guards.py','_ap_scientific_original_guards')
        actual=self.association._official_ready['view_inputs']['original']
        original=snap['official_score']
        require(set(original)=={'seal','score_receipt','score_report'},'Original capture official triplet census')
        for role,item in original.items():
            require({'path','sha256'}<=set(item)<={'path','sha256','bytes'} and
                    item=={k:actual[role][k] for k in item},'Original capture official identity drift: '+role)


        if snap.get('exact_cutoff_observation') is False:
            guards.validate_embedded_capture(snap,original,r['context']['fill_clock'],P=self.P)
        else:
            require('capture_authority' not in snap and 'capture_authority_kind' not in snap,
                    'Ambiguous timestamp_checks on exact cutoff observation')
            guards.validate_official_score(original,P=self.P,synthetic=synthetic)
            require(snap['official_score']==original and self.P.utc(snap['observed_utc'])==self.P.utc(snap['cutoff_utc']),'Exact capture identity/time drift')
            require(self.P.fill_cutoff(r['context']['fill_clock'],m.get('refill',False))==self.P.utc(snap['cutoff_utc']),'Refill cutoff drift')
            if 'clock_identity' in snap:
                capture=self.checked_payload(snap['clock_identity'])
                require(capture.get('schema')=='A8POST5_CUTOFF_CLOCK_V1' and capture.get('source_verified') is True
                        and capture.get('official_score')==original and capture.get('files')==snap['files'],
                        'Original exact capture clock/identity drift')
                checked=guards.cutoff_snapshot(capture,snap['observed_utc'],P=self.P)
                require(all(snap.get(k)==v for k,v in checked.items()),'Original exact capture regeneration drift')
                for key in ('score_utc','authorised_runs'):
                    require(key in capture['fill_clock'] and key in r['context']['fill_clock'] and
                            capture['fill_clock'][key]==r['context']['fill_clock'][key],
                            'Refill fixed cutoff input drift: '+key)
            for item in snap['files']:self.P.checked(item)
        self.reverify_official_views();return m,r

    def load_source(self,path,name):
        a=self.association
        with a._source_loading():
            data=self.checked_source(path);spec=importlib.util.spec_from_file_location(name,path)
            module=importlib.util.module_from_spec(spec);sys.modules[name]=module
            exec(compile(data,str(path),'exec',dont_inherit=True),vars(module))
        self.checked_source(path);return module

    def verified_original_attachment(self,record=None):
        require(set(self.contract['original_attachment'])=={'path','bytes','sha256'},
                'Original214 exact byte timestamp_checks required')
        value=self.checked_payload(self.contract['original_attachment'])
        original=self.association._official_ready['view_inputs']['original']
        require(value['source_receipt_sha256']==original['score_receipt']['sha256'] and value['days']==214,
                'Original214 independent receipt/domain drift')
        require(value['original_callable']==self.association._scorer_contract['original']['callable'] and
                value['original_destination']==self.association._scorer_contract['original']['receipt_path'],
                'Original callable/destination drift')
        require([(c['arm'],c['reference']) for c in value['contrasts']]==[('L_count','M'),('L_chen','M')]
                and {'RS8','N0'}<=set(value),'Original214 exact existing scientific fields required')
        if record is not None:
            require(record.get('original_news_214_source')==self.contract['original_attachment'],
                    'Original214 exported timestamp_checks descriptor drift')
            require(canonical(value)==canonical(record['original_news_214']),
                    'Original214 attachment document/value drift')
        self.reverify_official_views()
        return value

    def public_execution_provenance(self):
        self.reverify_official_views();return deepcopy(self.association._official_ready['view_inputs'])

    def verified_limitations(self):return self.checked_payload(self.contract['limitations'])
    def native_unavailable_series(self):return self.checked_payload(self.contract['native_unavailable_series'])

    def current_sens35_metadata(self):

        from ..exporter.sensitivity_export import days
        view=self.association._official_ready['view_inputs']['r2']
        receipt=self.checked_payload(view['score_receipt']);out={}
        for task in ('news','notice'):
            def item(name):
                rows=[x for x in receipt['files'] if Path(x['path']).name==name]
                require(len(rows)==1,'Missing/duplicate R2 native output: '+name);return rows[0]
            primary=self.checked_payload(item(task+'__PRIMARY.json'));panel=primary['panel_identity']
            daily=item(task+'__DAILY_LOSSES.csv')
            out[task]=dict(days=days(task),
                evaluation_view=deepcopy(receipt['evaluation_view']),
                daily_common_key_counts=deepcopy(panel['daily_common_key_counts']),
                common_keys_sha256=panel['common_keys_sha256'],
                sealed_prediction_manifest_sha256=panel['sealed_prediction_manifest_sha256'],
                r2_score_receipt_sha256=view['score_receipt']['sha256'],main_daily_csv_sha256=daily['sha256'])
        self.reverify_official_views();return out

    def verified_sens35_metadata(self,bundles,replay):
        out=self.current_sens35_metadata()
        for task in ('news','notice'):
            require(bundles[task+'/primary']['days']==out[task]['days'],'Replay/current task day drift')
            require(replay['daily_csv_proof'][task]['file']['sha256']==out[task]['main_daily_csv_sha256'],
                    'Replay/R2 main CSV drift')
        return out

    def verified_sens35_publication(self,exports,record,numeric_source):

        from ..exporter.sensitivity_export import value_sha256
        require(all(isinstance(exports[t].get('replay_binding'),dict) for t in ('news','notice')) and
                isinstance(record.get('sens35_replay_binding'),dict),'Missing actual replay binding')
        refs=[exports[t]['replay_binding'] for t in ('news','notice')]
        for task,ref in zip(('news','notice'),refs):
            require(ref.get('schema')=='AP_SCORING_SENS35_REPLAY_REFERENCE_V1' and
                    set(ref)=={'schema','numeric_source','numeric_evidence','numeric_receipt','pointer'} and
                    ref['numeric_source']==numeric_source and
                    ref['pointer']=='/sens35_replay_binding/tasks/'+task,'Detached numeric replay reference drift')
            for key in ('numeric_source','numeric_evidence','numeric_receipt'):
                require(set(ref[key])=={'path','bytes','sha256'},'Exact replay byte timestamp_checks required')
        require(all(refs[0][k]==refs[1][k] for k in ('numeric_source','numeric_evidence','numeric_receipt')),
                'Detached tasks came from different numeric replays')
        ref=refs[0];receipt=self.checked_payload(ref['numeric_receipt'])
        require(receipt.get('schema')=='AP_SCORING_NUMERIC_OUTPUT_RECEIPT_V1' and
                receipt.get('state')=='ARTIFICIAL_NUMERIC_OUTPUT_COMPLETE' and
                receipt.get('synthetic_only') is True and receipt.get('production_authority') is False,
                'Verified numeric replay receipt required')
        require(len(receipt['files'])==2 and receipt['files']==[numeric_source,ref['numeric_evidence']],
                'Numeric replay source/evidence not receipt-bound')
        evidence=self.checked_payload(ref['numeric_evidence'])
        require(evidence.get('schema')=='AP_SCORING_NATIVE_NUMERIC_EVIDENCE_V1' and
                evidence['execution_authority']==self.association._official_ready['view_inputs'],
                'Replay evidence/current official chain drift')
        commitment=record['sens35_replay_binding']
        require(commitment.get('schema')=='AP_SCORING_SENS35_REPLAY_BINDING_V1' and
                commitment['r2_score_receipt']==self.association._official_ready['view_inputs']['r2']['score_receipt'] and
                commitment['loss_replay_sha256']==value_sha256(evidence['loss_replay']) and
                commitment['execution_authority_sha256']==value_sha256(evidence['execution_authority']),
                'Verified actual replay/evidence commitment drift')
        metadata=self.current_sens35_metadata()
        self.reverify_official_views();return metadata

    def verify_specified_association(self,numeric_source,rd_source,receipts):
        association=self.contract['specified_association']
        require(association==dict(numeric_source=numeric_source,rd_source=rd_source,receipts=receipts),
                'C-reviewed request specified association drift')
        self.verify_rd_eligibility(rd_source,numeric_source,receipts)

    def verify_rd_eligibility(self,rd_source,numeric_source,receipts):


        a=self.association;self.reverify_official_views()
        pin=a._science_binding.get('g42_verifier_contract')
        require(pin is not None,'Pending independent C/G42 adopted source contract')
        descriptor=self.checked_payload(pin)
        require(descriptor.get('schema')=='C_SCORING_G42_VERIFIER_CONTRACT_V1' and
                descriptor.get('independent') is True,'Independent G42 contract schema')
        source=descriptor['source'];require(a._ap_runtime.family(source['path']) is None,'Producer cannot verify own eligibility')
        a.verify_code(source['path']);require(source_identity(source['path'])==source,'G42 verifier source drift')
        module=self.load_source(Path(source['path']),'_ap_independent_g42_verifier')
        verifier=getattr(module,descriptor['callable'])
        require(Path(verifier.__code__.co_filename).resolve()==Path(source['path']),'Foreign verifier callable')
        result=verifier(association=a,eligibility=self.contract['eligibility'],numeric_source=numeric_source,
                        rd_source=rd_source,receipts=receipts)
        require(isinstance(result,dict) and result.get('schema')=='C_SCORING_G42_VERIFIED_ASSOCIATION_V1'
                and result.get('numeric_source')==numeric_source and result.get('rd_source')==rd_source
                and result.get('receipts')==receipts and result.get('eligibility')==self.contract['eligibility'],
                'Missing/exact independent verifier result')
        a.verify_code(source['path']);self.reverify_official_views()
