# V1.5 v13条件批次技术观测

2026-10-24T15:35:01.257798+08:00。用户已授权完整条件批次，阶段1精确预计158716超131072，0Chat，条件成立。

新独占data/v15-observation-20261024-v13-final-once，最多1计数／1Chat、输入131072／输出8192／总139264，零重试，不换版本。release=eeb7925e52dbecb521ad19a448ba7ae24be4aac63ff8d5b4a0a384ba534c4a68；profile=61941797052baa3c4a6cc1df54759b91d7fa933d2a4b98ec19d8b3b116cfc70e。

工具SHA256=5c5a5dadc34bda4b8b89a45ef1fc0f671db89982d64d17130d1928a13ddd251f；固定业务源码及输入见v13-final-batch-authorization-2026-10-24.md。凭证由CLI安全读取.env.local，值不记录。执行即占用槽；未知先读正常库，不重发。技术准入和首轮结构均通过才允许后续26EV；本报告尚未填结果。

实际执行已结束（CLI退出0只说明技术准入，不代表业务结构合格）：1计数／1Chat，LLMUse=1；call／parse=SUCCEEDED、validation=FAILED；finish_reason=stop。实际输入=8177、输出=1872、总量=10049、缓存=0，framing gap=3，耗时毫秒=12973。

同release正常审计重读技术状态LIVE_VERIFIED；输出根仅6字段，缺失必须显式null的analysis, document_result, suggestions，所以首轮结构门未通过。正常run COMPLETED、根IDLE、文档数0、正文=NOT_REQUESTED、进度=NOT_REQUESTED。原始返回可读／保留，未建立候选，不回写validation。

离线纯诊断副本仅补齐三个null后，完整OutputDiscuss Schema通过；原Progress／ModelCardGroup单独Schema及apply_progress纯计算通过。副本未保存、未采用、不被当成新真实结果。

阶段3的26EV未执行；整批按条件结束，剩余次数不得续用到修复版或新槽。
