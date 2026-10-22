'Export the metadata of computed numerical results.'
from copy import deepcopy
import hashlib, json
from pathlib import Path
import producer as R
P=R.P

FIELDS=('effect_percent','one_day','seven_day','p_two_sided','p_improvement',
        'p_deterioration','hac7_p_two_sided','holm_p','days','class')

def canonical_hash(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()

def row_identity(index,row):
    return dict(forest_index=index,task=row['task'],group=row['group'],
                layer=row['field'].rsplit('/',1)[0].split('/',1)[1],
                arm=row['arm'],reference=row['ref'],field=row['field'])

def descriptive_subset(layer):
    return layer=='subsets' or 'A1_EXPOSURE_EXCLUDED' in layer

def row_role(identity):
    layer=identity['layer']
    if identity['group']=='Combination':return 'COMBINATION'
    if descriptive_subset(layer) or layer=='report_2025':return 'DIAGNOSTIC'
    if layer in P.LAYERS or layer.startswith('seed_') or 'A1_OFFICIAL_CAP_RECLIP' in layer:return 'SENSITIVITY'
    return 'SECONDARY'

def native_supplement(record,current,bundles):

    primary={t:[[c['arm'],c['reference']] for c in record['tasks'][t]['contrasts']] for t in P.PAIRS}
    P.require(primary=={t:[list(p) for p in pairs] for t,pairs in P.PAIRS.items()}, 'AP5 primary census drift')
    rows=[]
    for index,row in enumerate(record['forest_rows']):
        if row['group']=='Primary':continue
        identity=row_identity(index,row);key=identity['task']+'/'+identity['layer']
        P.require(key in current and key in bundles, 'AP5 existing native family required')
        family=current[key]
        found=[r for r in family['reports'] if (r['arm'],r['reference'])==(identity['arm'],identity['reference'])]
        P.require(len(found)==1 and family['state']=='COMPUTED','AP5 unique computed native row required')
        native=found[0];layer=identity['layer']
        adjusted=layer in ('combination','l1_family','pd_family')
        interval_field='interval_family_adjusted_percent' if adjusted else 'interval95_percent'
        one=native['bootstrap']['1'].get(interval_field);seven=native['bootstrap']['7'].get(interval_field)
        P.require(row['effect']==native.get('effect_percent_reference_mae') and row['thick']==one and row['thin']==seven,
                  'AP5 native/forest scientific identity drift')
        values=dict(effect_percent=P.decimal(native.get('effect_percent_reference_mae')),
                    one_day=P.interval_strings(one),seven_day=P.interval_strings(seven),
                    days=int(native['n_days']),native_decision=native['decision'],
                    **{'class':'not applicable (descriptive subset)' if descriptive_subset(layer) else P.CLASS[native['decision']]})
        for field in ('p_two_sided','p_improvement','p_deterioration','hac7_p_two_sided','holm_p'):
            values[field]=P.decimal(native.get(field),12)
        rows.append(dict(identity=identity,scope='SPECIFIED_NONPRIMARY',role=row_role(identity),
            adjustment=dict(family_m=int(family['family_m']),
                dm='UNADJUSTED' if bundles[key].get('unadjusted') else 'HOLM_WITHIN_SPECIFIED_NONPRIMARY_FAMILY',
                interval='FAMILY_ADJUSTED' if adjusted else 'PER_CONTRAST_95'),
            seed_design='ADDITIONAL_SINGLE_SEED' if layer.startswith('seed_') else 'MAIN_SINGLE_SEED',values=values))
    return dict(schema='A8POST5_NATIVE_SUPPLEMENT_V1',source_receipt_sha256=record['identities']['source_receipt_sha256'],
        producer_identity=P.identity(R.ROOT/'code/producer.py'),
        frozen_function_identities=[dict(P.identity(R.AP/'code/read_comparisons.py'),
            functions=['table_records','decimal','interval_strings','compute_bundle']),
            dict(P.identity(P.confirmation/'code/scoring.py'),functions=['dm_daily','holm','block_picks','paired_percent_interval'])],
        forest_rows_sha256=canonical_hash(record['forest_rows']),primary_pairs=primary,rows=rows)

def requested_plan(record,base,native_identity):

    result=deepcopy(base)
    P.require(result['schema']=='A8POST5_TABLE_PLAN_V1','AP5 requested table plan schema')
    slots=[(i,row) for i,row in enumerate(record['forest_rows']) if row['group']!='Primary']
    for position,(index,row) in enumerate(slots):
        identity=row_identity(index,row);layer=identity['layer']
        role=row_role(identity)
        table='combinations' if role=='COMBINATION' else 'cheap' if layer=='cheap' else 'sensitivities' if role=='SENSITIVITY' else 'diagnostics' if role=='DIAGNOSTIC' else 'secondary_'+row['task']
        timestamp_checks=dict(native_identity,pointer='/rows/'+str(position),source_receipt_sha256=record['identities']['source_receipt_sha256'])
        cells=[dict(kind='forest_pair',identity=identity)]
        cells += [dict(kind='forest_native',identity=identity,field=field,timestamp_checks=timestamp_checks)
                  for field in ('scope','role','adjustment','seed_design',*FIELDS)]
        body=result['tables'][table];width=max(len(cells),len(body[0]))
        for raw in body:raw.extend(dict(kind='label',value='') for _ in range(width-len(raw)))
        cells.extend(dict(kind='label',value='') for _ in range(width-len(cells)))
        body.append(cells)
    return result
