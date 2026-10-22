'Validate the metadata required by numerical scoring.'
from pathlib import Path
import copy
import datetime as dt
import hashlib
import json
import re

FREEZE_SCHEMA = 'C_SCORING_SCIENTIFIC_FREEZE_V1'
FREEZE_STATE = 'SCIENTIFIC_CONSUMER_FROZEN_BEFORE_T5'
TASK_REVISION = 'SCORING_C8B_SCIENCE_V1'


def _utc(c, value):
    c.require(isinstance(value,str),'Aware UTC identity required')
    result=dt.datetime.fromisoformat(value.replace('Z','+00:00'))
    c.require(result.utcoffset()==dt.timedelta(0),'UTC offset must be zero')
    return result


def _exact(c, item, root):
    c.require(isinstance(item,dict) and set(item)=={'path','bytes','sha256'},'Exact bytes/SHA identity required')
    raw=item['path'];p=Path(raw)
    c.require(isinstance(raw,str) and p.is_absolute() and raw==str(p) and '..' not in p.parts,
              'Noncanonical identity/alias')
    c.contained(p,root);c.require(type(item['bytes']) is int and item['bytes']>=0,'Invalid bytes')
    c.checked(item)

    payload=p.read_bytes()
    c.require(len(payload)==item['bytes'] and hashlib.sha256(payload).hexdigest()==item['sha256'],'Identity changed during snapshot')
    return payload


def _json(c, payload):
    def pairs(rows):
        value={}
        for key,item in rows:
            c.require(key not in value,'Duplicate JSON key')
            value[key]=item
        return value
    return json.loads(payload,object_pairs_hook=pairs,
                      parse_constant=lambda value: (_ for _ in ()).throw(c.Refusal('Nonfinite JSON')))

def _capture_census(a,c,clock,capture,policy):

    outputs=policy['producer_outputs'];initial=policy['initial_input_paths']
    c.require(isinstance(outputs,dict) and isinstance(initial,list),'Reviewed finite capture census pending')
    c.require(clock.get('producer_outputs')==outputs and [r['path'] for r in clock.get('initial_inputs',[])]==initial,'Native clock capture input census drift')
    stages=capture.get('producer_states');c.require(isinstance(stages,dict) and set(stages)==set(outputs),'Capture stage census omitted/extra')
    expected={r['path']:r for r in clock['initial_inputs']}
    for name,paths in outputs.items():
        c.require(len(paths)==len(set(paths)),'Duplicate native stage input')
        row=stages[name];items=row.get('files')
        c.require(isinstance(items,list) and len(items)==len({x['path'] for x in items}),'Capture stage duplicate/missing')
        if row.get('state')=='COMPLETED_BY_CUTOFF':
            c.require({x['path'] for x in items}==set(paths) and _utc(c,row['end_utc'])<=_utc(c,capture['cutoff_utc']),'Capture completed-stage census/chronology drift')
            expected.update({x['path']:x for x in items})
        else:c.require(row.get('state') in {'TERMINAL_BY_CUTOFF','RUNNING_AT_CUTOFF','PENDING_AT_CUTOFF'} and items==[],'Capture dishonest pending/terminal identity')
    rows=capture['files']
    c.require(len(rows)==len({x['path'] for x in rows}) and {x['path']:x for x in rows}==expected,'Native capture omitted/extra identity')


