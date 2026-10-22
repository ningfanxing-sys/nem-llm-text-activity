'Validate forecast grids and compute news losses on the selected issue days.'
from __future__ import annotations
import ast
from copy import deepcopy
from datetime import date, timedelta
import hashlib
import json
import math
from pathlib import Path
from types import SimpleNamespace
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
PROJ = HERE.parents[2]
PINS = json.loads((HERE/'PARENT_PINS.json').read_text())
NATIVE = 'studies/confirmation/execution/seal_score.py'
SCORING = 'studies/confirmation/code/scoring.py'
A2_PATH = 'studies/confirmation/primary_tests/code/primary_comparisons.py'
AP_PATH = 'studies/inference/code/read_comparisons.py'
A3_PATH = 'studies/confirmation/sensitivity_tests/code/sensitivity_comparisons.py'
OPTIONAL = 'studies/inference/code/optional_losses.py'
BATCH_SCORE = 'studies/batch_scoring/code/batch_score.py'
LABEL_SCORE = 'studies/label_scoring/code/score_labels.py'
LOSSES = 'studies/inference/code/frozen_losses.py'
KEYS = ['origin', 'target_time', 'region', 'horizon']


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def source(relative):
    path = PROJ/relative
    if path.is_symlink() or not path.resolve().is_relative_to(PROJ.resolve()) \
            or digest(path) != PINS[relative]:
        raise PermissionError('R2 inherited source drift: '+relative)
    return path


def inherit(relative, names, namespace, replacements=None):

    path = source(relative)
    nodes = [n for n in ast.parse(path.read_bytes()).body
             if isinstance(n, (ast.FunctionDef, ast.ClassDef)) and n.name in names]
    if {n.name for n in nodes} != set(names):
        raise PermissionError('R2 inherited function census drift')
    for old, new, expected in replacements or ():
        constants = [n for node in nodes for n in ast.walk(node)
                     if isinstance(n, ast.Constant) and n.value == old]
        if len(constants) != expected:
            raise PermissionError('R2 finite inherited delta drift')
        for node in constants:
            node.value = new
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), 'exec'), namespace)
    return namespace


def evidence_module():
    relative = 'availability_checks/postcut_reading.py'
    env = dict(Path=Path, date=date, timedelta=timedelta, hashlib=hashlib,
               json=json, PROJ=PROJ)
    tree = ast.parse(source(relative).read_bytes())
    for node in tree.body:
        if isinstance(node,ast.Assign) and len(node.targets)==1 \
                and isinstance(node.targets[0],ast.Tuple) \
                and [getattr(n,'id',None) for n in node.targets[0].elts]==['START','END']:
            env['START'],env['END']=ast.literal_eval(node.value)
        if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                and isinstance(node.targets[0], ast.Name) and node.targets[0].id in {
                    'START','END','WINDOW_START','CUTOFF','RECORD_PATH','RECORD_SHA',
                    'PAGE_SHA','OFFICIAL_URL','CUTOFF_QUOTE'}:
            env[node.targets[0].id] = ast.literal_eval(node.value)
    inherit(relative, ('sha256_bytes','calendar_days','official_evidence',
                       'verify_evidence','day_set'), env)
    return SimpleNamespace(**env)


def day_set():
    return evidence_module().day_set()


def issue_positions(panel):

    days = panel['target_day'].astype(str)
    expected = evidence_module().calendar_days('2026-03-01', '2026-09-30')
    counts = panel.groupby('target_day', sort=True).size()
    if list(counts.index) != expected or not np.all(counts.to_numpy() == 72):
        raise ValueError('R2 view requires the fully verified original 214-day grid')
    origin = pd.to_datetime(panel['origin'], utc=True).dt.tz_convert('Australia/Brisbane')
    if not origin.dt.strftime('%Y-%m-%d').equals(days) \
            or not origin.eq(origin.dt.normalize()).all():
        raise ValueError('R2 issue origin/day identity drift')
    return np.flatnonzero(days.isin(day_set()).to_numpy())


