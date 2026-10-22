
'Compare table sources and rendered PDF assertions.'
from __future__ import annotations
import argparse
import json
from pathlib import Path
import re
import sys
import unicodedata
from functools import lru_cache

A8_BINDINGS = {'A8_FREEZE.json': '80e95c8db2c85ca38490f443612cda30d7ff33124f33ed87b70d8f8317909162', 'ADDENDUM_A8.md': 'efe1770cd04a44131fda63d3d99f36a7bf521da270adae6ccf8bcbdf054a7f8b', 'RULES_FOR_TABLE_RESULTS.json': 'a7490266709a5607f424154635b77bb8fafcc2139d705541612fa7ed7b00b048', 'RULES_FOR_TABLE_RESULTS.md': '6d8dd278227c7053c316af16686a39e707ce283556aa002ff6a65dc2569fe35a', 'FIXED_FACTS_A8.json': 'cebd9113a4c8c67bb225a4b29dfcba613f0543d7492a83c3f1aa2acfb2f84eb8', 'AUTHOR_CONFIRMATION_A8_SCHEMA.json': 'd1d08bff57dab76dd90219223169eda11e2d1c8f3f2ebd60407b08e89d54aa45'}

MACRO=re.compile(r'\\Dres\s*\{([A-Za-z0-9_+/-]+)\}\s*\{([A-Za-z0-9_+/-]+)\}\s*\{([A-Za-z0-9_+/-]+)\}')
NUMBER=re.compile(r'(?<![\w.])[+−-]?\d+(?:[,.]\d+)*(?:\s*(?:\\?%|percent|AUD\s*/\s*MWh))',re.I)
CLASS=re.compile(r'\b(?:reliable|robust|improv\w*|outperform\w*|better|excluded|equivalent|no effect|content-specific|LLM-specific|causal)\b',re.I)
SEVEN='one-day interval only; seven-day interval undefined'

@lru_cache(maxsize=16384)
def normal(text):
    text=unicodedata.normalize('NFKC',text).replace('\u00ad','').replace('−','-').replace('\u2019',"'")
    lexicon=normal_lexicon()
    def line_join(m):
        a,b=m.groups();compound=a+'-'+b;joined=a+b
        return joined if joined.casefold() in lexicon and compound.casefold() not in lexicon else compound
    text=re.sub(r'\b([A-Za-z]+)-\s*\n\s*([A-Za-z]+)\b',line_join,text)
    text=re.sub(r'(\d(?:[–-]\d+)?[–-])\s+(?=minute\b)',r'\1',text)
    return re.sub(r'\s+',' ',text).strip()

@lru_cache(maxsize=1)
def normal_lexicon():
    from table_results_conf_results import templates
    corpus=' '.join(templates()['forms'].values())+' '+' '.join(templates()['frozen_templates'].values())
    return set(re.findall(r'[A-Za-z]+(?:-[A-Za-z]+)*',corpus.casefold()))


def comments(text):
    return re.sub(r'(?<!\\)%[^\n]*','',text)

def macro_calls(text):
    return [tuple(m.groups()) for m in MACRO.finditer(comments(text))]

def strip_fact_sentences(text,facts,document=None):
    bydoc=facts.get('rendered_sentences',{})
    sentences=bydoc.get(document,[]) if document else [s for ss in bydoc.values() for s in ss]
    from table_results_conf_results import tex
    for s in sentences:
        for variant in (s,tex(s)):
            text=text.replace(variant,' '*len(variant))
    return text

def banned_problems(text):
    from table_results_conf_results import templates, fixed_facts_for_tests
    text=re.sub(r'\\(?:label|ref|eqref|pageref|cite\w*)(?:\[[^]]*\])?\{[^}]*\}', ' ',text)
    n=normal(text).casefold()
    extra=[phrase for values in fixed_facts_for_tests()['banned_renderings'].values() if isinstance(values,list) for phrase in values]
    out=['K8 banned phrase: '+b for b in templates()['banned']+extra+inherited_banned() if b!='confirmation' and normal(b).casefold() in n]
    if re.search(r'\bconfirmation\b',n):out.append('K8 banned phrase: confirmation')
    specified=n
    for pattern in templates()['words']['SPECIFIED_ALLOWED']['patterns']:
        specified=re.sub(pattern,' ',specified,flags=re.I)
    if re.search(r'\bregistered\b',specified):out.append('K8.2 unapproved specified wording')
    return out

