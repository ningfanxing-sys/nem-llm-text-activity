
'Check manuscript sources, PDFs and source-file inventories.'
import argparse,hashlib,json,re,sys,shutil
from pathlib import Path

def digest(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def strict(root,out,package=None):
    root=Path(root).resolve();out=Path(out)
    if out.exists() or package and Path(package).exists():raise ValueError('strict outputs must be fresh')
    binding=json.loads((root/'table_results_support/CODE_BINDING.json').read_text());code=Path(binding['code_root'])
    for rel,sha in binding['code_sha256'].items():
        if digest(code/rel)!=sha:raise ValueError('consumer code drift')
    sys.path.insert(0,str(code));sys.path.append(str(root))
    import table_results_conf_results as F
    for name in ('check_arxiv.py','claims.sty'):
        if not (root/name).is_file() or digest(root/name)!=digest(F.MS/name):raise ValueError('strict checker/style byte drift')
    import check_arxiv as C
    import check_table_sources as K
    m=json.loads((root/'TABLE_RESULTS_K8_EXPECTATIONS.json').read_text())
    documents={s:C.check(root,s+'.tex') for s in ('main','supplement')}


    for stem,r in documents.items():
        source=(root/(stem+'.tex')).read_text()
        peers=re.findall(r'\\externaldocument\{(main|supplement)\}',source)
        external=set()
        for peer in peers:
            aux=root/(peer+'.aux')
            if aux.is_file():external.update(re.findall(r'\\newlabel\{([^}]+)\}',aux.read_text()))
        r['failures']=[f for f in r['failures'] if not(f['kind']=='undefined_reference' and f['detail'] in external)]
        r['status']='PASS' if not r['failures'] else 'FAIL'
    k8=K.check_documents(root,m,source_only=False)
    archive=root/'audit_archive.pdf';archive_log=root/'audit_archive.log'
    archive_pass=archive.is_file() and archive_log.is_file() and not re.search(r'undefined|Undefined control sequence|LaTeX Error|Package .* Error',archive_log.read_text(),re.I)


    archive_review=root/'ARCHIVE_REVIEW.json'
    archive_review_ok=False
    if archive_review.is_file() and archive.is_file():
        ar=json.loads(archive_review.read_text());archive_review_ok=ar.get('state')=='PASS' and ar.get('pdf_sha256')==digest(archive) and ar.get('references_verified') is True
    result={'state':'PASS' if all(r['status']=='PASS' for r in documents.values()) and k8['state']=='PASS' and archive_pass and archive_review_ok else 'FAIL','documents':documents,'K8':k8,'archive':{'compiled':archive_pass,'reviewed':archive_review_ok},'pdf_sha256':{s:digest(root/(s+'.pdf')) for s in ('main','supplement','audit_archive') if (root/(s+'.pdf')).is_file()},'paper_validator_used':False}
    out.mkdir(parents=True);(out/'STRICT_ARXIV.json').write_text(json.dumps(result,indent=2)+'\n')
    if package:
        if result['state']!='PASS':raise ValueError('strict arXiv gate failed; no source package created')
        package=Path(package);package.mkdir(parents=True);files={}
        for stem in ('main','supplement','audit_archive'):
            sources,deps=C.collect_sources(root,entry=stem+'.tex',include_attachments=stem=='main')
            if deps:raise ValueError('source-package dependency unresolved')
            files.update({p.relative_to(root):p for p in sources})
            text='\n'.join(sources.values());graphics,missing=C.graphic_dependencies(root,text)
            if missing:raise ValueError('package figures absent')
            files.update({p.relative_to(root):p for p in graphics})
            for bib in C.BIB_RE.findall(text):
                for rel in bib.split(','):
                    p=C.find_local(root,rel,('.bib',));files[p.relative_to(root)]=p
        for rel in ('claims.sty','elsarticle.cls'):
            if (root/rel).is_file():files[Path(rel)]=root/rel
        for rel,src in files.items():
            dest=package/rel;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(src,dest)
        (package/'PACKAGE_MANIFEST.json').write_text(json.dumps({str(r):digest(package/r) for r in files},indent=2)+'\n')
        result['package_sha256']=digest(package/'PACKAGE_MANIFEST.json')
        (out/'PACKAGE_VALIDATION.json').write_text(json.dumps({'state':'SOURCE_INVENTORY_PASS_COMPILE_AND_STRICT_RECHECK_REQUIRED','package_sha256':result['package_sha256'],'next':'compile fresh package, then check_arxiv main and supplement; require exact PASS before upload'},indent=2)+'\n')
    return result
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--copy',type=Path,required=True);p.add_argument('--out',type=Path,required=True);p.add_argument('--package',type=Path);a=p.parse_args();r=strict(a.copy,a.out,a.package);print(json.dumps(r));raise SystemExit(0 if r['state']=='PASS' else 2)
