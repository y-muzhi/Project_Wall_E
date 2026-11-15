# WALL-E V2.0 Coding与Testing拆分静态核对

日期：2026-11-03（Asia/Hong_Kong）。用户已确认Coding与Testing独立分工并要求修改。结果：本轮设计重构与静态核对完成，未实施或执行产品验收。

## 1. 范围与基线

先保存[独立模块迭代](../../iterations/pending/v2.0/WALL-E.Coding与Testing独立模块迭代_V_2.0.md)，再修订[后端](../../design/v2.0/WALL-E.后端设计文档_V_2.0.md)、[前端](../../design/v2.0/WALL-E.前端设计文档_V_2.0.md)、[唯一设计断点](../../project/v2.0/设计进度_V_2.0.md)及两个导航索引，连同本报告共7份Markdown。基线后端0.12-draft-12／前端0.11-draft-11，当前0.13-draft-13／0.12-draft-12，均DRAFT。

按项目统一模板在原对象、能力、入口、依赖和验收位置替换相关契约，前端补独立页面／组件／路由／存储。不新增第三份共同规格，不自动合入正式V1.5或原V2汇总；迭代仍pending。

[历史验收测试专项](../../iterations/pending/v2.0/WALL-E.验收测试代码模块专项设计迭代_V_2.0.md)的计划、Oracle、覆盖、测试自身有效性、防作弊及归因作为复用依据，其“执行仍挂CodeTask”由本轮替代。构建评测／自迭代及最小API案例保留原范围和字节，不自动扩展成本期自迭代功能。

## 2. 完成的契约

| 范围 | 最终行为 | 实现／验证状态 |
| --- | --- | --- |
| Coding | 三角色实现、开发自检、固定候选发布及明确修复；原内部ACCEPTANCE入口移除，发布后AWAITING_TESTING | 设计已同步，代码待实施 |
| 独立Testing | TestingTask可选择Coding候选或共享仓库快照，独立状态／授权／预算／停止；不创建占位Coding任务、不占其活动名额 | 对象／控制／输入输出已定义，未运行 |
| 测试资产 | 独立计划／版本／行为覆盖／用例／预期，编译封存包；正参考、缺陷对照和预定重复均实际验证后才能发布 | 资源、Schema和有效性证据未发布／执行 |
| 模型与执行 | 显式一次结构化计划起草，仅保存DRAFT；测试运行用受控driver，不调用模型判分，不自动发布／修复 | 新Prompt／输出定义完整，运行资源与供应方证据仍待后续 |
| 报告与接收 | 不可变TestReport、独立归因Finding；Coding明确LINK报告，准备／接收复验当前目标／设计／版本／四阶段／真实联通及完整收尾 | 报告适用性与历史结果分开，待真实跨模块验证 |
| 缺陷闭环 | PRODUCT Finding明确导入CodeDefect，事实从原报告复制；再明确REPAIR，新候选必须新Testing复测 | 不复制隐式修复／缺陷系统，未实施 |
| 共享基础 | Operation／Step、Verification／Item／Case、Command／Environment／Guard观察、幂等和模型预留共用，新增排他owner和真实外键 | 200 SQL／校验器／Guard包需按新字段实现，不改冻结151 |
| 浏览器恢复 | 单一CommandRecoveryStore／IDB，PendingAction v3增加owner_module／testing_task_id，原键／原body／事务／终局规则保持；各自终止按完整owner恢复 | 未改实际浏览器存储或源码 |

独立Testing固定原候选，即使Coding并行产生新代码，原测试和报告仍对应原版本。独立快照或部分诊断报告可有实际结论，但不能取得Coding交付权。Testing终止不停止Coding，反向也不级联；相同数字ID不能跨模块读取／停止。报告原result不可因撤销包或新候选改写，当前delivery_eligible必须失效并说明原因。

原五项修复继续保留：缺失字段／存储映射、外部请求ID不透明文本、接收防跳、具名事实澄清完整四键、持久原命令与确定拒绝回执。接收门槛改由Coding发布链和独立Testing报告共同执行；Testing Verification.role／Coding交接引用为null，避免把独立测试伪装成编码会话。

## 3. 静态检查及实际结果

实际检查入口：rg精确检索，PowerShell here-string传入Python的内存正则／字段集合／表格／引用／SHA-256检查，git status --short、git rev-parse HEAD、git diff --check。检查脚本没有作为产品／测试代码保存，也未留JSON报告。

