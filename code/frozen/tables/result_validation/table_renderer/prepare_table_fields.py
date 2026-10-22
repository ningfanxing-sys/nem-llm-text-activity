
'Write the table fields from the specified input records.'
import csv
import difflib
import hashlib
import io
import json
from pathlib import Path
import re
import sys
sys.dont_write_bytecode=True
MS=Path(__file__).resolve().parents[3]
sys.path.append(str(MS))
from check_arxiv import collect_sources
from table_results_conf_results import templates, fixed_facts_for_tests, form, tex, timestamp_checks, author_title, require


CONTEXT_RENAMES=(
 ('This is retrospective confirmation','This is a retrospective evaluation'),
 ('confirmation of the earlier operator-forecast increment','evaluation of the earlier operator-forecast increment'),
 ('confirmation of that comparison','evaluation of that comparison'),
 ('and its confirmation','and its evaluation'),
 ('author-confirmation','author-approval'),('author confirmation','author approval'),
 ('pre-confirmation windows','earlier windows'),('pre-confirmation','pre-window'),('confirmation-period review','window-D extraction review'),
 ('confirmation review','window-D extraction review'),('confirmation-period','window-D'),
 ('confirmation-window','window-D'),('confirmation window','evaluation window D'),
 ('historical confirmation windows','historical evaluation windows'),('retrospective confirmation windows','retrospective evaluation windows'),
 ('retrospective confirmation families','retrospective evaluation families'),
 ('retrospective confirmation','retrospective evaluation'),('Joint confirmation','The joint reading'),
 ('joint confirmation','the joint reading'),('news confirmation','news evaluation'),
 ('notice confirmation','notice evaluation'),('a confirmation','an evaluation window D'),
 ('window-C','January-February 2026'),('window C','the January-February 2026 window'),
 ('beyond text activity','over article and notice counts'))


def named(text,trace=None,file='',source=True):
    protected=r'(\\(?:input|include|label|ref|eqref|pageref|cite\w*)(?:\[[^]]*\])?\{[^}]+\}|(?<!\\)%[^\n]*)'
    if not source:protected=r'(\\(?:input|include|label|ref|eqref|pageref|cite\w*)(?:\[[^]]*\])?\{[^}]+\})'
    chunks=re.split(protected,text);offset=0
    for i,chunk in enumerate(chunks):
        if i%2:offset+=len(chunk);continue
        original=chunk
        for old,new in CONTEXT_RENAMES:
            def rep(m):
                value=new
                if m.group()[0].isupper():value=value[0].upper()+value[1:]
                return value
            chunk=re.sub(r'(?<![A-Za-z_])'+re.escape(old)+r'(?![A-Za-z_])',rep,chunk,flags=re.I)
        chunk=re.sub(r'\bconfirmations\b','evaluations',chunk,flags=re.I)
        chunk=re.sub(r'\bconfirmation\b',lambda m: 'Evaluation window D' if m.group()[0].isupper() else 'evaluation window D',chunk,flags=re.I)
        chunk=chunk.replace('The the January','The January').replace('the the January','the January')
        if trace is not None and chunk!=original:trace.append([file,text[:offset].count('\n')+1,original,chunk])
        chunks[i]=chunk;offset+=len(original)
    return ''.join(chunks)


def cited(text):

    names={'Giacomini and White':'Giacomini2006','Harvey et al.':'Harvey1997','Liu et al.':'Liu2024a','Zhou et al.':'Zhou2026',
           'Chordia et al.':'Chordia2005','Cerqueira et al.':'Cerqueira2020','Clark and West':'Clark2007','Andrews and Buchinsky':'Andrews2000'}
    rendered=tex(text)
    keys=[key for name,key in names.items() if name in text]
    return rendered+((' '+r'\cite{'+','.join(dict.fromkeys(keys))+'}') if keys else '')


def estimand():

    return form('A8EST',cw='')


def declarations_stage(text,T):

    names=['credit','competing_interest','data_availability','accountability','funding'];i=iter(names)
    text=re.sub(r'\\textcolor\{red\}\{\[AUTHOR TO COMPLETE:.*?\]\}',lambda _:r'\Dres{global}{declaration_'+next(i)+'}{reading}',text)
    text=re.sub(r'% PENDING: author[^\n]*',lambda _:'\\input{TABLE_RESULTS_author_a3_a6}',text)
    marker=T['frozen_templates']['auth_slot_marker_a8']
    text=text.replace('\\section*{Extraction methods}','\\section*{Extraction methods}'+'\n'+marker+'\n'+'\\input{TABLE_RESULTS_fixed}')
    return text


