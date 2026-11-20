"""Schema210 extension builder. Existing Schema200 objects retain their released bytes."""

MAX_ID = 9_007_199_254_740_991


def integer(name, *, nullable=False, minimum=1):
    required = '' if nullable else ' NOT NULL'
    return f'{name} INTEGER{required} CHECK({name} BETWEEN {minimum} AND {MAX_ID})'


def text(name, *, nullable=False, maximum=None):
    required = '' if nullable else ' NOT NULL'
    bound = '' if maximum is None else f' CHECK(length({name}) BETWEEN 1 AND {maximum})'
    if name.endswith(('_digest', '_sha256')):
        bound = f" CHECK(length({name})=64 AND {name} NOT GLOB '*[^0-9a-f]*')"
    if name == 'committed_at':
        bound = f" CHECK(length({name})=24 AND {name} GLOB '????-??-??T??:??:??.???Z')"
    result = f'{name} TEXT{required}{bound}'
    prefixes = {
        'step_ref': 's',
        'current_step_ref': 's',
        'origin_step_ref': 's',
        'return_step_ref': 's',
        'from_step_ref': 's',
        'to_step_ref': 's',
        'target_step_ref': 's',
        'next_step_ref': 's',
        'branch_ref': 'b',
        'active_branch_ref': 'b',
        'issue_ref': 'i',
        'artifact_ref': 'a',
        'reviewed_artifact_ref': 'a',
        'replacement_artifact_ref': 'a',
    }
    if name in prefixes:
        number = f'substr({name},2)'
        bound_text = str(MAX_ID)
        result += (
            f" CHECK(substr({name},1,1)='{prefixes[name]}' AND {number}<>'' "
            f"AND {number} NOT GLOB '*[^0-9]*' AND substr({number},1,1)<>'0' "
            f"AND (length({number})<16 OR length({number})=16 AND {number}<='{bound_text}'))"
        )
    if name == 'result_ref':
        split = f"instr({name},'.o')"
        step_no = f'substr({name},2,{split}-2)'
        result_no = f'substr({name},{split}+2)'
        result += f" CHECK(substr({name},1,1)='s' AND {split}>2)"
        for number in (step_no, result_no):
            result += (
                f" CHECK({number}<>'' AND {number} NOT GLOB '*[^0-9]*' "
                f"AND substr({number},1,1)<>'0' AND "
                f"(length({number})<16 OR length({number})=16 AND {number}<='{MAX_ID}'))"
            )
    return result


def enumeration(name, values, *, nullable=False):
    quoted = ','.join("'" + value + "'" for value in values.split())
    return text(name, nullable=nullable) + f' CHECK({name} IN ({quoted}))'


def json_column(name, kind='object'):
    return f"{name} TEXT NOT NULL CHECK(json_valid({name}) AND json_type({name})='{kind}')"


def foreign(columns, table, target, *, deferred=False):
    suffix = ' DEFERRABLE INITIALLY DEFERRED' if deferred else ''
    return f'FOREIGN KEY({columns}) REFERENCES {table}({target}) ON DELETE RESTRICT{suffix}'


def doc_fk():
    return foreign('document_id', 'formation_heads', 'document_id')


def step_fk(column='step_ref'):
    return foreign(
        f'document_id,{column}', 'formation_steps', 'document_id,step_ref', deferred=True
    )


def event_fk(column='event_id'):
    return foreign(
        f'{column},document_id', 'document_change_audits', 'id,document_id', deferred=True
    )


def message_fk(column):
    return foreign(f'{column},document_id', 'conversation_messages', 'id,document_id')


def revision_fk(column):
    return foreign(f'{column},document_id', 'revisions', 'id,document_id')