def stale_problems(text,record,allow_stage_pending=True):
    from table_results_conf_results import templates
    text=comments(text)
    text=re.sub(r'\\(?:input|include|label|ref|eqref|pageref|cite\w*)(?:\[[^]]*\])?\{[^}]*\}', ' ',text)

    for form in templates()['forms'].values():
        if 'pending' in form.casefold() and '{' not in form:text=text.replace(form,' ')
    if allow_stage_pending:
        for optional,label in (('batch_scoring','Batch-context label comparison'),('ISOBATCH','Isolated-label comparison')):
            if not record.get('optional',{}).get(optional):
                status=templates()['absent'][optional]
                if text.strip()==status:return []


                text=text.replace(label+': '+status,label+': REGISTEREDPENDING')
    if allow_stage_pending and any(r['counted_category']=='pending (no result file when filled)' for r in record.get('stages',[])):
        for phrase in ('pending (no result file when filled)',):
            text=text.replace(phrase,' ')
    text=text.replace('Capture-latency diagnostic: pending (no result file when filled); descriptive only.',' ')
    for k,optional in (('A8PEND_A2B','batch_scoring'),('A8PEND_ISO','ISOBATCH')):
        if not record.get('optional',{}).get(optional):text=text.replace(templates()['forms'][k],' ')

    text=text.replace('none ', 'no member ')
    nulls=['K8 stale/unfilled state: None'] if re.search(r'\bNone\b',text) else []
    return nulls+['K8 stale/unfilled state: '+m.group() for m in re.finditer(r'\b(?:pending|planned|nan|will be|will determine|to be supplied|TBD|have not yet been taken)\b|\?\?|PENDING:|AUTHOR TO COMPLETE|has no .{0,50} results|seven pre-score addenda',text,re.I)]


def scope_problems(text,record):
    problems=[]


    from table_results_conf_results import inherited_form
    for k in ('A6ATTR','A4CAP_ALL','A4CAP_LEAR','A4CAP_CHEAP','A4CAP_L1','A4CAP_PD'):
        text=text.replace(inherited_form(k),' ')
    for task in record['tasks']:
        for value in record.get('kept_alert_sentences',{}).get(task,[]):text=text.replace(value,' ')
    alerts=[task for task,t in record['tasks'].items() if t['alert']]
    if alerts:text=text.replace(inherited_form('A6ALERT',tasks=__import__('table_results_conf_results').join({'news':'day-ahead news','notice':'5–30-minute notices'}[task] for task in alerts)),' ')
    for paragraph in re.split(r'\n\s*\n|\\\\\s*\n',text):
        if re.search(r'\b(?:each|every|all)\s+(?!evaluable\b)(?:[A-Za-z-]+\s+){0,5}(?:representations?|members?|arms?|readings?)\b',paragraph,re.I):
            for task,t in record['tasks'].items():
                if any(c['class']=='NE' for c in t['contrasts']) and re.search(r'\b'+task+r'\b|'+ ('article|news' if task=='news' else 'notice'),paragraph,re.I):
                    problems.append('K8 quantified non-evaluable member: '+task)
        if 'seven-day' in paragraph and re.search(r'(?:undefined|unavailable)',paragraph,re.I):
            if normal(SEVEN) not in normal(paragraph):
                problems.append('K8 seven-day undefined without qualifier')
        for task,t in record['tasks'].items():
            if t['alert'] and re.search(r'\b'+task+r'\b|'+('article' if task=='news' else 'notice'),paragraph,re.I) and (re.search(r'(?<!no )\breliable (?:increment|reduction)',paragraph,re.I) or 'inferentially robust' in paragraph and any(c['class']=='IMP' and (__import__('table_results_conf_results').templates()['names'][c['arm']] in paragraph or c['arm']+'-' in paragraph) for c in t['contrasts'])):
                problems.append('K8 alert together with reliable increment: '+task)
    return problems


@lru_cache(maxsize=1)
def inherited_banned():
    import ast
    from table_results_conf_results import PROJ
    tree=ast.parse((PROJ/'studies/confirmation/robustness_tests/code/robustness_comparisons.py').read_text())
    for node in tree.body:
        if isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='BANNED_A4' for t in node.targets):return list(ast.literal_eval(node.value))
    raise RuntimeError('missing frozen BANNED_A4')


def strip_frozen_fixed_forms(text):
    from table_results_conf_results import templates, tex

    for identity,pattern in templates()['forms'].items():
        if re.search(r'\{[A-Za-z0-9_]+\}',pattern):continue
        if identity in templates()['replaces_forms']:continue
        for variant in (pattern,tex(pattern)):text=text.replace(variant,' ')
    return text


def strip_verified_pdf_forms(text,manifest):

    return strip_frozen_fixed_forms(text)