def complete_hosts(after,T):
    replacements={
      'outcomes remain pending under frozen comparison families.':'readings are reported under frozen comparison families.',
      'for the pending evaluation window D':'for evaluation window D',
      'All effects, intervals, decisions, clipping counts and event summaries remain pending.':'Effects, intervals, decisions, clipping counts and event summaries are reported in the result tables.',
      'All evaluation window D outcomes and interpretations remain pending.':'The evaluation readings follow the frozen comparison families.',
      'The final adapted LEAR benchmark is separately pre-specified and remains pending with evaluation window D.':r'The final adapted LEAR benchmark was separately pre-specified; its reading is reported in Section~\ref{sec:ms12-confirmation}.',
      'The pending result could support an increment over the activity reference, a deterioration, or no reliable increment with its sample-specific bound. None is assumed in the present discussion.':'The recorded reading and its qualifications determine the interpretation.',
      'The new reviews require separate scored receipts.':'The review readings use separate scored receipts.',
      'News, isolated-notice and window-D semantic results and the second-annotator agreement require their own scored and attested slots.':'The scored window-D review and agreement are reported below; the historical reviews follow the eighth-addendum timing rule.',
      'whose results remain pending':'whose readings are reported here',
      'The evaluation window D reading remains pending.':r'The evaluation reading is reported in Section~\ref{sec:ms12-confirmation} of the main article.',
      'The current version has no evaluation window D results.':'The evaluation results and their provenance are reported separately from that historical release.',
      'Seven pre-score addenda':'Eight pre-score addenda','seven pre-score addenda':'eight pre-score addenda',
      'No window-D outcomes were accessed.':'The completed evaluation is reported under its frozen rules.',
      'Full detection rates, null rates, intervals and sensitivity readings are reserved for the complete evaluation window D tables.':r'Full detection rates, null rates, intervals and sensitivity readings are reported in the diagnostic tables.',
      'Public repository deposit and the DOI are to be completed by the author at submission.':r'\Dres{global}{declaration_data_availability}{reading}',
      'its public repository DOI is to be supplied by the author at submission.':r'its data availability statement is supplied in the main article.',
    }
    for rel,text in list(after.items()):
        if rel=='audit_archive.tex' or rel.startswith('audit_archive_sections/'):continue
        for old,new in replacements.items():text=text.replace(old,new)
        text=text.replace('None isolates','No comparison isolates').replace('None changes','These addenda do not change').replace('& None &','& Not applicable &')
        text=text.replace('& pending &',r'& \Dres{global}{overview}{reading} &').replace('are filled after scoring','are reported in the completed evaluation')
        text=text.replace('Their outcomes remain pending', 'Their readings are reported').replace('for the pending '+tex(form('A8NAME_FIRST')), 'for the '+tex(form('A8NAME_FIRST')))
        if rel=='authors.tex':
            names=iter(('front_authors','front_affiliations','front_correspondence'))
            text=re.sub(r'\\textcolor\{red\}\{\[AUTHOR TO COMPLETE:.*?\]\}',lambda _:r'\Dres{global}{declaration_'+next(names)+'}{reading}',text)

        text=re.sub(r'% PENDING:[^\n]*',lambda m:m.group() if m.group()==T['frozen_templates']['auth_slot_marker_a8'] else '',text)
        after[rel]=text
    after['sections/MS12_human.tex']+='\n'+'\\input{TABLE_RESULTS_human}'+'\n'
    after['supplement_sections/MS17_confirmation_review.tex']+='\n'+'\\input{TABLE_RESULTS_human_tables}'+'\n'
    after['sections/MS12_notice_results.tex']+='\n'+'\\input{TABLE_RESULTS_section_readings}'+'\n'
    after['sections/MS12_methods.tex']+='\nA different decision class under a sensitivity is not a test of a difference between the two increments.\n'
    after['sections/MS12_news_results.tex']+='\n'+'\\input{TABLE_RESULTS_combinations}'+'\n'
    rel='supplement_sections/S7_protocol_records.tex'
    text=after[rel]
    text=re.sub(r'\\begin\{table\}.*?\\end\{table\}',lambda _:'\\input{TABLE_RESULTS_timestamp_table}',text,count=1,flags=re.S)
    text=re.sub(r'Timestamps T4 and T5 are planned.*?(?=\n|$)','The actual timestamp records are listed in the table above.',text)
    after[rel]=text

    for rel in ('supplement_sections/S5_news.tex','supplement_sections/S6_contracts.tex'):
        after[rel]=after[rel].replace('has not been scored.', 'follows the eighth-addendum human-review timing rule.')
        after[rel]+='\n'+r'\Dres{global}{hrc_historical}{reading}'+'\n'

    rel='supplement_sections/MS13B_template_adherence.tex'
    after[rel]=after[rel].replace('run available by 00:00','price-history hour with interval ends 23:00 through 23:55, admitted only if all twelve intervals are legal and available by the 00:00 issue; the interval ending at 00:00 is excluded')


