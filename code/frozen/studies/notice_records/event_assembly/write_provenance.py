'Save source hashes for notice record construction.'
import csv
from pathlib import Path
OUT=Path(__file__).resolve().parents[1]
PROJ=OUT.parents[2]
FILES={'parent':PROJ.parent/'notice_forecasting/nw_notices.py',
       'v2':PROJ/'notice_assembly/notice_event_records.py',
       'v3':PROJ/'studies/V3/assembler_v3/nw_notices_v3.py'}
rows=[]
def add(version,needle,field,origin,effect,final):
 p=FILES[version];lines=p.read_text().splitlines(); matches=[i for i,s in enumerate(lines,1) if needle in s]
 rows.append(dict(version=version,file=str(p),line=matches[0] if matches else '',code_anchor=needle,field=field,origin=origin,effect=effect,final_policy=final))
add('parent','reg = reg.loc[reg.is_relevant_operational','record existence','M463 official relevance and clock metadata','Defines common operational population and valid availability','KEEP unchanged population contract')
add('parent',"reg['available_utc'] =",'availability','Official M463 available_time_utc','As-of availability','KEEP')
add('parent',"reg['anchor_local'] =",'start,end','Official raw_time_local creation clock','Time-only publication-day and missing-year anchor','KEEP official clock anchor; remove old +12h heuristic')
add('parent',"start is not None and sp == 'time_only'",'start','Clock heuristic +12 hours relative to publication','Rolls past time-only starts to next day','REMOVE; final anchors literal clock to codebook day')
add('parent','start_utc = available_utc if start is None','start','Availability fallback','Invents absent physical start','Already removed by v2; remains removed')
add('parent','end_utc = start_utc + OPEN_ENDED','end','Fixed 24-hour fallback','Invents absent or contradictory end','Already removed by v2; remains removed')
add('parent','return start_utc, min(end_utc','end','Fixed seven-day cap','Clips explicit end','Already removed by v2; remains removed')
add('parent','kind = TYPE_KIND.get(r.notice_type','kind','Official notice type fallback','Fallback for unrecognized M331 kind','KEEP exact v2 fallback')
add('parent','if region not in REGIONS:','record existence','Code admits only five regional label tokens','Drops UNKNOWN and directional label windows','SET normalize label direction; retain UNKNOWN diagnostic')
add('v2',"if start is None:",'end','Parser conditional on start','Drops known end when start absent','SET independent endpoints')
add('v2',"if sp == 'time_only' and start < anchor_local",'start','Publication +12-hour heuristic','Rolls time-only start forward','REMOVE per final codebook normalization')
add('v2',"return start_utc, end_utc if end_utc > start_utc",'end','Ordering filter','Drops explicit non-increasing end','SET preserve literal contradictory values with diagnostic')
add('v2',"if re.search(r'\\breturn(?:ed)?",'status,cancel','Shared official title rule','Title return-to-service gives RECOVERY','KEEP: applied identically by v2 _status in both arms')
add('v2',"if lifecycle in ('CANCELLATION', 'CEASED')",'status,cancel','Shared title CANCEL_RULE plus M331 lifecycle','Title cancellation/ceased/no-longer status','KEEP shared title branch; M331 lifecycle retained')
add('v2',"if lifecycle == 'UPDATE' or re.search",'status','Shared title update rule plus M331 lifecycle','Title update gives UPDATE','KEEP shared title branch')
add('v2',"kind = ('CONSTRAINT' if r.notice_type",'kind','Official RECLASSIFY CONTINGENCY type','Maps this official type to CONSTRAINT','KEEP official metadata override')
add('v2','closing = _status(r.title, r.lifecycle)','record existence,region','Shared title status followed by source title/body region','No-window cancellation/recovery gets rule-made regional rows','REMOVE source regional fallback; only label CANCELLATION/CEASED gets UNKNOWN diagnostic')
add('v2',"for region in rule_regions(r.title, r.text)",'region,record existence','Title/body region parser','Creates regions for L closing record without M331 windows','REMOVE; not identical shared title content rule')
add('v2','offset = _llm_window_offset(r.text','quantity binding','Source body positions of label endpoints/evidence','Decides association of label MW values to windows','REMOVE source access; bind only saved label evidence')
add('v2',"candidates = [m.start() for m in pattern.finditer(text)]",'quantity binding','Source positions of quantity evidence','Locates saved quantity in original body','REMOVE; label-only evidence relation')
add('v2',"candidates = [m.start() for m in re.finditer",'quantity binding','Source MW-number fallback','Locates same numeric value when label evidence not found','REMOVE source number search')
add('v2','refs = _references(r.text)','references,event relation','Source body reference regex','Adds notice IDs absent a typed M331 reference field','REPLACE with same regex over GPT-selected saved label evidence only')
add('v2','key = _title_key(title)','event relation','Dated official title normalization','Allows unique dated-title or overlap relation','KEEP shared v2 _title_key; identical both arms')
add('v2','body_regions = _body_event_regions(r.text)','region compatibility,event relation','Source body event region','Controls citation compatibility and partial closures','REPLACE label region tokens only')
add('v2',"lor = re.search(r'\\bLOR",'topic compatibility,event relation','Source body LOR level','Controls whether cited notice has compatible topic','REPLACE saved label evidence only')
add('v2',"PARTIAL_SCOPE.search(r.text)",'relation scope','Source body partial-window wording','May limit reference closure to one region/kind','REMOVE L source scope rule; default EVENT')
add('v2',"REGION_RELEASE.search(r.text)",'relation scope','Source body all-regions release wording','May close all matching regional events','REMOVE L source scope rule; default EVENT')
add('v3','regions, rbasis, revidence, direction = source_regions','region','Source event-region fields/clauses, directions, title, body','Supplies fallback regions, directional expansion and conflict suppression','REMOVE from L; keep R own parser')
add('v3','category, source_kind, active_admission = source_category','kind,feature eligibility','Official type plus source negative/NRM wording','Overrides L kind, category and activity admission','REMOVE text-based L decisions; keep official MARKET SYSTEMS exclusion and v2 type policy')
add('v3','action, prospective, abasis, aevidence, aprecision = action_metadata','closing time,prospective closure','Source ACTION_RE','Adds physical action to both arms incl missing label endpoint','REMOVE from L; L closing time only from structured label endpoint')
add('v3','extracted = source_windows','start,end','Source interval/start grammar','Candidate shared endpoint recoveries','REMOVE L call')
add('v3',"source_region_conflict =",'region','Source body contradiction check','Suppresses recognized M331 region to UNKNOWN','REMOVE L source validation or correction')
add('v3',"s, offset, why, evidence = xs",'start','Source unique interval fallback','Recovers unknown/unparseable label start','REMOVE; set parsing of actual label string only')
add('v3',"e, why, evidence = xe",'end','Source unique interval/open-end fallback','Recovers missing end or repeats source further-notice phrase','REMOVE; label further-notice remains open')
add('v3',"windows = [(reg, source_kind, status, s, e, off, 'NO_M331_WINDOW'",'record existence,all core fields','Source-only windows and region','Creates entire L records when label has none','REMOVE')
add('v3',"refs = v2._references(r.text)",'references','Source body regex','Adds source citation IDs','REPLACE saved M331 evidence only')
add('v3',"ids = tuple(sorted(set",'event relation','Source exact NRM constraint IDs','Matches cancellation/update history by source constraint identifier','REPLACE saved M331 evidence only')
add('v3',"before = re.split(r'[.!?]', r.text",'start,end','Source relative-day context','Suppresses time-only label endpoint based on body tomorrow/yesterday','REMOVE L source suppression; preserve codebook anchor')
add('v3','negative = bool(NEGATIVE.search(r.text))','status,cancel,feature eligibility','Source negative-reserve sentence','Changes L status/cancel flag and excludes active evidence','REMOVE source negative rule from L')
add('v3',"if re.search(r'\\bwill",'status','Source body/title future close/resumption additions','Overrides M331 status for will-end/resumption and ended-period wording','REMOVE v3-only status additions from L; keep R')
add('v3',"if re.search(r'\\bceased",'status','Source body closing wording','Overrides M331 status on body ceased/cancellation','REMOVE from L; keep R')
with (OUT/'PROVENANCE_AUDIT.csv').open('w',newline='') as f:
 w=csv.DictWriter(f,fieldnames=rows[0].keys());w.writeheader();w.writerows(rows)
