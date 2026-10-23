# WALL-E V1_0.6 上下文封装与缓存迭代 V1

2026-10-16已合并：本迭代最终采用规则已按原模板合入前端1.1-draft-sync9／后端1.0-draft-sync3的相关职责位置；历史暂停、服务进程和“未回写”描述保留当时含义；FLOW-002被替代门禁不恢复。合入去向见[2026-10-16合并记录](../../merges/v1.0/合并记录-2026-10-16.md)。

日期：2026-10-11。迭代编号：CTX-001。用户指示：“写迭代文档，然后更改代码部分”。状态：源码已实施，未验证、未更新服务；仅源码与文档，验证和服务更新仍暂停。

## 1. 问题与目标

需求创建的初始化和详情后续对话共享同一需求下的消息记录；每次调用独立组装 System 与完整 User，不建立供应方持续 Session。历史仅读取最近最多10条 TEXT／正式 CARD_RESPONSE，2048 token 分项预算和优先删最老完整消息的规则保持。

原 User 顺序为协议标识、requirement、current_document、template、scope、allowed_targets、user_input、history、source、read_manifest。CURRENT 的身份和版本位于大模板之前，本轮输入位于历史之前，易变字段提前打断可复用前缀。

新原则：固定规则和完整模板在前，当前正文与近期历史居中，本轮输入及易变信息在后。全部事实、对象身份、来源与授权信息继续传递；不改变业务可信度优先级。

## 2. 新封装

System 保持任务固定指令及派生输出 Schema，并补充正文与尾部身份按数组位置关联的说明。User 使用独立 `stable_prefix_v1` 传输布局：

| 顺序 | 字段 | 内容 |
| --- | --- | --- |
| 1 | schema_version／function_type／action_type／source_type | 本次任务固定协议标识 |
| 2 | template | 模板键、版本及完整 Markdown；锁定区块身份移到尾部 |
| 3 | current_document | 按原顺序保留实际读取区块的 Markdown、plain_text、heading_level |
| 4 | history | 原历史顺序的 role、message_type、content、formal_responses |
| 5 | user_input | 本轮真实 content 和 formal_responses |
| 6 | source | 原完整评论或评审来源快照，或 null |
| 7 | request_metadata | 需求属性、CURRENT id/version、锁定标题ID、逐块完整元数据、历史id/sequence_no、本轮message_id、Scope、Allowed Targets和Read Manifest |

`current_document.read_blocks[i]` 与尾部 `read_block_metadata[i]` 严格一一对应；`history[i]` 与 `history_message_refs[i]` 同样对应。不得排序、合并或按文本猜测身份。正式回答内部结构及来源快照不剥离字段。模型使用尾部实际ID引用目标和证据，尾部Scope／Allowed Targets继续控制权限。

内部应用上下文与旧输入 Schema 不改。序列化前完成原完整 Schema 校验，再校验新传输 Schema；只在发送边界重排和拆分。计数、裁剪后的重建、审计回放及诊断组装共用同一序列化入口，不能出现计数旧文本、发送新文本。

## 3. 版本与预算

新增资源发布 `backend/resources/v4/`：普通模板新运行冻结 Function／Prompt／Context v4，完整新需求模板 `new-requirement@v2` 新运行冻结 v5；两者分别继承 v2／v3 的全部预算和业务输出协议。共享六份独立传输输入 Schema v2。创建模板目录与前端模板锁资源保持。

新增 counting/v5（普通预算）及 counting/v6（完整模板预算），固定绑定新发布及对应 Function 版本。保留精确六项计数、1024经验封装余量、实际usage复核及不具备通用封装上界证明的边界。新增准入仅承接原已批准准入和本次封装变更，不授权新的真实观测或付费调用。

所有已持久化运行按自己的 v1／v2／v3／v4／v5 协议恢复。普通等待继续保持原冻结版本；新创建、初始化卡片产生的新运行、评论修改及重跑采用新默认。旧 resources/v1—v3、counting/v1—v4 及历史审计不原地改写。不新增 Session，不改变自动初始化触发或用户正文。

