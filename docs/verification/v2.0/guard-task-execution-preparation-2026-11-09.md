# V2.0 固定程序、原入口与执行准备

2026-11-09（Asia/Hong_Kong），Windows x64，工作树基线 `28a7c9e`，固定 SQLite 3.54.1。对照 BE 7.3.1—7.4.2。 [独立迭代](../../iterations/pending/v2.0/WALL-E.执行器配置隔离与生效迭代_V_2.0.md)

- 固定程序从原部署引用及归档成员取得真实 PE 句柄。窗口参数为显式回环地址、固定原端口和关闭 mDNS。真实 NTFS 原件防替换、错误部署、重复持有、超时、非回环／未知字段均覆盖。测试用固定摘要的临时归档与 PE，未运行 OpenCode。 [固定参数](https://github.com/anomalyco/opencode/blob/810c0eba1a7348036f8bdf61e6632d0c36c6876c/packages/opencode/src/cli/network.ts)
- 原入口使用实际 Win32 TCP 监听表及进程句柄。IPv4 模型与 IPv6 转发监听、原进程、异进程、已关闭、通配地址和占用控制端口均覆盖。独占绑定探针不发送应用字节，退出时释放端口。 [Win32 TCP 表](https://learn.microsoft.com/en-us/windows/win32/api/iphlpapi/nf-iphlpapi-getextendedtcptable)
- 两项均经 `tools.quality_gate.environment`、`WALLE_TEST_CONTROLLER_POSITIVE=1` 和隔离 `--basetemp` 运行 `.venv/Scripts/python.exe -B tools/python-v20.py tools/quality_python.py -x -q -p no:cacheprovider --tb=short`。 `test_v20_opencode_binary.py` **6 项通过**（0.28 秒），`test_v20_windows_task_endpoints.py` **2 项通过**（0.84 秒）。自有目录均已核对清理。

## 原执行准备与网络计划

- 同账户认证管道在同一 TASK 原 PREPARE 下完成四类文件证据，再持有固定程序、核对登记监听和实际原端口、分配原 Job 并核对其限制及 LPAC 创建属性。Guard 持久化原执行准备记录和原 WFP 计划。证据回复按原输入摘要关联，网络规则未核实时保持 UNKNOWN。普通账户显式安装请求拒绝，没有 WFP 写入标记或完整 PREPARE 回执。部署登记监听以测试侧受信注入，正式程序与配置为夹具。
- 回归核对占用控制端口、未登记监听、重复准备、规则封存后的只读复验和迟到请求。另用测试 Job 内真实挂起子进程验证 STOP 在实际成员未退时只封闭，进程退出后原 STOP 才确认。该单项 **1 项通过**（23.38 秒）。原生阶段未创建正式 LPAC 执行器。
- 同一隔离命令选取原 Guard、任务文件／依据／工作区及执行准备管道、固定程序／配置、TCP 监听、WFP 与 Job 专项。首轮执行准备两个场景 **2 项通过**（29.32 秒）。加入部署监听登记及拒绝分支后，最终数据库无关组合 **150 项通过**（171.93 秒），实际 Job 成员停止竞争单项见上。仅既有 Starlette 弃用提示。临时目录已核对清理。应用 299 文件 Ruff 格式、13 个改动应用模块 Ruff lint、`git diff --check` 通过。
- 下一步取得实际 LPAC profile／令牌及访问证据、正式 WFP 安装和仲裁、原生入口及凭据核对、完整 PREPARE ACK／CREATE。前批 `db20-r29` 既有来源摘要差异仍保留，数据库依赖仓库登记未复跑。
