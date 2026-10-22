'Check table-width constraints over numerical formatting cases.'
from itertools import product
from copy import deepcopy
import table_results_conf_results as F

def proof():
    T=F.templates();W=T['words'];count=0;levels={};best={};texts={}
    def metric(s):return F.words(s),len(s)
    def retain(d,key,text):
        for j in (0,1):
            k=(key,j)
            if k not in d or metric(text)[j]>metric(d[k])[j]:d[k]=text
    for task in F.ARMS:
        taskbest={}
        for alert in (False,True):
            variations=[]
            for arm,ref in F.ARMS[task]:
                local={}
                for cls in F.CLASSES:
                    for seed in (F.CLASSES if cls in ('IMP','DET') else (cls,)):
                        for check,seven in product(('PASS','FAIL','UNAVAILABLE'),(False,True)):
                            if cls=='NE' and seven:continue
                            c={'arm':arm,'class':cls,'effect_percent':'-100.00000','three_seed_class':seed,'checks':dict.fromkeys(F.CHECKS,check),'family_seven_day':None if seven else ['-1','1'],'per_contrast_seven_day':None if seven else ['-1','1']}
                            text=F.pfmin_item(c,{'alert':alert});count+=1
                            flag=(cls=='IMP',cls in ('IMP','DET') and (check!='PASS' or seven),seven and cls!='NE',cls in ('IMP','DET'))
                            retain(local,flag,text)
                variations.append(local)
            for combination in product(*(list(v.items()) for v in variations)):
                flags=[k[0] for k,s in combination]
                imp=any(x[0] for x in flags);nr=any(x[1] for x in flags);seven=[W['PFMIN_NAMES'][arm] for (arm,ref),x in zip(F.ARMS[task],flags) if x[2]];rej=any(x[3] for x in flags)
                s=F.sentence('PFMIN_TASK',head=W['PFMIN_HEAD'][task],items='; '.join(s for k,s in combination))


                if not imp:s+=' '+F.sentence('PFMIN_BOUND_NC' if alert else 'PFMIN_BOUND',head=W['PFMIN_HEAD'][task],X='100.000',seven=F.form('PFMIN_SEVEN') if seven else '',sens=F.form('PFMIN_SENS'))
                else:s+=' '+F.sentence('PFMIN_NULL_SENS',head=W['PFMIN_HEAD'][task])
                retain(taskbest,(imp,nr,tuple(seven),rej,alert),s);count+=1
            for reason in list(W['PFMIN_INC_REASON'].values())+list(F.specification_words().values()):

                if reason==F.specification_words().get('PFMIN_C3.NE'):continue
                retain(taskbest,(False,False,(),False,alert),F.sentence('PFMIN_INC',head=W['PFMIN_HEAD'][task],reason=reason))
        best[task]=taskbest
    fixed=[F.sentence('PFMIN_DS'),F.sentence('PFMIN_EV_PRIVATE'),F.sentence('PFMIN_CUT')]
    learn=[F.sentence('PFMIN_LEAR',abs='100.000',lower_higher=x,cls=W['PFMIN_CLASS_LEAR'][c]) for x,c in product(('lower','higher'),('IMP','NULL','DET'))]+[F.sentence('PFMIN_LEAR_NE')]
    clocks=[v.format(X='100.000',Y='100.000',Z='99999') for v in W['PFMIN_CLK'].values()]
    for j in (0,1):
        lead=max(learn,key=lambda s:metric(s)[j]);clock=max(clocks,key=lambda s:metric(s)[j]);sec=max((F.sentence('PFMIN_SEC_'+x) for x in ('SAME','DIFF','NA')),key=lambda s:metric(s)[j])
        for (nk,ns),(dk,ds) in product(best['news'].items(),best['notice'].items()):
            if nk[1]!=j or dk[1]!=j:continue
            n,d=nk[0],dk[0];parts=fixed+[lead,ns,clock,ds];seven=list(n[2])+list(d[2]);rejection=n[3] or d[3]
            if seven:parts.append(F.sentence('PFMIN_SEVEN_S',names=F.join(seven)))
            if n[1] or d[1]:parts.append(F.sentence('PFMIN_NOTROBUST'))
            if rejection:parts.append(max((F.sentence('PFMIN_NOTREP_KEY',key=F.join(W['PFMIN_KEY_LAYERS'].values())),F.sentence('PFMIN_NOTREP')),key=lambda s:metric(s)[j]))
            alert=[task for task,x in zip(F.ARMS,(n,d)) if x[4]]
            parts.append(F.sentence('PFMIN_ALERT',tasks=W['PFMIN_ALERT_TASKS']['both' if len(alert)==2 else alert[0]]) if alert else F.sentence('PFMIN_PCNR'))
            if n[0] or d[0]:parts.append(F.sentence('PFMIN_ATTR'))
            parts.append(sec);text=' '.join(parts);count+=1
            score=metric(text)[j]
            if score>levels.get(j,0):levels[j]=score;texts[j]=text
    result={'state':'PASS' if levels[0]<=249 and levels[1]<=1912 else 'FAIL','words':levels[0],'characters':levels[1],'evaluated':count,'word_envelope':texts[0],'character_envelope':texts[1],'scope':'PFMIN dominance envelope; unreachable public registration is not promoted; sentence widths checked in source suite','renderer_sha256':F.sha256(F.CODE_ROOT/'table_results_conf_results.py')}
    return result