def generated_problems(text,rel,manifest,document):

    from table_results_conf_results import templates, frozen_template, author_title, tex, seven_undefined
    T=templates();record=manifest['record']
    marks=(__import__('table_results_conf_results').load_summary_comparisons().TP7['table6_mark_nc'] if any(t['alert'] for t in record['tasks'].values()) else '')+(T['frozen_templates']['table6_mark_seven'] if any(c['class']!='NE' and seven_undefined(c) for t in record['tasks'].values() for c in t['contrasts']) else '')+(T['frozen_templates']['table6_mark_mc'] if any(c.get('mc_unresolved',False) for t in record['tasks'].values() for c in t['contrasts']) else '')
    text=text.replace(frozen_template('table6_caption',marks=marks,table_ref='\\ref{tab:main_comparisons-sensitivity}'),' ')

    for identity,pattern in T['frozen_templates'].items():
        if '<<' not in pattern:
            for value in (pattern,tex(pattern)):text=text.replace(value,' ')
    if rel=='TABLE_RESULTS_title.tex':text=text.replace(tex(author_title(record['author_confirmation'])),' ')

    if rel=='TABLE_RESULTS_deviations.tex':
        for item in record.get('deviations',[]):
            for field in ('pre_deviation_reading','post_deviation_reading'):text=text.replace(tex(item[field]),' ')
    return source_problems(text,manifest['registry'],record,manifest['facts'],document)


def fixed_fact_problems(text,facts):
    from table_results_conf_results import tex
    text=normal(text.replace(r'\%','%'))
    out=[]
    for sentence in {s for ss in facts.get('rendered_sentences',{}).values() for s in ss}:
        expected=normal(sentence)

        parts=re.split(r'(\d+(?:[,.]\d+)*%?)',expected)
        pattern=''.join(r'[+-]?\d+(?:[,.]\d+)*%?' if re.fullmatch(r'\d+(?:[,.]\d+)*%?',p) else re.escape(p) for p in parts)
        for match in re.finditer(pattern,text):
            if match.group(0)!=expected:out.append('K8.1 fixed fact differs from display string: '+match.group(0))
    for values in facts.get('banned_renderings',{}).values():
        if isinstance(values,list):
            for value in values:
                if normal(value) in text:out.append('K8.1 banned fixed-fact rendering: '+value)
    return out


def source_problems(text,registry,record,facts,document=None):
    text=comments(text)
    text=re.sub(r'\\(?:label|ref|eqref|pageref|cite\w*)(?:\[[^]]*\])?\{[^}]*\}', ' ',text)
    problems=fixed_fact_problems(text,facts)
    text=strip_frozen_fixed_forms(text)
    calls=macro_calls(text)
    for call in calls:
        if '/'.join(call) not in registry:
            problems.append('K8 unknown claim macro: '+'/'.join(call))
    stripped=MACRO.sub(' REGISTEREDCLAIM ',text)
    stripped=strip_fact_sentences(stripped,facts,document)
    problems+=['K8 literal result number outside macro: '+m.group(0) for m in NUMBER.finditer(stripped)]

    stripped=stripped.replace(r'\mathrm','').replace(r'\texttt','').replace(r'\_','_').replace('{','').replace('}','')
    tokens=list(re.finditer(r"[A-Za-z0-9_]+(?:[-'][A-Za-z0-9_]+)*",stripped))
    from table_results_conf_results import ARMS
    arms={a for pairs in ARMS.values() for pair in pairs for a in pair}|{'N','R','L','P','NP','NPL','NPR','NPP','LEAR','W2_D','W_Bai','news','notice','notices','articles'}
    for i,tok in enumerate(tokens):
        if tok.group(0) in arms or tok.group(0).lower() in {x.lower() for x in __import__('table_results_conf_results').templates()['names'].values()}:
            start=tokens[max(0,i-12)].start(); end=tokens[min(len(tokens)-1,i+12)].end()
            if CLASS.search(stripped[start:end]):
                problems.append('K8 class word within twelve words of arm outside macro: '+tok.group(0))
    from table_results_conf_results import templates
    for name in templates()['names'].values():
        phrase=name.removeprefix('the ')
        for match in re.finditer(re.escape(phrase),stripped,re.I):
            nearby=re.findall(r"[A-Za-z0-9_]+(?:[-'][A-Za-z0-9_]+)*",stripped[:match.start()])[-12:]+re.findall(r"[A-Za-z0-9_]+(?:[-'][A-Za-z0-9_]+)*",stripped[match.end():])[:12]
            if CLASS.search(' '.join(nearby)):problems.append('K8 class word within twelve words of named representation: '+phrase)
    expanded=MACRO.sub(lambda m:registry.get('/'.join(m.groups()),'UNKNOWN CLAIM'),text)
    problems+=banned_problems(expanded)
    problems+=stale_problems(expanded,record)
    problems+=scope_problems(expanded,record)
    from table_renderer.constraint_contract import exclusion_problems
    problems+=exclusion_problems(stripped,any(t['alert'] for t in record['tasks'].values()))
    problems+=banned_problems(stripped)
    problems+=scope_problems(stripped,record)
    return problems

