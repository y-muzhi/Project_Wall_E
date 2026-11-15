"""Run a project module/script in a new process with the fixed V2 SQLite build.

Examples:
  .venv/Scripts/python.exe -B tools/python-v20.py --probe
  .venv/Scripts/python.exe -B tools/python-v20.py tools/quality_python.py ...
"""

from pathlib import Path
import runpy
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.app.infrastructure.sqlite_runtime import activate


def main() -> None:
    runtime = activate()
    arguments = sys.argv[1:]
    if arguments == ['--probe']:
        print(f'{runtime.bundle_ref}: SQLite {runtime.version}; fixed DLL identity verified')
        return
    if not arguments:
        raise SystemExit('Specify --probe, a project script, or -m project.module')
    if arguments[0] == '-m':
        if len(arguments) < 2:
            raise SystemExit('A module name is required')
        module = arguments[1]
        sys.argv = arguments[1:]
        runpy.run_module(module, run_name='__main__', alter_sys=True)
        return
    if arguments[0].startswith('-'):
        raise SystemExit('Supported forms: --probe, -m module, or a project script')
    script = (ROOT / arguments[0]).resolve(strict=True)
    if not script.is_relative_to(ROOT):
        raise SystemExit('The script must be inside this project')
    sys.argv = [str(script), *arguments[1:]]
    runpy.run_path(str(script), run_name='__main__')


if __name__ == '__main__':
    main()
