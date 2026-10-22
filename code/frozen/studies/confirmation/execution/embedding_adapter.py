"""Frozen MiniLM with resume-safe revision/token-block and corpus caches."""
from __future__ import annotations
from pathlib import Path
import hashlib,json,os,tempfile
import numpy as np
from runtime import CONF,conf_module,file_identity,read_json,atomic_json,sha256
original=conf_module('encoders')
require_execution=conf_module('guard').require_execution


def _save_array(path,value):
    p=Path(path);p.parent.mkdir(parents=True,exist_ok=True)
    fd,name=tempfile.mkstemp(prefix=p.name+'.',suffix='.tmp',dir=p.parent)
    try:
        with os.fdopen(fd,'wb') as stream:
            np.save(stream,np.asarray(value,dtype='float32'),allow_pickle=False)
            stream.flush();os.fsync(stream.fileno())
        os.replace(name,p)
    finally:
        if os.path.exists(name):os.unlink(name)


class PersistentMiniLM(original.FrozenMiniLM):
    def __init__(self,model_directory,lock_path,cache_directory,*,permit,opened):
        require_execution(permit)
        self.cache_directory=Path(cache_directory)
        self.cache_directory.mkdir(parents=True,exist_ok=True)
        super().__init__(model_directory,lock_path,permit=permit,opened=opened)
        if not hasattr(self.tokenizer,'prepare_for_model'):
            # Transformers 5 removed this API. Recreate only the pinned BERT
            # single-sequence operation so the original _chunk runs unchanged.
            tokenizer=self.tokenizer
            cls,sep=tokenizer.cls_token_id,tokenizer.sep_token_id
            if cls is None or sep is None:
                raise ValueError('Pinned BERT single-sequence special IDs missing')
            def prepare(ids,*,add_special_tokens,truncation,return_attention_mask,return_token_type_ids):
                if not add_special_tokens or truncation or not return_attention_mask or not return_token_type_ids:
                    raise ValueError('Unexpected frozen single-sequence token preparation arguments')
                if len(ids)>original.CONTENT_LIMIT:
                    raise ValueError('No silent truncation allowed')
                sequence=[int(cls),*ids,int(sep)]
                return {'input_ids':sequence,'attention_mask':[1]*len(sequence),
                        'token_type_ids':[0]*len(sequence)}
            probe='Synthetic token adapter check.'
            ids=tokenizer.encode(probe,add_special_tokens=False,truncation=False)
            adapted=prepare(ids,add_special_tokens=True,truncation=False,
                            return_attention_mask=True,return_token_type_ids=True)
            backend=tokenizer(probe,add_special_tokens=True,truncation=False,
                              return_attention_mask=True,return_token_type_ids=True)
            if any(adapted[k]!=backend[k] for k in adapted):
                raise ValueError('Tokenizer compatibility differs from pinned BERT postprocessor')
            tokenizer.prepare_for_model=prepare

    def _chunk(self,ids):
        key=hashlib.sha256(json.dumps(ids,separators=(',',':')).encode()).hexdigest()
        if key in self.chunk_cache:return self.chunk_cache[key]
        path=self.cache_directory/'chunks'/original.REVISION/(key+'.npy')
        meta=path.with_suffix('.json')
        if path.exists() and meta.exists():
            record=read_json(meta)
            if record['revision']!=original.REVISION or record['token_ids_sha256']!=key or sha256(path)!=record['vector_sha256']:
                raise ValueError('Persistent encoder token cache drift')
            vector=np.load(path,allow_pickle=False)
            if vector.shape!=(384,) or vector.dtype!=np.float32 or not np.isfinite(vector).all():
                raise ValueError('Invalid persistent encoder vector')
            if len(self.chunk_cache)>=10000:self.chunk_cache.pop(next(iter(self.chunk_cache)))
            self.chunk_cache[key]=vector
            return vector
        vector=super()._chunk(ids)
        _save_array(path,vector)
        atomic_json(meta,{'revision':original.REVISION,'token_ids_sha256':key,
            'token_count':len(ids),'vector_sha256':sha256(path)},immutable=True)
        return vector


def encode_cached(encoder,text,cache_directory,*,permit,first_chunk_only=False):
    require_execution(permit)
    serialized=str(text)
    signature={'revision':original.REVISION,'content_budget':254,
        'text_sha256':hashlib.sha256(serialized.encode()).hexdigest(),
        'first_chunk_only':bool(first_chunk_only),'dimension':384,'dtype':'float32'}
    key=hashlib.sha256(json.dumps(signature,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    root=Path(cache_directory);path=root/'corpora'/(key+'.npy');meta=path.with_suffix('.json')
    if path.exists() and meta.exists():
        m=read_json(meta)
        if m['signature']!=signature or sha256(path)!=m['vector_sha256']:
            raise ValueError('Corpus cache drift')
        v=np.load(path,allow_pickle=False)
        if v.shape!=(384,) or v.dtype!=np.float32 or not np.isfinite(v).all():raise ValueError('Corpus cache vector invalid')
        return v,m['encoding']
    vector,encoding=encoder.encode_corpus(serialized,first_chunk_only=first_chunk_only)
    encoding={**encoding,'serialized_chars':len(serialized),'serialized_utf8_bytes':len(serialized.encode()),
        'serialized_text_sha256':signature['text_sha256'],'all_original_field_text_serialized':True,
        'corpus_concatenated_before_tokenization':True}
    vector=np.asarray(vector,dtype=np.float32)
    if vector.shape!=(384,) or not np.isfinite(vector).all():raise ValueError('Encoder output invalid')
    _save_array(path,vector)
    atomic_json(meta,{'signature':signature,'encoding':encoding,'vector_sha256':sha256(path)},immutable=True)
    return vector,encoding


def build_encoder(*,permit,cache_directory):
    require_execution(permit)
    lock=read_json(CONF/'ENCODER_LOCK.json')
    directory=Path('/Users/stacchining/.cache/huggingface/hub/models--sentence-transformers--all-MiniLM-L6-v2/snapshots')/lock['revision']
    if not (directory/'model.safetensors').is_file():directory=CONF/'model_lock'
    def opened(path,mode,purpose):
        # Host's Python audit hook records every actual open; this callback also
        # remains compatible with the frozen encoder's explicit I/O interface.
        return None
    return PersistentMiniLM(directory,CONF/'ENCODER_LOCK.json',cache_directory,permit=permit,opened=opened)
