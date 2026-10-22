'Construct synthetic scoring inputs and their metadata.'
import contextlib
import copy
import datetime as dt
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import time
import types
from contract_io import _phase,_identity,_write_exclusive,ContractError
import fixture_api as C
from inherited_cases import InheritedSuite,dump,encoded,baseline
HERE=Path(__file__).absolute().parent

class ScientificSuite(InheritedSuite):
    def __init__(self,owned,monitor):
        if __import__('os').environ.get('SCORING_PHASE')!='accept':raise PermissionError('No suites in prepare')
        self.scratch=Path(owned)/'fixtures';self.scratch.mkdir()
        self.project=self.scratch/'project';self.project.mkdir()
        dump(self.project/'SYNTHETIC_ONLY.json',{'synthetic_only':True})
        _phase(self.project,True)
        self.a=C.Association(self.project,synthetic=True)
        self.start=time.monotonic();self.cases=[];self.samples=[];self.mocks=[];self.parity={};self.export_evidence={};self.cps_projection_evidence={};self.snapshots={}
        self.b,self.d,self.out=self.a.b,self.a.d,self.a.out
        self.seal=None;self.monitor=monitor
        self.initial_artifacts={name:C.sha(HERE/name) for name in json.loads((HERE/'PUBLIC_RUNTIME_SOURCE_MANIFEST.json').read_bytes())['files'] if name.endswith('.py')}
        self.initial_spec=C.identity(HERE/'SCIENTIFIC_ACCEPTANCE_SPEC.json')
        self.fixture_snapshots={};self.control_fixture=None

    def restore(self):
        if not self.fixture_snapshots:return super().restore()
        _phase(self.project,True)


        for root in (self.out,self.d,self.a.f1,self.a.f2,self.project/'fixtures',self.a.q/'ARTIFICIAL_RUNTIME'):
            shutil.rmtree(root,ignore_errors=True)
        for path,blob in self.fixture_snapshots.items():
            path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(blob)
        self.a.sealed.clear()

    def sample(self):return self.monitor.sample()

    def _families(self,a):
        families={};paths=[]
        for family in ('AP5','AP6','notice_delays','scoring_callback'):
            root=a.q/'ARTIFICIAL_RUNTIME'/family;root.mkdir(parents=True,exist_ok=True)
            body='__synthetic_fixture__=True\nSENTINEL="ARTIFICIAL_'+family+'"\ndef science_entry(**kwargs):return SENTINEL\n'
            if family=='AP5':body+='from synthetic_scorecb import SENTINEL as CHILD\n'
            if family=='AP6':body+='from synthetic_rd import SENTINEL as CHILD\n'
            filename={'notice_delays':'synthetic_rd.py','scoring_callback':'synthetic_scorecb.py'}.get(family,'entry.py')
            code=root/filename;code.write_text(body)
            fp=root/'ARTIFICIAL_CODE_AUTHORITY.json'
            names=[filename]
            document=dict(schema='ARTIFICIAL_'+family+'_AUTHORITY_V1',state='ARTIFICIAL_REVIEWED_FROZEN_PREMISE',frozen_utc='2026-10-08T01:00:00Z',declared_census=names,files=[C.identity(code)],synthetic_only=True)
            dump(fp,document);paths.extend([code,fp])
            families[family]=dict(root=str(root.relative_to(a.q)),freeze=str(fp.relative_to(a.q)),schema=document['schema'],state=document['state'],inventory_field='files',inventory_format='absolute_bytes_sha_list',inventory_base=str(root.relative_to(a.q)),declared_census_field='declared_census',names=names)
        return dict(schema='C_SCORING_RUNTIME_FAMILIES_V1',status='REVIEWED_EXACT_OWNER_CONTRACTS',families=families),paths

    def _science_fixture(self):
        a=self.a;self.out.mkdir(parents=True,exist_ok=True)
        manifest=json.loads((HERE/'PUBLIC_RUNTIME_SOURCE_MANIFEST.json').read_bytes())
        census=json.loads((HERE/'FREEZE_CENSUS.json').read_bytes())['files']
        for name in sorted(set(census)|set(manifest['files'])):
            src=HERE/name;dst=self.out/name;dst.parent.mkdir(parents=True,exist_ok=True)
            if src.is_file():shutil.copyfile(src,dst)


        ancestor=copy.deepcopy(C.read(HERE/'NUMERIC_ANCESTOR_PROPOSAL.json'));ancestor['source_adopted']=True
        dump(self.out/'NUMERIC_ANCESTOR_CONTRACT.json',ancestor)
        policy,runtime_paths=self._families(a);dump(self.out/'RUNTIME_FAMILY_POLICY.json',policy)
        entries={}
        for role,family in [('arm','scoring_callback'),('capture','scoring_callback'),('r2_complete','scoring_callback'),('ap5_science','AP5'),('ap6_joint','AP6'),('rd_joint','notice_delays'),('optional_loader','AP5'),('numeric_assembly','AP5'),('author_validation','AP5')]:
            entries[role]=dict(family=family,status='OWNER_DELIVERED_REVIEWED',source=policy['families'][family]['names'][0],callable='science_entry')
        dump(self.out/'ENTRY_CONTRACTS.json',dict(schema='C_SCORING_RUNTIME_ENTRIES_V1',status='REVIEWED_EXACT_OWNER_ENTRIES',entries=entries))
        scorer=copy.deepcopy(C.read(HERE/'SCORER_CONTRACT.pending.json'));scorer['status']='REVIEWED_EXACT_R2_SOURCE_DELIVERY'
        original=copy.deepcopy(self.official_items)

        source=C.LIVE/scorer['r2']['source']['path'];a.verify_code(source)
        assert C.sha(source)==scorer['r2']['source']['sha256']
        artificial_source=self.project/scorer['r2']['source']['path']
        artificial_source.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,artificial_source)
        marker=scorer['r2']['evaluation_view']
        r2state=self.project/'fixtures/r2_fresh_state';r2out=r2state/'scored'
        dump(r2out/'SCORE_REPORT.json',dict(synthetic_only=True,evaluation_view=marker))
        dump(r2out/'SCORE_RECEIPT.json',dict(state='FROZEN_SCORE_COMPLETE',seal_sha256=original['seal']['sha256'],evaluation_view=marker,files=[C.identity(r2out/'SCORE_REPORT.json')]))
        r2=dict(seal=original['seal'],score_receipt=C.identity(r2out/'SCORE_RECEIPT.json'),score_report=C.identity(r2out/'SCORE_REPORT.json'))
        for view,items,state in [('original',original,Path(original['seal']['path']).parent),('r2',r2,r2state)]:
            wire=scorer[view];wire.update(seal_path=items['seal']['path'],state_root=str(state),receipt_path=items['score_receipt']['path'],report_path=items['score_report']['path'],receipt_identity=items['score_receipt'],report_identity=items['score_report'],seal_identity=items['seal'],output_census=[items['score_report']['path']])
        permit=self.project/'fixtures/ACTUAL_ARTIFICIAL_PERMIT.json';dump(permit,dict(synthetic_only=True,not_real_permission=True));permit_id=C.identity(permit)
        scorer['r2']['permit_identity']=permit_id
        scorer['r2']['state_seal_association']=dict(schema='C_SCORING_R2_STATE_SEAL_ASSOCIATION_V1',source_reviewed=True,resolution='EXACT_IN_PROCESS_ORIGINAL_SEAL_ONLY',state_root=str(r2state),seal_identity=original['seal'])
        cbroot=a.q/policy['families']['scoring_callback']['root'];cbfreeze=cbroot/'ARTIFICIAL_CODE_AUTHORITY.json';cbcode=cbroot/'synthetic_scorecb.py'
        plan=self.project/'fixtures/CALLBACK_PLAN.json';dump(plan,dict(synthetic_only=True,not_real_plan=True));plan_id=C.identity(plan)
        cb=C.read(cbfreeze);cb['plan']=plan_id;dump(cbfreeze,cb);callback=C.identity(cbfreeze)
        scorer['execution_producer_path']=str(cbcode)
        scorer['capture_contract']=dict(schema='ARTIFICIAL_NATIVE_CAPTURE_V1',state='ARTIFICIAL_CAPTURE_COMPLETE',producer_outputs={},initial_input_paths=[])
        control=self.project/'fixtures/callback_control';control.mkdir(parents=True,exist_ok=True)
        self.control_fixture=dict(root=control,plan=plan_id,callback=callback,producer=C.identity(cbcode),permit=permit_id)
        scorer['execution_evidence_path']=str(control/'EXECUTION.json')
        dump(self.out/'SCORER_CONTRACT.json',scorer)
        bindings=dict(schema='C_SCORING_SCORER_BINDINGS_V1',source_reviewed=True,scientific_eligibility_changed=False,scientific_authority_contract=dict(path=str(self.out/'SCIENCE_FREEZE.json'),schema='C_SCORING_SCIENTIFIC_FREEZE_V1',state='SCIENTIFIC_CONSUMER_FROZEN_BEFORE_T5'))
        dump(self.out/'SCORER_BINDINGS.json',bindings)


        host=self.host_parent_fixture(a)
        roots=dict(batch=str(a.b),state=str(a.d/'state'),dly8=str(a.d/'dly8'),cps8=str(a.d/'cps8'))
        dump(a.d/'T4C_ROOTS.json',roots)
        disk=dict(state='FROZEN_RESOURCE_ONLY_DISK_SPECIFICATION',utc='2026-10-08T00:00:00Z',roots=roots,files={},parents={})
        dump(a.d/'DISK_FREEZE.json',disk)
        tsa=[]
        for n in (1,2):
            p=a.q/'confirmation/TIMESTAMPS'/('ARTIFICIAL_TSA_'+str(n)+'.json');dump(p,dict(synthetic_only=True,not_a_real_timestamp=True));tsa.append(C.identity(p))
        dump(a.d/'T4C_BINDING.json',dict(label='T4C',state='T4C_VERIFIED',source_verified=True,roots=roots,utc='2026-10-08T00:01:00Z',supplement_freeze=C.identity(a.d/'DISK_FREEZE.json'),files=[C.identity(p) for p in (a.d/'DISK_FREEZE.json',a.d/'T4C_ROOTS.json',a.b/'CODE_FREEZE.json')],tsa_receipts=tsa))

        f1=C.read(a.f1/'SET1_FREEZE.json');f1['parents']={str(p):{k:v for k,v in C.identity(p).items() if k!='path'} for p in (a.d/'DISK_FREEZE.json',a.d/'T4C_BINDING.json')};dump(a.f1/'SET1_FREEZE.json',f1)
        stamp=C.read(a.f1/'T4D_BINDING.json');stamp['set1_freeze']=C.identity(a.f1/'SET1_FREEZE.json');stamp['files']=[stamp['set1_freeze']];dump(a.f1/'T4D_BINDING.json',stamp)
        f2=C.read(a.f2/'SET2_FREEZE.json');parents={str(p):{k:v for k,v in C.identity(p).items() if k!='path'} for p in (a.f1/'SET1_FREEZE.json',a.f1/'T4D_BINDING.json')};dump(a.f2/'PARENT_PINS.json',parents);f2['parents']=parents;f2['files']['PARENT_PINS.json']={k:v for k,v in C.identity(a.f2/'PARENT_PINS.json').items() if k!='path'};dump(a.f2/'SET2_FREEZE.json',f2)
        stamp=C.read(a.f2/'T4E_BINDING.json');stamp['set2_freeze']=C.identity(a.f2/'SET2_FREEZE.json');stamp['files']=[stamp['set2_freeze']];dump(a.f2/'T4E_BINDING.json',stamp)
        host={k:C.identity(Path(v['path'])) for k,v in host.items()}
        release=dict(schema='C_SCORING_SCIENTIFIC_RELEASE_V1',source_reviewed=True,scientific_eligibility_changed=False,integration_complete=True,disk_freeze=C.identity(a.d/'DISK_FREEZE.json'),t4c_binding=C.identity(a.d/'T4C_BINDING.json'),numeric_ancestor_contract=C.identity(self.out/'NUMERIC_ANCESTOR_CONTRACT.json'),runtime_family_policy=C.identity(self.out/'RUNTIME_FAMILY_POLICY.json'),scorer_contract=C.identity(self.out/'SCORER_CONTRACT.json'),entry_contracts=C.identity(self.out/'ENTRY_CONTRACTS.json'),t5_metadata=[],**host)
        dump(self.out/'SCIENTIFIC_ASSOCIATION.json',release)
        b0=a.d/'state/B0_REPRODUCTION.json';dump(b0,dict(state='ARTIFICIAL_B0_PARITY_PREMISE',synthetic_only=True))
        dump(self.out/'OUTPUT_EVIDENCE_BINDINGS.json',dict(schema='A8DISK_OUTPUT_EVIDENCE_IDENTITIES_V1',source_reviewed=True,batch_seal=C.identity(a.d/'state/SEAL_BATCH.json'),scientific_eligibility_changed=False,files=[dict(role='OPERATIONAL_EVIDENCE',identity=C.identity(b0))]))


        old_active=C.ACTIVE;old_path=sys.path[:]
        clone={p:p.read_bytes() for r in ('state','dly8','cps8') for p in (self.b/r).rglob('*') if p.is_file()}
        self.remove_b_outputs()
        a.sources();sys.path.insert(0,str(C.LIVE/C.B_REL/'code'))
        a._bootstrap_source_ready=True;a._bootstrap_depth=1;C.ACTIVE=a
        try:
            with a._validation():
                a._load_verified('batch_inputs')
                a._evidence_proposal_chain();a.census()
                closure_files=[C.identity(p) for p in sorted(a.prescore_paths())]
        finally:
            C.ACTIVE=old_active;a._bootstrap_source_ready=False;a._bootstrap_depth=0;sys.path[:]=old_path
            for p,b in clone.items():p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b)
        source=dict(schema='A8DISK_T5_COMMITMENT_SOURCE_V1',association_source=C.identity(HERE/'consumer_roots.py'),batch_seal=C.identity(a.d/'state/SEAL_BATCH.json'),files=closure_files)
        dump(self.out/'T5_COMMITMENT_SOURCE_RECEIPT.json',source)
        dump(self.out/'T5_IDENTITY_COMMITMENTS.json',dict(schema='A8DISK_T5_IDENTITY_COMMITMENTS_V1',source_reviewed=True,scientific_eligibility_changed=False,batch_seal=source['batch_seal'],files=closure_files,closure_receipt=C.identity(self.out/'T5_COMMITMENT_SOURCE_RECEIPT.json')))
        test_sources={name:{k:v for k,v in C.identity(self.out/name).items() if k!='path'} for name in C.read(self.out/'SCIENTIFIC_ACCEPTANCE_SPEC.json')['tested_source_files']}
        premise=dict(schema='C_SCORING_ARTIFICIAL_RELEASE_PREMISE_V1',state='ARTIFICIAL_PRIOR_REVIEW_PREMISE_NOT_ACCEPTANCE',synthetic_only=True,premise_only=True,case_ids=C.read(self.out/'SCIENTIFIC_ACCEPTANCE_SPEC.json')['case_ids'],delivered_sources=test_sources,task_revision='SCORING_C8B_SCIENCE_V1',failures=[],errors=[],skipped=[])
        dump(self.out/'SCIENTIFIC_ACCEPTANCE_RECEIPT.json',premise)
        dump(self.out/'INDEPENDENT_REVIEW.json',dict(schema='C_SCORING_INDEPENDENT_REVIEW_V1',verdict='ACCEPT',independent=True,reviewer_role='C_REVIEWER',task_revision='SCORING_C8B_SCIENCE_V1',reviewed_sources=test_sources,synthetic_only=True,premise_only=True))
        for name in census:
            p=self.out/name
            if not p.exists():dump(p,dict(synthetic_only=True,not_real_identity=True,fixture_name=name))
        f=dict(schema='C_SCORING_SCIENTIFIC_FREEZE_V1',state='SCIENTIFIC_CONSUMER_FROZEN_BEFORE_T5',task_revision='SCORING_C8B_SCIENCE_V1',frozen_utc='2026-10-08T01:00:00Z',files={name:{k:v for k,v in C.identity(self.out/name).items() if k!='path'} for name in census},tested_sources=test_sources,callable_ast_inventory=C.identity(self.out/'SOURCE_AST_HELPER_INVENTORY.json'),scientific_decisions=C.read(HERE/'SCIENCE_RULES.json')['authority_identities'],numeric_ancestor_contract=release['numeric_ancestor_contract'],acceptance=C.identity(self.out/'SCIENTIFIC_ACCEPTANCE_RECEIPT.json'),independent_review=C.identity(self.out/'INDEPENDENT_REVIEW.json'),release_binding=C.identity(self.out/'SCIENTIFIC_ASSOCIATION.json'),synthetic_only=True)
        dump(self.out/'SCIENCE_FREEZE.json',f)

        with baseline(a) as load:hashes=load('batch_inputs').code_hashes('scorer')
        scorer_meta=dict(schema='C_SCORING_SCORER_METADATA_V1',frozen_utc='2026-10-08T01:30:00Z',state='A8_SCORER_CODE_FROZEN_BEFORE_T5',code_sha256=hashes,batch_code_freeze=C.identity(a.b/'CODE_FREEZE.json'),numerical_inputs=C.identity(self.out/'SCIENCE_FREEZE.json'),scorer_bindings=C.identity(self.out/'SCORER_BINDINGS.json'),files=[C.identity(self.out/'SCORER_BINDINGS.json')],synthetic_only=True)
        dump(self.out/'SCORER_CODE_FREEZE.json',scorer_meta)
        self.views=dict(original=original,r2=r2,execution=None)
        self._temporary_t5(a,runtime_paths,tsa)
        self._capture(a,scorer,plan_id,callback,permit_id)
        self.fixture_snapshots={p:p.read_bytes() for root in (self.out,a.d,a.f1,a.f2,self.project/'fixtures',a.q/'ARTIFICIAL_RUNTIME') for p in root.rglob('*') if p.is_file()}
        self.fixture_snapshots[artificial_source]=artificial_source.read_bytes()

    def _temporary_t5(self,a,runtime_paths=(),tsa=()):
        paths={p for p in self.out.rglob('*') if p.is_file() and a.metadata_root(p)}|set(runtime_paths)|{p for p in (a.d,a.f1,a.f2) if False}
        for root in (a.d,a.f1,a.f2):paths|={p for p in root.rglob('*') if p.is_file() and a.metadata_root(p)}


        paths.update(a.host_metadata())
        commitment=C.read(self.out/'T5_COMMITMENT_SOURCE_RECEIPT.json')
        paths.update(Path(i['path']) for i in commitment['files'] if a.metadata_root(i['path']))
        sf=C.read(self.out/'SCORER_CODE_FREEZE.json')
        paths.update(Path(i['path']) for i in [sf['batch_code_freeze'],sf['numerical_inputs'],sf['scorer_bindings'],*sf['files']])
        projection=self.out/'CPS8_METADATA.receipt.json'
        if projection.exists():
            proof=C.read(projection);paths.update(Path(proof[k]['path']) for k in ('source','adapter'))
        paths.add(self.control_fixture['plan']['path'])

        for family in C.read(self.out/'RUNTIME_FAMILY_POLICY.json')['families'].values():paths|={a.q/family['root']/n for n in family['names']}|{a.q/family['freeze']}
        paths={Path(p) for p in paths};paths.discard(a.out/'T5_BINDING.json')
        t=dict(state='T5_VERIFIED',source_verified=True,utc='2026-10-08T02:00:00Z',files=[C.identity(p) for p in sorted(paths)],tsa_receipts=list(tsa),synthetic_only=True,not_a_real_timestamp=True)
        dump(a.out/'T5_BINDING.json',t);a.synthetic_t5_receipts=list(tsa)
        return t

    def _capture(self,a,scorer,plan,callback,permit):
        root=self.control_fixture['root'];t5=C.identity(a.out/'T5_BINDING.json')
        armed=root/'ARMED.json';dump(armed,dict(state='ARMED_AFTER_T5_BEFORE_SCORE',callback_freeze=callback,score_argv=scorer['original']['argv'],score_receipt_absent=True,no_postscore_launches_confirmed=True,t5_binding=t5,plan=plan,synthetic_only=True))
        clock=root/'CLOCK.json';dump(clock,dict(schema='SCORECB_POSTSCORE_CLOCK_ASSOCIATION_V1',state='POSTSCORE_CLOCK_ASSOCIATION_VERIFIED',producer_outputs={},initial_inputs=[],conf_score_receipt=self.views['original']['score_receipt'],source_verified=True,retrospective_reconstruction_authorised=False,completion_evidence=dict(kind='SOURCE_OBSERVED_SPECIFIED_COMMAND_EXIT',argv=scorer['original']['argv'],exit_status=0,no_postscore_launches_confirmed=True,receipt_contents_decoded=False),armed=C.identity(armed),t5_binding=t5,plan=plan,score_complete_utc='2026-10-08T03:00:00Z',callback_ready_utc='2026-10-08T03:00:01Z',synthetic_only=True))
        capture=root/'CAPTURE.json';dump(capture,dict(schema='ARTIFICIAL_NATIVE_CAPTURE_V1',state='ARTIFICIAL_CAPTURE_COMPLETE',clock_association=C.identity(clock),source_values_decoded=False,pending_is_negative=False,cutoff_utc='2026-10-08T03:00:00Z',observed_utc='2026-10-08T03:00:02Z',producer_states={},files=[],synthetic_only=True))
        execution=root/'EXECUTION.json';dump(execution,dict(schema='C_SCORING_SCORE_EXECUTION_EVIDENCE_V1',original_receipt=self.views['original']['score_receipt'],r2_receipt=self.views['r2']['score_receipt'],capture_complete=True,original_exit_status=0,r2_exit_status=0,producer_code=self.control_fixture['producer'],callback_freeze=callback,original_clock=C.identity(clock),original_capture=C.identity(capture),capture_complete_utc='2026-10-08T03:00:03Z',r2_start_utc='2026-10-08T03:00:04Z',r2_complete_utc='2026-10-08T03:00:05Z',actual_permit_identity=permit,synthetic_only=True))
        self.views['execution']=C.identity(execution)

    @contextlib.contextmanager
    def active_t5_fixture(self):
        self.remove_b_outputs()
        a=C.Association(self.project,synthetic=True)
        reference_snapshot=self.a;self.a=a
        try:
            with a.installed():
                a.authorize_ap_route('AP6')
                a.official_views(self.views['original'],self.views['r2'],self.views['execution'])
                yield a
        finally:self.a=reference_snapshot

    @contextlib.contextmanager
    def t5_fixture(self):
        with self.active_t5_fixture() as a:
            yield a,C.read(a.out/'T5_IDENTITY_COMMITMENTS.json'),a.out/'SCIENCE_FREEZE.json',a.out/'consumer_roots.py',C.LIVE/C.ENTRIES['cps8_projection']

    def bind_temporary_T5(self,a):return [__import__('os').path.relpath(x['path'],a.q) for x in C.read(a.out/'T5_BINDING.json')['files']]
    def renew_temporary_T5(self,a):return self.bind_temporary_T5(a)

    def exact_t5_list(self):
        roots=C.read(self.out/'T5_BINDING.json')['files']
        assert len(roots)==len({r['path'] for r in roots}) and all(self.a.metadata_root(r['path']) for r in roots)
        assert all('tables' not in Path(r['path']).parts for r in roots)
        for p in (self.d/'state/models/model.pkl',self.d/'state/scoring/score.json',self.d/'host_state/data.json',self.d/'dly8/model.npy'):
            assert not self.a.metadata_root(p)
        return dict(metadata_only=True,all_payloads_committed_separately=True)

    def load_launch(self):return __import__('dispatch')
    def production_gate(self,missing_t4c=False):
        with self.changed(self.d/('T4C_BINDING.json' if missing_t4c else 'DISK_FREEZE.json'),remove=True):
            return self.refuse(lambda:C.Association(self.project,synthetic=True).release())

    @contextlib.contextmanager
    def changed(self,path,*,value=None,remove=False):
        p=Path(path);saved=p.read_bytes() if p.exists() and p.is_file() else None
        try:
            if remove:p.unlink()
            else:dump(p,value)
            yield
        finally:
            if p.is_symlink():p.unlink()
            if p.is_dir():shutil.rmtree(p)
            if saved is not None:p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(saved)
            elif p.exists():p.unlink()

    def official_score_publication(self,variant='valid'):
        return self.score_case('original',variant)
    def official_score_main_scope(self,variant='valid'):
        return self.score_case('original',variant)
    def pinned_fill_authority(self,variant='valid'):
        return self.authority_case(variant)
    def pinned_fill_author_schema_drift(self):return self.authority_case('schema')
    def pinned_fill_shared_static_inputs(self,drift=None):
        return self.authority_case('drifted' if drift else 'valid')
    def pinned_fill_anchor_sidecar(self,mode='AGREE'):

        record=dict(primary={'fixed':True},anchor=dict(synthetic_only=True,claim_cap={'mode':mode}))
        frozen=encoded(record['primary']);assert encoded(record['primary'])==frozen
        return dict(mode=mode,primary_bytes_unchanged=True,production_inline_sidecar_refused=True,rendering_removed=True)

    def decision_anchor_regression(self):

        import science_contract
        self.remove_b_outputs()
        self.authority_case('valid')
        trap=self.project/'ARTIFICIAL_UNLISTED_DECISION.txt';trap.write_text('ARTIFICIAL TRAP NEVER READ\n')
        freeze=self.out/'SCIENCE_FREEZE.json';value=copy.deepcopy(C.read(freeze))
        value['scientific_decisions'].append(C.identity(trap))
        calls=[];original=science_contract._exact
        def record(c,item,root):
            calls.append(item['path']);return original(c,item,root)
        try:
            with self.changed(freeze,value=value):
                t5=copy.deepcopy(C.read(self.out/'T5_BINDING.json'))
                t5['files']=[C.identity(freeze) if r['path']==str(freeze) else r for r in t5['files']]
                with self.changed(self.out/'T5_BINDING.json',value=t5):
                    science_contract._exact=record
                    try:C.Association(self.project,synthetic=True).release()
                    except C.Refusal as e:assert str(e)=='Frozen protocol/decision identities missing/changed'
                    else:raise AssertionError('Forged public decision accepted')
                    finally:science_contract._exact=original
            assert str(trap) not in calls
        finally:trap.unlink()
        return dict(public_ancestor_exact_identity=True,forged_decision_rejected_before_read=True,synthetic_only=True,production_authority=False)

    def authority_case(self,variant='valid'):
        self.remove_b_outputs()
        path=self.out/'SCIENCE_FREEZE.json';value=copy.deepcopy(C.read(path))
        if variant=='valid':
            a=C.Association(self.project,synthetic=True);a.release();assert a._released
            return dict(new_schema=value['schema'],whole_FILL_authority=False,fixture_premise_only=True)
        aliases={'old_round':'schema','inventory':'omitted','bytes':'drifted','current_receipt':'test_state'}
        variant=aliases.get(variant,variant)
        with self.changed(path,value=value):
            if variant=='missing':path.unlink()
            elif variant in {'unfrozen','state'}:value['state']='NOT_FROZEN';dump(path,value)
            elif variant in {'schema','wrong_view'}:value['schema']='OLD_FILL_AUTHORITY_REFUSED';dump(path,value)
            elif variant in {'drifted','wrong_seal'}:path.write_bytes(path.read_bytes()+b' ')
            elif variant in {'unlisted'}:
                with self.changed(self.out/'T5_BINDING.json',value={**C.read(self.out/'T5_BINDING.json'),'files':[r for r in C.read(self.out/'T5_BINDING.json')['files'] if r['path']!=str(path)]}):return self.refuse(lambda:C.Association(self.project,synthetic=True).release())
            elif variant in {'after_T5'}:value['frozen_utc']='2026-10-09T00:00:00Z';dump(path,value)
            elif variant=='extra':value['files']['EXTRA.json']={'bytes':0,'sha256':'0'*64};dump(path,value)
            elif variant in {'omitted','inventory'}:value['files'].pop(next(iter(value['files'])));dump(path,value)
            elif variant=='duplicate':
                text=json.dumps(value);path.write_text('{"schema":"DUPLICATE",'+text[1:])
            elif variant in {'alias','symlink'}:
                target=path.with_name('ALIAS_TARGET.json');target.write_bytes(path.read_bytes());path.unlink();path.symlink_to(target)
            elif variant=='directory':path.unlink();path.mkdir()
            elif variant=='test_state':value['acceptance']['sha256']='0'*64;dump(path,value)
            else:raise AssertionError('Unknown scientific timestamp_checks variant '+variant)
            return self.refuse(lambda:C.Association(self.project,synthetic=True).release())

    def score_case(self,view='original',variant='valid'):
        self.remove_b_outputs()
        items=copy.deepcopy(self.views);wire=C.read(self.out/'SCORER_CONTRACT.json')[view]
        receipt=Path(items[view]['score_receipt']['path']);report=Path(items[view]['score_report']['path'])
        if variant in {'valid','raw_valid'}:
            with self.active_t5_fixture() as a:
                certificate=a.official_views(items['original'],items['r2'],items['execution'])
                assert len(certificate['files'])>2 and items['original']['score_receipt']['path']!=items['r2']['score_receipt']['path']
                return dict(both_verified=True,distinct_receipts=True,real_score_run=False)
        with self.changed(receipt,value=C.read(receipt)),self.changed(report,value=C.read(report)):
            if variant in {'missing','raw_missing'}:receipt.unlink()
            elif variant in {'unverified','unfrozen'}:
                v=C.read(receipt);v['state']='NOT_COMPLETE';dump(receipt,v);items[view]['score_receipt']=C.identity(receipt)
            elif variant in {'identity_drift','drifted','bytes_drift'}:receipt.write_bytes(receipt.read_bytes()+b' ')
            elif variant=='missing_identity':items[view]['score_receipt'].pop('sha256')
            elif variant in {'wrong_seal','receipt_seal_drift'}:
                v=C.read(receipt);v['seal_sha256']='0'*64;dump(receipt,v);items[view]['score_receipt']=C.identity(receipt)
            elif variant in {'report_drift','report_bytes_drift'}:report.write_bytes(report.read_bytes()+b' ')
            elif variant in {'report_unbound','omitted','outside_receipt','member_outside'}:
                v=C.read(receipt);v['files']=[];dump(receipt,v);items[view]['score_receipt']=C.identity(receipt)
            elif variant=='duplicate':
                v=C.read(receipt);v['files']*=2;dump(receipt,v);items[view]['score_receipt']=C.identity(receipt)
            elif variant in {'wrong_view','missing_marker'}:
                v=C.read(receipt)
                if view=='r2':v.pop('evaluation_view',None)
                else:v['evaluation_view']=wire.get('evaluation_view',{})
                dump(receipt,v);items[view]['score_receipt']=C.identity(receipt)
            elif variant in {'alias','symlink','leaf_symlink','parent_symlink'}:
                target=receipt.with_name('ARTIFICIAL_ALIAS.json');target.write_bytes(receipt.read_bytes());receipt.unlink();receipt.symlink_to(target)
            elif variant=='directory':receipt.unlink();receipt.mkdir()
            elif variant in {'extra','unsealed_extra'}:
                extra=receipt.parent/'UNSEALED_EXTRA.json';dump(extra,{'synthetic_only':True})
            elif variant=='after_T5':


                clock=Path(C.read(items['execution']['path'])['original_clock']['path'])
                v=C.read(clock);v['score_complete_utc']='2026-10-07T00:00:00Z'
                with self.changed(clock,value=v):return self._refused_views(items)
            elif variant=='unlisted':


                t5=C.read(self.out/'T5_BINDING.json');producer=C.read(items['execution']['path'])['producer_code']['path'];t5['files']=[r for r in t5['files'] if r['path']!=producer]
                with self.changed(self.out/'T5_BINDING.json',value=t5):return self._refused_views(items,'Runtime member not exact T5-listed')
            elif variant in {'record_drift','before_first_write','before_receipt_write','closure_drift','derived_drift'}:
                with self.active_t5_fixture() as a:
                    certificate=a._official_ready
                    report.write_bytes(report.read_bytes()+b' ')
                    result=self.refuse(lambda:a._check_official_score(certificate))
                    assert a._official_ready is None and a._ap_runtime.grant_record is None
                    return result
            elif variant.startswith('scorer_'):
                sf=self.out/'SCORER_CODE_FREEZE.json'
                if variant=='scorer_missing':return self._scorer_fault('missing')
                return self._scorer_fault('state' if variant=='scorer_unverified' else 'drifted')
            else:raise AssertionError('Unknown score refusal '+variant)
            try:return self._refused_views(items)
            finally:
                for name in ('UNSEALED_EXTRA.json','ARTIFICIAL_ALIAS.json'):
                    p=receipt.parent/name
                    if p.exists():p.unlink()

    def _refused_views(self,items,needle=None):


        a=C.Association(self.project,synthetic=True)
        with a.installed():
            def public_boundary():
                a.authorize_ap_route('AP6')
                return a.official_views(items['original'],items['r2'],items['execution'])
            result=self.refuse(public_boundary,needle)
            assert a._official_ready is None and a._ap_runtime.grant_record is None
            return result

    def _scorer_fault(self,variant):
        sf=self.out/'SCORER_CODE_FREEZE.json';v=C.read(sf)
        with self.changed(sf,value=v):
            if variant=='missing':sf.unlink()
            elif variant=='state':v['state']='NOT_COMPLETE';dump(sf,v)
            else:sf.write_bytes(sf.read_bytes()+b' ')
            return self.refuse(lambda:C.Association(self.project,synthetic=True).release())

    def official_cache_regression(self,case):
        self.restore();self.remove_b_outputs()
        with self.active_t5_fixture() as a:
            report=Path(self.views['r2']['score_report']['path'])
            cached=copy.deepcopy(a._official_ready)
            if case=='public_verified_score_payload_read_survives_T5_revalidation':
                common=a.load('batch_inputs')
                for view in ('original','r2'):
                    path=Path(self.views[view]['score_report']['path'])
                    expected=self.fixture_snapshots[path]
                    assert path.read_bytes()==expected
                    assert common.read_json(path)==json.loads(expected)
                assert a._official_ready is not None and a._ap_runtime.grant_record is not None
                return dict(raw_path_and_frozen_public_helper=True,both_verified_report_reads=True,full_T5_gate_retained=True,real_scoring=False)
            if case=='failed_initial_view_validation_revokes_cached_graph':
                broken=copy.deepcopy(self.views['r2']);broken['score_receipt']=self.views['original']['score_receipt']
                result=self.refuse(lambda:a.official_views(self.views['original'],broken,self.views['execution']),'Wrong view/receipt destination')
            elif case=='score_namespace_extra_after_completion_revokes':
                extra=report.parent/'ARTIFICIAL_UNSEALED_LATE.json'
                dump(extra,dict(synthetic_only=True,unsealed=True))
                try:result=self.refuse(lambda:report.read_bytes(),'Official output namespace changed after completion')
                finally:extra.unlink()
            else:raise AssertionError('Unknown cache regression '+case)
            assert a._official_ready is None and not a._official_files and a._ap_runtime.grant_record is None
            stale=self.refuse(lambda:a._check_official_score(cached),'No current verified official completion certificate')
            blocked=self.refuse(lambda:report.read_bytes(),'No consumer payload read before verified original/capture/R2 completion')
            source=self.refuse(lambda:a._ap_runtime.member(self.control_fixture['producer']['path']),'G39 family has no runtime authorization')
            return dict(result,cached_completion_and_runtime_grant_revoked=True,stale_certificate_refused=stale,old_payload_read_refused=blocked,regrant_required=source,real_scoring=False)

    def scorer_preparation(self,variant='valid'):
        from scorer_metadata import _proposal
        import consumer_roots as Actual
        self.remove_b_outputs()
        a=Actual.Association(self.project,synthetic=True)
        binding=C.identity(self.out/'SCORER_BINDINGS.json');timestamp_checks=C.identity(self.out/'SCIENCE_FREEZE.json')
        with a.installed(preparation=True,metadata_only=True):
            with a._source_loading():common=a._load_verified('batch_inputs')
            code=C.read(Actual.LIVE/Actual.B_REL/'CODE_FREEZE.json')
            tests=copy.deepcopy(code['test_receipts_provenance']['tests'])
            def proposal():return _proposal(a,common,binding,tests,timestamp_checks)
            if variant=='valid':
                result=proposal();assert result['state']=='SCIENTIFIC_SCORER_METADATA_PROPOSAL_NOT_FREEZE' and 'frozen_utc' not in result
                return dict(original_source_test_census_verified=True,metadata_proposal_only=True,production_grant=False)
            if variant=='declared_test_path_drift':tests['path']=str(self.out/'foreign_tests.json')
            elif variant=='test_SHA_drift':tests['sha256']='0'*64
            elif variant=='fill_wrong_path':timestamp_checks=dict(timestamp_checks,path=str(self.out/'FOREIGN_SCIENCE_FREEZE.json'))
            elif variant=='shell_hash_drift':
                shell=a.b/'host_postscore_a8batch.sh';reference_snapshot=shell.read_bytes()
                try:
                    shell.write_bytes(reference_snapshot+b'# ARTIFICIAL drift\n')
                    return self.refuse(proposal)
                finally:shell.write_bytes(reference_snapshot)
            elif variant=='unknown_read':
                unknown=self.scratch/'unsealed_scorer_metadata_input.json';dump(unknown,dict(synthetic_only=True))
                return self.refuse(lambda:common.read_json(unknown))
            else:raise AssertionError('Unported scorer preparation variant '+variant)
            return self.refuse(proposal)

    def operational_history_case(self,variant='valid'):
        if variant in {'arbitrary_md','history_envelope_drift'}:


            from inherited_tests_r8bpre import sealed_census_case
            return sealed_census_case(self,variant)
        return super().operational_history_case(variant)

    def review_readiness(self,variant='valid'):

        import review_gate
        root=self.scratch/'independent_science_review_unit'
        shutil.rmtree(root,ignore_errors=True);root.mkdir()
        dump(root/'SYNTHETIC_ONLY.json',{'synthetic_only':True})
        (root/'consumer_roots.py').write_text('# ARTIFICIAL inert source\n')
        (root/'static_note.md').write_text('ARTIFICIAL static artifact\n')
        pin=lambda p:{k:v for k,v in C.identity(p).items() if k!='path'}
        spec=dict(case_ids=['ARTIFICIAL_METADATA_PREDICATE'],tested_source_files=['consumer_roots.py'])
        dump(root/'SCIENTIFIC_ACCEPTANCE_SPEC.json',spec)
        dump(root/'FREEZE_CENSUS.json',dict(files=['consumer_roots.py','static_note.md'],pending_members=[]))
        test=dict(schema='C_SCORING_ARTIFICIAL_REVIEW_METADATA_V1',state='UNIT_REVIEW_METADATA_PREMISE_NOT_ACCEPTANCE',task_revision='SCORING_C8B_SCIENCE_V1',synthetic_only=True,premise_only=True,utc='2026-10-08T00:00:00Z',case_ids=spec['case_ids'],delivered_sources={'consumer_roots.py':pin(root/'consumer_roots.py')},failures=[],errors=[],skipped=[],production_state_reads=0,production_commands_run=0)
        testpath=root/'SCIENTIFIC_ACCEPTANCE_RECEIPT.json';dump(testpath,test)
        old=root/'REVIEW_OLD_source.md';old.write_text(' Verdict ：SET FIRST\nARTIFICIAL metadata UNIT review\n');oldid=C.identity(old)
        final=root/'REVIEW_FINAL_source.md';final.write_text(' Verdict ：FREEZE-READY\nARTIFICIAL metadata UNIT premise only. Replaces '+old.name+' '+oldid['sha256']+'\n')
        review=dict(independent=True,reviewed_by='ARTIFICIAL independent metadata unit reviewer',reviewed_utc='2026-10-08T00:01:00Z',test_receipt=C.identity(testpath),reviewed_sources=copy.deepcopy(test['delivered_sources']),review_files={x.name:pin(x) for x in (old,final)},final_review=C.identity(final),replaces=[oldid],production_state_reads=0,production_commands_run=0)
        try:
            if variant=='missing_acceptance':testpath.unlink()
            elif variant=='SET_FIRST_final':final.write_text(' Verdict ：SET FIRST\n');review['final_review']=C.identity(final);review['review_files'][final.name]=pin(final)
            elif variant=='exclusion_missing':review['replaces']=[]
            elif variant=='exclusion_SHA_drift':review['replaces'][0]['sha256']='0'*64
            elif variant=='exclusion_not_addressed':final.write_text(' Verdict ：FREEZE-READY\nARTIFICIAL without address\n');review['final_review']=C.identity(final);review['review_files'][final.name]=pin(final)
            elif variant=='test_receipt_drift':testpath.write_bytes(testpath.read_bytes()+b' ')
            elif variant=='tested_code_drift':(root/'consumer_roots.py').write_text('# changed\n')
            elif variant=='tested_source_missing':test['delivered_sources']={}
            elif variant=='new_review_after_acceptance':(root/'REVIEW_NEW_source.md').write_text(' Verdict ：SET FIRST\n')
            elif variant=='review_bytes_drift':old.write_text(old.read_text()+'changed\n')
            elif variant=='non_independent':review['independent']=False
            elif variant=='empty_reviewer':review['reviewed_by']=' '
            elif variant=='wrong_timezone':review['reviewed_utc']='2026-10-08T10:01:00+10:00'
            elif variant=='review_before_test':review['reviewed_utc']='2026-10-07T23:59:00Z'
            elif variant=='nonzero_production_reads':review['production_state_reads']=1
            elif variant=='nonzero_production_commands':review['production_commands_run']=1
            elif variant in {'pre_F12_receipt','old_task_receipt'}:test['task_revision']='OLD_WRITING_PHASE_NOT_SCIENTIFIC_FINAL'
            elif variant=='failed_test_receipt':test['failures']=[{'case_id':'ARTIFICIAL_FAIL'}]
            elif variant=='mixed_final_verdict':final.write_text(final.read_text()+' Verdict ：SET FIRST\n');review['final_review']=C.identity(final);review['review_files'][final.name]=pin(final)
            elif variant=='unsafe_final_path':review['final_review']=dict(oldid,path=str(root.parent/'outside_review.md'))
            elif variant=='missing_static_artifact':(root/'static_note.md').unlink()
            elif variant!='valid':raise AssertionError('Unported review variant '+variant)
            if variant not in {'missing_acceptance','test_receipt_drift'}:dump(testpath,test)
            def check():return review_gate._review_provenance(root,test,review)
            if variant!='valid':return self.refuse(check)
            result=check();assert result['inactive']==[oldid] and result['freeze_permitted'] is False
            return dict(exact_review_provenance_predicates=True,unit_premise_not_acceptance=True,review_files=result['review_files'],freeze_writer_run=False)
        finally:shutil.rmtree(root)

    def artifact_check(self):
        current={name:C.sha(HERE/name) for name in json.loads((HERE/'PUBLIC_RUNTIME_SOURCE_MANIFEST.json').read_bytes())['files'] if name.endswith('.py')}
        assert current==self.initial_artifacts
        return dict(all_delivered_python_unchanged=True)

    def bootstrap_case(self,variant):
        from bootstrap import _proof,_scope,_collect
        from inherited_tests_r8bpre import four_remedies
        with four_remedies(self) as f:
            a=f['a']


            manifest=C.read(self.out/'PUBLIC_RUNTIME_SOURCE_MANIFEST.json')
            proof=dict(schema='C_SCORING_BOOTSTRAP_SOURCE_PROPOSAL_V1',source_adopted=True,scientific_eligibility_changed=False,consumer_release=False,synthetic_only=True,source_manifest=C.identity(self.out/'PUBLIC_RUNTIME_SOURCE_MANIFEST.json'),sources=manifest['files'],acceptance=C.identity(self.out/'SCIENTIFIC_ACCEPTANCE_RECEIPT.json'),independent_review=C.identity(self.out/'INDEPENDENT_REVIEW.json'),numeric_ancestor_contract=C.identity(self.out/'NUMERIC_ANCESTOR_CONTRACT.json'),host_bindings=C.read(self.out/'SCIENTIFIC_ASSOCIATION.json'))
            item=self.out/'ARTIFICIAL_BOOTSTRAP_SOURCE_PROPOSAL.json';dump(item,proof)
            if variant=='G45_missing_ancestor_or_review_refused':
                proof['numeric_ancestor_contract']['sha256']='0'*64;dump(item,proof)
                return self.refuse(lambda:_proof(a,C.identity(item)))
            authenticated=_proof(a,C.identity(item))


            old=C.ACTIVE;a._bootstrap_source_ready=True;a._bootstrap_depth=1;C.ACTIVE=a
            destination=self.scratch/'G45_metadata_proposal';shutil.rmtree(destination,ignore_errors=True);destination.mkdir()
            try:
                with a._validation():
                    evidence,source=_collect(a,destination)
                assert a._released is False and not a._official_ready and set(evidence['remedy_history']['remedies'])==set(f['pins'])
                result=self.refuse(lambda:a.load('read_comparisons'))
                return dict(no_C_freeze_dependency=True,consumer_release=False,exact_original_payload_commitments=len(source['files']),four_honest_remedies=True,public_consumer_refusal=result,host_release_unit_premise=True)
            finally:C.ACTIVE=old;a._bootstrap_source_ready=False;a._bootstrap_depth=0;shutil.rmtree(destination)

    def parity_test(self):
        self.restore()
        for r in ('state','dly8','cps8'):
            shutil.rmtree(self.b/r,ignore_errors=True);shutil.copytree(self.d/r,self.b/r)
        with baseline(self.a) as load:
            old=self.operations(load,False)
        old={k:v() if callable(v) else v for k,v in old.items()}
        self.remove_b_outputs()
        with self.active_t5_fixture() as a:
            new=self.operations(a.load,True)
        new={k:v() if callable(v) else v for k,v in new.items()}
        assert set(old)==set(new)
        for name in old:assert old[name]==new[name],name
        self.parity={name:dict(bytes_equal=True,sha256=hashlib.sha256(old[name]).hexdigest()) for name in old}
        return dict(scientific_surfaces=len(old),byte_equal=True,B100000_native_case=True,FILL_render_suite_removed=True)

    def import_gate(self):
        a=C.Association(self.project,synthetic=True)
        return self.refuse(lambda:a.load('runner'),'Scientific integration pending')
    def install_gate(self):
        a=C.Association(self.project,synthetic=True);a.synthetic=False
        def enter():
            with a.installed():raise AssertionError('Real release bypassed')
        return self.refuse(enter,'Accept phase allows explicitly artificial')
