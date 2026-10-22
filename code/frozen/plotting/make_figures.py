'Plot Figures 2–4 from saved comparisons and daily context series.'
from __future__ import annotations
import argparse, csv, hashlib, json, os, re, sys, tempfile
from datetime import date as calendar_date, timedelta
from pathlib import Path
sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
FIGURE3_JOB = ROOT / 'plot_checks'
QA_DIR = FIGURE3_JOB / 'qa'
QA_DIR.mkdir(parents=True, exist_ok=True)
os.environ['MPLCONFIGDIR'] = str(QA_DIR / 'mplconfig')
os.environ['XDG_CACHE_HOME'] = str(QA_DIR / 'cache')
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib import font_manager
from matplotlib.lines import Line2D
from matplotlib.patches import Rectangle, Patch
from matplotlib.backends import backend_pdf
import string
from matplotlib import ticker as mticker
import numpy as np
from frozen_context import load_context
DEFAULT_RESULTS = ROOT.parent / 'minrun_execution_20261010/t5_final/a13f/source_delivery_final/SCORE_ATTEMPT_DECLARED_ONLY/export/OFFICIAL_RESULTS.json'
EXPECTED_RESULTS_SHA256 = '7fce73ed9e11542e2ec7515e6448e37a4c12c9f60103bf5b899f908544b8b591'
ROLE_COLORS = {'Activity reference': '#222222', 'Event states': '#0072B2', 'Overlap components': '#00845F', 'Archive embeddings': '#B34E00', 'Fields': '#AA3377', 'Embeddings': '#946B00', 'Non-LLM representations': '#8C8C8C'}
TEXT = '#333333'
BORDER = '#555555'
GRAY = ROLE_COLORS['Non-LLM representations']
LABELS = {'N': 'No-text model', 'M': 'Activity reference', 'M_notice': 'Activity reference', 'L_count': 'Fields', 'L_chen': 'Embeddings', 'L14': 'Event states', 'L_Laz': 'Overlap components', 'L_chen_notice': 'Archive embeddings', 'E_raw': 'Raw embeddings', 'W2_D': 'Word frequencies', 'R': 'Rule parser', 'T': 'Word frequencies'}
COLORS = {arm: ROLE_COLORS[LABELS[arm]] for arm in ['L_count', 'L_chen', 'L14', 'L_Laz', 'L_chen_notice']}
LINESTYLES = {'L14': '-', 'L_Laz': (0, (3, 1.2)), 'L_chen_notice': '-', 'L_count': '-', 'L_chen': '-'}
PRIMARY = [0, 1, 2, 3, 4]
CONTROLS = [18, 31, 61, 62]
FIGURE_QA = {}
PLOTTED_CONTRASTS = []
WIDTH = 6.3
AUDIT_SCRIPTS = Path.cwd() / '.local/figure-audit/scripts'
sys.path.insert(0, str(AUDIT_SCRIPTS))

def style():
    arial = Path('/System/Library/Fonts/Supplemental/Arial.ttf')
    if arial.is_file():
        for name in ['Arial.ttf', 'Arial Bold.ttf', 'Arial Italic.ttf']:
            p = arial.parent / name
            if p.is_file():
                font_manager.fontManager.addfont(p)
        family = 'Arial'
    else:
        family = next((name for name in ['Helvetica', 'DejaVu Sans'] if any((f.name == name for f in font_manager.fontManager.ttflist))), 'DejaVu Sans')
    plt.rcParams.update({'font.family': 'sans-serif', 'font.sans-serif': [family], 'font.size': 8, 'axes.labelsize': 8, 'axes.titlesize': 8, 'xtick.labelsize': 8, 'ytick.labelsize': 8, 'legend.fontsize': 7.5, 'text.color': TEXT, 'axes.labelcolor': TEXT, 'xtick.color': TEXT, 'ytick.color': TEXT, 'axes.edgecolor': BORDER, 'axes.linewidth': 0.6, 'lines.linewidth': 1.25, 'xtick.major.size': 3, 'ytick.major.size': 3, 'axes.spines.top': False, 'axes.spines.right': False, 'legend.frameon': False, 'pdf.fonttype': 42, 'ps.fonttype': 42, 'svg.fonttype': 'none', 'savefig.facecolor': 'white', 'figure.facecolor': 'white', 'axes.facecolor': 'white', 'hatch.linewidth': 0.5, 'axes.unicode_minus': True, 'savefig.dpi': 300})
    FIGURE_QA['font_family'] = family
PDF_SALT = {'stem': ''}

def subset_psname(self, ps, cmap):
    digest = hashlib.sha1(f'{PDF_SALT['stem']}|{ps}'.encode()).digest()
    return ''.join((string.ascii_uppercase[b % 26] for b in digest[:6])) + '+' + ps
backend_pdf.PdfFile._get_subsetted_psname = subset_psname

def panel(ax, letter, title):
    ax.set_gid(letter)
    pos = ax.get_position()
    y = pos.y1 + 4 / (72 * ax.figure.get_size_inches()[1])
    anchor = max(0.012, pos.x0 - 0.125) if getattr(ax.figure, '_letter_by_column', False) else 0.012
    text = ax.figure.text(anchor, y, f'({letter})', fontsize=9, fontweight='normal', va='bottom')
    ax.figure._panel_labels = getattr(ax.figure, '_panel_labels', []) + [text]
    ax.set_title(title, loc='left', pad=4, fontweight='normal')

def save(fig, stem, **alignment_options):
    from audit_panel_alignment import require_matplotlib_panel_alignment
    assert abs(fig.get_size_inches()[0] - WIDTH) < 1e-12
    fig.canvas.draw()
    for text in fig.findobj(matplotlib.text.Text):
        if text.get_visible() and text.get_text():
            assert text.get_fontsize() >= 7.5, text.get_text()
    anchors = [t.get_position()[0] * WIDTH * 72 for t in getattr(fig, '_panel_labels', [])]
    for i, ax in enumerate(fig.axes):
        for j, other in enumerate(fig.axes):
            if i < len(anchors) and j < len(anchors) and (abs(ax.get_position().x0 - other.get_position().x0) < 1e-08):
                assert abs(anchors[i] - anchors[j]) < 1e-09
    report = require_matplotlib_panel_alignment(fig, json_out=QA_DIR / f'{stem}.alignment.json', strict=True, require_panel_labels=False, **alignment_options)
    FIGURE_QA.setdefault(stem, {}).update(alignment=report['verdict'], panel_letter_anchor_x_pt=anchors, panel_letter_anchor_check='PASS')
    PDF_SALT['stem'] = stem
    fig.savefig(HERE / f'{stem}.pdf', dpi=300, transparent=False, metadata={'Creator': 'make_figures.py', 'CreationDate': None, 'ModDate': None, **({'Producer': None} if stem == 'figure_3_primary_effects' else {})})
    fig.savefig(HERE / f'{stem}.png', dpi=300, transparent=False)
    plt.close(fig)

def date(s):
    return mdates.datestr2num(s)

def native(data, i):
    return data['rows'][i]['value']['native']

