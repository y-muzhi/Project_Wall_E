"""Resolve original Coding design and materials in one database snapshot."""

from dataclasses import dataclass, field

from backend.app.infrastructure.command_receipts import Rejection
from backend.app.infrastructure.database import StorageUnavailable
from backend.app.shared.code_errors import empty_conflict

from .design_revisions import design_revision_choice


@dataclass(frozen=True)
class BasisOriginal:
    document_id: int
    revision_id: int
    utf8: bytes = field(repr=False)


@dataclass(frozen=True)
class FixedDesignBasis:
    requirement_id: int
    differences: list[dict]
    originals: tuple[BasisOriginal, ...] = field(repr=False)


class TaskBasisUnavailable(StorageUnavailable):
    code = 'CONTENT_NOT_READY'


def fixed_design_basis(
    connection, document_id, design_revision_id, material_refs, *, include_originals=False
):
    sources = ({'document_id': document_id, 'revision_id': design_revision_id}, *material_refs)
    requirement_id = None
    differences = []
    originals = []
    for index, source in enumerate(sources):
        document_id, revision_id = source['document_id'], source['revision_id']
        choice = design_revision_choice(
            connection,
            document_id,
            revision_id,
            usage='MAIN' if index == 0 else 'MATERIAL',
            include_markdown=include_originals,
        )
        if choice is None or (index > 0 and choice['requirement_id'] != requirement_id):
            return Rejection('NOT_FOUND', None)
        requirement_id = choice['requirement_id']
        if not choice['eligible']:
            return Rejection(
                'BASIS_NOT_CONFIRMED',
                {
                    **empty_conflict(),
                    'related_entity_kind': 'REVISION',
                    'related_entity_id': revision_id,
                },
            )
        if include_originals:
            try:
                raw = choice['markdown_snapshot'].encode('utf-8', errors='strict')
            except (AttributeError, UnicodeError) as error:
                raise TaskBasisUnavailable('Original revision UTF-8 is unavailable') from error
            originals.append(BasisOriginal(document_id, revision_id, raw))
        if not choice['is_current']:
            current = connection.execute(
                """SELECT r.id FROM revisions r JOIN requirement_documents d
                   ON d.id=r.document_id AND d.content_version=r.version_no
                   WHERE d.id=? AND r.revision_type='CONTENT'""",
                (document_id,),
            ).fetchone()
            if current is None:
                raise TaskBasisUnavailable('Current design content version is missing')
            differences.append(
                {
                    'document_id': document_id,
                    'fixed_revision_id': revision_id,
                    'current_revision_id': current['id'],
                }
            )
    return FixedDesignBasis(requirement_id, differences, tuple(originals))


def read_task_basis(connection, task, *, include_originals=False):
    materials = [
        dict(row)
        for row in connection.execute(
            'SELECT document_id,revision_id FROM code_task_materials WHERE task_id=? '
            'ORDER BY document_id',
            (task['id'],),
        )
    ]
    design = fixed_design_basis(
        connection,
        task['document_id'],
        task['design_revision_id'],
        materials,
        include_originals=include_originals,
    )
    if isinstance(design, Rejection) or design.requirement_id != task['requirement_id']:
        raise TaskBasisUnavailable('Fixed task design owner or revision is invalid')
    return materials, design
