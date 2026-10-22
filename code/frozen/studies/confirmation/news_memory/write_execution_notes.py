"""Apply the exact resource-only CONFX8 HOST_RUN patch after install archived the parent.
python update_host_run.py --preview   # writes CONFX8/HOST_RUN_DRAFT.md and HOST_RUN_DIFF.patch only
python update_host_run.py             # coordinator only; not run during preparation
"""
import argparse, difflib, hashlib, json
from pathlib import Path
HERE=Path(__file__).resolve().parent;CONF=HERE.parent

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def render(text):
    # Current instructions point to X8; retain CONFX7 historical descriptions verbatim.
    text=text.replace('`CONFX7/features_completion_rule.py`','`CONFX8/features_completion_rule.py`')
    text=text.replace('`CONFX7/measurement_gate.py`','`CONFX8/measurement_gate.py`')
    text=text.replace('`CONF/CONFX7/host_chain_CONFX7.sh`','`CONF/CONFX8/host_chain_CONFX8.sh`')
    text=text.replace('/CONF/CONFX7/host_chain_CONFX7.sh','/CONF/CONFX8/host_chain_CONFX8.sh')
    old='   **Memory rule for steps 4–6 (CONFX7; the CONFX6 hold is resolved).**'
    assert text.count(old)==1
    new='''   **CONFX8 resource-only amendment (2026-10-04).**
   - CONFX7 full-shape news fits failed at 2 GiB anonymous. CONFX8 raises only the news per-fit stop to **3.5 GiB (3,758,096,384 bytes)**. LEAR keeps 2 GiB; serial notices keep 6.6 GiB; the tree hard stop (6.6 GiB), throttle (6.0 GiB), reserved admission, stages and budget stay unchanged.
   - News projections now have measured lifetime-peak floors (wide 3,300,741,536 bytes; narrow 2,487,864,800 bytes), with the inherited 1.08 margin and bank-cell growth bound. The pool still allows up to seven workers; full-shape news is likely one or two fits at once. Recompute concurrency and 24-hour feasibility from CONFX8 measurements.
   - The feature path is byte-identical to non-switch CONFX7. CONFX8 accepts the registered CONFX6 feature completion with the inherited resume-comparison proof and the verified CONFX7→CONFX8 chain, or a CONFX7/CONFX8-bound completion.
   - The old pre-CONFX7 reference worker receives a 3.5 GiB **measurement-only RSS override** inside CONFX8/measure_fit_memory.py. Production code contains no measurement override.
   - Before the chain: install CONFX8, update this document, verify/freeze the exact six-step amendment chain, make scratch roots, run CONFX8 memory/speed measurements and both feasibility scripts, require CONFX8/measurement_gate.py to accept, then retain the T4 timestamp note. Exact commands: CONFX8/REPORT_zh.md. Missing or failed production-shape proofs stop the chain.

   **Memory rule inherited from CONFX7 (historical; news limit amended above).**'''
    text=text.replace(old,new)
    old='   - The adapter verifier checks the exact archived chain: input-bound original → CONFX3 → CONFX4 → CONFX5 → CONFX6 → CONFX7.'
    assert text.count(old)==1;text=text.replace(old,old[:-1]+' → CONFX8.')
    old='   - A successful run writes `COMPLETE_features.json`.'
    start=text.index(old);end=text.index('\n',start)
    text=text[:start]+old+' `CONFX8/features_completion_rule.py` accepts the CONFX8 freeze, the registered CONFX7 freeze with byte-identical feature-path proof, or the registered CONFX6 freeze with the inherited CONFX7 resume-comparison proof and verified parent links.'+text[end:]
    text=text.replace('applies `CONFX8/features_completion_rule.py`;','applies `CONFX8/features_completion_rule.py`;')
    text=text.replace('`MEMORY_MEASUREMENTS.json`, `SPEED_MEASUREMENTS_A3.json` and both feasibility files exist',
                      '`CONFX8/MEMORY_MEASUREMENTS.json`, `CONFX8/SPEED_MEASUREMENTS_A3.json` and both CONFX8 feasibility files exist')
    text=text.replace('Review [CONFX7 execution note]', 'Review [CONFX8 execution note](CONFX8/EXECUTION_NOTE.md), [CONFX7 execution note]')
    return text

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--preview',action='store_true');a=p.parse_args()
    before=json.loads((HERE/'PRE_IDENTITIES.json').read_text());path=CONF/'HOST_RUN.md'
    if sha(path)!=before['HOST_RUN.md']:raise SystemExit('HOST_RUN.md differs from registered pre-CONFX8 bytes')
    old=path.read_text();new=render(old)
    if a.preview:
        (HERE/'HOST_RUN_DRAFT.md').write_text(new)
        (HERE/'HOST_RUN_DIFF.patch').write_text(''.join(difflib.unified_diff(old.splitlines(True),new.splitlines(True),fromfile='CONF/HOST_RUN.md',tofile='CONFX8/HOST_RUN_DRAFT.md')))
    else:
        archived=HERE/'archive/pre_CONFX8/HOST_RUN.md'
        if not archived.exists() or sha(archived)!=before['HOST_RUN.md']:raise SystemExit('parent HOST_RUN archive missing/drifted')
        if (HERE/'AMENDED_ADAPTER_CHAIN.json').exists():raise SystemExit('chain already frozen; refusing host document mutation')
        path.write_text(new)
    print(json.dumps({'preview':a.preview,'sha256':hashlib.sha256(new.encode()).hexdigest()}))

if __name__=='__main__':main()
