# 失败根重新运行（2026-10-08）

范围：普通 USER_INSTRUCTION 来源 REVIEW 的 C04/I18/OP30；原 FAILED 保持独立、原用户触发消息复用、新运行正常完成、原键未知恢复/在途禁重复、最新 CURRENT、Scope失效/占用拒绝。完整重读 BE C03/C04 2501–2649、I17/I18 5173–5253、FE OP29/30 1249–1287，补读公开 GuideRunReadModel 4057–4116；完整核对原生重试/HTTP/worker/ORCH、RunControls/动作/read-owner，相关人工编辑接口。

明确私有 --controlled-retry-model 在全新 output/playwright SQLite 使用本机 TCP。首个真实 REVIEW 收到503三次；生产 ORCH 决定 call_no1/attempt_no1–3 及2/5秒后退，生产 C08 写 FAILED/MODEL_ERROR并释放占用，没有 SQL 安装失败状态。真实 I18 创建新 Run 后正常 ORCH/v2/C07 完成检查，原用户消息仍归旧 Run，新 Run引用同一trigger_message_id，不复制消息。没有新收费或正式计数/效果证明，编译预算及兼容回调明确是隔离诊断。

最终固定源码：四成功根 retry-root-browser-2026-10-07T16-26-31-751Z-3d3b345a12c7.json、两拒绝根 retry-root-browser-2026-10-07T16-26-31-734Z-46e961668e88.json 与相应两份命令报告通过。两独立 immutable关闭库审计 retry-root-post-audit-2026-10-08T02-59-53.626279+00-00.json / 02-59-53.781113+00-00.json通过。相关现有 C04/C07 原生回归28项通过（retry-root-native-regression-2026-10-07T16-27-21.308007+00-00.json），450生产输入不变，不称814整套重跑。

六根具体范围：
- RETRY-normal：真实三次失败后，页面点击一次I18，新ID被实际跟踪到COMPLETED。
- RETRY-unknown：I18真实202已落库后，明确丢一次响应；页面保原失败ID与请求、禁止新增意图，用户点击核实后实际GET并原键空body回放，两个202同data，同一新Run。
- RETRY-inflight：真实202仅交付被私有屏障暂缓，在途按钮disabled，DOM触发不发第二请求；放行后只一个新Run。
- RETRY-latest：原输入v3失败，经真实人工编辑完成v4，再从旧失败历史重新运行；旧三尝试仍v3，新审计/Manifest/read_blocks/frozen读取均v4，Baseline完整不变。
- RETRY-scope-invalid：原😀选区真实三次失败，真实人工编辑删除该选区到v4；原失败Run重试返回422 SCOPE_INVALID，页面保旧失败摘要和重试入口，0新Run/助手/建议。
- RETRY-work-conflict：页面已知IDLE但另一实际API草稿占用，I18返回409 WORK_STATE_CONFLICT，保原失败及入口；隔离清理按真正DELETE manual-draft及草稿版本，不改CURRENT。

两套452输入before/after相同且套间一致；与上批451共同输入仅私有helper变化，450生产输入保持。合计6需求/6CURRENT/6Baseline/16Run/22真实LLMUse/22本机Chat/0批次/0付费。完整CURRENT/BlockState/Baseline、旧失败的时间/范围/来源/错误不变、唯一用户指令、新Run RETRY来源及失败回执清理、旧三失败尝试和新1成功尝试、DeepSeek v2请求/schema/raw/trusted/context/Manifest/read_blocks全由关闭库独立核对。两库SHA跨审计不变，隔离服务/TCP线程/transport正常关闭。21张原阶段/失败PNG保持字节及SHA（retry-root-media/manifest.json）；原选区拒绝/UNKNOWN/最新成功图已查看。

失败保留：16-23-13脚本错把内部trigger_type断言为公开响应字段；真实新Run已经成功但脚本失败。16-23-28占用拒绝已出现，脚本清理错误猜测POST manual-draft/cancel，实际404；原库占用保留。没有放宽业务校验：内部trigger_type/trigger_message_id继续由实库验证，公开字段遵守GuideRunReadModel，清理换真实DELETE契约。两失败/命令/原图完整保留；retry-root-failure-facts-2026-10-08T03-02-53.602941+00-00.json独立保存各关闭库事实，未改原测试失败为通过。此前会话的工具进程ID失效后，检查真实完整报告及进程确认两个最终矩阵和28回归已经完成，没有重复测试。

当前预览：10-08 03:00 UTC只读探针10061，用户库SHA前后不变；只读查看1需求IDLE/0未结束Run。按此前授权尝试恢复隐藏单进程backend.app时，自动审批审查在执行前拒绝，仅称blocked by policy，未说明具体原因；没有重启，不处理崩溃。证据 retry-root-current-preview-2026-10-08T03-00-48.970724+00-00.json 和 retry-root-preview-policy-rejection-2026-10-08T03-02-53.602941+00-00.json。正常dist仍保留，8000当前停止，用户库未变。

正式373行身份/六列保留：OP30按上述普通检查部分从未开始登记实现中，44已验证/310未开始/19实现中；不是功能完成率。OP29补链接真实PERSISTING竞争专项，仍不整体升级。整体交付粗估80%左右只为工程估计，未建立逐条加权量表，不能据此宣布完成。下一单元应重读 C03/I17/C07/ORCH及FE OP29，检验真实已发送网络调用取消后的迟到门禁（消息/正文/可信输出/重试均不能追加），随后其他来源重试/初始化卡片与完整正式编号；正式DeepSeek计数兼容/真实效果及人工IME/键盘独立未闭合，未授权新增付费，不处理Windows崩溃。
