'Prepare the inventory of numerical source modules.'
import ast
import hashlib
import json
from pathlib import Path
HERE=Path(__file__).absolute().parent
PROJ=HERE.parents[4]

def main():
    src=HERE.parent/'runtime_sources.py';payload=src.read_bytes()
    expected=json.loads((HERE.parent/'G39_TARGETED_RESULTS.json').read_text())['current_delivered_source_identities']['runtime_sources.py']
    if hashlib.sha256(payload).hexdigest()!=expected['sha256']:raise RuntimeError('SET FIRST: G39 source drift')
    tree=ast.parse(payload);cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='RuntimeAuthorities')
    originals={n.name:hashlib.sha256(ast.dump(n,include_attributes=False).encode()).hexdigest() for n in cls.body if isinstance(n,ast.FunctionDef)}
    def replace(name,code):
        old=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name==name);cls.body[cls.body.index(old)]=ast.parse(code).body[0]
    tree.body=[n for n in tree.body if not(isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id in {'CONTRACTS','AP5_FIXED','AP6_FIXED','RD_FIXED'} for t in n.targets))]
    replace('family','''def family(self,path):
        raw=os.fsdecode(os.fspath(path));p=Path(os.path.abspath(raw))
        rows=self.a._science_policy.get('families',{})
        exact=[name for name,row in rows.items() if p==self.a.q/row['freeze']
               or p in {self.a.q/row['root']/leaf for leaf in row['names']}]
        self.c.require(len(exact)<=1,'Ambiguous runtime family alias')
        if exact:return exact[0]
        return next((name for name,row in rows.items() if p.is_relative_to(self.a.q/row['root'])),None)
''')
    replace('census','''def census(self,family):
        policy=self.a._science_policy['families'][family]
        root=self.a.q/self.relative(policy['root'])
        names=policy['names']
        self.c.require(isinstance(names,list) and names and len(names)==len(set(names)),'Empty/duplicate declared exact census')
        result={}
        for name in names:
            self.c.require(not any(x in name for x in '*?[]'),'Wildcard is not an exact runtime name')
            result[name]=self.canonical(root/self.relative(name))
        self.c.require(any(p.suffix=='.py' for p in result.values()),'Runtime census has no code')
        return result
''')
    replace('_snapshot_json',"def _snapshot_json(self,path,item):\n        self.c.require(self.c.ACTIVE is self.a and self.a._validation_depth>0,'Private verified timestamp_checks decoder only')\n        allowed={self.a.out/'T5_BINDING.json',*(self.a.q/row['freeze'] for row in self.a._science_policy['families'].values())}\n        self.c.require(self.canonical(path) in allowed,'Not an exact timestamp_checks metadata path')\n        payload=Path(path).read_bytes()\n        self.c.require(len(payload)==item['bytes'] and hashlib.sha256(payload).hexdigest()==item['sha256'],'Metadata identity drift')\n        def pairs(rows):\n            result={}\n            for key,value in rows:\n                self.c.require(key not in result,'Duplicate JSON timestamp_checks key')\n                result[key]=value\n            return result\n        return json.loads(payload,object_pairs_hook=pairs,parse_constant=lambda value: (_ for _ in ()).throw(self.c.Refusal('Nonfinite JSON')))\n")
    replace('_candidate','''def _candidate(self,families):
        t5,value,indexed=self._t5();identities={};declarations={}
        for family in families:
            policy=self.a._science_policy['families'][family]
            self.c.require(set(policy)=={'root','freeze','schema','state','inventory_field','inventory_format','inventory_base','declared_census_field','names'},'Exact reviewed owner policy required')
            root=self.a.q/self.relative(policy['root']);freeze=self.canonical(self.a.q/self.relative(policy['freeze']))
            self.c.require(freeze.is_relative_to(root),'Freeze outside family root')
            fi=self.c.identity(freeze);self.c.require(indexed.get(str(freeze))==fi,'Freeze missing/drifted/not T5-listed')
            f=self._snapshot_json(freeze,fi)
            self.c.require(f.get('schema')==policy['schema'] and f.get('state')==policy['state'],'Wrong/unfrozen successor')
            self.c.require(self.utc(f.get('frozen_utc'))<self.utc(value['utc']),'Successor freeze after/equal T5')
            census=self.census(family)
            declared=f.get(policy['declared_census_field'])
            self.c.require(isinstance(declared,list) and len(declared)==len(set(declared)) and set(declared)==set(census),'Declared census missing/extra/duplicate')
            inventory=f.get(policy['inventory_field']);pins={}
            if policy['inventory_format']=='relative_sha_dict':
                self.c.require(isinstance(inventory,dict),'Exact relative SHA dictionary required')
                base=self.a.q/self.relative(policy['inventory_base'])
                for name,digest in inventory.items():
                    p=self.canonical(base/self.relative(name));self.c.require(p.is_relative_to(root),'Family inventory escaped root')
                    key=str(p.relative_to(root));self.c.require(key not in pins,'Duplicate family member');pins[key]={'sha256':digest}
            else:
                self.c.require(policy['inventory_format'] in {'absolute_sha_list','absolute_bytes_sha_list'} and isinstance(inventory,list),'Exact declared inventory format required')
                fields={'path','sha256'} if policy['inventory_format']=='absolute_sha_list' else {'path','bytes','sha256'}
                for row in inventory:
                    self.c.require(isinstance(row,dict) and set(row)==fields,'Wrong inventory identity fields')
                    p=self.canonical(row['path']);self.c.require(p.is_relative_to(root),'Family inventory escaped root')
                    key=str(p.relative_to(root));self.relative(key);self.c.require(key not in pins,'Duplicate family member')
                    pins[key]={k:v for k,v in row.items() if k!='path'}
            self.c.require(set(pins)==set(census),'Omitted/extra runtime inventory')
            for key,p in census.items():
                actual=self.c.identity(p);pin=pins[key]
                self.c.require(actual['sha256']==pin['sha256'] and ('bytes' not in pin or type(pin['bytes']) is int and actual['bytes']==pin['bytes']),'Runtime source identity drift')
                self.c.require(indexed.get(str(p))==actual,'Runtime member not exact T5-listed')
                self.c.require(str(p) not in identities,'Overlapping family identity')
                identities[str(p)]=actual
            self.c.require(str(freeze) not in identities,'Freeze/member alias')
            identities[str(freeze)]=fi;declarations[family]=tuple(sorted(census))
        for path,item in identities.items():self.c.require(self.c.identity(self.canonical(path))==item,'Runtime changed during verification')
        self.c.require(self.c.identity(self.a.out/'T5_BINDING.json')==t5,'T5 changed during verification')
        return dict(families=tuple(families),t5=t5,files=identities,census=declarations)
''')
    core=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='Core')
    get=next(n for n in core.body if isinstance(n,ast.FunctionDef) and n.name=='__getattr__')
    get.body.insert(0,ast.parse("if name in {'read','sha','identity','checked','write','contained','no_symlink_path'}:name='_'+name").body[0])
    core.name='_Core';cls.name='_RuntimeAuthorities'
    (HERE/'runtime_sources.py').write_text('# SCORING explicit-census G39 successor; no downstream SOURCE_LOCK bytes.\n'+ast.unparse(ast.set_missing_locations(tree))+'\n')
    final=ast.parse((HERE/'runtime_sources.py').read_bytes());cls=next(n for n in final.body if isinstance(n,ast.ClassDef) and n.name=='_RuntimeAuthorities')
    rows=[]
    for n in cls.body:
        if isinstance(n,ast.FunctionDef):
            digest=hashlib.sha256(ast.dump(n,include_attributes=False).encode()).hexdigest()
            rows.append(dict(name=n.name,original_ast_sha256=originals[n.name],delivered_ast_sha256=digest,unchanged=digest==originals[n.name]))
    (HERE/'G39_AST_PARITY.json').write_text(json.dumps(dict(schema='C_SCORING_G39_STATIC_AST_V1',parent=expected,methods=rows,scientific_suite_run=False),indent=2)+'\n')
if __name__=='__main__':main()
