"""Program-bound AI document results, shared snapshots/commit/anchor path."""
from collections import Counter
from difflib import SequenceMatcher
import json

from backend.app.documents.content import commit_content, validate_structure
from backend.app.documents.contracts import document_effect
from backend.app.documents.markdown import parse_markdown
from backend.app.documents.patch_validation import prove_selection
from backend.app.documents.snapshot import Provenance, create_snapshot, assign_identities, validate_snapshot, validate_creation_inheritance
from backend.app.documents.sources import DocumentSources
from backend.app.documents.scopes import restore_authority
from backend.app.infrastructure.document_repository import DocumentRepository
from backend.app.infrastructure.revision_repository import RevisionRepository
from backend.app.infrastructure.identifiers import EntityKind, entity_id, block_id
from backend.app.infrastructure.idempotency import canonical_input
from backend.app.shared.command_execution import Rejected

KINDS = {'brief': 'REQUIREMENT_BRIEF', 'design': 'DESIGN', 'specification': 'SPECIFICATION'}


def _refs(context):
    result = {canonical_input(source): source for source in context.canonical['source_refs']}
    source = {'kind': 'MESSAGE', 'message_id': context.canonical['current_message']['message_id']}
    result.setdefault(canonical_input(source), source)
    return list(result.values())


def prepare_document_result(connection, run, context, result, catalog, at):
    canonical = context.canonical
    target = canonical['target']
    if target is None or run['operation'] not in ('GENERATE', 'REVISE'):
        raise Rejected('OUTPUT_INVALID')
    provenance = Provenance('AI', 'GUIDE_RUN', run['id'])
    if run['operation'] == 'GENERATE':
        if target['kind'] != 'NEW' or result['name'] != target['name'] or result['document_kind'] != target['document_kind']:
            raise Rejected('OUTPUT_INVALID')
        snapshot = create_snapshot(result['markdown_content'], provenance, at, lambda origin: origin == provenance)
        reference = None if target['template_ref'] is None else catalog.collaboration.reference(target['template_ref']['key'], target['template_ref']['version'])
        if result['document_kind'] == 'specification':
            template = catalog.template('NEW', 'new-requirement', 'v4')
            expected = [(heading.level, heading.text) for heading in template.locked_headings]
            approved = set(expected)
            headings = [(block.heading_level, block.plain_text) for block in snapshot.parsed.blocks if block.block_type == 'heading' and (block.heading_level, block.plain_text) in approved]
            if headings != expected:
                raise Rejected('OUTPUT_INVALID')
        def commit():
            identity = entity_id(connection, EntityKind.DOCUMENT)
            origin = {'kind': 'MESSAGE', 'message_id': canonical['current_message']['message_id']}
            current = DocumentRepository(connection).create_current(identity, run['requirement_id'], snapshot, at,
                name=target['name'], document_kind=KINDS[target['document_kind']], template_ref=reference, origin=origin)
            revision_id = entity_id(connection, EntityKind.REVISION)
            RevisionRepository(connection).insert_content(revision_id, current, _refs(context), result['change_summary'], at)
            payload = {'source_refs': _refs(context), 'change_summary': result['change_summary'], 'idempotency_key': run['idempotency_key']}
            connection.execute("INSERT INTO document_change_audits(id,requirement_id,document_id,source_type,source_id,reason_code,before_content_version,after_content_version,created_at,event_type,revision_id,guide_run_id,payload_json) VALUES (?,?,?,'GUIDE_RUN',?,'CONTENT_CREATE',NULL,1,?,'CONTENT_COMMITTED',?,?,?)",
                (entity_id(connection, EntityKind.DOCUMENT_AUDIT), run['requirement_id'], identity, run['id'], at, revision_id, run['id'], canonical_input(payload)))
            # Once its actual event exists, provenance is checked using the same
            # repository lookup as every later edit and historical read.
            validate_snapshot(snapshot.parsed.markdown, snapshot.state, DocumentSources(connection, run['requirement_id'], catalog, document_id=identity))
            return document_effect({'document_id': identity, 'before_content_version': None, 'after_content_version': 1, 'revision_id': revision_id, 'result': 'CREATED'})
        return commit
    if target['kind'] != 'EXISTING':
        raise Rejected('OUTPUT_INVALID')
    current = DocumentRepository(connection).get_current(run['requirement_id'], target['document_id'])
    frozen = next(document for document in canonical['documents'] if document['document_id'] == target['document_id'] and document['content_version'] == target['expected_content_version'])
    if result['name'] != frozen['name'] or result['document_kind'] != frozen['document_kind']:
        raise Rejected('OUTPUT_INVALID')
    if current is None or current['content_version'] != target['expected_content_version']:
        raise Rejected('CONTENT_VERSION_CONFLICT')
    sources = DocumentSources(connection, run['requirement_id'], catalog, document_id=current['id'])
    prior = validate_snapshot(current['markdown_content'], json.loads(current['block_state_json']), sources)
    scope = canonical['scope'];reference = scope['scope_ref']
    if scope['scope_type'] == 'SECTION':
        reference = {'block_id': reference['heading_block_id']}
    authority = restore_authority(prior, 'MODIFY', scope['scope_type'], reference, {'schema_version': 1, 'targets': canonical['authorization']['allowed_targets']})
    markdown = _scope_markdown(prior, result['markdown_content'], authority, scope['scope_type'])
    candidate = _derive_snapshot(prior, markdown, authority, provenance, sources, at, scope_type=scope['scope_type'])
    validate_creation_inheritance(candidate, prior)
    validate_structure(candidate, prior, current, catalog)
    def commit():
        return commit_content(connection, current, candidate, resources=catalog, source_type='GUIDE_RUN', source_id=run['id'],
            source_refs=_refs(context), summary=result['change_summary'], key=run['idempotency_key'], at=at)
    return commit


