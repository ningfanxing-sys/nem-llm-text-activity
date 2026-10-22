"""Complete CONF feature orchestration. Study sources are read only after permit.

Writes one shared numeric float32 NPY per source and per-arm extras/order manifests. Frozen
projection functions, source clocks, shared activity, pruning and sensitivities
are reused; preprocessing is fixed on nominal training support.
"""
from __future__ import annotations
from collections import Counter
from datetime import date,timedelta
from pathlib import Path
import argparse,bisect,csv,hashlib,importlib.util,json,math,os,sys,tempfile,itertools
import numpy as np
import pandas as pd
from runtime import (CONF,PROJ,STATE,conf_module,read_json,file_identity,atomic_json,
    validate_permit,install_audit,sha256,verify_identities,exclusive_lock)
from nrx_adapter import load_final3,load_corrected_rule,normalize_notices,laz_asof,load_host_notices
from embedding_adapter import build_encoder,encode_cached
from feature_storage import require_disk_space,FEATURE_HEADROOM_BYTES,verify_bundle
from a1_scoring import require_a1_dispositions
f=conf_module('features');require_execution=conf_module('guard').require_execution
NEWS_ARMS=('N','M','L_count','L_chen','E_raw','W_Bai','M_shift','P_shift','P_content')
NOTICE_ARMS=('N','M_notice','L14','L_Laz','L_chen_notice','R','T','M_shift_notice','P_shift','P_content','NP','NPL','NPP','NPM')
# CONFX5 (CONF-A1 decision 4): W2_D is registered beside NEWS_ARMS. It is yielded only
# with a non-empty scale-matched vocabulary; the frozen CONFX3 storage proof enumerates
# NEWS_ARMS without one. NPM (decision 7) joins NOTICE_ARMS inside the E3 branch.
NEWS_A1_ARMS=('W2_D',)
W2D_CANDIDATE_SIZES=(('title',456),('body',550))
W2D_GRANGER_LAG=30
W2D_CORPUS_ISSUE_DAYS=('2021-10-01','2024-12-31')
W2D_PRICE_DAYS=('2021-10-01','2024-12-30')
W2D_LABEL_CUTOFF='2024-12-31T14:00:00Z'
W2D_RULE={'source':'CONF/CONFX5/SPEC.md section 1; NEWSSEC/w2_selection.py (W2 candidate step); Bai et al., IEEE TPWRS 39 (2024) pp. 6224-6225',
    'corpus':'union of unique articles admitted by the frozen 72-hour saved-version rule at 00:00 AEST issues 2021-10-01..2024-12-31, all extraction states',
    'tokens':'frozen features.bai_tokens with the hash-checked TFN2 stopwords; title and body separately',
    'candidates':'descending training-corpus count, ascending token tie break; exactly 456 title and 550 body tokens; fewer gives the candidate gate',
    'price_days':list(W2D_PRICE_DAYS),'label_cutoff_utc':W2D_LABEL_CUTOFF,
    'price_series':'frozen W_Bai daily price: mean over NSW1/QLD1/TAS1 of each region mean of 72 legal labels per day',
    'word_series':'sum of field counts over the frozen 72-hour support at 00:00 AEST of each price day',
    'stationarity':'frozen _stationary (ADF constant, AIC lag; difference once if p >= .05)',
    'granger':'frozen _granger, fixed lag 30 in both directions; keep iff forward p < .05 <= reverse p',
    'column_order':'title then body, each lexicographic'}
# File names written by the notice pass of _write_bundles/notice_feature_rows. A stale
# copy from an earlier attempt must be moved out of host_state/features before a rerun.
NOTICE_DERIVED_FILES=('notice_joint.parquet','notice__shared_numeric.npy','notice_coverage.jsonl',
    'notice_P_content_matched.npy','NOTICE_DERIVED_DATE_SIDECARS.json')


def notice_derived_feature_files(features_root):
    """CONFX5 restart rule from file names only (no file is opened): every notice-derived
    output, plus top-level temporary files left by an interrupted atomic write."""
    root=Path(features_root);selected=[]
    for path in sorted(root.iterdir()) if root.exists() else ():
        if not path.is_file() and not path.is_symlink():continue
        name=path.name
        if (name in NOTICE_DERIVED_FILES or name.endswith('.tmp') or
                (name.startswith('notice__') and (name.endswith('.extras.npy') or name.endswith('.feature_order.json')))):
            selected.append(path)
    return selected


def import_pure(path,name):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


def load_news_articles(*,permit):
    require_execution(permit)
    bank=PROJ/'autopilot/q1_audits/NEWSX';extension=CONF/'newsx_extension'
    prep=import_pure(bank/'prepare_newsx.py','_confx2_news_prep')
    # This frozen loader verifies all source vintages and duplicate semantics.
    posts,_,_=prep.load_posts()
    extra_posts=read_json(extension/'source_posts.json')
    result={}
    for root,source in ((bank,posts),(extension,extra_posts)):
        receipt=read_json(root/'EXTRACTION_RECEIPT.json')
        failed=set(map(str,receipt['failed_article_ids']))
        labels=pd.read_parquet(root/'labels.parquet')
        if labels.article_id.astype(str).duplicated().any():raise ValueError('News labels duplicate IDs')
        joined={str(r['article_id']):r for r in labels.to_dict('records')}
        with (root/'article_manifest.csv').open(newline='') as stream:
            for row in csv.DictReader(stream):
                aid=str(row['article_id'])
                if aid not in source:raise ValueError('Frozen source article absent: '+aid)
                post=source[aid];title=prep.plain(post['title']['rendered']);body=prep.plain(post['content']['rendered'])
                text=title+'\n\n'+body
                if hashlib.sha256(text.encode()).hexdigest()!=row['article_text_sha256']:
                    raise ValueError('News normalized source hash drift: '+aid)
                status='TERMINAL_FAILURE' if aid in failed else 'SUCCESS'
                if (status=='SUCCESS')!=(aid in joined):raise ValueError('News label/failure partition drift')
                article={**row,**joined.get(aid,{}),'article_id':aid,'title':title,'body':body,'extraction_status':status}
                if aid in result:
                    prior=result[aid]
                    if any(str(prior[k])!=str(article[k]) for k in ('article_text_sha256','publication_utc','modified_utc','saved_version_available_utc')):
                        raise ValueError('Conflicting news article version: '+aid)
                    # The original NEWSX bank owns duplicated immutable source
                    # versions. Its labels remain unchanged; redundant extension
                    # labels are retained as provenance and never arbitrated by
                    # label/status values. This original-first ownership is fixed
                    # before values by the existing-training-label reuse rule.
                    prior.setdefault('redundant_extension_source_versions',[]).append({
                        'bank':str(root),'article_id':aid,'source_text_sha256':row['article_text_sha256']})
                else:result[aid]=article
    return sorted(result.values(),key=lambda a:(f.utc(a['saved_version_available_utc']),a['article_id']))


def _stationary(values):
    from statsmodels.tsa.stattools import adfuller
    x=np.asarray(values,dtype=np.float64)
    info={'adf_p':None,'differenced':False,'reason':None}
    if len(x)<4 or not np.isfinite(x).all() or np.ptp(x)==0:
        return None,{**info,'reason':'CONSTANT_OR_NONFINITE_OR_SHORT'}
    try:
        p=float(adfuller(x,regression='c',autolag='AIC')[1]);changed=p>=.05
        z=np.diff(x) if changed else x
        if not np.isfinite(z).all() or np.ptp(z)==0:return None,{**info,'adf_p':p,'differenced':changed,'reason':'CONSTANT_AFTER_ADF'}
        return z,{**info,'adf_p':p,'differenced':changed}
    except (ValueError,np.linalg.LinAlgError) as exc:
        return None,{**info,'reason':type(exc).__name__}