def text_problems(text,manifest,document):

    n=normal(text)
    problems=banned_problems(n)+stale_problems(n,manifest['record'])
    allowed=[]
    for paragraph in manifest['expected'][document]:
        np=normal(paragraph)
        if np not in n:
            problems.append('K8 expected RS8 paragraph missing or changed: '+np[:90])
        allowed.append(np)
    problems+=fixed_fact_problems(n,manifest['facts'])
    for sentence in manifest['facts']['rendered_sentences'].get(document,[]):
        if normal(sentence) in n:allowed.append(normal(sentence))


    for call in manifest.get('document_calls',{}).get(document,[]):
        key='/'.join(call)
        value=normal(manifest['registry'][key])
        if value not in n:
            problems.append('K8 macro expansion missing: '+key)
        allowed.append(value)
    remainder=n
    for value in sorted(set(allowed),key=len,reverse=True):
        remainder=remainder.replace(value,' ')

    return problems

def plain_problems(text):
    from table_results_conf_results import templates, words, ARMS
    n=normal(text);W=templates()['words'];out=[]
    for term in W['K8_BANNED_PLAIN']:
        if re.search(r'(?<![A-Za-z0-9_])'+re.escape(term)+r'(?![A-Za-z0-9_])',n,re.I):out.append('K8.14 internal plain term: '+term)
    arms={v for ps in ARMS.values() for pair in ps for v in pair}|{'N','M','P_content','W2_D','M+','M+0'}
    for arm in arms:
        if re.search(r'(?<![A-Za-z0-9_])'+re.escape(arm)+r'(?![A-Za-z0-9_])',n):out.append('K8.14 plain arm symbol: '+arm)
    for s in re.split(r'(?<=[.!?])\s+(?=[A-Z])',n):
        if words(s)>35:out.append('K8.14 sentence over 35 words')
    return out


def expectation_problems(manifest):
    from table_results_conf_results import A8_BINDINGS, render_bundle, FillError, render, validate_record
    out=[]
    if manifest.get('authority_sha256')!=A8_BINDINGS:return ['K8 inference_design expectation identity drift']
    try:
        validate_record(manifest['record'],{'a8_freeze_sha256':A8_BINDINGS['A8_FREEZE.json'],'fixed_facts_sha256':A8_BINDINGS['FIXED_FACTS_A8.json']})
        _,regenerated=render_bundle(manifest['record'],{'a8_freeze_sha256':A8_BINDINGS['A8_FREEZE.json'],'fixed_facts_sha256':A8_BINDINGS['FIXED_FACTS_A8.json'],'facts':manifest['facts']})
        for key in ('registry','expected','title','abstract_words','abstract_characters','abstract_text','abstract_level','generated_sha256','frozen_form_ids','frozen_template_ids'):
            if manifest.get(key)!=regenerated[key]:out.append('K8 generated expectation drift: '+key)
        if manifest.get('prefill_sha256') is not None:
            from table_renderer.prepare_table_fields import generate
            _,prefill=generate(manifest['record']['author_confirmation'],record=manifest['record'])
            expected_prefill=manifest.get('nonclaim_version',{}).get('prior_prefill_sha256',manifest['prefill_sha256'])
            if expected_prefill!=prefill['proposed_outputs_sha256']:out.append('K8 stage-4 source binding drift')
            if manifest.get('nonclaim_version'):
                for rel,paragraphs in manifest['nonclaim_version']['changes']['postscore_changed'].items():
                    for paragraph in paragraphs:out.extend(source_problems(paragraph,manifest['registry'],manifest['record'],manifest['facts']))
        v=render(manifest['record']);out+=plain_problems(v['text'])
        if v['words']>250 or v['characters']>1920:out.append('K8.15 abstract limits')
    except (FillError,KeyError,ValueError) as exc:out.append('K8 inference_design refusal: '+str(exc))
    return out


def pdf_text(path):
    import pymupdf
    with pymupdf.open(path) as doc:
        return '\n\n'.join(page.get_text(sort=True) for page in doc)

