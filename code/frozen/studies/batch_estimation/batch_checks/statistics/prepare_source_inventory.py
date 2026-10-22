'Build an inventory of source files and AST definitions.'
import ast
import hashlib
import json
from pathlib import Path

HERE=Path(__file__).absolute().parent
PROJ=HERE.parents[4]
PARENT=HERE.parent

def main():
    source=PARENT/'consumer_roots.py';blob=source.read_bytes();tree=ast.parse(blob)
    declaration=json.loads((PROJ/'paper_plan/nof12_path_20261009/INVENTORY.json').read_text())
    rel=str(source.relative_to(PROJ));expected=declaration['source_snapshots'][rel]
    if hashlib.sha256(blob).hexdigest()!=expected['sha256']:raise RuntimeError('SET FIRST: audited C source drift')
    changes=[]


    cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='Association')
    methods={n.name:n for n in cls.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))}
    originals={k:hashlib.sha256(ast.dump(v,include_attributes=False).encode()).hexdigest() for k,v in methods.items()}
    def replace(name,text):
        old=methods[name];new=ast.parse(text).body[0];cls.body[cls.body.index(old)]=new
        methods[name]=new;changes.append(name)

    n=methods['sources'];cut=next(i for i,x in enumerate(n.body) if isinstance(x,ast.Assign)
                and any(isinstance(t,ast.Name) and t.id=='contract' for t in x.targets))
    n.body=n.body[:cut]+ast.parse("with self._validation():\n self._authority_files[str(HERE/'SOURCE_LOCK.json')]=identity(HERE/'SOURCE_LOCK.json')\nreturn self.lock").body
    changes.append('sources')
    init_method=methods['__init__']
    init_method.body[0]=ast.parse("self.project=no_symlink_path(project)").body[0]
    changes.append('__init__')
    replace('_need_validation',"def _need_validation(self):\n require(ACTIVE is self and self._released and self._validation_depth>0,'Internal seal helper requires verified scientific release/scope')")
    old_release=methods['release']

    start=next(i for i,x in enumerate(old_release.body) if isinstance(x,ast.Assign)
               and any(isinstance(t,ast.Name) and t.id=='frozen' for t in x.targets))
    end=next(i for i,x in enumerate(old_release.body) if isinstance(x,ast.Expr) and isinstance(x.value,ast.Call)
             and isinstance(x.value.func,ast.Attribute) and x.value.func.attr=='verify_host_parents')
    disk=ast.parse('def _disk_release(self,binding):\n pass').body[0]
    disk.body=ast.parse("for name in ('disk_freeze','t4c_binding'):\n checked(binding[name])\nrequire(Path(binding['disk_freeze']['path'])==self.d/'DISK_FREEZE.json' and Path(binding['t4c_binding']['path'])==self.d/'T4C_BINDING.json','Wrong disk release association')").body+old_release.body[start:end+1]
    cls.body.append(disk)
    replace('release','def release(self):\n return science_contract._release(self,runtime_sources.Core(globals()))')
    replace('verify_fill_authority',"def verify_science_authority(self,item):\n require(self._validation_depth>0,'Private scientific timestamp_checks verification scope required')\n require(Path(item['path'])==self.out/'SCIENCE_FREEZE.json','Wrong scientific timestamp_checks')\n checked(item)\n return read(item['path'])")
    replace('fill_t5_metadata',"def science_t5_metadata(self):\n require(self._released,'Scientific release required')\n paths=[]\n for item in self._science_binding['t5_metadata']:\n  p=checked(item)\n  require(self.metadata_root(p),'Scientific T5 member is not metadata')\n  paths.append(p)\n return paths")
    replace('_official_score','def _official_score(self,items):\n return science_contract._views(self,runtime_sources.Core(globals()),items)')
    replace('_check_official_score','def _check_official_score(self,certificate):\n try:\n  return science_contract._recheck(self,runtime_sources.Core(globals()),certificate)\n except BaseException:\n  self._official_ready=None\n  self._ap_runtime.revoke()\n  raise')
    cls.body+=ast.parse('\ndef official_views(self,original_inputs,r2_inputs,execution_identity):\n    self._official_ready=None\n    certificate=self._official_score(dict(original=original_inputs,r2=r2_inputs,execution=execution_identity))\n    self._official_ready=certificate\n    return certificate\ndef _verify_numeric_ancestors(self,item):\n    return science_contract._numeric_ancestors(self,runtime_sources.Core(globals()),item)\n').body


    class Adapt(ast.NodeTransformer):
        def visit_Constant(self,node):
            values={'CONSUMER_FREEZE.json':'SCIENCE_FREEZE.json','table_results_freeze':'numerical_inputs',
                    'TABLE_RESULTS_ASSOCIATION.json':'SCIENTIFIC_ASSOCIATION.json'}
            if isinstance(node.value,str) and node.value in values:node.value=values[node.value]
            return node
        def visit_Attribute(self,node):
            if node.attr=='fill_t5_metadata':node.attr='science_t5_metadata'
            return self.generic_visit(node)
    tree=Adapt().visit(tree)

    m=methods['metadata_root'];m.body.insert(1,ast.parse("if Path(path).is_relative_to(self.project/'tables'):return False").body[0]);changes.append('metadata_root')

    m=methods['_public_gate'];m.body.insert(0,ast.parse("require(self._released and self._science_binding.get('integration_complete') is True,'Scientific integration pending; no legacy fallback')").body[0]);changes.append('_public_gate')
    branch=next(n for n in m.body if isinstance(n,ast.If) and isinstance(n.test,ast.Name) and n.test.id=='t5')
    branch.body+=ast.parse("require(self._official_ready is not None,'Both verified official score views required before public post-score consumption')\nself._check_official_score(self._official_ready)").body


    m=methods['_authorize_read']
    index=next(i for i,n in enumerate(m.body) if isinstance(n,ast.If) and isinstance(n.test,ast.UnaryOp)
               and isinstance(n.test.operand,ast.Attribute) and n.test.operand.attr=='_guard_depth')
    m.body[index:index]=ast.parse("if str(p) not in self._authority_files:\n require(self._official_ready is not None,'No consumer payload read before verified original/capture/R2 completion')\n self._check_official_score(self._official_ready)").body
    changes.append('_authorize_read')

    m=methods['_call_public']
    main_try=next(n for n in m.body if isinstance(n,ast.Try) and any(isinstance(x,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='name' for t in x.targets) for x in n.body))
    tail=main_try.body[-1]
    assert isinstance(tail,ast.Return)
    main_try.body[-1:]=ast.parse("result=fn(*args,**kwargs)\nif t5:self._check_official_score(self._official_ready)\nreturn result").body
    changes.append('_call_public')


    m=methods['_t5_roots_body']
    fixed=next(n for n in m.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='fixed' for t in n.targets))
    fixed.value=ast.parse("['consumer_roots.py','SOURCE_LOCK.json','SCIENCE_FREEZE.json','SCORER_CODE_FREEZE.json','SCORER_BINDINGS.json','SCIENTIFIC_ASSOCIATION.json','SCIENTIFIC_ACCEPTANCE_RECEIPT.json','SOURCE_CLOSURE_RECEIPT.json','INDEPENDENT_REVIEW.json']",mode='eval').body
    changes.append('_t5_roots_body')

    for node in tree.body:
        if isinstance(node,ast.Assign):
            for target in node.targets:
                if isinstance(target,ast.Name) and target.id=='LIVE':node.value=ast.parse('HERE.parents[4]',mode='eval').body
                if isinstance(target,ast.Name) and target.id=='O_REL':node.value=ast.Constant(value='studies/batch_estimation/batch_checks/statistics')
        if isinstance(node,ast.Expr) and isinstance(node.value,ast.Call) and isinstance(node.value.func,ast.Attribute) and isinstance(node.value.func.value,ast.Name) and node.value.func.value.id=='ENTRIES' and node.value.func.attr=='update':
            node.value.keywords=[x for x in node.value.keywords if x.arg not in ('table_results_conf_results','receipt_gates')]

    tree.body=[n for n in tree.body if not(isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id in {'FILL_REL','FILL_FREEZE_SCHEMA','FILL_FREEZE_STATE'} for t in n.targets))]
    installed=methods['installed']
    for node in installed.body:
        if isinstance(node,ast.If) and any(isinstance(x,ast.Attribute) and x.attr=='synthetic' for x in ast.walk(node.test)):
            node.test=ast.parse('not preparation',mode='eval').body
    changes.append('installed')
    for n in ast.walk(installed):
        if isinstance(n,ast.List):
            n.elts=[e for e in n.elts if not any(isinstance(x,ast.Name) and x.id=='FILL_REL' for x in ast.walk(e))]
    tree.body.insert(2,ast.parse('import science_contract').body[0])
    tree=ast.set_missing_locations(tree)
    (HERE/'consumer_roots.py').write_text('# SCORING additive preparation capsule; no inference changes. Runtime pending.\n'+ast.unparse(tree)+'\n')

    lock=json.loads((PARENT/'SOURCE_LOCK.json').read_text());removed={}
    for field in ('sources','authorities'):
        for name in list(lock[field]):
            if name.startswith('tables/'):
                removed[field+'/'+name]=lock[field].pop(name)
    lock.pop('table_results_consumer');lock['state']='C_SCORING_SCIENTIFIC_SOURCE_PROPOSAL_NOT_RELEASED'
    lock['production_authority']=False
    ancestors={}
    for name in list(lock['sources']):
        if name.startswith('studies/inference/code/'):
            ancestors[name]=lock['sources'].pop(name)['identity']
    approved=json.loads((PROJ/'comparison_inputs/APPROVED_NEWS_SOURCE.json').read_text())
    for rel,digest in approved['source_pins'].items():
        payload=(PROJ/rel).read_bytes()
        if hashlib.sha256(payload).hexdigest()!=digest:raise RuntimeError('SET FIRST: R2 source drift: '+rel)
        pin=dict(bytes=len(payload),sha256=digest)
        if rel.startswith('studies/inference/'):
            ancestors[rel]=pin
        else:lock['sources'][rel]=dict(identity=pin,timestamp_checks='SCORING reviewed exact scientific source; release pending')
    contract_rel='comparison_inputs/APPROVED_NEWS_SOURCE.json'
    payload=(PROJ/contract_rel).read_bytes()
    lock['sources'][contract_rel]=dict(identity=dict(bytes=len(payload),sha256=hashlib.sha256(payload).hexdigest()),timestamp_checks='source contract, production_authority=false')


    out=ast.parse((HERE/'consumer_roots.py').read_bytes());cl=next(n for n in out.body if isinstance(n,ast.ClassDef) and n.name=='Association')
    init=next(n for n in cl.body if isinstance(n,ast.FunctionDef) and n.name=='__init__')
    init.body+=ast.parse("self._science_binding={}\nself._science_policy={'families':{}}\nself._scorer_contract={}\nself._official_ready=None\nself._ancestor_sources=read(HERE/'NUMERIC_ANCESTOR_PROPOSAL.json')['files']\nself._effective_sources=dict(self.lock['sources'])").body
    src=next(n for n in cl.body if isinstance(n,ast.FunctionDef) and n.name=='sources')
    src.body.insert(1,ast.parse("self._effective_sources=dict(self.lock['sources'])\nself._effective_sources.update({k:dict(identity=v) for k,v in self._ancestor_sources.items() if k.startswith('studies/inference/code/')})").body[0])

    src.body.insert(2,ast.parse("self._effective_sources.update({k:dict(identity=v) for k,v in self._ancestor_sources.items() if k.startswith('studies/inference/code/')})").body[0])
    for method in cl.body:
        if isinstance(method,ast.FunctionDef) and method.name in ('sources','verify_code'):
            for n in ast.walk(method):
                if isinstance(n,ast.Subscript) and isinstance(n.value,ast.Attribute) and n.value.attr=='lock' and isinstance(n.slice,ast.Constant) and n.slice.value=='sources':
                    n.__class__=ast.Attribute;n.value=ast.Name(id='self',ctx=ast.Load());n.attr='_effective_sources';n.ctx=ast.Load()
    src.body[1]=ast.parse("self._effective_sources=dict(self.lock['sources'])").body[0]


    private_names={'read','sha','identity','checked','write','contained','no_symlink_path','ConsumerModule','RoutedPath','RepinQPath','RepinQ'}
    class Privatize(ast.NodeTransformer):
        def visit_Attribute(self,node):
            if isinstance(node.value,ast.Name) and node.value.id=='runtime_sources' and node.attr in {'Core','RuntimeAuthorities'}:
                node.attr='_'+node.attr
            return self.generic_visit(node)
        def visit_Name(self,node):
            if node.id in private_names:node.id='_'+node.id
            return node
        def visit_FunctionDef(self,node):
            if node.name in private_names:node.name='_'+node.name
            return self.generic_visit(node)
        def visit_ClassDef(self,node):
            if node.name in private_names:node.name='_'+node.name
            return self.generic_visit(node)
    out=Privatize().visit(out)
    (HERE/'consumer_roots.py').write_text('# SCORING additive preparation capsule; no inference changes. Runtime pending.\n'+ast.unparse(ast.set_missing_locations(out))+'\n')
    (HERE/'SOURCE_LOCK.json').write_text(json.dumps(lock,ensure_ascii=False,sort_keys=True,indent=2)+'\n')
    (HERE/'NUMERIC_ANCESTOR_PROPOSAL.json').write_text(json.dumps({'schema':'C_SCORING_NUMERIC_ANCESTORS_V1','source_adopted':False,'files':ancestors,'downstream_successor_files':{},'scope':'unchanged original inference/code numerical ancestor identities only; independent review/adoption pending'},indent=2)+'\n')
    (HERE/'REMOVED_WRITING_DEPENDENCIES.json').write_text(json.dumps({'schema':'C_SCORING_WRITING_REMOVAL_AUDIT_V1','removed_lock_members':removed,'retained_history':True,'not_a_scientific_waiver':True},ensure_ascii=False,indent=2)+'\n')
    final=ast.parse((HERE/'consumer_roots.py').read_bytes());cl=next(n for n in final.body if isinstance(n,ast.ClassDef) and n.name=='Association')
    parity=[]
    for n in cl.body:
        if isinstance(n,ast.FunctionDef) and n.name in originals:
            now=hashlib.sha256(ast.dump(n,include_attributes=False).encode()).hexdigest()
            parity.append({'name':n.name,'original_ast_sha256':originals[n.name],'delivered_ast_sha256':now,'unchanged':now==originals[n.name]})
    (HERE/'INHERITED_AST_PARITY.json').write_text(json.dumps({'schema':'C_SCORING_STATIC_AST_PARITY_V1','parent_source':expected,'methods':parity,'named_boundary_changes':changes,'scientific_suite_run':False},indent=2)+'\n')

if __name__=='__main__':main()
