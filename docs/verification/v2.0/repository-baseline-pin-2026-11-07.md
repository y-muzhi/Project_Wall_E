# V2.0 C05 保留引用与原基线保存验证

2026-11-07。V2.0 工作区源码，db20-r19。Windows NTFS、锁定 SQLite、MinGit 2.56.0.windows.4、隔离双进程 Guard 管道、临时仓库与数据库。正常仓库、业务数据及服务保持原样。验证范围为内部执行及原操作读取，生产队列与 C05 POST 尚未开放。

## 实际结果

- C05 固定提交及保留引用组 7 项通过。包括 SHA-1／SHA-256 固定提交、缺对象、两种格式创建、已有同名引用和写入后应用结果丢失。成功只增加指定 ref，已有 Git 文件及未提交正文保持原样。冲突保留原引用，结果丢失保留原引用和私有派发记录，原操作为 UNKNOWN，拒绝同一执行者重发。
- C05 原保存组 SHA-1 和 SHA-256 2 项通过。各自走完原四步，重新读取原提交与对象闭包，保存唯一快照及原操作结果。读取只公开最终快照 ID，重放同一输入保留原接收回执。新步骤使用不同的原作用域，六个原进程范围均释放。
- 私有 Git 回执、固定对象批读、引用协议、Guard 契约、原接收与原操作查询回归 239 项通过。原作用域按阶段回执可重新打开，拒绝重复追加。同一临时环境下的旧原始读取组曾有 SHA-256 工作进程回执超时，单项复测通过。
- 首轮保留引用用例发现更新已固定 external_identity 被数据库阻止。实现改为在原作用域的私有日志逐阶段持久追加，数据库只在步骤完成时写原结果。无需改变数据库约束。测试改为按实际 STOP／RELEASE 状态结束等待，避免用固定次数代替实际进程状态。
- 当前测试继续核对实际引用被改变时的发布拒绝，以及重启时选取原步骤。跨控制方 C05 正向未知结果收敛仍待独立验证。

## 命令和隔离

使用工作区 .venv/Scripts/python.exe -B -X utf8 tools/python-v20.py tools/quality_python.py。由 tools.quality_gate.environment 注入隔离环境，临时根为工作区 .tmp 下自动清理的临时目录，指定 -p no:cacheprovider、--tb=short 和本轮 --basetemp。原生组运行 backend/tests/infrastructure/test_v20_guard_control_git_transport.py，按 c05_fixed_batch 及 BASELINE_SAVE 筛选。回归另运行 backend/tests/code_tasks 的 test_repository_baseline_acceptance、test_repository_operations、test_git_ref_protocol、test_git_receipts、test_git_object_batch，以及 backend/tests/infrastructure 的 test_v20_git_receipt_store、test_v20_guard_control_git_version。旧 Git SHA-256 超时单项复测使用 test_v20_git_metadata_command.py 的 raw_commit_tree_blob_and_tag_conversion and sha256。

浏览器、正式 Windows 服务安装、真实模型及计数 API 未纳入本轮。