def inherited_source_problems(root,manifest):

    from table_results_conf_results import load_summary_comparisons,templates,tex,form,inherited_form
    E=load_summary_comparisons();E.deps();r=manifest['record'];out=[]
    out+=E.llm_problems(manifest['abstract_text'])
    tables={t['id']:t for t in r.get('source_tables',[])}
    for table in tables.values():
        raw='\n'.join(' & '.join(row) for row in table['rows'])
        out+=E.banned_problems(raw,table['id'])+E.minus_problems(re.sub(r'\$[^$]*\$', 'MATHFRAGMENT',raw),table['id'])
        width=table['header'].count(' & ')+1
        if any(len(row)!=width for row in table['rows']):out.append('K6.6 native table column census: '+table['id'])
    current='\n'.join(' & '.join(row) for t in tables.values() for row in t['rows'])
    for row in r.get('forest_rows',[]):
        if all(k in row for k in ('task','arm','ref','group')):
            label=row['arm']+' - '+row['ref']
            if row['group']=='Primary':
                if not any((row['arm'],row['ref'])==(c['arm'],c['reference']) for c in r['tasks'][row['task']]['contrasts']):out.append('K7.3 forest primary not in Table 6: '+label)
            elif label not in current and not any(row['arm'] in cell and row['ref'] in cell for t in tables.values() for cells in t['rows'] for cell in cells):out.append('K7.3 forest row missing from supplement: '+label)
    primary=root/'TABLE_RESULTS_tables.tex'
    if primary.exists():
        expanded=MACRO.sub(lambda m:manifest['registry'].get('/'.join(m.groups()),'UNKNOWN'),primary.read_text())
        want=sum(t['alert'] and c['class']!='NE' and c['envelope'] is not None for t in r['tasks'].values() for c in t['contrasts'])
        if expanded.count('$^{c}$')!=want:out.append('K7.2 nominal bound mark census')
        out+=E.minus_problems(re.sub(r'\$\[[^$]*\]\$', 'MATHINTERVAL',expanded),'Table 6')

    wbai=inherited_form('A6WBAI')
    for table in tables.values():
        for row in table['rows']:
            if row and 'W_Bai' in row[0] and (len(row)!=6 or row[1:5]!=['--']*4 or row[5]!=wbai):out.append('K7.1 word-screen row drift')
    secondary=tables.get('secondary_notice')
    if secondary and any('L_chen_notice' in row[0] for row in secondary['rows']):
        names=[row[0].replace(r'\_', '_').replace(r'$^{\ddagger}$','') for row in secondary['rows']]
        anchor='L_chen_notice - P_content';expected=['L_chen_notice - R','L_chen_notice - T']
        if anchor not in names or names[names.index(anchor)+1:names.index(anchor)+3]!=expected:out.append('K7.4 second-addendum rows/order missing')
        if E.TP7['s14_note'].strip() not in secondary['caption']:out.append('K7.4 second-addendum caption note missing')
    leads=root/'TABLE_RESULTS_detail.tex';conclusion=root/'TABLE_RESULTS_conclusion.tex'
    if leads.exists():
        text=MACRO.sub(lambda m:manifest['registry'].get('/'.join(m.groups()),'UNKNOWN'),leads.read_text())
        for task,t in r['tasks'].items():
            sentence=inherited_form('A6ALERT_S',task_label=__import__('table_results_conf_results').kept_task_label(task))
            if text.count(sentence)!=(1 if t['alert'] else 0):out.append('K6.5 one task alert required: '+task)
    if conclusion.exists() and any(t['alert'] for t in r['tasks'].values()):
        text=MACRO.sub(lambda m:manifest['registry'].get('/'.join(m.groups()),'UNKNOWN'),conclusion.read_text())
        if text.count('the pipeline diagnostic raised a pre-specified alert')!=1:out.append('K6.5 one conclusion alert required')
    return out


