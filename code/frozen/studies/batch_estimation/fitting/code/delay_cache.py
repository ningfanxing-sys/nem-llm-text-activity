"""Post-seal production-cache transfer, identities only; no fitted values read."""
from a8_common import *

class CacheOnlyEncoder:
    def encode_corpus(self,*args,**kwargs):
        raise ResourceStop('Production corpus cache miss; document resource-only cache remedy, never re-encode')

class LockedMissingEncoder:
    """Cache hits stay byte-identical; cache misses use the unchanged pinned encoder."""
    def __init__(self,A,permit,cache):
        self.A,self.permit,self.cache = A,permit,Path(cache)
        self.encoder = None
    def encode_corpus(self,text,**kwargs):
        if self.encoder is None:
            import tempfile
            local = self.cache/'library_tmp';local.mkdir(parents=True,exist_ok=True)
            tempfile.tempdir = str(local);os.environ['TMPDIR'] = str(local)
            os.environ['HF_HUB_OFFLINE'] = '1';os.environ['TRANSFORMERS_OFFLINE'] = '1'
            self.encoder = self.A.features.build_encoder(permit=self.permit,cache_directory=self.cache)
        result = self.encoder.encode_corpus(text,**kwargs)
        with (self.cache/'MISSING_CORPORA.jsonl').open('a') as stream:
            stream.write(json.dumps(dict(utc=now(),text_sha256=hashlib.sha256(str(text).encode()).hexdigest(),
                         characters=len(str(text)),first_chunk_only=kwargs.get('first_chunk_only',False),
                         encoder_lock=identity(CONF/'ENCODER_LOCK.json')))+'\n')
            stream.flush();os.fsync(stream.fileno())
        return result

def notice_census(notices):
    import pandas as pd
    lo = pd.Timestamp('2026-07-27',tz='Australia/Brisbane')
    split = pd.Timestamp('2026-08-01',tz='Australia/Brisbane')
    hi = pd.Timestamp('2026-10-01',tz='Australia/Brisbane')
    # Scope is Creation Date's local pool, not rounded availability at a boundary.
    def clock(n):
        raw = n.get('clocks',{}).get('raw_time_local') or n.get('anchor_local')
        if raw:
            stamp = pd.Timestamp(raw)
            return stamp.tz_localize('Australia/Brisbane') if stamp.tzinfo is None else stamp
        return pd.Timestamp(n.get('creation_utc',n.get('creation_date',n['available_utc'])))
    clocks = [clock(n) for n in notices]
    require(all(t.tzinfo is not None for t in clocks),'DLY8 census needs timezone-aware source clocks')
    pool = [n for n,t in zip(notices,clocks) if lo <= t < hi]
    lead = sum(lo <= t < split for t in clocks)
    require(len(pool) == 796 and lead == 71 and len({str(n['notice_id']) for n in pool}) == 796,
            'DLY8 registered 796-notice / 71-lead-in census failed')
    return dict(pool=796,lead_in=71,scope='2026-07-27 through 2026-09-30 AEST')

def copy_production_cache(source,destination):
    source,destination = Path(source),Path(destination)
    receipt = destination/'PRODUCTION_CACHE_INPUTS.json'
    if receipt.exists():
        for row in read_json(receipt)['files']:
            checked(row['source']);checked(row['copy'])
        return receipt
    require(source.is_dir(),'Production encoder cache missing after seal')
    rows = []
    for group in ('chunks','corpora'):
        for p in sorted((source/group).rglob('*')):
            if not p.is_file() or {'revisions','failed_attempts'} & set(p.relative_to(source).parts):
                continue
            if '.atomic.' in p.name or '.tmp.' in p.name or p.name.endswith('.tmp'):
                continue  # interrupted unpublished cache temporary; not an input
            require(p.suffix in ('.npy','.json'),'Unexpected production cache file')
            src = identity(p)
            target = destination/p.relative_to(source)
            target.parent.mkdir(parents=True,exist_ok=True)
            atomic_copy(p,target)
            rows.append(dict(source=src,copy=identity(target)))
    require(any('/corpora/' in r['source']['path'] for r in rows),'Empty production corpus cache')
    write_json(receipt,dict(state='SEALED_PRODUCTION_CACHE_COPIED',files=rows,
                           reencoding_allowed="LOCKED_MISSING_CORPORA_ONLY_WITH_RECEIPTS",content_values_decoded=False),exclusive=True)
    return receipt