def diagnostics(panel, predicted, raw, root, tag):
    clips = []
    for (arm, seed, variant), values in predicted.items():
        frame = panel[KEYS+['target_day']].copy()
        frame['prediction'], frame['raw_prediction'] = values, raw[(arm, seed, variant)]
        frame['raw_below_lower'] = frame.raw_prediction < -1000.
        frame['raw_above_upper'] = frame.raw_prediction > 17500.
        frame['final_lower_hits'] = frame.prediction == -1000.
        frame['final_upper_hits'] = frame.prediction == 17500.
        fields = ['raw_below_lower','raw_above_upper','final_lower_hits','final_upper_hits']
        if root is not None:
            path = Path(root)/(tag('news',arm,seed,variant)+'__BOUND_DIAGNOSTIC_KEYS.parquet')
            path.parent.mkdir(parents=True,exist_ok=True)
            frame.loc[frame[fields].any(axis=1)].to_parquet(path,index=False)
        for grouping in (['region','horizon'], ['target_day'], []):
            groups = frame.groupby(grouping,sort=True) if grouping else [((),frame)]
            for values_, group in groups:
                if not isinstance(values_,tuple): values_ = (values_,)
                row = dict(zip(grouping,values_))
                row.update(source='news',arm=arm,seed=seed,variant=variant,
                           eligible_predictions=len(group),clipping_operations=0)
                row.update({name:int(group[name].sum()) for name in fields})
                clips.append(row)
    return clips


def native_namespace(original):
    'Validate matched forecast grids and select the numerical loaders.'
    ns = dict(original)
    parent_read, parent_mask = original['_read_task_data'], original['_matched_mask']
    cache = {}

    def read(source_, receipt, diagnostic_root=None):
        if source_ != 'news':
            return parent_read(source_,receipt,diagnostic_root)
        values = parent_read(source_,receipt,None)
        full, old_days, old_counts, predicted, identities, _, raw = values
        if old_days != evidence_module().calendar_days('2026-03-01','2026-09-30') \
                or old_counts != [72]*214:
            raise ValueError('R2 original verification failed')
        for ident in identities.values():
            predicted_days=pd.read_parquet(ident['path'],columns=['target_day'])['target_day'].astype(str)
            if not predicted_days.equals(full['target_day'].astype(str)):
                raise ValueError('R2 original prediction issue-day identity failed')

        if any(np.asarray(a).shape != (len(full),) or not np.isfinite(a).all()
               for a in [*predicted.values(),*raw.values()]):
            raise ValueError('R2 complete original final/raw prediction integrity failed')
        ix = issue_positions(full)
        panel = full.iloc[ix].reset_index(drop=True)
        prediction = {k:v[ix].copy() for k,v in predicted.items()}
        raw_view = {k:v[ix].copy() for k,v in raw.items()}
        cache.clear(); cache.update(full=full, panel=panel.copy(), ix=ix)
        clips = diagnostics(panel,prediction,raw_view,diagnostic_root,ns['tag'])
        return panel,day_set(),[72]*len(day_set()),prediction,identities,clips,raw_view

    def mask(manifest, source_, panel):
        if source_ != 'news': return parent_mask(manifest,source_,panel)
        if not cache or not panel[KEYS].equals(cache['panel'][KEYS]):
            raise ValueError('R2 matched mask must share the verified loader view')
        full_mask = parent_mask(manifest,source_,cache['full'])
        return full_mask[cache['ix']].copy()

    ns['_read_task_data'], ns['_matched_mask'] = read, mask


    return ns


def scoring_successor(parent):
    ns = dict(parent.specified_daily_inference.__globals__)
    inherit(SCORING, ('specified_daily_inference',), ns,
            [('2026-03-01',day_set()[0],1)])
    result = SimpleNamespace(**vars(parent))
    news_inference=ns['specified_daily_inference']
    def specified(losses,days,task,permit,identity):
        if task!='news':
            return parent.specified_daily_inference(losses,days,task,permit,identity)
        return news_inference(losses,days,task,permit,identity)
    result.specified_daily_inference = specified
    return result


