'Compare reproduced results with saved values before resampling.'
from copy import deepcopy
import read_comparisons as P


def deviation(bundle,exc):

    bundle.update(state='DEVIATION',losses={},mean_prediction_losses=None,
        reason='A8NR_PARITY',parity_failure=str(exc),frozen_parity='DEVIATION')
    bundle.pop('native_result',None)
    return bundle


def run(bundle,check):
    if bundle['state']!='COMPUTED':return False
    try:check()
    except (P.Refusal,ValueError,KeyError,TypeError) as exc:
        deviation(bundle,exc);return False
    bundle['frozen_parity']='PASS'
    return True


def require_before_large(bundles):
    for b in bundles:
        P.require(b['state']!='COMPUTED' or b.get('frozen_parity')=='PASS', 'Unproved bundle before B100000: '+b['id'])
        if b['state']!='COMPUTED':P.require(not b.get('losses') and b.get('mean_prediction_losses') is None,'Deviation retained numeric arrays')