def _granger(target,predictor,lag):
    from scipy.stats import f as fd
    n=len(target)
    if len(predictor)!=n or n-lag<=2*lag+1:return None
    y=np.asarray(target)[lag:];yp=np.column_stack([target[lag-i:n-i] for i in range(1,lag+1)])
    xp=np.column_stack([predictor[lag-i:n-i] for i in range(1,lag+1)])
    r=np.column_stack([np.ones(len(y)),yp]);u=np.column_stack([r,xp])
    if np.linalg.matrix_rank(u)<u.shape[1]:return None
    ru=np.linalg.lstsq(u,y,rcond=None)[0];rr=np.linalg.lstsq(r,y,rcond=None)[0]
    rssu=float(np.square(y-u@ru).sum());rssr=float(np.square(y-r@rr).sum());df=len(y)-u.shape[1]
    if rssu<=0 or df<=0:return None
    return float(fd.sf(max(0.,(rssr-rssu)/lag)/(rssu/df),lag,df))


def bilateral_aic(values,prices,lag_candidates=(1,7,30,90)):
    """ADF constant/AIC, one differencing, bivariate OLS AIC and bilateral F."""
    from statsmodels.tsa.api import VAR
    x,xa=_stationary(values);y,ya=_stationary(prices)
    out={'word_adf':xa,'price_adf':ya,'lag_aic':[],'lag':None,'forward_p':None,'reverse_p':None}
    if x is None or y is None:return out
    length=min(len(x),len(y));x=x[-length:];y=y[-length:]
    fits=[]
    for lag in lag_candidates:
        try:
            fit=VAR(np.column_stack([y,x])).fit(lag,trend='c')
            aic=float(fit.aic)
            if math.isfinite(aic) and length-lag>2*lag+1:fits.append((aic,lag))
            out['lag_aic'].append({'lag':lag,'aic':aic if math.isfinite(aic) else None,'state':'AVAILABLE'})
        except (ValueError,np.linalg.LinAlgError) as exc:
            out['lag_aic'].append({'lag':lag,'aic':None,'state':type(exc).__name__})
    if not fits:return out
    _,lag=min(fits,key=lambda z:(z[0],z[1]));out.update(lag=lag,forward_p=_granger(y,x,lag),reverse_p=_granger(x,y,lag))
    return out


def select_news_vocabulary(panel,articles,stopwords,*,permit):
    require_execution(permit)
    training=panel.loc[panel.target_day.astype(str).between('2021-10-01','2024-12-31')].copy()
    training=training.loc[pd.to_datetime(training.label_available,utc=True)<pd.Timestamp('2024-12-31T14:00:00Z')]
    days=pd.date_range('2021-10-01','2024-12-31',freq='D').date
    expected=set(map(str,days));regions=('NSW1','QLD1','TAS1')
    points=training[['target_day','region','horizon','y']]
    if points.duplicated(['target_day','region','horizon']).any():
        return {'state':'BAI_UNAVAILABLE_TRAINING_PRICE_PREREQUISITE','reason':'duplicate nominal training price key','vocabulary':{'title':[],'body':[]},'audit':[]}
    prices=[]
    for day in days:
        frame=points.loc[points.target_day.astype(str)==str(day)]
        if len(frame)!=72 or set(frame.region)!=set(regions) or not np.isfinite(frame.y.to_numpy()).all():
            return {'state':'BAI_UNAVAILABLE_TRAINING_PRICE_PREREQUISITE','reason':'incomplete observed daily three-region training prices','vocabulary':{'title':[],'body':[]},'audit':[]}
        prices.append(float(frame.groupby('region').y.mean().reindex(regions).mean()))
    admitted=[];supports=[];seen=set()
    for day in days:
        issue=pd.Timestamp(str(day),tz='Australia/Brisbane').tz_convert('UTC')
        support=f.news_support(articles,issue,permit=permit)
        supports.append(support)
        for a in support:
            aid=str(a['article_id'])
            if aid not in seen:admitted.append({**a,'first_admitted_issue_aest':str(day)});seen.add(aid)
    corpus={field:Counter() for field in ('title','body')}
    for doc in admitted:
        for field in corpus:corpus[field].update(f.bai_tokens(doc[field],stopwords))
    selected={'title':[],'body':[]};audit=[]
    for field,threshold in (('title',200),('body',5000)):
        for word in sorted(w for w,n in corpus[field].items() if n>=threshold):
            series=[sum(f.bai_tokens(a[field],stopwords)[word] for a in support) for support in supports]
            row=bilateral_aic(series,prices)
            good=(row['forward_p'] is not None and row['reverse_p'] is not None and row['forward_p']<.05<=row['reverse_p'])
            audit.append({**row,'field':field,'word':word,'training_count':int(corpus[field][word]),'threshold':threshold,'selected':bool(good)})
            if good:selected[field].append(word)
    return {'state':'AVAILABLE' if any(selected.values()) else 'BAI_UNAVAILABLE_EMPTY_VOCABULARY',
        'vocabulary':selected,'audit':audit,'nominal_training_days':len(days),'unique_training_articles':len(admitted)}


def _finite_or_none(value):
    return float(value) if value is not None and math.isfinite(float(value)) else None


def _w2d_unavailable(state,reason,**extra):
    return {'state':state,'reason':reason,'vocabulary':{'title':[],'body':[]},'audit':[],'rule':W2D_RULE,**extra}


