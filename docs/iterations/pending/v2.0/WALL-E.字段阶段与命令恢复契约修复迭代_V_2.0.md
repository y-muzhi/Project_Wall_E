# WALL-E V2.0 字段、阶段与命令恢复契约修复迭代

日期：2026-11-03（Asia/Hong_Kong）。用户要求：修复[五类契约问题](../../../verification/v2.0/design-contract-review-2026-11-03.md)全部项目。状态：设计修订及静态核对完成，两份详细规格仍DRAFT／待实现验证；仅Markdown和静态核对，保留pending，不合入正式V1.5或原V2汇总。

## 1. 来源及授权

基线为后端0.11-draft-11、前端0.10-draft-10及统一模板。共同规则仍只在[后端](../../../design/v2.0/WALL-E.后端设计文档_V_2.0.md)，页面／组件／本地恢复在[前端](../../../design/v2.0/WALL-E.前端设计文档_V_2.0.md)。本迭代记录修订来源，不建立第三份共同规格。

用户此次明确要求修复全部五项，因此事实澄清与持久命令恢复均采用补能力，不继续保留原限制。仍不授权源码／Schema／资源／真实配置／数据／服务实施、产品测试／真实模型／计数、安装／提交／推送。现场有并行V1.5源码及资源工作，保留其改动，不沿用旧源码组摘要。

## 2. RC20-01／02：字段及外部ID

逐行补齐Delivery.planned_commit_oid、Delivery.failure_code、ExecutionRecord.source_id、ManagedInstance.stopped_at、ExecutionSession.last_observed_at、CommandExecution.ended_at、CodeRepair.failure_code，明确实际观察、同任务引用、原计划不可变及null时机。同时恢复CodeWorkspace.ready_at的就绪时刻定义；本轮全篇显式成员引用扫描另发现LLMUse.id只有身份说明无字段行，补为原llm_uses主键。两项均不冒充上轮已确认的七项。连同两个交接操作外键，本轮补11行。

新增字段在7.1明确列／类型／可空／恢复用途，所有字段来源均有独立定义，不能用其他行约束提到名字代替。对中文紧邻英文标识的组内约束使用ASCII边界扫描，核对正文—字段表—存储映射；非记录字段的原生协议／派生投影按唯一完整结构归属。

provider_request_id改为不透明文本，可null，新代码调用非null时1—1024个Unicode码点，原值不trim／转数字／当重试身份；缺失或空值不构造有效ID，原始响应事实仍按审计保存。超长不是截断为合法值。旧文档调用的原值和旧<=1024约束保留，可能历史空串不隐式清洗；不改冻结151 SQL／checksum。CodeCallDetail及前端解码采用该文本定义。

## 3. RC20-03：阶段门槛与固定检查范围

统一SHR-CODE-VERIFY-STAGE，由APP-CODE-CONTROL负责，从同任务原已成功HANDOFF_ROLE操作／步骤、源／目标真实会话及顺序推导角色链。未知、失败、仅退役或模型自报不算完成；同角色修复会话不新增已完成角色。无需第二个角色完成账本。

| 当前有效角色及角色链 | HANDOFF固定范围 | ACCEPTANCE |
| --- | --- | --- |
| BACKEND；无前序交接 | BACKEND | 拒绝 |
| FRONTEND；后端→前端已成功 | BACKEND／FRONTEND | 拒绝 |
| INTEGRATION；两次顺序交接均成功 | BACKEND／FRONTEND／INTEGRATION | 固定四阶段，另含ACCEPTANCE |
| 角色／代次／链不完整或未知 | 不派发新捕获／检查 | 拒绝 |

Verification增加backend_handoff_operation_id、frontend_handoff_operation_id两个可null真实外键，准备后不可改；BACKEND均null、FRONTEND只首项必有、INTEGRATION两项必有。它们只是原交接证据引用，不新增业务根。ACCEPTANCE要求Verification.role=INTEGRATION且scope_stages恰为四阶段；必检不齐未就绪，不以空集合通过。

创建捕获／重查操作前、固定Verification、计算eligible、进入AWAITING_ACCEPTANCE、准备Plan及Accept事务均核对同一门槛。提前调用返回409 VERIFICATION_STAGE_NOT_READY，未接受新操作时不物化／捕获／执行；已发生历史事实不删除。HANDOFF通过不直接进入待接收；最终联调HANDOFF通过也须完整ACCEPTANCE才可接收。前端从TaskView.verification_purposes逐动作取enabled目的，不能写死两个选项或把选择器当后端保证。

