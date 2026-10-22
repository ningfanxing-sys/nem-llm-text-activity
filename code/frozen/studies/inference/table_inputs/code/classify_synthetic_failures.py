'Classify the saved synthetic test failures.'
import hashlib, json, sys
from pathlib import Path
from table_input_hash import AP, ROOT, PROJ, FILL_ROOT

def digest(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def identity(p): return dict(path=str(Path(p).resolve()), sha256=digest(p))
def write(p, value): p.write_text(json.dumps(value, indent=2, ensure_ascii=False)+'\n')
def cite(rel, first, last, role):
    return dict(path=str(PROJ/rel), lines=[first,last], sha256=digest(PROJ/rel), role=role)

def classify():
    sys.path.insert(0,str(FILL_ROOT))
    from table_renderer import table_bodies as T
    baseline=AP/'a8post4/final_suite/validation_group_8_FULL_NATIVE_K8.json'
    second=AP/'a8post4/diagnostic2/validation_group_8_FULL_NATIVE_K8.json'
    k=json.loads(baseline.read_text()); assert k['problems']==json.loads(second.read_text())['problems']
    fixture=AP/'a8post3/final_suite2/A8_POSTSCORE.json'

    reuse=json.loads((AP/'a8post3/final_suite3/VERIFIED_READER_REUSE.json').read_text())
    for rel,sha in reuse['files'].items(): assert digest(AP/rel)==sha
    r=json.loads(fixture.read_text()); assert len(r['forest_rows'])==110
    shared=[cite('tables/summary_comparisons_conf_results.py',798,807,'FROZEN_K7_3_SUPPLEMENT_OBLIGATION'),
            cite('tables/fill3a_conf_results.py',1673,1708,'FROZEN_INHERITED_FOREST_DEFINITION'),
            cite('tables/main_comparisons_conf_results.py',1639,1646,'FROZEN_FOREST_INHERITANCE'),
            cite('studies/confirmation/A7/RULES_FOR_SUMMARY_COMPARISONS.md',11,11,'FROZEN_EVERY_FIGURE_ROW_IN_TABLE'),
            cite('studies/confirmation/INFERENCE_RULES.md',17,17,'FROZEN_PRIMARY_2_PLUS_3_HOLM'),
            cite('studies/confirmation/INFERENCE_RULES.md',41,41,'FROZEN_SECONDARY_REPORTING'),
            cite('studies/confirmation/STUDY_DESIGN.md',80,80,'FROZEN_SECONDARY_SCOPE'),
            cite('studies/inference/code/read_comparisons.py',742,763,'PINNED_NATIVE_FOREST_DEFINITION'),
            cite('studies/inference/code/native_tables.py',188,202,'PINNED_NATIVE_FOREST_CENSUS')]
    rows=[]
    for index,row in enumerate(r['forest_rows']):
        message='K7.3 forest row missing from supplement: '+row['arm']+' - '+row['ref']
        if row['group']=='Primary' or message not in k['problems']:continue
        descriptor=dict(kind='pair',task=row['task'],arm=row['arm'],reference=row['ref'])
        name='secondary_'+row['task']
        table=dict(id=name,scientific_context=T.scientific_context(r,name),body_cells=[[descriptor]],rows=[['']])
        try:
            rendered=T.expected_rows(r,table); category='a'; reason='inference synthetic plan omitted a pair accepted by the unchanged FILL contract'
            probe=dict(state='ACCEPTED',rows=rendered)
        except Exception as exc:
            category='b'; reason=str(exc); probe=dict(state='REJECTED',exception=type(exc).__name__,reason=reason)
        layer=row['field'].rsplit('/',1)[0].split('/',1)[1]
        references=list(shared)
        if layer.startswith('native:') and '__A1_OFFICIAL_CAP_RECLIP__' in layer:
            references.append(cite('studies/confirmation/execution/additional_scoring.py',26,26,'FROZEN_EXACT_PAIR_INVENTORY'))
        elif row['arm'] in ('W2_D','NPM') or row['ref']=='NPM' or row['ref']=='W2_D':
            references.append(cite('studies/confirmation/execution/additional_scoring.py',23,25,'FROZEN_EXACT_PAIR_INVENTORY'))
        elif layer=='cheap':
            references.append(cite('studies/confirmation/sensitivity_tests/code/sensitivity_comparisons.py',208,211,'FROZEN_EXACT_PAIR_INVENTORY'))
        elif layer=='shift':
            references.append(cite('studies/confirmation/primary_tests/code/primary_comparisons.py',47,51,'FROZEN_EXACT_PAIR_INVENTORY'))
        else:
            references.append(cite('studies/confirmation/execution/seal_score.py',333,347,'FROZEN_EXACT_PAIR_INVENTORY'))
        rows.append(dict(problem_ordinal=len(rows)+1,problem=message,category=category,reason=reason,
            identity=dict(forest_index=index,task=row['task'],group=row['group'],layer=layer,arm=row['arm'],reference=row['ref'],field=row['field']),
            current_pair_descriptor=descriptor,descriptor_probe=probe,specified_sources=references))
    assert [x['problem'] for x in rows]==k['problems'] and len(rows)==68
    counts={c:sum(x['category']==c for x in rows) for c in ('a','b')}; assert counts==dict(a=16,b=52)
    result=dict(schema='A8POST5_G05_CLASSIFICATION_V1',state='CLASSIFIED_NOT_CLOSED',synthetic_only=True,
        baseline=identity(baseline),diagnostic=identity(second),synthetic_native_fixture=identity(fixture),
        consumer=dict(root=str(FILL_ROOT),table_bodies=identity(FILL_ROOT/'table_renderer/table_bodies.py'),
                      interface=identity(FILL_ROOT/'A8_POSTSCORE_INTERFACE.json')),
        counts=counts,forest_rows=110,primary_rows=5,nonprimary_rows=105,rows=rows,
        classification_rule='Row-label K7.3 cause: actual expected_rows pair probe. Additional numeric-timestamp_checks gap applies independently to nonprimary postscore scientific cells, including category a; fixing label coverage never claims numeric closure.',
        global_native_authority_gap=dict(state='FILL_CHANGE_REQUIRED',affected_nonprimary_forest_rows=105,
            source=cite(str((FILL_ROOT/'table_renderer/table_bodies.py').relative_to(PROJ)),41,49,'NO_NONPRIMARY_POSTSCORE_T5_EXCEPTION')),
        scientific_scope='110 is this synthetic emitted census, not a universal frozen row count. No primary hypothesis or Holm family is expanded.')
    observed=ROOT/'diagnostic2/FILL_FULL_NATIVE_K8.json'
    if observed.exists():
        actual=json.loads(observed.read_text());assert actual['state']=='FAIL' and len(actual['problems'])==50
        result['rendered_text_check_limit']=dict(source=cite(str((FILL_ROOT/'check_table_sources.py').relative_to(PROJ)),303,309,'NONPRIMARY_SUBSTRING_CHECK'),
            observed_receipt=identity(observed),observed_missing_count=50,
            still_refused_text_matched_rows=[row['identity'] for row in rows if row['identity']['forest_index'] in (58,82)],
            input_checks='NP/N is incidentally substring-matched by L14/NP etc. Exact NP/N typed descriptors still refuse. Classification remains a16/b52; no exact row or native timestamp_checks closure is claimed.')
    return result

def main():
    result=classify(); write(ROOT/'G05_CLASSIFICATION.json',result)
    lines=['# Input validation summary','',
      'Classification: (a) 16 inference plan omissions; (b) 52 FILL descriptor refusals. All 68 instances are enumerated in G05_CLASSIFICATION.json, preserving duplicate pairs by exact forest index and source field. This request is delivered before the engineering suite; it is not an approval or freeze.', '',
      '## Specified scope and immutable sources','',
      'Frozen K7.3 requires every emitted forest row in its corresponding supplement/table: tables/summary_comparisons_conf_results.py:798–807; confirmation/A7/RULES_FOR_SUMMARY_COMPARISONS.md:11,32. The inherited frozen forest definition is tables/fill3a_conf_results.py:1673–1708, inherited by main_comparisons_conf_results.py:1639–1646. The exact current native projection is AP/code/read_comparisons.py:742–763 and AP/code/native_tables.py:188–202, byte-pinned reviewed AP sources, not an effective AP source freeze. These functions preserve the specified pair inventories, not a new scientific scope.', '',
      'Primary scope is unchanged: confirmation/INFERENCE_RULES.md:17 and confirmation/STUDY_DESIGN.md:67 retain news {L_count−M,L_chen−M}, notice {L14−M_notice,L_Laz−M_notice,L_chen_notice−M_notice}; preserve all primary slots, class/check/alert/disposition context and Holm families. Secondary reporting is already required by INFERENCE_RULES.md:41 and STUDY_DESIGN.md:80. 110 is the full synthetic fixture census (5 primary + 105 nonprimary), not a rule requiring 110 in every production disposition.', '',
      'Current FILL refusals: table_bodies.py:178–182 and scoped_contrast:22–25 prohibit nonprimary arms; pair references at :89–91 reject E_raw/W2_D/P_shift. Native numeric cells at :41–49 require historic T5 timestamp_checks and have no nonprimary postscore route. Primary-only table_contract.native_primary:152–165 is not a blanket exemption. Every (b) instance below has exact frozen-source path/line/SHA citations in the JSON.', '',
      '## Exact requested schema','',
      'The machine-readable normative schemas are G05_INTERFACE_SCHEMAS.json: table_plan and native_authority. The producer supplies A8POST5_TABLE_PLAN_V1 with exactly the nine existing nonprimary table IDs. Only the static base plan is genuinely T5-bound; specified assembly exports NATIVE_SUPPLEMENT.json and TABLE_PLAN_POSTSCORE.json as separate dynamic POSTscore companions under the frozen producer, with identities in evidence.nonprimary_supplement. The expanded plan must never be claimed as historic T5. Existing closed descriptors remain unchanged. Add forest_pair {kind,identity} and forest_native {kind,identity,field,timestamp_checks}; identity is exactly {forest_index,task,group,layer,arm,reference,field}. Consumer resolution must match an existing nonprimary record.forest_rows slot and the identity-bound native-timestamp_checks slot. No descriptor can add a new contrast or attach a primary RS8 class/check to a different reference.', '',
      'A8POST5_NATIVE_SUPPLEMENT_V1 is a small POSTscore export from the already computed specified current families. It contains exact source_receipt_sha256, producer_identity, frozen_function_identities, forest_rows_sha256, primary_pairs, and all nonprimary slots in original order. Each slot contains identity, scope=SPECIFIED_NONPRIMARY, role, adjustment {family_m,dm,interval}, seed_design, values. Values are formatted by the original specified P.decimal/P.interval_strings and copied from current reports; effect/one_day/seven_day must independently match the forest values. Raw/two directional DM p, HAC7 p, Holm p and days retain their original values/nulls; values.native_decision is audit only and is never a display field. Exposure-excluded descriptive subsets are DIAGNOSTIC, routed to diagnostics, and values.class is the exact frozen label not applicable (descriptive subset). Official-cap native rows remain SENSITIVITY. No scoring, bootstrap, averaging or new inference is performed.', '',
      'Each timestamp_checks has exactly {path,sha256,pointer,source_receipt_sha256}; pointer identifies the complete /rows/i slot. FILL checks bytes/SHA, exact source receipt and forest census, producer/functions under the genuinely T5-listed frozen code, and the independently verified postscore timestamp_checks chain, analogous to the existing primary export. Dynamic numeric timestamp_checks bytes are POSTscore and must never be inserted into historic T5. Any additional independent consumer-chain receipt required by FILL must be explicit; AP cannot manufacture one.', '',
      '## Nonprimary labels','',
      'All new rows remain in supplement tables, labelled specified secondary/diagnostic/sensitivity as appropriate and “does not change the primary family decision”. Pair identity includes the layer so repeated labels remain distinct. Unadjusted single-secondary/cheap comparisons keep unadjusted labels; combination and other specified families retain their own family_m/Holm/interval basis. Additional single-seed sensitivity rows remain single-seed; no fabricated three-seed mean or robustness. The consumer owns the exact neutral label rendering. Existing primary rows, primary census, scientific contexts and primary Holm adjustment are byte/field-equivalent.', '',
      '## Exact acceptance test','',
      'Use AP/table_inputs/tests/test_producer.py::test_fresh_fill_assembly_and_source_k8 with the SHA-verified AP3 full native synthetic cache and the complete exported plan/timestamp_checks. Preserve every one of the 110 original forest rows (including duplicate arm/reference labels with distinct layer/field), all 12 tables, unchanged native primary authorities and original primary families. Run the real current consumer schema/complete-input/render and **K.check_documents(copy_root, receipt, source_only=True)**. Acceptance requires state=PASS, problems=[], forest census=110 and exact untouched primary/native reading identities. A bounded FILL fixture PASS, deletion/relabeling of forest rows or weaker checker cannot satisfy this test. The AP5 engineering suite is permitted to retain current FILL refusal evidence while this change is pending; that is not G05 closure.', '',
      '## Exact (b) instances','',
      '| ordinal | forest index | task | layer | arm | reference | field | refusal |','|---|---|---|---|---|---|---|---|']
    for row in result['rows']:
        if row['category']=='b':
            i=row['identity'];lines.append('| '+ ' | '.join(str(v) for v in (row['problem_ordinal'],i['forest_index'],i['task'],i['layer'],i['arm'],i['reference'],i['field'],row['reason']))+' |')
    if 'rendered_text_check_limit' in result:
        lines += ['', '## Preserved current rendered-check limitation', '',
          'After the 16 inference label fixes, the real F9 source K8 reports 50 missing instances. Two (b) NP/N slots, forest indices 58 and 82, are incidentally matched by L14/NP etc: F9 check_table_sources.py:303–309 checks arm and reference as independent substrings, so NP already contains N. This is not exact NP/N row coverage or an accepted typed/native timestamp_checks. All 52 FILL descriptor obligations and all 105 nonprimary numeric-timestamp_checks obligations remain. The requested identity-distinct full plan must resolve every native slot; this incidental text match cannot establish G05 closure.']
    (ROOT/'G05_FILL_INTERFACE_REQUEST.md').write_text('\n'.join(lines)+'\n')
    print('A8POST5 STEP1 DELIVERED: a=16 b=52; FILL_CHANGE_REQUIRED; G05_OPEN; 68/68 exact row identities classified')

if __name__=='__main__':main()
