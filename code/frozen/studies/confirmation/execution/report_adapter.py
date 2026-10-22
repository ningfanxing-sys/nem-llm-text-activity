"""Pure rendering of already-saved CONF inference and descriptive reports.

No truth, prediction, feature, bootstrap-draw or training input is opened here.
The decisions/statistics remain those saved by frozen scoring; the only numeric
operation is the registered display bound X=max(0,-lower interval endpoint).
"""
from __future__ import annotations

import csv
import math
from pathlib import Path

try:
    from .runtime import read_json
except ImportError:
    from runtime import read_json

NO_EQUIVALENCE = 'This does not establish equivalence or zero effect.'
DESCRIPTIVE = 'This is a descriptive diagnostic, not an inferential confirmation gate or a source of new feature selection.'
SENSITIVITY = 'This pre-specified sensitivity concerns {name}. The main window, representation and seed remain the primary analysis; this estimate does not replace that decision.'


def _finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _number(value):
    return format(value, '.12g') if _finite(value) else 'undefined'


def _bootstrap(report, block):
    items = report.get('bootstrap', {})
    return items.get(str(block), items.get(block, {}))


def _interval(report, block):
    value = _bootstrap(report, block).get('interval95_percent')
    return value if isinstance(value, (list, tuple)) and len(value) == 2 and all(_finite(x) for x in value) else None


def _interval_text(report, block):
    interval = _interval(report, block)
    return '[' + ','.join(_number(v) for v in interval) + ']%' if interval is not None else 'undefined (' + _percentage_reason(report, block) + ')'


def _percentage_reason(report, block=1):
    record = _bootstrap(report, block)
    if record.get('reason') or record.get('recorded_reason'):
        return str(record.get('reason') or record['recorded_reason'])
    reference = record.get('reference_mae')
    if 'reference_mae' in record and (not _finite(reference) or reference <= 0):
        return 'zero or nonfinite reference MAE'
    if record.get('state') and record['state'] != 'DEFINED':
        return str(record['state'])
    if record.get('finite_draws') == 0:
        return 'no finite percentage bootstrap draws'
    return 'a finite percentage effect/interval was not recorded'


def _test_reason(report, field='dm_p1'):
    record = report.get(field, {})
    reason = record.get('reason') or record.get('recorded_reason') or report.get('reason')
    if reason:
        return str(reason)
    state = record.get('state')
    if state == 'UNDEFINED_VARIANCE':
        return 'UNDEFINED_VARIANCE (nonpositive or nonfinite registered DM variance)'
    if state and state != 'DEFINED':
        return str(state)
    return 'a finite registered ' + ('Holm p value' if field == 'dm_p1' and 'primary_two_sided_holm_p' in report else 'DM test') + ' was not recorded'


def _decision(mean, p):
    if not _finite(mean) or not _finite(p):
        return None
    return (-1 if mean < 0 else 1 if mean > 0 else 0) if p < .05 else 0


def disagreement_names(report, primary=False):
    """Name disagreement with the saved nominal decision, including absent
    support for a rejection. An undefined sensitivity is disclosed separately
    for a nonrejection and is not declared a conflicting decision.
    """
    nominal_p = report.get('primary_two_sided_holm_p') if primary else report.get('dm_p1', {}).get('p_two_sided')
    nominal = _decision(report.get('dm_p1', {}).get('mean_difference'), nominal_p)
    if nominal is None:
        return []
    names = []
    for block, label in ((1, 'one-day paired interval'), (7, 'seven-day paired interval')):
        interval = _interval(report, block)
        direction = None if interval is None else -1 if interval[1] < 0 else 1 if interval[0] > 0 else 0
        if (nominal != 0 and direction != nominal) or (nominal == 0 and direction not in (0, None)):
            names.append(label + (' (undefined)' if direction is None else ''))
    hac = report.get('dm_hac7', {})
    p = report.get('sensitivity_hac7_two_sided_holm_p') if primary else hac.get('p_two_sided')
    direction = _decision(hac.get('mean_difference', report.get('dm_p1', {}).get('mean_difference')), p)
    if (nominal != 0 and direction != nominal) or (nominal == 0 and direction not in (0, None)):
        names.append(('HAC7 Holm sensitivity' if primary else 'HAC7 sensitivity') + (' (undefined)' if direction is None else ''))
    return names


