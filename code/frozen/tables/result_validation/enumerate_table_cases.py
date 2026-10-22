
'Run the exhaustive enumeration of table rendering cases.'
import argparse, contextlib, json, os, sys, time, threading, subprocess, re, resource
from pathlib import Path
from functools import lru_cache
sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT))
import table_results_conf_results as F
import receipt_gates as G
import freeze_table_results as W
from table_renderer.constraint_contract import specification2_plan, specification2
from table_results_test_conf_results import fixture
from exhaustive_proof import Enumerator


def run(out):
    out=Path(out);F.require(out.is_relative_to(ROOT) and not out.exists(),'fresh proof output directory required')
    out.mkdir(parents=True);inventory=W.inventory();start=time.monotonic()
    plan=specification2_plan();effective=specification2();binding=effective or plan
    F.timestamp_checks(frozen=False)
    F.require(bool(F.specification_words()),'verified specification 1 required')
    protected=F.PROJ/'studies/confirmation';blocked=[];samples=[];stop=threading.Event()
    def audit(event,args):
        if event!='open' or not isinstance(args[0],(str,bytes,os.PathLike)): return
        p=Path(os.fsdecode(args[0])).resolve()
        if p.suffix in ('.xlsx','.xlsm') or p.name=='reviewer_1.csv' or 'semantic_validation/private' in str(p):
            blocked.append(str(p));raise PermissionError('forbidden proof input')
        if p.is_relative_to(protected) and re.search(r'(?i)(?:^|/)(?:host_state|seals?|scores?|predictions?|prices?|truth|evaluation|run)(?:/|$)',str(p.relative_to(protected))):
            blocked.append(str(p));raise PermissionError('forbidden proof payload')
    sys.addaudithook(audit)
    def check():
        text=subprocess.run(['memory_pressure'],capture_output=True,text=True,check=True).stdout
        sample=dict(elapsed_seconds=round(time.monotonic()-start,2),memory_free_percent=int(re.search(r'free percentage:\s*(\d+)%',text)[1]),nice=os.getpriority(os.PRIO_PROCESS,0))
        samples.append(sample);F.require(sample['memory_free_percent']>=25 and sample['nice']>=5,'proof resource gate')
    def monitor():
        while not stop.wait(20):
            try: check()
            except Exception: os._exit(3)
    check();worker=threading.Thread(target=monitor,daemon=True);worker.start()


    original_form=F.form;original_sentence=F.sentence;original_inherited=F.inherited_form;original_words=F.words;original_specification_words=F.specification_words
    specification1_sha=F.sha256(F.inference_design/'ADDENDUM_A8_SPECIFICATION_1_FREEZE.json')
    cached_specification_words=lru_cache(maxsize=2)(original_specification_words)
    F.specification_words=cached_specification_words
    @lru_cache(maxsize=100000)
    def cached_form(identity,items):return original_form(identity,**dict(items))
    @lru_cache(maxsize=100000)
    def cached_sentence(identity,items):return original_sentence(identity,**dict(items))
    @lru_cache(maxsize=1000)
    def cached_inherited(identity,items):return original_inherited(identity,**dict(items))
    cached_words=lru_cache(maxsize=100000)(original_words)
    F.words=cached_words
    F.form=lambda identity,**slots:cached_form(identity,tuple(sorted(slots.items())))
    F.sentence=lambda identity,**slots:cached_sentence(identity,tuple(sorted(slots.items())))
    F.inherited_form=lambda identity,**slots:cached_inherited(identity,tuple(sorted(slots.items())))
    class Tee:
        def __init__(self,stream,log):self.stream=stream;self.log=log
        def write(self,x):self.log.write(x);self.log.flush();return self.stream.write(x)
        def flush(self):self.log.flush();self.stream.flush()
    try:
        with (out/'PROOF.log').open('x') as log,contextlib.redirect_stdout(Tee(sys.stdout,log)):
            enum=Enumerator(fixture)
            branches=enum.audit_domain(plan)
            cached_form.cache_clear();cached_sentence.cache_clear()
            result=enum.run()
            print('P8R7_DOMAIN='+json.dumps(result['domains'],sort_keys=True))
            print('P8R7_BRANCHES='+json.dumps(branches,sort_keys=True))
            print('P8R7_MAXIMA='+json.dumps({k:{m:v[m] for m in ('words','characters','sentence_max')} for k,v in result['levels'].items()},sort_keys=True))
    except Exception as exc:
        (out/'FAILURE.json').write_text(json.dumps(dict(state='FAIL',error=str(exc),code_sha256=inventory,resources=samples),indent=2)+'\n');raise
    finally:
        F.form=original_form;F.sentence=original_sentence;F.inherited_form=original_inherited;F.words=original_words;F.specification_words=original_specification_words
        stop.set();worker.join();check()
    F.require(W.inventory()==inventory and not blocked,'proof code drift/access violation')
    F.require(F.sha256(F.inference_design/'ADDENDUM_A8_SPECIFICATION_1_FREEZE.json')==specification1_sha,'frozen specification 1 drift during memoised proof')
    F.require(original_specification_words()==cached_specification_words(),'specification 1 verified vocabulary changed')
    levels={k:{f:v[f] for f in ('words','characters','sentence_max','sentence_witness','witnesses','texts')} for k,v in result['levels'].items()}
    proof=dict(schema=G.PROOF_SCHEMA,state=result['state'],mode='COMPLETE_FROZEN_REACHABLE_DOMAIN',bindings=G.proof_bindings(inventory,dict(specification2=binding)),domain=G.required_proof_domain(),coverage=dict(all_levels=True,exhaustive=True,refused_branches_checked=True,attained_witnesses_verified=True,first_qualifying_level_verified=True),levels=levels,proof_engine=dict(path='exhaustive_proof.py',sha256=F.sha256(ROOT/'exhaustive_proof.py')),proof_spec=dict(path='PROOF_RECEIPT_SPEC.md',sha256=F.sha256(ROOT/'PROOF_RECEIPT_SPEC.md')),raw_log=dict(path=str((out/'PROOF.log').relative_to(ROOT)),sha256=F.sha256(out/'PROOF.log')),signatures_evaluated=result['signatures_evaluated'])
    target=out/'P8R7_COMPLETE_PROOF.json';target.write_text(json.dumps(proof,indent=2)+'\n')

    G.validate_proof(target,ROOT,inventory,dict(specification2=binding),dict(abstract_proof_sha256=F.sha256(target),abstract_proof_verified=True))
    summary=dict(state=result['state'],proof_sha256=F.sha256(target),proof_receipt=proof['raw_log'],elapsed_seconds=round(time.monotonic()-start,2),signatures_evaluated=result['signatures_evaluated'],levels={k:{m:v[m] for m in ('words','characters','sentence_max')} for k,v in levels.items()},resources=samples,peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,blocked_accesses=blocked,specification2_effective=effective is not None,specification2_source_plan=plan,domain_audit=branches,independent_acceptance_created=False)
    (out/'SUMMARY.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps({k:summary[k] for k in ('state','levels','signatures_evaluated','elapsed_seconds')}))

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--out',type=Path,required=True);args=parser.parse_args();run(args.out.resolve())
