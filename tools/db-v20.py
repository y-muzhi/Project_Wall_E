"""Explicit DB20 maintenance. Run only through the fixed SQLite bootstrap.

.venv/Scripts/python.exe -B -X utf8 tools/python-v20.py tools/db-v20.py --help
No default database, service management or automatic migration is provided.
"""

from backend.app.infrastructure.schema_v20_cli import main


if __name__ == '__main__':
    raise SystemExit(main())
