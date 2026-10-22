'Compare the chronology of notice availability specifications.'
from copy import deepcopy
import json
from pathlib import Path

OUT = Path(__file__).resolve().parents[1]
Q = OUT.parents[4]/'studies'
BINDING = dict(
    schema='ANCHORREADER_DEADLINE_SPECIFICATION_V1',
    original_deadline_utc='2026-10-06T07:00:00Z',
    specification1_deadline_utc='2026-10-09T07:00:00Z',
    effective_calendar_deadline_utc=None,
    specification_recorded_utc='2026-10-05T10:25:00Z',
    timestamp_label='T4I', timestamp_utc='2026-10-05T10:28:35Z',
    specification_identity=dict(
        path=str(Q/'confirmation/ANCHORDIAG/SOURCE_DECISION_RULE_SPECIFICATION_1_DEADLINE_20261005.md'),
        sha256='d62decfb4904264c0aba816f749a00d288c6bef72fa88cea9b86b52236955680'),
    manifest_identity=dict(
        path=str(Q/'confirmation/TIMESTAMPS/T4I/MANIFEST_T4I.sha256'),
        sha256='859b33c8cd7e4c09f823a297dc5413b3c72f92bf19adb46a5855680504ef8ee6'),
    timestamp_result_identity=dict(
        path=str(Q/'confirmation/TIMESTAMPS/T4I/T4I_RESULT.json'),
        sha256='a4d0ec20e98494f116896636325a9408c3d9ca361ae0e5dcbb58316624bc4f1e'),
    specification2_identity=dict(
        path=str(Q/'confirmation/ANCHORDIAG/SOURCE_DECISION_RULE_SPECIFICATION_2_NO_CALENDAR_DEADLINE_20261005.md'),
        sha256='ff2b893f5c5bbdf6067cbd93311802bdd3a9cc25013d02442babca7f19905807'),
    manifest2_identity=dict(
        path=str(Q/'confirmation/TIMESTAMPS/T4J/MANIFEST_T4J.sha256'),
        sha256='3297a87490755f8bb0fe4832407c9c856223c7dd6c6f9240accca3b321b1ef00'),
    timestamp_result2_identity=dict(
        path=str(Q/'confirmation/TIMESTAMPS/T4J/T4J_RESULT.json'),
        sha256='5a62aa149a1b98130b576b9daa2329dc7603662d5a06571e8c405eec99d538fd'),
    erratum_identity=dict(
        path=str(Q/'confirmation/ANCHORDIAG/ERRATUM_SPECIFICATION_2_RECORDED_TIME_20261005.md'),
        sha256='e697cd79d29b852f52757cab94e4948c8b68db69bbd9e3ba446f482c1ba1e1fb'),
    specification2_timestamp_label='T4J', specification2_timestamp_utc='2026-10-05T10:32:36Z',
    specification2_printed_recorded_utc='2026-10-05T10:33:00Z',
    specification_order=['specification_identity', 'specification2_identity'],
    completion_rule='Corrected seal completed and verified before T5; T5 waits for it',
    nr_rule='Frozen procedure cannot complete: terminal parity/coverage/identity failure or repair requires changing frozen computation')
IDENTITY_FIELDS = ('specification_identity', 'manifest_identity', 'timestamp_result_identity',
                   'specification2_identity', 'manifest2_identity', 'timestamp_result2_identity', 'erratum_identity')
METADATA_SOURCES = tuple(Path(BINDING[key]['path']) for key in IDENTITY_FIELDS)


def verified_binding(checked, require):

    paths = {key: checked(BINDING[key]) for key in IDENTITY_FIELDS}
    for specification_key, manifest_key, result_key, label, timestamp, tsa_time in (
        ('specification_identity', 'manifest_identity', 'timestamp_result_identity',
         'T4I', BINDING['timestamp_utc'], 'Oct  5 10:28:35 2026 GMT'),
        ('specification2_identity', 'manifest2_identity', 'timestamp_result2_identity',
         'T4J', BINDING['specification2_timestamp_utc'], 'Oct  5 10:32:36 2026 GMT')):
        manifest = paths[manifest_key].read_text().splitlines()
        specification = paths[specification_key]
        row = '{}  {}  {}'.format(BINDING[specification_key]['sha256'],
                                specification.stat().st_size, specification.relative_to(Q).as_posix())
        require(manifest.count(row) == 1, 'Specification absent from exact '+label+' manifest')
        require('# label: '+label in manifest
                and '# created_utc: '+timestamp.replace('Z', '+00:00') in manifest,
                'Specification '+label+' timestamp mismatch')
        result = json.loads(paths[result_key].read_text())
        require(result.get('label') == label and result.get('manifest') == paths[manifest_key].name
                and result.get('manifest_sha256') == BINDING[manifest_key]['sha256'],
                'Specification '+label+' manifest identity mismatch')
        require(result.get('tsa', {}).get('freetsa', {}).get('verified') is True
                and result['tsa']['freetsa'].get('time_stamp') == tsa_time
                and result.get('tsa', {}).get('digicert', {}).get('verified') is True,
                'Specification '+label+' verification receipt mismatch')
    return deepcopy(BINDING)


def corrected_seal_precedes_t5(acceptance, t5, checked, require, utc):

    binding = verified_binding(checked, require)
    for key in IDENTITY_FIELDS:
        item = binding[key]
        require(any(Path(path).resolve() == Path(item['path']).resolve() and digest == item['sha256']
                    for path, digest in t5['files'].items()),
                'Exact specification/T4I/T4J/erratum T5 row missing: '+key)
    return utc(acceptance['corrected_seal_verified_utc']) < utc(t5['utc'])
