'Extract file-access checks from the saved validation source.'
import ast
from pathlib import Path
HERE=Path(__file__).absolute().parent

def main():
    tree=ast.parse((HERE.parent/'review_isolator.py').read_bytes())
    tree.body=[n for n in tree.body if not isinstance(n,ast.FunctionDef) or n.name not in {'run_suite_once','main'}]
    tree.body=[n for n in tree.body if not(isinstance(n,ast.If) and '__name__' in ast.unparse(n.test))]
    cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='ReviewIsolator')
    init=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='__init__')
    start=next(i for i,n in enumerate(init.body) if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='lock_path' for t in n.targets))


    stop=next(i for i,n in enumerate(init.body) if isinstance(n,ast.Assign) and any(isinstance(t,ast.Attribute) and t.attr=='runtime' for t in n.targets))
    prefix=init.body[:start];suffix=init.body[stop:]
    for n in ast.walk(init):
        if isinstance(n,ast.Constant) and n.value=='studies/batch_estimation/batch_checks':n.value+='/'+'statistics'
    replacement=ast.parse("\nlock_path=self.code/'SOURCE_LOCK.json'\nlock=json.loads(lock_path.read_bytes())\nself.pinned_roots=[];self.fill_rel=None\nself.lock_sha256=digest(lock_path);self.allowed={lock_path}\nfor rel,item in lock['sources'].items():\n    path=self.project/rel\n    if path.stat().st_size!=item['identity']['bytes'] or digest(path)!=item['identity']['sha256']:raise ValueError('Public source drift')\n    self._approve_live(path)\nfor rel,pin in json.loads((self.code/'NUMERIC_ANCESTOR_PROPOSAL.json').read_bytes())['files'].items():\n    path=self.project/rel\n    if path.stat().st_size!=pin['bytes'] or digest(path)!=pin['sha256']:raise ValueError('Numeric ancestor drift')\n    self._approve_live(path)\nfor rel,pin in lock['authorities'].items():\n    path=self.project/rel\n    if path.stat().st_size!=pin['bytes'] or digest(path)!=pin['sha256']:raise ValueError('Code timestamp_checks drift')\n    self._approve_live(path)\n    value=json.loads(path.read_bytes())\n    if rel.endswith('fitting/CODE_FREEZE.json'):\n        row=value['test_receipts_provenance']['tests'];p=Path(row['path'])\n        if p!=self.project/'studies/batch_estimation/fitting/TEST_RESULTS.json' or p.stat().st_size!=row['bytes'] or digest(p)!=row['sha256']:raise ValueError('Frozen numeric test source drift')\n        self._approve_live(p)\n    for field in ('files','code_sha256'):\n        for name,pin in value.get(field,{}).items():\n            p=path.parent/name\n            expected=pin if isinstance(pin,str) else pin.get('sha256')\n            if expected and self._inventory_metadata(p):\n                if digest(p)!=expected:raise ValueError('Code metadata drift')\n                self._approve_live(p)\nmanifest=json.loads((self.code/'PUBLIC_RUNTIME_SOURCE_MANIFEST.json').read_bytes())\nself._approve_live(self.code/'PUBLIC_RUNTIME_SOURCE_MANIFEST.json')\nfor rel,pin in manifest['files'].items():\n    p=self.code/rel\n    if p.stat().st_size!=pin['bytes'] or digest(p)!=pin['sha256']:raise ValueError('C exact source drift')\n    self._approve_live(p)\nfor rel in json.loads((self.code/'FIXTURE_PUBLIC_SOURCE_CENSUS.json').read_bytes())['files']:\n    self._approve_live(self.project/rel)\nself.allowed_directories={p.parent for p in self.allowed}\nself.allowed_directories.update({self.project,self.code,self.project/'studies/batch_estimation/fitting/code',self.project/'studies/batch_estimation/fitting/tests'})\n").body
    init.body=prefix+replacement+suffix


    (HERE/'run_synthetic_checks.py').write_text('# Check file access during synthetic numerical tests.\n'+ast.unparse(ast.set_missing_locations(tree))+'\n\n'+"def main(argv=None):\n    import os\n    if os.environ.get('SCORING_PHASE','prepare')!='accept':raise PermissionError('Prepare cannot run the suite')\n    from tests_science import main as run\n    return run(argv)\nif __name__=='__main__':raise SystemExit(main())\n")
if __name__=='__main__':main()
