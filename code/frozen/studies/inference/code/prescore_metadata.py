'Project input metadata into the pre-scoring computation record.'
from pathlib import Path
import json
import read_comparisons as P


def normalize_selection(raw):
    selected=raw['selected'];expected={task+'/'+arm for task,pairs in P.PAIRS.items() for pair in pairs for arm in pair}
    P.require(set(selected)==expected,'Native CPS8 per-arm census mismatch')
    out={task:{} for task in P.PAIRS}
    for key,value in selected.items():
        task,arm=key.split('/',1)
        P.require(value is None or value in ('g0','g1','g2'),'Native CPS8 grid value mismatch')
        out[task][arm]=None if value is None else int(value[1:])
    return out


def project(source,destination):

    source=dict(source);raw=P.strict_json(P.checked(source));data=normalize_selection(raw)
    destination=Path(destination);P.require(not destination.exists(),'Refuse existing CPS8 projection')
    receipt=destination.with_suffix('.receipt.json');P.require(not receipt.exists(),'Refuse existing CPS8 projection receipt')
    with destination.open('x') as f:json.dump(data,f,indent=2);f.write('\n')
    identity=P.identity(destination)
    binding=dict(schema='A8POST_CPS8_METADATA_PROJECTION_V1',source=source,output=identity,adapter=P.identity(Path(__file__)),outcome_access=False)
    with receipt.open('x') as f:json.dump(binding,f,indent=2);f.write('\n')
    return identity,P.identity(receipt)


def verify(identity,receipt,timestamps):
    data=P.strict_json(P.checked(identity));binding=P.strict_json(P.checked(receipt))
    P.require(binding['schema']=='A8POST_CPS8_METADATA_PROJECTION_V1' and binding['outcome_access'] is False,'CPS8 projection timestamp_checks invalid')
    P.require(binding['output']==identity and binding['adapter']==P.identity(Path(__file__)),'CPS8 projection identities drift')
    raw=P.strict_json(P.checked(binding['source']))
    P.require(data==normalize_selection(raw),'CPS8 metadata projection drift')
    for item in (identity,receipt,binding['source'],binding['adapter']):
        P.require(any(Path(k).resolve()==Path(item['path']).resolve() and v==item['sha256'] for k,v in timestamps['T5']['files'].items()),'CPS8 projection/source/adapter exact T5 binding missing')
    return data
