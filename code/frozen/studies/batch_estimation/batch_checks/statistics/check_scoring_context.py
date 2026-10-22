'Dispatch scoring with the recorded computation context.'
import os
from pathlib import Path
import sys
HERE=Path(__file__).absolute().parents[0]
def main():
    if os.environ.get('SCORING_PHASE','prepare')=='prepare':raise PermissionError('Prepare cannot dispatch controllers')
    sys.path.insert(0,str(HERE))
    from dispatch import main as dispatch
    required=['SCORING_PROJECT','SCORING_REQUEST','SCORING_REQUEST_BYTES','SCORING_REQUEST_SHA256','SCORING_REQUEST_PROVENANCE','SCORING_REQUEST_PROVENANCE_BYTES','SCORING_REQUEST_PROVENANCE_SHA256']
    if any(not os.environ.get(x) for x in required):raise PermissionError('Exact inherited reviewed dispatch context missing')
    argv=['postscore','--project',os.environ['SCORING_PROJECT'],'--request',os.environ['SCORING_REQUEST'],
          '--request-bytes',os.environ['SCORING_REQUEST_BYTES'],'--request-sha256',os.environ['SCORING_REQUEST_SHA256'],'--request-provenance',os.environ['SCORING_REQUEST_PROVENANCE'],'--request-provenance-bytes',os.environ['SCORING_REQUEST_PROVENANCE_BYTES'],'--request-provenance-sha256',os.environ['SCORING_REQUEST_PROVENANCE_SHA256']]
    if os.environ.get('SCORING_PHASE')=='accept':argv.append('--synthetic')
    return dispatch([*argv,'--',*sys.argv[1:]],forced_consumer='check_scoring_context')
if __name__=='__main__':main()
