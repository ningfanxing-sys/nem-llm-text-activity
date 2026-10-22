"""Read-only amendment pin and declared identity checks; never open fit artifacts.

TSA signature verification is the coordinator's existing timestamp procedure.
Here its two verified result entries, manifest digest, and exact covered bytes
are required. A prepared CONFX directory without a chain is not an installation.
"""
from a8_common import *
import re

NO_SEAL_ADAPTER = 'seal carries no adapter field; binding by AMENDED_ADAPTER_CHAIN + live freeze + T4'
ADAPTER_FIELDS = ('adapter_freeze_sha256', 'adapter_sha256', 'adapter_freeze', 'adapter_identity')
CODE_FIELDS = ('code_sha256', 'adapter_code_sha256', 'code_files', 'adapter_files',
               'code_identity', 'code_identities', 'code', 'adapter_code')
PATH_FIELDS = ('adapter_root', 'adapter_freeze_path')


def digest(value):
    require(isinstance(value, str) and re.fullmatch('[0-9a-f]{64}', value),
            'Invalid declared identity SHA-256')
    return value


def newest_chain(root):
    """Choose the greatest CONFX version with a chain, never live freeze or mtime."""
    root = Path(root).resolve()
    paths = [(int(p.parent.name[5:]), p) for p in root.parent.glob('CONFX*/AMENDED_ADAPTER_CHAIN.json')
             if re.fullmatch(r'CONFX\d+', p.parent.name)]
    require(paths, 'No installed AMENDED_ADAPTER_CHAIN')
    _, path = max(paths)
    chain = read_json(path)
    require(chain.get('state') == 'EXECUTION_AMENDMENT_CHAIN_FROZEN', 'Newest amendment chain is not frozen')
    steps = chain.get('steps')
    require(isinstance(steps, list) and steps, 'Newest amendment chain has no last entry')
    last = steps[-1]
    require(last.get('task') == path.parent.name and chain.get('registered_chain', [])[-1:] == [last['task']],
            'Newest amendment chain last task mismatch')
    item = last['adapter_freeze']
    digest(item.get('sha256'))
    require(item == chain.get('amended_adapter_freeze') and
            Path(item['path']).resolve() == root/'ADAPTER_FREEZE.json', 'Last entry/adapter pin mismatch')
    # A newer chain must retain its predecessor's exact frozen record and pin.
    if len(steps) > 1:
        previous_path = root.parent/steps[-2]['task']/'AMENDED_ADAPTER_CHAIN.json'
        previous = read_json(previous_path)
        def archival_neutral(value):
            if isinstance(value, dict):
                return {k: archival_neutral(v) for k,v in value.items() if k != 'path'}
            if isinstance(value, list):
                return [archival_neutral(v) for v in value]
            return value
        require(archival_neutral(previous.get('steps')) == archival_neutral(steps[:-1]) and
                previous['amended_adapter_freeze']['sha256'] == last['parent_adapter_freeze']['sha256'],
                'Amendment chain extension does not retain predecessor')
    return path, chain


def chain_utc(chain):
    value = chain.get('time_utc')
    require(isinstance(value,str) and bool(value),
            'Latest amendment chain is missing time_utc; coordinator must supply a dated, re-timestamped chain before A8BATCH')
    try:
        stamp = dt.datetime.fromisoformat(value.replace('Z','+00:00'))
    except ValueError as exc:
        raise RuntimeError('Latest amendment chain has invalid time_utc') from exc
    require(stamp.utcoffset() == dt.timedelta(0), 'Amendment chain must have a UTC freeze time')
    return stamp

