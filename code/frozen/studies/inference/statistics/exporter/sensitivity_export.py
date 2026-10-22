'Export the saved sensitivity arrays and their computation metadata.'
from copy import deepcopy
from datetime import date, timedelta
import math
import re
import hashlib
from ..input_checks import require, json_bytes, canonical

SEEDS = (20260919, 20260920, 20260921)
SERIES = tuple('seed_' + str(s) for s in SEEDS) + ('three_seed_mean_prediction',)
MEAN_DEFINITION = 'daily loss of the mean prediction; not mean arm loss'
ARMS = {'news': ('M', 'L_count', 'L_chen'), 'notice': ('M_notice', 'L14', 'L_Laz', 'L_chen_notice')}


def days(task):
    start = date.fromisoformat('2026-05-19' if task == 'news' else '2026-08-01')
    end = date.fromisoformat('2026-09-30')
    return [(start + timedelta(days=i)).isoformat() for i in range((end - start).days + 1)]


def disposition(bundle, tag):

    state, parity = bundle.get('state'), bundle.get('frozen_parity')
    native = bundle.get('native_status', bundle.get('native_disposition', state))
    require(state in ('COMPUTED', 'NOT_RUN', 'NOT_EVALUABLE', 'DEVIATION', 'PENDING'), 'Unknown native series status')
    require(isinstance(native, str) and bool(native), 'Nonempty native status required')
    computed = state == 'COMPUTED' and parity == 'PASS' and native == 'COMPUTED'
    if tag == SERIES[0]:
        require(computed, 'Primary-seed completion/parity/native status failure: ' + str((state, native, parity, bundle.get('reason'))))
    if computed:
        effective = 'COMPUTED'
    else:
        require(isinstance(bundle.get('reason'), str) and bool(bundle['reason']), 'Native failure reason required')
        not_run = state == 'NOT_RUN' and native == 'NOT_RUN' and parity in (None, 'NOT_RUN')
        effective = 'NOT_RUN' if not_run else 'NOT_EVALUABLE'
    return dict(state=effective, native_status=native, native_parity=parity, reason=bundle.get('reason', ''))


def series_sources(task,bundles,replay_evidence,unavailable_series):
    sources={}
    for seed in SEEDS:
        tag='seed_'+str(seed)
        key=task+('/primary' if seed==SEEDS[0] else '/seed_'+str(seed))
        sources[tag]=bundles.get(key)
        if sources[tag] is None:sources[tag]=unavailable_series.get(task,{}).get(tag)
        require(sources[tag] is not None,'Missing native seed disposition: '+key)
    tag=SERIES[-1];sources[tag]=replay_evidence['native'].get(task+'__THREE_SEED_MEAN.json')
    if sources[tag] is None:sources[tag]=unavailable_series.get(task,{}).get(tag)
    require(sources[tag] is not None,'Missing native mean disposition')
    return sources,{tag:disposition(sources[tag],tag) for tag in SERIES}


def task_pair_export(bundles,replay_evidence,verified_metadata,unavailable_series):

    for task in ('news','notice'):
        require(replay_evidence['daily_csv_proof'][task]['state']=='PASS' and
                replay_evidence['pooled_mean_proof'][task]['state']=='PASS',
                'Native daily/pooled parity required')
        series_sources(task,bundles,replay_evidence,unavailable_series)
    return {task:task_export(task,bundles,replay_evidence,verified_metadata,unavailable_series)
            for task in ('news','notice')}


def task_export(task, bundles, replay_evidence, verified_metadata, unavailable_series):

    require(task in ARMS, 'Unknown task')
    daily = replay_evidence['daily_csv_proof'][task]
    pooled = replay_evidence['pooled_mean_proof'][task]
    require(daily['state'] == pooled['state'] == 'PASS', 'Native daily/pooled parity required')
    meta = deepcopy(verified_metadata[task])
    require(set(meta) == {'days', 'evaluation_view', 'daily_common_key_counts', 'common_keys_sha256',
            'sealed_prediction_manifest_sha256', 'r2_score_receipt_sha256', 'main_daily_csv_sha256'}, 'Closed verified metadata contract')
    for field in ('common_keys_sha256', 'sealed_prediction_manifest_sha256',
                  'r2_score_receipt_sha256', 'main_daily_csv_sha256'):
        require(isinstance(meta[field], str) and re.fullmatch('[0-9a-f]{64}', meta[field]) is not None, 'Missing verified identity: ' + field)
    require(meta['main_daily_csv_sha256'] == daily['file']['sha256'], 'Main CSV receipt binding drift')
    require(meta['days'] == days(task), 'Full task day census drift')
    require(meta['daily_common_key_counts'] == [72 if task == 'news' else 8640] * len(meta['days']), 'Verified complete grid required')
    view = meta['evaluation_view']
    require(view['schema'] == 'PCPRIMARY_R2_NEWS_EVALUATION_V1' and view['issue_days'] == days('news') and
            view['primary_days'] == 135 and view['sealed_domain_days'] == 214, 'R2 receipt evaluation view required')
    require(re.fullmatch('[0-9a-f]{64}', view.get('scientific_source_sha256', '')) is not None, 'R2 scientific source identity required')
    require(meta['evaluation_view'] == verified_metadata['news']['evaluation_view'], 'Same R2 receipt view for both tasks')
    mean_tag = SERIES[-1]

    sources,statuses=series_sources(task,bundles,replay_evidence,unavailable_series)
    output = dict(schema='SENS35_TASK_LOSSES_V2', task=task, **meta,
                  main_daily_csv_parity='PASS', series={})
    for tag in SERIES:
        source, status = sources[tag], statuses[tag]
        require(source['days'] == meta['days'], 'Source series day census drift')
        result = dict(status, days=deepcopy(source['days']),
                      seeds=list(SEEDS) if tag == mean_tag else [int(tag[5:])])

        if source.get('frozen_parity') is not None and (status['state'] == 'COMPUTED' or source['frozen_parity'] != 'PASS'):
            result['frozen_parity'] = source['frozen_parity']
        if status['state'] == 'COMPUTED':
            losses = source['losses']
            require(set(ARMS[task]) <= set(losses), 'Primary loss arm census missing')
            result['losses'] = {}
            for arm in ARMS[task]:
                values = losses[arm].tolist() if hasattr(losses[arm], 'tolist') else list(losses[arm])
                require(len(values) == len(meta['days']) and all(type(v) in (float, int) and math.isfinite(v) and v >= 0 for v in values), 'Loss shape/type/finite drift')
                result['losses'][arm] = values
            if tag == mean_tag:
                primary = bundles[task + '/primary']
                require(primary.get('mean_prediction_loss_definition') == MEAN_DEFINITION, 'Actual mean-prediction provenance required')

                mean = primary.get('mean_prediction_losses')
                require(mean is not None and all((mean[a].tolist() if hasattr(mean[a], 'tolist') else list(mean[a])) == result['losses'][a] for a in ARMS[task]), 'Mean/source array identity drift')
                result['loss_definition'] = MEAN_DEFINITION
        output['series'][tag] = result
    return output


