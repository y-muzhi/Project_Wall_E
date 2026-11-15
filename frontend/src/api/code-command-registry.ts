/** Reviewed business paths only; no GET or recursive close intent. */
import { positiveInteger } from './client.ts';
export const COMMAND_ROUTES = Object.freeze(
  (
    [
      ['CODING', 'APP-CODE-CMD-C01', '/api/v1/code-repositories'],
      ['CODING', 'APP-CODE-CMD-C02', '/api/v1/code-repositories/{id}/refresh'],
      ['CODING', 'APP-CODE-CMD-C05', '/api/v1/code-repositories/{id}/snapshots'],
      ['CODING', 'APP-CODE-CMD-C07', '/api/v1/code-execution-profiles/{profile_id}/versions'],
      ['CODING', 'APP-CODE-CMD-C08', '/api/v1/code-check-sets/{check_set_id}/versions'],
      ['CODING', 'APP-CODE-CMD-C09', '/api/v1/code-execution-profiles'],
      ['CODING', 'APP-CODE-CMD-C10', '/api/v1/code-check-sets'],
      ['CODING', 'APP-CODE-CMD-C15', '/api/v1/code-authorizations'],
      ['CODING', 'APP-CODE-CMD-C32', '/api/v1/documents/{document_id}/code-tasks'],
      ['CODING', 'APP-CODE-CMD-C35', '/api/v1/code-tasks/{task_id}/start'],
      ['CODING', 'APP-CODE-CMD-C36', '/api/v1/code-tasks/{task_id}/resume'],
      ['CODING', 'APP-CODE-CMD-C37', '/api/v1/code-tasks/{task_id}/terminate'],
      ['CODING', 'APP-CODE-CMD-C38', '/api/v1/code-tasks/{task_id}/reconcile'],
      ['CODING', 'APP-CODE-CMD-C39', '/api/v1/code-tasks/{task_id}/configuration'],
      ['CODING', 'APP-CODE-CMD-C40', '/api/v1/code-tasks/{task_id}/budget'],
      [
        'CODING',
        'APP-CODE-CMD-C46',
        '/api/v1/code-tasks/{task_id}/questions/{question_id}/responses',
      ],
      [
        'CODING',
        'APP-CODE-CMD-C47',
        '/api/v1/code-tasks/{task_id}/permissions/{permission_id}/responses',
      ],
      [
        'CODING',
        'APP-CODE-CMD-C48',
        '/api/v1/code-tasks/{task_id}/questions/{question_id}/handoff',
      ],
      ['CODING', 'APP-CODE-CMD-C49', '/api/v1/code-tasks/{task_id}/handoffs/{handoff_id}/links'],
      ['CODING', 'APP-CODE-CMD-C50', '/api/v1/code-tasks/{task_id}/candidates'],
      [
        'CODING',
        'APP-CODE-CMD-C51',
        '/api/v1/code-tasks/{task_id}/candidates/{candidate_id}/verifications',
      ],
      ['CODING', 'APP-CODE-CMD-C58', '/api/v1/code-tasks/{task_id}/defects'],
      ['CODING', 'APP-CODE-CMD-C59', '/api/v1/code-tasks/{task_id}/repairs'],
      ['CODING', 'APP-CODE-CMD-C62', '/api/v1/code-tasks/{task_id}/delivery-plans'],
      ['CODING', 'APP-CODE-CMD-C64', '/api/v1/code-tasks/{task_id}/accept'],
      ['CODING', 'APP-CODE-CMD-C68', '/api/v1/code-tasks/{task_id}/testing-publication'],
      ['CODING', 'APP-CODE-CMD-C69', '/api/v1/code-tasks/{task_id}/test-reports'],
      ['TESTING', 'APP-TEST-CMD-C01', '/api/v1/testing-profile-versions'],
      ['TESTING', 'APP-TEST-CMD-C04', '/api/v1/testing-authorizations'],
      ['TESTING', 'APP-TEST-CMD-C06', '/api/v1/test-plans'],
      ['TESTING', 'APP-TEST-CMD-C09', '/api/v1/test-plans/{plan_id}/versions'],
      ['TESTING', 'APP-TEST-CMD-C12', '/api/v1/test-plan-versions/{id}/draft'],
      ['TESTING', 'APP-TEST-CMD-C13', '/api/v1/test-plan-versions/{id}/publish'],
      ['TESTING', 'APP-TEST-CMD-C14', '/api/v1/test-plan-versions/{id}/revoke'],
      ['TESTING', 'APP-TEST-CMD-C15', '/api/v1/test-plan-versions/{plan_version_id}/packs'],
      ['TESTING', 'APP-TEST-CMD-C18', '/api/v1/test-pack-versions/{id}/seal'],
      ['TESTING', 'APP-TEST-CMD-C19', '/api/v1/test-pack-versions/{id}/validations'],
      ['TESTING', 'APP-TEST-CMD-C21', '/api/v1/test-pack-versions/{id}/publish'],
      ['TESTING', 'APP-TEST-CMD-C22', '/api/v1/test-pack-versions/{id}/revoke'],
      ['TESTING', 'APP-TEST-CMD-C23', '/api/v1/testing-tasks'],
      ['TESTING', 'APP-TEST-CMD-C26', '/api/v1/testing-tasks/{testing_task_id}/draft-plan'],
      ['TESTING', 'APP-TEST-CMD-C27', '/api/v1/testing-tasks/{testing_task_id}/assets'],
      ['TESTING', 'APP-TEST-CMD-C28', '/api/v1/testing-tasks/{testing_task_id}/run'],
      ['TESTING', 'APP-TEST-CMD-C29', '/api/v1/testing-tasks/{testing_task_id}/budget'],
      ['TESTING', 'APP-TEST-CMD-C30', '/api/v1/testing-tasks/{testing_task_id}/resume'],
      ['TESTING', 'APP-TEST-CMD-C31', '/api/v1/testing-tasks/{testing_task_id}/terminate'],
      ['TESTING', 'APP-TEST-CMD-C32', '/api/v1/testing-tasks/{testing_task_id}/reconcile'],
      ['TESTING', 'APP-TEST-CMD-C40', '/api/v1/testing-findings/{id}/review'],
    ] as const
  ).map((route) => Object.freeze(route)),
);

