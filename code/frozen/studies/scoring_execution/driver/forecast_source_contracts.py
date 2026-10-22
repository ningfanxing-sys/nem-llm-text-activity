'Check the source contracts for forecast input records.'
from pathlib import Path
import json
from forecast_check_helpers import checked, document, exclusive, require, row

HERE = Path(__file__).absolute().parent
DECISION = 'studies/confirmation/comparison_specifications/SOURCE_DECISION_TIME_ALIGNMENT_A2_20261010.md'
MODE = 'TIME_ALIGNMENT_A2_MECHANICAL_SOURCE_ADOPTION'
NAMES = ('NUMERIC_ANCESTOR_CONTRACT.json', 'RUNTIME_FAMILY_POLICY.json', 'SCORER_CONTRACT.json',
         'ENTRY_CONTRACTS.json', 'SCIENTIFIC_ASSOCIATION.json')


def timestamp_checks(value, sources=None, *, original_source=None):
    text = checked(value['decision'], sources).decode()
    require('TIME_ALIGNMENT-primary_tests (ADOPTED' in text and 'produce it from existing evidence, mechanically' in text,
            'Adopted TIME_ALIGNMENT-primary_tests source disposition required')
    require(value.get('adoption') == MODE and value.get('production_authority') is False,
            'Source-only mechanical adoption; no reviewer or production grant')
    for item in value['evidence']:
        original_source(item) if original_source is not None else checked(item, sources)


def numeric(item, native):
    value = document(item, native.sources); timestamp_checks(value, native.sources)
    proposal = document(value['proposal'], native.sources)
    require(value.get('schema') == 'C_SCORING_NUMERIC_ANCESTORS_V1' and
            value.get('source_adopted') is True and value['files'] == proposal['files'] and
            value.get('downstream_successor_files') == proposal.get('downstream_successor_files') == {},
            'Exact original ancestor proposal only; no downstream numerical substitution')
    files = {name: dict(path=str(native.project / name), **pin) for name, pin in value['files'].items()}
    for r in files.values(): checked(r, native.sources)
    return dict(files=files, contract=item, scientific_eligibility_changed=False)


def policy(binding, native):
    timestamp_checks(binding, native.sources)
    require(binding.get('schema') == 'MINRUN_C_V1_SCIENTIFIC_ASSOCIATION_V1' and
            binding.get('scientific_eligibility_changed') is False,
            'Limited C scientific source association required')
    values = {k: document(binding[k], native.sources) for k in
              ('runtime_family_policy', 'scorer_contract', 'entry_contracts')}


    historical = None
    def original_source(item):
        nonlocal historical
        root = getattr(native, 'driver_root', HERE)
        if Path(item['path']).is_relative_to(root):
            if historical is None:
                from forecast_contract_history import ContractSources
                historical = ContractSources(native)
            return historical.verify(item)
        return checked(item, native.sources)
    for v in values.values(): timestamp_checks(v, native.sources, original_source=original_source)
    p, s, e = [values[k] for k in ('runtime_family_policy', 'scorer_contract', 'entry_contracts')]
    require(p['schema'] == 'MINRUN_RUNTIME_FAMILIES_V1' and set(p['families']) == {'AP5','AP6','notice_delays','scoring_callback'},
            'Four actual driver families required')
    require(e['schema'] == 'MINRUN_ENTRY_CONTRACTS_V1' and e['entry_contracts'] == p['families'],
            'Exact installed driver entry contracts required')
    require(s['schema'] == 'MINRUN_SCORER_CONTRACT_V1' and s['original']['callable'] == 'seal_score.score' and
            s['r2']['callable'] == 'news_source.official_score', 'Original/R2 actual scorer entry required')
    for family in p['families'].values(): original_source(family['source'])
    for entry in e['entry_contracts'].values(): original_source(entry['source'])
    for role in ('original', 'r2'):
        original_source(s[role]['source'])
        require(s[role]['output_census_rule'] == 'NATIVE_FRESH_DIRECTORY_RECEIPT_COMPLETE_CENSUS',
                'Complete original native receipt census required')
    return values


