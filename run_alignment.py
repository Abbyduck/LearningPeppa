"""Run the S01E01 Wiki/audio alignment pipeline or refresh an existing stage."""
import argparse
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
STAGES = {
    'nfa': ['alignment.prepare'],
    'export': ['alignment.export'],
    'tails': ['alignment.word_tails', 'alignment.tail_checks'],
    'report': ['alignment.report'],
    'all': ['alignment.prepare', 'alignment.export', 'alignment.word_tails',
            'alignment.tail_checks', 'alignment.report'],
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage', choices=STAGES, default='all',
                        help='Default: all; report only rebuilds the local review page.')
    args = parser.parse_args()
    python = ROOT / '.nemo-venv/Scripts/python.exe'
    if not python.is_file():
        parser.error('Missing .nemo-venv/Scripts/python.exe; see README.md for environment setup.')
    for module in STAGES[args.stage]:
        print(f'Running {module}', flush=True)
        result = subprocess.run([str(python), '-m', module], cwd=ROOT)
        if result.returncode:
            return result.returncode
    print('Review: ' + str(ROOT / 'output/forced_alignment/S01E01/review.html'))
    return 0


if __name__ == '__main__':
    sys.exit(main())
