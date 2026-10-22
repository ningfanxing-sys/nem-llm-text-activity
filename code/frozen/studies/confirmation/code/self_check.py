"""No study values: static checks, key/calendar checks and opaque integrity.
No feature generation, model fit, prediction or study scoring is invoked.
"""
from pathlib import Path
from datetime import datetime,date,timedelta,timezone
import json,sys,ast,importlib.util,argparse
CONF=Path(__file__).resolve().parent.parent
sys.path[:0]=[str(CONF),str(CONF/'code')]
from audit_io import read_text,sha256,record

REQUIRED=('PROTOCOL_CONF.md','PROTOCOL_CONF_zh.md','FEATURE_SPEC_CONF.md','DATA_BUILD_PLAN.md',
 'LEAR_SPEC.md','INFERENCE_RULES.md','COMPUTE_PLAN.md','NEWS_EXTRACTION_PLAN.md','DESIGN_CONFIG.json',
 'ENCODER_LOCK.json','NEWS_EXTENSION_MANIFEST.json','INPUT_MANIFEST.json','BLINDING_ACCESS_NOTE.md',
 'REPORT_zh.md','OPENED_PATHS.jsonl','code/panel_build.py','code/features.py','code/encoders.py',
 'code/lear.py','code/scheduler.py','code/scoring.py','code/guard.py','code/prepare_news_manifest.py')

def imported(name):
 p=CONF/'code'/f'{name}.py';record(p,'code_import','import-safe metadata/key self-check')
 spec=importlib.util.spec_from_file_location('conf_'+name,p);mod=importlib.util.module_from_spec(spec)
 sys.modules[spec.name]=mod;spec.loader.exec_module(mod);return mod