def _release(a,c):

    phase=c.os.environ.get('SCORING_PHASE','prepare')
    c.require(phase!='prepare','SCORING prepare: no runtime release or production read')
    if phase=='accept':
        c.require(a.synthetic,'Accept phase allows explicitly artificial fixtures only')
    else:
        c.require(phase=='source_runtime' and not a.synthetic,'Separate source runtime release required')
    a._released=False
    a._official_ready=None
    a._t5_value={}
    a.sources()
    with a._validation():
        t5=c.read(a.out/'T5_BINDING.json')
        c.require(t5.get('state')=='T5_VERIFIED' and t5.get('source_verified') is True,'Actual C list-form verified T5 required')
        c.require(isinstance(t5.get('files'),list) and len(t5['files'])==len({r['path'] for r in t5['files']}),'Missing/duplicate T5 identities')
        a._t5_value=t5
        for row in t5['files']:
            c.require(a.metadata_root(row['path']),'T5 payload/score/host_state root refused')
        freeze_id=c.identity(a.out/'SCIENCE_FREEZE.json')
        c.require(freeze_id in t5['files'],'Scientific freeze not exact T5-listed')
        f=_json(c,_exact(c,freeze_id,a.out))
        c.require(_utc(c,f.get('frozen_utc'))<_utc(c,t5.get('utc')),'Scientific freeze not strictly before T5')
        c.require(set(f)=={'schema','state','task_revision','frozen_utc','files','tested_sources','callable_ast_inventory','scientific_decisions','numeric_ancestor_contract','acceptance','independent_review','release_binding','synthetic_only'},'Scientific timestamp_checks exact schema fields required')
        _exact(c,f['callable_ast_inventory'],a.project)
        expected_decisions=c.read(c.HERE/'SCIENCE_RULES.json')['authority_identities']
        c.require(f['scientific_decisions']==expected_decisions and c.read(a.out/'SCIENCE_RULES.json')['authority_identities']==expected_decisions,'Frozen protocol/decision identities missing/changed')


        for item in expected_decisions:_exact(c,item,c.LIVE)
        c.require(f.get('schema')==FREEZE_SCHEMA and f.get('state')==FREEZE_STATE,
                  'Missing/unfrozen scientific timestamp_checks')
        c.require(f.get('task_revision')==TASK_REVISION,'Wrong scientific task revision')
        c.require(f.get('synthetic_only') is True if a.synthetic else f.get('synthetic_only') is not True,
                  'Synthetic/real input_checks')
        declared=c.read(a.out/'FREEZE_CENSUS.json')['files']
        c.require(isinstance(f.get('files'),dict) and set(f['files'])==set(declared) and len(declared)==len(set(declared)),
                  'Scientific freeze exact census missing/extra/duplicate')
        for rel,item in f['files'].items():
            c.require(not Path(rel).is_absolute() and rel==Path(rel).as_posix() and '..' not in Path(rel).parts,
                      'Scientific freeze alias/escape')
            ident=dict(path=str(a.out/rel),**item)
            _exact(c,ident,a.out);a._authority_files[ident['path']]=ident
        for rel,pin in f['tested_sources'].items():
            own=c.HERE/rel
            if own.is_file():
                expected=dict(path=str(own),**pin)
                _exact(c,expected,c.HERE);a._authority_files[str(own)]=expected
        test=_json(c,_exact(c,f['acceptance'],a.out))
        spec=c.read(a.out/'SCIENTIFIC_ACCEPTANCE_SPEC.json')
        artificial=(a.synthetic and phase=='accept' and test.get('schema')=='C_SCORING_ARTIFICIAL_RELEASE_PREMISE_V1' and test.get('state')=='ARTIFICIAL_PRIOR_REVIEW_PREMISE_NOT_ACCEPTANCE' and test.get('synthetic_only') is True and test.get('premise_only') is True)
        c.require((artificial or (test.get('schema')=='C_statistics_ACCEPTANCE_V1' and test.get('state')=='CLEAN_FULL_PASS'))
                  and test.get('task_revision')==TASK_REVISION and test.get('case_ids')==spec['case_ids']
                  and test.get('failures')==[] and test.get('errors')==[] and test.get('skipped')==[]
                  and test.get('delivered_sources')==f['tested_sources'],
                  'Exact new scientific acceptance required; historical FILL PASS is invalid')
        c.require(set(f['tested_sources'])==set(spec['tested_source_files']),'Scientific tested-source census omitted/extra')
        resources=test.get('resources',{})
        c.require(artificial or (resources.get('nice')==20 and resources.get('test_processes')==1
                  and resources.get('minimum_memory_free_percent',0)>=25
                  and resources.get('scratch_peak_bytes',10**12)<10**9
                  and resources.get('peak_rss_bytes',10**12)<=1610612736
                  and resources.get('periodic_samples')
                  and resources.get('breaches')==[]),'Observed inherited acceptance resource gates required')
        c.require(all(c.identity(a.out/rel)==dict(path=str(a.out/rel),**item)
                      for rel,item in f['tested_sources'].items()),'Tested/delivered source drift')
        review=_json(c,_exact(c,f['independent_review'],a.out))
        c.require(review.get('schema')=='C_SCORING_INDEPENDENT_REVIEW_V1'
                  and review.get('verdict')=='ACCEPT' and review.get('independent') is True
                  and review.get('reviewer_role')=='C_REVIEWER'
                  and review.get('task_revision')==TASK_REVISION
                  and review.get('reviewed_sources')==f['tested_sources'],
                  'Independent exact-version C review required; AP/notice_delays cannot self-certify')
        binding=_json(c,_exact(c,f['release_binding'],a.out))
        if not artificial:
            import review_gate
            c.require(review_gate.eligibility(a.out)['state']=='FREEZE-READY-PENDING-SOURCE-RELEASE','Full independent scientific eligibility required')
        c.require(binding.get('schema')=='C_SCORING_SCIENTIFIC_RELEASE_V1'
                  and binding.get('source_reviewed') is True
                  and binding.get('scientific_eligibility_changed') is False,
                  'Actual reviewed scientific release required')
        c.require(binding.get('integration_complete') is True,'Stable scientific integration pending')

        a._disk_release(binding)
        c.require(f['numeric_ancestor_contract']==binding['numeric_ancestor_contract'],'Numerical ancestor release/freeze disagreement')
        a._verify_numeric_ancestors(binding['numeric_ancestor_contract'])
        a._science_policy=_json(c,_exact(c,binding['runtime_family_policy'],a.out))
        c.require(a._science_policy.get('schema')=='C_SCORING_RUNTIME_FAMILIES_V1'
                  and a._science_policy.get('status')=='REVIEWED_EXACT_OWNER_CONTRACTS'
                  and set(a._science_policy.get('families',{}))=={'AP5','AP6','notice_delays','scoring_callback'},
                  'Stable four-family owner policy pending')
        a._scorer_contract=_json(c,_exact(c,binding['scorer_contract'],a.out))
        c.require(a._scorer_contract.get('schema')=='C_SCORING_SCORER_CONTRACT_V1'
                  and a._scorer_contract.get('status')=='REVIEWED_EXACT_R2_SOURCE_DELIVERY',
                  'PCIMPL2/scoring_callback exact source_delivery pending')
        entries=_json(c,_exact(c,binding['entry_contracts'],a.out))
        c.require(entries.get('schema')=='C_SCORING_RUNTIME_ENTRIES_V1' and entries.get('status')=='REVIEWED_EXACT_OWNER_ENTRIES' and entries.get('entries') and all(r.get('status')=='OWNER_DELIVERED_REVIEWED' for r in entries['entries'].values()),'Delivered owner entries pending')
        a._science_freeze=f;a._science_binding=binding
        a._released=True


