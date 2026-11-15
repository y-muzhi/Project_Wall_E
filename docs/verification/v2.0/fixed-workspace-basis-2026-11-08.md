# V2.0 固定 Git 工作区与原设计依据验证

2026-11-08（Asia/Hong_Kong）。代码位于当前 V2.0 工作区，沿 db20-r28、SQLite 3.54.1、固定 MinGit 2.56.0.windows.4 及本机 NTFS。测试使用隔离数据库、专用私有目录、实际本机管道及自有 Windows Job。真实保护后端程序准入沿已有测试端口，未安装正式 Guard 或执行器。

## 固定起点与失败边界

- 原登记快照、保留引用、完整对象批、树摘要及文件清单共同约束新私有工作区。复制已确认的文件原字节，保留原 Git 模式元数据。空文件、BOM、CRLF、NUL、非 UTF-8 二进制和嵌套路径按字节核对。
- 独占暂存及文件创建；发布前后核对工作区、子目录和文件的原卷及文件 ID。路径、字节、完整树或来源证据不匹配均失败。Windows 同父无覆盖重命名处理临时出现的目标，保留原阶段和目标供核对。
- 目标位于源仓库范围时，在创建暂存和登记 Git 查询前拒绝。未提交源工作区、用户索引及 Git 其余元数据保持原事实。原登记／只读查询的业务行不因物化改变。
- 最初用 Git 配置读取器回读工作区时二进制 NUL 被配置语法拒绝。改为抽出共用原生锁与字节读取，由原配置子类保留配置字节规则。另同步旧队列测试为当前返回的具体运行器，并扩展实际 Git 向量按三文件计算独立的预期树及内容摘要。

## 依据和已执行检查

- 同一数据库快照取得同任务／同需求的确认版本。主设计在前，材料按文档 ID 升序，保留已确认空材料及完整 UTF-8，包括所存 BOM 和换行。后续修改只改变当前差异，原材料仍为已确认版本。错误归属使整组失败。API34 与设计版本列表只返回原公开元数据。
- 最终离线定向 72 通过，80.65 秒。经 tools/python-v20.py 与 tools/quality_python.py，在临时 basetemp 执行 test_workspace_materialization.py、test_git_fixed_content.py、test_content_manifest_git_vectors.py、test_repository_snapshot_reads.py、test_repository_registration_actor.py、test_v20_windows_config_source.py、test_v20_windows_private_record.py、test_task_basis.py、test_design_revisions.py、test_task_stop.py。
- 实际固定起点、HTTP 创建／详情及未派发停止组合 1 通过，182.15 秒。物化早期组合 3 通过，217.27 秒；加入重叠防护时两种恢复因私有目标误入原仓库指纹失败，普通只读通过。将目标边界改为基于受信目录句柄的独立核对，保持原仓库身份。最终 test_v20_guard_control_git_transport.py -k BASELINE_QUERY_RESTORE 两种实际格式 2 通过，137.75 秒，各自验证重叠拒绝且未分配、随后合法发布及源仓库保持原状态。
- 修正后的 test_v20_git_repository_location.py、test_workspace_materialization.py、test_repository_registration_actor.py 专项 47 通过，15.54 秒，包含与前一组重复的测试文件，不合计为独立总数。
- Ruff 受影响的 11 个应用文件检查通过，后端 263 文件格式通过。git diff --check 通过，报告既有前端测试文件的 CRLF 转换提示。清理工具 dry-run 显示 0 JSON／截图。
- 当前是内部固定起点和原文读取。尚未接 API35、原任务工作区分配记录、崩溃后原分配核对、执行器只读依据入口、模型会话、已派发停止、Testing 和交付。未运行用户服务／业务数据库、真实模型或计数。前端源码无改动。
