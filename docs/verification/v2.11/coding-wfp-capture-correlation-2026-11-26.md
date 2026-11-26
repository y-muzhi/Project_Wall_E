# Windows 控制连接拦截规则关联（2026-11-26）

V2.11 事项 22 修订 12。接续[控制端口启动诊断](coding-control-startup-diagnostics-2026-11-26.md)。本轮检查只读诊断入口，并准备将主机单次复现与实际拦截过滤器对应。

- 核对已安装仓库登记 Guard 的部署清单，`task`、`runtime`、`checks` 皆为空。现有只读 SCM 工具无法打开该正式服务，`sc.exe query` 核实原生错误 5。Windows 防火墙事件通道读出同样返回 5。当前环境的 `netsh wfp show state` 不提供该子命令。以上不用于判断主机 Guard 在运行还是已停止。
- 新增 `tools/inspect-windows-task-wfp-capture.py`。仅读单次复现临时 XML，按 IPv4 TCP 两端回环地址及源端口、控制端口匹配后台出站和任务入站，入站还需精确匹配任务 SID。用同一 XML 中的 filterId 对应规则键、供应方、层、子层和动作。重复规则、缺少规则及未命中分别返回状态，未输出应用路径、规则说明或无关事件。[微软 WFP 抓包与过滤器说明](https://learn.microsoft.com/en-us/windows/security/operating-system-security/network-security/windows-firewall/troubleshooting-uwp-firewall)
- 用锁定项目虚拟环境执行 CLI 临时夹具，共七组离线场景通过。覆盖 UTF-16／XML 命名空间、两方向及同规则多次拦截、异 SID／端口／地址／协议和允许事件、缺失和重复规则、非法 ID、DTD 与损坏 XML。Ruff 静态及格式检查通过。临时夹具回收，未采集真实网络数据。
- 实机接续以只包含该次隔离复现的临时 `wfpdiag.xml` 为输入。后台探针固定为该次绑定所得的 IPv4 源端口，另外取原受管任务 SID 和控制端口。在工作区用 `.venv/Scripts/python.exe -B tools/inspect-windows-task-wfp-capture.py <wfpdiag.xml> --task-sid <测试SID> --source-port <源端口> --control-port <控制端口>` 输出对应关系。只有真实匹配才用于定位；空结果保留未定位状态。诊断工作结束只留 Markdown。
- 未改服务、任务能力、代理、防火墙、业务数据或 8001。没有调模型。实际受管入站故障仍需有主机诊断权限的实机证据。

## 接续现场只读核对

2026-11-26，再核对 `C:\Program Files` 里可见的 7 份 WALL-E Guard 安装清单及工作区固定部署目录中的 16 份 Guard 准备清单。25 日登记方案、RepoHold 等测试部署和备选准备件的 `task`、`runtime` 均为空。正式 Guard 启动任务前仍需绑定固定运行包、后台程序及主机的任务网络证据。没有可切换的已准入 TASK 配置。

Windows 原生 `FwpmEngineOpen0` 以通常的 WinNT 鉴权和默认鉴权打开本机 BFE，均返回 5。ActiveStore 规则和网络适配器的 CIM 只读查询亦不可用。无法从该会话确认 TUN 所在的过滤层或匹配拦截规则。当前会话只读核对，未发模型请求或更新服务。继续点仍为有诊断权限的实机隔离复现、对应实际拦截 ID，并在通过允许和拒绝验证后准备 TASK 部署。[Windows 过滤平台访问控制](https://learn.microsoft.com/en-us/windows/win32/fwp/access-control)