def uncertainty_sentence(report, primary=False):
    names = disagreement_names(report, primary)
    if not names:
        return ''
    return 'The nominal DM decision is not supported consistently by ' + ', '.join(names) + '. This disagreement limits the robustness of the conclusion; the primary decision and every sensitivity are retained.'


def primary_sentence(report, task):
    if task not in ('news', 'notice'):
        raise ValueError('Unknown registered source')
    unit = 'article volume' if task == 'news' else 'notice activity'
    arm, ref = report['arm'], report['reference']
    name = arm + '−' + ref
    b = _bootstrap(report, 1)
    interval, effect = _interval(report, 1), b.get('effect_percent_reference_mae')
    p, mean = report.get('primary_two_sided_holm_p'), report.get('dm_p1', {}).get('mean_difference')
    if not _finite(p) or not _finite(mean):
        return f'The registered test for {name} is undefined because {_test_reason(report)}. No reliable increment conclusion or improvement-exclusion bound is available from that calculation.'
    if interval is None or not _finite(effect):
        return f'The registered percentage interval for {name} is undefined because {_percentage_reason(report)}. No reliable increment conclusion or improvement-exclusion bound is available from that calculation.'
    lo, hi = interval
    if p < .05 and mean < 0:
        text = f"A conditional reliable increment beyond {unit} was detected for {name} under the registered pooled p=1 daily DM rule: {_number(effect)}% of {ref}'s MAE, one-day 95% interval [{_number(lo)},{_number(hi)}]%, Holm p={_number(p)}. This is conditional evidence for this historical window and design."
    elif p < .05 and mean > 0:
        text = f"Conditional deterioration beyond {unit} was detected for {name} under the registered pooled p=1 daily DM rule: {_number(effect)}% of {ref}'s MAE, one-day 95% interval [{_number(lo)},{_number(hi)}]%, Holm p={_number(p)}."
    else:
        text = f"No reliable increment beyond {unit} was detected for {name}: {_number(effect)}% of {ref}'s MAE, one-day 95% interval [{_number(lo)},{_number(hi)}]%. Improvements larger than {_number(max(0., -lo))}% of {ref}'s MAE are excluded by this nominal 95% interval, conditional on these fitted predictions and this resampling design. {NO_EQUIVALENCE}"
    uncertainty = uncertainty_sentence(report, primary=True)
    return text + (' ' + uncertainty if uncertainty else '')


def _secondary_prefix(arm, reference):
    if arm == 'LEAR' or reference == 'LEAR':
        return 'This secondary benchmark comparison concerns issue-legal adapted LEAR; LEAR is not a text arm.'
    if arm == 'NPL' and reference in ('NP', 'NPP'):
        return 'This secondary E3 contrast confirms or refutes the earlier positive finding under the new labels and untouched target window; the bundled activity and semantic input cannot be isolated by this contrast.'
    if (arm, reference) in (('NP', 'N'), ('NPP', 'NP')):
        return 'This secondary E3 contrast estimates the named P5MIN/shifted-input bundle relative to its registered reference; it does not isolate semantic information.'
    if arm in ('L_chen', 'L_chen_notice') and reference in ('P_shift', 'P_content'):
        return 'This secondary project diagnostic compares original and altered content/activity under the frozen REDESIGN rule; it neither identifies causation nor replaces the primary increment test.'
    if arm == 'P_content' and reference in ('M', 'M_notice'):
        return 'This secondary project diagnostic has no top-venue placebo template. It compares activity-matched, within-month permuted content with the identical matched-key activity reference.'
    if arm == 'P_shift' and reference in ('M_shift', 'M_shift_notice'):
        return 'This secondary project diagnostic has no top-venue placebo template. All clocks and derived dates were shifted together by 28 days; the estimate is conditional on that altered activity process.'
    if arm in ('E_raw', 'W_Bai') and reference == 'M':
        return 'This secondary contrast estimates the increment of ' + ('raw text' if arm == 'E_raw' else 'Bai word frequencies') + ' beyond article volume.'
    # CONFX5 (CONF-A1 decisions 4 and 7): the registered additions use the frozen class forms.
    if (arm, reference) == ('W2_D', 'M'):
        return 'This secondary contrast estimates the increment of scale-matched Bai word frequencies beyond article volume.'
    if (arm, reference) == ('NPL', 'NPM'):
        return 'This secondary E3 contrast estimates the increment of the L14 notice-content columns beyond notice activity, given the P5MIN block; it does not identify a mechanism.'
    if (arm, reference) == ('L_chen', 'E_raw'):
        return 'This secondary contrast compares structured-field serialisation with raw title/body encoding; it does not identify a mechanism.'
    return 'This secondary contrast estimates the named input bundle against its registered reference; it is not a primary confirmation decision.'


