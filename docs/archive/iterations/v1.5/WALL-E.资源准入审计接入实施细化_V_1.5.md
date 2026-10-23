# V1.5资源准入审计接入实施细化

2026-10-23，已按职责合入后端AI-RESOURCE第7部分及V1.5运行说明。此记录替代编写过程中的未接入草稿状态，不表示真实供应方准入完成。

复用LLMUse、CountingJournal及不可变请求／计数／响应。程序配置保存原审计引用和已核实Admission，冻结v9／v10字节不变；每个真实IO边界核实，准备审计保存同一凭证。异常usage从正常LLMUse持久推导SUSPENDED，不能同release重新批准消除异常。缺失或损坏原凭证拒绝。

隔离入口内部能力绑定实际SQLite连接、run、profile、release与独立工作区，普通HTTP／Worker不能安装。默认CLI仅临时新库离线预览；execute显式预算与新目录原子槽，IO前消耗额度、失败不返还、不重试，保留正常审计。成功且技术证据合格仅给隔离库记录准入，其他库导入独立执行；真实调用仍需当前人工授权。

实现位置：infrastructure/collaboration_admission.py、collaboration_observation.py，guide/collaboration_execution.py、orchestrator.py，AuditRepository及tools/admit-v15-resource.py、observe-v15-once.py。未新增业务根、Schema150表、公共接口或provider SDK。

实际离线专项：准入／接受／计数／用量22项，准入／执行15项，隔离观测7项通过。完整联合结果及中断边界见verification/v1.5/admission-observation-2026-10-23.md；真实观测未执行，无实际LIVE凭证发布。模型语义效果、浏览器及普通生产使用分别报告，不混为验收完成。
