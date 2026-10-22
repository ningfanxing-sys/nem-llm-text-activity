
'Check saved reference records against the source freeze.'
import argparse
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tempfile

QUERIES={'Clark2007':'10.1016/j.jeconom.2006.05.023','Andrews2000':'10.1111/1468-0262.00092'}

def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def query_snapshot(snapshot):
    sql="""SELECT i.key, f.fieldName, v.value FROM items i JOIN itemData d ON i.itemID=d.itemID
    JOIN fields f ON d.fieldID=f.fieldID JOIN itemDataValues v ON d.valueID=v.valueID
    WHERE i.itemID NOT IN (SELECT itemID FROM deletedItems) AND f.fieldName IN ('DOI','title')"""
    with sqlite3.connect(Path(snapshot).resolve().as_uri()+'?mode=ro',uri=True) as db:
        if db.execute('PRAGMA quick_check').fetchone()[0]!='ok':raise ValueError('copied Zotero snapshot integrity failure')
        rows=db.execute(sql).fetchall()
    items={}
    for key,field,value in rows:items.setdefault(key,{})[field]=value
    return sql,{key:[{'zotero_key':k,**v} for k,v in items.items() if v.get('DOI','').casefold().removeprefix('https://doi.org/')==doi] for key,doi in QUERIES.items()}


def verify_receipt(path,freeze=None):
    r=json.loads(Path(path).read_text())
    if r.get('schema')!='TABLE_RESULTS_REFERENCE_GATE_V1' or r.get('state')!='CHECKED_AT_FREEZE':raise ValueError('reference gate receipt missing')
    if r['queries']!=QUERIES or not r.get('sql') or len(r.get('snapshot_sha256',''))!=64:raise ValueError('reference gate query/snapshot identity missing')
    when=datetime.fromisoformat(r['queried_utc'])
    if freeze:
        if freeze.get('reference_gate_sha256')!=digest(path):raise ValueError('F freeze does not bind reference gate')
        stamp=freeze.get('created_utc',freeze.get('frozen_utc'))
        if not stamp:raise ValueError('F freeze time required for reference gate freshness')
        delta=datetime.fromisoformat(stamp.replace('Z','+00:00'))-when
        if not 0<=delta.total_seconds()<=3600:raise ValueError('reference check must be within one hour before F freeze')
    return r


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--zotero',type=Path,default=Path.cwd()/'Zotero/zotero.sqlite');p.add_argument('--out',type=Path,required=True);a=p.parse_args()
    if a.out.exists():raise SystemExit('refuse reference receipt overwrite')
    scratch=Path(tempfile.mkdtemp(prefix='TABLE_RESULTS_REFERENCE_GATE_'));snapshot=scratch/'zotero.sqlite'
    try:
        identities={}
        for suffix in ('','-wal','-shm'):
            src=Path(str(a.zotero)+suffix)
            if src.exists():shutil.copyfile(src,Path(str(snapshot)+suffix));identities[suffix or 'db']=digest(Path(str(snapshot)+suffix))
        sql,matches=query_snapshot(snapshot)
        receipt={'schema':'TABLE_RESULTS_REFERENCE_GATE_V1','state':'CHECKED_AT_FREEZE','queried_utc':datetime.now(timezone.utc).isoformat(),'queries':QUERIES,'sql':sql,'snapshot_sha256':digest(snapshot),'copied_file_sha256':identities,'matches':matches,'rule':'R13: library presence is recorded as evidence only; neither conditional clause activates','clauses_active':{'Clark2007':False,'Andrews2000':False},'code_sha256':digest(__file__)}
        with a.out.open('x') as f:json.dump(receipt,f,ensure_ascii=False,indent=2);f.write('\n')
    finally:
        try:cleanup=subprocess.run(['/usr/bin/trash',str(scratch)],capture_output=True,text=True,check=False);refused=cleanup.returncode!=0
        except OSError:refused=True
        if refused:
            print(json.dumps({'cleanup':'TRASH_REFUSED_SCRATCH_RETAINED','scratch':str(scratch)}))

if __name__=='__main__':main()
