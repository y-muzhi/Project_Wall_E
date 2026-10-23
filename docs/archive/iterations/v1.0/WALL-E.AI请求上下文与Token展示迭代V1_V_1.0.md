# WALL-E V1_0.6 AI请求上下文与Token展示迭代V1

2026-10-16已合并：本迭代最终采用规则已按原模板合入前端1.1-draft-sync9／后端1.0-draft-sync3的相关职责位置；历史暂停、服务进程和“未回写”描述保留当时含义；FLOW-002被替代门禁不恢复。合入去向见[2026-10-16合并记录](../../merges/v1.0/合并记录-2026-10-16.md)。

日期：2026-10-11。编号：UX-032／OBS-001。用户已要求实施“对话内摘要＋详情面板”方案。

## 1. 目标与范围

用户需要直接看到每次请求实际携带的上下文和 token 用量，便于判断答案是否被传入、历史携带了哪些条目、使用了哪个正文版本，以及是否命中缓存。

本轮接入展示与只读查询。提示词、上下文排序／裁剪策略、模型参数、卡片提交、模型返回展示和事实确认直接写入均沿用原实现。原始设计归档不修改，本记录独立于 FLOW-001—005 和 CTX-001。

## 2. 界面结构

### 2.1 对话内请求摘要

每条带运行身份的用户消息下显示紧凑请求记录，位于用户气泡外，包含操作、运行状态、调用时间、模型名称、调用状态和“查看上下文”入口。下一行显示输入、输出、合计、缓存命中及调用耗时；多次调用／尝试默认折叠，可展开逐次查看。

摘要按请求快照中保存的 `user_message_id` 关联输入消息。同一运行的多轮输入各显示其自己的调用，避免把整个运行的用量重复算到每条消息。运行重试或触发消息不在当前消息窗口时，在当前任务区域显示运行摘要作为补充。

程序确认事实后直接写入的运行显示“程序已处理，未调用模型”，不伪造 0 token。准备中、取消、失败且没有调用、读取失败和旧调用缺少输入身份分别说明。旧调用仍可打开运行上下文；不猜测属于哪条输入。

### 2.2 AI 面板内详情

“查看上下文”在当前 AI 面板内覆盖显示详情；文档正文和全局导航保持现有布局。原对话、卡片草稿、输入组件和滚动容器保持挂载，底层暂设 `inert`，关闭后焦点回到原入口。关闭按钮和 Esc 均返回对话。

详情由固定头部及独立滚动内容组成，复用公共 SingleSelect 切换调用／尝试：

1. 调用概览：模型、操作、状态、开始／结束时间、耗时、提示词及上下文版本、采用正文版本、解析／业务校验状态。
2. 实际携带的上下文：按保存的消息及 User JSON 键顺序展示，分为系统规则、模板、读取正文、历史、本轮输入、来源和身份／范围／权限。旧协议保留其真实顺序。
3. Token 用量：模型返回的实际消耗与发送前计数、预算分开。
4. 原始请求：保存的 Chat 请求对象，支持格式化 JSON 与紧凑 JSON 原文切换及复制。

上下文默认折叠；摘要显示字符数、区块数、历史条数，正文存在明确 `heading_level` 时显示章节标题数。展开模板显示完整 Markdown；正文按实际读取区块显示编号／章节，历史展示实际传入的消息正文。搜索作用于快照文字，匹配内容片段出现在折叠标题下；各部分可复制完整保存内容。

默认不挂载大型上下文的完整展示内容；正文区块内部再次折叠。原始 JSON 仅在展开时挂载。上述都是本地阅读操作。

### 2.3 运行记录复用

“文档记录 → 运行记录 → 运行详情”显示该运行全部调用的摘要，使用同一个 ModelCallDrawer 查看上下文和用量。该页面继续使用原 GuideRunPolling，不选择或替换 AI 对话的任务，不携带业务提交按钮。

## 3. 数据与字段含义

