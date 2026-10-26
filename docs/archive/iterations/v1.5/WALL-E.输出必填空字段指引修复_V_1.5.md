# WALL-E V1.5 输出必填空字段指引修复

2026-10-24。依据正式BE AI-OUTPUT、AI-RESOURCE及原九字段根契约，增量修复模型可见指令，不放宽程序校验。

真实依据：已授权v13条件批次在阶段1确认必要全文预计158716超131072，阶段2实际1计数／1Chat技术LIVE、parse成功，但validation FAILED。DISCUSSION只返回六个根字段，省略document_result／suggestions／analysis三个必须显式null的字段。原Progress／ModelCardGroup及进度纯计算有效，离线诊断副本补null后完整Schema有效；原返回、原失败不改写，不采用副本，不运行修复重试。整批2计数／1Chat、总Chat10049后结束，26EV未执行，旧上限不能用于新版。

最终规则：正式共同Prompt第四段明确九根字段名称、全部必填、不适用结果必须JSON null、DISCUSSION仍保留三个空结果字段。Schema、C07、引用、授权、事务、显示及取消保护保持；不自动补字段或把缺失当作可信null。追加resources/v14（Prompt v5／release v6，其余Schema／指引／结构／计数同字节），仍OFFLINE_READY，不继承v13凭证或付费许可。

实施／离线专项已完成：工具追加不可覆盖的v14生成入口，默认资源固定新manifest。完整设计源及四种缺字段C07路径定向5 passed／33.26秒；相关13文件129 passed／11子场景／579.03秒，覆盖新资源源一致性／闭包、原始返回可读／不补字段／不应用／占用释放、完整根正常执行、上下文／计数／恢复／准入及固定26样本后处理。完整命令与实际结果见verification/v1.5/output-null-roots-v14-offline-2026-10-24.md。BE SHA256 8c818b009879ce902b9ef2e2692028013437cc47a801d32b5ac7e484c38e80f0；manifest0353339a…／release ac9c887f…，旧资源不改。无用户库／服务／Git写操作；真实新版兼容和26效果仍需新的明确许可，不把离线通过称真实通过。