def figure2(price, activity):
    fig = plt.figure(figsize=(WIDTH, 4.8))
    gs = fig.add_gridspec(5, 1, left=0.115, right=0.97, bottom=0.105, top=0.92, height_ratios=[0.76, 0.56, 1, 0.9, 0.9], hspace=0.7)
    a1 = fig.add_subplot(gs[0])
    b = fig.add_subplot(gs[2])
    a2 = fig.add_subplot(gs[1], sharex=b)
    c1 = fig.add_subplot(gs[3], sharex=b)
    c2 = fig.add_subplot(gs[4], sharex=b)
    pos = a1.get_position()
    a1.set_position([pos.x0, pos.y0 + 1.4 / (72 * 4.8), pos.width, pos.height])
    panel(a1, 'a', 'Archive overview')
    fills = {'Training data': '#8C8C8C', 'Other archive': '#DDDDDD', 'Refitted daily': 'white', 'Gap': 'white'}

    def span(y, start, end, kind):
        x0, x1 = (date(start), date(end))
        a1.add_patch(Rectangle((x0, y), x1 - x0, 0.2, facecolor=fills[kind], edgecolor=BORDER, lw=0.5, hatch='////' if kind == 'Gap' else None))
    span(0.64, '2021-10-01', '2026-05-19', 'Training data')
    span(0.64, '2026-05-19', '2026-10-01', 'Refitted daily')
    span(0.1, '2021-10-01', '2026-10-01', 'Other archive')
    span(0.1, '2021-10-01', '2024-01-01', 'Training data')
    for lo, hi in [('2024-08-01', '2025-11-01'), ('2026-05-19', '2026-07-27')]:
        span(0.1, lo, hi, 'Gap')
    a1.text(date('2021-10-01'), 0.9, 'News archive', fontsize=8, va='bottom')
    a1.text(date('2021-10-01'), 0.34, 'Notice archive', fontsize=8, va='bottom')
    a1.annotate('evaluation window, refitted daily', (date('2026-07-25'), 0.84), xytext=(-22, 2), textcoords='offset points', fontsize=7.5, ha='right', va='bottom', arrowprops=dict(arrowstyle='-', color=BORDER, lw=0.5, shrinkA=2, shrinkB=0))
    a1.axvspan(date('2026-05-01'), date('2026-10-01'), color='#EEEEEE', zorder=-3)
    a1.set(xlim=(date('2021-07-01'), date('2026-10-01')), ylim=(0, 1.22), yticks=[])
    a1.spines['left'].set_visible(False)
    a1.xaxis.set_major_locator(mdates.YearLocator())
    a1.xaxis.set_major_formatter(mdates.DateFormatter('%Y'))
    a1.tick_params(axis='x', pad=1)
    a1.annotate('(b)–(e)', (date('2026-07-16'), 0), xycoords=a1.get_xaxis_transform(), xytext=(0, -14), textcoords='offset points', ha='center', va='top', fontsize=7.5, color=GRAY)
    fig.legend(handles=[Patch(facecolor=fills[k], edgecolor=BORDER, hatch='////' if k == 'Gap' else None, label=k) for k in ['Training data', 'Other archive', 'Gap']], loc='upper right', bbox_to_anchor=(0.98, 1), ncol=3, handlelength=1.15, columnspacing=1.2, fontsize=7.5)
    panel(a2, 'b', '2026 evaluation windows')
    for y, lo, label in [(0.58, '2026-05-19', 'News: 19 May–30 Sep'), (0.1, '2026-08-01', 'Notices: 1 Aug–30 Sep')]:
        a2.broken_barh([(date(lo), date('2026-10-01') - date(lo))], (y - 0.1, 0.46), facecolors='#DDDDDD')
        a2.annotate(label, (date(lo), y + 0.14), xytext=(2, 0), textcoords='offset points', fontsize=7.5, va='center')
    a2.set(ylim=(0, 1.4), yticks=[])
    a2.spines['left'].set_visible(False)
    cutoff = date('2026-05-18')
    a2.axvline(cutoff, color=BORDER, lw=0.65, ls='--')
    a2.annotate('Documented knowledge cutoff (18 May 2026)', (cutoff, 1.38), xytext=(3, 0), textcoords='offset points', ha='left', va='top', fontsize=7.5)
    panel(b, 'c', 'Daily price context')
    for task, col, label in [('news', '#555555', 'News: NSW1, QLD1, TAS1'), ('notice', GRAY, 'Notices: all five regions')]:
        series = price[task]
        b.plot([date(d) for d in series.index], series.to_numpy(), color=col, lw=1.05, label=label, ls=(0, (3, 1.5)) if task == 'notice' else '-', zorder=3 if task == 'notice' else 2)
    b.set_ylim(0, max((s.max() for s in price.values())) * 1.15)
    b.yaxis.set_minor_locator(mticker.NullLocator())
    b.yaxis.set_major_locator(mticker.MaxNLocator(3))
    b.set_ylabel('Mean price\n(AUD/MWh)', labelpad=4)
    b.legend(loc='upper right', bbox_to_anchor=(1, 1.49), ncol=2, handlelength=1.4, columnspacing=1.1, fontsize=7.5)
    for ax, task, letter, title, ylabel in [(c1, 'news', 'd', 'News: articles in the 72-h window at each 00:00 issue', 'Articles'), (c2, 'notice', 'e', 'Notices: arrivals per day', 'Notices')]:
        panel(ax, letter, title)
        series = activity[task]
        ax.plot([date(d) for d in series.index], series.to_numpy(), color='#222222', lw=0.9)
        ax.set_ylim(0, series.max() * 1.12)
        ax.set_ylabel(ylabel, labelpad=4)
        ax.yaxis.set_major_locator(mticker.MaxNLocator(3, integer=True))
    for ax in [b, c1, c2]:
        ax.axvspan(date('2026-08-01'), date('2026-10-01'), color='#F0F0F0', zorder=-2)
        ax.axvline(cutoff, color=BORDER, lw=0.65, ls='--', zorder=-1)
    b.set_xlim(date('2026-05-01'), date('2026-09-30'))
    b.set_xticks([date(f'2026-{m:02d}-01') for m in range(5, 10)] + [date('2026-09-30')])
    b.xaxis.set_major_formatter(mdates.DateFormatter('%-d %b'))
    for ax in [a2, b, c1]:
        ax.tick_params(labelbottom=False)
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    label_boxes = [t.get_window_extent(renderer).padded(fig.dpi / 72) for t in a2.texts]
    for month in range(6, 10):
        x = date(f'2026-{month:02d}-01')
        display_x = a2.transData.transform((x, 0))[0]
        holes = sorted(((max(0, a2.transAxes.inverted().transform((0, box.y0))[1]), min(1, a2.transAxes.inverted().transform((0, box.y1))[1])) for box in label_boxes if box.x0 <= display_x <= box.x1))
        ys = []
        start = 0
        for lo, hi in holes + [(1, 1)]:
            if lo > start:
                ys.extend([start, lo, np.nan])
            start = max(start, hi)
        a2.plot([x] * len(ys), ys, transform=a2.get_xaxis_transform(), color='#E6E6E6', lw=0.35, zorder=-3)
    a2.tick_params(axis='x', length=2, width=0.5)
    for tick in (a2.xaxis.get_major_ticks()[0], a2.xaxis.get_major_ticks()[-1]):
        tick.tick1line.set_visible(False)
    c2.set_xlabel('2026 (AEST)', labelpad=3)
    fig.align_ylabels([b, c1, c2])
    save(fig, 'figure_2_timeline', column_groups=[['a', 'b', 'c', 'd', 'e']])

