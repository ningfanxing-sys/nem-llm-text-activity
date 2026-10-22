'Independently check numerical values, record pointers and receipts.'
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from source_bytes import checked, document, identity, require
from native_entries import reader_modules
from adapters import rd_native_projection

RECEIPTS=('original_score','r2_score','capture_clock','capture_snapshot','a2','a3','a4',
          'batch','numeric','score_news_full_window','rd','af_acceptance','am3')


def pointer(value, path):
    for key in path.split('/')[1:]:
        key=key.replace('~1','/').replace('~0','~')
        value=value[int(key)] if isinstance(value,list) else value[key]
    return value


def verify(*,association,eligibility,numeric_source,rd_source,receipts):
    a=association;a._check_official_score(a._official_ready)
    spec=document(eligibility)
    require(spec['schema']=='MINRUN_G42_INPUTS_V1','K6 G42 contract')
    require(set(receipts)==set(RECEIPTS),'K6 thirteen-receipt census')
    values={k:document(v) for k,v in receipts.items()}
    numeric=document(numeric_source);rd=document(rd_source)
    require(values['numeric']['files'][0]==numeric_source and rd_source in values['rd']['files'],
            'K6 independently receipt-bound outputs')
    require(values['score_news_full_window']['original_score_receipt']==receipts['original_score'],
            'K5 score_news_full_window independent original chain')
    require(receipts['original_score']==a._official_ready['view_inputs']['original']['score_receipt'] and
        receipts['r2_score']==a._official_ready['view_inputs']['r2']['score_receipt'] and
        numeric['source_receipt_sha256']==receipts['r2_score']['sha256'] and
        rd['provenance']['specified_record']==numeric_source and
        rd['provenance']['source_receipt_sha256']==receipts['r2_score']['sha256'],'K6 original/R2/specified lineage')
    from evaluator import api, _joint_comparisons as J
    from native import compute
    joint=document(spec['joint_source']);kernel=document(spec['native_source'])
    require(spec['joint_source'] in values['rd']['files'] and spec['native_source'] in values['rd']['files'],
            'K6 independent joint/native receipt binding')
    execution=a._official_ready['view_inputs']['execution']
    require(receipts['capture_clock']==execution['clock'] and receipts['capture_snapshot']==execution['capture']
        and values['capture_clock']['conf_score_receipt']==receipts['original_score'],
        'K6 independent original capture receipt binding')
    require(set(joint['bindings'])==api.BINDING_ROLES,'K6 nine-binding census')
    for role,item in joint['bindings'].items():
        actual=identity(item['path']);require(actual['sha256']==item['sha256'] and
            item=={k:spec['bindings'][role][k] for k in item},'K6 independent binding hash/association')


    sources=a._sources;primary_tests,sensitivity_tests,robustness_tests,sc,_=reader_modules(sources,a._control['project'])
    P=sources.module('read_comparisons',Path(a._control['project'])/'studies/inference/code/read_comparisons.py')
    M=SimpleNamespace(P=P,primary_tests=primary_tests,sensitivity_tests=sensitivity_tests,robustness_tests=robustness_tests,sc=sc)
    families={};authorities={}
    for key in ('specified/5','specified/15','specified/60','aligned/5','aligned/15','aligned/60'):
        origin,delay=key.split('/'); rows=[r for c in joint['contrasts'] for r in c['readings']
            if r['origin']==origin and r['delay_minutes']==int(delay)]
        require(len(rows)==3,'K6 independent condition census')
        paths={r['native_authority']['path'] for r in rows};require(len(paths)==1,'K6 family pointer source')
        item=identity(paths.pop());family=document(item)
        require(family==kernel['families'][key] and item in values['rd']['files'],'K6 independent family value/receipt')
        authorities[key]={k:item[k] for k in ('path','sha256')};families[key]=family
        for i,row in enumerate(rows):
            require(row['native_authority']==dict(authorities[key],pointer='/reports/'+str(i)),
                    'K6 native pointer drift')
            require(pointer(family,row['native_authority']['pointer'])==family['reports'][i], 'K6 native report pointer')
    schema=document(spec['schema_identity'])
    regenerated=compute.joint_from_native(M,families,authorities,joint['bindings'],
        alert=numeric['tasks']['notice']['alert'],schema=schema)
    require(regenerated==joint,'K6 independent numbers/checks/seed/exclusion native parity')
    projected=rd_native_projection(api,joint,numeric['tasks']['notice'],rd['provenance'],schema,a.project)
    require(projected==rd,'K6 independent weakest reading/maxU/seed parity')
    require(values['af_acceptance']['corrected_seal_verified_utc']==spec['corrected_seal_verified_utc'],
            'K6 corrected timestamp_checks mismatch')
    utc=lambda s:datetime.fromisoformat(s.replace('Z','+00:00'))
    require(utc(spec['corrected_seal_verified_utc'])<utc(a._t5_value['utc']),
            'K6 independent corrected verified seal before T5')


    return dict(schema='C_SCORING_G42_VERIFIED_ASSOCIATION_V1',eligibility=deepcopy(eligibility),
        numeric_source=deepcopy(numeric_source),rd_source=deepcopy(rd_source),receipts=deepcopy(receipts),
        checked_native_conditions=18,checked_joint_contrasts=3,no_new_statistics=True)
