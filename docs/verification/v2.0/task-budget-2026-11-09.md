# V2.0 Coding 任务预算专项

日期 2026-11-09，代码状态为本地 master 28a7c9e 上的工作区增量。设计来源为 BE APP-CODE-CONTROL.INCREASE_BUDGET、API40、模型预算与原幂等账本，以及 FE BND-CODE-CONTROLS。正式设计沿已有生效基线，处理说明保留在独立迭代。

| 环境与范围 | 实际结果 |
| --- | --- |
| Windows 隔离 SQLite／ASGI，`tools/python-v20.py tools/quality_python.py -x -q -p no:cacheprovider`，预算、原 START／STOP 相关路径 | 12 项通过。覆盖总额必须严格增加、非法金额／说明、旧版本冲突、不同键并发、同键原快照、账本关联、未开始任务在多次预算后仍可走空范围停止、在等待中调额不移动等待、原模型窗口及账单。 |
| 前端 `npm run typecheck`、`npm run format:check` | 均通过。 |
| 隔离 Chrome，`tools/verify-v20-command-recovery.py --probe tasks`，实际前端与受控 HTTP fixture | 1280／360 宽度通过。预算表单拒绝降低、可取消并恢复焦点，原 200 丢失后刷新页面仍能找到原键，核对原回执后显示新总额，原等待保持，预算 POST 仅一次。继续核对停止仍使用当前版本。工具确认本轮 Chrome Job 和输出已清理。 |

追加联合回归共 21 项通过。原 START 已排队、创建原会话或发送首条执行消息时可以调额。程序用原成功预算回执逐条证明新增版本，实例、会话和消息派发保留原启动的固定身份，最终状态事务比较当前真实版本。隔离 SQLite／ASGI 已验证两次调额穿过原创建／发送检查点且仅有一个 START 和一个原会话；调额后的排队 START 仍可完成空范围停止。真实账单、供应方及产品联调未执行。

最终 Chrome 复核通过。预算原回执确认后，焦点返回增加预算按钮；任务终止后同入口禁用。最终前端 566 项、类型／格式和隔离生产构建均通过。
