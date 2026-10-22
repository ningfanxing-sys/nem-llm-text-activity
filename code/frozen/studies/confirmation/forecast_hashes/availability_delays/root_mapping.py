'Check source paths for delayed notice forecasts.'
import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import types

sys.dont_write_bytecode = True
HERE = Path(__file__).absolute().parent
PROJ = HERE.parents[4]
C_REL = 'studies/batch_estimation/batch_checks'
FILL_REL = 'tables/table_renderer/notice_constraints'
SCHEMA = 'FORECAST_BINDING_FINAL_ROOT_MAPPING_V2'
STATE = 'FINAL_REVIEWED_SOURCE_MAPPING_NOT_FREEZE'
REVIEW_SCHEMA = 'A8CONSUMER_INDEPENDENT_REVIEW_ACCEPTANCE_V1'
PARENT_SOURCE = HERE.parent/'deadline_checks/root_mapping.py'
PARENT_SHA256 = '1d623915731956b2af560064f20f8a3a33ec55ab662df7eed6e827e16fb4eb2d'
FORBIDDEN = {'host_state','state','dly8','cps8','sealed','scored','scores',
             'predictions','models','evaluation','run'}


def require(ok, why):
    if not ok:
        raise RuntimeError(why)


def _provider():

    p = PARENT_SOURCE
    for part in (p,*p.parents):
        require(not stat.S_ISLNK(part.lstat().st_mode),'Parent mapping symlink refused')
    require(stat.S_ISREG(p.lstat().st_mode),'Regular parent mapping source required')
    source = p.read_bytes()
    require(hashlib.sha256(source).hexdigest() == PARENT_SHA256,
            'Historical validation_group_10 mapping source drift')
    module = types.ModuleType('_forecast_binding8_parent_mapping')
    module.__file__ = str(p)
    exec(compile(source,str(p),'exec'),module.__dict__)
    module.HERE = HERE
    module.FILL_REL = FILL_REL
    module.SCHEMA = SCHEMA
    return module


def identity(path):
    return _provider().identity(path)


def read(path):
    return _provider().read(path)


def source_path(root, relative):
    return _provider().source_path(root,relative)


def constant(path, name):
    return _provider().constant(path,name)


def mapping_sha256(mapping):
    return _provider().mapping_sha256(mapping)


def final_mapping_contract(project=PROJ):
    value = _provider().final_mapping_contract(project)
    value['schema'] = 'FORECAST_BINDING_FINAL_ROOT_MAPPING_CONTRACT_V2'
    value['consumer_final_reading'] = 'FILL3f notice_constraints; DEC D1/D2/D7'
    return value


def record_final_mapping(base_mapping, *, project=PROJ):

    provider = _provider()
    value = provider.record_final_mapping(base_mapping,project=project)
    value['contract'] = final_mapping_contract(project)
    value['unchanged_parent_mapping_algorithm'] = provider.identity(PARENT_SOURCE)
    value['metadata_constant_overlay'] = dict(fill_relative_path=FILL_REL,
        output_directory=str(HERE),schema=SCHEMA,
        numerical_computation_changed=False)
    return value


def verify_final_mapping(path=HERE/'FINAL_ROOT_MAPPING.json', *, project=PROJ):
    value = read(path)
    require(value == record_final_mapping(value['root_mapping'],project=project),
            'Final notice_constraints source/mapping drift')
    return value


def runtime_mapping(base_mapping=None, *, receipt_path=HERE/'FINAL_ROOT_MAPPING.json', project=PROJ):
    value = verify_final_mapping(receipt_path,project=project)
    if base_mapping is None:
        from forecast_inputs import root_mapping_contract
        base_mapping = root_mapping_contract()
    require(value['root_mapping'] == base_mapping,'Current frozen mapping provider drift')
    return value['root_mapping']


def refresh(base_mapping, *, project=PROJ, out=HERE):
    require(os.getpriority(os.PRIO_PROCESS,0) == 20,'Refresh requires nice20')
    out = Path(out).absolute()
    require(out == HERE or out.is_relative_to(Path('/private/tmp')),
            'Refresh write escaped overlay or synthetic scratch')
    value = record_final_mapping(base_mapping,project=project)
    payload = (json.dumps(value,indent=2,ensure_ascii=False,allow_nan=False)+'\n').encode()
    fd = os.open(out/'FINAL_ROOT_MAPPING.json',os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o444)
    with os.fdopen(fd,'wb') as f:
        f.write(payload); f.flush(); os.fsync(f.fileno())
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-refresh',action='store_true')
    args = parser.parse_args()
    require(args.source_refresh and os.environ.get('FORECAST_BINDING_SOURCE_MAPPING_REFRESH') == '1',
            'Explicit source-only refresh required')
    sys.path.insert(0,str(HERE.parent/'code'))
    from forecast_inputs import root_mapping_contract
    refresh(root_mapping_contract())
    print('Final notice_constraints source mapping recorded; no freeze or production run')


if __name__ == '__main__':
    try:
        main()
    except (OSError,ValueError,RuntimeError,KeyError,TypeError) as exc:
        raise SystemExit('FORECAST_BINDING8 notice_records MAPPING REFUSED: '+str(exc))
