"""Create the existing review batch bound to one actual target document."""
from backend.app.documents.patch_application import preview_patches
from backend.app.documents.scopes import restore_authority
from backend.app.documents.snapshot import validate_snapshot
from backend.app.documents.sources import DocumentSources
from backend.app.infrastructure.document_repository import DocumentRepository
from backend.app.infrastructure.identifiers import EntityKind, entity_id
from backend.app.infrastructure.idempotency import canonical_input
from backend.app.infrastructure.schema_transport import compact
from backend.app.shared.command_execution import Rejected
import json


def prepare_proposal_batch(connection, run, context, patches, catalog, at):
    canonical = context.canonical;target = canonical['target'];scope = canonical['scope']
    if run['operation'] != 'PROPOSE_CHANGES' or target is None or target['kind'] != 'EXISTING':
        raise Rejected('OUTPUT_INVALID')
    current = DocumentRepository(connection).get_current(run['requirement_id'], target['document_id'])
    if current is None or current['content_version'] != target['expected_content_version'] or current['archived_at'] is not None:
        raise Rejected('CONTENT_VERSION_CONFLICT')
    snapshot = validate_snapshot(current['markdown_content'], json.loads(current['block_state_json']), DocumentSources(connection, run['requirement_id'], catalog, document_id=current['id']))
    reference = scope['scope_ref']
    if scope['scope_type'] == 'SECTION':
        reference = {'block_id': reference['heading_block_id']}
    authority = restore_authority(snapshot, 'MODIFY', scope['scope_type'], reference, {'schema_version': 1, 'targets': canonical['authorization']['allowed_targets']})
    preview_patches(snapshot, patches, authority)
    refs = canonical['source_refs']
    heads = {}
    for source in refs:
        if source['kind'] == 'REVISION':
            head = DocumentRepository(connection).get_current(run['requirement_id'], source['document_id'])
            if head is None:
                raise Rejected('SOURCE_INVALID')
            heads[head['id']] = {'document_id': head['id'], 'content_version': head['content_version']}
    def commit():
        identity = entity_id(connection, EntityKind.BATCH)
        fields = {'id': identity, 'requirement_id': run['requirement_id'], 'guide_run_id': run['id'], 'source_type': run['source_type'], 'source_id': run['source_id'],
            'title': '修改建议：'+current['name'], 'summary': run['instruction_summary'], 'status': 'PENDING', 'completion_result': None, 'error_message': None,
            'base_content_version': current['content_version'], 'applied_content_version': None, 'created_at': at, 'completed_at': None, 'updated_at': at,
            'target_document_id': current['id'], 'source_refs_json': compact(refs), 'source_heads_json': compact(list(heads.values()))}
        connection.execute('INSERT INTO suggestion_batches('+','.join(fields)+') VALUES ('+','.join('?' for _ in fields)+')', tuple(fields.values()))
        for order, patch in enumerate(patches, 1):
            item = {'id': entity_id(connection, EntityKind.SUGGESTION), 'batch_id': identity, 'order_no': order,
                **{key: patch[key] for key in ('title', 'explanation', 'impact', 'patch_operation', 'original_content', 'proposed_markdown')},
                'target_ref_json': canonical_input(patch['target_ref']), 'selector_json': None if patch['selector_json'] is None else canonical_input(patch['selector_json']),
                'proposed_data_json': None if patch['proposed_data_json'] is None else canonical_input(patch['proposed_data_json']),
                'user_edited_content': None, 'status': 'PENDING', 'validation_status': 'VALID', 'validation_error': None, 'created_at': at, 'decided_at': None, 'updated_at': at}
            connection.execute('INSERT INTO suggestions('+','.join(item)+') VALUES ('+','.join('?' for _ in item)+')', tuple(item.values()))
        return identity
    return commit