def value_sha256(value):

    return hashlib.sha256(json_bytes(value)).hexdigest()


def pair_statuses(exports):

    require(set(exports)=={'news','notice'},'Both replay loss tasks required')
    states={}
    for task in ('news','notice'):
        obj=exports[task]
        require(obj['schema']=='SENS35_TASK_LOSSES_V2' and obj['task']==task and
                obj['days']==days(task) and set(obj['series'])==set(SERIES),'Replay task/day/series drift')
        states[task]={}
        for tag in SERIES:
            item=obj['series'][tag]
            require(item['days']==days(task) and item['seeds']==
                    (list(SEEDS) if tag==SERIES[-1] else [int(tag[5:])]),'Replay series day/seed drift')
            states[task][tag]=disposition(item,tag)
    return states


def safe_task_export(obj,states):

    base={k:deepcopy(v) for k,v in obj.items() if k not in ('series','replay_binding')}
    base['series']={}
    for tag in SERIES:
        item=obj['series'][tag]
        safe={k:deepcopy(v) for k,v in item.items() if k!='losses'}
        if states[tag]['state']=='COMPUTED':safe['losses']=deepcopy(item['losses'])
        base['series'][tag]=safe
    return base


def replay_binding(exports,evidence):

    states=pair_statuses(exports);tasks={}
    for task in ('news','notice'):
        safe=safe_task_export(exports[task],states[task]);series={}
        for tag in SERIES:
            item=safe['series'][tag]
            series[tag]=dict(metadata={k:v for k,v in item.items() if k!='losses'},
                losses_sha256={arm:value_sha256(item['losses'][arm]) for arm in ARMS[task]}
                    if states[task][tag]['state']=='COMPUTED' else {})
        tasks[task]=dict(export_sha256=value_sha256(safe),
            metadata={k:v for k,v in safe.items() if k!='series'},series=series)
    views=evidence['execution_authority']
    return dict(schema='AP_SCORING_SENS35_REPLAY_BINDING_V1',
        r2_score_receipt=deepcopy(views['r2']['score_receipt']),
        execution_authority_sha256=value_sha256(views),
        loss_replay_sha256=value_sha256(evidence['loss_replay']),tasks=tasks)


def bind_replay_exports(exports,record,evidence,*,numeric_source,numeric_evidence,numeric_receipt):
    require(canonical(replay_binding(exports,evidence))==canonical(record['sens35_replay_binding']),
            'Replay arrays changed after actual callback commitment')
    states=pair_statuses(exports);out={}
    for task in ('news','notice'):
        out[task]=safe_task_export(exports[task],states[task])
        out[task]['replay_binding']=dict(schema='AP_SCORING_SENS35_REPLAY_REFERENCE_V1',
            numeric_source=deepcopy(numeric_source),numeric_evidence=deepcopy(numeric_evidence),
            numeric_receipt=deepcopy(numeric_receipt),pointer='/sens35_replay_binding/tasks/'+task)
    return out


def write_replay_artificial(exports,output,*,fixture_root,reverify,record,evidence,
                            numeric_source,numeric_evidence,numeric_receipt):

    from pathlib import Path
    from ..input_checks import artificial_accept, json_bytes, source_identity
    root=artificial_accept(fixture_root);out=Path(output)
    require(set(exports)=={'news','notice'} and out.resolve()==out and out.is_relative_to(root)
            and not out.exists(),'Fresh artificial replay-loss pair')
    bound=bind_replay_exports(exports,record,evidence,numeric_source=numeric_source,
        numeric_evidence=numeric_evidence,numeric_receipt=numeric_receipt)
    reverify();out.mkdir(parents=True,exist_ok=False);identities={}
    for task in ('news','notice'):
        path=out/('SENS35_'+task.upper()+'_LOSSES.json')
        with path.open('xb') as handle:handle.write(json_bytes(bound[task]))
        identities[task]=source_identity(path)
    reverify();return identities