def main_wave_chronology(seal,seal_path,root):
    chain_path,chain = newest_chain(root)
    stamp = chain_utc(chain)
    entries = [i for i in seal.get('auxiliary_sources_and_resources',[]) if i.get('kind') == 'wall_fitting_ledger']
    require(len(entries) == 1, 'Main seal must bind exactly one wall fitting ledger for chain chronology')
    entry = entries[0]
    require(Path(entry['path']).resolve() == Path(seal_path).resolve().parent/'FITTING_WALL_LEDGER.json',
            'Main wall ledger is outside sealed main state')
    ledger = read_json(checked(entry))
    sealed_stages = {r['stage'] for r in seal.get('stage_dispositions',[]) if r['state'] in COMPLETE}
    starts = [w.get('start') for w in ledger.get('waves',[]) if
              w.get('state') != 'ABANDONED_ATTEMPT_CHARGED' and w.get('end') is not None
              and (not sealed_stages or w.get('stage') in sealed_stages)]
    require(starts and all(isinstance(s,(int,float)) for s in starts), 'Main wall ledger has no valid earliest wave')
    earliest = min(starts)
    require(stamp.timestamp() < earliest, 'Latest amendment chain does not precede earliest main fitting wave; re-pin refused')
    return dict(chain=identity(chain_path),chain_time_utc=stamp.isoformat(),wall_ledger=entry,earliest_wave_start=earliest)

def memory_rule_prefix(root):
    import ast
    tree = ast.parse((Path(root)/'execution_adapter.py').read_text())
    for node in tree.body:
        if isinstance(node,ast.Assign) and any(isinstance(n,ast.Name) and n.id == 'MEMORY_RULE' for n in node.targets):
            value = node.value
            while isinstance(value,ast.BinOp):
                value = value.left
            require(isinstance(value,ast.Constant) and isinstance(value.value,str) and value.value.endswith(': '),
                    'Installed memory_rule has no declared prefix')
            return value.value
    raise RuntimeError('Installed adapter has no MEMORY_RULE prefix')


def timestamp_binding(root, chain_path, chain):
    """Stream manifests, selecting only chain and freeze rows; no covered data opens."""
    q = Path(root).resolve().parent.parent
    wanted = {str(chain_path.relative_to(q)): identity(chain_path),
              str((Path(root)/'ADAPTER_FREEZE.json').relative_to(q)): chain['steps'][-1]['adapter_freeze']}
    chain_time = chain_utc(chain)
    require(chain_time.utcoffset() == dt.timedelta(0), 'Amendment chain must have a UTC freeze time')
    for directory in sorted((Path(root).parent/'TIMESTAMPS').glob('T4*')):
        label = directory.name
        result_path = directory/(label+'_RESULT.json')
        if not result_path.is_file():
            continue
        result = read_json(result_path)
        manifest = directory/('MANIFEST_'+label+'.sha256')
        require(result.get('label') == label and result.get('manifest') == manifest.name,
                'T4 result/manifest mismatch')
        require(sha(manifest) == result.get('manifest_sha256'), 'T4 manifest digest drift')
        found = {}
        with manifest.open() as stream:
            for line in stream:
                if line.startswith('#'):
                    continue
                parts = line.rstrip('\n').split('  ', 2)
                if len(parts) == 3 and parts[2] in wanted:
                    require(parts[2] not in found, 'Duplicate T4 identity row')
                    found[parts[2]] = dict(sha256=parts[0], bytes=int(parts[1]))
        if any(found.get(rel) != dict(sha256=item['sha256'], bytes=item['bytes']) for rel,item in wanted.items()):
            continue
        tsa = result.get('tsa', {})
        require(len(tsa) >= 2 and all(e.get('verified') is True for e in tsa.values()),
                'T4 requires two coordinator-verified TSA results')
        replies = []
        for name, entry in tsa.items():
            require(re.fullmatch('[a-zA-Z0-9_-]+', name), 'Invalid TSA name')
            stamp = dt.datetime.strptime(entry['time_stamp'], '%b %d %H:%M:%S %Y GMT').replace(tzinfo=dt.timezone.utc)
            require(stamp >= chain_time, 'T4 predates amendment freeze')
            replies.append(identity(directory/(label+'_'+name+'.tsr')))
        return dict(label=label, manifest=identity(manifest), result=identity(result_path),
                    tsa_receipts=replies, verification='coordinator verified TSA results; exact manifest coverage checked')
    raise RuntimeError('No verified T4 binding covers newest amendment chain and adapter freeze')


def chain_pin(root):
    path, chain = newest_chain(root)
    return dict(task=chain['steps'][-1]['task'], chain=identity(path),
                adapter_freeze=chain['steps'][-1]['adapter_freeze'],
                timestamp=timestamp_binding(root, path, chain))