def select_w2d_vocabulary(panel,articles,stopwords,*,permit):
    """CONF-A1 decision 4: scale-matched Bai vocabulary (W2 rule) on frozen CONF training data.

    Training-only statistics: texts admitted at the 2021-10-01..2024-12-31 issues and labels of
    2021-10-01..2024-12-30 available before 2024-12-31T14:00Z. No 2025/2026 value is used.
    """
    require_execution(permit)
    regions=('NSW1','QLD1','TAS1')
    days=pd.date_range(*W2D_PRICE_DAYS,freq='D').strftime('%Y-%m-%d').tolist()
    training=panel.loc[panel.target_day.astype(str).between(*W2D_PRICE_DAYS)]
    training=training.loc[pd.to_datetime(training.label_available,utc=True)<pd.Timestamp(W2D_LABEL_CUTOFF)]
    points=training[['target_day','region','horizon','y']].copy();points['target_day']=points.target_day.astype(str)
    if points.duplicated(['target_day','region','horizon']).any():
        return _w2d_unavailable('W2_D_UNAVAILABLE_TRAINING_PRICE_PREREQUISITE','duplicate nominal training price key')
    groups={day:frame for day,frame in points.groupby('target_day',sort=True)}
    prices=[]
    for day in days:
        frame=groups.get(day)
        if frame is None or len(frame)!=72 or set(frame.region)!=set(regions) or not np.isfinite(frame.y.to_numpy()).all():
            return _w2d_unavailable('W2_D_UNAVAILABLE_TRAINING_PRICE_PREREQUISITE',
                'incomplete observed daily three-region training prices on '+day)
        prices.append(float(frame.groupby('region').y.mean().reindex(regions).mean()))
    issues=pd.date_range(*W2D_CORPUS_ISSUE_DAYS,freq='D').strftime('%Y-%m-%d').tolist()
    supports=[];admitted={}
    for day in issues:
        issue=pd.Timestamp(day,tz='Australia/Brisbane').tz_convert('UTC')
        support=f.news_support(articles,issue,permit=permit)
        supports.append([str(a['article_id']) for a in support])
        for a in support:admitted.setdefault(str(a['article_id']),a)
    tokens={aid:{field:f.bai_tokens(a[field],stopwords) for field in ('title','body')} for aid,a in admitted.items()}
    corpus={field:Counter() for field in ('title','body')}
    for aid in sorted(tokens):
        for field in corpus:corpus[field].update(tokens[aid][field])
    eligible={field:len(corpus[field]) for field in corpus}
    identity={'corpus_issue_days':len(issues),'training_price_days':len(days),'first_price_day':days[0],'last_price_day':days[-1],
        'unique_training_articles':len(admitted),'eligible_distinct_tokens':eligible,
        'training_article_ids_sha256':hashlib.sha256(json.dumps(sorted(admitted),separators=(',',':')).encode()).hexdigest(),
        'training_prices_float64_le_sha256':hashlib.sha256(np.asarray(prices,dtype='<f8').tobytes()).hexdigest()}
    candidates={}
    for field,size in W2D_CANDIDATE_SIZES:
        ranked=sorted(corpus[field],key=lambda word:(-corpus[field][word],word))
        if len(ranked)<size:
            return _w2d_unavailable('W2_D_UNAVAILABLE_CANDIDATE_GATE',
                f'{field}: {len(ranked)} eligible distinct tokens < registered size {size}',**identity)
        candidates[field]=ranked[:size]
    # Exact integer counts over the frozen 72-hour supports of the price days.
    series={}
    for field,_ in W2D_CANDIDATE_SIZES:
        column={word:j for j,word in enumerate(candidates[field])}
        sparse={aid:[(column[word],count) for word,count in tokens[aid][field].items() if word in column] for aid in tokens}
        matrix=np.zeros((len(days),len(column)),dtype=np.float64)
        for t,ids in enumerate(supports[:len(days)]):
            for aid in ids:
                for j,count in sparse[aid]:matrix[t,j]+=count
        series[field]=(column,matrix)
    price_z,price_adf=_stationary(prices)
    audit=[];selected={'title':[],'body':[]}
    for field,size in W2D_CANDIDATE_SIZES:
        column,matrix=series[field];rank={word:r for r,word in enumerate(candidates[field],1)}
        for word in sorted(candidates[field]):
            x,x_adf=_stationary(matrix[:,column[word]])
            forward=reverse=None
            if x is not None and price_z is not None:
                length=min(len(x),len(price_z))
                forward=_granger(price_z[-length:],x[-length:],W2D_GRANGER_LAG)
                reverse=_granger(x[-length:],price_z[-length:],W2D_GRANGER_LAG)
            forward,reverse=_finite_or_none(forward),_finite_or_none(reverse)
            good=forward is not None and reverse is not None and forward<.05<=reverse
            audit.append({'field':field,'word':word,'training_count':int(corpus[field][word]),'candidate_rank':rank[word],
                'candidate_set_size':size,'word_adf':{**x_adf,'adf_p':_finite_or_none(x_adf.get('adf_p'))},
                'lag':W2D_GRANGER_LAG,'forward_p':forward,'reverse_p':reverse,'selected':bool(good)})
            if good:selected[field].append(word)
    available=any(selected.values())
    return {'state':'AVAILABLE' if available else 'W2_D_UNAVAILABLE_EMPTY_VOCABULARY',
        'reason':None if available else 'no candidate passed the fixed-lag bilateral Granger screen',
        'vocabulary':selected,'audit':audit,'rule':W2D_RULE,'candidate_sizes':dict(W2D_CANDIDATE_SIZES),
        'daily_price_adf':{**price_adf,'adf_p':_finite_or_none(price_adf.get('adf_p'))},**identity}


def load_notice_vocabulary(*,permit):
    require_execution(permit)
    selected=read_json(PROJ/'autopilot/q1_audits/TFN2/corrected/selection/C.json')
    vocabulary={'title':[],'body':[]}
    for key in selected['selected']:
        field,word=key.split('__',1)
        if field not in vocabulary:raise ValueError('TFN2 frozen field drift')
        vocabulary[field].append(word)
    return vocabulary


def fixed_pruning(matrix,train_mask,columns,chunk=10000):
    """Remove constant/all-missing columns using nominal training only."""
    lows=np.full(len(columns),np.inf);highs=np.full(len(columns),-np.inf);observed=np.zeros(len(columns),dtype=np.int64)
    indices=np.flatnonzero(train_mask)
    if not len(indices):raise ValueError('No frozen preprocessing-training rows')
    for i in range(0,len(indices),chunk):
        block=np.asarray(matrix[indices[i:i+chunk]],dtype=np.float32)
        finite=np.isfinite(block)
        if np.isinf(block).any():raise ValueError('Infinite feature value')
        observed+=finite.sum(0)
        if isinstance(matrix,np.memmap):_evict(matrix)
        lows=np.minimum(lows,np.where(finite,block,np.inf).min(0));highs=np.maximum(highs,np.where(finite,block,-np.inf).max(0))
    keep=np.flatnonzero((observed>0)&(highs>lows))
    return keep,[c for i,c in enumerate(columns) if i not in set(keep)]


def news_derived_date_sidecar(article,absolute_interval,*,permit,shift_days=0,recipient_publication=None):
    require_execution(permit)
    statements=article.get('statements_json',[])
    if isinstance(statements,str):statements=json.loads(statements)
    if article.get('extraction_status')!='SUCCESS':statements=[]
    rows=[]
    for index,statement in enumerate(statements):
        literal=statement.get('event_time_text','Unknown');interval=absolute_interval(literal)
        parsed={'statement_index':index,'raw_event_time_text':literal,
            'state':'PARSED_ABSOLUTE_DATE' if interval else 'UNKNOWN_OR_UNPARSED'}
        if interval:
            derived={'event_start_date':interval[0],'event_end_date':interval[1]}
            if statement.get('kind')=='FORECAST':derived['forecast_target_date']=interval[0]
            if shift_days:derived=f.shift_normalized_clocks(derived,permit=permit)
            if recipient_publication is not None:
                derived=f.relocate_content_dates(derived,article['publication_utc'],recipient_publication,permit=permit)
            parsed.update({key:str(value) for key,value in derived.items()})
        rows.append(parsed)
    clocks={key:article[key] for key in ('publication_utc','modified_utc','saved_version_available_utc') if key in article}
    if shift_days:clocks=f.shift_normalized_clocks(clocks,permit=permit)
    return {'source_article_id':str(article['article_id']),'donor_article_id':article.get('donor_document_id'),
        'shift_days':shift_days,
        'derived_source_clocks':{key:str(value) for key,value in clocks.items()},'statements':rows,
        'attribute_date_literals':'UNCHANGED_RAW_DONOR_PROVENANCE; unsupported dates remain unparsed'}


def notice_derived_date_sidecars(records,*,permit,shift_days=0,donor_publication=None,recipient_publication=None):
    require_execution(permit)
    output=[]
    for row in records.to_dict('records'):
        derived={key:row[key] for key in ('available_utc','start_utc','end_utc','action_effective_utc')
            if pd.notna(row.get(key))}
        if shift_days:derived=f.shift_normalized_clocks(derived,permit=permit)
        if recipient_publication is not None:
            derived=f.relocate_content_dates(derived,donor_publication,recipient_publication,permit=permit)
        output.append({'notice_id':str(row['notice_id']),'window_id':row.get('nrx_window_id'),
            'derived_dates':{key:str(value) for key,value in derived.items()},
            'raw_start_text':row.get('raw_start_text'),'raw_end_text':row.get('raw_end_text'),
            'temporal_status':row.get('temporal_status'),'shift_days':shift_days})
    return output


def _bundle(origin,region,support,id_key,clock_key):
    return {'bundle_id':str(origin)+'|'+str(region),'issue_utc':str(origin),'region':region,
        'document_count':len(support),'source_document_ids':[str(a[id_key]) for a in support],
        'extraction_status_mask':[a['extraction_status'] for a in support],
        'latest_content_available_utc':str(max((f.utc(a[clock_key]) for a in support),default=f.utc(origin))),
        'support':support}