## 4. 缓存边界

方舟隐式缓存按公共前缀自动尝试复用，不要求持续 Session；命中受缓存淘汰及路由影响。依据：[官方上下文缓存说明](https://docs.volcengine.com/docs/ark/context-cache?lang=zh)。

相同任务、模板和正文更容易保留长前缀；不同任务的 System 不同，正文编辑、历史窗口滑动或裁剪也会改变前缀。完整模板在 INITIALIZE 与后续操作之间可复用的长度仍受不同 System 限制。重排不是命中率或费用保证。实际命中依供应方 `usage.prompt_tokens_details.cached_tokens`，原缓存用量审计保持，本轮未测命中率。

## 5. 实施记录与待验证

先建立本独立文档，再完成下列源码修改：

| 文件／范围 | 实施内容 |
| --- | --- |
| `backend/resources/v4/` | 12份Prompt、12份Context、六份传输Schema、Function清单与固定Manifest；发布SHA256为`8e0800c8c2ddaf704d18e3a94246bf7af9c64e9a107288399b060e37cb8e77b4` |
| `infrastructure/resources.py` | 先注册历史资源，再选择普通v4／完整模板v5；新增传输Schema身份并固定验证新发布 |
| `guide/context_builder.py` | 共用传输组装／序列化／还原入口；按位置配对正文与身份，数组长度不一致拒绝 |
| `guide/counted_context.py`、`counting/v5—v6/`、`production_ai.py` | 各预算独立固定策略与准入；最终wire精确计数、裁剪后重建、证据回放使用同一入口；绑定Function版本及发布 |
| `audit_repository.py`、`counting_journal.py`、`trusted_output.py`、`output_evidence.py` | 审计实际wire及传输Schema v2；还原完整内部对象后复核实际数据和身份，保留原事实／权限／采用保护 |
| `framing_probe.py`、`tools/ai-service.py` | 诊断组装复用序列化／还原入口；启动工具展示新布局，但本轮未执行 |
| `backend/tests/infrastructure/test_context_layout.py` | 新增待执行专项源码：两预算与历史恢复、完整往返、稳定前缀、配对错位拒绝、计数／发送／审计同文、裁剪回放、资源篡改拒绝 |
| 旧D-010／D-011／D-015夹具及完整模板专项源码 | 历史观测和旧协议场景明确部署v1／v2；完整模板新运行预期更新为v5；不改原计划及验收结论 |

源码静态阅读已覆盖创建／新运行版本选择、等待继续及历史恢复、wire组装、精确计数、计数日志、调用准备、已调用审计还原、可信输出及实际usage复核。原资源与冻结历史字节保留；仅新接纳运行采用新布局。System新增配对说明仍受原4096 token分项预算约束，实际长度和模型效果待获准专项确认。

本轮不运行测试、类型检查、构建、浏览器验收、Tokenization或Chat；不启动或重启服务，不读写用户业务数据。后续获准专项需覆盖新旧版本恢复、六任务两预算、新布局Schema及身份配对、计数回放与裁剪、篡改拒绝，以及真实调用时的System预算与缓存统计。源码检查不宣称验收通过。

## 6. 后续专项与服务加载（2026-10-11）

用户后续授权模板报错所需检查与后端重启。上下文6项离线专项已通过；首次2项因模拟计数回执字段缺失而报错，补齐测试夹具后重跑通过，生产校验保持。覆盖两预算六任务及历史恢复、布局完整往返和稳定前缀、身份配对／篡改拒绝、精确wire同文及裁剪回放。后端新进程已加载新布局，实际GET及前端代理正常；没有真实模型请求，System真实token预算及缓存命中率仍待验证。详见[专项记录](../../../verification/v1.0/template-context-service-2026-10-11.md)。上节未执行说明为初次实施时的历史状态。
