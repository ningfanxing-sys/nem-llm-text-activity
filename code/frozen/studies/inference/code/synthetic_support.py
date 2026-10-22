'Construct the support metadata for synthetic tests.'
from contextlib import contextmanager
from unittest.mock import patch
from pathlib import Path
import read_comparisons as P


@contextmanager
def readmission(sensitivity_tests,seal):
    if not seal.get('synthetic'):
        yield;return
    ident=seal.get('synthetic_readmission')
    P.require(ident is not None,'Synthetic readmission fixture identity required')
    path=P.checked(ident)
    P.require(path.resolve().is_relative_to(Path('/private/tmp')),'Synthetic support must be scratch-only')
    original=sensitivity_tests.readmission_free_days
    with patch.object(sensitivity_tests,'readmission_free_days',lambda:original(path,ident['sha256'])):yield
