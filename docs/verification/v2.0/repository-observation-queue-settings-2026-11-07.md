# C02 仓库队列、HTTP 与设置页验证

2026-11-07，V2.0 工作区，db20-r18、固定 SQLite 3.54.1、MinGit 2.56.0.windows.4。实际工作库与用户服务未操作。

- 后端经 tools/python-v20.py 激活固定 SQLite，执行 test_repository_acceptance.py、test_repository_registration_actor.py、test_repository_git_dispatch.py、test_repository_observation_publish.py，共 40 项通过（100.69秒）。涵盖真实 ASGI 的空对象／路径／幂等键／未就绪无部分写／同键原202、原取件和原事务约束。首次普通权限组合在360秒超时，受控隔离进程复跑通过。已通过既有本机 Guard 普通程序准入测试端口验证派发；正式 SYSTEM 受信安装未接。
- 完整 Native 管道首轮11通过／2失败，C02 流程把目录导出上下文错当实际导出，第二条命令未派发。修复为进入真实目录租约并保持外层原位置租约。第二轮13项主体通过，SHA256 隔离夹具退出时测试根短时占用导致清理报错，已在原结果后等待原进程正常退出，最终整组13项通过（182.80秒）。两种格式均经 SQLite 原回执及生产队列取件，三条真实固定命令逐个释放，原观察保存及同键重放。
- npm run typecheck、npm run format:check、npm test 通过，前端551项。tools/verify-v20-command-recovery.py --probe settings 经隔离构建、Chrome 及真实 IndexedDB 通过。设置全回归含1280／360px。新增场景检查打开仓库不发POST、显式空对象仅一次、禁用布局、202中断后同键恢复、UNKNOWN不重新提交、仅GET本次结果中的原观察 #35、正常分支及工作树空态。总计97次产品GET、9次明确写（C02一次），测试Job和构建已清理。浏览器HTTP使用隔离回执，实际保护部署、任务创建页观察入口和真实模型未覆盖。
- 后端Ruff格式243文件、受影响模块lint与git diff --check通过。共享工作区既有CRLF提示不影响检查。

- 在同一隔离用例中补足真实 ASGI → 实际后端专用线程 → 本机 Guard／固定 MinGit → 原操作及观察 GET，test_v20_guard_control_git_transport.py -k THREAD 最终 2 项通过（65.46秒），同时复测 C01。C02 用真实 202 接收，测试丢失唤醒仍从数据库取件、同键回放原202、三条原命令已释放、按原观察ID读取正确 HEAD、正常退出释放 ProcessLock。SCM 注册和程序保护准入在隔离 fixture 注入，仍需正式安装联调。
