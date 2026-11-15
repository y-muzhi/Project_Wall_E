# V2.0 Testing 固定测试包封存

2026-11-10，master 28a7c9e 工作树未提交实现。以隔离 SQLite、应用服务 lifespan、私有 NTFS 目录和实际 Runner／fixture 文件闭包执行 API18／45。Runner 文件是用于封存的隔离夹具，专项未启动测试 Driver。

命令经工具锁定 SQLite 运行时和临时目录执行，使用 `tools/python-v20.py tools/quality_python.py -x -q -p no:cacheprovider backend/tests/test_testing_pack_seal.py backend/tests/test_testing_pack_api.py backend/tests/test_testing_plan_api.py backend/tests/infrastructure/test_v20_check_case_pack.py`。39 项通过，耗时 72.08 秒。覆盖实际 Revision、固定编译、公开／保留资源分隔、CheckSet TESTING owner、同包冲突、原 202 回执、响应阶段和路径隔离、真实 NTFS 字节、fixture 漂移，以及文件已写而 SQLite 提交中断后的服务重建。重建重用原包及原 operation，原文件时间与字节一致，移除遗留的未发布阶段文件，最终原子保存一个 CheckSetVersion。无编译资源 503 不建立永久拒绝回执或后台任务。

发现并修正 canonical_input 仅允许顶层对象及缺资源 503 应走可恢复错误边界的问题。Chrome 360／1280／1920 专项完成，封存界面确认前取消、原 202 响应中断、原键核对唯一后台操作、处理中禁用、读回原 SEALED、刷新复核。封存 POST 实际一次，浏览器后端为协议夹具。生产部署、原参考验证、实际 Driver 执行及发布另行取证。隔离后端、浏览器自有 Job 与临时输出已回收。