def metric_reading(report, primary=False):
    """Render saved statistics; display both frozen bounds without selecting one."""
    ref = report['reference']; one, seven = _bootstrap(report, 1), _bootstrap(report, 7)
    dm, hac = report.get('dm_p1', {}), report.get('dm_hac7', {})
    def bound(block):
        interval = _interval(report, block)
        if primary and (not _finite(report.get('primary_two_sided_holm_p')) or not _finite(dm.get('mean_difference'))):
            return 'unavailable (registered test undefined)'
        if primary and (not _finite(one.get('effect_percent_reference_mae')) or _interval(report, 1) is None):
            return 'unavailable (registered percentage interval undefined)' if block == 1 else (_number(max(0., -interval[0])) + '%' if interval is not None else 'undefined')
        return _number(max(0., -interval[0])) + '%' if interval is not None else 'undefined'
    text = f"{report['arm']}−{ref}: effect={_number(one.get('effect_percent_reference_mae'))}% of {ref}'s MAE; one-day nominal 95% interval {_interval_text(report, 1)}; seven-day secondary 95% interval {_interval_text(report, 7)}; one-day nominal improvement-exclusion X={bound(1)}; seven-day secondary improvement-exclusion X={bound(7)}; raw daily mean difference={_number(dm.get('mean_difference'))}; reference raw MAE={_number(one.get('reference_mae'))}; raw DM p(two-sided)={_number(dm.get('p_two_sided'))}, p(improvement)={_number(dm.get('p_improvement'))}, p(deterioration)={_number(dm.get('p_deterioration'))}; HAC7 p(two-sided)={_number(hac.get('p_two_sided'))}, p(improvement)={_number(hac.get('p_improvement'))}, p(deterioration)={_number(hac.get('p_deterioration'))}."
    if primary:
        text += f" Primary Holm p={_number(report.get('primary_two_sided_holm_p'))}; secondary HAC7 Holm p={_number(report.get('sensitivity_hac7_two_sided_holm_p'))}."
    if not _finite(hac.get('p_two_sided')):
        text += ' HAC7 undefined because ' + _test_reason(report, 'dm_hac7') + '.'
    for block, bootstrap in ((1, one), (7, seven)):
        if 'finite_draws' in bootstrap:
            text += f" {block}-day bootstrap finite/undefined draws={bootstrap.get('finite_draws')}/{bootstrap.get('undefined_draws')}; nonpositive-effect tail count={bootstrap.get('bootstrap_nonpositive_effect_count')}/{bootstrap.get('finite_draws')}; Monte Carlo resolution={_number(bootstrap.get('monte_carlo_resolution'))}."
    return text + ' ' + NO_EQUIVALENCE


def secondary_reading(arm, reference, report, source):
    if source not in ('news', 'notice'):
        raise ValueError('Unknown registered source')
    prefix = _secondary_prefix(arm, reference)
    if report.get('state') == 'NO_VALID_PERMUTATION':
        return prefix + ' NO_VALID_PERMUTATION: no valid matched P_content support; this is not a successful null or zero effect.'
    dm = report.get('dm_p1', {}); p, mean = dm.get('p_two_sided'), dm.get('mean_difference')
    metrics = metric_reading({**report, 'arm': arm, 'reference': reference})
    if not _finite(p) or not _finite(mean):
        result = 'The registered secondary test is undefined because ' + _test_reason(report) + '; no reliable increment conclusion is available.'
    elif p < .05 and mean < 0:
        result = 'A conditional favorable difference was observed in this secondary comparison.'
    elif p < .05 and mean > 0:
        result = 'A conditional unfavorable difference was observed in this secondary comparison.'
    else:
        result = 'No reliable increment was detected in this secondary comparison.'
    text = prefix + ' ' + metrics + ' ' + result
    # Frozen paired diagnostic language follows the paired estimate and intervals.
    if arm in ('L_chen', 'L_chen_notice') and reference in ('P_shift', 'P_content'):
        if _finite(p) and _finite(mean):
            text += ' ' + ('A conditional difference between the original-content and project placebo predictions was observed in this secondary diagnostic; it does not identify a mechanism.' if p < .05 and mean != 0 else 'No reliable paired difference between the original-content and placebo predictions was detected under this project diagnostic.')
    uncertainty = uncertainty_sentence(report)
    return text + (' ' + uncertainty if uncertainty else '')


