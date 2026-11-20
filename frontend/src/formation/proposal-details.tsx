import type { SourceReading } from '../requirements/source-reading.ts';
import type { JsonObject, Json } from '../api/client.ts';
import { snapshotObject } from '../api/client.ts';
import { sourceRef, wireScope } from '../api/models.ts';
import type { CardsState, InteractionCards } from '../guide/cards.ts';
import type { MessageMarkdownRenderer } from '../messages/content.tsx';
import { MessageContent } from '../messages/content.tsx';
import { SourceReference } from '../requirements/source-reference.tsx';
import './proposal-details.css';

const referenceName = (value: Json | undefined): string => {
  if (typeof value !== 'string') return '';
  const step = /^(?:new_step_|s)([1-9][0-9]*)$/.exec(value);
  if (step) return (value.startsWith('new_') ? '新步骤 ' : '步骤 ') + step[1];
  const result = /^(?:new_result_)([1-9][0-9]*)$/.exec(value);
  return result ? '新成果 ' + result[1] : value;
};
const names = (value: Json | undefined) =>
  Array.isArray(value) ? value.map(referenceName).join('、') : '';
const disposition = (value: Json | undefined) => (value === 'DROPPED' ? '放弃' : '暂缓');
function adoptionScopeLabel(value: Json | undefined): string {
  const scope = wireScope(value);
  if (scope.scope_type === 'DOCUMENT') return '整份文档';
  const reference = snapshotObject(scope.scope_ref);
  const block = String(reference.block_id);
  if (scope.scope_type === 'SECTION') return '章节区块 ' + block;
  if (scope.scope_type === 'SELECTION') return '区块 ' + block + ' 内的选中文本';
  return '区块 ' + block;
}

