"""Prepare Schema210 repository resources; never open a business database."""

from pathlib import Path
import argparse
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.infrastructure.sqlite_runtime import activate

activate()

from backend.app.infrastructure.formation_schema_publish import publish_release

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--publish', required=True, metavar='NEW_RELEASE_ID')
arguments = parser.parse_args()
release = publish_release(arguments.publish)
print(release.release_id, release.schema_contract_sha256, release.manifest_sha256)
