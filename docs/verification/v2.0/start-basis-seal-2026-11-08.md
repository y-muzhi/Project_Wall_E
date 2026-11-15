# V2.0 PREPARE_BASIS 固定原文与原封存验证

2026-11-08（Asia/Hong_Kong）。Windows／NTFS、固定 SQLite 3.54.1／MinGit 2.56.0.windows.4。沿现行 db20-r29，未修改 Schema 资源或正式设计。

- 既有受信后台线程在原 RESTORE_WORKSPACE 验证后处理第二步。读取任务原主设计和有序材料的完整 UTF-8，先以短事务保存原操作、代次、工作区、来源摘要与确定名称，再在私有根按原句柄无覆盖发布。空材料为真实零字节文件。原封存绑定每个原文件 ID、字节数及 SHA256，保存结果前重新验证全套及停止屏障。
- 后端读取按原 ProcessLock、任务及代次核对单个原文，使用只读句柄并重验原文件身份和字节。停止或错误文件拒绝。私有正文、路径、原引用和摘要不进入浏览器；API17 只给安全文件数量。已确定缺失的原文在原步骤保存 CONTENT_NOT_READY，经 START 动作原因引用原失败操作，已失败操作不列在 active_operations。
- 有受信工作区根时，重启对第二步 RUNNING 仅查看原封存。完整且仍具有原资格时确认原完成事实，缺文件或身份不明时保持 UNKNOWN，不覆盖已有文件。停止优先，晚到的部分原文不能进入执行。重启专项模拟原所有者退出并实际重开应用及 ProcessLock。
- 首轮 test_task_start_basis.py、test_task_basis.py、test_v20_windows_private_record.py、test_task_start.py 共 23 项通过，72.87 秒。使用 tools/python-v20.py、tools/quality_python.py 和自动清理 basetemp。加入停止抢占及原文缺失场景并扩大到 STOP／原队列后，六文件 35 项通过，168.40 秒；随后按 active_operations 的正式契约修正明确失败的投影，最终六文件 35 项通过，132.65 秒。
- 实际 Guard 管道与 MinGit 组合 test_v20_guard_control_git_transport.py::test_fixed_baseline_http_reads_and_creates_one_task_in_private_guard_scopes[start]，1 通过，218.39 秒。真实 API35 → 原固定 Git → 私有工作区 → 后台封存原设计及空材料 → API17／34 和后端只读入口。主设计后续有新版仍读取原确认全文。测试使用显式隔离程序准入和配置就绪端口。
- 前端最终 564 项、严格类型、格式及临时生产构建通过。Chrome 宽屏／窄屏实际页面用 HTTP 夹具验证依据未知、明确缺失、刷新和原停止仍可用，浏览器和自有 Job 已退出。后端受影响文件 Ruff、269 文件格式及 git diff --check 通过。
- 尚无 LPAC 执行器只读目录授权、实际实例／会话、CHECK_CONDITIONS、首次消息、已分配资源的停止回收及真实供应方验证。未配置工作区根的后端不会访问或继续原私有准备；需受信根重新可用才进行其原封存核对。用户服务、数据、系统安装和真实模型未操作。
