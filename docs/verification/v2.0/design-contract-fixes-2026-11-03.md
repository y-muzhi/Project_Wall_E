# WALL-E V2.0 五项契约修复静态核对

日期：2026-11-03（Asia/Hong_Kong）。任务：按用户“修复以上所有问题”修订五类设计契约。结果：本轮设计修复及静态核对完成；两份详细规格仍DRAFT，未实施或取得产品验收证据。

## 1. 范围与来源

先保存[独立修复迭代](../../iterations/pending/v2.0/WALL-E.字段阶段与命令恢复契约修复迭代_V_2.0.md)，再按项目统一模板职责修订[后端](../../design/v2.0/WALL-E.后端设计文档_V_2.0.md)和[前端](../../design/v2.0/WALL-E.前端设计文档_V_2.0.md)，同步本报告、设计进度及两个索引，共7份Markdown。迭代留pending，不合并正式V1.5或原V2汇总。

基线为后端0.11-draft-11／前端0.10-draft-10；[上轮复核](design-contract-review-2026-11-03.md)和[模板校正记录](template-conformance-2026-11-03.md)保留原时点结果，未回写成通过。八项技术设计选择及用户已确认边界保持。

## 2. 五项处理结果

| 项目 | 最终设计与落点 | 状态 |
| --- | --- | --- |
| RC20-01 字段遗漏 | 第3章补独立类型、可空与约束，7.1补物理绑定；恢复依赖原事实、原OID，不以别行约束替代定义 | 设计修复；SQL／代码待实施验证 |
| RC20-02 供应方请求ID | LLMUse及CodeCallDetail为不透明可空文本；新代码非null时1—1024码点，不trim／转数值／截断；历史文档原值／旧约束保留，前端不按整数解码 | 设计修复；真实响应／decoder待验证 |
| RC20-03 接收跳阶段 | SHR-CODE-VERIFY-STAGE要求真实顺序交接及INTEGRATION当前候选；ACCEPTANCE范围固定四阶段，多个接收入口复验；前端只展示后端对应动作enabled目的 | 设计修复；控制链／交付集成待验证 |
| RC20-04 普通事实澄清 | 三分支QuestionResponse，新增FactClarification；完整原题组、2000码点／原选项／原证据校验，固定原生string[][]，用户报告不等于程序验证，不改设计／授权或自动恢复其他等待 | 设计修复；协议／输入法／浏览器待验证 |
| RC20-05 命令身份丢失 | 独立IndexedDB保存原key／完整body，发送前等事务提交；跨页唯一intent／CAS，先查原回执，终局原子清理，NOT_FOUND不作未发送证明；一次性确认只查询，终止有窄例外 | 设计修复；持久库／句柄恢复／多页故障待实施验证 |

本轮新增11条独立字段行：用户六项、上轮同类确认的CodeRepair.failure_code、恢复CodeWorkspace.ready_at、本轮显式成员扫描发现的LLMUse.id、两个Verification交接操作外键。LLMUse.id沿既有主键，不新建调用身份。第3章共394字段／33记录组，非额外新增11个业务对象。

为支持安全清理确定拒绝，静态阅读发现既有idempotency_records只有成功回执，而原读取契约已承诺原错误。修订200设计，在同一表增加error_result_json及V2代码REJECTED终局；确定回滚／原claim有效才提交，500／503和提交未知不能伪造终局。迟到同键保持原成功／拒绝，终局不自动过期，旧151列值／历史保留。未生成或执行SQL，不改冻结151。

TERMINATE在本地存储失效时仍由用户明确触发；后端原键优先、每任务唯一停止意图，TaskView.termination_operation_id可按任务恢复。新增停止校验可信用户停止权／版本，不依赖模型、执行授权EFFECTIVE或预算就绪；其他写命令不得借此退回内存。

## 3. 实际检查与命令

本轮只执行本地文档和源码静态读取，以及通过PowerShell here-string送入Python的内存核对脚本；未留测试JSON或临时脚本。实际入口为rg精确检索、Python正则／表格／集合／SHA-256校验、git status --short、git rev-parse HEAD、git diff --check。可复核定位：