intro="# notice_records provenance audit\n\nThe audit is static and target-blind: it follows the parent NW assembler, the specified v2 overlay, and v3. Line anchors below point to read-only inputs. The CSV has one row per identified input-to-content path, including inherited parent behavior and v2 removals; it does not assert that all paths affect disjoint records.\n\n**Finding:** neither v2 nor v3 was strictly label-only. v2 sourced references, relation scope, source-region/topic compatibility and quantity binding from the body; its no-window closing fallback could also create regional L records. v3 additionally sourced L regions, endpoints, action times, status/category/admission decisions, constraint IDs and whole no-window records from source text. Fixing parsing loss alone would not remove these dependencies.\n\n**Allowed shared inputs kept:** M463 operational/valid-clock population selection, notice ID, AEMO official notice type, availability and official creation clock for the codebook anchor. The v2 `_status` title branches for return-to-service, cancellation/ceased/no-longer, and update are retained identically for R and L; `_title_key` retains its dated-title normalization for relation inference. The v2 official RECLASSIFY CONTINGENCY override and parent official-type fallback remain. No other title rule supplies an L region or time. The parent's title `direction/directed` kind rule applied only to R; it is not introduced into L.\n\n**Final L content input_checks:** the L assembly input_checks drops `text` before joining M331. Core region/kind/start/end come from structured label windows, status from label lifecycle plus the permitted v2 title rules. UNKNOWN remains UNKNOWN, missing start does not erase an end, directions in the label region enumerate their literal endpoints. No source window or source action function can run in L. A label cancellation/ceased lifecycle with no window yields only an UNKNOWN diagnostic; otherwise no label window means no event record. MW binding uses label evidence only; ambiguous binding stays unknown.\n\nM331 has no typed reference/constraint-ID/LOR field. Reference IDs and auxiliary constraint/LOR compatibility metadata may be parsed from **GPT-selected saved label evidence only**, not the original source. That provenance is explicit; it cannot recover information omitted from every label field. Evidence-only operational times/regions are not promoted into core rows under the separately frozen interpretation: they are reported as unstructured-label omissions, not falsely described as absent from the full label. A structured closing start/end is retained and duplicated as an action instant; no evidence-based future-action inference is added to L.\n\nThe v3 event-state resolver, 14-column feature function and +28-day placebo clock shift are copied unchanged and checked byte-for-byte in a synthetic unit test. Closing information can affect forecast states only once available. No forecasting model was fit or scored.\n\n| Version | Field(s) | Input path and effect | notice_records policy | Source line |\n|---|---|---|---|---|\n"
lines=[intro]
for r in rows:
 lines.append('| {version} | {field} | {origin}: {effect} | {final_policy} | `{file}:{line}` |'.format(**r))
(OUT/'PROVENANCE_AUDIT.md').write_text('\n'.join(lines)+'\n')
print('Static paths audited:',len(rows))
