"""One explicit formation version basis across a caller-owned content transaction."""

from backend.app.infrastructure.identifiers import increment, require_write_transaction
from backend.app.infrastructure.requirement_repository import RequirementRepository

from .repository import FormationRepository
from .state_commands import version_basis


class FormationTransaction:
    def __init__(self, connection, root, head):
        self.connection = connection
        self.requirement_id = root['id']
        self.document_id = root['assistant_document_id']
        if head is None:
            document = self.document()
            self.before = {
                'discussion_version': root['discussion_version'],
                'formation_version': None,
                'goal_version': None,
                'document_revision_id': document['revision_id'],
                'content_version': document['content_version'],
            }
            self.focus_before = {'current_step_ref': None, 'active_branch_ref': None}
        else:
            self.before = version_basis(root, head, self.document())
            self.focus_before = {
                name: head[name] for name in ('current_step_ref', 'active_branch_ref')
            }

    def document(self):
        row = self.connection.execute(
            'SELECT d.content_version,r.id AS revision_id FROM requirement_documents d JOIN revisions r '
            'ON r.document_id=d.id AND r.source_content_version=d.content_version WHERE d.id=? AND d.requirement_id=?',
            (self.document_id, self.requirement_id),
        ).fetchone()
        if row is None:
            raise ValueError('Formation transaction lost its current Revision')
        return row

    def root(self):
        root = RequirementRepository(self.connection).get_for_document(
            self.requirement_id, self.document_id
        )
        if root is None:
            raise ValueError('Formation transaction lost its owner')
        return root

    def touch(self, at):
        """Join already-applied same-round D/F changes; each counter advances at most once."""
        require_write_transaction(self.connection)
        root = self.root()
        old_d = self.before['discussion_version']
        if root['discussion_version'] == old_d:
            root = RequirementRepository(self.connection).advance_discussion(root, at)
        elif root['discussion_version'] != increment(old_d):
            raise ValueError('One transaction cannot advance D more than once')
        repository = FormationRepository(self.connection)
        head = repository.head(self.document_id, required=True)
        old_f = self.before['formation_version']
        if old_f is None:
            if head['version'] != 1:
                raise ValueError('A new formation begins at its real version one')
        elif head['version'] == old_f:
            changed = self.connection.execute(
                'UPDATE formation_heads SET version=? WHERE document_id=? AND version=?',
                (increment(old_f), self.document_id, old_f),
            )
            if changed.rowcount != 1:
                raise ValueError('Formation version changed inside its owner transaction')
        elif head['version'] != increment(old_f):
            raise ValueError('One transaction cannot advance F more than once')
        return self.versions()

    def versions(self):
        return version_basis(
            self.root(),
            FormationRepository(self.connection).head(self.document_id, required=True),
            self.document(),
        )


def capture_transaction(connection, requirement_id, document_id):
    """A normal content update neither upgrades old schemas nor initializes a formation."""
    require_write_transaction(connection)
    if (
        connection.execute(
            "SELECT 1 FROM sqlite_schema WHERE type='table' AND name='formation_heads'"
        ).fetchone()
        is None
    ):
        return None
    head = FormationRepository(connection).head(document_id)
    if head is None:
        return None
    root = RequirementRepository(connection).get_for_document(requirement_id, document_id)
    if root is None:
        raise ValueError('Formation head has no real current owner')
    return FormationTransaction(connection, root, head)