def _link(path, label=None):
    path = Path(path)
    return '[' + (label or path.name).replace('|', '\\|') + '](<' + str(path.resolve()) + '>)'


def _table(headers, rows):
    def cell(value):
        return str(value).replace('|', '\\|').replace('\n', ' ')
    return '\n'.join(['| ' + ' | '.join(headers) + ' |', '| ' + ' | '.join('---' for _ in headers) + ' |'] + ['| ' + ' | '.join(cell(v) for v in row) + ' |' for row in rows])


def _saved_inference(root, path):
    """Only named report JSON beneath scored_root can be decoded."""
    path = Path(path)
    if not path.is_absolute():
        path = root / path
    path = path.resolve()
    if path.parent != root.resolve() or path.suffix != '.json' or '__' not in path.name:
        raise ValueError('Inference report must be a direct saved scoring JSON')
    return read_json(path)


def _csv_table(path, pooled_only=False):
    # These are already-produced descriptive artifacts, never numeric source panels.
    with path.open(newline='', encoding='utf-8') as handle:
        reader = csv.DictReader(handle)
        rows = [row for row in reader if not pooled_only or not any(row.get(k) for k in ('target_day', 'region', 'horizon'))]
        return _table(reader.fieldnames or [], [[row.get(k, '') for k in (reader.fieldnames or [])] for row in rows]) if reader.fieldnames else 'EMPTY_DESCRIPTIVE_ARTIFACT'


def _stage_reasons(summaries):
    reasons = []
    for stage in summaries.get('stage_dispositions', []):
        if stage.get('state') != 'COMPLETE':
            reasons.append(str(stage.get('stage', 'unnamed stage')) + ': ' + str(stage.get('state', 'UNAVAILABLE')) + '; ' + str(stage.get('reason') or stage.get('error') or 'see retained stage receipt'))
        for config in stage.get('unavailable_configurations', []):
            reasons.append(str(config.get('task_id', 'unnamed configuration')) + ': ' + str(config.get('state', 'UNAVAILABLE')) + '; ' + str(config.get('reason') or config.get('error') or 'see retained stage receipt'))
    return reasons


def e3_joint_reading(state, reports, reasons=None):
    pairs = [('NPL', 'NP'), ('NPL', 'NPP')]
    records = {(r['arm'], r['reference']): r for r in reports}
    if state == 'E3_SECONDARY_JOINT_NOT_EVALUABLE':
        recorded = list(reasons or [])
        for pair in pairs:
            r = records.get(pair)
            if r is not None and _decision(r.get('dm_p1', {}).get('mean_difference'), r.get('dm_p1', {}).get('p_two_sided')) is None:
                recorded.append('−'.join(pair) + ': registered daily DM undefined because ' + _test_reason(r))
        return state + ': ' + '; '.join(recorded or ['required paired E3 inputs/tests unavailable; see retained secondary and stage dispositions']) + '.'
    if state == 'E3_SECONDARY_JOINT_CONFIRMED':
        text = 'The earlier positive notice finding was conditionally reproduced by both registered E3 contrasts in this secondary confirmation design.'
    elif state == 'E3_SECONDARY_JOINT_NOT_CONFIRMED':
        failed = []
        for pair in pairs:
            r = records.get(pair)
            dm = r.get('dm_p1', {}) if r else {}
            if _decision(dm.get('mean_difference'), dm.get('p_two_sided')) != -1:
                failed.append('−'.join(pair))
        estimates = '; '.join(metric_reading(records[p]) if p in records else '−'.join(p) + ': unavailable' for p in pairs)
        text = 'The earlier positive notice finding was not confirmed jointly by this design; nonpassing contrasts: ' + ', '.join(failed) + '; all estimates: ' + estimates
    else:
        raise ValueError('Unknown saved E3 joint state')
    uncertainties = [(p, uncertainty_sentence(records[p])) for p in pairs if p in records]
    return state + ': ' + text + ''.join(' ' + '−'.join(p) + ': ' + u for p, u in uncertainties if u)


