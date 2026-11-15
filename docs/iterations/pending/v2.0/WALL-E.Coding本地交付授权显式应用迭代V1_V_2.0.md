# Coding本地交付授权显式应用 V1

2026-11-12 香港18:41半小时任务内接续。BE 0.17-draft-17／FE 0.16-draft-16及当前断点摘要不变，仍DRAFT；独立pending先于源码，不自动合入正式设计。

## 输入、输出及不变量

APP-CODE-CONDITIONS、OBJ-CODE-POLICY及7.7.3—7.7.4。allow_local_delivery由后端C64的_deliver_authorization及require_live_delivery在真实写入前重新核对，不属于原生或OS规则。沿原C39在原模型窗口CLOSED及旧活动／费用核清后，只调整原成功START固定交付配置内、当前明确批准的本地交付许可；固定delivery作者／提交者／模板、目标、provider／运行包、目录／命令／网络及原生permission不变。

从共享原START授权读取原授权ID及delivery版本，编译固定身份摘要和新的布尔许可；原接收步骤冻结、采用前与历史核对。原启动scope为false不构成永久禁用：交付由后端C64直接管控，新授权已经明确批准且固定delivery配置一致时可开启。原配置未声明交付、或作者／模板漂移则拒绝，不借新授权改变原固定交付身份。编译不授予Git窗口、不自动接收报告、恢复Plan或执行交付；原采用继续清除当前报告／Plan资格，旧Acceptance、Plan及实际记录保留。

复用原四步骤、TaskConfigurationApplication及授权对象，无新Schema／API，不新增交付流程。当前模型授权编译分支保持；通用原生权限仍待规则／系统同组证据。

## 验证

真实隔离SQLite／HTTP撤销、恢复、新明确批准开启、未知、STOP及固定交付配置漂移拒绝，实际C64授权函数核对；关联原C39／模型／交付入口回归。仅离线夹具，不写用户Git分支，不启停用户服务，不SYSTEM／WFP、不真实模型／计数、不提交推送。源码原子保存，临时资源清理，只留Markdown证据。


## 当前实施状态

本批限定路径已实现，并通过最终6场景统一、原C64事务及C39扩大回归、实际CLI HTTP授权审阅。scope原false经新明确批准可开启；与模型许可同时变更仍为一次原组合采用，零自动模型／交付。STOP仅接受请求时保留待控制收尾状态，未假称已完成Guard停止。缺失交付对象先领域拒绝，不落入只接收对象的序列化。实际命令、失败及修正见[验证](../../../verification/v2.0/coding-delivery-authorization-2026-11-12.md)。仍pending，不自动合入设计；通用原生／OS权限及真实产品交付证据另列。
