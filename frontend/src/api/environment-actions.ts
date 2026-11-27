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

const requirementGuideRuns = /^\/api\/v1\/requirements\/[1-9][0-9]*\/guide-runs$/;
const guideRunRead = /^\/api\/v1\/guide-runs\/[1-9][0-9]*(?:\/model-calls)?$/;
const modelCallRead = /^\/api\/v1\/model-calls\/[1-9][0-9]*$/;
const guideRunAction = /^\/api\/v1\/guide-runs\/[1-9][0-9]*\/(?:cancel|continue|retry)$/;
const commentGuideRun = /^\/api\/v1\/comments\/[1-9][0-9]*\/guide-runs$/;
const cardResponse = /^\/api\/v1\/conversation-messages\/[1-9][0-9]*\/responses$/;
const pendingSuggestion =
  /^\/api\/v1\/requirements\/[1-9][0-9]*\/documents\/[1-9][0-9]*\/pending-suggestion$/;
const formationLocation =
  /^\/api\/v1\/requirements\/[1-9][0-9]*\/documents\/[1-9][0-9]*\/formation\//;
const formationEntity = /^(?:steps|branches|issues|artifacts|proposals)(?:\/[A-Za-z0-9_.-]+)?$/;
const formationRelated =
  /^(?:steps\/s[1-9][0-9]*\/relations|artifacts\/a[1-9][0-9]*\/(?:ranges|lineage))$/;
const formationEvents =
  /^events(?:\/[1-9][0-9]*\/(?:changes(?:\/[1-9][0-9]*\/members)?|closure-items(?:\/[A-Za-z0-9_-]+\/[A-Za-z0-9_.-]+\/evidence)?))?$/;
const batchRead = /^\/api\/v1\/suggestion-batches\/[1-9][0-9]*$/;
const batchAction =
  /^\/api\/v1\/suggestion-batches\/[1-9][0-9]*\/(?:accept-pending|discard|complete)$/;
const batchDecision =
  /^\/api\/v1\/(?:suggestions\/[1-9][0-9]*\/decision|suggestion-batches\/[1-9][0-9]*\/groups\/[1-9][0-9]*\/decision)$/;

function readsFormation(route: string): boolean {
  if (!formationLocation.test(route)) return false;
  const resource = route.replace(formationLocation, '');
  return (
    formationEntity.test(resource) ||
    formationRelated.test(resource) ||
    formationEvents.test(resource)
  );
}

function previewsFormation(route: string): boolean {
  return formationLocation.test(route) && route.replace(formationLocation, '') === 'path-preview';
}

function allowsDocumentAiRequest(method: string, route: string): boolean {
  if (method === 'GET')
    return (
      requirementGuideRuns.test(route) ||
      guideRunRead.test(route) ||
      modelCallRead.test(route) ||
      pendingSuggestion.test(route) ||
      readsFormation(route) ||
      batchRead.test(route)
    );
  if (method === 'PUT') return batchDecision.test(route);
  return (
    method === 'POST' &&
    (requirementGuideRuns.test(route) ||
      guideRunAction.test(route) ||
      commentGuideRun.test(route) ||
      cardResponse.test(route) ||
      previewsFormation(route) ||
      batchAction.test(route))
  );
}

export function allowsOrdinaryRequest(
  method: string,
  target: string,
  documentAiReady = false,
): boolean {
  const route = target.split('?', 1)[0]!;
  if (documentAiReady && allowsDocumentAiRequest(method, route)) return true;
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