def _scope_markdown(prior, markdown, authority, scope_type):
    """The frozen scope decides interpretation; never infer local vs full text."""
    if scope_type == 'DOCUMENT': return markdown
    writable = {target.block_id for target in authority.allowed_targets}
    blocks = [(block, identity) for identity, (block, _) in prior.by_id.items() if identity in writable]
    if not blocks: raise Rejected('OUTPUT_INVALID')
    first, last = blocks[0][0], blocks[-1][0]
    parsed = parse_markdown(markdown)
    if scope_type in ('BLOCK', 'SELECTION') and len(parsed.blocks) != 1:
        raise Rejected('OUTPUT_INVALID')
    if scope_type == 'SECTION' and (not parsed.blocks or parsed.blocks[0].heading_level != first.heading_level or
            any(block.heading_level is not None and block.heading_level <= first.heading_level for block in parsed.blocks[1:])):
        raise Rejected('OUTPUT_INVALID')
    # A model need not manufacture the original block's final line terminator.
    # Reuse that terminator inside the replaceable span; all outside bytes stay.
    if markdown and not markdown.endswith(('\r', '\n')):
        for ending in ('\r\n', '\n', '\r'):
            if last.markdown.endswith(ending): markdown += ending;break
    return prior.parsed.markdown[:first.start_offset]+markdown+prior.parsed.markdown[last.end_offset:]