def archive_markings(after,reference_snapshot):
    marker='\\textit{Inactive by the eighth addendum; retained as the historical record.}'
    allow={'audit_archive_sections/MS13B_protocol_detail.tex':('Smallest effect size of interest.','Seeds.','Positive control.'),
           'audit_archive_sections/S7_protocol_records.tex':('3.8\\% of the reference MAE for both tasks','decision class or sign','upper bound on sensitivity')}
    for rel,phrases in allow.items():
        lines=after[rel].splitlines(True)
        for i,line in enumerate(lines):
            if any(phrase in line for phrase in phrases):

                lines[i]=line.replace(r' \\', ' '+marker+r' \\') if '&' in line else line.rstrip('\n')+' '+marker+'\n'
        after[rel]=''.join(lines)
    rel='audit_archive_sections/S7_protocol_records.tex'

    after[rel]+='\n'+marker+' Historical notice power of 100\\% is inactive by the eighth-addendum sensitivity reading.\n'
    after['audit_archive.tex']=after['audit_archive.tex'].replace(r'\end{document}','\\input{audit_archive_sections/TABLE_RESULTS_reference_policy}'+'\n'+r'\end{document}')
    after['audit_archive_sections/TABLE_RESULTS_reference_policy.tex']=r'\section{Eighth-addendum reference audit decision}'+'\n'+'Clark and West (2007) and Andrews and Buchinsky (2000) were deliberately excluded from the current bibliographies after the reference audit found that they did not support the frozen clauses as written. The conditional Clark--West clause stays inactive, and the 100,000-draw choice remains a project choice. This record follows source ruling R13 and the reference audit of 4 October 2026; library membership alone does not activate either clause.\n'