def declared_identity(record, root, pin, frozen, source):
    """Inspect only explicitly named identity fields, never task/prediction/score fields.

    Code declarations are file SHA maps or {path, sha256, bytes?} records.
    An opaque aggregate digest with no declared file cannot prove agreement.
    """
    root = Path(root).resolve()
    expected = {str((root/rel).resolve()): item for rel,item in frozen['files'].items()}
    expected[str(root/'ADAPTER_FREEZE.json')] = dict(sha256=pin, bytes=(root/'ADAPTER_FREEZE.json').stat().st_size)
    module_fields = {Path(rel).stem+'_sha256': rel for rel in frozen['files'] if Path(rel).suffix == '.py'}

    def file_check(item, rel=None):
        require(isinstance(item, (dict, str)), 'Unsupported declared code identity: '+source)
        if isinstance(item, str):
            item = dict(sha256=item)
        path = item.get('path', rel)
        require(isinstance(path, str), 'Declared code identity lacks file path: '+source)
        path = str((root/path).resolve())
        require(path in expected and digest(item.get('sha256')) == expected[path]['sha256'] and
                ('bytes' not in item or item['bytes'] == expected[path]['bytes']),
                'Conflicting declared code identity: '+source)

    for key in ADAPTER_FIELDS:
        if key not in record:
            continue
        value = record[key]
        value_hash = value.get('sha256') if isinstance(value, dict) else value
        require(digest(value_hash) == pin, 'Conflicting declared adapter identity: '+source)
        if isinstance(value, dict):
            file_check(value, 'ADAPTER_FREEZE.json')
    for key in CODE_FIELDS:
        if key not in record:
            continue
        value = record[key]
        if isinstance(value, dict) and 'sha256' in value:
            file_check(value)
        elif isinstance(value, dict):
            for rel, item in value.items():
                file_check(item, rel)
        elif isinstance(value, list):
            for item in value:
                file_check(item)
        else:
            raise RuntimeError('Unsupported declared code identity: '+source)
    for key in PATH_FIELDS:
        if key in record:
            target = root if key == 'adapter_root' else root/'ADAPTER_FREEZE.json'
            require(isinstance(record[key], str) and (root/record[key]).resolve() == target,
                    'Conflicting declared adapter path: '+source)
    for key, rel in module_fields.items():
        if key in record:
            file_check(record[key], rel)
    supported = set((*ADAPTER_FIELDS, *CODE_FIELDS, *PATH_FIELDS, *module_fields))
    for key in record:
        if key not in supported and re.search(r'(adapter|code).*(sha256|identity|files|freeze)', key):
            raise RuntimeError('Unsupported declared code/adapter identity field: '+key+' in '+source)
    return [key for key in record if key in supported]


def receipt_identity_checks(seal, seal_path, root, pin, frozen):
    """Own fit receipts only; models, features, predictions and scores are never opened."""
    own = Path(seal_path).resolve().parent/'fits/receipts'
    require(own.resolve() == own, 'Main chain receipt directory is redirected')
    paths = {}
    # Only seal-bound completed fits can establish the installed-chain identity.
    # Failed/abandoned pre-install attempts are retained, not evidence of this seal.
    for p in own.glob('*.json'):
        require(p.resolve().parent == own,'Fit receipt outside main chain receipt directory')
    for item in seal.get('fit_receipts_and_models', []):
        if item.get('kind') != 'fit_receipt':
            continue
        path = Path(item['path']).resolve()
        require(path.parent == own and path.suffix == '.json', 'Fit receipt outside main chain receipt directory')
        checked(item)
        paths[path] = item
    records = []
    prefix = memory_rule_prefix(root)
    for path in sorted(paths):
        record = read_json(path)
        require(isinstance(record.get('memory_rule'),str) and record['memory_rule'].startswith(prefix),
                'Fit receipt memory_rule prefix does not match pinned adapter: '+str(path))
        fields = declared_identity(record, root, pin, frozen, str(path))
        records.append(dict(receipt=identity(path), declared_identity_fields=fields))
    return records
