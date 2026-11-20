"""Original immutable proposal protection drives message availability, without D expiry."""

import json

from backend.app.shared.command_execution import Rejected

from .proposal_binding import check_binding
from .proposal_sources import read_reference
from .write_preview import prepare_write


def message_card_state(repository, root, row, catalog):
    group = json.loads(row['structured_content_json'])
    reference = {'message_id': row['id'], 'card_key': group['cards'][0]['card_key']}
    source = repository.guide(row['guide_run_id'])
    if source is None or source['status'] != 'COMPLETED':
        return 'EXPIRED'
    # Temporary occupancy gates actions separately. It must not turn an intact
    # immutable proposal into EXPIRED and cause local selections to be cleared.
    try:
        proposal = read_reference(repository.connection, root, reference, purpose=group['purpose'])
        if proposal.disposition != 'PENDING' or proposal.needs_revision:
            return 'EXPIRED'
        check_binding(repository.connection, root, proposal, group['purpose'], catalog)
        if group['purpose'] == 'STAGED_WRITE':
            prepare_write(repository.connection, root, proposal.payload, catalog)
    except (Rejected, ValueError):
        return 'EXPIRED'
    return 'AVAILABLE'