| 核对范围 | 实际结果 | 可证明的边界 |
| --- | --- | --- |
| 对象与字段 | 16对象块、42记录组、522独立字段行，无重复，字段均6列；当前两份规格中已定义记录组的显式成员引用差集为空 | 不代表自然语言隐含字段或真实SQL自动证明；新／旧字段的类型、null、owner和物理载体已逐组人工核对 |
| 模板逐实例 | 19能力均有适用输入／过程／结果／关键执行／定位，计划AI有4.7；10页面／抽屉和10复杂组件条目齐备 | 模板结构不等于业务实现正确 |
| HTTP／客户端 | 114唯一方法＋路径（原67＋Coding发布／报告关联2＋Testing45），请求／结果／错误／实现定位齐备；79条规范化前端路径无未映射 | 未发送任何产品HTTP；计划／授权等组合输入已明确平铺到APP DTO的转换 |
| 稳定引用与格式 | 206稳定定义无悬空引用，7份本轮文档相对链接目标存在，UTF-8／表格列／围栏／行末无问题 | 外部链接未联网逐一验证 |
| 共享owner | 任务级真实task_id／testing_task_id排他字段、Testing空Coding role／profile、三类LLM归属及原终止引用已机械与人工交叉核对 | 真实SQLite FK／CHECK／唯一／并发和Guard身份仍须运行证明 |
| 接收与旧规则清理 | Coding捕获／自检仅HANDOFF，Delivery准备／接收输入test_report_id；缺陷导入与人工输入互斥；旧双归属／Coding内部ACCEPTANCE规则已替换 | 当前114入口均为V2设计契约，尚未实施；不保留Coding内部最终ACCEPTANCE执行兼容路径 |
| 验收目标 | 后端104原场景＋20独立模块场景；前端65原场景＋20独立模块场景，均6列表；4项EV有固定样本／次数／指标及失败计入 | 实际场景执行0；原三EV与独立测试计划AI评测分开，未授权模型调用 |
| 现场与保护 | 43份保护文档及6份所读源码和开始摘要一致；HEAD不变；git diff --check退出0；本轮原子保存临时文件0 | 其他任务既有V1.5源码、资源和工具改动保留，不把它们当本轮修改或回退 |

核对过程中已修正：Coding原读模型仍显示两种检查目的；接收接口和缺陷导入的旧字段要求；共享模型双归属／环境对候选的旧限制；同步操作与外部步骤混用；报告缺少可直接展示的provenance；计划起草停止后迟到输出的保存门槛。修正后重跑受影响静态核对，最终问题集合为空。API、字段和标记的静态检查只能核对文档，不能充当程序状态机或故障运行验证。

复核定位可用：

- rg -n 'SHR-TEST-OWNER|SHR-TEST-ACCEPTANCE|APP-CODE-PUBLISH|APP-TEST-|OBJ-TEST-' docs/design/v2.0
- rg -n 'testing_task_id|test_report_id|TEST20-PLAN-1|BND-TEST-API-' docs/design/v2.0/WALL-E.后端设计文档_V_2.0.md
- rg -n 'BND-TEST-|PendingAction v3|owner_module|/testing' docs/design/v2.0/WALL-E.前端设计文档_V_2.0.md

## 4. 保存与摘要

所有修改均在内存准备完整内容，写同目录临时文件、flush／fsync并关闭，复核原文件未并发改变后os.replace；不清空目标再写，临时文件成功／失败均清理。索引按实时内容追加，未覆盖其他任务条目。

| 基线／当前项 | SHA-256或版本 |
| --- | --- |
| 后端当前 | 0.13-draft-13／DRAFT；fc3be413f34b1692c523f710e58fa3bdc66cfec53373e8ae7d9eea02d6e38c40 |
| 前端当前 | 0.12-draft-12／DRAFT；a74ec97d5d9476010993719320dba499842b751c3bf9bed65749a58fcde03345 |
| Git HEAD | 8c5df4c6683e10c265e2f719a4fdc09ba4210ea0 |

## 5. 未执行与后续

未修改产品源码、Schema、资源包、配置、正常数据或服务；未运行单元／专项／集成、类型／格式／构建、浏览器、SQLite／升级、Windows／OpenCode／Git执行、模型／计数或真实效果评测，未安装、启停、提交或推送。本轮无产品进程或未完成代码／DDL分支。

独立Testing模型资源、计划／包编译器、有效性参考集、受控runner／浏览器包、共享owner版Guard、200 SQL／发布清单／校验器／维护工具及真实跨模块证据仍待实施／发布／验证。现行Case协议只允许已定义受控能力；不支持的动态变量、自由脚本等必须明示未覆盖，不通过删需求／假断言绕过。既有Windows／模型／Git／存储准入不因本轮架构修改自动通过。

本轮设计拆分无未完成改写单元。后续启动代码实施前，建立V2实施计划／进度／需求映射，并按新边界重排批次：共享字段／存储／owner、Coding发布、Testing资产／执行／报告、缺陷复测与接收交付；真实数据／服务／付费调用仍需当轮明确范围。
