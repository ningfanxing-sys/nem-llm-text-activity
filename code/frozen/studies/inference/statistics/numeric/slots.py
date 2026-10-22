'Project saved numerical rows into table fields.'
from copy import deepcopy
from ..input_checks import require


def token(value):
    return str(value).replace('~', '~0').replace('/', '~1')


def forest_projection(current, census):
    rows = []
    for slot in census['forest']:
        key = slot['family_key']
        require(key in current, 'Missing native family/disposition for forest: ' + key)
        family = current[key]
        reports = family.get('reports', [])
        matches = [(i, r) for i, r in enumerate(reports)
                   if (r['arm'], r['reference']) == (slot['arm'], slot['reference'])]
        require(len(matches) <= 1, 'Ambiguous native pair within one forest layer')
        computed = family['state'] == 'COMPUTED'
        require(not computed or len(matches) == 1, 'Computed forest slot missing native row')
        require(computed or bool(family.get('reason')), 'Unavailable forest needs native reason')
        index, native = matches[0] if matches else (None, None)
        pointer = '/current/' + token(key)
        if index is not None:
            pointer += '/reports/' + str(index)
        rows.append(dict(identity=deepcopy(slot), state=family['state'],
                         native_disposition=family.get('native_disposition', family['state']),
                         reason=family.get('reason'), native=deepcopy(native), pointer=pointer,
                         family_m=family.get('family_m'), days=family.get('days')))
    require(len(rows) == 110 and len({r['identity']['slot_id'] for r in rows}) == 110,
            'Forest identity census drift')
    return rows


def native_census(current):

    rows = []


    for key in sorted(current):
        family = current[key]
        base = '/current/' + token(key)
        task, layer = key.split('/', 1)
        view = ('REPORT_ONLY_2025' if layer == 'report_2025' else
                'R2_FIXED_AEST_135' if task == 'news' else 'NOTICE_TARGET_61')
        rows.append(dict(slot_id='native-family/' + key, pointer=base,
                         identity=dict(task=task, layer=layer), view=view,
                         state=family['state'], reason=family.get('reason'),
                         native=deepcopy(family)))
        for i, report in enumerate(family.get('reports', [])):
            rows.append(dict(slot_id='native-comparison/' + key + '/' + str(i),
                             identity=dict(task=task, layer=layer, report_index=i,
                                           arm=report['arm'], reference=report['reference']), view=view,
                             pointer=base + '/reports/' + str(i), state=family['state'],
                             reason=family.get('reason'), native=deepcopy(report)))
    require(len({r['slot_id'] for r in rows}) == len(rows), 'Native identity collision')
    return rows