def a2_inputs(parent_class, original_native):
    'Check input hashes and full-grid pairing before selecting issue days.'
    class Inputs(parent_class):
        def __init__(self,*args,**kwargs):

            grid = kwargs.get('grid',args[1] if len(args)>1 else None)
            if grid is not None and grid.get('news') != ('2026-03-01','2026-09-30',72):
                raise ValueError('R2 primary_tests must validate original grid first')
            super().__init__(*args,**kwargs)
            self._r2_native = native_namespace(original_native)
            self._r2_values = None
            self._r2_input_identity = None

        def full_truth(self):
            return super().truth('news')

        def truth(self,source_):
            if source_ != 'news': return super().truth(source_)
            super().truth(source_)
            for ident in self.seal['predictions']:
                if ident['source'] in ('news','lear') and ident['variant'] != '2025_fixed_validation':
                    self._checked(ident,'r2_full_original_prediction')


            identity=json.dumps(self.seal,sort_keys=True)
            if self._r2_values is None or identity!=self._r2_input_identity:
                self._r2_values = self._r2_native['_read_task_data']('news',self.seal)
                self._r2_input_identity=identity
            return self._r2_values[0].copy()

        def prediction(self,source_,arm,truth,seed=20260919,variant='main'):
            if source_ not in ('news','lear') or variant == '2025_fixed_validation':
                return super().prediction(source_,arm,truth,seed,variant)
            if self._r2_values is None: self.truth('news')
            panel = self._r2_values[0]
            if not truth[KEYS].equals(panel[KEYS]):
                raise ValueError('R2 primary_tests common view key drift')
            values = self._r2_values[3].get((arm,seed,variant))
            return None if values is None else values.copy()

        def daily_losses(self,source_):
            frame = super().daily_losses(source_)
            if source_ == 'news' and frame.target_day.tolist() != day_set():
                raise ValueError('R2 primary_tests daily census drift')
            return frame
    return Inputs


def ap_build(namespace):
    return inherit(AP_PATH, ('build',), dict(namespace),
                   [('2026-03-01',day_set()[0],1)])['build']


def panel_hash(panel):

    return inherit(NATIVE,('key_hash',),dict(KEYS=KEYS,hashlib=hashlib))['key_hash'](panel)


def score_prefix(namespace, sc, source_, receipt, output, permit, manifest, state_root):
    'Compute daily losses through the frozen scoring functions.'
    tree = ast.parse(source(NATIVE).read_bytes())
    fn = next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='score')
    loop = next(n for n in fn.body if isinstance(n,ast.For)
                and isinstance(n.target,ast.Name) and n.target.id=='source')
    stop = next(i for i,n in enumerate(loop.body) if isinstance(n,ast.Assign)
                and any(isinstance(t,ast.Name) and t.id=='price_path' for t in n.targets))
    body = deepcopy(loop.body[:stop])

    assignment = next(n for n in body if isinstance(n,ast.Assign)
                      and any(isinstance(t,ast.Name) and t.id=='panel_identity' for t in n.targets))
    if not isinstance(assignment.value,ast.Dict): raise PermissionError('Panel identity AST drift')
    positions = [i for i,k in enumerate(assignment.value.keys)
                 if isinstance(k,ast.Constant) and k.value=='common_keys_sha256']
    if len(positions)!=1: raise PermissionError('Panel identity census drift')
    if source_=='news':
        assignment.value.values[positions[0]] = ast.Call(func=ast.Name(id='_r2_panel_hash',ctx=ast.Load()),
                                                       args=[ast.Name(id='panel',ctx=ast.Load())],keywords=[])
    env = dict(namespace,source=source_,scoring=sc,seal_receipt=receipt,
               scoring_root=Path(output),scoring_permit=permit,manifest=manifest,
               summaries={},lines=[],a1_primary={},a1_tasks={},root=Path(state_root),
               _r2_panel_hash=panel_hash)
    ast.set_missing_locations(ast.Module(body=body,type_ignores=[]))
    exec(compile(ast.set_missing_locations(ast.Module(body=body,type_ignores=[])),
                 str(source(NATIVE)),'exec'),env)
    return env


