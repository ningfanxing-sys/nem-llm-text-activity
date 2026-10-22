'Acquire the source article inventory.'
from pathlib import Path
import ast,datetime as dt,hashlib,json,subprocess,time,urllib.parse,urllib.robotparser,shutil,csv,sys,collections
HERE=Path(__file__).resolve().parent
PROJ=HERE.parents[3]
LAMP=PROJ.parent.parent
RAW=HERE/'raw'; RAW.mkdir(exist_ok=True)
UA='ResearchSourceInventory/1.0 (public academic source collection; polite 2-second interval)'
START='2026-02-01'; END='2026-09-30'

def now(): return dt.datetime.now(dt.timezone.utc).isoformat()
def log(path=None,url=None,operation='read',**kw):
 with (HERE/'OPENED.jsonl').open('a') as fh: fh.write(json.dumps(dict(utc=now(),path=str(Path(path).resolve()) if path else None,url=url,operation=operation,**kw))+'\n')
def read_json(path):
 log(path,operation='read_json_metadata')
 with Path(path).open() as f: return json.load(f)
def hash_file(path):
 log(path,operation='opaque_byte_hash')
 h=hashlib.sha256()
 with Path(path).open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
 return h.hexdigest()
def write_json(path,obj):
 Path(path).write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n')
