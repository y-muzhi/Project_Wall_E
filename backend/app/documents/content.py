"""Internal formal content transaction shared by edit, AI and batch callers.

No public generic write endpoint or private commit. The caller owns the real
transaction, execution lease and release of its exact operation afterwards.
"""
from backend.app.infrastructure.document_repository import DocumentRepository
from backend.app.infrastructure.revision_repository import RevisionRepository
from backend.app.infrastructure.requirement_repository import RequirementRepository
from backend.app.infrastructure.audit_repository import AuditRepository
from backend.app.infrastructure.identifiers import EntityKind, entity_id, increment, require_write_transaction
from backend.app.shared.command_execution import Rejected
from backend.app.shared.validation import strict_json_object
from .contracts import document_effect
from .snapshot import validate_snapshot, validate_creation_inheritance
from .sources import DocumentSources


def validate_structure(candidate, prior, current, resources):
    """Keep existing fixed specification headings; light documents are editable.

    The subset is the actual document's template headings, so omitted conditional
    sections are not silently manufactured from the full source template.
    """
    if current['document_kind'] != 'SPECIFICATION' or current['template_ref'] is None:
        return
    reference = strict_json_object(current['template_ref'])
    if reference['key'] == 'structure.specification':
        resources.collaboration.content(reference)
        profile = resources.collaboration.structure('specification')
        template = resources.template('NEW', profile['template_ref']['key'], profile['template_ref']['version'])
    else:
        template = resources.template('NEW', reference['key'], reference['version'])
    approved = {(item.level, item.text) for item in template.locked_headings}
    expected = [(identity, block.heading_level, block.plain_text) for identity, (block, metadata) in prior.by_id.items()
        if block.block_type == 'heading' and (block.heading_level, block.plain_text) in approved]
    identities = {item[0] for item in expected}
    actual = [(identity, block.heading_level, block.plain_text) for identity, (block, metadata) in candidate.by_id.items() if identity in identities]
    if actual != expected:
        raise Rejected('DOCUMENT_INVALID')


def commit_content(connection, current, snapshot, *, resources, source_type, source_id, source_refs, summary, key, at):
    require_write_transaction(connection)
    documents = DocumentRepository(connection)
    actual = documents.get_current(current['requirement_id'], current['id'])
    if actual is None:
        raise Rejected('NOT_FOUND')
    if actual['content_version'] != current['content_version']:
        raise Rejected('CONTENT_VERSION_CONFLICT')
    if actual['archived_at'] is not None:
        raise Rejected('STATE_CONFLICT')
    root = RequirementRepository(connection).get(current['requirement_id'])
    kinds = {'MANUAL_EDIT': ('MANUAL_EDITING', 'MANUAL_DRAFT'), 'GUIDE_RUN': ('GUIDE_ACTIVE', 'GUIDE_RUN'),
        'SUGGESTION_BATCH': ('SUGGESTION_REVIEWING', 'SUGGESTION_BATCH')}
    if source_type not in kinds or (root['document_work_state'], root['active_operation_type'], root['active_operation_id']) != (*kinds[source_type], source_id):
        raise Rejected('WORK_STATE_CONFLICT')
    binding = None
    if source_type == 'MANUAL_EDIT':
        binding = connection.execute("SELECT current_document_id FROM manual_edit_sessions WHERE draft_id=? AND requirement_id=? AND status='EDITING'", (source_id, root['id'])).fetchone()
    elif source_type == 'GUIDE_RUN':
        binding = connection.execute("SELECT target_document_id FROM guide_runs WHERE id=? AND requirement_id=? AND status='RUNNING' AND operation='REVISE'", (source_id, root['id'])).fetchone()
    else:
        binding = connection.execute("SELECT target_document_id FROM suggestion_batches WHERE id=? AND requirement_id=? AND status='PENDING'", (source_id, root['id'])).fetchone()
    if binding is None or binding[0] != current['id']:
        raise Rejected('SOURCE_INVALID')
    sources = DocumentSources(connection, root['id'], resources, document_id=current['id'])
    prior = validate_snapshot(actual['markdown_content'], strict_json_object(actual['block_state_json']), sources)
    candidate = validate_snapshot(snapshot.parsed.markdown, snapshot.state, sources)
    validate_creation_inheritance(candidate, prior)
    validate_structure(candidate, prior, actual, resources)
    if at < actual['updated_at']:
        raise ValueError('Content commit cannot precede the current document')
    revision = connection.execute('SELECT id FROM revisions WHERE document_id=? AND source_content_version=?', (actual['id'], actual['content_version'])).fetchone()
    if revision is None:
        raise ValueError('Current content has no immutable Revision')
    if candidate.parsed.markdown == prior.parsed.markdown and candidate.state == prior.state:
        return document_effect({'document_id': actual['id'], 'before_content_version': actual['content_version'],
            'after_content_version': actual['content_version'], 'revision_id': revision['id'], 'result': 'NO_CHANGE'})
    updated = documents.replace_current(actual, candidate, increment(actual['content_version']), at)
    revision_id = entity_id(connection, EntityKind.REVISION)
    RevisionRepository(connection).insert_content(revision_id, updated, source_refs, summary, at)
    AuditRepository(connection).record_content_commit(actual, updated, revision_id, source_type, source_id, source_refs, summary, key, at)
    from backend.app.comments.commands import revalidate_anchors
    revalidate_anchors(connection, {'requirement_id': root['id'], 'document_id': actual['id'],
        'new_document': {'markdown_content': candidate.parsed.markdown, 'block_state_json': candidate.state}}, catalog=resources)
    return document_effect({'document_id': updated['id'], 'before_content_version': actual['content_version'],
        'after_content_version': updated['content_version'], 'revision_id': revision_id, 'result': 'UPDATED'})
