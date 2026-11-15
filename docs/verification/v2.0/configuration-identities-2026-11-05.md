# 配置身份创建／列表及原请求结果绑定（2026-11-05）

代码状态：V1.5基线28a7c9e之后未提交V2实现；BE0.17-draft-17、FE0.16-draft-16，正式设计未改。完整补读APP-CODE-SETUP、API09—12、SHR-CODE-PAGE及前端BND-CODE-SETTINGS。本单元不实施完整设置页面、配置版本、授权或执行准备。

## 实现及边界

- 新增code_tasks/configuration_identities.py／configuration_api.py，实际service接四条路由：POST／GET code-execution-profiles、POST／GET code-check-sets。创建仅保存id／name／created_at，返回201及resource_kind／resource_id；不建版本、授权、Task、Operation、工作区或模型调用，不生成可执行资格。
- EntityKind增加ExecutionProfile／CheckSet，复用原sequences及entity_id；分配、身份写入和原幂等SUCCEEDED同事务。显示名称不是相等身份，不新增名称唯一限制。同键同输入取原结果，改输入冲突，关闭先于指纹；不自动清claim或换键。
- GET同一只读快照统计／分页，每页20、page1—100000，保留真实越界页；按created_at DESC,id DESC。latest_version_id取本身份最高版本，检查配置只取CODING，不用TESTING版本或最新可执行版本替换原值；无版本为null。
- 原结果字段及201状态集中在command_registry.validate_registered_success，两条实际命令由原账本接受／回放／回执及HTTP投影复用；损坏额外字段、错resource_kind、错状态或错成功编码拒绝，原记录不修补／重执行、不泄漏私有值。其他46条原命令的完整输入／结果绑定仍随实际业务实施。
- 前端code-configuration-identities.ts为这两条真实入口注册输入／结果及冻结恢复policy；WalleApi接创建、列表和现有CommandRecovery工厂，继续同一个ApiClient。分页扩展现有公共page helper的错误policy，不另建传输／分页流程。Name核对与后端Unicode White_Space一致，不用trim误判BOM／U+0085。
- CommandRecovery显式字段代替构造器参数属性，使既有Node原生TS strip入口可加载；不关闭strict／未使用检查，不改变IDB流程。浏览器专项已将实际两条DTO接入真实IDB owner：DISPATCHING提交后才允许HTTP，201保存终局并移除pending正文。HTTP为明确替身，后端另用真实ASGI／SQLite，不宣称浏览器到后端端到端。

## 实际检查

- 最终固定SQLite＋quality_python，获准普通非提升环境，七文件 **64通过、5子场景，170.53秒**：
  test_configuration_identities.py（32项）、test_identifiers.py、test_v20_command_http.py、test_v20_command_receipts.py、test_v20_startup.py、test_v20_published_schema.py、test_v20_schema_release.py。
  覆盖正常创建／同名不同身份／原键／原CLOSED／计数回滚／真实提交后回执丢失503及原结果恢复、151拒绝、空页／越界／模块版本隔离／只读GET、不完整结果与损坏回执、真实两连接竞争、默认200及实际发布维护。
- 前端新增7专项；**全套485通过，6.285秒**；strict类型、Prettier格式通过，临时生产构建**1.04秒**。保留既有约2.59MB主块提示，没有改构建告警阈值。
- 实际Chrome：存储8组＋owner5组＋bounds2组 **15组及两个真实标签竞争通过**；包括新增两种实际配置DTO。出现V20_IDB_BROWSER_PASSED、OWNED_BROWSER_CLOSED、OWNED_JOB_EMPTY_AND_BROWSER_OUTPUT_CLEANED；新profile／服务／Job／临时输出均清理。
- 173个生产Python文件Ruff格式、两个新增配置模块及登记模块Ruff check、git diff --check通过。仅Markdown证据，未留测试JSON／原始日志／截图；无本轮临时目录或活动进程残留。

## 发布与修复记录

先发db20-r5（8c32ced1a63137356ecb7180161c4e10e0caf5f5dffec1713b5a4b36a384b0dd），原结果安全校验追加后另发**db20-r6**，当前manifest SHA256 **bb2cdb68a084c0030c99f7eccdcc9e2357699beecf58c0701b981723d1106672**。最终64项使用r6，load_release已另核对；r1—r5不覆盖。发布是仓库资源准备，未升级正常用户库或更新服务。

初轮新增27项中26通过，丢失提交回执本来按StorageUnavailable返回503，测试错误预期500已校正，单项及最终组合均通过。前端首次加载因参数属性语法不受Node strip支持，已改显式字段后通过。损坏夹具最初直接UPDATE成功终局，被原IMMUTABLE_SUCCESS保护拒绝；改用全新隔离初始坏行，未关闭／删除任何产品保护，验证三种读取／回放／关闭均500且不泄漏、不重执行。先前各失败不记成全组合通过。

未执行正常库操作、系统安装／ACL／网络变更、用户服务启停、V2提交／推送或真实模型／计数。仍待完整配置／资源目录、Guard认证／受保护运行包／LPAC-WFP、Coding／Testing业务及逐页前端和全版验收。
