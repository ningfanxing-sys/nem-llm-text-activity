'Run scoring after checking that all required predictions are saved.'
import sys
import time
import traceback
from score_dayfirst import *
from official_scoring import OfficialForecasts,prepare_official,write_official

def main():
    assert read(OUT/'EQUIVALENCE.json')['state']=='PASSED'
    assert read(OUT/'PREDICTIONS.json')['state']=='COMPLETE'
    start=time.monotonic()
    progress('Scoring: every required forecast complete; frozen truth/key verification starts')
    frozen,forecasts,seal,original_seal,changes,native=posthoc_context()
    post_specs,lookup=prepare_posthoc(frozen,forecasts)
    F=OfficialForecasts(forecasts,read(OUT/'PREDICTIONS.json'),native)
    official_specs,metadata=prepare_official(F)
    write(OUT/'POSTHOC_BOOTSTRAP_SPECS.json',post_specs)
    progress(f'Scoring inputs verified: {len(post_specs)} unique seed and window bootstrap pairs, {len(official_specs)} official family/version jobs')
    results,workers=run_stats(post_specs+official_specs)
    tree=write_official(results,metadata)
    write_posthoc_intervals(results,lookup)
    decisions=run_posthoc_frozen(frozen,forecasts,seal,results)
    checks=read(OUT/'OFFICIAL_BASELINE_EQUIVALENCE.json')
    completion=dict(state='COMPLETE',runtime_seconds=time.monotonic()-start,
        bootstrap_draws=100000,bootstrap_seed=20260925,bootstrap_workers=workers,
        statistical_jobs=len(results),maximum_worker_peak_rss_bytes=max(r['peak_rss_bytes'] for r in results.values()),
        posthoc_decisions=decisions,official_families=len(metadata),
        official_month_first_point_checks=len(checks['checks']),models_refitted=0)
    write(OUT/'SCORING_COMPLETE.json',completion)
    progress('Scoring COMPLETE; frozen seed and window decision rules executed')

if __name__=='__main__':
    try:main()
    except BaseException as exc:
        write(OUT/'SCORING_FAILURE.json',dict(state='STOPPED',error=str(exc),traceback=traceback.format_exc()))
        progress('Scoring STOP: '+str(exc))
        raise