| 字段 | 含义与缺失处理 |
| --- | --- |
| `id / guide_run_id / call_no / attempt_no` | 保存的调用身份、所属运行、逻辑调用和尝试编号；按 call_no、attempt_no、id 排序 |
| `user_message_id` | 该次输入身份；新布局从 request_metadata 读取，旧布局从 user_input.message_id 读取，缺失为 null |
| `document_version` | 请求实际采用的正文版本；从保存的请求元信息读取，不读取当前 CURRENT |
| `call_status` | 请求在途／成功返回／失败／取消；与运行总体状态、解析和业务校验状态分开 |
| `input_tokens / output_tokens` | 保存的 Provider 实际用量；缺失为 null，界面显示“未记录”；已记录的真实 0 可展示 |
| `total_tokens` | 两项实际用量都已记录时求和，否则为 null；跨调用汇总含全部尝试，任一项未知则不猜测完整汇总 |
| `cached_tokens` | 保存的 cache_info.cached_tokens，是输入的子集，不再次计入合计 |
| `duration_ms` | 保存的调用耗时，显示秒；多次调用为记录耗时之和，不声称是整个运行的墙钟耗时 |
| `prompt_reference / context_reference` | 快照冻结的协议引用；缺失显示“未记录” |
| `sections` | 同一保存请求的可读分段；content、Unicode 字符长度及已有数组项数，不生成新 token 估计 |
| `included_history_ids` | 新布局 history_message_refs 或旧布局 history 中保存的历史身份；不按当前消息窗口推算 |
| `budget_removed_history_ids` | 最后一次已保存计数尝试明确记录的预算裁剪历史；仅存在记录时展示，不猜测其他裁剪原因 |
| `raw_request_json` | 审计保存的 Chat 请求体 JSON；包括原始 messages 和参数，不暴露外围 Profile、凭据或计数日志 |
| `preflight.input_tokens` | 发送前输入计数候选，包含已有封装余量；不等同 Provider 实际输入 |
| `preflight.budget` | 根据已保存 release_sha256 恢复的冻结预算；无法恢复时为 null，不套用当前预算 |
| `preflight.counts` | 最后计数尝试的六项已有计数：System、完整 User JSON、本轮输入、来源、模板、历史；缺失项为 null |

独立内容计数与完整 User JSON 重叠，只作为组成内容参考，不相加、不绘制占比图。正文／权限没有独立计数记录时仅展示内容与长度，不用字符数换算精确 token。

旧快照可能缺少 Profile、预算、身份或结构化 User JSON；已有原始文本仍可阅读。所有可读内容和原始请求均从同一 `llm_uses.request_snapshot_json` 得出。审计阶段已有的凭据脱敏保留，查看器不根据 CURRENT、现有模板或最新提示词重新生成请求。

## 4. 只读接口

| 接口 | 返回 | 加载时机 |
| --- | --- | --- |
| `GET /api/v1/guide-runs/{guide_run_id}/model-calls` | 运行身份／状态、program_processed、逐次调用与用量摘要；不返回完整上下文 | 可见请求记录首次加载，之后跟随已有运行 updated_at 刷新 |
| `GET /api/v1/model-calls/{llm_use_id}` | 调用概览、上下文分段、历史身份、原始请求、预检数据 | 打开详情、切换调用或显式重读时；已选调用事实变化时更新 |

沿用现有 READ_OK 响应信封、规范 ID、空请求体和错误映射。不存在返回 NOT_FOUND，读取故障保留已有界面内容。后端使用普通只读事务，没有数据库迁移、业务写入、Provider／Tokenization 请求。

列表查询只投影小字段及保存的输入／正文身份，不向前端传输大型快照。前端 ModelCallReader 对同一运行及状态版本合并并发读取，没有新增定时器；隐藏／退出时取消只读请求并忽略迟到结果，重新打开补读。打开详情还会读取最新调用列表，覆盖取消后迟到用量等历史变化。摘要不会触发详细快照、模型或计数请求。

## 5. 实现位置

- 后端：`backend/app/guide/model_calls.py`、`api.py`、`http_models.py`。
- 前端契约与 API：`frontend/src/api/model-calls.ts`、`walle.ts`。
- 共用读取与界面：`frontend/src/guide/model-call-reader.ts`、`model-call-view.tsx`。
- 对话接入：`conversation-owner.ts`、`conversation.tsx`、`read-view.tsx`、`messages/timeline.tsx`。
- 运行记录接入：`requirements/document-records.tsx`、`detail.tsx`；样式在 `shared/styles.css`。
- 专项：`backend/tests/guide/test_model_calls.py`、`frontend/tests/model-calls.test.mjs`。

## 6. 验证状态

本轮相关离线专项、构建、真实页面只读观察和服务加载结果见 [专项验证记录](../../../verification/v1.0/ai-request-inspection-2026-10-11.md)。该记录保留初次失败与修复，不替代全项目或真实模型验收。
