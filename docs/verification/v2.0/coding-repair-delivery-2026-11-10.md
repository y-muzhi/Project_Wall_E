# V2.0 Coding 明确修复、报告接收与交付（2026-11-10）

本轮依据 BE 0.17-draft-17 的 APP-CODE-REPAIR、APP-CODE-DELIVERY、SHR-CODE-FINALIZE 和 §7.7，以及 FE 0.16-draft-16 的 Coding 缺陷、报告与交付工作台。起点 master 28a7c9e。使用隔离 Schema200 SQLite、原权限和临时 Git 仓库。

- C59 在当前候选上选择固定缺陷，另存原修复与原操作。原任务和固定候选可读，缺陷须同任务同候选。真实 SQLite／HTTP 专项验证拒绝不适用请求、同键回执、C27／C61 原记录。丢失派发响应使用原生传输夹具核对，只发送一次，确认后只申请一次新候选捕获。需要从固定包恢复到新工作区的分支仍待实施。
- C69 使用 Testing 原资格，不合格的诊断报告被实际拒绝。使用明确替换报告准入的合格夹具，实际 ASGI／SQLite 复验 C69→C62→C64 的独立原操作、确认与回执。目标变化拒绝，人工风险必须匹配，同键重复接收不再访问目标。交付记录公开 PENDING 和原窗口待确认，无已交付时间。正式合格 LPAC 报告到 C69 的正向链路仍未取得。
- 完整目标包及差异、候选对象、SHA-1／SHA-256 和阶段提交由真实固定 MinGit 在自有隔离仓库验证。95 项原 Git 及控制联合通过。完整目标独有文件计入删除，目标仓库内重建对象保留原提交字节；准备确认前目标引用保持原值，旧值失配拒绝。实际固定 Git 的证据与受控产品线程和正常仓库的准入分开。
- 前端 strict／Prettier 与 566 项 Node 回归通过。新增交付控件的实际浏览器、正式系统 Guard 及自然收尾另核对。

命令采用项目锁定环境和临时目录包装，核心为 `tools/python-v20.py tools/quality_python.py -x -q -p no:cacheprovider` 对 `backend/tests/code_tasks/test_task_delivery.py`、`test_task_repairs.py`、`backend/tests/infrastructure/test_v20_delivery_git.py` 及原 Git 基线／协议专项，前端在 `frontend` 执行 `npm run typecheck`、`npm run format:check`、`npm test`。临时库和 Git 目录随专项清理。

## 19:31 续验

- 本轮隔离 SQLite 的修复、接收、停止联合 6 项通过。原停止在 MAY 保存之后、实际发送许可之前接收，事务不交付写端许可，原 MAY 回执保留。夹具观察到 expected 时保持 UNKNOWN，观察到原计划提交且固定对象已确认时补原交付，原任务仍 STOPPING。此项使用真实 HTTP／SQLite 与私有持久回执，持锁进程与外部观察为定向夹具。
- 实际 Windows Guard、原 Job、STDIO 和固定 MinGit 联合 2 项在 SHA-1／SHA-256 通过。同一真实锁持有时，另一个固定 Git 命令观察到旧目标。原管道只接受一次提交，退出后读回原新值与 reflog，原索引、工作树和 HEAD 无变化。此联合与协议回归共 94 项通过。测试分支在自有临时仓库内，未调用正常仓库。
- `tools/verify-v20-command-recovery.py --cli-entry <本机固定 CLI> --probe coding-delivery` 在真实 Chrome 和隔离 HTTP 夹具中验证 360／1024／1280／1920。覆盖固定预览读取失败及恢复、删除项两侧、人工风险和合作窗口分别阻断接收、取消后输入保留、原请求只提交一次、待交付历史。首次发现 360 宽度下提交 OID 导致溢出，改用现有事实布局及可换行内容后通过。实际 SPA 用 Vite 构建至临时目录，Job 结束后清理目录。
- 最新 B3 后台收尾已接源码和 C38 原操作核对，完整产品链及正式安装仍待验证。窗口重确认、从漂移工作区恢复原修复候选均仍有未完成分支。