def _permuted_support(recipient,history,*,permit,id_key,clock_key,publication_key):
    donor,side=f.activity_matched_donor(recipient,history,permit=permit)
    if donor is None:return None,side
    if any(f.utc(a[clock_key])>=f.utc(recipient['issue_utc']) for a in donor['support']):
        raise ValueError('P_content donor violates strict before-origin contract')
    output=[]
    for slot,content in zip(recipient['support'],donor['support'],strict=True):
        if slot['extraction_status']!=content['extraction_status']:raise ValueError('P_content missing-state drift')
        # Only semantic/raw content transfers. Source slot clocks/IDs and failure
        # state remain recipient; parsed temporal sidecars transfer by offset.
        moved={**content,**{k:slot[k] for k in (id_key,clock_key,publication_key,'publication_utc','modified_utc','saved_version_available_utc','available_utc') if k in slot}}
        moved['extraction_status']=slot['extraction_status']
        moved['donor_document_id']=content[id_key]
        moved['donor_publication_utc']=content.get(publication_key,content[clock_key])
        moved['recipient_publication_utc']=slot.get(publication_key,slot[clock_key])
        output.append(moved)
    side={**side,'donor_bundle_id':donor['bundle_id'],
        'donor_source_document_ids':donor['source_document_ids'],
        'recipient_source_document_ids':recipient['source_document_ids'],
        'donor_issue_utc':donor['issue_utc'],'recipient_issue_utc':recipient['issue_utc'],
        'reuse_disclosed':'Repeated donor source-ID tuples across coverage rows are retained'}
    return output,side


def news_feature_rows(panel,articles,*,permit,encoder,cache_directory,absolute_interval,
                      vocabulary,stopwords,w2_vocabulary=None):
    require_execution(permit)
    w2_active=w2_vocabulary is not None and any(w2_vocabulary.values())
    history={region:[] for region in ('NSW1','QLD1','TAS1')}
    for origin,frame in panel.groupby('origin',sort=True):
        target_day=date.fromisoformat(str(frame.target_day.iloc[0])[:10])
        supports={hours:f.news_support(articles,origin,permit=permit,hours=hours) for hours in (72,24)}
        shifted=f.news_support(articles,origin,permit=permit,shift_days=28)
        for region,regional in frame.groupby('region',sort=True):
            support=supports[72];meta=f.news_metadata(support,permit=permit);shiftmeta=f.news_metadata(shifted,permit=permit)
            extras={('N','main'):{},('M','main'):meta,('M_shift','main'):shiftmeta}
            count=f.news_count(support,target_day,absolute_interval,permit=permit)
            extras[('L_count','main')]={**meta,**count}
            text=f.chen_news_text(support,permit=permit);raw=f.raw_news_text(support,permit=permit)
            reports={}
            for arm,serialized in (('L_chen',text),('E_raw',raw),('P_shift',f.chen_news_text(shifted,permit=permit))):
                vector,report=encode_cached(encoder,serialized,cache_directory,permit=permit)
                base=shiftmeta if arm=='P_shift' else meta
                extras[(arm,'main')]={**base,**{f'emb_{j:03d}':v for j,v in enumerate(vector)}};reports[arm]=report
                if arm in ('L_chen','E_raw'):
                    vec,report=encode_cached(encoder,serialized,cache_directory,permit=permit,first_chunk_only=True)
                    extras[(arm,'first_L')]={**meta,**{f'emb_{j:03d}':v for j,v in enumerate(vec)}};reports[arm+'__first_L']=report
            if any(vocabulary.values()):extras[('W_Bai','main')]={**meta,**f.bai_counts(support,vocabulary,stopwords,permit=permit)}
            # CONFX5: the same frozen count projection with the scale-matched vocabulary.
            if w2_active:extras[('W2_D','main')]={**meta,**f.bai_counts(support,w2_vocabulary,stopwords,permit=permit)}
            narrow=supports[24];m24=f.news_metadata(narrow,permit=permit)
            extras[('M','24h')]=m24
            extras[('L_count','24h')]={**m24,**f.news_count(narrow,target_day,absolute_interval,permit=permit)}
            vector,report=encode_cached(encoder,f.chen_news_text(narrow,permit=permit),cache_directory,permit=permit)
            extras[('L_chen','24h')]={**m24,**{f'emb_{j:03d}':v for j,v in enumerate(vector)}}
            recipient=_bundle(origin,region,support,'article_id','saved_version_available_utc')
            permuted,permutation=_permuted_support(recipient,history[region],permit=permit,
                id_key='article_id',clock_key='saved_version_available_utc',publication_key='publication_utc')
            if permuted is None:vector=np.zeros(384,dtype=np.float32)
            else:vector,_=encode_cached(encoder,f.chen_news_text(permuted,permit=permit),cache_directory,permit=permit)
            extras[('P_content','main')]={**meta,**{f'emb_{j:03d}':v for j,v in enumerate(vector)}}
            history[region].append(recipient)
            yield regional.index.to_numpy(),extras,{'origin':str(origin),'region':region,
                'raw_candidates':len(articles),'clock_admitted':len(support),
                'valid_labels':sum(a['extraction_status']=='SUCCESS' for a in support),
                'failed_labels':meta['extraction_failed_count'],'source_ids':[a['article_id'] for a in support],
                'embeddings':reports,'P_content':permutation,
                'P_shift_derived_dates':[news_derived_date_sidecar(a,absolute_interval,permit=permit,shift_days=28) for a in shifted],
                'P_content_derived_dates':[] if permuted is None else [news_derived_date_sidecar(
                    {**moved,'publication_utc':moved['donor_publication_utc']},absolute_interval,permit=permit,
                    recipient_publication=moved['recipient_publication_utc']) for moved in permuted]}



def _active_laz(resolved,issue,target_min,target_max):
    """Outcome-independent broad interval prefilter before exact frozen overlap."""
    issue=pd.Timestamp(issue)
    eligible=resolved.feature_eligible.astype(bool)&(resolved.available_utc<=issue)&~resolved.cancel
    eligible&=resolved.start_utc.notna()&(resolved.start_utc<target_max)
    eligible&=(resolved.end_utc.isna()|(resolved.end_utc>target_min-pd.Timedelta(minutes=5)))
    if 'close_utc' in resolved:eligible&=resolved.close_utc.isna()|(resolved.close_utc>issue)
    eligible&=~((resolved.temporal_status=='OPEN_UNTIL_NOTICE')&((issue-resolved.available_utc)>=pd.Timedelta(hours=48)))
    return resolved.loc[eligible]


