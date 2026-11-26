# OpenCode 执行器目录登记

2026-11-26，香港时间。V2.11 事项 22 修订 9。将固定 OpenCode 元数据接入真实配置选项，保留任务和供应方的实际准入。操作全部在当前工作区、临时库和普通沙箱内完成。

- 通过 `python -B -X utf8 -m tools.prepare-code-catalogue --release-id code20-r4` 及完整来源参数发布。实际核对官方 Windows x64 ZIP 内的 PE、固定 OpenAPI Git blob，以及 3,672 文件的完整运行闭包。发布清单 SHA-256 为 `957b615ec0ca3131a3795c76ccc245d0731318eba8613ffbf4fe45fb5984b294`。读取旧 r3 和新 r4 后逐类比较，其他选项和旧目录不变。
- 新增项 `executor:opencode-1.19.5`，引用固定二进制、原生 OpenAPI、管理配置策略及运行包。通过清单对执行器来源与响应字段作独立严格核对。缺项、摘要不一致、非法版本引用及自称就绪均被拒绝。真实 API 投影沿用同一形状校验，从目录绑定的选项读取。
- 用临时 Schema210 审阅库调用正式 `list_options` 和 `OptionsResponse.project`，返回一条 `EXECUTOR`，分页 total=1，`ready=false`，原因 `Q20-CONFIG`／`Q20-WINDOWS`。PRICE 仍为空。最初的整套 HTTP 夹具在 Windows asyncio socketpair 等待并按预定时限退出。改用不启网络的正式读取和响应投影，HTTP 收发尚未覆盖。
- 配置目录、固定程序／运行包及不能由空准入推断就绪的专项通过 47 项。4 项原生正例要求另起普通非 AppContainer 进程，本轮跳过，19 项 HTTP 案例未执行。Ruff、目录校验和改动差异检查通过。临时库、测试产物按所属目录清理。
- 当前开发包采用 r4。正常 8001 和已准备但尚未安装的固定后台包均未更新。真实代码任务继续受 Windows 控制端口入站和 Coding 模型计费准入阻塞，见[Windows 实测与收尾](coding-windows-task-route-2026-11-26.md)。本轮没有请求弹窗授权，未调用方舟或计数。