def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def load_daily(data, score_root):
    'Check saved daily MAEs, then subtract and accumulate them.'
    series, audit = ({}, {'tolerance': 0.0, 'sources': {}, 'contrasts': []})
    receipt_path = score_root / 'R2_STATE/scored/SCORE_RECEIPT.json'
    for task, indices, start, end in [('news', [0, 1], '2026-05-19', '2026-09-30'), ('notice', [2, 3, 4], '2026-08-01', '2026-09-30')]:
        csv_path = receipt_path.parent / f'{task}__DAILY_LOSSES.csv'
        seed_path = score_root / 'numerical_evidence' / f'{task}__SENS35_LOSSES.json'
        source = {'csv': str(csv_path.resolve()), 'receipt': str(receipt_path.resolve()), 'seed_binding': str(seed_path.resolve())}
        audit['sources'][task] = source
        try:
            receipt = json.loads(receipt_path.read_text())
            if receipt['state'] != 'FROZEN_SCORE_COMPLETE':
                raise ValueError(' Score receipt is not complete ')
            receipt_hash = sha256(receipt_path)
            if any((data['rows'][i]['source_receipt_sha256'] != receipt_hash for i in indices)):
                raise ValueError(' Score receipt hash differs from the official export ')
            entries = [(j, e) for j, e in enumerate(receipt['files']) if Path(e['path']).name == csv_path.name]
            if len(entries) != 1:
                raise ValueError(' Score receipt lacks a unique daily  CSV  binding ')
            entry_index, entry = entries[0]
            csv_hash = sha256(csv_path)
            if csv_hash != entry['sha256'] or csv_path.stat().st_size != entry['bytes']:
                raise ValueError(' Daily  CSV  bytes ／ hash differs from the receipt ')
            source.update(csv_sha256=csv_hash, receipt_sha256=receipt_hash, receipt_pointer=f'/files/{entry_index}', seed_binding_sha256=sha256(seed_path))
            with csv_path.open(newline='') as f:
                rows = list(csv.DictReader(f))
            first, last = (calendar_date.fromisoformat(start), calendar_date.fromisoformat(end))
            days = [(first + timedelta(days=j)).isoformat() for j in range((last - first).days + 1)]
            if task == 'news' and receipt['evaluation_view']['issue_days'] != days:
                raise ValueError(" News dates differ from the score receipt's  R2 issue-day  window ")
            if [r['target_day'] for r in rows] != days:
                raise ValueError(' Daily dates differ from the continuous evaluation window （ no imputation ／ day deletion ／ or reordering ）')
            frozen = json.loads(seed_path.read_text())
            seed = frozen['series']['seed_20260919']
            if frozen['r2_score_receipt_sha256'] != receipt_hash or frozen['main_daily_csv_sha256'] != csv_hash or frozen['main_daily_csv_parity'] != 'PASS' or (seed['seeds'] != [20260919]) or (seed['days'] != days) or (seed['frozen_parity'] != 'PASS') or (seed['native_parity'] != 'PASS') or (seed['state'] != 'COMPUTED'):
                raise ValueError(' Main-seed arrays and daily  CSV  bindings differ ')
            if any((frozen['replay_binding']['numeric_source']['sha256'] != data['rows'][i]['timestamp_checks']['sha256'] for i in indices)):
                raise ValueError(' Main-seed source differs from the official export ')
        except (OSError, ValueError, KeyError) as exc:
            for i in indices:
                audit['contrasts'].append({'row': i, 'arm': native(data, i)['arm'], 'task': task, 'status': 'SKIPPED', 'reason': str(exc)})
            continue
        for i in indices:
            n = native(data, i)
            arm, reference = (n['arm'], n['reference'])
            check = {'row': i, 'task': task, 'arm': arm, 'reference': reference, 'official_pointer': f'/rows/{i}/value/native/mean_difference', 'official_mean_difference': n['mean_difference']}
            audit['contrasts'].append(check)
            try:
                arm_values = np.array([float(r[arm]) for r in rows])
                ref_values = np.array([float(r[reference]) for r in rows])
                if not (np.isfinite(arm_values).all() and np.isfinite(ref_values).all()):
                    raise ValueError(' Daily  MAE  contains nonfinite values ')
                for code, values in [(arm, arm_values), (reference, ref_values)]:
                    if not np.array_equal(values, np.asarray(seed['losses'][code])):
                        raise ValueError(f'{code}  differs from the main-seed arrays ')
                previous_differences = arm_values - ref_values
                mean = float(previous_differences.mean())
                error = abs(mean - n['mean_difference'])
                check.update(n_days=len(days), start=days[0], end=days[-1], daily_difference_mean=mean, absolute_error=error)
                if not np.isfinite(n['mean_difference']) or len(days) != n['n_days'] or error > audit['tolerance']:
                    raise ValueError(f' Day-count or mean check failed ； absolute mean error ={error:.17g}')
                differences = ref_values - arm_values
                previous_cumulative = np.cumsum(previous_differences)
                cumulative = np.cumsum(differences)
                assert np.array_equal(differences, -previous_differences)
                assert np.array_equal(cumulative, -previous_cumulative)
                check.update(status='PASS', cumulative_end=float(cumulative[-1]), previous_cumulative_end=float(previous_cumulative[-1]), sign_verification={'status': 'PASS', 'exact_negative': True, 'checked_days': len(days), 'maximum_absolute_sum': float(np.max(np.abs(cumulative + previous_cumulative)))})
                series[arm] = {'days': days, 'cumulative': cumulative, 'differences': differences, 'task': task}
            except (ValueError, KeyError) as exc:
                check.update(status='SKIPPED', reason=str(exc))
    return (series, audit)

def load_dayfirst_daily(data, score_root):
    'Read checked daily losses with the day-first Event states results.'
    series, audit = load_daily(data, score_root)
    assert len(series) == 5 and all((c['status'] == 'PASS' and c['absolute_error'] == 0 for c in audit['contrasts']))
    source = ROOT / 'dayfirst_analysis/results'
    hashes = {'figure4_daily_values.csv': 'fc1489c5e7249534666ef25e8288b7591969503e7654f131e837f2fdb8406272', 'daily_losses.csv': '05d7625a9cb333379d11c3ae5cc58a42bb8fbb3660ba0cb1c109b8021c514239'}
    tables = {}
    for name, digest in hashes.items():
        path = source / name
        assert sha256(path) == digest, f'Figure 4 source hash mismatch: {path}'
        with path.open(newline='') as stream:
            tables[name] = list(csv.DictReader(stream))
    tolerance = 1e-12
    checks = []
    for arm, old in series.items():
        task = old['task']
        reference = 'M_notice' if task == 'notice' else 'M'
        versions = {}
        for version in ('month-first', 'day-first'):
            rows = [r for r in tables['figure4_daily_values.csv'] if (r['version'], r['task'], r['arm']) == (version, task, arm)]
            assert [r['target_day'] for r in rows] == old['days']
            differences = np.array([float(r['reference_minus_representation_mae']) for r in rows])
            cumulative = np.array([float(r['cumulative']) for r in rows])
            assert np.isfinite(differences).all() and np.isfinite(cumulative).all()
            accumulation_error = float(np.max(np.abs(np.cumsum(differences) - cumulative)))
            assert accumulation_error <= tolerance, (arm, version, accumulation_error)
            versions[version] = (differences, cumulative)
        month_d, month_c = versions['month-first']
        day_d, day_c = versions['day-first']
        month_error = max(float(np.max(np.abs(month_d - old['differences']))), float(np.max(np.abs(month_c - old['cumulative']))))
        assert month_error <= tolerance, (arm, month_error)
        group = [r for r in tables['daily_losses.csv'] if r['task'] == task and r['seed'] == '20260919' and (r['group'] == 'original') and (r['placebo'] == 'False')]
        losses = {}
        for code in (arm, reference):
            rows = [r for r in group if r['arm'] == code]
            assert [r['target_day'] for r in rows] == old['days']
            losses[code] = np.array([float(r['daily_mae']) for r in rows])
            assert np.isfinite(losses[code]).all()
        difference = losses[reference] - losses[arm]
        loss_error = float(np.max(np.abs(difference - day_d)))
        cumulative_error = float(np.max(np.abs(np.cumsum(difference) - day_c)))
        assert max(loss_error, cumulative_error) <= tolerance, (arm, loss_error, cumulative_error)
        if arm == 'L14':
            series[arm] = dict(old, differences=day_d, cumulative=day_c)
        else:
            assert np.array_equal(day_d, month_d) and np.array_equal(day_c, month_c), arm
            assert series[arm] is old
        checks.append({'arm': arm, 'days': len(old['days']), 'month_first_maximum_error': month_error, 'daily_losses_maximum_error': loss_error, 'cumulative_maximum_error': cumulative_error, 'changed': arm == 'L14', 'cumulative_end': float(series[arm]['cumulative'][-1]), 'status': 'PASS'})
    audit['day_first'] = {'status': 'PASS', 'seed': 20260919, 'parsing': 'day-first', 'sources': hashes, 'absolute_tolerance': tolerance, 'checks': checks}
    (QA_DIR / 'figure4-source-checks.json').write_text(json.dumps(audit, indent=2) + '\n')
    with (FIGURE3_JOB / 'figure4_values.csv').open('w', newline='') as stream:
        writer = csv.writer(stream)
        writer.writerow(['task', 'arm', 'target_day', 'difference', 'cumulative'])
        for arm, values in series.items():
            writer.writerows(((values['task'], arm, d, x, y) for d, x, y in zip(values['days'], values['differences'], values['cumulative'])))
    return (series, audit)

def finalize_figures34_metadata():

    from io import BytesIO
    from pypdf import PdfReader, PdfWriter
    from PIL import Image
    path = HERE / 'figure_4_cumulative.pdf'
    reader = PdfReader(path)
    writer = PdfWriter(clone_from=reader)
    writer.metadata = None
    writer.add_metadata({'/Creator': 'make_figures.py'})
    assert '/Metadata' not in writer.root_object
    buffer = BytesIO()
    writer.write(buffer)
    final = PdfReader(BytesIO(buffer.getvalue()))
    assert final.pages[0].get_contents().get_data() == reader.pages[0].get_contents().get_data()
    assert final.metadata == {'/Creator': 'make_figures.py'}
    path.write_bytes(buffer.getvalue())
    for stem in ('figure_3_primary_effects', 'figure_4_cumulative'):
        png = HERE / f'{stem}.png'
        with Image.open(png) as preview:
            pixels = np.array(preview)
            dpi = preview.info['dpi']
        Image.fromarray(pixels).save(png, dpi=dpi)
        with Image.open(png) as preview:
            assert np.array_equal(pixels, np.array(preview))
            assert 'Software' not in preview.info
