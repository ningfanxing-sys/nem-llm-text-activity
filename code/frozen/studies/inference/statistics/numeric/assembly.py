'Compute result fields using the checked statistical functions.'
import ast
from copy import deepcopy
import json
from pathlib import Path
from ..input_checks import HERE, require, checked_bytes
from .slots import forest_projection, native_census


def helpers(P, checked_source):

    parent = HERE.parent / 'code/read_comparisons.py'
    require(Path(P.__file__).resolve() == parent, 'Inherited namespace origin drift')
    checked_bytes(parent, checked_source)
    own = HERE / 'numeric/inherited_assembly.py'
    data = checked_bytes(own, checked_source)


    namespace = dict(P.__dict__, P=P, deepcopy=deepcopy, Path=Path)
    exec(compile(ast.parse(data), str(own), 'exec'), namespace)
    checked_bytes(parent, checked_source)
    require(checked_bytes(own, checked_source) == data, 'Extracted helper drift')
    return namespace


def assemble_numeric(P, primary_tests, sensitivity_tests, robustness_tests, frozen, F, manifest, inputs, bundles,
                     current, saved_2000, replay_evidence, chunk=512, gate=None,
                     *, checked_source):
    require(F is None, 'Numeric seam received a writing consumer')
    require(replay_evidence is not None, 'Fresh native V2 replay required')
    h = helpers(P, checked_source)
    propagation, sc = h['assembly_prefix'](primary_tests, sensitivity_tests, robustness_tests, frozen, None, manifest,
                                          inputs, bundles, current, saved_2000,
                                          replay_evidence, chunk, gate)
    context, batch = inputs['context'], inputs['batch']
    census = json.loads(checked_bytes(HERE / 'SLOT_CENSUS.json', checked_source))
    h['prepare_stages'](inputs)
    record = dict(schema='AP_SCORING_NATIVE_NUMERIC_V1', bootstrap_draws=P.DRAWS,
                  source_receipt_sha256=manifest['inputs']['score_receipt']['sha256'],
                  tasks={}, optional=deepcopy(context['optional']),
                  author_confirmation=deepcopy(inputs['author']),
                  batch_parity_failed=any(v['state'] != 'PASS' for v in batch['scoring_parity'].values()))
    record['stages'] = h['stage_projection'](census['stage_names'],
        inputs['score_report']['stage_dispositions'], batch, context['own_stages'],
        inputs['author']['choices']['r8_seeds'] == 'three', batch['scoring_parity'], False)
    for task in P.PAIRS:
        family = current[task + '/primary']
        if family['state'] != 'COMPUTED':
            context['task_complete'][task] = False
            context['task_reasons'][task] = 'parity' if family.get('reason') == 'A8NR_PARITY' else 'fail'
        contrasts = [P.output_contrast(primary_tests, sensitivity_tests, robustness_tests, sc, bundles[task + '/primary'],
                     family, i, task, batch, context) for i in range(len(P.PAIRS[task]))]


        for c in contrasts:
            attr = next(a for a in propagation['details'][task]['a3']['attribution_a3']
                        if a['arm'] == c['arm'])
            cheap = attr.get('cheap_text', {})
            c['cheap_comparators'] = {kind: [primary_tests.COMPARATOR_NAME[k] for k, v in
                cheap.get('computed', {}).items() if v == val]
                for kind, val in (('beaten', 'beaten'), ('not_beaten', 'not_beaten'), ('worse', 'worse'))}
            c['cheap_comparators']['unavailable'] = [primary_tests.COMPARATOR_NAME[k] for k in cheap.get('unavailable', [])]
            key = robustness_tests.cheap_reading_key(cheap)
            c['cheap_text'] = ('NOT_EVALUABLE' if context['pc_flags'][task]['alert'] or not cheap.get('computed')
                              else 'BETTER' if key == 'A4CHR_BETTER' else 'WORSE'
                              if 'worse' in cheap.get('computed', {}).values() else 'NOTSHOWN')
        bound = [float(c['envelope']) for c in contrasts
                 if c['class'] in ('NULL', 'DET') and c['envelope'] is not None]
        mn = current[task + '/mn']
        mr = mn['reports'][0] if mn['state'] == 'COMPUTED' else None
        record['tasks'][task] = dict(complete=context['task_complete'][task], contrasts=contrasts,
            alert=context['pc_flags'][task]['alert'], signal_failed=context['pc_flags'][task]['signal_failed'],
            reason=context['task_reasons'][task], secondary_clause=context['secondary_clause'][task],
            secondary_check=context['secondary_check'][task],
            secondary_differing_arms=context['secondary_differing_arms'][task],
            bound=P.decimal(max(bound), 3, 'hi') if bound else None,
            mn_effect=P.decimal(mr.get('effect_percent_reference_mae')) if mr else None,
            mn_class=P.CLASS[mr['decision']] if mr else 'NE')
    h['selection_projection'](None, primary_tests, sensitivity_tests, robustness_tests, record, inputs, manifest, current, propagation)


    record['current'] = primary_tests.json_safe(deepcopy(current))
    record['propagation'] = primary_tests.json_safe(deepcopy(propagation))
    record['specified_reading_2000'] = primary_tests.json_safe(deepcopy(saved_2000))
    record['forest_slots'] = forest_projection(record['current'], census)
    record['native_comparison_census'] = native_census(record['current'])
    record['operational'] = deepcopy({k: inputs[k] for k in
        ('human_review', 'hrc_review', 'hrc_agreement', 'author_a3_a6', 'specification2', 'timestamps')})
    record['deviations'] = deepcopy(context['deviations'])
    record['fill_clock'] = deepcopy(context['fill_clock'])
    record['declarations'] = deepcopy(context['declarations'])
    record['clk8'] = deepcopy(inputs['clk8'])
    record['original_seed_native'] = {task: deepcopy(record['current'][task + '/primary'].get('three_seed'))
                                      for task in P.PAIRS}
    record['clipping'] = primary_tests.json_safe(deepcopy(replay_evidence['clipping']))
    record['score_report_native'] = deepcopy(inputs['score_report'])
    record['batch_native'] = primary_tests.json_safe(deepcopy(batch))
    evidence = dict(schema='AP_SCORING_NATIVE_NUMERIC_EVIDENCE_V1', inputs=deepcopy(manifest['inputs']),
                    loss_replay=primary_tests.json_safe({k: v for k, v in replay_evidence.items()
                                             if k not in ('native', 'reader', 'clipping')}),
                    stage_counts={c: sum(r['counted_category'] == c for r in record['stages']) for c in P.CATEGORIES},
                    frozen_A4_caps=deepcopy(propagation['caps']), current_draws=P.DRAWS,
                    production_authority=False)
    evidence['rerun_count_all_batch_dispositions'] = sum(r['stage'] in P.RERUNS and r['postseal'] != '--' for r in record['stages'])
    evidence['rerun_count_fully_completed'] = sum(r['stage'] in P.RERUNS and r['postseal'] != '--' and
                                                r['counted_category'] == P.CATEGORIES[0] for r in record['stages'])
    return record, evidence
