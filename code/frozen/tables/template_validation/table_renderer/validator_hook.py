'Check abstract assertions against the specified source metadata.'
from pathlib import Path
import re
import table_results_conf_results as F
from check_arxiv import mask_comments


def patched_validator(text):

    lines=(F.MS/'TABLE_RESULTS_VALIDATE_MS12.diff').read_text().splitlines(True)
    start=next(i for i,line in enumerate(lines) if line.startswith('@@'))+1
    hunk=lines[start:]
    F.require(all(line[:1] in (' ','+','-') for line in hunk),'invalid validator proposal')
    old=''.join(line[1:] for line in hunk if line[0] in (' ','-'))
    new=''.join(line[1:] for line in hunk if line[0] in (' ','+'))
    F.require(text.count(old)==1,'validator source differs from reviewed hook location')
    text=text.replace(old,new,1)
    anchor="if (MS/'MS12_CONF_FILL_RECEIPT.json').exists():"
    replacement="if (MS/'TABLE_RESULTS_RECEIPT.json').exists():\n    conf_access='The manuscript uses the hash-bound inference_design post-score record through table_results_conf_results.py; its source receipt, complete producer fields and generated source identities are recorded in TABLE_RESULTS_RECEIPT.json.'\nel"+anchor
    F.require(text.count(anchor)==1,'validator access-state anchor drift')
    return text.replace(anchor,replacement,1)


def abstract_source(root,registry):
    root=Path(root).resolve()
    def expand(path,seen):
        path=path.resolve();F.require(path.is_relative_to(root) and path not in seen,'abstract input escapes copy or cycles')
        text=path.read_text()
        def replace(m):
            rel=m.group(1);return expand(root/(rel if rel.endswith('.tex') else rel+'.tex'),seen|{path})
        return re.sub(r'\\input\{([^}]+)\}',replace,text)
    text=expand(root/'sections/abstract.tex',set())
    from check_table_sources import MACRO
    for m in MACRO.finditer(text):F.require('/'.join(m.groups()) in registry,'unknown abstract claim')
    return MACRO.sub(lambda m:F.tex(registry['/'.join(m.groups())]),text)


def abstract_plain(root,registry,plain):

    return plain(abstract_source(root,registry)).replace(r'\%','%').replace(r'\&','&').strip()
