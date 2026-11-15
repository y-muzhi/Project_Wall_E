# V2.0显式升级内核与审计恢复资产

日期：2026-11-04，HEAD 28a7c9e。正常库／服务／真实模型及计数均未操作。仅隔离151副本与本轮私有临时包；V2源码未提交。

依据：BE7.1.3—7.1.6及已有pending数据库保留升级迭代。实际维护命令与发布pin尚未完成，本记录不授权正常库操作。

实现：
- schema_v20_upgrade.py：MaintenanceSession先检查未resolve的原源路径与原生身份、私有包、原lock文件，再取得真实ProcessLock；显式维护窗口确认必需。原数据库文件不替换。rebuild_locked只在维护连接事务外关闭FK并读回，再BEGIN IMMEDIATE内重验冻结151、完整typed源清单、全部DDL／逐原列复制、追加200与同upgrade_id／源摘要marker；同事务核验最终对象、旧值、全部新业务表为空、完整性／FK；单次commit，恢复FK后新连接只读重开核验。
- 同upgrade_id已提交仅读原标记，不再DDL；提交回执未知不自动重试。recover_locked只查原路径／发布／身份与真实持久事实，151不变是NOT_APPLIED；原200 marker匹配可认历史提交，正常新数据引起旧投影变化单独标CURRENT_DATA_CHANGED；未知对象／其他upgrade_id为UNKNOWN或拒绝，不删除／修复／降级。
- schema_v20_assets.py：只从CountingJournal实际根记录ABSENT／EMPTY／FILES；逐真实文件、ID、长度和SHA保存字节副本，原JSON空白／null／0及空文件不重写，准入记录一并复制。拒绝链接／嵌套目录、不递归复制任意外部目录；既有备份不覆盖。源变化／部分写入失败不写合格证明，保留源和私有部分资产。
- 磁盘检查来自同源SQLite读快照page_count/page_size和原生[GetDiskFreeSpaceExW](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-getdiskfreespaceexw)的调用用户可用配额；连接必须绑定实际源。估算源重建／WAL、两个库副本／演练增长、审计临时空间、DDL及每侧64MiB安全余量，同卷合并预算。空间不足直接拒绝，不清理原数据。
- 发布候选源码绑定增加升级内核、审计资产及Windows路径／权限源；实际schema_v20_admission编译pin仍不存在。

最新检查：固定SQLite＋tools/quality_python.py，maintenance_assets／upgrade_engine／windows_private_package／windows_local_paths／schema_release五文件，32通过、22子场景（64.14秒）。真实NTFS／私有DACL／SQLite非空副本，外网／正常数据／本地凭据保护开启。源路径junction在resolve前拒绝；窗口确认缺失不打开路径；第二维护会话无OS锁不能进入；后续真实文档写入不抹历史marker；复制失败保留部分资产且校验拒绝；错误连接不能借用磁盘快照。各次32、此前20／6等不是相加的一次全量验收。

范围限制：仍须计划封存、外部注册证据／配置引用核对、已验证原库备份及封存演练回执、plan／rehearse／apply／recover／check CLI组合与真实发布pin；程序入口在此完成前不用于正常维护。当前引擎只在已知隔离副本专项调用，维护窗口确认标记不替代当前任务的正常库授权。未取得LPAC／Guard／OpenCode／Git、供应方、前端或整版验收证据。无测试JSON报告／截图／原始日志保留。
