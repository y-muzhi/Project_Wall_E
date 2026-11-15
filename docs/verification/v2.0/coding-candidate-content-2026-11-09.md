# Coding 候选静止前置证据、源锁与固定内容包

2026-11-09，Windows x64、NTFS、本地 master 28a7c9e 实施工作区。设计依据为 BE APP-CODE-CAPTURE、SHR-CODE-VERIFY-STAGE、7.2.2—7.2.6、7.3.4、7.6.3—7.6.4 及 7.7.6。正式前后端设计字节保留。

- 原续跑前置检查使用同原任务实例的完整 Job 观察，拒绝其他会话活跃、未结束或缺合法时间的工具、子任务、未知部件和会话绑定错误。没有把该检查投影为候选 QUIESCE。隔离原生 HTTP／续跑联合 31 项通过。固定的 [OpenCode 工具部件定义](https://github.com/anomalyco/opencode/blob/810c0eba1a7348036f8bdf61e6632d0c36c6876c/packages/sdk/openapi.json#L16747)。
- 初始候选源与内容选择／敏感内容联合 81 项通过。后续加入 LFS 拒绝，保留固定 Git 敏感策略的原路径校验优先级。所选文件按原字节和原 NTFS 身份只共享读，最终复扫核对目录与文件；新文件模式由原选择决定，跟踪文件沿原模式，被排除目录剪枝。原 Guard 初始工作区发布专项通过 1 项。
- 固定 MinGit 2.56.0.windows.4 在测试所属 Job 中创建实际私有裸库，通过 SHA-1／SHA-256 的二进制、多级目录、Unicode、可执行模式和空树向量。实际引用、树、blob、清单和封印一致后，Windows 从原目录句柄同卷不覆盖发布；重新读取原身份、暂存和目标冲突、加入外部对象引用的失败均有测试。发布／恢复只用固定包，源后来新增文件未进入内容。包和源共 11 项通过。
- 第一轮固定 Git 检查定位只读松散对象的额外写回失败，以及 SHA-256 初始化配置节顺序。按固定版本的 Git 自身 fsync 策略写回对象和引用，控制端写回初始化元数据；将实际固定配置字节作为复核对象。未修改用户 Git 配置、索引、工作区或引用。

命令为锁定 Python 的 tools/python-v20.py tools/quality_python.py -x -q -p no:cacheprovider，使用独占临时 SQLite、NTFS 目录和测试 Job。候选包与源测试分别为 backend/tests/infrastructure/test_v20_candidate_content_package.py、test_v20_candidate_workspace.py；Guard 为 test_v20_guard_control_git_transport.py::test_authenticated_task_workspace_publication[execution_pipe_watch]；续跑为 test_v20_opencode_instance_control.py、test_task_resume.py。仅保留本 Markdown 证据。

- 独立物化沿固定起点的既有物化器，验证原包的引用／树、每条原字节、目标完整树及独立 NTFS FileID。共享 Git blob 的两个物化路径保持独立；测试副本变化不改变原包。既有固定 Git 读取、秘密策略、物化及私有回执回归 51 项通过。
- 原模型入口的阶段屏障、单次原模型继续及权限回归共 31 项通过。原阶段完成观察要求明确正常结束或固定 OpenCode 的 MessageAbortedError，同任务原 Job 仅剩宿主，原问题／权限、未决操作及费用清单已核清。隔离原生／SQLite 联合 29 项通过。SQLite 成功时同事务关原模型窗、保存带真实范围的 QUIESCE 引用，并保留 CHECK 未执行状态。 [OpenCode 取消清理](https://github.com/anomalyco/opencode/blob/810c0eba1a7348036f8bdf61e6632d0c36c6876c/packages/opencode/src/session/processor.ts)。
- 候选预留编号来自共享事务分配器，内容键固定在私有 CAPTURE 步骤。封存及发布分步对账，唯一 capture_operation_id 保存候选。原版本或代次变化只补历史，停止后不更新当前指针、不开始检查。候选持久事务、实际 SQLite／ASGI 读回、原暂存包恢复和终止后历史保留联合 8 项通过。重建调度器复核封存原包后，同代次恢复当前候选；停止已生效时仅补历史并结束原捕获，CHECK 保持未执行。首次故障注入的测试安装引用长度用错，使用 Guard 要求的固定长度后重跑通过。发布当前不可变 db20-r31，保留 r30。Schema 架构／发布／迁移 10 项通过，并复核 r31 的 39 个来源和 3 个资源摘要及两份正式设计原字节。

- 在真实认证命名管道和 Windows Job 运行固定 MinGit 2.56.0.windows.4。候选专用七种操作经固定输入和原目录身份核对，包含 10 KiB 二进制输入。独立命令测试与候选调度器／SQLite 联合均通过。联合测试从已登记的原 CAPTURE 操作开始，实际后台调度保存七条成功的原 CommandExecution 和真实退出／释放证据，再封存及发布候选。重新读取原包返回同一候选编号，无新增命令。既有原 VERSION 命令和仓库调度器检查通过。复跑时过长的测试临时目录触发既有候选完整路径限制，使用较短独占前缀重跑，未放宽产品路径策略。最终候选真实 Guard 命名管道三种路径均通过，共 3 项。命令选择为 test_v20_guard_control_git_transport.py::test_authenticated_guard_builds_exact_private_candidate 的 CANDIDATE_PACKAGE／CANDIDATE_DURABLE。
- 追加故障注入覆盖 Guard 已确认 STOP／RELEASE 后、CommandExecution 写回前的中断。新调度器从私有原回执恢复原退出码、进程和 Job 绑定。丢失的管道输出无法重新取证，命令记 FAILED、捕获保持 UNKNOWN，未新增候选或派发命令。CANDIDATE_RELEASED_LOST_RESULT 与 CANDIDATE_DURABLE 联合 2 项通过。测试在同一受控后端进程重建调度器。整机重启、原 Guard 未释放和 Guard 自身丢失仍未验证。
- API52／53 验证当前／历史列表、任务归属、原包真实读取、损坏回 409 及历史保留；API42／43 读取原捕获步骤。Chrome 360／1280 隔离工作台验证列表、详情及错误恢复。浏览器沿 tools/verify-v20-command-recovery.py --probe tasks，使用独占 Chrome 与 ASGI 夹具。前端 566 项、类型、Prettier 及隔离生产构建通过。
- HANDOFF 自检计划按正式阶段前缀选固定 CheckSet，按阶段核对必需内容完整性及已链接的设计覆盖项。检查输入复核可识别独立副本字节变化，保留候选原包。CheckSet 内容／选择、候选副本及源组合 88 项通过。项目命令及被测服务逐一比对原配置的完整登记定义与生效授权中的命令和网络范围。当前数据库选择入口只接受原 BACKEND 和同代次候选；新增授权边界通过组件专项。

最终代码状态的 API47 与文档移交回归联合 8 项通过。后端改动范围 Ruff lint、backend/app 的 361 文件格式、Git 差异空白检查均通过。

API50／51 的完整捕获自检、只读检查副本的运行 ACL、项目命令和 CHECK_DRIVER 启动仍待接。旧会话仍忙时的原取消、其他命令／服务的停止证明另待实现。本轮使用受控组件和隔离原生证据。正常库、用户服务、实际 OpenCode 与供应商未参与。
