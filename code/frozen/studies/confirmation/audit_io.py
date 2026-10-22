'Record the design files read during input preparation.'
from pathlib import Path
import os,json,datetime,hashlib
PROJ=Path(__file__).resolve().parents[3]
OUT=Path(__file__).resolve().parent
LOG=OUT/'OPENED_PATHS.jsonl'
def record(path, mode='text_read', purpose='confirmation design'):
 p=Path(path).resolve()
 row={'utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'worker':os.environ.get('CONF_WORKER','root'),'path':str(p),'mode':mode,'purpose':purpose}
 fd=os.open(LOG,os.O_CREAT|os.O_WRONLY|os.O_APPEND,0o644)
 try:os.write(fd,(json.dumps(row,ensure_ascii=False)+'\n').encode())
 finally:os.close(fd)
 return p
def read_text(path,purpose='confirmation design'):
 p=record(path,purpose=purpose)
 if ('semantic_validation' in str(p) and '/private/' in str(p)) or any(x in str(p) for x in ['/run/','/evaluation/','.env','auth.json']):raise PermissionError(p)
 if p.suffix not in {'.md','.py','.json','.csv','.txt','.toml','.yaml','.yml','.log','.jsonl'}:raise PermissionError('No general binary or panel reads')
 return p.read_text()
def sha256(path):
 p=record(path,'hash_only','input identity, no decoding')
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
 return h.hexdigest()
if __name__=='__main__':
 import sys
 for arg in sys.argv[1:]:
  p=Path(arg);print('\nPATH:',p);print(read_text(p))
