/** Ordinary-document routes are the only business routes admitted by the
 * binding-protocol 1 handshake currently supported by the browser. */
const requirements =
  /^\/api\/v1\/requirements(?:\/[1-9][0-9]*(?:\/(?:current-document|manual-draft|revisions|comments|comment-index|messages))?)?$/;
const individual = /^\/api\/v1\/(?:revisions|comments|conversation-messages)\/[1-9][0-9]*$/;
const receipt = /^\/api\/v1\/(?:code|testing)-command-receipts$/;
const draft = /^\/api\/v1\/requirements\/[1-9][0-9]*\/manual-draft$/;
const requirementWrite =
  /^\/api\/v1\/requirements\/[1-9][0-9]*\/(?:documents|manual-draft(?:\/complete)?|complete-initialization)$/;

function readsDocument(route: string): boolean {
  return requirements.test(route) || individual.test(route);
}

export function allowsRecoveryRequest(method: string, target: string): boolean {
  return method === 'GET' && readsDocument(target.split('?', 1)[0]!);
}

export function allowsOrdinaryRequest(method: string, target: string): boolean {
  const route = target.split('?', 1)[0]!;
  switch (method) {
    case 'GET':
      return readsDocument(route) || receipt.test(route);
    case 'POST':
      return route === '/api/v1/requirements' || requirementWrite.test(route);
    case 'PUT':
    case 'DELETE':
      return draft.test(route);
    default:
      return false;
  }
}

export const RECOVERY_READ_ONLY = '恢复核对期间仅可读取已核验资料';

export const ORDINARY_OPERATION_UNAVAILABLE = '此环境未启用该操作所需能力。';
export const ORDINARY_CODING_UNAVAILABLE = '此环境尚未开放代码开发。';
export const ORDINARY_TESTING_UNAVAILABLE = '此环境尚未开放测试验收。';
export const ORDINARY_SETTINGS_UNAVAILABLE = '此环境尚未开放代码开发和测试验收的设置。';
