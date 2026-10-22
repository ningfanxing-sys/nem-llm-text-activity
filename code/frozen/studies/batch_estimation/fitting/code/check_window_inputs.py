"""R12b: one result-independent decision, durable before any B4 fit."""
from a8_common import *
import math

DEADLINE = '2026-10-05T18:00:00+00:00'
PROXY_ROUND_SECONDS = 43.488448833
# Five arms per origin require two four-fit waves, plus two validation waves.
NEWS_ROUNDS = 214 * 2 + 2

def decision(start, rho, dly8_seconds, seal_seconds):
    start = dt.datetime.fromisoformat(start.replace('Z','+00:00'))
    require(start.utcoffset() == dt.timedelta(0), 'Admission start must be UTC')
    require(all(isinstance(x,(int,float)) and math.isfinite(x) and x >= 0 for x in (rho,dly8_seconds,seal_seconds)) and rho > 0,
            'Finite metadata-only time projection required')
    news_seconds = NEWS_ROUNDS * PROXY_ROUND_SECONDS * rho
    end = start + dt.timedelta(seconds=news_seconds+dly8_seconds+seal_seconds)
    admitted = end <= dt.datetime.fromisoformat(DEADLINE)
    return dict(stage='R8_news',state='ADMITTED' if admitted else 'NOT_ADMITTED_RESOURCE',admitted=admitted,
                start_utc=start.isoformat(),deadline_utc=DEADLINE,projected_end_utc=end.isoformat(),rho=rho,
                planning_rounds=NEWS_ROUNDS,proxy_round_seconds=PROXY_ROUND_SECONDS,
                b4_seconds=news_seconds,dly8_r8_seconds=dly8_seconds,seal_seconds=seal_seconds,
                reason=None if admitted else 'A8NR_RESOURCE_A8AM2',outcome_access=False,
                rule='A8.2(e) conservative two-wave planning at realised rho; R12b deadline inclusive')

def record_decision(state, ledger, rho, projection, start=None):
    path = Path(state)/'R8_ADMISSION.json'
    require(set(projection) == {'dly8_r8_seconds','seal_seconds','evidence'}, 'Reviewed projection fields required')
    for item in projection['evidence']: checked(item)
    require(projection['evidence'], 'Bind measured DLY8 and reviewed seal-step projection evidence')
    if path.exists():
        row = read_json(path)
        require(row['rho'] == rho and row['projection_inputs'] == projection,'R8 admission input drift')
    else:
        row = decision(start or now(),rho,projection['dly8_r8_seconds'],projection['seal_seconds'])
        rho_path=Path(state)/'RHO.json'
        rho_input=identity(rho_path) if rho_path.exists() else None
        if rho_input is not None: require(read_json(rho_path)['rho']==rho,'Realised rho metadata mismatch')
        row.update(projection_inputs=projection,rho_input=rho_input,budget_before_seconds=ledger.remaining())
        write_json(path,row,exclusive=True)
    decisions = ledger.data.setdefault('result_independent_admissions',{})
    item = identity(path)
    require('R8_news' not in decisions or decisions['R8_news'] == item,'Ledger R8 decision drift')
    decisions['R8_news'] = item
    ledger.save()  # succeeds before caller may launch any B4 wave
    return row
