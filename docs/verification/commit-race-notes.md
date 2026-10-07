# 真实提交与取消竞争（2026-10-08，本机日期）

范围：FE OP29；BE C03/I17 与 C07 的持久化门禁。完整重读 BE2501–2649、5173–5253，FE1249–1287；公共命令、HTTP、原生数据库/lease、ORCH、C07、前端 RunControls/动作/轮询及私有 runner 已核对。原输入未改。

固定报告 commit-race-browser-2026-10-07T16-16-28-548Z-e680fd5ddaab.json、外部命令 commit-race-command-2026-10-07T16-16-28.452412+00-00.json 和关闭库独立审计 commit-race-post-audit-2026-10-07T16-18-17.732937+00-00.json 全部通过。完整真实前端生产构建、原文 hash 校验、CLI 页面发送 REVIEW 和取消均执行。

私有 controlled-commit-race-model 明确隔离在 output/playwright 新库，仅本机 TCP 输出。程序 ORCH/v2 校验/审计/C07 自行进入真实写事务，更新 PERSISTING 后在生产验证函数前停住；没有 SQL 安装 PERSISTING 或可信结果。私有中间件仅传递 I17 请求上下文及一个非业务诊断读取。连接 trace 在该真实请求执行 BEGIN IMMEDIATE 之前记录写入竞争并放行 C07，SQLite 正常排序，C03 正常读取。三事件顺序和两个不同线程实证：C07_NATIVE_GATE_HELD（in_transaction=true，PERSISTING）→I17_NATIVE_WRITE_BEGIN（gate_held=true）→C07_NATIVE_GATE_RELEASED。事务提交前真实 I16 因 WAL 隔离仍见 VALIDATING，不能伪称浏览器读到了未提交 PERSISTING。

唯一 I17 原请求为空 body，409 STATE_CONFLICT；页面自动继续跟踪检查直到 COMPLETED/FINISHED、人工编辑重新可用、取消入口消失，没有虚假的取消成功。原 409 仍显示安全错误并提供重读，完成状态已更新。图像原字节已查看，commit-race-media/manifest.json 保存 SHA。

关闭后独立 immutable SQLite 核对：1需求/1CURRENT/1Baseline/2Run（初始化真实缺配置失败＋REVIEW完成）/1LLMUse/1本机Chat/0建议/0付费。完整 CURRENT3/Block身份/markdown/Baseline前后相同、唯一助手/真实 trusted/raw/Review结果、冻结 DeepSeek v2 输入、原始用户指令/context/read blocks/Manifest及失败取消不留成功幂等回执全部通过。库 SHA 前后未变；网络线程/transport关闭，私有函数和连接钩子已恢复。

452输入 before/after 一致；与上一批451共同输入仅私有helper变化，450生产输入不变。无生产代码修补；正常8000服务与用户库保留。既有263＋4、814及55核心沿原范围，未声称本批重跑。本批无失败；之前取消先获胜的三个实际根报告仍按其固有范围保存，不当本批重跑。OP29剩余迟到取消/等待与完整负向仍需逐项核对，正式373台账不整体升级。下一单元继续 C04/I18/OP30 的 FAILED→新Run、原触发消息复用、正常/未知原键及拒绝路径；真实模型计数/效果及人工IME/键盘独立待。
