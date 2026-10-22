'Recompute composite losses using the frozen scoring functions.'
import copy
from types import SimpleNamespace
from pathlib import Path
import read_comparisons as P
from frozen_losses import ast_functions


def composite(primary_tests,sc,main,batch,dispositions):
    scheduler_ns=dict(SEED=20260919,EXTRA_SEEDS=(20260920,20260921),
        NEWS_PRIMARY=('N','M','L_count','L_chen'),
        NEWS_SECONDARY=('M_shift','E_raw','W_Bai','P_shift','P_content'),
        NOTICE_PRIMARY=('N','M_notice','L14','L_Laz','L_chen_notice'),
        NOTICE_SECONDARY=('M_shift_notice','R','T','P_shift','P_content','NP','NPL','NPP'))
    import dataclasses,datetime
    scheduler_ns.update(dataclass=dataclasses.dataclass,date=datetime.date,timedelta=datetime.timedelta)
    ast_functions(P.confirmation/'code/scheduler.py',('FitTask','days','news_tasks','notice_tasks','plan'),scheduler_ns)
    scheduler=SimpleNamespace(**scheduler_ns)
    ex=dict(conf_module=lambda name:scheduler if name=='scheduler' else None,
        A1_NEWS_SECONDARY=('W2_D',),A1_NOTICE_SECONDARY=('NPM',))
    ast_functions(P.confirmation/'execution/execution_adapter.py',('specified_plan',),ex)
    ns=dict(copy=copy)
    ast_functions(P.BATCH_CODE/'score_batch.py',('composite_seal',),ns)
    for ident in batch.get('predictions',[]):P.checked(ident)
    return ns['composite_seal'](SimpleNamespace(execution=SimpleNamespace(specified_plan=ex['specified_plan'])),main,batch,dispositions)


def effective_inputs(primary_tests,sc,state,records,synthetic=False):
    inputs=primary_tests.Inputs(state)
    cs8=records['batch']['CS8']
    P.require('score_receipt' in cs8,'CS8 frozen score receipt required; no main-score substitution')
    receipt=P.strict_json(P.checked(cs8['score_receipt']))
    P.require(receipt['state']=='FROZEN_SCORE_COMPLETE' and receipt['seal_sha256']==inputs.seal_sha256,'CS8 receipt/seal mismatch')
    for ident in receipt['files']:P.checked(ident)
    main=inputs.seal
    main_stages={row['stage']:row for row in main['stage_dispositions']}
    for name,row in cs8['stage_dispositions'].items():
        P.require(name in P.RERUNS and name in main_stages and P.rerun_trigger(main_stages[name]) is not None,'CS8 disposition without frozen re-run eligibility: '+name)
        P.require(not row.get('score_eligible') or row['state'] in ('COMPLETE','COMPLETE_WITH_UNAVAILABLE_CONFIGURATIONS'),
                  'CS8 partial/deviated stage marked score eligible')
    effective=composite(primary_tests,sc,main,records['batch_seal'],cs8['stage_dispositions'])

    keys={(t,a,20260919,'main') for t,ps in P.PAIRS.items() for a,b in ps for a in (a,b)}
    def selected(seal):return {(i['source'],i['arm'],i['seed'],i['variant']):i['sha256'] for i in seal['predictions'] if (i['source'],i['arm'],i['seed'],i['variant']) in keys}
    P.require(selected(main)==selected(effective),'CS8 altered primary predictions')
    inputs.seal=effective;inputs.receipt=receipt
    inputs.score_files={Path(i['path']).name:i for i in receipt['files']}
    inputs.read_log.append(dict(cs8_receipt=cs8['score_receipt'],source_seals=[records['_seal_path'],records['batch']['seal']]))
    return inputs