function pathDescription(change: JsonObject): string {
  const step = referenceName(change.step_ref);
  switch (change.type) {
    case 'SET_GOAL':
      return '更新目标：' + String(change.text);
    case 'ADD_STEP':
      return '新增步骤：' + String(change.title);
    case 'RENAME_STEP':
      return step + '更名为“' + String(change.title) + '”';
    case 'MOVE_STEP':
      return (
        '将' +
        step +
        '移至' +
        (change.before_step_ref === null ? '末尾' : referenceName(change.before_step_ref) + '之前')
      );
    case 'SET_DEPENDENCIES':
      return step + '的前置步骤：' + (names(change.dependencies) || '无');
    case 'UPDATE_RESULT':
      return '更新成果 ' + String(change.result_ref) + '：' + String(change.description);
    case 'ADD_RESULT':
      return step + '新增成果：' + String(change.description);
    case 'CANCEL_STEP':
      return (
        '取消' +
        step +
        (Array.isArray(change.replacement_step_refs) && change.replacement_step_refs.length
          ? '，承接至' + names(change.replacement_step_refs)
          : '')
      );
    case 'LINK_CONTENT':
      return (
        '将文档历史版本 ' +
        String(change.revision_id) +
        ' 的区块 ' +
        (Array.isArray(change.block_ids) ? change.block_ids.join('、') : '') +
        ' 关联至' +
        step +
        '，覆盖成果 ' +
        names(change.result_refs)
      );
    case 'MOVE_ISSUE':
      return '将问题 ' + String(change.issue_ref) + '转交至' + referenceName(change.to_step_ref);
    case 'SET_BRANCH_RETURN':
      return (
        '将支线 ' +
        String(change.branch_ref) +
        '的返回位置改为' +
        referenceName(change.return_step_ref)
      );
    case 'DISPOSE_ISSUE':
      return (
        disposition(change.disposition) +
        '问题 ' +
        String(change.issue_ref) +
        '：' +
        String(change.reason)
      );
    case 'DISPOSE_BRANCH':
      return (
        disposition(change.disposition) +
        '支线 ' +
        String(change.branch_ref) +
        '：' +
        String(change.reason)
      );
    case 'RESUME_ISSUE':
      return '恢复问题 ' + String(change.issue_ref);
    default:
      throw new TypeError('Unregistered immutable route change');
  }
}
export function FormationProposalDetails({
  state,
  owner,
  render,
}: Readonly<{
  state: CardsState;
  owner: InteractionCards;
  render?: MessageMarkdownRenderer;
}>) {
  const purpose = state.cards.purpose,
    payload = state.cards.action_payload;
  if ((purpose !== 'STAGED_WRITE' && purpose !== 'FORMATION_PATH_CHANGE') || payload === null)
    return null;
  return (
    <FormationPayloadDetails
      purpose={purpose}
      payload={payload}
      read={owner.readReference}
      {...(render === undefined ? {} : { render })}
    />
  );
}
export function FormationPayloadDetails({
  purpose,
  payload,
  read,
  render,
}: Readonly<{
  purpose: 'STAGED_WRITE' | 'FORMATION_PATH_CHANGE';
  payload: JsonObject;
  read: (source: unknown, signal: AbortSignal) => Promise<SourceReading>;
  render?: MessageMarkdownRenderer;
}>) {
  const sources = Array.isArray(payload.source_refs) ? payload.source_refs.map(sourceRef) : [];
  return (
    <section className="formation-proposal-details" aria-label="提案原文与采用范围">
      <h4>{purpose === 'STAGED_WRITE' ? '待写入内容' : '待采用的路线调整'}</h4>
      <p>{String(payload.change_summary)}</p>
      {purpose === 'STAGED_WRITE' ? (
        <>
          <p>
            {referenceName(payload.step_ref)} · 文档版本 V{String(payload.content_version)} ·{' '}
            {names(payload.result_refs)}
          </p>
          <p>
            采用范围：
            {adoptionScopeLabel(payload.scope)}
          </p>
          {typeof payload.markdown_content === 'string' ? (
            <MessageContent content={payload.markdown_content} {...(render ? { render } : {})} />
          ) : (
            Array.isArray(payload.patches) &&
            payload.patches.map((value, index) => {
              const patch = snapshotObject(value);
              return (
                <section
                  key={index}
                  className="formation-patch-preview"
                  aria-label={'精确修改 ' + (index + 1)}
                >
                  <h5>{String(patch.title)}</h5>
                  <p>{String(patch.explanation)}</p>
                  <p>
                    区块 {String(snapshotObject(patch.target_ref).block_id)}
                    {patch.patch_operation === 'REPLACE_TABLE_ROW' && patch.selector_json !== null
                      ? ' · 匹配行：' + String(snapshotObject(patch.selector_json).key_value)
                      : ''}
                  </p>
                  <p>原文</p>
                  <pre>{String(patch.original_content)}</pre>
                  {patch.patch_operation === 'DELETE_BLOCK' ? (
                    <p>采用后删除此区块。</p>
                  ) : (
                    <>
                      <p>
                        {patch.patch_operation === 'INSERT_BEFORE'
                          ? '在原文前插入'
                          : patch.patch_operation === 'INSERT_AFTER'
                            ? '在原文后插入'
                            : '更新为'}
                      </p>
                      {typeof patch.proposed_markdown === 'string' ? (
                        <MessageContent
                          content={patch.proposed_markdown}
                          {...(render ? { render } : {})}
                        />
                      ) : (
                        <pre>
                          {Array.isArray(snapshotObject(patch.proposed_data_json).cells)
                            ? (snapshotObject(patch.proposed_data_json).cells as Json[]).join(' | ')
                            : ''}
                        </pre>
                      )}
                    </>
                  )}
                </section>
              );
            })
          )}
        </>
      ) : (
        <>
          <ol>
            {Array.isArray(payload.changes) &&
              payload.changes.map((value, index) => {
                const change = snapshotObject(value);
                return (
                  <li key={index}>
                    <p>{pathDescription(change)}</p>
                    {Array.isArray(change.expected_results) && (
                      <ul>
                        {change.expected_results.map((result, i) => (
                          <li key={i}>
                            {referenceName(snapshotObject(result).temp_result_ref)}：
                            {String(snapshotObject(result).description)}（
                            {snapshotObject(result).kind === 'CONTENT' ? '正文成果' : '讨论结论'}）
                          </li>
                        ))}
                      </ul>
                    )}
                    {change.type === 'ADD_STEP' && (
                      <p>
                        前置：{names(change.dependencies) || '无'}；替代：
                        {names(change.replaces_step_refs) || '无'}；位置：
                        {change.before_step_ref === null
                          ? '末尾'
                          : referenceName(change.before_step_ref) + '之前'}
                      </p>
                    )}
                  </li>
                );
              })}
          </ol>
          {Array.isArray(payload.result_routes) && payload.result_routes.length > 0 && (
            <section aria-label="成果要求的承接安排">
              <h5>成果承接</h5>
              <ul>
                {payload.result_routes.map((value, index) => {
                  const route = snapshotObject(value);
                  return (
                    <li key={index}>
                      {String(route.from_result_ref)}：
                      {route.disposition === 'NOT_REQUIRED'
                        ? '不再要求'
                        : '由 ' + names(route.target_result_refs) + ' 承接'}
                      。{String(route.reason)}
                    </li>
                  );
                })}
              </ul>
            </section>
          )}
        </>
      )}
      {sources.length > 0 && (
        <details>
          <summary>查看提案依据</summary>
          <ul>
            {sources.map((source, index) => (
              <li key={index}>
                <SourceReference
                  read={(signal) => read(source, signal)}
                  label={
                    source.kind === 'REVISION'
                      ? '文档历史版本 ' + source.revision_id
                      : source.kind === 'MESSAGE' || source.kind === 'CARD_ANSWER'
                        ? '对话消息 ' + source.message_id
                        : '运行 ' + source.guide_run_id + ' 的材料'
                  }
                />
              </li>
            ))}
          </ul>
        </details>
      )}
    </section>
  );
}
