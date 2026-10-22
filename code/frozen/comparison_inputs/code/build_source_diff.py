'Compute a source diff from saved reference files.'
import difflib
import hashlib
import json
from pathlib import Path

HERE=Path(__file__).resolve().parents[1]
PROJ=HERE.parents[1]
F12='tables/table_renderer/notice_constraints'


MODULE='"""R2 exact approved news source; installed C/T5 timestamp_checks remains mandatory."""\nfrom contextlib import contextmanager\nimport importlib.util\nfrom pathlib import Path\nimport sys\nimport table_results_conf_results as F\n\nROOT=Path(__file__).resolve().parents[1]\nCONTRACT=ROOT/\'source_overrides/PCPRIMARY_R2/NEWS_SOURCE.json\'\nCONTRACT_SHA256=\'@SHA@\'\n\ndef source_contract():\n    F.require(not CONTRACT.is_symlink() and F.sha256(CONTRACT)==CONTRACT_SHA256,\n              \'R2 exact news contract drift\')\n    return F.strict_json(CONTRACT)\n\ndef source_dependencies(association=None):\n    if association is not None:association.verify_code(CONTRACT)\n    value=source_contract()\n    result={str(CONTRACT):CONTRACT_SHA256}\n    for relative,digest in value[\'source_pins\'].items():\n        path=F.PROJ/relative\n        cursor=F.PROJ\n        for part in relative.split(\'/\'):\n            cursor=cursor/part\n            F.require(not cursor.is_symlink(),\'R2 source alias\')\n        F.require(not Path(relative).is_absolute() and \'..\' not in Path(relative).parts\n                  and path.resolve().is_relative_to(F.PROJ.resolve()),\'R2 source scope\')\n        if association is not None:association.verify_code(path)\n        F.require(path.is_file() and F.sha256(path)==digest,\'R2 exact scientific source drift: \'+relative)\n        result[str(path)]=digest\n    directory=F.PROJ/value[\'code_directory\']\n    F.require({str(p.relative_to(F.PROJ)) for p in directory.iterdir()\n               if p.suffix in (\'.py\',\'.json\') and p.name!=\'build_source_diff.py\'}\n              ==set(value[\'runtime_files\']),\'R2 closed runtime source census drift\')\n    return result\n\ndef source_module(name):\n    source_dependencies()\n    value=source_contract()\n    F.require(name in (\'news_source\',\'consumer_branch\'),\'R2 finite module name\')\n    path=F.PROJ/value[\'code_directory\']/(name+\'.py\')\n    spec=importlib.util.spec_from_file_location(\'_fill12_r2_\'+name,path)\n    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)\n    return module\n\n@contextmanager\ndef consumer_scope(producer):\n    source_dependencies()\n    with source_module(\'consumer_branch\').producer_scope(producer,source_contract()):\n        yield producer\n    source_dependencies()\n\ndef validate_primary(bundle):\n    S=source_module(\'news_source\')\n    F.require(bundle[\'days\']==S.day_set() and bundle[\'pairs\']==[[\'L_count\',\'M\'],[\'L_chen\',\'M\']],\n              \'R2 exact primary dates/family drift\')\n    F.require(bundle.get(\'subset\') is False and not bundle.get(\'unadjusted\'),\n              \'R2 primary cannot be descriptive/unadjusted\')\n    return bundle\n\ndef validate_evidence(evidence):\n    F.require(evidence.get(\'news_source\')==source_contract(),\'R2 truthful executed news source binding drift\')\n    return evidence\n'


def once(text,old,new):
    if text.count(old)!=1:raise ValueError('F12 baseline patch context drift: '+old[:80])
    return text.replace(old,new)


