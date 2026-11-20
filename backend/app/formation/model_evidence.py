"""Resolve only material addresses actually carried in this counted round."""

from backend.app.guide.progress_application import ProgressInvalid, resolve_sources
from backend.app.requirements.source_refs import verify_source_refs


class ModelEvidence:
    def __init__(self, connection, root, context, catalog):
        self.connection = connection
        self.root = root
        self.context = context
        self.catalog = catalog
        formation = context.canonical['formation']
        self.visible = {
            kind: {row['ref'] for row in formation['coverage']['included'] if row['kind'] == kind}
            for kind in ('STEP', 'BRANCH', 'ISSUE', 'ARTIFACT')
        }
        self.step_refs = set(self.visible['STEP'])
        step = formation['selected_step']
        if step is not None:
            self.step_refs.update(step['dependencies'])
            self.step_refs.update(step['replaces_step_refs'])
        self.blocks = {
            block['ref']: (document, block)
            for document in context.input['documents']
            for block in document['blocks']
        }

    def sources(self, refs):
        sources = resolve_sources(refs, self.context)
        verify_source_refs(
            self.connection, self.root['id'], sources, resources=self.catalog.collaboration
        )
        return sources

    def block_ids(self, refs):
        result = []
        basis = self.context.canonical['formation']['basis']
        for ref in refs:
            pair = self.blocks.get(ref)
            if pair is None:
                raise ProgressInvalid('Coverage is not an actually transmitted block alias')
            document, block = pair
            if (
                document['document_id'] != self.root['assistant_document_id']
                or document['revision_id'] != basis['document_revision_id']
            ):
                raise ProgressInvalid('Coverage must address this actual frozen current Revision')
            if block['block_id'] in result:
                raise ProgressInvalid('Duplicate block coverage')
            result.append(block['block_id'])
        return result

    def require_visible(self, kind, ref, *, newly_declared=(), full=True):
        if ref in newly_declared:
            return
        visible = self.visible[kind] if full or kind != 'STEP' else self.step_refs
        if ref not in visible:
            raise ProgressInvalid(
                'An unread database identity cannot grant model mutation authority'
            )
