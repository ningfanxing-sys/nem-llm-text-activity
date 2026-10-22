'Check the selected structural feature calculations against their sources.'
import hashlib
from pathlib import Path
import types
from science_contract import require

AF = Path(__file__).absolute().parent.parent
SOURCE = AF / 'availability_delays/speed_binding.py'


def validate_selected_receipt(receipt):
    require(receipt.get('schema') == 'AFSPEEDC2_COMPLETE_REGRESSION_RECEIPT_V1' and
            receipt.get('state') == 'PASS' and receipt.get('tests_run') == 197 and
            all(type(receipt.get(k)) is int and receipt[k] == 0
                for k in ('failures', 'errors', 'skipped')) and
            receipt.get('selected_tests') is False and receipt.get('source_unchanged') is True,
            'Unclean/obsolete speed receipt cannot be selected')


def validate_selection(selected, expected, receipt):
    require(selected and selected == expected, 'Selected overlay source/schema/evidence drift')
    validate_selected_receipt(receipt)
    return selected


def verify_inherited_delivery(*, expected_source):

    require(expected_source['path'] == str(SOURCE), 'Exact public speed checker required')
    for path in (SOURCE, *SOURCE.parents):
        require(not path.is_symlink(), 'Speed checker symlink refused')
    source = SOURCE.read_bytes()
    require(len(source) == expected_source['bytes'] and
            hashlib.sha256(source).hexdigest() == expected_source['sha256'],
            'Inherited speed checker drift')
    module = types.ModuleType('_af_scoring_speed_binding')
    module.__file__ = str(SOURCE)
    exec(compile(source, str(SOURCE), 'exec'), module.__dict__)
    return module.verify_speed_delivery()
