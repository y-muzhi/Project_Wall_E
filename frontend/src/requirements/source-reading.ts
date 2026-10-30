import { positiveInteger } from '../api/client.ts';
import { sourceRef, collaborationValue } from '../api/models.ts';
import type { Message } from '../api/models.ts';
import type { WalleApi } from '../api/walle.ts';
export type SourceReading = Readonly<{ title: string; content: string }>;
export type SourceReadApi = Pick<
  WalleApi,
  'getRevision' | 'listMessages' | 'getGuideRun' | 'listModelCalls' | 'getModelCall'
>;
const json = (value: unknown) => JSON.stringify(value, null, 2);

/** Lazy actual source reads, with no command, reassembly or count capability. */
export async function readSource(
  requirement: number,
  input: unknown,
  api: SourceReadApi,
  signal: AbortSignal,
): Promise<SourceReading> {
  positiveInteger(requirement);
  const source = sourceRef(input),
    id = (name: string) => positiveInteger(source[name]);
  const alive = () => {
    if (signal.aborted) throw Error('来源读取已取消');
  };
  alive();
  async function message(identity: number): Promise<Message> {
    let cursor: number | null = null;
    const seen = new Set<number>();
    while (true) {
      alive();
      const page = await api.listMessages(requirement, cursor, signal);
      alive();
      if (page.data.items.some((item) => item.requirement_id !== requirement))
        throw Error('来源不属于本需求');
      const found = page.data.items.find((item) => item.id === identity);
      if (found) return found;
      const pagination = page.meta.pagination;
      if (!pagination || !('has_more' in pagination)) throw Error('来源分页记录不完整');
      if (!pagination.has_more || pagination.next_cursor === null) throw Error('来源消息不存在');
      if (seen.has(pagination.next_cursor)) throw Error('来源分页无法继续');
      seen.add(pagination.next_cursor);
      cursor = pagination.next_cursor;
    }
  }
  if (source.kind === 'REVISION') {
    const revision = (await api.getRevision(id('revision_id'), signal)).data;
    alive();
    if (revision.requirement_id !== requirement || revision.document_id !== id('document_id'))
      throw Error('版本不属于引用文档');
    const ids = source.block_ids;
    if (
      Array.isArray(ids) &&
      ids.some(
        (identity) =>
          !revision.block_state_json.blocks.some((block) => block.block_id === identity),
      )
    )
      throw Error('引用区块已不可用');
    return {
      title: `文档 #${revision.document_id} · V${revision.source_content_version}`,
      content:
        (Array.isArray(ids)
          ? '引用区块：' + ids.map((identity) => '#' + identity).join('、') + '\n该版本全文：\n\n'
          : '') + revision.markdown_content,
    };
  }
  if (source.kind === 'MESSAGE' || source.kind === 'CARD_ANSWER') {
    const actual = await message(id('message_id'));
    if (source.kind === 'MESSAGE') return { title: `消息 #${actual.id}`, content: actual.content };
    if (
      actual.role !== 'USER' ||
      actual.message_type !== 'CARD_RESPONSE' ||
      actual.reply_to_message_id === null ||
      actual.structured_content === null
    )
      throw Error('来源不是正式回答');
    const question = await message(actual.reply_to_message_id);
    alive();
    const cards = question.structured_content as {
      cards?: {
        card_key: string;
        question: string;
        options: { option_key: string; label: string }[];
      }[];
    } | null;
    const answer = (
      actual.structured_content as {
        responses?: {
          card_key: string;
          selected_option_keys: string[];
          custom_answer: string | null;
          skipped: boolean;
        }[];
      }
    ).responses?.find((item) => item.card_key === source.card_key);
    const card = cards?.cards?.find((item) => item.card_key === source.card_key);
    if (!answer || !card || question.role !== 'ASSISTANT') throw Error('正式回答与原题不匹配');
    return {
      title: `正式回答 #${actual.id}`,
      content: [
        card.question,
        ...(answer.skipped
          ? ['已跳过']
          : [
              ...answer.selected_option_keys.map((key) => {
                const option = card.options.find((item) => item.option_key === key);
                if (!option) throw Error('正式选项不属于原题');
                return option.label;
              }),
              ...(answer.custom_answer === null ? [] : [answer.custom_answer]),
            ]),
      ].join('\n'),
    };
  }
  const run = (await api.getGuideRun(id('guide_run_id'), signal)).data;
  alive();
  if (run.requirement_id !== requirement || run.status !== 'COMPLETED')
    throw Error('来源运行尚不可读取');
  if (source.kind === 'RUN_RESULT') {
    const actual = run.final_result?.analysis;
    if (actual === null || actual === undefined) throw Error('该运行未保存可引用的分析结果');
    return {
      title: `运行 #${run.id} · 分析结果`,
      content: json(collaborationValue('Analysis')(actual)),
    };
  }
  const calls = (await api.listModelCalls(run.id, signal)).data;
  alive();
  if (calls.requirement_id !== requirement || calls.id !== run.id)
    throw Error('请求记录不属于来源运行');
  for (const call of calls.items) {
    const detail = (await api.getModelCall(call.id, signal)).data;
    alive();
    if (
      detail.requirement_id !== requirement ||
      detail.call.guide_run_id !== run.id ||
      detail.call.id !== call.id
    )
      throw Error('保存请求归属异常');
    const selection = detail.selection_summary;
    if (!selection || !('selected_materials' in selection) || detail.raw_request_json === null)
      continue;
    const selected = selection.selected_materials.find(
      (item) =>
        item.ref === source.material_ref ||
        (Array.isArray(item.source_refs) &&
          item.source_refs.some((ref) => {
            const actual = ref as Record<string, unknown>;
            return (
              actual.kind === 'RUN_MATERIAL' &&
              actual.guide_run_id === source.guide_run_id &&
              actual.material_ref === source.material_ref
            );
          })),
    );
    if (!selected) continue;
    const request = JSON.parse(detail.raw_request_json) as {
        messages: { role: string; content: string }[];
      },
      wire = collaborationValue('Wire')(
        JSON.parse(request.messages.find((item) => item.role === 'user')!.content),
      );
    const blockIds = selected.block_ids as number[],
      messageIds = selected.message_ids as number[];
    const documents = (wire.documents as Record<string, unknown>[])
      .filter(
        (item) =>
          item.document_id === selected.document_id && item.revision_id === selected.revision_id,
      )
      .map((item) => ({
        ...item,
        blocks: (item.blocks as { block_id: number }[]).filter((block) =>
          blockIds.includes(block.block_id),
        ),
      }));
    const messages = [wire.current_request, ...(wire.recent_history as unknown[])].filter((item) =>
      messageIds.includes(Number((item as Record<string, unknown>).message_id)),
    );
    const texts = (wire.goal_and_decisions as { ref: string }[]).filter(
      (item) =>
        item.ref === selected.ref || messageIds.some((identity) => item.ref === 'm' + identity),
    );
    return {
      title: `运行 #${run.id} · 已携带材料 ${String(selected.ref)}`,
      content: json({ documents, messages, texts }),
    };
  }
  throw Error('该材料未记录为来源运行的实际已携带内容');
}
