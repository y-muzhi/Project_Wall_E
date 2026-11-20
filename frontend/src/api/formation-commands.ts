/** Native program-only command DTOs; server transactions remain authoritative. */
import contract from '../../../backend/resources/v27/schemas/collaboration-contract.v15.json' with { type: 'json' };
import { exact, object, snapshotObject, stableJson } from './client.ts';
import { array, bool, choices, distinct, id, nullable, require, shape } from './decoding.ts';
import { boundedText, stepRef, resultRef } from './formation-values.ts';
import { validateDefinition } from './resource-schema.ts';
import { sourceRef } from './models.ts';
const branchRef = (value: unknown) => {
  validateDefinition('FormationBranchRef', value, contract.$defs);
  return boundedText(17)(value);
};
const issueRef = (value: unknown) => {
  validateDefinition('FormationIssueRef', value, contract.$defs);
  return boundedText(17)(value);
};
const proposal = shape({ message_id: id, card_key: boundedText(100) });
const reason = boundedText(1000);
const refs = (decode: (v: unknown) => string) => (value: unknown) => {
  const rows = array(decode, Number.MAX_SAFE_INTEGER)(value);
  distinct(rows);
  return rows;
};
const remaining = (decode: (v: unknown) => string) => (value: unknown) => {
  const row = shape({
    ref: decode,
    disposition: choices(['KEEP_OPEN', 'TRANSFER', 'DEFERRED', 'DROPPED']),
    to_step_ref: nullable(stepRef),
    reason: nullable(reason),
  })(value);
  require((row.disposition === 'TRANSFER') === (row.to_step_ref !== null));
  if (['DEFERRED', 'DROPPED'].includes(row.disposition)) require(row.reason !== null);
  return row;
};
const resultDisposition = shape({
  result_ref: resultRef,
  status: choices(['OUTSTANDING', 'LANDED', 'ANALYZED']),
  artifact_refs: refs((value: unknown) => {
    validateDefinition('FormationArtifactRef', value, contract.$defs);
    return boundedText(17)(value);
  }),
  source_refs: array((value: unknown) => sourceRef(value), 100),
});
export function nativeFormationCommand(value: unknown) {
  const header = object(value);
  const common = { type: choices(['FORMATION']) };
  const action = String(header.action);
  let decoded: object;
  if (['START_STEP', 'PAUSE_STEP', 'RESUME_STEP', 'REOPEN_STEP', 'SWITCH_STEP'].includes(action)) {
    decoded = shape({
      ...common,
      action: choices(['START_STEP', 'PAUSE_STEP', 'RESUME_STEP', 'REOPEN_STEP', 'SWITCH_STEP']),
      step_ref: action === 'SWITCH_STEP' ? nullable(stepRef) : stepRef,
    })(value);
  } else if (action === 'COMPLETE_STEP') {
    const row = shape({
      ...common,
      action: choices(['COMPLETE_STEP']),
      step_ref: stepRef,
      expected_definition_version: id,
      expected_goal_version: id,
      expected_content_version: id,
      result_dispositions: array(resultDisposition, 20),
      issue_dispositions: array(remaining(issueRef), 20),
      branch_dispositions: array(remaining(branchRef), 20),
      next_step_ref: nullable(stepRef),
    })(value);
    distinct(row.result_dispositions.map((item) => item.result_ref));
    distinct(row.issue_dispositions.map((item) => item.ref));
    distinct(row.branch_dispositions.map((item) => item.ref));
    decoded = row;
  } else if (action === 'ADJUST_PATH') {
    const row = shape({
      ...common,
      action: choices(['ADJUST_PATH']),
      expected_formation_version: id,
      expected_content_version: id,
      based_on_proposal: nullable(proposal),
      changes: array((item: unknown) => {
        validateDefinition('CanonicalFormationPathChange', item, contract.$defs);
        return snapshotObject(item);
      }, 20),
      result_routes: array((item: unknown) => {
        validateDefinition('FormationResultRoute', item, contract.$defs);
        return snapshotObject(item);
      }, Number.MAX_SAFE_INTEGER),
      reason,
    })(value);
    require(row.changes.length > 0);
    require(
      new TextEncoder().encode(
        stableJson({ changes: row.changes, result_routes: row.result_routes }),
      ).length <=
        64 * 1024,
    );
    distinct(row.result_routes.map((route) => route.from_result_ref));
    decoded = row;
  } else if (action === 'ENTER_BRANCH') {
    decoded = shape({
      ...common,
      action: choices(['ENTER_BRANCH']),
      step_ref: stepRef,
      branch_ref: branchRef,
    })(value);
  } else if (action === 'RETURN_FROM_BRANCH') {
    decoded = shape({ ...common, action: choices(['RETURN_FROM_BRANCH']), branch_ref: branchRef })(
      value,
    );
  } else if (action === 'DISPOSE_BRANCH') {
    decoded = shape({
      ...common,
      action: choices(['DISPOSE_BRANCH']),
      branch_ref: branchRef,
      disposition: choices(['DEFERRED', 'DROPPED']),
      reason,
    })(value);
  } else if (action === 'RESUME_BRANCH') {
    decoded = shape({
      ...common,
      action: choices(['RESUME_BRANCH']),
      step_ref: stepRef,
      branch_ref: branchRef,
      expected_branch_status: choices(['DEFERRED', 'RESOLVED']),
      expected_branch_event_id: id,
      enter_after_resume: bool,
    })(value);
  } else if (action === 'RESUME_ISSUE') {
    decoded = shape({ ...common, action: choices(['RESUME_ISSUE']), issue_ref: issueRef })(value);
  } else if (action === 'DEFER_WRITE_PROPOSAL') {
    decoded = shape({ ...common, action: choices(['DEFER_WRITE_PROPOSAL']), proposal, reason })(
      value,
    );
  } else if (['RESUME_WRITE_PROPOSAL', 'WITHDRAW_PROPOSAL_ADJUSTMENT'].includes(action)) {
    decoded = shape({
      ...common,
      action: choices(['RESUME_WRITE_PROPOSAL', 'WITHDRAW_PROPOSAL_ADJUSTMENT']),
      proposal,
    })(value);
  } else throw TypeError('Unregistered formation action');
  return snapshotObject(decoded);
}
export function formationCommandBody(value: unknown) {
  const row = exact(value, ['document_id', 'expected_discussion_version', 'discussion_command']);
  id(row.document_id);
  id(row.expected_discussion_version);
  nativeFormationCommand(row.discussion_command);
  return snapshotObject(row);
}
