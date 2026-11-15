# 仓库登记内部 runner 验证（2026-11-07）

代码在 repository_git_runner.RepositoryRegistrationRun。原操作接收后启动 VALIDATE，使用原随机 scope、普通后端源位置、单独配置导出、后端私有 MAY／ACK、实际 Guard 管道、固定 MinGit、原标准 I/O 和完整 STOP／空 Job 观察／RELEASE。共享 parse_original_config_output 绑定实际输出及原配置，释放证据持久后核对 RepositoryMetadataLease，才原子发布完整仓库。

实际双进程＋临时 SQLite 专项通过（8.17 秒）。原 202 重放仍为 PENDING，操作实际 SUCCEEDED，仓库存在，无占位 Task。开始联调时测试进程初始化次序触发原数据库执行锁保护；已改为先初始化测试库，再持有其原执行锁，未改锁规则。

原 CREATE 回执丢失专项验证后端原操作及 VALIDATE 进入 UNKNOWN，保留本地原源和 I/O owner；close 拒绝误报清理。Guard 原 Git 根仍处于挂起，未恢复、未释放，最后由测试持有的原 owner 停止并回收。真实未知后的重新鉴权连接及完整恢复清理仍需接续。OBSERVE 现在分开返回原动作输入摘要、已持久 ACK、当前进程及原 Job 观察；后端仅按同摘要补存原 ACK，端口专项覆盖错摘要拒绝及不重复 CREATE。

运行 `tools/python-v20.py tools/quality_python.py`，隔离 SQLite、NTFS、管道和自有 Job。首个 4 文件内部集成 37 项通过（60.45 秒）。接生产 runner 后扩大 7 文件 70 项通过（116.73 秒），再补原回执丢失与 UNKNOWN 保留后最终 **71 项通过**（126.81 秒）。只有既有 Starlette 依赖弃用提示。236 个 app 文件 Ruff 格式、受影响模块 lint 和 Git 差异检查通过，产物清理无残留。

实际程序包准入仍用隔离测试端口。没有启动或更新用户服务。当前内部 runner 已可由宿主调用；生产 Guard 宿主／后端线程归属与在途恢复、C01／C02 HTTP、前端页面及实际 SYSTEM／LPAC-WFP 仍待完成。

## 同后端重连清理

RepositoryRegistrationRun.reconcile_cleanup 要求同一存活后端、原 PREPARE ACK 与原 scope。已有 MAY 先 OBSERVE 同动作，不重发；随后原 STOP、当前空 Job 与退出核对、RELEASE。业务 UNKNOWN 保持，不恢复原进程、不发布仓库。缺原 ACK 或 owner 保持未知。

实际丢 CREATE 回执后，关闭双方原端点，重新建立同安装、同真实后端的受控管道，完成原挂起进程停止及资源释放。本地保留列表清空，业务仍 UNKNOWN。初次测试的 6 秒整段时限与实际 MinGit 创建竞争，客户端先关闭触发真实 peer 拒绝；改用原 CREATE 已记录后的明确故障信号，保留正常 30 秒上限。重连专项 1 项通过（7.31 秒），最终 7 文件 **71 项通过**（124.79 秒）。236 格式、受影响 lint、diff 和产物检查通过。
