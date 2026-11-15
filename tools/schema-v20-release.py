"""Prepare repository Schema200 resources through the fixed runtime only."""

from backend.app.infrastructure.schema_v20_publish import main


if __name__ == '__main__':
    raise SystemExit(main())
