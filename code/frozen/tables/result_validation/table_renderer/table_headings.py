'Define the table captions and column headings.'
import table_results_conf_results as F
PRIMARY_HEADERS={
 'primary_effects':r'Contrast & Days & Ref. MAE & $\Delta$ & Effect & One-day & Family one-day',
 'primary_tests':r'Contrast & Seven-day & Family seven-day & DM $p$ & Holm $p$ & HLN $p$ & HAC7 $p$',
 'primary_seeds':r'Contrast & Main seed & Extra seed 1 & Extra seed 2 & SD & Three-seed mean & Seed check'}
NEUTRAL_CAPTIONS={
 'primary_tests':'Primary uncertainty checks and test statistics.',
 'primary_seeds':'Primary seed estimates and checks.',
 'combinations':'Combination comparisons.', 'cheap':'Text comparator comparisons.',
 'secondary_news':'Secondary news comparisons.', 'secondary_notice':'Secondary notice comparisons.',
 'diagnostics':'Pipeline diagnostics.', 'clipping_news':'News clipping diagnostics.',
 'clipping_notice':'Notice clipping diagnostics.', 'execution':'Execution records.'}
def headings(table,record):
 key=table['id'];T=F.templates()
 if key=='primary_effects':
  marks=(F.load_summary_comparisons().TP7['table6_mark_nc'] if any(t['alert'] for t in record['tasks'].values()) else '')+(T['frozen_templates']['table6_mark_seven'] if any(c['class']!='NE' and F.seven_undefined(c) for t in record['tasks'].values() for c in t['contrasts']) else '')+(T['frozen_templates']['table6_mark_mc'] if any(c.get('mc_unresolved',False) for t in record['tasks'].values() for c in t['contrasts']) else '')
  caption=F.frozen_template('table6_caption',marks=marks,table_ref='\\ref{tab:main_comparisons-sensitivity}')
 elif key=='sensitivities':caption=F.strict_json(F.MS/'summary_comparisons_templates.json')['secondary']['sens_caption']
 else:
  F.require(key in NEUTRAL_CAPTIONS,'unregistered native table heading: '+key)
  caption=NEUTRAL_CAPTIONS[key]
  if key=='secondary_notice':caption+=F.load_summary_comparisons().TP7['s14_note']
 width=len(table['rows'][0]) if table['rows'] else 1
 header=PRIMARY_HEADERS.get(key,'Reading' if width==1 else ' & '.join('Column '+str(i+1) for i in range(width)))
 return caption,header

def validate(record):
 for table in record['source_tables']:
  expected=headings(table,record)
  F.require((table['caption'],table['header'])==expected,'native table heading must equal consumer-owned template: '+table['id'])
