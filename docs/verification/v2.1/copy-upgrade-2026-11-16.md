# V2.1源只读复制升级检查

日期：2026-11-16；独立工作区codex/v2.1-design-review／HEAD a0f40592702cb702ed928849ac540479c22c224f及实际未提交源码。仅隔离离线，未读写正常业务库、未更新用户服务、未调用真实模型／计数，未提交推送。

## 实现与不变量

入口tools/db-v21.py copy／inspect及formation_upgrade_source／formation_upgrade／formation_upgrade_cli，复用原MaintenanceSession、LocalPathGuard、PrivatePackageGuard、ProcessLock、typed retention、SQLite backup、审计及注册引用检查。copy要求源／目标manifest及明确维护窗口、源只读、全新目标父目录；已有目标、未知manifest、源真实DDL不符或活动／PROCESSING／未知执行状态拒绝。原r48及当前r54资源／DDL逐字节相同且固定manifest白名单；不把版本整数当依据，不执行旧源码。

SQLite backup保留完整原72表及索引／触发器、全部类型／原字节、JSON、时间、ID／高水位与原回执。新增22表仅Schema marker有记录，21个业务表空。计数审计按原名字节复制到目标实际.count-audit根；注册admission引用保持原路径并核验，不改证据或凭据。210扩展与marker在同一短事务。仅Markdown意图／结果／失败／inspect记录，原业务审计JSON保留业务字节，测试结束全部随临时目录清理。

inspect只读核实已有目标：已提交且与原升级ID／源摘要匹配才VERIFIED_TARGET；原200副本为COPIED_SOURCE_NOT_UPGRADED，不重放DDL、不修补、不覆盖。结果仅离线目标核验，不切服务，不承诺使用新库后的双向回退。

## 实际结果

- 固定Python入口tools/quality_python.py backend/tests/formation/test_v21_copy_upgrade.py：13 passed，103.32秒。源由真实旧create_requirement／create_document／C01及离线Gateway执行形成1个真实Run／LLMUse、正式消息、原幂等回执和计数审计；另含旧code_repositories记录。r48／r54两种已知manifest复制、全部原表类型摘要、源物理字节不变、原审计字节相同、旧回执实际重放及inspect通过。
- 拒绝未知源／目标manifest、无维护窗口、已有目标、已有父目录、真实源额外表、当前OS执行锁、PROCESSING及实际活动AI，均未取消原工作。
- 故障覆盖复制后未执行DDL；完整DDL＋marker已写但提交前异常整体回滚；提交完成后最终Markdown回执丢失，仅inspect恢复确认；错误升级ID拒绝。源保持物理字节不变，失败目标保留可检查。
- 另单独检查当前编译pin的真实CLI copy／inspect及Schema回归：10 passed，26.97秒。其中CLI实际子进程使用tools/db-v21.py及已发布r6，未用测试替身替代正式发布入口。
- 初版资源检查误将collaboration_v1走旧Function.restore，并错误使用无v前缀版本；原私有记录发布器只允许固定JSON文件角色，也不能直接发表Markdown。现按原执行依据精确恢复release／digest及原元数据；Markdown复用原native不替换发布原语，写前核ACL、fsync并读回核字节。上述失败均在临时库定位并修复，未回避校验。
- 现有StarletteDeprecationWarning一条；没有新增失败。尚未做整版大数据／外部文件损坏矩阵及正常业务现场升级，不外推其他未固定源或真实供应方效果。

## 当前发布与使用边界

core/db20-r54 manifest：3d48be65e3ad6e549c3b73b831456459537adb1e03c765ef6f28ad9ce6eeedc7。

target/db21-r7 manifest：b9b9da55266f067b1b4ac0b3d4eae01ce027e4b7f2953cbaf29c35aa4000d554；完整DDL合同仍f3f29931a176cbb64effa63fad516280120711a472f4e59a246a9683df9e0b78，94表；新增维护四个入口纳入9个来源固定项。旧r5／r6原字节保留。

维护操作仍需用户当轮授权。本轮仅构建工具并在隔离临时数据演练；未对正常库运行。帮助入口：.venv/Scripts/python.exe -B tools/db-v21.py --help。服务默认Schema200仍不变；另获授权才能选择新目标并更新服务。


追加：当前r6下test_v21_startup.py三个实际进程／factory专项通过，30.41秒；正常默认Schema200边界保持。无用户进程启停。


扩展检查formation包及全部formation_*基础文件时另发现4条导入排序，已通过stdin格式化后原子保存，再生成新不可变r7。DDL合同及core/r54未变；扩展Ruff现0提示。r7实际CLI复制／inspect单项再核对1 passed，14.07秒。旧r6下13项＋10项证据保留原状态，不冒充r7全部重跑；本次仅 import 顺序调整，依变化范围补正式入口核验。