def download(url,name,receipts,delay=2):
 global last_req
 wait=delay-(time.monotonic()-last_req)
 if wait>0:time.sleep(wait)
 if shutil.disk_usage(HERE).free<3*1024**3: raise RuntimeError('disk reserve below 3 GiB')
 started=now(); path=RAW/name
 if path.exists(): path=RAW/(dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')+'_'+name)
 headers=path.with_name(path.name+'.headers')
 log(url=url,operation='remote_download_attempt',destination=str(path),started_utc=started)
 result=subprocess.run(['/usr/bin/curl','--silent','--show-error','--location','--connect-timeout','15','--max-time','100','-A',UA,'--dump-header',str(headers),'--output',str(path),'--write-out','%{http_code}',url],text=True,capture_output=True)
 last_req=time.monotonic(); completed=now()
 log(url=url,operation='remote_download_result',http_status=result.stdout[-3:] if result.stdout else None,returncode=result.returncode,finished_utc=completed,error=result.stderr.strip()[:500])
 entry={'url':url,'local_path':str(path),'size_bytes':path.stat().st_size if path.exists() else 0,'sha256':hash_file(path) if path.exists() else None,'started_utc':started,'capture_utc':completed,'http_status':result.stdout[-3:] if result.stdout else None,'returncode':result.returncode,'headers_path':str(headers),'headers_sha256':hash_file(headers) if headers.exists() else None,'error':result.stderr.strip()[:500]}
 receipts.append(entry); write_json(HERE/'DOWNLOAD_RECEIPT.json',{'downloads':receipts,'source':'WattClarity'})
 log(path,operation='read_remote_response'); body=path.read_bytes() if path.exists() else b''
 log(headers,operation='read_remote_headers'); head=headers.read_text(errors='replace') if headers.exists() else ''
 return entry,body,head

last_req=0.0
if __name__=='__main__':
 log(__file__,operation='execute_code')
 receipts=read_json(HERE/'DOWNLOAD_RECEIPT.json')['downloads'] if (HERE/'DOWNLOAD_RECEIPT.json').exists() else []
 entry,body,head=download('https://wattclarity.com.au/robots.txt','robots.txt',receipts)
 write_json(HERE/'ROBOTS_STATUS.json',dict(entry=entry,body_sha256=entry['sha256']))
 print(json.dumps({'robots_http_status':entry['http_status'],'robots_returncode':entry['returncode'],'robots_bytes':entry['size_bytes'],'robots_text':body.decode(errors='replace')[:5000]}))

if __name__=='__main__':

 freeze=read_json(HERE/'FREEZE.json')
 if hash_file(HERE/'READING_SPEC.md')!=freeze['spec_sha256']: raise RuntimeError('reading rule hash mismatch')
 normalizer_path=PROJ/'studies/news_extraction/prepare_articles.py'
 log(normalizer_path,operation='read_frozen_html_normalization_code')
 source=normalizer_path.read_text(); tree=ast.parse(source)
 nodes=[n for n in tree.body if isinstance(n,(ast.ClassDef,ast.FunctionDef)) and n.name in ['_Plain','plain','article_text']]
 env={}; exec('from html.parser import HTMLParser\n'+ast.unparse(ast.Module(body=nodes,type_ignores=[])),env)
 plain=env['plain']; article_text=env['article_text']

 manifest_path=PROJ/'studies/NEWS2/A/source_manifest.csv'
 log(manifest_path,operation='read_source_paths')
 with manifest_path.open(newline='') as f: source_rows=list(csv.DictReader(f))
 libraries={}
 for name,suffix in [('M917','m917_wattclarity_source_2016_2024/raw_posts.json'),('M162','m162_wattclarity_llm_source_expansion/wattclarity_wp_posts_raw.json')]:
  found=[x for x in source_rows if x['source_path'].endswith(suffix)]
  if len(found)!=1:raise RuntimeError('source path ambiguity '+name)
  libraries[name]={'path':Path(found[0]['source_path']),'expected_sha256':found[0]['sha256']}
 libraries['M846']={'path':LAMP/'artifacts/pivot_bq/m846_wattclarity_source_2024_2026/raw_posts.json','expected_sha256':'ac1a7b1448864a7ceba5acab5216eead554e8e74f933f66d961798dad55ac605'}
 by_id={}; library_provenance=[]
 metadata_fields=['id','link','date','date_gmt','modified','modified_gmt']
 for name,lib in libraries.items():
  path=lib['path']; sha=hash_file(path)
  if sha!=lib['expected_sha256']:raise RuntimeError('library hash differs: '+name)
  posts=read_json(path)
  seen=set(); selected=[]
  for post in posts:
   ident=str(post['id'])
   if ident in seen:raise RuntimeError('within-library duplicate '+name+' '+ident)
   seen.add(ident)
   meta={k:post.get(k) for k in metadata_fields}
   meta.update(library=name,source_path=str(path),source_sha256=sha,capture_utc=None,capture_provenance=None)
   by_id.setdefault(ident,[]).append(meta)
   if START<=str(post.get('date',''))[:10]<=END: selected.append(ident)
  lib['selected_ids']=selected
  library_provenance.append({'library':name,'source_path':str(path),'sha256':sha,'hash_verified':True,'all_unique_ids':len(seen),'requested_unique_ids':len(selected)})
  del posts

 lib=libraries['M846']; selected_ids=set(lib['selected_ids'])
 for receipt_path in sorted(lib['path'].parent.glob('page_*.receipt.json')):
  capture_receipt=read_json(receipt_path)
  body_path=receipt_path.with_name(receipt_path.name.replace('.receipt.json','.body.json'))
  page=read_json(body_path)
  for post in page:
   ident=str(post['id'])
   if ident in selected_ids:
    for ref in by_id[ident]:
     if ref['library']=='M846':
      ref['capture_utc']=capture_receipt.get('finished_utc')
      ref['capture_provenance']={'receipt_path':str(receipt_path),'receipt_sha256':hash_file(receipt_path),'page_body_path':str(body_path),'page_body_sha256':capture_receipt.get('body_sha256'),'page_url':capture_receipt.get('url')}
  del page
 write_json(HERE/'LIBRARY_PROVENANCE.json',{'libraries':library_provenance,'normalizer_path':str(normalizer_path),'normalizer_sha256':hash_file(normalizer_path),'projected_fields':metadata_fields})
 robot=urllib.robotparser.RobotFileParser(); robot.set_url(entry['url']); robot.parse(body.decode(errors='replace').splitlines())
 crawl_delay=robot.crawl_delay(UA) or robot.crawl_delay('*') or 0
 delay=max(2,crawl_delay)
 current={}; pagination=[]; failures=[]; total=None; total_pages=None; complete=False
 query={'after':'2026-01-31T23:59:59','reference_snapshot':'2026-10-01T00:00:00','orderby':'date','order':'asc','_fields':'id,date,date_gmt,modified,modified_gmt,slug,link,title,content','per_page':50}
 page_no=1
 if entry['returncode']!=0 or entry['http_status']!='200': failures.append({'reason':'robots unavailable; source collection stopped'})
 else:
  while True:
   url='https://wattclarity.com.au/wp-json/wp/v2/posts?'+urllib.parse.urlencode(query|{'page':page_no})
   if not robot.can_fetch(UA,url):failures.append({'url':url,'reason':'robots disallowed'});break
   ent,data,headers=download(url,f'posts_page_{page_no:03d}.json',receipts,delay)
   if ent['returncode']!=0 or ent['http_status']!='200':failures.append({'url':url,'reason':'HTTP or transport failure','http_status':ent['http_status']});break
   try: posts=json.loads(data)
   except Exception as exc:failures.append({'url':url,'reason':'invalid JSON','exception_type':type(exc).__name__});break
   if not isinstance(posts,list):failures.append({'url':url,'reason':'response not post array'});break
   hfields={}
   for line in headers.splitlines():
    if ':' in line:
     k,v=line.split(':',1);hfields[k.lower().strip()]=v.strip()
   total=int(hfields['x-wp-total']) if 'x-wp-total' in hfields else total
   total_pages=int(hfields['x-wp-totalpages']) if 'x-wp-totalpages' in hfields else total_pages
   page_ids=[]
   for post in posts:
    ident=str(post.get('id'));date=str(post.get('date',''))
    if not START<=date[:10]<=END:continue
    if ident in current:raise RuntimeError('duplicate current API identity '+ident)
    required=['id','link','date','date_gmt','modified','modified_gmt','title','content']
    missing=[k for k in required if k not in post]
    if missing:failures.append({'id':ident,'reason':'missing required fields','fields':missing})
    record={k:post.get(k) for k in required}
    record['article_id']=ident;record['url']=post.get('link')
    record['title']=plain(post.get('title',{}).get('rendered',''))
    record['body']=plain(post.get('content',{}).get('rendered',''))
    record['capture_utc']=ent['capture_utc']; record['raw_path']=ent['local_path']; record['raw_sha256']=ent['sha256']
    record['existing_library_references']=by_id.get(ident,[])
    record['library_overlap']=bool(by_id.get(ident))
    record['version_status']='current_capture; previous source references preserved' if by_id.get(ident) else 'new_identity'
    record['historical_first_publication_verified']=False
    record['normalized_text_sha256']=hashlib.sha256((record['title']+'\n\n'+record['body']).encode()).hexdigest()
    if post.get('content',{}).get('protected') or not record['body']:failures.append({'id':ident,'reason':'protected or empty source body'})
    current[ident]=record;page_ids.append(ident)
   pagination.append({'page':page_no,'post_count':len(posts),'selected_ids':page_ids,'api_total':total,'api_total_pages':total_pages,'raw_path':ent['local_path']})
   print(json.dumps({'page':page_no,'rows':len(posts),'api_total':total,'api_total_pages':total_pages}),flush=True)
   if (total_pages is not None and page_no>=total_pages) or len(posts)<50:
    complete=(total is None or len(current)==total);break
   page_no+=1
   if page_no>100:failures.append({'reason':'pagination safety bound'});break

 if not complete:
  for route,name in [('https://wattclarity.com.au/feed/','fallback_feed.xml'),('https://wattclarity.com.au/2026/09/','fallback_month_2026_09.html')]:
   if robot.can_fetch(UA,route):
    ent,data,headers=download(route,name,receipts,delay)
    failures.append({'url':route,'reason':'fallback response preserved; finite feed or month HTML cannot certify requested WordPress JSON field coverage','http_status':ent['http_status']})

 requested_library_ids={ident for lib in libraries.values() for ident in lib['selected_ids']}
 absent_local=requested_library_ids-set(current)
 if absent_local:
  for name,lib in libraries.items():
   wanted=absent_local.intersection(lib['selected_ids'])
   if not wanted:continue
   posts=read_json(lib['path'])
   for post in posts:
    ident=str(post['id'])
    if ident not in wanted or ident in current:continue
    ref=next(x for x in by_id[ident] if x['library']==name)
    record={k:post.get(k) for k in ['id','link','date','date_gmt','modified','modified_gmt']}
    record.update(article_id=ident,url=post.get('link'),title=plain(post.get('title',{}).get('rendered','')),body=plain(post.get('content',{}).get('rendered','')),capture_utc=ref.get('capture_utc'),raw_path=str(lib['path']),raw_sha256=lib['expected_sha256'],existing_library_references=by_id[ident],library_overlap=True,version_status='local_saved_version_absent_from_current_acquisition',historical_first_publication_verified=False)
    record['normalized_text_sha256']=hashlib.sha256((record['title']+'\n\n'+record['body']).encode()).hexdigest()
    current[ident]=record
   del posts
 records=sorted(current.values(),key=lambda x:(x['date'],x['article_id']))
 with (HERE/'articles.jsonl').open('w') as f:
  for record in records:f.write(json.dumps(record,ensure_ascii=False)+'\n')
 metadata=[{k:v for k,v in record.items() if k not in ['title','body']} for record in records]
 write_json(HERE/'ARTICLE_METADATA.json',metadata)
 months=[]
 for month in [f'2026-{m:02d}' for m in range(2,10)]:
  selected=[x for x in metadata if str(x['date']).startswith(month)]
  ids=[x['article_id'] for x in selected]; pub_days=sorted({str(x['date'])[:10] for x in selected})
  months.append({'source':'WattClarity','month':month,'unique_ids':len(ids),'ids':ids,'publication_days_present':pub_days,'days_without_publications':'not classified as gaps; publication is event-based','current_downloaded_ids':sum(x['version_status']!='local_saved_version_absent_from_current_acquisition' for x in selected),'new_ids_vs_existing_libraries':sum(not x['library_overlap'] for x in selected),'existing_library_overlap_ids':sum(x['library_overlap'] for x in selected),'local_only_saved_ids':sum(x['version_status']=='local_saved_version_absent_from_current_acquisition' for x in selected),'files':sorted({x['raw_path'] for x in selected}),'missing_days':None,'intervals_expected':None,'coverage_status':'complete current public REST pagination' if complete else 'partial current acquisition; local saved-version union retained'})
 api_ids_count=sum(x['version_status']!='local_saved_version_absent_from_current_acquisition' for x in metadata)
 inv={'source':'WattClarity','created_utc':now(),'publication_window_local':[START,END],'api_query':query,'api_total':total,'api_total_pages':total_pages,'api_downloaded_unique_ids':api_ids_count,'api_pagination_complete':complete,'requested_union_unique_ids':len(records),'dedup_key':'WordPress ID as string','duplicate_current_ids':0,'existing_library_requested_unique_ids':len(requested_library_ids),'existing_library_overlap_ids':len(requested_library_ids&set(current)),'current_api_absent_local_saved_ids':sorted(absent_local),'months':months,'pagination':pagination,'robots_path':str(RAW/'robots.txt'),'polite_delay_seconds':delay,'articles_path':str(HERE/'articles.jsonl'),'articles_sha256':hash_file(HERE/'articles.jsonl'),'article_metadata_path':str(HERE/'ARTICLE_METADATA.json'),'failures':failures,'outcome_values_inspected':False,'capture_clock_note':'capture_utc is actual saved response completion time; does not verify first-publication version or historical issue-time eligibility'}
 write_json(HERE/'INVENTORY.json',inv)
 gaps=['# WattClarity source_acquisition gaps','']
 if complete:gaps.append('The current public WordPress REST pagination completed. This proves coverage of the current public query, not deleted, private, or historically modified versions.')
 else:gaps.append('Current REST coverage could not be completed. The recorded attempted REST/site/feed URLs and local saved-version union remain source evidence; missing items are not inferred from publication-free days.')
 if absent_local:gaps.append(f'{len(absent_local)} requested IDs exist in prior saved libraries and are absent from the current API acquisition; retained as local saved versions with capture provenance.')
 gaps.append('Historical first-publication bodies and issue-time availability remain unverified. The actual capture clocks are retained separately from WordPress publication and modification clocks. No outcome figures or article claims were read or summarized.')
 if failures:gaps.extend(['','Recorded acquisition limitations:']+[json.dumps(x,ensure_ascii=False) for x in failures])
 (HERE/'GAPS.md').write_text('\n'.join(gaps)+'\n')
 report=f''' Collected under the specified rules  WattClarity  from  2026-02-01  to  2026-09-30  public article sources 。robots.txt  allows  REST  access ； Requests are separated by at least  {delay}  seconds ， per page  50  articles 。 The  API  returns  {api_ids_count}  distinct  WordPress ID； pagination complete ：{complete}。 and  M917/M162/M846  by  ID  after deduplication ， the source-record union contains  {len(records)}  articles 。 Article bodies are deterministically normalized and saved ， without displaying 、 summarizing or extracting  D  result values 。\n\n Raw responses and headers are in  raw/； Each download records its  URL、 collection time 、 path 、 bytes 、SHA-256  from  DOWNLOAD_RECEIPT.json。articles.jsonl  retains titles 、 article bodies 、 publication dates 、 modification dates 、 collection clocks and source provenance ；ARTICLE_METADATA.json、LIBRARY_PROVENANCE.json、INVENTORY.json  provide audit information without article bodies 。 Access records are in  OPENED.jsonl。\n\n Limitations are in  GAPS.md： Collection establishes neither the original historical text nor availability at that time ； Days without articles are not automatically classified as gaps 。 Source observations are retained 。\n'''
 (HERE/'REPORT.md').write_text(report)
 print(json.dumps({'source':'WattClarity','api_ids':api_ids_count,'union_ids':len(records),'complete':complete,'months':[{k:x[k] for k in ['month','unique_ids','new_ids_vs_existing_libraries']} for x in months],'limitations':len(failures)}),flush=True)
