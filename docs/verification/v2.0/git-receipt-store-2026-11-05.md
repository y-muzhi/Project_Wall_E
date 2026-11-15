# V2.0严格Git私有回执与原句柄追加验证

日期：2026-11-05。BE0.17-draft-17／DRAFT 7.7.4／.7及原7.3资源归属；28a7c9e后未提交V2源码。没有正常仓库写入、正常数据／配置修改、用户服务更新、系统安装或真实供应方调用。

## 输入、输出及不变量

git_receipts.py严格编解码既定GitReceipt：schema_version=1、原operation／step／guard_run_ref／nonce、GIT20-LOCAL-1、仓库／指纹、原planned OID可null、阶段／UTC毫秒时间和六项允许facts。关联由原GitReceiptBinding提供；对象格式只从该原上下文校验，不从回执猜测或新增wire字段。所有声明字段必须出现，未观测项保留null；整数／布尔不相互转换，OID按原sha1／sha256全长非零校验，分支及基线引用复用现有语法。观察到的unsupported symref可以保存为私有事实，不能据此放行引用事务。

只接受确定UTF8 JSON原字节；重复键、未知／缺失字段、非有限数、格式修补／额外JSON、越限及原身份不符均拒绝。facts无stdout、stderr、config、任意result或句柄字段。阶段及exit0不证明真实ACK或交付成功，编解码不能授予执行权限；实际生产调用方仍须绑定原进程、decoder及原操作。

windows_private_record.py复用既有Win32读取／写入API、私有包DACL与BOOLEAN删除结构，新增按原CREATE_NEW句柄的追加发布。完整写入／短写循环、原句柄读回／SHA与flush后，以FileRenameInfo=3、完整绝对目标和ReplaceIfExists=false重命名同一对象，再flush及原FileID／字节／DACL核对。无路径rename／copy／覆盖回退；未发布清理只对原创建句柄设置删除标记。发布可能发生后不删任何路径，也不再次rename；关闭失败保留同一owner。结构偏移8／16／20在实际x64环境核对。依据[微软FILE_RENAME_INFO文档](https://learn.microsoft.com/en-us/windows/win32/api/winbase/ns-winbase-file_rename_info)；此实现未声称真实掉电验证。

git_receipt_store.py使用原LaunchJournal的scope互斥及同一私有包，只保存证据，不prepare／dispatch任何nonce。先严格encode及原binding检查，限额内新增文件，发布／关闭确认后以原文件身份／字节数／SHA重新锁定读取并decode才返回私有引用。未知append保存原writer；新append被阻止，reconcile_pending只读同一个filename／SHA／FileID，不新建文件、重发rename或执行Git。最终文件不存在不改称未发送；未决stage保留，不自动删除。读取构造／关闭失败时，原LockedConfigSource子owner由store传递保存，父清理可以重试，不丢掉原句柄。

runtime_control_git.py已将原NativeReceipt的路径MoveFileEx／临时路径unlink流程移除，复用同一PrivateRecordAppend。GitReceipt与NativeReceipt仍是不同事实：前者为Git业务证据，后者为原OS资源事实。原Entry保留pending_record与原比较facts；后续仅核对同一个原文件。恢复该私有回执不补填丢失的原创建ACK，不触发第二个根进程，不改变原LaunchJournal的MAY状态。没有新增第二套调度／派发账本。

## 实际检查与修复

环境：Python3.13.5／固定SQLite3.54.1／Ruff0.17.3，实际NTFS及普通非提升非AppContainer操作者。所有新DACL只施于本轮临时私有目录，使用tools.quality_gate.environment＋tools/python-v20.py＋tools/quality_python.py隔离外网、数据及凭据；pytest禁用缓存、专属--basetemp并在finally清理根。

- GitReceipt纯专项99＋原worktree／引用137：236通过，0.31秒。
- 原句柄发布初版组合111通过／2失败，1.35秒：测试在持有含DELETE访问权的原writer期间用CRT路径重开读取，分享模式不兼容。改用同一个原句柄读回，路径读取留到关闭后；未放宽产品共享锁。修后发布＋codec113通过，1.25秒。
- 新store／发布／codec三文件123通过，1.89秒。覆盖原文件身份、同字节替换拒绝、绑定／秘密字段、容量、发布后flush未知、未发生最终rename但不推断未发、仅同文件恢复及读关闭失败子owner保存。
- 复用到原Native生产入口后，六文件151通过，54.93秒：test_v20_git_receipt_store.py、test_v20_windows_private_record.py、test_git_receipts.py、test_v20_runtime_control_git.py、test_v20_git_config_command.py、test_v20_runtime_guard_crash.py。包含实际普通AsUser配置解析与独立测试宿主被终止／最后Job句柄回收。此为原生测试宿主，不是已安装Guard服务或Task隔离验收。
- 补充“创建成功但Native回执发布后flush未知”的原回执恢复分支，最终四文件136通过，33.02秒：原runtime_control_git及store／发布／codec。确认原挂起根保留、原文件恢复、不重复publish／CreateProcess、原创建状态仍MAY_HAVE_BEEN_SENT且再次create拒绝。
- 后端187文件格式、四个本批模块lint、git diff --check通过；db20-r7实际load_release仍为88dcb99509f6184f5289bffc403f6043130a43f9ada9fdb3f962c16604781860。既有httpx弃用提示保留，未更改依赖。

这些结果是重叠的分批检查，不相加冒充一次全量。所有本轮根／Git孩子／独立peer已退出且Job为空，临时JSON、原始输出、stage、测试journal及库由各专属根清理；正常业务和正式资源未清理。

## 未覆盖与下一步

GitReceipt编解码／存储已实现验证，但实际Git业务生产方尚未接完整OperationStep／原Git ACK与计划事实，不能构造任意facts冒充真实调用。Native复用已接真实原入口；私有原文件读取的成功也不等于业务成功或外部调用授权。

仍待完整仓库／config／.lock／对象历史准入、完整固定Git命令、有界并发STDIO／超时消费、原DeliveryWindow／停止／MAY短栅栏及后核对、原业务HTTP和恢复。回执引用／未决状态的业务持久关联仍须原CodeOperationStep承担；本store不是重启调度器。没有真实掉电、完整Guard认证／受保护包／LPAC-WFP、正常库升级或整个V2产品验收。
