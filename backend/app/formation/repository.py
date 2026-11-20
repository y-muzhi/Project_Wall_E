"""Same-connection formation reads and mutations; no commits or provider calls."""

from copy import deepcopy

from backend.app.infrastructure.identifiers import increment, require_write_transaction
from backend.app.shared.command_execution import Rejected

from .types import BRANCH_STATUSES, ISSUE_STATUSES, STEP_STATUSES

PROPOSAL_STATUSES = ('PENDING', 'DEFERRED', 'APPLIED', 'SUPERSEDED')


class FormationRepository:
    def __init__(self, connection):
        self.connection = connection

    def head(self, document_id, *, required=False):
        row = self.connection.execute(
            'SELECT * FROM formation_heads WHERE document_id=?', (document_id,)
        ).fetchone()
        if row is None and required:
            raise Rejected(
                'STATE_CONFLICT',
                details={
                    'reason': 'FORMATION_NOT_INITIALIZED',
                    'step_ref': None,
                    'proposal': None,
                },
            )
        return None if row is None else dict(row)

    def summary(self, document_id):
        head = self.head(document_id)
        counts = {
            'steps': dict.fromkeys(STEP_STATUSES, 0),
            'branches': dict.fromkeys(BRANCH_STATUSES, 0),
            'issues': dict.fromkeys(ISSUE_STATUSES, 0),
            'proposals': dict.fromkeys(PROPOSAL_STATUSES, 0),
            'pending_review_artifacts': 0,
        }
        if head is not None:
            for kind, table, column in (
                ('steps', 'formation_steps', 'status'),
                ('branches', 'formation_branches', 'status'),
                ('issues', 'formation_issues', 'disposition'),
                ('proposals', 'formation_proposal_index', 'disposition'),
            ):
                for row in self.connection.execute(
                    f'SELECT {column},count(*) FROM {table} WHERE document_id=? GROUP BY {column}',
                    (document_id,),
                ):
                    counts[kind][row[0]] = row[1]
            counts['pending_review_artifacts'] = self.connection.execute(
                "SELECT count(*) FROM formation_artifacts a WHERE a.document_id=? AND a.freshness='NEEDS_REVIEW' "
                'AND NOT EXISTS(SELECT 1 FROM formation_artifact_reviews r WHERE r.document_id=a.document_id '
                "AND r.reviewed_artifact_ref=a.artifact_ref AND r.result='REASSOCIATED')",
                (document_id,),
            ).fetchone()[0]
        from backend.app.shared.validation import strict_json_loads

        return {
            'document_id': document_id,
            'view_schema': 'formation_read_v21_1',
            'exists': head is not None,
            'formation_version': None if head is None else head['version'],
            'goal': None
            if head is None
            else {
                'version': head['goal_version'],
                'text': head['goal_text'],
                'source_refs': strict_json_loads(head['goal_sources_json']),
            },
            'current_step_ref': None if head is None else head['current_step_ref'],
            'active_branch_ref': None if head is None else head['active_branch_ref'],
            'counts': counts,
            # Filled by the application after checking the real document work state.
            'availability': [],
        }

    def display_position(self, document_id, step_ref, physical_position):
        if physical_position > 0:
            return physical_position
        from backend.app.shared.validation import strict_integer, strict_json_object

        row = self.connection.execute(
            'SELECT c.before_json FROM formation_event_refs r JOIN document_change_audits e ON e.id=r.event_id '
            'JOIN formation_event_changes c ON c.event_id=r.event_id AND c.entity_ref=r.ref '
            "AND c.entity_kind='STEP' WHERE r.document_id=? AND r.kind='STEP' AND r.ref=? "
            "AND json_extract(e.payload_json,'$.formation_event_type')='STEP_CANCELLED' "
            'ORDER BY r.event_id DESC LIMIT 1',
            (document_id, step_ref),
        ).fetchone()
        if row is None or row[0] is None:
            raise ValueError('Cancelled step has no immutable original display position')
        return strict_integer(strict_json_object(row[0])['position'], 'historical.position')

    def graph(self, document_id):
        head = self.head(document_id, required=True)
        collections = []
        for table, identity in (
            ('formation_steps', 'step_ref'),
            ('formation_branches', 'branch_ref'),
            ('formation_issues', 'issue_ref'),
        ):
            rows = self.connection.execute(
                f'SELECT * FROM {table} WHERE document_id=?', (document_id,)
            )
            collection = {row[identity]: dict(row) for row in rows}
            if table == 'formation_steps':
                for ref, row in collection.items():
                    row['position'] = self.display_position(document_id, ref, row['position'])
            collections.append(collection)
        edges = {'DEPENDENCY': [], 'REPLACES': []}
        for row in self.connection.execute(
            'SELECT * FROM formation_step_edges WHERE document_id=?', (document_id,)
        ):
            edges[row['kind']].append((row['from_step_ref'], row['to_step_ref']))
        return head, *collections, edges

    def save_state(self, document_id, before, mutation):
        """Save calculated changes only; audit, D and success receipt belong to this same caller."""
        require_write_transaction(self.connection)
        if not mutation.changed:
            return
        old_head, old_steps, old_branches, old_issues = before
        for table, identity, previous, current in (
            ('formation_steps', 'step_ref', old_steps, mutation.steps),
            ('formation_branches', 'branch_ref', old_branches, mutation.branches),
            ('formation_issues', 'issue_ref', old_issues, mutation.issues),
        ):
            if set(previous) != set(current):
                raise ValueError('Native state transitions cannot insert or remove entities')
            for ref, row in current.items():
                fields = {key: value for key, value in row.items() if previous[ref][key] != value}
                if not fields:
                    continue
                if identity in fields or 'document_id' in fields:
                    raise ValueError('Native transitions cannot change entity ownership')
                result = self.connection.execute(
                    f'UPDATE {table} SET '
                    + ','.join(key + '=?' for key in fields)
                    + f' WHERE document_id=? AND {identity}=?',
                    (*fields.values(), document_id, ref),
                )
                if result.rowcount != 1:
                    raise ValueError('Formation entity changed inside its shared transaction')
        result = self.connection.execute(
            'UPDATE formation_heads SET version=?,current_step_ref=?,active_branch_ref=? '
            'WHERE document_id=? AND version=?',
            (
                increment(old_head['version']),
                mutation.head['current_step_ref'],
                mutation.head['active_branch_ref'],
                document_id,
                old_head['version'],
            ),
        )
        if result.rowcount != 1:
            raise Rejected(
                'STATE_CONFLICT',
                details={'reason': 'PATH_CHANGED', 'step_ref': None, 'proposal': None},
            )

    def allocate_path_references(self, document_id, scope):
        """Called only after whole-graph validation in COMMIT, never from preview/publication."""
        require_write_transaction(self.connection)
        head = self.head(document_id, required=True)
        from .path_scope import planned_references

        steps = {
            row['step_ref']: dict(row)
            for row in self.connection.execute(
                'SELECT step_ref,next_result_no FROM formation_steps WHERE document_id=?',
                (document_id,),
            )
        }
        mapping, next_results, next_step = planned_references(head, scope, steps)
        result = self.connection.execute(
            'UPDATE formation_heads SET next_step_no=? WHERE document_id=? AND next_step_no=?',
            (next_step, document_id, head['next_step_no']),
        )
        if result.rowcount != 1:
            raise ValueError('Formation step allocator changed inside the transaction')
        for owner, next_number in next_results.items():
            if owner not in mapping:
                self.connection.execute(
                    'UPDATE formation_steps SET next_result_no=? WHERE document_id=? AND step_ref=?',
                    (next_number, document_id, owner),
                )
        return mapping, deepcopy(next_results)