FIGURE3_CONTRACT = '- Figure 3 (seed-averaged decomposition): three aligned notice small multiples compare Original, Seven-day window and 24-hour window activity references; the full-width news panel has its own scale. Forecasts are averaged across seeds 20260919, 20260920 and 20260921 before losses are computed, as in the seed-averaged decomposition table of paper_source.md (Table 4).'
FIGURE3_DESIGN = '- Figure 3: #222222 diamonds show Activity step (M vs N); filled role-colour circles show Representation step (L vs M), and open role-colour circles show Net change (L vs N). Each circle pair is offset ±0.18 within its row and joined by the existing #D8D8D8 connector. Every marker has a solid 95% seven-day block-bootstrap interval in its colour. Notice columns share −0.90…+0.55%; news uses −10…+37%; no intervals are clipped and no numeric values appear beside markers. A single-row neutral-grey legend names the three steps. No non-LLM squares or individual-seed markers are drawn. Each task has a ← lower MAE cue; width 6.30 in, height 5.30 in.'

def figure3_rows():
    'Select seed-averaged comparisons and check Table 4 rounding.'
    sources = {'analysis1_comparisons.csv': '9a5a9ec3aafc187bd3fb057e6656c05d28c8804795319fef56802bfdc1aa90ba', 'analysis2_comparisons.csv': 'b146e39574f203a067744fc094fb956299ddf5f30d86f0cb6afef84cfdfdc736'}
    raw = []
    for name, digest in sources.items():
        path = ROOT / 'dayfirst_analysis/results' / name
        assert sha256(path) == digest, f'Figure 3 source hash mismatch: {path}'
        with path.open(newline='') as stream:
            for line, row in enumerate(csv.DictReader(stream), 2):
                if row['seed'] == 'mean':
                    raw.append(dict(row, source_file=str(path.relative_to(ROOT)), source_line=str(line), source_sha256=digest))
    paper = (ROOT / 'paper_source.md').read_text()
    match = re.search('\\*\\*Table (\\d+)\\.\\*\\* Activity step, representation step and net change with seed-averaged forecasts\\.(.*?)(?=\\*Notes\\.\\*)', paper, re.S)
    assert match, 'Seed-averaged decomposition table missing'
    assert match.group(1) == '4', 'Expected Table 4 of paper_source.md'
    table = match.group(2)
    expected = {}
    task = None
    representation = None
    for line in table.splitlines():
        if not line.startswith('|'):
            continue
        cells = [c.strip() for c in line.strip('|').split('|')]
        if cells[0] in ('*Notices*', '*News*'):
            task = 'notice' if cells[0] == '*Notices*' else 'news'
        elif task and cells[1] in ('Original', 'Seven-day window', '24-hour window', '72-hour counts'):
            representation = cells[0] or representation
            for step, cell in zip(('activity', 'representation', 'net'), cells[2:5]):
                value = re.match('([+−-]?\\d+\\.\\d+)', cell).group(1)
                expected[task, cells[1], representation, step] = value.replace('−', '-').lstrip('+')
    assert len(expected) == 33
    rows = []
    for task, activity_reference, analysis, arms, group in [('notice', 'Original', 'a1', ['L14', 'L_Laz', 'L_chen_notice'], 'original'), ('notice', 'Seven-day window', 'a2_w7', ['L14', 'L_Laz', 'L_chen_notice'], 'w7'), ('notice', '24-hour window', 'a2_w24', ['L14', 'L_Laz', 'L_chen_notice'], 'w24'), ('news', '72-hour counts', 'a1', ['L_count', 'L_chen'], 'original')]:
        candidates = [r for r in raw if r['task'] == task and r['analysis'] == analysis]
        assert len(candidates) == len(arms) * 3
        for arm in arms:
            for step in ('activity', 'representation', 'net'):
                matches = [r for r in candidates if r['representation'] == arm and r['step'] == step]
                assert len(matches) == 1, (task, analysis, arm, step)
                row = matches[0]
                assert row['representation_name'] == LABELS[arm]
                assert int(row['bootstrap_block_days']) == 7
                assert int(row['n_days']) == (61 if task == 'notice' else 135)
                assert row['arm_group'] == group
                assert row['reference_group'] == ('original' if step in ('activity', 'net') else group)
                activity_arm = 'M_notice' if task == 'notice' else 'M'
                assert row['arm'] == (activity_arm if step == 'activity' else arm)
                assert row['reference'] == (activity_arm if step == 'representation' else 'N')
                values = [float(row[k]) for k in ('delta_percent', 'interval95_low_percent', 'interval95_high_percent')]
                assert np.isfinite(values).all() and values[1] <= values[0] <= values[2]
                precision = 3 if task == 'notice' else 2
                table_value = expected[task, activity_reference, LABELS[arm], step]
                assert f'{values[0]:.{precision}f}' == table_value, (row, table_value)
                if step == 'activity':
                    duplicates = [r for r in candidates if r['step'] == 'activity']
                    keys = ('arm', 'reference', 'delta_percent', 'interval95_low_percent', 'interval95_high_percent', 'bootstrap_block_days', 'n_days')
                    assert all((all((r[k] == row[k] for k in keys)) for r in duplicates))
                    if arm != arms[0]:
                        continue
                rows.append(dict(row, activity_reference=activity_reference, row_label='Activity step' if step == 'activity' else LABELS[arm], table6_value=table_value))
    assert len(rows) == 26
    FIGURE3_JOB.mkdir(parents=True, exist_ok=True)
    fields = ['task', 'activity_reference', 'row_label', 'step', 'analysis', 'seed', 'arm', 'reference', 'delta_percent', 'interval95_low_percent', 'interval95_high_percent', 'bootstrap_block_days', 'n_days', 'table6_value', 'source_file', 'source_line', 'source_sha256']
    with (FIGURE3_JOB / 'figure3_values.csv').open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows)
    return rows

