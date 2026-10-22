
'Merge table trace records while preserving the numerical CSV schema.'
import argparse,csv,json,hashlib,re
from pathlib import Path
NUMERIC=['location','number','source_file','source_field','note']
PSB=['file','category','score_receipt_sha256','old_sha256','new_sha256']

def digest(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def read_rows(p,fields):
    with p.open() as f:
        r=csv.DictReader(f)
        if r.fieldnames!=fields:raise ValueError('trace schema mismatch: '+str(p))
        return list(r)

def finalize(root,out):
    root=Path(root).resolve();out=Path(out);support=root/'table_results_support'
    if out.exists():raise ValueError('refuse trace output overwrite')
    rows=read_rows(support/'LEGACY_NUMBERS_TRACE.csv',NUMERIC)
    if (support/'LEGACY_MS15_TRACE.csv').is_file():rows+=read_rows(support/'LEGACY_MS15_TRACE.csv',NUMERIC)
    psb=read_rows(root/'TABLE_RESULTS_PSB_TRACE.csv',PSB)
    for r in psb:
        p=(root/r['file']).resolve()
        if not p.is_relative_to(root) or not p.is_file() or digest(p)!=r['new_sha256']:raise ValueError('PSB source drift')


    manifest=json.loads((root/'TABLE_RESULTS_K8_EXPECTATIONS.json').read_text())
    for key,value in manifest['registry'].items():
        for token in re.findall(r'(?<![A-Za-z])[-+]?\d[\d,]*(?:\.\d+)?(?:/\d+)?',value):
            rows.append(dict(location='TABLE_RESULTS claim '+key,number=token,source_file='TABLE_RESULTS_K8_EXPECTATIONS.json',source_field='registry.'+key,note='RS8 claim registry; source receipt '+manifest['record']['identities']['source_receipt_sha256']))

    old=dict(re.findall(r'\\newlabel\{([^}]+)\}\{\{([^}]+)\}',(support/'LEGACY_main.aux').read_text()))
    archive=dict(re.findall(r'\\newlabel\{([^}]+)\}\{\{([^}]+)\}',(root/'audit_archive.aux').read_text()))
    expected={k for k in old if k.startswith(('fig:','tab:'))}
    if expected-set(archive):raise ValueError('legacy archive display lost')
    mapping=[]
    with (support/'LEGACY_MAP.csv').open() as f:
        for r in csv.DictReader(f):mapping.append(dict(r,TABLE_RESULTS_document='audit_archive',TABLE_RESULTS_number=archive.get(r['label'],'')))
    out.mkdir(parents=True)
    with (out/'NUMBERS_TRACE.csv').open('x',newline='') as f:
        w=csv.DictWriter(f,fieldnames=NUMERIC);w.writeheader();w.writerows(rows)
    if mapping:
        with (out/'REPRO_MAP.csv').open('x',newline='') as f:
            w=csv.DictWriter(f,fieldnames=list(mapping[0]));w.writeheader();w.writerows(mapping)
    result={'state':'PASS','legacy_rows_preserved':len(read_rows(support/'LEGACY_NUMBERS_TRACE.csv',NUMERIC)),'psb_rows':len(psb),'archive_displays_preserved':len(expected),'numeric_sha256':digest(out/'NUMBERS_TRACE.csv'),'psb_sha256':digest(root/'TABLE_RESULTS_PSB_TRACE.csv')}
    (out/'TRACE_RECEIPT.json').write_text(json.dumps(result,indent=2)+'\n');return result
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--copy',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();print(json.dumps(finalize(a.copy,a.out)))
