"""Frozen-order post-score host continuation; no command runs on import.

The coordinator supplies reviewed argv and identity-only re-pin bindings before
T5. KCX is launched in the author's terminal with inherited environment; this
module never reads, logs or writes the API key. The PCX extension charges the
same fitting wall ledger used before T5 (base PC has its own frozen ledger).
"""
from pathlib import Path
import subprocess
from a8_common import *

ORDER = ('A2LABEL','KCX','PC','PCX_extension')
CUTOFF = dt.datetime(2026,10,6,12,tzinfo=dt.timezone(dt.timedelta(hours=11)))

def fill_cutoff(score_time, terminal_times):
    score_time = dt.datetime.fromisoformat(score_time)
    # None represents an authorised run that has not terminated. Its presence
    # keeps the cutoff at the fixed deadline, not an earlier completed turn.
    end = CUTOFF if any(t is None for t in terminal_times) else max((dt.datetime.fromisoformat(t) for t in terminal_times),default=CUTOFF)
    return max(score_time,min(CUTOFF,end))

def charge_extension(command, ledger, call=subprocess.run):
    require(command and all(isinstance(a,str) for a in command), 'Reviewed PCX argv required')
    require(ledger.remaining() > 0, 'Admitted PCX extension exhausted batch ledger: deviation')
    # PCX's own code controls its scientific fit waves. The host records its full
    # fit-only extension invocation, including failures, as a non-overlapping wave.
    from types import SimpleNamespace
    token = SimpleNamespace(task='pcx',origin='extension',arm='null_replicates_41_200',seed=SEED,variant='extension')
    ident = ledger.begin([token],'PCX_extension')
    success = False
    try:
        result = call(command,check=False)
        success = result.returncode == 0
        return result
    finally:
        ledger.finish(ident,'COMPLETE' if success else 'FAILED')

def run_order(steps, admission, ledger, log_path, call=subprocess.run):
    require(set(steps) == set(ORDER), 'Post-score stage inventory drift')
    log_path = Path(log_path)
    prior = []
    if log_path.exists():
        prior = [json.loads(line) for line in log_path.read_text().splitlines()]
        require([r['stage'] for r in prior] == list(ORDER[:len(prior)]), 'Post-score launch order deviation')
        require(all(r.get('end_utc') and r['state'] in ('COMPLETE','NOT_AUTHORISED','PENDING_A8NR_SPEED','NOT_RUN_A8NR_BATCH_BUDGET','NOT_RUN_A8NR_REPIN') for r in prior),
                'Interrupted/failed post-score command: document resource-only remedy before restarting')
    for stage in ORDER[len(prior):]:
        row = steps[stage]
        record = dict(stage=stage,launch_utc=now())
        write_json(log_path.parent/'POSTSCORE_TURN_STATE.json',dict(stage=stage,launch_utc=record['launch_utc']))
        if stage in ('PC','PCX_extension') and admission['rho'] >= 1.5:
            record['state'] = 'PENDING_A8NR_SPEED'
        elif stage == 'PCX_extension' and admission['state'] != 'ADMITTED':
            record['state'] = 'NOT_RUN_A8NR_BATCH_BUDGET'
        elif not row['authorised']:
            require(stage == 'KCX', 'Skipping a required post-score turn is a deviation')
            record['state'] = 'NOT_AUTHORISED'
        elif row.get('repin_verified') is not True:
            record.update(state='NOT_RUN_A8NR_REPIN',reason='A8NR_REPIN')
        else:
            for item in row['bindings']:
                checked(item)  # reviewed re-pin / code / T5 / author-record identities
            require(row.get('repin_verified') is True, 'A8NR_REPIN')
            result = charge_extension(row['argv'],ledger,call) if stage == 'PCX_extension' else call(row['argv'],check=False)
            record.update(state='COMPLETE' if result.returncode == 0 else 'DEVIATION',returncode=result.returncode)
        record['end_utc'] = now()
        log_path.parent.mkdir(parents=True,exist_ok=True)
        with log_path.open('a') as stream:
            stream.write(json.dumps(record,ensure_ascii=False)+'\n')
        require(record['state'] != 'DEVIATION', 'Post-score execution failure; keep deviation and stop')
    return log_path


if __name__ == '__main__':
    import argparse
    from a8_freeze import verify,validate_t5_binding
    from a8_adapter import load,relocate
    from runner import active_fit_jobs
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute',action='store_true')
    args = parser.parse_args()
    require(args.execute and os.environ.get('A8BATCH_HOST_RUN') == '1', 'Separate post-score host execution required')
    from a8_adapter import install_audit
    install_audit(OUT/'state')
    code = verify()
    validate_t5_binding(code,OUT/'state')
    require(os.getpriority(os.PRIO_PROCESS,0) >= 10, 'Production execution requires nice 10')
    require(not active_fit_jobs(), 'Post-score runs must not overlap independent fits')
    binding = read_json(checked(code['bindings']))
    A = load(code['adapter_root'],expected=code['adapter_freeze_sha256'],preverified=True)
    relocate(A,OUT/'state')
    from batch_export import verify_seal
    verify_seal(OUT/'state')
    require((OUT/'state/scoring/A8BATCH_POSTSCORE_INPUTS.json').is_file(), 'Post-score chain starts after batch scoring')
    with A.execution.exclusive_state(OUT/'state'):
        from repin_plan import effective_steps
        run_order(effective_steps(binding),read_json(OUT/'state/PCX_ADMISSION.json'),
                  A.execution.WallLedger(OUT/'state'),OUT/'POSTSCORE_HOST_LOG.jsonl')
