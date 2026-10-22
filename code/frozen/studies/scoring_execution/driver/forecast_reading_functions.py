'Read the two specified forecast comparison functions.'
from contextlib import contextmanager
import hashlib
from pathlib import Path
from types import FunctionType
from source_bytes import require

LEAVES=('studies/batch_estimation/matrix_storage/eviction_patch.py',
        'studies/scoring_execution/driver/a3/AF_ATTESTATION_CONTROL.json')


def selected(project, frozen):
    inventory=list(frozen['speed_overlay_binding']['source_inventory'].values())
    inventory.append(frozen['source_attestation'])
    result={}
    for relative in LEAVES:
        key=str(Path(project)/relative)
        matches=[r for r in inventory if r['path']==key]
        require(len(matches)==1, 'Exact frozen AF leaf missing/ambiguous: '+key)
        item=matches[0]
        require(set(item)=={'path','bytes','sha256'} and isinstance(item['bytes'],int)
                and len(item['sha256'])==64, 'Invalid frozen AF leaf identity')
        result[key]=dict(item)
    return result


@contextmanager
def installed(timestamp_checks, project, frozen):

    pins=selected(project,frozen)
    parent=timestamp_checks.parent_authority()
    previous=parent.read_metadata
    original=parent._unchanged_reader
    def read_metadata(path):
        raw=parent.canonical(path)
        if raw not in pins:return previous(path)
        globals_=dict(original.__globals__,ERRATUM={'path':raw})
        reader=FunctionType(original.__code__,globals_,'_minrun_two_exact_metadata_leaves',
                            original.__defaults__,original.__closure__)
        reader.__kwdefaults__=original.__kwdefaults__
        data=reader(raw)
        require(len(data)==pins[raw]['bytes'] and hashlib.sha256(data).hexdigest()==pins[raw]['sha256'],
                'Exact frozen AF leaf bytes drift: '+raw)
        return data
    parent.read_metadata=read_metadata
    try:yield pins
    finally:parent.read_metadata=previous