## 19:52 复验

- 固定 MinGit 在真实 Windows Guard／Job 下按 SHA-1／SHA-256 各运行完整的 14 个受控命令，2 项通过。覆盖固定对象写入、两阶段引用更新、持锁期间由另一个受控 Git 进程验证原引用、单次 COMMIT 后读回引用及 reflog、真实 merge-base 的成功与非祖先退出、原索引／HEAD／工作树保持一致。命令使用 `tools/python-v20.py tools/quality_python.py -x -q -p no:cacheprovider backend/tests/infrastructure/test_v20_native_delivery_guard.py` 原生 Guard 专项与自有临时仓库。
- `tools/verify-v20-command-recovery.py --cli-entry <本机固定 CLI> --probe coding-delivery` 的 360／1024／1280／1920 验证新增 C59 选择明确缺陷、取消保留原选择、请求仅发送一次及固定修复历史。 `--probe coding-report-link` 在 360／1280 验证 C69 丢失响应后按原键找回、仅一次接收、两条固定缺陷与报告撤销。真实 Chrome 启动实际 SPA，业务 HTTP 数据来自隔离夹具。
- C36 原窗口续期只覆盖原交付尚未派发任何 Git 命令。已发原命令的恢复仍按只读核对保留原事实。正式应用的 B3 交付 worker 准入仍关闭。

## 20:16 复验

- 现行 Schema200 db20-r43 上，隔离 SQLite、修复、报告接收、交付、C36 模型恢复回归联合 14 项通过。命令为本文件前述 Python 专项入口，测试文件为 test_task_delivery.py、test_task_resume.py 和 test_task_repairs.py。已验证未知 COMMIT 回执的只读观察，确认后再次观察到原目标也保留原已交付时间。
- 自然收尾重试曾将失败的空结果固定到第 8 步，阻断后续写入完整结果。修正为未取得证据时保留 NULL，仅确认原 STOP 和 CLEANUP 后保存最终证据。现行 Schema 的终态约束要求真实关联交付记录，复验夹具复用同库的候选和报告并补齐交付引用。另测正式 SYSTEM／WFP、同候选原生运行和应用交付 worker 准入。
- 后端 Ruff 全目录 466 个文件格式通过，收尾与 Job 证据模块定向 lint 通过。早期失败的原生 Git 专项遗留两个自有测试进程，经 PID、创建时间和原临时命令核实后退出，临时根目录确认消失。

## 20:18 自然收尾

隔离专项 1 项通过。对同库的 Testing 报告、候选、交付计划、接收、窗口和交付记录，实际执行原 SQLite 事务、原 NTFS 工作区清理及结果回读。第一次 STOP 或 RELEASE 证据不完整时，任务保持等待，工作区保留，原步骤结果为空。两种证据齐备后进入 COMPLETED／FINISHED，原 STOP 与 CLEANUP 各保留一条可核对记录。Git 已提交状态和 Guard 回执使用定向夹具，正式 B3 端到端独立待验。命令目标为 test_task_runtime_stop.py::test_delivery_naturally_closes_original_workspace_only_after_native_proof。末次定向 lint、应用及该测试共 467 文件格式与 Git 空白检查通过。

## 21:28 已构建对象的交付窗口恢复

- C36 同一原 Delivery 仅在原构建与计划步骤完成、原命令收尾、从未登记引用命令时允许新合作窗口。后续先按原封存候选及固定提交只读核对父提交、blob、树和提交的完整字节，再继续原引用步骤。原 Acceptance、Delivery、已完成步骤及 planned OID 不变。已登记任一引用命令、原活动未关或原写可能已发送不开放此分支。
- 隔离 SQLite 原窗口／原请求／单次发送栅栏，以及真实固定 MinGit 两种对象格式联合 3 项通过（test_task_delivery.py、test_v20_delivery_git.py）。覆盖已构建对象继续、未结束命令和任一引用命令拒绝、原对象只读回读且目标分支仍是旧值。测试采用自有临时 Git，续窗前的 SQLite 原命令事实由定向夹具构造；正式 B3 部署及已准备引用的窗口恢复仍未验证。

