# V2.0 START 执行条件与系统配置来源验证

2026-11-08（Asia/Hong_Kong）。Windows／NTFS、固定 SQLite 3.54.1、MinGit 2.56.0.windows.4。沿现行 db20-r29。验证使用隔离数据库、临时工作区、本机管道及自有 Windows Job。

- RESTORE_WORKSPACE 追加原私有文件清单，保存工作区目录、原清单文件身份和固定内容摘要。CHECK_CONDITIONS 复用真实 NTFS 树读取，核对路径、类型、ACL、原目录身份及每个固定文件字节，完整重验同一原依据封存。读取遵守固定配置的文件数、单文件和累计字节及内容核对期限。改变或缺失内容及旧工作区缺少清单时阻断；保留原工作区，不从源仓库重写。
- 原操作、工作区、控制代次、配置、授权和预算在写回前再次核对。内容与环境分别报告，区分 CONTENT_NOT_READY 和 CONFIG_NOT_READY。原启动键仍回放 202，公开读只返回已核对的布尔事实及准入缺项。停止抢占时保留原步骤，不采用迟到检查。当前缺完整受信执行器和隔离入口，未登记实例、会话或模型调用。
- 系统配置检查使用 Windows Known Folder 获取 ProgramData，并通过 NTFS 目录句柄只读检查 opencode 项。存在同名项或无法核对时保留 Q20-CONFIG；系统及本轮以外文件无改动。 [Microsoft Known Folders](https://learn.microsoft.com/windows/win32/shell/known-folders) [SHGetKnownFolderPath](https://learn.microsoft.com/en-gb/windows/win32/api/shlobj_core/nf-shlobj_core-shgetknownfolderpath)
- 初轮后端 26 通过，211.65 秒；实际 Guard／MinGit 的 test_fixed_baseline_http_reads_and_creates_one_task_in_private_guard_scopes[start] 1 通过，234.93 秒。实际 API35 → Git 工作区 → 固定依据 → 执行条件，证明内容通过时仍保留真实环境阻断。加入系统目录探测后扩大到七个后端文件共 46 项通过，212.32 秒；相同实际 Guard／MinGit 联调 1 通过，203.34 秒。增加期限与容量后，test_task_start_conditions.py 与 test_v20_opencode_managed_config.py 定向 13 通过，89.35 秒，含原期限和文件超限；损坏配置限额专项另 1 通过，1.62 秒。最终实际 Guard／MinGit 组合 1 通过，206.83 秒。受影响文件 Ruff、271 文件格式及 git diff --check 通过。隔离临时目录、浏览器专项目录和待清理报告／截图均为 0。
- 前端严格类型、格式、564 项测试和隔离生产构建通过。实际 Chrome 1280／360 检查内容缺失、执行环境阻断、刷新及停止可达，采用 HTTP 夹具；窗口及自有 Job 已退出。
- 当前缺正式执行器包及真实 LPAC／WFP、受控只读依据权限、真实原生配置／会话、首条消息和已分配资源的停止回收。未启动正式执行器、更新用户服务或调用真实模型。
