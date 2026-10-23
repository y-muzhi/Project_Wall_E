# WALL-E V1.5 讨论命令实施细化

2026-10-22，实施APP-REQ-CMD-C06时明确原设计未展开的传输判别／投影与阶段历史位置。已合入正式后端设计对应能力及I04；不增加共同规格、业务实体、HTTP方法或模型调用。

四种命令以type判别，严格互斥；同步回执为requirement_id／discussion_version／discussion。Discussion资源的document_kind使用小写profile值，由实际文档派生；SECTION规范引用heading_block_id，复用原scope算法时转换输入名称。DECLINE_DRAFT映射冻结Disposition的REJECT_DRAFT。旧阶段closure留PHASE_CHANGED审计，当前新phase.closure为空，旧主题及依据保留；无变化不新增消息／版本／事件。明确用户命令使旧last_step失效，后续建议由下一次用户工作产生。

来源核实、用户动作消息、讨论索引与审计同事务，权限不依赖提示词；变更不写文档、不改业务状态。前端按需展开讨论，保存绑定与阅读选择独立，UNKNOWN沿原请求核实。来源定位交互及完整AI增量合并仍留对应实施单元，不能把本次程序命令完成当作AI链路完成。

验证见docs/verification/v1.5/discussion-commands-2026-10-22.md；仅离线SQLite／进程内HTTP及前端专项／编译／构建，无真实调用或用户服务变更。