## 4. RC20-04：具名事实澄清

每题答案统一为{index,action,basis_refs,clarification}。原两类action保留且clarification=null；新增CLARIFY_FACTS，clarification={kind,text,option_indices,evidence_refs}，kind为OBSERVATION／REPRODUCTION／EXISTING_BEHAVIOR。text为1—2000码点非空说明，按同一换行及计数口径处理；不自动截断。option_indices引用原题真实选项，无重复，多选性按原题；EXISTING_BEHAVIOR还必须提供非空真实basis_refs，其他两类允许空。证据均同任务，可空数组。不能传自由原生answers或控制身份。

后端校验结构／原题／原文／证据归属，保存不可变原答复及实际native string[][]；事实标为用户报告，不能声称已由程序验证内容真实或不含新规则。发送文本固定标明仅定位原设计内的事实，不改变Revision／授权／预算／目标；冲突／新增规则仍走已有文档移交。没有隐藏语义分类／审阅调用。事实答复不写设计、不自动扩权／换版／接收或恢复其他等待。

前端逐题提供事实种类、文本、既有选项及证据输入，输入法／计数／未知恢复均按原owner；无需为这一步另设额外审批复选框。所有题有效后一次提交，旧实例／代次仍不可答。

## 5. RC20-05：持久待核对命令

### 5.1 载体、结构与发送顺序

采用独立IndexedDB命名空间walle-v2-code-command-recovery（版本1），复用现有IndexedDB事务／blocked／quota／关闭机制，新增异步CommandRecoveryStore职责；不是把同步StoragePort或绑定Milkdown／文档草稿的DraftRecoveryStore直接套给命令。原V1.5文档恢复库／格式不改，也不存完整代码或模型内容。

PendingAction升级schema_version=2，仅其版本改变；一般草稿／偏好仍schema_version=1。pending_commands主键[origin,key]，唯一intent_key为同origin的已登记method＋规范path，防止同一未决入口在新标签页换键重做。所有任务创建前／设置资源动作也纳入；不是只按task_id恢复。终局摘要存command_receipts，无原body。

ApiClient现有PreparedCommand使用WeakMap，ApiAction只暴露submit，不能直接序列化。目标是在同一ApiClient／WalleApi边界增加受控导出／恢复原冻结字节及原key的内部能力，不新建任意fetch，也不把数据库内容当指令；路由白名单、精确decoder、原作用域、请求摘要及同origin校验后才能还原句柄，恢复绝不重新生成UUID。

生成并冻结原method／path／key／body_json → 原子写PendingAction并等事务oncomplete → 原子标DISPATCHING／计次 → 才发送。put.onsuccess不是提交证明，不能靠离页事件补写。普通写命令存储失败／blocked／quota／原JSON体>8MiB／未决容量满时阻止发送并保留表单，不退回内存后继续普通变更。单body上限与HTTP8MiB一致，另留64KiB元数据；最多100份未决记录、总128MiB，不淘汰未知命令腾空间。

### 5.2 多标签页、恢复与终局

恢复入口复用代码设置及原任务操作区，在创建前也可见“待核对操作”。全origin列出已登记未决命令的非秘密方法／目标／时间／状态摘要，不把body或旧一次性确认带入新表单。重开／新标签只查原回执；通知可用BroadcastChannel，但正确性由IDB事务、唯一intent_key和后端幂等共同保证，不依赖通知、localStorage锁或超时判断旧发送者已停止。

同一原命令只保留一份冻结输入；已有未决入口时新标签关联原记录，不能先生成新键再声明不同草稿。发送计次与owner标记在IDB事务中CAS；租期／页面消失不证明未发送，也不自动接管重发。用户明确恢复才可能同键重放，原key／body字节不变，后端幂等最终保证外部意图不重复；旧标签迟到结果只能补同命令事实，不能覆盖已确认终局。

