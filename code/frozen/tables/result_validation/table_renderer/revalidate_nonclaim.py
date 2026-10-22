
'Validate wording edits against the saved scientific registry.'
import argparse,json,shutil,sys
from pathlib import Path

def revalidate(reference_snapshot,edited,out,author_metadata=None):
    reference_snapshot,edited,out=map(lambda p:Path(p).resolve(),(reference_snapshot,edited,out))
    if out.exists() or out==reference_snapshot or out==edited:raise ValueError('fresh output required')
    b=json.loads((reference_snapshot/'table_results_support/CODE_BINDING.json').read_text());sys.path.insert(0,b['code_root']);sys.path.append(str(reference_snapshot))
    import table_results_conf_results as F
    from table_results_diff import audit
    import check_table_sources as K
    m=F.strict_json(reference_snapshot/'TABLE_RESULTS_K8_EXPECTATIONS.json');old=F.strict_json(reference_snapshot/'TABLE_RESULTS_RECEIPT.json')
    for rel,sha in {**m['generated_sha256'],**m['prefill_sha256']}.items():F.require(F.sha256(reference_snapshot/rel)==sha,'before-copy byte drift')
    sources={str(p.relative_to(reference_snapshot)):p.read_text() for p in reference_snapshot.rglob('*.tex')}
    after={rel:(edited/rel).read_text() for rel in sources}
    F.require(set(sources)=={str(p.relative_to(edited)) for p in edited.rglob('*.tex')},'nonclaim source set changed')


    for rel in m['generated_sha256']:F.require(after.get(rel)==sources.get(rel),'generated scientific source edit: '+rel)
    anchor={'score_receipt_sha256':m['record']['identities']['source_receipt_sha256'],'source_sha256':{k:F.text_hash(v) for k,v in sources.items()}}
    changes=audit(sources,after,m,anchor,'non-claim edit')
    if author_metadata:
        meta=F.strict_json(author_metadata);F.require(set(meta)=={'declarations','recorded_by','recorded_utc'},'author metadata schema')
        F.require(bool(meta['recorded_by']) and bool(meta['recorded_utc']),'author metadata provenance')
        F.require(set(meta['declarations'])==set(m['record']['declarations']),'author declaration slot census')
        for key,value in meta['declarations'].items():
            F.require(isinstance(value,str) and value.strip() and not K.source_problems(value,{},m['record'],m['facts']),'author metadata contains scientific claim or placeholder')
            m['registry']['global/declaration_'+key+'/reading']=value
        m['record']['declarations']=meta['declarations'];after['TABLE_RESULTS_claim_values.tex']=F.claim_definitions(m['registry'])
        m['generated_sha256']['TABLE_RESULTS_claim_values.tex']=F.text_hash(after['TABLE_RESULTS_claim_values.tex'])
    for rel in changes['postscore_changed']:
        if rel in m['prefill_sha256']:m['prefill_sha256'][rel]=F.text_hash(after[rel])


    m['nonclaim_version']={'prior_receipt_sha256':F.sha256(reference_snapshot/'TABLE_RESULTS_RECEIPT.json'),'prior_prefill_sha256':F.strict_json(reference_snapshot/'TABLE_RESULTS_K8_EXPECTATIONS.json')['prefill_sha256'],'changes':changes,'author_metadata_sha256':F.sha256(author_metadata) if author_metadata else None}
    m['postscore_changed']=changes['postscore_changed']
    shutil.copytree(edited,out,ignore=shutil.ignore_patterns('main.pdf','supplement.pdf','audit_archive.pdf','*.aux','*.bbl','*.blg','*.log','*.synctex*','qa*'))
    for rel,text in after.items():(out/rel).write_text(text)
    (out/'TABLE_RESULTS_K8_EXPECTATIONS.json').write_text(json.dumps(m,ensure_ascii=False,indent=2)+'\n')


    import csv
    psb=reference_snapshot/'TABLE_RESULTS_PSB_TRACE.csv';fields=['file','category','score_receipt_sha256','old_sha256','new_sha256']
    current={}
    if psb.is_file():
        with psb.open() as f:
            reader=csv.DictReader(f);F.require(reader.fieldnames==fields,'prior PSB schema')
            current={row['file']:row for row in reader}
        shutil.copyfile(psb,out/'table_results_support/PRIOR_TABLE_RESULTS_PSB_TRACE.csv')
    for rel,text in after.items():
        if text!=sources[rel]:current[rel]=dict(file=rel,category='non-claim edit',score_receipt_sha256=anchor['score_receipt_sha256'],old_sha256=F.text_hash(sources[rel]),new_sha256=F.text_hash(text))
    with (out/'TABLE_RESULTS_PSB_TRACE.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(current[k] for k in sorted(current))
    changes['author_metadata_sha256']=F.sha256(author_metadata) if author_metadata else None
    (out/'TABLE_RESULTS_POSTSCORE_DIFF.json').write_text(json.dumps(changes,indent=2)+'\n')
    check=K.check_documents(out,m,source_only=True);F.require(check['state']=='PASS','new nonclaim source K8: '+str(check['problems']))
    old.update(state='NONCLAIM_SOURCE_REVALIDATED_REBUILD_REQUIRED',generated_sha256=m['generated_sha256'],prefill_sha256=m['prefill_sha256'],prior_receipt_sha256=m['nonclaim_version']['prior_receipt_sha256'],nonclaim_diff_sha256=F.text_hash(json.dumps(changes,sort_keys=True)))
    (out/'TABLE_RESULTS_RECEIPT.json').write_text(json.dumps(old,indent=2)+'\n');(out/'NONCLAIM_K8.json').write_text(json.dumps(check,indent=2)+'\n');return old
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--before',type=Path,required=True);p.add_argument('--edited',type=Path,required=True);p.add_argument('--out',type=Path,required=True);p.add_argument('--author-metadata',type=Path);a=p.parse_args();revalidate(a.reference_snapshot,a.edited,a.out,a.author_metadata)
