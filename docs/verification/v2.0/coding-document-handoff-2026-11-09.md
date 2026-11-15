# V2.0 原问题移交到文档验证

日期 2026-11-09，本地 master 28a7c9e 的 V2.0 工作区。按 BE APP-CODE-QUESTIONS 4.2—4.4、API25／48／49、FE BND-CODE-ISSUES 及需求详情深链规则。

| 环境及命令 | 实际结果 |
| --- | --- |
| Windows 隔离 SQLite／ASGI，`tools/python-v20.py tools/quality_python.py -x -q -p no:cacheprovider`，`test_task_question_handoff.py` | 端到端 1 项通过。核对 C48 201、跨需求目标与同任务证据、固定主设计／材料、原回执、事件分页、C49 201、已有 Revision 归属、停止后可读及不可追加。比较移交前后真实表，正文、Revision、ConversationMessage、GuideRun、LLMUse 未产生变化，原问题仍 OPEN，原任务等待保持。完成停止后原题按既有停止流程退役，移交事件保留。 |
| Chrome 隔离工作台，`tools/verify-v20-command-recovery.py --probe tasks` | 360／1280 通过。窄屏选择同需求目标及原操作证据，模拟丢失 201 后按原键恢复；宽屏由用户打开目标文档，显式追加来源及证据到已有草稿，关联已有版本，刷新后保留原草稿且插入入口禁用。夹具记录一条移交、一条关联及零条文档模型发送。Chrome／Job／临时输出已清理。 |
| 前端 `npm run typecheck`、`npm run format:check` | 通过。 |

首轮后端发现共享 HTTP 入口需要声明原 JSON 请求体，已补齐。测试随后按固定主设计加材料的完整任务依据修正断言。首轮浏览器夹具在切换场景时残留上一原继续的活跃操作，严格 TaskView 拒收该快照，夹具修正后最终回归通过。

API25／48／49 采用详细结果表的 200／201。已保存讨论和版本结果引用由服务器按同文档／需求校验；前端输入已有编号。真实文档讨论发送与模型调用保留独立授权和现有流程。本轮浏览器使用模拟业务 HTTP。