def produce(native, directory=HERE):

    directory = Path(directory); directory.mkdir(exist_ok=True)
    decision = row(native.project / DECISION)
    proposal_path = native.c_root / 'NUMERIC_ANCESTOR_PROPOSAL.json'
    proposal = json.loads(native.sources.bytes(proposal_path))
    proposal_id = row(proposal_path, native.sources.bytes(proposal_path))
    for name, pin in proposal['files'].items(): checked(dict(path=str(native.project/name), **pin), native.sources)
    def source(path):
        p = Path(path)
        return row(p, native.sources.bytes(p)) if str(p) in native.sources.rows else row(p)
    def put(name, value, evidence):
        value.update(adoption=MODE, decision=decision, evidence=evidence, production_authority=False,
                     scientific_eligibility_changed=False, independent_acceptance_created=False)
        return exclusive(directory/name, value)
    ancestor = put(NAMES[0], dict(schema=proposal['schema'], source_adopted=True,
        proposal=proposal_id, files=proposal['files'], downstream_successor_files=proposal['downstream_successor_files']),
        [proposal_id, *[source(native.project/n) for n in proposal['files']]])
    entries_source = source(HERE/'native_entries.py'); bridge = source(HERE/'scoring_entry.py')
    families = {k: dict(source=entries_source, callable='native_entries.'+fn, argv=[]) for k,fn in
                [('AP5','ap5_science'),('AP6','ap6_joint'),('notice_delays','rd_joint')]}
    families['scoring_callback'] = dict(source=bridge, callable='scoring_entry.child/fresh_r2',
                              capture_order='original_exit_immediate_capture_then_R2', fresh_state=True)
    policy_id = put(NAMES[1], dict(schema='MINRUN_RUNTIME_FAMILIES_V1', families=families), [entries_source, bridge])
    entry_id = put(NAMES[3], dict(schema='MINRUN_ENTRY_CONTRACTS_V1', entry_contracts=families), [entries_source, bridge])
    r2_rows = [r for r in native.catalog['files'] if r['logical_path'].endswith('/pc_primary_r2_20261008/code/news_source.py')]
    require(len(r2_rows)==1, 'Unique accepted R2 source required')
    original = source(native.project/'studies/confirmation/execution/seal_score.py')
    r2 = source(native.project/r2_rows[0]['logical_path'])
    score_id = put(NAMES[2], dict(schema='MINRUN_SCORER_CONTRACT_V1',
        original=dict(callable='seal_score.score', source=original,
                      output_census_rule='NATIVE_FRESH_DIRECTORY_RECEIPT_COMPLETE_CENSUS'),
        r2=dict(callable='news_source.official_score',source=r2,
                output_census_rule='NATIVE_FRESH_DIRECTORY_RECEIPT_COMPLETE_CENSUS'),
        receipt_path_source='REAL_CONTROL_AT_RELEASE', official_views='original_214_and_R2_specified'),
        [original,r2,bridge,source(HERE/'association.py')])
    association = put(NAMES[4], dict(schema='MINRUN_C_V1_SCIENTIFIC_ASSOCIATION_V1',
        runtime_family_policy=policy_id, scorer_contract=score_id, entry_contracts=entry_id,
        numeric_ancestor_contract=ancestor, c61=native.c61()['sources'],
        dual_official_view_source=source(HERE/'association.py'), scope='SOURCE_ASSOCIATION_ONLY',
        full_suite='NOT_RUN_B_CLASS'), [ancestor,policy_id,score_id,entry_id,*native.c61()['sources'].values()])
    return dict(numeric_ancestor_contract=ancestor, runtime_family_policy=policy_id, scorer_contract=score_id,
                entry_contracts=entry_id, release_binding=association)


def base_acceptance(native, original):

    def acceptance(path, schema, source_map, tests, mapping):
        from forecast_check_helpers import utc,now
        p=Path(path).absolute();value=document(row(p),native.sources)
        require(p.is_relative_to(native.project/'studies/confirmation/forecast_hashes') and
                value.get('schema')==schema and value.get('state')=='ACCEPTED_FOR_SOURCE_FREEZE',
                'Actual original-named AF owner scientific acceptance required')
        require(value.get('reviewed_sources')==source_map and value.get('test_receipt')==row(tests) and
                value.get('root_mapping')==mapping and value.get('owner') and utc(value['recorded_utc'])<=utc(now()),
                'Exact base source/test/mapping and actual dated owner acceptance')
        if schema=='FORECAST_BINDING5_REVIEW_ACCEPTANCE_V1':
            require(value.get('independent') is True,'Actual independent AF scientific Part B required')
            checked(value['review_report'],native.sources)
        else:
            interface=native.project/'studies/confirmation/forecast_hashes/SCORING_REPORTING_PATH.md'
            require(value.get('scoring_interface')==row(interface) and value.get('scientific_eligibility_changed') is False,
                    'Original scoring interface and eligibility unchanged')
        return row(p)
    return acceptance
