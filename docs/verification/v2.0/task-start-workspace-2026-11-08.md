# V2.0 START 原接收与首次工作区验证

2026-11-08（Asia/Hong_Kong），Windows／NTFS、固定 SQLite 3.54.1／MinGit 2.56.0.windows.4。代码在工作区，Schema db20-r29，manifest e92252027580506a364cb6cfe375d3314e1edd8324d9f08662d820e49df26737，三个物理资源沿 r28 字节，重新固定 HTTP 入口和回执规则。使用隔离 SQLite、原本机管道、自有 Job 和私有目录。

- API35 接收当前版本、原键及实际执行配置／授权／预算和受信工作区队列。原 202、任务版本和六步同事务，重复原键保持 202；其他键在当前版本下返回关联中的原操作。默认缺运行配置以 503 返回，原键未被消费。原停止意图和已终止限制先于新分配。
- SQLite 在原任务和代次下预留工作区、原 nonce、原父目录身份与预计回执。原暂存 FileID 及原 Git 查询 ID 以私有无覆盖回执保存后才继续读取及发布。实际发布后再核对原代次写 READY；停止与发布竞争保留原记录及 UNKNOWN，未提交任务就绪或启动执行。重启只把经过原回执校验的中断原分配转 UNKNOWN，保留原工作区与原键。
- API17 只投影原步骤、安全工作区 ID 和原任务关联。API34 返回工作区准备、已核验或待核对的持久事实，状态保持 PENDING 或原 STOPPING。前端支持刷新准备进度，任务停止仍可达。当前正式部署的执行准入尚未满足。
- 隔离测试 tools/python-v20.py → tools/quality_python.py 运行 test_task_start.py、test_task_stop.py、test_v20_command_http.py、test_repository_registration_actor.py、test_task_basis.py，22 通过，133.08 秒。包括并发双键、503 原键、SQLite 恢复、NTFS 暂存回执、迟到发布与停止竞争。另跑 test_task_start.py、test_v20_startup.py、test_v20_schema_publish.py、test_workspace_materialization.py，17 通过，53.29 秒。补齐未分配 START 停止后，定向重跑 START／STOP／原回执／登记队列四文件 21 通过，109.75 秒。
- test_v20_guard_control_git_transport.py::test_fixed_baseline_http_reads_and_creates_one_task_in_private_guard_scopes[start] 真实本机管道／MinGit 组合 1 通过，207.53 秒。通过 API35 提交，生产工作线程从原队列领取并实际恢复固定提交。原查询释放回执、文件字节、不可变 202 与任务详情核对。随后在物化回调复用原资源所有者，私有回执关闭失败时保留待关闭原句柄。相同真实联调最终 1 通过，192.97 秒。仓库未提交内容保持原样。保护程序准入与配置就绪使用显式隔离测试端口，未使用正式执行器、模型或供应商。
- 前端隔离 typecheck、格式、564 项测试及生产构建通过。首次类型检查发现可选动作未收窄，改为显式检查存在后复验通过。实际 Chrome 1280／360 在 HTTP 夹具中检查准备中、未知、工作区核验、手动刷新与停止仍可用，并回归取消和丢回执。隔离浏览器 Job 正常退出和清理。后端 267 文件格式、受影响应用文件 Ruff 与 git diff --check 通过。
- 若 START 已接收但仍未分配，原停止在复核六步未派发和真实空范围后取消该 START，完整停止并释放活动名额，原 START 202 可继续回放。已分配工作区走未知保留。
- 未覆盖执行器只读依据及会话、首次原生消息、已分配工作区的停止回收与重启核对、独立 Testing、交付及正式部署。页面本轮读取 START 进度，开始按钮的原请求提交和恢复交互待接。未操作用户服务、业务库、系统 Guard 安装或真实调用。
