'Dispatch notice calculations after checking input hashes.'
import inspect
import json
import os
from pathlib import Path
import sys
from evaluator.validation import require

HERE = Path(__file__).absolute().parent


def _association(association):
    module = sys.modules.get(type(association).__module__)
    expected = HERE.parents[4]/'studies/batch_estimation/batch_checks/statistics/consumer_roots.py'
    require(module is not None and Path(getattr(module, '__file__', '/')).absolute() == expected
        and type(association) is getattr(module, 'Association', None) and module.ACTIVE is association,
        'Actual installed C scientific association required')
    association.verify_code(expected)
    association.verify_t5_coverage()
    association._ap_runtime.member(__file__)
    require(association._official_ready is not None, 'Original capture and R2 completion required')
    association._check_official_score(association._official_ready)
    return association


def rd_joint(*, association, request, argv, scientific_scope):
    phase = os.environ.get('SCORING_PHASE', 'prepare')
    require(phase in ('accept', 'source_runtime'), 'Prepare: notice_delays dispatcher cannot execute')
    association = _association(association)
    require(callable(scientific_scope) and isinstance(argv, list), 'Exact C dispatcher ABI')
    require(request.get('schema') == 'C_SCORING_POSTSCORE_REQUEST_V1', 'C postscore request schema')
    require(request.get('score_views') == association._official_ready['view_inputs'], 'Both verified views required')
    if phase == 'accept':
        require(association.synthetic is True and request.get('function') == 'artificial_projection' and not argv,
                'Accept only permits the explicit artificial scalar fixture operation')
        from evaluator.api import project_joint
        values = request.get('function_kwargs', {})
        require(set(values) == {'record', 'specified_task', 'provenance', 'schema', 'fixture_root'},
                'Artificial projection request census')
        result = project_joint(**values)
        association._ap_runtime.member(__file__)
        association._check_official_score(association._official_ready)
        return result


    raise RuntimeError('PENDING_OWNER_CONTRACT: actual AP author/input validation and independent C/G42 native eligibility ABI')
