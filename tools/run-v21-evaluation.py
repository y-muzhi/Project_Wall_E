"""Offline by default; execute only the currently authorized bounded V2.1 cohort."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from formation_evaluation_execution import main

if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as error:
        print('V2.1 evaluation stopped: ' + type(error).__name__ + '; no retry', file=sys.stderr)
        raise SystemExit(1) from None
