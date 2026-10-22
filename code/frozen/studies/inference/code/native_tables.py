'Read the numerical columns produced by checked table functions.'
import ast
from collections import Counter
from types import SimpleNamespace
import numpy as np
import read_comparisons as P


def frozen_method(path,name,ns):
    pins=P.strict_json(P.HERE/'DEPENDENCY_PINS.json')['files'];rel=str(path.relative_to(P.PROJ))
    P.require(P.sha256(path)==pins[rel],'Native generator drift')
    tree=ast.parse(path.read_text());nodes=[n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef) and n.name==name]
    P.require(len(nodes)==1,'Ambiguous native generator')
    fn=nodes[0];exec(compile(ast.Module(body=[fn],type_ignores=[]),str(path),'exec'),ns)
    return ns[name]


class Cells:
    def __init__(self,primary_tests,sensitivity_tests,robustness_tests,E,current,prop):
        self.primary_tests,self.sensitivity_tests,self.robustness_tests=primary_tests,sensitivity_tests,robustness_tests
        self.current,self.prop=current,prop
        self.a2={};self.primary={};self.seedfrag={};self.tables=[]
        self.a7_checks=Counter();self.a6_checks=Counter();self.k7_expect={};self.secondary={}
        self.a2post=SimpleNamespace(src='inference B100000')
        self.T3=E.F3B.templates()
        self.a4={'tasks':{t:{'three_seed':prop['details'][t]['three_seed']} for t in P.PAIRS},'table_cells':{'pcontent':{t:robustness_tests.SENTENCES['A4PCN'] if t=='notice' else robustness_tests.SENTENCES['A4SUB'] for t in P.PAIRS}}}
        self.a3post=SimpleNamespace(src='inference B100000',task=lambda t:dict(
            seed_sign_only={},a3_new_cheap_contrasts={r['arm']+'-'+r['reference']:dict(r,state='COMPUTED',n_days=current[t+'/cheap']['days']) for r in current[t+'/cheap']['reports']},
            combination_robustness_a3=prop['details'][t]['a3']['combination_robustness_a3']))
        self.a4post=SimpleNamespace(src='inference B100000')
        self.s=SimpleNamespace(scored=P.HERE,src=lambda f:f)
        self._bound_values=[];self._set_intervals=E.set_intervals
        for task in P.PAIRS:
            f=current[task+'/primary'];self.a2[task]={'primary':f['reports'],'combination':dict(state=current[task+'/combination']['state'],family=current[task+'/combination'],sentence=current[task+'/combination'].get('reason','not available'))}
            self.primary[task]=[SimpleNamespace(arm=r['arm'],ref=r['reference'],file=f'{task}__PRIMARY.json',b1=r['bootstrap']['1'],dm=dict(n_days=f['days'],mean_difference=r.get('mean_difference')),row=r) for r in f['reports']]
            seeds=(f.get('three_seed') or {}).get('reports',[])
            self.seedfrag[task]={'rows':[dict(state='SEED_ROBUSTNESS_NOT_EVALUABLE' if not seeds else 'SEED_CONSISTENT' if seeds[i]['decision']==r['decision'] else 'SEED_FRAGILE',three_seed_mean_decision=seeds[i]['decision'] if seeds else None) for i,r in enumerate(f['reports'])]}
    def table3b(self,label,caption,header,rows,spec):
        import re
        cells=[]
        for line in rows:
            if line==r'\midrule':continue
            line=self._set_intervals(line)[0]
            line=re.sub('\x00(\\d+)\x01',lambda m:self._bound_values[int(m[1])],line)
            values=[]
            for cell in line.removesuffix(r' \\').split(' & '):
                span=re.fullmatch(r'\\multicolumn\{(\d+)\}\{l\}\{(.*)\}',cell)
                values.extend(['']*(int(span[1])-1)+[span[2]]) if span else values.append(cell)
            cells.append(values)
        self.tables.append(dict(id=label.rsplit('-',1)[-1],label=label,caption=caption,header=header,spec=spec,
            rows=cells,location='S7',bootstrap_draws=P.DRAWS))
        return ''
    def R(self,value,*args):
        self._bound_values.append(str(value))
        return '\x00'+str(len(self._bound_values)-1)+'\x01'
    def pair(self,a,b):return a+' - '+b
    def combo_tex(self,a,b):return '('+a+' + benchmark)/2 - ('+b+' + benchmark)/2'
    def task_decimals(self,task):return max(self.decimals(r['interval95_one_day']) for r in self.a2[task]['primary'])
    def decimals(self,v):return self.robustness_tests.decimals(v)
    def count(self,v,*args):return '--' if v is None else str(v)
    def num(self,v,*args):return str(v)
    def aud(self,c):return self.sensitivity_tests.aud(c.dm.get('mean_difference'))
    def cell_interval(self,v,d,*args):
        if v is None:return 'undefined'
        lo,hi=self.primary_tests.fmt_interval(v,d);return '$['+lo+', '+hi+']$'
    def cell_p(self,v,*args):return self.primary_tests.display_p(v)
    def seed_effect(self,t,i,s):
        f=self.current[t+'/primary' if s==20260919 else t+'/seed_'+str(s)]
        return self.primary_tests.fmt_effect(f['reports'][i].get('effect_percent_reference_mae'),self.task_decimals(t)) if f['state']=='COMPUTED' else 'not available'
    def seed_sd(self,t,i):
        vals=[self.current[k]['reports'][i].get('effect_percent_reference_mae') for k in (t+'/primary',t+'/seed_20260920',t+'/seed_20260921') if k in self.current and self.current[k]['state']=='COMPUTED']
        return P.decimal(float(np.std(vals,ddof=1)),3) if len(vals)==3 else 'not available'
    def plain_state(self,state):return (state or 'not recorded').replace('_',' ').lower()
    def fx3b(self,text,*args):return text
    def esc6(self,text,*args):return text
    def dagger(self,c):return '$^{\\dagger}$' if not isinstance(c,dict) and c.slot.get('days')==38 else ''
    def pcontent_cells(self,source,n):return ['']*(n-1)+[self.a4['table_cells']['pcontent'][source]]
    def verbatim(self,s,*a):return s
    def a3_report_cells_d(self,r,base,d):return [str(r.get('n_days','')),self.primary_tests.fmt_effect(r.get('effect_percent_reference_mae'),d),self.cell_interval(r['bootstrap']['1'].get('interval95_percent'),d),self.cell_p(r.get('p_two_sided')),self.robustness_tests.CS_WORDS.get(self.primary_tests.decision_class(r.get('mean_difference'),r.get('p_two_sided')),'not evaluable')]


