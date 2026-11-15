# V2.0 Coding 捕获自检、原候选复检及工作台

2026-11-10 香港时间。Git 基线 master 28a7c9e，测试使用本轮工作区源码与隔离环境。BE 0.17-draft-17、FE 0.16-draft-16 按原摘要，覆盖 APP-CODE-CAPTURE／VERIFY、SHR-CODE-VERIFY-STAGE、API50／51、API24／54、7.6.3—7.6.7 和 FE BND-CODE-CHECKS。本轮仅离线，使用实际 Windows NTFS、Job、LPAC、Guard 认证管道及 WFP 行为夹具。

- 原命令与复检。通过 ASGI 请求真实接受 API50。资源缺失时 503，同一原键可用于准备完成后接受；错误 purpose 422，重复同键返回原 202，冲突中的其他原请求被拒。原候选在隔离 Windows 经实际固定 Git 和原 CHECK 后能由 API24／54 读回。API51 按固定同候选接收，完成三个原步骤、生成新 Verification，原候选和原记录保留。注入复制中断后使用新后台 worker 核清从未派发，原步骤完成为 SUCCEEDED／FAILED／CANCELLED，原 Verification 为 UNKNOWN，停止和清理均 VERIFIED，操作失败码 EVIDENCE_INCOMPLETE，未连接 Guard。首跑发现 Schema 缺少该操作失败值，发布不可变 db20-r32 后重跑通过（1 项，140.10 秒）。
- 工作台。开发自检页的捕获、重查、不可用原因、原操作进度、结果／退出码、当前与历史均使用同一任务控制上下文；前端通过锁定类型／格式检查，应用测试 566 项。独立 Chrome 测试构建并打开隔离页面，360／1280 像素下验证成功空、读取失败及重试、禁用和进行中、结果未合格、确认取消、同候选重查、丢失 202 后刷新只查原键及最终结果。首次 Chrome runner 的新增 HTTP 夹具未声明 async，修正后退出 0，已核对浏览器 Job 清空及临时输出清理。
- 复现。Windows 隔离测试通过 tools/python-v20.py tools/quality_python.py -x -q -p no:cacheprovider 指定 backend/tests/infrastructure/test_v20_guard_control_git_transport.py::test_authenticated_project_check_transfers_input_runs_and_releases_original_job[PROJECT_CHECK_DURABLE]，保留原测试 Windows 进程／测试用临时目录清理机制。浏览器使用 tools/verify-v20-command-recovery.py --probe tasks --cli-entry 指向本机已有 Playwright CLI；执行真实隔离 Chrome、预构建隔离前端和 HTTP 夹具。前端检查使用 npm --prefix frontend run typecheck、npm --prefix frontend run format:check、npm --prefix frontend test。
- 未覆盖。原 BACKEND 离线配置以外的阶段／角色交接、正式资源与实际 SYSTEM／WFP 数据面、真实 OpenCode／供应方、真实业务库迁移、独立功能验收和真实前后端产品联调另验。浏览器使用隔离前端及 API 响应夹具。


追加验证（当前 db20-r33）。同一 CheckSet 选择两条已登记项目命令和完整性项，在真实认证管道依固定顺序运行。每条有独立原 CommandExecution、nonce、Job 和恢复凭据；第一条真实退出 0，选检第二条真实退出 1，合格性继续依据必检。实际独立输入副本及同一 Verification，WFP 夹具禁止两个范围重叠。复查中完成首条后撤去准入，后台在不连接 Guard 的条件下关闭原余项，保留首条退出和结果，第二条为 NOT_RUN 且无启动时刻。首跑补齐双命令测试夹具，随后修复 worker 把仍可派发的原空闲队列误当作已推进。修复后 PROJECT_CHECK_MULTI 与 PROJECT_CHECK_DURABLE 联合 2 项通过，277.89 秒。