def _a1_lines(root, summaries):
    """CONF-A1 (CONFX5) section from saved summaries and saved A1 JSON only; frozen readings untouched."""
    a1 = summaries.get('A1')
    lines = ['## CONF-A1 计分前补充（CONFX5 实施；冻结的主判定规则不变）']
    if not a1:
        return lines + ['CONF-A1: no saved A1 summary in this score report.']
    lines.append('Binding decisions SHA-256 at implementation ' + str(a1.get('decisions_sha256_at_implementation')) +
                 '; CONFX5 SPEC SHA-256 ' + str(a1.get('spec_sha256_at_implementation')) + '. ' + str(a1.get('source', '')))
    lines += ['### 分任务陈述（决定 9）'] + [str(x) for x in a1.get('per_task_statements', [])]
    lines.append('Window wording (decision 10): ' + str(a1.get('exposure_wording')) + '.')
    for key, label in (('w2_d', 'W2_D (decision 4)'), ('npm', 'NPM (decision 7)')):
        item = a1.get(key) or {}
        lines.append(label + ': ' + str(item.get('state', 'NOT_REGISTERED_IN_MANIFEST')) +
                     ('; ' + str(item.get('reason')) if item.get('reason') else '') + '.')
    if a1.get('w_bai_note'):
        lines.append(a1['w_bai_note'])
    lear = a1.get('lear_convergence_diagnostic') or {}
    if lear:
        lines.append('LEAR convergence diagnostic (template rule; descriptive, no accuracy): state=' + str(lear.get('state')) +
                     '; daily jobs=' + str(lear.get('daily_jobs')) + '; hour fits=' + str(lear.get('hour_fits')) +
                     '; coordinate-descent fits with a ConvergenceWarning=' + str(lear.get('cd_nonconverged_hour_fits')) +
                     '; largest reported gap/tolerance=' + _number(lear.get('cd_max_gap_over_tolerance')) +
                     '; hour fits with a LARS ConvergenceWarning=' + str(lear.get('hour_fits_with_lars_convergence_warning')) +
                     '; LARS warnings by type=' + str(lear.get('lars_convergence_warnings_by_type')) + '.')
    rule = a1.get('shift_support_rule') or {}
    if rule:
        lines.append('Shift-support rule (decision 5), arms ' + ', '.join(rule.get('arms', [])) + ': ' + str(rule.get('a1_sentence')))
    for source in ('news', 'notice'):
        task = (a1.get('tasks') or {}).get(source)
        if not task:
            lines += ['### ' + source, 'CONF-A1: task additions absent.']
            continue
        lines.append('### ' + ('新闻' if source == 'news' else '公告') + '：CONF-A1')
        lines.append('SESOI ' + _number(a1.get('sesoi_percent')) + '% (decision 2; interpretation only, never a decision rule):')
        for item in task.get('sesoi', []):
            name = item['arm'] + '−' + item['reference']
            lines.append(name + ': ' + (item.get('sentence') or str(item.get('branch'))))
            if item.get('seven_day_sentence'):
                lines.append(name + ': ' + item['seven_day_sentence'])
        lines.append('Seed rule (decision 3):')
        for row in (task.get('seed_fragile') or {}).get('rows', []):
            lines.append(str(row.get('sentence')) + ' Single-seed effects (% of reference MAE): ' +
                         ', '.join(str(k) + '=' + _number(v) for k, v in (row.get('single_seed_effects_percent_reference_mae') or {}).items()) +
                         '; SD=' + _number(row.get('single_seed_effect_sd_percent')) + '.')
        hln = task.get('hln') or {}
        lines.append('HLN t(n−1) declared sensitivity (decision 9): ' + str(hln.get('rule', '')))
        lines.append(_table(['比较', 'df', 'HLN p', 'HLN Holm p', 'HLN 判读', '主判读', '一致'],
            [[r['arm'] + '−' + r['reference'], r.get('df'), _number(r.get('hln_t_p_two_sided')), _number(r.get('hln_t_holm_p')),
              r.get('hln_decision'), r.get('primary_decision'), r.get('agrees_with_primary_decision')] for r in hln.get('rows', [])]))
        lines += [r['disagreement_sentence'] for r in hln.get('rows', []) if r.get('disagreement_sentence')]
        exposure = task.get('exposure_excluded') or {}
        lines.append(SENSITIVITY.format(name='the primary contrasts recomputed on the ' + str(exposure.get('days')) +
                     ' target days with no recorded analysis (decision 10; descriptive; sealed predictions; no refit)'))
        if exposure.get('report_path'):
            inference = _saved_inference(root, exposure['report_path'])
            lines.append(_link(exposure['report_path']) + '; day runs=' + str(exposure.get('day_runs')) + '; date gaps=' + str(inference.get('date_gaps', [])) + '.')
            lines += [metric_reading(report) for report in inference.get('reports', [])]
        cap = task.get('official_cap') or {}
        lines.append('Official market price cap (decision 6): FY caps ' + str(cap.get('caps_by_financial_year')) + '. ' + str(cap.get('window_c')))
        if cap.get('news_rule'):
            lines.append(cap['news_rule'])
        if cap.get('diagnostic_path'):
            lines += [_link(cap['diagnostic_path']), _csv_table(Path(cap['diagnostic_path']))]
        primary = cap.get('primary') or {}
        if primary.get('report_path'):
            lines.append(SENSITIVITY.format(name='re-clipping the sealed raw notice predictions at the official cap (no refit)'))
            inference = _saved_inference(root, primary['report_path'])
            lines.append(_link(primary['report_path']) + '.')
            for report in inference.get('reports', []):
                lines.append(metric_reading(report, primary=True) + ' Re-clip decision=' + str(report.get('primary_decision')) + '.')
        for row in cap.get('e3', []):
            if row.get('report_path'):
                inference = _saved_inference(root, row['report_path'])
                lines.append(_link(row['report_path']) + '; days=' + str(row.get('days')) + '.')
                lines += [metric_reading(report) for report in inference.get('reports', [])]
            else:
                lines.append(row['arm'] + '−' + row['reference'] + ' (official-cap re-clip): ' + str(row.get('state')) + '.')
        if cap.get('e3_joint_state'):
            lines.append('E3 joint reading under the official-cap re-clip: ' + str(cap['e3_joint_state']) + '. ' + str(cap.get('e3_joint_day_rule')))
    return lines