## 21:40 原修复消息与自然收尾

- C38 可显式只读核对 C59 的原修复消息。隔离 SQLite／ASGI 与同角色／原停止回归 14 项通过：原派发丢响应后读到其他消息时保持 UNKNOWN；再次核对只确认同一消息并恢复原 RUNNING，不重发模型消息，只预留一次新候选捕获。自有 Chrome 360／1280 验证取消、确认、读取及等待，原角色投递回归通过。没有执行真实模型，漂移工作区恢复及同角色新会话仍待。
- C36 自然收尾分支不接受 Git 窗口确认，不新建窗口、不触发 Git 或模型。只允许确认 Git 和 postcheck、同原冻结范围及未完成的第 8 步；存在原 STOP 证据时只继续 CLEANUP。隔离 SQLite／NTFS、原继续及窗口回归 16 项通过，首次缺 STOP 或 RELEASE 证明时等待，原 C36 同键重放，原交付时间和窗口保持，最终只记各一条 STOP／CLEANUP。Chrome 360／1024／1280／1920 的 Coding 交付回归包含 360 下的新入口、取消、响应丢失、冷恢复及单次 C36。正式部署与跨控制方联合尚未执行。

## 22:17 原引用明确中止后的重确认

C36 扩至两类可证明未发送的准备：SQLite 尚未保存准备、以及旧锁与锁内目标两步已保存但原第 6 步没有 MAY 证据。只有原退出、Job 停止、RELEASE 完整、私有 ABORT 且无私有 MAY／ACK，才允许明确重确认原 Delivery。已保存旧准备时还必须找回原私有 PREPARED；旧步骤不回写，新准备重新验证原对象、原目标及锁，新 MAY 继续绑定到原发送步骤。若私有 MAY 已保存但 SQLite 未写入，保持原未知，只读核对。丢失原对象完成记录且从未登记引用时，只读重验全部固定对象，缺任意对象不再写入。

早期准备及 SQLite/NTFS、固定 MinGit SHA-1／SHA-256 联合 5 项通过；修正测试夹具后，旧锁已保存分支与两种实际 Git 格式联合 3 项通过。实际 MinGit 明确 ABORT、目标不变、原锁已消失后才启动下一个事务。旧锁续窗由原 SQLite 步骤、窗口和私有日志专项验证，实际完整 Guard／交付进程链仍需单独验收。

22:44 实际原 Guard／MinGit SHA-1、SHA-256 和 SQLite Delivery 接收、可能已发、两种原 ABORT 场景联合 6 项通过。真实 Git 持锁目标及对象证据与 SQLite 原重确认分开，未将它们当作正式生产 C64 整链。Chrome 已核对固定历史 Plan、原文件的前后两侧、刷新和缺失；打开历史预览不读当前交付或报告、不发送接收／交付。原自然收尾继续的确认和一次派发回归通过。

22:47 C59 来源边界复验：原修复、原捕获／回读与原生 HTTP 控制联合 35 项通过。使用隔离 NTFS 中由固定 MinGit 形成的实际封存候选：原工作区字节一致时可复核；只在隔离工作区追加字节后，原来源读取确定不一致，原文件保留。另在真实 SQLite／ASGI 验证：原修复的 RESTORE_SOURCE 为 FAILED／SOURCE_CHANGED，后续三个原步骤保持 PENDING，不派发消息，当前候选与旧模型窗口不变；同键返回原接收回执。修复详情解释已核实未发送，不展示内部路径。此分支确认安全失败；仍需真实安全恢复工作区和同角色新会话。