export type CommandOwner = 'CODING' | 'TESTING';
export type CommandIdentity = Readonly<{
  owner_module: CommandOwner;
  method: 'POST';
  path: string;
  key: string;
  decoder_kind: string;
  parameters: Readonly<Record<string, number>>;
}>;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
export function registeredCommand(method: unknown, path: unknown, key: unknown): CommandIdentity {
  if (method !== 'POST' || typeof path !== 'string' || typeof key !== 'string' || !UUID.test(key))
    throw new TypeError('Invalid original command identity');
  const actual = path.split('/');
  for (const [owner_module, decoder_kind, template] of COMMAND_ROUTES) {
    const expected = template.split('/');
    if (actual.length !== expected.length) continue;
    const parameters: Record<string, number> = {};
    let matches = true;
    for (let index = 0; index < expected.length; index++) {
      const part = expected[index]!;
      const value = actual[index]!;
      if (part.startsWith('{')) {
        if (!/^[1-9][0-9]*$/.test(value)) {
          matches = false;
          break;
        }
        const identity = positiveInteger(Number(value));
        if (String(identity) !== value) throw new TypeError('Noncanonical command identity');
        parameters[part.slice(1, -1)] = identity;
      } else if (part !== value) {
        matches = false;
        break;
      }
    }
    if (matches)
      return Object.freeze({
        owner_module,
        method: 'POST',
        path,
        key,
        decoder_kind,
        parameters: Object.freeze(parameters),
      });
  }
  throw new TypeError('Unregistered original command path');
}
