# V2.0 独立测试继续、终止与核对

2026-11-10 15:35（香港时间）。后端设计 APP-TEST-TASK、API23／27／28／30—34，前端 BND-TEST-TASK。master 28a7c9e，本地 Schema200 db20-r37。

- 固定执行资源准入后 CREATE／ATTACH 保存 READY，RUN 仍按原版本重验。原操作可按 Testing owner 读回；并发的终止保留唯一停止、原代次及全部原命令闭包。没有原停止和清理证据时保持 STOPPING 待核对。只有已闭合用例有真实结果、未派发用例有原证明且当前控制方可核实时才可继续。
- tools/python-v20.py tools/quality_python.py -x -q -p no:cacheprovider 运行 test_testing_cli_run.py、test_testing_task_api.py、test_testing_report_api.py，共 11 项通过。覆盖原 202 同键、已保留未派发记录的终止、终态核对原操作、不打开旧任务、无效原目标拒绝。历史候选和验证资产采用明确夹具，实际 Guard 执行见独立专项。已派发后的故障恢复在下节单独取证。
- npm run format:check、npm run typecheck、npm test 共 566 项通过。隔离 Chrome 原任务工作台在 360／1024／1280／1920 通过，包含既有原终止、报告和跨祖先拒绝。后续同一隔离专项再验证开始 202 响应截断后原键找回、原继续和原核对各发送一次、取消确认零写入及状态恢复。工具返回 creates=1、stops=1、reviews=1、execution=3。自有浏览器、Job 与临时构建已回收。

16:56 补证已闭合的原用例丢失 SQLite 提交。实际 Guard／MinGit／LPAC／Job，首例在取得原私有终态后注入一次丢失，C32 只观察原步骤并补写结果，C30 只继续第二例，单份原报告 PASSED。TESTING_VALIDATION_RECOVERY 1 项通过。 [实际命令及边界](testing-validation-group-2026-11-10.md)