def official_score(parent_namespace, permit, feature_root, state_root):

    ns=native_namespace(parent_namespace)
    if 'severe_events' in parent_namespace:
        event_env=dict(parent_namespace['severe_events'].__globals__)
        inherit(NATIVE,('severe_events',),event_env,[('2026-03-01',day_set()[0],1)])
        def events(*args,**kwargs):
            task=args[3] if len(args)>3 else kwargs['source']
            if task!='news':return parent_namespace['severe_events'](*args,**kwargs)
            return event_env['severe_events'](*args,**kwargs)
        ns['severe_events']=events
    parent_conf=parent_namespace['conf_module']
    ns['conf_module']=lambda name:scoring_successor(parent_conf(name)) if name=='scoring' else parent_conf(name)
    path=source(NATIVE)
    fn=next(n for n in ast.parse(path.read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='score')
    assignments=[n for n in ast.walk(fn) if isinstance(n,ast.Assign)
                 and any(isinstance(t,ast.Name) and t.id=='panel_identity' for t in n.targets)]
    if len(assignments)!=1:raise PermissionError('R2 official panel binding census drift')
    value=assignments[0].value
    slots=[i for i,k in enumerate(value.keys) if isinstance(k,ast.Constant) and k.value=='common_keys_sha256']
    if len(slots)!=1:raise PermissionError('R2 official panel key identity census drift')

    value.values[slots[0]]=ast.IfExp(test=ast.Compare(left=ast.Name(id='source',ctx=ast.Load()),
        ops=[ast.Eq()],comparators=[ast.Constant(value='news')]),
        body=ast.Call(func=ast.Name(id='_r2_panel_hash',ctx=ast.Load()),args=[ast.Name(id='panel',ctx=ast.Load())],keywords=[]),
        orelse=value.values[slots[0]])
    ns['_r2_panel_hash']=panel_hash
    marker=dict(schema='PCPRIMARY_R2_NEWS_EVALUATION_V1',issue_days=day_set(),
                scientific_source_sha256=digest(HERE/'news_source.py'),
                sealed_domain_days=214,primary_days=135)
    ns['_r2_evaluation_marker']=marker

    resume=next(n for n in fn.body if isinstance(n,ast.If) and isinstance(n.test,ast.Call)
                and isinstance(n.test.func,ast.Attribute) and n.test.func.attr=='exists')
    after_receipt=1
    resume.body.insert(after_receipt,ast.parse(
        "if receipt.get('evaluation_view') != _r2_evaluation_marker:\n"
        "    raise PermissionError('R2 refuses an original-window or unapproved resume')").body[0])
    receipt_calls=[n for n in ast.walk(fn) if isinstance(n,ast.Call)
                   and isinstance(n.func,ast.Name) and n.func.id=='atomic_json'
                   and any(isinstance(a,ast.Dict) and any(isinstance(k,ast.Constant) and k.value=='seal_sha256'
                           for k in a.keys) for a in n.args)]
    if len(receipt_calls)!=1:raise PermissionError('R2 official receipt census drift')
    receipt_value=next(a for a in receipt_calls[0].args if isinstance(a,ast.Dict))
    receipt_value.keys.append(ast.Constant(value='evaluation_view'))
    receipt_value.values.append(ast.Name(id='_r2_evaluation_marker',ctx=ast.Load()))

    literals=[n for n in ast.walk(fn) if isinstance(n,ast.Constant) and isinstance(n.value,str)
              and '214/61 days shorter than Lago' in n.value]
    if len(literals)!=1:raise PermissionError('R2 official scope text census drift')
    literals[0].value=literals[0].value.replace('214/61 days','135/61 days')
    exec(compile(ast.set_missing_locations(ast.Module(body=[fn],type_ignores=[])),str(path),'exec'),ns)
    return ns['score'](permit,feature_root,state_root)


def verified_prediction_view(frame, full, view):
    'Check forecast keys and values before selecting the evaluation window.'
    inherit(NATIVE,('complete_grid',),dict(KEYS=KEYS))['complete_grid'](full,'news')
    if not frame[KEYS+['target_day']].equals(full[KEYS+['target_day']]):
        raise ValueError('R2 optional original prediction common keys differ')
    for col in ('prediction','raw_prediction'):
        if col in frame and not np.isfinite(frame[col].to_numpy(dtype='float64')).all():
            raise ValueError('R2 optional original prediction nonfinite')
    selected=frame.iloc[issue_positions(full)].reset_index(drop=True)
    if not selected[KEYS+['target_day']].equals(view[KEYS+['target_day']]):
        raise ValueError('R2 optional shared evaluation view drift')
    return selected


def a3_successor(parent, primary_tests):

    env=dict(parent.matched_support_section.__globals__)
    env['primary_tests']=primary_tests
    fn=next(n for n in ast.parse(source(A3_PATH).read_bytes()).body
            if isinstance(n,ast.FunctionDef) and n.name=='matched_support_section')
    at=next(i for i,n in enumerate(fn.body) if isinstance(n,ast.If)
            and 'keys[primary_tests.KEYS].equals' in ast.unparse(n.test))
    fn.body[at:at]=ast.parse("keys = _r2_mask_view(keys, inputs, truth)").body
    def mask_view(keys, inputs, truth):
        full=inputs.full_truth()
        if not keys[KEYS+['target_day']].equals(full[KEYS+['target_day']]):
            raise ValueError('R2 sensitivity_tests original matched mask common keys differ')
        if len(keys['matched'])!=len(full):raise ValueError('R2 sensitivity_tests mask length drift')
        ix=issue_positions(full)
        return keys.iloc[ix].reset_index(drop=True)
    env['_r2_mask_view']=mask_view
    exec(compile(ast.set_missing_locations(ast.Module(body=[fn],type_ignores=[])),str(source(A3_PATH)),'exec'),env)
    old_days=parent.readmission_free_days
    def readmission(*args,**kwargs):
        original=old_days(*args,**kwargs)
        return [d for d in original if d in set(day_set())]
    old_coverage=parent.pcontent_coverage
    def coverage(feature_root, expected_manifest_sha=None):
        result=old_coverage(feature_root,expected_manifest_sha)
        if result['news'].get('state')!='COMPUTED':return result
        manifest=json.loads((Path(feature_root)/'manifest.json').read_text())
        b=parent._feature_bundle(manifest,'news')
        keys=pd.read_parquet(b['panel_path'],columns=KEYS+['target_day'])
        mask=np.load(b['matched_mask_path'],allow_pickle=False).astype(bool)
        if mask.shape!=(len(keys),):raise ValueError('R2 coverage original mask length drift')
        keys['target_day']=keys['target_day'].astype(str)
        keys['matched']=mask


        full=primary_tests.coerce_keys(keys.loc[keys.target_day.between('2026-03-01','2026-09-30')])
        full=full.sort_values(KEYS,kind='mergesort').reset_index(drop=True)

        check=inherit(NATIVE,('complete_grid',),dict(pd=pd,np=np,KEYS=KEYS))['complete_grid']
        check(full,'news')
        ix=issue_positions(full)
        selected=full.iloc[ix].matched.to_numpy(dtype=bool);days=full.iloc[ix].target_day.to_numpy()
        result['news'].update(matched_keys=int(selected.sum()),total_keys=len(ix),
            matched_share_percent=100.*selected.mean(),days_with_matched_key=len(set(days[selected])),n_days=len(day_set()))
        return result
    old_subset=parent.subset_reports
    def subset(sc, source_, frame, keep, sentence):
        result=old_subset(sc,source_,frame,keep,sentence)
        if source_=='news':result['state']='COMPUTED'
        return result
    return dict(subset_reports=subset,matched_support_section=env['matched_support_section'],
                readmission_free_days=readmission,pcontent_coverage=coverage)


def batch_prediction_losses(namespace):
    env=dict(namespace)
    fn=next(n for n in ast.parse(source(BATCH_SCORE).read_bytes()).body
            if isinstance(n,ast.FunctionDef) and n.name=='prediction_losses')
    loop=next(n for n in fn.body if isinstance(n,ast.For))
    at=next(i for i,n in enumerate(loop.body) if isinstance(n,ast.Assign)
            and any(isinstance(t,ast.Name) and t.id=='f' for t in n.targets))
    loop.body[at+1:at+1]=ast.parse("if not validation:\n    f = _r2_prediction(f, seal, truth)").body
    def view(frame,seal,truth):
        original=pd.read_parquet(env['checked'](seal['truth_panels']['news']),
                                 columns=KEYS+['target_day','y','weight'])
        full=env['sealing'].normalize(original.loc[
            original.target_day.astype(str).between('2026-03-01','2026-09-30')])
        if not np.isfinite(full.y.to_numpy()).all() or not full.weight.eq(1).all():
            raise ValueError('R2 optional full truth integrity')

        return verified_prediction_view(frame,full,truth)
    env['_r2_prediction']=view
    exec(compile(ast.set_missing_locations(ast.Module(body=[fn],type_ignores=[])),str(source(BATCH_SCORE)),'exec'),env)
    return env['prediction_losses']


def label_tree():
    tree=ast.parse(source(LABEL_SCORE).read_bytes())
    run=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='run')
    loop=next(n for n in run.body if isinstance(n,ast.For) and getattr(n.target,'id',None)=='source')
    inner=next(n for n in loop.body if isinstance(n,ast.For))
    at=next(i for i,n in enumerate(inner.body) if isinstance(n,ast.Assign)
            and any(getattr(t,'id',None)=='prediction' for t in n.targets))
    inner.body[at+1:at+1]=ast.parse("if source == 'news':\n    prediction = _r2_prediction(prediction, inputs.full_truth(), truth)").body
    return ast.set_missing_locations(tree)