def figure3():
    rows = figure3_rows()
    PLOTTED_CONTRASTS[:] = rows
    fig = plt.figure(figsize=(WIDTH, 5.3))
    grid = fig.add_gridspec(2, 3, left=0.25, right=0.975, bottom=0.205, top=0.865, height_ratios=[4, 3], wspace=0.16, hspace=0.75)
    notices = [fig.add_subplot(grid[0, i]) for i in range(3)]
    news = fig.add_subplot(grid[1, :])
    panel(notices[0], 'a', 'Original')
    fig._panel_labels[-1].set_y(0.948)
    fig.text(0.25, 0.948, 'Notices', fontsize=8, va='bottom')
    for ax, key, title in zip(notices[1:], ['a-seven-day', 'a-24-hour'], ['Seven-day window', '24-hour window']):
        ax.set_gid(key)
        ax.set_title(title, loc='left', pad=4, fontweight='normal')
    panel(news, 'b', 'News')
    notice_names = ['Activity step', 'Event states', 'Overlap components', 'Archive embeddings']
    news_names = ['Activity step', 'Fields', 'Embeddings']
    geometry = []
    for ax, task, activity_reference, names, xlim, ticks in [*[(ax, 'notice', ref, notice_names, (-0.9, 0.55), [-0.8, -0.4, 0, 0.4]) for ax, ref in zip(notices, ['Original', 'Seven-day window', '24-hour window'])], (news, 'news', '72-hour counts', news_names, (-10, 37), [-10, 0, 10, 20, 30])]:
        selected = [r for r in rows if r['task'] == task and r['activity_reference'] == activity_reference]
        ax.axvline(0, color=GRAY, lw=0.65, zorder=0)
        for j, name in enumerate(names):
            y = len(names) - 1 - j
            pair = [r for r in selected if r['row_label'] == name]
            color = '#222222' if j == 0 else ROLE_COLORS[name]
            if j:
                rep = next((r for r in pair if r['step'] == 'representation'))
                net = next((r for r in pair if r['step'] == 'net'))
                ax.plot([float(rep['delta_percent']), float(net['delta_percent'])], [y + 0.18, y - 0.18], color='#D8D8D8', lw=0.5, zorder=1, solid_capstyle='round')
            for row in pair:
                yy = y + (0.18 if row['step'] == 'representation' else -0.18 if row['step'] == 'net' else 0)
                x, lo, hi = [float(row[k]) for k in ('delta_percent', 'interval95_low_percent', 'interval95_high_percent')]
                assert xlim[0] < lo <= x <= hi < xlim[1], row
                ax.plot([lo, hi], [yy, yy], color=color, lw=1.3, solid_capstyle='butt', zorder=2)
                ax.plot(x, yy, marker='D' if j == 0 else 'o', ls='', ms=4, mec=color, mfc='white' if row['step'] == 'net' else color, mew=0.9, zorder=4)
                geometry.append({'task': task, 'activity_reference': activity_reference, 'step': row['step'], 'row_label': name, 'x': x, 'y': yy, 'interval': [lo, hi], 'colour': color})
        ax.set_yticks(range(len(names) - 1, -1, -1), names if ax in (notices[0], news) else [])
        ax.tick_params(axis='y', length=0, pad=5)
        ax.spines['left'].set_visible(False)
        ax.set(xlim=xlim, ylim=(-0.6, len(names) - 0.4), xticks=ticks)
        ax.xaxis.set_major_formatter(mticker.FuncFormatter(lambda x, pos: f'{x:g}'.replace('-', '−')))
    centre = (notices[0].get_position().x0 + notices[-1].get_position().x1) / 2
    notice_bottom = notices[0].get_position().y0
    fig.text(centre, notice_bottom - 24 / (72 * 5.3), 'ΔMAE (%)', ha='center', va='top', fontsize=8)
    notices[0].annotate('← lower MAE', (0, 0), xycoords='axes fraction', xytext=(0, -24), textcoords='offset points', ha='left', va='top', fontsize=7.5)
    news.set_xlabel('ΔMAE (%)')
    news.annotate('← lower MAE', (0, 0), xycoords='axes fraction', xytext=(0, -27), textcoords='offset points', ha='left', va='top', fontsize=7.5)
    handles = [Line2D([], [], color=BORDER, marker='D', ls='', ms=4, label='Activity step (M vs N)'), Line2D([], [], color=BORDER, marker='o', ls='', ms=4, label='Representation step (L vs M)'), Line2D([], [], color=BORDER, marker='o', mfc='white', ls='', ms=4, label='Net change (L vs N)')]
    fig.legend(handles=handles, ncol=3, fontsize=7.5, loc='lower center', bbox_to_anchor=(0.5, 0.025), handlelength=1.0, columnspacing=1.2, handletextpad=0.5)
    assert fig._panel_labels[0].get_position()[0] == fig._panel_labels[1].get_position()[0]
    FIGURE_QA['figure_3_primary_effects'] = {'seed': 'mean (forecasts averaged before losses)', 'plotted_estimates': len(rows), 'table6_rounded_estimates': 'PASS (all 33 table cells, including repeated activity)', 'bootstrap_block_days': 7, 'clipped_intervals': 0, 'non_llm_squares': 0, 'size_inches': [WIDTH, 5.3], 'notice_xlim': [-0.9, 0.55], 'news_xlim': [-10, 37], 'panel_letter_anchor_check': 'PASS', 'geometry': geometry}
    save(fig, 'figure_3_primary_effects')
    (QA_DIR / 'figure_3_primary_effects.layout.json').write_text(json.dumps(FIGURE_QA['figure_3_primary_effects'], indent=2) + '\n')

def figure4(series, audit):
    fig = plt.figure(figsize=(WIDTH, 3.6))
    fig._letter_by_column = True
    gs = fig.add_gridspec(2, 2, left=0.105, right=0.965, bottom=0.15, top=0.87, wspace=0.42, hspace=0.66, width_ratios=[1.5, 1])
    a = fig.add_subplot(gs[:, 0])
    b = fig.add_subplot(gs[0, 1])
    c = fig.add_subplot(gs[1, 1], sharex=b)
    for ax, letter, title, arms, start in [(a, 'a', 'Notices', ['L14', 'L_Laz', 'L_chen_notice'], '2026-08-01'), (b, 'b', 'News: Fields', ['L_count'], '2026-05-19'), (c, 'c', 'News: Embeddings', ['L_chen'], '2026-05-19')]:
        panel(ax, letter, title)
        if ax is not a:
            fig._panel_labels[-1].set_x(ax.get_position().x0 - 0.045)
        ax.axhline(0, color=GRAY, lw=0.6, zorder=0)
        for arm in arms:
            s = series[arm]
            x = np.array([date(d) for d in s['days']])
            y = s['cumulative']
            ax.plot(np.r_[x[0] - 1, x], np.r_[0, y], color=COLORS[arm], ls=LINESTYLES[arm], lw=1.25)
            if ax is a:
                offsets = {'L14': 12, 'L_Laz': -21, 'L_chen_notice': 12}
                ax.annotate('Overlap\ncomponents' if arm == 'L_Laz' else LABELS[arm], (x[-1], y[-1]), xytext=(-5, offsets[arm]), textcoords='offset points', ha='right', va='center', fontsize=7.5, color=COLORS[arm], annotation_clip=False, arrowprops={'arrowstyle': '-', 'color': COLORS[arm], 'lw': 0.7})
        ax.set_xlim(date(start) - 1, date('2026-09-30'))
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%-d %b'))
        if ax is a:
            ax.set_xticks([date('2026-08-01'), date('2026-09-01'), date('2026-09-30')])
            ax.set_ylim(-0.45, 4.8)
        else:
            ax.set_xticks([date('2026-06-01'), date('2026-08-01'), date('2026-09-30')])
        cue = '↑ representation\nmore accurate' if ax is c else '↑ representation more accurate'
        cue_x, cue_y = (0.5, 0.28) if ax is c else (0.04, 0.14 if ax is b else 0.94)
        ax.text(cue_x, cue_y, cue, transform=ax.transAxes, fontsize=7.5, va='top')
    a.set_ylabel('Cumulative daily MAE difference (AUD/MWh)', labelpad=4)
    fig.text(0.59, 0.51, 'Cumulative daily MAE difference (AUD/MWh)', rotation=90, ha='center', va='center', fontsize=8)
    b.set_ylim(-520, 20)
    a.set_xlabel('2026 (AEST)')
    c.set_xlabel('2026 (AEST)')
    b.tick_params(labelbottom=False)
    s = series['L_count']
    jump = int(np.argmax(np.abs(np.diff(np.r_[0, s['cumulative']]))))
    assert s['days'][jump] == '2026-07-20'
    b.annotate('20 Jul', (date(s['days'][jump]), s['cumulative'][jump]), xytext=(-8, -14), textcoords='offset points', fontsize=7.5, ha='right', arrowprops={'arrowstyle': '->', 'lw': 0.6, 'color': COLORS['L_count']})
    save(fig, 'figure_4_cumulative')

def figure3_caption():
    return next((line for line in (ROOT / 'paper_source.md').read_text().splitlines() if line.startswith('> **[Figure 3:')))

def figure3_value_notes():
    number = re.search('\\*\\*Table (\\d+)\\.\\*\\* Activity step, representation step and net change with seed-averaged forecasts\\.', (ROOT / 'paper_source.md').read_text()).group(1)
    lines = ['', '### Figure 3 exact estimates and intervals', '', f'The seed-averaged decomposition is Table {number} in `paper_source.md`. Sources: `dayfirst_analysis/results/analysis1_comparisons.csv` (original notices and news) and `analysis2_comparisons.csv` (notice analyses `a2_w7` and `a2_w24`), selecting only `seed == "mean"`. Both source SHA-256 values are asserted. Evaluation-period notice timestamps use day-first parsing as the main version; only Event states plotted values change. These are seed-averaged forecasts, not averages of seed-level losses or estimates. All 33 Table 4 estimate cells are checked at its precision (three decimals for notices, two for news); repeated activity rows are checked for exact parity and drawn once per reference. The 26 plotted estimates and their intervals retain the source decimal strings in `plot_checks/figure3_values.csv`.', '', 'Every interval is read directly from `interval95_low_percent` / `interval95_high_percent`; every estimate is `delta_percent`; `bootstrap_block_days == 7` is asserted. No fitting, bootstrap draws or new inference. Intervals condition on fitted forecasts and omit training randomness; notices use 61 target days and news 135 issue days. No non-LLM squares, individual-seed markers, one-day intervals or values beside markers are drawn.', '', '**The steps combine multiplicatively: (1 + net/100) = (1 + activity/100)(1 + representation/100).** Net estimates and intervals are independently read from the source tables.', '', '| Task | Activity reference | Row | Step | Estimate % | Seven-day 95% interval % | Source / CSV line |', '|---|---|---|---|---:|---|---|']
    for r in PLOTTED_CONTRASTS:
        lines.append(f'| {r['task']} | {r['activity_reference']} | {r['row_label']} | {r['step']} | {r['delta_percent']} | [{r['interval95_low_percent']}, {r['interval95_high_percent']}] | `{r['source_file']}:{r['source_line']}` |')
    for name in ('analysis1_comparisons.csv', 'analysis2_comparisons.csv'):
        lines += ['', f'Source SHA-256 `{name}`: `{sha256(ROOT / 'dayfirst_analysis/results' / name)}`.']
    return lines