NOT_FOUND不作为未发送或可删除证据。FOUND真实同步成功／明确拒绝为命令终局；202保存原operation_id并继续观察，必须该操作真实SUCCEEDED／FAILED／CANCELLED才结束未决，UNKNOWN不清理，不等整份CodeTask最终完成。解析不明／缺原身份保持待核对，404消失不作终局。用户“放弃草稿”不删除未决命令；终局后一个IDB事务移入无body墓碑并删除pending，墓碑最多30天且仅本地摘要，可在容量满时删除已终局摘要，不能删未决项。

source_quiescent_confirmed／repository_quiescent_confirmed属于一次性窗口。恢复旧true只查询原结果；带这类确认的旧请求标QUERY_ONLY，不提供无新窗口依据的原请求重放，更不能复制为新意图。普通GET及恢复不授予模型／Git执行权。存储被用户清理／不同origin／不同浏览器仍不能承诺恢复，但默认关闭标签页不再主动丢弃原凭据。

### 5.3 终止例外

不能因恢复存储故障使终止消失。唯一TERMINATE可在IDB不可用时由用户明确点击并确认真实task_id后走原终止入口，保留内存原键；其他普通写仍阻止。后端先查该任务唯一已保存TERMINATE意图，再处理新版本：STOPPING返回原停止操作，终态返回原事实，不换键重复停止；新增真实停止仍需版本／可信用户停止权核对，不依赖执行授权EFFECTIVE、模型／预算／隔离资源就绪。

复用原OperationRecord，增加每任务TERMINATE部分唯一约束及TaskView.termination_operation_id派生引用；跨标签页可只按task_id查询原停止事实。这是可重复停止语义的窄例外，不是通用内存降级／扩权或自动重放。数据丢失不自动声明任务已终止。


### 5.4 确定拒绝回执与原键一致性

源码静态核对发现既有idempotency_records只持久成功，CommandReceiptLookup却已承诺可返回原错误。V2代码命令要安全清理本地已拒绝请求，必须在既有幂等记录上补REJECTED和error_result_json，不新建并行回执账本。只有按已登记输入完成校验、业务未写入或已可靠回滚、原claim仍有效的确定4xx拒绝才能持久终局；存储／提交／外部结果未知不能写成REJECTED。原键重复先返原SUCCEEDED／REJECTED结果，包含跨标签页仍在途的迟到同键请求；503／500不因一次响应自动当永久终局。

200结构显式迁移这项增量：旧PROCESSING／SUCCEEDED行及全部旧列原值保持，error_result_json为null；SUCCEEDED／REJECTED终局不可更新。文档侧旧输入／调用行为不借机改写；代码命令作用域仍映射原capability＋target＋key。待核对记录只有FOUND可靠终局才清理；明确从未派发的PREPARED可由用户取消，但必须在同一IDB事务核对dispatch_count=0、移入CANCELLED_UNSENT墓碑，旧owner再发送必须重新过持久门槛并被拒绝。超时／页面关闭不构成从未派发证据。

## 6. 同步范围与状态

修订已同步后端0.12-draft-12、前端0.11-draft-11，均DRAFT。按模板同步对象／能力／输入输出／错误／HTTP／读取模型／物理映射／Prompt及前端页面／组件／存储／验收。67个公开HTTP不增加；CommandReceiptLookup仍只读，不新增任意命令查询／后台队列。

附录A逐项登记RC20-01—05“设计修复／待实现验证”，真实运行包、隔离／检查资源、200 SQL及供应方证据缺口保持。历史审阅／模板报告保留原字节，不追溯改成通过。

## 7. 静态检查与完成标准

执行字段约束集合—独立字段行—存储映射的差集；核对provider文本／旧历史保留、角色—目的—状态矩阵和多层门槛、答案分支完整字段／原生串映射、持久记录发送前提交／多页／终局／失败／停止例外。补后端及前端目标场景，不执行产品／浏览器／真实调用。

最终实际结果见[修复静态记录](../../../verification/v2.0/design-contract-fixes-2026-11-03.md)，当前断点见[设计进度](../../../project/v2.0/设计进度_V_2.0.md)。不以静态脚本代替真实SQLite、浏览器IndexedDB、多标签页／崩溃、原生SSE或Windows／Git证据。

本单元已完成：394独立字段／33记录组、12项明确物理绑定、67HTTP及37前端路径、136稳定定义、104＋65项目标场景结构和关键规则静态核对通过。实际产品／浏览器／SQL／原生／真实调用验证均0；剩余为实施与运行准入，不冒充已验收。
