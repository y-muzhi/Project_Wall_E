"""Cross-parser contract check of real browser output, using fixture origins.

This is a verification tool, not a repository or production source verifier.
It does not claim HTTP, database relationship, authorization or save success.
"""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app.infrastructure.database import Database
from backend.app.documents.sources import DocumentSources
from backend.app.infrastructure.resources import ResourceCatalog

from backend.app.documents.snapshot import validate_snapshot  # noqa: E402
from backend.app.documents.anchors import create_selection_anchor, locate  # noqa: E402


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
    for index, entry in enumerate(report.get('strikethrough', {}).get('outputs', [])):
        records.append((f'strikethrough-{index}', entry['pair'], entry['projection']))
    for index, entry in enumerate(report.get('raw_source', {}).get('outputs', [])):
        records.append((f'raw-source-{index}', entry['pair'], entry['projection']))
    for index, entry in enumerate(report.get('source_normalization', {}).get('outputs', [])):
        records.append((f'source-normalization-{index}', entry['pair'], entry['projection']))
    receipt_count = 0
    if 'receipts' in report:
        receipt = report['receipts']
        with Database(receipt['database_path']).transaction() as connection:
            sources = DocumentSources(connection, receipt['requirement_id'], ResourceCatalog())
            for entry in receipt['outputs']:
                snapshot = validate_snapshot(entry['pair']['markdown_content'], entry['pair']['block_state_json'], sources)
                actual = [{'block_type': block.block_type, 'plain_text': block.plain_text, 'section_path': list(block.section_path)} for block in snapshot.parsed.blocks]
                if actual != entry['projection']:
                    raise AssertionError('Actual receipt roundtrip projection differs')
                receipt_count += 1
    for index, entry in enumerate(report.get('editor_selection', {}).get('records', [])):
        records.append((f'editor-selection-{index}', entry['pair'], entry['projection']))
        snapshot = validate_snapshot(entry['pair']['markdown_content'], entry['pair']['block_state_json'], fixture_origin)
        event = entry['event']
        if event['document_id'] != 90 or event['content_version'] != 3:
            raise AssertionError('Selection is not bound to the actual fixture draft context')
        anchor = create_selection_anchor(snapshot, event['block_id'], {key: event[key] for key in ('selected_text', 'prefix_text', 'suffix_text')})
        location = locate(snapshot, 'SELECTION', event['block_id'], anchor)
        if (location.start_offset, location.end_offset) != (event['start_offset'], event['end_offset']):
            raise AssertionError('Backend codepoint location differs from actual native/editor selection')
    for name, pair, expected in records:
        snapshot = validate_snapshot(pair['markdown_content'], pair['block_state_json'], fixture_origin)
        actual = [{'block_type': block.block_type, 'plain_text': block.plain_text,
                   'section_path': list(block.section_path)} for block in snapshot.parsed.blocks]
        if actual != expected:
            raise AssertionError(f'{name}: frontend/backend projection mismatch: {actual!r} != {expected!r}')
    print(json.dumps({'passed': True, 'pairs_checked': len(records)+receipt_count, 'real_source_receipt_pairs': receipt_count, 'names': [name for name, _, _ in records],
                      'scope': 'Browser/parser pairs; legacy syntax cases use explicit fixture origins, receipt cases use actual SQLite sources'}, ensure_ascii=False))


if __name__ == '__main__':
    main()
