"""Outcome-blind exact input identities at the registered fill cutoff; never fits."""
from a8_common import *
import argparse
import time

CUTOFF = dt.datetime(2026,10,6,1,tzinfo=dt.timezone.utc)

def utc(value):
    stamp=dt.datetime.fromisoformat(value.replace('Z','+00:00'))
    require(stamp.utcoffset()==dt.timedelta(0),'UTC clock association required')
    return stamp

def capture(clock_path,destination,observed_utc=None):
    clock=read_json(clock_path)
    require(clock.get('state')=='POSTSCORE_CLOCK_ASSOCIATION_VERIFIED' and clock.get('coordinator_verified') is True,'Reviewed real score-time association required')
    checked(clock['conf_score_receipt'])  # opaque identity; no score/result interpretation
    score_time=utc(clock['score_complete_utc']);cut=max(score_time,CUTOFF)
    observed=utc(observed_utc or now())
    require(observed>=cut,'No snapshot before registered cutoff')
    rows=[json.loads(line) for line in Path(clock['host_log']).read_text().splitlines()] if Path(clock['host_log']).exists() else []
    completed={r['stage']:r for r in rows if r.get('end_utc') and utc(r['end_utc'])<=cut}
    turn_path=Path(clock['turn_state']);turn=read_json(turn_path) if turn_path.exists() else {}
    stages={};files=[]
    for name,paths in clock['producer_outputs'].items():
        row=completed.get(name)
        if row and row['state']=='COMPLETE':
            items=[]
            for path in paths:
                item=identity(path);require(item==identity(path),'Input publication changed during cutoff hash')
                items.append(item);files.append(item)
            stages[name]=dict(state='COMPLETED_BY_CUTOFF',end_utc=row['end_utc'],files=items)
        elif row:
            stages[name]=dict(state='TERMINAL_BY_CUTOFF',disposition=row['state'],end_utc=row['end_utc'],files=[])
        else:
            stages[name]=dict(state='RUNNING_AT_CUTOFF' if turn.get('stage')==name and turn.get('launch_utc') and utc(turn['launch_utc'])<=cut else 'PENDING_AT_CUTOFF',files=[])
    for item in clock['initial_inputs']:checked(item);files.append(item)
    value=dict(schema='A8_CUTOFF_IDENTITIES_V1',state='OUTCOME_BLIND_CUTOFF_SNAPSHOT',cutoff_utc=cut.isoformat(),
        observed_utc=observed.isoformat(),capture_lateness_seconds=(observed-cut).total_seconds(),
        late_score_cutoff=score_time>CUTOFF,clock_association=identity(clock_path),producer_states=stages,
        files=list({i['path']:i for i in files}.values()),pending_is_negative=False,source_values_decoded=False,
        native_V2_RS8_constructor_owner='A8POST/coordinator; use these exact identities and a fresh output')
    write_json(destination,value,exclusive=True)
    return value

def watch(clock_path,destination):
    clock=read_json(clock_path);cut=max(utc(clock['score_complete_utc']),CUTOFF)
    require(not Path(destination).exists(),'Never overwrite a cutoff snapshot')
    require(utc(now())<=cut,'Missed cutoff; refuse retrospective reconstruction, retain evidence for next version')
    while utc(now())<cut:time.sleep(max(0.,min(1.,(cut-utc(now())).total_seconds())))
    return capture(clock_path,destination)

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--execute',action='store_true');parser.add_argument('--clock-association',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();require(args.execute and os.environ.get('A8BATCH_HOST_RUN')=='1','Explicit post-T5 metadata watcher authorization required')
    from a8_freeze import verify,validate_t5_binding
    code=verify();validate_t5_binding(code,OUT/'state')
    require(os.getpriority(os.PRIO_PROCESS,0)>=10,'Production nice 10 required')
    watch(args.clock_association,args.output)
