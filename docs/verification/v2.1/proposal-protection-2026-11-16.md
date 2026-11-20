# V2.1提案保护实施（2026-11-16）

依据pending后端0.1-draft-4的APP-FORM-PROPOSAL／DTO-PROPOSAL／R23。保留原代码及文档改动；不改正式设计、冻结发布包或正常业务库，不调用真实模型／计数、不启停服务或提交推送。

新增proposal_binding.py：程序生成完整PublicationBinding及受保护投影，按真实Goal／Revision／内容版本／步骤定义／来源／相关实体与关系集合重新计算；保存原冻结F，当前性不比较全局D/F、焦点、展示排序及自身提案flags。写卡生命周期独立检查，COMPLETED不被当作失效，CANCELLED拒绝。路线卡还在当前全图重新校验，不凭缓存摘要跳过图约束。损坏绑定不从当前状态伪补。

新增proposal_commands.py及commands.update_proposal：暂缓／恢复写卡和撤回调整的同事务程序动作；恢复／撤回重新检查原绑定；撤回仅存PROPOSAL_CHECK成功凭证和标记变化，checked_versions为变更前真实版本，不更新原binding／payload，也不生成正式回答或GuideRun。真实动作消息、D/F、事件和成功回执沿已有机制。

实际检查：固定SQLite＋quality_python离线保护，独占临时目录自动清理。命令范围backend/tests/formation/test_v21_proposal_binding.py，-q -p no:cacheprovider --tb=short --basetemp <临时>/pytest：6通过，24.72秒。覆盖无关步骤／焦点／F／flags、完成生命周期保持绑定；Goal／定义／新增入边失效；取消许可；原绑定损坏拒绝。测试为保护层专项，不伪造AI发布／GuideRun，不代表端到端新卡发布或三个动作事务已验收。ruff format --no-cache --check backend/app通过（539文件）；git diff --check通过。

待继续：基于实际新卡发布链取得3动作事务／撤回重放及故障证据；当前绑定相关集合采取所属步骤范围，需在发布上下文接入时进一步核对精确相关性和较大集合流式摘要，不能把本批当最终全部语义验收。CARD_RESPONSE、所有内容路径维护／复核、RecommendationBasis、新AI资源及执行、读分页／HTTP／前端仍未完成。