def notice_feature_rows(panel,notices,*,permit,encoder,cache_directory,final3,corrected_rule,
                        vocabulary,stopwords,p5min_columns=()):
    require_execution(permit)
    records,sides=normalize_notices(notices,final3,permit=permit)
    sidecar_root=Path(cache_directory).parent
    atomic_json(sidecar_root/'NOTICE_DERIVED_DATE_SIDECARS.json',{
        'state':'COMPLETE','original':notice_derived_date_sidecars(records,permit=permit),
        'shift28':notice_derived_date_sidecars(records,permit=permit,shift_days=28),
        'P_content':'NO_VALID_PERMUTATION_FULL_PREFIX_NESTING',
        'source_literals_unchanged':True,
        'prefix_scope_status':'OBSERVED_SAVED_SOURCE_PREFIX_NOT_ALL_ISSUED_CENSUS',
        'cross_gap_unclosed_open_state':'UNKNOWN_AFTER_FROZEN_48H_ISSUE_FRESHNESS',
        'bounded_schedules':'RETAIN_SOURCE_SUPPORTED_BOUNDS_WITHOUT_AGE_CAP'})
    resolved=final3.resolve_event_states(records)
    keys=panel[['origin','target_time','region']].rename(columns={'origin':'issue_time'})
    l14=f.l14_projection(records,keys,final3.features,permit=permit)
    shifted_records=final3.shifted(records,28)
    shifted_l14=f.l14_projection(shifted_records,keys,final3.features,permit=permit)
    pop=pd.DataFrame([{'notice_id':n['notice_id'],'title':n.get('title',''),
        'text':n.get('body',n.get('text','')),'notice_type':n.get('notice_type',n.get('source_notice_type','')),
        'available_utc':pd.Timestamp(n['available_utc']),
        'anchor_local':pd.Timestamp(n.get('anchor_local') or pd.Timestamp(n['available_utc']).tz_convert('Australia/Brisbane').tz_localize(None))}
        for n in notices])
    rrecords=corrected_rule.rule_records(pop,reject_partial_year=True,completed_recovery=True)
    rule=corrected_rule.features(keys,rrecords)
    history={r:[] for r in f.REGIONS}
    notice_clocks=[f.utc(n['available_utc']) for n in notices]
    failures=np.r_[0,np.cumsum([n['extraction_status']!='SUCCESS' for n in notices])]
    side_lookup={(side['notice_id'],side['nrx_window_id']):side for side in sides}
    last_end=last_shift_end=-1
    main_vec=first_vec=shift_vec=None
    main_report=first_report=None
    for origin,frame in panel.groupby('origin',sort=True):
        now=f.utc(origin);end=bisect.bisect_right(notice_clocks,now)
        shift_now=now-timedelta(days=28);shift_end=bisect.bisect_right(notice_clocks,shift_now)
        # These ID-only cumulative counts are algebraically identical to the
        # frozen distinct-ID prefix/strict-left6h projection on unique sources.
        meta={'notice_prefix_count':end,'notice_arrivals_6h':end-bisect.bisect_right(notice_clocks,now-timedelta(hours=6)),
            'notice_failed_prefix_count':int(failures[end])}
        shiftmeta={'notice_prefix_count':shift_end,'notice_arrivals_6h':shift_end-bisect.bisect_right(notice_clocks,shift_now-timedelta(hours=6)),
            'notice_failed_prefix_count':int(failures[shift_end])}
        if end!=last_end:
            prefix=notices[:end];serialized=f.chen_notice_text(prefix,permit=permit)
            main_vec,main_report=encode_cached(encoder,serialized,cache_directory,permit=permit)
            first_vec,first_report=encode_cached(encoder,serialized,cache_directory,permit=permit,first_chunk_only=True)
            last_end=end
        if shift_end!=last_shift_end:
            shifted=notices[:shift_end]
            shift_vec,_=encode_cached(encoder,f.chen_notice_text(shifted,permit=permit),cache_directory,permit=permit)
            last_shift_end=shift_end
        raw24=notices[bisect.bisect_right(notice_clocks,now-timedelta(hours=24)):end]
        t=f.notice_tfn2_counts(raw24,origin,vocabulary,stopwords,permit=permit)
        active=_active_laz(resolved,origin,frame.target_time.min(),frame.target_time.max())
        active_keys=set(zip(active.notice_id.astype(str),active.nrx_window_id.astype(str)))
        active_sides=[side_lookup[key] for key in active_keys]
        for region,regional in frame.groupby('region',sort=True):
            # Full canonical prefixes are nested. Equal counts imply identical
            # IDs, which the frozen donor rule excludes. Therefore no distinct
            # same-count earlier notice prefix can meet the donor requirement.
            # Retain finite placeholders and explicit unmatched keys; do not
            # substitute a rolling activity cohort or relax the stratum.
            perm_side={'state':'UNMATCHED','eligible_donors':0,
                'reason':'NESTED_FULL_PREFIX_EQUAL_COUNT_IMPLIES_IDENTICAL_SOURCE_IDS'}
            perm_vec=np.zeros(384,dtype=np.float32)
            indices=regional.index.to_numpy()
            laz_rows=[];laz_reports=[]
            # At one issue each target/region state is reused by every repeated
            # training row. There are only six registered short horizons.
            by_target={}
            for target in regional.target_time.drop_duplicates():
                output,report=laz_asof(active,active_sides,origin,target,region,permit=permit)
                by_target[target]=(output,report)
            for row in regional.itertuples(index=False):
                output,report=by_target[row.target_time]
                laz_rows.append(output);laz_reports.append({'horizon':int(row.horizon),**report})
            laz_frame=pd.DataFrame(laz_rows,index=indices)
            emb=lambda vec:{f'emb_{j:03d}':v for j,v in enumerate(vec)}
            block=lambda table:{c:table.loc[indices,c].to_numpy(dtype=np.float32) for c in table}
            extras={('N','main'):{},('M_notice','main'):meta,
                ('L14','main'):{**meta,**block(l14)},
                ('L_Laz','main'):{**meta,**block(laz_frame)},('L_chen_notice','main'):{**meta,**emb(main_vec)},
                ('L_chen_notice','first_L'):{**meta,**emb(first_vec)},
                ('R','main'):{**meta,**block(rule)},('T','main'):{**meta,**t},
                ('M_shift_notice','main'):shiftmeta,('P_shift','main'):{**shiftmeta,**emb(shift_vec)},
                ('P_content','main'):{**meta,**emb(perm_vec)}}
            if p5min_columns:
                operator={c:regional[c].to_numpy(dtype=np.float32) for c in p5min_columns}
                extras[('NP','main')]=operator
                extras[('NPL','main')]={**operator,**meta,**block(l14)}
                extras[('NPP','main')]={**operator,**shiftmeta,**block(shifted_l14)}
                # CONFX5 (CONF-A1 decision 7): NPM = NP + M_notice, the activity reference of NPL.
                extras[('NPM','main')]={**operator,**meta}
            yield indices,extras,{'origin':str(origin),'region':region,'horizons':sorted(set(map(int,regional.horizon))),
                'clock_admitted':end,'valid_labels':end-int(failures[end]),
                'failed_labels':meta['notice_failed_prefix_count'],'embeddings':{'L_chen_notice':main_report,'first_L':first_report},
                'L_Laz':laz_reports,'P_content':perm_side,
                'prefix_scope_status':'OBSERVED_SAVED_SOURCE_PREFIX_NOT_ALL_ISSUED_CENSUS',
                'cross_gap_unclosed_open_state':'UNKNOWN_AFTER_FROZEN_48H_ISSUE_FRESHNESS'}



def _source_manifest_columns(manifest,source):
    if isinstance(manifest.get('numeric_columns'),dict):return manifest['numeric_columns']['notices' if source=='notice' else source]
    item=manifest.get(source,manifest.get('panels',{}).get(source,{}))
    if isinstance(item,dict) and 'numeric_columns' in item:return item['numeric_columns']
    for item in manifest.get('files',[]):
        if isinstance(item,dict) and item.get('source')==source and 'numeric_columns' in item:return item['numeric_columns']
    raise ValueError('Panel manifest does not certify numeric column order for '+source)



def _evict(matrix):
    matrix.flush()
    # Dropping resident file pages changes neither matrix bytes nor projection.
    try:
        import mmap
        if hasattr(matrix._mmap,'madvise') and hasattr(mmap,'MADV_DONTNEED'):
            matrix._mmap.madvise(mmap.MADV_DONTNEED)
    except (AttributeError,OSError,ValueError):
        pass

# CONFX6 (execution amendment 4): the auxiliary category (embedding cache, coverage, sidecars,
# feature orders, masks, selections, temporaries) receives a derived reservation that is never a
# stop of its own; the free-space guard of all remaining bytes plus FEATURE_HEADROOM_BYTES is the
# only stop. Measured 2026-10-02 production allocation: 8,192 allocated bytes per cache entry (two
# one-block files), coverage about 786 (notices) and 223 (news) bytes per panel row, sidecars about 13.
AUXILIARY_BYTES_PER_PANEL_ROW=2048
AUXILIARY_RULE='FEATURE_AUXILIARY_ALLOWANCE_DERIVED_RESERVATION_NOT_A_STOP'


