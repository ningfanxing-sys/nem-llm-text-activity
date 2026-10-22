'Read the targets and notice counts used in Figure 2.'
import hashlib
import json
from pathlib import Path
from datetime import timezone, timedelta
import numpy as np
import pandas as pd

AEST = timezone(timedelta(hours=10))


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1024*1024), b''):
            h.update(block)
    return h.hexdigest()


def load_context(score_root, official):
    sources = []
    def bound(entry, parent):
        path = Path(entry['path'])
        assert digest(path) == entry['sha256'], str(path)
        if 'bytes' in entry:
            assert path.stat().st_size == entry['bytes']
        sources.append({'path': str(path), 'sha256': entry['sha256'], 'binding': parent})
        return path
    manifest = json.loads((score_root/'SCORING_MANIFEST.json').read_text())
    seal_path = bound(manifest['inputs']['seal'], 'SCORING_MANIFEST.json /inputs/seal')
    seal = json.loads(seal_path.read_text())
    receipt = json.loads((score_root/'R2_STATE/scored/SCORE_RECEIPT.json').read_text())
    assert digest(seal_path) == receipt['seal_sha256']
    fm_path = bound({'path': seal['feature_manifest_path'], 'sha256': seal['feature_manifest_sha256']},
                    'SEAL.json /feature_manifest_sha256')
    fm = json.loads(fm_path.read_text())
    # Check timeline dates against the design and saved numerical inputs.
    freeze_path=bound({'path':str(fm_path.parents[3]/'FREEZE.json'),
                       'sha256':fm['design_freeze_sha256']},'feature manifest /design_freeze_sha256')
    freeze=json.loads(freeze_path.read_text())
    design_paths={}
    for name in ['DESIGN_CONFIG.json','STUDY_DESIGN.md']:
        design_paths[name]=bound({'path':str(freeze_path.parent/name),**freeze['frozen_files'][name]},
                                 'FREEZE.json /frozen_files/'+name)
    config=json.loads(design_paths['DESIGN_CONFIG.json'].read_text())
    assert config['notice']['training_nominal_months']==['2021-10','2023-12']
    assert config['notice']['target_days']==['2026-08-01','2026-09-30']
    assert config['news']['preprocessing_train'][0]=='2021-10-01'
    assert config['news']['refit']=='daily expanding strictly past-legal complete target days'
    authority_path=bound(official['rows'][0]['timestamp_checks'],'official /rows/0/timestamp_checks')
    timestamp_checks=json.loads(authority_path.read_text())
    timestamp_files=timestamp_checks['operational']['timestamps']['T5']['files']
    entries=[(p,h) for p,h in timestamp_files.items() if p.endswith('/MODEL_CUTOFF_RECORD.json')]
    assert len(entries)==1
    cutoff_path=bound({'path':entries[0][0],'sha256':entries[0][1]},
                       'SCORING_NUMERIC.json /operational/timestamps/T5/files')
    cutoff=json.loads(cutoff_path.read_text())['records']['gpt-6-luna']['knowledge_cutoff']
    assert cutoff=='2026-05-18'
    assert receipt['evaluation_view']['issue_days'][0]=='2026-05-19'
    price = {}; matched_counts = {}; unique_counts = {}
    keys = ['origin','target_time','region','horizon']
    for task, ref, start, size in [('news','M','2026-05-19',9720),
                                 ('notice','M_notice','2026-08-01',527040)]:
        entries = [e for e in seal['predictions'] if e['source']==task and e['arm']==ref
                   and e['seed']==20260919 and e['variant']=='main']
        assert len(entries)==1
        predictions = pd.read_parquet(bound(entries[0], 'SEAL.json /predictions (main seed activity arm)'))
        selected = predictions[predictions.target_day.between(start,'2026-09-30')].copy()
        truth = pd.read_parquet(bound(seal['truth_panels'][task],f'SEAL.json /truth_panels/{task}'),
                                columns=keys+['y'])
        joined = selected.merge(truth,on=keys,how='left',validate='one_to_one')
        assert len(joined)==size and np.isfinite(joined.y).all()
        regions = ['NSW1','QLD1','TAS1'] if task=='news' else ['NSW1','QLD1','SA1','TAS1','VIC1']
        assert sorted(joined.region.unique()) == regions
        # Compare targets with those used in the saved daily MAE calculation.
        losses = pd.read_csv(score_root/f'R2_STATE/scored/{task}__DAILY_LOSSES.csv')
        measured = joined.assign(error=(joined.prediction-joined.y).abs()).groupby('target_day').error.mean()
        assert np.allclose(measured.to_numpy(),losses[ref],rtol=0,atol=1e-12)
        matched_counts[task] = len(joined)
        unique_counts[task] = len(joined[['target_time','region']].drop_duplicates())
        # Average targets with equal weights across the six notice horizons.
        price[task] = joined.groupby('target_day',sort=True).y.mean()
    news_bundle = next(b for b in fm['bundles'] if b['source']=='news' and b['arm']=='M' and b['variant']=='main')
    cov_path = bound({'path':news_bundle['coverage_path'],'sha256':news_bundle['coverage_sha256']},
                     'feature manifest news M /coverage_sha256')
    coverage = {}
    first = {}; seen = set(); region_sets = {}
    with cov_path.open() as f:
        for line_no,line in enumerate(f,1):
            row=json.loads(line); issue=pd.Timestamp(row['origin']).tz_convert(AEST)
            day=issue.strftime('%Y-%m-%d')
            if not '2026-05-19'<=day<='2026-09-30': continue
            assert issue.hour==issue.minute==0 and len(row['source_ids'])==row['clock_admitted']
            ids=set(row['source_ids']); assert len(ids)==row['clock_admitted']
            region_sets.setdefault(day,[]).append(ids)
            coverage[day]=row['clock_admitted']
            for aid in ids: first[aid]=min(day,first.get(aid,day))
            seen |= ids
    assert len(coverage)==135 and len(seen)==207
    assert all(len(v)==3 and v[0]==v[1]==v[2] for v in region_sets.values())
    # Compare notice counts with the activity-reference feature array.
    extras=np.load(bound(news_bundle['extras_matrix'],'feature manifest news M /extras_matrix'),mmap_mode='r')
    panel=pd.read_parquet(news_bundle['panel_path'],columns=['target_day'])
    count_col=news_bundle['extra_columns'].index('article_count')
    count=pd.DataFrame({'day':panel.target_day,'count':extras[:,count_col]})
    count=count[count.day.between('2026-05-19','2026-09-30')].groupby('day')['count']
    assert (count.nunique()==1).all()
    assert count.first().to_dict()==coverage
    side_path=bound(fm['notice_derived_dates'],'feature manifest /notice_derived_dates')
    side=json.loads(side_path.read_text()); clocks={}
    for row in side['original']:
        aid=row['notice_id']; clock=row['derived_dates']['available_utc']
        if aid in clocks: assert clocks[aid]==clock
        clocks[aid]=clock
    local_days=[pd.Timestamp(clock).tz_convert(AEST).strftime('%Y-%m-%d') for clock in clocks.values()]
    for lo,hi in [('2024-08-01','2025-10-31'),('2026-05-19','2026-07-26')]:
        assert not any(lo<=d<=hi for d in local_days)
    days=pd.date_range('2026-08-01','2026-09-30').strftime('%Y-%m-%d')
    arrivals=dict.fromkeys(days,0)
    for clock in clocks.values():
        day=pd.Timestamp(clock).tz_convert(AEST).strftime('%Y-%m-%d')
        if day in arrivals: arrivals[day]+=1
    months={m:sum(v for d,v in arrivals.items() if d.startswith(m)) for m in ['2026-08','2026-09']}
    frozen=official['rows'][337]['value']['human_review']['extraction_failure']['by_month']['notice']
    assert months=={m:frozen[m]['counts']['population'] for m in months}=={'2026-08':259,'2026-09':466}
    activity={'news':pd.Series(coverage).sort_index(),'notice':pd.Series(arrivals)}
    audit={'sources':sources,'matched_price_rows':matched_counts,'unique_target_region_rows':unique_counts,
           'news_distinct_articles':len(seen),'news_window_appearances':sum(coverage.values()),
           'news_first_admission_months':{m:sum(d.startswith(m) for d in first.values()) for m in ['2026-05','2026-06','2026-07','2026-08','2026-09']},
           'notice_admissions_by_month':months,'notice_distinct_arrivals':sum(arrivals.values())}
    return price,activity,audit
