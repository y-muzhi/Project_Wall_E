# Coding 原停止、输出及资源回收验证

日期 2026-11-09，工作树基线 master 28a7c9e。使用隔离 SQLite、NTFS、实际认证 Guard 管道、实际 Windows Job 和专属 Chrome 测试进程。WFP 提供模拟可核对安装／删除和读回。OpenCode abort 使用固定接口契约，业务专项使用模拟原生回执。 [固定 OpenCode SDK](https://raw.githubusercontent.com/anomalyco/opencode/810c0eba1a7348036f8bdf61e6632d0c36c6876c/packages/sdk/js/src/v2/gen/sdk.gen.ts)

- `tools/python-v20.py tools/quality_python.py -x -q -p no:cacheprovider` 定向 `test_task_runtime_stop.py`、`test_task_stop.py`、`test_task_start_session.py`，12 项通过。运行中停止、原 abort 意图中断、错误 Job 观察、回收失败后原范围恢复、业务终止和历史读取均有实际 SQLite／ASGI 覆盖。后端工作副本通过真实 NTFS 删除，原树清单及依据保留。
- 同一命令定向 `test_v20_windows_pipe_capture.py` 和 `test_task_stop.py`，28 项通过。原诊断输出完整／截断分支均排空真实管道，只保留大小及摘要；空范围终止保持原规则。
- 同一命令定向 `test_authenticated_task_workspace_publication[execution_pipe_launch]`，1 项通过。实际认证管道重连，第一次 WFP 缺失读回未知，第二次核实释放，随后重复返回原 ACK，原运行目录移除、原后端源根保留。`execution_pipe_watch` 另 1 项通过，原控制方退出后真实 Job 已停，原资源待显式回收。
- `npm run typecheck`、`npm run format:check` 及 `npm test` 566 项通过。`tools/verify-v20-command-recovery.py --probe tasks --cli-entry <本机锁定 CLI>` 的实际 Chrome 360／1280 流程通过，运行中停止的原 202 丢失后按原键恢复、原进程停止与完整清理分开显示，且仅发一次停止请求；自有 Job 和临时输出已清理。
- 旧 `test_restarted_repository_actor_cleans_only_the_original_scope` 两次未进入实际交换。第二次定位到旧测试子进程的 `db20-r29` 构建源摘要不匹配，进程在连接前退出。该既有差异关联 `windows_local_paths.py`，冻结发布及其源文件保留。跨控制方 `execution_pipe_recover` 单项已通过。原后端退出且原 Job 由 Guard 监视停止后，新后端用同安装、真实同用户和原私有回执核对原范围；错误绑定拒绝，真实 STOP／RELEASE 只保存于原作用域，重复释放返回同一 ACK。该专项不覆盖 Guard 本身重启后丢失原持有者。

未覆盖生产 SYSTEM／普通后端安装、真实 WFP、固定 OpenCode 的完整终止和实际供应商。当前业务停止只验首个 Coding 实例的原工作区、可核对原会话和无额外写入者范围。费用未知保留，待后续原任务调节动作。

扩大回归包含 `test_v20_guard_recovery.py`、`test_v20_guard_action_journal.py`、`test_v20_windows_pipe_capture.py`、`test_v20_opencode_instance_control.py` 及 `execution_pipe_recover`，78 项通过。首轮组合发现缺失原 Registry 的内部原因被合并为日志归属差异，恢复原原因分类后复跑通过。

最终定向 `test_task_runtime_stop.py` 和 `test_task_stop.py` 共 6 项通过。受控中断发生在按原 NTFS 身份删除一个已盘点对象后，重读原计划完成剩余删除并返回同一原操作。第一版夹具的固定快照是空目录，首个删除就是根；补入隔离夹具内的原对象后取得部分回收和重启续接证据。终态异键请求返回真实 TaskView。
