'Compute the full-window news score using the frozen scoring AST.'
from copy import deepcopy
from pathlib import Path
from adapters import exclusive_json
from association import register
from source_bytes import checked, document, identity, require
from native_entries import native_dependencies, reader_modules


def produce(a, sources, contract):
    original=a._official_ready['view_inputs']['original'];seal=document(original['seal'])
    seal['_state_root']=str(Path(original['seal']['path']).parent)
    out=Path(contract['output_directory']);out.mkdir(parents=True,exist_ok=False)
    P=sources.module('read_comparisons',Path(a._control['project'])/'studies/inference/code/read_comparisons.py')
    L=sources.module('frozen_losses',P.HERE/'code/frozen_losses.py')
    modules=reader_modules(sources,a._control['project']);primary_tests,sensitivity_tests,robustness_tests,sc,_=modules
    receipt=document(original['score_receipt']);saved={Path(i['path']).name:i for i in receipt['files']}
    with native_dependencies(P,sources,modules):
        ns=L.native_functions()
        from reference_gate import ScoringBoundary, primary_bundle, capture_boundary
        with capture_boundary(L):
            captured,daily,clips,summary=L.core_task(ns,ScoringBoundary(sc,'news_full_window',out),'news',seal,out/'native_replay')
        primary=captured['news__PRIMARY.json']
        require(len(primary['days'])==214 and primary['days'][0]=='2026-03-01' and primary['days'][-1]=='2026-09-30',
                'K5 full score_news_full_window before attachment')
        require(L.canonical_daily(primary['days'],daily)==checked(saved['news__DAILY_LOSSES.csv']),
                'K5 independent original daily byte parity')
        require(summary['pooled_mae']==document(original['score_report'])['news']['pooled_mae'],
                'K5 independent original pooled MAE parity')
        proofs={}
        sc2000=P.ChunkedScoring(sc,2000,contract['chunk'],P.resource_gate)
        for name,bundle in captured.items():
            require(name in saved,'K5 missing original native anchor: '+name)
            saved_native=document(saved[name])
            if bundle.get('reference_mae_gate'):


                require([(r['arm'],r['reference']) for r in saved_native['reports']]==
                    [tuple(p) for p in bundle['pairs']], 'K5 original local family identity')
                proofs[name]=dict(state='NOT_EVALUABLE',reason=bundle['reason'],
                    reference_mae_gate=bundle['reference_mae_gate'],original_native_anchor=saved[name])
                bundle['frozen_parity']='NOT_EVALUABLE'
            else:
                proofs[name]=dict(state='PASS',checks=L.native_parity(sc2000,bundle,saved_native))
                bundle['frozen_parity']='PASS'
        mean=captured.get('news__THREE_SEED_MEAN.json')
        if mean and mean['state']=='COMPUTED':
            primary['mean_prediction_losses']=mean['losses']
            primary['mean_prediction_loss_definition']='daily loss of the mean prediction; not mean arm loss'

        primary.update(id='news/primary',subset=False)
        compute=primary_bundle(P.compute_bundle,'news_full_window',out)
        specified=compute(primary_tests,sc2000,primary)
        current=compute(primary_tests,P.ChunkedScoring(sc,100000,contract['chunk'],P.resource_gate),primary)
        seeds=(current.get('three_seed') or {}).get('reports',[])
        contrasts=[]
        for i,row in enumerate(current['reports']):
            checks,tier,rob=P.six_checks(primary_tests,sensitivity_tests,row,seeds[i] if seeds else None)
            contrasts.append(dict(deepcopy(row),checks=checks,frozen_tier=tier,
                native_class=P.CLASS[row['decision']],native_envelope=robustness_tests.envelope(row),robustness=rob))
        require([(c['arm'],c['reference']) for c in contrasts]==[('L_count','M'),('L_chen','M')],'K5 family2')


        rs8=dict(specified_reading_2000=primary_tests.json_safe(specified),three_seed=primary_tests.json_safe(current.get('three_seed')),
            native_seed_sources={k:dict(deepcopy(captured[k]['native_result']),original_native_anchor=saved[k])
                if k in captured and captured[k].get('reference_mae_gate') else deepcopy(document(saved[k]))
                for k in saved if k.startswith('news__SEED_') or k=='news__THREE_SEED_MEAN.json'})
        n0=[dict(arm=c['arm'],reference=c['reference'],native_class=c['native_class'],checks=c['checks'],
            frozen_tier=c['frozen_tier'],envelope=c['native_envelope']) for c in contrasts]
        attachment=dict(schema='MINRUN_ORIGINAL_NEWS_214_V1',days=214,days_native=primary['days'],contrasts=contrasts,
            pooled_mae=summary['pooled_mae'],RS8=rs8,N0=n0,bootstrap_draws=100000,
            source_receipt_sha256=original['score_receipt']['sha256'],original_callable=a._scorer_contract['original']['callable'],
            original_destination=a._control['original']['receipt_path'],science_callable=str(Path(L.__file__))+'::core_task',
            executed_original_score_AST_source=identity(P.confirmation/'execution/seal_score.py'),science_destination=str(out),
            clipping=primary_tests.json_safe(clips),outside_primary_robustness_and_forest=True)
        attachment=primary_tests.json_safe(attachment)
        source=register(a,exclusive_json(out/'SPECIFIED_NEWS_214.json',attachment))
        proof=register(a,exclusive_json(out/'NEWS_FULL_WINDOW_PARITY.json',dict(schema='MINRUN_ORIGINAL214_PARITY_V1',
            native_B2000=proofs,daily_csv=saved['news__DAILY_LOSSES.csv'],pooled_source=original['score_report'],
            specified_reading_2000=primary_tests.json_safe(specified))))
        receiptid=register(a,exclusive_json(out/'NEWS_FULL_WINDOW_RECEIPT.json',dict(schema='MINRUN_ORIGINAL214_RECEIPT_V1',
            files=[source,proof],original_score_receipt=original['score_receipt'],science_callable=attachment['science_callable'],
            own_output_directory=str(out),synthetic_only=a.synthetic)))
    return dict(document=attachment,source=source,receipt=receiptid,proof=proof)