- rg -n 'planned_commit_oid|failure_code|source_id|stopped_at|last_observed_at|ended_at|LLMUse.id|provider_request_id' docs/design/v2.0
- rg -n 'SHR-CODE-VERIFY-STAGE|verification_purposes|VERIFICATION_STAGE_NOT_READY|CLARIFY_FACTS|FactClarification' docs/design/v2.0
- rg -n 'PendingAction v2|walle-v2-code-command-recovery|transaction.oncomplete|QUERY_ONLY|REJECTED|termination_operation_id|RC20-' docs/design/v2.0

| 静态范围 | 实际结果 | 解释边界 |
| --- | --- | --- |
| 显式成员引用—独立字段行 | 两份当前规格中属于33记录组的英文成员引用差集为空；同组可空字段集合差集为空，394行无重复且均6列 | ASCII边界可识别紧邻中文的字段；不是自然语言全部隐含字段的自动证明 |
| 物理绑定 | 11个补齐字段及provider_request_id共12项均有独立物理映射；类型／null／原OID不可变／同任务引用已逐项核对 | 泛化映射仍需转换真实Schema，并验证FK／CHECK／触发器／升级 |
| 模板逐实例 | 11对象、12能力、67唯一HTTP、6内部入口、5页面、8复杂组件，适用条目表头完整；前八章职责保持 | 模板符合性不证明运行正确 |
| 引用与读取 | 136稳定定义无悬空引用，37前端路径全部映射；两份当前版本互引一致；7份相对链接目标存在，代码围栏／表格／UTF-8／行末核对通过 | 未联网验证外部链接；当前引用为草稿 |
| 关键契约 | 56处关键规则标记核对通过，并人工核对阶段表及所有入口、三答案分支、原生文本、持久事务／多页／清理／停止例外；旧1MiB限制及统一浏览器schema1表述已清除 | 标记存在只是静态证据，不代替状态机、事务或协议执行 |
| 验收目标 | 后端104、前端65项且均为6列表；新增12＋10项覆盖本轮；原3项EV及固定样本保持 | 实际执行0项，不预授予真实评测／付费请求 |
| 保护与现场 | 7份保护文档、6份本轮只读源码与开始摘要一致；HEAD未变；git diff --check退出0，本轮原子保存临时文件0 | 不用本轮摘要覆盖其他任务既有V1.5代码／资源改动；不沿用旧全仓摘要 |

核对中发现并修正：LLMUse.id同类遗漏；旧存储场景仍使用1MiB／内存降级；数据库200与浏览器schema版本混用；新增场景误写两个不存在的稳定引用；前端客户端绑定行残留三键答案，已补为含clarification的完整四键。修正后重新运行相同受影响静态核对，最终问题集合为空。原子保存全部先准备完整内容、同目录临时文件flush／fsync并关闭、复核原文件未被改写后os.replace；失败未覆盖目标。

## 4. 当前版本和摘要

| 文档 | 当前版本／SHA-256 |
| --- | --- |
| 后端 | 0.12-draft-12／DRAFT；cdce48d6739c9f6fb39eed68bdc2b839e11ba6bda7b9df4bfa666f1f0c901ab3 |
| 前端 | 0.11-draft-11／DRAFT；db3f502f03b15836968d438390916b673048c0be50e2d6837b2a94e0eaa116a5 |
| Git HEAD | 8c5df4c6683e10c265e2f719a4fdc09ba4210ea0 |

## 5. 未执行与接续

未运行产品单元／集成、类型／格式／构建、浏览器IndexedDB／多标签／关闭重开、SQLite／迁移、OpenCode、Windows／Git、真实模型或计数；未读取正常业务数据库／浏览器存储，未安装、改配置、启停服务或提交推送。没有本轮产品进程或代码／DDL半成品。只读核对ApiClient／WalleApi冻结命令、文档恢复库事务、idempotency、151 SQL及审计路径，当前源码不包含本轮设计能力。

五项设计缺口已有结论，不再等待产品选项确认；外部运行包、Guard、资源／价格、casepack、200 SQL／维护工具及实际协议证据仍按附录A取得。IndexedDB只保证当前同origin浏览器正常持久机制的关闭后恢复，不保证用户清除、异源／异浏览器或真实掉电；QUERY_ONLY原结果长期不明仍须核对，不以换键消除未知。若启动代码实施，先建立V2实施计划／进度／需求映射，并明确当轮运行验证和真实调用边界。唯一当前断点见[设计进度](../../project/v2.0/设计进度_V_2.0.md)。
