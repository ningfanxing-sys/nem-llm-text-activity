'Parse numerical TeX fragments and escape prose strings.'
import re
import table_results_conf_results as F
MATH_COMMANDS={'Delta','kappa','ddagger','dagger','mathrm','text','pm','le','ge','times','quad','cdot','sigma','bar'}
PROSE_COMMANDS={'ref','eqref','pageref','cite','citep','citet','emph','textit','textbf','texttt','mathrm'}

def check_fragment(value,math=False):
    F.require(not re.search(r'(?<!\\)(?:\\\\)*%',value),'unescaped percent in generated TeX fragment')
    commands=re.findall(r'\\([A-Za-z]+)',value)
    F.require(set(commands)<=(MATH_COMMANDS if math else PROSE_COMMANDS),'unapproved generated TeX command')
    F.require(value.count('{')==value.count('}') and '\n' not in value,'unbalanced generated TeX fragment')
    if math:F.require(bool(re.fullmatch(r'[A-Za-z0-9+.,;:=<>/ \t\[\](){}_^%\\−–-]*',value)),'unsupported math fragment')
    return value

def claim_tex(value):

    pattern=r'(\$[^$\n]+\$|\\\([^\n]*?\\\)|\\(?:ref|eqref|pageref|citep?|citet|emph|textit|textbf|texttt|mathrm)(?:\[[^\]\n]+\])?\{[^{}\n]*\}|\\[%&#_$ ]|\\\\)'
    parts=re.split(pattern,str(value));out=[]
    for i,p in enumerate(parts):
        if not p:continue
        if i%2:
            if p.startswith('$'):check_fragment(p[1:-1],True)
            elif p.startswith(r'\('):check_fragment(p[2:-2],True)
            elif len(p)==2:pass
            else:check_fragment(p)
            out.append(p)
        else:
            F.require('\\' not in p and '$' not in p,'unparsed TeX in generated value: '+repr(p[:100]))
            out.append(F.tex(p))
    return ''.join(out)
