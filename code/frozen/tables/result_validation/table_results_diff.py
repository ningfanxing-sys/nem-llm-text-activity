
'Compare result sources against the scoring receipt snapshot.'
import argparse
import csv
import difflib
import io
import json
from pathlib import Path
import table_results_conf_results as F
from check_table_sources import macro_calls,source_problems


def changed_paragraphs(old,new):
    a=old.split('\n\n');b=new.split('\n\n');out=[]
    for op,i,j,k,l in difflib.SequenceMatcher(None,a,b).get_opcodes():
        if op!='equal':out.extend(b[k:l])
    return out


def audit(reference_snapshot,after,manifest,anchor,category='non-claim edit',later_inputs=None):
    F.require(category in ('fill','refill','non-claim edit'),'invalid PSB3 category')
    F.require(anchor['score_receipt_sha256']==manifest['record']['identities']['source_receipt_sha256'],'PSB3 SCORE_RECEIPT anchor differs')
    F.require(set(reference_snapshot)==set(anchor['source_sha256']),'PSB3 snapshot file set differs')
    F.require(all(F.text_hash(v)==anchor['source_sha256'][k] for k,v in reference_snapshot.items()),'PSB3 source snapshot drift')
    if category=='refill':
        F.require(later_inputs and set(later_inputs)<= {'label_scoring','KCX','PC','matched_controls','PV'},'refill needs specified later inputs')
        F.require(all(isinstance(x,dict) and x.get('verified') is True and x.get('sha256') for x in later_inputs.values()),'unverified later refill input')
    F.require(set(reference_snapshot)<=set(after),'PSB3 cannot remove source files')
    rows=[];scope={}
    for rel,new in sorted(after.items()):
        old=reference_snapshot.get(rel,'');paragraphs=changed_paragraphs(old,new)
        if old==new:continue
        generated=manifest.get('generated_sha256',{}).get(rel)
        if generated:
            F.require(F.text_hash(new)==generated,'generated fill bytes differ from specified renderer')
        else:
            if category=='non-claim edit':F.require(macro_calls(old)==macro_calls(new),'postscore claim macro changed: '+rel)
            for text in paragraphs:F.require(not source_problems(text,manifest['registry'],manifest['record'],manifest['facts']),'postscore claim edit refused: '+rel)
        scope[rel]=paragraphs
        rows.append({'file':rel,'category':category,'score_receipt_sha256':anchor['score_receipt_sha256'],'old_sha256':F.text_hash(old),'new_sha256':F.text_hash(new),'diff':''.join(difflib.unified_diff(old.splitlines(True),new.splitlines(True),fromfile='a/'+rel,tofile='b/'+rel))})
    return {'schema':'TABLE_RESULTS_PSB3_V1','state':'PASS','anchor':anchor,'changes':rows,'postscore_changed':scope}


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    for k in ('reference_snapshot','after','expectations','anchor','out'):p.add_argument('--'+k,type=Path,required=True)
    p.add_argument('--refill',action='store_true');p.add_argument('--later-inputs',type=Path)
    a=p.parse_args(argv);F.timestamp_checks()
    anchor=F.strict_json(a.anchor);manifest=F.strict_json(a.expectations)
    reference_snapshot={k:(a.reference_snapshot/k).read_text() for k in anchor['source_sha256']}
    after={str(k.relative_to(a.after)):k.read_text() for k in a.after.rglob('*.tex')}
    result=audit(reference_snapshot,after,manifest,anchor,'refill' if a.refill else 'non-claim edit',F.strict_json(a.later_inputs) if a.later_inputs else None)
    F.require(not a.out.exists(),'refuse PSB3 receipt overwrite');a.out.mkdir(parents=True)
    (a.out/'TABLE_RESULTS_POSTSCORE_DIFF.json').write_text(json.dumps(result,indent=2)+'\n')
    with (a.out/'TABLE_RESULTS_PSB_TRACE.csv').open('x',newline='') as f:
        w=csv.DictWriter(f,fieldnames=['file','category','score_receipt_sha256','old_sha256','new_sha256']);w.writeheader();w.writerows({k:r[k] for k in w.fieldnames} for r in result['changes'])
    return 0

if __name__=='__main__':raise SystemExit(main())
