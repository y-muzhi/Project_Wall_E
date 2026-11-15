# V2.0 Testing 原 AI 计划草稿

2026-11-10（香港时间）。BE APP-TEST-PLAN 4.7、APP-TEST-QUERY、API26／33／34／41／42 与 FE Testing 任务工作台。隔离 Windows、ASGI、SQLite 3.54.1、Schema200 db20-r40，模型网关使用测试传输及本机协议夹具。

- tools/python-v20.py tools/quality_python.py -x -q -p no:cacheprovider 运行 backend/tests/test_testing_planning_api.py、backend/tests/test_testing_task_api.py 及 backend/tests/infrastructure/test_model_gateway.py 中实际请求封套和单次超时／断连两项，共 15 项通过。固定原文、材料及上下文；原键重放只保留一个 PLAN_TEST、一次发送和一笔 LLMUse。正常输出保存唯一原 DRAFT。原文错误保留已知使用量，不保存草稿。未部署或预算不足不发送；未知费用保留原预留。终止后抵达的结果只记原实际费用。
- tools/verify-v20-command-recovery.py --probe testing-task-workspace。隔离 Chrome 实际工作台在 360／1024／1280／1920 通过。浏览器对独立 HTTP 夹具验证显式确认、响应截断后找回原键、读取原操作及草稿。保存后仍须分别完成发布、测试包编译／验证和任务资产绑定。用同一工作台回归创建、停止、人工归因、原执行控制。
- Schema200 db20-r41 后对起草及两条模型网关边界复跑 8 项通过。
- 首轮扩大回归中 V1.5 旧业务取消夹具在准备需求时得到空结果，尚未到达模型网关。两条直接网关请求／超时用例已在上述 15 项中独立通过。真实供应方、生产报价配置及实际模型生成质量未验。

仅保留本记录。隔离 SQLite、临时原生进程及 Chrome 输出由测试回收。
