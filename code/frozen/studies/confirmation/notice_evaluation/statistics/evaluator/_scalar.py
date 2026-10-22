'Calculate scalar forecast evaluation quantities.'
import re
from decimal import Decimal, InvalidOperation

CHECKS = ('one_day', 'seven_day', 'hln', 'hac7', 'three_seed', 'family_interval')


class FillError(RuntimeError):
    pass


def require(ok, message):
    if not ok:
        raise FillError(message)


def decimal(value, nullable=False):
    if value is None and nullable:
        return None
    require(isinstance(value, str) and bool(re.fullmatch(r'[+-]?\d+(?:\.\d+)?', value)), 'expected signed decimal string')
    try:
        d = Decimal(value)
    except InvalidOperation as exc:
        raise FillError('invalid decimal') from exc
    require(d.is_finite(), 'non-finite decimal')
    return d


def seven_undefined(c):
    return c['family_seven_day'] is None or c['per_contrast_seven_day'] is None


def robust(c, alert=False):
    return c['class'] != 'NE' and not alert and not seven_undefined(c) and all(c['checks'][k] == 'PASS' for k in CHECKS) and ((c['class']=='IMP' and decimal(c['family_seven_day'][1]) < 0) or (c['class']=='DET' and decimal(c['family_seven_day'][0]) > 0))

