"""Run the same offline quality checks locally and in GitHub Actions.

Usage: python tools/check-v15-offline.py [--list] [--only backend]
Dependencies must already be installed. No real AI calls or service changes.
"""
from quality_gate import main

if __name__ == '__main__':
    raise SystemExit(main())