class FeatureDiskPlan:
    """Reserve all remaining sources; auxiliary growth cannot spend arrays (CONFX6: and is never a stop)."""
    def __init__(self,out,planned_bytes,*,array_bytes=None,panel_bytes=None,auxiliary_bytes=None):
        self.out=Path(out);self.planned_bytes=int(planned_bytes)
        self.budgets=None if array_bytes is None else (int(array_bytes),int(panel_bytes),int(auxiliary_bytes))
        self.initial_allocated=self.allocated()
        self.auxiliary_overspend_noted=False
    def allocations(self):
        arrays=panels=auxiliary=0
        for p in self.out.rglob('*') if self.out.exists() else ():
            if not p.is_file():continue
            allocated=p.stat().st_blocks*512
            if p.name.endswith('.extras.npy') or p.name.endswith('__shared_numeric.npy'):arrays+=allocated
            elif p.name in {'news_keys_labels.parquet','notice_joint.parquet'}:panels+=allocated
            else:auxiliary+=allocated
        return arrays,panels,auxiliary
    def allocated(self):return sum(self.allocations())
    def check(self,stage):
        allocated=self.allocations()
        if self.budgets is None:
            remaining=max(0,self.planned_bytes-max(0,sum(allocated)-self.initial_allocated))
        else:
            # Remaining arrays and panel copies stay reserved at every checkpoint. Auxiliary bytes
            # above their derived reservation only set that reservation to zero: measured free space
            # already reflects the overspend, and require_disk_space alone decides whether to stop.
            if allocated[2]>self.budgets[2] and not self.auxiliary_overspend_noted:
                print('CONFX6 note at '+stage+': auxiliary files allocate '+format(allocated[2],',')+' bytes, above their '
                      'derived reservation of '+format(self.budgets[2],',')+' bytes; this is not a stop, the free-space '
                      'guard decides.',file=sys.stderr,flush=True)
                self.auxiliary_overspend_noted=True
            remaining=sum(max(0,budget-used) for budget,used in zip(self.budgets,allocated))
        return require_disk_space(self.out,remaining,FEATURE_HEADROOM_BYTES,stage)


def auxiliary_allowance_bytes(out,panel_rows):
    """CONFX6 derived auxiliary reservation: bytes allocated now plus 2,048 bytes per panel row."""
    return int(FeatureDiskPlan(out,0).allocations()[2])+AUXILIARY_BYTES_PER_PANEL_ROW*int(panel_rows)


def registered_extra_widths(source,vocabulary,p5_columns=(),w2_vocabulary=None):
    """Frozen registered dimensions, independent of feature values/pruning."""
    words=sum(len(vocabulary[field]) for field in ('title','body'))
    if source=='news':
        widths={('N','main'):0,('M','main'):2,('L_count','main'):2+len(f.COUNT_COLUMNS),
            ('L_chen','main'):386,('E_raw','main'):386,('M_shift','main'):2,
            ('P_shift','main'):386,('P_content','main'):386,
            ('M','24h'):2,('L_count','24h'):2+len(f.COUNT_COLUMNS),('L_chen','24h'):386,
            ('L_chen','first_L'):386,('E_raw','first_L'):386}
        if words:widths[('W_Bai','main')]=2+words
        w2_words=0 if w2_vocabulary is None else sum(len(w2_vocabulary[field]) for field in ('title','body'))
        if w2_words:widths[('W2_D','main')]=2+w2_words
    else:
        widths={('N','main'):0,('M_notice','main'):3,('L14','main'):3+len(f.L14_COLUMNS),
            ('L_Laz','main'):3+len(f.LAZ_COLUMNS),('L_chen_notice','main'):387,
            ('L_chen_notice','first_L'):387,('R','main'):3+len(f.L14_COLUMNS),
            ('T','main'):3+words,('M_shift_notice','main'):3,('P_shift','main'):387,('P_content','main'):387}
        if p5_columns:
            widths.update({('NP','main'):len(p5_columns),('NPL','main'):len(p5_columns)+3+len(f.L14_COLUMNS),
                           ('NPP','main'):len(p5_columns)+3+len(f.L14_COLUMNS),('NPM','main'):len(p5_columns)+3})
    return widths


def planned_array_bytes(row_count,numeric_count,widths):
    # NPY v1 headers are bounded by 256 bytes for these float32 2-D shapes.
    return int(row_count)*4*(int(numeric_count)+sum(widths.values()))+256*(1+len(widths))


def panel_copy_sha256(panel):
    """CONFX7 resume identity: SHA-256 of the exact bytes `panel.to_parquet(path,index=False,compression='zstd')`
    writes, streamed to a hashing sink (no file is written). `_write_bundles` reuses a stored panel copy only if
    its bytes have this hash. Reading the copy back is not a valid test: pd.concat of the notice training clocks
    (timestamp[us]) and confirmation clocks (timestamp[ns]) leaves `label_available` an object column, which
    read_parquet returns as datetime64[us, UTC] (CONFX7/SPEC_ADDENDUM_2_RESUME_IDENTITY.md)."""
    import io
    class _Sha256Sink(io.RawIOBase):
        def __init__(self):super().__init__();self.digest=hashlib.sha256();self.size=0
        def writable(self):return True
        def write(self,data):
            view=memoryview(data);self.digest.update(view);self.size+=view.nbytes;return view.nbytes
        def tell(self):return self.size
    sink=_Sha256Sink();panel.to_parquet(sink,index=False,compression='zstd')
    return sink.digest.hexdigest()


