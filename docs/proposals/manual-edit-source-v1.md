# MANUAL_EDIT 持久来源补充 v1（待用户确认）

来源：后端 SHR-BLOCK L316–321 要求非 TEMPLATE 的来源 ID 按来源对象关系验证，但没有定义 MANUAL_EDIT 引用的对象。APP-DOC-CMD-C03 L1433 规定提交后删除 MANUAL_DRAFT；现有 manual_draft_context 也引用该草稿，随编辑流程清理。D-004 批准的稿 B 没有明确这个来源 ID 的持久归属。不能把删除后的草稿假装仍可引用，也不能只检查整数就通过来源关系。

阻塞：P4 草稿保存/完成以及 CURRENT、Revision 中人工区块来源的数据库验证。P3 纯算法、前端基础、其他来源能力可继续。

推荐增加内部 `manual_edit_sessions` 来源登记表，具体 DDL 见同目录 `manual-edit-source-v1.sql`。不是公开 HTTP 对象；不新增公开字段、接口或实体分配序列。会话身份使用这次独立 MANUAL_DRAFT 已分配的 `RequirementDocument.id`，`MANUAL_EDIT.source_id` 等于该 `draft_id`。它表示那次人工编辑操作，不能转而指向 CURRENT id 或提交审计 id。

开始编辑在创建草稿/上下文/占用的同一事务创建 EDITING 会话，保存时 USER/MANUAL_EDIT 使用这个 ID，服务器验证会话属于相同需求和 CURRENT。完成或取消在删除草稿/上下文及清占用的同一事务关闭会话为 COMPLETED 或 CANCELLED；失败全回滚仍 EDITING，未知提交依现有版本/幂等规则恢复。重复幂等动作不新建会话。

关闭会话保留最小关系元数据，不保存正文、用户输入或 BlockState，永久保留以证明在线正文/历史快照来源；会话不级联删除，不恢复关闭状态、不重复改时间。`draft_id` 不设指向临时草稿的外键，需求和正式 CURRENT 设外键，应用事务必须复查两者真实关系。初始化/升级先备份；已有数据若包含 MANUAL_EDIT 来源而没有可证明的会话，拒绝迁移，不根据 ID 或时间猜历史。当前尚无生产库/业务数据，测试数据库隔离。

来源署名补充：TEMPLATE 为 SYSTEM/null；GUIDE_RUN 为 AI/同需求 INITIALIZE Run；SUGGESTION_BATCH 为 AI（ACCEPTED）或 USER（EDITED）/同需求批次；MANUAL_EDIT 为 USER/同需求会话。来源引用合法不代替运行状态、取消、版本、占用、模板和范围检查，这些仍由对应 APP 提交事务独立保证。历史会话即使关闭，来源仍合法；引用不存在、跨需求或署名组合不合法时 DOCUMENT_INVALID。关闭/取消会话不能给新的采用动作授权。

提交审计仍使用已批准 document_change_audits，source_type=MANUAL_EDIT、source_id=会话 draft_id；开始或仅保存草稿不伪造 CURRENT 提交审计。既有 MANUAL_DRAFT 删除与 CURRENT 身份/版本规则保持。

待确认范围：此 ID 归属、最小来源登记长期保留、来源署名组合及新增迁移。确认前不加入生产迁移或应用能力，也不把对应业务标为完成。确认后补真实 DB 测试：删除草稿后来源仍可验证、跨需求/缺失/伪造拒绝、完成/取消与会话原子关闭、失败/未知结果不重复关闭、历史创建来源保持。