def extension_sql():
    statements = []

    def table(name, *columns):
        constraint_prefixes = ('PRIMARY KEY', 'UNIQUE(', 'FOREIGN KEY', 'CHECK(')
        definitions = [part for part in columns if not part.startswith(constraint_prefixes)]
        constraints = [part for part in columns if part.startswith(constraint_prefixes)]
        statements.append(
            f'CREATE TABLE {name} (\n  ' + ',\n  '.join(definitions + constraints) + '\n) STRICT;'
        )

    def index(name, table, columns, *, unique=False, where=None):
        condition = '' if where is None else ' WHERE ' + where
        statements.append(
            f'CREATE {"UNIQUE " if unique else ""}INDEX {name} ON {table}({columns}){condition};'
        )

    document = integer('document_id')
    doc = doc_fk()
    table(
        'formation_schema_state',
        'singleton_id INTEGER PRIMARY KEY NOT NULL CHECK(singleton_id=1)',
        'schema_version INTEGER NOT NULL CHECK(schema_version=210)',
        text('schema_contract_sha256', maximum=64),
        text('core_contract_sha256', maximum=64),
        enumeration('origin', 'FRESH_V21 UPGRADED_V200'),
        text('upgrade_id', nullable=True),
        text('source_data_sha256', nullable=True),
        text('committed_at', maximum=24),
        "CHECK((origin='FRESH_V21' AND upgrade_id IS NULL AND source_data_sha256 IS NULL) OR "
        "(origin='UPGRADED_V200' AND upgrade_id IS NOT NULL AND source_data_sha256 IS NOT NULL))",
    )
    index('formation_audit_doc_identity', 'document_change_audits', 'id,document_id', unique=True)
    index('formation_message_doc_identity', 'conversation_messages', 'id,document_id', unique=True)
    table(
        'formation_heads',
        document,
        'PRIMARY KEY(document_id)',
        integer('version'),
        integer('goal_version'),
        text('goal_text', maximum=1000),
        json_column('goal_sources_json', 'array'),
        text('current_step_ref', nullable=True),
        text('active_branch_ref', nullable=True),
        *(integer('next_' + kind + '_no') for kind in ('step', 'branch', 'issue', 'artifact')),
        foreign('document_id', 'requirement_documents', 'id'),
        step_fk('current_step_ref'),
        foreign(
            'document_id,active_branch_ref',
            'formation_branches',
            'document_id,branch_ref',
            deferred=True,
        ),
    )
    table(
        'formation_steps',
        document,
        text('step_ref'),
        integer('definition_version'),
        integer('next_result_no'),
        'position INTEGER NOT NULL CHECK(position<>0 AND position BETWEEN -9007199254740991 AND 9007199254740991)',
        text('title', maximum=120),
        enumeration('status', 'PLANNED IN_PROGRESS PAUSED COMPLETED CANCELLED'),
        integer('closure_event_id', nullable=True),
        'PRIMARY KEY(document_id,step_ref)',
        doc,
        event_fk('closure_event_id'),
    )
    index(
        'formation_steps_active_position',
        'formation_steps',
        'document_id,position',
        unique=True,
        where="status<>'CANCELLED'",
    )
    index('formation_steps_order', 'formation_steps', 'document_id,position,step_ref')
    table(
        'formation_results',
        document,
        text('step_ref'),
        text('result_ref'),
        text('description', maximum=1000),
        enumeration('kind', 'CONTENT ANALYSIS'),
        'PRIMARY KEY(document_id,step_ref,result_ref)',
        'UNIQUE(document_id,result_ref)',
        "CHECK(substr(result_ref,1,instr(result_ref,'.o')-1)=step_ref)",
        step_fk(),
    )
    table(
        'formation_step_edges',
        document,
        text('from_step_ref'),
        text('to_step_ref'),
        enumeration('kind', 'DEPENDENCY REPLACES'),
        'PRIMARY KEY(document_id,from_step_ref,to_step_ref,kind)',
        'CHECK(from_step_ref<>to_step_ref)',
        step_fk('from_step_ref'),
        step_fk('to_step_ref'),
    )
    index(
        'formation_edges_incoming',
        'formation_step_edges',
        'document_id,to_step_ref,kind,from_step_ref',
    )
    table(
        'formation_step_topics',
        document,
        text('step_ref'),
        text('topic_ref'),
        'PRIMARY KEY(document_id,step_ref,topic_ref)',
        step_fk(),
    )
    table(
        'formation_branches',
        document,
        text('branch_ref'),
        text('origin_step_ref'),
        text('return_step_ref'),
        text('question', maximum=1000),
        text('relevance', maximum=1000),
        enumeration('status', 'OPEN RESOLVED DEFERRED DROPPED'),
        integer('origin_event_id'),
        integer('state_event_id'),
        text('result_summary', nullable=True, maximum=1000),
        json_column('result_sources_json', 'array'),
        integer('disposition_event_id', nullable=True),
        'PRIMARY KEY(document_id,branch_ref)',
        step_fk('origin_step_ref'),
        step_fk('return_step_ref'),
        event_fk('origin_event_id'),
        event_fk('state_event_id'),
        event_fk('disposition_event_id'),
        "CHECK(status<>'RESOLVED' OR (result_summary IS NOT NULL AND json_array_length(result_sources_json)>0))",
    )
    index(
        'formation_branches_return',
        'formation_branches',
        'document_id,return_step_ref,status,branch_ref',
    )
    index('formation_branches_status', 'formation_branches', 'document_id,status,branch_ref')
    table(
        'formation_branch_topics',
        document,
        text('branch_ref'),
        text('topic_ref'),
        'PRIMARY KEY(document_id,branch_ref,topic_ref)',
        foreign('document_id,branch_ref', 'formation_branches', 'document_id,branch_ref'),
    )
    table(
        'formation_issues',
        document,
        text('issue_ref'),
        text('step_ref'),
        text('branch_ref', nullable=True),
        text('description', maximum=1000),
        json_column('source_refs_json', 'array'),
        'blocking INTEGER NOT NULL CHECK(blocking IN (0,1))',
        enumeration('disposition', 'OPEN RESOLVED DEFERRED DROPPED'),
        text('disposition_reason', nullable=True, maximum=1000),
        json_column('resolution_sources_json', 'array'),
        integer('disposition_event_id', nullable=True),
        'PRIMARY KEY(document_id,issue_ref)',
        step_fk(),
        foreign('document_id,branch_ref', 'formation_branches', 'document_id,branch_ref'),
        event_fk('disposition_event_id'),
        "CHECK(disposition NOT IN ('DEFERRED','DROPPED') OR disposition_reason IS NOT NULL)",
        "CHECK(disposition<>'RESOLVED' OR json_array_length(resolution_sources_json)>0)",
    )
    index('formation_issues_step', 'formation_issues', 'document_id,step_ref,disposition,issue_ref')
    index(
        'formation_issues_branch',
        'formation_issues',
        'document_id,branch_ref,disposition,issue_ref',
    )
    table(
        'formation_artifacts',
        document,
        text('artifact_ref'),
        text('step_ref'),
        integer('source_event_id'),
        integer('origin_revision_id'),
        text('origin_digest', maximum=64),
        text('summary', maximum=240),
        integer('checked_against_revision_id'),
        enumeration('freshness', 'CURRENT NEEDS_REVIEW REMOVED'),
        enumeration('review_reason', 'CHANGED UNVERIFIABLE', nullable=True),
        'PRIMARY KEY(document_id,artifact_ref)',
        step_fk(),
        event_fk('source_event_id'),
        revision_fk('origin_revision_id'),
        revision_fk('checked_against_revision_id'),
        "CHECK((freshness='NEEDS_REVIEW' AND review_reason IS NOT NULL) OR "
        "(freshness<>'NEEDS_REVIEW' AND review_reason IS NULL))",
    )
    index(
        'formation_artifacts_step',
        'formation_artifacts',
        'document_id,step_ref,freshness,artifact_ref',
    )
    table(
        'formation_artifact_results',
        document,
        text('artifact_ref'),
        text('result_ref'),
        'PRIMARY KEY(document_id,artifact_ref,result_ref)',
        foreign('document_id,artifact_ref', 'formation_artifacts', 'document_id,artifact_ref'),
        foreign('document_id,result_ref', 'formation_results', 'document_id,result_ref'),
    )
    table(
        'formation_artifact_ranges',
        document,
        text('artifact_ref'),
        enumeration('role', 'ORIGIN CURRENT'),
        integer('ordinal'),
        integer('revision_id'),
        integer('block_id'),
        text('block_digest', maximum=64),
        'PRIMARY KEY(document_id,artifact_ref,role,ordinal)',
        foreign('document_id,artifact_ref', 'formation_artifacts', 'document_id,artifact_ref'),
        revision_fk('revision_id'),
    )
    index(
        'formation_ranges_block',
        'formation_artifact_ranges',
        'document_id,revision_id,block_id,role',
    )
    for name, fields in (
        (
            'formation_assessments',
            (
                integer('goal_version'),
                integer('definition_version'),
                integer('evaluated_revision_id'),
                enumeration('verdict', 'SUFFICIENT GAPS_REMAIN UNCERTAIN'),
                text('reason', maximum=1000),
                json_column('coverage_json', 'array'),
                json_column('source_refs_json', 'array'),
                revision_fk('evaluated_revision_id'),
            ),
        ),
        (
            'formation_recommendations',
            (
                text('action'),
                text('reason', maximum=1000),
                text('target_step_ref', nullable=True),
                json_column('source_refs_json', 'array'),
                json_column('basis_json'),
                step_fk('target_step_ref'),
            ),
        ),
    ):
        table(
            name,
            integer('id'),
            'PRIMARY KEY(id)',
            document,
            text('step_ref'),
            integer('event_id'),
            integer('assistant_message_id'),
            *fields,
            step_fk(),
            event_fk(),
            message_fk('assistant_message_id'),
        )
        index(name + '_latest', name, 'document_id,step_ref,event_id DESC,id DESC')
    table(
        'formation_proposal_index',
        document,
        integer('message_id'),
        text('card_key', maximum=100),
        enumeration('purpose', 'STAGED_WRITE FORMATION_PATH_CHANGE'),
        enumeration('disposition', 'PENDING DEFERRED APPLIED SUPERSEDED'),
        integer('disposition_event_id', nullable=True),
        json_column('binding_json'),
        text('payload_digest', maximum=64),
        'PRIMARY KEY(document_id,message_id,card_key)',
        doc,
        message_fk('message_id'),
        event_fk('disposition_event_id'),
    )
    index(
        'formation_proposals_page',
        'formation_proposal_index',
        'document_id,purpose,disposition,message_id,card_key',
    )
    table(
        'formation_event_refs',
        document,
        integer('event_id'),
        enumeration('kind', 'STEP BRANCH ISSUE ARTIFACT RESULT'),
        text('ref'),
        'PRIMARY KEY(document_id,event_id,kind,ref)',
        doc,
        event_fk(),
    )
    index('formation_events_entity', 'formation_event_refs', 'document_id,kind,ref,event_id DESC')
    table(
        'formation_event_changes',
        integer('event_id'),
        integer('ordinal'),
        document,
        enumeration(
            'entity_kind',
            'GOAL STEP RESULT BRANCH ISSUE ARTIFACT ASSESSMENT RECOMMENDATION PROPOSAL PROPOSAL_CHECK ARTIFACT_REVIEW RESULT_ROUTE ORDER',
        ),
        text('entity_ref'),
        'before_json TEXT CHECK(before_json IS NULL OR json_valid(before_json))',
        'after_json TEXT CHECK(after_json IS NULL OR json_valid(after_json))',
        integer('member_count', minimum=0),
        text('member_digest', maximum=64),
        'PRIMARY KEY(event_id,ordinal)',
        'UNIQUE(event_id,ordinal,document_id)',
        'CHECK(before_json IS NOT NULL OR after_json IS NOT NULL)',
        doc,
        event_fk(),
    )
    index(
        'formation_review_fact_unique',
        'formation_event_changes',
        'event_id,entity_kind,entity_ref',
        unique=True,
        where="entity_kind IN ('PROPOSAL_CHECK','ARTIFACT_REVIEW')",
    )
    table(
        'formation_closures',
        integer('event_id'),
        'PRIMARY KEY(event_id)',
        document,
        text('step_ref'),
        integer('definition_version'),
        integer('goal_version'),
        integer('revision_id'),
        integer('command_message_id'),
        text('next_step_ref', nullable=True),
        *(integer(kind + '_count', minimum=0) for kind in ('result', 'issue', 'branch')),
        text('items_digest', maximum=64),
        doc,
        step_fk(),
        step_fk('next_step_ref'),
        event_fk(),
        revision_fk('revision_id'),
        message_fk('command_message_id'),
    )
    table(
        'formation_closure_items',
        integer('event_id'),
        enumeration('kind', 'RESULT ISSUE BRANCH'),
        text('item_ref'),
        integer('ordinal'),
        text('status'),
        json_column('payload_json'),
        'PRIMARY KEY(event_id,kind,item_ref)',
        'UNIQUE(event_id,kind,ordinal)',
        foreign('event_id', 'formation_closures', 'event_id'),
    )
    table(
        'formation_closure_evidence',
        integer('event_id'),
        enumeration('owner_kind', 'RESULT ISSUE BRANCH'),
        text('item_ref'),
        integer('ordinal'),
        text('evidence_kind'),
        text('artifact_ref', nullable=True),
        json_column('payload_json'),
        'PRIMARY KEY(event_id,owner_kind,item_ref,ordinal)',
        foreign(
            'event_id,owner_kind,item_ref', 'formation_closure_items', 'event_id,kind,item_ref'
        ),
    )
    index(
        'formation_closure_evidence_page',
        'formation_closure_evidence',
        'event_id,owner_kind,item_ref,evidence_kind,ordinal',
    )
    table(
        'formation_event_members',
        integer('event_id'),
        integer('change_ordinal'),
        integer('ordinal'),
        document,
        enumeration(
            'collection',
            'DEPENDENCY REPLACES TOPIC GOAL_SOURCE ISSUE_SOURCE ISSUE_RESOLUTION_SOURCE BRANCH_TOPIC BRANCH_RESULT_SOURCE ARTIFACT_RESULT ORIGIN_RANGE CURRENT_RANGE',
        ),
        text('member_key'),
        'before_json TEXT CHECK(before_json IS NULL OR json_valid(before_json))',
        'after_json TEXT CHECK(after_json IS NULL OR json_valid(after_json))',
        'PRIMARY KEY(event_id,change_ordinal,ordinal)',
        'UNIQUE(event_id,change_ordinal,collection,member_key)',
        'CHECK(before_json IS NOT NULL OR after_json IS NOT NULL)',
        foreign(
            'event_id,change_ordinal,document_id',
            'formation_event_changes',
            'event_id,ordinal,document_id',
        ),
    )
    table(
        'formation_artifact_reviews',
        document,
        integer('event_id'),
        text('reviewed_artifact_ref'),
        text('replacement_artifact_ref', nullable=True),
        enumeration('result', 'MATCHED REASSOCIATED UNVERIFIED REMOVED'),
        integer('checked_against_revision_id'),
        integer('assistant_message_id'),
        json_column('source_refs_json', 'array'),
        'PRIMARY KEY(document_id,event_id,reviewed_artifact_ref)',
        event_fk(),
        foreign(
            'document_id,reviewed_artifact_ref', 'formation_artifacts', 'document_id,artifact_ref'
        ),
        foreign(
            'document_id,replacement_artifact_ref',
            'formation_artifacts',
            'document_id,artifact_ref',
        ),
        revision_fk('checked_against_revision_id'),
        message_fk('assistant_message_id'),
        "CHECK((result='REASSOCIATED' AND replacement_artifact_ref IS NOT NULL "
        'AND replacement_artifact_ref<>reviewed_artifact_ref) OR '
        "(result<>'REASSOCIATED' AND replacement_artifact_ref IS NULL))",
    )
    for direction in ('reviewed', 'replacement'):
        index(
            'formation_artifact_' + direction + '_unique',
            'formation_artifact_reviews',
            f'document_id,{direction}_artifact_ref',
            unique=True,
            where="result='REASSOCIATED'",
        )
    index(
        'formation_reviews_history',
        'formation_artifact_reviews',
        'document_id,reviewed_artifact_ref,event_id DESC',
    )

    immutable = (
        'formation_schema_state',
        'formation_assessments',
        'formation_recommendations',
        'formation_event_refs',
        'formation_event_changes',
        'formation_event_members',
        'formation_closures',
        'formation_closure_items',
        'formation_closure_evidence',
        'formation_artifact_reviews',
        'formation_artifact_results',
    )
    for name in immutable:
        for operation in ('UPDATE', 'DELETE'):
            statements.append(
                f'CREATE TRIGGER {name}_{operation.lower()}_guard BEFORE {operation} ON {name} '
                "BEGIN SELECT RAISE(ABORT,'IMMUTABLE_FORMATION_RECORD'); END;"
            )
    for name, fields in (
        (
            'formation_artifacts',
            (
                'document_id',
                'artifact_ref',
                'step_ref',
                'source_event_id',
                'origin_revision_id',
                'origin_digest',
            ),
        ),
        (
            'formation_proposal_index',
            ('document_id', 'message_id', 'card_key', 'purpose', 'binding_json', 'payload_digest'),
        ),
        ('formation_branches', ('document_id', 'branch_ref', 'origin_step_ref', 'origin_event_id')),
        ('formation_steps', ('document_id', 'step_ref')),
        ('formation_artifact_ranges', ('document_id', 'artifact_ref', 'role', 'ordinal')),
        ('formation_results', ('document_id', 'step_ref', 'result_ref', 'kind')),
    ):
        condition = ' OR '.join(f'NEW.{field} IS NOT OLD.{field}' for field in fields)
        statements.append(
            f'CREATE TRIGGER {name}_identity_guard BEFORE UPDATE ON {name} WHEN {condition} '
            "BEGIN SELECT RAISE(ABORT,'IMMUTABLE_FORMATION_IDENTITY'); END;"
        )
    statements.append(
        'CREATE TRIGGER formation_artifact_result_owner BEFORE INSERT ON formation_artifact_results '
        'WHEN NOT EXISTS(SELECT 1 FROM formation_artifacts a JOIN formation_results r '
        'ON r.document_id=a.document_id AND r.step_ref=a.step_ref '
        'WHERE a.document_id=NEW.document_id AND a.artifact_ref=NEW.artifact_ref '
        'AND r.result_ref=NEW.result_ref) '
        "BEGIN SELECT RAISE(ABORT,'FORMATION_RESULT_OWNER_MISMATCH'); END;"
    )
    statements.append(
        'CREATE TRIGGER formation_head_current_guard BEFORE INSERT ON formation_heads '
        "WHEN NOT EXISTS(SELECT 1 FROM requirement_documents WHERE id=NEW.document_id AND document_type='CURRENT') "
        "BEGIN SELECT RAISE(ABORT,'FORMATION_REQUIRES_CURRENT_DOCUMENT'); END;"
    )
    for operation in ('UPDATE', 'DELETE'):
        statements.append(
            f'CREATE TRIGGER formation_origin_range_{operation.lower()}_guard BEFORE {operation} '
            "ON formation_artifact_ranges WHEN OLD.role='ORIGIN' "
            "BEGIN SELECT RAISE(ABORT,'IMMUTABLE_FORMATION_ORIGIN'); END;"
        )
    return (
        '-- V2.1 document formation extension; Schema200 is preserved.\n\n'
        + '\n\n'.join(statements)
        + '\n'
    )