def _numeric_ancestors(a,c,item):
    value=_json(c,_exact(c,item,a.out))
    c.require(value.get('schema')=='C_SCORING_NUMERIC_ANCESTORS_V1'
              and value.get('source_adopted') is True,'Reviewed source-only ancestor adoption required')
    expected=c.read(a.out/'NUMERIC_ANCESTOR_PROPOSAL.json')['files']
    c.require(value.get('files')==expected,'Original numerical ancestor identity changed/omitted')
    for rel,pin in expected.items():
        row=dict(path=str(c.LIVE/rel),**pin)
        _exact(c,row,c.LIVE);a._authority_files[row['path']]=row
    c.require(not value.get('downstream_successor_files'),'C→AP→C timestamp_checks cycle refused')


def _views(a,c,items):
    items=copy.deepcopy(items)
    a.verify_t5_coverage()
    with a._validation():
        batch=a.d/'state/SEAL_BATCH.json'
        c.require(a._verified_files.get(str(batch))==c.identity(batch),'Verified D seal chain required')
        parent=c.read(batch)['conf_seal'];c.checked(parent)
        c.require(set(items)=={'original','r2','execution'},'Both original and R2 score chains required')
        from runtime_resolution import _wire
        policy=_wire(a)
        c.require(policy.get('status')=='REVIEWED_EXACT_R2_SOURCE_DELIVERY','Scorer contract pending')
        certificate={'view_inputs':items,'batch_seal':c.identity(batch),'contract':c.identity(a._science_binding['scorer_contract']['path']),'files':{}}
        for view in ('original','r2'):
            supplied=items[view];wire=policy[view]
            c.require(supplied['seal']==wire['seal_identity'],'Wrong seal association')
            seal_item=supplied['seal'];seal_payload=_exact(c,seal_item,a.project)
            seal=_json(c,seal_payload)
            c.require(seal_item['sha256']==parent['sha256'],'Scorer seal differs from verified original seal')
            if a.synthetic:
                c.require(seal.get('synthetic') is True and Path(seal_item['path']).is_relative_to(Path('/private/tmp')),'Explicit artificial seal required')
            else:
                c.require(seal.get('state')=='ALL_SPECIFIED_PREDICTIONS_SEALED'
                          and seal.get('sealed_before_outcome_scoring') is True
                          and seal.get('partial_predictions_scored') is False,'Production seal incomplete/partial')
                c.require(seal['design_freeze_sha256']==c.sha(a.q/'confirmation/FREEZE.json')
                          and isinstance(seal.get('completed_input_manifest_sha256'),str)
                          and len(seal['completed_input_manifest_sha256'])==64,'Design/input manifest seal drift')
            c.require(Path(supplied['score_receipt']['path'])==Path(wire['receipt_path'])
                      and Path(supplied['score_report']['path'])==Path(wire['report_path']),
                      'Wrong view/receipt destination')
            state=Path(wire['state_root'])
            c.no_symlink_path(state)
            c.require(Path(wire['receipt_path'])==state/'scored/SCORE_RECEIPT.json'
                      and Path(wire['report_path'])==state/'scored/SCORE_REPORT.json','Unreviewed scorer layout')
            if view=='original':
                c.require(seal_item==parent and state==Path(parent['path']).parent,'Original callable/destination changed')
            else:
                bridge=wire['state_seal_association']
                c.require(bridge.get('schema')=='C_SCORING_R2_STATE_SEAL_ASSOCIATION_V1' and bridge.get('source_reviewed') is True and bridge.get('resolution')=='EXACT_IN_PROCESS_ORIGINAL_SEAL_ONLY' and bridge.get('state_root')==str(state) and bridge.get('seal_identity')==parent and seal_item==parent,'Unreviewed fresh-state seal bridge')
                c.require(state!=Path(parent['path']).parent and not (state/'SEAL.json').exists(),'R2 must use a separate unambiguous fresh state')
            receipt=_json(c,_exact(c,supplied['score_receipt'],state/'scored'))
            c.require(receipt.get('state')=='FROZEN_SCORE_COMPLETE' and receipt.get('seal_sha256')==seal_item['sha256'],
                      'Official score incomplete/unverified/wrong seal')
            if view=='r2':
                marker=wire['evaluation_view']
                days=[];day=dt.date(2026,5,19)
                while day<=dt.date(2026,9,30):days.append(day.isoformat());day+=dt.timedelta(days=1)
                source=a.project/'comparison_inputs/code/news_source.py'
                c.require(marker==dict(schema='PCPRIMARY_R2_NEWS_EVALUATION_V1',issue_days=days,
                           scientific_source_sha256=c.sha(source),sealed_domain_days=214,primary_days=135),
                          'R2 policy/source/view drift')
                c.require(receipt.get('evaluation_view')==marker,'Wrong/drifted R2 evaluation marker')
            else:c.require('evaluation_view' not in receipt,'R2 receipt cannot stand in for original window')
            c.require({str(p) for p in (state/'scored').iterdir()}==set(wire['output_census'])|{wire['receipt_path']},'Unsealed/unlisted extra official score output')
            rows=receipt.get('files');c.require(isinstance(rows,list) and len(rows)==len({r['path'] for r in rows}),
                                             'Receipt census missing/duplicate')
            c.require(set(r['path'] for r in rows)==set(wire['output_census']),'Official output census omitted/extra')
            c.require(supplied['score_report'] in rows,'Official report not receipt-bound')
            for row in [seal_item,supplied['score_receipt'],*rows]:
                root=a.project if row==seal_item else state/'scored'
                _exact(c,row,root);certificate['files'][row['path']]=row
            feature=Path(seal['feature_manifest_path'])
            c.require(a._verified_files.get(str(feature))==c.identity(feature)
                      and c.identity(feature)['sha256']==seal['feature_manifest_sha256'],
                      'Feature manifest absent/drifted from verified seal chain')
            certificate['files'][str(feature)]=c.identity(feature)
        producer=a._ap_runtime.member(policy['execution_producer_path'])
        callback_freeze=a._ap_runtime.member(str(a.q/a._science_policy['families']['scoring_callback']['freeze']))
        execution_item=items['execution']
        c.require(execution_item['path']==policy['execution_evidence_path'],'Wrong runtime execution evidence path')
        execution=_json(c,_exact(c,execution_item,a.project))
        c.require(execution.get('schema')=='C_SCORING_SCORE_EXECUTION_EVIDENCE_V1'
                  and execution.get('original_receipt')==items['original']['score_receipt']
                  and execution.get('r2_receipt')==items['r2']['score_receipt']
                  and execution.get('capture_complete') is True
                  and execution.get('original_exit_status')==0 and execution.get('r2_exit_status')==0,
                  'Actual successful original capture/R2 execution evidence required')
        c.require(execution.get('producer_code')==producer and execution.get('callback_freeze')==callback_freeze,
                  'Execution evidence not bound to reviewed runtime callback producer')
        clock=_json(c,_exact(c,execution['original_clock'],a.project))
        c.require(clock.get('schema')=='SCORECB_POSTSCORE_CLOCK_ASSOCIATION_V1'
                  and clock.get('state')=='POSTSCORE_CLOCK_ASSOCIATION_VERIFIED'
                  and clock.get('conf_score_receipt')==items['original']['score_receipt'],
                  'Original native callback clock not bound')
        c.require(clock.get('source_verified') is True and clock.get('retrospective_reconstruction_authorised') is False,
                  'Original callback retrospective/unverified')
        completion=clock.get('completion_evidence',{})
        c.require(completion.get('kind')=='SOURCE_OBSERVED_SPECIFIED_COMMAND_EXIT'
                  and completion.get('argv')==policy['original']['argv'] and completion.get('exit_status')==0
                  and completion.get('no_postscore_launches_confirmed') is True
                  and completion.get('receipt_contents_decoded') is False,'Unverified original observed exit/embargo')
        armed=_json(c,_exact(c,clock['armed'],a.project))
        c.require(armed.get('state')=='ARMED_AFTER_T5_BEFORE_SCORE'
                  and armed.get('callback_freeze')==callback_freeze
                  and armed.get('score_argv')==policy['original']['argv']
                  and armed.get('score_receipt_absent') is True
                  and armed.get('no_postscore_launches_confirmed') is True,'Original arming/callback lineage drift')
        t5_identity=c.identity(a.out/'T5_BINDING.json')
        c.require(clock['t5_binding']==t5_identity and armed['t5_binding']==t5_identity
                  and clock['plan']==armed['plan'],'Actual T5/plan lineage drift')
        plan_id=clock['plan'];_exact(c,plan_id,a.project)
        callback_value=_json(c,_exact(c,callback_freeze,a.project))
        c.require(callback_value.get('plan')==plan_id,'Runtime callback freeze does not bind exact plan')
        c.require(plan_id in c.read(a.out/'T5_BINDING.json')['files'],'Callback plan not actual T5-listed')

        capture=_json(c,_exact(c,execution['original_capture'],a.project))
        cp=policy['capture_contract']
        c.require(capture.get('schema')==cp['schema'] and capture.get('state')==cp['state'],
                  'Native capture incomplete/unverified')
        c.require(capture.get('clock_association')==execution['original_clock']
                  and capture.get('source_values_decoded') is False
                  and capture.get('pending_is_negative') is False,'Native cutoff capture lineage/interpretation drift')
        score_time=_utc(c,clock['score_complete_utc']);c.require(_utc(c,a._t5_value['utc'])<score_time,'Official score must follow actual T5');cutoff=max(score_time,dt.datetime(2026,10,6,1,tzinfo=dt.timezone.utc))
        c.require(_utc(c,capture['cutoff_utc'])==cutoff
                  and _utc(c,capture['observed_utc'])>=cutoff
                  and _utc(c,execution['capture_complete_utc'])>=_utc(c,capture['observed_utc']),
                  'Native specified cutoff/observation drift')
        rows=capture.get('files');c.require(isinstance(rows,list) and len(rows)==len({r['path'] for r in rows}),'Native capture census duplicate/missing')
        _capture_census(a,c,clock,capture,cp)
        for row in rows:_exact(c,row,a.project);certificate['files'][row['path']]=row
        c.require(_utc(c,clock['callback_ready_utc'])<=_utc(c,execution['capture_complete_utc'])
                  <_utc(c,execution['r2_start_utc'])<=_utc(c,execution['r2_complete_utc']),
                  'R2 started before successful original capture')
        _exact(c,execution['actual_permit_identity'],a.project)
        from runtime_resolution import _permit
        if a.synthetic:
            c.require(execution['actual_permit_identity']==policy['r2']['permit_identity'],'Artificial permit provenance drift')
        else:_permit(a,policy['r2'],execution['actual_permit_identity'])
        certificate['files'][execution['actual_permit_identity']['path']]=execution['actual_permit_identity']
        for row in (execution_item,execution['original_clock'],execution['original_capture'],clock['armed'],plan_id,callback_freeze,producer):
            certificate['files'][row['path']]=row
        for key in ('receipt_identity','report_identity'):
            actual=items['original']['score_receipt' if key=='receipt_identity' else 'score_report']
            c.require(policy['original'].get(key) in (None,actual),'Original receipt/report contract identity drift')
        a._official_files.update(certificate['files'])
        a._sealed_roots.update(Path(policy[v]['receipt_path']).parent for v in ('original','r2'))
        return certificate


def _recheck(a,c,certificate):
    with a._validation():
        c.require(c.identity(a.d/'state/SEAL_BATCH.json')==certificate['batch_seal'],'Score parent drift')
        c.require(c.identity(certificate['contract']['path'])==certificate['contract'],'Scorer contract drift')
        for row in certificate['files'].values():_exact(c,row,a.project)


        for view in ('original','r2'):
            wire=a._scorer_contract[view];root=Path(wire['state_root'])/'scored'
            c.no_symlink_path(root)
            c.require({str(p) for p in root.iterdir()}==set(wire['output_census'])|{wire['receipt_path']},
                      'Official output namespace changed after completion')