## 23:00 原工作区补缺

- 恢复前核对 SQLite 原候选及实际固定 MinGit 封存包、完整读取原活跃工作区、复核原会话及 Job。只补仍在原父目录下的缺失路径，原任务 scratch 内完整写入并刷新后，按原 NTFS 文件句柄无覆盖发布，发布受原 REPAIR 及 STOP 栅栏控制。其后完整复读原工作区及原会话，核对一致才允许准备原修复消息。原候选和缺陷历史保持原样。
- 锁定 Python 运行 pytest 目标 test_v20_task_repair_file.py、test_task_capture_quiescence.py::test_original_capture_runs_fixed_git_and_recovers_without_source、test_task_repairs.py，7 项通过。实际 NTFS 验证补回 CRLF 原字节、并发同名文件未覆盖、取消发布后清理、父目录身份失配、已有变化及额外文件保留。原静止凭据使用定向夹具，NTFS、封存包、MinGit、SQLite 和 ASGI 为真实隔离组件。临时目录已清理。
- Ruff 后端 470 个文件格式、变更生产模块与新增专项 lint、git diff --check 通过。旧 capture 夹具测试模块的导入式 fixture lint 仍有既有报错，保留 fixture 注册。正式 Guard／LPAC、整树漂移、同角色新会话及供应方未执行。

## 23:33 原目录恢复、句柄锁定与发送失联

- 补缺扩至原封存候选的缺失父目录。全部名称先与实际命名空间核对，原父目录固定后逐层创建，同名竞态不覆盖，已有内容变化或额外文件仍保留并停止。原 SQLite STOP 获准后会阻止下一次目录创建／文件发布及原模型发送。
- 原完整工作区在持有选中文件的实际 NTFS 句柄时重新核对，并在释放前写入同一 REPAIR 的 RESTORE_SOURCE 与 SEND_REPAIR 意图。原句柄释放结果异常时只观察原消息，未重复派发。锁定 Python 的修复、原文件发布和实际 MinGit 候选专项共 9 项通过，Ruff 470 文件格式与变更生产模块 lint 通过。原模型发送及原静止证明使用定向夹具，未向供应方发请求。

## 23:48 AI20-REPAIR 原消息和实际补缺联通

- 项目锁定 Python 运行 test_task_capture_quiescence.py::test_original_capture_runs_fixed_git_and_recovers_without_source，最终 1 项通过。隔离 ASGI 用原缺陷和 C59 HTTP 路由，原候选由实际固定 MinGit 建立，真实 NTFS 恢复两层缺失目录和 CRLF 文件。保持原句柄到 SQLite 保存原 RESTORE_SOURCE／SEND_REPAIR 意图，读取确认后只打开原排队模型窗口，同键回放返回原 TaskReceipt。
- 原生消息用真实构造和 ID 生成，核对原角色、原封存候选及路径、用户所选两条缺陷顺序、固定原文与证据、主设计和材料文件摘要、原有效授权和结尾范围约束。原设计及路径未通过公开 OperationView 泄漏。前序失败定位到缺陷数组误传仅接受对象的规范编码器，改为保留顺序的对象字段；测试断言改为从原材料关联表独立核对两份来源。
- test_v20_opencode_instance_control.py 最终 26 项通过，包含超原生 JSON 上限的 UTF-8 正文在产生原发送意图前拒绝；原生控制、角色链、启动和原生等待关联 44 项通过。另有修复、开始、继续与文件发布联合 26 项通过。范围交叉，不累加为产品用例总数。Ruff 470 文件格式和变更模块 lint、git diff --check 通过。Windows 测试目录和 Chrome Job 均按原范围清理。
- 联通的原生静止、发送确认由定向夹具提供，实际程序处理消息和模型窗，真实供应方未调用。已有文件漂移、同角色新会话及正式 Guard／LPAC 保持下一断点。