def table_records(primary_tests,sensitivity_tests,robustness_tests,F,current,clipping,stages,prop):
    E=F.load_summary_comparisons();B=E.F3B;_,_,F2,_=B.deps()


    ns=dict(SOURCES=('news','notice'),F2=F2,robustness_tests=robustness_tests,PW=B.PW,finite=primary_tests.finite)
    c=Cells(primary_tests,sensitivity_tests,robustness_tests,E,current,prop)
    for method in ('supp_primary_tables3b','combination_table3b','cheap_table3b'):
        frozen_method(P.MS/'main_comparisons_conf_results.py',method,ns)(c)
    ids={'a':'primary_effects','b':'primary_tests','seeds':'primary_seeds','combination':'combinations','cheap':'cheap'}
    for t in c.tables:
        t['id']=ids[t['id']];t['label']='supp:tab:a8post-'+t['id'];t['caption']+=' B = 100000.'


    D=E.F3D;ns.update(F3B=B,F3D=D,W7=E.W7,WD=D.WD,TP7=E.TP7,
        IMP=robustness_tests.IMP,NULL=robustness_tests.NULL,DET=robustness_tests.DET,require=P.require,PW=B.PW)
    c.a2['notice']['a2_new_secondary_contrasts']={}
    for task in P.PAIRS:
        c.secondary[task]={}
        for k,f in current.items():
            if not k.startswith(task+'/native:') or '__SECONDARY__' not in k:continue
            for r in f.get('reports',[]):
                pair=(r['arm'],r['reference'])
                c.secondary[task][pair]=(dict(state='NOT_EVALUABLE_INPUT_UNAVAILABLE') if r['decision']=='NOT_EVALUABLE' else
                    SimpleNamespace(i1=r.get('interval95_one_day'),effect=r.get('effect_percent_reference_mae'),
                        mean=r.get('mean_difference'),file=k.split('/')[-1]+'.json',
                        slot=dict(days=f['days']),dm=dict(p_two_sided=r.get('p_two_sided'))))


        from frozen_losses import native_functions
        for pair in native_functions()['_secondary_contrasts'](task):
            c.secondary[task].setdefault(tuple(pair),dict(state='NOT_EVALUABLE_WHOLE_STAGE_UNAVAILABLE'))
        if task=='notice':
            for a,b in primary_tests.A2_NEW_CONTRASTS[task]:
                r=next((r for r in current[task+'/cheap']['reports'] if (r['arm'],r['reference'])==(a,b)),None)
                c.a2['notice']['a2_new_secondary_contrasts'][a+'-'+b]=dict(r,state='COMPUTED',n_days=current[task+'/cheap']['days']) if r and r['decision']!='NOT_EVALUABLE' else dict(state='NOT_EVALUABLE_INPUT_UNAVAILABLE')


        family=current[task+'/combination_benchmark']
        for r in family.get('reports',[]):
            c.secondary[task][(r['arm'],r['reference'])]=(dict(state='NOT_EVALUABLE_WHOLE_STAGE_UNAVAILABLE') if family['state']!='COMPUTED' or r['decision']=='NOT_EVALUABLE' else
                SimpleNamespace(i1=r['interval95_one_day'],effect=r['effect_percent_reference_mae'],mean=r['mean_difference'],
                    file=task+'__DIRECT_BENCHMARK.json',slot=dict(days=family['days']),dm=dict(p_two_sided=r['p_two_sided'])))
    fn=frozen_method(P.MS/'summary_comparisons_conf_results.py','a2_notice_rows',ns)
    c.a2_notice_rows=lambda extra,d:fn(c,extra,d)
    for task in P.PAIRS:
        frozen_method(P.MS/'summary_comparisons_conf_results.py','all_secondary_table3b',ns)(c,task)
        c.tables[-1].update(id='secondary_'+task,label='supp:tab:a8post-secondary-'+task)

    from collections import OrderedDict
    ns.update(OrderedDict=OrderedDict,F3=B.deps()[1],IMP=robustness_tests.IMP,NULL=robustness_tests.NULL,DET=robustness_tests.DET)
    def seed_report(fname):
        task=fname.split('__')[0];seed=fname.split('SEED_')[1].split('.')[0]
        f=current[task+'/seed_'+seed]
        return dict(reports=[dict(r,dm_p1=dict(mean_difference=r.get('mean_difference'),p_two_sided=r.get('p_two_sided')),primary_decision=r['decision']) for r in f['reports']])
    c.s.has=lambda fname: fname.split('__')[0]+'/seed_'+fname.split('SEED_')[1].split('.')[0] in current
    c.s.json=seed_report
    c.row=lambda task,i:c.a2[task]['primary'][i]
    c.tn=lambda name:c.T3['sensitivity_names'][name]
    def matrix():
        out=OrderedDict()
        for name,layer in [('24h','window_24h'),('first_L','first_chunk'),('DROP_FIRST_SEVEN_DAYS','drop_first_seven'),('RECLIP','official_cap'),('U2','native:exposure'),('LABEL','label_replacement'),('L1','l1_family'),('PD','pd_family')]:
            cells={}
            for task in P.PAIRS:
                f=current.get(task+'/'+layer)
                if not f or f['state']!='COMPUTED':continue
                for i,r0 in enumerate(c.a2[task]['primary']):
                    r=next((r for r in f['reports'] if r['arm'].removesuffix('_L1').removesuffix('_PD')==r0['arm'] and r['reference'].removesuffix('_L1').removesuffix('_PD')==r0['reference']),None)
                    if r is None:continue
                    word={'CONDITIONAL_IMPROVEMENT':'FAVORABLE','CONDITIONAL_DETERIORATION':'UNFAVORABLE','NO_RELIABLE_INCREMENT_DETECTED':'NO_RELIABLE'}.get(r['decision'],'UNDEFINED')
                    cells[(task,i)]=(r.get('effect_percent_reference_mae'),r.get('interval95_one_day'),word,'inference B100000',layer)
            out[name]=cells
        return out
    c.sensitivity_matrix=matrix
    names=c.T3['sensitivity_names'];names.update(L1='absolute-error objective',PD='pre-dispatch input sensitivity')
    frozen_method(P.MS/'main_comparisons_conf_results.py','supp_sens_table3b',ns)(c)
    c.tables[-1].update(id='sensitivities',label='tab:main_comparisons-sensitivity')
    diag=[]
    for k,f in current.items():
        if 'subset' not in k and 'EXPOSURE' not in k:continue
        for r in f['reports']:
            d=c.decimals(r.get('interval95_one_day'));diag.append([k,c.pair(r['arm'],r['reference']),str(f.get('days','')),primary_tests.fmt_effect(r.get('effect_percent_reference_mae'),d),c.cell_interval(r.get('interval95_one_day'),d),c.cell_p(r.get('p_two_sided')),'descriptive only'])
    c.tables.append(dict(id='diagnostics',label='supp:tab:a8post-diagnostics',location='S7',bootstrap_draws=P.DRAWS,
        caption='Descriptive support subsets; no confirmatory class. B = 100000.',header=r'Subset & Contrast & Days & Effect (\%) & One-day 95\% & DM $p$ & Result \\',spec='lllllll',rows=diag or [['not available']*7]))
    clipfields=('arm','seed','variant','eligible_predictions','clipping_operations','raw_below_lower','raw_above_upper','final_lower_hits','final_upper_hits')

    header=E.F3B.templates()['supplement_block.clip_header']
    for task in P.PAIRS:
        rr=clipping[task]
        rows=[[str(r[k]) for k in clipfields] for r in rr] if rr and isinstance(rr[0],dict) else [['not recorded']*9]
        c.tables.append(dict(id='clipping_'+task,label='supp:tab:a8post-clipping-'+task,location='S9',bootstrap_draws=P.DRAWS,
            caption='Frozen clipping diagnostics, all arms, seeds and variants.',header=header,spec='lrlrrrrrr',rows=rows))


    pending_words='had no result when this version was filled'
    P.require(pending_words in F.templates()['forms']['A8ST_EXEC'], 'Pending narrative drift')
    execution_rows=[[pending_words if r[k]==P.CATEGORIES[4] else str(r[k] or '')
        for k in ('stage','conf','postseal','counted_category','reason','rerun_trigger')] for r in stages]
    c.tables.append(dict(id='execution',label='supp:tab:a8post-execution',location='S9',bootstrap_draws=P.DRAWS,
        caption='Execution dispositions.',header='Stage & confirmation & Post-seal & Counted category & Reason & Trigger \\\\',spec='llllll',rows=execution_rows))
    for t in c.tables:
        t['header']=F.rename_rendered(t['header']);t['caption']=F.rename_rendered(t['caption'])
        t['rows']=[[F.rename_rendered(cell) for cell in row] for row in t['rows']]
        width=t['header'].count(' & ')+1
        P.require(all(len(r)==width for r in t['rows']),'Native complete-column census failed: '+t['id'])


    forest_inputs={k:v for k,v in current.items() if not k.split('/',1)[1].startswith(('R8','DLY8','CPS8'))}
    _,forest=P.table_records(forest_inputs,{t:[['diagnostic']] for t in P.PAIRS},stages)
    primary=[]
    for task,pairs in P.PAIRS.items():
        for arm,ref in pairs:
            row=next((r for r in forest if r['group']=='Primary' and (r['task'],r['arm'],r['ref'])==(task,arm,ref)),None)
            if row is None:row=dict(task=task,group='Primary',arm=arm,ref=ref,effect=None,thick=None,thin=None,
                src='inference current reading',field=task+'/primary/'+arm,pcontent=None,bootstrap_draws=P.DRAWS)
            primary.append(row)
    forest=primary+[r for r in forest if r['group']!='Primary']
    return c.tables,forest
