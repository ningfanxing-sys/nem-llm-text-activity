'Check forecast source hashes and saved forecast records.'
import os
import sys
from common import *

if __name__=='__main__':
    require(os.environ.get('FORECAST_BINDING_SOURCE_RUN')=='1','Source-only host seal verification')
    install_audit()
    resources()
    from run_bound_forecasts import verify_code, require_before_t5
    frozen=verify_code(); require_before_t5(frozen['root_mapping'],frozen['timestamp_root_identity'])
    from prediction_set import verify_seal
    value=verify_seal(OUT/'SEAL_FORECAST_BINDING.json')
    print(json.dumps({'state':'VERIFIED_FORECAST_BINDING_BEFORE_T5','affected_arm_count':len(read_json(checked(value['parity']))['affected_arms']),
                      'seal_sha256':sha(OUT/'SEAL_FORECAST_BINDING.json'),'models_refitted':0,'values_printed':False}))
