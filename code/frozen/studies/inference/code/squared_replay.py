'Recompute squared losses using the frozen scoring function.'
import ast,hashlib
from pathlib import Path
from types import SimpleNamespace
import numpy as np,pandas as pd
import read_comparisons as P
from frozen_losses import native_functions


def calculate(sc,main,batch,native=None):
    path=P.BATCH_CODE/'score_batch.py'
    tree=ast.parse(path.read_text());fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='descriptive_scores')
    rel=str(path.relative_to(P.PROJ));pin=P.strict_json(P.HERE/'DEPENDENCY_PINS.json')['exact_ast'][rel]['descriptive_scores']
    P.require(hashlib.sha256(ast.dump(fn,include_attributes=False).encode()).hexdigest()==pin,'Frozen squared AST drift')
    loop=next(n for n in fn.body if isinstance(n,ast.For) and isinstance(n.target,ast.Name) and n.target.id=='source')


    body=[n for n in loop.body if not (isinstance(n,ast.For) and isinstance(n.target,ast.Tuple) and isinstance(n.target.elts[0],ast.Name) and n.target.elts[0].id=='key')]
    node=ast.For(target=loop.target,iter=loop.iter,body=body,orelse=loop.orelse,type_comment=None);ast.copy_location(node,loop);ast.set_missing_locations(node)
    ns=dict(native=native if native is not None else SimpleNamespace(**native_functions()),np=np,pd=pd,scoring=sc,main=main,batch=batch,SEED=20260919,squared={'primary':{},'R8':{}},FAMILIES=__import__('batch_layers').specified_families())
    exec(compile(ast.Module(body=[node],type_ignores=[]),str(path),'exec'),ns)
    return ns['squared']


def replay(sc,records):
    actual=calculate(sc,records['seal'],records['batch_seal'])
    proof={}
    for name in ('primary','R8'):
      for task,rows in actual[name].items():
          saved=records['batch']['squared_loss'][name][task]
          P.require([(r['arm'],r['reference']) for r in rows]==[(r['arm'],r['reference']) for r in saved],'Squared pair census drift')
          for new,old in zip(rows,saved):
              key=name+'/'+task+'/'+new['arm']+'-'+new['reference']
              ok=all(new.get(k)==old.get(k) for k in ('state','effect','dm'))
              proof[key]='PASS' if ok else 'DEVIATION'
              if not ok:new.update(state='NOT_RUN',effect=None,dm={},reason='A8NR_PARITY')
              if new['state']=='COMPUTED' and new.get('dm',{}).get('p_two_sided') is None:new.update(state='NOT_RUN',effect=None,dm={},reason='fail')
          records['batch']['squared_loss'][name][task]=rows
    return proof