def _derive_snapshot(prior, markdown, authority, provenance, sources, at, *, scope_type):
    """Exact block alignment, never fuzzy identity or a scope expansion.

    Whole returned source must prove every outside block and boundary intact.
    Ambiguous movement of repeated blocks is rejected rather than reassigning
    an existing comment's identity to another textual occurrence.
    """
    parsed = parse_markdown(markdown)
    if markdown == prior.parsed.markdown:
        return prior
    before, after = list(prior.parsed.blocks), list(parsed.blocks)
    ids = list(prior.by_id);allowed = {target.block_id: target for target in authority.allowed_targets}
    # Blank target permits its first whole-document content; no guessed block.
    if not before:
        if authority.allowed_targets:
            raise Rejected('OUTPUT_INVALID')
        next_id = prior.next_block_id;identities = []
        for _ in parsed.blocks:
            identity, next_id = block_id(next_id);identities.append(identity)
        return assign_identities(markdown, identities, next_id, prior, provenance, at, sources)
    writable = [index for index, identity in enumerate(ids) if identity in allowed]
    if not writable:
        raise Rejected('OUTPUT_INVALID')
    start, end = min(writable), max(writable)+1
    prefix = '' if scope_type == 'DOCUMENT' else prior.parsed.markdown[:before[start].start_offset]
    suffix = '' if scope_type == 'DOCUMENT' else prior.parsed.markdown[before[end-1].end_offset:]
    if not markdown.startswith(prefix) or not markdown.endswith(suffix) or len(markdown) < len(prefix)+len(suffix):
        raise Rejected('OUTPUT_INVALID')
    old_keys = [(block.block_type, block.markdown) for block in before]
    new_keys = [(block.block_type, block.markdown) for block in after]
    mapping = {};next_id = prior.next_block_id
    old_start = new_start = 0;old_end = len(before);new_end = len(after)
    if scope_type != 'DOCUMENT':
        old_start = new_start = start;old_end = end;new_end = len(after)-(len(before)-end)
        if new_end < new_start or old_keys[:start] != new_keys[:start] or old_keys[end:] != new_keys[new_end:]:
            raise Rejected('OUTPUT_INVALID')
        mapping.update((index, ids[index]) for index in range(start))
        mapping.update((new_end+offset, ids[end+offset]) for offset in range(len(before)-end))
    # Exact frozen outside spans already prove those identities, including
    # repeated text. Only the authorized local span needs content alignment.
    old_counts, new_counts = Counter(old_keys[old_start:old_end]), Counter(new_keys[new_start:new_end])
    matcher = SequenceMatcher(None, old_keys[old_start:old_end], new_keys[new_start:new_end], autojunk=False)
    for kind, left, right, new_left, new_right in matcher.get_opcodes():
        left += old_start;right += old_start;new_left += new_start;new_right += new_start
        if kind == 'equal':
            for old_index, new_index in zip(range(left, right), range(new_left, new_right)):
                key = old_keys[old_index]
                if old_index != new_index and (old_counts[key] > 1 or new_counts[key] > 1):
                    raise Rejected('OUTPUT_INVALID')
                mapping[new_index] = ids[old_index]
            continue
        for old_index in range(left, right):
            target = allowed.get(ids[old_index])
            operation = 'DELETE_BLOCK' if kind == 'delete' else 'REPLACE_BLOCK'
            if target is None or operation not in target.operations:
                raise Rejected('OUTPUT_INVALID')
            if target.selection_range is not None:
                if right-left != 1 or new_right-new_left != 1:
                    raise Rejected('OUTPUT_INVALID')
                prove_selection(before[old_index], after[new_left].markdown, target.selection_range)
            if target.row_selectors is not None:
                # A restricted row grant requires the existing precise row
                # patch algorithm; a whole-table return cannot override it.
                raise Rejected('OUTPUT_INVALID')
        if kind == 'insert':
            before_target = allowed.get(ids[left]) if left < len(ids) else None
            after_target = allowed.get(ids[left-1]) if left else None
            if not (before_target and 'INSERT_BEFORE' in before_target.operations or after_target and 'INSERT_AFTER' in after_target.operations):
                raise Rejected('OUTPUT_INVALID')
        for offset, new_index in enumerate(range(new_left, new_right)):
            if kind == 'replace' and left+offset < right:
                mapping[new_index] = ids[left+offset]
            else:
                identity, next_id = block_id(next_id);mapping[new_index] = identity
    snapshot = assign_identities(markdown, [mapping[index] for index in range(len(after))], next_id, prior, provenance, at, sources)
    for identity, (block, _) in prior.by_id.items():
        if identity in allowed:
            continue
        actual = snapshot.by_id.get(identity)
        if actual is None or actual[0].markdown != block.markdown or actual[0].section_path != block.section_path:
            raise Rejected('OUTPUT_INVALID')
    return snapshot
