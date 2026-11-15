# V2.0 Coding 原模型等待继续专项

日期 2026-11-09，代码状态为本地 master 28a7c9e 上的工作区增量。核对 BE APP-CODE-CONTROL.RESUME、API17／34／36／42／43、7.4.2—7.5.5，FE BND-CODE-CONTROLS 及原请求恢复。正式设计源沿已有摘要。

| 环境及命令 | 实际证据 |
| --- | --- |
| Windows 隔离 SQLite／ASGI，`tools/python-v20.py tools/quality_python.py -x -q -p no:cacheprovider`，原继续、预算、开始和停止 | 21 项通过。当前任务、版本、原操作及等待项必须完全对应；同键保留原 202，当前活动不重复接受；明确继续只派发一次，丢失响应后用同一消息 ID 查询；原等待在接收核实前继续保持，原 START 的消息绑定保留；停止先到时封闭窗口。 |
| 同一 SQLite／ASGI 运行中的原操作历史 | API42／43 与 API17 返回相同原投影，按创建时刻／ID 倒序、保留越界空页及真实总数；不接受跨任务、非读取参数和幂等头。 |
| Coding 模型账、MockTransport 供应方 | 9 项通过，覆盖原请求、SSE、费用预留／结算、重启恢复和终止抢占。 |
| 隔离 Chrome、`tools/verify-v20-command-recovery.py --probe tasks` | 360／1280 实际前端与模拟 HTTP；继续确认可取消，响应丢失后同原键核对，结果未知期间禁用重复操作，查到原消息后才显示已接收。确认继续仅一次。 |

固定 OpenCode 处理器使用原实例的状态映射，空闲条目会从映射移除。继续另核对原消息、对应的已完成回复、同会话请求及两次同一 Guard Job 快照。该组观察服务于原模型继续。交接／捕获所需的完整阶段静止另作专项。 [固定状态实现](https://github.com/anomalyco/opencode/blob/810c0eba1a7348036f8bdf61e6632d0c36c6876c/packages/opencode/src/session/status.ts) [固定消息读取](https://github.com/anomalyco/opencode/blob/810c0eba1a7348036f8bdf61e6632d0c36c6876c/packages/opencode/src/session/message-v2.ts)

隔离业务测试以受控 driver 观察消息。实际 OpenCode 执行、正式部署、真实供应方和费用证据仍待。当前正向范围限原 BACKEND 模型等待，原 Delivery／检查等后续阶段由各自原操作接续。

最终 Windows 联合专项 31 项通过，另有 5 项 Guard 运行快照门槛测试通过。补充验证原已接受 TCP 在新窗口建立后仍被原窗口拒绝；预算不足在登记继续派发之前保留 HELD；原停止完成后保留已经可能发出的继续消息为 UNKNOWN。Guard 快照门槛用受控回执验证原进程身份、完整 Job、无子进程及停止栅栏。

原命令账本／HTTP 错误边界回归 6 项通过。前端最终版本 566 项测试、类型／格式及临时生产构建通过。运行库与浏览器 fixture 隔离，结果只保留本 Markdown。

原仓库及原操作投影回归另 13 项通过。正式设计 SHA256、db20-r29 冻结资源摘要及原提交基线复查一致；发布源码清单仍只报接续前的 `windows_local_paths.py` 差异。