def check_documents(root,manifest,source_only=False):
    from check_arxiv import collect_sources
    from table_results_conf_results import sha256, validate_record
    root=Path(root).resolve()
    validate_record(manifest['record'])
    require_facts=manifest.get('facts',{}).get('rendered_sentences')
    if not isinstance(require_facts,dict) or set(require_facts)!= {'main','supplement'}:
        return {'state':'FAIL','problems':['K8 missing fixed-facts document binding']}
    problems=expectation_problems(manifest); results={}
    problems+=inherited_source_problems(root,manifest)
    problems+=independent_problems(root,manifest)
    for key,value in manifest['registry'].items():
        problems.extend(key+': '+p for p in banned_problems(value)+stale_problems(value,manifest['record']))
    from table_results_conf_results import tex
    for stem in ('main','supplement','audit_archive'):
        source=Path(root)/(stem+'.tex')
        if not source.is_file():problems.append('K8.19 missing title source: '+stem);continue
        generated=Path(root)/'TABLE_RESULTS_title.tex'
        title_source=generated.read_text() if '\\input{TABLE_RESULTS_title}' in source.read_text() and generated.is_file() else source.read_text()
        if r'\title{'+tex(manifest['title'])+'}' not in title_source:problems.append('K8.19 author title differs: '+stem)
    decl=Path(root)/'declarations.tex'
    if decl.is_file():
        from table_results_conf_results import templates
        d=decl.read_text()
        if d.count(templates()['frozen_templates']['auth_slot_marker_a8'])!=1 or d.count('\\input{TABLE_RESULTS_fixed}')!=1 or d.count('\\input{TABLE_RESULTS_author_a3_a6}')!=1:problems.append('K8.17 approval slots must be filled exactly once')
    arxiv=Path(root)/'arxiv_abstract.txt'
    if not arxiv.is_file() or arxiv.read_text().rstrip('\n')!=manifest['abstract_text']:problems.append('K8.15 arxiv abstract differs or is absent')
    for stem in ('main','supplement'):
        sources,deps=collect_sources(Path(root),include_attachments=stem=='main',entry=stem+'.tex')
        problems.extend('K8 missing source: '+str(d) for d in deps)
        calls=[]
        for path,text in sources.items():


            if path.name=='TABLE_RESULTS_claim_values.tex':
                from table_results_conf_results import claim_definitions
                problems.extend(generated_macro_syntax_problems(text))
                if text!=claim_definitions(manifest['registry']):
                    problems.append('K8 generated claim definitions drift')
                continue
            if path.name=='TABLE_RESULTS_RS8_2000.tex':
                from table_results_conf_results import tex
                if text != tex('Frozen 2,000-draw reading')+r'\par'+'\n'+tex(__import__('table_results_conf_results').rename_rendered(manifest['record']['specified_reading_2000']))+'\n':problems.append('K8 frozen 2000-draw reading drift')
                problems+=banned_problems(text)
                problems+=stale_problems(text,manifest['record'])
                continue
            if path.name=='TABLE_RESULTS_RS8_N0.tex':
                from table_results_conf_results import tex
                from table_renderer.prepare_table_fields import cited
                from table_renderer.reading_metadata import actual_source_problems
                problems.extend(actual_source_problems(text,manifest['record']))
                if text != cited(manifest['record']['specified_reading_n0'])+'\n':
                    problems.append('K8 specified N0 record drift')
                problems+=banned_problems(text)+stale_problems(text,manifest['record'])+scope_problems(manifest['record']['specified_reading_n0'],manifest['record'])
                continue
            rel=str(path.relative_to(root))
            problems.extend(fixed_fact_problems(text,manifest['facts']))
            generated=manifest.get('generated_sha256',{}).get(rel) or manifest.get('prefill_sha256',{}).get(rel)
            if generated is not None:
                from table_results_conf_results import text_hash
                if text_hash(text)!=generated:problems.append('K8 generated source drift: '+rel)
                elif rel in manifest.get('generated_sha256',{}):
                    problems.extend(rel+': '+p for p in generated_problems(text,rel,manifest,stem))
            else:
                for paragraph in manifest.get('postscore_changed',{}).get(rel,[]):
                    if paragraph not in text:problems.append('K8 changed paragraph missing: '+rel)
                    problems.extend(str(path.name)+': '+p for p in source_problems(paragraph,manifest['registry'],manifest['record'],manifest['facts'],stem))

            problems.extend('K8 unknown claim macro: '+ '/'.join(call) for call in macro_calls(text) if '/'.join(call) not in manifest['registry'])
            if path.name=='declarations.tex':
                text=text.replace(__import__('table_results_conf_results').templates()['frozen_templates']['auth_slot_marker_a8'],'')
            expanded=MACRO.sub(lambda m:tex(manifest['registry'].get('/'.join(m.groups()),'UNKNOWN CLAIM')),comments(text))
            problems.extend(rel+': '+p for p in banned_problems(expanded)+stale_problems(expanded,manifest['record']))
            calls.extend(macro_calls(text))
        local=dict(manifest,document_calls={stem:calls})
        pdf=Path(root)/(stem+'.pdf')
        for paragraph in manifest['expected'][stem]:
            joined='\n'.join(MACRO.sub(lambda m:manifest['registry'].get('/'.join(m.groups()),'UNKNOWN'),comments(t)) for p,t in sources.items() if p.name!='TABLE_RESULTS_claim_values.tex')
            if normal(paragraph.replace(r'\%','%').replace(r'\&','&')) not in normal(joined.replace(r'\%','%').replace(r'\&','&')):problems.append('K8 source expected paragraph absent: '+normal(paragraph)[:90])
        if source_only:
            results[stem]={'macro_calls':len(calls),'source_only':True}
            continue
        if not pdf.is_file():
            problems.append('K8 missing rendered PDF: '+stem)
        else:
            pp=text_problems(pdf_text(pdf),local,stem)
            problems.extend(stem+': '+p for p in pp)
            results[stem]={'pdf_sha256':sha256(pdf),'macro_calls':len(calls),'problems':pp}
    return {'state':'PASS' if not problems else 'FAIL','documents':results,'problems':problems}

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--manuscript',type=Path,required=True)
    p.add_argument('--expectations',type=Path,required=True)
    p.add_argument('--out',type=Path)
    p.add_argument('--source-only',action='store_true')
    a=p.parse_args(argv)
    from table_results_conf_results import timestamp_checks, strict_json
    binding=timestamp_checks()
    manifest=strict_json(a.expectations)
    from table_results_conf_results import author_context, inference_design, require
    first,second=author_context(inference_design.parent,manifest['record']['timestamps'])
    require(first==manifest['record']['author_confirmation'] and second==manifest['record']['author_prescore'], 'K8 author choice differs from named records')
    if manifest.get('facts')!=binding['facts']:
        result={'state':'FAIL','problems':['K8 fixed-facts file differs from timestamp_checks']}
    else:
        result=check_documents(a.manuscript,manifest,source_only=a.source_only)
    if a.out:
        if a.out.exists(): raise SystemExit('refuse receipt overwrite')
        a.out.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))
    return 0 if result['state']=='PASS' else 2

