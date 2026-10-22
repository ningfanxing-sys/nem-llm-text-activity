'Copy the files needed to build the manuscript tables.'
from pathlib import Path
import shutil
import table_results_conf_results as F

SUPPORT=('check_arxiv.py','claims.sty')

def install_support(root,manifest):
    root=Path(root).resolve();F.require(root!=F.MS and not F.MS.is_relative_to(root),'support target must be a source copy')
    for name in SUPPORT:
        src=F.MS/name;dest=root/name
        if dest.exists():F.require(F.sha256(dest)==F.sha256(src),'copy checker/style drift: '+name)
        else:shutil.copyfile(src,dest)
    support=root/'table_results_support';support.mkdir(exist_ok=False)
    for name in ('strict_arxiv.py','finalize_trace.py','revalidate_nonclaim.py','validate_package.py'):
        shutil.copyfile(Path(__file__).with_name(name),support/name)

    for name in ('NUMBERS_TRACE.csv','MS15_TRACE.csv'):
        src=F.MS/name
        if src.is_file():shutil.copyfile(src,support/('LEGACY_'+name))
    if (F.MS/'table_reference/main.aux').is_file():shutil.copyfile(F.MS/'table_reference/main.aux',support/'LEGACY_main.aux')
    source=F.PROJ/'release/repro_v4/MAP.csv'
    if source.is_file():shutil.copyfile(source,support/'LEGACY_MAP.csv')
    shutil.copyfile(Path(__file__).with_name('build_copy.sh'),root/'build_table_results_copy.sh')


    import json
    code=F.CODE_ROOT
    (support/'CODE_BINDING.json').write_text(json.dumps({'code_root':str(code),'code_sha256':{str(p.relative_to(code)):F.sha256(p) for p in code.rglob('*.py')},'project_root':str(F.PROJ),'supports':['archive build before main/supp','copy-local PSB trace','strict PDF/source/K8 check']},indent=2)+'\n')
    (root/'COPY_SUPPORT_MANIFEST.json').write_text(json.dumps({str(p.relative_to(root)):F.sha256(p) for p in [*(support.iterdir()),root/'build_table_results_copy.sh',root/'check_arxiv.py',root/'claims.sty'] if p.is_file()},indent=2)+'\n')
