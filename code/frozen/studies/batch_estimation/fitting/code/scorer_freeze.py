"""A8 §4 step 6: independent scorer freeze after FILL3f/interface freeze, before T5."""
from a8_common import *

def candidate():
    tests = read_json(OUT/'TEST_RESULTS.json')
    require(tests['passed'] and tests.get('scorer_code_sha256') == code_hashes('scorer'),
            'Exact current passing scorer/parity tests required')
    binding = read_json(OUT/'SCORER_BINDINGS.json')
    require(binding.get('coordinator_reviewed') is True,'Scorer bindings must be reviewed')
    # Bind the immutable consumer freeze, never mutable work-in-progress interfaces.
    freeze = binding['fill3f_freeze'];consumer = read_json(checked(freeze))
    require(consumer.get('frozen') is True or 'FROZEN' in consumer.get('state',''),'Completed FILL3f/interface freeze required')
    return dict(schema='A8POST_LOSS_EXPORT_FREEZE_V1',state='A8_SCORER_CODE_FROZEN_BEFORE_T5',
                frozen_utc=now(),code_sha256=code_hashes('scorer'),files=[identity(p) for p in code_files('scorer')],
                batch_code_freeze=identity(OUT/'CODE_FREEZE.json'),fill3f_freeze=freeze,
                scorer_bindings=identity(OUT/'SCORER_BINDINGS.json'),test_provenance=identity(OUT/'TEST_RESULTS.json'),
                production_fits=0,scope='scorer + parity tests; A8 section 4 step 6')

def create():
    path=OUT/'SCORER_CODE_FREEZE.json';require(not path.exists(),'Never overwrite scorer code freeze')
    value=candidate();write_json(path,value,exclusive=True);return value

def verify(path=OUT/'SCORER_CODE_FREEZE.json'):
    value=read_json(path)
    require(value['state']=='A8_SCORER_CODE_FROZEN_BEFORE_T5' and value['code_sha256']==code_hashes('scorer'),'Scorer code freeze drift')
    for item in (value['batch_code_freeze'],value['fill3f_freeze'],value['scorer_bindings'],*value['files']):checked(item)
    return value