def independent_problems(root,manifest):

    import table_results_conf_results as F
    from table_renderer.table_contract import complete
    from table_renderer.constraint_contract import exclusion_problems
    out=[];r=manifest['record'];reg=manifest['registry']
    try:complete(r)
    except (F.FillError,KeyError,ValueError,TypeError) as exc:out.append('K8 independent native contract: '+str(exc))
    def expanded(name):
        path=Path(root)/name
        if not path.is_file():return ''
        return MACRO.sub(lambda m:reg.get('/'.join(m.groups()),'UNKNOWN'),comments(path.read_text()))
    current={name:expanded(name) for name in ('TABLE_RESULTS_detail.tex','TABLE_RESULTS_tables.tex','TABLE_RESULTS_support.tex','TABLE_RESULTS_conclusion.tex','sections/MS12_methods.tex')}

    for task,t in r['tasks'].items():
        for c in t['contrasts']:
            key=task+'/'+c['arm']+'-'+c['reference']+'/'
            if c['class'] in ('IMP','DET') and F.decimal(c['family_one_day'][0])<=0<=F.decimal(c['family_one_day'][1]):
                clause=F.form('A8Z',level='97.5' if task=='news' else '98.3')
                if clause not in reg.get(task+'/task/detail',''):out.append('K8.8 missing A8Z: '+key)
            expected_label='not evaluable' if c['class']=='NE' else 'increment detected under a negative-control alert' if t['alert'] and c['class']=='IMP' else None
            if expected_label is not None and reg.get(key+'label')!=expected_label:out.append('K8.3 primary inference label: '+key)
            if c['class']=='NE' and reg.get(key+'holm')!='not evaluable':out.append('K8.3 NE Holm suppression')
            if t['alert'] and c['class']=='IMP' and any(x in reg.get(task+'/task/detail','') for x in ('all six uncertainty checks agreed','held under all six')):out.append('K8.7 alert inference claim')
            if c['class'] in ('IMP','DET') and not F.robust(c,t['alert']) and not t['alert']:
                seed=F.form('A8SEED',e3=c['three_seed_effect'],c3=F.templates()['words']['PLAIN_C3'][c['three_seed_class']]) if c['three_seed_effect'] is not None else F.form('A8SEED_NOEST',c3=F.templates()['words']['PLAIN_C3'][c['three_seed_class']])
                if seed.removesuffix('.') not in reg.get(task+'/task/detail',''):out.append('K8.11 missing differing-seed reading: '+key)
            if c['class']=='IMP' and not t['alert'] and 'exploratory' not in reg.get(key+'cheap',''):out.append('K8.10 cheap-text qualifier')
            if task=='notice' and t['clk8']['state']=='INFORMATIVE' and not F.clock_ok(t['clk8']):
                if all(c['delay_classes'][k] is not None for k in ('15','60')):
                    phrase=F.form('A8DLY_LATE',name=F.templates()['names'][c['arm']],c15=F.templates()['words']['PLAIN_C3'][c['delay_classes']['15']],c60=F.templates()['words']['PLAIN_C3'][c['delay_classes']['60']])
                    if phrase not in current['TABLE_RESULTS_conclusion.tex']:out.append('K8.6 missing CLK8 LATE consequence in conclusion: '+key)
                    if manifest['abstract_level'] in ('P0','P1','P2') and phrase not in manifest['abstract_text']:out.append('K8.6 missing CLK8 LATE consequence in abstract: '+key)
    if F.form('A8LEVELS') not in current['sections/MS12_methods.tex'].replace(r'\%','%'):out.append('K8.8 missing A8LEVELS')
    for name in ('TABLE_RESULTS_abstract.tex','TABLE_RESULTS_conclusion.tex'):
        text=expanded(name)
        if any(phrase in text for phrase in ('its point estimate exceeds','the comparison value is excluded','comparison-value position is above')):out.append('K8.9 comparison position in '+name)
    for name,text in current.items():
        if name=='sections/MS12_methods.tex' and re.search(r'(?<!\d)(?:2,000|2000)(?!\d)',text.replace(F.tex(F.form('A8B_METHODS')),'')):out.append('K8.21 current inference still B2000')
        if 'not assigned.;' in text or re.search(r'\n\s*and report\b',text):out.append('K8 grammar fragment: '+name)
    for key,value in reg.items():
        if key.endswith('_caption/reading') or key.endswith('_header/reading') or '/declaration_' in key or re.search(r'/[^/]+_\d+_\d+/reading$',key):
            out.extend(key+': '+x for x in exclusion_problems(value,any(t['alert'] for t in r['tasks'].values())))
    from table_renderer.table_headings import headings
    for table in r['source_tables']:
        caption,header=headings(table,r)
        for suffix,want in (('caption',caption),('header',header)):
            if reg.get('global/'+table['id']+'_'+suffix+'/reading')!=want:out.append('K8 independent table '+suffix+' template: '+table['id'])
    claims=Path(root)/'TABLE_RESULTS_claim_values.tex'
    if claims.is_file() and re.search(r'\\textbackslash\{\}|\\textasciicircum|\\\$\[|\\\$\^',claims.read_text()):out.append('K8 rendered raw TeX escape')
    for rel in ('refs.bib','supplement_sections/refs.bib'):
        p=Path(root)/rel
        if p.is_file() and re.search(r'@(article|book|misc)\s*\{\s*(Clark2007|Andrews2000)',p.read_text(),re.I):out.append('K8 R13 forbidden bibliography activation')
    for name,text in current.items():
        if 'Clark and West' in text or 'Andrews and Buchinsky' in text:out.append('K8 R13 forbidden clause: '+name)
    methods=Path(root)/'supplement_sections/TABLE_RESULTS_A8_methods.tex'
    if methods.is_file():
        for key in ('Chordia2005','Cerqueira2020'):
            if not re.search(r'\\cite\w*(?:\[[^]]*\])?\{[^}]*\b'+key+r'\b',methods.read_text()):out.append('K8 missing actual reference: '+key)


    from table_renderer.prepare_table_fields import generate
    _,_,staged=generate(r['author_confirmation'],return_sources=True,record=r)
    for rel,text in staged.items():
        if rel=='audit_archive.tex' or rel.startswith('audit_archive_sections/'):
            p=Path(root)/rel
            if not p.is_file() or p.read_text()!=text:out.append('K8 archive allowlist drift: '+rel)
    return out


def generated_macro_syntax_problems(text):
    out=[]
    definitions=re.split(r'(?m)(?=^\\expandafter\\def\\csname Dres@)',text)
    for line in definitions:
        if not line.startswith(r'\expandafter\def\csname Dres@'):continue
        if re.search(r'(?<!\\)(?:\\\\)*%',line):out.append('K8 raw percent in generated macro')
        effective=re.sub(r'(?<!\\)(?:\\\\)*%[^\n]*','',line)
        stack=0
        for i,ch in enumerate(effective):
            escaped=len(effective[:i])-len(effective[:i].rstrip('\\'))
            if escaped%2:continue
            if ch=='{':stack+=1
            elif ch=='}':stack-=1
            if stack<0:break
        if stack:out.append('K8 unbalanced generated macro after TeX comments')
        dollars=re.findall(r'(?<!\\)(?:\\\\)*\$',effective)
        if len(dollars)%2 or effective.count(r'\(')!=effective.count(r'\)'):out.append('K8 unbalanced generated math delimiter')
    return out

if __name__=='__main__':raise SystemExit(main())
