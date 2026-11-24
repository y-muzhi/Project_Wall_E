"""Counted route orientation and immediate adoption candidate from the accepted snapshot."""

from .progress_brief import progress_brief


def clarification_source(connection, root, before_message=None):
    """Read the user's original request only while the immediately preceding handoff is current."""
    from backend.app.shared.validation import strict_json_loads

    document = root['assistant_document_id']
    row = connection.execute(
        "SELECT m.id,m.role,r.final_result_json -> '$.route_clarification' AS clarification FROM conversation_messages m LEFT JOIN guide_runs r ON r.id=m.guide_run_id AND r.document_id=m.document_id AND r.requirement_id=m.requirement_id AND r.status='COMPLETED' WHERE m.requirement_id=? AND m.document_id=? AND (? IS NULL OR m.sequence_no<(SELECT sequence_no FROM conversation_messages WHERE id=? AND document_id=?)) ORDER BY m.sequence_no DESC LIMIT 1",
        (root['id'], document, before_message, before_message, document),
    ).fetchone()
    if row is None or row['role'] != 'ASSISTANT' or not row['clarification']:
        return None
    pending = strict_json_loads(row['clarification'])
    if pending['discussion_version'] != root['discussion_version']:
        return None
    head = connection.execute(
        'SELECT h.version,h.goal_version,r.id,d.content_version FROM formation_heads h JOIN requirement_documents d ON d.id=h.document_id JOIN revisions r ON r.document_id=d.id AND r.source_content_version=d.content_version WHERE h.document_id=? AND d.requirement_id=?',
        (document, root['id']),
    ).fetchone()
    basis = pending['basis']
    if head is None or tuple(head) != (
        basis['formation_version'],
        basis['goal_version'],
        basis['document_revision_id'],
        basis['content_version'],
    ):
        return None
    return connection.execute(
        "SELECT id,content FROM conversation_messages WHERE requirement_id=? AND document_id=? AND id=? AND role='USER'",
        (root['id'], document, pending['user_message_id']),
    ).fetchone()


def preceding_proposal(connection, root, trigger_id):
    if trigger_id is None:
        return None
    document = root['assistant_document_id']
    row = connection.execute(
        'SELECT id,role,message_type FROM conversation_messages WHERE requirement_id=? AND document_id=? '
        'AND sequence_no<(SELECT sequence_no FROM conversation_messages WHERE id=? AND document_id=?) '
        'ORDER BY sequence_no DESC LIMIT 1',
        (root['id'], document, trigger_id, document),
    ).fetchone()
    if row is None or row['role'] != 'ASSISTANT' or row['message_type'] != 'INTERACTION_CARDS':
        return None
    proposals = connection.execute(
        'SELECT p.card_key,p.payload_digest,p.purpose,p.disposition,m.structured_content_json '
        'FROM formation_proposal_index p JOIN conversation_messages m ON m.id=p.message_id '
        'WHERE p.document_id=? AND p.message_id=? LIMIT 2',
        (document, row['id']),
    ).fetchall()
    if len(proposals) != 1:
        return None
    candidate = proposals[0]
    if candidate['purpose'] != 'FORMATION_PATH_CHANGE' or candidate['disposition'] != 'PENDING':
        return None
    from .proposal_sources import read_reference

    ref = {'message_id': row['id'], 'card_key': candidate['card_key']}
    proposal = read_reference(connection, root, ref, purpose='FORMATION_PATH_CHANGE')
    if proposal.needs_revision:
        return None
    return {
        'proposal_ref': ref,
        'payload_digest': candidate['payload_digest'],
        'summary': proposal.payload['change_summary'],
    }


def route_context(connection, root, head, required_steps, trigger_id, *, lifecycle=False):
    document = root['assistant_document_id']
    focus = None if head is None else head['current_step_ref']
    brief = progress_brief(
        connection,
        root,
        {
            'current_step_ref': focus,
            'formation_version': None if head is None else head['version'],
            'goal': None,
        },
        display=False,
    )
    rows = connection.execute(
        "SELECT step_ref,title,position FROM formation_steps WHERE document_id=? AND status<>'CANCELLED' ORDER BY position",
        (document,),
    ).fetchall()
    required = set(required_steps)
    required.add(focus)
    chosen = {row['step_ref'] for row in rows if row['step_ref'] in required}
    for index, row in enumerate(rows):
        if row['step_ref'] == focus:
            chosen.update(item['step_ref'] for item in rows[max(0, index - 1) : index + 2])
    for row in rows:
        if len(chosen) >= 100:
            break
        chosen.add(row['step_ref'])
    if len(chosen) > 100:
        from backend.app.shared.command_execution import Rejected

        raise Rejected('CAPACITY_EXHAUSTED')
    deps = {}
    for edge in connection.execute(
        "SELECT from_step_ref,to_step_ref FROM formation_step_edges WHERE document_id=? AND kind='DEPENDENCY' ORDER BY from_step_ref,to_step_ref",
        (document,),
    ):
        if edge[0] in chosen:
            deps.setdefault(edge[0], []).append(edge[1])
    order = [
        {**dict(row), 'dependencies': deps.get(row['step_ref'], [])}
        for row in rows
        if row['step_ref'] in chosen
    ]
    extra = {}
    if lifecycle:
        from .initial_suggestion import preceding_initial
        from .order_restore import previous_order

        suggestion = preceding_initial(connection, root, trigger_id) if head is None else None
        extra['initial_proposal'] = (
            None
            if suggestion is None
            else {
                'message_id': suggestion['message_id'],
                'payload_digest': suggestion['payload_digest'],
                'goal': suggestion['goal'],
                'titles': [step['title'] for step in suggestion['steps']],
            }
        )
        extra['previous_order'] = previous_order(connection, document) if head else None
    return {
        **extra,
        'order': order,
        'step_total': len(rows),
        'focus_step_ref': focus,
        'decisions': brief['decisions'],
        'previous_proposal': preceding_proposal(connection, root, trigger_id),
    }


def positional_targets(rows, instruction):
    """Give the interpreter material for explicit positions, without changing user state."""
    import re

    numbers = {ch: i for i, ch in enumerate('零一二三四五六七八九十')}
    numbers['两'] = 2

    def number(text):
        return int(text) if text.isascii() else numbers[text]

    pattern = r'(?P<last>最后|倒数第)|(?P<first>最前|前面)|(?P<rank>第)'
    quantity = r'([1-9][0-9]{0,2}|[一二两三四五六七八九十])(?:个步骤|个环节|步|项)'
    positions = set()
    for match in re.finditer('(?:' + pattern + ')' + quantity, instruction):
        amount = number(match.group(4))
        prefix = match.group(1) or match.group(2) or match.group(3)
        if prefix == '最后':
            positions.update(range(max(0, len(rows) - amount), len(rows)))
        elif prefix == '倒数第':
            positions.add(len(rows) - amount)
        elif prefix == '第':
            positions.add(amount - 1)
        else:
            positions.update(range(min(amount, len(rows))))
    return [rows[index]['step_ref'] for index in sorted(positions) if 0 <= index < len(rows)]
