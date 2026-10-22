'Check the fields of the notice evaluation schema.'
import hashlib
import json
import math
import re
from pathlib import Path
from . import _scalar as F
from . import _joint_comparisons as J

JOINT_SCHEMA_BYTES = 17987
JOINT_SCHEMA_SHA256 = '8fb8342587d684539cc47e8f546adce860da90f28e61951747619c6523d96fd6'


def require(ok, message):
    if not ok:
        raise ValueError(message)


def exact_identity(item, pointer=False):
    expected = {'path', 'bytes', 'sha256'} | ({'pointer'} if pointer else set())
    require(isinstance(item, dict) and set(item) == expected, 'Exact identity fields')
    raw = item['path']
    require(isinstance(raw, str) and '\x00' not in raw, 'Identity path type')
    path = Path(raw)
    require(path.is_absolute() and raw == str(path) and '..' not in path.parts,
            'Identity lexical alias/escape')
    require(type(item['bytes']) is int and item['bytes'] >= 0, 'Identity bytes')
    require(isinstance(item['sha256'], str) and re.fullmatch('[0-9a-f]{64}', item['sha256']), 'Identity SHA')
    if pointer:
        require(isinstance(item['pointer'], str) and item['pointer'].startswith('/'), 'Identity pointer')
    return item


def schema_check(value, schema, spec=None):
    spec = schema if spec is None else spec
    supported = {'$schema', '$id', 'title', 'description', '$defs', '$ref', 'type',
        'additionalProperties', 'required', 'properties', 'const', 'enum', 'items',
        'minimum', 'maximum', 'pattern', 'anyOf', 'uniqueItems', 'minItems',
        'maxItems', 'minProperties', 'minLength'}
    require(set(spec) <= supported, 'Unsupported schema keyword')
    if '$ref' in spec:
        ref = spec['$ref']
        require(ref.startswith('#/$defs/') and ref.split('/')[-1] in schema['$defs'], 'Schema ref')
        schema_check(value, schema, schema['$defs'][ref.split('/')[-1]])
    if 'anyOf' in spec:
        failures = []
        for branch in spec['anyOf']:
            try:
                schema_check(value, schema, branch)
                break
            except ValueError as exc:
                failures.append(str(exc))
        else:
            raise ValueError('No schema branch: ' + '; '.join(failures))
    if 'const' in spec:
        require(type(value) is type(spec['const']) and value == spec['const'], 'Schema const')
    if 'enum' in spec:
        require(any(type(value) is type(x) and value == x for x in spec['enum']), 'Schema enum')
    number = type(value) in (int, float) and math.isfinite(value)
    if 'type' in spec:
        kinds = {'null': value is None, 'boolean': type(value) is bool,
            'object': isinstance(value, dict), 'array': isinstance(value, list),
            'string': isinstance(value, str), 'number': number, 'integer': type(value) is int}
        types = [spec['type']] if isinstance(spec['type'], str) else spec['type']
        require(all(t in kinds for t in types) and any(kinds[t] for t in types), 'Schema type')
    if isinstance(value, dict):
        require(len(value) >= spec.get('minProperties', 0), 'Schema object size')
        require(set(spec.get('required', [])) <= set(value), 'Schema missing fields')
        props = spec.get('properties', {})
        for key, item in value.items():
            if key in props:
                schema_check(item, schema, props[key])
            else:
                extra = spec.get('additionalProperties', True)
                require(extra is not False, 'Schema extra field: ' + key)
                if isinstance(extra, dict):
                    schema_check(item, schema, extra)
    if isinstance(value, list):
        require(spec.get('minItems', 0) <= len(value) <= spec.get('maxItems', len(value)), 'Schema array size')
        if spec.get('uniqueItems'):
            keys = [json.dumps(x, sort_keys=True, allow_nan=False) for x in value]
            require(len(keys) == len(set(keys)), 'Schema duplicate array item')
        if 'items' in spec:
            for item in value:
                schema_check(item, schema, spec['items'])
    if isinstance(value, str):
        require(len(value) >= spec.get('minLength', 0), 'Schema string size')
        if 'pattern' in spec:
            require(re.search(spec['pattern'], value) is not None, 'Schema pattern')
    if number:
        require(spec.get('minimum', value) <= value <= spec.get('maximum', value), 'Schema numerical range')
    return True


def pinned_joint_schema(schema):
    data = Path(__file__).with_name('JOINT_RECORD_SCHEMA.json').read_bytes()
    require(len(data) == JOINT_SCHEMA_BYTES and hashlib.sha256(data).hexdigest() == JOINT_SCHEMA_SHA256,
            'Pinned joint schema file identity drift')
    pinned = json.loads(data)
    require(isinstance(schema, dict), 'Pinned joint schema object required')
    try:
        canonical = lambda value: json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)
        matches = canonical(schema) == canonical(pinned)
    except (TypeError, ValueError):
        matches = False
    require(matches, 'Pinned joint schema object identity drift')
    return pinned


def validate_joint(record, schema):
    schema_check(record, pinned_joint_schema(schema))
    J.validate_joint_record(record)
    return True


def validate_scalar(row):
    required = {'arm', 'reference', 'class', 'checks', 'family_one_day',
        'family_seven_day', 'per_contrast_seven_day', 'three_seed_class', 'three_seed_effect'}
    require(isinstance(row, dict) and required <= set(row), 'Scalar fields missing')
    require(row['class'] in J.CLASSES and row['three_seed_class'] in J.CLASSES, 'Scalar/seed class')
    require(isinstance(row['checks'], dict) and set(row['checks']) == set(F.CHECKS), 'Exact six checks required')
    require(all(x in ('PASS', 'FAIL', 'UNAVAILABLE') for x in row['checks'].values()), 'Check status')
    for name in ('family_one_day', 'family_seven_day', 'per_contrast_seven_day'):
        values = row[name]
        if values is not None:
            require(isinstance(values, list) and len(values) == 2, 'Scalar interval shape')
            lo, hi = [F.decimal(x) for x in values]
            require(lo <= hi, 'Scalar interval order')
    F.decimal(row['three_seed_effect'], nullable=True)
    require((row['three_seed_class'] == 'NE') == (row['three_seed_effect'] is None), 'Seed unavailable/mean mismatch')
    return True