def build(baseline):
    baseline=Path(baseline)
    baseline_pins=json.loads((HERE/'BASELINE_INPUTS.json').read_text())
    for relative,expected in baseline_pins.items():
        if hashlib.sha256((baseline/relative).read_bytes()).hexdigest()!=expected:
            raise ValueError('F12 public baseline source drift: '+relative)
    parent=json.loads((HERE/'code/PARENT_PINS.json').read_text())
    runtime=[str((HERE/'code'/n).relative_to(PROJ)) for n in
             ('news_source.py','consumer_branch.py','PARENT_PINS.json')]
    pins={**parent,**{p:hashlib.sha256((PROJ/p).read_bytes()).hexdigest() for p in runtime}}

    old_catalog=json.loads((baseline/'R2_SYNTHETIC_METADATA_CATALOG.json').read_text())
    ap=old_catalog['executed_engineering_producer_sources']
    if len(ap)!=27:raise ValueError('Original AP27 census drift')
    contract=dict(schema='PCPRIMARY_R2_APPROVED_SCIENTIFIC_NEWS_V1',role='NEWS_PRIMARY',
        code_directory=str((HERE/'code').relative_to(PROJ)),runtime_files=runtime,
        source_pins=pins,original_ap27=ap,news_days=['2026-05-19','2026-09-30'],
        original_news_days=['2026-03-01','2026-09-30'],
        source_functions=[dict(path=runtime[0],sha256=pins[runtime[0]],functions=[
           'day_set','issue_positions','native_namespace','scoring_successor','a2_inputs',
           'ap_build','panel_hash','score_prefix','official_score','verified_prediction_view',
           'a3_successor','batch_prediction_losses','label_tree','optional_successor','evaluation_marker','score_optional_inputs']),
          dict(path=runtime[1],sha256=pins[runtime[1]],functions=['core_task','scope','producer_scope'])],
        original_and_notice_sources_unchanged=True,ap5_fixed_bytes_unchanged=True,
        production_authority=False)
    contract['acceptance_sources']={str((HERE/'tests'/n).relative_to(PROJ)):hashlib.sha256((HERE/'tests'/n).read_bytes()).hexdigest() for n in ('acceptance.py','fixtures.py','real_chain.py','run_acceptance.py','TEST_SOURCE_PINS.json')}
    contract['acceptance_public_sources']=json.loads((HERE/'tests/TEST_SOURCE_PINS.json').read_text())
    contract['acceptance_baseline_schemas']={F12+'/'+n:baseline_pins[F12+'/'+n] for n in ('G05_INTERFACE_SCHEMAS.json','ANCHOR_FORMS.json')}
    raw=(json.dumps(contract,indent=2,sort_keys=True)+'\n').encode()
    new={F12+'/source_overrides/PCPRIMARY_R2/NEWS_SOURCE.json':raw.decode(),
         F12+'/table_renderer/postcutoff_news.py':MODULE.replace('@SHA@',hashlib.sha256(raw).hexdigest())}
    rel=F12+'/table_renderer/dec11g_source_bindings.py'
    old=(baseline/rel).read_text();text=old
    text=once(text,'import table_results_conf_results as F','import table_results_conf_results as F\nfrom . import postcutoff_news as N')
    text=once(text,"    value,_=_catalog(current_public=False)\n    state=_PRODUCTION.get()",
        "    value,_=_catalog(current_public=False)\n    news=N.source_contract()\n    require(news['original_ap27']==value['executed_engineering_producer_sources'], 'R2 unchanged AP27 base')\n    state=_PRODUCTION.get()")
    text=once(text,"        return _source_map(value['executed_engineering_producer_sources'])",
        "        out=_source_map(value['executed_engineering_producer_sources'])\n        _merge(out,N.source_dependencies())\n        return out")
    text=once(text,"    return result\n\n\ndef production_dependencies", "    _merge(result,N.source_dependencies(association))\n    return result\n\n\ndef production_dependencies")
    text=once(text,"    timestamp_checks=consumer['timestamp_checks']", "    require(rd_pin.get('news_source')==N.source_contract(), 'R2 exact approved news timestamp_checks missing/changed')\n    _merge(out,{str(Path(k).relative_to(PROJ)):v for k,v in N.source_dependencies(association).items()})\n    timestamp_checks=consumer['timestamp_checks']")
    new[rel]=text
    rel=F12+'/table_renderer/joint_readings.py';old=(baseline/rel).read_text();text=old
    text=once(text,'from . import dec11g_source_bindings as D11G','from . import dec11g_source_bindings as D11G\nfrom . import postcutoff_news as N')
    text=once(text,'    return D11G.source_dependencies(SOURCE_PINS)',
        '    return {**D11G.source_dependencies(SOURCE_PINS),**N.source_dependencies()}')
    text=once(text,'        yield producer\n', '        with N.consumer_scope(producer):\n            yield producer\n')
    text=once(text,"    evidence = _json(authorities['specified_evidence'], synthetic=synthetic)",
        "    evidence = _json(authorities['specified_evidence'], synthetic=synthetic)\n    N.validate_evidence(evidence)")
    text=once(text,"    evidence=_json(authorities['specified_evidence'],synthetic=synthetic)",
        "    evidence=_json(authorities['specified_evidence'],synthetic=synthetic)\n    N.validate_evidence(evidence)")
    new[rel]=text
    rel=F12+'/table_renderer/descriptive_diagnostics.py';old=(baseline/rel).read_text();text=old
    text=once(text,'        namespace=loss_module.native_functions()',
        "        from . import postcutoff_news as N\n        namespace=N.source_module('news_source').native_namespace(loss_module.native_functions())")
    text=once(text,"    return {**prefix,**{str(F.PROJ/relative):digest for relative,digest in SOURCE_PINS.items()}}",
        "    from . import postcutoff_news as N\n    return {**prefix,**{str(F.PROJ/relative):digest for relative,digest in SOURCE_PINS.items()},**N.source_dependencies()}")
    new[rel]=text
    rel=F12+'/table_renderer/forest_supplement.py';old=(baseline/rel).read_text()
    new[rel]=once(old,"    return layer == 'subsets' or 'A1_EXPOSURE_EXCLUDED' in layer",
        "    return layer in ('subsets','readmission_free_subset','matched_support_subset') or 'A1_EXPOSURE_EXCLUDED' in layer")
    rel=F12+'/table_renderer/r12_end_to_end.py';old=(baseline/rel).read_text()
    test_hash=hashlib.sha256((HERE/'tests/acceptance.py').read_bytes()).hexdigest()
    new[rel]=old+'\n\ndef postcutoff_news_acceptance(root):\n    """D27 R2 targeted real loss-score/replay/interface acceptance, scratch only."""\n    from . import postcutoff_news as N\n    N.source_dependencies()\n    value=N.source_contract()\n    for relative,digest in {**value[\'acceptance_sources\'],**value[\'acceptance_public_sources\'],**value[\'acceptance_baseline_schemas\']}.items():\n        F.require(F.sha256(F.PROJ/relative)==digest,\'R2 exact acceptance helper drift: \'+relative)\n    path=F.PROJ/\'comparison_inputs/tests/acceptance.py\'\n    F.require(F.sha256(path)==\'@TESTSHA@\',\'R2 exact acceptance source drift\')\n    from importlib.util import spec_from_file_location,module_from_spec\n    spec=spec_from_file_location(\'_fill12_r2_acceptance\',path)\n    module=module_from_spec(spec);spec.loader.exec_module(module)\n    return module.run(root,ROOT=F.CODE_ROOT)\n'.replace('@TESTSHA@',test_hash)
    diff=[]
    for rel,text in new.items():
        reference_snapshot=(baseline/rel).read_text() if (baseline/rel).exists() else ''
        diff.extend(difflib.unified_diff(reference_snapshot.splitlines(True),text.splitlines(True),
                   fromfile='a/'+rel,tofile='b/'+rel))
    (HERE/'F12_PATCH.diff').write_text(''.join(diff))
    (HERE/'APPROVED_NEWS_SOURCE.json').write_bytes(raw)
    return new


if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--baseline',required=True)
    args=p.parse_args();build(args.baseline)
