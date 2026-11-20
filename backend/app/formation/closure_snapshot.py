"""Streaming closure facts: immutable scalar items plus one bounded evidence row at a time."""

from contextlib import closing
from dataclasses import dataclass

from backend.app.infrastructure.identifiers import require_write_transaction
from backend.app.shared.json_canonical import canonical_input

from .artifact_links import current_artifact_matches
from .digests import ArrayDigest, measured


@dataclass(frozen=True)
class ClosurePlan:
    connection: object
    head: dict
    items: object


class ClosureBuilder:
    def __init__(
        self,
        connection,
        *,
        root,
        step,
        document,
        command,
        event_id,
        message_id,
        sources,
        current_blocks,
    ):
        self.connection = connection
        self.document_id = root['assistant_document_id']
        self.step = step
        self.document = document
        self.command = command
        self.event_id = event_id
        self.message_id = message_id
        self.sources = sources
        self.current_blocks = current_blocks
        self.result_actions = {item['result_ref']: item for item in command['result_dispositions']}
        self.issue_actions = {item['ref']: item for item in command['issue_dispositions']}
        self.branch_actions = {item['ref']: item for item in command['branch_dispositions']}

    def _rows(self, query, parameters):
        cursor = self.connection.execute(query, parameters)
        try:
            for row in cursor:
                yield dict(row)
        finally:
            cursor.close()

    def artifacts(self, result_ref):
        yield from self._rows(
            'SELECT a.* FROM formation_artifacts a JOIN formation_artifact_results ar '
            'ON ar.document_id=a.document_id AND ar.artifact_ref=a.artifact_ref '
            'WHERE a.document_id=? AND ar.result_ref=? AND NOT EXISTS('
            'SELECT 1 FROM formation_artifact_reviews r WHERE r.document_id=a.document_id '
            "AND r.reviewed_artifact_ref=a.artifact_ref AND r.result='REASSOCIATED') "
            'ORDER BY CAST(substr(a.artifact_ref,2) AS INTEGER)',
            (self.document_id, result_ref),
        )

    def ranges(self, artifact_ref):
        yield from self._rows(
            'SELECT role,ordinal,revision_id,block_id,block_digest FROM formation_artifact_ranges '
            "WHERE document_id=? AND artifact_ref=? ORDER BY CASE role WHEN 'ORIGIN' THEN 0 ELSE 1 END,revision_id,block_id",
            (self.document_id, artifact_ref),
        )

    def artifact_matches(self, artifact):
        return current_artifact_matches(
            self.connection, self.document_id, artifact, self.current_blocks
        )

    def result_evidence(self, result_ref, explicit_sources):
        ordinal = 0
        for artifact in self.artifacts(result_ref):
            ordinal += 1
            range_count, range_digest = measured(
                {key: item[key] for key in ('role', 'revision_id', 'block_id', 'block_digest')}
                for item in self.ranges(artifact['artifact_ref'])
            )
            yield {
                'kind': 'ARTIFACT',
                'ordinal': ordinal,
                'artifact_ref': artifact['artifact_ref'],
                'source_event_ref': artifact['source_event_id'],
                'origin_revision_id': artifact['origin_revision_id'],
                'checked_against_revision_id': artifact['checked_against_revision_id'],
                'freshness': artifact['freshness'],
                'review_reason': artifact['review_reason'],
                'range_count': range_count,
                'range_digest': range_digest,
            }
        for artifact in self.artifacts(result_ref):
            for item in self.ranges(artifact['artifact_ref']):
                ordinal += 1
                yield {
                    'kind': 'RANGE',
                    'ordinal': ordinal,
                    'artifact_ref': artifact['artifact_ref'],
                    **{
                        key: item[key]
                        for key in ('role', 'revision_id', 'block_id', 'block_digest')
                    },
                }
        for source in self.sources.result(
            self.document_id, self.step['step_ref'], result_ref, explicit_sources
        ):
            ordinal += 1
            yield {'kind': 'SOURCE', 'ordinal': ordinal, 'source_ref': source}

    def result_item(self, result, ordinal):
        action = self.result_actions.get(result['result_ref'])
        explicit_sources = [] if action is None else action['source_refs']
        artifacts = range_count = source_count = 0
        evidence_digest = ArrayDigest()
        evidence_count = 0
        for evidence in self.result_evidence(result['result_ref'], explicit_sources):
            evidence_count += 1
            if evidence['kind'] == 'ARTIFACT':
                artifacts += 1
            elif evidence['kind'] == 'RANGE':
                range_count += 1
            else:
                source_count += 1
            evidence_digest.append(evidence)
        status = 'OUTSTANDING'
        if action is not None and action['status'] == 'LANDED' and result['kind'] == 'CONTENT':
            requested = set(action['artifact_refs'])
            matches = {
                row['artifact_ref']
                for row in self.artifacts(result['result_ref'])
                if self.artifact_matches(row)
            }
            if requested and requested <= matches:
                status = 'LANDED'
        elif (
            action is not None
            and action['status'] == 'ANALYZED'
            and result['kind'] == 'ANALYSIS'
            and explicit_sources
        ):
            status = 'ANALYZED'
        payload = {
            'kind': 'RESULT',
            'ordinal': ordinal,
            'result_ref': result['result_ref'],
            'description': result['description'],
            'result_kind': result['kind'],
            'status': status,
            'artifact_count': artifacts,
            'range_count': range_count,
            'source_count': source_count,
            'evidence_count': evidence_count,
            'evidence_digest': evidence_digest.hexdigest(),
        }
        return payload, lambda: self.result_evidence(result['result_ref'], explicit_sources)

    def remaining_item(self, kind, row, ordinal):
        ref = row['issue_ref'] if kind == 'ISSUE' else row['branch_ref']
        state = row['disposition'] if kind == 'ISSUE' else row['status']
        action = (self.issue_actions if kind == 'ISSUE' else self.branch_actions).get(ref)
        disposition, target, reason = 'KEEP_OPEN', None, None
        if state == 'RESOLVED':
            disposition = 'RESOLVED'
        elif action is not None:
            disposition, target, reason = (
                action['disposition'],
                action['to_step_ref'],
                action['reason'],
            )
            if disposition in ('DEFERRED', 'DROPPED'):
                state = disposition

        def evidence():
            source_rows = (
                self.sources.issue(self.document_id, ref)
                if kind == 'ISSUE'
                else self.sources.branch(self.document_id, ref)
            )
            for index, source in enumerate(source_rows, 1):
                yield {'kind': 'SOURCE', 'ordinal': index, 'source_ref': source}

        count, digest = measured(evidence())
        return {
            'kind': kind,
            'ordinal': ordinal,
            'ref': ref,
            'description': row['description'] if kind == 'ISSUE' else row['question'],
            'state_at_close': state,
            'disposition': disposition,
            'to_step_ref': target,
            'reason': reason,
            'source_count': count,
            'evidence_count': count,
            'evidence_digest': digest,
        }, evidence

    def items(self):
        ordinal = 0
        # Stable kind order, then stable allocated identity. No terminal/lifetime limit.
        for kind, table, identity, owner in (
            ('RESULT', 'formation_results', 'result_ref', 'step_ref'),
            ('ISSUE', 'formation_issues', 'issue_ref', 'step_ref'),
            ('BRANCH', 'formation_branches', 'branch_ref', 'return_step_ref'),
        ):
            sort_key = (
                f"CAST(substr({identity},instr({identity},'.o')+2) AS INTEGER)"
                if kind == 'RESULT'
                else f'CAST(substr({identity},2) AS INTEGER)'
            )
            for row in self._rows(
                f'SELECT * FROM {table} WHERE document_id=? AND {owner}=? ORDER BY {sort_key}',
                (self.document_id, self.step['step_ref']),
            ):
                ordinal += 1
                yield (
                    self.result_item(row, ordinal)
                    if kind == 'RESULT'
                    else self.remaining_item(kind, row, ordinal)
                )

    def prepare(self):
        counts = {'RESULT': 0, 'ISSUE': 0, 'BRANCH': 0}
        digest = ArrayDigest()
        with closing(self.items()) as items:
            for item, _ in items:
                counts[item['kind']] += 1
                digest.append(item)
        if not 1 <= counts['RESULT'] <= 20:
            raise ValueError('Closure requires a complete real step definition')
        head = {
            'event_id': self.event_id,
            'step_ref': self.step['step_ref'],
            'definition_version': self.step['definition_version'],
            'goal_version': self.command['expected_goal_version'],
            'revision_id': self.document['revision_id'],
            'command_message_id': self.message_id,
            'next_step_ref': self.command['next_step_ref'],
            'result_count': counts['RESULT'],
            'issue_count': counts['ISSUE'],
            'branch_count': counts['BRANCH'],
            'items_digest': digest.hexdigest(),
        }
        return ClosurePlan(self.connection, head, self.items)