def generate(record1=None,return_sources=False,source_root=None,record=None):
    root=Path(source_root) if source_root else MS
    binding=timestamp_checks(frozen=False);T=templates();reference_snapshot={};after={};trace=[]
    catalog=json.loads(Path(__file__).with_name('RENAME_GOLDEN.json').read_text())
    for entry in ('main.tex','supplement.tex','audit_archive.tex'):
        found,deps=collect_sources(root,entry=entry,include_attachments=entry=='main.tex')
        require(not deps,'unresolved stage-4 source dependencies: '+str(deps))
        for path,text in found.items():
            rel=str(path.relative_to(root));reference_snapshot[rel]=text
            if entry=='audit_archive.tex':
                if rel not in after:after[rel]=text
                continue
            lines=text.splitlines(True)
            sites={r['line']:r for r in catalog if r['file']==rel}
            for i,line in enumerate(lines,1):
                row=sites.get(i)
                if row:
                    require(line.rstrip('\n')==row['old'], 'unreviewed rename site drift: '+rel+':'+str(i))
                    lines[i-1]=row['new']+('\n' if line.endswith('\n') else '')
                    trace.append([rel,i,row['old'],row['new']])
                else:require(named(line)==line,'unreviewed rename site: '+rel+':'+str(i))
            after[rel]=''.join(lines)
    for name in ('main.tex','supplement.tex','audit_archive.tex'):
        title='\\input{TABLE_RESULTS_title}' if record1 is None else r'\title{'+tex(author_title(record1))+'}'
        after[name]=re.sub(r'\\title\{[^\n]+\}',lambda _:title,after[name],count=1)
        if name=='audit_archive.tex':continue
        if name=='main.tex':after[name]=after[name].replace(r'\begin{document}',r'\usepackage{xr}'+ '\n'+r'\externaldocument{supplement}'+ '\n'+r'\begin{document}',1)
        if name=='supplement.tex':after[name]=after[name].replace(r'\begin{document}',r'\usepackage{xr}'+'\n'+r'\externaldocument{main}'+'\n'+r'\begin{document}',1)
        after[name]=after[name].replace(r'\begin{document}',r'\usepackage{claims}'+'\n'+'\\input{TABLE_RESULTS_claim_values}'+'\n'+'\\input{TABLE_RESULTS_captions}'+'\n'+r'\begin{document}',1)
    p='sections/MS12_introduction.tex'
    contrib1=form('A8CONTRIB1')
    from table_renderer.constraint_contract import specification2
    deferred=specification2()
    if record is not None:
        b4=next(r for r in record['stages'] if r['stage']=='A8B-R8')
        if b4['reason']=='A8NR_RESOURCE_A8AM2':
            require(deferred is not None,'forecast_replication contribution requires verified specification 2')
            contrib1=deferred['record']['changes']['forms.A8CONTRIB1_when_B4_not_admitted']
    contribution=r'\begin{enumerate}'+'\n'+r'\item '+tex(contrib1)+'\n'+'\\item \\input{TABLE_RESULTS_contribution}'+'\n'+r'\item '+tex(form('A8CONTRIB3'))+'\n'+r'\end{enumerate}'
    after[p]=re.sub(r'\\begin\{enumerate\}.*?\\end\{enumerate\}',lambda _:contribution,after[p],count=1,flags=re.S)
    after[p]=re.sub(r'and reserve claims about increments over (?:text activity|article and notice counts) for the pending evaluation window D\.',lambda _:T['frozen_templates']['intro_final_clause'],after[p])
    after[p]=after[p].replace(form('A8NAME_FIRST'),form('A8NAME_FIRST')+' ('+form('A8NAME_WINDOW')+')',1)
    after[p]+='\n'+tex(form('A8NSTAND'))+'\n'
    p='sections/MS12_data.tex'

    p='sections/MS12_methods.tex'

    after[p]=re.sub(r'A reading is inferentially robust when .*?design dissent\.',lambda _:tex(form('A8M_DEF')),after[p],count=1)
    after[p]=after[p].replace('2,000 one-day draws','100,000 one-day and seven-day draws').replace('2,000 bootstrap draws','100,000 bootstrap draws').replace('0/2000','0/100000').replace('1/2000','1/100000')
    after[p]=re.sub(r'Headline intervals are family-adjusted:.*?per-contrast 95\\% intervals\.', '', after[p])
    after[p]+='\n'+cited(estimand())+'\n\n'+'\n\n'.join(cited(form(k)) for k in ('A8LEVELS','A8B_METHODS','A8D9'))+'\n'
    p='sections/MS12_discussion.tex'
    after[p]=after[p].replace('Knowledge probes showed no elevated later-period recall but leave contamination unresolved.',tex(form('A8PROBE')))
    after['sections/MS12_related.tex']+='\n'+cited(form('A8RELATED'))+'\n'
    after[p]+='\n'+tex(form('A8WAYBACK'))+'\n'+'\\input{TABLE_RESULTS_registration_limit}'+'\n'+r'\Dres{global}{branches}{reading}'+'\n'
    p='sections/MS12_confirmation_design.tex'
    after[p]=re.sub(r'\\section\{[^}]+\}',lambda _:r'\section{Pre-specified retrospective out-of-sample evaluation and results}',after[p],count=1)

    after[p]=re.sub(r'We use ``pre-specified.*?Two further timestamps.*?(?=\n\n)',lambda _:'\\input{TABLE_RESULTS_registration_protocol}'+'\n'+'\\input{TABLE_RESULTS_timestamps}',after[p],flags=re.S)
    after[p]+='\n'+r'\Dres{global}{stages}{reading}'+'\n'
    p='sections/MS12_news_results.tex'
    after[p]=after[p].replace(r'\par\noindent\textit{Primary-family results pending.}','')
    after[p]+='\n'+'\\input{TABLE_RESULTS_primary_intro}'+'\n'+'\\input{TABLE_RESULTS_leads}'+'\n'+'\\input{TABLE_RESULTS_shared}'+'\n'+'\\input{TABLE_RESULTS_detail}'+'\n'+'\\input{TABLE_RESULTS_tables}'+'\n'+'\\input{TABLE_RESULTS_figure}'+'\n'
    p='sections/MS12_notice_results.tex'

    text=after[p]
    marker='An earlier increment above the operator-forecast-augmented reference'
    if marker in text:
        start=text.index(marker);end=text.find('\n',start);end=len(text) if end<0 else end
        para=text[start:end];text=text[:start]+text[end:];pos=text.index(r'\paragraph{Evaluation window D of the earlier operator-forecast increment}') if r'\paragraph{Evaluation window D of the earlier operator-forecast increment}' in text else text.index(r'\paragraph{')
        text=text[:pos]+para+'\n\n'+text[pos:]
    after[p]=text+'\n'+'\\input{TABLE_RESULTS_statuses}'+'\n'+r'\Dres{global}{branches}{reading}'+'\n'+'\\input{TABLE_RESULTS_plant}'+'\n'
    after['sections/abstract.tex']='\\input{TABLE_RESULTS_abstract}'+'\n'
    p='sections/MS12_conclusion.tex'
    text=after[p];text=re.sub(r'If evaluation window D.*?(?=\nEvery|\Z)','',text,flags=re.S)
    text=re.sub(r'Every evaluation window D reading.*?(?=\n|\Z)','',text)
    after[p]=text+'\n'+'\\input{TABLE_RESULTS_conclusion}'+'\n'
    p='supplement_sections/S7_protocol_records.tex'
    after[p]+='\n'+cited(estimand())+'\n'+'\\input{supplement_sections/TABLE_RESULTS_A8_methods}'+'\n'
    after['supplement_sections/TABLE_RESULTS_A8_methods.tex']=r'\subsubsection{Eighth addendum: supporting readings}'+'\n'+r'\paragraph{'+tex(T['frozen_templates']['specified_record_heading'])+'}\n'+'\\input{TABLE_RESULTS_RS8_N0}'+'\n'+'\\input{TABLE_RESULTS_RS8_2000}'+'\n'+'\\input{TABLE_RESULTS_S7}'+'\n'+'\\input{TABLE_RESULTS_support}'+'\n'+r'\Dres{global}{branches}{reading}'+'\n'+'\\input{TABLE_RESULTS_stages}'+'\n'+'\\input{TABLE_RESULTS_LAT8}'+'\n'+'\\input{TABLE_RESULTS_leads}'+'\n'+'\\input{TABLE_RESULTS_deviations}'+'\n'
    after['supplement_sections/TABLE_RESULTS_A8_methods.tex']+='\nThe notice-delay grid adapts the five-to-sixty-minute band and intervals of Chordia et al.~'+r'\cite[p.~271 and Table~2, p.~280]{Chordia2005}'+'. The capacity-matched comparison follows the forecasting-evaluation design of Cerqueira et al.~'+r'\cite[p.~1997]{Cerqueira2020}'+', with the frozen CPS8 grid as a project adaptation.\n'
    p='supplement_sections/S9_execution.tex';after[p]+='\n'+'\\input{TABLE_RESULTS_S9}'+'\n'
    p='declarations.tex';after[p]=declarations_stage(after[p],T)

    after['sections/MS12_methods.tex']+='\nAt the 00:00 AEST news issue, the latest price-history hour uses interval ends from 23:00 through 23:55; the hour is admitted only when all twelve intervals are legal, and 23:55 is admitted only when its availability time is no later than the issue. The interval ending at 00:00 is excluded from this history hour.\n'

    for rel,text in list(after.items()):
        lines=[]
        for line in text.splitlines(True):
            if 'This study' in line and '&' in line:
                parts=line.split('&');parts[1]=' Numerical reference versus text representation (text against no text) ';line='&'.join(parts)
            lines.append(line)
        after[rel]=''.join(lines)
    for rel,text in list(after.items()):
        if rel.startswith('supplement_sections/') and '/archive/' not in rel:
            text=re.sub(r'When the Monte Carlo resolution of 2,000 bootstrap draws.*?says so\.', lambda _:tex(form('A8MC',S_phrase='the comparison value')).lstrip('; ')+'.',text)
            text=re.sub(r'A reading is inferentially robust when .*?design dissent\.',lambda _:tex(form('A8M_DEF')),text)
            after[rel]=text

    for rel in reference_snapshot:
        if rel=='audit_archive.tex' or rel.startswith('audit_archive_sections/'):
            if rel!='audit_archive.tex':after[rel]=reference_snapshot[rel]
    archive_markings(after,reference_snapshot)
    complete_hosts(after,T)

    for rel in ('supplement_sections/MS16_second_addendum.tex','supplement_sections/MS17_third_addendum.tex'):
        after[rel]=after[rel].replace('pp.~10 and 16','pp.~16--17').replace('pp. 10 and 16','pp. 16--17')
    rel='supplement_sections/S7_inference.tex'
    after[rel]=after[rel].replace(r'The 00:00 AEST pre-dispatch run provides demand and generation-availability forecasts~\cite[p.~1433]{Cornell2024}.',r'Cornell et al. compare forecasts with AEMO price pre-dispatch from the midnight run~\cite[p.~1433]{Cornell2024}. The separate pre-dispatch demand and generation-availability inputs are project adaptations.')
    additions=(MS.parent/'paper_plan/reference_audit_20261004/REFS_BIB_FIXES.diff').read_text()
    bib='\n'.join(line[1:] for line in additions.splitlines() if line.startswith('+') and not line.startswith('+++'))

    bib=bib[:bib.index('% REFAUDIT8',bib.index('@article{Cerqueira2020'))] if bib.count('@article{Chordia2005')>1 else bib
    for rel in ('refs.bib','supplement_sections/refs.bib'):
        reference_snapshot[rel]=(root/rel).read_text();after[rel]=reference_snapshot[rel]+bib
    reference_snapshot['audit_archive_sections/refs.bib']=(root/'audit_archive_sections/refs.bib').read_text()
    after['audit_archive_sections/refs.bib']=reference_snapshot['audit_archive_sections/refs.bib']
    golden=Path(__file__).with_name('RENAME_GOLDEN.json')
    require(golden.is_file(), 'rename golden catalog missing')
    for row in json.loads(golden.read_text()):
        require(row['old'] in reference_snapshot[row['file']], 'rename source drift: '+row['file'])
        require(named(row['old'])==row['new'], 'rename grammar golden differs: '+row['file'])

    for rel,text in after.items():
        if text!=reference_snapshot.get(rel,''):
            for op,i,j,k,l in difflib.SequenceMatcher(None,reference_snapshot.get(rel,'').splitlines(),text.splitlines()).get_opcodes():
                if op!='equal':trace.append([rel,i+1,'\n'.join(reference_snapshot.get(rel,'').splitlines()[i:j]),'\n'.join(text.splitlines()[k:l])])
    buf=io.StringIO();w=csv.writer(buf,lineterminator="\n");w.writerow(['file','line','old','new']);w.writerows(trace)
    after['TABLE_RESULTS_PREFILL_TRACE.csv']=buf.getvalue()
    diff=''.join(''.join(difflib.unified_diff(reference_snapshot.get(p,'').splitlines(True),text.splitlines(True),fromfile='a/'+p,tofile='b/'+p)) for p,text in sorted(after.items()) if text!=reference_snapshot.get(p,''))
    receipt={'status':'DRY_RUN_ONLY_NOT_APPLIED','timestamp_checks':T['timestamp_checks'],'inputs_sha256':{p:hashlib.sha256(t.encode()).hexdigest() for p,t in reference_snapshot.items()},'proposed_outputs_sha256':{p:hashlib.sha256(t.encode()).hexdigest() for p,t in after.items() if t!=reference_snapshot.get(p,'')},'trace_rows':len(trace),'CW_included':False,'Andrews_included':False,'R13_policy':'inactive, library membership is evidence only','trace_sources':{'forms':'confirmation/inference_design/RULES_FOR_TABLE_RESULTS.json','facts':'confirmation/inference_design/FIXED_FACTS_A8.json','timestamps':'verified T4/T4A/T4B/T5 records at production fill'}}
    return (diff,receipt,after) if return_sources else (diff,receipt)


if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);a=p.parse_args()
    require(not a.out.exists(),'stage-4 output already exists');diff,receipt,sources=generate(return_sources=True)
    a.out.mkdir(parents=True)
    for name,text in {'PREFILL_STAGE4.diff':diff,'PREFILL_DRY_RUN.json':json.dumps(receipt,indent=2)+'\n','TABLE_RESULTS_PREFILL_TRACE.csv':sources['TABLE_RESULTS_PREFILL_TRACE.csv']}.items():
        with (a.out/name).open('x') as f:f.write(text)
