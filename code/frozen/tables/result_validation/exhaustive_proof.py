'Enumerate synthetic table cases with the result renderer.'
from copy import deepcopy
from contextlib import nullcontext
import importlib.util
import itertools
import os
from pathlib import Path
import re
import subprocess
import time
from unittest.mock import patch

import table_results_conf_results as F

METRICS = ('words', 'characters', 'sentence')
GROUPS = tuple((c, s) for c in F.CLASSES for s in (False, True) if c != 'NE' or s)


class Enumerator:
    def __init__(self, fixture):
        self.base = fixture(); self.T = F.templates(); self.W = self.T['words']
        self.n = 0; self.sentence_max = 0; self.sentence_witness = ''
        self.local_sentence_records = {}; self.active_level = None; self.choice_cache={}
        self.domain = {}; self.last_gate = 0; self.minimum_free = 100; self.relation_domains = {}
        self.gate()

    def gate(self):
        F.require(os.getpriority(os.PRIO_PROCESS, 0) >= 5, 'proof requires nice 10 or authorized nice 5')
        line = subprocess.run(['memory_pressure'], capture_output=True, text=True, check=True).stdout.strip().splitlines()[-1]
        m = re.search(r'(\d+)%', line)
        F.require(m and int(m.group(1)) >= 25, 'proof stopped: less than 25 percent free memory')
        self.minimum_free = min(self.minimum_free, int(m.group(1))); self.last_gate = time.monotonic()

    def measure(self, ss):
        self.n += 1
        if time.monotonic()-self.last_gate > 20: self.gate()
        for s in ss:
            n = F.words(s)
            if n > self.sentence_max: self.sentence_max = n; self.sentence_witness = s
            F.require(n <= 35, 'exhaustive sentence over 35 words: '+s)
        text = ' '.join(ss)
        return {'words': F.words(text), 'characters': len(text), 'sentence': max(map(F.words, ss), default=0)}

    def value(self, ss, metric):
        return self.measure(ss)[metric]

    def helper_value(self, ss, metric):

        text=' '.join(ss)
        return F.words(text) if metric=='words' else len(text) if metric=='characters' else max(map(F.words,ss),default=0)

    def widest(self, original, cls, seven, labels, seed, estimate, reason):
        c = deepcopy(original)
        c.update({'class': cls, 'effect_percent': '+100.00000' if cls == 'DET' else '-100.00000',
                  'effect_aud': '+100.00000' if cls == 'DET' else '-100.00000', 'envelope': '100.000',
                  'family_one_day': ['-100.00000', '+100.00000'],
                  'family_seven_day': None if seven else ['-100.00000', '+100.00000'],
                  'per_contrast_seven_day': None if seven else ['-100.00000', '+100.00000'],
                  'checks': dict(zip(F.CHECKS, labels)), 'three_seed_class': seed,
                  'three_seed_effect': (('+' if seed=='DET' else '-')+'100.00000' if estimate and seed != 'NE' else None),
                  'reason': reason})
        if cls in ('IMP', 'DET') and c['checks']['family_interval'] == 'PASS':
            c['family_one_day'] = ['-100.00000', '-100.00000'] if cls == 'IMP' else ['+100.00000', '+100.00000']
        if cls == 'NE':
            for key in ('effect_percent', 'effect_aud', 'envelope', 'family_one_day', 'family_seven_day', 'per_contrast_seven_day'): c[key] = None
        return c

    def cores(self, task, original, level, alert):

        best = {}; vectors = 0
        for cls, seven in GROUPS:
            seeds = F.CLASSES if cls in ('IMP', 'DET') else (cls,)
            reasons = self.W['PLAIN_INC_REASON'] if cls == 'NE' else ('fail',)
            for labels in itertools.product(('PASS', 'FAIL', 'UNAVAILABLE'), repeat=6):
                if seven and labels[1] != 'UNAVAILABLE': continue
                for seed in seeds:
                    for estimate in ((False,) if seed == 'NE' else (False, True)):
                        for reason in reasons:
                            c = self.widest(original, cls, seven, labels, seed, estimate, reason)
                            ss = [F.pfmin_item(c, {'alert': alert})] if level == 'PFMIN' else F.member_sentences(c, self.T, level, alert)
                            val = self.measure(ss); vectors += 1
                            for metric in METRICS:
                                key = (cls, seven, metric)
                                if key not in best or val[metric] > best[key][0]: best[key] = (val[metric], c)
        self.domain['core_vectors_per_'+task+'_'+original['arm']+'_'+level+'_'+str(alert)] = vectors
        return best

    def clocks(self, task, floor=False):
        if task == 'news': return [None]
        result = [{'state':'NOT_RUN','public_by_admission':None,'maximum_delay_minutes':None,'reason_codes':[r]} for r in ('INPUT','FAIL')]
        result += [{'state':'NOT_INFORMATIVE','public_by_admission':None,'maximum_delay_minutes':None,'reason_codes':list(codes)} for n in range(1,6) for codes in itertools.combinations(('N1','N2','N3','N4','N5'),n)]

        result += [{'state': 'INFORMATIVE', 'public_by_admission': rate, 'maximum_delay_minutes': '99999',
                    'covered_n': 99999, 'listed_by_admission_n':99999 if F.decimal(rate)>=99 else 0, 'delay60_class': 'NE'} for rate in ('100.0', '0.000')]
        for clk in result: self.measure([F.clk_sentence({'clk8': clk}, floor)])

        best = {}
        for clk in result:
            late = clk['state'] == 'INFORMATIVE' and F.decimal(clk['public_by_admission']) < 99
            ss = [F.clk_sentence({'clk8': clk}, floor)]; values = self.measure(ss)
            for metric in METRICS:
                key = (late, metric)
                if key not in best or values[metric] > best[key][0]: best[key] = (values[metric], clk)
        return list({repr(v[1]): v[1] for v in best.values()}.values())

    def relations(self, task, c, clk, level, metric, alert=False):

        c = deepcopy(c); t = {'contrasts': [c], 'clk8': clk,'alert':alert}
        reason_ids=[k for k,v in self.T['forms'].items() if k.startswith('A8NR_') and '{' not in v and F.words(v)<=12]
        widest_reason=max(reason_ids,key=lambda k:F.words(F.form(k)) if metric=='words' else len(F.form(k)))
        for rel in c['relations'].values():rel['reason']=widest_reason
        def ss(): return F.relation_sentences(task, t, self.T, level)
        if c['class'] in ('IMP', 'DET'):


            c['design_layers'] = [k for k in self.W['PLAIN_LAYER'] if k not in ('windowed_activity','kcx','dly8_15','cps8')]; c['design_rejection_not_reproduced'] = True
        axes = {}
        for layer in F.LAYERS:
            states = F.REL_STATES
            if layer == 'KCX':states=('NOT_RUN',)
            if layer == 'DLY8' and task == 'news': states = ('NOT_RUN', 'NOT_APPLICABLE')
            if layer == 'DLY8' and task == 'notice' and clk['state'] == 'INFORMATIVE' and F.decimal(clk['public_by_admission']) < 99 and c['class'] != 'NE':
                states = ('SAME', 'DIFFERENT', 'NOT_EVALUABLE')
            opts = []
            for state in states:
                value = c['class'] if state == 'SAME' else ('IMP' if c['class'] != 'IMP' else 'NULL') if state == 'DIFFERENT' else None
                modes = ((False, 'single'),) if layer == 'R8' else ((None, None),)
                for checked, seeds in modes:
                    d = {'state': state, 'class': value, 'reason':widest_reason}
                    if layer=='CPS8' and state in ('SAME','DIFFERENT'):d['g0_class']=value if state=='SAME' else ('NULL' if value!='NULL' else 'IMP')
                    if layer == 'R8': d.update(fully_checked=checked, seeds_run=seeds)
                    opts.append(d)
            axes[layer] = opts
        axes['delay_classes'] = [{'5': c['class'], '15': a, '60': b} for a, b in itertools.product((*F.CLASSES, None), repeat=2)]
        self.relation_domains[task+'/'+c['class']+'/'+level+'/'+str(clk is not None and clk['state']=='INFORMATIVE' and F.decimal(clk['public_by_admission'])<99)] = {k: len(v) for k, v in axes.items()}
        selected = {}

        baseline = deepcopy(c); base_ss = ss(); base_value = self.measure(base_ss)
        deltas = []
        for axis, options in axes.items():
            best = None
            for option in options:
                if axis == 'delay_classes': c[axis] = option
                else: c['relations'][axis] = option
                value = self.value(ss(), metric)
                if best is None or value > best[0]: best = (value, deepcopy(option))
                if axis == 'delay_classes': c[axis] = baseline[axis]
                else: c['relations'][axis] = baseline['relations'][axis]
            selected[axis] = best[1]; deltas.append(best[0]-base_value[metric])
        for axis, option in selected.items():
            if axis == 'delay_classes': c[axis] = option
            else: c['relations'][axis] = option
        value = self.value(ss(), metric)
        if metric != 'sentence': F.require(value == base_value[metric]+sum(deltas), 'relation factoring is not additive')
        return c

    def authorize(self, r):

        r['author_confirmation']['choices'].update(r8_seeds='single', kcx='not_run',public_registration='b_private_timestamps_only')
        r['author_prescore']['kcx'].update(kcx_api_key_supplied_before_T5=False, kcx_spend_cap_usd=None)
        r['optional'].update(R8=True, KCX=False,batch_scoring=True)
        existing = {x['stage']: x for x in r['stages']}; ordered = []
        for text in self.W['STAGE_TABLE']['rows']:
            name = text.split(' (only')[0]
            if name == 'A8B-R8S': continue
            if name in existing: row = deepcopy(existing[name])
            else: row = {'stage': name, 'conf': '--', 'postseal': F.CATEGORIES[0], 'counted_category': F.CATEGORIES[0], 'reason': None, 'rerun_trigger': None}
            if name in ('PC','A2B-1','A2B-2','label_scoring','A8B-R8','A8B-R8N'): row.update(counted_category=F.CATEGORIES[0], postseal=F.CATEGORIES[0], reason=None)
            ordered.append(row)
        r['stages'] = ordered
        for row in r['stages']:
            if row['stage']=='KCX':row.update(counted_category=F.CATEGORIES[2],postseal=F.CATEGORIES[2],reason='A8NR_AUTHOR')
            if row['stage'] in ('PC','matched_controls') and r['pc_state']!='RESULT':row.update(counted_category=F.CATEGORIES[4],postseal=F.CATEGORIES[4],reason=None)
            if row['stage'] in ('PC','matched_controls') and r['pc_state']=='NOT_RUN_REPIN':
                row.update(counted_category=F.CATEGORIES[2],postseal=F.CATEGORIES[2],reason='A8NR_REPIN');continue
            if row['stage']=='matched_controls' and r['pc_state']=='RESULT':row.update(counted_category=F.CATEGORIES[4],postseal=F.CATEGORIES[4],reason=None)
        r['kept_alert_sentences']={task:[F.inherited_form('A6ALERT_S',task_label=F.kept_task_label(task))] for task,t in r['tasks'].items() if t['alert']}
        for task,t in r['tasks'].items():
            for c in t['contrasts']:
                c['relations']['R8']['seeds_run']='single'
                c['relations']['KCX'].update(state='NOT_RUN',**{'class':None},reason='A8NR_AUTHOR')
                for layer,rel in c['relations'].items():
                    if rel['state']=='PENDING':
                        name={'R8':'A8B-R8N' if task=='notice' else 'A8B-R8','DLY8':'DLY8','CPS8':'A8B-CPS8','KCX':'KCX'}[layer]
                        next(row for row in r['stages'] if row['stage']==name).update(counted_category=F.CATEGORIES[4],postseal=F.CATEGORIES[4],reason=None)
                if c['class'] in ('IMP','DET'):c['design_rejection_not_reproduced']=bool(c['design_layers']) or any(c['relations'][k]['state']=='DIFFERENT' and c['relations'][k]['class']!=c['class'] for k in ('DLY8','CPS8','KCX'))
                else:c['design_rejection_not_reproduced']=False
                rel=c['relations']['CPS8']
                if rel['state'] in ('SAME','DIFFERENT'):rel['g0_class']=rel['class'] if rel['state']=='SAME' else ('NULL' if rel['class']!='NULL' else 'IMP')

    def secondary(self, task, t, level, metric):
        if level=='PFMIN' or any(c['class']=='IMP' for c in t['contrasts']): return []
        t['secondary_clause']='DIFFERENT'
        t['secondary_differing_arms']=[c['arm'] for c in t['contrasts']]
        def sentence(k): return F.sentence('A8SEC_DIFF',check=self.W['PLAIN_CHECK_NAMES'][k],names=F.join(self.T['names'][c['arm']] for c in t['contrasts']))
        cache_key=('secondary',task,metric)
        if cache_key not in self.choice_cache: self.choice_cache[cache_key]=max(self.W['PLAIN_CHECK_NAMES'],key=lambda k:self.measure([sentence(k)])[metric])
        t['secondary_check']=self.choice_cache[cache_key]
        return [sentence(t['secondary_check'])]

    def task_profiles(self, task, level):
        original = self.base['tasks'][task]; profiles = {}; caches = {}; clocks = self.clocks(task, level == 'PFMIN')
        def retain(t, metric):
            secondary = self.secondary(task, t, level, metric)
            if level == 'PFMIN':
                r = deepcopy(self.base); r['tasks'][task] = t
                text = F.pfmin_render(r)['tasks'][task]

                value = F.words(text) if metric == 'words' else len(text) if metric == 'characters' else max(map(F.words,F.pfmin_render(r)['sentences']))
                key = (any(c['class'] == 'IMP' for c in t['contrasts']), t['alert'], t['signal_failed'],
                       tuple(c['class'] != 'NE' and F.seven_undefined(c) for c in t['contrasts']) if t['complete'] else tuple(False for _ in t['contrasts']),
                       any(c['class'] in ('IMP', 'DET') for c in t['contrasts']) if t['complete'] else False,
                       any(c['class'] in ('IMP', 'DET') and (any(x!='PASS' for x in c['checks'].values()) or F.seven_undefined(c)) for c in t['contrasts']) if t['complete'] else False)
            else:
                value = self.value(F.task_sentences(task, t, self.T, level=level), metric)
                key = (any(c['class'] == 'IMP' for c in t['contrasts']), t['alert'], t['signal_failed'])
            if level != 'PFMIN':
                ss=F.task_sentences(task,t,self.T,level=level)+secondary
                value=self.value(ss,metric)
            index = (key, metric)
            if index not in profiles or value > profiles[index][0]: profiles[index] = (value, deepcopy(t))

        for alert in (False, True):
            cores=[self.cores(task,c,level,alert) for c in original['contrasts']]
            print('  cores '+task+'/'+level+'/'+str(alert)+' complete',flush=True)
            for metric in METRICS:
                for clk in clocks:
                    for cidx, core in enumerate(cores):
                        for group in GROUPS:
                            c = deepcopy(core[(*group, metric)][1])
                            if level == 'PFMIN':
                                if alert and c['class'] in ('IMP','DET'): c['checks']['one_day']='FAIL'
                                if c['class'] in ('IMP', 'DET'):
                                    c['design_layers'] = [k for k in self.W['PLAIN_LAYER'] if k not in ('windowed_activity','kcx','dly8_15','cps8')]; c['design_rejection_not_reproduced'] = True
                                    for layer in ('R8','DLY8','CPS8'):
                                        c['relations'][layer].update(state='DIFFERENT', **{'class': 'IMP' if c['class'] != 'IMP' else 'NULL'})
                                        if layer == 'R8': c['relations'][layer].update(fully_checked=False, seeds_run='single')
                                if task == 'news': c['relations']['DLY8'].update(state='NOT_APPLICABLE', **{'class': None})
                                elif clk['state'] == 'INFORMATIVE' and F.decimal(clk['public_by_admission']) < 99 and c['class'] != 'NE':
                                    c['relations']['DLY8'].update(state='DIFFERENT', **{'class': 'IMP' if c['class'] != 'IMP' else 'NULL'})
                            else: c = self.relations(task, c, clk, level, metric, alert)
                            caches[(alert, metric, repr(clk), cidx, group)] = c
                    for groups in itertools.product(GROUPS, repeat=len(cores)):
                        t = deepcopy(original); t.update(alert=alert, clk8=clk, complete=True, bound='100.000', mn_effect='-100.00000')
                        t['contrasts'] = [deepcopy(caches[(alert, metric, repr(clk), i, group)]) for i, group in enumerate(groups)]

                        cache_key=('activity',task,metric)
                        if cache_key not in self.choice_cache: self.choice_cache[cache_key]=max(F.CLASSES,key=lambda k:self.helper_value([F.sentence('A8MN',activity_words=self.W['PLAIN_ACTIVITY'][task],mn=t['mn_effect'],cls=self.W['PLAIN_C3'][k])],metric))
                        t['mn_class']=self.choice_cache[cache_key]
                        for signal in (False, True):
                            t['signal_failed'] = signal


                            retain(t, metric)
                    for reason in self.W['PLAIN_INC_REASON']:
                        t = deepcopy(original); t.update(complete=False, reason=reason, alert=alert, clk8=clk)


                        for cls in ('NE',):
                            for c in t['contrasts']:
                                self.widen_incomplete(c, cls)
                            for signal in (False, True):
                                t['signal_failed'] = signal; retain(t, metric)
        return profiles

    def widen_incomplete(self, c, cls):
        c.update(self.widest(c, 'NE', True, ('UNAVAILABLE',)*6, 'NE', False, 'fail'))

    def global_profiles(self, level):
        profiles = []
        for title, variant, embargo in itertools.product(('a8', 'a8b'), ('private',), (False, True)):
            for cls in F.CLASSES:
                for sign in ((-1,) if cls=='IMP' else (1,) if cls=='DET' else (-1,1) if cls=='NULL' else (0,)):
                    for reason in self.W['PLAIN_INC_REASON'] if cls == 'NE' else ('fail',):
                        r = deepcopy(self.base); r['author_confirmation']['choices']['title_variant'] = title
                        if variant != 'private': r['author_confirmation']['choices']['public_registration'] = 'a_deposit_before_T5'
                        if variant == 'public': r['author_prescore']['registration'] = {'registration_repository': 'OSF', 'registration_identifier': 'SYNTHETIC', 'registration_embargo': embargo}
                        r['lear'] = {'class': cls, 'effect': None if cls == 'NE' else ('-' if sign < 0 else '')+'100.000', 'reason': reason}

                        v = F.plain_render(r, level=level)
                        global_ss = v['sentences'][:4] if level == 'PFMIN' else []


                        if level == 'PFMIN': ss = global_ss
                        else:
                            ss = [p for x in [F.form('A8DS'), *F.registration_sentences(r), F.sentence('A8CUT_S')] for p in re.split(r'(?<=[.!?])\s+(?=[A-Z])', x)]
                            lear = r['lear']
                            ss += [F.sentence('A8LEAR_NE', reason=self.W['PLAIN_INC_REASON'][reason]) if cls == 'NE' else F.sentence('A8LEAR', abs='100.000', lower_higher='lower' if sign < 0 else 'higher', cls=self.W['PLAIN_LEAR_CLASS'][cls])]
                        val = self.measure(ss); profiles.append((val, r))
        return {metric: max(profiles, key=lambda x: x[0][metric])[1] for metric in METRICS}

    def combine(self, level, task_profiles):
        globals_ = self.global_profiles(level); maxima = {}; witnesses = {}
        for metric in METRICS:
            news = [v[1] for (key, m), v in task_profiles['news'].items() if m == metric]
            notices = [v[1] for (key, m), v in task_profiles['notice'].items() if m == metric]
            for nt, mt in itertools.product(news, notices):
                r = deepcopy(globals_[metric]); r['tasks'] = {'news': deepcopy(nt), 'notice': deepcopy(mt)}
                self.authorize(r)


                for task, t in r['tasks'].items():
                    t['secondary_clause'] = 'DIFFERENT'
                    t['secondary_differing_arms']=[c['arm'] for c in t['contrasts']]
                    t['secondary_check'] = max(self.W['PLAIN_CHECK_NAMES'], key=lambda k: self.helper_value([F.sentence('A8SEC_DIFF', check=self.W['PLAIN_CHECK_NAMES'][k], names=F.join(self.T['names'][c['arm']] for c in t['contrasts']))], metric))
                allowed_pc = ('RESULT',) if any(t['alert'] or t['signal_failed'] for t in r['tasks'].values()) else ('RESULT', 'PENDING', 'SPEED_PENDING', 'NOT_RUN_REPIN')
                for pc in allowed_pc:
                    r['pc_state'] = pc
                    self.authorize(r)
                    states = ('UNCHANGED', 'DIFFERENT', 'NOT_RUN') if level == 'PFMIN' else ('DIFFERENT',)
                    for secondary in states:
                        for t in r['tasks'].values(): t['secondary_clause'] = secondary
                        v = F.plain_render(r, level=level); self.measure(v['sentences'])
                        score=v['sentence_max' if metric=='sentence' else metric]
                        if metric not in maxima or score > maxima[metric]: maxima[metric] = score; witnesses[metric] = deepcopy(r)
        for metric, r in witnesses.items():
            F.validate_record(r); v = F.plain_render(r, level=level)
            F.require(v['sentence_max' if metric=='sentence' else metric] == maxima[metric], 'full witness does not attain factored maximum')
        return {**maxima, 'witnesses': witnesses,
                'texts': {m: F.plain_render(r, level=level)['text'] for m, r in witnesses.items()},
                'task_signatures': {k: len(v) for k, v in task_profiles.items()},
                'method': 'exact factor enumeration with attainable production witnesses'}

    def design_subsets(self):

        layers = [k for k in self.W['PLAIN_LAYER'] if k not in ('windowed_activity','kcx','dly8_15','cps8')]; count = 0
        for task, t0 in self.base['tasks'].items():
            for c0 in t0['contrasts']:
                for cls in ('IMP','DET'):
                    c = deepcopy(c0); c['class'] = cls
                    t = {'contrasts':[c], 'clk8': t0['clk8']}
                    c['design_layers'] = layers
                    c['relations']['CPS8'].update(state='DIFFERENT',**{'class':'NULL'})
                    full = self.measure(F.relation_sentences(task,t,self.T,'PF'))
                    for mask in itertools.product((False,True),repeat=len(layers)):
                        c['design_layers'] = [k for k,b in zip(layers,mask) if b]
                        for cps in ('NOT_RUN','DIFFERENT'):
                            c['relations']['CPS8']['state'] = cps
                            value = self.measure(F.relation_sentences(task,t,self.T,'PF')); count += 1
                            F.require(all(value[m] <= full[m] for m in METRICS), 'design union does not dominate subset')
        return count

    def inert_inputs(self):

        count=0
        for level in F.LEVELS:
            expected=F.plain_render(self.base,level=level)['text']
            for bits,title,pcx in itertools.product(itertools.product((False,True),repeat=5),('a8','a8b'),F.CATEGORIES):
                r=deepcopy(self.base);r['optional']=dict(zip(r['optional'],bits))
                r['author_confirmation']['choices']['title_variant']=title
                row=next(x for x in r['stages'] if x['stage']=='matched_controls')
                row.update(counted_category=pcx,postseal=pcx,reason='A8NR_AUTHOR' if pcx==F.CATEGORIES[2] else 'A8DEV_PC' if pcx==F.CATEGORIES[3] else None)
                v=F.plain_render(r,level=level);self.measure(v['sentences']);count+=1
                F.require(v['text']==expected,'supposedly inert field changes abstract')
        for level in F.LEVELS:
            r=deepcopy(self.base);r['pc_state']='NOT_RUN_REPIN'
            F.require(F.plain_render(r,level=level)['text']==F.plain_render(self.base,level=level)['text'], 're-pin missing branch changes abstract beyond pending equivalence')
            count+=1
        return count

    def audit_domain(self, plan):

        refusals=[]
        for kind in ('public','fallback','KCX','three'):
            r=deepcopy(self.base)
            if kind in ('public','fallback'):
                r['author_confirmation']['choices']['public_registration']='a_deposit_before_T5'
                if kind=='public': r['author_prescore']['registration']=dict(registration_repository='OSF',registration_identifier='SYNTHETIC',registration_embargo=False)
            elif kind=='KCX': r['author_confirmation']['choices']['kcx']='run_if_key_before_T5'
            else: r['author_confirmation']['choices']['r8_seeds']='three'
            try: F.validate_record(r)
            except F.FillError as exc: refusals.append(dict(branch=kind,refused=True,error=str(exc)))
            else: raise F.FillError('forbidden author branch accepted: '+kind)


        relations=0; delays=0; incomplete=0; registration=0; seed_presence=0
        for level in F.LEVELS:
            for task,t0 in self.base['tasks'].items():
                for c0 in t0['contrasts']:
                    for cls in F.CLASSES:
                        for layer in F.LAYERS:
                            states=('NOT_RUN',) if layer=='KCX' else ('NOT_APPLICABLE',) if task=='news' and layer=='DLY8' else F.REL_STATES
                            for state in states:
                                values=(cls,) if state=='SAME' else tuple(k for k in F.CLASSES if k!=cls) if state=='DIFFERENT' else (None,)
                                for alternative in values:
                                    c=deepcopy(c0);c['class']=cls;c['relations'][layer].update(state=state,**{'class':alternative},reason='A8NR_AUTHOR' if layer=='KCX' else 'A8NR_PARITY')
                                    t=dict(contrasts=[c],clk8=t0['clk8'],alert=False)
                                    self.measure(F.relation_sentences(task,t,self.T,level));relations+=1
                        for estimate in (None,'-100.00000','+100.00000'):
                            c=deepcopy(c0);c.update(self.widest(c,cls,False,('FAIL',)*6,'NULL',estimate is not None,'fail'))
                            self.measure([F.pfmin_item(c,dict(alert=False))] if level=='PFMIN' else F.member_sentences(c,self.T,level,False));seed_presence+=1
                        if task=='notice':
                            clk=dict(state='INFORMATIVE',public_by_admission='0.000',maximum_delay_minutes='99999',covered_n=99999,listed_by_admission_n=0,delay60_class='NE')
                            for a,b,z in itertools.product((*F.CLASSES,None),repeat=3):
                                c=deepcopy(c0);c.update(**{'class':cls},delay_classes={'5':z,'15':a,'60':b})
                                self.measure(F.relation_sentences(task,dict(contrasts=[c],clk8=clk,alert=False),self.T,level));delays+=1
                    for reason in self.W['PLAIN_INC_REASON']:
                        t=deepcopy(t0);t.update(complete=False,reason=reason)
                        for c in t['contrasts']: self.widen_incomplete(c,'NE')
                        r=deepcopy(self.base);r['tasks'][task]=t
                        self.measure(F.plain_render(r,level=level)['sentences']);incomplete+=1

            for title,embargo in itertools.product(('a8','a8b'),(False,True)):
                r=deepcopy(self.base);r['author_confirmation']['choices']['title_variant']=title
                F.require(F.plain_render(r,level=level)['text']==F.plain_render(self.base,level=level)['text'],'title affects abstract')
                r['author_prescore']['registration']['registration_embargo']=embargo
                try:F.validate_record(r)
                except F.FillError: registration+=1
                else:raise F.FillError('private non-null embargo accepted')

        changes=plan['record']['changes'];resource=changes['forms.A8NR_RESOURCE_A8AM2']
        original=self.T['forms']['A8CONTRIB1']
        F.require(original.replace(' (and, secondarily, richer source metadata)','')==changes['forms.A8CONTRIB1_when_B4_not_admitted'],'specification contribution derivation')
        F.require(F.words(resource)<=12 and 'B2' in changes['admission_rule'] and 'R8S is not run (author default single seed)' in changes['admission_rule'],'specification admission/form identity')
        reason_values=[v for k,v in self.T['forms'].items() if k.startswith('A8NR_') and '{' not in v and F.words(v)<=12]
        F.require(F.words(resource)<=max(map(F.words,reason_values)) and len(resource)<=max(map(len,reason_values)),'resource reason not dominated by enumerated reasons')
        from table_renderer import constraint_contract as C
        resource_renders=0
        with patch.object(C,'specification2',return_value=plan):
            F.require(F.form('A8NR_RESOURCE_A8AM2')==resource,'specification resource form production replay')
            for admitted in (False,True):
                r=deepcopy(self.base);r['optional']['R8']=True
                t=r['tasks']['news'];t['bound']=None
                row=next(x for x in r['stages'] if x['stage']=='A8B-R8')
                row.update(counted_category=F.CATEGORIES[0] if admitted else F.CATEGORIES[2],postseal=F.CATEGORIES[0] if admitted else F.CATEGORIES[2],reason=None if admitted else 'A8NR_RESOURCE_A8AM2')
                for c in t['contrasts']:
                    c.update(self.widest(c,'IMP',False,('PASS',)*6,'IMP',True,'fail'))
                    c['relations']['R8'].update(state='SAME' if admitted else 'NOT_RUN',**{'class':'IMP' if admitted else None},reason=None if admitted else 'A8NR_RESOURCE_A8AM2')
                F.validate_record(r)
                for level in F.LEVELS:
                    self.measure(F.plain_render(r,level=level)['sentences']);resource_renders+=1
        return dict(refusals=refusals,relation_option_renders=relations,delay_triple_renders=delays,incomplete_renders=incomplete,refused_private_embargo=registration,seed_presence_renders=seed_presence,R12b_admission=[False,True],R12b_production_form_renders=resource_renders,specification2_source_verified=True)

    def run(self):
        levels = {}
        design_count = self.design_subsets(); inert_count=self.inert_inputs()
        overall_sentence = (self.sentence_max,self.sentence_witness)
        for level in F.LEVELS:
            print('exhaustive level '+level, flush=True)
            self.active_level=level
            self.sentence_max = 0; self.sentence_witness = ''
            profiles = {task: self.task_profiles(task, level) for task in F.ARMS}
            levels[level] = self.combine(level, profiles)
            F.require(self.sentence_max == levels[level]['sentence'], 'unattained longest sentence: '+level)
            levels[level]['sentence_max'] = levels[level].pop('sentence')
            levels[level]['sentence_witness'] = max(F.plain_render(levels[level]['witnesses']['sentence'],level=level)['sentences'],key=F.words)
            print('  attained maxima '+level+' '+str({k:levels[level][k] for k in ('words','characters','sentence_max')}),flush=True)
            overall_sentence = max(overall_sentence, (self.sentence_max,self.sentence_witness),key=lambda x:x[0])
        self.sentence_max,self.sentence_witness = overall_sentence
        self.gate(); floor = levels['PFMIN']
        good = floor['words'] <= 249 and floor['characters'] <= 1912 and self.sentence_max <= 35
        selections = {}
        for level, result in levels.items():
            for metric, r in result['witnesses'].items():
                selected = F.render(r); self.measure(selected['sentences'])
                F.require(selected['words'] <= 250 and selected['characters'] <= 1920, 'abstract selection outside bounds')
                choices=[F.plain_render(r,level=k) for k in F.LEVELS]
                expected=next(v for v in choices if v['words']<=250 and v['characters']<=1920)
                F.require(selected['level']==expected['level'] and selected['text']==expected['text'],'not first qualifying level')
                selections[level+'/'+metric] = {k: selected[k] for k in ('level', 'words', 'characters', 'sentence_max')}
        return {'schema': 'TABLE_RESULTS_EXHAUSTIVE_PROOF_V3', 'state': 'PASS' if good else 'FAIL',
                'levels': levels, 'worst_case': floor['words'], 'character_max': floor['characters'],
                'sentence_max': self.sentence_max, 'sentence_witness': self.sentence_witness,
                'witness': floor['witnesses']['words'], 'character_witness': floor['witnesses']['characters'],
                'text': floor['texts']['words'], 'signatures_evaluated': self.n,
                'domains': {'primary_classes': 4, 'check_vectors': 3**6, 'three_seed_classes': 4,
                            'seven_day_states': 2, 'relation_states_per_layer': len(F.REL_STATES), 'R8_seed_check_modes': 1,
                            'design_layer_subsets': 2**len([k for k in self.W['PLAIN_LAYER'] if k not in ('windowed_activity','kcx','dly8_15','cps8')]), 'delay_pairs': 25,
                            'design_subset_renders': design_count, 'relation_factor_enumerations':self.relation_domains,
                            'optional_title_PCX_invariance_renders':inert_count,
                            'joint_class_seven_patterns': {k: len(GROUPS)**len(v) for k, v in F.ARMS.items()},
                            'author_title_variants': 2, 'registration_variants_including_fallback': 1,
                            'embargo_states': 2, 'PC_states': 4, 'optional_presence_patterns': 2**5,
                            'inert_fields': 'matched_controls/batch_scoring/ISOBATCH presence, squared loss, cheap text, relation alternative classes, +5 delay and title have no abstract text dependence',
                            'core_enumerations': self.domain},
                'selection_checks': selections, 'minimum_free_memory_percent': self.minimum_free,
                'actual_nice': os.getpriority(os.PRIO_PROCESS, 0),
                'authority_sha256': F.A8_BINDINGS,
                'renderer_sha256': F.sha256(F.CODE_ROOT/'table_results_conf_results.py'),
                'templates_sha256': F.sha256(F.MS/'table_results_templates.json'),
                'proof_code_sha256': F.sha256(Path(__file__)),
                'proof_spec_sha256': F.sha256(Path(__file__).with_name('PROOF_RECEIPT_SPEC.md')),
                'scope': 'frozen numeral envelope; exact compositional categorical maxima; no data, outcomes, PDF builds or case suites'}