def _write_bundles(panel,numeric_columns,rows,out,source,train_mask,*,permit,train_rows=None,storage_plan=None):
    require_execution(permit)
    out=Path(out);panel=panel.reset_index(drop=True)
    if 'issue_time' not in panel:panel['issue_time']=panel.origin
    if 'day' not in panel:panel['day']=panel.target_day
    iterator=iter(rows)
    try:first=next(iterator)
    except StopIteration:raise ValueError('Empty feature projection')
    schema={key:list(extra) for key,extra in first[1].items()}
    widths={key:len(names) for key,names in schema.items()}
    if any(set(numeric_columns)&set(names) for names in schema.values()):raise ValueError('Shared/extra column collision')
    if storage_plan is None:
        # The full host supplies one joint two-source plan. Standalone fixtures
        # and callers still guard every remaining bundle before the first write.
        allowance=int(panel.memory_usage(index=False,deep=True).sum())*2+1024**2
        storage_plan=FeatureDiskPlan(out,planned_array_bytes(len(panel),len(numeric_columns),widths)+allowance)
    storage_plan.check('features: all remaining bundles before first '+source+' write')
    out.mkdir(parents=True,exist_ok=True)
    panel_path=out/(source+'_joint.parquet' if source=='notice' else 'news_keys_labels.parquet')
    if not panel_path.exists():panel.to_parquet(panel_path,index=False,compression='zstd')
    elif sha256(panel_path)!=panel_copy_sha256(panel):raise ValueError('Resume panel identity drift')
    shared_path=out/(source+'__shared_numeric.npy')
    if shared_path.exists():
        shared=np.load(shared_path,mmap_mode='r',allow_pickle=False)
        if shared.shape!=(len(panel),len(numeric_columns)) or shared.dtype!=np.float32:raise ValueError('Shared numeric shape drift')
        for start in range(0,len(panel),10000):
            expected=panel.iloc[start:start+10000][numeric_columns].to_numpy(dtype=np.float32)
            if shared[start:start+len(expected)].tobytes()!=expected.tobytes():raise ValueError('Shared numeric bits drift')
    else:
        storage_plan.check('features: shared numeric '+source)
        shared=np.lib.format.open_memmap(shared_path,mode='w+',dtype=np.float32,shape=(len(panel),len(numeric_columns)))
        for start in range(0,len(panel),10000):
            shared[start:start+10000]=panel.iloc[start:start+10000][numeric_columns].to_numpy(dtype=np.float32)
            _evict(shared)
    base_keep,base_pruned=fixed_pruning(shared,train_mask,list(numeric_columns))
    shared_identity=file_identity(shared_path,shape=list(shared.shape),dtype='float32')
    del shared
    matrices={};columns={};coverage_path=out/(source+'_coverage.jsonl');mask=np.zeros(len(panel),dtype=bool)
    for key,names in schema.items():
        storage_plan.check('features: extras '+source+' '+str(key))
        path=out/(source+'__'+key[0]+'__'+key[1]+'.extras.npy')
        if names:matrix=np.lib.format.open_memmap(path,mode='w+',dtype=np.float32,shape=(len(panel),len(names)))
        else:
            np.save(path,np.empty((len(panel),0),dtype=np.float32),allow_pickle=False)
            matrix=np.empty((len(panel),0),dtype=np.float32)
        matrices[key]=(matrix,path);columns[key]=list(numeric_columns)+names
    processed_rows=0
    with coverage_path.open('w') as flow:
        for indices,extras,coverage in itertools.chain([first],iterator):
            if {key:list(extra) for key,extra in extras.items()}!=schema:raise ValueError('Feature arm/column order drift')
            for key,extra in extras.items():
                if extra:
                    block=np.column_stack([np.broadcast_to(np.asarray(value,dtype=np.float32),len(indices)) for value in extra.values()])
                    matrices[key][0][indices,:]=block
            mask[indices]=coverage['P_content']['state']=='MATCHED'
            content_counts={};vector_origins={}
            activity={'article_count','extraction_failed_count','notice_prefix_count','notice_arrivals_6h','notice_failed_prefix_count'}
            for (arm,variant),extra in extras.items():
                values=[np.broadcast_to(np.asarray(value,dtype=np.float32),len(indices)) for name,value in extra.items() if name not in activity and name!='tier_Unknown']
                nonzero=np.any([np.isfinite(value)&(value!=0) for value in values],axis=0) if values else np.zeros(len(indices),bool)
                content_counts[arm+'__'+variant]=int(np.sum(nonzero))
                vectors=[value for name,value in extra.items() if name.startswith('emb_')]
                if vectors:vector_origins[arm+'__'+variant]=int(any(np.isfinite(value) and value!=0 for value in vectors))
            coverage={**coverage,'projection_rows':len(indices),'nonzero_postprojection_content_rows':content_counts,
                'nonzero_vector_origin_region':vector_origins}
            encoded=json.dumps(coverage,default=str,allow_nan=False)+'\n'
            flow.write(encoded)
            processed_rows+=len(indices)
            if processed_rows>=10000:
                storage_plan.check('features: remaining bank after coverage '+source)
                for matrix,_ in matrices.values():
                    if isinstance(matrix,np.memmap):_evict(matrix)
                processed_rows=0
    mask_path=out/(source+'_P_content_matched.npy');np.save(mask_path,mask,allow_pickle=False)
    panel_sha=sha256(panel_path);coverage_sha=sha256(coverage_path);mask_sha=sha256(mask_path)
    bundles=[]
    for key in list(matrices):
        matrix,path=matrices.pop(key)
        if isinstance(matrix,np.memmap):matrix.flush()
        names=columns[key];extra_keep,extra_pruned=fixed_pruning(matrix,train_mask,schema[key])
        keep=[int(i) for i in base_keep]+[len(numeric_columns)+int(i) for i in extra_keep]
        pruned=base_pruned+extra_pruned
        order={'source':source,'arm':key[0],'variant':key[1],'rows':len(panel),'dtype':'float32',
            'shared_columns':list(numeric_columns),'extra_columns':schema[key],
            'original_columns':names,'keep_indices':keep,'columns':[names[i] for i in keep],'pruned_names':pruned}
        order_path=out/(source+'__'+key[0]+'__'+key[1]+'.feature_order.json')
        atomic_json(order_path,order)
        bundles.append({**order,'layout':'shared_numeric_extras_v1','state':'COMPLETE','train_rows':train_rows,
            'preprocessing_training_rows':int(np.sum(train_mask)),
            'matrix':{'shape':[len(panel),len(keep)],'dtype':'float32'},
            'shared_numeric':shared_identity,'extras_matrix':file_identity(path,shape=[len(panel),len(schema[key])],dtype='float32'),
            'feature_order':file_identity(order_path),
            'panel_path':str(panel_path.resolve()),'panel_sha256':panel_sha,
            'coverage_path':str(coverage_path.resolve()),'coverage_sha256':coverage_sha,
            'matched_mask_path':str(mask_path.resolve()) if key[0]=='P_content' else None,
            'matched_mask_sha256':mask_sha if key[0]=='P_content' else None,
            'derived_date_sidecar_path':str((out/'NOTICE_DERIVED_DATE_SIDECARS.json').resolve()) if source=='notice' else None})
        del matrix
    if not mask.any():
        for bundle in bundles:
            if bundle['arm']=='P_content':
                bundle['state']='NO_VALID_PERMUTATION';bundle['reason']='No frozen activity/status-matched distinct earlier donor bundle'
    return bundles


