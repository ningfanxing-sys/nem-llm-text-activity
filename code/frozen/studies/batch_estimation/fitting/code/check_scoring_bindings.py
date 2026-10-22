"""Additive root association for REPIN8's reviewed outer startup gate."""
from a8_common import *
import argparse

def visibility(code):
    data=(OUT/'code/runner.py').read_bytes()
    require(hashlib.sha256(data).hexdigest()==code['code_sha256']['code/runner.py'],'Frozen candidate runner drift')
    import ast
    node=next(n for n in ast.parse(data).body if isinstance(n,ast.FunctionDef) and n.name=='fitting_argv')
    namespace={'Path':Path};exec(compile(ast.Module(body=[node],type_ignores=[]),str(OUT/'code/runner.py'),'exec'),namespace)
    sys.path.insert(0,str(Q/'REPIN8'));from overlap import BOOTSTRAP_CODE
    for rel,entry in [('A2LABEL','a2label_predict.py'),('CONF/A4/PCX','pcx_runner.py')]:
        stage=Q/rel/'REPIN_CONFX8';config=read_json(stage/'SOURCE_BINDING.json')
        argv=[sys.executable,'-B','-P','-c',BOOTSTRAP_CODE,str(Path(config['old'])/'code'/entry),str(Q/'REPIN8'),str(stage),entry,'run']
        require(namespace['fitting_argv'](argv),'Frozen candidate cannot see re-pin: '+rel)

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--execute',action='store_true');args=parser.parse_args()
    require(os.getpriority(os.PRIO_PROCESS,0)>=10,'Production nice 10 required')
    require(args.execute and os.environ.get('A8BATCH_HOST_RUN')=='1','Separate host authorization required')
    # Verify identity plan before importing the live outer launcher; no ledger writes.
    code=read_json(OUT/'CODE_FREEZE.json');binding=read_json(checked(code['bindings']))
    from repin_plan import validate_plan,validate_effective
    validate_plan(binding);validate_effective(binding)
    sys.path.insert(0,str(Q/'REPIN8'))
    from overlap import clear_control_environment
    clear_control_environment()
    outer=module(Q/'REPIN8/postscore_launch.py','_a8fix4_repin_outer')
    outer.preflight()  # unchanged REPIN8 PCX -> LABEL idle/spawn/parity gates
    visibility(code)
    source=OUT/'code/postscore_host.py'
    require(sha(source)==code['code_sha256']['code/postscore_host.py'],'Frozen candidate post-score controller drift')
    os.execve(sys.executable,[sys.executable,'-B',str(source),'--execute'],dict(os.environ,PYTHONDONTWRITEBYTECODE='1',A2LABEL_HOST_RUN='1'))

if __name__=='__main__':main()
