import { readFileSync, writeFileSync, existsSync } from 'node:fs';
import { resolve } from 'node:path';

const root = resolve(import.meta.dirname, '..');
const output = resolve(root, 'docs/需求实现映射.md');
if (existsSync(output)) throw new Error('Mapping already exists. Edit incrementally; do not overwrite reviewed mappings.');
const sources = JSON.parse(readFileSync(resolve(root, 'docs/sources/manifest.json'), 'utf8'));
const known = {
  'frontend:fe-ui-principles': ['黑白灰主体；真实区分受理/完成/未知结果；就近反馈；键盘焦点；减少动态效果', '浏览器检查页面/组件、焦点和减少动态效果；尚未执行'],
  'frontend:fe-ui-color': ['主按钮近黑色；保留成功绿色、危险/失败红色；已固定局部值优先', '实际 CSS 与浏览器核对；尚未执行'],
  'frontend:fe-ui-typography': ['系统无衬线与代码字体栈；筛选14px已定；其余建议集中为暂定参数', '字体回退、可读性和正文/历史对照；尚未执行'],
  'frontend:fe-ui-layout': ['保持局部宽度/圆角；留白分层；正文居中；未知提交保留用户内容', '实际尺寸/滚动/布局；尚未执行'],
  'backend:shr-id': ['整数身份/版本/序号1～9007199254740991；REQ六位业务编号与实体ID区分；请求键UUID v4', '边界、不同实体身份、原子分配、耗尽测试；未执行；Q-ID待决定'],
  'backend:shr-time': ['UTC毫秒输出；created_at不变；查询/无变化/重复状态动作不刷新事件时间', '受控时钟、接口时间格式及数据库前后快照；尚未执行'],
  'backend:shr-text': ['CRLF/CR转LF；普通文本Unicode首尾空白去除；码点长度；Markdown/定位片段不trim、不归一化、不裁剪', 'Unicode/换行/各字段边界及前后端契约测试；尚未执行'],
  'backend:shr-concurrency': ['事务内重读并原子比较所属文档版本；冲突不覆盖；占用关联不一致拒绝', '实际数据库并发屏障及冲突后快照；尚未执行'],
  'backend:shr-idempotency': ['相同键同输入重放；异输入冲突；进行中拒绝；成功记录与业务原子提交；无键动作不假定网络失败未写入', '实际存储/HTTP响应丢失及进程中断；未执行；Q-03待决定'],
  'backend:shr-result': ['应用结果code/data/details与HTTP分开；失败默认不改数据；C05孤立锚点例外；真实调用审计不随业务回滚抹除', '结果投影、异常及实际事务/审计测试；尚未执行'],
  'backend:shr-page': ['默认1、合法1～100000、固定20；空总页0；合法越界保留请求页；列表/总数同快照；消息独立游标', '真实数据库分页稳定性与空/越界测试；尚未执行'],
  'backend:shr-serialize': ['重复JSON键/未知字段/错误类型拒绝；JSON逻辑对象；白名单投影；单JSON可信校验；损坏历史消息仅指定降级', '原始HTTP字节解析、投影与模型解析；尚未执行'],
  'backend:obj-req': ['需求身份、固定模板、生命周期及互斥占用；7类状态关系与事件时间；无业务删除', '对象约束及生命周期事务场景；尚未执行'],
  'backend:obj-doc': ['同需求同文档类型唯一；CURRENT/草稿独立实例与版本；Markdown和区块状态完整快照；不可交换类型晋升', '对象约束、完整快照和数据库唯一性；尚未执行'],
  'backend:shr-block': ['schema_version=1；唯一block_id；next_block_id上界；顶层顺序、章节路径及来源元数据；不泄漏到Markdown', '前后端同算法、编辑器实际节点与序列化；未执行；Q-06族待决定'],
  'backend:obj-rev': ['不可变正文/区块快照；需求内version_no唯一；BASELINE=1且唯一；不含评论、不恢复历史', '真实快照、不可变及唯一性验证；尚未执行'],
  'backend:obj-msg': ['不可变USER/ASSISTANT消息；需求内sequence_no唯一；TEXT/卡片/回答条件；每组正式回答唯一', '对象/数据库唯一性与卡片提交事务；尚未执行'],
  'backend:shr-cards': ['完整1～5卡；选项及卡片键唯一；推荐仅展示；单选/自定义互斥；多选计数；必答不可跳过；整组覆盖', '结构和答案组合边界、用户选择与推荐隔离；尚未执行'],
  'backend:obj-guide': ['冻结协议与版本；真实请求LLMUse独立记录；call_no/attempt_no唯一；最多3次；传输/解析/校验分离；未知用量null；迟到结果不采用', '实际网关请求计数、取消/持久化竞争、审计与恢复；尚未执行'],
  'backend:obj-batch': ['每MODIFY运行最多一批；至少一项；单项四状态；整批终态；实际变更才有应用版本；counts由读取派生', '决策/批次状态与原子应用、无变化分支；尚未执行'],
  'backend:shr-patch': ['5类固定补丁操作；目标/顺序不可改；DELETE不可EDITED；行编辑仅cells JSON文本；非EDITED清除编辑值', '组合补丁/授权/原文比较/不部分采用；未执行；Q-06-PATCH待决定'],
  'backend:obj-comment': ['原引用不变；OPEN/RESOLVED与ATTACHED/ORPHANED独立；软删除；同锚点允许多评论；区块ID不是数据库外键', '对象/软删除/状态并发与生命周期测试；尚未执行'],
  'backend:shr-anchor': ['BLOCK完整Markdown后端构造；SELECTION单块唯一定位；原引用不变；重校验仅改anchor_status、不改updated_at；原块可自动恢复', '真实正文变更及重校验、查询无副作用；未执行；Q-06-ANCHOR待决定'],
};
const rows = [
  '# 需求实现映射', '',
  '目标：WALL-E V1_0.6。状态只用：未开始、实现中、已实现待验证、已验证、阻塞。业务已验证必须有对应范围和证据。', '',
  '这是持续维护台账。自动建立的稳定锚点行只是遗漏检查底稿：标为“待完整正文复核”的行不表示全文已读或行为已梳理。所有业务单元当前未开始；来源读取状态在 reading-ledger.json 单独记录。每次实现前重新阅读对应完整正文、公共规则及失败分支。实现时应将较大来源行继续拆为独立可核验单元。', '',
  '原文路径/内容哈希见 [实现进度.md](实现进度.md) 与 [来源清单](sources/manifest.json)。完整定位见 [设计来源索引.md](设计来源索引.md)。', '',
  '| 设计来源与条目 | 需要实现的行为及边界 | 实现位置 | 验证依据与证据 | 状态 | 阻塞或差异 |',
  '| --- | --- | --- | --- | --- | --- |',
];
function cell(value) { return value.replaceAll('|', '／').replaceAll('\n', ' '); }
for (const source of sources) {
  for (const anchor of source.anchors) {
    const item = known[`${source.key}:${anchor.id}`];
    const title = anchor.text.replace(/^\|/, '').split('|')[0].replace(/^#+ /, '').replaceAll('**', '').slice(0, 100);
    const isIssue = /^(?:q-|fe-q)/.test(anchor.id);
    const behavior = item?.[0] ?? (isIssue ? '待确认事项原文已读；需结合全部影响条目形成具体决策，尚未关闭' : '待完整正文复核：条件、处理、结果、失败分支及验收均未梳理');
    const evidence = item?.[1] ?? '未执行；验收场景关联待正文复核';
    rows.push(`| ${cell(source.key)} L${anchor.line} #${cell(anchor.id)} ${cell(title)} | ${cell(behavior)} | — | ${cell(evidence)} | 未开始 | ${isIssue ? '尚未关闭；路线/起草授权见决策记录，未将其视为批准全部细则' : item ? '只完成来源阅读；尚未实现' : '正文尚未复核；不作为已理解条目'} |`);
  }
}
rows.push('', '## 已读来源拆分的独立内容单元', '', '| 设计来源与条目 | 需要实现的行为及边界 | 实现位置 | 验证依据与证据 | 状态 | 阻塞或差异 |', '| --- | --- | --- | --- | --- | --- |');
const units = [
  ['FE L234–351 WB-OP01 输入/筛选', '搜索草稿与已提交条件分开；筛选用已提交关键词；全选省略；变更回首页；清除只发一次', 'FE-Q-FILTER存在清空/匹配冲突，需要具体决策'],
  ['FE L273–328 WB-OP01 请求竞态', '只有最新请求可更新数据/分页/错误/加载；旧请求成功或失败及完成通知都忽略', '需要真实响应顺序控制'],
  ['FE L329–351 工作台特殊状态', '首次/刷新加载失败与空/无匹配/合法越界区分；失败保留历史结果及其所属条件', '不伪造total=0；测试每种状态'],
  ['FE L303–319 WB-OP02 导航恢复', '列表拖选不跳转；使用实体ID；保存已提交条件、页码、滚动；返回先刷新再恢复；越界可返回有效页', 'FE-Q01路由和恢复载体待确认'],
  ['FE L315–319 WB-OP03 创建', '抽屉成功后用ID进入详情；失败保留输入；取消保留列表条件', 'CREATE正文及后端创建能力尚未读；Q-01资源待稿'],
  ['BE L207–230 OBJ-REQ 占用一致性', 'IDLE引用与开始时间均null；非IDLE必须类型/ID/状态/开始时间一致；completed_at随生命周期', '真实存储关系和竞争测试未执行'],
  ['BE L277–325 OBJ-DOC 快照与来源', 'Markdown/BlockState同一时点和顶层顺序；ID唯一；创建时间不晚于修改时间；既有创建来源不可改', 'Q-06解析及身份算法待稿'],
  ['BE L359–382 OBJ-REV 不可变及编号', 'requirement/version唯一；BASELINE只能1且最多一条；快照来源content_version；全部字段不可变', 'Q-ID及数据库DDL待稿'],
  ['BE L416–487 OBJ-MSG 卡片合法性', 'TEXT字段null；卡片仅助手；回答仅用户且指同需求原组；每原组正式回答至多一条；用户消息幂等键', '完整卡片提交能力尚未读；Q-CARD-STATE待稿'],
  ['BE L579–610 OBJ-GUIDE 计量与状态', '真实尝试最多3；未知token/duration/id按nullable；冻结协议；取消不反向改传输终态或可信输出', '模型供应方/协议及评测待确认'],
  ['BE L712–735 OBJ-BATCH 单项决定', 'EDITED必须合法；其他状态清除编辑值；DELETE拒绝EDITED；目标操作选择器顺序不可改', 'Q-06-PATCH算法待稿'],
  ['BE L821–834 SHR-ANCHOR 投影/持久化', '查询location独立计算；正文提交重校验不刷新评论事件时间；原block唯一定位才可恢复；无人工重新挂载', 'Q-06-ANCHOR算法待稿'],
];
for (const [source, behavior, difference] of units) rows.push(`| ${source} | ${behavior} | — | 原文已读；业务验证未执行 | 未开始 | ${difference} |`);
writeFileSync(output, rows.join('\n') + '\n');
console.log(JSON.stringify({ sourceAnchors: sources.reduce((sum, source) => sum + source.anchors.length, 0), splitUnits: units.length, path: output }));
