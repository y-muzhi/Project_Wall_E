# V2.0 原 LPAC profile、挂起令牌与文件访问

2026-11-09（Asia/Hong_Kong），Windows x64／NTFS，工作树基线 `28a7c9e`，固定 SQLite 3.54.1。对照 BE 7.3.1—7.3.4。 [独立迭代](../../iterations/pending/v2.0/WALL-E.执行器配置隔离与生效迭代_V_2.0.md)

- 隔离专项通过原后端的普通令牌注册一次性随机任务 profile。核对真实 Windows API 返回 SID、原目录 FileID 和私有意图／完成记录。重复原分配拒绝；封闭前不能回收，封闭且原 Job 空时由 Windows 删除实际原 profile。现有 profile 无需改动。 [Windows 创建接口](https://learn.microsoft.com/en-us/windows/win32/api/userenv/nf-userenv-createappcontainerprofile) [Windows 删除接口](https://learn.microsoft.com/en-us/windows/win32/api/userenv/nf-userenv-deleteappcontainerprofile)
- 经 `tools.quality_gate.environment`、`WALLE_TEST_CONTROLLER_POSITIVE=1`、隔离 `--basetemp` 执行 `.venv/Scripts/python.exe -B tools/python-v20.py tools/quality_python.py -x -q -p no:cacheprovider --tb=short backend/tests/infrastructure/test_v20_windows_lpac_profile.py`，首轮 profile **1 项通过**（1.70 秒）。Windows 创建和删除实际执行，原临时 profile 目录与测试目录已核对不存在。

## 实际挂起令牌

- 实际 `CreateProcessAsUserW` 在原普通后端令牌下把测试 PE 挂起并原子加入原 Job。首轮只有 SystemRoot 的测试环境返回 203。补齐 Windows 环境后进程可创建，此主机原 LPAC 信息类查询返回 87。使用实际原令牌做独立 opt-out ACL 对照，保留原标志未知。真实普通 AppContainer 反例被拒绝。
- 检查原 PE、主线程、真实 Job、原用户／登录和会话、实际包 SID、零 capabilities 与 Low 完整性。只观察实际挂起进程，测试未恢复执行。 [Microsoft AppContainer 创建与权限模型](https://learn.microsoft.com/en-us/windows/win32/secauthz/implementing-an-appcontainer)

## 实际目录访问与原停止屏障

- 实际挂起测试进程使用任务 scratch 内的私有 home／AppData／temp。增加 Win32 派生的 SystemDrive，试验不向子进程环境传递真实用户路径或凭据。
- 复用原任务角色、持有的原 profile 和实际令牌。按组对 11 个原 NTFS 对象发起不读正文的有效打开，核对可写 workspace／scratch、只读依据／配置、可执行运行包、不能打开的 Guard 日志／受保护来源及禁止的删除、写 ACL／所有者等权限。通过原 FileID 核对允许路径；未知和共享冲突均不能冒充拒绝。原 STOP 封闭后同一证据请求拒绝。最终四个 LPAC 原生场景 **4 项通过**（3.90 秒）。
- 同一隔离命令附加原 Job、原生进程、路径访问、私有记录、配置／运行包和同一原 Guard 执行准备专项，最终 **117 项通过**（55.95 秒）。仅既有 Starlette 弃用提示。自动测试目录及临时 profile 存储均核对清理。应用 302 文件 Ruff 格式、5 个改动应用模块 Ruff lint 和 Git 空白检查通过。
- 同账户验证实际创建和删除每个测试 profile、实际挂起令牌及有效文件访问，全部只在隔离对象内。当前访问检查已绑定原 Guard 日志和停止屏障，尚未接入认证管道的业务 CREATE／RESUME。正式 SYSTEM／普通后端双账户、实际 OpenCode、WFP 安装与仲裁、已派发 profile 回收及完整 PREPARE 待。前批 `db20-r29` 的既有摘要差异仍在，数据库依赖仓库登记未复跑。
