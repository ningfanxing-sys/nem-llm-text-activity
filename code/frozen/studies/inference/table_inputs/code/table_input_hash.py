'Store the input hash used for table construction.'
from pathlib import Path

FILL_ROUND = 'validation_group_9'
ROOT = Path(__file__).resolve().parents[1]
AP = ROOT.parent
PROJ = AP.parents[2]
FILL_ROOT = PROJ / 'tables/table_renderer' / FILL_ROUND
