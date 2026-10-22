'Check the source files required by the numerical tests.'
import json
from pathlib import Path
from contract_io import ContractError,_canonical,_json

def source_contracts(root):
    root=_canonical(root)
    policy=_json(_canonical(root/'RUNTIME_FAMILY_POLICY.json',root,regular=True).read_bytes())
    entries=_json(_canonical(root/'ENTRY_CONTRACTS.json',root,regular=True).read_bytes())
    scorer=_json(_canonical(root/'SCORER_CONTRACT.json',root,regular=True).read_bytes())
    if policy.get('status')!='REVIEWED_EXACT_OWNER_CONTRACTS' or set(policy['families'])!={'AP5','AP6','notice_delays','scoring_callback'}:raise ContractError('PENDING owner science census policy')
    fields={'root','freeze','schema','state','inventory_field','inventory_format','inventory_base','declared_census_field','names'}
    for family,row in policy['families'].items():
        if set(row)!=fields or any(row[k] is None for k in fields) or not row['names'] or len(row['names'])!=len(set(row['names'])):raise ContractError('PENDING exact '+family+' writer/census')
        for name in row['names']:
            p=Path(name)
            if p.is_absolute() or '..' in p.parts or name!=p.as_posix() or any(t in name for t in '*?[]'):raise ContractError('Owner census alias/wildcard')
    if entries.get('status')!='REVIEWED_EXACT_OWNER_ENTRIES' or any(r.get('status')!='OWNER_DELIVERED_REVIEWED' or not r.get('source') or not r.get('callable') for r in entries['entries'].values()):raise ContractError('PENDING complete AP/notice_delays/scoring_callback source entries')
    from runtime_entries import ROLE_FAMILY
    if set(entries['entries'])!=set(ROLE_FAMILY):raise ContractError('Exact nine source entry roles required')
    for role,row in entries['entries'].items():
        if row['family']!=ROLE_FAMILY[role] or row['source'] not in policy['families'][row['family']]['names'] or not row['callable'].isidentifier():raise ContractError('Entry foreign member/callable alias')
    if scorer.get('schema')!='C_SCORING_SCORER_CONTRACT_V1' or scorer.get('source_status')!='REVIEWED_SOURCE_SOURCE_DELIVERY':raise ContractError('PENDING agreed source-only scorer contract')
    if scorer.get('status')!='REVIEWED_EXACT_R2_SOURCE_DELIVERY':raise ContractError('Source scorer contract unreviewed')
    for view in ('original','r2'):
        row=scorer[view]
        if not all(row.get(k) for k in ('state_root','receipt_path','report_path','output_census')):raise ContractError('Finite '+view+' output contract pending')
        if len(row['output_census'])!=len(set(row['output_census'])):raise ContractError('Duplicate output census')
    if not all(scorer['r2'].get(k) for k in ('permit_path','feature_root','state_seal_association')) or not scorer['r2']['state_seal_association'].get('source_reviewed'):raise ContractError('R2 source permit/state bridge pending')
    cp=scorer['capture_contract']
    if not isinstance(cp.get('producer_outputs'),dict) or not isinstance(cp.get('initial_input_paths'),list):raise ContractError('Exact native capture partition pending')
    scope=scorer['completion_scope']
    if not scope.get('output_root') or not scope.get('output_paths') or not scope.get('control_paths'):raise ContractError('Finite completion scope pending')
    if set(scorer['command_contracts'])!={'arm','capture','r2-complete','r2-score','postscore','optional-r2'}:raise ContractError('Exact source command census required')
    for row in scorer['command_contracts'].values():
        if not row.get('request_path') or not row.get('parent_paths') or row.get('producer_family') not in policy['families']:raise ContractError('Finite command provenance pending')


    return dict(state='SOURCE_INTERFACES_READY_FOR_SYNTHETIC_ACCEPT',production_authority=False,real_runtime_identities_verified=False)