def optional_successor(parent):

    env=dict(parent.batch.__globals__)
    original_ast=env['ast_functions']
    def leaves(path,names,namespace):
        original_ast(path,names,namespace)
        if Path(path).resolve()==source(BATCH_SCORE).resolve():
            namespace['prediction_losses']=batch_prediction_losses(namespace)
        return namespace
    env['ast_functions']=leaves


    class AstProxy:
        def __getattr__(self,name):return getattr(ast,name)
        def parse(self,text):
            if text!=source(LABEL_SCORE).read_text():raise PermissionError('R2 label source drift')
            return label_tree()
    env['ast']=AstProxy()
    nodes=[n for n in ast.parse(source(OPTIONAL).read_bytes()).body if isinstance(n,ast.FunctionDef)]
    for node in nodes:
        if node.name=='label':
            at=next(i for i,n in enumerate(node.body) if isinstance(n,ast.For) and ast.unparse(n.iter)=='P.PAIRS')
            node.body[at:at]=ast.parse("ns['_r2_prediction'] = _r2_prediction").body
    env['_r2_prediction']=verified_prediction_view
    exec(compile(ast.set_missing_locations(ast.Module(body=nodes,type_ignores=[])),str(source(OPTIONAL)),'exec'),env)
    def guarded(name):
        def run(*args):
            records=args[-2]
            key='a2batch_receipt' if name=='batch' else 'label_receipt'
            if key in records and records[key].get('evaluation_view')!=evaluation_marker():
                raise PermissionError('R2 optional receipt evaluation identity missing/changed')
            return env[name](*args)
        return run
    return dict(batch=guarded('batch'),label=guarded('label'))


