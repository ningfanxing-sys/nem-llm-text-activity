'Extract the synthetic regression tests from saved source files.'
import ast
import hashlib
import json
from pathlib import Path
HERE=Path(__file__).absolute().parent
PARENT=HERE.parent

def _write(name,tree):
    (HERE/name).write_text('# Source-only inherited scientific fixture port; no tests on import.\n'+ast.unparse(ast.set_missing_locations(tree))+'\n')

def main():
    source=PARENT/'run_tests.py';tree=ast.parse(source.read_bytes())

    cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='Suite');cls.name='InheritedSuite'
    remove={'__init__','case','sample','t5_fixture','bind_temporary_T5','renew_temporary_T5','active_t5_fixture','exact_t5_list','review_readiness','scorer_preparation','pinned_fill_authority','pinned_fill_anchor_sidecar','pinned_fill_author_schema_drift','pinned_fill_shared_static_inputs','official_score_publication','official_score_main_scope','run','receipt','production_gate','load_launch'}
    cls.body=[n for n in cls.body if not isinstance(n,ast.FunctionDef) or n.name not in remove]
    fixture=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='fixture')
    fixture.body[0].iter=ast.parse("[*self.a.lock['sources'],*self.a.lock['authorities'],*self.a._ancestor_sources]",mode='eval').body

    for n in ast.walk(fixture):
        if isinstance(n,ast.Tuple):n.elts=[x for x in n.elts if not(isinstance(x,ast.Constant) and x.value=='tables/table_results_templates.json')]
        if isinstance(n,ast.Constant) and n.value=='shared/official/SEAL.json':n.value='project/fixtures/official/SEAL.json'


    idx=next(i for i,n in enumerate(fixture.body) if isinstance(n,ast.With) and any(isinstance(x,ast.Name) and x.id=='baseline' for x in ast.walk(n)))
    fixture.body=fixture.body[:idx]+ast.parse("self._science_fixture()\nreturn dict(exact_cloned_files=len(self.clone_bytes),mock_prediction_payloads=True)").body
    operations=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='operations')
    begin=next(i for i,n in enumerate(operations.body) if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='fill' for t in n.targets))
    end=next(i for i,n in enumerate(operations.body) if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='projection' for t in n.targets))
    operations.body[begin:end]=[]


    for n in ast.walk(operations):
        if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr=='write_output':
            n.args[2]=ast.parse("dict(synthetic_only=True,inputs=dict(self.official_items,scientific_views=self.views))",mode='eval').body

    tree.body=[n for n in tree.body if not(isinstance(n,ast.FunctionDef) and n.name=='main') and not(isinstance(n,ast.If) and '__name__' in ast.unparse(n.test))]
    class ImportPort(ast.NodeTransformer):
        def visit_Import(self,n):
            for alias in n.names:
                if alias.name=='consumer_roots':alias.name='fixture_api'
            return n
        def visit_Constant(self,n):
            if n.value=='CONSUMER_FREEZE.json':n.value='SCIENCE_FREEZE.json'
            return n
        def visit_Attribute(self,n):
            if isinstance(n.value,ast.Name) and n.value.id=='C' and n.attr=='FILL_REL':return ast.Constant(value='fixtures/REMOVED_WRITING_ROOT')
            return self.generic_visit(n)
    tree=ImportPort().visit(tree)
    _write('inherited_cases.py',tree)
    for name in ('tests_r8bpre.py','tests_g39.py'):
        t=ImportPort().visit(ast.parse((PARENT/name).read_bytes()))

        if name=='tests_r8bpre.py':
            for n in ast.walk(t):
                if isinstance(n,ast.Constant) and n.value=='bind_evidence.py':n.value='bootstrap.py'
        if name=='tests_g39.py':
            cl=next(n for n in t.body if isinstance(n,ast.ClassDef) and n.name=='RuntimeAuthorityTests')
            fn=next(n for n in cl.body if isinstance(n,ast.FunctionDef) and n.name=='_build_families')
            fn.body+=ast.parse("\nself.a._science_policy={'schema':'C_SCORING_RUNTIME_FAMILIES_V1','status':'REVIEWED_EXACT_OWNER_CONTRACTS','families':{}}\nfor family,root in self.roots.items():\n    document=self.documents[family]\n    names=[str(p.relative_to(root)) for p in self.members[family]]\n    document['declared_census']=names\n    _dump(self.freeze[family],document)\n    self.a._science_policy['families'][family]=dict(root=str(root.relative_to(self.a.q)),freeze=str(self.freeze[family].relative_to(self.a.q)),schema=SCHEMAS[family],state=STATES[family],inventory_field='sources' if family=='AP6' else 'files',inventory_format='relative_sha_dict' if family in ('AP5','AP6') else 'absolute_sha_list' if family=='notice_delays' else 'absolute_bytes_sha_list',inventory_base=str(self.ap.relative_to(self.a.q)) if family in ('AP5','AP6') else str(root.relative_to(self.a.q)),declared_census_field='declared_census',names=names)\n").body
        _write('inherited_'+name,t)


    from static_inventory import _expr
    reg=[]
    def collect(path,fn):
        t=ast.parse(path.read_bytes());env={}
        for n in t.body:
            if isinstance(n,ast.Assign):
                try:value=ast.literal_eval(n.value)
                except (ValueError,TypeError):continue
                for x in n.targets:
                    if isinstance(x,ast.Name):env[x.id]=value
        def walk(body,context):
            for n in body:
                if isinstance(n,ast.For):
                    for value in _expr(n.iter,context):
                        c=dict(context)
                        if isinstance(n.target,ast.Name):c[n.target.id]=value
                        elif isinstance(n.target,ast.Tuple):c.update({x.id:y for x,y in zip(n.target.elts,value)})
                        walk(n.body,c)
                elif isinstance(n,ast.Expr) and isinstance(n.value,ast.Call) and isinstance(n.value.func,ast.Attribute) and n.value.func.attr=='case':
                    name=_expr(n.value.args[0],context);callback=n.value.args[1]
                    if isinstance(callback,ast.Attribute):method=callback.attr;args=[];keywords={};wrapper=None
                    elif isinstance(callback,ast.Lambda):
                        body=callback.body
                        method=body.func.attr if isinstance(body,ast.Call) and isinstance(body.func,ast.Attribute) else None
                        args=[];keywords={};wrapper=ast.unparse(callback)

                        c=dict(context)
                        for arg,default in zip(callback.args.args[-len(callback.args.defaults):],callback.args.defaults):c[arg.arg]=_expr(default,c)
                        if isinstance(body,ast.Call):
                            for x in body.args:
                                try:args.append(_expr(x,c))
                                except (ValueError,KeyError):args.append({'expression':ast.unparse(x)})
                            for x in body.keywords:
                                try:keywords[x.arg]=_expr(x.value,c)
                                except (ValueError,KeyError):keywords[x.arg]={'expression':ast.unparse(x.value)}
                    else:raise ValueError('Unported callback '+ast.unparse(callback))
                    reg.append(dict(case_id=name,method=method,args=args,kwargs=keywords,callback=wrapper,bindings={k:v for k,v in context.items() if isinstance(v,(str,int,list,tuple,dict,bool,bytes))},source=str(path.relative_to(HERE.parents[4])),line=n.lineno,ast_sha256=hashlib.sha256(ast.dump(n,include_attributes=False).encode()).hexdigest()))
        walk(fn(t).body,env)
    collect(PARENT/'run_tests.py',lambda t:next(n for n in next(x for x in t.body if isinstance(x,ast.ClassDef) and x.name=='Suite').body if isinstance(n,ast.FunctionDef) and n.name=='run'))
    collect(PARENT/'tests_r8bpre.py',lambda t:next(n for n in t.body if isinstance(n,ast.FunctionDef) and n.name=='run'))
    (HERE/'INHERITED_CASE_CALLBACKS.json').write_text(json.dumps(dict(schema='C_SCORING_STATIC_CALLBACK_PORT_V1',rows=reg,executed=False),indent=2,default=lambda x:{'bytes_hex':x.hex()} if isinstance(x,bytes) else sorted(x) if isinstance(x,set) else str(x))+'\n')
if __name__=='__main__':main()
