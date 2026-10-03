"""Cross-parser contract check of real browser output, using fixture origins.

This is a verification tool, not a repository or production source verifier.
It does not claim HTTP, database relationship, authorization or save success.
"""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app.documents.snapshot import validate_snapshot  # noqa: E402


def fixture_origin(origin):
    return ((origin.actor, origin.source_type, origin.source_id) == ('SYSTEM', 'TEMPLATE', None)
            or (origin.actor, origin.source_type, origin.source_id) == ('USER', 'MANUAL_EDIT', 90))


def main():
    report = json.load(sys.stdin)
    records = []
    for entry in report['identity_types']:
        records.append((entry['name'], entry['unchanged_pair'], [
            {'block_type': block['block_type'], 'plain_text': plain, 'section_path': block['section_path']}
            for block, plain in zip(entry['unchanged_pair']['block_state_json']['blocks'], entry['projection'], strict=True)
        ]))
    for index, entry in enumerate(report['edited_snapshots']['outputs']):
        records.append((f'edited-{index}', entry['pair'], entry['projection']))
    for entry in report['identity_checks']:
        records.append((entry['name'], entry['pair'], entry['pair_projection']))
    for index, entry in enumerate(report.get('autolink_conformance', {}).get('outputs', [])):
        records.append((f'autolink-{index}', entry['pair'], entry['projection']))
    for name, pair, expected in records:
        snapshot = validate_snapshot(pair['markdown_content'], pair['block_state_json'], fixture_origin)
        actual = [{'block_type': block.block_type, 'plain_text': block.plain_text,
                   'section_path': list(block.section_path)} for block in snapshot.parsed.blocks]
        if actual != expected:
            raise AssertionError(f'{name}: frontend/backend projection mismatch: {actual!r} != {expected!r}')
    print(json.dumps({'passed': True, 'pairs_checked': len(records), 'names': [name for name, _, _ in records],
                      'scope': 'Actual browser output vs backend parser/schema; fixture provenance only'}, ensure_ascii=False))


if __name__ == '__main__':
    main()
