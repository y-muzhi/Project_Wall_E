"""Canonical, SQL-deduplicated source rows for one immutable closure transaction."""

import json
from contextlib import contextmanager

from backend.app.shared.json_canonical import canonical_input
from backend.app.shared.validation import strict_json_object

FUNCTION_NAME = '_walle_v21_closure_source'


@contextmanager
def source_reader(connection, resources):
    """Install before opening the closure cursors; remove after both streaming passes."""

    def canonical(raw):
        return canonical_input(
            resources.collaboration.validate('SourceRef', strict_json_object(raw))
        )

    connection.create_function(FUNCTION_NAME, 1, canonical, deterministic=True)
    try:
        yield ClosureSources(connection)
    finally:
        connection.create_function(FUNCTION_NAME, 1, None)


class ClosureSources:
    def __init__(self, connection):
        self.connection = connection

    def _rows(self, query, parameters):
        cursor = self.connection.execute(
            f'SELECT DISTINCT {FUNCTION_NAME}(source_json) AS canonical_source FROM ({query}) ORDER BY canonical_source',
            parameters,
        )
        try:
            for row in cursor:
                yield strict_json_object(row[0])
        finally:
            cursor.close()

    def result(self, document_id, step_ref, result_ref, explicit):
        query = """
        WITH active AS (
          SELECT a.* FROM formation_artifacts a JOIN formation_artifact_results ar
          ON ar.document_id=a.document_id AND ar.artifact_ref=a.artifact_ref
          WHERE a.document_id=:document AND ar.result_ref=:result
          AND NOT EXISTS(SELECT 1 FROM formation_artifact_reviews review
            WHERE review.document_id=a.document_id AND review.reviewed_artifact_ref=a.artifact_ref
            AND review.result='REASSOCIATED')
        ), latest_assessment AS (
          SELECT * FROM formation_assessments WHERE document_id=:document AND step_ref=:step
          ORDER BY event_id DESC,id DESC LIMIT 1
        )
        SELECT value AS source_json FROM json_each(:explicit)
        UNION ALL SELECT json_object('kind','REVISION','document_id',document_id,
          'revision_id',origin_revision_id,'block_ids',NULL) FROM active
        UNION ALL SELECT value FROM active a JOIN revisions r
          ON r.id=a.origin_revision_id AND r.document_id=a.document_id,json_each(r.source_refs_json)
        UNION ALL SELECT json_object('kind','MESSAGE','message_id',e.source_id)
          FROM active a JOIN document_change_audits e ON e.id=a.source_event_id
          WHERE e.source_type IN ('USER_ACTION','AI_MESSAGE')
        UNION ALL SELECT source.value FROM active a JOIN document_change_audits e ON e.id=a.source_event_id,
          json_each(e.payload_json,'$.source_refs') source
        UNION ALL SELECT value FROM latest_assessment,json_each(latest_assessment.source_refs_json)
        UNION ALL SELECT json_object('kind','MESSAGE','message_id',assistant_message_id) FROM latest_assessment
        """
        yield from self._rows(
            query,
            {
                'document': document_id,
                'step': step_ref,
                'result': result_ref,
                'explicit': json.dumps(
                    explicit, ensure_ascii=False, sort_keys=True, separators=(',', ':')
                ),
            },
        )

    def issue(self, document_id, issue_ref):
        yield from self._rows(
            'SELECT value AS source_json FROM formation_issues i,json_each(i.source_refs_json) '
            'WHERE i.document_id=:document AND i.issue_ref=:ref '
            'UNION ALL SELECT value FROM formation_issues i,json_each(i.resolution_sources_json) '
            'WHERE i.document_id=:document AND i.issue_ref=:ref',
            {'document': document_id, 'ref': issue_ref},
        )

    def branch(self, document_id, branch_ref):
        yield from self._rows(
            'SELECT value AS source_json FROM formation_branches b,json_each(b.result_sources_json) '
            'WHERE b.document_id=:document AND b.branch_ref=:ref '
            "UNION ALL SELECT json_object('kind','MESSAGE','message_id',e.source_id) "
            'FROM formation_branches b JOIN document_change_audits e ON e.id=b.origin_event_id '
            "WHERE b.document_id=:document AND b.branch_ref=:ref AND e.source_type IN ('USER_ACTION','AI_MESSAGE') "
            'UNION ALL SELECT source.value FROM formation_branches b JOIN document_change_audits e ON e.id=b.origin_event_id,'
            "json_each(e.payload_json,'$.source_refs') source WHERE b.document_id=:document AND b.branch_ref=:ref",
            {'document': document_id, 'ref': branch_ref},
        )