def update_figure3_notes():

    path = HERE / 'FIGURE_NOTES.md'
    text = path.read_text()
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.startswith('- Figure 3 ('):
            lines[i] = FIGURE3_CONTRACT
        elif line.startswith('- Figure 3:'):
            lines[i] = FIGURE3_DESIGN
        elif line.startswith('**Figure 3.') or line.startswith('> **[Figure 3:'):
            lines[i] = figure3_caption()
    text = '\n'.join(lines) + '\n'
    text = text.replace('Non-LLM methods use hollow #8C8C8C blocks/squares and activity uses #222222 diamonds in Figure 3.', 'Figure 3 uses #222222 activity diamonds and role-colour filled representation-step/open net-change circles; no non-LLM squares are shown. Its single-row legend uses neutral #555555 markers.')
    text = text.replace('reference-switch effects and cumulative figures are 4.80, 3.30, 5.00 and 3.60 in.', 'seed-averaged decomposition and cumulative figures are 4.80, 3.30, 5.30 and 3.60 in.')
    a = text.index('### Figure 3 exact estimates and intervals')
    b = text.index('### Figure 4 daily values', a)
    text = text[:a] + '\n'.join(figure3_value_notes()[1:]) + '\n\n' + text[b:]
    a = text.index('```json\n') + len('```json\n')
    b = text.index('\n```', a)
    qa = json.loads(text[a:b])
    qa['figure_3_primary_effects'] = FIGURE_QA['figure_3_primary_effects']
    qa['colour_checks']['redundant_encoding'] = qa['colour_checks']['redundant_encoding'].replace('filled/open circles, hollow non-LLM squares, activity diamonds', 'filled/open circles and activity diamonds in Figure 3 (no non-LLM squares)')
    qa['source_preflight']['warning_review'] = qa['source_preflight']['warning_review'].replace('all 16 contrasts use frozen seven-day intervals', 'all 26 Figure 3 estimates use the frozen seed-averaged seven-day intervals')
    text = text[:a] + json.dumps(qa, indent=2) + text[b:]
    text = text.replace('Figure 3 preserves intervals, sign-reversal connectors and reference/seed shape cues;', 'Figure 3 preserves seed-averaged intervals and light-grey connectors, with fill/shape encoding for all three steps;')
    text = text.replace('| 3a | Notice reference switches and controls | 61 paired days; 95% intervals; seven-day blocks | PASS | PASS | Hollow/filled points, connected sign reversals, lower-MAE cue |', '| 3a | Seed-averaged notices, three activity references | 61 paired days; 95% seven-day intervals | PASS | PASS | Shared scale, activity diamonds, filled/open circles, lower-MAE cue |')
    text = text.replace('| 3b | News reference switches and controls | 135 paired days; 95% intervals; seven-day blocks | PASS | PASS | Truncation endpoints, hollow squares, lower-MAE cue |', '| 3b | Seed-averaged news decomposition | 135 paired days; 95% seven-day intervals | PASS | PASS | Full intervals, activity diamond, filled/open circles, lower-MAE cue |')
    path.write_text(text)

def figure4_value_notes(daily, audit):
    lines = ['', '### Figure 4 daily values', '', 'Main version: day-first parsing of evaluation-period notice timestamps, seed 20260919. Event states uses the `version == "day-first"` rows of `dayfirst_analysis/results/figure4_daily_values.csv`, checked against original-group, non-placebo seed-20260919 daily MAEs in `dayfirst_analysis/results/daily_losses.csv`. Both SHA-256 values are asserted. Only Event states is replaced; the other four curves retain their exact frozen `load_daily()` arrays. All five month-first curves still pass the original receipt, source hash, seed-array, date, mean-difference and sign checks. Read-back checks against the earlier pandas CSV export use absolute tolerance 1e-12, zero relative tolerance; the original frozen checks remain exact.', '', '**Rising curves mean lower representation-model MAE.** Daily difference = activity-reference daily MAE minus representation daily MAE; plot the saved running sum, with a zero anchor one day before the window. No smoothing, rescaling, refitting or additional inference. The Fields annotation still selects its largest absolute daily change, 20 July 2026.', '', '| Arm | Main source | Days | Cumulative endpoint |', '|---|---|---:|---:|']
    for arm, values in daily.items():
        source = 'day-first figure4_daily_values.csv' if arm == 'L14' else 'frozen ' + values['task'] + '__DAILY_LOSSES.csv'
        lines.append(f'| {LABELS[arm]} | `{source}` | {len(values['days'])} | {values['cumulative'][-1]:.17g} |')
    for name, digest in audit['day_first']['sources'].items():
        lines += ['', f'Day-first source SHA-256 `{name}`: `{digest}`.']
    lines += ['', 'Detailed frozen provenance and day-first parity checks: `plot_checks/qa/figure4-source-checks.json`. Full plotted values: `plot_checks/figure4_values.csv`.', '', '### Figure 4 full plotted daily values', '', '| Day | Representation | Daily MAE reduction | Cumulative daily MAE difference (AUD/MWh) |', '|---|---|---:|---:|']
    for arm, values in daily.items():
        lines.append(f'| Zero anchor: {(calendar_date.fromisoformat(values['days'][0]) - timedelta(days=1)).isoformat()} | {LABELS[arm]} | — | 0 |')
        for day, delta, cumulative in zip(values['days'], values['differences'], values['cumulative']):
            lines.append(f'| {day} | {LABELS[arm]} | {delta:.17g} | {cumulative:.17g} |')
    return lines

def update_figures34_notes(daily, audit):
    update_figure3_notes()
    path = HERE / 'FIGURE_NOTES.md'
    text = path.read_text()
    text = re.sub('^Rebuild:.*$', f'Rebuild: `{ROOT.parents[3] / '.venv/bin/python'} -B figures/make_figures.py` (Matplotlib 3.11.1, matching the day-first reference job).', text, flags=re.M)
    text = text.replace('All five daily series pass exact frozen seed-array parity', 'All five month-first daily series pass exact frozen seed-array parity')
    a = text.index('### Figure 4 daily values')
    b = text.index('## Captions', a)
    text = text[:a] + '\n'.join(figure4_value_notes(daily, audit)[1:]) + '\n\n' + text[b:]
    a = text.index('```json\n') + len('```json\n')
    b = text.index('\n```', a)
    qa = json.loads(text[a:b])
    qa['figure_4_cumulative'] = FIGURE_QA['figure_4_cumulative']
    text = text[:a] + json.dumps(qa, indent=2) + text[b:]
    path.write_text(text)

