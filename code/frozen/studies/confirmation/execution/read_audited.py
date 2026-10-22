from pathlib import Path
import json, hashlib, sys
ROOT=Path(__file__).resolve().parent
for arg in sys.argv[1:]:
 p=Path(arg).resolve(); b=p.read_bytes()
 with (ROOT/'OPENED_PATHS_root.jsonl').open('a') as h:
  h.write(json.dumps({'path':str(p),'purpose':'design_code_identity_read','sha256':hashlib.sha256(b).hexdigest(),'bytes':len(b),'window_values_read':False})+'\n')
 print('\nFILE',p,'\n'+b.decode())
