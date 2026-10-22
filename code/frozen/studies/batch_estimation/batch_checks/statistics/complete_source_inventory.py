'Complete the static source inventory with a second AST check.'
import ast
from pathlib import Path
HERE=Path(__file__).absolute().parent

def main():
    p=HERE/'consumer_roots.py';tree=ast.parse(p.read_bytes())
    cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='Association')
    methods={n.name:n for n in cls.body if isinstance(n,ast.FunctionDef)}
    def replace(name,code):
        old=methods[name];new=ast.parse(code).body[0];cls.body[cls.body.index(old)]=new;methods[name]=new
    tree.body[2:2]=ast.parse('import output_lifecycle\nimport scorer_metadata').body
    methods['__init__'].body+=ast.parse('self._native_scope=None\nself._bootstrap_depth=0\nself._bootstrap_source_ready=False\nself._t5_value={}').body
    replace('_need_validation','''def _need_validation(self):
        require(ACTIVE is self and self._validation_depth>0 and (self._released or (self._bootstrap_depth>0 and self._bootstrap_source_ready)), 'Verified scientific release or authenticated private bootstrap required')
''')
    cls.body+=ast.parse('''
def _ready_inputs(self,inputs):
    require(self._official_ready is not None,'Original/capture/R2 completion required')
    self._check_official_score(self._official_ready)
    require(inputs.get('score_receipt')==self._scorer_contract['original']['receipt_identity'], 'Original receipt cannot be substituted or relabelled')
    require(inputs.get('seal')==self._scorer_contract['original']['seal_identity'], 'Original seal identity drift')
    require(inputs.get('score_report')==self._scorer_contract['original']['report_identity'], 'Original report identity drift')
    require(inputs.get('scientific_views')==self._official_ready['view_inputs'], 'Both score views and execution must be committed in published evidence')
    return self._official_ready
''').body

    m=methods['_call_public']
    first=m.body[0]
    first.body[2]=ast.parse("require(self._official_ready is not None,'Both official views required')\nself._check_official_score(self._official_ready)\nrequire(item==self._scorer_contract['original']['receipt_identity'],'Frozen batch scorer original receipt mismatch')\nself._producer_official=self._official_ready").body[0]
    first.body[3:3]=ast.parse("self._check_official_score(self._official_ready)\nrequire(item==self._scorer_contract['original']['receipt_identity'],'Frozen batch scorer original receipt mismatch')\nself._producer_official=self._official_ready").body
    for n in ast.walk(m):
        if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr=='_official_score':
            n.func.attr='_ready_inputs'
    m=methods['_consumer_execution']
    producer=next(n for n in ast.walk(m) if isinstance(n,ast.If) and isinstance(n.test,ast.Compare) and any(isinstance(x,ast.Attribute) and x.attr=='_producer_official' for x in ast.walk(n.test)))
    producer.body=ast.parse("require(self._official_ready is not None,'Both official views required')\nself._check_official_score(self._official_ready)\nself._producer_official=self._official_ready").body
    m=methods['_run_output_producer']
    for n in ast.walk(m):
        if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr=='_official_score':n.func.attr='_ready_inputs'
    m=methods['_source_delivery_body']
    m.body[1]=ast.parse("require((self._bootstrap_depth>0 and self._bootstrap_source_ready and self._validation_depth>0) or (self._released and not self._preparing),'Released consumer or authenticated private bootstrap required')").body[0]

    m=methods['_authorize_read']
    idx=next(i for i,n in enumerate(m.body) if isinstance(n,ast.If) and isinstance(n.test,ast.Attribute) and n.test.attr=='_preparing')
    m.body[idx:idx]=ast.parse("if self._bootstrap_depth:\n require(self._bootstrap_source_ready and self._validation_depth>0,'Bootstrap is private metadata-only verification')\n return").body
    idx=next(i for i,n in enumerate(m.body) if isinstance(n,ast.If) and isinstance(n.test,ast.Attribute) and n.test.attr=='_validation_depth' and i>idx)
    m.body[idx+1:idx+1]=ast.parse("if self._native_scope is not None:\n output_lifecycle._read(self,p)\n return").body
    m=methods['patch'];m.body.insert(0,ast.parse("if module.__name__=='scorer_freeze':scorer_metadata._install(self,module)").body[0])
    audit=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='_audit')
    for n in ast.walk(audit):
        if isinstance(n,ast.If) and isinstance(n.test,ast.BoolOp) and any(isinstance(x,ast.Attribute) and x.attr=='_preparing' for x in ast.walk(n.test)):
            n.test=ast.BoolOp(op=ast.And(),values=[n.test,ast.parse('not ACTIVE._bootstrap_depth',mode='eval').body])
    openbranch=next(n for n in ast.walk(audit) if isinstance(n,ast.If) and isinstance(n.test,ast.Compare) and ast.unparse(n.test)=="event == 'open'")
    idx=next(i for i,n in enumerate(openbranch.body) if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='associated' for t in n.targets))
    openbranch.body[idx:idx]=ast.parse("if writing and ACTIVE._native_scope is not None:\n output_lifecycle._write(ACTIVE,p)\n if not reading:return").body

    audit.body+=ast.parse("if ACTIVE._native_scope is not None and event in ('os.rename','os.link','os.mkdir','os.remove','os.rmdir'):\n for raw in args[:2 if event in ('os.rename','os.link') else 1]:\n  if isinstance(raw,(str,bytes,os.PathLike)):output_lifecycle._write(ACTIVE,_no_symlink_path(raw))").body
    p.write_text('# SCORING additive scientific association; no inference changes.\n'+ast.unparse(ast.set_missing_locations(tree))+'\n')
if __name__=='__main__':main()
