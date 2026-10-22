"""CONFX7 addendum 4 section 5: the fit steps start only after the post-features measurement records exist.

    python measurement_gate.py     # exit 0 when the records are in place and every bit-identity finding is true, else 5

Required records (run while the host is idle, after the features step):
- `MEMORY_MEASUREMENTS.json`: every new-worker case COMPLETE, and every old/new pair bit-identical (SPEC.md section 3);
- `SPEED_MEASUREMENTS_A3.json`: news 4 versus 7 workers and LEAR serial versus 1 and 3 workers identical (addendum 3);
- `FEASIBILITY_24H.json` and `FEASIBILITY_24H_A3.json`: present (planning records).
Only these CONFX7 records are read.
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def problems():
    found = []
    def load(name):
        try:
            return json.loads((HERE / name).read_text())
        except (OSError, ValueError) as exc:
            found.append(name + ' missing or unreadable: ' + type(exc).__name__)
            return None
    memory = load('MEMORY_MEASUREMENTS.json')
    if memory is not None:
        for entry in memory.get('cases', []):
            name = entry['case']['name']
            if ((entry['runs'].get('new') or {}).get('result') or {}).get('state') != 'COMPLETE':
                found.append('memory case not COMPLETE with the CONFX7 worker: ' + name)
            if 'old' in entry['runs'] and not all((entry.get('bit_identity') or {'missing': False}).values()):
                found.append('memory case not bit-identical between the CONFX6 and CONFX7 workers: ' + name)
        if not memory.get('cases'):
            found.append('MEMORY_MEASUREMENTS.json has no cases')
    speed = load('SPEED_MEASUREMENTS_A3.json')
    if speed is not None and speed.get('findings') != {'news_identical_4_vs_7': True, 'lear_identical_serial_vs_1_and_3': True}:
        found.append('SPEED_MEASUREMENTS_A3.json findings are not all identical')
    for name in ('FEASIBILITY_24H.json', 'FEASIBILITY_24H_A3.json'):
        load(name)
    return found


def main():
    found = problems()
    print(json.dumps({'measurement_records_accepted': not found, 'problems': found}))
    return 0 if not found else 5


if __name__ == '__main__':
    sys.exit(main())