def write_host_report(scored_root, summaries):
    """Write REPORT_zh.md using only saved summary JSON/descriptive CSV files.

    Links to binary masks, diagnostics, predictions and draws are provenance
    only: this function never opens them. Missing stage slots remain visible.
    """
    root = Path(scored_root).resolve()
    lines = ['# CONF 执行结果', '本报告仅渲染已保存的推断与描述性结果。主分析使用注册的主种子 20260919；新闻 Holm 家族固定为 2，公告家族固定为 3。负的 A−B 表示 A 的误差较低。',
             '新闻主窗口为 214 天、15,408 个共同键；公告主窗口为 61 个目标日、527,040 个共同键。缺少输入或完整预测的比较保留其状态，不缩短主窗口。']
    stage_reasons = _stage_reasons(summaries)
    for source in ('news', 'notice'):
        summary = summaries.get(source)
        if not summary:
            lines += ['## ' + source, 'NOT_EVALUABLE: saved task summary absent.']
            continue
        lines.append('## ' + ('新闻' if source == 'news' else '公告'))
        primary_path = summary.get('primary_path', root / (source + '__PRIMARY.json'))
        primary = _saved_inference(root, primary_path)
        lines += ['### 主分析', _link(primary_path)]
        rows = []
        for report in primary.get('reports', []):
            one = _bootstrap(report, 1)
            rows.append([report['arm'] + '−' + report['reference'], _number(one.get('effect_percent_reference_mae')), _interval_text(report, 1), _interval_text(report, 7), _number(report.get('primary_two_sided_holm_p')), _number(report.get('sensitivity_hac7_two_sided_holm_p')), report.get('primary_decision', 'undefined')])
        lines.append(_table(['比较', '效应 %（参考 MAE）', '1 日区间', '7 日区间（次要）', '主 Holm p', 'HAC7 Holm p（次要）', '保存的决策'], rows))
        for report in primary.get('reports', []):
            lines += [primary_sentence(report, source), metric_reading(report, primary=True)]
        lines += ['### 原币值 MAE 与全部次要比较', _table(['arm', 'pooled raw MAE'], [[a, _number(v)] for a, v in summary.get('pooled_mae', {}).items()])]
        if source == 'news' and summary.get('weekly_naive'):
            weekly = summary['weekly_naive']
            lines += ['Weekly naive / rMAE (descriptive): ' + str(weekly.get('state')) + '; denominator MAE=' + _number(weekly.get('mae')) + '; missing keys=' + str(weekly.get('missing_keys', 0)) + '.', _table(['arm', 'rMAE'], [[a, _number(v)] for a, v in weekly.get('rmae', {}).items()])]
        secondary_reports = []
        for slot in summary.get('secondary', []):
            name = slot['arm'] + '−' + slot['reference']
            if slot.get('state') != 'COMPUTED_SECONDARY':
                explanation = slot.get('reason') or ('no valid matched P_content support; this is not a successful null or zero effect' if slot.get('state') == 'NO_VALID_PERMUTATION' else 'registered arm/reference or complete matched support unavailable')
                lines.append(name + ': ' + str(slot.get('state', 'NOT_EVALUABLE')) + '; ' + explanation + '.')
                if slot.get('a1_sentence'):
                    lines.append(slot['a1_sentence'])
                continue
            path = slot.get('report_path', root / (source + '__SECONDARY__' + slot['arm'] + '__' + slot['reference'] + '.json'))
            inference = _saved_inference(root, path)
            report = next((r for r in inference.get('reports', []) if r['arm'] == slot['arm'] and r['reference'] == slot['reference']), None)
            if report is None:
                raise ValueError('Saved computed secondary slot missing its named inference')
            secondary_reports.append(report)
            lines += [_link(path) + '; paired matched keys=' + str(slot.get('matched_keys', 'recorded in inference')) + '; days=' + str(slot.get('days', 'recorded in inference')) + '; date gaps=' + str(inference.get('date_gaps', [])) + '.', secondary_reading(slot['arm'], slot['reference'], report, source)]
            if slot.get('a1_sentence'):
                lines.append(slot['a1_sentence'])
            if 'hln_t_p_two_sided' in slot:
                lines.append('CONF-A1 HLN t(n−1) two-sided p (declared sensitivity)=' + _number(slot.get('hln_t_p_two_sided')) + '.')
        if source == 'notice':
            unavailable = [r['arm'] + '−' + r['reference'] + ': ' + str(r.get('state')) + '; ' + str(r.get('reason', 'registered E3 input/completion gate')) for r in summary.get('secondary', []) if (r['arm'], r['reference']) in [('NPL', 'NP'), ('NPL', 'NPP')] and r.get('state') != 'COMPUTED_SECONDARY']
            lines += ['### E3 次要联合读法', e3_joint_reading(summary.get('e3_joint_state', 'E3_SECONDARY_JOINT_NOT_EVALUABLE'), secondary_reports, unavailable + stage_reasons)]
            if summary.get('e3_joint_day_rule'):
                lines.append(summary['e3_joint_day_rule'])
        lines.append('### 预注册敏感性与种子')
        seed_state = summary.get('seed_robustness', 'EXTRA_SEEDS_NOT_AVAILABLE')
        if seed_state == 'SEED_DIRECTION_INSTABILITY':
            lines.append(seed_state + ': The registered increment is sensitive to the learner seed.')
        elif seed_state == 'NO_OBSERVED_SEED_SIGN_REVERSAL':
            lines.append(seed_state + ': No sign reversal was observed across the registered computed seeds; this is not proof of seed invariance.')
        else:
            lines.append('EXTRA_SEEDS_NOT_AVAILABLE: ' + '; '.join(stage_reasons or ['no computed extra-seed paired predictions; retained input/budget/completion gate']) + '.')
        expected = [source + '__SEED_20260920.json', source + '__SEED_20260921.json', source + '__THREE_SEED_MEAN.json']
        expected += ([source + '__24h.json', source + '__first_L.json'] if source == 'news' else [source + '__first_L.json', 'notice__DROP_FIRST_SEVEN_DAYS.json'])
        names = {'24h': '24-hour saved-version window', 'first_L': 'first-L chunking', 'DROP_FIRST_SEVEN_DAYS': 'first-seven-notice-target-days exclusion (54 days, sealed predictions, no refit)', 'THREE_SEED_MEAN': 'the arithmetic mean of all three sealed predictions (not a p-value average)'}
        for filename in expected:
            path = root / filename
            suffix = filename[len(source) + 2:-5]
            name = 'learner seed ' + suffix[5:] if suffix.startswith('SEED_') else names[suffix]
            lines.append(SENSITIVITY.format(name=name))
            if not path.exists():
                slots = [x for x in summary.get('sensitivities', []) if x.get('name') == suffix or (suffix.startswith('SEED_') and x.get('seed') == int(suffix[5:]))]
                lines.append(filename + ': ' + str(slots or 'NOT_AVAILABLE_PAIRED_INPUT_OR_RESOURCE_GATE') + '; ' + '; '.join(stage_reasons or ['paired sealed input/completion gate']) + '.')
                continue
            inference = _saved_inference(root, path)
            lines.append(_link(path) + '; analysis role=' + str(inference.get('analysis_role', 'SECONDARY_SENSITIVITY')) + '; date gaps=' + str(inference.get('date_gaps', [])) + '.')
            for report in inference.get('reports', []):
                lines.append(secondary_reading(report['arm'], report['reference'], report, source))
                if 'primary_two_sided_holm_p' in report:
                    lines.append('Secondary fixed-family sensitivity Holm p=' + _number(report.get('primary_two_sided_holm_p')) + '; HAC7 sensitivity Holm p=' + _number(report.get('sensitivity_hac7_two_sided_holm_p')) + '; this is not the main-seed decision.')
        lines.append('### 描述性稳健性与完整产物')
        lines.append(DESCRIPTIVE)
        for suffix in ('CLIPPING', 'CONNECTED_SEVERE_EVENTS', 'REGION_HORIZON_MAE', 'DAILY_LOSSES'):
            path = root / (source + '__' + suffix + '.csv')
            if path.exists():
                lines.append(_link(path))
                if suffix in ('CLIPPING', 'CONNECTED_SEVERE_EVENTS'):
                    lines.append(_csv_table(path, pooled_only=(suffix == 'CLIPPING')))
            else:
                lines.append(path.name + ': NOT_AVAILABLE_SAVED_DESCRIPTIVE_ARTIFACT.')
        lines.append('Connected severe-event event-equal summary (descriptive): ' + str(summary.get('severe_events', 'not available')) + '.')
    lines += ['## 2025 固定验证（仅报告）', DESCRIPTIVE, _table(['arm', 'raw MAE', 'rows', 'role'], [[r.get('arm'), _number(r.get('mae')), r.get('rows'), r.get('role')] for r in summaries.get('validation_2025', [])]), _link(root / 'SCORE_REPORT.json', '2025 validation and all saved summary dispositions')]
    lines += ['## 输入覆盖、阶段状态与可追溯链接', DESCRIPTIVE]
    for identity in summaries.get('coverage_flow_files', []):
        path = identity.get('path') if isinstance(identity, dict) else identity
        if path:
            lines.append(_link(path) + ('; SHA256=' + identity.get('sha256', 'not recorded') if isinstance(identity, dict) else ''))
    lines += stage_reasons or ['All recorded execution stages COMPLETE.']
    for stage in summaries.get('stage_dispositions', []):
        receipt = stage.get('receipt_identity', {})
        if receipt.get('path'):
            lines.append(_link(receipt['path']) + '; ' + str(stage.get('state')))
    # Listing binary artifacts adds links only; no binary payload is read.
    for path in sorted(root.iterdir()):
        if path.is_file() and path.name not in ('REPORT_zh.md', 'SCORE_RECEIPT.json'):
            lines.append(_link(path))
    lines += _a1_lines(root, summaries)
    lines += ['## 结论范围', str(summaries.get('inference_limits', 'Historical conditional design; asymptotic covariance-stationarity DM assumptions; 214/61 days shorter than Lago test-year recommendation; nominal fixed-prediction intervals; no equivalence or mechanism identification.')), 'Both bootstrap intervals are nominal per contrast, conditional on sealed fitted predictions and the registered resampling design; they are not simultaneous family intervals or unconditional training-uncertainty intervals. There is no registered equivalence margin or equivalence test. Region/horizon, coverage, clipping, severe-event and 2025 validation diagnostics do not replace the pooled main-seed primary decisions.']
    output = root / 'REPORT_zh.md'
    output.write_text('\n\n'.join(lines) + '\n', encoding='utf-8')
    return output
