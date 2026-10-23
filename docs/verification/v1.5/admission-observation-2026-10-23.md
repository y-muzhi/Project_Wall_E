# V1.5准入与隔离观测离线检查（2026-10-23）

代码基于GitHub实施快照ac25218，新增隔离观测实际入口、审计事务核实及预算delegate；生产普通调度继续要求有效准入，资源v9／v10冻结字节不改。所有观测证据由私有离线delegate构造，不能当真实供应方证据或实际LIVE_VERIFIED发布。

环境：Windows、项目.venv Python／SQLite。test_v15_foundation.tmp_path覆盖pytest默认保留目录，所有正常数据库／计数审计及准入配置均在TemporaryDirectory，成功和失败后清理。不调用真实Chat／Tokenization，不读真实环境密钥，不写用户库，不启动服务；验证只保留本Markdown。

实际命令及结果：

- 准入／接受／计数／用量联合：`python -m pytest backend/tests/guide/test_v15_admission.py backend/tests/guide/test_v15_acceptance.py backend/tests/guide/test_v15_counting.py backend/tests/guide/test_v15_usage.py -q -p no:cacheprovider`，22 passed，92.79秒（隔离观测接线前）。首轮失败是夹具及CLI遗漏operation_time(None)，已修正；普通准备审计已传入同一已核实凭证。
- 同步前准入及执行联合：`python -m pytest backend/tests/guide/test_v15_admission.py backend/tests/guide/test_v15_execution.py -q -p no:cacheprovider`，15 passed，88.58秒。包括真实调度路径读取原审计准入、保存新调用准入快照、异常用量持久暂停及第三轮IO前拒绝；实际发送均为离线delegate。
- 新隔离入口专项：`python -m pytest backend/tests/guide/test_v15_observation.py -q -p no:cacheprovider`，7 passed，44.21秒。覆盖正常实际审计／不入Wire、不可重复目录、计数失败、实际usage矛盾、跨库／run／profile／非独立工作区拒绝、未知异常已消耗额度、默认离线预览／不读环境密钥、显式预算以及HTTP／Worker拒绝观察参数。没有patch生产require_live来完成新正向观察。

新工具默认模式通过上述main([])实际执行：临时新库接受唯一DISCUSS，调用实际Canonical／Wire编译，打印摘要与预算，计数0／Chat0；临时目录自动清理。真实execute选项未运行。正常观测槽在真实使用时是需保留的业务审计，不是测试JSON报告；本轮专项的模拟槽由TemporaryDirectory清理。

完整24文件后端联合正在执行，最终结果待补；本记录不提前宣称通过。存在既有Starlette httpx弃用提示。前端本单元未变，不重复最近完整355项／tsc／临时生产构建。

剩余：真实供应方准入和EV仍未授权；部分完整浏览器情境见验收矩阵。技术准入只验证当前release／profile及实际请求／用量，不能把一次成功当长期供应方容量保证，也不代替业务语义效果验收。

完整联合的首次2361输出不可取回；第二次76373在打印捕获输出时遇GBK编码异常，尚未来得及保存摘要，不计通过。新增check-v15-offline.py改为先落盘Markdown结果、后安全打印；85083重跑中。不得从进程已结束推断测试通过。

最新完整联合已由check-v15-offline.py保存：24文件、156 passed／586.83秒，1条既有警告，详见offline-suite-2026-10-23.md。此结果早于随后发现的历史消息详情修复；修复后只补相关专项，分开记录，不提前沿用为改后全量。

历史详情修复后：`python -m pytest backend/tests/guide/test_v15_model_calls.py -q -p no:cacheprovider`，4 passed／31.18秒，1条既有警告。含实际历史非空的REVIEW详情GET200、消息ID恢复及只读无编译；此前与usage联合1 failed／6 passed，失败为夹具错误假定历史ID1，已核实文档创建USER动作实际ID2并修正。生产选材不改，旧用量6项已通过，不机械重复。浏览器与中间诊断详见browser-phase-analysis-2026-10-23.md。