def write_closure(connection, document_id, plan):
    require_write_transaction(connection)
    if plan.connection is not connection:
        raise ValueError('Closure publication cannot cross its original transaction')
    head = {'document_id': document_id, **plan.head}
    connection.execute(
        'INSERT INTO formation_closures('
        + ','.join(head)
        + ') VALUES('
        + ','.join('?' for _ in head)
        + ')',
        tuple(head.values()),
    )
    counts = {'RESULT': 0, 'ISSUE': 0, 'BRANCH': 0}
    digest = ArrayDigest()
    with closing(plan.items()) as items:
        for item, evidence_factory in items:
            kind = item['kind']
            ref = item['result_ref'] if kind == 'RESULT' else item['ref']
            status = item['status'] if kind == 'RESULT' else item['disposition']
            counts[kind] += 1
            digest.append(item)
            connection.execute(
                'INSERT INTO formation_closure_items(event_id,kind,item_ref,ordinal,status,payload_json) VALUES(?,?,?,?,?,?)',
                (plan.head['event_id'], kind, ref, item['ordinal'], status, canonical_input(item)),
            )
            evidence_count, evidence_digest = 0, ArrayDigest()
            with closing(evidence_factory()) as evidence_rows:
                for evidence in evidence_rows:
                    evidence_count += 1
                    evidence_digest.append(evidence)
                    connection.execute(
                        'INSERT INTO formation_closure_evidence(event_id,owner_kind,item_ref,ordinal,evidence_kind,'
                        'artifact_ref,payload_json) VALUES(?,?,?,?,?,?,?)',
                        (
                            plan.head['event_id'],
                            kind,
                            ref,
                            evidence['ordinal'],
                            evidence['kind'],
                            evidence.get('artifact_ref'),
                            canonical_input(evidence),
                        ),
                    )
            if (
                evidence_count != item['evidence_count']
                or evidence_digest.hexdigest() != item['evidence_digest']
            ):
                raise ValueError('Closure evidence changed during its immutable publication')
    if (
        counts != {kind: plan.head[kind.lower() + '_count'] for kind in counts}
        or digest.hexdigest() != plan.head['items_digest']
    ):
        raise ValueError('Closure facts changed during their immutable publication')
