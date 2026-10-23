# 真实取消事务失败及未知恢复（2026-10-08）

范围：FE OP29/5.5，BE C03/I17/SHR-IDEMPOTENCY；补读FE1249–1266、1290–1308、2075–2079，BE5173–5210、6185–6204、6857–6866；原实际命令/SQL事务/前端API客户端、运行动作和控件核对。保留原公共协议和批准资源，不修改生产业务代码。

最终固定两根 cancel-failure-browser-2026-10-08T03-34-53-496Z-1796a172bdbf.json、外部命令 cancel-failure-command-2026-10-08T03-34-53.435546+00-00.json 全部通过；关闭后独立 immutable SQLite 审计 cancel-failure-post-audit-2026-10-08T03-37-09.403930+00-00.json 通过。2需求/2完整CURRENT3/2Baseline/4Run/2真实LLMUse/2本机Chat/0批次/0付费；452输入before/after稳定，451共同输入仅私有helper变化，450生产输入不变。独立库前后SHA相同。

明确 controlled-cancellation-model 仅隔离新库/本机TCP/合成凭据。真实I14/worker/ORCH已发请求、真实TCP头后body有限60秒等待。分别安装SQLite AFTER UPDATE触发器：guide_runs进入CANCELLED时ABORT；idempotency_records写成功回执时ABORT。两支页面实际I17返回原生503/STORAGE_UNAVAILABLE；观察器不替换响应，响应生成后比较九表完整业务事实hash并移除故障触发器。第一支运行写入回滚，第二支已执行运行/占用/审计写入也随成功幂等回执失败完整回滚。未产生假取消或半提交；当前运行/CURRENT/Baseline和消息保持。

503和500的公开错误不能区分已提交后失败；既有客户端因此保守留UNKNOWN，并保存原动作、原键/空body，取消和人工编辑入口不可写，不能把本次内部诊断回滚当成公开失败证明。用户明确核实第一次实际CURRENT读取200后丢浏览器传输回执，页面保UNKNOWN、0取消重放。第二次明确核实先读实际需求/文档/运行/消息，再原键空body真实I17成功200，唯一CANCELLED原记录，生产lease退休、Task取消、真实TCP EOF。没有新Run或第二次模型请求；最后不同键重复取消保结束时间和业务事实。独立审计核对唯一正式用户消息、原始Manifest/输入/未知用量null、成功幂等记录和服务器关联；故障触发器已不存在，所有worker/transport/server关闭、私有钩子恢复。

I17现有ASGI四项真实数据库接口回归本批重跑通过（2.421秒）：包括PERSISTING409不变、真实SQL503回滚、安全投影与提交后500原键恢复；见 cancel-failure-http-regression-2026-10-08T03-33-33.419789+00-00.json。现有前端运行动作10项重跑通过（243.4284ms），PERSISTING门禁、同动作去重、隐藏/恢复、明确409保状态与未知读取等，见 cancel-failure-frontend-regression-2026-10-08T03-35-28.105561+00-00.json。这些对象回归不是实际根页PERSISTING可见截图证明；C07提交事务先胜的实际竞争另见commit-race-notes.md。历史263＋4/814/55未冒称本批全量重跑。

失败全部保留：03-29报告工具错误预期503是明确拒绝，真实产品正确进入UNKNOWN；03-32工具错误等待在GUIDE_ACTIVE下不存在的人工编辑按钮。两次正常关闭后修正测试期望与已观察页面门禁，不改变产品行为。失败矩阵与外部命令、两张失败原图及四张最终原图/SHA均保存在cancel-failure-media/manifest.json；最终未知/成功截图实际查看。第一次编辑脚本断言因缩进锚点不符失败，只写私有helper，未执行业务调用或更改正式资源。

373原行/六列保持44已验证/310未开始/19实现中。OP29已发送/迟到/未知存储及读取失败恢复接续，不以这批两根宣称全部PERSISTING可见/公共负向和所有场景完成；其余初始化卡片、REVIEW/COMMENT来源等待及重试、建议各补丁根和正式Provider/人工验收继续。正常8000仍停、正常用户库未参与，本批未重试被拒正常启动；GitHub两次网络失败保留，本地完整提交后另核对远端。不处理Windows崩溃、不新增付费、不宣布全项目完成。
