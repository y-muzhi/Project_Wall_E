import { snapshotObject } from './client.ts';
/** Strict V2.1 workflow values; private bindings never cross this boundary. */
import formationContract from '../../../backend/resources/v27/schemas/collaboration-contract.v15.json' with { type: 'json' };
import {
  array,
  bool,
  checked,
  choices,
  distinct,
  id,
  nullable,
  require,
  shape,
} from './decoding.ts';
import {
  boundedText,
  resultRef,
  stepRef,
  availability,
  availabilityReason,
  proposalStatuses,
} from './formation-values.ts';
import { validateDefinition } from './resource-schema.ts';

export const formationSelection = checked(
  shape({
    discussion_step_ref: nullable((value: unknown) => stepRef(value)),
    discussion_branch_ref: nullable((value: unknown) => {
      validateDefinition('FormationBranchRef', value, formationContract.$defs);
      return boundedText(17)(value);
    }),
    branch_intent: nullable(choices(['ENTER', 'RESUME'])),
    branch_resume_basis: nullable(
      shape({
        expected_branch_status: choices(['DEFERRED', 'RESOLVED']),
        expected_branch_event_id: id,
      }),
    ),
  }),
  (value) => {
    if (value.discussion_branch_ref === null)
      require(value.branch_intent === null && value.branch_resume_basis === null);
    else
      require(
        value.discussion_step_ref !== null &&
          value.branch_intent !== null &&
          (value.branch_intent === 'RESUME') === (value.branch_resume_basis !== null),
      );
  },
);
export const acceptedSelection = checked(formationSelection, (value) =>
  require(value.branch_intent !== 'RESUME'),
);
export function validateFormationCards(value: unknown): void {
  validateDefinition('StoredCardGroup', value, formationContract.$defs);
}
export function isFormationPurpose(
  value: unknown,
): value is 'STAGED_WRITE' | 'FORMATION_PATH_CHANGE' {
  return value === 'STAGED_WRITE' || value === 'FORMATION_PATH_CHANGE';
}
const mappedReference = (value: unknown) => {
  const row = shape({ temp_ref: boundedText(48), resolved_ref: boundedText(48) })(value);
  if (row.temp_ref.startsWith('new_step_')) {
    validateDefinition('TempStepRef', row.temp_ref, formationContract.$defs);
    stepRef(row.resolved_ref);
  } else {
    validateDefinition('TempResultRef', row.temp_ref, formationContract.$defs);
    resultRef(row.resolved_ref);
  }
  return row;
};
export const formationProgramReceipt = checked(
  shape({
    schema: choices(['formation_program_receipt_v21_1']),
    processing: choices(['PROGRAM']),
    requirement_id: id,
    document_id: id,
    discussion_version: id,
    formation_version: id,
    content_version: id,
    operation: choices(['NATIVE_FORMATION', 'STAGED_WRITE', 'FORMATION_PATH_CHANGE']),
    result: choices(['APPLIED', 'NO_CHANGE']),
    user_message_id: nullable(id),
    effects: shape({
      content_changed: bool,
      revision_id: nullable(id),
      formation_changed: bool,
      proposal_disposition: nullable(choices(['PENDING', 'DEFERRED', 'APPLIED', 'SUPERSEDED'])),
    }),
    event_ids: array(id, Number.MAX_SAFE_INTEGER),
    reference_map: array(mappedReference, Number.MAX_SAFE_INTEGER),
  }),
  (value) => {
    require(value.effects.content_changed === (value.effects.revision_id !== null));
    distinct(value.event_ids);
    distinct(value.reference_map.map((row) => row.temp_ref));
    distinct(value.reference_map.map((row) => row.resolved_ref));
    if (value.result === 'NO_CHANGE')
      require(
        value.user_message_id === null &&
          value.event_ids.length === 0 &&
          value.reference_map.length === 0 &&
          !value.effects.content_changed &&
          !value.effects.formation_changed &&
          value.effects.proposal_disposition === null,
      );
    else require(value.user_message_id !== null);
    if (value.operation === 'NATIVE_FORMATION') require(!value.effects.content_changed);
  },
);

export const proposalView = checked(
  shape({
    message_id: id,
    card_key: boundedText(100),
    purpose: choices(['STAGED_WRITE', 'FORMATION_PATH_CHANGE']),
    payload: snapshotObject,
    disposition: (value: unknown) => choices(proposalStatuses)(value),
    needs_revision: bool,
    can_apply: bool,
    reasons: array((value: unknown) => availabilityReason(value), 32),
    availability: array((value: unknown) => availability(value), 20),
    expiry_reason: nullable(
      choices([
        'CONTENT_CHANGED',
        'GOAL_CHANGED',
        'DEFINITION_CHANGED',
        'SOURCE_UNAVAILABLE',
        'PURPOSE_CHANGED',
        'BASIS_CHANGED',
        'ADJUSTING',
        'ALREADY_ANSWERED',
      ]),
    ),
    source_run_id: id,
  }),
  (value) => {
    validateDefinition(
      value.purpose === 'STAGED_WRITE'
        ? 'CanonicalFormationWritePayload'
        : 'CanonicalFormationPathPayload',
      value.payload,
      formationContract.$defs,
    );
    distinct(value.reasons);
    distinct(value.availability.map((row) => row.action));
    const apply = value.availability.find((row) => row.action === 'apply');
    require(apply !== undefined && apply.available === value.can_apply);
    require(value.can_apply ? value.reasons.length === 0 : value.reasons.length > 0);
    if (value.disposition !== 'PENDING' || value.needs_revision) require(!value.can_apply);
  },
);
export type FormationProposal = ReturnType<typeof proposalView>;