def evaluation_marker():
    return dict(schema='PCPRIMARY_R2_NEWS_EVALUATION_V1',issue_days=day_set(),
        scientific_source_sha256=digest(HERE/'news_source.py'),sealed_domain_days=214,primary_days=135)


def score_optional_inputs(primary_tests, sc, permit, loader, batch_seal_identity,
                          replacement_identity, output):

    sc.require_execution(permit,scoring=True)
    output=Path(output)
    if output.exists():raise PermissionError('R2 optional output must be fresh')
    if not isinstance(loader,primary_tests.Inputs):raise PermissionError('R2 optional loader identity')
    full=loader.full_truth();truth=loader.truth('news')
    if truth.target_day.unique().tolist()!=day_set():raise ValueError('R2 optional truth view')
    def checked(item):
        path=Path(item['path'])
        if path.is_symlink() or digest(path)!=item['sha256']:raise PermissionError('R2 optional input identity drift')
        return path
    def require(ok,message):
        if not ok:raise ValueError(message)
    def identity(path):return dict(path=str(Path(path).resolve()),sha256=digest(path))
    def write(name,value):
        path=output/name;path.write_text(json.dumps(primary_tests.json_safe(value),indent=2,allow_nan=False)+'\n')
        return identity(path)
    seal=json.loads(checked(batch_seal_identity).read_text())
    require(seal['truth_panels']['news']['sha256']==loader.seal['truth_panels']['news']['sha256'],'R2 optional truth identity')
    env=dict(np=np,pd=pd,KEYS=KEYS,SEED=20260919,checked=checked,require=require)
    inherit('studies/batch_scoring/code/sealing.py',('normalize',),env)
    env['sealing']=SimpleNamespace(normalize=env['normalize'])
    losses=batch_prediction_losses(env)(seal,truth,day_set(),primary_tests)
    refs=dict(loader.seal,predictions=[i for i in loader.seal['predictions'] if i['arm'] in ('N','M','L_count','L_chen','LEAR')])
    losses.update(batch_prediction_losses(env)(refs,truth,day_set(),primary_tests))
    path=source(BATCH_SCORE)
    for n in ast.parse(path.read_bytes()).body:
        if isinstance(n,ast.Assign) and any(getattr(t,'id',None) in ('FAMILIES','DESCRIPTIVE','SENTENCES','VERBS') for t in n.targets):
            exec(compile(ast.Module(body=[n],type_ignores=[]),str(path),'exec'),env)
    inherit(BATCH_SCORE,('inference',),env)
    dispositions={r['stage']:r for r in seal['stage_dispositions']}
    families,descriptive=env['inference'](losses,day_set(),primary_tests,sc,dispositions)
    for family in families.values():
        if family['state']=='COMPUTED_SECONDARY':family['state']='COMPUTED'
    replacement=json.loads(checked(replacement_identity).read_text())
    require(replacement['state']=='ALL_REPLACEMENT_PREDICTIONS_COMPLETE','R2 replacement seal')
    require(replacement['seal_sha256']==loader.seal_sha256,'R2 replacement main seal binding')
    require(json.loads(checked(replacement['parity']).read_text())['state']=='BOTH_PARITY_GATES_PASS','R2 replacement parity')
    for ident in replacement['files']:checked(ident)
    fn=next(n for n in label_tree().body if isinstance(n,ast.FunctionDef) and n.name=='run')
    loop=next(n for n in fn.body if isinstance(n,ast.For) and getattr(n.target,'id',None)=='source')
    end=next(i for i,n in enumerate(loop.body) if isinstance(n,ast.Assign) and any(getattr(t,'id',None)=='family' for t in n.targets))
    pairs=primary_tests.FAMILIES
    env=dict(a2=primary_tests,inputs=loader,receipt=replacement,np=np,pd=pd,checked=checked,KEYS=KEYS,
        ARMS={t:list(dict.fromkeys(a for pair in ps for a in pair)) for t,ps in pairs.items()},_r2_prediction=verified_prediction_view)
    label_families={}
    for task in pairs:
        env['source']=task
        exec(compile(ast.Module(body=loop.body[:end],type_ignores=[]),str(source(LABEL_SCORE)),'exec'),env)
        label_families[task]=primary_tests.family_inference(sc,env['losses'],pairs[task],env['days'])

    output.mkdir(parents=True)
    batch=dict(seal=batch_seal_identity,conf_seal_sha256=loader.seal_sha256,
               families=families,descriptive=descriptive,evaluation_view=evaluation_marker())
    batch_id=write('R2_BATCH.json',batch)
    daily=output/'DAILY_LOSSES.csv';pd.DataFrame(dict(target_day=day_set(),**losses)).to_csv(daily,index=False)
    batch_receipt=dict(state='A2BATCH_SECONDARY_SCORE_COMPLETE',seal_sha256=batch_seal_identity['sha256'],
        conf_seal_sha256=loader.seal_sha256,files=[batch_id,identity(daily)],evaluation_view=evaluation_marker())
    label=dict(state='A2LABEL_SCORED',families=label_families,evaluation_view=evaluation_marker())
    label_id=write('R2_LABEL.json',label)
    label_receipt=dict(state='A2LABEL_COMPLETE',production_seal_sha256=loader.seal_sha256,
        replacement_predictions=replacement_identity,files=[label_id],evaluation_view=evaluation_marker())
    write('R2_BATCH_RECEIPT.json',batch_receipt);write('R2_LABEL_RECEIPT.json',label_receipt)
    return dict(a2batch=batch,a2batch_receipt=batch_receipt,label=label,label_receipt=label_receipt)
