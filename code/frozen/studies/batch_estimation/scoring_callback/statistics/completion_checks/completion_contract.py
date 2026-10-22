'Check source identities and metadata chains for scoring completion.'
import scientific_contract as K

def verify_final_registry(registry, template):
    K.require(registry['production_authority'] is False, 'Registry is not timestamp_checks')
    K.require(template['production_authority'] is False and template['source_reviewed'] is False,
              'Only an unreviewed template may be inspected here')
    K.require(template['python_process_allowlist'] == [], 'Default allowlist must be empty')
    K.require(template['scientific_route'] == list(K.ROUTE), 'Original capture ordering drift')
    K.require(template['historical_FILL_completion_required'] is False,
              'No writing completion prerequisite')
    for entry in registry['entries']:
        K.require(entry.get('entry_path'), 'Known source entries must not remain guessed/null')
        if entry.get('historical_blocked_name_only') is True:
            K.require(entry['entry_path'] in template['historical_FILL_blocked_entry_paths'] and
                      entry.get('source_identity') is None and entry['production_authority'] is False,
                      'Historical FILL names must not add a writing-source completion gate')
            continue
        K.exact_identity(entry['source_identity'])
        K.require(entry['entry_path'] == entry['source_identity']['path'], 'Registry source alias/drift')
        K.require(entry['production_authority'] is False, 'Source entry cannot authorize itself')
    K.require(template['r2_binding']['successor_entry'] == registry['r2_successor_identity'],
              'R2 successor source identity drift')
    K.require(template['r2_binding']['permit_identity'] is None and
              template['r2_binding']['state_root'] is None and
              template['r2_binding']['t5_identity'] is None, 'No invented real identities')
    for output in template['scientific_output_contracts'].values():
        K.require(output['root'] is None and output['source_reviewed'] is False,
                  'Real output roots wait for a reviewed real plan')
        K.require(len(output['relative_paths']) == len(set(output['relative_paths'])),
                  'Duplicate output leaf')
    return 'SOURCE_REGISTRY_VERIFIED_NOT_RUNTIME_GRANT'

def project_authority(timestamp_checks, contract):

    field = contract['inventory_field']
    K.require(field in ('files', 'sources'), 'Unknown inventory key')
    K.require(timestamp_checks.get('declared_census') == contract['names'], 'Declared census drift')
    return dict(identity=timestamp_checks['identity'], schema=timestamp_checks['schema'],
                state=timestamp_checks['state'], frozen_utc=timestamp_checks['frozen_utc'], files=timestamp_checks[field])

def exact_names(actual, required, label):

    for names in (actual, required):
        K.require(isinstance(names, list) and names and
                  all(isinstance(n, str) and n for n in names), 'Missing census: '+label)
        K.require(len(names) == len(set(names)), 'Duplicate census: '+label)
    K.require(set(actual) == set(required), 'Missing/extra census: '+label)

def verify_terminal_receipt(receipt, exact_sources, validation_spec, expected_bindings):

    K.require(validation_spec.get('schema') == 'SCORECB5B_REQUIRED_VALIDATION_V1' and
              validation_spec.get('production_authority') is False, 'Wrong validation specification')
    branches = validation_spec.get('required_branches')
    tests = validation_spec.get('required_tests')
    exact_names(branches, branches, 'reviewed branches')
    exact_names(tests, tests, 'reviewed tests')
    K.require('SCORECB5A5_real_macos_process_table_positive' in branches,
              'Reviewed census must include the real host branch')
    K.verify_source_census(receipt.get('tested_sources'), exact_sources)
    by_path = {row['path']: row for row in exact_sources}
    bound_sources = validation_spec.get('source_bindings')
    K.require(isinstance(bound_sources, list) and bound_sources, 'Missing specification source bindings')
    K.verify_source_census(bound_sources, [by_path.get(row.get('path')) for row in bound_sources])
    binding_fields = ('validation_spec_identity', 'authorization', 'delivery_inventory_identity',
                      'source_dependency_inventory_identity', 'final_registry_identity', 'final_template_identity')
    K.require(set(expected_bindings) == set(binding_fields), 'Exact independently verified bindings required')
    for field in binding_fields:
        expected = K.exact_identity(expected_bindings[field])
        K.require(receipt.get(field) == expected, 'Receipt identity drift: '+field)
        if field != 'authorization':
            K.require(by_path.get(expected['path']) == expected, 'Identity outside tested bytes: '+field)
    K.require(receipt.get('authorization_scope') == 'SCORECB_SCORING_NEW_FULL_SYNTHETIC_SUITE_TERMINAL',
              'Wrong scoped terminal authorization')
    for field in ('required_branches', 'executed_branches', 'passed_branches'):
        exact_names(receipt.get(field), branches, field)
    for field in ('required_tests', 'executed_tests', 'passed_tests'):
        exact_names(receipt.get(field), tests, field)
    K.require(receipt.get('schema') == 'SCORECB_SCORING_SOURCE_SYNTHETIC_RECEIPT_V1' and
              receipt.get('state') == 'PASS' and receipt.get('mode') == 'terminal-host' and
              receipt.get('all_required_validation_complete') is True and
              receipt.get('all_non_host_validation_complete') is True, 'Pending/partial host receipt')
    K.require(receipt.get('full_suite_runs') == 1 and type(receipt.get('tests_run')) is int and
              receipt['tests_run'] == len(tests) and
              all(receipt.get(k) == 0 for k in ('failures', 'errors', 'skipped', 'production_payload_reads')),
              'Unclean complete suite')
    for field in ('harness_errors', 'denied_production_accesses', 'source_identity_drift', 'missing_non_host_coverage'):
        K.require(receipt.get(field) == [], 'Host refusal/drift ledger: '+field)
    K.require(receipt.get('authorization_identity_unchanged') is True, 'Release identity drift')
    coverage = receipt.get('coverage')
    K.require(isinstance(coverage, dict) and set(coverage) == set(branches), 'Incomplete coverage keys')
    K.require(all(isinstance(x, dict) and x.get('executed') is True and x.get('successful_test') is True
              for x in coverage.values()), 'A required dynamic branch did not execute')
    terminal = receipt['terminal']
    K.require(all(terminal.get(k) is True for k in ('actual_process_scan_verified', 'live_positive',
              'synthetic_capture_executed', 'no_candidate')), 'Unmocked/live-positive/capture pending')
    K.require(terminal.get('extra_allowlist_used') is False, 'Host cannot use extra allowlist')
    resources = receipt['resources']; samples = resources['checkpoints']
    K.require(resources.get('test_processes') == 1 and samples, 'One observed test process required')
    K.require(all(s.get('nice') == 20 and s.get('memory_free_percent', 0) >= 25 and
              0 <= s.get('scratch_bytes', -1) < 1000000000 and
              0 <= s.get('peak_rss_bytes', -1) <= 1610612736 for s in samples), 'Resource gates breached')
    K.require(receipt.get('production_authority') is False and receipt.get('real_C_T5_grant') is False,
              'Synthetic PASS must not masquerade as production permission')
    return 'SAME_BYTE_TERMINAL_PASS_METADATA_VERIFIED_NOT_T5_GRANT'