def build_all_features(permit,panels_root,out,input_freeze=None):
    require_execution(permit)
    panels_root=Path(panels_root);out=Path(out);out.mkdir(parents=True,exist_ok=True)
    panel_manifest=read_json(panels_root/'manifest.json')
    if panel_manifest.get('state') not in ('PASS','COMPLETE','PANELS_COMPLETE_VALIDATED'):
        raise ValueError('Panel validation gate is incomplete')
    dependencies=[file_identity(panels_root/'manifest.json')]
    for name in ('news.parquet','notices.parquet','notices_train.parquet'):dependencies.append(file_identity(panels_root/name))
    stamp={'panel_inputs':dependencies,'design_freeze_sha256':permit.design_freeze_sha256,
        'completed_input_manifest_sha256':permit.completed_input_manifest_sha256}
    manifest_path=out/'manifest.json'
    if manifest_path.exists():
        previous=read_json(manifest_path)
        if previous.get('signature')!=stamp:raise ValueError('Feature resume signature drift')
        verify_identities(previous['inputs'])
        for bundle in previous['bundles']:
            if 'shared_numeric' in bundle or bundle.get('state')=='COMPLETE':verify_bundle(bundle)
        # CONFX5: a manifest without the CONF-A1 W2_D/NPM dispositions predates this amendment.
        require_a1_dispositions(previous)
        return previous
    stops_path=PROJ/'autopilot/q1_audits/TFN2/corrected/english_stopwords.txt'
    if sha256(stops_path)!='f6d005956f407dbc6ea32e5ff0c7e8e6f71488d3239b9023efdc7fc139d6375b':raise ValueError('Frozen stopword drift')
    stops=frozenset(stops_path.read_text().splitlines())
    news=pd.read_parquet(panels_root/'news.parquet')
    news['origin']=pd.to_datetime(news.origin,utc=True);news['target_time']=pd.to_datetime(news.target_time,utc=True)
    news['target_day']=news.target_day.astype(str).str[:10]
    articles=load_news_articles(permit=permit)
    vocabulary_path=out/'W_Bai_selection.json'
    if vocabulary_path.exists():vocabulary=read_json(vocabulary_path)
    else:
        vocabulary=select_news_vocabulary(news,articles,stops,permit=permit)
    # CONFX5: the registered scale-matched vocabulary, selected once and then reused.
    w2_path=out/'W2_D_selection.json'
    if w2_path.exists():w2=read_json(w2_path)
    else:w2=select_w2d_vocabulary(news,articles,stops,permit=permit)
    import pyarrow.parquet as pq
    p5cols=panel_manifest.get('p5_columns',panel_manifest.get('p5min_columns',[]))
    legal_p5=p5cols if panel_manifest.get('e3_state','READY')=='READY' else ()
    notice_vocabulary=load_notice_vocabulary(permit=permit)
    notice_rows=pq.ParquetFile(panels_root/'notices_train.parquet').metadata.num_rows+pq.ParquetFile(panels_root/'notices.parquet').metadata.num_rows
    array_bytes=planned_array_bytes(len(news),len(_source_manifest_columns(panel_manifest,'news')),
        registered_extra_widths('news',vocabulary['vocabulary'],w2_vocabulary=w2['vocabulary']))+planned_array_bytes(notice_rows,
        len(_source_manifest_columns(panel_manifest,'notice')),registered_extra_widths('notice',notice_vocabulary,legal_p5))
    # Uncompressed parquet sizes bound the single panel copies. Additional
    # sidecars/cache are reserved conservatively and checked again as they grow.
    panel_bytes=sum(max((panels_root/name).stat().st_size,
        sum(pq.ParquetFile(panels_root/name).metadata.row_group(i).total_byte_size
            for i in range(pq.ParquetFile(panels_root/name).metadata.num_row_groups)))
        for name in ('news.parquet','notices_train.parquet','notices.parquet'))
    # CONFX6: a derived auxiliary reservation replaces the fixed 512 MiB stop (see FeatureDiskPlan).
    panel_rows={'news':len(news),'notice':notice_rows}
    auxiliary_bytes=auxiliary_allowance_bytes(out,sum(panel_rows.values()))
    planned=array_bytes+2*panel_bytes+auxiliary_bytes
    storage_plan=FeatureDiskPlan(out,planned,array_bytes=array_bytes,panel_bytes=2*panel_bytes,auxiliary_bytes=auxiliary_bytes)
    storage_plan.check('features: complete news and notice bank, before cache or bundle writes')
    atomic_json(out/'DISK_PLAN.json',{'array_bytes':array_bytes,'panel_copy_allowance_bytes':2*panel_bytes,
        'auxiliary_rule':AUXILIARY_RULE,'auxiliary_reservation_bytes':auxiliary_bytes,
        'auxiliary_allocated_at_plan_bytes':auxiliary_bytes-AUXILIARY_BYTES_PER_PANEL_ROW*sum(panel_rows.values()),
        'auxiliary_bytes_per_panel_row':AUXILIARY_BYTES_PER_PANEL_ROW,'panel_rows':panel_rows,
        'auxiliary_reservation_is_a_stop':False,'planned_bytes':planned,'headroom_bytes':FEATURE_HEADROOM_BYTES})
    atomic_json(vocabulary_path,vocabulary,immutable=True)
    atomic_json(w2_path,w2,immutable=True)
    encoder=build_encoder(permit=permit,cache_directory=out/'embedding_cache')
    date_parser=import_pure(PROJ/'autopilot/q1_audits/NEWSD/feature_contract_amendment1.py','_confx2_date_parser').absolute_interval
    nominal=news.target_day.between('2021-10-01','2024-12-31').to_numpy()
    nominal&=(pd.to_datetime(news.label_available,utc=True)<pd.Timestamp('2024-12-31T14:00:00Z')).to_numpy()
    bundles=_write_bundles(news,_source_manifest_columns(panel_manifest,'news'),
        news_feature_rows(news,articles,permit=permit,encoder=encoder,cache_directory=out/'embedding_cache',
            absolute_interval=date_parser,vocabulary=vocabulary['vocabulary'],stopwords=stops,
            w2_vocabulary=w2['vocabulary']),out,'news',nominal,permit=permit,storage_plan=storage_plan)
    if vocabulary['state']!='AVAILABLE':bundles.append({'source':'news','arm':'W_Bai','variant':'main','state':vocabulary['state'],'reason':vocabulary.get('reason','frozen vocabulary has no surviving words')})
    if w2['state']!='AVAILABLE':bundles.append({'source':'news','arm':'W2_D','variant':'main','state':w2['state'],'reason':w2.get('reason') or 'registered scale-matched vocabulary unavailable'})
    del news,articles
    train=pd.read_parquet(panels_root/'notices_train.parquet');evaluation=pd.read_parquet(panels_root/'notices.parquet')
    train_rows=len(train);notice=pd.concat([train,evaluation],ignore_index=True)
    notice['origin']=pd.to_datetime(notice.origin,utc=True);notice['target_time']=pd.to_datetime(notice.target_time,utc=True)
    notice['target_day']=notice.target_day.astype(str).str[:10]
    input_manifest=input_freeze if isinstance(input_freeze,dict) else read_json(input_freeze) if input_freeze is not None else read_json(STATE/'COMPLETE_INPUT_FREEZE.json')
    nrx_path=Path(input_manifest.get('nrx_labels_path',PROJ/'autopilot/q1_audits/NRX/results_1_3/labels.parquet')).parent
    catalog_path=input_manifest.get('source_catalog_path')
    catalog=read_json(catalog_path) if catalog_path else None
    prefix_rows=pd.read_parquet(catalog['notice_prefix']['path'],columns=['notice_id','available_utc']).to_dict('records') if catalog else None
    notices=load_host_notices(nrx_path,permit=permit,prefix_clock_rows=prefix_rows)
    if prefix_rows is not None and {str(row['notice_id']) for row in prefix_rows}!={str(n['notice_id']) for n in notices}:
        raise ValueError('Complete NRX/canonical prefix ID census mismatch')
    final3=load_final3(permit=permit);corrected=load_corrected_rule(permit=permit)
    p5cols=panel_manifest.get('p5_columns',panel_manifest.get('p5min_columns',[]))
    if p5cols:
        p5_train=pd.read_parquet(panel_manifest['notice_p5_train']['path'])
        p5_evaluation=pd.read_parquet(panel_manifest['notice_p5']['path'])
        p5_joint=pd.concat([p5_train,p5_evaluation],ignore_index=True)
        if len(p5_joint)!=len(notice) or list(p5_joint)!=list(p5cols):raise ValueError('E3 fixed block row/column identity drift')
        for col in p5cols:notice[col]=p5_joint[col].to_numpy(dtype=np.float32)
        del p5_joint,p5_train,p5_evaluation
    nominal=np.arange(len(notice))<train_rows
    bundles+=_write_bundles(notice,_source_manifest_columns(panel_manifest,'notice'),
        notice_feature_rows(notice,notices,permit=permit,encoder=encoder,cache_directory=out/'embedding_cache',
            final3=final3,corrected_rule=corrected,vocabulary=notice_vocabulary,stopwords=stops,
            p5min_columns=p5cols if panel_manifest.get('e3_state','READY')=='READY' else ()),out,'notice',nominal,permit=permit,train_rows=train_rows,storage_plan=storage_plan)
    if not p5cols or panel_manifest.get('e3_state','READY')!='READY':
        for arm in ('NP','NPL','NPP','NPM'):bundles.append({'source':'notice','arm':arm,'variant':'main','state':'UNAVAILABLE_E3_INPUT_GATE','reason':'panel manifest E3 fixed-block completeness/legality gate failed'})
    output={'state':'COMPLETE','layout':'shared_numeric_extras_v1','signature':stamp,'bundles':bundles,'inputs':dependencies,
        'design_freeze_sha256':permit.design_freeze_sha256,'completed_input_manifest_sha256':permit.completed_input_manifest_sha256,
        'fitting_calls':0,'encoder_training_calls':0,'preprocessing_training_only':True,
        'hourly_path':panel_manifest['hourly']['path'],'hourly_sha256':panel_manifest['hourly']['sha256'],
        'canonical_price_path':panel_manifest['canonical_price']['path'],
        'canonical_price_sha256':panel_manifest['canonical_price']['sha256'],
        'W_Bai_selection':file_identity(vocabulary_path),
        'W2_D_selection':file_identity(w2_path),
        'execution_amendment':'CONFX5 (CONF-A1): W2_D and NPM dispositions registered',
        'notice_derived_dates':file_identity(out/'NOTICE_DERIVED_DATE_SIDECARS.json')}
    require_a1_dispositions(output)
    atomic_json(manifest_path,output,immutable=True)
    return output


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--permit',type=Path);parser.add_argument('--panels',type=Path,default=STATE/'panels')
    parser.add_argument('--out',type=Path,default=STATE/'features');parser.add_argument('--input-freeze',type=Path)
    args=parser.parse_args();install_audit('features_host')
    permit=validate_permit(receipt_path=args.permit)
    with exclusive_lock(STATE/'HOST.lock'):
        result=build_all_features(permit,args.panels,args.out,args.input_freeze)
    print(json.dumps({'state':result['state'],'bundles':len(result['bundles'])}))

if __name__=='__main__':main()
