
'Compile the manuscript sources and validate the resulting package.'
import argparse,json,sys,re
from pathlib import Path
from strict_arxiv import digest

def validate(package,source_copy,out):
    package,source_copy,out=map(Path,(package,source_copy,out))
    if out.exists():raise ValueError('fresh package validation output required')
    listing=json.loads((package/'PACKAGE_MANIFEST.json').read_text())
    if not listing:raise ValueError('empty package')
    for rel,sha in listing.items():
        p=(package/rel).resolve()
        if not p.is_relative_to(package.resolve()) or not p.is_file() or digest(p)!=sha:raise ValueError('packaged source byte drift')
    binding=json.loads((source_copy/'table_results_support/CODE_BINDING.json').read_text());code=Path(binding['code_root'])
    for rel,sha in binding['code_sha256'].items():
        if digest(code/rel)!=sha:raise ValueError('consumer code drift')
    sys.path.insert(0,str(code));sys.path.append(str(source_copy))
    import check_arxiv as C
    import check_table_sources as K
    m=json.loads((source_copy/'TABLE_RESULTS_K8_EXPECTATIONS.json').read_text())
    documents={stem:C.check(package,stem+'.tex') for stem in ('main','supplement')}
    for stem,r in documents.items():
        peers=re.findall(r'\\externaldocument\{(main|supplement)\}',(package/(stem+'.tex')).read_text());labels=set()
        for peer in peers:
            p=package/(peer+'.aux')
            if p.is_file():labels.update(re.findall(r'\\newlabel\{([^}]+)\}',p.read_text()))
        r['failures']=[x for x in r['failures'] if not(x['kind']=='undefined_reference' and x['detail'] in labels)];r['status']='PASS' if not r['failures'] else 'FAIL'
    k8=K.check_documents(package,m,source_only=False)
    review=package/'ARCHIVE_REVIEW.json';archive=package/'audit_archive.pdf';log=package/'audit_archive.log'
    ar=json.loads(review.read_text()) if review.is_file() else {}
    archive_ok=archive.is_file() and log.is_file() and ar.get('state')=='PASS' and ar.get('references_verified') is True and ar.get('pdf_sha256')==digest(archive) and not re.search(r'undefined|LaTeX Error|Undefined control sequence',log.read_text(),re.I)
    result={'state':'PASS' if all(x['status']=='PASS' for x in documents.values()) and k8['state']=='PASS' and archive_ok else 'FAIL','documents':documents,'K8':k8,'archive_review_current':archive_ok,'package_manifest_sha256':digest(package/'PACKAGE_MANIFEST.json'),'pdf_sha256':{s:digest(package/(s+'.pdf')) for s in ('main','supplement','audit_archive') if (package/(s+'.pdf')).is_file()},'paper_validator_used':False}
    out.mkdir(parents=True);(out/'PACKAGE_STRICT.json').write_text(json.dumps(result,indent=2)+'\n');return result
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--package',type=Path,required=True);p.add_argument('--source-copy',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();r=validate(a.package,a.source_copy,a.out);print(json.dumps(r));raise SystemExit(0 if r['state']=='PASS' else 2)