def run(verify=False):
 checks=[]
 def test(name,condition,detail=None):checks.append({'check':name,'pass':bool(condition),'detail':detail})
 for rel in REQUIRED:test('exists:'+rel,(CONF/rel).is_file())
 config=json.loads(read_text(CONF/'DESIGN_CONFIG.json'))
 test('author_fixed_news_dates',config['news']['issue_days']==['2026-03-01','2026-09-30'])
 test('author_fixed_notice_dates',config['notice']['target_days']==['2026-08-01','2026-09-30'])
 test('no_equivalence_margin',config['inference']['equivalence_margin'] is None)
 test('no_execution_authorization',config['design_execution_authorized'] is False)
 test('news_family_two',len(config['inference']['news_primary_family'])==2)
 test('notice_family_three',len(config['inference']['notice_primary_family'])==3)
 test('news_preprocessing_fixed',config['news']['preprocessing_train']==['2021-10-01','2024-12-31'])
 test('only_24h_sensitivity',config['news']['window_sensitivity_hours']==24)
 test('notice_fixed_fit',config['notice']['refits']==1 and config['notice']['window_weights']==1)
 test('notice_original_threads',config['notice']['learner_threads']==6)
 test('fixed_four_news_workers',config['news_workers']==4)
 test('fixed_seed_choices',config['seed_primary']==20260919 and config['seeds_extra']==[20260920,20260921])
 test('fixed_placebo_shift',config['placebo_shift_days']==28)
 for p in sorted((CONF/'code').glob('*.py')):
  source=read_text(p,'static AST check; no scientific execution');tree=ast.parse(source)
  test('AST:'+p.name,True)
  if p.name in ['panel_build.py','features.py','encoders.py','lear.py','scheduler.py','scoring.py']:
   # Actual callbacks/models/data readers must be inside functions, not imports.
   top_calls=[]
   for node in tree.body:
    if isinstance(node,(ast.Assign,ast.AnnAssign,ast.Expr)):
     for z in ast.walk(node):
      if isinstance(z,ast.Call):
       n=ast.unparse(z.func)
       if any(s in n for s in ['read_parquet','read_csv','np.load','LGBM','SentenceTransformer','AutoModel','Lasso(','fit(','predict(']):top_calls.append(n)
   test('import_no_study_io_or_fit:'+p.name,not top_calls,top_calls)
 panel=imported('panel_build');sched=imported('scheduler');lear=imported('lear')
 news=list(panel.news_keys());notice=list(panel.notice_keys())
 test('news_15408_metadata_keys',len(news)==15408)
 test('notice_527040_metadata_keys',len(notice)==527040)
 test('news_exact_regions',set(k.region for k in news)=={'NSW1','QLD1','TAS1'})
 test('notice_five_regions',len(set(k.region for k in notice))==5)
 test('notice_horizons',sorted(set(k.horizon for k in notice))==[5,10,15,20,25,30])
 test('LEAR_four_exact_windows',lear.WINDOW_DAYS==(56,84,1092,1456))
 test('LEAR_registered_199_inputs',lear.TOTAL_FEATURES==199)
 counts=sched.plan_counts()
 test('news_max_count',counts['news_lightgbm_fits']==4289,counts)
 test('notice_max_count',counts['notice_lightgbm_fits']==22)
 test('LEAR_count',counts['lear_component_pairs']==61632)
 from guard import require_execution
 for scoring in [False,True]:
  try:require_execution(None,scoring=scoring);blocked=False
  except PermissionError:blocked=True
  test('reject_missing_permit:'+str(scoring),blocked)
 lock=json.loads(read_text(CONF/'ENCODER_LOCK.json'))
 test('encoder_model',lock['model_id']=='sentence-transformers/all-MiniLM-L6-v2')
 test('encoder_revision',lock['revision']=='1110a243fdf4706b3f48f1d95db1a4f5529b4d41')
 test('encoder_actual_content_limit',lock['content_token_budget']==254)
 inputs=json.loads(read_text(CONF/'INPUT_MANIFEST.json','content-free input identities'))
 test('pending_inputs_explicit',len(inputs['pending_dependencies'])>=5)
 test('manifest_no_values',inputs['values_in_manifest'] is False and inputs['source_panels_decoded'] is False)
 bad=[]
 for row in inputs['inputs']:
  if sha256(row['path'])!=row['sha256']:bad.append(row['path'])
 test('current_input_hashes_match',not bad,bad)
 # Each required first-read was logged. JSON schemas are labels contracts, not
 # extracted window outcomes; only hash_only opens of binary panels are allowed.
 logs=[json.loads(s) for s in read_text(CONF/'OPENED_PATHS.jsonl').splitlines() if s]
 prohibited=[r for r in logs if (('semantic_validation' in r['path'] and '/private/' in r['path']) or any(s in r['path'] for s in ['auth.json','/.env']))]
 test('no_protected_path_open',not prohibited)
 numeric_decodes=[r for r in logs if Path(r['path']).suffix in {'.parquet','.npy','.zip','.xlsx'} and
                  r.get('mode') not in {'hash_only','parquet_metadata','metadata_only','parquet_schema','key_columns_only'} and
                  '/evidence/' not in r['path']]
 test('no_logged_value_container_decode',not numeric_decodes,numeric_decodes)
 test('access_incident_disclosed','ARTICLE_METADATA.json' in read_text(CONF/'BLINDING_ACCESS_NOTE.md'))
 if verify:
  freeze=json.loads(read_text(CONF/'FREEZE.json','design freeze verification'))
  mismatches=[rel for rel,entry in freeze['frozen_files'].items() if sha256(CONF/rel)!=entry['sha256']]
  test('design_frozen_bytes_match',not mismatches,mismatches)
  test('freeze_execution_disabled',freeze['scientific_execution_authorized'] is False)
  test('selfcheck_precedes_freeze',freeze['self_check_passed_before_freeze'] is True)
 result={'state':'PASS' if all(r['pass'] for r in checks) else 'FAIL','checks':checks,
         'study_fits':0,'study_scores':0,'confirmation_feature_builds':0,
         'synthetic_check_scope':'static code, clocks, keys, counts, guard rejection and opaque hashes only'}
 if not verify:(CONF/'SELF_CHECK.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
 else:(CONF/'CLOSURE_VERIFICATION.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
 print(json.dumps({'state':result['state'],'checks':len(checks),'failed':[r for r in checks if not r['pass']]},ensure_ascii=False))
 return result['state']=='PASS'
if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('--verify-freeze',action='store_true');args=parser.parse_args()
 sys.exit(0 if run(args.verify_freeze) else 1)
