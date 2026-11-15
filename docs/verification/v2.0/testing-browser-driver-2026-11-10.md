# V2.0 独立 CHECK_DRIVER 与双端联通专项（2026-11-10）

## 代码与范围

按 BE 0.17-draft-17 §7.6／SHR-TEST-ACCEPTANCE 及 FE 0.16-draft-16 独立测试工作台契约实施。基线 master 28a7c9e，运行 Schema200 db20-r41。驱动使用独立 CHECK_DRIVER 的 LPAC、原控制方、Job、只读固定运行闭包及私有帧。前后端各为独立原 TASK，使用自己固定的候选／快照、监听端点、Job 和清理证据。原项目包不能写结果通道。测试只用自有 Windows 临时目录、进程、端口及临时 SQLite。

## 已取得的证据

- 结果帧、私有句柄转移、标准流、固定检查资源、LPAC、WFP 计划和 Windows TCP 联合 77 项通过。实际原进程继承只读侧对应的写端，后代不能继承已撤销继承标志的写端；错误范围、nonce、超限和截断拒绝。
- Chrome 双端专项 2 项通过。已安装 Chrome 使用 chromiumSandbox=true 并置于本轮自有 Job。实际页面从前端 Windows 进程读取，点击后发起 fetch，经原 Job 和 Windows TCP 两端身份核验转发到另一个实际服务进程，DOM 显示后端生成的值。另一项核对独立监听及非登记 origin 被拒绝。两端和浏览器使用普通 Windows 测试 Job。首次 fixture 通过 Python 启动器启动，实际监听 PID 与预期不符，修正为实际解释器并按完整 Job 内根进程成员验证。
- 独立 Testing CLI／任务／报告既有 SQLite／ASGI 回归 13 项通过。原生 Guard 夹具已到独立 LPAC 的创建、恢复、退出、STOP 和 RELEASE。首次未取得可信结果帧，继续核对驱动进程退出与私有帧；该路径仍未通过。

## 未验证范围

正式 SYSTEM／WFP 安装、固定 Playwright Python／Chromium 运行闭包、真实 LPAC 中浏览器及两端候选同时启动、原四阶段正向报告及 Coding 接收和 Git 交付仍独立验证。此前 LPAC SERVICE 的 Winsock 10107 保留为该宿主现象。源码准入默认阻断缺少证明的资源。隔离输出目录在专项结束后由各自工具清理。

## 19:31 续验

- 独立 Guard LPAC 夹具取得原进程创建、恢复、退出、STOP 与 RELEASE。复制的 CPython 退出 0xC0000022，驱动私有结果通道读取零帧。该用例记为 1 项跳过，浏览器 LPAC 断言未通过。
- `backend/tests/test_testing_cli_run.py::test_browser_original_intake_reserves_three_distinct_commands_without_fixture_pass` 实际 HTTP／SQLite 1 项通过。BROWSER 的原计划和封存用例为每例保留一个 CHECK_DRIVER 和两个不同服务范围。无实际运行安装时收口为资源缺失，无通过报告。初次发现私有记录名称未登记，修正后通过。C32 在已派发情况下按实际三个范围分别只读观察，未将夹具当作真实浏览器报告。

## 19:51 复验

- 在现行 Schema200 db20-r43 上，隔离 Testing CLI／报告、双 Windows 进程和实际 Chrome、独立 LPAC 驱动联合复验 8 项通过、1 项跳过。命令使用 `tools/python-v20.py tools/quality_python.py -x -q -p no:cacheprovider` 和受控临时 `--basetemp`。独立驱动仍在真实 LPAC 中以 0xC0000022 退出，私有通道无有效帧。已校验原 RELEASE 的非零退出归入不可用，缺少运行／清理证明的状态保留不明。普通 Chrome 双端连通和正式 LPAC 准入各自记录。


## 21:20 独立 LPAC 启动诊断

- Windows x64 原测试夹具补齐 Anaconda CPython 3.13 主 DLL 直接依赖的 `zlib.dll`，并用本机已有 CPython 3.12.14 作独立对照。两项仍在原专项记为跳过；未放行浏览器能力。
- 仅调试本轮原已挂起 CHECK_DRIVER PID。解释器和基础系统 DLL、私有 C 运行库及 `python313.dll` 已映射；初始化在驱动脚本／私有结果帧之前以 `0xC0000022` 结束。对原限制令牌分别 impersonate，确认选取的私有 DLL 和系统 DLL 可由绝对路径直接打开并以 `SEC_IMAGE` 映射；现有证据不足以定位加载器的确切拒绝对象。
- 两次诊断沿原 STOP／RELEASE；未更改系统 ACL、安装、工作区用户数据或产品准入。临时调试探针已删除。正式 LPAC 三进程及独立报告继续受阻。普通受管 Chrome 的双端联通仍按前项范围有效。

## 21:40 独立驱动收尾恢复

修正收到原 RELEASE ACK 但最后一次 Job 观察不完整时提前关闭本地结果／控制句柄。真实 Windows 原 CHECK_DRIVER 创建、退出及 Guard 夹具验证：注入原 RELEASE 后的观测缺口时拒绝结案并保留句柄；重新观察完整空 Job 后完成，未重发原 RELEASE。专项中收尾证明 1 项通过，可信结果帧仍按 LPAC 解释器退出跳过。联合另覆盖原路由与 Testing 隔离回归，共 6 项通过、2 项跳过；其一为这次未注入本机 Playwright 路径的普通 Chrome 分支，既有双端联通证据仍单列。WFP 与正式运行资源保持原准入。

22:03 补验：显式注入本机已安装 Playwright 模块后，真实普通 Windows Chrome＋双端原应用 Job 的两个用例均通过，端点归属和结果边界保持。未把普通 Chrome 证据替代独立 LPAC 的可信帧或正式三进程验收。