def write_notes(results, daily, audit, price, activity, context):
    lines = ['# Figure notes', '', f'Rebuild: `{ROOT.parents[3] / '.venv/bin/python'} -B figures/make_figures.py` (Matplotlib 3.11.1, matching the day-first reference job).', '', '## Figure contracts and presentation', '', '- Figure 2 (quantitative context): the two scored windows differ in price and document context. Panel a establishes the archive context; b aligns the 2026 windows with c (linear price context), d (72-hour article counts) and e (notice arrivals).', FIGURE3_CONTRACT, '- Figure 4 (asymmetric time-series grid): notice gains accumulate gradually while news Fields is sensitive to a single daily change; separate news scales preserve visibility.', '', 'All PDFs are exactly **6.30 in wide**, exported without cropping, for scale-1.0 inclusion. Heights for the timeline, seed-averaged decomposition and cumulative figures are 4.80, 5.30 and 3.60 in. PNG previews are 300 dpi (1,890 px wide); the authoritative PDF has no raster images. Arial regular and bold are specified from the system fonts; TrueType embedding uses `pdf.fonttype=42`. Rendered glyph floor 7.5 pt, body/axes 8 pt, panel labels 9 pt regular, parenthesized (a), (b), etc. Labels are `fig.text`, 4 pt above each panel and aligned with the left edge of its content; the Figure 4 right column has its own shared content anchor. The upstream alignment auditor cannot discover figure-level letters, so their physical x anchors are independently asserted within each column; plot rectangles pass its unchanged 1.5 pt tolerance.', '', 'Palette: Fields #AA3377; news Embeddings #946B00; Event states #0072B2; Overlap components #00845F; Archive embeddings #B34E00. Figure 3 uses #222222 activity diamonds and role-colour filled representation-step/open net-change circles; no non-LLM squares are shown. Its single-row legend uses neutral #555555 markers. Every text element is #333333, except the explicitly requested Figure 4 endpoint labels, which match their line colours and meet 4.5:1 contrast. Contrast against white is checked for all semantic marks (minimum 3:1); neutral background shading and the light-grey dumbbell connector are subordinate guides, with darker semantic points and intervals laid over them. Dashed lines distinguish the Figure 2 documented cutoff, notice price series (3, 1.5), extraction failure counts in Figure 2, and Figure 4 Overlap components (3, 1.2). Each Figure 3 estimate has one solid 95% seven-day block-bootstrap interval; Figure 2 activity facets have neither dashes nor markers.', '', 'PDF font-subset tags use SHA-1 of figure stem plus PostScript font name, mapped to six uppercase letters. The PdfFile hook is set before every save. The final PDF audit checks all tags across figures are distinct, all fonts embedded, no Type 3 fonts, and no raster XObjects.', '', '', '## IJF convention alignment (15 October 2026)', '', '- Figure 2: regular parenthesized panels (a)–(e) show archive overview, 2026 evaluation windows, daily price, news activity and notice activity. Definitions are in d/e titles; their short y-labels align with c. Archive shading marks the May–September 2026 zoom. The Gap legend and bars share the same hatch. QA bounds only the three repeating Gap pattern tiles by their actual PDF clip rectangles; all text, borders and other paths retain the upstream checks. Notice prices are dashed on top of solid news prices. The documented cutoff is dashed in panels (b)–(e), with its full label once at the top of (b).', FIGURE3_DESIGN, '- Figure 4: curves are solid except Overlap components. The y-title Cumulative daily MAE difference (AUD/MWh) appears once per column, shared across the right panels. Width ratios are 1.5:1 with wspace 0.42. Right-aligned endpoint labels are inside the notice axes in their line colours. The 20 July Fields annotation points to the drop inside its panel. Label offsets and y-limits are mirrored for the reversed sign.', '', '## Frozen timestamp_checks and provenance', '', f'Official export: `{results.relative_to(ROOT.parent)}`; unchanged SHA-256 gate **{EXPECTED_RESULTS_SHA256}**.', f'Score receipt SHA-256: `{audit['sources']['news']['receipt_sha256']}`. All five month-first daily series pass exact frozen seed-array parity and **zero** mean-difference error. The day-first Event states source is checked separately below. No rows are inserted, removed or interpolated from daily loss series.', '', '### Figure 2 source chain', '', 'The score receipt binds the sealed prediction/truth/feature manifest. Each used source is hashed and byte-count checked where supplied. The following paths are relative to the study preparation directory (two levels above this manuscript directory).', '', '| Frozen file | SHA-256 | Binding |', '|---|---|---|']
    for e in context['sources']:
        p = Path(e['path'])
        try:
            p = p.relative_to(ROOT.parent.parent)
        except ValueError:
            pass
        lines.append(f'| `{p}` | `{e['sha256']}` | {e['binding']} |')
    lines += ['', 'Price mapping: main seed 20260919 activity-arm predictions are restricted to the primary window and joined one-to-one to frozen truth `y` (the scorer’s y_true) on `origin, target_time, region, horizon`. Daily arithmetic means pool scored keys by `target_day`, with no axis transform. These are descriptive prices, not forecast errors. News: 9,720 keys = 135 × 24 hours × 3 regions (NSW1, QLD1, TAS1). Notices: 527,040 keys = 61 × 288 five-minute targets × 5 regions × 6 horizons; 87,840 distinct target-time/region pairs. Equal horizon replication does not change the daily mean. Both joins are complete; reconstructed activity-arm daily MAE agrees with frozen daily loss CSVs within 1e−12 AUD/MWh.', '', 'Panel c uses a linear AUD/MWh axis with no minor ticks. Two pooled task series are directly keyed by region sets; individual regional means are not implied. The daily values and source mapping are unchanged.', '', 'News counts: frozen `news_coverage.jsonl` `/clock_admitted` at each 00:00 AEST origin, with `/source_ids` cardinality parity. The three regional rows have identical source sets; they are counted once per issue, not added. Every count also matches the frozen M extras array’s `article_count`. The union is **207 distinct IDs**; first appearances by month are 12, 44, 68, 53, 30. Daily 72-hour counts sum to **617 appearances**, because the same article may recur at successive issues. Thus 617 is not a unique-article census and is not directly comparable with notice arrivals. Articles first published earlier can be admitted via later saved versions; publication month is not the plotting clock.', '', 'Notice arrivals: deduplicate the frozen derived-date sidecar `/original` by `notice_id`, require identical `derived_dates/available_utc` for repeated event windows, convert to fixed UTC+10 (AEST), and count by admission day. Zero-arrival dates are explicitly retained within the 61-day window. Total **725** (August 259; September 466), exactly equal to official `/rows/337/value/human_review/extraction_failure/by_month/notice/<month>/counts/population`. These are source-admission counts, not parsed event dates; the as-run event-date defect does not alter this census. The clock remains a proxy for availability.', '', 'Panel a date boundaries follow the requested archive/window specification and the frozen evaluation dates. Archive spans are half-open drawing intervals; inclusive gaps Aug 2024–Oct 2025 and 19 May–26 Jul 2026 end at 1 Nov 2025 and 27 Jul 2026. The notice bank Oct 2021–Dec 2023 is dark grey, other archived spans light grey, gaps hatched. Expanding news training continues through daily refits from 19 May, shown white with a dark border and keyed as Refitted daily. Timeline timestamp_checks: the feature manifest binds `FREEZE.json`, which binds `DESIGN_CONFIG.json` (`news/preprocessing_train`, `news/refit`, `notice/training_nominal_months`, `notice/target_days`) and `STUDY_DESIGN.md` §4 (archived periods Oct 2021–Jul 2024 and Nov 2025–Feb 2026). The sidecar has no admissions inside either requested inclusive archive gap. The primary news window is bound to the R2 score receipt `/evaluation_view/issue_days`. The documented 18 May cutoff comes from the timestamp-bound `MODEL_CUTOFF_RECORD.json` `/records/gpt-6-luna/knowledge_cutoff`, reached via official numerical timestamp_checks `/operational/timestamps/T5/files`. It is a contextual vendor statement, not a verified executed-model knowledge input_checks.', '', 'Every plotted daily context value follows (full precision retained in the script). A dash means outside that task’s requested window, not zero.', '', '| Day (AEST) | News mean price | Notice mean price | News 72-hour count | Notice arrivals |', '|---|---:|---:|---:|---:|']
    for day in sorted(set(price['news'].index) | set(price['notice'].index)):
        cells = [format(s[day], '.17g') if day in s.index else '—' for s in [price['news'], price['notice'], activity['news'], activity['notice']]]
        lines.append('| ' + day + ' | ' + ' | '.join(cells) + ' |')
    lines += ['', '']
    lines += figure3_value_notes()
    lines += figure4_value_notes(daily, audit)
    lines += ['', '## Captions (each ≤80 words)', '', '**Figure 2. Data windows and daily context.** a Archive overview: training data, other archive, daily refits and hatched gaps; light shading identifies the May–September 2026 zoom. b Evaluation windows and documented cutoff. c Linear daily mean scored target prices; notice prices are dashed. d News articles in each 72-hour window at 00:00 AEST. e Notice arrivals per admission day. Context shading marks the notice window. Repeated news appearances are counted; 207 distinct articles and 725 notices are admitted.', '', '', figure3_caption(), '', '**Figure 4. Cumulative paired daily MAE differences.** Primary seed 20260919. a Notice representations; b News Fields; c News Embeddings, with separate news scales. Curves sum activity-reference daily MAE minus representation daily MAE; rising indicates lower MAE. Interior endpoint labels identify notice representations; Overlap components uses short dashes. The 20 July annotation marks Fields’ largest absolute daily change. Curves use fixed saved forecasts and carry no additional inference.', '', '', '## Automated QA and visual review', '', f'QA diagnostics: `{QA_DIR}`. `figure-audit` panel-alignment tolerance is 1.5 pt; the fresh JSON reports are retained there. All plots preserve full vector paths and selectable embedded TrueType PDF text. The figure-specific PDF, PNG and layout results follow.', '', '```json', json.dumps(FIGURE_QA, indent=2), '```', '', 'Final visual inspection covers every panel in colour, Machado-2009 deuteranopia and luminance greyscale. Figure 2 separates distinct count definitions and avoids marker clutter; Figure 3 preserves seed-averaged intervals and light-grey connectors, with fill/shape encoding for all three steps; Figure 4 retains direct notice labels and the overlap dash in greyscale. Light-grey connectors are auxiliary guides, not effect marks. Full numerical and frozen-source checks pass; source-preflight warnings are resolved in the QA record above.']
    lines += [f"\n## Final panel-by-panel QA\n\n| Panel | Evidence role / summary | Uncertainty / unit | Alignment | Collision | Visual checks |\n|---|---|---|---|---|---|\n| 2a | Archive coverage, training and gaps | Descriptive date spans; no CI | PASS | PASS | Annual ticks, Refitted daily key, lane labels |\n| 2b | Scored windows and cutoff | Frozen calendar boundaries; no CI | PASS | PASS | Shared 2026 axis, dashed cutoff with one top label |\n| 2c | Daily target-price arithmetic means | Scored keys pooled by day; no CI | PASS | PASS | Linear scale, units, dashed cutoff and notice band |\n| 2d | News activity at issue time | Articles in 72 h at 00:00 AEST; no CI | PASS | PASS | Separate count definition, solid line, no markers |\n| 2e | Notice admissions | Unique notice IDs per admission day; no CI | PASS | PASS | Separate count definition, zeros retained |\n| 3a | Seed-averaged notices, three activity references | 61 paired days; 95% seven-day intervals | PASS | PASS | Shared scale, activity diamonds, filled/open circles, lower-MAE cue |\n| 3b | Seed-averaged news decomposition | 135 paired days; 95% seven-day intervals | PASS | PASS | Full intervals, activity diamond, filled/open circles, lower-MAE cue |\n| 4a | Accumulating notice increments | Fixed seed 20260919 daily sums; no new interval | PASS | PASS | Observed date span, interior labels, short overlap dash |\n| 4b | Accumulating Fields differences | Fixed seed 20260919 daily sums; no new interval | PASS | PASS | Own units/scale, 20 July drop annotated inside panel |\n| 4c | Accumulating Embeddings differences | Fixed seed 20260919 daily sums; no new interval | PASS | PASS | Own units/scale, solid higher-contrast line |\n\nAll panels were inspected in colour, deuteranopia and greyscale. The combined audit has zero collision FAILs and zero WARNs. The minimum semantic-mark contrast is {min((c['white_contrast'] for c in FIGURE_QA['colour_checks']['palette'].values())):.3f}:1; all {FIGURE_QA['subset_tags']['unique_tag_count']} font subset tags are unique. The paper uses vector PDF figures and PNG previews.\n"]
    (HERE / 'FIGURE_NOTES.md').write_text('\n'.join(lines) + '\n')

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--results', type=Path, default=DEFAULT_RESULTS)
    p.add_argument('--score-root', type=Path)
    p.add_argument('--figures-3-4-only', action='store_true', help='Generate day-first Figures 3 and 4; preserve every other figures/ file except their notes')
    p.add_argument('--figure3-only', action='store_true', help='Generate seed-averaged Figure 3 and amend only its notes; preserve every other figures/ file')
    args = p.parse_args()
    if args.figures_3_4_only:
        assert not args.figure3_only
        changed = {'figure_3_primary_effects.pdf', 'figure_3_primary_effects.png', 'figure_4_cumulative.pdf', 'figure_4_cumulative.png', 'FIGURE_NOTES.md'}
        preserved = {str(p.relative_to(HERE)): sha256(p) for p in HERE.rglob('*') if p.is_file() and str(p.relative_to(HERE)) not in changed}
        assert sha256(args.results) == EXPECTED_RESULTS_SHA256
        data = json.loads(args.results.read_text())
        score_root = args.score_root or args.results.parent.parent
        daily, audit = load_dayfirst_daily(data, score_root)
        style()
        figure3()
        figure4(daily, audit)
        finalize_figures34_metadata()
        from figure_qa import run_qa
        passed = run_qa(HERE, ROOT, QA_DIR, AUDIT_SCRIPTS, FIGURE_QA, stems=['figure_3_primary_effects', 'figure_4_cumulative'])
        assert passed, 'Repair Figures 3/4 rendered collisions before delivery'
        update_figures34_notes(daily, audit)
        after = {str(p.relative_to(HERE)): sha256(p) for p in HERE.rglob('*') if p.is_file() and str(p.relative_to(HERE)) not in changed}
        assert after == preserved, 'A file outside Figures 3/4 and their notes changed'
        (QA_DIR / 'preservation-on-generation.json').write_text(json.dumps({'status': 'PASS', 'scope': 'Every file recursively under figures/ except Figures 3/4 PDF/PNG and FIGURE_NOTES.md', 'file_count': len(preserved), 'sha256': preserved}, indent=2) + '\n')
        print('Generated day-first Figures 3 and 4 only; every other figures/ file byte-identical.')
        return
    if args.figure3_only:
        changed = {'figure_3_primary_effects.pdf', 'figure_3_primary_effects.png', 'FIGURE_NOTES.md'}
        preserved = {str(p.relative_to(HERE)): sha256(p) for p in HERE.rglob('*') if p.is_file() and str(p.relative_to(HERE)) not in changed}
        style()
        figure3()
        from figure_qa import run_qa
        passed = run_qa(HERE, ROOT, QA_DIR, AUDIT_SCRIPTS, FIGURE_QA, stems=['figure_3_primary_effects'])
        assert passed, 'Repair Figure 3 rendered collisions before delivery'
        update_figure3_notes()
        after = {str(p.relative_to(HERE)): sha256(p) for p in HERE.rglob('*') if p.is_file() and str(p.relative_to(HERE)) not in changed}
        assert after == preserved, 'A file outside Figure 3 and its notes changed'
        (QA_DIR / 'preservation-on-generation.json').write_text(json.dumps({'status': 'PASS', 'scope': 'Every file recursively under figures/ except Figure 3 PDF/PNG and FIGURE_NOTES.md', 'file_count': len(preserved), 'sha256': preserved}, indent=2) + '\n')
        print('Generated Figure 3 only; every other figures/ file byte-identical.')
        return
    if sha256(args.results) != EXPECTED_RESULTS_SHA256:
        raise ValueError('Results file does not match the frozen official export SHA-256')
    data = json.loads(args.results.read_text())
    score_root = args.score_root or args.results.parent.parent
    daily, audit = load_dayfirst_daily(data, score_root)
    assert len(daily) == 5 and all((c['status'] == 'PASS' and c['absolute_error'] == 0 for c in audit['contrasts']))
    price, activity, context = load_context(score_root, data)
    style()
    figure2(price, activity)
    figure3()
    figure4(daily, audit)
    finalize_figures34_metadata()
    from figure_qa import run_qa
    passed = run_qa(HERE, ROOT, QA_DIR, AUDIT_SCRIPTS, FIGURE_QA)
    write_notes(args.results, daily, audit, price, activity, context)
    print('Temporary QA reports:', QA_DIR)
    if not passed:
        raise RuntimeError('Repair rendered collisions before delivery')
    print('Generated three 6.30-inch vector PDFs and 300-dpi PNGs.')
if __name__ == '__main__':
    main()
