
'Run the synthetic table validation tests in one process.'
import argparse,json,os,re,subprocess,threading,time,sys,resource,hashlib,contextlib
from pathlib import Path
sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parent
PROJ=ROOT.parents[2]
def digest(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def run(scratch,out,collect_only=False,select=None):
    scratch,out=Path(scratch),Path(out)
    if scratch.exists() or out.exists():raise ValueError('fresh scratch and receipt directory required')
    if scratch.is_relative_to(PROJ) or not scratch.is_relative_to(Path('/private/tmp')):raise ValueError('scratch must be under /private/tmp')
    scratch.mkdir();out.mkdir(parents=True);sys.path.insert(0,str(ROOT))
    import freeze_table_results as W
    code=W.inventory();access=set();blocked=[];blocked_cache=[];samples=[];violations=[];stop=threading.Event()
    protected=PROJ/'studies/confirmation'
    def audit(event,args):
        if event!='open' or not isinstance(args[0],(str,bytes,os.PathLike)):return
        p=Path(os.fsdecode(args[0])).resolve()
        if p.is_relative_to(PROJ) and p.suffix=='.pyc':
            blocked_cache.append(str(p));raise FileNotFoundError('verified-source import: bytecode cache ignored')
        mode=args[1] or '';flags=args[2] or 0
        if not p.is_relative_to(PROJ):return
        write=any(x in mode for x in 'wax+') or flags&(os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC)
        forbidden=('semantic_validation/private' in str(p) or p.suffix in ('.xlsx','.xlsm') or p.name=='reviewer_1.csv')
        if p.is_relative_to(protected):
            rel=str(p.relative_to(protected));access.add(rel)
            forbidden |= bool(re.search(r'(?i)(?:^|/)(?:host_state|seals?|scores?|predictions?|prices?|truth|evaluation|run)(?:/|$)',rel))
            forbidden |= bool(re.search(r'(?i)(?:prediction|truth|price|daily.loss|scores?)(?:[_\.])',p.name)) and p.suffix not in ('.py','.md')
            if 'RESULT' in p.name and p.name!='CLK8_RESULT.json' and not (p.parent.name=='tests' and p.name in ('TEST_RESULTS.txt','TEST_RESULTS.json')):forbidden=True
        if write and not p.is_relative_to(ROOT):forbidden=True
        if forbidden:blocked.append(str(p));raise PermissionError('synthetic suite read/write input_checks: '+str(p))
    sys.addaudithook(audit)
    def check():
        raw=subprocess.run(['memory_pressure'],capture_output=True,text=True,check=True).stdout
        free=int(re.search(r'free percentage:\s*(\d+)%',raw)[1]);size=sum(p.stat().st_size for base in Path('/private/tmp').glob('TABLE_RESULTSSET5_*') if base.is_dir() for p in base.rglob('*') if p.is_file())
        priority=os.getpriority(os.PRIO_PROCESS,0);samples.append(dict(elapsed_seconds=round(time.monotonic()-start,2),memory_free_percent=free,nice=priority,scratch_bytes=size))
        if free<25 or size>=1_000_000_000 or priority<5:violations.append(samples[-1]);raise RuntimeError('resource input_checks violated')
    def monitor():
        while not stop.wait(20):
            try:check()
            except Exception as e:violations.append(str(e));os._exit(3)
    start=time.monotonic();check();thread=threading.Thread(target=monitor,daemon=True);thread.start()
    import pytest
    class Results:
        def __init__(self):self.reports=[];self.nodeids=[]
        def pytest_collection_finish(self,session):self.nodeids=[item.nodeid for item in session.items]
        def pytest_runtest_logreport(self,report):self.reports.append(dict(nodeid=report.nodeid,phase=report.when,outcome=report.outcome))
    results=Results()
    class Tee:
        def __init__(self,stream,log):self.stream=stream;self.log=log
        def write(self,value):self.log.write(value);self.log.flush();return self.stream.write(value)
        def flush(self):self.log.flush();self.stream.flush()
        def isatty(self):return False
    suites=['test_validation_group_4.py','test_validation_group_4_edges.py','test_template_validation.py']
    with (out/'RUN.log').open('x') as log:
        try:
            with contextlib.redirect_stdout(Tee(sys.stdout,log)),contextlib.redirect_stderr(Tee(sys.stderr,log)):
                args=['-q','-p','no:cacheprovider','--basetemp='+str(scratch/'pytest')]+[str(ROOT/name) for name in suites]
                if collect_only:args.insert(0,'--collect-only')
                if select:args+=['-k',select]
                rc=pytest.main(args,plugins=[results])
                print('TABLE_RESULTS_TEST_EVENTS='+json.dumps({'collected_nodeids':results.nodeids,'pytest_exit':int(rc),'test_cases':results.reports},separators=(',',':')))
        finally:stop.set();thread.join();check()
    from receipt_gates import collection_hash
    if collect_only:
        if rc or not results.nodeids:raise RuntimeError('collection failed')
        (ROOT/'TEST_CASES.json').write_text(json.dumps({'nodeids':results.nodeids,'collection_sha256':collection_hash(results.nodeids),'suite_sources_sha256':{name:digest(ROOT/name) for name in suites}},indent=2)+'\n')
        print(json.dumps({'state':'COLLECTED_NO_TESTS','count':len(results.nodeids)}));return 0
    changed=code!=W.inventory();passed=sum(r['phase']=='call' and r['outcome']=='passed' for r in results.reports);failed=sum(r['outcome']=='failed' for r in results.reports)
    record={'schema':'TABLE_RESULTSSET4_SYNTHETIC_TESTS_V2','state':'PASS' if not select and rc==0 and not failed and not violations and not blocked and not changed else 'FAIL','passed':passed,'failed':failed,'pytest_exit':int(rc),'elapsed_seconds':round(time.monotonic()-start,2),'peak_rss_bytes':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,'code_sha256':code,'code_unchanged':not changed,'single_test_process':True,'production_run':False,'freeze_written':False,'pdf_build':False,'human_workbook_access':False,'resource_samples':samples,'resource_violations':violations,'blocked_accesses':blocked,'bytecode_caches_ignored':sorted(set(blocked_cache)),'CONF_metadata_code_paths_read':sorted(access),'test_cases':results.reports,'collected_nodeids':results.nodeids,'collection_sha256':collection_hash(results.nodeids),'raw_log':{'path':str((out/'RUN.log').resolve().relative_to(ROOT)),'sha256':digest(out/'RUN.log')}}
    (out/'TEST_RECEIPT.json').write_text(json.dumps(record,indent=2)+'\n')
    branches=[]
    for p in (scratch/'pytest').glob('*/copy/TABLE_RESULTS_K8_EXPECTATIONS.json'):
        m=json.loads(p.read_text());k=json.loads(p.with_name('K8_RESULT.json').read_text());branches.append(dict(case=p.parent.parent.name,state=k['state'],abstract_level=m['abstract_level'],words=m['abstract_words'],characters=m['abstract_characters'],expectations_sha256=digest(p),claim_values_sha256=digest(p.parent/'TABLE_RESULTS_claim_values.tex')))
    (out/'SYNTHETIC_BRANCHES.json').write_text(json.dumps(branches,indent=2)+'\n')
    proof=list((scratch/'pytest').glob('*/ABSTRACT_BOUND.json'))
    if proof:(out/'ABSTRACT_BOUND.json').write_bytes(proof[0].read_bytes())
    catalog=list((scratch/'pytest').glob('*/EXCLUSION_CATALOG.json'))
    if catalog:(out/'EXCLUSION_CATALOG.json').write_bytes(catalog[0].read_bytes())
    print(json.dumps({k:record[k] for k in ('state','passed','failed','elapsed_seconds','peak_rss_bytes')}));return 0 if record['state']=='PASS' else 1
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--select');p.add_argument('--collect-only',action='store_true');p.add_argument('--scratch',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();raise SystemExit(run(a.scratch,a.out,a.collect_only,a.select))
