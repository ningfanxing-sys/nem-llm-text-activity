'Validate sensitivity records and input array hashes.'
from ..input_checks import require

def validate_detached(exports,receipt_sha256):

    from .sensitivity_validators import validate_export
    require(set(exports)=={'news','notice'},'Both detached tasks required')
    for task in ('news','notice'):
        validate_export(exports[task],expected_task=task,metadata_only=True)
        require(exports[task]['r2_score_receipt_sha256']==receipt_sha256,'Detached R2 receipt drift')
    require(exports['news']['evaluation_view']==exports['notice']['evaluation_view'],'Detached task view drift')
    for task in ('news','notice'):validate_export(exports[task],expected_task=task)


def validate_publication(exports,record,numeric_source,runtime):

    from copy import deepcopy
    from .sensitivity_validators import validate_export
    from .sensitivity_export import pair_statuses,safe_task_export,value_sha256,SERIES,ARMS
    from ..input_checks import canonical
    require(set(exports)=={'news','notice'},'Both detached tasks required')
    for task in ('news','notice'):validate_export(exports[task],expected_task=task,metadata_only=True)
    states=pair_statuses(exports)

    metadata=runtime.verified_sens35_publication(exports,record,numeric_source)
    commitment=record['sens35_replay_binding'];require(set(commitment['tasks'])=={'news','notice'},'Replay task commitment census')
    for task in ('news','notice'):
        obj=exports[task];expected=commitment['tasks'][task]
        for key,value in metadata[task].items():
            require(canonical(obj[key])==canonical(value),'Detached/current official metadata drift: '+task+'/'+key)
        declared={k:v for k,v in obj.items() if k not in ('series','replay_binding')}
        require(canonical(declared)==canonical(expected['metadata']),'Detached/replay metadata drift')
        require(set(expected['series'])==set(SERIES),'Replay series commitment census')
        for tag in SERIES:
            source={k:v for k,v in obj['series'][tag].items() if k!='losses'}
            require(canonical(source)==canonical(expected['series'][tag]['metadata']),
                    'Detached/replay status or seed metadata drift')
    clean={}
    for task in ('news','notice'):
        validate_export(exports[task],expected_task=task)
        safe=safe_task_export(exports[task],states[task]);expected=commitment['tasks'][task]
        for tag in SERIES:
            hashes=({arm:value_sha256(safe['series'][tag]['losses'][arm]) for arm in ARMS[task]}
                    if states[task][tag]['state']=='COMPUTED' else {})
            require(hashes==expected['series'][tag]['losses_sha256'],'Detached/native replay loss array drift')
        require(value_sha256(safe)==expected['export_sha256'],'Detached/native task export drift')
        safe['replay_binding']=deepcopy(exports[task]['replay_binding']);clean[task]=safe
    return clean
